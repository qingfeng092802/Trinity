"""``POST /models/key`` 与 ``POST /models/key/validate``：面板收 Key 这条链的契约。

为什么单独一个文件：Key 与"换模型"共用同一个覆盖层（:mod:`core.llm.runtime`），
但它们的**风险方向**完全不同 —— 换模型错了会 422，Key 处理错了会**泄漏**。
所以这个文件里一半的用例判的都是"某个地方不许出现那串值"。

四条硬规矩（每条对应一个已知的失效形状）：

1. **值只进不出**：两个写端点的响应都是整份 ``GET /models`` 视图，里面没有任何字段
   装得下那串明文，也没有脱敏串。回显一次，录屏 / DevTools / react-query 缓存里
   就各多一份副本（方案 L-1 当初就是因为这个才选"页面不收 Key"）。
2. **不进 URL、不进 query、不进日志**：探测请求的 URL 只有端点本身，
   凭据走 ``Authorization`` 头；``caplog`` 里 grep 不到那串值。
3. **重启回落 .env**：覆盖值只在进程内（:data:`core.llm.runtime._key_overrides`），
   本文件所有用例都靠 ``reset_state_for_tests`` 前后各清一次 —— 那条函数漏清这个字典的话，
   第一个用例填的 Key 会让后面的用例在"根本没人配环境变量"的情况下量到已配置。
4. **自建网关那一档点名而不是照收**（U-5）：``LLM_PROVIDER=custom`` 时所有请求都走
   ``.env`` 的端点与 Key，那时填"智谱的 Key"不会生效 ——
   ``providers[].env_channel`` 必须为真、校验必须当场拒，
   否则用户填完看到的是一个纹丝不动的状态点。
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any, Iterator

import pytest
from pydantic import SecretStr

import core.llm.runtime as runtime
from api.routes import models as models_route
from config import Settings
from tests.integration.conftest import TestClient

#: 可辨认的假 Key：泄漏时 grep 这个串就能定位是哪一处。故意写成"看着像 Key 但不是任何真格式"
FAKE_ZHIPU_KEY = "sk-AEKEYCHECK-zhipu-0123456789abcdef"
FAKE_NEW_KEY = "sk-AEKEYCHECK-zhipu-ffffffffffffffff"
FAKE_GATEWAY_KEY = "sk-AEKEYCHECK-gateway-0000"

#: 注册表里智谱的官网端点（用例复述一次是刻意的：改注册表必须同时改这里才会红）
ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4"


@pytest.fixture(autouse=True)
def _clean_runtime_state() -> Iterator[None]:
    """前后各清一次进程内状态（含 Key 覆盖层）。"""
    runtime.reset_state_for_tests()
    yield
    runtime.reset_state_for_tests()


def _settings(**kwargs: Any) -> Settings:
    """与本机 ``.env`` 无关的配置对象（没配任何 Key 的机器也必须能跑这些用例）。"""
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def _no_zhipu_key(**kwargs: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_provider": "deepseek",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_api_key": SecretStr("sk-env-deepseek"),
        "llm_api_key_zhipu": SecretStr(""),
        "llm_api_key_qwen": SecretStr(""),
    }
    base.update(kwargs)
    return _settings(**base)  # type: ignore[arg-type]


def _use(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    """把路由模块看到的 ``get_settings`` 换成给定配置。

    ⚠️ 打的是 ``models_route.get_settings`` 而不是 :func:`config.get_settings`：
    路由是 ``from config import get_settings``，只换 runtime 模块那份的话端点仍然读到
    本机 ``.env`` —— 那样"网关那一档"的用例会**假绿**（第一版就在这里翻过一次）。
    """
    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    return settings


def _zhipu_view(body: dict) -> dict:
    return next(p for p in body["providers"] if p["provider"] == "zhipu")


class _FakeResponse:
    """假的 ``urlopen`` 返回对象（可读 + 能当上下文管理器用）。

    ⚠️ 为什么不是一个挂了属性的 :class:`io.BytesIO`：``with x as y`` 找 ``__enter__`` /
    ``__exit__`` 是查**类型**而不是实例（CPython 的 dunder 隐式查找规则），
    往实例上塞这两个名字不会生效 —— 第一版就在这里抛 TypeError，
    而那正好说明 :func:`runtime.probe_key` 真的走的是 ``with`` 那条路。
    """

    def __init__(self, body: bytes, status: int) -> None:
        self._stream = io.BytesIO(body)
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, *, status: int = 200, payload: Any = None,
                  error: Exception | None = None) -> dict:
    """换一个假的 ``urlopen``，返回它记到的请求信息（URL / 头 / 超时）。

    打 ``urllib.request.urlopen`` 这一层是因为 :func:`runtime.probe_key` 就用它；
    换更上层的话探测逻辑根本没被走到，判据就成了空的。
    """
    seen: dict[str, Any] = {}

    def _fake(request: urllib.request.Request, timeout: float | None = None) -> Any:
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        if error is not None:
            raise error
        body = json.dumps(payload if payload is not None else {"data": [{"id": "m"}]}).encode()
        return _FakeResponse(body, status)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    return seen


class TestApplyKey:
    """``POST /models/key``：填进去、撤回来、以及"值不许出去"。"""

    def test_填进去之后视图跟着变且缓存代号加一(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = _use(monkeypatch, _no_zhipu_key())
        before = _zhipu_view(api_env.get("/models").json())
        assert before["key_configured"] is False and before["own_key_configured"] is False
        gen_before = runtime.generation()

        ack = api_env.post("/models/key", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
        assert ack.status_code == 200, ack.text
        assert ack.json()["changed"] is True
        after = _zhipu_view(ack.json()["state"])
        # 三件事必须一起成立：请求发得出去、这家的字段有值、来源是"本次进程填的"
        assert after["key_configured"] is True
        assert after["own_key_configured"] is True
        assert after["key_source"] == "runtime"
        assert after["env_channel"] is False
        assert runtime.generation() == gen_before + 1, "不作废缓存会『界面说已配、请求还打旧凭据』（T-1）"
        # 首尾空白不是 Key 的一部分：带空格提交应当命中同一个值 ⇒ changed=False
        again = api_env.post("/models/key", json={"provider": "zhipu", "api_key": f"  {FAKE_ZHIPU_KEY}  "})
        assert again.json()["changed"] is False, "重复提交同一个值不该再作废一次连接池"
        assert runtime.generation() == gen_before + 1

    def test_传空串就是撤回_回落到环境变量(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _use(monkeypatch, _no_zhipu_key())
        api_env.post("/models/key", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
        ack = api_env.post("/models/key", json={"provider": "zhipu", "api_key": ""})
        view = _zhipu_view(ack.json()["state"])
        assert ack.json()["changed"] is True
        assert view["key_configured"] is False and view["key_source"] == "none"
        # 没填过再撤一次：幂等、不改代号
        gen = runtime.generation()
        assert api_env.post("/models/key", json={"provider": "zhipu", "api_key": ""}).json()["changed"] is False
        assert runtime.generation() == gen

    @pytest.mark.parametrize(
        "path,body",
        [
            ("/models/key", {"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY}),
            ("/models/key/validate", {"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY}),
        ],
    )
    def test_两个写端点的响应里既无明文也无掩码形态(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch, path: str, body: dict
    ) -> None:
        """收 Key 不等于吐 Key。明文、掩码、字段名 ``api_key`` 三种形态一起判。"""
        _use(monkeypatch, _no_zhipu_key())
        _stub_urlopen(monkeypatch)
        response = api_env.post(path, json=body)
        assert response.status_code == 200, response.text
        raw = response.text
        assert FAKE_ZHIPU_KEY not in raw
        # 掩码形态（前 3 后 2）也不许出现：它足够让"这串对不对"在截图里被认出来
        assert runtime.providers.masked(FAKE_ZHIPU_KEY) not in raw
        assert '"api_key"' not in raw, "响应模型里出现了叫 api_key 的字段"

    def test_未知供应商与控制字符与超长都是422(
        self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use(monkeypatch, _no_zhipu_key())
        cases = {
            "未知供应商": {"provider": "nope", "api_key": "x"},
            "换行（会进 HTTP 头）": {"provider": "zhipu", "api_key": "a\nb"},
            "超长": {"provider": "zhipu", "api_key": "k" * 300},
        }
        for label, body in cases.items():
            assert api_env.post("/models/key", json=body).status_code == 422, label
        # 422 的文案里也不许带上被拒的值
        refused = api_env.post("/models/key", json=cases["超长"])
        assert "kkkk" not in refused.text

    def test_Key_不进日志(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """路由是纯读写的，但任何一层打了 request body 就前功尽弃 —— 这条钉住"没有那层"。"""
        _use(monkeypatch, _no_zhipu_key())
        _stub_urlopen(monkeypatch)
        with caplog.at_level("DEBUG"):
            api_env.post("/models/key", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
            api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
        assert FAKE_ZHIPU_KEY not in caplog.text

    def test_snapshot_只报字段名不报值(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``snapshot()`` 会进日志，所以它给的是环境变量名，不是那串值也不是脱敏串。"""
        settings = _no_zhipu_key()
        runtime.apply_key(settings, provider="zhipu", api_key=FAKE_ZHIPU_KEY)
        snap = runtime.snapshot()
        assert snap["runtime_keys"] == ["llm_api_key_zhipu"]
        assert FAKE_ZHIPU_KEY not in str(snap)
        assert runtime.providers.masked(FAKE_ZHIPU_KEY) not in str(snap)


class TestProbeKey:
    """``POST /models/key/validate``：零 token 的鉴权探测。"""

    def test_探的是那家官网_带_Bearer_超时三秒且_url_不含明文(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _use(monkeypatch, _no_zhipu_key())
        seen = _stub_urlopen(monkeypatch, payload={"data": [{"id": "glm-4.6"}, {"id": "glm-4-air"}]})
        body = api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY}).json()
        assert seen["url"] == f"{ZHIPU_URL}/models"
        assert FAKE_ZHIPU_KEY not in seen["url"], "Key 落进了 URL/query ⇒ 访问日志与浏览器历史各留一份"
        assert seen["auth"] == f"Bearer {FAKE_ZHIPU_KEY}"
        assert seen["timeout"] == 3.0, "拍的是 3 秒：同步等的按钮，5 秒会被当成卡死"
        assert body["ok"] is True and body["model_count"] == 2
        assert body["timeout_s"] == 3.0, "界面要说『3 秒超时』，那个数得从后端读而不是前端写死"

    def test_失败时供应商原话落进_detail(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """三家 401 的说法各不相同，界面编一句"Key 无效"不如把原话搬回来（同 F-1 纪律）。"""
        _use(monkeypatch, _no_zhipu_key())
        err = urllib.error.HTTPError(
            f"{ZHIPU_URL}/models", 401, "Unauthorized", {},  # type: ignore[arg-type]
            io.BytesIO(b'{"error":{"code":"1002","message":"Wrong API key"}}'),
        )
        _stub_urlopen(monkeypatch, error=err)
        body = api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY}).json()
        assert body["ok"] is False and body["http_status"] == 401
        assert "Wrong API key" in body["detail"]
        assert FAKE_ZHIPU_KEY not in json.dumps(body, ensure_ascii=False)

    def test_超时给的是那句可行动的话(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _use(monkeypatch, _no_zhipu_key())
        _stub_urlopen(monkeypatch, error=urllib.error.URLError("timed out"))
        body = api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY}).json()
        assert body["ok"] is False and body["http_status"] is None
        assert "校验超时" in body["detail"] and "base_url" in body["detail"]

    def test_校验不改变任何状态(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """点「校验」不该把没确认过的值悄悄生效 —— 那是另一颗按钮（应用）的职责。"""
        _use(monkeypatch, _no_zhipu_key())
        _stub_urlopen(monkeypatch)
        gen = runtime.generation()
        api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
        assert runtime.generation() == gen
        assert runtime.key_override_fields() == ()
        assert _zhipu_view(api_env.get("/models").json())["key_configured"] is False


class TestGatewayChannel:
    """U-5：自建网关那一档必须点名，不能收一把用不上的 Key。"""

    def _gateway(self) -> Settings:
        return _no_zhipu_key(llm_provider="custom", llm_base_url="https://gateway.invalid/v1",
                             llm_api_key=SecretStr(FAKE_GATEWAY_KEY))

    def test_网关档下三家点亮的都是网关那把(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """这条就是我今天量出来的形状：三家全部 report 网关的字段名。

        ``env_channel`` 就是为它加的：没有这一位，界面上一句「智谱 GLM：已配置」
        其实说的是网关那把 Key —— 一句话两个意思。
        """
        _use(monkeypatch, self._gateway())
        views = {p["provider"]: p for p in api_env.get("/models").json()["providers"]}
        assert views["zhipu"]["key_env_var"] == "LLM_API_KEY"
        assert views["zhipu"]["own_key_env_var"] == "LLM_API_KEY_ZHIPU"
        assert views["zhipu"]["env_channel"] is True
        assert views["zhipu"]["key_configured"] is True, "网关那把在 ⇒ 请求发得出去（这是 key_configured 的意思）"
        assert views["zhipu"]["own_key_configured"] is False, "但智谱自己的字段是空的（这是 own_* 的意思）"

    def test_网关档下校验当场拒_并说清为什么不探(self, api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """不拒的话它会拿智谱的 Key 去探智谱官网然后报"通过"，而真实请求打的是网关。"""
        settings = _use(monkeypatch, self._gateway())
        seen = _stub_urlopen(monkeypatch)
        response = api_env.post("/models/key/validate", json={"provider": "zhipu", "api_key": FAKE_ZHIPU_KEY})
        assert response.status_code == 422, response.text
        # 统一信封是 ``{"detail": {"code","message","request_id"}}``（api/errors.py:103），
        # 拒因写在 ``detail.message`` 而不是顶层 —— 这里读错一层就是"用例假设了不存在的契约"。
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_request"
        assert "不会被用到" in detail["message"]
        assert FAKE_ZHIPU_KEY not in response.text, "被拒的 Key 不许从错误响应里回到浏览器"
        assert "url" not in seen, "既然要拒，就不该先把那趟请求发出去"
        assert settings.llm_provider == "custom"
