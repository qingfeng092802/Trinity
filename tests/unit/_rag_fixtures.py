"""T02 单元测试共享夹具：文本 PDF 生成器 + ParsedDocument 构造器。

PDF 生成器复用 ``scripts/bench_index.py`` 的零依赖实现（单一来源，bench 与
测试共用以避免两份漂移的 PDF 写法）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
for _path in (str(PROJECT_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from bench_index import build_text_pdf, escape_pdf_text  # noqa: E402,F401  (re-export)


def make_parsed(document_id: str, blocks: list[tuple[str, str, list[str]]]):
    """按 parsers 的拼接语义构造 ParsedDocument。

    Args:
        blocks: ``(text, kind, heading_path)`` 三元组列表；
            ``kind`` 传 ``"heading"`` 的块会按层级自动推进 heading_path，
            与 :func:`rag.parsers._BlockCollector.push_heading` 同语义。

    Returns:
        ``(parsed, block_specs)``——block_specs 是补全了 heading_path 的
        ``(text, kind, heading_path)``，供用例直接断言。
    """
    from rag.types import ParsedBlock, ParsedDocument

    stack: list[str] = []
    specs: list[tuple[str, str, list[str]]] = []
    parsed_blocks: list[ParsedBlock] = []
    offset = 0
    for text, kind, _path in blocks:
        if kind == "heading":
            level = text.count("#", 0, text.find(" ") if " " in text else len(text)) or 1
            title = text.lstrip("#").strip()
            del stack[level - 1 :]
            stack.append(title)
            current = list(stack)
        else:
            current = list(stack)
        specs.append((text.strip(), kind, current))
        parsed_blocks.append(
            ParsedBlock(text=text.strip(), kind=kind, start_char=offset, heading_path=list(current))
        )
        offset += len(text.strip()) + 2  # "\n\n"
    parsed = ParsedDocument(
        document_id=document_id,
        filename=f"{document_id}.md",
        format="md",
        source_path=Path(f"/tmp/{document_id}.md"),
        blocks=parsed_blocks,
        text="\n\n".join(block.text for block in parsed_blocks),
    )
    return parsed, specs


__all__ = ["build_text_pdf", "escape_pdf_text", "make_parsed"]
