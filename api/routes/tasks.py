"""任务相关路由：提交、查询、取消、SSE 订阅。

**``async def`` 还是 ``def``（设计文档 §7.6，违反会直接导致队列状态错乱）**

===============================  ============  =====================================
路由                              定义方式      原因
===============================  ============  =====================================
``POST /tasks``                   async def     触碰 ``asyncio.Queue``
``POST /tasks/{id}/cancel``       async def     写 EventBus + CAS，且要发 SSE 事件
``GET /tasks/{id}/stream``        async def     长连接协程
``GET /tasks/{id}``               def           纯 DB 读，交给线程池不阻塞 loop
===============================  ============  =====================================

FastAPI 会把 ``def`` 路由丢进**线程池**执行；那时 ``asyncio.Queue`` / ``deque``
就不是单线程访问了，``queue_position`` 会忽大忽小，并发上限也会失效（R11）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from api.constants import (
    API_TERMINAL_STATUSES,
    EVT_HEARTBEAT,
    EVT_SNAPSHOT,
    EVENT_BY_STATUS,
    RETRY_AFTER_SECONDS,
    STATUS_CANCELED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TASK_ID_HEX_LEN,
    TASK_ID_PREFIX,
    TERMINAL_EVENTS,
    TRACE_DEFAULT_LIMIT,
    TRACE_MAX_LIMIT,
)
from api.deps import get_cache_facade, get_database, get_event_bus, get_task_queue
from api.errors import ApiError, ErrorCode
from api.events import StreamEvent, format_frame, format_retry_frame
from api.queue import QueueItem
from api.runner import estimate_cost_cny, price_multiplier_relative
from api.schemas import (
    CancelResponse,
    CostBreakdownResponse,
    CostReconcile,
    CostRoleRow,
    CostTotals,
    CostWindow,
    ErrorResponse,
    PriceCheck,
    TaskAcceptedResponse,
    TaskError,
    TaskEventView,
    TaskListResponse,
    TaskProgress,
    TaskQueueInfo,
    TaskSubmitRequest,
    TaskRunConfigView,
    TaskTraceResponse,
    TaskView,
    to_cn,
)
from config import get_settings
from core.llm import providers
from core.llm.adapter import resolve_price
from core.llm.pricing import (
    OFF_PEAK_MULTIPLIER,
    is_peak,
    next_off_peak,
    now,
    price_multiplier,
    window_description,
)
from storage.models import TaskEventRecord, TaskRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["tasks"])

#: ``GET /tasks`` 允许过滤的全部状态值（状态机的穷举，防止拼接错的查询白跑）
VALID_TASK_STATUSES: frozenset[str] = frozenset(
    {STATUS_QUEUED, STATUS_RUNNING, *API_TERMINAL_STATUSES}
)

#: ``GET /tasks/{id}/trace`` 允许的 ``role`` 过滤值（与 ``core.workflow.state.AgentRole``
#: 同值，本地声明以刻意避免 API 契约层耦合编排内核——同 ToolSpecView 的纪律）。
VALID_TRACE_ROLES: frozenset[str] = frozenset({"planner", "executor", "reviewer", "judge"})

#: 老任务无事件时的降级说明（设计文档 §6.2 / §5.3，必须是人话且指向结论数据出处）
_TRACE_UNAVAILABLE_REASON = (
    "该任务在事件持久化（P1-A）落地前执行，节点级轨迹不可追溯；"
    "结论数据请见 GET /tasks/{task_id}"
)

#: 取消接口的说明文案（已知限制 L1 必须让调用方看到）
_CANCEL_NOTE = (
    "取消将在下一个节点边界生效；当前节点已发出的 LLM 请求会跑完但结果被丢弃"
    "（最坏等待 llm_timeout × (1 + llm_max_retries) 才释放并发槽位）"
)


def _new_task_id() -> str:
    """生成服务端任务 id：``task-<12 位 hex>``。"""
    return f"{TASK_ID_PREFIX}{uuid4().hex[:TASK_ID_HEX_LEN]}"


def _build_warnings(settings_llm_configured: bool, peak: bool) -> list[str]:
    """拼受理提示（非致命，只是让调用方知情）。"""
    warnings: list[str] = []
    if peak:
        warnings.append(
            f"当前为高峰计费时段（{window_description()}），单价为低谷的 2 倍"
        )
    if not settings_llm_configured:
        warnings.append("未配置 LLM_API_KEY，任务大概率失败")
    return warnings


# --------------------------------------------------------------------------- #
# POST /tasks
# --------------------------------------------------------------------------- #
@router.post(
    "/tasks",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "task_id 已存在"},
        422: {"model": ErrorResponse, "description": "参数校验失败 / 高峰硬拦"},
        429: {"model": ErrorResponse, "description": "队列已满"},
    },
    summary="异步提交任务",
)
async def submit_task(body: TaskSubmitRequest) -> TaskAcceptedResponse:
    """受理一条任务并**立即**返回（不等待执行）。

    Args:
        body: 提交请求。

    Returns:
        201 受理响应，含 ``task_id`` 与轮询 / 订阅 / 取消三个地址。

    Raises:
        ApiError: 409（task_id 冲突）、422（高峰硬拦）、429（队列满）。
    """
    settings = get_settings()
    database = get_database()
    queue = get_task_queue()

    task_id = body.task_id or _new_task_id()
    if database.get_task(task_id) is not None:
        raise ApiError(
            ErrorCode.TASK_ID_CONFLICT,
            f"task_id 已存在：{task_id}",
            status=status.HTTP_409_CONFLICT,
        )

    max_iterations = body.max_iterations or settings.max_iterations
    review_threshold = (
        body.review_threshold if body.review_threshold is not None else settings.review_threshold
    )
    peak = is_peak()
    if settings.api_block_peak_tasks and peak:
        raise ApiError(
            ErrorCode.PEAK_BLOCKED,
            f"当前为高峰计费时段（{window_description()}），已开启 api_block_peak_tasks 硬拦",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    warnings = _build_warnings(settings.llm_configured, peak)
    cost_estimate = estimate_cost_cny(body.task, max_iterations, settings)

    # ① 先落一条 queued 记录：客户端拿到 task_id 后立刻能查到
    database.save_task(
        task_id=task_id,
        task=body.task,
        status=STATUS_QUEUED,
        difficulty=body.difficulty,
        iterations=0,
        score=None,
        grade=None,
        final_answer="",
        cost=0.0,
        duration_ms=0,
        tool_calls=0,
        tool_failures=0,
    )

    # ② 登记取消令牌 → 入队
    token = queue.register(task_id)
    item = QueueItem(
        task_id=task_id,
        task=body.task,
        max_iterations=max_iterations,
        review_threshold=review_threshold,
        # 三态语义（缺陷 A）：不传=None（全量）；true=全量；false=安全子集。
        use_tools=body.use_tools,
        enabled_tools=body.enabled_tools,
        run_judge=body.run_judge,
        difficulty=body.difficulty,
        submitted_at=time.time(),
        cancel=token,
        # —— 运行期闸门（U-3 / U-4）：None 一律表示"不设限"，不是 0 ——
        max_cost_cny=body.max_cost_cny,
        timeout_s=body.timeout_s,
        rag_top_k=body.rag_top_k,
    )
    try:
        position = await queue.submit(item)
    except ApiError as exc:
        # 队列满：把刚写的 queued 记录回滚成 canceled，避免留下一条永远没人跑的孤儿
        database.mark_canceled(task_id)
        queue.cancel_registry.pop(task_id)
        if exc.code is ErrorCode.QUEUE_FULL:
            exc.headers.setdefault("Retry-After", str(RETRY_AFTER_SECONDS))
        raise

    logger.info("任务受理完成 task_id=%s position=%d", task_id, position)
    return TaskAcceptedResponse(
        task_id=task_id,
        status="queued" if position >= 1 else "running",
        queue_position=position,
        submitted_at=now(),
        poll_url=f"/tasks/{task_id}",
        stream_url=f"/tasks/{task_id}/stream",
        cancel_url=f"/tasks/{task_id}/cancel",
        estimated_cost_cny=cost_estimate,
        peak_pricing=peak,
        price_multiplier=price_multiplier_relative(),
        warnings=warnings,
        # 回执：把**服务端真正收下**的那份原样报回去。界面显示"这条任务的预算"时
        # 读这里而不是自己刚发出去的字段 —— 老后端会静默丢掉新键（extra=ignore），
        # 那时这里回 null，界面就能说"这一条后端没收下"而不是继续显示用户填的数。
        run_config=TaskRunConfigView(
            max_iterations=max_iterations,
            review_threshold=review_threshold,
            max_cost_cny=body.max_cost_cny,
            timeout_s=body.timeout_s,
            rag_top_k=body.rag_top_k,
            use_tools=body.use_tools,
            enabled_tools=body.enabled_tools,
        ),
    )


# --------------------------------------------------------------------------- #
# GET /tasks（任务列表）
# --------------------------------------------------------------------------- #
@router.get(
    "/tasks",
    response_model=TaskListResponse,
    responses={422: {"model": ErrorResponse, "description": "status 含非法状态值"}},
    summary="任务列表（分页 + 状态过滤，updated_at 倒序）",
)
async def list_tasks(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="逗号分隔的状态过滤，如 running,queued；缺省返回全部状态",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="页大小（默认 50，上限 200）"),
    offset: int = Query(default=0, ge=0, description="跳过条数"),
) -> TaskListResponse:
    """分页列出任务，按 ``updated_at`` 倒序。

    **为什么是 ``async def``**：要合并队列内存态（运行中 / 排队中的实时视图），
    而 ``_running`` / ``_waiting`` 只允许在 loop 线程访问（设计文档 §7.6）；
    DB 分页查询则经 ``asyncio.to_thread`` 丢进线程池，不阻塞事件循环。

    Returns:
        当前页 ``items`` + 过滤后的 ``total``。
    """
    statuses: list[str] | None = None
    if status_filter:
        statuses = [item.strip().lower() for item in status_filter.split(",") if item.strip()]
        unknown = sorted(set(statuses) - VALID_TASK_STATUSES)
        if unknown:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                f"非法状态值：{'、'.join(unknown)}（合法值：{sorted(VALID_TASK_STATUSES)}）",
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    queue = get_task_queue()
    # 内存态只读快照：本协程就跑在 loop 线程，符合「仅 loop 线程访问」的约束
    running_ids = dict(queue.list_running_ids())
    queued_positions = dict(queue.list_queued_ids())
    logger.debug(
        "任务列表合并内存态 running=%d queued=%d", len(running_ids), len(queued_positions)
    )

    database = get_database()
    records, total = await asyncio.to_thread(
        lambda: database.list_tasks_page(statuses=statuses, limit=limit, offset=offset)
    )
    items = [_to_view(record) for record in records]
    return TaskListResponse(items=items, total=total, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}
# --------------------------------------------------------------------------- #
@router.get(
    "/tasks/{task_id}",
    response_model=TaskView,
    responses={404: {"model": ErrorResponse, "description": "任务不存在"}},
    summary="查询任务状态与结果",
)
def get_task(task_id: str) -> TaskView:
    """查一条任务（纯 DB 读 + 缓存读，用 ``def`` 交给线程池）。

    Args:
        task_id: 任务 id。

    Returns:
        任务视图。

    Raises:
        ApiError: 404 任务不存在。
    """
    database = get_database()
    record = database.get_task(task_id)
    if record is None:
        raise ApiError(
            ErrorCode.TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            status=status.HTTP_404_NOT_FOUND,
        )
    return _to_view(record)


def _to_view(record: TaskRecord) -> TaskView:
    """把 ORM 记录拼成响应模型。"""
    queue = get_task_queue()
    cache = get_cache_facade()
    terminal = record.status in API_TERMINAL_STATUSES

    progress: TaskProgress | None = None
    if not terminal:
        progress = _load_progress(record, cache)

    position = 0 if terminal else queue.queue_position(record.task_id)
    wait_seconds = 0.0
    if position > 0 and record.created_at is not None:
        created = record.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        wait_seconds = round((datetime.now(timezone.utc) - created).total_seconds(), 3)

    error: TaskError | None = None
    if record.status == "failed":
        error = TaskError(
            code=record.error_code or "node_failed",
            message=record.error_message or "任务失败（无详细信息）",
        )
    elif record.status == "canceled" and record.error_code:
        # 运行期闸门（预算 / 超时）中断的任务：状态是 canceled，但**不是用户取消的**。
        # 只填 failed 的话，这里就会显示成"已取消"，用户以为是自己点的取消 ——
        # 那是把"被策略停掉"说成"你自己停的"，比多一列错误严重得多。
        # 用户自己取消时那两列是 NULL（K3），所以这个分支不会误伤。
        error = TaskError(
            code=record.error_code,
            message=record.error_message or "任务被运行期限制中断",
        )

    return TaskView(
        task_id=record.task_id,
        task=record.task,
        status=record.status,
        iterations=record.iterations,
        score=record.score,
        grade=record.grade,
        final_answer=record.final_answer,
        cost=round(record.cost, 6),
        duration_ms=record.duration_ms,
        tool_calls=record.tool_calls,
        tool_failures=record.tool_failures,
        difficulty=record.difficulty,
        created_at=to_cn(record.created_at),
        updated_at=to_cn(record.updated_at),
        progress=progress,
        queue=TaskQueueInfo(position=position, wait_seconds=max(wait_seconds, 0.0)),
        error=error,
    )


def _load_progress(record: TaskRecord, cache: Any) -> TaskProgress:
    """读进度视图；缓存没有时按记录退化出一个最小视图（不报错）。"""
    cached = cache.load_progress(record.task_id)
    if isinstance(cached, dict):
        return TaskProgress(
            current_node=cached.get("current_node"),
            completed_nodes=list(cached.get("completed_nodes") or []),
            iteration=int(cached.get("iteration") or 0),
            max_iterations=int(cached.get("max_iterations") or get_settings().max_iterations),
            elapsed_ms=int(cached.get("elapsed_ms") or 0),
        )
    elapsed_ms = 0
    if record.created_at is not None:
        created = record.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed_ms = int((datetime.now(timezone.utc) - created).total_seconds() * 1000)
    return TaskProgress(
        current_node=None,
        completed_nodes=[],
        iteration=record.iterations,
        max_iterations=get_settings().max_iterations,
        elapsed_ms=max(elapsed_ms, 0),
    )


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}/trace
# --------------------------------------------------------------------------- #
@router.get(
    "/tasks/{task_id}/trace",
    response_model=TaskTraceResponse,
    responses={404: {"model": ErrorResponse, "description": "任务不存在"}},
    summary="查询任务的轨迹事件（event_seq 游标分页，只读）",
)
def get_task_trace(
    task_id: str,
    after_seq: int = Query(
        default=0, ge=0, description="event_seq 游标；返回严格大于此值的事件（禁止 OFFSET）"
    ),
    limit: int = Query(
        default=TRACE_DEFAULT_LIMIT,
        ge=1,
        le=TRACE_MAX_LIMIT,
        description=f"页大小 1..{TRACE_MAX_LIMIT}（默认 {TRACE_DEFAULT_LIMIT}）",
    ),
    role: str | None = Query(
        default=None,
        description="可选角色过滤：planner/executor/reviewer/judge",
    ),
) -> TaskTraceResponse:
    """按 ``event_seq`` 游标回放一条任务的轨迹事件（纯 DB 读，用 ``def``）。

    **为什么是 ``def``**（设计文档 §6.1 / K4 与 ``routes/tasks.py`` 顶部纪律）：
    只有 ``POST /tasks``、``POST /tasks/{id}/cancel``、``GET /tasks/{id}/stream``
    三个触碰 ``asyncio.Queue`` / 长连接的路由用 ``async def``；本路由是纯 DB 读，
    交给线程池执行，**不得用 ``async def``**（否则阻塞事件循环）。

    **老任务兼容**（设计文档 §5.3，核心验收点）：``task_events`` 是新表，历史任务
    无事件。请求「存在但无事件」的任务返回 **200 + ``events_available=false``**
    （而非 404 / 500）——「任务存在但无轨迹」与「任务不存在」是两种事实。
    仅当 ``task_id`` 在 ``tasks`` 表都查不到时才 404。

    Args:
        task_id: 任务 id。
        after_seq: ``event_seq`` 游标（≥0）；返回严格大于它的事件。
        limit: 页大小（1..``TRACE_MAX_LIMIT``，越界由 Pydantic 自动 422）。
        role: 可选角色过滤；非法值 422 ``invalid_request``。

    Returns:
        轨迹页：``items``（按 ``event_seq`` 升序）+ 游标续拉信息 + 可用性标注。

    Raises:
        ApiError: 404 任务不存在；422 ``role`` 非法。
    """
    database = get_database()
    if database.get_task(task_id) is None:
        raise ApiError(
            ErrorCode.TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            status=status.HTTP_404_NOT_FOUND,
        )

    if role is not None and role not in VALID_TRACE_ROLES:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            f"非法 role：{role}（合法值：{sorted(VALID_TRACE_ROLES)}）",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    rows = database.list_events(task_id, after_seq=after_seq, limit=limit, role=role)
    # total 必须走 count_events 单独 count（同 count_evals 纪律）：不能用
    # len(rows)，后者受 limit 截断，会得到一个假的「总数」。
    total = database.count_events(task_id, role=role)

    items = [_to_event_view(row) for row in rows]
    # has_more：本次返回条数已达 limit 且游标之后仍有未拉取的行。
    # 从老任务（total=0）或正好拉完的边界看都是 False，不会多给一次空页。
    has_more = len(items) == limit and after_seq + len(items) < total
    next_after_seq = items[-1].event_seq if (has_more and items) else None

    return TaskTraceResponse(
        task_id=task_id,
        items=items,
        total=total,
        limit=limit,
        after_seq=after_seq,
        has_more=has_more,
        next_after_seq=next_after_seq,
        # 契约纪律（§6.3）：events_available=false 时 items 恒为空
        events_available=total > 0,
        unavailable_reason=None if total > 0 else _TRACE_UNAVAILABLE_REASON,
    )


def _parse_arguments(raw: object) -> dict[str, Any] | None:
    """把 DB 里的 ``arguments``（JSON 串或 ``None``）解析成对象。

    设计文档 §6.2 规定响应里的 ``arguments`` 是 **object**（不是 JSON 串）；
    ``None``（非工具事件）必须原样返回 ``None``，**绝不落成 ``{}``**（K3）。
    解析失败（历史脏数据）时返回 ``None`` 并记 DEBUG，**不抛**——
    一条坏数据不该让整页轨迹 500。
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        # 已解析的形态（防御性：ORM 列是 Text，正常只会是 str/None）
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        logger.debug("arguments 类型异常（%s），按 None 处理", type(raw).__name__)
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        logger.debug("arguments JSON 解析失败，按 None 处理：%r", raw[:120])
        return None
    return parsed if isinstance(parsed, dict) else None


def _to_event_view(row: TaskEventRecord) -> TaskEventView:
    """把 ORM 事件行拼成响应模型（``arguments`` 串 → 对象，时间转北京时间）。"""
    return TaskEventView(
        event_seq=int(row.event_seq),
        step=int(row.step),
        sub_step=None if row.sub_step is None else int(row.sub_step),
        event_type=row.event_type,
        role=row.role,
        node=row.node,
        thought=row.thought or "",
        tool_name=row.tool_name,
        arguments=_parse_arguments(row.arguments),
        observation=row.observation or "",
        latency_ms=int(row.latency_ms),
        tokens_in=int(row.tokens_in),
        tokens_out=int(row.tokens_out),
        cost=round(float(row.cost), 6),
        status=row.status,
        error_code=row.error_code,
        error_message=row.error_message,
        sse_seq=None if row.sse_seq is None else int(row.sse_seq),
        created_at=to_cn(row.created_at),
    )


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}/cost-breakdown
# --------------------------------------------------------------------------- #

#: 「``Σ by_role.cost`` == ``tasks.cost``」的容差，单位**元**。
#: 两边是**各自独立算出来**的：前者是本端点对 ``task_events`` 的 ``GROUP BY``，
#: 后者是 ``evaluation/metrics.py:83`` 把 ``traces`` 记录求和后 ``round(…, 6)`` 落库。
#:
#: **1e-6 是推出来的，不是凑出来的**：``tasks.cost`` 经过 ``round(x, 6)`` ⇒ 舍入误差
#: 的**上界是 5e-7，与事件条数无关**（这才是门槛能与总量解耦的原因）；1e-6 给它留一倍余量，
#: 又比最小的真实调用小三个数量级（实测 ``task-5ba7127ba5f0`` 的 planner 一次 7.07e-4 元）。
#: 实测 19 条真实任务的偏差落在 0 … 4.3e-7，全部在此容差内。
_RECONCILE_TOL_CNY = 1e-6

#: 单价反推（C6 守门人）的判据阈值，单位**百分数**。
#: 实测方案 §1.5 那五次真实运行，反推出的单价对与 ``MODEL_PRICES["deepseek-flash"]``
#: 的偏差是 **0.000%**（含唯一那条低谷 ×0.5 的运行）；留 0.5% 是给 ``cost`` 落库时的
#: 10 位取整、以及未来按官网调价时表内价与历史账的短暂不一致。
_PRICE_TOL_PCT = 0.5


def _peak_from_multiplier(multiplier: float | None, model: str | None = None) -> bool | None:
    """由**存进库里的那次调用实际用的系数**反推峰谷标签。

    ⚠️ 这里刻意**不查当前时钟**：面板要回答的是「这笔钱当时按什么档计的」，
    而不是「现在是什么档」。两个数各自都有意义，混成一个就是说谎。

    两个已知取值来自 :func:`core.llm.pricing.price_multiplier`（高峰 ``1.0`` /
    低谷 :data:`~core.llm.pricing.OFF_PEAK_MULTIPLIER`）。除此之外（含 ``None``）
    一律返回 ``None`` —— 「不知道」不是「不算高峰」，硬贴一个布尔值就等于猜。

    Args:
        multiplier: 库里的 ``price_multiplier``；``None`` = 这条历史记录时还没记。
        model: 这一行的模型 id。**分峰谷只是 DeepSeek 一家的计费规则**，
            智谱与千问不分 ⇒ 它们的 ``1.0`` 意思是"没有折扣"，不是"高峰"。
            给这些家的行贴「高峰」是把三家不同的规则压成一个标签（换模型方案 T-3 同款）。

    Returns:
        ``True``=高峰、``False``=低谷、``None``=未记录 / 系数不是已知档位 / 这家不分峰谷。
    """
    if model:
        provider = providers.provider_for(str(model))
        if provider is not None and not provider.peak_off_peak:
            return None
    if multiplier is None:
        return None
    value = round(float(multiplier), 6)
    if value == 1.0:
        return True
    if value == round(OFF_PEAK_MULTIPLIER, 6):
        return False
    return None


def _price_check(rows: list[CostRoleRow], settings: Any) -> PriceCheck:
    """从库里的 ``(tokens_in, tokens_out, cost)`` **反解**单价，与 ``resolve_price`` 对咬。

    为什么要有这件事：``cost`` 这一列是写入侧用当时的单价算完再存进来的，端点如果只是
    把它加起来，那么「单价表被改错」「单位口径漂了 10⁶ 倍」「系数套了两遍」这类问题都会
    被原样加出来 —— 面板越整齐越可疑。反解是让**存的金额**和**当前代码里的价**互相作证。

    解法（单条方程解不出两个未知数，必须联立）：同一 ``(model, price_multiplier)`` 组合下
    每行满足 ``cost = (tokens_in·p_in + tokens_out·p_out) × m / 1e6``，令
    ``C = cost × 1e6 / m`` 得线性方程组；取两行解 ``p_in`` / ``p_out``，
    **其余各行当独立验证**（用解出的单价预测它们的 ``cost`` 再与库里比）。

    判不了就明说判不了（``ok=None`` + ``reason``）。⚠️ 这条纪律比判对更重要：返回
    ``True`` 或 ``0`` 蒙过去，「没验过」就会被读成「验过了」，而这个字段的存在理由
    就是不让这种情况发生。

    Args:
        rows: 已经拼好的 ``by_role`` 行（聚合值本身就是合法的方程系数，不必回查明细）。
        settings: 配置对象，喂给 :func:`~core.llm.adapter.resolve_price`。

    Returns:
        :class:`PriceCheck`；``equations`` 是可用于反推的候选行数。
    """
    candidates = [
        row
        for row in rows
        if row.model
        and row.price_multiplier
        and row.cost > 0
        and (row.tokens_in > 0 or row.tokens_out > 0)
    ]
    if not candidates:
        return PriceCheck(
            ok=None,
            equations=0,
            reason="没有可反推的行：model / price_multiplier 未记录（老任务）或 cost 为 0",
        )

    # 只有同模型 + 同系数才共享同一对未知单价；按 role 分组不行（同价不同角色要合并）
    buckets: dict[tuple[str, float], list[CostRoleRow]] = {}
    for row in candidates:
        buckets.setdefault((str(row.model), float(row.price_multiplier or 0.0)), []).append(row)
    # 取候选行最多的那一组：单行组解不出两个未知数
    key = max(buckets, key=lambda k: len(buckets[k]))
    group = buckets[key]
    model, multiplier = key
    # 阶梯计价的家（智谱、千问）**判不了**：一组里各次调用的输入长度可能落在不同档，
    # 于是"这一组的单价"根本不是常数，反解出来的数与表内任何一档都对不上。
    # 报 ok=False 会把"没法判"显示成"单价漂移了"，那是比空着更坏的结果（C6 守门人的
    # 存在理由就是不让"没验过"被读成"验过了"）。
    tiered_spec = providers.resolve_model(str(model))
    if tiered_spec is not None and tiered_spec.tiered:
        return PriceCheck(
            ok=None,
            equations=len(group),
            reason=(
                f"模型 {model} 按输入长度分档（{providers.tiers_description(tiered_spec)} 元/百万 token），"
                f"这一组 {len(group)} 行里每次调用的长度可能落在不同档 ⇒ 单价不是常数，"
                "反解出的那一对数与任一档都对不上。判不了 ≠ 有问题"
            ),
        )
    if len(group) < 2:
        return PriceCheck(
            ok=None,
            equations=len(group),
            reason=(
                f"同一 (模型={model}, 系数={multiplier}) 下只有 {len(group)} 行，"
                "方程数不足 2，解不出两个未知单价"
            ),
        )

    # 找一对行列式非奇异的两行（token 比相同 ⇒ 两条方程共线，解不唯一）
    solved: tuple[float, float, list[CostRoleRow]] | None = None
    for i, first in enumerate(group):
        for j, second in enumerate(group):
            if j <= i:
                continue
            determinant = first.tokens_in * second.tokens_out - second.tokens_in * first.tokens_out
            if abs(determinant) < 1:
                continue
            c_first = first.cost * 1_000_000 / multiplier
            c_second = second.cost * 1_000_000 / multiplier
            price_in = (c_first * second.tokens_out - c_second * first.tokens_out) / determinant
            price_out = (first.tokens_in * c_second - second.tokens_in * c_first) / determinant
            rest = [row for index, row in enumerate(group) if index not in (i, j)]
            solved = (price_in, price_out, rest)
            break
        if solved is not None:
            break
    if solved is None:
        return PriceCheck(
            ok=None,
            equations=len(group),
            reason=f"候选 {len(group)} 行的 token 比例两两共线（行列式为 0），方程组奇异无唯一解",
        )

    implied_in, implied_out, validators = solved
    table_in, table_out, _source = resolve_price(model, settings)

    def _relative_delta_pct(actual: float, expected: float) -> float:
        """相对偏差（百分数）。``expected == 0`` 时不能除，另走一条判据。

        ⚠️ 表内价为 0 时**不能**直接记 0 偏差 —— 那会把「表里写着免费、账上却收了钱」
        这种最刺眼的不一致判成通过。0 对非 0 就是不一致，给满格 100%。
        """
        if expected == 0:
            return 0.0 if abs(actual) < 1e-9 else 100.0
        return abs(actual - expected) / abs(expected) * 100

    deltas = [
        _relative_delta_pct(implied_in, table_in),
        _relative_delta_pct(implied_out, table_out),
    ]
    # 第三方验证：拿解出的单价回头预测没用过的那几行
    for row in validators:
        predicted = (row.tokens_in * implied_in + row.tokens_out * implied_out) * multiplier / 1_000_000
        deltas.append(_relative_delta_pct(predicted, row.cost))

    max_delta = max(deltas)
    return PriceCheck(
        ok=max_delta <= _PRICE_TOL_PCT,
        max_delta_pct=round(max_delta, 4),
        implied_price_in=round(implied_in, 4),
        implied_price_out=round(implied_out, 4),
        equations=len(group),
        reason=None
        if max_delta <= _PRICE_TOL_PCT
        else (
            f"反推单价 ({implied_in:.4f}, {implied_out:.4f}) 与表内价 "
            f"({table_in}, {table_out}) 或独立验证行偏差 {max_delta:.3f}% > {_PRICE_TOL_PCT}%"
            f"（模型 {model}，系数 {multiplier}）"
        ),
    )


@router.get(
    "/tasks/{task_id}/cost-breakdown",
    response_model=CostBreakdownResponse,
    responses={404: {"model": ErrorResponse, "description": "任务不存在"}},
    summary="按（角色, 模型, 峰谷系数）聚合某任务的 LLM 成本（只读，全量口径）",
)
def get_task_cost_breakdown(task_id: str) -> CostBreakdownResponse:
    """成本归因面板的服务端：钱花在哪个角色、哪个模型、乘了 1.0 还是 0.5。

    **为什么是 ``def``**：与 ``/trace`` 同一条纪律（本文件顶部表格），纯 DB 读交给
    线程池，``async def`` 会把 ``asyncio.Queue`` 变成多线程访问。

    **三条口径，都是"不报错但会说谎"的那类**（方案 §6 三条避坑）：

    1. **合计是全量的**。``/trace`` 的游标分页在前端封顶（``limit=50`` × 10 页 = 500 条），
       拿明细去加会得到一个静默偏小的数。这里的合计来自 ``GROUP BY``，与总事件数解耦。
    2. **时段与单价一律后端算**。``tasks.created_at`` 存 UTC 而
       :func:`core.llm.pricing.is_peak` 把 naive 串当北京时间解释 ⇒ 前端自判整体错 8 小时。
       本端点返回的 datetime 全带 ``+08:00``。
    3. **``model`` 为 ``NULL`` 的旧行不回落到当前 ``role_map``**。以今天的配置解释昨天的账
       就是造数（不造数是底线）；这类行返回 ``price_source="unknown"`` + 单价 ``None``，
       前端显示「未记录」。同理 ``price_multiplier`` 的 ``NULL`` 不当成 1.0 ——
       ``0.0`` 是免费，``NULL`` 是没记，两回事。

    金额在本端点**不做展示层截断**（``round`` 到 6 位会把 ``Σ by_role`` 与 ``tasks.cost``
    的对账推到 1e-6 容差边缘）；要几位小数是展示层的事。

    Args:
        task_id: 任务 id。

    Returns:
        合计 + 分组明细 + 时段事实 + 单价反推 + 对账。无 LLM 调用时 200 + 空明细
        （「跑了但没花钱」与「任务不存在」是两种事实，后者才 404）。

    Raises:
        ApiError: 404 任务不存在。
    """
    database = get_database()
    record = database.get_task(task_id)
    if record is None:
        raise ApiError(
            ErrorCode.TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            status=status.HTTP_404_NOT_FOUND,
        )

    settings = get_settings()
    rows: list[CostRoleRow] = []
    for group in database.cost_breakdown(task_id):
        # resolve_price 是全项目唯一的单价入口（与 GET /models、estimate_cost 同源），
        # 在这里再写一份 MODEL_PRICES 查表就是制造第二个口径。
        model = group.get("model")
        multiplier = group.get("price_multiplier")
        if model:
            unit_in, unit_out, source = resolve_price(str(model), settings)
        else:
            unit_in, unit_out, source = None, None, "unknown"
        # ⚠️ 阶梯模型的 unit_price 是**最低档**（这一行是 N 次调用的聚合，
        # 拿聚合的 tokens_in 去选档是错的 —— 单次长度 ≠ 总长度）。所以把"分不分档"
        # 一起报出去，页面必须写成"下界"而不是"这个模型就是这个价"（方案 T-3）。
        spec = providers.resolve_model(str(model)) if model else None
        tiered = None if spec is None else spec.tiered
        rows.append(
            CostRoleRow(
                role=group.get("role"),
                model=model,
                price_multiplier=None if multiplier is None else float(multiplier),
                peak=_peak_from_multiplier(multiplier, str(model) if model else None),
                tiered=tiered,
                calls=int(group.get("calls") or 0),
                tokens_in=int(group.get("tokens_in") or 0),
                tokens_out=int(group.get("tokens_out") or 0),
                cost=float(group.get("cost") or 0.0),
                unit_price_in=unit_in,
                unit_price_out=unit_out,
                price_source=source,  # type: ignore[arg-type]
                # 单价口径原话跟着**这一行的那一家**走：以前前端在所有行上盖一句
                # 「按官网高峰价折算（DeepSeek 口径）」，换供应商之后每行都在说谎。
                pricing_basis=(
                    spec.pricing_basis
                    if spec
                    else "未在价目表里 ⇒ 单价取 .env 的兜底值（未核价），只能当量级参考"
                    if model
                    else ""
                ),
            )
        )

    totals = CostTotals(
        calls=sum(row.calls for row in rows),
        tokens_in=sum(row.tokens_in for row in rows),
        tokens_out=sum(row.tokens_out for row in rows),
        cost=sum(row.cost for row in rows),
    )

    # 对账：本端点的聚合 vs 任务级记账。旧任务没有 model / 系数两列，但 cost 列一直在，
    # 所以这一项对新旧任务同样有效（不依赖那两列）。
    #
    # ⚠️ 未进终态的任务**不做判定**：``tasks.cost`` 只在 ``mark_terminal`` 时写，
    # 半程任务库里恒为 0 而事件已经在花钱（实测 task-1365c179c055：running、
    # tasks.cost=0、Σ llm_call=0.0126）。判成「不等」是假警报，判成「相等」是撒谎。
    task_cost = float(record.cost or 0.0)
    delta = totals.cost - task_cost
    if record.status not in API_TERMINAL_STATUSES:
        all_equal: bool | None = None
        note = (
            f"对账不适用：任务仍在 {record.status}，tasks.cost 要到终态才落库（当前 {task_cost}），"
            f"而 events_cost={totals.cost:.10f} 是实时累加值"
        )
    else:
        reconciled = abs(delta) <= _RECONCILE_TOL_CNY
        all_equal = reconciled
        note = (
            ""
            if reconciled
            else (
                f"Σ by_role.cost={totals.cost:.10f} 元与 tasks.cost={task_cost:.10f} 元相差 "
                f"{delta:+.10f} 元（超出 {_RECONCILE_TOL_CNY} 元容差，即 tasks.cost 那次 "
                "round(…, 6) 的 5e-7 上界的两倍）：两侧独立算出的总额不该不一致，"
                "先查聚合是否漏了 event_type 过滤、tasks.cost 是否走了另一条累加路径"
            )
        )
    reconcile = CostReconcile(
        events_cost=totals.cost,
        task_cost=task_cost,
        all_equal=all_equal,
        note=note,
    )

    clock = now()
    peak_now = is_peak(clock)
    window = CostWindow(
        is_peak_now=peak_now,
        multiplier_now=price_multiplier(clock),
        # pricing.next_off_peak 在「已是低谷」时返回当前时刻；对面板来说那不是一个
        # 「下一次」，所以这里判成 None，让前端能区分「18:00 后进低谷」和「正在低谷」。
        next_off_peak_at=to_cn(next_off_peak(clock)) if peak_now else None,
        window_desc=window_description(),
    )

    return CostBreakdownResponse(
        task_id=task_id,
        generated_at=clock,
        totals=totals,
        by_role=rows,
        window=window,
        price_check=_price_check(rows, settings),
        reconcile=reconcile,
    )


# --------------------------------------------------------------------------- #
# POST /tasks/{task_id}/cancel
# --------------------------------------------------------------------------- #
@router.post(
    "/tasks/{task_id}/cancel",
    response_model=CancelResponse,
    responses={
        404: {"model": ErrorResponse, "description": "任务不存在"},
        409: {"model": ErrorResponse, "description": "任务已终态"},
    },
    summary="取消任务（节点边界生效）",
)
async def cancel_task(task_id: str) -> CancelResponse:
    """取消一条任务。

    语义（PRD §P0-5）：``queued`` 直接丢弃（零 LLM 调用）；``running`` 在当前
    节点返回后停止并丢弃结果；已终态返回 409。

    Args:
        task_id: 任务 id。

    Returns:
        取消结果（含生效模式与限制说明）。

    Raises:
        ApiError: 404 / 409。
    """
    database = get_database()
    queue = get_task_queue()

    if database.get_task(task_id) is None:
        raise ApiError(
            ErrorCode.TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            status=status.HTTP_404_NOT_FOUND,
        )

    # ① 先置事件位：让 worker 尽快停（哪怕 CAS 失败也已尽量减少后续动作）
    token = queue.cancel_registry.get(task_id)
    if token is not None:
        token.event.set()

    # ② CAS 仲裁：失败说明任务已经终态
    if not database.mark_canceled(task_id):
        raise ApiError(
            ErrorCode.TASK_ALREADY_FINISHED,
            f"任务已处于终态，无法取消：{task_id}",
            status=status.HTTP_409_CONFLICT,
        )

    canceled_at = now()
    queue.publish_canceled(task_id, canceled_at=canceled_at.isoformat())
    get_cache_facade().drop_progress(task_id)
    mode = "queued_dropped" if (token is None or token.started_at is None) else "node_boundary"
    logger.info("任务已取消 task_id=%s mode=%s", task_id, mode)
    return CancelResponse(
        task_id=task_id,
        status=STATUS_CANCELED,  # type: ignore[arg-type]
        canceled_at=canceled_at,
        mode=mode,  # type: ignore[arg-type]
        note=_CANCEL_NOTE,
    )


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}/stream  +  别名 GET /tasks/{task_id}/events
# --------------------------------------------------------------------------- #
def _build_sse_response(task_id: str, request: Request) -> StreamingResponse:
    """构建任务 SSE 响应（``/stream`` 与 ``/events`` 共用同一份实现）。

    404 **必须**在建流之前抛出：一旦返回 200 就不能再改状态码（设计文档 R18）。

    Args:
        task_id: 任务 id。
        request: 原始请求（用于检测客户端断连）。

    Returns:
        ``text/event-stream`` 响应。

    Raises:
        ApiError: 404 任务不存在。
    """
    database = get_database()
    record = database.get_task(task_id)
    if record is None:
        raise ApiError(
            ErrorCode.TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            status=status.HTTP_404_NOT_FOUND,
        )

    settings = get_settings()
    heartbeat = max(float(settings.api_sse_heartbeat_seconds), 0.1)
    bus = get_event_bus()

    async def generate() -> Any:
        """SSE 帧生成器（在 loop 线程执行）。

        发号纪律（Q6-10，2026-10-02）：这一层**不再自己编号**。
        ``id:`` 唯一的来源是 worker 的任务级 ``seq_box``；本函数自己产出的两/三帧
        （首屏 ``snapshot``、终态补帧、``heartbeat``）传 ``seq=None``，
        :func:`~api.events.format_frame` 于是省掉 ``id:`` 行。
        改前三处各数各的（worker 的 ``seq``、``_build_streams`` 的
        ``state["seq"]``、这里的 ``seq``），同一根连接上必然撞号，而
        ``seq = max(seq, event.seq)`` 只是把本地号往回垫一点，发出去的帧仍带
        旧号 —— 一个既不单调也不唯一的 ``id:`` 比没有 ``id:`` 更糟。
        """
        subscription = await bus.subscribe(task_id)
        started = time.perf_counter()
        try:
            yield format_retry_frame()

            current = database.get_task(task_id)
            if current is None:  # pragma: no cover - 入口已校验过
                return
            yield format_frame(
                StreamEvent(
                    task_id=task_id,
                    name=EVT_SNAPSHOT,
                    seq=None,
                    data={
                        "task_id": task_id,
                        "status": current.status,
                        "progress": _snapshot_progress(current),
                        "ts": now().isoformat(),
                    },
                )
            )

            if current.status in API_TERMINAL_STATUSES:
                # 已是终态：补一帧终态事件后立刻关流，不挂起（PRD §P0-6 规则 3）
                yield format_frame(
                    StreamEvent(
                        task_id=task_id,
                        name=EVENT_BY_STATUS.get(current.status, EVT_SNAPSHOT),
                        seq=None,
                        data=_terminal_event_data(current),
                    )
                )
                return

            while True:
                try:
                    event = await asyncio.wait_for(subscription.get(), timeout=heartbeat)
                except (asyncio.TimeoutError, TimeoutError):
                    if await request.is_disconnected():
                        logger.debug("SSE 客户端已断开 task_id=%s", task_id)
                        return
                    yield format_frame(
                        StreamEvent(
                            task_id=task_id,
                            name=EVT_HEARTBEAT,
                            seq=None,
                            data={
                                "task_id": task_id,
                                "ts": now().isoformat(),
                                "running_ms": int((time.perf_counter() - started) * 1000),
                            },
                        )
                    )
                    continue
                except asyncio.CancelledError:
                    return

                yield format_frame(event)
                if event.name in TERMINAL_EVENTS:
                    return
        finally:
            await bus.unsubscribe(task_id, subscription)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/tasks/{task_id}/stream",
    responses={404: {"model": ErrorResponse, "description": "任务不存在"}},
    summary="订阅任务的 SSE 节点增量",
)
async def stream_task(task_id: str, request: Request) -> StreamingResponse:
    """订阅一条任务的节点级增量（SSE，主路径）。

    Args:
        task_id: 任务 id。
        request: 原始请求。

    Returns:
        ``text/event-stream`` 响应。
    """
    return _build_sse_response(task_id, request)


@router.get(
    "/tasks/{task_id}/events",
    responses={404: {"model": ErrorResponse, "description": "任务不存在"}},
    summary="订阅任务的 SSE 节点增量（/stream 的别名）",
)
async def stream_task_events(task_id: str, request: Request) -> StreamingResponse:
    """``/tasks/{id}/stream`` 的别名路由。

    语义与 ``/stream`` **完全一致**（共用 ``_build_sse_response``，不复制生成器），
    仅为前端 EventSource 命名习惯提供可读入口。保留别名而非替换，是为了不破坏
    既有客户端与集成测试对 ``/stream`` 的依赖。

    Args:
        task_id: 任务 id。
        request: 原始请求。

    Returns:
        ``text/event-stream`` 响应。
    """
    return _build_sse_response(task_id, request)


def _snapshot_progress(record: TaskRecord) -> dict[str, Any] | None:
    """快照帧里的 progress（终态为 ``null``）。"""
    if record.status in API_TERMINAL_STATUSES:
        return None
    cached = get_cache_facade().load_progress(record.task_id)
    if isinstance(cached, dict):
        return {
            "current_node": cached.get("current_node"),
            "completed_nodes": list(cached.get("completed_nodes") or []),
            "iteration": int(cached.get("iteration") or 0),
            "max_iterations": int(cached.get("max_iterations") or 0),
            "elapsed_ms": int(cached.get("elapsed_ms") or 0),
        }
    return {
        "current_node": None,
        "completed_nodes": [],
        "iteration": record.iterations,
        "max_iterations": get_settings().max_iterations,
        "elapsed_ms": 0,
    }


def _terminal_event_data(record: TaskRecord) -> dict[str, Any]:
    """按 PRD §P0-6 组装终态事件负载。"""
    if record.status == "failed":
        return {
            "task_id": record.task_id,
            "error": {
                "code": record.error_code or "node_failed",
                "message": record.error_message or "任务失败",
            },
        }
    if record.status == STATUS_CANCELED:
        return {
            "task_id": record.task_id,
            "reason": "user_requested",
            "canceled_at": to_cn(record.updated_at).isoformat(),
        }
    return {
        "task_id": record.task_id,
        "status": record.status,
        "final_answer": record.final_answer,
        "cost": round(record.cost, 6),
        "duration_ms": record.duration_ms,
        "iterations": record.iterations,
        "score": record.score,
        "grade": record.grade,
    }


__all__ = ["router"]
