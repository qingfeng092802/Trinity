"""``rag/parsers.py`` 单元测试：三格式（pdf/md/txt）解析 + 扫描件报错 + 不支持格式（T02）。

覆盖（m2_design.md §5 T02 验证方式）：
* md 标题路径推进、txt 空行分段、pdf 多页文本提取；
* 区间不变量：``doc.text[start:start+len(block.text)] == block.text``；
* PDF 无文本层（扫描件）→ ``ParserError("文本层缺失，不支持扫描件")``；
* 不支持的扩展名 / 不存在的文件 → ``ParserError``。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.exceptions import ParserError
from rag.parsers import SUPPORTED_FORMATS, parse


DOC_ID = "doc-test000001"


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def test_parse_md_heading_paths(tmp_path: Path) -> None:
    md = tmp_path / "a.md"
    md.write_text(
        "# 第一章 总则\n"
        "本章说明适用范围。\n"
        "## 1.1 六类线\n"
        "六类线弯曲半径不小于 4 倍外径。\n",
        encoding="utf-8",
    )
    parsed = parse(md, DOC_ID)
    assert parsed.format == "md"
    assert [b.kind for b in parsed.blocks] == ["heading", "paragraph", "heading", "paragraph"]
    assert parsed.blocks[1].heading_path == ["第一章 总则"]
    assert parsed.blocks[3].heading_path == ["第一章 总则", "1.1 六类线"]
    # 标题块自身的 heading_path 含自己
    assert parsed.blocks[2].heading_path == ["第一章 总则", "1.1 六类线"]


def test_parse_md_offset_invariant(tmp_path: Path) -> None:
    md = tmp_path / "b.md"
    md.write_text("# 标题甲\n\n正文第一段。\n\n正文第二段更长一些，包含标点：；、。\n", encoding="utf-8")
    parsed = parse(md, DOC_ID)
    for block in parsed.blocks:
        assert parsed.text[block.start_char : block.start_char + len(block.text)] == block.text


# --------------------------------------------------------------------------- #
# TXT
# --------------------------------------------------------------------------- #
def test_parse_txt_paragraphs(tmp_path: Path) -> None:
    txt = tmp_path / "c.txt"
    txt.write_text("第一段内容。\n\n第二段内容，\n跨行书写。\n\n\n第三段。\n", encoding="utf-8")
    parsed = parse(txt, DOC_ID)
    assert parsed.format == "txt"
    texts = [block.text for block in parsed.blocks]
    assert texts == ["第一段内容。", "第二段内容，\n跨行书写。", "第三段。"]


# --------------------------------------------------------------------------- #
# PDF（用零依赖生成器造样例；扫描件场景用空白内容流）
# --------------------------------------------------------------------------- #
def test_parse_pdf_multi_page(tmp_path: Path) -> None:
    from tests.unit._rag_fixtures import build_text_pdf

    path = tmp_path / "f.pdf"
    build_text_pdf(path, pages=3, lines_per_page=5)
    parsed = parse(path, DOC_ID)
    assert parsed.format == "pdf"
    assert parsed.char_count > 500
    assert all(block.text.strip() for block in parsed.blocks)


def test_parse_pdf_scan_like_raises(tmp_path: Path) -> None:
    """无文本层的 PDF（空白页）必须报「文本层缺失，不支持扫描件」。"""
    from bench_index import escape_pdf_text

    path = tmp_path / "blank.pdf"
    # 手工构造一个只有空白 content stream 的合法 PDF
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Length 10 >>\nstream\nBT ET end\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    assert escape_pdf_text("()") == r"\(\)"  # 顺手覆盖转义

    with pytest.raises(ParserError, match="文本层缺失"):
        parse(path, DOC_ID)


# --------------------------------------------------------------------------- #
# 边界
# --------------------------------------------------------------------------- #
def test_parse_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "g.xyz"
    path.write_text("whatever", encoding="utf-8")
    with pytest.raises(ParserError, match="不支持的文档格式"):
        parse(path, DOC_ID)


def test_parse_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ParserError, match="文件不存在"):
        parse(tmp_path / "nope.md", DOC_ID)


def test_parse_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "h.txt"
    path.write_text("", encoding="utf-8")
    parsed = parse(path, DOC_ID)
    assert parsed.blocks == []
    assert parsed.text == ""


def test_supported_formats_whitelist() -> None:
    """白名单只有一份：解析侧那个名字**就是**受理侧的常量对象本身（Q7-09）。

    第二行才是判据：改前这里是 ``frozenset({"pdf", "md", "txt"})`` 的第二份字面量，
    ``==`` 恒真（两份集合内容当然相等），谁改了哪一处都不红。换成 ``is`` 之后，
    任何"再抄一份字面量"的写法都会在这里翻红 —— 值相等但对象不同。
    """
    from api.constants import DOC_SUPPORTED_FORMATS

    assert SUPPORTED_FORMATS == frozenset({"pdf", "md", "txt"})
    assert SUPPORTED_FORMATS is DOC_SUPPORTED_FORMATS, (
        "解析侧又写了一份字面量：受理侧加格式时这里不会跟着变"
    )
