"""路由汇总：按 tasks → tools → models → eval → health → stats 的顺序注册。

模块文件名 ``eval.py`` 与内置函数 ``eval`` 同名，因此导入时**一律用别名**
``eval_router``，避免在包作用域里遮蔽内置函数（``from api.routes import eval``
之后本模块内再调用 ``eval(...)`` 就会炸，且报错极难看懂）。
"""

from __future__ import annotations

from api.routes.config import router as config_router
from api.routes.eval import router as eval_router
from api.routes.health import router as health_router
from api.routes.knowledge import router as knowledge_router
from api.routes.models import router as models_router
from api.routes.stats import router as stats_router
from api.routes.tasks import router as tasks_router
from api.routes.tools import router as tools_router

#: 注册顺序（设计文档 §5 T03 第 5 步；``models`` 紧跟 ``tools`` —— 两者同为「只读注册表」）
#:
#: ⚠️ 这个元组**没有被 ``api/main.py`` 消费**（那边是七/八条 ``include_router`` 手写），
#: 所以只往这里加一行会得到一个"看起来注册了、其实 404"的路由，且没有任何报错。
#: 加路由必须三处同改：本文件的 import、本元组、``main.py`` 的 ``include_router``
#: （方案 §4 P-7；用例直接打真实路径就是为了盯住第三处）。
ROUTERS = (
    tasks_router,
    tools_router,
    models_router,
    config_router,
    eval_router,
    health_router,
    stats_router,
    knowledge_router,
)

__all__ = [
    "ROUTERS",
    "config_router",
    "eval_router",
    "health_router",
    "knowledge_router",
    "models_router",
    "stats_router",
    "tasks_router",
    "tools_router",
]
