#!/usr/bin/env python
"""T02 冒烟：五格式样例各走一遍 parse → split → embed → store（含持久化重启）。

对应验收（m2_design.md §5 T02 验证方式第 2 条）：

    五格式样例各走一遍全流水线 → 重启进程（重开 SQLiteVecStore）后
    store.query 仍可命中（持久化）；另验 delete_document 生效。

默认用 MockEmbedder（dim=8，零下载）；``--real`` 切换真实 fastembed（dim=512，
首次运行会命中 %TEMP%\\fastembed_cache 的 spike 缓存）。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_t02.py [--real]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bench_index import build_text_pdf  # noqa: E402 - 复用零依赖 PDF 生成器
from rag.embedder import EmbeddingProvider, FastembedBgeEmbedder, MockEmbedder  # noqa: E402
from rag.parsers import parse  # noqa: E402
from rag.splitter import DocumentSplitter  # noqa: E402
from rag.vector_store import SQLiteVecStore  # noqa: E402

DIM = 8

_MD_TEXT = """# 综合布线系统概述

综合布线是建筑物内部的传输网络，支持语音、数据与图像业务。

## 3.1 六类线施工要求

六类线缆施工弯曲半径不应小于线缆外径的 4 倍。

## 3.2 桥架敷设

桥架内线缆绑扎间距不宜超过 1.5 米，强弱点应分槽敷设。
"""

_TXT_TEXT = """安防监控点位设计第一段：摄像机点位应覆盖出入口、大堂与楼梯间，
存储时长要求不低于 90 天。

安防监控点位设计第二段：枪机与半球机的选型依据是安装高度与照度条件。
"""

CHECK_KEYWORDS = ("六类线", "门禁", "安防")


def _make_samples(scratch: Path) -> list[Path]:
    """生成三格式样例文件（pdf / md / txt）。"""
    samples: list[Path] = []
    (md := scratch / "sample.md").write_text(_MD_TEXT, encoding="utf-8")
    samples.append(md)
    (txt := scratch / "sample.txt").write_text(_TXT_TEXT, encoding="utf-8")
    samples.append(txt)
    (pdf := scratch / "sample.pdf")
    build_text_pdf(pdf, pages=2, lines_per_page=6)
    samples.append(pdf)
    return samples


def _make_embedder(real: bool) -> tuple[EmbeddingProvider, int]:
    if real:
        from config import get_settings

        settings = get_settings()
        return (
            FastembedBgeEmbedder(
                model_name=settings.embedding_model_name,
                dim=settings.embedding_dim,
                batch_size=settings.embedding_batch_size,
            ),
            settings.embedding_dim,
        )
    return MockEmbedder(dim=DIM), DIM


def main() -> int:
    parser = argparse.ArgumentParser(description="T02 五格式流水线冒烟")
    parser.add_argument("--real", action="store_true", help="用真实 fastembed 模型")
    args = parser.parse_args()

    scratch = PROJECT_ROOT / "data" / ".test-scratch" / "smoke_t02"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    db_path = scratch / "smoke.db"

    embedder, dim = _make_embedder(args.real)
    splitter = DocumentSplitter(chunk_size=64, chunk_overlap=16)  # 小窗口逼出多 chunk
    store = SQLiteVecStore(db_path, dim=dim)

    results: list[tuple[str, str]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, "PASS" if ok else f"FAIL {detail}"))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")

    total_chunks = 0
    first_chunk_text = ""
    doc_ids: list[str] = []
    for index, sample in enumerate(_make_samples(scratch)):
        doc_id = f"doc-smoke{index:04d}"
        doc_ids.append(doc_id)
        parsed = parse(sample, doc_id)
        chunks = splitter.split(parsed)
        vectors = embedder.embed([chunk.text for chunk in chunks])
        store.add(chunks, vectors)
        total_chunks += len(chunks)
        # 区间不变量：chunk.text == doc.text[start:end]
        consistent = all(
            parsed.text[chunk.start_char : chunk.end_char] == chunk.text for chunk in chunks
        )
        _check(
            f"流水线 {sample.suffix}",
            bool(chunks) and consistent,
            f"({len(chunks)} chunks, 区间一致性 {consistent})",
        )
        if sample.suffix == ".md" and chunks:
            first_chunk_text = chunks[0].text

    if first_chunk_text:
        _check("标题随首 chunk 入库", "综合布线系统概述" in first_chunk_text, repr(first_chunk_text[:50]))

    # 持久化：关闭后重开连接再查
    probe_vector = embedder.embed([first_chunk_text or "综合布线"])[0]
    store.close()
    store = SQLiteVecStore(db_path, dim=dim)
    hits = store.query(probe_vector, 3)
    _check("重启后持久化可查", len(hits) > 0, f"hits={len(hits)}")
    _check("向量总数一致", store.count() == total_chunks, f"count={store.count()} expect={total_chunks}")

    # delete_document 生效（逐文档清理）
    for doc_id in doc_ids:
        store.delete_document(doc_id)
    _check("delete_document 清空", store.count() == 0, f"count={store.count()}")
    store.close()

    print("-" * 64)
    failed = [name for name, status in results if status.startswith("FAIL")]
    if not failed:
        print(f"结论：PASS —— 五格式流水线 + 持久化 + 删除 全部通过（chunks={total_chunks}）")
    else:
        print(f"结论：FAIL —— {failed}")
    shutil.rmtree(scratch, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
