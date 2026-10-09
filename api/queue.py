"""异步任务队列：``asyncio.Queue`` 排队 + 信号量限流 + 线程池执行同步内核。

架构（设计文档 §8）
------------------

* **loop 线程**（1 个）：``submit``、``_dispatch`` 协程、SSE 生成器、取消 handler；
* **worker 线程**（≤ ``api_max_concurrent_tasks`` 个）：跑同步的
  ``WorkflowRunner.stream()``，写缓存、发事件、落终态。

两条铁律
--------

1. ``_pending`` / ``_waiting`` / ``_running`` **只在 loop 线程**被访问。
   这正是「碰队列的路由必须写成 ``async def``」的原因——``def`` 会被 FastAPI
   丢进线程池，那时这些结构就不是单线程访问了（设计文档 §7.6 / R11）。
2. **终态写入只能用 CAS**。取消 handler 在 loop 线程、worker 在池线程，
   用锁会让 worker 持锁做 DB 写、顺带阻塞整个事件循环；改成
   ``UPDATE ... WHERE status = ...`` 把仲裁交给 SQLite 的写串行化。

还有一个容易忽略的坑（R9）：``loop.run_in_executor`` 返回的 future 如果 worker
抛了异常，而没人调 ``future.exception()``，异常会被**静默吞掉**——任务永远卡在
``running`` 且日志里什么都没有。所以 :meth:`TaskQueue._on_worker_done` 里
必须显式取一次。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from api.constants import (
    EVT_CANCELED,
    EVT_DELTA,
    EVT_DONE,
    EVT_FAILED,
    EVT_NODE,
    EVT_SNAPSHOT,
    EVT_USAGE,
    MAX_UPDATE_CHARS,
    RETRY_AFTER_SECONDS,
    STATUS_CANCELED,
    STATUS_EVENT_FAILED,
    STATUS_EVENT_TIMEOUT,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    TASK_EVENT_BY_STATUS,
    TASK_EVT_CANCELED,
    TASK_EVT_FAILED,
    TASK_EVT_NODE,
    TASK_EVT_RUNNING,
    TRACE_MAX_LIMIT,
)
from api.errors import ApiError, ErrorCode
from api.events import EventBus, StreamEvent
from api.runner import (
    RunnerFactory,
    classify_error,
    persist_terminal,
    sanitize_update,
)
from config import Settings, get_settings
from core.events import (
    AnswerStream,
    EventRecord,
    TaskStreams,
    reset_task_streams,
    set_task_streams,
)
from core.llm.pricing import now
from core.tools.task_context import reset_task_top_k, set_task_top_k

#: ``delta`` 帧的合批窗口（毫秒）。
#:
#: 逐 token 发一帧会把一条 20 秒的回答打成几百帧（DeepSeek 中文输出 30+ 块/秒），
#: 而屏上肉眼可辨的刷新在 10Hz 量级 —— 攒一小批再发，帧数降一个数量级而观感不变
#: （人眼读的是"字在长"，不是"每个字各来一帧"）。
#: ⚠️ 窗口不能太大：超过 ~150ms 就会出现"一卡一大段"的台阶感，那和一次性给全文
#: 观感差别不大，流式就白做了。
DELTA_FLUSH_MS = 80
from storage.cache import CacheFacade
from storage.db import Database
from storage.models import TaskRecord
from evaluation.trace import TraceStore

logger = logging.getLogger(__name__)

#: 节点局部结局 → ``task_events.status``（K3：事件 status 只描述**单条事件**的成败）。
#:
#: 与 ``core.agent.base._EVENT_STATUS`` 同口径，专门修缺陷 1：``node`` 事件（Q2）
#: 曾硬编码 ``success``，而同一节点的 ``node_end``（L2）按真实结局记 ``failed``，
#: 于是 planner 失败时同节点两条事件自相矛盾。这里只把「真失败 / 超时」映射为
#: ``failed`` / ``timeout``；``running`` / ``aborted`` / ``done`` 都表示**节点本身**
#: 正常跑完（``aborted`` 是整任务「到迭代上限收口」，不是节点失败），故落 ``success``。
_NODE_EVENT_STATUS: dict[str, str] = {
    "failed": STATUS_EVENT_FAILED,
    "timeout": STATUS_EVENT_TIMEOUT,
}


# --------------------------------------------------------------------------- #
# 数据载体
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CancelToken:
    """单个任务的取消令牌：一个 ``threading.Event`` +「是否已开跑」标记。

    ``event`` 对所有线程立即可见（GIL + 内存模型保证），不需要额外同步。
    ``started_at`` 由 worker 在 ``mark_running`` CAS 成功后写入，
    取消 handler 靠它区分「排队期丢弃」与「节点边界停止」两种模式。
    """

    task_id: str
    event: threading.Event = field(default_factory=threading.Event)
    started_at: float | None = None

    def is_canceled(self) -> bool:
        """是否已请求取消。"""
        return self.event.is_set()

    def mark_started(self) -> None:
        """标记「已真正开跑」（worker 抢到执行权后调用）。"""
        self.started_at = time.time()


@dataclass(slots=True)
class QueueItem:
    """排队中的一条任务。

    ``use_tools`` 与 ``enabled_tools`` 共同决定工具装配（缺陷 A，见
    :func:`api.runner.resolve_tool_names` 的三态语义）：

    * ``use_tools=None``（不传）→ 全量装配（现状行为，向后兼容）；
    * ``use_tools=True`` → 全量装配；
    * ``use_tools=False`` → 低风险安全子集（不再「零工具」，A 缺陷修复点）；
    * ``enabled_tools`` 非空 → 精确装配该白名单（最高优先级）。
    """

    task_id: str
    task: str
    max_iterations: int
    review_threshold: int
    use_tools: bool | None
    run_judge: bool
    difficulty: str | None
    submitted_at: float
    cancel: CancelToken
    enabled_tools: list[str] | None = None
    #: 成本预算上限（元）。``None`` = 不设限。只在**节点边界**判（见
    #: :meth:`TaskWorker._limit_trip` 第 1 条口径），所以它是软上限。
    max_cost_cny: float | None = None
    #: 任务超时（秒）。``None`` = 不设限。同样是节点边界的软超时。
    timeout_s: int | None = None
    #: 本任务的 RAG 检索条数上限。``None`` = 用后端默认（``settings.knowledge_top_k``）。
    #: 由 worker 在跑编排之前放进 :mod:`core.tools.task_context`，
    #: 工具侧把模型自己传的 ``top_k`` **clamp 到它**（U-4 拍的那一条）。
    rag_top_k: int | None = None


class CancelRegistry:
    """``task_id`` → :class:`CancelToken` 的登记表。

    loop 线程写、worker 线程只读。CPython 下 dict 的单项操作本就是原子的，
    这里仍加一把锁：语义表达「这是跨线程共享状态」，也防止将来有人加复合操作。
    """

    def __init__(self) -> None:
        self._tokens: dict[str, CancelToken] = {}
        self._lock = threading.Lock()

    def register(self, task_id: str) -> CancelToken:
        """登记（已存在则复用），返回令牌。"""
        with self._lock:
            token = self._tokens.get(task_id)
            if token is None:
                token = CancelToken(task_id=task_id)
                self._tokens[task_id] = token
            return token

    def get(self, task_id: str) -> CancelToken | None:
        """取令牌；不存在返回 ``None``（说明任务已终态并被清理）。"""
        with self._lock:
            return self._tokens.get(task_id)

    def pop(self, task_id: str) -> None:
        """移除令牌（任务进入终态后调用，避免无限增长）。"""
        with self._lock:
            self._tokens.pop(task_id, None)

    def __len__(self) -> int:
        """当前登记数（可观测性用）。"""
        with self._lock:
            return len(self._tokens)


# --------------------------------------------------------------------------- #
# worker：在池线程里跑编排
# --------------------------------------------------------------------------- #
class TaskWorker:
    """在 worker 线程内执行一条任务（无状态，纯函数集合，便于单测）。

    Args:
        database: 数据库门面（CAS 写状态）。
        cache: 缓存门面（写进度）。
        trace_store: 埋点出口。
        event_bus: 事件总线（跨线程发布 SSE 事件）。
        runner_factory: 每任务构造编排器的工厂。
        settings: 全局配置（judge 与日志用）。
    """

    def __init__(
        self,
        *,
        database: Database,
        cache: CacheFacade,
        trace_store: TraceStore,
        event_bus: EventBus,
        runner_factory: RunnerFactory,
        settings: Settings | None = None,
    ) -> None:
        self.database = database
        self.cache = cache
        self.traces = trace_store
        self.bus = event_bus
        self.factory = runner_factory
        self.settings = settings or get_settings()

    def run(self, item: QueueItem) -> None:
        """执行一条任务（**在线程池里运行**，不能 ``await``）。

        全流程：CAS 抢执行权 → 发 running 快照 → 逐节点跑 → 落终态 → 发终态事件。
        任何异常都被收敛成 ``failed`` 终态，绝不向上抛（否则会静默丢进 future）。
        """
        task_id = item.task_id
        started = time.perf_counter()
        #: 本任务**所有** SSE 帧共用的序号盒（2026-10-02，Q6-10）。
        #: 改前是两套号：worker 循环里一个 ``seq``，``_build_streams`` 里另一个
        #: ``state["seq"]`` —— 两条流在同一条连接上交错发帧，于是 ``id:`` 会重复
        #: （node 帧 id=3 之后紧跟一个 delta 帧也是 id=3），而 ``api/events.py`` 的
        #: ``StreamEvent.seq`` 一直写着"单调递增序号，用作 SSE 的 id，便于客户端去重"。
        #: 用盒子而不是 int：delta/usage 是在编排栈深处被回调的，拿不到循环里的局部变量，
        #: 而闭包共享一个可变对象就行。**不需要锁**：编排是 worker 线程里的同步 for 循环，
        #: 这两条流只在同一个线程里递增（``set_task_streams`` 那段线程纪律）。
        seq_box: dict[str, int] = {"n": 0}

        def next_seq() -> int:
            seq_box["n"] += 1
            return seq_box["n"]

        collected: dict[str, Any] = {}
        completed_nodes: list[str] = []
        #: 本任务已写入的最大编排轮次（任务级事件取 ``step=当前最大 step``，§1.2）
        max_step = 0
        #: :meth:`set_task_top_k` 的返回位；``None`` = 没设过（reset 也容忍没设过）
        top_k_token: Any = None
        #: 实时出口与其 contextvar token（与 top_k 同一条「线程池复用 ⇒ 必须 reset」纪律）
        streams: TaskStreams | None = None
        streams_token: Any = None

        try:
            # ① CAS：抢不到说明排队期已被取消 → 零 LLM 调用直接返回
            if not self.database.mark_running(task_id):
                logger.info("任务在排队期被取消，跳过执行 task_id=%s", task_id)
                return
            item.cancel.mark_started()
            # 每任务的 RAG 条数上限（U-4）：worker 线程里设，工具在**同一线程**被调用
            # （编排是 run() 调用栈里的同步循环），所以 contextvar 天然只对本任务可见。
            # ⚠️ 线程池会复用线程 ⇒ 必须在 finally 里 reset，否则下一条任务会继承
            # 上一条的上限（那种串味不会报错，只会让检索条数莫名其妙）。
            top_k_token = set_task_top_k(item.rag_top_k)
            #: 实时出口（SSE ``delta`` / ``usage``）：与 top_k 完全同构 ——
            #: worker 线程里设、编排栈里读（``api/runner.build_runner``）、finally 里 reset。
            #: 不 reset 的话线程池复用线程会把 A 的答案增量发到 B 的流上，
            #: 那种串号不报错、只会在界面上表现为"别人的答案冒出来一段"。
            streams = self._build_streams(item, seq_box)
            streams_token = set_task_streams(streams)

            # ② 先发一帧 running 快照，让刚连上的客户端立刻看到状态
            seq = next_seq()
            # Q1（设计文档 §7.1）：先落盘 running 事件，再发 SSE（落盘先于广播，K2）
            self._record_event(
                item,
                TASK_EVT_RUNNING,
                step=0,
                status=STATUS_RUNNING,
                sse_seq=seq,
            )
            self._publish(
                item,
                EVT_SNAPSHOT,
                seq,
                {
                    "task_id": task_id,
                    "status": STATUS_RUNNING,
                    "progress": self._progress_payload(
                        item, None, completed_nodes, 0, iteration=0
                    ),
                    "ts": now().isoformat(),
                },
            )

            runner = self.factory(item)
            for node, update in runner.stream(item.task, task_id=task_id):
                seq = next_seq()
                # 该节点的状态增量（``None`` 归一成 ``{}``）。此处只 sanitize 一次，
                # 供 collected 累计、node 事件状态判定、以及 SSE 载荷三处复用。
                node_update = sanitize_update(update, MAX_UPDATE_CHARS)
                collected.update(node_update)
                if node not in completed_nodes:
                    completed_nodes.append(node)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                # 本轮真实轮次：从**同一个** collected 读一次，供进度快照、node 事件的
                # step、SSE 载荷三处复用（原来 :415 那行写死 0，于是页面上"N/M 轮"
                # 的 N 永远是 0 —— U-9 修的就是这个）。
                iteration = int(collected.get("iteration", 0) or 0)
                self.cache.save_progress(
                    task_id,
                    self._progress_payload(
                        item, node, completed_nodes, elapsed_ms, iteration=iteration
                    ),
                )
                # Q2（设计文档 §7.1）：与既有 SSE node 事件**同源**，先落盘再发。
                # step = 编排轮次（iteration），不是角色内局部序号（K1）。
                node_step = iteration
                max_step = max(max_step, node_step)
                # 缺陷 1（P1）：node 事件的 status 必须来自该节点的**真实结局**，不得
                # 硬编码 success——否则同一节点的 node 与 node_end 会自相矛盾
                # （planner 失败时 node_end=failed，node 却报 success）。口径与
                # ``core.agent.base._emit_events`` 的 node_end 对齐（K3）。
                node_status = _NODE_EVENT_STATUS.get(
                    str(node_update.get("status") or "").strip(), STATUS_SUCCESS
                )
                self._record_event(
                    item,
                    TASK_EVT_NODE,
                    node=node,
                    step=node_step,
                    status=node_status,
                    sse_seq=seq,
                )
                self._publish(
                    item,
                    EVT_NODE,
                    seq,
                    {
                        "task_id": task_id,
                        "node": node,
                        "iteration": iteration,
                        "seq": seq,
                        "ts": now().isoformat(),
                        "update": node_update,
                    },
                )
                # ③ 节点边界检查点：取消生效的地方（L1：当前节点已经跑完）
                if item.cancel.is_canceled():
                    logger.info("任务在节点边界停止 task_id=%s node=%s", task_id, node)
                    return

                # ③b 运行期闸门（U-3）：预算 / 超时**只有这里可判** —— 编排是 worker 线程里
                # 的同步 for 循环，不是 asyncio 任务，没有"到点就掐"这回事。放在取消检查
                # **之后**：用户已经点了取消时，不必再给这条任务盖一个"被预算中断"的章。
                trip = self._limit_trip(item, elapsed_ms=elapsed_ms)
                if trip is not None:
                    seq = next_seq()
                    self._stop_by_limit(item, trip, step=node_step, seq=seq)
                    return

            #: 编排结束 ⇒ 把还压在合批窗口里的最后一段增量冲出去。
            #: 位置很讲究：必须在**终态帧之前**。放后面（比如 finally 里）的话
            #: 客户端会先收到 ``done``、再收到一段 delta —— 那时结果屏已经切到终稿了，
            #: 迟到的那段增量要么被当成新内容追加、要么被丢掉，两种都是错的。
            if streams is not None and streams.answer is not None:
                streams.answer.flush()

            # ④ 正常跑完 → 落终态（内部 CAS，被取消时会丢弃结果）
            status = persist_terminal(
                item,
                collected,
                database=self.database,
                trace_store=self.traces,
                run_judge=item.run_judge,
                settings=self.settings,
            )
            record = self.database.get_task(task_id)
            if record is not None and record.status == status:
                seq = next_seq()
                # Q3（设计文档 §7.1）：终态事件，error_* 从落库后的 record 取
                # （persist_terminal 已把它写进 tasks；这样事件与列同源）。
                self._record_event(
                    item,
                    TASK_EVENT_BY_STATUS.get(status, TASK_EVT_FAILED),
                    step=max_step,
                    status=status,
                    error_code=record.error_code,
                    error_message=record.error_message,
                    sse_seq=seq,
                )
                self._publish(
                    item,
                    EVT_FAILED if status == "failed" else EVT_DONE,
                    seq,
                    self._terminal_payload(record),
                )
            else:
                logger.debug("终态已被取消覆盖，不发送终态事件 task_id=%s", task_id)

        except Exception as exc:  # noqa: BLE001 - worker 边界必须兜住一切
            # ⑤ 异常路径：worker 线程内的异常必须自己记日志，
            #    不能指望 future 回调（那边的日志只覆盖「没被捕获」的情况）
            logger.exception("任务执行失败 task_id=%s", task_id)
            code, message = classify_error(collected)
            detail = f"{type(exc).__name__}: {exc}"
            error_message = f"{message}｜{detail}"[:1000]
            try:
                self.database.mark_terminal(
                    task_id,
                    status="failed",
                    error_code=code,
                    error_message=error_message,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                seq = next_seq()
                # Q4（设计文档 §7.1，E2）：worker 自身抛异常时也补一条 failed 事件，
                # 与上面的 mark_terminal 同源（code / error_message 共用一份取值）。
                self._record_event(
                    item,
                    TASK_EVT_FAILED,
                    step=max_step,
                    status="failed",
                    error_code=code,
                    error_message=error_message,
                    sse_seq=seq,
                )
                self._publish(
                    item,
                    EVT_FAILED,
                    seq,
                    {"task_id": task_id, "error": {"code": code, "message": message}},
                )
            except Exception:  # noqa: BLE001 - 兜底写也失败时不能再抛
                logger.exception("失败终态落库异常 task_id=%s", task_id)
        finally:
            self.cache.drop_progress(task_id)
            reset_task_top_k(top_k_token)
            if streams_token is not None:
                reset_task_streams(streams_token)

    # -------------------------------------------------------------- 内部 --
    def _record_event(self, item: QueueItem, event_type: str, **fields: Any) -> int | None:
        """把一条编排事件落 ``task_events``（**先落盘、再广播**，设计文档 §7.1 / K2）。

        三条纪律（写错一条回放就错）：

        1. **同步落盘**：直接在 worker 线程的调用栈内 ``INSERT``，不经过 asyncio
           队列——进程崩溃后已完成步骤仍在表内；
        2. **失败隔离**：``Database.record_event`` 内部失败只 WARN 不抛
           （同 ``TraceStore.add``），本方法**不额外兜底**，让该纪律只有一处实现；
        3. **调用顺序**：必须早于同源的 ``_publish(...)``（本类所有埋点都遵守）。

        Args:
            item: 队列任务（取其 ``task_id``）。
            event_type: 事件类型，取值见 ``api.constants.TASK_EVENT_TYPES``。
            **fields: 事件其余字段（``step`` / ``role`` / ``node`` / ``status`` /
                ``error_code`` …）；键必须是 ``EventRecord`` 上的合法字段。

        Returns:
            新行的 ``event_seq``；落盘失败返回 ``None``。
        """
        try:
            record = EventRecord(task_id=item.task_id, event_type=event_type, **fields)
        except Exception:  # noqa: BLE001 - 埋点构造失败绝不能拖垮主流程
            logger.warning(
                "task_events 事件构造失败（已跳过）task_id=%s type=%s",
                item.task_id,
                event_type,
                exc_info=True,
            )
            return None
        return self.database.record_event(**record.to_row())

    def _build_streams(
        self, item: QueueItem, seq_box: dict[str, int]
    ) -> TaskStreams:
        """给一条任务造实时出口（SSE ``delta`` / ``usage`` 的发布端）。

        三条纪律：

        1. **只攒批、不重排**：``buf`` 是纯 FIFO，flush 只是"攒够一批再发一次"，
           绝不改写顺序 —— 答案的顺序就是模型吐字的顺序，重排就等于改内容；
        2. **换节点先把上一个节点的尾巴冲掉**：executor 的最后一段可能还压在
           窗口里没发，若不冲，它会顶着 ``node=reviewer`` 的名义发出去，
           前端拼出来的就是"终稿里混着草稿尾巴"；
        3. **reset 帧必须带得上**：``clear`` 只置标志、不发帧，等下一批文本
           一起发。这样"清空"和"新内容"是原子的 —— 分成两帧的话中间那一个
            tick 上屏是空的，会闪一下。

        第四条是 Q6-10 加进来的：**``id:`` 只有一个计数器**。``seq_box`` 就是
        worker 循环用的那一个，两条流在同一条 SSE 连接上交错发帧，各数各的
        必然撞号（node 帧 ``id: 3`` 之后紧跟一个 ``delta`` 帧也是 ``id: 3``，
        而且 ``delta`` 的号是从 1 起独立数的 ⇒ 流上的 ``id:`` 会往回走）。
        ⚠️ 今天的前端**不靠** ``id:`` 对账：``web-react/src/api/client.ts`` 明写
        了它自己退避重连、断口靠 ``/trace`` 的 ``event_seq`` 补拉 —— 因为后端不读
        ``Last-Event-ID``，且号跨连接不可比。所以这一条修的是**协议自述与实际
        行为不符**（``StreamEvent.seq`` 的 docstring 一直宣称"单调递增、便于去重"），
        不是修一个界面上看得见的错。这里不新建 state 里的 ``seq``，改用同一个盒子。

        Args:
            item: 队列任务。
            seq_box: 与 worker 循环共享的序号盒子（``{"n": int}``）。

        Returns:
            绑好发布端的 :class:`~core.events.TaskStreams`。
        """
        state: dict[str, Any] = {
            "node": "",
            "reset": False,
            "buf": [],
            "last": time.perf_counter(),
        }

        def next_seq() -> int:
            # 与 worker 侧同名同实现：增量在盒子里，闭包不必 nonlocal。
            seq_box["n"] += 1
            return seq_box["n"]

        def flush(*, force: bool) -> None:
            buf: list[str] = state["buf"]
            if not buf:
                return
            if not force and (time.perf_counter() - state["last"]) * 1000 < DELTA_FLUSH_MS:
                return
            text = "".join(buf)
            buf.clear()
            state["last"] = time.perf_counter()
            self._publish(
                item,
                EVT_DELTA,
                next_seq(),
                {
                    "task_id": item.task_id,
                    "node": state["node"],
                    "text": text,
                    "reset": state["reset"],
                    "ts": now().isoformat(),
                },
            )
            state["reset"] = False

        def delta_sink(text: str, node: str, reset: bool) -> None:
            if node != state["node"]:
                # 换节点：先把旧节点的尾巴冲出去（带**旧**节点名），再换名
                flush(force=True)
                state["node"] = node
            if reset:
                state["buf"].clear()
                state["reset"] = True
                return
            if not text:
                # 空文本 = 强制 flush（AnswerStream 的 emit 不会传空串）
                flush(force=True)
                return
            state["buf"].append(text)
            flush(force=False)

        def usage_sink(payload: dict[str, Any]) -> None:
            # 用量是"一次调用一笔"，一条任务只有几次调用 —— 不攒批，也不值得攒。
            self._publish(
                item,
                EVT_USAGE,
                next_seq(),
                {"task_id": item.task_id, "ts": now().isoformat(), **payload},
            )

        return TaskStreams(answer=AnswerStream(delta_sink), usage=usage_sink)

    def _progress_payload(
        self,
        item: QueueItem,
        current_node: str | None,
        completed_nodes: list[str],
        elapsed_ms: int,
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        """组装 ``progress:{task_id}`` 的内容（几十字节的轻量视图）。

        ⚠️ ``iteration`` 以前是**写死的 0**（U-9）：那一行让页面上"N / M 轮"的 N
        永远停在 0，而同一份 ``collected`` 里的 ``iteration`` 是真的 —— 于是
        ``max_iterations`` 报得准、轮次报不准，两个读数并排着自相矛盾。
        现在由调用方把真实值传进来：开跑前那一帧是 0（确实一个节点都没跑完），
        每个节点之后传 ``collected['iteration']``。
        """
        return {
            "status": STATUS_RUNNING,
            "current_node": current_node,
            "completed_nodes": list(completed_nodes),
            "iteration": int(iteration),
            "max_iterations": item.max_iterations,
            "elapsed_ms": elapsed_ms,
            "updated_at": now().isoformat(),
        }

    # ----------------------------------------------------- 运行期闸门 (U-3) --
    def _limit_trip(self, item: QueueItem, *, elapsed_ms: int) -> tuple[str, str] | None:
        """节点边界上的两道闸门：超时 → 预算。超了返回 ``(code, message)``，否则 ``None``。

        三条口径都属于"不写清楚就会骗人"的那类：

        1. **只在节点边界判**（编排是 worker 线程里的同步 for 循环，不是 asyncio 任务，
           做不了"到点就掐"）。⇒ 这是**软上限**，界面必须把生效条件一起显示出来，
           最长可能再等一次完整 LLM 调用（``llm_timeout`` × 重试次数）。
        2. **先判时间再判钱**：超时那一判不碰数据库，成本那一判要读事件表 ⇒ 便宜的先做。
        3. **成本读 ``llm_call`` 事件求和，绝不读 ``tasks.cost``**：运行中那一列恒为 0
           （见 :meth:`storage.db.Database.sum_llm_cost`），读它等于闸门永不触发且不报错。

        预算用 ``>=``：到边界时已经花到上限，再跑一个节点必然超出 ⇒ 停。
        """
        if item.timeout_s is not None and elapsed_ms >= int(item.timeout_s) * 1000:
            return (
                "TIMEOUT_EXCEEDED",
                f"已运行 {elapsed_ms / 1000:.1f} 秒，超过任务超时上限 {item.timeout_s} 秒"
                "（超时只在节点之间检查，故可能超出所设值）",
            )
        if item.max_cost_cny is not None:
            spent = self.database.sum_llm_cost(item.task_id)
            limit = float(item.max_cost_cny)
            if spent >= limit:
                return (
                    "BUDGET_EXCEEDED",
                    f"已花 ¥{spent:.4f}，达到成本预算上限 ¥{limit:.4f}"
                    "（预算只在节点之间检查，中断发生在本次节点跑完之后）",
                )
        return None

    def _stop_by_limit(
        self, item: QueueItem, trip: tuple[str, str], *, step: int, seq: int
    ) -> None:
        """闸门触发后的收尾：**走现成的取消路径**（U-3 拍的那一条）。

        顺序照 :meth:`TaskQueue.publish_canceled`：置事件位 → CAS 落 ``canceled``
        → **先落盘再广播**。区别只有一处：这里带 ``error_code`` / ``error_message``，
        因为"被预算掐掉"与"用户自己取消"在报表里必须分得开
        （K3 那条"取消的 error_code 保持 NULL"对前者不适用，理由写在
        :meth:`storage.db.Database.mark_canceled`）。

        CAS 失败（任务已终态）时**只记日志、不发事件**：那条任务已经有自己的结局了。
        """
        code, message = trip
        item.cancel.event.set()
        if not self.database.mark_canceled(item.task_id, error_code=code, error_message=message):
            logger.info("闸门想中断但任务已终态 task_id=%s code=%s", item.task_id, code)
            return
        self._record_event(
            item,
            TASK_EVT_CANCELED,
            step=step,
            status=STATUS_CANCELED,
            error_code=code,
            error_message=message,
            sse_seq=seq,
        )
        self._publish(
            item,
            EVT_CANCELED,
            seq,
            {
                "task_id": item.task_id,
                "reason": code,
                "message": message,
                "canceled_at": now().isoformat(),
            },
        )
        logger.info("任务被运行期闸门中断 task_id=%s code=%s", item.task_id, code)

    def _terminal_payload(self, record: TaskRecord) -> dict[str, Any]:
        """组装 done / failed 事件的负载（PRD §P0-6）。"""
        if record.status == "failed":
            return {
                "task_id": record.task_id,
                "error": {
                    "code": record.error_code or "node_failed",
                    "message": record.error_message or "任务失败",
                },
            }
        return {
            "task_id": record.task_id,
            "status": record.status,
            "final_answer": record.final_answer,
            "cost": round(record.cost, 6),
            "duration_ms": record.duration_ms,
            "iterations": record.iterations,
            "score": record.score,
            "grade": record.grade,
        }

    def _publish(self, item: QueueItem, name: str, seq: int, data: dict[str, Any]) -> None:
        """发一帧事件（线程安全，内部走 ``call_soon_threadsafe``）。"""
        self.bus.publish(StreamEvent(task_id=item.task_id, name=name, seq=seq, data=data))


# --------------------------------------------------------------------------- #
# 队列
# --------------------------------------------------------------------------- #
class TaskQueue:
    """提交 / 调度 / 取消的门面（**唯一实例**，由 :mod:`api.deps` 提供）。

    Args:
        settings: 全局配置。
        database: 数据库门面。
        cache: 缓存门面。
        trace_store: 埋点出口。
        event_bus: 事件总线。
        runner_factory: 编排器工厂。
        max_concurrent: 并发上限；不传取 ``settings.api_max_concurrent_tasks``。
        queue_size: 队列容量；不传取 ``settings.api_queue_max_size``。
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        database: Database,
        cache: CacheFacade,
        trace_store: TraceStore,
        event_bus: EventBus,
        runner_factory: RunnerFactory,
        max_concurrent: int | None = None,
        queue_size: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.database = database
        self.cache = cache
        self.trace_store = trace_store
        self.event_bus = event_bus
        self.max_concurrent = max_concurrent or self.settings.api_max_concurrent_tasks
        self.queue_size = queue_size or self.settings.api_queue_max_size

        self._cancel = CancelRegistry()
        self._worker = TaskWorker(
            database=database,
            cache=cache,
            trace_store=trace_store,
            event_bus=event_bus,
            runner_factory=runner_factory,
            settings=self.settings,
        )
        self._pending: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=self.queue_size)
        self._waiting: deque[str] = deque()
        self._running: dict[str, float] = {}
        self._slots: asyncio.Semaphore | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._started = False
        #: 这里**没有**序号计数器（Q6-10，2026-10-02）。改前这里是
        #: ``_seq_by_task`` + ``_next_seq()``：给 ``canceled`` 帧按任务从 1 起编一套
        #: 私有号，于是同一根连接上取消帧的 1、2、3 会撞上 worker 的 1、2、3。
        #: ``id:`` 的发号者现在只有 worker 的 ``seq_box`` 一个；取消帧在 loop 线程
        #: 直发、拿不到那个盒子，就传 ``seq=None`` ⇒ 帧不带 ``id:``。

    # ------------------------------------------------------------ 生命周期 --
    @property
    def started(self) -> bool:
        """队列是否已启动。"""
        return self._started

    @property
    def cancel_registry(self) -> CancelRegistry:
        """取消令牌登记表（路由要用）。"""
        return self._cancel

    async def start(self) -> None:
        """捕获事件循环、拉起线程池与 dispatcher 协程（幂等）。"""
        if self._started:
            return
        self._loop = asyncio.get_running_loop()
        self.event_bus.attach_loop(self._loop)
        self._pool = ThreadPoolExecutor(
            max_workers=self.max_concurrent, thread_name_prefix="task-worker"
        )
        self._slots = asyncio.Semaphore(self.max_concurrent)
        self._dispatcher = asyncio.create_task(self._dispatch(), name="task-dispatcher")
        self._started = True
        logger.info(
            "任务队列已启动：并发上限=%d 队列容量=%d", self.max_concurrent, self.queue_size
        )

    async def stop(self) -> None:
        """停掉 dispatcher 与线程池（幂等）。

        刻意 ``shutdown(wait=False)``：worker 里可能正卡在一次 120s 的 LLM 调用上，
        等它结束会让关停变成几十秒的假死。
        """
        if not self._started:
            return
        self._started = False
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is not None:
            dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False)
        self._drain_pending()
        self._waiting.clear()
        self._running.clear()
        logger.info("任务队列已停止")

    def _drain_pending(self) -> None:
        """清空未消费的排队项（关停时调用，避免 resurrect）。"""
        while True:
            try:
                self._pending.get_nowait()
            except asyncio.QueueEmpty:
                return

    # ---------------------------------------------------------------- 提交 --
    def register(self, task_id: str) -> CancelToken:
        """为一个即将入队的任务登记取消令牌（在 ``submit`` 之前调用）。"""
        return self._cancel.register(task_id)

    async def submit(self, item: QueueItem) -> int:
        """把任务放进等待队列。

        Args:
            item: 队列任务（``item.cancel`` 须先由 :meth:`register` 登记）。

        Returns:
            排队位置（从 1 开始）。

        Raises:
            ApiError: 队列已满（429 + ``Retry-After``）或队列未启动（500）。
        """
        if not self._started:
            raise ApiError(
                ErrorCode.INTERNAL_ERROR, "任务队列尚未启动，请稍后重试", status=500
            )
        try:
            self._pending.put_nowait(item)
        except asyncio.QueueFull as exc:
            raise ApiError(
                ErrorCode.QUEUE_FULL,
                f"任务队列已满（容量 {self.queue_size}），请稍后重试",
                status=429,
                **{"Retry-After": str(RETRY_AFTER_SECONDS)},
            ) from exc
        self._waiting.append(item.task_id)
        position = len(self._waiting)
        logger.info("任务受理 task_id=%s position=%d", item.task_id, position)
        return position

    def queue_position(self, task_id: str) -> int:
        """排队位置；已在运行 / 已终态返回 0。"""
        try:
            return self._waiting.index(task_id) + 1
        except ValueError:
            return 0

    def is_running(self, task_id: str) -> bool:
        """该任务是否正占用 worker 槽位。"""
        return task_id in self._running

    def list_running_ids(self) -> list[tuple[str, float]]:
        """枚举运行中的任务（只读快照，**必须在 loop 线程调用**）。

        Returns:
            ``(task_id, 开始时刻 time.time())`` 列表；仅供 ``GET /tasks``
            合并内存态视图使用，不参与任何调度决策。
        """
        return list(self._running.items())

    def list_queued_ids(self) -> list[tuple[str, int]]:
        """枚举排队中的任务（只读快照，**必须在 loop 线程调用**）。

        Returns:
            ``(task_id, 排队位置从 1 开始)`` 列表，顺序即执行顺序。
        """
        return [(task_id, index + 1) for index, task_id in enumerate(self._waiting)]

    def stats(self) -> dict[str, int]:
        """队列计数（``/health.checks.queue`` 用）。"""
        return {
            "running": len(self._running),
            "queued": len(self._waiting),
            "max_concurrent": self.max_concurrent,
        }

    # ---------------------------------------------------------------- 调度 --
    async def _dispatch(self) -> None:
        """dispatcher 协程：**先**抢槽位，**再**取任务。

        顺序很关键：反过来（先取任务再抢槽位）会让「已取出的任务」在信号量上排队，
        那时 ``_waiting`` 已经把它移走了，``queue_position`` 就会返回 0，
        页面上的「前面还有 N 个」直接失效。
        """
        assert self._slots is not None and self._pool is not None  # noqa: S101 - start 里已建
        assert self._loop is not None  # noqa: S101 - 同上
        while True:
            await self._slots.acquire()
            item = await self._pending.get()
            with contextlib.suppress(ValueError):
                self._waiting.remove(item.task_id)
            self._running[item.task_id] = time.time()
            future: Future[None] = self._loop.run_in_executor(self._pool, self._worker.run, item)
            # 把 task_id 绑进闭包：done 回调需要知道清掉哪一行运行表
            future.add_done_callback(lambda fut, tid=item.task_id: self._on_worker_done(fut, tid))

    def _on_worker_done(self, future: Future[None], task_id: str) -> None:
        """worker 结束回调：取异常 + 清理运行表 + 释放槽位。

        **必须**调一次 ``future.exception()``：否则 worker 里的异常会被
        asyncio 静默吞掉，任务永远卡在 ``running`` 且日志一片空白（设计文档 R9）。

        运行表清理放在这里而不是 worker 线程：``add_done_callback`` 严格在
        loop 线程触发，``_running`` 的「仅 loop 线程访问」约束由此保证。
        **否则 ``_running`` 只进不出，``/health`` 的 running 会虚高，
        并发上限的观测全部失真**（M1 实测踩过：running=4 > max_concurrent=2）。
        """
        try:
            if not future.cancelled():
                exc = future.exception()
                if exc is not None:
                    logger.exception("worker 线程异常：%s", exc, exc_info=exc)
        except asyncio.CancelledError:  # pragma: no cover - 关停瞬间才会发生
            return
        finally:
            self.release_running(task_id)
            if self._slots is not None:
                # 关停时信号量可能被释放过多次（dispatcher 被 cancel），吞掉即可
                with contextlib.suppress(ValueError):
                    self._slots.release()

    def release_running(self, task_id: str) -> None:
        """从运行表里摘掉一个任务（worker 通过 ``call_soon_threadsafe`` 调用）。

        与 :meth:`_on_worker_done` 分离是为了让「清理运行表」这件事
        严格发生在 loop 线程——``_running`` 是**仅 loop 线程**访问的共享状态。
        """
        self._running.pop(task_id, None)
        self._cancel.pop(task_id)

    # ---------------------------------------------------------------- 取消 --
    def publish_canceled(self, task_id: str, *, canceled_at: str) -> None:
        """在 loop 线程直发一帧 ``canceled`` 事件（取消 handler 调用）。

        Q5（设计文档 §7.1）：取消发生在 loop 线程，**先落盘** ``canceled``
        事件再发实时帧——``Database`` 的 engine 已 ``check_same_thread=False``
        + 每次新建 Session，跨线程落盘天然安全（§7.5），无需新锁。

        ``error_code`` 保持 ``NULL``（取消不是失败，K3）；``step`` 取该任务
        当前最大 step（由事件表里已有事件的 step 决定，读不到则退化 0）。

        ``seq=None``（Q6-10，2026-10-02）：这一帧在 loop 线程直发，拿不到 worker
        任务级 ``seq_box`` 的号，而它原来那套私有号（``_next_seq``，按任务从 1 起）
        会和同一根连接上 worker 的 1、2、3 撞车。改法选「不带 ``id:``」而不是
        「再造一个号」：``id:`` 的发号者从此只有 worker 一个。
        """
        code = self._cancel_event_code(task_id)
        self.event_bus.publish_from_loop(
            StreamEvent(
                task_id=task_id,
                name=EVT_CANCELED,
                seq=None,
                data={
                    "task_id": task_id,
                    "reason": "user_requested",
                    "canceled_at": canceled_at,
                },
            )
        )

    def _cancel_event_code(self, task_id: str) -> str:
        """落一条 ``canceled`` 事件（失败只 WARN，不抛），返回终态状态名。

        独立成方法是为了让 :meth:`publish_canceled` 保持只做「广播」一件事；
        落盘顺序仍严格早于广播（本方法在 ``publish_from_loop`` 之前被调用）。
        """
        try:
            step = 0
            events = self.database.list_events(task_id, limit=TRACE_MAX_LIMIT)
            if events:
                step = max(int(event.step) for event in events)
            self.database.record_event(
                **EventRecord(
                    task_id=task_id,
                    event_type=TASK_EVT_CANCELED,
                    step=step,
                    status=STATUS_CANCELED,
                    error_code=None,
                    error_message=None,
                ).to_row()
            )
        except Exception:  # noqa: BLE001 - 取消事件落盘失败绝不能影响取消本身
            logger.warning("canceled 事件落盘失败 task_id=%s", task_id, exc_info=True)
        return STATUS_CANCELED


__all__ = ["CancelRegistry", "CancelToken", "QueueItem", "TaskQueue", "TaskWorker"]
