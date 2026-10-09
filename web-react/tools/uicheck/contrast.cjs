/* WCAG 2.1 相对亮度与对比度实算。
 *
 * ⚠️ 色值不在这里硬编码 —— 直接解析 src/theme.ts 的 PALETTE 与 LOG_SURFACE，
 * 这样改配色后跑一次就能拿到真数字，不会出现文档与实际脱节。
 *
 * 日志层（LOG_SURFACE）**主题无关**，所以它的用例会各自在 light / dark 两趟里
 * 跑一遍——两趟数字必须一样，不一样就说明有人把节点色改回了 `--node-*`
 * （那组是为白底调的，压在终端深底上只有 2.8~3.8:1）。
 *
 * 用法：node tools/uicheck/contrast.cjs
 */
const fs = require('fs');
const path = require('path');

const THEME = fs.readFileSync(path.resolve(__dirname, '../../src/theme.ts'), 'utf8');

/* ⚠️ 必须限定在 PALETTE 内搜索：ANTD_THEME 里也有 `light: {` / `dark: {`，
   不加这层定位会静默取到 AntD token，亮色组算出暗色数字且看不出来。 */
const P_START = THEME.indexOf('export const PALETTE');
const P_END = THEME.indexOf('\n};', P_START);
if (P_START < 0 || P_END < 0) throw new Error('PALETTE block not found');
const PALETTE_SRC = THEME.slice(P_START, P_END);

/** 从 PALETTE 里抠出某个 mode 的 '--key': 'value' 字典 */
function grabPalette(mode) {
  const start = PALETTE_SRC.indexOf(`  ${mode}: {`);
  if (start < 0) throw new Error(`mode block not found: ${mode}`);
  const braceEnd = PALETTE_SRC.indexOf('\n  },', start);
  const block = PALETTE_SRC.slice(start, braceEnd);
  const out = {};
  const re = /'([^']+)':\s*'([^']+)'/g;
  let m;
  while ((m = re.exec(block))) out[m[1]] = m[2];
  return out;
}

/** 终端层：TERM_SURFACE 是主题无关的一档，两趟共用。 */
function grabTermSurface() {
  const start = THEME.indexOf('const TERM_SURFACE');
  if (start < 0) throw new Error('TERM_SURFACE block not found');
  const braceEnd = THEME.indexOf('\n} as const;', start);
  const block = THEME.slice(start, braceEnd);
  const out = {};
  const re = /'([^']+)':\s*'([^']+)'/g;
  let m;
  while ((m = re.exec(block))) out[m[1]] = m[2];
  return out;
}

const LIGHT = grabPalette('light');
const DARK = grabPalette('dark');
const LOG = grabTermSurface();

/** LOG_LEVEL_META 的 onDark 档也解析进来：级别列的字色压在终端底上同样要过 AA。
 *  现在 onDark 存的是 `var(--term-x)` 引用（终端只有一张色表，不再养第二套 hex），
 *  所以这里要先把引用解成实色 —— 解不出来就抛，静默少测几档比测错更糟。 */
(function grabLevels() {
  const start = THEME.indexOf('export const LOG_LEVEL_META');
  if (start < 0) throw new Error('LOG_LEVEL_META block not found');
  const block = THEME.slice(start, THEME.indexOf('};', start));
  const re = /(\w+):\s*\{[^}]*?onDark:\s*'([^']+)'/g;
  let m;
  let n = 0;
  while ((m = re.exec(block))) {
    const ref = /^var\((--[\w-]+)\)$/.exec(m[2]);
    const value = ref ? LOG[ref[1]] : m[2];
    if (!value) throw new Error(`onDark 引用解不开：${m[1]} → ${m[2]}`);
    LOG[`--lvl-${m[1]}`] = value;
    n += 1;
  }
  if (n !== 4) throw new Error(`LOG_LEVEL_META 只解析到 ${n} 档 onDark`);
})();

const lin = (c) => {
  c /= 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
};

function L(hex) {
  const h = hex.replace('#', '');
  if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null; // rgba() 之类跳过
  return (
    0.2126 * lin(parseInt(h.slice(0, 2), 16)) +
    0.7152 * lin(parseInt(h.slice(2, 4), 16)) +
    0.0722 * lin(parseInt(h.slice(4, 6), 16))
  );
}

const HEX6 = /^#([0-9a-f]{6})$/i;
const RGBA = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/;

/** 把 token 值解析成 [r,g,b] 或 [r,g,b,a]；认不出来返回 null。 */
function toRgb(v) {
  if (HEX6.test(v)) {
    const h = v.slice(1);
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  }
  const m = RGBA.exec(v);
  return m ? [+m[1], +m[2], +m[3], +m[4]] : null;
}

/** 半透明 token 先按「叠在指定底上」压成实色再算。
 *
 * 深色主题的 --primary-100 / --*-soft 全是 rgba，直接跳过等于**没检查**，
 * 而那些正是新加的高亮行底色。前景 token 目前是纯色，走同一条路径不影响结果。
 * base 默认卡片底；终端层的 rgba 必须显式传 --term-bg，否则合成基准就错了。
 */
function solidify(dict, value, base) {
  const rgb = toRgb(value);
  if (!rgb || rgb.length === 3) return value;
  const b = toRgb(base ?? dict['--bg-surface']);
  if (!b) return null;
  const a = rgb[3];
  const mix = rgb.slice(0, 3).map((c, i) => Math.round(c * a + b[i] * (1 - a)));
  return `#${mix.map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

const cr = (bg, fg) => {
  const a = L(bg);
  const b = L(fg);
  if (a === null || b === null) return null;
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
};

/** [底色 token, 前景 token, 说明, 是否必须 ≥4.5:1] */
const CASES = [
  ['--bg-surface', '--text-1', 'text-1 / 卡片白底', true],
  ['--bg-surface', '--text-2', 'text-2 / 卡片白底', true],
  ['--bg-surface', '--text-3', 'text-3 / 卡片白底', true],
  ['--bg-surface', '--primary', 'primary / 卡片白底', true],
  ['--bg-surface', '--primary-500', 'primary-500 图形（不承载文字）', false],
  ['--bg-surface', '--success-fg', 'success-fg / 白底', true],
  ['--bg-surface', '--warning-fg', 'warning-fg / 白底', true],
  ['--bg-surface', '--danger-fg', 'danger-fg / 白底', true],
  ['--bg-surface', '--info-fg', 'info-fg / 白底', true],
  ['--bg-surface', '--success', 'success fill 圆点（不承载文字）', false],
  ['--bg-surface', '--node-planner', 'planner fg / 白底', true],
  ['--bg-surface', '--node-executor', 'executor fg / 白底', true],
  ['--bg-surface', '--node-executor-fill', 'executor fill 圆点（不承载文字）', false],
  ['--bg-surface', '--node-reviewer', 'reviewer fg / 白底', true],
  ['--bg-app', '--text-3', 'text-3 / 应用底色', true],
  ['--bg-app', '--text-2', 'text-2 / 应用底色', true],
  ['--bg-surface-2', '--text-3', 'text-3 / 卡片次级底', true],
  ['--bg-sunken', '--text-2', 'text-2 / 下沉底色', true],
  ['--bg-sunken', '--text-3', 'text-3 / 下沉底色', true],
  ['--bg-surface', '--nav-fg', '图标栏常态字色', true],
  ['--primary-soft', '--primary', '图标栏选中态（底 / 图标）', true],
  ['--primary-100', '--text-2', '胜出行里的普通单元格', true],
  ['--primary-100', '--primary-soft-fg', '胜出行里的权重 chip', true],
  ['--warning-soft', '--warning-fg', '降级态胶囊', true],
  ['--danger-soft', '--danger-fg', '离线态胶囊', true],
  /* 成本归因面板的计费档位（C1–C7）。胶囊文字压在胶囊底色上、档位文字也直接压在卡片白底上
     （明细表「档位」那一列没有底色），所以**两表面各量一次** —— 只量白底会漏掉胶囊那半。 */
  ['--cost-peak-soft', '--cost-peak', '高峰档胶囊（成本面板）', true],
  ['--cost-offpeak-soft', '--cost-offpeak', '低谷档胶囊（成本面板）', true],
  ['--bg-surface', '--cost-peak', '高峰档文字 / 卡片白底', true],
  ['--bg-surface', '--cost-offpeak', '低谷档文字 / 卡片白底', true],
  ['--bg-sunken', '--success-fg', 'JSON 树字符串', true],
  ['--bg-sunken', '--info-fg', 'JSON 树数字', true],
  ['--bg-sunken', '--accent', 'JSON 树布尔', true],
  /* 答案富文本层（react-markdown）：底色走 --code-bg，两主题各按自己的档 */
  ['--code-bg', '--text-1', '答案表头 / 行内代码 / 公式', true],
  ['--bg-surface-2', '--text-2', '答案斑马行正文', true],
  ['--bg-hover', '--text-2', '答案悬停行正文', true],
  ['--primary-soft', '--text-1', '摘要条结论摘录', true],
  ['--primary-soft', '--text-2', '摘要条硬指标行', true],
  ['--primary-soft', '--primary-soft-fg', '摘要条「结论」标签', true],
  ['--bg-surface', '--accent', '答案删除线（旧口径）', false],
  ['--bg-surface-2', '--text-1', '工具卡意图标题', true],
  /* 工具卡异常出参块：底色是 --danger-soft 压在卡片次级底（.tool-card 用 --bg-surface-2）
     上合成的，所以基准必须显式传 --bg-surface-2，传默认值等于没测这块。 */
  ['--danger-soft', '--danger-fg', '工具卡异常出参正文', true, '--bg-surface-2'],
  ['--warning-soft', '--warning-fg', '工具卡「执行异常」徽标', true, '--bg-surface-2'],
  /* 源码入参块（pre.code-src）沿用上面 JSON 树那条 ramp：关键字=--accent、串=--success-fg、
     数字=--info-fg、注释=--text-3，底色同为 --bg-sunken —— 那四条已判定，这里只补按钮。 */
  ['--bg-surface-2', '--primary', '入参块「展开全文」链接', true],
  ['--bg-surface-2', '--text-2', '源码正文（未上色那段）', true],
  /* 知识库页（Z 趟那页）的状态徽标。四档里只有 success 这一对是**第一次落在真实位置**上：
     任务状态徽标走的是 STATUS_META 的另外几档，从没把绿字压在绿底上量过。
     文档表那些行不铺自己的底色，底就是卡片白底 ⇒ 基准不传是对的，**这条不是猜的**：
     `theme.ts:546` 把 AntD 的 `colorBgContainer` 直接指派成 `c['--bg-surface']`（两档各一次），
     而 `.ant-table` 的底色就取这个 token ⇒ 表格行、徽标、分段条标签压的都是 `--bg-surface`。
     改坏的症状：以后谁给 `.ant-table-row` 铺一层自己的底色（斑马纹、按状态染色），
     这几条的基准就不再成立 —— 那时必须像工具卡那样显式传第五个参数。 */
  ['--success-soft', '--success-fg', '知识库「已索引」徽标', true],
  ['--primary', '--primary-300', '分段条 done↔active 色差（图形，不判定）', false],
  /* F-6 / F-7（顶栏那一族）。⚠️ 基准必须显式传：顶栏底是半透明的 `--topbar-bg`，
     默认基准 `--bg-surface`（卡片白底）压出来的不是用户实际看到的那层。
     已知近似：solidify 合成时只取基准的 RGB、忽略基准自己的 alpha，
     所以这里合成出的顶栏底与真实值差 ≤2/255（暗色算下来 #101219 vs 真实 #0F1118），
     对这个量级的判定（4.5 上下差 3 倍）没有影响。 */
  ['--topbar-bg', '--text-3', '面包屑分隔符（F-6 改后）', true, '--bg-app'],
  ['--warning-soft', '--text-2', '降级胶囊里的数据源 code（F-7 改后）', true, '--topbar-bg'],
  /* 下面两条不判定，只把"改之前那个组合"留在账上：F-7 那行小字原来吃 --text-3。 */
  ['--warning-soft', '--text-3', 'F-7 改之前的组合（不判定，留证）', false, '--topbar-bg'],

  ['--bg-surface', '--text-1', 'dark text-1', true],
  ['--bg-surface', '--text-2', 'dark text-2', true],
  ['--bg-surface', '--text-3', 'dark text-3', true],
  ['--bg-surface', '--primary', 'dark primary', true],
  ['--bg-app', '--text-3', 'dark text-3 / 应用底色', true],
  ['--bg-app', '--text-2', 'dark text-2 / 应用底色', true],
  ['--bg-surface-2', '--text-3', 'dark text-3 / 卡片次级底', true],
  ['--bg-sunken', '--text-3', 'dark text-3 / 下沉底色', true],
  ['--bg-surface', '--nav-fg', 'dark 图标栏常态字色', true],
  ['--primary-soft', '--primary', 'dark 图标栏选中态（底 / 图标）', true],
  ['--primary-100', '--text-2', 'dark 胜出行里的普通单元格', true],
  ['--primary-100', '--primary-soft-fg', 'dark 胜出行里的权重 chip', true],
  ['--warning-soft', '--warning-fg', 'dark 降级态胶囊', true],
  ['--danger-soft', '--danger-fg', 'dark 离线态胶囊', true],
  /* 成本面板的计费档位（暗色档）。半透明底要先与 `--bg-surface` 合成再量，
     所以这里传第五个参数 base —— 合成后是「实际看到的那层底」，不是 rgba 字面值。 */
  ['--cost-peak-soft', '--cost-peak', 'dark 高峰档胶囊（成本面板）', true, '--bg-surface'],
  ['--cost-offpeak-soft', '--cost-offpeak', 'dark 低谷档胶囊（成本面板）', true, '--bg-surface'],
  ['--bg-surface', '--cost-peak', 'dark 高峰档文字 / 卡片底', true],
  ['--bg-surface', '--cost-offpeak', 'dark 低谷档文字 / 卡片底', true],
  ['--bg-sunken', '--success-fg', 'dark JSON 树字符串', true],
  ['--bg-sunken', '--info-fg', 'dark JSON 树数字', true],
  ['--bg-sunken', '--accent', 'dark JSON 树布尔', true],
  ['--code-bg', '--text-1', 'dark 答案表头 / 行内代码 / 公式', true],
  ['--bg-surface-2', '--text-2', 'dark 答案正文（斑马纹行 / 引用块）', true],
  ['--bg-hover', '--text-2', 'dark 答案表格 hover 行正文', true],
  ['--primary-soft', '--text-1', 'dark 摘要条结论摘录', true],
  ['--primary-soft', '--text-2', 'dark 摘要条硬指标行', true],
  ['--primary-soft', '--primary-soft-fg', 'dark 摘要条「结论」标签', true],
  ['--bg-surface-2', '--text-1', 'dark 工具卡意图标题', true],
  ['--danger-soft', '--danger-fg', 'dark 工具卡异常出参正文', true, '--bg-surface-2'],
  ['--warning-soft', '--warning-fg', 'dark 工具卡「执行异常」徽标', true, '--bg-surface-2'],
  ['--bg-surface-2', '--primary', 'dark 入参块「展开全文」链接', true],
  ['--bg-surface-2', '--text-2', 'dark 源码正文（未上色那段）', true],
  /* 知识库页（Z 趟那页）—— 暗色三档：
     ① 「已索引」徽标：`--success-soft` 在暗色是 rgba，缺省基准 --bg-surface 正是
        表格行的实际底，所以不传第五个参数就是对的；
     ② 失败原因那一行（.doc-error）与行内动作失败条的正文：暗色那一档以前只在
        --bg-sunken / --danger-soft 上量过，卡片底这一档是新增的。 */
  ['--success-soft', '--success-fg', 'dark 知识库「已索引」徽标', true],
  ['--bg-surface', '--danger-fg', 'dark 知识库失败原因那一行', true],
  /* 亮色那侧第 133 行早就钉过 (白底, warning-fg)，暗色一直是缺的 —— 缺的那一条正好是
     知识库页用得最多的那句提醒色：`.up-notice`（"后面 N 份没加入队列"）与 `.up-warn`
     （覆盖重建的"旧索引已清除"）都直接压在卡片底上，没有软底垫着。 */
  ['--bg-surface', '--warning-fg', 'dark 知识库批量提示 / 受理 warning', true],
  /* 分段条的"已走完 / 正在走"两档挨在一起，靠的是色差 —— 这一条**不判定**（图形不是文字），
     但要留个数：它量的是"如果 done 直接吃 `--primary-300`"会剩下多少差。
     暗色那个数就是为什么 done 最后走的是透明度而不是这一档（见 index.css §10.7 的注释）。 */
  ['--primary', '--primary-300', 'dark 分段条 done↔active 色差（图形，不判定）', false],
  /* F-6 / F-7 的暗色档：底是 `--topbar-bg`（暗色下更暗的一层），基准同样必须显式给。
     F-7 报的就是这一档（4.32:1 的 11px 小字），亮色那边其实也只勉强过。 */
  ['--topbar-bg', '--text-3', 'dark 面包屑分隔符（F-6 改后）', true, '--bg-app'],
  ['--warning-soft', '--text-2', 'dark 降级胶囊里的数据源 code（F-7 改后）', true, '--topbar-bg'],
  ['--warning-soft', '--text-3', 'dark F-7 改之前的组合（不判定，留证）', false, '--topbar-bg'],

  /* ---- 终端层（TERM_SURFACE，主题无关）：两趟都跑，数字必须一致 ----
     第 5 项是半透明底色的合成基准 token，缺省用 --bg-surface。
     ⚠️ 心跳行那三条必须单独量：--term-live-bg 那层薄底会把上面的所有字都吃掉
     半档对比 —— 参考稿给的 #8b98a5 在空底上 5.11:1（过），压到心跳底上只剩
     4.46:1（不过），所以弱档最终取的是 #94a3b8。 */
  ['--term-bg', '--term-text', '终端 日志正文', true],
  ['--term-bg', '--term-seq', '终端 序号 / DEBUG 正文 / 页脚弱字', true],
  ['--term-surface', '--term-seq', '终端 工具条与页脚弱字', true],
  ['--term-bg', '--lvl-info', '终端 级别列 INFO', true],
  ['--term-bg', '--lvl-warn', '终端 级别列 WARN', true],
  ['--term-bg', '--lvl-error', '终端 级别列 ERROR', true],
  ['--term-bg', '--lvl-debug', '终端 级别列 DEBUG', true],
  ['--term-bg', '--term-node-planner', '终端 Planner 节点色', true],
  ['--term-bg', '--term-node-executor', '终端 Executor 节点色', true],
  ['--term-bg', '--term-node-reviewer', '终端 Reviewer 节点色', true],
  ['--term-bg', '--term-node-system', '终端 System 节点色', true],
  ['--term-live-bg', '--term-seq', '终端 心跳行序号', true, '--term-bg'],
  ['--term-live-bg', '--term-text', '终端 心跳行正文', true, '--term-bg'],
  ['--term-live-bg', '--lvl-warn', '终端 心跳行 WARN', true, '--term-bg'],
  ['--term-hit-bg', '--term-hit-fg', '终端 命中词', true, '--term-bg'],
  /* 图形件：不承载文字，只记录数字（描边弱是有意的，见 theme.ts 注释） */
  ['--term-bg', '--term-border', '终端 描边（图形，不判定）', false],
  ['--term-bg', '--term-rule', '终端 行间细线（图形，不判定）', false, '--term-bg'],
  ['--term-bg', '--term-info', '终端 spinner（图形，复用 INFO 档）', false],
  ['--bg-surface', '--term-border', '终端描边 vs 页面卡片底（面板存在感）', false],
  ['--term-bg', '--term-border', '终端描边 vs 终端底（刻意弱，1.2:1 档）', false],
  /* 旧口径存档：这几档是为白底调的，压在终端上必然不达标 —— 判定关掉，
     但把数字留在报表里，防止有人「顺手」把 LogStream 改回 nodeColorVar()。 */
  ['--term-bg', '--node-planner', '终端 ← 旧口径 planner（不判定）', false],
  ['--term-bg', '--node-executor', '终端 ← 旧口径 executor（不判定）', false],
  ['--term-bg', '--node-reviewer', '终端 ← 旧口径 reviewer（不判定）', false],
];

let pass = 0;
let fail = 0;
const rows = [];

for (const mode of ['light', 'dark']) {
  /* LOG_SURFACE 主题无关，但必须能被 PALETTE 覆盖不到 —— 先展开再合并当次主题 */
  const dict = { ...LOG, ...(mode === 'light' ? LIGHT : DARK) };
  for (const [bgKey, fgKey, note, required, baseKey] of CASES) {
    const isDarkCase = /^dark /.test(note);
    const isTermCase = /^终端 /.test(note);
    if (!isTermCase) {
      if (mode === 'light' && isDarkCase) continue;
      if (mode === 'dark' && !isDarkCase) continue;
    }

    const bgRaw = dict[bgKey];
    const fgRaw = dict[fgKey];
    if (!bgRaw || !fgRaw) {
      rows.push([mode, note, `${bgKey}/${fgKey}`, 'token 缺失']);
      fail += 1;
      continue;
    }
    const base = baseKey ? dict[baseKey] : dict['--bg-surface'];
    const bg = solidify(dict, bgRaw, base);
    const fg = solidify(dict, fgRaw, base);
    const ratio = cr(bg, fg);
    if (ratio === null) {
      rows.push([mode, note, `${bg}/${fg}`, '认不出的色值格式，跳过']);
      continue;
    }
    const ok = ratio >= 4.5;
    if (required) (ok ? (pass += 1) : (fail += 1));
    rows.push([
      mode,
      note,
      `${bg} → ${fg}`,
      `${ratio.toFixed(2)}:1 ${ok ? 'AA' : required ? '✗ 不达标' : '(不判定：图形或旧档)'}`,
    ]);
  }
}

console.log('\n' + 'mode'.padEnd(7) + '用例'.padEnd(36) + '色值'.padEnd(22) + '结果');
console.log('-'.repeat(100));
for (const r of rows) {
  console.log(String(r[0]).padEnd(7) + String(r[1]).padEnd(36) + String(r[2]).padEnd(22) + r[3]);
}
console.log('-'.repeat(100));
console.log(`必须达标项：${pass} 通过 / ${fail} 未通过`);
if (fail > 0) process.exitCode = 1;
