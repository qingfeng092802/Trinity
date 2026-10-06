"""评测指标：把逐条任务的产物汇总成一张可横向比较的报表。

指标口径刻意选得保守、可复算：

* **完成率** 只认 ``status == "done"``。``aborted``（达到迭代上限被强制收口）
  单独计数，不算完成——把它算进完成率会让平台「看起来更好」，属于自欺欺人。
* **工具成功率** 按**调用次数**算，不按任务算。一次失败的工具调用就是一次失败，
  跟它出现在几个任务里无关。
* **平均分** 只在真的跑过 judge 的任务上求平均，没评测的条目不参与（用 0 分填充
  会把平均分拉低，用满分填充会拉高，都是错的）。
* **取消（``canceled``）单独计数**：既不算完成，也不算失败，完成率的分母仍是
  ``total``。把它并进 ``failed`` 会让「我主动止损」看起来像「系统出错」，
  把它并进 ``completed`` 就更离谱——与 ``aborted`` 的处理哲学一致：不美化数字。
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.agent.base import TraceRecord
from evaluation.contracts import (
    ASSERT_TOOL_SEQUENCE,
    STATUS_DONE,
    SuiteMetrics,
    round_cost,
    round_ratio,
)

#: 等级展示顺序（报表里固定按这个顺序统计）
GRADE_ORDER: tuple[str, ...] = ("excellent", "good", "fair", "poor")


@dataclass(slots=True)
class TaskOutcome:
    """单条评测任务的产物。"""

    task: str
    task_id: str
    status: str
    iterations: int = 0
    duration_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    cost: float = 0.0
    tool_calls: int = 0
    tool_failures: int = 0
    score: int | None = None
    grade: str | None = None

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        records: Sequence[TraceRecord] = (),
        *,
        score: int | None = None,
        grade: str | None = None,
    ) -> TaskOutcome:
        """从最终状态 + 埋点构造产物。

        ``state`` 用 ``Mapping`` 而不是 ``dict``：``AgentState`` 是 TypedDict，
        TypedDict 与 ``dict[str, Any]`` 不兼容（前者是后者的子类型），用 Mapping 两边都收。
        """
        tool_calls = 0
        tool_failures = 0
        for record in records:
            for call in record.tool_calls:
                tool_calls += 1
                if call.get("status") != "success":
                    tool_failures += 1
        return cls(
            task=str(state.get("task", "")),
            task_id=str(state.get("task_id", "")),
            status=str(state.get("status", "unknown")),
            iterations=int(state.get("iteration", 0)),
            duration_ms=sum(record.duration_ms for record in records),
            token_in=sum(record.token_in for record in records),
            token_out=sum(record.token_out for record in records),
            cost=round(sum(record.cost for record in records), 6),
            tool_calls=tool_calls,
            tool_failures=tool_failures,
            score=score,
            grade=grade,
        )


@dataclass(slots=True)
class BatchMetrics:
    """一批任务的汇总指标。"""

    tasks: int
    completed: int
    aborted: int
    failed: int
    canceled: int
    completion_rate: float
    avg_iterations: float
    avg_duration_ms: float
    total_duration_ms: int
    total_cost: float
    avg_cost: float
    total_tokens: int
    tool_calls: int
    tool_failures: int
    tool_success_rate: float
    judged: int
    avg_score: float | None
    grade_distribution: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "tasks": self.tasks,
            "completed": self.completed,
            "aborted": self.aborted,
            "failed": self.failed,
            "canceled": self.canceled,
            "completion_rate": round(self.completion_rate, 4),
            "avg_iterations": round(self.avg_iterations, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "total_duration_ms": self.total_duration_ms,
            "total_cost": round(self.total_cost, 6),
            "avg_cost": round(self.avg_cost, 6),
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "judged": self.judged,
            "avg_score": None if self.avg_score is None else round(self.avg_score, 2),
            "grade_distribution": self.grade_distribution,
        }


def summarize(outcomes: Sequence[TaskOutcome]) -> BatchMetrics:
    """汇总一批任务产物。空输入返回全零，不抛异常。"""
    total = len(outcomes)
    if total == 0:
        return BatchMetrics(
            tasks=0,
            completed=0,
            aborted=0,
            failed=0,
            canceled=0,
            completion_rate=0.0,
            avg_iterations=0.0,
            avg_duration_ms=0.0,
            total_duration_ms=0,
            total_cost=0.0,
            avg_cost=0.0,
            total_tokens=0,
            tool_calls=0,
            tool_failures=0,
            tool_success_rate=0.0,
            judged=0,
            avg_score=None,
            grade_distribution=dict.fromkeys(GRADE_ORDER, 0),
        )

    completed = sum(1 for item in outcomes if item.status == "done")
    aborted = sum(1 for item in outcomes if item.status == "aborted")
    failed = sum(1 for item in outcomes if item.status == "failed")
    canceled = sum(1 for item in outcomes if item.status == "canceled")
    tool_calls = sum(item.tool_calls for item in outcomes)
    tool_failures = sum(item.tool_failures for item in outcomes)
    scored = [item.score for item in outcomes if item.score is not None]
    distribution: dict[str, int] = dict.fromkeys(GRADE_ORDER, 0)
    for item in outcomes:
        if item.grade:
            distribution[item.grade] = distribution.get(item.grade, 0) + 1

    total_cost = round(sum(item.cost for item in outcomes), 6)
    return BatchMetrics(
        tasks=total,
        completed=completed,
        aborted=aborted,
        failed=failed,
        canceled=canceled,
        completion_rate=completed / total,
        avg_iterations=sum(item.iterations for item in outcomes) / total,
        avg_duration_ms=sum(item.duration_ms for item in outcomes) / total,
        total_duration_ms=sum(item.duration_ms for item in outcomes),
        total_cost=total_cost,
        avg_cost=round(total_cost / total, 6),
        total_tokens=sum(item.token_in + item.token_out for item in outcomes),
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        tool_success_rate=(tool_calls - tool_failures) / tool_calls if tool_calls else 0.0,
        judged=len(scored),
        avg_score=(sum(scored) / len(scored)) if scored else None,
        grade_distribution=distribution,
    )


# --------------------------------------------------------------------------- #
# P2 评测台 · 套件指标汇总（设计文档 §4，逐条精确）
#
# 与上面的 ``BatchMetrics`` 分工明确：
# * ``BatchMetrics`` 服务**旧 criteria 任务集**（JSONL + judge），键名沿用其历史口径。
# * ``SuiteMetrics``（契约 ``evaluation/contracts.py``，**不在本模块定义**）服务
#   **P2 新任务集**（YAML + 规则断言），主指标键名见 ``contracts.METRIC_KEYS``。
#
# 本节**只新增符号**：不触碰 ``TaskOutcome`` / ``BatchMetrics`` / ``summarize`` /
# ``format_report`` 等既有实现（回归风险 = 0）。
#
# 输入约定（给 T03 harness 的接口契约）
# ------------------------------------
# :func:`summarize_suite` 吃一串「逐任务行」（``Sequence[Mapping]``）。推荐用
# :func:`make_suite_row` 由 ``(EvalTask, TaskRun, TaskAssertionResult)`` 生成，键名与
# 设计文档 §3.4 的 ``per_task`` 一致，另加三个**仅供汇总**的键：
#
#   * ``tool_expected`` (bool) —— 该任务是否声明了 ``expected_tools``（决定 ``tool_accuracy`` 分母）；
#   * ``tool_passed``   (bool | None) —— ``tool_sequence`` 断言是否通过（``tool_expected`` 为真时有效）；
#   * ``tool_soft``     (float | None) —— ``subset``/``set`` 的软分（汇总为 ``tool_accuracy_soft``）。
#
# 其余键（``passed`` / ``status`` / ``steps`` / ``iterations`` / ``tool_calls`` /
# ``tool_failures`` / ``cost`` / ``duration_ms`` / ``wall_ms``）缺省都有兜底值，
# 因此也接受直接传入/裁剪过的字典（新旧基线兼容）。
# --------------------------------------------------------------------------- #

#: ``summarize_suite`` 读取的逐任务键（文档用途，供 harness / 测试对照）
SUITE_ROW_KEYS: tuple[str, ...] = (
    "id",
    "category",
    "difficulty",
    "passed",
    "status",
    "steps",
    "iterations",
    "tool_calls",
    "tool_failures",
    "cost",
    "duration_ms",
    "wall_ms",
    "tool_sequence",
    "tool_source",
    "failed_assertions",
    "tool_expected",
    "tool_passed",
    "tool_soft",
)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """从「逐任务行」里取值，兼容 ``Mapping`` 与对象（鸭子类型）。"""
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _as_int(value: Any, default: int = 0) -> int:
    """把可能是 ``None`` / 字符串的计数值安全转成 ``int``。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    """把可能是 ``None`` 的数值安全转成 ``float``。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def percentile_nearest_rank(values: Sequence[float], q: float) -> float:
    """nearest-rank 分位数（算法**写死**，保证跨机器/跨版本可复现，§4.5）。

    规则：对升序后的 ``v``（长度 ``n``）取第 ``rank = ceil(q * n)`` 个（1 起），
    下标 ``rank - 1`` 再夹到 ``[0, n-1]``。刻意不用 ``statistics.quantiles``——
    后者小样本走插值，会引入"看起来精确"的伪值。

    Args:
        values: 数值序列（内部先排序，不改动入参）。
        q: 分位点，``0.0 <= q <= 1.0``。

    Returns:
        分位数值；``values`` 为空时返回 ``0.0``。
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    rank = math.ceil(q * n) if q > 0 else 0
    index = min(max(rank, 1), n) - 1
    return float(ordered[index])


def _find_outcome(outcomes: Sequence[Any], name: str) -> Any | None:
    """在断言结果列表里按名字取一条 outcome（兼容对象与字典）。"""
    for outcome in outcomes:
        if _row_get(outcome, "name") == name:
            return outcome
    return None


def make_suite_row(task: Any, run: Any, result: Any) -> dict[str, Any]:
    """把 ``(EvalTask, TaskRun, TaskAssertionResult)`` 拍成一行套件记录。

    纯读取入参，不做任何断言——断言结果 ``result`` 已由 :mod:`evaluation.assertions`
    产出，这里只做投影。

    Args:
        task: 评测任务（读 ``id`` / ``category`` / ``difficulty`` / ``expected_tools``）。
        run: 规范化产物（读 ``status`` / ``steps`` / ``iterations`` / ``tool_sequence`` /
            ``tool_calls`` / ``tool_failures`` / ``cost`` / ``duration_ms`` / ``wall_ms`` /
            ``tool_source``）。
        result: 单任务断言汇总（读 ``passed`` / ``failed_assertions`` 或 ``failed_names()`` /
            ``outcomes``）。

    Returns:
        可直接喂给 :func:`summarize_suite`、也可落基线 ``per_task`` 的字典。
    """
    outcomes = list(_row_get(result, "outcomes", []) or [])

    failed = _row_get(result, "failed_assertions", None)
    if failed is None:
        failed_method = getattr(result, "failed_names", None)
        failed = failed_method() if callable(failed_method) else []
    failed_list = list(failed or [])

    tool_outcome = _find_outcome(outcomes, ASSERT_TOOL_SEQUENCE)
    tool_passed: bool | None = None
    tool_soft: float | None = None
    if tool_outcome is not None:
        tool_passed = bool(_row_get(tool_outcome, "passed", False))
        evidence = _row_get(tool_outcome, "evidence", {}) or {}
        soft_value = evidence.get("soft_score") if isinstance(evidence, Mapping) else None
        if soft_value is not None:
            tool_soft = _as_float(soft_value, 0.0)

    return {
        "id": _row_get(task, "id", ""),
        "category": _row_get(task, "category", ""),
        "difficulty": _row_get(task, "difficulty", ""),
        "passed": bool(_row_get(result, "passed", False)),
        "status": _row_get(run, "status", ""),
        "steps": _as_int(_row_get(run, "steps", 0)),
        "iterations": _as_int(_row_get(run, "iterations", 0)),
        "tool_calls": _as_int(_row_get(run, "tool_calls", 0)),
        "tool_failures": _as_int(_row_get(run, "tool_failures", 0)),
        "cost": round_cost(_as_float(_row_get(run, "cost", 0.0))),
        "duration_ms": _as_int(_row_get(run, "duration_ms", 0)),
        "wall_ms": _as_int(_row_get(run, "wall_ms", 0)),
        "tool_sequence": list(_row_get(run, "tool_sequence", []) or []),
        "tool_source": _row_get(run, "tool_source", ""),
        "failed_assertions": failed_list,
        # 仅供汇总的三个键（不属于基线 per_task 的展示字段）
        "tool_expected": getattr(task, "expected_tools", None) is not None,
        "tool_passed": tool_passed,
        "tool_soft": tool_soft,
    }


def summarize_suite(
    rows: Sequence[Any],
    *,
    skipped: int = 0,
    repeat_std: Mapping[str, float] | None = None,
) -> SuiteMetrics:
    """把逐任务行汇总成 :class:`SuiteMetrics`（设计文档 §4，逐条精确）。

    口径（**失败/超时/中止一律计入分母，不美化数字**）：

    * ``pass_rate = passed / evaluated``；``evaluated = len(rows)``（含 failed/aborted/
      canceled/timeout），``skipped`` 单列、不进任何分母；
    * ``tool_accuracy`` 分母 = **有 ``expected_tools`` 的任务数**（``|T|``）；
      ``|T| == 0`` → 返回 ``None``（报表写"本批无工具期望"，**不是** 0%）；
    * ``tool_call_success_rate`` 描述"调用本身成不成功"，与 ``tool_accuracy``
      （"有没有调对工具"）**严格区分**；
    * ``avg_steps`` = 节点执行次数均值；``avg_iterations`` / ``avg_tool_calls`` 作旁参；
    * 成本求和/均值均 ``round(x, 6)``；延迟主口径 ``duration_ms``（avg/p50/p95/max），
      墙钟 ``wall_ms`` 另记；
    * 空集（``evaluated == 0``）：比率/均值返回 ``0.0``，可空项（``tool_accuracy`` /
      ``tool_accuracy_soft``）返回 ``None``。

    Args:
        rows: 逐任务行（推荐由 :func:`make_suite_row` 生成；也接受等价字典）。
        skipped: 因前置条件不满足而跳过的条数（不进分母）。
        repeat_std: ``repeat>1`` 时逐指标标准差（键名见 ``contracts.METRIC_KEYS``）；
            单次运行传 ``None``。

    Returns:
        填好的 :class:`SuiteMetrics`（比率 ``round(,4)``、成本 ``round(,6)``）。
    """
    materialized = list(rows)
    evaluated = len(materialized)

    passed_count = sum(1 for row in materialized if bool(_row_get(row, "passed", False)))
    failed_count = evaluated - passed_count
    pass_rate = round_ratio(passed_count / evaluated) if evaluated else 0.0

    steps_values = [_as_int(_row_get(row, "steps", 0)) for row in materialized]
    iterations_values = [_as_int(_row_get(row, "iterations", 0)) for row in materialized]
    latency_values = [float(_as_int(_row_get(row, "duration_ms", 0))) for row in materialized]

    tool_calls = sum(_as_int(_row_get(row, "tool_calls", 0)) for row in materialized)
    tool_failures = sum(_as_int(_row_get(row, "tool_failures", 0)) for row in materialized)
    costs = [_as_float(_row_get(row, "cost", 0.0)) for row in materialized]
    total_cost = round_cost(sum(costs))
    wall_ms = sum(_as_int(_row_get(row, "wall_ms", 0)) for row in materialized)

    # 工具准确率：分母只算「有工具期望」的任务
    tool_rows = [row for row in materialized if bool(_row_get(row, "tool_expected", False))]
    tool_expected_tasks = len(tool_rows)
    if tool_expected_tasks == 0:
        tool_accuracy: float | None = None
    else:
        hits = sum(1 for row in tool_rows if bool(_row_get(row, "tool_passed", False)))
        tool_accuracy = round_ratio(hits / tool_expected_tasks)

    soft_values = [
        _as_float(_row_get(row, "tool_soft"))
        for row in tool_rows
        if _row_get(row, "tool_soft", None) is not None
    ]
    tool_accuracy_soft = (
        round_ratio(sum(soft_values) / len(soft_values)) if soft_values else None
    )

    return SuiteMetrics(
        evaluated=evaluated,
        skipped=int(skipped),
        passed=passed_count,
        failed=failed_count,
        pass_rate=pass_rate,
        tool_accuracy=tool_accuracy,
        tool_expected_tasks=tool_expected_tasks,
        tool_accuracy_soft=tool_accuracy_soft,
        avg_steps=(sum(steps_values) / evaluated) if evaluated else 0.0,
        avg_iterations=(sum(iterations_values) / evaluated) if evaluated else 0.0,
        avg_tool_calls=(tool_calls / evaluated) if evaluated else 0.0,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        tool_call_success_rate=(
            round_ratio((tool_calls - tool_failures) / tool_calls) if tool_calls else 0.0
        ),
        total_cost=total_cost,
        avg_cost=(round_cost(sum(costs) / evaluated) if evaluated else 0.0),
        avg_latency_ms=(sum(latency_values) / evaluated) if evaluated else 0.0,
        p50_latency_ms=percentile_nearest_rank(latency_values, 0.5),
        p95_latency_ms=percentile_nearest_rank(latency_values, 0.95),
        max_latency_ms=(max(latency_values) if latency_values else 0.0),
        wall_ms=wall_ms,
        std={str(key): float(value) for key, value in (repeat_std or {}).items()},
    )


def latency_success_only(rows: Sequence[Any]) -> dict[str, float | int | None]:
    """仅 ``done`` 任务的延迟分位（副指标，§4.5）。

    失败任务的延迟分布可能被长尾污染，故单列"只看成功"的 P50/P95。
    ``SuiteMetrics`` 无对应字段（契约冻结，不得改），故以独立函数暴露给报告层。

    Returns:
        ``{"count": n, "p50": ..., "p95": ...}``；无 done 任务时两个分位为 ``None``。
    """
    done_latencies = [
        float(_as_int(_row_get(row, "duration_ms", 0)))
        for row in rows
        if _row_get(row, "status", "") == STATUS_DONE
    ]
    if not done_latencies:
        return {"count": 0, "p50": None, "p95": None}
    return {
        "count": len(done_latencies),
        "p50": percentile_nearest_rank(done_latencies, 0.5),
        "p95": percentile_nearest_rank(done_latencies, 0.95),
    }


def _display_width(text: str) -> int:
    """估算终端显示宽度：CJK 全角字符按 2 列算。

    不做这一步，中文表头会整体错位——``str.ljust`` 数的是字符数，不是显示列数。
    """
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _cell(text: str, width: int, align: str) -> str:
    """按显示宽度补空格。"""
    gap = max(width - _display_width(text), 0)
    return (" " * gap + text) if align == "right" else (text + " " * gap)


#: 报表列定义：(表头, 显示宽度, 对齐)
_COLUMNS: tuple[tuple[str, int, str], ...] = (
    ("#", 3, "right"),
    ("task_id", 18, "left"),
    ("终态", 8, "left"),
    ("分", 3, "right"),
    ("等级", 9, "left"),
    ("迭代", 4, "right"),
    ("耗时", 8, "right"),
    ("成本", 10, "right"),
)


def _table_row(cells: Sequence[str]) -> str:
    """把一行单元格按列宽拼起来。"""
    parts = [
        _cell(cell, width, align)
        for cell, (_, width, align) in zip(cells, _COLUMNS, strict=True)
    ]
    return " " + "  ".join(parts)


def format_report(
    metrics: BatchMetrics,
    outcomes: Sequence[TaskOutcome] = (),
    *,
    title: str = "批量评测报表",
    width: int = 78,
) -> str:
    """渲染成可直接打印的文本报表。"""
    line = "=" * width
    sub = "-" * width
    lines = [line, f" {title}", line]

    if outcomes:
        lines.append(_table_row([name for name, _, _ in _COLUMNS]))
        for index, item in enumerate(outcomes, 1):
            lines.append(
                _table_row(
                    [
                        str(index),
                        item.task_id[:18],
                        item.status,
                        "-" if item.score is None else str(item.score),
                        item.grade or "-",
                        str(item.iterations),
                        f"{item.duration_ms / 1000:.1f}s",
                        f"{item.cost:.6f}",
                    ]
                )
            )
        lines.append(sub)

    lines.append(f" 任务数        {metrics.tasks}")
    lines.append(
        f" 完成 / 收口 / 失败  {metrics.completed} / {metrics.aborted} / {metrics.failed}"
        f"    完成率 {metrics.completion_rate * 100:.1f}%"
        f"    取消 {metrics.canceled}"
    )
    if metrics.avg_score is None:
        lines.append(f" 平均分        未评测（judged={metrics.judged}）")
    else:
        lines.append(f" 平均分        {metrics.avg_score:.2f} / 10（judged={metrics.judged}）")
        distribution = "  ".join(
            f"{grade}:{metrics.grade_distribution.get(grade, 0)}" for grade in GRADE_ORDER
        )
        lines.append(f" 等级分布      {distribution}")
    lines.append(f" 平均迭代      {metrics.avg_iterations:.2f} 轮")
    lines.append(
        f" 耗时          总计 {metrics.total_duration_ms / 1000:.1f}s"
        f"    平均 {metrics.avg_duration_ms / 1000:.1f}s/任务"
    )
    lines.append(
        f" 成本          总计 ¥{metrics.total_cost:.6f}"
        f"    平均 ¥{metrics.avg_cost:.6f}/任务    token {metrics.total_tokens}"
    )
    if metrics.tool_calls:
        lines.append(
            f" 工具          调用 {metrics.tool_calls} 次，失败 {metrics.tool_failures} 次"
            f"    成功率 {metrics.tool_success_rate * 100:.1f}%"
        )
    else:
        # 0 次调用时成功率没有定义，写 0% 会被误读成「全部失败」
        lines.append(" 工具          本批未发生工具调用（任务不需要外部工具）")
    lines.append(line)
    return "\n".join(lines)


__all__ = [
    "GRADE_ORDER",
    "SUITE_ROW_KEYS",
    "BatchMetrics",
    "TaskOutcome",
    "format_report",
    "latency_success_only",
    "make_suite_row",
    "percentile_nearest_rank",
    "summarize",
    "summarize_suite",
]
