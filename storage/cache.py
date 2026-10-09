"""缓存层：Redis 优先，不可用时自动退化为进程内缓存。

设计原则：**缓存永远不能拖垮主流程**。Redis 没装包、没起服务、网络不通、
序列化失败，一律降级成内存缓存，绝不向上抛异常——它是加速器，不是依赖。

用途有两个：

1. 缓存运行中状态（``state:{task_id}``），配合 checkpointer 做**断点续跑**；
2. 缓存高开销的只读数据（如评测看板的统计结果）。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any, Protocol

from config import Settings, get_settings

logger = logging.getLogger(__name__)

#: 状态缓存的键前缀（断点续跑用）
STATE_PREFIX = "state:"
#: 看板统计的键前缀
STATS_PREFIX = "stats:"
#: 运行进度缓存的键前缀（M1：SSE 与轮询消费的轻量进度视图）
PROGRESS_PREFIX = "progress:"


class CacheBackend(Protocol):
    """缓存后端协议：get / set / delete / clear / ping。"""

    def ping(self) -> bool:
        """健康检查；门面据此决定是否降级。"""
        ...  # pragma: no cover - 协议声明

    def get(self, key: str) -> Any | None:
        """取值；不存在或已过期返回 None。"""
        ...  # pragma: no cover - 协议声明

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """存值，返回是否成功。"""
        ...  # pragma: no cover - 协议声明

    def delete(self, key: str) -> bool:
        """删键，返回是否真的删掉了。"""
        ...  # pragma: no cover - 协议声明

    def clear(self) -> int:
        """清空并返回清理条数。"""
        ...  # pragma: no cover - 协议声明


def _dumps(value: Any) -> str:
    """序列化；不可序列化的对象退化为字符串，避免整条链路崩掉。"""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


class MemoryCache:
    """进程内缓存（带过期时间）。单进程够用，多进程/多副本时请用 Redis。"""

    def __init__(self, default_ttl: int = 3600) -> None:
        self.default_ttl = default_ttl
        self._data: dict[str, tuple[Any, float]] = {}

    def ping(self) -> bool:
        """进程内缓存永远可用。"""
        return True

    def get(self, key: str) -> Any | None:
        """取值；过期视为未命中并顺手清掉。"""
        hit = self._data.get(key)
        if hit is None:
            return None
        value, expires_at = hit
        if expires_at <= time.time():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """存值。"""
        seconds = self.default_ttl if ttl is None else ttl
        self._data[key] = (value, time.time() + max(seconds, 1))
        return True

    def delete(self, key: str) -> bool:
        """删键。"""
        return self._data.pop(key, None) is not None

    def clear(self) -> int:
        """清空。"""
        count = len(self._data)
        self._data.clear()
        return count

    def __len__(self) -> int:
        """当前条目数（未清理过期项，仅便于测试）。"""
        return len(self._data)


class RedisCache:
    """Redis 缓存。所有异常都被吞掉并转成返回值，不向上抛。

    ``redis`` 是**可选**依赖（见 pyproject 的 ``[project.optional-dependencies] redis``）：
    没装、没起服务、连不上，三者的处理完全一致——本实例退化为「永远不可用」，
    由 :class:`CacheFacade` 自动降级到 :class:`MemoryCache`。这与本模块顶部的
    「缓存永远不能拖垮主流程」是同一条纪律，不能只保护``ping()`` 而不保护构造。

    Args:
        client: 已构造好的 Redis 客户端；不传则按 ``redis_url`` 自己连。
        url: 连接串（``client`` 为空时使用）。
        settings: 配置；为空时取全局单例。
        default_ttl: 默认存活秒数。
        socket_timeout: 连接/读写超时（秒）。
    """

    def __init__(
        self,
        client: Any = None,
        *,
        url: str | None = None,
        settings: Settings | None = None,
        default_ttl: int = 3600,
        socket_timeout: float = 1.0,
    ) -> None:
        self.default_ttl = default_ttl
        self._client = client
        if self._client is None:
            # 延迟导入：只有真的用 Redis 时才付这个依赖成本；ImportError 必须就地
            # 消化——否则 CacheFacade 默认 use_redis=True 会把 ImportError 冒泡到
            # 调用方，整个 API 起不来（redis 明明是可选依赖，不该有这种杀伤力）。
            try:
                import redis
            except ImportError as exc:
                logger.warning(
                    "redis 包未安装，缓存退化为进程内缓存（功能不受影响；"
                    "需要 Redis 时 pip install trinity[redis]）：%s",
                    exc,
                )
                return
            resolved = settings or get_settings()
            self._client = redis.Redis.from_url(
                url or resolved.redis_url,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                decode_responses=True,
            )

    @property
    def client(self) -> Any:
        """底层客户端（测试与运维排查用）；Redis 不可用时为 ``None``。"""
        return self._client

    def ping(self) -> bool:
        """连通性探测；客户端不存在（依赖缺失）同样返回 False，不抛异常。"""
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:  # noqa: BLE001 - 缓存不能拖垮主流程
            return False

    def get(self, key: str) -> Any | None:
        """取值；依赖缺失（``_client`` 为 ``None``）按未命中处理。"""
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.debug("Redis get 失败（按未命中处理）：%s", exc)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """存值；写入失败或依赖缺失返回 False（调用方据此降级）。"""
        if self._client is None:
            return False
        seconds = self.default_ttl if ttl is None else ttl
        try:
            self._client.setex(key, max(int(seconds), 1), _dumps(value))
            return True
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.debug("Redis set 失败：%s", exc)
            return False

    def delete(self, key: str) -> bool:
        """删键；依赖缺失返回 False。"""
        if self._client is None:
            return False
        try:
            return bool(self._client.delete(key))
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.debug("Redis delete 失败：%s", exc)
            return False

    def clear(self) -> int:
        """清空当前 db（只清业务键，用 SCAN 避免 KEYS 阻塞）。"""
        removed = 0
        if self._client is None:
            return removed
        try:
            for key in self._client.scan_iter(match="*"):
                self._client.delete(key)
                removed += 1
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.debug("Redis clear 失败：%s", exc)
        return removed


class CacheFacade:
    """带降级的缓存门面：优先用 Redis，不通就用内存。

    Args:
        primary: 首选后端；默认按配置连 Redis。
        fallback: 降级后端；默认是进程内缓存。
    """

    def __init__(
        self,
        primary: CacheBackend | None = None,
        fallback: CacheBackend | None = None,
        *,
        settings: Settings | None = None,
        default_ttl: int | None = None,
        use_redis: bool = True,
    ) -> None:
        resolved = settings or get_settings()
        self.default_ttl = default_ttl or resolved.cache_ttl_seconds
        # 注意：这里必须显式判断 None，不能写 ``fallback or MemoryCache(...)``。
        # MemoryCache 实现了 __len__，空实例是 falsy 的，用 or 兜底会把它静默丢掉，
        # 结果就是调用方传进来的后端根本没被用上（且没有任何报错）。
        self.fallback: CacheBackend = (
            fallback if fallback is not None else MemoryCache(default_ttl=self.default_ttl)
        )
        self.primary: CacheBackend | None = None
        self.backend: CacheBackend = self.fallback
        if use_redis or primary is not None:
            # primary 显式传入时优先信它（测试注入假客户端就靠这条路径）；
            # 否则按配置构造 RedisCache —— 构造器内部已把「redis 包没装」消化成
            # 不可用状态，不会向上抛 ImportError。
            candidate = primary if primary is not None else RedisCache(
                settings=resolved, default_ttl=self.default_ttl
            )
            if candidate.ping():
                self.primary = candidate
                self.backend = candidate
            else:
                logger.warning("Redis 不可用，缓存降级为进程内缓存（功能不受影响）")

    @property
    def using_redis(self) -> bool:
        """当前是否真的在用 Redis。"""
        return self.primary is not None

    def get(self, key: str) -> Any | None:
        """取值；首选后端读不到时再读降级后端。"""
        value = self.backend.get(key)
        if value is None and self.backend is not self.fallback:
            value = self.fallback.get(key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """存值：首选后端写失败就退回降级后端，保证数据不丢。"""
        if not self.backend.set(key, value, ttl):
            return self.fallback.set(key, value, ttl)
        return True

    def delete(self, key: str) -> bool:
        """删键：两个后端都删。"""
        removed = self.backend.delete(key)
        if self.backend is not self.fallback:
            removed = self.fallback.delete(key) or removed
        return removed

    def clear(self) -> int:
        """清空：两个后端都清。"""
        removed = self.backend.clear()
        if self.backend is not self.fallback:
            removed += self.fallback.clear()
        return removed

    # -------------------------------------------------- 断��续跑（状态缓存） --
    def save_state(self, task_id: str, state: Mapping[str, Any]) -> bool:
        """缓存运行中状态，供断点续跑恢复。"""
        return self.set(f"{STATE_PREFIX}{task_id}", dict(state))

    def load_state(self, task_id: str) -> dict[str, Any] | None:
        """读回运行中状态。"""
        value = self.get(f"{STATE_PREFIX}{task_id}")
        return value if isinstance(value, dict) else None

    def drop_state(self, task_id: str) -> bool:
        """任务结束后清掉状态，避免缓存无限膨胀。"""
        return self.delete(f"{STATE_PREFIX}{task_id}")

    # ------------------------------------------------------ 运行进度（M1） --
    def save_progress(self, task_id: str, progress: Mapping[str, Any]) -> bool:
        """写一份轻量进度视图（``GET /tasks/{id}.progress`` 与 SSE 快照读它）。

        刻意**不**复用 ``state:{task_id}``：后者是可恢复的完整 ``AgentState``
        （含 ``final_answer``，可达数 KB），而进度视图只要几十字节；混在一个键里
        既放大 Redis 与序列化开销，又会让「断点续跑」与「进度展示」两种语义互相
        污染（设计文档 §7.4 A1）。
        """
        return self.set(f"{PROGRESS_PREFIX}{task_id}", dict(progress))

    def load_progress(self, task_id: str) -> dict[str, Any] | None:
        """读回进度视图；不存在或类型不对返回 ``None``（调用方按降级处理）。"""
        value = self.get(f"{PROGRESS_PREFIX}{task_id}")
        return value if isinstance(value, dict) else None

    def drop_progress(self, task_id: str) -> bool:
        """任务进入终态后清掉进度，避免缓存无限膨胀。"""
        return self.delete(f"{PROGRESS_PREFIX}{task_id}")


def get_cache(
    settings: Settings | None = None,
    *,
    use_redis: bool = True,
    refresh: bool = False,
) -> CacheFacade:
    """取全局缓存门面（进程内单例，懒创建）。"""
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = CacheFacade(settings=settings, use_redis=use_redis)
    return _CACHE


_CACHE: CacheFacade | None = None


__all__ = [
    "STATE_PREFIX",
    "STATS_PREFIX",
    "CacheBackend",
    "CacheFacade",
    "MemoryCache",
    "RedisCache",
    "get_cache",
]
