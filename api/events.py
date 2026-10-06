"""SSE 事件总线：把 worker 线程（同步）产出的事件跨线程投递给 asyncio 订阅者。

为什么需要这一层
----------------
编排内核是**同步**的（``WorkflowRunner.stream()`` 是生成器），只能跑在线程池里；
而 SSE 订阅者是**协程**。同步代码里不能 ``await``，所以 worker 只能通过
``loop.call_soon_threadsafe(fn, event)`` 把事件「扔」给事件循环，由循环线程
扇出到该任务的每一个订阅队列（设计文档 §4.2 方案 A）。

被否掉的方案 B（每 0.3s 轮询进度缓存）的代价：固定延迟 + 常驻轮询开销 +
无法表达「同一节点内多次事件」，而节点级事件本来就稀疏（一条任务 3-10 个）。

三个必须知道的实现细节
----------------------
1. worker 必须持有 loop 引用 —— 由 :meth:`EventBus.attach_loop` 在
   ``TaskQueue.start()`` 里捕获并注入；
2. 关停时 loop 可能已关闭，``call_soon_threadsafe`` 会抛 ``RuntimeError``，
   必须吞掉并记 debug（否则刷屏）；
3. 订阅队列设了 ``maxsize``，慢客户端会被丢事件并记 WARNING，
   而不是让内存无限涨（设计文档 §9 R12）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from api.constants import SSE_RETRY_MS, SUBSCRIBE_QUEUE_SIZE

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """一条 SSE 事件。

    Attributes:
        task_id: 所属任务。
        name: 事件名（见 :mod:`api.constants` 的 ``EVT_*``）。
        seq: 本任务的 SSE 序号，用作帧的 ``id:``。**发号者只有 worker 一个**
            （``api/queue.py::TaskWorker.run`` 里的 ``seq_box``），一条任务内
            严格递增。``None`` = 这一帧不是任务状态变化、而是连接本地的
            合成帧（``snapshot`` 首屏快照 / ``heartbeat`` 心跳），
            ``format_frame`` 会**整个省掉 ``id:`` 行**——理由见那里。
            ⚠️ 它**不是**全局游标，也不能拿去重连对账：每条连接各自订阅、
            每条任务的号都从 1 起，跨连接/跨任务都不可比。客户端的对账走
            ``/trace`` 的 ``event_seq``（前端 ``api/client.ts`` 的注释与此一致）。
        data: 事件负载（必须可 JSON 序列化）。
    """

    task_id: str
    name: str
    seq: int | None
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """按 task_id 分 topic 的事件总线（订阅者各自一个 ``asyncio.Queue``）。

    线程模型：``_subs`` 只在**事件循环线程**被读写——worker 通过
    :meth:`publish` 走 ``call_soon_threadsafe`` 间接访问，因此不需要加锁。
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[StreamEvent]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        #: 给「尚未 attach loop 就想发布」的场景兜底，避免事件静默丢失时无从排查
        self._dropped_without_loop = 0

    # ------------------------------------------------------------ 生命周期 --
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环（由 ``TaskQueue.start()`` 在启动协程里调用一次）。"""
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """当前绑定的事件循环；未启动时为 ``None``。"""
        return self._loop

    # ---------------------------------------------------------------- 订阅 --
    async def subscribe(self, task_id: str) -> asyncio.Queue[StreamEvent]:
        """订阅某个任务的事件流，返回专属队列（必须在 loop 线程调用）。"""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=SUBSCRIBE_QUEUE_SIZE)
        self._subs.setdefault(task_id, set()).add(queue)
        logger.debug("SSE 订阅 task_id=%s 当前订阅数=%d", task_id, len(self._subs[task_id]))
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue[StreamEvent]) -> None:
        """退订；最后一个订阅者离开时顺手清掉 topic，避免字典无限增长。"""
        subscribers = self._subs.get(task_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subs.pop(task_id, None)

    def subscriber_count(self, task_id: str) -> int:
        """某个任务的订阅者数量（可观测性用）。"""
        return len(self._subs.get(task_id, ()))

    # ---------------------------------------------------------------- 发布 --
    def publish(self, event: StreamEvent) -> None:
        """线程安全的发布（worker 线程调用）。

        Args:
            event: 要发布的事件。
        """
        loop = self._loop
        if loop is None:
            self._dropped_without_loop += 1
            logger.debug(
                "事件总线尚未绑定事件循环，丢弃事件 task_id=%s name=%s", event.task_id, event.name
            )
            return
        try:
            loop.call_soon_threadsafe(self._fanout, event)
        except RuntimeError as exc:
            # 关停中 loop 已关闭：这是预期内的，记 debug 而不是 error
            logger.debug("事件循环已关闭，丢弃事件 %s/%s：%s", event.task_id, event.name, exc)

    def publish_from_loop(self, event: StreamEvent) -> None:
        """在事件循环线程里直接发布（取消 handler 用，省一次调度）。"""
        self._fanout(event)

    #: 设计文档 §3.2 用的名字，保留别名以免两处文档对不上
    publish_nowait_from_loop = publish_from_loop

    def _fanout(self, event: StreamEvent) -> None:
        """把一个事件扇出给该任务的全部订阅者（**只在 loop 线程执行**）。"""
        targets: Iterable[asyncio.Queue[StreamEvent]] = tuple(self._subs.get(event.task_id, ()))
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "订阅队列已满，丢弃事件 task_id=%s name=%s seq=%s（客户端消费过慢）",
                    event.task_id,
                    event.name,
                    event.seq,
                )


# --------------------------------------------------------------------------- #
# 帧格式（手写，零新增依赖）
# --------------------------------------------------------------------------- #
def format_frame(event: StreamEvent) -> str:
    """把事件渲染成一个 SSE 帧：``id: N\\nevent: X\\ndata: {...}\\n\\n``。

    ``ensure_ascii=False`` 让中文直接以 UTF-8 输出（否则一帧里全是 ``\\uXXXX``，
    体积翻倍且不可读）；``default=str`` 兜住 datetime 等非 JSON 原生类型。

    ``seq is None`` 时**整行省略** ``id:``（Q6-10，2026-10-02）：连接本地的
    合成帧（首屏 ``snapshot``、``heartbeat``）本来就不代表任务状态推进，给它编
    一个从 1 起的本地号，就会和 worker 的任务级号在同一根连接上撞车
    （实测形状是 ``id:1`` 之后又来一个 ``id:1``）。SSE 规范允许帧不带 ``id:``，
    浏览器此时保持上一个 ``Last-Event-ID`` —— 那正是我们要的：心跳不该把
    重连游标往前推。

    Returns:
        以 ``\\n\\n`` 结尾的一帧文本。
    """
    payload = json.dumps(event.data, ensure_ascii=False, default=str)
    head = f"id: {event.seq}\n" if event.seq is not None else ""
    return f"{head}event: {event.name}\ndata: {payload}\n\n"


def format_retry_frame(ms: int = SSE_RETRY_MS) -> str:
    """首帧下发的重连间隔提示。"""
    return f"retry: {ms}\n\n"


# 这里原来还有一个 ``format_comment()``（注释帧 ``: 文本``），2026-10-02 删掉：
# 全仓零调用点（代码、用例、文档都没有引用）。Q6-10 讨论过"心跳是不是该走注释帧"，
# 结论是不走：前端 ``web-react/src/api/client.ts`` 把 ``heartbeat`` 挂成一条
# **debug 级日志**（:317），换成注释帧等于把这类条目从日志里删掉，那是改行为不是
# 清理死码。所以心跳仍是具名事件，只是不再带 ``id:``（见 :func:`format_frame`）。
# 记在这里是为了别让下一个人以为"该改用注释帧"是把当初那半套接上。

__all__ = [
    "EventBus",
    "StreamEvent",
    "format_frame",
    "format_retry_frame",
]
