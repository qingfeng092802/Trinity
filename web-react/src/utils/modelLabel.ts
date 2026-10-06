import type { ModelListResponse, ModelSpecView } from '../types';

/** ``GET /models`` 的展示层措辞。
 *
 * 刻意做成**纯函数**：模型条是「这次到底在调什么模型、按什么价记账」的事实陈述，
 * 措辞错了就是页面在说谎，而说谎不该等到浏览器里才发现 ——
 * 断言在 ``tools/uicheck/modelLabel.test.cjs``（node 直跑，不拉 React）。
 *
 * 三条硬规则：
 * 1. **拉不到就不显示**：返回空串，调用方据此整条不渲染。宁可少一行信息，
 *    也不回落到一份写死的模型清单（上一版就是这么错的：选项躺在 mock 文件里，
 *    后端根本没有对应字段）。
 * 2. **兜底价不许叫官方价**：``price_source = settings_fallback`` 时明说
 *   「单价取兜底值」，不与「官方高峰价」混成同一种语气。
 * 3. **两档不同必须都露出来**：只显示大档会让人觉得"全程用它"，那是另一种误导。
 */

const ROLE_LABELS: Record<string, string> = {
  planner: '规划',
  executor: '执行',
  reviewer: '评审',
  judge: '裁判',
  extract: '抽取工具',
};

const TIER_LABELS: Record<string, string> = { large: '强模型', small: '快模型' };

/** 人民币单价：两位小数（``¥2.13``），与全站「百分比两位、金额两位」的口径一致。 */
function cny(value: number): string {
  return `¥${value.toFixed(2)}`;
}

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

function byTier(items: ModelSpecView[], tier: ModelSpecView['tier']): ModelSpecView | undefined {
  return items.find((i) => i.tier === tier);
}

/** 胶囊上那行字：``模型 deepseek-v4-pro +deepseek-flash``（两档同一模型时不带 ``+``）。 */
export function modelChipText(reg: ModelListResponse | null): string {
  const items = reg?.items ?? [];
  if (!items.length) return '';
  const large = byTier(items, 'large') ?? items[0];
  const small = byTier(items, 'small');
  if (!small || small.id === large.id) return `模型 ${large.id}`;
  return `模型 ${large.id} +${small.id}`;
}

/** 悬停明细：每个模型一行「角色｜进出单价｜价的来路」，末尾两行交代峰谷口径与「为何不可切换」。 */
export function modelTooltipLines(reg: ModelListResponse | null): string[] {
  if (!reg || !reg.items.length) return [];
  /* 只有一条 ⇒ 两档配的是同一个模型（后端已经合并成一行）。此时前缀写「强模型」会让
     人以为还有个快模型没露出来 —— 而那恰恰是这件事要说清的反面，所以换一种说法。 */
  const merged = reg.items.length === 1;
  const lines = reg.items.map((item) => {
    const roles = item.roles.map(roleLabel).join('/');
    const price = `${cny(item.price_in_per_million_cny)} 进 / ${cny(
      item.price_out_per_million_cny,
    )} 出 每 100 万 token`;
    // 来路必须分开写：把兜底单价说成「官方价」就是替后端圆场
    const source = item.price_source === 'official_table' ? '表内价' : '兜底价';
    /* 阶梯模型（智谱、千问按输入长度分档）在服务端报的是**最低档** —— 那是一个下界，
       不写清楚就等于把一个"看起来对"的数当成唯一口径（长上下文会比它贵）。 */
    const floor = item.tiered ? '（最低档，按输入长度跳档）' : '';
    const prefix = merged ? '两档同一个模型' : TIER_LABELS[item.tier] ?? item.tier;
    return `${prefix} ${item.id}｜${roles}｜${price}${floor} · ${source}`;
  });
  /* 峰谷口径只对**分峰谷计价**的家成立（目前只有 DeepSeek）。旧版无条件印这一句，
     换到智谱 / 千问之后就是在替一个不存在的折扣做说明 —— 与「兜底价不许叫官方价」同一类。
     ``peak_off_peak`` 缺失（重启前的老后端）时按老语义走，不因此少一行信息。 */
  const splitsPeak = reg.items.some((item) => item.peak_off_peak !== false);
  lines.push(
    splitsPeak
      ? `低谷时段系数 ×${reg.off_peak_multiplier} · ${reg.pricing_basis}`
      : `这家不分高峰 / 低谷 · ${reg.pricing_basis}`,
  );
  /* 「不在页面里切换」这句在齿轮出现之后就成假话了 —— 改成说清**在哪改、改了影响什么**：
     生效范围（之后新建的任务）与存续期（重启回落到 .env）都必须在这一行里，
     否则用户会以为改完立刻全局生效。 */
  lines.push('改模型：右上角「模型设置」齿轮 · 只影响之后新建的任务 · 重启后回落到 .env');
  return lines;
}
