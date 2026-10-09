#!/usr/bin/env python
"""手工建表脚本：给已有 SQLite 库建 ``task_events`` 表 + 两个索引（P1-A）。

``Database.init_db()`` 启动时会自动跑一次同样的迁移，本脚本存在的意义是：

1. 运维可以在**不停服务**的前提下先把库结构对齐（``CREATE TABLE IF NOT EXISTS``
   不会重写已有数据）；
2. 出问题时可以单独重跑并看到明确输出，不必去翻服务日志。

用法::

    .venv\\Scripts\\python.exe scripts\\migrate_add_task_events.py
    .venv\\Scripts\\python.exe scripts\\migrate_add_task_events.py --db-url sqlite:///./data/other.db

三条硬约束（照抄 ``migrate_add_task_error_fields.py``）：

1. **幂等**：连跑 N 次，只有第一次真的建表，后续输出「无需变更」且退出码 0；
2. **不猜**：用 ``sqlite_master`` / ``PRAGMA table_info`` 查真实现状；
3. **只管 SQLite**：``--db-url`` 非 sqlite 时直接跳过。

退出码恒为 0（迁移是"尽力而为"，失败已记 WARNING，不该让启动脚本因此中断）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from storage.migrations import (  # noqa: E402
    TASK_EVENTS_INDEX_DDL,
    ensure_task_events_table,
)

_SQLITE_PREFIX = "sqlite:///"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="建 task_events 表（轨迹事件表，P1-A）与两个索引"
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLAlchemy 连接串；不传则取配置里的 DB_URL（仅支持 sqlite）",
    )
    return parser.parse_args(argv)


def resolve_db_path(db_url: str | None) -> Path | None:
    """把连接串解析成文件路径；非 sqlite 返回 None。"""
    url = db_url or get_settings().resolved_db_url
    if not url.startswith(_SQLITE_PREFIX):
        return None
    raw = url[len(_SQLITE_PREFIX) :]
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    args = parse_args(argv)
    db_path = resolve_db_path(args.db_url)

    if db_path is None:
        print("[跳过] 当前数据库不是 SQLite，无需本迁移。")
        return 0

    expected_indexes = [
        ddl.split("IF NOT EXISTS", 1)[1].split("ON", 1)[0].strip()
        for ddl in TASK_EVENTS_INDEX_DDL
    ]
    print(f"目标数据库：{db_path}")
    if not db_path.is_file():
        print("[跳过] 数据库文件不存在，首次启动时 create_all 会直接建出 task_events。")
        return 0

    created = ensure_task_events_table(db_path)
    if created:
        print(f"[完成] 已创建：{'、'.join(created)}")
    else:
        names = "、".join(["task_events", *expected_indexes])
        print(f"[无需变更] {names} 均已存在，本次未做任何修改（幂等）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
