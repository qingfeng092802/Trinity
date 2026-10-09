"""运行配置面板的唯一数据来源：``GET /config/agent-options``。

存在的理由只有一条：**前端不许写死默认值、枚举和下拉选项**（方案
``docs/run_config_panel_plan_2026-09-26.md`` §2 规矩 3 与 U-1）。
这一屏以前只有一个"最大迭代轮数"，而那个 3 在前端写了**四处**
（``initialValues`` / ``useWatch`` 兜底 / ``normalize(v ?? 3)`` / 提示文案），
后端真正的默认值却是 5（``settings.max_iterations``）—— 两份口径、其中一份还说谎。

四件事各自只有一个来源，本模块只做"读它们并摊平"：

* 默认值 ← :mod:`config`（``max_iterations`` / ``review_threshold`` / ``knowledge_top_k``）
  与工具签名（检索条数默认值同样经 :func:`core.tools.task_context.default_top_k`）；
* 边界 ← ``api.schemas.RUN_CONFIG_LIMITS`` —— **与请求模型的 ``Field(ge/le)`` 同源**，
  所以不会出现"界面允许填 60 秒、后端只收 30 秒"那种 422（方案 P-3）；
* 角色 → 档位 ← ``api.routes.models._ROLE_TIER``，生效模型与来源 ← ``_override_view``
  （刻意 import 这两个私有 helper：复制一份 role→model 的推导就是制造第二个真相，
  而 ``GET /models`` 那边已经有用例 grep 源码核对这张表了）；
* 工具清单 ← **不在这里列**，只给指针 ``source="/tools"``。内置模块里还留着三个
  已退役工具的 ``register()``，任何从常量抄来的清单都会与真实注册结果分叉（方案 P-6）。

⚠️ 与需求不同的一处，写在 ``reviewer_enabled`` 这条 field 里而不是藏在代码注释里：
"快速模式 = 关 Reviewer" 后端**做不到** —— reviewer 是编排图里的固定节点，
把它摘掉之后循环就没有出口条件了（``core/workflow/conditions.py`` 判的就是评审结论）。
所以这一栏 ``accepted=false``，界面把它列进"后端暂不支持"，预设里也不带这个键。
**宁缺勿假**：给一个什么都不控制的开关，比不给更糟（这与 ``GET /models`` 当年
"composer 那颗选了也不进请求体的下拉"是同一个病灶）。

与 ``GET /tools`` / ``GET /models`` 一样**不走鉴权豁免**：默认值、边界与"哪些字段后端还不吃"
都是部署内部事实，不该外露。
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.models import _ROLE_TIER, _override_view
from api.schemas import (
    RUN_CONFIG_LIMITS,
    AgentModelsView,
    AgentOptionField,
    AgentOptionPreset,
    AgentOptionsResponse,
    AgentRoleModelView,
    AgentToolsView,
)
from config import Settings, get_settings
from core.tools.task_context import default_top_k

router = APIRouter(prefix="/config", tags=["config"])

#: 契约版本号。前端认不认识的版本都要能渲染 —— 版本号只用来让"我看的是哪一版契约"
#: 这件事有地方可查，不用来卡渲染（卡渲染等于让后端一次加字段就打挂界面）。
SCHEMA_VERSION = 1

#: 美元 → 人民币。⚠️ 与 ``core/llm/providers.py`` 里 DeepSeek 那三行的折算口径**同一个数**
#: （官方标价是美元、按 1 USD = 7.1 CNY 取高峰价）。全站成本读数都是**元**，
#: 所以预设在这里换算一次，并把原始美元数写进 ``note`` 让界面说得出来源 ——
#: 绝不在前端中间某处偷偷再乘一次（方案 P-9）。
USD_TO_CNY = 7.1

#: 软限制的生效条件。**只在这里写一遍**：``fields[].help`` 与预设的 note 都读它，
#: 界面原样显示。写成两处迟早一份说"超时"、另一份说"节点之间才检查"。
SOFT_LIMIT_HELP = (
    "节点之间才检查：最长可能再等一次完整 LLM 调用（120 秒 × 重试次数）才会中断"
)

#: 成本单位口径（不是价格表，只是"这一列的钱用什么单位"）。
COST_CURRENCY_BASIS = "全站成本一律是人民币元；DeepSeek 的美元标价按 1 USD = 7.1 元折算、取高峰价"


def _usd_to_cny(amount_usd: float) -> float:
    """把需求里给的美元预算换算成元（两位小数 —— 面板上的钱就是这个精度）。"""
    return round(amount_usd * USD_TO_CNY, 2)


#: 三档预设。**值来自这里、由后端发出去**，前端拿到几档渲染几档。
#: 只带后端真吃得下的键（``reviewer_enabled`` 不在其中，理由见模块 docstring）。
_PRESETS: tuple[AgentOptionPreset, ...] = (
    AgentOptionPreset(
        id="fast",
        label="快速模式",
        values={"max_iterations": 2, "max_cost_cny": _usd_to_cny(0.01)},
        note=(
            "迭代 2 轮 · 预算 ¥"
            + f"{_usd_to_cny(0.01):.2f}"
            + "（原需求 $0.01 × 7.1）· 评审开关后端不支持，见下方「后端暂不支持」"
        ),
    ),
    AgentOptionPreset(
        id="standard",
        label="标准模式",
        values={"max_iterations": 3, "max_cost_cny": _usd_to_cny(0.05)},
        note=f"迭代 3 轮 · 预算 ¥{_usd_to_cny(0.05):.2f}（原需求 $0.05 × 7.1）",
    ),
    AgentOptionPreset(
        id="deep",
        label="深度模式",
        values={"max_iterations": 10, "max_cost_cny": _usd_to_cny(0.5)},
        note=(
            f"迭代 10 轮 · 预算 ¥{_usd_to_cny(0.5):.2f}（原需求 $0.50 × 7.1）"
            "· 10 已经是本部署的迭代上界，再深要抬三处界"
        ),
    ),
)


def _fields() -> list[AgentOptionField]:
    """每个键"收不收 / 有没有用"。⚠️ 这两件事是两个独立的布尔，别合并。

    ``unit`` 也在契约里（方案 §2.1）：单位是**后端事实**，不是界面的措辞 ——
    后缀写在前端就等于"前端自己有一张字段表"，那正是这一屏要拆掉的东西。
    """
    return [
        AgentOptionField(
            key="max_iterations",
            label="最大迭代轮数",
            kind="int",
            unit="轮",
            accepted=True,
            enforced=True,
            help="到上限时 reviewer 会把任务收口成 aborted（不是失败），所以它是收口线不是掐断线",
        ),
        AgentOptionField(
            key="review_threshold",
            label="评审通过分",
            kind="int",
            unit="分",
            accepted=True,
            enforced=True,
            help="Reviewer 给的 0-10 分低于这条线就退回 Executor；改它等于改收口标准",
        ),
        AgentOptionField(
            key="max_cost_cny",
            label="最大成本预算",
            kind="money",
            unit="元",
            accepted=True,
            enforced=True,
            help=SOFT_LIMIT_HELP + "；读的是 llm_call 事件累加，不是运行中恒为 0 的 tasks.cost",
        ),
        AgentOptionField(
            key="timeout_s",
            label="任务超时",
            kind="duration",
            unit="秒",
            accepted=True,
            enforced=True,
            help=SOFT_LIMIT_HELP,
        ),
        AgentOptionField(
            key="rag_top_k",
            label="RAG 检索条数上限",
            kind="int",
            unit="条",
            accepted=True,
            enforced=True,
            help="是**上限**：模型自己要得更少时尊重模型，要得更多时夹到这里",
        ),
        AgentOptionField(
            key="use_tools",
            label="允许调用工具",
            kind="bool",
            accepted=True,
            enforced=True,
            help="false 时后端装配低风险安全子集，不是「零工具」",
        ),
        AgentOptionField(
            key="enabled_tools",
            label="工具白名单",
            kind="select",
            accepted=True,
            enforced=True,
            help="优先级高于 use_tools；不传=全量。清单只从 GET /tools 读，界面不抄一份",
        ),
        # R-08：这一条本轮**不得推翻**，也不得改成"看起来支持"。
        AgentOptionField(
            key="reviewer_enabled",
            label="启用评审节点",
            kind="bool",
            accepted=False,
            enforced=False,
            help=(
                "评审节点是编排图固定节点，循环出口判的就是它的结论"
                "（core/workflow/conditions.py）；摘掉它等于换一个收口语义，本轮不支持"
            ),
        ),
    ]


#: composer 上那颗「RAG」快捷开关对应哪个工具名 —— **由后端说**。
#: 前端写死这个字符串就是藏了第二个名字口径（与它刚刚删掉的
#: ``enabled_tools: ['calculator','code_exec']`` 是同一类东西）。
RAG_TOOL_NAME = "knowledge_search"


def _rag_tool() -> str | None:
    """该工具**真的注册上了**才报名字。

    报一个没注册的名字，界面那颗开关就会去白名单里减一个根本不存在的项 ——
    用户看到"RAG 已关"，实际什么也没关。查不到注册表时同样返回 ``None``
    （宁可不给开关，不给一个假的）。
    """
    try:
        from api.deps import get_tool_registry  # noqa: PLC0415 - 避免 import 期拉装配链

        names = {spec.name for spec in get_tool_registry().specs()}
    except Exception:  # noqa: BLE001 - 装配没就绪就当"不知道"，界面据此置灰
        return None
    return RAG_TOOL_NAME if RAG_TOOL_NAME in names else None


def _defaults(settings: Settings) -> dict[str, object]:
    """后端自己的默认值 —— 界面显示"默认 N 轮"时读的就是这里，不许另写一份。

    ⚠️ ``max_cost_cny`` / ``timeout_s`` / ``rag_top_k`` 的默认是 ``None``，
    意思是"不设限 / 不额外限制"，**不是** 0 也不是某个具体数字。
    前端把 ``None`` 当 0 用会得到一个一跑就中断的任务。
    """
    return {
        "max_iterations": settings.max_iterations,
        "review_threshold": settings.review_threshold,
        "rag_top_k": default_top_k(),
        "max_cost_cny": None,
        "timeout_s": None,
        "use_tools": True,
        "enabled_tools": None,
    }


@router.get(
    "/agent-options",
    response_model=AgentOptionsResponse,
    summary="运行配置面板的默认值 / 边界 / 预设 / 字段能力",
)
def get_agent_options() -> AgentOptionsResponse:
    """摊出这一屏需要知道的一切。

    刻意用 ``def`` 而不是 ``async def``：这里全是本地读（settings + 两张表），
    没有 await，放在线程池里跑反而不占事件循环（与 ``GET /tools``、``GET /models`` 同纪律）。
    """
    settings = get_settings()
    override = _override_view(settings)
    return AgentOptionsResponse(
        schema_version=SCHEMA_VERSION,
        defaults=_defaults(settings),
        limits=RUN_CONFIG_LIMITS,
        presets=list(_PRESETS),
        fields=_fields(),
        models=AgentModelsView(
            editable_here=False,
            entry_point="顶栏右上角齿轮 → 模型设置",
            roles=[
                AgentRoleModelView(
                    role=role,
                    tier=tier,
                    model=override.model_large if tier == "large" else override.model_small,
                    source=override.source,
                )
                for role, tier in _ROLE_TIER.items()
            ],
        ),
        tools=AgentToolsView(source="/tools", default_enabled=None, rag_tool=_rag_tool()),
        currency="CNY",
        pricing_basis=COST_CURRENCY_BASIS,
    )


__all__ = ["router"]
