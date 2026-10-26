#!/usr/bin/env python
"""一次性回填 H-2 历史口径：按 ``task_events`` 重算 done 任务的 ``tasks.cost``。

背景：H-2 修复后新任务的 ``TraceRecord`` 已累加节点内全部 LLM 调用，但修复前落库的
历史行仍是“节点末次调用”口径。本脚本只做这件事：

  * 只处理 ``status='done'`` 的任务；
  * 目标值 = ``Σ task_events.cost WHERE event_type='llm_call'``，按 6 位小数取整
    （与 ``TaskOutcome.from_state`` / ``mark_terminal`` 的落库口径一致）；
  * 显式排除取消任务 ``task-1365c179c055``（它没有终态成本，不属 H-2 口径）；
  * **不修改 task_events、duration_ms、status 或任何其他列**；
  * 默认 dry-run，只有显式 ``--apply`` 才写库；写库前把旧值备份到
    ``data/backfill_tasks_cost_<date>.json``。

用法::

    .venv\\Scripts\\python.exe scripts\\backfill_tasks_cost.py
    .venv\\Scripts\\python.exe scripts\\backfill_tasks_cost.py --apply
    .venv\\Scripts\\python.exe scripts\\backfill_tasks_cost.py --db-url sqlite:///./data/other.db

退出码：dry-run / 无需变更 / apply 成功均为 0；SQLite 或写入异常返回 1。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings

_SQLITE_PREFIX = "sqlite:///"
#: 取消任务没有终态成本；即使未来状态被改写，也不允许本脚本碰它。
EXCLUDED_TASK_IDS = frozenset({"task-1365c179c055"})
#: 唯一参与回填的事件类型；tool_call / node_end 不进入成本口径。
LLM_CALL_EVENT = "llm_call"
COST_TOL = 1e-6


@dataclass(frozen=True, slots=True)
class CostRow:
    """一个 done 任务的对账行。"""

    task_id: str
    old_cost: float
    new_cost: float
    llm_calls: int
    event_cost: float

    @property
    def delta(self) -> float:
        return self.new_cost - self.old_cost

    @property
    def undercount_pct(self) -> float:
        return (self.delta / self.new_cost * 100.0) if self.new_cost else 0.0

    @property
    def needs_update(self) -> bool:
        return self.llm_calls > 0 and abs(self.delta) > COST_TOL


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="按 task_events 回填 done 任务的 tasks.cost（H-2 历史口径）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行 UPDATE；不加时只打印 dry-run 表",
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


def read_rows(connection: sqlite3.Connection) -> tuple[list[CostRow], int, int]:
    """读取 done 任务的对账行，返回 (待处理行, 无事件条数, 排除条数)。"""
    rows = connection.execute(
        """
        SELECT t.task_id,
               t.cost,
               COUNT(CASE WHEN e.event_type = ? THEN 1 END) AS llm_calls,
               COALESCE(SUM(CASE WHEN e.event_type = ? THEN e.cost END), 0) AS event_cost
        FROM tasks AS t
        LEFT JOIN task_events AS e ON e.task_id = t.task_id
        WHERE t.status = 'done'
        GROUP BY t.task_id
        ORDER BY t.task_id
        """,
        (LLM_CALL_EVENT, LLM_CALL_EVENT),
    ).fetchall()

    cost_rows: list[CostRow] = []
    no_events = 0
    excluded = 0
    for task_id, old_cost, llm_calls, event_cost in rows:
        if task_id in EXCLUDED_TASK_IDS:
            excluded += 1
            continue
        if int(llm_calls) == 0:
            no_events += 1
            continue
        cost_rows.append(
            CostRow(
                task_id=str(task_id),
                old_cost=float(old_cost or 0.0),
                new_cost=round(float(event_cost or 0.0), 6),
                llm_calls=int(llm_calls),
                event_cost=float(event_cost or 0.0),
            )
        )
    return cost_rows, no_events, excluded


def format_table(rows: list[CostRow]) -> str:
    """打印 dry-run / apply 共用的人读表。"""
    header = f"{'task_id':<26} {'calls':>5} {'old_cost':>12} {'new_cost':>12} {'delta':>12} {'少算%':>8}"
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.task_id:<26} {row.llm_calls:>5} {row.old_cost:>12.6f} "
            f"{row.new_cost:>12.6f} {row.delta:>+12.6f} {row.undercount_pct:>7.2f}%"
        )
    return "\n".join(lines)


def backup_path_for(now: datetime) -> Path:
    """生成不覆盖旧备份的路径：data/backfill_tasks_cost_<date>.json。"""
    base = PROJECT_ROOT / "data" / f"backfill_tasks_cost_{now:%Y%m%d}.json"
    if not base.exists():
        return base
    return PROJECT_ROOT / "data" / f"backfill_tasks_cost_{now:%Y%m%d-%H%M%S}.json"


def write_backup(rows: list[CostRow]) -> Path:
    """写库前把旧值和新值一起留档。"""
    now = datetime.now().astimezone()
    path = backup_path_for(now)
    payload: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "scope": "H-2 tasks.cost backfill; status=done; event_type=llm_call",
        "excluded_task_ids": sorted(EXCLUDED_TASK_IDS),
        "rows": [
            {
                "task_id": row.task_id,
                "old_cost": row.old_cost,
                "new_cost": row.new_cost,
                "delta": row.delta,
                "llm_calls": row.llm_calls,
                "event_cost": row.event_cost,
            }
            for row in rows
        ],
    }
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def apply_rows(db_path: Path, rows: list[CostRow]) -> None:
    """在一个事务里回填；任何一行 rowcount 不为 1 就整体回滚。"""
    connection = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        for row in rows:
            cursor = connection.execute(
                "UPDATE tasks SET cost = ? WHERE task_id = ? AND status = 'done'",
                (row.new_cost, row.task_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"UPDATE 命中 {cursor.rowcount} 行（期望 1）：{row.task_id}；已回滚"
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def remaining_mismatches(db_path: Path) -> list[CostRow]:
    """apply 后重读并返回仍不等的行（用于自证回填完成）。"""
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows, _, _ = read_rows(connection)
    finally:
        connection.close()
    return [row for row in rows if abs(row.delta) > COST_TOL]


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    args = parse_args(argv)
    db_path = resolve_db_path(args.db_url)
    if db_path is None:
        print("[跳过] 当前数据库不是 SQLite；本脚本只支持 SQLite。")
        return 0
    if not db_path.is_file():
        print(f"[错误] 数据库文件不存在：{db_path}")
        return 1

    print(f"目标数据库：{db_path}")
    print(f"口径：status='done'，event_type='{LLM_CALL_EVENT}'，排除 {sorted(EXCLUDED_TASK_IDS)}")

    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        cost_rows, no_events, excluded = read_rows(connection)
    except sqlite3.Error as exc:
        print(f"[错误] 读取数据库失败：{exc}")
        return 1
    finally:
        connection.close()

    pending = [row for row in cost_rows if row.needs_update]
    unchanged = [row for row in cost_rows if not row.needs_update]

    print("\n待回填（dry-run 读数）：")
    print(format_table(pending) if pending else "（无）")
    print(
        f"\n汇总：done 且有 llm_call 事件 {len(cost_rows)} 条；待回填 {len(pending)} 条；"
        f"已一致 {len(unchanged)} 条；无 llm_call 事件跳过 {no_events} 条；"
        f"显式排除 {excluded} 条。"
    )

    if not args.apply:
        print("\nDRY-RUN：未写库。确认读数无误后加 --apply。")
        return 0

    if not pending:
        print("\n[无需变更] 所有 done 任务已一致，未写库。")
        return 0

    backup = write_backup(pending)
    print(f"\n备份已写入：{backup}")
    try:
        apply_rows(db_path, pending)
    except Exception as exc:  # noqa: BLE001 - 脚本边界打印并返回非零
        print(f"[错误] 回填失败，事务已回滚：{exc}")
        return 1

    print(f"[完成] 已回填 {len(pending)} 条 done 任务的 tasks.cost。")

    leftovers = remaining_mismatches(db_path)
    if leftovers:
        print("\n[警告] 回填后仍有不相等行：")
        print(format_table(leftovers))
        return 1
    print("[自证] 回填后所有 done 且有 llm_call 事件的任务：|tasks.cost - Σ llm_call.cost| <= 1e-6。")
    print("[边界] task_events / duration_ms / status 均未修改；取消任务未触碰。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
