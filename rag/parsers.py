"""文档解析：pdf / md / txt **三格式** → :class:`ParsedDocument`（T02）。

**2026-09-21 收敛决策**：原先支持 pdf/md/docx/txt/html 五格式。docx 要额外背
python-docx、html 要自己写标签状态机，两条链路的维护成本与它们带来的样本量不匹配，
故收敛到单机零运维前提下真正跑得通的三种：``pdf``（pypdf 文本层）/ ``md`` / ``txt``。

设计要点（m2_design.md §5 T02 子步骤 1 / §1.2 选型）：

* 按扩展名分发（不区分大小写），解析器只认白名单 ``SUPPORTED_FORMATS``；
  未知扩展名的 422 拦截在 API 路由层做，这里统一抛 :class:`ParserError`。
* 输出是**结构块序列**（标题边界优先，其次段落），切分器据此做结构感知切分；
  块的 ``start_char`` 指向 ``ParsedDocument.text`` 中的精确偏移，保证
  ``doc.text[start:start + len(block.text)] == block.text``（splitter 的区间
  计算依赖这条不变量，测试有覆盖）。
* 扫描件（PDF 无文本层）→ ``ParserError("文本层缺失，不支持扫描件")``，OCR 明确不做。
* 重依赖（pypdf）全部**函数体内 import**（懒加载纪律 §7.4）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from api.constants import DOC_SUPPORTED_FORMATS
from rag.exceptions import ParserError
from rag.types import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

#: 支持的格式白名单（小写扩展名，不含点）。
#: **唯一来源 = ``api.constants.DOC_SUPPORTED_FORMATS``**（Q7-09，2026-10-02）。
#: 改前这里是第二份字面量 ``frozenset({"pdf", "md", "txt"})``，与受理侧的一致性
#: 全靠一句注释"保持一致" —— 那种一致在任何一处加回 docx 时都不会报错，只会让
#: 文档被**受理**、异步索引当场失败。
#: 引用 ``api.constants`` 不算"反向依赖 api 层"：本仓的口径是
#: "``api.constants`` 是全项目唯一常量源"（见 ``rag/service.py`` 头部那段 §1.3
#: 依赖方向说明的后半句），``rag/service.py`` 自己也从这里 import 同一个常量。
#: 名字保留 ``SUPPORTED_FORMATS`` 是给解析层与既有用例的本地读法，值同一个对象。
SUPPORTED_FORMATS: frozenset[str] = DOC_SUPPORTED_FORMATS

#: Markdown 标题行：行首 1-6 个 ``#`` + 空格
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

#: 块与块之间写入全文时的分隔符（splitter 依赖同一常量语义）
_BLOCK_SEPARATOR = "\n\n"

#: PDF 全文低于该字符数视为无文本层（扫描件）
_MIN_PDF_CHARS = 10


# --------------------------------------------------------------------------- #
# 内部：块收集器（各格式共用 —— 统一维护 start_char 与 heading 路径）
# --------------------------------------------------------------------------- #
class _BlockCollector:
    """按顺序收块，并维护「当前标题栈」；负责全文拼接与偏移记录。"""

    def __init__(self) -> None:
        self._blocks: list[ParsedBlock] = []
        self._heading_stack: list[str] = []
        self._offset = 0

    @property
    def heading_path(self) -> list[str]:
        """当前生效的标题路径（栈的浅拷贝）。"""
        return list(self._heading_stack)

    def push_heading(self, level: int, title: str) -> None:
        """进入一级标题：裁剪栈到 ``level - 1`` 再压入（标题块本身也收进块序列）。"""
        title = title.strip()
        if not title:
            return
        del self._heading_stack[level - 1 :]
        self._heading_stack.append(title)
        self.add_block(title, kind="heading")

    def add_block(self, text: str, *, kind: str = "paragraph") -> None:
        """收一个块；空块静默忽略。"""
        cleaned = text.strip()
        if not cleaned:
            return
        self._blocks.append(
            ParsedBlock(text=cleaned, kind=kind, start_char=self._offset, heading_path=list(self._heading_stack))
        )
        self._offset += len(cleaned) + len(_BLOCK_SEPARATOR)

    def finish(self, *, document_id: str, filename: str, fmt: str, source_path: Path) -> ParsedDocument:
        """产出最终 :class:`ParsedDocument`（text 为块的精确拼接视图）。"""
        text = _BLOCK_SEPARATOR.join(block.text for block in self._blocks)
        return ParsedDocument(
            document_id=document_id,
            filename=filename,
            format=fmt,
            source_path=source_path,
            blocks=self._blocks,
            text=text,
        )


def _split_paragraphs(raw: str) -> list[str]:
    """按空行切段，段内保留换行。"""
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in raw.splitlines():
        if line.strip():
            buffer.append(line)
        elif buffer:
            paragraphs.append("\n".join(buffer))
            buffer = []
    if buffer:
        paragraphs.append("\n".join(buffer))
    return paragraphs


# --------------------------------------------------------------------------- #
# 五格式实现
# --------------------------------------------------------------------------- #
def _parse_txt(path: Path, collector: _BlockCollector) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    for paragraph in _split_paragraphs(raw):
        collector.add_block(paragraph)


def _parse_md(path: Path, collector: _BlockCollector) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    buffer: list[str] = []
    for line in raw.splitlines():
        match = _MD_HEADING_RE.match(line.strip())
        if match:
            if buffer:
                collector.add_block("\n".join(buffer))
                buffer = []
            level = len(match.group(1))
            collector.push_heading(level, match.group(2))
        elif line.strip():
            buffer.append(line)
        elif buffer:
            collector.add_block("\n".join(buffer))
            buffer = []
    if buffer:
        collector.add_block("\n".join(buffer))


def _parse_pdf(path: Path, collector: _BlockCollector) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖由 pyproject 保证
        raise ParserError(f"pypdf 未安装，无法解析 PDF：{exc}") from exc
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - 损坏/加密 PDF 统一编码为 ParserError
        raise ParserError(f"PDF 解析失败（文件可能损坏或加密）：{exc}") from exc
    full_text = "\n".join(pages).strip()
    if len(full_text) < _MIN_PDF_CHARS:
        raise ParserError("文本层缺失，不支持扫描件")
    for page in pages:
        for paragraph in _split_paragraphs(page):
            collector.add_block(paragraph)


_PARSERS = {
    "pdf": _parse_pdf,
    "md": _parse_md,
    "txt": _parse_txt,
}


# --------------------------------------------------------------------------- #
# 公开入口
# --------------------------------------------------------------------------- #
def parse(file_path: Path, document_id: str) -> ParsedDocument:
    """按扩展名分发解析。

    Args:
        file_path: 源文件路径（须已存在）。
        document_id: 归属文档 id（``doc-<hex12>``）。

    Returns:
        解析产物（块序列 + 全文拼接视图）。

    Raises:
        ParserError: 扩展名不在白名单 / 文件不存在 / 格式损坏 / 文本层缺失。
    """
    path = Path(file_path)
    if not path.is_file():
        raise ParserError(f"文件不存在：{path}")
    fmt = path.suffix.lstrip(".").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ParserError(f"不支持的文档格式：{fmt}（白名单：{sorted(SUPPORTED_FORMATS)}）")
    filename = path.name
    if not filename:
        raise ParserError(f"文件名无效：{path}")

    collector = _BlockCollector()
    try:
        _PARSERS[fmt](path, collector)
    except ParserError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解析层兜底：任何异常都编码为 ParserError
        raise ParserError(f"{fmt} 解析异常：{type(exc).__name__}: {exc}") from exc

    parsed = collector.finish(document_id=document_id, filename=filename, fmt=fmt, source_path=path)
    logger.info(
        "解析完成 %s：%s，%d 块 / %d 字符", document_id, filename, len(parsed.blocks), parsed.char_count
    )
    return parsed


__all__ = ["SUPPORTED_FORMATS", "parse"]
