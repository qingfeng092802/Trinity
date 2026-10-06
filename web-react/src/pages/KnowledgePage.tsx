import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { CSSProperties } from 'react';
import { Button, Popconfirm, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined,
  InboxOutlined,
  RedoOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

import {
  describeFetchError,
  deleteDocument,
  fetchDocuments,
  fetchKnowledgeOverview,
  retryDocument,
  uploadDocument,
} from '../api/client';
import {
  EmptyState,
  ErrorState,
  MetricTile,
  PageHeader,
  ScrollXFrame,
  Skel,
  SurfaceCard,
} from '../components/ui';
import { useRefresh } from '../hooks/useRefresh';
import type { DocumentView, KnownDocumentStatus } from '../types';
import { fmtBytes, fmtDateTime, fmtInt } from '../utils/format';

/** 页面 ④：知识库 —— 上传、看索引进度、删除、重试。
 *
 * 三条口径先钉在这里，它们决定这一页上哪些字是真的：
 *
 *  1. **进度只有两个来源**：处理段读后端 `status`（六状态机，`api/constants.py:62-77`），
 *     传输段读本地 `File.size`。中间没有任何"估计"。`fetch` 拿不到已上传字节，
 *     所以传输段**不画百分比**（方案 §6 避坑 2 + K4 拍板）—— 要真百分比只能换
 *     `XMLHttpRequest.upload.onprogress`，那一刀没拍。
 *  2. **未知状态原样上屏**（避坑 5）：后端加第七个状态时，界面既不许当 `ready`、
 *     也不许当"索引中"、更不许崩。Z 趟往 mock 里塞一个 `verifying` 钉这条。
 *  3. **不补零**：四枚概览读数全部来自 `GET /knowledge/overview`。前端绝不自己数
 *     列表行去填"索引中" —— 同屏两份同数迟早分叉，而分叉那次一定没人报警。
 */

/* ------------------------------------------------------------------ *
 * 状态口径
 * ------------------------------------------------------------------ */

/** 推进四阶段，顺序与后端 `DOC_STAGE_FLOW`（`api/constants.py:77`）一致。
 *  `ready` 不是阶段而是终点：进度条一共四格，走满即"已索引"。 */
const STAGES: Array<{ key: KnownDocumentStatus; label: string }> = [
  { key: 'pending', label: '排队' },
  { key: 'parsing', label: '解析' },
  { key: 'chunking', label: '切分' },
  { key: 'embedding', label: '向量化' },
];

const DOC_LABEL: Record<KnownDocumentStatus, string> = {
  pending: '排队中',
  parsing: '解析中',
  chunking: '切分中',
  embedding: '向量化中',
  ready: '已索引',
  failed: '索引失败',
};

type Tone = 'primary' | 'success' | 'danger' | 'warning';

/** 四档取色。全部复用任务状态徽标那套 token，**不新开色阶**：
 *  「文档到哪一步了」与「任务到哪一步了」是同一个语义，两套色必然互相污染。
 *  `primary` 档取 `--primary-soft-fg` 而不是 `--primary` —— 实心紫压在自己的
 *  浅底上只有 4.2:1 上下，`-soft-fg` 那版才是按"文字要落在软底色上"调的。 */
const TONE_VAR: Record<Tone, { fg: string; soft: string }> = {
  primary: { fg: 'var(--primary-soft-fg)', soft: 'var(--primary-soft)' },
  success: { fg: 'var(--success-fg)', soft: 'var(--success-soft)' },
  danger: { fg: 'var(--danger-fg)', soft: 'var(--danger-soft)' },
  warning: { fg: 'var(--warning-fg)', soft: 'var(--warning-soft)' },
};

/** 上传白名单：**从 `/overview` 的 `supported_formats` 读，页面不再自带一份清单**（R-03）。
 *
 * 之前这里写死过 `.pdf,.md,.txt`，而后端那份在 HEAD 上其实是五种（含 docx/html）——
 * 两份清单漂移就是 R-03 记的那件事：窄了**误拒**（本来能索引的文档被拦在门外，
 * 而页面那句"这一版只收 pdf / md / txt"在 HEAD 上根本不成立），宽了**白传一次**再吃 422。
 * 现在唯一的来源是 `api/constants.py::DOC_SUPPORTED_FORMATS`，经
 * `rag.service.supported_formats()` 同时喂给 ① `/overview` 这个字段 ② 422 的判定
 * ③ 422 那句文案里列的清单 —— 三个消费者同一份，界面说的就是说给后端的那句话。
 *
 * ⚠️ 判的是**形状**，不是"有没有响应"（这个坑 K3 踩过一次，见下面 `maxMb` 那段注释）：
 * 没重启的后端进程压根不发这个字段，写成 `overview.data.supported_formats.join(' / ')`
 * 只会印出"支持 undefined"或半截话。 */
function readFormats(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const list: string[] = [];
  for (const item of raw) {
    // 一项不合规就当整份不可信：半份白名单比没有更危险（它会让人以为其余几样被拒了）。
    if (typeof item !== 'string') return null;
    const name = item.trim().toLowerCase().replace(/^\./, '');
    if (!name) return null;
    list.push(name);
  }
  // 排序是为了让文案与 `accept` 在常量变化前也稳定（后端那份也给 sorted）。
  return list.sort();
}

/** K5：一次最多 5 份，且**串行**（不是并发）。原因写在 `uploadDocument` 注释里：
 *  后端 `file.file.read()` 一次读进内存，索引队列容量只有 20。 */
const MAX_BATCH = 5;

/** 轮询间隔：索引是"毫秒级到十几秒级"，2 秒既跟手又不刷日志。 */
const POLL_MS = 2_000;

interface StatusView {
  label: string;
  tone: Tone;
  /** 是不是"还在动"：决定呼吸点与要不要继续轮询。未知状态**故意**是 false。 */
  live: boolean;
  /** 进度条走到的格数 0..4；`failed` 与未知状态为 -1（不画推进位）。 */
  stage: number;
}

/** 状态字符串 → 界面读数。`DocumentView.status` 的类型是 `string`（理由见 types.ts），
 *  所以这里**必须**有 `default`：编译期帮不了我们，运行时才不给假话。 */
function statusView(status: string): StatusView {
  switch (status) {
    case 'pending':
      return { label: DOC_LABEL.pending, tone: 'primary', live: true, stage: 0 };
    case 'parsing':
      return { label: DOC_LABEL.parsing, tone: 'primary', live: true, stage: 1 };
    case 'chunking':
      return { label: DOC_LABEL.chunking, tone: 'primary', live: true, stage: 2 };
    case 'embedding':
      return { label: DOC_LABEL.embedding, tone: 'primary', live: true, stage: 3 };
    case 'ready':
      return { label: DOC_LABEL.ready, tone: 'success', live: false, stage: STAGES.length };
    case 'failed':
      return { label: DOC_LABEL.failed, tone: 'danger', live: false, stage: -1 };
    default:
      // 未知状态：原样上屏 + 琥珀档。琥珀说的是"这里有件我们没预料到的事"，
      // 它既不是成功也不是进行中 —— 正是这个含义该待的位置。
      return { label: status || '（空状态）', tone: 'warning', live: false, stage: -1 };
  }
}

/** `error_stage` → 第几格。后端给的不止三个阶段名：`queue` / `dedup` / `unknown`
 *  是**根本没进到解析**就失败了（入队失败、受理期去重、后端认不出），
 *  那种时候一格都不该点亮 —— 点了就是在讲"它跑过这一步"。 */
function failStageIndex(errorStage: string | null): number {
  if (!errorStage) return -1;
  return STAGES.findIndex((s) => s.key === errorStage);
}

/* ------------------------------------------------------------------ *
 * 分段进度条
 * ------------------------------------------------------------------ */

/** 处理段进度条：四格，每格对应后端一个真实状态。
 *
 * 为什么不是百分比条：`status` 只有六个离散值，画成连续条就得编一个"解析 37%"，
 * 那是假的。为什么传输段不在这里：那一段唯一的真数是本地 `File.size`，
 * "上传中 · 3.24 MB"已经说满了我们能诚实说的话。
 *
 * `aria-hidden`：读屏听到的说法就在旁边的状态徽标里（`statusView().label`），
 * 这条只是那份文字的图形化；两处都播等于把同一句话念两遍。
 * 探针读的是 `data-stages`（形如 `done,done,active,todo`），不读像素。 */
function StageBar({ doc }: { doc: DocumentView }) {
  const view = statusView(doc.status);
  const failIdx = doc.status === 'failed' ? failStageIndex(doc.error_stage) : -1;
  const cells = STAGES.map((stage, i) => {
    let state: 'done' | 'active' | 'todo' | 'failed' | 'off';
    if (doc.status === 'failed') {
      if (failIdx < 0) state = 'off';
      else if (i < failIdx) state = 'done';
      else if (i === failIdx) state = 'failed';
      else state = 'todo';
    } else if (view.stage < 0) {
      state = 'off';
    } else if (i < view.stage) {
      state = 'done';
    } else if (i === view.stage) {
      state = 'active';
    } else {
      state = 'todo';
    }
    return { key: stage.key, label: stage.label, state };
  });
  return (
    <span
      className="stage-bar"
      aria-hidden
      data-status={doc.status}
      data-stages={cells.map((c) => c.state).join(',')}
      data-fail-stage={failIdx >= 0 ? STAGES[failIdx].key : doc.error_stage || ''}
    >
      {cells.map((c) => (
        <span key={c.key} className={`stage-cell stage-cell--${c.state}`}>
          <span className="stage-cell-fill" />
          <span className="stage-cell-label">{c.label}</span>
        </span>
      ))}
    </span>
  );
}

/** 状态徽标：与 `components/ui.tsx` 的 `StatusBadge` **同一套 DOM 与类名**
 *  （`.status-badge` + `is-live` + `--chip-fg/--chip-soft`），这样"还在动"这个信号
 *  在全站只有一种画法、呼吸也只有一处实现。
 *  没有直接复用那个组件：它吃 `TaskStatus` 并查 `STATUS_META`，语义是"任务到哪一步"，
 *  把文档状态硬塞进那张表就是拿别人的口径说自己的话（`ToolBadge` 的注释讲的正是这件事）。 */
function DocBadge({ view }: { view: StatusView }) {
  const tone = TONE_VAR[view.tone];
  return (
    <span
      className={view.live ? 'status-badge is-live' : 'status-badge'}
      style={{ '--chip-fg': tone.fg, '--chip-soft': tone.soft } as CSSProperties}
    >
      <span className="dot" aria-hidden />
      {view.label}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * 上传队列
 * ------------------------------------------------------------------ */

type QueuePhase = 'waiting' | 'uploading' | 'needs-overwrite' | 'accepted' | 'rejected';

const PHASE_TEXT: Record<QueuePhase, string> = {
  waiting: '排队上传',
  uploading: '上传中',
  'needs-overwrite': '等确认',
  accepted: '已受理',
  rejected: '没传上去',
};

const PHASE_TONE: Record<QueuePhase, Tone> = {
  waiting: 'primary',
  uploading: 'primary',
  'needs-overwrite': 'warning',
  accepted: 'success',
  rejected: 'danger',
};

interface QueueItem {
  uid: string;
  file: File;
  phase: QueuePhase;
  /** 要展示的那一句话：后端原文优先，本地拦下来的才用自己的话。 */
  message: string;
  /** 覆盖重建：用户点过一次确认后才带上，重发同一份文件。 */
  overwrite: boolean;
  /** 429 的自动退避只做一次（方案 §2.3），靠它计数。 */
  attempts: number;
  /** 受理回执里的提示（覆盖重建会回"旧索引已清除"），必须上屏，不能只报"成功"。 */
  warnings: string[];
  /** 受理成功后回填：下面文档表里那一行就是它。删除时靠这个号把这一行一起摘掉。 */
  documentId: string | null;
}

function blankItem(file: File): QueueItem {
  return {
    uid: `q-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    file,
    phase: 'waiting',
    message: '',
    overwrite: false,
    attempts: 0,
    warnings: [],
    documentId: null,
  };
}

function rejectedItem(file: File, message: string): QueueItem {
  return { ...blankItem(file), phase: 'rejected', message };
}

/* ------------------------------------------------------------------ *
 * 页面
 * ------------------------------------------------------------------ */

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const { token: refreshToken } = useRefresh();
  const overview = useQuery({ queryKey: ['knowledge-overview'], queryFn: fetchKnowledgeOverview });
  const docs = useQuery({ queryKey: ['knowledge-documents'], queryFn: fetchDocuments });

  const [queue, setQueue] = useState<QueueItem[]>([]);
  /** 只有一句话要说、但不属于任何一行文件的时候用它（比如一次拖了 9 个文件）。 */
  const [notice, setNotice] = useState('');
  /** 删除/重试这类"行内动作"的失败：贴在表上方，不用 window.alert 打断整页。 */
  const [actionError, setActionError] = useState('');
  const [dragIn, setDragIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  /** 退避定时器：卸载时全清，否则组件没了还有 setTimeout 在写它的 state。 */
  const timers = useRef<number[]>([]);

  const patch = useCallback((uid: string, next: Partial<QueueItem>) => {
    setQueue((prev) => prev.map((it) => (it.uid === uid ? { ...it, ...next } : it)));
  }, []);

  const refetchAll = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] });
    void queryClient.invalidateQueries({ queryKey: ['knowledge-overview'] });
  }, [queryClient]);

  // 顶栏「刷新」→ 重取概览与列表
  useEffect(() => {
    refetchAll();
  }, [refreshToken, refetchAll]);

  useEffect(
    () => () => {
      timers.current.forEach((id) => window.clearTimeout(id));
      timers.current = [];
    },
    [],
  );

  const rows: DocumentView[] = useMemo(() => docs.data?.items ?? [], [docs.data]);

  /* ---- 轮询：只在"有东西还在索引"时开 ----
   *
   * 与方案 §2.3 有一处**刻意的偏离**，理由得写下来：方案写的是"按 document_id 轮询
   * `GET /documents/{id}`"，可这张表本身就要显示每一行的状态 —— 逐 id 发 N 个请求
   * 等于让同一个数字在同一屏上取两次（列表一份、详情一份），两者迟早差一拍。
   * 这里改成一次 `GET /documents` + 一次 `/overview`，行状态与"索引中"计数同源同刻。
   * `GET /documents/{id}` 仍是单文档的权威读法（201 回执里的 `status_url` 指着它），
   * 只是这一页不需要按 id 散开问。
   *
   * 三条纪律照抄 `AppShell.useHealth`：不可见的标签不发（后台不许白打）、
   * 切回前台立刻补一次、终态即停（`anyLive` 一变 false，interval 随依赖被清掉）。
   * 未知状态不算 live ⇒ 后端真加了新状态，这里会**停下来**而不是无限轮询。 */
  const anyLive = useMemo(() => rows.some((r) => statusView(r.status).live), [rows]);
  useEffect(() => {
    if (!anyLive) return undefined;
    const tick = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      refetchAll();
    };
    const id = window.setInterval(tick, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [anyLive, refetchAll]);

  /* ---- 串行上传：一次只让一份在路上 ----
   * 依赖只有 [queue, busy]：取第一个 waiting，跑完回到这里取下一个。 */
  useEffect(() => {
    if (busy) return;
    const item = queue.find((it) => it.phase === 'waiting');
    if (!item) return;
    setBusy(true);
    void (async () => {
      // hold=true 表示"这一轮的结束不等于可以开始下一轮"（429 退避中）。
      // 少了这个闸门，finally 一放 busy，同一个 waiting 行会被立刻重发，
      // 退避就成了零秒 —— 队列满的时候正好把后端再踹一脚。
      let hold = false;
      patch(item.uid, { phase: 'uploading', message: '' });
      try {
        const ack = await uploadDocument(item.file, { overwrite: item.overwrite });
        patch(item.uid, {
          phase: 'accepted',
          documentId: ack.document_id,
          // 这句刻意不提进度也不报字节：进度已经在下面的文档表里了，
          // 同一屏同一份数据出现两处，早晚对不上。
          message: '已进入索引队列 · 进度见下方文档表',
          warnings: ack.warnings,
        });
        refetchAll();
      } catch (err) {
        const e = describeFetchError(err);
        if (e.httpStatus === 409 && e.code === 'duplicate_document') {
          // 同名 ⇒ 问一句要不要覆盖。它必须与"指纹不一致"分开走（避坑 6）：
          // 两个都是 409，合并分支就会把"换模型要重索引"说成"文件重名了"。
          patch(item.uid, { phase: 'needs-overwrite', message: e.message });
        } else if (e.httpStatus === 409 && e.code === 'fingerprint_mismatch') {
          patch(item.uid, {
            phase: 'rejected',
            message: `${e.message}（这是"换了 embedding 模型、整库要重索引"，不是文件重名）`,
          });
        } else if (e.httpStatus === 429) {
          const wait = e.retryAfterSeconds;
          if (wait > 0 && item.attempts === 0) {
            patch(item.uid, {
              phase: 'waiting',
              attempts: item.attempts + 1,
              message: `队列已满 · ${wait} 秒后自动重试一次`,
            });
            const id = window.setTimeout(() => setBusy(false), wait * 1000);
            timers.current.push(id);
            hold = true;
          } else {
            // 后端没给 Retry-After 就**不自己编**一个退避秒数：只把原话贴出来，
            // 什么时候再试由用户决定。
            patch(item.uid, {
              phase: 'rejected',
              message:
                wait > 0
                  ? `${e.message}（已按 ${wait}s 自动重试过一次，仍是队列满）`
                  : `${e.message}（后端未给退避时长，请手动再试）`,
            });
          }
        } else {
          patch(item.uid, { phase: 'rejected', message: e.message });
        }
      } finally {
        if (!hold) setBusy(false);
      }
    })();
  }, [queue, busy, patch, refetchAll]);

  /* ---- 选文件 / 拖拽 ---- */
  /* K3 那个字段**可能压根不在**：后端进程没重启时，`/overview` 回的还是加字段之前的形状。
     所以判的是"有没有一个有限的数"，不是"有没有响应"——写成
     `overview.data ? overview.data.max_file_mb * 1024 * 1024 : null` 会得到
     `undefined * 1024 * 1024 = NaN`：界面印出"单文件 ≤ — MB"这种半截话，
     而本地预拦那条恒不触发（任何数与 NaN 比较都是 false）⇒ 一个都不拦，还不说为什么。 */
  const maxMbRaw = overview.data?.max_file_mb;
  const maxMb = typeof maxMbRaw === 'number' && Number.isFinite(maxMbRaw) ? maxMbRaw : null;
  const maxBytes = maxMb === null ? null : maxMb * 1024 * 1024;

  /* R-03：白名单同理，**读不到就一份都不拦、`accept` 也不设**（与上面那条同一纪律）。
     这里刻意**不**退回"页面自己那份三样" —— 退回就等于把两份清单又养回来了，
     而且窄/宽两侧都可能错（后端五种时误拒、后端两种时白传）。所以那一档的表现是
     "选择器不限制 + 文案说清没读到 + 后端的 422 原文上屏"。 */
  const formats = useMemo(
    () => readFormats(overview.data?.supported_formats),
    // 键在**响应那一份数组**上：不 memo 的话每次渲染都是一个新数组，
    // `enqueue` 的依赖跟着抖，队列那一块 memo 子树全跟着重建（与 line 326 同一写法）。
    [overview.data],
  );
  const acceptAttr = formats === null ? undefined : formats.map((f) => `.${f}`).join(',');
  const formatHint = formats === null ? null : formats.join(' / ');
  /* 两句"读不到"不许在同一行里各说一遍：老进程同时缺这两个字段（K3 与 R-03 都是后加的），
     照原本的组合会印成"格式白名单…交给后端判 · 单文件上限暂时读不到，交给后端判 · …"，
     同一句话里出现两次"交给后端判"是噪声不是信息 ⇒ 两个都缺时合成一句。 */
  const bothMissing = formats === null && maxMb === null;
  const uploadScope =
    formatHint !== null
      ? `支持 ${formatHint}`
      : bothMissing
        ? '格式与大小上限这一趟都没读到'
        : '格式白名单这一趟没读到，交给后端判';
  const uploadCap =
    maxMb !== null
      ? `单文件 ≤ ${fmtInt(maxMb)} MB`
      : formatHint !== null
        ? '单文件上限暂时读不到，交给后端判'
        : '';
  const uploadLimits = [uploadScope, uploadCap, `一次最多 ${MAX_BATCH} 份（串行）`]
    .filter(Boolean)
    .join(' · ');

  const enqueue = useCallback(
    (files: FileList | File[]) => {
      const all = Array.from(files);
      if (!all.length) return;
      const picked: QueueItem[] = [];
      for (const file of all) {
        if (picked.length >= MAX_BATCH) {
          // 不静默丢弃：说清丢了几个、为什么。批量上限是 K5 拍的，不是浏览器给的。
          setNotice(`一次最多 ${MAX_BATCH} 份，后面 ${all.length - picked.length} 份没加入队列`);
          break;
        }
        const ext = (file.name.split('.').pop() ?? '').toLowerCase();
        /* `formats === null` ⇒ **不本地拦**（这一趟没读到白名单，交给后端说 422）。
           与体积那一档同一条纪律：拿一份猜出来的清单去拦人，窄了误拒、宽了让人白传一次。 */
        if (formats !== null && !formats.includes(ext)) {
          picked.push(
          rejectedItem(
              file,
              `不支持的格式 .${ext || '（无扩展名）'}：后端这一趟给的白名单是 ${formatHint}`,
            ),
          );
          continue;
        }
        if (file.size === 0) {
          picked.push(rejectedItem(file, '空文件（0 字节），后端会拒，这里先挡住'));
          continue;
        }
        // 上限来自后端 overview（K3）。读不到就**不做本地预拦**，让后端说 422 ——
        // 拿一个猜出来的数字去拦人，比不拦更糟。
        if (maxBytes !== null && file.size > maxBytes) {
          picked.push(
            rejectedItem(
              file,
              `${fmtBytes(file.size)} 超过单文件上限 ${maxMb} MB`,
            ),
          );
          continue;
        }
        picked.push(blankItem(file));
      }
      if (picked.length) setQueue((prev) => [...prev, ...picked]);
    },
    [maxBytes, maxMb, formats, formatHint],
  );

  const openPicker = () => inputRef.current?.click();

  const deleteOne = useCallback(
    async (documentId: string) => {
      setDeleting(documentId);
      setActionError('');
      try {
        await deleteDocument(documentId);
        // 队列里那行"已受理"现在指的是一个已经不存在的文档 —— 一起摘掉，别留假话。
        setQueue((prev) => prev.filter((it) => it.documentId !== documentId));
        refetchAll();
      } catch (err) {
        const e = describeFetchError(err);
        // 404 = 已经被删了（两个标签页同时开着会撞到）。这不算失败，刷新就对上了。
        if (e.httpStatus !== 404) setActionError(`删除失败：${e.message}`);
        refetchAll();
      } finally {
        setDeleting(null);
      }
    },
    [refetchAll],
  );

  const retryOne = useCallback(
    async (documentId: string) => {
      setRetrying(documentId);
      setActionError('');
      try {
        await retryDocument(documentId);
        refetchAll();
      } catch (err) {
        setActionError(`重试没成功：${describeFetchError(err).message}`);
      } finally {
        setRetrying(null);
      }
    },
    [refetchAll],
  );

  const columns = useMemo<ColumnsType<DocumentView>>(
    () => [
      {
        title: '文件名',
        dataIndex: 'filename',
        key: 'filename',
        width: 240,
        fixed: 'left',
        render: (name: string) => (
          <span className="mono" title={name}>
            {name}
          </span>
        ),
      },
      { title: '格式', dataIndex: 'format', key: 'format', width: 72 },
      {
        title: '大小',
        dataIndex: 'size_bytes',
        key: 'size_bytes',
        width: 96,
        align: 'right',
        render: (v: number) => fmtBytes(v),
      },
      {
        title: '状态 / 进度',
        key: 'status',
        width: 268,
        render: (_v, doc) => {
          const view = statusView(doc.status);
          return (
            <div className="doc-status">
              <DocBadge view={view} />
              <StageBar doc={doc} />
              {doc.status === 'failed' && (
                <p className="doc-error">
                  {doc.error_stage ? `${doc.error_stage} · ` : ''}
                  {doc.error_message || '后端没给失败原因'}
                </p>
              )}
            </div>
          );
        },
      },
      {
        title: 'chunks',
        dataIndex: 'chunk_count',
        key: 'chunk_count',
        width: 82,
        align: 'right',
        render: (v: number) => fmtInt(v),
      },
      {
        title: 'tokens',
        dataIndex: 'token_count',
        key: 'token_count',
        width: 92,
        align: 'right',
        render: (v: number) => fmtInt(v),
      },
      {
        title: '索引完成',
        dataIndex: 'indexed_at',
        key: 'indexed_at',
        width: 116,
        render: (v: string | null) => fmtDateTime(v),
      },
      {
        title: '操作',
        key: 'actions',
        width: 158,
        render: (_v, doc) => (
          <span className="row-actions">
            {/* 重试只在 failed 行出现：对别的状态后端会 422。"先给按钮、再让用户吃了错"
                等于把该在这里做的判断推给服务端。 */}
            {doc.status === 'failed' && (
              <Button
                size="small"
                icon={<RedoOutlined />}
                loading={retrying === doc.document_id}
                onClick={() => void retryOne(doc.document_id)}
              >
                重试
              </Button>
            )}
            <Popconfirm
              title="删除这份文档？"
              description="chunk、向量与磁盘上的原件一起清掉，不可恢复。"
              okText="仍要删除"
              cancelText="留着"
              placement="bottomRight"
              onConfirm={() => void deleteOne(doc.document_id)}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={deleting === doc.document_id}
              >
                删除
              </Button>
            </Popconfirm>
          </span>
        ),
      },
    ],
    [deleting, retrying, deleteOne, retryOne],
  );

  const ov = overview.data;
  const listErr = docs.error ? describeFetchError(docs.error) : null;
  // 503 是整页级的：这一刻列表、队列、概览都没有可信来源。
  const ragDown = listErr !== null && (listErr.httpStatus === 503 || listErr.code === 'rag_unavailable');

  if (ragDown && listErr) {
    return (
      <>
        <PageHeader title="知识库" desc="上传文档、看索引进度、删除与重试。" />
        {/* 这里不铺空表：把"服务不可用"演成"库里没东西"是这一轮报告里数出来的老毛病。
            `kb-rag-down` 这枚类是给探针的**落点**：整页降级与"只有概览读不到"那张卡共用
            `.error-state`，Z 趟第一版拿 `.app-content .error-state` 当"整页"的判据，
            结果概览先失败那一帧就把等待骗过去了（症状：报的标题是"概览拉取失败"）。 */}
        <SurfaceCard className="kb-rag-down" title="知识库不可用" icon={<InboxOutlined />}>
          <ErrorState
            title="服务端读不到知识库"
            message={listErr.message}
            httpStatus={listErr.httpStatus}
            code={listErr.code}
            requestId={listErr.requestId}
            note="常见原因是 rag 依赖没装好或索引服务初始化失败。修好后按刷新即可，不需要重传文档。"
            onRetry={refetchAll}
          />
        </SurfaceCard>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="知识库"
        desc="上传 → 解析 → 切分 → 向量化 → 可检索。进度只读后端状态机，页面不猜也不补零。"
        actions={
          <>
            <Button icon={<ReloadOutlined />} onClick={refetchAll} loading={docs.isFetching}>
              刷新
            </Button>
            <Button type="primary" icon={<InboxOutlined />} onClick={openPicker}>
              上传文档
            </Button>
          </>
        }
      />

      {/* ------------------------- 概览 ------------------------- */}
      {/* 读不到就整条换成一张通栏的错误卡：让它当 `.metric-grid` 的第一格，
          会被压成 158px 宽的一条，那句"为什么读不到"正好被截掉。 */}
      {overview.error ? (
        <SurfaceCard className="kb-overview-error" title="概览读不到" bodyPadding="tight">
          {(() => {
            const e = describeFetchError(overview.error);
            return (
              <ErrorState
                title="概览拉取失败"
                message={e.message}
                httpStatus={e.httpStatus}
                code={e.code}
                requestId={e.requestId}
                /* 这句 note 以前是写死的"它没坏"。可这一刻**列表还没回话** ——
                   替一个还不知道结果的东西担保，就是在骗人。Z 趟的 503 竞态正是这么抓出来的：
                   概览先失败、列表隔一拍也失败，中间那一帧整页还没降级，而这句话已经在断言
                   "文档表没事"。现在按列表自己的状态给三种说法，任何一种都不超出已知范围。 */
                note={
                  docs.isPending
                    ? '这一条只说四枚读数：文档表那一路是独立取的，此刻还没回话。'
                    : docs.error
                      ? '文档表那一路也没回话 —— 两路都读不到时整页会换成一条说明。'
                      : '下面的文档表是独立取的，它这一趟回来了：只有四枚读数暂时读不到。'
                }
                onRetry={() => void overview.refetch()}
              />
            );
          })()}
        </SurfaceCard>
      ) : (
        <div className="metric-grid">
          {overview.isPending && <Skel w="100%" h={78} r={12} />}
          {ov && (
            <>
            <MetricTile
              label="文档数"
              value={fmtInt(ov.document_count)}
              hint={`${fmtInt(ov.ready_count)} 份已索引 · ${fmtInt(ov.failed_count)} 份失败`}
              title="documents 表里的全部文档：含排队中与索引中的，不只算能检索的那部分，所以后半句单独给。"
            />
            <MetricTile
              label="chunk 数"
              value={fmtInt(ov.chunk_count)}
              hint="全库切分片段总数"
              title="所有文档切出来的片段数之和。覆盖重建会按新文档重算，旧的那批一起清掉。"
            />
            <MetricTile
              label="token 数"
              value={fmtInt(ov.token_count)}
              hint="切片段落的估算 token"
              title="按切分后的文本估算的 token 之和，不是模型实际消耗的 token —— 检索与生成两本的计法不同，别拿它去对账单。"
            />
            <MetricTile
              label="索引中"
              value={fmtInt(ov.indexing_count)}
              tone={ov.indexing_count > 0 ? 'primary' : 'default'}
              empty={ov.indexing_count === 0}
              hint="非终态文档数 · 随轮询自己变小"
              title="后端按 status ∈ {排队中, 解析中, 切分中, 向量化中} 数的结果。前端不自己数列表行（两处口径迟早分叉），后端我们不认识的状态也不会计进来。"
            />
            </>
          )}
        </div>
      )}

      {/* ------------------------- 上传区 ------------------------- */}
      <SurfaceCard
        title="上传文档"
        icon={<InboxOutlined />}
        sub={uploadLimits}
        extra={
          queue.length > 0 && !busy ? (
            <Button size="small" onClick={() => setQueue([])}>
              清空列表
            </Button>
          ) : undefined
        }
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={acceptAttr}
          /* `acceptAttr` 是 undefined 的时候**这个属性干脆不出现** —— 那一档是
             "这一趟没读到后端的白名单"（老进程）。此时不限制选择器、也不本地拦，
             让后端的 422 原文上屏。写成 `accept=""` 是另一个意思（空串等于不收任何类型），
             那才是真把用户挡在门外。 */
          /* 用 .sr-only 而不是 display:none：前者是"1px 且移出可视区"，控件仍在
             （Z 趟用 setInputFiles 驱动它，display:none 的元素会被 actionability 判成
             不可见）；后者直接把节点从渲染树里摘掉。对用户仍然看不见，键盘入口在
             上面那个 role="button" 的拖拽区。 */
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            if (e.target.files) enqueue(e.target.files);
            // 清空 value：不清的话，同一份文件选第二次不会触发 change，
            // "再试一次"点了就没反应。
            e.target.value = '';
          }}
        />
        <div
          className={dragIn ? 'up-drop is-drag' : 'up-drop'}
          role="button"
          tabIndex={0}
          aria-label="拖拽文档到这里，或按回车键选择文件上传"
          onClick={openPicker}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              openPicker();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragIn(true);
          }}
          onDragLeave={() => setDragIn(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragIn(false);
            if (e.dataTransfer?.files) enqueue(e.dataTransfer.files);
          }}
        >
          <InboxOutlined className="up-drop-icon" aria-hidden />
          <span className="up-drop-main">把文件拖进来，或点这里选文件</span>
          <span className="up-drop-sub">
            传上去不等于能检索 —— 得等它跑完向量化。下面这张队列表只管"送到服务端没有"，
            检索什么时候能用要看文档表里的状态。
          </span>
        </div>

        {notice && (
          <p className="up-notice" role="status">
            {notice}
          </p>
        )}

        {queue.length > 0 && (
          <ul className="up-list" aria-label="上传队列">
            {queue.map((it) => (
              <li key={it.uid} className="up-row" data-phase={it.phase}>
                <span className="up-name mono" title={it.file.name}>
                  {it.file.name}
                </span>
                <span className="up-size tabular">{fmtBytes(it.file.size)}</span>
                <span className="up-badge">
                  <DocBadge view={{ label: PHASE_TEXT[it.phase], tone: PHASE_TONE[it.phase], live: it.phase === 'uploading', stage: -1 }} />
                </span>
                <span className="up-msg">
                  {it.message}
                  {it.warnings.length > 0 && <span className="up-warn"> · {it.warnings.join(' · ')}</span>}
                </span>
                <span className="row-actions">
                  {it.phase === 'needs-overwrite' && (
                    <>
                      {/* 这一步**只有一层确认**：上面那行已经把后端的"同名文档已存在"
                          原样说了一遍，这里再套一层 Popconfirm 就成了"问两遍同一件事"。
                          按钮名直接写清后果（覆盖重建 = 旧索引先清掉）。 */}
                      <Button
                        size="small"
                        danger
                        onClick={() => patch(it.uid, { phase: 'waiting', overwrite: true })}
                      >
                        覆盖重建
                      </Button>
                      <Button
                        size="small"
                        onClick={() => setQueue((p) => p.filter((x) => x.uid !== it.uid))}
                      >
                        放弃
                      </Button>
                    </>
                  )}
                  {it.phase === 'rejected' && (
                    <Button
                      size="small"
                      icon={<RedoOutlined />}
                      onClick={() => patch(it.uid, { phase: 'waiting', message: '', attempts: 0 })}
                    >
                      再试一次
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SurfaceCard>

      {/* ------------------------- 文档表 ------------------------- */}
      <SurfaceCard
        title="文档"
        sub={`按创建时间倒序 · ${anyLive ? '有文档在索引，每 2 秒跟一次' : '没有文档在索引，暂不轮询'}`}
        bodyPadding="flush"
      >
        {actionError && (
          <div className="kb-action-error" role="alert">
            {actionError}
            <button type="button" className="kb-action-error-close" onClick={() => setActionError('')}>
              知道了
            </button>
          </div>
        )}
        {docs.isPending && (
          <div className="kb-pad">
            <Skel w="100%" h={120} r={10} />
          </div>
        )}
        {docs.error && !ragDown && (
          <div className="kb-pad">
            {(() => {
              const e = describeFetchError(docs.error);
              return (
                <ErrorState
                  title="文档列表读不到"
                  message={e.message}
                  httpStatus={e.httpStatus}
                  code={e.code}
                  requestId={e.requestId}
                  note="这不是「库里没有文档」—— 是这一次没读回来。上面的上传队列不依赖它，可以照常用。"
                  onRetry={() => void docs.refetch()}
                />
              );
            })()}
          </div>
        )}
        {!docs.isPending && !docs.error && rows.length === 0 && (
          <div className="kb-pad">
            <EmptyState
              icon={<InboxOutlined />}
              title="还没有文档"
              desc="传一份制度文档或一段说明进来，跑完向量化就能在检索里命中它。"
              bullets={[
                `${uploadScope}${maxMb === null ? '' : ` · 单文件 ≤ ${fmtInt(maxMb)} MB`}`,
                '解析 → 切分 → 向量化全程在服务器后台跑，可以关掉这一页',
                '删除是物理删：chunk、向量与磁盘原件一起清，不可恢复',
              ]}
              actions={
                <Button type="primary" icon={<InboxOutlined />} onClick={openPicker}>
                  上传第一份
                </Button>
              }
            />
          </div>
        )}
        {rows.length > 0 && (
          <ScrollXFrame label="文档表：文件名 / 格式 / 大小 / 状态与进度 / chunks / tokens / 索引完成 / 操作，共 8 列，可横向滚动">
            <Table<DocumentView>
              columns={columns}
              dataSource={rows}
              rowKey="document_id"
              size="small"
              pagination={false}
              scroll={{ x: 1124 }}
            />
          </ScrollXFrame>
        )}
      </SurfaceCard>
    </>
  );
}
