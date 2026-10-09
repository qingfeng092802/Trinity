"""LLM Judge：按验收标准对一次任务的交付结果自动打分。

与 reviewer 的区别（两者都是「评审」，但职责不同）：

* **reviewer** 是**流程内**的门禁，决定要不要回退重做，它看到的是当前这一轮的产物；
* **judge** 是**流程外**的评测，只在任务结束后跑一次，按预先写好的 ``expected_criteria``
  打分，用于横向比较不同版本的平台（提示词换了、模型换了、工具换了，分数怎么动）。

``grade`` 由代码从分数推导，不由模型自报：让模型同时给分和定级，它经常自相矛盾。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from config import Settings, get_settings
from core.agent.base import TraceRecord, render_prompt
from core.llm.adapter import LLMAdapter, get_adapter

logger = logging.getLogger(__name__)

#: 分数 → 等级（从高到低匹配，取第一个满足的）
GRADE_BANDS: tuple[tuple[int, str], ...] = (
    (9, "excellent"),
    (7, "good"),
    (5, "fair"),
    (0, "poor"),
)


class JudgeError(RuntimeError):
    """评测无法完成。"""


def grade_for(score: int) -> str:
    """把 0-10 的分数映射成等级。"""
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "poor"


class EvalResult(BaseModel):
    """自动评测结果（手册契约 + 一个便于排查 judge 本身的可选字段）。"""

    task_id: str = Field(description="被评测的任务 id")
    score: int = Field(ge=0, le=10, description="0-10 综合分")
    grade: str = Field(description="等级：excellent / good / fair / poor（由分数推导）")
    issues: list[str] = Field(default_factory=list, description="未达标之处，逐条可核对")
    suggestions: list[str] = Field(default_factory=list, description="可执行的改进建议")
    trace_refs: list[str] = Field(default_factory=list, description="支撑该结论的 trace_id 列表")
    reasoning: str = Field(
        default="",
        description="一句话打分依据。手册契约里没有这个字段，是为了排查 judge 自身稳定性而追加的",
    )


class JudgeVerdict(BaseModel):
    """judge 的结构化输出契约（``grade`` 不在这里，由代码推导）。"""

    score: int = Field(ge=0, le=10, description="0-10 综合分")
    reasoning: str = Field(default="", description="一句话说明打分依据")
    issues: list[str] = Field(default_factory=list, description="未达标之处；全达标时为空数组")
    suggestions: list[str] = Field(default_factory=list, description="可执行建议；没有给空数组")


class LLMJudge:
    """一次任务跑完之后的自动评分器。"""

    def __init__(
        self,
        llm: LLMAdapter | None = None,
        settings: Settings | None = None,
        *,
        model: str | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm if llm is not None else get_adapter()
        self.model = model or self.settings.llm_model_large
        self.prompt_version = prompt_version

    def evaluate(
        self,
        *,
        task: str,
        criteria: Sequence[str],
        final_answer: str,
        task_id: str,
        records: Sequence[TraceRecord] = (),
        status: str = "done",
        iterations: int = 0,
    ) -> EvalResult:
        """按 ``criteria`` 给结果打分。

        Raises:
            JudgeError: 评测标准为空（没有标准的打分没有意义，直接报错而不是乱给分）。
        """
        if not criteria:
            raise JudgeError(f"任务 {task_id} 没有验收标准，无法评测")

        prompt = render_prompt(
            "judge",
            self.prompt_version,
            task=task,
            criteria="\n".join(f"{index}. {item}" for index, item in enumerate(criteria, 1)),
            execution=_summarize_records(records, status=status, iterations=iterations),
            answer=final_answer.strip() or "（空答案）",
            status=status,
        )
        verdict = self.llm.invoke_model(
            [SystemMessage(content=prompt), HumanMessage(content="请按验收标准打分")],
            JudgeVerdict,
            model=self.model,
        )
        result = EvalResult(
            task_id=task_id,
            score=verdict.score,
            grade=grade_for(verdict.score),
            issues=[item.strip() for item in verdict.issues if item.strip()],
            suggestions=[item.strip() for item in verdict.suggestions if item.strip()],
            trace_refs=[record.trace_id for record in records],
            reasoning=verdict.reasoning.strip(),
        )
        logger.info("judge 完成 task=%s score=%d grade=%s", task_id, result.score, result.grade)
        return result


def _summarize_records(
    records: Sequence[TraceRecord],
    *,
    status: str,
    iterations: int,
) -> str:
    """把埋点压成给 judge 看的执行摘要。

    刻意不把整段 trace 原文塞进去：judge 需要的是「流程是否完整、有没有失败的工具调用」，
    细节交给答案本身，省下的 token 留给评分质量。
    """
    if not records:
        return "（无埋点记录）"
    tool_calls = 0
    tool_failures = 0
    for record in records:
        for call in record.tool_calls:
            tool_calls += 1
            if call.get("status") != "success":
                tool_failures += 1
    lines = [
        f"- 终态：{status}，迭代轮数：{iterations}",
        f"- 节点埋点：{len(records)} 条（{'、'.join(f'{r.role}#{r.step}' for r in records)}）",
        f"- 工具调用：{tool_calls} 次，其中失败 {tool_failures} 次",
        f"- 累计耗时：{sum(r.duration_ms for r in records)}ms，"
        f"token 输入 {sum(r.token_in for r in records)} / 输出 {sum(r.token_out for r in records)}",
    ]
    failed = [record for record in records if record.status != "success"]
    if failed:
        lines.append(f"- 异常节点：{'、'.join(f'{r.role}({r.status})' for r in failed)}")
    return "\n".join(lines)


def evaluate_state(
    state: dict[str, Any],
    *,
    criteria: Sequence[str],
    records: Sequence[TraceRecord] = (),
    llm: LLMAdapter | None = None,
    settings: Settings | None = None,
) -> EvalResult:
    """便捷入口：直接拿 ``WorkflowRunner.run()`` 返回的状态去评测。"""
    judge = LLMJudge(llm=llm, settings=settings)
    return judge.evaluate(
        task=str(state.get("task", "")),
        criteria=criteria,
        final_answer=str(state.get("final_answer", "")),
        task_id=str(state.get("task_id", "")),
        records=records,
        status=str(state.get("status", "unknown")),
        iterations=int(state.get("iteration", 0)),
    )


__all__ = [
    "GRADE_BANDS",
    "EvalResult",
    "JudgeError",
    "JudgeVerdict",
    "LLMJudge",
    "evaluate_state",
    "grade_for",
]
