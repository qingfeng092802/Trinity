"""直接生成通路（M3 · T5）：检索 → 编号化材料 → prompt → LLM → 引用校验 → 拒答判定。

M2 只有「工具被 Agent 调用」这一条 RAG 路径，答得好不好混在整条工作流里量不出来。
E4 四版 prompt 要的是**可复现的单次生成**：检索与生成分开计时、温度钉死、
引用合法性在本地判（不依赖模型自述），这样 T6 的四指标评分器才拿得到干净的输入。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from copy import copy
from dataclasses import dataclass, field
from typing import Any

from core.agent.base import render_prompt
from core.llm.adapter import Usage
from rag.types import safe_document_label
from rag.citation import (
    check_materials,
    drop_invalid_citations,
    final_answer,
    is_refusal,
    parse_citations,
)
from rag.exceptions import RagError
from rag.types import SearchHit

__all__ = ["ANSWER_TEMPERATURE", "PROMPT_ROLES", "RagAnswer", "RagAnswerer", "format_materials"]

#: E4 的四版 prompt（= 矩阵里的 ``prompt`` 臂字段）。
PROMPT_ROLES = ("answer_basic", "answer_cot", "answer_grounding", "answer_refusal")

#: 消融实验里温度**不是旋钮**：0.0 钉死，否则"prompt 改了"和"采样抖了一下"分不开。
#: 要改温度必须走 :func:`core.llm.adapter.reset_adapters`（适配器按温度 lru_cache）。
ANSWER_TEMPERATURE = 0.0

SearchFn = Callable[[str, int], list[SearchHit]]


@dataclass(slots=True)
class RagAnswer:
    """一次端到端生成。检索延迟与端到端延迟**分开记**，否则没法归因。"""

    question: str
    answer: str
    prompt: str
    contexts: list[SearchHit] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    valid_citations: list[int] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    refused: bool = False
    usage: Usage = field(default_factory=Usage)
    retrieval_ms: int = 0
    latency_ms: int = 0

    @property
    def citation_rate(self) -> float | None:
        """被引材料占送进 prompt 的材料数的比例（拒答/无材料时 None，不进均值）。"""
        if not self.contexts or is_refusal(self.answer):
            return None
        return round(len(self.valid_citations) / len(self.contexts), 4)

    def sources(self) -> list[str]:
        """合法引用指向的来源行，顺序即编号。"""
        return [self.contexts[index - 1].citation() for index in self.valid_citations]

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "prompt": self.prompt,
            "refused": self.refused,
            "citations": self.citations,
            "valid_citations": self.valid_citations,
            "invalid_citations": self.invalid_citations,
            "citation_rate": self.citation_rate,
            "sources": self.sources(),
            "contexts": [hit.citation() for hit in self.contexts],
            "usage": self.usage.as_dict(),
            "retrieval_ms": self.retrieval_ms,
            "latency_ms": self.latency_ms,
        }


def format_materials(hits: Sequence[SearchHit]) -> str:
    """把命中渲染成 ``【材料N】`` 编号块，**列表顺序就是编号顺序**。

    来源行带着 chunk 序号与字符区间，模型要抄也抄不准成"材料1"以外的东西；
    编号只在本轮有效，所以任何改动命中顺序的代码都会静默改变引用含义 —— 判分依赖的
    正是这个不变量。
    """
    blocks: list[str] = []
    for number, hit in enumerate(hits, start=1):
        blocks.append(
            f"【材料{number}】{safe_document_label(hit.document_name, hit.document_id)}"
            f" · chunk {hit.chunk_seq}（字符 {hit.start_char}-{hit.end_char}）\n{hit.text}"
        )
    return "\n\n".join(blocks) if blocks else "（无材料）"


class RagAnswerer:
    """一次问答的门面。检索侧以 callable 注入，Phase B 各臂才能换融合/重排而不换生成。"""

    def __init__(
        self,
        *,
        search: SearchFn,
        adapter: Any = None,
        model: str | None = None,
        prompt: str = "answer_basic",
        top_k: int = 5,
    ) -> None:
        if prompt not in PROMPT_ROLES:
            raise RagError(
                f"未知 prompt 版本 {prompt!r}，只认 {list(PROMPT_ROLES)}", stage="generation"
            )
        self._search = search
        self._adapter = adapter
        self._model = model
        self.prompt = prompt
        self.top_k = top_k

    @classmethod
    def from_service(cls, service: Any, **kwargs: Any) -> "RagAnswerer":
        """生产/评测默认走 :class:`rag.service.KnowledgeService` 的检索。"""
        return cls(search=lambda query, top_k: service.search(query, top_k), **kwargs)

    def _llm(self) -> Any:
        if self._adapter is None:
            from core.llm.adapter import get_adapter

            self._adapter = get_adapter(temperature=ANSWER_TEMPERATURE)
        return self._adapter

    def answer(self, question: str, *, prompt: str | None = None, top_k: int | None = None) -> RagAnswer:
        """跑完整通路。``prompt`` / ``top_k`` 不传时用构造时的臂配置。"""
        role = prompt or self.prompt
        if role not in PROMPT_ROLES:
            raise RagError(f"未知 prompt 版本 {role!r}，只认 {list(PROMPT_ROLES)}", stage="generation")
        cleaned = question.strip()
        if not cleaned:
            raise RagError("问题不能为空", stage="generation")
        k = top_k if top_k is not None else self.top_k

        started = time.perf_counter()
        hits = list(self._search(cleaned, k))
        retrieval_ms = int((time.perf_counter() - started) * 1000)

        materials = [(hit.text, hit.document_id) for hit in hits]
        check_materials(materials)
        rendered = format_materials(hits)
        text = render_prompt(
            role, "v1", materials=rendered, materials_count=str(len(hits)), question=cleaned
        )

        adapter = self._llm()
        raw = adapter.invoke(
            [{"role": "user", "content": text}],
            self._model,
            temperature=ANSWER_TEMPERATURE,
        )
        usage = copy(adapter.last_usage)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        body = final_answer(str(raw))
        refused = is_refusal(body)
        body, valid, invalid = drop_invalid_citations(body, len(hits))
        numbers = parse_citations(body)
        return RagAnswer(
            question=cleaned,
            answer=body,
            prompt=role,
            contexts=hits,
            citations=numbers,
            valid_citations=valid,
            invalid_citations=invalid,
            refused=refused,
            usage=usage,
            retrieval_ms=retrieval_ms,
            latency_ms=elapsed_ms,
        )
