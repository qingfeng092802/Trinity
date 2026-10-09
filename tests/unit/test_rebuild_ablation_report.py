"""M3 · 追算脚本单测：口径重算会不会把报表算歪。

``scripts/rebuild_ablation_report.py`` 是对**已发表的数字**动手的工具，它出错时
输出的表和真跑出来的表长得一模一样，所以这几条比脚本本身更值钱。
"""

from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation.ablation import ArmOutcome  # noqa: E402
from evaluation.experiment import ArmConfig  # noqa: E402
from rebuild_ablation_report import load_outcome, rescore  # noqa: E402

pytestmark = pytest.mark.unit


def _row(qid: str, retrieved: list[str], expected: list[str], qtype: str = "factual") -> dict[str, Any]:
    return {
        "qid": qid,
        "type": qtype,
        "expected_doc_ids": expected,
        "retrieved_doc_ids": retrieved,
        "recall_at_k": None,
        "mrr_at_k": None,
        "ndcg_at_k": None,
        "hit_at_k": None,
    }


def _legacy_outcome() -> ArmOutcome:
    """还原"去重修复之前"落盘的格式：``retrieved_doc_ids`` 带重复、没有审计字段。"""
    return ArmOutcome(
        arm=ArmConfig(arm_id="A-BASE", role="baseline"),
        per_question=[
            _row("q1", ["A", "A", "B", "C", "D"], ["A"]),
            _row("q2", ["X", "X", "A", "B", "C"], ["A"]),
            _row("q3", ["B", "B", "C", "D", "E"], [], "refusal"),
        ],
    )


def test_rescore_dedups_before_scoring() -> None:
    outcome = rescore(_legacy_outcome())
    q1 = outcome.per_question[0]

    assert q1["retrieved_chunk_doc_ids"] == ["A", "A", "B", "C", "D"], "原始 chunk 序要留档"
    assert q1["retrieved_doc_ids"] == ["A", "B", "C", "D"], "判分用的是保序去重后的文档序"
    assert q1["ndcg_at_k"] == pytest.approx(1.0), "同一篇文档计两次会把 nDCG 顶到 1 以上"
    assert q1["recall_at_k"] == pytest.approx(1.0)
    assert outcome.per_question[2]["hit_at_k"] is None, "拒答题不参与判分"


def test_rescore_ranks_by_distinct_document() -> None:
    """重复槽不再把首命中往后挤：这是"文档粒度排名"口径的一部分，必须写死。"""
    outcome = rescore(_legacy_outcome())
    q2 = outcome.per_question[1]

    assert q2["mrr_at_k"] == pytest.approx(1 / 2), "去重前是第 3 槽（1/3），去重后第 2 槽"
    assert q2["recall_at_k"] == pytest.approx(1.0), "Recall 只看成员，去重不改它"


def test_rescore_aggregates_and_by_type() -> None:
    outcome = rescore(_legacy_outcome())
    expected_ndcg = (1.0 + 1 / math.log2(3)) / 2  # q1 首槽命中、q2 第二槽命中

    assert outcome.metrics["questions_scored"] == 2.0
    assert outcome.metrics["questions_total"] == 3.0
    assert outcome.metrics["ndcg_at_5"] == pytest.approx(expected_ndcg)
    assert outcome.by_type["refusal"]["scored"] == 0
    assert outcome.by_type["refusal"]["ndcg_at_5"] is None


def test_rescore_is_idempotent() -> None:
    """重算跑第二遍必须纹丝不动 —— 否则"追算"会把数字越算越偏。"""
    once = deepcopy(rescore(_legacy_outcome()).per_question)
    outcome = _legacy_outcome()
    rescore(outcome)

    assert rescore(outcome).per_question == once


def test_load_outcome_reads_the_real_file_format(tmp_path: Path) -> None:
    """脚本吃的是 ``as_dict()`` 的产物，字段名对不上就会静默算出空表。"""
    outcome = rescore(_legacy_outcome())
    path = tmp_path / "arm_A-BASE.json"
    path.write_text(json.dumps(outcome.as_dict(), ensure_ascii=False), encoding="utf-8")

    fresh = load_outcome(path)

    assert fresh.arm.arm_id == "A-BASE" and fresh.error is None
    assert fresh.per_question == outcome.per_question
    assert fresh.metrics == outcome.metrics
