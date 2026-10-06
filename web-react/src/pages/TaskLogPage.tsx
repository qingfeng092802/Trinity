import {
  lazy,
  memo,
  Profiler,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ProfilerOnRenderCallback,
  type ReactNode,
} from 'react';
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Switch,
  Tabs,
  Tooltip,
} from 'antd';
import type { TextAreaRef } from 'antd/es/input/TextArea';
import {
  CodeOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  InfoCircleOutlined,
  MenuOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons';

import {
  type CancelAck,
  cancelTask,
  describeFetchError,
  fetchTask,
  fetchTaskList,
  fetchTrace,
  isCancelRejected,
  submitTask,
  subscribeTaskStream,
  type StreamState,
} from '../api/client';
import JsonView from '../components/JsonView';
import CodeBlock from '../components/CodeBlock';
import LogStream from '../components/LogStream';
import ResultPane from '../components/ResultPane';
import { liveAnswer } from '../utils/liveAnswer';
import RunBar from '../components/RunBar';
import { withPaneBoundary } from '../components/paneBoundary';
import TaskListPanel from '../components/TaskListPanel';

/** 运行配置面板：**懒加载**。弹层内容是点开才挂的，而绝大多数提交根本不打开它 ——
 *  直接 import 会把 Tabs / Select / Checkbox 与那一整块逻辑压进入口 chunk。
 *  与顶栏那个模型设置面板同一套做法（``AppShell`` 的 ``ModelSettingsEntry``）。 */
const RunConfigPanel = lazy(() => import('../components/RunConfigPanel'));
import {
  Chip,
  CopyButton,
  EmptyState,
  PageHeader,
  ToolBadge,
} from '../components/ui';
import { useRefresh } from '../hooks/useRefresh';
import { useLogBuffer } from '../hooks/useLogBuffer';
import { useTasklist } from '../hooks/useTasklist';
import { useIsMid, useIsNarrow } from '../hooks/useMediaQuery';
import { useModels } from '../hooks/useModels';
import { defaultOf, fieldReadingsOf, unitOf, useAgentOptions } from '../hooks/useAgentOptions';
import {
  buildRunConfigBody,
  deriveRagOn,
  echoDiffLines,
  useRunConfig,
} from '../hooks/useRunConfig';
import { modelChipText, modelTooltipLines } from '../utils/modelLabel';
import { STATUS_META } from '../theme';
import {
  type AgentNode,
  type LogEvent,
  type LogLevel,
  type TaskDetail,
  type TaskPhase,
  type TaskRecord,
  type TaskResult,
  type TaskStatus,
  type TaskSubmitForm,
  type ToolCall,
  type ToolSpecView,
  type TraceEvent,
} from '../types';
import { fmtDuration } from '../utils/format';
import { bumpCommit, bumpRender } from '../utils/renderLedger';
import { buildCitations } from '../utils/citations';
import { collapseRepeats } from '../utils/logRows';
import { argMetaOf, codeArgOf, fieldsStack, intentSub, intentTitle, toolOutcome, tooltipLines } from '../utils/toolMeta';
import { useToolSpecs } from '../hooks/useToolSpecs';
import { useNavigate, useSearchParams } from 'react-router-dom';

/** 「在看哪条任务」的 URL 参数名。
 *
 *  ⚠️ 与回放页的 `?id=` **故意不同名**（`TraceReplayPage.tsx:156`）：那边选中的是**轨迹**，
 *  这边选中的是**任务**，两页共用一个字面 `id` 看上去整齐，实际是把两种语义糊成一个 ——
 *  将来有人"顺手统一"就会让 /trace 的链接参数指向一个不再存在的含义。想统一先看这句。 */
const TASK_ID_PARAM = 'task_id';

const LEVEL_OPTIONS: Array<{ label: string; value: LogLevel }> = [
  { label: 'DEBUG 及以上', value: 'debug' },
  { label: 'INFO 及以上', value: 'info' },
  { label: 'WARN 及以上', value: 'warn' },
  { label: '仅 ERROR', value: 'error' },
];

const LEVEL_RANK: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3 };

/** 页签 → 兜底文案里的位置名（用户报障时能说清是哪一块塌了）。 */
const TAB_LABELS: Record<string, string> = {
  log: '实时日志',
  result: '运行结果',
  tools: '工具调用',
};

/** 页签项的最小结构。`label` 在 AntD 的 Tab 里是必填，所以包边界时要原样带过去
 *  （早先用 `typeof tab` 当返回类型，把 label 抹掉了，tsc 当场拦住）。
 */
type TabPane = { key: string; label: ReactNode; children: ReactNode };

/** 给每个页签的内容单独包一层错误边界。
 *
 *  一个页签渲染抛错时只塌这一页签：页签栏和另外两个照常可用。
 *  不包的话 React 会连整棵外壳一起卸载 —— 就是之前那次白屏。
 *
 *  ⚠️ 边界本体在 ``components/paneBoundary``（全站一份，U-7 要的是"复用"不是"抄同一份写法"）。
 *  这里只留"把 key 翻成给用户看的位置名"这一层 —— 位置名是这个文件的知识（日志/结果/工具），
 *  不是边界自己的。
 */
function withTabBoundary(pane: TabPane): TabPane {
  return { ...pane, children: withPaneBoundary(TAB_LABELS[pane.key] ?? pane.key, pane.children) };
}

/** 一条工具调用 = 一张卡。
 *
 *  memo 的理由是量出来的，不是习惯使然：5,000 行那一档整页 11,875 个元素里，
 *  `span.row` 1,001 + `.copy-btn` 1,002 + `.chip` 1,002 全出自这块列表，
 *  而切页签时 `t` 和 `spec` 的引用都不变（`t` 来自已落定的 `record.result.toolCalls`，
 *  `spec` 来自 `useToolSpecs` 那个只在取回时替换一次的 Map）—— 整段重渲染纯属白算。
 *  所以派生计算（outcome / 意图标题 / 入参提炼 / tooltip 行）全部搬进组件内部：
 *  只把 JSX 包一层 memo 而把计算留在外面，函数该算的还是算了。 */
const ToolCard = memo(function ToolCard({
  t,
  spec,
}: {
  t: ToolCall;
  spec: ToolSpecView | undefined;
}) {
  const why = intentSub(t.name, t.args, t.thought);
  const outcome = toolOutcome(t.status);
  /* 源码入参走代码块，其余仍走 JSON 树：前者要的是缩进和换行，
     后者要的是键名和层级，两种需求凑不到一个渲染器里。 */
  const code = codeArgOf(t.name, t.args);
  const meta = argMetaOf(t.name, t.args);
  const cardCls =
    outcome.tone === 'error' ? ' is-failed' : outcome.tone === 'warn' ? ' is-warn' : '';
  const tipLines = tooltipLines(t.name, spec);
  return (
    <div className={`tool-card${cardCls}`}>
      <div className="row row--nowrap" style={{ gap: 8 }}>
        <Tooltip
          trigger={['hover', 'focus']}
          title={
            <div className="stack" style={{ gap: 4 }}>
              {tipLines.map((line, i) => (
                <span key={i} className={i === 2 ? 'tt-note' : undefined}>
                  {line}
                </span>
              ))}
            </div>
          }
        >
          {/* 可聚焦：只靠 hover 的 Tooltip 键盘用户永远看不到 */}
          <span className="tool-name" tabIndex={0}>
            <Chip mono tone={{ fg: 'var(--primary-soft-fg)', soft: 'var(--primary-soft)' }}>
              {t.name}
            </Chip>
            <InfoCircleOutlined className="tool-help" aria-hidden />
          </span>
        </Tooltip>
        <ToolBadge outcome={outcome} />
        <span className="t3 fs-11 tabular tool-when">{fmtDuration(t.durationMs)}</span>
      </div>

      {/* 意图标题：执行器自己写的 thought 优先，没有就退回「动词：关键入参」。
          两条都是真实数据，前端不替模型编一句「为了算总功耗」。 */}
      <p className="tool-intent">{intentTitle(t.name, t.args, t.thought)}</p>
      {why && <p className="tool-why">{why}</p>}

      <div className={fieldsStack(t.name) ? 'grid-2 is-stack' : 'grid-2'}>
        <div className="field">
          <div className="field-head">
            <span className="field-label">入参</span>
            {meta && <span className="arg-meta tabular">{meta}</span>}
            {/* 复制的内容跟显示的内容一致：屏上是干净源码，复制到的就是源码 */}
            <CopyButton text={code ?? t.args} />
          </div>
          {code !== null ? <CodeBlock code={code} /> : <JsonView text={t.args} />}
        </div>
        <div className="field">
          <div className="field-head">
            <span className="field-label">出参</span>
            <CopyButton text={t.result} />
          </div>
          {/* 只有出参块标异常：入参是模型/用户给的东西，它没做错
              什么，跟着变红只会把责任指错地方。 */}
          <JsonView text={t.result} error={outcome.bad} />
        </div>
      </div>
    </div>
  );
});

/** 快捷示例：点一下填入，不自动提交 —— 用户仍然拥有「发出去」这一步。 */
const QUICK_EXAMPLES = [
  {
    label: '知识库检索',
    icon: <DatabaseOutlined />,
    task: '用三句话说明 RAG 的检索增强原理，并指出结论来自哪份文档的哪一段。',
  },
  {
    label: '数值计算',
    icon: <ExperimentOutlined />,
    task: '1024 路摄像头整机功耗怎么估算？请给出算式、代入过程与最终结果。',
  },
  {
    label: '结论对比',
    icon: <CodeOutlined />,
    task: '对比 BM25 与向量检索在中文技术文档场景下的适用边界，各给一个例子。',
  },
];

/* ---------------- 轨迹 → 结果区的展示级映射（不反序列化后重算） ---------------- */

function buildToolCalls(trace: TraceEvent[]): ToolCall[] {
  return trace
    .filter((e) => !!e.tool_name && e.event_type !== 'running')
    .map((e) => ({
      id: String(e.event_seq),
      name: e.tool_name as string,
      args: e.arguments ?? '',
      result: e.observation ?? '',
      durationMs: e.latency_ms ?? 0,
      /* 三档如实透传。旧写法是 `e.status === 'failed' ? 'failed' : 'success'`，
         等于把后端的 timeout 折成绿色成功 —— 出参里明写「执行超时，进程已被强制终止」
         用户仍看到「成功」。降级与文案口径统一收在 toolOutcome()。 */
      status: e.status === 'failed' || e.status === 'timeout' ? e.status : 'success',
      thought: e.thought ?? null,
    }));
}

/* 引用列表的构建搬到了 utils/citations.ts —— 那里是能不进浏览器、用 node 直接断言的
   纯函数（tools/uicheck/citations.test.cjs）。留在这个文件里就测不到「认不出就 —」
   这条口径，而它正是上一版写死假文档名的地方。 */

function applyDetail(prev: TaskRecord, detail: TaskDetail, trace: TraceEvent[]): TaskRecord {
  const tokensIn = trace.reduce((s, e) => s + (e.tokens_in ?? 0), 0);
  const tokensOut = trace.reduce((s, e) => s + (e.tokens_out ?? 0), 0);
  const result: TaskResult = {
    finalAnswer: detail.final_answer ?? '',
    citations: buildCitations(trace),
    toolCalls: buildToolCalls(trace),
    usage: { prompt: tokensIn, completion: tokensOut, total: tokensIn + tokensOut },
    durationMs: detail.duration_ms ?? 0,
    iterations: detail.iterations ?? 0,
  };
  return {
    ...prev,
    task: detail.task || prev.task,
    status: detail.status,
    createdAt: Date.parse(detail.created_at) || prev.createdAt,
    progress: undefined,
    result,
    error: detail.error ? { code: detail.status.toUpperCase(), message: detail.error } : undefined,
  };
}

/** 轨迹回放里没有内容载荷的那几类事件，event_type 直接当消息会露出 'running'
 *  这种后端词。翻成固定句子有两个作用：读得懂，且**文本恒定** ——
 *  连续心跳才能被 logRows 合并成一行（SSE 侧的同一口径在 api/client.ts）。 */
const EVENT_TEXT: Record<string, string> = {
  running: '等待节点事件',
  node_end: '节点收尾',
  llm_call: '模型调用',
};

/** 历史任务没有 SSE 可订阅 —— 用轨迹事件还原一份日志，口径与实时流对齐。
 *  level 由事件状态推：**失败即 error**，running 心跳归 debug，其余 info。 */
function traceToLogEvents(trace: TraceEvent[]): LogEvent[] {
  return trace.map((e) => {
    const level: LogLevel =
      e.status === 'failed' ? 'error' : e.event_type === 'running' ? 'debug' : 'info';
    const node = (e.node ?? (e.role as AgentNode) ?? 'system') as AgentNode;
    const message =
      (e.thought ?? '').trim() ||
      (e.tool_name
        ? `${e.tool_name}${e.observation ? ` → ${e.observation.slice(0, 120)}` : ''}`
        : '') ||
      (e.error_message ? `${e.error_code ?? 'ERROR'}：${e.error_message}` : '') ||
      EVENT_TEXT[e.event_type] ||
      e.event_type;
    return {
      seq: e.event_seq,
      ts: Date.parse(e.created_at) || Date.now(),
      level,
      node,
      message,
    };
  });
}

/* 模型展示名的措辞全在 utils/modelLabel.ts（纯函数，断言在 tools/uicheck/modelLabel.test.cjs）。
   这里不留 MODEL_LABELS 之类的字典：页面自带一份模型清单就是上一版那颗假下拉的病根。 */

/** 日志面板那棵子树的**提交**计数（探针 M 趟用）。账本与两枚计数的区别都写在
 *  utils/renderLedger.ts —— 一句话版：Profiler 数的是"这块落没落地"，
 *  要判 memo 挡没挡住得数组件函数体（`bumpRender`），别拿提交数当判据。
 *  生产构建里 React 根本不调 onRender（只有 dev / profiling 版回调），所以这层插桩
 *  不会带进 dist；探针跑在 5173 的 dev 构建上。
 *
 *  ⚠️ 计数器同时被 M 趟用作**反证**：先确认"改了关键字一定数得到"，再断言
 *  "无关的父级重渲染数不到"。少了前一步，计数器坏掉时后一条恒真。 */
const countLogStreamCommit: ProfilerOnRenderCallback = (id, _phase, actualDuration) =>
  bumpCommit(id, actualDuration);

/** 页面 ①：任务与日志（三栏）。
 *
 * 布局：第二栏「任务列表」负责选任务，主区「新建流 → 状态条 → 页签内容区」负责干活。
 * 数据流沿用既有实现：POST /tasks → SSE 增量 → 终态补拉 /tasks/{id} 与 /tasks/{id}/trace。
 * 诚实口径：**未知一律显示「—」**（token / 迭代轮数在运行中后端未给就不补 0）。
 */
export default function TaskLogPage() {
  /* 探针插桩（running.cjs 的 V 趟）：**整页**函数体跑了几遍。这一枚就是 P1-01 的判据本体
     —— 秒表一跳整页就得重算，是它当年的病；现在 1Hz 关在 Elapsed 里，运行中静置两秒多，
     `page` 一次都不许涨。生产构建里没人读它，与 utils/renderLedger.ts 同一套。 */
  bumpRender('page');
  const [form] = Form.useForm<TaskSubmitForm>();
  const navigate = useNavigate();
  const isCompact = useIsMid();
  /** ≤768：日志控件从页签栏的 extra 位挪进面板顶行。页签栏那一行不换行
   *  （AntD 的 `.ant-tabs-nav-list` 是横向滚动），411px 宽的控件组在 390 视口下
   *  会把整篇文档撑到 545 —— 由 running.cjs 的 J 趟钉住。 */
  const isNarrow = useIsNarrow();
  const { token: refreshToken } = useRefresh();
  const { message } = App.useApp();
  const { collapsed: listCollapsed } = useTasklist();

  const [record, setRecord] = useState<TaskRecord | null>(null);
  /* ---------- 选中态落到 URL（W 趟，报告 A6 那一族：现场只活在组件内存里） ----------
     两份账必须分清，不然会写出"每刷一次列表就把当前任务重选一遍"的 bug：
       · `urlTaskId`   = **谁被选中**（真值在地址栏，刷新 / Edge 丢标签 / 手敲都还在）
       · `loadedIdRef` = **谁已经在这一屏上**（写入点自己先把账记上，跟随 effect 才不会重复加载）
     两者不等才加载。分工照 `TraceReplayPage.tsx:169-178` —— 那边当年就是因为只比 state
     （同一批更新里 state 可能已被改写）导致"点了别的任务页面不动"，守卫对象才换成 ref。 */
  const [sp, setSp] = useSearchParams();
  const urlTaskId = sp.get(TASK_ID_PARAM) ?? '';
  const loadedIdRef = useRef('');
  // 实时日志的行缓冲：攒批 + 封顶都在 useLogBuffer 里（原来每条 SSE 一次 setState）
  const {
    events,
    dropped,
    replace: replaceEvents,
    push: pushEvent,
  } = useLogBuffer();
  const [autoScroll, setAutoScroll] = useState(true);
  /** 传输层状态那一行（不是任务状态）。null = 连接正常，什么都不说。 */
  const [streamNote, setStreamNote] = useState<string | null>(null);
  const [levelFilter, setLevelFilter] = useState<LogLevel>('debug');
  const [keyword, setKeyword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [canceling, setCanceling] = useState(false);
  /** 取消回执（Q3-01）。null = 这一屏没有"刚取消过一次"这件事要说。
   *
   *  为什么要把后端那句 `mode` 存下来而不是就地拼进 toast：toast 三秒就没了，而
   *  "取消位已置"这件事在整个节点跑完之前都成立 —— 一次性的提示等于没说过
   *  （与上面那条回执核对同一个理由）。
   *  带 `taskId`：切到别的任务之后这条回执就不属于屏幕上这一条了，不许留着。 */
  const [cancelAck, setCancelAck] = useState<{ taskId: string; ack: CancelAck } | null>(null);
  const [history, setHistory] = useState<TaskRecord[]>([]);
  const [cfgOpen, setCfgOpen] = useState(false);
  const [justCreated, setJustCreated] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  /** 默认落在「运行结果」，页签顺序也是 结果 → 实时日志 → 工具调用。
   *  ⚠️ 这一处与下面三个 `setTab('result')` 是一件事：以前默认与切任务都落在日志，
   *  于是"提交完先看什么"答案是终端 —— 而绝大多数人先看的是答案本身。
   *  日志没有降级：它仍然是第二页签，且提交**失败**时仍然会自动切过去（见 submit 的 catch）。 */
  const [tab, setTab] = useState<'log' | 'result' | 'tools'>('result');
  /** 答案已经逐段揭示过的任务 id。放在页面而不是 ResultPane 里，理由与 `citationsOpen`
   *  完全一样：那个组件切走页签就卸载，状态放里面等于每次回来重播一遍打字机。 */
  const [revealedIds, setRevealedIds] = useState<Set<string>>(() => new Set());
  const markRevealed = useCallback((id: string) => {
    setRevealedIds((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }, []);
  /* 本次会话里**亲眼看着它跑过**的任务 id。打字机只给这一批放。
     理由不是性能，是真假：从列表里点开一条历史任务时，答案早就躺在库里了，逐字敲出来
     是在演一场"它正在生成"的戏 —— 这一屏不许演这个（同一族的先例：消耗明细不编数、
     相关度读不出显示「—」）。刚提交完那条不一样：那一刻答案确实还没到，逐段出现
     就是它真实的到达过程。
     ⚠️ 用 Set 而不是单个 id：跑完一条之后接着点回另一条刚跑完的，也不该重播。 */
  const [liveIds, setLiveIds] = useState<Set<string>>(() => new Set());
  const markLive = useCallback((id: string) => {
    setLiveIds((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }, []);
  /** 引用列表默认折叠到前若干条（实测理由见 components/ResultPane.tsx 的 CitationRow）。
   *  切任务时**不**重置：这是用户的阅读偏好，不是这个任务的状态。
   *  ⚠️ 也**不能**放进 ResultPane：那个组件切走页签就卸载，状态放里面等于每次回来都
   *  被重置成折叠 —— 用户刚展开看完一半，切去看日志再切回来就没了。 */
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);

  const stopRef = useRef<(() => void) | null>(null);
  const taskInputRef = useRef<TextAreaRef | null>(null);

  /* ---------- 运行配置：唯一宿主是 RunConfigProvider（U-5）----------
     ⚠️ 原来上面那几行是 `Form.useWatch('maxIterations', form) ?? 3` 加两颗住在 Form 里的开关。
     那个 ``?? 3`` 是前端把"3"写下的第四个地方，而后端默认是 **5** ⇒ 右下角那行读数一直在
     替用户编一个没人说过的数字；而 Form 那份状态要靠"控件挂载过"才存在（弹层懒挂），
     于是有了"没点开弹层 ⇒ 字段没注册 ⇒ 请求体少键"这一族坑（详见 composer-foot 那段注释）。
     现在的口径：用户说过话就用他那份；没说就用**响应给的**默认；响应也没给就**不报数**
     （``iterationsShown`` 为 null 时那行读数整条消失，而不是显示一个猜的数）。 */
  const options = useAgentOptions();
  const { draft, disabledTools, setUseTools, setToolEnabled, reset: resetRunConfig } = useRunConfig();
  /** 工具注册表：既给工具卡片兜底，也是"取消勾选后要发完整白名单"的那份**全量清单**。
   *  上移到这一段是因为 handleSubmit 要用它算 ``enabled_tools``。
   *  ⚠️ 与 ``RunConfigPanel`` 里的 ``ToolRows`` 是同一个 hook、同一份模块级合流请求，
   *  不是第二份清单（判据：AD 趟比的是"面板勾的"与"开关算出来的"落在同一个 body）。 */
  const toolSpecs = useToolSpecs();
  const toolNames = useMemo(() => [...toolSpecs.keys()], [toolSpecs]);
  /** 「RAG」快捷开关管的是哪个工具，由后端说（``tools.rag_tool``）；
   *  不知道 ⇒ ``null`` ⇒ 开关置灰并说明原因，而不是拿一份猜的名字去算白名单。 */
  const ragTool = options?.tools?.rag_tool ?? null;
  const ragOn = deriveRagOn(ragTool, disabledTools);
  /** 开关置灰的**原因**（三种都各自独立：拿不到配置 / 后端没报名字 / 拿不到清单）。
   *  为什么不能只是 disabled：上一版的教训是"控件看着能动、实际什么都没发"，
   *  而"看着灰掉了、也没说为什么"只是把同一个谎换成更难查的形状。 */
  const ragDisabledReason = !options
    ? '还没读到 GET /config/agent-options，这一屏只发任务文本'
    : !ragTool
      ? '后端没声明哪个工具负责知识库检索（tools.rag_tool 缺席或该工具未注册）'
      : !toolNames.length
        ? '还没读到 GET /tools 的清单，算不出完整白名单'
        : null;
  /** 工具开关的**读数**：没表达过意见时显示后端默认（默认值来自响应，不是这里的 ``true``）。
   *  ``true`` 这个兜底只在"响应还没到"的瞬间存在 —— 那时请求体也什么都没发，两者同值。 */
  const defaultUseTools = defaultOf(options, 'use_tools');
  const useToolsShown =
    draft.use_tools ?? (typeof defaultUseTools === 'boolean' ? defaultUseTools : true);
  const defaultIterations = defaultOf(options, 'max_iterations');
  const iterationsShown =
    draft.max_iterations ?? (typeof defaultIterations === 'number' ? defaultIterations : null);
  /** 那行读数的单位也来自响应（``fields[].unit``）。后端没说就不写后缀 ——
   *  写死"轮"就是在这处又埋一份前端字段表，与刚删掉的 ``CONFIG_LABELS`` 同病。 */
  const iterationsUnit = unitOf(options, 'max_iterations');
  /** 模型注册表（``GET /models``）。这一栏是**读数**不是控件 ——
   *  拉不到就整条不渲染，绝不回落到一份写死的清单。 */
  const models = useModels();
  const modelChip = modelChipText(models);

  const refreshHistory = useCallback(async () => {
    try {
      const body = await fetchTaskList(30);
      setHistory(
        body.items.map((t) => ({
          taskId: t.task_id,
          task: t.task,
          status: t.status,
          createdAt: Date.parse(t.created_at) || Date.now(),
          // 列表接口本来就返回这三个字段，之前映射时丢掉了；任务列表要靠它们做信息密度。
          // 都是 null 安全的：未完成的任务后端给 null，交给展示层按缺值处理。
          cost: t.cost ?? null,
          toolCalls: t.tool_calls ?? null,
          durationMs: t.duration_ms ?? null,
        })),
      );
    } catch {
      // 列表拉不到不影响主流程：留空即可，不弹错打断用户
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  /** SSE 阶段 → 任务状态。
   *
   *  修的是一个真实 bug：POST /tasks 返回时任务还在**排队**，而 record.status 只有
   *  在流关闭、补拉详情后才更新 —— 实测任务已经跑到 Reviewer 复核了，状态条还
   *  显示「排队中」，整整卡了 25s+。现在阶段一变就更新，终态仍以详情为准覆盖。
   */
  const phaseRef = useRef<string>('');
  const handlePhase = useCallback(
    (phase: TaskPhase) => {
      setRecord((prev) => {
        if (!prev) return prev;
        // 终态已由 applyDetail 用真实详情落定，不再被阶段回调改写
        if (STATUS_META[prev.status].terminal) return prev;
        const next: TaskStatus = phase === 'running' ? 'running' : phase;
        return prev.status === next ? prev : { ...prev, status: next };
      });
      // 列表同步：只在「排队 → 执行」这一次转换刷，避免每个 SSE 帧都打一次接口
      if (phaseRef.current !== phase) {
        phaseRef.current = phase;
        if (phase === 'running') void refreshHistory();
      }
    },
    [refreshHistory],
  );

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory, refreshToken]);

  // 计时器：只在运行态走，终态即停（状态口径读 STATUS_META，不在组件里写死状态名）
  const running = !!record && !STATUS_META[record.status].terminal;

  /* 「这一条是我看着它跑完的」记一笔 —— 打字机只给这一批放（判据与理由见 liveIds 那段）。
     写在 effect 里而不是 render 里：渲染期 setState 会当场再排一次渲染。 */
  const liveId = record?.taskId;
  useEffect(() => {
    if (running && liveId) markLive(liveId);
  }, [running, liveId, markLive]);

  /* ---------- 浏览器标签栏上那枚 ●（P1-06 / 报告 B8） ----------
     为什么只有这一个信号算数：用户切走之后，页面里那些"运行中 / 实时推送中"的字**全都看不见**
     （在另一个标签页里），而后台任务最要命的恰恰是"我切走了，它到底还在不在跑"。
     标题栏是这一屏唯一在页面外还读得到的读数，所以它必须跟着状态走。
     刻意**不塞任务名**：`truncate` 出来的半句话会把"这是哪条任务"说成假话，而 ● 这个字符
     什么都没说错。基线在挂载时从 `document.title` 现取（即 index.html 那句），**不写死字面量** ——
     将来谁改 index.html 的标题，不必回来改这里第二份。
     ⚠️ 只在 running 翻转时写：每次渲染都赋同一个串会不断惊动浏览器改标题（也打断读屏）。 */
  const titleBaseRef = useRef<string | null>(null);
  useEffect(() => {
    if (titleBaseRef.current === null) titleBaseRef.current = document.title;
    const base = titleBaseRef.current;
    const next = running ? `● ${base}` : base;
    if (document.title !== next) document.title = next;
  }, [running]);
  // 离开这一屏要把点摘掉：停在 /eval 页上还挂着「● Trinity · …」是谎报
  useEffect(
    () => () => {
      if (titleBaseRef.current !== null) document.title = titleBaseRef.current;
    },
    [],
  );
  /* 墙上时间不再由页面持有（P1-01，报告 A4②）。旧写法在这里放一个 `useState(now)` +
     1Hz setInterval，然后在下面各处算 `elapsedMs` / `logStale` —— 后果是**整页每秒重渲染
     一次**：日志面板（虚拟列表 + 逐行测量）、结果页的整棵 markdown 树、工具卡，全都陪着
     一枚秒表跳。现在计时器关进 components/Elapsed.tsx，只有真正显示秒数的那两截页脚在跳。
     起点仍用后端 created_at（提交即落库），口径与旧版逐字相同。 */

  /** 最后一条「有内容」日志的时间戳；整批都是心跳帧时返回 null。
   *  倒着扫，一般第一两条就退出 —— 心跳连续 30 条也才 30 次比较。 */
  const lastLogTs = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (events[i].idleMs === undefined) return events[i].ts;
    }
    return null;
  }, [events]);

  /** 已经交过卷的最后一个**编排节点**（结果页签那行"正在跑什么"由它推出来）。
   *  只认真节点：心跳帧与本地塞进去的 `system` 行（提交失败那类）都不算交卷，
   *  把它们当阶段会让加载文案在"根本没跑起来"的时候报出具体阶段。
   *  ⚠️ 后端的 `node` 帧是**该节点已完成**才发的（`api/queue.py` 从 `runner.stream()`
   *  拿到增量之后才 publish），所以这里给的是"上一个完成的"，措辞说的是它的后继 ——
   *  整套推理与图的边都在 `utils/runPhase.ts` 里，判定在 `runPhase.test.cjs`。 */
  const lastDoneNode = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const node = events[i].node;
      if (node === 'planner' || node === 'executor' || node === 'reviewer') return node;
    }
    return null;
  }, [events]);

  // 卸载时断开 SSE，否则长连接泄漏
  useEffect(() => () => stopRef.current?.(), []);

  /** 这一屏还活着吗（Q4-01）。`useRef(true)` + 卸载置 false，给**跨过 await 之后**的续段用。
   *
   *  为什么 :591 那条拆解挡不住这件事：它只关"卸载那一刻已经存在的句柄"。而 selectTask
   *  在 `await Promise.all([...])` **之后**才开订阅 —— 用户点了任务立刻切走时，卸载跑完了、
   *  await 才落地，于是这一行开出一条**此后没人再关**的 `/sse` 连接（活到标签页关闭），
   *  并且 `setRecord` / `replaceEvents` 会往已卸载的组件里写 state。
   *  ⚠️ 只在这一条路上成立，别把 :970 那道 reqId 闸当替代品：号对得上不代表屏还在。
   *
   *  ⚠️ **effect 体里那句置 `true` 不能省**（dev 实测：省掉它整页就废了）。
   *  React 18 `StrictMode`（`main.tsx:57`）会把「挂载 → effect → 清理 → 再 effect」走两遍，
   *  而这个模拟重挂**不重建 state 也不重建 ref 对象** —— 只写 cleanup 的写法在第一遍清理时
   *  把 `current` 落成 false，第二遍 effect 无人把它抬回来，于是 `useRef(true)` 的初值骗过了
   *  类型检查、tsc 也 0 错，屏上却是「详情和 trace 都 200 回来了、record 永远停在（载入中）
   *  排队中、日志 0 行、SSE 一声不吭地不订」。生产构建没有双跑 ⇒ 这一条只在 dev 复现，
   *  也正因为它只在 dev 复现，写下来：守卫要写成「setup 置真 + cleanup 置假」这一对。 */
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const filtered = useMemo(
    () => {
      const kw = keyword.trim().toLowerCase();
      return events.filter(
        (e) =>
          LEVEL_RANK[e.level] >= LEVEL_RANK[levelFilter] &&
          (kw === '' || e.message.toLowerCase().includes(kw)),
      );
    },
    [events, levelFilter, keyword],
  );

  /** 相邻且同文本的行合并后的展示行（心跳这类）。页签计数与面板必须读同一个数，
   *  否则会出现「页签写 39、面板只有 9 行」这种看着像丢日志的怪事。 */
  const logRows = useMemo(() => collapseRepeats(filtered), [filtered]);

  /** 代际守卫：每次"选任务 / 补拉详情"领一个号，回来时对不上号就直接丢掉。
   *
   *  为什么必须有：详情 + 轨迹是两个请求，而轨迹是**串行分页**的
   *  （`api/client.ts` 最多 10 页 × 50 条，逐页 await）—— 慢的那条要走满 10 个 RTT，
   *  竞态窗口不是理论风险。没有这层的话，先点 A、立刻点 B，A 的响应后到就会把
   *  **A 的答案盖在 B 的任务上**：界面不报错、不闪烁，只是内容不对，用户极难察觉。
   *  见 running.cjs 的 N 趟（慢 A 快 B 的对撞用例）。
   *
   *  为什么不用 AbortController：能省下行列，但 `getJson` 这一层没接 signal，
   *  改它要动整条 API 层；而这里要的语义只是"迟到结果不许落地"，号就够了。 */
  const reqIdRef = useRef(0);

  /** 断口对账。**SSE 不会重发断流期间的事件** —— 后端的 `seq` 每条连接各自从 0 起算
   *  （`api/routes/tasks.py` 的 `generate()` 里 `seq = 0`，帧里没有全局 `event_seq`），
   *  浏览器重连游标在这个后端是坏的 ⇒ 增量补拉（`/trace?after_seq=`）没有可用的游标，
   *  只能整包替换。可以整包替换的依据是后端契约：事件**先同步落盘再发布**
   *  （`api/queue.py` 的 `_record_event`：「调用顺序：必须早于同源的 `_publish(...)`」）
   *  ⇒ trace 永远是实时流的超集，替换不会抹掉用户已经看到的行。
   *  ⚠️ 代价：trace 里的行没有 `running_ms`（那是心跳帧独有的字段），
   *  所以合并行的尾巴会从「订阅后 45.0s」退回「已重复 N 次」—— 两个都是真口径，
   *  一个是本次订阅起算、一个是任务起算，谁也不许冒充谁（见 `api/client.ts` 同段注释）。 */
  const resyncTrace = useCallback(
    async (taskId: string) => {
      const myReq = reqIdRef.current;
      try {
        const trace = await fetchTrace(taskId);
        if (reqIdRef.current !== myReq) return; // 期间已经切走：不许拿别人的账盖这一屏
        replaceEvents(traceToLogEvents(trace.items));
      } catch {
        /* 对账失败不再叠一条红字：连接状态那行文案已经说了实话，
           这里再报只会把"接不上"升级成"页面坏了"的错觉。 */
      }
    },
    [replaceEvents],
  );

  /** 传输层状态回调。**只改"连接怎么样"这一行，绝不改任务状态** ——
   *  任务是否还在跑由补拉详情去确定；把断流写成"已结束"是这一条缺陷的本体。
   *
   *  对账只在 `restored` / `failed` 两个点做，`lost` 时**不拉**：
   *  刚断的那一刻，断口之后的事件后端还没来得及落库，补拉回来的一定是
   *  "屏幕上已有的一份" —— 白跑一个 RTT；而退避三次全接不上时，
   *  每次 `lost` 都拉一次就变成「4 次断线 × 10 页串行分页」的踩踏，
   *  打的是一个本来就正在抖的后端。隔了一整个退避周期之后再拉才有意义。 */
  const streamHandler = useCallback(
    (taskId: string) => (state: StreamState) => {
      if (state === 'restored') {
        setStreamNote(null);
        void resyncTrace(taskId); // 断口那几帧这时才在库里
        return;
      }
      if (state === 'lost') {
        setStreamNote('实时连接中断，正在重连（任务可能仍在运行）');
        return;
      }
      setStreamNote('自动重连 3 次未成功，实时日志已停 —— 任务可能仍在运行；重新选中该任务可续上');
      void resyncTrace(taskId); // 认输之前把已有的一整份账落下来，别再留半截
    },
    [resyncTrace],
  );

  /** 关掉当前这条 SSE，并把句柄记账清干净。
   *
   *  单独抽一个函数有两层原因：
   *  1. 订阅前、切任务前、取消时都要"先关旧的"，写三遍就会漏一遍；
   *  2. 顺带绕开一个类型坑 —— 在同一个函数体里先 `stopRef.current = null` 再
   *     `stopRef.current?.()`，TS 会把 `current` 一路收窄成 `null`，报
   *     "Type 'never' has no call signatures"，好像那个句柄永远不会存在似的；
   *     而它当然会存在（跨 await 期间别的调用可能已经订阅上了）。 */
  /* ---------- 流式增量（SSE delta / usage）的两个入口 ----------
     两个都**只写外部 store，不进页面 state**：增量是 80ms 一批（约 12Hz），
     进 state 就是"整页每秒重渲染 12 次"，日志面板与结果页那棵 markdown 树都得陪着跳
     （P1-01「别让整页陪秒表跳」那条纪律的 12 倍版本）。store 那一侧只让真正显示
     它的 `RunProgress` 重渲染，页面本身一动不动。 */
  const handleDelta = useCallback((delta: Parameters<typeof liveAnswer.push>[0]) => {
    liveAnswer.push(delta);
  }, []);
  const handleUsage = useCallback((usage: Parameters<typeof liveAnswer.addUsage>[0]) => {
    liveAnswer.addUsage(usage);
  }, []);

  const closeStream = useCallback(() => {
    const prev = stopRef.current;
    stopRef.current = null;
    prev?.();
    /* 换任务 / 重新提交时清空流式缓冲。不清的话上一条的答案会接在新一条前面，
       而且"已经流式看过"那枚标志会残留到历史任务上（后果：历史任务打开即全文，
       本该如此；但**这条**残留会让刚提交的任务被当成"看过了"）。 */
    liveAnswer.reset();
  }, []);

  /** 流关闭后拉详情 + 轨迹：SSE 只送增量，结果区要靠这两条补齐。
   *
   *  **提交路径与「从列表选中」路径必须共用这一份**。之前只有提交路径补拉，
   *  从第二栏点开一条正在跑的任务时 `onDone` 是 `() => undefined` —— 任务跑完、
   *  流关闭，详情却再也不拉，结果区一直停在「后端未回填 final_answer」，
   *  用户看到的是一条明明成功却"没答案"的任务。
   *
   *  只写 record、**不碰 events**：onDone 时实时日志已经在缓冲区里，
   *  这里再用 trace 覆盖一遍会把 SSE 推来但 trace 尚未落库的那几行抹掉。 */
  const pullDetail = useCallback(
    async (taskId: string, opts?: { withEvents?: boolean }) => {
      /* 这里**不领号**：补拉不是一次新的用户意图。领了的话，一条已经被切走的任务
         在流关闭时反而把自己的号刷成最新、绕过 selectTask 的守卫。
         代际由 prev.taskId 把住：结果只许落在"屏幕上就是这条"的时候。
         ⚠️ `withEvents`（切回前台那一次）另有一道闸：事件整包替换前再对一次
         `loadedIdRef` —— 上面那道 prev.taskId 只护得住 record，护不住行缓冲，
         中间用户切走的话，A 的 trace 会把 B 的屏幕洗成 A 的行。 */
      try {
        const [detail, trace] = await Promise.all([fetchTask(taskId), fetchTrace(taskId)]);
        setRecord((prev) =>
          prev && prev.taskId === taskId ? applyDetail(prev, detail, trace.items) : prev,
        );
        if (opts?.withEvents && loadedIdRef.current === taskId) {
          replaceEvents(traceToLogEvents(trace.items));
        }
      } catch (err) {
        setRecord((prev) =>
          prev && prev.taskId === taskId
            ? { ...prev, error: { code: 'RESULT_FETCH_FAILED', message: (err as Error).message } }
            : prev,
        );
      } finally {
        void refreshHistory();
      }
    },
    [refreshHistory, replaceEvents],
  );

  const handleSubmit = useCallback(
    async () => {
      /* ---------- 闸在函数里，不在按钮上（Q3-02） ----------
         `loading={submitting}` 只挡鼠标那一条路；文本框里那个**界面自己教出来的**
         Ctrl/Cmd+Enter 走的是 `form.submit()`（:1246 一带），根本不经过按钮 ⇒
         连按就是连发多个 `POST /tasks`、反复开关订阅、`?task_id` 落最后一条。
         写法照同一文件里已经对了的那一条（`handleCancel` 的
         `if (!record || canceling) return` + 把 `canceling` 列进依赖）。
         ⚠️ 依赖里必须真的带上 `submitting`：这个回调是 useCallback，不带的话闭包
         永远捕着首帧那个 `false`，这道闸就成了"写了但一次也不生效"的假闸。 */
      if (submitting) return;
      /* ⚠️ 参数一个都不用，而且**不能**用 onFinish 给的那份 values（P0-11 的尾巴，
         2026-09-25 真实浏览器实测过一次）：rc-field-form 交给 onFinish 的只含**当前已注册**
         的字段，而「运行配置」弹层是懒挂的 —— 用户一次都没点开过，里面那些控件就从来没
         注册过 ⇒ 请求体少键，界面却照常显示"3 轮 / 工具开"。
         现在（U-5）配置整个搬出了 Form，这件事在结构上不再可能：Context 与"有没有渲染"无关。
         于是这里只剩两份来源，各管各的：
         · 任务文本 ← Form（它本来就是表单字段）；
         · 运行配置 ← RunConfigProvider。
         刻意**没被用户碰过的键不进请求体**（``buildRunConfigBody`` 只摊 ``draft``），
         后端那份默认才是真跑的那份（方案 §2 规矩 3、P-8）。
         回归用例：running.cjs 的 R 趟 ②③ + AD 趟（"弹层从头到尾没点开过"那一档现在必须
         **什么都不发**，而不再是"发一份前端编的 3"）。 */
      const task = ((form.getFieldsValue(true) as { task?: string }).task ?? '').trim();
      const config = buildRunConfigBody(draft, disabledTools, toolNames);
      setSubmitting(true);
      setCfgOpen(false);
      replaceEvents([]);
      setAutoScroll(true);
      /* 提交后落在「运行结果」：这一屏从这一刻起进"思考中"态（三点 + 阶段文案），
         正是用户点完提交想看的东西。
         ⚠️ U-8 那半没丢：提交**失败**时下面 catch 里会把页签拨回实时日志 ——
         422 的原文（哪个字段、为什么）落在眼前这条要求仍然成立，只是从"提交前就切"
         改成"确认失败才切"。 */
      setTab('result');
      setStreamNote(null);
      try {
        const created = await submitTask({ task, config });
        /* 回执核对（P-1 的正面那一半）：发出去的意见有没有被**收下**。
           请求模型是 ``extra="ignore"`` ⇒ 一台没重启的后端会把这些键静默丢掉，
           界面如果继续显示"预算 ¥0.36"就是在替用户编一个不存在的闸门。
           所以这里读的是 ``created.runConfig``（服务端原话），不是自己发出去的那份。
           ⚠️ 结论**两处都要落**，各自挡一种失效：
           · 日志事件：这一刻用户正看着日志页签，话说在眼前（U-8 同一口径）；
           · `record.configEchoIssue`：随后整包 trace 会 ``replaceEvents`` 盖掉日志缓冲，
             一条只活一秒的告警等于没说过 —— 而"你以为设了"这件事必须一直看得见。 */
        /* 名字与单位从 ``fields[]`` 拿（``fieldReadingsOf``）：这张告警行以前用
           useRunConfig 里自带的一份 ``CONFIG_LABELS``，写的"成本预算上限"而后端 label 是
           "最大成本预算" —— 同一屏两个名字，正是 R-03 那条先例要拆的形状。
           降级时 readings 为空 ⇒ 退化成"原始 key=裸值"，不猜措辞也不猜单位。 */
        const diffLines = echoDiffLines(config, created.runConfig, fieldReadingsOf(options));
        if (diffLines.length) {
          created.configEchoIssue = {
            code: created.runConfig ? 'RUN_CONFIG_MISMATCH' : 'RUN_CONFIG_UNACKNOWLEDGED',
            lines: diffLines,
          };
        }
        setRecord(created);
        /* 日志里只记**一句**（哪一刻发生过核对），细节全在那条常驻提示里。
           为什么不在两处都写一遍全文：同屏两份同样的数是这一轮清单里专门反掉的形状（P0），
           而这一句的价值是"时间线上有个交代"，不是"再看一遍数字"。 */
        if (diffLines.length) {
          pushEvent({
            seq: -1,
            ts: Date.now(),
            level: 'warn',
            node: 'system',
            message: `运行配置有 ${diffLines.length} 项未被服务端确认，详见运行条下方的提示`,
          });
        }
        /* 提交的这一条也要落到地址栏（主线 2）：先记账、再写 URL —— 顺序反了就会被
           上面的跟随 effect 当成"URL 里冒出一条没人加载的任务"再 selectTask 一遍，
           而那一次会把刚订上的 SSE 关掉重来（`replaceEvents([])` 顺手清掉已经在滚的日志）。
           用 replace 的理由：提交不该在后退栈里留下一个"空视图"的回车点。
           失败分支**不写**：那条任务根本没建起来，写进地址栏等于造一个必坏的链接。 */
        loadedIdRef.current = created.taskId;
        setSp({ [TASK_ID_PARAM]: created.taskId }, { replace: true });
        // 立刻刷一次列表：否则新建的这条要等到任务跑完才出现
        void refreshHistory();
        closeStream();
        stopRef.current = subscribeTaskStream(
          created.taskId,
          pushEvent,
          () => void pullDetail(created.taskId),
          handlePhase,
          streamHandler(created.taskId),
          handleDelta,
          handleUsage,
        );
      } catch (err) {
        /* ---------- U-8：422 的原文要落在用户正看着的那一屏 ----------
           以前这里只留一句 `(err as Error).message`，把后端信封里的 `code` / HTTP 状态 /
           `request_id` 全丢了，而 `record.error` 渲染在**隔壁页签**（运行结果）⇒
           提交失败的下一秒，日志区显示「暂无日志」，真话看不见。
           现在三件事都做：① 三件套原样存进 record.error（详情卡要能复制 request_id 去查后端日志）；
           ② 同一条以 `level:'error'` 写进实时日志；
           ③ **在这一刻**把页签拨回实时日志 —— 提交前落在的是「运行结果」（思考态），
             不切过去的话错误原文就藏在隔壁，U-8 那句话会重新变成假话。
           注意 message 用的是**服务端原话**，不改写、不翻译 —— 422 的价值就在"哪个字段、为什么"。 */
        const apiErr = describeFetchError(err);
        const statusText = apiErr.httpStatus ? `HTTP ${apiErr.httpStatus}` : '请求未送达';
        setTab('log');
        setRecord({
          taskId: '-',
          task,
          status: 'failed',
          createdAt: Date.now(),
          error: {
            code: apiErr.code,
            message: apiErr.message,
            httpStatus: apiErr.httpStatus,
            requestId: apiErr.requestId || null,
          },
        });
        pushEvent({
          seq: -1,
          ts: Date.now(),
          level: 'error',
          node: 'system',
          message:
            `提交失败（${statusText}${apiErr.requestId ? `，request_id ${apiErr.requestId}` : ''}）` +
            `：[${apiErr.code}] ${apiErr.message}`,
        });
        message.error('提交失败，原因见实时日志');
      } finally {
        setSubmitting(false);
      }
    },
    [
      closeStream,
      draft,
      disabledTools,
      handleDelta,
      handlePhase,
      handleUsage,
      message,
      pullDetail,
      pushEvent,
      refreshHistory,
      replaceEvents,
      setSp,
      streamHandler,
      toolNames,
    ],
  );

  /** 取消运行。四条各自独立的原因：
   *  - `canceling` —— 后端落库要时间，没有这个标志的话按钮点下去仍是「运行中」，
   *    再点一次就是第二次 cancel 请求。
   *  - **先问后端、再关流** —— 上一版是 `closeStream()` 在 `await` 之前，取消被拒
   *    （409 已是终态 / 404 不存在）或根本没送达时，一条还在推的流被白白掐了：
   *    用户既没取消成功，又失去实时日志，界面从此停在「运行中」再动不了。
   *  - catch —— 失败必须说给用户听（口径与 useCopy 一致），但**分两种说法**：
   *    后端说"这条已经结束了"时，"任务可能仍在运行"就是反话（这正是 B13 的病根：
   *    不判 HTTP 状态 ⇒ 200 / 409 / 404 / 5xx 在前端是同一句话）。判据走错误码，
   *    不去匹配中文文案。被拒时补拉一次详情，让徽标落到服务端真值上。
   *  - **接住回执里的 `mode`（Q3-01）** —— 200 只代表"取消位已置、DB 已改成 canceled"，
   *    而 `node_boundary` 时 worker 仍在把当前节点跑完（`api/queue.py::_limit_trip` 那一族的
   *    节点边界软闸门同样只在节点之间收口）。上一版把这个返回值整包丢掉、只把徽标改成
   *    「已取消」，于是钱还在涨、日志还在出，而屏上已经说完了 —— 这一条是本屏唯一一处
   *    由我们自己写出去的假话，所以单独占一块常驻区，不进那条会被 `replaceEvents` 换掉的日志。
   *  - finally —— 无论成败都要复位，否则失败一次就永久禁用。 */
  const handleCancel = useCallback(async () => {
    if (!record || canceling) return;
    const taskId = record.taskId;
    setCanceling(true);
    try {
      const ack = await cancelTask(taskId);
      closeStream();
      setCancelAck({ taskId, ack });
      setRecord((prev) =>
        prev && prev.taskId === taskId
          ? { ...prev, status: 'canceled', progress: undefined }
          : prev,
      );
    } catch (err) {
      const msg = (err as Error).message;
      if (isCancelRejected(err)) {
        message.error(`取消未生效：${msg}`);
        void pullDetail(taskId); // 本地那份状态不可信了，换成服务端的
      } else {
        message.error(`取消未送达：${msg}；任务可能仍在运行`);
      }
    } finally {
      setCanceling(false);
    }
  }, [record, canceling, message, closeStream, pullDetail]);

  /** 从第二栏选一个任务 / 从 URL 恢复一个任务：先拿详情 + 轨迹补齐结果，非终态再补订阅 SSE。
   *
   *  `opts.fromUrl` 只影响**视图偏好**，不影响加载哪条。口径（页签调换之后重新对过）：
   *  **这一条路永远不抢页签** —— 用户停在「实时日志」还是「工具调用」上，换任务之后还在那儿，
   *  只有「提交新任务」与「＋ 新建任务」这两个动作会把他带到「运行结果」（也只在失败时
   *  把他推到「实时日志」，见 handleSubmit 的 catch）。抢页签的旧写法是"点列表就把人
   *  拨回日志"，那一版连"我正在看结果页"这个事实都不认，W 趟 ②④⑤ 钉的就是这一族。
   *
   *  ⚠️ `loadedIdRef.current = taskId` **必须在任何 await 之前**（坑 B）：写在响应之后会留出
   *  一个"URL 已经有 id、账上还没有"的空窗，紧随其后的跟随 effect 就再拉一次 ——
   *  症状是同一条任务被打两份 trace（最多 20 个串行请求），而界面看起来一切正常。
   *  失败路径同样记账（下面那个 catch 之前已经记了）：不记的话一个坏 id 会在每次依赖变化时重试，
   *  用户读到的是"点了没反应，但网络面板一直在打"。 */
  const selectTask = useCallback(
    async (taskId: string, opts?: { fromUrl?: boolean }) => {
      const myReq = ++reqIdRef.current;
      const prevId = loadedIdRef.current;
      loadedIdRef.current = taskId;
      closeStream();
      replaceEvents([]);
      setStreamNote(null);
      if (!opts?.fromUrl) {
        setAutoScroll(true);
        /* 这一支今天实际上跑不到：列表那头的 onSelect 只做两件事 —— 同一条再点一次时
           **显式带 fromUrl:true** 顶一次加载（:1148），换一条时只改地址栏、由上面的
           跟随 effect 进来（那条路也带 fromUrl:true）。所以"点列表换任务"根本不经过这里，
           页签也就不会被抢。
           留在原地是因为它记的是这一轮的口径：**万一**有人接一条直接调用（不走 URL），
           换任务应当落在「运行结果」而不是日志；同一个 id 是刷新，哪儿都不许去。
           判据在 W 趟 ④/⑤：④ 钉"点同一条不许动页签"，⑤ 钉"换一条也不许把用户从他
           正待着的页签上拽走"（后者是实测行为，不是愿望）。 */
        if (prevId !== taskId) setTab('result');
      }

      const hit = history.find((h) => h.taskId === taskId);
      setRecord(
        hit ?? { taskId, task: '（载入中）', status: 'queued', createdAt: Date.now() },
      );

      try {
        const [detail, trace] = await Promise.all([fetchTask(taskId), fetchTrace(taskId)]);
        /* 三道闸：屏没了 ⇒ 整包丢掉（否则下面 :993 会开出一条关不掉的连接，Q4-01）；
           号不对 ⇒ 已经有更新的选择在飞，整包丢掉；
           record 已经不是这条 ⇒ 同样丢掉（号会被 pullDetail 之外的路径推进，
           只判号会漏，只判 taskId 会漏"同一条任务被连点两次"的那次迟到）。 */
        if (!mountedRef.current) return;
        if (reqIdRef.current !== myReq) return;
        setRecord((prev) =>
          prev && prev.taskId === taskId ? applyDetail(prev, detail, trace.items) : prev,
        );
        replaceEvents(traceToLogEvents(trace.items));
        if (!STATUS_META[detail.status].terminal) {
          /* 订阅前再关一次：这一行在 await **之后**，期间用户可能又点了别的任务 ——
             那边的 selectTask 已经把句柄关过、清过，正停在它自己的 await 里。
             这里直接覆写就会把「上一条的订阅句柄」冲掉，那条连接从此关不掉（泄漏）。 */
          closeStream();
          stopRef.current = subscribeTaskStream(
            taskId,
            pushEvent,
            () => void pullDetail(taskId),
            handlePhase,
            streamHandler(taskId),
            handleDelta,
            handleUsage,
          );
        }
      } catch (err) {
        if (!mountedRef.current) return;
        if (reqIdRef.current !== myReq) return;
        setRecord((prev) =>
          prev && prev.taskId === taskId
            ? { ...prev, error: { code: 'LOAD_FAILED', message: (err as Error).message } }
            : prev,
        );
      }
    },
    [
      history,
      handleDelta,
      handlePhase,
      handleUsage,
      pushEvent,
      replaceEvents,
      pullDetail,
      closeStream,
      streamHandler,
    ],
  );

  /* ---------- 跟随地址栏（主线 3：URL 是唯一入口，这一条是唯一的加载器） ----------
     守卫只比 `loadedIdRef`，**不比 `record`**：`record` 在同一批更新里可能已经被提交路径
     改写过了（比 :345 那处 setRecord 与这里的 URL 写入谁先落地），拿它当判据会时灵时不灵 ——
     回放页踩过一次，注释在 `TraceReplayPage.tsx:169-171`。

     ⚠️ 为什么 deps 里敢放 `selectTask`（坑 A）：`selectTask` 的身份会随 `history` 变化而变
     （它的 deps 里有 history，:749），而 `refreshHistory` 在这些点都会跑：阶段一转变现
     （:444）、每次 `pullDetail` 的 finally（:614）、提交后（:645）、顶栏刷新（:452）。
     少了这道守卫，就是"每刷一次列表 ⇒ 把当前任务重选一遍 ⇒ 清屏 + 重订 SSE + 再打 10 页 trace"。
     现在身份变了也只是空跑一次比较。 */
  useEffect(() => {
    if (urlTaskId && urlTaskId !== loadedIdRef.current) void selectTask(urlTaskId, { fromUrl: true });
  }, [urlTaskId, selectTask]);

  /** 「＋ 新建任务」：清空主区 + 清空表单 + 给一个看得见的反馈。
   *
   *  之前只清了 record/events，**表单内容原样留着**、也没有任何视觉变化 ——
   *  如果右侧本来就是空态，点下去屏幕上什么都没动，用户会以为按钮没生效。
   *  所以这里补三件事：真正 reset 表单、composer 短暂高亮、顶部出现「新建模式」标签。
   *  纯视觉反馈，不碰提交与 SSE 逻辑。
   */
  const startNew = useCallback(() => {
    /* 顺序要紧：先把"屏幕上是谁"的账清掉，再把地址栏抹干净。
       反过来的话中间那一帧会出现"URL 已空、账上还有 id"的错位；此时若用户是从别的任务
       切过来点新建，跟随 effect 只看 `urlTaskId` 非空才加载，不会误拉 —— 但把账先清掉
       能让"同一个 id 再点一次 = 刷新"那条分支（TaskListPanel 的 onSelect）判得准。 */
    loadedIdRef.current = '';
    closeStream();
    setSp({}, { replace: true }); // 新建意图 = 明确要离开这条任务，地址栏也要跟着离开
    setStreamNote(null);
    setRecord(null);
    replaceEvents([]);
    // 新建意图：结果区显示的是"还没有运行结果"那份引导（与默认页签同一个口径）
    setTab('result');
    setListOpen(false);
    setCfgOpen(false);
    form.setFieldsValue({ task: '' });
    /* 配置也一并撤回"用户没表达过意见"这一档（U-5：它已经不在 Form 里，所以要显式 reset）。
       口径与旧版一致 —— 旧版这里是把三颗控件写回 true/true/3，差别是那个 3 是前端编的，
       现在什么都不发，后端那份默认才是真跑的那份。 */
    resetRunConfig();
    setJustCreated(true);
    window.requestAnimationFrame(() => taskInputRef.current?.focus());
  }, [form, resetRunConfig, closeStream, setSp, submitting]);

  /* ---------- 切回前台先补一次账（P1-06 / 报告 B8） ----------
     为什么必须有：这一屏的日志有两个来源 —— SSE 增量、以及 `/trace` 整包。隐藏标签里
     浏览器会把定时器压到 ≥1s、重连退避（1s/3s/9s，`api/client.ts:106`）也可能整段烧在后台，
     于是切回来的那一刻我们手上那份**很可能是缺帧的**。而后端的 `seq` 每条连接各自从 0 起算
     （`:119-122` 那条 ⚠️），没有可用游标 ⇒ 只能整包换，这与断流恢复走的是同一条 `resyncTrace`。
     两个都要，但**一次请求都要**：`pullDetail` 定状态（不然徽标停在切走那一刻），
     它的 `withEvents` 那一份 trace 定行。
     ⚠️ 已拍板：**不设"streamNote 非空才补"的条件** —— 要防的那一档恰恰是"静默停更但没报错"
     （流没断、就是没帧过来，界面上一行新日志都没有），加条件等于放弃这一档。
     代价是一次切回最多 10 个串行 trace 请求（每页 50 条），只在真的从后台回来时付。
     `wasHiddenRef` 保证首屏不白发这一轮：没离开过就没有"缺帧"这回事。 */
  const recordRef = useRef(record);
  useEffect(() => {
    recordRef.current = record;
  }, [record]);
  useEffect(() => {
    let wasHidden = false;
    const onVis = () => {
      if (document.hidden) {
        wasHidden = true;
        return;
      }
      if (!wasHidden) return;
      wasHidden = false;
      const r = recordRef.current;
      if (!r || STATUS_META[r.status].terminal) return; // 没选中 / 已终态 ⇒ 无可补
      /* 一次 `pullDetail(…, { withEvents: true })` 就够了 —— 它内部本来就要拉一次 trace
         来补结果区，顺手把那份 items 整包换进行缓冲。
         ⚠️ 别拆成 pullDetail + resyncTrace：实测那样会把**同一条 trace 连打两次**
         （切回前台那一下读到的是 详情 1 / 轨迹 2），而 trace 是串行分页的（最多 10 页 × 50），
         等于每次切回都白付一倍后端。 */
      void pullDetail(r.taskId, { withEvents: true });
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
    // deps 里**不放 record**：那枚读数走 recordRef（见上）。写进来的话每一次阶段变化
    // （:416 那个 handlePhase 每帧都可能改 status）都要摘掉再挂一次监听，
    // 而这一条本该整页只挂一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pullDetail]);

  // 「新建模式」提示 2.2s 后自淡出：足够看清，又不会一直挂着占视觉
  useEffect(() => {
    if (!justCreated) return undefined;
    const t = window.setTimeout(() => setJustCreated(false), 2200);
    return () => window.clearTimeout(t);
  }, [justCreated]);

  const fillExample = (task: string) => {
    form.setFieldValue('task', task);
    taskInputRef.current?.focus();
  };

  /* ------------------------------ 运行条要的那两个读数 ------------------------------ *
   *  状态徽标、三步完成态（stageStates）、播报文案都在 components/RunBar.tsx 里自己算 ——
   *  页面只留"只有这里才算得出来"的那一个：当前节点。 */
  /** 当前节点 = **最后一个非 system** 的节点事件。
   *
   *  system 有两类，以前被当成一类：心跳帧（每 15s 一条，任务其实还卡在同一个节点上）
   *  与终态帧。旧口径把 system 一律算作「整条链走完了」，
   *  于是跑一条长任务时状态条有相当比例的时间显示三个节点全绿 —— 心跳一来就「完成」。
   *  现在只认真实节点，终态由 RunBar 那边按 status 单独判。 */
  const currentNode: AgentNode | null = (() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (events[i].node !== 'system') return events[i].node;
    }
    return record?.progress?.currentNode ?? null;
  })();
  const toolCalls = record?.result?.toolCalls ?? [];
  // toolSpecs / toolNames 已上移到"运行配置"那一段（提交时要拿它算完整白名单）

  /** 日志控件组。**两个挂载点共用这一个元素**（窄屏挂面板顶行、宽屏挂页签栏 extra 位），
   *  这样探针能用同一个选择器数同一份账；只有一分支会渲染，不会重复挂载。
   *  ⚠️ 别把它拆成两份 JSX —— 上一次的 390 溢出正是「控件只在页签栏里放得下」这一个
   *     假设造成的，两份副本会让窄屏那份悄悄漏掉某个控件而不报错。 */
  const logControls = (
    <div className="log-controls">
      <Select
        size="small"
        value={levelFilter}
        onChange={setLevelFilter}
        options={LEVEL_OPTIONS}
        style={{ width: 124 }}
        aria-label="日志级别过滤"
      />
      <Input
        size="small"
        placeholder="过滤关键字"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        allowClear
        prefix={<SearchOutlined style={{ color: 'var(--text-3)' }} />}
        style={{ width: 152 }}
        aria-label="日志关键字过滤"
      />
      <Button
        size="small"
        icon={autoScroll ? <PauseOutlined /> : <PlayCircleOutlined />}
        onClick={() => setAutoScroll((v) => !v)}
        aria-pressed={autoScroll}
      >
        {autoScroll ? '暂停滚动' : '继续滚动'}
      </Button>
      <Button size="small" onClick={() => replaceEvents([])} disabled={events.length === 0}>
        清空
      </Button>
    </div>
  );

  /* 「设置」中心的**同一份内容**挂两个容器：宽屏是 720px 的 Modal，≤768 是底部 Drawer。
     刻意只写一份 JSX —— 上一版"控件只在页签栏里放得下"这一个假设造成过 390 溢出，
     两份副本必然漏掉其中一份的判据。面板本身懒加载（见文件头的 lazy import）。
     ⚠️ 2026-09-27 起这一份不再收 examples / onFillExample：那三颗快捷示例是"填任务文本"，
     与配置无关，已经搬到输入框正下方（判据见 running.cjs 的 AD-57…59）。 */
  const runConfigBody = (
    <Suspense fallback={<div className="rcp-loading">正在读取后端给的运行配置…</div>}>
      <RunConfigPanel />
    </Suspense>
  );

  return (
    <>
      <PageHeader
        title="任务与日志"
        desc="提交任务后实时跟踪 Planner → Executor → Reviewer 的编排过程；左侧列表可随时切回任意历史任务。"
        actions={
          <>
            <Button
              className="only-compact"
              icon={<MenuOutlined />}
              onClick={() => setListOpen(true)}
            >
              任务列表
            </Button>
            <Button icon={<HistoryOutlined />} onClick={() => navigate('/trace')}>
              去回放最近轨迹
            </Button>
          </>
        }
      />

      <div className="page-columns">
        <TaskListPanel
          items={history}
          activeId={record?.taskId ?? null}
          loading={historyLoading}
          /* 点列表项 = 改地址栏，不直接调 selectTask（主线 1：URL 是唯一入口，
             加载统一交给跟随 effect，两条路径不会分叉 —— 回放页同一形状）。
             同一个 id 再点一次 URL 不变、effect 不动，所以就地顶一次加载，当刷新用：
             这一条同时兑现了断流认输时那句「重新选中该任务可续上」（:566 的文案），
             以前那个"再点一次"是**什么都不做的**。 */
          onSelect={(id) => {
            if (id === loadedIdRef.current) void selectTask(id, { fromUrl: true });
            else setSp({ [TASK_ID_PARAM]: id }, { replace: true });
          }}
          onCreate={startNew}
          compact={isCompact}
          collapsed={listCollapsed}
          open={listOpen}
          onClose={() => setListOpen(false)}
        />

        <div className="stack page-main">
          {/* ---------- 1. 新建任务流：目标 + 折叠设置胶囊 + 提交（≤100px） ---------- */}
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            onFinish={handleSubmit}
            /* 「运行配置」弹层盖在输入框右半区，校验红字在它下面。
               点提交时弹层会被外部点击自动关掉，但 Ctrl+Enter 不会 ——
               于是空提交那一刻两个反馈叠在一起，用户只看到弹层看不到原因。
               不管校验过没过，提交一次就把弹层收回。 */
            onFinishFailed={() => setCfgOpen(false)}
            initialValues={{ task: '' }}
            className={`composer${justCreated ? ' is-new' : ''}`}
          >
            {justCreated && (
              <div className="composer-badge" role="status">
                <PlusOutlined /> 新建模式 · 已清空，填写新任务目标
              </div>
            )}
            {/* 不用 noStyle：它会把校验文案整块吞掉，空表单提交只剩一个红框，
                用户读不出「为什么红」。规则本来就写着，给它一个落点。 */}
            <Form.Item
              name="task"
              rules={[
                { required: true, message: '请填写任务目标' },
                { max: 4000, message: '最长 4000 字' },
              ]}
            >
              <Input.TextArea
                ref={taskInputRef}
                className="composer-input"
                autoSize={{ minRows: 2, maxRows: 6 }}
                placeholder="描述你要完成的任务，Ctrl + Enter 直接提交"
                maxLength={4000}
                aria-label="任务目标"
                onKeyDown={(e) => {
                  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    form.submit();
                  }
                }}
              />
            </Form.Item>

            {/* 快捷示例（2026-09-27 从「设置」中心里搬出来）。
                为什么搬：这三颗做的是"往上面那格填字"，与迭代轮数/预算/工具没有半点关系 ——
                放在配置面板里，用户要点开设置才看得见，点完还得收起那一层才能回到输入框
                （原来正是这么写的：``onFillExample`` 里那句 ``setCfgOpen(false)``）。
                放在输入框正下方之后：点一下填字 + 焦点回到那格，**仍然不自动提交** ——
                "发出去"这一步归用户（这条纪律从搬到之前一直没变）。 */}
            <div className="composer-examples">
              <span className="composer-examples-label">快捷示例</span>
              {QUICK_EXAMPLES.map((ex) => (
                <button
                  type="button"
                  key={ex.label}
                  className="cfg-ex"
                  onClick={() => fillExample(ex.task)}
                >
                  {ex.icon}
                  {ex.label}
                </button>
              ))}
            </div>

            <div className="composer-foot">
              {/* 工具 / RAG 换成标准开关：自制胶囊（圆点 + 「开/关」）既不像可点的控件，
                  也要读字才知道状态；开关的轨道 + 滑块是无需学习的通用隐喻（清单 P1#8）。 */}
              {/* ⚠️ 这一小块栽过两次，动它之前先读完整：
                  ① 报告 C7 说的那句「label 包着 button，Chromium 不把点击代劳给内部控件」**不是**根因。
                     实测：外面这层用原生 ``<label>``、不加任何转发 onClick，点标题文字照样翻，
                     点开关本体也只翻一次（Chromium 对"点的就是被标注控件"不再代劳）。
                  ② 真正的根因是**状态住在哪儿**。上一版三颗控件的值写在 AntD ``Form`` store 里，
                     而 rc-field-form 只把**已注册**字段交给 ``getFieldsValue()`` / ``onFinish``；
                     注册发生在 ``Form.Item`` 挂载时，而「运行配置」弹层是懒挂的 ⇒ 用户没点开过
                     就等于没注册 ⇒ 实发请求体只剩 ``{"task":"…"}``，界面却显示"开 / 3 轮"。
                     那一次连带的 ``enabled_tools:['calculator','code_exec']`` 写死在前端，
                     还让每条任务都悄悄排除掉知识库检索。一句错都不报，只是静默算错。
                  ③ 现在（U-5）配置的唯一宿主是 ``RunConfigProvider``：**与渲染无关的状态**才敢当
                     请求体的来源。所以这两颗开关不再套 ``Form.Item`` —— 这里少了一层注册，
                     也就少了"忘了注册"这个失败模式。判据在 running.cjs 的 R 趟 + AD 趟
                     （AD 里"面板一次都没打开就提交"必须与"打开后同样设置"发出同一个体）。
                  ④ 别把 ② 读成"只是显示问题"，它是**口径**问题：界面说的、用户以为发出去的、
                     后端真跑的，必须三件同值。 */}
              <label className="switch-row">
                工具
                <Switch
                  size="small"
                  checked={useToolsShown}
                  onChange={setUseTools}
                  aria-label="启用工具"
                />
              </label>
              {/* 「RAG」管的是哪个工具**由后端说**（``tools.rag_tool``），前端不再抄名字。
                  不知道是谁 ⇒ 开关**置灰**并给原因，而不是拿一份猜的名字去算白名单 ——
                  后者正是上一版的病：控件看着能动，实际发的是一个自己编的名单。 */}
              <label
                className={`switch-row${ragDisabledReason ? ' is-disabled' : ''}`}
                title={ragDisabledReason ?? undefined}
              >
                RAG
                <Switch
                  size="small"
                  checked={ragOn === true}
                  disabled={Boolean(ragDisabledReason)}
                  onChange={(on) => {
                    if (ragTool) setToolEnabled(ragTool, on);
                  }}
                  aria-label={ragDisabledReason ? `启用知识库检索（暂不可用：${ragDisabledReason}）` : '启用知识库检索'}
                />
              </label>

              {/* 模型这一栏**只读**。本项目的选型是按编排角色定档的
                  （规划/评审/裁判走强模型，执行与抽取工具走强/快模型），
                  换档等于换掉整套成本与质量口径 —— 那是后端 settings 的事。
                  上一版这里是一颗 Select：选项抄自 ``src/mock/taskMock.ts``、
                  选完既不进 POST body、后端 ``TaskSubmitRequest`` 也没有这个字段，
                  是个什么都不控制的控件。现在的数据源是 ``GET /models``，
                  拉不到就整条不渲染（措辞规则见 utils/modelLabel.ts 的三条硬规则）。
                  给它一个 tab 停靠点不是手滑：明细（单价、价的来路、各角色用哪一档）只在
                  Tooltip 里，只靠 hover 的悬浮内容键盘用户永远读不到 —— 图标栏与状态胶囊
                  两处已按同一口径修过（WCAG 1.4.13）。 */}
              {modelChip && (
                <Tooltip
                  trigger={['hover', 'focus']}
                  title={modelTooltipLines(models).map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                >
                  <span className="cp-model-ro" tabIndex={0}>
                    {modelChip}
                  </span>
                </Tooltip>
              )}

              {/* 运行配置弹层（U-7）：宽屏 380px 的 Popover，≤768 换成底部 Drawer。
                  为什么换容器而不是把弹层缩小：面板里有页签 + 数字输入 + 工具勾选清单，
                  在 390 视口上 380px 的悬浮层只剩"贴边"，且 Popover 的箭头定位会漂出屏幕；
                  Drawer 是 AntD 在这一档宽度下的既定做法（任务列表抽屉同一形状）。
                  两分支共用 ``runConfigBody`` 这一份元素 ⇒ 不会出现"抽屉里少一个控件"。 */}
              {isNarrow ? (
                <>
                  <button
                    type="button"
                    className="cp-icon"
                    aria-haspopup="dialog"
                    aria-expanded={cfgOpen}
                    aria-label="设置"
                    onClick={() => setCfgOpen(true)}
                  >
                    <SettingOutlined />
                  </button>
                  <Drawer
                    className="rcp-drawer"
                    title="设置"
                    placement="bottom"
                    height="78%"
                    open={cfgOpen}
                    onClose={() => setCfgOpen(false)}
                  >
                    {runConfigBody}
                  </Drawer>
                </>
              ) : (
                <>
                  <Tooltip title="设置（基础 / 模型 / 高级）" trigger={['hover', 'focus']}>
                    <button
                      type="button"
                      className="cp-icon"
                      aria-haspopup="dialog"
                      aria-expanded={cfgOpen}
                      aria-label="设置"
                      onClick={() => setCfgOpen(true)}
                    >
                      <SettingOutlined />
                    </button>
                  </Tooltip>
                  {/* 2026-09-27：容器从 Popover 换成 Modal。这不只是"宽一点"——
                      Popover 与输入框**同层**，才有过录屏报告 UI-5 那一帧（浮层压着
                      "请填写任务目标"）与"点示例要顺手收起那一层"的别扭；
                      Modal 有遮罩，配置与提交这两件事从此不在同一层里抢位置。
                      代价也说清：开着它就不能顺手 Ctrl+Enter 提交（焦点被 Modal 接走），
                      所以原来那颗"外部点击自动收起"没了必要，``onFinishFailed`` 那半段留着。 */}
                  <Modal
                    className="sc-modal"
                    title="设置"
                    open={cfgOpen}
                    onCancel={() => setCfgOpen(false)}
                    footer={null}
                    /* 宽度给成**字符串**是有原因的：AntD 把它原样写进 ``style.width``，
                       于是 CSS 的 ``min()`` 在这里生效 —— 960 是"放得下两列角色映射 +
                       一整行单价"的宽度，92vw 是窄一点的笔记本上不横向溢出的保险。
                       高度在 index.css 的 ``.sc-modal .ant-modal-content`` 上（min(600px,80vh)）：
                       那一处还要管标题栏，写在这里管不到。 */
                    width="min(960px, 92vw)"
                    centered
                  >
                    {runConfigBody}
                  </Modal>
                </>
              )}

              {/* 读数只在**服务端报过数**时才出现：``iterationsShown`` 为 null 意味着
                  既没读到默认值、用户也没说过话 —— 那就不许在这里写一个数。 */}
              {iterationsShown !== null && (
                <span className="cp-hint hide-narrow">
                  {iterationsShown}
                  {iterationsUnit ? ` ${iterationsUnit}` : ''} · Ctrl + Enter 提交
                </span>
              )}

              <Button
                type="primary"
                className="cp-submit"
                htmlType="submit"
                icon={<ThunderboltOutlined />}
                loading={submitting}
              >
                提交
              </Button>
            </div>
          </Form>

          {/* ---------- 2. 运行条：状态 + 走到哪个节点 + 取消（拆给 components/RunBar.tsx）。
              为什么拆出去（P1-01，报告 A4②③）：这块以前直接长在页面里，而"多久没有新日志"
              那枚读数依赖页面自己持有的 1Hz `now` state ⇒ 每次 tick 整页重渲染。
              现在计时器在 RunBar 里面的 <Elapsed> 手里，页面不再有秒表 state。
              运行条刻意不放数字：迭代 / Token / 耗时三块在「运行结果」页签里各有一张卡，
              同屏两份同样的数（清单 P0）。运行中唯一要动的数（耗时）交给日志页脚。 ---------- */}
          <RunBar
            record={record}
            currentNode={currentNode}
            streamNote={streamNote}
            running={running}
            lastLogTs={lastLogTs}
            canceling={canceling}
            onCancel={() => void handleCancel()}
          />

          {/* ---------- 2.5 回执核对的结论（P-1）：常驻一条，不在日志缓冲里 ----------
             为什么不"只写进日志就够了"：日志会被随后的整包 trace ``replaceEvents`` 整块换掉
             （断流对账、切回前台补拉、终态补拉都走那条路），一条只活一秒的告警等于没说过。
             为什么这里**不再重复**日志里那些行的全文：同屏两份同样的数是清单 P0 反掉的形状，
             所以日志那一份按时间顺序记账，这一块只说结论 + 一句来路。 */}
          {record?.configEchoIssue && (
            <div className="cfg-issue" role="status" data-code={record.configEchoIssue.code}>
              <p className="cfg-issue-title">
                {record.configEchoIssue.code === 'RUN_CONFIG_UNACKNOWLEDGED'
                  ? '后端没有回报运行配置，下面这几项无法确认是否生效'
                  : '后端回报的实际值与你发出去的不一致'}
              </p>
              <ul className="cfg-issue-list">
                {record.configEchoIssue.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p className="cfg-issue-note">
                多半是这个后端进程比这一版界面旧（重启后才会收下预算 / 超时 / 检索上限）。
                现在真跑的仍是后端自己的默认值。
              </p>
            </div>
          )}

          {/* ---------- 2.6 取消回执（Q3-01）：200 到"位已置"为止，不停到当前节点跑完 ----------
             为什么不复用 `.cfg-issue` 这个类名：那一族有三条探针判据**按类名计数**
             （`tools/uicheck/running.cjs:8546` 断 0、`:8711` 断 1），再加一个同名单元会让
             那两条一起翻红 —— 那是探针在替我记账，不是它坏了。样式带靠 index.css 里把
             `.cancel-ack*` 并进同一组选择器，视觉与上面那条完全一致（同一个 warning 色阶：
             这一块说的也是"你以为它停了"，不是 danger —— danger 留给真烧掉预算的那一条）。 */}
          {cancelAck && record?.taskId === cancelAck.taskId && (
            <div className="cancel-ack" role="status" data-code={cancelAck.ack.mode}>
              <p className="cancel-ack-title">
                {cancelAck.ack.mode === 'node_boundary'
                  ? '取消位已置，当前节点跑完才停'
                  : '这条还在队列里就被丢掉了，worker 从未接手'}
              </p>
              {cancelAck.ack.note && <p className="cancel-ack-note">{cancelAck.ack.note}</p>}
              {cancelAck.ack.mode === 'node_boundary' && (
                <p className="cancel-ack-note">
                  本页已停止订阅，看不到它真正停下的那一刻；已经花掉的那一次不退，
                  最终消耗以任务详情里的回执为准。
                </p>
              )}
            </div>
          )}

          {/* ---------- 3. 页签内容区 ---------- */}
          <div className="pane">
            <Tabs
              activeKey={tab}
              onChange={(k) => setTab(k as typeof tab)}
              tabBarExtraContent={tab === 'log' && !isNarrow ? logControls : null}
              items={[
                /* 顺序就是这一轮的口径：**运行结果排第一、且是默认页签**，实时日志跟在
                   它后面当辅助视图。日志没有降级 —— 同一个组件、同一批控件、一条不少，
                   降的是顺序。两处例外仍然自动跳回日志：提交失败（submit 的 catch，U-8）
                   与"这一屏没载进来"（LOAD_FAILED 在日志里也说得出口，W 趟 ④）。 */
                {
                  key: 'result',
                  label: '运行结果',
                  /* 按需挂载（P1-01，报告 A4③）：**不激活就一行都不建**。
                     AntD 的 Tabs 激活过一次就把面板留在 DOM 里（切走只是隐藏），于是任务
                     一跑完，那上千个引用节点从此常驻，页面每次无关重渲染都要走一遍协调。
                     卸载式挂载把这笔常驻账抹掉；代价是切回来要重挂一次（见 ResultPane 头注释）。 */
                  children:
                    tab === 'result' ? (
                      <ResultPane
                        record={record}
                        running={running}
                        citationsOpen={citationsOpen}
                        onCitationsOpenChange={setCitationsOpen}
                        lastDoneNode={lastDoneNode}
                        revealed={
                          /* 两种"直接给全文"：这一条不是本次看着跑的（历史任务 ⇒ 演打字机
                             就是说假话），或这一条已经播过一遍（切走再切回来不该重来）。 */
                          !liveIds.has(record?.taskId ?? '') || revealedIds.has(record?.taskId ?? '')
                        }
                        onRevealed={() => markRevealed(record?.taskId ?? '')}
                      />
                    ) : null,
                },
                {
                  key: 'log',
                  label: (
                    <span>
                      实时日志 <span className="tab-count">{logRows.length}</span>
                    </span>
                  ),
                  children: (
                    <>
                      {/* 窄屏下控件改挂在这里：页签栏那一行不能换行，塞不下就顶穿视口。
                          放在 LogStream 外面而不是塞进终端工具条 —— 零日志时 LogStream 渲染的是
                          浅色静默态（没有深色工具条），控件在那时同样要能用到。 */}
                      {isNarrow && logControls}
                      <Profiler id="logstream" onRender={countLogStreamCommit}>
                        <LogStream
                          rows={logRows}
                          total={events.length}
                          dropped={dropped}
                          keyword={keyword}
                          running={running}
                          /* 跑动中的计时读数：放在日志页脚，与「实时推送中」同一行 ——
                             盯的是终端，秒表就该在终端上。终态后不传，页脚回到静态口径。
                             ⚠️ 传的是**起点**不是"已经跑了多久"：传后者的话这棵面板每秒
                             都要跟着秒表重渲染一次（P1-01，报告 A4②）。 */
                          startedAt={running ? record?.createdAt : undefined}
                          autoScroll={autoScroll}
                          onAutoScrollChange={setAutoScroll}
                          height={isCompact ? 300 : 420}
                          /* 载入失败要在**日志这一屏**也说得出（W 趟 ④）：`record.error` 以前
                             只渲染在「运行结果」里，而这一屏是用户查"为什么没东西"时必然会点开的
                             那一页 —— 他读到的若是「已订阅，等待首个节点事件」，就是一句会让他
                             一直等下去的谎话（占位 record 的 status 是 queued，不是终态）。
                             ⚠️ 只认 `LOAD_FAILED` 这一个码：`applyDetail`(:271) 也会把后端那份
                             「任务本身失败」写进同一个 `record.error`（码是状态名，如 FAILED），
                             那是任务的结局、不是这一屏没载进来 —— 说成"载入失败"就改口错了。 */
                          loadError={
                            record?.error?.code === 'LOAD_FAILED' ? record.error : null
                          }
                        />
                      </Profiler>
                    </>
                  ),
                },
                {
                  key: 'tools',
                  label: (
                    <span>
                      工具调用 <span className="tab-count">{toolCalls.length}</span>
                    </span>
                  ),
                  /* 与结果页签同一口径：一次调用两张卡（入参 + 出参各一棵树），5,000 事件
                     那一档这里能铺出上千个元素。不激活就不建（P1-01）。
                     页签计数在 label 上，label 一直在 DOM 里，所以折叠不影响"看得见有几个"。 */
                  children:
                    tab === 'tools' ? (
                      toolCalls.length === 0 ? (
                        <EmptyState
                          compact
                          icon={<ToolOutlined />}
                          title="本次未调用工具"
                          desc="「启用工具」关闭时，任务只走模型推理。"
                        />
                      ) : (
                        <div className="stack" style={{ gap: 10 }}>
                          {toolCalls.map((t) => (
                            <ToolCard key={t.id} t={t} spec={toolSpecs.get(t.name)} />
                          ))}
                        </div>
                      )
                    ) : null,
                },
              ].map(withTabBoundary)}
            />
          </div>
        </div>
      </div>
    </>
  );
}
