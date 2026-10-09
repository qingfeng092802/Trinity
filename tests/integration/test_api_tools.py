"""单工具调用：成功 / 未注册 / 参数校验失败 / HITL 三态。"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import TestClient


def test_calculator_success(api_env: TestClient) -> None:
    """验收 P0-7.1：calculator 1+1 → success，result 含 2。"""
    response = api_env.post("/tools/calculator/invoke", json={"args": {"expression": "1+1"}})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "calculator"
    assert body["status"] == "success"
    assert "2" in body["result"]
    assert body["hitl"]["required"] is False
    assert body["duration_ms"] >= 0


def test_unknown_tool_returns_404(api_env: TestClient) -> None:
    """验收 P0-7.4：未注册工具 404，错误信息列出可用工具。"""
    response = api_env.post("/tools/no_such_tool/invoke", json={"args": {}})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "tool_not_found"
    assert "calculator" in detail["message"]


def test_tool_validation_failure_is_200_with_failed_status(api_env: TestClient) -> None:
    """验收 P0-7.5：参数校验失败不抛 500，编码进 status（限制 L6）。"""
    response = api_env.post("/tools/calculator/invoke", json={"args": {"expression": "1+"}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"failed", "timeout"}


def test_missing_args_key_defaults_to_empty(api_env: TestClient) -> None:
    response = api_env.post("/tools/calculator/invoke", json={})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# HITL（enable_hitl=true 时高危工具 fail-closed）
# --------------------------------------------------------------------------- #
def test_hitl_high_risk_denied_without_approval(hitl_env: TestClient) -> None:
    """验收 P0-7.2：HITL 开启 + code_exec + 无审批 → 拒绝且**不得**执行代码。"""
    response = hitl_env.post(
        "/tools/code_exec/invoke", json={"args": {"code": "print('should-not-run')"}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["hitl"]["required"] is True
    assert body["hitl"]["approved"] is False
    assert body["hitl"]["reason"] is not None


def test_hitl_high_risk_denied_without_server_override(hitl_env: TestClient) -> None:
    """带 ?approve_high_risk=true 但服务端未开 override → 仍拒绝（三层门禁第 2 层）。"""
    response = hitl_env.post(
        "/tools/code_exec/invoke",
        json={"args": {"code": "print('should-not-run')"}},
        params={"approve_high_risk": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "API_ALLOW_HIGH_RISK_OVERRIDE" in body["hitl"]["reason"]


def test_hitl_low_risk_tool_unaffected(hitl_env: TestClient) -> None:
    """HITL 只管 high 危险级：calculator 不受影响。"""
    response = hitl_env.post("/tools/calculator/invoke", json={"args": {"expression": "2*3"}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["hitl"]["required"] is False


# --------------------------------------------------------------------------- #
# B-3（P1）：ENABLE_HITL=false 不再是"零门槛"
#
# 旧实现是 `needs_approval = settings.enable_hitl and danger == "high"`，于是
# `.env` 里一行 `ENABLE_HITL=false` 就把 fail-closed 翻成 fail-open：报告实测
# 无 Authorization 头直接 POST /tools/code_exec/invoke 就能跑任意代码，
# `?approve_high_risk=true` 这根链条从来没被要求过。
# API 这条通道上没有人，所以"审批流没启用"只能推出"没人能批"。
# --------------------------------------------------------------------------- #
_SENTINEL_CODE = "print('SENTINEL-CODE-RAN')"


def test_high_risk_denied_when_hitl_disabled(api_env: TestClient) -> None:
    """``ENABLE_HITL`` 未设（默认 false）+ 高危 + 无审批 → 拒绝，且**代码没跑**。"""
    response = api_env.post("/tools/code_exec/invoke", json={"args": {"code": _SENTINEL_CODE}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["hitl"]["required"] is True, "关掉审批流不该等于关掉门禁"
    assert body["hitl"]["approved"] is False
    assert "SENTINEL-CODE-RAN" not in body["result"]


def test_high_risk_still_denied_when_hitl_disabled_but_client_approves(api_env: TestClient) -> None:
    """客户端单方面传 ``approve_high_risk=true`` 也不算数（服务端 override 才是第二把钥匙）。"""
    response = api_env.post(
        "/tools/code_exec/invoke",
        json={"args": {"code": _SENTINEL_CODE}},
        params={"approve_high_risk": "true"},
    )
    body = response.json()
    assert body["status"] == "failed"
    assert "API_ALLOW_HIGH_RISK_OVERRIDE" in body["hitl"]["reason"]
    assert "SENTINEL-CODE-RAN" not in body["result"]


def test_拒绝理由里写清了关开关没用(api_env: TestClient) -> None:
    """文案要挡住下一个"我把 ENABLE_HITL 设成 false 不就行了"。"""
    body = api_env.post("/tools/code_exec/invoke", json={"args": {"code": "print(1)"}}).json()
    assert "ENABLE_HITL" in body["hitl"]["reason"]


def test_low_risk_still_runs_when_hitl_disabled(api_env: TestClient) -> None:
    """反向钉：门禁按危险级生效，不是"整个 /invoke 都拒"。"""
    body = api_env.post(
        "/tools/calculator/invoke", json={"args": {"expression": "2*3"}}
    ).json()
    assert body["status"] == "success"
    assert body["hitl"]["required"] is False


def test_high_risk_allowed_with_both_keys(override_env: TestClient) -> None:
    """两把钥匙齐全（``approve_high_risk=true`` + 服务端 override）→ 真的放行、真的跑。

    没有这一条，上面的拒绝用例可能只是"接口整个坏了"，判不出门禁有没有钥匙。
    """
    body = override_env.post(
        "/tools/code_exec/invoke",
        json={"args": {"code": _SENTINEL_CODE}},
        params={"approve_high_risk": "true"},
    ).json()
    assert body["status"] == "success", body
    assert body["hitl"]["approved"] is True
    assert "SENTINEL-CODE-RAN" in body["result"]


# --------------------------------------------------------------------------- #
# GET /tools（只读工具清单；前端「内置工具」页的唯一数据源，绝不硬编码）
# --------------------------------------------------------------------------- #
#: 内置工具的**完整清单**，由 core/tools/builtin 决定；顺序由 registry.specs()
#: 的 sorted() 保证为字母序。
_EXPECTED_TOOL_NAMES = [
    "calculator",
    "code_exec",
    "knowledge_search",
]

#: 每个列表项必须齐全的字段（**刻意不含 func**）。
_REQUIRED_ITEM_KEYS = {"name", "description", "danger_level", "timeout", "retry", "parameters"}

#: 高危工具（会执行代码）。file_io 已随工具面收敛下线。
_HIGH_RISK_TOOLS = {"code_exec"}


def test_list_tools_returns_200(api_env: TestClient) -> None:
    """验收 T01：GET /tools 返回 200（本机此前实测为 404）。"""
    response = api_env.get("/tools")
    assert response.status_code == 200


def test_list_tools_total_and_count(api_env: TestClient) -> None:
    """total 与 items 同源：均为 3（工具面已收敛）。"""
    body = api_env.get("/tools").json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_list_tools_names_exactly_and_sorted(api_env: TestClient) -> None:
    """工具名恰好是这 3 个，且为字母序（registry.specs() 的 sorted 保证）。"""
    names = [item["name"] for item in api_env.get("/tools").json()["items"]]
    assert names == _EXPECTED_TOOL_NAMES


def test_list_tools_never_leaks_func(api_env: TestClient) -> None:
    """防 Callable 泄漏的**关键回归**：每一项都不得出现 func 键。

    ToolSpec.func 是 Field(exclude=True)，但它只作用于 model_dump() 的默认行为，
    不能保证作为 FastAPI response_model 时被自动剔除——所以必须逐项断言。
    """
    body = api_env.get("/tools").json()
    for item in body["items"]:
        assert "func" not in item
    # 兜底：整份响应体序列化后也不得出现该键
    assert '"func"' not in response_text(body)


def test_list_tools_item_fields_complete(api_env: TestClient) -> None:
    """每项字段齐全：6 个期望字段是 item keys 的子集。"""
    for item in api_env.get("/tools").json()["items"]:
        assert _REQUIRED_ITEM_KEYS.issubset(item.keys())


def test_list_tools_danger_levels(api_env: TestClient) -> None:
    """danger_level 正确：code_exec 为 high，其余 2 个为 low。"""
    items = api_env.get("/tools").json()["items"]
    by_name = {item["name"]: item["danger_level"] for item in items}
    for name in _EXPECTED_TOOL_NAMES:
        expected = "high" if name in _HIGH_RISK_TOOLS else "low"
        assert by_name[name] == expected, f"{name} 的危险级应为 {expected}"


def test_list_tools_parameters_are_json_schema(api_env: TestClient) -> None:
    """parameters 是非空 dict 且含 type/properties（前端据此动态建表单）。"""
    for item in api_env.get("/tools").json()["items"]:
        params = item["parameters"]
        assert isinstance(params, dict) and params
        assert "type" in params
        assert "properties" in params


def test_list_tools_timeout_retry_are_ints(api_env: TestClient) -> None:
    """timeout/retry 是 int；抽查 calculator 的 timeout==5, retry==0。"""
    items = api_env.get("/tools").json()["items"]
    for item in items:
        assert isinstance(item["timeout"], int)
        assert isinstance(item["retry"], int)
    calculator = next(item for item in items if item["name"] == "calculator")
    assert calculator["timeout"] == 5
    assert calculator["retry"] == 0


def response_text(payload: Any) -> str:
    """把响应体序列化成文本，用于 grep 敏感键（如 ``"func"``）。"""
    import json

    return json.dumps(payload, ensure_ascii=False)
