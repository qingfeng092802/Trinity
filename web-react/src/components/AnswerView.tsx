import { Children, cloneElement, isValidElement, memo, useMemo, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import type { PluggableList } from 'unified';
import { isMathBlock, remarkMathText } from '../utils/answerMath';
import { isBareHeadingLine, isNumericCell, liftBareHeadings } from '../utils/answerText';
import { bumpRender } from '../utils/renderLedger';

/** FINAL ANSWER 的富文本渲染：react-markdown + remark-gfm。

 三条口径：
 1. **安全**：不开 `rehype-raw`，模型输出里的原生 HTML 进不了 DOM；链接统一
    `target=_blank` + `rel=noopener noreferrer`。
 2. **排版走设计 token**：字号 / 颜色 / 圆角与站内其他区块同源，不用 markdown
    库自带的那套文章页默认样式。
 3. **不改写文字**：渲染器只决定「怎么摆」，不删句、不补句、不重排序号。
    允许的两处**结构**改写都在喂给渲染器的那一份串上：`hardBreaks`（单换行补成硬换行）
    与 `liftBareHeadings`（把「一、xxx」这类裸序号行从正文里分出来）——
    两者只加空白字符，一个字都不动，所以复制按钮复制的是**原文**而不是渲染串。

 表格是重灾区，单独处理：外层 `overflow: auto` 横向滚动 + `thead` 粘性，
 并按列扫描内容 —— **整列都是数值**才右对齐（保守判定，「约 7.7kW」这种
 带前缀的不算数值列，宁可左对齐也不猜错）。

 注意：react-markdown 会给自定义组件多传一个 `node`（hast 节点），只能显式挑
 需要的属性往下铺，不能把 props 整包 spread 到 DOM 元素上。

 数值列判定（isNumericCell）、结论摘录（pickConclusion）、裸序号标题判定
 （isBareHeadingLine / liftBareHeadings）这几个纯文本逻辑在 utils/answerText.ts
 —— 那边不依赖 React，能在 node 里直接跑断言。
 */

/** 行 / 单元格 / 列表项这类元素，往下只用到这几个字段。 */
type El = ReactElement<{ children?: ReactNode; className?: string }>;

function els(n: ReactNode): El[] {
  return Children.toArray(n).filter(isValidElement) as El[];
}

/** 把 React 子树压成纯文本，供「重复段」「数值列」判定用。 */
function nodeText(n: ReactNode): string {
  if (n === null || n === undefined || typeof n === 'boolean') return '';
  if (typeof n === 'string' || typeof n === 'number') return String(n);
  if (Array.isArray(n)) return n.map(nodeText).join('');
  if (isValidElement(n)) return nodeText((n.props as { children?: ReactNode }).children);
  return '';
}

function cx(...parts: Array<string | undefined | false>): string {
  return parts.filter(Boolean).join(' ');
}

const cellsOf = (row: El) => els(row.props.children);

/** 整列都是数值才右对齐：只用表体投票，表头是「单路功率」这种词不该把列带偏。 */
function numericCols(bodyRows: El[]): number[] {
  const colCount = bodyRows.reduce((m, r) => Math.max(m, cellsOf(r).length), 0);
  const out: number[] = [];
  for (let c = 0; c < colCount; c += 1) {
    const texts = bodyRows
      .map((r) => nodeText(cellsOf(r)[c]?.props.children))
      .filter((t) => t.trim() !== '');
    if (texts.length > 0 && texts.every(isNumericCell)) out.push(c);
  }
  return out;
}

/** 把 .is-num 打到这些行的对应列上（th 与 td 同样处理，否则表头跟内容对不齐）。 */
function markRows(rows: El[], cols: number[]): ReactNode {
  return rows.map((row, ri) =>
    cloneElement(row, {
      key: ri,
      children: cellsOf(row).map((cell, ci) =>
        cols.includes(ci) ? cloneElement(cell, { className: cx(cell.props.className, 'is-num') }) : cell,
      ),
    }),
  );
}

/** 表格整体接管：外层滚动盒 + 数值列判定，一次遍历把表头表体都标好。 */
function Table({ children }: { children?: ReactNode }): ReactElement {
  const sections = els(children);
  const rowsOf = (sec: El) => els(sec.props.children);
  const head = sections.slice(0, 1).flatMap(rowsOf);
  const body = sections.slice(1).flatMap(rowsOf);
  const cols = numericCols(body);
  return (
    <div className="ast-table-wrap">
      <table className="ast-table">
        {sections.map((sec, si) =>
          cloneElement(sec, {
            key: si,
            children: markRows(si === 0 ? head : body, cols),
          }),
        )}
      </table>
    </div>
  );
}

/** 把 markdown 源按空行切成块，记下每块的字符区间（不切内容，只定位）。 */
function blockRanges(text: string): Array<{ start: number; end: number }> {
  const out: Array<{ start: number; end: number }> = [];
  const sep = /\n[ \t]*\n/g;
  let from = 0;
  let m: RegExpExecArray | null;
  while ((m = sep.exec(text))) {
    if (m.index > from) out.push({ start: from, end: m.index });
    from = m.index + m[0].length;
  }
  if (from < text.length) out.push({ start: from, end: text.length });
  return out;
}

/** 重复段折叠：长答案里同一段结论常被复述（Reviewer 退回后重写尤其明显）。
 *
 * 判定在**渲染之前**、按源文本做一次：字符串全等（忽略空白）才算复述，
 * 相似但不同的内容一律不动。折叠对象是「第二次及以后出现」的那些块，
 * 用块的起始偏移当身份 —— 这样 StrictMode 双跑、组件重渲染都拿到同一个答案，
 * 不会再出现「自己在渲染过程中数自己」这种把首段也认成重复的错。
 */
function findRepeats(text: string) {
  const collapse = new Set<number>();
  const originOf = new Map<number, string>();
  const firstOf = new Map<string, number>();
  for (const { start, end } of blockRanges(text)) {
    const key = text.slice(start, end).trim().replace(/\s+/g, '');
    if (key.length < 40) continue;
    const first = firstOf.get(key);
    if (first === undefined) {
      firstOf.set(key, start);
    } else {
      collapse.add(start);
      originOf.set(start, text.slice(first, first + 24).replace(/\s+/g, ' '));
    }
  }
  const ranges = blockRanges(text);
  /** 段落节点的起始偏移落在哪一块里 */
  const blockStartAt = (offset: number): number | undefined => {
    let hit: number | undefined;
    for (const r of ranges) {
      if (offset < r.start) break;
      if (offset < r.end) hit = r.start;
    }
    return hit;
  };
  return { collapse, originOf, blockStartAt };
}

/** 公式区：把「源文本里这一段是算式」的判定换算成块的起始偏移。
 *
 *  表格块（含 `|`）永远排除 —— 单元格里的段落也走 `p` 覆写，
 *  不排掉的话一个等号就能把表格里的某格变成灰盒子。 */
function findMathBlocks(text: string): Set<number> {
  const out = new Set<number>();
  for (const { start, end } of blockRanges(text)) {
    const raw = text.slice(start, end);
    if (raw.includes('|')) continue;
    if (isMathBlock(raw)) out.add(start);
  }
  return out;
}

/** 裸序号小标题：把「一、xxx」那种独立成段的行标成块起始偏移。
 *
 *  判定与 `liftBareHeadings` 共用 :func:`isBareHeadingLine`（同一份正则，两处不会分叉）。
 *  多行块与表格块直接排除：能被标成标题的只有"整块就一行"的那种。 */
function findBareHeadings(text: string): Set<number> {
  const out = new Set<number>();
  for (const { start, end } of blockRanges(text)) {
    const raw = text.slice(start, end).trim();
    if (!raw || raw.includes('\n')) continue;
    if (isBareHeadingLine(raw)) out.add(start);
  }
  return out;
}

function buildComponents(
  repeats: ReturnType<typeof findRepeats>,
  math: Set<number>,
  headings: Set<number>,
  open: Record<string, boolean>,
  setOpen: (fn: (prev: Record<string, boolean>) => Record<string, boolean>) => void,
): Components {
  const { collapse, originOf, blockStartAt } = repeats;
  return {    // 答案里不该出现 h1（那是页面级标题的层级），整体降一级
    h1: ({ children }) => <h2 className="ast-h ast-h--1">{children}</h2>,
    h2: ({ children }) => <h3 className="ast-h ast-h--2">{children}</h3>,
    h3: ({ children }) => <h4 className="ast-h ast-h--3">{children}</h4>,
    h4: ({ children }) => <h5 className="ast-h ast-h--3">{children}</h5>,
    h5: ({ children }) => <h6 className="ast-h ast-h--4">{children}</h6>,
    h6: ({ children }) => <h6 className="ast-h ast-h--4">{children}</h6>,

    p: ({ children, node }) => {
      const off = node?.position?.start.offset;
      const block = off === undefined ? undefined : blockStartAt(off);
      if (block !== undefined && collapse.has(block) && !open[block]) {
        const origin = originOf.get(block) ?? '';
        return (
          <button
            type="button"
            className="ast-dup"
            onClick={() => setOpen((prev) => ({ ...prev, [block]: true }))}
          >
            与上文「{origin}…」完全重复 · 点开看原文
          </button>
        );
      }
      /* 裸序号行（「一、门禁开门延时默认几秒？」）：`liftBareHeadings` 已经把它从正文里
         分成独立段落，这里换上**一级**标题的皮肤 —— 后端不少答案不用 markdown 的 #，
         整篇读下来没有层级，正文糊成一坨；而「一、」在作者的编号体系里就是最高一层。 */
      if (block !== undefined && headings.has(block)) {
        return <div className="ast-h ast-h--1">{children}</div>;
      }
      /* 算式段：等号与括号密集的段落换成等宽 + 深一阶底 + 横向可滚，
         读起来就不再是「一段没写完的代码」。 */
      if (block !== undefined && math.has(block)) {
        return <p className="ast-p ast-math">{children}</p>;
      }
      return <p className="ast-p">{children}</p>;
    },

    /* 加粗**且含数字**的那一格提到主色。
       刻意只借用模型自己的强调信号：真答案（n=8）里"关键数字"的朴素嗅探会碰到
       105 个数字 token（≈13 个/篇，还含序号与型号上下文），全染成主色等于没有重点。 */
    strong: ({ children }) => (
      <strong className={/\d/.test(plainText(children)) ? 'ast-num' : undefined}>
        {children}
      </strong>
    ),

    ul: ({ className, children }) => <ul className={cx('ast-ul', className)}>{children}</ul>,
    ol: ({ className, children, start }) => (
      <ol className={cx('ast-ol', className)} start={start}>
        {children}
      </ol>
    ),
    li: ({ className, children }) => <li className={cx('ast-li', className)}>{children}</li>,

    table: Table,

    blockquote: ({ children }) => <blockquote className="ast-quote">{children}</blockquote>,
    pre: ({ children }) => <pre className="ast-pre">{children}</pre>,
    code: ({ className, children }) =>
      // 块级代码带 language-* 标记，行内的没有
      /language-/.test(className ?? '') ? (
        <code className={cx('ast-codeblock', className)}>{children}</code>
      ) : (
        <code className="ast-code">{children}</code>
      ),

    a: ({ href, children }) => (
      <a className="ast-a" href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    hr: () => <hr className="ast-hr" />,
  };
}

export interface AnswerViewProps {
  text: string;
}

/** 单个换行是作者的分意（后端不少答案是纯文本按行排的），但 Markdown 把软换行当空格吞掉，
 *  两行会并成一行。这里补成 Markdown 的硬换行（行尾两个空格），空行分隔照旧不动。 */
function hardBreaks(md: string): string {
  return md.replace(/([^\n])\n(?!\n)/g, '$1  \n');
}

/** children → 纯文本，只用来判「这格里有没有数字」。
 *  元素节点（比如加粗里套了行内代码）一律当空串 —— 宁可漏染，不误染。 */
function plainText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(plainText).join('');
  return '';
}

/** 模块级常量：每次 render 新建数组会让 react-markdown 的 processor 缓存失效，
 *  等于每敲一次「展开重复段」就重解析一遍整篇答案。 */
const REMARK_PLUGINS: PluggableList = [remarkGfm, remarkMathText];

/** ⚠️ `memo` 是这一层的正事（报告 A4①）。
 *
 *  上面那串 useMemo 只挡住了**解析**（findRepeats / findMathBlocks / 裸序号分块），
 *  挡不住 react-markdown 自己那棵 element 树：父级（结果页签所在的 ResultPane）任何一次
 *  与答案无关的重渲染 —— 展开/收起那 181 行引用、跑动中那枚秒表 —— 都会把整棵
 *  markdown 树（表格 + 重复段 + 公式区）重建一遍。答案文本一旦落地就不再变，所以
 *  默认浅比较正好够用，不需要自定义 areEqual。
 *  护栏：TaskLogPage 把它包在 `<Profiler id="answer">` 里数提交，判定用下面那枚 render
 *  自数；断言在 running.cjs 的 U 趟（双向：先证换答案时计数器数得到，再证无关重渲染数不到）。 */
export default memo(function AnswerView({ text }: AnswerViewProps) {
  /* ⚠️ 探针专用的 **render 计数**（护栏：U 趟）。为什么判定不用外面那枚
     `<Profiler id="answer">` 的提交数：实测切四次页签，Profiler 从 3 涨到 7，而答案的
     DOM 节点始终是同一个 —— 父级每重渲染一次，Profiler 自己就是一次 commit，
     memo 挡得住本组件、挡不住 Profiler 被重新渲染。要问的问题恰恰是"这个函数体跑了几遍"。
     账本与这套两枚计数的分工都写在 utils/renderLedger.ts。 */
  bumpRender('answerRenders');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // 先分裸序号行，再补硬换行：顺序反了的话分出来的空行会被 hardBreaks 当普通行处理
  const src = useMemo(() => hardBreaks(liftBareHeadings(text)), [text]);
  /* ⚠️ 块偏移必须在**喂给渲染器的那一份字符串**上算。
     hardBreaks 会在每个单换行前插两个空格 ⇒ 拿原文算区间、再拿 hast 的偏移去查，
     第一个多行块之后的所有块都会错位（重复段/公式区同时判错）。 */
  const repeats = useMemo(() => findRepeats(src), [src]);
  const math = useMemo(() => findMathBlocks(src), [src]);
  const headings = useMemo(() => findBareHeadings(src), [src]);
  const comps = useMemo(
    () => buildComponents(repeats, math, headings, open, setOpen),
    [repeats, math, headings, open],
  );

  return (
    <div className="answer">
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={comps}>
        {src}
      </ReactMarkdown>
    </div>
  );
});
