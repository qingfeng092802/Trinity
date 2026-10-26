"""EventBus 历史补发与丢弃计数（G-7）。

这里的判据都是**确定性**的：``subscribe()`` 与 ``_fanout()`` 都在同一个
loop 线程执行、中间没有 ``await``，所以「先发布、再订阅」不依赖 worker 时序。
20 次连跑只用于兜住共享状态（历史/计数器）没有在用例之间泄漏。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from api.constants import SUBSCRIBE_QUEUE_SIZE
from api.events import HISTORY_TTL_SECONDS, EventBus, StreamEvent

TASK_ID = "task-g7"


def _frame(seq: int, name: str = "node") -> StreamEvent:
    return StreamEvent(task_id=TASK_ID, name=name, seq=seq, data={"seq": seq})


def _drain(queue: asyncio.Queue[StreamEvent]) -> list[int | None]:
    seqs: list[int | None] = []
    while not queue.empty():
        seqs.append(queue.get_nowait().seq)
    return seqs


def test_publish_before_subscribe_replays_all_frames_in_order() -> None:
    """★ 先 publish 2 帧、再 subscribe：队列里立刻有这 2 帧且顺序不变（连跑 20 次）。"""

    async def scenario() -> None:
        for _ in range(20):
            bus = EventBus()
            bus.publish_from_loop(_frame(1))
            bus.publish_from_loop(_frame(2))
            queue = await bus.subscribe(TASK_ID)
            assert _drain(queue) == [1, 2]
            assert bus.subscriber_count(TASK_ID) == 1

    asyncio.run(scenario())


def test_last_event_id_skips_already_seen_frames() -> None:
    """重连游标：跳过 ``seq <= last_event_id``，其余按原顺序补发。"""

    async def scenario() -> None:
        bus = EventBus()
        for seq in range(1, 5):
            bus.publish_from_loop(_frame(seq))

        assert _drain(await bus.subscribe(TASK_ID)) == [1, 2, 3, 4]
        assert _drain(await bus.subscribe(TASK_ID, last_event_id=2)) == [3, 4]
        assert _drain(await bus.subscribe(TASK_ID, last_event_id=0)) == [1, 2, 3, 4]
        assert _drain(await bus.subscribe(TASK_ID, last_event_id=4)) == []
        assert _drain(await bus.subscribe(TASK_ID, last_event_id=999)) == []

    asyncio.run(scenario())


def test_queue_full_drops_are_counted_not_silent() -> None:
    """慢客户端：队列满后新帧被丢弃，但计数 +1，已入队帧不受影响。"""

    async def scenario() -> None:
        bus = EventBus()
        queue = await bus.subscribe(TASK_ID)
        for seq in range(1, SUBSCRIBE_QUEUE_SIZE + 1):
            bus.publish_from_loop(_frame(seq))

        assert queue.full()
        assert bus.stats()["dropped_queue_full"] == 0

        bus.publish_from_loop(_frame(SUBSCRIBE_QUEUE_SIZE + 1))
        assert bus.stats()["dropped_queue_full"] == 1

        seqs = _drain(queue)
        assert len(seqs) == SUBSCRIBE_QUEUE_SIZE
        assert seqs[0] == 1
        assert seqs[-1] == SUBSCRIBE_QUEUE_SIZE  # 前 256 帧仍在，丢的是第 257 帧

    asyncio.run(scenario())


def test_publish_without_loop_is_counted_and_warned(caplog: pytest.LogCaptureFixture) -> None:
    """未 bind loop 的丢弃不再静默：首条 WARNING，计数可从 ``stats()`` 读。"""

    bus = EventBus()
    with caplog.at_level(logging.WARNING, logger="api.events"):
        bus.publish(_frame(1))
        bus.publish(_frame(2))

    stats = bus.stats()
    assert stats["dropped_without_loop"] == 2
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, "只首条刷 WARNING，后续降为 debug，但计数仍逐条累加"


def test_history_prunes_after_ttl() -> None:
    """有界历史：超过 TTL 的任务整条清掉，不随进程运行无限增长。"""

    bus = EventBus()
    bus._remember(_frame(1), 0.0)  # 直接构造时间轴，避免 patch 全局 clock
    assert bus.stats()["history_tasks"] == 1

    bus._prune_history(HISTORY_TTL_SECONDS + 1.0)
    assert bus.stats()["history_tasks"] == 0
