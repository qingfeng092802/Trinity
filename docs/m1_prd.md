# M1 增量 PRD：REST API 层 + 异步任务队列

> 阶段 5 · M1（第 1-2 周 · P0）
> 本文档**只覆盖 M1**，不扩大到 RAG（M2）/ MCP（M3）/ 前端重设计（M4）。

---

## 0. 项目信息

| 项 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | Python 3.11；新增 **FastAPI + Uvicorn + Pydantic v2**（API 层）；**Streamlit 沿用**（前端不做框架迁移） |
| Project Name | `trinity_m1_rest_api` |
| 文档类型 | 简单 PRD（不做竞品/市场分析） |
| 依赖现状 | `pytest-asyncio` 已在 dev 依赖中，`asyncio_mode=auto` 已配置；**FastAPI / uvicorn 需新加依赖** |

### 原始需求复述

把平台从「单人演示工具」升级为「可被集成的 Agent 服务」的第一步：在现有同步编排内核（`WorkflowRunner.run/stream`）之上，加一层 FastAPI 接口 + 后台任务队列，让外部系统能通过 HTTP 提交任务、查询状态、实时流式获取节点增量、单独调用工具、查询评测结果与健康状态；同时把 Streamlit 的执行入口从「页面进程内直跑」改为「调用 API」，作为前后端分离的第一步。

---

## 1. 产品目标

**一句话**：M1 要解决的不是"能力不够"，而是"能力出不去"——目前平台的能力只能通过 Streamlit 页面或 CLI 触达，外部系统没有任何稳定契约可以集成，且页面关掉任务就断。M1 通过 REST API + 后台队列，把「任务的执行」从「请求的生命周期」里剥离出来。

**解决后平台能力边界的变化**：

| 维度 | M1 之前 | M1 之后 |
|---|---|---|
| 触达方式 | 只有 Streamlit 页面 + CLI 脚本 | 多一种：HTTP 契约（Swagger 可查、curl 可调） |
| 任务生命周期 | 与页面/终端进程绑定，关掉即断 | 与请求解耦，后台执行，进程内队列排队 |
| 集成者 | 只有本人 | 任何能发 HTTP 请求的系统 |
| 中途干预 | 无（只能杀进程） | 可按 task_id 取消（节点边界生效） |
| 并发 | 串行（页面跑一个才能跑下一个） | 并发上限内并行，超限排队 |

### 3 条可量化目标

| # | 目标 | 量化标准 |
|---|---|---|
| G1 | **接口可用**：外部系统能用 curl 走完「提交 → 查询 → 拿结果」全链路 | `POST /tasks` 返回 201 且 ≤ 200ms；6 个规划端点全部在 Swagger 可见；`docs/` 与 `openapi.json` 返回 200 |
| G2 | **队列可控**：并发上限生效、超限排队、可取消 | 并发上限默认 3；连发 5 条时任意时刻 `running ≤ 3` 且 5 条最终全部终态；`cancel` 后 10s 内重复查询状态恒为 `canceled`，且被取消任务不再进入下一节点 |
| G3 | **前端解耦**：Streamlit 主页面不再自己跑编排 | 「工作流测试」页 100% 通过 API 执行；API 不可达时页面报明确错误（不做本地降级直跑）；页面关掉后任务仍能在 `/health` 的 `queue.running` 中观察到 |

---

## 2. 用户故事

### A. 外部系统集成者

| # | 用户故事 |
|---|---|
| US-1 | 作为**外部系统开发者**，我希望用一条 HTTP 请求提交任务并**立即**拿到 `task_id`，以便我的系统不必为一个可能跑 30 秒的 Agent 任务挂起连接或设超长超时。 |
| US-2 | 作为**外部系统开发者**，我希望通过 SSE 实时收到每个节点（planner/executor/reviewer）的增量输出，以便把 Agent 的中间过程渲染给我自己的终端用户，而不是干等一个黑盒结果。 |
| US-3 | 作为**外部系统开发者**，我希望在任务跑偏时能调用取消接口及时止损，以便不再为已经无用的任务继续烧 token。 |
| US-4 | 作为**外部系统的运维人员**，我希望 `/health` 能区分「数据库不可用（真的不能服务）」和「Redis 不通（有降级，能服务）」，以便我正确决定是重启服务还是可以忽略。 |

### B. 平台运营 / 使用方

| # | 用户故事 |
|---|---|
| US-5 | 作为**平台使用者（Streamlit 用户）**，我希望页面上的任务是在后台服务里跑的，以便我刷新或关掉浏览器标签时任务不会中断，回来还能查到结果。 |
| US-6 | 作为**平台使用者**，我希望在页面上能看到「排队中 / 运行中」以及队列位置和当前节点，以便区分"任务卡住了"和"前面还有任务在排队"。 |
| US-7 | 作为**成本敏感的使用者**，我希望提交任务时 API 明确告诉我当前是否处于高峰计费时段，以便我决定现在跑还是等低谷再跑。 |

### C. 后续 M2-M4 开发者

| # | 用户故事 |
|---|---|
| US-8 | 作为 **M2（RAG）开发者**，我希望 M1 已经沉淀出统一的任务提交 / 查询 / 流式通道与配置规范，以便我加 `knowledge_search` 工具时只需要动工具层和提示词，不必再改接口层。 |
| US-9 | 作为 **M3（MCP）开发者**，我希望已有 `POST /tools/{name}/invoke` 与工具清单接口，以便 MCP 拉来的外部工具能复用同一套「单工具调试 → 注册进编排」的通道。 |
| US-10 | 作为**后续阶段开发者**，我希望所有 API 行为都可通过 `config.get_settings()` 配置且有 Swagger 契约，以便我在不读源码的前提下对接与联调。 |

---

## 3. 关键设计决策速览（结论先行）

| 议题 | 决策 | 一句话理由 |
|---|---|---|
| **任务状态机** | 沿用现有 `done / aborted / failed`，**只新增 `queued`、`canceled`** 两个状态 | `TaskRecord.status` 是 `String(16)`，新状态长度合规；不新增"运行中"以外的抽象，避免与 `evaluation/metrics.py` 的完成率口径冲突（`aborted` 不算完成） |
| **取消语义** | **在下一个节点边界生效，不中止正在飞行的 LLM HTTP 请求** | `WorkflowRunner` 是同步阻塞代码，跑在线程池里，Python 无法强制杀线程；承诺"真正中止 LLM 调用"在 M1 做不到，见 §7 已知限制 L1 |
| **并发上限** | 默认 **3**，超限**排队**，队列满（默认 50）才 **429 拒绝** | 与"3 个任务正确排队"的验收场景一致；排队比拒绝更友好，但要防无限堆积 |
| **SSE 粒度** | **节点级增量**（每个 LangGraph 节点返回后一帧），**不是 token 级流式** | `stream_mode="updates"` 只在节点结束后吐数据；token 级需要核心层 async 化，属 M2+ |
| **HITL 与工具调用** | 传承全局 `enable_hitl`，**默认 fail-closed 拒绝**；需显式 `?approve_high_risk=true` 且 `api_allow_high_risk_override=true`（默认 false）才放行 | 项目既有纪律是 fail-closed（无审批回调按拒绝），API 无人在环，不能偷偷放宽 |
| **`/health` 降级** | Redis 不通 = **degraded + HTTP 200**；DB 不可写 = **unhealthy + HTTP 503** | 与 `scripts/health_check.py` 里 Redis 只 warn、DB 为硬依赖的既有口径一致 |
| **高峰计费闸门** | `POST /tasks` **默认只提示不拦截**（响应带 `peak_pricing` + `warnings`）；提供 `api_block_peak_tasks=true` 可硬拦 | 与现有"单条任务只提示、批量评测才硬拦"的口径一致；API 调用方可能是自动化系统，硬拦会破坏集成 |
| **API 认证** | 单静态 Bearer Token（`api_auth_token`）；为空时=仅绑定 127.0.0.1 全放行并打印启动告警 | M1 不做用户体系（阶段 5 明确不做），但要留一个"不是完全裸奔"的最小闸门 |
| **Streamlit 降级** | **不做**「API 连不上就本地直跑」的双实现，连不上就报错 | 两条执行路径必然导致口径分裂，这正是 `evaluation/batch.py` 当初要避免的坑 |

---

## 4. 需求池

### 4.1 任务状态机（P0，契约）

```
                        ┌─→ canceled（用户取消；queued 时直接丢弃，running 时在节点边界生效）
                        │
  POST /tasks → queued ─┼─→ running ─┬─→ done     （评审通过或强制收口且有答案）
                        │            ├─→ aborted  （达到 max_iterations 被强制收口，沿用现义）
                        │            └─→ failed   （节点异常 / 不可重试的 LLM 错误）
                        └──────────────────────────┘
```

| 状态 | 含义 | 与现有 `TaskRecord.status` 的关系 | 是否终态 |
|---|---|---|---|
| `queued` | 已受理，等待 worker 槽位 | **新增** | 否 |
| `running` | 已占用槽位，正在执行节点 | 已存在（原为初始态） | 否 |
| `done` | 正常完成 | 已存在 | 是 |
| `aborted` | 达到迭代上限被强制收口（**不计入完成率**） | 已存在 | 是 |
| `failed` | 节点异常 / 不可重试错误 / 软超时 | 已存在 | 是 |
| `canceled` | 用户主动取消 | **新增** | 是 |

- 终态集合扩展为 `{done, failed, aborted, canceled}`（现有 `core/workflow/state.py::TERMINAL_STATUSES` 为工作流内部状态，不动；API 层另定义 `API_TERMINAL_STATUSES`）。
- `canceled` **不计入完成率**，也不计入 `failed`（`evaluation/metrics.py` 的统计口径新增一类或忽略，随 §8 Q4 结论确定）。
- 状态流转的唯一写入方：worker（执行中）+ API handler（受理时写 `queued`、取消时写 `canceled`）；worker 落终态前必须再次确认未被取消，防止覆盖。

---

### 4.2 P0 需求（Must have）

#### P0-1 API 服务骨架与自动文档

新增 `api/` 包（`api/main.py` / `api/deps.py` / `api/schemas.py` / `api/queue.py` / `api/routes/*.py`），FastAPI 应用 + `scripts/start_api.py` 启动脚本（uvicorn）。所有端点加统一前缀 `/`，版本号**暂不引入**（`/v1` 留到有破坏性变更时再加，见 §8 Q6）。

统一错误响应体：

```json
{ "detail": { "code": "task_not_found", "message": "任务不存在：task-xxx", "request_id": "..." } }
```

**验收标准**
1. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs` → `200`；`/openapi.json` → `200`。
2. `/openapi.json` 的 `paths` 至少包含 `/tasks`、`/tasks/{task_id}`、`/tasks/{task_id}/stream`、`/tasks/{task_id}/cancel`、`/tools/{tool_name}/invoke`、`/eval`、`/health` 7 项。
3. 依赖新增后 `uv sync` 可通过，`scripts/health_check.py` 的「依赖完整性」检查仍为 ok。

#### P0-2 `POST /tasks` —— 异步提交，立即返回

**请求体**

| 字段 | 类型 | 必填 | 默认 | 约束 |
|---|---|---|---|---|
| `task` | string | 是 | — | 去空白后长度 1..4000（`initial_state` 会拒绝空串） |
| `task_id` | string\|null | 否 | 服务端生成 `task-<hex12>` | `^[A-Za-z0-9_-]{1,64}$`；已存在则 409 |
| `use_tools` | bool | 否 | `true` | 是否接入 5 个内置工具 |
| `max_iterations` | int | 否 | 取 `settings.max_iterations` | 1..10 |
| `review_threshold` | int | 否 | 取 `settings.review_threshold` | 0..10 |
| `run_judge` | bool | 否 | `false` | M1 默认不跑 judge（省一轮 LLM 成本） |
| `difficulty` | string\|null | 否 | `null` | `easy/medium/hard` |

**响应 201**

```json
{
  "task_id": "task-3f9a1c2b7d10",
  "status": "queued",
  "queue_position": 2,
  "submitted_at": "2026-09-20T10:11:12+08:00",
  "poll_url": "/tasks/task-3f9a1c2b7d10",
  "stream_url": "/tasks/task-3f9a1c2b7d10/stream",
  "cancel_url": "/tasks/task-3f9a1c2b7d10/cancel",
  "estimated_cost_cny": 0.015,
  "peak_pricing": true,
  "price_multiplier": 2.0,
  "warnings": ["当前为高峰计费时段（周一至周五 09:00-12:00、14:00-18:00），单价为低谷的 2 倍"]
}
```

**验收标准**
1. Mock LLM 下 `POST /tasks` 返回 **201**，响应耗时 **≤ 200ms**（不得等待任务执行）。
2. 响应 `status ∈ {queued, running}`，`task_id` 匹配 `^task-[0-9a-f]{12}$`。
3. 客户端传 `task_id` 重复提交 → **409** + `code=task_id_conflict`。
4. `task` 为空串/纯空白 → **422**（Pydantic 校验）。
5. 未配置 `LLM_API_KEY` 时仍受理（不预检），但 `warnings` 中含「未配置 LLM_API_KEY，任务大概率失败」。

#### P0-3 `GET /tasks/{task_id}` —— 状态与结果查询

**响应 200**（终态时字段齐全，非终态时 `score/grade/final_answer` 可为 null/空）

```json
{
  "task_id": "...", "task": "...", "status": "running",
  "iterations": 1, "score": null, "grade": null, "final_answer": "",
  "cost": 0.0, "duration_ms": 0, "tool_calls": 2, "tool_failures": 0,
  "difficulty": null, "created_at": "...", "updated_at": "...",
  "progress": { "current_node": "executor", "completed_nodes": ["planner"], "iteration": 1, "max_iterations": 3, "elapsed_ms": 8400 },
  "queue": { "position": 0, "wait_seconds": 0.0 },
  "error": null
}
```

`error` 结构：`{"code": "llm_not_retryable", "message": "..."}`（仅 `failed` 时非空）。

**验收标准**
1. 存在的任务 → 200，字段与 `TaskRecord.as_dict()` 一致（含 `cost` 保留 6 位小数）。
2. 不存在的 id → **404** + `code=task_not_found`。
3. 任务在排队时（`queued`）`queue.position ≥ 1`；转入 `running` 后 `position = 0`。
4. 终态任务的 `duration_ms > 0` 且 `cost ≥ 0`；`GET` 是幂等的，连续两次调用结果一致（除 `queue.wait_seconds` 外）。

#### P0-4 任务队列与并发控制

- 实现：`ThreadPoolExecutor(max_workers=api_max_concurrent_tasks)` + `asyncio.Queue(maxsize=api_queue_max_size)` + 一个 dispatcher 协程；worker 线程内调用同步的 `runner.stream()`，每 yield 一次后检查 `cancel_event`。
- 进度写入**复用现有 `storage/cache.py::CacheFacade`**（键 `state:{task_id}`，Redis 优先、进程内降级），终态写入 `storage/db.py::Database.save_task`。
- 运行中任务的 `progress` 优先读 CacheFacade；缓存不可用时退化为只返回 DB 字段（`progress=null`，不报错）。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `api_max_concurrent_tasks` | `3` | 同时执行的任务数上限 |
| `api_queue_max_size` | `50` | 等待队列容量 |
| `api_sse_heartbeat_seconds` | `15` | SSE 心跳间隔 |

**验收标准**
1. 并发上限=3、Mock LLM 每节点 sleep 0.2s：`for i in {1..5}; do curl POST /tasks; done`，采样 `/health` 的 `queue.running`，**任意时刻 ≤ 3**，且 5 条最终全部进入终态。
2. 队列满（临时把 `api_queue_max_size` 设为 1，并发设为 1，连发 3 条）→ 第 3 条返回 **429** + `code=queue_full` + `Retry-After: 5`。
3. pytest：断言并发峰值恰好为 3（用计数器记录同时进入 `running` 的任务数）。
4. 队列 FIFO：按提交顺序执行（断言 5 条任务的首次 `running` 时间戳单调递增）。

#### P0-5 `POST /tasks/{task_id}/cancel` —— 取消任务

**语义（诚实版，务必与 §7 L1 一起读）**

| 任务当前状态 | 取消行为 | 落库状态 |
|---|---|---|
| `queued` | **直接丢弃**，不分配 worker，不发起任何 LLM 调用 | 立即 `canceled` |
| `running` | 置 `cancel_event`；worker 在**当前节点返回后**停止迭代，丢弃结果，不再进入下一节点 | 立即 `canceled`（worker 不得再覆盖） |
| 已终态 | 不变更，返回 **409** + `code=task_already_finished` | 不变 |

**响应 200**：`{"task_id": "...", "status": "canceled", "canceled_at": "...", "mode": "queued_dropped" | "node_boundary", "note": "取消将在下一个节点边界生效；当前节点已发出的 LLM 请求会跑完但结果被丢弃"}`

**验收标准**
1. `queued` 态取消 → 200；随后断言 Mock LLM **调用次数为 0**（证明真的没跑）。
2. `running` 态取消 → 200；用 3 节点 Mock（每节点 sleep 0.3s，记录进入次数）断言：**取消后不再进入下一节点**（进入次数 < 未取消时）。
3. 取消后 10s 内每 0.5s 采样一次 `GET /tasks/{id}`，`status` **恒为 `canceled`**（验证 worker 不覆盖）。
4. 对已终态任务取消 → **409**。

#### P0-6 `GET /tasks/{task_id}/stream` —— SSE 节点增量

**握手**：`Content-Type: text/event-stream; charset=utf-8`，`Cache-Control: no-cache`，`Connection: keep-alive`，`X-Accel-Buffering: no`（防反向代理缓冲）。首帧下发 `retry: 3000`。
**前置校验**：`task_id` 不存在时在**建立流之前**返回 404（一旦返回 200 不能再改状态码）。

| 事件名 | 触发时机 | `data` 结构 |
|---|---|---|
| `snapshot` | 连接建立后立即发一次（支持中途接入） | `{"task_id","status","progress","ts"}` |
| `node` | 每个 LangGraph 节点返回后（`stream_mode="updates"`） | `{"task_id","node","iteration","seq","ts","update":{...}}` |
| `heartbeat` | 每 `api_sse_heartbeat_seconds` 秒（默认 15s） | `{"task_id","ts","running_ms"}` |
| `done` | 进入 `done` / `aborted` | 终态任务视图：`{"task_id","status","final_answer","cost","duration_ms","iterations","score","grade"}` |
| `failed` | 进入 `failed` | `{"task_id","error":{"code","message"}}` |
| `canceled` | 进入 `canceled` | `{"task_id","reason":"user_requested","canceled_at"}` |

**规则**
1. 每帧带 `id: <seq>`（单调递增整数），便于客户端去重；**M1 不支持 `Last-Event-ID` 断点续播**（P2）。
2. `node.update` **必须剔除 `messages` 键**（LangChain 消息对象不可 JSON 序列化且体积大）——与现有 `ui/pages/2_workflow_test.py` 的 `collected.update({k: v for k, v in update.items() if k != "messages"})` 口径一致。
3. 任务在连接建立时**已处于终态** → 立即发 `snapshot` + 对应终态事件，然后**关闭连接**（不挂起）。
4. 终态事件发出后**立即关闭流**，不再发心跳。
5. 客户端断开（`asyncio.CancelledError` / `GeneratorExit`）→ 服务端清理订阅，**不影响任务继续执行**。

**验收标准**
1. `curl -N http://127.0.0.1:8000/tasks/<id>/stream` 能依次收到 `snapshot`、`node`(planner/executor/reviewer 至少各 1 次)、`done`。
2. pytest：把 `api_sse_heartbeat_seconds` 设为 0.1，断言 1 秒内收到 ≥ 5 个 `heartbeat` 且期间无 `node` 事件。
3. pytest：对已终态任务建立 SSE → 收到 `snapshot` + 终态事件后**连接在 1s 内关闭**。
4. pytest：`node` 事件的 `update` 中**不含** `messages` 键。
5. 不存在的 task_id → **404**（且响应体是 JSON，不是流）。

#### P0-7 `POST /tools/{tool_name}/invoke` —— 单工具调用

**请求**：`{"args": {...}}`；查询参数 `?approve_high_risk=false`。
**响应 200**：`{"name","args","result","status","duration_ms","hitl":{"required":bool,"approved":bool,"reason":string|null}}`

（`registry.call()` 不抛异常、失败编码进 `status`——沿用既有契约，所以**工具执行失败也返回 HTTP 200**。）

**与 HITL 的关系（决策表）**

| `settings.enable_hitl` | 工具 `danger_level` | `?approve_high_risk` | `api_allow_high_risk_override` | 行为 |
|---|---|---|---|---|
| false | low | — | — | 直接执行 |
| false | high | — | — | 直接执行（`hitl.required=false`） |
| true | low | — | — | 直接执行（HITL 只管 high） |
| true | high | false（默认） | — | **拒绝**：`status="failed"`，`hitl.required=true`，`hitl.reason="高危工具需人工确认，API 未提供审批通道"`（fail-closed） |
| true | high | true | **true** | 放行（仅本次调用注入 `lambda n,a: True`），`hitl.approved=true`，**记 WARNING 日志** |
| true | high | true | **false（默认）** | 仍拒绝，`reason` 说明需开启 `api_allow_high_risk_override` |

**验收标准**
1. `POST /tools/calculator/invoke {"args":{"expression":"1+1"}}` → 200，`status="success"`，`result` 含 `2`。
2. `enable_hitl=true` + `code_exec` + 不带 `approve_high_risk` → 200 且 `status="failed"`、`hitl.required=true`（**不得**真的执行代码）。
3. `enable_hitl=true` + `api_allow_high_risk_override=true` + `?approve_high_risk=true` + `code_exec` → `status="success"`。
4. 未注册的工具名 → **404** + `code=tool_not_found`（错误信息中列出可用工具名）。
5. `args` 校验失败 → 200 且 `status="failed"`、`result` 含参数校验说明（不抛 500）。
6. 超时/沙箱路径越界 → 200 且 `status="timeout"` / `"failed"`，不抛 500。

#### P0-8 `GET /eval` —— 评测结果查询（只读）

查询参数：`task_id`（可选）、`limit`（1..200，默认 50）、`offset`（默认 0）。
响应：`{"items":[...EvalRecord.as_dict()...], "total": N, "limit": 50, "offset": 0}`，按 `created_at` 倒序。

**验收标准**
1. 空库 → 200 且 `{"items":[],"total":0,...}`。
2. 预置 3 条 `eval_records` → `total=3`；`?task_id=<某 id>` 只返回该任务的记录。
3. `limit=201` → **422**；`limit=0` → **422**。
4. **M1 不提供触发批量评测的接口**（见 §6）。

#### P0-9 `GET /health` —— 健康检查

```json
{
  "status": "healthy | degraded | unhealthy",
  "version": "0.2.0",
  "uptime_seconds": 1234,
  "checks": {
    "api":      { "status": "ok", "detail": "FastAPI 0.x" },
    "database": { "status": "ok | fail", "detail": "sqlite:///... 可读写" },
    "redis":    { "status": "ok | degraded | fail", "detail": "..." },
    "llm":      { "status": "ok | degraded | fail", "detail": "..." },
    "queue":    { "status": "ok", "running": 2, "queued": 1, "max_concurrent": 3 }
  }
}
```

| 依赖项 | 判定口径 | 不通时的整体状态 |
|---|---|---|
| `api` | 恒 ok | — |
| `database` | 能打开会话并执行 `SELECT 1` | **unhealthy（HTTP 503）**——结果无处落库，等于不能服务 |
| `redis` | `CacheFacade.using_redis` / `ping()` | **degraded（HTTP 200）**——平台有进程内缓存降级，功能不受影响（与 `scripts/health_check.py` 中 Redis 只 warn 一致） |
| `llm` | 默认**只校验 `settings.llm_configured`**（零 token）；`?deep=true` 才真实调用一次探针 | 未配置 Key → **fail** → 整体 `unhealthy（503）`；`?deep=true` 调用异常 → `degraded（200）` |
| `queue` | 恒 ok，只上报计数 | — |

**验收标准**
1. 全绿 → `200` + `status=healthy`。
2. 停掉 Redis（或 `redis_url` 指向不通端口）→ **HTTP 200** + `status=degraded` + `checks.redis.status=degraded`（**不得**返回 503）。
3. `db_url` 指向不可写路径 → **HTTP 503** + `status=unhealthy` + `checks.database.status=fail`。
4. 清空 `LLM_API_KEY` → **HTTP 503** + `checks.llm.status=fail`；`?deep=true` 时在正常环境下返回 `ok` 并带耗时。
5. `checks.queue` 的 `running`/`queued` 与 `POST /tasks` 的实际状态一致（提交 2 条后 `running+queued=2`）。

#### P0-10 配置扩展（全部走 `config.py`）

新增字段（**禁止硬编码**，沿用 `pydantic-settings` + `.env`）：

`api_host`(`127.0.0.1`)、`api_port`(`8000`)、`api_max_concurrent_tasks`(`3`)、`api_queue_max_size`(`50`)、`api_sse_heartbeat_seconds`(`15`)、`api_auth_token`(`SecretStr("")`)、`api_block_peak_tasks`(`false`)、`api_allow_high_risk_override`(`false`)。

**验收标准**：通过环境变量 `API_MAX_CONCURRENT_TASKS=1` 启动后，`/health` 的 `queue.max_concurrent == 1`（证明走配置而非硬编码）。

#### P0-11 Streamlit「工作流测试」页改造为调 API

见 §5。

**验收标准**
1. 页面提交后，任务在 API 进程执行：`/health` 的 `queue.running ≥ 1`；**杀掉浏览器标签后任务仍在跑**（`/health` 仍能观察到 running，最终 `GET /tasks/{id}` 为终态）。
2. 页面新增「取消」按钮，点击后 `/tasks/{id}` 状态变为 `canceled`。
3. API 未启动（连不上 `API_BASE_URL`）→ 页面显示明确错误 + 启动命令提示（`python scripts/start_api.py`），**不静默回退到本地直跑**。

#### P0-12 认证最小方案

| 场景 | 行为 |
|---|---|
| `api_auth_token` 为空（默认） | 仅绑定 `127.0.0.1`，**全放行**；启动时打印 WARNING：「API_AUTH_TOKEN 未设置，仅本机可访问，请勿暴露端口」 |
| `api_auth_token` 非空 | 除 `/health`、`/docs`、`/openapi.json`、`/redoc` 外，全部要求 `Authorization: Bearer <token>` |
| 校验方式 | `secrets.compare_digest` 常量时间比较 |
| 失败 | **401** + `code=unauthorized` + `WWW-Authenticate: Bearer` |

**验收标准**
1. 设了 token 后不带 Header 访问 `/tasks` → **401**。
2. 错误 token → **401**；正确 token → 正常。
3. `/health`、`/docs` 在无 token 时仍 **200**（供探活与文档访问）。
4. 未设 token 时请求 `/health` 的响应或启动日志中含降级警告标记。

#### P0-13 测试与文档

- `tests/integration/test_api_tasks.py`、`test_api_stream.py`、`test_api_tools.py`、`test_api_health.py`（用 `fastapi.testclient.TestClient` + 注入 Mock LLM，**不消耗真实 token**；`asyncio_mode=auto` 已配置）。
- `docs/m1_api.md`（对外接口说明，含 curl 示例）与 `README.md` 补一节「启动 API」。

**验收标准**
1. `pytest tests/ -q` 全绿，新增 API 测试 ≥ 20 条断言组。
2. 不设 `LLM_API_KEY` 也能跑通全部 API 测试（用 Mock LLM）。
3. `README.md` 中能直接复制命令启动 API 并提交一条任务。

---

### 4.3 P1 需求（Should have）

| # | 需求 | 说明 / 验收要点 |
|---|---|---|
| P1-1 | `POST /tasks?wait=true&timeout=<1..300>` 同步等待模式 | 在并发上限内直接 await 任务完成；超时返回 **200** + 当前快照 + `"wait_timeout": true`（**不是错误**，任务仍有效），避免长连接被网关切断后调用方误判失败。默认 `wait=false`。 |
| P1-2 | `GET /tasks` 列表查询 | 支持 `status` / `limit` / `offset` 过滤，供「轨迹回放」页与运维排查；复用 `Database.list_tasks`。 |
| P1-3 | `GET /tools` 工具清单 | 返回 `ToolSpec`（名称/签名/危险级别/超时/重试/说明），供 Swagger 与页面下拉框使用。 |
| P1-4 | 孤儿任务回收 | API 启动时把库中残留的 `queued`/`running` 标记为 `failed` 并标注 `error_code=orphaned`（进程重启后内存态必然丢失）。依赖 P0 的错误字段落点（§8 Q1）。 |
| P1-5 | 任务软超时 `api_task_timeout_seconds`（默认 900） | watchdog 到点把任务标 `failed(timeout)`；**注意：不释放 worker 槽位**（见 §7 L2）。 |
| P1-6 | `TaskRecord` 增加 `error_code` / `error_message` 两列 | 让 `GET /tasks/{id}` 能解释"为什么失败"；需要一次性迁移脚本（`create_all` 不会加列）。 |
| P1-7 | `/health` 与 `scripts/health_check.py` 判定口径统一 | 抽出共享判定函数，避免两处各写一套"什么算挂了"。 |
| P1-8 | 高危工具调用审计 | `?approve_high_risk=true` 的每次放行写一条审计日志（时间/工具名/入参摘要）；字段落点待定（日志先行）。 |
| P1-9 | Streamlit「Agent 与工具」页的单工具试跑改为调 API | 与 P0-7 同一接口，页面不再直接持有 registry 实例。 |
| P1-10 | 结构化请求日志 | 每请求一条 `request_id` + 路径 + 耗时 + 状态码，便于排查；不引入第三方 APM。 |

### 4.4 P2 需求（Nice to have）

| # | 需求 | 说明 |
|---|---|---|
| P2-1 | `POST /eval/runs` 触发批量评测 | 复用任务队列跑 N 条样本；**必须继承现有高峰期拒绝闸门**（默认拒绝 + `force=true` 才放行，与 `evaluation/batch.py` 在 CLI/UI 的口径一致）。 |
| P2-2 | SSE `Last-Event-ID` 断点续播 | 需要为每任务维护事件环形缓冲（内存或缓存），断线后从指定 seq 补发。 |
| P2-3 | token 级 LLM 流式 | 需要核心层 async 化（`graph.astream` + 异步节点），M1 明确不做。 |
| P2-4 | `GET /tasks/{id}/trace` 轨迹接口 | 让「轨迹回放」页也走 API；M1 轨迹数据在同机 SQLite（`TraceStore` 用的是 `settings.db_path`），页面直读即可。 |
| P2-5 | CORS 白名单 `api_cors_origins` | 仅当未来浏览器前端直连 API 时才需要；当前 Streamlit 是服务端调用。 |
| P2-6 | 子进程隔离执行以实现"真·硬取消" | 每个任务跑在独立子进程，取消时 `SIGKILL`。代价：状态与 trace 需跨进程回传，改动面大。 |

---

## 5. UI 设计稿（Streamlit 改造部分）

### 5.1 改造范围

| 页面 | M1 是否改造 | 改造内容 |
|---|---|---|
| **2_工作流测试** | ✅ **P0 改造** | 从「页面进程内构造 `WorkflowRunner` 同步跑」改为「POST /tasks 提交 → SSE 增量渲染 → 可取消」 |
| 1_Agent 与工具 | ⚠️ **P1** | 「单独试跑一个工具」改为调 `POST /tools/{name}/invoke`；Agent 启停仍直连 DB（纯 CRUD，无编排） |
| 3_轨迹回放 | ❌ 不改 | trace 在同机 SQLite，**API 与 Streamlit 同库**，直读即可；改为走 API 收益低（P2-4） |
| 4_批量评测 | ❌ 不改 | 批量执行入口 `run_batch` 暂不 API 化（P2-1），看板仍直读 DB |

### 5.2 「工作流测试」页：改造前 vs 改造后

| 维度 | 改造前 | 改造后 |
|---|---|---|
| 执行位置 | Streamlit 脚本线程内同步执行 | API 服务进程内的线程池 |
| 提交 | 点「运行」后进入 `st.spinner("编排执行中…")`，页面阻塞 | `POST /tasks` 立即返回 `task_id`；按钮变为「提交任务」 |
| 过程展示 | `for node, update in runner.stream(...)` 直接渲染 | `httpx.stream("GET", f"{API_BASE}/tasks/{id}/stream")` 逐行解析 SSE，用 `st.empty()` 容器增量渲染（**渲染逻辑与 `_render_node_update` 保持一致**，只是数据源从生成器换成 SSE 帧） |
| 中断 | 无（只能关页面，任务随之中断） | 新增「**取消任务**」按钮 → `POST /tasks/{id}/cancel`；`queued` 时提示"已排队，取消后立即生效"，`running` 时提示"将在当前节点结束后停止" |
| 排队反馈 | 无 | 顶部状态条：`queued` 显示「排队中 · 前面还有 N 个任务（已等 X 秒）」；`running` 显示「运行中 · 当前节点 executor · 第 2/3 轮」 |
| 异常 | `st.error(f"运行失败：{exc}")` | 连接失败 → 明确提示「无法连接 API（{base_url}），请先启动：`python scripts/start_api.py`」；任务失败 → 展示 `error.code` + `error.message` |
| 计费提示 | 沿用 `status_line()` + 高峰 `st.info` | 沿用，并**额外展示 API 响应里的 `peak_pricing` / `warnings`**（服务端判定，口径统一） |
| 侧边栏 | `show_env_sidebar()` | 增加「API 连接」区块：`API Base URL` 输入框（默认 `http://127.0.0.1:8000`）、`API Token` 密码框，存 `st.session_state`，**不落盘** |

### 5.3 新增共享模块

- `ui/api_client.py`：`httpx.Client` 封装（提交/查询/取消/工具调用/SSE 生成器），统一超时（连接 3s / 读取 `api_sse_heartbeat_seconds * 3`）、统一错误翻译（httpx 异常 → 中文提示）。
- `ui/pages/__init__.py` 增加 `get_api_client()`，与现有 `get_database()` / `get_trace_store()` 风格一致。

### 5.4 明确的设计约束

**不做"API 连不上就本地直跑"的降级双实现。** 理由：一旦存在两条执行路径，「同一个任务在页面跑和在 API 跑」的结果口径迟早分裂（成本、trace、落库时机都可能不同），而这正是 `evaluation/batch.py` 当初把批量执行抽成单一入口要避免的问题。宁可报错并给出启动命令。

---

## 6. 明确不做的事（Out of Scope）

| 不做 | 理由 |
|---|---|
| **用户体系 / 多租户 / 配额** | 阶段 5 Roadmap 明确不建议做（"需要先有真实多用户需求再设计，否则容易过度设计"）。M1 只给单静态 Token 做最小闸门。 |
| **RAG 知识库** | 这是 M2 的内容，M1 只为其预留通道（工具接入与接口契约不变）。 |
| **MCP 工具协议** | 这是 M3 的内容。 |
| **前端框架迁移**（Streamlit → React 等） | 阶段 5 明确"Streamlit 在原型阶段够用，迁移成本高且不解决核心问题"（M4 范畴）。M1 只做"页面改调 API"这一步。 |
| **记忆 / 会话机制** | 依赖用户体系，且实现复杂度高，属阶段 6+。 |
| **token 级 LLM 流式输出** | 需要核心层 async 化（节点改异步 + `graph.astream`），超出 M1 工作量与风险预算。M1 只做节点级增量。 |
| **"真·硬取消"（中止飞行中的 HTTP 请求 / 杀线程）** | 同步内核 + 线程池的架构下不可行；强行做需要子进程隔离（P2-6）。M1 定义为节点边界取消，并写入 §7 已知限制。 |
| **分布式任务队列**（Celery / RQ / Redis Queue） | 单机单进程 + 线程池足够满足"并发上限 3"的验收要求；引入 Celery 会带来 worker 部署、序列化、结果后端等一堆运维成本，与"原型阶段"不匹配。**队列状态是内存态，进程重启即丢**（P1-4 兜底）。 |
| **Alembic 数据库迁移体系** | 项目当前用 `create_all`，M1 最多写一个一次性 ALTER 脚本（P1-6），不引入完整迁移框架。 |
| **API 版本前缀 `/v1`** | 尚无破坏性变更需求；加了反而要维护两套路由（留待 §8 Q6 拍板）。 |
| **WebSocket** | SSE 足够承载"服务端 → 客户端"的单向节点增量；WebSocket 双向能力当前无场景，成本更高。 |
| **限流 / 熔断 / 指标暴露（Prometheus）** | 并发上限已覆盖"防打爆"的核心诉求；可观测性留到阶段 6。 |

---

## 7. 已知限制（必须让调用方知道）

| # | 限制 | 具体影响 | 缓解 |
|---|---|---|---|
| **L1** | **取消不能中止正在飞行的 LLM 请求** | `WorkflowRunner` 是同步阻塞代码（LangGraph 节点为同步 `__call__`，跑在线程池里），Python 无法强制终止线程。取消后，最坏情况下仍要等**当前节点**跑完（单个 LLM 调用最坏 `llm_timeout × (1 + llm_max_retries)` = 120s × 4 = **480s**；工具调用最坏 `tool_timeout × (1 + tool_tool_retry)` = 30s × 3 = 90s）才会释放 worker 槽位；该节点的 token 已经花了 | ① API 场景下建议把 `llm_timeout` 调低（如 60s）；② P1-5 软超时让任务**状态**及时变 `failed`（但不释放槽位）；③ P2-6 子进程隔离是根治方案 |
| **L2** | worker 槽位不能被强制回收 | 一个卡死的任务会**永久占用**一个并发槽位，极端情况下 3 个任务卡死则队列完全停滞 | 监控 `/health.queue`；P1-5 提供可观测的软超时；必要时重启服务 |
| **L3** | 队列与进度是**进程内存态** | API 进程重启后，`queued`/`running` 的任务变成孤儿（DB 里状态卡住不变） | P1-4：启动时把残留任务标 `failed(orphaned)` |
| **L4** | SSE 是**节点级**增量，不是 token 级 | 一个节点（一次 LLM 调用）期间客户端看不到任何中间文本 | UI 上用"当前节点 + 已等待秒数"填补感知；P2-3 |
| **L5** | SQLite 并发写入 | 多线程 worker 同时写 `tasks` 表 + `TraceStore` 同库，可能出现 `database is locked` | 建议开启 WAL 模式 / 单写入线程（见 §8 Q3） |
| **L6** | 工具调用失败**返回 HTTP 200** | 沿用 `registry.call()` 不抛异常的既有契约，失败编码在 `status` 字段里 | 文档明确说明；客户端须判断 `status != "success"` |
| **L7** | `run_judge` 默认关闭 | 通过 API 提交的任务默认不产生 `eval_records`，`GET /eval` 查不到 | 需要评测时显式传 `"run_judge": true`（多一轮 LLM 成本） |
| **L8** | 高峰时段不硬拦 | 自动化系统在高峰提交会照常执行，成本翻倍 | 需要硬拦时设 `api_block_peak_tasks=true` |

---

## 8. 已知开放问题与后续计划

| # | 问题 | 备选方案 | 我的倾向 |
|---|---|---|---|
| **Q1** | 是否允许给 `TaskRecord` 加 `error_code` / `error_message` 两列（需一次性 ALTER 迁移脚本）？不加的话 `GET /tasks/{id}` 无法解释失败原因 | A. 加两列 + 一次性迁移脚本；B. 不加，错误只存在于内存/响应体；C. 复用 `final_answer` 存错误（丑，但零迁移） | **A**（可观测性缺口比迁移成本贵） |
| **Q2** | **取消语义是否接受"节点边界生效"**？规划文档原验收标准写的是"取消能正确中止正在执行的 LLM 调用"，按当前同步内核**做不到** | A. 接受节点边界语义（M1 交付，改验收标准）；B. 要求真硬取消 → 需要子进程隔离（P2-6），M1 工期翻倍；C. 要求核心层 async 化 | **A**，并在 README 与 API 文档明示 L1 |
| **Q3** | SQLite 并发写入策略 | A. 开启 WAL + `busy_timeout`；B. 所有 DB 写收口到单线程 executor；C. 换 PostgreSQL（docker-compose 已有? 需改部署） | **A**（改动最小），若压测仍锁则升 B |
| **Q4** | `canceled` 任务在 `evaluation/metrics.py` 里怎么算？ | A. 新增 `canceled` 计数，不计入完成率也不计入 failed；B. 归入 `failed`；C. 完全不计入（从样本中剔除） | **A**（与 `aborted` 的处理哲学一致：不美化数字） |
| **Q5** | 队列是否需要持久化？ | A. 内存队列（M1，重启丢）；B. 用 Redis 做队列（已有 `redis_url`，但 Redis 可不通，得处理降级） | **A**（M1 范围），P1-4 兜底 |
| **Q6** | 是否现在就加 `/v1` 前缀？ | A. 不加，后续破坏性变更时再加；B. 现在就加 | **A**（YAGNI；但需确认未来能接受一次路径变更） |
| **Q7** | `api_allow_high_risk_override` 默认值 | A. `false`（保守，符合项目 fail-closed 纪律）；B. `true`（方便，本地开发平台） | **A**，但请确认"开发时想用 API 跑 `code_exec` 是否会被这个默认值烦到" |
| **Q8** | Streamlit 与 API 是两个进程，是否需要 `docker-compose.yml` 增加 `api` 服务？ | A. 加一个 `api` service（暴露 8000）；B. 只在本地脚本启动 | **A**（否则"前后端分离"在容器环境下不成立） |
| **Q9** | `POST /tasks` 的 `run_judge` 默认 false 是否可接受？ | A. 接受（省成本，评测走批量入口）；B. 默认 true（每条都有分） | **A** |
| **Q10** | 单条任务的成本上限保护 | A. M1 不做，靠 `max_iterations` 间接约束；B. 加 `max_cost_cny` 参数，超预算在节点边界终止 | **A**（M1），B 列入 P1 |

---

## 9. M1 出口验收清单（DoD）

- [ ] `python scripts/start_api.py` 启动成功，`/docs` 可访问且 7 个端点齐全
- [ ] `curl -X POST /tasks -d '{"task":"..."}'` → 201 + task_id（≤200ms）
- [ ] `curl /tasks/{id}` → 200，能查到终态结果；不存在的 id → 404
- [ ] 连发 5 条（上限 3）→ 任意时刻 `running ≤ 3`，5 条最终全部终态，且按提交顺序执行
- [ ] 队列满 → 429 + `Retry-After`
- [ ] `POST /tasks/{id}/cancel` → 排队中直接丢弃（LLM 零调用）；运行中在节点边界停止；终态任务 → 409；取消后 10s 内状态恒为 `canceled`
- [ ] SSE：`snapshot` → `node`×3 → `done`；心跳按配置间隔；终态后关闭；`update` 不含 `messages`
- [ ] `POST /tools/calculator/invoke` → success；高危工具在 HITL 下默认 fail-closed 拒绝；未注册工具 → 404
- [ ] `GET /eval` 返回分页评测记录
- [ ] `/health`：Redis 不通 → 200 + degraded；DB 坏 → 503 + unhealthy；无 API Key → 503
- [ ] 设 `API_AUTH_TOKEN` 后无 token 请求 → 401，`/health` 与 `/docs` 仍 200
- [ ] Streamlit「工作流测试」页全程走 API，可取消，API 不可达时报错而非本地直跑
- [ ] `pytest tests/ -q` 全绿，API 测试不消耗真实 token
- [ ] 已知限制 L1/L2 已写入 `README.md` 与 `docs/m1_api.md`
