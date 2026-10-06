"""Agent 节点的共享基础设施。

包含四件事：
1. :class:`NodeContext` —— 节点运行上下文的显式注入（LLM / 配置 / 埋点 / 工具层）；
2. :class:`BaseNode` —— 节点基类，统一异常兜底、耗时统计与 trace 埋点；
3. :class:`TraceRecord` + :class:`TraceSink` —— 埋点数据结构与出口协议
   （阶段 3 直接在其上加内存 + SQLite 双写，结构不再变动）；
4. :func:`render_prompt` —— 从 ``core/llm/prompts/<version>/`` 加载提示词模板。
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from api.constants import (
    STATUS_EVENT_FAILED,
    STATUS_SUCCESS,
    STATUS_EVENT_TIMEOUT,
    TASK_EVT_LLM_CALL,
    TASK_EVT_NODE_END,
    TASK_EVT_TOOL_CALL,
)
from config import PROJECT_ROOT, Settings, get_settings
from core.events import AnswerStream, EventRecord, TaskEventSink, UsageSink
from core.llm.adapter import LLMAdapter, Usage, get_adapter
from core.workflow.state import (
    AgentRole,
    AgentState,
    StateUpdate,
    ToolCallRecord,
    WorkflowConfig,
)

logger = logging.getLogger(__name__)

#: 节点 / 工具的局部状态 → ``task_events.status`` 事件状态映射。
#: 两侧命名空间刻意分开（设计文档 §3.2 / K3）：事件 status 描述**单条事件**的
#: 成败（success/failed/timeout），任务 status 描述**整条任务**的状态机。
_EVENT_STATUS: dict[str, str] = {
    "success": STATUS_SUCCESS,
    "failed": STATUS_EVENT_FAILED,
    "timeout": STATUS_EVENT_TIMEOUT,
}


# --------------------------------------------------------------------------- #
# 可观测：埋点数据结构与出口
# --------------------------------------------------------------------------- #
class TraceRecord(BaseModel):
    """节点级埋点事件（字段与手册的 TraceRecord 契约一致）。"""

    trace_id: str = Field(description="单条埋点的唯一 id")
    task_id: str = Field(description="所属任务 id")
    step: int = Field(description="编排轮次（0 起，跨角色可比）：planner=0，executor/reviewer=N-1")
    role: AgentRole = Field(description="产生该埋点的角色")
    input: str = Field(description="节点输入摘要")
    output: str = Field(description="节点输出摘要")
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list, description="本次调用涉及的工具记录"
    )
    timestamp: float = Field(description="Unix 时间戳（秒）")
    duration_ms: int = Field(description="节点耗时（毫秒）")
    status: Literal["success", "failed", "timeout"] = Field(description="本次节点执行状态")
    token_in: int = Field(default=0, description="本次调用消耗的输入 token")
    token_out: int = Field(default=0, description="本次调用消耗的输出 token")
    cost: float = Field(default=0.0, description="本次调用估算成本（元人民币）")


class TraceSink(Protocol):
    """埋点出口协议。任何 ``Callable[[TraceRecord], None]`` 都满足它。"""

    def __call__(self, record: TraceRecord) -> None:  # pragma: no cover - 协议声明
        ...


class ListTraceSink:
    """把埋点收集到内存列表：demo、测试与阶段 4 的轨迹回放页都用它。"""

    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def __call__(self, record: TraceRecord) -> None:
        self.records.append(record)

    def for_task(self, task_id: str) -> list[TraceRecord]:
        """按任务 id 过滤，便于回放单次运行。"""
        return [record for record in self.records if record.task_id == task_id]

    def summary(self) -> dict[str, Any]:
        """汇总埋点：次数、成功率、总耗时与总成本。"""
        if not self.records:
            return {"count": 0, "failed": 0, "duration_ms": 0, "cost": 0.0}
        return {
            "count": len(self.records),
            "failed": sum(1 for record in self.records if record.status != "success"),
            "duration_ms": sum(record.duration_ms for record in self.records),
            "cost": round(sum(record.cost for record in self.records), 6),
        }


# --------------------------------------------------------------------------- #
# 工具层接口（阶段 2 的 registry + sandbox 在结构上满足它，无需继承）
# --------------------------------------------------------------------------- #
@runtime_checkable
class ToolInvoker(Protocol):
    """工具层最小接口。"""

    def describe(self) -> str:
        """返回给提示词看的工具清单文本；没有可用工具时返回空字符串。"""
        ...  # pragma: no cover - 协议声明

    def call(self, name: str, args: dict[str, Any]) -> ToolCallRecord:
        """执行一次工具调用，需自行把异常转成 ``status="failed"`` 的记录。"""
        ...  # pragma: no cover - 协议声明


# --------------------------------------------------------------------------- #
# 提示词加载
# --------------------------------------------------------------------------- #
class PromptNotFoundError(FileNotFoundError):
    """提示词文件缺失。"""


class PromptRenderError(ValueError):
    """提示词变量未提供完整。"""


def prompt_path(role: str, version: str = "v1") -> Path:
    """返回提示词文件路径：``core/llm/prompts/<version>/<role>.md``。"""
    return PROJECT_ROOT / "core" / "llm" / "prompts" / version / f"{role}.md"


def load_prompt(role: str, version: str = "v1") -> Template:
    """加载提示词模板。

    用 ``string.Template``（``$var``）而不是 ``str.format``：提示词里塞满了 JSON
    示例，花括号满地都是，用 format 得逐个写 ``{{}}``，极易漏。
    """
    path = prompt_path(role, version)
    if not path.is_file():
        raise PromptNotFoundError(f"提示词不存在：{path}")
    return Template(path.read_text(encoding="utf-8"))


def render_prompt(role: str, version: str = "v1", **values: Any) -> str:
    """渲染提示词；缺变量直接报错，避免把带 ``$var`` 的半成品发给模型。"""
    try:
        return load_prompt(role, version).substitute(**values)
    except KeyError as exc:
        raise PromptRenderError(f"提示词 {role}/{version} 缺少变量：{exc}") from exc


# --------------------------------------------------------------------------- #
# 运行上下文
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class NodeContext:
    """节点运行上下文：把依赖显式注入，测试时整包替换即可。

    Args:
        llm: LLM 适配器（测试传 Mock，生产传真实 adapter）。
        config: 编排参数。
        settings: 全局配置，节点取模型名等参数用。
        trace_sink: 埋点出口，None 表示不埋点（旧 traces 表，已冻结）。
        tool_invoker: 工具层，None 表示当前无可用工具（阶段 1 的默认值）。
        event_sink: **轨迹事件**落盘出口（``task_events`` 唯一真源）；None 表示
            不落事件（测试默认）。与 ``trace_sink`` 是两条独立链路：
            前者服务「可回放的历史」，后者服务「TaskOutcome 汇总」。
        answer_stream: **答案增量**出口（SSE ``delta`` 帧的源头）；None 表示这一条
            不流式。与 ``event_sink`` 同样是「可选出口」：没有它，节点逻辑
            一字不变，只是屏上没有逐段出现的文字。
        usage_sink: **用量增量**出口（SSE ``usage`` 帧）；None 同理。
    """

    llm: LLMAdapter
    config: WorkflowConfig
    settings: Settings
    trace_sink: TraceSink | None = None
    tool_invoker: ToolInvoker | None = None
    event_sink: TaskEventSink | None = None
    answer_stream: AnswerStream | None = None
    usage_sink: UsageSink | None = None

    @classmethod
    def create(
        cls,
        *,
        llm: LLMAdapter | None = None,
        config: WorkflowConfig | None = None,
        settings: Settings | None = None,
        trace_sink: TraceSink | None = None,
        tool_invoker: ToolInvoker | None = None,
        event_sink: TaskEventSink | None = None,
        answer_stream: AnswerStream | None = None,
        usage_sink: UsageSink | None = None,
    ) -> NodeContext:
        """按需注入，未传的部分取全局默认值。"""
        resolved_settings = settings or get_settings()
        return cls(
            llm=llm if llm is not None else get_adapter(),
            config=config or WorkflowConfig.from_settings(resolved_settings),
            settings=resolved_settings,
            trace_sink=trace_sink,
            tool_invoker=tool_invoker,
            event_sink=event_sink,
            answer_stream=answer_stream,
            usage_sink=usage_sink,
        )


# --------------------------------------------------------------------------- #
# 节点基类
# --------------------------------------------------------------------------- #
class BaseNode(ABC):
    """节点基类。

    子类只需实现 :meth:`run`（纯业务逻辑，返回状态增量）；
    :meth:`__call__` 是 LangGraph 的节点入口，负责把任何异常收敛成
    ``status="failed"`` 的增量，并在出口处补一条埋点。
    """

    #: 角色名，子类必须覆盖
    role: ClassVar[AgentRole] = "planner"

    #: 本节点是否**自己**按"每次 LLM 调用一条"落 ``llm_call``（executor = True）。
    #:
    #: 为什么需要这个开关（2026-10-02，审查报告 Q6-01）：executor 一次节点调用里
    #: 跑完整轮计划（``for index in range(cursor, len(plan))``，``executor.py:84``），
    #: 每步一次**真实付费**调用，而出口这条汇总事件只取 ``last_usage`` = 最后一步的用量
    #: ⇒ N 步只记 1 笔，成本闸门 / ``tasks.cost`` / 成本面板 / 报表一起少算。
    #: 修法是"一步一条"（:meth:`_emit_llm_call_event`），而出口那条必须**跟着关掉**，
    #: 否则最后一步被计两遍。关掉的前提是"本轮真的落过至少一条"，见 :meth:`_emit_events`
    #: 里 L1 那个条件。planner / reviewer 每次节点调用只调一次 LLM，保持 False = 行为不变。
    per_call_llm_events: ClassVar[bool] = False

    def __init__(self, ctx: NodeContext) -> None:
        self.ctx = ctx
        #: 本次节点调用里由 :meth:`_emit_llm_call_event` 实际落成的条数。
        #: 在 :meth:`__call__` 开头重置；节点实例是**每任务一份**
        #: （``api/runner.py:166`` 每次 build 都新建图与新节点），故放实例上不会跨任务串。
        self._llm_calls_logged = 0

    # ---- 便捷访问 ----
    @property
    def settings(self) -> Settings:
        return self.ctx.settings

    @property
    def config(self) -> WorkflowConfig:
        return self.ctx.config

    @property
    def llm(self) -> LLMAdapter:
        return self.ctx.llm

    # ---- LangGraph 入口 ----
    def __call__(self, state: AgentState) -> StateUpdate:
        started = time.perf_counter()
        # 每次节点调用重新计：executor 的循环会往里加，出口的 L1 要看它的数决定发不发。
        self._llm_calls_logged = 0
        status: Literal["success", "failed", "timeout"] = "success"
        # 调用前记录本线程的用量快照，用于判定「本次节点是否**真的**发生过 LLM 调用」。
        # 判据是对象**身份**而非数值：真实适配器与 Mock 每次调用都会把 ``last_usage``
        # 换成一个**新对象**（``adapter._call`` / ``MockLLMAdapter.invoke_json`` 里的
        # ``self.last_usage = Usage(...)``），故「调用后 is not 调用前」⇔ 发生过调用；
        # 未调用时读到的是同一个（惰性缓存的）对象。这样才能覆盖 U4 漏掉的
        # 「本次根本没调用」分支——该槽位线程本地且从不清空，旧实现会把上一次调用的
        # 残留当成本次用量。
        usage_before = getattr(self.llm, "last_usage", None)
        try:
            update = self.run(state)
            if update.get("status") == "failed":
                status = "failed"
        except Exception as exc:  # 节点边界必须兜住一切，转成失败增量
            logger.exception("[%s] 节点执行失败", self.role)
            update = {
                "status": "failed",
                "review_comment": f"{self.role} 异常：{type(exc).__name__}: {exc}",
                "final_answer": state.get("final_answer", ""),
            }
            status = "failed"

        duration_ms = int((time.perf_counter() - started) * 1000)
        usage_after = getattr(self.llm, "last_usage", None)
        # 「本次节点是否真的调用过 LLM」的**显式信号**（缺陷 2 修复）：
        #   1) 用量对象身份变了 → 一定成功发生过一次调用；
        #   2) 或节点产出了非空状态增量 → 节点确实执行了业务（调用抛错时用量不会更新，
        #      但节点返回了失败增量，仍应记一条 failed 的 llm_call 以示「尝试过」）。
        # 被终态守卫 ``if is_terminal(state): return {}`` 短路的节点两条都不满足 →
        # 不写 llm_call（旧实现无条件写且把未知状态兜底成 success，于是给 executor /
        # reviewer 捏造了「成功的 LLM 调用」幻影事件）。
        usage_fresh = usage_after if usage_after is not usage_before else None
        llm_invoked = usage_fresh is not None or bool(update)
        self._emit_trace(state, update, status, duration_ms, llm_invoked, usage_fresh)
        return update

    @abstractmethod
    def run(self, state: AgentState) -> StateUpdate:
        """节点业务逻辑：读状态、调 LLM、返回状态增量。"""

    # ---- 埋点 ----
    def trace_step(self, state: AgentState, update: StateUpdate) -> int:
        """本次事件所属的**编排轮次**（0 起，跨角色可比）。

        语义按设计文档 §1.2 统一定义（这是消灭旧 ``traces`` 错序的关键）：

        * planner 恒在 ``iteration=0`` 时跑 → ``step=0``；
        * 第 N 轮 executor / reviewer：``step = N - 1``（首轮 = 0）；
        * ``state["iteration"]`` 恰好等于「已完成轮数」——reviewer 通过前才自增
          （``reviewer.py:74``），故节点运行瞬间读到的 ``iteration`` 就是 ``N-1``。

        因此**所有角色**都直接取 ``state["iteration"]``；executor 的轮内子步骤
        下标不再混进 ``step``，另开 ``sub_step`` 列（见 ``_emit_tool_events``）。

        Args:
            state: 节点入口状态。
            update: 节点产出的状态增量（保留入参以兼容契约签名，本实现不依赖它）。

        Returns:
            编排轮次，非负整数。
        """
        return max(int(state.get("iteration", 0)), 0)

    def trace_input(self, state: AgentState) -> str:
        """默认取任务文本；子类覆盖成更贴切的输入摘要。"""
        return state.get("task", "")

    def trace_output(self, update: StateUpdate) -> str:
        """默认拼接关键增量字段；子类覆盖成更贴切的输出摘要。"""
        parts: list[str] = []
        for key in ("current_step", "review_score", "review_comment", "final_answer"):
            if key in update:
                value = update[key]
                parts.append(f"{key}={value}")
        return " | ".join(parts)[:2000]

    def _emit_trace(
        self,
        state: AgentState,
        update: StateUpdate,
        status: Literal["success", "failed", "timeout"],
        duration_ms: int,
        llm_invoked: bool,
        usage: Usage | None,
    ) -> None:
        task_id = state.get("task_id", "")
        step = self.trace_step(state, update)
        # ``usage`` 是本节点**本次调用产生的**用量快照；未发生调用时为 ``None``
        # （绝不回读到上一次调用的残留，缺陷 2）。节点级埋点与事件埋点共用它。
        self._emit_events(state, update, status, duration_ms, step, usage, llm_invoked)

        sink = self.ctx.trace_sink
        if sink is None:
            return
        tool_calls: list[dict[str, Any]] = []
        results = update.get("execution_results")
        if results:
            # executor 一次节点调用会跑完整轮计划（多条子步骤），
            # trace 必须聚合**全部**步骤的工具调用，只取 results[-1] 会丢掉
            # 非最后一步的调用（T04 A3 验收：knowledge_search 必须可回放）
            for item in results:
                tool_calls.extend(dict(call) for call in item["tool_calls"])
        sink(
            TraceRecord(
                trace_id=f"{task_id}-{self.role}-{uuid4().hex[:8]}",
                task_id=task_id,
                step=step,
                role=self.role,
                input=self.trace_input(state)[:2000],
                output=self.trace_output(update),
                tool_calls=tool_calls,
                timestamp=time.time(),
                duration_ms=duration_ms,
                status=status,
                token_in=int(getattr(usage, "token_in", 0) or 0),
                token_out=int(getattr(usage, "token_out", 0) or 0),
                cost=float(getattr(usage, "cost", 0.0) or 0.0),
            )
        )

    def _emit_llm_call_event(
        self,
        state: AgentState,
        *,
        step: int,
        sub_step: int,
        thought: str,
        status: Literal["success", "failed", "timeout"] = "success",
        zero_usage: bool = False,
    ) -> bool:
        """按**一次 LLM 调用**落一条 ``llm_call``（给 ``per_call_llm_events`` 的节点用）。

        用量读 ``self.llm.last_usage`` —— 必须**紧跟在那次调用之后**调它：那是线程本地
        且从不清空的槽位（见 :meth:`__call__` 里 U4 那段），晚一步读到的就是下一步
        或上一个节点的残留。模型名与峰谷系数同样只从这份快照取，不重算时钟
        （``Usage.multiplier`` 那条纪律：事后算会整体错 8 小时或跨窗口错档）。

        Args:
            zero_usage: 调用**抛异常**时用 —— 那时 ``last_usage`` 还是上一步的残留，
                照读就会把上一步的钱再计一遍。置 True 则整行记零（token/钱/model 全空），
                语义与 ``usage is None`` 那一档一致："尝试过但没测到用量"，不拿残留冒充。

        Returns:
            是否真落了一条。没有 ``event_sink`` 时返回 ``False``（单测与批量评测不传
            database 就是这一档）—— 此时出口的汇总那条照常工作，行为与改之前一致。
        """
        sink = self.ctx.event_sink
        if sink is None:
            return False
        usage = None if zero_usage else getattr(self.llm, "last_usage", None)
        try:
            sink(
                EventRecord(
                    task_id=state.get("task_id", ""),
                    event_type=TASK_EVT_LLM_CALL,
                    role=self.role,
                    node=self.role,
                    step=step,
                    sub_step=sub_step,
                    thought=thought[:2000],
                    observation="",
                    status=_EVENT_STATUS.get(status, STATUS_SUCCESS),
                    latency_ms=int(getattr(usage, "duration_ms", 0) or 0),
                    tokens_in=int(getattr(usage, "token_in", 0) or 0),
                    tokens_out=int(getattr(usage, "token_out", 0) or 0),
                    cost=float(getattr(usage, "cost", 0.0) or 0.0),
                    model=getattr(usage, "model", "") or None,
                    price_multiplier=getattr(usage, "multiplier", None),
                )
            )
        except Exception:  # noqa: BLE001 - 埋点失败绝不拖垮节点执行（K2 失败隔离）
            logger.warning("[%s] 单步 llm_call 埋点失败（已跳过）", self.role, exc_info=True)
            return False
        self._llm_calls_logged += 1
        return True

    def _emit_events(
        self,
        state: AgentState,
        update: StateUpdate,
        status: Literal["success", "failed", "timeout"],
        duration_ms: int,
        step: int,
        usage: Usage | None,
        llm_invoked: bool,
    ) -> None:
        """把节点的 LLM 调用 / 节点结束 / 工具调用写成 ``task_events`` 行。

        埋点位置（设计文档 §7.2 L1/L2、§7.3 T1）：

        * **L1** ``llm_call``：**仅当 ``llm_invoked`` 为真**（本次节点确实发生了
          LLM 调用）**且本节点没有按步自己落过**才落盘，字段取 ``usage.token_in /
          token_out / cost / duration_ms``；未调用的节点**不落** ``llm_call``（缺陷 2 修复）；
        * **L2** ``node_end``：节点内部结束（含 thought / observation / status）；
        * **T1** ``tool_call``：从 executor 的 ``execution_results[*].tool_calls``
          逐条落盘，字段名照 K7 映射（``name→tool_name`` / ``args→arguments`` /
          ``result→observation`` / ``duration_ms→latency_ms``）。

        **⚠️ ``last_usage`` 前提（U4，已修正）**：``last_usage`` 是线程本地且
        **从不清空**的槽位。旧实现无条件读它写 ``llm_call``，于是：

        1. 「同一节点内连续两次 LLM 调用」——后一次覆盖前一次（原 U4 已注明）；
        2. 「**本次节点根本没调用**」——读到的是**上一次调用的残留**，且状态被兜底成
           ``success``，凭空捏造「成功的 LLM 调用」（生产实测：只有 1 次真实请求，
           却落出 3 条 ``llm_call``）。

        本实现用 ``__call__`` 传入的 ``llm_invoked``（基于用量对象**身份变化**或
        节点产出了非空增量）显式判定；``usage`` 为 ``None`` 时一律记零，绝不复用残留。

        **「节点内多次 LLM 调用」这件事已经发生了**（原 §8 U4 预留的那条）：
        executor 一次节点调用跑完整轮计划，每步一次真实付费调用。它的处理是
        :attr:`per_call_llm_events` + :meth:`_emit_llm_call_event` —— **一步一条**，
        出口这条汇总随之关掉（否则最后一步计两遍）。没有改成"让 ``invoke_*`` 直接返回
        本次 usage"那条原计划：那要动 adapter 签名与全部调用点，而"紧跟调用之后读
        ``last_usage``"在单线程 worker 里同样严格（``last_usage`` 是线程本地槽位，
        本任务的工作线程独占它）。若哪天引入并发调用同一 adapter，才需要换成返回值那条。

        失败隔离：任何一条落盘异常都由 ``TaskEventSink`` 实现方吞掉
        （``DatabaseEventSink`` → ``Database.record_event`` 只 WARN），
        这里再兜一层，确保埋点绝不拖垮节点执行。
        """
        sink = self.ctx.event_sink
        if sink is None:
            return
        task_id = state.get("task_id", "")
        if not task_id:
            return
        event_status = _EVENT_STATUS[status] if status in _EVENT_STATUS else STATUS_SUCCESS
        try:
            # L1：只有本次节点真的调用过 LLM 才落 llm_call（缺陷 2）。
            # 未调用的节点落 0 条，避免「没调用却报 success」的幻影事件。
            #
            # 第二个条件是 2026-10-02 新加的（Q6-01）：节点自己已经按「一次调用一条」
            # 落过了（executor 的轮内多步），这里再补一条汇总就会把最后一步**计两遍**。
            # 但「一条都没落成」时仍然要发 —— 那是异常发生在第一次调用之前的形状，
            # 连着关掉等于把失败也抹掉（缺陷 2 那道判据不许退）。
            if llm_invoked and not (self.per_call_llm_events and self._llm_calls_logged):
                sink(
                    EventRecord(
                        task_id=task_id,
                        event_type=TASK_EVT_LLM_CALL,
                        role=self.role,
                        node=self.role,
                        step=step,
                        thought=self.trace_input(state)[:2000],
                        observation="",
                        status=event_status,
                        latency_ms=int(getattr(usage, "duration_ms", 0) or 0),
                        tokens_in=int(getattr(usage, "token_in", 0) or 0),
                        tokens_out=int(getattr(usage, "token_out", 0) or 0),
                        cost=float(getattr(usage, "cost", 0.0) or 0.0),
                        #: 模型名与**当时那次调用实际用的**峰谷系数，都取自 ``usage``
                        #: （adapter 在调用那一刻取的），不在这里重算时钟：
                        #: 事后算会整体错 8 小时（created_at 是 UTC）或跨窗口错档（×1.0/×0.5）。
                        #: 空串按"未知"处理交 NULL，别让它读成"模型叫 ''"。
                        model=getattr(usage, "model", "") or None,
                        price_multiplier=getattr(usage, "multiplier", None),
                    )
                )
            sink(
                EventRecord(
                    task_id=task_id,
                    event_type=TASK_EVT_NODE_END,
                    role=self.role,
                    node=self.role,
                    step=step,
                    thought=self.trace_output(update),
                    observation=self.trace_output(update),
                    status=event_status,
                    latency_ms=int(duration_ms),
                )
            )
            self._emit_tool_events(sink, update, step, task_id)
        except Exception:  # noqa: BLE001 - 埋点失败绝不拖垮节点执行（K2 失败隔离）
            logger.warning("[%s] task_events 埋点失败（已跳过）", self.role, exc_info=True)

    def _emit_tool_events(
        self,
        sink: TaskEventSink,
        update: StateUpdate,
        step: int,
        task_id: str,
    ) -> None:
        """把 executor 各子步骤的工具调用逐条落 ``tool_call`` 事件（K7 字段映射）。"""
        results = update.get("execution_results")
        if not results:
            return
        for item in results:
            sub_step = int(item.get("step_index", 0))
            for call in item.get("tool_calls") or []:
                call_status = str(call.get("status", "") or "")
                sink(
                    EventRecord(
                        task_id=task_id,
                        event_type=TASK_EVT_TOOL_CALL,
                        role=self.role,
                        node=self.role,
                        step=step,
                        sub_step=sub_step,
                        thought="",
                        tool_name=str(call.get("name") or "") or None,
                        arguments=dict(call.get("args") or {}),
                        observation=str(call.get("result") or ""),
                        status=_EVENT_STATUS.get(call_status, STATUS_SUCCESS),
                        latency_ms=int(call.get("duration_ms", 0) or 0),
                    )
                )


def json_text(value: Any, limit: int = 2000) -> str:
    """把任意对象渲染成紧凑 JSON 文本，用于写回 state.messages / 埋点。"""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = str(value)
    return text[:limit]


__all__ = [
    "BaseNode",
    "ListTraceSink",
    "NodeContext",
    "PromptNotFoundError",
    "PromptRenderError",
    "ToolInvoker",
    "TraceRecord",
    "TraceSink",
    "json_text",
    "load_prompt",
    "prompt_path",
    "render_prompt",
]
