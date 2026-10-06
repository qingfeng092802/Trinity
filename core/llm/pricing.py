"""DeepSeek 计费时段：高峰 / 低谷。

官方规则（https://api-docs.deepseek.com/quick_start/pricing）：高峰时段为
**UTC 周一至周五 01:00-04:00 与 06:00-10:00**，换算北京时间（UTC+8）正好是
**周一至周五 09:00-12:00、14:00-18:00**；低谷价是高峰价的**一半**。

本项目据此提供两件事：

1. :func:`is_peak` / :func:`next_off_peak` —— 让「现在能不能跑」变成可判断的事实；
2. :func:`price_multiplier` —— 成本估算按调用时刻套用折扣，报表不会把低谷价按高峰算。

时区刻意用固定 UTC+8 而不是 ``zoneinfo``：中国不使用夏令时，而 Windows 上
``zoneinfo`` 需要额外装 ``tzdata`` 才有区域数据库，没必要为了一个偏移量引入依赖。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

#: 北京时间（UTC+8，中国无夏令时）
CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

#: 高峰窗口（北京时间，左闭右开）
PEAK_WINDOWS: tuple[tuple[time, time], ...] = (
    (time(9, 0), time(12, 0)),
    (time(14, 0), time(18, 0)),
)

#: 高峰发生在周一至周五（``date.weekday()``：周一 = 0）
PEAK_WEEKDAYS: frozenset[int] = frozenset({0, 1, 2, 3, 4})

#: 低谷时的价格系数（低谷 = 高峰的一半）
OFF_PEAK_MULTIPLIER = 0.5


def now() -> datetime:
    """当前北京时间。"""
    return datetime.now(CN_TZ)


def _as_cn(moment: datetime | None) -> datetime:
    """统一转成北京时间；naive 时间按北京时间解释。"""
    if moment is None:
        return now()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=CN_TZ)
    return moment.astimezone(CN_TZ)


def is_peak(moment: datetime | None = None) -> bool:
    """给定时刻是否处于高峰计费时段。"""
    current = _as_cn(moment)
    if current.weekday() not in PEAK_WEEKDAYS:
        return False
    clock = current.time()
    return any(start <= clock < end for start, end in PEAK_WINDOWS)


def price_multiplier(moment: datetime | None = None) -> float:
    """按时刻给价格系数：高峰 1.0，低谷 0.5。"""
    return 1.0 if is_peak(moment) else OFF_PEAK_MULTIPLIER


def next_off_peak(moment: datetime | None = None) -> datetime:
    """下一次进入低谷的时刻；当前已是低谷时返回当前时刻。"""
    current = _as_cn(moment)
    if not is_peak(current):
        return current
    for start, end in PEAK_WINDOWS:
        if start <= current.time() < end:
            # 高峰窗口不会跨天（12:00 / 18:00 结束），所以窗口终点就是低谷起点
            return current.replace(
                hour=end.hour, minute=end.minute, second=0, microsecond=0
            )
    return current  # pragma: no cover - is_peak 为真时必然落在某个窗口内


def window_description() -> str:
    """高峰窗口的可读描述。"""
    return "周一至周五 09:00-12:00、14:00-18:00（北京时间）"


def status_line(moment: datetime | None = None) -> str:
    """渲染成一行状态提示，给 CLI 与页面直接用。"""
    current = _as_cn(moment)
    clock = current.strftime("%H:%M")
    if not is_peak(current):
        return f"当前 {clock}（北京）属**低谷时段**：单价是高峰的一半"
    target = next_off_peak(current)
    minutes = max(int((target - current).total_seconds() // 60), 0)
    return (
        f"当前 {clock}（北京）属**高峰时段**（{window_description()}）："
        f"单价是低谷的 2 倍，{target.strftime('%H:%M')} 后进入低谷（约 {minutes} 分钟后）"
    )


__all__ = [
    "CN_TZ",
    "OFF_PEAK_MULTIPLIER",
    "PEAK_WEEKDAYS",
    "PEAK_WINDOWS",
    "is_peak",
    "next_off_peak",
    "now",
    "price_multiplier",
    "status_line",
    "window_description",
]
