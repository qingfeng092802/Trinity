"""T02 埋点端到端：真编排跑完后，``task_events`` 里必须有事件（含工具调用）。

本文件与 ``test_trace_api.py`` 互补：

* ``test_trace_api.py::test_trace_real_run_persists_events`` 验证「默认 Mock 任务
  （不调工具）→ 事件落盘 → ``GET /trace`` 能查到」；
* 本文件进一步验证 **工具调用事件** 的 K7 字段映射（``name→tool_name`` /
  ``args→arguments`` / ``result→observation`` / ``duration_ms→latency_ms``），
  用脚本化 responder 让 executor 必调 ``calculator``（纯本地、无外部依赖）。

为什么要单独开文件：``tests/integration/conftest.py`` 的录制工厂用的是「永不调工具」
的 responder；要覆盖 tool_call 必须自带一个脚本化工厂，不动共享夹具。
且这里**直接查 DB**（``database.list_events``）断言，绕开 HTTP 层，
即使与 T03 的路由并行开发也互不阻塞。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.constants import (
    TASK_EVT_LLM_CALL,
    TASK_EVT_NODE,
    TASK_EVT_NODE_END,
    TASK_EVT_RUNNING,
    TASK_EVT_TOOL_CALL,
)
from core.agent.planner import PLAN_SCHEMA
from core.workflow.state import ExecutorDecision, ReviewVerdict
from tests.integration.conftest import Recorder, poll_terminal
from tests.integration.mock_llm import MockLLMAdapter


def _scripted_factory(monkeypatch: pytest.MonkeyPatch, *, tool_name: str | None) -> None:
    """把**存活队列实例**上的 runner 工厂换成脚本化版本（含事件落库）。

    关键（与 conftest 同一个坑）：``database`` 必须在 ``factory(item)`` 函数体内取
    ``get_database()``——此时 ``_apply_api_env`` 已注入临时库 ``DB_URL`` 并
    ``reset_api_caches()``，取到的才是那个临时库；模块级/import 期取会写错库。

    替换存活队列的 ``_worker.factory`` 而不是 patch ``deps``：``get_task_queue()``
    是 lifespan 期间创建的 lru_cache 单例，其 ``_worker`` 已捕获旧工厂，
    只清 deps 缓存影响不到它（见 ``test_knowledge_tool._script_factory`` 注释）。
    """
    from api.deps import get_database, get_task_queue, get_trace_store
    from api.runner import build_runner
    from config import get_settings

    counters = {"executor": 0}

    def responder(schema: Any, _text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return ["算一下", "给结论"]
        if schema is ExecutorDecision:
            counters["executor"] += 1
            if counters["executor"] == 1 and tool_name:
                return {
                    "thought": "需要算一下",
                    "tool_name": tool_name,
                    "tool_args": {"expression": "1+1"},
                    "answer": "",
                }
            return {
                "thought": "汇总",
                "tool_name": None,
                "tool_args": {},
                "answer": "本步结论",
            }
        if schema is ReviewVerdict:
            return {
                "pass": True,
                "score": 9,
                "comment": "结构完整",
                "final_answer": "这是 Mock 生成的最终答案。",
            }
        raise AssertionError(f"未预期的 schema：{schema}")

    def factory(item: Any) -> Any:
        return build_runner(
            item,
            settings=get_settings(),
            trace_store=get_trace_store(),
            llm=MockLLMAdapter(responder),
            database=get_database(),
        )

    queue = get_task_queue()
    monkeypatch.setattr(queue._worker, "factory", factory)  # noqa: SLF001 - 替换存活 worker 工厂


def test_tool_call_event_persisted_with_k7_mapping(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ executor 调用 calculator → ``task_events`` 落一条 ``tool_call``，字段按 K7 映射。"""
    from api.deps import get_database

    _scripted_factory(monkeypatch, tool_name="calculator")

    submitted = api_env.post("/tasks", json={"task": "帮我算 1+1", "use_tools": True})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]

    final = poll_terminal(api_env, task_id)
    assert final["status"] == "done", final

    database = get_database()
    events = database.list_events(task_id, limit=200)
    assert events, "真任务必须落盘事件（若为空说明埋点未生效）"

    tool_events = [event for event in events if event.event_type == TASK_EVT_TOOL_CALL]
    assert len(tool_events) == 1, f"应恰好 1 条 tool_call 事件，实际 {len(tool_events)}"

    event = tool_events[0]
    # K7 字段映射（错一个就丢数据且不报错）
    assert event.tool_name == "calculator", "name 必须映射到 tool_name"
    assert event.arguments == '{"expression": "1+1"}', "args 必须序列化进 arguments（JSON 串）"
    assert event.observation == "2", "result 必须映射到 observation"
    assert event.status == "success"
    assert event.latency_ms >= 0, "duration_ms 必须映射到 latency_ms"
    # 归属：工具事件挂在 executor 下，带编排轮次与轮内子步骤
    assert event.role == "executor"
    assert event.step == 0, "首轮执行的编排轮次为 0（K1）"
    assert event.sub_step == 0, "第一个子步骤下标为 0"

    # 事件顺序按 event_seq 严格递增（回放排序唯一依据，K1）
    seqs = [int(item.event_seq) for item in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "event_seq 不得重复"


def test_real_run_event_types_and_step_semantics(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真编排（不调工具）→ 事件类型齐全 + ``step`` 语义是编排轮次而非子步骤下标。"""
    from api.deps import get_database

    _scripted_factory(monkeypatch, tool_name=None)

    submitted = api_env.post("/tasks", json={"task": "写一句话", "use_tools": True})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]
    poll_terminal(api_env, task_id)

    events = get_database().list_events(task_id, limit=200)
    types = [event.event_type for event in events]

    assert TASK_EVT_RUNNING in types, "缺 running（Q1）"
    assert TASK_EVT_LLM_CALL in types, "缺 llm_call（L1）"
    assert TASK_EVT_NODE_END in types, "缺 node_end（L2）"
    assert TASK_EVT_NODE in types, "缺 node（Q2）"
    assert TASK_EVT_TOOL_CALL not in types, "未调工具不应有 tool_call 事件"

    # llm_call / node_end 属于节点级事件：必有 role/node；且 step 为编排轮次
    node_events = [e for e in events if e.event_type in {TASK_EVT_LLM_CALL, TASK_EVT_NODE_END}]
    assert node_events
    for event in node_events:
        assert event.role in {"planner", "executor", "reviewer"}
        assert event.node == event.role
        assert event.step >= 0
    # planner 恒在 iteration=0 跑 → 其 step 必为 0
    planner_events = [e for e in node_events if e.role == "planner"]
    assert planner_events and all(e.step == 0 for e in planner_events)


def test_run_without_tool_still_has_no_tool_name_leak(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NULL 语义：非工具事件的 ``tool_name`` / ``arguments`` 必须是 NULL（不是 '' / '{}'）。"""
    from api.deps import get_database

    _scripted_factory(monkeypatch, tool_name=None)

    submitted = api_env.post("/tasks", json={"task": "随便写点", "use_tools": True})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]
    poll_terminal(api_env, task_id)

    events = get_database().list_events(task_id, limit=200)
    non_tool = [e for e in events if e.event_type != TASK_EVT_TOOL_CALL]
    assert non_tool
    for event in non_tool:
        assert event.tool_name is None, "非工具事件 tool_name 必须是 NULL"
        assert event.arguments is None, "非工具事件 arguments 必须是 NULL，不允许 '{}'（K3）"


def test_executor_multi_step_persists_one_llm_call_per_step(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ Q6-01 回归闸：一次节点调用跑 N 个计划步 ⇒ 落 **N 条** ``llm_call``，钱按步累加。

    计划固定 2 步（``_scripted_factory`` 的 responder 返回 ``["算一下", "给结论"]``），
    Mock 每次调用记 ``COST_PER_CALL`` + 42 入 / 17 出。

    **这条用例改前必红**：旧实现只在节点出口落 1 条汇总，且取 ``last_usage`` =
    最后一步的用量 ⇒ 拿到的是 1 条、钱只有一份。它守的是本机真库复算出的那 15 条缺口
    （32 条任务、executor ≥53 次调用 vs 38 条事件）；哪天把按步埋点撤回去，
    它应当红在这里，而不是让预算闸门与成本面板静默少算。
    """
    from api.deps import get_database

    _scripted_factory(monkeypatch, tool_name="calculator")

    submitted = api_env.post("/tasks", json={"task": "帮我算 1+1", "use_tools": True})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]
    final = poll_terminal(api_env, task_id)
    assert final["status"] == "done", final

    events = get_database().list_events(task_id, limit=200)
    executor_calls = [
        event for event in events if event.event_type == TASK_EVT_LLM_CALL and event.role == "executor"
    ]
    assert len(executor_calls) == 2, (
        f"2 步计划应落 2 条 executor 的 llm_call，实际 {len(executor_calls)} 条"
        "（=1 说明又退回'一次节点调用一条汇总'的旧口径）"
    )
    assert [event.sub_step for event in executor_calls] == [0, 1], "sub_step 必须是轮内步下标"
    assert {event.step for event in executor_calls} == {0}, "首轮：编排轮次恒 0"
    total_cost = sum(float(event.cost or 0.0) for event in executor_calls)
    assert total_cost == pytest.approx(2 * MockLLMAdapter.COST_PER_CALL), "钱必须按步累加"
    assert {int(event.tokens_in or 0) for event in executor_calls} == {42}

    # 出口那条汇总必须同时关掉，否则最后一步被计两遍：
    # 全任务 llm_call = planner 1 + executor 2 + reviewer 1 = 4
    all_calls = [event for event in events if event.event_type == TASK_EVT_LLM_CALL]
    assert len(all_calls) == 4, f"llm_call 总数应为 4（1+2+1），实际 {len(all_calls)}"


__all__ = ["_scripted_factory"]
