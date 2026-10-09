import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';

import type { AgentNode, LogLevel, TaskStatus } from './types';

/** Trinity 控制台 · 设计系统（单一事实来源）。
 *
 * 结构说明 —— 三层，改色只改第一层：
 *  1. `PALETTE`     颜色（light / dark 两套）。经 `applyThemeVars()` 同步注入
 *                    `<html>` 的 CSS 自定义属性，自定义组件一律 `var(--x)` 消费。
 *  2. `SCALE`       与主题无关的尺度：间距 / 字号 / 圆角 / 阴影 / 动效 / 层级。
 *  3. `ANTD_THEME`  AntD 组件库的 token 映射（值取自上面两层，不另写魔法值）。
 *
 * 硬约束（沿用 docs/frontend_ui_review.md §2 的审计结论，逐条实测对比度）：
 *  - 承载白字的主色必须是 `#4f46e5`（6.28:1）；`#6366f1` 只有 4.47:1，
 *    只允许用于描边、图示、渐变，**永不承载文字**。
 *  - 一切小字（≤13px）文字色对比度 ≥4.5:1：`--text-3` 亮 #676e7c / 暗 #868da0，
 *    实测在运行条底色上分别是 5.12 / 5.44（running.cjs B 趟那条「常态字色 ≥4.5」）。
 *    ⚠️ 这里曾经写着「#6b7280（4.78:1）」—— 那个色值早已被换掉、注释一直没跟（N5）：
 *    注释里的数与 token 不一致时，下一个人会照着注释把色改回去。改色必须同改这一行。
 *  - 节点色分「填充」与「文字」两档：Executor 现在是 teal —— 文字用 `#0f766e`（白底 5.47:1），
 *    `#0d9488` 只做圆点/描边（3.74:1，不承载文字）。
 *    ⚠️ 这一条曾经写着 cyan 那一对（`#0891b2` 3.68:1 只做图形 / `#0e7490` 5.38:1 承载文字）：
 *    2026-09-23 Executor 换成 teal 之后注释没跟（与上面 `--text-3` 同一类漂移）。
 *    数都由 tools/uicheck/contrast.cjs 实算（它按 token 读，换色就自动跟着变）。
 *  - 日志面板恒为深色沉浸层（终端隐喻），两主题下不变，避免切换时配色抖动。
 */

export type ThemeMode = 'light' | 'dark';

/* ------------------------------------------------------------------ *
 * 1. 色彩
 * ------------------------------------------------------------------ */

export const PALETTE: Record<ThemeMode, Record<string, string>> = {
  light: {
    /* 表面 —— 中性灰阶取自参考包（更偏冷、更接近 GitHub 的灰）
       注意：`--bg-surface-2` 与 `--bg-sunken` 的深浅次序保持现状
       （surface-2 浅于 sunken），参考包里两者是同一个值，直接照搬会让
       「卡内嵌块」与「代码块」分不开。 */
    '--bg-app': '#f5f6fa',
    '--bg-sunken': '#eff1f5',
    '--bg-surface': '#ffffff',
    '--bg-surface-2': '#f7f8fb',
    '--bg-hover': '#f3f4f7',
    '--bg-active': '#eceef3',
    '--bg-inverse': '#141826',
    '--border': '#e6e8f0',
    /* 卡头 / 表格行这类「同张卡内部」的分隔，比外描边再轻一档，
       否则整页边框密度过高（重设计清单 P1#7「盒状嵌套过多」）。 */
    '--border-soft': '#eff0f4',
    '--border-strong': '#d3d8e4',
    '--border-focus': '#a5b4fc',
    /* 答案富文本层专用：表格/代码/公式的描边与下沉底。
       亮色下与 --border / --bg-sunken 同值（保持既有观感），
       暗色下换成半透明白 + slate 深一阶 —— 见 dark 同名两项的理由。 */
    '--panel-line': '#e6e8f0',
    '--code-bg': '#eff1f5',

    /* 文本 —— ⚠️ 这里与参考包刻意不一致：
       参考包的 `--text-3 = #8a90a2` 在白底只有约 3.5:1，不满足 WCAG AA，故不采用。
       text-1 / text-2 直接用参考包取值（#141826 / #4b5266）。
       text-3 定为 #676e7c 而非常见的 #6b7280：后者在参考包的应用底色 #f5f6fa 上
       只有 4.48:1（差 0.02 未过 AA），在更深的 --bg-sunken 上只有 4.28:1。
       #676e7c 在 白 / 应用底 / 卡片次级底 / 下沉底 四档上分别
       5.12 / 4.74 / 4.83 / 4.53:1，全过 AA，且视觉上只比 #6b7280 深一档。
       改为任何值前请先跑 `node tools/uicheck/contrast.cjs`。 */
    '--text-1': '#141826',
    '--text-2': '#4b5266',
    '--text-3': '#676e7c',
    '--text-inverse': '#ffffff',

    /* 品牌 —— 主色阶补齐到参考包的 50/100/300/500/600/700 六档 */
    '--primary': '#4f46e5',
    '--primary-hover': '#4338ca',
    '--primary-50': '#eef0fe',
    '--primary-100': '#e0e3fd',
    '--primary-300': '#a5abf7',
    '--primary-500': '#6366f1',
    '--primary-700': '#4338ca',
    '--primary-soft': '#eef0fe',
    /* 比 soft 深一档：结论 callout、强调指标块这类「要成焦点」的面用描边色 */
    '--primary-soft-2': '#e0e3fd',
    '--primary-soft-fg': '#3730a3',
    '--accent': '#7c3aed',
    /* 品牌渐变对齐参考包的品牌图形：#6366f1 → #8b5cf6（比原 #a855f7 更偏靛紫） */
    '--brand-gradient': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    '--ring': 'rgba(79, 70, 229, 0.30)',

    /* 语义色：fill 用于图形/描边，fg 用于文字 */
    '--success': '#059669',
    '--success-fg': '#047857',
    '--success-soft': '#d1fae5',
    '--warning': '#d97706',
    '--warning-fg': '#b45309',
    '--warning-soft': '#fef3c7',
    '--danger': '#dc2626',
    '--danger-fg': '#b91c1c',
    '--danger-soft': '#fee2e2',
    '--info': '#2563eb',
    '--info-fg': '#1d4ed8',
    '--info-soft': '#dbeafe',

    /* 任务状态 */
    '--st-queued-fg': '#b45309',
    '--st-queued-soft': '#fef3c7',
    '--st-running-fg': '#1d4ed8',
    '--st-running-soft': '#dbeafe',
    '--st-done-fg': '#047857',
    '--st-done-soft': '#d1fae5',
    '--st-aborted-fg': '#c2410c',
    '--st-aborted-soft': '#ffedd5',
    '--st-failed-fg': '#b91c1c',
    '--st-failed-soft': '#fee2e2',
    '--st-canceled-fg': '#4a5162',
    '--st-canceled-soft': '#eef0f4',

    /* 三角色节点 —— 2026-09-23 重设计：Executor 从 cyan(#0e7490/#0891b2) 换成
       teal(#0f766e/#0d9488)。原来 planner/executor/reviewer 是 靛/青/紫 三个冷色，
       青和紫在快速扫读时容易混；换成青绿后三色相拉开约 60°，
       且 fill 与 fg 两档的分工不变（fg 承载文字必须过 AA，改前跑 contrast.cjs）。 */
    '--node-planner': '#4f46e5',
    '--node-executor': '#0f766e',
    '--node-reviewer': '#7c3aed',
    '--node-system': '#64748b',
    '--node-planner-fill': '#6366f1',
    '--node-executor-fill': '#0d9488',
    '--node-reviewer-fill': '#7c3aed',
    '--node-system-fill': '#94a3b8',

    /* 计费档位（成本归因面板）。**单独一个色阶，不复用状态色**：
       「这次花了多少 / 成没成功」和「这笔钱按高峰还是低谷计」是两个语义，
       共用 绿/红 会让人把「低谷」读成「省了 = 好事」、把「高峰」读成「失败」。
       玫红 = 贵，橄榄绿 = 便宜一档，两者与全站任何状态色都不同族。
       玫红 = 贵，橄榄绿 = 便宜一档，两者与全站任何状态色都不同族。
       AA 实算（`tools/uicheck/contrast.cjs`，2026-09-26 跑，四种表面各量一次）：
         light  胶囊 #fce7f3/#be185d = 5.14:1、#ecfccb/#4d7c0f = 4.60:1；
                直接压卡片白底 = 6.04:1 / 4.99:1；
         dark   胶囊（rgba 先与 #14161e 合成）#332333/#f472b6 = 5.55:1、
                #283321/#a3e635 = 8.78:1；白底档文字 6.82:1 / 11.97:1。
       ⚠️ 改这四枚时必须重跑那支脚本 —— 只量白底会漏掉胶囊那一半。 */
    '--cost-peak': '#be185d',
    '--cost-peak-soft': '#fce7f3',
    '--cost-offpeak': '#4d7c0f',
    '--cost-offpeak-soft': '#ecfccb',

    /* 导航（62px 图标栏）—— 只留图标栏真正消费的两档：常态字色与 hover 底。
       文字侧栏那批 token（sider-bg / nav-group-fg / nav-*-active）随侧栏一起删除。 */
    '--nav-fg': '#4a5162',
    '--nav-bg-hover': '#f3f4f7',
    '--topbar-bg': 'rgba(255, 255, 255, 0.78)',

    /* 阴影 —— 采用参考包那套偏冷的 rgba(18,22,38,…)：同样深度下更「柔」，
       不像纯黑阴影那样在白底上发灰。另加一层主色投影给主按钮（参考包 signature）。 */
    '--shadow-1': '0 1px 2px rgba(18, 22, 38, 0.05)',
    '--shadow-2': '0 1px 3px rgba(18, 22, 38, 0.07), 0 1px 2px rgba(18, 22, 38, 0.04)',
    '--shadow-3': '0 6px 18px -6px rgba(18, 22, 38, 0.12), 0 2px 6px -2px rgba(18, 22, 38, 0.06)',
    '--shadow-4': '0 20px 48px -16px rgba(18, 22, 38, 0.22)',
    '--shadow-primary': '0 6px 16px -6px rgba(79, 70, 229, 0.55)',

    /* 横向滚动区两端的"还有内容"渐影（.scrollx-frame，走查 EV-01）。
       亮色压暗、暗色提亮 —— 深底上再画一层黑是看不见的，所以两主题不是同一方向。
       ⚠️ 这条不许写成 CSS 里的死 rgba：它必须跟着主题换方向。 */
    '--scroll-fade': 'rgba(18, 22, 38, 0.20)',

    /* 骨架屏 */
    '--skeleton-a': '#eef0f4',
    '--skeleton-b': '#e1e5ec',
  },
  dark: {
    '--bg-app': '#0b0d13',
    '--bg-sunken': '#0f1118',
    '--bg-surface': '#14161e',
    '--bg-surface-2': '#181b24',
    '--bg-hover': '#1c1f29',
    '--bg-active': '#222634',
    '--bg-inverse': '#e8eaf1',
    '--border': '#272b38',
    '--border-soft': '#222531',
    '--border-strong': '#333846',
    '--border-focus': '#4f46e5',
    /* 暗色下表格边框用半透明白（rgba(255,255,255,.10) 压在 #14161e 上合成约 #2c2d35，
       比同主题的实色 --border 更贴「线」的观感，不会把宽表画成一片灰格子）；
       代码/公式底比面板再**深一阶**到 slate（#0b1220），近黑的 --bg-sunken 压在
       暗色卡片上几乎没有层次。文字在此底上：text-1 15.58:1 / text-2 8.52:1。 */
    '--panel-line': 'rgba(255, 255, 255, 0.10)',
    '--code-bg': '#0b1220',

    '--text-1': '#e8eaf1',
    '--text-2': '#a8afc0',
    '--text-3': '#868da0',
    '--text-inverse': '#0b0d13',

    '--primary': '#818cf8',
    '--primary-hover': '#a5b4fc',
    '--primary-50': 'rgba(129, 140, 248, 0.14)',
    '--primary-100': 'rgba(129, 140, 248, 0.20)',
    '--primary-300': '#a5b4fc',
    '--primary-500': '#818cf8',
    '--primary-700': '#c7d2fe',
    '--primary-soft': '#1e2242',
    '--primary-soft-2': 'rgba(129, 140, 248, 0.30)',
    '--primary-soft-fg': '#c7d2fe',
    '--accent': '#a78bfa',
    '--brand-gradient': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    '--ring': 'rgba(129, 140, 248, 0.36)',

    '--success': '#34d399',
    '--success-fg': '#34d399',
    '--success-soft': 'rgba(52, 211, 153, 0.14)',
    '--warning': '#fbbf24',
    '--warning-fg': '#fbbf24',
    '--warning-soft': 'rgba(251, 191, 36, 0.14)',
    '--danger': '#f87171',
    '--danger-fg': '#f87171',
    '--danger-soft': 'rgba(248, 113, 113, 0.16)',
    '--info': '#60a5fa',
    '--info-fg': '#60a5fa',
    '--info-soft': 'rgba(96, 165, 250, 0.14)',

    '--st-queued-fg': '#fbbf24',
    '--st-queued-soft': 'rgba(251, 191, 36, 0.14)',
    '--st-running-fg': '#60a5fa',
    '--st-running-soft': 'rgba(96, 165, 250, 0.14)',
    '--st-done-fg': '#34d399',
    '--st-done-soft': 'rgba(52, 211, 153, 0.14)',
    '--st-aborted-fg': '#fb923c',
    '--st-aborted-soft': 'rgba(251, 146, 60, 0.14)',
    '--st-failed-fg': '#f87171',
    '--st-failed-soft': 'rgba(248, 113, 113, 0.16)',
    '--st-canceled-fg': '#a8afc0',
    '--st-canceled-soft': 'rgba(148, 163, 184, 0.12)',

    '--node-planner': '#818cf8',
    '--node-executor': '#2dd4bf',
    '--node-reviewer': '#a78bfa',
    '--node-system': '#94a3b8',
    '--node-planner-fill': '#818cf8',
    '--node-executor-fill': '#2dd4bf',
    '--node-reviewer-fill': '#a78bfa',
    '--node-system-fill': '#94a3b8',

    /* 计费档位暗色档：与 light 同两个语义，只是提亮一档并把 soft 换成半透明
       （暗色底上再铺一层浅粉/浅绿会变成刺眼的高亮块，且和深色卡边缘打架）。
       数字与 AA 判定同上一条，跑 contrast.cjs 现算。 */
    '--cost-peak': '#f472b6',
    '--cost-peak-soft': 'rgba(244, 114, 182, 0.14)',
    '--cost-offpeak': '#a3e635',
    '--cost-offpeak-soft': 'rgba(163, 230, 53, 0.14)',

    '--nav-fg': '#a8afc0',
    '--nav-bg-hover': 'rgba(255, 255, 255, 0.05)',
    '--topbar-bg': 'rgba(16, 18, 25, 0.82)',

    '--shadow-1': '0 1px 2px rgba(0, 0, 0, 0.4)',
    '--shadow-2': '0 2px 10px -2px rgba(0, 0, 0, 0.5), 0 1px 3px rgba(0, 0, 0, 0.3)',
    '--shadow-3': '0 20px 48px -16px rgba(0, 0, 0, 0.7), 0 4px 12px -4px rgba(0, 0, 0, 0.4)',
    '--shadow-4': '0 24px 56px -18px rgba(0, 0, 0, 0.78), 0 6px 16px -6px rgba(0, 0, 0, 0.5)',
    '--shadow-primary': '0 6px 16px -6px rgba(99, 102, 241, 0.45)',

    /* 同 light 那条：暗色下用半透明白提亮边缘（压黑在 #141826 上等于没有）。 */
    '--scroll-fade': 'rgba(255, 255, 255, 0.13)',

    '--skeleton-a': '#1a1e28',
    '--skeleton-b': '#232834',
  },
};

/** 日志终端层（**恒深**，两主题同一套 —— 终端是「嵌进页面的控制台」，不跟页面换肤）。
 *
 * 底色 #1e2734 是深灰蓝：比近黑（#0d1017）柔和，比 slate-900（#0f172a）暖一档，
 * 与站内白卡 / slate 文本同一色温，长日志读下来眼睛不用在两个明度世界之间来回适应。
 *
 * ⚠️ 这一层**不随主题变**，所以承载的文字色不能取 PALETTE：日志里的节点色以前
 * 直接用 `--node-planner` 那档，那是为**白底**调的（#4f46e5 在白底 6.28:1），
 * 压在深底上实测只有 2.84:1。所以这里单列 `--term-node-*` 四档，由
 * `logNodeColorVar()` 消费。**改这一层任何一档都要跑 contrast.cjs** —— 下面每个
 * 数字都是压平实测出来的，不是估的。
 *
 * 历史上这里叫 `--log-*`，2026-09-24 全量换成 `--term-*`：同一层皮肤曾经有
 * 三处各自定义深色（LOG_SURFACE、LOG_LEVEL_META.onDark 的字面 hex、PALETTE 的
 * --warning/--danger），换底色时只改一处就会留下半套旧色。现在 onDark 那档
 * 改成引用 var(--term-*)，终端色阶只剩这一张表。
 */
const TERM_SURFACE = {
  '--term-bg': '#1e2734',
  /* 工具条 / 页脚：比面板底亮一阶（与底差 1.1:1，靠明暗分层不靠描边） */
  '--term-surface': '#232e3d',
  /* 面板外描边 + 内部分隔：参考稿的 #2a3442。
     它相对底色只有 1.20:1 —— 这是**刻意**的：描边不承载信息，只要让面板在白卡上
     读成「嵌进去的一块」就够；真正的存在感来自 #2a3442 vs 页面底 #eff1f5 = 11.13:1。 */
  '--term-border': '#2a3442',
  /* 行间细线：参考稿的 rgba(255,255,255,0.04)，压到 0.05 才在 #1e2734 上看得见（合成 #29323e） */
  '--term-rule': 'rgba(255, 255, 255, 0.05)',
  /* 正文用 #c9d1d9（9.75:1）而不是纯白：纯白在深底上小字会发「眩」，长行读久了刺眼 */
  '--term-text': '#c9d1d9',
  /* 弱档：序号列 / DEBUG 正文 / 心跳尾巴 / 页脚计数 / 光标共用这一档灰。
     ⚠️ 参考稿给的 #8b98a5 在**空底**上是 5.11:1（过 AA），但心跳行有 --term-live-bg
     那层底色，压上去掉到 **4.46:1**，12px 文字就不达标了 —— 所以取 #94a3b8：
     空底 5.87:1、心跳底 5.12:1，两处都过。 */
  '--term-seq': '#94a3b8',
  /* 级别三档（DEBUG 走 --term-seq，不单独给色）：info 7.78 / warn 8.01 / error 5.96 */
  '--term-info': '#58c7f1',
  '--term-warn': '#f5b044',
  '--term-error': '#ff7a7a',
  /* 节点色（深底专用四档）：5.05 / 8.09 / 5.53 / 5.87 */
  '--term-node-planner': '#818cf8',
  '--term-node-executor': '#2dd4bf',
  '--term-node-reviewer': '#a78bfa',
  '--term-node-system': '#94a3b8',
  /* 关键字命中：琥珀底 + 更亮的琥珀字（#fde68a 压在合成底 #534b30 上 6.98:1） */
  '--term-hit-bg': 'rgba(251, 191, 36, 0.24)',
  '--term-hit-fg': '#fde68a',
  '--term-hit-ring': '#fbbf24',
  /* 心跳行底色：比面板深一档不成立（会更糊），改走「亮一档的灰蓝薄层」，
     合成 #28313e；上面 --term-seq 的 4.46 陷阱就是在这层上量出来的 */
  '--term-live-bg': 'rgba(139, 152, 165, 0.09)',
} as const;

/* ------------------------------------------------------------------ *
 * 2. 尺度（两主题共用）
 * ------------------------------------------------------------------ */

export const SCALE: Record<string, string> = {
  /* 间距 —— 4px 基准，只用这 8 档 */
  '--sp-1': '4px',
  '--sp-2': '8px',
  '--sp-3': '12px',
  '--sp-4': '16px',
  '--sp-5': '20px',
  '--sp-6': '24px',
  '--sp-8': '32px',
  '--sp-10': '40px',

  /* 字号 —— 中文正文最小 12px */
  '--fs-11': '11px',
  '--fs-12': '12px',
  '--fs-13': '13px',
  '--fs-14': '14px',
  /* 15 这一档只为「答案里的二级标题」存在：正文是 14px，标题必须比正文大一档
     才称得出层级，但 16px 是页面级标题的地盘，不该被正文内部的层级占用。 */
  '--fs-15': '15px',
  '--fs-16': '16px',
  '--fs-20': '20px',
  '--fs-24': '24px',
  '--fs-28': '28px',

  /* 行高 */
  '--lh-tight': '1.3',
  '--lh-snug': '1.5',
  '--lh-body': '1.65',
  '--lh-log': '1.65',

  /* 字重 */
  '--fw-regular': '400',
  '--fw-medium': '500',
  '--fw-semibold': '600',
  '--fw-bold': '700',

  /* 圆角 —— 2026-09-23 重设计对齐参考稿：卡片 12、控件 9、标签 pill。
     原来 10/14/18 偏软，卡片越大越显得「胖」，收一档更接近 Linear/Vercel 的克制感。 */
  '--r-sm': '6px',
  '--r-md': '9px',
  '--r-lg': '12px',
  '--r-xl': '14px',
  '--r-pill': '999px',

  /* 动效 —— 时长/缓动取自参考包并落到 token，组件里不再写魔法值
     · hover / 按压        180ms  ease            （参考包 .ap-hover）
     · 功能性展开折叠      200ms  --ease
     · 入场（卡片、页块）  420ms  --ease-emph      （参考包 ap-fade-up，强缓出）
     · 日志新行            220ms  ease            （参考包 ap-log-in）
     · 状态脉动            1800ms ease-out 循环    （参考包 ap-pulse-dot） */
  '--dur-fast': '120ms',
  '--dur-base': '200ms',
  '--dur-slow': '320ms',
  '--dur-hover': '180ms',
  '--dur-enter': '420ms',
  '--dur-log': '220ms',
  '--dur-pulse': '1800ms',
  '--ease': 'cubic-bezier(0.4, 0, 0.2, 1)',
  '--ease-out': 'cubic-bezier(0.16, 1, 0.3, 1)',
  /* 入场专用：先快后极缓的「甩尾」曲线，比 --ease-out 更有重量感 */
  '--ease-emph': 'cubic-bezier(0.22, 1, 0.36, 1)',

  /* 图标尺度（参考包 Menu iconSize=16 / brand mark 20 / 行内小图标 14） */
  '--icon-sm': '14px',
  '--icon-md': '16px',
  '--icon-lg': '20px',
  '--icon-stroke': '1.4',

  /* 层级 */
  '--z-sticky': '10',
  '--z-sider': '40',
  '--z-topbar': '50',
  '--z-tabbar': '60',
  '--z-drawer': '100',

  /* 骨架尺寸 —— 2026-09-23 重设计：文字导航收成 62px 图标栏，
     任务列表（268px）从「第二条左栏」移进工作区并可一键收起，
     主内容区因此拿回约 390px 宽度（清单 P0#1）。 */
  '--rail-w': '62px',
  '--list-w': '268px',
  '--topbar-h': '56px',
  '--tabbar-h': '58px',
  '--content-max': '1560px',
  /* 结构化答案的正文限宽：长行满宽读起来累，820px 约 75 个汉字 */
  '--measure': '820px',
} as const;

export const FONT_STACK =
  "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif";
export const MONO_STACK = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

/** 把当前主题的变量写入 <html>。`main.tsx` 在首次渲染前同步调用，避免闪白。 */
export function applyThemeVars(mode: ThemeMode): void {
  const root = document.documentElement;
  const vars = { ...SCALE, ...TERM_SURFACE, ...PALETTE[mode] };
  for (const [name, value] of Object.entries(vars)) {
    root.style.setProperty(name, value);
  }
  // 让原生控件（滚动条、日期选择器）跟随主题
  root.style.colorScheme = mode;
  root.dataset.theme = mode;
}

/** 读系统偏好，作为「跟随系统」的初值。 */
export function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/* ------------------------------------------------------------------ *
 * 3. 语义映射
 * ------------------------------------------------------------------ */

export interface StatusMeta {
  label: string;
  /** 卡片/对话气泡上一句话解释，避免「aborted」这类后端词直接糊到用户脸上。 */
  hint: string;
  /** 是否属于「已结束」，用于决定要不要继续跑计时器/进度条。 */
  terminal: boolean;
}

/** 状态文案。取值只来自后端（api/schemas.py），前端不新增状态。 */
export const STATUS_META: Record<TaskStatus, StatusMeta> = {
  queued: { label: '排队中', hint: '已受理，等待并发位', terminal: false },
  running: { label: '运行中', hint: 'Planner → Executor → Reviewer 编排中', terminal: false },
  done: { label: '成功', hint: 'Reviewer 通过并收口', terminal: true },
  aborted: {
    label: '已收口',
    hint: '迭代耗尽或超时后被强制收口（后端无独立 timeout 状态）',
    terminal: true,
  },
  failed: { label: '失败', hint: '执行中抛出未恢复的异常', terminal: true },
  canceled: { label: '已取消', hint: '在节点边界被取消', terminal: true },
};

export interface NodeMeta {
  label: string;
  /** 形状前缀 —— 不只靠颜色区分节点（色盲安全）。 */
  glyph: string;
  desc: string;
}

export const NODE_META: Record<AgentNode, NodeMeta> = {
  planner: { label: 'Planner', glyph: '◆', desc: '拆解任务，产出计划' },
  executor: { label: 'Executor', glyph: '▶', desc: '按步执行，调用工具' },
  reviewer: { label: 'Reviewer', glyph: '✔', desc: '按阈值复核，决定收口或退回' },
  system: { label: 'System', glyph: '·', desc: '队列与平台侧事件' },
};

/** 节点色：一律通过 CSS 变量取，两主题自动适配。 */
export function nodeColorVar(node: AgentNode, kind: 'fg' | 'fill' = 'fg'): string {
  return kind === 'fg' ? `var(--node-${node})` : `var(--node-${node}-fill)`;
}

/** 日志面板里的节点色：走**主题无关**的 `--term-node-*` 四档。
 *  不能用 `nodeColorVar()` —— 那组值是为白底调的，压在终端深底上只有 2.8~3.8:1
 *  （见 TERM_SURFACE 的注释）。 */
export function logNodeColorVar(node: AgentNode): string {
  return `var(--term-node-${node})`;
}

/** 状态色：同上。 */
export function statusColorVar(status: TaskStatus, kind: 'fg' | 'soft' = 'fg'): string {
  return status === 'canceled'
    ? `var(--st-canceled${kind === 'fg' ? '-fg' : '-soft'})`
    : `var(--st-${status}-${kind === 'fg' ? 'fg' : 'soft'})`;
}

export interface LevelMeta {
  label: string;
  /** 浅色上下文（表格、Tag）用的文字色。 */
  fg: string;
  /** 终端层里的文字色 —— **存的是 CSS 变量引用**，不是第二份字面 hex。
   *  以前这里是四个硬编码色（#8b93a6 / #dbe2ee / #fcd34d / #fca5a5），
   *  换终端底色时它们不会跟着换，等于同一层皮肤养两套色阶。
   *  DEBUG 不单独给色，与序号列共用弱档。 */
  onDark: string;
}

/** 日志级别：**不只靠颜色**——面板里每条都带 LEVEL 徽标。 */
export const LOG_LEVEL_META: Record<LogLevel, LevelMeta> = {
  debug: { label: 'DEBUG', fg: '#6b7280', onDark: 'var(--term-seq)' },
  info: { label: 'INFO', fg: '#4a5162', onDark: 'var(--term-info)' },
  warn: { label: 'WARN', fg: '#b45309', onDark: 'var(--term-warn)' },
  error: { label: 'ERROR', fg: '#b91c1c', onDark: 'var(--term-error)' },
};

/** 指标变好/变差的方向色。
 *
 * 注意：本项目**不是金融场景**，指标是「越大越好」（nDCG/MRR/Hit），
 * 所以遵循 docs/frontend_ui_review.md §3.6 的口径 —— 变好=绿、变差=红，
 * 并且**必须同时给符号与文字方向**，不靠颜色单独传达。
 */
export function deltaColorVar(delta: number): string {
  if (delta > 0) return 'var(--success-fg)';
  if (delta < 0) return 'var(--danger-fg)';
  return 'var(--text-3)';
}

/** 同图多系列的固定色板（Top-1 / Top-3 / Hit@5 / MRR 顺序消费）。
 *
 * 挑色口径：色相间隔拉开、纯色填充。**不用渐变** —— 竖向渐变让等高柱看着
 * 不等高，明度跨度还会被误读成数值差（2026-09-23 清单 P1#4）。
 * 加第五个系列时在这里补色，别在页面里现编，也不按索引取模 —— 撞色正是这么来的。
 */
export const CHART_SERIES: Record<ThemeMode, string[]> = {
  light: ['#4f46e5', '#0d9488', '#d97706', '#2563eb'],
  dark: ['#818cf8', '#2dd4bf', '#fbbf24', '#60a5fa'],
};

/* ------------------------------------------------------------------ *
 * 4. AntD token 映射
 * ------------------------------------------------------------------ */

function baseToken(mode: ThemeMode): ThemeConfig['token'] {
  const c = PALETTE[mode];
  return {
    colorPrimary: c['--primary'],
    colorSuccess: c['--success'],
    colorWarning: c['--warning'],
    colorError: c['--danger'],
    colorInfo: c['--info'],
    colorBgLayout: c['--bg-app'],
    colorBgContainer: c['--bg-surface'],
    colorBgElevated: mode === 'light' ? '#ffffff' : c['--bg-surface-2'],
    colorBorder: c['--border-strong'],
    colorBorderSecondary: c['--border'],
    colorText: c['--text-1'],
    colorTextSecondary: c['--text-2'],
    colorTextTertiary: c['--text-3'],
    colorTextQuaternary: c['--text-3'],
    fontFamily: FONT_STACK,
    fontFamilyCode: MONO_STACK,
    fontSize: 13,
    borderRadius: 9,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    /* 控件高度对齐参考包的 32（原 34）——控件更紧凑，信息密度更接近 GitHub */
    controlHeight: 32,
    controlHeightSM: 28,
    controlHeightLG: 40,
    lineWidth: 1,
    wireframe: false,
    motionDurationFast: '0.12s',
    motionDurationMid: '0.18s',
    motionDurationSlow: '0.32s',
    motionEaseOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
  };
}

function components(mode: ThemeMode): ThemeConfig['components'] {
  const c = PALETTE[mode];
  return {
    Button: {
      /* 主按钮带一点主色投影（参考包的 signature），其余保持无阴影避免发脏 */
      primaryShadow: c['--shadow-primary'],
      defaultShadow: 'none',
      dangerShadow: 'none',
      fontWeight: 500,
      paddingInline: 16,
    },
    Card: {
      bodyPadding: 18,
      headerHeight: 46,
      headerFontSize: 14,
    },
    Table: {
      headerBg: c['--bg-surface-2'],
      headerColor: c['--text-2'],
      headerSplitColor: 'transparent',
      /* 行 hover 用主色最浅一档（参考包用 PRIMARY[50]），比中性灰更有「可点」暗示 */
      rowHoverBg: c['--primary-50'],
      cellPaddingBlock: 10,
      cellPaddingInline: 14,
      borderColor: c['--border'],
      fontSize: 12,
    },
    Tabs: {
      horizontalItemPadding: '10px 0',
      titleFontSize: 13,
      horizontalMargin: '0 0 14px 0',
      inkBarColor: c['--primary'],
    },
    Input: { paddingBlock: 6, activeShadow: `0 0 0 3px ${c['--ring']}` },
    Select: { optionSelectedBg: c['--primary-soft'], optionSelectedColor: c['--primary-soft-fg'] },
    Switch: { trackHeight: 20, trackMinWidth: 38, handleSize: 16 },
    Segmented: {
      itemSelectedBg: c['--bg-surface'],
      itemSelectedColor: c['--text-1'],
      trackBg: mode === 'light' ? c['--bg-sunken'] : c['--bg-sunken'],
      borderRadius: 999,
      itemColor: c['--text-2'],
      trackPadding: 3,
    },
    Tooltip: { colorBgSpotlight: mode === 'light' ? '#14161d' : '#2a3042', borderRadius: 8 },
    Drawer: { paddingLG: 0 },
    Empty: { colorTextDescription: c['--text-3'] },
    Progress: { defaultColor: c['--primary'], remainingColor: c['--bg-active'] },
    Message: { contentPadding: '10px 16px' },
  };
}

export const ANTD_THEME: Record<ThemeMode, ThemeConfig> = {
  light: {
    algorithm: antdTheme.defaultAlgorithm,
    token: baseToken('light'),
    components: components('light'),
  },
  dark: {
    algorithm: antdTheme.darkAlgorithm,
    token: baseToken('dark'),
    components: components('dark'),
  },
};

/* ------------------------------------------------------------------ *
 * 5. 兼容导出（老引用保留，避免破坏既有 import）
 * ------------------------------------------------------------------ */

/** @deprecated 用 `PALETTE.light['--primary']`；保留仅为兼容旧引用。 */
export const TOKENS = {
  colorPrimary: PALETTE.light['--primary'],
  colorSuccess: PALETTE.light['--success'],
  colorWarning: PALETTE.light['--warning'],
  colorError: PALETTE.light['--danger'],
  colorInfo: PALETTE.light['--info'],
  colorBgLayout: PALETTE.light['--bg-app'],
  colorBorder: PALETTE.light['--border'],
  colorTextSecondary: PALETTE.light['--text-2'],
  borderRadius: 10,
  fontSizeBase: 13,
} as const;

/** @deprecated 用 `nodeColorVar()`。 */
export const NODE_COLOR: Record<string, string> = {
  planner: PALETTE.light['--node-planner'],
  executor: PALETTE.light['--node-executor'],
  reviewer: PALETTE.light['--node-reviewer'],
  system: PALETTE.light['--node-system'],
};

/** @deprecated 用 `NODE_META[n].glyph`。 */
export const NODE_PREFIX: Record<string, string> = {
  planner: '◆',
  executor: '▶',
  reviewer: '✔',
  system: '·',
};

/** @deprecated 用 `LOG_LEVEL_META[l].fg`。 */
export const LOG_LEVEL_COLOR: Record<string, string> = {
  debug: LOG_LEVEL_META.debug.fg,
  info: LOG_LEVEL_META.info.fg,
  warn: LOG_LEVEL_META.warn.fg,
  error: LOG_LEVEL_META.error.fg,
};
