/**
 * 三栏结构截图验收：直接打真实 dev server（5199）+ 真实后端（8001）。
 *
 * 用法：
 *   export NODE_PATH='<USER_HOME>\.workbuddy\binaries\node\workspace\node_modules'
 *   node tools/uicheck/three-col.cjs
 *
 * 产出：tools/uicheck/shots/3c-*.png（不入库），并把控制台报错打到 stdout。
 */
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');

// 用本机已装的 Chrome，而不是 playwright 自带的 chromium（本机没下载那个）
// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';
const OUT = path.resolve(__dirname, 'shots');

const SHOTS = [
  { name: '3c-desktop-light', w: 1440, h: 900, theme: 'light', url: '/' },
  { name: '3c-desktop-dark', w: 1440, h: 900, theme: 'dark', url: '/' },
  { name: '3c-desktop-selected', w: 1440, h: 900, theme: 'light', url: '/', select: true },
  { name: '3c-trace-light', w: 1440, h: 900, theme: 'light', url: '/trace' },
  { name: '3c-trace-dark', w: 1440, h: 900, theme: 'dark', url: '/trace' },
  { name: '3c-tablet', w: 1100, h: 900, theme: 'light', url: '/' },
  { name: '3c-mobile', w: 390, h: 844, theme: 'light', url: '/' },
  { name: '3c-mobile-drawer', w: 390, h: 844, theme: 'light', url: '/', drawer: true },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROME });
  let errors = 0;

  for (const shot of SHOTS) {
    const ctx = await browser.newContext({
      viewport: { width: shot.w, height: shot.h },
      deviceScaleFactor: 1,
      colorScheme: shot.theme === 'dark' ? 'dark' : 'light',
    });
    const page = await ctx.newPage();
    page.on('console', (m) => {
      if (m.type() === 'error') {
        errors += 1;
        console.log(`[console.error][${shot.name}] ${m.text().slice(0, 200)}`);
      }
    });
    page.on('pageerror', (e) => {
      errors += 1;
      console.log(`[pageerror][${shot.name}] ${String(e).slice(0, 200)}`);
    });

    await page.goto(BASE + shot.url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(900);

    // 尺寸探针：状态条是否真的 36px、新建流高度、第二栏宽度
    const probe = await page.evaluate(() => {
      const h = (sel) => {
        const el = document.querySelector(sel);
        return el ? Math.round(el.getBoundingClientRect().height) : null;
      };
      const w = (sel) => {
        const el = document.querySelector(sel);
        return el ? Math.round(el.getBoundingClientRect().width) : null;
      };
      return {
        composerH: h('.composer'),
        statusbarH: h('.statusbar'),
        taskColW: w('.task-col'),
        logIdle: !!document.querySelector('.log-idle'),
        tlItems: document.querySelectorAll('.tsk-item').length,
        tabs: Array.from(document.querySelectorAll('.ant-tabs-tab')).map((t) =>
          t.textContent.trim(),
        ),
      };
    });
    console.log(`${shot.name} probe =`, JSON.stringify(probe));

    if (shot.drawer) {
      const trigger = await page.$('.only-compact');
      if (trigger) {
        await trigger.click();
        await page.waitForTimeout(600);
        const openState = await page.evaluate(() => {
          const col = document.querySelector('.task-col--drawer');
          return {
            isOpen: col?.classList.contains('is-open') ?? null,
            x: col ? Math.round(col.getBoundingClientRect().x) : null,
          };
        });
        console.log(`${shot.name} drawer =`, JSON.stringify(openState));
      }
    }

    if (shot.select) {
      const first = await page.$('.tsk-item');
      if (first) {
        await first.click();
        await page.waitForTimeout(2500);
        const sel = await page.evaluate(() => ({
          status: document.querySelector('.statusbar')?.textContent?.trim().slice(0, 90),
          active: document.querySelector('.tsk-item.is-active .tl-title')?.textContent?.slice(0, 30),
          logRows: document.querySelectorAll('.log-row').length,
        }));
        console.log(`${shot.name} after select =`, JSON.stringify(sel));
      }
    }

    await page.screenshot({ path: path.join(OUT, `${shot.name}.png`), fullPage: false });
    await ctx.close();
  }

  await browser.close();
  console.log(`\n控制台报错总数：${errors}`);
})();
