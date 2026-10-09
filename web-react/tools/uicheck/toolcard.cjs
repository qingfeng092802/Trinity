/* 工具调用卡片「用户视角」改造的验收探针：
   1) 意图标题：thought 优先、无 thought 退回「动词：关键入参」、字典外工具不瞎编
   2) Tooltip：大白话 + 计费口径 + 注册表参数；键盘聚焦也要能打开
   3) 注册表真的被拉了一次（/api/tools），拉不到时也不该白屏
   跑法：NODE_PATH=<playwright-core 所在目录> node tools/uicheck/toolcard.cjs */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots/toolcard');
const { installMocks, traceBody } = require('./mocks.cjs');

/* seq 12 = 超时那条 code_exec：入参是一整段 15 行 Python，出参是沙箱的超时两行。
   断言直接拿 fixture 原文比，改 fixture 不用改断言。 */
const EV12 = (traceBody.items || traceBody.events || []).find((e) => e.event_seq === 12);
const WANT_CODE = EV12.arguments.code;
const WANT_OUT = EV12.observation;

let pass = 0;
const fails = [];
function check(name, cond, got) {
  const good = Boolean(cond);
  if (good) pass += 1;
  else fails.push(`${name} — got ${JSON.stringify(got)}`);
  console.log(`  ${good ? '✓' : '✗'} ${name}${got === undefined ? '' : ` — ${JSON.stringify(got)}`}`);
}

/** Tooltip 第三行的实测对比度：AntD 的 Tooltip 底在两个主题下都可能是深色，
 *  而 --text-inverse 在暗色主题里是**近黑** —— 拿它当浅色字用会糊成一片。 */
async function tipTone(page) {
  return page.evaluate(() => {
    const inner = document.querySelector('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner');
    const note = inner && inner.querySelector('.tt-note');
    if (!note) return null;
    const lum = (c) => {
      const m = c.match(/\d+(\.\d+)?/g);
      if (!m) return null;
      const [r, g, b] = m.slice(0, 3).map((x) => {
        const s = Number(x) / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const cs = getComputedStyle(note);
    const is = getComputedStyle(inner);
    const a = Number(cs.opacity === '' ? 1 : cs.opacity);
    // 半透明前景先按 Tooltip 底色压成实色再算
    const mix = (fg, bg) => {
      const f = fg.match(/\d+(\.\d+)?/g).map(Number);
      const b = bg.match(/\d+(\.\d+)?/g).map(Number);
      return `rgb(${f.slice(0, 3).map((c, i) => Math.round(c * a + b[i] * (1 - a))).join(', ')}, 1)`;
    };
    const ratio = (x, y) => {
      const l1 = lum(x);
      const l2 = lum(y);
      return +((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2);
    };
    return {
      innerBg: is.backgroundColor,
      noteColor: cs.color,
      opacity: a,
      ratio: ratio(mix(cs.color, is.backgroundColor), is.backgroundColor),
    };
  });
}

async function openTools(page) {
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(500);
  await page.getByRole('tab', { name: /工具调用/ }).click();
  await page.waitForTimeout(400);
}

/** 悬停第 n 张卡的工具名，读 Tooltip 正文。 */
async function tipOf(page, n) {
  await page.locator('.tool-name').nth(n).hover();
  await page.waitForTimeout(400);
  const txt = await page
    .locator('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner')
    .first()
    .innerText()
    .catch(() => '');
  await page.mouse.move(4, 4);
  await page.waitForTimeout(250);
  return txt.replace(/\s+/g, ' ').trim();
}

/** P0/P1：code_exec 的入参必须按「代码」渲染，而不是 JSON 字符串叶子。
 *  逐条对着 DOM 实测，不看源码想当然。 */
async function codePass(page, want, obs) {
  const box = await page.evaluate(
    ([src, outText]) => {
      const card = Array.from(document.querySelectorAll('.tool-card')).find((c) => {
        const name = c.querySelector('.tool-name');
        return name && name.innerText.trim() === 'code_exec' && c.classList.contains('is-warn');
      });
      if (!card) return { missing: '超时那张 code_exec 卡没找到' };
      const fields = Array.from(card.querySelectorAll('.grid-2 .field'));
      const inp = fields[0];
      const out = fields[1];
      const pre = inp && inp.querySelector('pre.code');
      const cs = pre && getComputedStyle(pre);
      const cardBox = card.getBoundingClientRect();
      const b0 = inp && inp.getBoundingClientRect();
      const b1 = out && out.getBoundingClientRect();
      return {
        hasJv: !!(inp && inp.querySelector('.jv')),
        text: pre ? pre.textContent : null,
        dataLines: pre ? pre.getAttribute('data-lines') : null,
        whiteSpace: cs ? cs.whiteSpace : null,
        wordBreak: cs ? cs.wordBreak : null,
        maxHeight: cs ? cs.maxHeight : null,
        overflowY: cs ? cs.overflowY : null,
        clamped: pre ? pre.classList.contains('is-clamped') : null,
        clientH: pre ? pre.clientHeight : null,
        scrollH: pre ? pre.scrollHeight : null,
        tokens: pre
          ? {
              kw: pre.querySelectorAll('.py-kw').length,
              str: pre.querySelectorAll('.py-str').length,
              com: pre.querySelectorAll('.py-com').length,
            }
          : null,
        meta: inp ? (inp.querySelector('.arg-meta')?.innerText ?? null) : null,
        label: inp ? (inp.querySelector('.field-label')?.innerText ?? null) : null,
        outCopyBtn: !!(out && out.querySelector('.field-head .copy-btn')),
        /* 堆叠判定：两块同宽同列、出参在入参下方 */
        stacked: !!(b0 && b1) && Math.abs(b0.width - b1.width) < 2 && b1.top > b0.bottom - 2,
        fullWidth: b0 ? Math.abs(cardBox.width - 28 - b0.width) < 6 : false,
      };
    },
    [want, obs],
  );
  console.log(JSON.stringify(box, null, 1));

  check('入参不再走 JSON 树（.jv 已经让位给代码块）', box.hasJv === false, box.hasJv);
  check('P0 无损：DOM 里的文本逐字等于入参源码', box.text === want, (box.text || '').slice(0, 60));
  check('真实换行渲染出来了（不是 \\n 两字符）', /import os, re, time/.test(box.text || '') && !/\\n/.test(box.text || ''), (box.text || '').slice(0, 40));
  check('开头是 docstring，没有被键名截断成「co"」', (box.text || '').startsWith('"""'), (box.text || '').slice(0, 12));
  check('行数按源码算（15 行）', box.dataLines === '15', box.dataLines);
  check('white-space: pre —— 缩进原样、长行横向滚动而不是硬拆', box.whiteSpace === 'pre' && box.wordBreak === 'normal', [box.whiteSpace, box.wordBreak]);
  check('四类色上色了（关键字 / 串 / 注释各有实例）', box.tokens && box.tokens.kw >= 5 && box.tokens.str >= 3 && box.tokens.com === 1, box.tokens);
  check('字段头补了其余入参小字', box.meta === 'timeout_s=30', box.meta);

  check('P1 折叠态：高度上限交给外部按钮，块内不开纵向滚动条', box.clamped === true && box.overflowY === 'hidden', [box.clamped, box.overflowY]);
  check('折叠态确实截断了（还有内容在下面）', box.clientH < box.scrollH, [box.clientH, box.scrollH]);
  check('P1 堆叠：入参 / 出参各占整幅，出参在入参下方', box.stacked === true && box.fullWidth === true, [box.stacked, box.fullWidth]);

  const more = page.locator('.code-more').first();
  check('「展开全文」按钮在（超过 12 行才给）', (await more.count()) === 1, await more.innerText().catch(() => null));
  await more.click();
  await page.waitForTimeout(250);
  /* 查询必须锁在这张卡上：另一张 code_exec（4 行那段）也渲染代码块但没有折叠按钮，
     全局 querySelector 会拿到它，于是「展开后全可见」这条会因为**错误的理由**通过。 */
  const opened = await page.evaluate(() => {
    const pre = document.querySelector('.tool-card.is-warn pre.code.code-src');
    const cs = pre && getComputedStyle(pre);
    return {
      lines: pre ? pre.getAttribute('data-lines') : null,
      clamped: pre ? pre.classList.contains('is-clamped') : null,
      overflowY: cs ? cs.overflowY : null,
      fits: pre ? pre.clientHeight >= pre.scrollHeight : null,
      btn: (document.querySelector('.code-more') || {}).innerText || null,
    };
  });
  check('展开的是那张 15 行的卡（没测错对象）', opened.lines === '15', opened.lines);
  check('展开后 15 行全部可见，不需要在块内滚动', opened.clamped === false && opened.fits === true, opened);
  check('展开后按钮变「收起」（还能折回去）', opened.btn === '收起', opened.btn);
  await page.locator('.code-more').first().click();
  await page.waitForTimeout(250);
  const back = await page.evaluate(
    () => document.querySelector('.tool-card.is-warn pre.code.code-src').classList.contains('is-clamped'),
  );
  check('再点一次能收回折叠态', back === true, back);

  /* P2：出参那个报错块要能整段复制走（提工单直接贴） */
  await page.evaluate(() => {
    const card = document.querySelector('.tool-card.is-warn');
    card.querySelector('.grid-2 .field:nth-child(2) .field-head .copy-btn').click();
  });
  await page.waitForTimeout(300);
  const clip = await page
    .evaluate(() => navigator.clipboard.readText())
    .catch((e) => ({ err: String(e).slice(0, 60) }));
  /* Windows 剪贴板把 \n 归一成 \r\n，比对侧归一 —— 复制到的内容本身一个字不改 */
  const norm = typeof clip === 'string' ? clip.replace(/\r\n/g, '\n') : clip;
  check('P2 点出参复制按钮 → 剪贴板里是完整报错文本', norm === obs, typeof norm === 'string' ? norm : clip);

  /* 其余卡片不受影响：calculator 仍是左右分栏 + JSON 树 */
  const split = await page.evaluate(() => {
    const card = Array.from(document.querySelectorAll('.tool-card')).find((c) => {
      const n = c.querySelector('.tool-name');
      return n && n.innerText.trim() === 'calculator';
    });
    const [a, b] = Array.from(card.querySelectorAll('.grid-2 .field')).map((f) => f.getBoundingClientRect());
    return { sideBySide: Math.abs(a.top - b.top) < 2 && b.left > a.right - 2, jv: !!card.querySelector('.jv') };
  });
  check('非代码工具没有被顺手改掉：calculator 仍分栏 + JSON 树', split.sideBySide && split.jv, split);
  return box;
}

/** 轨迹回放页用的是第二个渲染点（StepTimeline），同一个 bug 在那里长一样 —— 一起验。 */
async function tracePass(page, want) {
  await page.goto(`${BASE}/trace`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: /全部展开/ }).click().catch(() => {});
  await page.waitForTimeout(400);
  const got = await page.evaluate((src) => {
    const pres = Array.from(document.querySelectorAll('pre.code.code-src'));
    const hit = pres.find((p) => p.textContent === src);
    return {
      found: !!hit,
      lines: hit ? hit.getAttribute('data-lines') : null,
      total: pres.length,
      /* 时间轴里还有非源码工具的入参，那些必须仍是 JSON 树 */
      jvLeft: document.querySelectorAll('.tl-body .jv, .field .jv').length,
      sample: pres.map((p) => (p.textContent || '').slice(0, 18)),
    };
  }, want);
  console.log(JSON.stringify(got));
  check('轨迹回放页的 code_exec 入参同样按代码渲染（逐字相等）', got.found === true, got.sample);
  check('轨迹回放页也拿到了 15 行（两个渲染点口径一致）', got.lines === '15', got.lines);
  check('非源码入参在时间轴里仍走 JSON 树', got.jvLeft > 0, got.jvLeft);
}

async function pass1(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  /* 剪贴板读要授权，否则 P2 那条只能断言按钮存在，测不到「复制到了什么」 */
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const page = await ctx.newPage();
  const errors = [];
  const hits = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('request', (r) => {
    if (/\/api\/tools/.test(r.url())) hits.push(r.method());
  });
  await installMocks(page);
  await openTools(page);

  console.log(`\n== ${label} ==`);
  const cards = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.tool-card')).map((c) => {
      const badge = Array.from(c.querySelectorAll('.status-badge')).pop();
      /* 出参块 = grid-2 里第二个 .field。JsonView 解析得出来是 .jv，
         解析不出来回落 pre.code —— 两个都要认，否则异常样式挂在哪个上都说不清。 */
      const out = c.querySelectorAll('.grid-2 .field')[1]?.querySelector('.jv, pre.code');
      const inp = c.querySelectorAll('.grid-2 .field')[0]?.querySelector('.jv, pre.code');
      return {
        name: c.querySelector('.tool-name')?.innerText.trim(),
        intent: c.querySelector('.tool-intent')?.innerText.trim(),
        why: c.querySelector('.tool-why')?.innerText.trim() ?? null,
        failed: c.classList.contains('is-failed'),
        warn: c.classList.contains('is-warn'),
        hasArgs: !!c.querySelector('.jv-root, .jv'),
        badge: badge ? badge.innerText.trim() : null,
        /* 判「是不是绿色成功」要看实测色，不能只看文案 —— 文案对但配色错同样是 bug。 */
        badgeColor: badge ? getComputedStyle(badge).color : null,
        outCls: out ? out.className : null,
        outBg: out ? getComputedStyle(out).backgroundColor : null,
        /* 入参块全文（截一段）：标题不摆代码之后，代码必须仍在这里看得见 */
        inText: inp ? inp.textContent.slice(0, 60) : null,
      };
    }),
  );
  console.log(JSON.stringify(cards, null, 1));

  check('六张卡（失败 / 超时 / 非零退出 / 字典外工具都各一张）', cards.length === 6, cards.length);
  check(
    '标题用执行器自己写的 thought，句末句号收掉',
    cards[0].intent === '先查知识库里 PoE 供电标准的原文段落',
    cards[0].intent,
  );
  check('副行补「动词：关键入参」', cards[0].why === '正在翻知识库：POE 单端口最大输出功率 标准', cards[0].why);
  check('calculator 的副行是表达式而不是 JSON 壳', /正在算这笔数：1024 \* 0\.85 \* 17\.5/.test(cards[1].why || ''), cards[1].why);
  check(
    '字典外工具不瞎编：标题退回「正在调用 <name>」',
    cards[3].name === 'ocr_table' && cards[3].intent === '正在调用 ocr_table' && cards[3].why === null,
    cards[3],
  );
  check('失败那条走 is-failed 左边框', cards[2].failed === true, cards[2]);

  /* ---- 第 2 步：code_exec 的意图标题不再摆代码 ---- */
  const timeout = cards[4];
  const exitCode = cards[5];
  check('超时那张卡的入参是一整段源码', timeout.name === 'code_exec', timeout.name);
  check(
    '无 thought 时标题走提炼，不是代码截断',
    timeout.intent === '正在扫描系统文件' && !/import|os\.walk|roots/.test(timeout.intent),
    timeout.intent,
  );
  check(
    '代码原文仍在入参块里（标题不摆代码，但信息不能藏）',
    /import os, re, time/.test(timeout.inText || ''),
    timeout.inText,
  );
  /* 没有 thought 时副行本来就不出现（intentSub 只在 thought 存在时补「动词：关键入参」），
     这时代码只在入参块里 —— 这条钉住「副行不是代码的第二个落点」。 */
  check('无 thought 的卡没有副行', timeout.why === null, timeout.why);

  /* ---- 第 5 步（本轮 P0/P1/P2）：源码入参按代码渲染、上下堆叠、报错可复制 ---- */
  await codePass(page, WANT_CODE, WANT_OUT);

  /* ---- 第 3 步：徽章语义。绿色与否看实测色，不看文案（配色错而文案对同样是 bug） ---- */
  const green = cards[1].badgeColor; // calculator 必须是绿档，同时当参照色
  check('calculator 仍是绿色「成功」（不受降级影响）', cards[1].badge === '成功' && cards[1].outCls.includes('jv'), [cards[1].badge, cards[1].outCls]);
  check('降级档文案含「异常」', /异常/.test(timeout.badge || ''), timeout.badge);
  check('降级档不是绿色成功', timeout.badgeColor !== green, [timeout.badgeColor, green]);
  check('超时走 is-warn 左边框，不是 is-failed', timeout.warn === true && timeout.failed === false, [timeout.warn, timeout.failed]);
  /* 非零退出：后端如实记 failed（core/tools/builtin/code_exec.py 的 SandboxFailed），
     前端那层「嗅出参 exit_code 文本」的降级判定已随之删除 —— 所以这里要看到的是
     红色「失败」而不是琥珀「异常退出」。这条断言就是那次删除的落点。 */
  check('非零退出由后端 status 记 failed，前端不再嗅文本', exitCode.failed === true && exitCode.badge === '失败', [exitCode.failed, exitCode.badge]);
  check('非零退出不是绿色成功', exitCode.badgeColor !== green, [exitCode.badgeColor, green]);
  check('红色失败档文案不变', cards[2].badge === '失败', cards[2].badge);

  /* ---- 第 4 步：异常出参的底色确实换了 ---- */
  check('异常出参块挂上 is-error', timeout.outCls.includes('is-error') && exitCode.outCls.includes('is-error'), [timeout.outCls, exitCode.outCls]);
  check(
    '异常出参底色 ≠ 正常出参底色（浅红底真的渲染出来了）',
    timeout.outBg !== cards[1].outBg && exitCode.outBg !== cards[1].outBg,
    [cards[1].outBg, timeout.outBg],
  );
  check('正常出参没有被连坐', !cards[1].outCls.includes('is-error') && !cards[0].outCls.includes('is-error'), [cards[0].outCls, cards[1].outCls]);
  check('/api/tools 被拉了一次', hits.length === 1, hits);

  const tip0 = await tipOf(page, 0);
  check(
    'Tooltip 三行齐：大白话 / 计费口径 / 注册表参数',
    tip0.includes('检索本地知识库') &&
      tip0.includes('本地执行 · 不产生 API 费用') &&
      tip0.includes('注册表 · 超时 10s · 失败重试 1 次 · 常规权限'),
    tip0,
  );
  const tip2 = await tipOf(page, 2);
  check(
    'code_exec 标出高危与「超时交给工具自己管」',
    tip2.includes('沙箱里跑一段 Python') && tip2.includes('高危：需显式放行') && tip2.includes('交给工具自己管'),
    tip2,
  );
  const tip3 = await tipOf(page, 3);
  check('字典外工具的 Tooltip 如实说没收录', tip3.includes('未在字典里收录的工具：ocr_table'), tip3);

  // Tooltip 第三行的可读性实测（两个主题都得过 AA）
  await page.locator('.tool-name').nth(2).hover();
  await page.waitForTimeout(450);
  const tone = await tipTone(page);
  check('Tooltip 第三行 ≥4.5:1', tone && tone.ratio >= 4.5, tone);

  // 键盘可达：rc-tooltip 默认只挂 hover，键盘用户永远读不到解释 ——
  // 组件上必须显式 trigger={['hover','focus']}，这条断言就是钉住那个属性。
  await page.locator('.tool-name').first().evaluate((el) => el.focus());
  await page.waitForTimeout(400);
  const byKb = await page
    .locator('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner')
    .first()
    .innerText()
    .catch(() => '');
  check('键盘聚焦也能打开工具解释', byKb.includes('检索本地知识库'), byKb.replace(/\s+/g, ' ').slice(0, 40));

  check('无 pageerror', errors.length === 0, errors.slice(0, 3));

  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.pane').screenshot({ path: path.join(OUT, `${label}-tools.png`) });
  /* 验收要的那张：单张 code_exec 卡片，展开态，看得清缩进与上色 */
  await page.evaluate(() => {
    const card = Array.from(document.querySelectorAll('.tool-card')).find((c) =>
      c.classList.contains('is-warn'),
    );
    card.scrollIntoView({ block: 'start' });
  });
  await page.locator('.code-more').first().click();
  await page.waitForTimeout(300);
  await page
    .locator('.tool-card.is-warn')
    .first()
    .screenshot({ path: path.join(OUT, `${label}-codeexec.png`) });
  await page.locator('.code-more').first().click();
  // 这张要拍到 Tooltip 本身：hover 后直接截，别走 tipOf()（它读完就把鼠标移开）
  await page.locator('.tool-name').nth(2).hover();
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(OUT, `${label}-tooltip.png`) });
  console.log(`  ✓ 截图 → ${label}-tools / ${label}-codeexec / ${label}-tooltip`);
  await tracePass(page, WANT_CODE);
  check('轨迹回放页跑完仍无 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

/** 注册表拉不到（后端没起 / 未鉴权）时，卡片必须照样能读。 */
async function degraded(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await page.route('**/api/tools', (r) => r.fulfill({ status: 401, contentType: 'application/json', body: '{}' }));
  await openTools(page);

  console.log('\n== 注册表 401 ==');
  const cards = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.tool-card')).map((c) => ({
      name: c.querySelector('.tool-name')?.innerText.trim(),
      intent: c.querySelector('.tool-intent')?.innerText.trim(),
    })),
  );
  check('拉不到注册表：六张卡仍有意图标题', cards.length === 6 && cards.every((c) => !!c.intent), cards);
  const tip = await tipOf(page, 0);
  check('拉不到注册表：Tooltip 仍给得出大白话', tip.includes('检索本地知识库'), tip);
  check('无 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

async function run() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  await pass1(browser, 'light', 'light');
  await pass1(browser, 'dark', 'dark');
  await degraded(browser);
  await browser.close();

  console.log(`\ntoolcard probe: ${pass} 通过 / ${pass + fails.length} 断言`);
  if (fails.length) {
    console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
    process.exit(1);
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
