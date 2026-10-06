import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { bumpRender } from '../utils/renderLedger';

/** 1Hz 墙上时间的**唯一持有者**（P1-01，报告 A4②「别让整页陪秒表跳」）。
 *
 *  用法是 render-prop：`<Elapsed startedAt={ts} active>{(ms) => …}</Elapsed>`。
 *  每秒重渲染的只有这一枚小组件和它自己那一截输出 —— 父级、兄弟节点、以及它们昂贵的
 *  子树（markdown 答案、虚拟列表）都不再被牵动。
 *
 *  两个刻意的选择从 TaskLogPage 的旧注释原样搬过来：
 *  1. **不累加 tick，按起点重算** —— 后台标签里 `setInterval` 被限到 ≥1s，累加会
 *     「切走一分钟、回来只走二十秒」，而重算自恢复；
 *  2. **1Hz 而不是 10Hz** —— 数字一秒才变一次，10Hz 只是白醒十次 React。
 *
 *  `active=false` 时不挂计时器，读数停在最后一次的值（终态不该继续跳）。
 *  ⚠️ 起点变化（换任务）与 active 翻转都会先对一次表 —— 少了这一步，切到一条
 *  更早的任务时会先显示上一个任务停住的那个数，要等下一秒才更正。 */
export interface ElapsedProps {
  /** 起点（毫秒时间戳；通常是后端 `created_at` 或最后一条日志的时间）。 */
  startedAt: number;
  /** 是否继续跳。false ⇒ 不挂 interval。 */
  active: boolean;
  children: (elapsedMs: number) => ReactNode;
}

export default function Elapsed({ startedAt, active, children }: ElapsedProps) {
  // 探针插桩（running.cjs 的 V 趟）：这一枚**该**每秒涨 —— 它是全页唯一被允许跳的读数
  bumpRender('elapsed');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt, active]);
  return <>{children(Math.max(0, now - startedAt))}</>;
}
