/* FINAL ANSWER 富文本渲染的验收探针：
   1) 表格：横向溢出真的发生、粘性表头真的粘住、数值列右对齐而文字列不右对齐
   2) 安全：不开 rehype-raw 时原生 HTML 与 javascript: 链接都不该进 DOM
   3) 结构：标题降级、重复段折叠、指标与结论前置
   跑法：NODE_PATH=<playwright-core 所在目录> node tools/uicheck/markdown.cjs */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots/markdown');
const { installMocks } = require('./mocks.cjs');

let pass = 0;
const fails = [];
function check(name, ok, got) {
  if (ok) {
    pass += 1;
    console.log(`  ✓ ${name}${got === undefined ? '' : ` — ${got}`}`);
  } else {
    fails.push(`${name}${got === undefined ? '' : ` — got ${JSON.stringify(got)}`}`);
    console.log(`  ✗ ${name}${got === undefined ? '' : ` — got ${JSON.stringify(got)}`}`);
  }
}

async function openResult(page) {
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(400);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(600);
}

async function measure(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const wrap = q('.answer .ast-table-wrap');
    const w = wrap.getBoundingClientRect();
    const headCells = Array.from(wrap.querySelectorAll('thead th'));
    const row2 = Array.from(wrap.querySelectorAll('tbody tr'))[1];
    const cells = Array.from(row2.querySelectorAll('td'));
    const align = (el) => getComputedStyle(el).textAlign;

    // 粘性：把表体滚下去，再看表头是不是还贴在滚动盒顶边
    wrap.scrollTop = 180;
    const stickyTop = wrap.getBoundingClientRect().top;
    const thTop = wrap.querySelector('thead th').getBoundingClientRect().top;
    const afterScroll = { scrollTop: wrap.scrollTop, delta: Math.round(thTop - stickyTop) };

    return {
      overflowX: getComputedStyle(wrap).overflowX,
      scrollW: Math.round(wrap.scrollWidth),
      clientW: Math.round(wrap.clientWidth),
      scrollH: Math.round(wrap.scrollHeight),
      maxH: getComputedStyle(wrap).maxHeight,
      rowCount: wrap.querySelectorAll('tbody tr').length,
      alignTypeCol: align(cells[0]),
      alignPowerCol: align(cells[2]),
      alignDocCol: align(cells[11]),
      alignFactorCol: align(cells[9]),
      headAlignPowerCol: align(headCells[2]),
      headPosition: getComputedStyle(wrap.querySelector('thead th')).position,
      isNumCount: wrap.querySelectorAll('.is-num').length,
      sticky: afterScroll,
      h1: qa('.answer h1').length,
      brs: qa('.answer br').length,
      /** 段内单换行有没有真的换行：量两句的行首 y 差 */
      lineSplit: (() => {
        const p = document.querySelector('.answer .ast-p');
        if (!p) return null;
        const range = document.createRange();
        const topOf = (needle) => {
          const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walk.nextNode())) {
            const i = n.textContent.indexOf(needle);
            if (i >= 0) {
              range.setStart(n, i);
              range.setEnd(n, i + 2);
              return range.getBoundingClientRect().top;
            }
          }
          return null;
        };
        const a = topOf('IEEE');
        const b = topOf('并发系数');
        return a === null || b === null ? null : Math.round(b - a);
      })(),
      h3: qa('.answer h3').length,
      tables: qa('.answer table').length,
      realTable: !!q('.answer table') && q('.answer table').tagName === 'TABLE',
      codeCount: qa('.answer code').length,
      codeFont: q('.answer code') ? getComputedStyle(q('.answer code')).fontFamily : null,
      dupBtn: qa('.ast-dup').length,
      dupText: q('.ast-dup') ? q('.ast-dup').textContent : null,
      dupParents: qa('.ast-dup').map((b) => `${b.parentElement.tagName}.${b.parentElement.className}`),
      paraTexts: qa('.answer p').map((p) => p.textContent.slice(0, 24)),
      dupParents: qa('.ast-dup').map((b) => `${b.parentElement.tagName}.${b.parentElement.className}`),
      paras: qa('.answer p').map((p) => `${p.className}|${p.textContent.slice(0, 26)}`),

      scriptsInAnswer: qa('.answer script').length,
      imgXss: qa('.answer img[src="x"]').length,
      jsHref: qa('a[href^="javascript"]').length,
      rawScriptText: q('.answer') ? q('.answer').textContent.includes('XSS-EXECUTED') : null,
      title: document.title,
      conclusion: q('.sc-main') ? q('.sc-main').textContent : null,
      metricsAboveAnswer: (() => {
        const m = q('.metric-grid--head');
        const a = q('.answer');
        return m && a ? Math.round(a.getBoundingClientRect().top - m.getBoundingClientRect().top) : null;
      })(),
      tiles: qa('.metric-grid--head .metric-label').map((e) => e.textContent.trim()),
      /* ---- 公式区（④）：sub/sup 是否真的成了元素、分数是否真的上下两层 ---- */
      math: (() => {
        const boxes = qa('.ast-math').map((el) => {
          const cs = getComputedStyle(el);
          return {
            overflowX: cs.overflowX,
            whiteSpace: cs.whiteSpace,
            scrollW: el.scrollWidth,
            clientW: el.clientWidth,
            font: cs.fontFamily,
            bg: cs.backgroundColor,
            tag: el.tagName.toLowerCase(),
            /* 作者手写的换行有没有被 nowrap 吃掉：量 first/last 行的 y 差 */
            lineSpan: (() => {
              const r = document.createRange();
              r.selectNodeContents(el);
              const rects = Array.from(r.getClientRects());
              return rects.length ? Math.round(rects[rects.length - 1].top - rects[0].top) : 0;
            })(),
            text: el.textContent.slice(0, 20),
          };
        });
        /* 分数：分子分母必须**错行**（分子底边在分母顶边之上），且分母要有那条中线。
           只看类名在不在等于没验 —— CSS 少写一行 border 它就悄悄变成一行了。 */
        const fracs = qa('.mx-frac').map((el) => {
          const num = el.querySelector('.mx-num');
          const den = el.querySelector('.mx-den');
          const nr = num.getBoundingClientRect();
          const dr = den.getBoundingClientRect();
          const denCs = getComputedStyle(den);
          return {
            stacked: Math.round(nr.bottom) <= Math.round(dr.top) + 1,
            numTop: Math.round(nr.top),
            denTop: Math.round(dr.top),
            h: Math.round(el.getBoundingClientRect().height),
            barW: denCs.borderTopWidth,
            barStyle: denCs.borderTopStyle,
            barColor: denCs.borderTopColor,
            display: getComputedStyle(el).display,
            vAlign: getComputedStyle(el).verticalAlign,
            num: num.textContent,
            den: den.textContent,
          };
        });
        return {
          boxes,
          fracs,
          /* 从代码皮肤换出来的公式：不该再有 code/pre 皮肤 */
          fromCode: qa('.mx-from-code').map((el) => ({
            tag: el.tagName.toLowerCase(),
            inCode: Boolean(el.closest('code') || el.closest('pre')),
            subs: el.querySelectorAll('sub').length,
            text: el.textContent.slice(0, 26),
          })),
          subs: qa('.answer sub').length,
          sups: qa('.answer sup').length,
          /* 所有 <sub> 的文本（含花括号写法与裸简写两种来源），用来同时判正例与反例 */
          bareSubs: qa('.answer sub').map((e) => e.textContent),
          rawText: q('.answer') ? q('.answer').textContent : '',
          untouched: ['my_file.py', 'knowledge_search', 'read_config.js', 'FOO_BAR'],
          /* python 围栏必须还是真代码，且里面的 `x_{1}` 一个字符都没变 */
          py: (() => {
            const c = Array.from(document.querySelectorAll('.answer pre code')).find((el) =>
              /language-python/.test(el.className),
            );
            return c ? { kept: c.textContent.includes('"x_{1}": 1.0'), tag: c.tagName } : null;
          })(),
          // 残留裸 `_{` 只算**非代码**部分：fixture 里的 python 围栏是故意留着 `x_{1}` 的，
          // 把它算进泄漏就等于要求我们把用户的代码改坏。
          leaked: (() => {
            const a = q('.answer');
            if (!a) return null;
            const w = document.createTreeWalker(a, NodeFilter.SHOW_TEXT);
            let t = '';
            let n;
            while ((n = w.nextNode())) {
              if (!n.parentElement.closest('code, pre')) t += n.textContent;
            }
            return /[_^]\{/.test(t);
          })(),
        };
      })(),
      answerRight: (() => {
        const a = q('.answer');
        const r = a.getBoundingClientRect();
        return { right: Math.round(r.right), w: Math.round(r.width) };
      })(),
      quoteBg: q('.ast-quote') ? getComputedStyle(q('.ast-quote')).backgroundColor : null,
      tokens: (() => {
        const cs = getComputedStyle(document.documentElement);
        const names = ['--text-1', '--text-2', '--bg-sunken', '--bg-surface', '--primary', '--border', '--code-bg', '--panel-line'];
        return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue(n).trim()]));
      })(),
    };
  });
}

async function themePass(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => {
    localStorage.setItem('trinity-console.theme', s);
  }, scheme);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await openResult(page);

  console.log(`\n== ${label} ==`);
  const m = await measure(page);
  console.log(JSON.stringify(m, null, 1));

  check('表格渲染成真 <table>', m.realTable && m.tables === 1, `tables=${m.tables}`);
  check('外层 overflow-x: auto', m.overflowX === 'auto', m.overflowX);
  check('宽表真的溢出（scrollWidth > clientWidth）', m.scrollW > m.clientW, `${m.scrollW} > ${m.clientW}`);
  check('纵向封顶后表格可滚（scrollHeight > 上限）', m.scrollH > 520, `${m.scrollH} / ${m.maxH}`);
  check('粘性表头：滚 180px 后仍贴顶（≤2px）', m.headPosition === 'sticky' && Math.abs(m.sticky.delta) <= 2, {
    position: m.headPosition,
    ...m.sticky,
  });
  check('文字列左对齐', m.alignTypeCol !== 'right' && m.alignDocCol !== 'right', [m.alignTypeCol, m.alignDocCol].join(' / '));
  check('数值列右对齐', /right|end/.test(m.alignPowerCol) && /right|end/.test(m.alignFactorCol), `${m.alignPowerCol} / ${m.alignFactorCol}`);
  check('同一列的表头也右对齐', /right|end/.test(m.headAlignPowerCol), m.headAlignPowerCol);
  check('等宽字体作用于行内代码/公式', /mono/i.test(m.codeFont || ''), m.codeFont);

  /* ---- ④ 裸文本公式的排布 ---- */
  const codeBg = scheme === 'dark' ? 'rgb(11, 18, 32)' : 'rgb(239, 241, 245)';
  check(
    '公式区底色 = --code-bg（比面板深一阶）',
    m.math.boxes.every((b) => b.bg === codeBg),
    [m.math.boxes[0] && m.math.boxes[0].bg, m.tokens['--code-bg'], m.tokens['--bg-surface']],
  );
  /* BM25 那条 111 字符的算式必须横向溢出（ nowrap 生效），而不是被折成三行打断结构 */
  check(
    '长算式没被折行打断（单视觉行 ⇒ 只靠横向滚）',
    m.math.boxes.some((b) => b.text.startsWith('scoreBM25') && b.lineSpan <= 2),
    m.math.boxes.map((b) => `${b.text.slice(0, 10)} 行差=${b.lineSpan}`),
  );
  /* fixture 里的公式区共 4 块：三条纯算式段（p.ast-math）+ 一个无语言标记的围栏
     （div.ast-math.mx-from-code）。「行内形式 `…` 与之一致。」那句**不该**成盒 ——
     里面有连续汉字，等宽不换行会把一句话装进代码框。数字跟着 fixture 走。 */
  check(
    '公式区只有 5 块：散文句不套盒',
    m.math.boxes.length === 5,
    m.math.boxes.map((b) => b.text),
  );
  check(
    '公式区：等宽 + overflow-x auto + 不换行',
    m.math.boxes.every(
      (b) => /mono/i.test(b.font) && b.overflowX === 'auto' && ['nowrap', 'pre-wrap'].includes(b.whiteSpace),
    ),
    m.math.boxes.map((b) => [b.tag, b.whiteSpace]),
  );
  check(
    '围栏公式保住作者手写的换行（pre-wrap，两行错开 ≥18px）',
    m.math.boxes.some((b) => b.tag === 'div' && b.whiteSpace === 'pre-wrap' && b.lineSpan >= 18),
    m.math.boxes.map((b) => [b.tag, b.lineSpan]),
  );
  /* fixture 里的公式有 40 处下标（花括号写法 + `P_IT` 这种简写混在一起）、2 处上标。
     数字是实测的，改 fixture 要跟着改。 */
  check('_{} 与 ^{} 变成真上下标', m.math.subs === 40 && m.math.sups === 2, {
    subs: m.math.subs,
    sups: m.math.sups,
  });
  check('代码块之外不再残留裸 _{', m.math.leaked === false, m.math.leaked);

  /* ---- 裸简写下标：正例 + 反例必须在同一张页面里一起判 ----
     只判「P_IT 变成了下标」没有意义 —— 那条规则真正的风险是把
     my_file.py / knowledge_search 也咬掉。两头都钉住才算回归。 */
  check(
    '裸简写 P_IT / η_PoE / P_PoE_chain 渲染成真下标',
    ['IT', 'cam', 'PoE', 'NVR', 'UPS', 'PoE_chain'].every((t) => m.math.bareSubs.includes(t)),
    m.math.bareSubs.join(','),
  );
  check(
    '不误伤：my_file.py 与 knowledge_search 在页面上仍是原样',
    m.math.untouched.every((t) => m.math.rawText.includes(t)) && !m.math.bareSubs.includes('file') &&
      !m.math.bareSubs.includes('search') && !m.math.bareSubs.includes('code'),
    m.math.untouched.filter((t) => !m.math.rawText.includes(t)),
  );

  /* ---- 分数：立起来的才是分数，斜杠排一行的不算 ---- */
  check('分数结构出现（\\frac 与算式里的 A / B）', m.math.fracs.length >= 5, m.math.fracs.length);
  check(
    '分数是上下两层：分子底边不晚于分母顶边',
    m.math.fracs.every((f) => f.stacked),
    m.math.fracs.map((f) => [f.num, f.den, f.stacked]),
  );
  check(
    '分母带那条中线（border-top 有宽度且实线）',
    m.math.fracs.every((f) => parseFloat(f.barW) >= 1 && f.barStyle === 'solid'),
    m.math.fracs.map((f) => [f.barW, f.barStyle]),
  );
  check(
    '分数比单行高（inline-flex 两行 ≥ 1.6 倍行高）',
    m.math.fracs.every((f) => f.h >= 24),
    m.math.fracs.map((f) => f.h),
  );
  check(
    '行内分数字号不塌陷、垂直对齐走 middle（不是把下一行顶开）',
    m.math.fracs.every((f) => f.display === 'inline-flex' && f.vAlign === 'middle'),
    m.math.fracs.map((f) => [f.display, f.vAlign]),
  );
  check(
    '代码皮肤里的公式换出了 code/pre',
    m.math.fromCode.length >= 2 && m.math.fromCode.every((f) => !f.inCode),
    m.math.fromCode.map((f) => [f.tag, f.inCode, f.text]),
  );
  check(
    '围栏公式里也有真下标',
    m.math.fromCode.some((f) => f.subs >= 1),
    m.math.fromCode.map((f) => f.subs),
  );
  check(
    '```python 仍是真代码，`x_{1}` 一字未改',
    m.math.py && m.math.py.kept && m.math.py.tag === 'CODE',
    m.math.py,
  );
  check('标题降级：答案里没有 h1', m.h1 === 0, `h1=${m.h1} h3=${m.h3}`);
  check('段内单换行没被 Markdown 吞掉', m.brs >= 1 && m.lineSplit > 12, `br=${m.brs} 行差=${m.lineSplit}`);
  console.log('  段落清单：', JSON.stringify(m.paraTexts));
  console.log('  折叠按钮父级：', JSON.stringify(m.dupParents), ' count=', m.dupBtn);
  check('重复段折叠成一条开关', m.dupBtn === 1, m.dupBtn);
  check('XSS：答案内无 script 节点', m.scriptsInAnswer === 0, m.scriptsInAnswer);
  check('XSS：onerror 的 img 没进 DOM', m.imgXss === 0, m.imgXss);
  check('XSS：没有 javascript: 链接', m.jsHref === 0, m.jsHref);
  console.log('  原生 HTML 是否以字面文本露出（仅记录，不判失败）：', m.rawScriptText);

  check('XSS：document.title 未被改写', !/XSS/.test(m.title), m.title);
  check('结论前置：摘要条取到结论段', /结论/.test(m.conclusion || ''), JSON.stringify(m.conclusion));
  check('指标卡在答案之上', m.metricsAboveAnswer !== null && m.metricsAboveAnswer > 0, m.metricsAboveAnswer);
  check('三块指标卡都在', m.tiles.length === 3, m.tiles.join(' / '));

  // 折叠段可展开
  await page.locator('.ast-dup').first().click();
  await page.waitForTimeout(150);
  const expanded = await page.evaluate(() => ({
    btn: document.querySelectorAll('.ast-dup').length,
    hit: Array.from(document.querySelectorAll('.answer .ast-p')).filter(
      (p) => p.textContent.startsWith('其中 0.85'),
    ).length,
  }));
  check('点开后重复段原文显示两处、按钮消失', expanded.btn === 0 && expanded.hit === 2, expanded);

  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.result-wrap').screenshot({ path: path.join(OUT, `${label}-result.png`) });
  // 公式区特写：sub/sup 与「深一阶底 + 横向溢出」只能看像素定案
  await page.evaluate(() =>
    document.querySelectorAll('.ast-math')[1].scrollIntoView({ block: 'center' }),
  );
  await page.waitForTimeout(300);
  await page.locator('.answer').screenshot({ path: path.join(OUT, `${label}-math.png`) });
  /* 公式区特写：整张答案图里 12px 的分数看不清结构，验收要看这一张。
     clip 用文档坐标（视口坐标 + 滚动量），配 fullPage 才不受当前滚位影响。 */
  const crop = await page.evaluate(() => {
    const first = document.querySelector('.answer .ast-math');
    const fences = Array.from(document.querySelectorAll('.answer .mx-from-code'));
    const last = fences[fences.length - 1];
    const wrap = document.querySelector('.answer');
    if (!first || !last || !wrap) return null;
    const a = first.getBoundingClientRect();
    const b = last.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return {
      x: Math.max(0, w.left + scrollX - 6),
      y: a.top + scrollY - 12,
      width: w.width + 12,
      height: b.bottom - a.top + 24,
    };
  });
  if (crop) {
    await page.screenshot({ path: path.join(OUT, `${label}-math-crop.png`), clip: crop, fullPage: true });
    console.log(`  ✓ 公式特写 → ${label}-math-crop.png  ${JSON.stringify(crop)}`);
  } else {
    check('公式特写裁得到（首块公式 + 围栏都在）', false, crop);
  }
  // 长表格特写：滚到中段后按视口裁剪 —— 元素截图会把整段可滚内容拼成长图，
  // 那样既看不出粘性表头、也看不出横向溢出，等于没验。
  await page.evaluate(() => {
    const w = document.querySelector('.answer .ast-table-wrap');
    w.scrollTop = 200;
    w.scrollLeft = 0;
  });
  await page.waitForTimeout(150);
  // 把表格整块居中进视口（scrollIntoViewIfNeeded 只保证「露出一点」，
  // 表头那 38px 会被视口上边缘切掉，截图看起来就像表头没粘住）
  await page.evaluate(() =>
    document.querySelector('.answer .ast-table-wrap').scrollIntoView({ block: 'center' }),
  );
  await page.waitForTimeout(400);
  const geo = await page.evaluate(() => {
    const w = document.querySelector('.answer .ast-table-wrap');
    const th = w.querySelector('thead th');
    const wr = w.getBoundingClientRect();
    const tr = th.getBoundingClientRect();
    return {
      wrapTop: Math.round(wr.top),
      wrapH: Math.round(wr.height),
      thTop: Math.round(tr.top),
      thH: Math.round(tr.height),
      thLeft: Math.round(tr.left),
      scrollTop: w.scrollTop,
      scrollLeft: Math.round(w.scrollLeft),
    };
  });
  console.log('  表格几何：', JSON.stringify(geo));
  // 直接截视口：clip 的坐标空间在「页面自己也要滚」的布局里对不准（试了视口坐标与
  // 文档坐标两种，都会被页面滚动量偏移掉），而粘性表头只要滚进视口就能看见。
  await page.screenshot({ path: path.join(OUT, `${label}-table-scrolled.png`) });
  await page.screenshot({ path: path.join(OUT, `${label}-full.png`), fullPage: true });
  console.log(`  ✓ 截图 → ${label}-result / ${label}-table-scrolled / ${label}-full`);
  check('无 pageerror', errors.length === 0, errors.slice(0, 3));

  return m;
}

/** ③ P1 窄屏：长算式与宽表都必须「自己滚」，不许把整页撑出横向滚动条。 */
async function narrowPass(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 460, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 窄屏下任务列表收进抽屉、页签可能被挤到视口外，Playwright 的点击要过命中测试
     （报 "element is outside of the viewport"）。这里只是要切到「运行结果」页签，
     直接派发 .click() 就够 —— 布局本身才是这一趟要验的东西。 */
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector('.tsk-item').click());
  await page.waitForTimeout(600);
  await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
      /运行结果/.test(t.textContent || ''),
    );
    tab.click();
  });
  await page.waitForTimeout(400);

  console.log('\n== 窄屏 460px ==');
  const g = await page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const box = (el) =>
      el
        ? {
            overflowX: getComputedStyle(el).overflowX,
            scrollW: el.scrollWidth,
            clientW: el.clientWidth,
          }
        : null;
    return {
      pageScrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      answerRight: Math.round(q('.answer') ? q('.answer').getBoundingClientRect().right : -1),
      math: qa('.ast-math').map((el) => ({ ...box(el), text: el.textContent })),
      table: box(q('.answer .ast-table-wrap')),
      pre: box(q('.ast-pre')),
    };
  });
  check('整页没有横向溢出', g.pageScrollX <= 0, g.pageScrollX);
  check('答案没顶破视口右边缘', g.answerRight > 0 && g.answerRight <= 460, g.answerRight);
  check(
    '窄屏：长算式自己横向滚、页面不被撑破',
    /* 短算式（η_Carnot 那条）在 460px 下本来就读得完，要求它「也溢出」是假判据 ——
       要判的是「长的那条靠横向滚，不靠把整页撑出滚动条」。 */
    g.math.length === 5 &&
      g.math.some((b) => /^scoreBM25/.test(b.text) && b.overflowX === 'auto' && b.scrollW > b.clientW),
    g.math.map((b) => `${b.text.slice(0, 10)} ${b.scrollW}/${b.clientW}`),
  );
  check('宽表自己横向滚', g.table.overflowX === 'auto' && g.table.scrollW > g.table.clientW, g.table);
  check('无 pageerror', errors.length === 0, errors.slice(0, 3));

  await page.locator('.answer').screenshot({ path: path.join(OUT, 'narrow-460.png') });
  console.log('  ✓ 截图 → narrow-460');
  await ctx.close();
}

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const light = await themePass(browser, 'light', 'light');
  const dark = await themePass(browser, 'dark', 'dark');
  check(
    '亮暗主题变量确实换了底',
    light.tokens['--bg-surface'] !== dark.tokens['--bg-surface'],
    `${light.tokens['--bg-surface']} → ${dark.tokens['--bg-surface']}`,
  );
  await narrowPass(browser);
  await browser.close();

  console.log(`\nmarkdown probe: ${pass} 通过 / ${pass + fails.length} 断言`);
  if (fails.length) {
    console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
    process.exit(1);
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
