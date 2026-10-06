import { lazy, Suspense, useMemo, useRef, useState } from 'react';

import { Checkbox, InputNumber, Select, Tooltip } from 'antd';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';

import { withPaneBoundary } from './paneBoundary';
import { useModelOverrideReset, useModelRegistry } from '../hooks/useModels';
import {
  defaultOf,
  fieldOf,
  limitOf,
  presetsOf,
  readingOf,
  unenforcedFields,
  unrecognizedOf,
  unsupportedFields,
  useAgentOptions,
} from '../hooks/useAgentOptions';
import { useRunConfig, formatFieldValue } from '../hooks/useRunConfig';
import { useToolSpecs } from '../hooks/useToolSpecs';
import type { AgentFieldSpec, AgentNumericLimit } from '../types';

/** 「模型设置」那份面板（齿轮用的就是它）在这里**内嵌** —— 同一个组件、同一份查询缓存，
 *  不是抄第二份 UI。也是 lazy：没点开过「模型」这一项，就不该付 AutoComplete 与
 *  密码框那半份代码（``tools/uicheck/bundle.cjs`` 量入口 gzip 时这笔不该出现）。 */
const ModelSettingsPanel = lazy(() => import('./ModelSettings'));

/** 数值行分两组（2026-09-27 从"页签"改成"左侧导航 + 右侧内容"，分组本身一个没动）。
 *
 * ⚠️ 这张表里**只有键名与它住在哪一组**。名字、单位、界、生效条件、默认值
 * 全部来自 ``GET /config/agent-options`` —— 这一屏要拆掉的东西就是"前端自己有一张字段表"，
 * 把 label 与后缀抄在这里等于把那张表搬了个家（R-03 那条先例的核对方式正是 grep 字面量）。
 *
 * 漏一个键的后果是**那一行没有控件**（``NumericRow`` 只渲染这里列出的键），
 * 不是错数 —— 所以由 ``unrecognizedOf().unrowedFields`` 在「高级」里点名，不让它静默。
 * ``review_threshold`` 就是那一轮补进来的：后端 ``fields`` 早就声明 accepted+enforced，
 * 前端却没有行，"能配"这件事只在后端成立。 */
const BASIC_ROWS = ['max_iterations', 'max_cost_cny', 'timeout_s'] as const;
const ADVANCED_ROWS = ['review_threshold', 'rag_top_k'] as const;
const ALL_ROW_KEYS: readonly string[] = [...BASIC_ROWS, ...ADVANCED_ROWS];

type NumericRowKey = (typeof BASIC_ROWS)[number] | (typeof ADVANCED_ROWS)[number];

/** 左侧导航那三项。**顺序与文案就是屏幕上那三份**，不读响应 ——
 *  它们是界面结构，不是配置值（跟"默认值必须来自后端"那条纪律不冲突）。 */
const NAV = [
  { key: 'basic', label: '基础' },
  { key: 'model', label: '模型' },
  { key: 'advanced', label: '高级' },
] as const;

type PaneKey = (typeof NAV)[number]['key'];

/** 小数位从**后端给的步长**推，不是按键名硬编码"钱那栏两位小数"：
 *  哪天 ``max_cost_cny`` 的 step 变成 0.5，或者新加一个 step 0.1 的键，
 *  这里都不用改；反过来按键名写就会把 0.35 静默夹成 0。 */
function decimalsOf(step: number | undefined): number {
  const text = String(step ?? 1);
  const dot = text.indexOf('.');
  return dot < 0 ? 0 : text.length - dot - 1;
}

/** 一行 = 左边「标签 + 描述」、右边控件（右对齐）。
 *
 * ⚠️ 类名一律沿用改造前的那批（``rcp-row`` / ``rcp-label`` / ``rcp-default`` / ``rcp-help`` /
 *  ``rcp-warn`` / ``rcp-input`` / ``data-field``）：**DOM 里有的东西只有位置变了**。
 *  换一套 ``sc-*`` 类名会让 AD 那 72 条的读点集体失效，而"判据跟着实现改名"
 *  正是最容易把"其实没验了"混进绿灯里的动作。新类名只给新结构（导航 / 卡片 / 分组标题）。 */
function NumericRow({ rowKey }: { rowKey: NumericRowKey }) {
  const options = useAgentOptions();
  const { draft, setNumeric } = useRunConfig();
  const limit: AgentNumericLimit | null = limitOf(options, rowKey);
  const field = fieldOf(options, rowKey);
  const reading = readingOf(options, rowKey);
  const rawDefault = defaultOf(options, rowKey);
  const fallback = typeof rawDefault === 'number' ? rawDefault : null;
  const shown = draft[rowKey] ?? fallback;
  const usingDefault = draft[rowKey] === undefined;

  /* 两个条件都必须成立才给控件（方案 P-1 / 契约要点 2）：
     · 后端给了**界**（``limits``）—— 没有界就意味着前端填什么都是"发明"，不许凑一个 1..10；
     · 后端**声明收这个键**（``fields`` 里 accepted=true）—— 只凭"有界"就渲染，
       等于给一个后端不吃的字段做了个能填、会发、什么都不发生的输入框。
     ⚠️ 少一行的后果是看得见的"这项配不了"，而多一行的后果是配了不生效。两害里选前者。 */
  if (!limit || field?.accepted !== true) return null;

  const label = reading?.label ?? rowKey;

  return (
    <div className="rcp-row" data-field={rowKey}>
      <div className="rcp-row-head">
        <span className="rcp-label">{label}</span>
        {usingDefault && fallback !== null ? (
          <span className="rcp-default">后端默认 {formatFieldValue(fallback, reading)}</span>
        ) : null}
      </div>
      <InputNumber
        size="small"
        className={`rcp-input${usingDefault ? ' is-default' : ''}`}
        min={limit.min}
        max={limit.max}
        step={limit.step ?? 1}
        precision={decimalsOf(limit.step)}
        value={shown ?? undefined}
        addonAfter={reading?.unit ?? undefined}
        aria-label={label}
        onChange={(next) => {
          // 清空 = 撤回这条意见（不是 0、不是默认值）—— 见 useRunConfig 的 setNumeric
          setNumeric(rowKey, next === null ? undefined : Number(next));
        }}
      />
      {/* 生效条件必须是**看得见的字**，不能塞进 tooltip：
          "预算/超时是软上限"这件事一旦只在悬停里说，键盘用户与截屏里的人
          读到的就是一个承诺到点就掐的输入框（方案 P-4）。 */}
      {field.help ? <p className="rcp-help">{field.help}</p> : null}
      {/* accepted=true 但 enforced=false：值收得下、发得出，**但没有执行机制**。
          这一档比"不支持"更危险，因为界面上一切正常，只有账单不正常。单独说一句话。 */}
      {field.enforced === false ? (
        <p className="rcp-warn">后端会收下这个值，但当前没有执行机制 —— 它不会改变运行行为。</p>
      ) : null}
    </div>
  );
}

function ToolRows() {
  const options = useAgentOptions();
  const { disabledTools, setToolEnabled } = useRunConfig();
  const specs = useToolSpecs();
  const names = useMemo(() => [...specs.keys()], [specs]);

  if (!names.length) {
    return (
      <p className="rcp-empty">
        这一趟没读到工具清单（GET /tools），所以不给勾选框 ——
        拿一份前端抄来的名单顶上，就是第二个清单。
      </p>
    );
  }
  const ragTool = options?.tools?.rag_tool ?? null;
  return (
    <div className="rcp-tools">
      {/* 这句话原来在讲"发出去的是什么名单"（实现细节），现在只讲用户做得到的动作。
          白名单怎么算的（全量减掉未勾选项、清单来自 ``GET /tools``）是 ``buildRunConfigBody``
          的职责，那边有 AD-16/22/28 三条请求体判据钉着 —— 界面不需要再复述一遍机制。 */}
      <p className="rcp-help">默认启用全部工具。取消勾选表示本次任务禁用该工具。</p>
      {names.map((name) => {
        const spec = specs.get(name);
        const on = !disabledTools.includes(name);
        return (
          <label className="rcp-tool" key={name}>
            <Checkbox
              checked={on}
              onChange={(e) => setToolEnabled(name, e.target.checked)}
              aria-label={`启用工具 ${name}`}
            />
            <span className="rcp-tool-name">
              {name}
              {name === ragTool ? <span className="rcp-tool-tag">RAG 开关管的就是这条</span> : null}
            </span>
            {spec?.danger_level === 'high' ? (
              /* 「沙箱 / Python / 超时上限」这些**不重写一遍** —— 它们来自后端的
                 ``description``（``GET /tools``）。这一屏定的口径是"能说的原话只有一份"：
                 这里自己写"执行 Python 代码"，哪天后端把上限从 30 秒改成 60 秒，
                 浮层就会继续说旧的实现。前端只补**后端没说**的那两件：
                 默认要人工确认、以及 Prompt 注入这条风险提醒。
                 分行而不是拼接字符串：直接拼会得到"…安装依赖高危工具：…"这种糊在一起的话。 */
              <Tooltip
                title={
                  <span>
                    高危工具：默认需要人工确认（HITL）才执行，注意 Prompt 注入风险。
                    {spec.description ? (
                      <>
                        <br />
                        {spec.description}
                      </>
                    ) : null}
                  </span>
                }
              >
                <span className="rcp-tool-danger">高危</span>
              </Tooltip>
            ) : null}
          </label>
        );
      })}
    </div>
  );
}

/** 「后端暂不支持」那一栏：``accepted=false`` 的键**不给控件**，只列 key + label + help。
 *
 * 为什么 help 在这里不能省（契约要点 1）：这一栏的键上面**没有行**，
 * 少了 help 就只剩"不行"两个字没有原因。与上面「会收下但没执行机制」那栏**故意不同** ——
 * 那一栏的键上面一定有一行、help 已经摆在正文里，再抄一遍就是同屏两份同样的话。 */
function UnsupportedBlock({
  title,
  items,
  withHelp,
}: {
  title: string;
  items: AgentFieldSpec[];
  withHelp: boolean;
}) {
  if (!items.length) return null;
  return (
    <div className={withHelp ? 'rcp-unsupported' : 'rcp-unenforced'}>
      <p className="rcp-unsupported-title">{title}</p>
      {items.map((f) => (
        <p className="rcp-unsupported-item" key={f.key}>
          <span className="rcp-unsupported-head">
            <span className="rcp-unsupported-name">{f.label}</span>
            <code className="rcp-unsupported-key">{f.key}</code>
          </span>
          {withHelp && f.help ? <span className="rcp-unsupported-help">{f.help}</span> : null}
        </p>
      ))}
    </div>
  );
}

/** 「设置」中心：左侧三项导航 + 右侧一份白卡片 + 底部一条固定操作栏。
 *
 * 五条硬规矩（都各有判据，见 tools/uicheck/running.cjs 的 AD 趟）：
 * 1. 默认值、边界、预设、单位、字段名、工具清单**全部来自响应** —— 拉不到就整块降级，
 *    且请求体里只发任务文本；
 * 2. 后端 ``accepted=false`` 的键不给控件，只在「后端暂不支持」里列出 **key + label + help**；
 * 3. ``accepted=true`` 而 ``enforced=false`` 的键**要单独警告** ——
 *    这一档最危险：填得进去、发得出去、界面一切正常，只有账单不正常；
 * 4. 后端多出来的未知顶层键 / 不认识的 ``kind`` / "有界但没声明收不收"的键 /
 *    "声明能配但界面没有行"的数值键，原样列在「后端还给了这些」里 ——
 *    静默隐藏等于让"后端已经支持"永远看不见；
 * 5. **改的是容器，不是内容**：这一轮从水平页签换成左侧导航，一个控件、一句话都没新增，
 *    「填入示例」是**搬走**（搬到任务输入框正下方），不是删掉。
 *
 * 三处结构决定，都写在代码里而不是留给下一位猜：
 * · 页签**挂载过就留着**（不活跃的加 ``hidden``）—— 与原来 AntD Tabs 的行为一致。
 *   改成"只渲染当前页"会让 AE-12c 那条"靠 invalidate 换读数、不靠 remount"的判据
 *   失去可证伪性（每次切换都重挂载 ⇒ 它想红也红不出来）。
 * · 不活跃页用 ``hidden`` 而不是 ``display:none`` + 留在 Tab 序里：
 *   屏外还能 Tab 到是 EV-07 在这台机器上翻过车的形状。
 * · 降级态（读不到 ``agent-options``）**不给导航**：三项里两项的内容确实还在
 *   （``/models``、``/tools`` 是另外两个端点），但"基础"这一项是空的 ——
 *   给一个点开什么都没有的导航项，比只给一句实话更坏。 */
export default function RunConfigPanel() {
  const options = useAgentOptions();
  const { presetId, applyPreset, draft, disabledTools, reset } = useRunConfig();
  const presets = presetsOf(options);
  const unsupported = unsupportedFields(options);
  const unenforced = unenforcedFields(options);
  const unknown = unrecognizedOf(options, ALL_ROW_KEYS);
  const [pane, setPane] = useState<PaneKey>('basic');
  /** 挂载过的页签：初值就是默认那一项，之后每次切换把新访问的并进来。 */
  const [mounted, setMounted] = useState<ReadonlySet<PaneKey>>(() => new Set<PaneKey>(['basic']));
  const navRefs = useRef<(HTMLButtonElement | null)[]>([]);

  /** 内嵌那份模型面板里"两个档位 / Key 有没有改过"（由它自己报上来，见 ModelSettings）。
   *  为什么需要它：那两个下拉框的状态住在 ``ModelSettings`` 里面，而底栏那枚小圆点
   *  住在这一层 —— 不传这道信号，改了档位而小圆点不动是必然的。 */
  const [modelDirty, setModelDirty] = useState(false);
  /** 「恢复默认配置」点一次 +1，往下传给模型面板当"清回出厂态"的信号。 */
  const [restoreSignal, setRestoreSignal] = useState(0);

  /* 底部那栏**两份分支共用同一个元素**（降级态也要有）：草稿住在 Context 里，
     它不会因为这一趟读不到 options 就清空 —— 只在正常分支渲染读数的话，
     "配置加载失败，只发任务文本"那句会在"先读到、后来刷新失败"的那一刻变成假话，
     而用户手里连撤回的地方都没有。写成一份而不是两处各摆一遍，是同一屏不许有两份的口径。

     2026-09-29 定形：**左一颗「恢复默认配置」（文字链）+ 右一枚 dirty 小圆点**，
     其余全撤。三条理由，各对着一个"看起来正常但会骗人"的形状：
     · **没有「应用」**：改动是即时写进 RunConfigProvider 的，请求体在点「提交任务」
       那一刻从同一份状态算出来（AD-04/05 钉的就是"面板改了、读数跟着变"）。
       一颗按下去不提交任何东西的按钮，正是本仓库删过的那类控件。
     · **两颗合成一颗**：原来的「回落到 .env」（撤进程级档位）与「撤回全部修改」
       （清本次草稿）做的是**一件事的两半** —— 用户心里的动作只有一个"都别改了"，
       摆两颗还逼他去分辨哪半是哪半；而分辨错了的代价是"以为恢复了其实没有"。
     · **读数改成一枚点**：那句「已改 N 项 / 没有改动」说的就是 dirty 这一个比特，
       占的却是一整行会折行的中文。点带 tooltip，两态各一句完整的话。 */
  const changedCount =
    Object.values(draft).filter((v) => v !== undefined).length + disabledTools.length;
  /** 这一屏有没有"改了还没提交"的东西：本次草稿 + 内嵌模型面板那两处。 */
  const dirty = changedCount > 0 || modelDirty;

  const registry = useModelRegistry();
  const revert = useModelOverrideReset();

  /** 有没有"默认值以外的东西"可恢复：草稿、工具禁用、进程级档位覆盖，任一都算。 */
  const hasOverride = registry?.override?.source === 'override';
  const restoreDisabled = !dirty && !hasOverride;

  const restoreDefaults = () => {
    /* 两半都做，且**先清本地、再撤进程级**：
       · ``reset()`` 清的是 RunConfigProvider 里的草稿与禁用工具（本次任务那一半）；
       · ``revert`` 发 ``DELETE /models/override``，撤的是进程级两个档位覆盖（另一半）；
       · ``setRestoreSignal`` 让内嵌那份模型面板把自己那两个输入框也拉回服务端值 ——
         少了这一步，下拉框会停在用户改过的那个 id 上（那里有一条"改过就不覆盖"的规矩），
         于是界面显示"恢复了"而实际没有。 */
    reset();
    setRestoreSignal((n) => n + 1);
    if (hasOverride) revert.mutate();
  };

  const footerBar = (
    <div className="rcp-footer">
      <Tooltip title="清空本次草稿与禁用的工具，并撤掉本进程的档位覆盖（回到 .env 的默认值）">
        {/* 文字链样式：这一颗是"撤销"，不是主操作 —— 给它一个描边按钮的体量，
            这一屏的重心就跑到"恢复"上了，而用户来这里是**配东西**的。 */}
        <button
          type="button"
          className="rcp-restore"
          onClick={restoreDefaults}
          disabled={restoreDisabled}
        >
          恢复默认配置
        </button>
      </Tooltip>
      {/* dirty 小圆点：灰=未修改、橙=已修改。**形状 + 位置 + 颜色**三条一起说，
          不靠颜色单说（色盲与高对比模式下那一点橙就消失了）。
          ⚠️ 它是一枚 ``<span>`` 不是按钮：这里没有"点它做什么"，
          做成可点的就是一颗什么都不控制的控件 —— 状态靠 tooltip 读，不靠点。
          给 ``tabIndex=0`` + ``aria-label`` 是为了键盘与读屏**也拿得到这两态**，
          否则这枚点只存在于鼠标用户的世界里。 */}
      <Tooltip title={dirty ? '已修改，应用后生效' : '未修改，按后端默认值运行'}>
        <span
          className={`rcp-dirty${dirty ? ' is-dirty' : ''}`}
          tabIndex={0}
          role="status"
          aria-label={dirty ? '已修改，应用后生效' : '未修改，按后端默认值运行'}
          data-dirty={dirty ? '1' : '0'}
        />
      </Tooltip>
    </div>
  );

  const go = (next: PaneKey) => {
    setPane(next);
    setMounted((prev) => (prev.has(next) ? prev : new Set(prev).add(next)));
  };

  /* 竖排 tablist 的键盘规矩：上下（左右也收，横屏窄版会退化）换项、Home/End 跳两端。
     焦点必须跟着走 —— 只改选中项不改焦点，键盘用户按完方向键就"丢了光标"。 */
  const onNavKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = (delta: number) => {
      const next = NAV[(index + delta + NAV.length) % NAV.length];
      go(next.key);
      navRefs.current[(index + delta + NAV.length) % NAV.length]?.focus();
    };
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') step(1);
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') step(-1);
    else if (event.key === 'Home') {
      go(NAV[0].key);
      navRefs.current[0]?.focus();
    } else if (event.key === 'End') {
      const last = NAV.length - 1;
      go(NAV[last].key);
      navRefs.current[last]?.focus();
    } else return;
    event.preventDefault();
  };

  if (!options) {
    return (
      <div className="rcp rcp--degraded">
        <p className="rcp-degraded-title">配置加载失败，这一版按后端默认值提交</p>
        <p className="rcp-help">
          读不到 <code>GET /config/agent-options</code>（多半是后端进程比这一版界面旧）。
          这一屏<strong>不发任何前端造的默认值</strong>，只发任务文本 ——
          重启后端后这里才会出现可编辑的档位。
        </p>
        {footerBar}
      </div>
    );
  }

  const paneOf = (key: PaneKey, title: string, children: ReactNode) => {
    const active = pane === key;
    return (
      <section
        className="sc-pane"
        id={`sc-panel-${key}`}
        role="tabpanel"
        aria-labelledby={`sc-tab-${key}`}
        tabIndex={0}
        hidden={!active}
      >
        <div className="sc-card">{withPaneBoundary(title, children)}</div>
      </section>
    );
  };

  return (
    <div className="rcp sc">
      <nav className="sc-nav" role="tablist" aria-orientation="vertical" aria-label="设置分组">
        {NAV.map((item, index) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            id={`sc-tab-${item.key}`}
            ref={(el) => {
              navRefs.current[index] = el;
            }}
            className={`sc-nav-item${pane === item.key ? ' is-active' : ''}`}
            aria-selected={pane === item.key}
            aria-controls={`sc-panel-${item.key}`}
            /* 只有一项进 Tab 序（roving tabindex）：三项都可 Tab 的话，
               从导航走到内容区要按三次 Tab，而这是全站唯一一处这么干的导航。 */
            tabIndex={pane === item.key ? 0 : -1}
            onClick={() => go(item.key)}
            onKeyDown={(e) => onNavKeyDown(e, index)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="sc-body">
        {mounted.has('basic') &&
          paneOf(
            'basic',
            '基础',
            <>
              {presets.length ? (
                <div className="rcp-row rcp-preset-row">
                  <div className="rcp-row-head">
                    <span className="rcp-label">预设方案</span>
                    <span className="rcp-default">{presets.length} 档，来自后端</span>
                  </div>
                  <Select
                    size="small"
                    className="rcp-input"
                    aria-label="预设方案"
                    placeholder="不套预设（按后端默认）"
                    allowClear
                    value={presetId ?? undefined}
                    onChange={(id: string | undefined) => {
                      const hit = presets.find((p) => p.id === id);
                      applyPreset(hit ?? null);
                    }}
                    options={presets.map((p) => ({
                      value: p.id,
                      label: p.note ? `${p.label} · ${p.note}` : p.label,
                    }))}
                  />
                </div>
              ) : null}
              <p className="sc-group-title">运行上限</p>
              {BASIC_ROWS.map((k) => (
                <NumericRow key={k} rowKey={k} />
              ))}
            </>,
          )}

        {mounted.has('model') &&
          paneOf(
            'model',
            '模型',
            /* 2026-09-29：原来这一格是「角色模型映射」五行表 + 「模型档位与 API Key」两块的
               上下结构。五行表整块删掉（那五行永远不可能不一致 —— 后端只接受两个档位，
               没有 per-role 语义，第二列只是第一列的展开），
               "两档各管哪些角色"搬进模型面板顶部那行「角色绑定」小字里。
               两块合成一块之后这一格是**从上到下一条线**：
               模型配置（两档）→ API 配置（Key）→ 向量模型，一屏读得完，不用滚。 */
            <Suspense fallback={<div className="rcp-loading">正在读取模型档位与 Key 状态…</div>}>
              <ModelSettingsPanel
                embedded
                onDirtyChange={setModelDirty}
                resetSignal={restoreSignal}
              />
            </Suspense>,
          )}

        {mounted.has('advanced') &&
          paneOf(
            'advanced',
            '高级',
            <>
              <p className="sc-group-title">检索与评审</p>
              {ADVANCED_ROWS.map((k) => (
                <NumericRow key={k} rowKey={k} />
              ))}
              <p className="sc-group-title">工具白名单</p>
              <ToolRows />
              <UnsupportedBlock title="以下配置后端会收下，但当前没有执行机制" items={unenforced} withHelp={false} />
              <UnsupportedBlock title="后端暂不支持以下配置" items={unsupported} withHelp />
              {Object.keys(unknown.topKeys).length ||
              unknown.fieldKinds.length ||
              unknown.undeclaredLimits.length ||
              unknown.unrowedFields.length ? (
                <details className="rcp-unknown" data-testid="rcp-unknown">
                  <summary>后端还给了这些（前端未识别，原样列出）</summary>
                  {unknown.fieldKinds.map((f) => (
                    <p key={`${f.key}-${f.kind}`} className="rcp-unknown-item">
                      <code>{f.key}</code> 的控件类型 <code>{f.kind}</code> 这一版界面不认识
                    </p>
                  ))}
                  {unknown.unrowedFields.length ? (
                    <p className="rcp-unknown-item">
                      这些数值键后端说<strong>能配</strong>、这一版界面却<strong>没有给行</strong>
                      （所以发不出去，也不是"配了不生效"）：<code>
                        {unknown.unrowedFields.map((f) => `${f.key}（${f.label}）`).join('、')}
                      </code>
                    </p>
                  ) : null}
                  {unknown.undeclaredLimits.length ? (
                    <p className="rcp-unknown-item">
                      这些键给了界、却没声明收不收，因此<strong>没有控件</strong>：<code>
                        {unknown.undeclaredLimits.join('、')}
                      </code>
                    </p>
                  ) : null}
                  {Object.entries(unknown.topKeys).map(([key, value]) => (
                    <pre key={key} className="rcp-unknown-json">
                      {key} = {JSON.stringify(value)}
                    </pre>
                  ))}
                </details>
              ) : null}
            </>,
          )}
      </div>

      {footerBar}
    </div>
  );
}
