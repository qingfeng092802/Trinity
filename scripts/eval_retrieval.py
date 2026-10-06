"""检索评测 CLI（T05）：转发到 :mod:`evaluation.retrieval_eval` 的 ``main``。

用法（零 LLM 调用，可断网跑）::

    python scripts/eval_retrieval.py                          # 默认三组权重对照
    python scripts/eval_retrieval.py --weights 1.0:0.0        # 纯 BM25 对照组
    python scripts/eval_retrieval.py --weights 0.0:1.0        # 纯向量对照组
    python scripts/eval_retrieval.py --dataset <jsonl> --fixtures <dir>

退出码：G2 门槛只认**参照组** 0.4:0.6 的 top-3 命中率（≥ 80%）。
通过 = 0；跑了但未达门槛 = 1；**参照组没在本次扫描里（如只传 ``--weights 1.0:0.0``）= 2**，
此时报告与 stdout 都会写"无法判定 G2"，不会拿别的组冒充参照组打绿。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.retrieval_eval import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
