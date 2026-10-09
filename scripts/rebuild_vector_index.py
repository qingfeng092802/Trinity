#!/usr/bin/env python
"""全库向量重建 / 一致性体检（审查报告 Q7-01 的配套脚本，也是 Q7-08 的修复入口）。

为什么需要它
------------
2026-10-02 修 Q7-01 时确认了一件事，写在这里免得下一个人重新推一遍：
**改度量换算式不需要重新嵌入**。vec0 存的是原始 float32 向量，L2 在查询时算，
``1-d`` → ``1-d²/2`` 是纯读侧的修正 —— 所以那次修复之后本机跑一遍本脚本的
``--check-only`` 就够了，不必动 106 条向量。

那这个脚本留着干什么？三件真需要**写侧**重建的事：

1. **换 embedder**（改 ``EMBEDDING_MODEL_NAME`` / ``EMBEDDING_BACKEND`` / ``EMBEDDING_DIM``）：
   新旧向量混在一张表里，检索会给出毫无意义的分数，而 ``vec0`` 的表结构（``float[dim]``）
   连维度不一致都存不进去 —— 必须全库重嵌。
2. **改存储侧的向量口径**（例如哪天决定不再归一化，或升级 sqlite-vec 后改用
   ``distance_metric=cosine`` 建表）：读侧公式与写入侧表示必须同时换，只有重建能保证一致。
3. **修孤儿**（Q7-08）：``chunks``（SQLAlchemy 连接 A）与向量（vec0 独立连接 B）**不在同一事务**，
   中间任何异常都会留下"有 chunk 无向量"或反向的残迹。本脚本的 ``--check-only`` 就是量这个的。

用法::

    python scripts/rebuild_vector_index.py                    # 只体检，不写任何东西（默认）
    python scripts/rebuild_vector_index.py --check-only       # 同上，但"不一致"时退出码 1（给门禁脚本用）
    python scripts/rebuild_vector_index.py --rebuild --backup # 先拷 .db 再全库重嵌（唯一会写盘的档）
    python scripts/rebuild_vector_index.py --rebuild --limit-docs 1   # 先拿一份文档试手

退出码：0 成功（体检模式下"一致"也算成功）；1 体检发现不一致 / 文档数与向量数不匹配；
2 环境或依赖问题（embedder 起不来、库文件不存在、指纹不符且没给 ``--force``）。

⚠️ 两条 fail-closed：
* ``RAG_FAKE_EMBEDDER=1`` 时**拒绝** ``--rebuild``（哈希向量会把真索引覆盖掉，且现场看不出来）；
* 当前 embedder 指纹与库里记录不符时拒绝重建（那是"换模型"，正是要重建的理由，
  但必须先让人意识到自己在换模型 —— 加 ``--force`` 才继续）。
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import struct
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _stored_vectors(store) -> dict[str, list[float]]:
    """把 vec0 表里的向量原样读出来（体检用：算模长、算双向差集）。

    只走 ``_conn`` 这一条只读连接；表名取模块常量，不拼用户输入。
    """
    from rag.vector_store import VEC_TABLE

    rows = store._conn.execute(f"SELECT chunk_id, embedding FROM {VEC_TABLE}").fetchall()  # noqa: SLF001
    out: dict[str, list[float]] = {}
    for chunk_id, blob in rows:
        count = len(blob) // 4
        out[str(chunk_id)] = list(struct.unpack(f"<{count}f", blob))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="真重建（默认只体检，不写盘）")
    parser.add_argument("--check-only", action="store_true", help="只体检，且不一致时退出码 1")
    parser.add_argument("--backup", action="store_true", help="重建前先把 .db 拷一份（仅 --rebuild 有效）")
    parser.add_argument("--force", action="store_true", help="越过指纹不符这道 fail-closed")
    parser.add_argument("--limit-docs", type=int, default=0, help="只处理前 N 份文档（试手用）")
    args = parser.parse_args(argv)

    # Windows 控制台默认 GBK，重定向到文件时也一样 —— 本脚本的输出里有 `⇒` 与 `²`
    # 这类 GBK 装不下的字符，不重设就直接 UnicodeEncodeError 崩掉（实跑踩过一次，
    # 崩在体检结论那行，退出码还是 1，看起来像"发现不一致"，其实是没跑完）。
    # 与 ``core/tools/sandbox.py`` 给子进程加 ``-X utf8`` 是同一条纪律。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover - 被替换成非 TextIO 时
            pass

    if args.check_only and args.rebuild:
        print("--check-only 与 --rebuild 互斥", file=sys.stderr)
        return 2

    from config import get_settings
    from rag.embedder import create_embedder, fingerprint_of
    from rag.types import Chunk
    from rag.vector_store import SQLiteVecStore, create_vector_store

    settings = get_settings()
    configured = settings.db_path
    if configured is None:  # pragma: no cover - 默认值 always set，留这道闸是给自定义 Settings 的
        print("settings.db_path 未配置，没有可重建的库。", file=sys.stderr)
        return 2
    db_path = Path(configured)
    print(f"库文件：{db_path}（存在={db_path.is_file()}）  后端={settings.vector_store_backend}")
    if not db_path.is_file():
        print("库文件不存在：还没有可重建的索引。先起服务上传文档，或用 scripts/ 下的演示语料脚本。", file=sys.stderr)
        return 2

    from storage.db import Database

    database = Database(settings=settings)
    documents = database.list_documents(statuses=["ready"])
    if args.limit_docs > 0:
        documents = documents[: args.limit_docs]
    records = database.list_all_chunks()
    print(f"ready 文档 {len(documents)} 份 / chunks 表 {len(records)} 条")

    store = create_vector_store(settings, dim=settings.embedding_dim)
    stored = _stored_vectors(store)
    print(f"向量表 {len(stored)} 条（backend={store.backend_name()}）")

    # ---- 体检 1：双向差集（Q7-08 的两条孤儿路径） ----
    chunk_ids = {record.chunk_id for record in records}
    vector_ids = set(stored)
    only_chunks = sorted(chunk_ids - vector_ids)
    only_vectors = sorted(vector_ids - chunk_ids)
    print(f"有 chunk 无向量：{len(only_chunks)} 条  {only_chunks[:3]}")
    print(f"有向量无 chunk：{len(only_vectors)} 条  {only_vectors[:3]}")

    # ---- 体检 2：模长（换算式的前提） ----
    if stored:
        norms = [_norm(vector) for vector in stored.values()]
        print(
            f"向量模长 min={min(norms):.6f} max={max(norms):.6f} "
            f"⇒ {'全部单位化（1-d²/2 的前提成立）' if max(abs(n - 1) for n in norms) < 1e-3 else '存在非单位向量，换算式与排序都要重新讨论'}"
        )
        dims = {len(vector) for vector in stored.values()}
        print(f"维度集合：{dims}（配置 embedding_dim={settings.embedding_dim}）")

    consistent = not only_chunks and not only_vectors
    if not args.rebuild:
        print("体检模式：没有写任何东西。要重建请加 --rebuild（建议同时 --backup）。")
        if not consistent and args.check_only:
            print("⇒ 不一致，退出码 1", file=sys.stderr)
            store.close()
            return 1
        store.close()
        return 0

    # ---- 重建档：以下才会写盘 ----
    fake = os.environ.get("RAG_FAKE_EMBEDDER", "").strip().lower() in {"1", "true", "yes"}
    if fake:
        print(
            "RAG_FAKE_EMBEDDER=1：这是哈希桩向量，重建会把真索引覆盖成不可用的东西。拒绝执行。",
            file=sys.stderr,
        )
        store.close()
        return 2
    if not isinstance(store, SQLiteVecStore):
        print(f"本脚本的重建档只写了 sqlite-vec 后端（当前 {store.backend_name()}）。", file=sys.stderr)
        store.close()
        return 2

    embedder = create_embedder(settings)
    # 指纹必须按 ``rag/service.py::check_fingerprint`` **同一个表达式**算：
    # ``fingerprint_of(settings.embedding_model_name, settings.embedding_dim)``。
    # 这里曾经踩过一个自己的坑：写成 ``embedder.dim`` —— ``dim`` 在 embedder 上是
    # **方法不是属性**（``Protocol`` 里也这么声明），于是拿一个 bound method 去哈希，
    # 算出一个凭空的"指纹不符"把 fail-closed 触发了。API 检索闸读的是配置，
    # 脚本读的也必须是配置，否则就是第三个真值（R-28 那一族）。
    from rag.service import FINGERPRINT_KEY

    want = fingerprint_of(settings.embedding_model_name, settings.embedding_dim)
    recorded = {record.embedding_fingerprint for record in documents if record.embedding_fingerprint}
    meta = database.get_meta(FINGERPRINT_KEY)
    if meta:
        recorded.add(meta)
    if recorded and recorded != {want}:
        print(f"⚠️ 指纹不符：库里是 {sorted(recorded)}，当前配置算出 {want}", file=sys.stderr)
        if not args.force:
            print("换 embedder 正是需要重建的理由，但请确认后加 --force。", file=sys.stderr)
            store.close()
            return 2
        print("⇒ --force 已给，按新 embedder 全库重写。")
    else:
        print(f"指纹一致：{want}（与检索入口那道闸同一个表达式）")

    if args.backup:
        stamp = int(time.time())
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if src.is_file():
                dst = PROJECT_ROOT / "test-reports" / f"backup_{src.name}.{stamp}"
                dst.parent.mkdir(exist_ok=True)
                shutil.copy2(src, dst)
                print(f"已备份 {src.name} → {dst}")

    by_document: dict[str, list] = {}
    for record in records:
        by_document.setdefault(record.document_id, []).append(record)

    rewritten = 0
    for document in documents:
        rows = sorted(by_document.get(document.document_id, []), key=lambda r: r.seq)
        if not rows:
            print(f"  {document.document_id}：chunks 表里没有记录，跳过（该重建元数据而不是向量）")
            continue
        chunks = [
            Chunk(
                document_id=row.document_id,
                seq=row.seq,
                text=row.text,
                start_char=row.start_char,
                end_char=row.end_char,
                chunk_id=row.chunk_id,
            )
            for row in rows
        ]
        vectors = embedder.embed([chunk.text for chunk in chunks])
        store.delete_document(document.document_id)
        store.add(chunks, vectors)
        rewritten += len(chunks)
        print(f"  {document.document_id}（{document.filename}）：{len(chunks)} chunks 重嵌完成")

    after = _stored_vectors(store)
    print(f"重建写入 {rewritten} 条；向量表现在 {len(after)} 条")
    if len(after) != len({record.chunk_id for record in records}):
        print("⇒ 重建后条数与 chunks 表不等，请查上面跳过的文档", file=sys.stderr)
        store.close()
        return 1
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
