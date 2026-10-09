/* 答案文本的纯函数工具：结论摘录 + 数值列判定。
   放这儿而不是组件里，是为了能在 node 里直接跑断言，不必拉起 React。 */

const HEAD_RE = /^\s{0,3}#{1,6}\s*(.+?)\s*$/;
const CONCLUSION_LABEL =
  /^(?:最终|综合|分析)?(?:结论|总结|小结|结果|建议|答案|摘要)|^综上(?:所述)?/;

/** markdown 片段 → 单行纯文本（只为摘要条服务，不改写原文）。 */
function plain(md: string): string {
  return md
    .replace(/`{1,3}([^`]*)`{1,3}/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+[.、)]\s+/gm, '')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/\s*\n\s*/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/** 「结论：xxx」拆成标签与正文；没有冒号时正文为空。 */
function splitLabel(s: string): [string, string] {
  const i = s.search(/[：:]/);
  return i > 0 ? [s.slice(0, i).trim(), s.slice(i + 1).trim()] : [s.trim(), ''];
}

/** 摘要条只留一两句话：在 200 字内找最后一个句末标点截断，找不到就硬截加省略号。 */
function clip(t: string): string {
  if (t.length <= 200) return t;
  const cut = t.slice(0, 200);
  const i = Math.max(
    cut.lastIndexOf('。'),
    cut.lastIndexOf('！'),
    cut.lastIndexOf('？'),
    cut.lastIndexOf(';'),
  );
  return i > 40 ? cut.slice(0, i + 1) : `${cut.slice(0, 180).trimEnd()}…`;
}

export interface Conclusion {
  /** 命中的标签，如「结论」「综上所述」「摘要」 */
  label: string;
  text: string;
}

/** 从 Final Answer 里摘录结论段。

 纯机械提取，一个字都不补：
 1. 找「结论 / 总结 / 建议 …」小标题，取它下面第一段正文（标题自带冒号就取冒号后）；
 2. 找不到标题就找以结论词开头的段落；
 3. 都没有就退回第一段，标签写成「摘要」—— 它确实只是答案开头那段，
    不冒充「结论」（早先这里叫「答案首段」，读起来像故障信息而不是一个标签）。
 表格块（含 `|`）永远不当结论：一句话摘要条装不下一张表。 */
export function pickConclusion(md: string): Conclusion | null {
  const blocks = md.split(/\n\s*\n/);
  const tagOf = (s: string) => CONCLUSION_LABEL.exec(s)?.[0] ?? s;
  /** 「综上所述，综上所述，…」读两遍：正文开头的标签由摘要条负责，这里剔掉。 */
  const stripTag = (text: string, tag: string) =>
    text.startsWith(tag) ? text.slice(tag.length).replace(/^[，,：:、。\s]+/, '') : text;
  const hit = (rawLabel: string, body: string): Conclusion => {
    const label = tagOf(rawLabel);
    return { label, text: clip(stripTag(body, label)) };
  };

  for (let i = 0; i < blocks.length; i += 1) {
    const lines = blocks[i].split('\n');
    const h = HEAD_RE.exec(lines[0]);
    if (h) {
      const [label, inlineBody] = splitLabel(h[1].replace(/[*_]/g, ''));
      if (CONCLUSION_LABEL.test(label)) {
        const nxt = HEAD_RE.test(blocks[i + 1] ?? '') ? '' : plain(blocks[i + 1] ?? '');
        // 标题自带正文就用它；否则看同块后续行，再看下一块（下一块也是标题就作罢）
        const body = inlineBody || plain(lines.slice(1).join('\n')) || nxt;
        if (body.length >= 12 && !body.includes('|')) return hit(label, body);
      }
      continue;
    }
    const [label, body] = splitLabel(plain(lines[0]));
    if (CONCLUSION_LABEL.test(label)) {
      // 「综上所述，…」这类没有冒号的，整段端出去再剔掉开头标签
      const text = body.length >= 12 ? body : plain(blocks[i]);
      if (text.length >= 12 && !text.includes('|')) return hit(label, text);
    }
  }

  for (const b of blocks) {
    const t = plain(b);
    if (t.length >= 20 && !t.includes('|')) return { label: '摘要', text: clip(t) };
  }
  return null;
}

/** 纯数值单元格：可带千分位、正负号与一个常见单位。
 *  刻意不收「约 / 左右 / ≈」这类前后缀 —— 认不准就退回左对齐。 */
const NUM_CELL =
  /^[-+−]?[\d][\d,._]*(?:%|‰|x|×|k|K|M|G|万|亿|元|¥|℃|dB|Wh|kWh|mWh|mAh|Ah|W|kW|V|A|s|ms|min|h|年|月|天|小时|分钟|秒|个月|个|路|台|次|档|项|条|倍)?$/;

export function isNumericCell(raw: string): boolean {
  const t = raw.replace(/\s+/g, '');
  return t !== '' && /\d/.test(t) && NUM_CELL.test(t);
}

/* ------------------------- 裸序号小标题（真数据量出来的口径） ------------------------- */

/** 后端不少答案不用 markdown 标题，直接按行排「一、xxx」。
 *
 * 口径来自 2026-09-24 对库内 8 篇真答案的只读统计：这种行**全部**是
 * 「序号行 + 紧跟正文」同一个块（4/4 处），长度都在 32 字以内。
 * 刻意**只认中文序号 +「、」**：`1、` / `1.` 与 markdown 的有序列表撞车，
 * 认了就会把列表项拆成标题 —— 那是把结构弄坏，不是排版。 */
const BARE_HEADING = /^[一二三四五六七八九十]{1,3}、/;

/** 这一行是不是小标题？长句、带句号的、表格行一律不算。
 *  允许结尾「？」—— 中文里「一、门禁延时默认几秒？」就是标题写法。 */
export function isBareHeadingLine(raw: string): boolean {
  const t = raw.trim();
  if (!BARE_HEADING.test(t)) return false;
  if (t.length > 32) return false;
  if (t.includes('。') || t.includes('！') || t.includes('；') || t.includes('|')) return false;
  return true;
}

/** 把「序号行 + 紧跟正文」里的序号行提成独立段落（在它后面插一个空行）。
 *
 * 只在**块的第一行**且该块确实还有后续行时才动：单独成段的「一、xxx」本来就是段落，
 * 拆它没有意义。围栏代码块（``` 之间）里一律不动 —— 那不是排版，是别人的源码。
 * 返回的串才是喂给渲染器的那一份，重复段/公式区的偏移都跟着它算。 */
export function liftBareHeadings(md: string): string {
  const lines = md.split('\n');
  const out: string[] = [];
  let fence = false;
  for (let i = 0; i < lines.length; i += 1) {
    const cur = lines[i];
    if (/^\s{0,3}```/.test(cur)) fence = !fence;
    out.push(cur);
    if (fence) continue;
    const prevBlank = i === 0 || lines[i - 1].trim() === '';
    const next = i + 1 < lines.length ? lines[i + 1] : '';
    if (prevBlank && next.trim() !== '' && isBareHeadingLine(cur)) out.push('');
  }
  return out.join('\n');
}
