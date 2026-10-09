/* 第二轮 5 项改动的验收探针：只读测量 + 点击交互，不改任何东西。 */
const { chromium } = require('playwright-core');
// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // ---------- 1. 配置区 ----------
  const composer = await page.evaluate(() => {
    const cfgs = [...document.querySelectorAll('.cfg')];
    const c = document.querySelector('.composer');
    const r = c.getBoundingClientRect();
    const sum = document.querySelector('.composer-summary');
    const dot = document.querySelector('.cfg--switch.is-on .cfg-dot');
    const dotCs = dot ? getComputedStyle(dot) : null;
    return {
      composerH: Math.round(r.height),
      cfgCount: cfgs.length,
      cfgTexts: cfgs.map((e) => e.textContent.trim()),
      cfgHeights: cfgs.map((e) => Math.round(e.getBoundingClientRect().height)),
      summary: sum ? sum.textContent.trim() : null,
      switchOnDotBg: dotCs ? dotCs.backgroundColor : null,
    };
  });

  // ---------- 2. 任务列表 ----------
  const list = await page.evaluate(() => {
    const item = document.querySelector('.tsk-item');
    if (!item) return null;
    const r = item.getBoundingClientRect();
    const l1 = item.querySelector('.tsk-line1');
    const l2 = item.querySelector('.tsk-line2');
    const stats = item.querySelector('.tsk-stats');
    return {
      itemH: Math.round(r.height),
      line1: l1 ? l1.innerText.replace(/\n/g, ' | ') : null,
      line2: l2 ? l2.innerText.replace(/\n/g, ' | ') : null,
      statsText: stats ? stats.innerText.replace(/\n/g, ' ') : null,
      // 溢出检测：stats 被 ellipsis 裁掉就会 scrollWidth > clientWidth
      statsClipped: stats ? stats.scrollWidth > stats.clientWidth + 1 : null,
      titleClipped: (() => {
        const t = item.querySelector('.tsk-title');
        return t ? t.scrollWidth > t.clientWidth + 1 : null;
      })(),
    };
  });

  // ---------- 3. 降级胶囊 ----------
  await page.click('.status-pill');
  await page.waitForTimeout(600);
  const health = await page.evaluate(() => {
    const pop = document.querySelector('.health-pop');
    if (!pop) return { missing: true };
    const rows = [...pop.querySelectorAll('.health-row')].map((r) => ({
      name: r.querySelector('.health-name')?.textContent,
      state: r.querySelector('.health-state')?.textContent,
      detail: r.querySelector('.health-detail')?.textContent?.slice(0, 60),
      hasFix: !!r.querySelector('.health-fix'),
    }));
    return { head: pop.querySelector('.health-pop-head')?.textContent, rows };
  });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  // ---------- 4. 新建任务反馈 ----------
  // 先填点内容，再点新建，验证是否真的被清空
  await page.fill('.composer-input', '这是一段用来测试新建清空的文本');
  await page.waitForTimeout(200);
  const beforeNew = await page.inputValue('.composer-input');
  await page.click('.task-col-head button');
  await page.waitForTimeout(400);
  const afterNew = await page.evaluate(() => ({
    inputValue: document.querySelector('.composer-input')?.value,
    badge: document.querySelector('.composer-badge')?.textContent?.trim() ?? null,
    isNew: !!document.querySelector('.composer.is-new'),
    composerH: Math.round(document.querySelector('.composer').getBoundingClientRect().height),
  }));

  console.log('=== 1. 配置区 ===');
  console.log(JSON.stringify(composer, null, 2));
  console.log('\n=== 2. 任务列表 ===');
  console.log(JSON.stringify(list, null, 2));
  console.log('\n=== 3. 降级体检弹层 ===');
  console.log(JSON.stringify(health, null, 2));
  console.log('\n=== 4. 新建任务反馈 ===');
  console.log(JSON.stringify({ beforeNew, ...afterNew }, null, 2));
  console.log('\nconsole errors:', errors.length, errors.slice(0, 5));

  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
