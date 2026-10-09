"""一次性 schema 迁移。

包含三个迁移：

1. ``ensure_task_error_columns``（M1）—— 给 ``tasks`` 表补
   ``error_code`` / ``error_message`` 两列（``ALTER TABLE ADD COLUMN``）。
2. ``ensure_task_events_table``（P1-A）—— 建 ``task_events`` 表 + 两个索引
   （``CREATE TABLE/INDEX IF NOT EXISTS``），供「真实可回放的轨迹时间线」使用。
3. ``ensure_task_event_cost_columns``（成本归因）—— 给 ``task_events`` 补
   ``model`` / ``price_multiplier`` 两列。缺它们就没有"这次跑在高峰还是低谷"的现场记录：
   ``tasks.created_at`` 存的是 UTC，而 :func:`core.llm.pricing.is_peak` 把无时区的串
   当北京时间解释，事后重算会整体错 8 小时（把半夜的半价标成高峰）。

为什么不用 Alembic
------------------
项目目前用 ``Base.metadata.create_all`` 建表，改动都是「加两列」或「建一张新表」，
引入完整迁移框架（Alembic）属于过度设计。但 ``create_all`` **不会**给已存在的
表加列，所以老库缺列必须靠 ALTER 补上；新表虽由 ``create_all`` 能建，但**手工
建表路径**（运维不重启就补结构）与**显式索引**仍需一个幂等函数——本模块就是它。

三条硬约束
----------
1. **幂等**：连跑 N 次，只有第一次真的改 schema，后续返回 ``[]`` 且不报错；
2. **不猜**：用 ``PRAGMA table_info`` / ``sqlite_master`` 看真实现状，
   而不是靠版本号或记忆；
3. **只管 SQLite**：非 SQLite（``db_path is None``）直接返回 ``[]`` 并记日志，
   因为 PG/MySQL 的语法与权限模型都不一样，不该由本模块擅自决定。

被两处共用：``Database.init_db()``（进程内自动跑一次）与
``scripts/migrate_add_task_error_fields.py`` / ``scripts/migrate_add_task_events.py``
（运维手工跑）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

#: 表名
TASKS_TABLE = "tasks"

#: 轨迹事件表名（P1-A）
TASK_EVENTS_TABLE = "task_events"

#: 需要补齐的列：(列名, DDL 类型)。与 ``storage/models.py`` 的声明保持一致。
TASK_ERROR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("error_code", "VARCHAR(32)"),
    ("error_message", "TEXT"),
)

#: 成本归因需要补齐的列：(列名, DDL 类型)。与 ``storage/models.py`` 的声明保持一致。
#:
#: 两列都**可空**，且 NULL 与 0 是两件事：``price_multiplier = 0.0`` 读起来是"这次免费"，
#: NULL 才是"这条历史记录时还没这字段"。界面必须把后者显示成「未记录」，
#: 不许回落到"当前 ``role_map`` 里的模型"或"现在的时段系数"（那是拿今天的账填昨天的坑）。
TASK_EVENT_COST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("model", "VARCHAR(64)"),
    ("price_multiplier", "REAL"),
)

#: ``task_events`` 规范 DDL（设计文档 §3.2）。
#: 与 ``storage.models.TaskEventRecord`` 逐列等价，供迁移脚本与审查比对。
#: ★ ``event_seq`` 用 ``INTEGER PRIMARY KEY AUTOINCREMENT``（而非裸 rowid）：
#:   借 ``sqlite_sequence`` 保证「删除最大行后新 id 不复用」，这是全局单调序的
#:   基础（设计文档 §1.1）。
TASK_EVENTS_DDL: str = """
CREATE TABLE IF NOT EXISTS task_events (
    event_seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    role          TEXT,
    step          INTEGER NOT NULL DEFAULT 0,
    sub_step      INTEGER,
    node          TEXT,
    thought       TEXT    NOT NULL DEFAULT '',
    tool_name     TEXT,
    arguments     TEXT,
    observation   TEXT    NOT NULL DEFAULT '',
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost          REAL    NOT NULL DEFAULT 0.0,
    model         VARCHAR(64),
    price_multiplier REAL,
    status        TEXT    NOT NULL DEFAULT 'success',
    error_code    TEXT,
    error_message TEXT,
    sse_seq       INTEGER,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

#: ``task_events`` 的索引 DDL（设计文档 §3.3）。
TASK_EVENTS_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_task_events_task_seq "
    "ON task_events (task_id, event_seq)",
    "CREATE INDEX IF NOT EXISTS idx_task_events_task_role "
    "ON task_events (task_id, role)",
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """判断表是否存在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """用 ``PRAGMA table_info`` 读回真实列名（下标 1 是 name）。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    """判断索引是否存在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?", (index,)
    ).fetchone()
    return row is not None


def ensure_task_error_columns(db_path: Path | str | None) -> list[str]:
    """确保 ``tasks`` 表有错误原因两列；返回**本次**新增的列名。

    Args:
        db_path: SQLite 文件路径。``None`` 表示当前不是 SQLite，直接跳过。

    Returns:
        本轮真正 ALTER 出来的列名列表；已是最新时返回空列表。
    """
    if db_path is None:
        logger.info("当前数据库不是 SQLite，跳过 error 字段迁移")
        return []

    path = Path(db_path)
    if not path.is_file():
        logger.info("数据库文件尚不存在，交给 create_all 建表：%s", path)
        return []

    added: list[str] = []
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        if not _table_exists(conn, TASKS_TABLE):
            logger.info("tasks 表尚不存在，交给 create_all 建表：%s", path)
            return []
        present = _existing_columns(conn, TASKS_TABLE)
        for column, ddl_type in TASK_ERROR_COLUMNS:
            if column in present:
                continue
            conn.execute(f"ALTER TABLE {TASKS_TABLE} ADD COLUMN {column} {ddl_type}")
            added.append(column)
        if added:
            conn.commit()
            logger.info("已为 tasks 表补列：%s", "、".join(added))
        else:
            logger.debug("tasks 表 error 字段已是最新，无需变更")
    except sqlite3.Error as exc:
        logger.warning("补充 tasks.error_* 列失败（不影响启动，但失败原因将无法落库）：%s", exc)
        return []
    finally:
        conn.close()
    return added


def ensure_task_events_table(db_path: Path | str | None) -> list[str]:
    """确保 ``task_events`` 表与两个索引存在；返回**本次**新建的对象名。

    与 :func:`ensure_task_error_columns` 的关键差异：那个是
    ``ALTER TABLE ADD COLUMN``；这个是 ``CREATE TABLE IF NOT EXISTS`` +
    ``CREATE INDEX IF NOT EXISTS``。**因为 ``Base.metadata.create_all()`` 本身就会
    建新表**，所以本函数主要是为「手工脚本 + 显式索引」服务，逻辑更简单
    （无「表不存在则跳过」的必要，``IF NOT EXISTS`` 已幂等）。

    设计文档 §5.2：两者**共用**同一份 DDL（``TASK_EVENTS_DDL``），不重复实现。

    Args:
        db_path: SQLite 文件路径。``None`` 表示当前不是 SQLite，直接跳过。

    Returns:
        本轮真正创建的对象名列表（如 ``["task_events", "idx_task_events_task_seq",
        "idx_task_events_task_role"]``）；已是最新时返回空列表。
    """
    if db_path is None:
        logger.info("当前数据库不是 SQLite，跳过 task_events 迁移")
        return []

    path = Path(db_path)
    if not path.is_file():
        logger.info("数据库文件尚不存在，交给 create_all 建表：%s", path)
        return []

    created: list[str] = []
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        table_present = _table_exists(conn, TASK_EVENTS_TABLE)
        if not table_present:
            conn.execute(TASK_EVENTS_DDL)
            created.append(TASK_EVENTS_TABLE)
        # 索引一律用 IF NOT EXISTS 补齐（表已存在但索引缺失的手工建表场景也能修复）
        for ddl in TASK_EVENTS_INDEX_DDL:
            index_name = ddl.split("IF NOT EXISTS", 1)[1].split("ON", 1)[0].strip()
            if not _index_exists(conn, index_name):
                conn.execute(ddl)
                created.append(index_name)
        if created:
            conn.commit()
            logger.info("已创建 task_events 相关对象：%s", "、".join(created))
        else:
            logger.debug("task_events 表与索引已是最新，无需变更")
    except sqlite3.Error as exc:
        logger.warning("创建 task_events 表失败（回放将无数据，但不影响启动）：%s", exc)
        return []
    finally:
        conn.close()
    return created


def ensure_task_event_cost_columns(db_path: Path | str | None) -> list[str]:
    """确保 ``task_events`` 有成本归因两列；返回**本次**新增的列名。

    形状与 :func:`ensure_task_error_columns` 一致（同一套硬约束）：
    只读现状不猜（``PRAGMA table_info``）、幂等（连跑两次第二次返回 ``[]``）、
    只管 SQLite、失败只记日志不抛（结构缺列不该让启动挂掉，
    面板会退化成"没有系数可读"，那比整个服务不起来诚实）。

    ⚠️ 为什么非要**当场记**而不是事后用 ``created_at`` 反算：
    ``tasks.created_at`` 存的是 UTC，而 :func:`core.llm.pricing.is_peak` 把无时区的串
    按北京时间解释 —— 事后重算会整体错 8 小时，正好把半夜的低谷价标成高峰。

    Args:
        db_path: SQLite 文件路径。``None`` 表示当前不是 SQLite，直接跳过。

    Returns:
        本轮真正 ALTER 出来的列名列表；已是最新或非 SQLite 时返回空列表。
    """
    if db_path is None:
        logger.info("当前数据库不是 SQLite，跳过成本列迁移")
        return []

    path = Path(db_path)
    if not path.is_file():
        logger.info("数据库文件尚不存在，交给 create_all 建表：%s", path)
        return []

    added: list[str] = []
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        if not _table_exists(conn, TASK_EVENTS_TABLE):
            logger.info("task_events 表尚不存在，交给 create_all 建表：%s", path)
            return []
        present = _existing_columns(conn, TASK_EVENTS_TABLE)
        for column, ddl_type in TASK_EVENT_COST_COLUMNS:
            if column in present:
                continue
            # ALTER 的表名与列名都来自本模块常量（不是用户输入），无注入面
            conn.execute(f"ALTER TABLE {TASK_EVENTS_TABLE} ADD COLUMN {column} {ddl_type}")
            added.append(column)
        if added:
            conn.commit()
            logger.info("已为 task_events 表补成本列：%s", "、".join(added))
        else:
            logger.debug("task_events 成本列已是最新，无需变更")
    except sqlite3.Error as exc:
        logger.warning("补充 task_events 成本列失败（成本面板将读不到系数，但不影响启动）：%s", exc)
        return []
    finally:
        conn.close()
    return added


__all__ = [
    "TASK_ERROR_COLUMNS",
    "TASK_EVENT_COST_COLUMNS",
    "TASK_EVENTS_DDL",
    "TASK_EVENTS_INDEX_DDL",
    "TASK_EVENTS_TABLE",
    "TASKS_TABLE",
    "ensure_task_error_columns",
    "ensure_task_event_cost_columns",
    "ensure_task_events_table",
]
