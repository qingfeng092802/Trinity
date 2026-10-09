"""评估与可观测层：Trace 落库、LLM Judge、指标统计与评测集。

四个模块各管一段，串起来就是完整的评测流水线::

    dataset（样本） → 编排执行 → trace（埋点落库） → judge（按标准打分）
                                                          ↓
                                                    metrics（报表）

对外最常用的入口：

* :class:`~evaluation.trace.TraceStore` —— 可直接作为 ``NodeContext`` 的 ``trace_sink``；
* :class:`~evaluation.judge.LLMJudge` —— 任务结束后按 ``expected_criteria`` 打分；
* :func:`~evaluation.metrics.summarize` / :func:`~evaluation.metrics.format_report` —— 汇总出报表；
* :func:`~evaluation.dataset.load_dataset` —— 读 ``evaluation/dataset/agent_tasks.jsonl``（50 条）。
"""

from __future__ import annotations

from evaluation.dataset import (
    DEFAULT_DATASET,
    DIFFICULTY_ORDER,
    DatasetError,
    Difficulty,
    EvalItem,
    dataset_stats,
    load_dataset,
)
from evaluation.judge import (
    GRADE_BANDS,
    EvalResult,
    JudgeError,
    JudgeVerdict,
    LLMJudge,
    evaluate_state,
    grade_for,
)
from evaluation.metrics import (
    GRADE_ORDER,
    BatchMetrics,
    TaskOutcome,
    format_report,
    summarize,
)
from evaluation.trace import DEFAULT_MEMORY_LIMIT, TraceStore, default_db_path

__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_MEMORY_LIMIT",
    "DIFFICULTY_ORDER",
    "GRADE_BANDS",
    "GRADE_ORDER",
    "BatchMetrics",
    "DatasetError",
    "Difficulty",
    "EvalItem",
    "EvalResult",
    "JudgeError",
    "JudgeVerdict",
    "LLMJudge",
    "TaskOutcome",
    "TraceStore",
    "dataset_stats",
    "default_db_path",
    "evaluate_state",
    "format_report",
    "grade_for",
    "load_dataset",
    "summarize",
]
