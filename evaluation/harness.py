"""P2 评测台 · **执行与归一化通道**（T03）。

本模块负责「把一条 :class:`evaluation.taskset.EvalTask` 真跑一遍，并把结果归一化成
契约层唯一产物 :class:`evaluation.contracts.TaskRun`」。两条通道：

* **直调通道**（默认，:data:`~evaluation.contracts.CHANNEL_DIRECT`）——
  在本进程内直接拼装 ``WorkflowRunner``，仿 ``evaluation/batch.py`` 的装配方式，
  但**额外挂上 ``event_sink``**，因此同一次运行既有旧 ``traces`` 又有新 ``task_events``，
  可交叉校验两者口径（把 ``batch.py`` 缺 ``event_sink`` 导致的「不产生任何
  ``task_events``」缺陷从隐患变成可检测项）；
* **HTTP 通道**（``--via-api``，:data:`~evaluation.contracts.CHANNEL_API`）——
  ``POST /tasks`` → 轮询 ``GET /tasks/{id}`` 到终态 → 拉 ``GET /tasks/{id}/trace``，
  真·端到端（含队列 / 并发 / CAS 持久化），作为「金标准通道」。

**两通道断言同源**：无论走哪条通道，都产出同一个 :class:`TaskRun`，断言引擎只吃它。

⚠️ **隔离库硬约束（务必遵守，违反会让检索类任务全灭）**
------------------------------------------------------
``data/trinity.db`` **不只是任务库**，它同时是 **RAG 向量库**
（``documents`` / ``chunks`` / ``knowledge_vec*`` / ``knowledge_meta`` 都在同一个文件）。
因此：

* **绝不能用「空库」跑评测** —— 空库下 ``knowledge_search`` 查不到任何文档，
  所有检索类任务必然失败，指标毫无意义。
* 本模块的「隔离库」是 **现有库的一致性副本**：用 SQLite ``backup`` API 把运行库
  （含 RAG 索引与全部影子表）整库复制到临时路径，再让直调通道的 ``Database`` /
  ``TraceStore`` 指向副本。**绝不新建空库**。
* 副本路径记进 ``TaskRun.meta["db_path"]``，报告里自证「跑的是哪个知识库」。
* **默认绝不写坏 ``data/trinity.db``**（那是演示库，含真实任务与知识库）。
  隔离副本跑完即删（``EvalHarness.close``）。

口径（唯一真源，见 ``evaluation/contracts.py``）
---------------------------------------------
* ``tool_calls`` 权威源 = ``task_events`` 的 ``tool_call`` 事件数，不可用时回退旧
  ``traces``；由 ``TaskRun.tool_source`` 记录实际用了哪个源（不同源数字不可跨基线比较）。
* ``steps`` = **节点执行次数**（= ``node_end`` 事件数 = ``len(TraceStore.for_task())``），
  **不是** ``iterations``（``reviewer.py`` 通过时不加一，会得出 0 的荒谬值）。
* 成本单位 CNY，一律 ``round(x, 6)``。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from api.constants import (
    API_TERMINAL_STATUSES,
    DOC_READY,
    TASK_EVT_NODE_END,
    TASK_EVT_TOOL_CALL,
    TRACE_MAX_LIMIT,
)
from config import Settings, get_settings
from core.agent.base import NodeContext, TraceRecord
from core.events import DatabaseEventSink
from core.llm.adapter import (
    LLMAdapter,
    LLMNotRetryableError,
    text_reports_non_retryable,
)
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry
from core.workflow.graph import WorkflowRunner
from core.workflow.state import WorkflowConfig
from evaluation.contracts import (
    CHANNEL_API,
    CHANNEL_DIRECT,
    CHANNELS,
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_UNKNOWN,
    TASK_STATUSES,
    TOOL_SOURCE_TASK_EVENTS,
    TOOL_SOURCE_TRACES,
    SuiteMetrics,
    TaskRun,
    round_cost,
)
from evaluation.taskset import EvalTask, EvalTaskSet
from evaluation.trace import TraceStore
from storage.db import Database

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 默认参数
# --------------------------------------------------------------------------- #
#: HTTP 通道默认服务地址（本机运行中的 :8000 服务；绑 127.0.0.1，免鉴权）
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
#: 轮询间隔（秒）
DEFAULT_POLL_INTERVAL_S = 0.3
#: HTTP 通道整任务等待上限（秒），超过判失败
DEFAULT_API_TIMEOUT_S = 180.0
#: 单次 HTTP 请求超时（秒）
DEFAULT_HTTP_TIMEOUT_S = 30.0
#: 隔离副本落盘子目录名（相对源库所在目录）
EVAL_DB_DIRNAME = "eval"


class HarnessError(RuntimeError):
    """执行通道的环境 / 参数错误（隔离库不可用、通道非法等）。"""


class HarnessTimeout(HarnessError):
    """单任务超过 ``timeout_s`` 仍未完成。"""


# --------------------------------------------------------------------------- #
# 结果容器
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SkippedTask:
    """因前置条件不满足而跳过的任务（不计入通过率分母，见设计 §4）。"""

    task_id: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        """转成可直接 json.dumps 的字典。"""
        return {"task_id": self.task_id, "reason": self.reason}


@dataclass(slots=True)
class SuiteReport:
    """一次套件执行的产物：**原始 ``TaskRun`` 列表 + 元信息**。

    职责边界（刻意）：本模块**只负责产出 N 个 ``TaskRun``**；
    通过率 / 工具准确率 / 分位延迟等**聚合**由 ``evaluation/metrics.py``（T02）与
    ``evaluation/baseline.py``（T04）负责。``metrics`` 字段留作占位（默认 ``None``），
    由调用方（T05 CLI）用 T02 的汇总函数填入，避免在本模块再造一套口径。
    """

    channel: str
    repeat: int
    runs: list[TaskRun] = field(default_factory=list)
    skipped: list[SkippedTask] = field(default_factory=list)
    aborted: bool = False
    """``True`` = 整批被提前中止（成本护栏 / LLM 重试无用错误）。"""
    abort_reason: str = ""
    cost_total: float = 0.0
    wall_ms: int = 0
    db_path: str = ""
    """本次运行实际使用的 SQLite 库路径（隔离副本，或复用库）。"""
    taskset: dict[str, Any] = field(default_factory=dict)
    metrics: SuiteMetrics | None = None
    """占位：由 T02 的汇总函数填入；本模块不计算。"""

    def runs_for(self, task_id: str) -> list[TaskRun]:
        """取某个任务的（``repeat`` 次）全部运行产物。"""
        return [run for run in self.runs if run.task_id.startswith(f"eval-{task_id}-")]

    def done_runs(self) -> list[TaskRun]:
        """以 ``done`` 收口的运行产物。"""
        return [run for run in self.runs if run.is_done()]

    def failed_runs(self) -> list[TaskRun]:
        """非 ``done`` 的运行产物。"""
        return [run for run in self.runs if not run.is_done()]

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "channel": self.channel,
            "repeat": self.repeat,
            "runs": [run.as_dict() for run in self.runs],
            "skipped": [item.as_dict() for item in self.skipped],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "cost_total": round_cost(self.cost_total),
            "wall_ms": self.wall_ms,
            "db_path": self.db_path,
            "taskset": dict(self.taskset),
            "metrics": None if self.metrics is None else self.metrics.as_dict(),
        }


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def _ev(obj: Any, key: str, default: Any = None) -> Any:
    """统一读取「ORM 行对象 / 普通映射」的同名字段（直调给 ORM，HTTP 给 dict）。"""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_status(raw: Any) -> str:
    """把任务级状态字符串收敛到契约枚举（未知值 → ``unknown``）。"""
    text = str(raw or "").strip().lower()
    return text if text in TASK_STATUSES else STATUS_UNKNOWN


def _slug(value: str) -> str:
    """把任务 id 清洗成 ``^[A-Za-z0-9_-]{1,64}$``（HTTP 提交对 task_id 有格式约束）。"""
    out = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(value))
    return out[:48] or "task"


def _events_to_tool_calls(events: Sequence[Any]) -> tuple[list[str], int]:
    """从 ``task_events`` 行抽取有序工具序列与失败数（按 ``event_seq`` 升序）。"""
    ordered = sorted(events, key=lambda e: int(_ev(e, "event_seq", 0) or 0))
    sequence: list[str] = []
    failures = 0
    for event in ordered:
        if str(_ev(event, "event_type", "")) != TASK_EVT_TOOL_CALL:
            continue
        name = str(_ev(event, "tool_name", "") or "")
        if name:
            sequence.append(name)
        if str(_ev(event, "status", "success") or "success") != "success":
            failures += 1
    return sequence, failures


def _records_to_tool_calls(records: Sequence[TraceRecord]) -> tuple[list[str], int]:
    """从旧 ``traces`` 记录抽取有序工具序列与失败数（按 ``(step, timestamp)`` 升序）。"""
    ordered = sorted(records, key=lambda r: (int(getattr(r, "step", 0) or 0), float(getattr(r, "timestamp", 0.0) or 0.0)))
    sequence: list[str] = []
    failures = 0
    for record in ordered:
        for call in getattr(record, "tool_calls", None) or []:
            name = str((call or {}).get("name") or "")
            if name:
                sequence.append(name)
            if str((call or {}).get("status") or "success") != "success":
                failures += 1
    return sequence, failures


def _count_events(events: Sequence[Any], event_type: str) -> int:
    """统计某类事件条数。"""
    return sum(1 for event in events if str(_ev(event, "event_type", "")) == event_type)


def _event_range(events: Sequence[Any]) -> tuple[int, int] | None:
    """事件游标范围 ``(min_seq, max_seq)``；无事件返回 ``None``。"""
    seqs = [int(_ev(event, "event_seq", 0) or 0) for event in events]
    if not seqs:
        return None
    return (min(seqs), max(seqs))


def check_tool_consistency(
    records: Sequence[TraceRecord], events: Sequence[Any]
) -> dict[str, Any]:
    """★ 一致性自检：对比 ``traces`` 与 ``task_events`` 的**工具序列**与步数。

    直调通道同时挂两个 sink，于是同一次运行两条链路都有数据。若两者不一致，
    说明埋点链路有缺陷（设计 §3.3 / §0.2②），必须显式报出而不是静默。

    Returns:
        ``{"checked", "matched", "traces_tool_sequence", "events_tool_sequence",
        "traces_steps", "events_steps", "warning"}``。``checked`` 仅在两侧都有数据时为真。
    """
    traces_seq, _ = _records_to_tool_calls(records)
    events_seq, _ = _events_to_tool_calls(events)
    traces_steps = len(records)
    events_steps = _count_events(events, TASK_EVT_NODE_END)
    checked = bool(records) and bool(events)
    matched = (traces_seq == events_seq) and (traces_steps == events_steps)
    warning = ""
    if checked and not matched:
        warning = (
            "event_sink/trace_sink 不一致：traces 工具序列 "
            f"{traces_seq}（{traces_steps} 步）≠ task_events 工具序列 "
            f"{events_seq}（{events_steps} 步）——埋点链路可能存在缺陷"
        )
        logger.warning("%s", warning)
    return {
        "checked": checked,
        "matched": matched,
        "traces_tool_sequence": traces_seq,
        "events_tool_sequence": events_seq,
        "traces_steps": traces_steps,
        "events_steps": events_steps,
        "warning": warning,
    }


def _abort_text(state: Any) -> str:
    """从（失败）状态里取一句话原因（对齐 ``evaluation/batch.py::_abort_text``）。"""
    if isinstance(state, Mapping):
        return str(state.get("review_comment") or state.get("final_answer") or "")
    return str(state)


def _state_reports_non_retryable(state: Any) -> bool:
    """失败状态里是否含「重试无用」标记（余额 / 鉴权，复用既有文本判定）。"""
    if not isinstance(state, Mapping) or state.get("status") != STATUS_FAILED:
        return False
    return text_reports_non_retryable(_abort_text(state))


def _decide_terminal(state: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    """**单一出口**的终态判定（与 ``api/runner.decide_terminal_status`` 同源）。

    直调通道不走 ``persist_terminal``，但终态必须和 HTTP 通道一致（否则「同一任务
    两个通道一个 done 一个 aborted」）。故复用 API 侧那唯一的判定函数；为避免顶层
    硬依赖（``api.runner`` 会拉起 ``evaluation.metrics``），改为**延迟 import**，
    并在失败时退回一份等价的最小实现。
    """
    try:
        from api.runner import decide_terminal_status  # noqa: PLC0415 - 延迟导入避免循环/耦合

        return decide_terminal_status(state)
    except Exception:  # noqa: BLE001 - 极端环境下退回最小实现，不阻断评测
        raw = str(state.get("status") or "")
        answer = str(state.get("final_answer") or "").strip()
        if raw == STATUS_FAILED:
            return STATUS_FAILED, "node_failed", _abort_text(state)[:500] or None
        if raw == STATUS_CANCELED:
            return STATUS_CANCELED, "canceled_by_user", "任务被用户取消"
        if answer:
            return STATUS_DONE, None, None
        return STATUS_ABORTED, None, None


def _call_with_timeout(fn: Callable[[], Any], timeout_s: float | None) -> Any:
    """在守护线程里跑 ``fn`` 并施加超时（LangGraph 无取消 API，超时后线程可能仍在跑）。

    Args:
        fn: 无参可调用（实际是 ``runner.run`` 的闭包）。
        timeout_s: 超时秒数；``None`` 或 ``<=0`` 表示不限制。

    Raises:
        HarnessTimeout: 超时。
    """
    if timeout_s is None or timeout_s <= 0:
        return fn()
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样回传给主线程
            box["error"] = exc

    thread = threading.Thread(target=_target, name="eval-direct-run", daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise HarnessTimeout(f"单任务超时：{timeout_s:g}s 内未完成（编排器无取消 API，后台线程可能仍在跑）")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------- #
# 隔离库：一致性副本
# --------------------------------------------------------------------------- #
def _sidecar_paths(db_path: Path) -> list[Path]:
    """SQLite 的 ``-wal`` / ``-shm`` 旁挂文件路径。"""
    return [Path(str(db_path) + suffix) for suffix in ("-wal", "-shm")]


def _unlink_db(db_path: Path) -> None:
    """删除库文件与其 WAL/SHM 旁挂文件（幂等、失败只记日志）。"""
    for path in [db_path, *_sidecar_paths(db_path)]:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - 权限等极端场景
            logger.warning("删除临时库失败：%s（%s）", path, exc)


def copy_sqlite_database(source: Path | str, dest: Path | str, *, overwrite: bool = False) -> Path:
    """把 ``source`` 整库复制到 ``dest``（★ 含 RAG 向量库与全部影子表）。

    优先用 SQLite ``backup`` API：它在页级复制，能拿到 **WAL 下的一致性快照**，
    且无需理解 ``vec0`` 虚拟表即可完整带走其影子表（``knowledge_vec_*``）。
    失败时退化为文件复制（连同 ``-wal`` / ``-shm``）。

    Args:
        source: 源库路径（通常是运行中的 ``data/trinity.db``）。
        dest: 目标副本路径。
        overwrite: 目标存在时是否覆盖（默认 ``False``，存在即报错）。

    Returns:
        ``dest``（``Path``）。

    Raises:
        HarnessError: 源库不存在，或目标已存在且未允许覆盖。
    """
    src_path = Path(source)
    dest_path = Path(dest)
    if not src_path.is_file():
        raise HarnessError(f"源库不存在，无法创建隔离副本：{src_path}")
    if dest_path.exists():
        if not overwrite:
            raise HarnessError(f"隔离副本目标已存在（拒绝覆盖）：{dest_path}")
        _unlink_db(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        src_conn = sqlite3.connect(f"file:{src_path.as_posix()}?mode=ro", uri=True)
        try:
            dest_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest_conn)
                dest_conn.commit()
            finally:
                dest_conn.close()
        finally:
            src_conn.close()
        logger.debug("隔离库副本创建完成（backup API）：%s → %s", src_path, dest_path)
    except sqlite3.Error as exc:
        logger.warning("SQLite backup 复制失败，退化为文件复制：%s", exc)
        shutil.copy2(src_path, dest_path)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src_path) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(dest_path) + suffix))
    return dest_path


# --------------------------------------------------------------------------- #
# 归一化适配器：两通道 → 同一个 TaskRun
# --------------------------------------------------------------------------- #
def to_taskrun_direct(
    state: Mapping[str, Any],
    records: Sequence[TraceRecord],
    events: Sequence[Any],
    *,
    db_path: str = "",
    wall_ms: int = 0,
    channel: str = CHANNEL_DIRECT,
    score: int | None = None,
    grade: str | None = None,
    run_index: int = 0,
) -> TaskRun:
    """把直调通道的原始数据（``state`` + ``traces`` + ``task_events``）归一成 :class:`TaskRun`。

    ``tool_calls`` 权威源优先 ``task_events``（可用时），不可用回退旧 ``traces``；
    ``tool_source`` 记录实际取源。
    """
    state = state or {}
    task_id = str(state.get("task_id") or "")
    status, error_code, error_message = _decide_terminal(state)

    events_available = bool(events)
    if events_available:
        tool_sequence, tool_failures = _events_to_tool_calls(events)
        tool_source = TOOL_SOURCE_TASK_EVENTS
        # steps = 节点执行次数 = node_end 事件数（回退 len(records)）
        steps = _count_events(events, TASK_EVT_NODE_END) or len(records)
    else:
        tool_sequence, tool_failures = _records_to_tool_calls(records)
        tool_source = TOOL_SOURCE_TRACES
        steps = len(records)

    cost = round_cost(sum(float(getattr(record, "cost", 0.0) or 0.0) for record in records))
    duration_ms = int(sum(int(getattr(record, "duration_ms", 0) or 0) for record in records))
    iterations = int(state.get("iteration", 0) or 0)
    final_answer = str(state.get("final_answer") or "")

    if score is None:
        review_score = state.get("review_score")
        score = int(review_score) if isinstance(review_score, (int, float)) else None

    error = error_message
    if status != STATUS_DONE and not error:
        error = _abort_text(state)[:500] or None

    consistency = check_tool_consistency(records, events)
    non_retryable = error_code == "llm_not_retryable" or _state_reports_non_retryable(state)

    raw_summary: dict[str, Any] = {
        "review_score": state.get("review_score"),
        "review_result": state.get("review_result"),
        "node_end_events": _count_events(events, TASK_EVT_NODE_END),
        "traces_records": len(records),
        "events_total": len(events),
        "tool_calls_events": len(_events_to_tool_calls(events)[0]),
        "tool_calls_traces": len(_records_to_tool_calls(records)[0]),
    }
    meta: dict[str, Any] = {
        "db_path": str(db_path),
        "tool_source": tool_source,
        "consistency": consistency,
        "run_index": int(run_index),
        "error_code": error_code,
        "non_retryable": bool(non_retryable),
    }
    if not events_available:
        meta["warning"] = "task_events 不可用，工具序列回退旧 traces（tool_source=traces）"

    return TaskRun(
        task_id=task_id,
        final_answer=final_answer,
        status=status,
        steps=int(steps),
        iterations=iterations,
        tool_sequence=list(tool_sequence),
        tool_calls=len(tool_sequence),
        tool_failures=int(tool_failures),
        cost=cost,
        duration_ms=duration_ms,
        channel=channel,
        tool_source=tool_source,
        event_range=_event_range(events),
        error=error,
        raw_summary=raw_summary,
        wall_ms=int(wall_ms),
        score=score,
        grade=grade,
        meta=meta,
    )


def to_taskrun_api(
    view: Mapping[str, Any],
    events: Sequence[Any],
    *,
    base_url: str = "",
    wall_ms: int = 0,
    channel: str = CHANNEL_API,
    run_index: int = 0,
) -> TaskRun:
    """把 HTTP 通道的原始数据（``TaskView`` + ``/trace`` 事件）归一成 :class:`TaskRun`。

    ``/trace`` 是 ``task_events`` 的读取侧，故有事件时 ``tool_source=task_events``；
    老任务（``events_available=false``）只能拿到 ``tasks.tool_calls``（traces 派生的
    计数，无序列），此时 ``tool_source=traces``、``tool_sequence=[]``，
    真实计数落在 ``raw_summary["tasks_tool_calls"]`` 并留警告（契约要求
    ``tool_calls == len(tool_sequence)``，不能凭空造序列）。
    """
    view = dict(view or {})
    task_id = str(view.get("task_id") or "")
    status = _normalize_status(view.get("status"))
    events_available = bool(events)

    if events_available:
        tool_sequence, tool_failures = _events_to_tool_calls(events)
        tool_source = TOOL_SOURCE_TASK_EVENTS
        steps = _count_events(events, TASK_EVT_NODE_END)
    else:
        tool_sequence, tool_failures = [], int(view.get("tool_failures") or 0)
        tool_source = TOOL_SOURCE_TRACES
        steps = 0

    tasks_tool_calls = int(view.get("tool_calls") or 0)
    error: str | None = None
    err = view.get("error")
    if isinstance(err, Mapping) and err:
        error = f"{err.get('code') or 'error'}: {err.get('message') or ''}".strip(": ")
    elif status not in (STATUS_DONE,):
        error = f"status={status}"

    score = view.get("score")
    raw_summary: dict[str, Any] = {
        "iterations": int(view.get("iterations") or 0),
        "cost": float(view.get("cost") or 0.0),
        "duration_ms": int(view.get("duration_ms") or 0),
        "tool_calls": tasks_tool_calls,
        "tool_failures": int(view.get("tool_failures") or 0),
        "difficulty": view.get("difficulty"),
        "events_total": len(events),
    }
    meta: dict[str, Any] = {
        "base_url": str(base_url),
        "tool_source": tool_source,
        "events_available": events_available,
        "tasks_tool_calls": tasks_tool_calls,
        "run_index": int(run_index),
    }
    if events_available and tasks_tool_calls != len(tool_sequence):
        meta["tool_calls_mismatch"] = {
            "tasks_tool_calls": tasks_tool_calls,
            "event_tool_calls": len(tool_sequence),
        }
        logger.warning(
            "HTTP 通道口径分歧：tasks.tool_calls=%d 与 /trace 的 tool_call 事件数=%d 不一致",
            tasks_tool_calls,
            len(tool_sequence),
        )
    if not events_available:
        meta["warning"] = "events_available=false，工具序列不可得（仅回退 tasks.tool_calls 计数）"

    return TaskRun(
        task_id=task_id,
        final_answer=str(view.get("final_answer") or ""),
        status=status,
        steps=int(steps),
        iterations=int(view.get("iterations") or 0),
        tool_sequence=list(tool_sequence),
        tool_calls=len(tool_sequence),
        tool_failures=int(tool_failures),
        cost=round_cost(float(view.get("cost") or 0.0)),
        duration_ms=int(view.get("duration_ms") or 0),
        channel=channel,
        tool_source=tool_source,
        event_range=_event_range(events),
        error=error,
        raw_summary=raw_summary,
        wall_ms=int(wall_ms),
        score=int(score) if isinstance(score, (int, float)) else None,
        grade=str(view.get("grade")) if view.get("grade") is not None else None,
        meta=meta,
    )


def _failed_taskrun(
    task_id: str,
    error: str,
    *,
    channel: str,
    db_path: str = "",
    run_index: int = 0,
) -> TaskRun:
    """构造一条「通道级失败」的 :class:`TaskRun`（单任务失败不中断整批）。"""
    return TaskRun(
        task_id=task_id,
        final_answer="",
        status=STATUS_FAILED,
        steps=0,
        iterations=0,
        tool_sequence=[],
        tool_calls=0,
        tool_failures=0,
        cost=0.0,
        duration_ms=0,
        channel=channel,
        tool_source=TOOL_SOURCE_TRACES,
        event_range=None,
        error=error,
        raw_summary={},
        wall_ms=0,
        score=None,
        grade=None,
        meta={"db_path": str(db_path), "harness_failure": True, "run_index": int(run_index)},
    )


# --------------------------------------------------------------------------- #
# 执行器：直调 + HTTP
# --------------------------------------------------------------------------- #
ProgressCallback = Callable[[int, EvalTask, TaskRun], None]


class EvalHarness:
    """评测执行器（设计 §3.5 ``EvalHarness``）。

    Args:
        taskset: 已加载并校验的任务集。
        channel: ``direct``（默认）或 ``api``。
        repeat: 每任务重复采样次数（聚合 / 均值职责在 T02/T04，本模块只产出 N 个 run）。
        cost_cap_cny: 累计成本上限（CNY）；超过则中止剩余任务并置 ``aborted``。
        settings: 全局配置；默认取单例。
        llm: 注入的 LLM 适配器（测试传 ``MockLLMAdapter``，零 token）；默认每任务新建真实 adapter。
        isolate: 是否使用隔离库副本（**默认 True**；直调下强烈建议保持）。
        source_db_path: 隔离副本的源库（默认取 ``settings.db_path``，即运行库）。
        eval_db_dir: 隔离副本落盘目录（默认源库同级的 ``eval/``）。
        use_tools: 是否装配内置工具（默认取 ``taskset.defaults.use_tools``）。
        inject_knowledge: 是否为直调注入绑到隔离库的 ``KnowledgeService``（默认 False，省去加载开销）。
        run_judge: 是否跑 LLM Judge（默认取 ``taskset.defaults.run_judge``）。
        api_base_url: HTTP 通道服务地址。
    """

    def __init__(
        self,
        taskset: EvalTaskSet,
        *,
        channel: str = CHANNEL_DIRECT,
        repeat: int = 1,
        cost_cap_cny: float | None = None,
        settings: Settings | None = None,
        llm: LLMAdapter | None = None,
        isolate: bool = True,
        source_db_path: Path | str | None = None,
        eval_db_dir: Path | str | None = None,
        use_tools: bool | None = None,
        inject_knowledge: bool = False,
        run_judge: bool | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
        api_timeout_s: float = DEFAULT_API_TIMEOUT_S,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
        api_token: str | None = None,
        on_run: ProgressCallback | None = None,
    ) -> None:
        if channel not in CHANNELS:
            raise HarnessError(f"非法执行通道：{channel}（合法值：{list(CHANNELS)}）")
        if repeat < 1:
            raise HarnessError(f"repeat 必须 ≥ 1，实际 {repeat}")
        if cost_cap_cny is not None and cost_cap_cny < 0:
            raise HarnessError(f"cost_cap_cny 不能为负，实际 {cost_cap_cny}")

        self.taskset = taskset
        self.channel = channel
        self.repeat = int(repeat)
        self.cost_cap_cny = cost_cap_cny
        self._settings = settings or get_settings()
        self._llm = llm
        self._isolate = bool(isolate)
        self._source_db_path = Path(source_db_path) if source_db_path is not None else None
        self._eval_db_dir = Path(eval_db_dir) if eval_db_dir is not None else None
        self._use_tools = use_tools
        self._inject_knowledge = bool(inject_knowledge)
        self._run_judge = run_judge
        self.api_base_url = str(api_base_url).rstrip("/")
        self.api_timeout_s = float(api_timeout_s)
        self.poll_interval_s = float(poll_interval_s)
        self.http_timeout_s = float(http_timeout_s)
        self._api_token = api_token
        self._on_run = on_run

        self._database: Database | None = None
        self._trace_store: TraceStore | None = None
        self._db_path: Path | None = None
        self._owns_db = False
        self._knowledge_service: Any | None = None

    # -------------------------------------------------- 生命周期 / 隔离库 --
    @property
    def db_path(self) -> Path | None:
        """本次运行实际使用的 SQLite 库路径（隔离副本；未初始化时为 ``None``）。"""
        return self._db_path

    @property
    def database(self) -> Database | None:
        """直调通道使用的 ``Database``（未初始化时为 ``None``）。"""
        return self._database

    def _make_dest(self, source: Path) -> Path:
        """生成隔离副本路径：``<源库目录>/eval/eval_<时间>_<pid>_<hex>.db``。"""
        directory = self._eval_db_dir or (source.parent / EVAL_DB_DIRNAME)
        name = f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{uuid.uuid4().hex[:6]}.db"
        return directory / name

    def _ensure_isolation(self) -> None:
        """（幂等）准备直调通道的隔离库副本与两个 sink。"""
        if self._database is not None:
            return
        settings = self._settings
        source = self._source_db_path or settings.db_path
        if self._isolate:
            if source is None or not Path(source).is_file():
                raise HarnessError(
                    "隔离模式需要可用的 SQLite 源库（须含 RAG 索引）；未找到："
                    f"{source}。请用 source_db_path 指定，或确认 data/trinity.db 存在。"
                )
            dest = self._make_dest(Path(source))
            # ★ 必须是「现有库的副本」，绝不能是空库（否则 knowledge_search 查不到东西）
            copy_sqlite_database(source, dest)
            db_url = f"sqlite:///{dest.as_posix()}"
            self._db_path = dest
            self._owns_db = True
        else:
            db_url = settings.resolved_db_url
            self._db_path = settings.db_path
            self._owns_db = False
            logger.warning(
                "EvalHarness 未启用隔离：事件 / 任务将写入 %s（可能污染现有库）", db_url
            )
        self._database = Database(db_url, settings=settings)
        self._database.init_db()
        self._trace_store = TraceStore(db_path=self._db_path)
        if self._inject_knowledge:
            try:
                self._knowledge_service = self._build_knowledge_service()
            except Exception:  # noqa: BLE001 - 注入失败降级，不阻断评测
                logger.warning("为直调通道注入知识库服务失败（检索工具降级）", exc_info=True)

    def _build_knowledge_service(self) -> Any:
        """构造绑到隔离库的 ``KnowledgeService``（使检索也跑在副本上）。"""
        from rag.service import KnowledgeService  # noqa: PLC0415 - 懒加载纪律

        service = KnowledgeService(settings=self._settings, database=self._database)
        service.initialize()
        return service

    def _knowledge_ready(self) -> bool:
        """前置条件：知识库是否有 ``ready`` 文档（空库 → 检索类任务应 skipped）。"""
        if self._database is None:
            return False
        try:
            return len(self._database.list_documents(statuses=[DOC_READY])) > 0
        except Exception as exc:  # noqa: BLE001 - 查不通按未就绪处理
            logger.warning("知识库就绪检查失败，按未就绪处理：%s", exc)
            return False

    def __enter__(self) -> EvalHarness:
        if self.channel == CHANNEL_DIRECT:
            self._ensure_isolation()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False

    def close(self, *, delete_db: bool | None = None) -> None:
        """释放连接，并（默认）删除隔离副本。"""
        remove = self._owns_db if delete_db is None else bool(delete_db)
        trace_store, database = self._trace_store, self._database
        self._trace_store = None
        self._database = None
        self._knowledge_service = None
        if trace_store is not None:
            try:
                trace_store.close()
            except Exception:  # noqa: BLE001
                logger.warning("关闭 TraceStore 失败", exc_info=True)
        if database is not None:
            try:
                database.dispose()
            except Exception:  # noqa: BLE001
                logger.warning("释放 Database 失败", exc_info=True)
        if remove and self._db_path is not None:
            _unlink_db(self._db_path)
        self._db_path = None

    # ---------------------------------------------------------- 运行入口 --
    def _task_id_for(self, task: EvalTask, repeat_index: int, run_index: int) -> str:
        """为一次运行生成唯一 task_id（满足 HTTP 的 ``^[A-Za-z0-9_-]{1,64}$``）。"""
        return f"eval-{_slug(task.id)}-{repeat_index}-{uuid.uuid4().hex[:8]}"

    def run_all(self) -> SuiteReport:
        """跑完整个任务集（串行、含前置检查 / 超时 / 成本护栏 / 重复采样）。"""
        started = time.perf_counter()
        runs: list[TaskRun] = []
        skipped: list[SkippedTask] = []
        aborted = False
        abort_reason = ""
        run_index = 0
        stop = False

        if self.channel == CHANNEL_DIRECT:
            self._ensure_isolation()
            ready = self._knowledge_ready()
        else:
            ready = True  # HTTP 通道不持有本地库，前置检查交由运行中的服务

        for task in list(self.taskset.tasks):
            if stop:
                break
            if task.requires_ready_docs and not ready:
                skipped.append(
                    SkippedTask(task.id, "知识库未就绪（requires_ready_docs=true 且无 ready 文档）")
                )
                continue
            for repeat_index in range(self.repeat):
                run_index += 1
                task_id = self._task_id_for(task, repeat_index, run_index)
                try:
                    run = self._run_one(task, repeat_index, run_index, task_id)
                except LLMNotRetryableError as exc:  # 兜住未在节点内被收敛的同类异常
                    runs.append(
                        _failed_taskrun(
                            task_id, str(exc), channel=self.channel,
                            db_path=str(self._db_path or ""), run_index=run_index,
                        )
                    )
                    aborted = True
                    abort_reason = _abort_reason_for(str(exc))
                    stop = True
                    break
                except Exception as exc:  # noqa: BLE001 - 单任务失败不中断整批
                    logger.exception("评测任务执行失败 task_id=%s", task_id)
                    runs.append(
                        _failed_taskrun(
                            task_id, f"{type(exc).__name__}: {exc}", channel=self.channel,
                            db_path=str(self._db_path or ""), run_index=run_index,
                        )
                    )
                    continue

                runs.append(run)
                if self._on_run is not None:
                    try:
                        self._on_run(run_index, task, run)
                    except Exception:  # noqa: BLE001 - 回调异常不影响整批
                        logger.warning("on_run 回调异常（已忽略）", exc_info=True)

                # LLM「重试无用」错误 → 立即中止整批（对齐 batch.py：仅当尚无成功样本时）
                if run.meta.get("non_retryable") and not any(item.is_done() for item in runs):
                    aborted = True
                    abort_reason = _abort_reason_for(run.error or "")
                    stop = True
                    break

                # 成本护栏：超限立即停下剩余任务（设计 §5.2）
                if self.cost_cap_cny is not None:
                    total = round_cost(sum(item.cost for item in runs))
                    if total > self.cost_cap_cny:
                        aborted = True
                        abort_reason = (
                            f"成本护栏触发：累计 {total} 元 > 上限 {self.cost_cap_cny} 元"
                        )
                        stop = True
                        break

        wall_ms = int((time.perf_counter() - started) * 1000)
        report = SuiteReport(
            channel=self.channel,
            repeat=self.repeat,
            runs=runs,
            skipped=skipped,
            aborted=aborted,
            abort_reason=abort_reason,
            cost_total=round_cost(sum(item.cost for item in runs)),
            wall_ms=wall_ms,
            db_path=str(self._db_path or ""),
            taskset=self.taskset.summary(),
        )
        logger.info(
            "套件执行完成 channel=%s runs=%d skipped=%d aborted=%s cost=%.6f wall=%dms db=%s",
            self.channel,
            len(runs),
            len(skipped),
            aborted,
            report.cost_total,
            wall_ms,
            report.db_path,
        )
        return report

    def run_task(self, task: EvalTask) -> list[TaskRun]:
        """只跑单条任务（``repeat`` 次），不做前置检查 / 成本护栏（供测试与调试）。"""
        if self.channel == CHANNEL_DIRECT:
            self._ensure_isolation()
        results: list[TaskRun] = []
        for repeat_index in range(self.repeat):
            run_index = repeat_index + 1
            task_id = self._task_id_for(task, repeat_index, run_index)
            try:
                results.append(self._run_one(task, repeat_index, run_index, task_id))
            except Exception as exc:  # noqa: BLE001
                results.append(
                    _failed_taskrun(
                        task_id, f"{type(exc).__name__}: {exc}", channel=self.channel,
                        db_path=str(self._db_path or ""), run_index=run_index,
                    )
                )
        return results

    def _run_one(self, task: EvalTask, repeat_index: int, run_index: int, task_id: str) -> TaskRun:
        if self.channel == CHANNEL_DIRECT:
            return self._run_direct(task, run_index, task_id)
        return self._run_via_api(task, run_index, task_id)

    # ---------------------------------------------------------- 直调通道 --
    def _build_direct_runner(self) -> WorkflowRunner:
        """仿 ``batch.py`` 装配编排器，但**额外挂 ``event_sink``**（本任务的核心修复）。"""
        settings = self._settings
        use_tools = (
            self._use_tools
            if self._use_tools is not None
            else bool(self.taskset.defaults.use_tools)
        )
        registry: ToolRegistry | None = None
        if use_tools:
            registry = load_builtin_tools(ToolRegistry(settings=settings, enable_hitl=False))
            if self._inject_knowledge and self._knowledge_service is not None:
                from core.tools.builtin import knowledge_search  # noqa: PLC0415

                knowledge_search.set_knowledge_service(self._knowledge_service)
        config = WorkflowConfig(
            max_iterations=self.taskset.defaults.max_iterations,
            review_threshold=self.taskset.defaults.review_threshold,
        )
        llm = self._llm if self._llm is not None else LLMAdapter(settings=settings)
        ctx = NodeContext.create(
            llm=llm,
            config=config,
            settings=settings,
            trace_sink=self._trace_store,          # ← 旧 traces（TaskOutcome 汇总用）
            tool_invoker=registry,
            event_sink=DatabaseEventSink(self._database),  # ← 新 task_events（本任务补上）
        )
        return WorkflowRunner(ctx)

    def _run_direct(self, task: EvalTask, run_index: int, task_id: str) -> TaskRun:
        runner = self._build_direct_runner()
        timeout_s = float(self.taskset.defaults.timeout_s)
        state = _call_with_timeout(lambda: runner.run(task.prompt, task_id), timeout_s)
        records = self._trace_store.for_task(task_id)
        events = self._fetch_all_events(task_id)
        score, grade = self._maybe_judge(task, state, records)
        return to_taskrun_direct(
            state,
            records,
            events,
            db_path=str(self._db_path or ""),
            channel=CHANNEL_DIRECT,
            score=score,
            grade=grade,
            run_index=run_index,
        )

    def _fetch_all_events(self, task_id: str) -> list[Any]:
        """按 ``event_seq`` 游标分页拉取某任务的全部事件。"""
        collected: list[Any] = []
        cursor = 0
        for _ in range(200):  # 防死循环上界
            page = self._database.list_events(
                task_id, after_seq=cursor, limit=TRACE_MAX_LIMIT
            )
            if not page:
                break
            collected.extend(page)
            if len(page) < TRACE_MAX_LIMIT:
                break
            cursor = int(page[-1].event_seq)
        return collected

    def _maybe_judge(
        self, task: EvalTask, state: Mapping[str, Any], records: Sequence[TraceRecord]
    ) -> tuple[int | None, str | None]:
        """按需跑一次 LLM Judge（默认关闭省成本）；失败只记 WARNING。"""
        run_judge = (
            self._run_judge
            if self._run_judge is not None
            else bool(self.taskset.defaults.run_judge)
        )
        if not run_judge:
            return None, None
        try:
            from evaluation.judge import LLMJudge  # noqa: PLC0415

            judge = (
                LLMJudge(llm=self._llm, settings=self._settings)
                if self._llm is not None
                else LLMJudge(settings=self._settings)
            )
            result = judge.evaluate(
                task=task.prompt,
                criteria=[task.prompt],
                final_answer=str(state.get("final_answer") or ""),
                task_id=str(state.get("task_id") or ""),
                records=records,
                status=str(state.get("status") or "unknown"),
                iterations=int(state.get("iteration", 0) or 0),
            )
            return int(result.score), str(result.grade)
        except Exception as exc:  # noqa: BLE001 - judge 是旁路
            logger.warning("judge 评测失败（不影响流程指标）：%s", exc)
            return None, None

    # ------------------------------------------------------------ HTTP 通道 --
    def _run_via_api(self, task: EvalTask, run_index: int, task_id: str) -> TaskRun:
        """``POST /tasks`` → 轮询到终态 → 拉 ``/trace`` → 归一化。"""
        import httpx  # noqa: PLC0415 - 仅 HTTP 通道需要

        headers = (
            {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        )
        payload: dict[str, Any] = {
            "task": task.prompt,
            "task_id": task_id,
            "max_iterations": self.taskset.defaults.max_iterations,
            "review_threshold": self.taskset.defaults.review_threshold,
            "use_tools": self.taskset.defaults.use_tools,
            "run_judge": bool(task.expect_judge),
            "difficulty": task.difficulty,
        }
        started = time.perf_counter()
        with httpx.Client(
            base_url=self.api_base_url,
            timeout=self.http_timeout_s,
            headers=headers,
        ) as client:
            submitted = client.post("/tasks", json=payload)
            if submitted.status_code >= 400:
                raise HarnessError(
                    f"POST /tasks 失败（HTTP {submitted.status_code}）：{submitted.text[:300]}"
                )
            accepted = submitted.json()
            real_id = str(accepted.get("task_id") or task_id)
            view = self._poll_terminal(client, real_id)
            events = self._fetch_events_http(client, real_id)
        wall_ms = int((time.perf_counter() - started) * 1000)
        return to_taskrun_api(
            view,
            events,
            base_url=self.api_base_url,
            wall_ms=wall_ms,
            channel=CHANNEL_API,
            run_index=run_index,
        )

    def _poll_terminal(self, client: Any, task_id: str) -> dict[str, Any]:
        """轮询 ``GET /tasks/{id}`` 直到进入终态，超时抛 :class:`HarnessTimeout`。"""
        deadline = time.perf_counter() + self.api_timeout_s
        last: dict[str, Any] = {}
        while time.perf_counter() < deadline:
            response = client.get(f"/tasks/{task_id}")
            if response.status_code >= 400:
                raise HarnessError(
                    f"GET /tasks/{task_id} 失败（HTTP {response.status_code}）：{response.text[:300]}"
                )
            last = dict(response.json())
            if last.get("status") in API_TERMINAL_STATUSES:
                return last
            time.sleep(self.poll_interval_s)
        raise HarnessTimeout(
            f"任务 {task_id} 在 {self.api_timeout_s:g}s 内未进入终态"
            f"（最后状态：{last.get('status', 'unknown')}）"
        )

    def _fetch_events_http(self, client: Any, task_id: str) -> list[dict[str, Any]]:
        """按 ``after_seq`` 游标拉取 ``/trace`` 的全部事件。"""
        collected: list[dict[str, Any]] = []
        cursor = 0
        for _ in range(200):  # 防死循环上界
            response = client.get(
                f"/tasks/{task_id}/trace",
                params={"after_seq": cursor, "limit": TRACE_MAX_LIMIT},
            )
            if response.status_code >= 400:
                raise HarnessError(
                    f"GET /tasks/{task_id}/trace 失败（HTTP {response.status_code}）："
                    f"{response.text[:300]}"
                )
            body = response.json()
            collected.extend(body.get("items") or [])
            if not body.get("has_more"):
                break
            cursor = int(body.get("next_after_seq") or 0)
        return collected


def _abort_reason_for(text: str) -> str:
    """给「重试无用」错误一句可执行提示。"""
    detail = (text or "LLM 调用失败且重试无用").strip()
    return f"{detail}；请检查 LLM_API_KEY / 账户余额后重试（重试无用错误会持续复现）"


__all__ = [
    "DEFAULT_API_BASE_URL",
    "DEFAULT_API_TIMEOUT_S",
    "DEFAULT_HTTP_TIMEOUT_S",
    "DEFAULT_POLL_INTERVAL_S",
    "EVAL_DB_DIRNAME",
    "EvalHarness",
    "HarnessError",
    "HarnessTimeout",
    "ProgressCallback",
    "SkippedTask",
    "SuiteReport",
    "check_tool_consistency",
    "copy_sqlite_database",
    "to_taskrun_api",
    "to_taskrun_direct",
]
