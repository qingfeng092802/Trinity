#!/usr/bin/env python
"""50 页 PDF 索引计时基准（T02 收口，验收 A1 证据）。

流程（m2_design.md §5 T02 子步骤 6 / §1.6 吞吐估算）：

    生成 50 页文本型 PDF（零依赖手写 PDF 1.4，Helvetica 文本流）
    → parse（pypdf）→ split（500/80）→ embed（真实 fastembed，含首次加载）
    → store（sqlite-vec，临时库）→ KNN 查询 → 分阶段计时 → 对照 120s 指标

用法::

    .venv\\Scripts\\python.exe scripts\\bench_index.py            # 真实 embedder
    .venv\\Scripts\\python.exe scripts\\bench_index.py --fake    # MockEmbedder（无网快跑）
    .venv\\Scripts\\python.exe scripts\\bench_index.py --pages 50 --keep

说明：生成 PDF 用 ASCII 文本（Helvetica 基础字体），解析/切分/向量化路径与
中文 PDF 完全一致（pypdf 按页提取、bge 按字符切窗），吞吐结论可迁移。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.embedder import EmbeddingProvider, FastembedBgeEmbedder, MockEmbedder  # noqa: E402
from rag.parsers import parse  # noqa: E402
from rag.splitter import DocumentSplitter  # noqa: E402
from rag.vector_store import SQLiteVecStore  # noqa: E402

#: 每页行数与每行字符数（612pt 宽 - 80pt 边距，Helvetica 10pt ≈ 96 字符/行）
LINES_PER_PAGE = 40
CHARS_PER_LINE = 90

_FILLER = (
    "The quick brown fox jumps over the lazy dog while the energy dashboard "
    "streams telemetry from the microgrid controller into the analytics buffer."
)


def escape_pdf_text(text: str) -> str:
    """PDF 字符串字面量转义。"""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_text_pdf(path: Path, *, pages: int, lines_per_page: int = LINES_PER_PAGE) -> int:
    """生成最小可读的文本型 PDF（PDF 1.4 + Helvetica），返回总字符数。

    零第三方依赖：catalog/pages/font 三个基础对象 + 每页一对 page/content 对象，
    xref 偏移手工计算——pypdf 完全可解析。
    """
    if pages < 1:
        raise ValueError(f"pages 必须 ≥ 1，收到 {pages}")
    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    total_chars = 0
    for page_index in range(pages):
        lines = [
            (
                f"[{page_index:03d}.{line:03d}] {_FILLER}"[:CHARS_PER_LINE]
            ).ljust(CHARS_PER_LINE)
            for line in range(lines_per_page)
        ]
        total_chars += sum(len(line) for line in lines)
        body = "".join(f"({escape_pdf_text(line)}) Tj T*\n" for line in lines)
        stream = f"BT\n/F1 10 Tf\n12 TL\n40 756 Td\n{body}ET".encode("ascii")
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * page_index} 0 R >>"
        ).encode("ascii")
        content_dict = (
            f"<< /Length {len(stream)} >>\nstream\n{stream.decode('ascii')}\nendstream"
        ).encode("ascii")
        objects.append(page_dict)
        objects.append(content_dict)

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return total_chars


def _make_embedder(fake: bool) -> tuple[EmbeddingProvider, int]:
    if fake:
        return MockEmbedder(dim=8), 8
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


def main() -> int:
    parser = argparse.ArgumentParser(description="50 页 PDF 索引计时基准")
    parser.add_argument("--pages", type=int, default=50)
    parser.add_argument("--fake", action="store_true", help="用 MockEmbedder（跳过真实模型）")
    parser.add_argument("--keep", action="store_true", help="保留临时产物供检查")
    args = parser.parse_args()

    scratch = PROJECT_ROOT / "data" / ".test-scratch" / "bench_index"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    pdf_path = scratch / "bench_50p.pdf"
    db_path = scratch / "bench.db"

    timings: list[tuple[str, float]] = []

    def _stage(name: str, func):
        started = time.perf_counter()
        result = func()
        elapsed = time.perf_counter() - started
        timings.append((name, elapsed))
        return result

    total_chars = _stage("生成 PDF", lambda: build_text_pdf(pdf_path, pages=args.pages))
    document_id = "doc-bench000001"

    parsed = _stage("① parse（pypdf）", lambda: parse(pdf_path, document_id))
    splitter = DocumentSplitter(chunk_size=500, chunk_overlap=80)
    chunks = _stage("② split（500/80）", lambda: splitter.split(parsed))
    embedder, dim = _make_embedder(args.fake)
    vectors = _stage("③ embed（含首次模型加载）", lambda: embedder.embed([c.text for c in chunks]))
    store = _stage("④ 开向量库", lambda: SQLiteVecStore(db_path, dim=dim))
    _stage("⑤ 向量入库", lambda: store.add(chunks, vectors))
    probe = vectors[0]
    hits = _stage("⑥ KNN top-5", lambda: store.query(probe, 5))
    store.close()

    total = sum(seconds for _, seconds in timings)
    print("=" * 68)
    print(f"bench_index：{args.pages} 页 PDF / {total_chars} 字符 / {len(chunks)} chunks")
    print(f"embedder：{embedder.name()}（dim={dim}）  向量库：{store.backend_name()}")
    print("-" * 68)
    for name, seconds in timings:
        print(f"  {name:<28s} {seconds:8.2f}s")
    print("-" * 68)
    print(f"  {'合计':<28s} {total:8.2f}s   （120s 指标 {'PASS' if total <= 120 else 'FAIL'}）")
    print(f"  KNN top-1：{hits[0][0] if hits else '无'}（相似度 {hits[0][1]:.4f}）" if hits else "  KNN：无命中")
    print("=" * 68)
    if not args.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"临时产物保留在：{scratch}")
    return 0 if total <= 120 else 1


if __name__ == "__main__":
    raise SystemExit(main())
