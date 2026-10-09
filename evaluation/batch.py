"""批量评测执行器：把「跑一批样本」的执行与落库口径收在一处。

原先这里是"脚本与 UI 共用"：``scripts/run_eval.py`` 打印文本报表，
``ui/pages/4_batch_eval.py`` 在页面上实时刷新，两边的口径必须一致，否则同一批样本
在两个入口跑出的分数可能不同，那时候没人知道该信谁。
2026-09-27 那一页随 ``ui/`` 整目录删除，现在只有 CLI 一个入口 —— 但**这层抽象保留**：
下一份界面（``web-react`` 的评测页）要接批量评测时，必须接在这层上面，
而不是再抄一遍循环，理由与上面那句一模一样。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from config import Settings, get_settings
from core.agent.base import NodeContext
from core.llm.adapter import LLMNotRetryableError, text_reports_non_retryable
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry
from core.workflow.graph import WorkflowRunner
from core.workflow.state import WorkflowConfig
from evaluation.dataset import EvalItem, load_dataset
from evaluation.judge import LLMJudge
from evaluation.metrics import TaskOutcome
from evaluation.trace import TraceStore
from storage.db import Database

logger = logging.getLogger(__name__)

#: 单条样本跑完后的回调：``(序号, 样本, 产物或 None, 错误信息或 None)``
ProgressCallback = Callable[[int, EvalItem, TaskOutcome | None, str | None], None]


@dataclass(slots=True)
class BatchRun:
    """一次批量评测的结果。"""

    outcomes: list[TaskOutcome] = field(default_factory=list)
    eval_results: list[dict[str, Any]] = field(default_factory=list)
    #: 非空表示整批被提前中止（余额不足 / 鉴权失败这类重试无用的错误）
    abort_reason: str = ""

    @property
    def count(self) -> int:
        """样本条数。"""
        return len(self.outcomes)


def run_batch(
    items: Sequence[EvalItem],
    *,
    settings: Settings | None = None,
    config: WorkflowConfig | None = None,
    use_tools: bool = True,
    run_judge: bool = True,
    store: TraceStore | None = None,
    database: Database | None = None,
    on_item: ProgressCallback | None = None,
) -> BatchRun:
    """跑一批评测样本。

    Args:
        items: 评测样本。
        settings: 全局配置。
        config: 编排参数（迭代上限、通过线）。
        use_tools: 是否接入 5 个内置工具。
        run_judge: 是否用 LLM Judge 打分。
        store: Trace 存储（不传则新建）。
        database: 业务库（传入则落库 tasks / eval_records）。
        on_item: 每条跑完后的回调，用于 CLI 打印或页面刷新。

    Returns:
        :class:`BatchRun`。单条样本失败不会中断整批。
    """
    resolved = settings or get_settings()
    trace_store = store if store is not None else TraceStore()
    resolved_config = config or WorkflowConfig.from_settings(resolved)

    registry: ToolRegistry | None = None
    if use_tools:
        registry = load_builtin_tools(ToolRegistry(settings=resolved, enable_hitl=False))
    judge = LLMJudge(settings=resolved) if run_judge else None

    runner = WorkflowRunner(
        NodeContext.create(
            settings=resolved,
            config=resolved_config,
            trace_sink=trace_store,
            tool_invoker=registry,
        )
    )

    batch = BatchRun()
    for index, item in enumerate(items, 1):
        try:
            state = runner.run(item.task)
        except Exception as exc:  # 单条失败不能搞挂整批，转成 failed 产物继续跑
            logger.exception("样本 %s 执行失败", item.id)
            failed = TaskOutcome(task=item.task, task_id="-", status="failed")
            batch.outcomes.append(failed)
            if on_item is not None:
                on_item(index, item, failed, f"{type(exc).__name__}: {exc}")
            if isinstance(exc, LLMNotRetryableError) and not _any_done(batch):
                # 余额不足 / 鉴权失败：整批剩下的样本重试一万次也是同样结果，
                # 立刻停下并带上可执行提示，比跑满 50 条再报错有用得多。
                batch.abort_reason = str(exc)
                logger.error("批处理中止：%s", exc)
                break
            continue

        task_id = str(state.get("task_id", ""))
        records = trace_store.for_task(task_id)
        result = None
        if judge is not None:
            try:
                result = judge.evaluate(
                    task=item.task,
                    criteria=item.expected_criteria,
                    final_answer=str(state.get("final_answer", "")),
                    task_id=task_id,
                    records=records,
                    status=str(state.get("status", "unknown")),
                    iterations=int(state.get("iteration", 0)),
                )
            except Exception as exc:  # noqa: BLE001 - judge 失败不影响流程指标
                logger.warning("样本 %s 的 judge 失败：%s", item.id, exc)

        outcome = TaskOutcome.from_state(
            state,
            records,
            score=result.score if result else None,
            grade=result.grade if result else None,
        )
        batch.outcomes.append(outcome)
        if result is not None:
            batch.eval_results.append(result.model_dump())

        if database is not None:
            database.save_task(
                task_id=task_id,
                task=item.task,
                status=outcome.status,
                iterations=outcome.iterations,
                score=outcome.score,
                grade=outcome.grade,
                final_answer=str(state.get("final_answer", "")),
                cost=outcome.cost,
                duration_ms=outcome.duration_ms,
                tool_calls=outcome.tool_calls,
                tool_failures=outcome.tool_failures,
                difficulty=item.difficulty,
            )
            if result is not None:
                database.save_eval_result(result.model_dump())

        if on_item is not None:
            on_item(index, item, outcome, None)

        # 节点层会把异常转成失败状态（异常对象不会传出来），所以这里要从状态文本里
        # 识别「重试无用」的错误：余额不足 / 鉴权失败时整批剩下的样本没有意义，立刻停。
        if not _any_done(batch) and _state_reports_non_retryable(state):
            batch.abort_reason = _abort_text(state)
            logger.error("批处理中止：%s", batch.abort_reason)
            break

    return batch


def _state_reports_non_retryable(state: Any) -> bool:
    """失败状态里是否含「重试无用」的错误标记。"""
    if not isinstance(state, dict) or state.get("status") != "failed":
        return False
    return text_reports_non_retryable(_abort_text(state))


def _abort_text(state: Any) -> str:
    """从失败状态里取一句话原因。"""
    if isinstance(state, dict):
        return str(state.get("review_comment") or state.get("final_answer") or "")
    return str(state)


def _any_done(batch: BatchRun) -> bool:
    """是否已经有样本真的跑完了（用来区分「一开始就环境不对」和「跑了一半挂了」）。"""
    return any(item.status == "done" for item in batch.outcomes)


def run_batch_from_dataset(
    *,
    dataset_path: str | None = None,
    difficulty: str | None = None,
    limit: int | None = None,
    **kwargs: Any,
) -> tuple[BatchRun, list[EvalItem]]:
    """读评测集并跑完（便捷入口）。"""
    items = load_dataset(dataset_path, difficulty=difficulty, limit=limit)  # type: ignore[arg-type]
    return run_batch(items, **kwargs), items


__all__ = ["BatchRun", "ProgressCallback", "run_batch", "run_batch_from_dataset"]
