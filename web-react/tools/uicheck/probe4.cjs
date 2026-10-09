/* 参考包融合项落地探针：不靠肉眼，直接读 computed style 验证。
 * 用法：node tools/uicheck/probe4.cjs
 */
const { chromium } = require('playwright-core');
const { resolveChrome } = require('./_chrome.cjs');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';

(async () => {
  const browser = await chromium.launch({
    executablePath: resolveChrome(),
  });
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  const probe = await page.evaluate(() => {
    const cs = (sel, props) => {
      const el = document.querySelector(sel);
      if (!el) return { missing: sel };
      const s = getComputedStyle(el);
      const out = {};
      for (const p of props) out[p] = s.getPropertyValue(p).trim();
      return out;
    };
    return {
      brandMarkSvg: !!document.querySelector('.brand-mark svg'),
      brandMarkCircles: document.querySelectorAll('.brand-mark circle').length,
      brandTitle: cs('.brand-title', [
        'background-image',
        'color',
        '-webkit-background-clip',
        'font-size',
      ]),
      strokeIcon: cs('.stroke-icon', ['stroke-width', 'stroke-linecap']),
      navIcon: cs('.nav-icon', ['font-size', 'color']),
      pageTitleIcon: cs('.page-title .anticon', ['font-size', 'color']),
      surfaceTitleIcon: cs('.surface-title .anticon', ['font-size', 'color']),
      liveDot: cs('.dot--live', ['animation-name', 'animation-duration']),
      logRow: cs('.log-row', ['animation-name', 'animation-duration']),
      pageHead: cs('.page-head', ['animation-name', 'animation-duration']),
      // 主题 token 抽样
      tokens: {
        text3: getComputedStyle(document.documentElement)
          .getPropertyValue('--text-3')
          .trim(),
        bgApp: getComputedStyle(document.documentElement)
          .getPropertyValue('--bg-app')
          .trim(),
        durEnter: getComputedStyle(document.documentElement)
          .getPropertyValue('--dur-enter')
          .trim(),
        easeEmph: getComputedStyle(document.documentElement)
          .getPropertyValue('--ease-emph')
          .trim(),
        iconStroke: getComputedStyle(document.documentElement)
          .getPropertyValue('--icon-stroke')
          .trim(),
      },
    };
  });

  console.log(JSON.stringify(probe, null, 2));
  console.log('\nconsole errors:', errors.length, errors.slice(0, 5));
  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
