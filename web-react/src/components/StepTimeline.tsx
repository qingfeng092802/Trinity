import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { DownOutlined, UpOutlined } from '@ant-design/icons';

import { NODE_META, nodeColorVar } from '../theme';
import type { AgentNode, TraceEvent } from '../types';
import { fmtDuration, fmtInt } from '../utils/format';
import { codeArgOf } from '../utils/toolMeta';
import CodeBlock from './CodeBlock';
import JsonView from './JsonView';
import { Chip, CopyButton, NodeTag, StatusBadge } from './ui';

/** 轨迹步骤时间轴（页②核心）。
 *
 * 每步的信息层级：**谁做的 → 做了什么 → 结果如何 → 细节**
 *  - 左侧竖向导轨 + 节点色圆点（形状也区分，色盲安全）
 *  - 步骤卡：头部一行放「可扫描信息」，正文放「需要细读的内容」，正文可折叠
 *  - 入参/出参给复制按钮：轨迹页最常见的下一步就是把这些贴给别人
 */

function nodeOf(e: TraceEvent): AgentNode {
  const raw = e.node ?? e.role;
  return raw === 'planner' || raw === 'executor' || raw === 'reviewer' || raw === 'system' ? raw : 'system';
}

function StepStatus({ status, eventType }: { status: string | null; eventType: string }) {
  const s = (status ?? eventType ?? '').toLowerCase();
  if (s === 'failed' || s === 'error') return <StatusBadge status="failed" />;
  if (s === 'done' || s === 'success') return <StatusBadge status="done" />;
  if (s === 'running' || s === 'start' || s === 'started') return <StatusBadge status="running" />;
  if (s === 'canceled' || s === 'cancelled') return <StatusBadge status="canceled" />;
  if (s === 'queued' || s === 'pending') return <StatusBadge status="queued" />;
  // 认不出的状态原样透出，不硬套成已知状态
  return <Chip outline mono>{s || '—'}</Chip>;
}

export interface StepTimelineProps {
  events: TraceEvent[];
  /** 由页面控制的批量展开开关；单条点击产生的例外存在组件内部。 */
  expandAll: boolean;
}

export default function StepTimeline({ events, expandAll }: StepTimelineProps) {
  const [override, setOverride] = useState<Record<number, boolean>>({});

  // 换任务/重新加载后，逐条的临时展开状态作废
  useEffect(() => {
    setOverride({});
  }, [events]);

  /* 整屏默认展开的三个条件里，只留这两个（Q4-06）。
     去掉的是 `events.some((e) => !!e.error_message)` 那一项：`shown` 最多是 500 条
     （`api/client.ts:455` 的 10 页 × 50），于是**一条**失败的工具调用就把 500 条正文
     全部展开，而每个展开的正文里是 JsonView 的一次 `JSON.parse` + CodeBlock 的一次
     Python 重新分词 —— 一个布尔就是这道悬崖。
     删掉它**不丢功能**：下面 :69 那行 `open = override ?? (defaultOpen || !!e.error_message)`
     本来就按行判，出错的行仍然单独展开。
     `events.length <= 6` 保留：那是"短轨迹整屏摊开更省事"的独立好意，与悬崖无关，
     摘掉它等于顺手改了默认视图口径（要改请单说）。
     依赖收到 `events.length`：三个条件里现在只剩这一个用到数组本身，且用的只是长度 ——
     整条 trace 重新拉一遍但条数没变时，不必因为换了个引用就重算。 */
  const defaultOpen = useMemo(() => expandAll || events.length <= 6, [expandAll, events.length]);

  return (
    <ol className="tl">
      {events.map((e) => {
        const node = nodeOf(e);
        const open = override[e.event_seq] ?? (defaultOpen || !!e.error_message);
        const tokens = (e.tokens_in ?? 0) + (e.tokens_out ?? 0);
        const hasBody = !!(e.thought || e.arguments || e.observation || e.error_message);

        return (
          <li
            className="tl-item"
            key={e.event_seq}
            style={{ '--node-c': nodeColorVar(node, 'fill') } as CSSProperties}
          >
            <span className="tl-dot" aria-hidden>
              {NODE_META[node].glyph}
            </span>

            <div className="tl-card">
              <div className="tl-head">
                <Chip mono outline>
                  #{e.event_seq}
                </Chip>
                {e.step != null && <Chip mono outline>{`step ${e.step}`}</Chip>}
                <StepStatus status={e.status} eventType={e.event_type} />
                <NodeTag node={node} />
                {e.tool_name && (
                  <Chip mono tone={{ fg: 'var(--primary-soft-fg)', soft: 'var(--primary-soft)' }}>
                    {e.tool_name}
                  </Chip>
                )}
                <span className="t3 fs-11 tabular">{fmtDuration(e.latency_ms)}</span>
                <span className="t3 fs-11 tabular">{fmtInt(tokens)} tokens</span>

                {hasBody && (
                  <button
                    type="button"
                    className="icon-btn icon-btn--ghost tl-head-toggle"
                    style={{ width: 28, height: 28 }}
                    aria-expanded={open}
                    aria-label={open ? '收起详情' : '展开详情'}
                    onClick={() => setOverride((prev) => ({ ...prev, [e.event_seq]: !open }))}
                  >
                    {open ? <UpOutlined /> : <DownOutlined />}
                  </button>
                )}
              </div>

              {open && hasBody && (
                <div className="tl-body">
                  {e.error_message && (
                    <div
                      className="field"
                      role="alert"
                      style={{
                        padding: '9px 11px',
                        border: '1px solid var(--danger)',
                        borderRadius: 'var(--r-sm)',
                        background: 'var(--danger-soft)',
                        color: 'var(--danger-fg)',
                        fontSize: 12,
                      }}
                    >
                      <strong>{e.error_code ?? 'ERROR'}</strong>：{e.error_message}
                    </div>
                  )}

                  {e.thought && (
                    <div className="field">
                      <div className="field-head">
                        <span className="field-label">思考 / THOUGHT</span>
                      </div>
                      <div className="prose-block">{e.thought}</div>
                    </div>
                  )}

                  {e.arguments &&
                    (() => {
                      /* 与工具调用卡同一口径：源码字段走代码块，其余走 JSON 树 */
                      const code = codeArgOf(e.tool_name ?? '', e.arguments);
                      return (
                        <div className="field">
                          <div className="field-head">
                            <span className="field-label">入参 / ARGS</span>
                            <CopyButton text={code ?? e.arguments} />
                          </div>
                          {code !== null ? <CodeBlock code={code} /> : <JsonView text={e.arguments} />}
                        </div>
                      );
                    })()}

                  {e.observation && (
                    <div className="field">
                      <div className="field-head">
                        <span className="field-label">输出 / OBSERVATION</span>
                        <CopyButton text={e.observation} />
                      </div>
                      <div className="prose-block">{e.observation}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
