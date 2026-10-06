"""B-2（P1）：进程重启后，库里残留的非终态任务必须在启动时被判死。

背景：任务跑在**本进程的内存队列**里，没有持久化队列也没有续跑能力。硬杀 / 重启之后
``tasks`` 行还停在 ``queued`` / ``running``，而队列里什么都没有 —— 数据库在说谎。
本机实测挂着一条 3 天前的 ``running``（``task-1365c179c055``，创建时刻
``2026-09-22 23:54`` UTC ＝ 北京 09-23 07:54），前端「运行中」筛选永久挂着它，
而 ``/health`` 报「运行中 0/3」—— 两个口径同时存在就是自相矛盾。

不用 pytest 的 ``tmp_path``（本机沙箱对递归删除 fail-closed），库文件放
``data/.test-scratch/``（已 gitignore）。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.constants import (
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from config import PROJECT_ROOT, reset_settings_cache
from storage.db import Database

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


@pytest.fixture
def database() -> Database:
    """每个用例一个独立的 SQLite 文件。"""
    path = TEST_SCRATCH_ROOT / f"recovery-{uuid4().hex[:10]}.sqlite3"
    instance = Database(f"sqlite:///{path.as_posix()}")
    instance.init_db()
    return instance


def _seed(db: Database, task_id: str, status: str) -> None:
    """直接摆一个指定状态的任务（绕过队列，只验清理逻辑本身）。"""
    db.save_task(task_id=task_id, task=f"恢复用例 {task_id}", status=STATUS_QUEUED)
    if status == STATUS_QUEUED:
        return
    db.mark_running(task_id)
    if status in {STATUS_DONE, STATUS_ABORTED, STATUS_FAILED, STATUS_CANCELED}:
        db.mark_terminal(task_id, status=status)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (STATUS_QUEUED, STATUS_FAILED),
        (STATUS_RUNNING, STATUS_FAILED),
        (STATUS_DONE, STATUS_DONE),
        (STATUS_ABORTED, STATUS_ABORTED),
        (STATUS_FAILED, STATUS_FAILED),
        (STATUS_CANCELED, STATUS_CANCELED),
    ],
)
def test_只有非终态被判死(database: Database, status: str, expected: str) -> None:
    """终态一行都不许动：已完成的账不能被重启事件改写成失败。"""
    task_id = f"task-{uuid4().hex[:12]}"
    _seed(database, task_id, status)

    database.fail_interrupted_tasks()

    record = database.get_task(task_id)
    assert record is not None
    assert record.status == expected, f"{status} 不该被改成 {record.status}"


def test_判死带上机器码与原因(database: Database) -> None:
    """只改状态不够 —— 报表与前端要靠 ``error_code`` 分清"谁弄失败的"。"""
    task_id = f"task-{uuid4().hex[:12]}"
    _seed(database, task_id, STATUS_RUNNING)

    changed = database.fail_interrupted_tasks()

    assert changed == 1
    record = database.get_task(task_id)
    assert record is not None
    assert record.status == STATUS_FAILED
    assert record.error_code == "process_restarted"
    assert record.error_message is not None and "重启" in record.error_message


def test_取消的任务保持无错误码(database: Database) -> None:
    """K3 口径：取消不是失败，``error_code`` 必须仍是 NULL，也不该被这次清理波及。"""
    task_id = f"task-{uuid4().hex[:12]}"
    _seed(database, task_id, STATUS_QUEUED)
    assert database.mark_canceled(task_id) is True

    assert database.fail_interrupted_tasks() == 0

    record = database.get_task(task_id)
    assert record is not None
    assert record.status == STATUS_CANCELED
    assert record.error_code is None


def test_幂等且空库返回零(database: Database) -> None:
    """第二次调用必须是 0 —— 否则"启动清理"会变成一个每轮都在写的东西。"""
    assert database.fail_interrupted_tasks() == 0

    for _ in range(3):
        _seed(database, f"task-{uuid4().hex[:12]}", STATUS_RUNNING)
    assert database.fail_interrupted_tasks() == 3
    assert database.fail_interrupted_tasks() == 0


# --------------------------------------------------------------------------- #
# 接线：lifespan 真的调了它
# --------------------------------------------------------------------------- #
def test_启动时真的清理(monkeypatch: pytest.MonkeyPatch, database: Database) -> None:
    """前一条只证明"方法有用"，这条证明**服务起起来会用它**。

    刻意不复用 ``api_env``：那个夹具在 fixture 里就进了 ``with``，我没法在它启动前
    往库里塞一条僵尸任务。
    """
    from api.deps import reset_api_caches
    from api.main import create_app

    task_id = f"task-{uuid4().hex[:12]}"
    _seed(database, task_id, STATUS_RUNNING)

    monkeypatch.setenv("DB_URL", database.url)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:59999/0")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    reset_settings_cache()
    reset_api_caches()

    with TestClient(create_app()):
        pass

    fresh = Database(database.url)
    record = fresh.get_task(task_id)
    assert record is not None
    assert record.status == STATUS_FAILED, "lifespan 没在启动时清理非终态任务"
    assert record.error_code == "process_restarted"
    reset_settings_cache()
    reset_api_caches()


def test_清理不动本次会话新建的任务(monkeypatch: pytest.MonkeyPatch, database: Database) -> None:
    """反向钉：清理只发生在**启动那一瞬**，进 context 之后落的任务不该被自己判死。"""
    from api.deps import reset_api_caches
    from api.main import create_app

    monkeypatch.setenv("DB_URL", database.url)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:59999/0")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    reset_settings_cache()
    reset_api_caches()

    task_id = f"task-{uuid4().hex[:12]}"
    with TestClient(create_app()) as client:
        _seed(database, task_id, STATUS_RUNNING)  # 启动之后才出现的 running
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == STATUS_RUNNING, "启动清理跑到了请求路径上"
    reset_settings_cache()
    reset_api_caches()
