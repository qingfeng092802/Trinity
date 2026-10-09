/* 本轮 5 个问题的事实核查探针：只读测量，不改任何东西。 */
const { chromium } = require('playwright-core');
// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const measure = async () => {
    return page.evaluate(() => {
      const box = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height) };
      };
      const cfgs = [...document.querySelectorAll('.cfg')].map((el) => {
        const r = el.getBoundingClientRect();
        return {
          text: el.textContent.trim().slice(0, 10),
          w: Math.round(r.width),
          h: Math.round(r.height),
        };
      });
      const item = document.querySelector('.tsk-item');
      const itemMeta = item ? item.querySelector('.tsk-meta') : null;
      return {
        sider: box('.app-sider'),
        taskCol: box('.task-col'),
        main: box('.page-main'),
        composer: box('.composer'),
        composerSettings: box('.composer-settings'),
        cfgs,
        cfgRowWraps: (() => {
          const els = [...document.querySelectorAll('.cfg')];
          if (els.length < 2) return false;
          return els[els.length - 1].getBoundingClientRect().top > els[0].getBoundingClientRect().bottom - 2;
        })(),
        tskItemText: item ? item.innerText.replace(/\n/g, ' | ') : null,
        tskItemMeta: itemMeta ? itemMeta.innerText.replace(/\n/g, ' | ') : null,
        healthPill: (() => {
          const el = [...document.querySelectorAll('.topbar button, .topbar [role="button"]')].find(
            (e) => /降级|正常|异常/.test(e.textContent),
          );
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { text: el.textContent.trim(), w: Math.round(r.width), h: Math.round(r.height) };
        })(),
      };
    });
  };

  const before = await measure();

  // 收起侧栏
  const toggle = await page.$('button[aria-label="收起侧栏"]');
  if (toggle) {
    await toggle.click();
    await page.waitForTimeout(500);
  }
  const after = await measure();

  console.log('=== 收起前 ===');
  console.log(JSON.stringify(before, null, 2));
  console.log('\n=== 收起后 ===');
  console.log(JSON.stringify({ sider: after.sider, taskCol: after.taskCol, main: after.main }, null, 2));

  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
