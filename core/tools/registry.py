"""统一工具注册表：装饰器注册 + 自动生成 JSON Schema + 沙箱执行 + HITL 门禁。

一次工具调用的完整流水线::

    HITL 门禁 → 参数校验 → 墙钟超时 → 指数退避重试 → 结果字符串化 → ToolCallRecord

任何一环失败都**不会抛异常**，而是转成 ``status="failed"`` / ``"timeout"`` 的记录。
原因很实际：工具失败的现场信息（哪个参数错了、超时了多少秒）只有这里才知道，
让异常穿透到 executor 反而会丢掉这些信息，模型也就没法在下一轮自我修正。

本类同时满足 ``core.agent.base.ToolInvoker`` 协议，可直接注入 ``NodeContext``。
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from config import Settings, get_settings
from core.tools.sandbox import (
    SandboxFailed,
    SandboxPathError,
    SandboxTimeout,
    retry_call,
    run_with_deadline,
)
from core.tools.validators import (
    ToolRegistrationError,
    ToolValidationError,
    build_params_model,
    json_schema_for,
    validate_args,
)
from core.workflow.state import ToolCallRecord

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

#: 危险级别。``high`` 表示会执行代码 / 写文件 / 产生外部副作用。
ToolDanger = Literal["low", "high"]

#: HITL 审批回调：``(工具名, 入参) -> 是否放行``
HitlApprover = Callable[[str, dict[str, Any]], bool]

#: 结果字符串化的长度上限，避免一次工具返回把上下文撑爆
RESULT_LIMIT = 4000


class ToolSpec(BaseModel):
    """单个工具的定义（字段与手册契约一致）。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(description="工具名，模型调用时使用")
    description: str = Field(description="给模型看的一句话说明：做什么、什么时候用")
    parameters: dict[str, Any] = Field(description="入参的 JSON Schema，由函数签名自动生成")
    danger_level: ToolDanger = Field(
        default="low",
        description="危险级别；high 表示会执行代码/写文件，开启 HITL 时需人工确认",
    )
    timeout: int = Field(default=30, ge=0, description="单次调用墙钟超时（秒），0 表示不限制")
    retry: int = Field(
        default=2,
        ge=0,
        le=5,
        description="失败重试次数（指数退避）；超时不重试",
    )
    func: Callable[..., Any] = Field(exclude=True, description="工具实现；不参与序列化")

    def signature_text(self) -> str:
        """把参数渲染成 ``name: type``（可选参数带 ``?``），用于提示词里的工具清单。"""
        properties: dict[str, Any] = self.parameters.get("properties", {})
        required = set(self.parameters.get("required", []))
        parts = []
        for key, spec in properties.items():
            flag = "" if key in required else "?"
            parts.append(f"{key}{flag}: {spec.get('type', 'any')}")
        return ", ".join(parts)


class ToolRegistry:
    """工具注册表。

    Args:
        settings: 全局配置，工具默认超时/重试取自这里。
        enable_hitl: 是否开启高危工具的人工确认；None 表示跟随配置。
        hitl_approver: 审批回调。开启 HITL 但没提供回调时，高危调用按**拒绝**处理
            （fail-closed，宁可少做不可做错）。
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        enable_hitl: bool | None = None,
        hitl_approver: HitlApprover | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.enable_hitl = self.settings.enable_hitl if enable_hitl is None else enable_hitl
        self.hitl_approver = hitl_approver
        self._specs: dict[str, ToolSpec] = {}
        self._params: dict[str, type[BaseModel]] = {}

    # ------------------------------------------------------------- 注册 --
    def register(
        self,
        func: F,
        *,
        name: str | None = None,
        description: str | None = None,
        danger_level: ToolDanger = "low",
        timeout: int | None = None,
        retry: int | None = None,
    ) -> ToolSpec:
        """把一个函数注册成工具。

        ``timeout`` / ``retry`` 为 None 时取全局配置，保证默认值只有一个来源。

        Raises:
            ToolRegistrationError: 工具名重复，或参数无法生成 Schema。
        """
        tool_name = name or str(getattr(func, "__name__", "anonymous_tool"))
        if tool_name in self._specs:
            raise ToolRegistrationError(f"工具名重复：{tool_name}")

        params_model = build_params_model(tool_name, func)
        summary = description or _first_line(inspect.getdoc(func) or "") or f"调用 {tool_name}"
        spec = ToolSpec(
            name=tool_name,
            description=summary,
            parameters=json_schema_for(params_model),
            danger_level=danger_level,
            timeout=self.settings.tool_timeout if timeout is None else timeout,
            retry=self.settings.tool_retry if retry is None else retry,
            func=func,
        )
        self._specs[tool_name] = spec
        self._params[tool_name] = params_model
        logger.debug(
            "已注册工具 %s（danger=%s timeout=%ss retry=%d）",
            tool_name,
            spec.danger_level,
            spec.timeout,
            spec.retry,
        )
        return spec

    def tool(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        danger_level: ToolDanger = "low",
        timeout: int | None = None,
        retry: int | None = None,
    ) -> Callable[[F], F]:
        """装饰器工厂：``@registry.tool("calculator", description="...")``。"""

        def decorator(func: F) -> F:
            self.register(
                func,
                name=name,
                description=description,
                danger_level=danger_level,
                timeout=timeout,
                retry=retry,
            )
            return func

        return decorator

    # ------------------------------------------------------------- 查询 --
    def get(self, name: str) -> ToolSpec:
        """取工具定义。

        Raises:
            KeyError: 工具未注册（错误信息里会列出所有可用工具名）。
        """
        if name not in self._specs:
            available = ", ".join(self.names()) or "无"
            raise KeyError(f"未注册的工具：{name}（可用：{available}）")
        return self._specs[name]

    def has(self, name: str) -> bool:
        """工具是否已注册。"""
        return name in self._specs

    def specs(self) -> list[ToolSpec]:
        """按名称排序返回全部工具定义。

        方法名刻意不叫 ``list``：那会在类作用域里遮蔽内置的 ``list``，
        导致 ``list[str]`` 这类注解解析失败（mypy 会直接报 not valid as a type）。
        """
        return [self._specs[key] for key in sorted(self._specs)]

    def names(self) -> list[str]:
        """全部工具名。"""
        return sorted(self._specs)

    def restrict_to(self, keep: set[str]) -> "ToolRegistry":
        """就地把注册表裁剪成 ``keep`` 白名单（缺陷 A：``use_tools`` 三态语义）。

        只保留 ``keep`` 里的工具，其余从 ``_specs`` / ``_params`` 中移除。
        裁剪后 :meth:`describe` 只暴露白名单工具，模型便只能从白名单里选。

        幂等且安全：``keep`` 里不存在的名字会被忽略（调用方已做合法性校验）；
        连续调用取交集语义。

        Args:
            keep: 要保留的工具名集合。

        Returns:
            ``self``，便于链式调用。
        """
        wanted = {str(name).strip() for name in keep if str(name).strip()}
        for name in list(self._specs):
            if name not in wanted:
                del self._specs[name]
                self._params.pop(name, None)
        logger.debug("工具注册表已裁剪为：%s", ", ".join(self.names()) or "（空）")
        return self

    def describe(self) -> str:
        """渲染成提示词里的工具清单（满足 ``ToolInvoker`` 协议）。"""
        lines: list[str] = []
        for spec in self.specs():
            danger = "（高危，需人工确认）" if spec.danger_level == "high" else ""
            lines.append(f"- {spec.name}({spec.signature_text()}){danger}：{spec.description}")
        return "\n".join(lines)

    # ------------------------------------------------------------- 调用 --
    def call(self, name: str, args: dict[str, Any]) -> ToolCallRecord:
        """执行一次工具调用（满足 ``ToolInvoker`` 协议）。

        Returns:
            :class:`~core.workflow.state.ToolCallRecord`；失败与超时都编码在
            ``status`` / ``result`` 里，不抛异常。
        """
        started = time.perf_counter()
        if not self.has(name):
            return self._record(
                name,
                args,
                f"未注册的工具：{name}（可用：{', '.join(self.names()) or '无'}）",
                "failed",
                started,
            )

        spec = self._specs[name]

        denial = self._hitl_denial(spec, args)
        if denial:
            return self._record(name, args, denial, "failed", started)

        try:
            kwargs = validate_args(self._params[name], args, tool_name=name)
        except ToolValidationError as exc:
            return self._record(name, args, str(exc), "failed", started)

        try:
            value, attempts = retry_call(
                lambda: run_with_deadline(
                    lambda: spec.func(**kwargs), spec.timeout, tool_name=name
                ),
                retry=spec.retry,
            )
        except SandboxTimeout as exc:
            return self._record(name, args, str(exc), "timeout", started)
        except SandboxFailed as exc:
            # 与 timeout 同一待遇：出参就是沙箱 brief 原文（exit_code 那行不被前缀挤走）
            return self._record(name, args, str(exc), "failed", started)
        except SandboxPathError as exc:
            return self._record(name, args, f"路径被沙箱拒绝：{exc}", "failed", started)
        except Exception as exc:  # noqa: BLE001 - 工具边界必须兜住一切，转成失败记录
            logger.warning("工具 %s 执行异常：%s", name, exc)
            return self._record(name, args, f"{type(exc).__name__}: {exc}", "failed", started)

        result = _stringify(value)
        if attempts > 1:
            result = f"{result}\n（前 {attempts - 1} 次失败，重试后成功）"
        return self._record(name, args, result, "success", started)

    # ------------------------------------------------------------- 内部 --
    def _hitl_denial(self, spec: ToolSpec, args: dict[str, Any]) -> str:
        """返回拒绝理由；空字符串表示放行。

        两件事分开（Q5-01，2026-10-02）：

        * **有没有门** —— 高危工具**永远有门**。``enable_hitl=False`` 不再等于放行：
          它只说明"这个进程里没有人被问"，而"没人能批"推不出"可以不批"。
          旧实现第一行是 ``if not (self.enable_hitl and spec.danger_level == "high"): return ""``，
          于是 ``.env`` 里一行 ``ENABLE_HITL=false``（**默认值就是它**）把 fail-closed
          翻成 fail-open —— 编排链路里模型自己选的 ``code_exec`` 不经任何审批直接真跑。
          这与 ``api/routes/tools.py:121-122`` 那条 B-3 的决策表同口径：那条修了
          **HTTP 单工具通道**，编排通道今天才补上，而"同一件事两条通道两个口径"本身就是缺陷。
          顺带修正 ``config.py:110`` 那句 description —— 它一直写着"（fail-closed）"。
        * **要不要问人** —— 只有 ``enable_hitl=True`` 且给了 ``hitl_approver`` 才真的发起询问。
        """
        if spec.danger_level != "high":
            return ""
        approver = self.hitl_approver
        if not self.enable_hitl or approver is None:
            missing = "enable_hitl 未开启" if not self.enable_hitl else "未提供审批回调"
            return (
                f"工具 {spec.name} 属于高危工具，当前无法进行人工确认（{missing}），"
                "按拒绝处理（fail-closed）"
            )
        try:
            approved = bool(approver(spec.name, args))
        except Exception as exc:  # noqa: BLE001 - 审批环节异常也必须 fail-closed
            return f"工具 {spec.name} 的人工确认环节异常，按拒绝处理：{exc}"
        if approved:
            logger.info("高危工具 %s 的人工确认已通过", spec.name)
            return ""
        logger.info("高危工具 %s 被人工拒绝", spec.name)
        return f"工具 {spec.name} 的高危调用被人工拒绝"

    def _record(
        self,
        name: str,
        args: dict[str, Any],
        result: str,
        status: str,
        started: float,
    ) -> ToolCallRecord:
        record: ToolCallRecord = {
            "name": name,
            "args": args,
            "result": result,
            "status": status,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        return record


# --------------------------------------------------------------------------- #
# 全局默认注册表（供 get_tool / list_tools / call_tool 使用）
# --------------------------------------------------------------------------- #
_DEFAULT_REGISTRY = ToolRegistry()


def default_registry() -> ToolRegistry:
    """取全局默认注册表。"""
    return _DEFAULT_REGISTRY


def reset_default_registry(
    *,
    enable_hitl: bool | None = None,
    hitl_approver: HitlApprover | None = None,
) -> ToolRegistry:
    """重建全局注册表（测试隔离用）。"""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = ToolRegistry(enable_hitl=enable_hitl, hitl_approver=hitl_approver)
    return _DEFAULT_REGISTRY


def register_tool(
    name: str | None = None,
    *,
    description: str | None = None,
    danger_level: ToolDanger = "low",
    timeout: int | None = None,
    retry: int | None = None,
) -> Callable[[F], F]:
    """装饰器：把函数注册进全局默认注册表。"""
    return _DEFAULT_REGISTRY.tool(
        name,
        description=description,
        danger_level=danger_level,
        timeout=timeout,
        retry=retry,
    )


def get_tool(name: str) -> ToolSpec:
    """从全局注册表取工具定义。"""
    return _DEFAULT_REGISTRY.get(name)


def list_tools() -> list[ToolSpec]:
    """列出全局注册表里的全部工具。"""
    return _DEFAULT_REGISTRY.specs()


def call_tool(name: str, args: dict[str, Any]) -> ToolCallRecord:
    """调用全局注册表里的工具。"""
    return _DEFAULT_REGISTRY.call(name, args)


def _first_line(text: str) -> str:
    """取 docstring 的第一行非空文本作为默认描述。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _stringify(value: Any, limit: int = RESULT_LIMIT) -> str:
    """把工具返回值统一成字符串（``ToolCallRecord.result`` 是 str）。"""
    if value is None:
        return "（无返回值）"
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, BaseModel):
        return value.model_dump_json()[:limit]
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)[:limit]
        except TypeError:
            return str(value)[:limit]
    return str(value)[:limit]


__all__ = [
    "RESULT_LIMIT",
    "HitlApprover",
    "ToolDanger",
    "ToolRegistry",
    "ToolSpec",
    "call_tool",
    "default_registry",
    "get_tool",
    "list_tools",
    "register_tool",
    "reset_default_registry",
]
