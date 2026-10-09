"""持久化层：SQLAlchemy 业务表 + 带降级的缓存。

三个模块：

* :mod:`storage.models` —— 三张业务表（tasks / agents / eval_records）；
* :mod:`storage.db` —— :class:`Database` 门面，建表与增删改查都走它；
* :mod:`storage.cache` —— :class:`CacheFacade`，Redis 优先、不通则降级为进程内缓存。

节点级埋点仍然归 ``evaluation.TraceStore``（裸 sqlite3 的 ``traces`` 表）全权管理，
本层**不重复建模**，避免两套 ORM 争同一张表。
"""

from __future__ import annotations

from storage.cache import (
    STATE_PREFIX,
    STATS_PREFIX,
    CacheBackend,
    CacheFacade,
    MemoryCache,
    RedisCache,
    get_cache,
)
from storage.db import DEFAULT_AGENTS, Database
from storage.models import AgentRecord, Base, EvalRecord, TaskRecord

__all__ = [
    "DEFAULT_AGENTS",
    "STATE_PREFIX",
    "STATS_PREFIX",
    "AgentRecord",
    "Base",
    "CacheBackend",
    "CacheFacade",
    "Database",
    "EvalRecord",
    "MemoryCache",
    "RedisCache",
    "TaskRecord",
    "get_cache",
]
