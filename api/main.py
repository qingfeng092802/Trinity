"""FastAPI 应用工厂：中间件、异常处理器、生命周期与路由注册。

中间件的顺序（**容易写反**）
----------------------------
Starlette 的 ``add_middleware`` 是 ``user_middleware.insert(0, ...)``，
而构建时按 ``reversed`` 包裹，所以**最后添加的最先执行**（最外层）。
本模块先加鉴权、后加 request_id，于是 request_id 在外层——
它先把 ``request_id`` 写进 ContextVar，鉴权失败时错误响应里才能带上这个 id。

刻意**不开** uvicorn ``--reload``（设计文档 R15）：reload 会起子进程，
于是线程池与队列出现两份，行为诡异且极难排查。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from api import __version__
from api.constants import is_auth_exempt
from api.deps import get_database, get_knowledge_service, get_task_queue, verify_token
from api.errors import ApiError, install_exception_handlers, json_error, new_request_id
from api.errors import request_id_ctx
from api.routes import (
    config_router,
    eval_router,
    health_router,
    knowledge_router,
    models_router,
    stats_router,
    tasks_router,
    tools_router,
)
from config import Settings, get_settings

logger = logging.getLogger(__name__)

#: 中间件里 ``call_next`` 的类型（Starlette 只给了运行时约定，这里补全注解）
CallNext = Callable[[Request], Awaitable[Response]]


# --------------------------------------------------------------------------- #
# 真实监听地址（安全告警用）
# --------------------------------------------------------------------------- #
def _effective_bind_host(settings: Settings) -> str:
    """解析进程**真实**的监听 host（缺陷 3）。

    优先级：命令行 ``--host`` > 环境变量 ``API_HOST`` > ``settings.api_host``。

    为什么不直接用 ``settings.api_host``：``config.Settings.api_host`` 默认
    ``127.0.0.1``，但进程常被 ``uvicorn ... --host 0.0.0.0`` 启动——此时
    uvicorn 实际绑的是全网卡，而 ``settings.api_host`` 仍是默认值。旧告警据此
    打印「当前仅监听 127.0.0.1」，与同一份日志里 ``Uvicorn running on
    http://0.0.0.0:8000`` **直接矛盾**，会把「对全网卡开放且免鉴权」误报成
    「仅本机」。因此这里以命令行参数为准（它才是 uvicorn 真正的 bind 来源）。

    Args:
        settings: 全局配置（提供 ``api_host`` 兜底）。

    Returns:
        进程真实（或最可能）的监听 host 字符串。
    """
    argv = sys.argv
    for index, token in enumerate(argv):
        if token == "--host" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--host="):
            return token.split("=", 1)[1]
    env_host = os.environ.get("API_HOST")
    if env_host:
        return env_host
    return settings.api_host


def _is_loopback(host: str) -> bool:
    """判断监听地址是否仅限本机回环（``127.0.0.0/8`` / ``::1`` / ``localhost``）。

    非回环（``0.0.0.0`` / ``::`` / 局域网 IP / 空串）都视为「对外可达」——
    空串按不安全处理（宁可多报一次警，也不要漏报）。

    Args:
        host: 监听地址字符串。

    Returns:
        ``True`` 表示仅本机可访问。
    """
    normalized = (host or "").strip().strip("[]").lower()
    if normalized in {"localhost", "::1"}:
        return True
    if not normalized:
        return False
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        # 非 IP 文本（如主机名）无法判定是否为回环 → 视为对外可达，保守告警
        return False


# --------------------------------------------------------------------------- #
# 生命周期
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动：建表 + 起队列 + 打印降级告警；退出：停队列。

    Args:
        app: FastAPI 应用实例。

    Yields:
        ``None``；``yield`` 之前是启动逻辑，``finally`` 里是清理逻辑。
    """
    settings = get_settings()
    database = get_database()  # 建表 + 补列（lru_cache 保证每进程一次）
    queue = get_task_queue()

    # 任务跑在本进程的内存队列里，没有续跑能力：进程重启后留在 queued/running 的行
    # 就是数据库在说谎（本机实测有一条挂了 3 天）。启动即判死，见 db 里的单 worker 前提。
    reclaimed = database.fail_interrupted_tasks()
    if reclaimed:
        logger.warning(
            "启动清理：%d 条非终态任务被判定 failed（error_code=process_restarted）。"
            "它们是上一个进程被硬杀/重启时带走的中断任务，不是本次会话的。",
            reclaimed,
        )

    await queue.start()

    # 知识库（M2）：initialize 在 get_knowledge_service 里完成（不加载模型），
    # 这里只负责索引 worker 的起停；rag 不可用时 get_knowledge_service 为 None，
    # 平台其余功能照常（D3：RAG 故障不拖垮平台）。
    knowledge = get_knowledge_service()
    if knowledge is not None:
        knowledge.start_worker()

    # 缺陷 3：告警必须基于**真实绑定 host**，不能拿 settings 默认值去断言
    # 「仅监听 127.0.0.1」——那会在 `--host 0.0.0.0` 启动时误报（见 _effective_bind_host）。
    bind_host = _effective_bind_host(settings)
    if not settings.api_auth_enabled:
        if _is_loopback(bind_host):
            logger.warning(
                "API_AUTH_TOKEN 未设置：服务监听回环地址 %s，仅本机可访问、全部请求免鉴权。"
                "若要对外暴露端口，请先设置 API_AUTH_TOKEN。",
                bind_host,
            )
        else:
            logger.error(
                "安全风险：API_AUTH_TOKEN 未设置，且服务监听在 %s（非回环，对所有网卡开放）"
                "——任何能访问该端口的主机都可免鉴权 POST /tasks（消耗真实 LLM Token）"
                "并读写知识库。请立即设置 API_AUTH_TOKEN，或改为监听 127.0.0.1。",
                bind_host,
            )
    if not settings.llm_configured:
        logger.warning("LLM_API_KEY 未配置：任务仍会受理，但执行时大概率失败。")

    logger.info(
        "API 就绪：http://%s:%d/docs（并发上限 %d，队列容量 %d）",
        bind_host,
        settings.api_port,
        settings.api_max_concurrent_tasks,
        settings.api_queue_max_size,
    )
    try:
        yield
    finally:
        knowledge = None
        try:
            knowledge = get_knowledge_service()
        except Exception:  # noqa: BLE001 - 退出路径不允许再抛
            pass
        if knowledge is not None:
            knowledge.stop_worker()
        await queue.stop()
        logger.info("API 已停止")


# --------------------------------------------------------------------------- #
# 应用工厂
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    """构建 FastAPI 应用。

    Returns:
        已挂好中间件、异常处理器、lifespan 与全部路由的应用实例。
    """
    settings = get_settings()
    settings.setup_logging()
    settings.ensure_dirs()

    app = FastAPI(
        title="Trinity API",
        description=(
            "在同步编排内核（planner → executor → reviewer）之上的 REST 层："
            "异步提交任务、查询状态、SSE 节点级增量、单工具调用、评测查询与健康检查。"
        ),
        version=__version__,
        lifespan=lifespan,
    )
    install_exception_handlers(app)
    _install_middlewares(app)

    app.include_router(tasks_router)
    app.include_router(tools_router)
    app.include_router(models_router)
    # 运行配置面板的默认值 / 边界 / 预设（与 api/routes/__init__.py 的 ROUTERS 同序，
    # ⚠️ 那一份不被消费 —— 少这一行就是 404 且不报错，见方案 §4 P-7）
    app.include_router(config_router)
    app.include_router(eval_router)
    app.include_router(health_router)
    app.include_router(stats_router)
    app.include_router(knowledge_router)
    return app


def _install_middlewares(app: FastAPI) -> None:
    """挂两个 HTTP 中间件（顺序相关：后加的在外层，即先执行）。"""

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: CallNext) -> Response:
        """Bearer 鉴权；放行 :func:`~api.constants.is_auth_exempt` 命中的路径。"""
        if not is_auth_exempt(request.url.path):
            try:
                verify_token(request)
            except ApiError as exc:
                # headers 必须透传：401 需要带 WWW-Authenticate: Bearer（RFC 6750）
                return json_error(exc.code, exc.message, exc.status, headers=exc.headers)
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: CallNext) -> Response:
        """给每个请求分配 id：写入 ContextVar 并回写到响应头。"""
        token = request_id_ctx.set(new_request_id())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id = request_id_ctx.get()
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(int((time.perf_counter() - started) * 1000))
        return response


#: uvicorn 的入口（`uvicorn api.main:app`）
app = create_app()

__all__ = ["app", "create_app", "lifespan"]
