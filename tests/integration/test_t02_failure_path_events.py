"""失败路径埋点回归：节点**失败 / 被跳过**时，``task_events`` 不得失真。

背景（实测发现的三个缺陷）
------------------------------------------

当前测试套件有个致命盲区：几乎所有集成用例都用「**永远成功**」的
``MockLLMAdapter``，所以下面两条真实路径从没被测过——

1. **节点失败**：planner 首次调用就拿到 401（``LLMNotRetryableError``）；
2. **节点被跳过**：planner 失败后 ``state.status="failed"``，executor / reviewer
   被终态守卫 ``if is_terminal(state): return {}`` 短路，**根本没调用 LLM**。

生产实测（``task-cc19c7b21e2d``）只发生了 **1 次** DeepSeek 请求，却落出 3 条
``llm_call``，且同一节点的两条事件互相打脸：

* **缺陷 1**：``node`` 事件（``api/queue.py`` Q2）``status`` 硬编码 ``success``，
  而同一节点的 ``node_end``（``core/agent/base.py`` L2）是 ``failed``；
* **缺陷 2**：``llm_call``（L1）无条件落盘、未知状态兜底成 ``success``，于是给
  **没调用 LLM** 的 executor / reviewer 捏造了「成功的 LLM 调用」幻影事件；
* **缺陷 3**：``api/main.py`` 的免鉴权告警按 ``settings.api_host``（默认
  127.0.0.1）断言「仅监听 127.0.0.1」，但进程被 ``--host 0.0.0.0`` 启动时实际绑
  全网卡——文案在说谎（缺陷 3 的单元测试见 ``tests/unit/test_p1_main_auth_warning.py``）。

本文件用一个**首次 invoke_json 即抛 ``LLMNotRetryableError``** 的 stub adapter
复现 1+2，断言修复后埋点不再失真。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.constants import (
    TASK_EVT_FAILED,
    TASK_EVT_LLM_CALL,
    TASK_EVT_NODE,
    TASK_EVT_NODE_END,
    TASK_EVT_RUNNING,
)
from core.llm.adapter import LLMNotRetryableError
from tests.integration.conftest import poll_terminal
from tests.integration.mock_llm import MockLLMAdapter

#: 模拟生产 401 的异常文本（与 ``adapter._raise_if_non_retryable`` 同款）。
_AUTH_FAIL_MESSAGE = "LLM 调用失败（HTTP 401）：鉴权失败：检查 LLM_API_KEY 是否正确或已过期"


class FailingFirstCallAdapter(MockLLMAdapter):
    """第一次 ``invoke_json``（planner）即抛 ``LLMNotRetryableError``，复现生产 401。

    之后若再被调用（说明 executor / reviewer 没被终态守卫跳过 → 缺陷复现），
    ``invocations`` 会继续增长，测试据此断言「跳过的节点确实没调 LLM」。
    """

    def __init__(self) -> None:
        # 真 responder 永不被用到：第一次调用就直接抛错。
        super().__init__(lambda schema, text: None)
        self.invocations = 0

    def invoke_json(
        self,
        messages: Any,
        schema: Any,
        model: str | None = None,
        *,
        max_attempts: int = 2,
    ) -> Any:
        self.invocations += 1
        raise LLMNotRetryableError(_AUTH_FAIL_MESSAGE)


def _failing_factory(monkeypatch: pytest.MonkeyPatch, holder: dict[str, Any]) -> None:
    """把**存活队列实例**上的 runner 工厂换成「首次调用即失败」的版本。

    ``database`` 必须在 ``factory(item)`` 函数体内取 ``get_database()``（与
    ``conftest`` 同一个坑）：此刻 ``_apply_api_env`` 已注入临时库并清缓存，
    取到的才是那个临时库；模块级取会写错库。
    """
    from api.deps import get_database, get_task_queue, get_trace_store
    from api.runner import build_runner
    from config import get_settings

    adapter = FailingFirstCallAdapter()
    holder["adapter"] = adapter

    def factory(item: Any) -> Any:
        return build_runner(
            item,
            settings=get_settings(),
            trace_store=get_trace_store(),
            llm=adapter,
            database=get_database(),
        )

    queue = get_task_queue()
    monkeypatch.setattr(queue._worker, "factory", factory)  # noqa: SLF001 - 替换存活 worker 工厂


def _events(task_id: str) -> list[Any]:
    from api.deps import get_database

    return get_database().list_events(task_id, limit=200)


def test_failed_run_no_phantom_events_and_consistent_status(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ planner 401 → 任务 failed：事件不得捏造 / 不得自相矛盾（复现缺陷 1+2）。"""
    from api.deps import get_database

    holder: dict[str, Any] = {}
    _failing_factory(monkeypatch, holder)

    submitted = api_env.post("/tasks", json={"task": "请检索报销标准并总结"})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]

    final = poll_terminal(api_env, task_id)
    assert final["status"] == "failed", final
    # 缺陷 B 的生产路径：失败终态必须带真实 error_code / message（非 NULL / 非兜底文案）
    assert final["error"]["code"] == "llm_not_retryable", final["error"]
    assert "鉴权失败" in final["error"]["message"], final["error"]

    events = _events(task_id)
    types = [event.event_type for event in events]
    assert TASK_EVT_RUNNING in types, "缺 running（Q1）"
    assert TASK_EVT_FAILED in types, "缺终态 failed 事件（Q4）"

    # ---- 缺陷 2：不得为「没真正调用 LLM」的节点捏造 success 的 llm_call ----
    llm_events = [event for event in events if event.event_type == TASK_EVT_LLM_CALL]
    assert llm_events, "planner 尝试过调用，应至少有一条（failed 的）llm_call"
    assert all(event.status != "success" for event in llm_events), (
        "存在 status=success 的 llm_call —— 这是为未调用节点捏造的幻影事件（缺陷 2）"
    )
    # stub 只在 planner 那次被调用过一次；executor/reviewer 被终态守卫跳过，不该再调
    assert holder["adapter"].invocations == 1, (
        f"LLM 只应被调用 1 次（planner），实际 {holder['adapter'].invocations} 次"
    )
    for role in ("executor", "reviewer"):
        assert not [e for e in llm_events if e.role == role], f"{role} 被跳过却出现 llm_call 事件"

    # ---- 缺陷 1：同一节点的 node 与 node_end 状态必须一致 ----
    for role in ("planner", "executor", "reviewer"):
        node_events = [
            e for e in events if e.event_type == TASK_EVT_NODE and e.node == role
        ]
        end_events = [
            e for e in events if e.event_type == TASK_EVT_NODE_END and e.node == role
        ]
        if node_events and end_events:
            assert node_events[0].status == end_events[0].status, (
                f"{role} 的 node({node_events[0].status}) 与 "
                f"node_end({end_events[0].status}) 状态矛盾（缺陷 1）"
            )
    # planner 真的失败了：node 与 node_end 都必须是 failed（旧实现 node 恒 success）
    planner_node = [e for e in events if e.event_type == TASK_EVT_NODE and e.node == "planner"]
    planner_end = [e for e in events if e.event_type == TASK_EVT_NODE_END and e.node == "planner"]
    assert planner_node and planner_end, "planner 的 node / node_end 事件必须存在"
    assert planner_node[0].status == "failed", "planner 失败的 node 事件不得报 success（缺陷 1）"
    assert planner_end[0].status == "failed"

    # ---- 终态事件必须带 error_code（缺陷 B 的埋点侧） ----
    failed_events = [e for e in events if e.event_type == TASK_EVT_FAILED]
    assert failed_events and failed_events[0].error_code == "llm_not_retryable"

    # ---- 事件顺序：event_seq 严格递增（K1） ----
    seqs = [int(event.event_seq) for event in events]
    assert seqs == sorted(seqs)


def test_failed_task_row_carries_error_fields(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败任务在 ``tasks`` 表里必须落 error_code / error_message（缺陷 B，生产路径）。"""
    from api.deps import get_database

    _failing_factory(monkeypatch, {})

    submitted = api_env.post("/tasks", json={"task": "随便写点"})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]
    poll_terminal(api_env, task_id)

    record = get_database().get_task(task_id)
    assert record is not None
    assert record.status == "failed"
    assert record.error_code == "llm_not_retryable", "error_code 不得为 NULL"
    assert record.error_message, "error_message 不得为 NULL / 不得只剩兜底文案"


def test_skipped_nodes_still_emit_node_end_without_llm_call(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """被跳过的 executor / reviewer 仍落 ``node``/``node_end``，但**不落** ``llm_call``。"""
    holder: dict[str, Any] = {}
    _failing_factory(monkeypatch, holder)

    submitted = api_env.post("/tasks", json={"task": "边界场景"})
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["task_id"]
    poll_terminal(api_env, task_id)

    events = _events(task_id)
    for role in ("executor", "reviewer"):
        role_events = [e for e in events if e.role == role or e.node == role]
        assert role_events, f"{role} 作为图节点应留下 node/node_end 事件"
        assert not [e for e in role_events if e.event_type == TASK_EVT_LLM_CALL], (
            f"{role} 被终态守卫跳过，不得有 llm_call 事件"
        )


# --------------------------------------------------------------------------- #
# 缺陷 3：免鉴权告警必须反映**真实绑定 host**（lifespan 端到端）
# --------------------------------------------------------------------------- #
class _ListHandler(logging.Handler):
    """把 ``api.main`` 的日志消息收进列表。

    为什么不用 ``caplog``：``create_app()`` 会调 ``settings.setup_logging()``，其内部
    ``logging.basicConfig(force=True)`` 会**清空根 logger 上的全部 handler**（含
    pytest 的 caplog handler），于是 caplog 什么都抓不到。改为把 handler 挂在
    ``api.main`` 这个具体 logger 上，就不受 ``force=True`` 影响。
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _capture_lifespan_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, argv: list[str]) -> list[str]:
    """在指定 argv 下起一次 TestClient（跑 lifespan），返回 ``api.main`` 的日志消息。"""
    from config import reset_settings_cache
    from tests.integration.conftest import Recorder, _apply_api_env, _start_client

    _apply_api_env(monkeypatch, tmp_path)  # API_AUTH_TOKEN 被删除 → 免鉴权
    monkeypatch.setattr(sys, "argv", argv)

    # create_app() 内部 setup_logging(force=True) 会清空根 handler，必须先建 app，
    # 再把我们的 handler 挂到 api.main logger 上，然后才进入上下文（触发 lifespan）。
    client = _start_client(monkeypatch, Recorder())
    main_logger = logging.getLogger("api.main")
    handler = _ListHandler()
    main_logger.addHandler(handler)
    try:
        with client:
            pass
    finally:
        main_logger.removeHandler(handler)
        reset_settings_cache()
    return handler.messages


def test_lifespan_warns_error_when_bound_to_all_interfaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """``--host 0.0.0.0`` + 无 token → 必须打 ERROR 并点明「对所有网卡开放」，不再谎称仅监听 127.0.0.1。"""
    messages = _capture_lifespan_logs(
        monkeypatch, tmp_path, ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    )
    assert any("安全风险" in msg and "0.0.0.0" in msg for msg in messages), (
        f"0.0.0.0 且无鉴权必须打 ERROR 警示，实际日志：{messages}"
    )
    assert not any("仅监听 127.0.0.1" in msg for msg in messages), "不得再谎称仅监听 127.0.0.1"


def test_lifespan_warns_only_when_bound_to_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """``--host 127.0.0.1`` + 无 token → 仍为 WARNING（本机可达），不升级为 ERROR。"""
    messages = _capture_lifespan_logs(
        monkeypatch, tmp_path, ["uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"]
    )
    assert any("127.0.0.1" in msg and "免鉴权" in msg for msg in messages), (
        f"回环监听应打 WARNING，实际日志：{messages}"
    )
    assert not any("安全风险" in msg for msg in messages), "回环地址不该升级为 ERROR"


__all__ = ["FailingFirstCallAdapter"]