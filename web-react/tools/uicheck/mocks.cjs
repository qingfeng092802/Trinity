/* 视觉验收用的假后端：拦截 /api 与 /sse，返回与 types.ts 逐字段对齐的响应。
   仅用于渲染验证，不参与任何产品逻辑。 */
const TASK_ID = 'task-3f9a1c02be11';

const tasks = [
  { task: '用三句话说明 RAG 的检索增强原理，并指出结论来自哪份文档', status: 'done' },
  { task: '1024 路摄像头整机功耗怎么估算？给出算式与结果', status: 'running' },
  { task: '对比 BM25 与向量检索在中文技术文档场景下的适用边界', status: 'failed' },
  { task: '门禁一卡通系统选型要注意哪些供电与协议细节', status: 'aborted' },
  { task: '机房工程 UPS 容量按什么口径估算', status: 'queued' },
  { task: '综合布线里六类线与超六类的成本差在哪', status: 'done' },
  { task: '广播系统分区与功放功率怎么配比', status: 'done' },
  { task: '安防监控球机 PoE+ 与 PoE 的供电差异', status: 'canceled' },
].map((t, i) => ({
  task_id: i === 0 ? TASK_ID : `task-${(0x3f9a1c02be11 + i * 9973).toString(16)}`,
  task: t.task,
  status: t.status,
  created_at: new Date(Date.now() - i * 7 * 60 * 1000).toISOString(),
}));

/* FINAL ANSWER 故意给成一整篇 Markdown：标题 / 有序无序列表 / 宽表 / 行内代码 /
   引用块 / 删除线 / 外链 / 完全重复的段落 / 原生 HTML 与 javascript: 链接（XSS 探针）。
   2026-09-23 起答案走 react-markdown 渲染，这份 fixture 就是富文本与「不开 rehype-raw」
   这条安全口径的回归护栏。 */

/** 分路功耗表：12 列 × 12 行 —— 横向必溢出，纵向超过答案表格的 520px 封顶。
 *  前 10 列里除首列与末列外全是数值，用来验「整列都是数值才右对齐」。 */
const TBL_COLS = [
  '设备类型', '数量', '单路功率', '并发系数', '计算功率', '实测均值', '偏差',
  '功率因数', '电流谐波', '余量系数', '三相不平衡', '依据条文（含章节页码）',
];
const TBL_HEAD = `| ${TBL_COLS.join(' | ')} |`;
const TBL_SEP = `| ${TBL_COLS.map(() => '---').join(' | ')} |`;
const TBL_ROWS = [
  ['枪机 400 万', 512, '17.5 W', 0.85, '7616.0 W', '7402.3 W', '-2.81%', 0.92, '3.1%', 1.2, '1.8%', 'anfangjiankong.md#c12 · 第 3 章 41 页'],
  ['球机 800 万', 256, '27.4 W', 0.85, '5967.4 W', '6120.9 W', '+2.57%', 0.9, '4.2%', 1.2, '2.1%', 'anfangjiankong.md#c31 · 第 5 章 88 页'],
  ['半球 200 万', 128, '9.6 W', 0.8, '983.0 W', '964.2 W', '-1.91%', 0.94, '2.7%', 1.15, '1.2%', 'anfangjiankong.md#c58 · 第 3 章 52 页'],
  ['门禁一体机', 64, '6.2 W', 1, '396.8 W', '401.5 W', '+1.19%', 0.88, '5.4%', 1.3, '3.4%', 'menjin.md#c07 · 第 2 章 19 页'],
  ['广播功放', 64, '42.0 W', 0.6, '1612.8 W', '1588.4 W', '-1.51%', 0.86, '6.1%', 1.25, '2.9%', 'guangbo.md#c22 · 第 4 章 77 页'],
  ...Array.from({ length: 7 }, (_, i) => [
    `楼栋分支 ${i + 1} 号井`, 32, '17.5 W', 0.85, '476.0 W', `${470 + i}.2 W`, `-1.2${i}%`,
    0.92, `3.${i}%`, 1.2, `1.${i}%`, `anfangjiankong.md#c${60 + i} · 第 3 章 ${60 + i} 页`,
  ]),
].map((r) => `| ${r.join(' | ')} |`);

const MARKDOWN_ANSWER = [
  '## 整机功耗估算',
  '',
  '按 `IEEE 802.3af` 单端口最大输出 **15.4 W**、`802.3at`（PoE+）**30 W** 取上限；',
  '并发系数 0.85 由近 30 天在线率回归得到，与工单口径一致。',
  '',
  '### 计算口径',
  '',
  '1. 单路整机均值 = 编码 12.5 W + 网络 3.2 W + 云台余量 1.8 W',
  '2. 整机功耗 = 路数 × 并发系数 × 单路均值',
  '3. 交换机侧校核：`P = U × I × cosφ = 380 × 12.4 × 0.85 = 3999.08 W`',
  '',
  // 公式区探针：裸文本算式（_{}/^{}/Σ/√），必须换成真上下标并横向可滚
  '### 检索打分公式',
  '',
  'score(q,d) = Σ_{t∈q} tf(t,d) · idf(t) / √( Σ_{t∈d} tf(t,d) ^ 2 )',
  '',
  // 这条长算式（111 字符、两个带空格除号 ⇒ 不立分数）专门用来验「宁可横向溢出也不折行」
  'score_{BM25}(q,d) = Σ_{t∈q} IDF(t) · (tf(t,d) · (k_1 + 1)) / (tf(t,d) · (1 - b + b · len(d) / avgdl) + k_1)',
  '',
  'nDCG@k = DCG@k / IDCG@k ，其中 DCG@k = Σ_{i=1..k} (2^{rel_i} - 1) / log2(i + 1) ，IDCG@k = Σ_{i=1..k} (2^{rel_i^ast} - 1) / log2(i + 1) ，rel^ast 为按增益降序重排后的相关性分级',
  '',
  // 裸简写下标（模型不写花括号的那种）：下面四行是 2026-09-24 他截图里的真实输出。
  // 关键是 `P_IT` / `η_PoE` / `P_PoE_chain` 必须变成真下标，而同一段里的
  // `knowledge_search`、`my_file.py` 一个字都不许动 —— 两条一起放这里才是回归。
  '### 估算算式',
  '',
  'P_IT = N × P_cam ÷ η_PoE + P_sw + P_NVR + P_net + P_aux [W]',
  '',
  '- PoE链路段：P_PoE_chain = N × P_cam ÷ η_PoE （摄像头受电功率折算为交换机输入端取电）',
  '- 基础设施段：P_infra = P_sw + P_NVR + P_net + P_aux',
  '',
  'P_mains = P_IT ÷ η_UPS [W]，逐项取值的口径见 my_file.py 与 knowledge_search 的返回。',
  '',
  // 反例的第二档：散文段里出现的蛇形词，靠的是「段落根本不是算式形态」这道闸
  '常量 FOO_BAR 与脚本 read_config.js 只是顺带提到，不该被当成变量。',
  '',
  // 分数与「代码皮肤里的公式」：模型既会写 \frac{}{}，也爱把算式塞进反引号和 ``` 围栏里
  // 「保护」起来 —— 那两类必须换出代码皮肤，否则上下标永远出不来。
  '卡诺轩制冷系数写作 \\frac{Q_{cool}}{W_{comp}} ，按第二定律上限则只与两个热源温度有关：',
  '',
  'η_{Carnot} = \\frac{T_{hot} - T_{cold}}{T_{hot}}',
  '',
  '行内形式 `COP = Q_{cool} / W_{comp}` 与之一致。',
  '',
  '```',
  'Q_in = \\frac{m \\cdot c_p \\cdot (T_{max} - T_{min})}{\\eta_{motor}}',
  'P_total = 1024 × 12 / 0.92',
  '```',
  '',
  '```python',
  'sample = {"x_{1}": 1.0, "x_{2}": 0.5}  # 真代码：里面的 _{} 是字典键，不许当公式',
  'print(sum(sample.values()))',
  '```',
  '',
  '### 分路功耗计算表',
  '',
  // 12 列 × 12 行：横向一定溢出、纵向超过 520px 封顶，两个方向都有得验
  TBL_HEAD,
  TBL_SEP,
  ...TBL_ROWS,
  '',
  '> 表内「实测均值」来自近 7 天 PDU 采样，与计算功率的偏差超过 ±5% 的行需要复核并发系数。',
  '',
  '- 未计入 PoE 交换机自身损耗（经验值约 8%）',
  '- 未计入 NVR 侧长期供电',
  '  - 需要的话再补一轮 24 小时满写功耗',
  '',
  '## 结论',
  '',
  '1024 路整机功耗约 **15.23 kW**，建议按 1.2 裕量配到 `18.3 kW`，UPS 走 2N 冗余，三相均衡分配。',
  '',
  '其中 0.85 为同时在线并发系数，17.5 W 为单路整机均值（含编码与网络开销），两项均已核对原始工单记录。',
  '',
  '~~旧口径按 0.9 并发系数算得 16.13 kW，已废弃。~~',
  '',
  '参考条文：[GB 51346-2019](https://example.gov.cn/gb51346)',
  '',
  // 与上文完全相同的一段：验证「只折叠字符串全等的复述」
  '其中 0.85 为同时在线并发系数，17.5 W 为单路整机均值（含编码与网络开销），两项均已核对原始工单记录。',
  '',
  // 安全探针：不写 rehype-raw 就不该进 DOM，javascript: 就该被 urlTransform 抹掉
  '<script>document.title = "XSS-EXECUTED"</script>',
  '<img src=x onerror="document.title=\'XSS-EXECUTED\'">',
  '[点我](javascript:document.title=\'XSS-EXECUTED\')',
].join('\n');

const detail = {
  task_id: TASK_ID,
  task: tasks[0].task,
  status: 'done',
  final_answer: MARKDOWN_ANSWER,
  error: null, difficulty: 'medium', grade: 'B', score: 8, iterations: 2,
  progress: null, queue: null, tool_calls: 6, tool_failures: 3, cost: 0.0042,
  duration_ms: 9230,
  created_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

/** `arguments` 的线上形态是 **object**（设计文档 §6.2，后端 `TaskEventView` 刻意反序列化成
 *  dict 返回），不是 JSON 串。这里的三处工具事件必须按 object 给 ——
 *  之前写成预格式化字符串，正好绕过了「object 进 <pre> 白屏」这一类崩溃
 *  （2026-09-23：`code_exec` 的 `{"code": …}` 把「工具调用」页签整页打白）。
 *  保持与真接口一致，这份 fixture 才算崩溃回归护栏。 */
const traceItems = [
  {
    event_seq: 1, step: 0, sub_step: null, event_type: 'start', role: 'system', node: 'system',
    thought: null, tool_name: null, arguments: null, observation: null,
    latency_ms: 12, tokens_in: 0, tokens_out: 0, cost: 0, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 2, step: 1, sub_step: null, event_type: 'plan', role: 'planner', node: 'planner',
    thought: '先把问题拆成「标准依据 → 单路功耗 → 并发系数 → 总功耗估算」四步，再决定用哪个工具。',
    tool_name: null, arguments: null, observation: null,
    latency_ms: 1840, tokens_in: 642, tokens_out: 188, cost: 0.0009, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 3, step: 1, sub_step: 1, event_type: 'tool', role: 'executor', node: 'executor',
    thought: '先查知识库里 PoE 供电标准的原文段落。',
    tool_name: 'knowledge_search',
    arguments: { query: 'POE 单端口最大输出功率 标准', top_k: 5, fusion: 'rrf' },
    /* 这份 observation 的形状**照抄后端** `core/tools/builtin/knowledge_search.py:_render`
       （全角｜、`文档名 · chunk N（字符 a-b）`、`相关度 x（BM25 … / 向量 …）`）。
       之前写成「命中 4 个 chunk：…（0.83）」那种自造紧凑形，前端解析器永远不命中，
       引用列表就会一路走「认不出 → 全 —」的兜底分支，探针测到的根本不是真路径。
       复现命令见 tools/uicheck/citations.test.cjs 顶部。 */
    observation: [
      '共命中 4 条相关片段：',
      '【1】anfangjiankong.md · chunk 12（字符 0-512）｜相关度 0.83（BM25 0.71 / 向量 0.92）',
      '第 3 章：PoE 单端口最大输出功率 30W，设计值应按 25.5W 可用功率核算。',
      '【2】anfangjiankong.md · chunk 31（字符 900-1400）｜相关度 0.71（BM25 0.66 / 向量 0.74）',
      '第 5 章：整机功耗 = 设备数 × 单路功耗 ÷ 供电效率，PoE 交换机效率取 0.85。',
      '【3】anfangjiankong.md · chunk 58（字符 2100-2600）｜相关度 0.66（BM25 0.61 / 向量 0.70）',
      '第 3 章 52 页：冗余供电按 1+1 配置，主备切换时间不大于 50ms。',
      '【4】shengchanfangkong.md · chunk 7（字符 300-880）｜相关度 0.52（BM25 0.55 / 向量 0.49）',
      '监控中心供电回路应独立敷设，与动力回路间距不小于 300mm。',
    ].join('\n'),
    latency_ms: 312, tokens_in: 128, tokens_out: 24, cost: 0.0002, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 4, step: 1, sub_step: 2, event_type: 'tool', role: 'executor', node: 'executor',
    thought: '用计算器先估一遍，再决定要不要 code_exec 复核。',
    tool_name: 'calculator',
    arguments: { expression: '1024 * 0.85 * 17.5' },
    observation: '15232.0',
    latency_ms: 41, tokens_in: 62, tokens_out: 9, cost: 0.0001, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 5, step: 1, sub_step: 3, event_type: 'tool', role: 'executor', node: 'executor',
    thought: 'calculator 精度不足，交给 code_exec 复核。',
    tool_name: 'code_exec',
    arguments: { code: 'round(1024 * 0.85 * 17.5, 2)', timeout_s: 3 },
    observation: '15230.75',
    latency_ms: 412, tokens_in: 88, tokens_out: 16, cost: 0.0002, status: 'failed',
    error_code: 'TOOL_RETRY',
    error_message: '首次调用超时，已按 retry=1 重试成功（本事件记为失败便于统计真实失败率）',
    created_at: new Date().toISOString(),
  },
  {
    event_seq: 6, step: 2, sub_step: null, event_type: 'review', role: 'reviewer', node: 'reviewer',
    thought: '证据齐了，但第一步没给标准编号，退回补充。',
    tool_name: null, arguments: null, observation: 'review_result=false review_score=6',
    latency_ms: 980, tokens_in: 512, tokens_out: 96, cost: 0.0007, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 7, step: 3, sub_step: null, event_type: 'final', role: 'reviewer', node: 'reviewer',
    thought: '补了 IEEE 802.3af / 802.3at 的标准编号与功率上限，可以收口。',
    tool_name: null, arguments: null, observation: 'review_result=true review_score=8',
    latency_ms: 1120, tokens_in: 486, tokens_out: 132, cost: 0.0008, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 8, step: 3, sub_step: 1, event_type: 'tool', role: 'executor', node: 'executor',
    // 两条兜底分支一起验：thought=null（意图标题退回「动词：关键入参」），
    // 且名字既不在前端字典也不在注册表（Tooltip 走「未收录」分支）
    thought: null,
    tool_name: 'ocr_table',
    arguments: { image: 'uploads/rating-table.png' },
    observation: '识别出 12 行 6 列',
    latency_ms: 640, tokens_in: null, tokens_out: null, cost: null, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  /* 三条连续的运行中心跳帧（后端 TASK_EVT_RUNNING 的真实形状：没有 thought /
     tool / observation，只有状态）。逐条摆出来会把节点行挤出视野，
     展示层要合并成一行原地刷新 —— 见 src/utils/logRows.ts。 */
  {
    event_seq: 9, step: 3, sub_step: null, event_type: 'running', role: 'system', node: 'system',
    thought: null, tool_name: null, arguments: null, observation: null,
    latency_ms: 15000, tokens_in: 0, tokens_out: 0, cost: 0, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 10, step: 3, sub_step: null, event_type: 'running', role: 'system', node: 'system',
    thought: null, tool_name: null, arguments: null, observation: null,
    latency_ms: 15000, tokens_in: 0, tokens_out: 0, cost: 0, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  {
    event_seq: 11, step: 3, sub_step: null, event_type: 'running', role: 'system', node: 'system',
    thought: null, tool_name: null, arguments: null, observation: null,
    latency_ms: 15000, tokens_in: 0, tokens_out: 0, cost: 0, status: 'done',
    error_code: null, error_message: null, created_at: new Date().toISOString(),
  },
  /* code_exec 超时：后端 status 如实给 'timeout'（api/schemas.py:267），
     thought 为 null ⇒ 同时验「标题不能再拿代码截断凑数」这一条。
     出参文本是 core/tools/sandbox.py:73-74 那两行的原样。 */
  {
    event_seq: 12, step: 3, sub_step: 2, event_type: 'tool', role: 'executor', node: 'executor',
    thought: null,
    tool_name: 'code_exec',
    arguments: {
      /* 18 行、带三引号 docstring / 注释 / 数字 / f-string 的真实形状：
         既要验「换行与缩进原样出来」，也要验超过折叠线后由「展开全文」接管。 */
      code: '"""扫一遍工作区，统计文件数与最大的单个文件。"""\nimport os, re, time  # 只读遍历，不写不删\nroots = [".", "/data", "/var/log"]\npat = re.compile(r"\\d+(\\.\\d+)?")\nhits = []\nt0 = time.time()\nfor r in roots:\n    for d, sub, fs in os.walk(r):\n        for f in fs:\n            p = os.path.join(d, f)\n            try:\n                hits.append((p, os.path.getsize(p)))\n            except OSError:\n                continue\nprint(f\'共 {len(hits)} 个文件，最大 {max(s for _, s in hits):,} 字节\')',
      timeout_s: 30,
    },
    observation: '执行超时，进程已被强制终止\nexit_code=1 (30541ms)',
    latency_ms: 30541, tokens_in: null, tokens_out: null, cost: null, status: 'timeout',
    error_code: 'SANDBOX_TIMEOUT',
    error_message: null,
    created_at: new Date().toISOString(),
  },
  /* 脚本自己非零退出（KeyError）。2026-09-24 起后端如实记 failed：
     core/tools/builtin/code_exec.py 对 returncode != 0 抛 SandboxFailed，
     registry 转成 status='failed'。以前这里记的是 'success'，
     前端只能靠嗅出参里的 exit_code 文本反推 —— 那层嗅探已随之删除。
     error_code 留 null：执行器发工具事件时不带这个字段（core/agent/executor.py 只给 status）。 */
  {
    event_seq: 13, step: 3, sub_step: 3, event_type: 'tool', role: 'executor', node: 'executor',
    thought: '顺手用脚本核一遍三相不平衡度。',
    tool_name: 'code_exec',
    arguments: { code: "import json\nrows = json.load(open('rating.json'))\nprint(max(r['unbalance'] for r in rows))" },
    observation: "Traceback (most recent call last):\n  File \"<sandbox>\", line 2, in <module>\nKeyError: 'rating.json'\nexit_code=1 (86ms)",
    latency_ms: 86, tokens_in: null, tokens_out: null, cost: null, status: 'failed',
    error_code: null, error_message: null,
    created_at: new Date().toISOString(),
  },
];

/* GET /api/tools：与 core/tools/builtin/* 的注册参数逐字段对齐（2026-09-23 抄自源码）。
   description 是**写给模型看**的口径，前端字典只把它当未收录工具的兜底文案。 */
const toolsBody = {
  items: [
    {
      name: 'calculator',
      description:
        '计算一个算术表达式并返回精确数值。涉及四则运算、幂、开方、对数、三角函数时必须调用本工具，不要自己心算',
      danger_level: 'low', timeout: 5, retry: 0,
      parameters: { type: 'object', properties: { expression: { type: 'string' } }, required: ['expression'] },
    },
    {
      name: 'code_exec',
      description:
        '在沙箱子进程里运行 Python 代码（最多 20 秒）并取回 stdout。适合需要精确计算、字符串/数据处理、文件批处理验证的场景；不要用它做网络请求或安装依赖',
      danger_level: 'high', timeout: 0, retry: 0,
      parameters: { type: 'object', properties: { code: { type: 'string' } }, required: ['code'] },
    },
    {
      name: 'extract',
      description:
        '从一段自由文本里抽取结构化字段（返回 JSON）。需要把非结构化描述变成规整数据时使用；schema 用 JSON Schema 字符串描述目标结构',
      danger_level: 'low', timeout: 60, retry: 1,
      parameters: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
    },
    {
      name: 'file_io',
      description:
        '在沙箱工作区内读写文本文件或列目录。需要落盘中间产物、读取已有资料时使用；路径必须相对工作区，越界路径会被拒绝',
      danger_level: 'high', timeout: 10, retry: 1,
      parameters: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] },
    },
    {
      name: 'knowledge_search',
      description:
        '检索本地知识库（用户上传的文档）。任务需要依据企业内部文档/上传资料作答时必须调用本工具，并基于返回片段与来源引用作答',
      danger_level: 'low', timeout: 10, retry: 1,
      parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] },
    },
    {
      name: 'web_search',
      description:
        '联网搜索网页并返回标题、链接与摘要。需要最新事实、外部数据或不确定的信息时使用；搜索失败会如实报错，不要据此编造内容',
      danger_level: 'low', timeout: 15, retry: 2,
      parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] },
    },
  ],
  total: 6,
};

const traceBody = {
  items: traceItems, total: traceItems.length, limit: 50, after_seq: 0,
  next_after_seq: null, has_more: false, events_available: true, unavailable_reason: null,
};

const weights = [[0.3, 0.7], [0.5, 0.5], [0.7, 0.3], [1, 0], [0, 1]];
const retrievalBody = {
  available: true,
  report_file: 'evaluation/reports/retrieval/2026-09-21T10-12-03.json',
  report: {
    dataset: 'data/eval/retrieval_set.jsonl',
    dataset_size: 70,
    fixtures: Array.from({ length: 1000 }).map((_, i) => `doc_${i}.md`),
    embedding_model: 'bge-small-zh-v1.5',
    chunk_size: 512,
    chunk_overlap: 64,
    generated_at: '2026-09-21T10:12:03+08:00',
    g2_gate: { reference_top3_rate: 0.8143, threshold: 0.8, passed: true },
    groups: weights.map(([b, v], i) => ({
      weights: { bm25: b, vector: v },
      top_k: 5,
      total: 70,
      top1_rate: [0.6, 0.6857, 0.7429, 0.5571, 0.4714][i],
      top3_rate: [0.8143, 0.8571, 0.8857, 0.7286, 0.6429][i],
      hit5_rate: [0.9286, 0.9429, 0.9571, 0.8714, 0.8][i],
      mrr: [0.7013, 0.7482, 0.7911, 0.6321, 0.5429][i],
      bm25_score_mean: [12.4471, 11.0238, 9.8142, 14.229, 0][i],
      vector_score_mean: [0.6221, 0.6344, 0.6417, 0, 0.5988][i],
    })),
  },
};

const ablationBody = {
  available: true,
  report_file: 'evaluation/reports/ablation/ablation_summary.json',
  report: {
    questions: 70, corpus_docs: 1000, arms: {}, failed_arms: ['arm_no_rerank'],
    significance: { note: '未做显著性检验：5 臂 × 70 题撑不起统计功效，仅报绝对提升 Δ 与相对提升。' },
  },
  arms: [
    { arm_id: 'arm_baseline', n_used: 70, ndcg_at_k: 0.7124, mrr_at_k: 0.6801, hit_at_k: 0.8857, delta_ndcg_at_k: 0, rel_lift_ndcg_at_k: 0, delta_mrr_at_k: 0, rel_lift_mrr_at_k: 0 },
    { arm_id: 'arm_hybrid_rrf', n_used: 70, ndcg_at_k: 0.8213, mrr_at_k: 0.7482, hit_at_k: 0.9429, delta_ndcg_at_k: 0.1089, rel_lift_ndcg_at_k: 0.1529, delta_mrr_at_k: 0.0681, rel_lift_mrr_at_k: 0.1001 },
    { arm_id: 'arm_rerank_top20', n_used: 70, ndcg_at_k: 0.8561, mrr_at_k: 0.7911, hit_at_k: 0.9571, delta_ndcg_at_k: 0.1437, rel_lift_ndcg_at_k: 0.2017, delta_mrr_at_k: 0.111, rel_lift_mrr_at_k: 0.1632 },
    { arm_id: 'arm_no_hybrid', n_used: 70, ndcg_at_k: 0.6122, mrr_at_k: 0.5571, hit_at_k: 0.8, delta_ndcg_at_k: -0.1002, rel_lift_ndcg_at_k: -0.1406, delta_mrr_at_k: -0.123, rel_lift_mrr_at_k: -0.1809 },
    { arm_id: 'arm_no_rerank', n_used: null, ndcg_at_k: null, mrr_at_k: null, hit_at_k: null, delta_ndcg_at_k: null, rel_lift_ndcg_at_k: null, delta_mrr_at_k: null, rel_lift_mrr_at_k: null },
  ],
  attribution: {
    arm_baseline: { scored: 70, f1: 8, f2: 16, clean: 46 },
    arm_hybrid_rrf: { scored: 70, f1: 4, f2: 12, clean: 54 },
    arm_rerank_top20: { scored: 70, f1: 3, f2: 9, clean: 58 },
    arm_no_hybrid: { scored: 70, f1: 14, f2: 21, clean: 35 },
  },
};

const healthBody = {
  status: 'healthy', version: '0.9.3', uptime_seconds: 8412,
  checks: {
    api: { status: 'ok', detail: 'ok' },
    database: { status: 'ok', detail: 'sqlite ok' },
    redis: { status: 'degraded', detail: '降级为进程内缓存' },
    llm: { status: 'ok', detail: '已配置 Key' },
    queue: { status: 'ok', detail: '运行中 0/4' },
    rag: { status: 'ok', detail: 'ok' },
  },
};

function sseFrames() {
  const frames = [];
  const push = (seq, node, update) => {
    frames.push(`event: node\ndata: ${JSON.stringify({ seq, node, update, status: 'running', ts: new Date().toISOString() })}\n\n`);
  };
  push(1, 'system', { status: 'running' });
  push(2, 'planner', { plan: ['检索 PoE 供电标准', '估算单路与并发功耗', '复核并给出结论'] });
  push(3, 'executor', { execution_results: [{ step_index: 0, subtask: '检索 PoE 供电标准', status: 'done', output: '命中 4 个 chunk：anfangjiankong.md#c12（0.83）、#c31（0.71）' }] });
  push(4, 'executor', { execution_results: [{ step_index: 1, subtask: '估算整机功耗', status: 'done', output: 'code_exec 返回 15230.75（耗时 412ms）' }] });
  push(5, 'reviewer', { review_result: false, review_score: 6 });
  push(6, 'executor', { execution_results: [{ step_index: 2, subtask: '补充标准编号', status: 'done', output: '补检索 2 个 chunk，补齐 IEEE 802.3af / 802.3at' }] });
  push(7, 'reviewer', { review_result: true, review_score: 8 });
  frames.push(`event: done\ndata: ${JSON.stringify({ seq: 8, status: 'done', ts: new Date().toISOString() })}\n\n`);
  return frames.join('');
}

/* GET /api/models：三份 **逐字抄自真跑 `GET /models` 的响应**（2026-09-24，
   一份经 TestClient 起完整 app，一份经本机 8001 的活服务），不是手编的。
   抄真响应的理由与 citations 那轮相同：自造 fixture 只会让探针一路走兜底分支。
   ⚠️ 单价单位是「元 / 100 万 token」。
   - modelsBody：本机 .env 的实际形态 —— 两档都配成 deepseek-flash ⇒ 后端**合并成一条**
   - modelsBodyTwoTiers：两档不同模型（强模型走大档、执行/抽取走快档）
   - modelsBodyFallback：强模型不在单价表里 ⇒ 同数字也要标成「兜底价」，
     这条是 utils/modelLabel.ts 规则 2 的用例素材（不许把兜底价叫官方价） */
const modelsBody = {
  items: [
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      tier: 'large',
      roles: ['executor', 'extract', 'judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
    },
  ],
  total: 1,
  role_map: {
    executor: 'deepseek-flash',
    extract: 'deepseek-flash',
    judge: 'deepseek-flash',
    planner: 'deepseek-flash',
    reviewer: 'deepseek-flash',
  },
  default_model: 'deepseek-flash',
  pricing_basis: 'DeepSeek 官方高峰价（美元）按固定汇率折算的人民币；低谷时段再乘 off_peak_multiplier',
  off_peak_multiplier: 0.5,
};

const modelsBodyTwoTiers = {
  items: [
    {
      id: 'deepseek-v4-pro',
      provider: 'deepseek',
      tier: 'large',
      roles: ['judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 9.37,
      price_out_per_million_cny: 28.12,
      price_source: 'official_table',
      configured: true,
    },
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      tier: 'small',
      roles: ['executor', 'extract'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
    },
  ],
  total: 2,
  role_map: {
    judge: 'deepseek-v4-pro',
    planner: 'deepseek-v4-pro',
    reviewer: 'deepseek-v4-pro',
    executor: 'deepseek-flash',
    extract: 'deepseek-flash',
  },
  default_model: 'deepseek-v4-pro',
  pricing_basis: modelsBody.pricing_basis,
  off_peak_multiplier: 0.5,
};

const modelsBodyFallback = {
  items: [
    {
      id: '某没配过价的模型',
      provider: 'deepseek',
      tier: 'large',
      roles: ['judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'settings_fallback',
      configured: true,
    },
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      tier: 'small',
      roles: ['executor', 'extract'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
    },
  ],
  total: 2,
  role_map: {
    judge: '某没配过价的模型',
    planner: '某没配过价的模型',
    reviewer: '某没配过价的模型',
    executor: 'deepseek-flash',
    extract: 'deepseek-flash',
  },
  default_model: '某没配过价的模型',
  pricing_basis: modelsBody.pricing_basis,
  off_peak_multiplier: 0.5,
};

/* ``GET /models`` 的**带候选清单**那一份（AC 趟：换模型）。
 *
 * 与上面三份的关系：那三份**没有** catalog / providers / override 字段 ——
 * 它们因此天然成为"重启前的老后端"这个分支的桩（面板必须改口、不许印半截话）。
 * 这一份才是新契约的样子，字段逐条对得上新 ``api/routes/models.py``。
 *
 * ⚠️ 桩值纪律（§11.9 那一课的延续）：候选里的 id、价格、日期都是**后端真值**，
 * 前端代码里一个都不许出现；判据靠"改桩 ⇒ 界面跟着变"来证伪，不靠"看起来对"。
 * 刻意留一家 ``key_configured: false``（qwen）—— 那正是"必须当场拒并说清缺哪家"的素材。 */
const modelsBodyWithCatalog = {
  items: [
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      provider_display: 'DeepSeek',
      tier: 'large',
      roles: ['executor', 'extract', 'judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
      base_url: 'https://api.deepseek.com/v1',
      endpoint_source: 'env',
      known: true,
      tiered: false,
      tiers: [
        { max_input_tokens: null, price_in_per_million_cny: 2.13, price_out_per_million_cny: 8.52, note: '' },
      ],
      pricing_basis: 'DeepSeek 官方高峰价（美元）按固定汇率 7.1 折算的人民币；低谷时段再乘 0.5',
      peak_off_peak: true,
    },
  ],
  total: 1,
  role_map: {
    executor: 'deepseek-flash',
    extract: 'deepseek-flash',
    judge: 'deepseek-flash',
    planner: 'deepseek-flash',
    reviewer: 'deepseek-flash',
  },
  default_model: 'deepseek-flash',
  pricing_basis:
    '这一句只解释**兜底单价**（未登记模型用的 settings.llm_price_in/out）；每一家、每一个模型的口径看它自己那行的 pricing_basis',
  off_peak_multiplier: 0.5,
  catalog: [
    {
      id: 'deepseek-flash',
      display_name: 'DeepSeek-V4.1-Flash',
      provider: 'deepseek',
      provider_display: 'DeepSeek',
      tiers: [
        { max_input_tokens: null, price_in_per_million_cny: 2.13, price_out_per_million_cny: 8.52, note: '' },
      ],
      tiered: false,
      tiers_text: '2.13/8.52 元',
      pricing_basis: 'DeepSeek 官方高峰价（美元）按固定汇率 7.1 折算的人民币；低谷时段再乘 0.5',
      price_source_url: 'https://api-docs.deepseek.com/quick_start/pricing',
      price_checked_on: '2026-09-15',
      suggested_for: ['large', 'small'],
      key_configured: true,
      base_url: 'https://api.deepseek.com/v1',
      endpoint_source: 'env',
      key_env_var: 'LLM_API_KEY',
    },
    {
      id: 'glm-4.6',
      display_name: 'GLM-4.6',
      provider: 'zhipu',
      provider_display: '智谱 GLM',
      tiers: [
        { max_input_tokens: 32000, price_in_per_million_cny: 1, price_out_per_million_cny: 3, note: '' },
        { max_input_tokens: 128000, price_in_per_million_cny: 2, price_out_per_million_cny: 6, note: '' },
      ],
      tiered: true,
      tiers_text: '1/3 元（输入 ≤32,000） · 2/6 元（输入 ≤128,000）',
      pricing_basis: '智谱官网人民币标价（原价，按输入长度分档）',
      price_source_url: 'https://docs.bigmodel.cn/cn/guide/start/pricing',
      price_checked_on: '2026-09-26',
      suggested_for: ['large'],
      key_configured: true,
      base_url: 'https://open.bigmodel.cn/api/paas/v4',
      endpoint_source: 'provider_default',
      key_env_var: 'LLM_API_KEY_ZHIPU',
    },
    {
      id: 'glm-4-air',
      display_name: 'GLM-4-Air',
      provider: 'zhipu',
      provider_display: '智谱 GLM',
      tiers: [
        { max_input_tokens: null, price_in_per_million_cny: 0.5, price_out_per_million_cny: 0.5, note: '' },
      ],
      tiered: false,
      tiers_text: '0.5/0.5 元',
      pricing_basis: '智谱官网人民币标价（原价，不分档）',
      price_source_url: 'https://docs.bigmodel.cn/cn/guide/start/pricing',
      price_checked_on: '2026-09-26',
      suggested_for: ['small'],
      key_configured: true,
      base_url: 'https://open.bigmodel.cn/api/paas/v4',
      endpoint_source: 'provider_default',
      key_env_var: 'LLM_API_KEY_ZHIPU',
    },
    {
      id: 'qwen-plus',
      display_name: '通义千问-Plus',
      provider: 'qwen',
      provider_display: '阿里云千问',
      tiers: [
        { max_input_tokens: 128000, price_in_per_million_cny: 0.8, price_out_per_million_cny: 2, note: '' },
        { max_input_tokens: 256000, price_in_per_million_cny: 2.4, price_out_per_million_cny: 20, note: '' },
      ],
      tiered: true,
      tiers_text: '0.8/2 元（输入 ≤128,000） · 2.4/20 元（输入 ≤256,000）',
      pricing_basis: '千问官网人民币标价（非思考模式、原价；思考模式输出另计更高价）',
      price_source_url: 'https://help.aliyun.com/zh/model-studio/model-pricing',
      price_checked_on: '2026-09-26',
      suggested_for: ['small'],
      key_configured: false,
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      endpoint_source: 'provider_default',
      key_env_var: 'LLM_API_KEY_QWEN',
    },
  ],
  providers: [
    {
      provider: 'deepseek', display_name: 'DeepSeek', model_count: 3, key_configured: true,
      key_source: 'env', own_key_configured: true, own_key_env_var: 'LLM_API_KEY', env_channel: false,
      key_env_var: 'LLM_API_KEY', base_url: 'https://api.deepseek.com/v1', base_url_env_var: '', peak_off_peak: true,
    },
    {
      provider: 'zhipu', display_name: '智谱 GLM', model_count: 4, key_configured: true,
      key_source: 'env', own_key_configured: true, own_key_env_var: 'LLM_API_KEY_ZHIPU', env_channel: false,
      key_env_var: 'LLM_API_KEY_ZHIPU', base_url: 'https://open.bigmodel.cn/api/paas/v4',
      base_url_env_var: 'LLM_BASE_URL_ZHIPU', peak_off_peak: false,
    },
    {
      provider: 'qwen', display_name: '阿里云千问', model_count: 3, key_configured: false,
      key_source: 'none', own_key_configured: false, own_key_env_var: 'LLM_API_KEY_QWEN', env_channel: false,
      key_env_var: 'LLM_API_KEY_QWEN', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      base_url_env_var: 'LLM_BASE_URL_QWEN', peak_off_peak: false,
    },
  ],
  override: {
    model_large: 'deepseek-flash', model_small: 'deepseek-flash', source: 'env',
    applied_at: null, version: 0, previous_large: 'deepseek-flash', previous_small: 'deepseek-flash',
  },
  fallback_price_in_per_million_cny: 2.13,
  fallback_price_out_per_million_cny: 8.52,
};

/** 角色 → 档位（与后端 ``api/routes/models.py:_ROLE_TIER`` 同一张表，抄的不是意图）。 */
const MOCK_ROLE_TIER = {
  planner: 'large', reviewer: 'large', judge: 'large', executor: 'small', extract: 'small',
};

/** 造一个**有状态**的 /models + /models/override 桩，行为对齐真后端。
 *
 * 为什么桩必须"会动"：只回一份静态 JSON 的桩验不出这条链上最容易错的那件事 ——
 * "点了应用之后，界面显示的是不是服务端真的生效了那份"。这里 POST 会改内部状态，
 * 之后的 GET 返回改过的样子，与真后端同形（同一纪律：422 也要真的拒）。 */
function createModelOverrideMock(baseBody, options = {}) {
  const clone = (x) => JSON.parse(JSON.stringify(x));
  let body = clone(baseBody);
  let version = 0;
  const calls = { post: [], rejected: [], key: [] };
  /** 本次进程里被"面板填进来"的 Key：``provider → 明文``（只活在这个闭包里）。 */
  const runtimeKeys = {};
  /** 出厂那一份供应商视图：撤回时按家回落，与后端"回落到环境变量"同义。 */
  const baseProviders = clone(baseBody.providers);

  /** 把一家的四个 Key 字段按"有没有面板填的 Key"重画（后端的 ``key_secret`` 同一规则）。
   *
   * 四个字段必须**一起**动：只翻 ``key_configured`` 的话，界面会出现
   * 「已配置，但来源还写着 env」这种自相矛盾的读数（AE-4 盯的就是它）。 */
  function paintKeyView(p) {
    const filled = runtimeKeys[p.provider];
    if (filled !== undefined) {
      p.key_source = 'runtime';
      p.own_key_configured = true;
      p.key_configured = true;
      return;
    }
    const b = baseProviders.find((row) => row.provider === p.provider);
    if (b) Object.assign(p, clone(b));
  }

  const entryFor = (id) => (body.catalog || []).find((row) => row.id === String(id).toLowerCase());

  function rebuild(large, small) {
    const allRoles = [...body.items[0].roles];
    const tierOf = (id) => {
      const src = entryFor(id);
      const price = src ? src.tiers[0] : { price_in_per_million_cny: body.fallback_price_in_per_million_cny, price_out_per_million_cny: body.fallback_price_out_per_million_cny };
      return {
        id,
        provider: src ? src.provider : 'deepseek',
        provider_display: src ? src.provider_display : 'DeepSeek',
        price_in_per_million_cny: price.price_in_per_million_cny,
        price_out_per_million_cny: price.price_out_per_million_cny,
        price_source: src ? 'official_table' : 'settings_fallback',
        configured: src ? src.key_configured : true,
        base_url: src ? src.base_url : 'https://api.deepseek.com/v1',
        endpoint_source: src ? src.endpoint_source : 'env',
        known: Boolean(src),
        tiered: src ? src.tiered : false,
        tiers: src ? clone(src.tiers) : [],
        pricing_basis: src
          ? src.pricing_basis
          : `未登记模型 ⇒ 兜底单价 ${body.fallback_price_in_per_million_cny}/${body.fallback_price_out_per_million_cny} 元/百万 token`,
        peak_off_peak: src ? (body.providers.find((p) => p.provider === src.provider) || {}).peak_off_peak !== false : true,
      };
    };
    const largeItem = { ...tierOf(large), tier: 'large', roles: [] };
    const smallItem = { ...tierOf(small), tier: 'small', roles: [] };
    for (const [role, tier] of Object.entries(MOCK_ROLE_TIER)) {
      (tier === 'large' ? largeItem : smallItem).roles.push(role);
    }
    if (large === small) {
      largeItem.roles = allRoles.sort();
      body.items = [largeItem];
      body.total = 1;
    } else {
      smallItem.roles.sort();
      largeItem.roles.sort();
      body.items = [largeItem, smallItem];
      body.total = 2;
    }
    body.role_map = {};
    for (const item of body.items) for (const role of item.roles) body.role_map[role] = item.id;
    body.default_model = large;
    version += 1;
    body.override = {
      model_large: large,
      model_small: small,
      source: 'override',
      applied_at: `2026-09-26T18:0${version}:00+08:00`,
      version,
      previous_large: body.override.model_large,
      previous_small: body.override.model_small,
    };
    return body;
  }

  const json = (status, payload) => ({ status, contentType: 'application/json', body: JSON.stringify(payload) });

  return {
    body: () => body,
    calls,
    /** GET /api/models */
    get: () => json(200, body),
    /** POST /api/models/override —— 与后端同三条：相同值 changed=false；缺 Key 422；否则改状态 */
    post: (payload) => {
      calls.post.push(payload);
      const large = String(payload.model_large || '').trim().toLowerCase();
      const small = String(payload.model_small || '').trim().toLowerCase();
      if (!large || !small || /[\s]/.test(large) || /[\s]/.test(small)) {
        return json(422, { detail: { code: 'invalid_request', message: '模型名不合法', request_id: 'mock-l' } });
      }
      if (large === body.override.model_large && small === body.override.model_small) {
        return json(200, { changed: false, message: '与当前生效的两个档位相同，没有改动', state: body });
      }
      const missing = [...new Set([large, small])]
        .map(entryFor)
        .filter((src) => src && !src.key_configured)
        .map((src) => `${src.provider_display}（环境变量 ${src.key_env_var}）`);
      if (missing.length) {
        calls.rejected.push(missing.join('；'));
        return json(422, {
          detail: {
            code: 'invalid_request',
            message: `这几家还没有配 API Key：${missing.join('；')}。写进 .env 后重启后端即可（本面板不接收 Key，也不会改写 .env）`,
            request_id: 'mock-l',
          },
        });
      }
      rebuild(large, small);
      return json(200, {
        changed: true,
        message: '已对**之后新建的任务**生效；在途任务仍按原来的模型记账。这是进程内覆盖，后端重启后回落到 .env',
        state: body,
      });
    },
    /** DELETE /api/models/override（幂等） */
    del: () => {
      const had = body.override.source === 'override';
      if (had) rebuild(options.originalLarge || 'deepseek-flash', options.originalSmall || 'deepseek-flash');
      if (had) body.override = { ...clone(baseBody.override), version };
      return json(200, {
        changed: had,
        message: had ? '已回落到 .env 里的那两档；之后新建的任务按 .env 走' : '本来就没有覆盖在生效，没有改动',
        state: body,
      });
    },
    /* ---------- 下面两支是 AE 趟（面板收 Key）的桩 ----------
       与后端同形的三件事：①空串 = 撤回、回落到"环境变量那份"；②填进去之后
       ``providers[]`` 那一条的四个字段要一起变（不是只翻 ``key_configured`` 一位）；
       ③校验**不改变任何状态**。桩不照做这三条，AE 的判据就没有对手 ——
       它会去断言"界面自己算的那份状态对不对"，而那份状态根本不存在于响应里。 */
    /** POST /api/models/key */
    postKey: (payload) => {
      calls.key.push({ provider: payload.provider, key: payload.api_key });
      const p = body.providers.find((row) => row.provider === payload.provider);
      if (!p) {
        return json(422, {
          detail: { code: 'invalid_request', message: `未知的供应商「${payload.provider}」`, request_id: 'mock-k' },
        });
      }
      const raw = String(payload.api_key || '');
      // 后端拒控制字符（那串值要进 HTTP 头）：桩拒慢一步，AE-7b 那条哨兵就会假绿
      if (/[\u0000-\u001f]/.test(raw)) {
        return json(422, {
          detail: { code: 'invalid_request', message: 'Key 含换行或控制字符，已拒绝', request_id: 'mock-k' },
        });
      }
      const had = runtimeKeys[p.provider] !== undefined;
      const changed = raw ? !had || runtimeKeys[p.provider] !== raw : had;
      if (raw) runtimeKeys[p.provider] = raw;
      else delete runtimeKeys[p.provider];
      paintKeyView(p);
      return json(200, {
        changed,
        message: raw
          ? `Key 已放进本次进程（${p.own_key_env_var}）：只影响之后新建的任务，重启后回落到 .env`
          : had
            ? `已撤掉本次进程里填的那把，${p.own_key_env_var} 回落到环境变量`
            : '这一家本来就没有面板填的 Key，没有改动',
        state: body,
      });
    },
    /** POST /api/models/key/validate —— 三分支由 Key 前缀选，**不碰任何状态**。
     *
     * ⚠️ 桩里这几个数与后端真值刻意错开：``timeout_s`` 给 **4.5**（后端是 3.0）、
     * 模型条数给 7、耗时给 123。界面那句"超时上限"要是印出 3，就说明它在写死而不是读响应；
     * 印出 4.5 才证明这条链接通了（同一形状的哨兵见 AD-56b）。 */
    validateKey: (payload) => {
      const raw = String(payload.api_key || '');
      const p = body.providers.find((row) => row.provider === payload.provider) || {};
      const base = {
        provider: payload.provider,
        base_url: p.base_url ?? '',
        model_count: null,
        latency_ms: 123,
        timeout_s: 4.5,
      };
      if (raw.startsWith('sk-AEOK')) {
        return json(200, { ...base, ok: true, http_status: 200, model_count: 7, detail: '鉴权通过，端点报出 7 个模型' });
      }
      if (raw.startsWith('sk-AESLOW')) {
        return json(200, {
          ...base, ok: false, http_status: null,
          detail: '校验超时（4.5 秒），请检查网络或该家的 base_url',
        });
      }
      return json(200, {
        ...base, ok: false, http_status: 401,
        detail: 'HTTP 401：{"error":{"code":"1002","message":"Wrong API key"}}',
      });
    },
  };
}

/* ``GET /tasks/{id}/cost-breakdown`` 的桩（AA 趟）。
 *
 * 这份 fixture 是**故意长成这样**的，四条断言各要吃一处：
 *  - planner 出**两行**（×1.0 与 ×0.5）→ AA-4「跨峰谷不许折成一行」；
 *  - 其中一行 ``model: null`` / 系数 null → AA-3「历史任务不说谎」，
 *    且 ``role_map`` 里那个哨兵串（'某没配过价的模型'）必须**不出现**在面板上；
 *  - ``events_cost`` 与 ``task_cost`` 差 4.3e-7（真实库里 round(…,6) 造成的量级）
 *    → AA-1「三个读数在页面上仍然对齐」，用 4 位展示的口径判；
 *  - ``next_off_peak_at`` 是可改的桩值 → AA-6「前端不许自己算时间」。
 * ⚠️ route 回调里现取 JSON.stringify(costBody)：趟内改完字段，下一次请求就是新值。 */
const costBody = {
  task_id: TASK_ID,
  generated_at: '2026-09-26T15:04:05+08:00',
  totals: { calls: 5, tokens_in: 2507, tokens_out: 390, cost: 0.00939543 },
  by_role: [
    {
      role: 'planner', model: 'deepseek-flash', price_multiplier: 1.0, peak: true,
      calls: 1, tokens_in: 392, tokens_out: 137, cost: 0.0020022,
      unit_price_in: 2.13, unit_price_out: 8.52, price_source: 'official_table',
    },
    {
      role: 'planner', model: 'deepseek-flash', price_multiplier: 0.5, peak: false,
      calls: 1, tokens_in: 392, tokens_out: 68, cost: 0.00070716,
      unit_price_in: 2.13, unit_price_out: 8.52, price_source: 'official_table',
    },
    {
      role: 'executor', model: 'deepseek-flash', price_multiplier: 1.0, peak: true,
      calls: 2, tokens_in: 1000, tokens_out: 67, cost: 0.00270084,
      unit_price_in: 2.13, unit_price_out: 8.52, price_source: 'official_table',
    },
    /* 两列落地之前的历史行：钱在、模型与档位都不在 */
    {
      role: 'reviewer', model: null, price_multiplier: null, peak: null,
      calls: 1, tokens_in: 723, tokens_out: 118, cost: 0.00398523,
      unit_price_in: null, unit_price_out: null, price_source: 'unknown',
    },
  ],
  window: {
    is_peak_now: true,
    multiplier_now: 1.0,
    next_off_peak_at: '2026-09-26T18:00:00+08:00',
    window_desc: '周一至周五 09:00-12:00、14:00-18:00（北京时间）',
  },
  price_check: {
    ok: true, max_delta_pct: 0.012, implied_price_in: 2.1303, implied_price_out: 8.5191,
    equations: 3, reason: null,
  },
  reconcile: {
    events_cost: 0.00939543, task_cost: 0.009395, all_equal: true, note: '',
  },
};

/* 知识库（/knowledge）的三份文档 + 概览。Z 趟会**直接改这个对象**再让页面重取，
   所以路由的 handler 必须是"每次请求现读"，不能是注册时算好的字符串。
   字段与 src/types.ts 的 DocumentView / KnowledgeOverview 逐字对齐（后端 to_cn 之后
   的时间形态：带 +08:00 的 ISO 串）。 */
const kbState = {
  overview: {
    document_count: 3,
    chunk_count: 12,
    token_count: 5210,
    ready_count: 1,
    failed_count: 1,
    indexing_count: 1,
    fingerprint: 'sha256:probe-fingerprint',
    vector_backend: 'sqlite-vec',
    embedding_model: 'BAAI/bge-small-zh-v1.5',
    last_indexed_at: '2026-09-26T10:12:33+08:00',
    /* 故意**不填 50**：50 是 `config.py:209` 的默认上限，也就是"页面把数字写死了"时
       会印出来的那个数。fixture 的默认值撞上缺陷值 ⇒ 那条判据恒真（本轮自己踩到后改的）。
       33 这个数只在桩里存在，页面印 33 才证明它读的是响应。 */
    max_file_mb: 33,
    /* R-03：上传白名单也从这里给。**桩故意给四种**（多一个 docx），而页面曾经自带的那份是
       pdf/md/txt 三种 —— 桩值一旦等于"页面写死的那份"，"读接口"与"写死"就印出同一个字符串，
       那条判据从写下那天起恒真（同一支纪律见上面 33 那段）。
       后端真给的是 `sorted(DOC_SUPPORTED_FORMATS)`，所以这份也是排序后的形态。 */
    supported_formats: ['docx', 'md', 'pdf', 'txt'],
  },
  docs: [
    {
      document_id: 'doc-2b7c1e9a4d10',
      filename: '员工手册.md',
      size_bytes: 18432,
      format: 'md',
      status: 'ready',
      error_stage: null,
      error_message: null,
      chunk_count: 12,
      token_count: 5210,
      embedding_fingerprint: 'sha256:probe-fingerprint',
      created_at: '2026-09-26T10:12:05+08:00',
      updated_at: '2026-09-26T10:12:33+08:00',
      indexed_at: '2026-09-26T10:12:33+08:00',
    },
    {
      document_id: 'doc-7d3a55c1b092',
      filename: '消防疏散图说明.txt',
      size_bytes: 9216,
      format: 'txt',
      status: 'embedding',
      error_stage: null,
      error_message: null,
      chunk_count: 0,
      token_count: 0,
      embedding_fingerprint: '',
      created_at: '2026-09-26T10:20:01+08:00',
      updated_at: '2026-09-26T10:20:44+08:00',
      indexed_at: null,
    },
    {
      document_id: 'doc-54a7a41c0564',
      filename: '机房巡检规程.md',
      size_bytes: 30210,
      format: 'md',
      status: 'failed',
      error_stage: 'embedding',
      error_message: '向量化在第 3 批超时（探针桩，不是真故障）',
      chunk_count: 0,
      token_count: 0,
      embedding_fingerprint: '',
      created_at: '2026-09-26T09:58:12+08:00',
      updated_at: '2026-09-26T09:59:02+08:00',
      indexed_at: null,
    },
  ],
};

const kbJson = (obj, status) => ({
  status: status || 200,
  contentType: 'application/json',
  body: JSON.stringify(obj),
});

/* ---------------------------------------------------------------------------
   GET /api/config/agent-options —— 运行配置面板的唯一数据来源。

   骨架抄自本机 ``TestClient(app).get('/config/agent-options')`` 的**真实响应**
   （2026-09-26 20:08，本轮按 §2.1 对账后又补了 ``unit`` 与 ``review_threshold``），
   但下列几处**故意不同**，为的是让判据可证伪：
   · ``defaults.max_iterations`` = 6（后端 5，退役的那版前端写死 3）——
     桩值若等于后端值，"界面显示的是响应给的那个数"这条断言就恒真；
   · ``defaults.review_threshold`` = 8（后端 7，而前端上一版连这一栏都没有）；
   · ``defaults.rag_top_k`` = 7（后端 5）；
   · 三档预设的轮数/预算也都与后端不同（后端 2/3/10 轮、¥0.07/0.35/3.55）；
   · ``limits.timeout_s`` = 15..1800 步长 15（后端 30..3600 步长 30）——
     ⚠️ 这里曾经是 ``max: 3600``，**恰好等于本轮改成的后端上界** ⇒ "输入框的界跟着响应走"
     那条断言当场变成恒真（桩与真值撞车）。凡是用来当证据的桩值都必须与后端不同，
     这条是本轮对账时抓出来的第二处（第一处是 ``defaults`` 那个 7）。
   · ``limits.review_threshold`` = 0..12（后端 0..10）—— 同一族撞车的第三处，本轮对账时
     逐键比对 ``RUN_CONFIG_LIMITS`` 才抓到：这一栏是**新加的行**，桩照抄后端表最不容易被发现，
     因为没有任何"前端旧默认"会跟它对不上。⚠️ 记一笔口径边界：AD 今天**没有**读那五个界
     （数值行只测"控件在不在 + 读数与后缀是不是响应给的"），所以这条撞车还不是死判据；
     将来谁加"界跟着响应走"的判据，读的是 ``aria-valuemin`` / ``aria-valuemax``
     （rc-input-number **不给 input 写 HTML ``max`` 属性**，grep `max=` 会一无所获），
     届时这条桩值必须先错开 —— 已经错开了。
   · 唯一还**留着的**巧合：``max_cost_cny.step`` 桩与后端都是 0.01 ⇒ "小数位取自 step"
     这一条现在不可证伪（把界面的 ``decimalsOf(step)`` 改回旧的 ``key === 'max_cost_cny' ? 2 : 0``
     探针不会红）。没顺手改是因为改 step 会连带把预设值 ¥6.66 显示成 ¥6.7、把 AD-03 一起牵动，
     而那是"预设值来自响应"的判据，与小数位是两件事 —— 要加就单独加一条。
   · ``fields[].unit`` 与 ``label`` 也一律换个说法（轮→次、元→块钱、条→篇、分→档）——
     界面后缀/字段名只要露出"次/块钱/篇/档"，就证明它读的是响应，不是自己那张表。
   与 Z 趟的白名单桩同一口径：**桩里独有的值，就是判据的证据**。
   --------------------------------------------------------------------------- */
const agentOptionsBody = {
  schema_version: 1,
  defaults: {
    max_iterations: 6,
    review_threshold: 8,
    rag_top_k: 7,
    max_cost_cny: null,
    timeout_s: null,
    use_tools: true,
    enabled_tools: null,
  },
  limits: {
    max_iterations: { min: 1, max: 12, step: 1 },
    review_threshold: { min: 0, max: 10, step: 1 },
    rag_top_k: { min: 1, max: 24, step: 1 },
    max_cost_cny: { min: 0.01, max: 1000, step: 0.01 },
    timeout_s: { min: 15, max: 1800, step: 15 },
  },
  presets: [
    { id: 'fast', label: '快速模式', values: { max_iterations: 1, max_cost_cny: 0.13 }, note: '迭代 1 轮 · 预算 ¥0.13（桩值，非后端值）' },
    { id: 'standard', label: '标准模式', values: { max_iterations: 4, max_cost_cny: 0.66 }, note: '迭代 4 轮 · 预算 ¥0.66' },
    { id: 'deep', label: '深度模式', values: { max_iterations: 9, max_cost_cny: 6.66, timeout_s: 900 }, note: '迭代 9 轮 · 预算 ¥6.66 · 超时 900 秒' },
  ],
  fields: [
    { key: 'max_iterations', label: '迭代上限（桩词）', kind: 'int', unit: '次', accepted: true, enforced: true, help: '到上限时 reviewer 会把任务收口成 aborted（不是失败）' },
    { key: 'review_threshold', label: '评审通过分数线', kind: 'int', unit: '档', accepted: true, enforced: true, help: '桩值措辞：Reviewer 给分低于这条线就退回 Executor' },
    { key: 'max_cost_cny', label: '成本预算上限（桩词）', kind: 'money', unit: '块钱', accepted: true, enforced: true, help: '节点之间才检查：最长可能再等一次完整 LLM 调用（120 秒 × 重试次数）才会中断' },
    { key: 'timeout_s', label: '超时上限（桩词）', kind: 'duration', unit: '秒钟', accepted: true, enforced: true, help: '节点之间才检查：最长可能再等一次完整 LLM 调用（120 秒 × 重试次数）才会中断' },
    { key: 'rag_top_k', label: '检索条数上限（桩词）', kind: 'int', unit: '篇', accepted: true, enforced: true, help: '是上限：模型自己要得更少时尊重模型' },
    { key: 'use_tools', label: '允许调用工具', kind: 'bool', unit: null, accepted: true, enforced: true, help: 'false 时后端装配低风险安全子集' },
    { key: 'enabled_tools', label: '工具白名单', kind: 'select', unit: null, accepted: true, enforced: true, help: '优先级高于 use_tools；不传=全量' },
    { key: 'reviewer_enabled', label: '是否启用评审节点（Reviewer）', kind: 'bool', unit: null, accepted: false, enforced: false, help: '后端没有这个开关：reviewer 是编排图里的固定节点，循环的出口条件就是它的结论' },
  ],
  models: {
    editable_here: false,
    entry_point: '顶栏右上角齿轮 → 模型设置',
    /* 五个编排角色 —— 与后端 ``role_map`` 的条数一致（planner/reviewer/judge 走大档，
       executor/extract 走小档）。原来这里只放两条，于是"两列网格排下来是几行"
       在探针里从来没被量过（两条 = 一行，看不出列数）。 */
    roles: [
      { role: 'planner', tier: 'large', model: 'deepseek-flash', source: 'env' },
      { role: 'reviewer', tier: 'large', model: 'deepseek-flash', source: 'env' },
      { role: 'judge', tier: 'large', model: 'deepseek-flash', source: 'env' },
      { role: 'executor', tier: 'small', model: 'deepseek-flash', source: 'env' },
      { role: 'extract', tier: 'small', model: 'deepseek-flash', source: 'env' },
    ],
  },
  tools: { source: '/tools', default_enabled: null, rag_tool: 'knowledge_search' },
  currency: 'CNY',
  pricing_basis: '全站成本一律是人民币元；DeepSeek 的美元标价按 1 USD = 7.1 元折算、取高峰价',
};

/* 三个场景变体都从这份基线深拷，避免互相改脏（Z 趟的 kbState 同一教训）。 */
function agentOptionsVariants() {
  const base = JSON.parse(JSON.stringify(agentOptionsBody));
  /* 老后端：只给 defaults/limits，没有 presets、没有 tools.rag_tool、
     并且 timeout_s 不在 fields 里（声明都没声明）⇒ 界面既不能凭空出下拉，
     也不能凭空出输入框。 */
  const legacy = JSON.parse(JSON.stringify(base));
  delete legacy.presets;
  delete legacy.tools.rag_tool;
  legacy.fields = legacy.fields.filter((f) => f.key !== 'timeout_s');
  /* 后端比这一版界面新：多一个顶层键、多一个不认识的 kind、多一个"有界没声明"的键，
     还多一个**声明能配但前端没有行**的数值键（eval_seed）。
     四条都要原样露出来 —— 静默隐藏等于让下一个人以为前端漏做了。 */
  const future = JSON.parse(JSON.stringify(base));
  future.planner_hint = { temperature: 0.2, note: '后端新增，界面这一版没控件' };
  future.fields = future.fields.concat([
    { key: 'use_tools', label: '允许调用工具', kind: 'bool', unit: null, accepted: true, enforced: true, help: '' },
    { key: 'sandbox_profile', label: '沙箱档位', kind: 'segmented', unit: null, accepted: true, enforced: true, help: '新控件类型' },
    { key: 'eval_seed', label: '评测随机种子', kind: 'int', unit: '粒', accepted: true, enforced: true, help: '后端说能配，但这一版界面没有这一行' },
  ]);
  future.limits.eval_seed = { min: 0, max: 99, step: 1 };
  /* ⚠️ 契约要点 1 的**第二半**只有在这一档才测得出来：``accepted=true`` 而
     ``enforced=false`` —— 值收得下、发得出、界面一切正常，**只有后端不执行**。
     后端今天的八条声明里没有一条是这一档（本轮对账逐条核过 ``_fields()``），
     所以这是**假后端**，不是"后端将来会这样"的预言；给它的目的只有一个：
     让"控件仍在 + help 以正文在场 + 行内单独警告 + 底部点名 + 真的发出去了"这五件
     有地方一起量。挑 ``rag_top_k`` 是因为它已经有行（不需要动界面那张行表），
     而这一档里没有任何判据读它的值。 */
  const softRow = future.fields.find((f) => f.key === 'rag_top_k');
  softRow.enforced = false;
  softRow.help = '桩：这一版后端收了 rag_top_k，但检索没有用它（改了不会改变运行行为）';
  /* 「角色模型映射」那一栏的**另一种形状**：五档里有一档是本进程覆盖的。
     base 那份五条全是 ``env`` ⇒ 界面把来源并成标题旁一句小字，
     而"逐行 Tag"那一支就永远没有东西可量 —— 混档才是那一支的成立条件。
     ⚠️ 这一档**只**给那一处判据用（AD-74），别把它当"后端将来会这样"的预言：
     后端今天真的会混（``override.model_large`` 生效而小档仍来自 .env 的那一刻就是这样）。 */
  const mixed = JSON.parse(JSON.stringify(base));
  mixed.models.roles[1].source = 'override';
  mixed.models.roles[1].model = 'deepseek-v4-pro';
  return { base, legacy, future, mixed };
}

/** 提交桩：**有状态**，把每一次 POST /api/tasks 的请求体记下来，并按后端的规矩回一份
 *  ``run_config``（含 extra=ignore 的那一类静默丢弃 —— 见 ``oldAck``）。
 *
 * 为什么必须回 ack：``submitTask`` 拿不到 task_id 会直接进失败分支，后面的判据全空。
 * 为什么必须记 body：这一整轮改造的验收口径是"界面说的 == 发出去的 == 服务端收下的"，
 * 三件事只有在 body 与回执上才量得到。 */
function createSubmitMock(options = {}) {
  const state = { bodies: [], acks: 0 };
  const handler = async (route) => {
    const req = route.request();
    if (req.method() !== 'POST') return route.continue();
    let body = {};
    try {
      body = JSON.parse(req.postData() || '{}');
    } catch {
      body = null;
    }
    state.bodies.push(body);
    /* 422 档：模拟"值越界被后端挡回来"，信封与 api/errors.py 的 error_body 同形
       （detail.code / detail.message / detail.request_id），界面必须原样落到实时日志区。 */
    if (options.always422) {
      return route.fulfill(
        kbJson(
          {
            detail: {
              code: 'invalid_request',
              message: 'max_cost_cny: Input should be less than or equal to 1000；timeout_s: 必须 ≥ 10',
              request_id: 'req-ad-422',
            },
          },
          422,
        ),
      );
    }
    const id = `task-AD-${state.acks}`;
    state.acks += 1;
    /* ``clampIterations``：模拟"值收下了，但服务端按自己那一版上限钳过"（8 ⇒ 4）。
       这一档存在的目的是**证伪"界面只按自己发出去的那份显示"**：前端如果照着自己那份说，
       判据就抓不到；必须读回执，才说得出"实际用的是 4"。 */
    const echoIterations = () => {
      const raw = body?.max_iterations;
      if (typeof raw !== 'number') return agentOptionsBody.defaults.max_iterations;
      return options.clampIterations ? Math.min(raw, 4) : raw;
    };
    if (options.oldAck) {
      // 没重启的后端：回执里根本没有 run_config ⇒ 界面只能说"未回报"，不许自证
      return route.fulfill(
        kbJson(
          {
            task_id: id,
            status: 'queued',
            queue_position: null,
            submitted_at: new Date().toISOString(),
            stream_url: `/tasks/${id}/stream`,
            poll_url: `/tasks/${id}`,
            cancel_url: `/tasks/${id}/cancel`,
            estimated_cost_cny: 0.0042,
            peak_pricing: false,
            warnings: null,
          },
          201,
        ),
      );
    }
    return route.fulfill(
      kbJson(
        {
          task_id: id,
          status: 'queued',
          queue_position: null,
          submitted_at: new Date().toISOString(),
          stream_url: `/tasks/${id}/stream`,
          poll_url: `/tasks/${id}`,
          cancel_url: `/tasks/${id}/cancel`,
          estimated_cost_cny: 0.0042,
          peak_pricing: false,
          warnings: null,
          run_config: {
            // 服务端"最终采用"的轮数：没发就报自己的默认（桩里那份 = 6，与前端无关）
            max_iterations: echoIterations(),
            max_cost_cny: body?.max_cost_cny ?? null,
            timeout_s: body?.timeout_s ?? null,
            rag_top_k: body?.rag_top_k ?? null,
            use_tools: body?.use_tools ?? null,
            enabled_tools: body?.enabled_tools ?? null,
          },
        },
        201,
      ),
    );
  };
  return { state, handler };
}

/** 覆盖 ``GET /api/config/agent-options`` 的返回形态。
 *  ``body === null`` ⇒ 回 **404**（``not_found`` 信封，与 api/errors.py 同形）——
 *  那一档模拟的是"后端进程还是旧版，这个端点根本没注册"，
 *  与"端点在但回了一份空对象"必须是两种回法：界面对前者的义务是整块降级，
 *  对后者的义务是把缺的控件一条条不画。 */
async function installAgentOptions(page, body) {
  if (body === null) {
    await page.route('**/api/config/agent-options', (r) =>
      r.fulfill(
        kbJson(
          { detail: { code: 'not_found', message: 'Not Found', request_id: 'req-ad-404' } },
          404,
        ),
      ),
    );
    return;
  }
  await page.route('**/api/config/agent-options', (r) => r.fulfill(kbJson(body)));
}

/* 场景要改 kbState，所以必须有一份"出厂快照"能退回，否则上一个场景改剩的状态会
   悄悄流进下一个场景 —— 那类串味最难查（页面看着对，其实是上一份数据）。 */
const KB_BASE = JSON.parse(JSON.stringify(kbState));

function resetKb() {
  kbState.overview = JSON.parse(JSON.stringify(KB_BASE.overview));
  kbState.docs = JSON.parse(JSON.stringify(KB_BASE.docs));
  return kbState;
}

async function installMocks(page) {
  await page.route('**/api/health', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(healthBody) }));
  await page.route('**/api/tools', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(toolsBody) }));
  /* 模型注册表默认给「本机 .env 的真实形态」；G 趟会**再注册一次**这条路由来换形态
     （Playwright 后注册的 route 吃掉前一条 —— 同一形状也用于 /api/tasks/* 的分派） */
  await page.route('**/api/models', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modelsBody) }));
  /* 运行配置面板的数据源。默认给**完整**那一份（否则每一趟的 .cp-hint 读数都会消失、
     面板整块降级，别的趟会莫名其妙跟着红）。AD 趟按场景**再注册一次**同名路由换形态 ——
     后注册的先匹配，与 /api/models、/api/knowledge 那两个的玩法一致。 */
  await page.route('**/api/config/agent-options', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(agentOptionsBody) }));
  await page.route('**/api/tasks?*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: tasks, total: tasks.length, limit: 12, offset: 0 }) }));
  await page.route('**/api/eval/retrieval-report', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(retrievalBody) }));
  await page.route('**/api/eval/ablation-report', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ablationBody) }));
  await page.route('**/api/tasks/*/trace*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(traceBody) }));
  // 成本端点：每次请求现取 costBody，AA 趟改完字段立刻生效（同 traceBody 的做法）。
  // ⚠️ 注释里别写 glob —— 上一版这条写成块注释，里面的 `**/api/tasks/` 自带一个 `*/`，
  //    把块注释就地闭合，剩下的中文变成代码，报错是「api is not defined」（本文件实测踩过）。
  await page.route('**/api/tasks/*/cost-breakdown', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(costBody) }));
  await page.route('**/sse/tasks/*/*', (r) =>
    r.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' }, body: sseFrames() }));
  await page.route('**/api/tasks/*/cancel', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/tasks', (r) =>
    r.fulfill({
      status: 201, contentType: 'application/json',
      body: JSON.stringify({
        task_id: TASK_ID, status: 'queued', stream_url: `/tasks/${TASK_ID}/stream`,
        poll_url: `/tasks/${TASK_ID}`, cancel_url: `/tasks/${TASK_ID}/cancel`,
        queue_position: null, submitted_at: new Date().toISOString(), estimated_cost_cny: 0.0042, warnings: null,
      }),
    }));
  await page.route('**/api/tasks/*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) }));
  // 知识库三条。Z 趟按场景**再注册一次**同名路由换掉 POST/DELETE 的行为（后注册的先匹配）。
  await page.route('**/api/knowledge/overview', (r) => r.fulfill(kbJson(kbState.overview)));
  await page.route('**/api/knowledge/documents', (r) => {
    if (r.request().method() === 'POST') {
      /* 后端那一侧的格式判定照做（`rag/service.py:ingest`）：扩展名不在白名单 ⇒ 422
         ``unsupported_format``，而 message 里列的就是**同一份**清单。
         桩不照做的话，"页面读不到白名单就**不本地拦**、交给后端说话"那条判据没有对手，
         写不出能红的一版。字段被场景删掉时退回工作区那份常量（三种）—— 那档模拟的是
         "老进程压根不发这个字段"，后端自己的清单仍然是三种。 */
      const raw = String(r.request().postData() || '');
      const name = (raw.match(/filename="([^"]*)"/) || [])[1] || 'unnamed';
      const ext = (name.split('.').pop() || '').toLowerCase();
      const allow = kbState.overview.supported_formats || ['md', 'pdf', 'txt'];
      if (!allow.includes(ext)) {
        return r.fulfill(
          kbJson(
            {
              detail: {
                code: 'unsupported_format',
                message: `不支持的文档格式：.${ext}（白名单：${allow.join('/')}）`,
                request_id: 'req-kb-probe',
              },
            },
            422,
          ),
        );
      }
      return r.fulfill(
        kbJson({
          document_id: 'doc-newupload0001',
          filename: '新上传.md',
          status: 'pending',
          upload_at: '2026-09-26T10:31:00+08:00',
          status_url: '/knowledge/documents/doc-newupload0001',
          warnings: [],
        }, 201),
      );
    }
    return r.fulfill(kbJson({ items: kbState.docs, total: kbState.docs.length }));
  });
  /* ⚠️ 这里必须是 `**` 而不是 `*`：Playwright 的通配里 `*` **不跨斜杠**，
     `/documents/{id}` 能命中，`/documents/{id}/retry` 命不中 —— 症状是"重试按钮点了没反应"，
     而请求其实悄悄打到了 vite 代理后面的真 :8001（本机后端在跑时会拿到一个 404）。
     同一族坑在 Z 趟的路由注释里记着（`documents*` 要带尾星才盖得住 `?overwrite=true`）。 */
  await page.route('**/api/knowledge/documents/**', (r) => {
    const path = new URL(r.request().url()).pathname;
    if (r.request().method() === 'DELETE') {
      const id = path.split('/').pop();
      // 真的把那行从"库"里摘掉：后端是物理删（KB-01），只回执不摘行会让"删完之后列表跟着少一行"
      // 这种断言永远写不了，而页面自己也不会错 —— 假的是 fixture。
      kbState.docs = kbState.docs.filter((d) => d.document_id !== id);
      return r.fulfill(kbJson({ document_id: id, deleted: true }));
    }
    if (path.endsWith('/retry')) {
      const id = path.split('/').slice(-2, -1)[0];
      const doc = kbState.docs.find((d) => d.document_id === id);
      /* 后端 `retry` 的语义是 `failed → pending`、`error_*` 清空、从解析全量重跑
         （`api/routes/knowledge.py` 的 retry 路由）。这里照做，Z 趟才能断言
         "那一行真的回到了第一段"，而不是只数了一个请求。 */
      if (doc) {
        doc.status = 'pending';
        doc.error_stage = null;
        doc.error_message = null;
        doc.indexed_at = null;
      }
      return r.fulfill(kbJson({ document_id: id, status: 'pending', queued: true }));
    }
    const one = kbState.docs.find((d) => path.endsWith(d.document_id));
    return one ? r.fulfill(kbJson(one)) : r.fulfill(kbJson({ detail: { code: 'document_not_found', message: '文档不存在', request_id: 'req-kb-404' } }, 404));
  });
}

module.exports = {
  installMocks,
  installAgentOptions,
  agentOptionsBody,
  agentOptionsVariants,
  createSubmitMock,
  toolsBody,
  TASK_ID,
  detail,
  traceBody,
  tasks,
  modelsBody,
  modelsBodyTwoTiers,
  modelsBodyFallback,
  modelsBodyWithCatalog,
  createModelOverrideMock,
  costBody,
  healthBody,
  kbState,
  kbJson,
  resetKb,
};
