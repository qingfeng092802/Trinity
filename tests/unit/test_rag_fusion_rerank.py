"""M3 · T3-1 单测：RRF 融合、单路对照、精排插入点、weighted 回归保护。

与 ``test_rag_retriever.py`` 的分工：那个文件用真 sqlite-vec + MockEmbedder 验 M2 的
min-max 加权链路是否端到端可跑；本文件用**可编程桩**（秩与分数完全可控）逐项手算断言 ——
融合口径的正确性必须靠手算表钉住，不能靠真实检索的近似（口径 m3_design.md §4.1 / §4.2）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.exceptions import RagError  # noqa: E402
from rag.retriever import (  # noqa: E402
    DEFAULT_RRF_K,
    HybridRetriever,
    rrf_scores,
)
from rag.reranker import (  # noqa: E402
    CrossEncoderReranker,
    NoopReranker,
    RerankerError,
    create_reranker,
)
from rag.types import SearchHit  # noqa: E402

pytestmark = pytest.mark.unit

#: 本次手算用的固定候选池（4 条）与两路秩
#: BM25 秩：a ≫ b > c > d（分数极差悬殊）
#: 向量秩：d > b > a > c
#: 这是刻意构造的「口径分歧」样本：min-max 加权会把 d 抬到 b 之前，RRF 不会。
BM25_RANKED: list[tuple[str, float]] = [("a", 100.0), ("b", 2.0), ("c", 1.0), ("d", 0.5)]
VECTOR_RANKED: list[tuple[str, float]] = [("d", 0.99), ("b", 0.98), ("a", 0.50), ("c", 0.10)]


# --------------------------------------------------------------------------- #
# 测试桩
# --------------------------------------------------------------------------- #
class StubBm25:
    def __init__(self, ranked: list[tuple[str, float]]) -> None:
        self._ranked = ranked

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        return self._ranked[:top_k]

    def size(self) -> int:
        return len(self._ranked)


class StubStore:
    def __init__(self, ranked: list[tuple[str, float]]) -> None:
        self._ranked = ranked
        self.query_calls = 0

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        self.query_calls += 1
        return self._ranked[:top_k]

    def count(self) -> int:
        return len(self._ranked)


class StubEmbedder:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._fail:
            raise RuntimeError("模拟嵌入故障")
        return [[0.0, 1.0] for _ in texts]


class RecordingReranker:
    """记录输入候选、按预定顺序返回的桩（精排插入点的观察窗）。"""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.seen: list[list[str]] = []
        self.top_n_seen: list[int] = []

    def name(self) -> str:
        return "stub-recording"

    def rerank(self, query: str, candidates: list[SearchHit], *, top_n: int) -> list[SearchHit]:
        self.seen.append([hit.chunk_id for hit in candidates])
        self.top_n_seen.append(top_n)
        by_id = {hit.chunk_id: hit for hit in candidates}
        picked = [by_id[chunk_id] for chunk_id in self._order if chunk_id in by_id][:top_n]
        for position, hit in enumerate(picked):
            hit.rerank_score = round(10.0 - position, 6)
        return picked

    def health_check(self) -> tuple[bool, str]:
        return True, "stub"


def _retriever(
    *,
    fusion: str = "weighted",
    rrf_k: int = DEFAULT_RRF_K,
    reranker: Any | None = None,
    embedder: Any | None = None,
    store: Any | None = None,
    bm25: Any | None = None,
    weights: tuple[float, float] = (0.4, 0.6),
    candidate_multiplier: int = 4,
) -> HybridRetriever:
    return HybridRetriever(
        embedder=embedder or StubEmbedder(),
        store=store or StubStore(VECTOR_RANKED),
        bm25=bm25 or StubBm25(BM25_RANKED),
        bm25_weight=weights[0],
        vector_weight=weights[1],
        fusion=fusion,  # type: ignore[arg-type]
        rrf_k=rrf_k,
        reranker=reranker,
        candidate_multiplier=candidate_multiplier,
    )


def _ids(hits: list[SearchHit]) -> list[str]:
    return [hit.chunk_id for hit in hits]


def _ids_of(ranked: list[tuple[str, float]]) -> list[str]:
    return [chunk_id for chunk_id, _ in ranked]


def _approx(value: float) -> Any:
    """命中分数写进 ``SearchHit`` 时统一 round 到 6 位小数（M2 口径）。

    手算期望值必须先落到同一精度再比，否则 1e-7 量级的舍入差会被当成口径错误。
    """
    return pytest.approx(round(value, 6), abs=1e-9)


# --------------------------------------------------------------------------- #
# RRF 数学
# --------------------------------------------------------------------------- #
def test_rrf_scores_hand_computation() -> None:
    """倒数名次累加：同名 chunk 跨路累加，可逐位手算。"""
    scores = rrf_scores([["a", "b", "c"], ["b", "a", "c"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(2 / 63)
    assert scores["a"] == pytest.approx(scores["b"]), "a/b 名次对称，必须同分"


def test_rrf_scores_single_list_and_empty() -> None:
    assert rrf_scores([["x", "y"]], k=60) == {"x": pytest.approx(1 / 61), "y": pytest.approx(1 / 62)}
    assert rrf_scores([], k=60) == {}
    assert rrf_scores([[]], k=60) == {}


def test_smaller_rrf_k_widens_head_gap() -> None:
    """k 越小越偏袒榜首（A-SENS 的 k∈{20,60,100} 敏感性方向的先验检查）。"""
    gap_20 = (rrf_scores([["a", "b"]], k=20)["a"] - rrf_scores([["a", "b"]], k=20)["b"])
    gap_100 = (rrf_scores([["a", "b"]], k=100)["a"] - rrf_scores([["a", "b"]], k=100)["b"])
    assert gap_20 > gap_100 > 0


def test_rrf_is_invariant_to_score_magnitudes() -> None:
    """只改分数大小不改秩：RRF 结果不变，min-max 加权结果会变 —— 两口径的本质分歧。"""
    assert rrf_scores(_ids_of(BM25_RANKED), k=DEFAULT_RRF_K) == rrf_scores(
        ["a", "b", "c", "d"], k=DEFAULT_RRF_K
    )
    original = _retriever(fusion="weighted")
    # 把 BM25 原始分改成另一组同秩、不同极差的数值
    reshaped = _retriever(
        fusion="weighted", bm25=StubBm25([("a", 3.0), ("b", 2.5), ("c", 2.0), ("d", 0.5)])
    )
    same_rank_rrf = _retriever(
        fusion="rrf", bm25=StubBm25([("a", 3.0), ("b", 2.5), ("c", 2.0), ("d", 0.5)])
    )
    assert _ids(original.search("q", 4)) != _ids(reshaped.search("q", 4)), "加权应随极差变化"
    assert _ids(_retriever(fusion="rrf").search("q", 4)) == _ids(same_rank_rrf.search("q", 4)), (
        "RRF 只看秩，必须对分数极差免疫"
    )


# --------------------------------------------------------------------------- #
# weighted 回归保护（M2 口径逐位不变）
# --------------------------------------------------------------------------- #
def test_weighted_fusion_matches_hand_computation() -> None:
    """回归锚点：0.4/0.6 加权和与手算表逐位一致（M3 改动不得动 M2 口径）。"""
    hits = _retriever(fusion="weighted").search("弯曲半径", 4)
    # BM25 归一：a=(100-0.5)/99.5=1，b=(2-0.5)/99.5，c=(1-0.5)/99.5，d=0
    # 向量归一：d=(0.99-0.10)/0.89=1，b=0.88/0.89，a=0.4/0.89，c=0
    expected = {
        "a": 0.4 * 1.0 + 0.6 * (0.40 / 0.89),
        "b": 0.4 * (1.5 / 99.5) + 0.6 * (0.88 / 0.89),
        "c": 0.4 * (0.5 / 99.5) + 0.6 * 0.0,
        "d": 0.4 * 0.0 + 0.6 * 1.0,
    }
    by_id = {hit.chunk_id: hit.score for hit in hits}
    assert set(by_id) == set(expected)
    for chunk_id, score in expected.items():
        assert by_id[chunk_id] == pytest.approx(round(score, 6), abs=1e-6), chunk_id
    assert _ids(hits) == ["a", "d", "b", "c"]
    assert all(hit.rrf_score is None for hit in hits), "weighted 臂不得写 rrf_score"


def test_weighted_top_score_is_not_renormalized() -> None:
    """weighted 的 ``score`` 是凸组合原值（首位不必等于 1.0），与 RRF 臂区别开。"""
    top = _retriever(fusion="weighted").search("q", 4)[0]
    assert top.score == pytest.approx(0.4 * 1.0 + 0.6 * (0.40 / 0.89), abs=1e-6)
    assert top.score != pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# RRF 接入检索链路
# --------------------------------------------------------------------------- #
def test_rrf_hits_carry_normalized_and_raw_scores() -> None:
    """``score`` 归一到首位 = 1.0，``rrf_score`` 保留可手算的原始值。"""
    hits = _retriever(fusion="rrf").search("q", 4)
    expected_raw = {
        "a": 1 / 61 + 1 / 63,  # BM25 第 1、向量第 3
        "b": 1 / 62 + 1 / 62,
        "c": 1 / 63 + 1 / 64,
        "d": 1 / 64 + 1 / 61,
    }
    peak = max(expected_raw.values())
    for hit in hits:
        assert hit.rrf_score == _approx(expected_raw[hit.chunk_id])
        assert hit.score == _approx(expected_raw[hit.chunk_id] / peak)
    assert hits[0].score == pytest.approx(1.0)
    assert _ids(hits) == ["a", "b", "d", "c"]


def test_rrf_and_weighted_disagree_on_the_same_pool() -> None:
    """同一候选池、同一 query：两口径给出不同排序（E2a-3 这个臂存在的理由）。"""
    query = "弯曲半径"
    weighted = _ids(_retriever(fusion="weighted").search(query, 4))
    rrf = _ids(_retriever(fusion="rrf").search(query, 4))
    assert weighted == ["a", "d", "b", "c"]
    assert rrf == ["a", "b", "d", "c"]
    assert set(weighted) == set(rrf), "分歧只在排序，召回集合相同"


def test_rrf_keeps_candidates_recalled_by_only_one_path() -> None:
    """只被一路召回的 chunk 仍进池（单路分记 0，不丢候选）。"""
    store = StubStore([("z", 0.9), ("a", 0.1)])
    retriever = _retriever(fusion="rrf", store=store)
    hits = retriever.search("q", 10)
    ids = _ids(hits)
    assert "z" in ids and "b" in ids
    z_hit = next(hit for hit in hits if hit.chunk_id == "z")
    assert z_hit.rrf_score == _approx(1 / 61)
    assert z_hit.bm25_score == 0.0 and z_hit.vector_score == 1.0


def test_rrf_ties_break_deterministically_by_chunk_id() -> None:
    """完全对称的名次 → RRF 原始分相等，此时按 chunk_id 升序定序（可复现要求）。"""
    # bm25: a,b 与 vector: b,a 对称 ⇒ a 与 b 同为 1/61+1/62
    retriever = _retriever(
        fusion="rrf", bm25=StubBm25([("a", 9.0), ("b", 4.0)]), store=StubStore([("b", 0.9), ("a", 0.2)])
    )
    hits = retriever.search("q", 5)
    assert _ids(hits) == ["a", "b"]
    assert hits[0].rrf_score == pytest.approx(hits[1].rrf_score)
    assert hits[0].score == hits[1].score == pytest.approx(1.0)


def test_rrf_k_is_read_from_config() -> None:
    """``rrf_k`` 真的进入计算（A-SENS 三个 k 臂必须有区分度）。"""
    raw_60 = {h.chunk_id: h.rrf_score for h in _retriever(fusion="rrf", rrf_k=60).search("q", 4)}
    raw_20 = {h.chunk_id: h.rrf_score for h in _retriever(fusion="rrf", rrf_k=20).search("q", 4)}
    assert raw_60["a"] == _approx(1 / 61 + 1 / 63)
    assert raw_20["a"] == _approx(1 / 21 + 1 / 23)
    assert raw_60 != raw_20


def test_rrf_ignores_weights_argument() -> None:
    """陷阱显式化：fusion=rrf 时传 weights 不产生任何影响（臂配置写错要能被测出）。"""
    retriever = _retriever(fusion="rrf")
    plain = retriever.search("q", 4)
    with_weights = retriever.search("q", 4, weights=(0.99, 0.01))
    assert [h.rrf_score for h in plain] == [h.rrf_score for h in with_weights]
    assert _ids(plain) == _ids(with_weights)


def test_per_call_fusion_override() -> None:
    """runner 复用同一实例切臂：``search(fusion=...)`` 覆盖构造值。"""
    retriever = _retriever(fusion="weighted")
    assert _ids(retriever.search("q", 4)) == ["a", "d", "b", "c"]
    assert _ids(retriever.search("q", 4, fusion="rrf")) == ["a", "b", "d", "c"]
    assert _ids(retriever.search("q", 4)) == ["a", "d", "b", "c"], "覆盖不得污染实例状态"


# --------------------------------------------------------------------------- #
# 单路对照臂
# --------------------------------------------------------------------------- #
def test_single_path_modes_equal_weight_extremes() -> None:
    """``bm25_only`` ≡ weighted+(1,0)，``vector_only`` ≡ weighted+(0,1)（同一件事的两种写法对齐）。"""
    retriever = _retriever(fusion="weighted")
    bm25_only = _retriever(fusion="bm25_only").search("q", 4)
    vector_only = _retriever(fusion="vector_only").search("q", 4)
    assert _ids(bm25_only) == _ids(retriever.search("q", 4, weights=(1.0, 0.0)))
    assert _ids(vector_only) == _ids(retriever.search("q", 4, weights=(0.0, 1.0)))
    assert [h.score for h in bm25_only] == [h.score for h in retriever.search("q", 4, weights=(1.0, 0.0))]
    assert [h.score for h in vector_only] == [h.score for h in retriever.search("q", 4, weights=(0.0, 1.0))]


def test_single_path_modes_keep_the_other_path_score_for_diagnostics() -> None:
    """单路臂里另一路的归一分照常填（报告要靠它解释为什么这一路会输）。"""
    hits = _retriever(fusion="bm25_only").search("q", 4)
    assert hits[0].chunk_id == "a"
    assert hits[0].bm25_score == pytest.approx(1.0)
    assert hits[0].vector_score == pytest.approx(0.40 / 0.89, abs=1e-6)
    assert all(hit.rrf_score is None for hit in hits)


def test_vector_only_drops_bm25_only_candidates() -> None:
    """单路模式真的丢候选（与 weighted 的并集不同）。"""
    ids = _ids(_retriever(fusion="vector_only", store=StubStore([("only-vec", 0.9)])).search("q", 4))
    assert ids == ["only-vec"]


# --------------------------------------------------------------------------- #
# 精排阶段
# --------------------------------------------------------------------------- #
def test_reranker_sees_full_pool_before_truncation() -> None:
    """精排在截断之前：输入是整个 candidate pool，输出才砍到 top_k（§4.2 的插入点）。"""
    reranker = RecordingReranker(["c", "a", "d", "b"])
    hits = _retriever(reranker=reranker).search("q", 2)
    assert len(reranker.seen) == 1, "每次查询只走一遍精排"
    assert len(reranker.seen[0]) == 4, "候选池必须完整交给精排，不能先砍到 top_k"
    assert reranker.top_n_seen == [2]
    assert _ids(hits) == ["c", "a"]


def test_reranker_order_wins_and_score_semantics_stay_fused() -> None:
    """返回顺序 = 精排顺序；``score`` 仍是融合分，精排分单独记在 ``rerank_score``。"""
    reranker = RecordingReranker(["d", "c", "b", "a"])
    plain = {hit.chunk_id: hit for hit in _retriever(fusion="weighted").search("q", 4)}
    hits = _retriever(reranker=reranker).search("q", 4)
    assert _ids(hits) == ["d", "c", "b", "a"]
    for hit in hits:
        assert hit.score == plain[hit.chunk_id].score, "融合分不得被精排覆写"
        assert hit.bm25_score == plain[hit.chunk_id].bm25_score
    assert [hit.rerank_score for hit in hits] == [10.0, 9.0, 8.0, 7.0]


def test_noop_reranker_matches_missing_reranker_exactly() -> None:
    """基线臂（NoopReranker）与不接精排的结果必须**完全相同**（含浮点，逐字段）。"""
    from dataclasses import astuple

    with_noop = _retriever(reranker=NoopReranker()).search("q", 2)
    without = _retriever().search("q", 2)
    assert [astuple(hit) for hit in with_noop] == [astuple(hit) for hit in without]
    assert [hit.rerank_score for hit in with_noop] == [None, None]


def test_metadata_loader_receives_whole_pool() -> None:
    """元数据先按整池回填（精排要看 text），返回条数仍受 top_k 约束。"""
    requested: list[list[str]] = []

    def loader(chunk_ids: list[str]) -> dict[str, SearchHit]:
        requested.append(list(chunk_ids))
        return {
            chunk_id: SearchHit(
                chunk_id=chunk_id,
                score=0.0,
                document_id="doc-1",
                document_name="规程.md",
                chunk_seq=int(chunk_id.encode()[0] % 10),
                start_char=0,
                end_char=8,
                text=f"文本-{chunk_id}",
            )
            for chunk_id in chunk_ids
        }

    reranker = RecordingReranker(["c", "b", "a", "d"])
    hits = _retriever(reranker=reranker).search("q", 3, metadata_loader=loader)
    assert len(requested) == 1
    assert requested[0] == ["a", "d", "b", "c"], "loader 收到整个候选池，且按融合分降序"
    assert _ids(hits) == ["c", "b", "a"]
    assert [hit.text for hit in hits] == ["文本-c", "文本-b", "文本-a"]
    assert all(hit.document_name == "规程.md" for hit in hits)


def test_reranker_error_propagates_and_is_not_swallowed() -> None:
    """精排失败必须冒泡（臂级失败要整臂失败），不能被线上的降级逻辑吃掉。"""
    class Broken:
        def name(self) -> str:
            return "stub-broken"

        def rerank(self, query, candidates, *, top_n):  # noqa: ANN001, ANN201
            raise RuntimeError("模拟权重加载失败")

        def health_check(self):  # noqa: ANN201
            return False, "stub"

    with pytest.raises(RuntimeError, match="模拟权重加载失败"):
        _retriever(reranker=Broken()).search("q", 2)


# --------------------------------------------------------------------------- #
# 降级与边界
# --------------------------------------------------------------------------- #
def test_embed_failure_degrades_to_bm25_path() -> None:
    """嵌入故障 → 静默降级纯 BM25（线上路径 D3 口径），向量路分记 0。"""
    retriever = _retriever(embedder=StubEmbedder(fail=True))
    hits = retriever.search("q", 4)
    assert _ids(hits) == _ids(_retriever(fusion="bm25_only").search("q", 4))
    assert all(hit.vector_score == 0.0 for hit in hits)


def test_embed_failure_under_rrf_keeps_bm25_ranks() -> None:
    """降级同样作用于 RRF 臂：只剩一路时退化为该路的倒数名次。"""
    hits = _retriever(fusion="rrf", embedder=StubEmbedder(fail=True)).search("q", 4)
    assert _ids(hits) == ["a", "b", "c", "d"]
    assert hits[0].rrf_score == _approx(1 / 61)


def test_guards() -> None:
    retriever = _retriever()
    assert retriever.search("q", 0) == []
    assert retriever.search("   ", 5) == []
    with pytest.raises(ValueError, match="fusion"):
        _retriever(fusion="bge-reranker")
    with pytest.raises(ValueError, match="rrf_k"):
        _retriever(fusion="rrf", rrf_k=-1)
    with pytest.raises(ValueError, match="candidate_multiplier"):
        _retriever(candidate_multiplier=0)


# --------------------------------------------------------------------------- #
# 精排组件本身（不加载权重：只验构造纪律与失败口径）
# --------------------------------------------------------------------------- #
# ``CrossEncoderReranker.health_check()`` 问的就是"torch/transformers 能不能 import"，
# 所以这一条在缺包环境里必然红 —— 跳过而不是失败，断言文本一个字没动。
# ⚠️ 代价要写清：这条用例前半段（空串/None/空白 → NoopReranker）本来不需要 torch，
# 整条跳掉意味着那三行在缺包环境下也不跑。要拆开得改断言布局，不在这一趟。
_HAS_TORCH_STACK = all(
    importlib.util.find_spec(name) is not None for name in ("torch", "transformers")
)
needs_torch_stack = pytest.mark.skipif(
    not _HAS_TORCH_STACK,
    reason="本机无 torch/transformers：精排路径需 2GB+ 依赖，见 README",
)


@needs_torch_stack
def test_create_reranker_factory_maps_empty_to_noop() -> None:
    assert isinstance(create_reranker(""), NoopReranker)
    assert isinstance(create_reranker(None), NoopReranker)
    assert isinstance(create_reranker("   "), NoopReranker)
    model = create_reranker("BAAI/bge-reranker-base")
    assert isinstance(model, CrossEncoderReranker)
    assert model.name() == "cross-encoder/BAAI/bge-reranker-base"
    assert model._model is None, "构造不得加载权重（实测加载 129s，绝不能进启动路径）"
    healthy, note = model.health_check()
    assert healthy and "首次 rerank 时加载" in note


def test_cross_encoder_rejects_bad_construction_args() -> None:
    with pytest.raises(RerankerError, match="model_name"):
        CrossEncoderReranker(model_name="  ")
    with pytest.raises(RerankerError, match="batch_size"):
        CrossEncoderReranker(model_name="x", batch_size=0)


def test_reranker_error_is_a_rag_error_with_stage() -> None:
    """异常必须挂到 ``stage=reranking``：路由层与 runner 的失败归因全靠它。"""
    exc = RerankerError("模拟失败")
    assert isinstance(exc, RagError)
    assert exc.stage == "reranking"


def test_noop_reranker_truncation_semantics() -> None:
    noop = NoopReranker()
    hits = [SearchHit(chunk_id=cid, score=1.0, text="正文") for cid in ("a", "b", "c")]
    assert _ids(noop.rerank("q", hits, top_n=2)) == ["a", "b"]
    assert _ids(noop.rerank("q", hits, top_n=10)) == ["a", "b", "c"]
    assert noop.rerank("q", hits, top_n=0) == []
    assert noop.name() == "none"


def test_empty_candidate_text_fails_loudly_before_scoring() -> None:
    """候选没正文 = 回填被跳过 → 当场报错。

    放任的话模型会给空段落打出一堆近似同分，该臂照常产出报表，
    结论全假且无从追溯（消融实验最坏的一类错误：静默的假阳性）。
    """
    reranker = CrossEncoderReranker(model_name="BAAI/bge-reranker-base")
    candidates = [
        SearchHit(chunk_id="a", score=1.0, text=""),
        SearchHit(chunk_id="b", score=0.5, text="   "),
    ]
    with pytest.raises(RerankerError, match="没有正文"):
        reranker.rerank("q", candidates, top_n=2)
    assert reranker.score_calls == 0, "报错必须发生在任何打分之前"
