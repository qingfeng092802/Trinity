/* 真实流式「运行中」态抓取 + UI 异常检测。
 *
 * 与之前所有截图脚本的区别：以前截的都是**历史任务（终态）**，
 * 这次真的提交一个任务，在 SSE 推送过程中连续采样。
 *
 * 用法：node tools/uicheck/stream.cjs
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5199';
const OUT = path.resolve(__dirname, 'shots');
const TASK = process.env.TASK || '门禁开门延时默认几秒？用计算器算 12+30';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROME });
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  // 采样一次「运行中」相关的 UI 状态
  const sample = () =>
    page.evaluate(() => {
      const txt = (sel) => document.querySelector(sel)?.innerText?.trim() ?? null;
      const logBody = document.querySelector('.log-body');
      const rows = [...document.querySelectorAll('.log-row')];
      const activeItem = document.querySelector('.tsk-item.is-active');
      return {
        statusbar: txt('.statusbar'),
        logRows: rows.length,
        lastLog: rows.length ? rows[rows.length - 1].innerText.replace(/\n/g, ' ').slice(0, 90) : null,
        // 自动滚动是否真的贴底：这是「日志不滚动」类 bug 的直接判据
        scrollPinned: logBody
          ? Math.abs(logBody.scrollHeight - logBody.clientHeight - logBody.scrollTop) < 4
          : null,
        logScrollable: logBody ? logBody.scrollHeight > logBody.clientHeight : null,
        activeTaskStatus: activeItem
          ? activeItem.querySelector('.tsk-status')?.textContent
          : null,
        // 列表里是否存在「运行中」态的项（验证运行状态样式）
        runningInList: [...document.querySelectorAll('.tsk-status')].filter((e) =>
          /运行中|排队|执行/.test(e.textContent),
        ).length,
        submitDisabled: (() => {
          const b = [...document.querySelectorAll('button')].find((e) =>
            /提交/.test(e.textContent),
          );
          return b ? b.disabled || b.classList.contains('ant-btn-loading') : null;
        })(),
        cancelVisible: (() => {
          const b = [...document.querySelectorAll('.statusbar button')].find((e) =>
            /取消/.test(e.textContent.replace(/\s/g, '')),
          );
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return { w: Math.round(r.width), h: Math.round(r.height), text: b.innerText };
        })(),
      };
    });

  console.log('提交任务:', TASK);
  await page.fill('.composer-input', TASK);
  await page.waitForTimeout(200);
  await page.click('.composer-row button[type="submit"]');

  const timeline = [];
  const shots = [];

  // 真实任务实测 25s 左右完成，采样窗口必须比它长，否则只能抓到「运行中」半程
  for (let i = 0; i < 48; i += 1) {
    await sleep(900);
    const s = await sample();
    const t = (i + 1) * 0.9;
    timeline.push({ t: t.toFixed(1), ...s });

    // 关键帧留档：首帧、每 3 帧、终态
    const name = `rt-${String(i).padStart(2, '0')}-t${t.toFixed(1)}s.png`;
    await page.screenshot({ path: path.join(OUT, name) });
    shots.push(name);

    const done = s.statusbar && /成功|失败|已取消|中止/.test(s.statusbar);
    if (done && i > 0) {
      console.log(`任务在 t≈${t.toFixed(1)}s 进入终态`);
      break;
    }
  }

  // 终态再等一下，确保详情补拉完成
  await sleep(2500);
  const final = await sample();
  await page.screenshot({ path: path.join(OUT, 'rt-final-done.png') });
  shots.push('rt-final-done.png');

  console.log('\n=== 时间线 ===');
  for (const r of timeline) {
    console.log(
      `t=${String(r.t).padStart(4)}s  log=${String(r.logRows).padStart(3)}  ` +
        `pinned=${String(r.scrollPinned).padEnd(5)}  scrollable=${String(r.logScrollable).padEnd(5)}  ` +
        `run=${r.runningInList}  submitBusy=${r.submitDisabled}  cancel=${JSON.stringify(r.cancelVisible)}`,
    );
    if (r.statusbar) console.log(`        状态条: ${r.statusbar.replace(/\n/g, ' ').slice(0, 110)}`);
  }
  console.log('\n=== 终态 ===');
  console.log(JSON.stringify(final, null, 2));
  console.log('\n截图:', shots.length, '张');
  console.log('console errors:', errors.length, errors.slice(0, 5));

  await browser.close();
})().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
