import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';

/** 只读 JSON 折叠树（工具入参 / 出参用）。
 *
 * 三条硬口径：
 *  1. **解析不出来就原样回落 `<pre>`**，一个字都不改。工具出参经常是半截 JSON、
 *     纯文本或日志片段，宁可平铺也不能编造结构。
 *  2. 默认只展开两层：`execution_results` 这类嵌套数组一展开就是几十屏，
 *     折叠计数（`{3 键}` / `[18 项]`）要看得见，用户才知道下面还有。
 *  3. 不引依赖 —— Monaco / react-json-view 的量级对这块小面板不划算，
 *     折叠 + 类型着色 + 长串截断这三件事手写就够了。
 */

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** 默认展开到第几层（根算第 0 层）。 */
const OPEN_UNTIL = 1;
/** 超过这个长度的字符串先截断，点开才给全文。 */
const STRING_CLAMP = 300;

const PARSE_FAILED = Symbol('parse-failed');

function tryParse(text: string): Json | typeof PARSE_FAILED {
  try {
    return JSON.parse(text) as Json;
  } catch {
    return PARSE_FAILED;
  }
}

function isBranch(value: Json): value is Json[] | Record<string, Json> {
  return typeof value === 'object' && value !== null;
}

function leaf(value: Json): { text: string; cls: string } {
  if (value === null) return { text: 'null', cls: 'jv-null' };
  if (typeof value === 'boolean') return { text: String(value), cls: 'jv-bool' };
  if (typeof value === 'number') return { text: String(value), cls: 'jv-num' };
  return { text: JSON.stringify(value), cls: 'jv-str' };
}

function StringLeaf({ name, value }: { name: string | null; value: Json }) {
  const { text, cls } = leaf(value);
  const [full, setFull] = useState(false);
  const clamp = cls === 'jv-str' && text.length > STRING_CLAMP && !full;

  return (
    <div className="jv-line">
      {name !== null && <span className="jv-key">{name}: </span>}
      <span className={cls}>{clamp ? `${text.slice(0, STRING_CLAMP)}…` : text}</span>
      {cls === 'jv-str' && text.length > STRING_CLAMP && (
        <button
          type="button"
          className="jv-more"
          onClick={() => setFull((v) => !v)}
          aria-expanded={full}
        >
          {full ? '收起' : `展开全文（${(text.length - 2).toLocaleString('zh-CN')} 字符）`}
        </button>
      )}
    </div>
  );
}

function Node({ name, value, depth }: { name: string | null; value: Json; depth: number }): ReactNode {
  if (!isBranch(value)) return <StringLeaf name={name} value={value} />;

  const arr = Array.isArray(value);
  const entries: Array<[string, Json]> = arr
    ? (value as Json[]).map((v, i) => [String(i), v])
    : Object.entries(value as Record<string, Json>);
  const [open, setOpen] = useState(depth <= OPEN_UNTIL);
  const [o, c] = arr ? ['[', ']'] : ['{', '}'];

  return (
    <div className="jv-node">
      <div className="jv-line">
        <button
          type="button"
          className="jv-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? `收起 ${name ?? '根节点'}` : `展开 ${name ?? '根节点'}`}
        >
          <span aria-hidden>{open ? '▾' : '▸'}</span>
        </button>
        {name !== null && <span className="jv-key">{name}: </span>}
        <span className="jv-punc">{o}</span>
        {!open && (
          <>
            <span className="jv-count">
              {entries.length} {arr ? '项' : '键'}
            </span>
            <span className="jv-punc">{c}</span>
          </>
        )}
      </div>
      {open && (
        <>
          <div className="jv-kids">
            {entries.map(([k, v]) => (
              <Node key={k} name={arr ? null : k} value={v} depth={depth + 1} />
            ))}
          </div>
          <div className="jv-line">
            <span className="jv-punc">{c}</span>
          </div>
        </>
      )}
    </div>
  );
}

export interface JsonViewProps {
  /** 已经过边界归一的 JSON 文本（`client.ts` 的 jsonToText 产物）。 */
  text: string;
  /** 空文本时的占位，与周边 `<pre>` 口径一致。 */
  empty?: string;
}

export interface JsonViewProps {
  /** 已经过边界归一的 JSON 文本（`client.ts` 的 jsonToText 产物）。 */
  text: string;
  /** 空文本时的占位，与周边 `<pre>` 口径一致。 */
  empty?: string;
  /** 这次调用没成（超时 / 非零退出 / 失败）：容器换异常底色。
   *  判定不在这里做 —— 由 `toolMeta.ts` 的 `toolOutcome()` 决定后传进来，
   *  组件只负责「已经判定为异常」时的呈现，不自己猜文本。 */
  error?: boolean;
}

export default function JsonView({ text, empty = '—', error = false }: JsonViewProps) {
  const err = error ? ' is-error' : '';
  /* 解析缓存（Q4-06）：这一行过去是裸调用，所以**每次父渲染**都重跑一遍 `JSON.parse`。
     轨迹页那条"一处失败就整屏展开"的路径（StepTimeline 的 defaultOpen）会让最多 500 个
     JsonView 同时挂在树上，而它们共同的父组件每点一次展开就重渲染一次 ⇒ 500 次重解析。
     ⚠️ 必须排在下面那个早退**之前**：Hooks 不能写在条件 return 后面，这条顺序不是风格问题。
     空文本这里显式短路成 PARSE_FAILED，而不是把它喂给 tryParse：`JSON.parse('')` 确实会抛、
     抛出来也是 PARSE_FAILED，行为不差，但那等于靠异常做流程控制 —— 空文本本来就归上面那支
     `empty` 占位管，让 memo 与它的口径一致更省心。 */
  const parsed = useMemo(() => (text ? tryParse(text) : PARSE_FAILED), [text]);
  if (!text) return <pre className={`code${err}`}>{empty}</pre>;

  if (parsed === PARSE_FAILED) {
    // 不是 JSON：原样平铺，不猜结构
    return <pre className={`code${err}`}>{text}</pre>;
  }

  return (
    <div className={`jv${err}`}>
      <Node name={null} value={parsed} depth={0} />
    </div>
  );
}
