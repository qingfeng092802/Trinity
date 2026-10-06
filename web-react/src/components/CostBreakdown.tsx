import { memo, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Chip, ScrollXFrame, SparkBar } from './ui';
import { fetchCostBreakdown } from '../api/client';
import { fmtCostFixed, fmtInt } from '../utils/format';
import { NODE_META, nodeColorVar } from '../theme';
import type { AgentNode, CostRoleRow } from '../types';

/** 成本归因面板（C1–C7）。
 *
 * 回答一个问题：**这次的钱花在哪儿了** —— 哪个角色、哪个模型、乘了 1.0 还是 0.5。
 * 需求出处是用户那句「为什么同样的 1+1，一次 0.0039 元一次 0.0094 元」，
 * 结论（2.00× 时段 × 1.16× 用量，模型没换）在 `utils/costNote.ts` 与
 * `docs/cost_attribution_plan_2026-09-25.md` §1.5。
 *
 * 三条口径上的讲究，都是这一轮量出来的：
 *
 * 1. **合计只吃端点，不吃明细**（`api/client.ts` 的 `fetchCostBreakdown`）：
 *    轨迹明细那条路有 500 条封顶，超了会**静默少加**。
 * 2. **时段一律用后端给的绝对时刻**：`tasks.created_at` 是 UTC，而计费判档按北京时间，
 *    前端自己算会整体错 8 小时。本组件里**没有任何一处读 `Date.now()`** ——
 *    包括那个「下一次进入低谷」的读数（探针 AA 钉这条：改系统时间读数不许动）。
 * 3. **`null` 就是「没记录」**：不补 1.0、不补「高峰」、不拿当前配置里的模型名去顶。
 *    所以每一处系数/模型都写成「有值才说话」，缺值时那半句整条不出现。
 */

/** 「未记录」的统一措辞。刻意不写 0、也不写空白 —— 空白会被读成「没有这笔钱」。 */
const UNRECORDED = '未记录';

/** 系数 + 「这家分不分峰谷」→ 可读档位。
 *
 *  为什么不单看系数：``1.0`` 有两种完全不同的来历 —— DeepSeek 的高峰档，
 *  和智谱 / 千问那种**根本没有峰谷档**的家（记账时系数恒为 1.0，意思是"没有折扣"）。
 *  旧实现 ``multiplier === 1 ⇒ 高峰`` 会把后者说成前者：金额没错，标签在说谎。
 *  所以起名要问服务端给的 ``peak``：``null`` 且系数是 1.0 ⇒ 「不分峰谷」，
 *  系数本身没记进库 ⇒ 仍然老实写「未记录」。
 *
 *  其余取值（0.75、以后可能加的第二档）一律走「未记录」——
 *  写 ``m >= 1 ? '高峰' : '低谷'`` 会把不知道的东西归进两档之一。 */
function tierLabel(multiplier: number | null, peak: boolean | null = null): string {
  if (multiplier === null) return UNRECORDED;
  if (peak === null) return multiplier === 1 ? '不分峰谷' : UNRECORDED;
  return peak ? '高峰' : '低谷';
}

/** 后端时间串 → ``HH:mm``，**纯字符串切片**。
 *
 *  ⚠️ 这里绝不能用 `new Date(s).getHours()`：那个串是北京时间（带 ``+08:00``），
 *  而 `getHours()` 会先换算到**浏览器所在时区** —— 一台 UTC 机器上 18:00 会印成 10:00，
 *  恰好把「什么时候进低谷」这件最重要的事说错。后端已经换算好并带了偏移，
 *  要的是「它写的那个数」，不是「换算后的个数」。 */
function hhmmFromBeijingIso(iso: string | null): string | null {
  if (!iso) return null;
  const match = /T(\d{2}:\d{2})/.exec(iso);
  return match ? match[1] : null;
}

/** 角色 → 填充色。``judge`` 与 ``null`` 没有专属节点色，落到 system 那一档 ——
 *  关键是**不许**复用状态色（成功绿/失败红），那会让「哪个角色贵」和「这次成功没」
 *  共用一套色阶，两个语义互相污染。 */
function roleFill(role: string | null): string {
  const known: AgentNode[] = ['planner', 'executor', 'reviewer', 'system'];
  const node = role && (known as string[]).includes(role) ? (role as AgentNode) : 'system';
  return nodeColorVar(node, 'fill');
}

function roleLabel(role: string | null): string {
  if (!role) return UNRECORDED;
  const meta = (NODE_META as Record<string, { label: string; glyph: string }>)[role];
  if (meta) return `${meta.glyph} ${meta.label}`;
  // judge（裁判打分档）与库里可能出现的任何未知角色：原样回显，不硬归到四类里
  return role;
}

export interface CostBreakdownProps {
  taskId: string;
  /** 运行中**不拉**（决策 D5）：半程的合计会被当成成品账看。传进来只用来挡请求，
   *  渲染层不再自己判任务状态 —— 状态由调用方（结果页）持有。 */
  enabled: boolean;
}

const CostBreakdown = memo(function CostBreakdown({ taskId, enabled }: CostBreakdownProps) {
  const query = useQueryCostBreakdown(taskId, enabled);
  const data = query.data;

  /** 每个档位一个小计 —— 「跨峰谷」这件事要说得出金额，不然只是句空话。
   *
   *  分组键必须带上 ``peak``：同一个 ``1.0`` 可能来自 DeepSeek 的高峰，
   *  也可能来自根本不分峰谷的智谱 / 千问。只按系数分组会把两件事加成一个数、
   *  再贴一个标签 —— 金额是对的，标签对其中一半是错的。 */
  const tiers = useMemo(() => {
    const rows = data?.by_role ?? [];
    const map = new Map<
      string,
      { multiplier: number | null; peak: boolean | null; cost: number; calls: number }
    >();
    for (const row of rows) {
      const key = `${row.price_multiplier ?? 'null'}|${row.peak ?? 'null'}`;
      const prev =
        map.get(key) ?? { multiplier: row.price_multiplier, peak: row.peak, cost: 0, calls: 0 };
      prev.cost += row.cost;
      prev.calls += row.calls;
      map.set(key, prev);
    }
    return [...map.values()].sort((a, b) => b.cost - a.cost);
  }, [data]);

  const segments = useMemo(
    () =>
      (data?.by_role ?? []).map((row) => ({
        value: row.cost,
        color: roleFill(row.role),
        /* label 里带上档位：同一角色跨峰谷会有两段同色，只写"Planner"的话
           读屏听到的是一串无法区分的重名（AA 趟 4d 按这个断言）。 */
        label: `${roleLabel(row.role)} ${tierLabel(row.price_multiplier, row.peak)}`,
        // readout 给"看得懂的钱数"，不让 value 那个原始浮点直接进 aria-label / title
        readout: fmtCostFixed(row.cost, 4),
      })),
    [data],
  );

  if (query.isError) {
    // 拉不到就明说拉不到，并且**不许**退回一份前端自己加的数（那会是第二个口径）。
    return (
      <section className="cost-panel cost-panel--error" aria-label="成本归因">
        <span className="cost-lead">成本归因没取到</span>
        <p className="cost-note">
          {query.error instanceof Error ? query.error.message : '未知错误'} · 上面的「总 token」与
          花费读数不受影响（那是任务详情里带来的）。
        </p>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="cost-panel" aria-label="成本归因">
        <span className="cost-lead">{query.isLoading ? '正在算这次的花费…' : '暂无成本数据'}</span>
      </section>
    );
  }

  const { totals, by_role: rows, window, price_check: check, reconcile } = data;

  return (
    <section className="cost-panel" aria-label="成本归因">
      <div className="cost-head">
        <div className="cost-figure">
          {/* 只报钱。总 token 上面那格「总 token」已经报了，同一屏摆两份同数是
              用户明确否掉的（两份读数哪天漂了，读者无从判断信哪个）。 */}
          <span className="cost-total">{fmtCostFixed(totals.cost, 4)}</span>
          <span className="cost-total-hint">
            {fmtInt(totals.calls)} 次 LLM 调用 · {rows.length} 个「角色×模型×档位」组合
          </span>
        </div>
        <div className="cost-chips" role="group" aria-label="计费档位构成">
          {tiers.map((tier) => {
            const label = tierLabel(tier.multiplier, tier.peak);
            /* 「不分峰谷」不配占用高峰/低谷那一对色 —— 那是"折扣存不存在"的色阶。
               它走中性档：语义不同就不给同一个颜色，否则三种档位看着像两种。 */
            const channel =
              tier.peak === null
                ? tier.multiplier === 1
                  ? 'neutral'
                  : 'unknown'
                : tier.peak
                  ? 'peak'
                  : 'offpeak';
            return (
              <Chip
                key={`${tier.multiplier}|${tier.peak}`}
                tone={
                  channel === 'peak' || channel === 'offpeak'
                    ? {
                        fg: `var(--cost-${channel})`,
                        soft: `var(--cost-${channel}-soft)`,
                      }
                    : { fg: 'var(--text-2)', soft: 'var(--bg-surface-2)' }
                }
                title={
                  tier.multiplier === null
                    ? `这一档的系数没记进库（这条任务跑在 model / price_multiplier 两列落地之前），金额 ${fmtCostFixed(tier.cost, 4)}`
                    : tier.peak === null
                      ? `${tier.calls} 次调用来自**不分高峰/低谷**的供应商，系数恒 ×${tier.multiplier}，金额 ${fmtCostFixed(tier.cost, 4)}`
                      : `${tier.calls} 次调用按 ×${tier.multiplier} 计，金额 ${fmtCostFixed(tier.cost, 4)}`
                }
              >
                {label} ×{tier.multiplier ?? UNRECORDED} · {fmtCostFixed(tier.cost, 4)}
              </Chip>
            );
          })}
        </div>
      </div>

      {segments.length > 0 && <SparkBar segments={segments} />}

      <ScrollXFrame label="成本按角色与模型的明细表">
        <table className="cost-table">
          <caption className="sr-only">
            按（角色、模型、计费档位）聚合的本次运行用量与花费，按金额倒序
          </caption>
          <thead>
            <tr>
              <th scope="col">角色</th>
              <th scope="col">模型</th>
              <th scope="col" className="cost-num">
                次数
              </th>
              <th scope="col" className="cost-num">
                入 token
              </th>
              <th scope="col" className="cost-num">
                出 token
              </th>
              <th scope="col">档位</th>
              <th scope="col" className="cost-num">
                单价（元/百万）
              </th>
              <th scope="col" className="cost-num">
                花费
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <CostRow key={`${row.role ?? 'null'}|${row.model ?? 'null'}|${row.price_multiplier ?? 'null'}`} row={row} />
            ))}
          </tbody>
        </table>
      </ScrollXFrame>

      {/* ③ 时段：全部读后端。这一行说的是「查询此刻」，与上面那排 chip 说的
          「本次跑在哪一档」是两件事，措辞上必须分得开。 */}
      <div className="cost-window">
        <span className="cost-window-now">
          查询此刻：{window.is_peak_now ? '高峰' : '低谷'} ×{window.multiplier_now} ·{' '}
          {window.window_desc}
        </span>
        {window.next_off_peak_at ? (
          <span className="cost-window-next">
            想省钱就把这条留到 <b>{hhmmFromBeijingIso(window.next_off_peak_at)}</b> 之后再跑
          </span>
        ) : (
          <span className="cost-window-next">现在正是低谷，跑什么都比白天便宜一半</span>
        )}
      </div>

      {/* ④ 两条自检。都是「三态」而不是「对/错」：没校验就说没校验。 */}
      <div className="cost-checks">
        <p className="cost-check">
          <span className="cost-check-name">对账</span>
          <ReconcileMark state={reconcile.all_equal} />{' '}
          {reconcile.all_equal === null
            ? '任务未进终态，不判（tasks.cost 要到终态才写）'
            : reconcile.all_equal
              ? '本端点聚合与任务级记账一致'
              : '两边对不上，见下'}
          {/* 两个数**恒常露出**，不等时才补 note：对账这一行的证据就是这两个数本身，
              相等就不显示等于把凭据藏了 —— 页面上只剩一个「一致」的断言。
              ⚠️ 它们带各自的名字（Σ分组 / tasks.cost），所以这不违反「同屏不许两份同数」：
              那条禁的是同一个事实以两个身份出现两次，这里是两个独立测量的对照。 */}
          <span className="cost-check-detail">
            {' '}
            · Σ分组 <span className="cost-recon-events">{fmtCostFixed(reconcile.events_cost, 6)}</span>{' '}
            · tasks.cost{' '}
            <span className="cost-recon-task">{fmtCostFixed(reconcile.task_cost, 6)}</span>
            {reconcile.note ? ` —— ${reconcile.note}` : ''}
          </span>
        </p>
        <p className="cost-check">
          <span className="cost-check-name">单价反推</span>
          <ReconcileMark state={check.ok} />{' '}
          {check.ok === true
            ? `库里金额反推出的单价与表内价对咬（最大偏差 ${fmtPct(check.max_delta_pct)}）`
            : check.ok === false
              ? `反推单价与表内价对不上（最大偏差 ${fmtPct(check.max_delta_pct)}）`
              : '未校验'}
          {check.reason && <span className="cost-check-detail"> · {check.reason}</span>}
        </p>
      </div>
    </section>
  );
});

/** 一行 = 一个 ``(角色, 模型, 档位)`` 组合。单独抽出来是为了 memo：跨峰谷时同一角色
 *  会出两行，重渲染只该跟着数据走，不该跟着面板里另一行的 hover 走。 */
const CostRow = memo(function CostRow({ row }: { row: CostRoleRow }) {
  return (
    <tr data-peak={row.peak === null ? 'unknown' : row.peak ? 'peak' : 'off'}>
      <th scope="row" className="cost-role">
        {roleLabel(row.role)}
      </th>
      {/* 旧任务没有模型名：这里宁可显示「未记录」，也不许回落到当前 role_map 里的模型
          —— 那是拿今天的价去解释昨天的账（探针 AA 反向钉：页面里不许出现那个模型名）。 */}
      <td className="cost-model">{row.model ?? UNRECORDED}</td>
      <td className="cost-num">{fmtInt(row.calls)}</td>
      <td className="cost-num">{fmtInt(row.tokens_in)}</td>
      <td className="cost-num">{fmtInt(row.tokens_out)}</td>
      <td>
        {row.peak === null ? (
          /* 两种 null 不能合成一句：系数没记进库（老任务）≠ 这家根本没有峰谷档。
             金额上它们都是 ×1.0，语义上一个"不知道"、一个"知道且不存在"。 */
          <span className="cost-tier">
            {row.price_multiplier === null ? UNRECORDED : `${tierLabel(row.price_multiplier, null)} ×1`}
          </span>
        ) : (
          <span className={`cost-tier cost-tier--${row.peak ? 'peak' : 'off'}`}>
            {row.peak ? '高峰' : '低谷'} ×{row.price_multiplier}
          </span>
        )}
      </td>
      <td className="cost-num">
        {row.unit_price_in === null || row.unit_price_out === null ? (
          UNRECORDED
        ) : (
          <span title={priceSourceHint(row)}>
            {row.unit_price_in.toFixed(2)} / {row.unit_price_out.toFixed(2)}
            {row.price_source === 'settings_fallback' && <sup className="cost-sup">兜底</sup>}
            {/* 阶梯模型服务端报的是**最低档**（这一行是 N 次调用的聚合，无法逐次选档）。
                不标出来，这个数就会被读成"这个模型就是这个价"，而长上下文实际更贵。
                写「下界」不写「≥」：前者不需要读者猜符号指什么。 */}
            {row.tiered === true && <sup className="cost-sup">下界</sup>}
          </span>
        )}
      </td>
      <td className="cost-num cost-cost">{fmtCostFixed(row.cost, 4)}</td>
    </tr>
  );
});

/** 单价来源要说人话：表内官方价与配置兜底值是两种置信度，混成一种语气就是骗人。
 *
 *  ⚠️ 2026-09-26 起**优先用服务端逐行给的那一句**（``pricing_basis``）：
 *  原来这份表把「按官网高峰价折算，2026-09-15 查」写死在前端，盖在所有行上 ——
 *  换到智谱 / 千问之后每一行都在说谎（它们不分峰谷，核对日期也不是那一天）。
 *  这与 R-03 那轮"422 文案里写死 pdf/md/txt"是同一类错：一句话服务多个来源。
 *  字段缺失 = 后端是这次改动之前起的进程，那时才回落到下面这份写死的措辞。
 */
const LEGACY_SOURCE_HINT: Record<CostRoleRow['price_source'], string> = {
  official_table: '单价来自 MODEL_PRICES（按官网高峰价折算，2026-09-15 查）',
  settings_fallback: '表内没这个模型，单价取 .env 的兜底值 —— 只能当量级参考',
  unknown: '这条历史事件没记模型名，单价无从谈起',
};

function priceSourceHint(row: CostRoleRow): string {
  if (row.price_source === 'unknown') return LEGACY_SOURCE_HINT.unknown;
  const basis = row.pricing_basis?.trim();
  if (!basis) return LEGACY_SOURCE_HINT[row.price_source];
  const tail =
    row.tiered === true
      ? '。这一行是多次调用的聚合，报价取**最低档**：上下文越长单价越高（实际每档见右上角模型设置）'
      : '';
  return `${basis} · 元 / 100 万 token${tail}`;
}

/** ✓ / ✗ / ? 三态。刻意不用绿红两色承载「通过/不通过」之外的信息：
 *  ``?``（未校验）必须看得见是「没做」，不是「做了且没事」。 */
function ReconcileMark({ state }: { state: boolean | null }) {
  if (state === true)
    return (
      <span className="cost-mark cost-mark--ok" role="img" aria-label="通过">
        ✓
      </span>
    );
  if (state === false)
    return (
      <span className="cost-mark cost-mark--bad" role="img" aria-label="不通过">
        ✗
      </span>
    );
  return (
    <span className="cost-mark cost-mark--na" role="img" aria-label="未判定">
      ?
    </span>
  );
}

/** 百分比：两位小数（全站口径），null 交给「未记录」。 */
function fmtPct(v: number | null): string {
  return v === null ? UNRECORDED : `${v.toFixed(2)}%`;
}

/** 包一层 useQuery：单独成函数是为了让「运行中不拉」这条 enabled 有个明确落点，
 *  也方便探针在页面上按 queryKey 观察请求次数。 */
function useQueryCostBreakdown(taskId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['cost-breakdown', taskId],
    queryFn: () => fetchCostBreakdown(taskId),
    enabled: enabled && Boolean(taskId),
    // 终态之后这份账就不会再变；30s 的全局 staleTime 已经够，这里刻意不加 refetch 轮询。
  });
}

export default CostBreakdown;
