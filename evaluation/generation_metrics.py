"""生成侧四指标评分器（M3 · T6，按 RAGAS 论文口径自实现 —— 见 m3_design.md D2）。

为什么不引入 ragas 库：它硬拉 scikit-network（Cython 二进制，本机应用控制策略会拦）与
langchain-community（与本项目 langchain-core 1.x  resolver 打架），且要求异步 Runnable 而
``core/llm/adapter.py`` 全同步。四条指标本质都是"一个 prompt + 一次结构化调用 + 一个公式"。

口径要点（报表里所有数字都受这几条约束，写在代码旁边而不是散落在文档里）：

* **拒答题不算四指标**：模型正确拒答时材料里本来就没有答案，faithfulness 会把"没编造"
  算成 0 分还是 1 分都没意义。它只进 ``refusal_correct``（McNemar 的二值配对列）。
* **判定式请求一律合并**：全部陈述一次 NLI、top-k 材料一次判相关，
  成本约为逐条调用方案的 1/3（D2 的成本账）。
* **模型返回的长度必须与输入条数一致**，否则直接报错：悄悄补零或截断会让指标看着正常但全是错的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from pydantic import BaseModel, Field

from core.agent.base import render_prompt

__all__ = [
    "METRIC_NAMES",
    "GenerationScore",
    "GenerationScorer",
    "MetricsError",
    "context_precision",
    "mean_or_none",
]

#: 报表与显著性族里的连续指标列名（顺序稳定，逐题配对才可比）。
METRIC_NAMES = ("faithfulness", "context_precision", "answer_relevancy", "context_recall")


class MetricsError(RuntimeError):
    """judge 输出与输入对不上等"再算下去就是假数字"的情况。"""


class _Statements(BaseModel):
    statements: list[str] = Field(default_factory=list)


class _Values(BaseModel):
    values: list[int] = Field(default_factory=list)


class _Questions(BaseModel):
    questions: list[str] = Field(default_factory=list)


class _RecallItem(BaseModel):
    claim: str = ""
    supported: int = 0


class _RecallItems(BaseModel):
    items: list[_RecallItem] = Field(default_factory=list)


def mean_or_none(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def context_precision(relevance: Sequence[int]) -> float | None:
    """RAGAS 口径的 context precision：命中的位置越靠前分越高。

    ``sum(precision@k * v_k) / 相关材料总数``。没有一条相关时返回 **None** 而不是 0 ——
    库里根本没有可用材料是语料/检索问题，不该记在生成臂的分数上。
    """
    if not relevance:
        return None
    relevant = sum(1 for flag in relevance if flag)
    if relevant == 0:
        return None
    total = 0.0
    hits = 0
    for index, flag in enumerate(relevance, start=1):
        if flag:
            hits += 1
            total += hits / index
    return round(total / relevant, 4)


@dataclass(slots=True)
class GenerationScore:
    """一题的生成侧评分。``metrics`` 里的 None 表示"该题这指标不适用"，不是 0 分。"""

    metrics: dict[str, float | None] = field(default_factory=dict)
    refusal_correct: bool | None = None
    hallucination: float | None = None
    cost_cny: float = 0.0
    token_in: int = 0
    token_out: int = 0
    calls: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def metric(self, name: str) -> float | None:
        return self.metrics.get(name)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.metrics,
            "hallucination": self.hallucination,
            "refusal_correct": self.refusal_correct,
            "judge_cost_cny": round(self.cost_cny, 6),
            "judge_token_in": self.token_in,
            "judge_token_out": self.token_out,
            "judge_calls": self.calls,
            "detail": self.detail,
        }


class GenerationScorer:
    """四指标评分器。``llm`` / ``embedder`` 都以构造参数注入，测试整包换掉。"""

    def __init__(
        self,
        *,
        llm: Any = None,
        embedder: Any = None,
        judge_model: str | None = None,
        prompt_version: str = "v1",
        relevancy_questions: int = 3,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self.judge_model = judge_model
        self.prompt_version = prompt_version
        self.relevancy_questions = relevancy_questions
        self.cost_cny = 0.0
        self.token_in = 0
        self.token_out = 0
        self.calls = 0

    # ------------------------------------------------------------- 内部 ----
    def _model(self) -> Any:
        if self._llm is None:
            from core.llm.adapter import get_adapter

            # judge 温度钉死 0：评分本身抖一下，配对检验就多出几个假的不一致对。
            self._llm = get_adapter(temperature=0.0)
        return self._llm

    def _ask(self, role: str, model_cls: type[BaseModel], **values: Any) -> Any:
        prompt = render_prompt(role, self.prompt_version, **values)
        result = self._model().invoke_model(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请按规则只输出 JSON。"},
            ],
            model_cls,
            model=self.judge_model,
        )
        usage = getattr(self._model(), "last_usage", None)
        if usage is not None:
            self.cost_cny += float(usage.cost)
            self.token_in += int(usage.token_in)
            self.token_out += int(usage.token_out)
            self.calls += 1
        return result

    @staticmethod
    def _check_len(values: Sequence[int], expected: int, what: str) -> list[int]:
        if len(values) != expected:
            raise MetricsError(
                f"{what} 判定条数对不上：输入 {expected} 条，模型只给了 {len(values)} 条"
                "（缺一条都不许猜，否则指标是假的）"
            )
        return [1 if int(flag) else 0 for flag in values]

    @staticmethod
    def _materials_text(materials: Sequence[Any]) -> str:
        return "\n\n".join(
            f"【材料{n}】{getattr(hit, 'document_name', '') or getattr(hit, 'document_id', '')}"
            f"\n{getattr(hit, 'text', hit)}"
            for n, hit in enumerate(materials, start=1)
        )

    @staticmethod
    def _statements_text(items: Sequence[str]) -> str:
        return "\n".join(f"{n}. {text}" for n, text in enumerate(items, start=1))

    # ------------------------------------------------------------- 打分 ----
    def score(
        self,
        *,
        question: str,
        answer: str,
        materials: Sequence[Any] = (),
        reference: str = "",
        refused: bool = False,
        expected_refusal: bool = False,
    ) -> GenerationScore:
        """跑一题的四指标。返回对象里的 ``cost_cny`` 已含本次全部 judge 调用。"""
        score = GenerationScore(
            metrics={name: None for name in METRIC_NAMES},
            refusal_correct=(refused == expected_refusal),
        )
        if refused:
            # 正确/错误拒答都只进二值列：没有实质答案，四个连续指标全是不适用。
            score.detail["skipped"] = "refused"
            self._merge(score)
            return score
        if not answer.strip():
            score.detail["skipped"] = "empty_answer"
            self._merge(score)
            return score

        score.metrics["faithfulness"] = self._faithfulness(answer, materials, score)
        score.metrics["context_precision"] = self._context_precision(question, reference, materials, score)
        score.metrics["answer_relevancy"] = self._answer_relevancy(question, answer, score)
        score.metrics["context_recall"] = self._context_recall(question, reference, materials, score)
        score.hallucination = (
            None
            if score.metrics["faithfulness"] is None
            else round(1.0 - score.metrics["faithfulness"], 4)
        )
        self._merge(score)
        return score

    def _merge(self, score: GenerationScore) -> None:
        """把本次调用量折进结果并清零，报表逐题可加。"""
        score.cost_cny = round(self.cost_cny, 6)
        score.token_in = self.token_in
        score.token_out = self.token_out
        score.calls = self.calls
        self.cost_cny = 0.0
        self.token_in = 0
        self.token_out = 0
        self.calls = 0

    def _faithfulness(self, answer: str, materials: Sequence[Any], score: GenerationScore) -> float | None:
        split = self._ask("metric_faithfulness_split", _Statements, answer=answer)
        statements = [text.strip() for text in split.statements if text.strip()]
        if not statements:
            score.detail["faithfulness"] = "无可核查陈述"
            return None
        verdicts = self._ask(
            "metric_faithfulness_nli",
            _Values,
            materials=self._materials_text(materials),
            statements=self._statements_text(statements),
        )
        flags = self._check_len(verdicts.values, len(statements), "faithfulness")
        score.detail["statements"] = [
            {"text": text, "supported": flag} for text, flag in zip(statements, flags, strict=True)
        ]
        return mean_or_none([float(flag) for flag in flags])

    def _context_precision(
        self, question: str, reference: str, materials: Sequence[Any], score: GenerationScore
    ) -> float | None:
        if not materials:
            score.detail["context_precision"] = "无材料"
            return None
        verdicts = self._ask(
            "metric_context_precision",
            _Values,
            question=question,
            reference=reference.strip() or "（无参考答案）",
            materials=self._materials_text(materials),
        )
        flags = self._check_len(verdicts.values, len(materials), "context_precision")
        score.detail["context_relevance"] = flags
        return context_precision(flags)

    def _answer_relevancy(self, question: str, answer: str, score: GenerationScore) -> float | None:
        if self._embedder is None:
            score.detail["answer_relevancy"] = "未注入 embedder"
            return None
        generated = self._ask(
            "metric_answer_relevancy", _Questions, answer=answer, count=str(self.relevancy_questions)
        )
        questions = [text.strip() for text in generated.questions if text.strip()]
        if not questions:
            score.detail["answer_relevancy"] = "拒答式答案，不计算"
            return None
        vectors = self._embedder.embed([question, *questions])
        base, rest = vectors[0], vectors[1:]
        score.detail["generated_questions"] = questions
        return mean_or_none([_cosine(base, item) for item in rest])

    def _context_recall(
        self, question: str, reference: str, materials: Sequence[Any], score: GenerationScore
    ) -> float | None:
        if not reference.strip() or not materials:
            score.detail["context_recall"] = "缺参考答案或无材料"
            return None
        result = self._ask(
            "metric_context_recall",
            _RecallItems,
            question=question,
            reference=reference,
            materials=self._materials_text(materials),
        )
        items = [item for item in result.items if item.claim.strip()]
        if not items:
            score.detail["context_recall"] = "参考答案拆不出要点"
            return None
        score.detail["recall_claims"] = [
            {"claim": item.claim.strip(), "supported": 1 if item.supported else 0} for item in items
        ]
        return mean_or_none([1.0 if item.supported else 0.0 for item in items])


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise MetricsError(f"向量维度不一致：{len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
    if norm == 0:
        raise MetricsError("零向量参与余弦计算，嵌入结果异常")
    return max(0.0, min(1.0, dot / norm))
