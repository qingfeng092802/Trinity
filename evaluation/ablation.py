"""消融 runner（M3 · T3-3/T6-2）：按矩阵逐臂跑 Phase A 检索侧或 Phase B 生成侧评测，每臂一套独立临时索引库。

四条设计约束，改代码前先读：

* **索引分组复用**：``ArmConfig.index_key()`` 相同的臂共用一个库 —— 融合方式、rrf_k、
  top_k、fetch_k、重排只动查询侧，换它们不必重建索引（§8.3 的排期分组就靠这个键）；
* **每臂一套临时库**：跨臂绝不共享 chunk 空间（D6：只有 ``document_id`` 稳定，
  ``chunk_id`` 随分块变，拿它当跨臂键会把结论算歪）；
* **失败要响**：任何一臂装配或评测失败，该臂记 ``error`` 且整趟退出码非 0。
  绝不"跳过坏臂继续出表"——静默缺一枚组件的臂会产出看起来正常、其实全假的结论（§8.5-2）；
* **参数不被 Settings 悄悄改**：runner 用 env 建 Settings（索引侧），但报告里的 ``config``
  一律取自 :class:`ArmConfig`，并在跑之前 :func:`verify_arm_settings` 逐字段核对两者一致。
  这一道核对是防"env 名字拼错 → 该臂其实跑的是基线"（陷阱 6）。

Phase B（生成侧，花 API 钱）在 T6-2 接线，三条与 Phase A 不同的纪律：

* **一题只检索一次**：``RagAnswerer`` 的 ``search`` 注入本臂检索器的闭包，闭包把这批
  ``SearchHit`` 抄一份出来给检索指标用 —— 生成看到的是哪几段材料，判分就按哪几段算，
  两边不可能对不上（分两次检索就会）；
* **成本闸门是双层的**：启动前按 smoke 实测单价 × 题数 × 臂数预检，跑起来后逐题累计、
  一超上限立刻 ``CostLimitExceeded`` 停掉**整趟**（不是只停当前臂——剩下的臂还在排队烧钱）；
  单题成本没标定时只能靠第二层，所以日志会先警告一次；
* **显著性族按 phase 换**：Phase A 判排名（nDCG/MRR），Phase B 判"答得忠于材料吗"
  （faithfulness/context_recall）+ 两个二值天花板（hit@k、拒答是否正确）。**不做显著性检验**（2026-09-21 决策）：4~6 臂 × 50 题撑不起统计功效，
  一律报「相对基线的绝对提升 Δ」与「相对提升百分比 rel_lift」。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.experiment import ArmConfig, Matrix, load_matrix  # noqa: E402
from evaluation.retrieval_metrics import (  # noqa: E402
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)

__all__ = [
    "AblationError",
    "ArmGenerator",
    "ArmOutcome",
    "CostBudget",
    "CostLimitExceeded",
    "GENERATION_METRICS",
    "GoldenQuestion",
    "doc_key",
    "embed_dim_for_model",
    "estimate_seconds",
    "evaluate_arm",
    "load_golden_set",
    "run_matrix",
    "significance_family",
    "summarize",
]


class AblationError(RuntimeError):
    """runner 层面的失败：矩阵非法、参数漂移、预算超限、Phase B 前置件缺失。"""


class CostLimitExceeded(AblationError):
    """累计 API 成本触到 ``--max-cost-cny`` —— 要停整趟，而不是只停当前臂。

    单独一个类型才有办法穿过 :func:`_run_index_group` 那层"单臂失败要进报表"的
    ``except Exception``：失败臂可以记账后继续，烧钱超闸不行。
    """


# --------------------------------------------------------------------------- #
# 实测成本常量（出处：m3_design.md §8.3 / §8.7-1；换机器必须重测，别沿用）
# --------------------------------------------------------------------------- #

#: 每 1,000 篇文档的索引重建秒数（权重已缓存的口径）。
#: 轨道 A 全量实跑（7 组 × 1000 篇）标定：fastembed 组 41/45/51/59/66s，torch(bge-base) 259s。
#: **不含首次下载权重** —— bge-large 冷下载把那一组拉到 1019s，所以新模型要先预热再排期。
INDEX_SECONDS_PER_1K_DOCS = {"fastembed": 55.0, "torch": 265.0}

#: 单查询检索耗时（ONNX bge-small 实测 39ms/条 embed + 融合排序；轨道 A p50 29ms，留余量）
QUERY_SECONDS = 0.045

#: 重排单查询耗时（20 候选、CMRC 长 passage 口径）。
#: 2026-09-19 轨道 A 全量实跑校准：base p50 **11.19s** / p95 12.47s，v2-m3 p50 **31.09s** /
#: p95 39.87s —— 之前按"候选条数"推的 6s/12s 低了 2~3 倍，因为耗时实际随**候选正文长度**增长。
RERANK_SECONDS_PER_QUERY = {
    "BAAI/bge-reranker-base": 11.2,
    "BAAI/bge-reranker-v2-m3": 33.0,
}

#: 重排权重的首次加载（base 冷加载实测 129s；v2-m3 2.2GB 实测 325s）
RERANK_LOAD_SECONDS = 330.0

#: Phase A 零 API 调用 → 金钱预算恒为 0，>0 一律拒跑（花钱的闸门长这样）
PHASE_A_MAX_COST_CNY = 0.0

#: Phase B 的金钱预算默认上限（元）。设计口径 §5「预算闸门」：默认 ¥30，
#: 非高峰约 ¥29 刚好压线，高峰 ¥57 会被闸门拦下 —— 这是故意的。
PHASE_B_MAX_COST_DEFAULT_CNY = 30.0

#: 一题 Phase B 的实测单价（元/题）。**跑完 smoke 才能填**：15 题一趟把
#: ``cost.unit_cost_cny`` 打出来，再回填这里或用 ``--unit-cost-cny`` 传。
#: 留 None 时预检只能警告不能拒绝，硬闸仍在逐题累计那一层。
PHASE_B_UNIT_COST_CNY: float | None = None

#: 一题的 judge 调用次数（T6-1 单测钉住的成本不变量：4 指标合并成 5 次调用）。
#: 预检按它估 judge 那半边，别用"每指标一次"的老口径。
JUDGE_CALLS_PER_QUESTION = 5

#: Phase B 的四指标（进报表均值列的顺序）。
GENERATION_METRICS = ("faithfulness", "context_precision", "answer_relevancy", "context_recall")

#: 派生列：幻觉率 = 1 - faithfulness；拒答准确率吃 ``refusal_correct`` 二值。
#: 逐题行用 ``hallucination`` / ``refusal_correct``（评分器的原始口径），臂级均值改叫
#: ``*_rate`` / ``*_accuracy``（对齐 §5 报表样例），两套名字都在这张表里钉住。
HALLUCINATION_KEY = "hallucination"
HALLUCINATION_RATE_KEY = "hallucination_rate"
REFUSAL_CORRECT_KEY = "refusal_correct"
REFUSAL_ACCURACY_KEY = "refusal_accuracy"

#: 嵌入模型 → 输出维度。只认这张表，不猜（猜错会让向量库静默错位）。
EMBED_DIM_BY_MODEL = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-base-zh-v1.5": 768,
    "BAAI/bge-large-zh-v1.5": 1024,
}


# --------------------------------------------------------------------------- #
# Golden Set
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GoldenQuestion:
    """一道题的评测输入（``scripts/build_golden_set.py`` 的产物口径）。

    Attributes:
        qid: 题目 id，如 ``A-factual-001``。
        track: ``A``（CMRC）/ ``B``（自建长文档）。E2b 只在轨道 B 计分（陷阱 13）。
        qtype: ``factual`` / ``term`` / ``multihop`` / ``refusal``。
        query: 题干。
        expected_doc_ids: 应命中的文档键；**拒答题为空元组**，检索指标对空期望返回 None。
        heldout_document: 拒答题的留出篇章文件名（可审计"gold passage 确实没入库"）。
        ground_truth: 原始标注答案（CMRC 是抽取式短答）。Phase B 拿它当 ``reference``
            喂 context_recall —— 轨道 A 的 gold 是"答案span"而不是"完整参考答案段落"，
            所以 context_recall 在轨道 A 偏低是**口径如此**，不是模型差。
    """

    qid: str
    track: str
    qtype: str
    query: str
    expected_doc_ids: tuple[str, ...] = ()
    expected_document: str | None = None
    heldout_document: str | None = None
    ground_truth: tuple[str, ...] = ()

    @property
    def is_refusal(self) -> bool:
        return self.qtype == "refusal" or not self.expected_doc_ids

    @property
    def reference(self) -> str:
        """judge 用的参考答案文本；无标注时为空串（评分器据此把 context_recall 记 None）。"""
        return "；".join(text for text in self.ground_truth if text.strip())


def stratified_limit(questions: Sequence[GoldenQuestion], limit: int) -> list[GoldenQuestion]:
    """smoke 取「按题型分层的 N 题」，不是「前 N 题」。

    Golden Set 按题型分块排列（事实→术语→拒答），所以 ``questions[:15]`` 永远是 15 道事实题：
    T5-2 的出口门槛要求 smoke 证明「拒答题命中模板」，而这种取样里**一道拒答题都没有**，
    门槛根本没法被验到；同时 smoke 量出来的 ¥/题 会被系统性高估 —— 真发生拒答时四个连续指标
    全部不适用、**一次 judge 都不调**（见 ``GenerationScorer.score``），拿纯事实题的单价去预检
    全量，可能把其实跑得完的一趟误拒在闸门外。

    配额用**最大余数法**：先按占比取整，余下的名额给小数部分最大的题型（并列按题型名取先）。
    题型内保持文件顺序 ⇒ 同一题集 + 同一 ``limit`` 必然得到同一个子集（可复现优先于随机代表性）。
    """
    if limit <= 0 or limit >= len(questions):
        return list(questions)

    pools: dict[str, list[GoldenQuestion]] = {}
    for question in questions:
        pools.setdefault(question.qtype, []).append(question)

    exact = {qtype: limit * len(pool) / len(questions) for qtype, pool in pools.items()}
    quota = {qtype: int(value) for qtype, value in exact.items()}
    left = limit - sum(quota.values())
    for qtype in sorted(exact, key=lambda k: (-(exact[k] - quota[k]), k)):
        if left <= 0:
            break
        if quota[qtype] < len(pools[qtype]):
            quota[qtype] += 1
            left -= 1
    while left > 0:  # 只有小题型被配额撑满时才走得到这一步
        room = {k: len(p) - quota[k] for k, p in pools.items() if quota[k] < len(p)}
        if not room:
            break
        winner = min(sorted(room), key=lambda k: (-room[k], k))
        quota[winner] += 1
        left -= 1

    picked = [q for qtype, pool in pools.items() for q in pool[: quota[qtype]]]
    rank = {id(q): i for i, q in enumerate(questions)}
    return sorted(picked, key=lambda q: rank[id(q)])


def load_golden_set(path: Path | str) -> list[GoldenQuestion]:
    """读 golden jsonl；缺字段/类型错一律报错，不静默跳过（少一题就少一对配对观测）。"""
    items: list[GoldenQuestion] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            missing = {"id", "track", "type", "query"} - set(raw)
            if missing:
                raise AblationError(f"{path}:{line_number} 缺字段 {sorted(missing)}")
            qid = str(raw["id"])
            if qid in seen:
                raise AblationError(f"{path}:{line_number} 题目 id 重复：{qid}")
            seen.add(qid)
            items.append(
                GoldenQuestion(
                    qid=qid,
                    track=str(raw["track"]),
                    qtype=str(raw["type"]),
                    query=str(raw["query"]).strip(),
                    expected_doc_ids=tuple(str(x) for x in (raw.get("expected_doc_ids") or [])),
                    expected_document=raw.get("expected_document"),
                    heldout_document=raw.get("heldout_document"),
                    ground_truth=_as_texts(raw.get("ground_truth")),
                )
            )
    if not items:
        raise AblationError(f"金标集为空：{path}")
    return items


def _as_texts(value: Any) -> tuple[str, ...]:
    """``ground_truth`` 兼容"单个字符串"与"字符串数组"两种写法，空值一律成空元组。"""
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(str(item).strip() for item in values if str(item).strip())


def doc_key(document_id: str) -> str:
    """``SearchHit.document_id`` → 与 ``expected_doc_ids`` 同一套键。

    索引侧的命名规则是 ``doc-<文件 stem>``（``retrieval_eval.index_fixtures``），
    轨道 A 的文件名是 ``cmrc_<DOCID>.md``，所以这里剥掉这两层前缀。
    轨道 B 的文件 stem 必须直接等于其 ``expected_doc_ids`` 元素，否则判分全 0。
    """
    stem = document_id.removeprefix("doc-")
    return stem.removeprefix("cmrc_")


def embed_dim_for_model(model_name: str) -> int:
    """模型名 → 向量维度；不在表里就报错，绝不猜。"""
    try:
        return EMBED_DIM_BY_MODEL[model_name]
    except KeyError as exc:
        raise AblationError(
            f"未知嵌入模型 {model_name!r}，不知道它的输出维度。"
            f"已登记：{sorted(EMBED_DIM_BY_MODEL)}；新增模型请先确认 dim 再登记"
        ) from exc


# --------------------------------------------------------------------------- #
# 参数落地与漂移核对
# --------------------------------------------------------------------------- #
def apply_arm_env(arm: ArmConfig) -> dict[str, str]:
    """把臂的**索引侧**参数写进环境变量（Settings 的唯一来源），返回写了什么。

    维度从 :func:`embed_dim_for_model` 取，不接受臂上写 dim —— 少一个可写错的旋钮。
    查询侧（fusion / rrf_k / reranker / top_k / fetch_k）**故意不写 env**：
    它们由 runner 用臂配置直接构造，写进 env 只会多一份可能不一致的假真相。
    """
    values = {
        "EMBEDDING_BACKEND": arm.embed_backend,
        "EMBEDDING_MODEL_NAME": arm.embed_model,
        "EMBEDDING_DIM": str(embed_dim_for_model(arm.embed_model)),
        "CHUNK_MODE": arm.chunk_mode,
        "CHUNK_SIZE": str(arm.chunk_size),
        "CHUNK_OVERLAP": str(arm.chunk_overlap),
        "JIEBA_USERDICT": _userdict_path() if arm.jieba_userdict else "",
    }
    os.environ.update(values)
    return values


def _userdict_path() -> str:
    """A-DICT 臂的词典文件（由轨道 B 的领域术语表生成，见 m3_design.md §8.8）。"""
    return str(PROJECT_ROOT / "data" / "dicts" / "m3_terms.txt")


def _drop_unrunnable_dict_arms(
    arms: list[ArmConfig], only_arms: Sequence[str]
) -> list[ArmConfig]:
    """缺词典时：**点名要的就拒跑整趟，顺带扫到的跳过并大声告警**。

    轨道 A 是百科语料，提不出行业术语，``data/dicts/m3_terms.txt`` 只能等轨道 B 的规程
    文档到手再生成。整批扫 Phase A 时不该为它拖垮其余十几条臂（一趟一个多小时）；
    但用户显式 ``--arm A-DICT`` 时静默跳过，等于告诉他"这臂跑完了"。
    """
    dict_arms = [arm.arm_id for arm in arms if arm.jieba_userdict]
    if not dict_arms or Path(_userdict_path()).is_file():
        return arms
    detail = (
        f"臂 {dict_arms} 需要词典 {_userdict_path()}，但它不存在："
        "轨道 A（CMRC 百科语料）提不出行业术语，词典要等轨道 B 文档"
    )
    if set(dict_arms) & set(only_arms or ()):
        raise AblationError(f"{detail}（你已显式点名这些臂，不静默跳过）")
    logger.warning("%s —— 本趟跳过这些臂", detail)
    return [arm for arm in arms if not arm.jieba_userdict]


def verify_arm_settings(arm: ArmConfig, settings: Any) -> None:
    """核对 Settings 真的等于臂配置（env 名字拼错时该臂会静默跑成基线）。

    只核**索引侧**字段：这些是经 Settings 落到索引/嵌入组件的，env 写错就会静默漂移。
    ``fusion`` / ``rrf_k`` / ``reranker`` / ``top_k`` 是**查询侧**，runner 直接把臂上的值
    传给构造器、根本不经过 Settings，所以既不会漂移、也不该在这里核 ——
    同一索引组里多臂共享一个 Settings，拿查询侧字段去核会把正常分组报成漂移。
    """
    expected = {
        "embedding_backend": arm.embed_backend,
        "embedding_model_name": arm.embed_model,
        "embedding_dim": embed_dim_for_model(arm.embed_model),
        "chunk_mode": arm.chunk_mode,
        "chunk_size": arm.chunk_size,
        "chunk_overlap": arm.chunk_overlap,
        "jieba_userdict": "" if not arm.jieba_userdict else _userdict_path(),
    }
    drifted = {
        key: (getattr(settings, key), value)
        for key, value in expected.items()
        if getattr(settings, key, None) != value
    }
    if drifted:
        detail = "、".join(f"{key}: 实际 {got!r} ≠ 臂上 {want!r}" for key, (got, want) in drifted.items())
        raise AblationError(f"臂 {arm.arm_id} 参数漂移（Settings 没吃到臂的配置）：{detail}")


# --------------------------------------------------------------------------- #
# 预算闸门
# --------------------------------------------------------------------------- #
def estimate_seconds(arms: Sequence[ArmConfig], *, docs: int, questions: int) -> float:
    """一趟（同一索引组）的预估秒数。估的是排期不是结论，所以常量全部实测标定。"""
    backend = "torch" if any(arm.embed_backend == "torch" for arm in arms) else "fastembed"
    total = INDEX_SECONDS_PER_1K_DOCS[backend] * max(1, docs) / 1000.0
    for arm in arms:
        per_query = QUERY_SECONDS
        if arm.reranker:
            try:
                per_query += RERANK_SECONDS_PER_QUERY[arm.reranker]
            except KeyError as exc:
                raise AblationError(
                    f"未知重排模型 {arm.reranker!r}，无法估它的延迟。已登记："
                    f"{sorted(RERANK_SECONDS_PER_QUERY)}"
                ) from exc
            total += RERANK_LOAD_SECONDS
        total += per_query * questions
    return total


# --------------------------------------------------------------------------- #
# 单臂评测
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ArmOutcome:
    """一条臂的完整结果（报表与配对检验都从这里出）。"""

    arm: ArmConfig
    per_question: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    by_type: dict[str, dict[str, Any]] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    index_group: str = ""
    index_reused: bool = False
    seconds: float = 0.0
    error: str | None = None

    def series(self, metric: str) -> list[float | None]:
        """按题目顺序取某一列 —— Wilcoxon/McNemar 要的是**配对**原始观测。"""
        return [row.get(metric) for row in self.per_question]

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm.arm_id,
            "phase": self.arm.phase,
            "role": self.arm.role,
            "notes": self.arm.notes,
            "config": asdict(self.arm),
            "index_group": self.index_group,
            "index_reused": self.index_reused,
            "seconds": round(self.seconds, 2),
            "metrics": self.metrics,
            "by_type": self.by_type,
            "cost": self.cost,
            "error": self.error,
            "per_question": self.per_question,
        }


def _retrieval_row(
    arm: ArmConfig, question: GoldenQuestion, retrieved_all: Sequence[str], latency_ms: float
) -> dict[str, Any]:
    """一题的检索侧明细（Phase A/B 同一套算法，差别只在材料是不是生成看到的那批）。"""
    expected = list(question.expected_doc_ids)
    # 文档粒度判分必须先**保序去重**：长 passage 会切成多个 chunk，同一篇文档
    # 可能占掉 top-5 里的两个槽。重复计会把 nDCG 顶到 1 以上（实测轨道 A 基线
    # 12/70 计分题命中这个坑，最高 1.63），MRR 也会被重复槽把首命中挤到更靠后的位次。
    # 去重后的排名口径是"**第几个不重复的文档**"，不是"第几个 chunk"——Recall 只看
    # 成员，不受影响；nDCG/MRR 因此都偏文档粒度，与 hit@k 同一套口径。
    retrieved = list(dict.fromkeys(retrieved_all))
    # 拒答题（无期望文档）三项指标一律 None：hit_at_k 记 False 会被当成
    # "有标准答案但没命中"计入均值，凭空把命中率压低约 1/3（30/100 题是拒答）。
    scorable = bool(expected)
    return {
        "qid": question.qid,
        "type": question.qtype,
        "track": question.track,
        "expected_doc_ids": expected,
        "retrieved_doc_ids": retrieved,
        "retrieved_chunk_doc_ids": list(retrieved_all),
        "recall_at_k": recall_at_k(retrieved, expected, arm.top_k),
        "mrr_at_k": mrr_at_k(retrieved, expected, arm.top_k),
        "ndcg_at_k": ndcg_at_k(retrieved, expected, arm.top_k),
        "hit_at_k": hit_at_k(retrieved, expected, arm.top_k) if scorable else None,
        "latency_ms": round(latency_ms, 2),
    }


@dataclass(slots=True)
class CostBudget:
    """Phase B 的金钱硬闸。逐题累计，触线即抛 —— 剩下的臂没必要继续排队烧钱。"""

    cap_cny: float
    spent_cny: float = 0.0

    def add(self, cost_cny: float, *, where: str) -> None:
        self.spent_cny = round(self.spent_cny + float(cost_cny), 6)
        if self.spent_cny > self.cap_cny:
            raise CostLimitExceeded(
                f"成本闸门：跑到 {where} 已花 ¥{self.spent_cny:.4f}，超过上限 "
                f"¥{self.cap_cny:.2f}。整趟中止（已跑完的臂在报表里，不丢）。"
            )


class ArmGenerator:
    """Phase B 的一题通路：检索一次 → 生成 → 四指标 judge → 记账 + 过闸。

    ``RagAnswerer`` 的 ``search`` 注入的是 :meth:`_capture_search` 闭包，它把这批
    ``SearchHit`` 留在实例上给 :meth:`run` 取用。这样"生成看到的材料"和"检索指标算的
    材料"是同一个对象，不可能因为两次检索结果抖动而对不上。
    """

    def __init__(
        self,
        *,
        arm: ArmConfig,
        retriever: "HybridRetriever",
        metadata_loader: Any,
        scorer: Any,
        answerer_factory: Any = None,
        budget: CostBudget | None = None,
    ) -> None:
        self.arm = arm
        self._retriever = retriever
        self._metadata_loader = metadata_loader
        self._scorer = scorer
        self._answerer_factory = answerer_factory
        self._answerer: Any = None
        self._budget = budget
        self._hits: list[Any] = []

    def _capture_search(self, query: str, top_k: int) -> list[Any]:
        self._hits = list(
            self._retriever.search(query, top_k, metadata_loader=self._metadata_loader)
        )
        return self._hits

    def _llm_answerer(self) -> Any:
        if self._answerer is None:
            if self._answerer_factory is None:
                from rag.answer import RagAnswerer

                self._answerer_factory = lambda search: RagAnswerer(  # noqa: E731
                    search=search,
                    prompt=self.arm.prompt or "answer_basic",
                    top_k=self.arm.top_k,
                )
            # 工厂而不是实例：闭包（本臂检索器 + 命中抄本）必须在生成器手里，
            # 换掉这个不变量就等于允许"生成看到的材料"与"判分看到的材料"来自两次检索。
            self._answerer = self._answerer_factory(self._capture_search)
        return self._answerer

    def run(self, question: GoldenQuestion) -> dict[str, Any]:
        """返回一题的完整明细行（检索列 + 生成列 + 成本列）。"""
        result = self._llm_answerer().answer(question.query)
        hits, self._hits = self._hits, []
        row = _retrieval_row(
            self.arm, question, [doc_key(hit.document_id) for hit in hits], float(result.retrieval_ms)
        )
        score = self._scorer.score(
            question=question.query,
            answer=result.answer,
            materials=hits,
            reference=question.reference,
            refused=result.refused,
            expected_refusal=question.is_refusal,
        )
        row.update(
            {
                "prompt": result.prompt,
                "answer": result.answer,
                "refused": result.refused,
                "citation_rate": result.citation_rate,
                "invalid_citations": list(result.invalid_citations),
                "e2e_ms": round(float(result.latency_ms), 2),
                HALLUCINATION_KEY: score.hallucination,
                REFUSAL_CORRECT_KEY: score.refusal_correct,
                "judge_detail": score.detail,
                "answer_cost_cny": round(float(getattr(result.usage, "cost", 0.0) or 0.0), 6),
                "answer_token_in": int(getattr(result.usage, "token_in", 0) or 0),
                "answer_token_out": int(getattr(result.usage, "token_out", 0) or 0),
                **{name: score.metric(name) for name in GENERATION_METRICS},
            }
        )
        row["cost_cny"] = round(row["answer_cost_cny"] + float(score.cost_cny), 6)
        if self._budget is not None:
            self._budget.add(row["cost_cny"], where=f"臂 {self.arm.arm_id} 题 {question.qid}")
        return row


def evaluate_arm(
    arm: ArmConfig,
    questions: Sequence[GoldenQuestion],
    retriever: "HybridRetriever",
    metadata_loader: Any,
    *,
    generator: ArmGenerator | None = None,
) -> ArmOutcome:
    """跑一遍题集：检索 → 文档级判分 → 纯函数指标 + 延迟分位；``generator`` 给了就再加生成侧一趟。

    Args:
        arm: 本臂配置。
        questions: 题集。
        retriever: 本臂的检索器（Phase A 直接用它，Phase B 由 ``generator`` 内部复用）。
        metadata_loader: 取 chunk 元数据（标题路径）的回调。
        generator: Phase B 通路。None 时是纯检索臂，一行 API 都不调。
    """
    per_question: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    for question in questions:
        if generator is not None:
            per_question.append(generator.run(question))
            latencies_ms.append(float(per_question[-1]["latency_ms"]))
            continue
        started = time.perf_counter()
        hits = retriever.search(question.query, arm.top_k, metadata_loader=metadata_loader)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(elapsed_ms)
        per_question.append(
            _retrieval_row(arm, question, [doc_key(hit.document_id) for hit in hits], elapsed_ms)
        )
    latencies_ms.sort()
    e2e_ms = sorted(float(row["e2e_ms"]) for row in per_question if row.get("e2e_ms") is not None)
    metrics: dict[str, float | None] = {
        f"recall_at_{arm.top_k}": _mean_column(per_question, "recall_at_k"),
        f"mrr_at_{arm.top_k}": _mean_column(per_question, "mrr_at_k"),
        f"ndcg_at_{arm.top_k}": _mean_column(per_question, "ndcg_at_k"),
        f"hit_rate_at_{arm.top_k}": _mean_column(per_question, "hit_at_k"),
        "questions_scored": float(_scored_count(per_question, "recall_at_k")),
        "questions_total": float(len(per_question)),
    }
    if generator is not None:
        metrics.update(
            {
                **{name: _mean_column(per_question, name) for name in GENERATION_METRICS},
                HALLUCINATION_RATE_KEY: _mean_column(per_question, HALLUCINATION_KEY),
                REFUSAL_ACCURACY_KEY: _mean_column(per_question, REFUSAL_CORRECT_KEY),
                "citation_rate": _mean_column(per_question, "citation_rate"),
                "answers_refused": float(
                    sum(1 for row in per_question if row.get("refused"))
                ),
            }
        )
    return ArmOutcome(
        arm=arm,
        per_question=per_question,
        by_type=_split_by_type(
            per_question, arm.top_k, extra=GENERATION_METRICS if generator else ()
        ),
        metrics=metrics,
        cost={
            "retrieval_p95_ms": _percentile(latencies_ms, 0.95),
            "retrieval_p50_ms": _percentile(latencies_ms, 0.50),
            "e2e_p95_ms": _percentile(e2e_ms, 0.95) if e2e_ms else None,
            "e2e_p50_ms": _percentile(e2e_ms, 0.50) if e2e_ms else None,
            "avg_tokens_in": _mean_int(per_question, "answer_token_in"),
            "avg_tokens_out": _mean_int(per_question, "answer_token_out"),
            "cost_cny": round(sum(float(row.get("cost_cny") or 0.0) for row in per_question), 6),
            # Phase A 一行 API 都不调，"单价"这个问题本身不成立 —— 报 0 会被读成
            # 「标定过的 0 元/题」，所以直接 None，让预检那边显示"未标定"。
            "unit_cost_cny": _unit_cost(per_question) if generator is not None else None,
            "reranker": arm.reranker,
            "prompt": arm.prompt if generator is not None else None,
        },
    )


def _mean_int(rows: Sequence[dict[str, Any]], key: str) -> int:
    values = [int(row[key]) for row in rows if row.get(key) is not None]
    return round(sum(values) / len(values)) if values else 0


def _unit_cost(rows: Sequence[dict[str, Any]]) -> float | None:
    """实测单题成本（元/题）—— smoke 跑完就打印它，全量预检要用。"""
    if not rows:
        return None
    return round(sum(float(row.get("cost_cny") or 0.0) for row in rows) / len(rows), 6)


def _mean_column(rows: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _scored_count(rows: Sequence[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is not None)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return round(float(sorted_values[index]), 1)


def _split_by_type(
    rows: Sequence[dict[str, Any]], k: int, *, extra: Sequence[str] = ()
) -> dict[str, dict[str, Any]]:
    """分题型统计。聚合均值会把"事实题贴顶、术语/编号题才是主战场"这两件事抹平，
    而且 Track A 上 Recall@5 普遍接近 1，有区分度的是 nDCG/MRR（排名好坏）——
    只报一个总均值就无法解释差异到底来自哪类题。

    ``extra`` 是生成侧那几列（Phase B 才传）：Phase A 不传，输出与历史报表逐键一致。
    """
    result: dict[str, dict[str, Any]] = {}
    for qtype in sorted({str(row["type"]) for row in rows}):
        subset = [row for row in rows if row["type"] == qtype]
        result[qtype] = {
            "n": len(subset),
            "scored": _scored_count(subset, "recall_at_k"),
            f"recall_at_{k}": _mean_column(subset, "recall_at_k"),
            f"mrr_at_{k}": _mean_column(subset, "mrr_at_k"),
            f"ndcg_at_{k}": _mean_column(subset, "ndcg_at_k"),
            **{name: _mean_column(subset, name) for name in extra},
        }
    return result


# --------------------------------------------------------------------------- #
# 显著性
# --------------------------------------------------------------------------- #
#: 显著性族（D13 拍板）：**排名指标**做主判分，命中率作天花板检查。
#: 轨道 A 基线 Recall@5 实测 0.9571 —— 只剩 3 题空间，任何臂都测不出差异，
#: 把它留在主判分里只会稀释注意力，因此只作天花板检查（不做显著性检验）。
SIGNIFICANCE_METRICS = ("ndcg_at_k", "mrr_at_k")

#: 按 phase 换族。Phase B 的主判分是"答得忠于材料吗"（faithfulness）和
#: "该给的要点给了吗"（context_recall）；nDCG/MRR 那两列 Phase A 已经判过，
#: 再塞进来只会让判分口径发散 —— 每个 phase 只认自己那两列主判分。
SIGNIFICANCE_METRICS_BY_PHASE: dict[str, tuple[str, ...]] = {
    "A": SIGNIFICANCE_METRICS,
    "B": ("faithfulness", "context_recall"),
}

#: 二值天花板检查（McNemar）。Phase A 没有拒答列，硬算会变成"两边都无观测"的空比较，
#: 所以这一组也按 phase 给。
SIGNIFICANCE_BINARY_BY_PHASE: dict[str, tuple[str, ...]] = {
    "A": ("hit_at_k",),
    "B": ("hit_at_k", REFUSAL_CORRECT_KEY),
}


def significance_family(phase: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """返回该 phase 的（连续指标族, 二值检查族）。"""
    try:
        return SIGNIFICANCE_METRICS_BY_PHASE[phase], SIGNIFICANCE_BINARY_BY_PHASE[phase]
    except KeyError as exc:
        raise AblationError(
            f"未知 phase {phase!r}，只登记了 {sorted(SIGNIFICANCE_METRICS_BY_PHASE)}"
        ) from exc


#: 摘要表 Δ 列的短标签（报表里 ``ΔnDCG`` 这种写法已经在文档与截图里定了型，别改口径）。
_METRIC_SHORT = {
    "ndcg_at_k": "nDCG",
    "mrr_at_k": "MRR",
    "hit_at_k": "hit@k",
    REFUSAL_CORRECT_KEY: "拒答正确",
}


@dataclass(slots=True)
class PairedComparison:
    """一次配对比较的结论（**只报效应量，不做显著性检验**）。

    **2026-09-21 决策**：原 ``evaluation/stats.py`` 的 McNemar / Wilcoxon /
    Holm–Bonferroni 全条删除。4~6 臂 × 50 题的样本量给不出可信的 p 值，
    与其报一个伪精确的 ``p=0.031``，不如老老实实报 ``delta`` 与 ``rel_lift``。

    ``statistic`` / ``p_raw`` / ``p_adjusted`` 字段保留是为了不破坏已落盘的历史
    报表 JSON 契约，一律填 ``NaN`` / ``None`` —— 读到的任何 p 值都应当被忽略。
    """

    metric: str
    test: str
    n_pairs: int
    n_used: int
    mean_baseline: float
    mean_arm: float
    delta: float
    statistic: float = float("nan")
    p_raw: float = float("nan")
    p_adjusted: float | None = None
    dropped: int = 0
    detail: dict[str, float] = field(default_factory=dict)

    @property
    def rel_lift(self) -> float | None:
        """相对基线的提升百分比；基线均值为 0 时无定义（返回 ``None``）。"""
        return self.detail.get("rel_lift")

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "test": self.test,
            "n_pairs": self.n_pairs,
            "n_used": self.n_used,
            "dropped": self.dropped,
            "mean_baseline": round(self.mean_baseline, 4),
            "mean_arm": round(self.mean_arm, 4),
            "delta": round(self.delta, 4),
            "rel_lift": self.rel_lift,
            "statistic": None,
            "p_raw": None,
            "p_adjusted": None,
            "significance_removed": True,
            "detail": self.detail,
        }


def compare_arms(
    outcomes: dict[str, ArmOutcome], matrix: Matrix, *, phase: str = "A"
) -> list[PairedComparison]:
    """每条非基线臂对它自己的**参照臂**报「绝对提升」，**不做显著性检验**。

    **2026-09-21 决策变更（对外口径收敛）**：原先走 Wilcoxon / McNemar + Holm–Bonferroni
    同族校正。4~6 臂 × 50 题的样本量撑不起统计功效，p 值只会给出伪精确结论，
    因此**整条显著性路径删除**，改为直接报：

    * ``delta`` = 本臂均值 − 参照臂均值（**绝对差**，不是百分比）
    * ``rel_lift`` = delta / |参照均值|（**相对基线的提升百分比**，参照均值为 0 时为 ``None``）

    ``statistic`` / ``p_raw`` / ``p_adjusted`` 一律填 ``NaN`` / ``None``：
    报表里不再出现任何 p 值列。字段保留是为了不破坏 ``PairedComparison.as_dict()``
    的下游序列化契约。

    注意参照臂不一定是矩阵基线：跨模型对比的臂参照的是 ``A-E1-backend``
    （见 ``Matrix.reference_for``），拿生产基线比就是双变量。
    """
    metrics, binaries = significance_family(phase)
    comparisons: list[PairedComparison] = []
    for arm_id, outcome in outcomes.items():
        arm = outcome.arm
        if arm.role == "baseline":
            continue
        if outcome.error:
            logger.warning("臂 %s 失败，不参与对比（只统计跑通的臂）", arm_id)
            continue
        reference = matrix.reference_for(arm)
        base = outcomes.get(reference.arm_id)
        if base is None:
            logger.warning("臂 %s 的参照 %s 未跑，跳过对比（报表该格标 n/a）", arm_id, reference.arm_id)
            continue
        for metric in (*metrics, *binaries):
            base_vals = [float(v) for v in _clean(base.series(metric))]
            arm_vals = [float(v) for v in _clean(outcome.series(metric))]
            n = min(len(base_vals), len(arm_vals))
            mean_base = sum(base_vals[:n]) / n if n else 0.0
            mean_arm = sum(arm_vals[:n]) / n if n else 0.0
            delta = mean_arm - mean_base
            comparisons.append(
                PairedComparison(
                    metric=f"{arm_id}:{metric}",
                    test="delta_only",  # 只报效应量，不跑任何检验
                    n_pairs=n,
                    n_used=n,
                    mean_baseline=mean_base,
                    mean_arm=mean_arm,
                    delta=delta,
                    statistic=float("nan"),
                    p_raw=float("nan"),
                    p_adjusted=None,
                    detail={
                        "rel_lift": (delta / abs(mean_base)) if mean_base else None,
                        "significance_removed": 1.0,
                    },
                )
            )
    return comparisons


def _clean(values: "Sequence[Any]") -> list[Any]:
    """拒答题的 None 不进配对 —— 否则两边都"没有期望"会被算成一致对，稀释检验。"""
    return [value for value in values if value is not None]


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run_matrix(
    matrix: Matrix,
    *,
    dataset: Path,
    fixtures: Path,
    out_dir: Path,
    phase: str = "A",
    only_arms: Sequence[str] = (),
    limit: int = 0,
    max_seconds: float = 3 * 3600.0,
    max_cost_cny: float = PHASE_B_MAX_COST_DEFAULT_CNY,
    unit_cost_cny: float | None = None,
    keep_work: bool = False,
) -> dict[str, Any]:
    """按索引组逐臂跑完一个 phase，落盘 JSON + markdown 摘要表。"""
    problems = matrix.validate()
    if problems:
        raise AblationError("实验矩阵非法：\n  - " + "\n  - ".join(problems))

    arms = [arm for arm in matrix.all_arms if arm.phase == phase]
    if only_arms:
        wanted = set(only_arms)
        unknown = wanted - {arm.arm_id for arm in arms}
        if unknown:
            raise AblationError(
                f"--arm 指定了不存在或不属于 phase={phase} 的臂：{sorted(unknown)}"
            )
        arms = [arm for arm in arms if arm.arm_id in wanted]
    if not arms:
        raise AblationError(f"phase={phase} 没有可跑的臂")
    if phase == "B":
        # 缺件检查必须在看数据集与建库之前：一个要花钱的跑批不该在烧掉几十分钟索引之后
        # 才发现自己没 Key（§7 陷阱 3 的顺序纪律）。成本预检要题数，只能放在读完之后。
        _require_generation_ready(arms, settings=_fresh_settings())

    questions = load_golden_set(dataset)
    if limit:
        full = len(questions)
        questions = stratified_limit(questions, limit)
        mix = ", ".join(f"{qtype}×{count}" for qtype, count in
                        sorted(Counter(q.qtype for q in questions).items()))
        logger.info("smoke 取样按题型分层：%s（全量 %d 题 → %d 题）", mix, full, len(questions))
    docs = len([p for p in Path(fixtures).iterdir() if p.is_file()])

    arms = _drop_unrunnable_dict_arms(arms, only_arms)

    # 索引分组（Matrix 提供），保持"基线在前"的稳定顺序
    groups: dict[str, list[ArmConfig]] = {}
    for arm in arms:
        groups.setdefault(arm.index_key(), []).append(arm)

    estimate = sum(
        estimate_seconds(group_arms, docs=docs, questions=len(questions))
        for group_arms in groups.values()
    )
    logger.info(
        "计划：%d 臂 / %d 个索引组 / %d 题 / %d 篇语料，预估 %.0fs",
        len(arms), len(groups), len(questions), docs, estimate,
    )
    if estimate > max_seconds:
        raise AblationError(
            f"预估 {estimate/60:.1f} min 超过 --max-seconds 预算 {max_seconds/60:.1f} min；"
            "先用 --limit 缩题或 --arm 挑臂"
        )

    budget: CostBudget | None = None
    if phase == "B":
        unit = PHASE_B_UNIT_COST_CNY if unit_cost_cny is None else unit_cost_cny
        if unit is None:
            logger.warning(
                "单题成本未标定：预检只能靠 --unit-cost-cny（先跑 --limit 15 的 smoke 拿单价）。"
                "现在只有逐题累计的硬闸 ¥%.2f 兜底。", max_cost_cny,
            )
        else:
            projected = float(unit) * len(questions) * len(arms)
            logger.info(
                "成本预检：¥%.4f/题 × %d 题 × %d 臂 = ¥%.2f，闸门 ¥%.2f",
                unit, len(questions), len(arms), projected, max_cost_cny,
            )
            if projected > max_cost_cny:
                raise AblationError(
                    f"预估成本 ¥{projected:.2f} 超过 --max-cost-cny ¥{max_cost_cny:.2f}。"
                    "要么缩题（--limit）、要么挑臂（--arm）、要么明确抬高闸门。"
                )
        budget = CostBudget(cap_cny=max_cost_cny)

    out_dir.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, ArmOutcome] = {}
    aborted: str | None = None
    try:
        for group_index, (group_key, group_arms) in enumerate(groups.items(), start=1):
            logger.info(
                "索引组 %d/%d（%s）开始", group_index, len(groups), group_key
            )
            outcomes.update(
                _run_index_group(
                    group_key,
                    group_arms,
                    questions=questions,
                    fixtures=fixtures,
                    keep_work=keep_work,
                    out_dir=out_dir,
                    budget=budget,
                )
            )
    except CostLimitExceeded as exc:
        # 已跑完的臂现在就在 out_dir 里（每臂一个 json），这里补一份"带中止原因"的汇总，
        # 再把闸门异常往上抛让退出码非 0 —— 半途烧穿的跑批不能冒充完整报表。
        aborted = str(exc)
        logger.error("%s", aborted)

    comparisons = compare_arms(outcomes, matrix, phase=phase)
    total_cost = round(
        sum(float((outcome.cost or {}).get("cost_cny") or 0.0) for outcome in outcomes.values()), 6
    )
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "phase": phase,
        "matrix_source": matrix.source,
        "dataset": str(dataset),
        "fixtures": str(fixtures),
        "questions": len(questions),
        "corpus_docs": docs,
        "estimated_seconds": round(estimate, 1),
        "index_groups": {key: [arm.arm_id for arm in value] for key, value in groups.items()},
        "cost_cny_total": total_cost,
        "cost_gate": {
            "max_cost_cny": max_cost_cny if phase == "B" else PHASE_A_MAX_COST_CNY,
            "unit_cost_cny": (PHASE_B_UNIT_COST_CNY if unit_cost_cny is None else unit_cost_cny),
            "spent_cny": round(budget.spent_cny, 6) if budget is not None else 0.0,
            "judge_calls_per_question": JUDGE_CALLS_PER_QUESTION if phase == "B" else 0,
            "aborted": aborted,
        },
        "arms": {arm_id: outcome.as_dict() for arm_id, outcome in outcomes.items()},
        "significance": {
            "family": [comparison.as_dict() for comparison in comparisons],
            "note": "不做显著性检验；n=%d 题，只报相对基线的绝对提升与相对百分比" % len(questions),
        },
        "failed_arms": sorted(
            arm_id for arm_id, outcome in outcomes.items() if outcome.error
        ),
    }
    _write_reports(report, out_dir, outcomes, comparisons, matrix)
    if aborted is not None:
        raise CostLimitExceeded(aborted)
    failed = [arm_id for arm_id, outcome in outcomes.items() if outcome.error]
    if failed:
        raise AblationError(f"以下臂失败，报表不完整：{failed}")
    return report


def _fresh_settings() -> Any:
    """跑之前读一次 Settings（env 里还没有臂的配置，LLM 侧配置是全局的）。"""
    from config import get_settings, reset_settings_cache

    reset_settings_cache()
    return get_settings()


def _require_generation_ready(arms: Sequence[ArmConfig], *, settings: Any) -> None:
    """Phase B 的前置件：Key 在位、prompt 版本已登记、材料数没超过引用编号上限。

    ``phase=B 必须有 prompt`` 由 :class:`ArmConfig` 自己把门（``__post_init__``），
    这里不重复一遍；未登记的版本名与超上限的 top_k 是它管不到的两件事。
    """
    if not settings.llm_configured:
        raise AblationError(
            "Phase B 需要 LLM：`.env` 里配好 LLM_API_KEY 再跑（Phase A 零调用，不需要）"
        )
    from rag.answer import PROMPT_ROLES

    unknown = sorted({str(arm.prompt) for arm in arms if arm.prompt not in PROMPT_ROLES})
    if unknown:
        raise AblationError(
            f"prompt 版本不在已登记的四版里：{unknown}（只认 {list(PROMPT_ROLES)}）"
        )
    too_many = sorted(arm.arm_id for arm in arms if arm.top_k > 10)
    if too_many:
        raise AblationError(
            f"材料数超过引用编号上限（≤10）：{too_many}。引用解析只认【材料1】~【材料10】，"
            "再多出来的引用会静默失效"
        )


def _run_index_group(
    group_key: str,
    arms: list[ArmConfig],
    *,
    questions: Sequence[GoldenQuestion],
    fixtures: Path,
    keep_work: bool,
    out_dir: Path | None = None,
    budget: CostBudget | None = None,
) -> dict[str, ArmOutcome]:
    """一个索引组：建一次库，组内每臂只重建查询侧组件（融合/重排/top_k）。"""
    from config import get_settings, reset_settings_cache
    from evaluation.retrieval_eval import _prepare_env, index_fixtures, make_metadata_loader
    from rag.bm25 import BM25Index
    from rag.embedder import create_embedder
    from rag.retriever import HybridRetriever
    from rag.reranker import create_reranker
    from rag.vector_store import create_vector_store
    from storage.db import Database

    work = Path(tempfile.mkdtemp(prefix=f"m3_arm_{group_key[:8]}_"))
    results: dict[str, ArmOutcome] = {}
    store = database = None
    try:
        # 每臂一套临时库 + 临时知识目录：跨臂绝不共享 chunk 空间（D6），
        # 也绝不写开发用的真库。_prepare_env 顺手 reset_settings_cache，
        # 所以下面读到的 Settings 一定来自刚写好的臂 env。
        _prepare_env(work)
        apply_arm_env(arms[0])
        reset_settings_cache()
        settings = get_settings()
        verify_arm_settings(arms[0], settings)

        database = Database()
        database.init_db()
        embedder = create_embedder(settings)
        store = create_vector_store(settings, dim=settings.embedding_dim)
        started = time.perf_counter()
        indexed = index_fixtures(
            fixtures, settings=settings, database=database, embedder=embedder, store=store
        )
        logger.info(
            "索引组 %s 就绪：%d 篇 / %.1fs（%s）",
            group_key, len(indexed), time.perf_counter() - started,
            "、".join(arm.arm_id for arm in arms),
        )

        for position, arm in enumerate(arms):
            outcome = ArmOutcome(arm=arm, index_group=group_key, index_reused=position > 0)
            started = time.perf_counter()
            try:
                verify_arm_settings(arm, settings)
                bm25 = BM25Index(userdict=settings.jieba_userdict)
                bm25.rebuild(database.list_all_chunks())
                retriever = HybridRetriever(
                    embedder=embedder,
                    store=store,
                    bm25=bm25,
                    bm25_weight=arm.bm25_weight,
                    vector_weight=arm.vector_weight,
                    candidate_multiplier=_multiplier(arm),
                    fusion=arm.fusion,
                    rrf_k=arm.rrf_k,
                    reranker=create_reranker(arm.reranker),
                )
                loader = make_metadata_loader(database)
                fresh = evaluate_arm(
                    arm, questions, retriever, loader, generator=_make_generator(arm, retriever, loader, embedder, budget)
                )
                outcome.metrics = fresh.metrics
                outcome.by_type = fresh.by_type
                outcome.cost = fresh.cost
                outcome.per_question = fresh.per_question
            except CostLimitExceeded:
                raise  # 烧穿闸门不是"这一臂的失败"，是整趟的停止信号
            except Exception as exc:  # noqa: BLE001 - 单臂失败要进报表，再让整趟非 0 退出
                logger.exception("臂 %s 失败", arm.arm_id)
                outcome.error = f"{type(exc).__name__}: {exc}"
            outcome.seconds = time.perf_counter() - started
            results[arm.arm_id] = outcome
            # 一臂跑完立刻落盘：整趟要一个多小时，中途 OOM/被杀/手动 Ctrl-C 都不该
            # 把已跑完的臂一起带走（汇总文件最后写，单臂文件现在写）。
            if out_dir is not None:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"arm_{arm.arm_id}.json").write_text(
                    json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
            logger.info(_arm_log_line(outcome))
    finally:
        for closer in (store, database):
            if closer is not None and hasattr(closer, "close"):
                try:
                    closer.close()
                except Exception:  # noqa: BLE001
                    logger.debug("临时向量库关闭异常", exc_info=True)
        if database is not None:
            try:
                database.dispose()
            except Exception:  # noqa: BLE001
                logger.debug("临时库连接释放异常", exc_info=True)
        apply_arm_env_reset()
        reset_settings_cache()
        if not keep_work:
            _rmtree_quietly(work)
        else:
            logger.warning("保留临时索引库：%s", work)
    return results


def _make_generator(
    arm: ArmConfig,
    retriever: "HybridRetriever",
    metadata_loader: Any,
    embedder: Any,
    budget: CostBudget | None,
) -> ArmGenerator | None:
    """Phase B 才建生成通路；Phase A 返回 None，那条路一行 API 都不调。"""
    if arm.phase != "B":
        return None
    from evaluation.generation_metrics import GenerationScorer

    # embedder 借本臂的嵌入模型算 answer_relevancy（反述问题与原问题的余弦），
    # 不额外引一个模型 —— 换 embedder 也是臂配置的一部分，另起一个就是双变量。
    return ArmGenerator(
        arm=arm,
        retriever=retriever,
        metadata_loader=metadata_loader,
        scorer=GenerationScorer(embedder=embedder),
        budget=budget,
    )


def _arm_log_line(outcome: ArmOutcome) -> str:
    """一臂跑完打的那一行。Phase B 必须把**已花掉的钱**打出来，跑到第 3 臂就该看出超没超闸。"""
    arm = outcome.arm
    if outcome.error:
        return f"臂 {arm.arm_id} 失败：{outcome.error}（{outcome.seconds:.1f}s）"
    if arm.phase == "B":
        unit = outcome.cost.get("unit_cost_cny")
        return (
            f"臂 {arm.arm_id} 完成：faithfulness={_fmt(outcome.metrics.get('faithfulness'))}"
            f" / context_recall={_fmt(outcome.metrics.get('context_recall'))}"
            f" / 拒答准确={_fmt(outcome.metrics.get(REFUSAL_ACCURACY_KEY))}"
            f" / nDCG={_fmt(outcome.metrics.get(f'ndcg_at_{arm.top_k}'))}"
            f" / ¥{float(outcome.cost.get('cost_cny') or 0.0):.4f}"
            f"{'' if unit is None else f'（¥{float(unit):.4f}/题）'}/{outcome.seconds:.1f}s"
        )
    return (
        f"臂 {arm.arm_id} 完成：nDCG={_fmt(outcome.metrics.get(f'ndcg_at_{arm.top_k}'))} "
        f"/ Recall={_fmt(outcome.metrics.get(f'recall_at_{arm.top_k}'))}（天花板）"
        f" / {outcome.seconds:.1f}s"
    )


def _multiplier(arm: ArmConfig) -> int:
    """fetch_k → candidate_multiplier（检索器只认倍数）。"""
    multiplier = max(1, arm.fetch_k // max(1, arm.top_k))
    if multiplier * arm.top_k != arm.fetch_k:
        raise AblationError(
            f"臂 {arm.arm_id}：fetch_k({arm.fetch_k}) 必须整除 top_k({arm.top_k})，"
            "否则实际候选池会和臂声明的不一致"
        )
    return multiplier


def apply_arm_env_reset() -> None:
    """清掉本模块写过的 env（下一组/下一次跑不受污染）。

    ``DB_URL`` / ``KNOWLEDGE_DIR`` 是临时库隔离用的，一起清 —— 否则同进程里后续
    创建的 ``KnowledgeService``/``Database`` 会连到一个已被删掉的临时库上。
    """
    for key in (
        "EMBEDDING_BACKEND",
        "EMBEDDING_MODEL_NAME",
        "EMBEDDING_DIM",
        "CHUNK_MODE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "JIEBA_USERDICT",
        "DB_URL",
        "KNOWLEDGE_DIR",
    ):
        os.environ.pop(key, None)


def _rmtree_quietly(path: Path) -> None:
    """Windows 上 SQLite 句柄释放有竞态，清理失败不该掩盖评测结果。"""
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:  # pragma: no cover
        logger.debug("临时目录清理失败：%s", path)


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def _write_reports(
    report: dict[str, Any],
    out_dir: Path,
    outcomes: dict[str, ArmOutcome],
    comparisons: Sequence[PairedComparison],
    matrix: Matrix,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ablation_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for arm_id, outcome in outcomes.items():
        (out_dir / f"arm_{arm_id}.json").write_text(
            json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (out_dir / "ablation_table.md").write_text(
        summarize(report, outcomes, comparisons, matrix), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# 读回（页面与报表共用同一套字段名，所以读取端也留在这里）
# --------------------------------------------------------------------------- #
#: 一行的指标列顺序：Phase A 有前四，Phase B 补齐生成侧四指标与两个派生率。
#: 缺的列渲染成 None（页面显示 n/a）。带 ``@k`` 的列**不是写死 5**：报表里的键按各臂
#: 自己的 top_k 落（``ndcg_at_3`` / ``ndcg_at_10``），取值见 :func:`_metric_at_k`。
REPORT_METRIC_COLUMNS = (
    "recall_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "hit_rate_at_k",
    "faithfulness",
    "context_precision",
    "answer_relevancy",
    "context_recall",
    HALLUCINATION_RATE_KEY,
    REFUSAL_ACCURACY_KEY,
    "citation_rate",
)


def discover_report_dirs(root: Path | str) -> list[Path]:
    """找出 ``root`` 下所有落过消融报表的目录（含被中断、只有 ``arm_*.json`` 的）。"""
    base = Path(root)
    if not base.is_dir():
        return []
    found: list[Path] = []
    for candidate in sorted(path for path in base.iterdir() if path.is_dir()):
        if (candidate / "ablation_summary.json").is_file() or list(candidate.glob("arm_*.json")):
            found.append(candidate)
    return found


def load_report(directory: Path | str) -> dict[str, Any]:
    """读一趟消融报表；``ablation_summary.json`` 缺失时用 ``arm_*.json`` 拼出可用部分。

    中断的跑批最有价值的恰恰是"已经跑完的那几臂"，所以这里不退错，
    而是把 ``report['partial']`` 标上 True 让页面如实说明数据不全。
    """
    directory = Path(directory)
    summary = directory / "ablation_summary.json"
    if summary.is_file():
        payload = json.loads(summary.read_text(encoding="utf-8"))
        payload.setdefault("partial", False)
        return payload
    arms: dict[str, Any] = {}
    for path in sorted(directory.glob("arm_*.json")):
        one = json.loads(path.read_text(encoding="utf-8"))
        arms[str(one.get("arm_id") or path.stem.removeprefix("arm_"))] = one
    if not arms:
        raise AblationError(f"{directory} 里没有消融报表（既无 ablation_summary.json 也无 arm_*.json）")
    return {
        "phase": next(iter(arms.values())).get("phase", "A"),
        "questions": max((len(a.get("per_question") or []) for a in arms.values()), default=0),
        "arms": arms,
        "significance": {"family": [], "note": "报表不完整（缺 ablation_summary.json），未含显著性"},
        "partial": True,
    }


def metric_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """一臂一行：配置差异 + 各指标均值 + P95 + 成本。页面表格直接吃这个。"""
    arms: dict[str, Any] = report.get("arms") or {}
    family: list[dict[str, Any]] = (report.get("significance") or {}).get("family") or []
    p_by_arm = {
        str(item["metric"]).split(":")[0]: item
        for item in family
        if str(item["metric"]).endswith(":ndcg_at_k") or str(item["metric"]).endswith(":faithfulness")
    }
    rows: list[dict[str, Any]] = []
    for arm_id, arm in arms.items():
        metrics = arm.get("metrics") or {}
        by_type = arm.get("by_type") or {}
        cost = arm.get("cost") or {}
        # top_k 本身就是若干臂的自变量：报表里键是 ndcg_at_3 / ndcg_at_10 这种，
        # 只按 _at_5 取列会让那些臂整行 n/a（摘要表同一套修法，见 _at）。
        top_k = int((arm.get("config") or {}).get("top_k") or 5)
        comparison = p_by_arm.get(arm_id) or {}
        rows.append(
            {
                "arm_id": arm_id,
                "role": arm.get("role", "ablation"),
                "phase": arm.get("phase", ""),
                "notes": arm.get("notes", ""),
                "error": arm.get("error"),
                "index_reused": bool(arm.get("index_reused")),
                "seconds": arm.get("seconds", 0.0),
                **{column: _metric_at_k(metrics, column, top_k) for column in REPORT_METRIC_COLUMNS},
                "term_ndcg": _metric_at_k(by_type.get("term") or {}, "ndcg_at_k", top_k),
                "factual_ndcg": _metric_at_k(by_type.get("factual") or {}, "ndcg_at_k", top_k),
                "p95_ms": cost.get("retrieval_p95_ms"),
                "e2e_p95_ms": cost.get("e2e_p95_ms"),
                "cost_cny": cost.get("cost_cny"),
                "delta": comparison.get("delta"),
                "rel_lift": (comparison.get("detail") or {}).get("rel_lift"),
            }
        )
    return rows


def _metric_at_k(source: dict[str, Any], column: str, top_k: int) -> float | None:
    """把 ``@k`` 口径的列名翻成报表里的真实键。

    报表按各臂自己的 top_k 落键（``ndcg_at_3``、``recall_at_10``），所以先按本臂的 k 找，
    再退回历史报表的 ``@5`` 口径；两样都没有才是 None（不能拿 0 顶，0 是"真没命中"）。
    """
    value = source.get(column)
    if value is None and column.endswith("_at_k"):
        stem = column[: -len("k")]
        for candidate in (f"{stem}{top_k}", f"{stem}5"):
            if source.get(candidate) is not None:
                value = source[candidate]
                break
    return None if value is None else float(value)


def significance_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """显著性族原样摊平（``detail`` 里的不一致对数/非零对数是解释 p 的关键，不能丢）。"""
    rows: list[dict[str, Any]] = []
    for item in ((report.get("significance") or {}).get("family") or []):
        arm_id, _, metric = str(item.get("metric", "")).partition(":")
        rows.append(
            {
                "arm_id": arm_id,
                "metric": metric,
                "test": item.get("test"),
                "n_used": item.get("n_used"),
                "mean_baseline": item.get("mean_baseline"),
                "mean_arm": item.get("mean_arm"),
                "delta": item.get("delta"),
                "rel_lift": (item.get("detail") or {}).get("rel_lift"),
                "detail": item.get("detail") or {},
            }
        )
    return rows


#: 逐题 diff 里两臂各出一列的指标。Phase A 只有前四个键有值，Phase B 补齐后三个。
DIFF_COLUMNS = (
    "recall_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "hit_at_k",
    "faithfulness",
    "context_recall",
    "refusal_correct",
)


def diff_rows(report: dict[str, Any], left: str, right: str) -> list[dict[str, Any]]:
    """两臂逐题对照。按 qid 对齐（**不是按行号**：某臂少跑几题时行号会整体错位）。"""
    arms: dict[str, Any] = report.get("arms") or {}
    for arm_id in (left, right):
        if arm_id not in arms:
            raise AblationError(f"报表里没有臂 {arm_id}")

    def _index(arm_id: str) -> dict[str, dict[str, Any]]:
        return {str(row.get("qid")): row for row in (arms[arm_id].get("per_question") or [])}

    left_rows, right_rows = _index(left), _index(right)
    out: list[dict[str, Any]] = []
    for qid in sorted(set(left_rows) | set(right_rows)):
        one, two = left_rows.get(qid) or {}, right_rows.get(qid) or {}
        metrics: dict[str, Any] = {}
        for column in DIFF_COLUMNS:
            metrics[f"{column}_{left}"] = one.get(column)
            metrics[f"{column}_{right}"] = two.get(column)
        same_order = (one.get("retrieved_doc_ids") or []) == (two.get("retrieved_doc_ids") or [])
        # Phase B 的 E4 家族**检索完全相同、只换 prompt**，只看排序差异会把整张 diff 表
        # 筛成空的（那正是最有看头的一组对照）。所以差异判据是"排序或任一指标不同"。
        same_metrics = all(
            metrics[f"{column}_{left}"] == metrics[f"{column}_{right}"] for column in DIFF_COLUMNS
        )
        row = {
            "qid": qid,
            "type": one.get("type") or two.get("type"),
            "expected_doc_ids": ",".join(one.get("expected_doc_ids") or []) or "（拒答题）",
            f"retrieved_{left}": " > ".join(one.get("retrieved_doc_ids") or []),
            f"retrieved_{right}": " > ".join(two.get("retrieved_doc_ids") or []),
            "same_order": same_order,
            "same_all": same_order and same_metrics,
            **metrics,
        }
        if "answer" in one or "answer" in two:
            row[f"answer_{left}"] = one.get("answer")
            row[f"answer_{right}"] = two.get("answer")
        out.append(row)
    return out


def summarize(
    report: dict[str, Any],
    outcomes: dict[str, ArmOutcome],
    comparisons: Sequence[PairedComparison],
    matrix: Matrix,
) -> str:
    """人读的消融表：均值 + P95 + 校正后显著性，一臂一行。

    列序按 D13 排：**主判分指标在前**（Phase A 是 nDCG/MRR 排名，Phase B 是
    faithfulness/context_recall），Recall@k 退到后面只作天花板检查；分题型 nDCG 单独两列，
    因为总均值会把"事实题贴顶、术语题才是主战场"抹平。
    """
    phase = str(report.get("phase") or "A")
    metrics_family, binaries = significance_family(phase)
    primary = metrics_family[0]
    by_arm_p = {
        comparison.metric.split(":")[0]: comparison
        for comparison in comparisons
        if comparison.metric.endswith(f":{primary}")
    }
    columns = _PHASE_A_COLUMNS if phase != "B" else _PHASE_B_COLUMNS
    lines = [
        f"# Phase {phase} {'检索侧' if phase != 'B' else '生成侧'}消融表",
        "",
        f"- 题目数：{report.get('questions')}；语料：{report.get('corpus_docs')} 篇；"
        f"索引组：{len(report.get('index_groups') or {})} 个",
        f"- 预估耗时：{float(report.get('estimated_seconds') or 0)/60:.1f} min；"
        f"API 成本：¥{report.get('cost_cny_total')}"
        + ("（Phase A 零调用）" if phase != "B" else _cost_gate_note(report)),
        "",
        "| 臂 | 相对参照的唯一改动 | " + " | ".join(label for label, _ in columns)
        + f" | Δ{_METRIC_SHORT.get(primary, primary)} | 相对基线 |",
        "|---|---|" + "---|" * (len(columns) + 2),
    ]
    for arm_id, outcome in outcomes.items():
        arm = outcome.arm
        if outcome.error:
            rendered = f"❌ {outcome.error}"
        elif arm.role == "baseline":
            rendered = "（参照基线）"
        else:
            changes = arm.effective_changes(matrix.reference_for(arm))
            rendered = "、".join(f"{key}={new!r}" for key, (_, new) in sorted(changes.items()))
        comparison = by_arm_p.get(arm_id)
        if comparison is None:
            delta, rel = "—", "—"
        else:
            delta = f"{comparison.delta:+.4f}"
            lift = (comparison.detail or {}).get("rel_lift")
            rel = "n/a" if lift is None else f"{float(lift):+.1%}"
        cells = " | ".join(getter(outcome) for _, getter in columns)
        lines.append(f"| {arm_id} | {rendered} | {cells} | {delta} | {rel} |")
    lines += [
        "",
        _primary_note(phase, metrics_family),
        "> **不做显著性检验**：本题量（见「题目数」）不足以支撑可靠的 p 值结论，"
        "因此一律报「相对基线的绝对提升」，不给 p、不做族校正，避免用统计噪声冒充结论。",
        "> 相对基线 = Δ / 基线均值；基线为 0 时记 n/a。读表时先看 Δ 的绝对量级，再看相对百分比。",
    ]
    if phase == "B":
        lines.append(
            "> 一题只检索一次：检索列与生成列吃的是同一批 ``SearchHit``，"
            "所以「检索变好」与「答案变好」可以直接逐题对照，不存在两边材料不一致。"
        )
    return "\n".join(lines) + "\n"


def _at(arm: ArmConfig, source: dict[str, Any], stem: str) -> float | None:
    """取该臂**自己那个 k** 的指标值。列名写的是 ``@k``，就不能硬写 ``@5``：
    top_k 本身就是若干臂的自变量，写死会让那些臂整行变 n/a。"""
    for key in (f"{stem}_at_{arm.top_k}", f"{stem}_at_5"):
        if source.get(key) is not None:
            return float(source[key])
    return None


#: 摘要表列定义：(表头, 取值函数 → 已格式化的单元格文本)。
#: Phase A 与 Phase B 只有列不同，行、显著性、脚注是同一套。
_PHASE_A_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("nDCG@k", lambda o: _fmt(_at(o.arm, o.metrics, "ndcg"))),
    ("MRR@k", lambda o: _fmt(_at(o.arm, o.metrics, "mrr"))),
    ("命中率", lambda o: _fmt(_at(o.arm, o.metrics, "hit_rate"))),
    ("Recall@k(天花板)", lambda o: _fmt(_at(o.arm, o.metrics, "recall"))),
    ("术语 nDCG", lambda o: _fmt(_at(o.arm, o.by_type.get("term") or {}, "ndcg"))),
    ("事实 nDCG", lambda o: _fmt(_at(o.arm, o.by_type.get("factual") or {}, "ndcg"))),
    ("P95(ms)", lambda o: _fmt_ms(o.cost.get("retrieval_p95_ms"))),
)

_PHASE_B_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("faithfulness", lambda o: _fmt(o.metrics.get("faithfulness"))),
    ("context_recall", lambda o: _fmt(o.metrics.get("context_recall"))),
    ("幻觉率", lambda o: _fmt(o.metrics.get(HALLUCINATION_RATE_KEY))),
    ("拒答准确", lambda o: _fmt(o.metrics.get(REFUSAL_ACCURACY_KEY))),
    ("引用率", lambda o: _fmt(o.metrics.get("citation_rate"))),
    ("nDCG@k(传导)", lambda o: _fmt(_at(o.arm, o.metrics, "ndcg"))),
    ("e2e P95(ms)", lambda o: _fmt_ms(o.cost.get("e2e_p95_ms"))),
    ("¥/题", lambda o: _unit_cost_cell(o.cost)),
)


def _unit_cost_cell(cost: dict[str, Any]) -> str:
    value = cost.get("unit_cost_cny")
    return "—" if value is None else f"{float(value):.4f}"


def _primary_note(phase: str, metrics_family: tuple[str, ...]) -> str:
    if phase == "B":
        return (
            "> Phase B 主判分是 faithfulness 与 context_recall。nDCG@k 那列只用来看"
            "**检索增益有没有传导到答案**，不参与主判分。"
        )
    return (
        "> 主判分是 nDCG@5 与 MRR@5（D13）：Recall@5 在轨道 A 基线已 0.95+ 贴顶，"
        "只用作语料天花板检查。"
    )


def _cost_gate_note(report: dict[str, Any]) -> str:
    gate = report.get("cost_gate") or {}
    if not gate:
        return ""
    spent, cap = gate.get("spent_cny", 0.0), gate.get("max_cost_cny")
    unit = gate.get("unit_cost_cny")
    text = f"；闸门内已花 ¥{float(spent or 0.0):.4f} / 上限 ¥{cap}"
    text += f"；单价 {'未标定' if unit is None else f'¥{float(unit):.4f}/题'}"
    if gate.get("aborted"):
        text += "；**本次被成本闸中止**"
    return text


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _fmt_ms(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0f}"


def main(argv: list[str] | None = None) -> int:
    """CLI 入口（``scripts/run_ablation.py`` 转发到这里）。"""
    import argparse

    # 本机控制台默认 codepage 是 GBK，而报表文案里全是「¥」「≥」「臂」这类字符：
    # 不重配置的话，跑完 15 臂、print 单价那一步才 UnicodeEncodeError 退出码 1
    # —— 评测成功却报失败，是最难查的一种收尾事故。必须在 ArgumentParser 之前：
    # --help 和参数报错走 argparse 自己的 usage 打印，那条路径在 parse_args 里面。
    # 显式标注成 Any 元组：mypy 只看得到 TextIO，而它没有 reconfigure（union-attr）。
    streams: tuple[Any, ...] = (sys.stdout, sys.stderr)
    for stream in streams:
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # 被 pytest/管道换成的流没有 reconfigure
            pass

    parser = argparse.ArgumentParser(description="M3 消融实验 runner")
    parser.add_argument("--matrix", type=Path, default=PROJECT_ROOT / "evaluation/dataset/matrix_m3.yaml")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "evaluation/dataset/golden_a_cmrc.jsonl")
    parser.add_argument("--fixtures", type=Path, default=PROJECT_ROOT / "evaluation/fixtures_cmrc")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "evaluation/reports/ablation")
    parser.add_argument("--phase", default="A", choices=("A", "B"))
    parser.add_argument("--arm", action="append", default=[], help="只跑指定臂（可多次传入）")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="smoke 只跑 N 题：**按题型分层抽**（不是取前 N 条 —— 前 N 条永远是纯事实题，"
        "验不到拒答路径，单价也会被高估）",
    )
    parser.add_argument("--max-seconds", type=float, default=3 * 3600.0, help="预估耗时预算闸门")
    parser.add_argument(
        "--max-cost-cny",
        type=float,
        default=PHASE_B_MAX_COST_DEFAULT_CNY,
        help=f"Phase B 的金钱闸门（默认 ¥{PHASE_B_MAX_COST_DEFAULT_CNY:g}；Phase A 恒为 0）",
    )
    parser.add_argument(
        "--unit-cost-cny",
        type=float,
        default=None,
        help="实测单题成本（元/题），来自 --limit 15 的 smoke；不给则只做逐题硬闸",
    )
    parser.add_argument("--keep-work", action="store_true", help="保留每臂临时库目录（排障用）")
    parser.add_argument("--list", action="store_true", dest="list_only", help="只打印矩阵计划")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    matrix = load_matrix(args.matrix)
    problems = matrix.validate()
    if problems:
        print("实验矩阵非法：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    print(f"矩阵 {args.matrix.name}：{len(matrix.all_arms)} 臂")
    for line in matrix.summary_lines():
        print(line)
    if args.list_only:
        return 0

    try:
        report = run_matrix(
            matrix,
            dataset=args.dataset,
            fixtures=args.fixtures,
            out_dir=args.out,
            phase=args.phase,
            only_arms=args.arm,
            limit=args.limit,
            max_seconds=args.max_seconds,
            max_cost_cny=args.max_cost_cny,
            unit_cost_cny=args.unit_cost_cny,
            keep_work=args.keep_work,
        )
    except AblationError as exc:
        print(f"消融未跑成：{exc}", file=sys.stderr)
        return 1
    print(f"完成：{len(report['arms'])} 臂 → {args.out / 'ablation_table.md'}")
    unit = _worst_unit_cost(report)
    if unit is not None:
        print(
            f"实测单价（最贵的臂）¥{unit:.4f}/题 → 全量预检就传 --unit-cost-cny {unit:.4f}"
        )
    return 0


def _worst_unit_cost(report: dict[str, Any]) -> float | None:
    """取各臂里最贵的单题成本 —— 预检宁可保守，按便宜的臂估会低估。"""
    units = [
        float((arm.get("cost") or {}).get("unit_cost_cny") or 0.0)
        for arm in (report.get("arms") or {}).values()
        if (arm.get("cost") or {}).get("unit_cost_cny") is not None
    ]
    return max(units) if units else None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
