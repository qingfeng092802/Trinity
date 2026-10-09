"""REST API 层（阶段 5 · M1）。

在现有**同步**编排内核之上加一层 FastAPI + 异步任务队列：
``POST /tasks`` 立即返回 ``task_id``，任务在后台线程池里跑，调用方可以轮询
``GET /tasks/{id}`` 或订阅 ``GET /tasks/{id}/stream``（SSE 节点级增量）。

分层：``constants`` → ``errors`` → ``schemas`` → ``events`` → ``runner`` →
``queue`` → ``deps`` → ``main`` → ``routes``，依赖只从上往下，不允许反向。
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
