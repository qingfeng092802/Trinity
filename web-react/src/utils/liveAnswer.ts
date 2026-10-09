/** 运行中答案 / 用量的**外部 store**（SSE ``delta`` / ``usage`` 帧的落点）。
 *
 * 为什么不放 page 的 useState：``TaskLogPage`` 订阅着 SSE，一旦把逐段文本挂到页面上，
 * 每一帧增量都会让**整页**重渲染 —— 日志面板（虚拟列表 + 逐行测量）、工具卡、
 * 结果页那棵 markdown 树全都陪着跳。增量是 80ms 一批（约 12Hz），这个代价付不起
 * （P1-01「别让整页陪秒表跳」是同一条纪律，只是这里的频率是它的 12 倍）。
 *
 * 放到模块级 store、用 ``useSyncExternalStore`` 订阅之后，**只有真正显示这段文字的
 * 那个组件**重渲染，页面本身一动不动。
 *
 * ⚠️ 三条使用纪律：
 * 1. ``getUsage`` 必须返回**同一个引用**直到真的变了 —— ``useSyncExternalStore``
 *    每次渲染后都会拿快照比对，返回新对象会让它判定"变了"并无限重渲染；
 * 2. 换任务 / 提交新任务时必须 ``reset()``，否则上一条的答案会接在新一条前面；
 * 3. 这里的数字只在**运行中**显示。终态一律以 ``done`` 帧与 ``/tasks/{id}`` 回执
 *    为准 —— 运行中累出来的是"到目前为止花掉的"，不是成品账。
 */

/** 一次增量帧的形状（与后端 ``EVT_DELTA`` 的负载逐字段对应）。 */
export interface LiveDelta {
  /** 本帧新吐出的文本。 */
  text: string;
  /** 产出它的节点（``executor`` = 草稿，``reviewer`` = 终稿）。 */
  node: string;
  /** 真 ⇒ 丢弃已积累的文本，从本帧重新开始（换版本，不是接在后头）。 */
  reset: boolean;
}

/** 一次用量帧的形状（与后端 ``EVT_USAGE`` 的负载逐字段对应）。 */
export interface LiveUsageDelta {
  /** 节点名。 */
  node: string;
  tokens_in: number;
  tokens_out: number;
  /** 本次调用的金额（元）。 */
  cost: number;
}

/** 累计用量（前端累加的结果）。 */
export interface LiveUsage {
  prompt: number;
  completion: number;
  cost: number;
  /** 已收到几笔用量增量。 */
  calls: number;
}

type Listener = () => void;

const EMPTY_USAGE: LiveUsage = { prompt: 0, completion: 0, cost: 0, calls: 0 };

let text = '';
let node = '';
let usage: LiveUsage | null = null;
/** 这一条是否已经逐段显示过（供终态屏决定"还播不播打字机"）。 */
let streamed = false;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export const liveAnswer = {
  /** 换任务 / 重新提交：清空一切。 */
  reset(): void {
    if (text === '' && node === '' && usage === null && !streamed) return;
    text = '';
    node = '';
    usage = null;
    streamed = false;
    emit();
  },

  /** 追加（或重置后重写）一段增量。 */
  push(delta: LiveDelta): void {
    text = delta.reset ? delta.text : text + delta.text;
    if (delta.node) node = delta.node;
    if (delta.text) streamed = true;
    emit();
  },

  /** 这一条是否已经逐段显示过。
   *
   *  **刻意不是** `useSyncExternalStore` 的快照：读它的那一侧不需要随增量重渲染，
   *  它只在"任务收尾、结果整段落定"那一刻被问一次 ——
   *  「刚才已经一字一字看着它长出来了，就不要再把同一段字敲第二遍」。
   *  （打字机那半边的立场见 `ResultPane` 的 `revealed`：不给已经落定的内容演一遍生成过程。） */
  streamed(): boolean {
    return streamed;
  },

  /** 累加一次调用的用量。 */
  addUsage(delta: LiveUsageDelta): void {
    const prev = usage ?? EMPTY_USAGE;
    usage = {
      prompt: prev.prompt + num(delta.tokens_in),
      completion: prev.completion + num(delta.tokens_out),
      cost: prev.cost + num(delta.cost),
      calls: prev.calls + 1,
    };
    emit();
  },

  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },

  getText(): string {
    return text;
  },

  getNode(): string {
    return node;
  },

  getUsage(): LiveUsage | null {
    return usage;
  },
};
