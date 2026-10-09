import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Tooltip } from 'antd';
import { CheckOutlined, CloseOutlined, CopyOutlined, InfoCircleOutlined } from '@ant-design/icons';

import { NODE_META, STATUS_META, nodeColorVar, statusColorVar } from '../theme';
import type { ToolOutcome } from '../utils/toolMeta';
import type { AgentNode, TaskStatus } from '../types';
import { useCopy } from '../hooks/useCopy';

/* ------------------------------------------------------------------ *
 * 面板：全站唯一的卡片皮肤
 * ------------------------------------------------------------------ */

export interface SurfaceCardProps {
  title?: ReactNode;
  /** 标题右侧（或下方）的一句话说明。 */
  sub?: ReactNode;
  icon?: ReactNode;
  /** 右上角操作区。 */
  extra?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** `tight` = 14px，`flush` = 0，默认 18px。 */
  bodyPadding?: 'default' | 'tight' | 'flush';
  className?: string;
  hoverable?: boolean;
  /** 标题与说明竖排（说明较长时用）。 */
  headStack?: boolean;
  style?: CSSProperties;
}

export function SurfaceCard({
  title,
  sub,
  icon,
  extra,
  children,
  footer,
  bodyPadding = 'default',
  className = '',
  hoverable = false,
  headStack = false,
  style,
}: SurfaceCardProps) {
  const cls = [
    'surface',
    hoverable ? 'surface--hoverable' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const bodyCls =
    bodyPadding === 'flush' ? 'surface-body surface-body--flush' : bodyPadding === 'tight' ? 'surface-body surface-body--tight' : 'surface-body';

  return (
    <section className={cls} style={style}>
      {(title || extra) && (
        <header className={headStack ? 'surface-head surface-head--stack' : 'surface-head'}>
          <div className="grow min-w-0">
            {title && (
              <h2 className="surface-title">
                {icon}
                <span className="min-w-0 ellipsis">{title}</span>
              </h2>
            )}
            {sub && <div className="surface-sub" style={{ marginTop: title ? 3 : 0 }}>{sub}</div>}
          </div>
          {extra && <div className="surface-extra">{extra}</div>}
        </header>
      )}
      <div className={bodyCls}>{children}</div>
      {footer && <div className="surface-foot">{footer}</div>}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * 页头
 * ------------------------------------------------------------------ */

export interface PageHeaderProps {
  title: string;
  desc?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
}

export function PageHeader({ title, desc, actions, icon }: PageHeaderProps) {
  return (
    <div className="page-head anim-fade-up">
      <div className="page-head-main">
        <h1 className="page-title">
          {icon}
          {title}
        </h1>
        {desc && <p className="page-desc">{desc}</p>}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * 指标块
 * ------------------------------------------------------------------ */

export type MetricTone = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const TONE_COLOR: Record<MetricTone, string> = {
  default: 'var(--text-1)',
  primary: 'var(--primary)',
  success: 'var(--success-fg)',
  warning: 'var(--warning-fg)',
  danger: 'var(--danger-fg)',
};

export interface MetricTileProps {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: MetricTone;
  /** 顶部渐变条：只给「主角指标」用，避免一屏全是高亮。 */
  accent?: boolean;
  small?: boolean;
  /** 无数据态：数值位弱化显示。 */
  empty?: boolean;
  title?: string;
}

export function MetricTile({
  label,
  value,
  unit,
  hint,
  icon,
  tone = 'default',
  accent = false,
  small = false,
  empty = false,
  title,
}: MetricTileProps) {
  const valueCls = ['metric-value', small ? 'metric-value--sm' : '', empty ? 'is-empty' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <div className={accent ? 'metric metric--accent' : 'metric'}>
      <div className="metric-label">
        {icon}
        <span>{label}</span>
        {title && (
          /* F-4：释义以前挂在一个 AntD 图标（渲染成 `<span role="img"
             aria-label="info-circle">`）上，只有 hover 能触发 ⇒ 键盘与读屏都到不了，
             而读屏听到的还是"info-circle 图像"这个图标名，零信息。
             现在：① 触发器是真 `<button>`，`trigger=['hover','focus']` ⇒ Tab 得到；
             ② 全文以 `.sr-only` 形式**待在按钮里**，焦点一落上去就读得出来；
             ③ Tooltip 仍是给眼睛看的那一份。
             ⚠️ 为什么不用 `aria-describedby` + `useId`（第一版就是这么写的，判据全红才发现）：
                这一页是路由级 lazy 挂进来的，React 18.3 在 Suspense 重放下会给同一次渲染里的
                两个 `useId()` 槽位**发不同的值** —— 实测按钮上是 `aria-describedby=":r11:"`，
                而那个 span 的 `id` 是 `:rv:`，引用直接落空，读屏与探针都拿不到释义。
                把文本放进按钮内容里就不需要 id，也不会有"引用指向一个不存在的元素"这种静默失效。
                （外层 `<div>` 上原来那个同名原生 `title` 一并去掉 —— 它会和 Tooltip 叠两层。） */
          <Tooltip title={title} trigger={['hover', 'focus']}>
            <button type="button" className="metric-info">
              <InfoCircleOutlined aria-hidden style={{ fontSize: 11 }} />
              <span className="sr-only">{`${label}的口径说明：${title}`}</span>
            </button>
          </Tooltip>
        )}
      </div>
      <div className={valueCls} style={{ color: empty ? undefined : TONE_COLOR[tone] }}>
        {value}
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * 空状态 / 错误态
 * ------------------------------------------------------------------ */
export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  desc?: ReactNode;
  /** 「这个页面能给你什么」清单 —— 空状态最该回答的问题。 */
  bullets?: ReactNode[];
  actions?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ icon, title, desc, bullets, actions, compact = false }: EmptyStateProps) {
  return (
    <div className={compact ? 'empty empty--compact' : 'empty'}>
      <div className="empty-icon" aria-hidden>
        {icon ?? '·'}
      </div>
      <div className="empty-title">{title}</div>
      {desc && <p className="empty-desc">{desc}</p>}
      {bullets && bullets.length > 0 && (
        <ul className="empty-list">
          {bullets.map((b, i) => (
            <li key={i}>
              <span aria-hidden>▸</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
      {actions && <div className="empty-actions">{actions}</div>}
    </div>
  );
}

export interface ErrorStateProps {
  icon?: ReactNode;
  title: ReactNode;
  /** 错误本身那一句话（后端 message，或"请求没送达"）。 */
  message: ReactNode;
  /** HTTP 状态码；``0`` 表示请求根本没送达（后端没起 / 断网）。 */
  httpStatus?: number;
  /** 后端统一信封里的机器码（``api/errors.py``）。 */
  code?: string;
  /** 一次请求的追踪号：用户拿它能在服务端日志里对上这一次失败。 */
  requestId?: string;
  /** 与空态分家的那一句：告诉用户"这不是没数据，是这次读没成"。 */
  note?: ReactNode;
  onRetry?: () => void;
}

/** 错误态（F-1）。刻意不与 :func:`EmptyState` 共用出口 —— 两者过去同壳同文案，
 *  于是"后端 500"被读成"你还没跑过评测"，页面还把用户支去跑 CLI。
 *
 *  三件必须露出来的东西：**错误色**、``HTTP 状态码 · 机器码``、``request_id``，
 *  加一个**只重取这一份数据**的重试按钮（不是"再敲一遍 CLI"）。
 *  ``request_id`` 后端一直在给（统一信封），是过去的自己把它摊平成 ``Error(message)`` 丢掉的。 */
export function ErrorState({
  icon,
  title,
  message,
  httpStatus,
  code,
  requestId,
  note,
  onRetry,
}: ErrorStateProps) {
  const notDelivered = !httpStatus;
  /** 只有"确实有一次请求"时才说 HTTP 码 / 网络未送达。形状不识别那类没有请求上下文，
   *  硬套这句会把"报告字段不对"说成"后端没起" —— 那是另一种假指引。 */
  const showMeta = Boolean(httpStatus || code);
  return (
    <div className="error-state" role="alert">
      <div className="error-state-icon" aria-hidden>
        {icon ?? '!'}
      </div>
      <div className="error-state-title">{title}</div>
      <p className="error-state-message">{message}</p>
      {showMeta && (
        <p className="error-state-meta">
          {notDelivered ? '请求未送达（后端未启动或网络中断）' : `HTTP ${httpStatus}`}
          {code ? ` · ${code}` : ''}
          {requestId ? <code className="error-state-req">request_id: {requestId}</code> : null}
        </p>
      )}
      {note && <p className="error-state-note">{note}</p>}
      {onRetry && (
        <div className="error-state-actions">
          <button type="button" className="error-state-retry" onClick={onRetry}>
            重试这一份
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * 徽标
 * ------------------------------------------------------------------ */

export function Chip({
  children,
  tone,
  mono = false,
  outline = false,
  pill = false,
  title,
}: {
  children: ReactNode;
  tone?: { fg?: string; soft?: string };
  mono?: boolean;
  outline?: boolean;
  pill?: boolean;
  title?: string;
}) {
  const cls = ['chip', mono ? 'chip--mono' : '', outline ? 'chip--outline' : '', pill ? 'chip--pill' : '']
    .filter(Boolean)
    .join(' ');
  return (
    <span
      className={cls}
      title={title}
      style={tone ? { color: tone.fg, background: tone.soft } : undefined}
    >
      {children}
    </span>
  );
}

/** 状态徽标：色 + 文案双通道，任何主题下都靠 inline CSS 变量取色。
 *  非终态（排队中 / 运行中）额外让圆点呼吸 —— 终态自动停，判定读 STATUS_META。 */
export function StatusBadge({ status, showHint = false }: { status: TaskStatus; showHint?: boolean }) {
  const meta = STATUS_META[status];
  const badge = (
    <span
      className={meta.terminal ? 'status-badge' : 'status-badge is-live'}
      style={
        {
          '--chip-fg': statusColorVar(status, 'fg'),
          '--chip-soft': statusColorVar(status, 'soft'),
        } as CSSProperties
      }
    >
      <span className="dot" aria-hidden />
      {meta.label}
    </span>
  );
  return showHint ? <Tooltip title={meta.hint}>{badge}</Tooltip> : badge;
}

/** 工具调用结果徽标：三档（成功 / 异常 / 失败）。
 *
 *  不复用 StatusBadge —— 它吃的是 TaskStatus，语义是「任务到哪一步」；
 *  工具调用的「执行异常」既不是任务状态、也不该往那张表里塞一个假状态
 *  （STATUS_META 是前后端共用的口径源，被运行条和任务列表同时消费）。
 *  色与底都取已有的 --*-fg / --*-soft，不新开支配红色阶；文案由 toolOutcome() 决定。 */
export function ToolBadge({ outcome }: { outcome: ToolOutcome }) {
  const pair =
    outcome.tone === 'ok'
      ? { fg: 'var(--success-fg)', soft: 'var(--success-soft)' }
      : outcome.tone === 'warn'
        ? { fg: 'var(--warning-fg)', soft: 'var(--warning-soft)' }
        : { fg: 'var(--danger-fg)', soft: 'var(--danger-soft)' };
  return (
    <span
      className="status-badge"
      style={{ '--chip-fg': pair.fg, '--chip-soft': pair.soft } as CSSProperties}
    >
      <span className="dot" aria-hidden />
      {outcome.label}
    </span>
  );
}

/** 节点标签：形状 + 颜色双通道（色盲安全）。 */
export function NodeTag({ node, showName = true }: { node: AgentNode; showName?: boolean }) {
  const meta = NODE_META[node] ?? NODE_META.system;
  return (
    <span className="node-tag" style={{ '--node-c': nodeColorVar(node) } as CSSProperties}>
      <span aria-hidden>{meta.glyph}</span>
      {showName && meta.label}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * 可复制片段
 * ------------------------------------------------------------------ */

export function CopyButton({ text, label = '复制', size = 'sm' }: { text: string; label?: string; size?: 'sm' | 'md' }) {
  const [state, setState] = useState<'idle' | 'done' | 'fail'>('idle');
  const copy = useCopy();

  const onClick = useCallback(() => {
    void copy(text).then((ok) => {
      /* 失败也要在按钮上留痕：Toast 可能已经滑走，而手指停在原地等回应 */
      setState(ok ? 'done' : 'fail');
      window.setTimeout(() => setState('idle'), ok ? 1600 : 2400);
    });
  }, [text, copy]);

  return (
    <button
      type="button"
      className={state === 'fail' ? 'copy-btn copy-btn--fail' : 'copy-btn'}
      style={size === 'md' ? { height: 30, paddingInline: 10 } : undefined}
      onClick={onClick}
      aria-label={state === 'done' ? '已复制' : state === 'fail' ? '复制失败' : label}
    >
      {state === 'done' ? (
        <CheckOutlined />
      ) : state === 'fail' ? (
        <CloseOutlined />
      ) : (
        <CopyOutlined />
      )}
      {size === 'md' && <span>{state === 'done' ? '已复制' : state === 'fail' ? '复制失败' : label}</span>}
    </button>
  );
}

/** 跑批命令 / 报告路径展示片。命令跑批是本项目最常见的「下一步」，所以给复制。 */
export function CodeChip({ children, label }: { children: string; label?: string }) {
  return (
    <span className="code-chip">
      {label && <span className="t3 fs-11 nowrap">{label}</span>}
      <code title={children}>{children}</code>
      <CopyButton text={children} />
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * 微型图表与占位
 * ------------------------------------------------------------------ */

export function SparkBar({
  segments,
}: {
  /** `readout` 是给读屏与 `title` 看的那一句。不传就退回 `String(value)` ——
   *  但**传**才是对的：`value` 是拿算宽度的原始数（成本场景下是 `0.0020022`），
   *  让读屏用户听到"零点零零二零零二二"而不是"零点零零二零元"，
   *  等于图形那条通道只服务视力正常的人（2026-09-26 成本面板撞出来的，AA 趟 4d 钉住）。 */
  segments: Array<{ value: number; color: string; label: string; readout?: string }>;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total <= 0) return null;
  const say = (s: { label: string; value: number; readout?: string }) =>
    `${s.label} ${s.readout ?? String(s.value)}`;
  return (
    <div className="spark" role="img" aria-label={segments.map(say).join('，')}>
      {segments.map((s, i) => (
        /* key 带上下标：同一根条里允许出现同名分段（成本面板按"角色×档位"上色，
           planner 的高峰与低谷两段 label 都是 Planner ⇒ 只按 label 出 key 会撞 React key）。 */
        <span
          key={`${s.label}-${i}`}
          title={say(s)}
          style={{ width: `${(s.value / total) * 100}%`, background: s.color }}
        />
      ))}
    </div>
  );
}

export function Skel({ w = '100%', h = 12, r = 6, style }: { w?: number | string; h?: number | string; r?: number; style?: CSSProperties }) {
  return <div className="skeleton" style={{ width: w, height: h, borderRadius: r, ...style }} aria-hidden />;
}

/* ------------------------------------------------------------------ *
 * 横向滚动区（宽表 / 宽面板通用）
 * ------------------------------------------------------------------ */

export interface ScrollXFrameProps {
  /** 写进 `aria-label` 的区名。口径：把"还能横着滚"一起说给读屏，
   *  因为视觉那一层（两端渐影）对读屏用户不存在。 */
  label: string;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}

/** 把「右边还有列」这件事说出来，并且让键盘能滚过去（走查报告 EV-01，P0）。
 *
 * 为什么要单独包一层：AntD 的 `.ant-table-content` 自带 `overflow-x:auto`，
 * 横向滚动发生在那一层上 —— 而窄屏的滚动条是 overlay 的（不占高度、几乎看不见），
 * 容器本身也不可聚焦。390 视口实测：9 列的权重表只露 2 列（藏 7），
 * 消融表 6 露 1，失败归因表 5 露 4，且三张表的 `tabindex` 全是 `null`
 * ⇒ 用户以为"这张表就这两列"，键盘更是滚不过去。
 *
 * 做法是把横向滚动**收回到自己这层**（CSS 里把 AntD 那层的 overflow 放开，见
 * `index.css` 的 `.scrollx-box … .ant-table-content`），于是：
 *  1. 容器可聚焦（`tabIndex=0` + `role="region"` + `aria-label`）⇒ 方向键原生就能滚；
 *  2. 三态落在 `data-scrollable / data-at-start / data-at-end` 上 ⇒ 两端的渐影由 CSS
 *     决定显不显，探针也有机械可比的东西，不用靠截图目测。
 *
 * ⚠️ 两件事别改回去：
 *  - 渐影不能用 `background-attachment: local/scroll` 那套纯 CSS 技巧 —— 表格自己会画
 *    单元格底色，画在滚动层背景上的影子会被盖掉，等于没有；所以做成 frame 的伪元素。
 *  - `atEnd` 必须留 1px 容差：dpr 1.5 下 `scrollLeft + clientWidth` 会比 `scrollWidth`
 *    差半个像素，不留容差永远判不到"到底"，右渐影赖着不走。
 */
export function ScrollXFrame({ label, children, className = '', style }: ScrollXFrameProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState({ scrollable: false, atStart: true, atEnd: true });

  const measure = useCallback(() => {
    const el = boxRef.current;
    if (!el) return;
    const over = el.scrollWidth - el.clientWidth;
    const next = {
      scrollable: over > 1,
      atStart: el.scrollLeft <= 1,
      atEnd: over <= 1 || el.scrollLeft + el.clientWidth >= el.scrollWidth - 1,
    };
    /* 同值就返回原对象：这一条挂在 scroll 上，不挡一下就 setState 会让整张表跟着重渲染。 */
    setState((prev) =>
      prev.scrollable === next.scrollable && prev.atStart === next.atStart && prev.atEnd === next.atEnd ? prev : next,
    );
  }, []);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    measure();
    /* 两个都要观察：容器自身宽度随视口变，内容宽度随行/列数据变 ——
       只观察容器的话，"数据多到开始溢出"那一刻量不到。 */
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    el.addEventListener('scroll', measure, { passive: true });
    window.addEventListener('resize', measure);
    return () => {
      ro.disconnect();
      el.removeEventListener('scroll', measure);
      window.removeEventListener('resize', measure);
    };
  }, [measure]);

  return (
    <div
      className={className ? `scrollx-frame ${className}` : 'scrollx-frame'}
      data-scrollable={state.scrollable ? '1' : '0'}
      data-at-start={state.atStart ? '1' : '0'}
      data-at-end={state.atEnd ? '1' : '0'}
      style={style}
    >
      <div ref={boxRef} className="scrollx-box table-wrap" role="region" aria-label={label} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
