"""Session Memory v1 API：session_id 透传、回显与非法值拦截。"""

from __future__ import annotations

from typing import Any

import pytest

from api.deps import get_database, get_task_queue, get_trace_store
from api.runner import build_runner
from config import get_settings
from core.agent.planner import PLAN_SCHEMA
from core.workflow.state import ExecutorDecision, ReviewVerdict
from tests.integration.conftest import TestClient, poll_terminal
from tests.integration.mock_llm import MockLLMAdapter


def test_submit_with_session_id_echoes_and_persists(api_env: TestClient) -> None:
    response = api_env.post(
        "/tasks",
        json={"task": "会话回显任务", "session_id": "sess-api-1"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["session_id"] == "sess-api-1"

    final = poll_terminal(api_env, body["task_id"])
    assert final["session_id"] == "sess-api-1"
    assert final["status"] == "done"


def test_invalid_session_id_is_rejected(api_env: TestClient) -> None:
    response = api_env.post(
        "/tasks",
        json={"task": "非法 session", "session_id": "bad id!"},
    )
    assert response.status_code == 422, response.text


def _install_capturing_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, MockLLMAdapter]:
    """替换 worker 工厂，保留每个任务的 Mock adapter 以便检查 Prompt。"""
    adapters: dict[str, MockLLMAdapter] = {}

    def responder(schema: Any, _text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return ["收集事实", "形成结论"]
        if schema is ExecutorDecision:
            return {
                "thought": "直接给结论",
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
        adapter = MockLLMAdapter(responder)
        adapters[item.task_id] = adapter
        return build_runner(
            item,
            settings=get_settings(),
            trace_store=get_trace_store(),
            llm=adapter,
            database=get_database(),
        )

    monkeypatch.setattr(get_task_queue()._worker, "factory", factory)  # 替换存活 worker 工厂
    return adapters


def _planner_prompt(adapter: MockLLMAdapter) -> str:
    calls = [call for call in adapter.calls if call["schema"] is PLAN_SCHEMA]
    assert calls, "没有捕获到 planner 调用"
    return str(calls[0]["text"])


def test_second_turn_prompt_contains_first_turn(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一 session 的第二问，planner Prompt 必须带上一轮 Q/A；不同 session 不串。"""
    adapters = _install_capturing_factory(monkeypatch)
    first_question = "第一问：差旅报销口径是什么？"
    second_question = "那差旅标准呢？"

    first = api_env.post(
        "/tasks", json={"task": first_question, "session_id": "sess-prompt"}
    )
    assert first.status_code == 201, first.text
    poll_terminal(api_env, first.json()["task_id"])

    second = api_env.post(
        "/tasks", json={"task": second_question, "session_id": "sess-prompt"}
    )
    assert second.status_code == 201, second.text
    poll_terminal(api_env, second.json()["task_id"])

    prompt = _planner_prompt(adapters[second.json()["task_id"]])
    assert first_question in prompt
    assert "这是 Mock 生成的最终答案。" in prompt
    assert second_question in prompt

    # 另一个 session：不应看到 sess-prompt 的历史
    third = api_env.post(
        "/tasks", json={"task": "另一个会话的问题", "session_id": "sess-other"}
    )
    assert third.status_code == 201, third.text
    poll_terminal(api_env, third.json()["task_id"])
    third_prompt = _planner_prompt(adapters[third.json()["task_id"]])
    assert first_question not in third_prompt
