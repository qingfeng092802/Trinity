"""阶段 4 单测：SQLAlchemy 业务表 + 带降级的缓存。

不用 pytest 的 ``tmp_path``（本机沙箱对递归删除 fail-closed），
数据库文件与缓存都放在项目内的 ``data/.test-scratch/``（已 gitignore）。
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import pytest

from config import PROJECT_ROOT
from storage.cache import CacheFacade, MemoryCache, RedisCache
from storage.db import DEFAULT_AGENTS, Database
from storage.models import AgentRecord, EvalRecord, TaskRecord

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


@pytest.fixture
def database() -> Database:
    """每个用例一个独立的 SQLite 文件。"""
    path = TEST_SCRATCH_ROOT / f"db-{uuid4().hex[:10]}.sqlite3"
    instance = Database(f"sqlite:///{path.as_posix()}")
    instance.init_db()
    return instance


class FakeRedis:
    """最小可用的 Redis 客户端替身（不联网）。"""

    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def ping(self) -> bool:
        return self.alive

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttls[key] = ttl

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0

    def scan_iter(self, match: str = "*") -> Any:
        return iter(list(self.data))


class DeadCache:
    """``ping`` 永远失败的后端，用来验证降级路径。"""

    def ping(self) -> bool:
        return False

    def get(self, key: str) -> Any | None:
        raise AssertionError("降级后不应再调用不可用后端")

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        raise AssertionError("降级后不应再调用不可用后端")

    def delete(self, key: str) -> bool:
        raise AssertionError("降级后不应再调用不可用后端")

    def clear(self) -> int:
        raise AssertionError("降级后不应再调用不可用后端")


class TestDatabase:
    """业务表的增删改查。"""

    def test_init_db_seeds_agents(self, database: Database) -> None:
        names = {item.name for item in database.list_agents()}
        assert {name for name, _, _ in DEFAULT_AGENTS} <= names

    def test_repeated_init_db_neither_duplicates_nor_raises(self, database: Database) -> None:
        """重复建库不该重复播种，也不该撞 ``agents.name`` 唯一约束。

        盯 :meth:`Database._seed_agents` 的两道防线：预查已存在的名字，以及兜住并发
        ``init_db`` 竞态的 ``INSERT OR IGNORE``。
        """
        database.init_db()
        records = list(database.list_agents())
        assert {item.name for item in records} == {name for name, _, _ in DEFAULT_AGENTS}
        assert len(records) == len(DEFAULT_AGENTS)

    def test_save_and_get_task(self, database: Database) -> None:
        database.save_task(task_id="t-1", task="算个数", status="done", iterations=2, cost=0.01)
        record = database.get_task("t-1")
        assert record is not None
        assert record.task == "算个数"
        assert record.status == "done"
        assert record.iterations == 2

    def test_save_task_is_upsert(self, database: Database) -> None:
        database.save_task(task_id="t-1", task="第一次", status="running")
        database.save_task(task_id="t-1", task="第二次", status="done", score=9)
        record = database.get_task("t-1")
        assert record is not None
        assert record.task == "第二次"
        assert record.score == 9
        assert len(database.list_tasks()) == 1  # 没有变成两条

    def test_save_task_requires_id(self, database: Database) -> None:
        with pytest.raises(ValueError, match="task_id 不能为空"):
            database.save_task(task="没有 id")

    def test_list_tasks_filters_and_orders(self, database: Database) -> None:
        for index in range(3):
            database.save_task(task_id=f"t-{index}", task=f"任务{index}", status="done")
        database.save_task(task_id="t-x", task="失败的", status="failed")
        assert len(database.list_tasks(status="done")) == 3
        assert len(database.list_tasks(status="failed")) == 1
        assert len(database.list_tasks(limit=2)) == 2

    def test_delete_task(self, database: Database) -> None:
        database.save_task(task_id="t-1", task="x")
        assert database.delete_task("t-1") is True
        assert database.delete_task("t-1") is False

    def test_upsert_agent_and_toggle(self, database: Database) -> None:
        database.upsert_agent("coder", role="executor", description="写代码", model="m")
        listed = {item.name: item for item in database.list_agents()}
        assert "coder" in listed
        assert listed["coder"].role == "executor"
        assert listed["coder"].enabled_bool is True

        assert database.set_agent_enabled("coder", False) is True
        disabled = next(item for item in database.list_agents() if item.name == "coder")
        assert disabled.enabled_bool is False
        assert database.set_agent_enabled("不存在", True) is False

    def test_save_eval_result_roundtrip(self, database: Database) -> None:
        database.save_task(task_id="t-1", task="x")
        database.save_eval_result(
            {
                "task_id": "t-1",
                "score": 8,
                "grade": "good",
                "reasoning": "满足两条标准",
                "issues": ["缺少来源"],
                "suggestions": ["补引用"],
                "trace_refs": ["t-1-planner-0"],
            }
        )
        records = database.list_evals(task_id="t-1")
        assert len(records) == 1
        assert records[0].score == 8
        assert records[0].loads_issues() == ["缺少来源"]
        assert records[0].loads_suggestions() == ["补引用"]

    def test_save_eval_result_requires_task_id(self, database: Database) -> None:
        with pytest.raises(ValueError, match="缺少 task_id"):
            database.save_eval_result({"score": 1})

    def test_stats(self, database: Database) -> None:
        database.save_task(task_id="a", task="x", status="done", cost=0.01)
        database.save_task(task_id="b", task="y", status="aborted", cost=0.02)
        database.save_eval_result({"task_id": "a", "score": 8, "grade": "good"})
        stats = database.stats()
        assert stats["tasks"] == 2
        assert stats["by_status"]["done"] == 1
        assert stats["total_cost"] == pytest.approx(0.03)
        assert stats["avg_score"] == pytest.approx(8.0)

    def test_clear_all(self, database: Database) -> None:
        database.save_task(task_id="a", task="x")
        database.clear_all()
        assert database.stats()["tasks"] == 0

    def test_model_dict_exports(self) -> None:
        task = TaskRecord(task_id="t", task="x", status="done", cost=0.5)
        assert task.as_dict()["cost"] == 0.5
        agent = AgentRecord(name="a", role="planner", enabled=1)
        assert agent.as_dict()["enabled"] is True
        assert EvalRecord.dumps(["x"]) == '["x"]'


class TestMemoryCache:
    """进程内缓存。"""

    def test_set_get_delete(self) -> None:
        cache = MemoryCache(default_ttl=60)
        assert cache.set("k", {"a": 1})
        assert cache.get("k") == {"a": 1}
        assert cache.delete("k") is True
        assert cache.get("k") is None
        assert cache.delete("k") is False

    def test_expiry(self) -> None:
        cache = MemoryCache(default_ttl=1)
        cache.set("k", 1, ttl=1)
        assert cache.get("k") == 1
        time.sleep(1.1)
        assert cache.get("k") is None

    def test_clear(self) -> None:
        cache = MemoryCache()
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.clear() == 2
        assert len(cache) == 0

    def test_missing_key(self) -> None:
        assert MemoryCache().get("nope") is None


class TestRedisCache:
    """Redis 后端：正常路径与异常兜底。"""

    def test_roundtrip_with_injected_client(self) -> None:
        fake = FakeRedis()
        cache = RedisCache(fake, default_ttl=60)
        assert cache.ping() is True
        assert cache.set("k", {"a": 1}) is True
        assert fake.ttls["k"] == 60
        assert cache.get("k") == {"a": 1}
        assert cache.delete("k") is True
        assert cache.get("k") is None

    def test_custom_ttl(self) -> None:
        fake = FakeRedis()
        RedisCache(fake).set("k", 1, ttl=5)
        assert fake.ttls["k"] == 5

    def test_clear_counts(self) -> None:
        fake = FakeRedis()
        cache = RedisCache(fake)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.clear() == 2

    def test_broken_client_never_raises(self) -> None:
        class Broken:
            def ping(self) -> bool:
                raise RuntimeError("连接不上")

            def get(self, key: str) -> Any:
                raise RuntimeError("连接不上")

            def setex(self, key: str, ttl: int, value: str) -> None:
                raise RuntimeError("连接不上")

            def delete(self, key: str) -> int:
                raise RuntimeError("连接不上")

            def scan_iter(self, match: str = "*") -> Any:
                raise RuntimeError("连接不上")

        cache = RedisCache(Broken(), default_ttl=10)
        assert cache.ping() is False
        assert cache.get("k") is None
        assert cache.set("k", 1) is False
        assert cache.delete("k") is False
        assert cache.clear() == 0


class TestCacheFacade:
    """降级门面。"""

    def test_falls_back_when_primary_dead(self) -> None:
        facade = CacheFacade(primary=DeadCache(), fallback=MemoryCache(default_ttl=60))
        assert facade.using_redis is False
        assert facade.set("k", "v")
        assert facade.get("k") == "v"

    def test_uses_primary_when_alive(self) -> None:
        fake = FakeRedis()
        facade = CacheFacade(primary=RedisCache(fake, default_ttl=30), fallback=MemoryCache())
        assert facade.using_redis is True
        facade.set("k", [1, 2])
        assert facade.get("k") == [1, 2]

    def test_explicit_fallback_is_kept_even_when_empty(self) -> None:
        """回归：调用方传进来的后端必须被用上，哪怕它是空的。

        ``MemoryCache`` 实现了 ``__len__``，空实例是 **falsy** 的；一旦在
        ``CacheFacade.__init__`` 里用 ``fallback or MemoryCache(...)`` 兜底，
        就会被静默丢弃、换成另一个新实例——调用方拿到的永远读不到自己写的东西，
        而且没有任何报错。所以那里必须显式判断 ``is not None``。
        """
        fallback = MemoryCache(default_ttl=60)
        facade = CacheFacade(primary=DeadCache(), fallback=fallback)
        assert facade.backend is fallback
        facade.set("k", "v")
        assert fallback.get("k") == "v"

    def test_write_failure_goes_to_fallback(self) -> None:
        class HalfBroken:
            def ping(self) -> bool:
                return True

            def get(self, key: str) -> Any | None:
                return None

            def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
                return False

            def delete(self, key: str) -> bool:
                return False

            def clear(self) -> int:
                return 0

        fallback = MemoryCache(default_ttl=60)
        facade = CacheFacade(primary=HalfBroken(), fallback=fallback)
        assert facade.set("k", "v") is True  # 首选失败，落到内存
        assert fallback.get("k") == "v"

    def test_state_helpers_for_resume(self) -> None:
        facade = CacheFacade(primary=DeadCache(), fallback=MemoryCache(default_ttl=60))
        facade.save_state("task-1", {"status": "running", "step": 2})
        assert facade.load_state("task-1") == {"status": "running", "step": 2}
        assert facade.drop_state("task-1") is True
        assert facade.load_state("task-1") is None

    def test_clear_touches_both(self) -> None:
        fallback = MemoryCache(default_ttl=60)
        facade = CacheFacade(primary=DeadCache(), fallback=fallback)
        facade.set("k", 1)
        assert facade.clear() >= 0
        assert facade.get("k") is None
