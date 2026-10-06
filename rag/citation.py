"""引用标注的解析与校验（M3 · T5）。

为什么单独一个模块：引用「有没有编出来」是 E4 溯源臂的**判分依据**，
它必须能和"模型答得好不好"分开算，所以解析规则要能被单测钉住，而不是埋在 prompt 里。

编号约定与 ``core/llm/prompts/v1/answer_*.md`` 里的 ``【材料N】`` 顺序一一对应
（顺序即编号，见 :func:`rag.answer.format_materials`）。
"""

from __future__ import annotations

import re

from rag.exceptions import RagError

__all__ = [
    "REFUSAL_MARKERS",
    "REFUSAL_SENTENCE",
    "check_materials",
    "drop_invalid_citations",
    "final_answer",
    "is_refusal",
    "parse_citations",
]

#: 模型被要求写成 ``【材料2】``；方括号/圆括号/全半角的实际输出都比 prompt 说的野，
#: 所以两种括号都收 —— 少认一个写法就会把真引用记成"无引用"，溯源指标被低估。
_CITATION_RE = re.compile(r"[【\[]\s*材料\s*(\d+)\s*[】\]]")

#: 拒答模板串。**必须与 answer_refusal.md 里那句一字不差**（有单测钉住这条耦合）。
REFUSAL_SENTENCE = "根据现有资料无法回答"

#: 判定用的前缀集合：模型常在这句前后加标点或补半句，只认整句会把正确拒答算成失败。
REFUSAL_MARKERS = (REFUSAL_SENTENCE, "无法根据现有资料回答", "资料中未提及", "材料未提及")

#: CoT 版要求答案以 ``【答案】`` 起头；模板串改了要同步改这里。
_ANSWER_MARKER = "【答案】"


def parse_citations(text: str) -> list[int]:
    """按出现顺序取出不重复的被引编号。"""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(text):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def drop_invalid_citations(text: str, total: int) -> tuple[str, list[int], list[int]]:
    """删掉指向不存在材料的编号，返回 ``(清理后的文本, 合法编号, 非法编号)``。

    为什么是**删掉**而不是留着标红：下游的引用忠实度评分要按"文本里剩下的引用"逐条核对，
    留着 【材料9】 这种幻觉编号等于让 judge 去核对一个根本不存在的材料，只会把分数算脏。
    非法编号单独计数上报（``invalid_citations``），编造这件事在报表里看得见，但不进正文。
    """
    valid: list[int] = []
    invalid: list[int] = []
    for number in parse_citations(text):
        (valid if 1 <= number <= total else invalid).append(number)

    def _replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return match.group(0) if 1 <= number <= total else ""

    cleaned = _CITATION_RE.sub(_replace, text) if invalid else text
    return cleaned, valid, invalid


def is_refusal(text: str) -> bool:
    """是否命中拒答模板。"""
    normalized = text.strip().replace(" ", "")
    return any(marker in normalized for marker in REFUSAL_MARKERS)


def final_answer(text: str) -> str:
    """CoT 版只留最终答案，思考段不进判分。"""
    if _ANSWER_MARKER in text:
        return text.split(_ANSWER_MARKER, 1)[1].strip()
    cleaned = re.sub(r"<思考>.*?</思考>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<思考>.*", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def check_materials(materials: list[tuple[str, str]]) -> None:
    """材料必须都带正文：空材料会白占一个编号，引用校验从此不可信。"""
    empty = [index for index, (text, _) in enumerate(materials, start=1) if not text.strip()]
    if empty:
        raise RagError(
            f"第 {empty} 条材料没有正文（检索命中了空 chunk？）：生成前先剔除或回填",
            stage="generation",
        )
