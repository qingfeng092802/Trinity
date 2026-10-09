"""P2 全链路评测台 · **冻结数据契约**（唯一真源）。

本模块是评测台所有新模块（``taskset`` / ``assertions`` / ``harness`` / ``baseline``）
的公共依赖：它们**只依赖本模块**，因此可以并行开发，且不会各自造一套口径。
字段与语义逐条对齐 ``docs/p2_eval_harness_design.md`` §3.2 / §3.4 / §4。

设计要点（跨模块约定，勿在本模块之外复制）
------------------------------------------

* **规范化产物**：两执行通道（直调 / HTTP）各自把原始数据映射成同一个
  :class:`TaskRun`，断言引擎**只吃** ``TaskRun``。见 §3.2。
* **``tool_calls`` 权威口径**：优先取 ``task_events`` 的 ``tool_call`` 事件数，
  不可用时回退旧 ``traces`` 表；**必须**用 :data:`TOOL_SOURCE_TASK_EVENTS` /
  :data:`TOOL_SOURCE_TRACES` 记录实际用了哪个源（不同源的数字不可跨基线直接比较）。
* **``steps`` 权威口径**：= **节点执行次数**（= ``node_end`` 事件数 =
  ``len(TraceStore.for_task())``），**不是** ``state["iteration"]``。
  实证：``core/agent/reviewer.py:74`` 为 ``iteration = state.iteration + (0 if passed else 1)``
  ——通过时不加一，故 ``iterations`` 是「被 reviewer 打回的轮数」，首轮成功任务会得 0。
* **成本单位 CNY 元**，一律 ``round(x, 6)``；比率一律 ``round(x, 4)``；
  时间一律北京时间 ISO-8601 ``+08:00``（复用 ``core.llm.pricing.now`` / ``api.schemas.to_cn``）。

⚠️ **隔离库硬约束（供 ``harness.py`` 使用，务必遵守）**
------------------------------------------------------
``data/trinity.db`` **不只是任务库**，它同时是 **RAG 向量库**
（``documents`` / ``chunks`` / ``knowledge_vec*`` 索引与 ``knowledge_meta`` 都在同一个文件）。
因此：

* **绝不能用「空库」跑评测** —— 空库下 ``knowledge_search`` 查不到任何文档，
  所有检索类任务必然失败，指标毫无意义。
* 「隔离库」的正确做法是 **现有库的副本**（连同 ``documents`` / ``chunks`` / 向量索引一起复制），
  或直接复用运行库（只读读取，见 :data:`TaskRun.meta` 的 ``db_path`` 约定）。
* :class:`TaskRun` 预留 ``meta["db_path"]`` 记录本次运行实际使用的库路径，
  便于报告里自证「跑的是哪个知识库」。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# 口径常量（唯一真源；其余模块一律 import 本处，不得自造字符串）
# --------------------------------------------------------------------------- #

#: 执行通道
CHANNEL_DIRECT = "direct"
CHANNEL_API = "api"
CHANNELS: tuple[str, ...] = (CHANNEL_DIRECT, CHANNEL_API)

#: ``tool_calls`` / ``tool_sequence`` 的取源标识（写进报告用于口径溯源）
TOOL_SOURCE_TASK_EVENTS = "task_events"
TOOL_SOURCE_TRACES = "traces"
TOOL_SOURCES: tuple[str, ...] = (TOOL_SOURCE_TASK_EVENTS, TOOL_SOURCE_TRACES)

#: 任务级终态（与 ``api.constants`` 的任务 status 命名空间一致，勿与事件级混用）
STATUS_DONE = "done"
STATUS_ABORTED = "aborted"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
STATUS_UNKNOWN = "unknown"
TASK_STATUSES: tuple[str, ...] = (
    STATUS_DONE,
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_CANCELED,
    STATUS_UNKNOWN,
)

#: ``terminal_status`` 断言的默认可接受终态（可被任务用 ``accepted_status`` 放宽）
DEFAULT_ACCEPTED_STATUS: tuple[str, ...] = (STATUS_DONE,)

#: 断言名枚举（``snake_case``，见设计文档 §9.1）
ASSERT_RESULT_CONTAINS = "result_contains"
ASSERT_TOOL_SEQUENCE = "tool_sequence"
ASSERT_MAX_STEPS = "max_steps"
ASSERT_TERMINAL_STATUS = "terminal_status"
ASSERT_NO_TOOL_FAILURE = "no_tool_failure"
ASSERT_MAX_TOOL_CALLS = "max_tool_calls"
ASSERT_MAX_COST = "max_cost"
ASSERT_MAX_LATENCY = "max_latency"
ASSERT_NO_FABRICATION = "no_fabrication"
ASSERTION_NAMES: tuple[str, ...] = (
    ASSERT_RESULT_CONTAINS,
    ASSERT_TOOL_SEQUENCE,
    ASSERT_MAX_STEPS,
    ASSERT_TERMINAL_STATUS,
    ASSERT_NO_TOOL_FAILURE,
    ASSERT_MAX_TOOL_CALLS,
    ASSERT_MAX_COST,
    ASSERT_MAX_LATENCY,
    ASSERT_NO_FABRICATION,
)

#: 指标名（baseline diff / SuiteMetrics 共用键名，避免两套口径）
METRIC_PASS_RATE = "pass_rate"
METRIC_TOOL_ACCURACY = "tool_accuracy"
METRIC_AVG_STEPS = "avg_steps"
METRIC_AVG_COST = "avg_cost"
METRIC_P95_LATENCY = "p95_latency_ms"
METRIC_KEYS: tuple[str, ...] = (
    METRIC_PASS_RATE,
    METRIC_TOOL_ACCURACY,
    METRIC_AVG_STEPS,
    METRIC_AVG_COST,
    METRIC_P95_LATENCY,
)

# --------------------------------------------------------------------------- #
# 波动容忍带（设计文档 §3.4）——单次运行用固定带；``repeat>1`` 时带 = max(固定带, 2×std)
# --------------------------------------------------------------------------- #

#: 通过率固定容忍带：±5 个百分点
TOLERANCE_PASS_RATE: float = 0.05
#: 工具准确率固定容忍带：±5 个百分点
TOLERANCE_TOOL_ACCURACY: float = 0.05
#: 平均步数固定容忍带：±0.5 步
TOLERANCE_AVG_STEPS: float = 0.5
#: 平均成本固定容忍带：±20%（相对）
TOLERANCE_AVG_COST_REL: float = 0.20
#: P95 延迟固定容忍带：±30%（相对）
TOLERANCE_P95_LATENCY_REL: float = 0.30


@dataclass(frozen=True, slots=True)
class Tolerances:
    """一组波动容忍带（越小越敏感）。

    绝对带（``pass_rate`` / ``tool_accuracy`` / ``avg_steps``）单位同指标本身；
    相对带（``avg_cost_rel`` / ``p95_latency_rel``）是比例，判定时乘以基线值。
    """

    pass_rate: float = TOLERANCE_PASS_RATE
    tool_accuracy: float = TOLERANCE_TOOL_ACCURACY
    avg_steps: float = TOLERANCE_AVG_STEPS
    avg_cost_rel: float = TOLERANCE_AVG_COST_REL
    p95_latency_rel: float = TOLERANCE_P95_LATENCY_REL

    @classmethod
    def for_task_count(cls, task_count: int) -> Tolerances:
        """小样本下收紧通过率/工具准确率容忍带的写法。

        设计文档 §3.4：``pass_rate`` 固定 ±5 个百分点，**小样本再取 ±1/任务数**，
        即单条任务翻转（``1/N``）不应被当成趋势。
        """
        if task_count <= 0:
            return cls()
        floor = 1.0 / task_count
        return cls(
            pass_rate=max(TOLERANCE_PASS_RATE, floor),
            tool_accuracy=max(TOLERANCE_TOOL_ACCURACY, floor),
        )

    def widened(self, std_by_metric: Mapping[str, float]) -> Tolerances:
        """``repeat>1`` 时按 ``max(固定带, 2×std)`` 放宽。

        Args:
            std_by_metric: 指标名 → 多次重复采样的标准差；缺省项保持固定带。
                **单位约定**：绝对带指标（``pass_rate`` / ``tool_accuracy`` /
                ``avg_steps``）传**绝对值**标准差（与指标同单位）；相对带指标
                （``avg_cost`` / ``p95_latency_ms``）传**相对比例**标准差
                （即 ``std / mean``，无量纲，与固定带同为比例），否则会与
                固定带发生量纲错配。
        """
        return Tolerances(
            pass_rate=max(self.pass_rate, 2.0 * std_by_metric.get(METRIC_PASS_RATE, 0.0)),
            tool_accuracy=max(
                self.tool_accuracy, 2.0 * std_by_metric.get(METRIC_TOOL_ACCURACY, 0.0)
            ),
            avg_steps=max(self.avg_steps, 2.0 * std_by_metric.get(METRIC_AVG_STEPS, 0.0)),
            avg_cost_rel=max(self.avg_cost_rel, 2.0 * std_by_metric.get(METRIC_AVG_COST, 0.0)),
            p95_latency_rel=max(
                self.p95_latency_rel, 2.0 * std_by_metric.get(METRIC_P95_LATENCY, 0.0)
            ),
        )

    def as_dict(self) -> dict[str, float]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "pass_rate": self.pass_rate,
            "tool_accuracy": self.tool_accuracy,
            "avg_steps": self.avg_steps,
            "avg_cost_rel": self.avg_cost_rel,
            "p95_latency_rel": self.p95_latency_rel,
        }


def pass_rate_tolerance(task_count: int, base: Tolerances | None = None) -> float:
    """便捷函数：给定任务数返回通过率的绝对容忍带。"""
    resolved = base if base is not None else Tolerances.for_task_count(task_count)
    return resolved.pass_rate


# --------------------------------------------------------------------------- #
# 归一化与舍入（断言与任务集共用的口径，禁止各处重写）
# --------------------------------------------------------------------------- #
def normalize(text: Any) -> str:
    """期望/实际文本的**唯一**归一化函数（设计文档 §3.1）。

    NFKC 全半角统一 → 去掉所有空白 → ASCII 小写。
    这样 ``450 元`` / ``450元`` / ``４５０元`` 等价，断言不会因排版差异误判。
    """
    if text is None:
        return ""
    composed = unicodedata.normalize("NFKC", str(text))
    return "".join(ch for ch in composed if not ch.isspace()).lower()


def round_cost(value: float) -> float:
    """成本一律 ``round(x, 6)``（CNY 元）。"""
    return round(float(value), 6)


def round_ratio(value: float) -> float:
    """比率一律 ``round(x, 4)``。"""
    return round(float(value), 4)


# --------------------------------------------------------------------------- #
# 规范化产物 TaskRun（断言引擎的唯一输入）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class TaskRun:
    """一次任务执行的**规范化产物**：两通道统一的出口。

    字段口径来源见类 docstring 上方模块说明与设计文档 §3.2 / §3.3。
    """

    task_id: str
    final_answer: str
    status: str
    """任务级终态：done / aborted / failed / canceled / unknown（见模块级 STATUS_*）。"""

    steps: int
    """节点执行次数（= ``node_end`` 事件数 = ``len(TraceStore.for_task())``）。"""

    iterations: int
    """被 reviewer 打回的轮数（真实语义，仅作旁参，**不要**当作步数）。"""

    tool_sequence: list[str]
    """有序工具名（已按 ``event_seq`` / ``(step, timestamp)`` 排序）。"""

    tool_calls: int
    """= ``len(tool_sequence)``（权威口径）。"""

    tool_failures: int
    """工具调用失败次数（``status != success`` 的调用条数）。"""

    cost: float
    """本次执行估算成本（CNY 元，``round(x, 6)``）。"""

    duration_ms: int
    """节点耗时求和（主延迟口径，去掉排队等待）。"""

    channel: str
    """执行通道：direct / api（见模块级 CHANNEL_*）。"""

    tool_source: str
    """工具序列的取源：task_events / traces（见模块级 TOOL_SOURCE_*）。"""

    event_range: tuple[int, int] | None = None
    """``(min_seq, max_seq)``，用于取证跳转 ``GET /tasks/{id}/trace``。"""

    error: str | None = None
    """失败原因（``status`` 非 done 时宜非空）。"""

    raw_summary: dict[str, Any] = field(default_factory=dict)
    """通道原始摘要（grade / progress / token 等），仅作排查，不参与断言。"""

    wall_ms: int = 0
    """墙钟耗时（含排队；HTTP 通道才显著），与 ``duration_ms`` 分列避免口径混淆。"""

    score: int | None = None
    """LLM Judge 主指标（数值）。基线主指标用它；``None`` 表示该任务未评分。"""

    grade: str | None = None
    """附属等级标签，**可为 None**（不得因 ``None`` 判失败，见设计文档 Q7）。"""

    meta: dict[str, Any] = field(default_factory=dict)
    """额外元信息。预留键 ``db_path``：本次运行实际使用的 SQLite 库路径
    （**必须是含 RAG 索引的现有库或其副本，不能是空库**，见模块 docstring）。"""

    # ----------------------------------------------------------- 便捷方法 --
    def is_done(self) -> bool:
        """是否以 ``done`` 收口。"""
        return self.status == STATUS_DONE

    def tool_sequence_collapsed(self) -> list[str]:
        """折叠**连续重复**后的工具序列（``[ks, ks, ks] → [ks]``）。

        真实任务里一个 3 步计划会产生 3 条同名 ``knowledge_search``，
        工具断言默认按折叠后序列比较（设计文档 §3.1 ``collapse_repeats``）。
        """
        collapsed: list[str] = []
        for name in self.tool_sequence:
            if not collapsed or collapsed[-1] != name:
                collapsed.append(name)
        return collapsed

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典（``event_range`` 元组转列表）。"""
        return {
            "task_id": self.task_id,
            "final_answer": self.final_answer,
            "status": self.status,
            "steps": self.steps,
            "iterations": self.iterations,
            "tool_sequence": list(self.tool_sequence),
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "cost": self.cost,
            "duration_ms": self.duration_ms,
            "channel": self.channel,
            "tool_source": self.tool_source,
            "event_range": list(self.event_range) if self.event_range is not None else None,
            "error": self.error,
            "raw_summary": dict(self.raw_summary),
            "wall_ms": self.wall_ms,
            "score": self.score,
            "grade": self.grade,
            "meta": dict(self.meta),
        }


# --------------------------------------------------------------------------- #
# 断言结果
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AssertionOutcome:
    """单条断言的结构化结果（便于报告与 diff）。"""

    name: str
    """断言名（见模块级 ASSERT_*，``snake_case`` 固定枚举）。"""

    passed: bool
    expected: Any
    actual: Any
    reason: str
    """★ 人话失败原因——唯一归因入口。"""

    evidence: dict[str, Any] = field(default_factory=dict)
    """★ 取证字段；失败必须能归因，否则等于没测（设计文档 §3.2）。"""

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class TaskAssertionResult:
    """单任务的断言汇总（``passed = all(outcomes.passed)``，AND 语义）。"""

    task_id: str
    passed: bool
    outcomes: list[AssertionOutcome] = field(default_factory=list)

    @classmethod
    def from_outcomes(
        cls, task_id: str, outcomes: Sequence[AssertionOutcome]
    ) -> TaskAssertionResult:
        """由断言列表构造，``passed`` 按 AND 语义计算。"""
        items = list(outcomes)
        return cls(task_id=task_id, passed=all(o.passed for o in items), outcomes=items)

    @property
    def failed_outcomes(self) -> list[AssertionOutcome]:
        """未通过的断言（报告里优先展示）。"""
        return [o for o in self.outcomes if not o.passed]

    def failed_names(self) -> list[str]:
        """未通过的断言名清单。"""
        return [o.name for o in self.outcomes if not o.passed]

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "outcomes": [o.as_dict() for o in self.outcomes],
            "failed_assertions": self.failed_names(),
        }


# --------------------------------------------------------------------------- #
# 套件指标 SuiteMetrics（设计文档 §4）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SuiteMetrics:
    """一批任务的汇总指标（与既有 ``metrics.BatchMetrics`` 口径分工明确）。

    口径（设计文档 §4，逐条精确）：

    * ``attempted = evaluated`` —— 实际执行并拿到结果的条数（含 failed/aborted/canceled）。
    * ``pass_rate = passed / attempted``；**失败/超时计入分母**，分子记 0（不美化数字）。
    * ``tool_accuracy`` 分母 = **有工具期望的任务数**（``|T|``）；``|T| == 0`` 时返回 ``None``。
    * ``avg_steps = Σ steps / attempted``（失败也有投入，计入）。
    * 成本：``total_cost`` 求和、``avg_cost`` 均值，均 ``round(x, 6)``；失败也烧 token，计入。
    * 延迟主口径 = ``duration_ms``；分位用 nearest-rank（写死算法保证可复现）。
    * 空集（``attempted == 0``）：比率返回 0.0，均值返回 0.0，可空项返回 ``None``。
    """

    evaluated: int = 0
    skipped: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    tool_accuracy: float | None = None
    tool_expected_tasks: int = 0
    tool_accuracy_soft: float | None = None
    avg_steps: float = 0.0
    avg_iterations: float = 0.0
    avg_tool_calls: float = 0.0
    tool_calls: int = 0
    tool_failures: int = 0
    tool_call_success_rate: float = 0.0
    total_cost: float = 0.0
    avg_cost: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    wall_ms: int = 0
    std: dict[str, float] = field(default_factory=dict)
    """``repeat>1`` 时逐指标的多次采样标准差（键名见模块级 METRIC_*）。"""

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典（比率 ``round(,4)``，成本 ``round(,6)``）。"""
        return {
            "evaluated": self.evaluated,
            "skipped": self.skipped,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round_ratio(self.pass_rate),
            "tool_accuracy": (
                None if self.tool_accuracy is None else round_ratio(self.tool_accuracy)
            ),
            "tool_expected_tasks": self.tool_expected_tasks,
            "tool_accuracy_soft": (
                None if self.tool_accuracy_soft is None else round_ratio(self.tool_accuracy_soft)
            ),
            "avg_steps": round(self.avg_steps, 3),
            "avg_iterations": round(self.avg_iterations, 3),
            "avg_tool_calls": round(self.avg_tool_calls, 3),
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "tool_call_success_rate": round_ratio(self.tool_call_success_rate),
            "total_cost": round_cost(self.total_cost),
            "avg_cost": round_cost(self.avg_cost),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p50_latency_ms": round(self.p50_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "max_latency_ms": round(self.max_latency_ms, 1),
            "wall_ms": self.wall_ms,
            "std": {k: round(float(v), 6) for k, v in self.std.items()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SuiteMetrics:
        """从 ``as_dict`` 输出还原（缺失键用默认值，便于新旧基线兼容）。"""
        data = dict(payload)
        known = cls.__dataclass_fields__  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


# --------------------------------------------------------------------------- #
# 基线模型与 diff（设计文档 §3.4）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class MetricDelta:
    """单个指标的基线 → 当前差异。"""

    name: str
    baseline: float | None
    current: float | None
    delta: float | None
    """绝对差（``current - baseline``）；任一为空则 ``None``。"""

    delta_pct: float | None
    """相对差（``delta / baseline``）；基线为 0 或空则 ``None``。"""

    direction: str
    """``up`` / ``down`` / ``flat`` / ``undetermined``。"""

    tolerance: float | None = None
    """判定用的容忍带（绝对带单位同指标；相对带已折算为绝对值）。"""

    within_tolerance: bool = False
    """``True`` 表示「无显著变化（在波动带内）」。"""

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "name": self.name,
            "baseline": self.baseline,
            "current": self.current,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "direction": self.direction,
            "tolerance": self.tolerance,
            "within_tolerance": self.within_tolerance,
        }


@dataclass(slots=True)
class BaselineModel:
    """一次「晋级」后的基线快照（``evaluation/baselines/<name>.json``）。

    ``taskset`` / ``model`` / ``prompts`` / ``code_fingerprint`` 是可比性的**最小集**：
    缺任何一项，「改 Prompt 后指标变了」就无法归因（设计文档 §3.4）。
    """

    schema_version: int = 1
    created_at: str = ""
    taskset: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    prompts: dict[str, Any] = field(default_factory=dict)
    code_fingerprint: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    channel: str = CHANNEL_DIRECT
    repeat: int = 1
    metrics: SuiteMetrics = field(default_factory=SuiteMetrics)
    per_task: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "taskset": dict(self.taskset),
            "model": dict(self.model),
            "prompts": dict(self.prompts),
            "code_fingerprint": dict(self.code_fingerprint),
            "config": dict(self.config),
            "channel": self.channel,
            "repeat": self.repeat,
            "metrics": self.metrics.as_dict(),
            "per_task": [dict(item) for item in self.per_task],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BaselineModel:
        """从 JSON 字典还原。"""
        data = dict(payload)
        metrics_raw = data.pop("metrics", {}) or {}
        per_task = list(data.pop("per_task", []) or [])
        known = cls.__dataclass_fields__  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        return cls(metrics=SuiteMetrics.from_dict(metrics_raw), per_task=per_task, **clean)


@dataclass(slots=True)
class BaselineDiff:
    """基线对比结果（可比性警告 + 逐指标 delta + 逐任务回归/改善清单）。"""

    comparability_warnings: list[str] = field(default_factory=list)
    comparable: bool = True
    metric_deltas: dict[str, MetricDelta] = field(default_factory=dict)
    regressed: list[str] = field(default_factory=list)
    """``pass`` → ``fail`` 的任务 id。"""

    improved: list[str] = field(default_factory=list)
    """``fail`` → ``pass`` 的任务 id。"""

    changed: list[str] = field(default_factory=list)
    """指标变化超容忍带的任务 id。"""

    unchanged: list[str] = field(default_factory=list)
    aborted_prematurely: bool = False

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "comparability_warnings": list(self.comparability_warnings),
            "comparable": self.comparable,
            "metric_deltas": {k: v.as_dict() for k, v in self.metric_deltas.items()},
            "regressed": list(self.regressed),
            "improved": list(self.improved),
            "changed": list(self.changed),
            "unchanged": list(self.unchanged),
            "aborted_prematurely": self.aborted_prematurely,
        }


__all__ = [
    "ASSERTION_NAMES",
    "ASSERT_MAX_COST",
    "ASSERT_MAX_LATENCY",
    "ASSERT_MAX_STEPS",
    "ASSERT_MAX_TOOL_CALLS",
    "ASSERT_NO_FABRICATION",
    "ASSERT_NO_TOOL_FAILURE",
    "ASSERT_RESULT_CONTAINS",
    "ASSERT_TERMINAL_STATUS",
    "ASSERT_TOOL_SEQUENCE",
    "CHANNELS",
    "CHANNEL_API",
    "CHANNEL_DIRECT",
    "DEFAULT_ACCEPTED_STATUS",
    "METRIC_AVG_COST",
    "METRIC_AVG_STEPS",
    "METRIC_KEYS",
    "METRIC_PASS_RATE",
    "METRIC_P95_LATENCY",
    "METRIC_TOOL_ACCURACY",
    "STATUS_ABORTED",
    "STATUS_CANCELED",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_UNKNOWN",
    "TASK_STATUSES",
    "TOLERANCE_AVG_COST_REL",
    "TOLERANCE_AVG_STEPS",
    "TOLERANCE_PASS_RATE",
    "TOLERANCE_P95_LATENCY_REL",
    "TOLERANCE_TOOL_ACCURACY",
    "TOOL_SOURCES",
    "TOOL_SOURCE_TASK_EVENTS",
    "TOOL_SOURCE_TRACES",
    "AssertionOutcome",
    "BaselineDiff",
    "BaselineModel",
    "MetricDelta",
    "SuiteMetrics",
    "TaskAssertionResult",
    "TaskRun",
    "Tolerances",
    "normalize",
    "pass_rate_tolerance",
    "round_cost",
    "round_ratio",
]
