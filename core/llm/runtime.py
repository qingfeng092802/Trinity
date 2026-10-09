"""运行时模型覆盖层：**这一进程**当前用哪个模型、请求实际打到哪儿。

存在的理由（换模型方案 L-1/L-2/T-1/T-5）：模型只从 ``Settings`` 的四个字段来，
而 ``get_settings()`` 是 ``@lru_cache(maxsize=1)`` 的单例 ⇒ 想"当场换一家"只有两条路：
重建单例（``reset_settings_cache()`` 会连带把 ``api/deps.py`` 里一片单例的装配状态清掉，
比"改一个字段"大得多 —— T-5），或者一个**显式的覆盖对象**。这里选后者。

三条设计决定：

1. **覆盖的只有两个模型名**（``llm_model_large`` / ``llm_model_small``），
   ``llm_provider`` / ``llm_base_url`` / ``llm_api_key`` 三个字段**一个都不改**。
   端点与 Key 由 :func:`route` 按**模型 id 自己**查注册表决定 ⇒
   "模型名换了、请求还打旧供应商"（T-1）在结构上不可能发生，
   也不存在"provider 改了、model 还没改"这种撕裂中间态（两个字段之间没有任何耦合）。
2. **只活到重启**：状态是进程内的，重启后 ``Settings`` 从 ``.env`` 重新读，
   自然回落。这条必须写在面板上（L-2），否则用户会以为改了配置。
   本模块**永远不写文件**，尤其不写 ``.env``（凭据与配置只读，T-6）。
3. **Key 的值不进响应、不进日志**：路由结果只带 ``key_configured`` 与
   :func:`~core.llm.providers.masked` 后的脱敏串（L-1 定的"每家一把环境变量 Key +
   页面只读展示"）。写端点当场检查那家的 Key 在不在，缺就拒 ——
   否则症状会挪到"任务失败：未配置 LLM_API_KEY"（T-2），用户看不出是设置没生效。

4. （2026-09-27 起）**Key 也可以由面板在本进程内给**：:func:`apply_key` 把值放进
   模块级的 ``_key_overrides``，:func:`route` 优先读它，读不到才回落到 ``Settings``
   那三把环境变量 Key。三条边界都是照第 2 条定的口径来的：
   **不落盘、不写 ``.env``、不替换 ``get_settings()`` 单例**，重启自然回落；
   明文只作为参数往外传（``ModelRouting.api_key`` 那条 ``repr=False`` 的纪律不变），
   **任何响应模型与日志字段里都不许出现它**（用例
   ``test_key_response_never_echoes_the_secret`` 钉住）。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from config import Settings, get_settings
from core.llm import providers
from core.llm.pricing import CN_TZ, price_multiplier

__all__ = [
    "KEY_PROBE_TIMEOUT_S",
    "KeyProbe",
    "KeySource",
    "ModelRouting",
    "OverrideError",
    "OverrideRecord",
    "apply_key",
    "apply_override",
    "current",
    "effective_multiplier",
    "generation",
    "key_override_fields",
    "key_secret",
    "probe_key",
    "reset_override",
    "reset_state_for_tests",
    "route",
    "snapshot",
]

#: 模型 id 的上限长度（防止把一整段文本当模型名提交进日志）
_MAX_MODEL_ID_LENGTH = 64

#: 一把 Key 的三个来源。就这三个值 —— 页面要说清"这把 Key 从哪来"只有这三句话可说，
#: 加第四个取值等于给界面留一处"不知道该怎么翻译"的状态。
KeySource = Literal["env", "runtime", "none"]

#: Key 的长度上限。真实 Key 都在这个范围内（DeepSeek ``sk-`` + 32 位、智谱 ``id.secret``、
#: 千问 ``sk-`` + 32 位），而"贴进来一整段文档"不是 Key —— 那条会连着进日志与内存。
_MAX_KEY_LENGTH = 256

#: 探测供应商 ``GET /models`` 的超时（秒）。**3 秒**是拍过的数：这颗按钮是同步等的，
#: 5 秒以上用户会以为界面卡死，然后去重复点。超时不重试（重试等于把这笔等待再等一遍）。
#: 公开给 ``POST /models/key/validate`` 回显用 —— 界面要说"3 秒超时"，那个数得从这一处来。
KEY_PROBE_TIMEOUT_S = 3.0

#: 模型 id 允许的字符：字母数字 + ``. _ : / -``。千问与智谱的 id 都带点或冒号
#: （``qwen3-max``、``glm-4.6``、带版本号的 ``deepseek-v4-pro:0813`` 之类），
#: 空白与控制字符一律拒 —— 它们会出现在日志行里，等于给日志注入开了个口。
_ALLOWED_EXTRA = ".:/-"


class OverrideError(ValueError):
    """覆盖请求被拒（缺 Key / 模型名不合法）。

    单独成类是为了让写端点能稳定地翻成 422，而不是把 ``ValueError`` 一路撒到
    别的校验路径上。``message`` 里**只有供应商名与字段名**，没有 Key。
    """


@dataclass(frozen=True, slots=True)
class ModelRouting:
    """一次调用实际会用到的端点与 Key。

    ⚠️ ``api_key`` 是**明文**，只服务一件事：进程内传给 ``ChatOpenAI``。
    它被标了 ``repr=False``，所以 ``repr()`` / f-string / 异常里带上这个对象都不会
    把它吐出来；但它仍然**不该出现在任何响应模型或日志字段里** ——
    页面要显示的一直是 ``key_masked``（用例 ``Key 不进响应`` 钉住这一条）。
    """

    model: str
    provider: str
    provider_display: str
    base_url: str
    #: ``Settings`` 上那家 Key 的字段名（错误文案据此说"该配哪个环境变量"，不另抄一份命名规则）
    api_key_field: str
    #: 这个端点/Key 是从哪来的：.env 那一家 / 那家自己的端点覆盖 / 注册表默认端点
    endpoint_source: Literal["env", "provider_env", "provider_default"]
    #: 那家的 Key 到底配了没有（写端点据此拒绝）
    key_configured: bool
    #: 页面可显示的脱敏串
    key_masked: str
    #: 模型在注册表里有没有这一行（False = 自由填 ⇒ 单价必须标"未核价"）
    known: bool
    #: 建这个路由时生效的覆盖代号（适配层拿它作废 ``ChatOpenAI`` 缓存）
    generation: int
    #: 这把 Key 从哪来：``runtime`` = 面板在本次进程里填的，``env`` = 环境变量，
    #: ``none`` = 两个都没有。**页面要说"已配置（本进程填的）"还是得靠这一位**：
    #: 只报 ``key_configured`` 的话，重启前后界面长得一模一样，而生效原因不同。
    key_source: Literal["env", "runtime", "none"] = "none"
    #: 明文 Key，见类注释的 ``repr=False`` 纪律
    api_key: str = field(repr=False, default="")


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    """本次进程被改成了什么（``GET /models`` 直接摊成响应字段）。"""

    model_large: str
    model_small: str
    applied_at: datetime
    version: int
    #: 覆盖前的两个模型名（"点错了怎么回"的凭据，也写进响应给人看）
    previous_large: str
    previous_small: str


@dataclass(frozen=True, slots=True)
class KeyProbe:
    """一次「校验」的结果（``GET {base_url}/models`` 那趟探测的答复）。

    ⚠️ 这里**没有 Key 的位置**，也没有请求头 —— 结构上就回不出去。
    ``detail`` 是给屏幕看的：成功时报拿到几个模型，失败时是**供应商原话**
    （401/403 那句"invalid api key"比界面自己编的"Key 无效"更有用 —— 同一条 F-1 纪律）。
    """

    ok: bool
    provider: str
    base_url: str
    http_status: int | None
    model_count: int | None
    detail: str
    latency_ms: int


_lock = threading.RLock()
_record: OverrideRecord | None = None
_generation = 0
#: ``.env`` 里那两个档位的原始取值，第一次覆盖前记下来，供 :func:`reset_override` 回落。
#: 刻意**不在导入时**读：导入时 ``get_settings()`` 会被提前构造，测试里改环境变量的顺序
#: 就失效了。用惰性快照，保证"改 → 撤"与"改到同一个值"两种情况都对。
_base_models: tuple[str, str] | None = None
#: 面板在本次进程里填进来的 Key：键是 ``Settings`` 上的字段名（``llm_api_key_zhipu`` 等），
#: 值是明文。**不落盘、不进 DB、不进日志**，重启即空 —— 与 :data:`_record` 同一档生命周期。
#: 用字段名而不是 provider 名做键：一家可能有多个字段名路径（.env 那一家用的是 ``llm_api_key``），
#: 而 :func:`route` 算出来的正是字段名，两边同一把钥匙就不会有"存了却没读到"的那天。
_key_overrides: dict[str, str] = {}


def key_override_fields() -> tuple[str, ...]:
    """本次进程里被面板填过 Key 的那些 ``Settings`` 字段名（排序后给出，稳定可比）。"""
    with _lock:
        return tuple(sorted(_key_overrides))


def key_secret(field_name: str, settings: Settings | None = None) -> tuple[str, KeySource]:
    """某个 ``Settings`` 字段名上**实际会用到的**Key 明文与它的来源。

    一条规则：面板在本次进程里填的优先，其次才是环境变量。
    **全仓只这一处**读 :data:`_key_overrides`（:func:`route` 与 ``GET /models`` 的
    供应商视图都走这里）—— 两处各读一遍就会有"一处看到覆盖、一处没看到"的那天。

    Returns:
        ``(明文, 来源)``，来源是 ``runtime`` / ``env`` / ``none`` 之一。
    """
    resolved = settings or get_settings()
    with _lock:
        overridden = _key_overrides.get(field_name)
    if overridden is not None:
        return overridden, "runtime"
    raw = getattr(resolved, field_name, None)
    value = str(getattr(raw, "get_secret_value", lambda: raw or "")() or "").strip()
    return (value, "env") if value else ("", "none")


def apply_key(
    settings: Settings | None = None,
    *,
    provider: object,
    api_key: object,
) -> tuple[str, bool]:
    """把某家的 Key 放进本次进程（空串 = 撤掉这一家，回落到环境变量）。

    Args:
        settings: 配置对象，默认取全局单例。**只读它，不改它** ——
            覆盖值只进 :data:`_key_overrides`，所以 ``Settings`` 里那三把
            环境变量 Key 保持"来自 .env"这件事仍然为真，重启回落也是自动的。
        provider: 供应商标识（``deepseek`` / ``zhipu`` / ``qwen``）。
        api_key: 明文 Key；``strip()`` 后为空串表示撤回这一家。

    Raises:
        OverrideError: 供应商不在注册表里、Key 过长、或含控制字符
            （换行会一路进 HTTP 头，那是请求走私的形状，不是"用户手滑"）。

    Returns:
        ``(该家的 Key 字段名, 是否真的变了)``。与当前值相同时不改也不动缓存代号 ——
        白白作废一次 ``ChatOpenAI`` 缓存没有意义（与 :func:`apply_override` 同一口径）。
    """
    global _generation
    resolved = settings or get_settings()
    name = str(provider or "").strip().lower()
    spec = providers.provider_spec(name)
    if spec is None:
        known = "、".join(p.provider for p in providers.providers())
        raise OverrideError(f"未知的供应商「{name}」；注册表里有：{known}")
    field_name = spec.api_key_field
    raw = str(api_key or "").strip()
    if raw:
        if len(raw) > _MAX_KEY_LENGTH:
            raise OverrideError(f"Key 太长（{len(raw)} 字符，上限 {_MAX_KEY_LENGTH}）")
        if any(ch in raw for ch in ("\r", "\n", "\x00")) or any(ord(ch) < 0x20 for ch in raw):
            raise OverrideError("Key 含换行或控制字符，已拒绝")
    with _lock:
        current_value = _key_overrides.get(field_name)
        if not raw:
            changed = _key_overrides.pop(field_name, None) is not None
        else:
            changed = current_value != raw
            _key_overrides[field_name] = raw
        if changed:
            _generation += 1
        return field_name, changed


def probe_key(
    provider: str,
    api_key: str,
    settings: Settings | None = None,
    *,
    timeout_s: float = KEY_PROBE_TIMEOUT_S,
) -> KeyProbe:
    """拿这把 Key 去问一次 ``GET {base_url}/models`` —— **零 token** 的校验。

    为什么不发一次 chat completion：那要花钱、要等生成，而且失败原因会被模型可用性
    污染（"配额不足"与"Key 无效"是两件事，用户要点开才知道是哪件）。三家
    （DeepSeek / 智谱 / 千问）都是 OpenAI 兼容端点，``/models`` 只验鉴权。

    端点**不接收参数**：由 :func:`route` 按供应商查出来（与真发请求走的是同一个函数）。
    ⚠️ 这条是刻意的：如果界面能填 Base URL，这个端点就变成"带着别人的 Key 往任意
    地址发请求"的探针（SSRF），而且会出现"面板说会打智谱、请求其实打着别处"（T-1 那个形状）。
    要改端点请改环境变量 ``LLM_BASE_URL_<PROVIDER>``。

    用 stdlib ``urllib``：仓库依赖表里没有 httpx（它是 openai/langchain 的传递依赖），
    为一个探测动作把它升成直接依赖不值。
    """
    resolved = settings or get_settings()
    name = str(provider or "").strip().lower()
    spec = providers.provider_spec(name)
    if spec is None:
        known = "、".join(p.provider for p in providers.providers())
        raise OverrideError(f"未知的供应商「{name}」；注册表里有：{known}")
    # 端点向 route() 要（同一个函数，别在这里重述路由规则），拿那家里**一个真实模型**去问 ——
    # 拿一个编出来的 id 去问会落到"自由填 ⇒ 走 .env 那一家"那条规则，端点就问错了。
    sample = next((s.model_id for s in providers.registry() if s.provider == spec.provider), "")
    if not sample:  # pragma: no cover - 注册表自洽性用例兜着（每家至少一个模型）
        raise OverrideError(f"{spec.display_name} 在注册表里没有可用来探测的模型")
    routing = route(sample, resolved)
    if routing.endpoint_source == "env" and str(resolved.llm_provider).strip().lower() != spec.provider:
        # 自建网关那一档：请求根本不会打到这家的官网，拿这把 Key 去探网关等于自证假象。
        raise OverrideError(
            f"当前所有请求都走 .env 的端点与 Key（LLM_PROVIDER={resolved.llm_provider}），"
            f"{spec.display_name} 这把 Key 不会被用到，校验也没有意义"
        )
    base_url = routing.base_url
    url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(  # noqa: S310 - URL 来自注册表/环境变量，不是用户输入
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            payload = response.read(200_000)
            status = int(getattr(response, "status", 200) or 200)
        count: int | None = None
        try:
            body = json.loads(payload.decode("utf-8", "replace"))
        except ValueError:
            body = None
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, list):
                count = len(data)
        latency = int((time.monotonic() - started) * 1000)
        return KeyProbe(
            ok=status == 200,
            provider=routing.provider,
            base_url=base_url,
            http_status=status,
            model_count=count,
            detail=(
                f"鉴权通过，端点报出 {count} 个模型" if count is not None and status == 200
                else f"HTTP {status}（响应里没有 data 数组）" if status == 200
                else f"HTTP {status}"
            ),
            latency_ms=latency,
        )
    except urllib.error.HTTPError as exc:
        detail = _read_error_body(exc)
        latency = int((time.monotonic() - started) * 1000)
        return KeyProbe(
            ok=False,
            provider=routing.provider,
            base_url=base_url,
            http_status=int(exc.code),
            model_count=None,
            detail=f"HTTP {exc.code}{f'：{detail}' if detail else ''}",
            latency_ms=latency,
        )
    except urllib.error.URLError as exc:
        latency = int((time.monotonic() - started) * 1000)
        reason = str(getattr(exc, "reason", exc))[:160]
        timed_out = "timed out" in reason.lower() or "timeout" in reason.lower()
        return KeyProbe(
            ok=False,
            provider=routing.provider,
            base_url=base_url,
            http_status=None,
            model_count=None,
            detail=f"校验超时（{timeout_s:g} 秒），请检查网络或该家的 base_url" if timed_out
            else f"连不上 {url}：{reason}",
            latency_ms=latency,
        )


def _read_error_body(exc: urllib.error.HTTPError, limit: int = 300) -> str:
    """把供应商那句原话取出来（截到 ``limit`` 字符，压成一行）。

    为什么值得取：401 时 DeepSeek 报 ``Authentication Fails``、智谱报
    ``1002 Wrong API key``、千问报 ``InvalidApiKey`` —— 三家的说法比界面能编的
    任何一句都准，而排查的人要的就是"哪一家认出来的"。
    """
    try:
        raw = exc.read(limit * 4)
    except Exception:  # pragma: no cover - 读不到 body 就退回空串，不该为此崩
        return ""
    text = raw.decode("utf-8", "replace").strip().replace("\n", " ")
    if not text:
        return ""
    return text[:limit] + ("…" if len(text) > limit else "")


def _normalize_model_id(raw: object, field: str) -> str:
    """校验并归一化模型 id（写端点与自由填共用这一条，别在第二处再验一遍）。"""
    value = str(raw or "").strip().lower()
    if not value:
        raise OverrideError(f"{field} 不能为空")
    if len(value) > _MAX_MODEL_ID_LENGTH:
        raise OverrideError(f"{field} 太长（{len(value)} 字符，上限 {_MAX_MODEL_ID_LENGTH}）")
    if not all(ch.isalnum() or ch in _ALLOWED_EXTRA for ch in value):
        raise OverrideError(f"{field} 含不允许的字符（只允许字母、数字与 {' '.join(_ALLOWED_EXTRA)}）")
    return value


def route(model: str, settings: Settings | None = None) -> ModelRouting:
    """这个模型 id 的请求会打到哪个端点、用哪把 Key。

    路由规则**只有三条**，按顺序判，写成一句话好核对（每条都有用例钉着）：

    1. **注册表没有这一行**（自由填的 id）⇒ 完全走 ``.env``：``llm_base_url`` +
       ``llm_api_key``。这是"我自己的网关上有个新模型"的正常用法，
       也正是换供应商功能出现之前的老行为，一字不变。
    2. **``.env`` 里那一家不是注册表里的供应商**（填的是 ``custom`` / ``openai``）
       ⇒ 所有模型都继续走 ``llm_base_url``。⚠️ 这条是防回归的：一个把
       ``LLM_BASE_URL`` 指向自建网关的人，切到 ``glm-4.6`` 时**不该**被悄悄改打到
       智谱官网 —— 那会让原本能用的部署当场失配，而且报的是"鉴权失败"。
    3. 其余情况：**模型 id 决定供应商**，端点用该家的官网地址
       （可被 ``LLM_BASE_URL_<PROVIDER>`` 覆盖），Key 用 ``LLM_API_KEY_<PROVIDER>``。
       ``.env`` 那一家自己的模型仍用 ``llm_api_key`` / ``llm_base_url``（老字段不动）。

    Args:
        model: 模型 id。
        settings: 配置对象，默认取全局单例。

    Returns:
        :class:`ModelRouting`。``provider`` 是"这个模型属于哪家"，
        ``endpoint_source`` 是"请求实际从哪拿到的地址" —— 两者分开记，
        所以自建网关 + 智谱模型这种组合也能在人话里说清（"智谱 GLM · 端点来自 LLM_BASE_URL"）。
    """
    resolved = settings or get_settings()
    name = str(model or "").strip().lower()
    spec = providers.resolve_model(name)
    env_provider = providers.provider_spec(resolved.llm_provider)
    if spec is not None and providers.provider_spec(spec.provider) is None:  # pragma: no cover
        raise OverrideError(f"模型 {spec.model_id} 指向未登记的供应商 {spec.provider}")

    provider = providers.provider_spec(spec.provider) if spec is not None else None
    # 该不该用 .env 那套端点与 Key（见上面规则 1 / 2 / "正是那一家"的规则 3 前半）
    uses_env_channel = (
        provider is None or env_provider is None or env_provider.provider == provider.provider
    )
    if uses_env_channel:
        base_url = resolved.llm_base_url
        key_field = "llm_api_key"
        endpoint_source: Literal["env", "provider_env", "provider_default"] = "env"
    else:
        override_url = str(getattr(resolved, provider.base_url_field, "") or "").strip().rstrip("/")
        base_url = override_url or provider.base_url
        key_field = provider.api_key_field
        endpoint_source = "provider_env" if override_url else "provider_default"

    # 值与来源都向 :func:`key_secret` 要（它才是"面板填的优先于环境变量"那一条规则的唯一住处）
    plaintext, key_source = key_secret(key_field, resolved)
    return ModelRouting(
        model=name,
        provider=(
            provider.provider if provider else str(resolved.llm_provider).strip().lower()
        ),
        provider_display=(
            provider.display_name
            if provider
            else env_provider.display_name
            if env_provider
            else str(resolved.llm_provider)
        ),
        base_url=base_url,
        api_key_field=key_field,
        endpoint_source=endpoint_source,
        key_configured=bool(plaintext),
        key_masked=providers.masked(plaintext),
        known=spec is not None,
        generation=_generation,
        key_source=key_source,
        api_key=plaintext,
    )


def effective_multiplier(model: str, settings: Settings | None = None) -> float:
    """这家供应商在该时刻的价格系数。

    ⚠️ **不是所有家都分峰谷**：高峰/低谷是 DeepSeek 的计费规则
    （:mod:`core.llm.pricing`），智谱与千问官网没有这一档。对不分峰谷的家返回 ``1.0`` ——
    把 0.5 的低谷折扣套到它们头上，账会在每天 12:00/18:00 之后**系统性少一半**，
    而且看起来完全正常。这是本模块存在的一个理由。

    问的是**路由之后的那一家**（:func:`route`），不是拿模型名自己查表：
    ``.env`` 写着 ``llm_provider=deepseek`` 而模型是自由填的 id 时，请求打的仍是
    DeepSeek（或它的兼容网关），低谷折扣**该**继续生效 —— 按模型名查会把它判成"别家"，
    那是把一个原本正确的折扣悄悄关掉。

    ⚠️ 反过来，``llm_provider=custom`` / ``openai`` 这类注册表里查不到的家
    **一律给 1.0**：网关背后是什么计费我们核实不了，而"套用 DeepSeek 的低谷折扣"一旦
    网关不认这个规则，账就**系统性少一半且不报错**。方向上宁可高估 ——
    与 DeepSeek 那三行"按固定汇率折算、偏保守"是同一条口径。
    这是一处**有意的行为变化**：以前挂着自建网关跑 DeepSeek 的部署在低谷时段会被打半价。

    计费规则**跟着请求真正打到的那个端点**走（``endpoint_source``），不是跟着模型名走：
    ``LLM_PROVIDER=zhipu`` 的部署选 ``deepseek-flash`` 时，请求打的是 DeepSeek 官网，
    该拿 DeepSeek 的峰谷规则；反之自建网关选 ``deepseek-flash`` 时打的是网关，规则未知。
    """
    resolved = settings or get_settings()
    routing = route(model, resolved)
    billing_name = str(resolved.llm_provider) if routing.endpoint_source == "env" else routing.provider
    provider = providers.provider_spec(billing_name)
    if provider is None or not provider.peak_off_peak:
        return 1.0
    return price_multiplier()


def current() -> OverrideRecord | None:
    """当前覆盖记录；``None`` = 还在用 ``.env`` 的值。"""
    return _record


def generation() -> int:
    """覆盖代号，每次成功 apply/reset 各加一。

    适配层拿它作缓存作废的凭据（``ChatOpenAI`` 实例里烙着 ``base_url`` 与 Key，
    换模型后必须重建，否则界面显示新模型、请求还打旧供应商 = T-1）。
    """
    return _generation


def apply_override(
    settings: Settings | None = None,
    *,
    model_large: object,
    model_small: object,
) -> OverrideRecord:
    """把两个档位改成新的模型 id（进程内，重启即回落）。

    Args:
        settings: 配置对象，默认取全局单例。
        model_large: 强模型档（planner / reviewer / judge）。
        model_small: 快模型档（executor / extract）。

    Raises:
        OverrideError: 模型名不合法，或该模型所属供应商**没有配 Key**（T-2），
            或 .env 那一家完全没有 Key（这时换了也发不出请求，当场说清）。

    Returns:
        新的 :class:`OverrideRecord`。
    """
    global _record, _generation, _base_models

    resolved = settings or get_settings()
    large = _normalize_model_id(model_large, "model_large")
    small = _normalize_model_id(model_small, "model_small")

    missing = _providers_missing_key(large, small, resolved)
    if missing:
        raise OverrideError(
            f"这几家还没有配 API Key：{'；'.join(missing)}。"
            "可以在下面那栏填（只在这一次进程里生效，重启回落到 .env），"
            "或者写进 .env 再重启后端 —— 本面板不会改写 .env"
        )

    with _lock:
        if _base_models is None:
            _base_models = (resolved.llm_model_large, resolved.llm_model_small)
        previous_large, previous_small = (
            _record.model_large if _record else _base_models[0],
            _record.model_small if _record else _base_models[1],
        )
        # 先写大档再写小档：两档属于同一次原子操作，中途被读到也只是"新大档 + 旧小档"，
        # 两个模型各自都能正常路由（模型 id 自己决定端点），不会打错供应商。
        resolved.llm_model_large = large
        resolved.llm_model_small = small
        _generation += 1
        _record = OverrideRecord(
            model_large=large,
            model_small=small,
            applied_at=datetime.now(CN_TZ),
            version=_generation,
            previous_large=previous_large,
            previous_small=previous_small,
        )
        return _record


def reset_override(settings: Settings | None = None) -> bool:
    """回落到 ``.env`` 里的那两个模型。

    Returns:
        ``True`` = 确实撤掉了一个覆盖；``False`` = 本来就没覆盖在生效（幂等，
        不报错也不动缓存代号 —— "点了没改"不该白白断掉一次连接池）。
    """
    global _record, _generation

    resolved = settings or get_settings()
    with _lock:
        if _record is None or _base_models is None:
            return False
        resolved.llm_model_large, resolved.llm_model_small = _base_models
        _record = None
        _generation += 1
        return True


def _providers_missing_key(large: str, small: str, settings: Settings) -> list[str]:
    """这两档涉及的供应商里，哪些没有 Key（返回"哪家 + 该配哪个环境变量"的人话）。

    .env 那一家完全没配 Key 时**也要报**：``llm_configured`` 为假意味着换了谁都发不出
    请求，那时候点"应用"成功、下一个任务失败，是最难查的一种挪位置（T-2）。
    """
    names: list[str] = []
    for model in (large, small):
        routing = route(model, settings)
        if routing.key_configured:
            continue
        label = f"{routing.provider_display}（环境变量 {routing.api_key_field.upper()}）"
        if label not in names:
            names.append(label)
    return names


def reset_state_for_tests() -> None:
    """把本模块的进程内状态清干净（**测试专用**，业务代码不许调）。

    为什么单独需要它：这里的状态是模块级全局（覆盖层按设计就是进程内的），
    而 ``conftest`` 的重置只清 ``lru_cache`` 那些单例 —— 清不到这里。
    漏掉的后果不是"测试脏"而是**顺序依赖**：前一个用例换了模型没换回来，
    后一个用例读到的 ``.env`` 值就已经是前一个用例写进去的了。
    先把当前单例上的两个档位还原，再清快照与代号。
    ``_key_overrides`` 同样必须清：漏掉的话"上一把 Key"会让下一个用例
    在根本没人配环境变量的情况下量到 ``key_configured=True``。
    """
    global _record, _generation, _base_models

    with _lock:
        if _record is not None and _base_models is not None:
            try:
                settings = get_settings()
                settings.llm_model_large, settings.llm_model_small = _base_models
            except Exception:  # noqa: BLE001 - 还原失败也要把状态清掉，别把脏状态留给下一个用例
                pass
        _record = None
        _base_models = None
        _generation = 0
        _key_overrides.clear()


def snapshot() -> dict[str, object]:
    """给日志/自检用的一行事实（**不含任何 Key 明文**）。

    ``runtime_keys`` 只报**字段名**（``llm_api_key_zhipu`` 这种 —— 它本来就是环境变量名，
    已经出现在 ``GET /models`` 的响应里），不报值也不报脱敏串。这一行会进日志，
    而"本进程有没有面板填进来的 Key"是排查时必须知道的事实：不报的话，人只会去翻 .env。
    """
    record = current()
    return {
        "override": None if record is None else record.model_large,
        "override_small": None if record is None else record.model_small,
        "generation": generation(),
        "runtime_keys": list(key_override_fields()),
    }
