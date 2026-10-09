"""Executor 节点：逐条执行计划中的子步骤。

一次 ``executor_node`` 调用会**跑完整轮计划**：以 ``current_step`` 为游标逐条推进，
每条子步骤单独做一次「调用工具 / 直接输出」的决策。这样图上的循环语义才自洽——
reviewer 判的是**整份交付**，不通过则整轮回退重做（``iteration + 1``），
而不是每步都过一遍门禁、第一步通过就提前收工。

工具层通过 :class:`~core.agent.base.ToolInvoker` 协议注入：阶段 1 传 ``None``
即纯推理模式；阶段 2 接上 registry + sandbox 后无需改动本文件。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent.base import BaseNode, NodeContext, render_prompt
from core.agent.delta import JsonFieldDelta
from core.workflow.state import (
    AgentState,
    ExecutorDecision,
    StateUpdate,
    StepResult,
    ToolCallRecord,
    draft_answer,
    format_results,
    is_terminal,
    numbered,
)

logger = logging.getLogger(__name__)


class ExecutorError(RuntimeError):
    """executor 无法继续执行。"""


class ExecutorNode(BaseNode):
    """执行节点：``plan`` + ``current_step`` → ``execution_results``。"""

    role = "executor"

    #: 本节点**一步一条** ``llm_call``（Q6-01）：一次节点调用会跑完整轮计划，
    #: 每步一次真实付费调用，出口那条汇总只带最后一步的用量 ⇒ 少算 N-1 笔。
    #: 落点在 :meth:`run` 的循环里（紧跟调用之后），开关定义在
    #: :attr:`BaseNode.per_call_llm_events`。
    per_call_llm_events = True

    def run(self, state: AgentState) -> StateUpdate:
        if is_terminal(state):
            return {}

        plan = list(state.get("plan") or [])
        if not plan:
            raise ExecutorError("state.plan 为空，无法执行：planner 可能没有成功运行")

        carry = list(state.get("execution_results") or [])
        feedback = (state.get("review_comment") or "").strip()
        cursor = int(state.get("current_step", 0))

        if cursor >= len(plan):
            # reviewer 打回：带着上一轮意见整轮重做，避免「只重做最后一步」而漏掉根因
            logger.info("收到评审意见，整轮重做 | %s", feedback or "（无意见）")
            cursor = 0
        elif cursor > 0:
            logger.info("检测到执行游标 %d，从该步继续（断点续跑场景）", cursor)

        #: 这一段是**流式输出**的接线处。三条纪律：
        #: ① **没有出口就一字不改**（``answer_stream is None`` ⇒ 连 ``on_text`` 这个
        #:    关键字都不传）—— 批量评测与单测里的 MockLLM 签名里没有 ``on_text``，
        #:    无条件传一个 ``on_text=None`` 会让它们直接 TypeError；
        #: ② 抽取器按**步**重建：每一步都是一次独立的 LLM 调用、一份独立的 JSON，
        #:    共用一个状态机会把上一步读完的状态（``_S_DONE``）带到下一步；
        #: ③ 步与步之间补一个空行，否则两步的结论会粘成一段读不通的话。
        stream = self.ctx.answer_stream
        usage_sink = self.ctx.usage_sink
        start_index = cursor
        prev_emitted = False
        if stream is not None:
            stream.mark("executor")
            # 新一轮执行（首轮或被 reviewer 打回重做）⇒ 草稿从头写，
            # 否则打回重做时新草稿会接在旧草稿后面，屏上是两份答案。
            stream.clear()

        transcript: list[Any] = []
        #: 本次节点调用所属的**编排轮次**（0 起）。``trace_step`` 只看 state、不看 update，
        #: 传空字典纯粹是为了满足签名 —— 循环里每轮 state 不变，取一次就够。
        step_index = self.trace_step(state, {})
        for index in range(cursor, len(plan)):
            subtask = plan[index]
            if stream is not None and index > start_index and prev_emitted:
                stream.emit("\n\n")
            history = format_results([item for item in carry if item["step_index"] < index])
            prompt = render_prompt(
                "executor",
                self.config.executor_prompt_version,
                task=state.get("task", ""),
                plan=numbered(plan),
                step_index=index + 1,
                total_steps=len(plan),
                subtask=subtask,
                history=history,
                feedback=feedback or "（首轮执行，暂无评审意见）",
                tool_section=self._tool_section(),
            )
            ask = [SystemMessage(content=prompt), HumanMessage(content=f"请执行第 {index + 1} 步")]
            streamer = JsonFieldDelta("answer", stream.emit) if stream is not None else None
            kwargs: dict[str, Any] = {"on_text": streamer.feed} if streamer is not None else {}
            try:
                decision = self.llm.invoke_model(
                    ask,
                    ExecutorDecision,
                    model=self.settings.llm_model_small,
                    **kwargs,
                )
            except Exception:
                # 这一步没跑成：落一条**零用量**的 failed ``llm_call``，让"尝试过"留在账上，
                # 同时绝不把上一步的钱再计一遍（Q6-01 的失败分支）。异常照原样抛给
                # ``BaseNode.__call`` 那个兜底，节点增量与 node_end 的行为不变。
                self._emit_llm_call_event(
                    state,
                    step=step_index,
                    sub_step=index,
                    thought=f"[executor] 第 {index + 1}/{len(plan)} 步 · {subtask}（本次调用失败）",
                    status="failed",
                    zero_usage=True,
                )
                raise
            prev_emitted = bool(streamer and streamer.chars)
            if usage_sink is not None:
                usage_sink(self._usage_of())
            #: **一步一条**（Q6-01）：紧跟在调用之后读 ``last_usage``，
            #: 落完 :attr:`per_call_llm_events` 会让出口那条汇总自动关掉。
            self._emit_llm_call_event(
                state,
                step=step_index,
                sub_step=index,
                thought=f"[executor] 第 {index + 1}/{len(plan)} 步 · {subtask}",
            )

            tool_calls: list[ToolCallRecord] = []
            if decision.tool_name:
                tool_calls.append(self._call_tool(decision.tool_name, decision.tool_args))

            output = decision.answer.strip() or self._fallback_output(tool_calls)
            status = (
                "success"
                if all(call["status"] == "success" for call in tool_calls)
                else "failed"
            )
            record: StepResult = {
                "step_index": index,
                "subtask": subtask,
                "output": output,
                "tool_calls": tool_calls,
                "status": status,
            }
            # 按 step_index 覆盖：重做时旧结果被同一位置的旧记录替换，不会越滚越长
            carry = [item for item in carry if item["step_index"] != index] + [record]
            transcript.extend([*ask, AIMessage(content=decision.model_dump_json())])
            logger.info(
                "第 %d/%d 步完成 status=%s tools=%d",
                index + 1,
                len(plan),
                status,
                len(tool_calls),
            )

        carry.sort(key=lambda item: item["step_index"])
        return {
            "execution_results": carry,
            "current_step": len(plan),
            "final_answer": draft_answer(carry),
            "messages": transcript,
            "status": "running",
        }

    # ---- 埋点 ----
    def _usage_of(self) -> dict[str, Any]:
        """取**本次** LLM 调用的用量增量（给 SSE ``usage`` 帧）。

        只读 ``last_usage``，不重算时钟、不读数据库：用量是 adapter 在调用那一刻
        按当时峰谷系数算好的（``core/llm/adapter._call``），这里再算一次就会出现
        「金额按 A 档、档位标 B 档」的两份账 —— 与 ``core/agent/base`` 里
        ``llm_call`` 埋点那条注释同一条纪律。

        ⚠️ 拿不到（Mock 没有这个属性）时返回**全零**而不是抛异常：用量是观测，
        观测失败绝不能拖垮执行（K2 失败隔离）。前端收到全零也只是"这一跳没数"，
        总账仍以终态 ``done`` 帧里的数字为准。
        """
        usage = getattr(self.llm, "last_usage", None)
        return {
            "node": self.role,
            "model": getattr(usage, "model", "") or "",
            "tokens_in": int(getattr(usage, "token_in", 0) or 0),
            "tokens_out": int(getattr(usage, "token_out", 0) or 0),
            "cost": float(getattr(usage, "cost", 0.0) or 0.0),
        }

    # ---- 工具调用 ----
    def _tool_section(self) -> str:
        """渲染给提示词看的工具清单。"""
        invoker = self.ctx.tool_invoker
        described = invoker.describe().strip() if invoker is not None else ""
        if not described:
            return "当前没有接入任何工具：`tool_name` 必须为 null，请直接给出结论。"
        return f"当前可用工具（`tool_name` 只能从这里选，入参键名必须与说明一致）：\n{described}"

    def _call_tool(self, name: str, args: dict[str, Any]) -> ToolCallRecord:
        """执行一次工具调用，把任何异常就地转成 failed 记录。

        高危工具的 HITL 确认由工具层自己负责（它才知道 danger_level），
        本节点只如实记录结果。
        """
        invoker = self.ctx.tool_invoker
        if invoker is None:
            return ToolCallRecord(
                name=name,
                args=args,
                result="工具层未接入（阶段 2 提供 registry + sandbox）",
                status="failed",
                duration_ms=0,
            )
        started = time.perf_counter()
        try:
            return invoker.call(name, args)
        except Exception as exc:  # noqa: BLE001 - 工具边界必须兜住异常，转成 failed 记录
            logger.warning("工具 %s 调用异常：%s", name, exc)
            return ToolCallRecord(
                name=name,
                args=args,
                result=f"{type(exc).__name__}: {exc}",
                status="failed",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    @staticmethod
    def _fallback_output(tool_calls: list[ToolCallRecord]) -> str:
        """模型没给 answer 时的兜底：至少把工具返回结果带出去。"""
        if not tool_calls:
            return "（模型未给出结论，且未调用工具）"
        return "\n".join(f"{call['name']} 返回：{call['result']}" for call in tool_calls)

    # ---- 埋点 ----
    def trace_input(self, state: AgentState) -> str:
        plan = list(state.get("plan") or [])
        cursor = min(int(state.get("current_step", 0)), max(len(plan) - 1, 0))
        return plan[cursor] if plan else ""

    def trace_output(self, update: StateUpdate) -> str:
        results = update.get("execution_results") or []
        if not results:
            return ""
        last = max(results, key=lambda item: item["step_index"])
        return f"第 {last['step_index'] + 1} 步 [{last['status']}] {last['output']}"


def executor_node(state: AgentState, ctx: NodeContext | None = None) -> StateUpdate:
    """手册签名的单次调用入口；图编排里请复用 ``ExecutorNode`` 实例。"""
    return ExecutorNode(ctx or NodeContext.create())(state)


__all__ = ["ExecutorError", "ExecutorNode", "executor_node"]
