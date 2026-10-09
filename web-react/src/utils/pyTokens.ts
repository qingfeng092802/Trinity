/* Python 源码的极简分词（工具入参展示用）。

 为什么不引 highlight.js / Prism：只要四类色（关键字 / 字符串 / 注释 / 数字），
 引一条依赖是给 8 KB 的 gzip 买一整套语言包。这里 60 行手写正则就够，
 且**只返回文本片段**，由 React 建 span —— 全程不碰 innerHTML，源码里写
 `<script>` 也只会当普通字符渲染。

 口径：认不准就不染。识别不出来的全部落 'plain'，宁可少上色也不要
 把 `re.match` 里的 match 染成关键字（所以 match/case 软关键字刻意不在表里）。 */

export type PyToken = 'kw' | 'str' | 'com' | 'num' | 'plain';

export interface PySegment {
  text: string;
  cls: PyToken;
}

/** Python 3.13 的硬关键字。软关键字 match / case / _, 类型标记都不收。 */
const KEYWORDS = new Set([
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break',
  'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally',
  'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal',
  'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
]);

/** 顺序有意义：注释 > 三引号串 > 单行串（带 r/f/b/u 前缀）> 数字 > 标识符。
 *  每条都是线性正则，没有嵌套量词，不存在回溯爆炸。 */
const RULES: Array<[RegExp, PyToken]> = [
  [/#.*(?=\n|$)/y, 'com'],
  [/("""|''')(?:[\s\S]*?\1)?/y, 'str'],
  [/[rRbBuUfF]{0,2}(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/y, 'str'],
  [/0[xXbBoO][0-9a-fA-F_]+|[0-9](?:_?[0-9])*(?:\.[0-9](?:_?[0-9])*)?(?:[eE][-+]?[0-9]+)?[jJ]?|\.[0-9](?:_?[0-9])*[jJ]?/y, 'num'],
  [/[A-Za-z_]\w*/y, 'kw'],
];

function classify(word: string): PyToken {
  return KEYWORDS.has(word) ? 'kw' : 'plain';
}

function push(out: PySegment[], text: string, cls: PyToken): void {
  const last = out[out.length - 1];
  if (last && last.cls === cls) last.text += text;
  else out.push({ text, cls });
}

/** 源码 → 带类别的文本片段。空串返回空数组。 */
export function tokenizePython(src: string): PySegment[] {
  const out: PySegment[] = [];
  if (!src) return out;

  let i = 0;
  let plain = '';
  while (i < src.length) {
    let hit = false;
    for (const [re, cls] of RULES) {
      re.lastIndex = i;
      const m = re.exec(src);
      if (!m || m[0] === '') continue;
      if (plain) {
        push(out, plain, 'plain');
        plain = '';
      }
      push(out, m[0], cls === 'kw' ? classify(m[0]) : cls);
      i += m[0].length;
      hit = true;
      break;
    }
    if (!hit) {
      plain += src[i];
      i += 1;
    }
  }
  if (plain) push(out, plain, 'plain');
  return out;
}

/** 展示用的两个计数：折叠按钮上要说清「展开还有多少」。 */
export function codeSize(code: string): { lines: number; chars: number } {
  return {
    lines: code ? code.split('\n').length : 0,
    chars: code.length,
  };
}
