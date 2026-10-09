"""每任务一份的运行期上下文（目前只有 RAG 检索条数上限）。

为什么走 contextvar 而不是把 ``top_k`` 一路传进节点签名：工具是被模型以 kwargs 调起来的
（:meth:`core.tools.registry.ToolRegistry.invoke` 里 ``spec.func(**kwargs)``）。
"这条任务的检索上限"是**用户/部署**的参数，不是模型的参数 —— 让它变成工具签名的一部分，
等于把"用户配的东西"放进"模型可写的东西"里，模型自己就能覆盖它。
contextvar 的好处正是：worker 线程内设一次，工具在同一线程读，
中间那三层（graph → executor → registry）一行签名都不用改。

⚠️ **线程池会复用线程**（``api/queue.py`` 的 ``ThreadPoolExecutor``，
``max_workers=api_max_concurrent_tasks``）⇒ 设过就必须 reset。
``api/queue.py`` 在 ``finally`` 里做这件事；漏掉的后果不是崩，而是
"下一条任务的检索条数被上一条限制住" —— 不报错、只是数字莫名其妙。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from config import get_settings

__all__ = [
    "clamp_top_k",
    "default_top_k",
    "reset_task_top_k",
    "set_task_top_k",
    "task_top_k",
    "task_top_k_scope",
    "TOP_K_HARD_MAX",
    "TOP_K_HARD_MIN",
]

#: 工具签名里 ``Field(ge=1, le=20)`` 的两个硬界。这里**抄一份**是故意的：
#: 闸门要在 clamp 之前把非法值挡住，而工具的 Field 只在 pydantic 校验时生效 ——
#: 校验失败会让整次工具调用变成 ``failed``，那不是"用户填了 999"想要的结果。
TOP_K_HARD_MIN = 1
TOP_K_HARD_MAX = 20

#: 本任务用户配的检索上限；``None`` = 用户没配（不限制模型自己选的条数）。
_task_top_k: ContextVar[int | None] = ContextVar("trinity.task_rag_top_k", default=None)


def default_top_k() -> int:
    """部署级默认检索条数 —— :attr:`config.Settings.knowledge_top_k` 的**唯一读取点**。

    ⚠️ 这个字段在 2026-09-26 之前是死的（全仓零消费者），默认值实际来自
    ``knowledge_search`` 工具签名上写死的 ``= 5``。两处各写一份 5 就是两份口径，
    所以把它接上成"签名默认值从这里取"，而不是删掉字段留个说不清的 env 名
    （``.env.example`` 里 ``KNOWLEDGE_TOP_K=5`` 那行还活着，删字段会让它变成
    "写了没人读"的那类配置 —— 与本仓库 R-04 的教训同一形状）。

    ⚠️ 生效条件：工具签名是在 **import 期**求值的（Python 的默认参数就求值一次），
    所以改 ``KNOWLEDGE_TOP_K`` 要重启进程才看得见，光改 ``.env`` 不会立刻变。
    填错的症状：检索条数与面板上那句"默认 N 条"不一致，而不会报错。
    """
    value = int(get_settings().knowledge_top_k)
    return max(TOP_K_HARD_MIN, min(value, TOP_K_HARD_MAX))


def set_task_top_k(value: int | None) -> Token[Any] | None:
    """把本任务的上限放进 contextvar；``None`` 表示"不设限"，返回 ``None`` 令牌。

    越界的值在这里挡（夹到硬界），而不是留给 pydantic 把整次工具调用打成失败。
    """
    if value is None:
        return None
    return _task_top_k.set(max(TOP_K_HARD_MIN, min(int(value), TOP_K_HARD_MAX)))


def reset_task_top_k(token: Token[Any] | None) -> None:
    """还原 contextvar（``token is None`` 时是空操作 —— 没设过就不必还原）。"""
    if token is not None:
        _task_top_k.reset(token)


def task_top_k() -> int | None:
    """本任务配的检索上限；没配返回 ``None``。"""
    return _task_top_k.get()


@contextmanager
def task_top_k_scope(value: int | None) -> Iterator[None]:
    """测试与直接调用方用的作用域版本（保证出去时还原，异常也不例外）。"""
    token = set_task_top_k(value)
    try:
        yield
    finally:
        reset_task_top_k(token)


def clamp_top_k(model_supplied: int, ceiling: int | None) -> int:
    """模型这次要几条 ⇒ 实际给几条。

    口径（U-4 拍的那一条）：用户配的值是**上限**，不是"替模型决定"。

    * 用户没配（``ceiling is None``）→ 模型要多少给多少（现状行为，一字不变）；
    * 用户配了 → 模型可以要得更少（那是更省、更安全的方向，尊重它），
      要得更多则夹到上限。

    ⚠️ 反向实现（"用户配了就一律用用户的值"）看着更"听话"，实际是把模型的判断覆盖掉：
    模型觉得只要 2 条就够，用户配 5 就硬要 5 条 —— 多出来的 3 条低相关片段会挤进
    prompt，那是**变差的检索**而不是更严格的用户意志。
    """
    if ceiling is None:
        return max(TOP_K_HARD_MIN, min(int(model_supplied), TOP_K_HARD_MAX))
    return max(TOP_K_HARD_MIN, min(int(model_supplied), int(ceiling), TOP_K_HARD_MAX))
