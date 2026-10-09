"""M1 API 集成测试夹具：临时库 + Mock LLM 工厂 + TestClient。

核心思路（设计文档 §5 T05）：

* **零真实 token**：把 ``default_runner_factory`` 换成「每任务注入
  :class:`MockLLMAdapter`」的录制工厂，走 ``api.runner.build_runner`` 的真实
  装配路径，只把最后一跳换成查表；
* **录制器**：记录每个任务的 LLM 调用次数与首次调用顺序——并发上限、FIFO、
  取消语义这三组验收全靠它做断言；
* **慢任务**：任务文本含「慢」时 planner 调用前睡 0.6s，让排队 / 取消的
  时序窗口足够大，避免竞态导致的偶发失败；
* **夹具退出必须** ``queue.stop()``（由 ``TestClient`` 的 lifespan 退出触发），
  否则线程池泄漏到下一个测试。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.runner import build_runner
from config import reset_settings_cache
from core.agent.planner import PLAN_SCHEMA
from core.workflow.state import ExecutorDecision, ReviewVerdict
from tests.integration.mock_llm import MockLLMAdapter

#: 慢任务每次 LLM 调用前的停顿（秒）——5 次调用 ≈ 3s，足够覆盖排队 / 取消窗口
SLOW_CALL_SLEEP = 0.6


class Recorder:
    """按任务记录 LLM 调用情况（线程安全靠 GIL 的原子 dict/list 操作即可）。"""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.first_call_order: list[str] = []

    def record(self, task_id: str) -> None:
        self.calls[task_id] = self.calls.get(task_id, 0) + 1
        if task_id not in self.first_call_order:
            self.first_call_order.append(task_id)

    def calls_of(self, task_id: str) -> int:
        return self.calls.get(task_id, 0)


def _make_recording_factory(
    recorder: Recorder,
) -> Callable[[Any], Any]:
    """构造带录制与慢任务支持的 runner 工厂（替换 ``default_runner_factory``）。"""

    def factory(item: Any) -> Any:
        task_text = item.task

        def responder(schema: Any, _text: str) -> Any:
            recorder.record(item.task_id)
            if "慢" in task_text:
                time.sleep(SLOW_CALL_SLEEP)
            if schema is PLAN_SCHEMA:
                return ["收集事实", "形成结论"]
            if schema is ExecutorDecision:
                return {"thought": "直接给结论", "tool_name": None, "tool_args": {}, "answer": "本步结论"}
            if schema is ReviewVerdict:
                return {
                    "pass": True,
                    "score": 9,
                    "comment": "结构完整，可直接交付",
                    "final_answer": "这是 Mock 生成的最终答案。",
                }
            raise AssertionError(f"未预期的 schema：{schema}")

        from config import get_settings
        from api.deps import get_database, get_trace_store

        # database=get_database() 必须在**函数体内**取：_apply_api_env 已把 DB_URL
        # 指向临时库并 reset_api_caches()，此刻单例才是那个临时库；若在模块级 /
        # import 期取，会拿到旧单例或生产库，事件就写错库、/trace 永远查不到。
        # 传入后 build_runner 会注入 DatabaseEventSink，节点在返回前把
        # llm_call / node_end / tool_call 事件落 task_events（T02 埋点）。
        return build_runner(
            item,
            settings=get_settings(),
            trace_store=get_trace_store(),
            llm=MockLLMAdapter(responder),
            database=get_database(),
        )

    return factory


def _apply_api_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    max_concurrent: int = 2,
    queue_size: int = 20,
    heartbeat: float = 0.1,
) -> None:
    """统一的环境注入：临时库 + 不可达 Redis（强制内存降级）+ 可调队列参数。"""
    monkeypatch.setenv("DB_URL", f"sqlite:///{(tmp_path / 'api_test.db').as_posix()}")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:59999/0")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("API_MAX_CONCURRENT_TASKS", str(max_concurrent))
    monkeypatch.setenv("API_QUEUE_MAX_SIZE", str(queue_size))
    monkeypatch.setenv("API_SSE_HEARTBEAT_SECONDS", str(heartbeat))
    monkeypatch.delenv("ENABLE_HITL", raising=False)
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("API_ALLOW_HIGH_RISK_OVERRIDE", raising=False)
    monkeypatch.delenv("API_BLOCK_PEAK_TASKS", raising=False)


def _start_client(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> TestClient:
    """重置全部单例缓存 → 替换 runner 工厂 → 起 TestClient（lifespan 内建队列）。"""
    from api.deps import reset_api_caches
    from config import get_settings

    reset_settings_cache()
    reset_api_caches()

    # get_runner_factory 内部引用的是 **api.deps 命名空间**里的
    # default_runner_factory（from-import 把函数对象绑进了 deps），
    # 所以必须 patch deps 侧的绑定，patch api.runner 侧不生效。
    import api.deps as deps_mod

    monkeypatch.setattr(
        deps_mod, "default_runner_factory", lambda _s, _t: _make_recording_factory(recorder)
    )
    # get_runner_factory 是 lru_cache 单例，必须清掉再重建，否则拿到旧工厂
    deps_mod.get_runner_factory.cache_clear()
    assert get_settings().api_max_concurrent_tasks >= 1

    # ★ 判定桩（2026-10-03 挂 R-75）：全量 `pytest tests` 里出现过
    #   ``sqlite3.OperationalError: table tasks already exists``（抛点在
    #   `storage/db.py` 的 ``Base.metadata.create_all(engine)``），子代理 2/2 撞上、
    #   我 3/3 没撞上 ⇒ 现象真、根因不明。两种可能要靠这一行分开：
    #   ① 缓存没清干净，engine 指向**共享的生产库**（`data/trinity.db` 里
    #      `tasks` 表本来就在，①就是这么来的）；② URL 是对的，是同路径两个连接
    #      在 checkfirst 与 CREATE 之间抢跑。断言成立 ⇒ ①被排除，下次再撞那条
    #      ERROR 就只管查②，不必再怀疑 ``reset_settings_cache / reset_api_caches`` 的顺序。
    #   用 `Database()` 而不是 `get_database()`：前者只建 engine 对象（SQLAlchemy 是
    #   惰性的，不连库、不建表），所以 create_all 仍留在 lifespan 里发生，
    #   **这条断言不改变原来的时序**，只是在错的时候多打一句真因。
    #   ⚠️ 批 3 报告 Q8-02 给的默认方案写的是断言 `engine.url == settings.db_url`，
    #   那条在本仓**恒真**（`Database.__init__` 正是拿 `settings.resolved_db_url` 造
    #   engine，等于自己跟自己比），所以这里比的是"URL 的 basename 是不是本次
    #   tmp_path 那枚 `api_test.db`" —— 只有它能把①和②分开。负对照已做：把期望值
    #   换成别的串，`test_trace_api.py` 立刻成片 fixture setup ERROR 并在消息里
    #   打出真实 URL ⇒ 这条断言不是死的。
    from storage.db import Database

    probe = Database()
    try:
        db_url = str(probe.engine.url)
    finally:
        probe.engine.dispose()
    assert db_url.rsplit("/", 1)[-1] == "api_test.db", (
        f"夹具的库不是本次 tmp_path 的临时库 —— 建表 ERROR 的真因是 URL 而不是竞态：{db_url}"
    )

    app = create_app()
    return TestClient(app)


@pytest.fixture()
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """默认档位：并发 2、队列 20、心跳 0.1s。用完由 lifespan 负责停队列。"""
    _apply_api_env(monkeypatch, tmp_path)
    recorder = Recorder()
    # TestClient 必须进上下文，lifespan（含 queue.start()）才会执行
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]  # 测试通过它读录制数据
        yield client
    reset_settings_cache()


@pytest.fixture()
def tiny_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """极小档位：并发 1、队列 1——专测 429 与排队语义。"""
    _apply_api_env(monkeypatch, tmp_path, max_concurrent=1, queue_size=1)
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client
    reset_settings_cache()


@pytest.fixture()
def serial_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """串行档位：并发 1、队列 10——专测 FIFO 顺序（队列够大不会 429）。"""
    _apply_api_env(monkeypatch, tmp_path, max_concurrent=1, queue_size=10)
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client
    reset_settings_cache()


@pytest.fixture()
def hitl_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """HITL 开启档位：验证高危工具 fail-closed。"""
    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENABLE_HITL", "true")
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client
    reset_settings_cache()


@pytest.fixture()
def override_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """HITL 开启 **且**服务端允许 override：决策表最后一行（放行 + 记 WARNING 审计）。

    只有这一档能把高危工具真的跑起来 —— 它是"门禁有钥匙"的证据。
    ``api_env``（``ENABLE_HITL`` 未设）从 2026-09-26 起**也**要两把钥匙：
    那条改动把"关掉审批流"从"关掉门禁"改回成"没人能批 ⇒ 拒绝"。
    """
    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENABLE_HITL", "true")
    monkeypatch.setenv("API_ALLOW_HIGH_RISK_OVERRIDE", "true")
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client
    reset_settings_cache()


def poll_terminal(client: TestClient, task_id: str, timeout: float = 20.0) -> dict[str, Any]:
    """轮询到终态（done/failed/aborted/canceled）并返回最终 TaskView。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/tasks/{task_id}").json()
        if body["status"] in {"done", "failed", "aborted", "canceled"}:
            return body
        time.sleep(0.1)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内未进入终态：{body['status']}")


def wait_running(client: TestClient, task_id: str, timeout: float = 10.0) -> None:
    """轮询到 running / 终态（终态说明太快没观察到 running，也算就绪）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/tasks/{task_id}").json()
        if body["status"] in {"running", "done", "failed", "aborted", "canceled"}:
            return
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内未开始运行")


def recorder_of(client: TestClient) -> Recorder:
    """从 client 上取回录制器。"""
    return client._m1_recorder  # type: ignore[attr-defined]


__all__ = [
    "Recorder",
    "api_env",
    "hitl_env",
    "poll_terminal",
    "recorder_of",
    "serial_env",
    "tiny_env",
    "wait_running",
]
