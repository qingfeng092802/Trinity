/** 探针用的渲染账本（M / U 两趟读它；产品代码不读）。
 *
 *  两枚计数，别混用 —— 它们回答的是两个不同的问题：
 *
 *  1. `bumpCommit(id, ms)`：**提交**计数，挂在 `<Profiler onRender>` 上。
 *     问的是"这一帧这块子树落没落地"。StrictMode 把渲染跑两遍**不会**把它翻倍
 *     （onRender 一次提交只回调一次），所以它适合当"某件事确实发生了"的证据。
 *     生产构建里 React 根本不调 onRender（只有 dev / profiling 版回调），
 *     所以这些插桩不会带进 dist；探针跑在 5173 的 dev 构建上。
 *
 *  2. `bumpRender(key)`：**组件函数体执行**计数，写在组件自己第一行。
 *     问的是"这个组件白渲染了没有"—— 这正是 `memo` 该不该挡住的判据。
 *     ⚠️ 别拿 Profiler 的提交数去判 memo 挡没挡住：实测父级每重渲染一次，
 *     Profiler 自己就是一次 commit，memo 挡得住子组件、挡不住 Profiler
 *     （读数 3→7，而被 memo 的那棵子树一次都没重渲染）。踩过的坑，实测在
 *     tools/uicheck/README.md 的 U 节。
 */

type Ledger = Record<string, number>;

const led = (): Ledger => {
  const w = globalThis as unknown as { __renders?: Ledger };
  return (w.__renders ??= {});
};

export function bumpCommit(id: string, actualDurationMs: number): void {
  const l = led();
  l[id] = (l[id] ?? 0) + 1;
  l[`${id}Ms`] = (l[`${id}Ms`] ?? 0) + actualDurationMs;
}

export function bumpRender(key: string): void {
  const l = led();
  l[key] = (l[key] ?? 0) + 1;
}

/** 读一枚计数；插桩没挂上时返回 -1，让断言以"值不对"失败而不是静默读到 undefined。 */
export function renderCount(key: string): number {
  return led()[key] ?? -1;
}
