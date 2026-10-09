/* buildCitations / parseCitations 的断言集：npx esbuild 转成 cjs 后直接在 node 跑。
   用法：npx esbuild src/utils/citations.ts --bundle --format=cjs --outfile=tools/uicheck/citations.cjs
        node tools/uicheck/citations.test.cjs

   ⚠️ 下面那份 observation **不是我编的**：它是后端自己的渲染函数打出来的，
   复现命令（改完 knowledge_search._render 或 SearchHit.citation() 就要重跑一次抄期望值）：

     python -c "import sys;sys.path.insert(0,'.');from rag.types import SearchHit; \
       from core.tools.builtin import knowledge_search as ks; \
       print(ks._render([SearchHit(chunk_id='c12',score=0.83,bm25_score=0.71,vector_score=0.92, \
       document_id='d1',document_name='anfangjiankong.md',chunk_seq=12,start_char=0,end_char=512,text='…')],200))"

   另一份（认不出来的那条）是从 data/trinity.db 的 task_events 里读的真实 observation。 */
const { buildCitations, parseCitations } = require('./citations.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}

const REAL = [
  '共命中 3 条相关片段：',
  '【1】anfangjiankong.md · chunk 12（字符 0-512）｜相关度 0.83（BM25 0.71 / 向量 0.92）',
  '系统由前端设备、传输网络、监控中心三部分组成。系统由前端设备、传输网络、监控中心三部分组成。',
  '【2】anfangjiankong.md · chunk 31（字符 900-1400）｜相关度 0.61（BM25 0.55 / 向量 0.66）',
  '供电方式宜采用 PoE。',
  '【3】d2 · chunk -1（字符 0-0）｜相关度 0.40（BM25 0.40 / 向量 0.00）',
].join('\n');

/* ---- 真形状：一次检索 3 条命中 ⇒ 3 行，各自带真文档名与真相关度 ---- */
const rows = parseCitations(7, REAL);
eq('3 条命中拆成 3 行', rows.length, 3);
eq('第 1 行的溯源 id', rows[0].chunkId, '#7·【1】');
eq('第 1 行的文档名取自引用行（不再写死「知识库检索结果」）', rows[0].document, 'anfangjiankong.md');
eq('第 1 行的相关度是融合分', rows[0].score, 0.83);
eq('第 1 行的片段是引用行与下一条之间那些行', rows[0].snippet.startsWith('系统由前端设备'), true);
eq('第 2 行文档名', rows[1].document, 'anfangjiankong.md');
eq('第 2 行相关度', rows[1].score, 0.61);
eq('第 3 行：后端 document_name 为空时引用行里落的是 document_id，前端照实显示', rows[2].document, 'd2');
eq('第 3 行没有片段 ⇒ 空串（界面据此写「未带原文片段」，不拿省略号冒充内容）', rows[2].snippet, '');
eq('三行的 chunkId 互不相同（memo + key 的前提）', new Set(rows.map((r) => r.chunkId)).size, 3);

/* ---- 认不出来就整条退回一行「—」：绝不替后端编一个文档名 ---- */
const ERR =
  'KnowledgeSearchError: 检索失败：[retrieval] 知识库服务不可用；' +
  '[storage] sqlite-vec 未安装，无法使用 sqlite-vec 后端：No module named \'sqlite_vec\'';
const bad = parseCitations(12, ERR);
eq('真错误串 ⇒ 1 行', bad.length, 1);
eq('认不出文档名 ⇒ —', bad[0].document, '—');
eq('认不出相关度 ⇒ NaN（界面显示 —，不补 0）', Number.isNaN(bad[0].score), true);
eq('整段原文仍然留给用户看', bad[0].snippet, ERR);
eq('溯源 id 退回到只有事件序号', bad[0].chunkId, '#12');

eq('只有【n】没有「｜相关度」不算命中行', parseCitations(1, '【1】某文档 · chunk 3（字符 0-9）\n片段').length, 1);
eq('半角 | 冒充全角 ｜ 不算命中行（这条就是分隔符踩坑的护栏）', parseCitations(1, '【1】a.md · chunk 1（字符 0-9)|相关度 0.5（x）').length, 1);
eq('空 observation ⇒ 0 行由上层过滤，这里给一行空片段', parseCitations(3, '').length, 1);

/* ---- 形状对但字段怪：照实读，不修数据 ---- */
const zero = parseCitations(5, '【1】x.md · chunk 0（字符 0-0）｜相关度 0.00（BM25 0.00 / 向量 0.00）\n正文');
eq('相关度 0 是真的 0，不是缺值', zero[0].score, 0);
const wide = parseCitations(6, '【1】带 空格 的文档名.md · chunk 9（字符 1-2）｜相关度 1.00（BM25 1.00 / 向量 1.00）\n正文');
eq('文档名里的空格照实保留', wide[0].document, '带 空格 的文档名.md');

/* ---- 多事件：序号 + 命中序号 才唯一 ---- */
const many = buildCitations([
  { event_seq: 3, tool_name: 'knowledge_search', observation: REAL },
  { event_seq: 4, tool_name: 'calculator', observation: '15232.0' },
  { event_seq: 5, tool_name: 'knowledge_search', observation: '' },
  { event_seq: 6, tool_name: 'knowledge_search', observation: REAL },
]);
eq('非检索工具不算引用', many.filter((c) => c.chunkId.startsWith('#4')).length, 0);
eq('observation 为空的事件不算引用', many.filter((c) => c.chunkId.startsWith('#5')).length, 0);
eq('两次检索共 6 行', many.length, 6);
eq('跨事件仍然唯一（key 撞了 memo 就会张冠李戴）', new Set(many.map((c) => c.chunkId)).size, 6);
eq('第一行的溯源确实落在 event_seq=3', many[0].chunkId, '#3·【1】');

/* ---- 片段预算兜住超长 ---- */
const long = parseCitations(9, `【1】a.md · chunk 1（字符 0-9）｜相关度 0.50（BM25 0.5 / 向量 0.5）\n${'字'.repeat(900)}`);
eq('超长片段截到 400', long[0].snippet.length, 400);

console.log(`citations: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
  process.exit(1);
}
