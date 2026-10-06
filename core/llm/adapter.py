"""统一的 LLM 适配层。

设计目标
--------
1. **屏蔽供应商差异**：对外只暴露 ``invoke`` / ``invoke_json`` / ``invoke_model`` /
   ``count_tokens`` / ``estimate_cost``，上层 Agent 不感知底层是
   DeepSeek 还是 OpenAI。
   （2026-10-02 摘掉 ``stream``：那条独立的流式实现全仓零调用点，且用量口径与
   主路径不同源 —— 主路径走 ``_stream_once``（那里显式传 ``stream_usage=True``
   拿真实 usage），而被删的这条只能靠 ``count_tokens`` 估。留着就是第二条会
   算错账的账本。）
2. **可观测**：每次调用都会把 token 数、耗时、成本写入 ``adapter.last_usage``，
   供 ``evaluation/trace.py`` 埋点直接取用，不需要在业务代码里重复统计。
3. **抗脏输出**：LLM 返回非 JSON 时走「抽取 → 校验 → 带错误回灌重试 → 抛
   ``LLMJsonError``」四段式，把不确定性收敛在一处，而不是散落到每个节点。

示例::

    from core.llm.adapter import get_adapter

    llm = get_adapter()
    text = llm.invoke([{"role": "user", "content": "用一句话解释什么是 Agent"}])
    print(llm.last_usage)                    # Usage(token_in=..., cost=...)

    from pydantic import BaseModel
    class Plan(BaseModel):
        steps: list[str]

    data = llm.invoke_json([{"role": "user", "content": "拆解：写一个爬虫"}], Plan)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Literal, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import Settings, get_settings
from core.llm import providers, runtime

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

#: 允许作为消息传入的两种形态：LangChain 消息对象，或 {"role": ..., "content": ...} 字典。
MessageLike = BaseMessage | Mapping[str, str]

_ROLE_MAP: dict[str, type[BaseMessage]] = {
    "system": SystemMessage,
    "user": HumanMessage,
    "human": HumanMessage,
    "assistant": AIMessage,
    "ai": AIMessage,
}

_FENCE_RE = re.compile(r"```(?:json|JSON|javascript|python)?\s*(.*?)```", re.DOTALL)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")

#: 成本估算保留的小数位数。
#:
#: 单价单位全项目统一为「元 / 100 万 token」（默认 2.13 / 8.52，与 ``MODEL_PRICES``
#: 同源），一次短调用（约 1k in / 500 out）的成本在 0.006 元量级。
#: 取 10 位是为了吸收二进制浮点尾差（1e-16 相对量级），又不给数值加上虚假精度——
#: 真正的展示取整交给报告 / 页面层，这里不提前截断，否则多轮累计与低谷折扣
#: 叠起来会看见抹平痕迹。
#: ⚠️ 这段理由原先写的是「单价按元/token 计（默认 2.13e-6）」——那个单位是错的，
#: 详见 :meth:`estimate_cost` 的口径说明与 tests/unit/test_adapter_json.py。
_COST_PRECISION_DIGITS = 10

#: 已知模型的官方价（人民币元 / 100 万 token），键为 (输入价, 输出价)。
#:
#: ⚠️ **这张表不再是数据，它是 :mod:`core.llm.providers` 注册表的一个投影**：
#: 值由 ``{id: 最低档价}`` 生成，所以"注册表里标的价"与"记账用的价"结构上不可能分叉
#: （以前这里是唯一的一份价，加供应商时再抄一份就是第三个口径 —— R-03 那轮的教训）。
#: 保留这个名字与形状，是为了让既有消费方（``api/routes/tasks.py`` 的单价反推、
#: 用例里钉死的 ``(2.13, 8.52)``）一字不改地继续成立。
#:
#: ⚠️ 阶梯模型（glm-4.6 / qwen-plus / qwen3-max…）在这一份里看到的是**最低档**，
#: 长上下文会更贵。真正记账时按输入长度选档请走 :func:`resolve_price`
#: （它接 ``token_in``），别直接用这张扁表。
#:
#: 来源、核对日期与"为什么 GLM-4.5 不在表里"见 :mod:`core.llm.providers`。
#: 价格随时会变，以官网为准；表中没有的模型会退回 ``Settings.llm_price_in/out``。
MODEL_PRICES: dict[str, tuple[float, float]] = providers.MODEL_PRICES

#: 单价解析结果的来源标记（``resolve_price`` 的第三个返回值）。
#: 单独定出来是为了让 ``GET /models`` 能如实告诉前端这个价是"表里的官方价"
#: 还是"兜底猜的"，而不是把两种置信度不同的数混成一份看起来一样的清单。
PriceSource = Literal["official_table", "settings_fallback"]


def resolve_price(
    name: str, settings: Settings, token_in: int | None = None
) -> tuple[float, float, PriceSource]:
    """解析某个模型的单价，返回 ``(输入价, 输出价, 来源)``，单位**元 / 100 万 token**。

    查找顺序：注册表精确匹配 → 最长前缀匹配 → ``Settings`` 兜底单价。

    这是全项目**唯一**的单价口径入口：``estimate_cost`` 与 ``GET /models`` 都走它。
    之前两边各写一份的话，注册表上显示的价和实际记账的价可能悄悄分叉
    （同一个页面两份不一致的数字，比没有数字更糟）。

    Args:
        name: 模型 id。
        settings: 配置对象，提供兜底单价。
        token_in: 本次调用的**输入** token 数。智谱与千问都按输入长度分档计价，
            给了才能选对档；不给（或该模型不分档）时取最低档，
            这是一个**偏乐观**的口径 —— 长上下文实际更贵，所以 ``GET /models``
            会把整张阶梯表一起报出去，让"报的是哪一档"可以被核对。

    Returns:
        ``(price_in, price_out, source)``；``source`` 见 :data:`PriceSource`。
    """
    price = providers.price_for(name, token_in)
    if price is not None:
        return price[0], price[1], "official_table"
    return settings.llm_price_in, settings.llm_price_out, "settings_fallback"


#: 需要重试的瞬时异常（网络抖动 / 限流 / 超时）。openai SDK 由 langchain-openai 间接引入。
_TRANSIENT_ERROR_TYPES: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)


def _collect_transient_errors() -> tuple[type[BaseException], ...]:
    """把 openai SDK 的可重试异常合并进来（SDK 缺失时静默降级）。"""
    errors: list[type[BaseException]] = list(_TRANSIENT_ERROR_TYPES)
    try:  # pragma: no cover - 取决于环境是否装了 openai
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        errors.extend(
            [APIConnectionError, APITimeoutError, RateLimitError, APIStatusError]
        )
    except Exception:  # noqa: BLE001 - 缺 openai 不影响主流程
        logger.debug("未检测到 openai SDK，重试策略仅覆盖内置网络异常")
    return tuple(dict.fromkeys(errors))


RETRYABLE_ERRORS: tuple[type[BaseException], ...] = _collect_transient_errors()

#: 「重试也不会好」的 HTTP 状态码：参数错误、鉴权、计费、权限、资源不存在。
#: 注意：429（限流）与 5xx（服务端抖动）**必须**继续重试，不能放进这个集合。
NON_RETRYABLE_STATUS: frozenset[int] = frozenset({400, 401, 402, 403, 404, 422})

#: 状态码 → 可执行提示（把「重试无用」的原始报错翻译成人能看懂的一句话）
STATUS_HINTS: dict[int, str] = {
    400: "请求参数不合法：检查模型名与请求体（重试无用）",
    401: "鉴权失败：检查 LLM_API_KEY 是否正确或已过期",
    402: "账户余额不足：去供应商控制台充值后再跑（这不是代码问题，重试无用）",
    403: "权限不足：当前 Key 没有该模型或接口的权限",
    404: "接口或模型不存在：检查 LLM_BASE_URL 与模型名",
    422: "请求体校验失败：检查参数格式",
}


def _status_code_of(exc: BaseException) -> int | None:
    """取 HTTP 状态码；openai SDK 的异常带 ``status_code``。"""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def status_is_retryable(status: int | None) -> bool:
    """只看状态码：429（限流）与 5xx（服务端抖动）可重试，4xx 客户端错误不可重试。

    ``None`` 表示连接层错误（没有 HTTP 响应），属于可重试。
    """
    return status is None or status not in NON_RETRYABLE_STATUS


def is_non_retryable(exc: BaseException) -> bool:
    """这个错误重试还有意义吗？（余额 / 鉴权 / 参数错误属于重试无用）"""
    return _status_code_of(exc) in NON_RETRYABLE_STATUS


def is_retryable(exc: BaseException) -> bool:
    """只重试真正瞬时的错误：连接失败、超时、限流、5xx。

    两个条件都要满足：**异常类型**属于已知瞬时类型，且**状态码**不在「重试无用」集合里。
    这里必须按状态码细分，不能只按异常类型判断——``openai.APIStatusError`` 是所有 HTTP
    错误的父类（401/402/403/429/5xx 全在内），按类型放行会把「余额不足」也重试 3 次。
    """
    if not isinstance(exc, RETRYABLE_ERRORS):
        return False
    return status_is_retryable(_status_code_of(exc))


class LLMError(RuntimeError):
    """LLM 调用相关错误的基类。"""


class LLMNotRetryableError(LLMError):
    """重试无用的调用失败（余额不足 / 鉴权失败 / 参数错误）。

    单独成类是为了让批处理能**快速失败**：这类错误重试一万次结果都一样，
    整批任务应当立刻停下并给出可执行提示，而不是把时间耗在指数退避上。
    """


class LLMJsonError(LLMError):
    """LLM 输出无法解析为合法 JSON / 不满足给定 Schema。"""

    def __init__(self, message: str, *, raw_text: str = "", attempts: int = 1) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.attempts = attempts


@dataclass(slots=True)
class Usage:
    """单次 LLM 调用的用量与成本快照。"""

    model: str = ""
    token_in: int = 0
    token_out: int = 0
    cost: float = 0.0
    #: 这次调用**实际套用的**峰谷系数（高峰 1.0 / 低谷 0.5，来自
    #: :func:`core.llm.pricing.price_multiplier`）。默认 1.0 只服务两件事：
    #: 手工构造 ``Usage``（测试里的 Mock 适配器）与历史数据无此字段时的语义。
    #: ⚠️ 它必须与上面的 ``cost`` 来自**同一个** ``mult`` 值：一次调用如果跨了
    #: 12:00 / 18:00 边界，"cost 按 A 档算、multiplier 记 B 档"就是两份自相矛盾的账，
    #: 而且不会报错 —— 成本归因面板的峰谷标注正是读这一列（方案 §10.2b）。
    multiplier: float = 1.0
    duration_ms: int = 0
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        """转成可直接写进 TraceRecord 的普通字典。"""
        return asdict(self)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def to_messages(messages: Sequence[MessageLike]) -> list[BaseMessage]:
    """把混合形态的消息列表统一转换成 LangChain 消息对象。"""
    converted: list[BaseMessage] = []
    for item in messages:
        if isinstance(item, BaseMessage):
            converted.append(item)
            continue
        role = str(item.get("role", "user")).lower()
        content = str(item.get("content", ""))
        cls = _ROLE_MAP.get(role, HumanMessage)
        converted.append(cls(content=content))
    if not converted:
        raise LLMError("messages 为空，至少需要一条用户消息")
    return converted


def _json_span(text: str) -> str | None:
    """用括号配对扫描出第一个完整 JSON 值（对象或数组），跳过字符串内的括号。"""
    start = -1
    for idx, ch in enumerate(text):
        if ch in "{[":
            start = idx
            break
    if start < 0:
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def extract_json(text: str) -> Any:
    """从可能带解释文字的 LLM 输出里抽取 JSON。

    依次尝试：整体解析 → ```json 代码块 → 首个配平的 ``{...}`` / ``[...]`` 片段。

    Raises:
        LLMJsonError: 三种策略都失败时抛出，附带原始文本片段便于定位。
    """
    if text is None:
        raise LLMJsonError("LLM 返回内容为 None", raw_text="")

    raw = text.strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    for match in _FENCE_RE.finditer(raw):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            span = _json_span(candidate)
            if span:
                try:
                    return json.loads(span)
                except json.JSONDecodeError:
                    continue

    span = _json_span(raw)
    if span:
        try:
            return json.loads(span)
        except json.JSONDecodeError as exc:
            raise LLMJsonError(
                f"JSON 括号配对成功但内容非法：{exc}", raw_text=raw[:500]
            ) from exc

    raise LLMJsonError("未能从 LLM 输出中抽取到 JSON", raw_text=raw[:500])


def _schema_hint(schema: type[BaseModel] | Mapping[str, Any]) -> str:
    """给出一段简短的 Schema 说明，拼进提示词提高一次成功率。"""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        fields = []
        for name, field in schema.model_fields.items():
            # 优先用 alias：pass 这类 Python 关键字只能走别名声明，提示词必须用同一个键名
            key = field.alias or name
            desc = field.description or ""
            fields.append(f'  - "{key}": {desc}'.rstrip())
        head = f"JSON 对象，字段如下（{schema.__name__}）："
        return head + "\n" + "\n".join(fields)
    return f"必须严格符合该 JSON Schema：\n{json.dumps(dict(schema), ensure_ascii=False)}"


def _validate(schema: type[BaseModel] | Mapping[str, Any], data: Any) -> Any:
    """按 Pydantic 模型或 JSON Schema 校验。

    传入 Pydantic 模型时校验最严格；传入 JSON Schema 字典时用 ``jsonschema``
    校验，既支持 object 也支持 array（对应 planner 的「只输出 JSON 数组」契约）。

    Returns:
        校验通过的数据本体：Pydantic 模型返回 ``model_dump()`` 的 dict，
        JSON Schema 形式原样返回（可能是 dict，也可能是 list）。
    """
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(data).model_dump()
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema 是声明依赖
        raise LLMJsonError(
            "缺少 jsonschema 依赖，无法按 JSON Schema 校验输出",
            raw_text=str(data)[:200],
        ) from exc
    try:
        jsonschema.validate(instance=data, schema=dict(schema))
    except jsonschema.ValidationError as exc:
        raise LLMJsonError(
            f"JSON Schema 校验失败：{exc.message}",
            raw_text=str(data)[:200],
        ) from exc
    return data


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #
class LLMAdapter:
    """LLM 调用的唯一入口。

    Args:
        settings: 配置对象，默认取全局单例。
        temperature: 采样温度，默认 0.0 以求稳定复现（评测场景尤为重要）。
        max_tokens: 单次输出上限，None 表示交给模型默认值。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        self.settings: Settings = settings or get_settings()
        self.temperature = temperature
        self.max_tokens = max_tokens
        #: ``last_usage`` 改为**线程本地**存储（见下方 property 的注释）：
        #: 每个线程持有自己的用量槽位，从结构上消除「多 worker 共读一个
        #: 可变字段」的 TOCTOU 串号（设计文档 §0.1-4 / U4）。
        self._usage_local = threading.local()
        self._clients: dict[str, ChatOpenAI] = {}
        #: ``_clients`` 是在哪个覆盖代号下建的（见 :meth:`_client` 的 T-1 说明）。
        #: 初值取当前代号，所以"进程起来还没人换过模型"时不会多做一次无谓清空。
        self._client_generation = runtime.generation()

    # ------------------------------------------------------------ 用量快照 --
    @property
    def last_usage(self) -> Usage:
        """最近一次 LLM 调用的用量快照（**线程本地**）。

        为什么是线程本地而不是普通实例字段：``get_adapter()`` 是 ``lru_cache``
        单例，而 ``last_usage`` 原本是单例上的**单一可变槽位**。M1 有最多
        ``api_max_concurrent_tasks`` 个 worker 线程共用同一 adapter 时，
        A 任务读到的可能是 B 任务刚写进去的用量，导致 token / 成本串号
        （设计文档 §0.1-4 的 TOCTOU 风险）。

        改为线程本地后，每个 worker 线程各读各的槽位，**结构上不可能串号**，
        且对既有调用方（``getattr(self.llm, "last_usage", None)``、
        ``adapter.last_usage.as_dict()``）保持完全兼容的读写接口。

        Returns:
            本线程最后一次调用的 :class:`Usage`；本线程尚未调用过时返回
            一个全零的默认 :class:`Usage`。
        """
        usage = getattr(self._usage_local, "value", None)
        if usage is None:
            usage = Usage()
            self._usage_local.value = usage
        return usage

    @last_usage.setter
    def last_usage(self, usage: Usage) -> None:
        """写入本线程的用量槽位（供真实适配器与测试替身共同使用）。"""
        self._usage_local.value = usage

    # ------------------------------------------------------------- 客户端 --
    def _client(self, model: str, temperature: float | None = None) -> ChatOpenAI:
        """按 (模型, 温度, **端点**) 缓存客户端实例，避免每次调用都重建连接池。

        ⚠️ 这里原来只用 ``f"{model}@{temp}"`` 作键，而 ``api_key`` / ``base_url`` 是在
        **第一次建实例时**从当时的 settings 烙进 ``ChatOpenAI`` 的（陷阱 T-1）。
        换供应商 / 换端点时旧实例的键没变、里面却还打着旧地址 ⇒
        界面显示新模型、请求仍打旧供应商，一切看起来正常、钱记在另一家头上。
        两条一起修：① 键里带上真正生效的 ``base_url``；
        ② 覆盖层代号（:func:`core.llm.runtime.generation`）一变就清空整张缓存 ——
        这一行是"删掉必红"的那一行，L 趟与后端用例都钉着它。
        """
        temp = self.temperature if temperature is None else temperature
        routing = runtime.route(model, self.settings)
        if routing.generation != self._client_generation:
            self._clients.clear()
            self._client_generation = routing.generation
        cache_key = f"{model}@{temp}@{routing.base_url}"
        if cache_key not in self._clients:
            if not routing.key_configured:
                #: 环境变量名由**注册表里的字段名**推出来（``llm_api_key_zhipu`` →
                #: ``LLM_API_KEY_ZHIPU``），不在这里再抄一份命名规则、也不分 .env 那一家
                #: 特殊处理 —— ``deepseek`` 的字段名本来就是 ``llm_api_key``。
                raise LLMError(
                    f"未配置 {routing.provider_display} 的 API Key"
                    f"（环境变量 {routing.api_key_field.upper()}）。"
                    "请写进 .env 后重启后端；设置面板不接收 Key。"
                )
            kwargs: dict[str, Any] = {
                "model": routing.model,
                "api_key": routing.api_key,
                "base_url": routing.base_url,
                "temperature": temp,
                "timeout": self.settings.llm_timeout,
                "max_retries": 0,  # 重试由本层统一控制，避免双重退避
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
            self._clients[cache_key] = ChatOpenAI(**kwargs)
        return self._clients[cache_key]

    def _invoke_once(
        self,
        messages: list[BaseMessage],
        model: str,
        *,
        json_mode: bool,
        temperature: float | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> tuple[str, int, int]:
        """真正发一次请求，返回 (文本, 输入 token, 输出 token)。

        Args:
            on_text: 给了就走**流式**分支（逐块回调 + 逐块累积），否则走一次性
                ``invoke``。两条分支的用量口径刻意保持一致（见
                :meth:`_stream_once` 的注释）。
        """
        client = self._client(model, temperature)
        runnable: Any = client
        if json_mode and self.settings.llm_json_mode:
            # bind 为惰性绑定，模型不支持时会在 invoke 阶段抛错，由上层降级重试。
            runnable = client.bind(response_format={"type": "json_object"})

        if on_text is not None:
            return self._stream_once(runnable, messages, model, on_text)

        response = runnable.invoke(messages)

        content = response.content
        if isinstance(content, list):  # 多模态分片，拼成纯文本
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        text = str(content)

        meta = getattr(response, "usage_metadata", None) or {}
        token_in = int(meta.get("input_tokens", 0)) or self.count_tokens(_flatten(messages))
        token_out = int(meta.get("output_tokens", 0)) or self.count_tokens(text)
        return text, token_in, token_out

    def _stream_once(
        self,
        runnable: Any,
        messages: list[BaseMessage],
        model: str,
        on_text: Callable[[str], None],
    ) -> tuple[str, int, int]:
        """流式发一次请求：逐块 ``on_text`` 回调，返回 (全文, 输入 token, 输出 token)。

        三条与 :meth:`_invoke_once` **刻意保持一致**的口径：

        1. **用量**：优先读供应商在末块给的 ``usage_metadata``（真实计数），
           读不到才退回 :meth:`count_tokens` 估算 —— 与非流式分支的
           ``meta.get(...) or count_tokens(...)`` 完全同一条降级链。
           ⚠️ ``stream_usage=True`` 是显式传的：langchain-openai 只在**默认端点**
           上自动开用量统计，本项目 base_url 指向 DeepSeek，不传就没有用量块 ——
           少了它，流式路径的 token/成本会整体退化成估算值，而同一条任务的
           非流式路径是真实值，两份账并排会自相矛盾（这正是 ``_call`` 那条
           「时钟只读一次」纪律要防的同一类事故）。
        2. **内容拼法**：多模态分片按 ``part["text"]`` 拼，与上面那条一致。
        3. **异常**：不在这里吞。流式跑到一半失败由 :meth:`_call` 的重试兜住。

        Args:
            runnable: 已 bind 好的客户端（可能带 ``response_format``）。
            messages: 请求消息。
            model: 模型名（仅用于日志）。
            on_text: 文本增量回调。

        Returns:
            ``(完整文本, 输入 token, 输出 token)``。
        """
        chunks: list[str] = []
        meta: dict[str, Any] = {}
        for chunk in runnable.stream(messages, stream_usage=True):
            content = chunk.content
            if isinstance(content, list):  # 多模态分片，拼成纯文本
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            text = str(content) if content else ""
            if text:
                chunks.append(text)
                on_text(text)
            # 末块才带用量；中途出现也一并记下（有些供应商每个块都带）
            usage = getattr(chunk, "usage_metadata", None) or {}
            if usage:
                meta = dict(usage)
        full = "".join(chunks)
        token_in = int(meta.get("input_tokens", 0) or 0) or self.count_tokens(
            _flatten(messages)
        )
        token_out = int(meta.get("output_tokens", 0) or 0) or self.count_tokens(full)
        logger.debug(
            "LLM 流式调用完成 model=%s 块数=%d in=%d out=%d",
            model,
            len(chunks),
            token_in,
            token_out,
        )
        return full, token_in, token_out

    def _call(
        self,
        messages: list[BaseMessage],
        model: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """带重试与降级的调用：json_mode 不被支持时自动退化为纯文本模式。

        Args:
            on_text: 文本增量回调；给了就走流式。**重试时会静默停发**（见下面
                ``attempts`` 那条注释），否则断流重试会把同一段答案发两遍。
        """
        #: 重试去重闸门：``on_text`` 只在**第一次**尝试里放行。
        #: 流式跑到一半网络断了，第一批增量已经发给前端了；tenacity 重跑一次，
        #: 第二次再逐块回调一次，前端拼出来的就是「半段 + 整段」。
        #: 所以第二次及以后只管拿全文（终值仍会正常落到 ``last_usage`` 与返回值）。
        attempts = 0

        def _sink(chunk: str) -> None:
            if attempts > 1 or on_text is None:
                return
            on_text(chunk)

        def _run(use_json_mode: bool) -> tuple[str, int, int]:
            def _once() -> tuple[str, int, int]:
                nonlocal attempts
                attempts += 1
                return self._invoke_once(
                    messages,
                    model,
                    json_mode=use_json_mode,
                    temperature=temperature,
                    on_text=_sink,
                )

            fn = retry(
                reraise=True,
                stop=stop_after_attempt(max(1, self.settings.llm_max_retries)),
                wait=wait_exponential_jitter(initial=1, max=20),
                retry=retry_if_exception(is_retryable),
            )(_once)
            return fn()

        started = time.perf_counter()
        try:
            text, token_in, token_out = _run(json_mode)
        except Exception as exc:  # 需要判断是否为「不支持 json_object」，故显式兜底
            # 先把重试无用的错误（余额/鉴权）翻译成带可执行提示的异常：
            # 这类错误既不该降级 json 模式，也不该被当成「模型能力问题」。
            _raise_if_non_retryable(exc)
            if not (json_mode and _looks_like_json_mode_rejection(exc)):
                raise
            logger.warning("模型 %s 不支持 response_format=json_object，降级为纯文本模式", model)
            try:
                text, token_in, token_out = _run(False)
            except Exception as retry_exc:
                _raise_if_non_retryable(retry_exc)
                raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        # ★ 时钟只读**一次**：单价表是高峰价，这里按「实际调用时刻」套用时段系数
        # （低谷 = 高峰的一半）。同一次调用跨了 12:00 / 18:00 边界时，读两次会让
        # ``cost`` 用 A 档、``multiplier`` 记 B 档 —— 两份账自相矛盾且不报错。
        # ⚠️ 峰谷是 **DeepSeek 一家的**计费规则，:func:`core.llm.runtime.effective_multiplier`
        # 对不分峰谷的家返回 1.0 —— 把 0.5 套到智谱/千问头上，账会在每天 12:00 之后
        # 系统性少一半，而且看起来完全正常（这是换供应商时最容易漏的一处）。
        mult = runtime.effective_multiplier(model, self.settings)
        self.last_usage = Usage(
            model=model,
            token_in=token_in,
            token_out=token_out,
            cost=self.estimate_cost(token_in, token_out, model=model, multiplier=mult),
            multiplier=mult,
            duration_ms=duration_ms,
        )
        logger.debug(
            "LLM 调用完成 model=%s in=%d out=%d cost=%.6f %dms",
            model,
            token_in,
            token_out,
            self.last_usage.cost,
            duration_ms,
        )
        return text

    # ------------------------------------------------------------ 公开 API --
    def invoke(
        self,
        messages: Sequence[MessageLike],
        model: str | None = None,
        *,
        temperature: float | None = None,
    ) -> str:
        """普通文本调用，返回模型输出的纯文本。

        Args:
            messages: 消息列表，支持 ``{"role": "user", "content": "..."}`` 或 LangChain 消息对象。
            model: 模型名，默认使用 ``settings.llm_model_large``。
            temperature: 临时覆盖采样温度。
        """
        return self._call(
            to_messages(messages),
            model or self.settings.llm_model_large,
            temperature=temperature,
        )

    def invoke_json(
        self,
        messages: Sequence[MessageLike],
        schema: type[BaseModel] | Mapping[str, Any],
        model: str | None = None,
        *,
        max_attempts: int = 2,
        on_text: Callable[[str], None] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """要求模型输出 JSON，并保证返回值通过 ``schema`` 校验。

        失败路径：抽取失败或校验失败时，把错误信息作为新的 user 消息回灌，
        最多重试 ``max_attempts`` 次；仍失败则抛 ``LLMJsonError``。

        Args:
            schema: Pydantic 模型类（推荐），或 JSON Schema 字典
                （传 ``{"type": "array", ...}`` 时返回 list）。
            max_attempts: 含首次在内总尝试次数。
            on_text: 文本增量回调（流式）。**只有第一轮**会回调：JSON 校验失败
                回灌重问的那几轮再回调一次，前端就会看到两段答案前后拼接。
                这一层不负责"从 JSON 里挑出某个字段"——那是调用方的事
                （``core.agent.delta.JsonFieldDelta``），因为只有调用方知道
                哪个字段是给用户看的正文。

        Returns:
            校验通过的数据：Pydantic 模型返回 dict，JSON Schema 原样返回 dict / list。
        """
        history = [
            *to_messages(messages),
            SystemMessage(
                content=(
                    "你必须只输出一个合法 JSON，不要包含 markdown 代码块、解释或多余文字。\n"
                    + _schema_hint(schema)
                )
            )
        ]
        model_name = model or self.settings.llm_model_large
        last_error: Exception | None = None
        last_text = ""

        for attempt in range(1, max(1, max_attempts) + 1):
            # 只有第一轮吐增量：回灌重问的那一轮同样会生成一整份 JSON，再吐一遍
            # 就是把同一段正文发两次（前端是 append 语义，拼出来会重复）。
            last_text = self._call(
                list(history),
                model_name,
                json_mode=True,
                on_text=on_text if attempt == 1 else None,
            )
            try:
                return _validate(schema, extract_json(last_text))
            except (LLMJsonError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning("第 %d/%d 次 JSON 解析失败：%s", attempt, max_attempts, exc)
                history.extend(
                    [
                        AIMessage(content=last_text[:2000]),
                        HumanMessage(
                            content=(
                                f"上面的输出无法通过校验：{exc}\n"
                                "请只重新输出修正后的 JSON，不要任何解释文字。"
                            )
                        ),
                    ]
                )

        raise LLMJsonError(
            f"连续 {max_attempts} 次未获得合法 JSON：{last_error}",
            raw_text=last_text[:500],
            attempts=max_attempts,
        )

    def invoke_model(
        self,
        messages: Sequence[MessageLike],
        model_cls: type[TModel],
        *,
        model: str | None = None,
        max_attempts: int = 2,
        on_text: Callable[[str], None] | None = None,
    ) -> TModel:
        """``invoke_json`` 的强类型版本，直接返回 Pydantic 模型实例。

        Args:
            on_text: 文本增量回调；透传给 :meth:`invoke_json`。
        """
        data = self.invoke_json(
            messages, model_cls, model=model, max_attempts=max_attempts, on_text=on_text
        )
        return model_cls.model_validate(data)

    # ------------------------------------------------------------- 计量 --
    def count_tokens(self, text: str) -> int:
        """估算 token 数。

        优先使用 ``tiktoken``（若已安装，按 cl100k_base 近似）；
        否则退化为「中日韩字符 ×0.6 + 其他字符 ÷3.5」的经验公式。
        真正的精确计数只能由供应商的 tokenizer 给出，这里用于成本估算与预算控制。
        """
        if not text:
            return 0
        try:  # pragma: no cover - 取决于是否额外安装 tiktoken
            import tiktoken

            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:  # noqa: BLE001 - 未安装或下载词表失败都走经验公式
            cjk = len(_CJK_RE.findall(text))
            other = len(text) - cjk
            return max(1, int(cjk * 0.6 + other / 3.5))

    def estimate_cost(
        self,
        token_in: int,
        token_out: int,
        model: str | None = None,
        *,
        multiplier: float = 1.0,
    ) -> float:
        """按模型单价估算成本（人民币元）。

        **单位口径全项目统一为「元 / 100 万 token」**：``MODEL_PRICES`` 的取值、
        ``Settings.llm_price_in/out`` 的兜底值、以及下面 ``token / 1_000_000 × 单价``
        这条公式三者必须同单位 —— 它们不一致时不会报错，只会把成本悄悄算错 10⁶ 倍
        （这条用例钉在 tests/unit/test_adapter_json.py）。

        单价顺序：注册表精确匹配 → 最长前缀匹配 → ``Settings`` 兜底单价。

        ``MODEL_PRICES`` / 注册表里存的是**高峰价**；``multiplier`` 用来套用计费时段系数
        （低谷 0.5，见 :mod:`core.llm.pricing`；不分峰谷的家由
        :func:`core.llm.runtime.effective_multiplier` 给 1.0）。默认 1.0 保持纯函数语义，
        便于测试；实际调用由 :meth:`_call` 传入当前时段系数。

        ⚠️ 阶梯计价（智谱、千问按**输入**长度分档）在这里是**按本次的 ``token_in``
        选档**的，所以记账与 ``GET /models`` 报的可能是不同档 —— 那是对的：
        注册表在"不知道多长"时按最低档报，记账知道多长就按真正那一档算。

        这里刻意**只做浮点噪声收敛，不做金额取整**：一次短调用约 0.006 元
        （1k in / 500 out 在默认单价下实测 0.00639），而成本要跨多轮迭代、多个角色
        累加，再乘时段系数——在本层截断会把小额抹平，累计对账与预算控制就失真了。
        展示层（报告 / 页面）需要固定小数位时自行格式化，不在这里提前截断精度。

        Returns:
            估算成本（人民币元），保留 10 位小数以消除浮点尾差。
        """
        name = model or self.settings.llm_model_large
        price_in, price_out, _source = resolve_price(name, self.settings, token_in)
        cost = token_in / 1_000_000 * price_in + token_out / 1_000_000 * price_out
        return round(cost * multiplier, _COST_PRECISION_DIGITS)

    # ------------------------------------------------------------- 诊断 --
    def describe(self) -> dict[str, Any]:
        """输出当前适配器的可读配置，用于自检与调试（Key 已脱敏）。

        ⚠️ 报的是**这一趟真正会用到的**端点与 Key（:func:`core.llm.runtime.route`），
        不是 ``.env`` 里写着的那一套：换过供应商之后还打印 ``llm_base_url``，
        自检就会指着旧网关说"这就是现在打的地方" —— 那种日志除了把人往错的方向带上，
        什么都没有（``GET /models`` 与这里必须同源，见 ``api/routes/models.py``）。
        """
        large = runtime.route(self.settings.llm_model_large, self.settings)
        small = runtime.route(self.settings.llm_model_small, self.settings)
        override = runtime.current()
        return {
            "provider": large.provider,
            "base_url": large.base_url,
            "api_key": large.key_masked,
            "model_large": self.settings.llm_model_large,
            "model_small": self.settings.llm_model_small,
            "model_large_provider": large.provider_display,
            "model_large_endpoint": large.endpoint_source,
            "model_small_base_url": small.base_url,
            "model_small_api_key": small.key_masked,
            "overridden": override is not None,
            "temperature": self.temperature,
            "json_mode": self.settings.llm_json_mode,
            "timeout": self.settings.llm_timeout,
            "max_retries": self.settings.llm_max_retries,
        }


def _flatten(messages: Sequence[BaseMessage]) -> str:
    """把消息列表压成一段文本，用于 token 粗估。"""
    parts: list[str] = []
    for msg in messages:
        content = msg.content
        parts.append(content if isinstance(content, str) else str(content))
    return "\n".join(parts)


def _raise_if_non_retryable(exc: BaseException) -> None:
    """把「重试无用」的底层异常翻译成带可执行提示的 :class:`LLMNotRetryableError`。"""
    status = _status_code_of(exc)
    if status is None or status not in NON_RETRYABLE_STATUS:
        return
    hint = STATUS_HINTS.get(status, "该错误重试无用")
    raise LLMNotRetryableError(f"LLM 调用失败（HTTP {status}）：{hint}") from exc


def text_reports_non_retryable(text: str) -> bool:
    """判断一段**失败文本**里是否含「重试无用」的错误标记。

    为什么要按文本匹配：节点包装层（``core.agent.base.NodeWrapper.__call__``）会把异常
    转成失败状态并只保留 ``类名: 消息``，异常对象本身不会传到编排层。所以批处理只能
    从状态文本里认这个标记——用它来决定「整批立刻停下」而不是把 50 条挨个白跑。
    """
    return LLMNotRetryableError.__name__ in text or "重试无用" in text


def _looks_like_json_mode_rejection(exc: BaseException) -> bool:
    """判断异常是否**真的**由「模型不支持 response_format=json_object」引起。

    这里有两个踩过的坑：

    1. **不能拿 ``invalid_request_error`` 当标志**：DeepSeek 连 402 余额不足的响应体里
       ``code`` 字段都是它，于是计费错误被误诊成「json 模式不支持」，日志把人往错方向带；
    2. **鉴权/计费/资源类状态码与 json 模式无关**，直接判否（400 除外，参数类错误可能就是它）。
    """
    status = _status_code_of(exc)
    if status is not None and status in NON_RETRYABLE_STATUS and status != 400:
        return False
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "response_format",
        "json_object",
        "json mode",
        "unsupported",
        "not supported",
    )
    return any(marker in text for marker in markers)


@lru_cache(maxsize=4)
def get_adapter(
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> LLMAdapter:
    """获取进程级复用的适配器实例。"""
    return LLMAdapter(temperature=temperature, max_tokens=max_tokens)


def reset_adapters() -> None:
    """清空适配器缓存，供测试在切换配置后重建。"""
    get_adapter.cache_clear()


__all__ = [
    "MODEL_PRICES",
    "RETRYABLE_ERRORS",
    "LLMAdapter",
    "LLMError",
    "LLMJsonError",
    "Usage",
    "extract_json",
    "get_adapter",
    "reset_adapters",
    "to_messages",
]
