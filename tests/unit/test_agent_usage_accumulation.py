"""H-2 回归：节点级 TraceRecord 必须累加本节点内全部 LLM 调用。

覆盖三件事：

1. 无 ``event_sink``（批量评测路径）也要累加，不能只记末次调用；
2. 有 ``event_sink`` 时事件通道仍是“一次调用一条”，TraceRecord 只多一条汇总，
   两边总额相等，不双计；
3. 同一个节点实例连续跑两次，第二次不携带第一次的累加值。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from api.constants import TASK_EVT_LLM_CALL, TASK_EVT_NODE_END
from config import Settings
from core.agent.base import ListTraceSink, NodeContext
from core.agent.executor import ExecutorNode
from core.events import EventRecord
from core.llm.adapter import Usage
from core.workflow.state import ExecutorDecision, WorkflowConfig

TOKEN_IN = 10
TOKEN_OUT = 5
CALL_COST = 0.001


class ScriptedLLM:
    """按顺序返回 executor 决策，每次调用刷新 last_usage。"""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)
        self.last_usage: Usage | None = None
        self.calls = 0

    def invoke_model(
        self,
        messages: Any,
        schema: Any,
        model: str | None = None,
        **kwargs: Any,
    ) -> ExecutorDecision:
        self.calls += 1
        self.last_usage = Usage(
            model=model or "test-model",
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            cost=CALL_COST,
            duration_ms=1,
        )
        return ExecutorDecision(
            thought="",
            tool_name=None,
            tool_args={},
            answer=next(self._answers),
        )


def _state(task_id: str, steps: int) -> dict[str, Any]:
    return {
        "task": "测试多步任务",
        "task_id": task_id,
        "plan": [f"步骤 {index + 1}" for index in range(steps)],
        "current_step": 0,
        "execution_results": [],
        "review_result": False,
        "review_score": 0,
        "review_comment": "",
        "iteration": 0,
        "messages": [],
        "final_answer": "",
        "status": "running",
    }


def _ctx(
    llm: ScriptedLLM,
    trace: ListTraceSink,
    *,
    event_sink: Any = None,
) -> NodeContext:
    return NodeContext(
        llm=llm,  # type: ignore[arg-type] - 测试替身只需 invoke_model/last_usage
        config=WorkflowConfig(max_iterations=1),
        settings=Settings(llm_api_key=SecretStr("mock-key")),
        trace_sink=trace,
        event_sink=event_sink,
    )


def test_no_event_sink_accumulates_multiple_calls() -> None:
    """无 DB 批量评测：3 次调用 → 1 条 TraceRecord，金额/token 为三次之和。"""
    trace = ListTraceSink()
    llm = ScriptedLLM(["a", "b", "c"])
    node = ExecutorNode(_ctx(llm, trace))

    node(_state("task-h2-no-db", 3))

    assert len(trace.records) == 1
    record = trace.records[0]
    assert llm.calls == 3
    assert record.cost == pytest.approx(CALL_COST * 3)
    assert record.token_in == TOKEN_IN * 3
    assert record.token_out == TOKEN_OUT * 3


def test_event_channel_stays_per_call_without_double_count() -> None:
    """有 DB：仍落 3 条 llm_call；TraceRecord 汇总同样是 3 次，不双计。"""
    trace = ListTraceSink()
    events: list[EventRecord] = []
    llm = ScriptedLLM(["a", "b", "c"])
    node = ExecutorNode(_ctx(llm, trace, event_sink=events.append))

    node(_state("task-h2-with-db", 3))

    llm_events = [event for event in events if event.event_type == TASK_EVT_LLM_CALL]
    node_end_events = [event for event in events if event.event_type == TASK_EVT_NODE_END]
    assert llm.calls == 3
    assert len(llm_events) == 3
    assert len(node_end_events) == 1

    assert len(trace.records) == 1
    record = trace.records[0]
    assert record.cost == pytest.approx(sum(event.cost for event in llm_events))
    assert record.cost == pytest.approx(CALL_COST * 3)
    assert record.token_in == sum(event.tokens_in for event in llm_events)
    assert record.token_out == sum(event.tokens_out for event in llm_events)


def test_accumulator_resets_between_node_calls() -> None:
    """同一个节点实例跑两次：第二条 TraceRecord 只含第二次的 2 次调用。"""
    trace = ListTraceSink()
    llm = ScriptedLLM(["a1", "a2", "b1", "b2"])
    node = ExecutorNode(_ctx(llm, trace))

    node(_state("task-h2-reset", 2))
    node(_state("task-h2-reset", 2))

    assert llm.calls == 4
    assert len(trace.records) == 2
    for record in trace.records:
        assert record.cost == pytest.approx(CALL_COST * 2)
        assert record.token_in == TOKEN_IN * 2
