import { useSyncExternalStore } from 'react';

import AnswerView from './AnswerView';
import Elapsed from './Elapsed';
import { liveAnswer } from '../utils/liveAnswer';
import { phaseOf } from '../utils/runPhase';
import { fmtDuration, fmtInt } from '../utils/format';
import type { AgentNode } from '../types';

/** 「运行结果」页签在**跑动中**的那一屏。
 *
 * 它要解决的是录屏里那 12 秒：SSE 只有 4 帧（snapshot / planner / executor / done），
 * 期间屏上唯一在动的是三点动画 —— 用户看不出"它在动"和"它卡住了"的区别。
 * 这一屏补三件东西，三件都只说**已知**的事：
 *
 * 1. **阶段进度条**：已完成到哪一格由 `node` 事件推（它 = 该节点已跑完），
 *    所以格子是**真事实**；正在跑的那一格只做"呼吸"，**不编百分比** ——
 *    要编就得先猜每个节点要跑多久，那是把估算显示成事实；
 * 2. **流式答案**：后端 `delta` 帧到了就逐段显示，没到就显示骨架屏。
 *    骨架屏的行数与最终答案形状对齐（标题行 + 若干正文行），
 *    这样答案到达时**不会跳版**（CLS）—— 骨架屏的意义就是"先占位"；
 * 3. **已用时 + 累计用量**：都是这次运行**真的**发生过的量，随调用推进。
 *
 * ⚠️ 订阅走 `useSyncExternalStore` 而不是把文本挂在页面上：增量是 80ms 一批，
 * 挂到页面上就会让整页（含虚拟日志列表与那棵 markdown 树）以 12Hz 重渲染
 * —— 纪律与 `components/Elapsed.tsx` 那条「别让整页陪秒表跳」同源。
 */

/** 三个编排节点（图的定边：planner → executor → reviewer，见 utils/runPhase.ts）。 */
const STAGES = [
  { key: 'planner', label: '规划' },
  { key: 'executor', label: '执行' },
  { key: 'reviewer', label: '复核' },
] as const;

/** `lastDone`（**已完成**的最后一个节点）→ 已完成几格。 */
function doneCount(lastDone: AgentNode | null): number {
  if (lastDone === 'reviewer') return 3;
  if (lastDone === 'executor') return 2;
  if (lastDone === 'planner') return 1;
  return 0;
}

/** 正在滚的这段是谁写的。说是谁，不说"最终答案"—— 草稿会被 reviewer 重写。 */
function streamLabel(node: string): string {
  if (node === 'reviewer') return '复核后的终稿（正在生成）';
  if (node === 'executor') return '执行草稿（正在生成）';
  return '正在生成';
}

function StageBar({ done }: { done: number }) {
  return (
    <div className="rp-stages" role="img" aria-label={`已完成 ${done} / 3 个阶段：规划、执行、复核`}>
      {STAGES.map((stage, i) => {
        const state = i < done ? 'is-done' : i === done ? 'is-active' : '';
        return (
          <div key={stage.key} className={`rp-stage ${state}`}>
            <span className="rp-stage-bar" aria-hidden />
            <span className="rp-stage-label">
              {stage.label}
              {i < done ? ' ✓' : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** 骨架屏：行数与宽度刻意做成"一段答案"的形状（首行短标题 + 逐行正文 + 末行收尾），
 *  这样答案真的到达时高度差最小。`.skeleton` 复用既有那一条 shimmer（index.css）。 */
function AnswerSkeleton() {
  return (
    <div className="rp-skel" aria-hidden>
      <span className="skeleton" style={{ width: '32%', height: 14 }} />
      <span className="skeleton" style={{ width: '100%', height: 11 }} />
      <span className="skeleton" style={{ width: '96%', height: 11 }} />
      <span className="skeleton" style={{ width: '88%', height: 11 }} />
      <span className="skeleton" style={{ width: '64%', height: 11 }} />
    </div>
  );
}

export interface RunProgressProps {
  /** 已完成交卷的最后一个编排节点；`null` = 一个都还没交卷。 */
  lastDoneNode: AgentNode | null;
  /** 起点（后端 `created_at`）。不传就不显示已用时。 */
  startedAt: number | undefined;
  /** 用户要求减少动态（系统设置）；关掉骨架屏的 shimmer 与呼吸动画。 */
  reduceMotion: boolean;
}

export default function RunProgress({ lastDoneNode, startedAt, reduceMotion }: RunProgressProps) {
  const text = useSyncExternalStore(liveAnswer.subscribe, liveAnswer.getText);
  const node = useSyncExternalStore(liveAnswer.subscribe, liveAnswer.getNode);
  const usage = useSyncExternalStore(liveAnswer.subscribe, liveAnswer.getUsage);
  const phase = phaseOf(lastDoneNode);
  const done = doneCount(lastDoneNode);

  return (
    <div className={`stack rp ${reduceMotion ? 'rp--still' : ''}`} style={{ gap: 12 }}>
      <div className="row row--between">
        {/* 三颗点 + 阶段文案：**唯一**带 aria-live 的一行。文字本身不进增量区，
            否则读屏会把每一帧都当新内容念一遍。 */}
        <span className="thinking" role="status" aria-live="polite">
          <span className="thinking-dots" aria-hidden />
          <span className="thinking-text">{phase.label}</span>
        </span>
        {startedAt !== undefined && (
          <Elapsed startedAt={startedAt} active>
            {(ms) => (
              <span className="fs-11 t3 tabular">已用时 {fmtDuration(ms)}</span>
            )}
          </Elapsed>
        )}
      </div>

      <StageBar done={done} />

      {usage && (
        /* 运行中的累计：**明说是过程量**。终态那一屏有后端落库的成品账，
           这里多写的这句"以终态回执为准"就是为了防止两处数字被当成两份账。 */
        <p className="result-meta">
          <span>
            已调用 {fmtInt(usage.calls)} 次 · 累计 token {fmtInt(usage.prompt + usage.completion)}
            （入 {fmtInt(usage.prompt)} / 出 {fmtInt(usage.completion)}） · 累计成本约 ¥
            {usage.cost.toFixed(4)}
          </span>
        </p>
      )}

      {text ? (
        <div className="stack" style={{ gap: 6 }}>
          <div className="sec-label sec-label--answer">
            生成中的答案
            <span className="sec-label-zh">{streamLabel(node)}</span>
          </div>
          <div className="rp-stream" aria-busy="true">
            <AnswerView text={text} />
            {!reduceMotion && <span className="rp-caret" aria-hidden />}
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 6 }}>
          <div className="sec-label sec-label--answer">
            生成中的答案
            <span className="sec-label-zh">首个字还没到，先占住位置</span>
          </div>
          <AnswerSkeleton />
        </div>
      )}

      <p className="result-meta">
        {text
          ? '以上为生成中的增量，最终答案以收尾后的终稿为准。'
          : '引用来源与消耗明细要等任务收尾后才落库，届时这一屏会整段替换。'}
      </p>
    </div>
  );
}
