"""``GET /models``：注册表内容与「编排层实际调用点」「实际记账口径」不许分叉。

本文件的重点不是状态码，而是三类 anti-drift 断言：

1. **roles 来自代码事实**：:func:`_tier_from_source` 从 ``core/agent/*.py`` 等源文件里
   正则读出每个角色实际传的档位，再与端点报的 ``roles`` 双向比对。
   「改了调用点忘了改注册表」和「改了注册表骗过用例」两个方向都拦得住。
   档位**不写进用例常量**：写死了就只是把注册表抄一遍，不构成证据。
2. **``role_map`` 是 ``items`` 的转置**：注册表里"哪个角色用哪个模型"只有一处真源，
   第二份表只可能带来对不上的那一天。
3. **价目与记账同源**：注册表报的单价必须等于 :meth:`LLMAdapter.estimate_cost`
   真拿来算钱的那个数，也必须等于 ``POST /tasks`` 预估用的那个数（三处都走
   ``resolve_price``）。
4. **不泄漏 Key**：明文与掩码形态都不许出现在响应里。
"""

from __future__ import annotations

import re

import pytest

from api import runner
from api.constants import AUTH_EXEMPT_PATHS, AUTH_EXEMPT_PREFIXES
from api.routes import models as models_route
from api.runner import estimate_cost_cny
from config import PROJECT_ROOT, Settings
from core.llm.adapter import MODEL_PRICES, LLMAdapter
from tests.integration.conftest import TestClient

#: 「角色 → 定义它用哪一档的源文件」。与 ``api/routes/models.py`` 的 ``_ROLE_TIER``
#: 刻意分开写 —— 两份一致才是证据，用例直接 import 那份常量等于自我证明。
#: 档位**不写在这里**：由 :func:`_tier_from_source` 从源码里读出来，
#: 这样「改了调用点忘了改注册表」和「改了注册表骗过用例」两个方向都拦得住。
_ROLE_FILES: dict[str, str] = {
    "planner": "core/agent/planner.py",
    "reviewer": "core/agent/reviewer.py",
    "executor": "core/agent/executor.py",
    # extract 是内置工具，走自己的 adapter
    "extract": "core/tools/builtin/extract.py",
    # judge 不显式传档位：`model or self.settings.llm_model_large` ⇒ 落到 large
    "judge": "evaluation/judge.py",
}

#: 源码里「这个模块用哪一档」的唯一出处；``model=`` 与 ``model or`` 两种写法都认
_TIER_RE = re.compile(r"settings\.(llm_model_(large|small))")


def _tier_from_source(role: str) -> str:
    """从源文件里读出该角色实际用的档位（``large`` / ``small``）。

    要求**恰好一种**取值：同一文件里既出现 large 又出现 small，就说明这个角色的
    归属不再是一句话能说清的，那时该改的是注册表与本用例，而不是放宽断言。
    """
    text = (PROJECT_ROOT / _ROLE_FILES[role]).read_text(encoding="utf-8")
    found = {m.group(2) for m in _TIER_RE.finditer(text)}
    assert found == {"large"} or found == {"small"}, f"{role} 的档位不唯一：{found or '没找到'}"
    return found.pop()


def _use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    """把路由模块看到的 ``get_settings`` 换成给定配置（路由是 ``from config import …``）。"""
    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    return settings


def _get_models(client: TestClient) -> dict:
    response = client.get("/models")
    assert response.status_code == 200, response.text
    return response.json()


def _by_id(body: dict) -> dict[str, dict]:
    return {item["id"]: item for item in body["items"]}


def test_two_tiers_return_two_items_with_roles_and_table_price(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两档配不同模型 ⇒ 两条记录，档位 / 角色 / 官方价都对得上。"""
    _use_settings(
        monkeypatch,
        Settings(
            _env_file=None,
            llm_model_large="deepseek-v4-pro",
            llm_model_small="deepseek-flash",
        ),
    )
    body = _get_models(api_env)
    assert body["total"] == 2
    assert body["default_model"] == "deepseek-v4-pro"

    large = _by_id(body)["deepseek-v4-pro"]
    small = _by_id(body)["deepseek-flash"]
    assert large["tier"] == "large"
    assert small["tier"] == "small"
    assert large["roles"] == ["judge", "planner", "reviewer"]
    assert small["roles"] == ["executor", "extract"]
    # 表内价 ⇒ 明确标来源，不与兜底混成一个数
    assert large["price_source"] == "official_table"
    assert (large["price_in_per_million_cny"], large["price_out_per_million_cny"]) == (
        MODEL_PRICES["deepseek-v4-pro"]
    )
    assert (small["price_in_per_million_cny"], small["price_out_per_million_cny"]) == (
        MODEL_PRICES["deepseek-flash"]
    )


def test_both_tiers_same_model_collapses_to_one_row(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两档同一个 id（本机 ``.env`` 就是这种配置）⇒ 只出一条、roles 合并。

    给用户摆两行一模一样的模型不是信息，是噪声。
    """
    _use_settings(
        monkeypatch,
        Settings(_env_file=None, llm_model_large="deepseek-flash", llm_model_small="deepseek-flash"),
    )
    body = _get_models(api_env)
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == "deepseek-flash"
    assert sorted(item["roles"]) == sorted(_ROLE_FILES)
    # 合并后档位报 large：这是「两档都用它」里更强的那个语义，不为此造第三种取值
    assert item["tier"] == "large"


def test_prefix_match_still_counts_as_table_price(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """带版本后缀的 id（``deepseek-v4-pro-0813``）靠前缀匹配命中表价，不算兜底。"""
    _use_settings(
        monkeypatch,
        Settings(_env_file=None, llm_model_large="deepseek-v4-pro-0813"),
    )
    item = _by_id(_get_models(api_env))["deepseek-v4-pro-0813"]
    assert item["price_source"] == "official_table"
    assert item["price_in_per_million_cny"] == MODEL_PRICES["deepseek-v4-pro"][0]


def test_unknown_model_reports_fallback_saying_so(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表外模型 ⇒ 单价退回 ``Settings`` 兜底值，且 ``price_source`` 如实标成 fallback。"""
    settings = _use_settings(
        monkeypatch,
        Settings(_env_file=None, llm_model_large="某没配过价的模型"),
    )
    item = _by_id(_get_models(api_env))["某没配过价的模型"]
    assert item["price_source"] == "settings_fallback"
    assert item["price_in_per_million_cny"] == settings.llm_price_in
    assert item["price_out_per_million_cny"] == settings.llm_price_out


@pytest.mark.parametrize(
    "model_id",
    ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-pro-0813", "某没配过价的模型"],
)
def test_registry_price_equals_the_number_actually_charged(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch, model_id: str
) -> None:
    """注册表报的价 ≡ ``estimate_cost`` 真拿去算钱的价。

    判据取「100 万 token 的总成本 == 报的进价 + 出价」——两个数只在**同单位**
    （元 / 100 万 token）下才相等，所以这条同时守住了 2026-09-24 那个单位坑。
    """
    settings = _use_settings(monkeypatch, Settings(_env_file=None, llm_model_large=model_id))
    item = _by_id(_get_models(api_env))[model_id]
    adapter = LLMAdapter(settings=settings)
    charged = adapter.estimate_cost(1_000_000, 1_000_000, model=model_id)
    quoted = item["price_in_per_million_cny"] + item["price_out_per_million_cny"]
    assert charged == pytest.approx(quoted, rel=1e-9)


def test_roles_match_the_real_agent_call_sites(    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点报的 ``roles`` ≡ 源码里各角色真实传的档位（双向比，两个方向都拦）。

    这里故意把两档配成两个**只在注册表里当占位用**的 id，让"哪个角色落在哪一行"
    完全由档位决定 —— 于是 ``model-L.roles`` 必须恰好等于源码里传 ``llm_model_large``
    的那批角色，多一个少一个都红。
    """
    _use_settings(monkeypatch, Settings(_env_file=None, llm_model_large="model-L", llm_model_small="model-S"))
    items = _by_id(_get_models(api_env))
    from_source = {role: _tier_from_source(role) for role in _ROLE_FILES}

    assert items["model-L"]["roles"] == sorted(r for r, t in from_source.items() if t == "large")
    assert items["model-S"]["roles"] == sorted(r for r, t in from_source.items() if t == "small")
    # 防"某角色被从表里删掉"：源码里数出来的角色数必须和端点报的总数一致
    assert sum(len(v["roles"]) for v in items.values()) == len(_ROLE_FILES)


def test_role_map_is_the_transpose_of_items(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``role_map`` 必须是 ``items`` 的**转置**，不是第二份手写的表。

    三条各拦一种说谎方式：
    * 值必须是 ``items`` 里出现过的**模型 id** —— 这里刻意用 ``model-L`` / ``model-S``
      当 id，所以"图省事把 ``item.tier`` 塞进去"（值是 ``large`` / ``small``）会直接红。
      两档配成同一个模型时档位会说谎，实测踩过。
    * 键必须恰好是全部角色 —— 少一个键＝有角色没人认领。
    * 每条映射都要在对应那行的 ``roles`` 里能反查到 —— 两份表就可能对不上。
    """
    _use_settings(monkeypatch, Settings(_env_file=None, llm_model_large="model-L", llm_model_small="model-S"))
    body = _get_models(api_env)
    items = _by_id(body)
    role_map = body["role_map"]

    assert set(role_map.values()) <= set(items)
    assert sorted(role_map) == sorted(_ROLE_FILES)
    for role, model_id in role_map.items():
        assert role in items[model_id]["roles"]
    for item in body["items"]:
        for role in item["roles"]:
            assert role_map[role] == item["id"]


def test_role_map_reports_ids_not_tiers_when_tiers_collapse(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两档同一个模型时，``role_map`` 仍报 id：报档位会把「其实只有一个模型」说漏。"""
    _use_settings(
        monkeypatch,
        Settings(_env_file=None, llm_model_large="deepseek-flash", llm_model_small="deepseek-flash"),
    )
    body = _get_models(api_env)
    assert body["total"] == 1
    assert set(body["role_map"].values()) == {"deepseek-flash"}
    assert sorted(body["role_map"]) == sorted(_ROLE_FILES)


def test_submit_estimate_uses_the_registry_price(
    api_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POST /tasks`` 的预估 ≡ 注册表那个价算出来的数（同一个 ``resolve_price``）。

    早先 ``estimate_cost_cny`` 直接读 ``settings.llm_price_in/out``：本机 .env 填
    2.0/8.0 而表内是 2.13/8.52 时，提交前显示的预估和注册表差 6%，实际记账用的是
    表内价 —— 同一屏两个价。这里把兜底单价设成荒谬值，谁还走 ``settings`` 就红。
    """
    settings = _use_settings(
        monkeypatch,
        Settings(
            _env_file=None,
            llm_model_large="deepseek-v4-pro",
            llm_price_in=0.0001,
            llm_price_out=0.0002,
        ),
    )
    # 时段系数在两次调用之间翻转会假红 ⇒ 钉死成高峰
    monkeypatch.setattr(runner, "price_multiplier", lambda: 1.0)

    task, iterations = "锅炉启停流程有哪些步骤", 4
    # token 数按设计文档 §7.7 的粗估公式独立复算（与价无关，不构成自我证明）
    est_in = max(len(task) / 1.6, 1.0) * (2 + iterations * 2)
    est_out = 800.0 * (1 + iterations)
    expected = LLMAdapter(settings=settings).estimate_cost(
        est_in, est_out, model="deepseek-v4-pro", multiplier=1.0
    )
    assert estimate_cost_cny(task, iterations, settings) == pytest.approx(expected, abs=1e-6)

    quoted = _by_id(_get_models(api_env))["deepseek-v4-pro"]
    assert quoted["price_source"] == "official_table"
    # 兜底单价没参与：荒谬值若被用进预估，成本会掉到 1e-4 量级
    assert estimate_cost_cny(task, iterations, settings) > 1e-3


def test_response_carries_no_api_key_in_any_form(api_env: TestClient) -> None:
    """响应体里不许出现 Key（明文或掩码都不行）—— 注册表不是 ``describe()``。"""
    settings = Settings(_env_file=None)
    body = api_env.get("/models")
    raw = body.text
    assert "api_key" not in raw
    assert settings.masked_api_key not in raw or settings.masked_api_key == ""
    for item in body.json()["items"]:
        assert "api_key" not in item


def test_models_endpoint_is_not_auth_exempt() -> None:
    """``/models`` 必须走鉴权（与 ``/tools`` 同一纪律）：模型清单 + 单价不外露。"""
    path = "/models"
    assert path not in AUTH_EXEMPT_PATHS
    assert not any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)
