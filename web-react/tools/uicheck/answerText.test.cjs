/* pickConclusion / isNumericCell / 裸序号标题判定的断言集：npx esbuild 转成 cjs 后直接在 node 跑。
   用法：npx esbuild src/utils/answerText.ts --bundle --format=cjs --outfile=tools/uicheck/answerText.cjs
        node tools/uicheck/answerText.test.cjs */
const { pickConclusion, isNumericCell, isBareHeadingLine, liftBareHeadings } = require('./answerText.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

/* ---- 结论摘录 ---- */
eq(
  '标题独立成块，取下一块',
  pickConclusion('# 分析\n\n一些过程描述。\n\n## 结论\n\n整站峰值功耗约 463.6kW，建议按 2N 冗余配置。'),
  { label: '结论', text: '整站峰值功耗约 463.6kW，建议按 2N 冗余配置。' },
);

eq(
  '标题自带冒号',
  pickConclusion('## 结论：制冷系统 COP 为 4.2，优于风冷方案的 2.8。'),
  { label: '结论', text: '制冷系统 COP 为 4.2，优于风冷方案的 2.8。' },
);

eq(
  '加粗段首标签',
  pickConclusion('先讲过程。\n\n**结论**：PUE 从 1.55 降到 1.32。\n\n后面还有附录。'),
  { label: '结论', text: 'PUE 从 1.55 降到 1.32。' },
);

eq(
  '无冒号的「综上所述」整段端出，正文里不重复标签',
  pickConclusion('过程一。\n\n综上所述，该机房适合液冷改造，投资回收期约 3.4 年。'),
  { label: "综上所述", text: '该机房适合液冷改造，投资回收期约 3.4 年。' },
);

eq(
  '结论段是表格时不硬塞，退回首段',
  pickConclusion('这是第一段，讲的是背景与口径设定，长度足够被当成兜底摘要。\n\n## 结论\n\n| 项 | 值 |\n| --- | --- |\n| PUE | 1.32 |'),
  { label: '摘要', text: '这是第一段，讲的是背景与口径设定，长度足够被当成兜底摘要。' },
);

eq(
  '没有结论词 → 标成「摘要」，不冒充结论',
  pickConclusion('本次检索未命中相关规程条文，无法给出确定性结论建议。'),
  { label: '摘要', text: '本次检索未命中相关规程条文，无法给出确定性结论建议。' },
);

eq('空文本 → null', pickConclusion(''), null);

const long = '结论：' + '功耗校验通过。'.repeat(40);
const picked = pickConclusion(long);
eq('超长在句末标点截断', picked.text.length <= 200 && /[。！？]$/.test(picked.text), true);

/* ---- 数值列判定 ---- */
const numYes = ['463.6', '1,234', '-12.5', '7.7kW', '98 %', '380V', '12.3 kWh', '+0.5', '3.4 年'];
const numNo = ['约 7.7kW', '7.7 左右', 'PUE', '2024-09-23', '380V/50Hz', '—', '', 'A-3 路'];
for (const t of numYes) eq(`数值认作是: ${t}`, isNumericCell(t), true);
for (const t of numNo) eq(`数值认作非: ${t}`, isNumericCell(t), false);

/* ---- 裸序号小标题：口径来自库内 8 篇真答案（4/4 处都是「序号行 + 紧跟正文」） ---- */
eq('中文序号 + 短行 ⇒ 认作标题', isBareHeadingLine('一、门禁开门延时默认几秒？'), true);
eq('序号行里带算式也认（≤32 字）', isBareHeadingLine('二、用计算器算 12+30'), true);
eq('前后空白不影响判定', isBareHeadingLine('   三、结论   '), true);
/* 这四条是"宁可漏判也不弄坏结构"的那半边闸门 */
eq('阿拉伯序号不认（与有序列表撞车）', isBareHeadingLine('1、先用计算器算一遍'), false);
eq('带句号的整句不认（那是正文不是标题）', isBareHeadingLine('一、门禁延时默认 3-5 秒。'), false);
eq('超过 32 字不认', isBareHeadingLine('一、这一行特意写得很长很长超过了三十二个字符的闸门所以不该被当成标题'), false);
eq('表格行不认', isBareHeadingLine('一、项目 | 数值'), false);
eq('markdown 标题不重复认', isBareHeadingLine('## 结论'), false);

/* lift 的四种"不该动"：单独成段、非首行、围栏里、下一行是空行 */
eq(
  '序号行 + 紧跟正文 ⇒ 中间补一个空行',
  liftBareHeadings('一、门禁延时\n行业默认 3-5 秒。'),
  '一、门禁延时\n\n行业默认 3-5 秒。',
);
eq('单独成段的序号行不动（它本来就是段落）', liftBareHeadings('一、门禁延时\n\n正文。'), '一、门禁延时\n\n正文。');
eq('块中间的序号行不动（那是列表内容）', liftBareHeadings('前言。\n二、门禁延时'), '前言。\n二、门禁延时');
eq(
  '围栏代码块里一律不动',
  liftBareHeadings('```\n一、门禁延时\nprint(1)\n```'),
  '```\n一、门禁延时\nprint(1)\n```',
);
/* 最重要的一条：lift 只许加空白，一个字都不许动 —— 复制按钮给的是原文，
   渲染串与原文差一个字符就是页面在说谎（口径同 pyTokens 那套 round-trip）。 */
const LIFT_SRC =
  '一、门禁延时默认几秒？\n行业常见 3-5 秒。\n\n二、算一下\n```\n一、这不是标题\nprint(42)\n```\n1、这是列表';
eq(
  'lift 前后去掉空白的字符序列逐字相等（只加空白）',
  liftBareHeadings(LIFT_SRC).replace(/\s+/g, '') === LIFT_SRC.replace(/\s+/g, ''),
  true,
);

console.log(`answerText: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
  process.exit(1);
}
