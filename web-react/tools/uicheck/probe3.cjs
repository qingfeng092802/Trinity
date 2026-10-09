/** 交互探针：选中任务后主区是否正确回填 + 404 资源定位。 */
const { chromium } = require('playwright-core');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('response', (r) => {
    if (r.status() >= 400) console.log(`[${r.status()}] ${r.url()}`);
  });

  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const before = await page.$$eval('.tl-item', (n) => n.length);
  await page.click('.tl-item');
  await page.waitForTimeout(3000);

  const after = await page.evaluate(() => ({
    statusText: document.querySelector('.statusbar')?.textContent?.trim().slice(0, 120),
    activeItem: document.querySelector('.tl-item.is-active .tl-title')?.textContent?.slice(0, 40),
    logRows: document.querySelectorAll('.log-row').length,
    logIdleStill: !!document.querySelector('.log-idle'),
    tabs: Array.from(document.querySelectorAll('.ant-tabs-tab')).map((t) => t.textContent.trim()),
  }));
  console.log('tl-items before =', before);
  console.log('after select =', JSON.stringify(after));

  // 切到运行结果页签看是否回填
  const tabBtns = await page.$$('.ant-tabs-tab');
  if (tabBtns[1]) {
    await tabBtns[1].click();
    await page.waitForTimeout(600);
    const res = await page.evaluate(() => ({
      hasAnswer: !!document.querySelector('.answer-block'),
      answerLen: document.querySelector('.answer-block')?.textContent?.length ?? 0,
      emptyTitle: document.querySelector('.empty-title')?.textContent ?? null,
    }));
    console.log('result tab =', JSON.stringify(res));
  }

  await browser.close();
})();
