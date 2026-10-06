import { useCallback, useEffect, useRef, useState } from 'react';

import type { LogEvent } from '../types';

/** 内存与 DOM 里保留的最大日志行数。
 *
 * 取 5,000 的口径：本项目一次任务的真实量级是几百条（实测最长 336 条），
 * 5,000 已经放宽了一个数量级；再往上没有人回头看，却会把 DOM 行数顶到浏览器掉帧。
 * 丢掉的行数**必须**在面板上说出来（见 LogStream 的 dropped 页脚），不能悄悄丢。
 */
export const MAX_LOG_EVENTS = 5000;

/** 攒批窗口。50ms = 每秒最多 20 次 render，与事件到达速率解耦。
 *
 * 用 setTimeout 而不是 requestAnimationFrame：rAF 在后台标签里**不执行**，
 * 而这个页面最常见的用法正是「提交完任务切到别的标签，让它后台跑」——
 * 用 rAF 会让日志停在切走的那一刻。setTimeout 后台只被限到 ≥1s，仍会推进。
 */
const BATCH_MS = 50;

export interface LogBuffer {
  /** 当前保留（且已封顶）的行，渲染用。 */
  events: LogEvent[];
  /** 本次任务累计收到的行数，含被封顶丢掉的。 */
  received: number;
  /** 因封顶被丢掉的最早行数。0 = 一行没丢。 */
  dropped: number;
  /** 整屏灌入（轨迹回放回填历史）或清空：待 flush 的批次一并作废。 */
  replace: (next: LogEvent[]) => void;
  /** SSE 推来一条：先进缓冲，到窗口点才进 state。 */
  push: (event: LogEvent) => void;
}

/** 实时日志的行缓冲：攒批 + 封顶 + 丢弃计数三件事收在一处。
 *
 * 要解决的原始问题：每条 SSE 事件一次 `setEvents(prev => [...prev, e])`，
 * 于是「一条事件 = 一次 render + 一次整数组拷贝」。事件密集时是 O(n²) 拷贝，
 * 且 render 次数完全跟着推送速率走 —— 攒批把两者都降到「每秒最多 20 次」。
 */
export function useLogBuffer(): LogBuffer {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [received, setReceived] = useState(0);
  const pendingRef = useRef<LogEvent[]>([]);
  const timerRef = useRef<number | null>(null);

  const cancelFlush = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const flush = useCallback(() => {
    timerRef.current = null;
    const batch = pendingRef.current;
    if (batch.length === 0) return;
    pendingRef.current = [];
    setReceived((prev) => prev + batch.length);
    setEvents((prev) => {
      /* 裁的是「合并后的尾部」，不是「塞进去之前的旧尾巴」。
         只裁 prev 的话，单批就超过上限时 slice 参数会变成负数 —— 等于没裁，
         封顶静默失效（8,000 行一次性到达时实测就是这个结果）。 */
      const merged = prev.concat(batch);
      return merged.length > MAX_LOG_EVENTS ? merged.slice(merged.length - MAX_LOG_EVENTS) : merged;
    });
  }, []);

  const push = useCallback(
    (event: LogEvent) => {
      pendingRef.current.push(event);
      if (timerRef.current === null) {
        timerRef.current = window.setTimeout(flush, BATCH_MS);
      }
    },
    [flush],
  );

  const replace = useCallback(
    (next: LogEvent[]) => {
      pendingRef.current = [];
      cancelFlush();
      const kept = next.length > MAX_LOG_EVENTS ? next.slice(next.length - MAX_LOG_EVENTS) : next;
      setEvents(kept);
      setReceived(next.length);
    },
    [cancelFlush],
  );

  // 卸载前把攒着没 flush 的行处理掉：连接由调用方断开，这里只保证不留下待触发的定时器
  useEffect(() => cancelFlush, [cancelFlush]);

  return {
    events,
    received,
    dropped: Math.max(0, received - events.length),
    replace,
    push,
  };
}
