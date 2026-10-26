/* B-4 验收：知识库页的「试检索」必须走 POST /knowledge/search，
 * 并把 BM25 / 向量 / 综合分三列摆出来。空库与 409 指纹不一致也要有正确文案。
 *
 * 前置：后端 8001、前端 5173 已起；NODE_PATH 指向 playwright-core；
 *       CHROME 指向本机 Chrome。
 */
const assert = require('assert/strict');
const { chromium } = require('playwright-core');

const CHROME =
  process.env.CHROME || 'C:/Users/15539/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const QUERY = process.env.SEARCH_QUERY || '六类线施工弯曲半径要求';

async function fillAndSearch(page) {
  const input = page.getByPlaceholder('输入一个问题，例如：六类线施工弯曲半径要求');
  await input.fill(QUERY);
  // AntD Input.Search 的 enterButton 在部分版本里不可作 role=button 命中；
  // 回车与点按钮走同一个 onSearch，功能验收不看点击路径。
  await input.press('Enter');
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });

  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const requests = [];
    page.on('request', (request) => {
      if (request.url().includes('/knowledge/search')) {
        requests.push({ method: request.method(), url: request.url() });
      }
    });

    await page.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' });
    await page.getByText('试检索', { exact: true }).waitFor({ timeout: 30_000 });
    await fillAndSearch(page);
    await page.locator('.kb-hit').first().waitFor({ timeout: 30_000 });

    const hits = await page.locator('.kb-hit').count();
    const first = (await page.locator('.kb-hit').first().innerText()).replace(/\s+/g, ' ');
    assert.ok(hits >= 1, `检索没有返回 hit：${first}`);
    assert.match(first, /BM25\s+[\d.]+/, '命中缺少 BM25 分数');
    assert.match(first, /向量\s+[\d.]+/, '命中缺少向量分数');
    assert.match(first, /综合\s+[\d.]+/, '命中缺少综合分');
    assert.ok(
      requests.some((req) => req.method === 'POST'),
      `检索没有走 POST：${JSON.stringify(requests)}`,
    );
    assert.ok(
      !requests.some((req) => req.method === 'GET'),
      `检索不应再走 GET：${JSON.stringify(requests)}`,
    );
    console.log(
      JSON.stringify({
        real_search: { hits, first_hit: first.slice(0, 240), requests },
      }),
    );
    await context.close();

    /* 空库：后端 200 + hits: []，页面应显示“库为空”，不是报错。 */
    const emptyContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const emptyPage = await emptyContext.newPage();
    await emptyPage.route('**/api/knowledge/overview', async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.chunk_count = 0;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });
    await emptyPage.route('**/api/knowledge/search', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ query: QUERY, top_k: 5, took_ms: 1, hits: [] }),
      }),
    );
    await emptyPage.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' });
    await emptyPage.getByText('试检索', { exact: true }).waitFor({ timeout: 30_000 });
    await fillAndSearch(emptyPage);
    await emptyPage.getByText('库为空', { exact: true }).waitFor({ timeout: 30_000 });
    console.log(JSON.stringify({ empty_library: '库为空' }));
    await emptyContext.close();

    /* 409：复用现有 ApiFetchError 文案，并明确提示需要全量重索引。 */
    const conflictContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const conflictPage = await conflictContext.newPage();
    await conflictPage.route('**/api/knowledge/search', (route) =>
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: { code: 'fingerprint_mismatch', message: '索引指纹不一致' },
        }),
      }),
    );
    await conflictPage.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' });
    await conflictPage.getByText('试检索', { exact: true }).waitFor({ timeout: 30_000 });
    await fillAndSearch(conflictPage);
    await conflictPage.getByText(/需要全量重索引/).waitFor({ timeout: 30_000 });
    console.log(JSON.stringify({ fingerprint_mismatch: '提示需要全量重索引' }));
    await conflictContext.close();

    console.log('PASS B-4 knowledge search');
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error('FAIL B-4 knowledge search:', error);
  process.exit(1);
});
