/** 领域类型定义。
 *
 * 口径说明（重要，别改错）：
 *  - TaskStatus 的取值**只来自后端**，见 api/schemas.py 与 ui/pages/__init__.py 的
 *    STATUS_LABELS：queued / running / done / aborted / failed / canceled。
 *    需求描述里写的「超时」在后端**没有独立状态**——迭代耗尽或超时统一落到
 *    `aborted`（强制收口）。所以这里不编一个 timeout 状态，只在展示层把
 *    aborted 标注为「已收口（迭代耗尽/超时）」。
 *  - 工具入参 `arguments` 在**线上是 object**（设计文档 §6.2，后端
 *    `api/schemas.py::TaskEventView` 刻意反序列化成 dict 返回）。前端在
 *    `api/client.ts::fetchTrace` 这个边界上统一字符串化，所以页面读到的
 *    `TraceEvent.arguments` 与 `ToolCall.args` / `result` 恒为 string。
 *    边界不能省：object 进 `<pre>` 会抛「Objects are not valid as a React
 *    child」并白屏（2026-09-23 实测，`code_exec` 的 `{"code": …}` 触发）。
 *    归一之后前端只做展示与折叠，不反序列化后重算。
 */

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'aborted'
  | 'failed'
  | 'canceled';

export type AgentNode = 'planner' | 'executor' | 'reviewer' | 'system';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/** SSE 推送的一条日志。seq 与后端 /tasks/{id}/stream 的 event_seq 对齐。 */
export interface LogEvent {
  seq: number;
  ts: number;
  level: LogLevel;
  node: AgentNode;
  message: string;
  /** 心跳帧专属：后端报的「本次 SSE 订阅后已运行多少毫秒」（api/routes/tasks.py
   *  的 running_ms）。别的帧没有这个字段 —— 它是连接存活时长，不是任务耗时，
   *  所以只在「多久没有新事件」这句话里用，别拿去做耗时口径。 */
  idleMs?: number;
}

/** 一次工具调用。字段对齐 core/tools/registry.py 记录的调用记录。 */
export interface ToolCall {
  id: string;
  name: 'calculator' | 'knowledge_search' | 'code_exec' | string;
  args: string;
  result: string;
  durationMs: number;
  /** 三档都来自后端事件（api/schemas.py:267 的 Literal）：
   *  success / failed / **timeout**。别在映射时把 timeout 折进 success ——
   *  那正是「出参写着执行超时、徽章却是绿色成功」的成因（判定见 utils/toolMeta.ts 的 toolOutcome）。 */
  status: 'success' | 'failed' | 'timeout';
  /** 执行器在调这个工具前记的原因（轨迹里的 thought）。没有就是 null，
   *  工具卡片的意图标题会退回「动词：关键入参」，绝不自己编一句。 */
  thought: string | null;
}

/** 引用溯源：一条命中的 chunk 及其来源文档。 */
export interface Citation {
  chunkId: string;
  document: string;
  score: number;
  snippet: string;
}

export interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

export interface TaskResult {
  finalAnswer: string;
  citations: Citation[];
  toolCalls: ToolCall[];
  usage: TokenUsage;
  durationMs: number;
  iterations: number;
}

/** 提交体里的运行配置。键名与 ``api/schemas.py::TaskSubmitRequest`` 的新字段一一对应。
 *
 * ⚠️ 每个键都是可选的，而**缺席 = 用户没表达意见**，不是 0、也不是"前端觉得应该是几"。
 * 读不到 ``/config/agent-options`` 时前端只发 ``task``：一旦前端替后端补默认值，
 * 就有了第二份口径，而后端那份才是真跑的那份（方案 §2 规矩 3、§4 P-8）。
 * 尤其 ``max_cost_cny: 0`` 与"不设限"是两回事 —— 前者会让任务一步都跑不动。 */
export interface TaskRunConfig {
  max_iterations?: number;
  review_threshold?: number;
  max_cost_cny?: number;
  timeout_s?: number;
  rag_top_k?: number;
  use_tools?: boolean;
  enabled_tools?: string[];
}

/** 服务端**实际收下**的那份（201 回执）。界面显示"这条任务的配置"时读这里。
 *
 * ⚠️ 不读自己刚发出去的那份：请求模型是 ``extra="ignore"``，一台没重启的老后端
 * 会把这些新键静默丢掉 ⇒ 界面上"预算 ¥0.36"照样显示，任务却把钱花光了。
 * 老响应里没有这个字段 ⇒ 整个对象可选（``TaskRecord.runConfig``）。
 *
 * 与请求侧（:type:`TaskRunConfig`）**故意不是同一个类型**：请求用"键缺席"表达
 * "用户没意见"，回执用 ``null`` 表达"服务端没有这一档限制"（``api/schemas.py`` 的
 * ``TaskRunConfigView`` 每个可空字段都是 ``| None``）。把两者合并成一份，
 * 就等于把"没发"与"发了但被当成不设限"混成一个状态 —— 那正是本面板要拆的东西。 */
export interface TaskRunConfigEcho {
  max_iterations: number;
  review_threshold: number;
  max_cost_cny?: number | null;
  timeout_s?: number | null;
  rag_top_k?: number | null;
  use_tools?: boolean | null;
  enabled_tools?: string[] | null;
}

/** 提交表单：只剩任务文本 + 一份运行配置。
 *
 * ⚠️ 原来这里有 ``useTools`` / ``useRag`` / ``maxIterations`` 三个平铺键，值住在
 * AntD ``Form`` store 里，而「运行配置」弹层是**懒挂载**的 ⇒ 用户没点开过就等于字段没注册
 * ⇒ 请求体少键（这个坑踩过两次，见 TaskLogPage 的 composer-foot 注释）。
 * 现在配置的唯一宿主是 :mod:`hooks/useRunConfig` 那个 Context，Form 只管任务文本。
 * 也**没有 ``model`` 字段**：模型按编排角色定档，换档的入口在顶栏齿轮（U-2 拍的那条）。 */
export interface TaskSubmitForm {
  task: string;
  config: TaskRunConfig;
}

/** 一个数值字段的界。⚠️ 由后端给，InputNumber 只渲染不发明（方案 P-3）。 */
export interface AgentNumericLimit {
  min: number;
  max: number;
  step?: number;
}

/** 一个键的"能不能填 / 填了有没有用"。两个布尔各管一件事，不许合并。 */
export interface AgentFieldSpec {
  key: string;
  label: string;
  /** 刻意是 ``string`` 不是联合类型：新 kind 要能原样透出去，不认识就列进「未识别」，
   *  而不是在校验层炸掉或被静默丢掉。 */
  kind: string;
  accepted: boolean;
  enforced: boolean;
  help?: string | null;
  /** 数值键的单位后缀（轮 / 分 / 元 / 秒 / 条），非数值键为 ``null``。
   *
   * ⚠️ 单位是**后端事实**（方案 §2.1 把它放进契约）。界面自己写"轮"就是藏了第二张
   * 字段表 —— 与这一屏刚删掉的那四处 ``3`` 同一个病。缺席时界面**不给后缀**，
   * 不是回落成一个猜出来的字。 */
  unit?: string | null;
}

/** 一档预设。``values`` 是后端给的键→值，前端原样套、不解释语义。 */
export interface AgentPreset {
  id: string;
  label: string;
  values: Record<string, unknown>;
  note?: string | null;
}

/** 某个编排角色这次用哪个模型（只读）。 */
export interface AgentRoleModel {
  role: string;
  tier: string;
  model: string;
  source: string;
}

/** ``GET /config/agent-options``。
 *
 * ⚠️ 所有字段都是可选的：一台没重启的后端会 404，界面必须整块降级而不是崩。
 * 末尾那个索引签名也是故意的 —— 后端将来多给一个顶层键，它得留得住，
 * 才谈得上"原样透出"。 */
export interface AgentOptionsResponse {
  schema_version?: number;
  defaults?: Record<string, number | string | boolean | null>;
  limits?: Record<string, AgentNumericLimit>;
  presets?: AgentPreset[];
  fields?: AgentFieldSpec[];
  models?: {
    editable_here?: boolean;
    entry_point?: string;
    roles?: AgentRoleModel[];
  };
  tools?: {
    source?: string;
    default_enabled?: string[] | null;
    /** 「RAG」快捷开关对应哪个工具名，由后端说。null/缺席 ⇒ 开关置灰，不猜。 */
    rag_tool?: string | null;
  };
  currency?: string;
  pricing_basis?: string;
  [extra: string]: unknown;
}

/** 前端认识的顶层键集合 —— 只为算出「未识别」那一栏，不参与渲染判断。 */
export const AGENT_OPTIONS_KNOWN_KEYS: readonly string[] = [
  'schema_version',
  'defaults',
  'limits',
  'presets',
  'fields',
  'models',
  'tools',
  'currency',
  'pricing_basis',
];

/** 认识的控件类型集合，同样只用来算「未识别的 kind」。 */
export const AGENT_FIELD_KNOWN_KINDS: readonly string[] = [
  'int',
  'money',
  'duration',
  'bool',
  'select',
];

/** 需要"一个数字输入框"的 kind —— 用来发现**后端说能配、界面却没给行**的那一栏。
 *
 * ⚠️ 这不是"前端决定哪些字段能填"：能填的名单是后端的 ``accepted``。这里只回答
 * "一个数字该长成长什么样"。它的唯一用途是反向对账：后端新加一个 accepted 的数值键、
 * 而前端这一版还没有对应的行 ⇒ 与其静默少一栏（下一个人只会以为后端没给），
 * 不如在「后端还给了这些」里点名。 */
export const AGENT_NUMERIC_KINDS: readonly string[] = ['int', 'money', 'duration'];

export interface TaskRecord {
  taskId: string;
  task: string;
  status: TaskStatus;
  createdAt: number;
  progress?: {
    currentNode: AgentNode;
    iteration: number;
    maxIterations: number;
    elapsedMs: number;
  };
  result?: TaskResult;
  error?: { code: string; message: string; httpStatus?: number; requestId?: string | null };
  /** ``POST /tasks`` 的回执：服务端**实际收下**的运行配置（提交那一条才有）。
   *  界面显示"这条任务的预算/超时"读这里，不读自己发出去的那份。 */
  runConfig?: TaskRunConfigEcho | null;
  /** 回执核对的结论（P-1），只在**刚提交的那一条**上存在；切任务即没有（别的记录不带这个字段）。
   *
   * 为什么不只写成一条日志：日志会被随后的整包 trace ``replaceEvents`` 盖掉，
   * 而"你以为设了预算、后端其实没收下"这件事必须在那一秒之后仍然看得见。
   * 存的是**结论行**（已经算好的中文），界面只负责原样显示，不再自己拼第二份口径。 */
  configEchoIssue?: { code: 'RUN_CONFIG_UNACKNOWLEDGED' | 'RUN_CONFIG_MISMATCH'; lines: string[] } | null;
  /** 列表接口的真实统计字段（2026-09-22 实测 /tasks 返回）。
   *
   * ⚠️ 口径提醒：
   *  - `cost` 是**金额（元）**，不是 token 数 —— 后端不返回 token，别当 token 显示。
   *  - 接口**没有 model 字段**，历史任务用了哪个模型无法回溯，不要编。
   *  - 三者都可能是 null（任务未完成 / 后端未落库），展示层必须按「缺值不补」处理。
   */
  cost?: number | null;
  toolCalls?: number | null;
  durationMs?: number | null;
}

/** 任务阶段（由 SSE 具名事件驱动，不是前端猜测）。
 *
 * 为什么需要它：`POST /tasks` 返回时任务还在**排队**，而状态条要等到流关闭、
 * 补拉详情才会更新 —— 中间几十秒会一直显示「排队中」。SSE 的具名事件本身就带
 * 阶段语义（心跳/节点更新 = 在跑），把它单独抽出来，运行状态才有真实来源。
 */
export type TaskPhase = 'running' | 'done' | 'failed' | 'canceled';

/* ------------------------------------------------------------------ *
 * 以下类型**逐字段对齐真实 API 响应**（2026-09-21 实测 FastAPI 8001）
 * ------------------------------------------------------------------ */

/** POST /tasks 的 201 响应。 */
export interface TaskSubmitAck {
  task_id: string;
  status: string;
  stream_url: string;
  poll_url: string;
  cancel_url: string;
  queue_position: number | null;
  submitted_at: string;
  estimated_cost_cny: number | null;
  warnings: string[] | null;
  /** 服务端实际收下的运行配置。⚠️ 界面上"这条任务的预算/超时"读这里，
   *  不读自己发出去的那份（老后端会静默丢掉新键 ⇒ 那时这里缺席，界面就得说"没收下"）。
   *  可选是为了让**没重启的后端**那份没有这个键的响应照样能解析。 */
  run_config?: TaskRunConfigEcho | null;
}

/** GET /tasks/{id} 与 GET /tasks 的列表项。 */
export interface TaskDetail {
  task_id: string;
  task: string;
  status: TaskStatus;
  final_answer: string | null;
  error: string | null;
  difficulty: string | null;
  grade: string | null;
  score: number | null;
  iterations: number | null;
  progress: Record<string, unknown> | null;
  queue: Record<string, unknown> | null;
  tool_calls: number | null;
  tool_failures: number | null;
  cost: number | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string | null;
}

export interface TaskListResponse {
  items: TaskDetail[];
  total: number;
  limit: number;
  offset: number;
}

/** GET /tasks/{id}/trace 的一条事件（游标分页）。
 *
 * 这是**归一后**的形态，页面一律读它；线上形态见 `TraceEventRaw`。
 */
export interface TraceEvent {
  event_seq: number;
  step: number | null;
  sub_step: number | null;
  event_type: string;
  role: string | null;
  node: string | null;
  thought: string | null;
  tool_name: string | null;
  /** 工具入参的 JSON 文本（fetchTrace 边界处由 object 转来）；非工具事件为 null。 */
  arguments: string | null;
  observation: string | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost: number | null;
  status: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

export interface TraceResponse {
  items: TraceEvent[];
  total: number;
  limit: number;
  after_seq: number;
  next_after_seq: number | null;
  has_more: boolean;
  events_available: boolean;
  unavailable_reason: string | null;
}

/** `GET /tasks/{id}/trace` 列表项的**线上形态**：`arguments` 是 object 或 null。
 *
 * 只有 `api/client.ts::fetchTrace` 允许读它 —— 在那里映射成 `TraceEvent`。
 * 分开声明的意义：哪天有人想把 raw 事件直接传进组件，tsc 会拦住，
 * 而不是等运行时白屏（原来这里写成 `string` 就是白屏的直接原因）。
 */
export interface TraceEventRaw extends Omit<TraceEvent, 'arguments'> {
  arguments: Record<string, unknown> | null;
}

export interface TraceResponseRaw extends Omit<TraceResponse, 'items'> {
  items: TraceEventRaw[];
}

/** GET /tools 的一项。 */
export interface ToolSpecView {
  name: string;
  description: string;
  danger_level: 'low' | 'high';
  timeout: number;
  retry: number;
  parameters: Record<string, unknown>;
}

/** ``GET /models`` 的列表项：本次部署**实际**会调用的模型（不是候选清单）。
 *
 * 字段与服务端一一对应；``price_*`` 单位是「元 / 100 万 token」。
 * 前端**不许**再自带一份模型清单 —— 上一版的选项写在 ``src/mock/taskMock.ts`` 里，
 * 选完既不进请求体、后端也没这个字段。
 */
/** 一个价格档（阶梯计价时一个模型有多条）。单位：元 / 100 万 token。 */
export interface PriceTierView {
  max_input_tokens: number | null;
  price_in_per_million_cny: number;
  price_out_per_million_cny: number;
  note: string;
}

/** 候选清单里的一行（``GET /models`` 的 ``catalog``）。 */
export interface ModelCatalogEntry {
  id: string;
  display_name: string;
  provider: string;
  provider_display: string;
  tiers: PriceTierView[];
  tiered: boolean;
  tiers_text: string;
  pricing_basis: string;
  price_source_url: string;
  price_checked_on: string;
  suggested_for: Array<'large' | 'small'>;
  /** 那家的 Key 配了没有。``false`` 时选中它会被写端点当场拒 —— 界面要提前说。 */
  key_configured: boolean;
  base_url: string;
  endpoint_source: 'env' | 'provider_env' | 'provider_default';
  key_env_var: string;
}

/** 每家的 Key / 端点状态。
 *
 * ⚠️ 这里**没有装 Key 值的字段**，连掩码都没有 —— 面板能知道的只有"配了没有、
 * 配的是哪一个来源、环境变量叫什么"。页面上新加的输入框是**只进不出**的：
 * 值只出现在 ``POST /models/key`` 的请求体里，响应回来的是整份 ``ModelListResponse``
 * （``tests/integration/test_api_models_key.py`` 的"既无明文也无掩码形态"钉住这一条）。
 *
 * 后四个字段是可选的：老进程（这次改动之前起的）不会给，读不到时界面按
 * ``key_configured`` 说话，不假装知道来源。 */
export interface ProviderKeyView {
  provider: string;
  display_name: string;
  model_count: number;
  /** 这一家**实际发请求时**有没有可用的 Key —— 网关档下它说的是网关那把。 */
  key_configured: boolean;
  /** 上面那个"有"是从哪儿来的。``runtime`` = 本次进程里面板填的。 */
  key_source?: 'env' | 'runtime' | 'none';
  /** 环境变量叫什么名字（网关档下是 ``LLM_API_KEY``，不是这家自己的）。 */
  key_env_var: string;
  /** 这家**自己的**那个字段（``LLM_API_KEY_ZHIPU``）填了没有。 */
  own_key_configured?: boolean;
  own_key_env_var?: string;
  /** ``true`` = 所有请求都走 .env 的端点与 Key（自建网关档），这家自己的 Key 不会被用到。 */
  env_channel?: boolean;
  base_url: string;
  base_url_env_var: string;
  peak_off_peak: boolean;
}

/** ``POST /models/key`` 的响应：整份新状态 + 一句人话（**没有 Key**）。 */
export interface ModelKeyAck {
  changed: boolean;
  message: string;
  state: ModelListResponse;
}

/** ``POST /models/key/validate`` 的响应：一次零 token 探测的结果。 */
export interface ModelKeyProbeView {
  ok: boolean;
  provider: string;
  /** 探测实际打在哪个端点上（由后端按注册表算出来的，不是前端给的）。 */
  base_url: string;
  /** 上游给的 HTTP 状态；``null`` = 连上了但没有 HTTP 层响应（超时 / DNS 失败）。 */
  http_status: number | null;
  /** ``/models`` 报回来的模型条数；``null`` = 响应里没有 ``data`` 数组。 */
  model_count: number | null;
  /** 给人看的那句：成功是"拿到几个模型"，失败是**供应商原话**。 */
  detail: string;
  latency_ms: number;
  /** 超时上限（秒）。界面那句"3 秒"读这里，不在前端写死。 */
  timeout_s: number;
}


/** 当前生效来源：.env 还是本进程的覆盖。 */
export interface ModelOverrideView {
  model_large: string;
  model_small: string;
  source: 'env' | 'override';
  applied_at: string | null;
  version: number;
  previous_large: string;
  previous_small: string;
}

export interface ModelSpecView {
  id: string;
  provider: string;
  tier: 'large' | 'small';
  roles: string[];
  price_in_per_million_cny: number;
  price_out_per_million_cny: number;
  price_source: 'official_table' | 'settings_fallback';
  configured: boolean;
  /* ↓ 2026-09-26 换模型那一轮新增的字段，全部**可选**：
     跑着旧进程的后端不会给（他那个后端不带 --reload，新字段要重启才在）。
     可选不是宽容，是逼调用方处理"读不到"：少了这层，页面会对着 undefined
     印出一句半截话，正是 R-03 / K3 那一轮反复钉的东西。 */
  provider_display?: string;
  base_url?: string;
  endpoint_source?: 'env' | 'provider_env' | 'provider_default';
  known?: boolean;
  tiered?: boolean;
  tiers?: PriceTierView[];
  pricing_basis?: string;
  peak_off_peak?: boolean;
}

export interface ModelListResponse {
  items: ModelSpecView[];
  total: number;
  /** 角色 → 实际调用的模型 id（服务端从 ``items`` 派生，不是第二份表）。
   *
   * 前端**刻意不渲染**它：``items[].roles`` 已经是同一事实的另一面，
   * 同屏放两份"哪个角色用哪个模型"只会多一处能说过话的地方。留字段是给
   * 按角色查表的调用方（以及 P2b 的多 provider 预置）用的。 */
  role_map: Record<string, string>;
  /** 调用方不指定 model 时，适配层实际用的那个（= 强模型档）。 */
  default_model: string;
  /** 服务端自己对单价口径的原话，前端不另写一份。 */
  pricing_basis: string;
  /** ⚠️ 这个系数只对**分峰谷计价**的家有意义（目前只有 DeepSeek）。
   *  旧版把它无条件印成"低谷时段系数 ×0.5"，换成智谱/千问之后那句话就是说谎 ——
   *  现在必须先问 ``providers[].peak_off_peak``。 */
  off_peak_multiplier: number;
  /** 候选清单（只含核过价的行）。缺字段 = 后端是重启前的老进程 ⇒ 面板改口，不印半截话。 */
  catalog?: ModelCatalogEntry[];
  providers?: ProviderKeyView[];
  override?: ModelOverrideView;
  fallback_price_in_per_million_cny?: number;
  fallback_price_out_per_million_cny?: number;
}

/** ``POST/DELETE /models/override`` 的响应：整份新状态 + 一句人话。 */
export interface ModelOverrideAck {
  changed: boolean;
  message: string;
  state: ModelListResponse;
}

/** GET /knowledge/overview。 */
export interface KnowledgeOverview {
  document_count: number;
  chunk_count: number;
  token_count: number;
  ready_count: number;
  failed_count: number;
  indexing_count: number;
  vector_backend: string;
  embedding_model: string;
  last_indexed_at: string | null;
  /** 单文件上限（MB）。K3：界面上那句「≤ N MB」只读这里，**前端不许写死数字**
   *  （写死之后改 config 的人只会看到"界面在骗人"；422 的原文照旧兜底显示）。 */
  max_file_mb: number;
  /** 上传白名单（小写扩展名、不带点、后端已排序）。R-03：与 `max_file_mb` 同一形状，
   *  值来自 `api/constants.py::DOC_SUPPORTED_FORMATS`，且与后端 422 的判定**同一份**。
   *
   *  ⚠️ 这里**刻意**写成可选，而上面那条 `max_file_mb` 是必选：字段是新加的，
   *  没重启的后端进程压根不发它 —— 写成必选等于让 TS 替我们撒一次谎（编译期绿、
   *  运行期 `undefined`）。K3 当时没吸取这一点，R-03 这一条开始新字段一律按"可能不在"标。
   *  消费方（`KnowledgePage`）判的是"形状对不对"，不是"响应有没有"。 */
  supported_formats?: string[];
}

/** 文档状态机里**已知**的六个值，与 ``api/constants.py`` 的 ``DOC_*`` 一一对应。
 *
 * ⚠️ 刻意**不**把 `DocumentView.status` 的类型写成这个联合：
 * 线上回来什么就得显示什么（避坑 5）。写成联合等于让 TS 替我们断言"不会有第七种"，
 * 而后端加状态时它是真会来 —— 那时编译期一片绿、运行期把未知状态当成
 * 别的东西渲染。Z 趟专门往 mock 里塞一个 `verifying` 钉这条。
 */
export type KnownDocumentStatus =
  | 'pending'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'ready'
  | 'failed';

/** GET /knowledge/documents 的列表项，也是 GET /knowledge/documents/{id} 的响应。 */
export interface DocumentView {
  document_id: string;
  filename: string;
  size_bytes: number;
  format: string;
  /** 已知取值见 :type:`KnownDocumentStatus`；未知值原样上屏。 */
  status: string;
  /** 失败阶段。后端给的不止三个阶段名，还有 `queue` / `dedup` / `unknown`
   *  （入队失败与受理期失败根本没有进到解析那三步），画进度条时要兜住。 */
  error_stage: string | null;
  error_message: string | null;
  chunk_count: number;
  token_count: number;
  embedding_fingerprint: string;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface DocumentListResponse {
  items: DocumentView[];
  total: number;
}

/** POST /knowledge/documents 的 201 回执（受理成功 ≠ 索引完成）。 */
export interface DocumentUploadAck {
  document_id: string;
  filename: string;
  status: string;
  upload_at: string;
  /** 轮询地址（后端原样给出，前端不自己拼路径）。 */
  status_url: string;
  /** 受理提示：覆盖重建时后端会在这里说"旧索引已清除"，必须上屏，不能只报"上传成功"。 */
  warnings: string[];
}

export interface DocumentRetryAck {
  document_id: string;
  status: string;
  queued: boolean;
}

export interface DocumentDeleteAck {
  document_id: string;
  deleted: boolean;
}

/** 检索评测某一组的**单题**结果（CLI 落盘原样透传，用于逐题明细表）。 */
export interface EvalDetail {
  id: string;
  type: string;
  query: string;
  expect_document: string;
  /** 0 = 未命中；1..k = 命中排名 */
  rank: number;
  top_score: number;
  hit_document: string;
  hit_chunk_seq: number;
  took_ms: number;
  bm25_mean: number;
  vector_mean: number;
}

/** GET /eval/retrieval-report 里 report.groups[] 的一项（CLI 落盘原样透传）。 */
export interface EvalGroup {
  weights: { bm25: number; vector: number };
  top_k: number;
  total: number;
  top1_rate: number;
  top3_rate: number;
  hit5_rate: number;
  mrr: number;
  bm25_score_mean: number;
  vector_score_mean: number;
  /** 逐题明细（1000 篇语料实测 70 条/组）；前端分页渲染，不预填 */
  details?: EvalDetail[];
}

export interface RetrievalReportEnvelope {
  available: boolean;
  report_file?: string;
  reason?: string;
  report?: {
    dataset: string;
    dataset_size: number;
    /** 语料文件名清单（1000 篇），前端只取 length 显示语料规模 */
    fixtures: string[];
    embedding_model: string;
    chunk_size: number;
    chunk_overlap: number;
    generated_at: string;
    g2_gate: {
      /** 参照组的 top-3 命中率；参照组没参与本次扫描时后端给 null（原来会拿别的组冒充它） */
      reference_top3_rate: number | null;
      threshold: number;
      passed: boolean;
      /** 参照组权重，标签从这里读，别再在文案里硬写 0.4:0.6 */
      reference_group?: { bm25: number; vector: number };
      /** false ⇒ `passed=false` 的含义是"无法判定"，不是"未达门槛"（CLI 退出码 2） */
      evaluable?: boolean;
      reason?: string;
      scanned_groups?: string[];
    };
    groups: EvalGroup[];
  };
}

/** GET /eval/ablation-report：一臂一行（后端摊平好，前端不自己拼）。 */
export interface AblationArmRow {
  arm_id: string;
  n_used: number | null;
  ndcg_at_k?: number | null;
  mrr_at_k?: number | null;
  hit_at_k?: number | null;
  baseline_ndcg_at_k?: number | null;
  delta_ndcg_at_k?: number | null;
  rel_lift_ndcg_at_k?: number | null;
  delta_mrr_at_k?: number | null;
  rel_lift_mrr_at_k?: number | null;
}

/** F1/F2 归因计数（判据与 scripts/analyze_ablation_failures.py 一致）。 */
export interface AttributionRow {
  scored: number;
  f1: number;
  f2: number;
  clean: number;
}

export interface AblationReportEnvelope {
  available: boolean;
  report_file?: string;
  reason?: string;
  report?: {
    questions: number;
    corpus_docs: number;
    arms: Record<string, { error?: string | null; metrics?: Record<string, number> }>;
    failed_arms: string[];
    significance?: { note?: string };
  };
  arms?: AblationArmRow[];
  attribution?: Record<string, AttributionRow>;
}

/** ``GET /tasks/{id}/cost-breakdown`` 的一行 = 一个 ``(角色, 模型, 峰谷系数)`` 组合。
 *
 *  同一次运行跨了 12:00 / 18:00 边界时，**同一角色会出两行**（两个系数），这是后端有意
 *  为之（方案 §10.2g）：挑一个「代表系数」盖掉差异就是把真实分布抹平。渲染层不许再按
 *  角色二次聚合。
 *
 *  ⚠️ ``null`` 一律读作「没记录」，不是 0、也不是「免费」：
 *  - ``model === null`` —— 这条事件写于 ``model`` 列落地之前；
 *  - ``price_multiplier === null`` —— 同上，且此时 ``peak`` 也是 ``null``。
 *  后端**不会**拿今天的 ``role_map`` 去填历史（那是拿今天的账算昨天的钱），
 *  前端也不许在展示层补 ``1.0``。 */
export interface CostRoleRow {
  role: string | null;
  model: string | null;
  price_multiplier: number | null;
  /** 由服务端的系数 + "这家分不分峰谷"共同决定。``null`` 有三种意思，前端不许合并成一种：
   *  ①老任务没记系数；②这家根本不分峰谷（智谱/千问）⇒ 1.0 是"没有折扣"不是"高峰"；
   *  ③系数不是已知档位。所以不许写成 ``row.peak ? '高峰' : '低谷'``（None 会被读成低谷）。 */
  peak: boolean | null;
  /** ``true`` ⇒ 下面的 unit_price_* 是**下界**（该模型按输入长度分档）；``null`` = 模型没记进库。 */
  tiered?: boolean | null;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  /** 人民币元。后端不截断精度，展示一律走 ``fmtCostFixed(v, 4)``。 */
  cost: number;
  /** 元 / 100 万 token（全项目统一单位）。 */
  unit_price_in: number | null;
  unit_price_out: number | null;
  price_source: 'official_table' | 'settings_fallback' | 'unknown';
  /** 这一行单价的口径原话（服务端给，前端不另写一份）。缺字段 = 重启前的老后端。 */
  pricing_basis?: string;
}

export interface CostTotals {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
}

/** 计费时段事实，**全部后端算**（避坑 1）。
 *
 *  ⚠️ 前端不许自己判时段：``tasks.created_at`` 存的是 UTC，而后端把无时区的串按北京
 *  时间解释 ⇒ 自判整体错 8 小时（把半夜的半价标成高峰）。``next_off_peak_at`` 也是
 *  后端算好的绝对时刻，前端只做格式化 —— 连 ``Date.now()`` 都不该读（探针 AA 就是钉这条）。 */
export interface CostWindow {
  /** **查询此刻**是否高峰。与「本次运行跑在哪一档」（``by_role[].peak``）是两件事。 */
  is_peak_now: boolean;
  multiplier_now: number;
  /** 下一次进入低谷的时刻；当前已在低谷时为 ``null``（那时「下一次」没有意义）。 */
  next_off_peak_at: string | null;
  window_desc: string;
}

/** 单价反推（C6 守门人）。后端解不出时 ``ok === null`` —— 页面必须显示「未校验」，
 *  不许显示成通过。渲染层唯一该做的是把 ``ok`` 的三态分开画。 */
export interface CostPriceCheck {
  ok: boolean | null;
  max_delta_pct: number | null;
  implied_price_in: number | null;
  implied_price_out: number | null;
  equations: number;
  reason: string | null;
}

/** 对账：``Σ by_role.cost`` 与 ``tasks.cost`` 是两条独立算出来的路径。 */
export interface CostReconcile {
  events_cost: number;
  task_cost: number;
  /** ``null`` = 任务未进终态，对账不适用（``tasks.cost`` 只在终态落库），**不是「不等」**。 */
  all_equal: boolean | null;
  note: string;
}

export interface CostBreakdown {
  task_id: string;
  /** 服务器北京时间（带 ``+08:00``）。面板上「计费时段」那一行的时间基准就是它。 */
  generated_at: string;
  totals: CostTotals;
  by_role: CostRoleRow[];
  window: CostWindow;
  price_check: CostPriceCheck;
  reconcile: CostReconcile;
}

export const STATUS_LABELS: Record<TaskStatus, string> = {
  queued: '排队中',
  running: '运行中',
  done: '成功',
  aborted: '已收口（迭代耗尽/超时）',
  failed: '失败',
  canceled: '已取消',
};

/** 状态 → AntD Tag 颜色。色板走 src/theme.ts 的 token，不写魔法色值。 */
export const STATUS_COLORS: Record<TaskStatus, string> = {
  queued: 'gold',
  running: 'blue',
  done: 'green',
  aborted: 'orange',
  failed: 'red',
  canceled: 'default',
};
