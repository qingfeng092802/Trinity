/* record_demo.cjs —— 录一段**真实点击**的端到端演示（Playwright + 本机 Chrome）
 *
 * 与同目录其它脚本的分工：capture*.cjs / kbshot.cjs 出的是**判据用的静态像素**；
 * 这个脚本出的是"过程"——逐字打一条任务、点提交、让 SSE 日志真流起来、再从结果卡跳进
 * 轨迹回放页展开节点，全程录成 webm，之后用 ffmpeg 截两段拼成 README 首屏的 GIF。
 *
 * 为什么要在本机跑（而不是 CI）：它要三样同时在线 ——
 *   ① 后端（**起在隔离运行目录**，别把演示数据写进 data/，命令见下）
 *   ② 前端 dev server（:5173，vite 代理指到 :8001）
 *   ③ 一个真实 LLM Key —— ⚠️ 本脚本**会真实消耗 token**（一条 Agent 任务）。
 *      纯检索与评测不花钱，但这条路径会调模型，别在 CI 里跑它。
 *
 * 用法：
 *   # 终端 A：隔离的后端（临时 DB / 知识库 / 工作区 / 日志）
 *   mkdir -p "$TMP/trinity_demo/kb" "$TMP/trinity_demo/logs" "$TMP/trinity_demo/workspace"
 *   DB_URL="sqlite:///$TMP/trinity_demo/demo_tasks.db" KNOWLEDGE_DIR="$TMP/trinity_demo/kb" \
 *   WORKSPACE_DIR="$TMP/trinity_demo/workspace" LOG_DIR="$TMP/trinity_demo/logs" \
 *     python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
 *   # 终端 B：知识库播种（三篇 md/txt 进 ready；csv/html 不在白名单，见 demo_kb_seed.py 注释）
 *   python web-react/tools/uicheck/demo_kb_seed.py
 *   # 终端 C：前端 + 录制
 *   cd web-react && npm run dev
 *   NODE_PATH="<playwright-core 所在的 node_modules>" CHROME="<chrome 可执行文件>" \
 *     node tools/uicheck/record_demo.cjs
 *
 * 环境变量：
 *   CHROME / CHROME_PATH  Chrome 可执行文件（必填习惯：本机路径不该进仓库）
 *   NODE_PATH             让 require('playwright-core') 解析得到（ESM 的 import 不认 NODE_PATH，
 *                         所以这个脚本刻意是 CommonJS）
 *   DEMO_URL              默认 http://127.0.0.1:5173
 *   DEMO_BACKEND          默认 http://127.0.0.1:8001（只用后端判终态，不信界面上的字样）
 *   DEMO_OUT              默认 系统临时目录/trinity_demo_frames
 *   DEMO_PROMPT           任务文本（默认一条命中示例知识库的报销题）
 *   DEMO_MAX_WAIT_MS      等终态上限，默认 240000
 *
 * 产物（都在临时目录，不进仓库）：
 *   <DEMO_OUT>/video/*.webm     录屏
 *   <DEMO_OUT>/timeline.json    每一步的相对时刻 + 任务真实读数（GIF 文案照它写）
 *   <DEMO_OUT>/marks.log        同一份时间轴的追加日志 —— 卡住时能立刻看出卡在哪一步
 *
 * GIF 合成（⚠️ Playwright 自带的那个 ffmpeg **不够用**：它是精简版，没有 gif 编码器，
 *   也没有 setpts / concat / palettegen。本机可用的是 `pip install imageio-ffmpeg`
 *   带进来的完整二进制（找 `python -c "import imageio_ffmpeg,os;print(os.path.dirname(imageio_ffmpeg.__file__))"`
 *   目录下的 ffmpeg-win-x86_64-*.exe）。截两段拼起来：
 *   ffmpeg -y -i in.webm -filter_complex \
 *     '[0:v]trim=start=A:end=B,setpts=PTS-STARTPTS[s1];[0:v]trim=start=C:end=D,setpts=PTS-STARTPTS[s2]; \
 *      [s1][s2]concat=n=2:v=1:a=0,scale=960:-1:flags=lanczos,fps=10,split[a][b]; \
 *      [a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle' \
 *     -loop 0 out.gif
 *   （在 Windows 上把这段写成 -filter_complex_script 文件会被 CRLF 打断解析，直接内联传。）
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright-core');

const FRONTEND = process.env.DEMO_URL || 'http://127.0.0.1:5173';
const BACKEND = process.env.DEMO_BACKEND || 'http://127.0.0.1:8001';
const OUT = process.env.DEMO_OUT || path.join(os.tmpdir(), 'trinity_demo_frames');
const PROMPT =
  process.env.DEMO_PROMPT ||
  '出差打车报销需要哪些凭证？按公司制度回答，并指出依据来自哪份文件。';
const MAX_WAIT = Number(process.env.DEMO_MAX_WAIT_MS || 240_000);
const VIEWPORT = { width: 1280, height: 800 };
const MARKS_FILE = path.join(OUT, 'marks.log');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const marks = [];
const t0 = Date.now();

/** 记一步时刻：同时写 marks.log —— 上次就是靠 stdout 缓冲看不出卡在哪，挂在这里的文件不会等进程退出。 */
function mark(label, extra = {}) {
  const row = { label, t_s: Number(((Date.now() - t0) / 1000).toFixed(2)), ...extra };
  marks.push(row);
  const line = `${row.t_s}s  ${label}${Object.keys(extra).length ? ' ' + JSON.stringify(extra) : ''}\n`;
  fs.appendFileSync(MARKS_FILE, line, 'utf8');
  process.stdout.write(line);
}

async function getJson(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return res.json();
}

// Chrome 路径解析：统一由 ./_chrome.cjs 提供（环境变量 -> 各平台常见安装位置）
const { resolveChrome } = require('./_chrome.cjs');

/** 侧栏是**图标按钮**（里面没有文字，label 在 aria-label 上），所以只能按 aria-label 点。 */
async function navTo(page, ariaLabel) {
  const btn = page.locator(`button.rail-btn[aria-label="${ariaLabel}"]`).first();
  await btn.waitFor({ state: 'visible', timeout: 8_000 });
  await btn.click();
  await sleep(1_000);
}

async function main() {
  fs.mkdirSync(path.join(OUT, 'video'), { recursive: true });
  fs.writeFileSync(MARKS_FILE, '', 'utf8');

  const health = await getJson(`${BACKEND}/health`);
  mark('preflight', { backend: health.status, version: health.version });
  const kb = await getJson(`${BACKEND}/knowledge/documents`);
  const ready = (kb.items || []).filter((i) => i.status === 'ready');
  if (ready.length === 0) throw new Error('知识库是空的：先跑 demo_kb_seed.py，否则检索那一屏没有出处可指');

  const browser = await chromium.launch({
    headless: true,
    executablePath: resolveChrome(),
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: path.join(OUT, 'video'), size: VIEWPORT },
    locale: 'zh-CN',
    colorScheme: 'light',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);

  let terminalStatus = null;
  let taskId = null;
  let detail = null;
  let cost = null;

  try {
    // 用 domcontentloaded 而不是 networkidle：界面每 30 s 轮询一次 /health，
    // networkidle 这种"等网络安静"的判据在这里只会白等。
    await page.goto(`${FRONTEND}/tasks`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('button.cp-submit').first().waitFor({ state: 'visible', timeout: 20_000 });
    mark('tasks-page');

    await navTo(page, '知识库');
    await page.waitForTimeout(2_000); // 让这一屏在动画里停留够读
    mark('knowledge-page', { docs: ready.length });

    await navTo(page, '任务与日志');
    const box = page.locator('textarea').first();
    await box.click();
    await box.fill('');
    await box.pressSequentially(PROMPT, { delay: 55 });
    mark('typed', { chars: PROMPT.length });

    // 工具与知识库检索两个开关：只在"关"的时候点，别把开着的东西关掉。
    for (const label of ['启用工具', '启用知识库检索']) {
      const sw = page.locator(`[aria-label="${label}"]`).first();
      if ((await sw.count()) === 0) {
        mark(`switch-absent:${label}`);
        continue;
      }
      const state = await sw.evaluate((node) => ({
        checked:
          node.getAttribute('aria-checked') === 'true' ||
          node.className.includes('ant-switch-checked'),
      }));
      if (!state.checked) {
        await sw.click({ force: true });
        await sleep(400);
      }
      mark(`switch:${label}`, { was_on: state.checked });
    }

    const listBefore = await getJson(`${BACKEND}/tasks?limit=1`);
    const idsBefore = new Set((listBefore.items || []).map((i) => i.task_id));

    await page.locator('button.cp-submit').first().click();
    mark('submitted');

    // 终态问后端，不问界面：界面上"耗时/tokens"这些字样在空态提示里也有，拿它判终态会把还在跑的任务判完。
    const deadline = Date.now() + MAX_WAIT;
    while (Date.now() < deadline) {
      await sleep(1_000);
      const list = await getJson(`${BACKEND}/tasks?limit=5`);
      const fresh = (list.items || []).find((i) => !idsBefore.has(i.task_id));
      if (!fresh) continue;
      taskId = fresh.task_id;
      detail = await getJson(`${BACKEND}/tasks/${taskId}`);
      if (['done', 'failed', 'canceled'].includes(detail.status)) {
        terminalStatus = detail.status;
        break;
      }
      mark('polling', { status: detail.status });
    }
    mark(terminalStatus ? `terminal:${terminalStatus}` : 'terminal:TIMEOUT', { task_id: taskId });
    await sleep(4_200); // 结果卡渲染与数字落定，也给答案在画面里留够读的时间

    // 从结果卡进轨迹回放 —— 这是真实用户路径，且会把这条任务带过去（省掉驱动 AntD Select）
    const link = page.getByText('在轨迹回放中打开', { exact: false }).first();
    if ((await link.count()) > 0) {
      await link.click();
      await sleep(1_800);
      mark('trace-via-result-link');
    } else {
      await navTo(page, '轨迹回放');
      mark('trace-via-nav');
    }
    // 铺开步骤详情：点工具栏上的「全部展开」。
    // 上一版在这里按 planner / executor / reviewer 三个词去找行并点击，命中的其实是
    // 筛选区的那三个 chip（Segmented 的 label），于是录出来是"已筛选 7 / 15 条"，
    // 节点分布反而变成 0/7/0 —— 要展示的恰恰是被筛掉的那两类。
    // 定位器为什么用 hasText 而不是 getByRole：AntD 的 Button 里那个图标是
    // `<span role="img" aria-label="down">`，可访问名变成了"down 全部展开"，
    // `getByRole({ name: '全部展开', exact: true })` 实测命中 0 个（上一版就是这么录成
    // 没展开的）；`locator('button', { hasText })` 命中 1 个。这里只用后者。
    const expandAllBtn = page.locator('button', { hasText: '全部展开' }).first();
    await expandAllBtn
      .waitFor({ state: 'visible', timeout: 10_000 })
      .catch(() => mark('trace:expand-all-not-found'));
    if (await expandAllBtn.isVisible().catch(() => false)) {
      await expandAllBtn.click();
      await sleep(1_800);
      const opened = await page.locator('[aria-label="收起详情"]').count();
      mark('trace:expand-all', { opened_rows: opened });
    } else {
      mark('trace:expand-all-absent');
    }

    // 滚进带工具入参/出参的那几行，让正文真的进画面（页面本身不自动滚）。
    for (let i = 0; i < 4; i += 1) {
      await page.mouse.wheel(0, 380);
      await sleep(650);
    }
    mark('trace:scrolled-into-details');
    await sleep(2_200);

    if (taskId) cost = await getJson(`${BACKEND}/tasks/${taskId}/cost-breakdown`).catch(() => null);
  } finally {
    // 上一次失败时 browser 没关，node 进程挂着录了 12 分钟视频不退出 —— 这里无论如何都要收干净。
    const video = page.video();
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    const videoPath = video ? await video.path().catch(() => null) : null;
    await browser.close().catch(() => {});

    const payload = {
      video: videoPath,
      prompt: PROMPT,
      marks,
      task: taskId
        ? {
            task_id: taskId,
            status: terminalStatus,
            detail_keys: detail ? Object.keys(detail) : [],
            duration_ms: detail?.duration_ms ?? null,
            iterations: detail?.iterations ?? detail?.review_rounds ?? null,
            usage: detail?.usage ?? detail?.total_tokens ?? null,
            cost,
          }
        : null,
      kb: { ready: ready.length, chunks: ready.reduce((a, i) => a + (i.chunk_count || 0), 0) },
    };
    fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify(payload, null, 2), 'utf8');
    mark('written', { video: videoPath ? path.basename(videoPath) : null });
    console.log(JSON.stringify(payload.task, null, 2));
  }
}

main().catch((err) => {
  mark('fatal', { message: String(err && err.message ? err.message : err) });
  process.exitCode = 1;
});
