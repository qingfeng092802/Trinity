"""Session Memory v1 API：session_id 透传、回显与非法值拦截。"""

from __future__ import annotations

from tests.integration.conftest import TestClient, poll_terminal


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
