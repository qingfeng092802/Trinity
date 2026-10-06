"""API 层的**全局唯一常量源**。

放在这里而不是散落到各模块，是为了让「状态名 / 事件名 / 缓存前缀 / 阈值」
只有一份定义：SSE 的帧名写错一个字母，客户端就永远收不到那个事件，而这类
错误在单元测试里极难发现（测试往往按同样拼错的常量断言）。

本模块**不 import 任何项目内模块**（连 config 都不 import），这样
``storage/db.py`` 与 ``evaluation/trace.py`` 也能安全地引用它而不会有循环导入。
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# 任务状态（与 PRD §4.1 状态机一致；TaskRecord.status 是 String(16)，全部合规）
# --------------------------------------------------------------------------- #
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ABORTED = "aborted"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"

#: 终态集合：进入这些状态后不再有任何写入（除了一次性读取展示）
API_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {STATUS_DONE, STATUS_ABORTED, STATUS_FAILED, STATUS_CANCELED}
)

#: 非终态集合（``mark_canceled`` 的 CAS 条件用得上）
API_ACTIVE_STATUSES: frozenset[str] = frozenset({STATUS_QUEUED, STATUS_RUNNING})

# --------------------------------------------------------------------------- #
# 轨迹事件（task_events 表）状态值 —— 设计文档 §3.2 status 列注释
#   与「任务状态」是两个命名空间：事件 status 描述**单条事件**的成败，
#   任务 status 描述**整条任务**的状态机，两者刻意不复用同一组常量名，
#   避免 X1/X2 那类「同名不同义」的串号。
# --------------------------------------------------------------------------- #
#: 单条事件成功
STATUS_SUCCESS = "success"
#: 单条事件失败
STATUS_EVENT_FAILED = "failed"
#: 单条事件超时
STATUS_EVENT_TIMEOUT = "timeout"

#: 事件 status 白名单（task_events.status 列的合法取值）
TASK_EVENT_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_SUCCESS,
        STATUS_EVENT_FAILED,
        STATUS_EVENT_TIMEOUT,
        STATUS_RUNNING,
        STATUS_DONE,
        STATUS_ABORTED,
        STATUS_CANCELED,
    }
)

# --------------------------------------------------------------------------- #
# 知识文档索引状态机（m2_design.md §7.2；唯一来源，rag/ingest.py 与 API 层共用）
# --------------------------------------------------------------------------- #
DOC_PENDING = "pending"
DOC_PARSING = "parsing"
DOC_CHUNKING = "chunking"
DOC_EMBEDDING = "embedding"
DOC_READY = "ready"
DOC_FAILED = "failed"

#: 索引推进中的状态（重启恢复时统一标 failed 的对象）
DOC_INDEXING_STATUSES: frozenset[str] = frozenset(
    {DOC_PENDING, DOC_PARSING, DOC_CHUNKING, DOC_EMBEDDING}
)
#: 终态集合
DOC_TERMINAL_STATUSES: frozenset[str] = frozenset({DOC_READY, DOC_FAILED})

#: 索引阶段推进顺序：``doc_pending → doc_parsing → doc_chunking → doc_embedding``
DOC_STAGE_FLOW: tuple[str, str, str] = (DOC_PARSING, DOC_CHUNKING, DOC_EMBEDDING)

#: 支持的文档格式白名单（小写扩展名，不含点）
DOC_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "md", "txt"})

# --------------------------------------------------------------------------- #
# SSE 事件名（PRD §P0-6）
# --------------------------------------------------------------------------- #
EVT_SNAPSHOT = "snapshot"
EVT_NODE = "node"
EVT_HEARTBEAT = "heartbeat"
EVT_DONE = "done"
EVT_FAILED = "failed"
EVT_CANCELED = "canceled"

#: 答案增量（**流式输出**）。一次 LLM 生成过程中吐出的文本片段，append 语义。
#: 为什么不是复用 ``node``：``node`` 是**节点跑完**才发的（见 ``api/queue.py``），
#: 一条任务只有 3-5 帧，中间十几秒是纯静默 —— 屏上那段空窗就是这里要填的。
#: ⚠️ 帧名必须与前端 ``subscribeTaskStream`` 里 addEventListener 的那一串逐字一致
#: （``api/constants.py`` 开头的纪律：错一个字母客户端就永远收不到）。
EVT_DELTA = "delta"

#: 用量增量。一次 LLM 调用结束后发的 token / 成本**增量**（不是累计值），
#: 由前端累加显示。之所以发增量而不是累计：累计值只有后端有全量视图，
#: 而「运行中」的累计随时间变化，发累计会让客户端无法分辨"新花的"和"重发的历史"。
EVT_USAGE = "usage"

#: 发出即关流的事件（终态）
TERMINAL_EVENTS: frozenset[str] = frozenset({EVT_DONE, EVT_FAILED, EVT_CANCELED})

#: 状态 → SSE 事件名（用于「连接时已是终态」立即补发一帧）
EVENT_BY_STATUS: dict[str, str] = {
    STATUS_DONE: EVT_DONE,
    STATUS_ABORTED: EVT_DONE,
    STATUS_FAILED: EVT_FAILED,
    STATUS_CANCELED: EVT_CANCELED,
}

# --------------------------------------------------------------------------- #
# task_events 事件类型（持久化事件，设计文档 §6.4）
#   ★ 与上面 SSE 的 EVT_* 刻意分成两组：SSE 的 seq / 事件名只服务实时流，
#     task_events 的事件名服务「可回放的历史」。X1/X2 已证明两套 seq 混用会出事，
#     事件名同理——不能因为「done 就是 done」就复用同一个常量。
# --------------------------------------------------------------------------- #
TASK_EVT_RUNNING = "running"      # 任务开跑
TASK_EVT_NODE = "node"            # 节点完成（SSE EVT_NODE 的同源快照）
TASK_EVT_NODE_END = "node_end"    # 节点内部结束（含 thought/observation/status）
TASK_EVT_LLM_CALL = "llm_call"    # 一次 LLM 调用（tokens/cost/latency）
TASK_EVT_TOOL_CALL = "tool_call"  # 一次工具调用（tool_name/arguments/observation）
TASK_EVT_DONE = "done"
TASK_EVT_FAILED = "failed"
TASK_EVT_ABORTED = "aborted"
TASK_EVT_CANCELED = "canceled"

#: task_events.event_type 白名单（写入校验 + 前端渲染分支的共同真源）
TASK_EVENT_TYPES: frozenset[str] = frozenset(
    {
        TASK_EVT_RUNNING,
        TASK_EVT_NODE,
        TASK_EVT_NODE_END,
        TASK_EVT_LLM_CALL,
        TASK_EVT_TOOL_CALL,
        TASK_EVT_DONE,
        TASK_EVT_FAILED,
        TASK_EVT_ABORTED,
        TASK_EVT_CANCELED,
    }
)

#: 任务终态 → task_events 事件类型（Q3 埋点：终态事件类型映射）
TASK_EVENT_BY_STATUS: dict[str, str] = {
    STATUS_DONE: TASK_EVT_DONE,
    STATUS_FAILED: TASK_EVT_FAILED,
    STATUS_ABORTED: TASK_EVT_ABORTED,
    STATUS_CANCELED: TASK_EVT_CANCELED,
}

#: 单次 /trace 拉取的事件上限与默认页大小（游标分页的兜底，设计文档 §6.4）
TRACE_MAX_LIMIT = 500
TRACE_DEFAULT_LIMIT = 200

# --------------------------------------------------------------------------- #
# 校验与阈值
# --------------------------------------------------------------------------- #
#: 客户端可指定的 task_id 形状（PRD §P0-2）
TASK_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
TASK_ID_RE: re.Pattern[str] = re.compile(TASK_ID_PATTERN)

#: 服务端生成的 task_id 前缀与随机位数
TASK_ID_PREFIX = "task-"
TASK_ID_HEX_LEN = 12

#: 任务文本长度上限（先 strip 再校验）
MAX_TASK_CHARS = 4000

#: 单个 SSE ``update`` 里字符串的截断长度（防一帧几 MB 把连接压垮）
MAX_UPDATE_CHARS = 4000

#: 每个 SSE 订阅者的队列容量；满了丢弃事件并记 WARNING（M1 事件量极小，纯兜底）
SUBSCRIBE_QUEUE_SIZE = 256

#: 队列满时 ``Retry-After`` 的秒数
RETRY_AFTER_SECONDS = 5

#: SQLite 忙等超时（毫秒）——storage/db.py 与 evaluation/trace.py 两处都要设
SQLITE_BUSY_TIMEOUT_MS = 5000

#: SSE 重连建议间隔（毫秒），首帧下发给浏览器
SSE_RETRY_MS = 3000

# --------------------------------------------------------------------------- #
# 鉴权白名单
# --------------------------------------------------------------------------- #
#: 无需 Bearer 的路径（探活与文档）。``/docs`` 与 ``/redoc`` 按前缀放行。
AUTH_EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
#: 按前缀放行的路径（Swagger UI 的静态资源都在这些前缀下）
#:
#: ⚠️ ``/console`` **曾经在这里**（零构建静态控制台 ``web/``）。豁免挂在**前缀**上意味着
#: 往 ``web/`` 里落任何文件都自动免鉴权 —— 页面无敏感数据这条理由，护不住下一个
#: ``*.map`` / 导出件 / 探针脚本。2026-09-25 摘掉豁免，2026-09-27 连目录带挂载一起删了。
#:  这段账要留着（它解释的是"前缀豁免"这个机制为什么危险，跟 ``/console`` 死没死无关）：
#:  - 数据接口（``/tasks`` / ``/stats`` 等）本来就各自要 Bearer，摘豁免不影响它们；
#:  - 启用鉴权（``API_AUTH_TOKEN`` 非空）后，浏览器**无法**在文档导航上带 Bearer，
#:    而 ``WWW-Authenticate: Bearer`` 也不触发浏览器登录框 ⇒ 当时的 ``/console`` 直接吃 401，
#:    即"已知损坏"——那才是决定删它的直接原因；
#:  - 未配置 token 的部署（本地默认）行为不变：``verify_token`` 在未启用鉴权时直接放行。
#: 删目录换掉的三项能力记在 ``docs/known_residuals.md`` R-12（聚合看板 / 服务端 status
#: 过滤与分页 / Bearer token 输入与 401 重试），别在这里重复一遍口径。
AUTH_EXEMPT_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json")


def is_auth_exempt(path: str) -> bool:
    """判断该路径是否免鉴权。

    Args:
        path: 请求路径（不含 query string）。

    Returns:
        ``True`` 表示放行。``/docs`` 这类带子资源的路径按前缀匹配，
        其余用 ``rstrip("/")`` 归一化后精确匹配，避免 ``/health/`` 漏网。

    前缀匹配**带边界**：只认 ``/docs`` 自己与 ``/docs/...``，不认 ``/docsx``。
    早先写的是 ``path.startswith(AUTH_EXEMPT_PREFIXES)``，那是"看起来像前缀匹配"的
    子串匹配 —— ``/docsx``、``/redocx``、``/openapi.json.evil`` 全部命中。今天没有
    以这些串开头的路由，所以它没爆；但豁免名单恰恰是"多一个字符就少一道门"的地方
    （``/console`` 已经在这里出过一次事，见 :data:`AUTH_EXEMPT_PREFIXES` 上方那段），
    所以按边界写死。
    """
    normalized = path.rstrip("/") or "/"
    if normalized in AUTH_EXEMPT_PATHS:
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in AUTH_EXEMPT_PREFIXES)


__all__ = [
    "API_ACTIVE_STATUSES",
    "API_TERMINAL_STATUSES",
    "AUTH_EXEMPT_PATHS",
    "AUTH_EXEMPT_PREFIXES",
    "DOC_CHUNKING",
    "DOC_EMBEDDING",
    "DOC_FAILED",
    "DOC_INDEXING_STATUSES",
    "DOC_PENDING",
    "DOC_PARSING",
    "DOC_READY",
    "DOC_STAGE_FLOW",
    "DOC_SUPPORTED_FORMATS",
    "DOC_TERMINAL_STATUSES",
    "EVENT_BY_STATUS",
    "EVT_CANCELED",
    "EVT_DELTA",
    "EVT_DONE",
    "EVT_FAILED",
    "EVT_HEARTBEAT",
    "EVT_NODE",
    "EVT_SNAPSHOT",
    "EVT_USAGE",
    "MAX_TASK_CHARS",
    "MAX_UPDATE_CHARS",
    "RETRY_AFTER_SECONDS",
    "SSE_RETRY_MS",
    "SQLITE_BUSY_TIMEOUT_MS",
    "STATUS_ABORTED",
    "STATUS_CANCELED",
    "STATUS_DONE",
    "STATUS_EVENT_FAILED",
    "STATUS_EVENT_TIMEOUT",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "SUBSCRIBE_QUEUE_SIZE",
    "TASK_EVENT_BY_STATUS",
    "TASK_EVENT_STATUSES",
    "TASK_EVENT_TYPES",
    "TASK_EVT_ABORTED",
    "TASK_EVT_CANCELED",
    "TASK_EVT_DONE",
    "TASK_EVT_FAILED",
    "TASK_EVT_LLM_CALL",
    "TASK_EVT_NODE",
    "TASK_EVT_NODE_END",
    "TASK_EVT_RUNNING",
    "TASK_EVT_TOOL_CALL",
    "TASK_ID_HEX_LEN",
    "TASK_ID_PATTERN",
    "TASK_ID_PREFIX",
    "TASK_ID_RE",
    "TERMINAL_EVENTS",
    "TRACE_DEFAULT_LIMIT",
    "TRACE_MAX_LIMIT",
    "is_auth_exempt",
]
