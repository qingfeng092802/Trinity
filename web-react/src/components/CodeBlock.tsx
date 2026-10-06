import { useMemo, useState } from 'react';
import { codeSize, tokenizePython } from '../utils/pyTokens';

/** 一整段源码的展示块（code_exec 的入参）。
 *
 * 为什么不用 JsonView：JSON 树会把源码当成一个字符串叶子，`JSON.stringify` 之后
 * `\n` 变回字面量两字符、整段挤成一行 —— 这正是清单 P0 那坨「co"import os, glob\n…」的成因。
 * 这里按**代码**渲染：真实换行、原样缩进、`white-space: pre`（长行横向滚动而不是硬拆行）。
 *
 * 折叠口径按清单 P1：代码块自己**不开纵向滚动条**，高度上限 + 外部「展开全文」按钮
 * 二选一，避免卡片里出现「滚动条套滚动条」。 */

/** 超过这个行数才给「展开全文」；折叠高度写在 CSS 的 `.is-clamped`（约 11 行）。 */
const CLAMP_LINES = 12;

export interface CodeBlockProps {
  /** 真实源码文本（已从 JSON 字符串里解出来的那种，带真换行）。 */
  code: string;
  /** 语言标签，只用于底色块上那行小字，不做分词分支 —— 目前只有 Python。 */
  lang?: string;
}

export default function CodeBlock({ code, lang = 'python' }: CodeBlockProps) {
  const [full, setFull] = useState(false);
  const { lines, chars } = codeSize(code);
  const clampable = lines > CLAMP_LINES;
  /* 分词缓存（Q4-06）：与 JsonView 同一件事 —— 轨迹页一处失败就整屏展开时，最多 500 个
     CodeBlock 同时挂在树上，而它们的共同父组件每点一次展开就重渲染一次，
     于是一段段 Python 被反复重切。`code` 不变 ⇒ 分词结果就不该重算。
     只 memo 这一趟遍历：`full` / `clampable` 那些渲染照旧要走，改的是纯浪费的那一半。 */
  const segments = useMemo(() => tokenizePython(code), [code]);

  return (
    <div className="code-block">
      <pre
        className={`code code-src${full || !clampable ? '' : ' is-clamped'}`}
        data-lang={lang}
        data-lines={lines}
      >
        {segments.map((s, i) =>
          s.cls === 'plain' ? (
            s.text
          ) : (
            <span key={i} className={`py-${s.cls}`}>
              {s.text}
            </span>
          ),
        )}
      </pre>
      {clampable && (
        <button
          type="button"
          className="code-more"
          onClick={() => setFull((v) => !v)}
          aria-expanded={full}
        >
          {full ? '收起' : `展开全文（共 ${lines} 行 · ${chars.toLocaleString('zh-CN')} 字符）`}
        </button>
      )}
    </div>
  );
}
