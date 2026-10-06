"""从已落盘的 ``arm_*.json`` 重建消融报表（不重跑检索）。

两个用途：

1. **改判分口径后追算**：runner 一趟要跑几十分钟，中途改了的指标口径（如 D13 的显著性族、
   文档级去重后的 nDCG）对不上已在跑的进程。每臂的逐题原始观测都在 JSON 里，指标是纯函数，
   所以只需重算判分 + 重做配对检验，不必重跑一次embedding/rerank。
2. **跑挂了也拿得到表**：整趟非 0 退出时 ``ablation_summary.json`` 不落盘，但完成臂的
   ``arm_*.json`` 是增量的 —— 本脚本能只靠它们拼出报表。

::

    python scripts/rebuild_ablation_report.py --dir evaluation/reports/ablation/phaseA
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.ablation import (  # noqa: E402
    GENERATION_METRICS,
    HALLUCINATION_KEY,
    HALLUCINATION_RATE_KEY,
    REFUSAL_ACCURACY_KEY,
    REFUSAL_CORRECT_KEY,
    ArmOutcome,
    _mean_column,
    _scored_count,
    _split_by_type,
    _write_reports,
    compare_arms,
)
from evaluation.experiment import ArmConfig, Matrix, load_matrix  # noqa: E402
from evaluation.retrieval_metrics import (  # noqa: E402
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


def load_outcome(path: Path) -> ArmOutcome:
    payload = json.loads(path.read_text(encoding="utf-8"))
    outcome = ArmOutcome(
        arm=ArmConfig(**payload["config"]),
        per_question=list(payload.get("per_question") or []),
        metrics=dict(payload.get("metrics") or {}),
        by_type=dict(payload.get("by_type") or {}),
        cost=dict(payload.get("cost") or {}),
        index_group=str(payload.get("index_group") or ""),
        index_reused=bool(payload.get("index_reused")),
        seconds=float(payload.get("seconds") or 0.0),
        error=payload.get("error"),
    )
    return rescore(outcome)


def rescore(outcome: ArmOutcome) -> ArmOutcome:
    """按当前口径重算逐题指标：文档粒度**保序去重**后再判分。

    旧 JSON 没有 ``retrieved_chunk_doc_ids``，它的 ``retrieved_doc_ids`` 就是未去重的原始
    chunk 序 —— 两种来源都能还原成"原始 + 去重"两份，重算因此可幂等。
    """
    k = outcome.arm.top_k
    for row in outcome.per_question:
        raw = list(row.get("retrieved_chunk_doc_ids") or row.get("retrieved_doc_ids") or [])
        expected = list(row.get("expected_doc_ids") or [])
        deduped = list(dict.fromkeys(raw))
        row["retrieved_chunk_doc_ids"] = raw
        row["retrieved_doc_ids"] = deduped
        scorable = bool(expected)
        row["recall_at_k"] = recall_at_k(deduped, expected, k)
        row["mrr_at_k"] = mrr_at_k(deduped, expected, k)
        row["ndcg_at_k"] = ndcg_at_k(deduped, expected, k)
        row["hit_at_k"] = hit_at_k(deduped, expected, k) if scorable else None
    # Phase B 的臂带着生成侧那几列：重算检索口径时要把它们一起摊回 by_type，
    # 否则"追算一次"就把四指标的分题型列洗掉了。
    generation = GENERATION_METRICS if any("faithfulness" in row for row in outcome.per_question) else ()
    outcome.by_type = _split_by_type(outcome.per_question, k, extra=generation)
    outcome.metrics = {
        **outcome.metrics,
        f"recall_at_{k}": _mean_column(outcome.per_question, "recall_at_k"),
        f"mrr_at_{k}": _mean_column(outcome.per_question, "mrr_at_k"),
        f"ndcg_at_{k}": _mean_column(outcome.per_question, "ndcg_at_k"),
        f"hit_rate_at_{k}": _mean_column(outcome.per_question, "hit_at_k"),
        "questions_scored": float(_scored_count(outcome.per_question, "recall_at_k")),
        "questions_total": float(len(outcome.per_question)),
        **(
            {
                **{name: _mean_column(outcome.per_question, name) for name in GENERATION_METRICS},
                HALLUCINATION_RATE_KEY: _mean_column(outcome.per_question, HALLUCINATION_KEY),
                REFUSAL_ACCURACY_KEY: _mean_column(outcome.per_question, REFUSAL_CORRECT_KEY),
                "citation_rate": _mean_column(outcome.per_question, "citation_rate"),
            }
            if generation
            else {}
        ),
    }
    return outcome


def build_report(
    out_dir: Path,
    outcomes: dict[str, ArmOutcome],
    matrix: Matrix,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    report: dict[str, Any] = dict(previous or {})
    report.setdefault("phase", "A")
    report["matrix_source"] = matrix.source
    report["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["rebuilt_from_arms"] = True
    report["questions"] = max((len(o.per_question) for o in outcomes.values()), default=0)
    report["index_groups"] = {
        key: [arm_id for arm_id, outcome in outcomes.items() if outcome.index_group == key]
        for key in sorted({o.index_group for o in outcomes.values()})
    }
    report["arms"] = {arm_id: outcome.as_dict() for arm_id, outcome in outcomes.items()}
    report["failed_arms"] = sorted(a for a, o in outcomes.items() if o.error)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 arm_*.json 重建消融报表")
    parser.add_argument("--dir", type=Path, required=True, help="含 arm_*.json 的报表目录")
    parser.add_argument("--matrix", type=Path, default=PROJECT_ROOT / "evaluation/dataset/matrix_m3.yaml")
    parser.add_argument("--arm", action="append", default=[], help="只纳入指定臂（默认全纳入）")
    args = parser.parse_args(argv)

    out_dir: Path = args.dir
    paths = sorted(out_dir.glob("arm_*.json"))
    if not paths:
        print(f"{out_dir} 里没有 arm_*.json", file=sys.stderr)
        return 1
    outcomes: dict[str, ArmOutcome] = {}
    for path in paths:
        outcome = load_outcome(path)
        if args.arm and outcome.arm.arm_id not in set(args.arm):
            continue
        outcomes[outcome.arm.arm_id] = outcome

    matrix = load_matrix(args.matrix)
    # 报表顺序按矩阵的稳定序（基线在前、其余按 arm_id），只保留跑出来的臂
    ordered = {
        arm.arm_id: outcomes[arm.arm_id]
        for arm in matrix.all_arms
        if arm.arm_id in outcomes
    }
    summary_path = out_dir / "ablation_summary.json"
    previous = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    )
    comparisons = compare_arms(ordered, matrix)
    report = build_report(out_dir, ordered, matrix, previous)
    report["significance"] = {
        "family": [comparison.as_dict() for comparison in comparisons],
        "note": (
            "不做显著性检验；只报相对基线的绝对提升 Δ 与相对百分比，"
            "主判分为 nDCG@k / MRR@k（D13），n=%d 题" % report["questions"]
        ),
    }
    _write_reports(report, out_dir, ordered, comparisons, matrix)

    for comparison in comparisons:
        lift = (comparison.detail or {}).get("rel_lift")
        lift_text = "n/a" if lift is None else f"{float(lift):+.1%}"
        print(
            f"{comparison.metric:<34} Δ={comparison.mean_arm - comparison.mean_baseline:+.4f} "
            f"相对基线={lift_text} n={comparison.n_used}"
        )
    print(f"→ {out_dir / 'ablation_table.md'}（{len(ordered)} 臂）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
