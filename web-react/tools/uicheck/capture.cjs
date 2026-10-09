/* 视觉验收：用 Playwright 拦截 /api 与 /sse，喂真实结构的假数据，
   在不改源码、不起后端的前提下把三页的所有状态渲染出来截图。
   目的：验证布局 / 层级 / 明暗主题 / 双端适配，而不是验证后端。 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
// 截图输出目录：优先读环境变量；回退到脚本同目录下的相对路径
const OUT = process.env.OUT_DIR || path.join(__dirname, 'shots');

const TASK_ID = 'task-3f9a1c02be11';

const tasks = Array.from({ length: 8 }).map((_, i) => ({
  task_id: `task-${(0x3f9a1c02be11 + i * 9973).toString(16)}`,
  task: [
    '用三句话说明 RAG 的检索增强原理，并指出结论来自哪份文档',
    '1024 路摄像头整机功耗怎么估算？给出算式与结果',
    '对比 BM25 与向量检索在中文技术文档场景下的适用边界',
    '门禁一卡通系统选型要注意哪些供电与协议细节',
    '机房工程 UPS 容量按什么口径估算',
    '综合布线里六类线与超六类的成本差在哪',
    '广播系统分区与功放功率怎么配比',
    '安防监控球机 PoE+ 与 PoE 的供电差异',
  ][i],
  status: ['done', 'running', 'failed', 'aborted', 'queued', 'done', 'done', 'canceled'][i],
  created_at: new Date(Date.now() - i * 7 * 60 * 1000).toISOString(),
}));

const detail = {
  task_id: TASK_ID,
  task: tasks[0].task,
  status: 'done',
  final_answer:
    '按 IEEE 802.3af 标准，单端口 PoE 最大输出 15.4W；球机等大功率设备走 802.3at（PoE+），单端口 30W。\n' +
    '按 1024 路 × 0.85 并发系数 × 17.5W 估算，整机功耗约 15230.75W。\n\n' +
    '其中 0.85 为同时在线并发系数，17.5W 为单路整机均值（含编码与网络开销）。',
  error: null,
  difficulty: 'medium',
  grade: 'B',
  score: 8,
  iterations: 2,
  progress: null,
  queue: null,
  tool_calls: 3,
  tool_failures: 1,
  cost: 0.0042,
  duration_ms: 9230,
  created_at: new Date(Date.now() - 8 * 60 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

/** ⚠️ 这份内联 fixture 与 mocks.cjs 重复；`arguments` 必须按**线上形态给 object**
 *  （设计文档 §6.2，后端 TaskEventView 反序列化成 dict）。之前三处工具事件写成
 *  预串化字符串，正好绕过「object 进 <pre> 白屏」那条路径（2026-09-23 实测复发）。
 *  改一处记得两处一起改。 */
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
    observation: '命中 4 个 chunk：anfangjiankong.md#c12（0.83）、#c31（0.71）、#c58（0.66）、#c77（0.52）',
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
];

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
    questions: 70, corpus_docs: 1000,
    arms: {}, failed_arms: ['arm_no_rerank'],
    significance: { note: '未做显著性检验：5 臂 × 70 题撑不起统计功效，仅报绝对提升 Δ 与相对提升。' },
  },
  arms: [
    { arm_id: 'arm_baseline', n_used: 70, ndcg_at_k: 0.7124, mrr_at_k: 0.6801, hit_at_k: 0.8857, baseline_ndcg_at_k: 0.7124, delta_ndcg_at_k: 0, rel_lift_ndcg_at_k: 0, delta_mrr_at_k: 0, rel_lift_mrr_at_k: 0 },
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
  const push = (seq, node, update, status) => {
    frames.push(`event: node\ndata: ${JSON.stringify({ seq, node, update, status, ts: new Date().toISOString() })}\n\n`);
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

async function installMocks(page) {
  await page.route('**/api/health', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(healthBody) }));
  await page.route('**/api/tasks?*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: tasks, total: tasks.length, limit: 12, offset: 0 }) }));
  await page.route('**/api/eval/retrieval-report', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(retrievalBody) }));
  await page.route('**/api/eval/ablation-report', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ablationBody) }));
  await page.route('**/api/tasks/*/trace*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(traceBody) }));
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
}

async function shot(page, name) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log('  ✓', name);
}

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });

  const cases = [
    { name: 'desktop-light', viewport: { width: 1440, height: 900 }, scheme: 'light' },
    { name: 'mobile-light', viewport: { width: 390, height: 844 }, scheme: 'light', mobile: true },
    { name: 'desktop-dark', viewport: { width: 1440, height: 900 }, scheme: 'dark' },
  ];

  for (const c of cases) {
    console.log(`\n== ${c.name} ==`);
    const ctx = await browser.newContext({
      viewport: c.viewport,
      colorScheme: c.scheme,
      deviceScaleFactor: c.mobile ? 2 : 1,
      isMobile: !!c.mobile,
      hasTouch: !!c.mobile,
      locale: 'zh-CN',
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => console.log('  [pageerror]', e.message));
    await installMocks(page);

    // 页①：提交前（空态）
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    await shot(page, `${c.name}-1a-tasks-empty`);

    // 页①：提交后（实时日志 + 结果）
    // ⚠️ 已知限制（2026-09-23 登记，先于当轮 trace.arguments 归一化改动）：
    // 示例按钮已进「配置」弹层、提交按钮改名「提交」，这两步对不上当前 UI，会 30s 超时。
    await page.getByRole('button', { name: '数值计算' }).click();
    await page.getByRole('button', { name: '提交任务' }).click();
    await page.waitForTimeout(2600);
    await shot(page, `${c.name}-1b-tasks-filled`);

    // 结果区各 tab
    for (const tab of ['引用来源', '工具调用', '消耗明细']) {
      const t = page.getByRole('tab', { name: new RegExp(`^${tab}`) });
      if (await t.count()) {
        await t.first().click();
        await page.waitForTimeout(320);
        await shot(page, `${c.name}-1c-tab-${tab}`);
      }
    }

    // 页②
    await page.goto(`${BASE}/trace?id=${TASK_ID}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(700);
    await shot(page, `${c.name}-2a-trace`);
    await page.getByRole('button', { name: '全部展开' }).click();
    await page.waitForTimeout(320);
    await shot(page, `${c.name}-2b-trace-expanded`);

    // 页③
    await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(900);
    await shot(page, `${c.name}-3-eval`);

    await ctx.close();
  }

  await browser.close();
  console.log('\nDONE →', OUT);
}

run().catch((e) => {
  console.error('FAILED:', e);
  process.exit(1);
});
