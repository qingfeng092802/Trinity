"""混合检索：双路召回 → 融合（min-max 加权 / RRF）→ 可选精排 → 元数据回填（T03，M3 · T3 扩展）。

融合口径（m2_design.md D4 / §0.3 第 3 条 / Q8，m3_design.md §4.1）：

* ``fusion="weighted"``（M2 默认，行为逐位不变）：BM25 原始分无界、cosine 有界，量纲不同
  → **每路各自在本次查询的候选集内 min-max 归一化到 [0,1]**，再加权求和（默认 0.4 / 0.6）；
* ``fusion="rrf"``（M3 新增臂）：只用秩 ``Σ 1/(k+rank)``，不做归一化，绕开 min-max 的
  「跨查询不可比」限制；结果仍映射到 ``score`` 上（除以本次最大值，使首位 = 1.0），
  RRF 原始值单独记在 ``SearchHit.rrf_score``；
* ``fusion="bm25_only"`` / ``"vector_only"``（M3 单路对照臂）：只保留该路候选，
  ``score`` 即该路的 min-max 归一分（另一路 ``*_score`` 仍照常填，便于对照诊断）；
  此模式下 ``weights`` 不参与计算；
* 两路各召回 ``top_k × candidate_multiplier`` 条，保证融合池有交集；
* 融合分是**相对分**：只用于同一次查询结果内部的排序，跨查询不可比；
* 单路无候选（如纯数值查询 BM25 全零）→ 该路归一化分记 0，不影响另一路。

精排口径（m3_design.md §4.2）：``reranker`` 作用在**截断之前的 candidate pool**
（``fetch_k=20 → top_k=5``）上，故元数据先按整池回填。``score`` 语义不变（仍是融合分），
精排分单独记在 ``SearchHit.rerank_score``，但**返回列表顺序就是精排后的顺序**。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Literal

from rag.types import SearchHit

if TYPE_CHECKING:
    from rag.bm25 import BM25Index
    from rag.embedder import EmbeddingProvider
    from rag.reranker import Reranker
    from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

#: metadata_loader 的返回：chunk_id → 预填好的 SearchHit（text/位置/文档信息）
MetadataLoader = Callable[[list[str]], dict[str, SearchHit]]

#: 融合模式。``weighted`` 是 M2 既有口径；``rrf`` 与两个单路口径是 M3 消融臂。
#: 取值与 ``evaluation.experiment.Arm.fusion`` **逐字一致** —— runner 把臂上的值原样传进来，
#: 中间不放映射表（映射表会和矩阵漂移：矩阵里 ``fusion: bm25_only`` 拼错一次就废一个臂）。
FusionMode = Literal["weighted", "rrf", "bm25_only", "vector_only"]

_FUSION_MODES: frozenset[str] = frozenset({"weighted", "rrf", "bm25_only", "vector_only"})

#: RRF 平滑常数（原文取 60）：k 越大越弱化头部名次的优势
DEFAULT_RRF_K = 60


def _min_max(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """候选集内 min-max 归一化；极差为 0（全部同分）时全给 1.0。"""
    if not pairs:
        return {}
    values = [score for _, score in pairs]
    low, high = min(values), max(values)
    span = high - low
    if span <= 1e-12:
        return {chunk_id: 1.0 for chunk_id, _ in pairs}
    return {chunk_id: (score - low) / span for chunk_id, score in pairs}


def rrf_scores(id_lists: list[list[str]], *, k: int = DEFAULT_RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion：同名 chunk 在几路里出现就累加几路的倒数名次。

    只用秩不用分数，所以两路的分数量纲、是否召回同样多的候选都不影响结果 ——
    这正是它与 min-max 加权的可比性差异所在（E2a 要测的就是这个）。
    """
    scores: dict[str, float] = {}
    for ids in id_lists:
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    """双路召回 + 融合 + 可选精排；``SearchHit`` 元数据由 ``metadata_loader`` 回填。"""

    def __init__(
        self,
        *,
        embedder: "EmbeddingProvider",
        store: "VectorStore",
        bm25: "BM25Index",
        bm25_weight: float,
        vector_weight: float,
        candidate_multiplier: int = 4,
        fusion: FusionMode = "weighted",
        rrf_k: int = DEFAULT_RRF_K,
        reranker: "Reranker | None" = None,
    ) -> None:
        if candidate_multiplier < 1:
            raise ValueError(f"candidate_multiplier 必须 ≥ 1，收到 {candidate_multiplier}")
        if fusion not in _FUSION_MODES:
            raise ValueError(f"fusion 只支持 {sorted(_FUSION_MODES)}，收到 {fusion!r}")
        if rrf_k < 0:
            raise ValueError(f"rrf_k 必须 ≥ 0，收到 {rrf_k}")
        self._embedder = embedder
        self._store = store
        self._bm25 = bm25
        self._bm25_weight = bm25_weight
        self._vector_weight = vector_weight
        self._multiplier = candidate_multiplier
        self._fusion = fusion
        self._rrf_k = rrf_k
        self._reranker = reranker

    # ------------------------------------------------------------------ #
    def search(
        self,
        query: str,
        top_k: int,
        *,
        weights: tuple[float, float] | None = None,
        fusion: FusionMode | None = None,
        metadata_loader: MetadataLoader | None = None,
    ) -> list[SearchHit]:
        """主入口：召回 → 融合 → 精排 → 回填。

        Args:
            query: 检索问题（调用方保证 strip 后非空）。
            top_k: 最终返回条数。
            weights: ``(bm25_weight, vector_weight)``；``None`` 取构造时配置。
                允许 ``(1,0)`` / ``(0,1)`` 做单路对照（评测用，仅 ``weighted`` 生效）。
            fusion: 单次调用的融合模式覆盖；``None`` 取构造时配置（评测 runner 复用
                同一个实例跑多个融合臂用）。
            metadata_loader: 从存储回填 chunk 元数据的回调（service 注入）。
                收到的是**整个候选池**（精排需要 text），返回条数仍受 ``top_k`` 限制。

        Returns:
            排序后的 ``SearchHit`` 列表（≤ top_k 条）：无精排时按融合分降序，
            有精排时按精排分降序。
        """
        if top_k < 1 or not query.strip():
            return []
        w_bm25, w_vector = weights if weights is not None else (self._bm25_weight, self._vector_weight)
        candidate_k = max(top_k * self._multiplier, top_k)

        # ---- 双路召回 ----
        bm25_raw = self._bm25.search(query, candidate_k)
        vector_raw = self._query_vector_path(query, candidate_k)

        # ---- 各路归一化（候选集内；weighted 用，同时作为诊断字段两路分）----
        bm25_norm = _min_max(bm25_raw)
        vector_norm = _min_max(vector_raw)

        # ---- 融合（整池，未截断）----
        fused = self._fuse(
            fusion or self._fusion,
            bm25_raw,
            vector_raw,
            bm25_norm,
            vector_norm,
            w_bm25,
            w_vector,
        )
        if not fused:
            return []

        # ---- 元数据回填（精排要看 text，所以先回填整池）----
        base: dict[str, SearchHit] = {}
        if metadata_loader is not None:
            base = metadata_loader([chunk_id for chunk_id, _, _ in fused])
        hits = [
            self._to_hit(chunk_id, score, rrf_raw, bm25_norm, vector_norm, base.get(chunk_id))
            for chunk_id, score, rrf_raw in fused
        ]

        # ---- 精排（截断之前；无该阶段则直接截断）----
        if self._reranker is not None:
            hits = self._reranker.rerank(query, hits, top_n=top_k)
        else:
            hits = hits[:top_k]
        logger.debug(
            "混合检索完成：%r → %d 命中（fusion=%s，BM25 路 %d / 向量路 %d）",
            query[:40],
            len(hits),
            fusion or self._fusion,
            len(bm25_raw),
            len(vector_raw),
        )
        return hits

    # ------------------------------------------------------------------ #
    def _query_vector_path(self, query: str, candidate_k: int) -> list[tuple[str, float]]:
        """向量路召回：嵌入故障降级为纯 BM25（M2 口径，不让嵌入故障中断在线检索）。

        与 ``RerankerError`` 的「臂级失败要整体失败」纪律刻意不同 —— 这里是线上服务
        路径（D3：RAG 故障不拖垮平台），消融 runner 走的是另一条显式失败路径。
        """
        try:
            query_vector = self._embedder.embed([query])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("查询向量化失败，本查询降级为纯 BM25：%s", exc)
            return []
        return self._store.query(query_vector, candidate_k)

    def _fuse(
        self,
        mode: FusionMode,
        bm25_raw: list[tuple[str, float]],
        vector_raw: list[tuple[str, float]],
        bm25_norm: dict[str, float],
        vector_norm: dict[str, float],
        w_bm25: float,
        w_vector: float,
    ) -> list[tuple[str, float, float | None]]:
        """融合整池并按分降序，返回 ``(chunk_id, 归一融合分, RRF 原始分)``。

        并列一律以 ``chunk_id`` 升序定序（确定性要求：消融重跑必须逐位复现）。
        """
        fused: list[tuple[str, float, float | None]]
        if mode == "rrf":
            raw = rrf_scores(
                [[chunk_id for chunk_id, _ in bm25_raw], [chunk_id for chunk_id, _ in vector_raw]],
                k=self._rrf_k,
            )
            peak = max(raw.values()) if raw else 0.0
            fused = [
                (chunk_id, score / peak if peak > 0 else 0.0, score)
                for chunk_id, score in raw.items()
            ]
        elif mode in {"bm25_only", "vector_only"}:
            norm = bm25_norm if mode == "bm25_only" else vector_norm
            fused = [(chunk_id, score, None) for chunk_id, score in norm.items()]
        else:
            fused = [
                (
                    chunk_id,
                    w_bm25 * bm25_norm.get(chunk_id, 0.0) + w_vector * vector_norm.get(chunk_id, 0.0),
                    None,
                )
                for chunk_id in set(bm25_norm) | set(vector_norm)
            ]
        fused.sort(key=lambda item: (-item[1], item[0]))
        return fused

    @staticmethod
    def _to_hit(
        chunk_id: str,
        score: float,
        rrf_raw: float | None,
        bm25_norm: dict[str, float],
        vector_norm: dict[str, float],
        template: SearchHit | None,
    ) -> SearchHit:
        """融合分 + 双路归一分 + 元数据合成一条命中（``template`` 缺失时只带分数）。"""
        return SearchHit(
            chunk_id=chunk_id,
            score=round(float(score), 6),
            bm25_score=round(bm25_norm.get(chunk_id, 0.0), 6),
            vector_score=round(vector_norm.get(chunk_id, 0.0), 6),
            rrf_score=None if rrf_raw is None else round(float(rrf_raw), 6),
            document_id=template.document_id if template else "",
            document_name=template.document_name if template else "",
            chunk_seq=template.chunk_seq if template else -1,
            start_char=template.start_char if template else 0,
            end_char=template.end_char if template else 0,
            text=template.text if template else "",
        )


__all__ = ["DEFAULT_RRF_K", "FusionMode", "HybridRetriever", "MetadataLoader", "rrf_scores"]
