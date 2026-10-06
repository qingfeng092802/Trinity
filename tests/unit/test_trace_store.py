"""阶段 3 单测（一）：Trace 存储的内存 + SQLite 双写。

不用 pytest 的 ``tmp_path``：本机沙箱对递归删除 fail-closed，测试自管
``data/.test-scratch/``（已 gitignore）且不做清理。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from config import PROJECT_ROOT
from core.agent.base import TraceRecord
from evaluation.trace import TraceStore, default_db_path

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


def make_record(
    *,
    task_id: str = "t-1",
    role: str = "planner",
    step: int = 0,
    **overrides: object,
) -> TraceRecord:
    """造一条埋点，字段齐全。"""
    base: dict[str, object] = {
        "trace_id": f"{task_id}-{role}-{step}",
        "task_id": task_id,
        "step": step,
        "role": role,
        "input": f"{role} 输入",
        "output": f"{role} 输出",
        "tool_calls": [],
        "timestamp": time.time(),
        "duration_ms": 100,
        "status": "success",
        "token_in": 10,
        "token_out": 5,
        "cost": 0.001,
    }
    base.update(overrides)
    return TraceRecord.model_validate(base)


@pytest.fixture
def store() -> Iterator[TraceStore]:
    """每个用例一个独立的 sqlite 文件。"""
    db_path = TEST_SCRATCH_ROOT / f"trace-{uuid4().hex[:10]}.db"
    instance = TraceStore(db_path)
    yield instance
    instance.close()


class TestWriteAndRead:
    """写入与读回。"""

    def test_add_then_read_back(self, store: TraceStore) -> None:
        record = make_record()
        store.add(record)

        assert store.count() == 1
        assert len(store.memory) == 1
        back = store.query()[0]
        assert back.trace_id == record.trace_id
        assert back.role == "planner"
        assert back.token_in == 10
        assert back.cost == pytest.approx(0.001)

    def test_is_callable_as_trace_sink(self, store: TraceStore) -> None:
        """满足 TraceSink 协议：可调用对象。"""
        store(make_record(role="executor", step=3))
        assert store.count() == 1

    def test_tool_calls_json_roundtrip(self, store: TraceStore) -> None:
        calls = [
            {
                "name": "calculator",
                "args": {"expression": "6*7"},
                "result": "42",
                "status": "success",
                "duration_ms": 3,
            }
        ]
        store.add(make_record(role="executor", step=0, tool_calls=calls))
        back = store.query()[0]
        assert back.tool_calls == calls

    def test_persists_across_instances(self, store: TraceStore) -> None:
        store.add(make_record())
        reopened = TraceStore(store.db_path)
        try:
            assert reopened.count() == 1
        finally:
            reopened.close()

    def test_memory_is_bounded(self) -> None:
        db_path = TEST_SCRATCH_ROOT / f"trace-{uuid4().hex[:10]}.db"
        bounded = TraceStore(db_path, memory_limit=2)
        try:
            for step in range(3):
                bounded.add(make_record(step=step))
            assert len(bounded.memory) == 2  # 内存只留最近 2 条
            assert bounded.count() == 3  # 库里是全量
        finally:
            bounded.close()


class TestQuery:
    """按任务 / 角色 / 数量查询。"""

    def test_for_task_orders_by_step(self, store: TraceStore) -> None:
        for step in (2, 0, 1):
            store.add(make_record(step=step))
        steps = [record.step for record in store.for_task("t-1")]
        assert steps == [0, 1, 2]

    def test_for_task_falls_back_to_db(self, store: TraceStore) -> None:
        """内存被别人挤掉后，仍能从库里把任务还原出来。"""
        store.add(make_record(task_id="old", role="planner", step=0))
        for index in range(5):
            store.add(make_record(task_id=f"new-{index}", role="reviewer", step=index))
        store._memory.clear()  # 模拟内存视图被清空
        records = store.for_task("old")
        assert len(records) == 1
        assert records[0].task_id == "old"

    def test_query_filters(self, store: TraceStore) -> None:
        store.add(make_record(role="planner", step=0))
        store.add(make_record(role="executor", step=0))
        store.add(make_record(role="executor", step=1))
        assert len(store.query(role="executor")) == 2
        assert len(store.query(task_id="t-1")) == 3
        assert len(store.query(limit=1)) == 1

    def test_distinct_tasks(self, store: TraceStore) -> None:
        store.add(make_record(task_id="a"))
        store.add(make_record(task_id="b"))
        store.add(make_record(task_id="a"))
        assert set(store.distinct_tasks()) == {"a", "b"}

    def test_count_task(self, store: TraceStore) -> None:
        store.add(make_record(task_id="a"))
        store.add(make_record(task_id="b"))
        assert store.count_task("a") == 1
        assert store.count_task("missing") == 0


class TestAggregate:
    """汇总口径。"""

    def test_sums_tokens_cost_duration(self, store: TraceStore) -> None:
        store.add(
            make_record(role="planner", token_in=100, token_out=50, cost=0.01, duration_ms=200)
        )
        store.add(
            make_record(role="reviewer", token_in=300, token_out=70, cost=0.02, duration_ms=300)
        )
        summary = store.aggregate()
        assert summary["records"] == 2
        assert summary["token_in"] == 400
        assert summary["token_out"] == 120
        assert summary["cost"] == pytest.approx(0.03)
        assert summary["duration_ms"] == 500
        assert summary["not_success"] == 0

    def test_counts_failures(self, store: TraceStore) -> None:
        store.add(make_record(role="planner", step=0))
        store.add(make_record(role="executor", step=0, status="timeout"))
        assert store.aggregate()["not_success"] == 1

    def test_aggregate_scoped_to_task(self, store: TraceStore) -> None:
        store.add(make_record(task_id="a", cost=0.01))
        store.add(make_record(task_id="b", cost=0.02))
        assert store.aggregate("a")["cost"] == pytest.approx(0.01)

    def test_empty_aggregate(self, store: TraceStore) -> None:
        assert store.aggregate()["records"] == 0


class TestMaintenance:
    """清理与默认路径。"""

    def test_clear_only_affects_traces(self, store: TraceStore) -> None:
        store.add(make_record())
        store.clear()
        assert store.count() == 0
        assert store.memory == []

    def test_default_db_path_is_absolute(self) -> None:
        assert default_db_path().is_absolute()

    def test_context_manager_closes(self) -> None:
        db_path = TEST_SCRATCH_ROOT / f"trace-{uuid4().hex[:10]}.db"
        with TraceStore(db_path) as inner:
            inner.add(make_record())
            assert inner.count() == 1
