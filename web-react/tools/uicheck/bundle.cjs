#!/usr/bin/env node
/* 路由级拆包的产物门槛（P1-02 / B4）。跑在 `npm run build` 之后，读 dist 产物，不读源码 ——
 * 源码里写成 lazy 但产物没拆出来，才是用户实际付出的代价。
 *
 * 买到的东西只有一件：echarts（只有 /eval 用的那张图）不许进首屏。
 * 原来它经静态 import 链进入口图，落在 index.html 的 modulepreload 里，三页一起买单。
 *
 * 门槛形状：一条**存在性**判据（echarts 不在入口闭包里）+ 一条**与总量解耦的比例**判据
 * （入口占全站 JS 的比例）。后者不许换成"首屏 ≤ 430 KB"那种绝对值 —— 依赖只会变多，
 * 绝对值要么天天漂、要么逼人把别的东西塞回首屏去凑数。
 *
 * 用法：
 *   npm run build && node tools/uicheck/bundle.cjs
 *   DIST=dist node tools/uicheck/bundle.cjs
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.resolve(__dirname, '..', '..');
const DIST = path.resolve(ROOT, process.env.DIST || 'dist');
const ASSETS = path.join(DIST, 'assets');

/* echarts 的识别签名：它自带 zrender，全仓库只有 echarts 那份 chunk 里有这个串
 * （实测 6 份 JS 里 1 份命中、出现 3 次；许可头 "Apache ECharts" 已被压缩器剥掉，不能用）。
 * 认不出就**报错退出**，不许默认通过 —— 签名漂了而门槛闷声变绿，比没有门槛更糟。 */
const ECHARTS_SIG = 'zrender';

/* 静态 import：`import{a}from"./x.js"` / `import"./x.js"`；动态：`import("./x.js")`。
 * 两条正则分开，因为动态那一条正是"不占首屏"的证据。 */
const STATIC_RE = /(?:from\s*|import\s*)"\.\/([\w.-]+\.js)"/g;
const DYNAMIC_RE = /import\s*\(\s*"\.\/([\w.-]+\.js)"\s*\)/g;

let pass = 0;
const failed = [];
function check(name, cond, got) {
  if (cond) {
    pass += 1;
    console.log(`  ok   ${name}`);
  } else {
    failed.push(name);
    console.log(`  FAIL ${name}${got === undefined ? '' : `  读数=${JSON.stringify(got)}`}`);
  }
}
function die(msg) {
  console.error(`\nbundle probe: 判不了 —— ${msg}`);
  process.exit(2);
}

if (!fs.existsSync(path.join(DIST, 'index.html'))) {
  die(`${path.join(DIST, 'index.html')} 不存在 —— 先 npm run build`);
}
const html = fs.readFileSync(path.join(DIST, 'index.html'), 'utf8');
const files = fs.readdirSync(ASSETS).filter((f) => f.endsWith('.js'));

const gz = new Map();
const raw = new Map();
const text = new Map();
for (const f of files) {
  const buf = fs.readFileSync(path.join(ASSETS, f));
  raw.set(f, buf.length);
  gz.set(f, zlib.gzipSync(buf, { level: 9 }).length);
  text.set(f, buf.toString('utf8'));
}

const refs = (re) => {
  const out = new Set();
  let m;
  while ((m = re.exec(html))) out.add(path.basename(m[1]));
  return out;
};
/* index.html 里 <script type=module> 与 <link rel=modulepreload> 引用的那些 = 首屏必拉 */
const declared = refs(/(?:src|href)="\/assets\/([\w.-]+\.js)"/g);
if (!declared.size) die('index.html 里没解析到任何 /assets/*.js 引用 —— 判据的输入就没了');

function closure(seeds, { includeDynamic }) {
  const seen = new Set();
  const queue = [...seeds];
  while (queue.length) {
    const f = queue.pop();
    if (!text.has(f) || seen.has(f)) continue;
    seen.add(f);
    const t = text.get(f);
    for (const re of includeDynamic ? [STATIC_RE, DYNAMIC_RE] : [STATIC_RE]) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(t))) queue.push(m[1]);
    }
  }
  return seen;
}
/* 浏览器实际拉多少：静态闭包。modulepreload 只是提前，漏了也照样要拉。 */
const entry = closure(declared, { includeDynamic: false });
const sum = (set, table) => [...set].reduce((n, f) => n + (table.get(f) || 0), 0);

const echartsChunks = files.filter((f) => text.get(f).includes(ECHARTS_SIG));
if (!echartsChunks.length) die(`没有一份 chunk 含签名 "${ECHARTS_SIG}" —— 签名漂了，门槛需要重新核`);
if (echartsChunks.length > 1) die(`含签名的 chunk 有 ${echartsChunks.length} 份，不止一份 —— 判据得改写`);
const ECHARTS = echartsChunks[0];

const entryIn = [...entry].filter((f) => text.get(f).includes(ECHARTS_SIG));
const totalGz = sum(new Set(files), gz);
const entryGz = sum(entry, gz);
const ratio = entryGz / totalGz;

/* 每页真正要拉的量：入口静态闭包 ∪ 该页 chunk 的静态闭包。
 * "首屏"有两种读法 —— 「index.html 预取的那批」和「这一页渲染出来要多少 JS」——
 * 差着一整个 TaskLogPage（72 KB gzip）。两种都印出来，别拿其中一个冒充另一个。 */
const ROUTES = [
  ['/tasks', 'TaskLogPage'],
  ['/trace', 'TraceReplayPage'],
  ['/eval', 'EvalAblationPage'],
  /* /knowledge 是第四个入口（知识库上传页）。加进来不是为了报它的体积，而是为了让
     最后那条 `payers === ["/eval"]` 变成**四页**的判据：新页一旦静态 import 了 echarts，
     这笔钱就会悄悄进首屏，而三页时代的表根本不会看它。 */
  ['/knowledge', 'KnowledgePage'],
];
const routeChunks = ROUTES.map(([route, name]) => {
  const hits = files.filter((f) => f.startsWith(`${name}-`));
  if (hits.length !== 1) die(`${route} 的 chunk 认不出来（按名前缀 "${name}-" 命中 ${hits.length} 份）`);
  const set = closure(new Set([...declared, ...entry, hits[0]]), { includeDynamic: false });
  return { route, file: hits[0], set, gz: sum(set, gz), hasEcharts: set.has(ECHARTS) };
});

console.log(`\nchunk                        raw B     gzip B   首屏`);
for (const f of [...files].sort((a, b) => gz.get(b) - gz.get(a))) {
  console.log(
    `${f.padEnd(28)} ${String(raw.get(f)).padStart(9)} ${String(gz.get(f)).padStart(9)}   ${entry.has(f) ? '是' : '—'}`,
  );
}
console.log(`\n每页实际要拉的 JS（入口静态闭包 ∪ 本页 chunk）`);
for (const r of routeChunks) {
  console.log(
    `  ${r.route.padEnd(8)} ${String(r.gz).padStart(9)} B gzip  echarts=${r.hasEcharts ? '付' : '不付'}` +
      ` · ${[...r.set].filter((f) => !entry.has(f)).sort().join(' + ') || '（只有入口）'}`,
  );
}

console.log('\n判据：');
check(`首屏集合里不含 echarts（chunk=${ECHARTS}）`, entryIn.length === 0, entryIn);
check(
  'echarts 仍单独成 chunk、且被入口闭包外的某份 chunk 拉走（= /eval 才付这笔）',
  files.includes(ECHARTS) && !entry.has(ECHARTS),
  { entrySize: entry.size },
);
check(
  'index.html 的声明式预取里没有 echarts（modulepreload 那一层）',
  ![...declared].some((f) => text.get(f) && text.get(f).includes(ECHARTS_SIG)),
  [...declared],
);
/* 与总量解耦：echarts 一旦回到入口闭包，这个比例立刻跳回 ~1.0；平时依赖变多也只是慢慢降。 */
check(`入口占全站 JS 的 gzip 比例 ≤ 0.70（实测 ${ratio.toFixed(3)}）`, ratio <= 0.7, {
  entryGz,
  totalGz,
  ratio: Number(ratio.toFixed(4)),
});
check('四页各自成 chunk、都在入口闭包之外（少一页就是有人把它并回入口）',
  files.filter((f) => !entry.has(f)).length >= 4, {
    outside: files.filter((f) => !entry.has(f)),
  });
/* 正面判据：echarts 只挂在 /eval 那一页上。这才是"摘掉"的确证 ——
 * 前四条只证明它不在 index.html，那可能意味着它被塞进了某个别的 chunk 一起进首屏。 */
const payers = routeChunks.filter((r) => r.hasEcharts).map((r) => r.route);
check(`/tasks、/trace、/knowledge 三页的路由闭包都不付 echarts，只有 /eval 付`,
  JSON.stringify(payers) === '["/eval"]', payers);

const kb = (n) => `${(n / 1024).toFixed(1)} KiB`;
/* 这行只报数，不下结论 —— 上面五条判据绿不绿才是结论，让摘要重复一遍只会说谎
 * （拆包前跑它，"已从首屏摘掉"恰恰是反的）。 */
console.log(
  `\n首屏 JS：${entryGz} B gzip（${kb(entryGz)}）／全站 ${totalGz} B gzip（${kb(totalGz)}）` +
    ` · echarts 那份 ${gz.get(ECHARTS)} B，当前${entry.has(ECHARTS) ? '在' : '不在'}首屏`,
);
console.log(`\nbundle probe: ${pass} 通过 / ${pass + failed.length} 断言`);
if (failed.length) {
  console.log(`失败 ${failed.length} 条：`);
  failed.forEach((f) => console.log(`  · ${f}`));
  process.exit(1);
}
