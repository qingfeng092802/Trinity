/* Python 极简分词的断言集：npx esbuild 转成 cjs 后直接在 node 跑。
   用法：npx esbuild src/utils/pyTokens.ts --bundle --format=cjs --outfile=tools/uicheck/pyTokens.cjs
        node tools/uicheck/pyTokens.test.cjs

   最看重的是第一条：**片段拼回去必须等于原文**。上色是装饰，吞字符是事故 ——
   入参块里的代码是用户排查问题的唯一现场。 */
const { tokenizePython, codeSize } = require('./pyTokens.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

const join = (segs) => segs.map((s) => s.text).join('');
const cls = (segs, want) => segs.filter((s) => s.cls === want).map((s) => s.text);

/** 拼回原文 —— 每条样本都过一遍，不单独写用例容易漏。 */
function roundTrip(name, src) {
  eq(`无损：${name}`, join(tokenizePython(src)), src);
}

/** 与 mocks.cjs 里 seq 12 同形状的脚本（真换行版）。 */
const MOCK_SCRIPT =
  '"""扫一遍工作区，统计文件数与最大的单个文件。"""\n' +
  'import os, re, time  # 只读遍历，不写不删\n' +
  'roots = [".", "/data", "/var/log"]\n' +
  'pat = re.compile(r"\\d+(\\.\\d+)?")\n' +
  'hits = []\n' +
  't0 = time.time()\n' +
  'for r in roots:\n' +
  '    for d, sub, fs in os.walk(r):\n' +
  '        for f in fs:\n' +
  '            p = os.path.join(d, f)\n' +
  '            try:\n' +
  '                hits.append((p, os.path.getsize(p)))\n' +
  '            except OSError:\n' +
  '                continue\n' +
  "print(f'共 {len(hits)} 个文件，最大 {max(s for _, s in hits):,} 字节')";

/* ---- 四类色 ---- */
const kwSrc = 'for r in roots:\n    print(r)';
eq('关键字 for / in 认出来', cls(tokenizePython(kwSrc), 'kw'), ['for', 'in']);
eq('print 这种内置函数不上色（宁少不错）', cls(tokenizePython(kwSrc), 'str'), []);

eq(
  '单引号串整体一段',
  cls(tokenizePython("roots = ['.']"), 'str'),
  ["'.'"],
);
eq('双引号串', cls(tokenizePython('p = "/data"'), 'str'), ['"/data"']);
eq('转义引号不断串', cls(tokenizePython('s = "a\\"b"'), 'str'), ['"a\\"b"']);
eq('# 起手的注释', cls(tokenizePython('x = 1  # 说明'), 'com'), ['# 说明']);
eq('井号紧跟标识符也算注释（与 CPython 切法一致）', cls(tokenizePython('u = a#b'), 'com'), ['#b']);
eq('数字', cls(tokenizePython('t = 30'), 'num'), ['30']);
eq('浮点', cls(tokenizePython('k = 1.5e-3'), 'num'), ['1.5e-3']);
eq('科学计数没有小数点', cls(tokenizePython('k = 2e3'), 'num'), ['2e3']);
eq('省略整数位的小数', cls(tokenizePython('k = .5'), 'num'), ['.5']);
eq('下划线分隔的整数（一次吃完整串）', cls(tokenizePython('n = 1_000_000'), 'num'), ['1_000_000']);
eq('十六进制', cls(tokenizePython('m = 0xFF'), 'num'), ['0xFF']);
eq('复数后缀', cls(tokenizePython('z = 1.2j'), 'num'), ['1.2j']);
/* 属性访问里的点不能被当小数：os.path.getsize 后面跟的是标识符，不是数字 */
eq('点号后不是数字就不算数', cls(tokenizePython('os.path.getsize(p)'), 'num'), []);

/* ---- 三引号跨行：docstring 是一整段，不能被切成三段 ---- */
const doc = '"""第一行\n第二行\n"""\nx = 1';
eq('三引号串含首尾引号共一段', cls(tokenizePython(doc), 'str'), ['"""第一行\n第二行\n"""']);
roundTrip('三引号跨行', doc);
/* 未闭合的三引号：只把开头那三个引号当串，后面的代码照常切 —— 半截源码不能整块变白 */
eq('未闭合三引号只吃掉开头三个引号', cls(tokenizePython('"""\nx = 1'), 'str'), ['"""']);
roundTrip('未闭合三引号', '"""\nx = 1');

/* ---- 容易误判的形状 ---- */
eq('re.match 的 match 不当软关键字', cls(tokenizePython('re.match(p, s)'), 'kw'), []);
eq('f-string 前缀连着串', cls(tokenizePython("print(f'a{b}')"), 'str'), ["f'a{b}'"]);
eq('r-string 前缀连着串', cls(tokenizePython("re.compile(r'\\d+')"), 'str'), ["r'\\d+'"]);
eq('roots 不以 r 起手的串误判', cls(tokenizePython('roots = []'), 'str'), []);
eq('rb_test 这类标识符不被当字符串前缀', cls(tokenizePython('rb_test = 1'), 'str'), []);

/* ---- 空值与体量 ---- */
eq('空串 → 空片段数组', tokenizePython(''), []);
eq('只有换行也不丢', join(tokenizePython('\n\n')), '\n\n');
roundTrip('真实 15 行脚本', MOCK_SCRIPT);

/* ---- codeSize：折叠按钮上的那两个数 ---- */
eq('行数按 \\n 切，含末行', codeSize('a\nb\nc').lines, 3);
eq('空串行数 0 / 字符 0', codeSize(''), { lines: 0, chars: 0 });
eq('字符数含换行', codeSize('ab\nc').chars, 4);

/* ---- 安全：源码里出现标签也只当文本（组件不碰 innerHTML，这里验分词不拆坏） ---- */
const evil = 'x = "<script>alert(1)</script>"  # <img src=x onerror=alert(1)>';
eq('标签字符串原样拼回', join(tokenizePython(evil)), evil);
eq('标签不产生额外片段类型', [...new Set(tokenizePython(evil).map((s) => s.cls))].sort(), [
  'com',
  'plain',
  'str',
]);

console.log(`\npyTokens：${pass} 项通过`);
if (fails.length) {
  console.error(`\n✗ ${fails.length} 项失败：\n\n` + fails.join('\n\n'));
  process.exitCode = 1;
}
