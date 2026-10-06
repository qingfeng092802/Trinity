/* 打印「markdown → 简化 HTML」的实测串，供 answerMath.test.cjs 的期望值抄用。
   期望值必须是跑出来的，不是猜的。
   用法：npx esbuild src/utils/answerMath.ts --bundle --format=cjs --outfile=tools/uicheck/answerMath.cjs
        node tools/uicheck/mathdump.cjs */
const { remarkMathText } = require('./answerMath.cjs');
const { unified } = require('unified');
const remarkParse = require('remark-parse').default;
const remarkGfm = require('remark-gfm').default;
const remarkRehype = require('remark-rehype').default;

function ser(n) {
  if (n.type === 'root') return (n.children || []).map(ser).join('');
  if (n.type === 'text') return n.value;
  if (n.type === 'raw') return `RAW(${n.value})`;
  const cls = n.properties && n.properties.className ? '.' + [].concat(n.properties.className).join('.') : '';
  return `<${n.tagName}${cls}>${(n.children || []).map(ser).join('')}</${n.tagName}>`;
}

const CASES = [
  ['A 段落上下标', 'score(q,d) = Σ_{t∈q} tf(t,d) · idf(t)'],
  ['B 无上标注', 'x ^ {2} + y ^ {2} = r ^ {2}'],
  ['C 围栏里的公式', '```\nscore(q,d) = Σ_{t∈q} tf(t,d) / norm(d)\n```'],
  ['C2 带 text 标记的围栏', '```text\nCOP = Q_cool / W_comp\n```'],
  ['C3 python 围栏不动', '```python\ndata = {"x_{1}": 1, "sum": Σ}\nprint(data)\n```'],
  ['D 行内代码里的公式', '公式 `score(q,d) = Σ_{t∈q} tf(t,d)` 的含义'],
  ['E 裸 frac', 'nDCG@k = \\frac{DCG@k}{IDCG@k}'],
  ['E2 frac 里带下标', 'η_th = \\frac{W_{net}}{Q_{in}}'],
  ['F 算式段单斜杠', 'P_total = 1024 × 12 / 0.92'],
  ['F2 斜杠后带句号', 'COP = Q_cool / W_comp。'],
  ['F3 连续除不猜', 'η = a / b / c'],
  ['F4 不带空格的除不猜', 'η = Q/W_in'],
  ['F5 散文里的斜杠', '配置说明：路径 /data/kb 下有两个文件'],
  ['G snake_case 不被咬', '用 knowledge_search 与 code_exec 两个工具'],
  ['H 列表项', '- nDCG@5 = DCG_{5} / IDCG_{5}\n- 第二条'],
  ['I 表格单元', '指标如下：\n\n| 指标 | 值 |\n| - | - |\n| nDCG | DCG_{5} / IDCG_{5} |\n'],
  ['I2 没空行的伪表格', '| 指标 | 值 |\n| - | - |\n| nDCG | DCG_{5} / IDCG_{5} |'],
  ['J 嵌套花括号不动', 'a _{b{c}d} e'],
  ['K 多行围栏', '```\nQ_in = \\frac{m \\cdot c_p \\cdot \\Delta T}{\\eta}\nP = Q_in / COP\n```'],
  ['L XSS 探针', 'x_{<script>alert(1)</script>}'],
  ['M frac 里塞 img', '\\frac{<img src=x onerror=alert(1)>}{η}'],
  ['N 代码里的 script', '`<script>x_{1}</script>`'],
  ['O 等号左边不切', 'a / b = c'],
  ['P 分母带右括号', 'score(q,d) = Σ_{t∈q} tf(t,d) / norm(d)'],
  [
    'Q fixture 的 nDCG 长行',
    'nDCG@k = DCG@k / IDCG@k ，其中 DCG@k = Σ_{i=1..k} (2^{rel_i} - 1) / log2(i + 1) ，IDCG@k = Σ_{i=1..k} (2^{rel_i^ast} - 1) / log2(i + 1) ，rel^ast 为按增益降序重排后的相关性分级',
  ],
  ['R 行内代码带下标', '行内形式 `COP = Q_{cool} / W_{comp}` 与之一致。'],
  /* ---- 他 2026-09-24 截图里的真实行：模型没写花括号的简写下标 ---- */
  ['S1 裸简写主式', 'P_IT = N × P_cam ÷ η_PoE + P_sw + P_NVR + P_net + P_aux [W]'],
  ['S2 裸简写带中文说明', 'PoE链路段：P_PoE_chain = N × P_cam ÷ η_PoE （摄像头受电功率折算为交换机输入端取电）'],
  ['S3 市电侧', 'P_mains = P_IT ÷ η_UPS [W]'],
  ['S4 基础设施段', 'P_infra = P_sw + P_NVR + P_net + P_aux'],
  /* ---- 误伤探针：这些一个都不许变 ---- */
  ['F1 工具名', '已完成 4 个子步骤： 1. 用 knowledge_search 检索知识库获得依据条文。'],
  ['F2 文件名', '配置文件 my_file.py 与 read_config.js 都在 scripts 下。'],
  ['F3 全大写蛇形', '常量 FOO_BAR 与 MAX_LOG_EVENTS 决定封顶行数。'],
  ['F4 散文里的等号', '配置说明：超时 = 30s，重试 = 2 次。'],
  ['F5 代码里的简写', '`P_IT = N × P_cam` 在 python 里是变量名'],
  ['F6 算式段里混工具名', 'score = knowledge_search(q) × w_1 + b_2'],
];

for (const [name, md] of CASES) {
  const p = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMathText)
    .use(remarkRehype, { allowDangerousHtml: true });
  const tree = p.runSync(p.parse(md));
  console.log(`\n### ${name}\n   in   ${JSON.stringify(md)}\n   out  ${JSON.stringify(ser(tree))}`);
}
