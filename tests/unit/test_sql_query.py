"""sql_query（P1 智能问数）单测：只读边界、错误语义、行数上限与自愈。

安全判据必须**分层证伪**：只把关键字检查短路时，authorizer 仍要拒绝写；
再把 authorizer 也短路时，URI ``mode=ro`` 仍要拒绝写。只测最外层等于没测。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.tools.builtin import sql_query as sql_query_module
from core.tools.builtin.sql_query import (
    DEMO_DB_ENV,
    SqlQueryError,
    demo_db_path,
    register,
    sql_query,
)
from core.tools.registry import ToolRegistry


@pytest.fixture()
def demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """用真实种子脚本建临时库，并把工具指向它（不读写仓库 data/）。"""
    from scripts.seed_demo_sql import seed

    path = tmp_path / "demo.db"
    seed(path)
    monkeypatch.setenv(DEMO_DB_ENV, str(path))
    assert demo_db_path() == path
    return path


# --------------------------------------------------------------------------- #
# 允许的查询
# --------------------------------------------------------------------------- #
def test_demo_question_returns_expected_totals(demo_db: Path) -> None:
    """README 演示问题的答案与种子数据一致（也锁住种子不被误改）。"""
    result = sql_query(
        "SELECT d.dept_name, ROUND(SUM(c.amount_cny), 2) AS total_cny "
        "FROM expense_claims AS c JOIN departments AS d ON d.dept_id = c.dept_id "
        "WHERE c.status = 'approved' AND c.category LIKE '差旅%' "
        "GROUP BY d.dept_id, d.dept_name ORDER BY total_cny DESC"
    )
    assert result["columns"] == ["dept_name", "total_cny"]
    assert result["rows"] == [
        ["销售部", 8970.0],
        ["研发部", 5790.0],
        ["市场部", 5360.0],
        ["交付部", 3220.0],
        ["职能部", 2700.0],
    ]
    assert result["row_count"] == 5
    assert result["truncated"] is False


def test_allows_aggregate_and_with(demo_db: Path) -> None:
    assert sql_query("SELECT COUNT(*) AS n FROM employees")["rows"] == [[15]]
    result = sql_query(
        "WITH t AS (SELECT dept_id, SUM(amount_cny) AS s FROM expense_claims GROUP BY dept_id) "
        "SELECT COUNT(*) AS n FROM t"
    )
    assert result["rows"] == [[5]]


def test_allows_recursive_cte(demo_db: Path) -> None:
    result = sql_query(
        "WITH RECURSIVE nums(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM nums WHERE n < 3) "
        "SELECT n FROM nums",
        limit=10,
    )
    assert result["rows"] == [[1], [2], [3]]


def test_cte_allowlist_does_not_leak_between_queries(demo_db: Path) -> None:
    """CTE 白名单是 per-call 的：上一句的临时表名不能在下一句里变成可读表。"""
    sql_query(
        "WITH t AS (SELECT dept_id FROM departments) SELECT COUNT(*) AS n FROM t"
    )
    with pytest.raises(SqlQueryError, match="no such table"):
        sql_query("SELECT COUNT(*) AS n FROM t")


def test_limit_and_truncated(demo_db: Path) -> None:
    truncated = sql_query("SELECT claim_id FROM expense_claims ORDER BY claim_id", limit=2)
    assert truncated["row_count"] == 2
    assert truncated["truncated"] is True

    exact = sql_query(
        "SELECT claim_id FROM expense_claims ORDER BY claim_id LIMIT 2",
        limit=2,
    )
    assert exact["row_count"] == 2
    assert exact["truncated"] is False, "恰好 limit 行时不应谎报还有更多"


# --------------------------------------------------------------------------- #
# 拒绝的查询（第一层：语句检查）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("", "不能为空"),
        ("DELETE FROM departments", "只允许 SELECT / WITH"),
        ("PRAGMA table_info(departments)", "只允许 SELECT / WITH"),
        ("SELECT 1; SELECT 2", "单条语句"),
        ("SELECT * FROM departments WHERE dept_name = 'drop'", "禁止的关键字"),
        ("SELECT * FROM departments WHERE 1=1 -- update", "禁止的关键字"),
    ],
)
def test_statement_checks_reject(demo_db: Path, sql: str, message: str) -> None:
    with pytest.raises(SqlQueryError, match=message):
        sql_query(sql)


def test_keyword_blacklist_is_a_real_layer(
    demo_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """短路第一层后同一句能跑 ⇒ 上面那条拒绝确实来自黑名单，而不是 authorizer。

    黑名单是**保守**的：字符串字面量里出现 ``drop`` 也会被拒。只读工具宁可误拒。
    """
    text = "SELECT * FROM departments WHERE dept_name = 'drop'"
    monkeypatch.setattr(sql_query_module, "_validate_statement", lambda _text: None)
    assert sql_query(text)["row_count"] == 0


# --------------------------------------------------------------------------- #
# 拒绝的查询（第二层：authorizer；含变异对照）
# --------------------------------------------------------------------------- #
def test_authorizer_blocks_sqlite_master_and_unknown_functions(demo_db: Path) -> None:
    with pytest.raises(SqlQueryError, match="sqlite_master"):
        sql_query("SELECT * FROM sqlite_master")
    with pytest.raises(SqlQueryError, match="not authorized to use function"):
        sql_query("SELECT random()")


def test_authorizer_still_denies_when_statement_checks_short_circuited(
    demo_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """变异对照 1：只短路语句检查，authorizer 仍拒绝 DELETE。"""
    monkeypatch.setattr(sql_query_module, "_validate_statement", lambda _text: None)
    with pytest.raises(SqlQueryError, match="not authorized"):
        sql_query("DELETE FROM departments")
    assert sql_query("SELECT COUNT(*) AS n FROM departments")["rows"] == [[5]]


def test_uri_readonly_still_denies_when_first_two_layers_short_circuited(
    demo_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """变异对照 2：语句检查与 authorizer 都短路，URI ``mode=ro`` 仍拒绝写。"""
    monkeypatch.setattr(sql_query_module, "_validate_statement", lambda _text: None)
    monkeypatch.setattr(
        sql_query_module, "_authorizer", lambda *_args: sqlite3.SQLITE_OK
    )
    with pytest.raises(SqlQueryError, match="readonly"):
        sql_query("DELETE FROM departments")
    assert sql_query("SELECT COUNT(*) AS n FROM departments")["rows"] == [[5]]


# --------------------------------------------------------------------------- #
# 错误语义与自愈
# --------------------------------------------------------------------------- #
def test_bad_column_error_contains_ddl_and_recovers(demo_db: Path) -> None:
    """错误列名 → 异常文本带真实 DDL；模型可按提示改写后成功（自愈）。"""
    with pytest.raises(SqlQueryError) as excinfo:
        sql_query("SELECT dept_nam FROM departments")
    message = str(excinfo.value)
    assert "no such column" in message
    assert "CREATE TABLE departments" in message
    assert "dept_name" in message

    healed = sql_query("SELECT dept_name FROM departments ORDER BY dept_id LIMIT 2")
    assert healed["row_count"] == 2


def test_missing_db_raises_with_seed_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEMO_DB_ENV, str(tmp_path / "missing.db"))
    with pytest.raises(SqlQueryError, match="seed_demo_sql"):
        sql_query("SELECT 1")


def test_registry_records_failure_not_success(demo_db: Path) -> None:
    """异常语义：ToolRegistry 必须把拒绝记成 failed（不是返回 error dict 的成功）。"""
    registry = ToolRegistry()
    register(registry)
    record = registry.call("sql_query", {"sql": "DELETE FROM departments"})
    assert record["status"] == "failed"
    assert "只允许 SELECT / WITH" in record["result"]


# --------------------------------------------------------------------------- #
# 注册面
# --------------------------------------------------------------------------- #
def test_registration_contract(demo_db: Path) -> None:
    spec = register(ToolRegistry())
    assert spec.name == "sql_query"
    assert spec.danger_level == "low"
    assert spec.timeout == 5
    assert spec.retry == 0
    assert set(spec.parameters["properties"]) == {"sql", "limit"}
    assert "CREATE TABLE employees" in spec.description, "模型第一次调用就要看到列名"


def test_registration_survives_missing_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """库缺失不阻断注册（平台其余功能照常），但描述里要写明先跑种子。"""
    monkeypatch.setenv(DEMO_DB_ENV, str(tmp_path / "missing.db"))
    spec = register(ToolRegistry())
    assert "未初始化" in spec.description
    assert "seed_demo_sql" in spec.description


# --------------------------------------------------------------------------- #
# 种子脚本
# --------------------------------------------------------------------------- #
def test_seed_refuses_overwrite_without_force(tmp_path: Path) -> None:
    from scripts.seed_demo_sql import SeedError, seed

    path = tmp_path / "demo.db"
    counts = seed(path)
    assert counts == {
        "departments": 5,
        "employees": 15,
        "travel_standards": 10,
        "expense_claims": 32,
    }
    with pytest.raises(SeedError, match="--force"):
        seed(path)
    assert seed(path, force=True) == counts
