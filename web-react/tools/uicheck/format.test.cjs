/* fmtDuration / fmtCost / fmtPct / downloadCsv 的断言集：npx esbuild 转成 cjs 后直接在 node 跑。
   用法：npx esbuild src/utils/format.ts --bundle --format=cjs --outfile=tools/uicheck/format.cjs
        node tools/uicheck/format.test.cjs
   ⚠️ 改了 src/utils/format.ts 必须重跑上面那条 esbuild —— 测试读的是 tools/uicheck/format.cjs
   那份**产物**，不重生成就是拿旧实现跑新断言（看着全绿，其实测的是上一个版本）。

   fmtDuration 的边界用例来自 2026-09-24 录屏实测报告 UI-1：任务列表出现过 `1m 60s`。
   根因是分、秒各自取整 —— 秒位 59.6 被 round 抬成 60，而分位已经 floor 定死了。
   downloadCsv 那几条来自报告 B9：纯 node 里没有 DOM，所以造了一份最小替身，
   只记两件事 —— "点击那一刻 anchor 在不在 document 里" 与 "revoke 排在同步还是宏任务"。 */
const { downloadCsv, fmtCost, fmtDuration, fmtInt, fmtPct, relativeFromDelta, relativeTime } =
  require('./format.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

/* ---- 缺值：未知比 0 诚实 ---- */
eq('null → —', fmtDuration(null), '—');
eq('undefined → —', fmtDuration(undefined), '—');
eq('NaN → —', fmtDuration(NaN), '—');
eq('Infinity → —', fmtDuration(Infinity), '—');

/* ---- 三档主分支 ---- */
eq('0 → 0ms', fmtDuration(0), '0ms');
eq('480 → 480ms', fmtDuration(480), '480ms');
eq('1020 → 1.02s（两位小数）', fmtDuration(1020), '1.02s');
eq('8150 → 8.15s', fmtDuration(8150), '8.15s');
eq('9780 → 9.78s', fmtDuration(9780), '9.78s');
eq('12000 → 12.0s（一位小数）', fmtDuration(12000), '12.0s');
eq('82000 → 1m 22s（录屏里任务 2 的真实读数）', fmtDuration(82_000), '1m 22s');

/* ---- 进位边界：UI-1 的确案现场 ---- */
eq('999 → 999ms 不写成 1000ms', fmtDuration(999), '999ms');
eq('999.4 → 999ms', fmtDuration(999.4), '999ms');
eq('999.5 → 1.00s（换档到秒）', fmtDuration(999.5), '1.00s');
eq('9999 → 10.00s', fmtDuration(9_999), '10.00s');
eq('10000 → 10.0s', fmtDuration(10_000), '10.0s');
eq('59949 → 59.9s 不写成 60s', fmtDuration(59_949), '59.9s');
eq('59950 → 1m 0s（进位不留在秒位）', fmtDuration(59_950), '1m 0s');
eq('119600 → 2m 0s（曾经输出 1m 60s）', fmtDuration(119_600), '2m 0s');
eq('119999 → 2m 0s', fmtDuration(119_999), '2m 0s');
eq('120000 → 2m 0s', fmtDuration(120_000), '2m 0s');
eq('3599900 → 60m 0s（本函数不进时，只保证秒位归一）', fmtDuration(3_599_900), '60m 0s');

/* ---- 全区间扫描：秒位永远不许出现 60，ms 档永远不许出现 1000 ---- */
let carryBug = '';
for (let ms = 0; ms <= 7_200_000; ms += 50) {
  const out = fmtDuration(ms);
  const min = /^(\d+)m (\d+)s$/.exec(out);
  const secOnly = /^(\d+(?:\.\d+)?)s$/.exec(out);
  if (min && +min[2] > 59) carryBug = `fmtDuration(${ms}) = ${out}`;
  else if (out === '1000ms') carryBug = `fmtDuration(${ms}) = ${out}`;
  else if (secOnly && +secOnly[1] >= 60) carryBug = `fmtDuration(${ms}) = ${out}`;
  if (carryBug) break;
}
eq('0~2h 每 50ms 扫一遍，无未进位读数（首个反例 = 括号内）', carryBug, '');

/* ---- 其余展示层口径，顺手钉住 ---- */
eq('成本 0 → ¥0', fmtCost(0), '¥0');
eq('成本 13.1 分 → ¥0.0131（小额 4 位有效）', fmtCost(0.013139), '¥0.0131');
eq('成本 ≥1 元 → 两位', fmtCost(1.239), '¥1.24');
eq('成本缺值 → —', fmtCost(null), '—');
eq('百分比 2 位', fmtPct(0.9429, 2), '94.29%');
eq('百分比缺值 → 待测', fmtPct(undefined), '待测');
eq('整数千分位', fmtInt(22604), '22,604');

/* ---- downloadCsv：进 DOM → click → 摘掉 → 下一拍才 revoke（报告 B9） ----
   三个动作缺一不可，而全部三个都是"不报错、只是下载没发生"那一类：
   ① anchor 不进 document 就 click() —— Firefox / Safari 直接忽略下载；
   ② 同步 revokeObjectURL —— 下载还没真正开始，链接已经失效（Safari 会丢）；
   ③ click 之后不摘掉 anchor —— 一次导出攒一个无主的 <a>。
   替身只记这些现场，不实现 DOM。 */
(function downloadCsvCases() {
  const log = [];
  const timers = [];
  let revoked = 0;
  let made = null;
  let anchor = null;
  const body = {
    appendChild(n) {
      n.parentNode = body;
      log.push(['append']);
    },
    removeChild(n) {
      n.parentNode = null;
      log.push(['remove']);
    },
  };
  global.document = {
    body,
    createElement() {
      anchor = {
        style: {},
        parentNode: null,
        download: '',
        href: '',
        click() {
          // 点击那一刻的现场：在不在文档里、blob 有没有被提前撤掉
          log.push(['click', { inDom: anchor.parentNode === body, revoked }]);
        },
      };
      return anchor;
    },
  };
  global.Blob = class {
    constructor(parts, opts) {
      made = { parts, opts };
    }
  };
  global.URL = {
    createObjectURL: () => 'blob:fake/csv-1',
    revokeObjectURL: () => {
      revoked += 1;
    },
  };
  global.window = {
    // 只记录"排进了宏任务"，不同步执行 —— 同步执行就等于把 revoke 挪回原地，测了个寂寞
    setTimeout: (fn, ms) => {
      timers.push([fn, ms]);
      return 1;
    },
  };

  downloadCsv('groups.csv', ['a', 'b'], [['1', 'x,y'], ['2', 'he said "hi"'], ['3', 4]]);

  const seq = log.map((x) => x[0]).join(',');
  const atClick = (log.find((x) => x[0] === 'click') || [null, {}])[1];
  eq('B9①：click 那一刻 anchor 已在 document.body 里', atClick.inDom, true);
  eq('B9②：click 时 blob 还没被撤（revoke 不早于下载发起）', atClick.revoked, 0);
  eq('B9②：revoke 被排进宏任务，且只排一次', [timers.length, timers[0] ? typeof timers[0][0] : ''], [1, 'function']);
  eq('B9③：动作顺序 = append → click → remove（不攒无主的 <a>）', seq, 'append,click,remove');
  timers.forEach(([fn]) => fn());
  eq('B9②：宏任务真的跑起来时才 revoke 一次', revoked, 1);
  eq('文件名走 download 属性', anchor.download, 'groups.csv');
  eq('BOM 打头（Excel 才认 UTF-8）', made.parts[0].charCodeAt(0), 0xfeff);
  eq('逗号 / 引号 / 数字照样转义（改这三步不许动正文）', made.parts[0].slice(1), 'a,b\r\n1,"x,y"\r\n2,"he said ""hi"""\r\n3,4');
})();

/* ---- relativeFromDelta：P1-01 把秒表关进 Elapsed 后，运行条那行「最后一条日志 Ns 前」
   的文案就只剩这一个出口了（旧版是页面每次 tick 现算）。分档口径全部钉在这里：
   ①换档点（60s / 60min / 24h）按 floor 走，不许出现 "1m 60s" 那类自相矛盾的读数（UI-1 同一族）；
   ②非数字给 —，不补 0 —— 补 0 会把"读不出"显示成"刚刚发生过"；
   ③负数（后端时间比本地快 / 时钟回拨）说「刚刚」，不说「-3 秒前」。
   ⚠️ 已知且刻意保留的不连续：30_000 这一档文案是「30 秒前」，而运行条的黄色告警阈值
   是 `ms > LOG_STALE_MS`（严格大于），所以 30.000 秒整"读起来像到期、颜色还没变"。
   阈值在 RunBar.tsx，改任何一边都要同时改另一边的注释。 */
eq('非数字 → —（不补 0）', [relativeFromDelta(null), relativeFromDelta(undefined), relativeFromDelta(NaN)], ['—', '—', '—']);
eq('负 delta（时钟回拨 / 服务端快于本地）→ 刚刚', relativeFromDelta(-4_200), '刚刚');
eq('0 → 0 秒前', relativeFromDelta(0), '0 秒前');
eq('999ms 仍算 0 秒前（floor，不是 round）', relativeFromDelta(999), '0 秒前');
eq('1.5s → 1 秒前', relativeFromDelta(1_500), '1 秒前');
eq('30s → 30 秒前（运行条告警阈值同刻度，见上）', relativeFromDelta(30_000), '30 秒前');
eq('59.9s → 59 秒前（换档在整 60s）', relativeFromDelta(59_999), '59 秒前');
eq('60s → 1 分钟前', relativeFromDelta(60_000), '1 分钟前');
eq('90s → 1 分钟前', relativeFromDelta(90_000), '1 分钟前');
eq('59.9min → 59 分钟前', relativeFromDelta(3_599_000), '59 分钟前');
eq('60min → 1 小时前', relativeFromDelta(3_600_000), '1 小时前');
eq('23.9h → 23 小时前', relativeFromDelta(86_399_000), '23 小时前');
eq('24h → 1 天前', relativeFromDelta(86_400_000), '1 天前');
/* relativeTime 现在只是"减一下再交给 relativeFromDelta"：两条钉住委托关系，
   免得将来谁把分档表在两边各写一份，改一处漏一处。 */
eq('relativeTime 与 relativeFromDelta 同口径（5.4 秒前）', relativeTime(Date.now() - 5_400), '5 秒前');
eq('relativeTime 非数字同样 → —', relativeTime(undefined), '—');

console.log(`format: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
  process.exit(1);
}
