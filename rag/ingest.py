"""索引 worker：专职单线程、五阶段状态机、逐文档失败隔离（T02）。

设计要点（m2_design.md §1.1 D1/D2 / §3.2 / §5 T02 子步骤 5）：

* **不占用 M1 任务队列的 3 个并发槽位**（索引是分钟级长任务，会饿死 Agent
  任务）——独立 ``queue.Queue`` + daemon 线程，进程内跑；
* 状态推进**只经** ``Database.mark_document_stage/ready/failed`` 的 CAS 通道
  （§7.2：迁移唯一入口，路由层禁止绕过）；CAS 返回 ``False``（已被并发删除/
  改动）→ 立即放弃本次处理；
* 逐文档 try/except：任何异常编码进 ``error_stage/error_message``，**绝不冒泡**，
  worker 主循环永远继续下一个 job；
* ``file_hash`` 去重：内容相同且已有 ``ready`` 文档 → 本文档标 ``failed(dedup)``
  并 WARNING（可见、可重试，不产生幽灵重复索引）；
* 指纹双闸之「索引入口」：库级指纹已存在且与本 embedder 不一致 → 拒绝索引
  （提示全量重索引）；库级为空（首批文档）→ 写入库级指纹；
* ``on_ready`` 回调：T03 的 ``KnowledgeService`` 用它触发 BM25 增量重建；
* ``recover_stale_documents``：进程崩溃残留的 in-flight 文档在下次启动统一标
  ``failed(queue, 进程重启中断)``——标记失败而非断点续跑（§0.3 第 4 条）。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from api.constants import (
    DOC_CHUNKING,
    DOC_EMBEDDING,
    DOC_INDEXING_STATUSES,
    DOC_PARSING,
)
from rag.exceptions import RagError
from rag.parsers import parse
from rag.splitter import DocumentSplitter

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import Settings
    from storage.db import Database

    from rag.embedder import EmbeddingProvider
    from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndexJob:
    """一条索引请求。

    Attributes:
        document_id: 目标文档 id。
        file_path: 已落盘的源文件路径（上传路由负责保存）。
        overwrite: 内容去重是否豁免（覆盖上传时为 ``True``，同内容也重索引）。
    """

    document_id: str
    file_path: Path
    overwrite: bool = False


class IndexWorker:
    """专职单线程索引器：parse → chunk → embed → store → ready。"""

    def __init__(
        self,
        *,
        settings: "Settings",
        database: "Database",
        embedder: "EmbeddingProvider",
        store: "VectorStore",
        on_ready: "callable | None" = None,  # noqa: UP037 - 保持可读的回调签名
    ) -> None:
        self._settings = settings
        self._database = database
        self._embedder = embedder
        self._store = store
        self._on_ready = on_ready
        self._splitter = DocumentSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            mode=settings.chunk_mode,
            embedder=embedder,
        )
        self._queue: queue.Queue[IndexJob | None] = queue.Queue(
            maxsize=settings.knowledge_queue_max_size
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ 生命周期 --
    def start(self) -> None:
        """启动后台索引线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="index-worker", daemon=True)
        self._thread.start()
        logger.info("IndexWorker 已启动（专职单线程）")

    def stop(self, timeout: float = 5.0) -> None:
        """请求停止：置位事件 + 投递哨兵；等待当前 job 收尾（最多 ``timeout`` 秒）。"""
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)  # 哨兵：正在阻塞 get 的线程立即醒
        except queue.Full:  # pragma: no cover - 队列满时事件位已足够
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("IndexWorker 已停止")

    # ------------------------------------------------------------ 队列操作 --
    def enqueue(self, job: IndexJob) -> bool:
        """入队一条索引请求；满队列返回 ``False``（API 层翻译成 429）。"""
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            logger.warning("索引队列已满（容量 %d），拒绝 %s", self._queue.maxsize, job.document_id)
            return False
        return True

    def pending_count(self) -> int:
        """排队中的 job 数（含正在处理的一个）。"""
        return self._queue.qsize()

    # ------------------------------------------------------------ 主循环 --
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:  # 哨兵
                break
            try:
                self._process(job)
            except Exception as exc:  # noqa: BLE001 - 主循环兜底：worker 永不因单个文档死亡
                logger.exception("索引 job 处理兜底异常（%s）：%s", job.document_id, exc)
                try:
                    self._database.mark_document_failed(
                        job.document_id, stage="unknown", message=f"索引器内部异常：{exc}"
                    )
                except Exception:  # pragma: no cover - DB 也不可用时只能放弃
                    logger.exception("失败状态落库也失败（%s）", job.document_id)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------ 单文档流水线 --
    def _process(self, job: IndexJob) -> None:
        db = self._database
        record = db.get_document(job.document_id)
        if record is None:
            logger.warning("索引目标不存在，跳过：%s", job.document_id)
            return
        if not Path(job.file_path).is_file():
            db.mark_document_failed(job.document_id, stage="parsing", message=f"源文件丢失：{job.file_path}")
            return

        # ---- file_hash 去重（overwrite 豁免）----
        if not job.overwrite and record.file_hash:
            duplicate = db.find_document_by_hash(record.file_hash)
            if duplicate is not None and duplicate.document_id != job.document_id:
                db.mark_document_failed(
                    job.document_id,
                    stage="dedup",
                    message=f"内容与已索引文档 {duplicate.document_id}（{duplicate.filename}）重复，已跳过索引",
                )
                logger.warning(
                    "跳过重复文档 %s（与 %s 同 file_hash）", job.document_id, duplicate.document_id
                )
                return

        # ---- 指纹闸（索引入口）----
        fingerprint = self._embedder.fingerprint()
        library_fingerprint = db.get_meta("current_fingerprint")
        if library_fingerprint and library_fingerprint != fingerprint:
            db.mark_document_failed(
                job.document_id,
                stage="embedding",
                message=(
                    f"embedding 模型指纹不匹配（库级 {library_fingerprint} ≠ 当前 {fingerprint}），"
                    "请删除后重新上传或触发全量重索引"
                ),
            )
            logger.warning("指纹不匹配，拒绝索引 %s", job.document_id)
            return

        # ---- 阶段 1：parsing ----
        if not db.mark_document_stage(job.document_id, DOC_PARSING):
            logger.info("文档状态已被并发改动，放弃：%s", job.document_id)
            return
        try:
            parsed = parse(job.file_path, job.document_id)
        except RagError as exc:
            self._fail(job.document_id, exc)
            return
        except Exception as exc:  # noqa: BLE001
            self._fail(job.document_id, RagError(f"解析器异常：{exc}", stage="parsing"))
            return

        # ---- 阶段 2：chunking ----
        if not db.mark_document_stage(job.document_id, DOC_CHUNKING):
            logger.info("文档状态已被并发改动，放弃：%s", job.document_id)
            return
        try:
            chunks = self._splitter.split(parsed)
        except RagError as exc:
            self._fail(job.document_id, exc)
            return
        if not chunks:
            self._fail(job.document_id, RagError("切分后无有效内容", stage="chunking"))
            return
        import json as _json

        db.save_chunks(
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "seq": chunk.seq,
                    "text": chunk.text,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
                    "token_estimate": chunk.token_estimate,
                }
                for chunk in chunks
            ]
        )

        # ---- 阶段 3：embedding + 入库 ----
        if not db.mark_document_stage(job.document_id, DOC_EMBEDDING):
            logger.info("文档状态已被并发改动，放弃：%s", job.document_id)
            return
        try:
            # 重索引/重试前先清旧向量（save_chunks 已清旧元数据）
            self._store.delete_document(job.document_id)
            vectors = self._embedder.embed([chunk.text for chunk in chunks])
            self._store.add(chunks, vectors)
        except RagError as exc:
            self._fail(job.document_id, exc)
            return
        except Exception as exc:  # noqa: BLE001
            self._fail(job.document_id, RagError(f"向量化/入库异常：{exc}", stage="embedding"))
            return

        # ---- 阶段 4：ready ----
        if not db.mark_document_ready(
            job.document_id,
            fingerprint=fingerprint,
            chunk_count=len(chunks),
            token_count=sum(chunk.token_estimate for chunk in chunks),
        ):
            logger.info("ready 落库失败（已被并发改动）：%s", job.document_id)
            return
        if not library_fingerprint:
            db.set_meta("current_fingerprint", fingerprint)
            logger.info("库级 embedding 指纹已初始化：%s", fingerprint)
        logger.info(
            "索引完成 %s：%d chunks / %d tokens",
            job.document_id,
            len(chunks),
            sum(chunk.token_estimate for chunk in chunks),
        )
        if self._on_ready is not None:
            try:
                self._on_ready(job.document_id)
            except Exception:  # noqa: BLE001 - 回调故障不影响索引结果
                logger.exception("on_ready 回调异常（%s）", job.document_id)

    def _fail(self, document_id: str, exc: RagError) -> None:
        """编码失败状态（文档级失败隔离，不影响 worker 存活）。"""
        logger.error("索引失败 %s：%s", document_id, exc)
        self._database.mark_document_failed(document_id, stage=exc.stage, message=exc.message)


# --------------------------------------------------------------------------- #
# 重启恢复
# --------------------------------------------------------------------------- #
def recover_stale_documents(database: "Database") -> int:
    """把上次进程残留的 in-flight 文档统一标 ``failed(queue)``。

    由 ``KnowledgeService.initialize()`` 在启动时调用（设计 §4 图四）。

    Returns:
        被标记的文档数。
    """
    stale = database.list_documents(statuses=list(DOC_INDEXING_STATUSES))
    for record in stale:
        database.mark_document_failed(
            record.document_id, stage="queue", message="进程重启中断索引，可重试"
        )
    if stale:
        logger.warning("重启恢复：%d 个 in-flight 文档已标记失败（可重试）", len(stale))
    return len(stale)


__all__ = ["IndexJob", "IndexWorker", "recover_stale_documents"]
