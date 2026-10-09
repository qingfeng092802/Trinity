"""工具系统：统一注册表、参数校验、沙箱执行与 5 个内置工具。

对外只需要两个入口：

* :class:`~core.tools.registry.ToolRegistry` —— 建注册表、注册工具、调用工具；
  它同时满足 ``core.agent.base.ToolInvoker`` 协议，可直接注入 ``NodeContext``。
* :func:`~core.tools.builtin.load_builtin_tools` —— 一次性装好 5 个内置工具。

子模块之间一律走**直接导入**（``from core.tools.sandbox import ...``）而不是
``from core.tools import sandbox``，避免与本包 ``__init__`` 形成循环导入。
"""

from __future__ import annotations

from core.tools.builtin import load_builtin_tools
from core.tools.registry import (
    RESULT_LIMIT,
    HitlApprover,
    ToolDanger,
    ToolRegistry,
    ToolSpec,
    call_tool,
    default_registry,
    get_tool,
    list_tools,
    register_tool,
    reset_default_registry,
)
from core.tools.sandbox import (
    ProcessResult,
    SandboxError,
    SandboxFailed,
    SandboxPathError,
    SandboxTimeout,
    resolve_workspace_path,
    retry_call,
    run_python,
    run_with_deadline,
    workspace_root,
)
from core.tools.validators import (
    ToolRegistrationError,
    ToolValidationError,
    build_params_model,
    json_schema_for,
    validate_args,
)

__all__ = [
    "RESULT_LIMIT",
    "HitlApprover",
    "ProcessResult",
    "SandboxError",
    "SandboxFailed",
    "SandboxPathError",
    "SandboxTimeout",
    "ToolDanger",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolSpec",
    "ToolValidationError",
    "build_params_model",
    "call_tool",
    "default_registry",
    "get_tool",
    "json_schema_for",
    "list_tools",
    "load_builtin_tools",
    "register_tool",
    "reset_default_registry",
    "resolve_workspace_path",
    "retry_call",
    "run_python",
    "run_with_deadline",
    "validate_args",
    "workspace_root",
]
