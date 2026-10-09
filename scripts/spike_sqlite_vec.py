#!/usr/bin/env python
"""Spike①：验证 sqlite-vec 在本机（CPython 3.14 + Windows）是否可用。

流程（m2_design.md §0.2 风险① / §5 T01 子步骤 2）：
    import sqlite_vec → load_extension → 建 vec0 虚拟表（含 WAL 场景）
    → 插入 10 条 8 维向量 → KNN 查询 → 计时 → 输出 PASS / FAIL 结论

结论处理：
    PASS → .env 固化 ``VECTOR_STORE_BACKEND=sqlite-vec``
    FAIL → 装 chromadb 并固化 ``VECTOR_STORE_BACKEND=chroma``，
           失败原因写进 docs/m2_rag.md 附录（需人工确认后执行）

用法::

    .venv\\Scripts\\python.exe scripts\\spike_sqlite_vec.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / ".test-scratch" / "spike_sqlite_vec.db"
DIM = 8
ROWS = 10

STEPS: list[tuple[str, str]] = []


def _step(name: str, ok: bool, detail: str) -> None:
    """记录一步结果并立即打印（stdout 无缓冲落盘由外层重定向保证）。"""
    STEPS.append((name, "PASS" if ok else "FAIL"))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def _float32_blob(vector: list[float]) -> bytes:
    """sqlite-vec 的 vec0 列接受 packed float32 little-endian blob。"""
    import struct

    return b"".join(struct.pack("<f", float(value)) for value in vector)


def main() -> int:
    print("=" * 64)
    print("Spike①  sqlite-vec on CPython", sys.version.split()[0])
    print("=" * 64)

    # ① import
    started = time.perf_counter()
    try:
        import sqlite_vec  # noqa: F401 - 仅验证可 import
    except Exception as exc:  # noqa: BLE001
        _step("import sqlite_vec", False, f"{type(exc).__name__}: {exc}")
        return _conclude()
    _step("import sqlite_vec", True, f"{time.perf_counter() - started:.3f}s")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    try:
        # ② PRAGMA WAL（与业务库同口径——M1 教训：两条连接都要设）
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout=5000")
            _step("PRAGMA WAL + busy_timeout", True, conn.execute("PRAGMA journal_mode").fetchone()[0])
        except sqlite3.Error as exc:
            _step("PRAGMA WAL + busy_timeout", False, str(exc))
            return _conclude()

        # ③ load_extension
        started = time.perf_counter()
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            version_row = conn.execute("select vec_version()").fetchone()
            _step("load_extension", True, f"vec_version={version_row[0]} ({time.perf_counter() - started:.3f}s)")
        except Exception as exc:  # noqa: BLE001
            _step("load_extension", False, f"{type(exc).__name__}: {exc}")
            return _conclude()

        # ④ 建 vec0 虚拟表
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE spike_vec USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[{DIM}])"
            )
            _step("CREATE VIRTUAL TABLE vec0", True, f"dim={DIM}")
        except sqlite3.Error as exc:
            _step("CREATE VIRTUAL TABLE vec0", False, str(exc))
            return _conclude()

        # ⑤ 插入 10 条
        started = time.perf_counter()
        try:
            with conn:
                for index in range(ROWS):
                    vector = [float((index + j) % 7) for j in range(DIM)]
                    conn.execute(
                        "INSERT INTO spike_vec(chunk_id, embedding) VALUES (?, ?)",
                        (f"doc-{index:04d}:0000", _float32_blob(vector)),
                    )
            _step(f"INSERT {ROWS} rows", True, f"{time.perf_counter() - started:.3f}s")
        except sqlite3.Error as exc:
            _step(f"INSERT {ROWS} rows", False, str(exc))
            return _conclude()

        # ⑥ KNN 查询（与第 3 条向量最接近的 5 条）
        started = time.perf_counter()
        try:
            probe = [float((3 + j) % 7) for j in range(DIM)]
            rows = conn.execute(
                """
                SELECT chunk_id, distance
                FROM spike_vec
                WHERE embedding MATCH ?
                  AND k = 5
                ORDER BY distance
                """,
                (_float32_blob(probe),),
            ).fetchall()
            elapsed_ms = (time.perf_counter() - started) * 1000
            _step("KNN query top-5", True, f"{len(rows)} rows in {elapsed_ms:.2f}ms; top1={rows[0][0]} dist={rows[0][1]:.4f}")
        except sqlite3.Error as exc:
            _step("KNN query top-5", False, str(exc))
            return _conclude()

        # ⑦ WAL 场景下的删除（T02 的 delete_document 前置验证）
        try:
            with conn:
                conn.execute("DELETE FROM spike_vec WHERE chunk_id = ?", ("doc-0005:0000",))
            left = conn.execute("SELECT count(*) FROM spike_vec").fetchone()[0]
            _step("DELETE under WAL", True, f"remaining={left}")
        except sqlite3.Error as exc:
            _step("DELETE under WAL", False, str(exc))
    finally:
        conn.close()

    return _conclude()


def _conclude() -> int:
    """打印结论并返回退出码（0=全 PASS，1=任一 FAIL）。"""
    failed = [name for name, status in STEPS if status == "FAIL"]
    print("-" * 64)
    if not failed:
        print("结论：PASS —— sqlite-vec 可用，建议 .env 固化 VECTOR_STORE_BACKEND=sqlite-vec")
        return 0
    print(f"结论：FAIL —— 失败步骤：{failed}；建议降级 chromadb（VECTOR_STORE_BACKEND=chroma）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
