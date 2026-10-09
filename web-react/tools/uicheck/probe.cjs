/* 收尾校验：桌面左栏是否还有被裁的列表行（对比页面高度与左栏可视高度） */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = process.env.OUT_DIR || path.join(__dirname, 'shots');
const { installMocks } = require('./mocks.cjs');

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'zh-CN',
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await installMocks(page);
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);

  const probe = await page.evaluate(() => {
    const side = document.querySelector('.task-side');
    if (!side) return { ok: false };
    return {
      sideScrollHeight: side.scrollHeight,
      sideClientHeight: side.clientHeight,
      overflows: side.scrollHeight > side.clientHeight + 1,
      historyRows: document.querySelectorAll('.task-side .list-row').length,
    };
  });
  console.log('task-side probe =', JSON.stringify(probe));

  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, 'probe-tasks-desktop.png') });
  console.log('  ✓ probe-tasks-desktop');

  await ctx.close();
  await browser.close();
}

run().catch((e) => { console.error('FAILED:', e); process.exit(1); });
