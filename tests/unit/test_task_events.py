"""P1-A 单测（U1–U7）：``task_events`` 表的数据层基础设施。

对应 ``docs/p1_trace_events_design.md`` §9.1 的 U1–U7。

不用 pytest 的 ``tmp_path``（本机沙箱对递归删除 fail-closed），数据库文件放在
项目内的 ``data/.test-scratch/``（已 gitignore），与 ``test_storage.py`` 同一约定。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from api.constants import TASK_EVT_LLM_CALL, TASK_EVT_NODE_END, TASK_EVT_TOOL_CALL
from config import PROJECT_ROOT
from core.events import EventRecord
from storage.db import Database
from storage.migrations import (
    TASK_EVENTS_INDEX_DDL,
    ensure_task_events_table,
)

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"

#: 设计文档 §3.2 规范 DDL 的期望列集合（顺序无关，只比集合）。
EXPECTED_COLUMNS = {
    "event_seq",
    "task_id",
    "event_type",
    "role",
    "step",
    "sub_step",
    "node",
    "thought",
    "tool_name",
    "arguments",
    "observation",
    "latency_ms",
    "tokens_in",
    "tokens_out",
    "cost",
    # 成本归因面板（docs/cost_attribution_plan_2026-09-25.md §10.2d/e）加的两列。
    # 上面 :115 是**集合全等**，所以加列必须同时改这里 —— 那个全等正是
    # 「schema 漂了没人知道」的守门人，别把它改成子集判断来绕过这条用例。
    "model",
    "price_multiplier",
    "status",
    "error_code",
    "error_message",
    "sse_seq",
    "created_at",
}


def _event(task_id: str, **overrides: object) -> dict[str, object]:
    """构造一条最小合法事件行（非工具事件）。"""
    row: dict[str, object] = {
        "task_id": task_id,
        "event_type": TASK_EVT_NODE_END,
        "role": "planner",
        "step": 0,
        "node": "planner",
        "thought": "拆解",
        "observation": "3 步",
        "status": "success",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def db_path() -> Path:
    """每个用例一个独立的 SQLite 文件路径（尚未建表）。"""
    return TEST_SCRATCH_ROOT / f"te-{uuid4().hex[:10]}.sqlite3"


@pytest.fixture()
def database(db_path: Path) -> Database:
    """初始化好的 Database 实例（``init_db`` 自动建 task_events）。"""
    instance = Database(f"sqlite:///{db_path.as_posix()}")
    instance.init_db()
    return instance


class TestEnsureTaskEventsTable:
    """U1：DDL 幂等与列结构。"""

    def test_u1_idempotent_and_columns(self, db_path: Path) -> None:
        """U1：连跑 3 次，第 2/3 次返回 []；列集合与设计一致。"""
        # 先建一个空库文件（ensure_task_events_table 只在文件存在时动作）
        sqlite3.connect(str(db_path)).close()

        first = ensure_task_events_table(db_path)
        assert "task_events" in first, "首次应创建 task_events"
        assert "idx_task_events_task_seq" in first
        assert "idx_task_events_task_role" in first

        second = ensure_task_events_table(db_path)
        third = ensure_task_events_table(db_path)
        assert second == [], f"第二次应幂等返回 []，实际 {second}"
        assert third == [], f"第三次应幂等返回 []，实际 {third}"

        # 校验列集合
        conn = sqlite3.connect(str(db_path))
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(task_events)")}
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='task_events'"
                )
            }
        finally:
            conn.close()
        assert columns == EXPECTED_COLUMNS
        for ddl in TASK_EVENTS_INDEX_DDL:
            name = ddl.split("IF NOT EXISTS", 1)[1].split("ON", 1)[0].strip()
            assert name in indexes

    def test_u1_none_db_path_skips(self) -> None:
        """U1 附加：非 SQLite（db_path=None）返回 []，不抛。"""
        assert ensure_task_events_table(None) == []


class TestEventSeq:
    """U2 / U3：全局单调与不复用。"""

    def test_u2_global_monotonic_across_tasks(self, database: Database) -> None:
        """U2：交替写 task-A / task-B 各 5 条，event_seq 严格递增且不重复。"""
        from sqlalchemy import select

        from storage.models import TaskEventRecord

        for index in range(5):
            database.record_event(**_event("A", step=index))
            database.record_event(**_event("B", step=index))
        with database.session() as handle:
            rows = list(
                handle.scalars(
                    select(TaskEventRecord.event_seq).order_by(
                        TaskEventRecord.event_seq
                    )
                )
            )
        seqs = [int(value) for value in rows]
        assert len(seqs) == 10
        assert len(set(seqs)) == 10, "event_seq 不得跨任务重复"
        assert seqs == sorted(seqs), "event_seq 必须严格递增"

    def test_u3_seq_not_reused_after_delete(self, database: Database) -> None:
        """U3：写 3 条 → 删全部 → 再写 1 条，新 seq 大于已删最大值。"""
        for index in range(3):
            database.record_event(**_event("A", step=index))
        seqs = [
            database.record_event(**_event("A", step=index)) for index in range(3, 6)
        ]
        max_before = max(int(seq) for seq in seqs if seq is not None)

        # 删全部事件（用 ORM 直接 delete，模拟「删除最大行」）
        with database.session() as handle:
            from sqlalchemy import delete

            from storage.models import TaskEventRecord

            handle.execute(delete(TaskEventRecord))

        new_seq = database.record_event(**_event("A", step=99))
        assert new_seq is not None
        assert new_seq > max_before, (
            f"AUTOINCREMENT 应保证不复用 id：新 {new_seq} 必须 > 已删最大 {max_before}"
        )


class TestStepSemantics:
    """U4：step 归类。"""

    def test_u4_step_grouping_first_round(self, database: Database) -> None:
        """U4：第一轮 planner/executor(3 子步)/reviewer 的 step 全为 0。"""
        database.record_event(**_event("T", role="planner", node="planner", step=0))
        for sub in range(3):
            database.record_event(
                **_event(
                    "T",
                    event_type=TASK_EVT_LLM_CALL,
                    role="executor",
                    node="executor",
                    step=0,
                    sub_step=sub,
                )
            )
        database.record_event(**_event("T", role="reviewer", node="reviewer", step=0))
        events = database.list_events("T", limit=100)
        assert {ev.role for ev in events} == {"planner", "executor", "reviewer"}
        assert all(ev.step == 0 for ev in events)
        subs = sorted(ev.sub_step for ev in events if ev.role == "executor")
        assert subs == [0, 1, 2]

    def test_u4_step_grouping_second_round(self, database: Database) -> None:
        """U4：第二轮迭代时 executor/reviewer 的 step 全为 1。"""
        for step in (0, 1):
            database.record_event(
                **_event("T", role="executor", node="executor", step=step, sub_step=0)
            )
            database.record_event(
                **_event("T", role="reviewer", node="reviewer", step=step)
            )
        events = database.list_events("T", limit=100)
        assert [ev.step for ev in events] == [0, 0, 1, 1]


class TestNullSemantics:
    """U5：NULL 语义（禁止 arguments 默认 '{}'）。"""

    def test_u5_non_tool_event_nulls(self, database: Database) -> None:
        """U5：非工具事件的 tool_name/arguments 为 NULL；observation 为 ''。"""
        from sqlalchemy import select

        from storage.models import TaskEventRecord

        database.record_event(**_event("T", observation=""))
        with database.session() as handle:
            row = handle.execute(
                select(
                    TaskEventRecord.tool_name,
                    TaskEventRecord.arguments,
                    TaskEventRecord.observation,
                )
            ).one()
        tool_name, arguments, observation = row
        assert tool_name is None
        assert arguments is None, "arguments 必须是 NULL，不允许 '{}'（设计文档 §3.4）"
        assert observation == ""

    def test_u5_tool_event_arguments_is_json(self, database: Database) -> None:
        """U5 附加：工具事件的 arguments 落成 JSON 串（字典 → 串）。"""
        from sqlalchemy import select

        from storage.models import TaskEventRecord

        record = EventRecord(
            task_id="T",
            event_type=TASK_EVT_TOOL_CALL,
            role="executor",
            node="executor",
            step=0,
            sub_step=1,
            tool_name="calculator",
            arguments={"expression": "1+1"},
            observation="2",
        )
        seq = database.record_event(**record.to_row())
        assert seq is not None
        with database.session() as handle:
            row = handle.execute(
                select(TaskEventRecord.tool_name, TaskEventRecord.arguments)
            ).one()
        assert row[0] == "calculator"
        assert row[1] == '{"expression": "1+1"}'

    def test_u5_event_record_none_arguments_stays_none(self) -> None:
        """U5 附加：EventRecord.to_row() 对 None 参数必须保持 None。"""
        record = EventRecord(task_id="T", event_type=TASK_EVT_NODE_END, step=0)
        assert record.to_row()["arguments"] is None


class TestRecordEventFailureIsolation:
    """U6：record_event 失败不抛。"""

    def test_u6_swallow_sqlalchemy_error(
        self, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """U6：让 INSERT 抛 SQLAlchemyError，record_event 返回 None 且不抛。"""
        from sqlalchemy.orm import Session

        def _boom_add(self: Session, *args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("boom-insert")

        monkeypatch.setattr(Session, "add", _boom_add)
        result = database.record_event(**_event("T"))
        assert result is None, "落盘失败必须返回 None 而不是抛异常"

    def test_u6_reject_missing_ids(self, database: Database) -> None:
        """U6 附加：缺 task_id/event_type 时返回 None，不抛。"""
        assert database.record_event(event_type=TASK_EVT_NODE_END) is None
        assert database.record_event(task_id="T") is None


class TestEmptyDegradation:
    """U7：老数据降级。"""

    def test_u7_empty_table(self, database: Database) -> None:
        """U7：空表的 list_events 返回 []、count_events 返回 0，无异常。"""
        assert database.list_events("nope") == []
        assert database.count_events("nope") == 0
        assert database.max_event_seq("nope") == 0

    def test_u7_clear_all_purges_events(self, database: Database) -> None:
        """U7 附加（X3）：clear_all() 必须连带清空 task_events。"""
        database.save_task(task_id="T", task="x")
        database.record_event(**_event("T"))
        assert database.count_events("T") == 1
        database.clear_all()
        assert database.count_events("T") == 0, "clear_all 必须连带清 task_events（X3）"

    def test_u7_delete_task_cascades_events(self, database: Database) -> None:
        """U7 附加：delete_task 连带删该任务事件（应用层无外键的补偿）。"""
        database.save_task(task_id="T", task="x")
        database.record_event(**_event("T"))
        assert database.delete_task("T") is True
        assert database.count_events("T") == 0


class TestCursorPagination:
    """读取游标：list_events 用 event_seq 游标而非 OFFSET。"""

    def test_cursor_pagination(self, database: Database) -> None:
        seen: list[int] = []
        for index in range(10):
            seq = database.record_event(**_event("T", step=index))
            assert seq is not None
        cursor = 0
        while True:
            page = database.list_events("T", after_seq=cursor, limit=3)
            if not page:
                break
            seen.extend(int(ev.event_seq) for ev in page)
            cursor = int(page[-1].event_seq)
        assert seen == sorted(seen)
        assert len(seen) == 10


__all__ = ["EXPECTED_COLUMNS"]
