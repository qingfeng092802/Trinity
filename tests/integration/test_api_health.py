"""``GET /health``、OpenAPI 契约与 Bearer 鉴权。"""

from __future__ import annotations

import time
from typing import Any

import pytest

import api
from tests.integration.conftest import TestClient

EXPECTED_PATHS = {
    "/tasks",
    "/tasks/{task_id}",
    "/tasks/{task_id}/stream",
    "/tasks/{task_id}/cancel",
    "/tasks/{task_id}/trace",
    "/tools",
    "/tools/{tool_name}/invoke",
    "/eval",
    "/health",
}


def test_openapi_contains_all_endpoints(api_env: TestClient) -> None:
    """验收 P0-1.2：端点全部在契约里，/docs 可访问。"""
    response = api_env.get("/openapi.json")
    assert response.status_code == 200
    assert EXPECTED_PATHS.issubset(set(response.json()["paths"].keys()))

    assert api_env.get("/docs").status_code == 200


def test_health_shape_and_checks(api_env: TestClient) -> None:
    """无 Key 环境：llm=fail → 整体 unhealthy(503)；Redis 不通只是 degraded。"""
    response = api_env.get("/health")
    # 未配置 LLM Key → 按设计 503
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    # 不写死字面量：/health.version 由 api.__version__ 提供，版本一致性另由
    # tests/unit/test_version_consistency.py 钉住（见 known_residuals G-5）
    assert body["version"] == api.__version__
    checks = body["checks"]
    assert checks["api"]["status"] == "ok"
    assert checks["database"]["status"] == "ok"
    assert checks["llm"]["status"] == "fail"
    # Redis 指向不可达端口 → degraded（不是 fail）
    assert checks["redis"]["status"] == "degraded"
    assert checks["queue"]["status"] == "ok"
    assert set(checks["queue"]) >= {"running", "queued", "max_concurrent"}


def test_health_queue_counts_match_submissions(api_env: TestClient) -> None:
    """验收 P0-9.5：提交 2 条后 running + queued = 2。"""
    task_ids = []
    for i in range(2):
        response = api_env.post("/tasks", json={"task": f"健康计数任务 {i}"})
        assert response.status_code == 201
        task_ids.append(response.json()["task_id"])

    matched = False
    deadline = time.time() + 3.0
    while time.time() < deadline and not matched:
        queue = api_env.get("/health").json()["checks"]["queue"]
        matched = queue["running"] + queue["queued"] == 2
        time.sleep(0.05)
    assert matched, f"健康检查的队列计数与提交数不符：{queue}"


def test_eval_list_empty_and_validation(api_env: TestClient) -> None:
    """验收 P0-8.1 / P0-8.3：空库结构 + limit 越界 422。"""
    response = api_env.get("/eval")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    assert api_env.get("/eval", params={"limit": 201}).status_code == 422
    assert api_env.get("/eval", params={"limit": 0}).status_code == 422
    assert api_env.get("/eval", params={"limit": 10, "offset": 0}).status_code == 200


# --------------------------------------------------------------------------- #
# 鉴权（P0-12）
# --------------------------------------------------------------------------- #
def test_auth_enforced_when_token_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """设 API_AUTH_TOKEN 后：无 token 401、错误 token 401、/health 与 /docs 免鉴权。"""
    from tests.integration.conftest import Recorder, _apply_api_env, _start_client

    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_TOKEN", "secret-token-123")
    try:
        with _start_client(monkeypatch, Recorder()) as client:
            # 无 token
            response = client.post("/tasks", json={"task": "鉴权测试"})
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "unauthorized"
            assert response.headers.get("www-authenticate") == "Bearer"

            # 错误 token
            response = client.post(
                "/tasks",
                json={"task": "鉴权测试"},
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert response.status_code == 401

            # 正确 token → 201
            response = client.post(
                "/tasks",
                json={"task": "鉴权测试"},
                headers={"Authorization": "Bearer secret-token-123"},
            )
            assert response.status_code == 201

            # /health 与 /docs 免鉴权（验收 P0-12.3）：不受 401 拦截。
            # /health 的业务状态码由依赖健康度决定（无 Key 时是 503），所以
            # 只断言「不是 401」，/docs 恒 200。
            assert client.get("/health").status_code in {200, 503}
            assert client.get("/docs").status_code == 200
    finally:
        from config import reset_settings_cache

        reset_settings_cache()


def test_auth_open_when_token_empty(api_env: TestClient) -> None:
    """未设 token（默认）：全放行 + 健康检查正常工作。"""
    assert api_env.post("/tasks", json={"task": "匿名提交"}).status_code == 201
    assert api_env.get("/health").status_code in {200, 503}
