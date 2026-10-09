"""M3 · T3-2 单测：``chunk_mode`` 三档（heading / fixed / semantic）。

heading 档的行为由 ``test_rag_splitter.py`` 全套守着（M2 回归）；本文件只管新增的两档，
并且**每个用例都同时跑一遍 heading 作为对照** —— E2b 的结论就是这两档与 heading 之差，
断言必须能证明「差异只来自切分边界，不来自别的」。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.exceptions import SplitterError  # noqa: E402
from rag.splitter import CHARS_PER_TOKEN, SEMANTIC_SIM_THRESHOLD, DocumentSplitter  # noqa: E402
from tests.unit._rag_fixtures import make_parsed  # noqa: E402

pytestmark = pytest.mark.unit

#: 主题簇向量：同簇余弦 1.0，异簇余弦 0.0（按段落首字判定，完全可控）
_CLUSTER_VECTORS = {"甲": [1.0, 0.0], "乙": [0.0, 1.0], "#": [1.0, 0.0], "丙": [1.0, 0.0]}


class ClusterEmbedder:
    """按文本首字给方向向量的桩；顺带记录调用次数与入参。"""

    def __init__(self, *, vectors: dict[str, list[float]] | None = None, count_mismatch: bool = False) -> None:
        self._vectors = vectors or _CLUSTER_VECTORS
        self._count_mismatch = count_mismatch
        self.calls = 0
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts = list(texts)
        result = [self._vectors.get(text[:1], [1.0, 0.0]) for text in texts]
        return result + [[1.0, 0.0]] if self._count_mismatch else result


def _doc(document_id: str = "doc-mode01"):
    """两章 × 600 字的结构文档（与 M2 的跨章测试同一形状）。"""
    return make_parsed(
        document_id,
        [
            ("# 第一章", "heading", []),
            ("甲" * 600, "paragraph", []),
            ("# 第二章", "heading", []),
            ("乙" * 600, "paragraph", []),
        ],
    )


# --------------------------------------------------------------------------- #
# fixed：无视结构
# --------------------------------------------------------------------------- #
def test_fixed_mode_crosses_heading_boundaries() -> None:
    parsed, _ = _doc()
    heading_chunks = DocumentSplitter(chunk_size=64, chunk_overlap=8).split(parsed)
    fixed = DocumentSplitter(chunk_size=64, chunk_overlap=8, mode="fixed").split(parsed)

    assert not any("甲" in c.text and "乙" in c.text for c in heading_chunks), "对照前提"
    assert any("甲" in c.text and "乙" in c.text for c in fixed), "fixed 必须按定长滑窗，不管章节边界"
    assert fixed[0].text == parsed.text[: fixed[0].end_char], "区间不变量在 fixed 下同样成立"


def test_fixed_windows_are_uniform_stepped_slices() -> None:
    parsed, _ = _doc()
    splitter = DocumentSplitter(chunk_size=64, chunk_overlap=8, mode="fixed")
    chunks = splitter.split(parsed)
    window_chars = int(64 * CHARS_PER_TOKEN)
    step_chars = window_chars - int(8 * CHARS_PER_TOKEN)

    assert chunks[0].start_char == 0
    for previous, current in zip(chunks, chunks[1:]):
        assert current.start_char - previous.start_char == step_chars
        assert len(current.text) <= window_chars
    assert chunks[-1].end_char == len(parsed.text), "最后一条必须收到文末，不留尾巴"


def test_fixed_mode_still_backfills_heading_path() -> None:
    """只丢边界、不丢元数据：来源展示在两臂间必须可比。"""
    parsed, _ = _doc()
    chunks = DocumentSplitter(chunk_size=64, chunk_overlap=8, mode="fixed").split(parsed)
    assert chunks[0].heading_path == ["第一章"]
    second_chapter = next(chunk for chunk in chunks if "乙" in chunk.text and "甲" not in chunk.text)
    assert second_chapter.heading_path == ["第二章"]
    assert chunks[0].seq == 0 and [c.seq for c in chunks] == list(range(len(chunks)))


def test_fixed_mode_on_empty_document() -> None:
    parsed, _ = make_parsed("doc-mode-empty", [])
    assert DocumentSplitter(mode="fixed").split(parsed) == []


# --------------------------------------------------------------------------- #
# semantic：段落相似度低谷处断开
# --------------------------------------------------------------------------- #
def _five_block_doc():
    return make_parsed(
        "doc-mode02",
        [
            ("# 章", "heading", []),
            ("甲" * 40, "paragraph", []),
            ("甲" * 40, "paragraph", []),
            ("乙" * 40, "paragraph", []),
            ("乙" * 40, "paragraph", []),
        ],
    )


def test_semantic_splits_at_the_valley_only() -> None:
    parsed, _ = _five_block_doc()
    control = DocumentSplitter(chunk_size=500, chunk_overlap=80).split(parsed)
    splitter = DocumentSplitter(chunk_size=500, chunk_overlap=80, mode="semantic", embedder=ClusterEmbedder())
    chunks = splitter.split(parsed)

    assert len(control) == 1, "对照前提：容量足够时 heading 只出 1 块"
    assert len(chunks) == 2, "只在甲/乙交界处多切一刀"
    assert chunks[0].text.startswith("# 章"), "标题仍随其 section 首个正文块入库"
    assert "乙" not in chunks[0].text and "甲" not in chunks[1].text
    for chunk in chunks:
        assert chunk.text == parsed.text[chunk.start_char : chunk.end_char]


def test_semantic_without_valleys_equals_heading() -> None:
    """全同向量 → 永不 cut → 结果必须与 heading 逐块相同（差异只可能来自低谷）。"""
    parsed, _ = _five_block_doc()
    same = ClusterEmbedder(vectors={char: [1.0, 0.0] for char in "甲乙#丙"})
    semantic = DocumentSplitter(chunk_size=500, chunk_overlap=80, mode="semantic", embedder=same).split(parsed)
    heading = DocumentSplitter(chunk_size=500, chunk_overlap=80).split(parsed)
    assert [(c.start_char, c.end_char) for c in semantic] == [(c.start_char, c.end_char) for c in heading]


def test_semantic_threshold_is_a_real_knob() -> None:
    parsed, _ = _five_block_doc()
    strict = DocumentSplitter(
        chunk_size=500, chunk_overlap=80, mode="semantic", embedder=ClusterEmbedder(), semantic_threshold=1.0
    )
    loose = DocumentSplitter(
        chunk_size=500, chunk_overlap=80, mode="semantic", embedder=ClusterEmbedder(), semantic_threshold=0.0
    )
    assert len(strict.split(parsed)) == 2, "阈值=1.0 → 只有同簇（余弦恰为 1）才不切断"
    assert len(loose.split(parsed)) == 1, "阈值=0 → 永不断开，退化成 heading"


def test_semantic_still_hard_splits_oversized_block() -> None:
    parsed, _ = make_parsed(
        "doc-mode03",
        [
            ("甲" * 1000, "paragraph", []),
            ("乙" * 20, "paragraph", []),
        ],
    )
    heading = DocumentSplitter(chunk_size=64, chunk_overlap=8).split(parsed)
    semantic = DocumentSplitter(
        chunk_size=64, chunk_overlap=8, mode="semantic", embedder=ClusterEmbedder()
    ).split(parsed)
    assert len(semantic) == len(heading), "超窗硬切两档共用同一条 _slide 路径"
    assert [c.start_char for c in semantic] == [c.start_char for c in heading]


def test_semantic_embeds_blocks_once_per_document() -> None:
    parsed, _ = _five_block_doc()
    embedder: Any = ClusterEmbedder()
    DocumentSplitter(chunk_size=500, chunk_overlap=80, mode="semantic", embedder=embedder).split(parsed)
    assert embedder.calls == 1, "整篇一次批量向量化，不得逐块调用"
    assert embedder.texts == [block.text for block in parsed.blocks], "向量化对象是段落块原文"


def test_semantic_rejects_count_mismatched_embedder() -> None:
    parsed, _ = _five_block_doc()
    splitter = DocumentSplitter(
        chunk_size=500,
        chunk_overlap=80,
        mode="semantic",
        embedder=ClusterEmbedder(count_mismatch=True),
    )
    with pytest.raises(SplitterError, match="数量不一致"):
        splitter.split(parsed)


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #
def test_mode_and_threshold_validation() -> None:
    with pytest.raises(SplitterError, match="mode"):
        DocumentSplitter(mode="parent_child")
    with pytest.raises(SplitterError, match="semantic_threshold"):
        DocumentSplitter(mode="semantic", embedder=ClusterEmbedder(), semantic_threshold=1.5)
    with pytest.raises(SplitterError, match="需要 embedder"):
        DocumentSplitter(mode="semantic")


def test_default_threshold_is_the_documented_constant() -> None:
    """默认值只有一处定义，别在调用方复制粘贴一遍（改了会静默不一致）。"""
    parsed, _ = _five_block_doc()
    explicit = DocumentSplitter(
        mode="semantic", embedder=ClusterEmbedder(), semantic_threshold=SEMANTIC_SIM_THRESHOLD
    )
    default = DocumentSplitter(mode="semantic", embedder=ClusterEmbedder())
    assert [c.end_char for c in explicit.split(parsed)] == [c.end_char for c in default.split(parsed)]
