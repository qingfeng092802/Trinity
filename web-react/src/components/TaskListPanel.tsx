import { useEffect, useMemo, useState } from 'react';
import { Button, Input } from 'antd';
import { CloseOutlined, PlusOutlined, SearchOutlined, ToolOutlined } from '@ant-design/icons';

import { STATUS_META, statusColorVar } from '../theme';
import { STATUS_LABELS, type TaskRecord } from '../types';
import { fmtCost, fmtDuration, relativeTime } from '../utils/format';

/** 第二栏：任务列表（ChatGPT / IDE 的会话列隐喻）。
 *
 * 职责边界：**只负责「选哪个任务」**，不碰任务内容。
 *  - 顶部固定三件套：新建 → 搜索 → 状态筛选，顺序符合「先造、再找、再筛」。
 *  - 列表项 = 状态圆点 + 标题 + 时间；圆点**不只靠颜色**，右侧同时给出状态文字。
 *  - 终态判定读 `STATUS_META[...].terminal`，不在组件里硬编码状态名。
 *  - 缺值不补：时间为 0 / NaN 时显示「—」，绝不伪造一个时间点。
 */
export interface TaskListPanelProps {
  items: TaskRecord[];
  /** 当前主区正在看的任务，用于高亮。 */
  activeId?: string | null;
  loading?: boolean;
  onSelect: (taskId: string) => void;
  onCreate: () => void;
  /** 窄屏形态：整栏变成抽屉。 */
  compact?: boolean;
  /** 宽屏下整栏收起（顶栏收起按钮 → useTasklist → 页面传下来）。 */
  collapsed?: boolean;
  open?: boolean;
  onClose?: () => void;
}

type Filter = 'all' | 'running' | 'done';

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'done', label: '成功' },
];

function matchFilter(status: TaskRecord['status'], filter: Filter): boolean {
  if (filter === 'all') return true;
  const terminal = STATUS_META[status]?.terminal ?? false;
  return filter === 'running' ? !terminal : status === 'done';
}

export default function TaskListPanel({
  items,
  activeId,
  loading = false,
  onSelect,
  onCreate,
  compact = false,
  collapsed = false,
  open = false,
  onClose,
}: TaskListPanelProps) {
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');

  // 抽屉形态下 Esc 关闭（与导航抽屉一致的手感）
  useEffect(() => {
    if (!compact || !open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compact, open, onClose]);

  const counts = useMemo(
    () => ({
      all: items.length,
      running: items.filter((t) => matchFilter(t.status, 'running')).length,
      done: items.filter((t) => matchFilter(t.status, 'done')).length,
    }),
    [items],
  );

  const visible = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return items.filter(
      (t) =>
        matchFilter(t.status, filter) &&
        (kw === '' || t.task.toLowerCase().includes(kw) || t.taskId.toLowerCase().includes(kw)),
    );
  }, [items, q, filter]);

  /** 按「今天 / 昨天 / 更早」分段。
   *
   *  列表里大量重名任务（「门禁开门延时默认值核查」出现过 5 次），只靠标题分辨不出来，
   *  时间分组给一条纵向的坐标轴 —— 这也是清单 P2#13 要的元信息补充。
   *  分组用日历日而不是「24 小时内」：用户想的是「哪一天跑的」。
   */
  const groups = useMemo(() => {
    const dayStart = new Date();
    dayStart.setHours(0, 0, 0, 0);
    const today = dayStart.getTime();
    const bucketOf = (ts: number): string => {
      if (ts >= today) return '今天';
      if (ts >= today - 86_400_000) return '昨天';
      return '更早';
    };
    const out: Array<{ label: string; items: TaskRecord[] }> = [];
    for (const t of visible) {
      const label = bucketOf(t.createdAt);
      const last = out[out.length - 1];
      // items 已按时间倒序，同一段连续出现，所以只需和上一项比
      if (last && last.label === label) last.items.push(t);
      else out.push({ label, items: [t] });
    }
    return out;
  }, [visible]);

  const shellCls = [
    'task-col',
    // 宽屏：顶栏的收起按钮走 context；窄屏：同一栏改画成抽屉，走 open prop
    compact ? 'task-col--drawer' : collapsed ? 'is-collapsed' : '',
    compact && open ? 'is-open' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const list = (
    <>
      <div className="task-col-head">
        <Button type="primary" block icon={<PlusOutlined />} onClick={onCreate}>
          新建任务
        </Button>
        {compact && (
          <button type="button" className="task-col-close" onClick={onClose} aria-label="收起任务列表">
            <CloseOutlined />
          </button>
        )}
      </div>

      <Input
        size="small"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索任务"
        allowClear
        prefix={<SearchOutlined style={{ color: 'var(--text-3)' }} />}
        aria-label="搜索任务"
      />

      <div className="tsk-filters" role="group" aria-label="按状态筛选任务">
        {FILTERS.map((f) => (
          <button
            type="button"
            key={f.key}
            className={`tsk-filter${filter === f.key ? ' is-active' : ''}`}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
            <span className="tsk-count">{counts[f.key]}</span>
          </button>
        ))}
      </div>

      <div className="tsk-list">
        {loading ? (
          <>
            <div className="tsk-skel" />
            <div className="tsk-skel" />
            <div className="tsk-skel" />
          </>
        ) : visible.length === 0 ? (
          <p className="tsk-empty">
            {items.length === 0 ? '还没有任务，点上面「新建任务」开始' : '没有符合条件的任务'}
          </p>
        ) : (
          groups.map((g) => (
            <section className="tsk-group" key={g.label}>
              <h3 className="tsk-date">{g.label}</h3>
              {g.items.map((t) => (
                <button
                  type="button"
                  key={t.taskId}
                  /* 探针与排查都要用：选中态落到地址栏之后，"地址栏的 id 与高亮那行是同一条"
                     是一句必须能机械比对的断言。以前 DOM 里只有标题文案，比不了 id，
                     于是这条断言只能靠标题文本间接比对，标题重名时无法区分（实测就有一条标题恰好叫「用三句话说明 RAG…」）。 */
                  data-task-id={t.taskId}
                  className={`tsk-item${t.taskId === activeId ? ' is-active' : ''}`}
                  onClick={() => {
                    onSelect(t.taskId);
                    onClose?.();
                  }}
                  aria-current={t.taskId === activeId ? 'true' : undefined}
                  title={t.task}
                >
                  <span
                    className="tsk-dot"
                    style={{ background: statusColorVar(t.status) }}
                    aria-hidden
                  />
                  <span className="tsk-body">
                    {/* 行 1：标题 + 时间；行 2：耗时 / 工具次数 / 金额 + 状态。
                        时间上提到标题行，是为了给第二行的运行指标腾出整行宽度 ——
                        否则「指标 + 状态 + 时间」挤在一行会被截断，反而更难扫。 */}
                    <span className="tsk-line1">
                      <span className="tsk-title">{t.task || '（无标题任务）'}</span>
                      <span className="tsk-time">{relativeTime(t.createdAt)}</span>
                    </span>
                    <span className="tsk-line2">
                      <span className="tsk-stats">
                        <span className="tsk-stat">{fmtDuration(t.durationMs)}</span>
                        <span className="tsk-sep" aria-hidden>
                          ·
                        </span>
                        {/* 工具次数用「图标 + 数字」而不是「2 次工具」：
                            第二行只有约 190px 可用，实测「17.0s · 2 次工具 · ¥0.0131 · 成功」
                            会被裁切。图标省下的宽度留给金额，语义靠 title 补全。 */}
                        <span className="tsk-stat" title={`工具调用 ${t.toolCalls ?? '未知'} 次`}>
                          <ToolOutlined aria-hidden />
                          {t.toolCalls ?? '—'}
                        </span>
                        <span className="tsk-sep" aria-hidden>
                          ·
                        </span>
                        <span className="tsk-stat" title="本次任务花费">
                          {fmtCost(t.cost)}
                        </span>
                      </span>
                      <span className="tsk-status" style={{ color: statusColorVar(t.status) }}>
                        {STATUS_LABELS[t.status] ?? t.status}
                      </span>
                    </span>
                  </span>
                </button>
              ))}
            </section>
          ))
        )}
      </div>
    </>
  );

  if (!compact) return <aside className={shellCls}>{list}</aside>;

  return (
    <>
      <div
        className={`task-col-backdrop${open ? ' is-open' : ''}`}
        onClick={onClose}
        aria-hidden
      />
      <aside className={shellCls} aria-label="任务列表">
        {list}
      </aside>
    </>
  );
}
