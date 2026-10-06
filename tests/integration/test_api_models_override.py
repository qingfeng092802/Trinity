"""``GET /models`` 的候选清单与 ``POST/DELETE /models/override``（换模型这条链的契约）。

这个文件管四件事，每件都对应一个"看起来正常但会算错钱 / 骗过用户"的失效模式：

* **候选来自响应**（方案 T-7）：前端不许自带模型清单，所以 catalog 的行数、字段与
  "这一行了不公平"的标注（未核价、分档）都得由服务端给全。
* **应用之后显示的就是生效的**（方案 T-1）：``state.items`` 与 ``role_map`` 必须跟着
  变，前端拿响应渲染而不是"自己改完自己显示"。
* **缺 Key 当场拒**（方案 T-2）：放成 200 的话症状会挪到"任务失败：未配置 LLM_API_KEY"，
  用户看不出是设置没生效。
* **Key 一个都不出**（方案 L-1 的只读那一半）：明文、掩码都不许出现在任何响应里 ——
  页面看到的只有"已配 / 未配 + 该配哪个环境变量"。

覆盖层是**模块级进程状态**，所以每个用例前后都要 :func:`runtime.reset_state_for_tests`：
不清的话前一个用例换的模型会漏到后一个用例里，变成"顺序依赖型假绿"。
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from api.constants import AUTH_EXEMPT_PATHS, AUTH_EXEMPT_PREFIXES
from api.routes import health as health_route
from api.routes import models as models_route
from config import Settings
from core.llm import providers, runtime
from core.llm.adapter import LLMAdapter
from tests.integration.conftest import TestClient

#: 用例里用的"可辨认的假 Key"：一旦出现泄漏，grep 这个串就能定位是哪一处
FAKE_DEEPSEEK_KEY = "sk-LEAKCHECK-deepseek-abcdef"
FAKE_ZHIPU_KEY = "zp-LEAKCHECK-zhipu-abcdef"

#: 智谱官网端点（注册表里写死的那一个；用例复述一次是为了"改注册表必须同时改这里"）
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4"
DEEPSEEK_URL = "https://api.deepseek.com/v1"


@pytest.fixture(autouse=True)
def _clean_override_state() -> object:
    """前后各清一次进程内覆盖状态（见模块 docstring 最后一段）。"""
    runtime.reset_state_for_tests()
    yield
    runtime.reset_state_for_tests()


def _settings(**kwargs: object) -> Settings:
    """与本机 ``.env`` 无关的配置对象（没配 .env 的机器也必须能跑这些用例）。"""
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def _both_keys() -> Settings:
    return _settings(
        llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY), llm_api_key_zhipu=SecretStr(FAKE_ZHIPU_KEY)
    )


def _use(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    """把路由模块看到的 ``get_settings`` 换成给定配置（路由是 ``from config import …``）。"""
    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    return settings


def _get(client: TestClient) -> dict:
    response = client.get("/models")
    assert response.status_code == 200, response.text
    return response.json()


class TestCatalogContract:
    """候选清单是响应给的，不是前端抄的。"""

    def test_catalog_行数等于注册表且每行带来源与日期(self, api_env: TestClient) -> None:
        body = _get(api_env)
        catalog = body["catalog"]
        assert len(catalog) == len(providers.registry()), "少一行就是有人在前端补了一份清单"
        for row in catalog:
            assert row["price_source_url"].startswith("https://")
            assert len(row["price_checked_on"]) == len("2026-09-26")
            assert row["tiers"], f"{row['id']} 没有价目却进了候选"
            assert row["key_env_var"] == row["key_env_var"].upper(), row

    def test_阶梯行的_tiered_与_text_一起给(self, api_env: TestClient) -> None:
        rows = {row["id"]: row for row in _get(api_env)["catalog"]}
        assert rows["glm-4.6"]["tiered"] is True
        assert len(rows["glm-4.6"]["tiers"]) == 2
        assert "≤32,000" in rows["glm-4.6"]["tiers_text"]
        assert rows["glm-4-plus"]["tiered"] is False
        assert len(rows["glm-4-plus"]["tiers"]) == 1

    def test_providers_里只有一个家分峰谷(self, api_env: TestClient) -> None:
        views = {row["provider"]: row for row in _get(api_env)["providers"]}
        assert {name for name, row in views.items() if row["peak_off_peak"]} == {"deepseek"}
        assert views["zhipu"]["key_env_var"] == "LLM_API_KEY_ZHIPU"
        assert views["zhipu"]["base_url"] == ZHIPU_URL

    def test_items_的_provider_是按模型路由的不是_env_那一家(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``LLM_PROVIDER=zhipu`` 而强模型是 ``deepseek-flash`` 时，注册表必须说"这条走 DeepSeek"。

        报 ``settings.llm_provider`` 是换供应商之前唯一可能的写法；现在它是**第二个口径**，
        而且是会误导人的那个（用户会以为 deepseek-flash 打到了智谱）。
        """
        _use(
            monkeypatch,
            _settings(
                llm_provider="zhipu",
                llm_api_key=SecretStr(FAKE_ZHIPU_KEY),
                llm_model_large="deepseek-flash",
                llm_model_small="glm-4-air",
            ),
        )
        items = {item["id"]: item for item in _get(api_env)["items"]}
        assert items["deepseek-flash"]["provider"] == "deepseek"
        assert items["deepseek-flash"]["endpoint_source"] == "provider_default"
        assert items["deepseek-flash"]["base_url"] == DEEPSEEK_URL
        assert items["glm-4-air"]["provider"] == "zhipu"
        assert items["glm-4-air"]["endpoint_source"] == "env"


class TestApplyAndRevert:
    """应用 / 回落：显示的就是生效的。"""

    def test_应用后_items_与_role_map_真的跟着变(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _use(monkeypatch, _both_keys())
        before = _get(api_env)
        assert {item["id"] for item in before["items"]} == {"deepseek-flash"}
        assert before["override"]["source"] == "env"

        ack = api_env.post(
            "/models/override",
            json={"model_large": "glm-4.6", "model_small": "glm-4.5-air"},
        )
        assert ack.status_code == 200, ack.text
        body = ack.json()
        assert body["changed"] is True
        assert "重启" in body["message"] and "之后新建" in body["message"], "生效范围必须写在响应里"
        assert settings.llm_model_large == "glm-4.6"
        assert settings.llm_model_small == "glm-4.5-air"
        assert {item["id"] for item in body["state"]["items"]} == {"glm-4.6", "glm-4.5-air"}
        assert body["state"]["role_map"]["planner"] == "glm-4.6"
        assert body["state"]["role_map"]["executor"] == "glm-4.5-air"
        assert body["state"]["override"]["source"] == "override"
        assert body["state"]["override"]["previous_large"] == "deepseek-flash"
        assert body["state"]["override"]["applied_at"], "生效时刻必须报出去，不然「重启回落」没法核对"

    def test_应用后_GET_models_也是新状态(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """面板"重新打开时读到的"必须与刚点完的一致（前端会重取，两处不能各说各话）。"""
        _use(monkeypatch, _both_keys())
        api_env.post("/models/override", json={"model_large": "glm-4-air", "model_small": "glm-4-air"})
        body = _get(api_env)
        assert body["default_model"] == "glm-4-air"
        assert {item["id"] for item in body["items"]} == {"glm-4-air"}
        assert body["items"][0]["roles"] == sorted(
            ["planner", "reviewer", "judge", "executor", "extract"]
        )

    def test_提交与当前相同的值时_not_changed_也不动缓存代号(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """点了"应用"但什么都没改 ⇒ 不该白白作废一次连接池。"""
        _use(monkeypatch, _both_keys())
        generation = runtime.generation()
        ack = api_env.post(
            "/models/override",
            json={"model_large": "deepseek-flash", "model_small": "DeepSeek-Flash"},
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["changed"] is False
        assert runtime.generation() == generation

    def test_回落把档位还给_env_且第二次撤是幂等(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _use(
            monkeypatch,
            _settings(
                llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY),
                llm_api_key_zhipu=SecretStr(FAKE_ZHIPU_KEY),
                llm_model_large="deepseek-v4-pro",
                llm_model_small="deepseek-flash",
            ),
        )
        api_env.post(
            "/models/override", json={"model_large": "glm-4-air", "model_small": "glm-4-air"}
        )
        first = api_env.delete("/models/override")
        assert first.status_code == 200, first.text
        assert first.json()["changed"] is True
        assert (settings.llm_model_large, settings.llm_model_small) == (
            "deepseek-v4-pro",
            "deepseek-flash",
        )
        second = api_env.delete("/models/override")
        assert second.json()["changed"] is False
        assert second.json()["state"]["override"]["source"] == "env"

    def test_大小写与空白在响应里归一化(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, _settings(llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY)))
        ack = api_env.post(
            "/models/override",
            json={"model_large": "  DeepSeek-V4-Pro ", "model_small": "deepseek-flash"},
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["state"]["override"]["model_large"] == "deepseek-v4-pro"


class TestRejections:
    """该拒的必须当场拒，并且说清是哪家。"""

    def test_缺那把_Key_时_422_并点名环境变量(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _use(
            monkeypatch,
            _settings(
                llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY), llm_api_key_zhipu=SecretStr("")
            ),
        )
        response = api_env.post(
            "/models/override", json={"model_large": "glm-4.6", "model_small": "deepseek-flash"}
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_request"
        assert "LLM_API_KEY_ZHIPU" in detail["message"] and "智谱" in detail["message"]
        assert (settings.llm_model_large, settings.llm_model_small) == (
            "deepseek-flash",
            "deepseek-flash",
        ), "被拒的请求必须一个字都没写进去"

    def test_env_那把_Key_缺失时选中走它的模型就被拒(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T-2 的另一半，但**按路由判**：`.env` 那把 Key 空着时，只有"会用到它"的选项才该被拒。

        两个方向都要钉住，因为只写一边都会错：

        * 选 ``deepseek-flash`` 走的是 ``llm_api_key`` ⇒ 必须拒（换了也发不出请求，
          那时"应用成功"是骗人）；
        * 选智谱的模型走 ``LLM_API_KEY_ZHIPU`` ⇒ 必须**放行**，哪怕 .env 那把是空的。
          多家 Key 并存的意义就在这儿：旧写法只看 ``settings.llm_configured``，
          会把这条完全合法的路径一起拒掉。
        """
        _use(
            monkeypatch,
            _settings(
                llm_api_key=SecretStr(""), llm_api_key_zhipu=SecretStr(FAKE_ZHIPU_KEY)
            ),
        )
        blocked = api_env.post(
            "/models/override", json={"model_large": "deepseek-flash", "model_small": "glm-4-air"}
        )
        assert blocked.status_code == 422, blocked.text
        assert "DeepSeek" in blocked.json()["detail"]["message"]

        allowed = api_env.post(
            "/models/override", json={"model_large": "glm-4.6", "model_small": "glm-4-air"}
        )
        assert allowed.status_code == 200, allowed.text
        assert {item["id"] for item in allowed.json()["state"]["items"]} == {"glm-4.6", "glm-4-air"}

    def test_自由填的模型允许但价必须是兜底(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L-3 拍的"白名单 + 允许自由填"：能填，但不许冒充核过价的行。"""
        _use(monkeypatch, _settings(llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY)))
        ack = api_env.post(
            "/models/override",
            json={"model_large": "my-team-model", "model_small": "deepseek-flash"},
        )
        assert ack.status_code == 200, ack.text
        item = {row["id"]: row for row in ack.json()["state"]["items"]}["my-team-model"]
        assert item["known"] is False
        assert item["price_source"] == "settings_fallback"
        assert item["tiers"] == [], "未登记的模型不许有条目 —— 有就是编的"
        assert "兜底" in item["pricing_basis"]
        assert item["id"] not in {row["id"] for row in ack.json()["state"]["catalog"]}, (
            "未核价的模型不能混进候选清单的官方价那一列"
        )

    @pytest.mark.parametrize(
        "bad", ["", "   ", "glm 4.6", "a" * 65], ids=["空", "空白", "含空格", "超长"]
    )
    def test_非法模型名_422(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
        _use(monkeypatch, _settings(llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY)))
        response = api_env.post(
            "/models/override", json={"model_large": bad, "model_small": "deepseek-flash"}
        )
        assert response.status_code == 422, response.text

    def test_缺字段_422(self, api_env: TestClient) -> None:
        response = api_env.post("/models/override", json={"model_large": "glm-4-air"})
        assert response.status_code == 422, response.text


class TestNoKeyLeaks:
    """Key 的明文与掩码都不出场。"""

    def test_get_与_post_的响应里没有明文也没有掩码(self, api_env: TestClient) -> None:
        with pytest.MonkeyPatch.context() as monkeypatch:
            _use(monkeypatch, _both_keys())
            raw_get = api_env.get("/models").text
            raw_post = api_env.post(
                "/models/override", json={"model_large": "glm-4.6", "model_small": "glm-4-air"}
            ).text
        for raw in (raw_get, raw_post):
            for secret in (FAKE_DEEPSEEK_KEY, FAKE_ZHIPU_KEY):
                assert secret not in raw
                # 连"前 3 后 2"的脱敏形状都不许出现：响应里一旦有它，就能用来确认"是不是这把"
                assert providers.masked(SecretStr(secret)) not in raw
            assert "api_key" not in raw, "字段名本身也不许带 api_key —— 与既有守卫同形"

    def test_override_端点不在鉴权豁免名单(self) -> None:
        for path in ("/models", "/models/override"):
            assert path not in AUTH_EXEMPT_PATHS
            assert not any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


class TestAdapterFollowsOverride:
    """换完之后，请求真的打新的那一家（不是只有界面换了）。"""

    def test_换供应商后客户端打的是那家的端点(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _use(monkeypatch, _both_keys())
        adapter = LLMAdapter(settings=settings)
        assert str(adapter._client("deepseek-flash").openai_api_base).rstrip("/") == DEEPSEEK_URL
        runtime.apply_override(settings, model_large="glm-4.6", model_small="glm-4-air")
        client = adapter._client(settings.llm_model_large)
        assert client.model_name == "glm-4.6"
        assert str(client.openai_api_base).rstrip("/") == ZHIPU_URL, (
            "T-1：界面换了而请求还打着 DeepSeek，就是这种「看起来正常」的错"
        )

    def test_代号变了必须作废旧实例(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """这条是"删掉 ``_client`` 里那行作废逻辑必红"的负面对照。

        做法：先在**当前**的缓存键下放一个哨兵实例（模拟"上一个代号下建好的连接池"），
        进一个新代号，再取同一个模型 —— 拿到的必须是新建的对象，不是哨兵。
        只在键里带 ``base_url`` 是不够的：键相同而端点/Key 被换掉时，旧实例会原样复用
        （今天的形状下不会发生，将来把端点做成运行时可写就会 —— 那行删掉本条必红）。
        """
        settings = _use(monkeypatch, _both_keys())
        adapter = LLMAdapter(settings=settings)
        assert adapter._client("glm-4.6") is not None  # 先建一次，确认真实实例存在
        sentinel = object()
        key = f"glm-4.6@{adapter.temperature}@{ZHIPU_URL}"
        adapter._clients[key] = sentinel  # type: ignore[assignment]
        assert adapter._client("glm-4.6") is sentinel, "没进新代号时确实复用同一个实例"
        runtime.apply_override(settings, model_large="glm-4-air", model_small="glm-4-air")
        assert adapter._client("glm-4.6") is not sentinel
        assert len(adapter._clients) == 1, "作废要清整张表，留着旧端点的实例就是留着打错地址的可能"

    def test_缺_Key_的家抛出的错误点名环境变量(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _use(
            monkeypatch,
            _settings(
                llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY), llm_api_key_zhipu=SecretStr("")
            ),
        )
        adapter = LLMAdapter(settings=settings)
        with pytest.raises(Exception, match="LLM_API_KEY_ZHIPU") as caught:
            adapter._client("glm-4.6")
        assert FAKE_DEEPSEEK_KEY not in str(caught.value)


class TestHealthReportsTheRoutedKey:
    """体检胶囊查的是当前档位真正会用的那把 Key。"""

    def test_档位指向没配_Key_的家时体检报_fail_并说清哪家(self, api_env: TestClient) -> None:
        settings = _settings(
            llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY),
            llm_api_key_zhipu=SecretStr(""),
            llm_model_large="glm-4.6",
            llm_model_small="glm-4-air",
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(health_route, "get_settings", lambda: settings)
            text = api_env.get("/health").text
        assert "LLM_API_KEY_ZHIPU" in text, (
            "旧写法只看 llm_api_key，会对着一个必然失败的配置报 ok —— 而这一格正是「能不能跑」的依据"
        )
        assert FAKE_DEEPSEEK_KEY not in text

    def test_配了那把_Key_时体检的_ok_文案报的是路由结果(self, api_env: TestClient) -> None:
        settings = _settings(
            llm_api_key=SecretStr(FAKE_DEEPSEEK_KEY),
            llm_api_key_zhipu=SecretStr(FAKE_ZHIPU_KEY),
            llm_model_large="glm-4.6",
            llm_model_small="glm-4-air",
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(health_route, "get_settings", lambda: settings)
            text = api_env.get("/health").text
        assert "智谱 GLM/glm-4.6" in text and "open.bigmodel.cn" in text
        assert FAKE_ZHIPU_KEY not in text
