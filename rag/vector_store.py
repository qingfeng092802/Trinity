"""向量存储：VectorStore 协议 + SQLiteVecStore（主）+ ChromaStore（降级）+ 工厂（T02）。

选型落点（.env T01 spike 结论）：sqlite-vec 0.1.9 在 CPython 3.14 + Windows
的加载 / vec0 建表 / 插查全部 PASS → ``vector_store_backend="sqlite-vec"`` 固化。

关键纪律（m2_design.md §7.5 / 坑速查 #2）：

* ``SQLiteVecStore`` 用**独立的裸 sqlite3 连接**打开与业务库相同的 .db 文件，
  WAL / busy_timeout / synchronous 三个 PRAGMA **必须**与 SQLAlchemy 侧对齐
  （只改一边等于没改——M1「database is locked」教训）；
* 向量以 packed float32 little-endian blob 存 vec0 虚拟表；chunk 元数据（文本、
  字符区间）在 SQLAlchemy ``chunks`` 表，两边以 ``chunk_id`` 关联（设计 A1）；
* ``query`` 返回 **cosine 相似度** = ``1 - distance``（vec0 的 MATCH 默认给
  cosine 距离），截断到 [0, 1]；
* ``chromadb`` 为降级备胎：**不在基础依赖里**，工厂只在显式配置 backend="chroma"
  且 import 成功时才实例化。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from api.constants import SQLITE_BUSY_TIMEOUT_MS
from rag.exceptions import StoreError
from rag.types import Chunk

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)

#: vec0 虚拟表名（与业务表同 .db 文件）
VEC_TABLE = "knowledge_vec"


def _float32_blob(vector: list[float]) -> bytes:
    """packed float32 little-endian（spike 验证过的 vec0 接受格式）。"""
    import struct

    return b"".join(struct.pack("<f", float(component)) for component in vector)


def _l2_distance_to_cosine(distance: float) -> float:
    """把 vec0 的 **L2** 距离换算成余弦相似度（并 clamp 进 ``[0, 1]``）。

    单位向量下 ``d = √(2 - 2·cos)`` ⇒ ``cos = 1 - d²/2``（精确，不是近似）。
    负余弦（方向相反）按老口径一样压到 0.0：这一列今天全部当"相关度"展示，
    没有下游消费者需要区分 0 与负数，改成有负值的口径会连带动
    ``retriever`` 的 min-max 与界面文案，不在这次范围内。

    ⚠️ 前提：**入库向量必须已归一化**（embedder 三条路径都保证，见
    :meth:`SQLiteVecStore.query` 的注释）。若哪天有别的写入方塞未归一化向量，
    这个换算与 L2 排序一起失效 —— 那种情况下要改的是写入侧而不是这里。
    """
    d = float(distance)
    return max(0.0, min(1.0, 1.0 - (d * d) / 2.0))


@runtime_checkable
class VectorStore(Protocol):
    """向量库的统一接口；检索层与测试桩只认这个协议。"""

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]: ...

    def delete_document(self, document_id: str) -> None: ...

    def count(self) -> int: ...

    def backend_name(self) -> str: ...

    def close(self) -> None:
        """释放连接。两个实现都有（``SQLiteVecStore`` 关 sqlite3 连接、``ChromaStore`` 空实现），
        但协议里以前没写 —— 于是任何按协议类型标注的调用方（如
        ``scripts/rebuild_vector_index.py``）拿不到这个方法，mypy 报 attr-defined。"""
        ...


class SQLiteVecStore:
    """sqlite-vec 实现：vec0 虚拟表与业务库同 .db 文件，备份 = 拷整个 data/。"""

    def __init__(self, db_path: Path, *, dim: int) -> None:
        try:
            import sqlite_vec
        except ImportError as exc:
            raise StoreError(f"sqlite-vec 未安装，无法使用 sqlite-vec 后端：{exc}") from exc
        if dim < 1:
            raise StoreError(f"向量维度非法：{dim}")
        self._dim = dim
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            # ---- 与 storage/db.py 的 SQLAlchemy 连接同口径（双连接都要设）----
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE} USING vec0("
                f"chunk_id TEXT PRIMARY KEY, embedding float[{dim}])"
            )
        except sqlite3.Error as exc:
            raise StoreError(f"sqlite-vec 初始化失败（{path}）：{exc}") from exc
        self._lock = threading.RLock()
        logger.info("SQLiteVecStore 就绪：%s（dim=%d）", path, dim)

    # -- 协议实现 --
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """批量写入；``chunk_id`` 冲突时覆盖（overwrite/重试语义）。"""
        if len(chunks) != len(vectors):
            raise StoreError(f"chunks({len(chunks)}) 与 vectors({len(vectors)}) 数量不一致")
        if not chunks:
            return
        rows = [
            (chunk.chunk_id, _float32_blob(vector))
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            with self._lock, self._conn:
                # vec0 虚拟表不支持 INSERT OR REPLACE / ON CONFLICT（shadow 表
                # 机制限制）——覆盖语义用「先删后插」在同一事务内实现。
                for chunk_id, _blob in rows:
                    self._conn.execute(
                        f"DELETE FROM {VEC_TABLE} WHERE chunk_id = ?", (chunk_id,)
                    )
                self._conn.executemany(
                    f"INSERT INTO {VEC_TABLE}(chunk_id, embedding) VALUES (?, ?)", rows
                )
        except sqlite3.Error as exc:
            raise StoreError(f"向量写入失败：{exc}") from exc

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        """KNN 查询，返回 ``[(chunk_id, cosine 相似度)]``（相似度降序）。

        ⚠️ **vec0 的 ``distance`` 是 L2 距离，不是余弦距离**，所以换算式是
        ``1 - d²/2`` 而不是 ``1 - d``（2026-10-02 修正，审查报告 Q7-01）。三条实测事实：

        1. 本机 sqlite-vec **v0.1.9** 建表不写度量时默认 L2 —— 内存表 + 单位向量实测：
           真余弦 1.0 / 0.5 / -1.0 三档的 ``distance`` 分别是 0.0 / **1.0** / 2.0；
        2. 同一个版本**不认** ``distance_metric=cosine`` 这个建表选项
           （``vec0 constructor error: Unknown table option: distance_metric``，实跑），
           所以升级不了建表语句，只能在读侧换算；
        3. 换算式成立的前提是"存进来的向量已归一化"，这一条由 embedder 保证
           （``rag/embedder.py:105-106`` / ``:217`` / ``:296-297`` 三条路径都除过模长；
           本机 ``knowledge_vec`` 的 106 条实测模长 min=max=1.000000）。

        旧写法 ``1 - d`` 的实际后果不是排序错，而是**分数塌**：单位向量下
        ``d = √(2-2cos)``，于是真余弦 ≤0.5 的候选全部被 clamp 成 0.0（cos=0.5 直接变 0.0）。
        排序本身没事（L2 与余弦在单位向量上单调等价），但融合那一档拿的是分数 ——
        大面积 0.0 并列 ⇒ 谁在前由 ``retriever.py:235`` 的"并列按 ``chunk_id`` 定序"决定，
        而界面与报告里那个"向量 x.xx"根本不是余弦。

        另一条后端 ``ChromaStore`` 的 ``1 - d`` 是**对的**（它建集合时用了
        ``hnsw:space=cosine``，chroma 给的 distance 已经是 1-cos）—— 也就是说改之前
        同一个查询在两个后端上会得到两个不同的分数。现在两边一致。
        """
        if top_k < 1:
            return []
        blob = _float32_blob(vector)
        try:
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT chunk_id, distance FROM {VEC_TABLE} "
                    f"WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                    (blob, top_k),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"向量查询失败：{exc}") from exc
        return [
            (str(chunk_id), _l2_distance_to_cosine(distance))
            for chunk_id, distance in rows
        ]

    def delete_document(self, document_id: str) -> None:
        """删除一个文档的全部向量（chunk_id 前缀匹配 ``{document_id}:``）。"""
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    f"DELETE FROM {VEC_TABLE} WHERE chunk_id LIKE ?", (f"{document_id}:%",)
                )
        except sqlite3.Error as exc:
            raise StoreError(f"向量删除失败（{document_id}）：{exc}") from exc

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(f"SELECT count(*) FROM {VEC_TABLE}").fetchone()
        return int(row[0]) if row else 0

    def backend_name(self) -> str:
        return "sqlite-vec"

    def close(self) -> None:
        """关闭独立连接（进程退出 / 测试清理用）。"""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover - 重复 close 等极端场景
                pass


class ChromaStore:
    """chromadb 降级实现（persist_dir 独立目录，不在基础依赖里）。"""

    def __init__(self, persist_dir: Path) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise StoreError(
                f"chromadb 未安装（sqlite-vec 后端不可用时的降级备选）：{exc}"
            ) from exc
        persist_dir = Path(persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            "knowledge", metadata={"hnsw:space": "cosine"}
        )
        logger.info("ChromaStore 就绪：%s", persist_dir)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=vectors,
            metadatas=[{"document_id": chunk.document_id} for chunk in chunks],
        )

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        if top_k < 1 or self._collection.count() == 0:
            return []
        result = self._collection.query(query_embeddings=[vector], n_results=top_k)
        ids = result.get("ids") or [[]]
        distances = (result.get("distances") or [[]])[0]
        return [
            (str(chunk_id), max(0.0, min(1.0, 1.0 - float(distance))))
            for chunk_id, distance in zip(ids[0], distances, strict=False)
        ]

    def delete_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return int(self._collection.count())

    def backend_name(self) -> str:
        return "chroma"

    def close(self) -> None:  # chromadb 无需显式关闭
        return


def create_vector_store(settings: "Settings", *, dim: int) -> VectorStore:
    """按 ``settings.vector_store_backend`` 构造向量库。

    Raises:
        StoreError: backend 值非法 / sqlite 主库路径不可得 / 依赖缺失。
    """
    backend = settings.vector_store_backend
    if backend == "sqlite-vec":
        db_path = settings.db_path
        if db_path is None:
            raise StoreError("DB_URL 不是 SQLite 连接串，sqlite-vec 后端不可用（可改 chroma）")
        return SQLiteVecStore(db_path, dim=dim)
    if backend == "chroma":
        return ChromaStore(Path(settings.knowledge_dir) / "chroma")
    raise StoreError(f"未知向量库后端：{backend}（支持 sqlite-vec / chroma）")


__all__ = ["ChromaStore", "SQLiteVecStore", "VectorStore", "create_vector_store"]
