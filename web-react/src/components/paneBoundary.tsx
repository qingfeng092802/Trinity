import type { ReactNode } from 'react';

import ErrorBoundary from './ErrorBoundary';

/** 页签内容 → 统一包一层错误边界（U-7 要求"复用"，不是"抄同一份写法"）。
 *
 * 为什么只能有一份：这两处（`TaskLogPage` 的三个页签、`RunConfigPanel` 的基础/模型/高级）
 * 防的是同一个失效 —— 一块渲染抛错把整棵外壳带走，用户只剩「刷新」。写法各写一遍，
 * 迟早有一边改了兜底文案、另一边的判据跟着失效却没人知道（本轮就撞到过一次：
 * 面板那版把边界名写成了 ``basic 页签``，弹层里的兜底卡于是中英混着出现，
 * 而截图判据只看"有没有塌到整页"，看不见这行小字）。
 *
 * `paneName` 一律传**给用户看的那三个字**（实时日志 / 运行结果 / 工具调用 / 基础 / 模型 / 高级），
 * 不要传路由 key —— 这行字会出现在兜底卡上，是用户唯一能读到的"哪儿塌了"。 */
export function withPaneBoundary(paneName: string, children: ReactNode): ReactNode {
  return <ErrorBoundary label={`${paneName}页签`}>{children}</ErrorBoundary>;
}
