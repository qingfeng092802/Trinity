import { useQuery } from '@tanstack/react-query';

import { fetchAgentOptions } from '../api/client';
import type { AgentFieldSpec, AgentNumericLimit, AgentOptionsResponse } from '../types';
import { AGENT_FIELD_KNOWN_KINDS, AGENT_NUMERIC_KINDS, AGENT_OPTIONS_KNOWN_KEYS } from '../types';

/** 运行配置选项的查询键（面板、composer 那行读数、快捷开关共用同一份缓存）。 */
export const AGENT_OPTIONS_QUERY_KEY = ['agent-options'] as const;

/** ``GET /config/agent-options`` 的原始结果。``null`` = 还在拉 / 拉失败 / 老后端 404。
 *
 * ⚠️ 拉不到时**不许**回落到一份本地默认值 —— 那等于把"前端替后端决定默认值"
 * 这个刚被拆掉的病灶原地养回来。调用方的义务是：整块降级 + 请求体里只发 ``task``。 */
export function useAgentOptions(): AgentOptionsResponse | null {
  const { data } = useQuery({ queryKey: AGENT_OPTIONS_QUERY_KEY, queryFn: fetchAgentOptions });
  return data ?? null;
}

/** 某个数值字段的界。``null`` = 后端没说 ⇒ 调用方**不要渲染输入框**，
 *  而不是自己补一个 min/max（没有界就意味着前端填什么都是"发明"）。 */
export function limitOf(
  options: AgentOptionsResponse | null,
  key: string,
): AgentNumericLimit | null {
  const raw = options?.limits?.[key];
  if (!raw || typeof raw.min !== 'number' || typeof raw.max !== 'number') return null;
  return raw;
}

/** 后端给的默认值。``undefined`` 是**有意义的**："这一项不设限"（预算 / 超时 / top_k）。
 *  所以这里不做 ``?? 0`` 那种合并 —— 那会把"不设限"变成"预算 0 元"。 */
export function defaultOf(
  options: AgentOptionsResponse | null,
  key: string,
): number | string | boolean | null | undefined {
  return options?.defaults?.[key];
}

/** 某个键的能力声明（收不收 / 有没有用 / 生效条件原话）。 */
export function fieldOf(
  options: AgentOptionsResponse | null,
  key: string,
): AgentFieldSpec | null {
  return options?.fields?.find((f) => f.key === key) ?? null;
}

/** 后端**收不下**的键（``accepted=false``）⇒ 界面只列名字与原因，不给控件。 */
export function unsupportedFields(options: AgentOptionsResponse | null): AgentFieldSpec[] {
  return (options?.fields ?? []).filter((f) => f.accepted === false);
}

/** 某个键的单位后缀（``fields[].unit``）。``null`` = 后端没说 ⇒ 界面**不加后缀**，
 *  而不是猜一个"次"或"轮" —— 单位是后端事实，写第二份就有人对账对不上。 */
export function unitOf(options: AgentOptionsResponse | null, key: string): string | null {
  return fieldOf(options, key)?.unit ?? null;
}

/** 收了但**没有执行机制**的键（``accepted=true, enforced=false``）。
 *  这一档最危险：填得进去、发得出去，只是什么都不发生。界面必须单独说。 */
export function unenforcedFields(options: AgentOptionsResponse | null): AgentFieldSpec[] {
  return (options?.fields ?? []).filter((f) => f.accepted === true && f.enforced === false);
}

/** 后端多出来的、前端不认识的东西 —— 顶层键、不认识的 ``kind``、"有界但没声明收不收"的键、
 * "声明可配却**没有行**的数值键"，四处都算。
 *
 * 为什么必须列出来而不是忽略：静默隐藏未知配置 = 让"后端已经支持某件事"这件事
 * 在界面上永远看不见，而下一个人只会以为前端漏做了。列出来也不当默认值用。
 *
 * 第三类（``undeclaredLimits``）单独说：``limits`` 里给了某个键的界，``fields`` 里却没有
 * 这个键的 accepted/enforced 声明 —— 按纪律**不给控件**（不知道收不收就填值是赌），
 * 但也不能什么都不说，否则"后端已经准备了这一档"这条线索就消失了。
 *
 * 第四类（``unrowedFields``）是第三类的镜像，也是 ``review_threshold`` 这一轮踩出来的：
 * 后端在 ``fields`` 里声明"这个数值键收、也执行"，而前端这一版的行表里**没有它** ——
 * 按 ``NumericRow`` 的纪律不会渲染任何控件，于是"能配"这件事只在后端成立。
 * 没有这一栏，那种缺口是**静默**的；有了它，面板至少会点名。
 *
 * @param renderedKeys 前端真的给了行的键名（由 :mod:`components/RunConfigPanel` 传进来，
 *                     它才是"哪些键有行"的唯一权威）
 */
export function unrecognizedOf(
  options: AgentOptionsResponse | null,
  renderedKeys: readonly string[] = [],
): {
  topKeys: Record<string, unknown>;
  fieldKinds: AgentFieldSpec[];
  undeclaredLimits: string[];
  unrowedFields: AgentFieldSpec[];
} {
  if (!options) {
    return { topKeys: {}, fieldKinds: [], undeclaredLimits: [], unrowedFields: [] };
  }
  const topKeys: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(options)) {
    if (!AGENT_OPTIONS_KNOWN_KEYS.includes(key)) topKeys[key] = value;
  }
  const fields = options.fields ?? [];
  const fieldKinds = fields.filter((f) => !AGENT_FIELD_KNOWN_KINDS.includes(f.kind));
  const declared = new Set(fields.map((f) => f.key));
  const undeclaredLimits = Object.keys(options.limits ?? {}).filter((k) => !declared.has(k));
  const rendered = new Set(renderedKeys);
  const unrowedFields = fields.filter(
    (f) => f.accepted === true && AGENT_NUMERIC_KINDS.includes(f.kind) && !rendered.has(f.key),
  );
  return { topKeys, fieldKinds, undeclaredLimits, unrowedFields };
}

/** 一个键的**读数材料**：名字、控件类型、单位，全部取自 ``fields[]``。
 *
 * 存在的理由是把"这一项叫什么、带什么单位"收成一个来源。回执对账（``echoDiffLines``）
 * 原来在 :mod:`hooks/useRunConfig` 里自带一张 ``CONFIG_LABELS``，写的是"成本预算上限"，
 * 而后端 ``label`` 是"最大成本预算" —— 同一屏两个名字，正是这一轮要拆的形状。
 * ⚠️ 后端没给的键就**不给读数**（界面回落到原始 key），不猜措辞也不猜单位。 */
export interface FieldReading {
  label: string;
  kind: string;
  unit: string | null;
}

/** 单个键的读数材料。``undefined`` = 后端没声明这个键 ⇒ 调用方回落到原始 key，不猜。 */
export function readingOf(
  options: AgentOptionsResponse | null,
  key: string,
): FieldReading | undefined {
  const f = fieldOf(options, key);
  return f ? { label: f.label, kind: f.kind, unit: f.unit ?? null } : undefined;
}

export function fieldReadingsOf(
  options: AgentOptionsResponse | null,
): Record<string, FieldReading> {
  const map: Record<string, FieldReading> = {};
  for (const f of options?.fields ?? []) {
    map[f.key] = { label: f.label, kind: f.kind, unit: f.unit ?? null };
  }
  return map;
}

/** 三档预设。后端没给就是**没有**这一栏（不是"前端自己造三档"）。 */
export function presetsOf(options: AgentOptionsResponse | null) {
  const presets = options?.presets;
  return Array.isArray(presets) ? presets : [];
}
