/* 走查用**测量脚本**（不是趟：只出数、不判绿，`check()` 都没有）。
 *
 * 为什么留着：EV-02 / EV-04 / EV-05 这三条的原始读数（标题列宽度、实心按钮白字、
 * 最优行底色上的绿字）**只有这里能复算** —— X / Y 趟钉的是各自那两条缺陷的验收，
 * 对比度扫描与全站表格藏列普查不在 running.cjs 里。删掉就等于报告里那些 ① 级数字
 * 变成"当时量过"，以后复核只能重造脚本。
 *
 * 为什么不并进 X 趟：X 趟走的是 mock（不打真后端），这个走的是**真后端 + 真报告 JSON**；
 * 而且它是普查（全页所有表 / 所有文本节点），塞进正式趟会让每次全量都多跑一趟普查。
 * ⇒ 后续：EV-04 / EV-05 修完后，把"改完必须不复发"的那几个数并入正式趟次，本脚本即可退役。
 *
 * 量三件事：
 *   1) 窄屏适配：文档横向溢出、表格里被藏掉的列、底部标签栏与左侧图标栏是否同时出现；
 *   2) 配色对比度：对**渲染后**的每个叶子文本节点算 WCAG 对比度（前景按 alpha 压到实际底色上），
 *      亮/暗两主题各跑一遍 —— 口径是"在每种行底色上量"，不是拿 token 表算一遍就交差；
 *   3) 控制台报错与失败请求、长任务。
 *
 * 用法：NODE_PATH=<workspace/node_modules> node tools/uicheck/eval_ux_probe.cjs
 *      可用 WIDTHS=390 THEMES=dark 只跑一档；BASE_URL 指别的前端。
 */
const { chromium } = require('playwright-core');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = __dirname + '/final/eval-review';
const results = [];

/* 在页面里跑的那段：返回渲染后的对比度清单 + 布局读数。 */
const SWEEP = () => {
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (r, g, b) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  /* 实际底色 = 从自身往上把每一层半透明背景**逐层合成**到不透明底上。
     ⚠️ 不能只取"第一个 a>0 的背景"：delta chip / best-tag 用的是 rgba(色, .15)，
     直接拿未合成的 rgb 当底色会算出 1:1 的假红（第一版就误报过两条）。 */
  const bgOf = (el) => {
    const chain = [];
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { chain.push(c); if (c.a >= 0.999) break; }
      n = n.parentElement;
    }
    let out = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    if (out.a < 1) out = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = chain.length - 1; i >= 0; i--) {
      const c = chain[i];
      out = { r: c.a * c.r + (1 - c.a) * out.r, g: c.a * c.g + (1 - c.a) * out.g, b: c.a * c.b + (1 - c.a) * out.b, a: 1 };
    }
    return out;
  };
  const seen = new Set();
  const items = [];
  document.querySelectorAll('main *').forEach((el) => {
    const txt = (el.textContent || '').trim();
    if (!txt || txt.length > 44 || el.children.length > 0) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.opacity === '0' || cs.display === 'none') return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const fg = parse(cs.color);
    if (!fg || fg.a < 0.05) return;
    const bg = bgOf(el);
    const mix = { r: fg.a * fg.r + (1 - fg.a) * bg.r, g: fg.a * fg.g + (1 - fg.a) * bg.g, b: fg.a * fg.b + (1 - fg.a) * bg.b };
    const L1 = lum(mix.r, mix.g, mix.b);
    const L2 = lum(bg.r, bg.g, bg.b);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const fs = parseFloat(cs.fontSize);
    const fw = parseInt(cs.fontWeight, 10) || 400;
    const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    const need = large ? 3 : 4.5;
    const key = el.className.toString().slice(0, 28) + '|' + cs.color + '|' + Math.round(bg.r) + ',' + Math.round(bg.g) + ',' + Math.round(bg.b) + '|' + fs;
    if (seen.has(key)) return;
    seen.add(key);
    items.push({
      txt: txt.slice(0, 20), cls: el.className.toString().slice(0, 30), fs, fw,
      ratio: +ratio.toFixed(2), need, pass: ratio >= need,
      bg: 'rgb(' + [bg.r, bg.g, bg.b].map((v) => Math.round(v)).join(',') + ')', color: cs.color,
    });
  });

  /* 布局读数 */
  const docOver = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  const tables = [...document.querySelectorAll('table')].map((t) => {
    const cols = [...t.querySelectorAll('thead th')];
    const vw = window.innerWidth;
    const hidden = cols.filter((c) => { const r = c.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; }).length;
    const box = t.closest('.scrollx-box');
    const frame = t.closest('.scrollx-frame');
    const inner = t.closest('.ant-table-content');
    return {
      cols: cols.length, hiddenCols: hidden,
      box: box ? { sw: box.scrollWidth, cw: box.clientWidth, tabindex: box.getAttribute('tabindex'), role: box.getAttribute('role'), aria: (box.getAttribute('aria-label') || '').slice(0, 16) } : null,
      innerOverflowX: inner ? getComputedStyle(inner).overflowX : null,
      frame: frame ? { scrollable: frame.dataset.scrollable, atStart: frame.dataset.atStart, atEnd: frame.dataset.atEnd, fadeR: getComputedStyle(frame, '::after').opacity, fadeL: getComputedStyle(frame, '::before').opacity } : null,
    };
  });
  const rail = document.querySelector('[aria-label="主导航"]');
  const tabbar = document.querySelector('.app-tabbar');
  const railVisible = rail ? rail.getBoundingClientRect().width > 0 : false;
  const tabbarVisible = tabbar ? getComputedStyle(tabbar).display !== 'none' : false;
  const grids = [...document.querySelectorAll('.metric-grid')].map((g) => getComputedStyle(g).gridTemplateColumns.split(' ').length);
  const fs = {};
  ['h1', 'h2', '.metric-label', '.metric-value', '.page-desc', 'td', 'th'].forEach((sel) => {
    const el = document.querySelector(sel);
    if (el) { const c = getComputedStyle(el); fs[sel] = c.fontSize + '/' + c.fontWeight + '/' + c.lineHeight; }
  });
  /* 窄屏下区块标题会不会被截（.surface-head 是不换行的 flex，右边还有报告 chip） */
  const titles = [...document.querySelectorAll('.surface-title, h2')].map((h) => {
    const cs = getComputedStyle(h);
    const r = h.getBoundingClientRect();
    const head = h.closest('.surface-head');
    const sib = head ? [...head.children].map((c) => `${c.tagName}.${c.className.toString().slice(0, 16)}=${Math.round(c.getBoundingClientRect().width)}`) : [];
    return { txt: h.textContent.trim().slice(0, 22), w: Math.round(r.width), sw: h.scrollWidth, clipped: h.scrollWidth > h.clientWidth + 1, to: cs.textOverflow, headWrap: head ? getComputedStyle(head).flexWrap : null, headKids: sib };
  });
  return {
    vw: window.innerWidth, docOver, tables, railVisible, tabbarVisible, bothNavs: railVisible && tabbarVisible, grids, fs, titles,
    contrastCount: items.length, fails: items.filter((i) => !i.pass),
    worst: items.slice().sort((a, b) => a.ratio - b.ratio).slice(0, 8),
  };
};

async function visit(browser, { path, vw, vh, theme, tag }) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, colorScheme: theme, locale: 'zh-CN' });
  await ctx.addInitScript((t) => localStorage.setItem('trinity-console.theme', t), theme);
  const page = await ctx.newPage();
  const consoleErr = [];
  const failed = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') consoleErr.push(m.type() + ': ' + m.text().slice(0, 120)); });
  page.on('pageerror', (e) => consoleErr.push('pageerror: ' + e.message.slice(0, 120)));
  page.on('requestfailed', (r) => failed.push(r.url().replace(BASE, '') + ' ' + (r.failure() || {}).errorText));
  page.on('response', (r) => { if (r.status() >= 400) failed.push('HTTP ' + r.status() + ' ' + r.url().replace(BASE, '')); });
  const t0 = Date.now();
  await page.goto(BASE + path, { waitUntil: 'networkidle' });
  const loadMs = Date.now() - t0;
  await page.waitForTimeout(900);
  const long = await page.evaluate(() => new Promise((res) => {
    const out = [];
    try { new PerformanceObserver((l) => l.getEntries().forEach((e) => out.push(Math.round(e.duration)))).observe({ entryTypes: ['longtask'] }); } catch (e) {}
    setTimeout(() => res(out), 1500);
  }));
  const data = await page.evaluate(SWEEP);
  await page.screenshot({ path: `${OUT}/${tag}.png`, fullPage: true });
  results.push({ tag, path, vw, theme, loadMs, longTasksMs: long, ...data });
  console.log(
    `[${tag}] docOver=${data.docOver} navs=${data.bothNavs ? 'rail+tabbar' : 'one'} ` +
    `tables=${data.tables.map((t) => `${t.cols}列/藏${t.hiddenCols}/box=${t.box ? `${t.box.sw}>${t.box.cw},tab=${t.box.tabindex}` : 'none'}/inner=${t.innerOverflowX}/fr=${t.frame ? `${t.frame.scrollable}${t.frame.atStart}${t.frame.atEnd} fadeR=${t.frame.fadeR}` : 'none'}`).join('  ')}` +
    `grids=${data.grids.join(',')} 文本项=${data.contrastCount} AA不过=${data.fails.length} ` +
    `load=${loadMs}ms long=${long.join(',') || '无'}`
  );
  for (const f of data.fails) {
    console.log(`   ✗ ${f.ratio}:1 (需${f.need}) ${f.fs}px/${f.fw} "${f.txt}" ${f.color} on ${f.bg} [${f.cls}]`);
  }
  for (const t of data.titles) {
    console.log(`   标题 "${t.txt}" w=${t.w} sw=${t.sw} clipped=${t.clipped} textOverflow=${t.to} headWrap=${t.headWrap} 同排=[${t.headKids.join(' ')}]`);
  }
  await ctx.close();
  return data;
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  const widths = (process.env.WIDTHS || '1440,768,390').split(',').map(Number);
  const themes = (process.env.THEMES || 'light,dark').split(',');
  for (const vw of widths) {
    for (const theme of themes) {
      await visit(browser, { path: '/eval', vw, vh: 900, theme, tag: `s-eval-${vw}-${theme}` });
    }
  }
  /* 抽屉里的可 Tab 控件：窄屏抽屉收起时是否仍可被 Tab 走到 */
  const ctx = await browser.newContext({ viewport: { width: 724, height: 900 }, colorScheme: 'light' });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  await page.goto(BASE + '/tasks', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const drawer = await page.evaluate(() => {
    const panel = document.querySelector('[aria-label="任务列表"]');
    if (!panel) return { found: false };
    const cs = getComputedStyle(panel);
    const r = panel.getBoundingClientRect();
    const tabbable = [...panel.querySelectorAll('button, input, [tabindex]')].filter((e) => !e.disabled && e.tabIndex >= 0);
    return {
      found: true, x: Math.round(r.x), w: Math.round(r.width), transform: cs.transform,
      visibility: cs.visibility, ariaHidden: panel.getAttribute('aria-hidden'), inert: !!panel.inert,
      tabbableCount: tabbable.length,
      offscreenTabbable: tabbable.filter((e) => e.getBoundingClientRect().right < 1).length,
      firstTabbableInDomOrder: (() => {
        const all = [...document.querySelectorAll('button, input, [tabindex]')].filter((e) => !e.disabled && e.tabIndex >= 0);
        const idx = all.findIndex((e) => panel.contains(e));
        return { totalTabbable: all.length, firstDrawerIndex: idx };
      })(),
    };
  });
  console.log(JSON.stringify({ tag: 'drawer-724', drawer }, null, 1));
  await ctx.close();
  require('fs').writeFileSync(`${OUT}/sweep.json`, JSON.stringify(results, null, 1));
  await browser.close();
})();
