import type { LogEvent, TaskPhase, TaskRecord, TaskResult, TaskSubmitForm } from '../types';

/** Mock 数据源。
 *
 * 用途：任务 / 轨迹 / 评测三页在没有后端时也能完整跑通交互与布局。
 * 切到真实后端时，把 src/api/client.ts 的 `USE_MOCK` 改成 false 即可，
 * 页面代码一行都不用动（两边返回同一种类型）。
 *
 * ⚠️ 第四页「知识库」刻意不在 mock 覆盖范围内：它的核心就是"上传—索引"这条真实链路，
 * 假一份文档表反而会把"后端没起"演成"库里是空的"。要验这一页，走
 * `tools/uicheck/mocks.cjs` 的 `page.route`（Z 趟），那层拦的是网络、不是数据层。
 */



let seq = 0;

/** 生成一条任务 id，形如 task-<hex12>，与后端 api/routes/tasks.py 口径一致。 */
export function mockTaskId(): string {
  return `task-${Math.random().toString(16).slice(2, 14).padEnd(12, '0')}`;
}

/** 编排脚本：planner → executor（含工具调用）→ reviewer → 收口。
 *  节点与顺序对齐 core/workflow/graph.py 的 NODE_ORDER。 */
export const MOCK_SCRIPT: Array<{
  delayMs: number;
  level: LogEvent['level'];
  node: LogEvent['node'];
  message: string;
}> = [
  { delayMs: 0, level: 'info', node: 'system', message: '任务已受理，进入队列' },
  { delayMs: 400, level: 'info', node: 'system', message: '队列调度：开始执行（并发 1/4）' },
  { delayMs: 500, level: 'debug', node: 'planner', message: 'Planner 输入：解析任务目标与约束' },
  { delayMs: 900, level: 'info', node: 'planner', message: 'Planner 产出 3 步计划：检索 → 计算 → 复核' },
  { delayMs: 700, level: 'info', node: 'executor', message: 'Executor 第 1 步：调用 knowledge_search' },
  { delayMs: 1200, level: 'debug', node: 'executor', message: 'knowledge_search 命中 4 个 chunk，融合模式 rrf' },
  { delayMs: 800, level: 'info', node: 'executor', message: 'Executor 第 2 步：调用 calculator' },
  { delayMs: 600, level: 'warn', node: 'executor', message: 'calculator 结果精度不足，改用 code_exec 复核' },
  { delayMs: 900, level: 'info', node: 'executor', message: 'code_exec 返回：15230.75（耗时 412ms）' },
  { delayMs: 700, level: 'info', node: 'reviewer', message: 'Reviewer 评分 6/10：证据不足，退回 Executor' },
  { delayMs: 800, level: 'info', node: 'executor', message: 'Executor 第 2 轮：补检索 2 个 chunk' },
  { delayMs: 1100, level: 'info', node: 'reviewer', message: 'Reviewer 评分 8/10：通过，收口' },
  { delayMs: 500, level: 'info', node: 'system', message: '任务完成，轨迹已落库（trace 14 条事件）' },
];

/** 模拟 SSE 推送：按脚本间隔逐条吐日志，返回停止函数。
 *  真实实现见 src/api/client.ts 的 subscribeTaskStream（EventSource）。 */
export function startMockStream(
  onEvent: (event: LogEvent) => void,
  onDone: () => void,
  onPhase?: (phase: TaskPhase) => void,
): () => void {
  let index = 0;
  const timers: number[] = [];

  const schedule = () => {
    if (index >= MOCK_SCRIPT.length) {
      onPhase?.('done');
      timers.push(window.setTimeout(onDone, 300));
      return;
    }
    const step = MOCK_SCRIPT[index];
    timers.push(
      window.setTimeout(() => {
        seq += 1;
        // 与真实 SSE 对齐：任何一条帧都意味着任务已经在跑
        onPhase?.('running');
        onEvent({
          seq,
          ts: Date.now(),
          level: step.level,
          node: step.node,
          message: step.message,
        });
        index += 1;
        schedule();
      }, step.delayMs),
    );
  };

  schedule();
  return () => timers.forEach((t) => window.clearTimeout(t));
}

export function mockResult(form: TaskSubmitForm): TaskResult {
  /* ⚠️ 这里的 ``?? 5`` **不是**前端兜底默认值，而是"假后端"在模拟服务端行为：
     mock 这一档没有真的 ``GET /config/agent-options``，所以它得自己知道一份后端默认，
     就像真后端 ``TaskSubmitRequest`` 的字段默认那样。界面读的是响应给的数，不是这里。 */
  const toolsOn = form.config.use_tools !== false;
  const ragOn = !form.config.enabled_tools || form.config.enabled_tools.includes('knowledge_search');
  const maxIterations = form.config.max_iterations ?? 5;
  const toolCalls = toolsOn
    ? [
        {
          id: 'tc-1',
          name: 'knowledge_search',
          args: JSON.stringify({ query: form.task.slice(0, 24), top_k: 5, fusion: 'rrf' }, null, 2),
          result: '命中 4 个 chunk：anfangjiankong.md#c12（0.83）、#c31（0.71）…',
          durationMs: 312,
          status: 'success' as const,
          thought: '先查知识库里 PoE 供电标准的原文段落。',
        },
        {
          id: 'tc-2',
          name: 'calculator',
          args: JSON.stringify({ expression: '1024 * 0.85 * 17.5' }, null, 2),
          result: '15232.0',
          durationMs: 41,
          status: 'success' as const,
          thought: '用计算器先估一遍，再决定要不要 code_exec 复核。',
        },
        {
          id: 'tc-3',
          name: 'code_exec',
          args: JSON.stringify({ code: 'round(1024 * 0.85 * 17.5, 2)', timeout_s: 3 }, null, 2),
          result: '15230.75',
          durationMs: 412,
          status: 'success' as const,
          thought: null,
        },
      ]
    : [];

  const citations = ragOn
    ? [
        {
          chunkId: 'c12',
          document: 'anfangjiankong.md',
          score: 0.83,
          snippet: '…POE 供电遵循 IEEE 802.3af 标准，单端口最大输出功率 15.4W…',
        },
        {
          chunkId: 'c31',
          document: 'anfangjiankong.md',
          score: 0.71,
          snippet: '…球机等大功率设备应采用 802.3at（PoE+），单端口 30W…',
        },
      ]
    : [];

  return {
    finalAnswer:
      '按 IEEE 802.3af 标准，单端口 POE 最大输出 15.4W；球机等大功率设备走 802.3at（PoE+），单端口 30W。' +
      '按 1024 路 × 0.85 并发系数 × 17.5W 估算，整机功耗约 15230.75W。',
    citations,
    toolCalls,
    usage: { prompt: 1842, completion: 356, total: 2198 },
    durationMs: 9230,
    iterations: maxIterations > 2 ? 2 : 1,
  };
}

export function mockRecord(form: TaskSubmitForm): TaskRecord {
  /* ⚠️ 这里是**假后端**，不是界面：``?? 5`` / ``?? 7`` 模拟的是"请求里没带这一档时
     后端拿自己的全局默认补上"（真实值见 ``settings.max_iterations`` /
     ``settings.review_threshold``）。界面那侧不许有这种兜底 —— 它必须要么读
     ``/config/agent-options``，要么整块降级（方案 §2 规矩 3）。 */
  const maxIterations = form.config.max_iterations ?? 5;
  const reviewThreshold = form.config.review_threshold ?? 7;
  return {
    taskId: mockTaskId(),
    task: form.task,
    status: 'running',
    createdAt: Date.now(),
    progress: {
      currentNode: 'planner',
      iteration: 0,
      maxIterations,
      elapsedMs: 0,
    },
    /* 假后端也要给回执（与 ``TaskRunConfigView`` 同一形状）：
       界面那句"服务端实际用的是 N"必须有来源，不能拿自己发出去的那份自证。 */
    runConfig: {
      max_iterations: maxIterations,
      review_threshold: reviewThreshold,
      max_cost_cny: form.config.max_cost_cny ?? null,
      timeout_s: form.config.timeout_s ?? null,
      rag_top_k: form.config.rag_top_k ?? null,
      use_tools: form.config.use_tools ?? null,
      enabled_tools: form.config.enabled_tools ?? null,
    },
  };
}

/** 历史任务列表（任务与日志页左侧「最近任务」用，接 mock）。 */
export const MOCK_HISTORY: TaskRecord[] = [
  {
    taskId: 'task-3f9a1c02be11',
    task: '用三句话说明什么是 RAG',
    status: 'done',
    createdAt: Date.now() - 1000 * 60 * 12,
    result: { ...mockResult({ task: '', config: { use_tools: false } }) },
  },
  {
    taskId: 'task-7b21de4409aa',
    task: '1024 路摄像头整机功耗估算',
    status: 'aborted',
    createdAt: Date.now() - 1000 * 60 * 35,
    error: { code: 'ITERATION_EXHAUSTED', message: '迭代耗尽：3 轮内 Reviewer 未给到 7 分以上' },
  },
  {
    taskId: 'task-c08b5f1177cd',
    task: '对比 BM25 与向量检索的适用场景',
    status: 'failed',
    createdAt: Date.now() - 1000 * 60 * 58,
    error: { code: 'LLM_UPSTREAM_ERROR', message: '上游返回 429：速率限制，已重试 3 次' },
  },
];
