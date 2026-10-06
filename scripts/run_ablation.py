"""消融实验 CLI（M3 · T3-3）：转发到 :mod:`evaluation.ablation` 的 ``main``。

Phase A 零 API 成本、可断网跑::

    python scripts/run_ablation.py --list                              # 只看矩阵计划
    python scripts/run_ablation.py --arm A-BASE --arm A-E2a-rrf --limit 20   # smoke
    python scripts/run_ablation.py --phase A                           # 全量（预估见输出）

Phase B 花 API 钱，**没有例外地先 smoke 再全量**（``.env`` 里要有 LLM_API_KEY）::

    python scripts/run_ablation.py --phase B --arm B-BASE --limit 15   # 打印实测单价 ¥/题
    python scripts/run_ablation.py --phase B --unit-cost-cny <上一步打印的数>   # 拿单价过预检

``--limit`` 是按题型**分层**抽样的（15 题 = 8 事实 / 2 术语 / 5 拒答），不是取前 15 题：
题集按题型分块排列，前缀截断的 smoke 一道拒答题都遇不到 —— 既验不到"拒答题命中模板"这条门槛，
量出的单价还会偏高（真拒答时一次 judge 都不调，见 ``evaluation/generation_metrics.py``）。

退出码：0 全部臂跑通；1 参数漂移/预算超限/某臂失败/成本触闸；2 矩阵非法。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.ablation import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
