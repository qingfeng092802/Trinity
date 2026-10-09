"""KnowledgeService 门面：RAG 能力的唯一编排入口（api/deps 进程内单例）。

职责（m2_design.md §3.2 / §4 图四）：

* **上传受理**：格式校验 → file_hash → 落盘 → ``documents(pending)`` → 入队；
* **文档 CRUD**：list / get / delete / retry（删除连带清 chunks + 向量）；
* **指纹双闸**：``check_fingerprint()`` 在检索入口调用，不一致 →
  :class:`FingerprintMismatchError`（API 层 409）；索引侧的闸在 IndexWorker；
* **检索**：``search()`` → HybridRetriever（BM25 + 向量融合）+ 元数据回填；
* **生命周期**：``initialize()``（开库/重启恢复/重建 BM25，**不加载模型**）与
  ``start_worker()/stop_worker()``；
* **健康检查**：``health_check()`` 三档（/health.rag 数据源；rag=fail 只贡献
  degraded 的特判由 health 路由做）。

依赖方向铁律：rag 只依赖 storage/config，禁止反向 import api/core（§1.3；
``api.constants`` 是全项目唯一常量源，与 storage 同口径引用）。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from uuid import uuid4

from api.constants import (
    DOC_FAILED,
    DOC_PENDING,
    DOC_READY,
    DOC_SUPPORTED_FORMATS,
)
from rag.bm25 import BM25Index
from rag.embedder import create_embedder, fingerprint_of
from rag.exceptions import (
    FingerprintMismatchError,
    ParserError,
    RagError,
    StoreError,
)
from rag.ingest import IndexJob, IndexWorker, recover_stale_documents
from rag.reranker import create_reranker
from rag.retriever import HybridRetriever
from rag.types import SearchHit
from rag.vector_store import VectorStore, create_vector_store

logger = logging.getLogger(__name__)

#: 上传文件名的安全化规则：去路径分隔符与控制字符
_UNSAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")

#: 库级指纹在 knowledge_meta 里的键名（与 IndexWorker 一致）
FINGERPRINT_KEY = "current_fingerprint"


def safe_filename(filename: str) -> str:
    """文件名安全化：去路径分隔符与控制字符，保留可读主体（§7.6）。"""
    cleaned = _UNSAFE_NAME_RE.sub("_", filename).strip().strip(".")
    return cleaned[:180] or "unnamed"


def supported_formats() -> list[str]:
    """这份库**当下**能收哪些格式（排序后的稳定列表）。

    R-03（2026-09-26）把白名单收成**一个来源**：这里，也就是
    ``api.constants.DOC_SUPPORTED_FORMATS``。三个消费者全部走这扇门 ——
    ① ``ingest()`` 的 422 判定、② 422 那句 message 里列的白名单、
    ③ ``overview()`` 给界面的 ``supported_formats``（前端拿它填 ``<input accept>``
    和"支持 …"那句文案，不再自带一份清单）。

    ⚠️ 以前 ② 里写的是字面量 ``pdf/md/txt`` —— 常量一改那句话就开始说谎
    （HEAD 上常量是五种，而文案已经印成三种）。所以**别在 message 里再抄一遍清单**，
    也别在 ``if`` 的判定里用另一份集合：判定与解释必须是同一个数。
    每次调用现读模块全局（不是 import 时固化），这样测试可以换常量验"跟着变"。
    """
    return sorted(DOC_SUPPORTED_FORMATS)


class KnowledgeService:
    """知识库门面（一个进程一个实例；``api/deps`` 懒加载装配）。"""

    def __init__(self, *, settings, database) -> None:
        self.settings = settings
        self.database = database
        self._worker: IndexWorker | None = None
        self._store: VectorStore | None = None
        self._embedder = None
        self._bm25 = BM25Index(userdict=settings.jieba_userdict)
        self._retriever: HybridRetriever | None = None
        self._degraded_reason: str | None = None

    # ------------------------------------------------------------ 生命周期 --
    def initialize(self) -> None:
        """开向量库 / 重启恢复 / 指纹基线 / BM25 重建。**不加载 embedding 模型**。"""
        self.settings.ensure_dirs()
        self._degraded_reason = None
        try:
            self._store = create_vector_store(self.settings, dim=self.settings.embedding_dim)
        except StoreError as exc:
            # D3：RAG 故障不拖垮平台——store 起不来只降级，health 汇报 fail
            self._store = None
            self._degraded_reason = str(exc)
            logger.error("向量库初始化失败（服务降级）：%s", exc)
        try:
            self._embedder = create_embedder(self.settings)
        except Exception as exc:  # noqa: BLE001 - 依赖缺失也只降级
            self._embedder = None
            self._degraded_reason = f"embedder 构造失败：{exc}"
            logger.error("embedder 构造失败（服务降级）：%s", exc)

        recovered = recover_stale_documents(self.database)
        if recovered:
            logger.warning("initialize：恢复 %d 份中断文档（已标 failed，可重试）", recovered)
        self._ensure_fingerprint_baseline()
        self.rebuild_bm25()
        self._build_retriever()

    def _build_retriever(self) -> None:
        """检索器装配：store/embedder 就绪才建；否则保持 None（检索 503）。"""
        if self._store is None or self._embedder is None:
            self._retriever = None
            return
        self._retriever = HybridRetriever(
            embedder=self._embedder,
            store=self._store,
            bm25=self._bm25,
            bm25_weight=self.settings.bm25_weight,
            vector_weight=self.settings.vector_weight,
            fusion=self.settings.hybrid_fusion,
            rrf_k=self.settings.rrf_k,
            reranker=create_reranker(self.settings.reranker_model),
        )

    def _ensure_fingerprint_baseline(self) -> None:
        """库级指纹基线：已有 ready 文档但 meta 缺失时，以当前配置补齐。"""
        if self.database.get_meta(FINGERPRINT_KEY) is not None:
            return
        ready_docs = self.database.list_documents(statuses=[DOC_READY])
        if not ready_docs:
            return
        fingerprint = fingerprint_of(
            self.settings.embedding_model_name, self.settings.embedding_dim
        )
        self.database.set_meta(FINGERPRINT_KEY, fingerprint)
        logger.info("补齐库级指纹基线：%s（%d 份 ready 文档）", fingerprint, len(ready_docs))

    def rebuild_bm25(self, *_args: object) -> None:
        """从 ``chunks`` 表全量重建 BM25 索引（毫秒级；on_ready 回调复用本方法）。"""
        try:
            self._bm25.rebuild(self.database.list_all_chunks())
        except Exception as exc:  # noqa: BLE001 - BM25 重建失败不拖垮索引主流程
            logger.error("BM25 重建失败（检索将只有向量路）：%s", exc)

    def start_worker(self) -> None:
        """启动索引线程（幂等；store/embedder 不可用时不启动，保持降级）。"""
        if self._store is None or self._embedder is None:
            logger.warning("向量库或 embedder 不可用，索引 worker 不启动（降级模式）")
            return
        if self._worker is None:
            self._worker = IndexWorker(
                settings=self.settings,
                database=self.database,
                embedder=self._embedder,
                store=self._store,
                on_ready=self.rebuild_bm25,
            )
        self._worker.start()

    def stop_worker(self) -> None:
        """停止索引线程（进程退出用；幂等）。"""
        if self._worker is not None:
            self._worker.stop()
            logger.info("IndexWorker 已停止")

    # ------------------------------------------------------------ 上传受理 --
    def ingest(self, filename: str, file_path: Path, *, overwrite: bool) -> dict:
        """上传受理：校验 → 落盘 → ``documents(pending)`` → 入队。

        Args:
            filename: 原始文件名（决定格式白名单与展示）。
            file_path: 已保存到临时位置的上传文件（本方法会拷贝到正式位置）。
            overwrite: 同名文档已存在时是否覆盖重建。

        Returns:
            ``{"document_id", "filename", "status", "warnings"}`` 摘要
            （DocumentUploadResponse 的数据源）。

        Raises:
            ParserError: 格式不支持（路由层 422 unsupported_format）。
            RagError: 同名冲突（409）/ 队列满或服务未就绪（429/503）。
        """
        extension = Path(filename).suffix.lstrip(".").lower()
        if extension not in DOC_SUPPORTED_FORMATS:
            # 白名单从 supported_formats() 现取，**不在文案里抄第二份**（R-03）。
            # 判定与解释必须同源：否则改常量之后"拒了你"和"说能收你"会同时出现。
            whitelist = "/".join(supported_formats())
            raise ParserError(f"不支持的文档格式：.{extension}（白名单：{whitelist}）")

        warnings: list[str] = []
        existing = self.database.find_document_by_filename(filename)
        if existing is not None:
            if not overwrite:
                raise RagError(f"同名文档已存在：{filename}（?overwrite=true 可覆盖）", stage="queue")
            self._purge_document(existing.document_id, delete_record=True)
            warnings.append(f"同名文档已存在且 overwrite=true，旧索引已清除（{existing.document_id}）")

        file_hash = self._hash_file(file_path)
        document_id = f"doc-{uuid4().hex[:12]}"
        target = self.settings.knowledge_dir / "files" / f"{document_id}_{safe_filename(filename)}"
        target.parent.mkdir(parents=True, exist_ok=True)
        file_size = target.write_bytes(Path(file_path).read_bytes())

        record = self.database.save_document(
            document_id=document_id,
            filename=filename,
            file_path=str(target),
            size_bytes=int(file_size),
            format=extension,
            file_hash=file_hash,
            status=DOC_PENDING,
        )
        job = IndexJob(document_id=document_id, file_path=target, overwrite=bool(existing))
        if self._worker is None or not self._worker.enqueue(job):
            # 队列满 / worker 未启动：回滚记录与文件，调用方翻译成 429/503
            self.database.delete_document(document_id)
            target.unlink(missing_ok=True)
            raise RagError("索引队列已满或服务未就绪，请稍后重试", stage="queue")
        logger.info("上传受理：%s → %s（%d bytes）", filename, document_id, file_size)
        return {
            "document_id": document_id,
            "filename": record.filename,
            "status": record.status,
            "warnings": warnings,
        }

    # ------------------------------------------------------------ 查询/管理 --
    def get_document(self, document_id: str):
        """按 id 取文档记录（不存在返回 None，路由层 404）。"""
        return self.database.get_document(document_id)

    def list_documents(self, *, statuses=None) -> list:
        """文档列表（创建时间倒序）。"""
        return self.database.list_documents(statuses=statuses)

    def delete_document(self, document_id: str) -> bool:
        """删除文档：chunks 元数据 + 向量 + 记录连带清理（指纹基线不动）。"""
        record = self.database.get_document(document_id)
        if record is None:
            return False
        self._purge_document(document_id, delete_record=True)
        self.rebuild_bm25()
        logger.info("文档已删除：%s", document_id)
        return True

    def retry_document(self, document_id: str):
        """失败文档重试：``failed → pending`` 并重新入队（从 parsing 全量重跑，A4）。"""
        record = self.database.get_document(document_id)
        if record is None:
            raise RagError(f"文档不存在：{document_id}", stage="unknown")
        if record.status != DOC_FAILED:
            raise RagError(f"仅 failed 文档可重试（当前 {record.status}）", stage="queue")
        if not self.database.reset_document_pending(document_id, from_statuses=(DOC_FAILED,)):
            raise RagError("重试状态竞争，请刷新后重试", stage="queue")
        job = IndexJob(document_id=document_id, file_path=Path(record.file_path), overwrite=True)
        if self._worker is None or not self._worker.enqueue(job):
            self.database.mark_document_failed(
                document_id, stage="queue", message="索引队列已满或服务未就绪，重试未受理"
            )
            raise RagError("索引队列已满或服务未就绪", stage="queue")
        return self.database.get_document(document_id)

    def overview(self) -> dict:
        """知识库概览（GET /knowledge/overview 与控制台数据源）。"""
        documents = self.database.list_documents()
        counts = {"ready": 0, "failed": 0, "indexing": 0}
        token_count = 0
        from api.constants import DOC_INDEXING_STATUSES

        for record in documents:
            if record.status == DOC_READY:
                counts["ready"] += 1
                token_count += int(record.token_count)
            elif record.status == DOC_FAILED:
                counts["failed"] += 1
            elif record.status in DOC_INDEXING_STATUSES:
                counts["indexing"] += 1
        return {
            "document_count": len(documents),
            "chunk_count": self.database.count_chunks(),
            "token_count": token_count,
            "ready_count": counts["ready"],
            "failed_count": counts["failed"],
            "indexing_count": counts["indexing"],
            "fingerprint": self.database.get_meta(FINGERPRINT_KEY) or "",
            "vector_backend": self._store.backend_name() if self._store else "",
            "embedding_model": self.settings.embedding_model_name,
            "last_indexed_at": max(
                (record.indexed_at for record in documents if record.indexed_at is not None),
                default=None,
            ),
            # R-03：白名单随概览一起出，界面就不必自带一份清单（与 K3 的 max_file_mb 同形状）。
            # 值来自 ``api.constants.DOC_SUPPORTED_FORMATS``，每次现算 —— 常量改了这里就跟着改。
            "supported_formats": supported_formats(),
        }

    # ------------------------------------------------------------ 指纹闸 --
    def check_fingerprint(self) -> str:
        """检索入口指纹闸：库级指纹 vs 当前配置，不一致 → 拒绝（Q7）。

        Returns:
            当前配置的指纹（一致时）。

        Raises:
            FingerprintMismatchError: 换模型后未重索引（API 层 409）。
        """
        expected = fingerprint_of(
            self.settings.embedding_model_name, self.settings.embedding_dim
        )
        stored = self.database.get_meta(FINGERPRINT_KEY)
        if stored is not None and stored != expected:
            raise FingerprintMismatchError(
                f"embedding 模型指纹不匹配（库 {stored} ≠ 配置 {expected}），请全量重索引后重试"
            )
        return expected

    def reindex_all(self) -> int:
        """全量重索引：把全部 ready/failed 文档复位为 pending 并重新入队。"""
        queued = 0
        for record in self.database.list_documents(statuses=[DOC_READY, DOC_FAILED]):
            if not self.database.reset_document_pending(
                record.document_id, from_statuses=(record.status,)
            ):
                continue
            if self._worker is not None and self._worker.enqueue(
                IndexJob(
                    document_id=record.document_id,
                    file_path=Path(record.file_path),
                    overwrite=True,
                )
            ):
                queued += 1
        logger.info("全量重索引入队：%d 份文档", queued)
        return queued

    # ------------------------------------------------------------ 检索 --
    def search(self, query: str, top_k: int, *, weights: tuple[float, float] | None = None) -> list[SearchHit]:
        """混合检索：指纹闸 → 空库短路 → HybridRetriever。

        Raises:
            RagError: 服务降级不可检索（stage=retrieval，路由层 503）。
            FingerprintMismatchError: 模型指纹不一致（路由层 409）。
        """
        cleaned = query.strip()
        if not cleaned:
            raise RagError("检索问题不能为空", stage="retrieval")
        if self._retriever is None or self._store is None or self._embedder is None:
            raise RagError(
                f"知识库服务不可用：{self._degraded_reason or '组件未初始化'}", stage="retrieval"
            )
        self.check_fingerprint()
        if self._bm25.size() == 0 and self._store.count() == 0:
            return []  # 空库不是错误（PRD P0-4 验收 3）
        return self._retriever.search(
            cleaned, top_k, weights=weights, metadata_loader=self._load_hit_metadata
        )

    def _load_hit_metadata(self, chunk_ids: list[str]) -> dict[str, SearchHit]:
        """把命中 chunk 的文本/位置/文档名批量回填进 ``SearchHit`` 模板。"""
        result: dict[str, SearchHit] = {}
        records = self.database.get_chunks(chunk_ids)
        if not records:
            return result
        document_names: dict[str, str] = {}
        for record in records:
            if record.document_id not in document_names:
                document = self.database.get_document(record.document_id)
                document_names[record.document_id] = document.filename if document else record.document_id
            result[record.chunk_id] = SearchHit(
                chunk_id=record.chunk_id,
                score=0.0,
                document_id=record.document_id,
                document_name=document_names[record.document_id],
                chunk_seq=record.seq,
                start_char=record.start_char,
                end_char=record.end_char,
                text=record.text,
            )
        return result

    # ------------------------------------------------------------ 健康检查 --
    def health_check(self) -> tuple[str, str]:
        """``("ok"|"degraded"|"fail", detail)``——/health.rag 的数据源。

        注意：rag=fail 在 health 路由里被特判为**只贡献 degraded**（永不
        unhealthy，与 redis 同口径）。
        """
        if self._store is None or self._embedder is None:
            return "fail", self._degraded_reason or "RAG 组件未初始化"
        ok, detail = self._embedder.health_check()
        if not ok:
            return "fail", detail
        pending = self._worker.pending_count() if self._worker else 0
        if pending >= self.settings.knowledge_queue_max_size:
            return "degraded", f"索引队列已满（{pending}）"
        return "ok", f"向量库 {self._store.backend_name()}；{detail}"

    def store_count(self) -> int:
        """向量库当前向量总数（自检用；store 不可用时返回 -1）。"""
        if self._store is None:
            return -1
        try:
            return self._store.count()
        except StoreError:
            return -1

    # ------------------------------------------------------------ 内部工具 --
    @staticmethod
    def _hash_file(file_path: Path) -> str:
        """sha256 文件内容（§7.6：overwrite 判断与去重跳过）。"""
        digest = hashlib.sha256()
        with Path(file_path).open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    def _purge_document(self, document_id: str, *, delete_record: bool) -> None:
        """清一个文档的全部痕迹：chunks 表 + 向量 +（可选）记录与磁盘原件。

        ⚠️ 磁盘原件**只在 `delete_record=True` 时删**。这个条件是语义条件不是顺手写的：
        调用方只有两条用户路径（同名覆盖 `ingest` 里那条、`delete_document`），
        而"重建索引但保留记录"这类调用（`delete_record=False`）下一步就要拿同一个文件
        重新解析 —— 那种路径删文件等于把待索引的输入删了。以后加调用方时先看这一位。
        """
        # 记录一旦删掉就拿不到 file_path 了，所以**先取后删**。
        record = self.database.get_document(document_id) if delete_record else None
        self.database.delete_chunks(document_id)
        if self._store is not None:
            try:
                self._store.delete_document(document_id)
            except StoreError as exc:  # 清理失败不阻断记录删除
                logger.warning("向量清理失败（doc=%s）：%s", document_id, exc)
        if delete_record:
            self.database.delete_document(document_id)
            self._unlink_original(document_id, record)

    def _unlink_original(self, document_id: str, record) -> None:
        """删记录时连带删磁盘原件（KB-01）。

        为什么必须跟着删：入队失败的回滚路径（`ingest` 里那句 `target.unlink`）本来就是删文件的，
        而删除 / 覆盖这两条**用户路径**以前只清库不删文件 ⇒ 库里少一行、磁盘多一个孤儿。
        实测证据（2026-09-25）：`data/knowledge/files/` 有 7 个文件，`documents` 表只有 4 行，
        三个 `fmt_smoke` 孤儿的 `document_id` 在两个库里都查不到。
        症状是"不报错只留垃圾"：界面看不出任何异常，磁盘单向增长。

        ⚠️ 两道校验缺一不可 —— `file_path` 是**库里存的字符串**，不是当场拼出来的：
        ① 必须落在 `knowledge_dir/files/` 之下（`resolve()` 之后比前缀，挡 `..` 与符号链接）；
        ② 文件名必须以 `{document_id}_` 开头（挡一条被改坏的记录指向别人的原件）。
        任何一道不过就只警告、不删：**宁可留孤儿，不可误删** ——
        孤儿是磁盘垃圾，误删是把用户还在用的原件干掉。
        """
        if record is None or not getattr(record, "file_path", None):
            return
        files_dir = (self.settings.knowledge_dir / "files").resolve()
        path = Path(record.file_path)
        try:
            resolved = path.resolve()
        except OSError as exc:  # 路径本身就读不了（非法字符等），当作不可删处理
            logger.warning("原件路径无法解析，跳过删除（doc=%s）：%s", document_id, exc)
            return
        if resolved.parent != files_dir or not resolved.name.startswith(f"{document_id}_"):
            logger.warning(
                "原件不在知识库目录 / 前缀与 document_id 不符，拒绝删除（doc=%s）：%s",
                document_id,
                resolved,
            )
            return
        try:
            resolved.unlink(missing_ok=True)
        except OSError as exc:  # 只读挂载 / 占用中：记录已删，磁盘留孤儿，但要说出来
            logger.warning("原件删除失败（doc=%s）：%s", document_id, exc)


__all__ = ["KnowledgeService", "safe_filename"]
