import type {
  AblationReportEnvelope,
  AgentOptionsResponse,
  CostBreakdown,
  DocumentDeleteAck,
  DocumentListResponse,
  DocumentRetryAck,
  DocumentUploadAck,
  DocumentView,
  KnowledgeOverview,
  LogEvent,
  ModelKeyAck,
  ModelKeyProbeView,
  ModelListResponse,
  ModelOverrideAck,
  RetrievalReportEnvelope,
  TaskDetail,
  TaskListResponse,
  TaskPhase,
  TaskRecord,
  TaskRunConfig,
  TaskStatus,
  TaskSubmitAck,
  TaskSubmitForm,
  ToolSpecView,
  TraceEvent,
  TraceEventRaw,
  TraceResponse,
  TraceResponseRaw,
} from '../types';
import { STATUS_LABELS } from '../types';
import { mockRecord, startMockStream } from '../mock/taskMock';
import { jsonToText } from '../utils/format';
import type { LiveDelta, LiveUsageDelta } from '../utils/liveAnswer';

/** 后端接口客户端（**已切到真实后端**）。

 * 开关：`USE_MOCK = true` 时全部走 src/mock/，不依赖后端。
 * 联调/演示期改成 false 即可，页面代码不用动。
 *
 * 真实接口口径（与 api/routes/*.py 一一对应，2026-09-21 实测）：
 *   POST /tasks                     → 201 + task_id / stream_url / poll_url
 *   GET  /tasks/{id}/stream         → SSE 节点增量（主路径）
 *   GET  /tasks/{id}/events         → SSE 同一生成器的别名
 *   GET  /tasks/{id}                → 任务详情（终态含 final_answer/cost）
 *   GET  /tasks?limit&offset        → 任务列表
 *   GET  /tasks/{id}/trace          → 轨迹游标分页（event_seq，禁 OFFSET）
 *   GET  /tasks/{id}/cost-breakdown → 成本归因（按 角色×模型×峰谷系数 聚合，全量口径）
 *   GET  /tools                     → 工具规格（收敛后 3 个）
 *   GET  /knowledge/overview        → 语料规模 + 单文件上限（max_file_mb，K3）
 *   GET  /knowledge/documents       → 文档列表（后端按创建时间倒序）
 *   GET  /knowledge/documents/{id}  → 单文档详情（索引进度轮询就读它）
 *   POST /knowledge/documents       → 上传（multipart，201 = 已受理排队，非索引完成）
 *   DELETE /knowledge/documents/{id}→ 物理删（chunk + 向量 + 记录 + 磁盘原件）
 *   POST /knowledge/documents/{id}/retry → 重试 failed（回 pending 全量重跑）
 *   GET  /eval/retrieval-report     → 最近一次检索评测报告（只读透传）
 *   POST /tasks/{id}/cancel         → 取消（节点边界生效）
 */
export const USE_MOCK = false;

/** 后端真实地址（vite define 注入，来源是 vite.config.ts 的代理目标）。
 *  顶栏「数据源」标识读它 —— 修掉此前「代理打 8001、页头写 8000」的口径不一致。
 */
export const API_TARGET: string = typeof __API_TARGET__ === 'string' ? __API_TARGET__ : '127.0.0.1:8000';

/** 只给展示用的精简地址（去掉协议）。 */
export const API_LABEL = API_TARGET.replace(/^https?:\/\//, '');

/** GET /health 的响应（口径见 api/routes/health.py 模块 docstring）。 */
export interface HealthView {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  uptime_seconds: number;
  checks: Record<string, { status: string; detail: string }>;
}

const API_BASE = '/api';
/** SSE 走 /sse 前缀（vite proxy 剥前缀后转发到后端），可用 /events 或 /stream */
const SSE_PATH: 'events' | 'stream' = 'events';

/** 取数失败的错误，带"能让用户自证"的三件东西。
 *
 *  为什么单独一个类（F-1）：以前 ``getJson`` 把 body 的 message 摊成普通 ``Error``，
 *  HTTP 状态码、``code``、``request_id`` 全丢。于是"后端 500"、"404 路由不存在"、
 *  "后端根本没起"、"这份报告真的还没跑过"在页面上长得**一模一样**，
 *  而页面还给出一句"跑一次评测即可生成 + CLI 命令" —— 后端明明活着，却被支去跑 CLI。
 *  ``request_id`` 后端一直都给了（``api/errors.py`` 的统一信封），是我们自己扔掉的；
 *  留着它用户才能去日志里对上那一次请求。
 *
 *  网络层失败（fetch 自己抛 ``TypeError``）拿不到状态码，所以这里的 ``httpStatus``
 *  用 0 表示"请求没送达"，界面必须和"送达了但失败"分开说。
 */
export class ApiFetchError extends Error {
  constructor(
    message: string,
    readonly httpStatus: number,
    readonly code: string,
    readonly requestId: string,
    /** 429 时后端 ``Retry-After`` 给的秒数；没给就是 0（表示"没有服务端指示"，
     *  不等于"零退避"—— 调用方自己要有一个兜底节奏，但**不许拿兜底值冒充服务端说的**）。
     *  这个字段是为知识库上传的 429（队列已满）加的：后端确实在 header 里回了 5，
     *  以前 ``getJson`` 只读 body，那个数就被扔了，前端只能自己猜一个退避时间。 */
    readonly retryAfterSeconds = 0,
  ) {
    super(message);
    this.name = 'ApiFetchError';
  }

  /** 请求根本没送达（后端没起 / 断网 / CORS），区别于"送达了但返回错误"。 */
  get notDelivered(): boolean {
    return this.httpStatus === 0;
  }
}

/** 从 React Query 的 ``error`` 里取出可展示的三件套；不是 ``ApiFetchError`` 一律按未送达处理。 */
export function describeFetchError(err: unknown): ApiFetchError {
  if (err instanceof ApiFetchError) return err;
  return new ApiFetchError(err instanceof Error ? err.message : String(err), 0, 'network_error', '');
}

/** 非 2xx 响应 → :class:`ApiFetchError`。
 *
 * 单独抽出来是因为上传那条路**不能**走 `getJson`（它只吃 JSON body 的读法，
 * 而且丢 header）：429 的退避秒数在 ``Retry-After`` 里。两边共用一份
 * "信封怎么摊平"的判断，才不会有一天 message 的取法在两处漂移。
 * 信封形状见 ``api/errors.py``：``{detail: {code, message, request_id}}``，
 * 老写法（``detail`` 直接是字符串）也要能吃住。
 */
async function toApiError(res: Response): Promise<ApiFetchError> {
  const detail = await res.json().catch(() => null);
  const envelope = detail?.detail ?? {};
  const message = envelope.message ?? detail?.detail ?? `请求失败：HTTP ${res.status}`;
  return new ApiFetchError(
    typeof message === 'string' ? message : JSON.stringify(message),
    res.status,
    envelope.code ?? `http_${res.status}`,
    envelope.request_id ?? '',
    Number(res.headers.get('retry-after')) || 0,
  );
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    // fetch 只有在"请求没发出去"时才抛（后端没起 / 断网 / 被拦），没有响应可言
    throw new ApiFetchError(
      err instanceof Error ? err.message : '请求未能发出',
      0,
      'network_error',
      '',
    );
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

/** ``GET /config/agent-options``：运行配置这一屏的唯一数据来源。
 *
 * 默认值、边界、三档预设、"哪些字段后端还不吃"全在这里。前端**一处都不写死** ——
 * 原来那个"最大迭代轮数 3"在界面上写了四处，而后端默认是 5，两份口径里说谎的是界面那份。
 *
 * ⚠️ 拉不到就整块降级（调用方判 ``isError``），**不要**回落到一份本地默认值：
 * 那等于把"前端替后端决定默认值"这个病灶重新养回来（方案 §2 规矩 3）。 */
export async function fetchAgentOptions(): Promise<AgentOptionsResponse> {
  return getJson<AgentOptionsResponse>('/config/agent-options');
}

/** 把运行配置摊平成请求体：``undefined`` 的键**不发**。
 *
 * 为什么不是 ``?? 默认值``：缺席表示"用户没表达意见"，后端会按自己的默认跑；
 * 发一个数出去表示"用户要这个数"。两者混成一份 ⇒ 降级那一档界面照样发出去一个
 * 前端造的 3，而后端以为是用户选的（P-8）。 */
export function runConfigToBody(config: TaskRunConfig): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (value !== undefined) body[key] = value;
  }
  return body;
}

export async function submitTask(form: TaskSubmitForm): Promise<TaskRecord> {
  if (USE_MOCK) return mockRecord(form);

  const ack = await getJson<TaskSubmitAck>('/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task: form.task,
      ...runConfigToBody(form.config),
      /* 这里原来是一句写死的 ``enabled_tools: form.useRag ? undefined : ['calculator','code_exec']``：
         前端自己抄了一份工具名单，还用"精确白名单"去模拟一个布尔开关 —— 而 ``enabled_tools``
         的优先级高于 ``use_tools``，所以那一行**同时决定了每条任务的工具集合**，
         不只是"关掉 RAG"。现在白名单由 useRunConfig 从 GET /tools 的真实清单算出来，
         没改过勾选就一个键都不发（= 后端全量）。 */
    }),
  });
  return {
    taskId: ack.task_id,
    task: form.task,
    status: (ack.status as TaskStatus) ?? 'queued',
    createdAt: Date.parse(ack.submitted_at) || Date.now(),
    // 回执原样带出去：界面要说"服务端收下了什么"，不能引用自己发出去的那份。
    runConfig: ack.run_config ?? null,
  };
}

/** SSE 的传输层状态。**只有"断了 / 恢复了 / 放弃重连"这三件事**，不是任务状态。
 *
 *  为什么单独一类：以前终态帧和 `onerror` 走同一条路（都 `close(); onDone()`），
 *  于是后端重启一下，前端就以为任务结束了。而**反过来也不对**：断流时任务其实还在跑，
 *  徽标会一直停在「运行中」+「实时推送中」跳动，再也不会重订 —— 用户读到的是"卡住"。
 *  这一类回调就是为了把"连接怎么样"和"任务怎么样"分开说。 */
export type StreamState = 'lost' | 'restored' | 'failed';

/** 断线重连的退避表。三次封顶是刻意的：再多重连风暴会打后端，而内网环境里
 *  三次都接不上基本就是后端真停了 —— 那时要的是**一句人话**，不是继续静默重试。 */
const SSE_BACKOFF_MS = [1000, 3000, 9000] as const;

/** 解析一帧 SSE 的 `data:`；不是 JSON 或解析失败时返回 `null`。
 *
 *  抽出来是因为现在有四处要它（原 `handle` 一处 + `delta` / `usage` 两处新帧），
 *  而"解析失败就当没收到"这条纪律必须在四处一致 —— 增量帧坏了一帧最多少显示
 *  几个字，要是哪一处的 try 漏了，整个订阅会在一帧坏 JSON 上抛异常并断流。 */
function parseJson(raw: unknown): Record<string, unknown> | null {
  if (typeof raw !== 'string') return null;
  try {
    const value = JSON.parse(raw) as unknown;
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** 订阅任务 SSE。返回取消订阅函数（组件卸载时必须调用，否则连接泄漏）。
 *
 * 后端帧格式是**具名事件**（`event: node` / `snapshot` / `done` …），
 * 所以必须 addEventListener 逐个注册；`onmessage` 收不到具名事件。
 *
 * @param onPhase 任务阶段回调。**这是「运行中状态」的唯一真实来源**：
 *   SSE 的具名事件本身就带语义（心跳/节点更新 = 在跑，done/failed/canceled = 终态），
 *   以前只拿它拼日志、没更新任务状态，导致状态条会一直停在提交时的「排队中」。
 * @param onStreamState 传输层断/恢复的回调。**不要**在这里改任务状态 ——
 *   它只说明连接，任务是否还在跑由调用方补拉详情去确定。
 * @param onDelta 答案增量（`delta` 帧）。**append 语义**：`reset` 为真时替换、
 *   否则拼在已有文本后面。这是"结果流式输出"的那一半 —— 没有它，屏上那十几秒
 *   只有一行阶段文案在动。
 * @param onUsage 用量增量（`usage` 帧）。一次 LLM 调用一笔，由调用方累加。
 *   ⚠️ 与 `delta` 一样是**运行中的过程量**：终态一律以详情回执为准。
 *
 * ⚠️ 重连**不依赖** `Last-Event-ID`：后端 SSE 路由根本不读那个头。帧的 `id:`
 *    自 2026-10-02（Q6-10）起只有一个发号者 —— worker 的任务级计数器，一条任务内
 *    严格递增，连接本地的合成帧（`snapshot` / `heartbeat`）干脆不带 `id:`；
 *    但它**每条任务都从 1 起**，跨任务、跨连接仍不可比 ⇒ 交给浏览器自动重连只会
 *    **静默丢事件**。所以这里自己退避重连，并在恢复后回一次 `restored`，
 *    由调用方按 `event_seq` 从 `/trace` 补拉对账。
 */
export function subscribeTaskStream(
  taskId: string,
  onEvent: (event: LogEvent) => void,
  onDone: () => void,
  onPhase?: (phase: TaskPhase) => void,
  onStreamState?: (state: StreamState) => void,
  onDelta?: (delta: LiveDelta) => void,
  onUsage?: (usage: LiveUsageDelta) => void,
): () => void {
  if (USE_MOCK) return startMockStream(onEvent, onDone, onPhase);

  /* 记账跨连接保留：重连后后端的 `seq` 会从 1 重新开始（每连接独立计数），
     如果 maxSeq 跟着连接走，日志行 key 就会撞车 —— React 抛 duplicate key 并可能丢行。
     所以它在循环**外面**，且只增不减；代价是重连后显示的序号是客户端单调值而非服务端真值
     （这个取舍本来就在，见下面 seq 那行注释）。 */
  let maxSeq = 0;
  let source: EventSource | null = null;
  let timer = 0;
  let attempt = 0;
  /** 我们主动关的（终态 / 卸载）就不再重连 —— 否则任务跑完会凭空多挂三条重试连接。 */
  let disposed = false;
  /** 断开后重连上的第一件事：让调用方去对账（补拉 trace），因为断口那几帧永远不会重发。 */
  let needsReconcile = false;

  const handle = (level: LogEvent['level']) => (evt: MessageEvent) => {
    const payload = parseJson(evt.data);
    if (!payload) return; // 心跳/非 JSON 帧直接忽略
    const node = payload.node as string | undefined;
    const update = (payload.update ?? {}) as Record<string, unknown>;
    const rawSeq = Number(payload.seq ?? 0);
    // 后端给了更大的 seq 就跟随；缺失或回退时用本地递增，绝不产生重复值
    const seq = rawSeq > maxSeq ? (maxSeq = rawSeq) : ++maxSeq;
    /* running_ms 只在心跳帧上（api/routes/tasks.py 的 generate()）：它是「这次订阅
       之后过了多久」，是服务端真值，比前端自己数秒更可信。文案刻意写成**恒定**一句
       —— 数字放进 idleMs 交给展示层，这样连续心跳能被合并成一行原地刷新
       （见 utils/logRows.ts）；把秒数拼进 message 会让每帧都成为「新行」，合不上。
       ⚠️ 重连之后它读的是"新连接起算的时长"，不是任务总时长 —— 任务总时长看运行条。 */
    const rawIdle = Number(payload.running_ms);
    const idleMs = Number.isFinite(rawIdle) && rawIdle >= 0 ? rawIdle : undefined;
    onEvent({
      seq,
      ts: payload.ts ? Date.parse(String(payload.ts)) || Date.now() : Date.now(),
      level,
      node: (node ?? 'system') as LogEvent['node'],
      message: idleMs === undefined ? describeUpdate(node, update, payload) : '等待节点事件',
      idleMs,
    });
  };

  const connect = () => {
    if (disposed) return;
    source = new EventSource(
      `${API_BASE}/tasks/${taskId}/${SSE_PATH}`.replace('/api', '/sse'),
    );
    const es = source;

    es.addEventListener('snapshot', handle('info'));
    es.addEventListener('node', handle('info'));
    es.addEventListener('heartbeat', handle('debug'));
    es.addEventListener('done', handle('info'));
    es.addEventListener('failed', handle('error'));
    es.addEventListener('canceled', handle('warn'));

    /* 答案增量与用量增量：**不进日志缓冲**。
       ① 它们是"内容"不是"事件" —— 写进日志面板会把一句完整的话拆成几百行，
          而日志的价值恰恰是"按时间线看清发生了什么"；
       ② 频率高（80ms 一批），进 useLogBuffer 会顶掉 5000 条的封顶预算；
       ③ 读屏不该把答案逐帧念一遍（结果屏那一行 `aria-live` 已经负责播报状态）。
       ⚠️ 帧名必须与 `api/constants.py` 的 EVT_DELTA / EVT_USAGE 逐字一致。 */
    if (onDelta) {
      es.addEventListener('delta', (evt: MessageEvent) => {
        const payload = parseJson(evt.data);
        if (!payload) return;
        onDelta({
          text: String(payload.text ?? ''),
          node: String(payload.node ?? ''),
          reset: payload.reset === true,
        });
      });
    }
    if (onUsage) {
      es.addEventListener('usage', (evt: MessageEvent) => {
        const payload = parseJson(evt.data);
        if (!payload) return;
        onUsage({
          node: String(payload.node ?? ''),
          tokens_in: Number(payload.tokens_in ?? 0),
          tokens_out: Number(payload.tokens_out ?? 0),
          cost: Number(payload.cost ?? 0),
        });
      });
    }

    // 任何「活着」的帧（快照 / 节点更新 / 心跳）都说明任务已经离开排队、正在执行
    for (const live of ['snapshot', 'node', 'heartbeat'] as const) {
      es.addEventListener(live, () => {
        /* 收到第一帧才算真的接上了：连接成功但没有帧，说明对端可能已经换了进程。 */
        if (needsReconcile) {
          needsReconcile = false;
          attempt = 0;
          onStreamState?.('restored');
        }
        onPhase?.('running');
      });
    }

    // 终态三种都关流：交给调用方去拉详情，避免流关闭早于详情落库
    for (const terminal of ['done', 'failed', 'canceled'] as const) {
      es.addEventListener(terminal, () => {
        disposed = true; // 正常收口，不是断流 —— 绝不能再走一遍重连
        es.close();
        onPhase?.(terminal);
        onDone();
      });
    }

    /* 传输层出错 ≠ 任务终态。这里**不**调 onDone（那是"任务结束了"的意思），
       而是关流后自己按退避表重连；三次都接不上才认输，并如实交给调用方去说。
       为什么不用浏览器自带的自动重连：它的游标（Last-Event-ID）在这个后端是坏的
       —— 见函数头那条 ⚠️ —— 靠它会把断口那几帧静默吞掉。 */
    es.onerror = () => {
      if (disposed) return;
      es.close();
      if (attempt >= SSE_BACKOFF_MS.length) {
        disposed = true; // 认输：不再无限重试打后端
        onStreamState?.('failed');
        return;
      }
      const wait = SSE_BACKOFF_MS[attempt];
      attempt += 1;
      needsReconcile = true;
      onStreamState?.('lost');
      timer = window.setTimeout(connect, wait);
    };
  };

  connect();

  return () => {
    disposed = true;
    window.clearTimeout(timer);
    source?.close();
  };
}

/** 把 SSE 的 update 载荷压成一行可读日志（只做展示，不反序列化后重算）。 */
function describeUpdate(
  node: string | undefined,
  update: Record<string, unknown>,
  payload: Record<string, unknown>,
): string {
  if (node === 'planner') {
    const plan = update.plan as string[] | undefined;
    return plan?.length ? `规划 ${plan.length} 步：${plan[0]}` : '规划中…';
  }
  if (node === 'executor') {
    const results = update.execution_results as
      | Array<{ step_index?: number; subtask?: string; status?: string; output?: string }>
      | undefined;
    if (results?.length) {
      const r = results[0];
      const out = (r.output ?? '').replace(/\s+/g, ' ').slice(0, 120);
      return `步骤 ${(r.step_index ?? 0) + 1}：${(r.subtask ?? '').slice(0, 40)} → ${out}`;
    }
    return '执行中…';
  }
  if (node === 'reviewer') {
    return update.review_result === true
      ? `复核通过（评分 ${update.review_score ?? '-'}）`
      : `复核未通过（评分 ${update.review_score ?? '-'}）`;
  }
  /* 任务级帧（snapshot / done / canceled）只有 status。这里必须翻成人话：
     以前直接把后端的 'running' 原样丢进日志，于是同一屏里既有中文节点行
     又有一行英文 'running'，而它正是被合并成状态行的那一句。 */
  const raw = String(payload.status ?? update.status ?? 'running');
  return STATUS_LABELS[raw as TaskStatus] ?? raw;
}

export async function fetchTask(taskId: string): Promise<TaskDetail> {
  return getJson<TaskDetail>(`/tasks/${taskId}`);
}

export async function fetchTaskList(limit = 20): Promise<TaskListResponse> {
  return getJson<TaskListResponse>(`/tasks?limit=${limit}`);
}

/** 轨迹边界归一：`arguments` 线上是 object（§6.2），渲染层要的是文本。
 *
 *  这是唯一的收口点，两个消费方都从这里拿：TaskLogPage 的「工具调用」页签
 *  （`buildToolCalls` → `<pre>{t.args}`）与 StepTimeline（`<pre>{e.arguments}`）。
 *  在各渲染点补 typeof 守卫会漏 —— 曾按「某个 `<pre>` 加守卫」修过一次，
 *  同一字段另一页仍然白屏。
 */
function normalizeTraceEvent(e: TraceEventRaw): TraceEvent {
  return { ...e, arguments: jsonToText(e.arguments) || null };
}

/** 轨迹游标分页：一页拉不满就继续拉下一页（后端 next_after_seq 驱动）。 */
export async function fetchTrace(taskId: string, maxPages = 10): Promise<TraceResponse> {
  let after = 0;
  let merged: TraceResponseRaw | null = null;
  for (let page = 0; page < maxPages; page += 1) {
    const pageData = await getJson<TraceResponseRaw>(`/tasks/${taskId}/trace?after_seq=${after}&limit=50`);
    merged = merged
      ? { ...pageData, items: [...merged.items, ...pageData.items] }
      : pageData;
    if (!pageData.has_more || pageData.next_after_seq == null) break;
    after = pageData.next_after_seq;
  }
  const body: TraceResponseRaw = merged ?? { items: [], total: 0, limit: 50, after_seq: 0, next_after_seq: null, has_more: false, events_available: false, unavailable_reason: null };
  return { ...body, items: body.items.map(normalizeTraceEvent) };
}

/** 成本归因（面板的**合计与分组**唯一真源）。
 *
 *  为什么不复用 `fetchTrace` 的明细去前端加总（方案 §0 理由 2、§5.3）：
 *  上面那个 `maxPages = 10 × limit = 50` 把明细封顶在 500 条事件，
 *  超封顶的任务前端加出来的 token 与钱会**静默偏小** —— 属于「不报错只算错」那一类，
 *  而成本面板的全部价值就是数字可信。本函数一次拿全（后端 `GROUP BY`，与总量解耦）。
 *
 *  ⚠️ 也因此：明细列表（页面上的逐次调用）仍走 `fetchTrace`，两边的条数**可以不同**；
 *  合计只认这里的 `totals`。
 */
export async function fetchCostBreakdown(taskId: string): Promise<CostBreakdown> {
  return getJson<CostBreakdown>(`/tasks/${taskId}/cost-breakdown`);
}

export async function fetchTools(): Promise<ToolSpecView[]> {
  const body = await getJson<{ items: ToolSpecView[]; total: number }>('/tools');
  return body.items;
}

/** ``GET /models``：本次部署实际调用的模型注册表（含单价、候选清单与生效来源）。
 *
 * mock 模式返回**空清单**而不是编一份模型表 —— 空清单让页面把那一行整条不渲染，
 * 编的清单会让人以为后端真有那么两个档。``catalog`` 同理给空数组：
 * 设置面板读到"候选 0 条"会改口说"这一趟没读到"，比拿一份假清单去渲染下拉安全。
 */
export async function fetchModels(): Promise<ModelListResponse> {
  if (USE_MOCK) {
    return {
      items: [], total: 0, role_map: {},
      default_model: '', pricing_basis: '', off_peak_multiplier: 1,
      catalog: [], providers: [],
    };
  }
  return getJson<ModelListResponse>('/models');
}

/** ``POST /models/override``：把两个档位换成候选里的模型（只活到后端重启）。
 *
 * 请求体里**没有 Key 的位置** —— 这一条到 2026-09-27 仍然成立，但含义变了：
 * Key 有了自己的端点（:func:`postModelKey`），换模型这一趟只管两个档位。
 * 422 时 ``getJson`` 摊出 :class:`ApiFetchError`，``code=invalid_request`` +
 * 服务端原话（"这几家还没有配 API Key：智谱 GLM（环境变量 LLM_API_KEY_ZHIPU）"），
 * 调用方直接把那句话显示出来，不自己重写一遍 —— 哪家缺 Key 只有后端知道。
 */
export async function applyModelOverride(
  body: { model_large: string; model_small: string },
): Promise<ModelOverrideAck> {
  if (USE_MOCK) throw new ApiFetchError('mock 模式没有后端，换模型不生效', 0, 'mock_mode', '');
  return getJson<ModelOverrideAck>('/models/override', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** ``DELETE /models/override``：撤掉覆盖，回落到 .env 的那两个档位（幂等）。
 *
 * ⚠️ 它**不清 Key** —— 两个覆盖层各自独立（后端 ``delete_override`` 的 docstring 同义）。
 * 撤 Key 走 :func:`postModelKey` 传空串。 */
export async function resetModelOverride(): Promise<ModelOverrideAck> {
  if (USE_MOCK) throw new ApiFetchError('mock 模式没有后端，换模型不生效', 0, 'mock_mode', '');
  return getJson<ModelOverrideAck>('/models/override', { method: 'DELETE' });
}

/** 两个 Key 端点共用的发法：值**只在 POST body 里**，路径是常量。
 *
 * 为什么写成一个小函数而不是两处 ``fetch``：这条链上唯一真正要防的事是
 * "那串值以某种形式出现在 URL / query 里"（浏览器历史、访问日志、DevTools 的
 * Network 列表都会长期留着它），而"两处各写一遍 fetch"正是有一天写歪的形状。
 * 于是这里放一道自证：拼完 URL 再 grep 一次，串了就把这趟请求掐掉 ——
 * 宁可界面上报错，也不让 Key 上一条会被记住的通道。
 */
function postKeyJson<T>(path: string, body: { provider: string; api_key: string }): Promise<T> {
  const url = `${API_BASE}${path}`;
  /* ⚠️ 空串必须**跳过**这道自证：``url.includes('')`` 恒为真，照原样写会把"撤回那把 Key"
     （= 传空串）这条合法路径在客户端掐掉，报出来的还是一句谎话"Key 出现在 URL 里"。
     AE-8e 量的就是这一条 —— 探针第一版就在这里红。 */
  if (body.api_key !== '' && url.includes(body.api_key)) {
    return Promise.reject(
      new ApiFetchError('内部检查失败：Key 出现在 URL 里，已中止请求', 0, 'client_guard', ''),
    );
  }
  return getJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** ``POST /models/key``：把某家的 Key 放进**本次进程**（不落盘、重启回落到 .env）。
 *
 * 传空串 = 撤回这一家面板填的那把。响应是整份 ``GET /models`` 状态，
 * 里面没有任何字段装得下那串值（连掩码都没有）。 */
export async function postModelKey(provider: string, apiKey: string): Promise<ModelKeyAck> {
  if (USE_MOCK) throw new ApiFetchError('mock 模式没有后端，填 Key 不生效', 0, 'mock_mode', '');
  return postKeyJson<ModelKeyAck>('/models/key', { provider, api_key: apiKey });
}

/** ``POST /models/key/validate``：拿这把 Key 问一次 ``GET {base_url}/models``（零 token）。
 *
 * 超时在后端（``timeout_s`` 随响应回来，界面那句"3 秒"读它，不写死）。
 * Base URL **不是前端给的** —— 前端只能报供应商名，端点由后端按注册表算，
 * 否则这个端点就成了"带着别人的 Key 往任意地址发请求"的探针。 */
export async function validateModelKey(provider: string, apiKey: string): Promise<ModelKeyProbeView> {
  if (USE_MOCK) throw new ApiFetchError('mock 模式没有后端，校验不了 Key', 0, 'mock_mode', '');
  return postKeyJson<ModelKeyProbeView>('/models/key/validate', { provider, api_key: apiKey });
}

export async function fetchKnowledgeOverview(): Promise<KnowledgeOverview> {
  return getJson<KnowledgeOverview>('/knowledge/overview');
}

/** 文档列表（后端按创建时间倒序排好，前端不再排）。 */
export async function fetchDocuments(): Promise<DocumentListResponse> {
  return getJson<DocumentListResponse>('/knowledge/documents');
}

/** 单文档详情 —— **索引进度的唯一读数来源**。
 *
 * 进度只能轮询这个端点读 `status`，不许在前端按"过了几秒"猜阶段：
 * 解析/切分/向量化三步的真实耗时差一个数量级（几毫秒到十几秒），
 * 猜出来的条子只会是一种东西 —— 假的（方案 §6 避坑 2 同一条）。
 */
export async function fetchDocument(documentId: string): Promise<DocumentView> {
  return getJson<DocumentView>(`/knowledge/documents/${documentId}`);
}

/** 上传一份文档：201 = **已受理并排队**，不等于索引完成（回执里 `status` 恒为 `pending`）。
 *
 * 三件事必须写在这里，因为它们是"看着能跑、其实在埋雷"的那种：
 *
 * 1. **绝不手写 `Content-Type`**（方案 §6 避坑 1，已升格为 Z 趟的验收断言）：
 *    抄 `submitTask` 那行 `headers: {'Content-Type': 'application/json'}` 会连
 *    boundary 一起丢掉 ⇒ 后端 422，而那句报错看起来像"文件格式不支持"。
 *    交浏览器自己带 `multipart/form-data; boundary=…`，我们不碰 header。
 * 2. **一次只传一份**（避坑 3）：后端 `file.file.read()` 是把整份文件一次读进内存
 *    （`api/routes/knowledge.py:117`），上限 50 MB × 并发 = 内存尖峰；索引队列容量
 *    也只有 20（`config.py:216`）。所以批量是**串行队列**，不是 `Promise.all`。
 *    下一个人想加并发，请先让后端改成流式落盘。
 * 3. **不走 `getJson`**：429（队列已满）的退避秒数在 `Retry-After` header 里，
 *    `getJson` 只读 body 会把它扔掉。这里用同一份 `toApiError` 摊平信封，
 *    额外带上退避指示。
 */
export async function uploadDocument(
  file: File,
  opts: { overwrite?: boolean } = {},
): Promise<DocumentUploadAck> {
  const form = new FormData();
  // 第三个参数显式给文件名：File 对象来自拖拽时 name 也在，但某些裁剪工具会造出
  // 匿名 File（name 空串），那时后端会落成 "unnamed"，用户在列表里认不出是哪份。
  form.append('file', file, file.name || 'unnamed');
  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/knowledge/documents${opts.overwrite ? '?overwrite=true' : ''}`,
      { method: 'POST', body: form },
    );
  } catch (err) {
    throw new ApiFetchError(
      err instanceof Error ? err.message : '上传请求未能发出',
      0,
      'network_error',
      '',
    );
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as DocumentUploadAck;
}

/** 删除文档（物理删：chunk + 向量 + 记录，KB-01 修完还含磁盘原件）⇒ 调用方必须先二次确认。 */
export async function deleteDocument(documentId: string): Promise<DocumentDeleteAck> {
  return getJson<DocumentDeleteAck>(`/knowledge/documents/${documentId}`, { method: 'DELETE' });
}

/** 重试失败文档：后端 `failed → pending` 重新入队，从解析全量重跑（没有阶段断点）。
 *
 * 只有 `failed` 能重试；对别的状态后端会报错，所以按钮**只在 failed 行出现**，
 * 而不是"先给了再让用户点了吃一个错"。
 */
export async function retryDocument(documentId: string): Promise<DocumentRetryAck> {
  return getJson<DocumentRetryAck>(`/knowledge/documents/${documentId}/retry`, { method: 'POST' });
}

/** 只读透传：报告不存在时后端给 available=false，前端必须显示「待测」。 */
export async function fetchRetrievalReport(): Promise<RetrievalReportEnvelope> {
  return getJson<RetrievalReportEnvelope>('/eval/retrieval-report');
}

/** 只读透传：消融报表 + 服务端算好的 F1/F2 归因计数。 */
export async function fetchAblationReport(): Promise<AblationReportEnvelope> {
  return getJson<AblationReportEnvelope>('/eval/ablation-report');
}

/** ``POST /tasks/{id}/cancel`` 的 200 响应（字段口径见 ``api/schemas.py`` 的 ``CancelResponse``）。 */
export interface CancelAck {
  taskId: string;
  status: 'canceled';
  /** queued_dropped = 排队期直接丢弃（零 LLM 调用）；node_boundary = 等当前节点返回才停 */
  mode: 'queued_dropped' | 'node_boundary';
  /** 后端给的限制说明（L1：取消点之后的结果会被丢弃，但已经花掉的不退） */
  note: string;
}

/** 取消被后端拒绝。带上机器可读的错误码，调用方就不必去正则匹配中文文案。 */
export class CancelTaskError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'CancelTaskError';
  }
}

/** 后端在 ``detail.code`` 里给的「这条任务已经不是活着的任务」两类码。
 *  路由级 404 用通用码 ``not_found``（见 ``api/errors.py`` 的说明），所以一并认。 */
const CANCEL_REJECT_CODES = new Set(['task_already_finished', 'task_not_found', 'not_found']);

/**
 * 取消一条任务。**必须判 HTTP 状态**：上一版是 ``await fetch(...)`` 一把梭，
 * 200 / 409（已是终态）/ 404（不存在）/ 5xx 在前端是同一个"成功"，于是
 * 徽标被本地改成「已取消」而任务其实还在跑 —— 界面不报错，只是假话。
 *
 * 不走 ``getJson``：它把 body 的 message 摊平成一个普通 ``Error``，错误码就丢了，
 * 而调用方要按码区分"没能送达"与"这条已经结束"（两者的文案是反的）。
 * body 信封是 ``{detail: {code, message, request_id}}``（``api/errors.py`` 的统一契约）。
 *
 * ⚠️ 200 只代表"取消位已置、DB 已改成 canceled"。``mode === 'node_boundary'`` 时
 * worker 仍在把当前节点跑完，之后的结果被丢弃 —— 调用方不许把它读成"已经停下"。
 */
export async function cancelTask(taskId: string): Promise<CancelAck> {
  if (USE_MOCK) {
    return { taskId, status: 'canceled', mode: 'node_boundary', note: '' };
  }
  const res = await fetch(`${API_BASE}/tasks/${taskId}/cancel`, { method: 'POST' });
  const body = (await res.json().catch(() => null)) as {
    task_id?: string;
    status?: 'canceled';
    mode?: 'queued_dropped' | 'node_boundary';
    note?: string;
    detail?: { code?: string; message?: string };
  } | null;
  if (!res.ok) {
    throw new CancelTaskError(
      body?.detail?.message || `取消请求失败：HTTP ${res.status}`,
      body?.detail?.code || `http_${res.status}`,
      res.status,
    );
  }
  return {
    taskId: body?.task_id ?? taskId,
    status: 'canceled',
    mode: body?.mode ?? 'node_boundary',
    note: body?.note ?? '',
  };
}

/** 取消被拒时，这句话是"反话"的唯一来源：已经终态/根本不存在 ⇒ 不许再说"可能仍在运行"。 */
export function isCancelRejected(err: unknown): boolean {
  return err instanceof CancelTaskError && CANCEL_REJECT_CODES.has(err.code);
}

/** 健康检查。
 *
 * 注意：`unhealthy` 时后端返回 **503**，但 body 仍是完整的 HealthResponse ——
 * 所以这里不吃 `getJson` 的「非 2xx 就抛」逻辑，直接把 body 读出来交给 UI，
 * 让顶栏能如实显示「服务不健康」而不是「连不上」。
 */
export async function fetchHealth(): Promise<HealthView> {
  const res = await fetch(`${API_BASE}/health`);
  return (await res.json()) as HealthView;
}
