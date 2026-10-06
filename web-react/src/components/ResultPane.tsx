import { memo, Profiler, useEffect, useMemo, useRef, useState, type ProfilerOnRenderCallback } from 'react';
import { Button } from 'antd';
import { CheckCircleOutlined, HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import AnswerView from './AnswerView';
import CostBreakdown from './CostBreakdown';
import RunProgress from './RunProgress';
import { Chip, CopyButton, EmptyState, MetricTile } from './ui';
import { bumpCommit, bumpRender } from '../utils/renderLedger';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { liveAnswer } from '../utils/liveAnswer';
import { fmtDec, fmtDuration, fmtInt, truncate } from '../utils/format';
import { TOKEN_VARIANCE_NOTE } from '../utils/costNote';
import { pickConclusion } from '../utils/answerText';
import { STATUS_LABELS, type AgentNode, type Citation, type TaskRecord } from '../types';

/** `<Profiler id="answer">` 的账本回调（只打印，不判定 —— 判定看 AnswerView 里那枚
 *  render 自数，理由写在 utils/renderLedger.ts 顶部）。 */
const countCommit: ProfilerOnRenderCallback = (id, _phase, actualDuration) =>
  bumpCommit(id, actualDuration);

/** 引用列表折叠态铺几行。10 = 一次检索的 top-k 常见上限，
 *  也就是「不点展开也能看全一轮检索」的那个宽度。 */
const CITATION_PREVIEW = 10;

/** 一条引用 = 一行。memo 的理由与 ToolCard 同源，但**这一条才是量出来的那个开销**：
 *  5,000 事件那一档结果页铺 1,000 行引用、约 11,000 个元素，
 *  切走再切回来时 `c` 的引用一个都没变（`record.result.citations` 已落定），
 *  React 那半边纯属白算（拆法见 tools/uicheck/README.md 的「结果页往返那 230ms 的账」）。
 *
 *  ⚠️ 它治不了浏览器那半边：11,000 个节点重新可见时的 style/layout/paint 约 107ms。
 *  那一半是靠上面的「默认只渲染前 10 行」治的，不是靠 memo。
 *  （P1-01 之后又多了一治：整个结果页签不激活就不挂载，见下面的 ResultPane；
 *  实测 5,000 事件那一档"停在日志页签时全页常驻元素"= 501，引用行与工具卡都是 0，
 *  数与口径见 tools/uicheck/README.md 的 V 节。） */
const CitationRow = memo(function CitationRow({ c }: { c: Citation }) {
  return (
    <div className="list-row is-static">
      <span className="list-row-main">
        <span className="row" style={{ gap: 7 }}>
          <Chip mono tone={{ fg: 'var(--info-fg)', soft: 'var(--info-soft)' }}>
            {c.chunkId}
          </Chip>
          <b className="fs-12">{c.document}</b>
          {/* score 是引用行里那个融合分（0..1）。解析不出来时是 NaN → fmtDec 给「—」，
              不补 0 —— 补 0 会把「读不出」显示成「相关性为零」。 */}
          <span className="fs-11 t3 tabular">相关度 {fmtDec(c.score, 2)}</span>
        </span>
        {c.snippet ? (
          <span className="fs-12 t2" style={{ lineHeight: 1.6 }}>
            {c.snippet}
          </span>
        ) : (
          /* 后端按预算阶梯截断过：命中确实存在，只是这次没带原文片段。
             空片段留白会被读成「解析失败」，所以明说。 */
          <span className="fs-11 t3">（本次返回未带原文片段）</span>
        )}
      </span>
      <CopyButton text={c.snippet || c.chunkId} />
    </div>
  );
});

export interface ResultPaneProps {
  record: TaskRecord | null;
  running: boolean;
  /** 折叠状态是**页面**的，不是这一块的：切任务时不该重置（用户的阅读偏好），
   *  而切页签会把本组件整个卸载 —— 状态留在外面才活得过卸载。 */
  citationsOpen: boolean;
  onCitationsOpenChange: (open: boolean) => void;
  /** 已经交过卷的最后一个节点（`node` SSE 事件 = 该节点**已完成**，见 utils/runPhase.ts）。
   *  跑动中那行字由它推出来；页面持有事件缓冲，所以由页面算好传进来。 */
  lastDoneNode: AgentNode | null;
  /** 这一条的答案**不播**打字机，直接整段给。两种情况算"不播"：
   *  ① 这个任务已经逐段揭示过一次了 —— 切页签会卸载本组件，没有这层标志的话每次
   *     切回来都要重播，第二次看的人会以为答案还在长出来（`done` 帧早就整段到了）；
   *  ② 这一条不是本次会话里看着它跑的（从列表点开的历史任务）—— 它的答案早就躺在
   *     库里，逐字敲出来是在演一场"正在生成"的戏。页面把两件事合成一个布尔传进来，
   *     理由与 `citationsOpen` 同源：状态得活得过本组件的卸载。 */
  revealed: boolean;
  onRevealed: () => void;
}

/** 揭示动画每帧最小间隔（ms）。他这一轮的原话是"按 requestAnimationFrame 或 50ms
 *  节流批量更新"，两个一起用：rAF 决定"什么时候允许画"，50ms 决定"多久真的画一次"。
 *  每字符一次 setState 会让 react-markdown 那棵树每秒重解析几十次（AnswerView 顶部
 *  那笔 11,000 节点的账就是这么来的），必须攒批。 */
const REVEAL_FRAME_MS = 50;

/** 最多播多少帧就见底 ⇒ 长答案自动加大步长，**不靠"播得久"营造流式感**。
 *  50ms × 30 帧 = 1.5s 封顶；再长的答案一帧要多吐若干字符。 */
const REVEAL_FRAMES = 30;

/** 答案的逐段揭示。`skip` 为真（已播过 / 用户要求减少动态）时**直接整段渲染**，
 *  一帧都不播 —— 这条不是装饰，是 `prefers-reduced-motion` 的硬要求。 */
function RevealedAnswer({
  text,
  skip,
  onDone,
}: {
  text: string;
  skip: boolean;
  onDone: () => void;
}) {
  const [shown, setShown] = useState(skip ? text : '');
  // onDone 每帧都是新引用（页面的 setState），用 ref 存才不会把动画 effect 打断重启
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  // "中途离开也算看过了"那颗延迟补记（对策见下面 effect 里那段 StrictMode 的说明）
  const pendingDone = useRef<number | null>(null);

  useEffect(() => {
    /* StrictMode 的假卸载会紧跟着再跑一次 effect —— 那枚"中途离开也算看过了"的
       补记时器就在这一次清掉。少了这一步，开发模式下**第一次挂载就被自己判成看过**：
       cleanup 立刻 onDone → 页面把这一条记进 revealedIds → skip 翻真 → 全文一次给出，
       打字机在 dev（也就是用户实际跑的那一份）里一次都不会出现。
       AF 趟实测过这个形状：24 次采样全等于全文长度。 */
    if (pendingDone.current !== null) {
      window.clearTimeout(pendingDone.current);
      pendingDone.current = null;
    }
    if (skip || !text) {
      setShown(text);
      return;
    }
    const step = Math.max(6, Math.ceil(text.length / REVEAL_FRAMES));
    let raf = 0;
    let taken = 0;
    let last = -Infinity;
    const tick = (now: number) => {
      if (now - last >= REVEAL_FRAME_MS) {
        last = now;
        taken = Math.min(text.length, taken + step);
        setShown(text.slice(0, taken));
        if (taken >= text.length) {
          doneRef.current();
          return;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    /* 中途真卸载（切页签、切任务）也记作"看过了"：回来时整段给出，不重来一遍。
       用 setTimeout(0) 而不是直接 onDone，就是上面那段 StrictMode 的对策。 */
    return () => {
      cancelAnimationFrame(raf);
      if (taken < text.length) pendingDone.current = window.setTimeout(() => doneRef.current(), 0);
    };
  }, [text, skip]);

  return <AnswerView text={shown} />;
}

/** 「运行结果」页签的全部内容。P1-01（报告 A4③）从 TaskLogPage 拆出来，为的是能
 *  **按需挂载**：调用点是 `{tab === 'result' ? <ResultPane …/> : null}`。
 *
 *  为什么拆组件而不是只加个三元：AntD 的 Tabs 激活过一次就把面板留在 DOM 里
 *  （切走只是隐藏），于是任务一跑完，那 11,000 个引用/工具节点从此常驻 ——
 *  页面任何一次无关重渲染都要把它们走一遍协调。实测 5,000 事件档切进结果页签
 *  要 150ms 左右（其中约 104ms 是浏览器布局与绘制，见 tools/uicheck/README.md）。
 *  卸载式挂载把这笔常驻账直接抹掉：不看不挂载，看时从零挂一次。
 *
 *  ⚠️ 卸载是有代价的：切回来要重新挂载一次（答案那棵 markdown 树要重解析）。
 *  对答案的 memo 护栏因此换了触发器 —— running.cjs 的 U 趟现在用「展开/收起引用」
 *  当无关重渲染源，不再用切页签（切页签已经会卸载组件，那个断言不再成立）。 */
/** `record.error` 那一条常驻提示。**两处**用同一个组件：结果已落定那一屏，与
 *  压根没载进来那一屏（下面 `!record.result` 那一支）。同一条信息不写两份样式，
 *  免得有一天只改了一颗（这一族的先例：模型面板里那颗同名按钮）。 */
function ErrorBanner({ error }: { error: NonNullable<TaskRecord['error']> }) {
  return (
    <div
      role="alert"
      style={{
        padding: '10px 12px',
        border: '1px solid var(--danger)',
        borderRadius: 'var(--r-sm)',
        background: 'var(--danger-soft)',
        color: 'var(--danger-fg)',
        fontSize: 12,
        lineHeight: 1.6,
      }}
    >
      <strong>{error.code}</strong>：{error.message}
    </div>
  );
}

export default function ResultPane({
  record,
  running,
  citationsOpen,
  onCitationsOpenChange,
  lastDoneNode,
  revealed,
  onRevealed,
}: ResultPaneProps) {
  // 探针插桩（running.cjs 的 V 趟）：证明"没激活就没有这一份渲染"，产品代码不读
  bumpRender('resultPane');
  const navigate = useNavigate();
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  // 结论摘录：机械提取答案里的结论段（找不到就退回首段并如实标注），不自己造句子
  const conclusion = useMemo(
    () => (record?.result?.finalAnswer ? pickConclusion(record.result.finalAnswer) : null),
    [record?.result?.finalAnswer],
  );

  if (!record?.result) {
    /* 三种"这一屏还没有答案"，说的话完全不同，必须分开：
       ① **载入失败**（`LOAD_FAILED`：手敲的坏 id、后端没起来）—— 这一条优先于运行态。
          不这么做的话占位 record 的 status 是 queued ⇒ `running` 为真 ⇒ 屏幕上写
          「Agent 正在思考...」，一句会让用户一直等下去的谎。页签调换之前他默认落在
          日志那一屏（那边 W 趟 ⑥ 早就把这句话钉住了），调换之后默认就落在这一屏，
          于是同一句真话必须在这里也说得出 —— 不是把那边改掉的那条搬过来凑数，
          是换了默认页之后**这一屏有了说假话的能力**。
       ② 跑动中 —— 三点 + 阶段文案（utils/runPhase.ts）。
       ③ 从来没有结果（新建那一屏）—— 静态引导。 */
    if (record?.error) {
      return (
        <div className="result-wrap stack" style={{ gap: 14 }}>
          <ErrorBanner error={record.error} />
          <p className="result-meta">
            这一屏没有可显示的东西：任务没载进来，不是它还没跑完。
            从左侧列表挑一条，或把地址栏里的 <code>task_id</code> 换成存在的 id。
          </p>
        </div>
      );
    }
    if (!running) {
      return (
        <EmptyState
          compact
          icon={<CheckCircleOutlined />}
          title="还没有运行结果"
          bullets={[
            '最终答案：Reviewer 通过的那一版输出',
            '引用来源：knowledge_search 命中的片段（逐条可复制）',
            '消耗明细：prompt 与 completion token 拆分',
          ]}
        />
      );
    }
    /* 跑动中：**阶段进度 + 流式答案 + 已用时 + 累计用量**（components/RunProgress.tsx）。
       以前这里只有「三点 + 一行阶段文案 + 一块静态空态」，而录屏实测那 12 秒里
       SSE 一帧都没有（executor 跑完才发 `node`）⇒ 用户在屏上读到的"正在跑"
       其实是一块一动不动的空态，跟卡死分不出来。
       ⚠️ 空态那三条引导bullet 在这一支里删掉了：它们描述的是**终态那屏会有什么**，
       而跑动中这一屏现在真的有内容在长出来，再说一遍"结果会逐段出现"是空话。 */
    return (
      <RunProgress
        lastDoneNode={lastDoneNode}
        startedAt={record?.createdAt}
        reduceMotion={reduceMotion}
      />
    );
  }

  const { result } = record;

  return (
    <div className="result-wrap stack" style={{ gap: 14 }}>
      <div className="row row--between">
        <span className="row" style={{ gap: 7 }}>
          <Chip mono outline title={record.taskId}>
            {truncate(record.taskId, 24)}
          </Chip>
          <CopyButton text={record.taskId} />
          <span className="fs-11 t3">{STATUS_LABELS[record.status]}</span>
        </span>
        {record.taskId !== '-' && (
          <Button
            size="small"
            type="text"
            icon={<HistoryOutlined />}
            onClick={() => navigate(`/trace?id=${encodeURIComponent(record.taskId)}`)}
          >
            在轨迹回放中打开
          </Button>
        )}
      </div>

      {record.error && <ErrorBanner error={record.error} />}

      {/* 指标前置：原来三块卡在页尾，要滑过整段答案才看得到消耗；
          挪到 task ID 下面，和上面的 runbar 是同一份真值。 */}
      <div className="metric-grid metric-grid--head">
        <MetricTile
          small
          label="总 token"
          value={fmtInt(result.usage.total)}
          hint={`入 ${fmtInt(result.usage.prompt)} / 出 ${fmtInt(result.usage.completion)}`}
          /* 用户实测两条同样的 `1+1` 消耗不同，第一反应是"是不是有 bug"。
             这句解释必须**当场在场**，而且不许退化成"属正常，别担心" ——
             文案与它的实测数字来源都在 `utils/costNote.ts`（轨迹页共用同一份，防两处漂）。
             探针 A 趟按内容断言：提到采样 + 提到计费时段 + 带数字的"实测"。 */
          title={TOKEN_VARIANCE_NOTE}
        />
        <MetricTile small label="耗时" value={fmtDuration(result.durationMs)} />
        {/* 迭代显示 0 看着像「没跑起来」，其实后端口径是**退回重跑次数**
            （reviewer 通过就不自增，见 core/agent/reviewer.py:74）——
            所以数字旁边必须带这一句，不然第一个反应是「出错了？」。 */}
        <MetricTile
          small
          label="迭代轮数"
          value={fmtInt(result.iterations)}
          hint={
            result.iterations === 0
              ? '首轮复核即通过 · 无退回重跑'
              : `Reviewer 退回重跑 ${result.iterations} 次`
          }
          title="这一格记的是「退回重跑次数」：Reviewer 通过即不自增，所以 0 是「一次通过」，不是没跑。"
        />
      </div>

      {/* 成本归因（C1–C7）。挂在消耗指标**之后**、答案之前：这一节回答的正是
          上面那格「总 token」被追问的那句话（同样的问题为什么钱差这么多）。
          enabled 绑终态（决策 D5）：运行中不拉 —— 半程合计会被当成成品账看，
          而且 `tasks.cost` 要到终态才落库，那时对账位只能报「不适用」。
          组件本身只在「运行结果」页签激活时才挂载，所以拉取天然按需。 */}
      <CostBreakdown taskId={record.taskId} enabled={!running} />

      {/* 摘要条：结论摘录；下面那行硬指标（状态 / 工具次数 / 引用段数）
          拆到条外单独一行 —— 混在紫块里读，会把「机械摘录」当成后端给的事实。 */}
      <div className="stack" style={{ gap: 7 }}>
        {/* ⚠️ 条件要包在**容器外面**。`.summary-callout` 自己带着底色、描边和 11/14 的内边距，
            把容器留在原地只把里面那枚 <p> 藏掉，画出来的就是一条 24px 高的空紫条（实测值）——
            2026-09-25 真实浏览器实测：答案短到 ``pickConclusion`` 认不出结论段时必然出现
            （本地库 6 条已完成任务里 4 条中招，全是 1+1 / 1024×768 这类一句话答案）。
            没有结论可说就整块不渲染；"为什么没有"仍由下面那行 .result-meta 说清楚。 */}
        {conclusion && (
          <div className="summary-callout">
            <p className="sc-main">
              <b>{conclusion.label}：</b>
              {conclusion.text}
            </p>
          </div>
        )}
        <p className="result-meta">
          <CheckCircleOutlined aria-hidden />
          <span>
            {STATUS_LABELS[record.status]} · 工具调用 {result.toolCalls.length} 次 · 命中引用{' '}
            {result.citations.length} 段
            {result.citations.length === 0 && '（未启用 RAG 或检索无命中）'}
            {conclusion ? '' : ' · 答案里没认出结论段，结论请看下方 Final Answer'}
          </span>
        </p>
      </div>

      {result.finalAnswer ? (
        <div className="stack" style={{ gap: 8 }}>
          <div className="sec-label sec-label--answer">
            Final Answer
            <span className="sec-label-zh">模型给出的最终答案原文</span>
            <CopyButton text={result.finalAnswer} />
          </div>
          {/* 数提交用的插桩与 memo 是一对（见 AnswerView 顶部与 U 趟）：
              没有这层 Profiler，"答案跟着无关重渲染一起重建"就只能靠肉眼。
              ⚠️ 它只**打印**不判定 —— 判定用 AnswerView 里那枚 render 自数：父级每重渲染
              一次，Profiler 自己就是一次 commit，memo 挡得住子组件、挡不住 Profiler。
              ⚠️ 揭示期间 AnswerView 的 text 每帧都在变 ⇒ 它必然重解析，memo 在这里不生效，
              这是"逐段出现"的固有代价，所以步长按答案长度放大、总时长封顶 1.5s（见上）。
              复制键给的是**全文**（上面那枚 CopyButton），不是揭示到一半的那截。 */}
          <Profiler id="answer" onRender={countCommit}>
            <RevealedAnswer
              /* 三种"直接给全文，不演打字机"：
                 ① 本条不是这次会话里看着跑的（历史任务）—— 见 `revealed` 的注释；
                 ② 已经播过一遍（切页签回来不该重来）；
                 ③ **刚刚已经一字一字看着它流式长出来了**（`liveAnswer.streamed()`）——
                    再逐字敲一遍是在演一遍"它正在生成"，而那一刻它早就生成完了。
                    这一条是流式输出上线之后才存在的：以前 `done` 之前屏上什么都没有，
                    逐段揭示是唯一能表达"到达过程"的手段；现在到达过程本身是真的了。 */
              text={result.finalAnswer}
              skip={revealed || reduceMotion || liveAnswer.streamed()}
              onDone={onRevealed}
            />
          </Profiler>
        </div>
      ) : (
        <EmptyState
          compact
          title="后端未回填 final_answer"
          desc="终态任务应当有答案；为空通常是被取消、收口或执行期异常。"
        />
      )}

      <div className="stack" style={{ gap: 10 }}>
        <div className="sec-label">引用来源（{result.citations.length}）</div>
        {result.citations.length === 0 ? (
          /* 空态不画虚线框：上面标题已经写了（0），这里只需要一句"为什么是 0"。
             一块带边框的空白把"什么都没有"撑成一个大区，反而更占注意力。 */
          <p className="cite-empty">本次无命中或未启用 RAG，引用为空</p>
        ) : (
          <>
            <Chip
              outline
              title="相关度不是后端单独给的字段，是从工具返回的引用行里读出来的；那一行形状对不上时这一格显示「—」，不补 0、不编名字。"
            >
              相关度取自工具返回的引用行 · 读不出显示「—」
            </Chip>
            {/* 默认只铺前 10 条：一次检索 4 条 × 多轮，长任务能堆到上千行。
                这不是为了省内存 —— 是 5,000 事件那一档实测切页签要 150ms，
                其中 104ms 是浏览器给这 1,000 行做布局与绘制（memo 治不了）。
                总数写在标题里，折叠不会让人少看到任何东西。
                已知代价：折叠把常驻 DOM 钉在 10 行，代价挪到了点「展开全部」
                那一下 —— 真实任务规模（100 行以内）实测 <200ms，
                极端 fixture（4,800 行）是 1.8s 量级，实测数与口径见
                tools/uicheck/README.md。 */}
            {(citationsOpen ? result.citations : result.citations.slice(0, CITATION_PREVIEW)).map(
              (c) => <CitationRow key={c.chunkId} c={c} />,
            )}
            {result.citations.length > CITATION_PREVIEW && (
              <button
                type="button"
                /* ⚠️ 第二个类名是给探针的：`.code-more` 这一族里还住着答案里那枚
                   「展开重复段 / 收起重复段」，它也在 `.result-wrap` 里、文案同样含「收起」。
                   想精确点引用列表那一枚而没有别的手段，所以给它一个自己的钩子。
                   （样式仍然只吃 `.code-more`，加类名不改任何外观。） */
                className="code-more cite-more"
                onClick={() => onCitationsOpenChange(!citationsOpen)}
                aria-expanded={citationsOpen}
              >
                {citationsOpen
                  ? '收起'
                  : `展开全部 ${result.citations.length.toLocaleString('zh-CN')} 条（当前显示前 ${
                      CITATION_PREVIEW
                    } 条）`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
