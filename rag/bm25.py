"""BM25 内存索引：jieba 分词 + rank_bm25（T03；M3 · T3 加自定义词典臂）。

口径（m2_design.md Q4 / §1.2）：

* **内存索引**：进程重启从 ``chunks`` 表全量重建（百级 chunk 毫秒级）；
  写路径经 ``on_ready`` 回调整体重建（D2：不做增量，重建即幂等）；
* ``jieba`` / ``rank_bm25`` 只在函数体内 import（懒加载纪律 §7.4）；
* 查询返回**原始 BM25 分**（无界）——归一化在 :mod:`rag.retriever` 的
  单次查询候选集内做，不同查询之间分数不可比（§0.3 第 3 条）。

``userdict`` 口径（E-DICT 臂，m2_rag.md §7.1 的「六类线 → 六类+线」问题）：
配了词典时用**私有** :class:`jieba.Tokenizer` 实例，不碰 ``jieba.default_tokenizer``。
全局 ``jieba.load_userdict()`` 会污染同进程的所有分词，消融 runner 一趟跑多条臂时
会让"没开词典"的臂也吃到词典 —— 那种串味在报表里看不出来。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """jieba 精确模式分词 + 去空白 token（默认全局词典，M2 既有路径）。"""
    import jieba

    return [token for token in jieba.lcut(text) if token.strip()]


class BM25Index:
    """线程安全的 BM25 内存索引（RLock 内整体替换，读多写少）。"""

    def __init__(self, *, userdict: str = "") -> None:
        self._lock = threading.RLock()
        self._engine: Any | None = None
        self._chunk_ids: list[str] = []
        self._size = 0
        self._userdict = userdict.strip()
        self._tokenizer: Any | None = None

    # ------------------------------------------------------------------ #
    def _tokens(self, text: str) -> list[str]:
        """分词：无词典时走全局默认路径，有词典时走私有分词器。"""
        if not self._userdict:
            return _tokenize(text)
        return [token for token in self._ensure_tokenizer().lcut(text) if token.strip()]

    def _ensure_tokenizer(self) -> Any:
        """首次用到才建分词器（jieba 加载词典 ~0.5s，不能进构造路径）。"""
        if self._tokenizer is not None:
            return self._tokenizer
        import time
        from pathlib import Path

        import jieba

        if not Path(self._userdict).is_file():
            raise FileNotFoundError(f"jieba 自定义词典不存在：{self._userdict}")
        started = time.perf_counter()
        tokenizer = jieba.Tokenizer()
        tokenizer.load_userdict(self._userdict)
        entries = len(getattr(tokenizer, "FREQ", {}) or {})
        self._tokenizer = tokenizer
        logger.info(
            "BM25 私有分词器就绪：词典 %s（词条 %d，%.2fs）",
            self._userdict,
            entries,
            time.perf_counter() - started,
        )
        return tokenizer

    # ------------------------------------------------------------------ #
    def rebuild(self, chunks: Sequence[Any]) -> None:
        """全量重建索引。

        Args:
            chunks: 任意带 ``chunk_id`` 与 ``text`` 属性的序列
                （``rag.types.Chunk`` 与 ``storage.models.ChunkRecord`` 都可）。
        """
        if not chunks:
            with self._lock:
                self._engine = None
                self._chunk_ids = []
                self._size = 0
            return
        from rank_bm25 import BM25Okapi

        chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
        corpus = [self._tokens(str(chunk.text)) for chunk in chunks]
        engine = BM25Okapi(corpus)
        with self._lock:
            self._engine = engine
            self._chunk_ids = chunk_ids
            self._size = len(chunk_ids)
        logger.info("BM25 索引已重建：%d chunks", len(chunk_ids))

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """查询，返回 ``[(chunk_id, 原始 BM25 分)]``（分数降序；全零返回空）。"""
        if top_k < 1 or not query.strip():
            return []
        with self._lock:
            engine = self._engine
            chunk_ids = list(self._chunk_ids)
        if engine is None:
            return []
        scores = engine.get_scores(self._tokens(query))
        ranked = sorted(zip(chunk_ids, scores, strict=True), key=lambda item: item[1], reverse=True)
        return [(chunk_id, float(score)) for chunk_id, score in ranked[:top_k] if score > 0.0]

    def size(self) -> int:
        """当前索引中的 chunk 数。"""
        with self._lock:
            return self._size


__all__ = ["BM25Index"]
