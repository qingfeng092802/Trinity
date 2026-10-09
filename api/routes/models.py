"""模型注册表路由：``GET /models``、``POST /models/override``、``DELETE /models/override``、
``POST /models/key``、``POST /models/key/validate``。

存在的理由只有一条：**前端不许硬编码模型清单**。composer 里那颗下拉一度把
选项写在 ``web-react/src/mock/taskMock.ts``（文件名就自称 mock），选完既不进请求体、
后端也没有对应字段 —— 等于给用户一个什么都不控制的控件。本端点是那条链的
真数据源：``settings`` 里到底配了哪两个档位的模型、各自被哪些角色使用、单价多少，
以及（2026-09-26 起）**可以换成哪一些**。

刻意只报「服务端知道的事实」：

* 单价来自 :func:`core.llm.adapter.resolve_price` —— 与 ``estimate_cost`` **同一个函数**，
  所以注册表上显示的价和实际记账的价不会分叉。
* 候选清单来自 :mod:`core.llm.providers` —— 只含**核过价**的行，每行带来源 URL 与核对日期。
  表里没有的模型不是"不能选"（自由填仍然可用），而是"价没核过" ⇒ ``price_source``
  必须是 ``settings_fallback``，界面得写"兜底单价 · 未核价"（方案 T-3）。
* 端点与 Key 状态来自 :func:`core.llm.runtime.route` —— 与 ``LLMAdapter._client``
  用的是同一个函数。这条同源很重要：面板说"会打到智谱"而请求其实打着自建网关，
  比没有面板更糟（方案 T-1）。
* **Key 的值一个都不报**，连脱敏串都不报（``tests/integration/test_api_models.py``
  钉着"明文与掩码形态都不许出现在响应里"）。页面能看到的只有：已配 / 未配、
  从哪配的（``key_source``：环境变量还是本次进程里填的）、该配哪个环境变量。
  2026-09-27 起 ``POST /models/key`` **收** Key（容器里没 ``.env`` 可改，这是这个入口的
  全部理由），但**收进来不等于会吐出去**：两个写端点的响应都是整份 ``GET /models`` 视图，
  里面没有任何一个字段装得下那串值。
* 不报上下文长度、不报能力声明（是否支持 function calling 之类）：仓库里没有一份
  可核对的供应商元数据，写出来就是编的。
* ``roles`` 是编排层调用点的映射（见 :data:`_ROLE_TIER`），
  ``tests/integration/test_api_models.py`` 会 grep 源码核对它 ——
  改了调用点没改这张表就会红。

与 ``GET /tools`` 一样**不走鉴权豁免**：模型 id、单价与"哪一家配了 Key"都不应外露。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from api.errors import ApiError, ErrorCode
from api.schemas import (
    ModelCatalogEntry,
    ModelKeyAck,
    ModelKeyProbeRequest,
    ModelKeyProbeView,
    ModelKeyRequest,
    ModelListResponse,
    ModelOverrideAck,
    ModelOverrideRequest,
    ModelOverrideView,
    ModelSpecView,
    PriceTierView,
    ProviderKeyView,
)
from config import Settings, get_settings
from core.llm import providers, runtime
from core.llm.adapter import resolve_price
from core.llm.pricing import OFF_PEAK_MULTIPLIER

router = APIRouter(prefix="", tags=["models"])

#: 档位取值与 ``ModelSpecView.tier`` 同一集合（就地声明，避免契约层耦合内核类型）
Tier = Literal["large", "small"]

#: 角色 → 档位。**这张表是从调用点抄来的，不是设计意图**：
#: planner / reviewer 显式传 ``llm_model_large``，executor 与 extract 工具显式传
#: ``llm_model_small``，judge 不传 model ⇒ 落到适配层默认值（= ``llm_model_large``）。
_ROLE_TIER: dict[str, Tier] = {
    "planner": "large",
    "reviewer": "large",
    "judge": "large",
    "executor": "small",
    "extract": "small",
}

#: 兜底单价的口径说明。⚠️ 这里**不再**描述某一家供应商的计价规则 ——
#: 峰谷是 DeepSeek 的、阶梯是智谱/千问的，逐条口径写在各自行里
#: （``items[i].pricing_basis`` / ``catalog[i].pricing_basis``，同源生成）。
#: 以前这一句是手写的"DeepSeek 官方高峰价…"，加了别家之后它就开始对半数是假的
#: （与 R-03 那轮 422 文案里写死 ``pdf/md/txt`` 同一类错）。
_FALLBACK_BASIS = (
    "这一句只解释**兜底单价**（未登记模型用的 settings.llm_price_in/out）；"
    "每一家、每一个模型的口径看它自己那行的 pricing_basis"
)

#: 应用成功后的固定提示：生效范围 + 重启回落，两句都必须常驻（方案 L-2）。
_APPLIED_MESSAGE = (
    "已对**之后新建的任务**生效；在途任务仍按原来的模型记账。"
    "这是进程内覆盖，后端重启后回落到 .env"
)

_RESET_MESSAGE = "已回落到 .env 里的那两档；之后新建的任务按 .env 走"


def _tiers_of(model_id: str) -> list[PriceTierView]:
    """注册表里这个模型的阶梯（未登记时为空列表 —— 空就是"没有价目"，不编）。"""
    spec = providers.resolve_model(model_id)
    if spec is None:
        return []
    return [
        PriceTierView(
            max_input_tokens=tier.max_input_tokens,
            price_in_per_million_cny=tier.price_in,
            price_out_per_million_cny=tier.price_out,
            note=tier.note,
        )
        for tier in spec.tiers
    ]


def _model_view(settings: Settings, model_id: str, tier: Tier, roles: list[str]) -> ModelSpecView:
    """把一个「模型 id → 角色」条目摊成响应视图。"""
    price_in, price_out, source = resolve_price(model_id, settings)
    routing = runtime.route(model_id, settings)
    spec = providers.resolve_model(model_id)
    provider = providers.provider_spec(routing.provider)
    return ModelSpecView(
        id=model_id,
        provider=routing.provider,
        provider_display=routing.provider_display,
        tier=tier,
        roles=sorted(roles),
        price_in_per_million_cny=price_in,
        price_out_per_million_cny=price_out,
        price_source=source,
        configured=routing.key_configured,
        base_url=routing.base_url,
        endpoint_source=routing.endpoint_source,
        known=routing.known,
        tiered=bool(spec and spec.tiered),
        tiers=_tiers_of(model_id),
        pricing_basis=(
            spec.pricing_basis
            if spec
            else f"未登记模型 ⇒ 兜底单价 {settings.llm_price_in}/{settings.llm_price_out} 元/百万 token"
        ),
        peak_off_peak=bool(provider and provider.peak_off_peak),
    )


def _catalog_view(settings: Settings) -> list[ModelCatalogEntry]:
    """候选清单：注册表的全部行 + 每行"选了它会发生什么"（Key 状态、端点）。"""
    entries: list[ModelCatalogEntry] = []
    for spec in providers.registry():
        routing = runtime.route(spec.model_id, settings)
        entries.append(
            ModelCatalogEntry(
                id=spec.model_id,
                display_name=spec.display_name,
                provider=spec.provider,
                provider_display=routing.provider_display,
                tiers=_tiers_of(spec.model_id),
                tiered=spec.tiered,
                tiers_text=providers.tiers_description(spec),
                pricing_basis=spec.pricing_basis,
                price_source_url=spec.source,
                price_checked_on=spec.checked_on,
                suggested_for=list(spec.suggested_for),
                key_configured=routing.key_configured,
                base_url=routing.base_url,
                endpoint_source=routing.endpoint_source,
                key_env_var=routing.api_key_field.upper(),
            )
        )
    return entries


def _providers_view(settings: Settings) -> list[ProviderKeyView]:
    """每家的 Key / 端点状态。

    ⚠️ 状态一律用**这一家某个真实模型**去问 :func:`core.llm.runtime.route`，
    不在这里重述一遍路由规则：面板说"智谱已配"而选中它之后请求打不开，
    就是两个口径各说各话。加一家时这里不用改（注册表加一行就够）。
    """
    views: list[ProviderKeyView] = []
    for provider in providers.providers():
        sample = next((s.model_id for s in providers.registry() if s.provider == provider.provider), "")
        if not sample:  # pragma: no cover - 每家至少一个模型，注册表自洽性用例兜住
            continue
        routing = runtime.route(sample, settings)
        # own_* 问的是"这家的字段里到底有没有值"，与 routing 那个"请求真正用哪把"分开答。
        # 自建网关（``LLM_PROVIDER=custom``）时两者会不一致：那时每家报的都是网关那把。
        own_value, _own_source = runtime.key_secret(provider.api_key_field, settings)
        views.append(
            ProviderKeyView(
                provider=provider.provider,
                display_name=provider.display_name,
                model_count=sum(1 for s in providers.registry() if s.provider == provider.provider),
                key_configured=routing.key_configured,
                key_env_var=routing.api_key_field.upper(),
                key_source=routing.key_source,
                own_key_configured=bool(own_value),
                own_key_env_var=provider.api_key_field.upper(),
                env_channel=routing.api_key_field != provider.api_key_field,
                base_url=routing.base_url,
                base_url_env_var=provider.base_url_field.upper(),
                peak_off_peak=provider.peak_off_peak,
            )
        )
    return views


def _override_view(settings: Settings) -> ModelOverrideView:
    """当前生效来源：``.env`` 还是本次覆盖（覆盖时带生效时刻与覆盖前的值）。"""
    record = runtime.current()
    if record is None:
        return ModelOverrideView(
            model_large=settings.llm_model_large,
            model_small=settings.llm_model_small,
            source="env",
            applied_at=None,
            version=runtime.generation(),
            previous_large=settings.llm_model_large,
            previous_small=settings.llm_model_small,
        )
    return ModelOverrideView(
        model_large=record.model_large,
        model_small=record.model_small,
        source="override",
        applied_at=record.applied_at,
        version=record.version,
        previous_large=record.previous_large,
        previous_small=record.previous_small,
    )


def _list_response(settings: Settings) -> ModelListResponse:
    """摊出 ``GET /models`` 的那份状态（写端点的响应也复用这一份，保证同一形状）。"""
    roles_by_model: dict[str, list[str]] = {}
    tier_by_model: dict[str, Tier] = {}
    for role, tier in _ROLE_TIER.items():
        model_id = settings.llm_model_large if tier == "large" else settings.llm_model_small
        roles_by_model.setdefault(model_id, []).append(role)
        # 首次占位即定档位：两档共用一个 id 时报 large，不为此造第三种取值
        tier_by_model.setdefault(model_id, tier)

    items = [
        _model_view(settings, model_id, tier_by_model[model_id], roles_by_model[model_id])
        for model_id in sorted(roles_by_model, key=lambda m: (tier_by_model[m] != "large", m))
    ]
    return ModelListResponse(
        items=items,
        total=len(items),
        # 从 items 反推，不再抄一遍 _ROLE_TIER：两份表就有对不上的一天。
        # 映射到 **模型 id** 而非档位：两档配成同一个 id 时「档位」会说谎。
        role_map={role: item.id for item in items for role in item.roles},
        default_model=settings.llm_model_large,
        pricing_basis=_FALLBACK_BASIS,
        off_peak_multiplier=OFF_PEAK_MULTIPLIER,
        catalog=_catalog_view(settings),
        providers=_providers_view(settings),
        override=_override_view(settings),
        fallback_price_in_per_million_cny=settings.llm_price_in,
        fallback_price_out_per_million_cny=settings.llm_price_out,
    )


@router.get(
    "/models", response_model=ModelListResponse, summary="列出本次部署实际使用的模型与候选清单"
)
def get_models() -> ModelListResponse:
    """列出本次部署实际会调用到的模型、候选清单及其单价口径。

    Returns:
        :class:`~api.schemas.ModelListResponse`：``items`` 按 large → small 排列，
        同档位内按 id 字母序；**两档配成同一个模型时只返回一条**（``roles`` 合并）——
        给用户看「deepseek-flash 和 deepseek-flash」不是信息。
        ``catalog`` 是候选清单（只含核过价的行），``providers`` 是每家的 Key 状态，
        ``override`` 说明这两个档位的值是 .env 来的还是面板改的。

    Notes:
        刻意写成 ``def``：只做「读 settings + 查内存表 + 映射成 pydantic 模型」，
        零 DB、零网络、零 LLM —— 与 ``GET /tools`` 同一类纯读端点，交线程池即可。
    """
    return _list_response(get_settings())


@router.post(
    "/models/override",
    response_model=ModelOverrideAck,
    summary="把两个档位改成候选清单里的模型（仅本进程，不碰 .env，不接收 Key）",
)
def post_override(body: ModelOverrideRequest) -> ModelOverrideAck:
    """应用一次运行时覆盖。

    校验顺序（每条都对应一个已知的失效模式）：

    1. 模型名合法性 —— 由 :func:`core.llm.runtime.apply_override` 里的**唯一一条**
       校验负责，本端点不重述（两处校验就会有"一边放行一边拒绝"的那天）。
    2. **该家的 Key 在不在**（方案 T-2）—— 不在就当场 422 并点名是哪家、该配哪个
       环境变量。若这里放成 200，用户看到的将是"任务失败：未配置 LLM_API_KEY"，
       而不是"设置没生效"：症状挪了位置，最难查。
    3. 与当前值相同时**什么都不做**（``changed=false``）—— 不做覆盖也不动缓存代号。
       每次都作废一次 ``ChatOpenAI`` 缓存的话，"点了没改"会白白断掉连接池。

    Returns:
        :class:`~api.schemas.ModelOverrideAck`：整份新状态（与 ``GET /models`` 同形状）。
        界面显示的必须是这份响应给的，不许前端自改自显示（方案 T-7）。
    """
    settings = get_settings()
    same = (
        body.model_large.strip().lower() == settings.llm_model_large.strip().lower()
        and body.model_small.strip().lower() == settings.llm_model_small.strip().lower()
    )
    if same:
        return ModelOverrideAck(
            changed=False,
            message="与当前生效的两个档位相同，没有改动",
            state=_list_response(settings),
        )
    try:
        runtime.apply_override(
            settings, model_large=body.model_large, model_small=body.model_small
        )
    except runtime.OverrideError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), status=422) from exc
    return ModelOverrideAck(changed=True, message=_APPLIED_MESSAGE, state=_list_response(settings))


@router.delete(
    "/models/override",
    response_model=ModelOverrideAck,
    summary="撤掉运行时覆盖，回落到 .env 里的那两个档位",
)
def delete_override() -> ModelOverrideAck:
    """撤销覆盖（幂等：本来就没覆盖时 ``changed=false``，不报错）。

    有了它，"点错了怎么回"不需要重启后端。仍然不碰 ``.env``（方案 T-6）。
    ⚠️ 这一条**只撤模型名，不撤 Key**：两件事的回落点是分开的
    （Key 用 ``POST /models/key`` 传空串撤），混在一起会出现"我只想换回原来的模型，
    结果把刚填的 Key 也弄没了"。
    """
    settings = get_settings()
    changed = runtime.reset_override(settings)
    return ModelOverrideAck(
        changed=changed,
        message=_RESET_MESSAGE if changed else "本来就没有覆盖在生效，没有改动",
        state=_list_response(settings),
    )


@router.post(
    "/models/key",
    response_model=ModelKeyAck,
    summary="把某家的 API Key 放进本次进程（只在这一次运行里生效，不回显）",
)
def post_key(body: ModelKeyRequest) -> ModelKeyAck:
    """填入 / 撤掉某家供应商的 Key（**内存生效、重启回落 .env、永不写磁盘**）。

    三条硬规矩，每条都对应一个已知的失效形状：

    1. **响应里没有 Key**（连脱敏串都不给）：界面要显示的状态全部来自
       ``state.providers[]`` 的 ``key_configured`` / ``key_source``。回显一次，
       录屏与 DevTools 里就各留一份副本 —— 这正是方案 L-1 当初选"页面不收 Key"的理由，
       现在收下这个值已经是权衡后的决定，不能再多送一处外泄面。
    2. **值只走 POST body**：不进 URL、不进 query（访问日志、浏览器历史、代理日志都会留）。
    3. **改完 ``_generation`` 要加一**：``ChatOpenAI`` 实例里烙着 base_url 与 Key，
       不作废缓存就会出现"界面说已配置、请求还打着旧凭据"（T-1 那个形状）。

    ``api_key`` 传空串 = 撤掉这一家，回落到环境变量那把。
    """
    settings = get_settings()
    try:
        field_name, changed = runtime.apply_key(
            settings, provider=body.provider, api_key=body.api_key
        )
    except runtime.OverrideError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), status=422) from exc
    if not body.api_key:
        message = (
            f"已撤掉本次进程里填的那把，{field_name.upper()} 回落到环境变量"
            if changed
            else "这一家本来就没有面板填的 Key，没有改动"
        )
    else:
        message = (
            f"Key 已放进本次进程（{field_name.upper()}）：只影响**之后新建的任务**，"
            "后端重启后回落到 .env，这一步没有写任何文件"
            if changed
            else "与当前生效的那把相同，没有改动"
        )
    return ModelKeyAck(changed=changed, message=message, state=_list_response(settings))


@router.post(
    "/models/key/validate",
    response_model=ModelKeyProbeView,
    summary="拿这把 Key 问一次 GET {base_url}/models（零 token，超时 3 秒）",
)
def post_key_validate(body: ModelKeyProbeRequest) -> ModelKeyProbeView:
    """校验一把 Key 能不能用 —— **不发 chat completion**。

    为什么用 ``GET /models``：三家都是 OpenAI 兼容端点，这一个请求只验鉴权，
    零 token、毫秒级返回；发一次补全要花用户的钱，而且"配额没了"与"Key 无效"
    会被混成同一句失败。

    ⚠️ 刻意写成 ``def``（不是 ``async def``）：这趟是**阻塞网络 I/O**，
    放事件循环上会在超时窗口里卡住整个 API。
    ⚠️ 也不接受用户填的 Base URL：端点由 :func:`core.llm.runtime.route` 按供应商查表给。
    能填地址就变成"带着这把 Key 往任意内网地址发一次请求"的探针（SSRF），
    而且会造出"面板说打智谱、请求打着别处"（T-1）。要改端点请设
    ``LLM_BASE_URL_<PROVIDER>``。
    """
    settings = get_settings()
    try:
        probe = runtime.probe_key(body.provider, body.api_key, settings)
    except runtime.OverrideError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), status=422) from exc
    return ModelKeyProbeView(
        ok=probe.ok,
        provider=probe.provider,
        base_url=probe.base_url,
        http_status=probe.http_status,
        model_count=probe.model_count,
        detail=probe.detail,
        latency_ms=probe.latency_ms,
        timeout_s=runtime.KEY_PROBE_TIMEOUT_S,
    )


__all__ = ["router"]
