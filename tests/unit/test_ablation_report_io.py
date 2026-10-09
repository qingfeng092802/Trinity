"""M3 · T7 单测：消融报表的读取端（页面只读不算，读错一样会误导结论）。

真报表目录是 gitignore 的产物，所以这里全部用 tmp_path 造文件 ——
但**字段名用的是 runner 真实落盘的那套**（``ArmOutcome.as_dict`` / ``PairedComparison.as_dict``），
字段改名会让这些测试立刻红，而不是等页面显示空白。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.ablation import (  # noqa: E402
    AblationError,
    diff_rows,
    discover_report_dirs,
    load_report,
    metric_rows,
    significance_rows,
)

pytestmark = pytest.mark.unit


def _arm(arm_id: str, *, role: str = "ablation", phase: str = "A", **overrides: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "recall_at_5": 0.9,
        "mrr_at_5": 0.85,
        "ndcg_at_5": 0.92,
        "hit_rate_at_5": 0.95,
        "questions_scored": 70.0,
        "questions_total": 100.0,
    }
    metrics.update(overrides.pop("metrics", {}))
    payload = {
        "arm_id": arm_id,
        "phase": phase,
        "role": role,
        "notes": overrides.pop("notes", ""),
        "config": {"arm_id": arm_id, "top_k": 5},
        "index_group": "g1",
        "index_reused": False,
        "seconds": 4.2,
        "metrics": metrics,
        "by_type": {"term": {"ndcg_at_5": 0.8}, "factual": {"ndcg_at_5": 0.93}},
        "cost": {"retrieval_p95_ms": 34.0, "e2e_p95_ms": None, "cost_cny": 0.0},
        "error": None,
        "per_question": overrides.pop("per_question", []),
    }
    assert not overrides, f"未知的臂字段 {sorted(overrides)}：写错键名会让测试静默通过"
    return payload


def _row(qid: str, retrieved: list[str], *, ndcg: float = 1.0, qtype: str = "factual") -> dict[str, Any]:
    return {
        "qid": qid,
        "type": qtype,
        "expected_doc_ids": ["A"],
        "retrieved_doc_ids": retrieved,
        "recall_at_k": 1.0,
        "mrr_at_k": 1.0,
        "ndcg_at_k": ndcg,
        "hit_at_k": True,
        "latency_ms": 3.0,
    }


def _report(tmp_path: Path, arms: dict[str, Any], family: list[dict[str, Any]] | None = None) -> Path:
    directory = tmp_path / "phaseA"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase": "A",
        "questions": 100,
        "corpus_docs": 1000,
        "estimated_seconds": 600.0,
        "index_groups": {"g1": list(arms)},
        "cost_cny_total": 0.0,
        "matrix_source": "matrix_m3.yaml",
        "dataset": "golden_a_cmrc.jsonl",
        "arms": arms,
        "significance": {"family": family or [], "note": "Holm-Bonferroni 同族校正"},
        "failed_arms": [],
    }
    (directory / "ablation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return directory


def test_discover_and_load_report(tmp_path: Path) -> None:
    directory = _report(tmp_path, {"A-BASE": _arm("A-BASE", role="baseline")})
    (tmp_path / "not_a_report").mkdir()

    assert discover_report_dirs(tmp_path) == [directory]
    assert load_report(directory)["questions"] == 100
    assert discover_report_dirs(tmp_path / "不存在") == []


def test_load_report_falls_back_to_arm_files(tmp_path: Path) -> None:
    """跑批中断时只有 arm_*.json —— 那正是最想看的几臂，必须还能出表。"""
    directory = tmp_path / "phaseB"
    directory.mkdir()
    (directory / "arm_A-E3-base.json").write_text(
        json.dumps(_arm("A-E3-base", per_question=[_row("q1", ["A"])]), ensure_ascii=False),
        encoding="utf-8",
    )

    report = load_report(directory)

    assert report["partial"] is True
    assert report["significance"]["family"] == []
    assert list(report["arms"]) == ["A-E3-base"]


def test_load_report_without_anything_fails_loudly(tmp_path: Path) -> None:
    empty = tmp_path / "空的"
    empty.mkdir()
    with pytest.raises(AblationError, match="没有消融报表"):
        load_report(empty)


def test_metric_rows_carry_metrics_and_p_values() -> None:
    family = [
        {"metric": "A-E3-base:ndcg_at_k", "delta": 0.0631, "p_raw": 0.0097, "p_adjusted": 0.3958},
        {"metric": "A-E3-base:mrr_at_k", "delta": 0.075, "p_raw": 0.0097, "p_adjusted": 0.3958},
    ]
    arms = {
        "A-BASE": _arm("A-BASE", role="baseline"),
        "A-E3-base": _arm("A-E3-base", notes="开精排"),
    }
    rows = metric_rows({"arms": arms, "significance": {"family": family}})

    by_id = {row["arm_id"]: row for row in rows}
    assert by_id["A-E3-base"]["ndcg_at_k"] == pytest.approx(0.92)
    assert by_id["A-E3-base"]["term_ndcg"] == pytest.approx(0.8)
    assert by_id["A-E3-base"]["delta"] == pytest.approx(0.0631), "一臂只取主指标那一条 p"
    assert by_id["A-BASE"]["delta"] is None, "基线没有对照"
    # Phase A 没有生成侧指标：列必须在，但值是 None（页面显示 n/a，不能凭空补 0）
    assert by_id["A-E3-base"]["faithfulness"] is None
    assert by_id["A-E3-base"]["notes"] == "开精排"


def test_metric_rows_resolve_each_arm_own_k() -> None:
    """``top_k`` 本身就是若干臂的自变量：报表里的键是 ``ndcg_at_3``，取值就不能只查 ``@5``，
    否则那一臂整行 n/a —— 看着像"没跑"，其实跑了、只是 k 是 3。"""
    arms = {
        "A-BASE": _arm("A-BASE", role="baseline"),
        "A-E2a-3": _arm(
            "A-E2a-3",
            metrics={"ndcg_at_3": 0.4, "recall_at_3": 0.5, "hit_rate_at_3": 0.0},
        ),
    }
    arms["A-E2a-3"]["config"]["top_k"] = 3
    arms["A-E2a-3"]["by_type"] = {"term": {"ndcg_at_3": 0.25}}
    arms["A-E2a-3"]["metrics"].pop("mrr_at_5")

    row = next(item for item in metric_rows({"arms": arms}) if item["arm_id"] == "A-E2a-3")

    assert row["ndcg_at_k"] == pytest.approx(0.4)
    assert row["recall_at_k"] == pytest.approx(0.5)
    assert row["term_ndcg"] == pytest.approx(0.25)
    assert row["hit_rate_at_k"] == pytest.approx(0.0), "0 是真值，不能被当成缺列"
    assert row["mrr_at_k"] is None, "两样键都没有才是 n/a"
    # 历史报表（轨道 A 那几趟）全按 @5 落键，那一臂没给自己的 k 时仍要能读出来
    assert next(item for item in metric_rows({"arms": arms}) if item["arm_id"] == "A-BASE")["mrr_at_k"] == pytest.approx(0.85)


def test_significance_rows_split_arm_and_metric_and_keep_detail() -> None:
    family = [
        {
            "metric": "A-E2a-vector:ndcg_at_k",
            "test": "wilcoxon",
            "n_used": 70,
            "mean_baseline": 0.9226,
            "mean_arm": 0.8519,
            "delta": -0.0708,
            "p_raw": 0.00975,
            "p_adjusted": 0.3958,
            "detail": {"n_nonzero_diff": 8, "detectable_pp": 0.1},
        }
    ]
    rows = significance_rows({"significance": {"family": family}})

    assert rows[0]["arm_id"] == "A-E2a-vector" and rows[0]["metric"] == "ndcg_at_k"
    assert rows[0]["detail"]["n_nonzero_diff"] == 8, "不一致对数是解释 p 的关键，不许丢"


def test_diff_rows_align_by_qid_not_by_row_number() -> None:
    """两臂题数不同（smoke 截断、单臂失败）时按行号对齐会把整张表错开。"""
    arms = {
        "L": _arm("L", role="baseline", per_question=[_row("q1", ["A", "B"]), _row("q3", ["C"])]),
        "R": _arm("R", per_question=[_row("q1", ["B", "A"], ndcg=0.5), _row("q2", ["D"])]),
    }
    rows = diff_rows({"arms": arms}, "L", "R")

    assert [row["qid"] for row in rows] == ["q1", "q2", "q3"]
    q1 = next(row for row in rows if row["qid"] == "q1")
    assert q1["same_order"] is False
    assert q1["retrieved_L"] == "A > B" and q1["retrieved_R"] == "B > A"
    assert q1["ndcg_at_k_L"] == 1.0 and q1["ndcg_at_k_R"] == pytest.approx(0.5)
    q2 = next(row for row in rows if row["qid"] == "q2")
    assert q2["ndcg_at_k_L"] is None and q2["ndcg_at_k_R"] == 1.0, "只在右臂跑过的题要留空而不是 0"


def test_diff_rows_rejects_unknown_arm() -> None:
    arms = {"L": _arm("L", role="baseline")}
    with pytest.raises(AblationError, match="报表里没有臂"):
        diff_rows({"arms": arms}, "L", "不存在的臂")


# 这里原先还有四条判 ``ui/pages/5_ablation.py``（Streamlit 第五页）的用例：报表根目录、
# 表头中文名、p 值上色、列宽与数字格式。2026-09-27 那一页与 ``ui/`` 整目录一起删除，
# 判的对象没了 ⇒ 用例跟着删（不是"测试变宽了"，是"被测产物不存在了"）。
# 那五个读取端函数（``discover_report_dirs`` / ``load_report`` / ``metric_rows`` /
# ``significance_rows`` / ``diff_rows``）现在只剩 CLI 与本文件消费 —— 见
# ``docs/known_residuals.md`` R-13。
