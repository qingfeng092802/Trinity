"""交叉编码重排（M3 · T3，G2）：对融合后的候选集精排。

口径（m3_design.md §4.2 / §8.3）：

* **插入点在截断之前**：只作用于 candidate pool（``fetch_k=20 → top_k=5``）。
  放到 ``service.search`` 之后是错的 —— 那时结果已被砍到 5 条，精排没有候选空间；
* **``SearchHit.score`` 语义不变**（仍是融合相对分），精排分单独记在
  :attr:`~rag.types.SearchHit.rerank_score`。M2 已有的报表/API 消费的是 ``score``，
  复用同一字段会让"加了重排"与"换了融合口径"两件事混在一起，回归对比也做不了；
  但**返回列表的顺序就是精排后的顺序**（这是精排的实际产物）；
* 惰性加载权重（重排模型 CPU 加载实测 129 s，绝不能进 API 启动路径）；
* 长文本按 ``max_seq`` 截断 —— 这正是 v3 失败分类里"重排误排：Reranker 对长文本截断"的成因，
  截断条数会被计数并在 health_check 里报出来，让实验报告能直接引用。

耗时提醒（本机实测，别引用外部文档的数字）：bge-reranker-base 在 8 线程 CPU 上
20 候选/查询 ≈ **6.27 s**（p95 6.39 s）。它不是"加 440ms"，是加一个数量级。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Protocol, runtime_checkable

from rag.exceptions import RagError
from rag.types import SearchHit

logger = logging.getLogger(__name__)

#: 懒加载纪律：torch/transformers 只在函数体内 import
#: bge-reranker 系列的 max_seq（base 与 v2-m3 都是 512）
RERANK_MAX_SEQ = 512

#: 打分批大小；CPU 上过大会把内存顶满且没有吞吐收益
DEFAULT_RERANK_BATCH = 8

#: 模型名 → 仓库地址（留空则按原样传给 transformers，允许本地目录）
_RERANK_REPO_PREFIX = ""


class RerankerError(RagError):
    """重排失败。``stage`` 固定为 ``reranking``。

    与 ``EmbeddingError`` 同级纪律：**臂级失败要让该臂整体失败**，绝不静默退回
    "不精排"继续跑 —— 那样该臂会产出"看起来正常其实缺一个组件"的假结论（m3_design.md §8.5-2）。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="reranking")


@runtime_checkable
class Reranker(Protocol):
    """精排接口；``candidates`` 顺序即输入顺序，返回值为新排序。"""

    def name(self) -> str: ...

    def rerank(self, query: str, candidates: list[SearchHit], *, top_n: int) -> list[SearchHit]: ...

    def health_check(self) -> tuple[bool, str]: ...


class NoopReranker:
    """不精排（基线臂 / E3 的"无"对照）：原样截断，零成本。"""

    def name(self) -> str:
        return "none"

    def rerank(self, query: str, candidates: list[SearchHit], *, top_n: int) -> list[SearchHit]:
        return candidates[: max(0, top_n)]

    def health_check(self) -> tuple[bool, str]:
        return True, "未启用重排（基线）"


class CrossEncoderReranker:
    """transformers 交叉编码打分：``[CLS] query [SEP] passage [SEP]`` → 单 logit。

    刻意不走 ``sentence-transformers.CrossEncoder``：它会把 sklearn 拉进依赖闭包，
    而 M2 在 CPython 3.14 上正是那条链踩坑（m3_design.md §8.2）。
    直接调 ``AutoModelForSequenceClassification`` 只要 transformers + torch，
    且打分逻辑（取 ``logits[:, 0]``）就是 CrossEncoder 的实现本身。
    """

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-base",
        batch_size: int = DEFAULT_RERANK_BATCH,
        max_seq: int = RERANK_MAX_SEQ,
        cache_dir: str = "",
    ) -> None:
        if not model_name.strip():
            raise RerankerError("model_name 不能为空")
        if batch_size < 1:
            raise RerankerError(f"batch_size 必须 ≥1，收到 {batch_size}")
        self._model_name = model_name
        self._batch_size = batch_size
        self._max_seq = max_seq
        self._cache_dir = cache_dir
        self._model: object | None = None
        self._tokenizer: object | None = None
        #: 被截断过的 (query, passage) 对数 —— 报告里"重排误排"归因要用
        self.truncated_pairs = 0
        self.score_calls = 0
        self.total_seconds = 0.0

    # -- 协议实现 --
    def name(self) -> str:
        return f"cross-encoder/{self._model_name}"

    def health_check(self) -> tuple[bool, str]:
        """只回答依赖是否可导入，不加载权重（加载 2 分钟，不能进探活路径）。"""
        try:
            import transformers
        except Exception as exc:  # noqa: BLE001
            return False, f"transformers 未安装或不可用：{type(exc).__name__}: {exc}"
        note = f"transformers {getattr(transformers, '__version__', 'unknown')} 就绪，模型 {self._model_name}"
        note += "（首次 rerank 时加载）" if self._model is None else "（权重已加载）"
        if self.truncated_pairs:
            note += f"；已截断 {self.truncated_pairs} 对超长候选"
        return True, note

    def rerank(self, query: str, candidates: list[SearchHit], *, top_n: int) -> list[SearchHit]:
        """给每个候选打交叉编码分，按分数降序返回前 ``top_n`` 条。

        分数**不做归一化**：bge-reranker 的 logit 未过 sigmoid，量纲是任意实数。
        只在同一次查询内比较（与融合分的相对性一致），跨查询不可比。
        """
        if top_n <= 0 or not candidates:
            return []

        #: 空正文 = 精排前的元数据回填被跳过（``metadata_loader`` 没传或没命中）。
        #: 这时模型会给所有空段落打出几乎相同的分，臂结论全是假的 —— 必须当场失败。
        empty = [hit.chunk_id for hit in candidates if not hit.text.strip()]
        if empty:
            raise RerankerError(
                f"{len(empty)} 条候选没有正文（如 {empty[0]}）：精排前必须先回填 chunk 文本"
            )

        import torch  # noqa: PLC0415

        tokenizer = self._ensure_loaded()
        model: Any = self._model  # transformers 模型；惰性加载后才有值
        pairs = [(query, hit.text) for hit in candidates]
        #: tokenizer 的截断是静默的，事后无从分辨；按字符数预估先记账，
        #: 这是 v3 失败分类里「重排误排：Reranker 对长文本截断」的量化入口。
        self.truncated_pairs += sum(
            1 for _, passage in pairs if len(passage) / _CHARS_PER_TOKEN > self._max_seq
        )

        logits: list[float] = []
        started = time.perf_counter()
        try:
            with torch.inference_mode():
                for offset in range(0, len(pairs), self._batch_size):
                    chunk = pairs[offset : offset + self._batch_size]
                    encoded = tokenizer(
                        [a for a, _ in chunk],
                        [b for _, b in chunk],
                        padding=True,
                        truncation=True,
                        max_length=self._max_seq,
                        return_tensors="pt",
                    )
                    out = model(**encoded).logits[:, 0]
                    logits.extend(float(x) for x in out)
        except Exception as exc:  # noqa: BLE001
            raise RerankerError(f"{self._model_name} 精排失败：{type(exc).__name__}: {exc}") from exc
        self.total_seconds += time.perf_counter() - started
        self.score_calls += 1

        if len(logits) != len(candidates):
            raise RerankerError(f"精排返回 {len(logits)} 分，候选 {len(candidates)} 条，数量不一致")

        for hit, logit in zip(candidates, logits, strict=True):
            hit.rerank_score = round(float(logit), 6)
        ranked = sorted(candidates, key=lambda h: (-(h.rerank_score or 0.0), h.chunk_id))
        return ranked[:top_n]

    # -- 内部 --
    def _ensure_loaded(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RerankerError(f"transformers 未安装，无法精排：{exc}") from exc

        kwargs = {"cache_dir": self._cache_dir} if self._cache_dir else {}
        repo = f"{_RERANK_REPO_PREFIX}{self._model_name}"
        started = time.perf_counter()
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(repo, **kwargs)
            self._model = AutoModelForSequenceClassification.from_pretrained(repo, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RerankerError(f"重排模型加载失败（{repo}）：{exc}") from exc
        self._model.eval()
        logger.info("重排模型加载完成：%s（%.1fs）", repo, time.perf_counter() - started)
        return self._tokenizer


#: 字符 ↔ token 估算系数，与 rag/splitter.py 同口径
_CHARS_PER_TOKEN = 1.6


def default_cache_dir() -> str:
    """权重缓存目录：``HF_CACHE_DIR`` → 项目 ``data/models/hf`` → 空（用 huggingface 默认）。"""
    return os.environ.get("HF_CACHE_DIR", "").strip()


def create_reranker(model_name: str | None, *, batch_size: int = DEFAULT_RERANK_BATCH) -> Reranker:
    """工厂：``None`` / 空串 → :class:`NoopReranker`（基线臂），否则交叉编码器。"""
    if not model_name or not model_name.strip():
        return NoopReranker()
    return CrossEncoderReranker(
        model_name=model_name.strip(),
        batch_size=batch_size,
        cache_dir=default_cache_dir(),
    )


__all__ = [
    "DEFAULT_RERANK_BATCH",
    "RERANK_MAX_SEQ",
    "CrossEncoderReranker",
    "NoopReranker",
    "Reranker",
    "RerankerError",
    "create_reranker",
    "default_cache_dir",
]
