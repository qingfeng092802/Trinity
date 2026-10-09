import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode, Ref } from 'react';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { useVirtualizer } from '@tanstack/react-virtual';

import type { LogRow } from '../utils/logRows';
import { mergedAway } from '../utils/logRows';
import { fmtDuration } from '../utils/format';
import { bumpRender } from '../utils/renderLedger';
import Elapsed from './Elapsed';
import { MAX_LOG_EVENTS } from '../hooks/useLogBuffer';
import { LOG_LEVEL_META, NODE_META, logNodeColorVar } from '../theme';

/** 单行高度的**初值**：12px 字号 × 行高 1.65 ≈ 19.8，加上下 padding 4 与 1px 分隔线 ≈ 25。
 *  正文是 `white-space: pre-wrap`，长消息会折行 ⇒ 真实高度由 `measureElement` 逐行回填，
 *  这个数只决定首帧滚动条的比例，估偏了不影响正确性。 */
const ROW_ESTIMATE = 25;
/** 视口上下各多挂几行：太少会在快速滚动时露白，太多就白干虚拟化。 */
const OVERSCAN = 8;

interface RowViewProps {
  row: LogRow;
  /** 虚拟项在**全量行**里的下标：measureElement 靠 data-index 把高度回填给对的行。 */
  index: number;
  /** 这一行的偏移（transform 用）。 */
  start: number;
  rowRef: Ref<HTMLDivElement>;
  /** 全量列表里的最后一行（不是「最后一个挂载的行」—— 滚动时两者不同）。 */
  last: boolean;
  /** 挂载那一刻能不能放入场动画。 */
  playInAllowed: boolean;
  needle: string;
  active: number;
  /** 本行首个命中的全局序号，0 = 本行没有命中。 */
  hitOf: number;
  /** 任务是否还在跑。**转圈标记只许在跑的时候出现**（见 RowView 里 `waiting` 那段），
   *  所以这一位必须传到行里，不能只留在面板层。 */
  running: boolean;
}

/** 一行日志。抽成组件不是为了好看，是为了**入场动画的决定只做一次**：
 *
 *  `.log-row` 原本无条件挂着 `animation: log-in`，在「所有行都常驻 DOM」的前提下
 *  等价于「只有新增行动一次」。虚拟化之后历史行会被反复挂载，每进一次视口就重放一遍 ——
 *  滚动时整页呼吸。把判据交给 `useState` 的初始化函数，它对同一个 DOM 节点只跑一次，
 *  于是既不会在动画中途被下一次 render 掐断，也不会被滚动到视口的历史行触发。 */
function RowView({ row, index, start, rowRef, last, playInAllowed, needle, active, hitOf, running }: RowViewProps) {
  const [playIn] = useState(playInAllowed);
  const e = row.head;
  /* 两件事必须分开判，以前混成一个 `live`：
     - `merged`：**这行合并过重复事件**（repeat>1）。它是历史事实，什么时候都成立，
       所以薄底色与「· 已重复 N 次」这条尾巴一直留着（页脚还要报「合并重复 N 条」）。
     - `waiting`：**这条流还开着、正在等下一个事件**。判据是"心跳帧（带 idleMs）+ 还在运行"，
       ⚠️ 不能拿 `repeat>1` 当代理 —— 用户实测：任务早已「成功」，#293 那行
       `calculator → 2 · 已重复 2 次`（两条一模一样的工具行被并起来，跟心跳无关）
       上还挂着 0.9s 无限转的圈，看起来就是"跑完了还有一条在加载"。
       转圈是运行态元素，终态一律不许出现（与「终态不显示 CLI 光标 / 不跳秒 / 不呼吸」同档，A 趟钉）。 */
  const merged = row.repeat > 1;
  const waiting = running && row.idleMs !== undefined;
  const parts = needle ? splitHits(e.message, needle) : null;
  const cls = [
    'log-row',
    `log-row--${e.level}`,
    merged && 'log-row--live',
    last && 'is-last',
    playIn && 'log-row--in',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div
      ref={rowRef}
      data-index={index}
      className={cls}
      style={{ transform: `translateY(${start}px)` }}
    >
      <span className="log-seq">#{String(e.seq).padStart(3, '0')}</span>
      {/* 级别列每行都摆，字色取 LOG_LEVEL_META.onDark（那四个值就是 var(--term-*)）：
          级别由**文字**承载而不是颜色（WCAG 1.4.1），颜色只负责让扫读变快。
          这一条推翻了早先「只给 WARN/ERROR 挂徽标」的 P2#14 —— 定宽列补齐后，
          INFO 不再挤占消息宽度，代价只是每行多四个字符。 */}
      <span className="log-level" style={{ color: LOG_LEVEL_META[e.level].onDark }}>
        {LOG_LEVEL_META[e.level].label}
      </span>
      <span className="log-node" style={{ color: logNodeColorVar(e.node) }}>
        {waiting && <span className="log-live-mark" aria-hidden />}
        {NODE_META[e.node].glyph} {NODE_META[e.node].label}
      </span>
      <span className="log-msg">
        {parts
          ? parts.map((seg, j) =>
              j % 2 === 1 ? (
                <mark
                  className={hitOf + (j - 1) / 2 === active ? 'log-hit is-active' : 'log-hit'}
                  data-hit={hitOf + (j - 1) / 2}
                  key={j}
                >
                  {seg}
                </mark>
              ) : (
                seg
              ),
            )
          : e.message}
        {(merged || waiting) && (
          <span className="log-live-tail">
            {merged && `· 已重复 ${row.repeat.toLocaleString('zh-CN')} 次`}
            {/* 「订阅后多久没新事件」是**当下**的等待时长，只在还在等的时候说得通；
                任务落终态后再报一句"订阅后 45s"就是句没有去处的旧闻。 */}
            {waiting && ` · 订阅后 ${fmtDuration(row.idleMs)}`}
          </span>
        )}
      </span>
    </div>
  );
}

/** 把文本按关键字切成 [普通, 命中, 普通, 命中, ...]（奇数位是命中片段）。
 *
 * 大小写不敏感 —— 与页面那侧的过滤口径必须一致，否则会出现
 * 「这行被筛出来了，可一个高亮都没有」的怪事。
 */
function splitHits(text: string, needle: string): string[] {
  if (!needle) return [text];
  const lower = text.toLowerCase();
  const out: string[] = [];
  let from = 0;
  for (;;) {
    const at = lower.indexOf(needle, from);
    if (at < 0) {
      out.push(text.slice(from));
      break;
    }
    out.push(text.slice(from, at), text.slice(at, at + needle.length));
    from = at + needle.length;
  }
  return out;
}

/** 实时日志面板：**有日志才是深色终端，没日志是浅色静默态**。
 *
 * 设计取舍（对齐 docs/frontend_ui_review.md §3.4）：
 *  - **有日志时恒为深色**：终端隐喻，两主题下一致，切换主题时日志配色不抖动。
 *    既然是独立的一层深色，节点色也不能取 PALETTE —— 那组是为白底调的，
 *    压在终端底上只有 2.8~3.8:1，所以这里消费 `--term-node-*`（见 theme.ts）。
 *  - **零日志时不套深色皮肤**（改版修正）：深色是「沉浸阅读」的隐喻，管道里没有
 *    内容时这个隐喻不成立。空态下 360px 的纯黑块会成为整页视觉最重的元素，把真正
 *    的主操作（左上提交表单）压成配角 —— 所以静默态换成浅色占位，保持同高度避免跳版。
 *  - 面板内**不做 `aria-live` 播报**：SSE 高频推送会把读屏刷爆，所以 `role="log"`
 *    配 `aria-live="off"`，把「读」的主动权交回用户。
 *  - 用户上滑即暂停自动滚动，并给出「↓ N 条新日志」的显式回跳按钮。
 *  - **虚拟滚动**：只挂视口 + overscan 那几十行（`@tanstack/react-virtual`），
 *    常驻 DOM 行数与总行数解耦。消息会折行 ⇒ 行高不固定，用 `measureElement` 逐行
 *    动态测高，估算值只当首帧初值。代价是三个原本不存在的失效模式，全部钉了用例：
 *    命中跳转（目标行没挂载 ⇒ querySelector 拿到 null）、入场动画重放（历史行反复挂载）、
 *    自动滚动被测高回填误关（见 handleScroll 的注释）。
 *  - 级别走**独立定宽列**（序号 | 级别 | 节点 | 正文）：每行都写 DEBUG/INFO/WARN/ERROR
 *    四个字母，级别由文字而不是颜色承载（WCAG 1.4.1）；WARN/ERROR 另有左侧色栏 +
 *    加粗亮色，INFO 与 DEBUG 靠正文明暗分档。节点名前的 ◆/▶/✔/· 是第二通道。
 *
 * 进来的是**已经过滤、已经合并**的行（`utils/logRows.ts`）：合并只可能吃掉重复行，
 * 所以页脚必须报「合并重复 N 条」，不能让人以为日志少了。
 */
export interface LogStreamProps {
  /** 已经过滤 + 合并好的展示行（合并逻辑在页面那侧，面板只管渲染）。 */
  rows: LogRow[];
  /** 合并前的总条数，用于页脚「已显示 x / 共 y」。 */
  total: number;
  /** 因行数封顶被丢掉的最早行数。>0 时页脚必须说出来，不能悄悄丢数据。 */
  dropped?: number;
  /** 页面那侧用来过滤的关键字。传进来只为了做**高亮与跳转**，面板不自己筛。 */
  keyword?: string;
  running: boolean;
  /** 计时起点（后端 `created_at` 的毫秒）。传了就在页脚跳秒，这是「任务还在跑」的数字证据；
   *  终态后不传，页脚回到静态口径。
   *  ⚠️ 这里要的是**起点**不是"已经跑了多久"（P1-01，报告 A4②）：过去页面每秒把
   *  `elapsedMs` 重算好传进来，于是这一整棵面板（虚拟列表、行测量）每秒陪秒表重渲染一次
   *  —— memo 的浅比较必然失败。现在跳动由组件内部的 `<Elapsed>` 持有，props 全程稳定。 */
  startedAt?: number;
  autoScroll: boolean;
  onAutoScrollChange: (next: boolean) => void;
  height?: number;
  emptyNode?: ReactNode;
  /** 这一条任务的**载入**错误（详情 / 轨迹拉失败，或地址栏里那个 `task_id` 根本不存在）。
   *  传进来只为一件事：让静默态说实话。
   *  ⚠️ 顺序上它必须排在 `running` **之前**判（见下面那枚三元）：载入失败时 `record` 停在
   *  selectTask 塞的那份「（载入中）」queued 占位上，而 queued 不是终态 ⇒ `running` 为真，
   *  于是页面会读成「已订阅，等待首个节点事件」—— 那是一句谎话，用户会一直等。
   *  以前这一支不存在：错误只渲染在「运行结果」页签里（ResultPane），而手敲错 id 的人
   *  根本不会切过去。 */
  loadError?: { code: string; message: string } | null;
}

/** `memo` 的前提是 props 稳定：`rows` 由页面侧 useMemo 产出、`onAutoScrollChange` 是
 *  setState、`keyword` 是字符串 —— 下一个事件都没有时，这里应当**一次都不重渲染**。
 *  运行态也一样：跳秒由内部那枚 `<Elapsed>` 持有，只有它自己那一截页脚每秒重画，
 *  面板与虚拟列表不再陪跑（P1-01）。
 *  ⚠️ 断言读的是 `__renders.logstreamRender`（本组件函数体自数），**不是**外面那枚
 *  `<Profiler id="logstream">` 的提交数 —— Profiler 连**子树里的嵌套更新**也回调，
 *  页脚那枚 `<Elapsed>` 每秒一次 setState 就会把它推一格（实测同一窗口 page 16→16 而
 *  Profiler 15→18）。这与 P0-13 在 AnswerView 上踩的是同一个量具坑，第二次踩，写死在这儿。
 *  面板自己该不该重渲染，只有它自己数的数说得上话（V 趟读的就是下面这一枚）。 */
const LogStream = memo(function LogStream({
  rows,
  total,
  dropped = 0,
  keyword = '',
  running,
  startedAt,
  autoScroll,
  onAutoScrollChange,
  height = 340,
  emptyNode,
  loadError = null,
}: LogStreamProps) {
  /* 探针插桩（running.cjs 的 V 趟）：本组件函数体跑了几遍。判定"跳秒有没有牵到面板"只能靠它，
     理由见上面 memo 那段 —— Profiler 的提交数把页脚 <Elapsed> 的嵌套更新也算进去。
     与 utils/renderLedger.ts / logRows.ts 里那两枚同一套：只写一个全局计数，产品代码不读。 */
  bumpRender('logstreamRender');
  const bodyRef = useRef<HTMLDivElement>(null);
  const prevLen = useRef(rows.length);
  const [newCount, setNewCount] = useState(0);
  /** 被合并掉多少条。必须 memo：这是**整条渲染路径上唯一一处 O(全部行) 的循环**
   *  （5,000 行就是一次 5,000 步 reduce），而页面那侧每 1Hz 跳一次秒表就会重渲染
   *  一次。不 memo 时它不报错、只是每帧多算一遍 —— 所以由 M 趟用渲染计数钉住。 */
  const merged = useMemo(() => mergedAway(rows), [rows]);

  const needle = keyword.trim().toLowerCase();

  /** 每行首个命中的全局序号（1 起，无命中为 null）+ 命中总数。
   *  前缀和在这里算，渲染时才能给每个 `<mark>` 一个稳定、可跳转的编号。
   *  计数口径是**可见行**：一行重复 30 次的心跳算 1 处命中，跳一次就到。 */
  const hits = useMemo(() => {
    if (!needle) return null;
    const first: Array<number | null> = [];
    let count = 0;
    for (const r of rows) {
      const n = (splitHits(r.head.message, needle).length - 1) / 2;
      first.push(n > 0 ? count + 1 : null);
      count += n;
    }
    return { first, count };
  }, [rows, needle]);

  /** 命中序号 → 行下标。虚拟化之后目标行**根本没挂载**，
   *  原来那句 `querySelector('[data-hit]').scrollIntoView()` 会静默返回 null
   *  （点了上一处/下一处什么也不发生）。所以先按行下标滚，挂上之后再收口。 */
  const rowOfHit = useMemo(() => {
    if (!hits) return null;
    const map = new Map<number, number>();
    hits.first.forEach((n, i) => {
      if (n !== null && !map.has(n)) map.set(n, i);
    });
    return map;
  }, [hits]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => bodyRef.current,
    estimateSize: () => ROW_ESTIMATE,
    overscan: OVERSCAN,
    // key 带 index 兜底：即使上游 seq 出现重复也不会撞 key 丢行
    getItemKey: (i) => `${rows[i].head.seq}-${i}`,
  });

  const [active, setActive] = useState(1);

  // 换关键字 = 重新从第一处开始数，否则光标停在「7/12」而新词只有 3 处命中
  useEffect(() => {
    setActive(1);
  }, [needle]);

  /** 上一处 / 下一处：环形跳转，跳完把这处滚到视野中间。 */
  const step = (delta: number) => {
    if (!hits || hits.count === 0) return;
    const next = (((active - 1 + delta) % hits.count) + hits.count) % hits.count + 1;
    setActive(next);
    const idx = rowOfHit?.get(next);
    if (idx === undefined) return;
    virtualizer.scrollToIndex(idx, { align: 'center' });
    /* scrollToIndex 用的是**估算高度**，测高回填后可能还差半行。等这一行真的挂上，
       再用原生 scrollIntoView 收一次口 —— 两帧是挂载 + measure 落地的最短距离。 */
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        bodyRef.current
          ?.querySelector<HTMLElement>(`[data-hit="${next}"]`)
          ?.scrollIntoView({ block: 'center' });
      });
    });
  };

  /** 已经放过入场动画的 seq。虚拟化会让历史行反复挂载，没有这份账
   *  「滚动 = 整页重放入场动画」。封顶 5,000 行的会话里它最多长到 5,000 个数字，
   *  但**长跑**（不断追加、旧行被丢弃）会一直涨，所以超过两倍上限就按当前行重建。 */
  const seen = useRef<Set<number>>(new Set());
  useEffect(() => {
    if (seen.current.size > MAX_LOG_EVENTS * 2) seen.current = new Set();
    for (const r of rows) seen.current.add(r.head.seq);
  }, [rows]);

  /** 上一次「钉在底部」时的 scrollTop。 */
  const pinnedTop = useRef<number | null>(null);

  const pinToBottom = () => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    pinnedTop.current = el.scrollTop;
  };

  /* 第一次带行挂载时要单独钉一次底。
     ⚠️ 这一条是「页签调换」逼出来的：以前日志面板是默认页，它**必然**在 0 行的时候挂载，
     第一条永远经由上面那条 `delta > 0` 的路进来。换成「运行结果」当默认页之后，
     用户是先在结果页把 120 行拉完、再点开日志页签 —— 面板**带着满屏行第一次挂载**，
     而 `prevLen` 初始化成 `rows.length` ⇒ delta = 0 ⇒ 谁都不钉底。
     实测（120 行档，改之前）：scrollTop=0 / max=2592，视口停在 #001（最老那一条），
     而页脚仍写着「自动滚动已开启」—— 界面承诺的位置与实际滚动位置不一致。
     ⚠️ 必须**推两帧**再钉，不能在 effect 里当场钉：挂载这一帧里虚拟列表的总高还是
     `ROW_ESTIMATE × 条数`，真高要等 `measureElement` 回填。当场钉会被回填夹一次
     （scrollTop 被浏览器夹回新最大值），那一下夹动恰好落进 `handleScroll` 的
     "用户上滑了"判据里 ⇒ 自动滚动被悄悄关掉。第一版就是这么红的：
     页脚从「自动滚动已开启」变成「回到底部」，而视口还在 #001。
     两帧是这个文件里已有的口径（见上面 `step()` 里那句"两帧是挂载 + measure 落地的最短距离"）。
     ⚠️ 而"已经钉过一次"这枚旗**只能在真钉下那一下才立**：开发模式 StrictMode 会把 effect
     跑两遍（跑一遍 → 清掉 → 再跑一遍），第一版在调度时就立旗，于是第二遍直接早退、
      cleanup 又把那一击 cancel 掉 —— 结果是**一次都没钉**（实测视口仍停在 #001）。
     旗子挪进 rAF 回调之后，第二遍会重新调度并真的钉下去。 */
  const firstPinDone = useRef(false);

  useEffect(() => {
    if (firstPinDone.current || rows.length === 0 || !autoScroll) return;
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        pinToBottom();
        firstPinDone.current = true;
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
    // deps 里不放 pinToBottom：它每次 render 都是新函数，放进去这个 effect 会反复重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length, autoScroll]);

  // 新增行：自动滚动开启就贴底，关闭就累计「未读」，等用户自己决定什么时候回跳
  useEffect(() => {
    const delta = rows.length - prevLen.current;
    prevLen.current = rows.length;
    if (delta <= 0) return;
    if (autoScroll) {
      pinToBottom();
      setNewCount(0);
    } else {
      setNewCount((c) => c + delta);
    }
  }, [rows, autoScroll]);

  const jumpToBottom = () => {
    pinToBottom();
    setNewCount(0);
    onAutoScrollChange(true);
  };

  const handleScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (atBottom) {
      pinnedTop.current = el.scrollTop;
      if (!autoScroll) onAutoScrollChange(true);
      setNewCount(0);
      return;
    }
    /* ⚠️ 不能用「距底 > 24px」单独判用户上滑。
       虚拟化下新行是先按估算高度占位、随后 measureElement 才回填真实高度的 ——
       一批长消息折行会把 scrollHeight 突然撑长，此刻 scrollTop 一动没动，
       但距底差会从 0 跳到几十像素，于是自动滚动被**悄悄关掉**，
       用户看到的最后一条日志就此停止更新。
       真正的信号只有一个：scrollTop 比上一次钉住的位置**更小**（人往上推了）。 */
    if (pinnedTop.current !== null && el.scrollTop < pinnedTop.current - 2 && autoScroll) {
      onAutoScrollChange(false);
    }
  };

  // ---- 静默态：管道里还没有内容，不套深色终端皮肤 ----
  // 高度与深色态对齐（用 minHeight 而不是被内容撑高），避免首条日志到达时整页跳版。
  if (rows.length === 0) {
    const filteredOut = total > 0;
    return (
      <div
        className="log-idle"
        style={{ minHeight: height }}
        role="log"
        aria-live="off"
        aria-label="任务实时日志"
      >
        <span className="log-idle-mark" aria-hidden>
          &gt;_
          {/* 首帧之前是最焦虑的一段：浅色静默态里也给一枚闪烁光标，
              读的是「提示符已经就绪」，而不是「页面卡住了」。 */}
          {running && <span className="log-cursor-block">█</span>}
        </span>
        <p className="log-idle-title">
          {loadError
            ? `任务载入失败：${loadError.code}`
            : filteredOut
              ? '当前过滤条件下没有日志'
              : running
                ? '已订阅，等待首个节点事件'
                : '还没有日志'}
        </p>
        {/* 静默态也要跳秒：从提交到第一条事件之间往往有十几秒，
            这段时间没有终端皮肤，正是最容易怀疑「卡住了」的地方。 */}
        {running && startedAt !== undefined && (
          <p className="log-live-foot">
            提交后{' '}
            <Elapsed startedAt={startedAt} active>
              {(ms) => fmtDuration(ms)}
            </Elapsed>
          </p>
        )}
        <p className="log-idle-desc">
          {emptyNode ??
            (loadError
              ? `${loadError.message}；地址栏里的 task_id 可能对不上任何任务 —— 从左侧列表选一条，或点「＋ 新建任务」。`
              : filteredOut
                ? '换个级别或清空关键字再看看；日志本身没有被丢弃。'
                : running
                  ? '任务刚受理，Planner 的首个事件马上就到。'
                  : '提交任务后，Planner / Executor / Reviewer 的节点事件会实时推到这里。')}
        </p>
        {/* 载入失败时别再教人「按 Ctrl+Enter 提交」：那一步他刚做过，问题不在这里。 */}
        {!running && !filteredOut && !loadError && (
          <p className="log-idle-kbd">
            在上方输入任务目标，按 <kbd>Ctrl</kbd> + <kbd>Enter</kbd> 直接提交
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="log">
      <div
        className="log-body"
        ref={bodyRef}
        onScroll={handleScroll}
        role="log"
        aria-live="off"
        /* 这块自己滚，所以它必须进 Tab 序：不加 tabIndex，键盘用户只剩"整页滚"这一条路，
           而日志区自己带 overflow —— Tab 过去滚不动的东西不该算可达（P1-10 / C8，与
           .scrollx-box 同一处置，焦点环由全站那条 :where(…, [tabindex]):focus-visible 给）。
           aria-label 里把"能滚"一起说出去：底色与滚动条对读屏不存在。 */
        aria-label="任务实时日志（聚焦后用方向键或 PageUp / PageDown 滚动）"
        tabIndex={0}
        style={{ height }}
      >
        {/* 虚拟容器：spacer 撑出「全量高度」，行本身绝对定位、只挂视口 + overscan 那几十行。
            5,000 行 ⇒ DOM 里 ~30 行，且**常驻行数与总行数解耦**。 */}
        <div className="log-virtual" style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map((vi) => (
            <RowView
              key={vi.key}
              row={rows[vi.index]}
              index={vi.index}
              start={vi.start}
              rowRef={virtualizer.measureElement}
              last={vi.index === rows.length - 1}
              playInAllowed={!seen.current.has(rows[vi.index].head.seq)}
              needle={needle}
              active={active}
              hitOf={hits?.first[vi.index] ?? 0}
              running={running}
            />
          ))}
        </div>
        {/* 跑动中的终端在正文末尾固定挂一枚 CLI 光标：管道里没有新行时，
            它是唯一「进程还活着」的形状信号。aria-hidden —— 它不携带文本信息。
            放在 spacer **外面**走正常文档流，于是它永远贴在最后一行下面，
            不用跟着 totalSize 自己算 translateY。 */}
        {running && (
          <div className="log-cursor" aria-hidden>
            <span className="log-cursor-block">█</span>
          </div>
        )}
      </div>

      <div className="log-foot">
        <span>
          已显示 {rows.length} 行 / {total} 条
        </span>
        {merged > 0 && (
          <span
            className="log-merged"
            title="重复的等待/心跳行合并到了一起（同一句连续出现才并）：条数没少，只是不再各占一行。"
          >
            · 合并重复 {merged.toLocaleString('zh-CN')} 条
          </span>
        )}
        {dropped > 0 && (
          <span
            className="log-dropped"
            title={`内存里只保留最近 ${MAX_LOG_EVENTS.toLocaleString('zh-CN')} 行，更早的已丢弃；完整轨迹仍可在「轨迹回放」页按 event_seq 查。`}
          >
            · 封顶丢弃 {dropped.toLocaleString('zh-CN')} 行
          </span>
        )}
        {running && (
          <span className="log-live-foot">
            · 实时推送中
            {startedAt !== undefined && (
              <>
                {' · 提交后 '}
                <Elapsed startedAt={startedAt} active>
                  {(ms) => fmtDuration(ms)}
                </Elapsed>
              </>
            )}
          </span>
        )}
        {hits && (
          <span className="log-hits" aria-label="命中导航">
            {hits.count > 0 ? (
              <>
                · 命中 {hits.count} 处
                <button
                  type="button"
                  className="log-hit-btn"
                  onClick={() => step(-1)}
                  aria-label="上一处命中"
                >
                  <UpOutlined />
                </button>
                <span className="log-hit-pos tabular">
                  {active}/{hits.count}
                </span>
                <button
                  type="button"
                  className="log-hit-btn"
                  onClick={() => step(1)}
                  aria-label="下一处命中"
                >
                  <DownOutlined />
                </button>
              </>
            ) : (
              <span>· 命中 0 处</span>
            )}
          </span>
        )}
        {!autoScroll && (
          <button type="button" className="log-jump" onClick={jumpToBottom}>
            <DownOutlined style={{ fontSize: 10 }} />
            {newCount > 0 ? `${newCount} 条新日志` : '回到底部'}
          </button>
        )}
        {autoScroll && <span style={{ marginInlineStart: 'auto' }}>自动滚动已开启</span>}
      </div>
    </div>
  );
});

export default LogStream;
