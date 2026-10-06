"""检索指标单测（M3 · T2 出口门槛：nDCG/MRR 必须与手算值逐位一致）。

全部是纯函数，无 IO、无模型、无 LLM，毫秒级跑完。
手算过程写在每个用例的注释里，便于把公式逐行现推一遍。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.retrieval_metrics import (  # noqa: E402
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

pytestmark = pytest.mark.unit

GOLD = ["d1", "d2", "d3", "d4"]


# --------------------------------------------------------------------------- #
# Recall@k
# --------------------------------------------------------------------------- #
def test_recall_counts_covered_fraction() -> None:
    """4 篇 gold，top-5 里出现 d1/d3 → 2/4 = 0.5。"""
    assert recall_at_k(["x", "d1", "y", "d3", "z"], GOLD, k=5) == pytest.approx(0.5)


def test_recall_truncates_at_k() -> None:
    """d1 在第 2 位（窗口内）、d3 在第 4 位（k=2 窗外）→ 只有 1/4 被覆盖。"""
    assert recall_at_k(["x", "d1", "y", "d3"], GOLD, k=2) == pytest.approx(0.25)


def test_recall_none_when_no_expected() -> None:
    """拒答题无标准篇章 → None（不适用），不是 0 分。

    这是 M3 报表口径的关键：把"无答案"当 0 会人为压低均值，
    并让 30 道拒答题污染所有检索指标。
    """
    assert recall_at_k(["d1", "d2"], [], k=5) is None


def test_recall_k_zero_is_zero() -> None:
    assert recall_at_k(["d1"], GOLD, k=0) == 0.0


# --------------------------------------------------------------------------- #
# Precision@k
# --------------------------------------------------------------------------- #
def test_precision_denominator_is_k_not_result_count() -> None:
    """只检索回 1 条且命中：precision = 1/5 = 0.2，不是 1.0。

    分母若用实际返回条数，"召回极差但恰好第一发命中"会被算成满分。
    """
    assert precision_at_k(["d1"], GOLD, k=5) == pytest.approx(0.2)


def test_precision_all_relevant_is_one() -> None:
    assert precision_at_k(["d1", "d2", "d3", "d4", "x"], GOLD, k=4) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# MRR@k
# --------------------------------------------------------------------------- #
def test_mrr_first_hit_rank() -> None:
    """首个命中在第 3 位 → 1/3。"""
    assert mrr_at_k(["x", "y", "d2", "d1"], ["d2"], k=5) == pytest.approx(1 / 3)


def test_mrr_no_hit_is_zero_not_none() -> None:
    """有标准答案却没找到 = 真的失败，记 0；None 只留给"不适用"。"""
    assert mrr_at_k(["x", "y"], GOLD, k=2) == 0.0


def test_mrr_outside_k_window_ignored() -> None:
    assert mrr_at_k(["x", "d1"], GOLD, k=1) == 0.0


# --------------------------------------------------------------------------- #
# nDCG@k（二值增益）
# --------------------------------------------------------------------------- #
def test_ndcg_single_hit_at_rank2() -> None:
    """gold={d2}，排在第 2 位。

    dcg = 1/log2(2+1) = 1/log2(3)；idcg（1 篇相关理想放第 1 位）= 1/log2(2) = 1。
    → nDCG = 1/log2(3) ≈ 0.910。
    """
    value = ndcg_at_k(["d1", "d2", "d3"], ["d2"], k=3)
    assert value == pytest.approx(1.0 / math.log2(3))


def test_ndcg_ideal_ordering_is_one() -> None:
    assert ndcg_at_k(["d2", "d1", "x"], ["d1", "d2"], k=3) == pytest.approx(1.0)


def test_ndcg_penalizes_good_docs_ranked_late() -> None:
    """两篇 gold 全命中但排在 4、5 位：dcg < idcg，必须 <1。"""
    value = ndcg_at_k(["a", "b", "c", "d1", "d2"], ["d1", "d2"], k=5)
    dcg = 1 / math.log2(5) + 1 / math.log2(6)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert value == pytest.approx(dcg / idcg)
    assert value < 1.0


def test_ndcg_more_expected_than_k_normalizes_by_k() -> None:
    """gold 有 4 篇但 k=2 → idcg 只能按 2 篇理想位置算，否则满分永远拿不到。"""
    value = ndcg_at_k(["d1", "d2"], GOLD, k=2)
    assert value == pytest.approx(1.0)


def test_ndcg_none_for_unanswerable() -> None:
    assert ndcg_at_k(["d1"], [], k=5) is None


def test_ndcg_no_relevant_returned_is_zero() -> None:
    assert ndcg_at_k(["x", "y"], GOLD, k=2) == 0.0


# --------------------------------------------------------------------------- #
# hit@k —— McNemar 的二值观测来源
# --------------------------------------------------------------------------- #
def test_hit_at_k_boolean() -> None:
    assert hit_at_k(["x", "d3"], GOLD, k=2) is True
    assert hit_at_k(["x", "d3"], GOLD, k=1) is False
    assert hit_at_k(["d1"], [], k=5) is False


def test_duplicate_retrieved_ids_do_not_inflate() -> None:
    """同一篇重复返回不该把 recall 算成 2/4 以上（内部按集合取交）。"""
    assert recall_at_k(["d1", "d1", "d1"], ["d1"], k=3) == pytest.approx(1.0)
