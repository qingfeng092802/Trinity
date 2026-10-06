#!/usr/bin/env python
"""Phase A 报表的失败归因（``docs/m3_ablation_report.md`` 的「失败案例」一节全部出自这里）。

判分只有四个数（recall/mrr/ndcg/hit），看不出「为什么错」。本脚本把逐题结果拆成
**两类可复算的失败模式** —— 每类都是一个能报出计数的判据，不是形容词：

* **F1 未召回**：``hit_at_k == 0``，gold 篇章根本没进 top-k（检索层的能力上限问题，
  改 prompt 没用，只能动分块/索引/融合）。
* **F2 召回未居首**：``hit_at_k == 1 且 mrr < 1``，材料在 top-k 里但排在第 2..k 位
  （排序问题，也是 D13 把主指标从 Recall 换成 nDCG/MRR 的原因；rerank 就是冲着这个来的）。

**2026-09-21 收敛决策**：原先有 F1..F5 五类。F3（字面歧义）依赖把整份语料读进内存做
答案 span 子串扫描，题目一多就变成 O(题数 × 语料) 且结论不可复算；F4（组件引入/修好）
是配对计数，不是失败模式；F5（拒答无信号）在本题集里样本恒为 0，没有信息量。
三类都删掉，只留真正能指导下一步改什么的 F1 / F2。

用法：

    python scripts/analyze_ablation_failures.py --report evaluation/reports/ablation/phaseA300_cheap
    python scripts/analyze_ablation_failures.py --report evaluation/reports/ablation/phaseA \
        --dataset evaluation/dataset/knowledge_eval.jsonl      # 报表配哪份题集就给哪份

退出码：0 正常；2 报表或题集读不到（qid 对不上时只告警，因为新旧报表的 qid 本就不同源）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def read_questions(path: Path) -> dict[str, dict[str, Any]]:
    """qid → 题目行。F1 按题型归因要用 ``type`` 字段。"""
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                out[row["id"]] = row
    return out


def arm_rows(arm: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in arm.get("per_question") or [] if r.get("hit_at_k") is not None]


def classify(report: dict[str, Any], questions: dict[str, dict[str, Any]], *, show_f1: bool) -> int:
    unmatched = 0

    print(f"报表 {report['dataset']}  题数={report['questions']}  臂数={len(report['arms'])}")
    print(f"{'臂':<20}{'计分':>5}{'F1未召回':>9}{'F2未居首':>9}{'F1+F2':>8}{'干净':>7}")
    for arm_id, arm in sorted(report["arms"].items()):
        rows = arm_rows(arm)
        f1 = [r for r in rows if r["hit_at_k"] == 0.0]
        f2 = [r for r in rows if r["hit_at_k"] == 1.0 and (r["mrr_at_k"] or 0) < 1.0]
        clean = len(rows) - len(f1) - len(f2)
        print(f"{arm_id:<20}{len(rows):>5}{len(f1):>9}{len(f2):>9}"
              f"{len(f1) + len(f2):>8}{clean:>7}")

    base_arm = report["arms"]["A-BASE"]
    f1_rows = [r for r in arm_rows(base_arm) if r["hit_at_k"] == 0.0]
    f2_rows = [r for r in arm_rows(base_arm)
               if r["hit_at_k"] == 1.0 and (r["mrr_at_k"] or 0) < 1.0]
    print(f"\n基线 F1 按题型：{dict(Counter(_type_of(r, questions) for r in f1_rows))}")
    print(f"基线 F2 按题型：{dict(Counter(_type_of(r, questions) for r in f2_rows))}")

    for row in f1_rows:
        question = questions.get(row["qid"])
        if question is None:
            unmatched += 1
            continue
        if show_f1:
            top1 = (row.get("retrieved_doc_ids") or ["—"])[0]
            print(f"  [F1] {row['qid']:<16} {question.get('type', '?'):<8} "
                  f"gold={question.get('expected_doc_ids')} top1={top1} "
                  f"recall={row['recall_at_k']:.2f}")
            print(f"       问：{question['query']}")
    if f1_rows:
        print(f"基线 F1 共 {len(f1_rows)} 道：gold 篇章完全没进 top-k，"
              f"属于检索层能力上限，改 prompt 无效。")
    if f2_rows:
        print(f"基线 F2 共 {len(f2_rows)} 道：材料召回了但没排第一，"
              f"是排序问题 —— rerank / 融合权重是对应的解法。")

    if unmatched:
        print(f"\n[warn] {unmatched} 道 F1 的 qid 不在题集里（新旧报表 qid 不同源，按 query 文本另行对齐）",
              file=sys.stderr)
    return 0


def _type_of(row: dict[str, Any], questions: dict[str, dict[str, Any]]) -> str:
    question = questions.get(row["qid"])
    return "未知" if question is None else str(question.get("type", "未知"))


def main(argv: list[str] | None = None) -> int:
    streams: tuple[Any, ...] = (sys.stdout, sys.stderr)
    for stream in streams:  # 本机控制台默认 GBK，报表里有「¥」「≥」这类字符（同 runner 的处理）
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="消融报表失败归因（F1/F2 可复算判据）")
    parser.add_argument("--report", type=Path, required=True, help="一趟报表目录（含 ablation_summary.json）")
    parser.add_argument("--dataset", type=Path,
                        default=PROJECT_ROOT / "evaluation/dataset/knowledge_eval.jsonl",
                        help="与报表同源的那份题集")
    parser.add_argument("--quiet", action="store_true", help="不打印逐道 F1 明细")
    args = parser.parse_args(argv)

    summary = args.report / "ablation_summary.json"
    if not summary.is_file():
        print(f"读不到报表：{summary}", file=sys.stderr)
        return 2
    if not args.dataset.is_file():
        print(f"读不到题集：{args.dataset}", file=sys.stderr)
        return 2
    return classify(json.loads(summary.read_text(encoding="utf-8")),
                    read_questions(args.dataset), show_f1=not args.quiet)


if __name__ == "__main__":
    sys.exit(main())
