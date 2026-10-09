/* 裸文本公式的排布层。

 后端答案里的算式是**纯文本**：`score(q,d) = Σ_{t∈q} …`、`P = 1024 × 12 / 0.92`，
 模型还爱把它们塞进 ``` 围栏或行内反引号里「保护」起来。Markdown 不认 `_{}`，
 于是用户看到的是一串像没写完的代码。这一层做四件事，且都**不改写内容**
 （与 AnswerView 的第三条口径一致）：

 1. `_{…}` / `^{…}` → 真正的 `<sub>` / `<sup>`；**没写花括号的简写**（`P_IT`、`η_PoE`、
    `P_PoE_chain`）在"看着就是算式"的段里也认（见 `BARE_SUB` / `formulaish`）。
    简写这条有三门闸防误伤：基座必须是**单个字母**、只在算式形态的段里生效、
    后面紧跟 `.字母`（`.py`）判成文件名。库里 16 条真实答案里裸下划线命中 4 条，
    抓出来的全是 `knowledge_search` / `code_exec` 这类多字母 snake_case ⇒ 基座那条就把它们挡掉了。
 2. `\frac{A}{B}` → 上下结构的分数。
 3. 算式段里**唯一一个**带空格的 `A / B` → 也立成分数；连续除、不带空格的一律不猜
    （猜错的分数比一行斜杠更难读）。
 4. 代码节点里的公式 → 换出代码皮肤，改走公式区（只认无语言标记或 `text`/`math`
    这类「其实不是代码」的围栏；```python 里再像公式也不动）。

 实现全部走 mdast 的 `data.hName` / `hProperties`（见 mdast-util-to-hast 的 applyData）：
 自定义节点类型 + hName ⇒ 输出的就是 sub/sup/span 元素。
 **不做「字符串替换成 HTML 再塞进去」那种预处理器** —— 那需要 rehype-raw 或
 innerHTML，而答案文本是模型（间接是用户文档）产出的，开这条口子就是 XSS 面。
 */

/** `_{…}` / `^{…}`：允许 `^ {2}` 这种带空格的写法（模型真会这么输出），
 *  但刻意不允许嵌套花括号 —— 认不准就当普通文本，宁可不渲染也不猜。 */
const SCRIPT_RE = /([\^_])[ \t]*\{([^{}]*)\}/g;
const SCRIPT_ONE = /[_^][ \t]*\{[^{}]*\}/;
/** 只有算式里才会出现的运算符 */
const MATH_OPS = /[∑Σ∏∫√≈≤≥≠±×÷]/;
/** 汉字 / 假名 / 谚文：总量 + 最长连续串。用码位区间判断而不是写进正则字面量：
 *  这些区间边界在源码里长得很像，用数字比较才不会看错。
 *  0x3040-0x30ff 假名，0x3400-0x9fff 汉字（含扩展 A），0xac00-0xd7af 谚文。
 *
 *  为什么连「最长连续串」也要管：光看占比挡不住「行内形式 `COP = Q_{cool} / W_{comp}`
 *  与之一致。」这种句子 —— 反引号把拉丁字符的密度撑上去了，占比只有 26%，
 *  于是整句话被套进灰盒子等宽不换行，比原样更难读。真算式里的汉字只会是
 *  「其中」「瓦」这种一两字的夹注，成不了三个字的连续串。 */
function cjkStats(s: string): { total: number; maxRun: number } {
  let total = 0;
  let run = 0;
  let maxRun = 0;
  for (const ch of s) {
    const c = ch.codePointAt(0) ?? 0;
    const isCjk =
      (c >= 0x3040 && c <= 0x30ff) || (c >= 0x3400 && c <= 0x9fff) || (c >= 0xac00 && c <= 0xd7af);
    run = isCjk ? run + 1 : 0;
    if (run > maxRun) maxRun = run;
    if (isCjk) total += 1;
  }
  return { total, maxRun };
}

interface AnyNode {
  type: string;
  value?: string;
  lang?: string | null;
  children?: AnyNode[];
  data?: Record<string, unknown>;
}

/** 裸下标 `P_IT` / `η_PoE` / `P_PoE_chain` —— 模型大量不写花括号，直接 `P_IT = N × P_cam`。
 *
 *  这条规则上一轮被我**刻意拒掉**过：库里 16 条真答案里裸下划线命中 4 条，抓出来的全是
 *  `knowledge_search` / `code_exec` 这类 snake_case 工具名。这次能加，靠的是三个约束一起成立：
 *   1. **基座必须是单个字母**（拉丁或希腊）+ 前面不能贴词字符。
 *      `knowledge_search` 的基座是 `…edge`、`my_file.py` 的是 `y`（前面还有 `m`）、
 *      `FOO_BAR` 的基座前面是 `O` ⇒ 全部落不进 `[^\w]` + 单字母这个形状。
 *   2. **只在"这一看就是算式"的段里生效**（见 `formulaish`），散文段一个都不碰。
 *   3. 下标体后面紧跟 `.字母`（`.py` `.md` `.txt`）判成文件名，不切。
 *  体允许带下划线的链（`P_PoE_chain` ⇒ 整体当一个标签），因为拆成
 *  `P` + `PoE` + `chain` 反而是另一种错。
 *
 *  ⚠️ `(?![A-Za-z0-9_])` 不是多余的：只有后面那个扩展名判据时，`a_py.py` 会让正则**回溯**
 *  成「体 = p」从而切出 `a<sub>p</sub>y.py`（实测踩过）。要求体吃掉整段标识符，
 *  回溯这条路就断了。 */
const BARE_SUB =
  /(^|[^\w])([A-Za-z\u0391-\u03c9])_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)(?![A-Za-z0-9_])(?!\.[A-Za-z])/g;

/** 这一段"看着就是算式"吗？比 `isMathBlock` 松一档 —— 它只管**能不能开裸下标**，
 *  不管要不要套灰盒子。松的原因很具体：他截图里那几条是
 *  `P_PoE_chain = N × P_cam ÷ η_PoE （摄像头受电功率折算为交换机输入端取电）`，
 *  括号里的中文说明会把 `isMathBlock` 的汉字判据打掉，于是这些行一个下标都渲染不出来。
 *  判据：有等号 **且** 至少一个运算符（`× ÷ Σ √ ≈ ±` 或项间的 `+ - * /`）。 */
function formulaish(s: string): boolean {
  if (!s.includes('=')) return false;
  return (
    MATH_OPS.test(s) ||
    /[\w)\]]\s*[+*/\-]\s*[\w(]/.test(s) ||
    /[\w)\]]\s*\/\s*[\w(^]/.test(s)
  );
}

/** 一个纯文本片段 → 「普通文本 + 裸下标」节点序列。基座字母留在前面的文本里。 */
function splitBare(value: string): AnyNode[] {
  const out: AnyNode[] = [];
  let last = 0;
  for (const m of value.matchAll(BARE_SUB)) {
    const at = m.index ?? 0;
    const end = at + m[0].length;
    /* 文本只留到**基座字母**为止：那个 `_` 是下标记号，不是内容，必须吃掉。
       留成 `P_` + <sub>IT</sub> 就是「带下划线的代码变量」—— 正是要治的那个样子。 */
    const keep = at + m[1].length + m[2].length;
    if (keep > last) out.push({ type: 'text', value: value.slice(last, keep) });
    out.push({
      type: 'subscript',
      children: [{ type: 'text', value: m[3] }],
      data: { hName: 'sub' },
    });
    last = end;
  }
  if (last < value.length) out.push({ type: 'text', value: value.slice(last) });
  return out;
}

/** 一个文本节点 → 若干「普通文本 + 上下标」节点。`bare` 才认没花括号的简写。 */
function splitScripts(value: string, bare = false): AnyNode[] {
  const out: AnyNode[] = [];
  let last = 0;
  for (const m of value.matchAll(SCRIPT_RE)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ type: 'text', value: value.slice(last, at) });
    const sub = m[1] === '_';
    out.push({
      type: sub ? 'subscript' : 'superscript',
      // 花括号里的内容**不再递归**：`^{rel_i}` 里的下划线是作者写的字面量，
      // 再套一层 <sub> 会变成 sup 里嵌 sub，读起来像排版事故。
      children: [{ type: 'text', value: m[2] }],
      data: { hName: sub ? 'sub' : 'sup' },
    });
    last = at + m[0].length;
  }
  if (last < value.length) out.push({ type: 'text', value: value.slice(last) });
  return bare ? out.flatMap((n) => (n.type === 'text' ? splitBare(n.value ?? '') : [n])) : out;
}

/** `\frac{A}{B}`：两段各允许**一层**花括号（`W_{net}` 这种带下标的必须认得出来），
 *  再深就不认 —— 认不准就当普通文本。 */
const ARG = String.raw`(?:[^{}]|\{[^{}]*\})*`;
const FRAC_SRC = String.raw`\\frac[ \t]*\{(${ARG})\}[ \t]*\{(${ARG})\}`;
const FRAC = new RegExp(FRAC_SRC);
const FRAC_G = new RegExp(FRAC_SRC, 'g');
/** 模型爱把算式塞进行内代码或 ``` 围栏里「保护」起来 —— 那里面也是公式，
 *  但 Markdown 会当代码渲染，于是上下标永远出不来。判定要更严：必须带公式特征。 */
const CODE_MATH = /(?:[_^][ \t]*\{|\\frac|[\u03a3\u2211\u220f\u222b])/;
/** 声明了这些「语言」的围栏其实还是散文/公式，不当代码放过。
 *  反过来 ```python / ```json 里再像公式也是代码 —— 那里面的 `x_{1}` 是字典键，改了就是改数据。 */
const PROSE_LANG = /^(?:text|txt|plain|plaintext|markdown|md|math|formula|equation|latex|tex)$/i;
/** 分数分母尾巴上的句读：`P = U × I / η。` 里那个句号不该画进分母下面。
 *  ⚠️ 不含括号与方括号 —— `… / norm(d)` 的右括号属于分母本身，剥掉它会把算式切断
 *  （实测踩过：`norm(d)` 变成分母 `norm(d` + 外面一个孤立右括号）。 */
const TRAILING_PUNCT = /[.,;:!?、。，；：！？]+$/;
/** 汉字 / 假名 / 谚文 / CJK 标点 / 全角形式。出现在分子分母里就说明斜杠右边接的是散文。
 *  ⚠️ 不含 × ÷ √ ∑ Σ ∈ ≈ ± 这些数学符号所在的拉丁扩展/希腊/数学运算区，别照抄 cjkCount 之外再扩大。 */
const PROSE_EDGE = /[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af\uff00-\uffef]/;
/** 未转义的表格行（Markdown 里以 `|` 开头的行）。这种串里切「A / B」一定会切出
 *  「分子是一整张表」的笑话，所以除法只在**不是表格行**的段落里做。
 *  真表格的单元格文本里没有 `|`，不受这条影响。 */
const TABLE_ROW = /(?:^|\n)[ \t]*\|/;

function fracNode(num: string, den: string, bare = false): AnyNode {
  return {
    type: 'frac',
    data: { hName: 'span', hProperties: { className: ['mx-frac'] } },
    children: [
      {
        type: 'fracNum',
        data: { hName: 'span', hProperties: { className: ['mx-num'] } },
        children: splitScripts(num, bare),
      },
      {
        type: 'fracDen',
        data: { hName: 'span', hProperties: { className: ['mx-den'] } },
        children: splitScripts(den, bare),
      },
    ],
  };
}

/** 一个文本片段 → 「普通文本 / sub / sup / \frac」节点序列。
 *  先切 \frac（它自带结构），剩下的文本再切上下标。`bare` 一路往下传：
 *  分子分母里的 `P_cam` 和外面的同样该是下标。 */
function splitMath(value: string, bare = false): AnyNode[] {
  const out: AnyNode[] = [];
  let last = 0;
  for (const m of value.matchAll(FRAC_G)) {
    const at = m.index ?? 0;
    if (at > last) out.push(...splitScripts(value.slice(last, at), bare));
    out.push(fracNode(m[1], m[2], bare));
    last = at + m[0].length;
  }
  if (last < value.length) out.push(...splitScripts(value.slice(last), bare));
  return out;
}

/** 段落里唯一那个「带空格的除号」：两侧都非空才算，一条式子里只允许出现一次。
 *
 *  为什么这么保守：`1/2πr` 这种不带空格的、或 `a / b / c` 这种连续除的，
 *  靠文本猜分子分母边界一定会猜错 —— 猜错的分数比一行的斜杠更难读，所以直接不转。
 *  等号只认**两侧带空格的**那一种：`Σ_{i=1..k}` 里也有等号，拿它当界会把分母
 *  从一个下标的中间切开（实测踩过：分子变成 `1..k} (2^{rel_i^ast} - 1)`）。 */
function spacedSlash(
  s: string,
): { head: string; num: string; den: string; tail: string } | null {
  let eq = -1;
  /* 命中的是「空格 = 空格」，等号本身在 m.index + 1 —— 差一位就把 `= 1024 × 12` 整段塞进分子 */
  for (const m of s.matchAll(/[ \t]=[ \t]/g)) eq = m.index + 1;
  if (TABLE_ROW.test(s)) return null;
  const head = eq >= 0 ? s.slice(0, eq + 1) : '';
  const body = eq >= 0 ? s.slice(eq + 1) : s;
  const parts = body.split(' / ');
  if (parts.length !== 2) return null;
  let den = parts[1].trim();
  const m = TRAILING_PUNCT.exec(den);
  const tail = m ? m[0] : '';
  if (tail) den = den.slice(0, den.length - tail.length);
  const num = parts[0].trim();
  /* 分子分母里混进汉字或全角标点 ⇒ 这条斜杠后面接的是散文，不是算式
     （`… = Σ_{i=1..k} (2^{rel_i} - 1) / log2(i + 1) ，其中 …` 就把「，其中 …」整句吞进分母）。
     这种一律退回一行斜杠：不转只是朴素，转错了是断裂。 */
  if (!num || !den || num.length > 120 || den.length > 120) return null;
  if (PROSE_EDGE.test(num) || PROSE_EDGE.test(den)) return null;
  return { num, den, tail, head };
}

/** 一个容器节点的纯文本（用来判「这段是不是算式」）。 */
function textOf(node: AnyNode): string {
  if (typeof node.value === 'string') return node.value;
  return (node.children || []).map(textOf).join('');
}

/** 一段文本 → 公式节点序列。`allowSlash` 才尝试把 `A / B` 立成分数；
 *  `bare` 才认没写花括号的简写下标（`P_IT`）。
 *
 *  先试斜杠、再退回 splitMath：`COP = Q_{cool} / W_{comp}` 这种**既有下标又有除法**的
 *  才是最常见的真实算式，早先「有下标就不碰斜杠」的保守写法把它整个漏掉了。
 *  反过来带 `\frac` 的那一段不碰斜杠 —— 两条规则同时改写一条式子容易撞车。 */
function mathNodes(value: string, allowSlash: boolean, bare = false): AnyNode[] {
  const slash = allowSlash && !FRAC.test(value) ? spacedSlash(value) : null;
  if (!slash) return splitMath(value, bare);
  const head = slash.head && !/\s$/.test(slash.head) ? `${slash.head} ` : slash.head;
  const out = splitScripts(head, bare);
  out.push(fracNode(slash.num, slash.den, bare));
  if (slash.tail) out.push({ type: 'text', value: slash.tail });
  return out;
}

/** 就地重写一个 children 数组，返回新数组（父节点负责装回去）。
 *  `math` = 这段已被判为算式 ⇒ 允许把 `A / B` 立成分数（也是灰盒子的判据）；
 *  `bare` = 这段看着就是算式 ⇒ 允许认 `P_IT` 这种没花括号的简写下标。
 *  两个门槛**故意不一样**：灰盒子要严（宁可漏判也不把散文装进盒子），
 *  裸下标要松（他截图里那几条带中文说明的行，严判据会把它们全漏掉）。 */
function walk(children: AnyNode[], math = false, bare = false): AnyNode[] {
  const out: AnyNode[] = [];
  for (const child of children) {
    /* 代码里的公式：行内 code 与围栏 code 都换出去。换成 element 后
       react-markdown 不会再走 code/pre 那套皮肤，所以自己带上 ast-math 类。
       但声明了 python/json/bash 的围栏是真代码 —— 里面再像公式也不动它，
       那里头的 `x_{1}` 是字典键，改了就是改数据。 */
    const keepAsCode =
      child.type === 'code' && Boolean(child.lang) && !PROSE_LANG.test(child.lang ?? '');
    if (!keepAsCode && (child.type === 'inlineCode' || child.type === 'code') && CODE_MATH.test(child.value || '')) {
      const raw = (child.value || '').replace(/\s+$/, '');
      if (child.type === 'inlineCode') {
        out.push({
          type: 'mathInline',
          data: { hName: 'span', hProperties: { className: ['mx-from-code'] } },
          children: mathNodes(raw, !raw.includes('\n'), true),
        });
      } else {
        out.push({
          type: 'mathBlock',
          data: { hName: 'div', hProperties: { className: ['ast-math', 'mx-from-code'] } },
          /* 多行围栏不猜除法：整串只切一次「= 右边」会把后面几行吞进分母 */
          children: mathNodes(raw, !raw.includes('\n'), true),
        });
      }
      continue;
    }
    if (child.type === 'text' && typeof child.value === 'string') {
      if (!SCRIPT_ONE.test(child.value) && !FRAC.test(child.value) && !math && !bare) {
        out.push(child);
        continue;
      }
      out.push(...mathNodes(child.value, math, bare));
      continue;
    }
    if (child.children) {
      /* 段落 / 列表项 / 表格单元都按自己那一段重判：
         紧凑列表的 li 里没有 paragraph 节点，只判 paragraph 会漏掉整列算式。 */
      const own = child.type === 'paragraph' || child.type === 'listItem' || child.type === 'tableCell';
      if (!own) {
        child.children = walk(child.children, math, bare);
      } else {
        const text = textOf(child);
        child.children = walk(child.children, isMathBlock(text), formulaish(text));
      }
    }
    out.push(child);
  }
  return out;
}

/** remark 插件（attacher 形态）：整棵树做四件事 ——
 *  `_{}`/`^{}` → sub/sup、`\frac{}{}` → 上下结构分数、算式里唯一的 `A / B` → 分数、
 *  代码里的公式 → 换出代码皮肤。
 *
 *  必须是「返回 transformer 的函数」而不是直接拿 tree 的函数：unified 在 freeze
 *  阶段调用插件时传的是 options，直接把 transformer 当插件塞进去会拿到 undefined。 */
export function remarkMathText() {
  return (tree: { children: unknown[] }): void => {
    tree.children = walk(tree.children as AnyNode[]);
  };
}

/** 算式的构成证据 —— 攒够 4 分才判公式，宁可漏判也不把散文装进灰盒子。
 *  等号权重最高（2），因为它单独出现太常见：「超时 = 30s」不算算式。 */
function evidence(s: string): number {
  let n = 0;
  if (s.includes('=')) n += 2;
  if (MATH_OPS.test(s)) n += 1;
  if (/\([^)]*\)/.test(s)) n += 1;
  // 变量/数字之间的 * / ^：`a / b`、`1024 × 12 / 0.92`、`x ^ 2`
  if (/[\w)\]]\s*[*/]\s*[\w(]/.test(s)) n += 1;
  if (/[\w)\]]\s*\/\s*[\w(^]/.test(s)) n += 1;
  // 项与项之间的加减：`x ^ 2 + y ^ 2 = r ^ 2` 这类没有括号也没有花括号
  if (/[\w)\]]\s*[+-]\s*[\w(]/.test(s)) n += 1;
  if (/\^[ \t]*\{|\^[ \t]*\d/.test(s)) n += 1;
  if (SCRIPT_ONE.test(s)) n += 3;
  return n;
}

/** 这一段是算式吗？（只管「要不要套灰盒子」，上下标换不换由 `_{}` 本身决定）
 *
 *  - 汉字连成三个以上（「与之一致」「为按增益降序重排…」）⇒ 一定不是：那是散文，
 *    哪怕里面嵌着一条完整的算式。灰盒子是等宽 + 不换行，套上去只会更难读。
 *  - 汉字占比 >3 成 ⇒ 也不是（同上，只是拦的是「散字夹在算式里」那种）。
 *  - 带 `_{}`/`^{}` ⇒ 是（散文里不会出现这种写法）；
 *  - 否则要求证据 ≥4：等号权重最高，因为它单独出现太常见（「超时 = 30s」不算算式）。
 *  - 超过 400 字符不当公式：那是一整段说明，不是算式。 */
export function isMathBlock(raw: string): boolean {
  const s = raw.trim();
  if (!s || s.length > 400) return false;
  const { total, maxRun } = cjkStats(s);
  if (maxRun >= 3 || total / s.length > 0.3) return false;
  if (SCRIPT_ONE.test(s)) return true;
  if (!s.includes('=')) return false;
  return evidence(s) >= 4;
}
