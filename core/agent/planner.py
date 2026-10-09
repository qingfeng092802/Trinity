"""Planner 节点：把用户任务拆解成 3-5 个可执行子步骤。

输出契约是**纯 JSON 字符串数组**（``PLAN_SCHEMA``），不包一层对象：
这样提示词可以说「只输出 JSON 数组」，校验口径也是数组，两边完全对齐。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent.base import BaseNode, NodeContext, render_prompt
from core.workflow.state import AgentState, StateUpdate, is_terminal, normalize_steps

logger = logging.getLogger(__name__)

#: planner 输出契约：3-5 条字符串。
PLAN_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 3,
    "maxItems": 5,
}

#: 每次调用 planner 时给出的用户消息（除提示词外的那条）
PLANNER_ASK = "请把这个任务拆解成 3-5 个可执行子步骤：\n{task}"


class PlanError(RuntimeError):
    """planner 未能产出可用计划。"""


class PlannerNode(BaseNode):
    """拆解节点：``task`` → ``plan``。"""

    role = "planner"

    def run(self, state: AgentState) -> StateUpdate:
        if is_terminal(state):
            return {}

        task = state.get("task", "")
        prompt = render_prompt("planner", self.config.planner_prompt_version, task=task)
        ask = PLANNER_ASK.format(task=task)
        messages = [SystemMessage(content=prompt), HumanMessage(content=ask)]

        raw = self.llm.invoke_json(
            messages,
            PLAN_SCHEMA,
            model=self.settings.llm_model_large,
            max_attempts=3,
        )
        steps = normalize_steps(list(raw) if isinstance(raw, list) else None)
        if not steps:
            raise PlanError("planner 未产出任何子步骤")

        if not 3 <= len(steps) <= 5:
            # 步数越界不算致命：截断已在 normalize_steps 里做过，这里只提示
            logger.warning("planner 产出 %d 步，超出 3-5 的期望区间（已接受）", len(steps))
        logger.info("planner 产出 %d 个子步骤", len(steps))

        return {
            "plan": steps,
            "current_step": 0,
            "status": "running",
            "messages": [*messages, AIMessage(content=json.dumps(steps, ensure_ascii=False))],
        }

    def trace_output(self, update: StateUpdate) -> str:
        plan = update.get("plan") or []
        return "\n".join(f"{index}. {step}" for index, step in enumerate(plan, 1))


def planner_node(state: AgentState, ctx: NodeContext | None = None) -> StateUpdate:
    """手册签名的单次调用入口；图编排里请复用 ``PlannerNode`` 实例。"""
    return PlannerNode(ctx or NodeContext.create())(state)


__all__ = ["PLANNER_ASK", "PLAN_SCHEMA", "PlanError", "PlannerNode", "planner_node"]
