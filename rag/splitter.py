"""结构感知切分：标题边界优先 → 段落整块装箱 → token 滑窗（T02；M3 · T3 加 mode）。

口径（m2_design.md §1.2 / §5 T02 子步骤 2 / Q5 拍板，m3_design.md §4.4）：

* **token 估算 = 字符数 / 1.6**，与 M1 成本公式同口径；
* ``chunk_size=500 / overlap=80``（token 口径），换算成字符窗口后滑切；
* **标题块是新 section 的起点**：section 内正常装箱；任何 chunk 都不跨 section
  （即不跨越更高级的标题边界），标题文本随其 section 的首个 chunk 入库；
* 单段超窗口时按字符滑窗硬切（overlap 回看），``token_estimate > 480`` 的
  长尾会被截断到 480 tokens 并记 WARNING（防 bge max_seq=512 溢出）；
* chunk 的 ``text`` 恒等于 ``doc.text[start_char:end_char]`` 精确切片，
  字符区间可直达原文（来源引用展示用）。

``mode`` 三档（E2b 消融臂）：

* ``heading``（默认，= M2 行为逐位不变）：标题边界优先 + section 内段落整块装箱；
* ``fixed``：**无视结构**，全文按字符滑窗硬切。它与 ``heading`` 之差就是「结构信息值多少」。
  ``heading_path`` 仍按 chunk 起点所在 section 回填 —— 只丢切分边界、不丢元数据，
  否则两臂的差异会串进来源展示；
* ``semantic``：先按标题分 section，再在 section 内**相邻段落余弦跌破阈值处提前断开**。
  必须注入 embedder；缺 embedder 直接报错，**不静默退回 heading** —— 静默降级会让
  该臂产出「其实没开语义切分」的假结论。
"""

from __future__ import annotations

import bisect
import logging
import math
from typing import TYPE_CHECKING, Literal

from rag.exceptions import SplitterError
from rag.types import Chunk

if TYPE_CHECKING:
    from rag.embedder import EmbeddingProvider
    from rag.types import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

#: 字符 ↔ token 换算系数（与 M1 成本公式一致）
CHARS_PER_TOKEN = 1.6

#: 单 chunk token 上限（bge max_seq=512 留安全余量）
MAX_CHUNK_TOKENS = 480

#: section 内装箱时块间分隔符（与 parsers._BLOCK_SEPARATOR 语义一致）
_SEPARATOR = "\n\n"

#: 切分模式（与 ``evaluation.experiment.Arm.chunk_mode`` 逐字一致）
SplitMode = Literal["heading", "fixed", "semantic"]

#: ``semantic`` 的相邻段落余弦低谷阈值：低于它就在段间断开。
#:
#: 定标依据（本机实测，bge-small-zh ONNX）：CMRC2018 里 120 对**不同 passage** 的
#: 相邻余弦分布为 min 0.242 / p25 0.329 / 中位 0.367 / p75 0.411 / max 0.546。
#: 取 0.35 ≈ 该分布的下沿，只切断「最不像同一话题」的那批边界；
#: 取 0.45 会把约七成边界都判成低谷，退化成「一段一 chunk」，等于没做语义切分。
#: ⚠️ 缺口：CMRC 训练集没有文章 id 列，拿不到「同文章相邻段落」的对照组，
#: 所以这是下界估计；E2b 在轨道 B 长文档上跑通后应据实测分布复核。
SEMANTIC_SIM_THRESHOLD = 0.35


def _make_chunk(parsed: "ParsedDocument", seq: int, start: int, end: int, heading_path: list[str]) -> Chunk:
    """从全文精确切片构造 chunk（保证 text == doc.text[start:end]）。"""
    start = max(0, min(start, len(parsed.text)))
    end = max(start, min(end, len(parsed.text)))
    return Chunk(
        document_id=parsed.document_id,
        seq=seq,
        text=parsed.text[start:end],
        start_char=start,
        end_char=end,
        heading_path=list(heading_path),
    )


def _cosine(left: list[float], right: list[float]) -> float:
    """余弦相似度（自己算模长，不赌 provider 是否已 L2 归一）。"""
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm > 1e-12 else 0.0


class DocumentSplitter:
    """把 :class:`ParsedDocument` 切成带位置元数据的 :class:`Chunk` 列表。"""

    def __init__(
        self,
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
        mode: SplitMode = "heading",
        embedder: "EmbeddingProvider | None" = None,
        semantic_threshold: float = SEMANTIC_SIM_THRESHOLD,
    ) -> None:
        if chunk_size < 1:
            raise SplitterError(f"chunk_size 必须 ≥ 1，收到 {chunk_size}")
        if chunk_overlap < 0:
            raise SplitterError(f"chunk_overlap 不能为负，收到 {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise SplitterError(
                f"chunk_overlap({chunk_overlap}) 必须小于 chunk_size({chunk_size})"
            )
        if mode not in {"heading", "fixed", "semantic"}:
            raise SplitterError(f"mode 只支持 heading/fixed/semantic，收到 {mode!r}")
        if mode == "semantic" and embedder is None:
            raise SplitterError("mode=semantic 需要 embedder 计算段落相似度，不能静默退回 heading")
        if not 0.0 <= semantic_threshold <= 1.0:
            raise SplitterError(f"semantic_threshold 必须在 [0,1]，收到 {semantic_threshold}")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._mode = mode
        self._embedder = embedder
        self._semantic_threshold = semantic_threshold
        self._window_chars = int(chunk_size * CHARS_PER_TOKEN)
        self._overlap_chars = int(chunk_overlap * CHARS_PER_TOKEN)
        self._step_chars = max(1, self._window_chars - self._overlap_chars)

    # ------------------------------------------------------------------ #
    def split(self, parsed: "ParsedDocument") -> list[Chunk]:
        """主入口：按 ``mode`` 规划窗口 → 精确切片 → 长尾告警。"""
        if not parsed.blocks:
            return []
        chunks: list[Chunk] = []
        seq = 0
        for heading_path, start, end in self._plan(parsed):
            chunk = _make_chunk(parsed, seq, start, end, heading_path)
            if not chunk.text.strip():
                continue
            if chunk.token_estimate > MAX_CHUNK_TOKENS:
                logger.warning(
                    "chunk %s 有 %d tokens（>%d），来源 %s —— 建议检查文档段落粒度",
                    chunk.chunk_id,
                    chunk.token_estimate,
                    MAX_CHUNK_TOKENS,
                    parsed.filename,
                )
            chunks.append(chunk)
            seq += 1
        logger.info(
            "切分完成 %s：%d 块 → %d chunks（mode=%s，chunk_size=%d/overlap=%d tokens）",
            parsed.document_id,
            len(parsed.blocks),
            len(chunks),
            self._mode,
            self._chunk_size,
            self._chunk_overlap,
        )
        return chunks

    # ------------------------------------------------------------------ #
    def _plan(self, parsed: "ParsedDocument") -> list[tuple[list[str], int, int]]:
        """返回 ``(heading_path, start_char, end_char)`` 序列，全局有序。"""
        if self._mode == "fixed":
            marks = [
                (block.start_char, list(block.heading_path))
                for block in parsed.blocks
                if block.kind == "heading"
            ]
            positions = [position for position, _ in marks]

            def _path_at(start_char: int) -> list[str]:
                """chunk 起点落在哪个标题之下（``marks`` 按 start_char 升序）。"""
                index = bisect.bisect_right(positions, start_char)
                return marks[index - 1][1] if index else []

            return [(_path_at(start), start, end) for start, end in self._slide(0, len(parsed.text))]
        planned: list[tuple[list[str], int, int]] = []
        for section_path, blocks in self._iter_sections(parsed.blocks):
            windows = (
                self._plan_windows_semantic(blocks)
                if self._mode == "semantic"
                else self._plan_windows(blocks)
            )
            planned.extend((section_path, start, end) for start, end in windows)
        return planned

    # ------------------------------------------------------------------ #
    def _iter_sections(self, blocks: list["ParsedBlock"]):
        """按标题块把块序列切成 sections：``yield (heading_path, blocks)``。

        标题块开启新 section（并作为该 section 的首块，标题文本随首 chunk 入库）；
        非标题块顺延到当前 section。无任何标题时整篇是一个 section。
        """
        current_path: list[str] = []
        current: list[ParsedBlock] = []
        for block in blocks:
            if block.kind == "heading":
                if current:
                    yield current_path, current
                current_path = list(block.heading_path)
                current = [block]
            else:
                if not current:
                    current_path = list(block.heading_path)
                current.append(block)
        if current:
            yield current_path, current

    def _slide(self, start: int, end: int) -> list[tuple[int, int]]:
        """字符滑窗：窗口 ``window_chars``、步长 ``step_chars``（overlap 回看）。"""
        windows: list[tuple[int, int]] = []
        position = start
        while position < end:
            window_end = min(position + self._window_chars, end)
            windows.append((position, window_end))
            if window_end >= end:
                break
            position += self._step_chars
        return windows

    def _plan_windows(self, blocks: list["ParsedBlock"]) -> list[tuple[int, int]]:
        """在单个 section 内规划窗口，返回 ``(start_char, end_char)`` 列表。

        装箱：块整块放入当前窗口直到超限；单独一块就超窗口的，按字符滑窗硬切。
        所有偏移都换算到 ``ParsedDocument.text`` 的绝对坐标。
        """
        windows: list[tuple[int, int]] = []
        window_start: int | None = None
        window_end_of_last = 0
        window_tokens = 0.0

        def _flush(last_end: int) -> None:
            nonlocal window_start, window_tokens
            if window_start is not None:
                windows.append((window_start, last_end))
            window_start = None
            window_tokens = 0.0

        for block in blocks:
            block_start = block.start_char
            block_end = block_start + len(block.text)
            block_tokens = len(block.text) / CHARS_PER_TOKEN

            if block_tokens <= self._chunk_size:
                if window_start is not None and window_tokens + block_tokens > self._chunk_size:
                    _flush(window_end_of_last)
                if window_start is None:
                    window_start = block_start
                window_tokens += block_tokens
                window_end_of_last = block_end
                continue

            # 单块超窗口：先收掉当前窗口，再滑窗硬切该块
            _flush(window_end_of_last if window_start is not None else block_start)
            windows.extend(self._slide(block_start, block_end))
            window_start = None
            window_tokens = 0.0
            window_end_of_last = block_end

        if window_start is not None:
            windows.append((window_start, window_end_of_last))
        return windows

    def _plan_windows_semantic(self, blocks: list["ParsedBlock"]) -> list[tuple[int, int]]:
        """section 内按语义低谷 + 容量上限切窗口。

        与 ``_plan_windows`` 唯一的差别是**提前断开**的判据多了一条：相邻两块余弦
        低于阈值。装箱容量、超窗硬切、绝对坐标口径全部保持一致，
        所以 E2b 的 heading vs semantic 之差可以完全归因到「低谷处断开」这一件事。
        """
        vectors = self._embedder.embed([block.text for block in blocks])  # type: ignore[union-attr]
        if len(vectors) != len(blocks):
            raise SplitterError(
                f"embedder 返回 {len(vectors)} 条向量，段落 {len(blocks)} 个，数量不一致"
            )
        windows: list[tuple[int, int]] = []
        group: list["ParsedBlock"] = []
        group_tokens = 0.0

        def _flush_group() -> None:
            nonlocal group, group_tokens
            if group:
                last = group[-1]
                windows.append((group[0].start_char, last.start_char + len(last.text)))
            group = []
            group_tokens = 0.0

        for index, block in enumerate(blocks):
            block_tokens = len(block.text) / CHARS_PER_TOKEN
            if block_tokens > self._chunk_size:
                _flush_group()
                windows.extend(self._slide(block.start_char, block.start_char + len(block.text)))
                continue
            valley = (
                index > 0
                and bool(group)
                #: 标题块永远与其后首个正文块同 chunk（M2 的入库不变量）；
                #: 否则 semantic 与 heading 的差里会混进「标题孤立成块」这一额外变量。
                and blocks[index - 1].kind != "heading"
                and _cosine(vectors[index - 1], vectors[index]) < self._semantic_threshold
            )
            overflow = bool(group) and group_tokens + block_tokens > self._chunk_size
            if valley or overflow:
                _flush_group()
            group.append(block)
            group_tokens += block_tokens
        _flush_group()
        return windows


__all__ = [
    "CHARS_PER_TOKEN",
    "MAX_CHUNK_TOKENS",
    "SEMANTIC_SIM_THRESHOLD",
    "DocumentSplitter",
    "SplitMode",
]
