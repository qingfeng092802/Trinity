"""内置工具集：**对外只暴露 3 个**——calculator / knowledge_search / code_exec。

每个工具模块只负责定义函数与 :func:`register`，**不在 import 时自动注册**——
注册时机由调用方决定（:func:`load_builtin_tools` 或自己建独立注册表），
这样测试可以拿到互不干扰的注册表实例。

``knowledge_search`` 的服务注入在注册**之后**进行（T04 子步骤 4）：
``api.deps.get_tool_registry`` 与 ``api.runner.build_runner`` 装配完注册表后
调用 ``knowledge_search.set_knowledge_service(service)``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from core.tools.builtin import calculator, code_exec, extract, file_io, knowledge_search, web_search
from core.tools.registry import ToolRegistry, ToolSpec, default_registry
from core.tools.validators import ToolRegistrationError

logger = logging.getLogger(__name__)

#: 内置工具的注册函数（顺序即提示词里的展示顺序）
#:
#: **工具面收敛（2026-09-20）**：对外工具面从 6 个收敛到 3 个——
#: ``calculator``（确定性计算）/ ``knowledge_search``（RAG 检索 + 引用溯源）/
#: ``code_exec``（受限子进程沙箱，安全边界见 ``code_exec.py`` 的 docstring）。
#:
#: ``web_search`` / ``file_io`` / ``extract`` 的**模块保留在仓库里但不再默认注册**：
#: 它们属于 ``core`` 既有实现，直接删文件会同时打掉覆盖它们的回归测试，代价高于收益。
#: 收敛通过「不注册」实现——``GET /tools`` 与 Agent 提示词里都只会出现 3 个工具。
BUILTIN_REGISTRARS: tuple[Callable[[ToolRegistry], ToolSpec], ...] = (
    calculator.register,
    knowledge_search.register,
    code_exec.register,
)

#: 被收敛下线、但源码仍保留的工具（仅供测试与回溯，不进默认注册表）。
RETIRED_BUILTIN_REGISTRARS: tuple[Callable[[ToolRegistry], ToolSpec], ...] = (
    file_io.register,
    web_search.register,
    extract.register,
)


def load_builtin_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """把 3 个内置工具注册进给定注册表（默认全局注册表）。

    幂等：已注册的工具会跳过，重复调用不会抛错。
    注意：本函数**不做** knowledge_search 的服务注入——那由 api 层在
    装配完成后调用（注册先于注入，见模块 docstring）。
    """
    target = registry if registry is not None else default_registry()
    for registrar in BUILTIN_REGISTRARS:
        try:
            registrar(target)
        except ToolRegistrationError as exc:
            logger.debug("内置工具已注册，跳过：%s", exc)
    logger.debug("内置工具就绪：%s", ", ".join(target.names()))
    return target


__all__ = [
    "BUILTIN_REGISTRARS",
    "calculator",
    "code_exec",
    "extract",
    "file_io",
    "knowledge_search",
    "load_builtin_tools",
    "web_search",
]
