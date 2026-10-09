"""``GET /config/agent-options`` 的契约用例（全部打**真实路径**，不 import 函数自证）。

为什么每条都盯着"同源"而不是"值对不对"：这一屏的全部风险都在**两份口径**——
界面写死一个 3、后端默认是 5；界面允许填 60 秒、后端只收 30 秒；
面板列了工具名而真实注册表里少一个。所以断言的形状是"两处读的是不是同一个东西"。

⚠️ 路由注册有三处（``api/routes/__init__.py`` 的 import 与 ``ROUTERS``、
``api/main.py`` 的 ``include_router``），而 ``ROUTERS`` **不被 main 消费** ⇒
只加前两处会得到一个 404 且不报错的路由。本文件第一条用例就是打真实路径，
盯的正是第三处（方案 §4 P-7）。
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from api.constants import is_auth_exempt
from api.schemas import (
    RUN_CONFIG_LIMITS,
    AgentOptionsResponse,
    TaskRunConfigView,
    TaskSubmitRequest,
)
from tests.integration.conftest import TestClient

PATH = "/config/agent-options"


def _body(client: TestClient) -> dict[str, Any]:
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 路由真的挂上了（P-7）
# --------------------------------------------------------------------------- #
def test_打的是真实路径而不是只_import_自证(api_env: TestClient) -> None:
    body = _body(api_env)
    assert body["schema_version"] == 1
    assert {"defaults", "limits", "presets", "fields", "models", "tools"} <= set(body)


def test_这个端点不走鉴权豁免() -> None:
    """默认值、边界与"哪些字段后端还不吃"都是部署内部事实，不该外露。"""
    assert is_auth_exempt(PATH) is False


# --------------------------------------------------------------------------- #
# 默认值来自后端，不是前端那份 3
# --------------------------------------------------------------------------- #
def test_默认迭代轮数读的是全局配置而不是界面的三(api_env: TestClient) -> None:
    from config import get_settings

    body = _body(api_env)
    assert body["defaults"]["max_iterations"] == get_settings().max_iterations
    # 这条用例的存在理由：前端曾经把 3 写了四处，而后端默认是 5。
    assert body["defaults"]["max_iterations"] != 3 or get_settings().max_iterations == 3


def test_预算与超时的默认是空而不是零(api_env: TestClient) -> None:
    """``None`` = 不设限。前端把 ``None`` 当 0 用会得到一个一跑就中断的任务。"""
    defaults = _body(api_env)["defaults"]
    assert defaults["max_cost_cny"] is None
    assert defaults["timeout_s"] is None
    assert defaults["enabled_tools"] is None, "null=不传时后端全量，不是空名单"


def test_检索默认值与工具签名同源(api_env: TestClient) -> None:
    from core.tools.task_context import default_top_k

    assert _body(api_env)["defaults"]["rag_top_k"] == default_top_k()


# --------------------------------------------------------------------------- #
# 边界与请求模型同源（P-3）
# --------------------------------------------------------------------------- #
def test_limits_与请求模型的界是同一份数字(api_env: TestClient) -> None:
    """不是"看着差不多"：直接把 Field 的 ge/le 抠出来逐字段比。

    写两处就会分叉，而分叉的症状是"界面允许填、后端回 422"或反过来
    "后端收得下、界面给不出那个选项" —— 两种都表现为"配置页在骗人"。
    """
    body = _body(api_env)
    assert body["limits"] == RUN_CONFIG_LIMITS

    fields = TaskSubmitRequest.model_fields
    for key in ("max_iterations", "review_threshold", "max_cost_cny", "timeout_s", "rag_top_k"):
        # 两个约束各自找各自的：metadata 里 Ge 与 Le 是两个对象，
        # 拿第一个带 ge 的再去问 .le 只会拿到 AttributeError。
        meta_ge = next(m.ge for m in fields[key].metadata if hasattr(m, "ge"))
        meta_le = next(m.le for m in fields[key].metadata if hasattr(m, "le"))
        assert body["limits"][key]["min"] == float(meta_ge), key
        assert body["limits"][key]["max"] == float(meta_le), key


def test_界外的值真的被拒(api_env: TestClient) -> None:
    for payload in (
        {"max_iterations": 11},
        {"max_iterations": 0},
        {"review_threshold": 11},
        {"timeout_s": 5},
        {"timeout_s": 3630},
        {"rag_top_k": 0},
        {"rag_top_k": 21},
        {"max_cost_cny": 0},
        {"max_cost_cny": -1},
        {"max_cost_cny": 0.005},
        {"max_cost_cny": 50.01},
    ):
        response = api_env.post("/tasks", json={"task": "边界用例", **payload})
        assert response.status_code == 422, (payload, response.text)


def test_界内的值真的被收(api_env: TestClient) -> None:
    """上下两界各自单独试：只测"中间值能过"会漏掉 off-by-one。

    下界那一格尤其要紧：预算闸门的用例把上限**取在 ``max_cost_cny`` 的下限上**
    （见 ``test_api_run_config.py``），下界被悄悄抬高会让那条用例一路跑到 ``done``
    而不报错 —— 一条"什么也没测到"的绿。
    """
    for payload in (
        {"max_iterations": 10, "review_threshold": 9, "max_cost_cny": 50.0,
         "timeout_s": 3600, "rag_top_k": 20},
        {"max_iterations": 1, "review_threshold": 0, "max_cost_cny": 0.01,
         "timeout_s": 30, "rag_top_k": 1},
    ):
        response = api_env.post("/tasks", json={"task": "界内", **payload})
        assert response.status_code == 201, (payload, response.text)
        echo = response.json()["run_config"]
        for key, value in payload.items():
            assert echo[key] == value, (key, value, echo)
    assert echo["review_threshold"] == 0, "0 分线是合法值，回执不能把它当成『没填』丢掉"


# --------------------------------------------------------------------------- #
# 预设：来自后端、换算看得见、只带吃得下的键
# --------------------------------------------------------------------------- #
def test_三档预设都在响应里且带得出换算(api_env: TestClient) -> None:
    presets = {p["id"]: p for p in _body(api_env)["presets"]}
    assert set(presets) == {"fast", "standard", "deep"}
    for preset in presets.values():
        # 全站成本口径是**元**，而需求给的是美元 ⇒ 换算必须写在明面上（P-9）
        assert "7.1" in (preset.get("note") or ""), preset
    assert presets["fast"]["values"]["max_iterations"] == 2
    assert presets["deep"]["values"]["max_iterations"] == 10


def test_预设的美元换算对得上且没有偷偷再乘一次(api_env: TestClient) -> None:
    from api.routes.config import USD_TO_CNY, _usd_to_cny

    assert _usd_to_cny(0.01) == round(0.01 * USD_TO_CNY, 2)
    presets = {p["id"]: p for p in _body(api_env)["presets"]}
    assert presets["standard"]["values"]["max_cost_cny"] == _usd_to_cny(0.05)


def test_预设只带后端真吃得下的键(api_env: TestClient) -> None:
    """``reviewer_enabled`` 不许混进预设的 values —— 那会造出一个什么都不控制的开关。"""
    accepted = {f["key"] for f in _body(api_env)["fields"] if f["accepted"]}
    for preset in _body(api_env)["presets"]:
        assert set(preset["values"]) <= accepted, preset
        assert set(preset["values"]) <= set(RUN_CONFIG_LIMITS) | {"use_tools", "enabled_tools"}


def test_预设的值本身在limits之内(api_env: TestClient) -> None:
    """后端自己发的东西先过自己给的界 —— 否则界面一打开就报"超出范围"。"""
    limits = _body(api_env)["limits"]
    for preset in _body(api_env)["presets"]:
        for key, value in preset["values"].items():
            if key in limits:
                assert limits[key]["min"] <= value <= limits[key]["max"], (preset["id"], key)


# --------------------------------------------------------------------------- #
# fields：accepted / enforced 是两个独立布尔
# --------------------------------------------------------------------------- #
def test_每个_accepted_的键都是请求模型真有的(api_env: TestClient) -> None:
    """这条是 P-1 的正面对照。

    请求模型的 ``extra`` 策略是忽略未知键 ⇒ 前端照着 fields 发一个后端没有的键，
    **不会报错、会被静默丢掉**。所以"后端收不收"必须以 ``TaskSubmitRequest`` 的
    字段表为准，而不是以谁记得住为准。
    """
    accepted = {f["key"] for f in _body(api_env)["fields"] if f["accepted"]}
    assert accepted <= set(TaskSubmitRequest.model_fields), accepted - set(
        TaskSubmitRequest.model_fields
    )


def test_评审开关明说不支持而不是悄悄不给(api_env: TestClient) -> None:
    """需求里的"快速模式关 Reviewer"后端做不到 —— 界面要拿得到这句话才能显示出来。

    ``label`` 与 ``help`` 的措辞按契约要点 6 逐字核对：界面是**原样显示**这两段的，
    后端这里改口，面板上那句话就跟着变 —— 所以这里必须是承诺的那句，
    不能只写成"含'评审'两个字"。
    """
    field = next(f for f in _body(api_env)["fields"] if f["key"] == "reviewer_enabled")
    assert field["accepted"] is False and field["enforced"] is False
    assert field["label"] == "启用评审节点", field
    assert field["kind"] == "bool", field
    assert "本轮不支持" in field["help"], field
    assert "收口" in field["help"], "得说清为什么不支持（循环出口判的就是它的结论），不然像敷衍"


def test_软限制的帮助文本带着生效条件(api_env: TestClient) -> None:
    """P-4：说成硬限制就是界面在骗人。"""
    fields = {f["key"]: f for f in _body(api_env)["fields"]}
    for key in ("max_cost_cny", "timeout_s"):
        assert fields[key]["accepted"] and fields[key]["enforced"]
        assert "节点之间" in fields[key]["help"], key


def test_评审通过线声明为可配且真被执行(api_env: TestClient) -> None:
    """``review_threshold`` 早就在请求模型里，但一直到本轮才被摊进 ``fields``。

    ``enforced`` 不能凭印象写 True：它的真凭据是"这个值一路传到了编排配置"，
    所以这里连那条链路一起核（``QueueItem`` → ``build_runner`` 的 ``WorkflowConfig``）。
    """
    field = next(f for f in _body(api_env)["fields"] if f["key"] == "review_threshold")
    assert field["accepted"] is True and field["enforced"] is True, field
    assert field["key"] in TaskRunConfigView.model_fields, "声明可配却不回执 = 界面无法核对"

    import api.runner as runner_mod

    src = inspect.getsource(runner_mod)
    assert "item.review_threshold" in src, (
        "enforced=True 的依据是这个值真的传进了编排配置；"
        "哪天那一行被删了，这条 field 必须同时改成 enforced=False"
    )


def test_数值型字段都带单位而不是让界面自己猜(api_env: TestClient) -> None:
    """``unit`` 在契约里（方案 §2.1）：单位是**后端事实**。

    界面自己写"轮 / 元 / 秒 / 条"就是藏了第二张字段表 —— 与这一屏刚刚删掉的那四处
    ``3`` 是同一个病：一份口径写了两个地方，其中一个迟早会说谎。
    """
    for f in _body(api_env)["fields"]:
        if f["kind"] in ("int", "money", "duration"):
            assert isinstance(f.get("unit"), str) and f["unit"], f["key"]
        else:
            assert f.get("unit") is None, (f["key"], "bool / select 没有单位")


def test_声明可配的键回执里全都有(api_env: TestClient) -> None:
    """回执是"服务端真收下了"的唯一证据 ⇒ 界面要核对的每个键都得在那儿。

    少一个键**不会崩**：``echoDiffLines`` 只会报"回执里没有这一项 ⇒ 服务端未确认收下"，
    而那是一句说谎的告警 —— 后端其实收了，只是没往这儿报。所以这里按字段表逐一把关，
    而不是等界面上冒出一条误导性的警告再回来补。
    """
    accepted = {f["key"] for f in _body(api_env)["fields"] if f["accepted"]}
    echoed = set(TaskRunConfigView.model_fields)
    assert accepted <= echoed, accepted - echoed


# --------------------------------------------------------------------------- #
# 模型区只读、工具区只给指针
# --------------------------------------------------------------------------- #
def test_模型区不可编辑且角色到模型的映射与_GET_models_同源(
    api_env: TestClient,
) -> None:
    """两个端点各推一遍 role→model 就是两份真相 —— 这条把它们钉成同一个。"""
    options = _body(api_env)
    assert options["models"]["editable_here"] is False
    assert "齿轮" in options["models"]["entry_point"]

    role_map = api_env.get("/models").json()["role_map"]
    for entry in options["models"]["roles"]:
        assert role_map[entry["role"]] == entry["model"], entry


def test_工具区不抄清单只给指针(api_env: TestClient) -> None:
    """内置模块里还留着三个已退役工具的 register() ⇒ 任何抄来的清单都会与真实注册分叉。"""
    tools = _body(api_env)["tools"]
    assert tools["source"] == "/tools"
    assert "items" not in tools and "names" not in tools, "这里不许出现第二份工具清单"


def test_RAG_开关对应哪个工具由后端说而不是前端写死(api_env: TestClient) -> None:
    """前端刚删掉 ``enabled_tools: ['calculator','code_exec']`` 那行字面量 ——
    如果换个地方再写死一个工具名，等于只搬了个家。"""
    from api.routes.config import RAG_TOOL_NAME

    tools = _body(api_env)["tools"]
    listed = {item["name"] for item in api_env.get("/tools").json()["items"]}
    assert tools["rag_tool"] == (RAG_TOOL_NAME if RAG_TOOL_NAME in listed else None), (
        "报一个没注册的名字 ⇒ 那颗开关会去白名单里减一个不存在项，"
        "用户看到「RAG 已关」而实际什么也没关"
    )


# --------------------------------------------------------------------------- #
# 未知状态：不静默隐藏、不当默认值
# --------------------------------------------------------------------------- #
def test_后端多给一个顶层键时响应照样带得出去() -> None:
    """``extra="allow"`` 是这条契约的承重墙：严格模型会在序列化前就把未知键丢掉，
    于是"后端加了配置、界面看不见"变成一件查不出来的事。"""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "defaults": {},
        "limits": {},
        "models": {"entry_point": "顶栏右上角齿轮 → 模型设置", "roles": []},
        "tools": {},
        "currency": "CNY",
        "pricing_basis": "元",
        "brand_new_knob": {"enabled": True, "note": "前端不认识我"},
    }
    dumped = AgentOptionsResponse.model_validate(payload).model_dump()
    assert dumped["brand_new_knob"]["enabled"] is True


def test_不认识的_kind_照样序列化得出去(api_env: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """kind 刻意不是 Literal：新 kind 要能原样透出，而不是在校验层炸掉。"""
    import api.routes.config as config_route

    monkeypatch.setattr(
        config_route,
        "_fields",
        lambda: [
            config_route.AgentOptionField(
                key="mystery", label="新字段", kind="quantum", accepted=False, enforced=False
            )
        ],
    )
    fields = _body(api_env)["fields"]
    assert fields[0]["kind"] == "quantum"


def test_缺字段的老响应形状照样能解析(api_env: TestClient) -> None:
    """前端认的是"少给就降级"，不是"少给就崩"——这里验后端不会反过来卡前端。"""
    partial = {"schema_version": 1, "defaults": {"max_iterations": 5}}
    # 只给必填里的必填：models/tools 是必填 ⇒ 应当报错，说明契约没被悄悄放宽
    with pytest.raises(Exception):
        AgentOptionsResponse.model_validate(partial)
