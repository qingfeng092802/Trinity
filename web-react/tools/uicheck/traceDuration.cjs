/* H-1 验收：真实轨迹页的「总耗时」必须等于 Σ node_end，而不是 Σ 全部事件。
 *
 * 前置：
 *   1) 后端 8001、前端 5173 已起；
 *   2) NODE_PATH 指向含 playwright-core 的 node_modules；
 *   3) CHROME 指向本机 Chrome。
 *
 * 判据：
 *   - 指标卡读数与 /tasks/{id}/trace 的 Σ node_end 相差 ≤ 1s；
 *   - 读数显著小于 Σ 全部事件（旧算法），证明确实换了口径；
 *   - 切到「仅失败」筛选后读数不变（筛选只影响计数）。
 */
const assert = require('assert/strict');
const { chromium } = require('playwright-core');

const CHROME =
  process.env.CHROME || 'C:/Users/15539/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const API = process.env.API_URL || 'http://127.0.0.1:8001';
const TASK_ID = process.env.TASK_ID || 'task-804d76037a07';

/** 与 src/utils/format.ts::fmtDuration 同口径，解析回毫秒。 */
function parseDuration(text) {
  const value = text.trim();
  let match = value.match(/^(\d+)m\s+(\d+)s$/);
  if (match) return (Number(match[1]) * 60 + Number(match[2])) * 1000;
  match = value.match(/^([\d.]+)s$/);
  if (match) return Math.round(Number(match[1]) * 1000);
  match = value.match(/^(\d+)ms$/);
  if (match) return Number(match[1]);
  throw new Error(`无法解析耗时文本：${JSON.stringify(value)}`);
}

async function readTotal(page, { allowDash = false } = {}) {
  const tile = page.locator('.metric', { hasText: '总耗时' }).first();
  await tile.waitFor({ state: 'visible', timeout: 30_000 });
  if (!allowDash) {
    await page.waitForFunction(
      () => {
        const card = [...document.querySelectorAll('.metric')].find((el) =>
          el.textContent?.includes('总耗时'),
        );
        const value = card?.querySelector('.metric-value')?.textContent?.trim();
        return !!value && value !== '—';
      },
      null,
      { timeout: 30_000 },
    );
  }
  return {
    value: (await tile.locator('.metric-value').innerText()).trim(),
    hint: (await tile.locator('.metric-hint').count())
      ? (await tile.locator('.metric-hint').innerText()).trim()
      : '',
  };
}

(async () => {
  const detail = await (await fetch(`${API}/tasks/${TASK_ID}`)).json();
  const trace = await (await fetch(`${API}/tasks/${TASK_ID}/trace?limit=500`)).json();
  const nodeEndMs = trace.items
    .filter((item) => item.event_type === 'node_end')
    .reduce((sum, item) => sum + Number(item.latency_ms ?? 0), 0);
  const allEventMs = trace.items.reduce(
    (sum, item) => sum + Number(item.latency_ms ?? 0),
    0,
  );
  assert.ok(nodeEndMs > 0, `${TASK_ID} 没有 node_end，无法验收`);
  assert.equal(detail.status, 'done', `${TASK_ID} 不是完成态`);

  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await page.goto(`${BASE}/trace?id=${encodeURIComponent(TASK_ID)}`, {
      waitUntil: 'domcontentloaded',
    });
    const before = await readTotal(page);
    const displayedMs = parseDuration(before.value);

    console.log(
      JSON.stringify({
        task_id: TASK_ID,
        displayed: before.value,
        hint: before.hint,
        displayed_ms: displayedMs,
        node_end_ms: nodeEndMs,
        all_event_ms: allEventMs,
        task_duration_ms: detail.duration_ms,
      }),
    );

    assert.ok(
      Math.abs(displayedMs - nodeEndMs) <= 1000,
      `总耗时 ${before.value}（${displayedMs}ms）与 Σ node_end ${nodeEndMs}ms 相差超过 1s`,
    );
    assert.ok(
      displayedMs < allEventMs - 1000,
      `总耗时 ${before.value} 仍接近 Σ 全部事件 ${allEventMs}ms，旧的双计口径可能没改掉`,
    );

    await page.getByRole('combobox', { name: '按状态筛选' }).click({ force: true });
    await page.getByText('仅失败', { exact: true }).click();
    const after = await readTotal(page);
    const filteredMs = parseDuration(after.value);
    assert.equal(
      filteredMs,
      displayedMs,
      `筛选后总耗时从 ${displayedMs}ms 变成 ${filteredMs}ms；总耗时不应随筛选变化`,
    );
    console.log(JSON.stringify({ filtered_displayed: after.value, filtered_ms: filteredMs }));

    const noNodePage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    try {
      await noNodePage.route('**/api/tasks/*/trace*', async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.items = (body.items || []).filter((item) => item.event_type !== 'node_end');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        });
      });
      await noNodePage.goto(`${BASE}/trace?id=${encodeURIComponent(TASK_ID)}`, {
        waitUntil: 'domcontentloaded',
      });
      await noNodePage.waitForFunction(
        () => document.body.innerText.includes('该轨迹没有 node_end'),
        null,
        { timeout: 30_000 },
      );
      const noNode = await readTotal(noNodePage, { allowDash: true });
      assert.equal(noNode.value, '—', '没有 node_end 时总耗时必须显示 —，不能回退到全事件求和');
      console.log(JSON.stringify({ no_node_end_displayed: noNode.value, hint: noNode.hint }));
    } finally {
      await noNodePage.close();
    }
    console.log('PASS H-1 trace duration');
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error('FAIL H-1 trace duration:', error);
  process.exit(1);
});
