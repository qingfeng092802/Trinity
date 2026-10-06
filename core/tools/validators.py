"""工具参数校验：把 Python 函数的签名与类型注解变成 Pydantic 模型和 JSON Schema。

工具作者只需要写正常的 Python 函数并标好类型，剩下的三件事由本模块自动完成：

1. 用 ``create_model`` 生成参数模型（``extra="forbid"``，模型编造出来的多余参数会被拦下）；
2. 导出干净的 JSON Schema 塞进提示词，让模型知道每个参数叫什么、什么类型；
3. 调用时做字段级校验，把 Pydantic 的报错翻译成模型能看懂的一句话。

用 ``Annotated[X, Field(description="...")]`` 可以给参数补说明，说明会进 JSON Schema。
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model
from pydantic.fields import FieldInfo


class ToolRegistrationError(ValueError):
    """工具定义本身不合法（缺类型注解、用了 ``*args`` 之类）。"""


class ToolValidationError(ValueError):
    """调用参数不合法。字段级明细放在 :attr:`errors` 里，便于回灌给模型修正。"""

    def __init__(self, message: str, *, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.errors: list[dict[str, str]] = errors or []


def _describe(annotation: Any, param_name: str) -> Any:
    """参数没有自带说明时补一句默认描述，避免 JSON Schema 里全是裸类型。"""
    if typing.get_origin(annotation) is typing.Annotated:
        metadata = typing.get_args(annotation)[1:]
        if any(isinstance(item, FieldInfo) for item in metadata):
            return annotation
    return typing.Annotated[annotation, Field(description=f"参数 {param_name}")]


def build_params_model(tool_name: str, func: Callable[..., Any]) -> type[BaseModel]:
    """按函数签名动态生成参数模型。

    Raises:
        ToolRegistrationError: 参数缺类型注解，或使用了 ``*args`` / ``**kwargs``。
    """
    signature = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception as exc:  # 注解写错时给出可读错误，而不是把 NameError 抛给调用方
        raise ToolRegistrationError(f"工具 {tool_name} 的类型注解无法解析：{exc}") from exc

    fields: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ToolRegistrationError(
                f"工具 {tool_name} 不支持 *args / **kwargs（参数 {param_name}）："
                "无法生成确定性的 JSON Schema"
            )
        if param_name in {"self", "cls"}:
            continue
        annotation = hints.get(param_name)
        if annotation is None:
            raise ToolRegistrationError(
                f"工具 {tool_name} 的参数 {param_name} 缺少类型注解，无法生成 JSON Schema"
            )
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (_describe(annotation, param_name), default)

    if not fields:
        # 无参工具也要有模型，方便统一走校验路径
        return create_model(f"{tool_name}_Params", __config__=ConfigDict(extra="forbid"))

    return create_model(
        f"{tool_name}_Params",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _strip_titles(node: Any) -> None:
    """递归删掉 JSON Schema 里的 ``title``：字段名已经足够，留着只会污染提示词。"""
    if isinstance(node, dict):
        node.pop("title", None)
        for value in node.values():
            _strip_titles(value)
    elif isinstance(node, list):
        for item in node:
            _strip_titles(item)


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """导出精简后的 JSON Schema，可直接塞进提示词。"""
    schema = model.model_json_schema()
    _strip_titles(schema)
    return schema


def validate_args(
    model: type[BaseModel],
    args: dict[str, Any],
    *,
    tool_name: str,
) -> dict[str, Any]:
    """校验并补默认值，返回可直接 ``func(**kwargs)`` 的字典。

    Raises:
        ToolValidationError: 入参不是对象，或字段缺失 / 类型不符 / 出现多余字段。
    """
    if not isinstance(args, dict):
        raise ToolValidationError(
            f"工具 {tool_name} 的入参必须是 JSON 对象，实际收到 {type(args).__name__}"
        )
    try:
        return model.model_validate(args).model_dump()
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"]) or "<root>",
                "message": str(item["msg"]),
            }
            for item in exc.errors()
        ]
        detail = "；".join(f"{item['field']} {item['message']}" for item in errors)
        raise ToolValidationError(
            f"工具 {tool_name} 参数校验失败：{detail}",
            errors=errors,
        ) from exc


__all__ = [
    "ToolRegistrationError",
    "ToolValidationError",
    "build_params_model",
    "json_schema_for",
    "validate_args",
]
