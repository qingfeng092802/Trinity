/* 公式排布层的断言集（utils/answerMath.ts）。三块：
   1. isMathBlock 的判定 —— 判公式，但别把散文装进灰盒子；
   2. remarkMathText 真的产出 sub / sup / 分数结构（含代码节点里的公式）；
   3. 安全性 —— 模型输出里的 HTML 只能到 raw，不许变成元素。

   ⚠️ 这里的期望值全部是**跑出来的**（tools/uicheck/mathdump.cjs 打印的实测串），
   不是照着代码猜的。改了实现就重新跑一遍 dump，别改期望值去迁就代码。
   用法：npx esbuild src/utils/answerMath.ts --bundle --format=cjs --outfile=tools/uicheck/answerMath.cjs
        node tools/uicheck/answerMath.test.cjs
   unified / remark-* 是 ESM，require 回来要取 `.default`。 */
const { isMathBlock, remarkMathText } = require('./answerMath.cjs');
const { unified } = require('unified');
const remarkParse = require('remark-parse').default;
const remarkGfm = require('remark-gfm').default;
const remarkRehype = require('remark-rehype').default;

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

/** 与产品同款的处理链：react-markdown 内部用 allowDangerousHtml: true，
 *  再自己把 raw 节点渲染成文本。默认配置（false）会整节点丢掉，那样测的不是产品行为。 */
function html(md) {
  const p = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMathText)
    .use(remarkRehype, { allowDangerousHtml: true });
  const tree = p.runSync(p.parse(md));
  return ser(tree);
}

/** hast → 「带类名的简化 HTML」串，raw 节点显式标出来好断言。 */
function ser(n) {
  if (n.type === 'root') return (n.children || []).map(ser).join('');
  if (n.type === 'text') return n.value;
  if (n.type === 'raw') return `RAW(${n.value})`;
  const cls =
    n.properties && n.properties.className ? '.' + [].concat(n.properties.className).join('.') : '';
  return `<${n.tagName}${cls}>${(n.children || []).map(ser).join('')}</${n.tagName}>`;
}

/** hast 里出现过的元素标签名（去重排序），供「不许冒出没登记的标签」用。 */
function tagNames(md) {
  const p = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMathText)
    .use(remarkRehype, { allowDangerousHtml: true });
  const tree = p.runSync(p.parse(md));
  const out = new Set();
  (function walk(n) {
    if (n.type === 'element') out.add(n.tagName);
    (n.children || []).forEach(walk);
  })(tree);
  return [...out].sort();
}

/* ==================== 1. isMathBlock ==================== */

const MATH = [
  'score(q,d) = Σ_{t∈q} tf(t,d) · idf(t)',
  'P_total = 1024 × 12 / 0.92',
  'COP = Q_cool / W_comp',
  'η = (T1 - T2) / T1',
  'x ^ 2 + y ^ 2 = r ^ 2',
  'nDCG@5 = DCG@5 / IDCG@5',
  'P = U × I + losses',
];
for (const s of MATH) eq(`公式判真：${s.slice(0, 24)}`, isMathBlock(s), true);

const PROSE = [
  '综上，整机功耗约 28.76 kW，建议按 2N 冗余配置。',
  '本次检索未命中相关规程条文，无法给出确定性结论。',
  '配置说明：超时 = 30s，重试 = 2 次。',
  '结论：PUE 从 1.55 降到 1.32。',
  '知识库检索工具本次调用失败——knowledge_search 返回 KnowledgeSearchError',
  '调用 knowledge_search 与 code_exec 两个工具。',
  '路径 /data/kb 下有两个文件',
  // 反引号把拉丁字符密度撑上去了（占比仅 26%），靠占比挡不住 —— 靠连续汉字串挡
  '行内形式 `COP = Q_{cool} / W_{comp}` 与之一致。',
  '卡诺轩制冷系数写作 \\frac{Q_{cool}}{W_{comp}} ，按第二定律上限只与温度有关',
  '',
  '   ',
];
for (const s of PROSE) eq(`散文判假：${s.slice(0, 24) || '(空)'}`, isMathBlock(s), false);

/* 边界：花括号不再单独当判据 —— 汉字占大头就是「带着公式的散文」，不许套灰盒子 */
eq('超 400 字的长段不判公式', isMathBlock(`a = ${'1+1 '.repeat(120)}`), false);
eq(
  '中文句子里夹一个下标：算式换下标，但不算公式段',
  isMathBlock('q _ {prefix} 的前缀部分，表示检索词的公共前缀'),
  false,
);
eq('只有上下标、符号密集的段仍判公式', isMathBlock('q _ {prefix} = a_{1}'), true);

/* ==================== 2. 上下标 ==================== */

eq(
  'Σ_{t∈q} → 真的出现 sub 元素',
  html('score(q,d) = Σ_{t∈q} tf(t,d) · idf(t)'),
  '<p>score(q,d) = Σ<sub>t∈q</sub> tf(t,d) · idf(t)</p>',
);
eq(
  '^{...} → sup（允许 ^ 与花括号之间有空格）',
  html('x ^ {2} + y ^ {2} = r ^ {2}'),
  '<p>x <sup>2</sup> + y <sup>2</sup> = r <sup>2</sup></p>',
);
eq('同一行混排按顺序', html('a_{i} + b^{j} = c'), '<p>a<sub>i</sub> + b<sup>j</sup> = c</p>');
eq('snake_case 不被咬掉（无花括号）', html('用 knowledge_search 检索'), '<p>用 knowledge_search 检索</p>');
eq('花括号嵌套 → 整体不动它，认不准就不猜', html('a _{b{c}d} e'), '<p>a _{b{c}d} e</p>');
/* 紧凑列表的 li 里没有 p 节点，sub 直接挂在 li 上 */
eq('列表项里的下标同样生效', html('- nDCG@5 = DCG_{5}'), '<ul>\n<li>nDCG@5 = DCG<sub>5</sub></li>\n</ul>');

/* ==================== 3. \frac → 上下结构的分数 ==================== */

const FRAC_OUT = (body) =>
  `<span.mx-frac><span.mx-num>${body[0]}</span><span.mx-den>${body[1]}</span></span>`;

eq(
  '\\frac{A}{B} → 上下两层 + 中线（结构在类名里，CSS 负责画线）',
  html('nDCG@k = \\frac{DCG@k}{IDCG@k}'),
  `<p>nDCG@k = ${FRAC_OUT(['DCG@k', 'IDCG@k'])}</p>`,
);
eq(
  '\\frac 的参数里允许一层花括号：分子带真下标',
  html('η_th = \\frac{W_{net}}{Q_{in}}'),
  `<p>η_th = ${FRAC_OUT(['W<sub>net</sub>', 'Q<sub>in</sub>'])}</p>`,
);
eq('两段花括号之间允许有空格', html('P = \\frac {U} {I}'), `<p>P = ${FRAC_OUT(['U', 'I'])}</p>`);

/* ==================== 4. 算式里唯一那个带空格的 A / B ==================== */

eq(
  'P_total = 1024 × 12 / 0.92 → 除法立起来',
  html('P_total = 1024 × 12 / 0.92'),
  `<p>P<sub>total</sub> = ${FRAC_OUT(['1024 × 12', '0.92'])}</p>`,
);
eq(
  '下标与除法同时存在也切（最常见的真实算式）',
  html('score(q,d) = Σ_{t∈q} tf(t,d) / norm(d)'),
  `<p>score(q,d) = ${FRAC_OUT(['Σ<sub>t∈q</sub> tf(t,d)', 'norm(d)'])}</p>`,
);
eq(
  '分母尾巴上的句号留在分数外面',
  html('COP = Q_cool / W_comp。'),
  `<p>COP = ${FRAC_OUT(['Q<sub>cool</sub>', 'W<sub>comp</sub>'])}。</p>`,
);
eq(
  '右括号属于分母本身，不许剥（剥了就把算式切断）',
  html('η = (T1 - T2) / (T1 + T2)'),
  `<p>η = ${FRAC_OUT(['(T1 - T2)', '(T1 + T2)'])}</p>`,
);

/* ---- 不猜的三种：连续除、不带空格、切在等号左边 ---- */
eq('连续除 a / b / c 不猜', html('η = a / b / c'), '<p>η = a / b / c</p>');
eq('不带空格的 Q/W_in 不切除法（但 _in 照旧是下标）', html('η = Q/W_in'), '<p>η = Q/W<sub>in</sub></p>');
eq('斜杠在等号左边不切', html('a / b = c'), '<p>a / b = c</p>');
eq('散文段里的斜杠不切', html('路径 /data/kb 与 Q / W 两个都行'), '<p>路径 /data/kb 与 Q / W 两个都行</p>');
/* 表格行以 `|` 开头：拿整行切「A / B」会切出「分子是一整张表」 */
eq(
  '未转成表格的竖线行不切除法',
  html('| nDCG | DCG_{5} / IDCG_{5} |'),
  '<p>| nDCG | DCG<sub>5</sub> / IDCG<sub>5</sub> |</p>',
);
eq(
  '真表格的单元格照样立成分数',
  html('指标：\n\n| 名称 | 值 |\n| - | - |\n| nDCG | DCG_{5} / IDCG_{5} |\n'),
  '<p>指标：</p>\n<table>\n<thead>\n<tr>\n<th>名称</th>\n<th>值</th>\n</tr>\n</thead>\n<tbody>\n<tr>\n<td>nDCG</td>\n' +
    `<td>${FRAC_OUT(['DCG<sub>5</sub>', 'IDCG<sub>5</sub>'])}</td>\n</tr>\n</tbody>\n</table>`,
);
eq(
  '紧凑列表项里的除法也切（li 里没有 p 节点，只判 paragraph 会漏）',
  html('- nDCG@5 = DCG_{5} / IDCG_{5}\n- 第二条'),
  `<ul>\n<li>nDCG@5 = ${FRAC_OUT(['DCG<sub>5</sub>', 'IDCG<sub>5</sub>'])}</li>\n<li>第二条</li>\n</ul>`,
);

/* ---- 两道「不许猜错」的闸门（都是 DOM 探针抓出来的真实断裂，不是设想） ---- */
const LONG_NDCG =
  'nDCG@k = DCG@k / IDCG@k ，其中 DCG@k = Σ_{i=1..k} (2^{rel_i} - 1) / log2(i + 1) ，IDCG@k = Σ_{i=1..k} (2^{rel_i^ast} - 1) / log2(i + 1) ，rel^ast 为按增益降序重排后的相关性分级';
eq(
  '下标里的等号（Σ_{i=1..k}）不许当算式分界',
  (html(LONG_NDCG).match(/mx-frac/g) || []).length,
  0,
);
eq('长行里的上下标照换，且不残留裸 _{', /[_^]\{/.test(html(LONG_NDCG)), false);
eq(
  '斜杠右边接的是散文（分子分母带汉字/全角）就不立分数',
  html('η_{th} = Q_in / W_comp ，其中 Q_in 为吸热量'),
  '<p>η<sub>th</sub> = Q<sub>in</sub> / W<sub>comp</sub> ，其中 Q<sub>in</sub> 为吸热量</p>',
);

/* ==================== 4.5 裸简写下标：模型不写花括号的那一种 ====================
   这四条是他 2026-09-24 在 Edge 里截图的真实行（P_IT / η_PoE / P_PoE_chain 全是简写）。 */

eq(
  'P_IT = N × P_cam ÷ η_PoE + … → 每个变量都是真下标',
  html('P_IT = N × P_cam ÷ η_PoE + P_sw + P_NVR + P_net + P_aux [W]'),
  '<p>P<sub>IT</sub> = N × P<sub>cam</sub> ÷ η<sub>PoE</sub> + P<sub>sw</sub> + P<sub>NVR</sub>' +
    ' + P<sub>net</sub> + P<sub>aux</sub> [W]</p>',
);
eq(
  '带中文说明的算式行也认（isMathBlock 会把它判成散文，裸下标用的是松一档的 formulaish）',
  html('PoE链路段：P_PoE_chain = N × P_cam ÷ η_PoE （摄像头受电功率折算为交换机输入端取电）'),
  '<p>PoE链路段：P<sub>PoE_chain</sub> = N × P<sub>cam</sub> ÷ η<sub>PoE</sub> （摄像头受电功率折算为交换机输入端取电）</p>',
);
eq(
  'P_mains = P_IT ÷ η_UPS',
  html('P_mains = P_IT ÷ η_UPS [W]'),
  '<p>P<sub>mains</sub> = P<sub>IT</sub> ÷ η<sub>UPS</sub> [W]</p>',
);
eq(
  '一条式子里多个简写全切（不能只切第一个）',
  html('P_infra = P_sw + P_NVR + P_net + P_aux'),
  '<p>P<sub>infra</sub> = P<sub>sw</sub> + P<sub>NVR</sub> + P<sub>net</sub> + P<sub>aux</sub></p>',
);

/* ---- 防误伤：以下每一条都必须**一个字都不变** ----
   挡事的判据是「基座必须是单个字母，且前面不能贴词字符」——
   snake_case 的基座永远是多个字母，所以整类被排除，不需要列黑名单。 */
const UNCHANGED = [
  ['工具名（真语料 4/16 条命中）', '已完成 4 个子步骤： 1. 用 knowledge_search 检索知识库获得依据条文。'],
  ['文件名 .py / .js', '配置文件 my_file.py 与 read_config.js 都在 scripts 下。'],
  ['全大写蛇形常量', '常量 FOO_BAR 与 MAX_LOG_EVENTS 决定封顶行数。'],
  ['散文里的等号（没有运算符）', '配置说明：超时 = 30s，重试 = 2 次。'],
  ['向量库名', '本次走 sqlite_vec 扩展，索引由 rebuild 生成。'],
  ['工具调用名混在算式段里', 'score = knowledge_search(q) × w_1 + b_2'],
];
for (const [name, md] of UNCHANGED) {
  const out = html(md);
  /* 「工具名混在算式段里」这条是**部分**转换：knowledge_search 不动，w_1 / b_2 要动。
     所以判据写成「不含 <sub>knowledge</sub>」而不是「整条不变」—— 别把设计当 bug。 */
  if (name.startsWith('工具调用名')) {
    eq(`不误伤：${name}`, /<sub>knowledge<\/sub>|<sub>search<\/sub>|<sub>knowledge_search<\/sub>/.test(out), false);
    continue;
  }
  eq(`不误伤：${name}`, out, `<p>${md}</p>`);
}
eq(
  '算式段里的 w_1 / b_2 该切的还是切了（证明不是靠整段跳过实现的不误伤）',
  html('score = knowledge_search(q) × w_1 + b_2'),
  '<p>score = knowledge_search(q) × w<sub>1</sub> + b<sub>2</sub></p>',
);
eq(
  '单字母基座 + .扩展名 ⇒ 判成文件名，不切',
  html('总损耗 = a_py.py + b_md.md × 2 = 3'),
  '<p>总损耗 = a_py.py + b_md.md × 2 = 3</p>',
);
eq(
  '花括号写法优先，且简写不会在已转出的下标里再套一层',
  html('P_{IT} = P_IT × 2 + 1'),
  '<p>P<sub>IT</sub> = P<sub>IT</sub> × 2 + 1</p>',
);
eq(
  '反引号里的简写**不动**：那是代码字面量，改了就是改数据',
  html('`P_IT = N × P_cam` 在 python 里是变量名'),
  '<p><code>P_IT = N × P_cam</code> 在 python 里是变量名</p>',
);

/* ==================== 5. 代码节点里的公式 ==================== */

eq(
  '行内反引号里的公式 → 换出代码皮肤（span.mx-from-code），上下标这才出得来',
  html('公式 `score(q,d) = Σ_{t∈q} tf(t,d)` 的含义'),
  `<p>公式 <span.mx-from-code>score(q,d) = Σ<sub>t∈q</sub> tf(t,d)</span> 的含义</p>`,
);
eq(
  '无语言标记的围栏 → 公式区 div（带 ast-math，可横向滚）',
  html('```\nscore(q,d) = Σ_{t∈q} tf(t,d)\n```'),
  '<div.ast-math.mx-from-code>score(q,d) = Σ<sub>t∈q</sub> tf(t,d)</div>',
);
eq(
  '```text 这类「其实不是代码」的围栏也认',
  html('```text\nQ = m \\cdot c_p \\cdot ΔT_{max}\n```'),
  '<div.ast-math.mx-from-code>Q = m \\cdot c<sub>p</sub> \\cdot ΔT<sub>max</sub></div>',
);
eq(
  '声明了 python 的围栏是真代码，里面再像公式也不动（改了就是改数据）',
  html('```python\ndata = {"x_{1}": 1}\n```'),
  '<pre><code.language-python>data = {"x_{1}": 1}\n</code></pre>',
);
eq(
  '多行围栏：\frac 照切，但除法只在单行里猜',
  html('```\nQ_in = \\frac{m \\cdot c_p}{\\eta}\nP = Q_in / COP\n```'),
  `<div.ast-math.mx-from-code>Q<sub>in</sub> = ${FRAC_OUT(['m \\cdot c<sub>p</sub>', '\\eta'])}\nP = Q<sub>in</sub> / COP</div>`,
);

/* ==================== 6. 安全：模型输出的 HTML 只能到 raw ==================== */

eq(
  '下标里的 <script> 不产生元素',
  html('x_{<script>alert(1)</script>}'),
  '<p>x_{RAW(<script>)alert(1)RAW(</script>)}</p>',
);
eq(
  '普通文本里的 <b> 同样只到 raw，不进 DOM',
  html('前 <b>中</b> 后'),
  '<p>前 RAW(<b>)中RAW(</b>) 后</p>',
);
eq(
  '\\frac 参数里塞 <img onerror> → 整条不切，也不冒元素',
  html('\\frac{<img src=x onerror=alert(1)>}{η}'),
  '<p>\\frac{RAW(<img src=x onerror=alert(1)>)}{η}</p>',
);
eq(
  '行内代码里的 <script> 变成 span 的文本子节点，不是元素',
  html('`<script>x_{1}</script>`'),
  '<p><span.mx-from-code><script>x<sub>1</sub></script></span></p>',
);
/* 这一条是兜底：上面各条只看单个用例，这条横扫所有输入冒出的标签名。
   公式排布新登记的只有 span / div 两个，别的都是意外。 */
eq(
  '公式 soup 里只出现登记过的标签名',
  tagNames(
    [
      'score(q,d) = Σ_{<script>alert(1)</script>} tf(t,d) / norm(d)',
      '',
      '\\frac{<img src=x onerror=1>}{<iframe name=x>}',
      '',
      '`a_{<svg onload=1>} / b`',
      '',
      '- x^{<body>} = \\frac{<style>} {<form>}',
    ].join('\n'),
  ).filter((t) => !['p', 'sub', 'sup', 'span', 'div', 'ul', 'li'].includes(t)),
  [],
);

console.log(`\nanswerMath：${pass} 项通过`);
if (fails.length) {
  console.error(`\n✗ ${fails.length} 项失败：\n` + fails.join('\n\n'));
  process.exitCode = 1;
}
