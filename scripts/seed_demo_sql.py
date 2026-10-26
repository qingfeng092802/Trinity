#!/usr/bin/env python
"""生成 Text-to-SQL 演示库 ``data/demo_sql/demo.db``（P1 智能问数）。

数据是虚构公司「云启智能」的部门 / 员工 / 差旅标准 / 报销单，固定可复现。
``sql_query`` 工具只读这个库，**不接受路径参数**；本脚本是它唯一的数据来源。

用法::

    .venv\\Scripts\\python.exe scripts\\seed_demo_sql.py            # 首次生成
    .venv\\Scripts\\python.exe scripts\\seed_demo_sql.py --force    # 覆盖重建
    .venv\\Scripts\\python.exe scripts\\seed_demo_sql.py --db data/demo_sql/other.db

退出码：0 = 成功或已提示；1 = 目标已存在且未加 ``--force`` / 执行失败。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "demo_sql" / "demo.db"
SEED_SQL = PROJECT_ROOT / "scripts" / "fixtures" / "demo_sql_seed.sql"

TABLES: tuple[str, ...] = ("departments", "employees", "travel_standards", "expense_claims")


class SeedError(RuntimeError):
    """demo 库生成失败。"""


def seed(db_path: Path, *, force: bool = False) -> dict[str, int]:
    """执行种子 SQL 并返回每张表的行数。

    Args:
        db_path: 目标 SQLite 文件；父目录不存在会自动创建。
        force: 目标已存在时是否覆盖。默认拒绝，避免抹掉手工改过的演示库。

    Raises:
        SeedError: 目标已存在且未加 ``force``，或种子 SQL 执行失败。
    """
    target = db_path.expanduser().resolve()
    if target.exists() and not force:
        raise SeedError(f"目标已存在：{target}；要覆盖请加 --force")
    if not SEED_SQL.is_file():
        raise SeedError(f"种子 SQL 不存在：{SEED_SQL}")

    target.parent.mkdir(parents=True, exist_ok=True)
    script = SEED_SQL.read_text(encoding="utf-8")
    connection = sqlite3.connect(target)
    try:
        connection.executescript(script)
        connection.commit()
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in TABLES
        }
    except sqlite3.Error as exc:
        raise SeedError(f"种子 SQL 执行失败：{exc}") from exc
    finally:
        connection.close()
    return counts


def _demo_answer(db_path: Path) -> list[tuple[str, float]]:
    """跑一遍 README 里的演示问题，输出预期答案（用于人工复核）。"""
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT d.dept_name, ROUND(SUM(c.amount_cny), 2) AS total_cny
            FROM expense_claims AS c
            JOIN departments AS d ON d.dept_id = c.dept_id
            WHERE c.status = 'approved' AND c.category LIKE '差旅%'
            GROUP BY d.dept_id, d.dept_name
            ORDER BY total_cny DESC
            """
        ).fetchall()
    finally:
        connection.close()
    return [(str(name), float(total)) for name, total in rows]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 Text-to-SQL 演示库（只读工具 sql_query 的数据源）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"目标库路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--force", action="store_true", help="目标已存在时覆盖重建")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        counts = seed(args.db, force=bool(args.force))
    except SeedError as exc:
        print(f"[seed_demo_sql] {exc}", file=sys.stderr)
        return 1

    target = args.db.expanduser().resolve()
    print(f"[seed_demo_sql] 已生成 {target}")
    for table in TABLES:
        print(f"  - {table}: {counts[table]} 行")
    print("[seed_demo_sql] 演示问题「各部门差旅报销总额」的预期答案：")
    for name, total in _demo_answer(target):
        print(f"  - {name}: {total:.2f} 元")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
