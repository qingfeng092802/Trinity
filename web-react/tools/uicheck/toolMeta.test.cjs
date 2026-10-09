/* toolMeta 的断言集（纯函数，不拉 React）。
   跑法：npx esbuild src/utils/toolMeta.ts --bundle --format=cjs --outfile=tools/uicheck/toolMeta.cjs
        node tools/uicheck/toolMeta.test.cjs */
const {
  BILLING_NOTE,
  TOOL_DISPLAY,
  argMetaOf,
  argSummary,
  codeArgOf,
  fieldsStack,
  intentSub,
  intentTitle,
  tooltipLines,
  toolOutcome,
  verbFor,
} = require('./toolMeta.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}
function ok(name, cond, got) {
  if (cond) pass += 1;
  else fails.push(`${name} — got ${JSON.stringify(got)}`);
}

const CALC = {
  name: 'calculator',
  description: '计算一个算术表达式并返回精确数值',
  danger_level: 'low',
  timeout: 5,
  retry: 0,
  parameters: {},
};
const CODE = {
  name: 'code_exec',
  description: '在沙箱子进程里运行 Python 代码',
  danger_level: 'high',
  timeout: 0,
  retry: 0,
  parameters: {},
};

/* ---- 意图标题 ---- */
eq('有 thought 时标题就是 thought（去掉句末句号）',
  intentTitle('calculator', '{"expression":"1024*0.85*17.5"}', '先按整机口径估一遍总功耗。'),
  '先按整机口径估一遍总功耗');

eq('无 thought 退回「动词：关键入参」',
  intentTitle('calculator', '{"expression":"1024*0.85*17.5"}', null),
  '正在算这笔数：1024*0.85*17.5');

eq('字典没收录的工具不瞎编',
  intentTitle('ocr_table', '{"image":"a.png"}', null),
  '正在调用 ocr_table');

eq('入参解不动时只留动词', intentTitle('calculator', 'not json', ''), '正在算这笔数');

eq('副行：thought 当标题时把入参补在下面',
  intentSub('knowledge_search', '{"query":"POE 单端口最大输出功率","top_k":5}', '查原文段落'),
  '正在翻知识库：POE 单端口最大输出功率');

eq('副行：标题已经用了入参就不再重复', intentSub('calculator', '{"expression":"1+1"}', null), null);

/* ---- 动词与入参摘要 ---- */
eq('file_io 按 mode 细分动词', verbFor('file_io', '{"path":"a","mode":"list"}'), '正在列目录');
eq('file_io 未知 mode 退回静态动词', verbFor('file_io', '{"path":"a","mode":"stat"}'), '正在读写文件');
eq('argSummary 取第一个存在的字段', argSummary('extract', '{"text":"规程原文","schema":"{}"}'), '规程原文');
eq('argSummary 认数字字段', argSummary('calculator', '{"expression":42}'), '42');
eq('argSummary 空串不算命中', argSummary('calculator', '{"expression":"  "}'), null);
eq('非 JSON 入参不猜', argSummary('calculator', '表达式 1+1'), null);
eq('数组入参不猜', argSummary('calculator', '[1,2]'), null);

const long = argSummary('code_exec', JSON.stringify({ code: `a${'b'.repeat(400)}` }));
ok('超长入参压成一行并截断', long.length <= 110 && !long.includes('\n') && long.endsWith('…'), {
  len: long.length,
});

/* ---- Tooltip ---- */
const tipCalc = tooltipLines('calculator', CALC);
eq('字典工具：大白话 + 计费 + 注册表参数', tipCalc.length, 3);
ok('第一行是大白话不是注册表原文', tipCalc[0] === TOOL_DISPLAY.calculator.plain, tipCalc[0]);
eq('计费口径本地执行', tipCalc[1], BILLING_NOTE.local);
ok('注册表行带超时/重试/权限', /^注册表 · 超时 5s · 失败重试 0 次 · 常规权限$/.test(tipCalc[2]), tipCalc[2]);

const tipCode = tooltipLines('code_exec', CODE);
ok('超时 0 说成「交给工具自己管」', tipCode[2].includes('交给工具自己管'), tipCode[2]);
ok('高危工具标出来', tipCode[2].includes('高危'), tipCode[2]);

eq('未收录 + 无注册表：如实说没收录', tooltipLines('ocr_table', undefined), ['未在字典里收录的工具：ocr_table']);
eq('未收录但有注册表：用注册表说明兜底', tooltipLines('new_tool', { ...CALC, name: 'new_tool' })[0], '计算一个算术表达式并返回精确数值');

/* ---- 字典自身 ---- */
for (const [name, d] of Object.entries(TOOL_DISPLAY)) {
  ok(`${name}：四个字段都齐`, Boolean(d.plain && d.verb && d.billing && d.intentArgs.length), d);
  ok(`${name}：计费口径有对应文案`, Boolean(BILLING_NOTE[d.billing]), d.billing);
}
eq('计费分类按源码口径', {
  calculator: TOOL_DISPLAY.calculator.billing,
  knowledge_search: TOOL_DISPLAY.knowledge_search.billing,
  web_search: TOOL_DISPLAY.web_search.billing,
  extract: TOOL_DISPLAY.extract.billing,
}, { calculator: 'local', knowledge_search: 'local', web_search: 'external', extract: 'llm' });

/* ---- code_exec 的意图标题：绝不再拿代码截断凑数 ---- */
const SCAN_CODE =
  "import os, re, time\nroots = ['/etc', '/var/log']\nfor r in roots:\n    for d, _, fs in os.walk(r):\n        print(d)";
const codeArgs = (code) => JSON.stringify({ code, timeout_s: 30 });

eq(
  '有 thought 时优先用 thought',
  intentTitle('code_exec', codeArgs(SCAN_CODE), '先扫一遍系统日志目录看有没有异常项'),
  '先扫一遍系统日志目录看有没有异常项',
);
eq(
  '无 thought 但能提炼：import os + roots = [...] → 扫描系统文件',
  intentTitle('code_exec', codeArgs(SCAN_CODE), null),
  '正在扫描系统文件',
);
ok(
  '提炼出的标题里一个代码字符都没有',
  !/import|os\.walk|roots/.test(intentTitle('code_exec', codeArgs(SCAN_CODE), null)),
  intentTitle('code_exec', codeArgs(SCAN_CODE), null),
);
eq(
  '无 thought 也提炼不出：兜底报字符数，不报代码',
  intentTitle('code_exec', codeArgs('answer = 6 * 7'), null),
  '正在执行 Python 脚本（14 字符）',
);
eq('requests.get 认成网络请求', intentTitle('code_exec', codeArgs("import requests\nr = requests.get(url)"), null), '正在发送网络请求');
eq(
  '代码原文仍留在副行里（标题不摆代码，但入参不能藏）',
  intentSub('code_exec', codeArgs(SCAN_CODE), '先扫一遍'),
  "正在跑一段代码：import os, re, time roots = ['/etc', '/var/log'] for r in roots: for d, _, fs in os.walk(r): print(d)",
);
eq('入参不是 JSON 时不猜：退回动词', intentTitle('code_exec', 'import os\nroots = []', null), '正在跑一段代码');
eq('calculator 的标题不受影响', intentTitle('calculator', '{"expression":"1024*0.85"}', null), '正在算这笔数：1024*0.85');

/* ---- toolOutcome：只认后端 status ----
   这里曾经有第四档「嗅出参文本」（exit_code≠0 / 「执行超时」字样），用来兜后端把
   脚本非零退出记成 success 的那段谎。2026-09-24 后端修了谎（code_exec 对
   returncode != 0 抛 SandboxFailed → registry 记 failed），嗅探随之删除。
   删除依据：当时库内 27 条 tool_call 里 status=success 且出参含非零 exit_code 的行为 0。 */
const OUT = (s) => {
  const r = toolOutcome(s);
  return { tone: r.tone, label: r.label, bad: r.bad };
};
eq('failed → 红色失败', OUT('failed'), { tone: 'error', label: '失败', bad: true });
eq(
  'timeout → 琥珀「执行异常 · 超时」，不再被折成绿色成功',
  OUT('timeout'),
  { tone: 'warn', label: '执行异常 · 超时', bad: true },
);
eq('success → 绿色成功', OUT('success'), { tone: 'ok', label: '成功', bad: false });
ok(
  '降级档文案必须含「异常」或「失败」，不能让人读成成功',
  [OUT('timeout'), OUT('failed')].every((r) => /异常|失败/.test(r.label)),
  [OUT('timeout'), OUT('failed')],
);
/* 结构护栏：函数只接 status 一个参数 —— 想再把出参喂进来判成败，得先改签名，
   改签名就会撞上 TaskLogPage 那个调用点，不会悄悄长回来。 */
eq('toolOutcome 只接 status 一个参数（文本嗅探不可悄悄回归）', toolOutcome.length, 1);

/* ---------------- 源码入参：哪个字段该走代码块、其余字段留一行小字 ---------------- */

const CODE_ARGS = JSON.stringify({ code: 'import os\nprint(1)', timeout_s: 30 });
eq('code_exec 取出 code 字段（真换行，不是 JSON 字面量）', codeArgOf('code_exec', CODE_ARGS), 'import os\nprint(1)');
eq('其余入参压成一行小字', argMetaOf('code_exec', CODE_ARGS), 'timeout_s=30');
eq('code_exec 走堆叠布局', fieldsStack('code_exec'), true);
eq('calculator 仍是左右分栏', fieldsStack('calculator'), false);
eq('字典外的工具不猜布局', fieldsStack('ocr_table'), false);
eq('非源码工具不给 codeArgOf 结果', codeArgOf('calculator', '{"expression":"1+1"}'), null);
eq('解不出 JSON 就交回 JsonView', codeArgOf('code_exec', '我要是一段文本'), null);
eq('空字符串不冒充代码', codeArgOf('code_exec', '{"code":"   "}'), null);
eq('字段名不对就不抢渲染', codeArgOf('code_exec', '{"cmd":"ls -la"}'), null);
eq('字符串型其余入参也进小字', argMetaOf('code_exec', JSON.stringify({ code: 'x', note: '核一遍三相不平衡度' })), 'note=核一遍三相不平衡度');
eq('只剩源码字段时不给空小字', argMetaOf('code_exec', '{"code":"x"}'), null);
eq('没有 codeArg 声明的工具不给小字', argMetaOf('calculator', '{"expression":"1+1"}'), null);

console.log(`toolMeta: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
  process.exit(1);
}
