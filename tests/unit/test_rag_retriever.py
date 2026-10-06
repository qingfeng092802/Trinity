"""HybridRetriever 融合检索单测 + 评测指标单测（T05）。

MockEmbedder（确定性哈希向量）+ 真 sqlite-vec + 真 jieba/BM25，秒级完成；
真实模型的效果验证走 ``scripts/eval_retrieval.py``（不进单测，避免模型加载）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.retrieval_eval import EvalItem, evaluate, is_hit, load_dataset  # noqa: E402
from rag.retriever import HybridRetriever, _min_max  # noqa: E402
from rag.types import Chunk, SearchHit  # noqa: E402

try:
    import sqlite_vec  # noqa: F401

    HAS_SQLITE_VEC = True
except ImportError:  # pragma: no cover
    HAS_SQLITE_VEC = False

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not HAS_SQLITE_VEC, reason="sqlite-vec 未安装"),
]

DIM = 8


# --------------------------------------------------------------------------- #
# 融合归一化
# --------------------------------------------------------------------------- #
def test_min_max_normalizes_to_unit_interval() -> None:
    """极差 > 0 时归一化到 [0,1]，且保序。"""
    normalized = dict(_min_max([("a", 2.0), ("b", 4.0), ("c", 6.0)]))
    assert normalized["a"] == pytest.approx(0.0)
    assert normalized["b"] == pytest.approx(0.5)
    assert normalized["c"] == pytest.approx(1.0)


def test_min_max_zero_range_gives_all_ones() -> None:
    """极差为 0（单候选或全同分）时全给 1.0，避免除零与全 0。"""
    assert dict(_min_max([("a", 3.0)]))["a"] == pytest.approx(1.0)
    assert dict(_min_max([("a", 3.0), ("b", 3.0)]))["a"] == pytest.approx(1.0)


def test_weights_extremes_match_single_path_scores(tmp_path: Path) -> None:
    """(1,0) 时 score ≡ bm25_score；(0,1) 时 score ≡ vector_score（权重路由数学）。"""
    from rag.bm25 import BM25Index
    from rag.embedder import MockEmbedder
    from rag.vector_store import SQLiteVecStore

    embedder = MockEmbedder(dim=DIM, model_name="bge-small-zh-v1.5")
    chunks = [
        Chunk(document_id="doc-a", seq=0, text="综合布线系统支持语音数据图像业务", start_char=0, end_char=17),
        Chunk(document_id="doc-a", seq=1, text="六类线弯曲半径不小于线缆外径 4 倍", start_char=19, end_char=36),
    ]
    store = SQLiteVecStore(tmp_path / "t.db", dim=DIM)
    store.add(chunks, embedder.embed([chunk.text for chunk in chunks]))
    bm25 = BM25Index()
    bm25.rebuild(chunks)
    retriever = HybridRetriever(
        embedder=embedder, store=store, bm25=bm25, bm25_weight=0.4, vector_weight=0.6
    )

    hits_bm25 = retriever.search("弯曲半径", 2, weights=(1.0, 0.0))
    hits_vector = retriever.search("弯曲半径", 2, weights=(0.0, 1.0))
    assert hits_bm25, "BM25 路必须有召回"
    assert hits_vector, "向量路必须有召回"
    for hit in hits_bm25:
        assert hit.score == pytest.approx(hit.bm25_score, abs=1e-6)
    for hit in hits_vector:
        assert hit.score == pytest.approx(hit.vector_score, abs=1e-6)


def test_hybrid_fuses_both_paths(tmp_path: Path) -> None:
    """混合权重介于两路纯分数之间（凸组合的必要性检查）。"""
    from rag.bm25 import BM25Index
    from rag.embedder import MockEmbedder
    from rag.vector_store import SQLiteVecStore

    embedder = MockEmbedder(dim=DIM, model_name="bge-small-zh-v1.5")
    chunks = [
        Chunk(document_id="doc-a", seq=0, text="综合布线系统支持语音数据图像业务", start_char=0, end_char=17),
        Chunk(document_id="doc-a", seq=1, text="六类线弯曲半径不小于线缆外径 4 倍", start_char=19, end_char=36),
    ]
    store = SQLiteVecStore(tmp_path / "t.db", dim=DIM)
    store.add(chunks, embedder.embed([chunk.text for chunk in chunks]))
    bm25 = BM25Index()
    bm25.rebuild(chunks)
    retriever = HybridRetriever(
        embedder=embedder, store=store, bm25=bm25, bm25_weight=0.4, vector_weight=0.6
    )

    pure_bm25 = {hit.chunk_id: hit.bm25_score for hit in retriever.search("弯曲半径", 2, weights=(1.0, 0.0))}
    pure_vec = {hit.chunk_id: hit.vector_score for hit in retriever.search("弯曲半径", 2, weights=(0.0, 1.0))}
    fused = {hit.chunk_id: hit.score for hit in retriever.search("弯曲半径", 2)}
    assert set(fused) == set(pure_bm25) | set(pure_vec)
    for chunk_id, score in fused.items():
        expected = 0.4 * pure_bm25.get(chunk_id, 0.0) + 0.6 * pure_vec.get(chunk_id, 0.0)
        assert score == pytest.approx(expected, abs=1e-6), f"chunk {chunk_id} 融合分不等于凸组合"


# --------------------------------------------------------------------------- #
# 评测判定与指标
# --------------------------------------------------------------------------- #
def test_is_hit_requires_document_and_keyword() -> None:
    """文档不匹配 → False；文档匹配但无关键词 → False；两者都有 → True。"""
    item = EvalItem(id="q", type="参数", query="x", expect_document="a.md", expect_keywords=["4 倍"])
    assert not is_hit(SearchHit(chunk_id="a:0", score=1.0, document_name="a.md", text="无关内容"), item)
    assert not is_hit(SearchHit(chunk_id="a:1", score=1.0, document_name="a.md", text="通用段落"), item)
    assert is_hit(
        SearchHit(chunk_id="a:2", score=1.0, document_name="a.md", text="六类线弯曲半径不小于外径 4 倍"),
        item,
    )
    assert not is_hit(SearchHit(chunk_id="b:0", score=1.0, document_name="b.md", text="弯曲半径 4 倍"), item)


def test_load_dataset_skips_blank_and_validates_fields(tmp_path: Path) -> None:
    """空行跳过；缺字段直接报错（数据集错误尽早暴露）。"""
    good = '{"id": "q1", "query": "弯曲半径", "expect_document": "a.md", "expect_keywords": ["4 倍"]}'
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(f"\n{good}\n\n", encoding="utf-8")
    items = load_dataset(dataset)
    assert len(items) == 1 and items[0].id == "q1"

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "q2"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少字段"):
        load_dataset(bad)


def test_evaluate_metrics_math() -> None:
    """指标数学：top1/top3/hit5/MRR 按命中排名精确可算。"""
    items = [
        EvalItem(id="q1", type="参数", query="a", expect_document="d.md", expect_keywords=["k"]),
        EvalItem(id="q2", type="参数", query="b", expect_document="d.md", expect_keywords=["k"]),
    ]
    # 每次查询返回固定两条命中：q1 排第 1 命中，q2 排第 2 命中
    hits_by_query = {
        "a": [_hit("d.md", "含 k 的内容", 0.9), _hit("other.md", "x", 0.5)],
        "b": [_hit("other.md", "x", 0.9), _hit("d.md", "含 k 的内容", 0.5)],
    }

    class FakeRetriever:
        def search(self, query: str, top_k: int, *, weights=None, metadata_loader=None):  # noqa: ANN001
            return hits_by_query[query]

    metrics = evaluate(items, FakeRetriever(), None, weights=(0.4, 0.6), top_k=5)  # type: ignore[arg-type]
    assert metrics["total"] == 2
    assert metrics["top1_rate"] == pytest.approx(0.5)
    assert metrics["top3_rate"] == pytest.approx(1.0)
    assert metrics["hit5_rate"] == pytest.approx(1.0)
    assert metrics["mrr"] == pytest.approx((1.0 + 0.5) / 2)


# --------------------------------------------------------------------------- #
# 测试辅助
# --------------------------------------------------------------------------- #
def _hit(document_name: str, text: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=f"{document_name}:0", score=score, document_name=document_name, text=text
    )
