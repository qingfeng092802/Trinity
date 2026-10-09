"""运行配置新字段的端到端用例：回执、预算闸门真的掐、检索上限真的传到工具。

三条各自盯一种"不报错但会骗人"：

* ``POST /tasks`` 收下新字段后**回执**给不给（不给 ⇒ 前端只能显示自己发的那份，
  老后端静默丢字段时界面就在说谎）；
* 预算闸门是不是真的把任务停了（停了还得说清是**被预算停的**，不是"用户取消了"）；
* 用户配的 ``rag_top_k`` 到底传没传到检索调用上（配了不生效 = 又一个假控件）。
"""

from __future__ import annotations

from typing import Any

import pytest

from core.tools.builtin import knowledge_search as ks
from core.tools.task_context import task_top_k_scope
from tests.integration.conftest import TestClient, poll_terminal

# --------------------------------------------------------------------------- #
# 回执
# --------------------------------------------------------------------------- #
def test_新字段被服务端原样回执(api_env: TestClient) -> None:
    response = api_env.post(
        "/tasks",
        json={
            "task": "带配置的任务",
            "max_iterations": 4,
            "review_threshold": 9,
            "max_cost_cny": 0.35,
            "timeout_s": 600,
            "rag_top_k": 3,
        },
    )
    assert response.status_code == 201, response.text
    run_config = response.json()["run_config"]
    assert run_config["max_iterations"] == 4
    assert run_config["review_threshold"] == 9
    assert run_config["max_cost_cny"] == 0.35
    assert run_config["timeout_s"] == 600
    assert run_config["rag_top_k"] == 3


def test_不传时回执报的是全局默认而不是界面的三(api_env: TestClient) -> None:
    """前端那个写死的 3 就是这条用例的存在理由：不传时后端用的是全局默认。"""
    from config import get_settings

    response = api_env.post("/tasks", json={"task": "只给任务描述"})
    assert response.status_code == 201, response.text
    run_config = response.json()["run_config"]
    assert run_config["max_iterations"] == get_settings().max_iterations
    assert run_config["review_threshold"] == get_settings().review_threshold
    assert run_config["max_cost_cny"] is None, "不设限必须是 null，不是 0"
    assert run_config["timeout_s"] is None
    assert run_config["rag_top_k"] is None


def test_预算低于服务端下限的正数也拒(api_env: TestClient) -> None:
    """``0`` 会被 pydantic 挡下是好事：放行就等于"预算 0 元"，任务一步都跑不了。

    ``下限/2`` 那条才是本用例的重点：界面上的 ``min`` 与后端的 ``ge`` 必须同源
    （都读 ``RUN_CONFIG_LIMITS``）⇒ 低于下限的正数要么被界面挡住、要么在这里 422，
    不能"界面让填、后端静默按另一个数收"。
    """
    from api.schemas import RUN_CONFIG_LIMITS

    floor = float(RUN_CONFIG_LIMITS["max_cost_cny"]["min"])
    for bad in (0, -0.01, floor / 2):
        assert api_env.post("/tasks", json={"task": "坏预算", "max_cost_cny": bad}).status_code == 422


# --------------------------------------------------------------------------- #
# 预算闸门：真的掐断
# --------------------------------------------------------------------------- #
def test_预算用尽后在节点边界停住并说明原因(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上限取**服务端声明的下限**、假成本取它的两倍 ⇒ 第一个节点后必然越过。

    为什么不让魔数各写各的：把上限钉在 ``RUN_CONFIG_LIMITS`` 的下限上，
    "下限被抬到闸门来不及触发"（上限只能填更大的数，而每次调用还是几分钱 ⇒ 用例
    会一路跑到 ``done``）这类回归会直接把这条用例判红，而不是静默地测不到东西。
    """
    from api.schemas import RUN_CONFIG_LIMITS
    from tests.integration.mock_llm import MockLLMAdapter

    ceiling = float(RUN_CONFIG_LIMITS["max_cost_cny"]["min"])
    monkeypatch.setattr(MockLLMAdapter, "COST_PER_CALL", ceiling * 2)

    response = api_env.post("/tasks", json={"task": "预算很小的任务", "max_cost_cny": ceiling})
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]

    view = poll_terminal(api_env, task_id, timeout=30.0)
    assert view["status"] == "canceled", view
    error = view.get("error") or {}
    assert error.get("code") == "BUDGET_EXCEEDED", (
        "被预算掐掉必须与用户自己取消分得开：只报 canceled 而不带原因，"
        "用户看到的是「我自己取消的」，那是误导"
    )
    assert "¥" in (error.get("message") or ""), view


def test_预算宽松时同一任务正常跑完_对照组(api_env: TestClient) -> None:
    """没有这一条，上一条用例可能只是"任务本来就停" —— 看不出闸门有没有误伤。"""
    response = api_env.post("/tasks", json={"task": "预算充足的任务", "max_cost_cny": 50.0})
    assert response.status_code == 201, response.text
    view = poll_terminal(api_env, response.json()["task_id"], timeout=30.0)
    assert view["status"] == "done", view
    assert view.get("error") is None


def test_不设预算时不会因为闸门而停_负面对照(api_env: TestClient) -> None:
    """把闸门改成"一律停"，这条与上一条都会红；只测"会停"是测不出反方向的。"""
    response = api_env.post("/tasks", json={"task": "不设预算"})
    assert response.status_code == 201, response.text
    view = poll_terminal(api_env, response.json()["task_id"], timeout=30.0)
    assert view["status"] == "done", view


def test_用户取消仍然不带原因码(api_env: TestClient) -> None:
    """K3 那条纪律不能被这轮改动带跑：闸门写原因码，用户取消不写。"""
    response = api_env.post("/tasks", json={"task": "慢一点的任务：慢"})
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    assert api_env.post(f"/tasks/{task_id}/cancel").status_code in (200, 202)
    view = poll_terminal(api_env, task_id, timeout=30.0)
    assert view["status"] == "canceled", view
    assert view.get("error") is None, "用户取消不是失败，那两列保持 NULL ⇒ 视图里不该有 error"


# --------------------------------------------------------------------------- #
# 检索上限真的传到 service.search
# --------------------------------------------------------------------------- #
def _search_with(
    monkeypatch: pytest.MonkeyPatch,
    ceiling: int | None,
    model_supplied: int,
) -> int | None:
    """把假服务塞进工具，返回**真正传给 ``service.search`` 的条数**。

    假服务的 ``search`` 抛异常把调用停在"已经决定要几条"之后 —— 本用例不关心命中什么，
    只关心那个数字有没有传到检索层。工具会把任何检索异常包成
    :class:`KnowledgeSearchError`（失败字符串化纪律），所以外面吃的是它。
    """
    recorded: dict[str, int] = {}

    class _StubService:
        def search(self, _query: str, top_k: int) -> list[Any]:
            recorded["top_k"] = int(top_k)
            raise RuntimeError("停在检索调用上：本用例只关心传进去几条")

    monkeypatch.setattr(ks, "_get_service", lambda: _StubService())
    with task_top_k_scope(ceiling), pytest.raises(ks.KnowledgeSearchError):
        ks.knowledge_search("综合布线系统", model_supplied)
    return recorded.get("top_k")


def test_用户配的上限真的传到检索调用(monkeypatch: pytest.MonkeyPatch) -> None:
    """配 3 却把模型要的 20 条传给检索 ⇒ 那一栏就是个假控件。"""
    assert _search_with(monkeypatch, ceiling=3, model_supplied=20) == 3


def test_没配上限时模型要几条就给几条(monkeypatch: pytest.MonkeyPatch) -> None:
    """反方向：默认行为不能被这轮改动偷偷收紧 —— 收紧会掉召回率，且不报错。"""
    assert _search_with(monkeypatch, ceiling=None, model_supplied=12) == 12


def test_模型要得比上限少时尊重模型(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限不是"替模型决定"：把 2 硬抬到 5 是**更差的检索**（多三条低相关片段）。"""
    assert _search_with(monkeypatch, ceiling=5, model_supplied=2) == 2

