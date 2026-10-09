"""健康检查：``GET /health``。

判定口径（PRD §P0-9，与 ``scripts/health_check.py`` 保持一致）

=========  =======================================  ==================================
依赖项     不通时的处理                               理由
=========  =======================================  ==================================
database   **unhealthy + HTTP 503**                 结果无处落库，等于不能服务
redis      **degraded + HTTP 200**                  有进程内缓存降级，功能不受影响
llm        未配 Key → fail → unhealthy + 503；      默认零 token，不因探活烧钱
           ``?deep=true`` 真调一次，异常 → degraded
queue      恒 ok，只上报计数                         —
rag        fail → **只贡献 degraded**（特判，        RAG 故障不影响 Agent 任务
           永不 unhealthy，与 redis 同口径）
=========  =======================================  ==================================

整体状态优先级：任一 ``fail`` → ``unhealthy``；否则任一 ``degraded`` →
``degraded``；否则 ``healthy``。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from api import __version__
from api.deps import get_cache_facade, get_database, get_task_queue
from api.schemas import CheckResult, HealthResponse
from config import get_settings
from core.llm import runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["health"])


def _check_database() -> CheckResult:
    """数据库：能开会话并执行 ``SELECT 1`` 即 ok。"""
    from sqlalchemy import text

    try:
        database = get_database()
        with database.session() as handle:
            handle.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 健康检查必须兜住一切
        logger.warning("健康检查：数据库不可用：%s", exc)
        return CheckResult(status="fail", detail=f"数据库不可用：{type(exc).__name__}: {exc}")
    return CheckResult(status="ok", detail=f"SQLite 可读写（{get_settings().resolved_db_url}）")


def _check_redis() -> CheckResult:
    """Redis：不通只降级（平台有进程内缓存兜底）。"""
    try:
        cache = get_cache_facade()
        if cache.using_redis and bool(cache.backend.ping()):
            return CheckResult(status="ok", detail="Redis 可用")
    except Exception as exc:  # noqa: BLE001 - 同上
        logger.warning("健康检查：Redis 探测异常：%s", exc)
        return CheckResult(status="degraded", detail=f"Redis 探测异常：{exc}")
    return CheckResult(status="degraded", detail="Redis 不可用，已降级为进程内缓存（功能不受影响）")


def _check_llm(deep: bool) -> CheckResult:
    """LLM：默认只查配置（零 token）；``?deep=true`` 才真调一次探针。

    ⚠️ 查的是**当前两个档位真正会用的那两把 Key**（:func:`core.llm.runtime.route`），
    不是 ``settings.llm_api_key`` 一把。换了供应商之后只看 .env 那把的话，
    体检胶囊会对着一个必然失败的配置报「ok」—— 而这一格正是用户判断"能不能跑"的依据，
    报错的体检比没有体检更坏。
    """
    settings = get_settings()
    large = runtime.route(settings.llm_model_large, settings)
    small = runtime.route(settings.llm_model_small, settings)
    missing = [item for item in (large, small) if not item.key_configured]
    if missing:
        return CheckResult(
            status="fail",
            detail="未配置 "
            + "；".join(
                f"{item.provider_display} 的 Key（环境变量 {item.api_key_field.upper()}，"
                f"档位模型 {item.model}）"
                for item in missing
            )
            + "，这一档的任务无法执行",
        )
    if not deep:
        return CheckResult(
            status="ok",
            detail=f"已配置 Key（{large.provider_display}/{large.model} @ {large.base_url}）；"
            "加 ?deep=true 可真实调用一次探针",
        )
    started = time.perf_counter()
    try:
        from core.llm.adapter import LLMAdapter

        LLMAdapter(settings=settings).invoke(
            [{"role": "user", "content": "ping"}], model=settings.llm_model_small
        )
    except Exception as exc:  # noqa: BLE001 - 探针失败只降级
        logger.warning("健康检查：LLM 探针失败：%s", exc)
        return CheckResult(status="degraded", detail=f"LLM 探针失败：{type(exc).__name__}: {exc}")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return CheckResult(status="ok", detail=f"LLM 探针通过（{elapsed_ms}ms）")


def _check_queue() -> CheckResult:
    """队列：恒 ok，额外上报计数。"""
    stats = get_task_queue().stats()
    return CheckResult(
        status="ok",
        detail=(
            f"运行中 {stats['running']}/{stats['max_concurrent']}，排队 {stats['queued']}"
        ),
        **stats,
    )


def _check_rag() -> CheckResult:
    """知识库：依赖缺失/组件故障 → fail；**fail 只贡献 degraded**（特判，
    与 redis 同口径——RAG 故障不能影响 Agent 任务与旧 5 工具，PRD P0-7 验收 3）。"""
    from api.deps import get_knowledge_service

    service = get_knowledge_service()
    if service is None:
        return CheckResult(status="fail", detail="rag 依赖不可用，知识库功能未启用（平台其余功能照常）")
    status_value, detail = service.health_check()
    return CheckResult(status=status_value, detail=detail)


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(request: Request, deep: bool = Query(default=False, description="是否真实调用 LLM 探针")) -> JSONResponse:
    """健康检查：区分「真的不能服务」与「有降级但能服务」。

    Args:
        request: 原始请求（取 ``app.state.started_at`` 算 uptime）。
        deep: 是否真实调用一次 LLM（会消耗极少量 token）。

    Returns:
        ``200``（healthy / degraded）或 ``503``（unhealthy）。
    """
    checks = {
        "api": CheckResult(status="ok", detail=f"FastAPI 服务正常（版本 {__version__}）"),
        "database": _check_database(),
        "redis": _check_redis(),
        "llm": _check_llm(deep),
        "queue": _check_queue(),
        "rag": _check_rag(),
    }
    # 整体判定（rag 特判）：rag=fail 只贡献 degraded，永不升级 unhealthy。
    statuses = {item.status for item in checks.values()}
    rag_fail = checks["rag"].status == "fail"
    if "fail" in statuses and not rag_fail:
        overall = "unhealthy"
        http_status = 503
    elif "fail" in statuses or "degraded" in statuses:
        overall = "degraded"
        http_status = 200
    else:
        overall = "healthy"
        http_status = 200

    started_at = float(getattr(request.app.state, "started_at", time.time()))
    payload = HealthResponse(
        status=overall,  # type: ignore[arg-type]
        version=__version__,
        uptime_seconds=int(time.time() - started_at),
        checks=checks,
    )
    return JSONResponse(
        status_code=http_status,
        content=payload.model_dump(mode="json"),
    )


__all__ = ["router"]
