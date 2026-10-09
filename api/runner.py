"""把一条队列任务装配成可运行的 :class:`WorkflowRunner`，并处理终态落库。

两个「为什么这么做」的关键点
----------------------------

**1. 每个任务新建一个 ``LLMAdapter``**（设计文档 §8.5）

``core.llm.adapter.get_adapter()`` 是 ``lru_cache`` 单例，而 ``LLMAdapter.last_usage``
是**实例可变字段**，``BaseNode._emit_trace`` 靠 ``getattr(self.llm, "last_usage")``
读它来记 token / 成本。单线程没问题，但 M1 有最多 3 个 worker 线程：
A 任务的节点可能读到 B 任务的 ``last_usage``，成本与 trace 全串号。
所以这里**不用单例**，每任务 new 一个。代价是每任务新建一个 ``ChatOpenAI``
（毫秒级），相对秒级的任务耗时可忽略。

**2. 终态落库走 CAS 而不是 upsert**

:func:`persist_terminal` 内部调 ``Database.mark_terminal``（单条
``UPDATE ... WHERE status='running'``）。若返回 ``False``，说明任务在此期间被
取消了，本次结果**必须丢弃**——绝不能让 ``done`` 覆盖 ``canceled``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from api.constants import (
    MAX_UPDATE_CHARS,
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
)
from config import Settings, get_settings
from core.agent.base import NodeContext
from core.agent.delta import sanitize_surrogates, sanitize_surrogates_deep
from core.events import DatabaseEventSink, TaskEventSink, get_task_streams
from core.llm.adapter import LLMAdapter, resolve_price
from core.llm.pricing import OFF_PEAK_MULTIPLIER, price_multiplier
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry
from core.workflow.graph import WorkflowRunner
from core.workflow.state import WorkflowConfig
from evaluation.metrics import TaskOutcome
from evaluation.trace import TraceStore
from storage.db import Database

if TYPE_CHECKING:  # pragma: no cover - 只用于类型标注，避免 api.queue ↔ api.runner 循环导入
    from api.queue import QueueItem

logger = logging.getLogger(__name__)

#: 任务 → 编排器 的构造签名。测试可以整体替换成 Mock 版本（不消耗真实 token）。
RunnerFactory = Callable[["QueueItem"], WorkflowRunner]

#: ``use_tools=False`` 时装配的**默认安全子集**（缺陷 A 修复）。
#:
#: 语义修正：``use_tools=False`` 的用户意图是「不要开高危的 code_exec / file_io」，
#: 而**不是**「一个工具都不要」。旧实现把它当布尔开关一刀切地清空工具清单，
#: 导致 Agent 连只读的 ``knowledge_search`` 都用不了，最终 ``status=aborted``。
#: 这里改为「低风险工具白名单」，排除会执行代码 / 写文件的高危工具。
#:
#: 顺序即提示词里的展示顺序，与 ``core.tools.builtin.BUILTIN_REGISTRARS`` 对齐。
SAFE_TOOL_SUBSET: tuple[str, ...] = (
    "calculator",
    "knowledge_search",
)

#: 全部内置工具名（``use_tools`` 为 ``None`` / ``True`` 时装配）。
#: 与 :data:`core.tools.builtin.BUILTIN_REGISTRARS` 收敛后的 3 个工具一致。
ALL_TOOL_NAMES: tuple[str, ...] = (
    "calculator",
    "knowledge_search",
    "code_exec",
)


def resolve_tool_names(item: "QueueItem") -> tuple[str, ...]:
    """把 ``use_tools`` / ``enabled_tools`` 解析成要装配的工具名列表（缺陷 A）。

    三态语义（**向后兼容**，这是本函数存在唯一理由）：

    * ``enabled_tools`` 非空列表 → **精确装配**该列表（最高优先级；非法名已由
      ``api.schemas.TaskSubmitRequest`` 的校验器拦在 422，这里再兜一层过滤）。
    * ``use_tools is None`` → 现状行为（**全量装配**；不传 ``use_tools`` 同义）。
    * ``use_tools is True`` → 全量装配。
    * ``use_tools is False`` → 装配 :data:`SAFE_TOOL_SUBSET`（低风险子集），
      **不再**「零工具」。

    Args:
        item: 队列任务。

    Returns:
        待装配的工具名元组（已按内置顺序归一、去重、过滤未知名）。
    """
    enabled = getattr(item, "enabled_tools", None)
    if enabled:
        wanted = {str(name).strip() for name in enabled if str(name).strip()}
        return tuple(name for name in ALL_TOOL_NAMES if name in wanted)

    if item.use_tools is False:
        return SAFE_TOOL_SUBSET
    return ALL_TOOL_NAMES


def build_runner(
    item: "QueueItem",
    *,
    settings: Settings,
    trace_store: TraceStore,
    llm: LLMAdapter | None = None,
    database: Database | None = None,
) -> WorkflowRunner:
    """为单个任务装配编排器（每任务全新实例，不共享任何可变对象）。

    Args:
        item: 队列任务。
        settings: 全局配置。
        trace_store: 埋点出口。
        llm: 注入的适配器（测试用 Mock）；不传则**新建**一个真实适配器。
        database: 数据库门面；传入时会向 :class:`NodeContext` 注入
            ``DatabaseEventSink``，使节点内的 LLM / 工具事件**先落盘再返回**
            （设计文档 §7.2/§7.3、K2）。测试不传时不埋事件，保持既有行为。

    Returns:
        已编译好图的编排器。
    """
    config = WorkflowConfig.from_settings(settings).model_copy(
        update={
            "max_iterations": item.max_iterations,
            "review_threshold": item.review_threshold,
        }
    )
    tool_invoker: ToolRegistry | None = None
    tool_names = resolve_tool_names(item)
    if tool_names:
        # 每任务一份注册表：默认注册的那 3 个工具（``BUILTIN_REGISTRARS``：
        # calculator / knowledge_search / code_exec）都是无状态函数（knowledge_search 的
        # 服务是进程内单例，经模块级注入共享），重建成本可忽略，
        # 换来的是「不共享可变对象」这一确定性。
        registry = ToolRegistry(settings=settings, enable_hitl=settings.enable_hitl)
        load_builtin_tools(registry)
        _inject_knowledge_service(registry)
        tool_invoker = _restrict_tools(registry, tool_names)

    event_sink: TaskEventSink | None = (
        DatabaseEventSink(database) if database is not None else None
    )
    #: 实时出口（SSE ``delta`` / ``usage``）从 **contextvar** 里取，不从参数传：
    #: ``RunnerFactory`` 的签名是 ``(item) -> WorkflowRunner``，被集成测试用单参
    #: lambda 顶替过，加必填参数会直接 TypeError。contextvar 由 ``api/queue.py``
    #: 的 worker 在**本任务**的同步调用栈里设好（与 ``set_task_top_k`` 同源），
    #: 装配发生在这条栈里 ⇒ 这里读到的必然是本任务那一组出口。
    streams = get_task_streams()
    adapter = llm if llm is not None else LLMAdapter(settings=settings)
    ctx = NodeContext.create(
        settings=settings,
        config=config,
        trace_sink=trace_store,
        tool_invoker=tool_invoker,
        llm=adapter,
        event_sink=event_sink,
        answer_stream=streams.answer if streams is not None else None,
        usage_sink=streams.usage if streams is not None else None,
    )
    return WorkflowRunner(ctx)


def _restrict_tools(registry: ToolRegistry, tool_names: Sequence[str]) -> ToolRegistry:
    """把注册表裁剪成 ``tool_names`` 白名单（就地去重、按内置顺序）。

    内置注册表是「全量装载后裁剪」而不是「按名逐个注册」：``load_builtin_tools``
    是一把梭的注册器集合，逐名注册会与其顺序契约打架。裁剪后注册表的
    ``describe()`` 只暴露白名单工具，模型便只能从白名单里选。

    Args:
        registry: 已装载全部内置工具的注册表。
        tool_names: 保留的工具名（顺序即展示顺序）。

    Returns:
        同一个注册表实例（裁剪后），便于链式使用。
    """
    keep = {str(name).strip() for name in tool_names if str(name).strip()}
    registry.restrict_to(keep)
    return registry


def _inject_knowledge_service(registry: ToolRegistry) -> None:
    """给 ``knowledge_search`` 注入知识库服务（T04 子步骤 4；rag 不可用静默跳过）。

    刻意**函数体内** import ``api.deps``：本模块被 ``api.deps`` 顶层引用，
    模块级反向 import 会形成循环；运行时（首次任务装配）两边都已加载完毕，
    函数内 import 无风险。
    """
    if not registry.has("knowledge_search"):
        return
    try:
        from api.deps import get_knowledge_service  # noqa: PLC0415 - 避免循环导入

        service = get_knowledge_service()
    except Exception:  # noqa: BLE001 - 注入失败不阻断任务装配
        logger.warning("knowledge_search 服务注入失败（知识库降级）", exc_info=True)
        return
    if service is None:
        return
    from core.tools.builtin import knowledge_search  # noqa: PLC0415 - 懒加载纪律

    knowledge_search.set_knowledge_service(service)


def default_runner_factory(
    settings: Settings,
    trace_store: TraceStore,
    database: Database | None = None,
) -> RunnerFactory:
    """造一个「每任务新建适配器」的工厂（生产环境用）。

    ``database`` 为 ``None`` 时**懒取** ``api.deps.get_database()``（进程内单例），
    使节点内的 LLM / 工具事件经 ``DatabaseEventSink`` 落 ``task_events``
    （T02 埋点，设计文档 §7.2/§7.3）。懒取而不是要求调用方显式传入，有两个理由：

    1. **不破坏既有测试约定**：``tests/integration/conftest.py`` 用
       ``lambda _s, _t: ...`` 两参替换本函数，多一个必填参数会直接 TypeError；
    2. **避免循环导入**：``api.deps`` 顶层 import 本模块，只能函数内 import 回去。

    懒取失败（如未初始化）时退化为「不埋事件」，绝不阻断任务装配。

    Args:
        settings: 全局配置。
        trace_store: 埋点出口。
        database: 数据库门面；不传则懒取 ``api.deps.get_database()``。

    Returns:
        满足 :data:`RunnerFactory` 的可调用对象。
    """

    def factory(item: "QueueItem") -> WorkflowRunner:
        resolved_db = database if database is not None else _lazy_database()
        return build_runner(
            item, settings=settings, trace_store=trace_store, database=resolved_db
        )

    return factory


def _lazy_database() -> Database | None:
    """懒取进程内 ``Database`` 单例（供事件落盘）；失败返回 ``None``。"""
    try:
        from api.deps import get_database  # noqa: PLC0415 - 避免 api.runner ↔ api.deps 循环导入

        return get_database()
    except Exception:  # noqa: BLE001 - 拿不到库不该阻断任务装配
        logger.warning("事件落盘所需的 Database 懒取失败（本次任务不埋事件）", exc_info=True)
        return None


def sanitize_update(update: Mapping[str, Any], limit: int = MAX_UPDATE_CHARS) -> dict[str, Any]:
    """清洗节点增量：剔 ``messages``、截断长字符串。

    剔 ``messages`` 有两个理由（这条口径原先与 ``ui/pages/2_workflow_test.py`` 一致，
    那一页连同 ``ui/`` 已在 2026-09-27 删除，规则本身不变）：
    LangChain 消息对象**不可 JSON 序列化**，而且体积可达数十 KB——
    一帧几 MB 会把 SSE 连接压垮。

    Args:
        update: 节点返回的状态增量；**可能是 ``None``**——LangGraph 在
            ``stream_mode="updates"`` 下，节点失败（``BaseNode`` 兜住异常转成
            ``status="failed"``）或条件边路由等场景会 yield 出空增量，
            实测（M1 冒烟，无 Key 场景）确认会出现 ``None``。
        limit: 字符串值的截断长度。

    Returns:
        可安全 JSON 序列化的副本；入参为 ``None`` 时返回空字典。
    """
    if not update:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in update.items():
        if key == "messages":
            continue
        if isinstance(value, str) and len(value) > limit:
            cleaned[key] = value[:limit] + "…（已截断）"
        else:
            cleaned[key] = value
    # Q6-02：这一份是 SSE ``node`` 帧的载荷，而帧用 ``ensure_ascii=False`` 序列化 ——
    # 模型 JSON 里一个未配对代理码点（``json.loads('"\\ud83d"')`` 不报错）就会让
    # ``.encode('utf-8')`` 抛 UnicodeEncodeError，那一帧发不出去、整条流断掉。
    # 流式抽取器（JsonFieldDelta）只护住了 delta 那一条出口，这条走的是全文解析结果。
    return sanitize_surrogates_deep(cleaned)


def classify_error(state: Mapping[str, Any]) -> tuple[str, str]:
    """从最终状态里判定失败原因，返回 ``(error_code, message)``。

    判定依据是 ``review_comment`` / ``final_answer`` 里的文本：节点包装层
    （``BaseNode.__call__``）会把异常转成失败增量并只保留 ``类名: 消息``，
    异常对象本身传不到编排层，所以只能从文本认这个标记。

    Args:
        state: 已收集的状态（``collected``）。

    Returns:
        二元组。不可重试的 LLM 错误 → ``llm_not_retryable``，否则 ``node_failed``。
    """
    from core.llm.adapter import text_reports_non_retryable

    comment = str(state.get("review_comment") or "").strip()
    answer = str(state.get("final_answer") or "").strip()
    blob = f"{comment}\n{answer}"
    message = comment.splitlines()[0] if comment else (answer.splitlines()[0] if answer else "")
    if text_reports_non_retryable(blob):
        return "llm_not_retryable", message[:500] or "LLM 调用失败且重试无用"
    return "node_failed", message[:500] or "节点执行失败"


def estimate_cost_cny(
    task: str,
    max_iterations: int,
    settings: Settings | None = None,
) -> float:
    """粗估一条任务的成本（元）。

    公式（设计文档 §7.7）：

    * ``est_in  ≈ 任务字符数 / 1.6 × (2 + max_iterations × 2)``
    * ``est_out ≈ 800 × (1 + max_iterations)``
    * ``cost = (est_in/1e6 × price_in + est_out/1e6 × price_out) × price_multiplier()``

    **这是粗估，误差可能 3-5 倍，不得用于计费**（设计文档 §9 R14）。
    字段名带 ``estimated`` 就是为了提醒调用方。

    单价走 :func:`~core.llm.adapter.resolve_price`，与 ``LLMAdapter.estimate_cost``、
    ``GET /models`` **同一个函数**：早先这里直接读 ``settings.llm_price_in/out``，
    于是本机 .env 填了 2.0/8.0 时，提交前显示的预估价和注册表里标着的 2.13/8.52
    差 6%，而实际记账用的是后者。预估可以粗，单价不能是第二个数。

    取的是强模型档（``llm_model_large``）的价 —— 与 ``estimate_cost`` 未传 model 时
    的默认口径一致；executor/extract 走便宜的快模型，所以这个预估**偏高**，
    对「仅供量级参考」的字段是安全方向。

    Args:
        task: 任务文本。
        max_iterations: 迭代上限。
        settings: 全局配置；不传取单例。

    Returns:
        保留 6 位小数的成本估算。
    """
    resolved = settings or get_settings()
    price_in, price_out, _source = resolve_price(resolved.llm_model_large, resolved)
    est_in = max(len(task) / 1.6, 1.0) * (2 + max_iterations * 2)
    est_out = 800.0 * (1 + max_iterations)
    raw = (est_in / 1_000_000 * price_in + est_out / 1_000_000 * price_out) * price_multiplier()
    return round(raw, 6)


def price_multiplier_relative() -> float:
    """相对低谷的倍数：高峰 ``2.0``、低谷 ``1.0``。

    单一真源：由 ``pricing.price_multiplier()``（1.0 / 0.5）除以
    ``OFF_PEAK_MULTIPLIER`` 推导，API 层**不自己**实现高峰判定。
    """
    return round(price_multiplier() / OFF_PEAK_MULTIPLIER, 4)


def _judge_criteria(state: Mapping[str, Any], task: str) -> list[str]:
    """从状态里凑出 judge 的验收标准。

    M1 的 ``POST /tasks`` 不接受显式 criteria，所以退化方案是：
    planner 拆出的计划步骤就是最好的验收标准；planner 没产出时，
    用任务原文当唯一一条标准（``LLMJudge`` 要求 criteria 非空）。
    """
    plan = state.get("plan") or []
    criteria = [str(item).strip() for item in plan if str(item).strip()]
    if criteria:
        return criteria
    return [str(task).strip() or "给出可用的回答"]


def persist_terminal(
    item: "QueueItem",
    collected: Mapping[str, Any],
    *,
    database: Database,
    trace_store: TraceStore,
    run_judge: bool,
    settings: Settings,
) -> str:
    """把任务的终态写进 ``tasks`` 表。

    Args:
        item: 队列任务。
        collected: 编排过程中累计的状态（已剔除 ``messages``）。
        database: 数据库门面。
        trace_store: 埋点出口（取本任务的 trace 用）。
        run_judge: 是否跑一次 LLM judge（默认 false，省一轮成本）。
        settings: 全局配置。

    Returns:
        期望落库的终态字符串（``done`` / ``aborted`` / ``failed``）。
        注意：返回**不代表落库成功**——CAS 可能失败（任务被取消），
        调用方需要另看 :meth:`Database.mark_terminal` 的返回值。
    """
    records = trace_store.for_task(item.task_id)
    outcome = TaskOutcome.from_state(collected, records)

    # 单一出口的终态判定（缺陷 B）：status 由「有无可交付答案」+「是否异常中断」
    # 共同决定，而不是单纯由「是否达到最大迭代」决定。
    status, error_code, error_message = decide_terminal_status(collected)

    score: int | None = None
    grade: str | None = None
    if run_judge:
        score, grade = _run_judge(
            item, collected, records, outcome.status, settings, database=database
        )
    else:
        # 不跑 judge 时沿用评审分（页面与批量评测看板就是这么展示的）
        review_score = collected.get("review_score")
        score = int(review_score) if isinstance(review_score, (int, float)) else None

    applied = database.mark_terminal(
        item.task_id,
        status=status,
        iterations=outcome.iterations,
        score=score,
        grade=grade,
        # Q6-02：SQLite 写 TEXT 也按 UTF-8 编码，孤立代理同样抛 UnicodeEncodeError ——
        # 那条路会被 worker 的兜底吃成"任务 failed 且答案与账整份丢"，比断流更贵。
        final_answer=sanitize_surrogates(str(collected.get("final_answer") or ""))[:50_000],
        cost=outcome.cost,
        duration_ms=outcome.duration_ms,
        tool_calls=outcome.tool_calls,
        tool_failures=outcome.tool_failures,
        # 缺陷（§0.1-7）：失败终态必须带 error_code / error_message，
        # 否则 tasks.error_* 恒为 NULL，前端只能显示「任务失败（无详细信息）」。
        error_code=error_code,
        # 失败理由里会拼进模型吐出的文本（review_comment / 异常消息），同一道雷。
        error_message=None if error_message is None else sanitize_surrogates(error_message),
    )
    if not applied:
        logger.debug(
            "终态 CAS 失败（任务已被取消），丢弃结果 task_id=%s status=%s", item.task_id, status
        )
    else:
        logger.info(
            "任务落终态 task_id=%s status=%s iterations=%d cost=%.6f duration_ms=%d",
            item.task_id,
            status,
            outcome.iterations,
            outcome.cost,
            outcome.duration_ms,
        )
    return status


def decide_terminal_status(
    collected: Mapping[str, Any],
) -> tuple[str, str | None, str | None]:
    """**单一出口**的终态判定（缺陷 B）：返回 ``(status, error_code, error_message)``。

    旧实现有两处各算一次：``persist_terminal`` 按「是否达到最大迭代」定
    ``aborted``，而 ``final_answer`` 又照常落库 → 出现「``status=aborted`` 却带
    907 字完整答案 + score=3」的语义矛盾（前端因此显示互相打架的信息）。
    本函数把判定收敛成**唯一一处**，``persist_terminal`` 与事件埋点都调它。

    判定规则（「是否有可交付答案」∧「是否被取消 / 异常中断」）：

    1. ``collected.status == failed`` → ``failed`` + :func:`classify_error` 的错误码
       （LLM 不可重试错误 → ``llm_not_retryable``，否则 ``node_failed``）；
    2. ``collected.status == canceled`` → ``canceled`` + 固定错误码
       （任务被用户取消，非失败）；
    3. 其余情况（``done`` / ``aborted`` / ``running`` / 缺省）：
       - 有非空 ``final_answer`` → **``done``**（有可交付成果就是完成，
         即便 reviewer 曾打回或触达迭代上限——``aborted`` 不得再覆盖它）；
       - 无 ``final_answer`` → ``aborted``（真·没交付，且不是异常/取消）。

    Args:
        collected: 编排过程中累计的状态（已剔除 ``messages``）。

    Returns:
        三元组 ``(status, error_code, error_message)``；非失败态时后两者为 ``None``。
    """
    raw_status = str(collected.get("status") or "")
    answer = str(collected.get("final_answer") or "").strip()

    if raw_status == STATUS_FAILED:
        code, message = classify_error(collected)
        return STATUS_FAILED, code, message
    if raw_status == STATUS_CANCELED:
        return STATUS_CANCELED, "canceled_by_user", "任务被用户取消"
    if answer:
        return STATUS_DONE, None, None
    return STATUS_ABORTED, None, None


def _run_judge(
    item: "QueueItem",
    collected: Mapping[str, Any],
    records: Sequence[Any],
    status: str,
    settings: Settings,
    *,
    database: Database,
) -> tuple[int | None, str | None]:
    """跑一次 LLM judge；任何异常只记 WARNING，绝不影响任务终态。

    Args:
        database: 用于 ``save_eval_result``，显式传入而不是走全局单例，
            这样测试注入的临时库也能收到评测记录。

    Returns:
        ``(score, grade)``；未跑或失败时返回 ``(None, None)``。
    """
    try:
        from evaluation.judge import LLMJudge

        judge = LLMJudge(llm=LLMAdapter(settings=settings), settings=settings)
        result = judge.evaluate(
            task=item.task,
            criteria=_judge_criteria(collected, item.task),
            final_answer=str(collected.get("final_answer") or ""),
            task_id=item.task_id,
            records=records,
            status=status,
            iterations=int(collected.get("iteration", 0) or 0),
        )
        database.save_eval_result(result.model_dump())
        return int(result.score), str(result.grade)
    except Exception as exc:  # noqa: BLE001 - judge 是旁路，失败不能拖垮任务
        logger.warning("judge 评测失败（不影响任务终态）task_id=%s：%s", item.task_id, exc)
        return None, None


__all__ = [
    "ALL_TOOL_NAMES",
    "RunnerFactory",
    "SAFE_TOOL_SUBSET",
    "build_runner",
    "classify_error",
    "decide_terminal_status",
    "default_runner_factory",
    "estimate_cost_cny",
    "persist_terminal",
    "price_multiplier_relative",
    "resolve_tool_names",
    "sanitize_update",
]
