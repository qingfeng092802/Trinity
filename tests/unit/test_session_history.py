"""Session Memory v1 历史查询：顺序、过滤、隔离与当前任务排除。

历史来源是现有 ``tasks`` 表；本文件只测数据层，不碰真实 ``data/agent_platform.db``。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.agent.session import (
    MAX_HISTORY_ANSWER_CHARS,
    MAX_HISTORY_QUERY_CHARS,
    SessionTurn,
    format_session_history,
)
from storage.db import Database


def _at(minutes: int) -> datetime:
    # 与 TaskRecord.created_at 同口径：UTC naive
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC).replace(tzinfo=None) + timedelta(
        minutes=minutes
    )


def _database(tmp_path: Path) -> Database:
    path = tmp_path / "session.db"
    database = Database(f"sqlite:///{path.as_posix()}")
    database.init_db()
    return database


def _seed(database: Database) -> None:
    # 同一 session：5 条 done，时间递增
    database.save_task(
        task_id="s1", task="q1", session_id="s", status="done",
        final_answer="a1", created_at=_at(1),
    )
    database.save_task(
        task_id="s2", task="q2", session_id="s", status="done",
        final_answer="a2", created_at=_at(2),
    )
    database.save_task(
        task_id="s3", task="q3", session_id="s", status="done",
        final_answer="a3", created_at=_at(3),
    )
    database.save_task(
        task_id="s4", task="q4", session_id="s", status="done",
        final_answer="a4", created_at=_at(4),
    )
    database.save_task(
        task_id="s5", task="q5", session_id="s", status="done",
        final_answer="a5", created_at=_at(5),
    )
    # 不参与历史的：failed / 空答案 / 别的 session
    database.save_task(
        task_id="failed", task="q-failed", session_id="s", status="failed",
        final_answer="bad", created_at=_at(6),
    )
    database.save_task(
        task_id="empty", task="q-empty", session_id="s", status="done",
        final_answer="", created_at=_at(7),
    )
    database.save_task(
        task_id="other", task="q-other", session_id="other", status="done",
        final_answer="a-other", created_at=_at(8),
    )


def test_returns_last_three_done_turns_in_chronological_order(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)

    rows = database.list_session_history("s", exclude_task_id="s5", limit=3)

    assert [row.task_id for row in rows] == ["s2", "s3", "s4"]
    assert [row.task for row in rows] == ["q2", "q3", "q4"]
    assert [row.final_answer for row in rows] == ["a2", "a3", "a4"]


def test_filters_failed_empty_and_other_sessions(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)

    rows = database.list_session_history("s", exclude_task_id="not-current", limit=10)
    assert [row.task_id for row in rows] == ["s1", "s2", "s3", "s4", "s5"]

    other = database.list_session_history("other", exclude_task_id="not-current", limit=10)
    assert [row.task_id for row in other] == ["other"]


def test_no_history_for_unknown_session_or_invalid_limit(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)

    assert database.list_session_history("nope", exclude_task_id="x") == []
    assert database.list_session_history("", exclude_task_id="x") == []
    assert database.list_session_history("s", exclude_task_id="x", limit=0) == []


def test_session_id_is_persisted_and_exported(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.save_task(
        task_id="x", task="q", session_id="session-1", status="done", final_answer="a"
    )
    record = database.get_task("x")
    assert record is not None
    assert record.session_id == "session-1"
    assert record.as_dict()["session_id"] == "session-1"


def test_format_session_history_clips_and_keeps_last_three() -> None:
    turns = [
        SessionTurn(query=f"q{index}-" + "x" * (MAX_HISTORY_QUERY_CHARS + 20),
                    answer=f"a{index}-" + "y" * (MAX_HISTORY_ANSWER_CHARS + 20))
        for index in range(4)
    ]

    text = format_session_history(turns)

    assert "第 1 轮" in text and "第 3 轮" in text
    assert "q0-" not in text, "只保留最近 3 轮，最早的 q0 应被丢弃"
    assert "q1-" in text and "q3-" in text
    assert text.count("…") >= 6, "query 与 answer 超长都要截断"
    # 头部与每轮标签有固定开销，不能把上界卡成 3*(query+answer)
    assert len(text) < 3 * (MAX_HISTORY_QUERY_CHARS + MAX_HISTORY_ANSWER_CHARS) + 500
    assert "不要重复执行这些历史任务" in text


def test_format_session_history_empty_is_empty() -> None:
    assert format_session_history([]) == ""
