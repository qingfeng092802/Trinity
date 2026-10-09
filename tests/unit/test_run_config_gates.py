"""运行期闸门与 RAG 上限的单元测试（不起 HTTP、不碰网络）。

覆盖三处"错了不会崩、只会算错或说错话"的逻辑：

* :meth:`api.queue.TaskWorker._limit_trip` —— 超时 / 预算的判定与边界；
* :meth:`api.queue.TaskWorker._stop_by_limit` —— 中断走的是**取消**那条既有路径，
  且 CAS 抢不到时不许再发事件（否则会给一条已有结局的任务盖第二个终态）；
* :func:`core.tools.task_context.clamp_top_k` —— 用户配的是**上限**，
  模型要得更少时尊重模型（反向实现是"用户配 5 就硬要 5 条"，那是变差的检索）。

进度快照的 ``iteration``（U-9）也在这儿：那一行以前写死 0，
而 ``max_iterations`` 是真的 ⇒ 两个读数并排着自相矛盾。
"""

from __future__ import annotations

from typing import Any

import pytest

from api.queue import CancelToken, QueueItem, TaskWorker
from core.tools.task_context import (
    clamp_top_k,
    reset_task_top_k,
    set_task_top_k,
    task_top_k,
    task_top_k_scope,
)

# --------------------------------------------------------------------------- #
# 桩：只实现被测代码真正会碰的那几个方法
# --------------------------------------------------------------------------- #
class StubDatabase:
    """记录调用、按脚本返回花费与 CAS 结果的假 DB。"""

    def __init__(self, *, spent: float = 0.0, cas_ok: bool = True) -> None:
        self.spent = spent
        self.cas_ok = cas_ok
        self.sum_calls = 0
        self.canceled_with: tuple[str | None, str | None] | None = None
        self.events: list[dict[str, Any]] = []

    def sum_llm_cost(self, task_id: str) -> float:  # noqa: ARG002 - 签名对齐真 DB
        self.sum_calls += 1
        return self.spent

    def mark_canceled(
        self, task_id: str, *, error_code: str | None = None, error_message: str | None = None
    ) -> bool:  # noqa: ARG002
        self.canceled_with = (error_code, error_message)
        return self.cas_ok

    def record_event(self, **fields: Any) -> int:
        self.events.append(fields)
        return len(self.events)


class StubBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, event: Any) -> None:
        self.published.append(event)


def _worker(db: StubDatabase) -> tuple[TaskWorker, StubBus]:
    bus = StubBus()
    worker = TaskWorker(
        database=db,  # type: ignore[arg-type] - 桩只需要被测代码碰到的那几个方法
        cache=None,  # type: ignore[arg-type] - 本组用例不进 finally 那条路径
        trace_store=None,  # type: ignore[arg-type]
        event_bus=bus,  # type: ignore[arg-type]
        runner_factory=lambda _item: None,
    )
    return worker, bus


def _item(**overrides: Any) -> QueueItem:
    base: dict[str, Any] = {
        "task_id": "task-gate000001",
        "task": "闸门用例",
        "max_iterations": 3,
        "review_threshold": 7,
        "use_tools": True,
        "run_judge": False,
        "difficulty": None,
        "submitted_at": 0.0,
        "cancel": CancelToken(task_id="task-gate000001"),
    }
    base.update(overrides)
    return QueueItem(**base)


# --------------------------------------------------------------------------- #
# 超时闸门
# --------------------------------------------------------------------------- #
def test_没设超时就不判时间() -> None:
    worker, _ = _worker(StubDatabase())
    assert worker._limit_trip(_item(), elapsed_ms=10**9) is None


def test_超时到点即触发且消息说得出实际运行时长() -> None:
    worker, _ = _worker(StubDatabase())
    trip = worker._limit_trip(_item(timeout_s=30), elapsed_ms=30_000)
    assert trip is not None
    code, message = trip
    assert code == "TIMEOUT_EXCEEDED"
    assert "30.0 秒" in message and "30 秒" in message


def test_超时差一毫秒不触发() -> None:
    worker, _ = _worker(StubDatabase())
    assert worker._limit_trip(_item(timeout_s=30), elapsed_ms=29_999) is None


def test_超时那一判不碰数据库() -> None:
    """便宜的先做：时间判定不该为了一条已经超时的事件再去查一次事件表。"""
    db = StubDatabase(spent=0.0)
    worker, _ = _worker(db)
    assert worker._limit_trip(_item(timeout_s=10, max_cost_cny=99.0), elapsed_ms=60_000)
    assert db.sum_calls == 0, "超时先触发时不应再去读成本"


# --------------------------------------------------------------------------- #
# 预算闸门
# --------------------------------------------------------------------------- #
def test_预算恰好等于上限就中断() -> None:
    """``>=`` 是刻意的：到边界时钱已经花完了，再跑一个节点必然超出。"""
    db = StubDatabase(spent=0.36)
    worker, _ = _worker(db)
    trip = worker._limit_trip(_item(max_cost_cny=0.36), elapsed_ms=1_000)
    assert trip is not None
    code, message = trip
    assert code == "BUDGET_EXCEEDED"
    assert "¥0.3600" in message


def test_预算差一分不中断() -> None:
    db = StubDatabase(spent=0.35)
    worker, _ = _worker(db)
    assert worker._limit_trip(_item(max_cost_cny=0.36), elapsed_ms=1_000) is None


def test_没设预算就不查事件表() -> None:
    """负面对照的另一半：不设限的任务不该为闸门多付一次 SQL。"""
    db = StubDatabase(spent=99.0)
    worker, _ = _worker(db)
    assert worker._limit_trip(_item(), elapsed_ms=1_000) is None
    assert db.sum_calls == 0


# --------------------------------------------------------------------------- #
# 中断走的是"现成的取消路径"
# --------------------------------------------------------------------------- #
def test_闸门中断落取消终态并带上原因码() -> None:
    db = StubDatabase(spent=1.0)
    worker, bus = _worker(db)
    item = _item(max_cost_cny=0.5)
    worker._stop_by_limit(item, ("BUDGET_EXCEEDED", "已花 ¥1.0000"), step=2, seq=7)

    assert item.cancel.is_canceled() is True, "要置事件位，让其它观察者一起停"
    assert db.canceled_with is not None and db.canceled_with[0] == "BUDGET_EXCEEDED"
    assert db.canceled_with[1] == "已花 ¥1.0000"
    assert len(db.events) == 1 and db.events[0]["event_type"] == "canceled"
    assert db.events[0]["error_code"] == "BUDGET_EXCEEDED"
    assert len(bus.published) == 1, "先落盘再广播"
    assert bus.published[0].data["reason"] == "BUDGET_EXCEEDED"


def test_CAS_抢不到时不发事件也不广播() -> None:
    """任务已有自己的结局时，闸门只能闭嘴 —— 否则一条任务出现两个终态。"""
    db = StubDatabase(cas_ok=False)
    worker, bus = _worker(db)
    worker._stop_by_limit(_item(), ("TIMEOUT_EXCEEDED", "超时"), step=1, seq=3)
    assert db.events == []
    assert bus.published == []


# --------------------------------------------------------------------------- #
# 进度快照的轮次（U-9）
# --------------------------------------------------------------------------- #
def test_进度快照报真实轮次而不是写死的零() -> None:
    worker, _ = _worker(StubDatabase())
    payload = worker._progress_payload(
        _item(max_iterations=5), "executor", ["planner", "executor"], 1234, iteration=3
    )
    assert payload["iteration"] == 3
    assert payload["max_iterations"] == 5, "两个读数必须同一口径，否则页面自相矛盾"


def test_开跑前那一帧确实是零() -> None:
    worker, _ = _worker(StubDatabase())
    payload = worker._progress_payload(_item(), None, [], 0)
    assert payload["iteration"] == 0


# --------------------------------------------------------------------------- #
# RAG 上限
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("model_supplied", "ceiling", "expected"),
    [
        (20, None, 20),      # 用户没配 ⇒ 模型要多少给多少（现状行为）
        (20, 5, 5),          # 要得更多 ⇒ 夹到上限
        (2, 5, 2),           # 要得更少 ⇒ 尊重模型（夹上去是"变差的检索"）
        (5, 5, 5),           # 恰好等于
        (999, 3, 3),         # 非法大值也先被上限挡住
        (0, None, 1),        # 越界下限 ⇒ 夹到硬界，不让整次工具调用变成 failed
    ],
)
def test_clamp_top_k_的六种情形(model_supplied: int, ceiling: int | None, expected: int) -> None:
    assert clamp_top_k(model_supplied, ceiling) == expected


def test_上下文设了要还得回来并能在离开后清空() -> None:
    assert task_top_k() is None
    token = set_task_top_k(4)
    try:
        assert task_top_k() == 4
    finally:
        reset_task_top_k(token)
    assert task_top_k() is None, "线程池会复用线程，没还原就会串到下一条任务"


def test_传None等于不设限也不留残留值() -> None:
    with task_top_k_scope(6):
        assert task_top_k() == 6
        token = set_task_top_k(None)
        assert token is None, "None 不该占一个还原位"
        assert task_top_k() == 6, "不设限 ≠ 把已有的上限抹掉"
    assert task_top_k() is None


def test_越界的用户配置被夹进硬界而不是报错() -> None:
    with task_top_k_scope(999):
        assert task_top_k() == 20
    with task_top_k_scope(0):
        assert task_top_k() == 1
