/* 日志滚动交互验证（真实 SSE 流 + 强制滚动）。
 *
 * 为什么需要它：真实任务实测只推 ~9 条日志，面板 360px 装得下，
 * 永远 scrollable=false —— 所以「自动滚动 / 上滑暂停」这两个交互
 * 在真实流下**根本没被触发过**。这里注入 CSS 把面板压矮，逼出滚动再验。
 *
 * 不改产品代码，只在页面里注入样式。
 */
const { chromium } = require('playwright-core');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';
const TASK = process.env.TASK || '门禁开门延时默认几秒？用计算器算 12+30';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // 把日志面板压到 90px，强制出现滚动条
  await page.addStyleTag({
    content: '.log-body { height: 60px !important; max-height: 60px !important; }',
  });

  await page.fill('.composer-input', TASK);
  await page.click('.composer-row button[type="submit"]');

  const probe = () =>
    page.evaluate(() => {
      const b = document.querySelector('.log-body');
      if (!b) return { missing: true };
      return {
        rows: document.querySelectorAll('.log-row').length,
        scrollable: b.scrollHeight > b.clientHeight + 1,
        pinned: Math.abs(b.scrollHeight - b.clientHeight - b.scrollTop) < 4,
        scrollTop: Math.round(b.scrollTop),
        // 上滑后应出现的「N 条新日志」回跳按钮
        jumpBtn: document.querySelector('.log-jump')?.innerText?.trim() ?? null,
        footText: document.querySelector('.log-foot')?.innerText?.replace(/\n/g, ' ').trim() ?? null,
      };
    });

  // 阶段一：什么都不做，看是否自动贴底
  await sleep(6000);
  const auto = await probe();

  // 必须等「真的可滚动」再滚，否则滚轮作用在没滚动条的元素上等于空操作
  let waited = 0;
  let ready = await probe();
  while (waited < 40000 && !(ready.scrollable && ready.rows >= 3)) {
    await sleep(1000);
    waited += 1000;
    ready = await probe();
  }
  console.log(`等可滚动耗时 ${waited / 1000}s:`, JSON.stringify(ready));

  // 阶段二：用**真实滚轮**上滑（dispatch 合成事件 React 收不到），
  // 并且**立刻**检查 —— 慢一步新日志就会先把面板拉回底部，造成假阴性。
  await page.hover('.log-body');
  await page.mouse.wheel(0, -400);
  await sleep(250);
  const rightAfterWheel = await probe();
  await sleep(6000);
  const afterScrollUp = await probe();

  // 阶段三：点回跳按钮，验证能回到底部并恢复自动滚动
  let afterJump = null;
  const jump = await page.$('.log-jump');
  if (jump) {
    await jump.click();
    await sleep(2500);
    afterJump = await probe();
  }

  console.log('阶段一 · 自动滚动（不动鼠标）:', JSON.stringify(auto));
  console.log('阶段二 · 滚轮上滑后 250ms :', JSON.stringify(rightAfterWheel));
  console.log('阶段二 · 再等 6s（应仍停在原处，不被拉回）:', JSON.stringify(afterScrollUp));
  console.log('阶段三 · 点回跳后:', JSON.stringify(afterJump));
  console.log('\nconsole errors:', errors.length, errors.slice(0, 3));

  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
