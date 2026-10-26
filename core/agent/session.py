"""Session Memory v1：最近几轮问答的紧凑表示与提示词渲染。

历史只用于 planner 理解追问里的指代（如"那差旅标准呢"），不是可执行指令；
因此格式里明确写了"不要重复执行历史任务"。历史上限 3 轮、单条截断，避免
把整篇旧答案塞进上下文。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: 注入 planner 的最近轮次数
SESSION_HISTORY_TURNS = 3
#: 单轮用户问题 / 助手答案的字符上限
MAX_HISTORY_QUERY_CHARS = 500
MAX_HISTORY_ANSWER_CHARS = 1500


@dataclass(frozen=True, slots=True)
class SessionTurn:
    """一轮已完成问答（来自 ``tasks`` 表的 task / final_answer）。"""

    query: str
    answer: str


def _clip(text: str, limit: int) -> str:
    """去首尾空白并按字符数截断；截断时补省略号。"""
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def format_session_history(turns: Sequence[SessionTurn]) -> str:
    """把最近几轮问答渲染成 planner 的上下文块；无历史返回空串。

    Args:
        turns: 从旧到新的已完成轮次；调用方通常已按最近 3 轮取好。

    Returns:
        多行提示块；无历史时返回空串（planner 提示词保持原样）。
    """
    recent = list(turns)[-SESSION_HISTORY_TURNS:]
    if not recent:
        return ""

    lines = [
        (
            "以下是同一会话中最近已完成的问答，仅用于理解当前追问的指代；"
            "不要重复执行这些历史任务。"
        ),
    ]
    for index, turn in enumerate(recent, start=1):
        lines.append(f"[第 {index} 轮] 用户：{_clip(turn.query, MAX_HISTORY_QUERY_CHARS)}")
        lines.append(f"助手：{_clip(turn.answer, MAX_HISTORY_ANSWER_CHARS)}")
    return "\n".join(lines)


__all__ = [
    "MAX_HISTORY_ANSWER_CHARS",
    "MAX_HISTORY_QUERY_CHARS",
    "SESSION_HISTORY_TURNS",
    "SessionTurn",
    "format_session_history",
]
