"""LangGraph 编排图：planner → executor → reviewer，未通过则回退 executor。

拓扑（与手册一致）::

    START → planner → executor → reviewer ─┬─ pass ──────────────→ END
                                            └─ fail → executor（iteration+1）

``WorkflowRunner`` 是给上层用的门面：一次构造、多次运行，并自动带上
``recursion_limit``（按 ``max_iterations`` 推导，避免长循环被 LangGraph 默认上限截断）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.agent.base import NodeContext
from core.agent.executor import ExecutorNode
from core.agent.planner import PlannerNode
from core.agent.reviewer import ReviewerNode
from core.workflow.conditions import CONTINUE_NODE, STOP_NODE, should_continue
from core.workflow.state import AgentState, StateUpdate, initial_state

logger = logging.getLogger(__name__)

PLANNER_NODE = "planner"
EXECUTOR_NODE = "executor"
REVIEWER_NODE = "reviewer"

#: 节点执行顺序（供 demo 与前端展示固定顺序）
NODE_ORDER: tuple[str, ...] = (PLANNER_NODE, EXECUTOR_NODE, REVIEWER_NODE)


def build_graph(
    ctx: NodeContext | None = None,
    *,
    checkpointer: Any = None,
) -> CompiledStateGraph:
    """编译工作流图。

    Args:
        ctx: 节点运行上下文；不传则用全局默认（真实 LLM、无工具层）。
        checkpointer: LangGraph 的持久化后端，阶段 4 接 SQLite/Redis 时传入，
            对应「断点续跑」。

    Returns:
        已编译的图，可直接 ``invoke`` / ``stream``。
    """
    context = ctx if ctx is not None else NodeContext.create()
    builder: StateGraph = StateGraph(AgentState)

    builder.add_node(PLANNER_NODE, PlannerNode(context))
    builder.add_node(EXECUTOR_NODE, ExecutorNode(context))
    builder.add_node(REVIEWER_NODE, ReviewerNode(context))

    builder.add_edge(START, PLANNER_NODE)
    builder.add_edge(PLANNER_NODE, EXECUTOR_NODE)
    builder.add_edge(EXECUTOR_NODE, REVIEWER_NODE)
    builder.add_conditional_edges(
        REVIEWER_NODE,
        # 绑定同一份 config，保证节点与路由用的是同一个 max_iterations
        lambda state: should_continue(state, context.config),
        {CONTINUE_NODE: EXECUTOR_NODE, STOP_NODE: END},
    )
    logger.debug("编排图已编译：%s → ... → %s", " → ".join(NODE_ORDER), END)
    return builder.compile(checkpointer=checkpointer)


class WorkflowRunner:
    """编排图门面：一次构造、多次运行。"""

    def __init__(self, ctx: NodeContext | None = None, *, checkpointer: Any = None) -> None:
        self.ctx: NodeContext = ctx if ctx is not None else NodeContext.create()
        self.graph = build_graph(self.ctx, checkpointer=checkpointer)

    @property
    def recursion_limit(self) -> int:
        """按迭代上限推导递归上限：planner 1 步 + 每轮 (executor + reviewer) 2 步 + 4 步余量。"""
        return self.ctx.config.max_iterations * 2 + 6

    def run(self, task: str, task_id: str | None = None) -> AgentState:
        """跑完一次任务，返回最终状态。"""
        state = initial_state(task, task_id)
        result = self.graph.invoke(state, config={"recursion_limit": self.recursion_limit})
        return cast(AgentState, result)

    def stream(
        self,
        task: str,
        task_id: str | None = None,
    ) -> Iterator[tuple[str, StateUpdate]]:
        """流式执行：每完成一个节点就 yield ``(节点名, 状态增量)``。

        LangGraph 的 ``stream_mode="updates"`` 只在节点结束后吐数据，
        对 UI 实时日志来说粒度刚好：既能看到进度，又不会刷屏。
        """
        state = initial_state(task, task_id)
        for chunk in self.graph.stream(
            state,
            config={"recursion_limit": self.recursion_limit},
            stream_mode="updates",
        ):
            for node_name, update in chunk.items():
                yield node_name, cast(StateUpdate, update)


__all__ = [
    "EXECUTOR_NODE",
    "NODE_ORDER",
    "PLANNER_NODE",
    "REVIEWER_NODE",
    "WorkflowRunner",
    "build_graph",
]
