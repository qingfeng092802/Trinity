/* 路由级拆包（P1-02 / B4）的运行时探针 —— bundle.cjs 管产物，这一支管用户看得见的那一面：
 *
 *   1 在途态：chunk 还没到，主内容区有占位、外壳（图标栏/顶栏）不许跟着消失、
 *     外壳的几何不许动（这才叫"不引入 CLS"，不是嘴上说的）
 *   2 失败态：chunk 拉不到（模拟"控制台刚重构过、旧标签页里的 hash 已 404"）⇒
 *     错误卡说的话要真、给的出口要真能救回来。尤其不许出现「重试」这种**点了没用**的按钮
 *     （React.lazy 缓存 rejected promise，再渲染一次不会重发请求）
 *   3 记账：/tasks 与 /trace 全程不许发一个 echarts 请求；/eval 才发
 *     （EV-03 的原始症状就是 dev 下 /tasks 也拖 echarts-for-react.js 2,550 KB）
 *
 * 前置：dev server 起在 5173（不打后端，走 mocks.cjs）。
 *
 * NODE_PATH='C:\Users\<you>\.workbuddy\binaries\node\workspace\node_modules' \
 *   node tools/uicheck/lazy.cjs
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const { installMocks } = require('./mocks.cjs');

/* dev 下动态 import 解析成源文件路径；build 下是 /assets/EvalAblationPage-<hash>.js。
   两种都写进 matcher，所以这支脚本对 dev 与 preview 都能跑。 */
const EVAL_MOD = '**/EvalAblationPage.tsx*';

let pass = 0;
const fails = [];
function check(name, cond, got) {
  if (cond) {
    pass += 1;
    console.log(`  ok   ${name}`);
  } else {
    fails.push(name);
    console.log(`  FAIL ${name}${got === undefined ? '' : `  读数=${JSON.stringify(got)}`}`);
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 外壳几何：顶栏、图标栏、内容列的位置尺寸。占位与真实页面切换时这三枚不许变。
 *  导航按钮只数 `.rail-nav` 里的。⚠️ 这句注释原先的理由（"`.rail-foot` 还有一枚主题切换"）
 *   已经不成立了 —— 2026-09-26 主题切换挪到了顶栏右上角，`.rail-foot` 现在只剩一颗数据源点。
 *   但**只数 `.rail-nav` 这个写法要留**：`mid.rail === 3` 那两条判的是"外壳没掉件"，
 *   把栏脚的东西计进来，以后任何一次往 `.rail-foot` 加东西都会让这两条莫名变红。 */
const shellBox = (page) =>
  page.evaluate(() => {
    const g = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return [Math.round(r.top), Math.round(r.left), Math.round(r.width), Math.round(r.height)];
    };
    return { topbar: g('.app-topbar'), rail: g('.app-rail'), content: g('.app-content') };
  });

/** 投影成"不许动的那几个数"：顶栏/图标栏取整盒，内容列去掉 height。 */
const fixed = (b) => ({
  topbar: b.topbar,
  rail: b.rail,
  content: b.content ? b.content.slice(0, 3) : null,
});

async function open(context, { abortEvalChunk = false, delayEvalChunk = 0 } = {}) {
  const page = await context.newPage();
  const errors = [];
  const requests = [];
  page.on('pageerror', (e) => errors.push(String(e.message || e)));
  page.on('request', (r) => requests.push(r.url()));
  await installMocks(page);
  if (abortEvalChunk) await page.route(EVAL_MOD, (r) => r.abort());
  else if (delayEvalChunk)
    await page.route(EVAL_MOD, async (r) => {
      await sleep(delayEvalChunk);
      await r.continue();
    });
  return { page, errors, requests };
}

const chartReqs = (list) => list.filter((u) => /echarts/i.test(u));

async function main() {
  const browser = await chromium.launch({ executablePath: CHROME });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

  /* ---------------- 1 在途占位 ---------------- */
  {
    const { page, errors, requests } = await open(ctx, { delayEvalChunk: 700 });
    await page.goto(`${BASE}/tasks`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.rail-nav .rail-btn');
    const before = await shellBox(page);
    check('/tasks 落地时不碰 echarts（EV-03 的 dev 症状）', chartReqs(requests).length === 0, chartReqs(requests).slice(0, 3));

    /* 第四页也量一次：`bundle.cjs` 现在把 /knowledge 算进 payers，运行时这一面要能对上。
       等的是 `.stage-bar`（只有知识库页有那四条分段进度），不是 `.page-title` ——
       后者在 /tasks 上就在，点了没换页也会"秒过"。 */
    requests.length = 0;
    await page.locator('.rail-nav button[aria-label="知识库"]').click();
    await page.waitForSelector('.stage-bar', { timeout: 5000 });
    await sleep(250);
    check('/knowledge 落地时也不碰 echarts（拆包不许因为加了一页就漏一页）',
      chartReqs(requests).length === 0, chartReqs(requests).slice(0, 3));

    requests.length = 0;
    await page.getByRole('button', { name: '轨迹回放' }).click();
    await page.waitForSelector('.page-head .page-title', { timeout: 5000 });
    await sleep(250);
    check('/trace 落地时也不碰 echarts', chartReqs(requests).length === 0, chartReqs(requests).slice(0, 3));
    const traceBox = await shellBox(page);

    requests.length = 0;
    await page.getByRole('button', { name: '评测与消融' }).click();
    /* 在途窗口（chunk 被故意拖 700ms）：只读一次，不等待 */
    await sleep(200);
    const mid = await page.evaluate(() => ({
      fallback: !!document.querySelector('.page-fallback'),
      status: !!document.querySelector('[role="status"].page-fallback'),
      busy: document.querySelector('.page-fallback')?.getAttribute('aria-busy') || null,
      skel: document.querySelectorAll('.page-fallback .skeleton').length,
      srText: document.querySelector('.page-fallback .sr-only')?.textContent || '',
      padTop: getComputedStyle(document.querySelector('.page-fallback')).paddingTop,
      head: !!document.querySelector('.page-head'),
      rail: document.querySelectorAll('.rail-nav .rail-btn').length,
      minH: getComputedStyle(document.querySelector('.page-fallback')).minHeight,
    }));
    const midBox = await shellBox(page);
    check('chunk 在途时主内容区有占位（而不是空白，也不是上一页残留）', mid.fallback && !mid.head, mid);
    check('占位是 role=status + aria-busy（读屏听得见"在加载"）', mid.status && mid.busy === 'true', mid);
    check('占位里是三条骨架、不是转圈图标', mid.skel === 3, mid.skel);
    check('占位自带一句给读屏的话（不只靠底色）', /正在加载/.test(mid.srText), mid.srText);
    check('占位沿用 .page-main 的留白（paddingTop 非 0，留白只有一个来源）', parseFloat(mid.padTop) > 0, mid.padTop);
    check('占位高度与真实页同级（min-height 有值 ⇒ 切换不推东西）', parseFloat(mid.minH) > 200, mid.minH);
    check('在途期间外壳照旧在（图标栏四枚一枚不少，第四枚是知识库）', mid.rail === 4, mid.rail);
    /* 比的是"外壳没被推动"：顶栏与图标栏取整盒，内容列只取 top/left/width。
       内容列的 height 必然随占位↔真实页变（3,816 → 844 → 整页），把它也全等就等于
       断言"占位和真实页一样高"—— 那不是这条判据要说的话，而且是假话。 */
    check(
      '在途期间外壳几何没动（顶栏/图标栏整盒 + 内容列的 top-left-width 全等）',
      JSON.stringify(fixed(midBox)) === JSON.stringify(fixed(traceBox)),
      { traceBox: fixed(traceBox), midBox: fixed(midBox) },
    );

    await page.waitForFunction(() => !document.querySelector('.page-fallback'), null, { timeout: 8000 });
    const after = await page.evaluate(() => ({
      head: document.querySelector('.page-head .page-title')?.textContent?.slice(0, 12) || '',
      fallback: !!document.querySelector('.page-fallback'),
      liveStatus: !!document.querySelector('[role="status"].page-fallback'),
      pageSkel: document.querySelectorAll('.skeleton').length,
    }));
    const afterBox = await shellBox(page);
    check('落地后占位自己撤走、评测页头出现', !after.fallback && /评测与消融/.test(after.head), after);
    check('落地后不许残留 role=status 的加载占位', !after.liveStatus, after);
    console.log(
      `  · 落地后页面上另有 ${after.pageSkel} 条骨架 —— 那是评测页自己的报告/表格行占位` +
        `（EvalAblationPage.tsx:484、600），与拆包无关，只记录不判定`,
    );
    check(
      '落地后外壳几何仍与在途时一致（真实页挂载不推动任何东西）',
      JSON.stringify(fixed(afterBox)) === JSON.stringify(fixed(midBox)),
      { midBox: fixed(midBox), afterBox: fixed(afterBox) },
    );
    check('/eval 落地才发 echarts 请求', chartReqs(requests).length > 0, chartReqs(requests).slice(0, 3));
    check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  }

  /* ---------------- 2 chunk 拉不到 ---------------- */
  {
    const { page, errors } = await open(ctx, { abortEvalChunk: true });
    await page.goto(`${BASE}/tasks`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.rail-nav .rail-btn');
    await page.getByRole('button', { name: '评测与消融' }).click();
    await page.waitForSelector('[role="alert"]', { timeout: 8000 });
    const card = await page.evaluate(() => {
      const el = document.querySelector('[role="alert"]');
      return {
        text: el?.textContent || '',
        buttons: [...(el?.querySelectorAll('button') || [])].map((b) => b.textContent?.trim()),
        rail: document.querySelectorAll('.rail-nav .rail-btn').length,
      };
    });
    check('拉不到 chunk 时报的是"这一页没取到"，不是一句泛泛的加载失败', /这一页的代码没取到/.test(card.text), card.text.slice(0, 60));
    check(
      '给的出口是「刷新页面」，不是点了没用的「重试」（lazy 缓存 rejected promise，重试不会再发请求）',
      card.buttons.includes('刷新页面') && !card.buttons.includes('重试'),
      card.buttons,
    );
    check('错误只吃掉主内容区，外壳与导航还在（还能点回别的页）', card.rail === 4, card.rail);

    /* 分类判据用的是**源文件里那一条正则**（抠出来现场构造），不是脚本里另抄一份 ——
       否则改源码的人绿着改坏，探针还在骗人。 */
    const src = fs.readFileSync(path.resolve(__dirname, '../../src/components/ErrorBoundary.tsx'), 'utf8');
    const m = src.match(/const CHUNK_LOAD_FAILED\s*=\s*\/([\s\S]*?)\/[a-z]*;/);
    const shipped = m ? new RegExp(m[1], 'i') : null;
    check('能从 ErrorBoundary.tsx 里抠出那条分类正则（探针与源码同源）', !!shipped, m ? m[1].slice(0, 40) : null);
    const liveMsg = (card.text.match(/Failed to fetch[^·]*|Importing a module[^·]*/i) || [''])[0];
    const cases = [
      ['Chrome 实测串', liveMsg || 'Failed to fetch dynamically imported module: http://x/EvalAblationPage.js'],
      ['Safari 措辞', 'Importing a module script failed.'],
      ['Firefox 措辞', 'error loading dynamically imported module: http://x/y.js'],
    ];
    for (const [name, msg] of cases) check(`${name} 判为 chunk 类（走刷新页面那条）`, !!shipped && shipped.test(msg), msg.slice(0, 70));
    check(
      '一次普通渲染抛错不许被判成 chunk 错（否则所有错误都改成"刷新页面"，把真因盖掉）',
      !!shipped && !shipped.test('Cannot read properties of undefined (reading "map")'),
      true,
    );
    console.log(`  · 现场抓到的浏览器错误串：${liveMsg || '（卡片文案里没带上原文）'}`);
    console.log(`  · 这一趟的 pageerror（记录，不判绿判红：未处理拒绝由 vite 预加载器抛，卡片已兜住）：${errors.length} 条`);
  }

  await ctx.close();
  await browser.close();
  console.log(`\nlazy probe: ${pass} 通过 / ${pass + fails.length} 断言`);
  if (fails.length) {
    fails.forEach((f) => console.log(`  · ${f}`));
    process.exit(1);
  }
}

main().catch((e) => {
  console.error('探针自己炸了：', e);
  process.exit(2);
});
