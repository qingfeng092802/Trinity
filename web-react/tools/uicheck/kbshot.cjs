/* 知识库页（/knowledge）的像素留档 —— 三段：整页 / 文档表那一列分段进度条 / 暗色同一处。
 *
 * 为什么单独一个脚本而不是塞进 running.cjs 的 Z 趟：Z 趟是**判据**（50 条断言），
 * 像素不是判据、也不该被算进断言数里。这里只出图，不判绿。
 * 分段条的亮/暗/呼吸本身由 Z 趟读 `data-stages` 证明；这几张图回答的是另一句话：
 * "它看起来像不像一条能说清进度的条子"。
 *
 * 跑法（需要 dev server 在 :5173，桩全部走 mocks.cjs，不需要后端）：
 *   NODE_PATH='C:\Users\<you>\.workbuddy\binaries\node\workspace\node_modules' \
 *     node tools/uicheck/kbshot.cjs
 * 输出：tools/uicheck/shots/running/kb-*.png
 */
const path = require('path');
const { chromium } = require('playwright-core');
const { installMocks, resetKb } = require('./mocks.cjs');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots/running');

/** 主题写进 localStorage 再导航：避免"先渲染亮色再闪成暗色"被截进中间帧。 */
async function shot(browser, scheme, opts = {}) {
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 1000 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const page = await ctx.newPage();
  resetKb();
  await installMocks(page);
  await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' });
  /* 呼吸动画是 opacity 的 0.9s 循环：截图必然截到某一帧，
     所以这里只静置到**过渡**（200ms 底色那条）落定，不去"等一个动画峰值"——
     等峰值会把图拍成"某一格特别亮"，那不是这个条子的常态。 */
  await page.waitForTimeout(700);
  const files = [];
  const full = `kb-${scheme}-${opts.viewport ? opts.viewport.width : 'wide'}.png`;
  await page.screenshot({ path: path.join(OUT, full), fullPage: true });
  files.push(full);
  for (const [sel, name] of [
    ['.ant-table', `kb-${scheme}-table.png`],
    ['.up-drop', `kb-${scheme}-drop.png`],
  ]) {
    const loc = page.locator(sel).first();
    if (await loc.count()) {
      await loc.screenshot({ path: path.join(OUT, name) });
      files.push(name);
    }
  }
  await ctx.close();
  return files;
}

async function main() {
  const browser = await chromium.launch({ executablePath: CHROME });
  try {
    const light = await shot(browser, 'light');
    const dark = await shot(browser, 'dark');
    const narrow = await shot(browser, 'light', { viewport: { width: 390, height: 844 } });
    for (const f of [...light, ...dark, ...narrow]) console.log(`  · ${path.join(OUT, f)}`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
