"""多供应商 / 多模型注册表：**模型 id → 打哪个端点、用哪把 Key、多少钱** 的唯一来源。

为什么要有这个模块（R-05 / 换模型方案 §0.3）：「换 LLM」以前在结构上不成立 ——
DeepSeek / 智谱 / 千问是**三套 `base_url` + 三把不同的 Key**，而配置里只有一把
``llm_api_key``（``config.py``）。只在 ``.env`` 里改模型名，会把智谱的模型名发到
DeepSeek 的端点上，症状是 401/404，看不出是"路由"错了。⇒ 路由这件事必须有人持有
事实，而那个事实就是这张表。

三条纪律：

1. **只登记核过价的行**。每条带 ``source``（官网 URL）与 ``checked_on``（核对日期）。
   官网上读不稳的档位**宁可不放**（本次就剔掉了 GLM-4.5：两页读到的档位口径不一致，
   放进去就是一个可能错两位数的价）。表里没有的模型不报错，走 ``settings`` 兜底单价，
   并由 :data:`~core.llm.adapter.PriceSource` 标成 ``settings_fallback`` ⇒
   界面必须写"兜底单价 · 未核价"，不许冒充官方价。
2. **阶梯价如实存成阶梯**。智谱与千问都是**按输入 token 长度分档**计价（同一请求的
   全部 token 落在哪一档就按哪一档结算），而 DeepSeek 是单一价 + 高峰/低谷两档系数。
   把阶梯价压成一个数，长上下文就会被系统性**低估**而看起来完全正常 —— 比"没有价"更糟。
   所以 :class:`PriceTier` 保留边界，:func:`price_for` 按 ``token_in`` 选档。
3. **单位全项目统一为「元 / 100 万 token」**，与 ``MODEL_PRICES``、
   ``Settings.llm_price_in/out``、以及三处消费方的公式一致（单位漂了不报错、只算错 10⁶ 倍，
   这条纪律原来记在 ``core/llm/adapter.py`` 的单价注释里）。

DeepSeek 的三个 id 是从 ``adapter.MODEL_PRICES`` **搬进来**的，不是又抄一份：
:data:`MODEL_PRICES` 现在由本表**反推生成**，所以「表里的价」与「记账用的价」
结构上不可能分叉（用例见 tests/unit/test_llm_providers.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "MODEL_PRICES",
    "PriceTier",
    "ModelSpec",
    "ProviderSpec",
    "known_model_ids",
    "lowest_price",
    "price_for",
    "provider_for",
    "providers",
    "registry",
    "resolve_model",
    "tiers_description",
]


#: 档位边界口径：``max_input_tokens`` = 该档**输入** token 上限（含），``None`` = 不分档 / 最高档。
@dataclass(frozen=True, slots=True)
class PriceTier:
    """一个价格档。阶梯计价时一个模型会有多条。"""

    #: 本档的输入 token 上限（含边界）；``None`` 表示"到此以上"或"不分档"
    max_input_tokens: int | None
    #: 输入单价（元 / 100 万 token）
    price_in: float
    #: 输出单价（元 / 100 万 token）
    price_out: float
    #: 官网那一行的人话口径（例："思考模式输出另计 8 元/百万 token"）。
    #: ⚠️ 有这条note 时，``price_out`` 是**非思考模式**的价 ⇒ 用思考模式会更高，
    #: 记账会偏低。把它写在这里而不是抹平，是为了让页面能如实说出来。
    note: str = ""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """一行 = 一个模型 id 的官方事实。"""

    model_id: str
    display_name: str
    provider: str
    tiers: tuple[PriceTier, ...]
    #: 单价口径说明（"官网列人民币标价"/"美元按固定汇率折算"），页面直接显示
    pricing_basis: str
    #: 官网价格页 URL（来源可核对）
    source: str
    #: 核对日期（价格会变，没有日期的价等于没有来源）
    checked_on: str
    #: 建议档位：给设置面板排序/标注用，不限制可选
    suggested_for: tuple[Literal["large", "small"], ...] = ("large", "small")

    @property
    def tiered(self) -> bool:
        """是否分档计价（决定成本反推能不能判，见 ``api/routes/tasks.py`` 的 PriceCheck）。"""
        return len(self.tiers) > 1


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """一行 = 一家供应商：端点、Key 落在哪个字段、有没有峰谷计价。"""

    provider: str
    display_name: str
    #: 官网 OpenAI 兼容端点（作为"非 .env 那家"的默认值）
    base_url: str
    #: ``Settings`` 上那家的 Key 字段名（多家并存的唯一通道，L-1）
    api_key_field: str
    #: ``Settings`` 上那家的端点覆盖字段名；空串 = 不提供覆盖，只能用默认端点
    base_url_field: str
    #: 这家是否分高峰/低谷计价。只有 DeepSeek 分 ⇒
    #: :func:`~core.llm.pricing.price_multiplier` 的低谷折扣**不许**套到别家头上
    peak_off_peak: bool
    #: 是不是 OpenAI 兼容协议（本项目适配层只会这一种）
    openai_compatible: bool = True


def _t(*rows: tuple[int | None, float, float]) -> tuple[PriceTier, ...]:
    """把 ``(上限, 输入价, 输出价)`` 元组摊成 :class:`PriceTier`（省掉 repetitive 构造）。"""
    return tuple(PriceTier(max_input_tokens=a, price_in=b, price_out=c) for a, b, c in rows)


#: 官网价核对日期。改了价就改这一天，别改数不改日期。
CHECKED_ON = "2026-09-26"

_DEEPSEEK_BASIS = "DeepSeek 官方高峰价（美元）按固定汇率 7.1 折算的人民币；低谷时段再乘 0.5"

#: 供应商表。``deepseek`` 是 .env 里那一家（``llm_provider`` 的默认值），
#: 它的端点与 Key 仍走 ``llm_base_url`` / ``llm_api_key`` 两个老字段 —— 换供应商
#: 不该把已经跑通的人的路由改掉（见 :func:`core.llm.runtime.route`）。
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key_field="llm_api_key",
        base_url_field="",
        peak_off_peak=True,
    ),
    ProviderSpec(
        provider="zhipu",
        display_name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_field="llm_api_key_zhipu",
        base_url_field="llm_base_url_zhipu",
        peak_off_peak=False,
    ),
    ProviderSpec(
        provider="qwen",
        display_name="阿里云千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_field="llm_api_key_qwen",
        base_url_field="llm_base_url_qwen",
        peak_off_peak=False,
    ),
)

#: 模型表（**只放今天核过价的行**；来源见每行的 ``source``）。
REGISTRY: tuple[ModelSpec, ...] = (
    # ---------------------------------------------------------------- DeepSeek --
    ModelSpec(
        model_id="deepseek-flash",
        display_name="DeepSeek-V4.1-Flash",
        provider="deepseek",
        tiers=_t((None, 2.13, 8.52)),  # $0.30 / $1.20（高峰、cache miss）
        pricing_basis=_DEEPSEEK_BASIS,
        source="https://api-docs.deepseek.com/quick_start/pricing",
        checked_on="2026-09-15",
        suggested_for=("large", "small"),
    ),
    ModelSpec(
        model_id="deepseek-v4-flash",
        display_name="DeepSeek-V4.1-Flash（旧别名）",
        provider="deepseek",
        tiers=_t((None, 2.13, 8.52)),
        pricing_basis=_DEEPSEEK_BASIS,
        source="https://api-docs.deepseek.com/quick_start/pricing",
        checked_on="2026-09-15",
        suggested_for=("large", "small"),
    ),
    ModelSpec(
        model_id="deepseek-v4-pro",
        display_name="DeepSeek-V4-Pro-0813",
        provider="deepseek",
        tiers=_t((None, 9.37, 28.12)),  # $1.32 / $3.96（高峰、cache miss）
        pricing_basis=_DEEPSEEK_BASIS,
        source="https://api-docs.deepseek.com/quick_start/pricing",
        checked_on="2026-09-15",
        suggested_for=("large",),
    ),
    # -------------------------------------------------------------------- 智谱 --
    # 来源：https://docs.bigmodel.cn/cn/guide/start/pricing（2026-09-26 查，元/百万 Token）
    # 阶梯按**输入**长度分档；官网另有"批量/缓存命中"折扣，这里一律取**原价**（偏保守）。
    # GLM-4.5 那一行两次读到的档位口径不一致 ⇒ **不放**：宁缺一个模型，不缺一个可能错的价。
    ModelSpec(
        model_id="glm-4.6",
        display_name="GLM-4.6",
        provider="zhipu",
        tiers=_t((32_000, 1.0, 3.0), (128_000, 2.0, 6.0)),
        pricing_basis="智谱官网人民币标价（原价，按输入长度分档）",
        source="https://docs.bigmodel.cn/cn/guide/start/pricing",
        checked_on=CHECKED_ON,
        suggested_for=("large",),
    ),
    ModelSpec(
        model_id="glm-4.5-air",
        display_name="GLM-4.5-Air",
        provider="zhipu",
        tiers=_t((32_000, 0.8, 2.0), (128_000, 1.2, 8.0)),
        pricing_basis="智谱官网人民币标价（原价，按输入长度分档）",
        source="https://docs.bigmodel.cn/cn/guide/start/pricing",
        checked_on=CHECKED_ON,
        suggested_for=("small",),
    ),
    ModelSpec(
        model_id="glm-4-plus",
        display_name="GLM-4-Plus",
        provider="zhipu",
        tiers=_t((None, 5.0, 5.0)),
        pricing_basis="智谱官网人民币标价（原价，不分档）",
        source="https://docs.bigmodel.cn/cn/guide/start/pricing",
        checked_on=CHECKED_ON,
        suggested_for=("large",),
    ),
    ModelSpec(
        model_id="glm-4-air",
        display_name="GLM-4-Air",
        provider="zhipu",
        tiers=_t((None, 0.5, 0.5)),
        pricing_basis="智谱官网人民币标价（原价，不分档）",
        source="https://docs.bigmodel.cn/cn/guide/start/pricing",
        checked_on=CHECKED_ON,
        suggested_for=("small",),
    ),
    # -------------------------------------------------------------------- 千问 --
    # 来源：https://help.aliyun.com/zh/model-studio/model-pricing（2026-09-26 查，
    # 元/百万 Token，**中国内地（北京）**那一档；国际站与其他区价格不同）。
    ModelSpec(
        model_id="qwen-plus",
        display_name="通义千问-Plus",
        provider="qwen",
        tiers=_t((128_000, 0.8, 2.0), (256_000, 2.4, 20.0), (1_000_000, 4.8, 48.0)),
        pricing_basis="千问官网人民币标价（非思考模式、原价；思考模式输出另计更高价）",
        source="https://help.aliyun.com/zh/model-studio/model-pricing",
        checked_on=CHECKED_ON,
        suggested_for=("small",),
    ),
    ModelSpec(
        model_id="qwen3-max",
        display_name="通义千问3-Max",
        provider="qwen",
        tiers=_t((32_000, 2.5, 10.0), (128_000, 4.0, 16.0), (256_000, 7.0, 28.0)),
        pricing_basis="千问官网人民币标价（思考/非思考同价、原价）",
        source="https://help.aliyun.com/zh/model-studio/model-pricing",
        checked_on=CHECKED_ON,
        suggested_for=("large",),
    ),
    ModelSpec(
        model_id="qwen-max",
        display_name="通义千问-Max（旧版，不分档）",
        provider="qwen",
        tiers=_t((None, 2.4, 9.6)),
        pricing_basis="千问官网人民币标价（不分档、原价）",
        source="https://help.aliyun.com/zh/model-studio/model-pricing",
        checked_on=CHECKED_ON,
        suggested_for=("large",),
    ),
)

#: 按 id 建索引（模块级建一次，注册表是常量）。
_BY_ID: dict[str, ModelSpec] = {spec.model_id: spec for spec in REGISTRY}

#: 供应商索引。
_BY_PROVIDER: dict[str, ProviderSpec] = {spec.provider: spec for spec in PROVIDERS}

#: 兼容别名：旧代码里的 ``MODEL_PRICES``（``dict[str, tuple[输入价, 输出价]]``）。
#: **由本表生成，不是第二份数据** —— 取的是每个模型的**最低档**价，与"不知道多长时
#: 按最低档报"这一口径一致（:func:`price_for` 不传 ``token_in`` 时同一条规则）。
#: ⚠️ 阶梯模型的这一份是**下界**：长上下文会更高。真正记账走 :func:`price_for`
#: （``resolve_price`` 会带上 ``token_in``），别拿这张扁表当记账依据。
MODEL_PRICES: dict[str, tuple[float, float]] = {
    spec.model_id: (spec.tiers[0].price_in, spec.tiers[0].price_out) for spec in REGISTRY
}


def registry() -> tuple[ModelSpec, ...]:
    """全部已核价的模型行。"""
    return REGISTRY


def providers() -> tuple[ProviderSpec, ...]:
    """全部已登记的供应商行。"""
    return PROVIDERS


def known_model_ids() -> tuple[str, ...]:
    """白名单（注册表里有的模型 id）。自由填的 id 不在这里，但仍可用 ——
    只是单价会标成 ``settings_fallback``（未核价），**不许**冒充官方价。"""
    return tuple(sorted(_BY_ID))


def provider_spec(name: str) -> ProviderSpec | None:
    """按供应商标识取行；``deepseek`` 之类的大小写差异在这里吸收。"""
    return _BY_PROVIDER.get(str(name).strip().lower())


def resolve_model(name: str) -> ModelSpec | None:
    """按模型 id 找注册表行：精确匹配优先，其次**最长**前缀匹配。

    "最长前缀"这件事必须显式做：表里同时有 ``glm-4-plus`` 与假如有 ``glm-4``，
    普通 ``for`` 的字典顺序会决定命中谁 —— 那是"看运气定价"。
    """
    key = str(name).strip().lower()
    exact = _BY_ID.get(key)
    if exact is not None:
        return exact
    best: ModelSpec | None = None
    for model_id, spec in _BY_ID.items():
        if key.startswith(model_id) and (best is None or len(model_id) > len(best.model_id)):
            best = spec
    return best


def provider_for(name: str) -> ProviderSpec | None:
    """这个模型属于哪家（注册表没有它时返回 ``None`` = 按 .env 那家路由）。"""
    spec = resolve_model(name)
    return None if spec is None else _BY_PROVIDER.get(spec.provider)


def price_for(name: str, token_in: int | None = None) -> tuple[float, float] | None:
    """查官方价并按输入长度选档；表里没有时返回 ``None``。

    Args:
        name: 模型 id。
        token_in: 本次调用的**输入** token 数。两家新供应商都是按输入长度分档，
            所以选档只需要这一个数。

    Returns:
        ``(输入价, 输出价)``（元 / 100 万 token），或 ``None`` 表示未核价。
    """
    spec = resolve_model(name)
    if spec is None:
        return None
    return pick_tier(spec, token_in)


def pick_tier(spec: ModelSpec, token_in: int | None = None) -> tuple[float, float]:
    """按 ``token_in`` 落在哪一档取价；``token_in`` 为 ``None`` 时取**最低档**。

    ⚠️ "不知道多长就按最低档"是**偏乐观**的口径（长上下文会更贵），刻意不藏：
    页面与 ``GET /models`` 会连同 :func:`tiers_description` 一起把整档表摊出来，
    所以"报的这个数是哪一档"始终可核对。预估路径（``estimate_cost_cny``）本来就
    标注"误差 3-5 倍、不得用于计费"。
    """
    if token_in is None:
        first = spec.tiers[0]
        return first.price_in, first.price_out
    for tier in spec.tiers:
        if tier.max_input_tokens is None or token_in <= tier.max_input_tokens:
            return tier.price_in, tier.price_out
    last = spec.tiers[-1]  # 超出最高档：按最高档计（官网没有"再上一档"）
    return last.price_in, last.price_out


def tiers_description(spec: ModelSpec) -> str:
    """把阶梯摊成一句人话，给页面与 422 文案复用（同一来源，不另写一份）。

    例：``1/3 元（输入 ≤32,000 token）· 2/6 元（≤128,000）``；不分档时
    ``2.13/8.52 元``。单位一律"元 / 100 万 token"，与全项目一致。
    """
    parts: list[str] = []
    for tier in spec.tiers:
        label = f"{_num(tier.price_in)}/{_num(tier.price_out)} 元"
        parts.append(label if tier.max_input_tokens is None else f"{label}（输入 ≤{tier.max_input_tokens:,}）")
    return " · ".join(parts)


def _num(value: float) -> str:
    """去掉尾零：``1.0`` 写成 ``1``、``2.13`` 保持两位。给文案用，不影响数值。"""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def masked(secret: object) -> str:
    """Key 脱敏（前 3 后 2 + ``...``）。

    与 ``Settings.masked_api_key`` 同一形状。**永远不要把明文塞进这个函数的返回值**：
    它会经 ``GET /models`` 出现在响应里，而响应会进日志与录屏。
    """
    raw = str(getattr(secret, "get_secret_value", lambda: secret)() or "").strip()
    if not raw:
        return "（未配置）"
    if len(raw) <= 6:
        return "***"
    return f"{raw[:3]}...{raw[-2:]}"
