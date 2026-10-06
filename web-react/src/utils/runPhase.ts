import type { AgentNode } from '../types';

/** 「运行结果」页签在任务跑动时那行字的唯一来源。
 *
 * 为什么单独成一个纯模块（而不是写在 ResultPane 里）：措辞的真假只能靠推理检查，
 * 拉浏览器成本高，所以判定放在 `tools/uicheck/runPhase.test.cjs`（node 直跑，
 * 与 `modelLabel.test.cjs` 同一族）。
 *
 * ⚠️ 这套映射建立在一个后端事实上：**SSE 的 `node` 事件是在节点跑完之后才发的**
 * （`api/queue.py` 的 worker 从 `runner.stream()` 拿到增量之后才 `_publish(EVT_NODE, …)`，
 * 而 LangGraph 的 `stream_mode="updates"` 本身就是"节点完成才出增量"）。
 * 所以界面上"看到了 planner 事件"= planner **已经结束**，正在跑的是它的后继。
 * 下面每条文案说的都是**那个在跑的后继**，而不是刚结束的那个节点 ——
 * 反过来写就会在每一次节点结束时谎报"正在规划"。
 *
 * 图的边（`core/workflow/graph.py:60-63`）：START → planner → executor → reviewer
 * → 条件边（通过就收口，不通过退回 executor）。前三条是**定边**，所以推断得出来；
 * reviewer 之后是条件边，所以那一档只能说"正在判断是否需要重跑"——
 * 这句话在两种结局下都为真，比猜"正在收口"诚实。
 */
export type PhaseKey = 'thinking' | 'executing' | 'reviewing' | 'routing' | 'idle';

export interface Phase {
  key: PhaseKey;
  /** 屏上那行字。缺包/未知节点一律退回通用措辞，不许编一个具体阶段。 */
  label: string;
}

const PHASES: Record<PhaseKey, string> = {
  thinking: 'Agent 正在思考...',
  executing: 'Agent 正在执行工具...',
  reviewing: 'Agent 正在复核...',
  routing: 'Agent 正在判断是否需要重跑...',
  idle: '',
};

/**
 * @param lastDone 已经收到过 `node` 事件的那个节点；一条都还没有时传 `null`。
 * @returns 任务此刻"在跑哪一段"的措辞。`key === 'idle'` 表示这一屏不该显示加载态
 *   （调用方只在 running 时才问这一步，所以这里不重复判终态）。
 */
export function phaseOf(lastDone: AgentNode | null): Phase {
  switch (lastDone) {
    case null:
      // 订上了流、还没有任何节点交卷：planner 正在跑，但"正在规划"与"正在思考"
      // 在这一刻不可区分（没有事件能证明规划已经开始），所以用通用那句。
      return { key: 'thinking', label: PHASES.thinking };
    case 'planner':
      return { key: 'executing', label: PHASES.executing };
    case 'executor':
      return { key: 'reviewing', label: PHASES.reviewing };
    case 'reviewer':
      return { key: 'routing', label: PHASES.routing };
    default:
      // 'system' 与任何后端将来新增的节点：只说在跑，不指名阶段。
      return { key: 'thinking', label: PHASES.thinking };
  }
}
