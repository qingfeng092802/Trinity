"""``POST /tasks`` / ``GET /tasks/{id}`` / 取消 / 并发上限 / 队列满 / FIFO。"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest

from tests.integration.conftest import (
    TestClient,
    poll_terminal,
    recorder_of,
    wait_running,
)

TASK_ID_RE = re.compile(r"^task-[0-9a-f]{12}$")


def _submit(client: TestClient, task: str, **kwargs: Any) -> dict[str, Any]:
    response = client.post("/tasks", json={"task": task, **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 提交与查询
# --------------------------------------------------------------------------- #
def test_submit_returns_201_immediately(api_env: TestClient) -> None:
    """验收 P0-2：201、task_id 格式、三个 URL、不等待执行。"""
    start = time.time()
    response = api_env.post("/tasks", json={"task": "用三句话解释什么是 RAG"})
    elapsed = time.time() - start

    assert response.status_code == 201
    assert elapsed < 2.0, f"受理应立即返回，实际耗时 {elapsed:.2f}s"
    body = response.json()
    assert TASK_ID_RE.match(body["task_id"])
    assert body["status"] in {"queued", "running"}
    assert body["poll_url"] == f"/tasks/{body['task_id']}"
    assert body["stream_url"] == f"/tasks/{body['task_id']}/stream"
    assert body["cancel_url"] == f"/tasks/{body['task_id']}/cancel"
    assert body["estimated_cost_cny"] >= 0
    assert isinstance(body["warnings"], list)
    # 测试环境未配 Key，应有告警
    assert any("LLM_API_KEY" in warning for warning in body["warnings"])


def test_get_task_missing_returns_404(api_env: TestClient) -> None:
    response = api_env.get("/tasks/task-doesnotexist00")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_submit_duplicate_task_id_returns_409(api_env: TestClient) -> None:
    body = _submit(api_env, "第一条任务")
    conflict = api_env.post("/tasks", json={"task": "第二条任务", "task_id": body["task_id"]})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "task_id_conflict"


def test_submit_blank_task_returns_422(api_env: TestClient) -> None:
    for bad in ("", "   "):
        response = api_env.post("/tasks", json={"task": bad})
        assert response.status_code == 422


def test_submit_task_id_bad_format_returns_422(api_env: TestClient) -> None:
    response = api_env.post("/tasks", json={"task": "合法任务", "task_id": "非法 ID!"})
    assert response.status_code == 422


def test_task_runs_to_done_with_mock_llm(api_env: TestClient) -> None:
    """全链路：提交 → 后台执行 → 落终态 done，字段齐全。"""
    body = _submit(api_env, "写一句关于春天的诗")
    view = poll_terminal(api_env, body["task_id"])

    assert view["status"] == "done"
    assert view["final_answer"].strip() != ""
    assert view["score"] == 9  # Mock reviewer 给 9 分，不跑 judge 时沿用评审分
    assert view["duration_ms"] >= 0
    assert view["iterations"] == 0  # 一次通过
    # progress 在终态应为 null（缓存已清理）
    assert view["progress"] is None


# --------------------------------------------------------------------------- #
# 取消
# --------------------------------------------------------------------------- #
def test_cancel_queued_task_has_zero_llm_calls(tiny_env: TestClient) -> None:
    """排队中取消 = 直接丢弃：被取消任务零 LLM 调用（验收 P0-5.1）。"""
    blocker = _submit(tiny_env, "慢任务：占住唯一的并发槽位")
    queued = _submit(tiny_env, "排队中的牺牲品")
    wait_running(tiny_env, blocker["task_id"])  # blocker 已占槽位，queued 还在等

    response = tiny_env.post(f"/tasks/{queued['task_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"

    final = poll_terminal(tiny_env, queued["task_id"])
    assert final["status"] == "canceled"
    assert recorder_of(tiny_env).calls_of(queued["task_id"]) == 0


def test_cancel_running_task_stops_at_node_boundary(api_env: TestClient) -> None:
    """运行中取消：不再进入下一个节点（LLM 调用次数明显少于完整执行）。"""
    body = _submit(api_env, "慢任务：预计 5 次 LLM 调用")
    task_id = body["task_id"]
    wait_running(api_env, task_id)
    time.sleep(0.3)  # 让 planner 至少跑完一次调用

    response = api_env.post(f"/tasks/{task_id}/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "canceled"
    assert payload["mode"] == "node_boundary"

    final = poll_terminal(api_env, task_id)
    assert final["status"] == "canceled"
    # 完整执行需要 5 次调用（planner + 2×executor + reviewer×2 轮以内），
    # 节点边界取消后必然更少
    assert recorder_of(api_env).calls_of(task_id) < 5


def test_cancel_status_stays_canceled(api_env: TestClient) -> None:
    """取消后状态不被 worker 覆盖：1.5s 内重复采样恒为 canceled（验收 P0-5.3）。"""
    body = _submit(api_env, "慢任务：取消后观察状态稳定性")
    task_id = body["task_id"]
    wait_running(api_env, task_id)
    assert api_env.post(f"/tasks/{task_id}/cancel").status_code == 200

    for _ in range(10):
        time.sleep(0.15)
        assert api_env.get(f"/tasks/{task_id}").json()["status"] == "canceled"


def test_cancel_terminal_task_returns_409(api_env: TestClient) -> None:
    body = _submit(api_env, "很快跑完的任务")
    poll_terminal(api_env, body["task_id"])

    response = api_env.post(f"/tasks/{body['task_id']}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "task_already_finished"


def test_cancel_missing_task_returns_404(api_env: TestClient) -> None:
    response = api_env.post("/tasks/task-doesnotexist00/cancel")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


# --------------------------------------------------------------------------- #
# 队列容量与顺序
# --------------------------------------------------------------------------- #
def test_queue_full_returns_429_with_retry_after(tiny_env: TestClient) -> None:
    """并发 1 + 队列 1：第 3 条 429 + Retry-After（验收 P0-4.2）。"""
    first = tiny_env.post("/tasks", json={"task": "慢任务：占槽位"}).json()
    second = tiny_env.post("/tasks", json={"task": "排队任务"}).json()
    time.sleep(0.2)  # 确保 first 已被 dispatcher 取走、second 稳定占用队列

    third = tiny_env.post("/tasks", json={"task": "注定被拒的任务"})
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "queue_full"
    assert third.headers.get("retry-after") == "5"

    # 清场：取消前两条，避免阻塞后续（这个 client 的队列只服务本测试）
    tiny_env.post(f"/tasks/{second['task_id']}/cancel")
    tiny_env.post(f"/tasks/{first['task_id']}/cancel")


def test_fifo_execution_order(serial_env: TestClient) -> None:
    """并发 1 时按提交顺序执行（验收 P0-4.4，以首次 LLM 调用顺序为准）。"""
    submitted = [
        _submit(serial_env, f"顺序任务 {i}")["task_id"] for i in range(3)
    ]
    for task_id in submitted:
        poll_terminal(serial_env, task_id)

    recorder = recorder_of(serial_env)
    observed = [task_id for task_id in recorder.first_call_order if task_id in submitted]
    assert observed == submitted


def test_concurrent_never_exceeds_limit(api_env: TestClient) -> None:
    """连发 4 条（上限 2）：任意时刻 running ≤ 2，且全部终态（验收 P0-4.1）。"""
    task_ids = [_submit(api_env, f"并发观察任务 {i}")["task_id"] for i in range(4)]

    max_running = 0
    deadline = time.time() + 20.0
    finished = 0
    while finished < 4 and time.time() < deadline:
        health = api_env.get("/health").json()["checks"]["queue"]
        max_running = max(max_running, health["running"])
        finished = sum(
            1
            for task_id in task_ids
            if api_env.get(f"/tasks/{task_id}").json()["status"]
            in {"done", "failed", "aborted", "canceled"}
        )
        time.sleep(0.05)

    assert max_running <= 2, f"观察到 running={max_running} 超过并发上限"
    assert finished == 4
