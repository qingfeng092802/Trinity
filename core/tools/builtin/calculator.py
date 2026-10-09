"""calculator：安全计算算术表达式。

刻意**不用** ``eval``：先把表达式解析成 AST，再只放行白名单里的运算符、函数与常量。
外层还有三道闸——表达式长度、幂指数上限、结果量级——挡住 ``9**9**9`` 这类
「合法但会算到天荒地老 / 撑爆内存」的输入。
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Annotated, Any

from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec

#: 表达式长度上限（字符）
MAX_EXPRESSION_LENGTH = 200
#: 幂指数绝对值上限
MAX_POWER = 1000
#: 结果量级上限（超过视为溢出）
MAX_RESULT_MAGNITUDE = 1e12

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "degrees": math.degrees,
    "radians": math.radians,
}

_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}


class CalculatorError(ValueError):
    """表达式非法或无法计算。"""


def _eval_node(node: ast.AST) -> float:
    """递归求值单个 AST 节点，只放行白名单语法。"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculatorError(f"不支持的常量：{node.value!r}")
        return float(node.value)

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError(f"不支持的运算符：{type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER:
            raise CalculatorError(f"指数过大（上限 {MAX_POWER}）：{right}")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalculatorError("除数不能为 0")
        return float(op(left, right))

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError(f"不支持的一元运算符：{type(node.op).__name__}")
        return float(op(_eval_node(node.operand)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalculatorError("只支持直接调用内置数学函数，不支持属性访问")
        if node.keywords:
            raise CalculatorError("不支持关键字参数")
        func = _FUNCTIONS.get(node.func.id)
        if func is None:
            raise CalculatorError(f"不支持的函数：{node.func.id}")
        return float(func(*[_eval_node(arg) for arg in node.args]))

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalculatorError(f"未知标识符：{node.id}")

    raise CalculatorError(f"不支持的语法：{type(node).__name__}")


def _format(value: float) -> str:
    """整数值去掉小数点，其余保留 10 位有效小数。"""
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def calculator(
    expression: Annotated[
        str,
        Field(description="要计算的算术表达式，例如 (3+5)*2**3、sqrt(2)、log(100,10)"),
    ],
) -> str:
    """计算一个算术表达式并返回数值结果（支持四则运算、幂、开方、对数、三角函数）。"""
    text = expression.strip()
    if not text:
        raise CalculatorError("表达式不能为空")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(f"表达式过长（上限 {MAX_EXPRESSION_LENGTH} 字符）")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"表达式语法错误：{exc.msg}") from exc

    value = _eval_node(tree)
    if not math.isfinite(value):
        raise CalculatorError("计算结果不是有限数（出现溢出或非法运算）")
    if abs(value) > MAX_RESULT_MAGNITUDE:
        raise CalculatorError(f"计算结果超出量级上限 {MAX_RESULT_MAGNITUDE:g}")
    return _format(value)


def register(registry: ToolRegistry) -> ToolSpec:
    """把 calculator 注册进给定注册表。"""
    return registry.register(
        calculator,
        name="calculator",
        description=(
            "计算一个算术表达式并返回精确数值。涉及四则运算、幂、开方、对数、三角函数时"
            "必须调用本工具，不要自己心算"
        ),
        danger_level="low",
        timeout=5,
        retry=0,
    )


__all__ = ["CalculatorError", "calculator", "register"]
