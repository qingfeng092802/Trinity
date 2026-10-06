"""看板统计路由：``GET /stats/dashboard``。

口径（与 ``evaluation/metrics.py`` 对齐，不美化数字）
----------------------------------------------------
* **完成率只认 ``done``**：``aborted``（迭代上限强制收口）不算完成；
* **平均分只算有 score 的任务**：没跑过 judge / 评审没给分的条目不参与平均；
* **无数据日补零**：近 14 天逐日序列必须正好 14 条，前端不用再补；
* **时间一律北京时间 +08:00**：DB 里的 naive UTC 经 :func:`api.schemas.to_cn` 转换；
* **金额一律 ``round(x, 6)``**。

系统状态面板取数方式与 ``GET /health`` 完全一致（零 token，不真实调用 LLM）。

路由用 ``def``（纯 DB 读 + 纯函数计算，不触碰队列内存态），交给 FastAPI 的
线程池执行，避免阻塞事件循环。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import text

from api.deps import get_cache_facade, get_database
from api.schemas import DailyStat, DashboardStatsResponse, DashboardSystemInfo, TodayStat, to_cn
from config import get_settings
from core.llm.pricing import CN_TZ, is_peak, next_off_peak, now, price_multiplier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["stats"])

#: 统计窗口（天）：近 14 天含今天
DASHBOARD_DAYS = 14


def _check_db_ok() -> bool:
    """SQLite 探活（与 ``api.routes.health._check_database`` 同口径，只回布尔）。"""
    try:
        database = get_database()
        with database.session() as handle:
            handle.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 统计页不能因探活失败而 500
        logger.warning("看板统计：数据库探活失败：%s", exc)
        return False
    return True


def dashboard_stats() -> DashboardStatsResponse:
    """汇总 Dashboard 全部指标。

    Returns:
        今日指标 + 近 14 天逐日序列 + 系统状态。
    """
    settings = get_settings()
    current_cn = now()
    today_cn = current_cn.date()

    # 近 14 天窗口：起始日 00:00（北京时间）对应的 UTC naive 下界
    window_start_cn = datetime(
        today_cn.year, today_cn.month, today_cn.day, tzinfo=CN_TZ
    ) - timedelta(days=DASHBOARD_DAYS - 1)
    cutoff_utc_naive = window_start_cn.astimezone(timezone.utc).replace(tzinfo=None)

    records = get_database().list_tasks_since(cutoff_utc_naive)

    # 按北京时间日期聚合
    buckets: dict[str, dict[str, object]] = {}
    for record in records:
        day = to_cn(record.created_at).date().isoformat()
        bucket = buckets.setdefault(day, {"count": 0, "done": 0, "cost": 0.0, "scores": []})
        bucket["count"] = int(bucket["count"]) + 1  # type: ignore[call-overload]
        if record.status == "done":
            bucket["done"] = int(bucket["done"]) + 1  # type: ignore[call-overload]
        bucket["cost"] = float(bucket["cost"]) + float(record.cost or 0.0)  # type: ignore[arg-type]
        if record.score is not None:
            bucket["scores"].append(int(record.score))  # type: ignore[union-attr]

    def _build_stat(day: str) -> tuple[DailyStat, TodayStat]:
        """某一天的 DailyStat；若是今天顺带产出 TodayStat（同一份聚合，两种投影）。"""
        bucket = buckets.get(day, {"count": 0, "done": 0, "cost": 0.0, "scores": []})
        count = int(bucket["count"])  # type: ignore[arg-type]
        done_count = int(bucket["done"])  # type: ignore[arg-type]
        scores: list[int] = list(bucket["scores"])  # type: ignore[arg-type]
        stat = DailyStat(
            date=day,
            count=count,
            done_count=done_count,
            cost=round(float(bucket["cost"]), 6),  # type: ignore[arg-type]
            avg_score=round(sum(scores) / len(scores), 2) if scores else None,
        )
        today_stat = TodayStat(
            count=count,
            done_count=done_count,
            completion_rate=(done_count / count) if count else 0.0,
            avg_score=stat.avg_score,
            total_cost=stat.cost,
        )
        return stat, today_stat

    daily: list[DailyStat] = []
    today_stat: TodayStat | None = None
    for offset_days in range(DASHBOARD_DAYS):
        day = (today_cn - timedelta(days=DASHBOARD_DAYS - 1 - offset_days)).isoformat()
        stat, today_projection = _build_stat(day)
        daily.append(stat)
        if day == today_cn.isoformat():
            today_stat = today_projection

    assert today_stat is not None  # noqa: S101 - 窗口必含今天，逻辑上不可达 None

    system = DashboardSystemInfo(
        peak_pricing=is_peak(current_cn),
        price_multiplier=round(price_multiplier(current_cn), 4),
        next_off_peak=next_off_peak(current_cn).isoformat(),
        llm_configured=settings.llm_configured,
        cache_backend="redis" if get_cache_facade().using_redis else "memory",
        db_ok=_check_db_ok(),
    )
    return DashboardStatsResponse(
        today=today_stat,
        daily=daily,
        system=system,
        generated_at=now(),
    )


@router.get(
    "/stats/dashboard",
    response_model=DashboardStatsResponse,
    summary="Dashboard 看板统计（今日指标 / 近 14 天趋势 / 系统状态）",
)
def get_dashboard_stats() -> DashboardStatsResponse:
    """看板统计入口（``def`` 路由，DB 读在线程池执行）。"""
    return dashboard_stats()


__all__ = ["DASHBOARD_DAYS", "router"]
