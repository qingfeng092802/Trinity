import type { Citation, TraceEvent } from '../types';
import { DASH } from './format';

/* 引用列表：从 knowledge_search 的返回文本里还原「哪一篇、第几段、多相关」。
 *
 * 为什么前端要解析一段文本：后端**没有** citations 字段 ——
 * `api/schemas.py:538` 的 TaskEventView 只给 `observation: str`，检索命中本来就只以
 * 渲染文本的形式落库（`core/tools/builtin/knowledge_search.py:_render`）。
 *
 * 文本形状由后端那份集成测试钉着（tests/integration/test_knowledge_tool.py:120-123，
 * 断言的是「共命中 / 相关度 / chunk」三个子串，不是整行），所以这里**只认得就拆、
 * 认不得就不拆**，绝不去猜没匹配上的行。
 *
 * ⚠️ 分隔符是全角 `｜`（U+FF5C），不是 ASCII `|` —— 写错一个字符整条规则静默不命中，
 * 列表会退回「一行 + 全 —」，看起来像后端没数据。
 */

/** 一条命中的引用行：`【n】文档名 · chunk 12（字符 0-512）｜相关度 0.83（BM25 … / 向量 …）` */
const CITE_LINE = /^【(\d+)】(.+?)｜相关度\s*(-?\d+(?:\.\d+)?)（/;

/** 引用行里的来源部分，形状由 `rag/types.py:SearchHit.citation()` 唯一决定。
 *  chunk 序号允许是 **-1**：`chunk_seq` 默认值就是 -1（没回填位置的命中），
 *  这条是那份真 fixture 逼出来的 —— 只写 `\d+` 会把整行的文档名一起判成读不出。 */
const CITE_DOC = /^(.*?) · chunk (-?\d+)（字符 (\d+)-(\d+)）$/;

/** 片段预算：与上一版一致（后端按预算阶梯截断，这里只是兜住极端长的 observation） */
const SNIPPET_MAX = 400;

/** 一条工具返回 → 若干条引用。认不出引用行时返回**一条**「全 —」的记录：
 *  列表里少了行是「后端没给」，行在但字段是 — 才是「给了但读不出」，两者要分得开。 */
export function parseCitations(eventSeq: number, observation: string): Citation[] {
  const lines = observation.split('\n');
  const marks: Array<{ at: number; n: string; score: number }> = [];
  for (let i = 0; i < lines.length; i += 1) {
    const m = CITE_LINE.exec(lines[i].trim());
    if (m) marks.push({ at: i, n: m[1], score: Number(m[3]) });
  }
  if (marks.length === 0) {
    return [
      {
        chunkId: `#${eventSeq}`,
        document: DASH,
        score: Number.NaN,
        snippet: observation.slice(0, SNIPPET_MAX),
      },
    ];
  }
  return marks.map((mark, i) => {
    const head = lines[mark.at].trim();
    /* 文档名只从引用行里取：CITE_DOC 不匹配就是 —，不把整行塞进文档列凑数 */
    const doc = CITE_DOC.exec(head.match(CITE_LINE)?.[2] ?? '');
    const bodyTo = i + 1 < marks.length ? marks[i + 1].at : lines.length;
    const snippet = lines
      .slice(mark.at + 1, bodyTo)
      .join('\n')
      .trim();
    return {
      /* 溯源口径：#事件序号·【命中序号】—— 轨迹回放页按 event_seq 排，这两个数一起才落得下去 */
      chunkId: `#${eventSeq}·【${mark.n}】`,
      document: doc ? doc[1] : DASH,
      score: mark.score,
      snippet: snippet.slice(0, SNIPPET_MAX),
    };
  });
}

/** 整条轨迹 → 引用列表。只有 knowledge_search 且 observation 非空的事件才算引用。 */
export function buildCitations(trace: Array<Pick<TraceEvent, 'event_seq' | 'tool_name' | 'observation'>>): Citation[] {
  return trace
    .filter((e) => e.tool_name === 'knowledge_search' && (e.observation ?? '').length > 0)
    .flatMap((e) => parseCitations(e.event_seq, e.observation as string));
}
