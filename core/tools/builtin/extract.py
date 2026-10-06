"""extract：用 LLM 从自由文本里抽出结构化数据。

这个工具是「LLM 当函数用」的典型场景：输入一段非结构化文本 + 一份 JSON Schema，
输出符合 Schema 的 JSON。真正干活的是 ``LLMAdapter.invoke_json``，所以它自带
「抽取 → 校验 → 带错误回灌重试」的全套容错，schema 不满足会重试而不是直接失败。
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from pydantic import Field

from core.llm.adapter import get_adapter
from core.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)

#: 送入模型的原文长度上限（超出截断，避免一次调用吃光预算）
MAX_TEXT_CHARS = 12000

_EXTRACT_INSTRUCTION = (
    "从下面的文本中抽取信息，严格按给定的 JSON Schema 输出。\n"
    "要求：\n"
    "1. 只输出 JSON，不要任何解释；\n"
    "2. 只用文本里真实存在的信息，缺失的字段留空字符串或空数组，**不要编造**；\n"
    "3. 数字要转成数值类型，不要带单位。\n\n"
    "文本：\n{text}"
)


class ExtractError(ValueError):
    """抽取失败（schema 非法等）。"""


def extract(
    text: Annotated[str, Field(description="要抽取信息的原始文本")],
    target_schema: Annotated[
        str,
        # 对外（JSON Schema、提示词、模型调用）的键名是 schema；Python 侧叫 target_schema，
        # 因为字段名直接叫 schema 会遮蔽 BaseModel.schema 并触发 pydantic 告警
        Field(
            alias="schema",
            description=(
                "描述目标结构的 JSON Schema 字符串，例如 "
                '{"type":"object","properties":{"company":{"type":"string"}}}'
            ),
        ),
    ],
) -> str:
    """用 LLM 从文本中抽取符合给定 JSON Schema 的结构化数据，返回格式化 JSON。

    参数对模型暴露的名字是 ``text`` 与 ``schema``（见 JSON Schema）。
    """
    raw_schema = target_schema.strip()
    if not raw_schema:
        raise ExtractError("schema 不能为空")
    try:
        parsed_schema: Any = json.loads(raw_schema)
    except json.JSONDecodeError as exc:
        raise ExtractError(f"schema 不是合法 JSON：{exc.msg}") from exc
    if not isinstance(parsed_schema, dict):
        raise ExtractError("schema 必须是一个 JSON 对象（如 {'type': 'object', ...}）")

    content = text.strip()
    if not content:
        raise ExtractError("text 不能为空")
    if len(content) > MAX_TEXT_CHARS:
        logger.info("输入文本 %d 字符，截断到 %d", len(content), MAX_TEXT_CHARS)
        content = content[:MAX_TEXT_CHARS]

    adapter = get_adapter()
    data = adapter.invoke_json(
        [{"role": "user", "content": _EXTRACT_INSTRUCTION.format(text=content)}],
        parsed_schema,
        model=adapter.settings.llm_model_small,
    )
    return json.dumps(data, ensure_ascii=False, indent=2)


def register(registry: ToolRegistry) -> ToolSpec:
    """把 extract 注册进给定注册表。"""
    return registry.register(
        extract,
        name="extract",
        description=(
            "从一段自由文本里抽取结构化字段（返回 JSON）。需要把非结构化描述变成"
            "规整数据时使用；schema 用 JSON Schema 字符串描述目标结构"
        ),
        danger_level="low",
        timeout=60,
        retry=1,
    )


__all__ = ["MAX_TEXT_CHARS", "ExtractError", "extract", "register"]
