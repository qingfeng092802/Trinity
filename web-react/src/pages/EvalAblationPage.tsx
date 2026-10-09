import { useEffect, useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Table, theme as antdTheme } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  BarChartOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

import { describeFetchError, fetchAblationReport, fetchRetrievalReport } from '../api/client';
import {
  Chip,
  CodeChip,
  EmptyState,
  ErrorState,
  MetricTile,
  PageHeader,
  ScrollXFrame,
  Skel,
  SurfaceCard,
} from '../components/ui';
import { useRefresh } from '../hooks/useRefresh';
import { useThemeMode } from '../hooks/useThemeMode';
import { CHART_SERIES, MONO_STACK, deltaColorVar } from '../theme';
import type { AblationArmRow, AttributionRow, EvalGroup } from '../types';
import { PENDING, downloadCsv, fmtDec, fmtDelta, fmtInt, fmtPct } from '../utils/format';

/** 页面 ③：评测与消融报告（全部接真实后端，无一处预填数字）。
 *
 * 三条口径必须先说清，否则表里的数就是编的：
 *  1. 检索评测零 LLM：`scripts/eval_retrieval.py` 落盘 JSON，本页原样透传。
 *  2. 消融：`scripts/run_ablation.py` 落盘 ablation_summary.json。
 *  3. **不做显著性检验**：只报「相对基线的绝对提升 Δ」与相对提升百分比。
 *     没跑批就是「待测」，绝不补 0。
 */

/** 柱状图消费的四个比率指标 —— 顺序即 CHART_SERIES 的取色顺序。
 *
 *  gloss 是给表头和卡片上的 ⓘ 用的：这四个词是这份报告里最容易读错的四个数。
 *  口径逐条对齐 evaluation/retrieval_eval.py:_run_group（rank = 第一篇**期望文档**
 *  落在第几位，0 = 整组里没命中；分母是 total 全部题目，不是命中题数）。 */
const RATE_METRICS = [
  {
    key: 'top1_rate',
    name: 'Top-1',
    gloss: '第一篇期望文档正好排在第 1 位的题目占比（分母 = 本组全部题目）。',
  },
  {
    key: 'top3_rate',
    name: 'Top-3',
    gloss: '期望文档出现在前 3 条里的题目占比。G2 门槛判的就是这一列在参照组（0.4:0.6）下的值。',
  },
  {
    key: 'hit5_rate',
    name: 'Hit@5',
    gloss: '期望文档出现在前 5 条里的题目占比；前 3 没进来但前 5 进来了，只加这一列。',
  },
  {
    key: 'mrr',
    name: 'MRR',
    gloss: '平均倒数排名：命中的题取 1/排名（第 1 位 1.0、第 2 位 0.5、第 3 位 0.333…），没命中的题记 0，一起除以题目总数。',
  },
] as const;

type RateKey = (typeof RATE_METRICS)[number]['key'];

/* ------------------------------------------------------------------ *
 * 报告 payload 的形状闸门（F-2）
 *
 * 后端这两份报告是「CLI 落盘的 JSON 原样透传」（`api/routes/eval.py`），中间
 * **没有 schema 适配层**：CLI 一改字段形状（`groups` 从数组变成对象、`arms` 干脆没了），
 * 页面就会在 `.map` / `[...groups]` 上抛 TypeError，整页掉进 ErrorBoundary ——
 * 而本来另一份报告是可以独立渲染的。旧写法 `report?.groups ?? []` 只挡 null/undefined，
 * 挡不住"存在但不是数组"。
 *
 * 现在的口径：**形状不对就当没有**（表格空一行），同时把它标成"格式不识别"单独出一条
 * 出口 —— 既不整页崩，也不许伪装成"你还没跑过评测"（那是 F-1 那类假空态）。
 * 不引 zod/yup：只有两个入口、三种形状要判，运行时依赖不值当。
 * ------------------------------------------------------------------ */

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asRecord<T>(value: unknown): Record<string, T> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, T>) : {};
}

/** payload 在场、但那个本应是数组的字段不是数组 ⇒ 形状不识别。 */
function isShapeMismatch(payload: unknown, field: string): boolean {
  if (!payload || typeof payload !== 'object') return false;
  const value = (payload as Record<string, unknown>)[field];
  return value !== undefined && value !== null && !Array.isArray(value);
}

/** 路径字段取末段；**不是字符串就当没有**（同一条 F-2 纪律）。
 *
 *  这里原先写的是 `report.dataset.split(/[\\/]/).pop()` —— 少一个 `dataset` 字段
 *  （CLI 换了版本 / 手写了一份报告）就抛 `Cannot read properties of undefined`，
 *  整页进 ErrorBoundary。本轮探针把它逼出来了：桩只给了 `groups: []`，页面就崩了，
 *  而崩的原因是另一个字段没给 —— 这正说明"任何字段都可能是别的形状"这件事
 *  在这页上没有一处兜住。 */
function baseName(value: unknown): string {
  if (typeof value !== 'string' || !value) return PENDING;
  return value.split(/[\\/]/).pop() ?? value;
}

/** 最优配比：MRR 优先，其次 Top-3 / Top-1。
 *
 * 排序键写死在这里而不是「取表格第一行」，因为表格可以被用户点列头重排，
 * 结论 Banner 不能跟着表格抖。
 */
function pickBestGroup(groups: EvalGroup[]): EvalGroup | null {
  if (groups.length === 0) return null;
  return [...groups].sort(
    (a, b) =>
      b.mrr - a.mrr || b.top3_rate - a.top3_rate || b.top1_rate - a.top1_rate,
  )[0];
}

/** 最优消融臂：只在真的算出相对基线的臂里取最大值，全是「待测」就不给结论。 */
function pickBestArm(rows: AblationArmRow[]): AblationArmRow | null {
  const scored = rows.filter((r) => typeof r.rel_lift_ndcg_at_k === 'number');
  if (scored.length === 0) return null;
  return scored.reduce((a, b) => (b.rel_lift_ndcg_at_k! > a.rel_lift_ndcg_at_k! ? b : a));
}

/** 纵轴范围：贴着真实数据算，再吸附到整齐刻度。
 *
 * 从 0 起会把 0.85–0.96 的组间差异压成「几乎一样高」（清单 P0#4），所以放大；
 * 代价是**截断轴**，图注必须写明不从 0 起，否则读者会把高差当成倍数。
 */
function axisRange(values: number[]): { min: number; max: number; step: number } {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = Math.max(0.005, (hi - lo) * 0.2);
  const rawMin = Math.max(0, lo - pad);
  const rawMax = Math.min(1, hi + pad);
  const step = [0.01, 0.02, 0.05, 0.1].find((s) => (rawMax - rawMin) / s <= 6) ?? 0.1;
  const min = Math.max(0, Math.floor(rawMin / step) * step);
  let max = Math.min(1, Math.ceil(rawMax / step) * step);
  if (max - min < step) max = Math.min(1, min + step);
  return { min, max, step };
}

/** 表格数字列统一右对齐 + 等宽数字，纵向可比。缺值排到最后。 */
function numSorter<T extends object>(key: string) {
  const NEG = -Number.MAX_VALUE;
  return (a: T, b: T): number => {
    const av = (a as Record<string, unknown>)[key];
    const bv = (b as Record<string, unknown>)[key];
    return (typeof av === 'number' ? av : NEG) - (typeof bv === 'number' ? bv : NEG);
  };
}

/** 刻度位数跟着步长走：0.05 一档两位就够，0.01 一档才需要三位。 */
function decimalsOf(step: number): number {
  return Math.max(2, (String(step).split('.')[1] ?? '').length);
}

const rowKeyOf = (g: EvalGroup) => `${g.weights.bm25}-${g.weights.vector}`;

/** 「最优」小标：胜出行不只靠底色，颜色和底色都只是加码，文字才是判据。 */
function BestTag() {
  return <span className="best-tag">最优</span>;
}

/** 比率单元格：2 位小数（1 位会把 70 题分母下的组间差异抹平），本列最大值加粗标色。 */
function RateCell({ value, best }: { value: number; best: number }) {
  const win = Number.isFinite(best) && value === best;
  return <span className={win ? 'best' : undefined}>{fmtPct(value, 2)}</span>;
}

export default function EvalAblationPage() {
  const { token } = antdTheme.useToken();
  const { mode } = useThemeMode();
  const { token: refreshToken } = useRefresh();
  const queryClient = useQueryClient();

  const retrieval = useQuery({ queryKey: ['retrieval-report'], queryFn: fetchRetrievalReport });
  const ablation = useQuery({ queryKey: ['ablation-report'], queryFn: fetchAblationReport });

  // 顶栏「刷新」→ 重取两份报告
  useEffect(() => {
    void queryClient.invalidateQueries();
  }, [refreshToken, queryClient]);

  const report = retrieval.data?.report;
  const groups: EvalGroup[] = useMemo(() => asArray<EvalGroup>(report?.groups), [report]);
  const armRows: AblationArmRow[] = useMemo(() => asArray<AblationArmRow>(ablation.data?.arms), [ablation.data]);
  const attribution: Record<string, AttributionRow> = useMemo(
    () => asRecord<AttributionRow>(ablation.data?.attribution),
    [ablation.data],
  );
  /** F-2：报告在场但形状不对（CLI 改了字段 / 后端换了版本）⇒ 单独一条出口，
   *  既不整页崩，也不伪装成"还没跑过评测"。 */
  const retrievalShapeBad = isShapeMismatch(report, 'groups');
  const ablationShapeBad = isShapeMismatch(ablation.data, 'arms');
  /** F-1：错误必须先于空态判 —— 否则 `data` 是 undefined，会被渲染成"你还没跑过评测"。 */
  const retrievalError = retrieval.isError ? describeFetchError(retrieval.error) : null;
  const ablationError = ablation.isError ? describeFetchError(ablation.error) : null;

  const bestGroup = useMemo(() => pickBestGroup(groups), [groups]);
  const bestArm = useMemo(() => pickBestArm(armRows), [armRows]);
  /** 各比率列的最大值：表格里的「最优值」逐列判定，不假设胜出行四列全赢。 */
  const colMax = useMemo(() => {
    const out = {} as Record<RateKey, number>;
    for (const m of RATE_METRICS) out[m.key] = groups.length ? Math.max(...groups.map((g) => g[m.key])) : NaN;
    return out;
  }, [groups]);

  const axis = useMemo(
    () => (groups.length ? axisRange(groups.flatMap((g) => RATE_METRICS.map((m) => g[m.key]))) : null),
    [groups],
  );

  const chartOption = useMemo(() => {
    const labels = groups.map((g) => `${g.weights.bm25} : ${g.weights.vector}`);
    const colors = CHART_SERIES[mode];
    const bar = (name: string, data: number[], color: string) => ({
      name,
      type: 'bar' as const,
      data,
      barMaxWidth: 26,
      barGap: '28%' as const,
      itemStyle: { color, borderRadius: [4, 4, 0, 0] as [number, number, number, number] },
      // 柱顶数值标签：放大纵轴解决的是「看得出有差异」，标签解决的才是「差多少」，
      // 两者缺一都还得回表里查（清单 P0#4）。
      label: {
        show: true,
        position: 'top' as const,
        distance: 3,
        color: token.colorTextSecondary,
        fontFamily: MONO_STACK,
        fontSize: 10,
        formatter: (p: { value: unknown }) =>
          typeof p.value === 'number' ? `${(p.value * 100).toFixed(2)}%` : '',
      },
    });

    return {
      backgroundColor: 'transparent',
      animationDuration: 420,
      animationEasing: 'cubicOut' as const,
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
        backgroundColor: token.colorBgElevated,
        borderColor: token.colorBorder,
        textStyle: { color: token.colorText, fontSize: 12 },
        valueFormatter: (v: unknown) => (typeof v === 'number' ? v.toFixed(4) : '—'),
      },
      legend: {
        bottom: 0,
        icon: 'roundRect' as const,
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 18,
        textStyle: { color: token.colorTextSecondary, fontSize: 12 },
      },
      grid: { left: 8, right: 8, top: 34, bottom: 40, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: labels,
        // 不写 axis name：列头已经写明「权重（BM25 : 向量）」，避免和底部图例抢位置
        axisLabel: { color: token.colorTextSecondary, fontSize: 12 },
        axisLine: { lineStyle: { color: token.colorBorder } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value' as const,
        min: axis?.min ?? 0,
        max: axis?.max ?? 1,
        interval: axis?.step,
        // 刻度文字位数跟着步长走：0.05 一档写两位，0.01 一档才写三位
        axisLabel: {
          color: token.colorTextTertiary,
          fontSize: 11,
          fontFamily: MONO_STACK,
          formatter: (v: number) => v.toFixed(axis ? decimalsOf(axis.step) : 1),
        },
        splitLine: { lineStyle: { color: token.colorBorderSecondary, type: 'dashed' as const } },
      },
      series: RATE_METRICS.map((m, i) =>
        bar(m.name, groups.map((g) => g[m.key]), colors[i % colors.length]),
      ),
    };
  }, [groups, axis, mode, token]);

  const groupColumns: ColumnsType<EvalGroup> = [
    {
      title: '权重（BM25 : 向量）',
      key: 'weights',
      width: 190,
      render: (_, row) => (
        <span className="row row--nowrap">
          <Chip mono tone={{ fg: 'var(--primary-soft-fg)', soft: 'var(--primary-soft)' }}>
            {row.weights.bm25} : {row.weights.vector}
          </Chip>
          {bestGroup && rowKeyOf(row) === rowKeyOf(bestGroup) ? <BestTag /> : null}
        </span>
      ),
    },
    { title: 'top-k', dataIndex: 'top_k', width: 76, align: 'right', sorter: numSorter<EvalGroup>('top_k') },
    { title: '题数', dataIndex: 'total', width: 76, align: 'right', sorter: numSorter<EvalGroup>('total') },
    ...RATE_METRICS.map<ColumnsType<EvalGroup>[number]>((m) => ({
      title: m.name,
      key: m.key,
      align: 'right',
      sorter: numSorter<EvalGroup>(m.key),
      /* 释义挂在 <th> 的原生 title 上：不额外插图标，表头宽度一个字都不变，
         鼠标停上去就有。列名这几个词是本页最容易被读错的东西。 */
      onHeaderCell: () => ({ title: m.gloss }),
      render: (_, r) => <RateCell value={r[m.key]} best={colMax[m.key]} />,
    })),
    { title: 'BM25 均分', key: 'b', align: 'right', render: (_, r) => fmtDec(r.bm25_score_mean, 4) },
    { title: '向量均分', key: 'v', align: 'right', render: (_, r) => fmtDec(r.vector_score_mean, 4) },
  ];

  const armColumns: ColumnsType<AblationArmRow> = [
    {
      title: '臂',
      dataIndex: 'arm_id',
      width: 196,
      fixed: 'left',
      render: (v: string) => (
        <span className="row row--nowrap">
          <Chip mono>{v}</Chip>
          {bestArm?.arm_id === v ? <BestTag /> : null}
        </span>
      ),
    },
    {
      title: 'nDCG@k',
      key: 'ndcg',
      align: 'right',
      onHeaderCell: () => ({
        title:
          '二值增益的归一化折损累计：命中的期望文档排得越靠前分越多（折损 1/log2(排名+1)），再除以"理想排序全排在最前"的同式和。所有期望文档都排进前几名 = 1.0，一篇没命中 = 0。题目本身没有期望文档（拒答题）时这一列是「—」= 不适用，不是 0。',
      }),
      render: (_, r) => fmtDec(r.ndcg_at_k, 4),
    },
    {
      title: 'MRR@k',
      key: 'mrr',
      align: 'right',
      onHeaderCell: () => ({
        title: '第一篇命中的排名倒数（第 1 位 1.0、第 2 位 0.5…），k 内没命中记 0，不是「不适用」。',
      }),
      render: (_, r) => fmtDec(r.mrr_at_k, 4),
    },
    {
      title: '命中率',
      key: 'hit',
      align: 'right',
      onHeaderCell: () => ({
        title:
          'top-k 里至少命中一篇期望文档的题目占比（每题取 0/1）。McNemar 配对检验用的就是这一列的观测值。',
      }),
      render: (_, r) => fmtDec(r.hit_at_k, 4),
    },
    {
      title: 'ΔnDCG（绝对）',
      key: 'd',
      align: 'right',
      onHeaderCell: () => ({
        title: '本臂 nDCG@k 减基线臂 nDCG@k 的差值。只报绝对提升，不做显著性检验。',
      }),
      render: (_, r) =>
        r.delta_ndcg_at_k == null ? (
          PENDING
        ) : (
          <span style={{ color: deltaColorVar(r.delta_ndcg_at_k), fontVariantNumeric: 'tabular-nums' }}>
            {r.delta_ndcg_at_k >= 0 ? '+' : ''}
            {r.delta_ndcg_at_k.toFixed(4)}
          </span>
        ),
    },
    {
      title: '相对基线',
      key: 'rel',
      align: 'right',
      onHeaderCell: () => ({
        title:
          'ΔnDCG ÷ 基线臂的 nDCG。0 是基线自己（中性底，不涂绿）；这一列是「—」表示该臂没有可比的 nDCG（没跑批），不补 0。',
      }),
      render: (_, r) =>
        r.rel_lift_ndcg_at_k == null ? (
          PENDING
        ) : (
          <Chip
            mono
            tone={{
              fg: deltaColorVar(r.rel_lift_ndcg_at_k),
              /* 0 是基线自己，不是「没跌」：给中性底，别涂成绿色让人误读成提升 */
              soft:
                r.rel_lift_ndcg_at_k > 0
                  ? 'var(--success-soft)'
                  : r.rel_lift_ndcg_at_k < 0
                    ? 'var(--danger-soft)'
                    : 'var(--bg-surface-2)',
            }}
          >
            {fmtDelta(r.rel_lift_ndcg_at_k, 2)}
          </Chip>
        ),
    },
  ];

  const attrRows = Object.entries(attribution).map(([arm, row]) => ({ arm, ...row }));

  /** 结论 Banner 的三条结论：只列**真的算得出来**的项，缺数据的那条不出现，
   *  也不写「待测」占位 —— 半空的 Banner 比没有更误导。 */
  const gate = report?.g2_gate;
  /** 参照组标签读后端给的 `reference_group`，文案里不再自己硬写 0.4:0.6。 */
  const refLabel = gate?.reference_group
    ? `${gate.reference_group.bm25} : ${gate.reference_group.vector}`
    : '0.4 : 0.6';
  /** G2 三态：通过 / 未通过 / **无法判定**（参照组没在本次扫描里，`passed=false` 不代表没达标）。 */
  const gateState: 'pass' | 'fail' | 'unknown' =
    gate?.evaluable === false ? 'unknown' : gate?.passed ? 'pass' : 'fail';
  const verdict: { k: string; lead: string; tone: 'ok' | 'bad' | 'win'; tail?: string }[] = [];
  if (gate) {
    verdict.push({
      k: 'G2 判定',
      lead: gateState === 'pass' ? '通过' : gateState === 'fail' ? '未通过' : '无法判定',
      tone: gateState === 'pass' ? 'ok' : 'bad',
      tail:
        gateState === 'unknown'
          ? `参照组 ${refLabel} 未参与本次扫描 · 该脚本退出码 2`
          : `门槛 ${gate.threshold ?? PENDING} · 参考组 Top-3 ${fmtPct(gate.reference_top3_rate, 2)}`,
    });
  }
  if (bestGroup) {
    verdict.push({
      k: '最优权重配比',
      lead: `${bestGroup.weights.bm25} : ${bestGroup.weights.vector}`,
      tone: 'win',
      tail: `MRR ${fmtPct(bestGroup.mrr, 2)} · 依据 MRR 排序`,
    });
  }
  if (bestArm) {
    verdict.push({
      k: '最优消融臂',
      lead: bestArm.arm_id,
      tone: 'win',
      tail: `相对基线 ${fmtDelta(bestArm.rel_lift_ndcg_at_k, 2)} · 依据 ΔnDCG@k`,
    });
  }

  const exportRetrieval = () => {
    if (groups.length === 0) return;
    downloadCsv(
      'retrieval-groups.csv',
      ['bm25_weight', 'vector_weight', 'top_k', 'total', 'top1_rate', 'top3_rate', 'hit5_rate', 'mrr', 'bm25_score_mean', 'vector_score_mean'],
      groups.map((g) => [
        g.weights.bm25,
        g.weights.vector,
        g.top_k,
        g.total,
        g.top1_rate,
        g.top3_rate,
        g.hit5_rate,
        g.mrr,
        g.bm25_score_mean,
        g.vector_score_mean,
      ]),
    );
  };

  return (
    <>
      <PageHeader
        title="评测与消融"
        desc="检索评测（零 LLM）与消融对比的只读报告。所有数字来自 CLI 落盘 JSON 原样透传；没跑批一律显示「待测」，不做任何补零。"
        actions={
          <>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void queryClient.invalidateQueries()}
              loading={retrieval.isFetching || ablation.isFetching}
            >
              刷新报告
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={exportRetrieval}
              disabled={groups.length === 0}
              type="primary"
            >
              导出检索表 CSV
            </Button>
          </>
        }
      />

      {/* 结论 Banner：把「哪个配比/哪个臂胜出」提到页首，不用先扫三张表（清单 P1#5）。
          判定依据写在尾注里，读者能复核结论是怎么来的。 */}
      {verdict.length > 0 && (
        <section
          className={`verdict${gate && !gate.passed ? ' verdict--bad' : ''}`}
          aria-label="评测结论"
        >
          <span
            className={`v-icon${gate ? (gate.passed ? '' : ' v-icon--bad') : ' v-icon--none'}`}
            aria-hidden
          >
            {gate ? gate.passed ? <CheckCircleOutlined /> : <CloseCircleOutlined /> : <ExperimentOutlined />}
          </span>
          <div className="v-items">
            {verdict.map((v) => (
              <span className="v-item" key={v.k}>
                <span className="k">{v.k}</span>
                <span className="v">
                  <b className={`lead lead--${v.tone}`}>{v.lead}</b>
                  {v.tail && <span className="tail">{v.tail}</span>}
                </span>
              </span>
            ))}
          </div>
        </section>
      )}

      <div className="stack">
        {/* ------------------------- 检索评测 ------------------------- */}
        <SurfaceCard
          title="检索评测（零 LLM）"
          icon={<FileSearchOutlined />}
          sub="混合检索在不同 BM25 / 向量权重配比下的命中表现"
          extra={
            retrieval.data?.report_file ? (
              <CodeChip label="报告">{retrieval.data.report_file}</CodeChip>
            ) : null
          }
        >
          {retrieval.isLoading ? (
            <div className="metric-grid">
              {[0, 1, 2, 3].map((i) => (
                <div className="metric" key={i}>
                  <Skel w="58%" h={10} style={{ marginBottom: 9 }} />
                  <Skel w="42%" h={20} />
                </div>
              ))}
            </div>
          ) : retrievalError ? (
            /* F-1：错误态。过去 500 / 404 / 后端没起 与"真的还没跑过评测"共用下面那个
               空态壳，附带一句"跑一次评测即可生成 + CLI 命令" —— 后端明明活着，
               却被支去敲命令行。这条分支必须排在空态**前面**。 */
            <ErrorState
              icon={<FileSearchOutlined />}
              title="检索评测报告读取失败"
              message={retrievalError.message}
              httpStatus={retrievalError.httpStatus}
              code={retrievalError.code}
              requestId={retrievalError.requestId}
              note="后端还在，是这一次读没成 —— 不是「还没跑过评测」，也不需要去跑 CLI。"
              onRetry={() => void retrieval.refetch()}
            />
          ) : retrievalShapeBad ? (
            <ErrorState
              icon={<FileSearchOutlined />}
              title="报告格式不识别"
              message="report.groups 不是数组，多半是生成报告的脚本改了版本。"
              note="下方表格与图按「无数据」渲染；消融那份不受影响。"
              onRetry={() => void retrieval.refetch()}
            />
          ) : !retrieval.data?.available || !report ? (
            <EmptyState
              icon={<FileSearchOutlined />}
              title="暂无检索评测报告"
              desc={
                <>
                  {retrieval.data?.reason ?? '报告不可用'}。
                  跑一次评测即可生成（零 token：走本地 embedding，不调 LLM）。
                </>
              }
              actions={<CodeChip>python scripts/eval_retrieval.py</CodeChip>}
            />
          ) : (
            <>
              <div className="metric-grid">
                <MetricTile
                  label="参考组 Top-3"
                  accent
                  value={fmtPct(report.g2_gate?.reference_top3_rate, 2)}
                  hint={gateState === 'unknown' ? '本次扫描不含参照组' : 'G2 门槛的对照基准'}
                  title={`参照组（BM25 : 向量）= ${refLabel}。这一格是它在前 3 条里命中期望文档的题目占比，G2 判的就是这个数够不够门槛。参照组没参与本次扫描时后端给 null，于是这里显示"待测"，不会拿别的组顶上。`}
                />
                <MetricTile
                  label="G2 门槛"
                  value={String(report.g2_gate?.threshold ?? PENDING)}
                  title="通过线，写死在后端 evaluation/retrieval_eval.py 的 G2_TOP3_THRESHOLD。它和参照组一起决定那个脚本的退出码：参照组达到门槛 0、未达 1、参照组没在本次扫描里 2（无法判定）。"
                />
                <MetricTile
                  label="G2 判定"
                  value={gateState === 'pass' ? '通过' : gateState === 'fail' ? '未通过' : '无法判定'}
                  tone={gateState === 'pass' ? 'success' : gateState === 'fail' ? 'danger' : 'warning'}
                  icon={
                    gateState === 'pass' ? (
                      <CheckCircleOutlined />
                    ) : gateState === 'fail' ? (
                      <CloseCircleOutlined />
                    ) : (
                      <ExclamationCircleOutlined />
                    )
                  }
                  hint={
                    gateState === 'pass'
                      ? '达到门槛'
                      : gateState === 'fail'
                        ? '未达 G2 门槛'
                        : `参照组 ${refLabel} 未参与本次扫描`
                  }
                  title="判定直接读报告 JSON 的 g2_gate.evaluable / passed，前端不再算一遍 —— 口径只有后端一处。参照组缺席时 passed 也是 false，但那是「无法判定」而不是「没达标」，两者不能混着报。"
                />
                {/* 「可计分」是后端自己的口径（evaluation/retrieval_eval.py:21「70 道可计分题」：
                    数据集在派生时就把无期望文档的拒答题剔除了），这里跟着它叫，不改名。 */}
                <MetricTile
                  label="可计分题数"
                  value={fmtInt(report.dataset_size)}
                  hint={`${fmtInt(report.fixtures?.length ?? 0)} 篇语料 · 上面四个比率的分母`}
                  title="报告里的 dataset_size：这批检索评测跑完的用例条数，也是 Top-1 / Top-3 / Hit@5 / MRR 共同的分母。没命中的题照样在分母里，所以比率偏低可能是题太难，不一定是检索变差。"
                />
              </div>

              <div className="kv" style={{ marginTop: 14 }}>
                <span>
                  数据集：
                  <b className="mono">{baseName(report.dataset)}</b>
                </span>
                <span>
                  嵌入模型：<b className="mono">{report.embedding_model}</b>
                </span>
                <span>
                  chunk：<b className="mono">{report.chunk_size}</b> / overlap{' '}
                  <b className="mono">{report.chunk_overlap}</b>
                </span>
                <span>
                  生成时间：<b>{report.generated_at}</b>
                </span>
              </div>

              <div
                style={{ marginTop: 18 }}
                role="img"
                aria-label={`各权重配比下的命中率柱状图，共 ${groups.length} 组，纵轴 ${axis?.min.toFixed(2)}–${axis?.max.toFixed(2)}；等价数据见下方表格`}
              >
                <ReactECharts option={chartOption} style={{ height: 320 }} notMerge />
                <div className="fs-11 t3" style={{ textAlign: 'center', marginTop: 2 }}>
                  纵轴 {axis?.min.toFixed(2)}–{axis?.max.toFixed(2)}
                  ，是贴着数据取的截断轴（不从 0 起），为的是放大组间差异；
                  柱顶标签与表格同源，精确值以表格为准。
                </div>
              </div>

              {/* label 里点名"可横向滚动"：390 下这张 9 列表只露 2 列，
                  视觉那一层（两端渐影）读屏拿不到，只能靠 aria-label 说（EV-01）。 */}
              <ScrollXFrame
                label="各权重配比的命中明细表：Top-1 / Top-3 / Hit@5 / MRR 与两路均分，共 9 列，可横向滚动"
                style={{ marginTop: 14 }}
              >
                <Table<EvalGroup>
                  columns={groupColumns}
                  dataSource={groups}
                  size="small"
                  pagination={false}
                  rowKey={rowKeyOf}
                  rowClassName={(r) => (bestGroup && rowKeyOf(r) === rowKeyOf(bestGroup) ? 'row-best' : '')}
                  scroll={{ x: 940 }}
                />
              </ScrollXFrame>
            </>
          )}
        </SurfaceCard>

        {/* ------------------------- 消融对比 ------------------------- */}
        <SurfaceCard
          title="消融对比"
          icon={<ExperimentOutlined />}
          sub="各臂相对基线的绝对提升；不做显著性检验"
          extra={
            ablation.data?.report ? (
              <Chip outline mono>
                {ablation.data.report.questions} 题 / {ablation.data.report.corpus_docs} 篇语料
              </Chip>
            ) : null
          }
        >
          {ablation.isLoading ? (
            <div className="stack" style={{ gap: 8 }}>
              {[0, 1, 2].map((i) => (
                <Skel key={i} h={30} />
              ))}
            </div>
          ) : ablationError ? (
            <ErrorState
              icon={<ExperimentOutlined />}
              title="消融报表读取失败"
              message={ablationError.message}
              httpStatus={ablationError.httpStatus}
              code={ablationError.code}
              requestId={ablationError.requestId}
              note="后端还在，是这一次读没成 —— 不是「还没跑过消融」。"
              onRetry={() => void ablation.refetch()}
            />
          ) : ablationShapeBad ? (
            <ErrorState
              icon={<ExperimentOutlined />}
              title="报表格式不识别"
              message="ablation_summary.arms 不是数组，多半是跑批脚本改了版本。"
              note="检索评测那一块不受影响，照常渲染。"
              onRetry={() => void ablation.refetch()}
            />
          ) : !ablation.data?.available || armRows.length === 0 ? (
            <EmptyState
              icon={<ExperimentOutlined />}
              title="暂无消融报表"
              desc={<>{ablation.data?.reason ?? '报表不可用'}。跑批后每个实验臂各出一行。</>}
              actions={<CodeChip>python scripts/run_ablation.py</CodeChip>}
            />
          ) : (
            <>
              {ablation.data?.report?.failed_arms?.length ? (
                <div
                  style={{
                    marginBottom: 12,
                    padding: '9px 12px',
                    border: '1px solid var(--warning)',
                    borderRadius: 'var(--r-sm)',
                    background: 'var(--warning-soft)',
                    color: 'var(--warning-fg)',
                    fontSize: 12,
                  }}
                >
                  失败臂（未产出可用指标）：{ablation.data.report.failed_arms.join(', ')}
                </div>
              ) : null}
              <ScrollXFrame label="消融对比明细表：各臂的 nDCG / MRR / 命中率与相对基线提升，共 6 列，可横向滚动">
                <Table<AblationArmRow>
                  columns={armColumns}
                  dataSource={armRows}
                  size="small"
                  pagination={false}
                  rowKey="arm_id"
                  rowClassName={(r) => (bestArm && r.arm_id === bestArm.arm_id ? 'row-best' : '')}
                  scroll={{ x: 800 }}
                />
              </ScrollXFrame>
              {ablation.data?.report?.significance?.note && (
                <div className="fs-12 t3" style={{ marginTop: 12 }}>
                  {ablation.data.report.significance.note}
                </div>
              )}
            </>
          )}
        </SurfaceCard>

        {/* ------------------------- 失败归因 ------------------------- */}
        <SurfaceCard
          title="失败归因（2 类）"
          icon={<BarChartOutlined />}
          sub="F1 未召回（hit_at_k == 0） / F2 召回未居首（hit_at_k == 1 且 mrr < 1）"
        >
          {attrRows.length === 0 ? (
            <EmptyState
              icon={<BarChartOutlined />}
              title="暂无归因数据"
              desc="归因计数由服务端从消融结果里算好（判据与 scripts/analyze_ablation_failures.py 一致），跑批后自动出现。"
              actions={<CodeChip>python scripts/run_ablation.py</CodeChip>}
            />
          ) : (
            <ScrollXFrame label="失败归因计数表：各臂的 F1 未召回 / F2 召回未居首 / 干净，共 5 列，可横向滚动">
              <Table
                size="small"
                pagination={false}
                rowKey="arm"
                dataSource={attrRows}
                columns={[
                  {
                    title: '臂',
                    dataIndex: 'arm',
                    render: (v: string) => <Chip mono>{v}</Chip>,
                  },
                  { title: '计分题数', dataIndex: 'scored', align: 'right' },
                  { title: 'F1 未召回', dataIndex: 'f1', align: 'right' },
                  { title: 'F2 召回未居首', dataIndex: 'f2', align: 'right' },
                  { title: '干净', dataIndex: 'clean', align: 'right' },
                ]}
              />
            </ScrollXFrame>
          )}
        </SurfaceCard>
      </div>
    </>
  );
}
