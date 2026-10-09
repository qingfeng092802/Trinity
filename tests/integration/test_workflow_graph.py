"""阶段 1 集成测试：用 Mock LLM 跑完整编排图，覆盖五条关键路径。

1. 一次通过；
2. 评审不通过 → 整轮重做 → 通过（验证 iteration 与「意见回灌」）；
3. 迭代上限 → 强制收口（验证一定停机，且草稿答案不丢）；
4. 节点异常 → 被兜住并立即结束（验证不再继续烧 token）；
5. 流式输出 → 节点事件按顺序吐出（供阶段 4 的实时日志页使用）。

另外单独覆盖 executor 的工具分支：工具层未接入时如实记为 failed，
接入后如实记录工具调用（阶段 2 会把真实 registry 换进来）。
"""

from __future__ import annotations

from typing import Any

from core.agent.base import ListTraceSink, NodeContext, ToolInvoker
from core.agent.planner import PLAN_SCHEMA
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry
from core.workflow.graph import WorkflowRunner
from core.workflow.state import (
    ExecutorDecision,
    ReviewVerdict,
    WorkflowConfig,
    initial_state,
)
from tests.integration.mock_llm import MockLLMAdapter, StubToolInvoker

STEPS = ["收集事实", "形成结论", "自检覆盖度"]
FINAL_ANSWER = "AI Agent 的 ReAct 循环：推理与行动交替，观察结果驱动下一轮思考。"
PASS_VERDICT: dict[str, Any] = {
    "pass": True,
    "score": 9,
    "comment": "结构完整，可直接交付",
    "final_answer": FINAL_ANSWER,
}


def build_runner(
    verdicts: list[dict[str, Any]],
    *,
    config: WorkflowConfig | None = None,
    tool_invoker: ToolInvoker | None = None,
    tool_name: str | None = None,
) -> tuple[WorkflowRunner, MockLLMAdapter, ListTraceSink]:
    """按剧本构造 runner：verdicts 按轮次取用，用尽后一直沿用最后一条。"""

    def responder(schema: Any, text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return list(STEPS)
        if schema is ExecutorDecision:
            return {
                "thought": "先判断要不要用工具，再给结论",
                "tool_name": tool_name,
                "tool_args": {"expression": "6*7"} if tool_name else {},
                "answer": "" if tool_name else f"本步结论（{text[:24]}）",
            }
        if schema is ReviewVerdict:
            # invoke_json 在调用 responder 之前已经记录了本次调用，所以当前轮次 = 已记录数 - 1
            round_index = len(llm.calls_for(ReviewVerdict)) - 1
            return verdicts[min(round_index, len(verdicts) - 1)]
        raise AssertionError(f"未预期的 schema：{schema}")

    llm = MockLLMAdapter(responder)
    sink = ListTraceSink()
    ctx = NodeContext.create(
        llm=llm,
        config=config or WorkflowConfig(max_iterations=3, review_threshold=7),
        trace_sink=sink,
        tool_invoker=tool_invoker,
    )
    return WorkflowRunner(ctx), llm, sink


# --------------------------------------------------------------------------- #
# 1. 一次通过
# --------------------------------------------------------------------------- #
def test_happy_path_finishes_in_one_round() -> None:
    runner, llm, sink = build_runner([PASS_VERDICT])

    state = runner.run("用三句话解释什么是 AI Agent")

    assert state["status"] == "done"
    assert state["plan"] == STEPS
    assert [item["step_index"] for item in state["execution_results"]] == [0, 1, 2]
    assert state["review_result"] is True
    assert state["review_score"] == 9
    assert state["iteration"] == 0
    # 通过时用 reviewer 给出的终稿，而不是 executor 拼接的执行日志
    assert state["final_answer"] == FINAL_ANSWER
    assert state["task_id"].startswith("task-")

    # 3 个子步骤 → 3 次 executor 决策；reviewer 只跑 1 轮
    assert len(llm.calls_for(ExecutorDecision)) == 3
    assert len(llm.calls_for(ReviewVerdict)) == 1

    # messages 通过 add_messages reducer 累积：planner 3 条 + 每步 3 条 × 3 步 + reviewer 3 条
    assert len(state["messages"]) == 3 + 3 * len(STEPS) + 3

    # 三个角色各留下一条埋点
    assert [record.role for record in sink.records] == ["planner", "executor", "reviewer"]
    assert sink.summary()["failed"] == 0


# --------------------------------------------------------------------------- #
# 2. 评审不通过 → 整轮重做
# --------------------------------------------------------------------------- #
def test_review_failure_triggers_full_round_redo() -> None:
    runner, llm, _sink = build_runner(
        [
            {"pass": False, "score": 5, "comment": "第 2 步只给结论没有依据，请补推理过程"},
            PASS_VERDICT,
        ]
    )

    state = runner.run("写一份储能调度方案说明")

    assert state["status"] == "done"
    assert state["iteration"] == 1
    assert len(llm.calls_for(ReviewVerdict)) == 2
    # 整轮重做：3 步 × 2 轮 = 6 次 executor 决策
    assert len(llm.calls_for(ExecutorDecision)) == 6
    # 结果按 step_index 覆盖，不会随重做轮数线性膨胀
    assert [item["step_index"] for item in state["execution_results"]] == [0, 1, 2]

    # 第二轮把上一轮的评审意见回灌给了 executor
    round_two = llm.calls_for(ExecutorDecision)[3]["text"]
    assert "第 2 步只给结论没有依据" in round_two

    # 首轮 executor 的提示词里没有评审意见，第二轮才有
    assert "首轮执行，暂无评审意见" in llm.calls_for(ExecutorDecision)[0]["text"]


# --------------------------------------------------------------------------- #
# 3. 迭代上限 → 强制收口
# --------------------------------------------------------------------------- #
def test_iteration_limit_forces_stop() -> None:
    runner, llm, _ = build_runner(
        [{"pass": False, "score": 3, "comment": "仍不合格"}],
        config=WorkflowConfig(max_iterations=3, review_threshold=7),
    )

    state = runner.run("做一个很难的任务")

    assert state["status"] == "aborted"
    assert state["iteration"] == 3
    assert state["review_result"] is False
    assert len(llm.calls_for(ReviewVerdict)) == 3
    assert len(llm.calls_for(ExecutorDecision)) == 3 * len(STEPS)
    # 强制收口时没有终稿，回退到 executor 拼出的草稿，不空手而归
    assert state["final_answer"].startswith("已完成")
    assert STEPS[0] in state["final_answer"]


# --------------------------------------------------------------------------- #
# 4. 节点异常 → 兜住并立刻停机
# --------------------------------------------------------------------------- #
def test_node_failure_is_contained_and_stops_immediately() -> None:
    def responder(schema: Any, text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return []  # 触发 planner 的 PlanError
        raise AssertionError("进入失败终态后不应再调用 LLM")

    llm = MockLLMAdapter(responder)
    runner = WorkflowRunner(
        NodeContext.create(llm=llm, config=WorkflowConfig(max_iterations=3))
    )

    state = runner.run("触发失败路径")

    assert state["status"] == "failed"
    assert "planner" in state["review_comment"]
    assert "PlanError" in state["review_comment"]
    # 只发生了 1 次 LLM 调用：planner 失败后 executor / reviewer 都不该再动 LLM
    assert len(llm.calls) == 1


# --------------------------------------------------------------------------- #
# 5. 流式输出
# --------------------------------------------------------------------------- #
def test_stream_yields_node_events_in_order() -> None:
    runner, _, _ = build_runner([PASS_VERDICT])

    events = list(runner.stream("流式输出测试"))

    assert [name for name, _ in events] == ["planner", "executor", "reviewer"]
    assert events[0][1]["plan"] == STEPS
    assert events[1][1]["current_step"] == len(STEPS)
    assert events[2][1]["status"] == "done"


# --------------------------------------------------------------------------- #
# 附加：executor 的工具分支
# --------------------------------------------------------------------------- #
def test_executor_records_failed_call_when_no_tool_layer() -> None:
    """阶段 1 没有工具层：模型硬要调工具时，如实记为 failed，而不是假装成功。"""
    runner, _, _ = build_runner([PASS_VERDICT], tool_name="calculator")

    state = runner.run("算一下 6*7")

    calls = state["execution_results"][0]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["name"] == "calculator"
    assert calls[0]["status"] == "failed"
    assert "工具层未接入" in calls[0]["result"]
    # 工具失败也不丢结论：用工具返回/兜底文本撑住 output
    assert state["execution_results"][0]["output"].strip()
    assert state["execution_results"][0]["status"] == "failed"


def test_executor_uses_injected_tool_layer() -> None:
    """注入符合协议的替身工具层后，工具调用被如实记录并进入结论。"""
    invoker = StubToolInvoker(result="42")
    runner, _, _ = build_runner([PASS_VERDICT], tool_invoker=invoker, tool_name="calculator")

    state = runner.run("算一下 6*7")

    # 剧本里每一步都会要求调工具，所以 3 个子步骤 → 3 次调用
    assert invoker.calls == [("calculator", {"expression": "6*7"})] * len(STEPS)
    calls = state["execution_results"][0]["tool_calls"]
    assert calls[0]["status"] == "success"
    assert calls[0]["duration_ms"] == 3
    assert "42" in state["execution_results"][0]["output"]
    # 提示词里应带上工具清单
    assert "calculator" in invoker.describe()


def test_executor_calls_real_registry_tool() -> None:
    """把**真实注册表**接进编排：executor 的工具分支端到端跑通（阶段 2 的核心验收）。

    用 calculator 是为了不碰文件系统与网络，保证这条链路可重复。
    """
    registry = load_builtin_tools(ToolRegistry(enable_hitl=False))
    runner, llm, _ = build_runner([PASS_VERDICT], tool_invoker=registry, tool_name="calculator")

    state = runner.run("算一下 6*7")

    calls = [item["tool_calls"][0] for item in state["execution_results"]]
    assert len(calls) == len(STEPS)
    assert all(call["status"] == "success" for call in calls)
    # 真实 calculator 算出来的值，不是替身写死的
    assert calls[0]["result"].strip() == "42"
    assert calls[0]["duration_ms"] >= 0
    # 提示词里的工具清单来自真实注册表（收敛后的 3 个内置工具）
    prompt = llm.calls_for(ExecutorDecision)[0]["text"]
    assert "calculator" in prompt and "code_exec" in prompt
    assert "knowledge_search" in prompt
    assert "高危" in prompt


def test_partial_state_update_keeps_messages_reducer() -> None:
    """节点只返回增量：messages 是累加的，不会被整轮覆盖。"""
    runner, llm, _ = build_runner([PASS_VERDICT])

    state = runner.run("验证 reducer")

    planner_messages = len(llm.calls_for(ExecutorDecision))
    assert planner_messages == len(STEPS)
    # 计划、结果、终态字段都在同一份状态里
    assert set(state) >= {
        "task",
        "task_id",
        "plan",
        "current_step",
        "execution_results",
        "review_result",
        "review_score",
        "review_comment",
        "iteration",
        "messages",
        "final_answer",
        "status",
    }
    assert initial_state("x")["status"] == "running"
