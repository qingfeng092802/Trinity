/** 展示层格式化工具。
 *
 * 原则（沿用 docs/frontend_ui_review.md §2 A29 / A28）：
 *  - 一律走 `Intl`，不手拼 `¥` + `toFixed`、不硬编码 locale。
 *  - 未知比已知更诚实：`null` / `undefined` / `NaN` 返回 `—`（待测），**不补 0**。
 *  - 数字展示统一 tabular-nums，纵向可对齐。
 */

const intFmt = new Intl.NumberFormat('zh-CN');
const decFmt: Record<number, Intl.NumberFormat> = {};

function decimal(digits: number): Intl.NumberFormat {
  decFmt[digits] ??= new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return decFmt[digits];
}

const clockFmt = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/** 空值统一占位符。 */
export const PENDING = '待测';
export const DASH = '—';

export function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** 整数千分位。 */
export function fmtInt(v: number | null | undefined): string {
  return isNum(v) ? intFmt.format(v) : DASH;
}

/** 字节数 → 人话。**全站唯一的体积入口**（知识库上传方案 §6 避坑 9：
 *  不许在页面里手写 `size / 1024 / 1024 + ' MB'` 这种一次性换算）。
 *
 * ⚠️ 走的是**二进制**档：1 MB = 1024² = 1,048,576 字节。这不是随手选的口味问题 ——
 * 后端判超限用的正是 `settings.knowledge_max_file_mb * 1024 * 1024`
 * （`api/routes/knowledge.py:116`），所以界面上那句「≤ 50 MB」实际是 52,428,800 字节。
 * 谁把这里改成十进制（÷1000），就会出现「进度条说没超、后端回了个 422」这种
 * 两边各自正确、合起来在骗人的对不上。
 */
export function fmtBytes(v: number | null | undefined): string {
  if (!isNum(v) || v < 0) return DASH;
  if (v < 1024) return `${v} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let n = v / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  // 小于 10 那一档多留一位：3.24 MB 与 3.2 MB 在"为什么这份传不上去"面前不是一回事。
  return `${n < 10 ? n.toFixed(2) : n.toFixed(1)} ${units[i]}`;
}

/** 定点小数。 */
export function fmtDec(v: number | null | undefined, digits = 2): string {
  return isNum(v) ? decimal(digits).format(v) : DASH;
}

/** 0~1 比例 → 百分比字符串，缺值给「待测」。 */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : PENDING;
}

/** 带符号的百分点变化。 */
export function fmtDelta(v: number | null | undefined, digits = 1): string {
  if (!isNum(v)) return PENDING;
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;
}

/** 毫秒 → 人类可读时长（<1s 保留 ms；<60s 用 s；否则 m+s）。
 *
 * ⚠️ 三条分支的边界都要「先判进位再换档」，否则会出现 `1m 60s`：
 * 分/秒各自取整时，59.6s 那一段会被 `Math.round` 抬成 60。
 * 换算成 m/s 之前统一先 `Math.round(ms/1000)` 取总秒数，再拆。
 */
export function fmtDuration(ms: number | null | undefined): string {
  if (!isNum(ms)) return DASH;
  if (ms < 999.5) return `${Math.round(ms)}ms`;
  if (ms < 59_950) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`;
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}

/** 时间戳 → HH:mm:ss。 */
export function fmtClock(ts: number | null | undefined): string {
  return isNum(ts) ? clockFmt.format(new Date(ts)) : DASH;
}

/** 金额（元）→ 紧凑展示。
 *
 * ⚠️ 这是**钱不是 token**：后端 /tasks 的 cost 单位是元（实测 0.013139），
 * 千万别当 token 数显示。小额（<1 元）保留 4 位有效数字才有意义，
 * 否则 ¥0.01 和 ¥0.0131 看起来一样，用户判断不出哪个任务更贵。
 */
export function fmtCost(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  if (v === 0) return '¥0';
  if (v < 1) return `¥${v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')}`;
  return `¥${v.toFixed(2)}`;
}

/** 金额**定宽**版：固定 ``digits`` 位小数，绝不 strip 尾零。
 *
 *  为什么不改 `fmtCost`（决策 C5）：上面那个 strip 是**单值展示**对的行为 ——
 *  「¥0.0131」比「¥0.01310000」好读。但成本表是**竖排多行**，strip 之后：
 *
 *      ¥0.0131     ← 高峰
 *      ¥0.01       ← 低谷（真值是 0.0100）
 *
 *  两行既对不齐、也看不出第二位其实是个整数尾零，读者会把「0.01」当成
 *  "恰好一分"这种精度更高的断言。表格里的数需要的是**可比性**，不是简洁。
 *  所以新加一个口径，而不是把原来那个改掉（改了整个控制台的单值展示跟着变宽）。
 *
 *  默认 4 位的依据：一次最短的真实调用实测 7.07e-4 元（``task-5ba7127ba5f0`` 的
 *  planner），2 位会把它显示成 ¥0.01 —— 与 4 位差的正是"这次调用到底花了多少"。
 *
 *  @param v 人民币元；null/undefined → '—'（与全站缺数口径一致，不是 '¥0.0000'）
 *  @param digits 小数位数
 */
export function fmtCostFixed(v: number | null | undefined, digits = 4): string {
  if (!isNum(v)) return DASH;
  return `¥${v.toFixed(digits)}`;
}

/** 后端给的北京时间 ISO 串 → `MM-DD HH:mm`（**只截断、不换算**）。
 *
 *  知识库那三个时间字段（`created_at` / `updated_at` / `indexed_at`）在后端已经过
 *  `to_cn()` 统一成 +08:00（`api/routes/knowledge.py:67-69`），所以这里按字面切就对了。
 *  ⚠️ 别拿它去显示 `tasks.created_at` —— 那一个是 **UTC**，同一个页面上两种时间口径
 *  只差那 8 个小时，最难查。
 *  缺秒与毫秒都无所谓：只取到分钟，跨年场景靠"相对时间"那一支解决。
 */
export function fmtDateTime(v: string | null | undefined): string {
  if (typeof v !== 'string' || !v) return DASH;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(v);
  if (!m) return v; // 认不出的格式就原样贴出来，别静默丢字
  return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
}

/** 时间戳 → 相对时间（列表里比绝对时间更好读）。 */
/** 「距今 N 秒/分/时/天」的**纯**版：调用方自己交时间差，这里不读时钟。
 *
 *  为什么要拆出来（P1-01，报告 A4②）：`relativeTime` 内部读 `Date.now()`，
 *  于是"让它每秒跳一下"只能靠**父组件每秒重渲染**来驱动 —— 整页陪一枚小读数跳。
 *  现在计时器关进 `components/Elapsed.tsx` 那一枚小组件，它把毫秒差交给你，
 *  措辞口径与 `relativeTime` 逐字相同（同一条分支表，两份实现必然漂移，所以只留一份）。 */
export function relativeFromDelta(deltaMs: number): string {
  if (!isNum(deltaMs)) return DASH;
  if (deltaMs < 0) return '刚刚';
  const sec = Math.floor(deltaMs / 1000);
  if (sec < 60) return `${sec} 秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  return `${Math.floor(hour / 24)} 天前`;
}

export function relativeTime(ts: number | null | undefined): string {
  if (!isNum(ts)) return DASH;
  return relativeFromDelta(Date.now() - ts);
}

/** 先截断后使用 —— 顺序很重要：先转义再截断会把 `&amp;` 截成 `&am`。 */
export function truncate(text: string | null | undefined, max: number): string {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** 把「可能是 object」的后端值压成展示文本：字符串原样透，其余按 JSON 缩进两格。
 *
 *  这是崩溃防线，不是排版美化 —— object 直接进 `<pre>` 会让 React 抛
 *  「Objects are not valid as a React child」并卸载整棵树（白屏）。
 *  口径与 mock/taskMock.ts 里预格式化的入参一致（indent 2），两条数据源长得一样。
 */
export function jsonToText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

/** 字符串化 JSON 的紧凑预览（只压空白，不解析重算）。 */
export function compact(text: string | null | undefined, max = 160): string {
  if (!text) return '';
  return truncate(text.replace(/\s+/g, ' ').trim(), max);
}

/** 复制到剪贴板，只报成败、不报原因。
 *
 *  ⚠️ 调用方**不要**直接 `void copyText(...)`：不安全上下文（http）、用户拒绝权限、
 *  浏览器禁写剪贴板时它会返回 false，静默吞掉就等于「点了没反应」。
 *  界面上一律走 `hooks/useCopy`，那里把成败都说给了用户。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** 导出 CSV（客户端生成，带 BOM 以便 Excel 正确识别 UTF-8）。
 *
 * ⚠️ 三个必须一起做的动作，少一个就"点了没反应"（报告 B9）：
 *  1. **anchor 必须先进 DOM** 再 `click()` —— Firefox 对不在文档里的 `<a>` 直接忽略下载，
 *     Safari 亦同；旧版没 append 就点，于是一些浏览器上什么也不发生，还不报错。
 *  2. `revokeObjectURL` **不能同步调** —— 撤销发生在下载真正开始之前，Safari 会把它
 *     当成一个已失效的链接而丢弃。挂到下一个宏任务里再撤。
 *  3. `click()` 之后把 anchor 摘掉 —— 否则会一轮一轮攒下无主的 `<a>`。
 *     （摘的顺序必须在 revoke 之前，revoke 已经排到宏任务里，两者不冲突。）
 */
export function downloadCsv(filename: string, header: string[], rows: Array<Array<string | number>>): void {
  const escapeCell = (cell: string | number): string => {
    const s = String(cell ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const body = [header, ...rows].map((line) => line.map(escapeCell).join(',')).join('\r\n');
  const blob = new Blob([`\uFEFF${body}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
