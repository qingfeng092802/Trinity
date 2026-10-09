"""LLM 适配层的纯逻辑单测：不触网、不消耗 token。

覆盖阶段 0 的三条关键链路：
1. ``extract_json`` 对脏输出的容错（裸 JSON / 代码块 / 夹带解释 / 非法输入）；
2. ``to_messages`` 的角色映射；
3. ``count_tokens`` 与 ``estimate_cost`` 的计量口径。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, SecretStr

from config import Settings
from core.llm.adapter import (
    MODEL_PRICES,
    LLMAdapter,
    LLMError,
    LLMJsonError,
    extract_json,
    to_messages,
)


class TestExtractJson:
    """JSON 抽取的四类典型输入。"""

    def test_plain_json_object(self) -> None:
        assert extract_json('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}

    def test_plain_json_array(self) -> None:
        assert extract_json('["步骤一", "步骤二"]') == ["步骤一", "步骤二"]

    def test_fenced_code_block(self) -> None:
        raw = '好的，结果如下：\n```json\n{"steps": ["a", "b"]}\n```\n希望有帮助。'
        assert extract_json(raw) == {"steps": ["a", "b"]}

    def test_json_embedded_in_prose(self) -> None:
        raw = '思考过程...最终答案 {"pass": false, "score": 5, "comment": "缺少验证"} 完毕'
        assert extract_json(raw) == {"pass": False, "score": 5, "comment": "缺少验证"}

    def test_nested_braces_inside_string(self) -> None:
        raw = '{"expr": "if (x) { return {a:1}; }", "ok": true}'
        assert extract_json(raw) == {"expr": "if (x) { return {a:1}; }", "ok": True}

    def test_unparseable_raises_with_raw_text(self) -> None:
        with pytest.raises(LLMJsonError) as excinfo:
            extract_json("这里完全没有 JSON 结构")
        assert excinfo.value.raw_text


class TestToMessages:
    """消息形态归一化。"""

    def test_dict_roles_are_mapped(self) -> None:
        messages = to_messages(
            [
                {"role": "system", "content": "你是规划器"},
                {"role": "user", "content": "拆解任务"},
                {"role": "assistant", "content": "好了"},
            ]
        )
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        assert isinstance(messages[2], AIMessage)

    def test_unknown_role_falls_back_to_user(self) -> None:
        assert isinstance(to_messages([{"role": "tool", "content": "x"}])[0], HumanMessage)

    def test_empty_messages_raise(self) -> None:
        from core.llm.adapter import LLMError

        with pytest.raises(LLMError):
            to_messages([])


class TestMetering:
    """token 估算与成本计算。"""

    def test_count_tokens_positive_for_chinese(self) -> None:
        adapter = LLMAdapter()
        assert adapter.count_tokens("你好，世界") > 0

    def test_count_tokens_grows_with_length(self) -> None:
        adapter = LLMAdapter()
        short = adapter.count_tokens("hello world")
        long = adapter.count_tokens("hello world " * 20)
        assert long > short

    def test_count_tokens_empty_is_zero(self) -> None:
        assert LLMAdapter().count_tokens("") == 0

    def test_estimate_cost_matches_price_table(self) -> None:
        adapter = LLMAdapter()
        # deepseek-flash 官方高峰价 $0.30 / $1.20 每百万 token，按 1 USD = 7.1 CNY 折算
        cost = adapter.estimate_cost(1_000_000, 1_000_000, model="deepseek-flash")
        assert cost == pytest.approx(2.13 + 8.52, abs=1e-9)

    def test_estimate_cost_falls_back_for_unknown_model(self) -> None:
        """表外模型走兜底单价：**期望值写死**，不镜像公式。

        早先这条是 ``expected = settings.llm_price_in + settings.llm_price_out``，
        那是把被测公式照抄一遍 —— 单位错了它照样绿。现在给死数字（元/100 万 token
        口径下 100 万 in + 100 万 out = 2.0 + 8.0 = 10.0 元）。
        """
        adapter = LLMAdapter(settings=Settings(_env_file=None, llm_price_in=2.0, llm_price_out=8.0))
        assert adapter.estimate_cost(1_000_000, 1_000_000, model="某不存在的模型") == pytest.approx(
            10.0, abs=1e-9
        )

    def test_fallback_price_unit_matches_price_table(self) -> None:
        """兜底单价与 ``MODEL_PRICES`` 必须是**同一个单位**（元 / 100 万 token）。

        这条是负控制用例：``config`` 里这两个字段一度写成 ``2.13e-6`` 并标注
        「元/token」，而 ``estimate_cost`` 与 ``api/runner`` 都按「token/1e6 × 单价」算
        ⇒ 没配 ``.env`` 的人会把 100 万 token 估成 1e-5 元（**低估 10⁶ 倍**）。
        本机 ``.env`` 恰好填的是 2.0/8.0，所以线上看不出来 —— 必须直接拿声明的
        默认值测，拿 ``adapter.settings`` 测等于测他机器上的 .env。
        """
        default_in = Settings.model_fields["llm_price_in"].default
        default_out = Settings.model_fields["llm_price_out"].default
        flash_in, flash_out = MODEL_PRICES["deepseek-flash"]
        assert default_in == pytest.approx(flash_in, rel=1e-9)
        assert default_out == pytest.approx(flash_out, rel=1e-9)

    def test_default_price_and_price_table_agree_on_same_official_price(self) -> None:
        """同一官方价走两条路径（表内 / 兜底）必须得到同一个成本。"""
        defaults = Settings(
            _env_file=None,
            llm_price_in=Settings.model_fields["llm_price_in"].default,
            llm_price_out=Settings.model_fields["llm_price_out"].default,
        )
        adapter = LLMAdapter(settings=defaults)
        via_table = adapter.estimate_cost(1_000_000, 1_000_000, model="deepseek-flash")
        via_fallback = adapter.estimate_cost(1_000_000, 1_000_000, model="某不存在的模型")
        assert via_fallback == pytest.approx(via_table, rel=1e-9)

    def test_price_field_descriptions_state_the_unit(self) -> None:
        """字段描述里必须写清单位 —— 这次的坑就埋在「元/token」这四个字里。"""
        for name in ("llm_price_in", "llm_price_out"):
            description = Settings.model_fields[name].description or ""
            assert "100 万" in description, (name, description)
            assert "元/token" not in description, (name, description)

    def test_estimate_cost_scales_linearly(self) -> None:
        adapter = LLMAdapter()
        one = adapter.estimate_cost(1000, 500, model="deepseek-flash")
        two = adapter.estimate_cost(2000, 1000, model="deepseek-flash")
        assert two == pytest.approx(one * 2, rel=1e-9)


class TestConfigContract:
    """配置契约：字段齐全且默认值符合手册约定。"""

    def test_defaults_match_manual(self, settings: Settings) -> None:
        assert settings.max_iterations == 5
        assert settings.review_threshold == 7
        assert settings.tool_timeout == 30
        assert settings.tool_retry == 2
        assert settings.enable_hitl is False

    def test_workspace_dir_is_absolute(self, settings: Settings) -> None:
        assert settings.workspace_dir.is_absolute()

    def test_sqlite_url_becomes_absolute(self, settings: Settings) -> None:
        assert settings.resolved_db_url.startswith("sqlite:///")
        assert settings.db_path is not None
        assert settings.db_path.is_absolute()

    def test_api_key_is_masked(self, settings: Settings) -> None:
        masked = settings.masked_api_key
        assert "sk-" not in masked or "..." in masked


class TestUsageContract:
    """用量对象必须能直接塞进 TraceRecord。"""

    def test_usage_defaults(self) -> None:
        adapter = LLMAdapter()
        payload = adapter.last_usage.as_dict()
        assert set(payload) >= {"model", "token_in", "token_out", "cost", "duration_ms"}

    def test_describe_hides_secret(self) -> None:
        described = LLMAdapter().describe()
        assert "api_key" in described
        assert described["api_key"] != LLMAdapter().settings.llm_api_key.get_secret_value()


class TestFailureModes:
    """失败路径必须给出明确异常，而不是 TypeError / AttributeError。"""

    def test_invoke_without_key_raises_llm_error(self) -> None:
        adapter = LLMAdapter(settings=Settings(llm_api_key=SecretStr("")))
        with pytest.raises(LLMError, match="LLM_API_KEY"):
            adapter.invoke([{"role": "user", "content": "hi"}], temperature=0.7)

    def test_invoke_json_without_key_raises_llm_error(self) -> None:
        adapter = LLMAdapter(settings=Settings(llm_api_key=SecretStr("")))

        class Plan(BaseModel):
            steps: list[str] = []

        with pytest.raises(LLMError):
            adapter.invoke_json([{"role": "user", "content": "拆解任务"}], Plan)

    def test_invoke_json_reports_unparseable_output(self) -> None:
        """抽取彻底失败时抛 LLMJsonError，并带上原始文本便于排查。"""
        with pytest.raises(LLMJsonError) as excinfo:
            extract_json("模型今天不想输出结构化内容")
        assert "结构化内容" in excinfo.value.raw_text
