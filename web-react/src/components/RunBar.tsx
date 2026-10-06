import { Fragment, type CSSProperties } from 'react';
import { Button, Popconfirm } from 'antd';
import { WarningOutlined } from '@ant-design/icons';

import Elapsed from './Elapsed';
import { StatusBadge } from './ui';
import { NODE_META, STATUS_META, nodeColorVar } from '../theme';
import { relativeFromDelta } from '../utils/format';
import type { AgentNode, TaskRecord } from '../types';

/** 状态条上展示的三个编排节点（顺序即执行顺序）。 */
const STAGES: AgentNode[] = ['planner', 'executor', 'reviewer'];

/** 「多久没有新日志」算告警的阈值。口径从旧版 `logStale` 原样搬过来，是**超过**不是等于：
 *  30.000 秒整不算黄。Planner / Executor 是单次长调用，中间本来就没有子事件，
 *  黄了不代表出错 —— 所以文案与 title 都必须把这层意思说清楚（见 runbar-last）。 */
const LOG_STALE_MS = 30_000;

/** 三个编排节点的完成态，只由「当前节点 + 是否终态」推导，不做任何猜测性补判。
 *
 *  两条规则有先后：**先认终态，再看位置**。done / aborted 都必然走过 Reviewer
 *  （收口就是它做的），所以整条链算走完；failed / canceled 不补这一步 ——
 *  它们是在节点边界上断掉的，全绿就是假话。 */
function stagesOf(
  status: TaskRecord['status'] | undefined,
  currentNode: AgentNode | null,
): Array<'done' | 'active' | 'todo'> {
  const closed = status === 'done' || status === 'aborted';
  const cur = currentNode ? STAGES.indexOf(currentNode) : -1;
  return STAGES.map((_, i) => {
    if (closed) return 'done';
    if (cur < 0 || i > cur) return 'todo';
    return i < cur ? 'done' : 'active';
  });
}

export interface RunBarProps {
  record: TaskRecord | null;
  /** 当前节点 = 最后一个非 system 的节点事件，由页面从日志缓冲里算（见 TaskLogPage）。 */
  currentNode: AgentNode | null;
  /** 传输层那一行（不是任务状态）。null = 连接正常，什么都不说。 */
  streamNote: string | null;
  running: boolean;
  /** 最后一条「有内容」日志的时间戳；null = 一条都还没有。 */
  lastLogTs: number | null;
  canceling: boolean;
  onCancel: () => void;
}

/** 运行条（状态 + 走到哪个节点 + 取消）。P1-01（报告 A4②③）从 TaskLogPage 拆出来。
 *
 *  为什么要单独成一个组件：这一页上有两处读数每秒要重算 —— 这里的「最后一条日志 Ns 前」
 *  和日志面板页脚的总耗时。以前秒表挂在页面 state 上，一次 tick 把日志面板（虚拟列表）、
 *  markdown 答案、工具卡全牵着重渲染；现在 1Hz 只活在各自那枚 `<Elapsed>` 里
 *  （报告 A4②：1Hz 关进小组件，别让整页陪它跳）。
 *
 *  ⚠️ 它必须**常驻挂载**，不能跟着 `record` 一起消失：播报口那枚 `.sr-only` 是
 *  aria-live region，aria-live 靠"先在场、后变文本"才 reliably 出声（报告 B2 的口径，
 *  断言在 running.cjs 的 T 趟）。没任务时它渲染的是 `sb-idle` 那一行 + 空串。 */
export default function RunBar({
  record,
  currentNode,
  streamNote,
  running,
  lastLogTs,
  canceling,
  onCancel,
}: RunBarProps) {
  const statusMeta = record ? STATUS_META[record.status] : null;
  const stageStates = stagesOf(record?.status, currentNode);
  /** 运行条给读屏的那一句 —— **只在状态或当前节点真的变了才改**（报告 B2）。
   *
   *  刻意不含「最后一条日志 Ns 前」和任何计时读数：那两个每秒重写一次文本，
   *  挂在 live region 里就是把播报变成每秒一次的刷屏，而且念出来的还是这一行里
   *  唯一在动的那个废数（用户真正要知道的是"从 Planner 走到 Executor 了"）。
   *  显示区（`.runbar`）因此**不再是** live region；播报交给它下面那枚常驻 `.sr-only`。 */
  const runbarAnnouncement =
    record && statusMeta
      ? `${statusMeta.label}${currentNode ? ` · 当前节点 ${NODE_META[currentNode].label}` : ''}`
      : '';

  return (
    <>
      {/* ---------- 2. 运行条：状态 + 走到哪个节点 + 取消。
          刻意不放数字：迭代 / Token / 耗时三块在「运行结果」页签里各有一张卡，
          同屏两份同样的数（清单 P0）。运行中唯一要动的数（耗时）交给日志页脚。
          ⚠️ 这一整块**不是** live region（报告 B2）：以前它是 role="status"，而里面
          「最后一条日志 Ns 前」每秒重写一次 ⇒ 读屏每秒被打断一次。显示与播报分家，
          播报见下面那枚常驻 .sr-only（runbarAnnouncement）。 ---------- */}
      <div className="runbar">
        {record && statusMeta ? (
          <>
            <StatusBadge status={record.status} />
            {/* 连接状态单独一行、单独一个 live region：**任务还在跑**与**流断了**是两件事，
                混在一句里就会读成"任务结束了"。断流时不说"已结束"，也不假装还在推。 */}
            {streamNote && (
              <span className="stream-note" role="status">
                <WarningOutlined style={{ fontSize: 11 }} />
                {streamNote}
              </span>
            )}
            <span className="stepper">
              {STAGES.map((n, i) => {
                const state = stageStates[i];
                return (
                  <Fragment key={n}>
                    {i > 0 && (
                      <span
                        className={`s-line${stageStates[i - 1] === 'done' ? ' is-done' : ''}`}
                        aria-hidden
                      />
                    )}
                    <span
                      className={`step is-${state}`}
                      /* 节点色经 --step-c 下发：圆底与 spinner 环必须同一个色 */
                      style={{ '--step-c': nodeColorVar(n) } as CSSProperties}
                      title={`${NODE_META[n].label} · ${NODE_META[n].desc}`}
                    >
                      <span className="s-circle" aria-hidden>
                        {NODE_META[n].glyph}
                      </span>
                      <span className="s-label">{NODE_META[n].label}</span>
                    </span>
                  </Fragment>
                );
              })}
            </span>
            {running && (
              <span className="runbar-actions">
                {/* 「多久没有新日志」是运行态唯一还没被回答的问题：步骤条说得出在哪个节点，
                    页脚说得出总耗时，但一个 90 秒的模型调用中间本来就没有子事件 ——
                    没有这个数，用户只能靠「屏幕没动 = 可能卡死」来猜。
                    心跳帧（带 idleMs）不计入活跃时间：它恰恰是「没有新事件」的证据，
                    拿它当活跃时间会让这个读数永远停在 0。 */}
                {lastLogTs === null ? (
                  <span className="runbar-last">等待第一条日志</span>
                ) : (
                  /* 秒表在 Elapsed 手里：跳的只有这一行字，运行条其余部分与整页都不再
                     跟着重渲染（P1-01）。告警阈值仍是 30 秒**超过**，与旧 `logStale` 同口径。 */
                  <Elapsed startedAt={lastLogTs} active={running}>
                    {(ms) => (
                      <span
                        className={`runbar-last${ms > LOG_STALE_MS ? ' is-stale' : ''}`}
                        title="距最后一条「有内容」的日志过了多久（心跳帧不计）。超过 30 秒变黄：Planner / Executor 是单次长调用，中间本来就没有新事件，黄了不代表出错。"
                      >
                        最后一条日志 {relativeFromDelta(ms)}
                      </span>
                    )}
                  </Elapsed>
                )}
                {/* 二次确认：这条任务已经跑了 1 分多钟，误触一下就全废了。
                    文案刻意不写「确定/取消」—— 按钮本身就叫「取消」，两个「取消」意思相反。 */}
                <Popconfirm
                  title="取消这条任务？"
                  description="已产生的日志保留，但结果不会再补齐。"
                  okText="仍要取消"
                  cancelText="继续运行"
                  placement="bottomRight"
                  onConfirm={onCancel}
                >
                  <Button size="small" danger loading={canceling}>
                    取消
                  </Button>
                </Popconfirm>
              </span>
            )}
          </>
        ) : (
          <span className="sb-idle">
            尚未运行 · 提交任务后，这里实时显示运行阶段；迭代 / Token / 耗时在「运行结果」页签，
            跑动中的计时看日志面板页脚
          </span>
        )}
      </div>

      {/* 运行条的播报口：**常驻**（没有任务时是空串），文本只在状态/当前节点变化时变。
          放在 runbar 外面是故意的 —— 里面那块每秒都在动，谁跟它同处一个 live region
          谁就被一起刷出去。 */}
      <span className="sr-only" role="status" aria-live="polite" data-live="runbar">
        {runbarAnnouncement}
      </span>
    </>
  );
}
