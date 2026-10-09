"""单工具调用路由：``POST /tools/{tool_name}/invoke``。

HITL 决策表（PRD §P0-7，默认 fail-closed）

=========  ===========  ===================  ============================  ==========================
enable_hitl danger_level approve_high_risk   api_allow_high_risk_override   行为
=========  ===========  ===================  ============================  ==========================
任意       low           —                    —                             直接执行（门禁只管 high）
**false**  **high**      不带 / false         —                             **拒绝**（2026-09-26 改）
**false**  **high**      true                 false（默认）                 **拒绝**（同上）
true       high          不带 / false         —                             拒绝：status=failed
true       high          true                 false（默认）                 拒绝：需开启 override
true       high          true                 true                          放行 + 记 WARNING 审计
=========  ===========  ===================  ============================  ==========================

⚠️ **本路由不看 ``settings.enable_hitl``**（前四行之所以写"任意"）。理由不是保守，是
这条通道上**根本没有人在环**：``ENABLE_HITL=false`` 的含义是"这个部署没接审批流"，
在 API 上它只能推出"没人能批 ⇒ 拒绝"，推不出"无人值守放行"。旧实现把
``enable_hitl and danger == 'high'`` 当条件，等于让"关掉审批流"变成"关掉门禁"——
fail-open。agent 内部调用链（``core/tools/registry.py``）仍按 ``enable_hitl`` 走，
那是产品形态的显式选择，与这条无人值守通道不同源。

**工具执行失败也返回 HTTP 200**（沿用 ``ToolRegistry.call`` 不抛异常的既有契约），
失败信息编码在 ``status`` / ``result`` 里——客户端必须判断 ``status != "success"``
（PRD 已知限制 L6）。

路由刻意写成 ``def``：工具可能跑 30s × 3 次重试的沙箱，必须脱离事件循环。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from api.deps import get_tool_registry
from api.errors import ApiError, ErrorCode
from api.schemas import (
    ErrorResponse,
    ToolHitlInfo,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolListResponse,
    ToolSpecView,
)
from config import get_settings
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["tools"])

#: 默认拒绝理由（fail-closed：API 场景没有人在环，宁可少做不可做错）
_DENY_NO_APPROVAL = (
    "高危工具需人工确认，API 未提供审批通道（传 ?approve_high_risk=true 并开启 "
    "API_ALLOW_HIGH_RISK_OVERRIDE 可放行；把 ENABLE_HITL 设成 false **不会**放行，"
    "这条通道不看那个开关）"
)
_DENY_OVERRIDE_OFF = "已请求放行高危工具，但服务端未开启 API_ALLOW_HIGH_RISK_OVERRIDE，仍按拒绝处理"


def _approving_registry() -> ToolRegistry:
    """构造一个「高危一律放行」的**临时**注册表。

    刻意不修改全局注册表：``get_tool_registry()`` 是进程内单例，
    往它上面挂 approver 等于把「本次放行」变成「永久放行」——
    这与 fail-closed 纪律直接冲突。内置工具都是无状态函数，重建成本可忽略。
    """
    settings = get_settings()
    return load_builtin_tools(
        ToolRegistry(
            settings=settings,
            enable_hitl=True,
            hitl_approver=lambda _name, _args: True,
        )
    )


@router.post(
    "/tools/{tool_name}/invoke",
    response_model=ToolInvokeResponse,
    responses={404: {"model": ErrorResponse, "description": "工具未注册"}},
    summary="单独调用一个内置工具",
)
def invoke_tool(
    tool_name: str,
    body: ToolInvokeRequest,
    approve_high_risk: bool = Query(
        default=False, description="是否放行高危工具（danger_level=high）的本次调用"
    ),
) -> ToolInvokeResponse:
    """调用一个已注册的内置工具。

    Args:
        tool_name: 工具名。**默认注册表里只有三个**：``calculator`` / ``knowledge_search`` /
            ``code_exec``（唯一来源 ``core.tools.builtin.BUILTIN_REGISTRARS``）。
            ``file_io`` / ``web_search`` / ``extract`` 源码仍在仓库里但**已退役、不注册**，
            传它们会命中下面的 404，``detail.message`` 会带上当前可用清单。
        body: 入参对象。
        approve_high_risk: 是否请求放行高危工具。

    Returns:
        调用结果；失败与超时同样返回 200，见 ``status`` 字段。

    Raises:
        ApiError: 404 工具未注册。
    """
    settings = get_settings()
    registry = get_tool_registry()

    try:
        spec = registry.get(tool_name)
    except KeyError as exc:
        raise ApiError(
            ErrorCode.TOOL_NOT_FOUND,
            f"{exc}（可用工具：{', '.join(registry.names()) or '无'}）",
            status=status.HTTP_404_NOT_FOUND,
        ) from exc

    hitl = ToolHitlInfo(required=False, approved=False, reason=None)
    # 刻意不 && settings.enable_hitl：见模块 docstring 的决策表 —— API 这条无人值守通道上，
    # "审批流没启用"只能推出"没人能批"，不能推出"高危直接放行"。
    needs_approval = spec.danger_level == "high"

    if needs_approval:
        hitl.required = True
        if not approve_high_risk:
            return ToolInvokeResponse(
                name=tool_name,
                args=body.args,
                result=_DENY_NO_APPROVAL,
                status="failed",
                duration_ms=0,
                hitl=ToolHitlInfo(required=True, approved=False, reason=_DENY_NO_APPROVAL),
            )
        if not settings.api_allow_high_risk_override:
            return ToolInvokeResponse(
                name=tool_name,
                args=body.args,
                result=_DENY_OVERRIDE_OFF,
                status="failed",
                duration_ms=0,
                hitl=ToolHitlInfo(required=True, approved=False, reason=_DENY_OVERRIDE_OFF),
            )
        # 审计先行：这行 WARNING 是 P1-8 高危审计日志的前身，删了就没有痕迹了
        logger.warning("API 高危工具放行：name=%s args=%s", tool_name, body.args)
        registry = _approving_registry()
        hitl.approved = True

    record = registry.call(tool_name, body.args)
    return ToolInvokeResponse(
        name=tool_name,
        args=body.args,
        result=str(record.get("result", "")),
        status=_normalize_status(str(record.get("status", "failed"))),
        duration_ms=int(record.get("duration_ms", 0)),
        hitl=hitl,
    )


@router.get("/tools", response_model=ToolListResponse, summary="列出全部内置工具规格（只读）")
def get_tools() -> ToolListResponse:
    """列出注册表里的全部内置工具规格。

    前端「内置工具」页用它渲染工具清单（**前端绝不硬编码工具名**），
    再按各工具的 ``parameters`` 动态生成入参表单。

    Returns:
        :class:`~api.schemas.ToolListResponse`：``items`` 为按名称字母序排列的
        工具规格（**刻意不含工具实现回调字段**，见
        :class:`~api.schemas.ToolSpecView`），``total`` 与 ``items`` 同源
        （``len(items)``）。

    Notes:
        * **鉴权**：``/tools`` 不在 ``AUTH_EXEMPT_PATHS`` / ``AUTH_EXEMPT_PREFIXES``
          任何豁免名单里，因此**与本 router 的 ``invoke`` 一样走 Bearer 鉴权**
          （``api/main.py`` 的 ``auth_middleware``）。刻意不加豁免——工具元数据
          不应暴露给未鉴权者。
        * **为什么是 ``def`` 而不是 ``async def``**：本端点只做「读内存注册表 +
          映射成 pydantic 模型」，**零 DB、零网络、零 LLM、无任何可 await 对象**。
          按 ``api/routes/tasks.py`` 顶部的方法选择表，这属于「纯读 → 用 ``def``
          交线程池」，写 ``async def`` 反而会在无 await 对象时阻塞事件循环。
          同理**不触碰** ``asyncio.Queue`` / ``EventBus``。
    """
    registry = get_tool_registry()
    # 显式构造 6 个字段（而非 model_validate(spec.model_dump())）：
    # 显式即自证「响应里没有 func」，也让未来给 ToolSpec 加字段时不会被动泄漏。
    items: list[ToolSpecView] = [
        ToolSpecView(
            name=spec.name,
            description=spec.description,
            danger_level=spec.danger_level,
            timeout=spec.timeout,
            retry=spec.retry,
            parameters=spec.parameters,
        )
        for spec in registry.specs()
    ]
    return ToolListResponse(items=items, total=len(items))


def _normalize_status(raw: str) -> str:
    """把工具返回的 status 收敛到契约里的三个取值。"""
    if raw in {"success", "failed", "timeout"}:
        return raw
    return "failed"


__all__ = ["router"]
