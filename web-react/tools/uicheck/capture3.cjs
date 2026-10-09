/* 第三轮：只验证抽屉层级修复 + 产出最终对比截图 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
// 截图输出目录：优先读环境变量；回退到脚本同目录下的相对路径
const OUT = process.env.OUT_DIR || path.join(__dirname, 'shots2');
const { installMocks, TASK_ID } = require('./mocks.cjs');

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });

  // 抽屉层级
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2,
    isMobile: true, hasTouch: true, locale: 'zh-CN',
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await installMocks(page);

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: '打开导航' }).click();
  await page.waitForTimeout(500);

  // 抽屉里品牌区可见性：取品牌区元素的实际矩形与是否被遮挡
  const info = await page.evaluate(() => {
    const brand = document.querySelector('.sider-brand');
    if (!brand) return { ok: false, reason: 'no .sider-brand' };
    const r = brand.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    const sider = document.querySelector('.app-sider');
    return {
      rect: { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width) },
      hitIsInsideSider: !!(top && sider && sider.contains(top)),
      hitTag: top ? `${top.tagName}.${String(top.className).slice(0, 40)}` : 'none',
      siderZ: getComputedStyle(sider).zIndex,
      topbarZ: getComputedStyle(document.querySelector('.app-topbar')).zIndex,
    };
  });
  console.log('drawer check =', JSON.stringify(info, null, 2));
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, 'm2b-drawer-fixed.png') });
  console.log('  ✓ m2b-drawer-fixed');

  await ctx.close();
  await browser.close();
  console.log('DONE');
}

run().catch((e) => {
  console.error('FAILED:', e);
  process.exit(1);
});
