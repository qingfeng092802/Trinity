"""工作流状态契约（阶段 1 的核心数据契约，后续阶段只增不改）。

关于 ``total=False``
-------------------
``AgentState`` 用 ``TypedDict(total=False)`` 而不是全字段必填，原因有两个：

1. LangGraph 的节点返回的是**状态增量**（partial update），不是全量状态；
2. ``messages`` 挂了 ``add_messages`` reducer，节点若回传完整 messages 列表
   会让消息被重复追加。

所以所有键都在这里显式声明（契约不缩水），完整初值由 :func:`initial_state`
给出，节点只返回自己改动的那几个键。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from config import Settings, get_settings

#: 单次工具调用的结果状态
ToolCallStatus = Literal["success", "failed", "timeout"]

#: 整条任务的运行状态
RunStatus = Literal["running", "done", "failed", "aborted"]

#: 产生埋点 / 评审的角色
AgentRole = Literal["planner", "executor", "reviewer", "judge"]

#: 终态集合：进入这些状态后任何节点都不应再触发 LLM 调用
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "failed", "aborted"})


class ToolCallRecord(TypedDict):
    """一次工具调用的完整记录（阶段 2 的沙箱会把真实结果填进来）。"""

    name: str
    args: dict[str, Any]
    result: str
    status: str
    duration_ms: int


class StepResult(TypedDict):
    """单个子步骤的执行结果。"""

    step_index: int
    subtask: str
    output: str
    tool_calls: list[ToolCallRecord]
    status: str


class AgentState(TypedDict, total=False):
    """LangGraph 全局状态（键名与手册契约保持一致）。"""

    task: str
    task_id: str
    plan: list[str]
    current_step: int
    execution_results: list[StepResult]
    review_result: bool
    review_score: int
    review_comment: str
    iteration: int
    messages: Annotated[list[Any], add_messages]
    final_answer: str
    status: RunStatus


#: 节点返回值别名：语义上只携带增量字段，类型复用 AgentState（total=False 允许多退少补）
StateUpdate = AgentState


# --------------------------------------------------------------------------- #
# 结构化输出契约
# --------------------------------------------------------------------------- #
class ExecutorDecision(BaseModel):
    """executor 的单步决策契约：调用工具，还是直接给结论。"""

    thought: str = Field(default="", description="一句话说明打算怎么做，会写入 trace 便于回放")
    tool_name: str | None = Field(
        default=None,
        description="要调用的工具名，只能从提示词给出的清单里选；不需要工具时填 null",
    )
    tool_args: dict[str, Any] = Field(
        default_factory=dict,
        description="工具入参对象，键名必须与工具签名一致；不需要工具时填空对象",
    )
    answer: str = Field(
        default="",
        description="本步骤的最终结论；若调用了工具，可留空由工具返回结果补充",
    )


class ReviewVerdict(BaseModel):
    """reviewer 输出契约。

    模型字段名用别名 ``pass``（``pass`` 是 Python 关键字，不能直接做字段名），
    同时开启 ``populate_by_name``，两种写法都能解析。

    关于 ``final_answer``：手册给 reviewer 定的契约是 ``{pass, score, comment}``，
    这里**有意扩展**了一个可选字段。原因是流水线需要有人负责「交付收口」——
    executor 各步产出的是过程性结论，直接拼接会得到一份「执行日志」而不是
    「可直接交给用户的答案」（首轮真实跑通时 reviewer 自己也指出了这个问题）。
    reviewer 是最后一个看到全局的角色，由它在通过时给出一份打磨后的终稿最省节点。
    该字段可留空，留空时回退到 executor 拼出的草稿，因此不破坏原有契约。
    """

    model_config = ConfigDict(populate_by_name=True)

    passed: bool = Field(alias="pass", description="是否通过评审")
    score: int = Field(
        ge=0,
        le=10,
        description="0-10 质量分，低于 review_threshold 一律视为不通过",
    )
    comment: str = Field(default="", description="一句话评审意见：扣分点或通过理由")
    final_answer: str = Field(
        default="",
        description=(
            "通过评审时：打磨后的最终交付内容（合并各步骤结论、剔除过程性描述、"
            "直接可读）；不通过时留空字符串"
        ),
    )


class WorkflowConfig(BaseModel):
    """编排参数（阶段 1 契约）。默认值取自全局 ``Settings``，保证单一配置源。"""

    max_iterations: int = Field(
        default=5,
        ge=1,
        le=50,
        description="executor 整轮执行的最大次数（含首次），达到后强制收口",
    )
    review_threshold: int = Field(
        default=7,
        ge=0,
        le=10,
        description="reviewer 打分通过线，低于该分数一律回退重做",
    )
    enable_hitl: bool = Field(
        default=False,
        description="是否开启高危工具的人工确认（阶段 2 接入工具层后生效）",
    )
    planner_prompt_version: str = Field(default="v1", description="planner 提示词版本目录名")
    executor_prompt_version: str = Field(default="v1", description="executor 提示词版本目录名")
    reviewer_prompt_version: str = Field(default="v1", description="reviewer 提示词版本目录名")

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> WorkflowConfig:
        """用全局配置构造编排参数，避免两份默认值各说各话。"""
        resolved = settings or get_settings()
        return cls(
            max_iterations=resolved.max_iterations,
            review_threshold=resolved.review_threshold,
            enable_hitl=resolved.enable_hitl,
        )


# --------------------------------------------------------------------------- #
# 构造与读取辅助
# --------------------------------------------------------------------------- #
def initial_state(task: str, task_id: str | None = None) -> AgentState:
    """构造一份字段齐全的初始状态，交给 ``graph.invoke`` 作为入口。"""
    cleaned = task.strip()
    if not cleaned:
        raise ValueError("task 不能为空")
    return AgentState(
        task=cleaned,
        task_id=task_id or f"task-{uuid4().hex[:12]}",
        plan=[],
        current_step=0,
        execution_results=[],
        review_result=False,
        review_score=0,
        review_comment="",
        iteration=0,
        messages=[],
        final_answer="",
        status="running",
    )


def is_terminal(state: AgentState) -> bool:
    """是否已进入终态。终态下节点必须直接返回空增量，不再消耗 token。"""
    return state.get("status") in TERMINAL_STATUSES


def normalize_steps(raw: list[Any] | None) -> list[str]:
    """清洗 planner 的输出：字符串化、去空白、去空项、最多保留 5 条。"""
    if not raw:
        return []
    steps = [str(item).strip() for item in raw]
    return [step for step in steps if step][:5]


def numbered(plan: list[str]) -> str:
    """把计划渲染成带序号的文本，供提示词与 trace 使用。"""
    return "\n".join(f"{index}. {step}" for index, step in enumerate(plan, 1)) or "（无计划）"


def format_results(results: list[StepResult] | None) -> str:
    """把执行结果渲染成给 reviewer 与最终答案看的文本。"""
    if not results:
        return "（暂无执行结果）"
    lines: list[str] = []
    for item in sorted(results, key=lambda record: record["step_index"]):
        lines.append(
            f"第 {item['step_index'] + 1} 步 · {item['subtask']}\n"
            f"  状态：{item['status']}\n"
            f"  结论：{item['output']}"
        )
        for call in item["tool_calls"]:
            lines.append(
                f"  └ 工具 {call['name']}({call['args']}) → {call['status']}"
                f"（{call['duration_ms']}ms）：{call['result'][:200]}"
            )
    return "\n".join(lines)


def draft_answer(results: list[StepResult] | None) -> str:
    """把各步骤结论拼成草稿答案。

    它是 executor 的副产品：即使 reviewer 一直不通过、任务被强制收口，
    也能拿到一份「做到哪算哪」的回答，而不是空字符串。
    """
    if not results:
        return ""
    ordered = sorted(results, key=lambda record: record["step_index"])
    body = "\n".join(
        f"{index}. {item['subtask']}\n   {item['output']}"
        for index, item in enumerate(ordered, 1)
    )
    return f"已完成 {len(ordered)} 个子步骤：\n{body}"


__all__ = [
    "TERMINAL_STATUSES",
    "AgentRole",
    "AgentState",
    "ExecutorDecision",
    "ReviewVerdict",
    "RunStatus",
    "StateUpdate",
    "StepResult",
    "ToolCallRecord",
    "ToolCallStatus",
    "WorkflowConfig",
    "draft_answer",
    "format_results",
    "initial_state",
    "is_terminal",
    "normalize_steps",
    "numbered",
]
