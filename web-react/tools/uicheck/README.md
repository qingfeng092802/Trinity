# tools/uicheck · 前端视觉验收

在不改源码、不起后端的前提下，把三页的所有状态渲染出来截图，用于验证**布局 / 层级 / 亮暗主题 / 双端适配**。

做法：Playwright 在浏览器侧拦截 `**/api/**` 与 `**/sse/**`，返回与 `src/types.ts` 逐字段对齐的假数据（`mocks.js`）。

> **这份文档的定位**：它是**开发期的视觉验收日志**，不是产品使用说明。
> 下面按「趟」组织 —— **一趟 = 一轮验收跑批**，每趟给出断言条数与结论；
> 趟次编号（A / V / U / AD / AA / Z …）与 `running.cjs` 里的断言分组一一对应，
> 前端源码注释里引用的「X 趟」指的就是这里的分组。
> 只想把脚本跑起来，看「前置」与「用法」两节就够。
其中 SSE 用 `text/event-stream` 一次性吐完整帧，`EventSource` 会依次解析并在 `done` 后触发终态补拉 —— 所以**页①的实时日志与结果区是真跑出来的**，不是静态假 DOM。

## 已知限制

> capture.cjs:256、capture2.cjs:32 的交互步骤对不上当前 UI（示例按钮已进「配置」弹层、
> 提交按钮改名「提交」），跑到该步会 30s 超时。修复前请用最新 Playwright 脚本或手动截图。
> 该限制先于 2026-09-23 的 trace.arguments 归一化改动，已登记在案。

两处 fixture 要一起改：`capture.cjs` 内联了一份与 `mocks.cjs` 重复的 trace 数据，
改接口形态（例如 `arguments` 按线上给 object）时**两个文件都得改**，否则断言覆盖不到。

## 前置

1. dev server 起在 5173：`npm run dev`
2. 需要 `playwright-core` + 本机 Chrome（不下载 Playwright 自带浏览器）：

```bash
# 装到 WorkBuddy 托管 node 工作区（不要污染项目依赖）
cd ~/.workbuddy/binaries/node/workspace
npm install playwright-core --registry=https://registry.npmmirror.com

# 跑的时候指过去（Windows 路径写法）
export NODE_PATH='C:\Users\<you>\.workbuddy\binaries\node\workspace\node_modules'
```

Chrome 路径在 `capture*.js` 顶部的 `CHROME` 常量里，按本机实际位置改。

## 用法

```bash
node tools/uicheck/bundle.cjs     # 产物门槛（不需要浏览器、不需要 dev server，只要 npm run build 过）：
                                  # 读 dist/index.html 与各 chunk，判「echarts 不在首屏闭包」+
                                  # 「入口占全站 gzip ≤ 0.70（与总量解耦的比例门槛）」+
                                  # 「/tasks 与 /trace 不付 echarts，只有 /eval 付」，共 6 条。
                                  # echarts 的识别用产物里的 zrender 串（许可头已被压缩器剥掉），
                                  # 认不出就 exit 2 报错 —— 签名漂了而门槛闷声变绿比没有门槛更糟
node tools/uicheck/lazy.cjs       # 路由拆包的运行时那一面（要 dev server）：chunk 在途时占位对不对
                                  # （role=status + 三条骨架 + 外壳几何一字不动）、拉不到时报的文案与出口
                                  # 对不对（「刷新页面」而不是点了没用的「重试」，分类正则从 ErrorBoundary.tsx
                                  # 现场抠出来跑，不另抄一份）、以及 /tasks 与 /trace 全程不发 echarts 请求
node tools/uicheck/contrast.cjs   # 对比度实算（WCAG 2.1），核对设计规范里的数字
node tools/uicheck/eval_ux_probe.cjs  # /eval 走查用**测量脚本**（只出数、不判绿）：全站表格藏列普查 +
                                  # 逐层合成的对比度 + 窄屏双栏并存 + 控制台/长任务。走**真后端**（不打 mock），
                                  # 所以不并进 X/Y 趟。EV-04 / EV-05 修完把"不许复发"的数抽成正式趟 ⇒ 它退役
node tools/uicheck/capture.cjs    # 全量：3 页 × 亮/暗 × 桌面/移动，共 24 张
node tools/uicheck/capture2.cjs   # 视口级截图 + 交互验证（主题切换 / 抽屉 / 折叠 / Tab 焦点）
node tools/uicheck/capture3.cjs   # 只验抽屉层级修复（命中测试）
node tools/uicheck/kbshot.cjs     # /knowledge 的**像素留档**（只出图、不判绿，一条断言都没有）：
                                  # 亮/暗/390 三档 × 整页 + 文档表 + 上传区 ⇒ shots/running/kb-*.png。
                                  # 单独一个脚本是因为分段条的亮暗呼吸**本身**由 Z 趟读 data-stages 证明，
                                  # 这几张图回答的是另一句话："它看起来像不像一条能说清进度的条子"
node tools/uicheck/markdown.cjs   # FINAL ANSWER 富文本：82 条断言（表格溢出/粘性表头/数值列/公式区/分数真进 hast/XSS/结论前置/460px 窄屏）× 亮暗
node tools/uicheck/toolcard.cjs   # 工具卡「用户视角」：101 条断言 —— 意图标题 / Tooltip 三行 / 注册表兜底 / 键盘可达 /
                                  # 源码入参按代码渲染（含轨迹回放页那个第二渲染点）/ 折叠与展开 / 剪贴板实读
node tools/uicheck/running.cjs    # 终端配色 + 运行态反馈 + 运行条去重 + **虚拟容器** + **录屏报告核对** +
                                  # **引用列表折叠** + **单次展开负面对照** + **模型读数条** + **结果页宽屏居中** +
                                  # **断流不等于终态** + **取消的四种桩** + **后台标签的探测** +
                                  # **Composer 三设置（含请求体口径）** + **CSV 端到端落地** +
                                  # **运行条播报口（每秒跳秒≠每秒播报）** + **答案子树的 memo 账** +
                                  # **秒表隔离与页签按需挂载** + **URL 恢复与回前台补拉** + **宽表横向滚动区** +
                                  # **终态不许有转圈**（A/B 双向）+ **面板头两列抢宽度** +
                                  # **解释文案按内容断言**（C8）+ **收起态不许留焦点位、日志区键盘可滚**
                                  # （EV-07 / P1-10，挂在 J 这封窄屏信下，与横向溢出同一趟）
                                  # + **成本归因面板（AA）** + **/eval 错误态与形状闸门（AB）** +
                                  # **知识库上传页与分段进度条（Z）** + **右上角换模型设置弹层（AC）** +
                                  # **运行配置面板（AD：一屏五个口径 —— 一份状态 / 一份清单 / 不发没碰过的键 /
                                  # 后端原话落屏 / 字段名与单位也归响应）** +
                                  # **面板收 Key（AE：失焦真空串 / 值只走 body / 供应商原话落屏 /
                                  # 网关档不画框 / 换模型之后两处读数同步）** +
                                  # **答案逐段揭示（AF：只看这次会话里跑的那条才播、终稿一到位就整段给、
                                  # 播过的人切页签回来不重来、prefers-reduced-motion 下不演、
                                  # 剪贴板拿的是整篇原文而不是半截）**：
                                  # A–Y + Z + AA–AF = **32 封 / 41 趟**（数的是 running.cjs 末尾那张调度表：
                                  # A / B / G / H / I / J / AC / AE / AF 九封各挂两趟 ⇒ 封数 + 9）
                                  # （断言总数与开页数看下面"断言总数"那一节，只认探针打印的那一行。
                                  #  ⚠️ 旧版这里写的"三十一封 / 三十三趟"两数都不对：封数少算了 AF 那一封，
                                  #  趟数只数了 J/AE/AF 的双趟、漏了 A/B/G/H/I/AC 也是亮暗各一趟）
                                  # （亮暗各一趟的是 A/B/G/H/I，其余单趟；外加 240 行虚拟容器、评测页术语、
                                  #   引用折叠、100 行 vs 4,800 行、/models 三种形态、
                                  #   2560/1280/768 三档排版）
node tools/uicheck/logperf.cjs    # 日志性能：切页签 / 页签往返（**分方向**）/ 切结果页拆 React 与浏览器两半 /
                                  # 引用列表折叠两态元素数与切换耗时 / 滚动帧 / longtask / 堆 / 按块普查
                                  # ROWS=500|5000|8001 三档；只测不改，不碰 src/
python tools/uicheck/demo_kb_seed.py
                                  # 【录屏前置】把 data/demo_docs/ 里**能进库的三篇**（md/txt）传到正在跑的后端，
                                  # 并等索引状态机走完（pending→parsing→chunking→embedding→ready）。
                                  # 同名已存在回 409 ⇒ 直接复用：重拍几遍时 chunk/token 读数不该跟着抖。
                                  # ⚠️ 后端要起在**隔离运行目录**（临时 DB + 临时 KNOWLEDGE_DIR），
                                  #   否则演示数据会写进 data/ —— 命令在脚本 docstring 里。
node tools/uicheck/record_demo.cjs
                                  # 【README 首屏 GIF 的素材来源】真实点击跑一遍端到端并录成 webm：
                                  # 知识库页 → 逐字打一条任务 → 提交 → SSE 日志与答案流 → 结果卡 →
                                  # 从结果卡跳进轨迹回放并「全部展开」。产出 timeline.json（每步时刻 +
                                  # 任务真实读数），GIF 文案照它写，不凭记忆。
                                  # ⚠️ 与这个目录里其余脚本的根本区别：**要真后端 + 真 LLM Key，一条任务
                                  #   会真花钱**（本趟 6 次 deepseek-flash 调用、Σ 事件成本 ¥0.0546），
                                  #   所以它不进 CI，也不许对着生产 data/ 跑。
                                  # 两个坑写在脚本注释里，别重新踩：侧栏是图标按钮（只能按 aria-label 点）；
                                  # 界面每 30 s 轮询 /health ⇒ networkidle 永不安静，终态一律问后端。
```

## 不用浏览器的纯函数断言

`src/utils/` 下这几枚纯函数都能在 node 里直接断言，不必拉起 React：

```bash
npx esbuild src/utils/answerText.ts --bundle --format=cjs --outfile=tools/uicheck/answerText.cjs
npx esbuild src/utils/toolMeta.ts  --bundle --format=cjs --outfile=tools/uicheck/toolMeta.cjs
npx esbuild src/utils/logRows.ts   --bundle --format=cjs --outfile=tools/uicheck/logRows.cjs
npx esbuild src/utils/answerMath.ts --bundle --format=cjs --outfile=tools/uicheck/answerMath.cjs
npx esbuild src/utils/pyTokens.ts  --bundle --format=cjs --outfile=tools/uicheck/pyTokens.cjs
npx esbuild src/utils/format.ts    --bundle --format=cjs --outfile=tools/uicheck/format.cjs
npx esbuild src/utils/citations.ts --bundle --format=cjs --outfile=tools/uicheck/citations.cjs
npx esbuild src/utils/modelLabel.ts --bundle --format=cjs --outfile=tools/uicheck/modelLabel.cjs
npx esbuild src/utils/runPhase.ts   --bundle --format=cjs --outfile=tools/uicheck/runPhase.cjs
node tools/uicheck/answerText.test.cjs   # 38 条（+13：裸序号标题的闸门与"只加空白"的无损判定）
node tools/uicheck/toolMeta.test.cjs     # 60 条
node tools/uicheck/logRows.test.cjs      # 17 条（心跳合并：什么并、什么绝不并）
node tools/uicheck/answerMath.test.cjs   # 68 条（isMathBlock 判定 + sub/sup/\frac/分数真进 hast + 裸下划线 + 代码节点换皮肤 + 不猜的反例 + XSS 兜底）
node tools/uicheck/pyTokens.test.cjs     # 32 条（Python 分词：无损拼回 / 四类色 / 不误判 match 与属性点号）
node tools/uicheck/format.test.cjs       # 53 条（+23：新增 `relativeFromDelta` 的分档表与"超过 30 秒才算黄"那道不连续点；
                                  #      原有的**时长进位** 1m 60s / 60.0s / 1000ms 一档都不许出现、含 0~2h 全区间扫描仍在）
node tools/uicheck/citations.test.cjs    # 26 条（引用行解析：真形状拆成 N 行 / 认不出整条退一行「—」/ 全角｜的护栏 / 跨事件 key 不撞）
node tools/uicheck/modelLabel.test.cjs   # 20 条（模型读数的三条措辞纪律：拉不到⇒空串 / 兜底价不许叫官方价 / 两档不同不许只报一个大档）
node tools/uicheck/runPhase.test.cjs     # 17 条（跑动中那句阶段文案的口径：已完成到哪一格 ⇒ 说的是**后继**那一格，
                                  #      不是刚交卷的那格；未知/非编排节点（system / answer / router / 空）退回通用那句，
                                  #      绝不"猜"在规划 —— 编排图只有 planner→executor→reviewer 三条定边）
```

### 公式排布那两个「只出数、不判定」的脚本

`answerMath.test.cjs` 的期望值必须是**跑出来的**，所以留了两台生成器：

```bash
node tools/uicheck/mathdump.cjs                      # markdown → 简化 HTML 串，改完实现先跑它抄期望值
python tools/uicheck/formula_hits.py    # 只读打开 sqlite，数真答案里各种公式形态的命中率
node tools/uicheck/realcorpus.cjs <answers.json>     # 把真答案灌进排布层，数到底换出了几个分数/上下标
```

`realcorpus.cjs` 是「要不要上 KaTeX」的唯一依据 —— fixture 是我自己写的，不算证据。
它读那份 JSON 由 `formula_hits.py` 同源导出（写到临时目录，**别落进仓库**：那是他库里的答案原文）。

`pyTokens.test.cjs` 里最该保住的是那几条 **round-trip**：片段拼回去必须逐字等于原源码。
上色是装饰，吞字符是事故 —— 入参块里的代码是用户排查沙箱超时的唯一现场。

`answerMath.test.cjs` 里跑的是 `unified + remark-parse + remark-rehype`：这三个包是 ESM，
`require` 回来要取 `.default`，否则 unified 会把命名空间对象当成「空 preset」直接抛。
**安全断言必须按 react-markdown 的实际配置传参** —— 它内部用
`remarkRehype({ allowDangerousHtml: true })`（`react-markdown/lib/index.js:112`）再把 raw
渲染成文本；用默认配置（false）raw 整节点被丢，测出来的就不是产品行为。

esbuild 产物（`answerText.cjs` 等八份）**逐个点名**写在 `web-react/.gitignore` 里，不是 `*.cjs` 通配 ——
`.test.cjs` 和浏览器探针本身就是 `.cjs`，要入库。新增一枚纯函数测试时记得同步加一行。

### markdown.cjs 的两条经验

- **粘性表头的截图**：`scrollIntoViewIfNeeded` 只保证元素「露出一点」，表头那 38px 常被视口
  上边缘切掉，看起来就像表头没粘住。要 `scrollIntoView({ block: 'center' })` 把整块居中再截。
- **`page.screenshot({ clip })` 的坐标空间**在「页面自身还要滚」的布局里不可靠（视口坐标与
  文档坐标都会被页面滚动量偏移掉），所以这里改成整视口截图 + 数值断言（`thTop - wrapTop ≤ 1`）
  双管：数字定性，图片给人看。

### passVirtual：虚拟化独有的三类失效模式（240 行那一趟）

`LogStream` 换成 `@tanstack/react-virtual` 之后，DOM 里只挂视口 + overscan 那一窗，
于是出现三类**改造前根本不存在**的失效模式。它们都只会以「真机上坏了」的形式暴露，
所以必须在这里钉住：

- **命中跳转静默失败**：`querySelector('[data-hit=N]')` 对没挂载的行返回 `null`，点「下一处」什么都不发生。
  现在先 `scrollToIndex`，再等两帧用 `scrollIntoView` 收口（测高回填后可能还差半行）。
  用例：连点 40 次到第 41 处，断言 active 高亮确实落在面板内。
- **入场动画被滚动重放**：`.log-row` 原本无条件挂 `animation: log-in`，靠「所有行常驻」才成立。
  历史行反复挂载 = 每进视口放一次。现在动画挂在 `.log-row--in` 上，由组件在**挂载那一刻**决定
  （`useState` 初始化函数，同一个 DOM 节点只跑一次，不会中途翻掉把动画掐断）。
  用例：滚到中段后所有挂载行的 `animationName` 必须是 `none`。
- **自动滚动被测高回填误关**：新行先按估算高度占位、`measureElement` 之后才回填真实高度，
  一批折行长消息会把 `scrollHeight` 突然撑长 —— 此刻 `scrollTop` 一动没动，但「距底 > 24px」
  成立，于是自动滚动被悄悄关掉，用户看到的最后一条日志就此停止更新。
  现在只认「scrollTop 比上次钉住的位置更小」= 真人往上推。
  用例：钉底后把 spacer 撑高 400px 并派发 scroll，断言「自动滚动已开启」还在；
  再反向断言手动上滑 120px 时它确实关掉（只测不误关会漏掉反向回归）。

顺带一条**改造时才发现的死规则**：`.log-row:last-of-type { border-bottom: 0 }` 在运行态永远选不中任何一行 ——
`.log-body` 里最后一个 `div` 是 `.log-cursor` 不是 `.log-row`。现在换成显式的 `.log-row.is-last`。

### 录屏实测报告（2026-09-24）逐条核对

报告是看着 174 秒录屏写的，14 条里**只有 3 条是当下还成立的前端缺陷**。核对结果（成立=本轮已修）：

| 条目 | 判定 | 依据 |
|---|---|---|
| UI-1 时长 `1m 60s` | **成立，已修** | `fmtDuration` 分秒各自取整；现在先取总秒再拆档，`format.test.cjs` 扫 0~2h 每 50ms |
| UI-2 `P_IT` 等下标字面量 | 同日更早修好 | 裸下划线规则（录屏那一版还没有） |
| UI-3 中西文/希腊字形不同族 | 观察成立，**结论要改** | CDP 实测：拉丁 = Segoe UI，**η 与拉丁同族**，中文 = Microsoft YaHei，公式块 = Consolas（本轮刻意上的等宽）。所以 η 没掉进衬线，"等宽感"来自公式块本身。中/西不同族是不分发字体文件的必然结果，不当缺陷修 |
| UI-4 三张指标卡权重不一 | **不成立** | 只有一个渲染点；实测三张都是 `16px / 600` |
| UI-5 浮层压住校验文案 | **成立，已修** | 走键盘 `Ctrl+Enter` 时弹层不会因"外部点击"收起 → 提交一次就收 |
| UX-1 术语无释义 | 一半成立 | 「合并重复」「封顶丢弃」「降级」早就有 title / 弹层；缺的是评测页 4 张指标卡 + 9 个表头，已补 |
| UX-2 图标栏无文字标签 | **不成立**（但有真缺陷） | Tooltip + `aria-label` 一直在，录屏没悬停过所以没拍到。真缺的是键盘路径：`rc-tooltip` 默认只挂 hover，已补 `focus` |
| UX-4 回放页要手输 task_id | **不成立** | 「最近任务」下拉 + 嵌入的任务列表一直在 |
| UX-5 `迭代轮数 0` | **不成立，且建议会写错** | 后端记的是**退回重跑次数**（`reviewer.py:74`），改成 `1 / 3` 就是假数；场内已有 hint + ⓘ |
| UX-6 `aria-live="polite"` | 与既有决策冲突 | `role="log"` 配 `aria-live="off"` 是刻意的（SSE 高频会把读屏刷爆）。对比度那半实测 5.12 / 5.44，达标 |
| UX-7 取消无二次确认 | **成立，已修** | Popconfirm；判据用「第一下有没有真的发出 cancel 请求」，不看弹框 |
| SM-1 88 秒近静止 | 前端侧已补 | 运行条右侧「最后一条日志 x 秒前」，超 30 秒变黄（心跳帧不计）。根因是单次长模型调用中间没有子事件 —— 那是后端的账 |
| SM-3 计时器随事件跳变 | **不成立** | 1Hz `setInterval` 早就在（`TaskLogPage.tsx` 注释写明"不累加 tick，按 createdAt 重算"） |
| SM-4 结果页整屏铺开 | 未动 | 要真机 Performance 面板才能定性；先加淡入可能更糟 |

三条探针经验（都各吃掉一次调试）：

- **AntD 隐藏页签是「假可见」**：不活跃的 `.ant-tabs-tabpane` 挂 `visibility:hidden`，布局照排、
  `getBoundingClientRect` 照给高度、`getComputedStyle` 照给字号 —— 于是断言全绿而截图超时
  （"element is not visible"）。`offsetParent` 抓不到这种情况，只能一路往上查 visibility / display。
  所以 `readMetricParity` 带一个 `visible` 字段，并且切页签的断言排在 `.log` 截图**之后**。
- **`document.fonts.check('16px Inter')` 不能用来判断字体在不在**：对**没有任何 @font-face 的族**
  它恒返回 true（没有待加载字面 = "全部已加载"）。要读实际渲染用了哪一族，只有
  `CSS.getPlatformFontsForNode`（CDP）—— `platformFamilies()` 就是干这个的，它按字形数报族名。
- **is-stale 那一条用的是刻意错位的时间**：二次提交的帧 ts 被挪到 45 秒前，而 `submitted_at`
  仍是当下，所以同一屏会同时出现「提交后 1.0s」和「最后一条日志 45 秒前」。真机不会出现这个组合，
  截图也因此只裁 `.runbar-actions`（整条运行条会显得自相矛盾）。

### 结果页往返那 230ms 的账（U15，含一次误判的更正）

- **上一轮指错过对象**：数了 `.copy-btn` 1002 / `.chip` 1002 / `span.row` 1001 就断言「开销在工具块列表」。
  错了 —— 那三个数出自**结果页的引用列表**（1,000 行 × 约 11 个元素），同一趟里 `工具卡` 数是 **0**：
  AntD 的页签**首次激活才挂载**，往返只在「结果 ⇄ 日志」之间走，工具页签压根没挂过。
  教训：通用元素计数只会指错人，**块级计数**才指得对人 —— 现在 logperf 的普查把
  引用行 / 工具卡 / 复制按钮分开数。
- **拆法**：A = 点页签（React 重渲染 + 可见性翻转 + 布局绘制，全算上）；
  B = 不经过 React，只用内联 style 把同一屏 `display:none` ↔ 显示。A−B 就是 React 那半边。
  ⚠️ B 必须在结果页**正处于激活态**时量：第一次量出 5.7ms，因为那时整块子树是
  `visibility:hidden`，浏览器只排不画 —— 那不是切页签要付的那一份。
- **三档实测**（同一趟 dev server，memo 已生效）：

| 档 | 引用行 | 全页元素 | 走 React A | 不经 React B | React 那半边 A−B | 往返中位 |
|---|---|---|---|---|---|---|
| 500 | 100 | 1,945 | 51.2 | 21.8 | 29.4 | 55.7 |
| 5,000 | 1,000 | 11,885 | 150.4 | 104.4 | 46.0 | 150.0 |
| 8,001 | 1,600 | 18,486 | 252.5 | 171.2 | 81.3 | 220.7 |

- **memo 前后的同条件对照**（5,000 档，本会话内两趟）：到结果页 233.4 → 155.9，
  到日志页 142 → 71.8，往返中位 222 → 148。上一趟记的 314.3 是另一趟的数，
  条件不完全可比，别拿它当收益算。
- **结论**：React 那半边已被 memo 压到 46~81ms，剩下的 **104~171ms 是浏览器给 1,000~1,600 行引用
  做的布局与绘制**，memo 动不了它。要过 <100ms 那条线，只能把引用列表的行数与数据量解耦
  （虚拟化，或默认折叠 + 展开）—— 与日志面板同一套判据。

### 引用列表：从假文档名到默认折叠（U15b / c / d / e）

- 上一版 `buildCitations` 每行都写死 `document: '知识库检索结果'`、score 一律 NaN →「—」，
  旁边那颗胶囊还自称「如实显示 —」。**后端确实没有 citations 字段**
  （`api/schemas.py:538` 的 TaskEventView 只有 `observation: str`），但真文档名就在那段引用行里，
  于是改成「认得就拆、认不得就 —」。
- 期望值不是我编的：fixture 由后端 `_render()` 现跑出来抄进 `citations.test.cjs`（顶部有复现命令），
  另一条「认不出」的样本是从 `data/trinity.db` 的 `task_events` 里读出来的真错误串。
- 解析器第一个 bug 正是那份真 fixture 抓的：第三条命中写的是 `chunk -1`
  （`document_name` 为空时后端回填 id、`chunk_seq` 用默认值 -1），正则只写 `\d+`
  会把整行的文档名一起判成读不出 —— 自造 fixture 永远测不到这一条。
- **折叠三数**（logperf 2c，三档）：

| 档 | 引用总行数 | 折叠态 | 展开态 | 展开耗时 | 收起耗时 |
|---|---|---|---|---|---|
| 500 | 300 | 10 行 / 811 元素 | 300 行 / 4,001 元素 | 139 ms | 36 ms |
| 5,000 | 3,000 | 10 行 / 811 元素 | 3,000 行 / 33,701 元素 | 922 ms | 80 ms |
| 8,001 | 4,800 | 10 行 / 815 元素 | 4,800 行 / 53,505 元素 | **1,817 ms** | 121 ms |

- 折叠把往返彻底解耦了：往返中位 **51.4 / 57.1 / 57.8 ms**（此前 55.7 / 150.0 / 220.7），
  全页元素 **956 / 956 / 952**（此前 1,945 / 11,885 / 18,486）。<100ms 那条线三档全过。
- **负面对照（running.cjs 的 F 趟）**：折叠把常驻 DOM 钉在 10 行之后，「切页签 57ms」就
  不再暴露任何信息了 —— 代价没消失，只是挪到了点「展开全部」那一下。所以两个规模各点**一次**：

| 引用行数 | 折叠态常驻 | 展开后 | 单次展开（含帧） | 收起（含帧） |
|---|---|---|---|---|
| 100（真实任务规模上限附近） | 10 行 / 812 元素 | 100 行 / 1,802 元素 | **78.7 ms** | 42.2 ms |
| 4,801（5,000 事件全是检索） | 10 行 / 812 元素 | 4,801 行 / 53,513 元素 | **1,862 ms** | 118.4 ms |

  两档的折叠态元素数都是 **812** ⇒ 「与总行数解耦」这条口径的正证（E 趟里那个断言比的是
  181 / 100 / 4,801 三个规模的折叠态，任何一个变了就红）。
  两个 1.8 秒都记着，别当成互相打脸：上表 **1,817ms** 是 logperf 那一趟（同一页上还挂着
  5,000 行虚拟日志的堆与元素），F 趟 **1,862ms** 是干净页只有引用列表 —— 同量级，差额来源
  是同一页上别的东西。两趟各自可复现。
- **1.8 秒尾巴按已知限制记录，不当 bug 修**：真实任务一次约 5~20 条引用，100 行那档实测
  78.7ms（门槛 <200ms），尾巴要 4,800 行才够得到。要治它只能给这条列表也上虚拟滚动。
  长尾的**归因**（脚本 vs 布局 vs 绘制）走 DevTools Performance 录制，不用点击链去凑。
- ⚠️ 一个读数以讹传讹的机会：`btn().click()` 那一行的**同步**耗时实测只有 0.4~0.6ms，
  别把它读成「React 干得很便宜」—— React 18 把这批更新排进了帧前调度，click 的同步栈里
  压根没干活，1.8 秒全在「从点击到画完」那一个数里。门槛数一律取含帧。
- 分步展开（`CITATION_STEP = 50`，10 → 50 → 100 → … → 收起）实现过、也量过一档
  （300 行 6 步、单步含帧 47~50ms，其中 raf2 底噪就占 8.9ms —— 分步的分辨率不够），
  2026-09-24 拍板按已知限制接受尾巴，代码已撤：**`TaskLogPage.tsx` 里跑分的代码与 `3884a05`
  逐行一致**，只剩一段注释（把上面那条已知代价钉在按钮旁边，指向本节）。
- 同码复测（这一轮重跑三档）：单次展开 **124.8 / 955.1 / 1,851.9 ms**，往返中位
  **60.4 / 62.4 / 58.9 ms**，折叠态仍是 10 行 / **811–815** 元素。与上面两张表的差额是
  机器噪声（代码没动），量级一致 ⇒ 三档往返仍全在 <100ms 线内。
  - **2026-09-25 追加（P1-01 之后同一口径）**：上面那些"常驻"数已经作废一半 —— 结果页签
    改成按需挂载后，停在日志页签时全页元素只有 **501**（引用行 0、工具卡 0），
    而不是折叠态仍常驻的 956/956/952。旧数保留不改写，是为了留住的当时那次折叠的效果；
    两次的差额来源就是"看过一次之后是否常驻"。详见本文 V 节。
- 探针 fixture 也跟着换成真形状：`mocks.cjs` 的 knowledge_search observation 以前是自造紧凑形
  （`命中 4 个 chunk：x#c12（0.83）`），解析器**永远不命中**，浏览器探针测的一直是兜底分支。

### 模型读数条（G 趟，98 条断言）：把假下拉换成读数

**病根**：composer 里那颗模型 Select 的选项写在 `src/mock/taskMock.ts`（文件名就自称 mock），
选完既不进 `POST /tasks` 的请求体、后端 `TaskSubmitRequest` 也没有对应字段 —— 一个什么都不
控制的控件。现在这条链换成：`GET /models`（`api/routes/models.py`）→ `useModels`（**拉不到就
返回 null**，绝不回落到写死的清单）→ `utils/modelLabel.ts`（措辞层，纯函数）→ `.cp-model-ro` 读数。

G 趟按三种部署形态各跑一遍（亮暗两轮）：两档同一模型（本机 `.env` 的真实形态，后端**合并成一条**）/
两档不同模型 / 强模型不在单价表里。三份 fixture 都是真跑 `get_models()` dump 出来的，
不是手编的（同 U15 那轮的教训：自造 fixture 只会让探针一路走兜底分支）。断言盯的是：

- 胶囊文案跟着**响应**变（`模型 deepseek-v4-pro +deepseek-flash`），不是前端自带的一份清单；
- 「兜底价」不许冒充「表内价」—— 兜底那行数字与 flash 的表价**一模一样**（2.13 / 8.52），
  只看数字看不出谁是被兜底的，所以措辞必须分开；
- 只有一条时不说「强模型 / 快模型」：改成「两档同一个模型 X」，否则会让人觉得还有个快模型被藏起来了；
- 它不再假装是控件：DOM 是 `span`、`cursor: default`、无描边、`.composer` 里 `.ant-select` 数为 0、
  真发一次 `POST /tasks` 后请求体的键只有 `task` / `enabled_tools`（**没有** `model`）；
- 明细对键盘可达：`tabindex=0` + `trigger={['hover','focus']}`，聚焦后弹层真的出现；
- 字色实测对比度：**亮 7.78**（白底）/ **暗 8.22**（`rgb(20,22,30)`），都过全站正文 4.5 线；
- 后端 500 ⇒ 整条不渲染（这条是「宁少一行信息也不造清单」唯一的机器证据）。

**单价这条链的账**（2026-09-24，`10704ce` 修的是默认值，本轮补完两处下游）：

- `config.py` 的 `LLM_PRICE_IN/OUT` 默认值一度写成 `2.13e-6` 并标注「元/token」，却被按
  「元 / 100 万 token」用 ⇒ **没配 `.env` 的机器**把 100 万 token 估成 1e-5 元，低估 10⁶ 倍。
- `.env.example` 那份**单位本来就是对的**（`# 成本估算兜底单价（元 / 100 万 token）` + `2.0` / `8.0`），
  所以坑不在示例文件里。它缺的是**生效条件**：模型在 `core/llm/adapter.py:MODEL_PRICES` 表里时
  这两行根本不参与，而两个 DeepSeek 模型都在表里 ⇒ 改它没效果。已在示例里写明，防下一个部署继续踩。
- 真正没收口的是 `api/runner.py:estimate_cost_cny`：它直接读 `settings.llm_price_in/out`，
  于是本机 `.env`（2.0 / 8.0）下**提交前的预估**与注册表标的表内价（2.13 / 8.52）差 6%，
  而实际记账用的是表内价 —— 同一屏两个价。现在与 `estimate_cost`、`GET /models` 共用
  `resolve_price`。用例 `test_submit_estimate_uses_the_registry_price` 把兜底价设成荒谬值，
  修前那条算出来是 **0.0 元**（6 位小数直接被抹平），修后 0.056562 元。

`role_map` 的值必须是**模型 id**，不是档位：一开始写成 `item.tier`，在单模型部署上真的产出了
`executor: "large"` 这种谎（那个部署里根本没有第二档）。用例
`test_role_map_is_the_transpose_of_items` 用 `model-L` / `model-S` 当 id，把「顺手填档位」这个
写法直接判红。前端**刻意不渲染** `role_map` —— `items[].roles` 已是同一事实的另一面。

### 结果页宽屏排版（H 趟，42 条断言 = 亮暗各 21）：限宽是对的，缺的是居中

现象（他 2560 截图）：三块指标卡 + 摘要 + 正文全靠左，右侧一大片空。**根因与报的不完全一样**：
`.result-wrap` 一直有 `max-width: var(--measure)`（820px，正文限行宽），
外层 `.app-content` 也一直是 `max-width: 1560px; margin-inline: auto`（实测 2560 下左右各空 468/531，
那 62px 差是图标栏，不是 bug）。缺的只有"居中"这一半 —— 修前实测**左留白 0 / 右留白 390**。
所以"右侧空 60% 屏宽"不成立（390/2560 = 15%，占内容面板的 32%），但**缺陷本身成立**。

改法（`index.css`，两处）：`.result-wrap` 抬到 `max-width: 1100px` + `margin-inline: auto`，
正文三块（`.summary-callout` 与两个直接子 `.stack`）另挂 `max-width: var(--measure)`。
抬外层只为给指标卡呼吸，**不是给汉字行长开的口子** —— 正文仍 820（约 75 个汉字）。

H 趟按 2560 / 1280 / 768 三档 × 亮暗，每档 6–9 条：留白是真的（左右各 ≥20px，防"0/0 蒙对居中"）、
左右对称（|差| ≤2）、卡与正文同一条左边缘（|差| ≤1，居中不许变成"每块各居各的中"）、
正文 ≤820、无横向滚动。实测：2560 ⇒ 内容块 1100 / 留白 55+55 / 卡 1100 / 正文 820；
1280 与 768 ⇒ 内容块铺满（868 / 652）、留白 0/0、三档横向溢出都是 0。
截图 `shots/running/result-{light,dark}-2560.png`。CSS 体积 +0.08 kB（gzip +0.02 kB），JS 未变。

顺手量的**同类嫌疑，按边界只记录不改**：实时日志页签 `.log` 与工具调用页签 `.tool-card`
在 2560 下都是 1210 / 左右各 0（本来就铺满，无同类问题）。轨迹回放与评测页我只量到单块
`.metric`，它"右边空 968/1151"是**同一网格里兄弟卡占位**、不是空档 —— 那两个数不能当缺陷证据，
真要判这两页得另开一趟数整块网格的列布局。

### 结果页排版打磨（I 趟，44 条断言 = 亮暗各 22）

五处一起改，每条都读**计算样式**而不是源码字面量 —— CSS 写了不等于挂上了：

| 改的东西 | 实测（亮 / 暗） |
|---|---|
| 指标卡内边距 13/15 → 10/12，等分 1/3 → flex 靠左（min 180 / max 240） | `10px 12px 11px`（三段 shorthand：上 10 / 左右 12 / **下 11**），三块各 180px、总宽 540 < 网格 1028 |
| FINAL ANSWER 标签：11px 灰 → 14px 加粗 + 中文副标 + 3px 主色竖条 + 上间距 24px | `14px` / `3px rgb(79,70,229)` / `24px` |
| 硬指标那行拆出紫块（`.result-meta`） | 不在 `.summary-callout` 内、排在其下方；对比度 7.78 / 8.22 |
| 裸序号行「一、xxx」提成一级标题（16px + 竖条）；markdown 二级 14 → 15px | 正文 14px / 一级 16px / 二级 15px，段间 18px、标题后 8px、列表前 8px |
| 引用空态不再画虚线框 | `.cite-empty` 存在、`border 0px` + 透明底、旧胶囊确实不在 |

**「关键数字高亮」这条按证据缩了范围**：真答案（库内 n=8，只读统计）里"数字 + 可选单位"
的朴素嗅探会碰到 **105 个 token ≈ 13 个/篇**，其中还混着有序列表序号（`1.` `2.`）与
`IEEE 802.3af` 这类型号上下文 —— 全染主色等于没有重点。所以只做**"模型自己加粗且含数字"**
的那一格（`strong.ast-num`）：`3-5 秒`、`42` 染色，`重要提示`（不含数字）不染，
两条都在断言里。主色当文字用的 AA 也单独量了：**6.29 / 6.05**。

**裸序号行的判定口径**同样来自那 8 篇：这种行 4/4 处都是「序号行 + 紧跟正文」同一个块，
所以 `liftBareHeadings` 只在**块首行 + 后面确实还有行**时插一个空行。闸门：只认中文序号 +
「、」（`1、`/`1.` 与有序列表撞车，认了会把列表项拆成标题）、≤32 字、含「。」/「！」/「；」
或表格行一律不算（允许结尾「？」）。判定与拆分共用同一个 `isBareHeadingLine`，两处不会分叉；
`answerText.test.cjs` 里钉 13 条，含一条**"lift 前后去掉空白的字符序列逐字相等"** ——
渲染串与原文差一个字符就是页面在说谎（复制按钮给的仍是原文）。

**一条空紫条：条件渲染写在容器里面（2026-09-25，用户真实浏览器实测报告）**

结果页「成功 · 工具调用 1 次…」上方出现一条只有底色没有内容的浅紫横条。根因不在数据，
在 JSX 的**条件写在容器里面**：

```jsx
<div className="summary-callout">   {/* 底色 / 描边 / 11·14 内边距都挂在它身上 */}
  {conclusion && <p className="sc-main">…</p>}
</div>
```

`pickConclusion` 认不出结论段时返回 `null`（一句话答案必然认不出：`1+1`、`1024×768` 这类，
本地库 6 条已完成任务里 4 条如此）⇒ 里面的 `<p>` 没了，**容器还在画**，于是 24px 高的一条空块。
不崩、不报错，只是难看且说谎（那条紫块的视觉语义就是"这里有摘要"）。
修法是**把条件提到容器外面**，没有结论可说就整块不渲染；"为什么没有摘要"仍由下面那行
`.result-meta` 说清楚（那里本来就在写「答案里没认出结论段，结论请看下方 Final Answer」）。

I 趟为此加了两个方向的守卫（每主题 +5 条）：

- **正例**：长答案时读 `.summary-callout` 的文本，断言它非空（摘要条画出来就必须有内容）；
- **反例**：把 mock 的答案换成一句话（`answerNow = '1 + 1 = 2'` + 重新载入），断言
  `.summary-callout` **整块不在 DOM 里**、`.result-meta` 补上了"为什么没有"。
- 外加一枚**通用空壳普查**：结果页里凡是「背景不透明 + 无可读文本 + 无 svg + 未 `aria-hidden`
  + 高度 > 0」的块一律记名（`summary-callout@24px` 就是它抓出来的形状）。这条不是为了这一
  个 bug 写的，是为了下一枚同类的容器。

负面对照 N6（跑完已撤）：把 JSX 改回上面那个错误写法 ⇒ I 趟当场 **4 条翻红**（亮暗各 2），
读数是 `有摘要块:true / 块高:24 / 空壳块:["summary-callout@24px"]`。
这同时说明**原来的 I 趟是假绿的**：它只跑长答案那一档，空壳这一档从来没被测过 ——
每加一条排版断言都要问一句"这一条在哪个答案形态下会红"。

### 窄屏横向溢出（J 趟，32 条断言 = 390/820 判定 + 320 只记录）

起因是 2026-09-24 那份真实浏览器检查：390 视口下 `document.scrollWidth = 545`，越界元素
`div.ant-tabs-extra-content`（left 134 / right 545 / width 411）—— 日志控件那一排挂在页签栏的
extra 位，而页签栏是 AntD 的横滚容器、**不会换行**，塞不下就把整篇文档顶宽。窄屏（≤768）
把同一组控件挪到面板顶行的 `.log-controls`，宽屏维持原挂点。

三个设计上的讲究，都是这一趟自己踩出来的：

- **两档皮肤都要量**：0 行时 `LogStream` 渲染的是浅色静默态（没有深色工具条），控件那时
  同样得能用到 —— 所以每一档都跑「有日志」和「关键字滤到零行」两遍。
- **溢出普查分三路**：`offenders`（右边界越出视口）、`hiddenByClip`（被祖先裁掉、撑不宽文档
  但会把真凶藏起来）、`widening`（自身 `scrollWidth > clientWidth` 且 `overflow-x: visible`，
  把宽度**往上漏给祖先**的那类）。只查第一路会报出「越界元素为空、文档却溢出 18px」这种
  自相矛盾的读数 —— 320 档就是这么卡住的。
- **注入关键字必须走 `aria-label`**：`.log-controls input` 会先命中 AntD Select 的内部搜索框
  （只读），给它赋值不报错、也什么都不过滤，上一版就这样把「滤到零行」整条跑空还照样绿。

**320 记为已知限制、不判定**：结果页签上 `.page-columns` 外漏 18px（`scrollW 276 / clientW 258`，
文档 `scrollW=338 / clientW=320`）。验收口径是 390（390 档全绿），320 留作读数探针，等真要
把支持面压到 320 再修。处置方式同 F 趟对 4,800 行 1.8s 的负面对照。

**负面对照做过一次**：把 `!isNarrow` 摘掉再跑，390 档立刻复现 `overflowPx=155 / scrollW=545`，
与真实浏览器那份证据一字不差（同档另外三条断言一起红）。这条用例不是恒绿的装饰品。

### 收起态不许留焦点位 + 日志区键盘可滚 + 第一次点开就钉底（J 续，27 条 = EV-07 + P1-10 + 钉底）

`ONLY=J` 从这一轮起一次跑两趟（上面那封窄屏横向溢出 + 这一趟）。这一趟量的不是"DOM 里有多少
可聚焦元素"，而是**按下 Tab 之后焦点到底落在谁身上** —— EV-07 的形状正是"看不见但 Tab 得到"：
收起（宽屏 `width:0`）或关抽屉（窄屏 `translateX(-100%)`）之后，那栏里的搜索框、四个筛选、
整列任务条目照样能聚焦，键盘用户要连按二十多下对着看不见的面板操作。
`opacity:0` 与 `pointer-events:none` 对焦点**一个都不管**，管得住的是 `visibility:hidden`。

| 读数 | 值 |
|---|---|
| 宽屏展开：栏内焦点位 / Tab 45 次命中 | DOM 里 14 枚 · 命中 13 次 |
| 宽屏收起：visibility / 实渲宽度 / Tab 命中 | `hidden` / `0px` / **0 次** |
| 收起后再展开：第 80ms 的 visibility / Tab 命中 | `visible`（展开方向不排队）/ 19 次 |
| 窄屏抽屉关着：visibility / 右边缘 / Tab 30 次命中 | `hidden` / `0`（整块在屏外）/ **0 次** |
| 拉开抽屉：visibility / Tab 命中 | `visible` / 14 次 |
| `.log-body`：tabindex / role / 可滚量 / 第几步 Tab 到 | `0` / `log`（没改）/ 2,591px / 第 20 步 |
| 键盘聚焦环（读渲染值，不读 token） | `solid 2px rgb(79, 70, 229)` |
| PageUp / PageDown / ArrowUp 的 scrollTop | 2,591 → 2,224 → 2,591 → 2,551（一步就是一屏） |
| 静默态 `.log-idle`：tabindex / 自身溢出 | `null` / 0px（它不滚 ⇒ 不给 Tab 位） |

第 27 条是 2026-09-28 **页签调换**带出来的一个真实产品缺陷，判据落在这一趟而不是 V 趟：
调换之后默认页签是「运行结果」，用户先把整包 trace 拉完、再自己点开日志 ⇒ 面板**带着满屏行
第一次挂载**，而 `LogStream` 的钉底原来只挂在"行数涨了"那条路上（`prevLen = useRef(rows.length)`
⇒ 挂载这一拍 delta=0）⇒ 谁都不钉底。修之前的实测：`scrollTop=0 / max=2592`，视口停在
#001–#025 那最老的 25 行，而页脚仍写着「自动滚动已开启」—— 界面承诺的位置与实际滚动位置不一致。
修之后同一处：`top=2591 / max=2591 / #096–#120`。修法里"推两帧再钉"那一笔不能省
（当场钉会被虚拟器的测高回填夹一次，那一下夹动正好落进 `handleScroll` 的"用户上滑了"判据
⇒ 自动滚动被悄悄关掉，第一版就是这么红的）；而"已经钉过一次"那枚旗**只能在真钉下那一下才立**
（StrictMode 会把 effect 跑两遍，调度时就立旗 ⇒ 第二遍早退 + cleanup 把那一击 cancel 掉，
实测一次都没钉）。
⚠️ 这条判据**不能放 V 趟**：V 趟那份 trace 是 61 条同形状事件、被合并成 1 行
（页脚「已显示 1 行 / 61 条」）⇒ 面板没有可滚内容（`max=0`），同一个 `top >= max - 2`
在 0 上恒真。我第一版就是把它放在 V 趟，跑出来 `{"top":0,"max":0}` 全绿 —— 假绿。
**负面对照 NC-J**：把 `LogStream` 那次挂载钉底早退掉 ⇒ `ONLY=J` 56 通过 / 59 断言，
红的是「第一次点开就停在最后一条」（读数退回 `top:0/max:2592/firstSeq:1`）+
「前提读数：日志区确实停在底部」+「聚焦后 PageUp 滚得动」三条，后两条是这条缺陷的连带，
不是判据自己坏了。

两处口径写清楚，免得下次对不上账：① 走查报的"23 枚"是**真后端 + 17 条历史任务**在 724 视口量的，
这一趟走 mocks（列表 4 条）量到 14 / 15 枚 ⇒ 门槛因此写"成堆（≥8）"而不是抄 23；② 走查那次测的是
抽屉那半边，这一趟把 1440（宽屏收起）与 390（窄屏抽屉）两侧都量了，正好跨过 1180 那条断点。

**负面对照 EV-07-neg 分两条各跑一次**（归因必须分开，一次只摘一处）：只摘宽屏 `.is-collapsed`
那条 `visibility` ⇒ 55/58 三红，收起后 Tab 45 次**命中 19**；只摘窄屏抽屉那条 ⇒ 红两条、
都是同一个窄屏形状（`vis:"visible"` / Tab **命中 14**），宽屏那几条照常绿。
`右边缘 <= 0` 那条两种状态下都绿 —— 它恰好证明"看不见"不能当判据，这就是本趟存在的理由。

**PageDown 那条差点是自造的假红**：日志区刚挂载停在底部，第一下 PageDown 无处可去
（`before == after == 2591`）。改法不是放宽判据，而是先把前提量出来（`scrollTop 2591 / max 2591`
= 确实钉在底部），再按 PageUp → PageDown → ArrowUp 比位移；ArrowUp 那一下兼做"钉底逻辑不许把
键盘滚动顶回去"的复测。

**为什么用 `visibility` 而不是走查建议的 `inert`**：`inert` 要多一个 JS 状态跟 class 同步
（两处真源），React 18 的类型里也还没有它；`visibility:hidden` 在 CSS 一处生效，Tab 序与无障碍树
**同时**跟着可见性走，实测确实把整棵子树请了出去，而且不卸载 ⇒ 列表状态与已填的筛选一个字不丢。
代价照记：收起后该子树内的 CSS 动画会停（`prefers-reduced-motion` 那条全局规则本来就压掉 shimmer，
无感），命中测试也拿不到它（本来就该拿不到）。将来若要在收起态继续放动画或要量它的高度，再换 `inert`。

### 回放页选任务（K 趟，9 条断言）：`?id=` 是唯一状态源

上一版这一页有两个状态源（地址栏 `?id=` 与组件 `taskId`），点列表时先 `setTaskId(id)` 再
`setSearchParams({id})`，随后那句 `if (id === taskId)` 读的是**同一批更新里的旧闭包值**、恒假；
本该接手加载的跟随 effect 判据是 `idParam !== taskId`，两个 state 一起提交后也恒假 ⇒
**在回放页点一条别的任务，页面继续放上一条的轨迹，且不报任何错**。

三条改法，缺一不可：`gotoTrace` 只写 URL（列表点击 / 手敲 id / 重新加载三个入口全收敛到它）、
首屏那趟也只写 URL 不加载（否则和 effect 各拉一次）、**跟随 effect 与 `loadedIdRef` 比而不是与
`taskId` 比** —— 最后一条才是决定性的。

用例的形状：每条任务的 mock trace 盖一个只有它自己有的**钢印**（`stampedTrace(id)` 从请求 URL
里取 id），于是"页面显示的是谁的轨迹"变成可断言的事实 —— 每步都验
**「DOM 里的钢印 == 地址栏的 id」**，覆盖首屏回落、连点两条（两跳以上才排除"永远停在第一次"）、
地址栏直达、重复点当前条 = 刷新（比 `/trace` 请求次数，不比文案）。

**负面对照做过**：把比较对象换回 `taskId` 一行，② 立刻复现 —— URL 已是 `task-…e506`、
钢印还是 `task-…be11`。顺带翻掉我先前的一句判断：我一度以为"`gotoTrace` 重构已经顺带修好了
这个判据、负面对照摸不到"，实测不成立，只改入口不改成因是留半个坑。

### 从列表选中任务跑完要回填（L 趟，6 条断言）

`selectTask` 给 SSE 的 `onDone` 是 `() => undefined`，只有提交路径才补拉详情 ⇒
**从第二栏点开一条正在跑的任务，跑完后详情再也不拉，结果区永远停在「后端未回填
final_answer」** —— 一条成功的任务被读成没跑完。修法是把补拉抽成 `pullDetail(taskId)`
两条入口共用，并把关连接收进 `closeStream()`（订阅前、切任务前、取消时、新建时同一处）。

这一趟的两个口径值得记下来，都是踩出来的：

- **详情接口必须有状态机**。一开始我只把 `onDone` 换成真函数就断言"回填成功"，
  那是测了个寂寞：mock 从第一次就有答案，`onDone` 是不是 noop 根本看不出差别。
  现在改成 `streamed` 集合 —— SSE 被请求过之后详情才回终态 + 带答案。
- **句柄账要幂等**。`opened === closed` 才是"没有悬着的连接"；client 在终态帧和
  onerror 两条路径上都会 `close()` 一次，同一条关两次是无害的，但会把计数弄成假红，
  所以包装层只数第一次。跨 `await` 的**覆写**泄漏不在这里测 —— 那要有慢详情 + 连点两条
  才摸得到，由 P0-05 的 race 用例钉。

顺带挖出一个**应用侧脆性**（记在此，未修）：`STATUS_META[detail.status].terminal`
（`TaskLogPage.tsx:624`、`handlePhase:445`）对未登记的状态值没有兜底 —— 我一开始把 mock
写成 `status: 'succeeded'`（合法终态其实是 `done`），整页直接进错误边界。后端将来加一个
状态值就是全页白屏，值得单独补一档「认不出的状态按非终态渲染 + 如实显示原始值」。

**负面对照做过**：`onDone` 换回 `() => undefined` ⇒ 结果区立刻 `notBackfilled: true`，
两条断言红。

### 日志面板的重渲染账（M 趟，12 条断言）

`mergedAway(rows)` 曾是渲染路径上**唯一一处 O(全部行)** 的循环（5,000 行 = 一次 5,000 步
reduce），而面板自己每次重渲染都要跑它。修法是两层：`memo(LogStream)` 挡父级重渲染 +
`useMemo` 挡面板自渲染。这一趟就是分别钉这两层的，过程中翻案了三次，都值得记：

- **只断言"静置时渲染次数为 0"是不合格的守卫** —— 计数器坏掉时它同样成立。所以 M 趟双向：
  先证「改关键字 ⇒ mergedAway 必须重算」，再证「无关重渲染 ⇒ 一次都不许多跑」。
- **量组件提交数量不到 memo**：打开运行配置浮层那一次，提交数 +1 而 mergedAway 不动 ——
  那 1 次是面板**自己**的（行高由 `measureElement` 动态测，旁边布局一变就可能自渲染）。
  判据因此换成 `mergedAway` 的调用次数（插桩在 `src/utils/logRows.ts`，一次属性自增；
  本项目没有 `src/vite-env.d.ts`，`import.meta.env.DEV` 过不了 tsc，所以没判环境）。
- **"用浮层当 ②" 是假绿**：它测到的是外层 `memo(LogStream)`，摘掉 `useMemo` 也不红。
  换成**滚轮滚动面板**（rows 引用不变、组件必然重渲染）才是 `useMemo` 唯一挡得住的场景。
  负面对照做了：摘掉 `useMemo` ⇒ 一次滚动触发 **6 次** `mergedAway`（24 → 30）。
- **mock 接线本身要被断言**：`**/api/tasks/*` 匹配不到带 query 的 trace URL，硬塞进一个
  handler 分流会让 trace 悄悄退回默认 13 条，面板从"240 行可滚"变成"11 行到底"，滚动
  断言全部空转。现在开头三条（`total === 240` / spacer > 一屏 / 常驻 ≤60）先钉住接线。
- **块注释里别写 glob**：`/* ... **/api/tasks/* ... */` 里的 `*/` 会把注释提前闭合，剩下
  半句变成真代码 —— 症状是 `ReferenceError: api is not defined`，且 `node --check` 不报。

提交计数用的插桩在 `TaskLogPage.tsx` 的 `<Profiler id="logstream">`：计 **commit** 而不是
render（StrictMode 双跑渲染不会把它翻倍），且生产构建里 React 不调用 `onRender`，所以不带进 dist。

### 迟到响应不许盖别人（N 趟，7 条断言）

详情 + 轨迹是两个请求，而轨迹**串行分页**（`api/client.ts` 里 ≤10 页 × 50 条逐页 await），
慢的一条要跑满好几个 RTT ⇒ 先点 A、立刻点 B，A 后到就把 A 的答案和日志盖在 B 上。
这是 P0 里唯一"错了也看不出来"的一类：界面不报错、不闪烁，只是内容不对。

修法 = 两道闸，都在 `selectTask`：① 每次选择领一个号（`reqIdRef`），回来号不对整包丢掉；
② 结果只许落在 `prev.taskId === taskId` 的时候。`pullDetail`（流关闭后的补拉）**不领号** ——
补拉不是一次新的用户意图，领了反而会把已被切走的任务的号刷成最新、绕过①。

用例的三个要点：

- **慢的是"第一个被请求的 id"**（`firstId`），不是我以为的某一条：这样才保证它一定后到。
  两条都给终态（不订阅 SSE），把变量收窄到"迟到响应落不落地"。
- **答案必须切到结果页签再读**。第一版在日志页签读 `.answer` 拿到空串，于是
  "空串不包含迟到那条的文案" 恒真 —— 一条看起来在断言、实际是装饰品的守卫。
  现在先判 `ans.length > 0`，再拿页面自己认领的那枚 taskId Chip 当基准。
- **"谁的日志"用条数当指纹**：慢的那条给 60 行、快的给 3 行，页脚
  「已显示 N 行 / M 条」一比就看出盖没盖。

**负面对照做了两级**：只摘②（`prev.taskId` 那道）不红 ⇒ 说明**号才是主闸**；
两级一起摘 ⇒ 现场直接打出「页面认领 `…e506`、答案正文却是『答案 属于 `…be11`』、
日志从 3 条变成 60 条」，报告 A2 那句"张冠李戴且不报错"被抓了个现行。

### 断流不等于任务结束（O 趟，17 条断言）

旧客户端把 `EventSource.onerror` 直接当成"任务结束了"：关掉流 + 调 `onDone()` ⇒ 徽标停在
「运行中」+「实时推送中」一直呼吸，再也不会重订 —— 用户读到的是"卡住"，而后端还在跑。
报告 A3 的那一条。现在 `api/client.ts` 把两件事分开：`done/failed/canceled` 三种**终态帧**
才走 `onDone`；传输层错误走退避重连（1s / 3s / 9s），并回调 `onStreamState('lost' | 'restored' | 'failed')`。
状态与文案都在运行条下面那一行 `.stream-note` 里说，**绝不改任务状态**（任务是否还在跑由补拉详情确定）。

用例两段，各自钉一件事：

- **① 断流 → 重连 → 对账**：SSE 每条连接都给同一批"活着但没有终态"的帧 ⇒ 连接必然关闭。
  断言 `sse ≥ 2`（真的重连了）、`note` 含"中断"、`trace` 计数在断流后增长（按 `event_seq` 补拉），
  以及 console 里 `same key` 报错为 0（后端每连接各自从 0 起算 seq，`maxSeq` 必须放在连接**外面**）。
- **② 三次都接不上 ⇒ 认输**：SSE 一律回 500。断言**连接数恰好 = 4**（首连 + 3 次重试，
  不许无限重试打后端），文案说"自动重连 3 次未成功"，且**不把断流说成终态**。

三个坑：

- **瞬态读数必须在事件当时采**。"实时连接中断"那一行 1 秒退避后就被撤下，事后再查 DOM 只会
  查到"没有这行"，于是断言退化成"空串里不含 X"——恒真的装饰品。现在点任务**之前**挂
  MutationObserver，把它每次出现时的文本 / 盒子 / 字色钉进 `window.__noteSeen`
  （`const` 不挂 window，evaluate 里要显式写 `window.`）。
- **只报字色不够，要报盒子**：`color` 读到 `rgb(180, 83, 9)` 也可能是一行高度 0、
  或者被运行条 overflow 裁掉的行。所以量 `box[1] ≥ 16` + `insideRight/insideBottom ≥ 0`。
  实测两行断流文案都是 1024×17、对比度 5.02。
- **route 分层的老账**：`**/api/tasks/*` 单层通配**匹配不到带 query 的 trace URL**，
  把 trace 分支塞进它内部 = 计数永远 0，而 0 看起来像"没发生对账"。所以 trace 那条单独注册、
  且注册在**后面**（后注册的先匹配），并先断言基线 ≥ 1 再断言增长。

对账只在 `restored` / `failed` 做，`lost` 时**不拉**：刚断的那一刻后端还没把断口之后的事件
落完（契约是先落库再发布 ⇒ 那时能拉到的就是屏幕上已有的一份），白跑一个 RTT；三次退避全失败时
若每次 `lost` 都整包重拉，就成了对一个正在抖的后端的请求踩踏。②里那三条 trace 计数
（`基线 ≥1` / `断线期间零增长` / `认输时恰好 +1`）钉的就是这个。

### 取消的四种桩、三种说法（P 趟，37 条断言）

报告 B13：`cancelTask` 是 `await fetch(...)` 一把梭，不判 `res.ok`。于是 200（真取消了）/
409（早就是终态，没得取消）/ 404（这条不存在）/ 网络没送达 在前端是同一句话，而
`handleCancel` 无论哪种都本地把徽标改成「已取消」—— 任务还在跑，屏幕上写着已取消。
现在按后端的 `detail.code`（`api/errors.py` 的统一信封）或 HTTP 状态分口径，被拒时补拉一次
详情让徽标落到服务端真值，并且**先问后端、再关流**。

**四档桩、三种说法**是刻意的：`server500` 和 `network` 说的是同一类话（"没送达 + 可能仍在
运行"），因为后端没办成和根本没收到，对用户是同一件事；但它们钉住的代码路径不同 ——
`network` 走 `fetch` reject，`server500` 走"响应回来了、状态码不是 2xx 且 code 不在拒绝名单里"。
少一档就有一档分支没人看过。

| 档位 | 桩 | 钉住的行为 |
|---|---|---|
| `ok` | 200 + 合法 `CancelResponse` | 徽标「已取消」、不弹错误条、终态后取消按钮消失、不再收帧 |
| `conflict` | 409 `task_already_finished` + 详情同时改成 done | 说「取消未生效」并带出后端原话；**不许**出现"可能仍在运行"这种反话；徽标用服务端真值「成功」而不是本地的「已取消」 |
| `server500` | 第一次 500 `internal_error`，第二次 200 | 说「取消未送达」并带出后端原话；**不许**说「未生效」（那是明确拒绝的口径）；徽标与取消前一模一样（`运行中`）；第一次不自动重试；**再点一次真能取消掉** |
| `network` | `route.abort()` | 说「取消未送达；任务可能仍在运行」；徽标不许变「已取消」；按钮还在；**那条流没被白掐** |

`network` 那一档的"没被白掐"是这趟的正主：重连上的连接**晚 1.2 秒**才给一帧心跳 ——
点取消时它还在路上。取消失败后如果客户端还留着这条流，这帧就会落进日志（读数从 5 涨）；
旧顺序（`closeStream()` 在 `await` 之前）已经把它关了，这帧永远到不了。

⚠️ 「断流那一行消失了没有」**不能**当证据：假后端的响应体是一次性给完的，`'restored'`
之后紧接着就是下一条 `onerror ⇒ 'lost'`，撤下与挂上之间只差几毫秒，任何采样都抓不到那个
空窗（O 趟同样因此改用「在场 + 连接计数」）。这里改钉两件可持久的事：连接数 ≥ 2、事件数涨了。

`server500` 那一档补的是「必须还能再点一次」这句话：旧版只在 `network` 档断言"按钮还在"，
而**按钮在 ≠ 点得动**。这一档第二次点走 200 分支（桩按 `cancelHits` 计数切换），于是
"再点是唯一补救"成了能读出来的结果：徽标真的落到「已取消」、累计恰好两条 cancel 请求、
成功后不再留着上一条失败 toast。

治掉的一颗死桩：旧 B 趟把 `/cancel` 塞在 `**/api/tasks/*` 的 `if` 分支里"一律回 200"，
而 Playwright 的 `*` **不跨 `/`** ⇒ 那个分支从来没命中过，真正答取消的是 `installMocks` 里
那条同样一律 200 的桩。两条加起来的效果是**"取消永远成功"在假后端里不可达** ——
409 说反话这类缺陷无论怎么点都不会显形。P 趟把取消单独注册成能改状态码的三段式 glob。

**负面对照做了两级**：① `cancelTask` 改回"不判状态码" ⇒ 409 那档两条翻红
（toast 是空串、徽标成了「已取消」）；② 只把 `closeStream()` 挪回 `await` 之前 ⇒
`network` 那档的"流没被白掐"翻红（读数停在 `mid=5 / post=5`）。各红各的、互不掩盖。

⚠️ **待捕（未修，先记账）**：`409` 那一档曾出现一次未捕获的
`Failed to execute 'removeChild' on 'Node'` —— 复现率 **1/22 次开页**（2026-09-24 全量一趟），
同一趟隔离单跑 `ONLY=P` 是 **0/2**；本轮（2026-09-25）P1-01 收口前跑了**四次**全量
（每次 28 次开页、最后一趟 601/601），四次都没再见到（本轮没有单独重跑 P 趟）。
猜测的时序是 AntD Popconfirm 的 portal 拆除与 `pullDetail` 把记录翻成终态、连带卸载那颗
「取消」锚点按钮抢在同一帧，但**没有现场就不改**。每趟都带 `无 pageerror` 断言，
下次复现即有读数；P1 全绿后若仍复现再立案排查。

> **2026-09-25 追加：上面那三个分母（22 / 2 / 28）全部来源不明**。它们是手数的，而加一趟就漂一次。
> 现在探针收尾自己打印开页数，一趟全量实测是 **开页 46 / 导航 51** ⇒ 当时那句"1/22 次开页"
> 的真实分母应是 46 上下，复现率比记着的那个更低（不是更可疑，是更偶然）。
> 旧数字照原样留着不改写 —— 那是当时那次观察的记录；下次复现请按**新打印的那个分母**记。

⚠️ **本轮已修的一枚探针 flake（不是产品缺陷）**：C 趟「钉底后高度回填不误关自动滚动」
在全量第三跑读到 `before:false`，而 `ONLY=C` 连跑两趟全绿。查下来是**读数抢在 React 提交之前**：
页脚那句「自动滚动已开启」是 `setAutoScroll` 之后的产物，旧代码只等一次 rAF。
改法分两种口径 —— **前件**（重新钉底要把开关打开）轮询等到位（等不到就是 fixture 坏了，
判红是对的）；**被测那一读**用固定沉降窗（三帧 + 120ms），**绝不轮询"它有没有变回 true"**，
那会把断言等成恒真。这一条与 C 的负面对照无关，属护栏自身的稳定性，随 P1-01 一并提交并注明。

### 后台标签不许把徽标永久留在「探测中」（Q 趟，7 条断言）

`useHealth` 里那句 `if (document.hidden) return` 跑在 `try/finally` **之前**：页面在后台被打开
（新标签、最小化、从别的应用唤起）时第一次探测直接早退，`setLoading(false)` 根本没跑 ⇒
顶栏停在「探测中」；而 30 秒一次的 tick 每次都在同一处早退，浏览器在后台还会把计时器压到
分钟级 —— 用户切回来看到的是一枚永远不动的徽标（N4 + B11）。

修法两半，缺一不可：**hidden 时照常不发探测**（没测过就不许编结论，既不能写「后端未连接」
也不能假装「服务正常」），但 `visibilitychange` 必须立刻补拉一次，不等下一个 30 秒刻度。

⚠️ 这一趟的全部前提是**把 `document.hidden` 变成可控开关** —— Playwright 的页面永远是
visible，不接管这两个属性就根本造不出"在后台被打开"那条路径，整趟会是七条恒真的漂亮断言：

```js
window.__hidden = true;                                  // 只能挂 window（evaluate 里的 const 不挂）
Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.__hidden === true });
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (window.__hidden ? 'hidden' : 'visible') });
```

必须 `configurable: true`（盖的是 `Document.prototype` 上的 getter），且用 `addInitScript`
抢在应用脚本之前。切回前台由测试自己 `document.dispatchEvent(new Event('visibilitychange'))`
触发 —— 浏览器也就是这么发的，React 那侧只监听事件，不关心是谁派的。

断言的顺序是"前件 → 现象 → 反向"：先证明确实在 hidden（`document.hidden === true`）、
再证此时**一次探测都没发**（`healthHits === 0`，这条同时是"没白跑请求"的验收），
然后才允许判徽标文案；切回来之后判 `服务正常` + `healthHits ≥ 1`。
**负面对照**：把补拉那句事件绑成空函数 ⇒ 切回前台 1.2 秒后仍是 `探测中 / healthHits=0`，
两条翻红 —— 这正是缺陷本尊在探针里的样子。

### Composer 的三个设置：点得动，还得说得出（R 趟，27 条断言）

报告 C7 的原文是「`.switch-row` 用 `label` 包 AntD 的 Switch，点标题文字不翻」，给的根因是
「Chromium 不把 label 的点击代劳给内部那颗 `button[role=switch]`」。**这个根因不成立**，
而症状是真的 —— 两轮负面对照把它拆开了：

- 对照 A：实现就是 `label` 包 Switch、**不加任何转发 `onClick`**，只要字段注册到位 ——
  R 趟 16 条全绿（当时的条数；下面「曾经是假绿的」那一节说明这 16 条为什么仍算漏），
  其中「点标题文字就翻开关」的读数是 `before=true / after=false`，
  且前件实测 `leftOfSwitch=true`（点的位置在开关左边缘之外，不是又点了一次轨道）。
  ⇒ Chromium 确实会转发，label 从来不是问题。
- 对照 B：把注册摘掉（回到旧写法：只有 `initialValues` + `checked={Form.useWatch(...)}`）——
  同一趟当场 **5 条翻红**：`点标题文字` 和 `点开关本体` 双双 `before=true / after=true`
  （**旧版点哪儿都没反应**，热区根本没轮到出问题），请求体里 `use_tools` 成了 `undefined`，
  而 RAG 明明开着却照样发出 `enabled_tools: ["calculator","code_exec"]`。

真根因是 **rc-field-form 的 `getFieldsValue()` 只收已注册字段**：那三项没有 `Form.Item name`，
于是 `Form.useWatch` 恒为 `undefined`（界面冻在 `?? true` / `?? 3` 那层兜底上），
`onFinish` 的 `values` 里也压根没有这三个键。实发请求体修之前长这样（一次真实提交的原样）：

```json
{"task":"…","enabled_tools":["calculator","code_exec"]}
```

`use_tools` 与 `max_iterations` 整个丢掉（退回后端默认），`useRag` 恒 `undefined` 又让那个
三元走了"排除知识库"那一支 —— **从界面提交的任何任务都检索不到知识库，而界面上那颗 RAG
开关显示的是"开"**。一句错都不报。这类坑不会崩，只会让数字与行为悄悄不对。

所以修法是一条：三项统统交给 `Form.Item name=…` 注册（两颗开关 `valuePropName="checked"`，
迭代框加 `normalize={(v) => v ?? 3}` 兜住清空后的 `null`），外层保持原生 `label`。
`span` + 手写转发 `onClick` 那版已经撤了 —— 它治的是不存在的病，还多留一处"忘排除开关内部
就翻两次"的写法风险。

R 趟的口径是**界面说的必须等于发出去的**：除了点得动（含键盘 Space），它自己注册一条
`POST /api/tasks` 的路由把请求体抄下来（后注册的 route 优先，抄完再回一份合法 ack），
然后逐键对：`use_tools=false` / `max_iterations=7` / RAG 开着时 `enabled_tools` 这个键
**不该存在** / 关掉后才出现排除清单。少抄一次 body 就先断言 `bodies.length === 1`，
免得后面全部退化成对着空对象讲漂亮话。

**上面那段"逐键对"曾经是假绿的（2026-09-25，用户真实 Edge 实测揭穿）**

用户在真实浏览器里提交 `"1+1"`，抓到的请求体是 `{"task":"1+1","use_tools":true}` ——
`max_iterations` 整个不见了，而同一屏右下角明明写着「3 轮」。R 趟当时 16 条全绿。

为什么抓不到：**我自己写的那档用例，在提交前点开过「运行配置」弹层。** 点开的瞬间
InputNumber 挂载 ⇒ 字段注册 ⇒ `onFinish` 的 `values` 里就有了。探针替用户做了一次他
不会做的操作，把缺陷当场缝上了 —— 这类假绿不是断言写错了，是**前件被探针自己改掉了**。

真根因是「**注册 ≠ 挂载**」，比第一轮那三条「没有 `Form.Item name`」更进一层：字段注册了
也不一定在，因为 AntD 的 Popover / Tooltip 内容是**懒挂**的（首次打开才 mount）。
`handleSubmit` 用的是 `onFinish` 递来的那份**过滤视图**，缺的就是没挂过的字段。
修法是取整份 store：`form.getFieldsValue(true)`（`initialValues` 也在里面，与 `.cp-hint`
那行读数同源 —— useWatch 读的就是这个 store），界面读数与实发请求体合成一份口径。

两条反假绿的硬规矩，已经写进 R 趟 ③（新增 9 条）：

- **比键集合，不比单个键**：`JSON.stringify(Object.keys(body).sort()) ===
  '["max_iterations","task","use_tools"]'`，少一键多一键都红。原来只 `expect(body.use_tools)`
  这种点验，永远看不出"少了一个键"。
- **必须有一档"用户什么都没碰"**：单独开一个 context、单独开页（挂载状态不沿用上），
  全程不点弹层，前件先实测 `.ant-popover` 数为 0、`.ant-input-number` 数为 0、界面读数是
  「3 轮」，再提交。默认值最容易丢，因为没人碰过它 ⇒ 没人挂载过它。

**顺带纠正两处契约口径**（用户提问里的 3 个假设，实测都不成立，见 `api/schemas.py:92-110`
与 `src/api/client.ts:79-86`）：

- 请求体里**没有 `use_rag` 这个键**，后端 `TaskSubmitRequest` 也从来没有。前端表达 RAG 的方式
  是 `enabled_tools`：开着 RAG ⇒ **不发** `enabled_tools`（这个键缺席就是"全开"），关掉 ⇒ 发
  `["calculator","code_exec"]` 那份排除清单。所以"缺 `use_rag`"不是缺陷，"缺 `enabled_tools`"
  恰恰是 RAG 开着的正确表示。R 趟 ③ 现在把这个键集合钉住，就是为了下次不再靠猜。
- 迭代框在 store 里叫 `maxIterations`（camelCase），下划线那个 `max_iterations` 是
  `submitTask()` 出网前的映射结果 —— 查注册问题时别把两名当成两个字段。

负面对照 N5（跑完已撤）：`handleSubmit` 改回用 `onFinish` 递来的 `values` ⇒ R 趟 ③ 当场
**2 条翻红**（`键集合` 读到 `["task","use_tools"]`、`max_iterations` 读到 `undefined`），
①② 与点得动那几条形不变 —— 缺陷只在"没点过弹层"这一档现身，正如它在用户那边。

### 导出 CSV：端到端真的落地一个文件（S 趟，11 条断言）

报告 B9 指出 `downloadCsv` 少了两步：anchor 没进 DOM 就 `click()`、`revokeObjectURL` 同步调。
后果不是报错，是**在某些浏览器上点了没反应**（Firefox/Safari 不理脱离文档的 anchor；
Safari 里同步 revoke 会把下载扼杀在起飞前），而且控制台干干净净。

实现细节钉在 `format.test.cjs` 里（DOM 替身，纯 node）：`click` 那一刻 anchor 必须在
`document.body` 里、`revoke` 必须还没跑、顺序必须是 `append → click → remove`、
`revoke` 只能被排进宏任务一次。那是"代码写对了没有"。

S 趟补的是另一半：**用户真拿到文件**。`page.waitForEvent('download')` 要先挂上再点
（反过来会漏），然后读 `dl.path()` 的字节：文件名 `retrieval-groups.csv`、首字符是 BOM
（`0xFEFF`，Excel 才按 UTF-8 读）、表头 10 列一字不差、数据行列数 = 表头列数
（证明转义没漏，没有单元格藏着裸逗号）、导完 DOM 里 `a[download]` 归零（不攒无主 anchor），
再导一次仍然成功（延后的 revoke 各管各的 blob）。前件先断言导出按钮在场，
否则那一串等待只是一次安静的超时。

**⚠️ 2026-09-29 修正：上面那三条（BOM / 表头 / 行列数）在 S 趟里从未参与判定。**
`check(name, cond, got)` 的 `cond` 走 `Boolean(...)`，而这三条写成了
"被测值放第二参数、期望值放第三参数"（`charCodeAt(0)` / `lines[0]` / `split(',').length`）
⇒ `Boolean(65279)`、`Boolean('bm25_weight,...')`、`Boolean(10)` 恒真，
**README 那句"首字符是 BOM、表头 10 列一字不差"其实一直是空口的**。修法是把比较写回第二参数
（期望值逐字没动），并给"行列数"那条补上前件 `lines.length >= 2`
（只有一行表头时 `lines[1]` 是 undefined，`.split` 会抛异常——那是"崩"不是"红"，判据要能分）。

两组负面对照，都是改**产品代码**再复跑（不是改判据）：

| 改坏的地方 | 复跑读数 | 归因 |
| --- | --- | --- |
| `format.ts:227` 去掉 BOM | **9 通过 / 11 断言**；✗ 正文以 BOM 打头（`{"code":98,"hex":"0x62"}`）、✗ 表头那 10 列一字不差（拿到 `"m25_weight,..."`） | 两条一起红：判据本体是 `text.slice(1).split('\r\n')`，**它预设了 BOM 占一格** ⇒ 掉 BOM 会把表头首字符也吃掉。这两条有耦合，别当成两个独立信号 |
| `format.ts:226` 给数据行多塞一格 `'含,逗号的格子'`（表头不动） | **10 通过 / 11 断言**；✗ 数据行列数 = 表头列数（`{"headerCols":10,"dataCols":12}`） | 单独红这一条，BOM 与表头仍绿 ⇒ 归因干净 |

**这一条到底兜什么，要说准**（免得下一个人以为整个 CSV 没人管）：
`format.test.cjs:140` 早就在纯函数层钉着 `charCodeAt(0) === 0xfeff` 与那一串逗号/引号转义，
所以"BOM 丢了""转义漏了"这两种坏法**会在 `format.test.cjs` 变红**，只是不会在 S 趟变红。
S 趟修好之后独有的一格是**这一页的表头那 10 个列名与列序**——`format.test.cjs` 喂的是自造表头
（`a,b`），全仓此前没有任何地方钉过 `bm25_weight…vector_score_mean` 这串；
外加"页面侧表头列数 == 数据行列数"这一格（有人往 header 加一列而忘了 rows，只有这里会红）。

**这三条的最终定位（已拍板：保留，既不删也不算"重复钉"）**：单元层 `format.test.cjs:140-141`
钉的是"实现怎么写"，探针层这三条钉的是"**用户真下载到的那串字节**"——同一个 `downloadCsv`
中间隔着真 blob 与真下载事件，两层都要有才算端到端二次确认。红线一（不许恒真）在这里的执行方式
就是"把比较写回第二参数"，而不是"既然上层钉过就撤掉"。

### 运行条：每秒跳秒不许变成每秒播报（T 趟，12 条断言）

报告 B2：整条 `.runbar` 挂着 `role="status"`。它里面有「最后一条日志 Ns 前」——每秒重写一次
文本。live region 的语义是"内容变了就念出来"，于是读屏软件每秒被打断一次，念的还是这一行里
唯一在动的那个废数；用户真正想知道的"从 Planner 走到 Executor 了"反而被淹在里面。

修法是把**显示**与**播报**分家：`.runbar` 不再是 live region；新增一枚常驻的
`<span className="sr-only" role="status" aria-live="polite" data-live="runbar">`，
文本只由「状态 + 当前节点」决定（`运行中 · 当前节点 Planner`）。两个细节别踩：

- region 必须**先在场、后变文本**。跟着文本一起挂载的 live region，多数读屏根本不理 ——
  所以 T 趟第一条断言在**还没提交任务**时就要求这枚节点已经在 DOM 里（此时它是空串）。
- 播报文本与屏幕读数是同一个来源（`statusMeta.label` + `NODE_META[currentNode].label`），
  断言直接拿徽标文本与步骤条 `.is-active` 的标签拼出来比对，不写死中文 —— 否则改文案就把护栏
  改成了噪音。

⚠️ 造运行态这一步踩过坑：`installMocks` 默认的详情是**已完成**的 fixture，直接提交会一秒内
落终态 ⇒ 步骤条整排变绿、`.step.is-active` 永远等不到（第一版在这行超时 20s）。另外
`.runbar-last` 不能当前件 —— 「等待第一条日志」那一支渲染的是同一个 class。现在沿用 P 趟那套：
详情恒 `running`，SSE 第一口 400ms 后给 `runningFrames()`，第二口挂住不 settle
（挂住 ⇒ 没有 `'restored'` ⇒ 不触发对账 ⇒ 观察窗里除了跳秒什么都不该动）。

断言的形状是"前件 → 现象 → 反向"：`MutationObserver` 当场数 3.2 秒 ——
跳秒那枚变了 **3** 次（前件在场），而**任何** live region 的文本变化 = **0**。
最后一句是关键：只数播报口等于没数，`role="status"` 加回 `.runbar` 时动的不是它。
然后再取消一次（一次真的状态变化）⇒ 播报恰好变 **1** 次、念得出「已取消」——
证明这不是"把播报删了事"。

**负面对照实测**：把 `role="status"` 加回 `.runbar` ⇒ 12 条里当场 3 条翻红，
`other` 的读数逐字打脸：`runbar=运行中实时连接中断，正在重连（任务可能仍在运行）◆Plann…`
连着三条 —— 每秒一条、每条整条运行条。缺陷本尊在探针里的样子。

### 答案子树不跟无关重渲染（U 趟，13 条断言）

报告 A4①：`AnswerView` 没有 `memo`。它里面那串 `useMemo` 只挡住了**解析**
（`findRepeats` / `findMathBlocks` / 裸序号分块），挡不住 react-markdown 自己那棵 element 树 ——
父级（结果页签所在的 `ResultPane`）任何一次与答案无关的重渲染都会把整篇答案（宽表 + 重复段 +
公式区）重建一遍。修法就一层 `memo`：答案文本落地后不再变，浅比较正好够用，不需要自定义
`areEqual`。

⚠️ 这一趟最值得记的是**instrument 选错了会把"修好了"读成"没修"**。第一版判定读的是
外面那枚 `<Profiler id="answer">` 的提交数，结果那几下无关交互把读数推到 `3 → 7`，而答案的
DOM 节点始终是同一个（`sameNode=true`）—— 父级每重渲染一次，Profiler 自己就是一次 commit，
**memo 挡得住子组件，挡不住 Profiler 被重新渲染**。所以判定改成组件函数体自己数的
`__renders.answerRenders`（与 `utils/logRows.ts` 里那枚 `__mergedAway` 同一套插桩口径，
P1-01 起两枚计数统一收进 `src/utils/renderLedger.ts`），Profiler 的数只打印。

**触发器在 P1-01 之后换过一次**，这是本节最容易读错的地方：以前用的是切页签，但结果页签从
P1-01 起**按需挂载** —— 切走是卸载、切回来是重挂，计数器必涨，那个触发器量的已经不是 memo
而是挂载（卸载归 V 趟）。现在的触发器是**展开 / 收起引用列表**：它改的是页面 state
（`citationsOpen`），整页与 `ResultPane` 都重渲染，而答案文本一个字没变 —— 恰好就是 A4①
报的那个真实场景。fixture 也因此换成 `citedTrace(60)`（181 条引用），折叠按钮才存在。

| 场景 | render 计数（判定用） | Profiler 提交数（只打印） | 整页 `page` |
|---|---|---|---|
| 换一条答案不同的任务（含重新点开结果页签） | 2 → 4 ✅ 必须涨 | 1 → 2 | 未记 |
| 静置 3.2 秒（终态、没有计时器） | 6 → 6 | 3 → 3 | 22 → 22 |
| 展开 + 收起引用（答案 props 没变） | **6 → 6** | **3 → 5** ← 拿它判定就误判 | 22 → 26 |
| 同上，但 `memo(…, () => false)`（负面对照 N3） | **24 → 32** ⇒ 翻红 | 12 → 16 | 40 → 48 |

负面对照选的是 `areEqual` 恒 false 而不是删掉 `memo`：效果就是修之前的行为（每次父级渲染
都跑函数体），却不改 import、不碰闭合括号，一次编辑进、一次编辑出，tsc 全程干净。
`+8` 而不是 `+4` 是 StrictMode 把函数体双跑，与 M 趟记的同一个成因。

双向断言的形状沿用 M 趟：**先证计数器数得到**（换答案必须涨），**再证无关的重渲染数不到**。
少了前一步，"零增长"在计数器坏掉时同样成立。触发器还翻过一次车：更早想点「展开全部引用」时
默认 trace 的引用只有个位数、那枚按钮根本不渲染 —— 前件读到 `null` 才暴露"那三下点的是空气"。
本轮又踩到一条同族的：`selectTask` 里有 `setTab('log')`（切任务把页签拨回日志是刻意的），
所以每次换任务后必须重新点一次「运行结果」，否则 `.answer` 压根不在 DOM 里 ——
上一版读到 `t1 = null` 时以为"答案没换"，其实是面板没挂。

### 选中态落到 URL 与回前台补拉（W 趟，36 条断言）

**现象**（用户实测，必现）：提交一条会跑 30 秒以上的任务 → 切到别的标签页 → 30 秒后切回来 →
左侧列表照旧「运行中 · 42 秒前」，**主区却是空态「还没有日志」、日志页签计数 0**。
必须手动点一下列表才恢复。

**诊断的三条**（先排除，再定案 —— 三条候选里只有第一条成立）：

1. **state 丢失 = 成立。** 「在看哪条任务」从头到尾只活在 `TaskLogPage` 的 `useState` 里
   （`record` + `useLogBuffer` 的行缓冲），`/tasks` 这条路由上**没有任何持久落点**：
   全站 localStorage 只写主题与列表折叠两枚键。而左侧列表是**进页面重新拉的** ⇒
   文档一旦被重建，列表有新数据、主区回到初始态。
2. **visibilitychange 副作用 = 排除。** 全站只有一个 visibilitychange 监听
   （`AppShell.tsx:187-194`），它只调 `fetchHealth()` 改那枚健康徽标，碰不到 record/events。
   实测：真·覆写 hidden 持续 45 秒再切回，行数 13 保住、页签计数没动、空态没出现。
3. **SSE 边界 = 排除。** `client.ts:216-229` 的 `onerror` 只做"关流 / 退避重连 / 报 lost|failed"，
   从不写 record；`streamHandler` 只写 `streamNote` 一个字符串 + 断口对账。
   上面那次 hidden 实验恰好覆盖了"退避 + 认输"整条路径，视图一行没掉。
   而 `record` 全部 8 个写入点、`events` 全部 5 个写入点里，能同时把两者清空的只有 `startNew` ——
   它的调用点是「＋ 新建任务」那颗按钮，没有任何 effect 或定时器走这条路。

**复现的那一步**：`page.reload()`，别的什么都不动 ⇒ `行 13→0`、空态从 null 变「还没有日志」、
页签「实时日志 13 → 0」、运行条「运行中 → 尚未运行」、列表照旧有内容（相对时间跳到「51 秒前」= 刚重拉过）。
逐字对上用户报的三个读数。

**重建来源不硬编。** 试过用 `routeWebSocket` 以 `code=1006` 关掉 Vite 的 HMR socket 想看它自己
`location.reload()`（那条路确实存在：`vite/dist/client/client.mjs:552-563`，非 clean 关闭 ⇒
探活 ⇒ reload），**没触发** —— Playwright 造的 close 被判成 clean，而 Vite 第一行就是
`if (wasClean) return`。Edge 侧同理，30 秒不到冻结阈值，这台机器模拟不出它的私有能力。
所以只报"文档被重建了"，来源留在账上（下面的 30 秒口径就是给用户自己分的）。

**给用户自己测的 30 秒口径**（不阻塞修复，哪种来源都能分）：

```
切走前在 DevTools Console 跑：sessionStorage.setItem('t0', Date.now())
切回来跑：Math.round((Date.now() - sessionStorage.t0)/1000) + 's 墙钟 vs 文档已活 ' + Math.round(performance.now()/1000) + 's'
```

两个数明显不等 ⇒ 文档被重建过（F5、HMR 全量重载、Edge 丢弃/恢复标签都算）；
相等而主区仍空 ⇒ 回来找我们，那说明是应用内路径，上面的排除就得重翻。

**修了什么**：

- `?task_id=` 成为"谁被选中"的唯一状态源，写入点三处（提交 / 点列表 / 新建清空）一律 `replace: true`；
  跟随 effect 是**唯一的加载器**，走现成的 `selectTask(id, {fromUrl:true})` ——
  详情 + trace 整包回填 + 非终态补订阅，恢复路径不新写第二套。
- `loadedIdRef` 记"屏幕上是谁"。**两个坑都实测过**：
  (A) `selectTask` 的身份随 `history` 每次都变，而 `refreshHistory` 在阶段转变、每次
  `pullDetail` 的 finally、提交后、顶栏刷新都会跑 ⇒ 少了守卫就是"每刷一次列表把当前任务
  重选一遍（清屏 + 重订 SSE + 再打 10 页 trace）"；
  (B) `loadedIdRef.current = taskId` 必须写在 **await 之前**，写在响应之后就留出空窗，
  跟随 effect 会再拉一次（症状：同一条任务两份 trace 共 20 个请求，而界面一切正常）。
- 回前台补一次账（P1-06 合并进来做，两条都动 visibilitychange，分开做会冲突两次）：
  `pullDetail(id, { withEvents: true })` 一次请求两件事。
  ⚠️ 拆开写的那版实测会把**同一条 trace 连打两次**（切回那一下读数 详情 1 / 轨迹 2），
  而 trace 是串行分页的，等于每次切回白付一倍后端。
  ⚠️ 不设"streamNote 非空才补"的条件 —— 已拍板：要防的那一档恰恰是"静默停更但没报错"。
  ⚠️ `wasHidden` 那枚守卫保留：从没离开过就不补，首屏不白发一轮请求（W 趟 ① 钉着）。
- `document.title` 前面加 ●（running 时，P1-06 后半）：切走之后页面里的字全都读不到，
  标题栏是唯一还在页面外说话的地方。基线从 `document.title` 现取、不写死字面量，卸载时还原。
- 未知 id 不许装死：`LogStream` 加 `loadError`，空态直接说「任务载入失败：LOAD_FAILED」+ 下一步。
  ⚠️ 只认 `LOAD_FAILED` 这一个码 —— `applyDetail` 也会把"任务本身失败"写进同一个
  `record.error`（码是状态名，如 FAILED），那是任务的结局、不是这一屏没载进来。
  另一处顺序坑：这一支必须排在 `running` **前面**判 —— 失败时 record 停在 queued 占位上、
  `running` 为真，否则读到的是「已订阅，等待首个节点事件」，一句会让人一直等下去的谎话。

**两页参数名不同是故意的**：`/trace` 用 `?id=`（选中的是**轨迹**），`/tasks` 用 `?task_id=`
（选中的是**任务**）。统一成一个字面 `id` 看着整齐，实际把两种语义糊成一个 ——
将来谁"顺手统一"，/trace 那些分享出去的链接参数就指向一个不再存在的意思。**想统一先读这句。**

**W 趟 36 条的档位**（页签调换那一轮从 29 加到 36：② 与 ④⑤⑥ 各补了"落在哪一屏"的前件与反向读数）：① 无 query 不自动选（含"标题不许带点"、首屏不白发请求）② 提交写 URL 且
**不回头重拉**（详情 0 / 轨迹 0 —— 这条就是坑 B 的守卫）③ 重载后现场回来、只补一次、
**行数 ≥ 重载前**（用户给的验收口径）④ 同一个 id 再点一次 = 真刷新，且不许把用户从
「运行结果」弹回日志页（`fromUrl` 不动页签）⑤ 点另一条 URL 跟着换、重载恢复的是**那一条**
⑥ 坏 id 说清失败 + 静置 2.5 秒不许再打一次 ⑦ 后台 45 秒不补拉、切回恰好一次、
**补拉只许盖回去不许清屏**。
行数一律读**页签上那枚计数**，不读 `.log-row` —— 面板按需挂载，停在结果页签时它根本不在 DOM 里
（上一版拿 `.log-row` 数，⑤ 直接量到 0 行，看着像"换任务没换内容"）。
"地址栏 == 高亮行"用列表项上新加的 `data-task-id` 机械比对：以前 DOM 里没有 id 可比，
只能拿文案猜，本轮就猜错过一次（把"点了另一条"读成假红）。

**负面对照 W-neg（跑完已撤）**：摘掉跟随 effect 里那一行 ⇒ W 趟 ③ 当场 **4 条翻红**，
读数逐字回到用户那份：`idle:"还没有日志"`、`{before3:7, after:0}`、运行条「尚未运行」、
`{详情:0, 轨迹:0, SSE:0}`（压根没去拉）。这条探针不是恒绿的装饰品。

**顺带记下一条待办（本轮撞到，未改代码）**：SSE 的三次退避封顶只约束**连续失败** ——
`api/client.ts:195` 一收到活帧就把 `attempt` 归零。所以后端"接得上但不结流"时，客户端会
**每秒重连一条 + 每接上一次就打一整包 trace**：mock 立即应答（等于服务端关流）那一档，
45 秒里刷出 30+ 对请求。真机上要复现得让后端半关连接。先记账不当本轮修 ——
改的是退避语义，得单独想清楚"封顶"到底该数什么。

**② 那条的期望值这一轮被改过两次**，两次都是产品形状变了、不是缺陷：第一版判
`resultEmpty === null`（把"有思考态"读成"没有空态插画"，前提错）⇒ 改成判那句引导标题；
09-29 并发改进来的 `RunProgress` 又把跑动中那一支的空态插画整块删了 ⇒ 现在判
「思考那一行在 + `.rp` 在 + 三格阶段条 + 页脚那句"届时这一屏会整段替换"」。
意图一直是同一句：**跑动中那一屏必须说得出接下来会是什么**。
另有一条同批待办：`selectTask` 的 `!opts?.fromUrl` 那一支现在**不可达**（两处调用点都带
`fromUrl: true`）⇒ 见 `docs/known_residuals.md` R-16。

### 秒表隔离与页签按需挂载（V 趟，19 条断言）

报告 A4②③ + 决策 U8，一次 commit 里三个动作：

1. **1Hz 只活在 `components/Elapsed.tsx` 里**（render-prop，`<Elapsed startedAt active>`）。
   页面不再有 `now` state，运行条那行「最后一条日志 Ns 前」与日志面板两处页脚各自持有自己的
   计时器；传给 `LogStream` 的 prop 也从 `elapsedMs`（算好的时长）改成 `startedAt`（起点）——
   传后者的话这棵虚拟列表每秒都要陪着重算。
2. **`RunBar` / `ResultPane` 拆成组件**（CSS 拆分按 U8 继续顺延），`TaskLogPage` 从 1,459 行
   降到 1,112 行。
3. **结果 / 工具两个重页签按需挂载**：`children: tab === 'result' ? <ResultPane …/> : null`。

⚠️ 2026-09-28 页签调换（默认页从「实时日志」换成「运行结果」）之后，这一趟的**整段形状翻了个面**，
按需挂载那条规矩没变，变的是首屏挂的是哪一块：旧版钉"选中任务停在实时日志、结果页一行都不在"，
现在钉"选中任务停在运行结果、终端一行都不在"；切走要卸载 / 不许有残留那几条全部反过来写
（基线也从"结果页"挪到"日志页"那一档读数 `m1`，`m3.all > m1.all + 200`、
`|m4.all - m1.all| <= 20`）。两条新增：① 结果页是默认页 ⇒ 引用折叠态照样只有 10 行
（首屏就挂 181 行是旧版就修掉的东西，现在它落在首屏上，更要钉）；
② 历史任务不重播打字机 —— 判据写法换过一次，第一版"点开 800ms 读一次长度、判 `len > 50`"
是恒真的（动画已吐出六成），负面对照 NC-AF2 当场放过去 ⇒ 现在改成**两次读数相减**
（刚挂载那拍 vs 静置 1.6 秒之后一字不差），且必须放在 `m0` 之前测（`m0` 前面本来就有 1.2 秒，
1.5 秒的动画都在那一拍里跑完了）。
"第一次点开日志页签要钉底"那条本来也想放这儿，量到 `max=0` 是假绿 ⇒ 挪去 J 续，理由写在那一节。

判据是两枚计数并排读（`__renders.page` = 整页函数体，`__renders.elapsed` = 秒表组件），
运行中静置 2.8 秒的实测：

| 读数 | 修好 | 负面对照 N1 | 负面对照 N4 |
|---|---|---|---|
| `elapsed`（该涨） | 24 → 36 | 30 → 48 | 38 → 62 |
| `page`（不该涨） | **16 → 16** | **24 → 30** ⇒ 翻红 | **26 → 32** ⇒ 翻红 |
| `logstreamRender`（面板自己，不该涨） | **16 → 16** | 16 → 16（**没**翻红，见下） | **22 → 28** ⇒ 翻红 |
| 改一次关键字过滤（插桩活着的反证） | page 16 → 18、面板 16 → 22 | — | — |

两枚对照要分开跑，因为它们打的是**不同**的那一环：

- **N1** = 把 `useState` + `setInterval(1000)` 搬回页面（props 仍然稳定）。只有 `page` 翻红 ——
  日志面板靠 P0-13 那层 `memo` 还挡得住，所以 `logstreamRender` 照旧不动。
  这一枚钉的是"整页陪跳"。
- **N4** = 在 N1 之上再把 prop 恢复成"每秒算好的时长"（`startedAt={createdAt + tick}`，
  也就是旧 API 的形状）。这时面板才翻红 —— **A4② 的原病根是"prop 每秒变"，
  不是"页面每秒渲染"本身**，两个条件缺一个都打不红面板那一枚计数。
  N1 那一趟 `logstreamRender` 读到 16 → 16 就是这个道理，不是插桩坏了。

⚠️ **同一个量具坑在这一轮又踩了一次**：面板那一判据最初读的是 `<Profiler id="logstream">`
的提交数，结果"修好了"的状态下读数照样 `15 → 18` —— Profiler 对**子树里的嵌套更新**也回调，
而页脚那枚 `<Elapsed>` 每秒就是一次嵌套更新。换成组件自己数的 `__renders.logstreamRender`
之后才是 `16 → 16`。与 P0-13 在 `AnswerView` 上那次是同一件事：**要问"这个组件白渲染了没有"，
就只能问这个组件**；Profiler 只配当"这一帧落地了"的证据。这条写进 `LogStream.tsx` 的 memo 注释。

`elapsed` 一次跳两遍是 StrictMode 双跑、两枚实例（运行条 + 页脚）叠在一起，所以 2.8 秒涨 12。
这一趟照 M / U 的形状做**双向**：先证 `page` 与面板计数数得到（改关键字必涨），再证秒表不牵动它们。

按需挂载那半边（`p2` 单独开页，默认桩 + `citedTrace(60)`）实测：

| 时刻 | `.result-wrap` | 引用行 | 工具卡 | 文档元素总数 | `resultPane` 计数 |
|---|---|---|---|---|---|
| 选中任务、停在日志页签 | 0 | 0 | 0 | 398 | 从未调用（-1） |
| 点开结果页签 | 1 | 10（折叠） | 0 | 806 | 2 |
| 切到工具页签 | **0** | **0** | 61 | 3,230 | 2（不再动） |
| 切回日志页签 | 0 | 0 | 0 | **400** | 2 |
| 第二次点开结果页签 | 1 | 10 | 0 | 807 | 4（又挂了一遍） |

⚠️ 负面对照 N2（守卫拆成 `(tab === 'result' || true)`，也就是 AntD 默认的"挂过就常驻"）
打红的**不是**"没点过 ⇒ 不在 DOM 里"那条，而是"切走要卸载 / 从不同时在场 / 无残留 /
挂载着静置"四条 —— 因为 rc-tabs 对**从没激活过**的面板本来就不渲染 children。
所以那一条只是必要条件、不是判据，check 名字里已按这个口径改掉；按需挂载这刀真正治的是
"看过一次之后常驻"，实测残留 447 个节点（845 vs 398）。

已知代价（写进 `ResultPane` 的头注释，不是回归）：切回来要重新挂载一遍，答案那棵 markdown
树要重解析一次。换到的是"不看的时候一分钱不花"，与 U15 折叠引用是同一类取舍。

**同日重跑 `logperf.cjs ROWS=5000`（只测不改，不进 commit 清单）**，五项口径都记在这儿：

| 读数 | 本轮实测 |
|---|---|
| 常驻（停在日志页签）全页元素 | 501（引用行 0 / 工具卡 0 / 日志子树 115） |
| 页签往返 ×5 中位 / 最差 | 46.1ms / 142.8ms（到结果 51.1、到日志 29.6） |
| 切结果页拆两半：走 React / 不经 React | 44.3ms / 11.1ms ⇒ React 那半边 33.2ms |
| 引用展开 3,000 行 | 846.4ms（收起 54.8ms；元素 808 → 33,698） |
| 滚动帧 p50 / p95 / 最差 | 10.2 / 11.2 / 14.5ms |
| longtask | 6 条，最长 839ms（就是上面那次展开） |

⚠️ **2b 的判读口径随本轮改动变了，别再照旧注释读**：那一项写的是"memo 生效时 React 那半边
应该很小"。按需挂载之后，`A`（点页签）里合法地包含了一次**全新挂载**，所以 33.2ms 不再等于
"白协调"——它是"挂 10 行引用 + 解析一篇答案"的应付成本。这条口径改判据的时机是"谁把
`tab === 'result'` 守卫摘了、React 那半边反而涨回去"，不是"它大不大"。
上一轮那 230ms 的账（visibility 翻转 + 1,000 行重画）见本文
「结果页往返那 230ms 的账（U15，含一次误判的更正）」一节，两份数都留着：
差额来源就是本轮拆掉的常驻面板与上上轮拆掉的 markdown 重建。

### 答案逐段揭示（AF 趟，15 条断言 = 正常动画 10 + 减动档 5，各一趟）

页签调换之后跑动中那一屏落在「运行结果」上 ⇒ "答案怎么出现"第一次成了**首屏**的事。
后端当时没有 token 级通道（可行性判断与它后来怎么被推翻，整段记在
`docs/answer_streaming_2026-09-28.md`），所以这一趟量的是**前端那套逐段揭示**的口径，
落点 `components/ResultPane.tsx` 的 `RevealedAnswer`。一趟跑两遍：正常动画 +
`reducedMotion: 'reduce'`，两个 context 各开一页。

判据（`AF-normal 1…8` + 6a 前件 + 无 pageerror = 10 条；`AF-reduce 1…3` + 2b + 无 pageerror = 5 条）
钉的是这五件事，每件都有一正一反：

* **只对"这次会话里看着它跑"的那条播**：历史任务点开 ⇒ 刚挂载那拍与静置 1.6 秒之后
  **一字不差**（这条的写法换过一次，第一版判 `len > 50` 是恒真的，见 V 趟那段）；
* **播完记账不能被 StrictMode 吃掉**：`onDone` 用 `setTimeout(…, 0)` 推迟一拍 ——
  当场记账的话 effect 被清掉重跑 ⇒ 一次都没播、切页签回来还重来；
* **播的形状**：采样序列单调不减、末尾几拍稳定、答案里最后一行代码那一句确实在（不判
  "长度恰好等于源串" —— 渲染体 235 字 vs 源串 260 字，markdown 吃掉记号，判长度必假红）；
* **减动那一档不许演**：`animation-name` / `duration` 都读（只读 property 会被默认值骗过去），
  首拍就直接给全文；
* **复制键拿整篇原文**：读真剪贴板（context 要 `permissions: ['clipboard-read','clipboard-write']`），
  且先把 Windows 的 `\r\n` 换回 `\n` —— 实测 260 → 271 字，差额正好是源串里那 11 个换行。

两张验收截图落 `shots/running/`：`af-normal-thinking.png`（思考那一行 + 三点 + 阶段条）、
`af-revealing.png`（揭示中途）。另有 `af-result-full.png`（终态整屏）与
`af-reduce-thinking.png`（减动档）两张留档。
⚠️ 探针注入 DOM 之后拍的图不能复用"出厂态"的文件名（这条纪律在 AE 那节写过），所以这四张
一律带 `af-` 前缀。

**两组负面对照**（各跑一次，一次只摘一处）：
`NC-AF1` 把 `revealed` 那层记账删掉 ⇒ 红的是"切页签回来不许重来"那一族；
`NC-AF2` 把 `revealed` 写成恒 `false`（等于所有任务都重播打字机）⇒ 放过去的正是第一版那条
恒真判据，改写成"两次读数相减"之后它才红。红名单与读数都抄在 `running.cjs` 的 AF 段注释里。
⚠️ 两组都已回滚，`src/` 里没有残留 `NC-AF` 标记（`grep -rn "NC-" src/` 只剩 AD 那几条历史注释）。

### 宽表的横向滚动区（X 趟，22 条断言）

**要治的是走查报告 EV-01（P0）**：390 视口下 /eval 三张表分别藏掉 7 / 5 / 1 列，而"右边还有列"
既看不见（窄屏的滚动条是 overlay 的，不占高度）也滚不过去（容器不可聚焦，`tabindex` 全是 `null`）
⇒ 用户以为这张表就只有两列。修法是 `components/ui.tsx` 的 `ScrollXFrame`：外层 frame 只画两端渐影，
内层 `.scrollx-box`（同时挂着 `.table-wrap` 的粘性表头规矩）才是滚动 + 可聚焦那一层，
三态写在 `data-scrollable / data-at-start / data-at-end` 上。

**四颗坑，都是这一趟钉住的**：

1. **`!important` 不是写不够体面，是唯一的出路。** 带 `scroll={{ x }}` 的表，AntD 把
   `overflow-x:auto` 以**行内样式**打在 `.ant-table-content` 上，行内样式压过任何选择器 ——
   不带 `scroll.x` 的那张（失败归因）能正常收回，带 940 / 800 的两张抢不动。
   收回失败的症状很隐蔽：外层 `scrollWidth == clientWidth` ⇒ `data-scrollable` 恒 0，
   而"有 tabindex 属性"那几条照样全绿。
2. **别用 `End` / `Home` 测"滚到底"**：实测 Chromium 对可滚动 div 根本不响应这两个键
   （`scrollLeft` 纹丝不动），只有方向键会滚 ⇒ "键盘能不能把藏掉的列滚出来"只能一段
   `ArrowRight` 数出来（390 下 30 下到底，`scrollLeft` 642/940）。
3. **读渐影前要静置**：它带 120ms 过渡，`data-at-end` 已经是 1 时 `opacity` 可能还在 1→0 的路上
   （第一版就是这么误红过一次）。同类教训见「窄屏与计算样式」那段的 transition 条。
4. **键盘那几条要连发之后再读**。一下一读、或先 `page.focus()` 再按，那几下会**完全不滚**——
   `activeElement` 就在那块容器上、`scrollWidth-clientWidth=642`、`tabIndex=0`，`scrollLeft`
   却一动不动；连发 5 下 + 静置 150ms 才读到 200（Chromium 一档 40px）。这是**读法在干扰键盘滚动**，
   不是产品缺陷：全量首跑那条"固定三下立刻读"翻红、而同一趟里连发 10 下的循环正常到底，就是这么来的。
   顺带一条同源教训：内置浏览器在**标签不可见**时读伪元素计算样式也不可信
   （同一页面里现造的同属性探针读到 1，页面里那块读到 0），要判渐影到底有没有画出来，
   要么在可见上下文里读，要么截图。

**断言分两档跑**：390 档 20 条（结构 / 收回 / 溢出 / 三态 / 渐影 / 真聚焦 / 按键真改
`scrollLeft` / 最后一列进视口），1440 档 3 条钉**反向**——不溢出时 `data-scrollable=0`、
两端渐影都灭、最后一列本来就在视口里。少了 1440 那一档，"恒画渐影"的错实现也能全绿。

**负面对照 X-neg（跑完已撤）**：摘掉那条 `!important` ⇒ 当场 **10 条翻红**，读数逐字回到坑本身：
内层 `["auto","auto","visible"]`、外层 `["298>298","298>298","391>298"]`、
`data-scrollable` `["0","0","1"]`、`scrollLeft` 停在 0、最后一列「向量均分」`false`。
第三张表（不带 `scroll.x`）在两种实现下都是绿的 —— 这正说明"只测一张表"会漏掉这一整类。

### 面板头两列抢宽度（Y 趟，18 条断言 · 只跑亮色）

**要治的是走查报告 EV-02（P0）**：390 下「检索评测（零 LLM）」被压到 **38px**（本轮实测的另一张
掉到 **161px**）。机制是 flex 的**让位顺序**：`.surface-head` 不换行，右侧 chip 那一列作为 flex item
默认 `min-width:auto` = 内容宽（**不肯让**），而标题列带的偏偏是 `min-w-0`（**随便让**）⇒
两边的收缩代价全落在标题上。修法是三件事一起，缺一就不是修好：

1. `.surface-head > .grow { min-width: min(14rem, 100%) }` —— 给标题列一个**地板**；
2. `.surface-head { flex-wrap: wrap; row-gap: 8px }` —— 放不下的是 chip，让它落第二行
   （地板才是换行的**触发器**：只加 wrap 不给地板，标题先被压扁，永远轮不到 wrap）；
3. 收缩链 `.surface-extra` → `.code-chip` → `.code-chip code` **三环各给 `min-width:0`** ——
   `nowrap` 的整串文件名要能截断，否则换行之后从"压标题"变成"撑破卡片"。

**四颗坑，都是这一趟钉住的**：

1. **判"同一行"不能比 `top` 差**。`.surface-head` 是 `align-items:center`，同一行里 extra 会被
   垂直居到标题列（带 sub 的那列更高）的中间，实测 Δtop = 12px ⇒ 拿 `|Δtop|<=1` 当"同一行"，
   **宽屏那档假红、窄屏那档假绿**（第一版就是这么错的：`[true,false]` 出现在 1440，
   而 390 的"真的换行了"其实一直是蒙对的）。判据改成 `extra.top >= col.bottom - 1`：
   换行的事实是"跑到标题列下边去了"，行间距 8px 天然把它推开。
2. **"整页不溢出"挡不住卡片溢出**。Y-neg-B 的读数：卡片 `scrollWidth-clientWidth = +123px`，
   而 `documentElement` 那一层仍是 **0**（外层有裁剪）。⇒ 溢出必须量**出问题那一层**自己，
   与 X 趟"右留白要对着真正的容器算、别拿 `parentElement` 一把梭"是同一条教训。
3. **只测一张头会全绿**。Y-neg-A（摘掉地板）只有**短 chip 那张**翻红（161px、不换行），
   带 51 字符文件名的那张照样 298px + 换行 —— 因为它本来就必须换行。
   这与 X 趟"第三张表在两种实现下都是绿的"同源：**同一类缺陷里，最显著的那个样本往往最钝**。
   所以两档反向钉都留着（1440 不许无理由换行 / 一字不截；820 过渡档 ≥224px）。
4. **桩与探针的注释里别写 `*/`**。我在趟清单末尾写了一枚"看着像收尾"的 `*/`，直接提前闭合块注释 ⇒
   整个文件 SyntaxError。`.cjs` 改完先 `node --check` 再跑（这一条已经栽过一次，见 8c 末）。
   **AA 趟又栽了一次，而且换了一副样子**：`mocks.cjs` 里那段说明写了路由串 `**/api/tasks/*`，
   同一个 `*/` 在注释体里自终结 ⇒ 症状不是 SyntaxError 而是运行期 `ReferenceError: api is not defined`
   （`*/` 之后的中文被当代码解析）。同一类坑的第二条形状：**注释里出现 glob / URL 模式时改成 `//` 行注释**，
   别指望 `node --check` 每次都替你兜住（它兜得住前一种，兜不住后一种——后一种语法上是合法的）。

**负面对照两趟（跑完已撤，`index.css` 与备份 `cmp` 过一致）**：
Y-neg-A 摘地板 ⇒ **2 条翻红**，读数逐字回到缺陷本身：`["检索评测（零 LLM）:298px","消融对比:161px"]`
+ `换行 [true,false]`。Y-neg-B 把三环 `min-width` 恢复成 `auto` ⇒ **3 条翻红**：
卡片溢出 `[123,0]`、`codeOver` 从 137 变 0（不截断、改撑破）、链读数 `auto|auto|auto`。

**只跑亮色一趟**是有意的：这一趟全是几何与 `min-width`，跟配色无关，跑两遍只是把断言数翻倍。

### 成本归因面板（AA 趟，24 条断言）：页面说的必须是端点说的

面板的全部价值是"数字可信"，所以这一趟几乎不查外观，只查一件事：
**页面上那个数是读来的，不是前端自己算的**。八组正判据 + 三条负面对照 + 一条豁免补偿判据。

最值得记的三条：

- **1 / 1b 合计与次数不来自明细**。明细桩灌成 600 条 ×¥1、token 各 999,999，
  面板必须纹丝不动（仍是端点那份 `¥0.0094` / 5 次）。这一条替掉了草稿里"造 600 事件看有没有
  截断提示"那版判据 —— 合计走后端 `GROUP BY`，本来就不会截断，会截断的是明细那一侧；
  真正会被咬的是"前端自己去加明细"，所以判据直接堵那条路（详见方案 §5 第 3 条）。
- **6 / 6b 时钟口径是双向的**。改后端桩值 ⇒ 读数跟着动（证明是读来的）；
  再用 `page.clock` 把系统时钟整个挪 5 小时 ⇒ 读数**一个字符都不许变**（证明没读本地时钟）。
  只量前一半会漏掉"它同时也看了 Date.now()"。读数是 `21:07` / `18:00` 这种**字符串切片**，
  不是 `new Date(s).getHours()` —— 后者在 UTC 机器上会把 18:00 印成 10:00。
- **2b 两个对账数恒常露出**。相等时也把 `Σ分组 ¥0.009395` 与 `tasks.cost ¥0.009395` 摆在页面上，
  而不是只留一句"一致"。它们各带身份，所以不违反「同屏不许两份同数」。

**负面对照三条**（全部靠改桩实现，不动生产源码 —— 与 F/J 趟那种"摘掉再看红"等价，
但不冒改坏源码的风险）：① 把历史行的 `model` 回落成今天的 `role_map` ⇒ 判据 3 抓到；
② `all_equal=false` ⇒ ✗ 与 note 真落到页面（证明对账行不是恒 ✓）；
③ `price_check.ok=null` ⇒ 显示 `?` 与「未校验」而不是 ✓。

**一处豁免和它的补偿判据（4d）**：结果页那套「空壳普查」（I 趟，判据是
"有底色 + 读不出字 + 没 aria-hidden"）把新加的分段条 `.spark` 连同它的色块 span 一起记名了。
豁免条件是 `closest('[role="img"]')` 且那条 `aria-label` **非空** ——
放过一个图形的**前提**是先确认它真的说明了内容。这个前提由 4d 自己钉：
逐段点名 + 金额四位（`◆ Planner 高峰 ¥0.0020，…`）。
顺带修了 `SparkBar` 两处：`aria-label` 以前吐的是**原始浮点**（`0.0020022`，读屏念出来
等于没有），现在支持 `readout`；`key` 以前只用 `label`，成本面板同一角色跨峰谷会有两段同名 ⇒ 撞 React key。

**踩过的两个坑**（都不是代码错，是判据自己的错）：

1. **反向对照基准取错**。6b 最初拿"6 那一步特意改成 `21:07` 的读数"当基准，
   于是"时钟挪了读数不变"变成拿两个不同桩比 —— 恒红。对照必须落在**改桩之前**那份原始读数上。
2. **块注释里写 URL glob**。`mocks.cjs` 一句 `/* … **/api/… */` 在 `*/` 处就地闭合，
   剩下中文成代码，症状是运行期 `ReferenceError: api is not defined`，而 `node --check` 过得干干净净。
   这条本仓库 README 早就写过（见 Y 趟那段第 4 点），我又踩了一遍 —— 说明写在"经验"里不如写在**判据**里。

**AA 的 24 条里光"前件"就占 4 条**（面板在场 / 两主题各真量到几条文字 / 摘要条有没有内容 / 无标签）。
`check()` 是 `Boolean(cond)`，不写前件的断言在元素改名之后会一直绿。

### /eval 的错误态与形状闸门（AB 趟，25 条断言）

外部检测报告 2026-09-25 的 F-1/F-2/F-4/F-5/F-11 一轮。判据问的都是"用户读到了哪句话"，
不看像素（对比度那一类归 `contrast.cjs`）。桩用 `page.route` 覆盖 `installMocks` 的两条
report 路由（后注册的先匹配）：HTTP 500（带统一信封的 `code` + `request_id`）、HTTP 404、
`abort('connectionrefused')`、`available:false`、`groups:"不是数组"`、`groups:[]`。

- **F-1 的核心那条是分支顺序**：`retrieval.isError` 必须排在"没数据"那个判断**前面**。
  顺序错了，500 会被渲染成"尚未运行过检索评测"+ 一条 CLI 命令 —— 后端活着却被支去敲命令行。
  所以四档各有一条正向、再加两条反向钉：错误态里**不许**出现 `python scripts/eval_retrieval.py`，
  而 `available:false` 那一档**必须**还出现它（分家不等于把正确的指引一起删掉）。
  `request_id` / `HTTP 404` / 「请求未送达」各钉各的：断网那一档不许编一个状态码出来。
- **F-2 的对照组**：`groups` 非数组 ⇒ 「格式不识别」+ 另一份报告照常渲染；`groups: []` ⇒
  合法空值，**不许**报成格式问题。少了后一条，前一条就是恒真。
- **F-4/F-5** 读计算样式与可达名：释义触发器是 `<button>`、`.anticon` 带 `aria-hidden`、
  可达名是"什么的口径说明：全文"而不是图标名；可排序表头聚焦后 outline 必须是主色 2px。

三条本轮新坑（都值一行）：

1. **等待条件要 scoped 到被问的那一块**。`waitForSelector('.ant-table-tbody')` 在 /eval 上
   **立刻满足** —— 同页消融那张表的 tbody 一直在场，而检索那块还在骨架屏（`retry: 1` 更要等）。
   症状是"错误态没渲染"的假红。改成"在这一张卡里找 错误态 / 空态 / 真数据"才算落定。
2. **`useId()` + `aria-describedby` 在 lazy 子树里会失配**。第一版把释义放在 span 上、按钮用
   `aria-describedby` 指过去，实测按钮上是 `:r11:`、span 的 `id` 却是 `:rv:`（React 18.3 在
   Suspense 重放下给同一渲染里的两个槽位发了不同的值），引用落空 ⇒ C8 三条内容断言全红。
   这类"引用指向不存在的元素"不报错、只是安静地没有。**改成文本直接待在按钮里**，不依赖 id。
3. **AntD 表格列带 `transition: 0.32s`（全部属性）**，聚焦后**立刻**读 `outline-*` 会拿到插值：
   width 从 `medium`(3px) 走向 2px、color 从 `currentColor`(#4b5266) 走向 #4f46e5 ——
   于是"我的规则没生效"的假结论。聚焦与读取之间隔一次 `waitForTimeout(450)` 才是终值。
   （同一族坑在 J/X 趟已经记过：过渡中间态读样式不可信。）

顺带把 F-11 结了：390 下把外层 `.scrollx-box` 横滚 140px，`fixed: 'left'` 那个表头的 x **一字不动**
（`beforeX=77 afterX=77 scrolled=140`）⇒ 报告怀疑的"粘性左列被 `overflow: visible` 打死"不成立；
它量到的 `scrollWidth 226 > clientWidth 196` 正好是 196（列上写死的 `width`）+ 30（`fixed` 列
阴影伪元素），是**读数口径**问题不是裁字。两条判据留在 AB 末尾，`index.css` 里那句
"这三张表现在没用 fixed"的过期注释也一并改对了。

### 解释性文案要按**内容**断言（C8，3 条）

用户实测两条同样的 `1+1` 消耗不同（他报的是 2,762 / 3,076；本机库里那 5 条是
2,564–2,980，同一类现象，**3,076 这条本轮没在库里复现到**）。第一反应是"是不是有 bug"。
现场解释挂在结果页与轨迹页的「总 token」ⓘ 上，文案单一来源 `src/utils/costNote.ts`。

为什么单独钉一条：**这类文案的失效方式不是"没了"，而是"退化成安慰话"**。
只断言 `title` 非空或长度 > 20，那么把句子改成"token 会因模型采样略有波动，属正常"照样全绿 ——
而那句话恰好漏掉了真正的答案：钱的大头差来自**计费时段**（实测 `2.37 ≈ 2.00（峰谷）× 1.16（用量）`，
模型没换）。所以判据按内容三件齐全：`/采样/` + `/时段|×0\.5/` + `/实测/` 且串里有数字。
症状：删掉"计费时段"那半句 ⇒ 立刻翻红；把数字换成"会有一定浮动" ⇒ 翻红。

两个附带口径：① 同一句话在两页各有一份 DOM，所以两页各钉一条（少钉一处 = 那一页可以悄悄删掉），
但**文案只有一个出口**（抄两份必然各自漂，与"同屏不许两份同数"同源）；
② `readMetricParity()` 为此多返回一个 `tip`（原来只有 `gloss = title.length`，
长度挡得住"没挂解释"，挡不住"话说漂了"）。

⚠️ **2026-09-26 之后 `tip` 不再从 `element.title` 读**：F-4 把释义触发器换成了
`<button class="metric-info">`，全文以 `.sr-only` 待在按钮里（原生 `title` 与 Tooltip 会叠两层，
已删）。三处读点（`readMetricParity` / AB 趟 / 轨迹页 `traceTips`）都改成先找
`.metric-info .sr-only`、找不到再退回 `title`。**换位置的代价写清楚**：Tooltip 的文案是弹层，
没打开时根本不在 DOM 里 —— 所以这句常驻文本不是冗余，它是这三条内容断言唯一能落地的地方，
也是读屏在焦点上唯一读得到的那一份。改坏了的症状：`gloss = 0`、三条 C8 一起红。

### 知识库上传页与"分段进度条"（Z 趟，55 条断言）

方案见 `docs/knowledge_upload_plan_2026-09-25.md`（K1–K8 已拍板；R-03 的收口在第 12 节）。
十三个 context：正常三行 / 全终态 / 概览与行数不一致 / 未知状态 / 后台标签 / 轮询跟到终态 /
上传链路七种回法（同一 context 里 `step()` 复位）/ 删除两下 + 重试回到第一段 / 503 整页 /
**概览先挂、列表扣在闸门上那一帧** / **两个新字段都不给（后端没重启）** /
**只缺 `supported_formats`（重启到 HEAD 会落在的那一档）** / 390 窄屏。

**进度条的口径先说清楚，因为它决定哪几条判据是假的**：这条条子只画**处理段**四格
（解析 → 切分 → 向量化 → 可检索），格的亮/暗/动全部来自轮询回来的 `status`；
**传输段不画百分比** —— `fetch` 拿不到已上传字节，要百分比只能换 `XMLHttpRequest.upload.onprogress`，
而 K4 拍的是"状态文字 + 已传字节，不引 XHR"。所以那一行给的是 `fmtBytes(file.size)`（本地真数），
分段条上第 0 格都不点亮。`.stage-bar` 带 `data-stages="done,done,active,todo"` 与 `data-fail-stage`，
**探针读这两个属性，不读像素**；`aria-hidden` 是因为读屏听到的说法在旁边的徽标里，
一条进度条播两遍是吵。

判据里值得单独记账的十一条：

- **失败格停在 `error_stage` 那一格**，不是"永远最后一格"：后端在 `queue` / `dedup` / `unknown`
  三个阶段就失败了（压根没进流水线），点任何一格都是在讲"它跑过那一步"。
- **未知状态（`verifying`）三件套**：原文上屏 + 不呼吸 + 四格全 `off`。
  少了后两条，"不译成已索引"这条会假装通过 —— 一个不认识的状态被当成"还在跑"是同一类假话。
- **串行用峰值并发证明**：桩在 `fulfill` 之前记 `inflight`，`maxInflight === 1` 才算串行
  （只数总请求数的话，5 份并发发出去也是 5 次）。这是避坑 3（后端 `file.read()` 整读进内存）
  唯一能落地的正向判据。
- **429 的退避秒数来自 `Retry-After`**：桩故意给 **1 秒**而不是后端的 5 秒。
  判据因此测的是"读没读那个头"，不是"有没有把 5 抄进代码里"。
- **同名 409 的两个分支各自钉**：点「覆盖重建」⇒ 第二个请求的 URL 真的带 `overwrite=true`
  + 回执 `warnings` 上屏（"旧索引已清除"不许被"上传成功"盖掉）；点「放弃」⇒ **总共只发过一次请求**。
  后一条是反向钉：只有前一条时，把"放弃"做成"顺手也发一次"测不出来。
- **删除有两下，而且第二下之后列表真的少一行**：第一下 `DELETE === 0`（与 P 趟取消同一口径），
  确认后恰好 1 次 + `行数 3 → 2`。后半句要求 `mocks.cjs` 的 DELETE 桩**真的摘掉那行** ——
  只回执不改库的 fixture 写不出这条判据（而"只回执"的桩恰好会让页面看起来也没错）。
- **重试走到底**：`POST .../retry` 恰好一次 + 那一行从「索引失败」回到第一段（`排队中`、
  分段条 `active,todo,todo,todo`、红标消失、不再给重试按钮）。这条同时钉住"分段条能往回走" ——
  谁把它实现成只许前进的单调条，这一行就会一直红着。同样要求桩按后端语义改 `kbState`。
- **"只有概览失败"那一帧说的话要站得住**（9b 档）：概览 503、列表被 node 侧闸门扣住 ⇒
  那一帧附言必须是"此刻还没回话"；放行之后必须是"这一趟回来了"。**两半都钉**，
  因为写死任何一句都是在替一个还不知道的东西担保 —— 这是本轮由探针逼出的**产品**修正
  （旧版是一句写死的"它没坏"）。
- **两个新字段都不给**（9c 档 = 本机现在这个后端进程：K3 与 R-03 都是后加的，老进程两个都缺）：
  副说明**合成一句**"格式与大小上限这一趟都没读到 · 一次最多 5 份（串行）"，不许出现"≤ —"这种半截话；
  而且那份 3 MB 的文件**必须照样出网**（不本地拦，让后端的 422 说话）。两头一起钉才有效：
  只钉前一条，把上限写死成 50 也照样全绿；只钉后一条，界面印着"≤ — MB"也不会有人红。
  ⚠️ 合并不是顺手写的：分成两句会在同一行里说两遍"交给后端判"，那是噪声不是信息 ⇒
  判据里那半句"至多出现一次"就是钉这个的，别顺手拆回去。
- **"这一句读的是接口还是写死的"要能红**（同一档里的第二条判据）：桩给的是 **33** 不是 50。
  读点也换进上传卡那句副说明，不拿整页 `innerText` 找 `"单文件 ≤ 50 MB"` —— 整页里"50"随时可能
  从别的读数冒出来。⇒ 见坑 9。
- **上传白名单同理（R-03）**，而且是**四条一起**才成立：`accept` 由响应的 `supported_formats` 推导
  （桩给四种、含页面从没写过的 `docx`）、「支持 …」那句读同一份、响应给了 docx 就**不许**再本地拦、
  不在清单里的（.png）本地挡下且文案列的是**响应那四种**。
  再加 9d 一档：只缺白名单 ⇒ `accept` 属性**干脆不给**（不是给一个空串锁死选择器）、
  文案改口、`.png` 照样出网由后端 422 说话 —— 只断言"出网了"挡不住"出网后页面又自己判了一遍"，
  所以那句要同时**排除**页面本地拦的措辞（"后端这一趟给的白名单是 …"）。

**done / active 两档的色差是这条条子唯一的"走到哪儿了"读数**，所以它的算法写在 `index.css` §10.7
的注释里，而**证据在 `contrast.cjs`**：那两条"分段条 done↔active 色差（图形，不判定）"给的实数是
亮色 `#4f46e5 → #a5abf7` **2.92:1**、暗色 `#818cf8 → #a5b4fc` **1.50:1**。
1.50:1 就是"如果 done 直接吃 `--primary-300`"在暗色下剩下多少 —— 等于没换。
所以 done 压的是**同一支 `--primary` 的透明度（0.5）**，两档各自成立、也不必为一格进度新增色阶。
不判定是因为它是图形不是文字（WCAG 1.4.11 那条走的是 3:1，而这里比的不是"前景/背景"，
是"同一根条子上相邻两格"）；留数是因为动画在截图里、在 `prefers-reduced-motion` 下、
在低刷新屏上都不成立，那时静态一帧必须自己说清进度。

负面对照 A（2026-09-26 实跑，一次改三处、看红的是不是恰好那三条 ⇒ 41/44；
那一次跑的是当时那一版的 Z，之后补了"重试 + 那一帧附言"三条、再补 R-03 五条 ⇒ 现在整趟 55 条。
**三条判据本身没动**，所以这张表读的是"能不能红"，不是"红了几条对几条"）：

| 摘掉什么 | 该翻红的判据 | 实跑读数 |
| --- | --- | --- |
| 轮询的 `if (!anyLive) return` | 终态即停：3 秒内 0 次列表请求 | `之前 1 / 之后 2` |
| `<input accept>` | accept 那一条（R-03 后改名为"由响应的 supported_formats 推导"，当年叫"已收窄到 pdf/md/txt"） | `""` |
| `statusView` 的 `default: live:false` | 未知状态不转圈 | `在动 true` |

负面对照 B（R-03 那一族，同日实跑）：把 `readFormats` 改成**无视响应**、直接
`return ['md','pdf','txt']`（也就是"页面自带一份清单"那个旧写法）⇒ **48 通过 / 55 断言**，
翻红的恰好是这七条，且没有一条无关判据被牵连：

| 该翻红的判据（七条） | 实跑读数 |
| --- | --- |
| `accept` 由响应推导 | `".md,.pdf,.txt"`（少了桩给的 docx） |
| 「支持 …」那句读同一份 | `支持 md / pdf / txt · 单文件 ≤ 33 MB …` |
| 不在清单里的本地拦、文案列响应那四种 | `…白名单是 md / pdf / txt` |
| 响应给了 docx 就不许再拦 | 阶段 `rejected`、`POST 0` |
| 缺字段时不给 `accept` | `accept: ".md,.pdf,.txt"`（属性还在） |
| 缺字段时文案改口 | 还是 `支持 md / pdf / txt` |
| 缺字段时一个都不拦 | `POST: 0`（本地就挡了） |

改回原样之后 55/55。对照期间用的副本文件（`KnowledgePage.negbak.tsx`）先 `cmp` 证过无损、随后删除。

**这一趟新添的九条坑：1–6 与 8–9 全在探针这一层（症状却长得像"页面写坏了"），只有第 7 条是页面真的写坏了**：

1. **别拿 `document.body.innerText` 的正则等某个控件出现**。F-4 之后指标卡的口径说明以
   `.sr-only` **常驻** DOM，而那句话里正好有"覆盖重建"四个字 ⇒ 等待第一帧就"命中"，
   读到的是上一帧的状态（症状：断言说行还挂在"上传中"，而它等的正则早就绿了）。
2. **同一句 `.sr-only` 裹在 `.metric-info` 那枚 `<button>` 里**，所以
   `page.locator('button', { hasText: '覆盖重建' }).first()` 点到的是**指标卡的 ⓘ 按钮**
   （DOM 里它排在上传区前面）：点击成功、队列纹丝不动、然后等 30 秒超时。
   队列里的按钮一律用 `('.up-list button', …)` 先把搜索范围收到本块，再按名字找。
3. **AntD 两字标签中间是真空格**：`textContent` 是 `"放 弃"` ⇒ `hasText: '放弃'` 点不到，
   要传 `/放\s*弃/`。三字以上与带 `icon` 的那几枚（"覆盖重建""仍要删除""删除"）不受影响，
   所以症状是"只有这一个按钮点不到"。
4. **`data-scrollable` 挂在外层 `.scrollx-frame` 上，不在 `.scrollx-box`**（`ui.tsx:528`）。
   写成 `.scrollx-box` 恒读 `null`，看起来像"表格不能横滚了"。
5. **503 要等 react-query 的 `retry: 1` 落定，而且"整页降级"要有自己的落点**：`networkidle`
   之后立刻读，读到的是还在 pending 的那一帧 —— 既没有错误态也没有空态，`rows=0`，三种成因在
   旧读数里长得一模一样。第一版把等待写成 `.app-content .error-state`，结果**概览先失败**那一帧
   也算命中（那张卡也在 `.app-content` 里），于是 503 那条判据读到的标题是"概览拉取失败"。
   现在整页那一张卡带自己的类 `kb-rag-down`，判据与等待都只认它；并把**响应码流水**、
   骨架屏数、首段文本一起塞进 `got`：桩没生效 / 页面判错 / 时序太早，三者要能一眼分开。

6. **别用"延迟 N 秒"去撞某一帧，要用闸门**（本轮两版都输在这里）。9b 那一帧要读的是
   "列表还没回话时页面说了什么"：先留 1.2 秒、再放宽到 2.5 秒 + `polling: 100`，两次都读到
   "列表早就回来了"。原因是这些 context 从没被真正合成过（与 Q 趟那条 `document.hidden` 桩同源），
   Chrome 把隐藏页的 `setTimeout` 与 `requestAnimationFrame` 一起节流，页内的 `retry: 1` 退避
   与探针的轮询都不按墙钟走。**改法**：`page.route` 里 `await` 一枚 **node 侧**的 Promise
   （`openKnowledge` 的 `gate` / `releaseGate`），要放行时放行 —— 闸门不受页面节流影响，
   那一帧就变成**造出来的**而不是**碰上的**。代价：这一档的 `goto` 要用 `domcontentloaded`
   （有一条在途请求，`networkidle` 永远不会到）。

7. **这一条是真缺陷，而且是"新字段还没上线"这一类里最阴的一种**：K3 给 `/overview` 加了
   `max_file_mb`，但**后端进程没重启就没有这个字段**（本机 :8001 正是这个状态）。页面第一版写的是
   `overview.data ? overview.data.max_file_mb * 1024 * 1024 : null` —— 字段缺席时得到的是
   `NaN`，两个后果同时发生：界面印出"单文件 ≤ — MB"这种半截话，而本地预拦那条
   `file.size > NaN` **恒为 false**（不拦、也不说为什么不拦）。
   判"有没有这个数"要用 `typeof === 'number' && Number.isFinite()`，不能判"有没有响应"。
   ⇒ 新增 9c 档（把字段从 overview 响应里删掉）钉两头：副说明必须改口成"交给后端判"，
   且那份 3 MB 的文件必须照样出网让后端说 422。**少了这一档，K3 在重启前是静默半瘫的。**

8. **桩漏配路由不会报错，它会把请求放给真后端**。`mocks.cjs` 里那条
   `**/api/knowledge/documents/*` 管得住 `/documents/{id}`，**管不住** `/documents/{id}/retry`
   —— Playwright 的 `*` 不跨斜杠，要多写一层 `**`。症状是"重试点了没反应"，
   而真实情况是那一发悄悄打到 vite 代理后面的 `:8001`，被真后端回了一个 404。
   现在 `count('POST', '/retry')` 与"那一行回到第一段"两条一起钉，路径没接住就是红的。
   顺带把 fixture 改得**更像后端**：`retry` 真的把那条记录改成 `pending` 并清掉 `error_*`，
   `DELETE` 真的从 `kbState.docs` 里摘掉那行 —— 只回执不改库的桩，永远写不出
   "删完列表少一行 / 重试完回到第一段"这种判据（这正是"探针 fixture 必须是后端真行为"那条）。

9. **fixture 的默认值不许撞上"缺陷值"**。Z 趟原来那条判据长这样：
   桩里 `max_file_mb: 50`，断言写的是"整页文字里含 `单文件 ≤ 50 MB`" —— 而 50 正是
   `config.py:209` 的默认上限，也就是"页面把数字写死了"时**同样会印出来的那个数**。
   ⇒ 一个把上限写死的页面在这一条下恒绿，判据从未成立过（本轮自己踩到，改完才红过一遍）。
   改法：桩值换成只在桩里存在的 **33**，并断言 `/≤ 33 MB/ && !/≤ 50/`；读点从整页
   `innerText` 收窄到上传卡那句副说明（整页里"50"可能从别的读数冒出来，也可能以后从别处消失）。
   **同一条纪律在 11.4 那处也是这么用的**：判"读的是接口"必须让桩值避开缺陷值，
   否则"改了接口读没读"这件事永远测不出来。

⚠️ 顺手结掉一条**探针层的错位**（本轮查出、本轮改完）：`page.waitForFunction` 的签名是
`(fn, arg, options)` —— 写成 `waitForFunction(fn, { timeout: 8000 })` 时那个对象被当成了
**arg**，超时退回默认 30 秒。`running.cjs` 现在一共 **10 处**调用，形状全部正确；
本轮之内曾有 2 处是错位的（Z 趟 s6 的 `12000` 与 AB 趟 `settle()` 的 `20000`），都补了 `null,`。
症状不是假绿而是"等得比写的久"：`8000` 写成这样会跑到 30 秒才报超时 —— 与 `lazy.cjs`
（一直是正确的三参写法）对照才看出来。防它回来的办法不是 grep，是**看到第二个参数是对象就停手**。

### 终态不许有转圈（A / B 双向，2 条断言）

**要治的是你实测那颗**（EV-20）：运行条已经写着「成功」，`#293 calculator → 2 · 已重复 2 次`
那行还在无限转 —— "跑完了还有一条在加载"。旧代码只有一行判据：

```tsx
const live = row.repeat > 1;                 // 把"合并过重复"当成"还在等下一个事件"
{live && <span className="log-live-mark" aria-hidden />}   // 0.9s spin infinite，且不看 running
```

`repeat > 1` 是**合并的副产品**，跟"还在等"没有必然关系：两条一模一样的工具行照样会被
`collapseRepeats` 并成一行，于是任何历史任务里只要有过相邻同名行，终态就永久挂一个 spinner。
现在拆成两个判据，一个都不许代理另一个：

- `merged = row.repeat > 1` —— 历史事实，什么时候都成立 ⇒ 薄底色 + 「· 已重复 N 次」+ 页脚「合并重复 N 条」都留着；
- `waiting = running && row.idleMs !== undefined` —— 心跳帧 **且** 任务还在跑 ⇒ 转圈 + 「· 订阅后 X」。
  `running` 必须传进行级（`RowViewProps`），只留在面板层挡不住。

**为什么要两头都钉**：A 趟原来只有正向的「合并行有转圈标记」，把 `waiting` 写成恒 `false`
的实现也能全绿（那条断言本来就是错的）；反过来只留"终态 0 个"，则 spinner 整个删掉也照样过。
所以现在是 A 趟 `liveMarks === 0`（终态整页零个）+ B 趟 `liveMarks === 1 && liveMark === true`
（运行中那个心跳行确实挂着）配成一对，`readTerminal()` 为此多返回一个全页个数。

**同类项一起扫了**：`index.css` 里 `animation: … infinite` 共 8 处，其余 7 处的渲染条件都直接读
运行态（`.dot--live`、`.status-badge.is-live`、`.skeleton`、`.spin`、`.step.is-active`、
`.log-cursor`、`.live-dot`），**只有 `.log-live-mark` 是拿合并计数当运行态代理的** —— 不是普遍问题
的第一单，但"代理判据"这个写法值得记住：判"在不在跑"要读状态，别读状态留下的痕迹。

### 换模型面板（AC 趟，亮暗各 38 = 76 条）：这条链上"看起来正常"的四种错

方案里这一趟原本叫「L 趟」，**L 这个趟号早就被 `passListSelectFinish` 占了**，
A–Z 没有空位 ⇒ 往后排成 AC。名字换了，判据一条没换。

一屏要同时不骗人的四件事：候选是不是响应给的、应用之后显示的是不是真生效的、
被拒之后有没有留下半个生效的样子、老后端（没重启、没有 `catalog` 字段）会不会
假装能换。所以每一趟都开 **4 个页 / 4 次导航**走这四个场景：主路径（含拒绝与回落）、
老后端降级、"桩里删掉一家"的证伪、390 窄屏走抽屉；亮暗各一趟 ⇒ 本次开页 81→89、导航 91→99。

桩是**有状态**的（`createModelOverrideMock`）：`POST` 真的改内部状态、之后的 `GET`
返回改过的样子 —— 静态桩验不出"应用后界面读的是响应还是自己的记忆"这件事，
而那是这条链最容易错的一处。缺 Key 那家（桩里是 `qwen-plus` / `LLM_API_KEY_QWEN`）
就是专门留给"422 要真的拒"的素材。

对比度这一趟**在面板里现量**（不并进 `contrast.cjs`：那支量的是常驻选择器，
这个面板要点开才有 DOM）。亮 / 暗两档各量五个选择器，分母是**往上找到的第一层不透明底**：

| 选择器 | 亮 | 暗 |
| --- | --- | --- |
| `.model-settings-scope`（生效范围那句，11px） | 7.78 | 8.22 |
| `.model-settings-badge`（"本进程已覆盖"，11px） | 7.33 | 7.83 |
| `.model-settings-price` / `-keys li`（11px） | 7.78 | 8.22 |
| `.model-settings-label`（12px） | 17.67 | 15.02 |

**这一趟写探针时踩到的四条，逐条留着**（四条全在探针这一层，页面没返工过一次）：

1. **齿轮点了"没反应"** —— 我给按钮自己绑了 `onClick` 翻 `open`，而
   `Popover trigger="click"` 同时会走 `onOpenChange` ⇒ 开完立刻关。
   现象是 `waitForSelector('.model-settings')` 超时，看起来像"面板没渲染 / 懒加载坏了"。
   修法是宽屏那一支**不绑** onClick（窄屏没有 Popover 包着才需要自己开）。
2. **一打开下拉只剩已生效的那一条**。`AutoComplete` 默认拿**输入框当前值**过滤，
   而当前值就是现在生效的模型名 ⇒ 用户点开看"还能换成什么"，看到的却是"现在这个"。
   这条是 AC-1 首跑（4 条候选只出 1 条）直接抓出来的，修法：只在**真正打字**时才过滤
   （`onSearch` 置位、`onSelect` / `onBlur` 复位）。
3. **我自己写错过一条判据**：AC-4d 原本要求 tooltip 里出现「智谱官网人民币标价」，
   可那句在服务端给的 `pricing_basis` 上、只出现在**面板**的价行（AC-2 钉着它），
   而 composer 读数那条链（`utils/modelLabel.ts`）本来就不带 basis
   ⇒ 前提不成立的是我的断言，不是页面。改断言、不改页面，并且把这次写错留在文档里。
   留这一条是因为它长得非常像"页面少渲染了一句"，容易将错就错往页面里补一句重复话。
4. **弹层开合不许靠猜 `Escape`**。AntD 的 Popover 不是"按 Escape 一定关"，
   而探针后面十几条都建立在"此刻它是开 / 关"上。所以 `closePanel()` 写成
   按一次 → **量真实可见性** → 还开着就补一次外部点击。否则一次库行为变化
   会把后面整段一起带倒，而报出来的还是"面板没渲染"那种误导性结论。

判据里最值钱的一条是 **AC-13**：把桩里的智谱那一档删掉 ⇒ 候选必须跟着少一条、
且界面里不再出现 `glm-`。这是"前端有没有偷偷再抄一份清单"唯一能证伪的写法
（正向断言"数量等于 catalog 长度"在只有默认那一家时是恒真的，所以两半都要有）。

### 主题切换挪到右上角（同一趟，AC-17 … AC-23）

他补的一句"把主题颜色切换也放到右上角"。挪法本身两行 JSX，值得写下来的是三条判据的形状：

- **AC-17 是前件**：先钉"这一趟真的开在 `scheme` 那一档"（`data-theme` 与 `localStorage` 都读）。
  没有它，"点一下换了"可能被"本来就没换对"蒙过去 —— 探针自己把键名写错就是这么个错法。
- **AC-22 钉的是"只有一枚"**：`.rail-foot button` 计数为 0 且全页 `button[aria-label*="主题"]` 为 1。
  这条是**跑过负面对照**的：把图标栏那一枚加回去 ⇒ `74 通过 / 76 断言`，红的恰好是
  light 与 dark 的 AC-22 两条（`{"railButtons":1,"themeButtons":2}`），其余 74 条不受影响。
  也就是说这条判据咬得住"顺手在侧栏也放一枚"这种回潮，而不是只描述当前形状。
- **AC-23 量的是顶栏宽度**，不是面板宽度：多一枚 34px 的按钮把 `.topbar-actions` 撑出视口，
  AC-16 那一屏（量抽屉里的 `.model-settings`）是看不见的。390 实测
  `worstRight 376 / vw 390 / docScroll 390`，右上角四件事（体检 · 主题 · 齿轮 · 刷新）都在屏内。

顺带改口一处注释、删一条 CSS：`lazy.cjs:43` 原来写"只数 `.rail-nav` 是因为 `.rail-foot` 还有一枚
主题切换" —— 那句理由现在不成立了，但**写法要留**（栏脚以后再加东西不该让"外壳没掉件"那两条莫名变红），
注释已按这个口径重写；`.rail-divider` 那条规则随它唯一的引用一起删掉（`grep` 全仓含 `tools/` 只剩定义本身）。

### 设置中心（AD 趟，99 条断言 · 十二个 context）：一屏五个口径 + 底部那一栏 + 这一屏的形状

「运行配置」从一颗输入框扩成"预设 + 基础/模型/高级"之后，这一趟管的是五种"界面在说谎"的形状
（⑤「字段名与单位也归响应」是 §2.1 对账时补的：那一轮把 ``fields[].label`` / ``unit`` 升进契约、
把界面自带那张 ``CONFIG_LABELS`` 删了）。十个 context 各自换一份 `/config/agent-options` 桩，
**桩里的数值、边界、措辞、单位一律不等于后端真值**
（默认轮数 6 而非 5、评审线 8 而非 7、检索条数 7 而非 5、三档预设 1/4/9 轮与 ¥0.13/0.66/6.66
而非 2/3/10 与 ¥0.07/0.35/3.55、超时 15..1800 步长 15 而非 30..3600 步长 30、
预算上界 1000 而非 50、迭代上界 12 而非 10、评审线上界 12 而非 10、
单位写成"次/档/块钱/秒钟/篇"而非"轮/分/元/秒/条"）—— 桩值等于真值时，"界面读的是响应"
这类判据恒真（Z 趟 R-03 同一口径）。本轮对账抓到**三处撞车**，都在 ``mocks.cjs`` 的注释里留了字：
``defaults`` 那个 7、``timeout_s.max`` 那个 3600、``review_threshold`` 的整条 0..10。
⚠️ 还有**一处故意留着**的巧合：``max_cost_cny.step`` 桩与后端都是 0.01 ⇒ "小数位取自 step"
今天不可证伪（改回旧的那个 ``key === 'max_cost_cny' ? 2 : 0`` 探针不红）。原因是动它会连带
把预设 ¥6.66 显示成 ¥6.7、牵动 AD-03 那件别的事；要覆盖就单独加一条，别顺手改桩。
同理，"输入框的界跟着响应走"今天**没有**判据（数值行只测控件在不在、读数与后缀的来源），
所以它不算死判据 —— 将来加的时候读 ``aria-valuemin`` / ``aria-valuemax``，
rc-input-number **不给 input 写 HTML ``max`` 属性**。

- **① 只有一份状态（AD-04/05/09/10）**。判据是**双向**的：面板套预设 ⇒ 右下角读数跟着变（AD-04）、
  面板手改 ⇒ 读数跟着变（AD-05）、面板取消勾选 ⇒ composer 那颗开关自己灭（AD-09）、
  点 composer 开关 ⇒ 面板里那条复选框回到勾上（AD-10）。只测一个方向时，
  "两份本地 state 各自被对方同步一次"的写法照样全绿 —— 这正是负面对照要打的形状。
  ⚠️ AD-09/10 之间必须**重新打开弹层**：点 composer 是弹层外的一次点击，AntD Popover 会自己收起
  （内容仍在 DOM 里但点不动，第一次跑就栽在 `element is not visible`）。这顺带证了一件事：
  弹层关掉之后状态照样活着、照样参与请求体。
- **② 只有一份清单（AD-07/16）**。工具勾选清单逐条等于桩里的 `GET /tools`（六条，含页面
  从没写过的 `extract` / `file_io` / `web_search`）。配套改的是 R 趟那条旧断言：
  原来它断言"关掉 RAG ⇒ `enabled_tools=['calculator','code_exec']`"，而那份名单是
  `client.ts` 里写死的 —— **断言跟着假名单一起绿**，永远看不见"关 RAG 顺带停了三个工具"。
  现在期望值由 `toolsBody.items` 算出来，前端再抄一份名单立刻红。
- **③ 没碰过的键不发（AD-16/22/28）**。三个档位（完整响应 / 少字段 / 端点 404）各钉一次键集合：
  完整那一档只发碰过的三项，少字段与降级两档**只有 `task`**。R 趟 ③ 的期望值也一起改口了 ——
  旧断言那个 `['max_iterations','task','use_tools']` 本身就是"前端替后端补默认值"。
- **④ 后端原话落屏（AD-11…14、19…25、29、30…32、38…41、45…50）**。`accepted=false` 没控件、只在
  「后端暂不支持」里列 **key + label + help 三件**（AD-39：少了 key 出事对不回请求体，
  少了 help 只说"不行"不说为什么）；"有界但没声明"与"声明能配却没有行"两类分开点名
  （AD-20 / AD-41，都来自新增的 ``unrecognized.unrowedFields``）；未知顶层键以 JSON 原样透出；
  软上限那句"节点之间才检查"必须是正文不是 tooltip；422 的 HTTP 码 + `code` + `request_id` +
  服务端原话四样一起进实时日志（`.log-row--error`），且页签停在日志那一屏。
  AD-40 钉的是另一种说谎：界面上显示着后端给的默认 8 分 ≠ 用户发了 8 分，没碰过就不该发。
  ⚠️ **`accepted=true, enforced=false` 那一半原先只有代码、没有判据**（AD-45…49b 是补的）：
  后端八条声明里七条 `enforced=true`、第八条 `reviewer_enabled` 是 `accepted=false` ⇒
  真环境与桩里都没有"收了但不执行"这一档，于是"把底部那栏删掉"或"连控件都不画"两种改法
  一条都不会红。现在 `future` 那一档把 `rag_top_k` 改成 `enforced=false`（**假后端**，不是预言），
  量五件事：控件照旧在场（AD-46）、后端 help 以正文在场 + 行内一句"没有执行机制"（AD-47）、
  底部那栏点名 key + label 且与「暂不支持」**分成两栏**（AD-48）、填得进去且**真的进请求体**
  （AD-49 / 49b）、以及那句 help 在这一屏只出现**一次**（AD-50 —— 底部再抄一遍就红，读数 `2`；
  行整个消失也红，读数 `0`）。两栏义务不同：`accepted=false` 那栏没有行，少了 help 就没有原因，
  所以那里必须三件齐；`enforced=false` 这栏上面一定有行，重复就是"同屏两份同样的话"。
- **⑤ 字段名与单位也归响应（AD-37/37b/37c + 29a + 04/05/41b 的单位那一半）**。本轮 §2.1 对账
  把 `label` / `unit` 升进契约、把界面那张 ``CONFIG_LABELS`` 删了，所以这一族是**反向哨兵**：
  AD-37b 逐行比对"界面 = 桩的措辞（次·档·块钱·秒钟·篇）"，AD-37c 反过来要求屏上**一个**
  后端措辞都不许出现（轮·分·元·秒·条 / 最大迭代轮数…）。反例清单故意写在后端那一版，
  后端改措辞时要跟着改的是桩和这份反例，不是界面。回执对账那几行的小字同源（AD-29a）。
- **⑥ 底部那一栏与「去设置」（2026-09-27 界面优化那一轮补的九条，新场景 s9）**。
  补的东西只有一件：**把从来没有 UI 调用过的 `reset()` 接到一颗按钮上**，并给它一个
  跟它同源的改动读数（`draft` 的显式键数 + 被取消勾选的工具数，两个都从 Context 算，
  不另起 `dirty` state）。判据分三层：AD-51/52/53 是"读数、亮起、撤回"这一条链的三个面，
  AD-54 判**请求体**（撤回后提交只剩 `task`）——⚠️ 这条单独不可信，见下面第 5 条坑。
  另两条是这一轮顺手补上的：AD-55/55b 判「去设置」那颗**跨组件**入口（点了顶栏那份
  模型设置真进 DOM、且运行配置这一层自己收起 —— 读点是 `.rcp-pop` 上的
  `ant-popover-hidden`，只看 `.rcp` 还在不在会被 AntD 的"关了不卸载"骗过去）；
  AD-56/56b/56c 判高危浮层里那段"沙箱 / Python / 超时"的来源：现在它是
  ``GET /tools`` 的 `description`，桩里写 **20 秒** 而后端真值是 30 秒 ⇒ 出现 20 才叫读了响应，
  出现 30 就是前端又抄了一份实现描述（与 AD-37c 同形的反向哨兵，那个"30"会随实现过期）。
  ⚠️ AD-56 的读点第一版写成"把所有 `.ant-tooltip` 拼起来"，于是把 composer 那颗悬停提示
  也读了进来 —— 判据照旧绿，但它已经不再只检查自己声称检查的东西；改成顺
  `aria-describedby` 取**这颗触发器自己**那枚浮层，并给"取不到"留了一条前件。
  ⚠️ **这一轮没做的**：「应用」那颗按钮。面板没有"提交"这条路（改动即时进 Context，
  在点提交任务那一刻才算请求体），所以它不控制任何东西；要它就得先定
  "没点应用之前改动算不算数" —— 那是语义改动，另开一趟（连同 `buildRunConfigBody`
  的调用点与 AD-04/05/16/22/28/40 那一整族要跟着改口）。
- **另三条口径**：AD-33/34 = 390 挂 Drawer 且零横向溢出；AD-35/35b + AD-42/43 = 深色与 warning
  底上的 AA（**十二类**小字 × 各自真实底色，**前件**那两条要求每类选择器都真量到，
  某类为空是选择器写错、不是通过）；AD-44/44b = 等宽令牌真的生效 —— 它抓到过一次真实的
  静默失效：``--font-mono`` 在产物里**没有定义**（CSS 注释里写了个带"星杠"的路径通配，
  把块注释从中间关了），四条 ``font-family`` 全被丢弃，而 tsc / build / 其余判据一概不红。
  AD-44b 的前件同时防"只有一处挂载就蒙过去"。
  ⚠️ 深色那一档（s8）从 ``base`` 换成 ``future`` 桩是**为了让第八类进得来 DOM**：
  ``.rcp-warn``（"后端会收下但没有执行机制"那句行内警告）自带 ``--warning-soft`` 底色，
  在 ``base`` 里永远不渲染 ⇒ 它属于"新写的文字从来没被量过对比度"。``future`` 是 ``base``
  的超集，原来那七类照样量得到。
  ⚠️ 同一档 2026-09-27 又补了**四类**（``.rcp-footer-hint`` / ``.rcp-model-goto`` /
  ``.rcp-model-tier`` / ``.rcp-model-src``），理由与 ``.rcp-warn`` 那条一模一样：
  底部那栏与两枚 Tag 是这一轮新写的字，而**档位 Tag 自带 AntD 预设底色**
  （blue/cyan 在深色下是浅底深字，不量就等于没验）。s8 因此从"只点高级页签"改成
  **高级与模型都点一次** —— 页签首次激活才挂载，少点一个就是那一族类读回空数组，
  而空数组在前件那一条里必须是红的（清单也顺手收成了 ``AA_CLASSES`` 一份，
  以前判据与前件各抄一遍八项，改一项就会漏另一项）。亮色那一面这轮是**手量**的：
  5.50 / 16.93 / 5.17 / 5.12 / 5.12（强档 / `.env` / 去设置 / 读数 / 撤回），
  没有落成常驻判据 —— 要钉住得给 s8 再开一档 light。
- **AD-29 那一族值得单写**：回执整个缺席（老后端 `extra=ignore` 把新键静默丢掉）与回执把 8 钳成 4
  是**两种坑**，所以 `data-code` 分 `RUN_CONFIG_UNACKNOWLEDGED` / `RUN_CONFIG_MISMATCH`。
  ⚠️ 结论不能只写进日志缓冲区 —— 终态会整包补拉 trace 并 `replaceEvents`，一条只活一秒的告警
  等于没说过。所以它落在运行条下方那条**常驻**提示里（AD-29c 等的就是补拉之后还在），
  日志里只留一句不带数字的交代（同屏两份同样的数是这一轮清单 P0 反掉的形状）。

六组负面对照（改源码跑一次即撤，读数都是**自己 grep 回来的那一行**。
本轮界面优化把分母从 63 抬到 **72**，六组里**只重跑了 AD-neg1**（新那九条与它同一条链，
必须核它咬不咬得住）；其余五组那一列**分母作废**（63 时代的读数），
红的判据预期不变，但**别拿它当本轮结论** —— 要新数字就再跑一趟，别抄旧数）：

| 摘法 | 红的判据 | 读数 |
| --- | --- | --- |
| AD-neg1 面板勾选改成局部 `useState` | AD-09 / AD-10 / AD-16 / **AD-52**（+ AD-53 起不来） | 本轮重跑：**红四条后进程 exit=1**，AD-54/55/56 没跑到 |
| AD-neg2 `NumericRow` 只认"有没有界"、不认 `accepted` | AD-36（只这一条） | ~~62 通过 / 63 断言~~（分母作废，未重跑） |
| AD-neg3 `buildRunConfigBody` 回落 `max_iterations: 3` | AD-22 / AD-28 | ~~61 / 63~~（同上） |
| AD-neg4 名字/后缀与页脚读数写回前端那张表 | AD-04 / 05 / 25 / 37b / 37c / 41b | ~~57 / 63~~（同上） |
| AD-neg5 摘掉「后端会收下，但当前没有执行机制」那一栏 | AD-48（只这一条） | ~~62 / 63~~（同上） |
| AD-neg6 把 `enforced=false` 当成"不支持"（连控件都不画） | AD-46 / 47 / 49 前件 / 49b / 35b / 50 | ~~57 / 63~~（同上） |

六条各自只咬住该咬的那几条（AD-neg1 连请求体那一条都一起红了 —— 面板改本地那份、
请求体算 Context 那份，两边当场分叉），这就是"判据可证伪"的形态，不是描述当前实现的注释。
四处要记住的坑：

1. **AD-neg1 第一版没咬住**（56 全绿）。那次只把"读数"换成局部 state，`onChange` 还在写 Context
   ⇒ 负面对照自己是假的时也会全绿，所以每条都要核"红的是不是该红的那几条"，不能只看总分下降。
2. **AD-neg2 的红条换了人**。上一版记的是"红 AD-20"，本轮改成只红 AD-36：那半个闸门同时是
   "键压根不在 `fields[]` 里"时的兜底，摘掉后 `field` 是 `null`，读它的 `help` 直接抛 ⇒
   pageerror 那条（AD-36）红，而 AD-20 那段"有界没声明"的文案由别的分支渲染、照旧绿。
   ⚠️ 这一组**咬不到 AD-11**：`reviewer_enabled` 不在行表里，闸门再宽也不会给它画控件 ——
   那条要靠行表本身（``BASIC_ROWS`` / ``ADVANCED_ROWS``），别以为它被覆盖了。
3. **AD-neg4 会同时把后端的用例弄红**：``tests/unit/test_run_config_frontend_contract.py`` 里
   "前端代码不许出现后端的字段名与单位字面量"那两条静态审计（本轮为了证明它不恒真，
   临时塞过一个字面量看过一次红）。也就是说这一族坑有**两层**网，探针与 pytest 各抓一半。
4. **AD-50 那类"只出现一次"的判据，两种失效都要红**：底部再抄一遍 ⇒ 读数 `2` 红；
   整行被"当成不支持"删掉 ⇒ 读数 `0` 也红（AD-neg6 实测就是这个形状）。
   写成 `<= 1` 就只剩前一半有用，后一半正好是"界面什么都不说"那种最坏的失效。
   ⚠️ 分母换了三次（41→56→63→**72**）：41→56→63 那两次六组对照**全部重跑**过，
   第三跳（本轮界面优化）只重跑了与新增同链的 neg1，其余五组按上面的表标了作废。
5. **底部那栏三条判据必须成对读，AD-54 单独不可信**（AD-neg1 实测出来的形状）：勾选改成
   局部 state 之后，请求体那一条（AD-54：撤回后提交只剩 `task`）**照样是绿的** ——
   Context 压根没收到那次取消，所以它"撤回成功"的姿势和真的撤回了印出来一模一样。
   红的是 AD-52（读数不跟着变）与 AD-53（撤回按钮永远灰 ⇒ 探针在这一步 `element is not
   enabled` 超时、进程 exit=1，后面三条没跑到）。⇒ 凡"点了没反应"类的控件，
   **正面那条（改动有没有进状态）与结果那条（请求体/网络）要各一条**，只有后者等于没判。

**本轮收口（第二遍逐条对账，五句话，给下一个只读这段的人）**

1. 补完之一 —— U-7 的"复用"落到一份模块：页签错误边界抽成 ``src/components/paneBoundary.tsx``
   的 ``withPaneBoundary(位置名, children)``，宿主与面板各自只留"位置名从哪来"这一份知识，
   兜底卡上那句 ``basic 页签``（拿路由 key 当中文名）同时消失。
2. 补完之二 —— 契约要点 1 的第二半从零判据补到六条：`accepted=true, enforced=false`
   这一档在真环境与旧桩里都不存在，所以以前"删掉底部那栏"和"连控件都不画"两种改法一条不红。
3. AD 从 56 涨到 **63**，新增的七条全部落在已有的 ``future`` context（**没有新开页**）：
   AD-45 前件 / 46 控件在场 / 47 help 正文 + 行内警告 / 48 底部只列 key+label 且分栏 /
   49 + 49b 填得进去且真进请求体 / 50 那句 help 全屏一次；深色那一档（s8）跟着从 ``base``
   换到 ``future``，AA 才从七类补到八类（``.rcp-warn`` 自带 warning 底色，不换桩进不了 DOM）。
4. **已知限制（不排期，两条）**：① "输入框的 min/max/step 跟着响应走"今天没有判据 ——
   数值行只测控件在场与读数/后缀的来源，桩里那五个界已先与后端错开，将来加判据读
   ``aria-valuemin`` / ``aria-valuemax``（rc-input-number 不写 HTML ``max``）；
   ② ``max_cost_cny.step`` 桩与后端都是 0.01 ⇒ "小数位取自 step"今天**不可证伪**，
   动它会连带牵动 AD-03 的预设读数，所以故意留着（理由写在 ``mocks.cjs`` 注释里）。
5. 对外口径：这两条不是漏检，是"识别到了但目前不可证伪 / 判据要单独加"，说清楚比假装覆盖强。

#### 2026-09-27 改形那一趟（72 → **83** 条 · 开页没变，仍是 11）

「运行配置」那层 380px 的水平页签 Popover，换成 720px 的**左侧导航 + 右侧内容 Modal**
（他给的一张 WorkBuddy 设置截图做参照）。**一个控件、一句话都没新增** ——
预设方案归「基础」、`review_threshold` / `rag_top_k` 与三栏降级信息归「高级」、
「填入示例」整块**搬**到任务输入框下方。DOM 里那些 `rcp-*` 类名**一个都没改**：
只换容器类（`sc-nav` / `sc-card` / `sc-pane` / `sc-foot-env`），
因为"判据跟着实现改名"正是最容易把"其实没验了"混进绿灯里的动作。

探针这一趟改的六处，每一处都是一条会复发的坑：

| 改了什么 | 为什么必须改（红过才写的） |
| --- | --- |
| 9 处 `.rcp-tabs .ant-tabs-tab` → `.sc-nav-item` | 页签没了。驱动换、判据文字不换 —— 那 9 处后面读的还是同一批类 |
| `.ant-popover` → `.ant-modal`（AD-49 那枚 `softInput` 的读点） | 读点带容器前缀 ⇒ 容器一换就**静默量不到**，`hasInput` 却仍然 true（它读的是 `.rcp` 里面），第一版就是这么红了 AD-49 而不是红在选择器 |
| `openPanel` 改成**幂等**（已开着就直接返回） | Popover 时代"再点一次触发器"是安全的；Modal 有遮罩，开着再点 ⇒ 命中测试被 `.sc-card` 挡下 ⇒ TimeoutError |
| 新增模块级 `closeSettingsLayer(page)`，点 composer 控件前先调（18 处） | 这一层是模态的 ⇒ 真用户隔着遮罩也点不到提交按钮。这不是测试环境的假象，是"模态"这条语义本身 |
| 它点的是右上角那颗 X，不是 Esc | **Esc 的事件挂在 dialog 上，焦点不在这一层里时收不到** ⇒ Esc 是空操作，下一句点 submit 才 TimeoutError，红得毫无线索。AD-55d 那条判据量的才是"焦点在里面时 Esc 关得掉" |
| AD 的 `newPage` 里给 `/api/models` 换成带 catalog 的桩 | 「模型」格里内嵌了模型设置那份；默认桩没有 catalog ⇒ 它走"没读到候选清单"那一支、`KeySection` 整块不挂载 ⇒ AD-55b 读回空数组，看着像"没挂载"而不是"实现忘了加前缀" |
| s2 / s3 两个场景补 `openAdvanced(page)` | 三栏降级信息从"容器外面永远在场"搬进「高级」这一格 ⇒ 不点就没有，读回 `''` 与"界面没说话"长得一模一样（AD-20/23/24/41 第一版全红在这里） |

判据这一趟净增 11 条：

- **AD-57…AD-62 + AD-65**（这一屏的形状）：导航三项与默认选中、默认只有「基础」可见、
  承载面宽度落在 720±10、**一行的几何**是"标签+描述在左、控件在右"
  （读 `getBoundingClientRect`，不读类名 —— 类名都写对了而 grid 忘了写，界面照样上下堆）、
  「回落到 .env」这一屏只有一颗、切两次导航后可见那格跟着换、
  切过去那一瞬新格子的淡入**真在跑**（中途读 `opacity` 落在 0.55–1 之间，
  不是"声明了 animation 就算数"）。
- **AD-55 拆成四条**：原来判的是「去设置」那颗跨组件按钮（点了开顶栏那层、自己收起）。
  那颗按钮随"模型设置内嵌"一起删了 ⇒ 换成：内嵌那份在场且这一屏只有一份 `.model-settings`、
  它的 id **全部带 `sc-` 前缀**（两个宿主同时挂载时重复 id 会让判据与读屏量错那一份）、
  旧入口与那条 `window` 事件桥都不在了、Esc 关得掉这一层
  （判**可见性**不判存在性 —— Modal 关了不卸载，"在不在 DOM"是另一件事）。
- **AD-63 / AD-64**（快捷示例搬走之后）：这三颗改前**一条判据都没读过**
  （`grep cfg-ex running.cjs` = 0 命中）⇒ "搬丢了"不会有人发现。
  位置判"在 textarea 之下、仍在 `.composer` 里、`.rcp` 里已经没有它们"；
  动作判"三颗各点一次 ⇒ 三条互不相同且都非空、焦点回到输入框、一次请求都没多发"。
  ⚠️ 判据里**不写示例正文的字面量**（那是前端常量，写死等于探针读自己）。
- **AA 清单里 `.rcp-model-goto` 换成 `.sc-nav-item`**：那颗 link 按钮没了。
  换它进来不是凑数 —— 左导航是这一屏唯一一处**同一语义落在两种底色上**的文字
  （选中压在 `--primary-soft`、未选中压在 Modal 的 `--bg-app`），
  那个循环会把三个节点各量一次，正是"同一语义要在每种行底色上各量一次"那条口径。

四张新截图（`shots/running/`，都是探针驱动后的状态 ⇒ 文件名带 `AD-settings-*`，不复用出厂态那批）：
`AD-settings-basic.png` / `AD-settings-model.png` / `AD-settings-advanced.png` /
`AD-settings-switch-frame.png`（最后一张是切换中途那一帧，量到的就是 AD-65 那个读数）。

**两组负面对照（各跑一次，跑完已还原并逐文件 `cmp` 过）**

| 改坏什么 | 红的正好是 | 读数 |
| --- | --- | --- |
| 把 `.rcp-row` 的 grid 换回 `flex-direction: column`（类名全留着，只是"忘了写行式布局"） | 只红 **AD-60** | 82 / 83，`ctlRightOfLabel:false`、`ctlRightEdgeNearRow:false` |
| 把内嵌那份的 `embedded` 改成 `false`（同名按钮与未加前缀的 id 都回来了） | **AD-61 + AD-55b** | 81 / 83，AD-61 读数 **2**、AD-55b 读数 `["model-large","model-small","model-key-provider","model-key-input"]` |

⚠️ 第二组**第一版只红了 AD-55b**：那时 AD-61 写在切导航**之前**，内嵌那份根本还没挂载 ⇒
数出来永远是 1。⇒ 条件渲染的东西要在它存在的那一格里量，这条本轮在自己写的判据上又踩了一次
（挪到「模型」挂载之后再跑，才是上面那行读数）。

**产物差额（同一棵树 build 两次，中间只 `git stash push -- src`，跑完 pop 并逐文件 `cmp`）**

| 那份 chunk | 改前（raw / gzip） | 改后 | 差额 | 谁付 |
| --- | --- | --- | --- | --- |
| `RunConfigPanel-*.js`（懒加载） | 7.56 / 3.53 kB | 9.12 / 4.43 kB | **+0.90 kB gzip** | 只有点开设置那一层的人才付 |
| `ModelSettings-*.js`（懒加载） | 9.41 / 4.68 kB | 9.52 / 4.75 kB | +0.07 kB | 点开齿轮或「模型」那一格 |
| `TaskLogPage-*.js` | 231.38 / 76.62 kB | 231.61 / 76.66 kB | +0.04 kB | /tasks 一路 |
| `antd-*.js` | 1,025.71 / 322.82 kB | 1,028.81 / **323.82 kB** | **+1.00 kB（Modal 第一次进这一份）** | 首屏 |
| `index-*.css` | 66.04 / 12.04 kB | 68.94 / 12.56 kB | +0.52 kB | 首屏 |
| 首屏 JS 合计 | 362,687 B gzip | 363,606 B gzip | **+919 B（+0.25%）** | 三页一起 |
| 全站 JS 合计 | 820,795 B gzip | 822,725 B gzip | +1,930 B | — |

入口占比 0.442（门槛 ≤0.70）、echarts 仍不在首屏、`bundle.cjs` 6 / 6。
⚠️ 那 +919 B 里最大的一块是 **antd 那份 +1.00 kB**（全站第一次用到 `Modal`）——
左导航本身是**手写 `button role="tab"`**，没有把 `Menu` 拉进这一份 chunk（三行文字换一整枚
组件不值，代价是自己养 roving tabindex 与方向键，判据 AD-57 / AD-62 读的就是这两个属性）。

#### 2026-09-27 第二趟：960×600 与"少写一半的字"（83 → **99** 条 · 开页 11 → 12）

同一屏的纯排版与文案一趟：容器从 720×720 换成 **960×600**（比例 1.6）、左导航 180→160、
右格限宽 720 且靠左；模型候选改成**两行一项**并把弹层加宽到 `min(600px,90vw)`；
「按角色分配（只读）」改成「角色模型映射」并删掉那句长解释；Key 那一栏标题缩成四个字、
三行标签对齐到 80px、状态行压成一行、按钮改「应用到本次运行」；向量模型缩成一行 + ⓘ。
**契约、提交体、类型、后端一行没动。**

这一趟对探针是四件事，其中两件是**上一趟留下的债**：

| 改了什么 | 为什么 |
| --- | --- |
| 修 B 趟那条 UI-5 判据：从"命中的元素类名里有 mask"换成"命中的不是 textarea、且属于 `.ant-modal-root` 那一层" | 上一趟写窄了。720（现 960）的模态正好压在输入框上方 ⇒ 那一点之下命中 Modal 的**内容**（`DIV.sc-body` / `DIV.ant-modal-header`），内容本来就在遮罩之上。命中内容同样说明这一击到不了 textarea，而旧写法两条场景各红一次 |
| R 趟两处读点 `.ant-popover .rcp …` → `.ant-modal .rcp …`；③ 那档的前件从"数 `.ant-popover`"换成"数面板本体 + `.ant-modal`" | 上一趟只扫了 AD 那一趟，别处的旧前缀没跟 ⇒ 全量跑到这里 `locator.fill` 超时**中断整趟**（后面的趟一趟没跑到，连总数都没打印）。前件数一个不可能出现的类 = 恒真 |
| R 趟收尾那下 `page.keyboard.press('Escape')` 换成 `closeSettingsLayer` | 与上一趟 AD 里踩过同一坑：Esc 挂在 dialog 上，焦点不在层里就是空操作。这里虽然后面还有一次兜底，但"看起来收了其实没收"不该留在链上 |
| `AA_CLASSES` 八类 → 十五类里的新三类：`.ms-opt-name` / `.ms-opt-sub` / `.ms-key-note`；s8 因此**先把下拉打开**再量 | 两行候选是新写的字，而它压在弹层自己的底色（`colorBgElevated`）上，不是 `--bg-surface` ⇒ 不在任何底色上量过就等于没验。⚠️ 打开下拉要点得动那一格：停在「高级」时「模型」是 `hidden`，hidden 里的 input **存在但点不动**（AD 与 s8 两处都撞在这里） |

判据净增 16 条：**AD-66…AD-74**（+ AD-69b/c/d、AD-71b、AD-72b/c 四小条）。
形状量的是几何不是类名：整窗 960×600 与比例、导航 160、右格 ≤720 且**左间隙==内边距**
（写成 `margin:auto` 就变成居中窄栏，浅色底上肉眼看不出来）、**切三格整窗高度三次数值全等**、
弹层宽 = `min(600px,90vw)` 且 DOM 里的候选条数 = 响应的 catalog 条数、
两行不横向溢出（`scrollWidth<=clientWidth`）且 `white-space` 真的是 `normal`、
每条候选的第一行**就是一个模型 id**（逐条收下来按 id 找第二行，不是拿第一条的读数比第二条）、
Key 三行标签/控件左缘对齐 + 控件右缘==行右缘、状态行四项全来自响应、
两颗 ⓘ 顺 `aria-describedby` 真取得到浮层、向量模型那一行没有按钮。
「角色模型映射」两种形状**成对钉**：AD-73 全同源（并成标题旁一句、逐行 Tag 不画）
与 AD-74 混档（Tag 逐行回来、总注整块不画）—— 只钉一边，等于"当前来源：.env"写死也能过。

**两条判据不重复，是负面对照逼出来的分工**：AD-66 量"当前那一格"的窗口尺寸，
被 `max-height` 顶到 600 时它看不出来；有牙的是 AD-68。

| 改坏什么 | 红的正好是 | 读数 |
| --- | --- | --- |
| NC-geo：`.sc-modal .ant-modal-content` 的 `height` 换成 `height:auto; max-height:…` | 只红 **AD-68** | `{"基础":543,"模型":600,"高级":600}` —— 基础那一格内容短，窗口跟着塌 57px |
| NC-69：拿掉 `popupMatchSelectWidth={false}` | 只红 **AD-69** | `w:280 / wantW:600`，两行与折行照旧成立（`twoLines:true`、`wrap:"normal"`）⇒ 三条属性各管一件事，没有一条是凑数的 |

⚠️ NC-69 顺带量到一条事实：把 `virtual={false}` 删掉，DOM 里的候选条数**不变** ——
rc-select 里 `realVirtual = virtual !== false && dropdownMatchSelectWidth !== false`，
弹层不跟输入框同宽时虚拟列表自己就关了。组件注释里那条"为什么看得见全部候选"说的是这个。

**桩跟着改了两处**（不改这两处，新判据就是恒真）：`agent-options` 的 `models.roles`
从 2 条补到 5 条（与后端 `role_map` 同条数 —— 两条的时候"两列排几行"从来没被量过），
新增 `mixed` 一档（其中一条 `source=override`）给 AD-74；
`AE-11b` 原来把行数写死成 2 ⇒ 改成从桩读。

**AE-1 换判法**：标题从一整句缩成「API Key 配置」，那三条约束搬进 ⓘ ⇒
判据改成"标题在场 + 顺 `aria-describedby` 真取到浮层且里面是原话"两条一起（只判标题会永远红，
只判浮层则读点写错就恒真）。按钮改名 ⇒ `clickBtn('应用到本次运行')`。

五张截图（`shots/running/`）：`AD-settings-basic/-model/-advanced/-switch-frame` 之外，
新增 `AD-settings-dropdown.png`（候选下拉展开那一帧，两行一项 + 600 宽）与
`AD-settings-keybox.png`（Key 那一栏在 600px 高的窗口里落在折叠线以下，单独留一张）。

### 面板收 Key（AE 趟，亮 32 条 + 暗 5 条 · 两个 context）：一屏之内"只进不出"怎么判

用户拍板 U-1…U-7 + 四条补充约束之后，模型设置面板第一次开始**收**凭据。
这一趟的判据不冲"界面好不好看"，冲的是四条只在浏览器里才看得见的失效形状：

| 判据 | 钉住的那件事 | 为什么不能只靠后端用例 |
|---|---|---|
| AE-2 + AE-2b | 输入 → blur → 再聚焦，``input.value`` 是**真空串**且不回填 | 后端根本不知道 DOM 里留着什么；录屏安全是纯前端属性 |
| AE-4 / 4b / 4c | 那句"超时上限 4.5 秒"与"报出 7 个模型"来自**响应**；端点一致时不重复一遍 | pytest 只能证明字段在响应里，证明不了界面读它 |
| AE-7 / 7b / 7c | 明文只出现在请求体；URL 是常量、无 query；校验**不**改状态 | 客户端拼 URL 这一步在 TS 里，Python 侧看不见 |
| AE-10 + 10b | 网关档整块输入框**缺席**、只点名；非网关档必须有框 | 「不画」与"画了但没生效"在响应上完全同形 |
| AE-12 + 12b + 12c | 换模型后请求体是新值，且「运行配置」那一屏跟着换 | invalidate 是 react-query 的事，后端只见得到第二次 GET |

桩的三条纪律（与 AD 同一套）：① ``timeout_s`` 给 **4.5**（后端真值 3.0）、模型条数给 7、
耗时给 123 —— 界面印出 3 就说明它写死；② ``providers[]`` 补齐 ``key_source`` /
``own_key_configured`` / ``own_key_env_var`` / ``env_channel`` 四个新字段，
且 ``postKey`` 会**四个一起动**（只翻 ``key_configured`` 就会出"已配置但来源还写着 env"）；
③ ``validateKey`` 按 Key 前缀分三支（``sk-AEOK`` / ``sk-AEBAD`` / ``sk-AESLOW``），
失败那支吐的是智谱那句 ``1002 Wrong API key`` 原文，界面不许改写成"Key 无效"。

**这一趟抓到三件真缺陷**（都不是探针错）：

1. **"已暂存"那行把第一次点击吃掉了。** 它原来夹在输入框与按钮之间，只在 blur 那一刻出现：
   mousedown → blur → 插入一整行 ⇒ 按钮在 mouseup 之前往下跳一行 ⇒ 浏览器的 click 落在
   共同祖先上，React 的 ``onClick`` 根本没跑。人看到的就是"点了校验没反应，要点第二下"。
   判据是 AE-4d（点第一下**就**要发一次请求，数的是请求次数不是文案），修法是把这些
   "做过一步才出现"的文字统一挪到控件**下面**（``ModelSettings.tsx`` 里有注释）。
   ⚠️ 这类缺陷只在真鼠标事件序列下现形：换成 ``dispatchEvent('click')`` 就测不到 ——
   调试时我先用了合成事件，它"通过"了，而真点击一直不发请求。
2. **客户端那道"Key 不许进 URL"的自证把撤回掐了。** ``url.includes(body.api_key)`` 在
   ``api_key === ''``（= 撤回那把）时**恒为真**（空串是任何串的子串），于是撤回请求
   在浏览器里就被拒掉，报出来的还是一句谎话"Key 出现在 URL 里"。判据 AE-8e。
    ⇒ 凡是"拿值当参数做包含检查"的守卫，先问一句空值怎么走。
3. **换模型之后「运行配置」那一屏停在旧模型名上。** 全站 ``staleTime=30_000`` ⇒ 重新打开
   那个浮层**不会**补拉 ``/config/agent-options``，而那一屏的 ``models.roles`` 读的正是
   运行时覆盖。修法是在写侧成功后 ``invalidateQueries(AGENT_OPTIONS_QUERY_KEY)``
   （``useModels.ts`` 的 ``settle()``，两个写端点共用一份）。AE-12b（请求数 +1）与
   AE-12c（屏上名字换了）成对读：只有 12c 会漏，只有 12b 又说明不了屏上对不对。

**负面对照两组（各跑一次，跑完已还原）**

| 摘掉的那一处 | 结果 | 说明 |
|---|---|---|
| ``onBlur={() => setShown('')}`` → ``setShown(shown)``（AE-2 的正面判据失效） | **35 通过 / 37 断言**，红的恰好是 AE-2 与 AE-3，``afterBlur`` / ``afterFocus`` 都回读出整串 Key | AE-2b（前件：打字时框里确实有值）**照旧绿** ⇒ 这一对确实是"前件 + 判据"的形状，不是同一条判据被写了两遍 |
| ``useModels.ts`` 里那句 ``invalidateQueries`` | **35 通过 / 37 断言**，红的恰好是 AE-12b 与 AE-12c，``after`` 回读 ``["deepseek-flash","deepseek-flash"]`` | 12c 停在旧名 ⇒ 证明它不是靠"重新挂载就会补拉"蹭对的（30s 内确实不会补拉） |

两组都只红两条、且红的是该红的那两条 —— 分母 37 = 亮 32 + 暗 5（暗那一趟不参与负面对照，
它量的是对比度：网关块 8.10 / 标签 5.44 / 清单行 8.22 / 校验通过那句 9.39 / 失败那句 6.53）。

### 断言总数与开页数（只认探针打印的那一行）

设置中心那两趟（第一趟换容器 720×720、第二趟换 960×600 与文案，AD 72→83→**99**）之后：

```
running probe: 1040 通过 / 1040 断言 · 本次开页 103（导航 115）
```

（1013→1040 = AD 那两趟净增的 27 条（+11 / +16）；开页 102→103 = 第二趟为"来源不唯一"
那一档新开的 s10（AD-74 用），导航 114→115 同一页的 `goto`。
同一棵树上另跑过 `ONLY=AD`：**99 通过 / 99 断言 · 开页 12（导航 12）**、
`ONLY=AC`：**76 / 76 · 开页 8**、`ONLY=AE`：**37 / 37 · 开页 2**。）

产物大小那一笔（第二趟）——⚠️ 口径先说清：**没有再 stash 一次**，因为上一趟（换容器那一趟）
至今没单独提交，stash 的基线会是"两趟之前"，答的不是这一题。这里比的是**上一趟记录在案的
同一台机器、同一版 vite 的 build 读数**，中间只有我这几个文件的改动：

| 那份 chunk | 上一趟（raw / gzip） | 这一趟 | 差额 | 谁付 |
| --- | --- | --- | --- | --- |
| `RunConfigPanel-*.js`（懒加载） | 9.12 / 4.43 kB | 9.18 / **4.39 kB** | **−0.04 kB**（删掉那句长解释换回来的） | 点开设置那一层的人 |
| `ModelSettings-*.js`（懒加载） | 9.52 / 4.75 kB | 10.38 / 5.04 kB | +0.29 kB | 点开齿轮或「模型」那一格 |
| `TaskLogPage-*.js` | 231.61 / 76.66 kB | 231.63 / 76.68 kB | +0.02 kB | /tasks 一路 |
| `antd-*.js` | 323.82 kB | 323.82 kB | **0**（没引入任何新组件，ⓘ 那枚图标来自已经在用的 `@ant-design/icons`） | — |
| `index-*.css` | 68.94 / 12.56 kB | 69.95 / 12.74 kB | +0.18 kB | 首屏 |
| 首屏 JS 合计 | 363,606 B gzip | 363,609 B gzip | **+3 B** | 三页一起 |
| 全站 JS 合计 | 822,725 B gzip | 823,003 B gzip | +278 B | — |

入口占比 0.442（门槛 ≤0.70，与上一趟同一个数）、echarts 仍不在首屏、`bundle.cjs` 6 / 6。

面板收 Key 那一趟（AE 封两趟：亮 32 条行为 + 暗 5 条对比度）之后：

```
running probe: 1013 通过 / 1013 断言 · 本次开页 102（导航 114）
```

（976→1013 = AE 那 37 条；开页 100→102 / 导航 110→114 = AE 两个 context 各开一页，
导航 +4 是亮那一趟的 `goto` + `reload`（翻网关档必须重载，30s 内缓存不补拉）与暗那一趟的同两步。
同一棵树上另跑过 `ONLY=AE`：**37 通过 / 37 断言 · 开页 2（导航 4）**。）

产物大小那一笔（同一棵树 `npm run build` 两次，中间只 `git stash push --` 我这几个文件，
跑完 `stash pop` 还原并逐文件 `cmp` 过 —— ⚠️ 还原后行尾从 LF 变 CRLF，
`core.autocrlf=true` 下提交时会被归一化，diffstat 前后都是 `592 insertions / 30 deletions`）：

| 那份 chunk | 改前 | 改后 | 差额 | 谁付 |
|---|---|---|---|---|
| `ModelSettings-*.js`（懒加载） | 6,080 / 2,992 B | 11,100 / 4,677 B | **+1,685 B gzip** | 只有点开齿轮面板的人才付 |
| `useModels-*.js`（共享） | 473 / 289 B | 2,227 / 927 B | +638 B gzip | /tasks 一路 |
| `index-*.css` | 64,572 / 11,805 B | 66,039 / 12,039 B | +234 B gzip | 首屏 |
| 首屏 JS 合计 | 362,534 B gzip | 362,687 B gzip | **+153 B（+0.04%）** | 三页一起 |
| 全站 JS 合计 | 818,819 B gzip | 820,795 B gzip | +1,976 B（+0.24%） | — |

入口占比 0.442（门槛 ≤0.70）、echarts 仍不在首屏 —— `bundle.cjs` 6/6 全绿。
⚠️ 那 +153 B 来自 `client.ts` 里两颗新端点（它在入口闭包里），面板本体那 1.7 KiB 没进首屏：
这正是当初把面板做成 `React.lazy` 要买的东西，这轮第一次有人往里面加控件，量一下确认它还成立。

界面优化那一趟（AD 63→**72** 条：新场景 s9 九条 —— 底部那栏三层 + 「去设置」跨组件 +
高危浮层那段实现描述的来源；深色 AA 八类→十二类）之后：

```
running probe: 976 通过 / 976 断言 · 本次开页 100（导航 110）
```

（976 = **904** + AD 趟 72 条；开页 99→100 / 导航 109→110 = s9 那一档新 context 各一次。
同一棵树上另跑过 `ONLY=AD`：72 通过 / 72 断言 · 开页 11。
AD-neg1 那一趟**没跑到收尾**（AD-53 点不动 disabled 的撤回按钮 ⇒ 进程 exit=1），
所以那一档没有总分可报，红条清单见上面那张表 —— 负面对照的读数本来就只认自己 grep 的那几行。）

往前的那一趟（补漏那一趟，AD 56→**63** 条：`enforced=false` 那一档补了六条 + 页签边界抽成共享模块）之后：

```
running probe: 967 通过 / 967 断言 · 本次开页 99（导航 109）
```

（967 = **904** + AD 趟 63 条；开页/导航**一格没动** —— 新那六条全复用 ``future`` 那一档已有的
context，没有新开页。加判据不一定开页，这是"复用已有场景"能省下的验收成本。）

往前的那一跳（§2.1 对账那一轮，AD 41→**56** 条、九个→**十个** context、R 趟两条判据跟着桩改口）：

```
running probe: 960 通过 / 960 断言 · 本次开页 99（导航 109）
```

（960 = **904** + AD 趟 56 条；开页 98→99 / 导航 108→109 就是新那一档 ``future``
（"后端比界面新"：声明能配的数值键 ``eval_seed`` 界面没有行 ⇒ AD-41/41b 有得可咬）。
**R 趟仍是 27 条，但两条判据的写法换了**：③ 那两条原来写死 `/6 轮/`，
本轮把单位升进契约、桩里改成"次"之后**独红一条** —— 红的原因是**探针过期**，不是界面说谎。
教训单独记一笔：判据里的字面量必须跟桩同源（现在从 ``agentOptionsBody`` 取），
否则下一轮改桩会多出一条"看着像产品缺陷"的红，白白吃掉一次归因。）

往前的那一跳（运行配置面板首落：AD 趟 41 条 + R 趟三条期望值改口）是：

```
running probe: 945 通过 / 945 断言 · 本次开页 98（导航 108）
```

（945 = **904** + AD 趟 41 条；开页 89→98 / 导航 99→108 = AD 那九个 context 各导航一次
（完整响应 / 少字段 / 后端比界面新 / 端点 404 / 老 ack 没回执 / 回执钳值 / 422 / 390 抽屉 / 深色对比度）。
**R 趟的条数没变（27 条）但三条期望值改口了**：白名单从"前端抄的那两条"换成"桩里的全量减
`knowledge_search`"、③ 那一档的键集合从三个键换成只剩 `task`、默认读数从"3 轮"换成桩里的 6 轮 ——
三处都是往更严的方向改，所以总数一格没动。改口而不是加条数这件事本身值得记一笔：
判据数不变而红绿条件变严，是最容易被 review 漏掉的那类改动。）

往前的那一跳（主题切换挪到右上角，AC 趟加判据、没新开页）是：

```
running probe: 904 通过 / 904 断言 · 本次开页 89（导航 99）
```

（904 = **888** + 主题那 16 条（AC-17…AC-23，亮暗各 8）；开页与导航不变，因为八条新判据
全走的是 AC 趟已有的那四个页。AC 趟自己现在是 76 条 = 亮暗各 38 —— 趟内 `check(` 实数 38，
乘 2 等于 76，两个口径各自独立对上。）

往前的那一跳（换模型设置弹层 AC 趟落地之后）是：

```
running probe: 888 通过 / 888 断言 · 本次开页 89（导航 99）
```

（888 = **828** + AC 趟 60 条；开页 81→89 / 导航 91→99 = AC 每趟那四个页与四次导航 × 亮暗两趟。）

往前的那一跳（知识库上传页 Z 趟之后）是：

```
running probe: 828 通过 / 828 断言 · 本次开页 81（导航 91）
```

（828 = **773** + Z 趟 55 条；开页 80→81 / 导航 90→91 = R-03 新加的那一档"只缺白名单"（9d）。
**这一行今天连跑两趟都是 828**，Z 单独跑三趟都是 55，减出来的非 Z 部分是 **773** ——
与 `11fb8bd` 当时那行 `823 = 773 + Z 趟 50 条` 里的 773 一字不差。
⚠️ 因此要**翻掉我今天上午写在这里的一个结论**（那是 commit `12e7cd6` 带来的，当时我把 823 改成 824，
还写了一整段"差的有一条在 Z 之外、我没定位"）：那个 824 出自一条后台任务的**通知摘要**，
而同一批通知里另一条写着"contrast: 112 项判定"，实跑从来都是**必须达标 110 项 + 4 项图形不判定**
⇒ 那批通知里的数至少有一条是假的，824 大概率同一条来源，而"823 是旧读数"是我围着它编出来的解释。
真实的账一直是 823 = 773 + 50，今天上午那笔改动没动过任何判据数。
落到规矩上：**权威读数只认自己 grep 回来的那一行**（`node … | grep -a "running probe"`），
通知摘要、后台任务的 title、"看起来像输出的那段"都不算证据；
拆得开账的数才算数 —— 这次就是靠"减完要等于 773"这一眼看出来的。
留这一句是因为：对不上账时先分清"改了判据"与"读数的来源不可靠"，别为了凑一个数去动代码。
**这一轮之内还出现过 817 / 818 / 821 三个读数**，那不是三趟，是同一封 Z 信从 44 条长到 50 条的
中间态（补重试 +1、补 9b 那一帧 +2、补 9c 缺字段 +2 ⇒ 44→45→48→50 的其中几跳）。
往前的几跳一并记着，免得下次对不上账：
773 = 748 + AB 趟 25 条；新开 8 页 / 导航 +8 = AB 那八个 context（正常桩那一页要量
前件 + F-4 + F-5，再 500 / 404 / abort / 真空态 / 形状坏 / 空数组 / 390 窄屏各一页）。
748 = 724 + AA 趟 24 条（新开 6 页 / 6 次导航 + 1 次 reload = AA 那六个 context
（1440 主趟 / 挪时钟那一趟 / 390 窄屏那一趟 / 亮暗各一趟 / 负面对照那一趟）。
724 = 698 + J 续 26 条（新开 2 页 / 2 次导航 = 1440 与 390 两个 context，挂在 J 这封窄屏信下）；
698 = 695 + 3 条（A 趟「总 token」那句解释按内容断言，亮暗各一趟 ⇒ +2；K 趟轨迹页那一格 ⇒ +1）；
695 = 677 + Y 趟 18 条（Y 只跑亮色一趟、开 390/1440/820 三个页 ⇒ 开页 49→52、导航 58→61）；
677 = 673 + 转圈那 4 条（A 趟换 1 加 2 × 亮暗、B 趟加 1 × 亮暗）。）

页签调换 + 逐段揭示这一轮（AF 新开一封）之后 —— **最后一次跑完**的全量是 2026-09-29 00:24
那一刻的树（并发批次落进 `RunProgress` 之前）：

```
running probe: 1086 通过 / 1089 断言 · 本次开页 105（导航 117）
```

1040 → 1089 = **+49**。本轮动过判据的那几封，逐趟读数（同一份日志按 `== 趟名` 分组数出来的，
不是手数）：

| 趟 | 条数 | 本轮做了什么 |
|---|---|---|
| A 回放态 | 51 × 亮暗 | 加"选中任务落在运行结果"的前件 |
| B 运行态 | 55 × 亮暗 | 新增思考态一族；09-29 又把「思考态 6」跟 `RunProgress` 改口 + 补 6b/6c/6d（52→55） |
| C 虚拟容器 | 15 | 读点前加 `openLogTab` |
| J 窄屏 / J 续 | 32 / **27** | J 续 +1：第一次点开日志页签就钉底（NC-J 已验，见上面那节） |
| V 秒表隔离与按需挂载 | **19** | 整段翻面（默认页=结果页）+2；一度加过的"钉底"那条**删掉**，因为在 V 这份 fixture 上恒真 |
| W URL 恢复 | 36 | ②③④⑤⑥ 跟着页签调换改口；② 的期望值被 `RunProgress` 推翻后第二次改口 |
| AF 逐段揭示 | **10 + 5** | 新开一封两趟（正常动画 + `prefers-reduced-motion`）；09-29 00:54 单跑 `ONLY=AF` **15 / 15** |
| AD 设置中心 | 99 → **88（7 红 + 崩）** | 本轮没动 AD —— 这行掉是因为 00:49 那次并发编辑（`RunConfigPanel.tsx` 底部那一栏与撤回键正在改：`button.rcp-reset` 在 `src/` 里已搜不到，`grep -rn "rcp-reset" src/` ⇒ 0 命中，AD-51/52 的 hint 读回空串，末尾崩在等 `button.rcp-reset`）。**这条门槛现在归他那批改动的落定状态，不是本轮的读数** |

⚠️ **00:37 那次全量没跑完，也不该拿它的数**：崩在 M 趟等 `.rcp` 可见（`TimeoutError`），
崩前 0 红。崩的原因不是产品 —— 那一刻工作区正在被并发编辑
（`ModelSettings.tsx` 00:39、`RunConfigPanel.tsx` 00:41 的 mtime 落在跑动窗口里，
而 `npx tsc --noEmit` 在 00:42 报 `RunConfigPanel.tsx(3,10) TS6133 'Button' 声明了没用到`）。
同批并发改动还把跑动中那一屏换成了 `RunProgress` ⇒ B 与 W 各有一条判据被推翻，
改口之后单跑：`ONLY=B` **106 / 106**、`ONLY=B,W` **142 / 142**、`ONLY=J,V` **78 / 78**、
`ONLY=M` **12 / 12**。
00:49 他停手一会儿、`tsc` 回到绿之后，把**本轮动过判据的那几封**挑出来单跑一把
（`ONLY=B,C,V,J,W,AF,AD`，调度表顺序 ⇒ AF 排在 AD 之后）：
B 55×2 + C 15 + J 32 + J 续 27 + V 19 + W 36 = **239 条零红**，随后 AD 那封红 7 条并崩在
`button.rcp-reset`（他当时正在改底部那一栏，见上表那一行）⇒ AF 没跑到，00:54 单独补跑
`ONLY=AF` **15 / 15**。合计本轮动过的六封 **254 条零红**。
⇒ 等那批落定、`tsc` 回到绿，再复跑一次全量并把上面那一行改成可引用的数 ——
在那之前，**1089 这个总数不要拿去和别的轮次比**，它比的是 00:24 那一刻的树。

下面这段是**当初发现对不上账**的那一次读数，留着是为了说明"为什么只认这一行"，不是当前值：

```
running probe: 651 通过 / 651 断言 · 本次开页 47（导航 56）
```

单趟的条数写在各自的小节标题里，要复核就 `ONLY=<趟号>` 单跑 —— 那张行号表也是这么来的。

⚠️ **别拿 `grep -c '  ✓'` 当断言数**：本轮试过用 awk 按 `== 趟名` 分组数 `✓` 行，数出来 662
而探针报 651 —— 差额是 `✓ 截图 → xxx` 那一类**打印**也顶着同样的前缀。
一张对不上账的表比没有表更坏，所以这里不留手数的表，只留可复算的那一行：

```bash
NODE_PATH=… ONLY=W,R node tools/uicheck/running.cjs | tail -1   # ⇒ 56 通过 / 56 断言（W 29 + R 27）
```

开页数以前写在注释里靠手数（旧注释那句"28 次开页"实测是 46，W 趟之后是 47），
P 节 flake 的复现率分母就是它 —— 现在探针自己打印，加一趟就漂一次也会被下一次全量看见。

### running.cjs 抓到的十件事

- **报告给的根因，一半是错的**（R 趟，详见上面那节）：C7 说「label 包 button，Chromium 不代劳
  点击」，实测根本不成立 —— 注册修好后同样的 label 一个转发 `onClick` 都不写，点标题照样翻。
  真根因在别处（字段没注册 ⇒ `useWatch` 与 `onFinish` 双双拿不到），而且**比症状严重**：
  请求体里少了三个键，界面却显示得很正常。教训是别照着报告的症状去改 markup，
  先把"点了没反应"这件事量到能分层：是热区没命中、还是事件跑了但值没变、还是值变了没进请求。
- **终端层不能消费 PALETTE 的节点色**：日志面板两主题都是深底，而 `--node-planner` 那组是
  为**白底**调的（`#4f46e5` 白底 6.28:1）。压在 `#0f172a` 上实测 planner 2.84 / executor 3.26 /
  reviewer 3.13 / system 3.75 —— 四个全不达标，而且改底色之前就一直是错的。现在终端走
  `--log-node-*`（主题无关），contrast.cjs 两趟都跑同一批用例，**两趟数字必须一样**，
  不一样就说明有人把 `logNodeColorVar()` 改回了 `nodeColorVar()`。
- **transition 中间读不到最终色**：`.s-circle` 底色有 200ms 过渡，事件刚落就
  `getComputedStyle` 会拿到插值值（`rgba(0, 0, 0, 0)`），看起来像「压根没上色」。
  凡是断言**颜色/尺寸**的，先 `waitForTimeout(500)` 让过渡走完再读。
- **零日志时没有 `.log` 元素**：静默态是浅色占位（`.log-idle`），页脚 `.log-foot` 也不存在 ——
  探针里的 `cs(el)` 要对 null 返回 `{}`，让断言以「值不对」失败而不是整趟崩在 evaluate 里。
  这条顺带指出一个真空期：从提交到第一条事件之间恰好没有页脚可跳秒，所以静默态自己也要给时钟。
- **断言要按渲染结果写，不是按源码字面量写**：AntD 两字按钮渲染成「取 消」（中间有空格）、
  `fmtDuration(1020)` 输出「1.02s」—— 用 `/(\d+)s/` 提取会读成 `02`，看不出跳秒。
  两处都是探针错、产品对。
  ⚠️ AE 那一趟把这条从"知道"变成了"必须写成工具函数"：`hasText: '校验'` 匹配不到
  DOM 里的 `校 验`，报出来是 **30 秒等不到元素**，读起来像"这颗按钮没渲染"。
  现在按文案找按钮统一走 `buttonRx(text)`（把字串拆成"字与字之间允许空白"的正则），
  三个字的（`应用这把`）走同一条也照样命中。
- **"做过一步才出现的文字"不许夹在控件上面**（AE 抓到，真缺陷）：那行"已暂存"的说明原来
  写在输入框与按钮之间，只在 blur 那一刻出现 ⇒ mousedown→blur→插入一整行→按钮往下跳→
  mouseup 落在空处→React 的 `onClick` 根本不跑。人的现象是"点了校验没反应，得点第二下"。
  ⚠️ 调试时我先用 `dispatchEvent('click')` 验了一遍，**它是绿的** —— 合成事件不经过
  真实命中测试，正好绕过这个坑。⇒ 判"点了有没有反应"要数**请求次数**（AE-4d），
  而且必须用真鼠标事件。
- **拿值做包含检查的守卫，先问空值怎么走**（AE 抓到，真缺陷）：客户端那道
  "Key 不许进 URL"的自证写的是 `url.includes(body.api_key)`，而撤回那把 = 传**空串**，
  `String#includes('')` 恒为真 ⇒ 撤回请求在浏览器里就被拒，报出来的还是一句谎话
  "Key 出现在 URL 里"。判据 AE-8e。
- **块注释里别写 glob**：注释 `/* … **/api/tasks/* … */` 里那串 `*/` 会**提前闭合注释**，
  剩下的中文变成代码 —— `node --check` 不报错，跑到那一趟才炸 `ReferenceError`。
  同一个坑这轮踩了两次（G 趟一次、I 趟一次），要写 glob 就换行注释。
  顺带纠正一条旧事实：Playwright 的 `*` **不跨 `/`**，所以 `**/api/tasks/*` 盖不到
  `/api/tasks/x/trace` —— I 趟第一版把空态 fixture 挂在那条路由的 `/trace` 分支里，
  路由根本没命中，断言报的是"空态没渲染"而不是"路由没生效"。
- **`log-in` 关键帧动 `transform` ⇒ 虚拟化的行内定位被动画抢走**（P0-06 期间抓到，真缺陷，已修）。
  行是绝对定位 + 行内 `transform: translateY(start)`，而层叠里动画值压在 author-normal 的行内样式
  之上，`fill-mode: both` 又把终帧永久留在身上 ⇒ 旧写法（`transform: translateX(0)`）把
  translateY 抢成 0：**新行贴回容器顶部、和上面几行叠在一起**，不报错也不闪，只是内容重叠。
  改成动独立属性 `translate`（与 `transform` 相乘合成）后横向滑入照旧、纵向定位归虚拟器管。
  ⚠️ 这条之所以一直没被发现：**守卫量错了批次**。入场动画只在「已挂载的面板上追加新行」这条
  路径上才真的放（首批行落在实例第一次有行的那次提交里，`seen` 已被 StrictMode 的第二轮 effect
  填满 ⇒ `withAnim=0`，与 C 趟记录的同一成因），而 B 趟量的是首批 ⇒ `hijacked===0` 恒真。
  现在几何三项量第二帧批，负面对照：把 keyframes 改回 `transform` ⇒ 亮暗各红两条，
  现场打出 `start=50 / ty=0` 与 `overlap=[[1,2,25,25,0]]`。

### 怎么造出「运行态」这一屏

假 SSE 是 `route.fulfill` 一次性给完的，页面拿到终态帧就落定 —— 光标/呼吸/跳秒根本来不及看。
`running.cjs` 的做法：SSE 路由里先 `await` 4s 再 fulfill（这段时间任务必然是非终态），
并且把 `**/api/tasks/{id}` 改成回 `status: 'running'` 的详情，否则流一关就被详情拉回终态。
接管的 route 要自己处理 `/trace` 与 `/cancel` 两个子路径 —— 它排在 `installMocks` 之后会吃掉整条 `/api/tasks/*`。

⚠️ **P0-06 之后"第几条连接"不再等于"第几次提交"**：一条没有终态帧的流关闭后客户端会退避重连，
重连落在第几秒取决于前面那一串检查跑多快 —— 上一版拿 `sseCall` 当提交下标用，light 恰好对得上、
dark 慢半拍就全线错位（45 秒前的帧提前灌进常态那一段）。现在**第二次提交给一个新 task_id**，
SSE 按 URL 里的 id 分流：第一任务首连回 `runningFrames()`、它后续的每条重连**挂住不回**
（= 真机上「连接活着但没新事件」：既不往日志里掺行，也不把「最后一条日志 N 秒前」按回 0，
而且不应答就不会再触发下一条重连）；第二任务回一次 `staleFrames(45s)` 逼出告警档，之后同样挂住。
挂起用的是 `hangs` 数组里一个由收口时 `splice` 兑现的 promise —— **别用 `setTimeout` 轮询等它**，
悬着的计时器会把 Node 进程按住几十秒不退出。

### toolcard.cjs 抓到的两件事

- **`--text-inverse` 不能当「浅色字」用**：AntD Tooltip 的底在两个主题下都是深色，而该 token
  在暗色主题里是近黑 `#0b0d13` —— 压在 `#2a3042` 上实测 **1.39:1**，等于看不见。浮层上的次要
  文字要 `color: inherit` + 降不透明度（现在两个主题分别是 9.71 / 7.60）。
- **Tooltip 默认只挂 hover**：`rc-tooltip` 不监听 focus，键盘用户永远读不到工具解释。
  组件上要显式 `trigger={['hover', 'focus']}`，探针用 `.focus()` 后读 `.ant-tooltip-inner` 钉住它。

截图输出到 `tools/uicheck/shots*/`（已在 `.gitignore` 里）。归档用的成品截图在 `docs/screenshots/`（挑选后的成品）；脚本原始输出在 `shots*/`（不入库）。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BASE_URL` | `http://127.0.0.1:5173` | dev server 地址 |
| `OUT_DIR` | `tools/uicheck/shots` | 截图输出目录 |

## 注意

- 这是**视觉/交互**验证，不校验接口契约；接口口径的对齐靠 `src/types.ts` 与后端 `api/schemas.py`。
- 任务页的「提交」依赖假 `/api/tasks`（201）+ 假 SSE；若真后端起在 5173 的代理目标上，本脚本不会影响它（只在测试浏览器上下文里拦截）。
