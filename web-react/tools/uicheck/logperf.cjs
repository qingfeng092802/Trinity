/* 日志终端性能基线探针（**只测不改**：不碰 src/，不进任何 commit 的文件清单）。
 *
 * 为什么要它：上一轮已经把 SSE 改成 50ms 攒批 + 5,000 行封顶（97665ad），
 * 「8,000 行卡 616ms」这个痛点到底还剩多少，没人有数。装 @tanstack/react-virtual
 * 之前必须先有基线 —— 没有前后对比数据的性能改造等于凭感觉加依赖。
 *
 * 五个口径（与拍板时一致）：
 *   1. 首屏：切到「实时日志」页签 → 双 rAF 落点耗时 + DOM 行数 + .log 子树元素数
 *   2. 页签往返：结果页 ⇄ 实时日志 ×5，取中位与最差
 *   2b. 切结果页**拆 React / 浏览器两半**（memo 被摘掉时「React 那半边」会立刻涨回去）
 *   3. longtask：PerformanceObserver 全程挂着，数 >50ms 的条数与最长一条
 *   4. 滚动帧时间：连续推 30 帧 scrollTop，报 p50 / p95
 *   5. 分侧 DOM + 按块普查（引用行 / 工具卡 / 复制按钮分别计数）
 *
 * 跑法（需要 dev server 在跑）：
 *   NODE_PATH=<playwright-core 所在目录> node tools/uicheck/logperf.cjs
 *   ROWS=50 node tools/uicheck/logperf.cjs        # 对照组：小流量
 */
const { chromium } = require('playwright-core');
const { installMocks, traceBody } = require('./mocks.cjs');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const ROWS = Number(process.env.ROWS || 8001);

/** 造 ROWS 条轨迹事件：消息形状在几种真实长度之间轮转，
 *  全用同一句短文本会把渲染量低估一个数量级。 */
function bigTrace(n) {
  /* 检索事件的 observation **照抄后端 `_render` 的形状**（全角｜、引用行、相关度），
     一次调用 3 条命中 ⇒ 引用行数 = 检索事件数 × 3。用假形状等于让前端解析器
     一路走兜底分支，那测的就不是产品行为。 */
  const cite = (seq) =>
    [
      '共命中 3 条相关片段：',
      `【1】anfangjiankong.md · chunk ${seq}1（字符 0-512）｜相关度 0.83（BM25 0.71 / 向量 0.92）`,
      '第 3 章：PoE 单端口最大输出功率 30W，设计值按 25.5W 核算。',
      `【2】anfangjiankong.md · chunk ${seq}2（字符 900-1400）｜相关度 0.71（BM25 0.66 / 向量 0.74）`,
      '第 5 章：整机功耗 = 设备数 × 单路功耗 ÷ 供电效率。',
      `【3】shengchanfangkong.md · chunk ${seq}3（字符 300-880）｜相关度 0.52（BM25 0.55 / 向量 0.49）`,
      '监控中心供电回路应独立敷设，与动力回路间距不小于 300mm。',
    ].join('\n');
  const shapes = [
    { node: 'executor', level: 'tool', msg: '先查知识库里 PoE 供电标准的原文段落。', tool: 'knowledge_search' },
    { node: 'executor', level: 'tool', msg: 'calculator → 15232', tool: 'calculator' },
    { node: 'reviewer', level: 'node_end', msg: '证据齐了，但第一步没给标准编号，退回补充。', tool: null },
    {
      node: 'reviewer',
      level: 'node_end',
      msg:
        'pass=True score=8 status=done｜内容完整（原理对比、适配矩阵、边界判据、两个示例齐备）；' +
        '推理链条自治且已在自检中识别并给出修正；扣分点为正文仍保留「零字面重合/召回率为0」等过强表述，终稿已按此修正。',
      tool: null,
    },
    { node: 'planner', level: 'node_end', msg: '规划 4 步：标准依据 → 单路功耗 → 并发系数 → 总功耗估算', tool: null },
  ];
  const items = [];
  for (let i = 1; i <= n; i += 1) {
    const s = shapes[i % shapes.length];
    items.push({
      event_seq: i,
      step: (i % 9) + 1,
      sub_step: null,
      event_type: s.level,
      role: s.node,
      node: s.node,
      thought: s.msg,
      tool_name: s.tool,
      arguments: s.tool ? { q: 'x' } : null,
      observation: s.tool === 'knowledge_search' ? cite(i) : s.tool ? 'ok' : null,
      latency_ms: 120 + (i % 900),
      tokens_in: 300,
      tokens_out: 80,
      cost: 0.0004,
      status: 'done',
      error_code: null,
      error_message: null,
      created_at: new Date(Date.now() - (n - i) * 1000).toISOString(),
    });
  }
  return { ...traceBody, items, total: n, has_more: false, next_after_seq: n, events_available: true, unavailable_reason: null };
}

const pct = (arr, p) => {
  const a = [...arr].sort((x, y) => x - y);
  return a.length ? +a[Math.min(a.length - 1, Math.floor(a.length * p))].toFixed(1) : null;
};

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
  /* longtask 必须在应用代码之前挂上，addInitScript 是唯一时机 */
  await ctx.addInitScript(() => {
    window.__lt = { n: 0, max: 0, total: 0 };
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          window.__lt.n += 1;
          window.__lt.total += e.duration;
          if (e.duration > window.__lt.max) window.__lt.max = e.duration;
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch {
      window.__lt.unsupported = true;
    }
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

  await installMocks(page);
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bigTrace(ROWS)) }),
  );

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(800);

  const clickTab = (name) =>
    page.evaluate(async (label) => {
      const tab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
        (t.textContent || '').includes(label),
      );
      if (!tab) return null;
      const t0 = performance.now();
      tab.click();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      return +(performance.now() - t0).toFixed(1);
    }, name);

  /* ---- 1. 首屏：切到日志页签 ---- */
  const firstMount = await clickTab('实时日志');
  const dom = await page.evaluate(() => {
    const log = document.querySelector('.log');
    const body = document.querySelector('.log-body');
    return {
      rows: document.querySelectorAll('.log-row').length,
      elements: log ? log.querySelectorAll('*').length : 0,
      textLen: log ? (log.innerText || '').length : 0,
      /* 滚动条在 .log-body 上，量外层 .log 的 scrollHeight 只会得到面板自身高度 */
      bodyScrollH: body ? Math.round(body.scrollHeight) : 0,
      bodyClientH: body ? Math.round(body.clientHeight) : 0,
      heapMB: performance.memory ? +(performance.memory.usedJSHeapSize / 1048576).toFixed(1) : null,
    };
  });

  /* ---- 2. 页签往返 ×5，**分方向记** ----
     合在一起看会误判：改造后日志页只挂一窗，往返里剩下的开销全在**另一侧**
     （结果页按事件数铺工具块，1 条事件 ≈ 11 个元素）。不分方向就说不清
     「300ms 是谁花的」。 */
  const toResult = [];
  const toLog = [];
  for (let i = 0; i < 5; i += 1) {
    toResult.push(await clickTab('运行结果'));
    toLog.push(await clickTab('实时日志'));
  }
  const switches = [...toResult, ...toLog].filter((x) => x !== null);
  /* 分侧 DOM + **按块普查**：上一轮只数了 .copy-btn / .chip / span.row 就断言
     「开销在工具块列表」，结果错了 —— 那些元素出自结果页的引用列表，
     工具卡那趟压根没挂载（AntD 页签首次激活才挂）。块级计数才能指对人。 */
  const census = await page.evaluate(() => {
    const q = (s) => document.querySelectorAll(s).length;
    return {
      全页元素: q('*'),
      日志行: q('.log-row'),
      日志子树元素: document.querySelector('.log') ? document.querySelector('.log').querySelectorAll('*').length : 0,
      引用行: q('.list-row'),
      工具卡: q('.tool-card'),
      复制按钮: q('.copy-btn'),
    };
  });

  /* ---- 2b. 把「切到结果页」拆成 React 与浏览器两半 ----
     A = 点页签（React 重渲染 + 可见性翻转 + 布局绘制，全算上）
     B = **不经过 React**，只用内联 style 把同一屏 display:none ↔ 显示
     A − B 就是 React 那半边的账：memo 生效时它应该很小，谁把 memo 摘掉
     这里就会立刻涨回去（B 不受影响，所以涨的那一截只可能是 React）。

     ⚠️ B 必须在结果页**正处于激活态**时量。第一次把它放在「已经切回日志页」之后量，
     读数是 5.7ms —— 因为那时整块子树是 visibility:hidden，浏览器只排不画，
     量出来的根本不是切页签要付的那一份。 */
  const reactHalf = [];
  const browserHalf = [];
  for (let i = 0; i < 3; i += 1) {
    const r = await page.evaluate(async () => {
      const find = (label) =>
        Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
          (t.textContent || '').includes(label),
        );
      const raf2 = () => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
      const t0 = performance.now();
      find('运行结果').click();
      await raf2();
      const a = performance.now() - t0;
      const pane = Array.from(document.querySelectorAll('.ant-tabs-tabpane')).find((p) =>
        p.querySelector('.list-row'),
      );
      if (!pane) return { a: +a.toFixed(1), b: null };
      pane.style.display = 'none';
      void pane.offsetHeight;
      const t1 = performance.now();
      pane.style.display = '';
      void document.body.offsetHeight;
      await raf2();
      const b = performance.now() - t1;
      find('实时日志').click();
      await raf2();
      return { a: +a.toFixed(1), b: +b.toFixed(1) };
    });
    reactHalf.push(r.a);
    if (r.b !== null) browserHalf.push(r.b);
  }
  await page.evaluate(() => {
    const find = (label) =>
      Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
        (t.textContent || '').includes(label),
      );
    find('实时日志').click();
  });

  /* ---- 2c. 引用列表折叠：两态的元素数与切换耗时 ----
     折叠是这一轮真正治「切页签 150ms」的改动（memo 只砍掉 React 那半边），
     所以验收口径是三个数：折叠态常驻元素、展开态常驻元素、两态各自切换花多久。
     行数与数据量解耦 ⇒ 折叠态那两个数应该**不随 ROWS 涨**。
     这里量的是**当前页签往返**（折叠态），不是点展开那一下；展开代价的两个规模
     （100 行 / 4,800 行）在 running.cjs 的 F 趟，长尾归因走 Performance 录制。 */
  const fold = await page.evaluate(async () => {
    const find = (label) =>
      Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
        (t.textContent || '').includes(label),
      );
    const raf2 = () => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
    /* `.code-more` 也被代码块/JSON 树的「展开全文」用着 —— 只认引用列表那句文案，
       否则这里会点到别人的按钮，量出一份看起来合理的假数。 */
    const btn = () =>
      Array.from(document.querySelectorAll('.code-more')).find((b) =>
        /展开全部|收起/.test(b.textContent || ''),
      );
    const count = () => ({
      行: document.querySelectorAll('.list-row').length,
      元素: document.querySelectorAll('*').length,
      按钮: btn() ? btn().textContent.trim() : '',
    });
    find('运行结果').click();
    await raf2();
    const collapsed = count();
    const t0 = performance.now();
    btn().click();
    await raf2();
    const expandMs = +(performance.now() - t0).toFixed(1);
    const expanded = count();
    const t1 = performance.now();
    btn().click();
    await raf2();
    const collapseMs = +(performance.now() - t1).toFixed(1);
    const again = count();
    find('实时日志').click();
    await raf2();
    return { collapsed, expandMs, expanded, collapseMs, again };
  });

  /* ---- 3. 滚动帧时间：连续推 30 帧 ---- */
  const frames = await page.evaluate(async () => {
    const b = document.querySelector('.log-body');
    if (!b) return [];
    const out = [];
    let last = performance.now();
    for (let i = 0; i < 30; i += 1) {
      b.scrollTop = (b.scrollTop + 400) % (b.scrollHeight - b.clientHeight || 1);
      await new Promise((r) => requestAnimationFrame(() => r()));
      const now = performance.now();
      out.push(now - last);
      last = now;
    }
    return out.map((x) => +x.toFixed(1));
  });

  const lt = await page.evaluate(() => ({ ...window.__lt, max: +window.__lt.max.toFixed(1), total: +window.__lt.total.toFixed(1) }));

  console.log(
    JSON.stringify(
      {
        灌入事件: ROWS,
        首屏: { 切页签耗时ms: firstMount, ...dom },
        页签往返: {
          样本: switches,
          中位ms: pct(switches, 0.5),
          最差ms: pct(switches, 1),
          到结果页中位ms: pct(toResult, 0.5),
          到日志页中位ms: pct(toLog, 0.5),
        },
        分侧DOM: census,
        引用折叠: fold,
        切结果页拆解: {
          走React中位ms: pct(reactHalf, 0.5),
          不经React中位ms: pct(browserHalf, 0.5),
          即React那半边ms:
            pct(reactHalf, 0.5) !== null && pct(browserHalf, 0.5) !== null
              ? +(pct(reactHalf, 0.5) - pct(browserHalf, 0.5)).toFixed(1)
              : null,
        },
        滚动帧: { p50: pct(frames, 0.5), p95: pct(frames, 0.95), 最差: pct(frames, 1), 样本数: frames.length },
        longtask: lt,
        pageerror: errors.slice(0, 3),
      },
      null,
      1,
    ),
  );

  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
