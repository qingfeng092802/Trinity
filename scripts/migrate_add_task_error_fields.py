#!/usr/bin/env python
"""手工补列脚本：给已有 SQLite 库加上 ``tasks.error_code`` / ``tasks.error_message``。

``Database.init_db()`` 启动时会自动跑一次同样的迁移，本脚本存在的意义是：

1. 运维可以在**不停服务**的前提下先把库结构对齐（SQLite 的 ALTER ADD COLUMN
   是 O(1) 的元数据操作，加可空列不会重写表）；
2. 出问题时可以单独重跑并看到明确输出，不必去翻服务日志。

用法::

    .venv\\Scripts\\python.exe scripts\\migrate_add_task_error_fields.py
    .venv\\Scripts\\python.exe scripts\\migrate_add_task_error_fields.py --db-url sqlite:///./data/other.db

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
from storage.migrations import TASK_ERROR_COLUMNS, ensure_task_error_columns  # noqa: E402

_SQLITE_PREFIX = "sqlite:///"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="给 tasks 表补 error_code / error_message 两列")
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

    expected = "、".join(name for name, _ in TASK_ERROR_COLUMNS)
    print(f"目标数据库：{db_path}")
    if not db_path.is_file():
        print("[跳过] 数据库文件不存在，首次启动时 create_all 会直接建出带新列的表。")
        return 0

    added = ensure_task_error_columns(db_path)
    if added:
        print(f"[完成] 已补列：{'、'.join(added)}")
    else:
        print(f"[无需变更] tasks 表已包含 {expected}，本次未做任何修改（幂等）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
