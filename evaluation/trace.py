"""Trace 存储：内存视图 + SQLite 全量落盘。

三条设计约束：

1. **写入路径零 LLM**：只做序列化与落盘，所以可以全量记录、不做采样。
2. **内存只留最近 N 条**：UI 回放要快，但进程不能无限涨内存；查历史走 SQLite。
3. **自己管一张表，不用 SQLAlchemy**：阶段 4 的 ``storage`` 层会用 SQLAlchemy 管业务表
   （任务、Agent、评估结果），trace 表由本模块独占，避免两套 ORM 抢同一张表。

表结构自愈（``CREATE TABLE IF NOT EXISTS``），不需要迁移工具。

关于 WAL：本模块持有的是**独立于 SQLAlchemy 的第二条 sqlite3 连接**，两条连接
并发写同一个库文件。SQLite 的 ``journal_mode`` 与 ``busy_timeout`` 是**连接级**
设置，因此这里必须和 ``storage/db.py`` 一样设一遍，只改一边等于没改
（设计文档 §8.6 把它列为「最容易踩的 5 个坑」之一）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from api.constants import SQLITE_BUSY_TIMEOUT_MS
from config import PROJECT_ROOT, get_settings
from core.agent.base import TraceRecord

logger = logging.getLogger(__name__)

#: 内存里保留的最近条数
DEFAULT_MEMORY_LIMIT = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id    TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    step        INTEGER NOT NULL,
    role        TEXT NOT NULL,
    input       TEXT NOT NULL,
    output      TEXT NOT NULL,
    tool_calls  TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    duration_ms INTEGER NOT NULL,
    status      TEXT NOT NULL,
    token_in    INTEGER NOT NULL DEFAULT 0,
    token_out   INTEGER NOT NULL DEFAULT 0,
    cost        REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_traces_task ON traces(task_id);
CREATE INDEX IF NOT EXISTS idx_traces_role ON traces(role);
CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(timestamp);
"""

_COLUMNS = (
    "trace_id",
    "task_id",
    "step",
    "role",
    "input",
    "output",
    "tool_calls",
    "timestamp",
    "duration_ms",
    "status",
    "token_in",
    "token_out",
    "cost",
)


def default_db_path() -> Path:
    """默认落盘位置：优先用 ``DB_URL`` 指向的 sqlite 文件，否则 ``data/traces.db``。"""
    settings = get_settings()
    if settings.db_path is not None:
        return settings.db_path
    return PROJECT_ROOT / "data" / "traces.db"


class TraceStore:
    """把埋点同时写进内存队列与 SQLite。

    它本身就是一个 ``TraceSink``（实现 ``__call__``），可以直接塞给
    ``NodeContext(trace_sink=...)``。
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        memory_limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory: deque[TraceRecord] = deque(maxlen=memory_limit)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._apply_pragmas()
            self._conn.commit()
        logger.debug("TraceStore 就绪：%s", self.db_path)

    def _apply_pragmas(self) -> None:
        """给本连接设 WAL / busy_timeout / synchronous（与 SQLAlchemy 侧保持一致）。

        刻意与 ``_SCHEMA`` 分开执行：``executescript`` 会先隐式 COMMIT 再跑脚本，
        把 PRAGMA 混进去容易受事务边界影响；单独 ``execute`` 语义清晰且失败可控。
        """
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as exc:  # pragma: no cover - 只在极端环境下触发
            logger.warning("TraceStore 设置 SQLite PRAGMA 失败（降级为默认模式）：%s", exc)

    # ------------------------------------------------------------ 写入 --
    def __call__(self, record: TraceRecord) -> None:
        """满足 ``TraceSink`` 协议：写内存 + 落库。"""
        self.add(record)

    def add(self, record: TraceRecord) -> None:
        """写入一条埋点。落库失败只记日志，绝不打断编排。"""
        self._memory.append(record)
        try:
            with self._lock:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO traces ({', '.join(_COLUMNS)}) "
                    f"VALUES ({', '.join('?' * len(_COLUMNS))})",
                    (
                        record.trace_id,
                        record.task_id,
                        record.step,
                        record.role,
                        record.input,
                        record.output,
                        json.dumps(record.tool_calls, ensure_ascii=False),
                        record.timestamp,
                        record.duration_ms,
                        record.status,
                        record.token_in,
                        record.token_out,
                        record.cost,
                    ),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("埋点落库失败（不影响编排）：%s", exc)

    def add_many(self, records: Iterable[TraceRecord]) -> None:
        """批量写入。"""
        for record in records:
            self.add(record)

    # ------------------------------------------------------------ 读取 --
    @property
    def memory(self) -> list[TraceRecord]:
        """内存视图（最近 N 条的副本）。"""
        return list(self._memory)

    def for_task(self, task_id: str) -> list[TraceRecord]:
        """取某个任务的全部埋点，按 (step, timestamp) 排序。

        内存里能凑齐就用手里的，凑不齐再查库。
        """
        from_memory = [record for record in self._memory if record.task_id == task_id]
        if len(from_memory) >= self.count_task(task_id):
            return _sorted(from_memory)
        return _sorted(self.query(task_id=task_id, limit=10_000))

    def query(
        self,
        *,
        task_id: str | None = None,
        role: str | None = None,
        limit: int = 200,
    ) -> list[TraceRecord]:
        """按条件查历史埋点（时间倒序取最近 ``limit`` 条）。"""
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if role is not None:
            clauses.append("role = ?")
            params.append(role)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM traces{where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def count(self) -> int:
        """埋点总条数。"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM traces").fetchone()
        return int(row["n"]) if row else 0

    def count_task(self, task_id: str) -> int:
        """某个任务的埋点条数。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM traces WHERE task_id = ?", (task_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    def distinct_tasks(self, limit: int = 100) -> list[str]:
        """最近出现过的任务 id（按最后一条埋点时间倒序）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id, MAX(timestamp) AS ts FROM traces GROUP BY task_id "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(row["task_id"]) for row in rows]

    def aggregate(self, task_id: str | None = None) -> dict[str, Any]:
        """汇总 token、成本、耗时、成功率。"""
        where = " WHERE task_id = ?" if task_id else ""
        params = (task_id,) if task_id else ()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS records, "
                "COALESCE(SUM(token_in), 0) AS token_in, "
                "COALESCE(SUM(token_out), 0) AS token_out, "
                "COALESCE(SUM(cost), 0) AS cost, "
                "COALESCE(SUM(duration_ms), 0) AS duration_ms, "
                "COALESCE(SUM(status != 'success'), 0) AS not_success "
                f"FROM traces{where}",
                params,
            ).fetchone()
        if row is None:
            return {
                "records": 0,
                "token_in": 0,
                "token_out": 0,
                "cost": 0.0,
                "duration_ms": 0,
                "not_success": 0,
            }
        return {
            "records": int(row["records"]),
            "token_in": int(row["token_in"]),
            "token_out": int(row["token_out"]),
            "cost": round(float(row["cost"]), 6),
            "duration_ms": int(row["duration_ms"]),
            "not_success": int(row["not_success"]),
        }

    # ------------------------------------------------------------ 维护 --
    def clear(self) -> None:
        """清空本表（测试与「重新开始」用；只删 traces，不碰别的表）。"""
        with self._lock:
            self._conn.execute("DELETE FROM traces")
            self._conn.commit()
        self._memory.clear()

    def close(self) -> None:
        """关闭连接。"""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> TraceStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _sorted(records: Iterable[TraceRecord]) -> list[TraceRecord]:
    """按 (step, timestamp) 升序，还原执行顺序。"""
    return sorted(records, key=lambda record: (record.step, record.timestamp))


def _row_to_record(row: sqlite3.Row) -> TraceRecord:
    """SQLite 行 → TraceRecord。"""
    try:
        tool_calls: list[dict[str, Any]] = json.loads(row["tool_calls"])
    except (TypeError, json.JSONDecodeError):
        tool_calls = []
    return TraceRecord(
        trace_id=str(row["trace_id"]),
        task_id=str(row["task_id"]),
        step=int(row["step"]),
        role=str(row["role"]),  # type: ignore[arg-type]
        input=str(row["input"]),
        output=str(row["output"]),
        tool_calls=tool_calls,
        timestamp=float(row["timestamp"]),
        duration_ms=int(row["duration_ms"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        token_in=int(row["token_in"]),
        token_out=int(row["token_out"]),
        cost=float(row["cost"]),
    )


__all__ = ["DEFAULT_MEMORY_LIMIT", "TraceStore", "default_db_path"]
