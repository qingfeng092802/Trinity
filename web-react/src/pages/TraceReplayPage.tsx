import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Input, Segmented, Select, Skeleton } from 'antd';
import {
  ClockCircleOutlined,
  DownOutlined,
  FilterOutlined,
  MenuOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  UpOutlined,
} from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';

import { fetchTaskList, fetchTrace } from '../api/client';
import StepTimeline from '../components/StepTimeline';
import TaskListPanel from '../components/TaskListPanel';
import {
  Chip,
  EmptyState,
  MetricTile,
  PageHeader,
  SparkBar,
  SurfaceCard,
} from '../components/ui';
import { useRefresh } from '../hooks/useRefresh';
import { useTasklist } from '../hooks/useTasklist';
import { useIsMid } from '../hooks/useMediaQuery';
import { NODE_META, nodeColorVar } from '../theme';
import { TOKEN_VARIANCE_NOTE } from '../utils/costNote';
import type { AgentNode, TaskRecord, TraceEvent } from '../types';
import { fmtDuration, fmtInt } from '../utils/format';
import { useNavigate } from 'react-router-dom';

type NodeFilter = 'all' | 'planner' | 'executor' | 'reviewer';
type StatusFilter = 'all' | 'ok' | 'bad';

const STATUS_OPTIONS = [
  { label: '全部状态', value: 'all' },
  { label: '仅成功', value: 'ok' },
  { label: '仅失败', value: 'bad' },
];

function nodeOf(e: TraceEvent): AgentNode {
  const raw = e.node ?? e.role;
  return raw === 'planner' || raw === 'executor' || raw === 'reviewer' || raw === 'system' ? raw : 'system';
}

function isBad(e: TraceEvent): boolean {
  const s = (e.status ?? e.event_type ?? '').toLowerCase();
  return s === 'failed' || s === 'error';
}

/** 页面 ②：轨迹回放。
 *
 * 数据源：`GET /tasks/{id}/trace`（event_seq 游标分页，client 内部翻完页）。
 * 结构：粘性工具栏（选任务 + 三重筛选 + 展开控制）→ 概览指标 + 节点分布 → 竖向时间轴。
 * 全量指标由真实轨迹聚合，**不做任何补零**；上游没落库事件时如实提示原因。
 */
export default function TraceReplayPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const isCompact = useIsMid();
  const { token: refreshToken } = useRefresh();
  const { collapsed: listCollapsed } = useTasklist();

  const [listOpen, setListOpen] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [filter, setFilter] = useState<NodeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [keyword, setKeyword] = useState('');
  const [expandAll, setExpandAll] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<TaskRecord[]>([]);
  const [eventsAvailable, setEventsAvailable] = useState(true);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);

  const loadHistory = useCallback(async (): Promise<string | undefined> => {
    try {
      const body = await fetchTaskList(30);
      setHistory(
        body.items.map((t) => ({
          taskId: t.task_id,
          task: t.task,
          status: t.status,
          createdAt: Date.parse(t.created_at) || Date.now(),
        })),
      );
      return body.items[0]?.task_id;
    } catch {
      // 列表拉不到不影响回放主流程
      return undefined;
    }
  }, []);

  /** 屏幕上此刻是**谁的**轨迹。用它而不是 `taskId` 做"要不要重新加载"的比较：
   *  `taskId` 在同一个 handler 里会被改写，effect/闭包读到的是旧值 —— 上一版
   *  `if (id === taskId)` 与跟随 effect 的 `idParam !== taskId` 就是这样双双恒假的。 */
  const loadedIdRef = useRef('');

  /** 代际守卫（与任务页同一套）：轨迹接口是串行分页的，慢的一条要走满 ≤10 个 RTT，
   *  先点 A 再点 B 时 A 可能后到。迟到的那一包整包丢掉，**连"屏幕上是谁"这本账也不改**。 */
  const reqIdRef = useRef(0);

  const loadTrace = useCallback(async (id: string) => {
    const target = id.trim();
    if (!target) return;
    const myReq = ++reqIdRef.current;
    setLoading(true);
    setError(null);
    const fresh = () => reqIdRef.current === myReq;
    try {
      const body = await fetchTrace(target);
      if (!fresh()) return;
      setEvents(body.items);
      setEventsAvailable(body.events_available);
      setUnavailableReason(body.unavailable_reason);
    } catch (err) {
      if (!fresh()) return;
      setEvents([]);
      setUnavailableReason(null);
      setError((err as Error).message);
    } finally {
      if (!fresh()) return;
      /* 失败也记账：不记的话同一个坏 id 会在每次依赖变化时重试，
         症状是"点了没反应但网络面板一直在打"。 */
      loadedIdRef.current = target;
      setLoading(false);
    }
  }, []);

  /** 回放某条任务：URL 是唯一入口，`taskId` 只喂输入框与列表高亮。
   *  同一个 id 再点一次时 URL 不变，所以直接顶一次加载（当刷新用）。 */
  const gotoTrace = useCallback(
    (id: string) => {
      const target = id.trim();
      if (!target) return;
      setTaskId(target);
      if (target === (searchParams.get('id') ?? '')) {
        void loadTrace(target);
      } else {
        setSearchParams({ id: target });
      }
    },
    [searchParams, setSearchParams, loadTrace],
  );

  // 首屏：URL 上的 ?id= 优先（从任务页「去回放」跳过来），否则回落到最近一条。
  // 这一趟**只把目标写进 URL、不加载** —— 加载统一交给下面的跟随 effect，
  // 两条路径不会分叉（上一版这里 loadTrace 一次、effect 里又可能一次，判据全靠 state）。
  useEffect(() => {
    void (async () => {
      const fromUrl = searchParams.get('id') ?? '';
      const first = await loadHistory();
      const target = fromUrl || first || '';
      if (target) {
        setTaskId(target);
        if (!fromUrl) setSearchParams({ id: target }, { replace: true });
      }
      setBootstrapped(true);
    })();
    // 只在挂载时跑一次；后续变化由下面的 effect 负责
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** URL 的 ?id= 变了（列表点击、地址栏手敲、别页跳过来）就跟过去。
   *  比较对象是 `loadedIdRef`（永远是当时那份真值），不是 `taskId`（同一批更新里
   *  可能已经被改写过 —— 上一版就是这个条件恒假，导致点了别的任务页面不动）。 */
  const idParam = searchParams.get('id') ?? '';
  useEffect(() => {
    if (bootstrapped && idParam && idParam !== loadedIdRef.current) {
      setTaskId(idParam);
      void loadTrace(idParam);
    }
  }, [idParam, bootstrapped, taskId, loadTrace]);

  // 顶栏「刷新」：id 没变也要重拉一次，所以不能并进上面那个 effect
  useEffect(() => {
    if (bootstrapped && idParam) void loadTrace(idParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const shown = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return events.filter((e) => {
      if (filter !== 'all' && nodeOf(e) !== filter) return false;
      if (statusFilter === 'ok' && isBad(e)) return false;
      if (statusFilter === 'bad' && !isBad(e)) return false;
      if (kw) {
        const haystack = [e.thought, e.tool_name, e.arguments, e.observation, e.error_message]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(kw)) return false;
      }
      return true;
    });
  }, [events, filter, statusFilter, keyword]);

  const stats = useMemo(() => {
    const failed = shown.filter(isBad).length;
    const tokens = shown.reduce((s, e) => s + (e.tokens_in ?? 0) + (e.tokens_out ?? 0), 0);
    const ms = shown.reduce((s, e) => s + (e.latency_ms ?? 0), 0);
    const tools = shown.filter((e) => !!e.tool_name).length;
    const perNode: Record<AgentNode, number> = { planner: 0, executor: 0, reviewer: 0, system: 0 };
    for (const e of shown) perNode[nodeOf(e)] += 1;
    return { failed, tokens, ms, tools, perNode, successRate: shown.length ? (shown.length - failed) / shown.length : null };
  }, [shown]);

  const filtered = shown.length !== events.length;

  /* 选任务 / 手敲 id / 重新加载 三条路径全部收敛到 `gotoTrace`：它只写 URL
     （同 id 再点则当刷新），真正的加载只有跟随 effect 一个入口。
     上一版这里自己 setTaskId + setSearchParams + 判 `id === taskId` 又拉一次，
     三个入口各拉各的，才会出现"点了别的任务、右侧还是上一条"。 */

  return (
    <>
      <PageHeader
        title="轨迹回放"
        desc="按 event_seq 顺序回放一次完整编排：每一步的思考、工具入参出参、耗时与 token 消耗都可追溯。"
        actions={
          <>
            <Button
              className="only-compact"
              icon={<MenuOutlined />}
              onClick={() => setListOpen(true)}
            >
              任务列表
            </Button>
            <Button
              icon={expandAll ? <UpOutlined /> : <DownOutlined />}
              onClick={() => setExpandAll((v) => !v)}
              disabled={shown.length === 0}
            >
              {expandAll ? '全部收起' : '全部展开'}
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                gotoTrace(taskId);
              }}
              disabled={!taskId || loading}
            >
              重新加载
            </Button>
          </>
        }
      />

      <div className="page-columns">
        <TaskListPanel
          items={history}
          activeId={taskId || null}
          onSelect={gotoTrace}
          onCreate={() => navigate('/')}
          compact={isCompact}
          collapsed={listCollapsed}
          open={listOpen}
          onClose={() => setListOpen(false)}
        />

        <div className="stack page-main">
          <SurfaceCard className="trace-toolbar" bodyPadding="tight">
            <div className="stack" style={{ gap: 10 }}>
              {/* 第一行：选任务 */}
              <div className="row">
                <Input.Search
                  placeholder="输入 task_id 回放，如 task-3f9a1c02be11"
                  style={{ width: '100%', maxWidth: 380 }}
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  onSearch={(v) => gotoTrace(v)}
                  enterButton="回放"
                  loading={loading}
                  prefix={<SearchOutlined style={{ color: 'var(--text-3)' }} />}
                  aria-label="输入 task_id 回放"
                />
              {/* 「最近任务」下拉已移除：选任务统一交给第二栏列表，避免两处入口打架。
                  这里只保留按 task_id 直接回放（粘贴外部 id 的场景）。 */}
            </div>

              {/* 第二行：筛选 */}
              <div className="row">
                <Segmented
                  value={filter}
                  onChange={(v) => setFilter(v as NodeFilter)}
                  options={[
                    { label: '全部节点', value: 'all' },
                    { label: '◆ Planner', value: 'planner' },
                    { label: '▶ Executor', value: 'executor' },
                    { label: '✔ Reviewer', value: 'reviewer' },
                  ]}
                />
                <Select
                  size="middle"
                  value={statusFilter}
                  onChange={(v) => setStatusFilter(v as StatusFilter)}
                  options={STATUS_OPTIONS}
                  style={{ width: 124 }}
                  aria-label="按状态筛选"
                />
                <Input
                  placeholder="搜索思考 / 入参 / 输出"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  allowClear
                  prefix={<FilterOutlined style={{ color: 'var(--text-3)' }} />}
                  style={{ width: 220 }}
                  aria-label="按关键字搜索步骤"
                />
                {filtered && (
                  <Chip outline tone={{ fg: 'var(--warning-fg)', soft: 'var(--warning-soft)' }}>
                    已筛选：{shown.length} / {events.length} 条
                  </Chip>
                )}
              </div>
            </div>
          </SurfaceCard>

          {error && (
            <div
              role="alert"
              style={{
                padding: '11px 14px',
                border: '1px solid var(--danger)',
                borderRadius: 'var(--r-md)',
                background: 'var(--danger-soft)',
                color: 'var(--danger-fg)',
                fontSize: 12,
              }}
            >
              轨迹加载失败：{error}
            </div>
          )}

          {!error && !eventsAvailable && (
            <div
              style={{
                padding: '11px 14px',
                border: '1px solid var(--info)',
                borderRadius: 'var(--r-md)',
                background: 'var(--info-soft)',
                color: 'var(--info-fg)',
                fontSize: 12,
              }}
            >
              该任务没有落库轨迹事件
              {unavailableReason ? `（${unavailableReason}）` : '（历史任务早于 task_events 表）'}
              ，请回放新提交的任务。
            </div>
          )}

          <SurfaceCard title="回放概览" icon={<ThunderboltOutlined />} sub={taskId ? `task_id：${taskId}` : undefined}>
            {loading && events.length === 0 ? (
              <div className="metric-grid">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div className="metric" key={i}>
                    <Skeleton active paragraph={{ rows: 1 }} title={false} />
                  </div>
                ))}
              </div>
            ) : events.length === 0 ? (
              <EmptyState
                compact
                icon={<NodeIndexOutlined />}
                title="暂无可回放的轨迹"
                desc="在上面输入一个 task_id，或从「最近任务」下拉里选一条。"
              />
            ) : (
              <>
                <div className="metric-grid">
                  <MetricTile label="事件数" accent value={fmtInt(shown.length)} hint={`共 ${events.length} 条`} />
                  <MetricTile
                    label="成功 / 失败"
                    value={`${shown.length - stats.failed} / ${stats.failed}`}
                    tone={stats.failed > 0 ? 'warning' : 'success'}
                    hint={stats.successRate === null ? '—' : `成功率 ${(stats.successRate * 100).toFixed(1)}%`}
                  />
                  <MetricTile
                    label="工具调用"
                    icon={<NodeIndexOutlined />}
                    value={fmtInt(stats.tools)}
                    hint="含入参/出参的步骤数"
                  />
                  <MetricTile
                    label="总 token"
                    value={fmtInt(stats.tokens)}
                    hint={stats.tokens === 0 ? '该轨迹未上报 token' : '入 + 出 累加'}
                    /* 与结果页那格共用同一份文案（`utils/costNote.ts`）：这一页是用户并排
                       比对同类任务的地方，"为什么两次不一样"在这里问得最多。
                       抄两份必然各自漂，所以只留一个出口；探针 K 趟按内容断言。 */
                    title={TOKEN_VARIANCE_NOTE}
                  />
                  <MetricTile
                    label="总耗时"
                    icon={<ClockCircleOutlined />}
                    value={fmtDuration(stats.ms)}
                    hint={shown.length ? `平均 ${fmtDuration(stats.ms / shown.length)} / 步` : undefined}
                  />
                </div>

                <div style={{ marginTop: 16 }}>
                  <div className="row row--between" style={{ marginBottom: 7 }}>
                    <span className="field-label">节点分布</span>
                    <div className="row" style={{ gap: 12 }}>
                      {(Object.keys(NODE_META) as AgentNode[]).map((n) => (
                        <span className="row" style={{ gap: 5 }} key={n}>
                          <span
                            className="dot"
                            style={{ background: nodeColorVar(n, 'fill') }}
                            aria-hidden
                          />
                          <span className="fs-11 t3">
                            {NODE_META[n].glyph} {NODE_META[n].label} {stats.perNode[n]}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                  <SparkBar
                    segments={(Object.keys(NODE_META) as AgentNode[])
                      .filter((n) => stats.perNode[n] > 0)
                      .map((n) => ({
                        value: stats.perNode[n],
                        color: nodeColorVar(n, 'fill'),
                        label: NODE_META[n].label,
                      }))}
                  />
                </div>
              </>
            )}
          </SurfaceCard>

          <SurfaceCard
            title="步骤明细"
            icon={<NodeIndexOutlined />}
            sub="按 event_seq 升序；点单条右上角可折叠细节"
            extra={
              shown.length > 0 ? (
                <>
                  <Chip outline mono>
                    {shown.length} 条
                  </Chip>
                  {stats.failed > 0 && (
                    <Chip tone={{ fg: 'var(--danger-fg)', soft: 'var(--danger-soft)' }}>
                      失败 {stats.failed} 条
                    </Chip>
                  )}
                </>
              ) : null
            }
          >
            {loading && events.length === 0 ? (
              <div className="stack" style={{ gap: 10 }}>
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} active paragraph={{ rows: 2 }} />
                ))}
              </div>
            ) : shown.length === 0 ? (
              <EmptyState
                compact
                icon={<FilterOutlined />}
                title={events.length === 0 ? '暂无轨迹' : '当前筛选条件下没有步骤'}
                desc={
                  events.length === 0
                    ? '选一条任务后，这里会按时间顺序列出每一步。'
                    : '放宽节点 / 状态 / 关键字筛选试试。'
                }
              />
            ) : (
              <StepTimeline events={shown} expandAll={expandAll} />
            )}
          </SurfaceCard>
        </div>
      </div>
    </>
  );
}
