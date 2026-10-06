import type { ToolCall, ToolSpecView } from '../types';

/* 工具调用的「用户视角」语义层。

 分工要说清楚，别把这张表当事实来源：
 - **后端 /api/tools 才是事实来源**：有哪些工具、注册表说明、危险级、超时、重试。
   （api/routes/tools.py 的 docstring 明确写了「前端绝不硬编码工具名」。）
 - **这张表只是展示层覆盖**：把写给模型看的注册表说明，换成给人看的一句话；
   并声明「这次调用在干什么」该看入参的哪个字段、这工具花不花钱。
 - **字典缺项一律降级**：未收录的工具走后端 description 兜底，标题退回「正在调用 <name>」，
   绝不因为字典没跟上就显示空白或瞎编。
 */

export type Billing = 'local' | 'external' | 'llm';

export interface ToolDisplay {
  /** 大白话一句话，Tooltip 标题 */
  plain: string;
  /** 意图标题的动词，如「正在算这笔数」 */
  verb: string;
  /** 入参里最能说明意图的字段，按优先级取第一个存在的 */
  intentArgs: string[];
  /** 计费口径（不标单价，只标语义） */
  billing: Billing;
  /** 入参不适合直接当标题时的提炼（code_exec 的入参是一整段源码）。
   *  返回 null 就退回「动词：关键入参」那条通用路径。 */
  titleFromArgs?: (args: Record<string, unknown>) => string | null;
  /** 哪个入参字段是整段源码。命中后入参块改走 CodeBlock —— JSON 树会把源码当字符串
   *  叶子，`\n` 被打回字面量、整段挤成一行，这就是清单 P0 那坨乱码的成因。 */
  codeArg?: string;
  /** 入参 / 出参改上下堆叠。代码型工具的入参动辄几十行，左右分栏等于把代码压成一条缝。 */
  stack?: boolean;
}

export const BILLING_NOTE: Record<Billing, string> = {
  local: '本地执行 · 不产生 API 费用',
  external: '走外部服务 · 依赖网络',
  llm: '内部会再调一次模型 · 计入 token 费用',
};

/** 口径依据（2026-09-23 读 core/tools/builtin/*）：
 *  calculator / code_exec / file_io 纯本地；knowledge_search 跑本地向量检索
 *  （fastembed 推理，不产生 API 账单，但吃 CPU）；web_search 打 DuckDuckGo；
 *  extract 内部 adapter.invoke_json 再调一次小模型。 */
/** code_exec 的标题提炼规则：一段源码 → 一句人话。
 *
 *  口径：只认**特征足够明确**的写法，认不出就报字符数，绝不回落到代码截断
 *  （「正在跑一段代码：import os, re, time…」这种把机器视角又贴回脸上的写法）。
 *  顺序有意义：先具体后泛化，`os.walk` 这类扫描排在通用文件读写之前。
 *  新增规则时配一条测试（tools/uicheck/toolMeta.test.cjs），别只凭感觉加正则。 */
const CODE_INTENT: Array<[RegExp, string]> = [
  [/\brequests\.(get|post|put|patch|delete)\s*\(|\bhttpx\.|\burllib\.|\bhttp\.client\b/, '正在发送网络请求'],
  [/\bos\.(walk|listdir|scandir)\s*\(|\bshutil\.(rmtree|copy|move)\s*\(/, '正在遍历或整理文件系统'],
  [/\bsubprocess\.|os\.system\s*\(|os\.popen\s*\(/, '正在调用外部命令'],
  [/\bsocket\.|\baiohttp\.|\bftplib\.|\bsmtplib\./, '正在建立网络连接'],
  [/\bplt\.(show|savefig)\s*\(|matplotlib/, '正在画图'],
  [/\bpd\.read_(csv|excel|parquet)\s*\(|\bpandas\b/, '正在读表格数据'],
  [/\bjson\.dump|open\s*\([^)]*['"]w[+'"]/, '正在写文件'],
  [/\bjson\.load|open\s*\([^)]*['"]r['"]/, '正在读文件'],
  [/\bre\.(compile|findall|search|match|sub)\s*\(|regex\./, '正在做文本匹配'],
  [/\bnumpy\b|\bnp\.[a-z]+\(|\bmath\.(sqrt|log|exp|pow)\s*\(/, '正在做数值计算'],
  [/\btime\.sleep\s*\(|threading\.Timer/, '正在等待或计时'],
  [/\bcv2\.|\bPIL\./, '正在处理图像'],
];

/** 无 thought 时，从 code 入参里提炼一句人话的意图。 */
function codeIntent(code: string): string {
  const src = (code ?? '').trim();
  /* 「import os + roots = [...]」这个组合是遍历文件树的典型骨架，两条特征同时成立才算，
     单看 import os 会把「读个环境变量」也说成扫描文件。 */
  if (/\bimport\s+os\b|\bfrom\s+os\b/.test(src) && /\broots\s*=\s*\[/.test(src)) {
    return '正在扫描系统文件';
  }
  for (const [re, label] of CODE_INTENT) {
    if (re.test(src)) return label;
  }
  return `正在执行 Python 脚本（${src.length.toLocaleString('zh-CN')} 字符）`;
}

export const TOOL_DISPLAY: Record<string, ToolDisplay> = {
  calculator: {
    plain: '内置计算器：执行一条数学表达式，返回精确数值',
    verb: '正在算这笔数',
    intentArgs: ['expression'],
    billing: 'local',
  },
  code_exec: {
    plain: '沙箱里跑一段 Python：取回 print 出来的结果',
    verb: '正在跑一段代码',
    intentArgs: ['code'],
    billing: 'local',
    /* 入参是整段源码 —— 主标题必须提炼，代码原文只留在副行/入参块里。 */
    titleFromArgs: (a) => (typeof a.code === 'string' && a.code.trim() ? codeIntent(a.code) : null),
    codeArg: 'code',
    /* 代码一长，左右分栏就把它压成一条缝（清单 P1：把横向空间还给代码）。 */
    stack: true,
  },
  knowledge_search: {
    plain: '检索本地知识库：从你上传的文档里找相关片段',
    verb: '正在翻知识库',
    intentArgs: ['query'],
    billing: 'local',
  },
  web_search: {
    plain: '联网搜索：抓外部网页的搜索结果',
    verb: '正在联网查',
    intentArgs: ['query'],
    billing: 'external',
  },
  file_io: {
    plain: '沙箱工作区里的文本文件读写',
    verb: '正在读写文件',
    intentArgs: ['path'],
    billing: 'local',
  },
  extract: {
    plain: '按给定 schema 从一段自由文本里抽取结构化字段',
    verb: '正在抽取字段',
    intentArgs: ['text', 'schema'],
    billing: 'llm',
  },
};

const FILE_IO_VERB: Record<string, string> = {
  read: '正在读文件',
  write: '正在写文件',
  append: '正在追加写文件',
  list: '正在列目录',
};

export function displayOf(name: string): ToolDisplay | null {
  return TOOL_DISPLAY[name] ?? null;
}

/** 一行摘要：压掉换行与多余空白，超长截断。 */
function oneLine(s: string, max = 110): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max - 1).trimEnd()}…`;
}

/** 入参在边界处已被 jsonToText 压成文本，这里解回来挑字段；解不动就不猜。 */
function parseArgs(args: string): Record<string, unknown> | null {
  const t = (args ?? '').trim();
  if (!t.startsWith('{')) return null;
  try {
    const v: unknown = JSON.parse(t);
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** 「正在算这笔数：(1024*12*1.12 + …) / 0.92」里冒号后面那段。 */
export function argSummary(name: string, args: string): string | null {
  const d = displayOf(name);
  const parsed = parseArgs(args);
  if (!d || !parsed) return null;
  for (const key of d.intentArgs) {
    const raw = parsed[key];
    if (typeof raw === 'string' && raw.trim() !== '') return oneLine(raw);
    if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw);
  }
  return null;
}

/** 动词：file_io 按 mode 细分，其余用字典里的静态动词。 */
export function verbFor(name: string, args: string): string {
  const d = displayOf(name);
  if (!d) return `正在调用 ${name}`;
  if (name === 'file_io') {
    const mode = parseArgs(args)?.mode;
    if (typeof mode === 'string' && FILE_IO_VERB[mode]) return FILE_IO_VERB[mode];
  }
  return d.verb;
}

/** 卡片主标题：执行器自己写的 thought 最接近人话，优先用它；
 *  没有 thought 时，工具自己带提炼逻辑就走提炼（code_exec），
 *  否则退回「动词：关键入参」。 */
export function intentTitle(name: string, args: string, thought: string | null): string {
  const t = (thought ?? '').trim();
  if (t) return oneLine(t.replace(/[。.\s]+$/, ''));
  const d = displayOf(name);
  const parsed = parseArgs(args);
  if (d?.titleFromArgs && parsed) {
    const custom = d.titleFromArgs(parsed);
    if (custom) return oneLine(custom, 120);
  }
  const summary = argSummary(name, args);
  const verb = verbFor(name, args);
  return summary ? `${verb}：${summary}` : verb;
}

/** 副行：主标题走了 thought 时，把「动词：关键入参」补下来，两条都是真实数据。 */
export function intentSub(name: string, args: string, thought: string | null): string | null {
  if (!(thought ?? '').trim()) return null;
  const summary = argSummary(name, args);
  return summary ? oneLine(`${verbFor(name, args)}：${summary}`, 160) : null;
}

/* ---------------- 入参块怎么摆：源码走代码块，其余走 JSON 树 ---------------- */

/** 这次调用的源码入参。解不出 JSON / 字段缺失 / 不是非空字符串一律返回 null，
 *  交回 JsonView 原样平铺 —— 展示层不替后端编代码。 */
export function codeArgOf(name: string, args: string): string | null {
  const key = displayOf(name)?.codeArg;
  if (!key) return null;
  const raw = parseArgs(args)?.[key];
  return typeof raw === 'string' && raw.trim() !== '' ? raw : null;
}

/** 入参 / 出参是否上下堆叠（字典声明，不做长度猜测：同一页里卡片忽宽忽窄更难读）。 */
export function fieldsStack(name: string): boolean {
  return displayOf(name)?.stack === true;
}

/** 除源码之外的其余入参，压成一行小字（`timeout_s=30` 这种）。没有就返回 null。 */
export function argMetaOf(name: string, args: string): string | null {
  const key = displayOf(name)?.codeArg;
  const parsed = parseArgs(args);
  if (!key || !parsed) return null;
  const bits: string[] = [];
  for (const [k, v] of Object.entries(parsed)) {
    if (k === key || v === null || v === undefined) continue;
    if (typeof v === 'number' || typeof v === 'boolean') bits.push(`${k}=${v}`);
    else if (typeof v === 'string' && v.trim() !== '') bits.push(`${k}=${oneLine(v, 48)}`);
  }
  return bits.length ? bits.join(' · ') : null;
}

/* ---------------- 结果判定：只看后端 status ---------------- */

export type OutcomeTone = 'ok' | 'warn' | 'error';

export interface ToolOutcome {
  tone: OutcomeTone;
  /** 徽标文案。降级档必须含「异常」，不能让人把失败读成成功。 */
  label: string;
  /** 出参块要不要走异常底色（浅红底 + 深红字）。 */
  bad: boolean;
}

/** 一次工具调用算不算成功 —— 只认后端 `status` 这一档事实来源。
 *
 *  三档：`failed` / `timeout` / `success`（`api/schemas.py:267` 的 Literal 就这三个词）。
 *  曾经这里还有**第四档：嗅出参文本**（`exit_code≠0`、「执行超时」字样），
 *  用来兜「后端把脚本非零退出记成 success」那段谎。2026-09-24 后端修掉了那层谎
 *  （`core/tools/builtin/code_exec.py` 现在对 `returncode != 0` 抛 `SandboxFailed`，
 *  registry 如实记 `failed`），嗅探随之删除 —— 依据是当时库内 27 条 tool_call 事件里
 *  `status=success` 且出参含非零 `exit_code` 的行为 **0**，删它不改变任何历史任务的显示。
 *
 *  留这段注释是为了下次别再长回来：展示层不该替后端判断成败。
 */
export function toolOutcome(status: ToolCall['status']): ToolOutcome {
  if (status === 'failed') return { tone: 'error', label: '失败', bad: true };
  if (status === 'timeout') return { tone: 'warn', label: '执行异常 · 超时', bad: true };
  return { tone: 'ok', label: '成功', bad: false };
}

/** Tooltip 正文：字典的大白话 + 计费口径 + 注册表给的硬参数。 */
export function tooltipLines(name: string, spec?: ToolSpecView): string[] {
  const d = displayOf(name);
  const out: string[] = [];
  if (d) {
    out.push(d.plain, BILLING_NOTE[d.billing]);
  } else if (spec) {
    // 字典没跟上：直接端注册表说明，别空着
    out.push(oneLine(spec.description, 160));
  } else {
    out.push(`未在字典里收录的工具：${name}`);
  }
  if (spec) {
    const bits = [
      `超时 ${spec.timeout > 0 ? `${spec.timeout}s` : '交给工具自己管'}`,
      `失败重试 ${spec.retry} 次`,
      spec.danger_level === 'high' ? '高危：需显式放行' : '常规权限',
    ];
    out.push(`注册表 · ${bits.join(' · ')}`);
  }
  return out;
}
