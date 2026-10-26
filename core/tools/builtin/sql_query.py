"""sql_query：对固定 demo 库执行单条只读 SELECT / WITH 查询（P1 智能问数）。

安全边界（四层，逐层独立）：

1. **URI 只读**：``file:...?mode=ro``，物理上打不开写事务；
2. **SQLite authorizer**：只放行 ``SELECT`` / 白名单表的 ``READ`` / 白名单函数
   （含 ``WITH RECURSIVE``）；``ATTACH`` / ``PRAGMA`` / 写操作 / ``sqlite_master`` 全拒；
3. **语句前置检查**：必须以 ``SELECT`` / ``WITH`` 开头、禁止分号多语句、关键字黑名单；
4. **连接级 ``PRAGMA query_only=ON``**：即使前两层被改坏，连接仍拒绝写。

⚠️ 这不是 AST 分析，是「关键字黑名单 + authorizer + URI 只读」。对外描述别写成 AST。

数据库路径固定为 ``data/demo_sql/demo.db``，**不接受路径参数**；测试用环境变量
``TRINITY_SQL_DEMO_DB`` 覆盖（process 级，模型无法设置）。库缺失时注册仍成功，
调用抛 :class:`SqlQueryError` 并提示先跑 ``python scripts/seed_demo_sql.py``。

失败一律 **raise**：``ToolRegistry.call`` 只有捕获异常才会把 ``status`` 记为
``failed``；返回 ``{"status": "error"}`` 会被当成成功，Reviewer 与前端都会看错。
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec

#: 默认 demo 库：仓库根目录 / data / demo_sql / demo.db
DEFAULT_DEMO_DB = Path(__file__).resolve().parents[3] / "data" / "demo_sql" / "demo.db"
#: 覆盖 demo 库路径的环境变量（测试 / 临时演示用，process 级）
DEMO_DB_ENV = "TRINITY_SQL_DEMO_DB"
#: 库缺失时给模型/运维的修复命令
SEED_HINT = "python scripts/seed_demo_sql.py"

#: 允许读取的表（与 scripts/fixtures/demo_sql_seed.sql 一致）
ALLOWED_TABLES: frozenset[str] = frozenset(
    {"departments", "employees", "expense_claims", "travel_standards"}
)
#: 允许调用的 SQLite 函数。``like`` / ``glob`` 必须放行：现代 SQLite 会把
#: ``category LIKE '差旅%'`` 编译成对 like() 的函数调用，否则演示问题自己就被拒。
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "abs",
        "avg",
        "coalesce",
        "count",
        "date",
        "datetime",
        "dense_rank",
        "first_value",
        "glob",
        "group_concat",
        "ifnull",
        "instr",
        "julianday",
        "lag",
        "last_value",
        "lead",
        "length",
        "like",
        "lower",
        "ltrim",
        "max",
        "min",
        "ntile",
        "nullif",
        "printf",
        "rank",
        "replace",
        "round",
        "row_number",
        "rtrim",
        "strftime",
        "substr",
        "substring",
        "sum",
        "time",
        "total",
        "trim",
        "upper",
    }
)

#: 只读工具禁止出现的关键字（第一层快速失败；authorizer 才是兜底）
_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|"
    r"reindex|analyze|replace|trigger)\b",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^(select|with)\b", re.IGNORECASE)
#: CTE 名提取：``WITH t AS (`` / ``, other AS (`` / ``WITH RECURSIVE nums(n) AS (``。
#: 不是完整 SQL 解析器 —— 只用于把「本句自己定义的临时表名」放进 authorizer 白名单；
#: 匹配多了只会误放行一个读操作，而库本身是只读的、也没有敏感表。
_CTE_NAME_RE = re.compile(
    r"(?:\bwith\b|,)\s*(?:recursive\s+)?([a-z_][a-z0-9_]*)\s*"
    r"(?:\([^)]*\))?\s+as\s*\(",
    re.IGNORECASE,
)
#: 当前查询的 CTE 白名单（contextvar：工具可能在 worker 线程里并发执行）
_CTE_NAMES: ContextVar[frozenset[str]] = ContextVar("sql_query_cte_names", default=frozenset())
#: SQL 文本长度上限（防把整本 SQL 教材塞进参数）
MAX_SQL_LENGTH = 4000


class SqlQueryError(ValueError):
    """查询被拒绝或执行失败（只读边界 / 语法 / 列名错误）。"""


# --------------------------------------------------------------------------- #
# 路径与连接
# --------------------------------------------------------------------------- #
def demo_db_path() -> Path:
    """当前生效的 demo 库路径（环境变量优先，每次调用现读，便于测试隔离）。"""
    raw = os.environ.get(DEMO_DB_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_DEMO_DB


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """以 URI 只读模式打开 demo 库，并挂上 authorizer。"""
    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    try:
        # 连接级兜底：即使 authorizer 被绕过，这条连接也拒绝写
        connection.execute("PRAGMA query_only = ON")
    except sqlite3.Error as exc:
        connection.close()
        raise SqlQueryError(f"无法初始化只读连接：{exc}") from exc
    connection.set_authorizer(_authorizer)
    return connection


def _authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    _db_name: str | None,
    _trigger: str | None,
) -> int:
    """SQLite authorizer：默认拒绝，只放行读查询所需的四类动作。"""
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        table = str(arg1 or "").lower()
        if table in ALLOWED_TABLES:
            return sqlite3.SQLITE_OK
        # CTE 名会被 SQLite 当成表读取（如 SELECT COUNT(*) FROM t）；只放行本句定义的，
        # 且永远不许借 CTE 名碰 sqlite_* / pragma_*。
        if table in _CTE_NAMES.get() and not table.startswith(("sqlite_", "pragma_")):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function = str(arg2 or "").lower()
        return sqlite3.SQLITE_OK if function in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_RECURSIVE:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


# --------------------------------------------------------------------------- #
# 语句检查与结构提示
# --------------------------------------------------------------------------- #
def _validate_statement(text: str) -> None:
    """第三层：前缀 / 多语句 / 关键字黑名单（快速失败，不替代 authorizer）。"""
    if not text:
        raise SqlQueryError("SQL 不能为空")
    if len(text) > MAX_SQL_LENGTH:
        raise SqlQueryError(f"SQL 过长（{len(text)} 字符，上限 {MAX_SQL_LENGTH}）")

    body = text.rstrip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise SqlQueryError("只允许单条语句：检测到分号分隔的多条 SQL")
    if not _PREFIX_RE.match(body):
        raise SqlQueryError("只允许 SELECT / WITH 查询（本工具是只读的）")
    matched = _FORBIDDEN_RE.search(body)
    if matched:
        raise SqlQueryError(f"SQL 含只读工具禁止的关键字：{matched.group(0).lower()}")


def _cte_names(text: str) -> frozenset[str]:
    """提取本句 ``WITH`` 定义的临时表名（仅用于 authorizer 放行 CTE 读取）。"""
    return frozenset(match.group(1).lower() for match in _CTE_NAME_RE.finditer(text))


def _schema_hint(path: Path) -> str:
    """读取 demo 库的建表 DDL，拼成给模型看的紧凑结构提示。"""
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return "（无法读取表结构）"
    if not rows:
        return "（demo 库为空）"
    return "\n".join(f"-- {name}\n{sql};" for name, sql in rows)


def _missing_db_error(path: Path) -> SqlQueryError:
    return SqlQueryError(f"demo 库不存在：{path}。请先运行 `{SEED_HINT}` 生成。")


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #
def sql_query(
    sql: Annotated[
        str,
        Field(description="单条只读 SELECT / WITH 查询；表结构见工具描述"),
    ],
    limit: Annotated[int, Field(ge=1, le=200, description="最多返回行数")] = 50,
) -> dict[str, Any]:
    """对固定 demo 库执行一条只读查询，返回 ``columns`` / ``rows`` / ``row_count`` / ``truncated``。"""
    text = sql.strip()
    _validate_statement(text)

    path = demo_db_path()
    if not path.is_file():
        raise _missing_db_error(path)

    token = _CTE_NAMES.set(_cte_names(text))
    try:
        connection = _connect_readonly(path)
        try:
            try:
                cursor = connection.execute(text)
                columns = [str(item[0]) for item in (cursor.description or ())]
                rows = cursor.fetchmany(limit)
                # 多取一行只为判断「还有没有」，不返回给模型
                truncated = len(rows) == limit and cursor.fetchone() is not None
            except sqlite3.Error as exc:
                raise SqlQueryError(
                    f"SQL 执行失败：{exc}\n可用表结构：\n{_schema_hint(path)}"
                ) from exc
        finally:
            connection.close()
    finally:
        _CTE_NAMES.reset(token)

    return {
        "columns": columns,
        "rows": [list(row) for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def register(registry: ToolRegistry) -> ToolSpec:
    """把 sql_query 注册进给定注册表（demo 库缺失也成功，调用时才报错）。"""
    path = demo_db_path()
    if path.is_file():
        description = (
            "对固定的只读业务演示库执行单条 SELECT / WITH 查询，用于结构化问数"
            "（例如各部门差旅报销总额）。只能读不能写；表结构如下：\n"
            + _schema_hint(path)
        )
    else:
        description = (
            "对固定的只读业务演示库执行单条 SELECT / WITH 查询。"
            f"⚠️ demo 库尚未初始化：先运行 `{SEED_HINT}`，否则调用会失败。"
        )
    return registry.register(
        sql_query,
        name="sql_query",
        description=description,
        danger_level="low",
        timeout=5,
        retry=0,
    )


__all__ = [
    "ALLOWED_FUNCTIONS",
    "ALLOWED_TABLES",
    "DEFAULT_DEMO_DB",
    "DEMO_DB_ENV",
    "MAX_SQL_LENGTH",
    "SEED_HINT",
    "SqlQueryError",
    "demo_db_path",
    "register",
    "sql_query",
]
