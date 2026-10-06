"""多供应商注册表（``core/llm/providers.py``）与运行时覆盖层（``runtime.py``）的单元判据。

本文件管的是**换模型这条链的三条命脉**，全部都不走网络、不建 TestClient：

1. **只有一个价目来源**：``adapter.MODEL_PRICES`` 必须是注册表的投影而不是第二份数据
   （R-03 那一轮的同一课：两处数据迟早对不上，而 DeepSeek 三个 id 的数字是历史账的
   基准，一旦被"顺手改一下"就再也对不上了 ⇒ 逐条钉住）。
2. **阶梯价不许被压成一个数**：智谱与千问按**输入长度**分档，选错档不报错、只算错钱。
   选档口径（含"不知道多长时按最低档"这个偏乐观的下界）在这里钉死。
3. **路由是模型 id 的函数，不是 ``llm_provider`` 的函数**：三条路由规则各一条用例，
   其中"自建网关不许被注册表默认端点盖掉"是给已有部署兜底的（改了它就有人升级后连不上）。

覆盖层的两条纪律也在本文件：代号只在**真的改了**的时候进（点了没改不该断连接池），
以及 ``Key`` 的明文不许出现在 ``repr()`` 里（``repr=False`` 那一行删掉本文件必红）。
"""

from __future__ import annotations

import re

import pytest
from pydantic import SecretStr

from config import Settings
from core.llm import providers, runtime
from core.llm.adapter import MODEL_PRICES, resolve_price

#: 历史账的基准：DeepSeek 三个 id 的官方高峰价（元 / 100 万 token）。
#: 数字来自 https://api-docs.deepseek.com/quick_start/pricing ，2026-09-15 核对。
#: ⚠️ 这三对数同时是 ``tests/unit/test_adapter_json.py`` 与成本反推用例的锚点，
#: 改它们必须是"按官网调价 + 换核对日期"这一件事，不能是顺手。
_DEEPSEEK_BASELINE = {
    "deepseek-flash": (2.13, 8.52),
    "deepseek-v4-flash": (2.13, 8.52),
    "deepseek-v4-pro": (9.37, 28.12),
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _settings(**kwargs: object) -> Settings:
    """一个与本机 ``.env`` 无关的配置对象（用例必须能被没有 .env 的机器跑出来）。"""
    return Settings(_env_file=None, **kwargs)


class TestPriceSingleSource:
    """价目只有一个来源。"""

    def test_MODEL_PRICES_是注册表的最低档投影(self) -> None:
        assert set(MODEL_PRICES) == {spec.model_id for spec in providers.registry()}, (
            "扁表与注册表的键集必须一致：多一个少一个都说明有人又抄了一份价目"
        )
        for spec in providers.registry():
            first = spec.tiers[0]
            assert MODEL_PRICES[spec.model_id] == (first.price_in, first.price_out), (
                f"{spec.model_id}：扁表取的是最低档，与 pick_tier(None) 同一口径"
            )

    def test_DeepSeek_那三个价一字未动(self) -> None:
        """历史账的锚点。换供应商这件事不许顺手动到 DeepSeek 的价。"""
        for model_id, expected in _DEEPSEEK_BASELINE.items():
            assert MODEL_PRICES[model_id] == expected, model_id
            for token_in in (None, 1, 1_000_000):
                assert resolve_price(model_id, _settings(), token_in)[:2] == expected, (
                    f"{model_id} 在 token_in={token_in} 下报了别的价 —— DeepSeek 不分档，"
                    "选档逻辑对它必须完全透明"
                )

    def test_每一行都带来源与核对日期(self) -> None:
        for spec in providers.registry():
            assert spec.source.startswith("https://"), spec.model_id
            assert _DATE_RE.match(spec.checked_on), f"{spec.model_id} 的核对日期不是 YYYY-MM-DD"
            assert spec.pricing_basis, f"{spec.model_id} 没写单价口径"
            assert spec.display_name, spec.model_id

    def test_阶梯行必须真的按上限递增(self) -> None:
        """阶梯表若写成乱序，``pick_tier`` 会把长上下文算进低档 —— 且不报错。"""
        for spec in providers.registry():
            limits = [tier.max_input_tokens for tier in spec.tiers]
            if len(spec.tiers) == 1:
                assert limits == [None], f"{spec.model_id}：不分档就不该写上限"
                continue
            assert all(limit is not None for limit in limits[:-1]), (
                f"{spec.model_id}：只有最高一档可以不封顶"
            )
            numbers = [limit for limit in limits if limit is not None]
            assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers), spec.model_id
            prices = [(tier.price_in, tier.price_out) for tier in spec.tiers]
            assert prices == sorted(prices), f"{spec.model_id}：档位更贵必须排在后面"


class TestCrossTableConsistency:
    """两张表互相咬合（注册表 ↔ 供应商 ↔ Settings 字段）。"""

    def test_模型的供应商都在供应商表里(self) -> None:
        names = {spec.provider for spec in providers.providers()}
        for spec in providers.registry():
            assert spec.provider in names, f"{spec.model_id} 指向不存在的一家：{spec.provider}"

    def test_每家至少有一个模型(self) -> None:
        for spec in providers.providers():
            ids = [m.model_id for m in providers.registry() if m.provider == spec.provider]
            assert ids, f"{spec.provider} 一家都没有模型，路由状态没法用样本问出来"

    def test_Key_与端点字段在_Settings_上真的存在(self) -> None:
        """``extra="ignore"`` 会把没登记的 ``LLM_API_KEY_XXX`` 静默丢掉 ⇒ 这一条是防"配了但没生效"。"""
        fields = set(Settings.model_fields)
        for spec in providers.providers():
            assert spec.api_key_field in fields, f"Settings 没有 {spec.api_key_field} 这个字段"
            if spec.base_url_field:
                assert spec.base_url_field in fields, f"Settings 没有 {spec.base_url_field}"

    def test_只有_DeepSeek_那一家分峰谷(self) -> None:
        """低价系数只对这一家成立（官方规则写死了时段）。多一家 True 就是多一处错账。"""
        peak = {spec.provider for spec in providers.providers() if spec.peak_off_peak}
        assert peak == {"deepseek"}


class TestTierSelection:
    """按输入长度选档。"""

    def test_glm46_在_32k_边界上换档(self) -> None:
        assert providers.price_for("glm-4.6", 32_000) == (1.0, 3.0)
        assert providers.price_for("glm-4.6", 32_001) == (2.0, 6.0)
        assert providers.price_for("glm-4.6", 200_000) == (2.0, 6.0), "超出最高一档按最高档计"

    def test_不知道长度时取最低档(self) -> None:
        """这是**下界**口径，页面必须把整档表一起报（``tiers_text``）。"""
        assert providers.price_for("qwen-plus", None) == (0.8, 2.0)
        assert providers.price_for("qwen-plus", 128_000) == (0.8, 2.0)
        assert providers.price_for("qwen-plus", 128_001) == (2.4, 20.0)
        assert providers.price_for("qwen-plus", 300_000) == (4.8, 48.0)

    def test_resolve_price_未登记模型落兜底且标注来源(self) -> None:
        settings = _settings(llm_price_in=1.5, llm_price_out=6.0)
        price_in, price_out, source = resolve_price("my-proxy-model", settings)
        assert (price_in, price_out, source) == (1.5, 6.0, "settings_fallback")
        assert providers.price_for("my-proxy-model") is None

    def test_最长前缀匹配_qwen_plus_latest_归_qwen_plus(self) -> None:
        """官网表里 ``qwen-plus-latest`` 与 ``qwen-plus`` 同价；字典序匹配会撞运气。"""
        spec = providers.resolve_model("qwen-plus-latest")
        assert spec is not None and spec.model_id == "qwen-plus"

    def test_tiers_description_把阶梯摊成人话(self) -> None:
        spec = providers.resolve_model("glm-4.6")
        assert spec is not None
        text = providers.tiers_description(spec)
        assert "1/3" in text and "2/6" in text and "≤32,000" in text, text


class TestRoutingRules:
    """三条路由规则（``runtime.route`` 的 docstring 就是判据表）。"""

    def test_规则1_未登记的模型完全走_env(self) -> None:
        settings = _settings(
            llm_provider="deepseek",
            llm_base_url="https://api.deepseek.com/v1",
            llm_api_key=SecretStr("sk-secretvalue"),
        )
        routing = runtime.route("brand-new-model", settings)
        assert routing.known is False
        assert routing.base_url == "https://api.deepseek.com/v1"
        assert routing.endpoint_source == "env"
        assert routing.api_key_field == "llm_api_key"

    def test_规则2_自建网关不被注册表端点盖掉(self) -> None:
        """已有部署的保命一条：``LLM_PROVIDER=custom`` + 自建 ``LLM_BASE_URL`` 时，
        切到 ``glm-4.6`` 也必须打在自己的网关上 —— 改成官网地址会让原本能用的部署
        当场 401，而报的是"鉴权失败"，没人会怀疑是路由变了。"""
        settings = _settings(
            llm_provider="custom",
            llm_base_url="https://gw.internal/v1",
            llm_api_key=SecretStr("sk-gateway"),
        )
        routing = runtime.route("glm-4.6", settings)
        assert routing.known is True, "模型仍然认得（价还是智谱那一行）"
        assert routing.provider == "zhipu", "属于哪家与打到哪家是两件事，都要报"
        assert routing.base_url == "https://gw.internal/v1"
        assert routing.endpoint_source == "env"
        assert routing.api_key_field == "llm_api_key"

    def test_规则3_env_是_deepseek_时智谱模型打智谱端点与自己的_Key(self) -> None:
        settings = _settings(
            llm_provider="deepseek",
            llm_base_url="https://api.deepseek.com/v1",
            llm_api_key=SecretStr("sk-deep"),
            llm_api_key_zhipu=SecretStr("zp-secret"),
        )
        routing = runtime.route("glm-4.6", settings)
        assert routing.base_url == "https://open.bigmodel.cn/api/paas/v4"
        assert routing.endpoint_source == "provider_default"
        assert routing.api_key_field == "llm_api_key_zhipu"
        assert routing.key_configured is True

    def test_端点覆盖变量优先于注册表默认(self) -> None:
        settings = _settings(
            llm_provider="deepseek",
            llm_api_key=SecretStr("sk-deep"),
            llm_api_key_qwen=SecretStr("qw-secret"),
            llm_base_url_qwen="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/",
        )
        routing = runtime.route("qwen3-max", settings)
        assert routing.base_url.endswith("/compatible-mode/v1"), "尾斜杠必须被吃掉"
        assert routing.endpoint_source == "provider_env"

    def test_缺_Key_的家在路由结果里就是_False(self) -> None:
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"))
        routing = runtime.route("glm-4.6", settings)
        assert routing.key_configured is False
        assert routing.api_key_field == "llm_api_key_zhipu"


class TestEffectiveMultiplier:
    """低谷折扣只对分峰谷的家生效。"""

    def test_智谱与千问拿不到低谷折扣(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"))
        monkeypatch.setattr(runtime, "price_multiplier", lambda: 0.5)
        assert runtime.effective_multiplier("glm-4.6", settings) == 1.0
        assert runtime.effective_multiplier("qwen-plus", settings) == 1.0
        assert runtime.effective_multiplier("deepseek-flash", settings) == 0.5, (
            "DeepSeek 那条路一字不变 —— 这条如果不成立，历史任务的账就变了"
        )

    def test_自建网关的家不猜折扣(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``custom`` 网关无法核实计费规则 ⇒ 恒 1.0（宁可高估）。

        ⚠️ 这是一处**有意的行为变化**：本模块之前，挂自建网关跑 DeepSeek 的部署
        在低谷时段会被无条件打半价。方向上高估是安全的，写清楚比留着不说重要。
        """
        settings = _settings(llm_provider="custom", llm_api_key=SecretStr("sk-gw"))
        monkeypatch.setattr(runtime, "price_multiplier", lambda: 0.5)
        assert runtime.effective_multiplier("glm-4.6", settings) == 1.0
        assert runtime.effective_multiplier("deepseek-flash", settings) == 1.0

    def test_折扣跟着真正打到的端点而不是模型名(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``LLM_PROVIDER=zhipu`` 的部署选 ``deepseek-flash`` ⇒ 请求打 DeepSeek 官网，
        那就该拿 DeepSeek 的峰谷规则；反着写（按模型名一家、按端点另一家）会两头都错。"""
        settings = _settings(
            llm_provider="zhipu",
            llm_api_key=SecretStr("sk-deep"),
            llm_api_key_zhipu=SecretStr("zp-x"),
        )
        monkeypatch.setattr(runtime, "price_multiplier", lambda: 0.5)
        assert runtime.effective_multiplier("deepseek-flash", settings) == 0.5
        assert runtime.effective_multiplier("glm-4-air", settings) == 1.0


class TestOverrideLayer:
    """覆盖层：只改两个档位、只活到重启、Key 不进 repr。"""

    def setup_method(self) -> None:
        runtime.reset_state_for_tests()

    teardown_method = setup_method

    def test_没有_Env_那把_Key_时换谁都被拒(self) -> None:
        """T-2：换到一个发不出请求的配置，症状本来会长成"任务失败"，这里当场 422。"""
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr(""))
        with pytest.raises(runtime.OverrideError, match="DeepSeek"):
            runtime.apply_override(settings, model_large="deepseek-flash", model_small="deepseek-flash")

    def test_缺那把_Key_时被拒并点名环境变量(self) -> None:
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"))
        with pytest.raises(runtime.OverrideError) as caught:
            runtime.apply_override(settings, model_large="glm-4.6", model_small="glm-4-air")
        message = str(caught.value)
        assert "智谱 GLM" in message and "LLM_API_KEY_ZHIPU" in message
        assert "sk-deep" not in message, "错误文案里不许出现任何一家的 Key"
        assert settings.llm_model_large == "deepseek-flash", "被拒的覆盖不能已经写进去了"

    def test_应用只改两个档位不改_provider_与_Key(self) -> None:
        settings = _settings(
            llm_provider="deepseek",
            llm_base_url="https://api.deepseek.com/v1",
            llm_api_key=SecretStr("sk-deep"),
            llm_api_key_zhipu=SecretStr("zp-secret"),
        )
        record = runtime.apply_override(settings, model_large="GLM-4.6", model_small="glm-4-air")
        assert (settings.llm_model_large, settings.llm_model_small) == ("glm-4.6", "glm-4-air")
        assert settings.llm_provider == "deepseek", "provider 不动：路由由模型 id 决定"
        assert settings.llm_base_url == "https://api.deepseek.com/v1", ".env 的端点不动"
        assert record.previous_large == "deepseek-flash"
        assert runtime.current() is not None and runtime.generation() == 1

    def test_回落把两个档位还给_env(self) -> None:
        settings = _settings(
            llm_provider="deepseek",
            llm_api_key=SecretStr("sk-deep"),
            llm_api_key_zhipu=SecretStr("zp-secret"),
            llm_model_large="deepseek-v4-pro",
            llm_model_small="deepseek-flash",
        )
        runtime.apply_override(settings, model_large="glm-4.6", model_small="glm-4-air")
        assert runtime.reset_override(settings) is True
        assert (settings.llm_model_large, settings.llm_model_small) == (
            "deepseek-v4-pro",
            "deepseek-flash",
        )
        assert runtime.current() is None
        assert runtime.reset_override(settings) is False, "第二次撤是幂等，不该报成功"

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "glm 4.6", "glm-4.6\n", "x" * 65, "glm-4;rm -rf"],
        ids=["空", "全空白", "含空格", "含换行", "超长", "分号注入"],
    )
    def test_模型名校验(self, bad: str) -> None:
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"))
        with pytest.raises(runtime.OverrideError):
            runtime.apply_override(settings, model_large=bad, model_small="deepseek-flash")

    def test_Key_明文不出现在_repr_里(self) -> None:
        """``api_key: str = field(repr=False)`` 那一行被删掉，本条必红。

        为什么值得钉：异常信息、日志与调试输出都常常 ``repr()`` 一个对象；
        路由结果里带着明文 Key 是这条链上唯一一处"Key 可能顺口漏出去"的地方。
        """
        settings = _settings(
            llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"),
            llm_api_key_zhipu=SecretStr("zp-verysecret"),
        )
        routing = runtime.route("glm-4.6", settings)
        assert routing.api_key == "zp-verysecret"
        assert "zp-verysecret" not in repr(routing)
        assert "zp-verysecret" not in str(routing)
        assert routing.key_masked.startswith("zp-") and "verysecret" not in routing.key_masked

    def test_snapshot_不含_Key(self) -> None:
        settings = _settings(llm_provider="deepseek", llm_api_key=SecretStr("sk-deep"))
        runtime.apply_override(settings, model_large="deepseek-flash", model_small="deepseek-flash")
        assert "sk-deep" not in str(runtime.snapshot())


class TestMasked:
    def test_脱敏形状(self) -> None:
        assert providers.masked(SecretStr("sk-abcdef123456")) == "sk-...56"
        assert providers.masked(SecretStr("abc")) == "***"
        assert providers.masked(SecretStr("")) == "（未配置）"
        assert providers.masked(None) == "（未配置）"
