/* phaseOf 的断言集（结果页签那行"正在跑什么"）：
   npx esbuild src/utils/runPhase.ts --bundle --format=cjs --outfile=tools/uicheck/runPhase.cjs
   node tools/uicheck/runPhase.test.cjs

   这一族纯函数测试的存在理由与 modelLabel.test.cjs 一样：**措辞的真假只能靠推理检查**，
   拉浏览器的成本高，而它恰好是那种"数字全对、话说反了"的失效点。

   本轮真正要钉住的一条：后端的 SSE `node` 帧是**该节点跑完之后**才发的
   （api/queue.py 从 runner.stream() 拿到增量之后才 publish，LangGraph 的
   stream_mode="updates" 本身就是"节点完成才出增量"）。
   所以"收到 planner 事件"= planner 已经结束，屏上那句必须说**后继**在跑。
   写反了的形状是：planner 事件一到就印"正在规划任务"，而那一刻规划已经完了 ——
   界面看起来永远比真实进度慢一整拍，而且没有任何一帧能证明它错了。 */
const { phaseOf } = require('./runPhase.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}
function ok(name, cond, got) {
  if (cond) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}`);
}

const P = (node) => phaseOf(node);

/* ---------- 1. 四条阶段各一，且说的是"在跑的后继"而不是"刚完成的节点" ---------- */
eq('一条 node 事件都还没到 ⇒ 通用那句（不能指名"正在规划"，那一刻没有任何证据）',
  P(null).key, 'thinking');
eq('planner 已交卷 ⇒ 在跑的是 executor（定边 graph.py:61）', P('planner').key, 'executing');
eq('executor 已交卷 ⇒ 在跑的是 reviewer（定边 graph.py:62）', P('executor').key, 'reviewing');
eq('reviewer 已交卷 ⇒ 条件边在决定收口还是重跑，所以只能说"判断是否需要重跑"',
  P('reviewer').key, 'routing');

/* ---------- 2. 写反了要能红：每一档都不许提到刚完成的那个节点 ---------- */
const WRONG_WORDS = {
  planner: ['规划'],
  executor: ['执行'],
  reviewer: ['复核', '评审'],
};
for (const [node, banned] of Object.entries(WRONG_WORDS)) {
  const label = P(node).label;
  ok(`「${node} 已完成」那一档的文案里不许出现它自己的阶段词（${banned.join('/')}）：${label}`,
    banned.every((w) => !label.includes(w)), label);
}

/* ---------- 3. 未知节点不许编一个具体阶段 ---------- */
/* `''` / `undefined` 都归到 null 那一档：日志缓冲里本地插的 `system` 行、
   以及任务还没发出时压根没有事件，都不该读成某个具体阶段。 */
for (const weird of ['system', 'answer', 'router', '', undefined]) {
  const label = P(weird ?? null).label;
  const specific = ['规划', '执行', '复核', '评审', '重跑'];
  ok(`未知/非编排节点 ${JSON.stringify(weird) ?? 'undefined'} 退回通用措辞，不指名阶段`,
    specific.every((w) => !label.includes(w)), label);
}

/* ---------- 4. 文案形状：四条互不相同、都带主语、非空 ---------- */
const all = [P(null), P('planner'), P('executor'), P('reviewer')];
ok('四档文案两两不同（写成同一句就等于没有阶段感）',
  new Set(all.map((p) => p.label)).size === 4, all.map((p) => p.label));
ok('每档都以「Agent 正在」开头（主语在场，不写"正在…"这种无主语短句）',
  all.every((p) => p.label.startsWith('Agent 正在')), all.map((p) => p.label));
ok('每档都非空（空串会让那一行只剩三点，读屏什么也念不出）',
  all.every((p) => p.label.length > 0), all.map((p) => p.label));
ok('key 全部落在联合类型里（拼错的 key 会让 CSS/埋点静默失效）',
  all.every((p) => ['thinking', 'executing', 'reviewing', 'routing'].includes(p.key)),
  all.map((p) => p.key));

/* ---------- 5. 阶段推进的顺序与图一致：planner→executor→reviewer 不许倒 ---------- */
const ORDER = ['thinking', 'executing', 'reviewing'];
eq('前三档的推进顺序就是图的定边顺序',
  [P(null).key, P('planner').key, P('executor').key], ORDER);

console.log(`runPhase: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  for (const f of fails) console.log('  ✗ ' + f);
  process.exit(1);
}
