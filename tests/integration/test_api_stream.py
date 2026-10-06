"""SSE 流式端点：事件序列、终态即关、无 ``messages`` 键、404。"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from tests.integration.conftest import TestClient, poll_terminal


def _submit(client: TestClient, task: str) -> dict[str, Any]:
    response = client.post("/tasks", json={"task": task})
    assert response.status_code == 201, response.text
    return response.json()


def _collect_stream(
    client: TestClient,
    task_id: str,
    max_seconds: float = 15.0,
    path: str = "/tasks/{task_id}/stream",
) -> list[tuple[str, dict[str, Any]]]:
    """读完整条 SSE 流直到服务端关闭，返回 ``(事件名, data)`` 列表。

    ``path`` 可切换 ``/stream`` 与它的别名 ``/events``（两者共用同一生成器）。
    """
    events: list[tuple[str, dict[str, Any]]] = []
    with client.stream("GET", path.format(task_id=task_id), timeout=max_seconds) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        event_name = ""
        data_lines: list[str] = []
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
            elif not line and event_name:
                try:
                    data = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    data = {}
                events.append((event_name, data))
                event_name = ""
                data_lines = []
    return events


def test_stream_full_sequence(api_env: TestClient) -> None:
    """从头订阅：snapshot → node×N → done，事件顺序与数据形态正确（验收 P0-6.1）。"""
    body = _submit(api_env, "流式观察任务")
    events = _collect_stream(api_env, body["task_id"])

    names = [name for name, _data in events]
    assert names[0] == "snapshot"
    assert names[-1] == "done"
    node_events = [data for name, data in events if name == "node"]
    assert len(node_events) >= 2  # planner + reviewer（至少两个节点增量）

    # snapshot 携带任务与状态信息
    assert events[0][1]["task_id"] == body["task_id"]
    assert events[0][1]["status"] in {"queued", "running"}

    # node 事件的 update 不含 messages（验收 P0-6.4）
    for data in node_events:
        assert "messages" not in data["update"]
        assert data["node"] in {"planner", "executor", "reviewer"}

    # done 事件是终态任务视图
    done_data = events[-1][1]
    assert done_data["status"] == "done"
    assert done_data["final_answer"].strip() != ""
    assert "cost" in done_data and "duration_ms" in done_data


def test_stream_missing_task_returns_404_json(api_env: TestClient) -> None:
    """建流之前就要 404，且响应体是 JSON 而不是流（验收 P0-6.5）。"""
    response = api_env.get("/tasks/task-doesnotexist00/stream")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_stream_terminal_task_closes_immediately(api_env: TestClient) -> None:
    """对已终态任务建流：snapshot + 终态事件后服务端主动关闭（验收 P0-6.3）。"""
    body = _submit(api_env, "先跑完再订阅的任务")
    poll_terminal(api_env, body["task_id"])

    start = time.time()
    events = _collect_stream(api_env, body["task_id"])
    elapsed = time.time() - start

    names = [name for name, _data in events]
    assert names == ["snapshot", "done"]
    assert elapsed < 3.0, f"终态任务的流应在 1s 内关闭，实际 {elapsed:.2f}s"


def test_stream_heartbeat_while_node_in_progress(api_env: TestClient) -> None:
    """节点执行期间（无 node 事件）心跳按间隔补位（验收 P0-6.2）。"""
    body = _submit(api_env, "慢任务：planner 调用要 0.6s，期间只会有心跳")
    task_id = body["task_id"]

    heartbeats = 0
    with api_env.stream("GET", f"/tasks/{task_id}/stream", timeout=10) as response:
        event_name = ""
        for _line in response.iter_lines():
            if _line.startswith("event:"):
                event_name = _line.split(":", 1)[1].strip()
                if event_name == "heartbeat":
                    heartbeats += 1
                elif event_name in {"done", "failed"}:
                    break
    assert heartbeats >= 2, f"预期至少 2 次心跳，实际 {heartbeats}"


def test_client_disconnect_does_not_kill_task(api_env: TestClient) -> None:
    """断开 SSE 后任务继续执行并落终态（验收 P0-6 规则 5）。"""
    body = _submit(api_env, "断线观察任务")
    task_id = body["task_id"]

    # 建流后立刻断开（只读两行）
    with api_env.stream("GET", f"/tasks/{task_id}/stream", timeout=5) as response:
        for index, _line in enumerate(response.iter_lines()):
            if index >= 2:
                break

    final = poll_terminal(api_env, task_id)
    assert final["status"] == "done"


# --------------------------------------------------------------------------- #
# GET /tasks/{id}/events —— /stream 的别名
# --------------------------------------------------------------------------- #
#: 别名路由（前端 EventSource 命名习惯用 /events，主路径仍是 /stream）
_EVENTS_PATH = "/tasks/{task_id}/events"


def test_events_alias_returns_same_sequence_as_stream(api_env: TestClient) -> None:
    """/events 与 /stream 产出**同一套**事件序列（共用生成器，不复制实现）。"""
    body = _submit(api_env, "别名路由一致性任务")
    events = _collect_stream(api_env, body["task_id"], path=_EVENTS_PATH)

    names = [name for name, _data in events]
    assert names[0] == "snapshot"
    assert names[-1] == "done"
    node_events = [data for name, data in events if name == "node"]
    assert len(node_events) >= 2, "至少 planner + reviewer 两个节点增量"
    for data in node_events:
        assert data["node"] in {"planner", "executor", "reviewer"}


def test_events_alias_404_matches_stream(api_env: TestClient) -> None:
    """别名同样在建流**之前** 404，响应体是 JSON（与 /stream 一致）。"""
    response = api_env.get("/tasks/task-doesnotexist00/events")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_events_alias_terminal_task_closes_immediately(api_env: TestClient) -> None:
    """别名对已终态任务：snapshot + 终态事件后立刻关流（不挂起）。"""
    body = _submit(api_env, "别名终态任务")
    poll_terminal(api_env, body["task_id"])

    start = time.time()
    events = _collect_stream(api_env, body["task_id"], path=_EVENTS_PATH)
    elapsed = time.time() - start

    assert [name for name, _data in events] == ["snapshot", "done"]
    assert elapsed < 3.0, f"终态任务的流应在 1s 内关闭，实际 {elapsed:.2f}s"


# --------------------------------------------------------------------------- #
# GET /tasks/{id}/events —— /stream 的别名
# --------------------------------------------------------------------------- #
#: 别名路由（前端 EventSource 命名习惯用 /events，主路径仍是 /stream）
_EVENTS_PATH = "/tasks/{task_id}/events"


def test_events_alias_returns_same_sequence_as_stream(api_env: TestClient) -> None:
    """/events 与 /stream 产出**同一套**事件序列（共用生成器，不复制实现）。"""
    body = _submit(api_env, "别名路由一致性任务")
    events = _collect_stream(api_env, body["task_id"], path=_EVENTS_PATH)

    names = [name for name, _data in events]
    assert names[0] == "snapshot"
    assert names[-1] == "done"
    node_events = [data for name, data in events if name == "node"]
    assert len(node_events) >= 2, "至少 planner + reviewer 两个节点增量"
    for data in node_events:
        assert data["node"] in {"planner", "executor", "reviewer"}


def test_events_alias_404_matches_stream(api_env: TestClient) -> None:
    """别名同样在建流**之前** 404，响应体是 JSON（与 /stream 一致）。"""
    response = api_env.get("/tasks/task-doesnotexist00/events")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_events_alias_terminal_task_closes_immediately(api_env: TestClient) -> None:
    """别名对已终态任务：snapshot + 终态事件后立刻关流（不挂起）。"""
    body = _submit(api_env, "别名终态任务")
    poll_terminal(api_env, body["task_id"])

    start = time.time()
    events = _collect_stream(api_env, body["task_id"], path=_EVENTS_PATH)
    elapsed = time.time() - start

    assert [name for name, _data in events] == ["snapshot", "done"]
    assert elapsed < 3.0, f"终态任务的流应在 1s 内关闭，实际 {elapsed:.2f}s"


# --------------------------------------------------------------------------- #
# 帧的 ``id:`` —— 只有一个发号者（Q6-10，2026-10-02）
# --------------------------------------------------------------------------- #
#: 本节的判据形状：worker 产出的每一帧都从同一个 ``seq_box`` 取号，连接本地的
#: 合成帧（首屏 ``snapshot``、``heartbeat``、终态补帧）**不带** ``id:``。
#: 改前是三套号（worker 循环 / ``_build_streams`` 的 ``state["seq"]`` /
#: ``generate()`` 的本地 ``seq``），同一根连接上必然出现 ``id:`` 重复且倒退。


def _collect_frames(
    client: TestClient,
    task_id: str,
    path: str = "/tasks/{task_id}/stream",
) -> list[tuple[str, int | None, dict[str, Any]]]:
    """读完整条流，返回 ``(事件名, ``id:`` 或 None, data)``。

    与 :func:`_collect_stream` 分开写：那个helper 只关心事件名与载荷，这里唯一
    要量的就是 ``id:`` 这一行在不在、值多少。
    """
    frames: list[tuple[str, int | None, dict[str, Any]]] = []
    event_name = ""
    data_lines: list[str] = []
    frame_id: int | None = None
    with client.stream("GET", path.format(task_id=task_id), timeout=15.0) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("id:"):
                frame_id = int(line.split(":", 1)[1])
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
            elif not line and event_name:
                try:
                    data = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    data = {}
                frames.append((event_name, frame_id, data))
                event_name, data_lines, frame_id = "", [], None
    return frames


def _delta_emitting_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """把存活队列的 runner 工厂换成"会在 executor 步里发 delta/usage"的版本。

    为什么必须自己造增量：默认 Mock 通路**一帧 ``delta`` 都不发**（``client.ts``
    那边靠它做打字机，测试通路上是空的）。不造出来，本节第一条判据就退化成
    "只有 node 帧在比号" —— 那三套号里被改掉的那一套根本没参与，用例恒真。
    """
    from api.deps import get_database, get_task_queue, get_trace_store
    from api.runner import build_runner
    from config import get_settings
    from core.agent.planner import PLAN_SCHEMA
    from core.events import get_task_streams
    from core.workflow.state import ExecutorDecision, ReviewVerdict
    from tests.integration.conftest import SLOW_CALL_SLEEP
    from tests.integration.mock_llm import MockLLMAdapter

    def responder(schema: Any, _text: str) -> Any:
        if schema is PLAN_SCHEMA:
            time.sleep(SLOW_CALL_SLEEP)  # 给客户端留出订阅时间
            return ["收集事实", "形成结论"]
        if schema is ExecutorDecision:
            streams = get_task_streams()
            assert streams is not None and streams.answer is not None, (
                "worker 没把实时出口绑到本线程（contextvar 纪律被改了？）"
            )
            assert streams.usage is not None, "worker 没绑 usage 出口"
            streams.answer.mark("executor")
            streams.answer.emit("草稿第一段")
            streams.answer.emit("草稿第二段")
            streams.answer.flush()  # 合批窗口(80ms)里的尾巴必须冲出来
            streams.usage({"model": "mock", "tokens_in": 10, "tokens_out": 4, "cost": 0.0001})
            return {"thought": "直接给结论", "tool_name": None, "tool_args": {}, "answer": "本步结论"}
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


def test_worker_frames_have_one_increasing_id_sequence(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 同一根连接上，worker 产出的帧 ``id:`` 严格递增且**不重复**（含 delta/usage）。"""
    _delta_emitting_factory(monkeypatch)

    body = _submit(api_env, "慢任务：观察 delta 与 node 交错时的 id")
    frames = _collect_frames(api_env, body["task_id"])
    names = [name for name, _i, _d in frames]

    # 正对照：本用例真的观察到了两套号交错，否则判据是恒真的
    assert "delta" in names and "usage" in names, f"没抓到 delta/usage 帧：{names}"

    ids = [frame_id for _n, frame_id, _d in frames if frame_id is not None]
    assert ids, "worker 帧应当全部带 id"
    wire = [(name, frame_id) for name, frame_id, _d in frames]
    assert ids == sorted(set(ids)), f"id: 必须严格递增且不重复，实际 {wire}"

    # ★ 这条才是"两套号"的直接判据：改前 ``delta`` 用 ``state["seq"]`` **从 1 重新数**，
    #   于是第一帧 delta 的 id 不可能大于它前面那些 worker 帧（running 快照 / node）
    #   已经用掉的号。现在两条流共用 ``seq_box`` ⇒ delta 一定接在最后那个号之后。
    first_delta = names.index("delta")
    before = [frame_id for _n, frame_id, _d in frames[:first_delta] if frame_id is not None]
    assert before, "delta 之前应已有带 id 的 worker 帧（running 快照）"
    assert frames[first_delta][1] > max(before), (
        f"delta 的 id 必须接在既有 worker 号之后，实际 {wire}"
    )


def test_connection_local_frames_carry_no_id(api_env: TestClient) -> None:
    """连接本地的合成帧不带 ``id:``：首屏 ``snapshot`` 与终态补帧都不该推进重连游标。"""
    body = _submit(api_env, "终态合成帧任务")
    poll_terminal(api_env, body["task_id"])

    frames = _collect_frames(api_env, body["task_id"])
    assert [name for name, _i, _d in frames] == ["snapshot", "done"], frames
    assert all(frame_id is None for _n, frame_id, _d in frames), (
        f"合成帧不该有 id:，实际 {frames}"
    )


def test_format_frame_omits_id_line_when_seq_is_none() -> None:
    """:func:`format_frame` 在 ``seq=None`` 时整行省略 ``id:``（不是发 ``id: None``）。"""
    from api.events import StreamEvent, format_frame

    with_id = format_frame(StreamEvent(task_id="t", name="node", seq=7, data={"a": 1}))
    without_id = format_frame(StreamEvent(task_id="t", name="heartbeat", seq=None, data={"a": 1}))

    assert with_id.startswith("id: 7\n")
    assert without_id.startswith("event: heartbeat\n")
    assert "id:" not in without_id
