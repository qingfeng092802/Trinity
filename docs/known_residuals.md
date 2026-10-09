# 已知边界与残留（公开版）

这份清单是**已知的边界条件与当前取舍**：每条都记录了现象、可复算的判据、影响评估，
以及"什么时候才值得动"的关闭条件。级别沿用 P0/P1/P2（P0 = 影响能不能对外部署，P1 = 会让人对
产品事实产生误判，P2 = 口径与工程卫生）。

> **适用前提**：本项目面向**单机 / 内网**场景设计，默认只监听 `127.0.0.1`；
> 下文 A 组的三条 P0 均在这一前提下评估。公网部署前请先完成 README「部署到公网前」一节
> 列出的加固项（改默认口令 / HTTPS 反代 / 限制 `config/` 与 `.solve_cache/` 访问）。

三点交代：

- **每条的判据都在本工作树实测过**（2026-10-07）。行号会随改动漂移，所以能用 grep / 命令复算的
  一律给命令，别信这里的行号本身。
- **端口**：文中 curl 示例一律写 `:8000`（`config.py` 的 `api_port` 默认值）。如果你按 README 的
  本地链路起服务（`start.bat` 与 `uvicorn` 示例都是 **8001**，vite 代理也指 8001），
  把示例里的 8000 换成 8001 —— 这些判据读的是「回 2xx 还是 401」，不是端口号本身。
- 文中「已关闭」的条目**不删**，留作证据链（改口不删账）。

---

## A · 鉴权与暴露面

### A-1 默认配置下**所有路由免鉴权**（P0）

**现象**：`API_AUTH_TOKEN` 为空时，鉴权依赖第一句就直接放行 —— 不是"只豁免健康检查那几条"，
是全部路由开放。豁免清单（`/health` `/docs` `/openapi.json` `/redoc`）只在**已经设了 token**
时才起作用，别把它读成"默认只开放这几条"。
**判据**：`api/deps.py` 里 `verify_token` 的第一句 `if not settings.api_auth_enabled: return`；
`api/constants.py` 的 `AUTH_EXEMPT_PATHS`。实跑复算：不设 token 起服务，
`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/tasks` 应回 **200/受理**而不是 401。
**影响 · 为什么现在不动**：唯一的实质缓解是默认只绑 `127.0.0.1`；监听非回环地址时
`api/main.py` 会打一条 `logger.error`，**但那只是日志，不是闸**。免鉴权可达的写状态动作包括
`POST /tasks`（花真实 LLM 额度）、`POST /knowledge/documents`（投毒语料）、
`DELETE /knowledge/documents/{id}`（删数据）、`POST /models/key`（把别人的 Key 塞进本进程）。
本地单人使用把风险收窄到"同机其它进程"，所以默认没改。
**关闭条件**：`API_AUTH_TOKEN` 设为启动必填（为空即拒起）+ 前端补 token 输入口。成本已评估：
校验只能放 `lifespan`（`get_settings()` 被全站消费，放字段校验器里等于让每个用例与脚本一起拒起），
且集成用例的 fixture 显式删掉该环境变量 ⇒ 要连带改；半天以上，排在演示窗口之后。

### A-2 设了 token，这套控制台就整套不可用（P0）

**现象**：前端没有任何一处发 `Authorization` 头，也没有 401 后的重试/输入态。
**判据**：`grep -rn "Authorization" web-react/src` ⇒ **0 命中**（2026-10-07 实测）。
后端一旦启用鉴权，`/tasks`、`/knowledge/*`、`/models/*` 全部回 401。
**影响**："要对外服务"与"要用界面"目前是互斥的两件事。这不是本轮新退步 —— 旧版静态控制台同样
没有输入口，被删掉时这个缺口就被固化了。
**关闭条件**：一个 token 输入（存 sessionStorage 即可）+ `client.ts` 里统一带头 + 401 切到
"请输入 token"的状态。⚠️ 做完必须补一条探针判据：**401 与"确实没有任务"在界面上现在长得一样**
（都渲染成空数据），不钉住这条就会再一次把"没权限"显示成"没数据"。

### A-3 `?deep=true` 落在免鉴权路径上，可反复触发真实付费调用（P0）

**现象**：`/health` 在豁免清单里，而它接受 `deep` 查询参数 —— 带上它就真调一次 LLM 探针。
**判据**：`api/constants.py` 的 `AUTH_EXEMPT_PATHS` 含 `/health`；`api/routes/health.py` 里
`deep: bool = Query(default=False, ...)`。复算：不设 token 时
`curl "http://127.0.0.1:8000/health?deep=true"` 会产生一次真实调用。
**影响**：免鉴权 + 监听非回环时，同网段任何人可以反复点击这个按钮烧额度（零 token 的接口也照样白送）。
**关闭条件**：`deep=true` 单独要求 token，或检测到绑定非回环地址时直接拒绝 `deep`。

### A-4 上传先把整个文件读进内存，再判它超没超限（P1）

**现象**：注释写的是"大小校验（超限直接 422，不落盘）"，紧接着的代码是先 `file.file.read()`
整份读进内存，**然后**才比 `max_bytes`；Starlette 的 multipart 还会先把请求体 spool 到临时盘。
**判据**：`api/routes/knowledge.py` 的上传路由里 `payload = file.file.read()` 在
`if len(payload) > max_bytes` **之前**；全仓 grep `content-length` / body-limit 中间件 = 0；
该路由是同步 `def`（走线程池）⇒ 并发上传数不设上限。
**影响**：成本 = 整份体积先占盘、再整份进内存，乘以并发数。上限本身是有值的
（`knowledge_max_file_mb`），所以不是"无界"，而是"超限之前先付了全额"。
**关闭条件**：边读边累加、过阈值即 413 中断；顺手把那句注释改成实话。

### A-5 代码沙箱只有墙钟超时，没有任何资源上限（P1）

**现象**：`run_python` 类工具走子进程，只有超时这一道闸；CPU / 内存 / 磁盘 / 进程数 /
输出字节都没有第二道。`proc.communicate(timeout=...)` 会把子进程的 stdout/stderr **无上限**
灌进 API 进程，只在最后一步截断展示。入参侧 `ToolInvokeRequest.args: dict[str, Any]`
是全站唯一没有 `max_length` 的字符串入口（任务 4000、query 1000、api_key 256 都有上限）。
**判据**：`grep -c "setrlimit" core/tools/sandbox.py` ⇒ **0**，全仓也搜不到 Job Object 的调用
—— "Job Object" 这个词只出现在该模块 docstring 的**说明**里（`:14` 明写"要围住资源得引
Job Object"，也就是承认现在没做）；代码里只搜得到 `timeout=`。
`api/schemas.py` 的 `ToolInvokeRequest` 没有 args 长度约束。
**影响**：队列与在途任务都活在这一个进程的内存里，所以后果不是"这一次慢"，而是整个服务被打爆。
**关闭条件**：入口给 `len(code)` 封顶 + 读侧分块按字节截断（超阈值即 kill）。真要围住资源，
Windows 上得引 Job Object / AppContainer —— 那不是"一行顺手"的量级，本机也未验证。

---

## B · 界面能力被砍掉之后

（旧版零构建静态控制台 `/console` 与 Streamlit 界面于 2026-09-27 一并删除；后端**路由与字段一个没动**，
缺的只是消费它们的那一侧。下列四项是删掉的界面里带走的、React 控制台尚未补回的能力。）

### B-1 任务列表只在"最近 30 条"里筛（P1）

**现象**：后端 `GET /tasks` 支持 `status` / `limit` / `offset`（`limit` 默认 50、**上限 200**，
响应带 `total`），但前端只发 `?limit=`，并且两个页面都写死 `fetchTaskList(30)`，
过滤是在这 30 条里用 `Array.prototype.filter` 做的。
**判据**：`grep -n "fetchTaskList" web-react/src/api/client.ts web-react/src/pages/*.tsx`
（两处调用都是 30）；`grep -n "status=\|offset=" web-react/src/api/client.ts` ⇒ **0**。
**影响**：超过 30 条的历史任务在列表里**根本不存在** —— 筛出来是"没有这条"，不是"还没加载"。
这类失效不报错、不红屏，只有人去找旧任务时才看得见。
**关闭条件**：`fetchTaskList` 补三个参数、把过滤条件写进请求、用响应里的 `total` 显示"共 N 条 / 第 k 页"。
注意 `limit` 上限是 200，"一次拉全"是拿不到的；`status` 传非法值后端回 **422** 而不是忽略。

### B-2 `/stats/dashboard` 没有任何消费者（P2）

**现象**：聚合看板（完成率 / 平均分 / 近 14 天序列 / 系统状态）后端仍在算、用例仍绿，界面不显示。
**判据**：`grep -rn "stats/dashboard" web-react/src` ⇒ **0**；`client.ts` 里连对应的函数都没有。
**影响**：README 的功能表因此不敢提"看板"。
**关闭条件**：这不是删掉就能补的一项 —— 要先决定"哪些数字值得占一屏"，是一次设计决定，不是搬家。
响应形状已在 `api/schemas.py::DashboardStatsResponse` 里，后端不需要动。

### B-3 消融报表的"任意两臂逐题 diff"读取端无人调用（P2）

**现象**：`evaluation/ablation.py` 里的 `diff_rows()`（以及 `significance_rows()`）仍在，
消费它们的旧 Streamlit 对比页已随 `ui/` 删除；控制台 `EvalAblationPage` 只读总表与两类失败归因。
**判据**：`grep -n "def diff_rows" evaluation/ablation.py` 有定义；
`grep -rn "diff_rows\|ablation-diff" web-react/src api/routes` ⇒ 无消费点。
**影响**：后端仍能产出的能力，界面这一侧看不到；文档里提到"逐题 diff"时要说明它今天只在代码层。
**关闭条件**：要么在控制台补一屏两臂对比，要么把这两个函数连同测试一起摘掉（别留"看起来还在"的读取端）。

### B-4 知识库页没有检索测试（P2）

**现象**：知识库页提供上传、解析/索引状态机进度、文档与 chunk 读数，**没有**检索输入框；
`GET /knowledge/search` 只在 API 侧。
**判据**：`grep -rn "knowledge/search" web-react/src` ⇒ **0**。
**影响**：想验一条检索结果得开 curl 或让 Agent 走 `knowledge_search` 工具。README 的功能表已把
这句话写进去，免得人来者页面上找搜索框。
**关闭条件**：在知识库页加一个"试检索"小面板（复用 `/knowledge/search`，把 `bm25_score` /
`vector_score` / `score` 三列都摆出来），顺带能演示权重对排序的实际影响。

---

## C · 评测数字的可复核性

### C-1 今天的代码**不产 p 值**（P1）

**现象**：`evaluation/ablation.py` 的配对比较只报 `delta` / `rel_lift`；原先的
McNemar / Wilcoxon / Holm–Bonferroni（`evaluation/stats.py`）已于 2026-09-21 整条删除。
`p_raw` / `p_adjusted` 字段留在契约里但一律 `None`，落盘多了一个 `"significance_removed": true`。
**判据**：`grep -n "significance_removed" evaluation/ablation.py`；决策与理由写在同文件的
`PairedComparison` docstring 里（"样本量给不出可信 p 值，与其报一个伪精确的 p=0.031，
不如老老实实报 delta 与 rel_lift"）。
**影响**：仓库里出现的 p 值（0.000473 / 0.0199 / 0.0130 / 0.3958）**全部是历史留档**，
包括 `docs/m3_design.md` 那张 15 臂表的最后一列与 README 的 30 秒摘要。
**关闭条件**：不恢复检验（这是取舍，不是缺陷）。要对外引用结论时一律写 Δ + 波动带，
并把"当初为什么放弃检验"讲出来 —— 这一句本身比一个 p 值更有说服力。

### C-2 消融矩阵与报告里的数字仍是旧度量口径（P1）

**现象**：向量度量曾在某趟里把 L2 距离当相似度用，纠正之后只复跑了检索评测
（top-1 / top-3 / hit@5 / MRR），nDCG@5 那张 15 臂表**没有**在新度量下重跑。
**判据**：`docs/m3_ablation_report.md` 里的口径限定段；对比
`python scripts/eval_retrieval.py`（新口径、零 LLM 成本）与 `docs/m3_design.md:839` 那张表。
**影响**：跨表比数字会错。同一份语料上"纯 BM25 优于混合"这个结论在新口径下被复算坐实过，
但 nDCG 列的绝对值属于旧趟。
**关闭条件**：跑一趟 `scripts/run_ablation.py --phase A`（本地模型、零 API 成本，1,000 篇 / 300 题，
十几分钟量级）后把表与报告一起重出；重出前不要在别处引用那些 nDCG 绝对值。

### C-3 报告头号结论（精排 +3.66pp）在本机今天不可复跑（P1）

**现象**：精排臂需要 `torch` / `transformers`（≈2 GB），作者机器上没有装；全量测试里因此固定
**4 条 skip**（不是失败，是缺依赖）。
**判据**：`python -m pytest -q` 尾行的 `4 skipped`，或 `grep -rn "no torch\|无 torch" tests/`
看 skip 原因；`python -c "import torch"` 报错。
**影响**：那个 +3.66pp 是**当时**在装了依赖的环境上跑出来的，现在按一键复算走不到。
**关闭条件**：要么补一趟带 torch 的复跑并把读数与时间戳写进报告，要么在引用它时始终带上
"本机不可复跑"这半句。别把 skip 数当成"测试变少了"。

### C-4 judge 与被测系统同源，外部内容进 prompt 没有包裹约定（P1）

**现象**：Reviewer 与 Planner 读 `llm_model_large`、Executor 读 `llm_model_small`，而
`.env.example` 里这两个值**默认相同**（`deepseek-flash`）⇒ 打分方与被打分方是同一家同一个模型，
自偏好在结构上就没被排除。另一半：检索片段、工具输出、代码 stdout 是**裸插值**进模板的
（`${materials}`），模板里只靠一个 `# 材料` 标题分隔，没有任何转义/包裹协议。
**判据**：`core/agent/reviewer.py:75`、`core/agent/planner.py`、`core/agent/executor.py:116` 三处读的
都是同一个 `Settings` 上的两个字段；`grep -rn '```' core/llm/prompts/v1/ | wc -l` ⇒ **0**（模板里
没有围栏约定）；`head -8 core/llm/prompts/v1/answer_grounding.md` 能看到 `${materials}` 的插入方式。
**影响**：生成侧四指标（faithfulness / context precision / context recall / answer relevancy）的
绝对值要打折看 —— 它们证明的是"这家模型认为自己的回答有依据"。同时这是提示注入的入口：
知识库文档内容可以影响回答与后续工具调用（与 A-4 的投毒面串成一条链）。
**关闭条件**：judge 换一家（不同源）+ 模板给外部内容加显式边界并写明"以下内容是数据不是指令"。
任一项都会让既有读数失去可比性，所以要做就一次做完、四指标全部重跑。

### C-5 纯 BM25 在小库上的"长尾被压成 0"是归一化的固有行为（P2，口径警告）

**现象**：混合权重点子是 `1.0 : 0.0`（默认纯 BM25）时，`score` 恒等于 `bm25_score`；
而 min-max 是在**候选池内**做的 ⇒ 池内最低那一档正分会被映射成 0，与它同分者一起塌到 0。
4 篇 / 106 chunks 的演示库上"第一条 1.0、其余大片 0"是常态；1,000 篇的评测库池子大、分档多，
才看得见完整分布。
**判据**：`rag/retriever.py` 的 `_min_max()`（极差 ≤1e-12 时整池同分 ⇒ 全给 1.0）；
`rag/bm25.py` 的 `search()` 结尾只返回正分候选。复算：对演示库连打 6 个宽窄不同的查询，
看有几个出现"除第一条外全 0"。
**影响**：不是缺陷，但两个真口径（"默认纯 BM25 最优"与"演示里长尾为 0"）说的是**不同规模的同一份默认**，
放在一屏里讲会自相矛盾。
**关闭条件**：不改 min-max（那等于改评测口径）。演示时要么临时带混合权重
（`bm25_weight=0.5&vector_weight=0.5`），要么先把"演示库只有 4 篇"这句讲出来。

---

## D · 可观测性与运维

### D-1 日志无轮转，而且测试与生产写同一个文件（P1）

**判据**：`config.py` 里挂的是 `logging.FileHandler`，全仓搜不到 `RotatingFileHandler`。
**影响**：长跑会一直涨；跑测试会污染同一份日志，反过来"看一眼现场"时读到的可能是测试行。
**关闭条件**：按大小轮转 + 测试用独立日志路径（或干脆 `LOG_FILE` 为空 = 只写 stderr）。

### D-2 `request_id` 从没进过日志格式（P1）

**现象**：中间件给每个请求生成 `request_id`、写进 ContextVar、并回写 `X-Request-ID` 响应头，
但日志 format 串里没有它。
**判据**：`config.py` 的 `format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s"` —— 没有
`%(request_id)s`；而 `api/schemas.py` 里有"便于在服务端日志里定位"这类对外描述。
**影响**：客户端拿到一个 id 却没法在服务端日志里 grep 到它 —— 那句对外声明是虚的。这是"响应头算了、
日志里不落"的一类通病。
**关闭条件**：加一个 `logging.Filter` 把 ContextVar 注入 record，并把格式补一列；补一条用例断言
"同一请求的响应头 id 能在日志行里找到"。

### D-3 非成功终态都记 INFO，按级别筛抓不到任何一次业务失败（P1）

**判据**：`api/queue.py` 里"排队期被取消""节点边界停止""运行期闸门中断""闸门想中断但任务已终态"
四条都是 `logger.info`；`warning` 只出现在事件落盘失败这类基础设施异常上。
**影响**：拿 `level>=WARNING` 筛日志，会以为服务从没失败过。
**关闭条件**：终态按语义分级（取消 = INFO、失败/中断 = WARNING 或 ERROR），并在 README 的运维一段
写清"怎么只看失败"。

### D-4 前端是完全盲区：零上报通道（P1）

**判据**：`grep -rln "Sentry\|sendBeacon\|navigator.send" web-react/src` ⇒ **0**。
**影响**：SSE 断流、重连放弃、渲染异常、EventSource 报错，后端一概不知道；界面出问题只能靠人复述。
这条与 A-2/D-2 是同一族：**可观测性只做到了服务端一半**。
**关闭条件**：最小的一步是给 `EventSource.onerror` / `window.onerror` 加一条上报（不必第三方），
后端补一个计数端点，`/health` 里露出来。

### D-5 `/health` 回 unhealthy 不会让容器重启（P2）

**判据**：`docker-compose.yml` 只有 `healthcheck` + `restart: unless-stopped` ——
Docker 本身不会因为容器 unhealthy 而重启它。
**影响**：健康检查的作用被限制在"人能看到"，不是"系统能自愈"。别把配了 healthcheck 当成有自愈。
**关闭条件**：要么明确写"仅用于可见性"，要么引 autoheal 一类 watcher（多一层故障域，需评估）。

---

## E · 依赖与可复现性

### E-1 依赖全是 `>=` 下限、没有 lock ⇒ 镜像不可复现（P1）

**判据**：`pyproject.toml` 的 `dependencies` 全是 `>=`（fastapi>=0.115、langchain-core>=0.3、
pydantic>=2.7…），仓内没有 `*.lock`。而作者机器上实际装到的是 **fastapi 0.135.1 /
langchain-core 1.2.19 / pydantic 2.12.5**（`python -m pip show ...` 实测）——
`langchain-core` 的下限是 0.x、实装是 1.x，跨了一个 major。
**影响**：新机器 `pip install` 解析出的组合与作者测过的**不是同一个**。表现通常不是"装不上"，
而是"某个签名变了"——最难查的那类。
**关闭条件**：出一份 lock（`uv lock` / `pip freeze` 生成的 constraints 都行），
并在 CI 里跑一次"按 lock 安装"的作业。

### E-2 Python 版本有多套口径，且下限早被越过（P2）

**判据**：`requires-python = ">=3.12"`、`Dockerfile` 是 `FROM python:3.12-slim`、
CI 用 3.12、mypy `python_version = "3.12"` 四处一致，但作者本机日常跑的是 3.13.9。
**影响**：CI 只证明 3.12 能过，不证明 3.13/3.14 能过；反过来"我机器上是好的"也不覆盖 CI。
**关闭条件**：CI 矩阵加一档（3.12 + 3.13），或者把下限抬到实际验证过的那一档并写明。

### E-3 Dockerfile 用 heredoc 装依赖，经典 builder 下可能静默产出"空壳镜像"（P1，⚠️ 未在实跑中验证）

**判据**：`Dockerfile:42` 是 `RUN pip install --upgrade pip && python - <<'PY'`。
`DOCKER_BUILDKIT=0`（或某些 daemon 配置）会把 heredoc 那半段**静默吃掉**，
于是 RUN 只做了 `pip install --upgrade pip`，镜像里没有业务依赖，构建照样成功。
**影响**：失败点在运行期（import 失败），而不是构建期报错 —— 排查方向容易被带偏。
**关闭条件**：把 heredoc 换成写成文件的脚本再 `RUN python /tmp/probe.py`，或加一条构建期冒烟
（`RUN python -c "import fastapi, uvicorn, api.main"`）。⚠️ **本条在公开副本里未实跑验证**
（作者机器 Docker 引擎当时未启动），是从读码与已知 builder 行为推出来的。

### E-4 评测的模型来源由代码 `setdefault` 到第三方镜像（P2）

**判据**：`evaluation/ablation.py:1627-1628` 有
`os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")`。
**影响**：权重的实际来源取决于环境变量，不在 `requirements` 也不在文档里；直连不通的机器上
它会"悄悄生效"，能连直连的机器上又不会。两端拿到的可能不是同一份权重（且没有 revision 可钉）。
**关闭条件**：把端点与 revision 写进配置与报告口径（一次跑批记录里带上权重来源与哈希）。

---

## F · 许可与语料

### F-1 代码是 MIT，但**1,000 篇 CMRC2018 派生文档是提交进仓库的**（P1）

**现象**：`evaluation/fixtures_cmrc/`（1,000 个文件）与题目集来自 `hfl/cmrc2018`，
许可 **CC-BY-SA-4.0**。来源与许可写在 `docs/m3_ablation_report.md` 与
`evaluation/dataset/golden*_manifest.json` 里，但仓库根的 `LICENSE` 只覆盖代码（MIT），
没有 NOTICE/ATTRIBUTION。
**判据**：`ls LICENSE NOTICE*` ⇒ 只有 MIT 的 LICENSE；`grep -rn "cc-by-sa" docs evaluation` 有来源声明。
**影响**：别人 fork 或再分发这份数据时，ShareAlike 的义务不在 LICENSE 里，容易漏。
这条对**公开仓库**比对内部开发更要紧 —— 一旦公开，分发行为就发生了。
**关闭条件**：加 `NOTICE`/`ATTRIBUTION.md`（写明数据集、作者、许可、修改说明），并在 README
「许可证」一节把"代码 MIT / 语料 CC-BY-SA-4.0"分开写。

---

## G · 测试与门禁自身的洞

### G-1 `unit` / `integration` marker 没在 ini 里登记（P2）

**判据**：`grep -c "markers" pyproject.toml` ⇒ **0**；跑测试时满屏
`PytestUnknownMarkWarning: Unknown pytest.mark.unit`。
**影响**：告警噪音会淹没真信号，`-m unit` 这类筛选靠约定而不是登记。
**关闭条件**：`[tool.pytest.ini_options] markers = ["unit: ...", "integration: ..."]` 两行。

### G-2 `tests/` 不在 mypy 的配置目标里（ruff 覆盖它）（P2）

**判据**：`pyproject.toml` 的 `[tool.mypy].files = ["api", "config.py", "core", "storage",
"evaluation", "rag"]` —— 没有 `tests`；`[tool.ruff]` 没有 exclude ⇒ ruff **会**查 tests。
**影响**：测试代码里的类型错误不会在门禁里露头（用例照样能跑绿）。⚠️ 口径更正：早先记的
"测试在**两道**静态门禁里都是盲区"只对 mypy 成立，ruff 那半句是错的。
**关闭条件**：把 `tests` 加进 mypy files，或明确记录"测试代码不做类型检查"这个取舍。

### G-3 偶发建表 ERROR：判定桩已落，真因仍未定（P2）

**现象**：集成用例偶发在 fixture setup 阶段报 `sqlalchemy.exc.OperationalError: table tasks already exists`，
发生在 setup ⇒ 那两条断言从未执行，严格说连"失败"都算不上。
**判据**：`grep -n "engine.url" conftest.py tests/` 能看到那条判定桩（它把"指到生产库"这个假设排掉了）；
复现是概率性的，桩落下后本仓库多次全量未再复现。
**影响**：竞态仍是**假设**，不是结论。刻意只留桩不追根因 —— 追它需要连续多轮全量，成本高于收益。
**关闭条件**：再次复现时留下完整正文（全量带 `--junitxml`），并检查共享 engine 的生命周期；
不复现就维持"疑似环境抖动"的标注。

### G-4 README 的用例数是裸数字，会随每条新增而漂（P1，**已关闭 2026-10-07**）

**现象**：README 的 30 秒摘要曾写 **983（744 单元 + 239 集成）**，而本工作树同一天的实测是
**1,055 = `tests/unit` 812 + `tests/integration` 243**。用例数每加一条就漂，
而 README 是别人读的第一份文件 —— 漂了就等于文档会说谎。
**判据（复算命令，别抄这里的读数）**：

```bash
python -m pytest -o addopts= -q --collect-only | tail -1        # 1055 tests collected
python -m pytest tests/unit -o addopts= -q --collect-only | tail -1       # 812
python -m pytest tests/integration -o addopts= -q --collect-only | tail -1 # 243
```

`-o addopts=` 是必要的：`pyproject.toml` 的 `addopts = "-q"` 会和命令行那个 `-q` 叠成
双层 quiet，此时 `--collect-only` **不打印** "N tests collected" 那一行（实测读不出数）。
**关闭条件**：判据写成**关系式**而不是定值 —— README 里那个位置必须同时给出
**复算命令 + 当前读数 + "截至 <日期>"**，且三样与改动它的那一笔 commit 同签。
**已按此落**：README「测试」一节给的是命令 + 读数 + 日期，30 秒摘要那行改成引用它而不是重抄一份数。

### G-5 版本号有多个手写位（P2，**已关闭 2026-10-07，按关闭条件②**）

**现象**：`pyproject.toml` 的 `version` 与 `api/__init__.py` 的 `__version__` 是两份手写的
同一数，没有单一真源。**这条隐患在 v0.2.0 发布时真的发生了**：只改了 `pyproject.toml`，
`api/__init__.py` / `core/__init__.py` / `web-react/package.json` 三处仍停在 `0.1.0`，
于是包说 0.2.0、`/openapi.json` 的 `info.version` 还说 0.1.0 —— 与本条原先的预判逐字一致。
**判据**：`grep -n '__version__' api/__init__.py` 是字面量（不是
`importlib.metadata.version(...)`）；而本机的 `python -m pip show trinity` /
`importlib.metadata.version("trinity")` 在未 `pip install -e` 的解释器里
**PackageNotFoundError**（⇒ 也不能简单把 metadata 当唯一真源，它要求包已安装）。
**影响**：CI 与测试都不检查版本一致性，所以这个漂移是静默的。
**关闭条件**：二选一 ——①`api/__init__.py` 改成 `try: importlib.metadata` /
`except PackageNotFoundError: __version__ = "0.0.0+unknown"` 并让 `pyproject` 保持唯一手写位；
②留两份但加一条用例断言两者相等（最便宜，且不改变"未安装也能跑"的现状）。
**已按此落**（取②）：四处手写位统一到 `0.2.0`，并新增
`tests/unit/test_version_consistency.py`，断言 `pyproject.toml` / `api/__init__.py` /
`core/__init__.py` / `web-react/package.json` 四者相等 —— 漏改一处即变红，不再静默。
README「版本与发布」一节同步改写为四处清单并指向该用例。

---

### G-6 静态门禁有存量，而 CI 完全不看它们（P2，**未关闭**）

**现象**：仓库顶上的 CI 徽章是绿的，但它只跑 `pytest -q`；`ruff` 与 `mypy` 在本树都**不为 0**。
"CI 绿"因此证明不了"静态检查干净"，更证明不了"前端能构建"（CI 里没有 `tsc`、没有 `npm run build`）。
**判据**（读数随改动漂，命令才是判据；下面是 2026-10-07 的本树实测）：

```bash
ruff check . 2>&1 | tail -2          # Found 36 errors.（其中 15 条 --fix 可自动修）
mypy 2>&1 | tail -1                  # Found 34 errors in 17 files (checked 84 source files)
grep -c "^\s*run:" .github/workflows/ci.yml   # 2（一条装依赖、一条跑测试）
```

**影响**：三个口径容易被人混成一个 ——「测试全过」≠「静态干净」≠「界面能构建」。
另外 mypy 那 34 只是**配置内**的数（`[tool.mypy].files` 六个目标，不含 `tests/`，见 G-2），
把它读成"全仓库只剩 34 个问题"也是错的。
**关闭条件**：要么把 `ruff --statistics` 的基线快照与 `mypy` 各做成一个 CI 作业（存量清单进基线文件，
只拦新增），要么在 README 明写"存量不承诺清零"。后者已经写了（`../README.md` 的「测试」一节
最后两条 bullet 给了 ruff/mypy 的实跑读数并声明 CI 不管它们）；**没做的是前者**。

---

### G-7 「从头订阅」的 SSE 流其实不重放已发布事件（P1，**未关闭**）

**现象**：`tests/integration/test_api_stream.py::test_stream_full_sequence` 的 docstring 写着
"从头订阅：snapshot → node×N → done"，但事件总线的 `subscribe()` 只是新建一个空队列
（`api/events.py:86-91`），**没有任何历史补发**。所以谁先谁后决定收几条：
若 worker 在客户端建流之前已经发了 planner 那帧，这一帧对该连接就永远不存在。
**复现（本树 2026-10-07）**：终态树连跑三次全量 —— 两次 **0 failed**、一次这条 **failed**
（`assert 1 >= 2`，收到的唯一 node 增量是 `reviewer`、`seq=7` —— planner 那帧掉在订阅之前）；
单跑该文件 11/11 绿 ⇒ 是时序竞态，不是逻辑坏了。判据：
`python -m pytest tests -o addopts= -q --junitxml=gate.xml`（多跑几次看 failures 是否只出现在这一条）。
**机制另一半**：`publish()` 在事件循环还没绑定时直接丢弃并 `_dropped_without_loop += 1`
（`api/events.py:113-119`），而这个计数器**没有任何出口读**（全仓只有它自己写）
⇒ 丢事件既不补也不可见，所谓"对账"在这一层是没有的。
**影响**：界面侧被"终态补拉"兜住了（控制台在任务进终态后重取 `/tasks/{id}` 与 `/tasks/{id}/trace`，
见 `web-react/src/pages/TaskLogPage.tsx:347`），所以用户看到的最终轨迹是全的 ——
代价是**中间过程可能少几帧**，而任何直接消费 SSE 的新客户端（第三方、脚本、以后的小工具）
会把"少帧"当成事实。别把这条流当可靠投递用。
**关闭条件**：二选一，别混着做。① 语义改成"确实从头"：`subscribe()` 之后先从 TraceStore
按 `seq` 补发到当前位置，再转 live —— 要顺带处理"补发与 live 的接缝去重"，
且浏览器重连游标在这个后端本来就不可用（`id:` 跨连接不单调），别指望用 `Last-Event-ID` 抄近路；
② 语义承认"从订阅时刻起"：把用例的 `>= 2` 改成断言"终态必到 + 收到的帧单调递增"，
并在文档与 docstring 里把这句写进契约。② 便宜且不碰生产代码，① 才是用户以为的那件事。

---

### G-8 全量跑 pytest 偶发一条集成用例 setup ERROR（P2，flaky 登记）

**现象**：全量 `pytest tests` 约 1/3 的跑次里，`tests/integration/test_api_agent_options.py::test_三档预设都在响应里且带得出换算` 在 **setup 阶段**报 ERROR；同一条用例**单跑必过**，全量重跑也过。CI 已实际观察到同一棵树一次绿一次红（树 `ecfcdb3e`：`cbdda2f` 绿、`08fda04` 红 —— force push 重写历史前后内容一字不差）。
**判据**：单独跑 `.venv/Scripts/python -m pytest "tests/integration/test_api_agent_options.py::test_三档预设都在响应里且带得出换算" -q` 必过；全量跑到 100% 且 summary 里仅此一条 ERROR 即复现。
**影响 · 为什么现在不动**：ERROR 出在 `api_env` fixture 的启动链（`_start_client` 里 lifespan 起队列 + 0.1s 心跳线程，疑为启动竞态），不是断言失败；ERROR 计数为 0 时全量 100% 通过，不影响任何交付结论，也证明了它的非确定性。
**什么时候动怎么动**：给 `api_env` 的 lifespan 启动加确定性就绪等待（轮询 `/health` 后再 yield），或引入 `pytest-rerunfailures` 给集成用例挂 reruns=1。修复判据：连续 10 次全量 0 ERROR，CI 连续 10 次 run 全绿。

---

## H · 计量口径：一次任务的「耗时」与「钱」

### H-1 轨迹页的「总耗时」把节点 span 和单步耗时加了两遍（P1，**未关闭**）

**现象**：轨迹回放页顶部那块「总耗时」指标卡读出来是墙钟的 **1.69–2.00 倍**。
README 首屏 GIF 里就能看到它（那一格显示 `1m 10s`，而那条任务真实墙钟 41.6 s）。

**判据（机制）**：`web-react/src/pages/TraceReplayPage.tsx` 的 `stats` 里
`const ms = shown.reduce((s, e) => s + (e.latency_ms ?? 0), 0)` —— 它对**每一条事件**求和，
而事件流里同一个节点既有 N 条 `llm_call`（单步耗时）又有一条 `node_end`
（整个节点的 span，已经把本节点那些 `llm_call` 全包在里面）⇒ 两层相加就是重复计。
它下面的 hint `平均 …… / 步` 用同一个 `stats.ms` 除以条数，跟着一起偏。

**实测（2026-10-07，隔离实例上三条真实任务，`deepseek-flash` 驱动）**：

| task_id | `tasks.duration_ms` | Σ `node_end` | Σ 全部事件 | 倍数 |
|---|---|---|---|---|
| `task-6fab9b086ab5` | 23 155 | 23 155 | 46 139 | 1.99× |
| `task-40b89159db26` | 28 642 | 28 642 | 57 232 | 2.00× |
| `task-864552ce1e28` | 41 594 | 41 594 | 70 225 | 1.69× |

中间那列与 `tasks.duration_ms` **逐位相等** ⇒ 正确口径就是"只加 `node_end`"。复算：

```bash
curl -s "$BASE/tasks/<task_id>/trace?limit=500" | python -c "import sys,json;e=json.load(sys.stdin)['items'];print('all',sum(x['latency_ms'] or 0 for x in e),'node_end',sum(x['latency_ms'] or 0 for x in e if x['event_type']=='node_end'))"
```

**筛选态更难看**：那三个节点 chip 一按，`shown` 只剩 Executor 的 7 条，求和变成
"Executor 的 4 条 `llm_call` + 它自己的 `node_end`" —— 实测 `task-6fab9b086ab5`
读出 **31.3 s**，而 Executor 节点真实 20.2 s、整条任务才 23.2 s。读起来像"这一步比整条任务还久"。

**关闭条件**：求和限定在 `node_end`（或只加 `llm_call` + `tool_call`，但要先确认工具重试时
`tool_call` 是否也落在节点 span 内，别换成另一个双重计数）。改完补一条 fast 用例钉住
"页面总耗时 == `tasks.duration_ms`"；筛选态的语义另定（"这一类节点合计多少"还是"占墙钟多少"），
别沿用同一个标签。
**为什么现在不动**：读数口径缺陷，不崩；而"对的那个说法"要连筛选态语义一起拍，归后端/前端账。

### H-2 `tasks.cost` 只记每个节点**最后一次** LLM 调用（P1，**未关闭**）

**现象**：多步任务的实际花费被少算 37–39%（`tasks.cost` / Σ 事件成本 = 0.61 … 0.64），
而 `/cost-breakdown` 自带的对账位在真实任务上就是 `false`。

**判据（机制）**：节点出口的埋点取的是 `last_usage`。`core/agent/base.py` 的
`per_call_llm_events` 那段注释（2026-10-02，Q6-01）把这件事写得很明白：
"executor 一次节点调用里跑完整轮计划…每步一次**真实付费**调用，而出口这条汇总事件只取
`last_usage` = 最后一步的用量 ⇒ N 步只记 1 笔，成本闸门 / `tasks.cost` / 成本面板 / 报表一起少算"。
Q6-01 的修法只补了 **`llm_call` 事件通道**（一步一条），出口那条 `TraceRecord` 仍然带末次用量；
而落库的是 `evaluation/metrics.py` 里 `TaskOutcome.from_state` 的
`cost=round(sum(record.cost for record in records), 6)` —— 加的是**节点记录**，
于是 Executor 的四次调用只有最后一次进了 `tasks.cost`。

**实测（同上三条任务，单位元）**：

| task_id | Σ 事件成本（真值） | `tasks.cost` | 差额 | Σ「每节点末次调用」 |
|---|---|---|---|---|
| `task-6fab9b086ab5` | 0.042594 | 0.026377 | +61% | 0.026376 |
| `task-40b89159db26` | 0.052253 | 0.031871 | +64% | 0.031871 |
| `task-864552ce1e28` | 0.054580 | 0.034503 | +58% | 0.034502 |

最后一列与 `tasks.cost` 在 1e-6 内相等（差额来自逐条 `round(…, 6)`）⇒ 机制定位成立。复算：

```bash
curl -s "$BASE/tasks/<task_id>/cost-breakdown" | python -c "import sys,json;d=json.load(sys.stdin)['reconcile'];print(d['all_equal'],d['events_cost'],d['task_cost'])"
```

**门禁为什么没拦住（判据恒真）**：`tests/unit/test_cost_breakdown.py` 的 T1
确实断言 `reconcile.all_equal is True`，但它喂的是 `_REAL_RUNS` 那五条真实样本，
每条恰好 **3 次调用**（planner / executor / reviewer 各一次，用例里写死了
`assert calls == body["totals"]["calls"] == 3`）—— 一节点一调用的形状**结构上不可能**触发这个缺陷。
端点注释里那句"实测 19 条真实任务的偏差落在 0 … 4.3e-7，全部在此容差内"在本树今天
跑不出同样的结论：上面三条**多步**任务全部 `all_equal=false`、差额是 1.6e-2 元量级，
比容差大四个数量级。要么那 19 条里没有多步形状，要么当时 `traces` 侧还是全量累加。
**关闭条件**：① 加一条"executor 两步以上"的真实形状样本进 `_REAL_RUNS`（或直接用
Mock 造两条 `llm_call` 的节点），让 T1 先红一次；② 再二选一改口 —— 要么 `tasks.cost`
改成累加全部 `llm_call`（对，但历史行仍是末次口径，得迁移或标注），要么承认它就是
"节点级末次"、把字段改名并让成本面板顶部读事件侧。两条互斥，归后端账，等他拍板。

**影响**：同屏两个数 —— 按角色那张表读事件侧（全的），任务列表与 `tasks.cost` 读节点侧（少的）。
别把 `tasks.cost` 当账单，也别拿它做预算闸。

---

## 一句话版本（给只读三行的人）

默认免鉴权且前端带不了 token（A-1/A-2）、`/health?deep=true` 能白烧额度（A-3）、
上传与沙箱都没有第二道资源闸（A-4/A-5）、控制台比旧版少了看板/服务端分页/token 输入/检索测试
（B-1…B-4）、评测里的 p 值与 nDCG 表都是历史口径且头号结论本机不可复跑（C-1…C-3）、
可观测性只做到服务端一半（D-1…D-5）、依赖无 lock（E-1）、语料许可没进 LICENSE（F-1）、
门禁对测试代码是半盲区、版本号有两个手写位且没人检查它、CI 只管测试不管 ruff/mypy/tsc（G-1/G-2/G-5/G-6）、
SSE 那条流名为"从头订阅"其实不补发历史帧，丢了多少也没有计数器出口（G-7）、
轨迹页「总耗时」把节点 span 与单步加了两遍而 `tasks.cost` 只记每个节点最后一次调用（H-1/H-2）。
