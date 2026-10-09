"""轨迹事件契约：``EventRecord`` 数据模型 + ``TaskEventSink`` 协议 + 落盘门面。

本模块是 **P1-A「事件持久化」的写入侧唯一契约**（对应
``docs/p1_trace_events_design.md`` §3.1 / §7 / §12）。

三条关键纪律（写错一条回放就错）：

1. **单一真源**：``TaskWorker`` 每产出一个事件，**先**构造一个
   :class:`EventRecord`，用 ``database.record_event(**record.to_row())`` 落盘，
   **再**用同一个实例去 ``bus.publish(...)``（见设计文档 §8.2）。
   表是「因果」，SSE 是「通知」。二者共用同一个实例 → 结构上不可能不一致。
2. **落盘先于广播**：事件必须是「先写表、再发实时」，这样进程崩溃后已完成
   步骤仍在表内（设计文档 §1.3 / §8.1）。
3. **NULL 语义**（设计文档 §3.4）：``tool_name`` / ``arguments`` / ``role`` /
   ``node`` / ``sub_step`` / ``error_*`` / ``sse_seq`` 用 ``None`` 表示
   「不存在」；``thought`` / ``observation`` 用空串表示「值为空」。
   **``arguments`` 禁止默认 ``{}``**：``None``（非工具事件）与 ``{}``（无参工具
   调用）是两回事，这一条值得单独说明。

本模块**不 import storage / api**，只依赖 ``api.constants``（常量源）与 pydantic，
以保证「写入侧契约」可被 storage、core、api 三层安全引用而不引入循环导入。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from api.constants import (
    STATUS_SUCCESS,
    TASK_EVT_LLM_CALL,
    TASK_EVT_NODE_END,
    TASK_EVT_TOOL_CALL,
)


class EventRecord(BaseModel):
    """单条轨迹事件的**写入侧数据契约**（对应 ``task_events`` 一行）。

    字段与 ``storage.models.TaskEventRecord`` / ``task_events`` DDL 一一对应；
    ``to_row()`` 产出可直接喂给 ``Database.record_event(**row)`` 的字典。

    ``event_seq`` **不在这里**：它是 SQLite ``AUTOINCREMENT`` 生成的全局单调序，
    由数据库在 ``INSERT`` 时分配（设计文档 §1.1），写入侧不得预填。
    """

    model_config = ConfigDict(extra="forbid")

    # ---- 归属 -------------------------------------------------------------
    event_type: str = Field(description="事件类型，见 constants.TASK_EVENT_TYPES")
    task_id: str = Field(description="所属任务 id")
    role: str | None = Field(default=None, description="角色；任务级事件为 null")

    # ---- 顺序（设计文档 §1.2：step 为编排轮次，sub_step 为轮内子步骤）----
    step: int = Field(default=0, description="编排轮次（0 起），跨角色可比")
    sub_step: int | None = Field(default=None, description="轮内子步骤下标；不隶属则 null")

    # ---- 过程内容 ---------------------------------------------------------
    node: str | None = Field(default=None, description="节点名；任务级事件为 null")
    thought: str = Field(default="", description="LLM 思考/决策文本；无为空串")
    tool_name: str | None = Field(default=None, description="工具名；非工具事件为 null")
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="工具入参；非工具事件为 null。★禁止默认 {}，NULL ≠ {}",
    )
    observation: str = Field(default="", description="工具返回或节点输出；无为空串")

    # ---- 计量（来自 adapter.last_usage，设计文档 §7.2）--------------------
    latency_ms: int = Field(default=0)
    tokens_in: int = Field(default=0)
    tokens_out: int = Field(default=0)
    cost: float = Field(default=0.0)
    #: 本次调用用的模型 id。**``None`` = 这条历史记录时还没记**（成本归因两列后补），
    #: 读取侧**不许**回落到"当前 ``role_map`` 里的模型"。
    model: str | None = Field(
        default=None, description="llm_call 用的模型 id；非 LLM 事件与历史记录为 null"
    )
    #: 本次调用**实际套用**的峰谷价格系数（调用那一刻由 ``pricing.price_multiplier()`` 取值）。
    #: 必须与 ``cost`` 同源：事后重算会在跨 12:00 / 18:00 边界的调用上留下两份矛盾的账。
    #: ⚠️ ``None`` ≠ ``1.0``：前者是"没记录"，后者是"确定跑在高峰"。
    price_multiplier: float | None = Field(
        default=None, description="峰谷价格系数（1.0 / 0.5）；null = 未记录，不等于 1.0"
    )

    # ---- 状态与失败 -------------------------------------------------------
    status: str = Field(default=STATUS_SUCCESS)
    error_code: str | None = Field(default=None, description="null = 本次事件成功")
    error_message: str | None = Field(default=None, description="null = 本次事件成功")

    # ---- 与 EventBus 的旁挂参考（不参与排序，设计文档 §8.2）---------------
    sse_seq: int | None = Field(default=None, description="EventBus 的 seq；不参与排序")

    # -------------------------------------------------------------- 序列化 --
    def to_row(self) -> dict[str, Any]:
        """转成可直接 ``Database.record_event(**row)`` 的字典。

        唯一的字段变换是 ``arguments``：字典 → JSON 字符串（或保持 ``None``）。
        **``None`` 必须原样保留**，绝不能落成 ``'{}'``——否则
        ``WHERE arguments IS NULL``（表示「非工具事件」）就会漏掉这些行，
        违反设计文档 §3.4 的 NULL 纪律。

        Returns:
            列名 → 值 的字典；``arguments`` 为 JSON 串或 ``None``。
        """
        import json

        arguments = self.arguments
        row: dict[str, Any] = {
            "task_id": self.task_id,
            "event_type": self.event_type,
            "role": self.role,
            "step": int(self.step),
            "sub_step": None if self.sub_step is None else int(self.sub_step),
            "node": self.node,
            "thought": self.thought,
            "tool_name": self.tool_name,
            "arguments": None
            if arguments is None
            else json.dumps(arguments, ensure_ascii=False),
            "observation": self.observation,
            "latency_ms": int(self.latency_ms),
            "tokens_in": int(self.tokens_in),
            "tokens_out": int(self.tokens_out),
            "cost": float(self.cost),
            #: ★ 这两行**必须与 EventRecord 的字段同时加**：``to_row()`` 是显式枚举，
            #:   只往模型里加字段而忘了这里，列会永远是 NULL，而迁移脚本还报告"补列成功"
            #:   —— 界面于是把有值的行也读成「未记录模型」，是一种不会报错的假诚实。
            #:   刻意不做回落：``self.model`` 是 ``None`` 就交 ``None``。
            "model": self.model,
            "price_multiplier": self.price_multiplier,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "sse_seq": None if self.sse_seq is None else int(self.sse_seq),
        }
        return row


@runtime_checkable
class TaskEventSink(Protocol):
    """事件落盘口子（写入侧的唯一抽象）。

    任何持有 :class:`TaskEventSink` 的组件（如 ``NodeContext``）都可以
    「发一条事件」而不关心它是写库还是被测试替身吃掉。

    实现方**必须**保证：``__call__`` 内部失败**只记日志、绝不抛异常**
    （纪律同 ``TraceStore.add``）。节点埋点若因落盘失败而中断整个任务，
    是把「观测」误升级为「硬依赖」，与设计文档 §7.5 的失败隔离相悖。
    """

    def __call__(self, record: EventRecord) -> None:
        """落盘一条事件。

        Args:
            record: 已构造好的事件契约实例。
        """
        ...


class DatabaseEventSink:
    """把 :class:`TaskEventSink` 接到 :class:`storage.db.Database` 上的适配器。

    刻意**不在模块顶层 import storage**：本模块是三层共享的契约层，
    顶层 import storage 会让 ``storage`` ↔ ``core`` 产生潜在的导入环。
    改为在 ``__init__`` 里用 ``TYPE_CHECKING`` 仅做类型标注，运行时接受任意
    「有 ``record_event(**fields)`` 方法的对象」（鸭子类型），
    测试可以塞入轻量替身。
    """

    def __init__(self, database: "DatabaseLike") -> None:
        """绑定一个 Database（或任何提供 ``record_event`` 的等价对象）。

        Args:
            database: 目标存储对象，需提供 ``record_event(**fields)`` 方法。
        """
        self._database = database

    def __call__(self, record: EventRecord) -> None:
        """把事件契约落盘（失败只记日志，由 ``Database.record_event`` 兜底）。"""
        self._database.record_event(**record.to_row())


class EventType:
    """事件类型到「元数据默认值」的映射表（埋点施工的便捷入口）。

    构造事件时，多数字段可依事件类型推默认值（如 ``tool_call`` 必然带
    ``tool_name``，任务级事件必然无 ``role``）。本类把这些约定集中一处，
    避免 T02 埋点在各文件里各写一遍、写出不一致。
    """

    #: 需要 ``role`` / ``node`` 的节点级事件
    NODE_LEVEL: frozenset[str] = frozenset(
        {TASK_EVT_LLM_CALL, TASK_EVT_NODE_END}
    )
    #: 工具调用事件（唯一允许 ``tool_name`` / ``arguments`` 非空的类型）
    TOOL_LEVEL: frozenset[str] = frozenset({TASK_EVT_TOOL_CALL})


#: 运行时可注入的 Database 形状（只用到 ``record_event`` 一个方法）。
class DatabaseLike(Protocol):
    """``DatabaseEventSink`` 需要的最小 Database 形状。"""

    def record_event(self, **fields: Any) -> int | None:
        """落一条事件；返回新行的 ``event_seq``（失败返回 ``None``）。"""
        ...


# --------------------------------------------------------------------------- #
# 运行期实时出口（SSE ``delta`` / ``usage`` 帧的契约层）
# --------------------------------------------------------------------------- #
# 为什么走 contextvar 而不是把出口一路当参数传进 ``build_runner``：编排是 worker
# 线程里的**同步**调用栈（``for node, update in runner.stream(...)``），
# ``RunnerFactory`` 的签名是 ``(item) -> WorkflowRunner`` 且被集成测试用单参
# lambda 替换过 —— 多加一个必填参数会直接 TypeError。contextvar 在同一条调用栈里
# 天然只对本任务可见（与 ``core.rag.context`` 的 ``set_task_top_k`` 同一套纪律），
# 且**不改动任何既有函数签名**。
#: 每条增量 = ``(文本, 产出它的节点, 是否清空重来)``
DeltaSink = Callable[[str, str, bool], None]
#: 一次 LLM 调用结束后的用量增量
UsageSink = Callable[[dict[str, Any]], None]


class AnswerStream:
    """运行中答案的增量出口（**append 语义** + 可重置）。

    为什么要能重置：一条任务的答案会被写两遍 —— executor 逐子步骤拼出**草稿**，
    reviewer 再产出**终稿**。二者是同一份内容的两个版本，不是上下两段话；
    不做重置的话前端拼出来的是「草稿 + 终稿」前后相接，读起来是两句互相矛盾的话。

    节点名（``mark``）随增量一起发，是因为前端要靠它区分「现在滚的是草稿还是终稿」
    —— 同一个 ``delta`` 帧序列里没有别的字段能说明这件事。
    """

    __slots__ = ("_sink", "_node")

    def __init__(self, sink: DeltaSink) -> None:
        """绑定一个下游出口（由 ``api/queue.py`` 的 worker 提供）。"""
        self._sink = sink
        self._node = ""

    @property
    def node(self) -> str:
        """当前产出增量的节点名（空串 = 尚未声明）。"""
        return self._node

    def mark(self, node: str) -> None:
        """声明后续增量由哪个节点产出。"""
        self._node = node

    def clear(self) -> None:
        """丢弃已发出的内容，下一段从头写（reviewer 出终稿时用）。"""
        self._sink("", self._node, True)

    def emit(self, text: str) -> None:
        """追加一段新吐出的文本。

        Args:
            text: 增量文本；空串直接忽略（流式分块里空块很常见）。
        """
        if text:
            self._sink(text, self._node, False)

    def flush(self) -> None:
        """把下游压在合批窗口里的增量**立刻**发出去（空文本即"冲"的信号）。

        节点跑完时调一次：否则最后一段会卡在窗口里，直到下一次 emit 才被带出去
        —— 而那一次可能永远不来（这一步就是最后一步）。
        """
        self._sink("", self._node, False)


@dataclass(slots=True)
class TaskStreams:
    """一条任务的实时出口集合（只活在 worker 线程的 contextvar 里）。

    Args:
        answer: 答案增量出口；``None`` 表示这一条不流式（例如批量评测）。
        usage: 用量增量出口；``None`` 同理。
    """

    answer: AnswerStream | None = None
    usage: UsageSink | None = None


_task_streams: ContextVar[TaskStreams | None] = ContextVar("agent_task_streams", default=None)


def set_task_streams(streams: TaskStreams | None) -> Any:
    """把实时出口绑到**当前** worker 线程（返回 reset 用的 token）。"""
    return _task_streams.set(streams)


def reset_task_streams(token: Any) -> None:
    """还原 contextvar。**必须**在 finally 里调用：线程池复用线程，
    不还原的话下一条任务会继承上一条的出口，把 A 的答案增量发到 B 的流里。"""
    _task_streams.reset(token)


def get_task_streams() -> TaskStreams | None:
    """读当前线程的实时出口；没有则为 ``None``（不流式）。"""
    return _task_streams.get()


__all__ = [
    "AnswerStream",
    "DatabaseEventSink",
    "DatabaseLike",
    "DeltaSink",
    "EventRecord",
    "EventType",
    "TaskEventSink",
    "TaskStreams",
    "UsageSink",
    "get_task_streams",
    "reset_task_streams",
    "set_task_streams",
]
