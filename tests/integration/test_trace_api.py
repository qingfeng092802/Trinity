"""P1-T03 集成测试：``GET /tasks/{task_id}/trace``（只读查询侧）。

对应 ``docs/p1_trace_events_design.md`` §9.2 的 I3/I4/I5/I9 与任务说明的验收点。

**测试自足**：不用真实编排产生事件，而是直接用 ``database.record_event(...)``
造事件、用 ``database.save_task(...)`` 造「存在但无事件」的老任务行，
用例之间互不依赖当前 DB 里有什么。

**鉴权**：``api_env`` 默认 ``API_AUTH_TOKEN`` 为空 → 全放行；401 用例单独
设 token 后重建 client（沿用 ``test_api_health.py`` 的 ``_apply_api_env`` 范式）。
"""

from __future__ import annotations

from typing import Any

import pytest

from api.constants import (
    STATUS_DONE,
    TASK_EVT_LLM_CALL,
    TASK_EVT_NODE_END,
    TASK_EVT_RUNNING,
    TASK_EVT_TOOL_CALL,
    TRACE_DEFAULT_LIMIT,
    TRACE_MAX_LIMIT,
)
from api.deps import get_database
from core.events import EventRecord
from tests.integration.conftest import TestClient

#: 响应里必须出现的全部事件业务字段（验收：字段完整）
EXPECTED_EVENT_FIELDS = {
    "event_seq",
    "step",
    "sub_step",
    "event_type",
    "role",
    "node",
    "thought",
    "tool_name",
    "arguments",
    "observation",
    "latency_ms",
    "tokens_in",
    "tokens_out",
    "cost",
    "status",
    "error_code",
    "error_message",
    "sse_seq",
    "created_at",
}


def _event(task_id: str, **overrides: Any) -> dict[str, Any]:
    """构造一条最小合法事件行（``record_event(**fields)`` 直接可用的 dict）。"""
    row: dict[str, Any] = {
        "task_id": task_id,
        "event_type": TASK_EVT_NODE_END,
        "role": "planner",
        "step": 0,
        "node": "planner",
        "thought": "拆解任务",
        "observation": "3 步",
        "status": "success",
    }
    row.update(overrides)
    return row


def _make_task_and_events(
    task_id: str, count: int, *, task_status: str = STATUS_DONE
) -> list[int]:
    """建一条任务行 + ``count`` 条事件，返回落盘后的 ``event_seq`` 列表。

    直接经 ``get_database()``（TestClient 已在 lifespan 里建好表）落库，
    与生产写入路径共用 ``record_event``。
    """
    database = get_database()
    database.save_task(
        task_id=task_id,
        task="轨迹接口测试任务",
        status=task_status,
        iterations=1,
        score=None,
        grade=None,
        final_answer="结论",
        cost=0.0,
        duration_ms=0,
        tool_calls=0,
        tool_failures=0,
    )
    seqs: list[int] = []
    for index in range(count):
        seq = database.record_event(**_event(task_id, step=index))
        assert seq is not None, "造数据失败：record_event 返回 None"
        seqs.append(int(seq))
    return seqs


# --------------------------------------------------------------------------- #
# 正常路径：字段完整 + event_seq 升序
# --------------------------------------------------------------------------- #
def test_trace_ok_fields_and_ordering(api_env: TestClient) -> None:
    """正常取事件：字段完整、``event_seq`` 升序、``events_available=true``。"""
    task_id = "task-trace-ok"
    _make_task_and_events(task_id, 3)

    response = api_env.get(f"/tasks/{task_id}/trace")
    assert response.status_code == 200
    body = response.json()

    assert body["task_id"] == task_id
    assert body["events_available"] is True
    assert body["unavailable_reason"] is None
    assert body["total"] == 3
    assert body["limit"] == TRACE_DEFAULT_LIMIT
    assert body["after_seq"] == 0
    assert body["has_more"] is False
    assert body["next_after_seq"] is None

    items = body["items"]
    assert len(items) == 3
    for item in items:
        assert EXPECTED_EVENT_FIELDS.issubset(item.keys())
        assert item["event_type"] == TASK_EVT_NODE_END
        assert item["role"] == "planner"
        assert item["node"] == "planner"
        assert item["arguments"] is None, "非工具事件 arguments 必须是 null，不是 {}"

    seqs = [item["event_seq"] for item in items]
    assert seqs == sorted(seqs), "items 必须按 event_seq 升序"
    # created_at 是北京时间 ISO-8601，带 +08:00
    assert items[0]["created_at"].endswith("+08:00")


def test_trace_tool_call_arguments_is_object(api_env: TestClient) -> None:
    """工具事件的 ``arguments`` 在响应里是**对象**（JSON 串已反序列化）。"""
    task_id = "task-trace-tool"
    database = get_database()
    database.save_task(task_id=task_id, task="工具轨迹", status=STATUS_DONE)
    record = EventRecord(
        task_id=task_id,
        event_type=TASK_EVT_TOOL_CALL,
        role="executor",
        node="executor",
        step=0,
        sub_step=1,
        tool_name="calculator",
        arguments={"expression": "1+1"},
        observation="2",
    )
    assert database.record_event(**record.to_row()) is not None

    body = api_env.get(f"/tasks/{task_id}/trace").json()
    item = body["items"][0]
    assert item["tool_name"] == "calculator"
    assert item["arguments"] == {"expression": "1+1"}, "arguments 应为对象而非 JSON 串"
    assert item["observation"] == "2"
    assert item["sub_step"] == 1


def test_trace_arguments_null_and_dirty_do_not_crash(api_env: TestClient) -> None:
    """``arguments`` 为 NULL / 脏 JSON 串的事件都不崩（脏数据降级为 null）。"""
    task_id = "task-trace-dirty"
    database = get_database()
    database.save_task(task_id=task_id, task="脏数据", status=STATUS_DONE)
    # 非工具事件：arguments 为 NULL
    assert database.record_event(**_event(task_id, step=0)) is not None
    # 脏数据：疑似 JSON 但解析失败（历史遗留）
    assert (
        database.record_event(
            **_event(
                task_id,
                step=1,
                event_type=TASK_EVT_TOOL_CALL,
                role="executor",
                node="executor",
                tool_name="broken",
                arguments="{not-json",
            )
        )
        is not None
    )

    response = api_env.get(f"/tasks/{task_id}/trace")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["arguments"] is None
    assert items[1]["arguments"] is None, "脏 JSON 降级为 null，不能 500"


# --------------------------------------------------------------------------- #
# 游标续拉 / limit 截断 / 上限
# --------------------------------------------------------------------------- #
def test_trace_after_seq_cursor(api_env: TestClient) -> None:
    """``after_seq`` 游标续拉：造 5 条，``after_seq=2`` 应返回后 3 条。"""
    task_id = "task-trace-cursor"
    seqs = _make_task_and_events(task_id, 5)

    body = api_env.get(f"/tasks/{task_id}/trace", params={"after_seq": 2}).json()
    assert body["after_seq"] == 2
    assert body["total"] == 5, "total 是任务事件总数，不受游标影响"
    assert [item["event_seq"] for item in body["items"]] == seqs[2:]


def test_trace_limit_truncation_and_has_more(api_env: TestClient) -> None:
    """``limit`` 截断 + ``has_more``/``next_after_seq`` 正确反映是否还有下一页。"""
    task_id = "task-trace-limit"
    seqs = _make_task_and_events(task_id, 5)

    page1 = api_env.get(f"/tasks/{task_id}/trace", params={"limit": 2}).json()
    assert len(page1["items"]) == 2
    assert page1["limit"] == 2
    assert page1["has_more"] is True
    assert page1["next_after_seq"] == seqs[1]

    page2 = api_env.get(
        f"/tasks/{task_id}/trace", params={"limit": 2, "after_seq": seqs[1]}
    ).json()
    assert [item["event_seq"] for item in page2["items"]] == seqs[2:4]
    assert page2["has_more"] is True
    assert page2["next_after_seq"] == seqs[3]

    page3 = api_env.get(
        f"/tasks/{task_id}/trace", params={"limit": 2, "after_seq": seqs[3]}
    ).json()
    assert [item["event_seq"] for item in page3["items"]] == seqs[4:]
    assert page3["has_more"] is False, "最后不足一页时必须 has_more=false"
    assert page3["next_after_seq"] is None


def test_trace_pagination_equals_full_fetch(api_env: TestClient) -> None:
    """游标分页拼起来与一次性拉取结果**完全一致**（含顺序）。"""
    task_id = "task-trace-replay"
    seqs = _make_task_and_events(task_id, 12)

    collected: list[int] = []
    cursor = 0
    for _ in range(20):  # 防死循环上界
        page = api_env.get(
            f"/tasks/{task_id}/trace", params={"after_seq": cursor, "limit": 5}
        ).json()
        collected.extend(item["event_seq"] for item in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_after_seq"]
    assert collected == seqs, "分页拼接结果必须与全量一致且有序"


def test_trace_limit_bounds(api_env: TestClient) -> None:
    """``limit`` 越界 → 422（项目分页约定：越界由 Pydantic 自动 422）。"""
    task_id = "task-trace-bounds"
    _make_task_and_events(task_id, 1)

    assert api_env.get(f"/tasks/{task_id}/trace", params={"limit": 0}).status_code == 422
    assert (
        api_env.get(f"/tasks/{task_id}/trace", params={"limit": TRACE_MAX_LIMIT + 1}).status_code
        == 422
    )
    assert (
        api_env.get(f"/tasks/{task_id}/trace", params={"limit": TRACE_MAX_LIMIT}).status_code
        == 200
    )
    assert api_env.get(f"/tasks/{task_id}/trace", params={"after_seq": -1}).status_code == 422


def test_trace_role_filter_and_invalid_role(api_env: TestClient) -> None:
    """``role`` 过滤生效；非法 ``role`` → 422 ``invalid_request``。"""
    task_id = "task-trace-role"
    database = get_database()
    database.save_task(task_id=task_id, task="角色过滤", status=STATUS_DONE)
    assert (
        database.record_event(**_event(task_id, role="planner", node="planner", step=0))
        is not None
    )
    assert (
        database.record_event(
            **_event(
                task_id,
                role="executor",
                node="executor",
                step=0,
                sub_step=0,
                event_type=TASK_EVT_LLM_CALL,
            )
        )
        is not None
    )

    body = api_env.get(f"/tasks/{task_id}/trace", params={"role": "executor"}).json()
    assert [item["role"] for item in body["items"]] == ["executor"]
    assert body["total"] == 1, "total 必须按 role 过滤后计数"

    bad = api_env.get(f"/tasks/{task_id}/trace", params={"role": "nobody"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_request"


# --------------------------------------------------------------------------- #
# 老任务兼容（核心验收点）+ 404
# --------------------------------------------------------------------------- #
def test_trace_legacy_task_no_events_returns_200(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★核心验收：存在但无事件的老任务 → 200 + ``events_available=false``（非 404/500）。"""
    task_id = "task-legacy-no-events"
    # 只建任务行，不造任何事件 —— 模拟 P1-A 之前的历史任务
    database = get_database()
    database.save_task(task_id=task_id, task="老任务", status=STATUS_DONE)
    assert database.count_events(task_id) == 0

    # 确认 get_task 能查到（即任务确实存在），否则本用例失去意义
    assert api_env.get(f"/tasks/{task_id}").status_code == 200

    response = api_env.get(f"/tasks/{task_id}/trace")
    assert response.status_code == 200, "存在但无事件必须 200，绝不能 404/500"
    body = response.json()
    assert body["task_id"] == task_id
    assert body["events_available"] is False
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_more"] is False
    assert body["next_after_seq"] is None
    assert isinstance(body["unavailable_reason"], str)
    assert body["unavailable_reason"], "events_available=false 必须给出人话原因"


def test_trace_missing_task_returns_404(api_env: TestClient) -> None:
    """不存在的 ``task_id`` → 404 + ``task_not_found``（不是 200）。"""
    response = api_env.get("/tasks/task-does-not-exist/trace")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_trace_empty_table_no_events_is_also_404(api_env: TestClient) -> None:
    """全新空库：任何 task_id 都查不到 → 404（老任务兼容不能退化成「一律 200」）。"""
    response = api_env.get("/tasks/task-never-submitted/trace")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


# --------------------------------------------------------------------------- #
# 鉴权（验收 I9：证明 /trace 没被豁免名单漏掉）
# --------------------------------------------------------------------------- #
def test_trace_requires_bearer_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """开 ``API_AUTH_TOKEN`` 后：无 Bearer → 401；带正确 Bearer → 200。"""
    from tests.integration.conftest import Recorder, _apply_api_env, _start_client

    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_TOKEN", "trace-secret-123")
    try:
        with _start_client(monkeypatch, Recorder()) as client:
            task_id = "task-trace-auth"
            # 带 token 先造数据（写库与鉴权无关，这里只为下面 200 断言有数据）
            database = get_database()
            database.save_task(task_id=task_id, task="鉴权", status=STATUS_DONE)
            assert database.record_event(**_event(task_id)) is not None

            # 无 token → 401
            response = client.get(f"/tasks/{task_id}/trace")
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "unauthorized"
            assert response.headers.get("www-authenticate") == "Bearer"

            # 错误 token → 401
            assert (
                client.get(
                    f"/tasks/{task_id}/trace",
                    headers={"Authorization": "Bearer wrong"},
                ).status_code
                == 401
            )

            # 正确 token → 200
            ok = client.get(
                f"/tasks/{task_id}/trace",
                headers={"Authorization": "Bearer trace-secret-123"},
            )
            assert ok.status_code == 200
            assert ok.json()["events_available"] is True
    finally:
        from config import reset_settings_cache

        reset_settings_cache()


def test_trace_exempt_prefixes_untouched(api_env: TestClient) -> None:
    """回归：``/tasks/{id}/trace`` **不在**鉴权豁免名单里（边界不可被放宽）。"""
    from api.constants import AUTH_EXEMPT_PATHS, AUTH_EXEMPT_PREFIXES, is_auth_exempt

    path = "/tasks/task-abc/trace"
    assert path not in AUTH_EXEMPT_PATHS
    assert not path.startswith(AUTH_EXEMPT_PREFIXES)
    assert is_auth_exempt(path) is False


# --------------------------------------------------------------------------- #
# 真编排 → 事件落盘（T02 埋点端到端：证明 worker 真的写了 task_events）
# --------------------------------------------------------------------------- #
def test_trace_real_run_persists_events(api_env: TestClient) -> None:
    """★ 端到端：跑一条真任务（Mock LLM），``/trace`` 必须能查到**编排产生**的事件。

    本用例是「埋点确实落盘」的回归哨兵——此前 ``conftest`` 的录制工厂没给
    ``build_runner`` 传 ``database``，导致节点埋点被静默跳过、``/trace`` 永远
    返回空数组；本用例把它钉死。

    断言：``events_available=true``、``total > 0``、事件里同时存在
    ``running``（任务开跑）、``llm_call``（LLM 计量）、``node_end``（节点内结束）、
    ``node``（编排层同源快照）与终态 ``done``，且 ``event_seq`` 严格递增。
    """
    from api.constants import (
        TASK_EVT_DONE,
        TASK_EVT_LLM_CALL,
        TASK_EVT_NODE,
        TASK_EVT_NODE_END,
    )
    from tests.integration.conftest import poll_terminal

    submitted = api_env.post("/tasks", json={"task": "写一句关于春天的诗"})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]

    view = poll_terminal(api_env, task_id)
    assert view["status"] == "done"

    response = api_env.get(f"/tasks/{task_id}/trace")
    assert response.status_code == 200
    body = response.json()
    assert body["events_available"] is True, "真任务必须有事件落盘（埋点未生效）"
    assert body["total"] > 0, "真任务的事件条数必须 > 0"

    items = body["items"]
    event_types = [item["event_type"] for item in items]
    assert TASK_EVT_RUNNING in event_types, "缺 running 事件（Q1 未落盘）"
    assert TASK_EVT_LLM_CALL in event_types, "缺 llm_call 事件（L1 未落盘）"
    assert TASK_EVT_NODE_END in event_types, "缺 node_end 事件（L2 未落盘）"
    assert TASK_EVT_NODE in event_types, "缺 node 事件（Q2 未落盘）"
    assert TASK_EVT_DONE in event_types, "缺终态 done 事件（Q3 未落盘）"

    # llm_call 事件必须带计量（tokens/cost 来自 adapter.last_usage）
    llm_events = [item for item in items if item["event_type"] == TASK_EVT_LLM_CALL]
    assert any(
        item["tokens_in"] > 0 or item["cost"] > 0 for item in llm_events
    ), "llm_call 事件必须带上 tokens/cost 计量"

    seqs = [item["event_seq"] for item in items]
    assert seqs == sorted(seqs), "事件必须按 event_seq 升序（禁止依赖 timestamp，K1）"


__all__ = [
    "EXPECTED_EVENT_FIELDS",
    "TASK_EVT_RUNNING",
]
