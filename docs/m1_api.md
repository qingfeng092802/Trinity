# 多 Agent 协作平台 · M1 REST API 接口文档

> 阶段 5 · M1（REST API 层 + 异步任务队列）
> 交互式文档：服务启动后打开 `http://127.0.0.1:8000/docs`（Swagger UI）。

---

## 快速开始

```powershell
# 1. 启动 API（默认 127.0.0.1:8000）
.venv\Scripts\python.exe scripts\start_api.py

# 2. 提交任务（立即返回 201 + task_id，不等待执行）
curl -X POST http://127.0.0.1:8000/tasks -H "Content-Type: application/json" -d "{\"task\":\"用三句话解释什么是 RAG\"}"

# 3. 查询状态与结果（轮询）
curl http://127.0.0.1:8000/tasks/<task_id>

# 4. 订阅 SSE 节点增量流
curl -N http://127.0.0.1:8000/tasks/<task_id>/stream
```

容器方式：`docker compose --profile full up api`（暴露 8000，容器内监听 `0.0.0.0`）。

---

## 认证（最小方案）

| 场景 | 行为 |
|---|---|
| `API_AUTH_TOKEN` 为空（默认） | 仅监听 `127.0.0.1`、全放行；启动日志打 WARNING |
| `API_AUTH_TOKEN` 非空 | 除 `/health`、`/docs`、`/openapi.json` 外全部要求 `Authorization: Bearer <token>`；常量时间比较；失败 → `401` + `WWW-Authenticate: Bearer` |

---

## 统一错误响应体

```json
{
  "detail": {
    "code": "task_not_found",
    "message": "任务不存在：task-xxx",
    "request_id": "a1b2c3d4e5f6"
  }
}
```

| code | HTTP | 触发点 |
|---|---|---|
| `task_not_found` | 404 | 查询 / 取消 / 订阅不存在的任务 |
| `not_found` | 404 | 路由级 404（URL 写错、静态文件缺失），非领域资源不存在 |
| `task_id_conflict` | 409 | `POST /tasks` 指定的 task_id 已存在 |
| `queue_full` | 429 | 队列容量满（响应带 `Retry-After: 5`） |
| `task_already_finished` | 409 | 对终态任务调取消 |
| `tool_not_found` | 404 | 未注册的工具名 |
| `unauthorized` | 401 | Bearer 缺失 / 错误 |
| `peak_blocked` | 422 | `API_BLOCK_PEAK_TASKS=true` 且当前处于高峰计费时段 |
| `invalid_request` | 422 | 参数校验失败 |
| `internal_error` | 500 | 兜底（不回显堆栈） |

---

## 端点

### POST /tasks —— 提交任务

请求体：

| 字段 | 类型 | 必填 | 默认 | 约束 |
|---|---|---|---|---|
| `task` | string | 是 | — | 去空白后 1..4000 字符 |
| `task_id` | string\|null | 否 | 服务端生成 | `^[A-Za-z0-9_-]{1,64}$`，重复 → 409 |
| `use_tools` | bool | 否 | `true` | 是否接入内置工具 |
| `max_iterations` | int | 否 | 全局配置 | 1..10 |
| `review_threshold` | int | 否 | 全局配置 | 0..10 |
| `run_judge` | bool | 否 | `false` | 是否额外跑一轮 LLM judge |
| `difficulty` | string\|null | 否 | `null` | `easy/medium/hard` |

响应 `201`：

```json
{
  "task_id": "task-3f9a1c2b7d10",
  "status": "queued",
  "queue_position": 1,
  "submitted_at": "2026-09-17T00:29:06+08:00",
  "poll_url": "/tasks/task-3f9a1c2b7d10",
  "stream_url": "/tasks/task-3f9a1c2b7d10/stream",
  "cancel_url": "/tasks/task-3f9a1c2b7d10/cancel",
  "estimated_cost_cny": 0.019252,
  "peak_pricing": true,
  "price_multiplier": 2.0,
  "warnings": ["..."]
}
```

> `estimated_cost_cny` 是**粗估**（误差可能 3-5 倍），仅供量级参考，**不得用于计费**。

### GET /tasks/{task_id} —— 查询状态与结果

`200` 返回 `TaskView`：`TaskRecord` 全字段（`cost` 6 位小数、时间北京时区）+ `progress`（运行中：当前节点 / 已完成节点 / 迭代轮次；终态为 `null`）+ `queue.position` + `error`（仅 `failed` 时非空）。

不存在 → `404 task_not_found`。该端点幂等。

### POST /tasks/{task_id}/cancel —— 取消任务

**取消语义（务必阅读）**：

| 任务状态 | 行为 | 响应 `mode` |
|---|---|---|
| `queued` | 直接丢弃，**零 LLM 调用** | `queued_dropped` |
| `running` | 在**当前节点结束后**停止，结果丢弃 | `node_boundary` |
| 已终态 | 不变更 | `409 task_already_finished` |

取消后任务状态恒为 `canceled`（worker 不会覆盖）。

### GET /tasks/{task_id}/stream —— SSE 节点增量

响应头：`text/event-stream; charset=utf-8`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`。首帧 `retry: 3000`。

| 事件 | 时机 | data 要点 |
|---|---|---|
| `snapshot` | 连接建立后立即 | task_id / status / progress |
| `node` | 每个编排节点返回后 | node / iteration / seq / update（**已剔除 messages 键**） |
| `heartbeat` | 每 `API_SSE_HEARTBEAT_SECONDS`（默认 15s） | task_id / ts |
| `done` | 终态 done / aborted | final_answer / cost / duration_ms / score / grade |
| `failed` | 终态 failed | error.code / error.message |
| `canceled` | 终态 canceled | reason / canceled_at |

规则：终态事件发出后立即关闭；对已终态任务建流 → `snapshot` + 终态事件后马上关闭；客户端断开不影响任务继续执行；任务不存在 → 建流之前返回 `404`。

### POST /tools/{tool_name}/invoke —— 单工具调用

请求：`{"args": {...}}`，可选查询参数 `?approve_high_risk=true`。

**工具执行失败也返回 HTTP 200**（沿用 `ToolRegistry.call` 不抛异常的契约）——客户端必须判断 `status != "success"`。可选 `status`：`success / failed / timeout`。

HITL 决策表（`ENABLE_HITL=true` 时，高危工具 fail-closed）：

| `?approve_high_risk` | `API_ALLOW_HIGH_RISK_OVERRIDE` | 行为 |
|---|---|---|
| 不带 / false | — | 拒绝：`status=failed`，`hitl.required=true` |
| true | false（默认） | 仍拒绝：提示需开启服务端 override |
| true | true | 放行（记 WARNING 审计日志） |

### GET /eval —— 评测记录查询（只读）

参数：`task_id`（可选）、`limit`（1..200，默认 50）、`offset`（默认 0）。
响应：`{"items": [...], "total": N, "limit": 50, "offset": 0}`，按创建时间倒序。
M1 **不提供**触发批量评测的接口。

### GET /health —— 健康检查

```json
{
  "status": "healthy | degraded | unhealthy",
  "version": "0.2.0",
  "uptime_seconds": 1234,
  "checks": {
    "api": {"status": "ok"},
    "database": {"status": "ok"},
    "redis": {"status": "ok | degraded"},
    "llm": {"status": "ok | fail"},
    "queue": {"status": "ok", "running": 1, "queued": 0, "max_concurrent": 3}
  }
}
```

判定口径：**DB 不可写或未配 LLM Key → `unhealthy` + HTTP 503**；**Redis 不通 → `degraded` + HTTP 200**（自动降级进程内缓存，功能不受影响）。`?deep=true` 时对 LLM 做一次真实探针调用。

---

## 任务状态机

```
POST /tasks → queued ─┬─→ running ─┬─→ done
                      │            ├─→ aborted（迭代上限强制收口，不计完成率）
                      │            └─→ failed
                      ├─→ canceled（排队中取消，零 LLM 调用）
                      └────────────→ canceled（运行中取消，节点边界生效）
```

---

## 配置项（全部走环境变量 / `.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | 监听地址 |
| `API_MAX_CONCURRENT_TASKS` | `3` | 同时执行的任务数上限 |
| `API_QUEUE_MAX_SIZE` | `50` | 等待队列容量，满 → 429 |
| `API_SSE_HEARTBEAT_SECONDS` | `15` | SSE 心跳间隔（float） |
| `API_AUTH_TOKEN` | 空 | Bearer Token；空 = 仅本机 + 全放行 |
| `API_BLOCK_PEAK_TASKS` | `false` | 高峰计费时段是否硬拦提交 |
| `API_ALLOW_HIGH_RISK_OVERRIDE` | `false` | 是否允许 API 放行高危工具 |

---

## 已知限制（调用方必读）

| # | 限制 | 影响 |
|---|---|---|
| **L1** | **取消不能中止飞行中的 LLM 请求**（同步内核 + 线程池，Python 无法杀线程）。最坏等待 `llm_timeout × (1 + llm_max_retries)` = 120s × 4 = **480s** 才释放槽位 | 取消在节点边界生效；建议 API 场景把 `LLM_TIMEOUT` 调到 60s |
| **L2** | worker 槽位不可强制回收 | 卡死任务会占住槽位，极端情况队列停滞，只能重启 |
| **L3** | 队列与进度是**进程内存态** | API 重启后残留的 `queued`/`running` 需人工处理（DB 状态卡住） |
| **L4** | SSE 是**节点级**增量，不是 token 级 | 一次 LLM 调用期间客户端看不到中间文本 |
| **L5** | SQLite 并发写（已开 WAL + busy_timeout=5000） | 数据库文件不要放网络共享盘（Windows 上会 `disk I/O error`） |
| **L6** | 工具调用失败返回 HTTP 200 | 必须判断 `status != "success"` |
| **L7** | `run_judge` 默认 false | API 提交的任务默认不产生评测记录 |
| **L8** | 高峰时段不硬拦 | 需要硬拦时设 `API_BLOCK_PEAK_TASKS=true` |

## 测试

```powershell
uv sync --extra dev
uv run pytest tests/integration/test_api_tasks.py tests/integration/test_api_stream.py tests/integration/test_api_tools.py tests/integration/test_api_health.py -q
```

全部测试使用 Mock LLM，**不消耗真实 token**。
