#!/usr/bin/env python
"""从 ``golden_a_cmrc.jsonl`` 派生检索评测集（**纯字段映射，不生成任何新内容**）。

为什么要派生：**两条评测轨道必须用同一份真实基线**，否则前端展示的检索指标和
消融表的指标对不上，评测就变成各说各话。

源集 ``golden_a_cmrc.jsonl`` 与 ``retrieval_eval.py`` 的口径有三处不一致，逐一处理：

1. **字段名不同**：源集是 ``expected_document``（文件名）＋ ``ground_truth``（答案 span 列表），
   检索评测认的是 ``expect_document`` ＋ ``expect_keywords``。这里只做**键名映射**，
   不做任何改写。
2. **拒答题无 gold 文档**：100 题里 30 道 ``type=refusal`` 的 ``expected_doc_ids`` 为空。
   检索评测的命中判定是「文档名相等 且 片段含关键词」，没有 gold 文档的题**无法计分**——
   硬塞进去等于凭空制造 30 道必错题，把命中率打到 70%。这与消融脚本的口径一致
   （``scripts/analyze_ablation_failures.py`` 里 ``hit_at_k is None`` 的题同样被
   ``arm_rows()`` 挡在计分集外），所以这里也**剔除**，最终 70 道可计分题。
3. **关键词必须真的在文档里**：``is_hit`` 要求片段原文含任一关键词。源集给的是
   ``ground_truth``（答案 span），若某个 span 在目标文档里根本不出现，那道题永远判不中。
   因此逐条做**字面校验**，不通过的整条丢弃并计数——宁可少题，也不留假题。

用法::

    python evaluation/dataset/_derive_retrieval_from_cmrc.py

退出码：0 全部通过；1 有题目未通过字面校验（此时不写文件）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "evaluation/dataset/golden_a_cmrc.jsonl"
FIXTURES = PROJECT_ROOT / "evaluation/fixtures_cmrc"
TARGET = PROJECT_ROOT / "evaluation/dataset/retrieval_eval_cmrc.jsonl"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept: list[dict[str, object]] = []
    skipped_refusal = 0
    dropped_by_check = 0
    missing_doc = 0

    for row in rows:
        doc_name = row.get("expected_document")
        if not doc_name:
            skipped_refusal += 1
            continue
        doc_path = FIXTURES / str(doc_name)
        if not doc_path.is_file():
            missing_doc += 1
            print(f"[warn] 文档不存在，跳过：{row['id']} → {doc_name}", file=sys.stderr)
            continue
        text = doc_path.read_text(encoding="utf-8")
        # 只保留**逐字出现**在目标文档里的答案变体；一个都没有 → 这题判不中，丢弃
        keywords = [v for v in dict.fromkeys(row.get("ground_truth") or []) if v and str(v) in text]
        if not keywords:
            dropped_by_check += 1
            print(f"[warn] ground_truth 未逐字命中原文，丢弃：{row['id']}", file=sys.stderr)
            continue
        kept.append(
            {
                "id": row["id"],
                "type": row.get("type", "unknown"),
                "query": row["query"],
                "expect_document": doc_name,
                "expect_keywords": keywords,
            }
        )

    print(f"源题数 {len(rows)}；拒答剔除 {skipped_refusal}；"
          f"关键词未命中丢弃 {dropped_by_check}；文档缺失 {missing_doc}；产出 {len(kept)}")
    if dropped_by_check or missing_doc:
        print("存在未通过校验的题目，不写文件（修数据再跑）", file=sys.stderr)
        return 1

    TARGET.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in kept) + "\n", encoding="utf-8"
    )
    print(f"→ {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
