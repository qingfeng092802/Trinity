"""Session Memory v1 迁移：建列 / 索引 / 幂等 / fail-closed / 旧库升级演练。

所有用例都在 ``tmp_path`` 里构造旧 schema，不读取也不修改
``data/agent_platform.db``。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from storage.migrations import (
    TASK_SESSION_INDEX,
    TaskSessionMigrationError,
    ensure_task_session_column,
)


def _old_schema(path: Path) -> None:
    """造一份 v0.2.0 之前的 tasks 表（无 session_id），并留一条旧数据。"""
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id VARCHAR(64) PRIMARY KEY,
                task TEXT NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'done',
                final_answer TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO tasks (task_id, task, status, final_answer) "
            "VALUES ('task-old', '旧任务', 'done', '旧答案')"
        )
        connection.commit()
    finally:
        connection.close()


def _columns(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {str(row[1]) for row in connection.execute("PRAGMA table_info(tasks)")}
    finally:
        connection.close()


def _index_columns(path: Path, name: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [str(row[2]) for row in connection.execute(f"PRAGMA index_info({name})")]
    finally:
        connection.close()


def _indexes(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tasks'"
            )
        }
    finally:
        connection.close()


def test_old_schema_upgrade_drill_preserves_rows(tmp_path: Path) -> None:
    """临时旧库演练：补列 + 建索引，旧行不丢、不清表。"""
    path = tmp_path / "old.db"
    _old_schema(path)

    created = ensure_task_session_column(path)

    assert created == ["session_id", TASK_SESSION_INDEX]
    assert "session_id" in _columns(path)
    assert TASK_SESSION_INDEX in _indexes(path)
    assert _index_columns(path, TASK_SESSION_INDEX) == ["session_id", "created_at"]

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT task_id, task, final_answer FROM tasks").fetchall()
    finally:
        connection.close()
    assert rows == [("task-old", "旧任务", "旧答案")]


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _old_schema(path)

    assert ensure_task_session_column(path) == ["session_id", TASK_SESSION_INDEX]
    assert ensure_task_session_column(path) == []
    assert ensure_task_session_column(path) == []


def test_migration_fails_closed_on_wrong_index(tmp_path: Path) -> None:
    """同名索引但列不对：不静默继续，抛明确异常。"""
    path = tmp_path / "old.db"
    _old_schema(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("ALTER TABLE tasks ADD COLUMN session_id VARCHAR(64)")
        connection.execute(
            f"CREATE INDEX {TASK_SESSION_INDEX} ON tasks (task_id)"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(TaskSessionMigrationError, match="列不对"):
        ensure_task_session_column(path)


def test_migration_handles_missing_table_and_non_sqlite(tmp_path: Path) -> None:
    assert ensure_task_session_column(None) == []
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert ensure_task_session_column(empty) == []
    assert ensure_task_session_column(tmp_path / "does-not-exist.db") == []
