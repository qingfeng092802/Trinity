/* 心跳行合并的断言集：npx esbuild 转成 cjs 后直接在 node 跑。
   用法：npx esbuild src/utils/logRows.ts --bundle --format=cjs --outfile=tools/uicheck/logRows.cjs
        node tools/uicheck/logRows.test.cjs */
const { collapseRepeats, mergedAway } = require('./logRows.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

/** 造一条事件：只关心 node/level/message/idleMs */
const ev = (seq, node, message, extra = {}) => ({
  seq,
  ts: 1700000000000 + seq * 1000,
  level: 'info',
  node,
  message,
  ...extra,
});

/* ---- 基本形状 ---- */
const single = collapseRepeats([ev(1, 'planner', '规划 3 步：先检索')]);
eq('一条事件 = 一行，repeat=1', single.map((r) => r.repeat), [1]);
eq('head 就是原事件', single[0].head.message, '规划 3 步：先检索');
eq('空数组 → 空行数组', collapseRepeats([]), []);

/* ---- 心跳：这次改动的正题 ---- */
const beats = [
  ev(2, 'system', '等待节点事件', { level: 'debug', idleMs: 15000 }),
  ev(3, 'system', '等待节点事件', { level: 'debug', idleMs: 30000 }),
  ev(4, 'system', '等待节点事件', { level: 'debug', idleMs: 45000 }),
];
const [beat] = collapseRepeats([ev(1, 'executor', '步骤 1：检索 → 命中 3 段'), ...beats]);
eq('连续三条心跳并成一行', collapseRepeats(beats).map((r) => r.repeat), [3]);
eq('key 身份取首条 seq（原地刷新的前提）', collapseRepeats(beats)[0].head.seq, 2);
eq('时间戳跟随最后一条', collapseRepeats(beats)[0].idleMs, 45000);
eq('前面的真节点行不受影响', beat.head.message, '步骤 1：检索 → 命中 3 段');
eq('合并掉的条数', mergedAway(collapseRepeats(beats)), 2);

/* ---- 保守边界：不该并的绝不并 ---- */
eq(
  '文本不同不并（哪怕只差一个字符）',
  collapseRepeats([ev(1, 'system', '等待节点事件'), ev(2, 'system', '等待节点事件 ')]).map((r) => r.repeat),
  [1, 1],
);
eq(
  '不相邻的同文本不并（时间线顺序不能被缝起来）',
  collapseRepeats([
    ev(1, 'system', '等待节点事件'),
    ev(2, 'planner', '规划 3 步'),
    ev(3, 'system', '等待节点事件'),
  ]).map((r) => r.repeat),
  [1, 1, 1],
);
eq(
  '跨节点的同文本不并',
  collapseRepeats([ev(1, 'planner', '执行中'), ev(2, 'executor', '执行中')]).map((r) => r.repeat),
  [1, 1],
);
eq(
  '级别不同的同文本不并',
  collapseRepeats([
    ev(1, 'system', '失败', { level: 'info' }),
    ev(2, 'system', '失败', { level: 'error' }),
  ]).map((r) => r.repeat),
  [1, 1],
);

/* ---- 幂等与不共享状态（StrictMode 双跑的同一条纪律） ---- */
const input = [ev(1, 'system', '等待节点事件'), ev(2, 'system', '等待节点事件')];
const twice = [collapseRepeats(input), collapseRepeats(input)];
eq('同一输入跑两次结果一致', twice[1], twice[0]);
eq('第二次不会把 repeat 累加上去', twice[1][0].repeat, 2);
eq('不改动传入的事件对象', input[0].seq, 1);
eq(
  '无 idleMs 时不造假值',
  'idleMs' in twice[0][0],
  true,
);
eq('无心跳时 idleMs 为 undefined', collapseRepeats(input)[0].idleMs, undefined);

console.log(`\nlogRows：${pass} 项通过`);
if (fails.length) {
  console.error(`\n✗ ${fails.length} 项失败：\n` + fails.join('\n\n'));
  process.exitCode = 1;
}
