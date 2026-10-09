/* 把**真实答案**灌进公式排布层，数每条到底换出了什么。
   这是「要不要上 KaTeX」的唯一依据 —— 探针里的 fixture 是我写的，不算证据。

   用法（JSON 由 tools/uicheck/formula_hits.py 同源的那张表导出，不落仓库）：
     node tools/uicheck/answerMath.test.cjs            # 断言集
     node tools/uicheck/realcorpus.cjs <answers.json>  # 真实语料命中率
*/
const fs = require('fs');
const { isMathBlock, remarkMathText } = require('./answerMath.cjs');
const { unified } = require('unified');
const remarkParse = require('remark-parse').default;
const remarkGfm = require('remark-gfm').default;
const remarkRehype = require('remark-rehype').default;

const file = process.argv[2];
if (!file) {
  console.error('用法：node tools/uicheck/realcorpus.cjs <answers.json>');
  process.exit(1);
}
const answers = JSON.parse(fs.readFileSync(file, 'utf8'));

function toHast(md) {
  const p = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMathText)
    .use(remarkRehype, { allowDangerousHtml: true });
  return p.runSync(p.parse(md));
}

function count(tree, pred) {
  let n = 0;
  (function walk(x) {
    if (pred(x)) n += 1;
    (x.children || []).forEach(walk);
  })(tree);
  return n;
}

const isTag = (t) => (x) => x.type === 'element' && x.tagName === t;
const isFrac = (x) =>
  x.type === 'element' && x.tagName === 'span' &&
  [].concat((x.properties || {}).className || []).includes('mx-frac');

const RX = {
  dollar: /\$[^$\n]{2,}\$/,
  latexMacro: /\\\w+/,
  unicodeOp: /[∑Σ∏∫√]/,
  braceScript: /[_\^]\s*\{[^{}]*\}/,
  spacedDiv: /\S\s\/\s\S/,
  bareUnder: /\w_\w/,
};

const tally = { dollar: 0, latexMacro: 0, unicodeOp: 0, braceScript: 0, spacedDiv: 0, bareUnder: 0 };
let withFrac = 0;
let withSub = 0;
let withBox = 0;
const detail = [];

for (const a of answers) {
  for (const k of Object.keys(RX)) if (RX[k].test(a)) tally[k] += 1;
  const tree = toHast(a);
  const fracs = count(tree, isFrac);
  const subs = count(tree, isTag('sub')) + count(tree, isTag('sup'));
  const boxes = count(
    tree,
    (x) =>
      x.type === 'element' &&
      [].concat((x.properties || {}).className || []).some((c) => c === 'ast-math'),
  );
  if (fracs) withFrac += 1;
  if (subs) withSub += 1;
  if (boxes) withBox += 1;
  detail.push({ fracs, subs, boxes, len: a.length, head: a.replace(/\s+/g, ' ').slice(0, 40) });
}

console.log(`真实答案 ${answers.length} 条\n`);
console.log('源文本里含该形态的条数：');
for (const [k, label] of [
  ['dollar', '$…$ 包裹的 LaTeX'],
  ['latexMacro', '任意 LaTeX 宏（\\frac \\cdot …）'],
  ['unicodeOp', 'Unicode 算符 Σ ∏ ∫ √'],
  ['braceScript', '带花括号下标 _{…} / ^{…}'],
  ['spacedDiv', '带空格除号 A / B'],
  ['bareUnder', '裸下划线 a_b（snake_case）'],
]) {
  console.log(`  ${label.padEnd(34)} ${tally[k]}/${answers.length}`);
}
console.log('\n经过排布层后真的变了样的条数：');
console.log(`  立起至少一个分数             ${withFrac}/${answers.length}`);
console.log(`  出现至少一个真上下标         ${withSub}/${answers.length}`);
console.log(`  出现至少一个公式区（灰盒）   ${withBox}/${answers.length}`);
console.log('\n逐条明细（fracs/subs/boxes）：');
for (const d of detail) console.log(`  ${d.fracs} / ${d.subs} / ${d.boxes}  len=${d.len}  ${d.head}`);

/* 裸下标这条规则的**误伤面**必须逐 token 看清楚，不能只数个数：
   把每条答案里被换成 <sub> 的文本全列出来，人工过一遍是不是都该是下标。 */
function subTexts(tree) {
  const out = [];
  (function walk(x) {
    if (x.type === 'element' && x.tagName === 'sub') {
      const t = (x.children || []).map((c) => c.value ?? '').join('');
      out.push(t);
    }
    (x.children || []).forEach(walk);
  })(tree);
  return out;
}

const allSubs = new Map();
for (const a of answers) {
  for (const t of subTexts(toHast(a))) allSubs.set(t, (allSubs.get(t) || 0) + 1);
}
console.log('\n真答案里被换成 <sub> 的全部 token（去重 + 次数）：');
console.log(allSubs.size ? [...allSubs].map(([k, v]) => `${k}×${v}`).join('  ') : '（一个都没有）');

const bareUnderscoreLeft = answers.filter((a) => /\w_\w/.test(a)).length;
console.log(`\n仍然留着裸下划线的答案条数：${bareUnderscoreLeft}/${answers.length}`);
for (const a of answers.filter((x) => /\w_\w/.test(x))) {
  const toks = [...new Set((a.match(/\w+_\w+/g) || []))];
  console.log(`   ${toks.slice(0, 8).join('  ')}${toks.length > 8 ? `  …共 ${toks.length} 种` : ''}`);
}

/* KaTeX 的增量只能来自「我们这套规则认不出」的那些：$…$ 与 LaTeX 宏 */
const katexWouldHelp = answers.filter(
  (a) => RX.dollar.test(a) || /\\(?:frac|sum|sqrt|cdot|Delta)\b/.test(a),
).length;
console.log(`\n上 KaTeX 才会额外受益的条数：${katexWouldHelp}/${answers.length}`);
