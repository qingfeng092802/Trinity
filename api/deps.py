"""FastAPI 依赖：把「重对象」做成进程内单例，并留出可测试的替换点。

为什么全用 ``lru_cache`` 而不是 ``Depends`` 链：
``Database`` / ``TraceStore`` / ``TaskQueue`` 是**有状态、需要跨请求存活**的对象
（队列里还挂着正在跑的任务），依赖注入链每次请求都新建一个实例是错的。
用 ``lru_cache`` 保证进程内唯一，同时保留 ``app.dependency_overrides`` 的可替换性
（测试覆盖 :func:`get_runner_factory` 注入 Mock LLM）。

所有缓存都可以通过 :func:`reset_api_caches` 清空——测试改了环境变量之后
必须调它，否则拿到的是旧配置构造出来的实例。
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from fastapi import Request

from api.constants import STATUS_QUEUED
from api.errors import ApiError, ErrorCode
from api.events import EventBus
from api.queue import TaskQueue
from api.runner import RunnerFactory, default_runner_factory
from config import Settings, get_settings
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry
from evaluation.trace import TraceStore
from storage.cache import CacheFacade, get_cache
from storage.db import Database

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_settings_dep() -> Settings:
    """全局配置（转发 :func:`config.get_settings`，保持依赖入口统一）。"""
    return get_settings()


@lru_cache(maxsize=1)
def get_database() -> Database:
    """数据库门面：建表 + 补列都在这里完成（每个进程只做一次）。"""
    database = Database()
    database.init_db()
    return database


@lru_cache(maxsize=1)
def get_cache_facade() -> CacheFacade:
    """缓存门面（Redis 优先，不可用时自动降级为进程内缓存）。"""
    return get_cache()


@lru_cache(maxsize=1)
def get_trace_store() -> TraceStore:
    """埋点存储（内部自带线程锁，可跨线程复用）。"""
    return TraceStore()


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    """SSE 事件总线（进程内唯一；loop 由 ``TaskQueue.start()`` 注入）。"""
    return EventBus()


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    """内置工具注册表（``POST /tools/{name}/invoke`` 用）。

    注意：高危工具的 HITL 审批回调**不在这里注入**——默认值是 ``None``，
    按 ``ToolRegistry`` 的 fail-closed 语义，高危调用一律拒绝。放行必须由路由
    显式构造带 approver 的临时注册表（见 :mod:`api.routes.tools`）。

    T04：注册完成后调用 ``knowledge_search.set_knowledge_service(service)``
    （注册先于注入）；rag 依赖缺失时注入静默跳过，工具调用时走结构化失败字符串。
    """
    settings = get_settings()
    registry = load_builtin_tools(
        ToolRegistry(settings=settings, enable_hitl=settings.enable_hitl)
    )
    _inject_knowledge_service(registry)
    return registry


def _inject_knowledge_service(registry: ToolRegistry) -> None:
    """给 ``knowledge_search`` 注入知识库服务（rag 不可用时静默跳过，不拖垮装配）。"""
    if not registry.has("knowledge_search"):
        return
    try:
        service = get_knowledge_service()
    except Exception:  # noqa: BLE001 - 注入失败不阻断工具注册表装配
        logger.warning("knowledge_search 服务注入失败（知识库降级）", exc_info=True)
        return
    if service is None:
        return
    from core.tools.builtin import knowledge_search  # noqa: PLC0415 - 懒加载纪律

    knowledge_search.set_knowledge_service(service)
    logger.debug("knowledge_search 已注入知识库服务")


@lru_cache(maxsize=1)
def get_runner_factory() -> RunnerFactory:
    """编排器工厂（**测试的主要替换点**：override 成 Mock 版本即可零 token）。

    事件落库（T02 埋点）所需的 ``Database`` 由 ``default_runner_factory``
    自行懒取（见其 docstring），故此处**保持两参调用**——测试用两参 lambda
    替换 ``default_runner_factory`` 的既有约定不受影响。
    """
    return default_runner_factory(get_settings(), get_trace_store())


@lru_cache(maxsize=1)
def get_task_queue() -> TaskQueue:
    """任务队列（进程内唯一实例；``lifespan`` 负责 start / stop）。"""
    settings = get_settings()
    return TaskQueue(
        settings=settings,
        database=get_database(),
        cache=get_cache_facade(),
        trace_store=get_trace_store(),
        event_bus=get_event_bus(),
        runner_factory=get_runner_factory(),
        max_concurrent=settings.api_max_concurrent_tasks,
        queue_size=settings.api_queue_max_size,
    )


@lru_cache(maxsize=1)
def get_knowledge_service():
    """知识库服务门面（rag 依赖缺失时返回 None——平台其余功能照常跑）。

    懒加载纪律（m2_design.md §7.4 / D3）：

    * ``rag.service`` 只在**调用时** import（rag/__init__.py 零 import），
      未装 rag 依赖的环境 API 照常启动、5 个旧工具照常可用；
    * 构造失败（依赖缺失/配置错）也只记 WARNING 返回 None，
      ``/knowledge/*`` 路由（T03）按 ``rag_unavailable`` 503 处理；
    * ``start_knowledge_worker`` 由 lifespan 在 T03 接入，本任务只保证
      服务可获取、状态可轮询。
    """
    try:
        from rag.service import KnowledgeService  # noqa: PLC0415 - 懒加载纪律
    except Exception as exc:  # noqa: BLE001 - 依赖缺失是预期分支，不是故障
        logger.warning("rag 依赖不可用，知识库服务未启用：%s", exc)
        return None
    try:
        service = KnowledgeService(settings=get_settings(), database=get_database())
        service.initialize()
        return service
    except Exception:  # noqa: BLE001
        logger.exception("KnowledgeService 初始化失败（服务降级）")
        return None


def verify_token(request: Request) -> None:
    """校验 Bearer Token（未配置 token 时直接放行）。

    常量时间比较用 ``secrets.compare_digest``：普通 ``==`` 在字符串比较上会
    按首个不同字节提前返回，理论上可以被计时攻击逐字节猜出 token。

    Raises:
        ApiError: 401 + ``WWW-Authenticate: Bearer``。
    """
    settings = get_settings()
    if not settings.api_auth_enabled:
        return
    header = request.headers.get("authorization", "")
    scheme, _, credential = header.partition(" ")
    expected = settings.api_auth_token.get_secret_value().strip()
    if scheme.lower() != "bearer" or not secrets.compare_digest(credential.strip(), expected):
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "缺少或错误的 Bearer Token",
            status=401,
            **{"WWW-Authenticate": "Bearer"},
        )


def submit_status() -> str:
    """新任务落库时的初始状态（路由与测试共用的单一真源）。"""
    return STATUS_QUEUED


def reset_api_caches() -> None:
    """清空本模块的全部 ``lru_cache``。

    两个必须调用它的时机：

    1. 测试里改完环境变量（配合 ``config.reset_settings_cache()``）；
    2. 想彻底重建队列（比如把上一轮残留的 ``_running`` 丢掉）。
    """
    get_settings_dep.cache_clear()
    get_database.cache_clear()
    get_cache_facade.cache_clear()
    get_trace_store.cache_clear()
    get_event_bus.cache_clear()
    get_tool_registry.cache_clear()
    get_runner_factory.cache_clear()
    get_task_queue.cache_clear()
    get_knowledge_service.cache_clear()


__all__ = [
    "get_cache_facade",
    "get_database",
    "get_event_bus",
    "get_knowledge_service",
    "get_runner_factory",
    "get_settings_dep",
    "get_task_queue",
    "get_tool_registry",
    "get_trace_store",
    "reset_api_caches",
    "submit_status",
    "verify_token",
]
