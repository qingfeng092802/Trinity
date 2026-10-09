"""``rag/splitter.py`` 单元测试：标题边界 / overlap / 参数校验 / 截断（T02）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.exceptions import SplitterError
from rag.splitter import CHARS_PER_TOKEN, DocumentSplitter
from tests.unit._rag_fixtures import make_parsed


def _long_paragraph(chars: int, seed: str = "甲") -> str:
    return (seed * 8 + "，") * (chars // 9 + 1)


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #
def test_invalid_params_raise() -> None:
    with pytest.raises(SplitterError):
        DocumentSplitter(chunk_size=0)
    with pytest.raises(SplitterError):
        DocumentSplitter(chunk_size=64, chunk_overlap=64)  # overlap == size
    with pytest.raises(SplitterError):
        DocumentSplitter(chunk_size=64, chunk_overlap=-1)


# --------------------------------------------------------------------------- #
# 标题边界
# --------------------------------------------------------------------------- #
def test_chunks_never_cross_top_heading() -> None:
    parsed, _ = make_parsed(
        "doc-splitter01",
        [
            ("# 第一章", "heading", []),
            ("甲" * 600, "paragraph", []),
            ("# 第二章", "heading", []),
            ("乙" * 600, "paragraph", []),
        ],
    )
    splitter = DocumentSplitter(chunk_size=64, chunk_overlap=8)
    chunks = splitter.split(parsed)
    assert chunks, "应产出 chunk"
    # 任何 chunk 都不得同时含两章的正文
    for chunk in chunks:
        has_first = "甲" in chunk.text
        has_second = "乙" in chunk.text
        assert not (has_first and has_second), f"chunk 跨章：{chunk.text[:40]}"
    # 标题文本随其 section 首个 chunk 入库
    assert any("第一章" in chunk.text for chunk in chunks)
    assert any("第二章" in chunk.text for chunk in chunks)


def test_small_chunk_size_works() -> None:
    parsed, _ = make_parsed(
        "doc-splitter02",
        [
            ("# 标题", "heading", []),
            (_long_paragraph(1200), "paragraph", []),
        ],
    )
    splitter = DocumentSplitter(chunk_size=64, chunk_overlap=16)
    chunks = splitter.split(parsed)
    assert len(chunks) >= 3
    assert all(chunk.token_estimate > 0 for chunk in chunks)


# --------------------------------------------------------------------------- #
# overlap
# --------------------------------------------------------------------------- #
def test_overlap_exists_between_windows() -> None:
    text = _long_paragraph(1600)
    parsed, _ = make_parsed("doc-splitter03", [(text, "paragraph", [])])
    splitter = DocumentSplitter(chunk_size=100, chunk_overlap=40)
    chunks = splitter.split(parsed)
    assert len(chunks) >= 2
    for prev, nxt in zip(chunks, chunks[1:]):
        # 相邻窗口应共享内容（overlap>0 的直接证据）：后窗的开头出现在前窗中
        assert nxt.text[:20] in prev.text or nxt.start_char < prev.end_char
    # offset 连续性：窗口推进步长 = (size - overlap) * 1.6
    for prev, nxt in zip(chunks, chunks[1:]):
        expected_step = int(100 * CHARS_PER_TOKEN) - int(40 * CHARS_PER_TOKEN)
        assert nxt.start_char - prev.start_char <= expected_step + len(prev.text)


def test_zero_overlap_no_backtrack() -> None:
    text = _long_paragraph(1200)
    parsed, _ = make_parsed("doc-splitter04", [(text, "paragraph", [])])
    splitter = DocumentSplitter(chunk_size=100, chunk_overlap=0)
    chunks = splitter.split(parsed)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_char >= prev.end_char


# --------------------------------------------------------------------------- #
# 区间不变量与元数据
# --------------------------------------------------------------------------- #
def test_chunk_text_matches_slice_and_seq() -> None:
    parsed, _ = make_parsed(
        "doc-splitter05",
        [
            ("# A", "heading", []),
            (_long_paragraph(400, "丙"), "paragraph", []),
            ("# B", "heading", []),
            (_long_paragraph(400, "丁"), "paragraph", []),
        ],
    )
    splitter = DocumentSplitter(chunk_size=80, chunk_overlap=10)
    chunks = splitter.split(parsed)
    assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.text == parsed.text[chunk.start_char : chunk.end_char]
        assert chunk.chunk_id == f"{chunk.document_id}:{chunk.seq:04d}"
    # heading_path 快照
    first_of_b = next(chunk for chunk in chunks if "B" in chunk.text)
    assert first_of_b.heading_path == ["B"]


def test_empty_document_returns_empty() -> None:
    parsed, _ = make_parsed("doc-splitter06", [])
    splitter = DocumentSplitter(chunk_size=500, chunk_overlap=80)
    assert splitter.split(parsed) == []


def test_token_estimate_uses_1_6_factor() -> None:
    text = "字" * 800  # 800 字符 → ~500 tokens
    parsed, _ = make_parsed("doc-splitter07", [(text, "paragraph", [])])
    splitter = DocumentSplitter(chunk_size=100, chunk_overlap=10)
    chunks = splitter.split(parsed)
    for chunk in chunks:
        expected = int(len(chunk.text) / 1.6)
        assert chunk.token_estimate == expected
