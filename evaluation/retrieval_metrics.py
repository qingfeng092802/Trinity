"""检索专项指标（M3 · T2）：纯函数，零 LLM 调用，可断网复算。

口径（m3_design.md §4.5 / D6 判分口径）：

* **文档级**而非 chunk 级：``retrieved_ids`` / ``expected_ids`` 都是 ``document_id``。
  chunk 级 id 在换分块的臂之间不可比（``chunk_id = f"{document_id}:{seq:04d}"``，
  重切分后 ``seq`` 全变），所以 E2b 三个臂只能比文档级指标；
* **期望集为空 → 返回 ``None``，不是 0**。拒答题的 ``expected_doc_ids`` 恒为空
  （见 ``scripts/build_golden_set.py`` 的 ``emit(answerable=False)``），
  把"无标准答案"当 0 分计入均值会人为压低指标，也让 nDCG 的 idcg=0 除零；
* **二值增益**：CMRC 是抽取式 QA，一个 chunk 要么属于 gold 篇要么不属于，
  没有分级相关性，所以 nDCG 用 gain=1，idcg 按 ``min(|expected|, k)`` 归一；
* 所有函数都接受任意可迭代对象，内部只比集合成员，不改动入参。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "hit_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
]


def _prepare(retrieved_ids: Sequence[str], expected_ids: Sequence[str]) -> tuple[list[str], frozenset[str]]:
    """截断到 k 由调用方负责（k 语义在各函数里）；这里只去重期望集。"""
    return list(retrieved_ids), frozenset(expected_ids)


def recall_at_k(retrieved_ids: Sequence[str], expected_ids: Sequence[str], k: int) -> float | None:
    """Top-k 覆盖了多少比例的标准答案篇章。

    Args:
        retrieved_ids: 按相关性降序的检索结果文档 id。
        expected_ids: 标准答案所在文档 id 集合。
        k: 截断位。

    Returns:
        ``[0,1]``；``expected_ids`` 为空（拒答题）时返回 ``None`` 表示"该指标不适用"。
    """
    retrieved, expected = _prepare(retrieved_ids, expected_ids)
    if not expected:
        return None
    if k < 1:
        return 0.0
    hits = len(set(retrieved[:k]) & expected)
    return hits / len(expected)


def precision_at_k(retrieved_ids: Sequence[str], expected_ids: Sequence[str], k: int) -> float | None:
    """Top-k 里有多少比例是相关的。

    ``expected_ids`` 为空时返回 ``None``（与 recall 同口径）；
    分母用 ``k`` 而非实际返回条数——召回不足时 precision 本就该被惩罚，
    用实际条数会把"只返回 1 条且命中"算成满分 1.0。
    """
    retrieved, expected = _prepare(retrieved_ids, expected_ids)
    if not expected:
        return None
    if k < 1:
        return 0.0
    hits = len(set(retrieved[:k]) & expected)
    return hits / k


def hit_at_k(retrieved_ids: Sequence[str], expected_ids: Sequence[str], k: int) -> bool:
    """Top-k 是否至少命中一篇（二值，McNemar 配对检验就用它做观测值）。"""
    retrieved, expected = _prepare(retrieved_ids, expected_ids)
    if not expected or k < 1:
        return False
    return bool(set(retrieved[:k]) & expected)


def mrr_at_k(retrieved_ids: Sequence[str], expected_ids: Sequence[str], k: int) -> float | None:
    """第一个命中的排名倒数；k 内无命中记 0（不是 None —— 这是"没找到"而非"不适用"）。"""
    retrieved, expected = _prepare(retrieved_ids, expected_ids)
    if not expected:
        return None
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], expected_ids: Sequence[str], k: int) -> float | None:
    """二值增益 nDCG@k。

    ``dcg = Σ 1/log2(rank+1)``（仅对相关文档累加），
    ``idcg`` 取"理想排序下前 ``min(|expected|, k)`` 名全相关"的同式和。
    idcg 为 0 只可能是 ``k<1``，此时返回 0 而非除零。
    """
    retrieved, expected = _prepare(retrieved_ids, expected_ids)
    if not expected:
        return None
    if k < 1:
        return 0.0
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in expected:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if idcg <= 0.0:  # pragma: no cover - k>=1 时 idcg 恒 >0，留着防未来改动
        return 0.0
    return dcg / idcg
