/* 第二轮验收：视口级截图（不是 fullPage，避免固定元素错位）+ 交互验证
   - 移动端：顶栏 / 抽屉导航 / 底部标签栏 / 日志面板
   - 主题切换按钮是否真的切主题
   - 日志面板局部放大（检查等宽对齐与级别徽标）
   - 页③ 图表区（检查图例与坐标轴是否还打架） */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
// 截图输出目录：优先读环境变量；回退到脚本同目录下的相对路径
const OUT = process.env.OUT_DIR || path.join(__dirname, 'shots2');
const TASK_ID = 'task-3f9a1c02be11';

/* 与第一轮同一套假数据，抽成独立文件避免重复 */
const { installMocks } = require('./mocks.cjs');

async function shot(page, name) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log('  ✓', name);
}

async function shotEl(page, name, selector) {
  fs.mkdirSync(OUT, { recursive: true });
  const el = page.locator(selector).first();
  await el.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log('  ✓', name, `(${selector})`);
}

async function submitTask(page) {
  // ⚠️ 已知限制（2026-09-23 登记，先于当轮 trace.arguments 归一化改动）：
  // 示例按钮已进「配置」弹层、提交按钮改名「提交」，这两步对不上当前 UI，会 30s 超时。
  await page.getByRole('button', { name: '数值计算' }).click();
  await page.getByRole('button', { name: '提交任务' }).click();
  await page.waitForTimeout(2600);
}

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });

  /* ---------- A. 移动端（视口级） ---------- */
  {
    const ctx = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      locale: 'zh-CN',
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => console.log('  [pageerror]', e.message));
    await installMocks(page);

    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    await shot(page, 'm1-tasks-top');

    // 抽屉导航
    await page.getByRole('button', { name: '打开导航' }).click();
    await page.waitForTimeout(450);
    await shot(page, 'm2-drawer-open');
    await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '收起导航' }).click();
    await page.waitForTimeout(350);

    await submitTask(page);
    await shot(page, 'm3-tasks-log');
    await page.locator('.log').scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await shot(page, 'm4-log-panel');

    await page.goto(`${BASE}/trace?id=${TASK_ID}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await shot(page, 'm5-trace-top');
    await page.locator('.tl-item').nth(2).scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await shot(page, 'm6-trace-step');

    await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await shot(page, 'm7-eval-top');
    await page.locator('.ant-table-wrapper').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await shot(page, 'm8-eval-table');

    await ctx.close();
  }

  /* ---------- B. 桌面：交互 + 局部放大 ---------- */
  {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: 'light',
      locale: 'zh-CN',
    });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => console.log('  [pageerror]', e.message));
    await installMocks(page);

    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await submitTask(page);

    // 局部：日志面板 / 指标块 / 结果卡
    await shotEl(page, 'd1-log-panel', '.log');
    await shotEl(page, 'd2-metrics', '.metric-grid');
    await shotEl(page, 'd3-toolbar', '.app-topbar');

    // 主题切换是否真的换主题
    await page.getByRole('button', { name: '切换到深色主题' }).click();
    await page.waitForTimeout(600);
    const theme = await page.evaluate(() => document.documentElement.dataset.theme);
    console.log('  theme after toggle =', theme);
    await shotEl(page, 'd4-log-panel-dark', '.log');
    await shot(page, 'd5-tasks-dark-toggle');
    await page.getByRole('button', { name: '切换到浅色主题' }).click();
    await page.waitForTimeout(500);
    const back = await page.evaluate(() => document.documentElement.dataset.theme);
    console.log('  theme after toggle back =', back);

    // 侧栏折叠
    await page.getByRole('button', { name: '收起侧栏' }).click();
    await page.waitForTimeout(450);
    await shot(page, 'd6-sider-collapsed');

    // 页③ 图表
    await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1100);
    await shotEl(page, 'd7-eval-chart', '.ant-card, .surface');
    await page.locator('.surface').nth(0).screenshot({ path: path.join(OUT, 'd7-eval-card1.png') });
    console.log('  ✓ d7-eval-card1');

    // 键盘可达性：Tab 到第一个焦点并截图
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? `${el.tagName}.${el.className}`.slice(0, 80) : 'none';
    });
    console.log('  2nd tab focus =', focused);
    await shot(page, 'd8-focus-ring');

    await ctx.close();
  }

  await browser.close();
  console.log('\nDONE →', OUT);
}

run().catch((e) => {
  console.error('FAILED:', e);
  process.exit(1);
});
