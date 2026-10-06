"""Reviewer 节点：对整份交付做质量门禁。

判定规则是**模型判断 + 硬阈值**的合取：``pass=True`` 且 ``score >= review_threshold``
才算通过。只信模型的话，容易出现「嘴上说通过、实际给了 5 分」的自相矛盾；
只信分数的话，又丢掉了模型对上下文的判断，所以两个条件都要满足。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.agent.base import BaseNode, NodeContext, render_prompt
from core.agent.delta import JsonFieldDelta
from core.workflow.state import (
    AgentState,
    ReviewVerdict,
    RunStatus,
    StateUpdate,
    format_results,
    is_terminal,
    numbered,
)

logger = logging.getLogger(__name__)


class ReviewError(RuntimeError):
    """reviewer 无法完成评审。"""


class ReviewerNode(BaseNode):
    """评审节点：``execution_results`` → ``review_result`` / ``iteration`` / ``status``。"""

    role = "reviewer"

    def run(self, state: AgentState) -> StateUpdate:
        if is_terminal(state):
            return {}

        results = list(state.get("execution_results") or [])
        if not results:
            raise ReviewError("没有执行结果可评审（executor 可能失败了）")

        plan = list(state.get("plan") or [])
        executed = len({item["step_index"] for item in results})
        prompt = render_prompt(
            "reviewer",
            self.config.reviewer_prompt_version,
            task=state.get("task", ""),
            plan=numbered(plan),
            results=format_results(results),
            draft=state.get("final_answer", ""),
            threshold=self.config.review_threshold,
            executed_steps=executed,
            total_steps=len(plan),
        )
        ask = "请对上面的执行结果做质量评审"
        messages = [SystemMessage(content=prompt), HumanMessage(content=ask)]
        #: 流式：抽的是 ``final_answer``（终稿），并且**先清空**再写 ——
        #: executor 那一段已经在屏上滚过一遍草稿了，终稿是同一份内容的**新版本**，
        #: 不是接在草稿后面的第二段话。不清空的话用户读到的是「草稿 + 终稿」前后拼。
        #: （``clear`` 只在有出口时调用，与 executor 同理：没有出口就一字不改。）
        stream = self.ctx.answer_stream
        streamer = JsonFieldDelta("final_answer", stream.emit) if stream is not None else None
        kwargs: dict[str, Any] = {"on_text": streamer.feed} if streamer is not None else {}
        if stream is not None:
            stream.mark("reviewer")
            stream.clear()
        verdict = self.llm.invoke_model(
            messages,
            ReviewVerdict,
            model=self.settings.llm_model_large,
            **kwargs,
        )
        if self.ctx.usage_sink is not None:
            self.ctx.usage_sink(self._usage_of())

        passed = bool(verdict.passed) and verdict.score >= self.config.review_threshold
        if verdict.passed and not passed:
            logger.info(
                "reviewer 自评通过但分数 %d 低于通过线 %d，按不通过处理",
                verdict.score,
                self.config.review_threshold,
            )

        iteration = int(state.get("iteration", 0)) + (0 if passed else 1)
        status: RunStatus
        if passed:
            status = "done"
        elif iteration >= self.config.max_iterations:
            # 达到迭代上限：强制收口，把现有草稿答案作为最终交付（状态标记为 aborted）
            status = "aborted"
            logger.warning("已达迭代上限 %d，强制结束", self.config.max_iterations)
        else:
            status = "running"

        comment = verdict.comment.strip() or ("评审通过" if passed else "评审未通过，请重做")

        # 交付收口：通过且有终稿就用终稿；否则保留 executor 拼出的草稿
        # （这样即使任务被强制收口，手里也有一份「做到哪算哪」的答案）
        polished = verdict.final_answer.strip()
        if passed and polished:
            final_answer = polished
            logger.info("reviewer 产出终稿，%d 字", len(polished))
        else:
            final_answer = state.get("final_answer", "")

        logger.info(
            "reviewer pass=%s score=%d iteration=%d status=%s",
            passed,
            verdict.score,
            iteration,
            status,
        )

        return {
            "review_result": passed,
            "review_score": verdict.score,
            "review_comment": comment,
            "iteration": iteration,
            "status": status,
            "final_answer": final_answer,
            "messages": [
                *messages,
                AIMessage(content=verdict.model_dump_json(by_alias=True)),
            ],
        }

    def _usage_of(self) -> dict[str, Any]:
        """本次评审调用的用量增量（口径与 ``ExecutorNode._usage_of`` 完全一致）。"""
        usage = getattr(self.llm, "last_usage", None)
        return {
            "node": self.role,
            "model": getattr(usage, "model", "") or "",
            "tokens_in": int(getattr(usage, "token_in", 0) or 0),
            "tokens_out": int(getattr(usage, "token_out", 0) or 0),
            "cost": float(getattr(usage, "cost", 0.0) or 0.0),
        }

    def trace_output(self, update: StateUpdate) -> str:
        passed = update.get("review_result")
        score = update.get("review_score", 0)
        comment = update.get("review_comment", "")
        return f"pass={passed} score={score} status={update.get('status')} | {comment}"


def reviewer_node(state: AgentState, ctx: NodeContext | None = None) -> StateUpdate:
    """手册签名的单次调用入口；图编排里请复用 ``ReviewerNode`` 实例。"""
    return ReviewerNode(ctx or NodeContext.create())(state)


__all__ = ["ReviewError", "ReviewerNode", "reviewer_node"]
