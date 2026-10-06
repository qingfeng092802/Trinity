import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import type { FieldReading } from './useAgentOptions';
import type { AgentPreset, TaskRunConfig, TaskRunConfigEcho } from '../types';

/** 运行配置草稿：只装**用户显式表达过**的意见。
 *
 * ⚠️ 键缺席 ≠ 0、≠ 默认值，而是"用户没说要改" ⇒ 这个键不进请求体。
 * 这条区分是整个面板的地基：前端一旦替后端补一个默认值，就有了第二份口径，
 * 而后端那份才是真跑的那份（方案 §2 规矩 3、§4 P-8）。
 * 原来那个"最大迭代轮数 3"在界面上写了四处，后端默认是 5 —— 说谎的一直是界面。 */
export interface RunConfigDraft {
  max_iterations?: number;
  review_threshold?: number;
  max_cost_cny?: number;
  timeout_s?: number;
  rag_top_k?: number;
  use_tools?: boolean;
}

/** 数值键（预设与表单都只往这几个键上写；``use_tools`` 走开关那条路）。
 *
 * ⚠️ 这份名单只管"哪些键是数字"，不管叫什么、什么单位、界是多少 —— 那些都在
 * ``GET /config/agent-options`` 里。名单漏了一个键的后果不是错数，而是**那一行没有控件**
 * （``NumericRow`` 只渲染这里列出的键），所以后端新加数值键时由
 * ``unrecognizedOf().unrowedFields`` 在面板上点名，不让它静默。 */
const NUMERIC_KEYS = [
  'max_iterations',
  'review_threshold',
  'max_cost_cny',
  'timeout_s',
  'rag_top_k',
] as const;
type NumericKey = (typeof NUMERIC_KEYS)[number];

interface RunConfigValue {
  draft: RunConfigDraft;
  /** 被用户取消勾选的工具名。空数组 = 一个都没动 ⇒ **不发** ``enabled_tools``（= 后端全量）。 */
  disabledTools: string[];
  /** 当前套用的预设 id；手动改过任何一项就回 null（预设是起点，不是活绑定） */
  presetId: string | null;
  setNumeric: (key: NumericKey, value: number | undefined) => void;
  setUseTools: (on: boolean) => void;
  setToolEnabled: (name: string, on: boolean) => void;
  applyPreset: (preset: AgentPreset | null) => void;
  reset: () => void;
}

const RunConfigContext = createContext<RunConfigValue | null>(null);

/** 运行配置的唯一宿主。
 *
 * 为什么必须是 Context 而不是 AntD ``Form`` 的 store（U-5）：
 * 「运行配置」弹层是**懒挂载**的，字段住在 Form 里就得靠"注册"才进得了提交体 ——
 * 这个坑本项目踩过两次（``max_iterations`` 整键消失、``useRag`` 恒 undefined 让
 * 每条任务都悄悄排除掉知识库检索，而界面显示"开"）。搬进 Context 之后，
 * "没点开弹层"与"字段没进请求体"这两件事**在结构上不再有关联**，
 * 第三次踩坑需要有人新写一份本地 state —— 那正是 AD 趟负面对照盯的东西。
 *
 * 也不用 zustand：它在 package.json 里但全仓零 import，而
 * ``useRefresh`` / ``useTasklist`` / ``useThemeMode`` 已经是同一个形状的 Context。 */
export function RunConfigProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<RunConfigDraft>({});
  const [disabledTools, setDisabledTools] = useState<string[]>([]);
  const [presetId, setPresetId] = useState<string | null>(null);

  /* 任何一次手动改动都把预设标记成"已经不是那一档了"。
     不清的话，用户把迭代从 2 改成 9、面板顶部仍显示"快速模式"，
     那是拿一个已经不成立的标签盖住真实配置。 */
  const markDirty = useCallback(() => setPresetId(null), []);

  const setNumeric = useCallback(
    (key: NumericKey, value: number | undefined) => {
      markDirty();
      setDraft((prev) => {
        // 清空输入框 = 撤回这条意见，不是"改成 0"、也不是"改成默认值"。
        if (value === undefined || Number.isNaN(value)) {
          if (prev[key] === undefined) return prev;
          const next = { ...prev };
          delete next[key];
          return next;
        }
        if (prev[key] === value) return prev;
        return { ...prev, [key]: value };
      });
    },
    [markDirty],
  );

  const setUseTools = useCallback(
    (on: boolean) => {
      markDirty();
      setDraft((prev) => ({ ...prev, use_tools: on }));
    },
    [markDirty],
  );

  const setToolEnabled = useCallback(
    (name: string, on: boolean) => {
      markDirty();
      setDisabledTools((prev) => {
        const has = prev.includes(name);
        if (on && has) return prev.filter((x) => x !== name);
        if (!on && !has) return [...prev, name];
        return prev;
      });
    },
    [markDirty],
  );

  const applyPreset = useCallback((preset: AgentPreset | null) => {
    if (preset === null) {
      // 「不套预设」：把预设能写的那几个键撤回，工具勾选与 use_tools 不动 ——
      // 预设不该偷偷改用户没让它改的东西。
      setPresetId(null);
      setDraft((prev) => {
        const next: RunConfigDraft = {};
        if (prev.use_tools !== undefined) next.use_tools = prev.use_tools;
        return next;
      });
      return;
    }
    setPresetId(preset.id);
    setDraft((prev) => {
      const next: RunConfigDraft = {};
      if (prev.use_tools !== undefined) next.use_tools = prev.use_tools;
      for (const key of NUMERIC_KEYS) {
        const raw = preset.values?.[key];
        if (typeof raw === 'number' && Number.isFinite(raw)) next[key] = raw;
      }
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setDraft({});
    setDisabledTools([]);
    setPresetId(null);
  }, []);

  const value = useMemo(
    () => ({ draft, disabledTools, presetId, setNumeric, setUseTools, setToolEnabled, applyPreset, reset }),
    [draft, disabledTools, presetId, setNumeric, setUseTools, setToolEnabled, applyPreset, reset],
  );

  return <RunConfigContext.Provider value={value}>{children}</RunConfigContext.Provider>;
}

export function useRunConfig(): RunConfigValue {
  const ctx = useContext(RunConfigContext);
  if (!ctx) throw new Error('useRunConfig 必须在 RunConfigProvider 内使用');
  return ctx;
}

/** 把 Context 里的状态算成请求体（**纯函数**，单独导出是为了能被 node 侧用例直接打）。
 *
 * 三条规则：
 * 1. 没表达过意见的键一个都不发（``undefined`` 不进对象）；
 * 2. 工具白名单只在"用户真的取消勾选过某项"**且**拿得到全量清单时才发，
 *    发的是"全量减掉未勾选项"的完整名单 —— 绝不再发一份前端抄来的固定名单；
 * 3. 清单里一个都没勾（全量减完为空）时**不发空数组**：后端把空列表判 422，
 *    而"什么都不许用"本来也不是这里能表达的意图（要那个请用 ``use_tools=false``）。
 *
 * @param draft 用户显式改过的数值与开关
 * @param disabledTools 被取消勾选的工具名
 * @param allToolNames ``GET /tools`` 的真实清单；空数组 = 没读到 ⇒ 不发白名单
 */
export function buildRunConfigBody(
  draft: RunConfigDraft,
  disabledTools: string[],
  allToolNames: string[],
): TaskRunConfig {
  const body: TaskRunConfig = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value !== undefined) (body as Record<string, unknown>)[key] = value;
  }
  if (disabledTools.length > 0 && allToolNames.length > 0) {
    const allowed = allToolNames.filter((name) => !disabledTools.includes(name));
    if (allowed.length > 0) body.enabled_tools = allowed;
  }
  return body;
}

/** 「RAG」快捷开关的读数：从**同一份** ``disabledTools`` 派生，不是第二个 state。
 *
 * @param ragTool 后端告诉前端"RAG 开关管的是哪个工具名"（``tools.rag_tool``）
 * @returns ``null`` = 不知道管谁（老后端 / 该工具没注册）⇒ 界面把开关置灰并说明原因，
 *          而不是拿一份猜的名字去算白名单。 */
export function deriveRagOn(ragTool: string | null | undefined, disabledTools: string[]): boolean | null {
  if (!ragTool) return null;
  return !disabledTools.includes(ragTool);
}

/** 把一份运行配置的值渲染成读数。**面板上的"后端默认 X"与回执对账那两行**共用它。
 *
 * ⚠️ 为什么必须是同一个函数：这一屏有两个地方要说出同一个数（输入框旁边的默认值、
 * 提交后核对回执的告警）。分开格式化就会出现"预算 ¥0.36 / 0.36 元 / 0.4"三种写法，
 * 而三种写法里总有一份是在说另一件事 —— 与单价口径三处必须同一个函数是同一条纪律。
 *
 * 名字与单位（``label`` / ``unit``）都来自 ``fields[]``，这里**不写任何字段名**：
 * 原先这张表在 ``useRunConfig`` 里自带一份（``max_cost_cny: '成本预算上限'``），
 * 后端给的是"最大成本预算" ⇒ 同一屏两个名字，正是 R-03 那条先例要拆的东西。
 *
 * @param reading 该键的读数材料；``undefined`` = 后端没声明这个键 ⇒ 只报裸值，不猜单位
 */
export function formatFieldValue(value: unknown, reading?: FieldReading): string {
  if (value === null || value === undefined) return '未收下';
  if (typeof value === 'boolean') return value ? '开' : '关';
  if (typeof value === 'number') {
    // 钱用 ¥ 前缀（全站成本读数的既有口径），其余数值带后端给的单位。
    // 刻意不写成 "0.35 元" —— 同一个读数里说两遍货币单位，是这一轮清单反掉的形状。
    if (reading?.kind === 'money') return `¥${value.toFixed(2)}`;
    return reading?.unit ? `${value} ${reading.unit}` : String(value);
  }
  if (Array.isArray(value)) return `${value.length} 项（${value.join('、')}）`;
  return String(value);
}

function sameConfigValue(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i])
    );
  }
  return a === b;
}

/** 比对「我发出去的」与「服务端回执里真正收下的」，返回要写进实时日志的告警行。
 *
 * 存在的理由（方案 P-1）：``TaskSubmitRequest`` 的 ``extra`` 策略是**忽略未知键**，
 * 所以一台没重启的后端收到 ``max_cost_cny`` 不会报错、不会 422，只会当没看见，
 * 然后按自己的默认值把钱花下去。前端如果只按自己发出去的那份显示"预算 ¥0.36"，
 * 界面就在替用户编一个不存在的闸门 —— 这一条就是为了让那件事**看得见**。
 *
 * 三条口径：
 * 1. 一个字都没发（后端默认）⇒ 一行都不说，不打扰；
 * 2. 回执整体缺席 ⇒ 说一次"未回报"，逐条列出发出去的键（不假装收下）；
 * 3. 回执里有这一项但值不同（含被钳制、被丢弃）⇒ 逐条报"发的是 X，服务端用的是 Y"。
 *
 * 纯函数、不碰 React，所以 AD 趟与 node 侧用例可以直接打它。
 *
 * @param readings ``fields[]`` 摊出来的读数材料（名字 + 单位）；某个键不在里面就用原始 key。
 */
export function echoDiffLines(
  config: TaskRunConfig,
  echo: TaskRunConfigEcho | null | undefined,
  readings: Record<string, FieldReading> = {},
): string[] {
  const sent = Object.entries(config).filter(([, v]) => v !== undefined);
  if (!sent.length) return [];
  const line = ([k, v]: [string, unknown]) =>
    `${readings[k]?.label ?? k}=${formatFieldValue(v, readings[k])}`;
  if (!echo) {
    return [
      `后端未回报运行配置，本次发出的 ${sent.length} 项设置无法确认是否被收下：` +
        sent.map(line).join('、') +
        '。（旧版本后端会静默忽略这些字段，实际按后端默认值运行）',
    ];
  }
  const lines: string[] = [];
  for (const [key, value] of sent) {
    const reading = readings[key];
    const label = reading?.label ?? key;
    if (!(key in echo)) {
      lines.push(`${label}：发出的是 ${formatFieldValue(value, reading)}，回执里没有这一项 ⇒ 服务端未确认收下`);
      continue;
    }
    const got = (echo as unknown as Record<string, unknown>)[key];
    if (!sameConfigValue(value, got)) {
      lines.push(
        `${label}：发出的是 ${formatFieldValue(value, reading)}，服务端实际用的是 ${formatFieldValue(got, reading)}`,
      );
    }
  }
  return lines;
}
