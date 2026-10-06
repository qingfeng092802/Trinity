import type { LogEvent } from '../types';

/* 日志行的展示层合并：把**相邻且完全相同**的事件压成一行。
   纯函数、不依赖 React，放这儿是为了能在 node 里直接跑断言（见
   tools/uicheck/logRows.test.cjs）。 */

export interface LogRow {
  /** 这一串的首条事件 —— seq 用作 React key，所以重复行是**原地刷新**而不是新行。 */
  head: LogEvent;
  /** 串内共多少条事件（1 = 没有重复）。 */
  repeat: number;
  /** 串里最后一条的 idleMs（心跳帧带的是「订阅后多久没新事件」）。 */
  idleMs?: number;
}

/** 心跳这类「管道活着但没有新事件」的行，一次任务能推三十多条一模一样的。
 *  逐条堆上去会把真正有信息的节点行挤出视野，所以合并展示。
 *
 *  判定刻意保守：**相邻**且 node/level/message 三者全等才并。
 *  - 不相等的（哪怕只差一个字符）一律各占一行，不猜「大概是一回事」；
 *  - 非相邻的同文本不合并，否则会把两个阶段里的同一句话缝在一起，
 *    时间线顺序就假了。
 *  级别过滤/关键字过滤在页面那侧先做完，这里看到的已经是「要显示的」。 */
export function collapseRepeats(events: LogEvent[]): LogRow[] {
  const out: LogRow[] = [];
  for (const e of events) {
    const last = out[out.length - 1];
    if (last && last.head.node === e.node && last.head.level === e.level && last.head.message === e.message) {
      last.repeat += 1;
      if (e.idleMs !== undefined) last.idleMs = e.idleMs;
      continue;
    }
    out.push({ head: e, repeat: 1, idleMs: e.idleMs });
  }
  return out;
}

/** 被合并掉多少条（页脚要说，不能悄悄少显示）。 */
export function mergedAway(rows: LogRow[]): number {
  /** 调用计数，只给探针（`tools/uicheck/running.cjs` 的 M 趟）用。
   *
   *  为什么量这个、而不是量组件提交数：`memo` 挡住的正是"这次渲染要不要重跑下面那趟
   *  O(全部行) 的 reduce"；而组件提交数里掺了面板**自己**引起的重渲染 —— 行高是
   *  `measureElement` 动态测的，旁边浮层一开一合就可能自己重画一次 —— 拿提交数当判据
   *  会把正常的自渲染误判成 memo 失效（M 趟第一版就是这么假红的）。
   *
   *  一次属性自增，恒定执行：本项目没有 `src/vite-env.d.ts`，`import.meta.env.DEV`
   *  过不了 `tsc --noEmit`，所以不在这里判环境；探针跑在 dev 构建上，任何构建下都读得到。 */
  const w = globalThis as unknown as { __mergedAway?: { n: number } };
  (w.__mergedAway ??= { n: 0 }).n += 1;
  return rows.reduce((s, r) => s + r.repeat - 1, 0);
}
