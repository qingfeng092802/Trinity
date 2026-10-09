/* 运行页（页①）的验收探针，共四十一趟（三十二"封"）：
   ⚠️ 这一行以前写"共二十五趟"而实际已经 28 趟 —— 加一趟没人回头改这里，
      于是"多少趟"变成一个说不出来源的数。上一轮它写"三十五趟"也是错的（只数了
      J/AE/AF 三封的双趟，漏了 A/B/G/H/I/AC 这六封也是亮暗各跑一遍）。
      现在按调度表数：A–Y 25 封 + Z + AA + AB + AC + AD + AE + AF = **32 封**；
      其中 A / B / G / H / I / J / AC / AE / AF 这九封各挂两趟 ⇒ **41 趟**
      （J 那封的两趟是"窄屏溢出 + 收起态焦点"，不是亮暗）。
      收尾那行打印的断言数才是权威。
   ⚠️ 2026-09-28 页签调换（默认页签从「实时日志」换成「运行结果」）之后，**所有读 `.log*`
      的判据都要先自己把日志页签点开**（rc-tabs 对没激活过的面板不渲染 children）⇒
      统一走 `openLogTab()`。那一击刻意不藏进 `openTask()`：藏进去就没法断言
      "选中任务后停在哪一页签"，而那正是本轮要钉的本体（A 前件 / V ② / AD-32）。
   A 回放态 —— 终端配色 / 节点色对比度 / 心跳行合并 / 运行条去重 / 指标卡层级 / 实际字族
   B 运行态 —— 光标、呼吸徽标、跳秒页脚、最后活跃读数（常态 + 告警档）、取消二次确认；
     外加本轮新增的「思考态 1…8 + 6b/6c/6d」：提交后落在结果页、一条节点事件都没到时只说通用那句、
     三点动画真在动（读 name + duration）、planner 交卷后换成**后继**那句；
     6/6b/6c/6d 那四条在 2026-09-29 跟着 `RunProgress`（并发改进来的一屏）改过口，
     旧口径钉的是空态插画里那三条引导，新口径钉的是阶段条 + 骨架屏 + 页脚那句"届时整段替换"
   C 虚拟容器 —— 挂载行数与总行数解耦、历史行不重放动画、钉底不误关、未挂载也能跳转
   D 术语释义 —— 评测页卡片 ⓘ + 表头 title + 体检弹层的「降级」定义与对比度
   E 引用列表 —— 折叠/展开往返、真文档名、认不出⇒全 —、常驻元素数
   F 单次展开代价 —— 100 行 vs 4,800 行负面对照（1.8s 长尾按已知限制记录，不当 bug 修）
   G 模型读数条 —— 文案跟着 GET /models 变、兜底价不冒充官方价、拉不到整条不渲染、
     不再是假控件（无 .ant-select / cursor default / POST body 无 model）、双主题对比度
   H 结果页宽屏排版 —— 2560/1280/768 三档：内容块居中留白对称、卡与正文同一条左边缘、
     正文行宽仍 ≤820、无横向滚动
   I 结果页排版打磨 —— 指标卡收紧靠左 / FINAL ANSWER 标签升级 / 硬指标拆出紫块 /
     裸序号行提成标题 / 段间距节奏 / 加粗含数字才上主色（并量其对比度）/ 引用空态不画框 /
     **摘要条双向守卫**：长答案⇒画出来就必须有内容，一句话答案⇒`.summary-callout` 整块不在
     （条件写在容器里面 = 一条 24px 的空紫条，用户实测抓到、原 I 趟漏掉，负面对照 N6 已验）。
     外加一枚通用「空壳普查」：有底色 + 无文本 + 无 svg + 未 aria-hidden + 有高度 ⇒ 记名
   J 窄屏横向溢出 —— 390/320/820 三档 × 日志与结果两页签：文档零溢出、无越界元素、
     日志控件的挂点跟着窄/宽切、过滤到零行时控件不随皮肤一起消失
   K 回放页选任务 —— ?id= 是唯一状态源：首屏回落、连点两条、地址栏直达、重复点=刷新，
     每一步都断言「页面上的钢印 == 地址栏的 id」
   L 列表选中态回填 —— 从第二栏点开的任务跑完也要补拉详情；EventSource 句柄账幂等
   M 重渲染账 —— mergedAway 只在 rows 变化时跑；双向断言（先证计数器活着）
   N 迟到响应 —— 慢的那条整包丢掉，不许把 A 的答案与日志盖到 B 上
   O 断流 —— 传输层出错 ≠ 任务终态：要说出"中断"、要退避重连 1s/3s/9s、要按 event_seq
     补拉对账、重连后 seq 从头计过也不许撞 React key；三次接不上就认输说清楚
   P 取消的结局 —— 四档桩、三种说法：200 / 409 / 5xx / 直接没送达（判据是后端的 detail.code
     或 HTTP 状态，不是中文文案）；被拒时徽标要用服务端真值、不许本地改「已取消」也不许说
     "可能仍在运行"；服务端明确拒绝时说"没送达"同样是反话；取消失败不许把一条还在推的流
     白掐掉（先问后端、再关流）；5xx 那一档还钉"再点一次真能取消掉"（不自动重试 ⇒ 再点是唯一补救）
   Q 后台标签的探测 —— document.hidden 时不发探测也不许编结论（徽标如实停在「探测中」）；
     切回前台必须立刻补拉一次，不能等下一个 30 秒刻度（旧版的 hidden 早退跑在
     try/finally 之前 ⇒ 页面在后台被打开时 setLoading(false) 根本没跑，徽标永久卡住）
   R Composer 的三个设置 —— 点标题文字要能翻（旧版 label 包 button，Chromium 不代劳 ⇒ 点了
     没反应）；点开关本体只翻一次（转发排除开关内部）；键盘 Space 照旧可用；
     **并且界面说的必须就是发出去的**：use_tools / enabled_tools / max_iterations 三个键
     要跟着开关与迭代框变（旧版这三项没注册成 Form.Item ⇒ useWatch 恒 undefined、
     请求体里整个丢掉，而开关照常显示"开"）。
     ⚠️ ③ 那一档是**反假绿**用的：真实浏览器实测发现 16 条全绿而请求体仍缺 max_iterations ——
     因为用例自己点开了「运行配置」弹层，把懒挂字段顺手注册上了。③ 单独开页、全程不碰弹层，
     并且比的是**整个键集合**而不是某个键（见 ③ 上面那三条规矩；契约里根本没有 use_rag）
   S 导出 CSV —— 端到端真的产出一个文件：文件名、BOM、表头 10 列、行列数对齐、
     导完不留无主的 <a>，连导两次都成（三步缺一都只在部分浏览器上"点了没反应"）
   T 运行条的播报 —— 每秒跳秒不许变成每秒播报：runbar 不是 live region，播报交给一枚
     常驻的 [data-live=runbar]（空载时就在场）；同一观察窗里跳秒 ≥2 次而播报 0 次；
     取消成功（真的状态变化）时恰好播 1 次，且播报里永不含计时串
   U 答案子树 —— 与答案无关的父级重渲染不许把整棵 markdown 树重建：判定用组件内的
     render 计数（换答案必涨、静置与"展开/收起引用"都不涨，双向）；⚠️ 别用外面那枚
     Profiler 的提交数判定 —— 实测它 3→7 而答案一次没重渲染（memo 挡得住子组件、挡不住 Profiler）；
     ⚠️ 触发器也不能再用切页签 —— 结果页签从 P1-01 起按需挂载，切走是卸载、切回是重挂（V 趟管）
   V 秒表隔离与按需挂载 —— 1Hz 只许活在 Elapsed 里：运行中静置 2.8 秒，`elapsed` 涨 ≥2
     而 `page`（整页函数体）一次不许多跑，改一次关键字当"计数器活着"的反证；结果 / 工具
     两个重面板**没点开就不在 DOM 里**（不是 visibility:hidden），切走即卸载、无残留，
     再点开是重新挂载一遍
   W URL 恢复与回前台补拉 —— 「在看哪条任务」落到 ?task_id=（它以前只活在 useState 里，
     用户实测：切走 30 秒回来，列表照旧「运行中」而主区变空态「还没有日志」）：
     ① 无 query 不自动选 ② 提交写 URL 且**不回头重拉**（坑 B：记账必须写在 await 之前）
     ③ reload 后现场回来、只补一次、行数 ≥ 重载前 ④ 同一个 id 再点 = 真刷新，
     且 fromUrl 不许抢页签 ⑤ 点另一条 URL 跟着换、重载恢复的是那一条 ⑥ 坏 id 说清失败
     且不静置重试 ⑦ 后台 45 秒不补拉、切回恰好一次（详情 1 + 轨迹 1，拆开写就是两份 trace）、
     补拉只许盖回去不许清屏。行数一律读**页签计数**不是 `.log-row`（按需挂载时面板不在 DOM 里）。
     ⚠️ 不断言"reload 后页签也回来"——页签是内存态，重载必丢，那是事实不是缺陷
   X 宽表横向滚动 —— 390 下 9 列的表只露 2 列，而"右边还有列"既看不见（overlay 滚动条不占
     高度）也滚不过去（容器不可聚焦）：① 滚动必须从 AntD 的 .ant-table-content 收回到
     .scrollx-box（带 scroll.x 时 AntD 把 overflow-x:auto 写成**行内样式** ⇒ 只能 !important）
     ② 容器可聚焦且**按键真改 scrollLeft**（不是断言 tabindex 存在）③ 两端渐影跟三态走，
     滚到底右渐影必须收 ④ 1440 不溢出时一切提示都不许出现（少了这档，"恒画渐影"也全绿）
     ⚠️ 别用 End / Home 测"滚到底"：实测 Chromium 对可滚动 div 根本不响应这两个键
     （scrollLeft 纹丝不动），只有方向键会滚 ⇒ 只能一段 ArrowRight 数出来（390 下 30 下到底）。
     ⚠️ 键盘那几条要**连发之后再读**：一下一读、或先 page.focus() 再按，都会让那几下完全不滚
     （activeElement 就在那块上、overflow 642，scrollLeft 却一动不动）—— 是读法在干扰键盘滚动，
     不是产品缺陷。连发 5 下 + 静置 150ms 读到 200（Chromium 一档 40px）。
     ⚠️ 读渐影前必须静置：它带 120ms 过渡，data-at-end 已经是 1 时 opacity 可能还在 1→0 路上。
     负面对照 X-neg（摘掉那条 !important）当场 10 条翻红，读数逐字回到坑本身：
     内层 ["auto","auto","visible"]、外层 298>298（带 scroll.x 的两张收不回来，第三张正常）
   Y 面板头抢宽度 —— 390 下右侧 chip 不肯让（flex item 默认 min-width:auto = 内容宽），
     标题列带的却是 min-w-0 ⇒ 让位代价全落在标题上，实测压到 38px（EV-02）：
     ① 标题列有地板 min(14rem,100%)（只加 flex-wrap 不给地板 = 永远轮不到换行）
     ② chip 真落到第二行（只测"标题宽度够"会漏掉"chip 被挤出屏幕"）
     ③ 卡片与整页零横向溢出 —— 这是换行的代价检查：收缩链 .surface-extra → .code-chip
       → code 少任何一环 min-width:0，窄屏就从"压标题"变成"撑破卡片"（J 趟那类 P0 复活）
     ④ 截断只是视觉的：textContent 与 title 属性都还是完整串
     外加 1440（同一行 + 一字不截）与 820（过渡档 ≥224px）两档反向钉
   AA 成本归因面板（C1–C7）—— 面板的全部价值是"数字可信"，所以八条判据全在查
     「页面说的是端点说的，不是前端自己算的」：合计来自 GROUP BY 端点（明细桩被灌成
     600 条 ×¥1 而读数一动不动）、对账两个口径的数**恒常露出**（相等时也不许只留一句断言）、
     历史行 model=null 就显示「未记录」且绝不出现今天的 role_map 模型名、跨峰谷同角色
     两行两系数并存、金额一律 4 位（钉 fmtCostFixed）、"下一次进入低谷"跟着桩值走而
     **系统时钟挪 5 小时读数一字不变**（前端没有自判时段的余地）、390 不溢出且表能键盘滚、
     两主题五种文字在**实际所在底色**上 ≥4.5:1。
     ⚠️ 三条负面对照各摘一次（都靠改桩实现，不动源码）：回落模型名 → 判据 3 抓到；
     all_equal=false → ✗ 真落页面；price_check.ok=null → 显示 ? 与「未校验」而不是 ✓。
   AB /eval 的错误态与形状闸门 —— 四档桩（500 / 404 / abort / available:false）各钉一句
     "用户读到的是哪句话"，外加两条反向钉（错误态里不许出现 CLI 命令、真空态里必须还出现）；
     判据本体是**分支顺序**：isError 必须排在"没数据"之前。细节与三条本轮新坑见 README 的 AB 节。
   Z 知识库上传页（A 档 / K1–K8）—— 分段进度条只画处理段四格，亮暗与呼吸全部来自轮询回来的
     status（传输段仍是"状态文字 + 已传字节"，K4 未变、没引 XHR ⇒ 没有一个编出来的百分比）。
     十三个 context：正常三行 / 全终态即停 / 概览与行数不一致 / 未知状态三件套 / 后台标签不白打 /
     轮询跟到终态 / 上传链路七种回法（响应给了 docx 就**不许**再本地拦、multipart 头、201 只说进队列、
     同名 409→覆盖重建带 overwrite=true、按放弃只发一次、指纹 409 分开说、429 读 Retry-After、
     后端 422 原文、一次七份只排五份且峰值并发=1）/ 删除两下 + 重试回到第一段 /
     503 整页降级 / **概览先挂而列表扣在闸门上那一帧的附言** / 390 窄屏 /
     **上限与白名单两个字段都不在（老进程）** / **只缺白名单（重启到 HEAD 那一档）**。
     ⚠️ 上传白名单（`accept` 与"支持 …"那句）从 R-03 起**读 /overview 的 supported_formats**，
     桩因此故意给四种（含页面从没写过的 docx）—— 桩值等于"页面写死的那份"判据就恒真。
     负面对照：摘三处（终态即停、把 accept 整条摘掉、未知状态当"还在跑"）⇒ 恰好那三条翻红；
     R-03 另跑一次"页面无视响应、写回那三种"⇒ 该红的正是 accept 与文案那两条。
     九条探针层的坑（八条出在探针这一层、一条是页面真写坏了）记在 README 的 Z 节。
   AC 右上角换模型（亮暗各 38 条）—— 候选、当前生效值、价的来路全读 GET /models；
     没有 catalog 就说"这一趟没读到候选清单"并提示重启后端，绝不回落到前端自带的那份；
     含主题切换上右上角那 16 条（AC-17…AC-23，钉"顶栏只有一枚主题按钮"与 390 顶栏宽度）。
   AD 设置中心（左导航 + 右内容 · 十一个 context）—— 一屏五个口径 + 底部那一栏（s9）：
     ①只有一份状态（面板与 composer
     开关**双向**都测，单向断言挡不住"两份 state 互相同步一次"）②只有一份清单（勾选逐条等于
     桩里的 /tools，六条含页面从没写过的三个工具）③没碰过的键不发（四档各钉一次键集合，
     降级那两档只有 task；AD-40 钉的是"界面显示着默认 8 分"≠"发出了 8 分"）
     ④后端原话落屏（accepted=false 无控件、只列 **key + label + help**、未知键原样 JSON、
     "给了界没声明"与"声明能配却没有行"两类都点名、422 的 HTTP 码 + code + request_id + 原话
     进 .log-row--error、回执缺席 / 被钳值分两种 data-code，且断言的是整包补拉**之后仍在**那条常驻提示；
     **accepted=true 而 enforced=false 那一档由 AD-45…50 钉**：控件照旧在场、help 以正文在场、
     底部单独一栏点名 key + label、填了真的进请求体、那句话全屏只出现一次）
     ⑤**字段名与单位也归响应**（fields[].label / unit 决定每行叫什么、后缀是什么、回执那行怎么写；
     界面那张 CONFIG_LABELS 本轮删了 —— AD-37/37b/37c/29a 钉的就是这个）。
     ⑥**底部那一栏与「去设置」**（2026-09-27 界面优化那一轮，新 context s9，九条）：
     AD-51/52/53 判"改动读数 + 撤回"这条链的三个面（Context 里那个 reset() 以前
     **从来没有 UI 调用过**），AD-54 判撤回后的请求体只剩 task；
     ⚠️ AD-54 单独不可信 —— neg1 实测：勾选搬回局部 state 之后它照样绿（Context 根本没收到
     那次取消，"撤回成功"的姿势与真撤回一模一样），红的是 AD-52、而 AD-53 卡在 disabled 的
     按钮上起不来。⇒ "点了没反应"类控件必须**正面（进没进状态）与结果（请求体）各一条**。
     AD-55/55b/55c/55d 判的是「模型」这一格**内嵌**那份（2026-09-27 从"去设置"跨组件入口改成
     内嵌同一组件）：这一屏只有一份 .model-settings、它的 id 全带 sc- 前缀（重复 id 会让判据
     与读屏软件量错那一份）、旧的入口与那条 window 事件桥都不在了、Esc 关得掉这一层
     （判的是**可见性**不是存在性 —— Modal 关了不卸载，只看"在不在 DOM"会被骗过去）；
     AD-56/56b/56c 判高危浮层里那段"沙箱 / Python / 超时"的来源：现在读的是 GET /tools 的
     description（桩 20 秒 / 后端真值 30 秒，出现 30 就是前端又抄了一份），
     ⚠️ 读点第一版写成"把所有 .ant-tooltip 拼起来"，把 composer 那颗悬停提示也读了进来 ——
     判据照旧绿但它已不再只检查自己声称检查的东西，改成顺 aria-describedby 取自己那枚。
     ⑦**这一屏的形状**（2026-09-27 水平页签 → 左侧导航 + 右侧内容，AD-57…AD-64 八条）：
     AD-57 导航三项与默认选中、AD-58 默认只有「基础」那格可见（其余还没挂载）、
     AD-59 承载面是 Modal 那一层（.ant-modal 里有面板、.ant-popover 里没有旧壳）、
     AD-60 一行的**几何**是"标签+描述在左、控件在右"
     （读 getBoundingClientRect，不读类名 —— 类名对了而 grid 忘了写，界面照样上下堆）、
     AD-61 「恢复默认配置」这一屏只有一颗（2026-09-29：旧的「回落到 .env」+「撤回全部修改」
     两颗合成这一颗）、AD-62 切两次导航之后可见的那格跟着换
     （挂载过就留着 + hidden 挡住，与原来页签同一语义：改成每次 remount 会让 AE-12c 失去可证伪性）、
     AD-63/64 快捷示例搬到输入框下方之后**位置与动作都还在**（这三颗改前一条判据都没读过，
     "搬丢了"不会有人发现 ⇒ 判"三条互不相同且都非空 + 一次请求都没多发"，不写正文字面量）。
     ⑧**同一屏的第二趟：换成 960×600 那一档**（AD-66…AD-74，共九条半）：
     AD-66/67 整窗尺寸与比例 + 左导航 160 + 右格限宽 720 且**靠左**（AD-59 从此只管"是 Modal"，
     尺寸归这两条 —— 一条判据只声称一件事）、AD-68 切三格整窗高度三次数值全等
     （负面对照 NC-geo：把 height 改成 max-height，界面看着完全正常，而这一条必须红）、
     AD-69…69d 候选下拉两行一项、弹层宽 = min(600px,90vw)、DOM 里的条数 = catalog 条数、
     两行都不横向溢出、选中之后框里只剩模型 id（展示名与单价留在第二行，不是删了）、
     AD-70/71/71b Key 那一栏三行标签 80px 对齐 + 控件撑到行尾、标题只剩四个字 + 可聚焦的 ⓘ +
     「应用到本次运行」与旁边那句提示、状态行四项全来自响应，
     AD-72/72b/72c 向量模型那一行（**这一栏此前零判据**）+ 那枚锁的浮层真打得开，
     AD-73/73b 「角色绑定」那一行小字在场且逐字完整 + 那张五行角色表整块不在场
     （2026-09-29 顶掉了原来的「角色模型映射」两种形状那两条 ——
       那五行永远不可能不一致（后端只认两个档位），界面不再有对应物，判据跟着删，
       不为保留判据而保留冗余 UI）、
     AD-74/74b/75/75b 模型 Tab 一屏可见 + 档位改名「决策模式 / 执行模式」+
     改下拉框 ⇒ 底栏那枚 dirty 小圆点变橙（跨组件的连线，断了肉眼看不见）。
     深色那一档（s8）的 AA 清单同时从八类补到**十五类**（底部读数、左导航项、两枚 Tag、
     候选弹层那两行、按钮旁那句提示 ——
     ⚠️ 候选那两行**压在弹层自己的底色**上（AntD 的 colorBgElevated，不是 --bg-surface），
     所以 s8 量之前要先把下拉打开一次，否则那两类读回空数组、"量不到"被误读成通过）、
     档位 Tag 自带 AntD 预设底色，不量就等于没验），s8 因此高级与模型**两个页签都点**
     （页签首次激活才挂载，少点一个就是那族类读回空数组），清单收成 AA_CLASSES 一份。
     桩里的默认值、边界、措辞、单位**一律不等于后端真值**（对账时逐键比出**三处撞车**：
     defaults 那个 7、timeout_s.max 曾是 3600、review_threshold 的整条 0..10 —— 撞车的桩值
     会让"界面读的是响应"当场变成死判据）。还有一处**故意留着**的巧合：max_cost_cny.step
     两边都是 0.01 ⇒ "小数位取自 step"今天不可证伪，改它会牵动 AD-03 那件别的事，细节在
     mocks.cjs 那张表的注释里。
     AD-42/43 顺手把「回执对不上」那一栏的三类小字在**合成后的 warning 底**上量了亮暗两档
     （那一栏只在旧 ack 那一档才进 DOM，全站其它趟碰不到它）。AD-44 抓到一次真实的静默失效：
     --font-mono 在产物里**没有定义**（注释里写了个带"星杠"的路径通配，把 CSS 块注释从中间关了），
     四条 font-family 全被丢弃，而 tsc / build / 其余判据一概不红。
     六组负面对照（编号与 README 的 AD 节一致；数字是**当次实测**，趟涨了要重跑、别抄旧数）：
     · neg1 工具勾选搬回局部 useState ⇒ 旧读数 60/63（红 AD-09/10/16）。
       **本轮分母涨到 72 后重跑过这一组**：红 AD-09/10/16 + **AD-52**，且 AD-53 点不动
       disabled 的撤回按钮 ⇒ 探针 TimeoutError、进程 exit=1（AD-54/55/56 没跑到）。
       ⚠️ 第一版**没咬住**（全绿）：
       那次只把读数换成局部 state、onChange 还在写 Context —— 负面对照自己是假的时也会全绿，
       所以每条都要核"红的是不是该红的那几条"；
     · neg2 控件闸门只看"有没有界"、不认 accepted ⇒ 62/63，**只红 AD-36**（旧记的"红 AD-20"
       已不成立：那半个闸门同时是"键不在 fields[] 里"时的兜底，摘了它 field 直接是 null）。
       ⚠️ 这一组**咬不到 AD-11**：reviewer_enabled 不在行表里，闸门只看有没有界也不会给它画控件
       —— 那条要靠行表本身，别以为它被覆盖了；
     · neg3 buildRunConfigBody 回落 max_iterations: 3 ⇒ 61/63（红 AD-22/28）；
     · neg4 把 label/unit 写回前端那张表 ⇒ 57/63（红 AD-04/05/25/37b/37c/41b），
       同时让后端那份静态审计里"代码行不许出现后端措辞"两条翻红（两层网各抓一半）；
     · neg5 摘掉「后端会收下但没有执行机制」那一栏 ⇒ 62/63（**只红 AD-48**）；
     · neg6 把 enforced=false 当成"不支持"（连控件都不画）⇒ 57/63，红 AD-46/47/49 前件/49b/35b/50。
       AD-50 读数是 **0**（行整个没了，那句话一次都没出现）—— 前件型判据把"量不到"当成不通过。
     跑法与六组红条清单另见 README 的 AD 节。

   AF 答案逐段揭示（打字机，亮档 + 减动档各一趟）—— 后端真流式要动三处结构（worker 在
     线程池里同步跑、订阅队列 256 溢出即丢事件、Reviewer 是 JSON 模式结构化输出 ⇒ 原始增量
     是拼不上的 JSON 碎片），所以按本轮明确允许的降级做：**后端一次给全文、前端逐段揭示**。
     两头都钉：AF-3 证"真的出现过半截"（24 次采样里至少两拍是中间态、且在长），
     AF-4 证"播完了停在整段"，AF-6 证"中途点复制拿的是源串"（剪贴板逐字等于原文，
     换行要归一：Windows 把 \n 写成 \r\n，实测 260 ⇒ 271），AF-8 证"换一条新任务账是新的"；
     减动档（reducedMotion: 'reduce'）反过来钉：一次都不许出现半截、那三点 animation-name=none。
     反面那一头（**历史任务不许演"正在生成"**）在 V 趟②末尾：刚点开那拍与静置 1.6 秒之后
     必须一字不差。⚠️ 那条判据第一版是"读一次长度 > 50"，恒真 —— 负面对照 NC-AF2
     （把 `revealed` 写成恒 false）当场放过去，改成两次读数相减才咬住（实测 409 vs 2,666）。
     两组负面对照（跑完即撤，工作树里无残留）：NC-AF1 恒 skip ⇒ 红 AF-3/6a/6/8 四条；
     NC-AF2 从不 skip ⇒ 只红 V 那条「历史任务不重播打字机」。
     截图四张：af-{normal,reduce}-thinking（思考态）、af-revealing（动画中间那一拍）、
     af-result-full（播完）。

 跑法：NODE_PATH=<playwright-core 所在目录> node tools/uicheck/running.cjs */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// Chrome 路径：统一由 ./_chrome.cjs 解析（优先环境变量，回退各平台默认安装位置）
const CHROME = require('./_chrome.cjs').resolveChrome();
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots/running');
const {
  installMocks,
  installAgentOptions,
  agentOptionsBody,
  agentOptionsVariants,
  createSubmitMock,
  toolsBody,
  TASK_ID,
  detail,
  traceBody,
  modelsBody,
  modelsBodyTwoTiers,
  modelsBodyFallback,
  modelsBodyWithCatalog,
  createModelOverrideMock,
  costBody,
  healthBody,
  kbJson,
  resetKb,
} = require('./mocks.cjs');

let pass = 0;
const fails = [];
/** AntD 的 ``Button`` 会给**正好两个汉字**的按钮名中间插一个空格（``autoInsertSpaceInButton``，
 *  实测 DOM 里是 ``校 验`` / ``应 用`` / ``撤 回``）。所以按文案找按钮时不能传字面串 ——
 *  传了就是 30 秒等不到元素，而报出来的形状是"这颗按钮不存在"，一条假缺陷。
 *  这里把字串拆成"字与字之间允许空白"的正则；四个字以上的（``应用到本次运行``）AntD 不插空格，
 *  走同一条正则也照样命中 —— 所以按文案找按钮一律走它，别去猜这一颗几个字。 */
const buttonRx = (text) => new RegExp(text.split('').join('\\s*'));

/** 「设置」那一层如果开着就关掉（没开就是空操作，所以每一趟都能安全调用）。
 *
 * 为什么需要它：2026-09-27 那一层从 Popover 换成了 **Modal**，带遮罩 ⇒ composer 上的
 * 控件在它开着的时候**点不到**（真用户点不到，Playwright 的命中测试也点不到 —— 这不是
 * 测试环境的假象，是"模态"这条语义本身）。而面板里的草稿住在 ``RunConfigProvider``，
 * 不在这层的可见性里 ⇒ 关掉再点，判据量的还是同一份状态。
 * ⚠️ 只在**点**之前调；读判据不用关（``evaluate`` 不做命中测试，Modal 关了也不卸载，
 * 内容照样在 DOM 里 —— 反过来，谁要是把"在不在 DOM"当"开没开"读，那是另一个坑，
 * AD-55d 钉的就是这条）。 */
const closeSettingsLayer = async (p) => {
  if (await p.locator('.ant-modal-wrap').first().isVisible().catch(() => false)) {
    /* 用右上角那颗 X，不用 Esc：Esc 的事件挂在 dialog 上，**焦点不在这一层里的时候它收不到**
       （例如上一句 evaluate 之后 activeElement 还在 body 上）—— 那种条件下 Esc 是空操作，
       下一句点 composer 控件就会 TimeoutError，红的原因还很难读。
       AD-55d 那条判据量的是"焦点在里面的时候 Esc 关得掉"，与这里不是同一件事。 */
    await p.locator('.ant-modal-close').first().click();
    await p.waitForTimeout(360);
  }
};
/** 各 fixture 规模下的**折叠态**常驻元素数。跨档位必须相等 ——「与总量解耦」这条口径
 *  唯一的正证就是它（passCitations 与 passExpandCost 都往里塞，最后一起比）。 */
const FOLDED_ELEMENTS = [];
function check(name, cond, got) {
  const ok = Boolean(cond);
  if (ok) pass += 1;
  else fails.push(`${name} — got ${JSON.stringify(got)}`);
  console.log(`  ${ok ? '✓' : '✗'} ${name}${got === undefined ? '' : ` — ${JSON.stringify(got)}`}`);
}

/** 读一屏终端的实测样式与几何（一次 evaluate 全拿，避免多次往返）。
 *  对比度在页内算：拿的是**计算样式**，不是我抄进脚本的色值。 */
function readTerminal() {
  return (() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    /* 元素可能不存在（零日志时面板是浅色静默态，没有 .log）—— 返回空对象而不是抛，
       让断言以「值不对」的形式失败，而不是整趟崩在 evaluate 里。 */
    const cs = (el) => (el ? getComputedStyle(el) : {});
    const log = q('.log');
    const msg = q('.log-msg');
    const seq = q('.log-seq');
    const contrast = (fg, bg) => {
      const lin = (v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const parse = (s) => (String(s).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const f = String(fg).match(/[\d.]+/g) || [];
      const A = f.length > 3 ? Number(f[3]) : 1;
      const [r1, g1, b1] = parse(fg);
      const [r2, g2, b2] = parse(bg);
      const mix = [r1, g1, b1].map((c, i) => c * A + [r2, g2, b2][i] * (1 - A));
      const l1 = lum(mix);
      const l2 = lum([r2, g2, b2]);
      return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    };
    const nodeColors = {};
    qa('.log-node').forEach((el) => {
      const key = el.textContent.trim().replace(/^[^\w]+/, '');
      const c = getComputedStyle(el).color;
      if (!nodeColors[key] || nodeColors[key] !== c) nodeColors[key] = c;
    });
    const live = qa('.log-row--live');
    return {
      logBg: cs(log).backgroundColor,
      logRadius: cs(log).borderTopLeftRadius,
      logBorder: cs(log).borderTopColor,
      bodyBg: cs(q('.log-body')).backgroundColor,
      msgColor: msg ? cs(msg).color : null,
      seqColor: seq ? cs(seq).color : null,
      footColor: cs(q('.log-foot')).color,
      footBg: cs(q('.log-foot')).backgroundColor,
      msgOnBgContrast: msg ? contrast(cs(msg).color, cs(log).backgroundColor) : null,
      seqOnBgContrast: seq ? contrast(cs(seq).color, cs(log).backgroundColor) : null,
      /* 四列定宽：序号 | 级别 | 节点 | 正文 —— 列数与「前三列是定宽、只有正文 1fr」都要实测 */
      rowCols: q('.log-row') ? cs(q('.log-row')).gridTemplateColumns.split(' ').length : 0,
      colWidths: q('.log-row') ? cs(q('.log-row')).gridTemplateColumns : null,
      /* 级别列：每行都得有，且文字就是 DEBUG/INFO/WARN/ERROR 四个词之一 */
      levelLabels: Array.from(new Set(qa('.log-row .log-level').map((el) => el.textContent.trim()))),
      levelRows: qa('.log-row .log-level').length,
      levelContrast: Object.fromEntries(
        Array.from(new Set(qa('.log-row').map((el) => el.querySelector('.log-level').textContent.trim())))
          .map((label) => {
            const el = qa('.log-row').find((r) => r.querySelector('.log-level').textContent.trim() === label);
            return [label, contrast(getComputedStyle(el.querySelector('.log-level')).color, cs(log).backgroundColor)];
          }),
      ),
      /* 滚动条：Firefox 走 scrollbar-width，Chromium 的 ::-webkit-scrollbar 另测 */
      bodyScrollbarWidth: cs(q('.log-body')).scrollbarWidth,
      bodyOverflow: cs(q('.log-body')).overflow,
      liveRowBg: live[0] ? cs(live[0]).backgroundColor : null,
      ruleColor: q('.log-row') ? cs(q('.log-row')).borderBottomColor : null,
      ruleWidth: q('.log-row') ? cs(q('.log-row')).borderBottomWidth : null,
      nodeContrast: Object.fromEntries(
        qa('.log-node')
          .slice(0, 4)
          .map((el) => [
            el.textContent.trim(),
            contrast(getComputedStyle(el).color, cs(log).backgroundColor),
          ]),
      ),
      rowTotal: qa('.log-row').length,
      liveCount: live.length,
      liveSeq: live[0] ? live[0].querySelector('.log-seq').textContent : null,
      liveTail: live[0] ? live[0].querySelector('.log-live-tail')?.textContent ?? null : null,
      liveMark: live[0] ? Boolean(live[0].querySelector('.log-live-mark')) : false,
      /** 全页转圈标记的**个数**。终态必须是 0（跑完了还有一条在转 = 用户实测那颗），
       *  运行中的心跳行则必须 ≥1 —— 两头都钉，少一头这条断言就是恒真的。 */
      liveMarks: qa('.log-live-mark').length,
      liveAnim: live[0] ? cs(live[0]).animationName : null,
      footText: q('.log-foot') ? q('.log-foot').textContent.replace(/\s+/g, ' ').trim() : null,
      cursor: qa('.log-cursor-block').length,
      cursorAnim: q('.log-cursor-block') ? cs(q('.log-cursor-block')).animationName : null,
      clock: q('.log-live-foot') ? q('.log-live-foot').textContent.trim() : null,
      badgeLive: Boolean(q('.runbar .status-badge.is-live')),
      badgeAnim: q('.runbar .status-badge.is-live .dot')
        ? cs(q('.runbar .status-badge.is-live .dot')).animationName
        : null,
      runMetrics: qa('.runbar .rm').length,
      runbarText: q('.runbar') ? q('.runbar').textContent.replace(/\s+/g, ' ').trim() : null,
      steps: qa('.runbar .step').map((el) => {
        const circle = el.querySelector('.s-circle');
        const after = circle ? getComputedStyle(circle, '::after') : null;
        return {
          cls: el.className,
          afterAnim: after ? after.animationName : null,
          afterBorder: after ? after.borderTopColor : null,
          circleBg: circle ? getComputedStyle(circle).backgroundColor : null,
          glyphColor: circle ? getComputedStyle(circle).color : null,
        };
      }),
      idle: Boolean(q('.log-idle')),
      cancel: qa('.runbar button').map((b) => b.textContent.trim()),
    };
  })();
}

/** 用 CDP 直接问浏览器「这几个字实际用了哪个字族」。
 *
 *  CSS.getPlatformFontsForNode 给的是**渲染实际用到**的族和字形数，比读
 *  getComputedStyle 的声明栈诚实得多 —— 声明里写着 Inter / JetBrains Mono，
 *  本机没装就是没装（这个项目不打包字体文件）。录屏报告 UI-3 说「中西文字形明显不同」，
 *  只有这个接口能回答「到底各自落进了哪一族」。 */
async function platformFamilies(ctx, page, cases) {
  const placed = await page.evaluate((specs) => {
    return specs.map(([key, text, hostSel]) => {
      const host =
        document.querySelector(hostSel) || document.querySelector('.answer') || document.body;
      const s = document.createElement('span');
      s.setAttribute('data-uicheck', key);
      s.textContent = text;
      host.appendChild(s);
      return [key, host === document.body ? 'body(兜底)' : hostSel];
    });
  }, cases);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');
  const { root } = await cdp.send('DOM.getDocument', { depth: -1 });
  const out = {};
  for (const [key, host] of placed) {
    const { nodeId } = await cdp.send('DOM.querySelector', {
      nodeId: root.nodeId,
      selector: `span[data-uicheck="${key}"]`,
    });
    let fonts = [];
    if (nodeId) {
      const r = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
      fonts = (r.fonts || []).map((f) => [f.familyName, f.glyphCount]);
    }
    out[key] = { host, fonts };
  }
  await cdp.detach();
  return out;
}

async function openTask(page) {
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(600);
}

/* 页签调换（2026-09-28，任务与日志页产品化）：默认页签从「实时日志」换成了「运行结果」。
   rc-tabs 对**从没激活过**的面板不渲染 children（P1-01 那刀之前就是这样，只是当时
   日志是默认页、天然已激活）⇒ 探针里所有读 `.log*` 的点都得先把页签自己点开。
   ⚠️ 刻意不把这一击藏进 `openTask`：那样就再也没法断言"选中任务后停在哪一页签"，
   而那正是本轮要钉的两条（A 趟前件、V 趟 ②）与 AD-32（失败要落在眼前）的判据本体。 */
async function openLogTab(page) {
  await page.getByRole('tab', { name: /实时日志/ }).click();
  // 零日志时面板是浅色静默态（没有 .log），所以两个选择器都算挂载成功
  await page.waitForSelector('.log, .log-idle', { timeout: 8000 });
  await page.waitForTimeout(300);
}

/** 结果页签上那一行"正在跑什么"的读数（思考态：三点 + 阶段文案 + 引导清单）。
 *  写法与 readTerminal 同构：一次 evaluate 全拿，元素不在就返回 { present: false }，
 *  让断言以"值不对"的形式失败而不是整趟崩在 evaluate 里。 */
function readThinking() {
  return (() => {
    const q = (s) => document.querySelector(s);
    const cs = (el) => (el ? getComputedStyle(el) : {});
    const contrast = (fg, bg) => {
      const lin = (v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const parse = (s) => (String(s).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const f = String(fg).match(/[\d.]+/g) || [];
      const A = f.length > 3 ? Number(f[3]) : 1;
      const [r1, g1, b1] = parse(fg);
      const [r2, g2, b2] = parse(bg);
      const mix = [r1, g1, b1].map((c, i) => c * A + [r2, g2, b2][i] * (1 - A));
      const l1 = lum(mix);
      const l2 = lum([r2, g2, b2]);
      return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    };
    const box = q('.thinking');
    if (!box) return { present: false };
    const text = q('.thinking-text');
    const dots = q('.thinking-dots');
    const dcs = cs(dots);
    const tcs = cs(text);
    return {
      present: true,
      role: box.getAttribute('role'),
      live: box.getAttribute('aria-live'),
      text: (text ? text.textContent : '').trim(),
      color: tcs.color,
      fontSize: tcs.fontSize,
      boxBg: cs(box).backgroundColor,
      boxBorder: cs(box).borderTopWidth + ' ' + cs(box).borderTopColor,
      boxRadius: cs(box).borderTopLeftRadius,
      contrast: text ? contrast(tcs.color, cs(box).backgroundColor) : 0,
      // 三点动画：读 duration 而不是 property —— 只读 property 时 `animation: none`
      // 也可能被 `animation-name` 的默认值骗过去（全站那条口径见 README 的"判无动画"）。
      dotAnim: dcs.animationName,
      dotDuration: dcs.animationDuration,
      dotBg: dcs.backgroundColor,
      // 伪元素那两粒：没有独立 DOM，只能从 ::before/::after 的动画名证明它们在场
      dotPeers: ['::before', '::after'].map(
        (p) => (dots ? getComputedStyle(dots, p).animationName : 'none'),
      ),
      dotCount: dots ? 3 : 0,
      // 引导清单：跑动中那一屏**不放**那三条静态引导了（见下面 思考态 6 的改口说明），
      // 这个读数因此变成"反向证据"—— 它必须是 0，而 `.empty-list` 只在终态/空态那一支出现。
      guideBullets: Array.from(document.querySelectorAll('.empty-list li')).length,
      emptyTitle: (q('.empty-title') || {}).textContent?.trim() ?? null,
      /* ---- RunProgress 那一屏的四块读数（2026-09-29 并发改动之后补的） ----
         阶段条 / 骨架屏 / 流式区 / 已用时，四块各有各的判据，不能只靠"思考那一行在场"代表整屏。 */
      rp: Boolean(q('.rp')),
      stages: Array.from(document.querySelectorAll('.rp-stage')).map((x) => ({
        label: (x.querySelector('.rp-stage-label')?.textContent || '').trim(),
        cls: String(x.className || ''),
      })),
      stagesAria: (q('.rp-stages') || {}).getAttribute
        ? q('.rp-stages').getAttribute('aria-label') || ''
        : '',
      skel: Array.from(document.querySelectorAll('.rp-skel .skeleton')).length,
      skelTitle: (q('.sec-label--answer .sec-label-zh') || {}).textContent?.trim() ?? null,
      stream: Boolean(q('.rp-stream')),
      streamBusy: (q('.rp-stream') || {}).getAttribute
        ? q('.rp-stream').getAttribute('aria-busy') || null
        : null,
      caret: Array.from(document.querySelectorAll('.rp-caret')).length,
      elapsed: (q('.rp .tabular') || {}).textContent?.trim() ?? null,
      // 反向证据①：思考态这一屏不许已经偷偷画出**终态**那屏的答案容器
      //（`.answer` 现在允许出现在 `.rp-stream` 里 —— 那是真到达的增量，不是演的）
      answer: Boolean(q('.answer')),
      answerOutsideRp: Boolean(document.querySelector('.answer') && !q('.rp-stream .answer')),
      // 反向证据②：消耗/耗时这些没跑完就无从谈起，画出来就是编数
      metrics: document.querySelectorAll('.metric-grid .metric').length,
      // 反向证据③：终态那一整屏（.result-wrap：task id chip + 指标 + 引用）不该提前出现
      resultWrap: Boolean(q('.result-wrap')),
    };
  })();
}

/* ------------------------------ A 回放态 ------------------------------ */
async function passReplay(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await openTask(page);
  console.log(`\n== A 回放态 · ${label} ==`);

  /* 前件（页签调换，2026-09-28）：选中一条已完成的任务之后，落在「运行结果」而不是日志，
     且日志面板**一行都没建**（rc-tabs 对没激活过的面板不渲染 children）。
     这一条是本轮改动的正面读数；下面所有 `.log*` 判据都以"我先自己把页签点开了"为前提
     （见 openLogTab 顶上的注释 —— 那一击刻意不藏进 openTask）。 */
  const landed = await page.evaluate(() => ({
    active: (document.querySelector('.ant-tabs-tab-active')?.textContent || '').replace(/\s+/g, '').slice(0, 4),
    order: Array.from(document.querySelectorAll('.ant-tabs-tab')).map((t) =>
      (t.textContent || '').replace(/\s+/g, '').slice(0, 4),
    ),
    resultWrap: document.querySelectorAll('.result-wrap').length,
    logBody: document.querySelectorAll('.log-body').length,
    // 思考态那一行只在跑动中出现：已完成的任务不挂它（否则"还在想"是句假话）
    thinking: document.querySelectorAll('.thinking').length,
  }));
  check('A 前件：选中任务后停在「运行结果」（页签调换）', landed.active === '运行结果' && landed.resultWrap === 1, landed);
  check(
    'A 前件：页签顺序是 运行结果 → 实时日志 → 工具调用',
    JSON.stringify(landed.order) === JSON.stringify(['运行结果', '实时日志', '工具调用']),
    landed.order,
  );
  check('A 前件：日志页签没点过 ⇒ 终端整体不在 DOM 里（按需挂载现在两头都要成立）', landed.logBody === 0, landed);
  check('A 前件：已完成的任务不挂「Agent 正在…」那一行', landed.thinking === 0, landed);
  await openLogTab(page);

  console.log(`\n== A 回放态 · ${label} ==`);
  const t = await page.evaluate(readTerminal);
  console.log(JSON.stringify(t, null, 1).slice(0, 900));

  check('终端底色 = 深灰蓝 #1e2734（参考稿那一档，两主题同一套）', t.logBg === 'rgb(30, 39, 52)', t.logBg);
  check('外层 12px 圆角', t.logRadius === '12px', t.logRadius);
  check('外描边 1px 实色 #2a3442（不再是半透明白，避免与底色合成出第三个色）', t.logBorder === 'rgb(42, 52, 66)', t.logBorder);
  check('正文用 #c9d1d9 而不是纯白', t.msgColor === 'rgb(201, 209, 217)', t.msgColor);
  check('正文对比度 ≥4.5', t.msgOnBgContrast >= 4.5, t.msgOnBgContrast);
  check('序号对比度 ≥4.5（参考稿的 #8b98a5 在心跳行薄底上只有 4.46）', t.seqOnBgContrast >= 4.5, t.seqOnBgContrast);
  /* 四列定宽布局：参考稿的「对齐」逻辑照搬，150px 那个数值不照搬（那是时间戳的宽度） */
  check('行是四列网格：序号 | 级别 | 节点 | 正文', t.rowCols === 4, t.colWidths);
  check('前三列定宽、正文吃剩余', /^(\d+(\.\d+)?)px (\d+(\.\d+)?)px (\d+(\.\d+)?)px (\d+(\.\d+)?)px$/.test(t.colWidths || ''), t.colWidths);
  check('每一行都有级别列', t.levelRows === t.rowTotal && t.levelRows > 0, [t.levelRows, t.rowTotal]);
  check(
    '级别列用的是四个词（不只靠颜色）',
    ['DEBUG', 'INFO', 'WARN', 'ERROR'].some((x) => t.levelLabels.includes(x)) &&
      t.levelLabels.every((x) => ['DEBUG', 'INFO', 'WARN', 'ERROR'].includes(x)),
    t.levelLabels,
  );
  check(
    '四个级别列字色在终端底上都 ≥4.5',
    Object.keys(t.levelContrast).length > 0 && Object.values(t.levelContrast).every((c) => c >= 4.5),
    t.levelContrast,
  );
  check('滚动条走细档（scrollbar-width: thin）', t.bodyScrollbarWidth === 'thin', t.bodyScrollbarWidth);
  check('正文区两个方向都能滚（长行横向滚，不硬拆行）', t.bodyOverflow === 'auto', t.bodyOverflow);
  check('行间细线 1px 已挂上', t.ruleWidth === '1px' && Boolean(t.ruleColor), [t.ruleWidth, t.ruleColor]);
  check('心跳行确实换了薄底色', t.liveRowBg === 'rgba(139, 152, 165, 0.09)', t.liveRowBg);
  const nodes = Object.entries(t.nodeContrast);
  check('四个节点色都读到实测值', nodes.length >= 3, nodes);
  check(
    '节点色在终端深底上全部 ≥4.5（旧口径是 2.84~3.26）',
    nodes.length > 0 && nodes.every(([, c]) => c >= 4.5),
    nodes,
  );
  check('两主题下节点色同一档（终端层不跟主题抖）', nodes.every(([n, c]) => c === t.nodeContrast[n]), nodes);

  /* 心跳合并：fixture 里 3 条连续 running 事件 ⇒ 1 行 */
  check('连续 3 条心跳并成 1 行', t.liveCount === 1, t.liveCount);
  check('可见行 = 11（13 条事件 − 2 条被并）', t.rowTotal === 11, t.rowTotal);
  check('合并行的 key 身份是首条 seq #009', t.liveSeq === '#009', t.liveSeq);
  check('尾巴写出重复次数', /已重复 3 次/.test(t.liveTail || ''), t.liveTail);
  check('页脚显式说明合并了多少条', /合并重复 2 条/.test(t.footText || '') && /已显示 11 行 \/ 13 条/.test(t.footText || ''), t.footText);
  check('终态整页不挂转圈（跑完了还有一条在加载 = 用户实测那颗）', t.liveMarks === 0, t.liveMarks);
  check('转圈收掉后合并行仍是合并行（薄底色 + 尾巴都留着）', t.liveCount === 1 && t.liveMark === false, [t.liveCount, t.liveMark]);
  check('合并行不再走逐行入场动画', t.liveAnim === 'none', t.liveAnim);

  /* ③ 运行条去重 + 终态不该有的运行态元素 */
  check('运行条里没有 .rm 指标块', t.runMetrics === 0, t.runbarText);
  check('运行条只剩状态 + stepper + （终态无取消按钮）', /排队中|运行中|成功|已收口|失败|已取消/.test(t.runbarText || '') && t.cancel.length === 0, t.cancel);
  check('终态不显示 CLI 光标', t.cursor === 0, t.cursor);
  check('终态页脚不跳秒', t.clock === null, t.clock);
  check('终态徽标不呼吸', t.badgeLive === false, t.badgeLive);
  check('已完成 → 三个节点全 done', t.steps.every((s) => /is-done/.test(s.cls)), t.steps.map((s) => s.cls));
  check('实心圆里的字形用反色档（可读）', t.steps.every((s) => s.glyphColor !== 'rgb(103, 110, 124)'), t.steps[0].glyphColor);

  /* ---- 录屏报告 UX-2：图标栏的可发现性 ----
     报告说「4 个纯图标，未见 tooltip」—— 悬停其实一直都有，录屏没悬停过所以没拍到。
     真正缺的是键盘这条路径：rc-tooltip 默认只挂 hover，Tab 过去什么都读不到。 */
  await page.locator('.rail-btn').first().focus();
  await page.waitForTimeout(400);
  const tips = await page.locator('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner').allTextContents();
  check('键盘聚焦图标栏也弹得出文字标签', tips.some((x) => /任务与日志/.test(x)), tips);
  const railLabels = await page.locator('.rail-btn').evaluateAll((ns) => ns.map((n) => n.getAttribute('aria-label')));
  check('每个图标都有 aria-label（读屏不必依赖 tooltip）', railLabels.every((x) => !!x && x.length >= 2), railLabels);

  /* ---- 录屏报告 UI-4 + UX-5：结果页头部那三张并列指标卡 ----
     ⚠️ 这一段必须在 .log 那张截图**之后**：切到「运行结果」页签后，AntD 给不活跃的
     页签挂 visibility:hidden（布局还在、getBoundingClientRect 还有高度），
     于是「读得到样式、截不到图」—— 先截终端，再切页签，才不会被这个假可见性骗到。 */
  check('无 pageerror', errors.length === 0, errors.slice(0, 3));

  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.log').screenshot({ path: path.join(OUT, `${label}-terminal.png`) });
  await page.locator('.runbar').screenshot({ path: path.join(OUT, `${label}-runbar.png`) });

  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(600);
  const m = await page.evaluate(readMetricParity);
  check('结果页头部指标区在', m.present === true, m.present);
  check(
    '指标卡所在页签确实可见（AntD 隐藏页签照样排版，读到样式 ≠ 看得见）',
    m.visible === true,
    m.visible,
  );
  check(
    '三张卡同字号同字重（报告说「迭代轮数」被降成小号药丸，实测读的是渲染结果）',
    m.tiles.length === 3 && new Set(m.tiles.map((x) => `${x.size}/${x.weight}`)).size === 1,
    m.tiles.map((x) => [x.label, x.size, x.weight]),
  );
  const iter = m.tiles.find((x) => x.label === '迭代轮数');
  check(
    '「迭代轮数」把口径写在场内（0 = 首轮复核即通过，不是没跑）',
    !!iter && iter.gloss > 20 && /首轮|退回重跑/.test(iter.hint),
    iter,
  );
  /* C8：用户实测两条同样的 `1+1` 消耗不同，第一反应是"是不是有 bug"。
     这句解释必须**当场在场**，而且不许退化成"属正常，别担心" ——
     所以三样都要断言：提到采样、提到计费时段、并且带着实测数字（有 `\d` 的"实测"）。
     反向也钉：只写"会有浮动"没有数的文案，这条要翻红。 */
  const tok = m.tiles.find((x) => x.label === '总 token');
  check(
    '「总 token」当场说清"两次不一样"：采样 + 计费时段两个原因分开讲，且带实测数字（C8）',
    !!tok && /采样/.test(tok.tip) && /时段|×0\.5/.test(tok.tip) && /实测/.test(tok.tip) && /\d/.test(tok.tip),
    tok ? tok.tip.slice(0, 46) : tok,
  );
  check(
    '三块卡的读数都拿到了（不补 0、不显示空串）',
    m.tiles.every((x) => x.value.length > 0),
    m.tiles.map((x) => x.value),
  );
  await page.locator('.metric-grid--head').screenshot({ path: path.join(OUT, `${label}-metrics.png`) });

  /* ---- 录屏报告 UI-3：中/西/希腊/等宽各自落进哪一族（实测，不看声明） ---- */
  const fam = await platformFamilies(ctx, page, [
    ['cjk', '功耗监控标准', '.answer'],
    ['latin', 'Stationary', '.answer'],
    ['greek', 'η β Σ γ', '.answer'],
    ['mono', 'P mains', '.ast-math'],
  ]);
  const top = (k) => (fam[k].fonts.slice().sort((a, b) => b[1] - a[1])[0] || ['（空）', 0])[0];
  console.log(
    '   实际字族：',
    Object.entries(fam).map(([k, v]) => `${k}=${top(k)}@${v.host}`).join('  '),
  );
  check(
    '希腊字母与拉丁同族（η 不该掉进衬线或等宽里 —— 报告 UI-3 真正能修的那一半）',
    fam.greek.fonts.length > 0 && top('greek') === top('latin'),
    [top('latin'), top('greek')],
  );
  check(
    '中文与拉丁确实不同族（不打包字体的必然结果，记进报告不当缺陷修）',
    top('cjk') !== top('latin'),
    [top('latin'), top('cjk')],
  );
  check(
    '公式块换到了等宽族，且宿主存在（.ast-math 没渲染时这条会指出兜底到了 body）',
    fam.mono.host === '.ast-math' && top('mono') !== top('latin'),
    [fam.mono.host, top('mono')],
  );
  /* 只报数，不判定：document.fonts.check('16px Inter') 对**没有任何 @font-face 的族**
     恒返回 true（没有待加载的字面 = 全部已加载），所以它证明不了 Inter 在场。
     真正在场与否，看上面 CDP 读到的实际字族。 */
  console.log(
    '   声明栈首个族 = Inter / JetBrains Mono，本机实际渲染用的是上面那几族（项目不分发字体文件）',
  );

  check('截图前没有 pageerror', errors.length === 0, errors.slice(0, 3));
  console.log(`  ✓ 截图 → ${label}-terminal / ${label}-runbar / ${label}-metrics`);
  await ctx.close();
}

/* ------------------------------ B 运行态 ------------------------------ */
/** 心跳 ×3 + planner 一帧，**不发终态**；详情接口回 running ⇒ 任务稳定停在未来态。 */
function runningFrames() {
  const f = [];
  const push = (event, seq, payload) =>
    f.push(`event: ${event}\ndata: ${JSON.stringify({ seq, ts: new Date().toISOString(), ...payload })}\n\n`);
  push('snapshot', 1, { status: 'running', progress: null });
  push('heartbeat', 2, { running_ms: 15000 });
  push('heartbeat', 3, { running_ms: 30000 });
  push('heartbeat', 4, { running_ms: 45000 });
  push('node', 5, { node: 'planner', update: { plan: ['拆三步', '检索', '复核'] }, status: 'running' });
  return f.join('');
}

/** 第二次提交（新 task_id）用：把所有帧的 ts 挪到 ageMs 之前 ⇒ 运行条的「最后一条日志」必须变黄。
 *
 *  这是**故意**造出来的时间差：POST 回来的 submitted_at 仍是当下，所以同一屏会同时出现
 *  「提交后 1.0s」和「最后一条日志 45 秒前」。真机上不会出现这个组合（日志不会比任务更老），
 *  这里要验的只有「超过 30 秒 → is-stale → 告警色 ≥4.5」这一条，截图也只裁 .runbar-actions。 */
function staleFrames(ageMs) {
  const ts = new Date(Date.now() - ageMs).toISOString();
  const f = [];
  const push = (event, seq, payload) =>
    f.push(`event: ${event}\ndata: ${JSON.stringify({ seq, ts, ...payload })}\n\n`);
  push('snapshot', 1, { status: 'running', progress: null });
  push('node', 2, { node: 'planner', update: { plan: ['拆三步', '检索', '复核'] }, status: 'running' });
  push('heartbeat', 3, { running_ms: ageMs });
  return f.join('');
}

/** 运行条右侧那枚读数的实测状态（文案 / 是否告警 / 颜色 / 在告警底色上的对比度）。
 *  ⚠️ 必须自包含：page.evaluate 只序列化函数体，模块作用域里的常量拿不到
 *  （readTerminal 里那份 contrast 同理，两处各有一份不是手滑）。 */
function readRunbarLast() {
  return (() => {
    const el = document.querySelector('.runbar-last');
    const bar = document.querySelector('.runbar');
    const cs = el ? getComputedStyle(el) : null;
    const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
    const lin = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
    const pop = document.querySelector('.ant-popconfirm');
    /* ⚠️ 读数不在（终态）也要回 status / popconfirm —— 「取消之后状态变了没有」
       正是取消那两条断言要看的东西，早退会把它一起吞掉。 */
    const out = {
      present: !!el,
      status:
        ((document.querySelector('.runbar .status-badge') || {}).textContent || '').trim(),
      popOpen: !!pop && !pop.classList.contains('ant-popover-hidden'),
      popText: pop ? pop.textContent.trim() : '',
    };
    if (!el || !bar) return out;
    const fa = nums(cs.color);
    const A = fa.length > 3 ? fa[3] : 1;
    const bg = nums(getComputedStyle(bar).backgroundColor);
    const fg = fa.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
    const l1 = lum(fg);
    const l2 = lum(bg);
    out.text = el.textContent.trim();
    out.stale = el.classList.contains('is-stale');
    out.color = cs.color;
    out.weight = Number(cs.fontWeight);
    out.gloss = (el.title || '').length;
    out.contrast = +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    return out;
  })();
}

/** 结果页三张并列指标卡的排版层级（录屏报告 UI-4：怀疑「迭代轮数」被降成了小药丸）。
 *
 *  ⚠️ 带 visible 这条：AntD 不活跃的页签是 visibility:hidden —— 布局还在、
 *  getBoundingClientRect 照样给出高度、getComputedStyle 照样给出字号，
 *  所以「读到了样式」完全可能是读了一份藏起来的 DOM。offsetParent 抓不到这种情况，
 *  只能一路往上查 visibility / display。 */
function readMetricParity() {
  return (() => {
    const grid = document.querySelector('.metric-grid--head');
    if (!grid) return { present: false };
    const vis = (el) => {
      let n = el;
      while (n) {
        const s = getComputedStyle(n);
        if (s.visibility === 'hidden' || s.display === 'none') return false;
        n = n.parentElement;
      }
      return true;
    };
    const tiles = Array.from(grid.querySelectorAll('.metric')).map((m) => {
      const v = m.querySelector('.metric-value');
      const cs = getComputedStyle(v);
      /** 释义全文从哪儿读。
       *  F-4 之后它不在卡片的原生 `title` 上了（原生 title 与 Tooltip 会叠两层），
       *  而是 `.metric-info` 按钮里那句 `.sr-only` —— Tooltip 的文案是弹层，
       *  **没打开时不在 DOM 里**，判据必须读这份常驻的。
       *  读不到就退回原生 title（不是 MetricTile 的那些卡仍用 title 挂解释）。 */
      const btn = m.querySelector('.metric-info');
      const span = btn && btn.querySelector('.sr-only');
      const tip = (span && span.textContent) || m.getAttribute('title') || '';
      return {
        label: (m.querySelector('.metric-label span:not(.anticon)') || {}).textContent?.trim() || '',
        value: v.textContent.trim(),
        size: cs.fontSize,
        weight: cs.fontWeight,
        height: Math.round(v.getBoundingClientRect().height),
        tileHeight: Math.round(m.getBoundingClientRect().height),
        tip,
        /** `gloss` 只有长度，挡得住"挂了一句没用的话"但挡不住"话说漂了" ——
         *  所以两个都留：长度给判据，全文给内容断言（C8）。 */
        gloss: tip.length,
        hint: (m.querySelector('.metric-hint') || {}).textContent?.trim() || '',
      };
    });
    return { present: true, visible: vis(grid), tiles };
  })();
}

/** 虚拟化日志行的**几何体检**。
 *
 *  行的位置由行内 `transform: translateY(start)` 给出，而 CSS 层叠里**动画值压在行内样式之上**
 *  （author-normal 的 inline style 排在 animations 之下）。所以只要有任何关键帧动了 `transform`，
 *  放过这段动画的行就会脱离 virtualizer 给的 start —— 配 `fill-mode: both` 更是**永久**脱离，
 *  真机上看到的就是「日志内容重叠」。
 *  这是虚拟化**才引入**的失效模式：改造前行在正常流里，动画碰不到定位。
 *  `top` 量在 spacer 里（不是 body）—— `.log-body` 有 6px 上下内边距，拿 body 当原点会全线假红。 */
function readRowGeom() {
  return (() => {
    const spacer = document.querySelector('.log-virtual');
    if (!spacer) return { mounted: 0, noSpacer: true };
    const sr = spacer.getBoundingClientRect();
    const rows = Array.from(document.querySelectorAll('.log-row')).map((el) => {
      const cs = getComputedStyle(el);
      const m = cs.transform === 'none' ? null : cs.transform.match(/matrix\(([^)]+)\)/);
      const inline = (el.style.transform.match(/translateY\(([-\d.]+)px\)/) || [])[1];
      const r = el.getBoundingClientRect();
      return {
        idx: Number(el.dataset.index),
        start: inline === undefined ? null : Math.round(Number(inline)),
        ty: Math.round(m ? Number(m[1].split(',')[5]) : 0),
        top: Math.round(r.top - sr.top),
        h: Math.round(r.height),
        anim: cs.animationName,
      };
    });
    const byIdx = [...rows].sort((a, b) => a.idx - b.idx);
    const overlap = [];
    for (let i = 1; i < byIdx.length; i += 1) {
      const p = byIdx[i - 1];
      const c = byIdx[i];
      if (c.top < p.top + p.h - 1) overlap.push([p.idx, c.idx, p.top, p.h, c.top]);
    }
    return {
      mounted: rows.length,
      /* 这一趟到底有没有行放过动画。没有就是空跑，必须单独报出来 */
      withAnim: rows.filter((x) => x.anim !== 'none').length,
      hijacked: rows.filter((x) => x.anim !== 'none' && x.start !== null && x.ty !== x.start).length,
      misplaced: rows.filter((x) => x.start !== null && Math.abs(x.ty - x.top) > 1).length,
      overlap,
      sample: rows.slice(0, 4).map((x) => [x.idx, x.start, x.ty, x.top, x.anim]),
    };
  })();
}

async function passRunning(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const page = await ctx.newPage();
  const errors = [];
  const cancelHits = [];
  /* ---- 假后端的调度表：第二次提交换一个新的 task_id，SSE 按 URL 里的 id 分流 ----
     P0-06 之后「第几条连接」不再等于「第几次提交」：一条没有终态帧的流关闭后，客户端会按
     1s/3s/9s 退避重连，而那条重连落在第几秒取决于前面这一串检查跑多快 —— 上一版拿 sseCall
     当提交下标用，light 恰好对得上、dark 慢半拍就全线错位（45 秒前的帧提前灌进常态那一段，
     尾巴读数 / 告警档一起翻车）。按 id 分流才是与计时无关的判据。
       · 第一个任务的首连：延迟 4 秒回 runningFrames()，且**故意不带终态帧**；
       · 第一个任务的每一条重连：挂住不回 —— 等价于真机上「连接活着但没新事件」，
         既不往日志里掺行，也不会把「最后一条日志 N 秒前」重新按回 0；
       · 第二个任务（45 秒前的那批帧）：逼出 is-stale 告警档，只回一次，之后同样挂住。
     两次提交本来就该是两条任务 —— 复用同一个 id 才是这里的不真实之处。 */
  const SECOND_ID = 'task-2e-submit';
  let sseCall = 0;
  let submitCalls = 0;
  let firstServed = false;
  let staleServed = false;
  const hangs = [];
  const sseHeaders = { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' };
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await page.route('**/api/tasks', (r) => {
    const id = submitCalls === 0 ? TASK_ID : SECOND_ID;
    submitCalls += 1;
    return r.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: id,
        status: 'queued',
        stream_url: `/tasks/${id}/stream`,
        poll_url: `/tasks/${id}`,
        cancel_url: `/tasks/${id}/cancel`,
        queue_position: null,
        submitted_at: new Date().toISOString(),
        estimated_cost_cny: 0.0042,
        warnings: null,
      }),
    });
  });
  /* 后注册的 route 优先：这里要同时接管详情与 SSE —— 详情必须回 running，
     否则 SSE 一关页面就落终态，运行态的三个元素（光标/呼吸/跳秒）根本来不及看。 */
  await page.route('**/api/tasks/*', (r) => {
    const u = r.request().url();
    if (u.includes('/trace')) {
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(traceBody) });
    }
    // ⚠️ 这里**没有** `/cancel` 分支，不是漏了：Playwright 的 `*` 不跨 `/`，所以
    // `**/api/tasks/*` 盖不到 `/api/tasks/{id}/cancel` —— 旧版塞在它里面那个"一律 200"的
    // 分支从来没命中过，真正答取消的是 installMocks 里那条 `**/api/tasks/*/cancel`。
    // 409 / 404 / 没送达 三种结局要到 P 趟（passCancelOutcome）才可达，那里把取消单独
    // 注册成能改状态码的桩。
    // （为什么这段不用块注释：块注释里写 glob 会被串中间的 `*/` 提前闭合，node --check
    //  也不报错 —— 这个坑记在 tools/uicheck/README.md，本轮已经踩到第三次。）
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...detail, status: 'running', final_answer: null, duration_ms: null }),
    });
  });
  await page.route('**/sse/tasks/*/*', async (r) => {
    const n = (sseCall += 1);
    const second = r.request().url().includes(SECOND_ID);
    /* 判定一律在 await 之前做完：晚一步就可能把 45 秒前的帧发给一条不该收它的连接。 */
    const answer = second ? !staleServed : !firstServed;
    if (answer) {
      if (second) staleServed = true;
      else firstServed = true;
    }
    console.log(
      `   · SSE #${n} ${second ? '第二任务' : '第一任务'} ⇒ ${
        answer ? (second ? '45 秒前的帧' : 'running 帧') : '挂住不回（连着但没新事件）'
      }`,
    );
    if (!answer) {
      /* 挂起而不是应答：应答（哪怕是纯注释帧）会立刻关流 ⇒ 又一条重连又一遍退避。
         兑现交给收口时的 hangs.splice —— 刻意不用 setTimeout 轮询，
         悬着的计时器会把 Node 进程按住几十秒不退出。 */
      await new Promise((res) => hangs.push(res));
      return undefined;
    }
    /* 第二任务的帧延到 1.4 秒（原来随手写的 300ms）：页签调换之后提交会把人带回
       「运行结果」，探针要点回日志页签需要时间 —— 行**在隐藏的面板里落地**的话，
       LogStream 那份 `seen` 账会把它们的 seq 先记掉（它按 rows 记，不按"进过视口"记），
       等面板重新可见时 `playInAllowed` 已经是 false ⇒ 整批不放动画，
       下面「第二帧批确实有行放过入场动画」那条几何守卫就成了空跑。 */
    await new Promise((res) => setTimeout(res, second ? 1400 : 4000));
    return r.fulfill({
      status: 200,
      headers: sseHeaders,
      body: second ? staleFrames(45_000) : runningFrames(),
    });
  });
  /* cancel 请求到底发出去没有 —— 这是「二次确认」唯一算数的判据。
     只看界面变没变会漏掉「弹了确认框但同时也已经取消了」这种假安全。 */
  page.on('request', (rq) => {
    if (rq.url().includes('/cancel')) cancelHits.push(rq.url());
  });

  console.log(`\n== B 运行态 · ${label} ==`);
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);

  /* ---- 录屏报告 UI-5（2026-09-27 换了修法）：这一层现在是**模态**的 ----
     原来它是 380px 的 Popover，与输入框同层 ⇒ 才有过"浮层压着『请填写任务目标』"那一帧，
     还要靠"提交时顺手收起浮层"补救，而 Ctrl+Enter 不触发外部点击、补救不到。
     换成 Modal 之后遮罩把两件事分到不同层，那一帧**结构上不可能再出现** ⇒
     判据跟着换成"这一击落在浮层上，不落回输入框本体"（读 elementFromPoint，不是读某个类名在不在）。
     ⚠️ 第一版这里判的是"命中的那个元素类名里有没有 mask" —— 两条场景各红一次，
        读回来的是 ``DIV.sc-body`` 与 ``DIV.ant-modal-header``。原因不是界面没挡住，
        而是**判据写窄了**：720px 的模态正好压在输入框上方，那一点之下是 Modal 的**内容**，
        内容在遮罩之上 ⇒ 命中内容同样说明这一击到不了 textarea。
        所以口径换成三条：命中了东西、不是 textarea 自己、且属于 ``.ant-modal-root`` 那一层
        （遮罩与内容都在这层里；不这么收窄的话，"命中了页面上随便一个 div"也能蒙过这条）。 */
  await page.locator('.cp-icon').click();
  await page.waitForSelector('.rcp', { state: 'visible' });
  const blocked = await page.evaluate(() => {
    const ta = document.querySelector('textarea.composer-input');
    if (!ta) return { found: false, hit: '(没有输入框)', isSelf: false, inModalLayer: false };
    const r = ta.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(20, r.height / 2));
    return {
      found: true,
      hit: hit ? `${hit.tagName}.${String(hit.className)}` : '(无)',
      isSelf: Boolean(hit && hit.closest('textarea.composer-input')),
      inModalLayer: Boolean(hit?.closest('.ant-modal-root')),
    };
  });
  check('设置开着时，输入框那个位置命中的不是 textarea 本体，而是浮在它上面的那一层（Modal 的内容或遮罩 —— UI-5 那一帧从此不可能出现）',
    blocked.found && blocked.isSelf === false && blocked.inModalLayer === true, blocked);
  /* 关掉这一层再往下走：下面的 fill / click 都要真点到 composer 上的控件。 */
  await page.locator('.ant-modal-close').click();
  await page.waitForTimeout(400);
  await page.locator('.composer-input').press('Control+Enter');
  await page.waitForTimeout(500);
  const errBox = page.locator('.ant-form-item-explain-error');
  check('空提交有看得见的校验文案（不是只剩一个红框）', await errBox.isVisible(), await errBox.textContent());

  await page.locator('.composer-input').fill('1024 路摄像头整机功耗怎么估算？给出算式与结果');
  await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();

  // 提交后立刻：SSE 还没落地，任务处于非终态 ⇒ 光标/呼吸/跳秒都该在。
  // 这一段日志面板还是**浅色静默态**（零日志不套终端皮肤），所以只查这三件事。
  await page.waitForTimeout(1500);
  /* ---- 页签调换（2026-09-28）：提交之后落在「运行结果」，那一屏先给"思考中" ----
     读的是本轮新增的那一行阶段文案，不是日志面板。放在这里是因为**这一刻的现场是真的**：
     桩里首连延迟 4 秒才回帧，所以这 1.5 秒里任务确实一条节点事件都没交卷 ⇒ 文案必须
     停在通用那句「Agent 正在思考...」（不许提前报"正在规划"，那是没有证据的具体阶段）。 */
  const th0 = await page.evaluate(readThinking);
  check('思考态 1 - 提交后停在「运行结果」，思考态那一行在场（role=status 播报点）',
    th0.present === true && th0.role === 'status' && th0.live === 'polite', th0);
  check('思考态 2 - 一条节点事件都没到时只说通用那句（不提前指名"正在规划"）',
    th0.text === 'Agent 正在思考...', th0.text);
  check('思考态 3 - 三点确实在动（animation-name + duration 都读到；只读 name 会被默认值骗过去）',
    th0.dotAnim === 'thinking-dot' && parseFloat(th0.dotDuration) > 0 && th0.dotPeers.every((n) => n === 'thinking-dot'),
    th0);
  check('思考态 4 - 思考文案对比度 ≥4.5（它落在自己的卡片底色上，不是页面底色）', th0.contrast >= 4.5, th0.contrast);
  /* 思考态 5 的口径随 RunProgress 换过一次：以前判 `.answer === false`（"思考中不许有答案正文"），
     而现在跑动中那一屏**允许**出现答案正文 —— 那一截是真从 SSE `delta` 帧到达的增量
     （components/RunProgress.tsx 的 `.rp-stream`），不是打字机演出来的。所以判据换成
     两条方向相反的：① 终态那一整屏（`.result-wrap`：id chip + 指标 + 引用）不许提前出现；
     ② 出现的答案正文只许待在 `.rp-stream` 里。`answerOutsideRp` 就是②的那枚反向读数。 */
  check('思考态 5 - 思考态不演结果：终态那一整屏与消耗指标都不提前出现，答案正文只许在流式区里',
    th0.resultWrap === false && th0.metrics === 0 && th0.answerOutsideRp === false, th0);
  /* 思考态 6 改口（2026-09-29）：这一条原本钉的是"引导三行没被动画挤掉"（`.empty-list li` 三枚
     + EmptyState 标题）。并发改进来的 RunProgress 把跑动中那一支的空态插画整块删了
     （它的注释写着"再说一遍『结果会逐段出现』是空话"，删得有道理：那一屏现在会长出真东西）。
     同一个**意图**换了承载元素 ⇒ 判据跟着换，而不是删掉：这一屏必须说得出"待会儿会有什么"，
     而它说的是三格阶段条 + 页脚那句「届时这一屏会整段替换」。 */
  check(
    '思考态 6 - 跑动这一屏用阶段条交代"待会儿会有什么"：三格齐、第一格在跑、后面两格没被提前点亮',
    th0.rp === true
      && th0.stages.length === 3
      && ['规划', '执行', '复核'].every((x, i) => (th0.stages[i] || {}).label === x)
      && /is-active/.test((th0.stages[0] || {}).cls || '')
      && th0.stages.slice(1).every((s) => !/is-done|is-active/.test(s.cls))
      && /已完成 0 \/ 3/.test(th0.stagesAria),
    { stages: th0.stages, aria: th0.stagesAria, guideBullets: th0.guideBullets },
  );
  check(
    '思考态 6b - 首个字还没到时给的是骨架屏（占位 + 明说"首个字还没到"），不是一块空白也不是一句"生成中' +
      '"把位置空出来',
    th0.skel >= 3 && th0.stream === false && /首个字/.test(th0.skelTitle || ''),
    { skel: th0.skel, stream: th0.stream, skelTitle: th0.skelTitle },
  );
  check(
    '思考态 6c - 除了三点，还要有一个真的在推进的数（已用时）—— 录屏里那 12 秒分不清"在跑"与"卡死"就是缺这个',
    /已用时/.test(th0.elapsed || ''),
    th0.elapsed,
  );
  check(
    '思考态 6d - 那三条静态引导确实不在跑动这一屏了（形状换了要说得出，免得下一个人以为漏画了去补回来）',
    th0.guideBullets === 0 && th0.emptyTitle === null,
    { guideBullets: th0.guideBullets, emptyTitle: th0.emptyTitle },
  );
  /* ⚠️ 「等待第一条日志」这一读要**在点开日志页签之前**做完：`.runbar-last` 长在页签外面，
     不需要面板挂载，而它等的恰恰是"SSE 还没落地"那个窗口 —— 首连的帧在 4 秒之后才回
     （见上面那条 route 里的 `sleep(second ? 300 : 4000)`），而点开页签本身要花时间。
     上一版把它放在 `a`/`b` 两轮 readTerminal 之后，页签调换又多了一次点击 ⇒ 量到的是
     「最后一条日志 0 秒前」，红的不是产品，是探针自己的排队顺序。 */
  const q0 = await page.evaluate(readRunbarLast);
  check(
    '一条日志都还没到时说「等待第一条日志」，不谎报「0 秒前」',
    q0.present === true && q0.text === '等待第一条日志' && q0.stale === false,
    q0,
  );
  await openLogTab(page);
  const a = await page.evaluate(readTerminal);  check('静默态里也有闪烁光标', a.idle === true && a.cursor >= 1, { idle: a.idle, cursor: a.cursor });
  check('光标是硬切闪烁而不是淡出', a.cursorAnim === 'cursor-blink', a.cursorAnim);
  check('运行中：状态徽标挂上 is-live', a.badgeLive === true, a.badgeLive);
  check('徽标圆点在呼吸', a.badgeAnim === 'breathe', a.badgeAnim);
  check('运行条上没有指标块', a.runMetrics === 0, a.runbarText);
  /* AntD 会在两字按钮的两个汉字间插一个空格（「取 消」），断言要按渲染结果写。 */
  check('取消按钮仍在', a.cancel.some((t) => /取\s*消/.test(t)), a.cancel);
  check('还没收到节点事件时不谎报进度（三节点仍 todo）', a.steps.every((s) => /is-todo/.test(s.cls)), a.steps.map((s) => s.cls));
  const c1 = a.clock;
  await page.waitForTimeout(2200);
  const b = await page.evaluate(readTerminal);
  /* 解析整段数字：fmtDuration 输出「1.02s」，只取 \d+ 会读成 02 而看不出跳动 */
  const secs = (s) => Number((s || '').match(/([\d.]+)s/)?.[1] ?? -1);
  check('页脚时钟在跳秒', secs(c1) > 0 && secs(b.clock) > secs(c1), [c1, b.clock]);

  await page.locator('.log-idle, .log').first().screenshot({ path: path.join(OUT, `${label}-idle-running.png`) });

  // SSE 落地：面板换成深色终端，此后才谈得上 spinner 与心跳合并。
  // 读颜色之前先等 500ms —— .s-circle 的底色有 200ms transition，
  // 抢在过渡中间读 getComputedStyle 会拿到插值色（rgba(0,0,0,0)），误判成没上色。
  await page.waitForSelector('.log-row--live', { timeout: 8000 });
  await page.waitForTimeout(500);
  /* 首批行落在「这个 LogStream 实例第一次有行」的那一次提交里 —— 与 C 趟记录的同一个成因
     （`seen` 被 StrictMode 的第二轮 effect 填满）⇒ 实测**一行都不放动画**（两个主题一致，
     withAnim=0）。所以「动画抢定位」这条守卫量在首批仍是空跑，必须挪到第二帧批
     （下面 staleFrames 之后那次复检）：那批是「已挂载的面板上追加新行」，动画真会放。 */
  const g = await page.evaluate(readRowGeom);
  console.log('  ', JSON.stringify(g));
  check(
    `${label}：首批行的位置就是虚拟器给的 translateY(start)`,
    g.misplaced === 0 && g.mounted > 0,
    [g.misplaced, g.mounted, g.sample],
  );
  check(`${label}：首批相邻行零竖直重叠`, g.overlap.length === 0, g.overlap.slice(0, 6));
  const r = await page.evaluate(readTerminal);
  check(
    '当前节点有 spinner 环在转',
    r.steps.some((s) => /is-active/.test(s.cls) && s.afterAnim === 'spin'),
    r.steps.map((s) => [s.cls, s.afterAnim]),
  );
  check(
    'spinner 环色 = 该节点色',
    r.steps.filter((s) => /is-active/.test(s.cls)).every((s) => s.afterBorder === s.circleBg),
    r.steps.filter((s) => /is-active/.test(s.cls)).map((s) => [s.afterBorder, s.circleBg]),
  );
  check('终端底色 = 深灰蓝 #1e2734（运行态与回放态同底）', r.logBg === 'rgb(30, 39, 52)', r.logBg);
  check('心跳帧合并成一行', r.liveCount === 1, r.liveCount);
  check(
    '运行中：心跳行确实挂着转圈（与 A 趟"终态 0 个"配成双向，少一头这条就恒真）',
    r.liveMarks === 1 && r.liveMark === true,
    [r.liveMarks, r.liveMark],
  );
  check(
    '尾巴用服务端 running_ms（45s），不是前端数秒',
    /订阅后 45(\.0)?s/.test(r.liveTail || ''),
    r.liveTail,
  );
  check('合并行数写进页脚', /合并重复 2 条/.test(r.footText || ''), r.footText);
  check(
    '跑到 Planner 时后两个节点仍是 todo（心跳不会把链路推成全绿）',
    r.steps.filter((s) => /is-todo/.test(s.cls)).length === 2,
    r.steps.map((s) => s.cls),
  );
  check('运行中光标仍在', r.cursor >= 1, r.cursor);
  check('无 pageerror', errors.length === 0, errors.slice(0, 3));
  /* 截图前把闪烁动画钉在「亮」的那一半：cursor-blink 是 steps(1) 硬切，
     一半概率截到的是光标消失的那一帧 —— 像素上要能看见它，才叫验收。 */
  await page.addStyleTag({
    content: '.log-cursor-block,.log-live-mark,.status-badge.is-live .dot{animation:none !important}',
  });
  await page.locator('.log').screenshot({ path: path.join(OUT, `${label}-merged.png`) });
  console.log(`  ✓ 截图 → ${label}-idle-running / ${label}-merged`);

  /* ---- 阶段文案跟着 SSE 走（页签调换这一轮的第 7、8 条）----
     上面那批帧里含 planner 的 `node` 帧，而后端的 `node` 帧是**该节点跑完**才发的
     （api/queue.py 从 runner.stream() 拿到增量之后才 publish）⇒ 这一行必须换成
     "后继在跑"那句（正在执行工具），不许回头说"正在规划任务"。
     写反了的形状在这里第一次可测：只钉通用那句（上面第 2 条）证不出阶段推进。
     ⚠️ 读完必须切回日志页签：下面的几何与 stale 读数都长在终端那一屏上。 */
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(400);
  const th1 = await page.evaluate(readThinking);
  check(
    '思考态 7 - planner 交卷后那句换成后继阶段（「正在执行工具」，不回头说「正在规划」）',
    th1.present === true && th1.text === 'Agent 正在执行工具...',
    th1.text,
  );
  check(
    '思考态 8 - 换了字没换播报点（role=status 还在，读屏跟得到进度）',
    th1.role === 'status' && th1.live === 'polite' && th1.answer === false,
    th1,
  );
  await openLogTab(page);

  /* ---- 录屏报告 SM-1（前端侧）+ U7：最后活跃时间读数 ----
     88 秒近静止是真机观感里最差的一条：步骤条只说得出「在哪个节点」，页脚只说得出「跑了多久」，
     没人回答「上一次有新内容是什么时候」。这条读数补的就是那一句。 */
  const fresh = await page.evaluate(readRunbarLast);
  check(
    'SSE 落地后读数换成「最后一条日志 N 秒前」',
    /^最后一条日志 \d+ 秒前$/.test(fresh.text),
    fresh.text,
  );
  check('刚来过事件不该告警（无 is-stale）', fresh.stale === false, fresh);
  check('读数带得出解释（title 说清心跳不计 + 30 秒阈值）', fresh.gloss > 20, fresh.gloss);
  check('常态字色在运行条底上 ≥4.5', fresh.contrast >= 4.5, fresh.contrast);

  /* 第二次提交：假后端给这条换了新 task_id（见上面那张调度表），
     它的 SSE 回 45 秒前的帧 ⇒ 逼出告警档，不必真等 30 秒（见 staleFrames 的注释）。 */
  await page.locator('.composer-input').fill('换一个问法：把上一步的算法再核一遍');
  await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();
  /* 提交会把人带回「运行结果」⇒ 这里**立刻**点回日志页签，赶在第二帧批落地之前
     （桩把那条连接的帧延到 1.4 秒，就是为了留出这一击的时间）。
     ⚠️ 顺序不能反过来：行在隐藏的面板里落地时，LogStream 的 `seen` 账会先把它们的
     seq 记掉（它按 rows 记，不按"进过视口"记），等面板再可见时 `playInAllowed` 已是
     false ⇒ 整批不放动画，下面「第二帧批确实有行放过入场动画」就成了空跑。 */
  await openLogTab(page);
  await page.waitForTimeout(1800);
  /* 第二帧批 = 「已经挂在屏幕上的面板又追加了新行」，入场动画只在这条路径上才真会放
     （首批赶在换肤那一次提交里，一行都不动，见上面那段）。
     虚拟化才引入的失效模式正好在这儿：动画值在层叠里压在行内样式之上，`log-in` 旧写法动的
     是 transform ⇒ 把行内 translateY(start) 抢成 0，而 fill-mode: both 让终帧**永久**留着 ⇒
     新行贴回容器顶部、与上面几行叠在一起（这一版实测到：start=50 / ty=0 / 与第 1 行重叠）。
     改成动独立属性 translate 之后两者相乘合成，纵向定位仍归虚拟器管。
     这三项钉进用例，是为了下一次有人往 keyframes 里塞 transform 时当场翻红而不是"看着还行"。 */
  const g2 = await page.evaluate(readRowGeom);
  console.log('   · 第二帧批几何：', JSON.stringify(g2));
  check(`${label}：第二帧批确实有行放过入场动画（几何守卫不许空跑）`, g2.withAnim > 0, g2.withAnim);
  check(
    `${label}：入场动画没把新行的 translateY(start) 抢走`,
    g2.hijacked === 0 && g2.misplaced === 0,
    [g2.hijacked, g2.misplaced, g2.sample],
  );
  check(`${label}：第二帧批相邻行零竖直重叠`, g2.overlap.length === 0, g2.overlap.slice(0, 6));
  const stale = await page.evaluate(readRunbarLast);
  check('超过 30 秒没有新内容 → 挂 is-stale', stale.stale === true, stale);
  check('告警档文案跟着秒数走', /^最后一条日志 (4[5-9]|5\d|6\d) 秒前$/.test(stale.text), stale.text);
  check('告警档确实换了色', stale.color !== fresh.color, [fresh.color, stale.color]);
  check('告警字色在运行条底上仍 ≥4.5（黄字最容易在这里翻车）', stale.contrast >= 4.5, stale.contrast);
  check('变黄只加字重，不改字号（不撑动布局）', stale.weight >= 500, stale.weight);
  await page.locator('.runbar-actions').screenshot({ path: path.join(OUT, `${label}-stale.png`) });

  /* ---- 录屏报告 UX-7：取消要有二次确认 ----
     判据不是「有没有弹框」而是「点第一下时 cancel 请求有没有真的发出去」。 */
  await page.locator('.runbar-actions .ant-btn-dangerous').click();
  await page.waitForTimeout(500);
  const armed = await page.evaluate(readRunbarLast);
  check('点「取消」先弹确认框', armed.popOpen === true, armed.popText);
  check('确认框文案区分得开：仍要取消 / 继续运行', /仍要取消/.test(armed.popText) && /继续运行/.test(armed.popText), armed.popText);
  check('第一下不发出 cancel 请求', cancelHits.length === 0, cancelHits);
  check('确认前任务状态不变', /运行中|排队中/.test(armed.status), armed.status);
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await page.waitForTimeout(700);
  const done = await page.evaluate(readRunbarLast);
  check('确认后才真的取消', cancelHits.length === 1 && /已取消/.test(done.status), { cancelHits, status: done.status });
  check('取消后读数消失（终态不再报「多久没更新」）', done.present === false, done);
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  console.log(`  ✓ 截图 → ${label}-stale  ·  SSE 连接 ${sseCall} 条 / 提交 ${submitCalls} 次`);
  hangs.splice(0).forEach((res) => res()); // 放行挂起的重连，别让路由处理器悬在半路
  await ctx.close();
}

/* ------------------------------ C 虚拟容器 ------------------------------ */

/** 240 行：够把 340px 的面板溢出十几倍。每条消息都带 'PoE'，
 *  这样关键字过滤后**行数不减**，才能造出「目标行没挂载」的跳转场景。 */
function virtualTrace(n) {
  const items = [];
  for (let i = 1; i <= n; i += 1) {
    items.push({
      event_seq: i,
      step: (i % 9) + 1,
      sub_step: null,
      event_type: i % 4 === 0 ? 'node_end' : 'tool',
      role: 'executor',
      node: 'executor',
      thought: `第 ${i} 条：核对 PoE 供电标准的原文段落，这一条特意写得长一些，用来逼出折行与不固定行高。`,
      tool_name: 'knowledge_search',
      arguments: { q: 'PoE' },
      observation: 'ok',
      latency_ms: 120 + (i % 900),
      tokens_in: 300,
      tokens_out: 80,
      cost: 0.0004,
      status: 'done',
      error_code: null,
      error_message: null,
      created_at: new Date(Date.now() - (n - i) * 1000).toISOString(),
    });
  }
  return {
    ...traceBody,
    items,
    total: n,
    has_more: false,
    next_after_seq: n,
    events_available: true,
    unavailable_reason: null,
  };
}

/** 虚拟化**独有**的三类失效模式：不挂载就没有 DOM 可查、历史行会被反复挂载、
 *  测高回填会让「距底」这个判据突然失真。这三条在改造前不存在，所以必须在这里钉住 ——
 *  否则它们只会在真机上以「点了没反应」「滚动时整页闪」「日志自己不更新了」的形式复现。 */
async function passVirtual(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), 'dark');
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 必须在 installMocks 之后注册：Playwright 后注册的 route 先匹配，
     否则会被 mocks 那份 13 条的小 trace 盖掉。 */
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(virtualTrace(240)) }),
  );
  await openTask(page);
  /* 这一趟从头到尾读的是终端（虚拟列表的几何、粘底、命中跳转），所以先点开日志页签。
     顺带留一句：240 行在**没点开**时是 0 个 `.log-row` —— 那正是 V 趟②钉的按需挂载。 */
  await openLogTab(page);

  console.log('\n== C 虚拟容器 · dark（240 行）==');

  /* ⓪ 行的绘制位置必须等于 virtualizer 给的 translateY(start)，相邻行不许竖直重叠。
     回放态里 `seen` 已被 StrictMode 的第二轮 effect 填满 ⇒ 没有行放动画（withAnim=0），
     所以「动画抢定位」只能在 B 运行态那趟的**第二帧批**验（首批同理没动画），这里只钉几何。 */
  const geom = await page.evaluate(readRowGeom);
  console.log('  ', JSON.stringify(geom));
  check('挂载行的绘制位置 = translateY(start)', geom.misplaced === 0 && geom.mounted > 0, [
    geom.misplaced,
    geom.mounted,
    geom.sample,
  ]);
  check('相邻日志行零竖直重叠', geom.overlap.length === 0, geom.overlap.slice(0, 8));

  /* ① 常驻行数与总行数解耦 */
  const dec = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.log-row'));
    const foot = document.querySelector('.log-foot');
    const shown = foot ? (foot.textContent.match(/已显示 (\d+) 行/) || [])[1] : null;
    return {
      mounted: rows.length,
      total: Number(shown || 0),
      elements: document.querySelector('.log').querySelectorAll('*').length,
      spacerH: Math.round(document.querySelector('.log-virtual')?.getBoundingClientRect().height || 0),
    };
  });
  console.log('  ', JSON.stringify(dec));
  check('挂载行数 ≤ 60（与总行数解耦）', dec.mounted > 0 && dec.mounted <= 60, dec.mounted);
  check('总行数远大于挂载行数（确实只挂了一窗）', dec.total >= 200 && dec.mounted < dec.total / 3, [
    dec.mounted,
    dec.total,
  ]);
  check('spacer 撑出全量高度（远高于一屏）', dec.spacerH > 340 * 3, dec.spacerH);

  /* ② 滚到中段：历史行不许重放入场动画 */
  const anim = await page.evaluate(async () => {
    const body = document.querySelector('.log-body');
    body.scrollTop = Math.round(body.scrollHeight * 0.45);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const rows = Array.from(document.querySelectorAll('.log-row'));
    return {
      mounted: rows.length,
      withAnim: rows.filter((el) => getComputedStyle(el).animationName !== 'none').length,
      inClass: rows.filter((el) => el.classList.contains('log-row--in')).length,
      topOffset: Math.round(rows[0].getBoundingClientRect().top - body.getBoundingClientRect().top),
    };
  });
  console.log('  ', JSON.stringify(anim));
  check('滚到中段后挂载行仍是一窗（不是全量）', anim.mounted > 0 && anim.mounted <= 60, anim.mounted);
  check(
    '滚回来的历史行不重放入场动画',
    anim.withAnim === 0 && anim.inClass === 0,
    [anim.withAnim, anim.inClass],
  );
  check('绝对定位生效：首行偏移由 translateY 决定（不是 0）', anim.topOffset < 0 || anim.topOffset > 0, anim.topOffset);

  /* ③ 钉在底部时高度回填 ⇒ 自动滚动不能被误关。
     真实成因：新行先按估算高度占位、measureElement 之后才回填真实高度，
     一批折行长消息会把 scrollHeight 突然撑长几十到几百像素。这里直接改 spacer 高度
     并派发 scroll，复现同一件事。旧判据「距底 > 24px 就算用户上滑」会在这里误关。

     ⚠️ 读数不能只等一次 rAF。页脚那句「自动滚动已开启」是 React state 提交后的产物，
     而 setState 是微任务里排的 —— 一帧常常还没落地。实测同一份代码单跑两趟全绿，
     全量第三跑读到 `before:false`（把"没读到"当成了"被误关"）。
     改法分两种口径，别混：**前件**（重新钉底要把开关打开）用轮询等到位 —— 等不到
     就是 fixture 坏了，判红是对的；**被测那一读**用固定沉降窗（三帧 + 120ms），
     绝不能轮询"它有没有变回 true"，那会把断言等成恒真。 */
  const stick = await page.evaluate(async () => {
    const body = document.querySelector('.log-body');
    const spacer = document.querySelector('.log-virtual');
    const on = () => document.querySelector('.log-foot').textContent.includes('自动滚动已开启');
    const raf = () => new Promise((r) => requestAnimationFrame(r));
    const settle = () => Promise.all([raf(), raf(), raf(), new Promise((r) => setTimeout(r, 120))]);

    body.scrollTop = body.scrollHeight;
    body.dispatchEvent(new Event('scroll'));
    let before = false;
    for (let i = 0; i < 30 && !before; i += 1) {
      await raf();
      before = on();
    }
    const grew = spacer.style.height;
    spacer.style.height = `${parseFloat(grew) + 400}px`;
    body.dispatchEvent(new Event('scroll'));
    await settle();
    const after = on();
    /* 真人上滑必须还能关掉它 —— 只测「不误关」会漏掉反向的回归 */
    body.scrollTop = Math.max(0, body.scrollTop - 120);
    body.dispatchEvent(new Event('scroll'));
    await settle();
    const afterManual = on();
    return { before, after, afterManual, dist: Math.round(body.scrollHeight - body.scrollTop - body.clientHeight) };
  });
  console.log('  ', JSON.stringify(stick));
  check('前件：重新钉底能把开关打开（打不开就别谈"不误关"）', stick.before === true, stick);
  check('钉底后高度回填**不**误关自动滚动', stick.after === true, stick);
  check('用户真的上滑 120px 时仍然关掉（反向没被改坏）', stick.afterManual === false, stick.afterManual);

  /* ④ 目标行没挂载时，上一处/下一处也要滚过去 */
  await page.getByPlaceholder('过滤关键字').fill('PoE');
  await page.waitForTimeout(500);
  const jump = await page.evaluate(async () => {
    const btn = () =>
      Array.from(document.querySelectorAll('.log-hit-btn')).find((b) =>
        (b.getAttribute('aria-label') || '').includes('下一处'),
      );
    const footText = () => document.querySelector('.log-hits')?.textContent.replace(/\s+/g, '') || '';
    if (!btn()) return { err: '没有下一处按钮', foot: footText() };
    for (let i = 0; i < 40; i += 1) {
      btn().click();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    }
    const body = document.querySelector('.log-body');
    const act = document.querySelector('.log-hit.is-active');
    const br = body.getBoundingClientRect();
    const ar = act ? act.getBoundingClientRect() : null;
    return {
      foot: footText(),
      mounted: document.querySelectorAll('.log-row').length,
      hasActive: Boolean(act),
      insidePanel: ar ? ar.top >= br.top - 2 && ar.bottom <= br.bottom + 2 : false,
      pos: ar ? Math.round(ar.top - br.top) : null,
    };
  });
  console.log('  ', JSON.stringify(jump));
  check('连点 40 次后停在第 41 处', /41\/240/.test(jump.foot || ''), jump.foot);
  check(
    '目标行原本没挂载，跳转依然到位（active 高亮在面板内）',
    jump.hasActive && jump.insidePanel && jump.mounted <= 60,
    [jump.hasActive, jump.insidePanel, jump.mounted, jump.pos],
  );

  check('虚拟容器这一趟无 pageerror', errors.length === 0, errors.slice(0, 3));

  /* 绝对定位最容易悄悄弄坏的是**视觉**：四列没对齐、行间线错位、WARN 色栏跑偏。
     数字断言看不出来，所以这两张图是探针自己产的固定证据（顶部 / 中段各一张）。 */
  const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots/running');
  fs.mkdirSync(OUT, { recursive: true });
  await page.evaluate(() => {
    document.querySelector('.log-body').scrollTop = 0;
  });
  await page.waitForTimeout(250);
  await page.locator('.log').screenshot({ path: path.join(OUT, 'virtual-top.png') });
  await page.evaluate(async () => {
    const b = document.querySelector('.log-body');
    b.scrollTop = Math.round(b.scrollHeight * 0.45);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
  await page.waitForTimeout(250);
  await page.locator('.log').screenshot({ path: path.join(OUT, 'virtual-mid.png') });
  console.log('  ✓ 截图 → virtual-top / virtual-mid');

  await ctx.close();
}

/* --------------------------- D 术语释义（页③） --------------------------- */

/** 录屏报告 UX-1：专业术语无释义。
 *  逐条钉住「卡片上有 ⓘ、表头有原生 title、释义不是空壳」—— 不判内容对错，
 *  内容对不对由人读（他给的判据表口径）。 */
async function passJargon(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 体检弹层那句「降级」定义只在 status=degraded 时出现，而 fixture 默认回 healthy
     （它自己就带一项 degraded 检查，本来就是个自相矛盾的样本）。这里按后注册优先，
     把整份 health 换成 degraded 那一档，才测得到我们要测的那句话。 */
  await page.route('**/api/health', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'degraded',
        version: '0.9.3',
        uptime_seconds: 8412,
        checks: {
          api: { status: 'ok', detail: 'ok' },
          rag: { status: 'degraded', detail: 'sqlite-vec 未安装，退回全文检索' },
        },
      }),
    }),
  );

  console.log('\n== D 术语释义 · light ==');
  await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const g = await page.evaluate(() => {
    /** 释义全文：F-4 之后在 `.metric-info` 按钮里那句 `.sr-only` 上，
     *  不再是卡片上的原生 `title`（那个会和 Tooltip 叠两层）。见 readMetricParity 里同一段注释。 */
    const glossOf = (m) => {
      const btn = m.querySelector('.metric-info');
      const span = btn && btn.querySelector('.sr-only');
      return (span && span.textContent) || m.getAttribute('title') || '';
    };
    const tiles = Array.from(document.querySelectorAll('.metric')).map((m) => ({
      label: (m.querySelector('.metric-label span:not(.anticon)') || {}).textContent?.trim() || '',
      info: !!m.querySelector('.metric-label .anticon-info-circle'),
      gloss: glossOf(m).length,
    }));
    const ths = Array.from(document.querySelectorAll('thead th')).map((t) => ({
      text: t.textContent.trim(),
      gloss: (t.getAttribute('title') || '').length,
    }));
    return { tiles, ths, tables: document.querySelectorAll('table').length };
  });
  console.log('   表格数：', g.tables, ' 卡片数：', g.tiles.length, ' 表头数：', g.ths.length);

  for (const name of ['参考组 Top-3', 'G2 门槛', 'G2 判定', '可计分题数']) {
    const t = g.tiles.find((x) => x.label === name);
    check(`评测页「${name}」卡有 ⓘ + 释义`, !!t && t.info === true && t.gloss > 20, t);
  }
  /* 表头这九列是页③最容易被读错的东西；释义挂在 <th> 的原生 title 上，不占版面。 */
  for (const name of ['Top-1', 'Top-3', 'Hit@5', 'MRR', 'nDCG@k', 'MRR@k', '命中率', 'ΔnDCG（绝对）', '相对基线']) {
    const h = g.ths.find((x) => x.text === name);
    check(`表头「${name}」有原生 title 释义`, !!h && h.gloss > 20, h);
  }
  /* 降级运行那颗胶囊：点开的弹层里要有一句定义，不能只有绿点黄点。 */
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('.status-pill').click();
  await page.waitForTimeout(400);
  const pill = await page.evaluate(() => {
    const pop = document.querySelector('.health-pop');
    const note = pop && pop.querySelector('.health-pop-note');
    const rows = pop ? Array.from(pop.querySelectorAll('.health-row')).length : 0;
    /* 弹层内边是透明的，真正托着字的是 .ant-popover-inner —— 一路往上找到第一层不透明的底。
       对比度必须量在**这块底**上，量在 --bg-surface 上等于没测（口径同 contrast.cjs）。 */
    const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
    const opaqueBg = (el) => {
      let n = el;
      while (n) {
        const cs = getComputedStyle(n);
        const v = nums(cs.backgroundColor);
        if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) return v.slice(0, 3);
        n = n.parentElement;
      }
      return [255, 255, 255];
    };
    const cr = (fgStr, bg) => {
      const lin = (x) => {
        const c = x / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const f = nums(fgStr);
      const A = f.length > 3 ? f[3] : 1;
      const fg = f.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
      const l1 = lum(fg);
      const l2 = lum(bg);
      return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    };
    return {
      open: !!pop && getComputedStyle(pop.closest('.ant-popover') || pop).display !== 'none',
      rows,
      note: note ? note.textContent.trim() : '',
      noteContrast: note ? cr(getComputedStyle(note).color, opaqueBg(note)) : 0,
      /* 弹层里最浅的那一档（head 用的是 --text-3）—— 它不达标就说明整块弹层没校过 */
      headContrast: pop ? cr(getComputedStyle(pop.querySelector('.health-pop-head')).color, opaqueBg(pop)) : 0,
    };
  });
  console.log('   弹层实测对比度：', JSON.stringify(pill).slice(0, 160));
  check('体检弹层打得开、逐项都在', pill.open === true && pill.rows >= 2, pill);
  check(
    '「降级」有一句定义（胶囊只有 8 个字符的位置，定义放弹层里）',
    /降级/.test(pill.note) && pill.note.length > 20,
    pill.note,
  );
  check(
    '那句定义在弹层实际底色上 ≥4.5（浅底 --text-3 只有 4.2，所以给它 --text-2）',
    pill.noteContrast >= 4.5,
    pill.noteContrast,
  );
  check('弹层里最浅的一档（head）也不低于 3:1', pill.headContrast >= 3, pill.headContrast);
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

/* --------------------------- E 引用列表折叠与真名 --------------------------- */

/** 一次检索 3 条命中的轨迹；第一条 knowledge_search 故意给成后端真实会返回的
 *  **错误串**（sqlite-vec 没装时 observation 就是它），用来验「认不出 ⇒ 一行 + 全 —」。 */
function citedTrace(n) {
  const items = [];
  let seq = 0;
  const push = (over) => {
    seq += 1;
    items.push({
      event_seq: seq,
      step: (seq % 9) + 1,
      sub_step: null,
      event_type: 'tool',
      role: 'executor',
      node: 'executor',
      thought: '查一下原文。',
      tool_name: 'knowledge_search',
      arguments: { query: 'PoE', top_k: 5, fusion: 'rrf' },
      latency_ms: 300,
      tokens_in: 100,
      tokens_out: 20,
      cost: 0.0002,
      status: 'done',
      error_code: null,
      error_message: null,
      created_at: new Date(Date.now() - (n - seq) * 1000).toISOString(),
      ...over,
    });
  };
  push({
    observation:
      "KnowledgeSearchError: 检索失败：[retrieval] 知识库服务不可用；" +
      "[storage] sqlite-vec 未安装，无法使用 sqlite-vec 后端：No module named 'sqlite_vec'",
  });
  for (let i = 0; i < n; i += 1) {
    push({
      observation: [
        '共命中 3 条相关片段：',
        `【1】anfangjiankong.md · chunk ${i}1（字符 0-512）｜相关度 0.83（BM25 0.71 / 向量 0.92）`,
        `第 3 章：PoE 单端口最大输出功率 30W。（第 ${i} 次检索）`,
        `【2】anfangjiankong.md · chunk ${i}2（字符 900-1400）｜相关度 0.71（BM25 0.66 / 向量 0.74）`,
        '第 5 章：整机功耗 = 设备数 × 单路功耗 ÷ 供电效率。',
        `【3】shengchanfangkong.md · chunk ${i}3（字符 300-880）｜相关度 0.52（BM25 0.55 / 向量 0.49）`,
        '监控中心供电回路应独立敷设。',
      ].join('\n'),
    });
  }
  return {
    ...traceBody,
    items,
    total: items.length,
    has_more: false,
    next_after_seq: items.length,
    events_available: true,
    unavailable_reason: null,
  };
}

/** 折叠行为 + 「文档名不再造假」。往返耗时在 logperf.cjs 那边量，
 *  单次展开的代价（两个规模的负面对照）在下面的 passExpandCost，这里只管对错。
 *
 *  fixture 给到 181 行（60 次检索 × 3 条命中 + 1 条认不出的）：够越过 10 行的折叠线，
 *  又能让「最后一条检索的三个命中都在」这种断言有意义。 */
async function passCitations(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(citedTrace(60)),
    }),
  );

  const TOTAL = 181;
  console.log('\n== E 引用列表折叠与真名 · light ==');
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(700);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(500);

  const read = () =>
    page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('.code-more')).find(
        (b) => /展开全部|收起/.test(b.textContent || ''),
      );
      const rows = Array.from(document.querySelectorAll('.list-row')).map((r) => ({
        id: (r.querySelector('.chip') || {}).textContent?.trim() || '',
        doc: (r.querySelector('b') || {}).textContent?.trim() || '',
        score: (r.querySelector('.t3') || {}).textContent?.trim() || '',
      }));
      const label = Array.from(document.querySelectorAll('.sec-label')).find((s) =>
        /引用来源/.test(s.textContent || ''),
      );
      return {
        rows,
        标题: label ? label.textContent.trim() : '',
        按钮: btn ? btn.textContent.trim() : '',
        展开态: btn ? btn.getAttribute('aria-expanded') : null,
        元素: document.querySelectorAll('*').length,
        有假名: document.body.innerText.includes('知识库检索结果'),
      };
    });

  const folded = await read();
  check('折叠态只铺 10 行', folded.rows.length === 10, folded.rows.length);
  check('标题报的是总数，不是可见数', folded.标题.includes(String(TOTAL)), folded.标题);
  check('按钮说清了当前显示多少', folded.按钮 === `展开全部 ${TOTAL} 条（当前显示前 10 条）`, folded.按钮);
  check('aria-expanded=false', folded.展开态 === 'false', folded.展开态);
  check(
    '假文档名彻底消失（上一版每行都写死「知识库检索结果」）',
    folded.有假名 === false,
    folded.有假名,
  );
  check(
    '认不出的那条排第一：文档名与相关度都是 —，原文整段仍然给出',
    folded.rows[0].doc === '—' && /相关度 —/.test(folded.rows[0].score),
    folded.rows[0],
  );
  check(
    '认得出的那条：文档名来自引用行、相关度是融合分',
    folded.rows[1].doc === 'anfangjiankong.md' && /相关度 0\.83/.test(folded.rows[1].score),
    folded.rows[1],
  );
  check(
    '溯源 id 是 #事件序号·【命中序号】（能回到轨迹回放页对上号）',
    /^#\d+·【\d+】$/.test(folded.rows[1].id),
    folded.rows[1].id,
  );
  const foldedIds = new Set(folded.rows.map((r) => r.id)).size;
  check('10 行的 id 互不相同（memo + key 的前提）', foldedIds === 10, foldedIds);

  /* 截图要的是整块引用区（标题 + 行 + 按钮），不是单个标题 */
  const block = page.locator('.sec-label', { hasText: '引用来源' }).locator('..');
  await block.screenshot({ path: path.join(OUT, 'citations-folded.png') });

  /* 折叠态常驻元素数。这条口径的落点是「与总行数解耦」——
     passExpandCost 会拿另一个总量（4,800 行）的 fixture 再量一次，两次的数必须相等。 */
  check('折叠态常驻元素数在预算内（≤1,200）', folded.元素 <= 1200, folded.元素);
  FOLDED_ELEMENTS.push({ 总行数: TOTAL, 元素: folded.元素 });

  await page.locator('.code-more').last().click();
  await page.waitForTimeout(400);
  const open = await read();
  check('展开后 181 行全在', open.rows.length === TOTAL, open.rows.length);
  check('展开后按钮变「收起」', open.按钮 === '收起', open.按钮);
  check('aria-expanded=true', open.展开态 === 'true', open.展开态);
  const uniq = new Set(open.rows.map((r) => r.id)).size;
  check('展开态行 id 互不相同', uniq === TOTAL, { 去重后: uniq, 行数: TOTAL });
  check(
    '最后一条检索的三个命中都在（折叠没把数据弄丢）',
    open.rows.filter((r) => /shengchanfangkong/.test(r.doc)).length === 60,
    open.rows.filter((r) => /shengchanfangkong/.test(r.doc)).length,
  );
  check('展开态元素数比折叠态多（181 行确实挂上了）', open.元素 > folded.元素, {
    折叠: folded.元素,
    展开: open.元素,
  });
  await block.screenshot({ path: path.join(OUT, 'citations-expanded.png') });

  await page.locator('.code-more').last().click();
  await page.waitForTimeout(400);
  const back = await read();
  check('再点「收起」回到 10 行', back.rows.length === 10, back.rows.length);
  check('收起后按钮文案复位', back.按钮 === folded.按钮, back.按钮);
  check('收起后 aria-expanded=false', back.展开态 === 'false', back.展开态);
  check(
    '收起后元素数与折叠态一致（展开没在页面上留残渣）',
    back.元素 === folded.元素,
    { 折叠: folded.元素, 收起后: back.元素 },
  );
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

/** 负面对照：展开**一次**的代价随引用行数怎么涨。
 *
 *  为什么要有这一趟：折叠把常驻 DOM 钉死在 10 行之后，「切页签 57ms」就不再暴露任何
 *  信息了 —— 代价没消失，只是被推到了点展开那一下。只有「折叠很快」这一条证据的话，
 *  没人会注意到 4,800 行那一下是 1.8 秒。所以这里量两个规模，同一条代码路径、
 *  同一支探针，差别只有行数：
 *    · 100 行（真实任务的常见上限：5~20 条 × 几道子问题）⇒ 硬门槛 <200ms；
 *    · 4,800 行（5,000 事件全是检索的极端 fixture）⇒ 只报数，按已知限制写进 README。
 */
async function passExpandCost(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));

  const cases = [
    { 名: '100 行', n: 33, 门槛ms: 200 },
    { 名: '4,800 行', n: 1600, 门槛ms: null },
  ];

  console.log('\n== F 单次展开代价 · 负面对照 · light ==');
  for (const c of cases) {
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push(e.message));
    await installMocks(page);
    await page.route('**/api/tasks/*/trace*', (r) =>
      r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(citedTrace(c.n)),
      }),
    );
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await page.locator('.tsk-item').first().click();
    await page.waitForTimeout(700);
    await page.getByRole('tab', { name: '运行结果' }).click();
    await page.waitForTimeout(600);

    const m = await page.evaluate(async () => {
      const btn = () =>
        Array.from(document.querySelectorAll('.code-more')).find((b) =>
          /展开全部|收起/.test(b.textContent || ''),
        );
      const count = () => ({
        行: document.querySelectorAll('.list-row').length,
        元素: document.querySelectorAll('*').length,
      });
      const raf2 = () =>
        new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
      const before = count();
      /* 底噪单独量：raf2 自己就要等帧。实测两个规模下都是 9ms 上下，
         所以「含帧」这个数里真正该看的是展开本身，不是等待开销。 */
      const t0 = performance.now();
      await raf2();
      const frameFloor = +(performance.now() - t0).toFixed(1);
      const t1 = performance.now();
      btn().click();
      /* sync 段实测只有 0.4~0.6ms —— 别把它读成「React 的渲染很便宜」：
         React 18 把这批更新排进了帧前的调度里，click 的同步栈里压根没干活。
         真正的代价全在 totalMs（= 脚本 + 布局 + 绘制，从点击到画完）里，
         这也是这一趟为什么用「含帧」当门槛数、只把 sync 当参考打印出来。 */
      const syncMs = +(performance.now() - t1).toFixed(1);
      await raf2();
      const totalMs = +(performance.now() - t1).toFixed(1);
      const after = count();
      const t2 = performance.now();
      btn().click();
      const collapseSync = +(performance.now() - t2).toFixed(1);
      await raf2();
      return {
        before,
        after,
        frameFloor,
        syncMs,
        totalMs,
        collapseSync,
        collapseMs: +(performance.now() - t2).toFixed(1),
      };
    });

    console.log(
      `   ${c.名}（共 ${c.n * 3 + 1} 条引用）：折叠 ${m.before.行} 行 / ${m.before.元素} 元素` +
        ` → 展开 ${m.after.行} 行 / ${m.after.元素} 元素` +
        ` · 单次展开 同步 ${m.syncMs}ms / 含帧 ${m.totalMs}ms（raf2 底噪 ${m.frameFloor}ms）` +
        ` · 收起 同步 ${m.collapseSync}ms / 含帧 ${m.collapseMs}ms`,
    );
    check(`${c.名}：折叠态就是 10 行`, m.before.行 === 10, m.before.行);
    check(`${c.名}：展开后行数与 fixture 对得上`, m.after.行 === c.n * 3 + 1, m.after.行);
    FOLDED_ELEMENTS.push({ 总行数: m.after.行, 元素: m.before.元素 });
    if (c.门槛ms !== null) {
      check(
        `${c.名}：单次展开 <${c.门槛ms}ms（真实任务规模的门槛，也是「1.8s 只是长尾」的正证）`,
        m.totalMs < c.门槛ms,
        { 含帧ms: m.totalMs, 同步ms: m.syncMs, 底噪ms: m.frameFloor },
      );
    }
    check(`${c.名}：这一趟没有 pageerror`, errs.length === 0, errs.slice(0, 2));
    await page.close();
  }

  /* 「与总行数解耦」的正证：100 行与 4,800 行两档的**折叠态**常驻元素数必须一模一样。
     要是有人把折叠改回「全部挂上、CSS 藏起来」，这里就会分叉。 */
  const nums = FOLDED_ELEMENTS.map((x) => x.元素);
  check(
    `折叠态常驻元素数与引用总数解耦（${FOLDED_ELEMENTS.map((x) => `${x.总行数}行→${x.元素}元素`).join(' / ')}）`,
    new Set(nums).size === 1,
    nums,
  );
  await ctx.close();
}

/** 模型读数条（composer 里那一行「模型 xxx」）的验收。
 *
 *  这一条链上一版是断的：Select 的选项躺在 mock 文件里、值既不进 POST body、
 *  后端也没有对应字段。现在数据源换成 ``GET /models``，于是验收要盯四件事：
 *    ① 文案跟着**响应**变（三份 fixture 都是真跑 ``get_models()`` dump 出来的形态）；
 *    ② 兜底价不许被说成官方价；
 *    ③ 拉不到 ⇒ 整条不渲染（绝不回落到写死的清单）；
 *    ④ 它不再假装是控件：DOM 是 span、cursor 是 default、composer 里没有 .ant-select，
 *       而 POST 请求体里也确实没有 model 字段。
 *  ⑤ 顺带：它是全站少数「只靠 hover 就读不到」的信息位，所以给键盘留了 tab 停靠点。
 */
async function passModelReadout(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);

  const variants = [
    { 名: '两档同一模型', body: modelsBody, 胶囊: '模型 deepseek-flash', 来路: '表内价' },
    {
      名: '两档不同模型',
      body: modelsBodyTwoTiers,
      胶囊: '模型 deepseek-v4-pro +deepseek-flash',
      来路: '表内价',
    },
    {
      名: '强模型不在价表里',
      body: modelsBodyFallback,
      胶囊: '模型 某没配过价的模型 +deepseek-flash',
      来路: '兜底价',
    },
  ];

  console.log(`\n== G 模型读数条 · ${label} ==`);
  for (const v of variants) {
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await installMocks(page);
    /* 后注册的 route 吃掉 installMocks 那份默认响应 —— 与 trace 那条 route 同一手法 */
    await page.route('**/api/models', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(v.body) }),
    );
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);

    const got = await page.evaluate(() => {
      const el = document.querySelector('.cp-model-ro');
      if (!el) return { present: false };
      const cs = getComputedStyle(el);
      const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
      /* 对比度要量在**真正托着它的那块底**上：一路往上找第一层不透明背景
         （口径同 D 趟的弹层，量在 --bg-surface 上等于没测）。 */
      const opaqueBg = (node) => {
        let n = node;
        while (n) {
          const v = nums(getComputedStyle(n).backgroundColor);
          if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) return v.slice(0, 3);
          n = n.parentElement;
        }
        return null;
      };
      const cr = (fgStr, bg) => {
        const lin = (x) => {
          const c = x / 255;
          return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
        };
        const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
        const f = nums(fgStr);
        const A = f.length > 3 ? f[3] : 1;
        const fg = f.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
        const l1 = lum(fg);
        const l2 = lum(bg);
        return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
      };
      const bg = opaqueBg(el);
      return {
        present: true,
        text: el.textContent.trim(),
        tag: el.tagName,
        cursor: cs.cursor,
        borderWidth: cs.borderTopWidth,
        tabIndex: el.getAttribute('tabindex'),
        inComposer: Boolean(el.closest('.composer')),
        bg: bg ? `rgb(${bg.join(', ')})` : null,
        contrast: bg ? cr(cs.color, bg) : 0,
        selectsInComposer: document.querySelectorAll('.composer .ant-select').length,
      };
    });

    check(`${v.名}：胶囊文案 = 响应里那两个 id（不是前端自带的一份清单）`, got.text === v.胶囊, got.text);
    check(`${v.名}：它是读数不是控件（span + cursor: default + 无描边）`,
      got.tag === 'SPAN' && got.cursor === 'default' && got.borderWidth === '0px', [
        got.tag,
        got.cursor,
        got.borderWidth,
      ]);
    check(`${v.名}：composer 里已经没有 .ant-select（那颗假下拉真被拿掉了）`,
      got.selectsInComposer === 0, got.selectsInComposer);
    check(`${v.名}：位置仍在 composer 底栏内`, got.inComposer === true, got.inComposer);
    check(`${v.名}：字色在实际底上 ≥4.5（${got.bg}）`, got.contrast >= 4.5, got.contrast);

    /* 明细：hover 展开 Tooltip，读**渲染出来的**那几行，不读组件 props */
    await page.hover('.cp-model-ro');
    await page.waitForTimeout(500);
    const tip = await page.evaluate(() => {
      const box = document.querySelector('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner');
      if (!box) return { open: false, lines: [] };
      return {
        open: true,
        lines: Array.from(box.querySelectorAll('div')).map((d) => d.textContent.trim()),
      };
    });
    const joined = tip.lines.join('\n');
    check(`${v.名}：悬停有明细`, tip.open === true && tip.lines.length >= 2, tip.lines.length);
    check(`${v.名}：每个模型一行且标了来路「${v.来路}」`,
      tip.lines.filter((l) => /｜/.test(l)).length === v.body.total && joined.includes(v.来路),
      tip.lines);
    check(`${v.名}：单位写在字段里（每 100 万 token），金额两位小数`,
      /每 100 万 token/.test(joined) && /¥\d+\.\d{2} 进 \/ ¥\d+\.\d{2} 出/.test(joined), joined.slice(0, 120));
    check(`${v.名}：五个角色的归属都在明细里（谁用哪一档一眼读得出）`,
      /规划/.test(joined) && /执行/.test(joined) && /评审/.test(joined) && /裁判/.test(joined) &&
        /抽取/.test(joined),
      joined);
    /* 「强模型 / 快模型」这两个词只在两档确实是两个模型时出现；合并成一条时改说
       「两档同一个模型」—— 写「强模型」会让人以为还有个快模型被藏起来了。
       ⚠️ 比的是 joined（整段明细）不是第一行：第一行永远是强模型那档。 */
    check(
      `${v.名}：${
        v.body.total === 2
          ? '两档不同 ⇒ 强/快两个档位名都在，不说"同一个模型"'
          : '两档同一 ⇒ 说"两档同一个模型"，不出现强/快档位名'
      }`,
      v.body.total === 2
        ? /强模型/.test(joined) && /快模型/.test(joined) && !/两档同一个模型/.test(joined)
        : /两档同一个模型/.test(joined) && !/强模型/.test(joined) && !/快模型/.test(joined),
      tip.lines[0],
    );
    check(`${v.名}：峰谷口径用的是服务端原话（前端不另写一份）`,
      joined.includes(v.body.pricing_basis) && joined.includes(`×${v.body.off_peak_multiplier}`),
      joined.slice(-140));
    check(`${v.名}：末行说清「去哪改 + 影响什么 + 会不会一直有效」（旧文案"不在页面里切换"已成套话）`,
      /模型设置/.test(joined) && /之后新建的任务/.test(joined) && /回落到 \.env/.test(joined)
        && !/不在页面里切换/.test(joined),
      joined.slice(-90));
    check(`${v.名}：这一趟没有 pageerror`, errors.length === 0, errors.slice(0, 2));

    /* 键盘这条路径：只靠 hover 的明细，Tab 过去也得能读到。
       tabIndex=0 就是"在 Tab 序里"（DOM 层面的事实），focus 后弹层真的出现才算可达。 */
    check(`${v.名}：读数在 Tab 序里（tabindex=0）`, got.tabIndex === '0', got.tabIndex);
    await page.locator('.cp-model-ro').focus();
    await page.waitForTimeout(500);
    const kb = await page.evaluate(() => ({
      focused: document.activeElement === document.querySelector('.cp-model-ro'),
      tipOpen: Boolean(document.querySelector('.ant-tooltip:not(.ant-tooltip-hidden)')),
    }));
    check(`${v.名}：键盘聚焦在同一条读数上、明细弹得出来`,
      kb.focused === true && kb.tipOpen === true, kb);
    await page.close();
  }

  /* ③ 后端拉不到 ⇒ 整条不渲染。这条是"绝不回落到写死清单"的唯一机器证据：
       如果哪天有人加个 fallback 常量，胶囊会照样出现、文案还是 deepseek-flash。 */
  const failPage = await ctx.newPage();
  const failErrors = [];
  const posts = [];
  failPage.on('pageerror', (e) => failErrors.push(e.message));
  failPage.on('request', (rq) => {
    if (rq.method() === 'POST' && /\/api\/tasks(\?|$)/.test(rq.url())) {
      posts.push(rq.postData() || '');
    }
  });
  await installMocks(failPage);
  await failPage.route('**/api/models', (r) =>
    r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }),
  );
  await failPage.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await failPage.waitForTimeout(700);
  check('后端 500 时整条不渲染（宁可少一行信息，也不回落到写死的清单）',
    (await failPage.locator('.cp-model-ro').count()) === 0,
    await failPage.locator('.cp-model-ro').count());
  check('拉不到注册表不该把页面崩掉', failErrors.length === 0, failErrors.slice(0, 2));

  /* ④ 请求体里确实没有 model —— 这是「假下拉」与「真控件」的唯一分界 */
  await failPage.locator('.composer-input').fill('泵站日均能耗怎么折算？');
  await failPage.locator('.cp-submit').click();
  await failPage.waitForTimeout(800);
  let body = {};
  try {
    body = JSON.parse(posts[0] || '{}');
  } catch {
    body = { _parseError: posts[0] };
  }
  check('POST /tasks 发出去了（否则"没有 model 字段"是句空话）', posts.length === 1, posts.length);
  check('请求体里没有 model 字段（前端不再假装能选模型）',
    Object.prototype.hasOwnProperty.call(body, 'model') === false, Object.keys(body));
  await failPage.close();
  await ctx.close();
}

/** 运行结果页的宽屏排版（2560 / 1280 / 768 三档）。
 *
 *  为什么单独一趟：`.result-wrap` 是**正文限宽**（`--measure` 820px，防长行找不回行首）
 *  和**指标卡 + 摘要**共同的外层 —— 它自己靠左贴着 `.app-content`（1560 居中块）的左边缘时，
 *  宽屏上右侧会空出 ~740px，整页重心偏左。限宽是对的，缺的是把它居中。
 *  所以这趟钉四条不变量：① 外层左右留白对称；② 卡与正文共用同一条左边缘
 *  （居中不能变成"每块各居各的中"）；③ 正文行宽仍 ≤ 820（可读性红线）；
 *  ④ 任何一档都不许出现横向滚动。
 */
async function passResultCenter(browser, scheme, label) {
  const cases = [
    { 宽: 2560, 高: 1400, 该有空档: true },
    { 宽: 1280, 高: 900, 该有空档: false },
    { 宽: 768, 高: 900, 该有空档: false },
  ];
  console.log(`\n== H 结果页宽屏排版 · ${label} ==`);

  for (const c of cases) {
    const ctx = await browser.newContext({
      viewport: { width: c.宽, height: c.高 },
      colorScheme: scheme,
      locale: 'zh-CN',
    });
    await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await installMocks(page);
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    /* ≤1024 时任务栏换成抽屉（默认不开），DOM 里条目一直在 —— 直接派发 click 拿详情，
       不去点抽屉按钮：这一趟测的是结果页排版，不是抽屉交互（那个 capture2 在管）。 */
    await page.evaluate(() => document.querySelector('.tsk-item').click());
    await page.waitForTimeout(700);
    await page.getByRole('tab', { name: '运行结果' }).click();
    await page.waitForTimeout(700);

    const g = await page.evaluate(() => {
      const r = (el) => {
        const b = el.getBoundingClientRect();
        return { left: +b.left.toFixed(1), right: +b.right.toFixed(1), width: +b.width.toFixed(1) };
      };
      const wrap = document.querySelector('.result-wrap');
      const host = wrap.parentElement;
      const grid = document.querySelector('.metric-grid--head');
      const answer = document.querySelector('.answer');
      const callout = document.querySelector('.summary-callout');
      const de = document.documentElement;
      const wr = r(wrap);
      const hr = r(host);
      return {
        视口: de.clientWidth,
        外层: hr,
        内容块: wr,
        左留白: +(wr.left - hr.left).toFixed(1),
        右留白: +(hr.right - wr.right).toFixed(1),
        卡: grid ? r(grid) : null,
        正文: answer ? r(answer) : null,
        摘要: callout ? r(callout) : null,
        正文限宽: getComputedStyle(wrap).maxWidth,
        横向滚动: de.scrollWidth - de.clientWidth,
      };
    });
    console.log(
      `   ${c.宽}px：外层 ${g.外层.width} / 内容块 ${g.内容块.width}（max-width ${g.正文限宽}）` +
        ` · 左留白 ${g.左留白} 右留白 ${g.右留白} · 横向溢出 ${g.横向滚动}px`,
    );

    const tag = `${c.宽}px`;
    if (c.该有空档) {
      /* 居中这条断言最容易被"两边都是 0"蒙过去 —— 先证明留白是真的存在。 */
      check(`${tag}：留白是真的（左右各 ≥20px，不是 0/0 蒙对）`, g.左留白 >= 20 && g.右留白 >= 20, [
        g.左留白,
        g.右留白,
      ]);
    }
    check(`${tag}：内容块左右留白对称（|差| ≤ 2）`, Math.abs(g.左留白 - g.右留白) <= 2, [g.左留白, g.右留白]);
    check(`${tag}：指标卡与正文同一条左边缘（|差| ≤ 1）`, g.卡 && g.正文 && Math.abs(g.卡.left - g.正文.left) <= 1, [
      g.卡 && g.卡.left,
      g.正文 && g.正文.left,
    ]);
    check(`${tag}：摘要条也挂同一条左边缘`, g.摘要 && Math.abs(g.摘要.left - g.正文.left) <= 1, [
      g.摘要 && g.摘要.left,
      g.正文 && g.正文.left,
    ]);
    check(`${tag}：正文行宽 ≤ 820（可读性红线，居中不许顺手放宽）`, g.正文.width <= 821, g.正文.width);
    if (c.该有空档) {
      check(`${tag}：指标卡确实吃到 1100（抬外层生效，不是只加了居中）`, g.卡.width >= 1000, g.卡.width);
      check(`${tag}：正文仍被压在 820（抬外层没把汉字行长一起放开）`, g.正文.width === 820, g.正文.width);
    }
    check(`${tag}：无横向滚动`, g.横向滚动 <= 0, g.横向滚动);
    check(`${tag}：这一趟没有 pageerror`, errors.length === 0, errors.slice(0, 2));

    if (c.宽 === 2560) {
      fs.mkdirSync(OUT, { recursive: true });
      await page.screenshot({ path: path.join(OUT, `result-${label}-2560.png`) });
      console.log(`  ✓ 截图 → result-${label}-2560`);
    }
    await ctx.close();
  }
}

/** 结果页五处打磨的验收（1440 一档就够：这些是**排版 token**，与视口宽度无关）。
 *
 *  每条都读**计算样式**而不是源码字面量：CSS 里写了不等于挂上了（被更高优先级
 *  覆盖、或类名打错，只有计算样式会诚实回答）。
 *  答案 fixture 是刻意拼出来的，覆盖：裸序号行 / 含数字的加粗 / 不含数字的加粗 /
 *  两段正文 / 一个列表 —— 少一种形态就有一条断言测不到。 */
async function passResultPolish(browser, scheme, label) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  // 空态要真的空：citedTrace(0) 那条「认不出的检索」仍会产出 1 行「—」占位引用，
  // 量不到空态分支 —— 零事件才是 citations.length === 0。
  // ⚠️ trace 路由必须单独注册：glob 里的星号不跨斜杠，下面那条详情路由盖不到 trace。
  const emptyTrace = {
    ...traceBody,
    items: [],
    total: 0,
    has_more: false,
    next_after_seq: 0,
    events_available: true,
    unavailable_reason: null,
  };
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(emptyTrace) }),
  );
  /* fixture 覆盖五种形态，少一种就有一条断言测不到：
     裸序号行 / markdown 二级 / **含数字的加粗** / **不含数字的加粗** /
     两个相邻段落（段间距 18px 只有"前一个邻居是 p"时才量得到）/ 列表 */
  const ANSWER = [
    '一、门禁开门延时默认几秒？',
    '行业常见出厂默认值为 **3-5 秒**，多数控制器预设为 5 秒。',
    '',
    '## 二级：预设值差异',
    '少数型号支持 0-30 秒。',
    '',
    /* 这两段之间必须**空一行**：同一块里的两行会被 hardBreaks 并成一个 <p> 里的两行，
       那样「段与段 18px」这条根本量不到（第一版就是栽在这儿，报的是 null 不是 8px）。 */
    '这是独立第二段，前一个邻居就是 <p>，用来量段落之间的 18px。',
    '',
    '二、用计算器算 12+30',
    '**重要提示**：12 + 30 = **42**。',
    '',
    '- 列表项一',
    '- 列表项二',
  ].join('\n');
  // 这条只管详情：glob 的星号不跨斜杠，trace 由上面那条单独接管
  // ⚠️ 用 let：下面"认不出结论段"那一档要把同一份详情换成一句话答案，
  //    重新 route 同一个 glob 不如直接改这份闭包里的变量（少一层"后注册优先"的心智负担）。
  let answerNow = ANSWER;
  await page.route('**/api/tasks/*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...detail, final_answer: answerNow }),
    }));

  console.log(`\n== I 结果页排版打磨 · ${label} ==`);
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(800);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(800);

  const m = await page.evaluate(() => {
    const cs = (el, prop) => (el ? getComputedStyle(el)[prop] : null);
    const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
    const opaqueBg = (el) => {
      let n = el;
      while (n) {
        const v = nums(getComputedStyle(n).backgroundColor);
        if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) return v.slice(0, 3);
        n = n.parentElement;
      }
      return [255, 255, 255];
    };
    const cr = (fgStr, bg) => {
      const lin = (x) => {
        const c = x / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const f = nums(fgStr);
      const A = f.length > 3 ? f[3] : 1;
      const fg = f.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
      const l1 = lum(fg);
      const l2 = lum(bg);
      return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    };
    /* 自定义属性不走 CSSStyleDeclaration 的方括号访问；而且 token 是十六进制，
       计算样式给的是 rgb() —— 直接比字符串永远不等。造一个临时元素让浏览器换算。 */
    const probeEl = document.createElement('span');
    probeEl.style.color = 'var(--primary)';
    document.body.appendChild(probeEl);
    const primaryRgb = getComputedStyle(probeEl).color;
    probeEl.remove();
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const heads = qa('.answer .ast-h--1');
    const h2 = q('.answer .ast-h--2');
    const meta = q('.result-meta');
    const tiles = qa('.metric-grid--head .metric');
    const grid = q('.metric-grid--head');
    const empty = q('.cite-empty');
    const labelEl = q('.sec-label--answer');
    const strongs = qa('.answer strong');
    const ps = qa('.answer > p');
    const ul = q('.answer > ul');
    /* 段落间距要取「真正跟在另一段后面的那段」：标题后面那段吃的是 .ast-h + * 的 8px，
       拿它量 18px 会把"规则没生效"和"取错了元素"混成一件事（实测第一版就取错了）。 */
    const second = ps.find((p) => p.previousElementSibling?.matches('p'));
    /* 空壳容器普查。判据故意写成通用的，不点名 .summary-callout：
       **「自己画了底色 + 整块读不出一个字 + 没被 aria-hidden」就算一个空壳**。
       起因是 2026-09-25 用户实测：摘要条是"容器常驻、里面那行条件渲染"，
       `pickConclusion` 认不出结论段（1+1 这类一句话答案全都是）时就画出一条 23px 的空紫条。
       只查一条类名换个写法就漏，所以按形状查。
       排除项也点名，免得变成静默盲区：带 svg 的图标控件（复制按钮这种"本来就没字"）、
       以及零高的元素不算。 */
    const shells = qa('.result-wrap *')
      .filter((e) => {
        if ((e.textContent || '').trim() !== '') return false;
        if (e.querySelector('svg') || e.closest('[aria-hidden="true"]')) return false;
        /* 带标签的**图形**豁免（2026-09-26 加，成本面板的分段条撞出来的）：
           `.spark` 与它那些色块 span 本来就不该有字 —— 说"这是什么"的活儿由 role="img"
           上那条 aria-label 干（AA 趟按内容断言它非空且逐段点名，见那里的 4d）。
           ⚠️ 只豁免**真带标签**的那一类：没标签的图形照样记名，不许借这条开静默盲区。 */
        const graphic = e.closest('[role="img"]');
        if (graphic && (graphic.getAttribute('aria-label') || '').trim()) return false;
        const r = e.getBoundingClientRect();
        if (r.height <= 0) return false;
        const v = nums(getComputedStyle(e).backgroundColor);
        return v.length >= 3 && (v.length < 4 || v[3] > 0.05);
      })
      .map((e) => `${String(e.className || e.tagName).split(' ')[0]}@${Math.round(e.getBoundingClientRect().height)}px`);
    const callout = q('.summary-callout');
    return {
      摘要条文本: callout ? (callout.innerText || '').replace(/\s+/g, ' ').trim() : null,
      空壳块: shells,
      标题数: heads.length,
      首个标题: heads[0] ? heads[0].textContent.trim() : null,
      标题字号: cs(heads[0], 'fontSize'),
      标题加粗: Number(cs(heads[0], 'fontWeight')),
      二级标题字号: cs(h2, 'fontSize'),
      二级标题文本: h2 ? h2.textContent.trim() : null,
      正文段字号: cs(q('.answer .ast-p'), 'fontSize'),
      段间距: second ? cs(second, 'marginTop') : null,
      标题后内容: heads[1] && heads[1].nextElementSibling
        ? cs(heads[1].nextElementSibling, 'marginTop')
        : null,
      列表上间距: ul ? cs(ul, 'marginTop') : null,
      主色: primaryRgb,
      染色的加粗: strongs.filter((s) => s.classList.contains('ast-num')).map((s) => s.textContent.trim()),
      未染色的加粗: strongs.filter((s) => !s.classList.contains('ast-num')).map((s) => s.textContent.trim()),
      染色色值: cs(strongs.find((s) => s.classList.contains('ast-num')), 'color'),
      /* 主色也是**文字色**，就得在真正托着它的那块底上量 AA（口径同全站：
         每种行底色各量一次，不吃 token 名的保险）。 */
      染色对比度: (() => {
        const el = strongs.find((s) => s.classList.contains('ast-num'));
        return el ? cr(cs(el, 'color'), opaqueBg(el)) : 0;
      })(),
      标签字号: cs(labelEl, 'fontSize'),
      标签竖条: [cs(labelEl, 'borderInlineStartWidth'), cs(labelEl, 'borderInlineStartColor')],
      标签上间距: cs(labelEl, 'marginTop'),
      标签有中文副标: Boolean(labelEl && labelEl.querySelector('.sec-label-zh')),
      meta在块外: Boolean(meta && !meta.closest('.summary-callout')),
      meta在紫块下方: Boolean(meta && q('.summary-callout') && meta.compareDocumentPosition(q('.summary-callout')) & 2),
      meta字号: cs(meta, 'fontSize'),
      meta对比度: meta ? cr(cs(meta, 'color'), opaqueBg(meta)) : 0,
      卡内边距: tiles[0] ? cs(tiles[0], 'padding') : null,
      卡宽: tiles.map((t) => Math.round(t.getBoundingClientRect().width)),
      卡总宽: Math.round(tiles.reduce((a, t) => a + t.getBoundingClientRect().width, 0)),
      网格宽: grid ? Math.round(grid.getBoundingClientRect().width) : 0,
      网格display: cs(grid, 'display'),
      空态存在: Boolean(empty),
      空态描边: empty ? [cs(empty, 'borderTopWidth'), cs(empty, 'backgroundColor')] : null,
      /* 判"虚线框还在不在"要盯那句话本身：`.chip[style]` 会命中引用行里的其它胶囊，
         那是误报（第一版就是这么把一条好断言写成恒真的反例）。 */
      虚线框还在: qa('.result-wrap .chip').some((c) => (c.textContent || '').includes('本次无命中')),
    };
  });
  console.log('   实测：', JSON.stringify(m).slice(0, 620));

  check(`${label}：裸序号行真的成了标题（皮肤是 .ast-h--1）`, m.标题数 === 2 && m.首个标题 === '一、门禁开门延时默认几秒？', [m.标题数, m.首个标题]);
  check(`${label}：一级 16px / 二级 15px，都比 14px 正文大`, m.正文段字号 === '14px' && m.标题字号 === '16px' && m.二级标题字号 === '15px' && m.标题加粗 >= 700, [m.正文段字号, m.标题字号, m.二级标题字号, m.标题加粗]);
  check(`${label}：段落之间 18px（原来 11px 与行内换行分不开）`, m.段间距 === '18px', m.段间距);
  check(`${label}：标题下面紧跟的内容收紧到 8px`, m.标题后内容 === '8px', m.标题后内容);
  check(`${label}：列表与上方段落 8px`, m.列表上间距 === '8px', m.列表上间距);
  check(`${label}：只有"加粗且含数字"才提到主色`, m.染色的加粗.join('|') === '3-5 秒|42' && m.未染色的加粗.join('|') === '重要提示', [m.染色的加粗, m.未染色的加粗]);
  check(`${label}：染的那格确实是主色`, m.染色色值 === m.主色 || m.染色色值 === null, [m.染色色值, m.主色]);
  check(`${label}：主色当文字用也要 ≥4.5（在这块底上实测）`, m.染色对比度 >= 4.5, m.染色对比度);
  check(`${label}：FINAL ANSWER 标签升到 14px + 中文副标`, m.标签字号 === '14px' && m.标签有中文副标 === true, [m.标签字号, m.标签有中文副标]);
  check(`${label}：标签左侧 3px 主色竖条`, m.标签竖条[0] === '3px' && m.标签竖条[1] === m.主色, m.标签竖条);
  check(`${label}：标签上方 24px，与摘要条分段`, m.标签上间距 === '24px', m.标签上间距);
  check(`${label}：硬指标那行已拆到紫块外、且排在块下方`, m.meta在块外 === true && m.meta在紫块下方 === true, [m.meta在块外, m.meta在紫块下方]);
  check(`${label}：拆出来之后仍 ≥4.5（去掉底色就不许再用 --text-3）`, m.meta对比度 >= 4.5, m.meta对比度);
  check(`${label}：指标卡内边距收到 10/12`, m.卡内边距 === '10px 12px 11px', m.卡内边距);
  check(`${label}：三块卡靠左不吃满（flex + 每块 ≤240）`, m.网格display === 'flex' && m.卡宽.every((w) => w <= 240) && m.卡总宽 < m.网格宽 - 20, [m.网格display, m.卡宽, m.卡总宽, m.网格宽]);
  check(`${label}：引用空态不再画虚线框`, m.空态存在 === true && m.虚线框还在 === false && m.空态描边[0] === '0px', [m.空态描边, m.虚线框还在]);
  check(
    `${label}：摘要条画出来时必须有内容（结果页不许有空壳容器）`,
    /^摘要：\S/.test(m.摘要条文本 || '') && m.空壳块.length === 0,
    { 摘要条: m.摘要条文本, 空壳: m.空壳块 },
  );

  /* ---- ② 反方向：认不出结论段时，那块紫底**整块不渲染**（而不是留一条空紫条）----
     真实场景就是 1 + 1 = 2 / 1024 × 768 = 786432 这类一句话答案 —— 2026-09-25 用户实测
     打到的是这条：结果页「成功 · 工具调用…」上方多出一条浅色横条，背景在、内容空。
     上一版的写法是"容器常驻、里面那行 <p> 条件渲染"，而 .summary-callout 自己带底色 +
     描边 + 11/14 内边距 ⇒ 空的时候就是高 23px 的一条色块。本地库里 6 条已完成任务 4 条中招。
     这一档把同一份详情换成一句话答案，验两件事：块不在 DOM 里；"为什么没有"由
     .result-meta 那句话补上（缺解释等于什么都不说，用户会以为渲染坏了）。 */
  answerNow = '1 + 1 = 2';
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(800);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(800);
  const n = await page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
    const shells = qa('.result-wrap *')
      .filter((e) => {
        if ((e.textContent || '').trim() !== '') return false;
        if (e.querySelector('svg') || e.closest('[aria-hidden="true"]')) return false;
        /* 带标签的**图形**豁免（2026-09-26 加，成本面板的分段条撞出来的）：
           `.spark` 与它那些色块 span 本来就不该有字 —— 说"这是什么"的活儿由 role="img"
           上那条 aria-label 干（AA 趟按内容断言它非空且逐段点名，见那里的 4d）。
           ⚠️ 只豁免**真带标签**的那一类：没标签的图形照样记名，不许借这条开静默盲区。 */
        const graphic = e.closest('[role="img"]');
        if (graphic && (graphic.getAttribute('aria-label') || '').trim()) return false;
        const r = e.getBoundingClientRect();
        if (r.height <= 0) return false;
        const v = nums(getComputedStyle(e).backgroundColor);
        return v.length >= 3 && (v.length < 4 || v[3] > 0.05);
      })
      .map((e) => `${String(e.className || e.tagName).split(' ')[0]}@${Math.round(e.getBoundingClientRect().height)}px`);
    return {
      答案在场: (q('.answer')?.innerText || '').replace(/\s+/g, ' ').trim(),
      有摘要块: Boolean(q('.summary-callout')),
      块高: q('.summary-callout') ? Math.round(q('.summary-callout').getBoundingClientRect().height) : null,
      meta文本: (q('.result-meta')?.innerText || '').replace(/\s+/g, ' ').trim(),
      空壳块: shells,
    };
  });
  check(`${label}：前件（一句话答案）：答案真的渲染出来了`, n.答案在场.includes('1 + 1 = 2'), n.答案在场);
  check(
    `${label}：认不出结论段 ⇒ 摘要块整块不在 DOM 里（不再画一条空紫条）`,
    n.有摘要块 === false && n.块高 === null,
    n,
  );
  check(`${label}：结果页仍然没有任何"有底色没内容"的空壳`, n.空壳块.length === 0, n.空壳块);
  check(
    `${label}：没有摘要要给时，那行硬指标补上"为什么没有"`,
    /没认出结论段/.test(n.meta文本),
    n.meta文本,
  );

  check(`${label}：这一趟没有 pageerror`, errors.length === 0, errors.slice(0, 2));

  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.result-wrap').screenshot({ path: path.join(OUT, `polish-${label}-result.png`) });
  console.log(`  ✓ 截图 → polish-${label}-result`);
  await ctx.close();
}

/* ---------------------------- J 窄屏横向溢出 ---------------------------- */
/** 页内块级普查：文档横向溢出量 + 越界元素清单。
 *  被祖先 `overflow-x: hidden/auto/scroll` 裁掉的元素**不算**越界 —— 它们撑不宽文档。
 *  不排这一档的话，虚拟化容器和页签横滚容器里那些天然超宽的行会永远误报。 */
function readOverflow() {
  const de = document.documentElement;
  const clientW = de.clientWidth;
  const clipped = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'hidden' || ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  const offenders = [];
  const hiddenByClip = [];
  for (const el of document.querySelectorAll('body *')) {
    const b = el.getBoundingClientRect();
    if (b.width === 0 || b.height === 0) continue;
    if (b.right > clientW + 1) (clipped(el) ? hiddenByClip : offenders).push(el);
  }
  /* 两份清单都要报：offenders 为空但 scrollWidth 仍超出时，真凶一定在被裁的那份里
     （被裁的元素撑不宽文档，但它同时会把真凶藏起来 —— 320 档实测就是这样，
     只报 offenders 会得出「没有越界元素却溢出 18px」这种自相矛盾的读数）。 */
  const shape = (el) => {
    const b = el.getBoundingClientRect();
    const host = clipped(el) ? el.parentElement : el;
    let pathStr = '';
    for (let p = host; p && p !== document.body; p = p.parentElement) {
      pathStr = `${p.tagName.toLowerCase()}.${String(p.className || '').split(' ')[0]} ${pathStr}`;
    }
    return {
      cls: String(el.className || el.tagName).slice(0, 40),
      right: Math.round(b.right),
      w: Math.round(b.width),
      host: pathStr.trim().slice(0, 70),
    };
  };
  /* 第三份清单：自身内容比自己的内容盒还宽、又没有横向滚动裁掉的元素 ——
     这类元素会把宽度**往上漏给祖先**，最后表现为文档溢出。上面两份清单查的是
     「谁的右边界越出去了」，但 `scrollWidth > clientWidth` 的溢出根本不会体现在
     任何 getBoundingClientRect 上（子元素被算进父级的滚动区，边界还在视口内），
     320 档卡在这里就是因为少这一路。只在确实溢出时才普查，别白扫三遍。 */
  let widening = [];
  if (de.scrollWidth - clientW > 0) {
    widening = Array.from(document.querySelectorAll('body *'))
      .filter((el) => {
        if (el.scrollWidth <= el.clientWidth + 1) return false;
        const ox = getComputedStyle(el).overflowX;
        return ox === 'visible';
      })
      .slice(0, 6)
      .map((el) => ({
        cls: String(el.className || el.tagName).slice(0, 40),
        scrollW: el.scrollWidth,
        clientW: el.clientWidth,
      }));
  }
  return {
    overflowPx: de.scrollWidth - clientW,
    scrollW: de.scrollWidth,
    clientW,
    offenders: offenders.slice(0, 6).map(shape),
    hiddenByClip: hiddenByClip.slice(0, 6).map(shape),
    widening,
  };
}

/** 为什么单独一趟：窄屏下日志控件挂在页签栏的 extra 位，而页签栏那行是 AntD 的
 *  横滚容器、不换行 —— 一排 411px 的控件在 390 视口下把整篇文档顶到 545。
 *  实测证据（2026-09-24 的 Edge 检查）：越界元素 `div.ant-tabs-extra-content`，
 *  left 134 / right 545 / width 411，内含级别 Select + 关键字 Input + 暂停 + 清空。
 *  两个挂载分支都要钉：漏了窄屏分支就是这次的缺陷；漏了宽屏分支会把控件挤没。 */
async function passNarrowOverflow(browser) {
  const cases = [
    { vw: 390, inPanel: true },
    /* 320 只记录不判定：结果页签上 `.page-columns` 有 18px 的宽度外漏
       （scrollWidth 276 / clientWidth 258，实测 scrollW=338 / clientW=320）。
       这类外漏不体现在任何 getBoundingClientRect 上 —— 子元素被算进父级的滚动区，
       右边界还在视口内，所以 offenders 是空的。报告与验收口径都是 390，390 档全绿；
       320 留在这里当**读数探针**，等真要把支持面压到 320 时再修（同一处置方式见 F 趟
       对 4,800 行 1.8s 的负面对照）。 */
    { vw: 320, inPanel: true, recordOnly: true },
    { vw: 820, inPanel: false },
  ];
  console.log('\n== J 窄屏横向溢出 ==');

  for (const c of cases) {
    const ctx = await browser.newContext({
      viewport: { width: c.vw, height: 844 },
      colorScheme: 'light',
      locale: 'zh-CN',
    });
    await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await installMocks(page);
    /* 灌一档有日志的：0 行时 LogStream 渲染浅色静默态（没有深色工具条），
       控件那时同样要能用，所以两档都得过 —— 这里先测有日志的。 */
    await page.route('**/api/tasks/*/trace*', (r) =>
      r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(virtualTrace(120)),
      }),
    );
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    /* ≤1024 时第二栏收进 fixed 抽屉（translateX 到视口外），Playwright 点不到 ——
       这趟要的是"选中一条任务"，不是验抽屉，故直接派发 click（同 H 趟的口径）。 */
    await page.evaluate(() => document.querySelector('.tsk-item').click());
    await page.waitForTimeout(700);
    /* 页签调换之后日志那一屏不点就没有：控件挂点（`tab==='log'` 才进页签栏 extra 位）
       与溢出测量量的都是它。下面本来就有一击「换到结果页签再量一次」，两击各归各的。 */
    await openLogTab(page);

    /* ---- 日志页签：溢出 + 控件挂点 ---- */
    const g = await page.evaluate(readOverflow);
    console.log(`   ${c.vw}px / 日志：`, JSON.stringify(g));
    check(`${c.vw}px 日志页签无横向溢出`, g.overflowPx === 0, g);
    check(`${c.vw}px 日志页签无越界元素`, g.offenders.length === 0, g.offenders);

    const at = await page.evaluate(() => {
      const nodes = Array.from(document.querySelectorAll('.log-controls'));
      const one = nodes.length === 1 ? nodes[0] : null;
      const mount = !one
        ? '无'
        : one.closest('.ant-tabs-extra-content')
          ? '页签栏'
          : one.closest('.ant-tabs-tabpane')
            ? '面板顶行'
            : '其他';
      return { parts: nodes.length, kids: one ? one.children.length : -1, mount };
    });
    console.log(`   ${c.vw}px 控件挂点：`, JSON.stringify(at));
    check(`${c.vw}px 控件组只有一份（没被两个挂载点重复渲染）`, at.parts === 1, at);
    check(`${c.vw}px 四个控件齐`, at.kids === 4, at);
    check(
      `${c.vw}px 挂在${c.inPanel ? '面板顶行' : '页签栏 extra 位'}`,
      at.mount === (c.inPanel ? '面板顶行' : '页签栏'),
      at,
    );

    /* ---- 换到结果页签再量一次（页签栏本身也是溢出源） ---- */
    await page.getByRole('tab', { name: '运行结果' }).click();
    await page.waitForTimeout(600);
    const g2 = await page.evaluate(readOverflow);
    console.log(`   ${c.vw}px / 结果：`, JSON.stringify(g2));
    if (c.recordOnly) {
      console.log(`  · 记录：${c.vw}px 结果页签横向溢出 ${g2.overflowPx}px（已知限制，见上方案例表注释）`);
    } else {
      check(`${c.vw}px 结果页签无横向溢出`, g2.overflowPx === 0, g2);
    }
    check(`${c.vw}px 结果页签无越界元素`, g2.offenders.length === 0, g2.offenders);

    /* ---- 零日志的静默态：控件不能因为皮肤换掉就消失 ----
       ⚠️ 选择器必须走 aria-label：`.log-controls input` 会先命中 AntD Select 的
          内部搜索框（只读），给它赋值不报错也**什么都不过滤** —— 上一版就是这样
          把「过滤到零行」这一步整条跑空了还照样绿。 */
    await page.getByRole('tab', { name: /实时日志/ }).click();
    await page.getByLabel('日志关键字过滤').fill('绝无此关键字');
    await page.waitForTimeout(500);
    const idle = await page.evaluate(() => ({
      idle: Boolean(document.querySelector('.log-idle')),
      rows: document.querySelectorAll('.log-row').length,
      controls: document.querySelectorAll('.log-controls > *').length,
    }));
    console.log(`   ${c.vw}px 静默态：`, JSON.stringify(idle));
    check(`${c.vw}px 关键字过滤确实滤到零行`, idle.rows === 0, idle);
    check(`${c.vw}px 零行时退到静默态皮肤`, idle.idle === true, idle);
    check(`${c.vw}px 静默态下四个控件还在`, idle.controls === 4, idle);
    check(`${c.vw}px 全程无 JS 报错`, errors.length === 0, errors.slice(0, 3));

    fs.mkdirSync(OUT, { recursive: true });
    await page.locator('.pane').screenshot({
      path: path.join(OUT, `narrow-${c.vw}-idle.png`),
    });
    await ctx.close();
  }
}

/* --------------------------- K 回放页选任务 --------------------------- */
/** 给某条任务的 trace 盖上只有它自己有的钢印。
 *  为什么要钢印：`"页面显示的是谁的轨迹"` 必须是一个**可断言的事实**，
 *  不能靠肉眼看文案。有了钢印，"点了 B 却还在放 A" 就表现为
 *  「DOM 里的钢印 ≠ 地址栏的 ?id=」，一条比较搞定。 */
function stampedTrace(taskId) {
  const items = [1, 2, 3].map((i) => ({
    event_seq: i,
    step: i,
    sub_step: null,
    event_type: 'node_end',
    role: 'planner',
    node: 'planner',
    thought: `钢印 ${taskId} 的第 ${i} 步`,
    tool_name: null,
    arguments: null,
    observation: 'ok',
    latency_ms: 100 + i,
    tokens_in: 10,
    tokens_out: 5,
    cost: 0.0001,
    status: 'done',
    error_code: null,
    error_message: null,
    created_at: new Date(Date.now() - i * 1000).toISOString(),
  }));
  return {
    items,
    total: items.length,
    limit: 50,
    after_seq: 0,
    next_after_seq: null,
    has_more: false,
    events_available: true,
    unavailable_reason: null,
  };
}

/** 读页面上出现过的钢印 id 集合（去重）。 */
function readStamps() {
  const hits = String(document.body.innerText).match(/钢印 (task-[0-9a-f]+)/g) || [];
  return Array.from(new Set(hits.map((s) => s.replace('钢印 ', ''))));
}

/** 为什么单独一趟：`?id=` 与 `taskId` 是两个状态源，点列表时先把 `taskId` 改写、
 *  再比较 `idParam !== taskId` —— 两个条件双双恒假，症状是"在回放页点别的任务，
 *  右侧还是上一条"。这一趟钉的是那条不变量：**页面上的钢印必须等于地址栏的 id**。 */
async function passTraceSelection(browser) {
  console.log('\n== K 回放页选任务 · 状态源一致性 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const asked = [];
  await installMocks(page);
  /* 后注册的 route 先匹配（同 C 趟的注意点）：按请求 URL 里的 id 现造 trace。 */
  await page.route('**/api/tasks/*/trace*', (r) => {
    const m = r.request().url().match(/tasks\/([^/?#]+)\/trace/);
    const id = m ? decodeURIComponent(m[1]) : 'unknown';
    asked.push(id);
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(stampedTrace(id)),
    });
  });
  const urlId = () => new URL(page.url()).searchParams.get('id') ?? '';

  /* ① 无 ?id= 进页：回落到最近一条，且 URL 要被写上 */
  await page.goto(`${BASE}/trace`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  let stamps = await page.evaluate(readStamps);
  console.log('   ①首屏：', JSON.stringify({ url: urlId(), stamps, asked }));
  check('首屏 URL 写上了 ?id=（不再只存组件 state）', urlId().startsWith('task-'), urlId());
  check('首屏页面钢印 = URL 的 id', stamps.length === 1 && stamps[0] === urlId(), {
    stamps,
    url: urlId(),
  });
  const firstId = urlId();

  /* ② 点第二栏里**另一条**任务 —— 这就是上一版永远不动的那个动作 */
  const other = page.locator('.tsk-item').nth(1);
  await other.click();
  await page.waitForTimeout(700);
  stamps = await page.evaluate(readStamps);
  console.log('   ②点第 2 条：', JSON.stringify({ url: urlId(), stamps }));
  check('点另一条任务后 URL 跟着换', urlId() !== firstId && urlId().startsWith('task-'), {
    url: urlId(),
    firstId,
  });
  check('点另一条任务后**只**显示这一条的轨迹', stamps.length === 1 && stamps[0] === urlId(), {
    stamps,
    url: urlId(),
  });
  const secondId = urlId();

  /* ③ 点第三条：不能只验"从 1 到 2"，两跳以上才排除了"永远停在第一次" */
  await page.locator('.tsk-item').nth(2).click();
  await page.waitForTimeout(700);
  stamps = await page.evaluate(readStamps);
  console.log('   ③点第 3 条：', JSON.stringify({ url: urlId(), stamps }));
  check('连点第三条同样换得动', stamps.length === 1 && stamps[0] === urlId(), {
    stamps,
    url: urlId(),
  });
  /* ④ 地址栏直达（?id= 是入口，不是结果） */
  await page.goto(`${BASE}/trace?id=${secondId}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  stamps = await page.evaluate(readStamps);
  check('地址栏带 ?id= 直达时放的就是那条', stamps.length === 1 && stamps[0] === secondId, {
    stamps,
    secondId,
  });

  /* ⑤ 再点当前已选中的那条 = 刷新：URL 不变，但要真的重新发一次请求 */
  const before = asked.filter((x) => x === secondId).length;
  await page.locator('.tsk-item').nth(1).click();
  await page.waitForTimeout(700);
  const after = asked.filter((x) => x === secondId).length;
  stamps = await page.evaluate(readStamps);
  console.log('   ⑤重复点同一条：', JSON.stringify({ before, after, stamps }));
  check('点已选中的那条会重新拉一次（当刷新用）', after > before, { before, after });
  check('刷新后仍只显示这一条', stamps.length === 1 && stamps[0] === secondId, {
    stamps,
    secondId,
  });
  /* C8 在轨迹页的那一份：这一页正是用户并排比对同类任务的地方，
     "为什么两次不一样"在这里问得最多。结果页那句（A 趟钉着）不能替它 ——
     两个页各说各的，少一处就有一处人永远看不到。 */
  const traceTips = await page.evaluate(() =>
    /* 释义的来源跟着 F-4 换了位置：`.metric-info` 按钮里那句 `.sr-only`。
       原生 `title` 留作兜底（不是 MetricTile 的卡仍然用 title 挂解释）。 */
    Array.from(document.querySelectorAll('.metric')).map((m) => {
      const btn = m.querySelector('.metric-info');
      const span = btn && btn.querySelector('.sr-only');
      return [
        ((m.querySelector('.metric-label span:not(.anticon)') || {}).textContent || '').trim(),
        (span && span.textContent) || m.getAttribute('title') || '',
      ];
    }),
  );
  const tt = traceTips.find((x) => x[0] === '总 token');
  check(
    '轨迹页的「总 token」也带着同一句解释（采样 + 时段 + 实测数字，不是只在结果页有）',
    !!tt && /采样/.test(tt[1]) && /时段|×0\.5/.test(tt[1]) && /实测/.test(tt[1]),
    tt ? tt[1].slice(0, 46) : traceTips.map((x) => x[0]),
  );
  check('全程无 JS 报错', errors.length === 0, errors.slice(0, 3));

  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, 'trace-select.png') });
  await ctx.close();
}

/* --------------------------- L 列表选中态回填 --------------------------- */
/** 页内给 EventSource 记账（开了几条 / 关了几条 / 分别是哪条任务）。
 *  连接泄漏从请求日志上看不出来 —— 请求都已经发出去了；唯一算数的口径是
 *  「手上还活着的句柄数」。谁调 close() 都包得住，包括 client 里终态那次。 */
function esLedgerInit() {
  const Orig = window.EventSource;
  const led = { opened: 0, closed: 0, urls: [] };
  window.__es = led;
  const Wrapped = function (url, opts) {
    const es = new Orig(url, opts);
    led.opened += 1;
    led.urls.push(String(url));
    const origClose = es.close.bind(es);
    /* 只数第一次 close：client 在终态帧和 onerror 两条路径上都会关一次，
       同一条连接关两次是无害的，但会把 `opened === closed` 这个口径弄成假红。
       要测的是「开过的都关掉过」，不是「close 被调了几次」。 */
    let closedOnce = false;
    es.close = () => {
      if (!closedOnce) {
        closedOnce = true;
        led.closed += 1;
      }
      return origClose();
    };
    return es;
  };
  Wrapped.prototype = Orig.prototype;
  for (const k of ['CONNECTING', 'OPEN', 'CLOSED']) Wrapped[k] = Orig[k];
  window.EventSource = Wrapped;
}

/** 一条会**自己跑完**的流：snapshot → node → done。终态帧一到，
 *  client 会 close 并回调 onDone ⇒ 正是 P0-03 那个 noop 分支被踩到的时刻。 */
function finishFrames() {
  const f = [];
  const push = (event, seq, payload) =>
    f.push(`event: ${event}\ndata: ${JSON.stringify({ seq, ts: new Date().toISOString(), ...payload })}\n\n`);
  push('snapshot', 1, { status: 'running', progress: null });
  push('node', 2, { node: 'planner', update: { plan: ['拆三步'] }, status: 'running' });
  push('done', 3, { status: 'done' });
  return f.join('');
}

/** L 趟回填用的答案：一个只在这里出现的字符串，断言时不必猜排版。 */
const L_ANSWER = 'L 趟回填答案 6120W';

/** 为什么要单独一趟：从第二栏点开一条**正在跑**的任务时，`selectTask` 给的
 *  `onDone` 是 `() => undefined`（只有提交路径才补拉详情）⇒ 流一关，详情再也不拉，
 *  结果区永远停在「后端未回填 final_answer」，一条成功的任务被读成没跑完。
 *  顺带钉连接句柄数：`stopRef.current` 在 await 之后才赋值，会把上一条的句柄冲掉。 */
async function passListSelectFinish(browser) {
  console.log('\n== L 从列表选中任务 · 跑完要回填 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  await ctx.addInitScript(esLedgerInit);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 有状态的详情：SSE 一被请求过（= 任务跑完），详情就回终态 + 带答案。
     没有这层状态机的话，"回填" 这个动作在测试里永远是真的 —— 接口一开始就给了答案，
     onDone 是不是 noop 根本看不出差别（上一版就想这么测，测了个寂寞）。 */
  const streamed = new Set();
  await page.route('**/api/tasks/*', (r) => {
    const u = r.request().url();
    if (u.includes('/trace')) {
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(traceBody) });
    }
    const id = decodeURIComponent((u.match(/tasks\/([^/?#]+)/) || [])[1] || '');
    const done = streamed.has(id);
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        done
          ? { ...detail, status: 'done', final_answer: L_ANSWER, duration_ms: 4200 }
          : { ...detail, status: 'running', final_answer: null, duration_ms: null },
      ),
    });
  });
  await page.route('**/sse/tasks/*/*', (r) => {
    const id = decodeURIComponent((r.request().url().match(/tasks\/([^/?#]+)/) || [])[1] || '');
    streamed.add(id);
    return r.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
      body: finishFrames(),
    });
  });

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(1200);

  const ledger = await page.evaluate(() => ({ ...window.__es }));
  console.log('   句柄账：', JSON.stringify(ledger));
  check('从列表选中非终态任务会补订阅（opened ≥ 1）', ledger.opened >= 1, ledger);
  check('流走完后句柄被关掉，没有悬着的连接', ledger.opened === ledger.closed, ledger);

  /* 现场快照打在点页签**之前**：这一趟上次死在 `getByRole('tab')` 超时上，
     而错误收集放在末尾 ⇒ 崩的时候什么都看不见。诊断必须在会炸的那一步前面。 */
  const diag = await page.evaluate(() => ({
    tabs: Array.from(document.querySelectorAll('[role="tab"]')).map((t) =>
      String(t.textContent || '').slice(0, 14),
    ),
    pane: Boolean(document.querySelector('.pane')),
    runbar: Boolean(document.querySelector('.runbar')),
    head: String(document.body.innerText).replace(/\s+/g, ' ').slice(0, 180),
  }));
  console.log('   现场：', JSON.stringify(diag));
  check('页签栏在（三个页签都渲染出来）', diag.tabs.length === 3, diag.tabs);

  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(600);
  const res = await page.evaluate(
    (ans) => {
      const t = String(document.querySelector('.result-wrap')?.innerText || '');
      return { filled: t.includes(ans), notBackfilled: t.includes('后端未回填'), len: t.length };
    },
    L_ANSWER,
  );
  console.log('   结果区：', JSON.stringify(res));
  check('流关闭后详情补拉回来了、结果区显示真答案', res.filled === true, res);
  check('不再停在「后端未回填」那句空态文案', res.notBackfilled === false, res);
  check('全程无 JS 报错', errors.length === 0, errors.slice(0, 3));

  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, 'list-select-finish.png') });
  await ctx.close();
}

/* ------------------------- M 日志面板重渲染账 ------------------------- */
/** 为什么要单独一趟：`mergedAway(rows)` 以前每次渲染都全量 reduce（最多 5,000 步），
 *  而页面 1Hz 跳秒就会触发一次。修法是 memo —— 但"memo 生效"不能只断言
 *  「静置 3 秒渲染次数为 0」：**计数器坏掉时那条也恒真**。所以这一趟双向：
 *  先证明计数器数得到（改关键字 ⇒ 必须 ≥1），再证明无关的父级重渲染数不到（⇒ 0）。
 *  读数（actualDuration 累加）只打印不判定 —— 单个 reduce 的耗时在不同机器上抖动太大。 */
async function passRenderCount(browser) {
  console.log('\n== M 日志面板重渲染账（双向：计数器活着 + memo 挡得住）==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  // 回放态：详情回终态 ⇒ 页面那个 1Hz 计时器根本不启动，
  // "静置时零提交"才是由 memo 保证的，而不是由"没有定时器"蒙出来的。
  // ⚠️ 两条 route 分开注册、trace 那条**后**注册（Playwright 后注册的先匹配）：
  //    单层通配那条匹配不到带 query 的 trace URL，硬塞进同一个 handler 分流会让 trace
  //    悄悄退回默认 mock 的 13 条 —— 面板从"240 行可滚"变成"11 行到底"，于是所有滚动
  //    类断言都在测一件根本没发生的事（下面那条"覆盖生效"就是钉这个的）。
  // ⚠️ 这段只能写行注释：写进 /* */ 里，glob 字面量中的 `*/` 会把块注释提前闭合，
  //    剩下的半句变成真代码 —— 症状是 ReferenceError: api is not defined，
  //    而 `node --check` 不报错（那半句恰好是个合法表达式）。
  await page.route('**/api/tasks/*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...detail, status: 'done', duration_ms: 4200 }),
    }),
  );
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(virtualTrace(240)),
    }),
  );
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelector('.tsk-item').click());
  await page.waitForTimeout(900);
  /* 这一趟整支都在量日志面板的重渲染账 ⇒ 先把日志页签点开（默认页签现在是运行结果）。
     顺带说一句：没点开的話 `logstreamRender` 会是 -1（面板根本没挂载），
     那既不是"零重渲染"的好消息，也不是这趟要说的话。 */
  await openLogTab(page);

  const led = () => page.evaluate(() => ({ ...(window.__renders || {}) }));
  /** mergedAway 的调用计数（插桩在 src/utils/logRows.ts 里）。-1 = 插桩没挂上。 */
  const merged = () => page.evaluate(() => window.__mergedAway?.n ?? -1);
  const snap = await page.evaluate(() => ({
    rows: document.querySelectorAll('.log-row').length,
    total: Number(
      (String(document.querySelector('.log-foot')?.textContent || '').match(/已显示 (\d+) 行/) ||
        [])[1] || 0,
    ),
    spacer: Math.round(document.querySelector('.log-virtual')?.getBoundingClientRect().height || 0),
    renders: (window.__renders || {}).logstream ?? 0,
  }));
  console.log('   现场：', JSON.stringify(snap));
  /* 这条先于一切：它钉的是"本趟的 mock 真的接上了"，而不是产品行为。
     没有它，trace 退回默认 13 条时下面的滚动断言会静默变成空转。 */
  check('trace 覆盖生效：面板共 240 行', snap.total === 240, snap);
  check('spacer 撑出全量高度（远高于一屏，滚动才有得滚）', snap.spacer > 340 * 3, snap);
  check('常驻行数落在虚拟化那一窗里（≤60）', snap.rows > 0 && snap.rows <= 60, snap);

  /* ① 反证 A：计数器是活的 —— 改关键字会让 rows 换引用，mergedAway **必须**重跑一次。
        没有这一步，下面的"delta = 0"在计数器坏掉时同样成立（恒真的回归守卫等于没有）。 */
  const a0 = await led();
  const m0 = await merged();
  await page.getByLabel('日志关键字过滤').fill('PoE');
  await page.waitForTimeout(500);
  const a1 = await led();
  const m1 = await merged();
  console.log('   ①改关键字：', JSON.stringify({ a0, a1, m0, m1 }));
  check('提交计数器是活的（改关键字 ⇒ logstream ≥ 1）', (a1.logstream ?? 0) > (a0.logstream ?? 0), {
    a0,
    a1,
  });
  check('mergedAway 插桩是活的（rows 换引用 ⇒ 必须重算）', m1 > m0 && m0 >= 0, { m0, m1 });

  /* ② 正证：一次与日志无关的父级重渲染（打开运行配置浮层）⇒ 那趟 O(全部行) 的 reduce
        不该再跑。判据用 mergedAway 调用次数而不是组件提交数 —— 后者掺了面板自己的
        重测量（行高动态测，浮层一开一合就会自渲染一次），会把 memo 判成失效。 */
  const b0 = await merged();
  const cb0 = await led();
  await page.locator('.cp-icon').click();
  await page.waitForSelector('.rcp', { state: 'visible' });
  await page.waitForTimeout(600);
  const b1 = await merged();
  const cb1 = await led();
  const commits = (cb1.logstream ?? 0) - (cb0.logstream ?? 0);
  console.log('   ②开浮层：', JSON.stringify({ b0, b1, commits }));
  check('浮层确实开了（否则"没有重算"是 vacuous）', (await page.locator('.rcp').count()) > 0);
  check('无关的父级重渲染没有重跑 mergedAway（memo 生效）', b1 === b0, { b0, b1 });
  /* 只记录不判定：自渲染几次取决于测高回填的时机，跨机器不稳。 */
  console.log(`   读数（不判定）：这一趟组件提交了 ${commits} 次`);

  /* ②B 面板**自己**滚动：rows 引用没变，但组件必然重渲染（虚拟窗口换了一段）。
        这才是 `useMemo(mergedAway)` 唯一挡得住的场景 —— 负面对照就是摘掉这层 useMemo，
        届时这里必须红。（第一版用"打开浮层"当 ②，测到的其实是外层的 memo(LogStream)：
        父级重渲染根本到不了 merged 那一行，摘掉 useMemo 也不红 —— 假绿，已改。）
        ⚠️ 必须先把关键字清空：① 填的 'PoE' 会把面板滤到只剩 1 行，那时没有可滚的
        高度，"没重算"会因为"根本没滚动"而成立 —— 所以「滚动真的动了」这条要先判。
        滚法沿用 C 趟的惯用法（直接设 scrollTop + 派发 scroll）；`mouse.wheel` 在这个
        容器上量不到位移。 */
  await page.getByLabel('日志关键字过滤').fill('');
  await page.waitForTimeout(500);
  const s0 = await merged();
  const pre = await page.evaluate(() => ({
    rows: document.querySelectorAll('.log-row').length,
    firstSeq: document.querySelector('.log-row .log-seq')?.textContent || '',
    max: Math.round(document.querySelector('.log-body')?.scrollHeight || 0),
  }));
  await page.evaluate(() => {
    const b = document.querySelector('.log-body');
    b.scrollTop = Math.round(b.scrollHeight * 0.45);
    b.dispatchEvent(new Event('scroll'));
  });
  await page.waitForTimeout(600);
  const post = await page.evaluate(() => ({
    top: Math.round(document.querySelector('.log-body')?.scrollTop || 0),
    rows: document.querySelectorAll('.log-row').length,
    firstSeq: document.querySelector('.log-row .log-seq')?.textContent || '',
  }));
  const s1 = await merged();
  console.log('   ②B滚动：', JSON.stringify({ s0, s1, pre, post }));
  check(
    '滚动真的换了窗口（否则"没重算"是 vacuous）',
    post.top > 0 && post.firstSeq !== pre.firstSeq,
    { pre, post },
  );
  check('面板自渲染时没有重跑 mergedAway（useMemo 生效）', s1 === s0, { s0, s1, pre, post });
  /* ③ 静置 3 秒 ⇒ 零提交 + 零重算（这一档同时兜住"有人又把 1Hz 提到页面级"） */
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const c0 = await led();
  const d0 = await merged();
  await page.waitForTimeout(3000);
  const c1 = await led();
  const d1 = await merged();
  console.log('   ③静置 3 秒：', JSON.stringify({ c0, c1, d0, d1 }));
  check('回放态静置 3 秒零提交', (c1.logstream ?? 0) === (c0.logstream ?? 0), { c0, c1 });
  check('回放态静置 3 秒零重算', d1 === d0, { d0, d1 });
  check('全程无 JS 报错', errors.length === 0, errors.slice(0, 3));

  await ctx.close();
}

/* ---------------------- N 迟到响应不许盖别人 ---------------------- */
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

/** 给某条任务造一档"行数不同 + 答案带 id"的 trace，用来分辨屏幕上是谁。 */
function raceTrace(taskId, rows) {
  const items = Array.from({ length: rows }, (_, k) => {
    const i = k + 1;
    return {
      event_seq: i,
      step: i,
      sub_step: null,
      event_type: 'node_end',
      role: 'planner',
      node: 'planner',
      thought: `RACE ${taskId} 第 ${i} 条`,
      tool_name: null,
      arguments: null,
      observation: 'ok',
      latency_ms: 10,
      tokens_in: 1,
      tokens_out: 1,
      cost: 0,
      status: 'done',
      error_code: null,
      error_message: null,
      created_at: new Date(Date.now() - (rows - i) * 100).toISOString(),
    };
  });
  return {
    items,
    total: rows,
    limit: 50,
    after_seq: 0,
    next_after_seq: null,
    has_more: false,
    events_available: true,
    unavailable_reason: null,
  };
}

/** 为什么要单独一趟：详情 + 轨迹是两个请求，而轨迹**串行分页**（client 里 ≤10 页 × 50 条
 *  逐页 await），慢的一条要跑满好几个 RTT ⇒ 先点 A、立刻点 B，A 后到就把 A 的答案与日志
 *  盖在 B 上。界面不报错、不闪烁，只是内容不对 —— 这是 P0 里唯一"错了也看不出来"的一类。
 *
 *  慢的是**第一个被请求的 id**（`firstId`），不是我以为的某一条：这样才保证它一定后到。
 *  两条都给终态（不订阅 SSE），把这一趟的变量收窄到"迟到响应落不落地"。 */
async function passLateResponse(browser) {
  console.log('\n== N 迟到响应不许盖别人 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);

  let firstId = null;
  const slowFor = (id) => {
    if (firstId === null) firstId = id;
    return id === firstId;
  };
  const idOf = (u) => decodeURIComponent((u.match(/tasks\/([^/?#]+)/) || [])[1] || '');

  // 详情：答案里带 id；第一条被请求的慢 900ms（trace 用同一条判据）
  await page.route('**/api/tasks/*', async (r) => {
    const u = r.request().url();
    if (u.includes('/trace')) return r.continue();
    const id = idOf(u);
    await sleep(slowFor(id) ? 900 : 0);
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...detail,
        task_id: id,
        status: 'done',
        final_answer: `答案 属于 ${id}`,
        duration_ms: 3000,
      }),
    });
  });
  // 轨迹：慢的那条给 60 行、快的给 3 行 ⇒ "共几行"本身就是谁的指纹
  await page.route('**/api/tasks/*/trace*', async (r) => {
    const id = idOf(r.request().url());
    const slow = slowFor(id);
    await sleep(slow ? 900 : 0);
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(raceTrace(id, slow ? 60 : 3)),
    });
  });

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);

  /* ---- N1 任务与日志页：连点两条，慢 A 后到 ---- */
  await page.locator('.tsk-item').nth(0).click();
  await page.waitForTimeout(120);
  const lateId = firstId;
  await page.locator('.tsk-item').nth(1).click();
  await page.waitForTimeout(2200);
  /* 页脚那句「已显示 N 行 / M 条」是这一趟的对账读数 ⇒ 得先点到日志那一屏
     （页签调换之后它不再是默认页，不点就没有 `.log-foot`，会被读成"迟到响应没盖住"）。 */
  await openLogTab(page);
  const fastId = await page.evaluate(
    () => document.querySelector('.tsk-item--on .tsk-title')?.textContent?.trim() || '',
  );
  const seen = await page.evaluate(() => {
    /* 页脚的真实格式是「已显示 N 行 / M 条」（M = 合并前的总条数）。
       别按"共 M"猜正则 —— 猜错会拿到 0，然后一条断言就变成在比 0 === 3。 */
    const foot = String(document.querySelector('.log-foot')?.innerText || '').replace(
      /\s+/g,
      ' ',
    );
    return {
      foot,
      shown: Number((foot.match(/已显示 (\d+) 行/) || [])[1] ?? -1),
      total: Number((foot.match(/\/ (\d+) 条/) || [])[1] ?? -1),
      answer: String(document.querySelector('.answer')?.innerText || ''),
    };
  });
  console.log('   N1：', JSON.stringify({ lateId, fastId, seen }));
  check('慢的那条确实被请求过（对撞成立，不是在测两条快的）', lateId.startsWith('task-'), lateId);
  check(
    '日志账目是**后点那条**的 3 条，不是迟到那包的 60 条',
    seen.total === 3 && seen.shown === 3,
    seen,
  );

  /* 答案在**结果页签**上 —— 在日志页签里读 `.answer` 会拿到空串，
     而"空串不包含迟到那条的文案"是恒真的假断言（第一版就这样绿了）。 */
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(700);
  const ans = await page.evaluate(() => ({
    text: String(document.querySelector('.answer')?.innerText || '').replace(/\s+/g, ' '),
    /* 结果页顶部那枚 Chip 就是页面自己认领的 taskId —— 用它当"应该显示谁"的基准，
       比在 node 侧猜列表顺序稳。 */
    shownId: String(document.querySelector('.result-wrap .chip, .result-wrap [class*="chip"]')?.innerText || '').trim(),
  }));
  console.log('   N1 答案：', JSON.stringify({ id: ans.shownId, text: ans.text.slice(0, 48) }));
  check('结果页签确实渲染了答案（否则下面两条是空串上的恒真）', ans.text.length > 0, ans.text.slice(0, 40));
  check('页面认领的 taskId 不是迟到那条', ans.shownId !== lateId && /^task-/.test(ans.shownId), {
    shownId: ans.shownId,
    lateId,
  });
  check('答案正文属于页面认领的那条', ans.text.includes(`答案 属于 ${ans.shownId}`), {
    shownId: ans.shownId,
    text: ans.text.slice(0, 60),
  });

  /* ---- N2 轨迹回放页：同一个对撞 ---- */
  await page.goto(`${BASE}/trace`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  firstId = null;
  await page.locator('.tsk-item').nth(0).click();
  await page.waitForTimeout(120);
  const late2 = firstId;
  await page.locator('.tsk-item').nth(1).click();
  await page.waitForTimeout(2200);
  const replay = await page.evaluate(() => {
    const ids = new Set(
      (String(document.body.innerText).match(/RACE (task-[0-9a-f]+)/g) || []).map((s) =>
        s.replace('RACE ', ''),
      ),
    );
    return { ids: [...ids], url: new URL(location.href).searchParams.get('id') || '' };
  });
  console.log('   N2：', JSON.stringify({ late2, replay }));
  check(
    '回放页只显示地址栏那条的轨迹（迟到的那包整包丢掉）',
    replay.ids.length === 1 && replay.ids[0] === replay.url,
    replay,
  );
  check('全程无 JS 报错', errors.length === 0, errors.slice(0, 3));

  await ctx.close();
}

/* --------------------- O 断流不等于任务结束 --------------------- */
/** 造一档"活着但永远不到终态"的流：snapshot + 一帧 node，然后**响应结束**。
 *  响应结束 = 服务端关流 = 浏览器的 EventSource 报 `error`，这正是"后端重启了一下"
 *  在客户端唯一可见的形式。（`page.route().fulfill()` 只能整包给完就收口，
 *   没有"中途 abort"这种控制，所以断流只能这么造 —— 但它造的确实是真实的那条错误路径：
 *   后面 1s 的退避重连、重连后的第一帧、对账请求，全都是真跑的。） */
function liveFrames() {
  const f = [];
  const push = (event, seq, payload) =>
    f.push(`event: ${event}\ndata: ${JSON.stringify({ seq, ts: new Date().toISOString(), ...payload })}\n\n`);
  push('snapshot', 1, { status: 'running', progress: null });
  push('node', 2, { node: 'planner', update: { plan: ['拆三步'] }, status: 'running' });
  return f.join('');
}

/** 为什么要单独一趟：终态帧和 `onerror` 以前共用一条路（都 `close(); onDone()`），
 *  于是后端重启一下就被当成"任务结束"。这一趟钉的是三条：
 *  ① 断流要**说出来**；② 但**不许**改任务状态（徽标仍「运行中」、结果页仍是待回填）；
 *  ③ 重连真的发生、且重连后按 `event_seq` 补拉了对账。
 *  另外顺手钉一条只有跨连接才暴露的：重连后服务端 `seq` 从头计过，
 *  客户端的 `maxSeq` 必须跨连接保留 —— 撞 key 的话 React 会打
 *  "Encountered two children with the same key"，所以这里连 console error 一起收。 */
async function passStreamDrop(browser) {
  console.log('\n== O 断流不等于任务结束 ==');

  const open = async (mode) => {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      colorScheme: 'light',
      locale: 'zh-CN',
    });
    await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
    const page = await ctx.newPage();
    const errors = [];
    const consoleErrs = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrs.push(m.text());
    });
    await installMocks(page);
    const tally = { sse: 0, trace: 0 };
    /* 两条 route 分开、trace 那条**后**注册（后注册的先匹配）。
       ⚠️ 这是 M 趟已经踩过一次的坑，别再犯：单层通配那条匹配不到带 query 的 trace URL，
       把 trace 分支塞进它内部的后果是"计数永远是 0"—— 而 0 看起来像"没发生对账"，
       其实连首屏那一次拉取都没计到。所以先断言基线 > 0，再断言增长。 */
    await page.route('**/api/tasks/*', (r) =>
      r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...detail, status: 'running', final_answer: null }),
      }),
    );
    await page.route('**/api/tasks/*/trace*', (r) => {
      tally.trace += 1;
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(virtualTrace(2)),
      });
    });
    await page.route('**/sse/tasks/*/*', (r) => {
      tally.sse += 1;
      if (mode === 'dead') {
        return r.fulfill({ status: 500, contentType: 'text/plain', body: 'api down' });
      }
      return r.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
        body: liveFrames(),
      });
    });
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    /* 「实时连接中断」那一行是**瞬态**：退避 1 秒后重连成功就被撤下，事后再查 DOM 只会查到
       "没有这行"（M 趟踩过：读数在事件当时不采，回头补采就成了空断言）。
       所以在点任务**之前**挂一个 MutationObserver，把每次出现时的文本 + 盒子 + 字色钉下来。
       ⚠️ 必须写 window.__noteSeen：evaluate 里的 `const` 不挂到 window 上，出去就查不到。 */
    await page.evaluate(() => {
      window.__noteSeen = [];
      const rec = () => {
        const n = document.querySelector('.stream-note');
        const bar = document.querySelector('.runbar');
        if (!n || !bar) return;
        const b = n.getBoundingClientRect();
        const rb = bar.getBoundingClientRect();
        window.__noteSeen.push({
          text: String(n.innerText).replace(/\s+/g, ' ').trim(),
          box: [Math.round(b.width), Math.round(b.height)],
          insideRight: Math.round(rb.right - b.right),
          insideBottom: Math.round(rb.bottom - b.bottom),
          color: getComputedStyle(n).color,
        });
      };
      new MutationObserver(rec).observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      window.__noteRec = rec;
    });
    await page.evaluate(() => document.querySelector('.tsk-item').click());
    const seen = () => page.evaluate(() => window.__noteSeen);
    return { ctx, page, errors, consoleErrs, tally, seen };
  };

  const readState = (page) =>
    page.evaluate(() => {
      const note = document.querySelector('.stream-note');
      const bar = document.querySelector('.runbar');
      /* 断流要**看得见**才算数：只报字色会让「渲染出来但高度 0 / 被 overflow 裁掉」
         这类情况全绿（C 趟与 J 趟都栽过一次）。 */
      const nb = note?.getBoundingClientRect();
      const bb = bar?.getBoundingClientRect();
      const lin = (v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
      let contrast = -1;
      if (note && bar) {
        const fa = nums(getComputedStyle(note).color);
        const A = fa.length > 3 ? fa[3] : 1;
        const bg = nums(getComputedStyle(bar).backgroundColor);
        const fg = fa.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
        const [l1, l2] = [lum(fg), lum(bg)].sort((x, y) => y - x);
        contrast = +(((l1 + 0.05) / (l2 + 0.05)).toFixed(2));
      }
      return {
        note: String(note?.innerText || '').replace(/\s+/g, ' '),
        badge: String(
          document.querySelector('.runbar .ant-badge-status-text, .runbar [class*="badge"]')?.innerText || '',
        ).trim(),
        running: Boolean(bar),
        runbarAria: bar?.getAttribute('role') || '',
        noteBox: nb ? [Math.round(nb.width), Math.round(nb.height)] : null,
        barBox: bb ? [Math.round(bb.width), Math.round(bb.height)] : null,
        contrast,
      };
    });

  /* ---- ① 断流 + 重连 + 对账 ---- */
  const a = await open('drop');
  await a.page.waitForTimeout(400);
  const before = await readState(a.page);
  const t0 = a.tally.trace;
  await a.page.waitForTimeout(2600); // 1s 退避之后应当已经重连上（第二次连接）
  const after = await readState(a.page);
  console.log('   drop 前：', JSON.stringify({ ...before, sse: a.tally.sse, trace: t0 }));
  console.log('   drop 后：', JSON.stringify({ ...after, sse: a.tally.sse, trace: a.tally.trace }));
  check('断流被如实说出来（运行条上有一行连接状态）', a.tally.sse >= 2 && before.note.includes('中断'), {
    note: before.note,
    sse: a.tally.sse,
  });
  check('退避重连真的发了第二次连接', a.tally.sse >= 2, a.tally.sse);
  /* 出现过 ⇒ 再按出现那一刻的盒子量：高 ≥16（真占一行）、且完整落在运行条里
     （insideRight / insideBottom ≥ 0 ⇒ 没被 overflow 裁掉）。断流那一行是瞬态，
     事后补采会采到"没有这行"，所以读数来自点任务之前就挂好的 MutationObserver。 */
  const seenA = await a.seen();
  check(
    '断流那一行真占了一行、没被运行条裁掉（瞬态读数取自观察器）',
    seenA.some(
      (x) => /中断/.test(x.text) && x.box[1] >= 16 && x.insideRight >= 0 && x.insideBottom >= 0,
    ),
    seenA.slice(-1),
  );
  check('断流的字色在运行条底上 ≥4.5（告警档不许随主题掉到 3.x）', before.contrast >= 4.5, before.contrast);
  check('重连后按 event_seq 补拉了对账（基线 ≥1 且断流后又增加）', t0 >= 1 && a.tally.trace > t0, {
    t0,
    t1: a.tally.trace,
  });
  check('断流期间没有把任务说成已结束（运行条还在、仍是运行态）', after.running === true, after);
  check('断流的文案只谈连接、不谈结果', /结束|完成|失败/.test(after.note) === false, after.note);
  check(
    '跨连接 seq 不撞车（React duplicate key 的 console error 为 0）',
    a.consoleErrs.filter((x) => x.includes('same key')).length === 0,
    a.consoleErrs.slice(0, 3),
  );
  check('无 JS 报错', a.errors.length === 0, a.errors.slice(0, 3));
  await a.ctx.close();

  /* ---- ② 三次重连都接不上 ⇒ 认输并说清楚 ---- */
  const b = await open('dead');
  await b.page.waitForTimeout(400);
  const tBase = b.tally.trace; // 首屏 selectTask 那一次
  await b.page.waitForTimeout(5000); // 1s + 3s 两次退避都已失败过
  const tDuring = b.tally.trace;
  await b.page.waitForTimeout(10_500); // 再等第三次（9s）用完 ⇒ 认输
  const gave = await readState(b.page);
  console.log(
    '   放弃重连：',
    JSON.stringify({
      ...gave,
      sse: b.tally.sse,
      traceBase: tBase,
      traceDuring: tDuring,
      trace: b.tally.trace,
    }),
  );
  check('退避三次后停止重试（连接数 = 首连 + 3 次重试）', b.tally.sse === 4, b.tally.sse);
  check('认输时说的是"重连未成功"，不是"任务失败"', /3 次/.test(gave.note), gave.note);
  check('仍然不把断流说成终态', /已结束|已完成|失败$/.test(gave.note) === false, gave.note);
  /* ⚠️ 下面两条钉的是"对账只在接回 / 认输时做"。刚断的那一刻后端还没把断口之后的事件
     落完（契约是先落库再发布 ⇒ 那时能拉到的就是屏幕上已有的一份），白跑一个 RTT；
     而三次退避全失败时若每次 lost 都整包重拉，就成了对一个正在抖的后端的请求踩踏。 */
  check('基线：首屏确实拉过一次轨迹（否则"零增长"是蒙对的）', tBase >= 1, tBase);
  check('断线期间不每次重连都刷 /trace（两次失败退避之间零增长）', tDuring === tBase, {
    tBase,
    tDuring,
  });
  check('认输时补拉最后一次（把已有的整份账落下来）', b.tally.trace === tBase + 1, {
    tBase,
    got: b.tally.trace,
  });
  const seenB = await b.seen();
  check(
    '认输那一行也真占了一行、没被裁（瞬态读数取自观察器，不是事后补采）',
    seenB.some((x) => /3 次/.test(x.text) && x.box[1] >= 16 && x.insideRight >= 0 && x.insideBottom >= 0),
    seenB.slice(-1),
  );
  check('无 JS 报错', b.errors.length === 0, b.errors.slice(0, 3));
  await b.ctx.close();
}

/* ------------------------------ P 取消的四种结局 ------------------------------ */
/** 心跳 ×3 + planner 一帧之后**再补一帧心跳**：用来回答「取消失败之后那条流还活着吗」。
 *  这一帧只在重连的连接上给，且故意晚 2.5 秒 —— 点取消时它还在路上。 */
function extraHeartbeat() {
  return `event: heartbeat\ndata: ${JSON.stringify({
    seq: 6,
    ts: new Date().toISOString(),
    running_ms: 60000,
  })}\n\n`;
}

// 报告 B13：`cancelTask` 是 `await fetch(...)` 一把梭，不判 `res.ok`。
// 于是 200（真的取消了）/ 409（早就是终态，没得取消）/ 404（这条不存在）/ 网络没送达
// 在前端是同一句话 —— 本地还把徽标改成了「已取消」，任务其实还在跑。
// 现在四种结局分开：判据走 `detail.code`（后端契约，见 api/errors.py），不匹配中文文案。
//
// ⚠️ 这一趟同时治 B 趟那颗死桩：Playwright 的 `*` **不跨 `/`**，所以旧版塞在
// `**/api/tasks/*` 里的 `if (u.includes('/cancel'))` 分支从来没命中过，真正答取消的是
// installMocks 那条一律 200 的 `**/api/tasks/*/cancel`。"取消永远成功"的桩让「409 说
// 反话」这类缺陷在物理上不可达 ⇒ 桩必须能改状态码，才算可达路径。
// （同样因为块注释里的 glob 会被 `*/` 提前闭合，这段用行注释。）
async function passCancelOutcome(browser) {
  console.log('\n== P 取消：200 / 409 / 5xx / 没送达 必须四种说法 ==');
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

  const open = async (mode) => {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      colorScheme: 'light',
      locale: 'zh-CN',
    });
    await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
    const page = await ctx.newPage();
    const errors = [];
    const cancelHits = [];
    let sseCall = 0;
    let detailStatus = 'running';
    page.on('pageerror', (e) => errors.push(e.message));
    await installMocks(page);
    // 后注册的先匹配 ⇒ 这几条盖住 installMocks 的默认桩。取消要单独注册成三段式的 glob
    // （`.../tasks/*/cancel`），才能真正接管 `/api/tasks/{id}/cancel`（见上面那条 ⚠️）。
    await page.route('**/api/tasks/*/cancel', (r) => {
      cancelHits.push(r.request().url());
      if (mode === 'network') return r.abort(); // 根本没送达：fetch 直接 reject
      /* 5xx：后端活着、但这单没办成。它**不是**"任务已是终态"那种明确拒绝，所以口径必须
         走"没送达"那一支（未生效是反话），而且不许把在飞的流关掉 —— 用户唯一的补救是再点一次。
         只在第一次命中时报 500：第二次走下面的 200 分支，于是"再点一次真能取消掉"是可证的。 */
      if (mode === 'server500' && cancelHits.length === 1) {
        return r.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: {
              code: 'internal_error',
              message: '取消处理器抛了：redis 连接断了',
              request_id: 'req-uicheck-p5',
            },
          }),
        });
      }
      if (mode === 'conflict') {
        detailStatus = 'done'; // 服务端说它早就结束了 —— 本地那份不可信
        return r.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: {
              code: 'task_already_finished',
              message: '任务已处于终态，无法取消：task-3f9a1c02be11',
              request_id: 'req-uicheck-p',
            },
          }),
        });
      }
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: TASK_ID,
          status: 'canceled',
          canceled_at: new Date().toISOString(),
          mode: 'node_boundary',
          note: '取消在当前节点边界生效，之后的结果会被丢弃',
        }),
      });
    });
    await page.route('**/api/tasks/*', (r) =>
      r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...detail,
          status: detailStatus,
          final_answer: detailStatus === 'done' ? detail.final_answer : null,
          duration_ms: detailStatus === 'done' ? detail.duration_ms : null,
        }),
      }),
    );
    await page.route('**/sse/tasks/*/*', async (r) => {
      const n = (sseCall += 1);
      /* fulfill 一律裹 try/catch：取消成功之后客户端会把这条在飞的连接掐掉，
         届时 r.fulfill 抛"already handled / target closed" —— 那是**预期**，不是桩坏了。 */
      if (n === 1) {
        await sleep(400);
        try {
          await r.fulfill({
            status: 200,
            headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
            body: runningFrames(),
          });
        } catch {
          /* 页面已经不等了 */
        }
        return;
      }
      /* 重连上的这一帧晚 2.5 秒给：点取消时它还在路上，于是"取消失败后流还活着吗"
         成了一个能直接读出答案的观测（帧到了 = 没被白掐）。
         只在 network 这一档给 —— 另几档给了反而会干扰读数：409 之后那帧心跳会把
         handlePhase('running') 再推一次，徽标到底停在谁的口径就成了看时区的断言。
         不给就挂住（一个永不 settle 的 promise，没有计时器 ⇒ 不会按住 Node 进程）。 */
      if (mode !== 'network') return new Promise(() => {});
      // 1.2s：这一帧必须**晚于**点取消（约在 1.0s），又早于 post 那次读数（约 4.2s）。
      // 两侧都留了 ~1s 的余量 —— 再短就变成"取消前帧就到了"，那条断言会假绿。
      await sleep(1200);
      try {
        await r.fulfill({
          status: 200,
          headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
          body: extraHeartbeat(),
        });
      } catch {
        console.log('   · 重连的那帧没能落地（连接已被页面掐掉）');
      }
    });

    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    await page.locator('.composer-input').fill('1024 路摄像头整机功耗怎么估算？给出算式与结果');
    await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();
    /* 提交后落在「运行结果」⇒ 这一趟要的 `.log-row--live` 与页脚那句都得先把页签点回来。 */
    await openLogTab(page);
    await page.waitForSelector('.log-row--live', { timeout: 8000 }); // 5 条已落地
    const read = () =>
      page.evaluate(() => {
        const pop = document.querySelector('.ant-popconfirm');
        return {
          toast: String(document.querySelector('.ant-message')?.innerText || '').replace(/\s+/g, ' ').trim(),
          badge: String(document.querySelector('.runbar .status-badge')?.innerText || '').trim(),
          foot: String(document.querySelector('.log-foot')?.innerText || '').replace(/\s+/g, ' ').trim(),
          events: Number((document.querySelector('.log-foot')?.innerText || '').match(/\/ (\d+) 条/)?.[1] ?? -1),
          note: String(document.querySelector('.stream-note')?.innerText || '').replace(/\s+/g, ' ').trim(),
          cancelBtn: Array.from(document.querySelectorAll('.runbar-actions button')).map((b) => b.textContent.trim()),
          // AntD 不活跃的浮层不删 DOM，只加 ant-popover-hidden ⇒ 必须连这个类一起判
          popOpen: Boolean(pop) && !pop.classList.contains('ant-popover-hidden'),
          popText: pop ? String(pop.innerText).replace(/\s+/g, ' ').trim() : '',
        };
      });
    const pre = await read();
    return { ctx, page, errors, cancelHits, read, pre, mode, sse: () => sseCall };
  };

  const label = { ok: '200 取消成功', conflict: '409 已是终态', server500: '5xx 后端内部错误', network: '请求没送达' };
  const scenarios = ['ok', 'conflict', 'server500', 'network'];
  for (const mode of scenarios) {
    const h = await open(mode);
    console.log(`\n-- ${label[mode]} --`);
    check(`${label[mode]}：取消之前日志已经在推（否则后面"活没活着"无从判断）`, h.pre.events === 5, h.pre.events);
    /* 二次确认：第一下只弹框，不发请求（与 B 趟同一判据，这里再钉一次是因为
       取消的失败分支如果被误触发，"点一下就取消"会变成"点一下就把流掐了"） */
    await h.page.locator('.runbar-actions .ant-btn-dangerous').click();
    // 900ms 不是随手写的：AntD 的浮层走 portal + motion，500ms 时偶发还没挂上 DOM
    // （第一版就在 400ms 上读到 popOpen=false，而随后的 .ant-popconfirm 点击却又成功 ——
    //  说明框确实会弹，只是读得太早）。
    await h.page.waitForTimeout(900);
    const armed = await h.read();
    check(
      `${label[mode]}：第一下只弹确认框（浮层真在场），cancel 请求为 0`,
      armed.popOpen === true && armed.popText.includes('仍要取消') && h.cancelHits.length === 0,
      { popOpen: armed.popOpen, popText: armed.popText, hits: h.cancelHits },
    );
    await h.page.locator('.ant-popconfirm .ant-btn-primary').click();
    await h.page.waitForTimeout(600);
    const mid = await h.read();
    console.log('   点完确认 600ms：', JSON.stringify(mid));
    await h.page.waitForTimeout(2600); // 让那条 2.5s 的重连帧要么落地要么被掐掉
    const post = await h.read();
    console.log('   再 2.6s：      ', JSON.stringify(post));
    check(`${label[mode]}：恰好一条 cancel 请求（失败不自动重试）`, h.cancelHits.length === 1, h.cancelHits);
    check(`${label[mode]}：无 pageerror`, h.errors.length === 0, h.errors.slice(0, 3));
    if (mode === 'ok') {
      check('200：徽标落到「已取消」', /已取消/.test(post.badge), post.badge);
      check('200：成功不该弹错误条', mid.toast === '' && post.toast === '', [mid.toast, post.toast]);
      /* 成功后关流是对的 ⇒ 那帧晚到的心跳不该落进来（5 条，不是 6 条）。
         这条与 network 那条一起把"先问后端、再关流"的顺序钉死。 */
      check('200：取消成功后不再收帧（事件数停在 5）', post.events === 5, { mid: mid.events, post: post.events });
      check('200：终态之后运行条不再给取消按钮', post.cancelBtn.length === 0, post.cancelBtn);
    }
    if (mode === 'conflict') {
      check('409：说的是"取消未生效"并把后端那句话带出来', /取消未生效：任务已处于终态/.test(mid.toast), mid.toast);
      check('409：不许补"可能仍在运行"这种反话', /可能仍在运行/.test(mid.toast) === false, mid.toast);
      check('409：本地不许擅自改成「已取消」，徽标要用服务端真值', /成功/.test(post.badge) && /已取消/.test(post.badge) === false, post.badge);
    }
    if (mode === 'server500') {
      /* 后端明确回话了，但回的是"我这侧办砸了"—— 这既不是"没得取消"（未生效是反话），
         也不是"已经取消了"。唯一正确的口径仍是"没送达 + 可能仍在运行"，
         并把后端原话带出来（redis 断了这类原因用户/值班都要能看见）。 */
      check('5xx：说的是"取消未送达"，并带上后端那句原话', /取消未送达/.test(mid.toast) && /redis 连接断了/.test(mid.toast), mid.toast);
      check('5xx：不许说"取消未生效"（那是明确拒绝的口径）', /取消未生效/.test(mid.toast) === false, mid.toast);
      check('5xx：徽标纹丝不动（还是取消前那个读数，也没本地改成已取消）', post.badge === h.pre.badge && /已取消/.test(post.badge) === false, { pre: h.pre.badge, post: post.badge });
      check('5xx：第一次失败没有自动重试', h.cancelHits.length === 1, h.cancelHits.length);
      /* 「必须还能再点一次」到这里才是可证的：上一档只验了按钮还在，而按钮在 ≠ 点得动。
         第二次点走 200 分支（桩里按 cancelHits 计数切换），徽标必须真的落到「已取消」。 */
      await h.page.locator('.runbar-actions .ant-btn-dangerous').click();
      await h.page.waitForTimeout(900);
      const armed2 = await h.read();
      check('5xx：再点仍然先弹确认（不因为"刚失败过"就跳过二次确认）', armed2.popOpen === true && h.cancelHits.length === 1, armed2.popText);
      await h.page.locator('.ant-popconfirm .ant-btn-primary').click();
      await h.page.waitForTimeout(900);
      const retry = await h.read();
      check('5xx：再点一次真能取消掉（徽标「已取消」）', /已取消/.test(retry.badge), retry.badge);
      check('5xx：两次点击 = 两条 cancel 请求（对得上，不多发）', h.cancelHits.length === 2, h.cancelHits.length);
      check('5xx：成功之后不该留着上一条失败toast', /取消未送达/.test(retry.toast) === false, retry.toast);
    }
    if (mode === 'network') {
      check('没送达：说的是"取消未送达；任务可能仍在运行"', /取消未送达/.test(mid.toast) && /可能仍在运行/.test(mid.toast), mid.toast);
      check('没送达：徽标不许变成「已取消」', /已取消/.test(post.badge) === false, post.badge);
      /* 这一条是"先问后端、再关流"的正面证据：取消失败之后那条流还开着 ⇒ 晚到的心跳才落得进来。
         读数从 5 涨到 13 而不是 6，是因为心跳触发了 'restored' 对账、整包换成 /trace ——
         而 P 趟的 trace 桩用的还是 installMocks 那份**已完成**的 13 条 fixture（跑着的任务
         根本不该有这份账）。要的信号只是"变大了"：帧到了才会涨，被白掐就停在 5。
         旧顺序（closeStream 在 await 之前）下流已经被关，这帧永远到不了 ⇒ 读数停在 5 翻红。 */
      /* 取消那一刻确实处于"中断"态 ⇒ 后面那条"接回去了"才有前件（不先在场的恢复是句空话）。
         ⚠️ 但**不能**拿"那一行消失了"当证据：假后端的响应体是一次性给完的，'restored' 之后
         紧接着就是下一条 onerror ⇒ 'lost'，撤下与挂上之间只差毫秒，采样必然抓不到空窗
         （O 趟同样因此改用「中断」在场 + 连接计数）。所以这里钉两件可持久的事：
         ① 客户端确实发了第二条连接；② 那帧心跳真的落进来了（下面的事件数增长）。 */
      check(
        '没送达：取消那一刻确实处于"中断"态（前件在场，不是空跑）',
        /中断/.test(mid.note),
        mid.note,
      );
      check(
        '没送达：客户端自己重连上了（SSE 连接数 ≥ 2）',
        h.sse() >= 2,
        h.sse(),
      );
      check(
        '没送达：流没被白掐（晚到的那一帧心跳仍落进日志）',
        post.events > mid.events && mid.events === 5,
        { mid: mid.events, post: post.events },
      );
      /* 失败之后必须还能再点一次：旧顺序把流关了、状态卡在运行中，按钮虽然还在但整屏已经不再更新 */
      check('没送达：取消按钮还在（用户还可以再试一次）', post.cancelBtn.length === 1, post.cancelBtn);
    }
    await h.ctx.close();
  }
}

// ------------------------------ Q 后台标签的探测 ------------------------------ //
// N4 + B11：useHealth 的 `if (document.hidden) return` 跑在 try/finally **之前** ——
// 页面在后台被打开时这一次探测直接早退，finally 里的 setLoading(false) 根本没跑，
// 于是顶栏徽标停在「探测中」；而 30 秒一次的 tick 每次都在同一处早退，用户切回来
// 还要再等最多 30 秒（浏览器在后台还会把计时器压到分钟级）才终于动起来。
// 修法两半：hidden 时照常不发探测（没测过就不许编结论），但切回前台必须立刻补拉一次。
async function passHiddenProbe(browser) {
  console.log('\n== Q 后台标签：徽标不许永远停在「探测中」==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  /* Playwright 的页面永远是 visible ⇒ 不接管这两个属性，"在后台被打开"这条路径
     压根造不出来，整趟就是空跑。addInitScript 跑在应用脚本之前，正合适。
     ⚠️ 必须 configurable: true（覆盖 Document.prototype 上的 getter），
     且赋值只能走 window.__hidden —— evaluate 里的 const 不挂到 window 上。 */
  await ctx.addInitScript(() => {
    window.__hidden = true;
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => window.__hidden === true,
    });
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => (window.__hidden === true ? 'hidden' : 'visible'),
    });
  });
  const page = await ctx.newPage();
  const errors = [];
  let healthHits = 0;
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  // 后注册的先匹配：这条只为数探测次数，响应体与 installMocks 那份一致
  await page.route('**/api/health', (r) => {
    healthHits += 1;
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(healthBody),
    });
  });

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500); // 够第一个 tick 与所有微任务跑完

  const pill = () =>
    page.evaluate(() =>
      String(document.querySelector('.status-pill')?.innerText || '').replace(/\s+/g, ' ').trim(),
    );
  const st = await page.evaluate(() => ({ hidden: document.hidden, vs: document.visibilityState }));
  check('前件：这一趟真的跑在 hidden 状态下（否则后面全是空跑）', st.hidden === true && st.vs === 'hidden', st);
  const pillHidden = await pill();
  console.log('   后台 1.5s：', JSON.stringify({ pill: pillHidden, healthHits }));
  check('后台打开时不发探测请求（省掉必然被节流的 RTT）', healthHits === 0, healthHits);
  check('后台打开时徽标如实停在「探测中」', /探测中/.test(pillHidden), pillHidden);
  check('没测过就不许编结论：不许写成「后端未连接 / 不健康 / 降级」', /未连接|不健康|降级|正常/.test(pillHidden) === false, pillHidden);

  // 切回前台：浏览器只会发 visibilitychange，不会重跑挂载 effect
  await page.evaluate(() => {
    window.__hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(1200);
  const pillBack = await pill();
  console.log('   切回前台 1.2s：', JSON.stringify({ pill: pillBack, healthHits }));
  check(
    '切回前台立刻补拉一次（不等下一个 30 秒刻度）',
    /服务正常/.test(pillBack) && healthHits >= 1,
    { pillBack, healthHits },
  );
  check('补拉之后才交出服务端真值', /探测中/.test(pillBack) === false, pillBack);
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

// ------------------------------ R Composer 的三个设置：点得动、也说得出 ------------------------------ //
// 起点是报告 C7：「`.switch-row` 用 label 包 AntD 的 Switch，点标题文字不翻」。
// 两轮负面对照把这条拆成两半，结论和报告给的不一样：
// ① **label 转发那半不成立**：字段注册修好之后，外面这层就是原生 `<label>`、没有任何转发
//    onClick，点标题文字照样翻（实测点的位置落在开关左边缘之外），点开关本体也照样只翻一次。
//    也就是说 C7 描述的"点了没反应"根本不是热区问题。
// ② 真正的坑是**字段没注册**：三项只写在 initialValues 里、没有任何 Form.Item name，而
//    rc-field-form 的 getFieldsValue() 只收**已注册**字段 ⇒
//    useWatch 恒为 undefined（界面冻在兜底值，**连点开关本体都不动**），
//    onFinish 的 values 里也压根没有这三个键 ⇒ 实发请求体是
//    {"task":"…","enabled_tools":["calculator","code_exec"]} ——
//    use_tools / max_iterations 整个丢掉，而 useRag 恒 undefined 让那个三元走了"排除知识库"那一支：
//    从界面提交的**任何**任务都检索不到知识库，界面上那颗 RAG 开关却显示"开"。不报错，只是静默算错。
// 所以这一趟两半都验：点得到（含键盘 Space），**并且界面说的等于发出去的**（抓 POST body 逐键对）。
//
// ⚠️ 2026-09-25：这一趟**曾经假绿过一次**，用户拿真实浏览器打回来的。修完 ② 之后
// 请求体实测仍是 {"task":"1+1","use_tools":true} —— 少了 ``max_iterations``。根因是
// ① 那句「必须注册」只说了一半：**注册过 ≠ 挂载过**。迭代轮数那颗 InputNumber 住在
// 「运行配置」弹层里，AntD 的弹层内容是懒挂的，没点开过就从来没挂载过 ⇒ 字段不在
// store 的"已注册"视图里 ⇒ onFinish 给的那份 values 没有这个键 ⇒ 键整个消失。
// 而 ② 那半边的用例**先点了弹层**才提交，所以它永远看不见这条。
// 三条口径从这里开始写死：
//   a) 值要从 ``form.getFieldsValue(true)``（整个 store）取，不要信 onFinish 那份过滤视图；
//   b) 断言要**逐键对键集合**，不是"某个键在不在"；
//   c) 每个默认值都要有一档"用户什么都没碰"的用例，单独开页，不借前一页的挂载状态。
// 负面对照 N5：把 handleSubmit 改回用 onFinish 的 values ⇒ ③ 的"键集合"与"max_iterations=3"
// 两条同时翻红（本轮实测：旧写法发出的是 {"task":"1+1","use_tools":true}）。
async function passComposerSettings(browser) {
  console.log('\n== R Composer 设置：点文字 / 点开关 / 键盘 / 请求体口径 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);

  /* 后注册的 route 优先：抢在 mocks 的提交 mock 之前把请求体抄下来，再回一份合法 ack ——
     不回 ack 页面直接进 failed 分支，第二次提交就没法看了。 */
  const bodies = [];
  await page.route('**/api/tasks', async (r) => {
    if (r.request().method() !== 'POST') return r.continue();
    try {
      bodies.push(JSON.parse(r.request().postData() || '{}'));
    } catch {
      bodies.push(null);
    }
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-R-hit',
        status: 'queued',
        created_at: new Date().toISOString(),
        trace_url: '/api/tasks/task-R-hit/trace',
        events_url: '/api/tasks/task-R-hit/events',
      }),
    });
  });

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);

  /* x 取行左 +5 —— 那是标题文字所在的一段。前件要同时成立两件事：命中的元素**不在**
     .ant-switch 里，**且**这个点落在开关左边缘的左边。整行实测只有 59px 宽、开关占掉右半，
     少了后一半，"点文字就翻"很容易其实点在轨道上 —— 那就退化成又验了一遍开关本体。 */
  const hit = (i) =>
    page.evaluate((idx) => {
      const rows = Array.from(document.querySelectorAll('.switch-row'));
      const row = rows[idx];
      if (!row) return null;
      const sw = row.querySelector('.ant-switch');
      const rb = row.getBoundingClientRect();
      const sb = sw ? sw.getBoundingClientRect() : null;
      const x = Math.round(rb.left + 5);
      const y = Math.round(rb.top + rb.height / 2);
      const at = document.elementFromPoint(x, y);
      return {
        x,
        y,
        total: rows.length,
        leftOfSwitch: sb ? x < Math.round(sb.left) : false,
        onSwitch: Boolean(at && at.closest('.ant-switch')),
        tag: at ? at.tagName.toLowerCase() : '',
        // 用 aria-checked 而不是 .ant-switch-checked：它是这个控件的对外口径
        checked: sw ? String(sw.getAttribute('aria-checked')) : null,
        role: sw ? String(sw.getAttribute('role')) : null,
        otherChecked: rows[1 - idx] ? String(rows[1 - idx].querySelector('.ant-switch')?.getAttribute('aria-checked')) : null,
      };
    }, i);

  const r0 = await hit(0);
  check(
    '前件：两行开关都在，且点的位置落在开关左边缘之外的文字上',
    r0 !== null && r0.total === 2 && r0.onSwitch === false && r0.leftOfSwitch === true,
    r0,
  );
  check('前件：开关仍是原生 button[role=switch]（不是 div 画的假控件）', r0.role === 'switch' && r0.checked === 'true', r0);

  await page.mouse.click(r0.x, r0.y);
  await page.waitForTimeout(300);
  const r1 = await hit(0);
  check('点标题文字就翻开关（原生 label 就会转发，不需要手写 onClick）', r1.checked === 'false', { before: r0.checked, after: r1.checked });
  check('只翻被点的那一行（RAG 那行不受影响）', r1.otherChecked === 'true', r1.otherChecked);

  await page.mouse.click(r1.x, r1.y);
  await page.waitForTimeout(300);
  const r2 = await hit(0);
  check('再点一次翻回来（不是单向置位）', r2.checked === 'true', r2.checked);

  await page.locator('.switch-row .ant-switch').first().click();
  await page.waitForTimeout(300);
  const r3 = await hit(0);
  check(
    '点开关本体只翻一次（label 不会对"点的就是被标注控件"再代劳一遍）',
    r3.checked === 'false',
    { before: r2.checked, after: r3.checked },
  );

  await page.locator('.switch-row .ant-switch').first().focus();
  await page.keyboard.press('Space');
  await page.waitForTimeout(300);
  const r4 = await hit(0);
  check('键盘 Space 照样能翻（label 包着也没丢焦点与操作）', r4.checked === 'true', r4.checked);
  const focused = await page.evaluate(() => document.activeElement?.className || '');
  check('开关仍然是可聚焦控件（tab 停得住）', focused.includes('ant-switch'), focused);

  // ---- ② 界面说的 == 发出去的：抓 POST body 逐键对 ----
  // 此刻 工具=开（r4）、RAG=开。先把「工具」点掉，再把迭代改成 7，然后提交。
  const off = await hit(0);
  await page.mouse.click(off.x, off.y);
  await page.waitForTimeout(300);
  await page.locator('button.cp-icon').click();
  await page.waitForTimeout(400);
  /* ⚠️ 这里原来是 `input[aria-label="最大迭代轮数"]` —— 那一屏的**字段名与单位**从本轮起
     来自 ``fields[].label`` / ``unit``，桩里的措辞刻意与后端不同（"迭代上限（桩词）"、"次"），
     所以判据一律按 ``data-field`` 定位、单位从**面板那一行**读回来比对，
     不在探针里再抄一份措辞（抄了就把"界面读响应"这件事变成探针读自己）。
     ⚠️ 前缀这一轮从 ``.ant-popover`` 换成 ``.ant-modal``：这一屏换成了模态，
        留着旧前缀不会红在"契约不对"上，只会红在 ``locator.fill`` 超时 ——
        全量跑到这里直接中断，后面的趟一趟没跑到（本轮就是这么发现的）。 */
  const iterInput = '.ant-modal .rcp [data-field="max_iterations"] input';
  await page.locator(iterInput).fill('7');
  await page.waitForTimeout(300);
  const { hint, rowUnit } = await page.evaluate(() => ({
    hint: document.querySelector('.cp-hint')?.textContent?.trim() ?? '',
    rowUnit: document.querySelector(
      '.ant-modal .rcp [data-field="max_iterations"] .ant-input-number-group-addon',
    )?.textContent?.trim() ?? '',
  }));
  check('迭代改到 7，页脚读数跟着变（useWatch 活着，不是恒 undefined）',
    hint.startsWith(`7${rowUnit ? ` ${rowUnit}` : ''}`), { hint, rowUnit });
  check('页脚那行的单位与面板同一行**是同一个后缀**（两处都读 fields[].unit，不是各写一遍）',
    rowUnit.length > 0 && hint.includes(` ${rowUnit}`), { hint, rowUnit });
  /* 这里原来是 `page.keyboard.press('Escape')` —— 纯收尾动作、后面没有判据。
     换成 closeSettingsLayer 是有原因的：AntD 的 Esc 绑在 dialog 容器上，
     焦点不在这一层里时按 Esc 什么都不发生（本轮同一坑在 AD 趟踩过一次，
     那边改成了点右上角关闭）。留着 Esc 就是留一条"看起来收了、其实没收到"的定时炸弹。 */
  await closeSettingsLayer(page);

  await page.locator('.composer-input').fill('R 趟：界面与请求体必须同一个口径');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(900);
  const b1 = bodies[0] ?? {};
  check('第一次提交抓到请求体（没抓到后面全是空话）', bodies.length === 1, bodies.length);
  check('关掉的「工具」进了请求体：use_tools=false', b1.use_tools === false, b1.use_tools);
  check('迭代轮数进了请求体：max_iterations=7', b1.max_iterations === 7, b1.max_iterations);
  check('RAG 仍开着 ⇒ 不该排除知识库（不发白名单 = 后端全量）', 'enabled_tools' in b1 === false, b1.enabled_tools);

  const rag = await hit(1);
  await page.mouse.click(rag.x, rag.y);
  await page.waitForTimeout(300);
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(900);
  const b2 = bodies[1] ?? {};
  /* ⚠️ 这一条改过口径，而且是往**更严**的方向改（方案 P-6 / U-6）。
     旧版断言的是 ``['calculator','code_exec']`` —— 那份名单是前端在 ``client.ts`` 里写死的，
     桩里有六个工具它只发两个：关掉 RAG 顺带把 extract / file_io / web_search 也停了，
     而断言跟着那份写死的名单一起绿，永远看不见。
     现在期望值从**桩里的 /tools** 算出来（全量减掉 knowledge_search），
     所以"前端自带清单"这件事一露头就红 —— 负面对照 AD-neg2 用同一套算式验证。 */
  const expectedWhitelist = toolsBody.items.map((t) => t.name).filter((n) => n !== 'knowledge_search');
  check(
    '关掉 RAG 后发的是**完整白名单**（GET /tools 全量减掉未勾选项，不是前端抄的那两个）',
    JSON.stringify(b2.enabled_tools) === JSON.stringify(expectedWhitelist),
    { got: b2.enabled_tools, expected: expectedWhitelist },
  );
  check('两次提交互不串台：工具仍是关', b2.use_tools === false, b2.use_tools);
  check('改了迭代就必须发出去：第二次仍带 max_iterations=7', b2.max_iterations === 7, b2.max_iterations);

  /* ---- ③ 弹层**从头到尾没点开过**那一档（2026-09-25 用户真实浏览器实测打回来的票）----
     上面 ② 是"点开弹层、把 7 填进去、再提交"，所以它看不见这个缺陷：AntD 的 Popover 内容
     是**懒挂**的，没点开过 ⇒ 那颗 InputNumber 从未挂载 ⇒ 作为 Form 字段它从未注册 ⇒
     旧代码拿 onFinish 那份"只含已注册字段"的 values 去组装请求体 ⇒ ``max_iterations``
     整个键消失，而同一屏右下角写着「3 轮」。实测发出去的就是 {"task":"1+1","use_tools":true}。
     ⚠️ 2026-09-26 起这一档的**期望值变了**，而且不是放松：配置搬进 Context（U-5）之后，
     "没点开弹层"不再等于"字段丢了"，它等于"用户一个字都没说"⇒ 请求体里**只该有 task**。
     旧断言那个 ``['max_iterations','task','use_tools']`` 键集合本身是前端替后端补默认值，
     留着它就是把 P-8 那笔账重新写进判据。现在的判据是：键集合恰好 ``['task']``，
     而右下角那行读数用的是**响应给的**默认（桩里 6，后端真值 5 —— 都不等于旧的 3）。 */
  const ctx2 = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx2.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page2 = await ctx2.newPage();
  page2.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page2);
  const bodies2 = [];
  await page2.route('**/api/tasks', async (r) => {
    if (r.request().method() !== 'POST') return r.continue();
    try {
      bodies2.push(JSON.parse(r.request().postData() || '{}'));
    } catch {
      bodies2.push(null);
    }
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-R-noPopover',
        status: 'queued',
        created_at: new Date().toISOString(),
        trace_url: '/api/tasks/task-R-noPopover/trace',
        events_url: '/api/tasks/task-R-noPopover/events',
      }),
    });
  });
  await page2.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page2.waitForTimeout(700);

  const pre = await page2.evaluate(() => ({
    /* 读点从 ``.ant-popover`` 换成面板本体：这一屏已经是 Modal 了，数弹层等于
       "数一个不可能出现的东西"⇒ 恒真，前件不再挡得住"其实点开过"。
       ``.rcp`` 只属于这一个组件，且 AntD 不 forceRender ⇒ 没开过就不在 DOM 里。 */
    panels: document.querySelectorAll('.rcp').length,
    modals: document.querySelectorAll('.ant-modal').length,
    numberInputs: document.querySelectorAll('.ant-input-number').length,
    hint: document.querySelector('.cp-hint')?.textContent ?? '',
    switches: Array.from(document.querySelectorAll('.switch-row .ant-switch')).map((s) => s.getAttribute('aria-checked')),
  }));
  check('③ 前件：这一页从头到尾没点开过设置（面板、Modal 与 InputNumber 都不在 DOM 里）',
    pre.panels === 0 && pre.modals === 0 && pre.numberInputs === 0, pre);
  /* 读数那一屏的**数字与单位**都来自桩（``fields[].unit`` 本轮进契约后，界面不再自带
     "轮"这个后缀）⇒ 这里一律从桩里取，别在探针里抄一份措辞（抄了就变成探针读自己）。
     ⚠️ 这一条本轮栽过一次：改桩的单位之后，"/6 轮/" 这种字面量留在判据里 ⇒ R 趟③ 独红，
     而它红的原因是**探针**过期，不是界面说谎 —— 判据里的字面量要跟着桩走。 */
  const iterStub = agentOptionsBody.defaults.max_iterations;
  const iterUnit = agentOptionsBody.fields.find((f) => f.key === 'max_iterations')?.unit ?? '';
  check('③ 前件：界面上的读数是**响应给的**默认（桩里的 6 加桩里的单位，不是前端写死的 3 与"轮"）',
    iterStub !== 3 && iterUnit.length > 0 &&
      pre.hint.startsWith(`${iterStub} ${iterUnit}`) && !pre.hint.startsWith('3'),
    { hint: pre.hint, iterStub, iterUnit });
  check('③ 前件：两枚开关都没动过（默认 开/开）', JSON.stringify(pre.switches) === JSON.stringify(['true', 'true']), pre.switches);

  await page2.fill('textarea.composer-input', 'R 趟 ③：弹层没点开过，也一个字都不该替用户发');
  await page2.locator('button.cp-submit').click();
  await page2.waitForTimeout(900);
  const b3 = bodies2[0] ?? {};
  check('③ 抓到请求体（没抓到后面全是空话）', bodies2.length === 1, bodies2.length);
  check(
    '③ 键集合恰好只有 task：没被用户碰过的键一个都不发（发出去就是替后端做决定）',
    JSON.stringify(Object.keys(b3).sort()) === JSON.stringify(['task']),
    Object.keys(b3).sort(),
  );
  check(
    `③ 界面显示的是响应给的 ${iterStub} ${iterUnit}，而请求体里**没有** max_iterations —— ` +
      '真跑的是后端那份默认，前端没替它填一个数（旧版这里发的是自己编的 3）',
    b3.max_iterations === undefined && pre.hint.startsWith(`${iterStub} ${iterUnit}`),
    { body: b3, hint: pre.hint, iterStub, iterUnit },
  );
  check(
    '③ RAG 开着 ⇒ 不发排除清单；顺带钉住契约里**没有** use_rag 这个键（见 api/schemas.py:92-110）',
    'enabled_tools' in b3 === false && 'use_rag' in b3 === false,
    b3,
  );

  /* ---------------- R 趟补的一条：地址栏的 id 与界面上的钢印必须同一个 ----------------
     为什么放在这一趟而不是只留在 W 趟：这里的页面**已经提交过两次任务**，是全站唯一一个
     "URL 刚被写过、列表刚刷过、record 也被 SSE 改过状态"三份账凑在一起的时刻。
     选中态落到地址栏之后最容易悄悄分叉的就是"地址栏说 A、界面显示 B"，所以点回列表里
     **另一条**，比三样：地址栏的 task_id、列表高亮那一行在不在、主区不许还挂着上一条的空态。 */
  /* ---------------- R 趟补的一条：地址栏的 id 与界面上的钢印必须同一个 ----------------
     为什么放在这一趟而不是只留在 W 趟：这里的页面**已经提交过两次任务**（提交桩回的是
     自造 id `task-R-hit`，列表里根本没有这一条 ⇒ 点之前**没有任何高亮**），
     是全站唯一一个"URL 里的 id 不在列表里"的现场。选中态落到地址栏之后最容易悄悄分叉的
     就是这个形状：地址栏说 A，列表里高亮着 B，主区显示的是 C。
     判据用 `data-task-id`（列表项上刚加的），不拿文案猜 —— 上一版就是靠文本猜，
     误判成"点了没换"，红了一条自己的假绿。 */
  const preStamp = await page.evaluate(() => ({
    search: location.search,
    activeIds: Array.from(document.querySelectorAll('.tsk-item.is-active')).map((el) =>
      el.getAttribute('data-task-id'),
    ),
  }));
  const clickedId = await page.locator('.tsk-item:not(.is-active)').first().getAttribute('data-task-id');
  await page.locator(`.tsk-item[data-task-id="${clickedId}"]`).click();
  await page.waitForTimeout(1400);
  const stamp = await page.evaluate(() => ({
    url: new URL(location.href).searchParams.get('task_id') ?? '',
    activeIds: Array.from(document.querySelectorAll('.tsk-item.is-active')).map((el) =>
      el.getAttribute('data-task-id'),
    ),
    idle: document.querySelector('.log-idle-title')?.textContent?.trim() ?? null,
  }));
  check('④ 前件：提交之后列表里没有任何高亮（那条自造 id 不在列表里）', preStamp.activeIds.length === 0, preStamp);
  check(
    '点列表项之后：地址栏的 task_id 与高亮那一行的 data-task-id 是同一枚（界面不许和 URL 分叉）',
    stamp.url !== '' && stamp.url === clickedId && JSON.stringify(stamp.activeIds) === JSON.stringify([clickedId]),
    { clickedId, ...stamp },
  );
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx2.close();
  await ctx.close();
}

// ------------------------------ S 导出 CSV：文件真的落地 ------------------------------ //
// 报告 B9：downloadCsv 里 anchor 没进 DOM 就 click()、且 revokeObjectURL 同步调用。
// 后果是"在某些浏览器上点了没反应 / Safari 丢掉下载"，而且**一句报错都没有**。
// src/utils/format.ts 那三步（append → click → remove → 下一拍 revoke）在
// format.test.cjs 里用 DOM 替身钉住了；这一趟补的是端到端那半句：
// **真的产生了一次可读取的下载，文件里确实是带 BOM 的那张表**。
async function passCsvDownload(browser) {
  console.log('\n== S 导出 CSV：端到端拿到文件 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);

  const btn = page.locator('button:has-text("导出检索表 CSV")');
  const btnCount = await btn.count();
  check('前件：导出按钮在场（不然下面的等待只是一次超时）', btnCount === 1, btnCount);
  const leftovers = () => page.evaluate(() => document.querySelectorAll('a[download]').length);
  const n0 = await leftovers();
  check('导出前 DOM 里没有残留的下载 anchor', n0 === 0, n0);

  // waitForEvent 不接住超时就会抛，把后面所有趟一起带走 —— 先挂 waiter 再点，避免点击先跑完
  const grab = async () => {
    const waiter = page.waitForEvent('download', { timeout: 8000 }).catch(() => null);
    await btn.click();
    const dl = await waiter;
    if (!dl) return { dl: null, name: '', text: '' };
    const p = await dl.path();
    return { dl, name: dl.suggestedFilename(), text: p ? fs.readFileSync(p, 'utf8') : '' };
  };

  const first = await grab();
  check('点一次确实产生了一次下载（旧版在某些浏览器上点了没反应）', first.dl !== null, first.name);
  check('文件名是 retrieval-groups.csv', first.name === 'retrieval-groups.csv', first.name);
  /* ⚠️ 下面三条（BOM / 表头 / 行列数）**曾经全部恒真**：`check()` 的第二参数走
     `Boolean(cond)`（见文件顶部），而这三条把**被测值**写在第二参数、把**期望值**写在第三参数——
     第三参数只负责打印，从不参与判定。于是 `Boolean(65279)`、`Boolean('bm25_weight,...')`、
     `Boolean(10)` 一律为真 ⇒ 这三种坏法**在这一趟**都照样全绿（范围要说准：BOM 与逗号转义
     另有 `format.test.cjs:140-141` 在纯函数层钉着，会在那边变红；而"这一页的表头是那 10 列、
     列序不许动"此前**全仓无人钉**，只有这里的 `lines[0] === '...'` 能挡）。
     修法就是把比较写回第二参数（期望值仍是那一串，逐字没动）。
     与前件一起看：`lines.length >= 2` 是**必需**的——只有一行表头的 CSV 会让 `lines[1]` 变 undefined，
     `.split` 直接抛异常，那是"崩"不是"红"，判据要能区分这两件事。
     两组负面对照（改产品代码 `format.ts`，不是改判据）实测读数与归因记在
     `tools/uicheck/README.md` 的 S 节：去 BOM ⇒ 本条与"表头那 10 列"**一起红**
     （判据本体的 `slice(1)` 预设了 BOM 占一格，两条有耦合，别当成两个独立信号）；
     给数据行多塞一格含逗号的值 ⇒ 只有"行列数"红（`headerCols:10 / dataCols:12`）。
     ⚠️ 这三条的**最终定位**（拍板过，别再来一遍"要么删要么重复钉"）：保留。
     BOM 与转义在单元层 `format.test.cjs:140-141` 钉的是"实现怎么写"；探针层这三条钉的是
     **用户真下载到的那串字节**（走真 blob、真下载事件、真读文件），两层读的是同一份代码但
     中间隔着浏览器 ⇒ 这是**端到端二次确认**，不是重复劳动，也不是冗余可删项。 */
  check('正文以 BOM 打头（Excel 才按 UTF-8 读）', first.text.charCodeAt(0) === 0xfeff, {
    code: first.text.charCodeAt(0),
    hex: Number.isFinite(first.text.charCodeAt(0)) ? `0x${first.text.charCodeAt(0).toString(16)}` : 'NaN（正文为空）',
  });
  const lines = first.text.slice(1).split('\r\n');
  check(
    '表头那 10 列一字不差',
    lines[0] === 'bm25_weight,vector_weight,top_k,total,top1_rate,top3_rate,hit5_rate,mrr,bm25_score_mean,vector_score_mean',
    lines[0],
  );
  check(
    '数据行列数 = 表头列数（没有一个单元格里藏着裸逗号）',
    lines.length >= 2 && lines[1].split(',').length === lines[0].split(',').length,
    {
      rows: lines.length,
      headerCols: lines[0].split(',').length,
      dataCols: lines[1] ? lines[1].split(',').length : null,
    },
  );
  const n1 = await leftovers();
  check('导出之后 anchor 已被摘掉（不攒无主的 <a>）', n1 === 0, n1);

  const second = await grab();
  check('连着导两次都成功（延后的 revoke 各管各的 blob）', second.dl !== null && second.name === 'retrieval-groups.csv', second.name);
  const n2 = await leftovers();
  check('两次之后仍然一个 anchor 不留', n2 === 0, n2);
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

// ------------------------------ T 运行条的播报口 ------------------------------ //
// 报告 B2：整条 `.runbar` 挂着 role="status"，而它里面「最后一条日志 Ns 前」每秒重写一次
// 文本 ⇒ 读屏每秒被打断一次，念出来的还是这一行里唯一在动的那个废数；真正该播的是
// "从 Planner 走到 Executor 了"。现在显示与播报分家：runbar **不是** live region，
// 播报交给一枚常驻的 `[data-live=runbar]`，文本只由「状态 + 当前节点」决定。
// 三件事缺一不可，所以三件都验：
//   ① 结构：runbar 不带 role=status / aria-live，且跳秒那枚没有 live 祖先；
//      播报口两者都带、并且**没有任务时就在场**（live region 必须"先在场、后变文本"
//      才可靠出声 —— 跟着文本一起挂载的 region，多数读屏根本不理）。
//   ② 前件：跳秒这一路这 3.2 秒里真的在动（MutationObserver 当场数，不事后补采）。
//      少了这条，"播报口一次没变"可能只是任务压根没跑起来。
//   ③ 现象：同一窗口里播报口的文本变化 = 0；而取消成功（一次**真的**状态变化）时恰好变 1 次，
//      新文本读得出「已取消」。再钉一条：播报口任何时刻都不含计时串（`\d+s` / 「秒」）。
// 负面对照：把 role="status" 加回 `.runbar` ⇒ ② 与 ③ 同时翻红（跳秒直接记进播报口的账）。
async function passRunbarAnnounce(browser) {
  console.log('\n== T 运行条：每秒跳秒不许变成每秒播报 ==');
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 运行态要自己造：installMocks 默认的详情是**已完成**的 fixture，直接提交会一秒内落终态
     —— 落终态后步骤条整排变「已走完」，`.step.is-active` 永远等不到（第一版就在这超时 20s）。
     这里沿用 P 趟那套：详情恒 running；SSE 第一口 400ms 后给 runningFrames()（含节点事件），
     第二口挂住不 settle。挂住 ⇒ 没有 'restored' ⇒ 不触发对账 ⇒ 观察窗里除了跳秒什么都不该动。 */
  let sseCall = 0;
  await page.route('**/api/tasks/*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...detail, status: 'running', final_answer: null, duration_ms: null }),
    }),
  );
  await page.route('**/sse/tasks/*/*', async (r) => {
    const n = (sseCall += 1);
    if (n > 1) return new Promise(() => {});
    await sleep(400);
    try {
      await r.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
        body: runningFrames(),
      });
    } catch {
      /* 页面已不等 */
    }
  });
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);

  // ---- ① 空载时播报口就得在场（还没有任何文本可读，所以是空串） ----
  const idle = await page.evaluate(() => {
    const el = document.querySelector('[data-live="runbar"]');
    return { present: !!el, role: el?.getAttribute('role') ?? null, live: el?.getAttribute('aria-live') ?? null, text: el ? el.textContent.trim() : null };
  });
  check('前件：还没有任务时播报口已经在 DOM 里（region 不能跟着文本一起挂载）', idle.present === true && idle.text === '', idle);
  check('播报口是 polite 的 status region（不打断、也不静默）', idle.role === 'status' && idle.live === 'polite', idle);

  await page.locator('.composer-input').fill('1024 路摄像头整机功耗怎么估算？给出算式与结果');
  await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();
  await page.waitForSelector('.runbar-last', { timeout: 8000 });
  /* 前件：步骤条真的亮起了一个**当前节点**（播报与屏幕比对的那条要用它）。
     ⚠️ 别拿 `.runbar-last` 当"有日志了"的证据 —— 「等待第一条日志」那一支渲染的是同一枚
     class，第一版就在这行上 8 秒超时（mock 先给的几帧都是 system，节点事件更晚）。 */
  await page.waitForSelector('.runbar .step.is-active', { timeout: 20000 });
  await page.waitForTimeout(600);

  // ---- ① 结构：runbar 不再是 live region ----
  const struct = await page.evaluate(() => {
    const bar = document.querySelector('.runbar');
    const last = document.querySelector('.runbar-last');
    const LIVE = '[role="status"],[aria-live]:not([aria-live="off"])';
    return {
      barRole: bar?.getAttribute('role') ?? null,
      barLive: bar?.getAttribute('aria-live') ?? null,
      lastInLive: Boolean(last && last.closest(LIVE)),
      // 跳秒那枚离最近的 live region 有多远 —— 直接给出那个祖先是谁，翻红时看得见元凶
      lastLiveAncestor: last && last.closest(LIVE) ? (last.closest(LIVE).getAttribute('data-live') || last.closest(LIVE).className || last.closest(LIVE).tagName) : null,
      badge: (document.querySelector('.runbar .status-badge') || {}).textContent?.trim() ?? '',
      activeStep: (document.querySelector('.runbar .step.is-active .s-label') || {}).textContent?.trim() ?? '',
      announced: document.querySelector('[data-live="runbar"]')?.textContent.trim() ?? null,
    };
  });
  check('runbar 自己不带 role=status / aria-live（它是一块显示区，不是播报口）', struct.barRole === null && struct.barLive === null, struct);
  check('每秒重写的那枚读数不在任何 live region 里', struct.lastInLive === false, { lastInLive: struct.lastInLive, why: struct.lastLiveAncestor });
  check('播报内容与屏幕上同源的读数一致（状态 + 当前节点，不是第二份数）', struct.announced === `${struct.badge} · 当前节点 ${struct.activeStep}`, struct);
  check('播报里不含任何计时串（跳秒没被念出去）', /\d+(\.\d+)?\s*(s|秒)/.test(struct.announced || '') === false, struct.announced);

  // ---- ②+③ 同一个观察窗：跳秒在动，播报口不动 ----
  // 先让"断流那一行"挂出来（第一口 SSE 给完 5 帧就结束了 ⇒ 'lost' ⇒ 那条 note 挂载），
  // 再开始数 —— 否则 note 的挂载会落进观察窗，读数就成了"播报口也变了"。
  await page.waitForTimeout(2000);
  await page.evaluate(() => {
    const T = { last: 0, sr: [], other: [] };
    window.__t = T;
    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        const n = m.type === 'characterData' ? m.target.parentElement : m.target;
        if (!n || !n.closest) continue;
        if (n.closest('.runbar-last')) T.last += 1;
        const sr = n.closest('[data-live="runbar"]');
        if (sr) {
          T.sr.push(sr.textContent.trim());
          continue;
        }
        const anyLive = n.closest('[role="status"],[aria-live]:not([aria-live="off"])');
        if (anyLive) T.other.push(`${anyLive.getAttribute('data-live') || anyLive.className}=${anyLive.textContent.trim().slice(0, 30)}`);
      }
    });
    obs.observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await page.waitForTimeout(3200);
  const win = await page.evaluate(() => {
    const T = window.__t;
    return { last: T.last, sr: T.sr.length, srTexts: T.sr.slice(0, 4), other: T.other.slice(0, 4) };
  });
  check('前件：这 3.2 秒里跳秒真的在动（≥2 次文本变化）', win.last >= 2, win);
  check('同一个窗口里播报口一次都没变（每秒播报已止血）', win.sr === 0, win);
  /* 这条才是"每秒播报"的直接计量：窗口内**任何** live region（aria-live=off 除外）
     发生的文本变化都记在这里。role="status" 加回 `.runbar` 的 instant 效果就是这个数
     从 0 变成跟 last 同量级 —— 负面对照实测见 README 的 T 节。 */
  check('窗口内没有任何 live region 被跳秒带动（other = 0，不是"只数播报口"）', win.other.length === 0, win);

  // ---- ③ 真的状态变化时，播报必须出声（不是把 live region 一删了事） ----
  await page.locator('.runbar-actions .ant-btn-dangerous').click();
  await page.waitForTimeout(900);
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await page.waitForTimeout(1400);
  const after = await page.evaluate(() => {
    const T = window.__t;
    return {
      sr: T.sr.length,
      srTexts: T.sr.slice(-2),
      badge: (document.querySelector('.runbar .status-badge') || {}).textContent?.trim() ?? '',
      announced: document.querySelector('[data-live="runbar"]')?.textContent.trim() ?? null,
    };
  });
  check('取消成功 = 一次真的状态变化 ⇒ 播报恰好变一次', after.sr === win.sr + 1, { before: win.sr, after: after.sr, texts: after.srTexts });
  check('播报念得出「已取消」（与徽标同一个口径）', /已取消/.test(after.announced || '') && after.badge === '已取消', { announced: after.announced, badge: after.badge });
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

// ------------------------------ U 答案子树不跟无关重渲染 ------------------------------ //
// 报告 A4①：AnswerView 没有 memo。组件里那串 useMemo 只挡住了**解析**
// （findRepeats / findMathBlocks / 裸序号分块），挡不住 react-markdown 自己那棵 element 树 ——
// 父级每重渲染一次，整篇答案（宽表 + 重复段 + 公式区）就重建一次。
// 计数器是 TaskLogPage 里新加的 <Profiler id="answer">（与 M 趟同一套机制：生产构建里
// React 根本不调 onRender，所以这段插桩不进 dist）。
// 双向，缺前一步后面的"零提交"就是恒真（M 趟同形）：
//   ① 先证计数器活着：换一条**答案文本不同**的任务 ⇒ 必须涨；
//   ② 再证挡得住：静置 3.2 秒 + 展开/收起引用列表 ⇒ 一次都不许涨。
//      ⚠️ ②里必须先证明那两下点击**真的改变了界面**（行数 10 ⇄ 181 真的翻了），
//      否则"计数器没涨"只是没人点着东西。
//      ⚠️ 触发器为什么不是切页签：P1-01 之后结果页签**按需挂载**，切走就是卸载、
//      切回来就是重挂 ⇒ 计数器必涨，那量的已经不是"无关重渲染"了（卸载归 V 趟管）。
async function passAnswerMemo(browser) {
  console.log('\n== U 答案子树：无关重渲染不跟着重建 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  const stamp = Date.now();
  const mk = (id, task, answer, ms) => ({
    task_id: id,
    task,
    status: 'done',
    final_answer: answer,
    error: null, difficulty: 'medium', grade: 'B', score: 8, iterations: 2,
    progress: null, queue: null, tool_calls: 6, tool_failures: 3, cost: 0.0042,
    duration_ms: ms,
    created_at: new Date(stamp - 10 * 60 * 1000).toISOString(),
    updated_at: new Date(stamp).toISOString(),
  });
  const A = mk('task-U-aaaa', '答案甲：宽表那篇', '## 答案甲\n\n单路 42 W × 1024 = 43.0 kW\n\n- 结论：PDU 余量 1.3 倍\n\n| a | b |\n|---|---|\n| 1 | 2 |', 4200);
  const B = mk('task-U-bbbb', '答案乙：只有一段', '完全不同的另一篇答案，只有一段话，没有表格也没有列表。', 3000);
  // 后注册的优先：这两条盖掉 installMocks 的列表 / 详情桩，把"两条答案不同的任务"造出来。
  await page.route('**/api/tasks?*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [A, B], total: 2 }),
    }),
  );
  /* 引用铺到 181 条（E 趟同一手法、同一 fixture）：②的触发器是"展开/收起引用"，
     而折叠按钮**只有越过 10 行才存在** —— 默认 trace 的引用是个位数，
     上一版就在这儿读到 null，那三下点的是空气。 */
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(citedTrace(60)),
    }),
  );
  await page.route('**/api/tasks/*', (r) => {
    const hit = r.request().url().includes('task-U-bbbb') ? B : A;
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hit) });
  });

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(900);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(600);

  /* 两枚数一起读：
     renders  = AnswerView 函数体跑了几遍（组件内自数）——**判定看这个**
     commits  = 外面那枚 <Profiler id="answer"> 的提交数 —— 只打印
     ⚠️ 为什么不用 commits 判定：实测切四次页签 commits 从 3 涨到 7，而答案的 DOM 节点
     始终没换（sameNode=true）—— 父级重渲染时 Profiler 自己就是一次 commit，
     memo 挡得住子组件、挡不住 Profiler。拿它判定会把"修好了"读成"没修"。 */
  const led = () =>
    page.evaluate(() => {
      const r = window.__renders || {};
      return {
        renders: r.answerRenders ?? -1,
        commits: r.answer ?? -1,
        // 整页函数体的计数：②里用它证明"触发器真的推动了 React"，不然"答案没涨"可以是恒真
        page: r.page ?? -1,
      };
    });
  const shown = () => page.evaluate(() => (document.querySelector('.answer') || {}).innerText?.replace(/\s+/g, ' ').trim().slice(0, 24) ?? null);
  const n0 = await led();
  const t0 = await shown();
  check('前件：答案真渲染了（.answer 在场且读得出正文）', typeof t0 === 'string' && /答案甲/.test(t0 || ''), t0);
  check('前件：插桩挂上了（render 计数是有值的数字，不是死桩）', n0.renders >= 1, n0);

  // ---- ① 反向：换一条答案不同的任务，计数器必须涨 ----
  /* ⚠️ 必须重新点一次「运行结果」：selectTask 里有 `setTab('log')`（切任务把页签拨回日志
     是刻意的），而结果页签现在**按需挂载** —— 不点回来 `.answer` 根本不在 DOM 里。
     上一版就在这儿读到 t1=null：不是答案没换，是那块面板压根没挂。 */
  await page.locator('.tsk-item').nth(1).click();
  await page.waitForTimeout(1000);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(700);
  const n1 = await led();
  const t1 = await shown();
  check('前件：选中任务后屏幕上是一篇新答案', /另一篇答案/.test(t1 || '') && t1 !== t0, { t0, t1 });
  check('答案文本真的变了 ⇒ render 计数必须涨（这一步不涨就是计数器坏了）', n1.renders > n0.renders, { before: n0.renders, after: n1.renders });

  // ---- ② 挡得住：静置 + 无关交互（不卸载的触发器） ----
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(1000);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(700);
  const base = await led();
  await page.waitForTimeout(3200);
  const idle = await led();
  check('静置 3.2 秒（终态任务、没有计时器）：答案一次都没重渲染', idle.renders === base.renders, { base, idle });
  check(
    '同一个窗口里整页也一次没跑（终态没有秒表 ⇒ page 计数该是平的；运行态那一半在 V 趟）',
    idle.page === base.page,
    { base, idle },
  );

  /* 无关重渲染的触发器选的是**展开 / 收起引用列表**，不是切页签（P1-01 之前用的是切页签）：
     结果页签现在按需挂载，切走是卸载、切回来是重挂 ⇒ 计数必涨，那量的已经不是"无关重渲染"。
     展开引用改的是**页面** state（citationsOpen）⇒ 整页与 ResultPane 都重渲染，而答案文本
     一个字没变 —— 正是 memo 该挡住的那一类，也是当年 A4① 报的那个真实场景。
     ⚠️ 前件仍不能省：折叠按钮只有引用 >10 才渲染，点空了这趟就是恒真。 */
  const citeBtn = page.locator('.cite-more');
  const rowsOf = () => page.locator('.result-wrap .list-row').count();
  const btnCount = await citeBtn.count();
  const r0 = await rowsOf();
  check('前件：结果页签在场、折叠态恰好铺 10 行（<10 行的 fixture 点不到按钮）', r0 === 10, { r0 });
  check(
    '前件：展开按钮只有一枚（用 .cite-more 而不是 .code-more —— 答案里那枚「收起重复段」文案同样含「收起」，会误点）',
    btnCount === 1,
    btnCount,
  );
  await page.evaluate(() => {
    const el = document.querySelector('.answer');
    if (el) el.__u = 1; // 节点身份标记：被卸载重挂过就没了
  });
  const before = await led();
  await citeBtn.first().click();
  await page.waitForTimeout(700);
  const midRows = await rowsOf();
  await citeBtn.first().click();
  await page.waitForTimeout(700);
  const after = await led();
  const afterRows = await rowsOf();
  const same = await page.evaluate(() => {
    const el = document.querySelector('.answer');
    return {
      present: !!el,
      sameNode: Boolean(el && el.__u === 1),
      selected: Array.from(document.querySelectorAll('[role="tab"][aria-selected="true"]')).map((t) => t.textContent.trim()),
    };
  });
  check(
    '前件：那两下点击真的改了界面（行数 10 ⇄ 181 翻了，页签仍停在运行结果）',
    same.present && midRows === 181 && afterRows === 10 && /运行结果/.test(same.selected.join('|')),
    { present: same.present, midRows, afterRows, selected: same.selected },
  );
  check('答案节点没被卸载重挂（同一个 DOM 节点，标记还在）', same.sameNode === true, same);
  check(
    '前件：整页确实重渲染了（page 在涨 —— 答案没涨才是 memo 挡的，不是没人渲染）',
    after.page > before.page,
    { before, after },
  );
  check('父级重渲染 ×2（展开 + 收起）：答案一次都没重渲染（memo 挡得住）', after.renders === before.renders, { before, after });
  console.log('   Profiler 读数（只打印，不判定）：', JSON.stringify({ before: before.commits, after: after.commits }));
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

// ------------------------------ V 秒表隔离与页签按需挂载 ------------------------------ //
// 报告 A4②③（P1-01）的三刀，各钉一条，判定全用**组件内自数 render**（P0-13 那个量具坑：
// Profiler 数的是提交，父级每渲染一次它就是一次 commit，memo 与卸载都挡不住它）：
//   ① 1Hz 关进 Elapsed：运行中静置 2.8 秒，`elapsed` 必须涨（秒表还在跳），而 `page`
//      （整页函数体）一次都不许多跑。旧写法是页面自己持有 now state ⇒ 这一条每秒涨一次，
//      把日志虚拟列表、结果页的 markdown 全牵着重协调。
//   ② 结果 / 工具页签按需挂载：没点过的面板在 DOM 里**根本不存在**（不是隐藏），
//      切走之后也不留在原地；引用行那一千多个元素不再常驻。
//   ③ 前件双向：先证插桩是活的（点一下关键字 ⇒ page 必涨、计数器不是死桩），
//      再证它静置时不涨；少了①这一半，"零增长"可以是恒真。
//
// 负面对照四枚，本轮都真跑过（跑完即撤，工作树里已无残留）：
//   N1 把 1Hz 墙钟搬回页面（`useState` + `setInterval(1000)`，props 仍稳定）⇒
//      「跳秒不牵整页」翻红（page 24 → 30、elapsed 30 → 48）、「挂载着静置」翻红
//      （resultPane 8 → 12）；U 趟那两条"静置不涨"同时翻红（同一病根）。
//      ⚠️ 但「跳秒也不牵日志面板」**不红**（16 → 16）—— 面板还有 P0-13 那层 memo 挡着。
//   N4 在 N1 之上再把 prop 恢复成"每秒算好的时长"（`startedAt={createdAt + tick}`，旧 API 形状）
//      ⇒ 面板那枚才翻红：logstreamRender 22 → 28（同窗口 page 26 → 32）。
//      ⇒ A4② 的原病根是**"prop 每秒变"**，不是"页面每秒渲染"本身：两个条件缺一个都打不红
//      面板计数。只跑 N1 会拿到一个假的"已覆盖"，所以这枚必须单独跑一遍。
//   N2 挂载守卫拆成 `(tab === 'result' || true)`（= AntD 默认的"挂过就常驻"）⇒
//      切走要卸载 / 从不同时在场 / 无残留 / 挂载着静置 四条全红，
//      其中"无残留"读到 m3.all = 845 vs m0.all = 398（看过一次之后常驻 447 个节点）；
//      ⚠️ 而"没点过 ⇒ 不在 DOM 里"那条**不红** —— rc-tabs 对从没激活过的面板本来就不建
//      children，所以它是必要条件不是判据（下面那处注释已按这个口径改过）。
//   N3 `memo(…, () => false)` ⇒ U 趟「父级重渲染 ×2：答案不重渲染」翻红（renders 24 → 32，
//      同窗口 page 40 → 48：父级只渲染 4 遍，答案跟着跑了 8 遍 = StrictMode 双跑）。
//   ⚠️ 面板那一判据最早读的是外层 `<Profiler id="logstream">` 的提交数，"修好了"的状态下
//      照样 15 → 18 红着：Profiler 连**子树里的嵌套更新**也回调，页脚那枚 `<Elapsed>`
//      每秒就是一次。与 P0-13 在 AnswerView 上踩的是同一个量具坑（第二次），改用组件自数。
async function passTickerAndMount(browser) {
  console.log('\n== V 秒表隔离 + 结果/工具页签按需挂载 ==');
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  const led = () =>
    page.evaluate(() => {
      const r = globalThis.__renders || {};
      const v = (k) => (k in r ? r[k] : -1); // -1 = 这个组件从来没渲染过（不是 0，看得出差别）
      return {
        page: v('page'),
        elapsed: v('elapsed'),
        resultPane: v('resultPane'),
        // 日志面板**自己**的函数体计数（不是 Profiler 的提交数，理由见上面那段 ⚠️）
        logstreamRender: v('logstreamRender'),
      };
    });

  /* ---- ① 运行中：秒表在跳，整页不跟着跳 ----
     桩与 T 趟同一套：详情恒 running（默认 fixture 是**已完成**的，直接提交会一秒落终态，
     终态后不挂计时器 ⇒ 想测的现象根本不会出现）；SSE 第一口给 runningFrames()，第二口挂住。 */
  let sseCall = 0;
  await page.route('**/api/tasks/*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...detail, status: 'running', final_answer: null, duration_ms: null }),
    }),
  );
  await page.route('**/sse/tasks/*/*', async (r) => {
    const n = (sseCall += 1);
    if (n > 1) return new Promise(() => {});
    await sleep(400);
    try {
      await r.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
        body: runningFrames(),
      });
    } catch {
      /* 页面已不等 */
    }
  });
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await sleep(500);
  await page.locator('.composer-input').fill('1024 路摄像头整机功耗怎么估算？给出算式与结果');
  await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();
  await page.waitForSelector('.runbar .step.is-active', { timeout: 20000 });
  await page.waitForSelector('.runbar-last', { timeout: 8000 });
  // 等断流那一行挂出来（第一口给完帧就结束 ⇒ 'lost' ⇒ stream-note 挂载），别落进观察窗
  await sleep(2600);

  const rPre = await led();
  /* 页签调换之后这一段的"谁没挂载"整个翻了个面：提交落在**结果页**，所以
     `resultPane >= 1` 才是前件；而日志面板从没激活过 ⇒ `logstreamRender === -1`。
     ⚠️ 必须先读这一份再点开日志页签：不点开的話下面那两条"零重渲染"是恒真的
     （-1 === -1 说明不了任何事，面板压根不在场）。 */
  check(
    '① 前件：提交后落在「运行结果」⇒ ResultPane 已挂载（>=1），而日志面板一次都没渲染过（-1）',
    rPre.resultPane >= 1 && rPre.logstreamRender === -1,
    rPre,
  );
  await openLogTab(page);
  await sleep(400);

  const r0 = await led();
  await sleep(2800);
  const r1 = await led();
  check(
    '前件：秒表真的在跳（2.8 秒里 Elapsed 自己跑了 ≥2 遍，不是停了计时器）',
    r1.elapsed - r0.elapsed >= 2,
    { r0, r1 },
  );
  check('跳秒不牵整页：同一个窗口里 TaskLogPage 函数体一次都没多跑', r1.page === r0.page, {
    r0,
    r1,
  });
  /* 直接钉住 LogStream 头注释里那句"面板不陪秒表重渲染"：读的是**面板子树的提交数**
     （外层 `<Profiler id="logstream">` 记的，与 M 趟同一枚），下面改关键字那一笔是它的
     反证 —— 计数器坏了时上面那条会恒真。
     这一条现在另有第二重恒真风险：面板没挂载时两头都是 -1。所以判据里带上 `>= 0`，
     把"根本没挂上"这种假绿先摘掉。 */
  check(
    '跳秒也不牵日志面板：这一窗里面板自己一次都没重渲染（且它确实在场，读数 >=0）',
    r1.logstreamRender === r0.logstreamRender && r1.logstreamRender >= 0,
    { r0, r1 },
  );
  // 反证：计数器是活的 —— 页面状态一变它立刻涨。少了这一步，上面那条"零增长"是恒真。
  await page.getByLabel('日志关键字过滤').fill('PoE');
  await sleep(400);
  const r2 = await led();
  check(
    '正件：改一次关键字过滤 ⇒ page 立刻涨（插桩活着，上面的零增长不是死表）',
    r2.page > r1.page,
    { r1, r2 },
  );
  check(
    '正件：同一笔改动里面板自己重渲染了（上面那条"零渲染"不是因为计数器坏了）',
    r2.logstreamRender > r1.logstreamRender,
    { r1, r2 },
  );

  /* ---- ② 按需挂载：另一段用**已完成**的默认 fixture（结果页要有东西才谈得上挂载） ---- */
  const ctx2 = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx2.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const p2 = await ctx2.newPage();
  p2.on('pageerror', (e) => errors.push(e.message));
  await installMocks(p2);
  // 引用铺到 181 行：不这么做，"卸载省下了多少节点"根本没有量感
  await p2.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(citedTrace(60)),
    }),
  );
  const led2 = () =>
    p2.evaluate(() => {
      const r = globalThis.__renders || {};
      const v = (k) => (k in r ? r[k] : -1);
      const q = (s) => document.querySelectorAll(s).length;
      return {
        page: v('page'),
        resultPane: v('resultPane'),
        // 面板自己的函数体计数（①里那枚同名读数），用来证"点开了才建、建过就常驻"
        logstreamRender: v('logstreamRender'),
        resultWrap: q('.result-wrap'),
        citeRows: q('.list-row'),
        toolCards: q('.tool-card'),
        logBody: q('.log-body'),
        all: q('*'),
      };
    });
  await p2.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await sleep(500);
  await p2.locator('.tsk-item').first().click();
  /* 打字机的**反面**（本轮新增的一条口径）：这一条是列表里点开的**历史**任务，不是本次看着跑的
     ⇒ 答案必须一上来就是整段。逐字敲出来是在演"正在生成"，而它早就躺在库里了。
     ⚠️ 判据写法换过一次，两版都留在这儿是因为第二版才是能红的那版：
       第一版"点开 800ms 后读一次长度、判 len > 50"是恒真的 —— 动画播到那一拍已经吐出六成，
       负面对照 NC-AF2（把 `revealed` 写成恒 false，等于所有任务都重播）当场放过去。
       现在的口径是**两次读数相减**：刚挂载那一拍 vs 静置 1.6 秒之后，一字不差才算"没在播"。
     ⚠️ 必须放在 m0 之前测：m0 前面本来就有 1.2 秒的等待，动画（1.5 秒）都在那一拍里跑完了，
     放在后面测就等于测了个已经落定的现场。 */
  await sleep(200);
  const early = await p2.evaluate(() => (document.querySelector('.answer')?.textContent || '').trim().length);
  await sleep(1600);
  const late = await p2.evaluate(() => (document.querySelector('.answer')?.textContent || '').trim().length);
  const thinkAgain = await p2.evaluate(() => document.querySelectorAll('.thinking').length);
  check('历史任务不重播打字机：刚点开那拍与静置 1.6 秒之后一字不差（也没有"正在思考"那一行）',
    early === late && early > 50 && thinkAgain === 0, { 刚点开: early, 静置后: late, 思考行: thinkAgain });
  await sleep(500);

  const m0 = await led2();
  /* 页签调换（2026-09-28）之后这一段整个翻了个面：**结果页是默认页，日志页才是没点过的那个**。
     旧版钉的是"选中任务停在实时日志、结果页一行都不在"，同一套形状反过来钉 ——
     按需挂载这条规矩没变，变的是首屏挂的是哪一块。 */
  check(
    '前件：选中任务后停在「运行结果」（默认页签就是它；点列表换任务**不**抢页签，见 W 趟 ⑤）',
    m0.resultWrap === 1 && m0.logBody === 0 && m0.toolCards === 0,
    m0,
  );
  /* ⚠️ 与旧版同一句口径：这一条**不是**"按需挂载"的判据，只是它的必要条件 ——
     rc-tabs 对从没激活过的面板本来就不渲染 children。真正被负面对照打红的是下面那几条
     "切走要卸载 / 不许有残留"。记在这儿是因为口径要准。 */
  check(
    '日志页签没点过 ⇒ 终端一行都不在 DOM 里（必要条件；充分条件见下面"切过去再切回来"那几条）',
    m0.logBody === 0,
    m0,
  );
  check('结果页是默认页 ⇒ 引用折叠态照样只有 10 行（首屏就挂 181 行是旧版就修掉的东西）', m0.citeRows === 10, m0);

  await openLogTab(p2);
  await sleep(500);
  const m1 = await led2();
  check(
    '点开日志页签：终端在场，而结果页整个**卸载**（.result-wrap 归零、10 行引用一起走）',
    m1.logBody === 1 && m1.resultWrap === 0 && m1.citeRows === 0,
    m1,
  );
  check(
    '日志面板的 render 计数从 -1 变成 ≥1（插桩真的走了一遍挂载，不是读数字段写错）',
    m1.logstreamRender >= 1,
    m1,
  );
  /* 这里一度加过一条"第一次点开就停在最后一条"的钉底判据，量出来 max=0 ⇒ 那一版是**恒真**的，
     已删。原因记下来免得再犯：V 趟这份 trace 是 61 条**同一形状**的工具事件，日志面板把它们
     合并成 1 行（页脚「已显示 1 行 / 61 条 · 合并重复 60 条」），面板没有可滚内容 ⇒
     `scrollHeight - clientHeight = 0`、`scrollTop` 也只能是 0 ⇒ `top >= max - 2` 永远成立。
     "带行第一次挂载要不要钉底"这条规矩的判据本体在 **J 续（passCollapsedFocus）**：那一趟的
     页面上方有别的展开内容，`.log-body` 实测 overflow=2591 ⇒ 同一个读数才有真假可言。 */

  await p2.getByRole('tab', { name: /工具调用/ }).click();
  await sleep(800);
  const m2 = await led2();
  check(
    '切到工具页签：工具卡在场，结果页仍不在场（引用行为 0）',
    m2.toolCards >= 1 && m2.citeRows === 0 && m2.resultWrap === 0,
    m2,
  );
  /* 这一条是**故意留着**的口径差：日志面板激活过一次之后 AntD 只是把它隐藏（pane 还在 DOM 里），
     而结果页与工具页是我们自己写的"不激活就不建"。两种处理都真实存在，写明差额来源，
     免得下一个读数的人把 logBody===1 当成"按需挂载失效了"去"修"它。 */
  check(
    '日志面板激活过一次就常驻（AntD 的隐藏 ≠ 卸载；结果页/工具页才是我们自己卸的那两处）',
    m2.logBody === 1,
    m2,
  );

  await p2.getByRole('tab', { name: '运行结果' }).click();
  await sleep(900);
  const m3 = await led2();
  check(
    '回到结果页签：又挂了一遍（计数在涨、引用行照旧只有折叠的 10 行）、工具卡整块走了',
    m3.resultWrap === 1 && m3.citeRows === 10 && m3.toolCards === 0 && m3.resultPane > m0.resultPane,
    { rp0: m0.resultPane, rp3: m3.resultPane, m3 },
  );
  /* 结果页挂上时元素数必须**明显上涨**（这是"它真的建了那 10 行引用 + 整棵 markdown 树"的
     正面读数，与下面"卸干净"那条配成双向：只钉一头的话，"从来不建"和"卸不掉"都能蒙过去）。
     ⚠️ 基线取 m1（日志在场、结果与工具都不在场）而不是 m2：m2 那一刻工具页签的 61 张卡
     还挂着（3,256 个元素），拿它当"没结果"的基线比，结果页反而更小 —— 上一版就是这么红的。 */
  check(
    '结果页挂上时元素数明显上涨（引用 10 行 + 指标 + markdown 树 ≫ 200 个节点）',
    m3.all > m1.all + 200,
    { m1all: m1.all, m3all: m3.all },
  );
  await p2.getByRole('tab', { name: '实时日志' }).click();
  await sleep(800);
  const m4 = await led2();
  /* 卸载要"卸干净"：AntD 会在原地留一个空的 pane 容器，那是它的结构，不算残留；
     真的残留是内容 —— 所以拿"同样两块重面板都不在场"的两档比：
     m1（第一次点进日志，结果页刚被卸）与 m4（又切回来一次，结果页第二次被卸）。
     ⚠️ 旧版比的是 m3 与 m0，那时 m0 是"日志在场 + 结果没点开过"，与"日志在场 + 结果刚卸掉"
     同形；页签调换之后 m0 变成"结果在场"，拿它当基线必红，所以基线挪到 m1。
     ±20 容的是空 pane 容器那一点差异（上一版实测：工具页签 61 张卡 vs 折叠 10 行引用
     差 3,230 vs 806，那种量级的差才是真残留）。 */
  check(
    '第二次切走之后文档里没有残留（元素数与"结果页从没挂过"那一档齐平）',
    m4.resultWrap === 0 && Math.abs(m4.all - m1.all) <= 20,
    { m1all: m1.all, m4all: m4.all, m4 },
  );

  /* 挂载着静置：先把结果页签点开（此刻它在 m4 之后又被卸掉了），再静置 2.2 秒。
     这一条与①同形，只是把"不激活所以不渲染"和"渲染了但没人推动"分开钉。 */
  await p2.getByRole('tab', { name: '运行结果' }).click();
  await sleep(900);
  const s0 = await led2();
  await sleep(2200);
  const s1 = await led2();
  check('挂载着静置 2.2 秒：ResultPane 与整页一动不动', s1.resultPane === s0.resultPane && s1.page === s0.page, {
    s0,
    s1,
  });
  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx2.close();
  await ctx.close();
}

/* 第二十三趟（W）：现场丢了没有 —— 「在看哪条任务」落到地址栏之后，重载 / 手敲 / 后台切回
   三条路径都必须能把它捡回来。
   为什么单独一趟：用户实测到的现象是"切走 30 秒再回来，主区变空态"，而左侧列表照旧显示
   运行中。诊断结论是 state 丢失（选中态只活在组件内存里，列表是重新拉的），
   不是 visibilitychange 副作用、也不是 SSE 边界 —— 那两条在 ④ 里被当成断言钉住，
   而不是只写在诊断里。诊断的两枚仪器化实Readings（E1/E2）已进 README。
   ⚠️ 本趟刻意**不**断言"reload 之后页签也回来"：页签是内存态，重载必丢，
   这是事实而不是缺陷（要保页签得再挂一个 query 参数，另案）。 */
async function passUrlRestore(browser) {
  console.log('\n== W 选中态落到 URL：重载 / 换任务 / 后台切回 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  /* 三个计数器就是这一趟的判据本体：不看界面猜"有没有补拉"，直接数打出去几条。 */
  let detailHits = 0;
  let traceHits = 0;
  let sseHits = 0;
  page.on('request', (r) => {
    const u = r.url();
    if (/\/sse\/tasks\//.test(u)) sseHits += 1;
    else if (/\/api\/tasks\/[^/]+\/trace/.test(u)) traceHits += 1;
    else if (new RegExp(`/api/tasks/${TASK_ID}(\\?|$)`).test(u)) detailHits += 1;
  });
  const tally = () => ({ detailHits, traceHits, sseHits });

  const traceOf = (count, who) => ({
    task_id: TASK_ID,
    total: count,
    items: Array.from({ length: count }, (_, i) => ({
      event_seq: i + 1,
      event_type: i === count - 1 ? 'running' : 'node_update',
      node: ['planner', 'executor', 'reviewer'][i % 3],
      status: 'running',
      /* `tool_name` 是唯一能被 `traceToLogEvents`(:296-305) 原样带进 message 的字段 ——
         写 `payload.step` 那版量不到：那一支根本没人读，行文案退成通用的「节点更新」，
         于是"换过去之后首行含另一条"恒假。而通用文案 + 相邻同文还会被 collapseRepeats
         合并 ⇒ 行数也会少。给每行一个不同串，两件事一起解决。 */
      tool_name: `${who} 步骤 ${String(i + 1).padStart(3, '0')}`,
      observation: null,
      payload: {},
      created_at: new Date(Date.now() - 60_000 + i * 100).toISOString(),
      error_code: null,
      error_message: null,
    })),
  });

  /* 首连的 6 帧真事件 —— 每一步的消息都不同，`collapseRepeats` 合不到一起去，
     所以"重载前 6 行 / 重载后 ≥6 行"这一比才是实的。 */
  const sseHeaders = { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' };
  const sseSixFrames = () => {
    const t0 = Date.now();
    const nodes = ['planner', 'executor', 'reviewer'];
    let out = `event: snapshot\ndata: ${JSON.stringify({
      task_id: TASK_ID,
      seq: 0,
      node: 'system',
      ts: new Date(t0).toISOString(),
      update: { status: 'running' },
    })}\n\n`;
    for (let i = 1; i <= 6; i += 1) {
      out += `event: node\ndata: ${JSON.stringify({
        task_id: TASK_ID,
        seq: i,
        node: nodes[i % 3],
        ts: new Date(t0 + i * 80).toISOString(),
        update: { message: `SSE 帧 ${String(i).padStart(3, '0')}` },
      })}\n\n`;
    }
    return out;
  };

  await installMocks(page);
  await page.route('**/api/tasks', (r) =>
    r.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: TASK_ID,
        status: 'queued',
        stream_url: `/tasks/${TASK_ID}/stream`,
        poll_url: `/tasks/${TASK_ID}`,
        cancel_url: `/tasks/${TASK_ID}/cancel`,
        queue_position: null,
        submitted_at: new Date().toISOString(),
        estimated_cost_cny: 0.0042,
        warnings: null,
      }),
    }),
  );
  // ⚠️ trace 必须单独注册成「api/tasks/星/trace星」这一条。上一版把 trace 塞在
  // 「api/tasks/星」里面靠 url 含不含 "/trace" 分流 —— Playwright 的单个 `*` **不跨 `/`**，
  // 那条 glob 根本匹配不到 /api/tasks/{id}/trace?after_seq=… ，于是答案落回 installMocks
  // 那份默认 trace：⑤ 量到"换了任务还是本尊的十行"，那是桩没接上，不是产品分叉。
  // （同一个坑在 B 趟的 cancel 分支上记过一次，这是第二次 —— 所以这一段刻意用行注释：
  //  块注释里写 glob 会被串中间的 星斜杠 提前闭合，node --check 也不报错。）
  await page.route('**/api/tasks/*/trace*', (r) => {
    const u = r.request().url();
    const who = u.includes(TASK_ID) ? '本尊' : '另一条';
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(traceOf(who === '本尊' ? 9 : 5, who)),
    });
  });
  await page.route('**/api/tasks/*', (r) => {
    const u = r.request().url();
    if (u.includes('/cancel')) return r.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    /* 坏 id 必须真 404。上一版对任何 id 都回详情，"手敲一个不存在的 task_id"那一档
     量到的是 11 行日志 —— 桩在骗人。 */
    if (u.includes('task-bad')) {
      return r.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'TASK_NOT_FOUND', detail: '任务不存在：坏 id' }),
      });
    }
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...detail,
        task_id: u.includes(TASK_ID) ? TASK_ID : 'task-other',
        status: 'running',
        final_answer: null,
        duration_ms: null,
      }),
    });
  });
  /* 首连给 6 帧真事件，之后每一条挂住不答。
     ① 首连必须有帧：③ 的判据是"重载之后的行数 ≥ 重载前"，重载前若是 0 行，
        那条 ≥ 恒真（上一版就是这么个假绿：`before3: 0` 直接把前件写红了，看得见是运气好）。
     ② 后面的连接一律挂住：让 mock 立即 fulfill 等于"服务端关流" ⇒ onerror ⇒ 1 秒重连 ⇒
        每接上的第一帧又各打一次整包 trace，⑦ 里"我这一次补拉"根本择不出来。 */
  let sseRound = 0;
  const hangs = [];
  await page.route('**/sse/tasks/*/*', async (r) => {
    sseRound += 1;
    if (sseRound === 1) {
      return r.fulfill({ status: 200, headers: sseHeaders, body: sseSixFrames() });
    }
    await new Promise((res) => hangs.push(res));
    return undefined;
  });

  const snap = () =>
    page.evaluate(() => {
      const q = (s) => document.querySelector(s);
      const txt = (s) => (q(s) ? q(s).textContent.trim() : null);
      return {
        search: location.search,
        /* 行数**只数页签上那枚计数**：`.log-row` 在结果页签激活时根本不在 DOM 里
           （P1-01 的按需挂载），于是 ⑤ 量到 rows=0 —— 那不是没恢复，是没渲染。
           页签计数读的是同一份 logRows（TaskLogPage:1049），且不依赖面板挂没挂。 */
        rows: Number(q('.ant-tabs-tab .tab-count')?.textContent ?? 0),
        firstRow: (q('.log-row') ? q('.log-row').textContent.trim() : '').slice(0, 24),
        idle: txt('.log-idle-title'),
        idleDesc: (txt('.log-idle-desc') || '').slice(0, 30),
        runbar: (txt('.runbar') || txt('.sb-idle') || '').slice(0, 30),
        /* 当前页签名：把空白挤掉再截前四个字 —— 日志与工具那两枚 label 里带着
           `.tab-count`（「实时日志 13」「工具调用 8」），旧版 slice(0,8) 量到的是
           「工具调用 8」这种带尾巴的串，判 `=== '工具调用'` 必红。四个字正好是
           三枚页签名的共同前缀（运行结果 / 实时日志 / 工具调用）。 */
        tab: (txt('.ant-tabs-tab-active') || '').replace(/\s+/g, '').slice(0, 4),
        /* 页签调换之后"主区是不是空态"这一句有了**两个**读点：
           默认那一屏（运行结果）的空态标题，与点进日志之后那句「还没有日志」。
           两份都读，是因为 ① 与 ⑥ 分别要证的是"眼前这一屏说得出真相"和
           "隔壁那一屏也没有说谎" —— 只读其中一个，另一个屏空着就没人管了。 */
        resultEmpty: txt('.result-wrap .empty-title') ?? txt('.empty-title'),
        thinking: Boolean(q('.thinking')),
        /* 跑动中那一屏的"这一屏会给出什么"（2026-09-29 起的形状，见 ② 那条判据的注释）：
           阶段条 + 骨架屏/流式区 + 页脚那一句交代。三份都读是因为它们各说一件事，
           少读一份就可能"屏上只剩三点"却全绿。 */
        rp: Boolean(q('.rp')),
        rpStages: document.querySelectorAll('.rp-stage').length,
        rpSkel: document.querySelectorAll('.rp-skel .skeleton').length,
        rpFoot: (txt('.rp .result-meta') || '').replace(/\s+/g, ' ').slice(0, 40),
        title: document.title,
        activeIsTop: (() => {
          const list = Array.from(document.querySelectorAll('.tsk-item'));
          const i = list.findIndex((el) => el.classList.contains('is-active'));
          return i < 0 ? null : i;
        })(),
        /* 高亮那行的**身份**（不是位置）：选中态落到 URL 之后，"地址栏 == 高亮行"这句话
           只能拿 id 比，拿位置比就又回到靠文案猜了。 */
        activeIds: Array.from(document.querySelectorAll('.tsk-item.is-active')).map((el) =>
          el.getAttribute('data-task-id'),
        ),
      };
    });

  /* ---------------- ① 首屏没有 query ⇒ 不许自动选最新 ---------------- */
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  const s0 = await snap();
  check('① 前件：地址栏干净（无 query）', s0.search === '', s0.search);
  /* 页签调换之后"主区是空态"这句话要落在**默认那一屏**上：没选中任务时结果页给的是
     「还没有运行结果」那份引导（旧版读的是日志那一屏的「还没有日志」）。
     隔壁那一屏的说法也照读，见下面 ①b。 */
  check('① 没 query 就不自动选：默认那一屏是空态引导、列表无高亮',
    s0.resultEmpty === '还没有运行结果' && s0.activeIsTop === null, s0);
  check('① 空态那一屏不挂"正在思考"（没提交就没有在跑的东西）', s0.thinking === false, s0);
  check(
    '① 首屏 2 秒内一条详情/轨迹都不许白打（没选中就没得拉）',
    detailHits === 0 && traceHits === 0,
    { detailHits, traceHits },
  );
  check('① 空态时标题栏不许带点（没在跑就没信号）', !s0.title.startsWith('●'), s0.title);
  await openLogTab(page);
  const s0b = await snap();
  check('①b 隔壁那一屏（实时日志）在同一件事上说同样的话：还没有日志', s0b.idle === '还没有日志', s0b.idle);

  /* ---------------- ② 提交：URL 写入，且不许被跟随 effect 重拉 ---------------- */
  const t2 = tally();
  await page.fill('textarea.composer-input', 'W 趟：现场能不能捡回来');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(2000);
  const s2 = await snap();
  const d2 = { detailHits: detailHits - t2.detailHits, traceHits: traceHits - t2.traceHits, sseHits: sseHits - t2.sseHits };
  check('② 提交后地址栏出现 task_id（= 本尊，不是别的）', s2.search === `?task_id=${TASK_ID}`, s2.search);
  /* 这条判的是坑 B：提交路径自己已经建好现场（record + SSE + 缓冲），如果跟随 effect 再跑
     一遍 selectTask，就会多打一次详情 + 一整包 trace。SSE 条数**不参与判定** ——
     首连有帧就完，会被判成"服务端关流" ⇒ 退避重连，2 秒内开出第 2 条是正常行为。 */
  check('② 提交之后不许回头重拉：详情 0 / 轨迹 0（多打一次就是被跟随 effect 重跑了）', d2.detailHits === 0 && d2.traceHits === 0, d2);
  check('② 提交确实订上了流（至少一条 SSE）', d2.sseHits >= 1, d2);
  check('② 运行中的任务，标题栏必须带 ●（页面外唯一还读得到的信号）', s2.title.startsWith('●'), s2.title);
  check(
    '② 高亮那一行的 data-task-id 就是地址栏那条（选中态与列表同一枚钢印）',
    JSON.stringify(s2.activeIds) === JSON.stringify([TASK_ID]),
    s2.activeIds,
  );
  /* 提交之后落在哪一屏（本轮的产品口径）：默认页签 = 运行结果，那一屏在跑时挂"思考中"。
     与 B 趟那几条同一条款，只是这里顺带证明"从空态提交"这条路径也一样。
     ⚠️ 这一条的期望值改过**两次**，两次都是被真实产品形状推翻的，都记下来：
       第一版判 `resultEmpty === null` —— 那是我把"有思考态"读成"没有空态插画"，前提就错。
       第二版判 `resultEmpty === '结果会在这一屏逐段出现'` —— 那一句是我这一轮写的 EmptyState
         标题，而并发改进来的 `RunProgress`（components/RunProgress.tsx，非我所写）把跑动中的
         那一支整个换掉了：静态引导三行删了，换成「阶段条 + 骨架屏 + 页脚那句"届时这一屏会整段替换"」。
         量出来 `resultEmpty: null` 就是这一支不再有 EmptyState 的正常读数，不是缺陷。
       现在钉的是**新形状要交代的三件**：思考那一行在、`.rp` 那块在、页脚仍然告诉用户
       "现在看到的是过程、终稿稍后替换" —— 口径没变（跑动中也要说得出接下来会是什么），
       换掉的是承载它的元素。 */
  check('② 提交后停在「运行结果」而不是日志', s2.tab === '运行结果', s2.tab);
  check('② 跑动中的结果页挂着"正在…"那一行，且这一屏仍然交代"待会儿会有什么"（阶段条 + 页脚那句）',
    s2.thinking === true && s2.rp === true && s2.rpStages === 3
      && /整段替换|终稿|增量/.test(s2.rpFoot || ''),
    s2);

  /* ---------------- ③ 重载：现场回来，且只加载一次 ---------------- */
  const before3 = (await snap()).rows;
  const t3 = tally();
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const s3 = await snap();
  const d3 = { detailHits: detailHits - t3.detailHits, traceHits: traceHits - t3.traceHits, sseHits: sseHits - t3.sseHits };
  check('③ 前件：重载前主区是有行的（不然"回来了"无从证明）', before3 > 0, { before3 });
  check('③ 重载后地址栏还是那一条', s3.search === `?task_id=${TASK_ID}`, s3.search);
  /* ⚠️ 读 idle 之前必须先把日志页签点开：调换之后重载落在「运行结果」，面板没挂载时
     `.log-idle-title` 也读不到 ⇒ `idle === null` 会**假绿**（看着像"空态消失了"，其实
     是"整块没渲染"）。这一处是本轮改动给这套判据新挖的坑，写明免得下次又踩。 */
  check('③ 重载后落在默认页签（页签是内存态，重载必丢 —— 本趟本来就不钉它回来）',
    s3.tab === '运行结果', s3.tab);
  await openLogTab(page);
  const s3b = await snap();
  check('③ 重载后空态消失、日志整包回填（trace 9 行 + SSE 挂住不给帧）', s3b.idle === null && s3b.rows >= 9, s3b);
  check('③ 用户给的验收口径：重载之后的行数 ≥ 重载之前', s3b.rows >= before3, { before3, after: s3b.rows });
  check('③ 重载后运行条回到「运行中」（不是停在提交前那句尚未运行）', s3b.runbar.startsWith('运行中'), s3b.runbar);
  check('③ 重载只补一次：详情 1 / 轨迹 1 / 重订 SSE 1', d3.detailHits === 1 && d3.traceHits === 1 && d3.sseHits === 1, d3);

  /* ---------------- ④ 页签不被抢 + 同 id 再点当刷新 ----------------
     这一档在页签调换之后**换了钉法**，而且钉得更狠：
     旧写法是"停在运行结果 ⇒ 点同一条不许被弹回日志"，那只防得住一个方向；
     现在把用户放到**第三个**页签上（工具调用），点同一条之后哪儿都不许去 ——
     配套的产品口径是 selectTask 里那句 `if (prevId !== taskId)`（同一个 id 是刷新，
     不是换任务，刷新不许动人家正看着的那一屏）。 */
  await page.locator('.ant-tabs-tab', { hasText: /工具调用/ }).click();
  await page.waitForTimeout(700);
  const s4pre = await snap();
  check('④ 前件：用户自己切到了第三个页签「工具调用」（页签顺序：结果 / 日志 / 工具）',
    s4pre.tab === '工具调用', s4pre.tab);
  const t4 = tally();
  await page.locator('.tsk-item.is-active').first().click();
  await page.waitForTimeout(1600);
  const s4 = await snap();
  const d4 = { detailHits: detailHits - t4.detailHits, traceHits: traceHits - t4.traceHits };
  check(
    '④ 刷新同一条不许动页签（点的是当前这条 = 刷新，不是换任务）',
    d4.detailHits === 1 && s4.tab === '工具调用',
    { ...d4, tab: s4.tab },
  );
  check('④ 同一个 id 再点一次真的重拉了一遍（旧版这一步什么都不做）', d4.traceHits === 1, d4);

  /* ---------------- ⑤ 换任务：URL 跟着换，重载恢复的是新那条 ---------------- */
  await page.locator('.tsk-item:not(.is-active)').first().click();
  await page.waitForTimeout(1800);
  const s5 = await snap();
  check('⑤ 点另一条 ⇒ 地址栏换成那条的 id', /^task_id=/.test(s5.search.slice(1)) && !s5.search.includes(TASK_ID), s5.search);
  /* 读首行之前先把日志页签点开：此刻停在 ④ 留下的那一屏（调换之后连点同一条都不动页签），
     面板可能根本没挂载（P1-01 的按需挂载），不点开就量到 firstRow="" —— 那会被读成"换任务没换内容"。 */
  await page.locator('.ant-tabs-tab', { hasText: '实时日志' }).click();
  await page.waitForTimeout(700);
  const s5b = await snap();
  check('⑤ 换过去之后是那一条的账：5 行、首行写着「另一条」', s5b.rows === 5 && s5b.firstRow.includes('另一条'), s5b);
  check('⑤ 换一条也不抢页签：用户还站在他自己选的那一页（实测：列表点击只改地址栏，页签不动）',
    s5.tab === '工具调用', s5.tab);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1800);
  /* 重载之后页签回到默认（内存态必丢），首屏又不在日志那一屏 ⇒ 想读"恢复的是哪一条的内容"
     还是得自己点过去。这与 ③ 同一手法，两处各写一句免得看起来像手滑。 */
  await openLogTab(page);
  const s5c = await snap();
  check('⑤ 重载后恢复的是**那一条**（不是永远回到第一条）', s5c.search === s5b.search && s5c.rows === 5 && s5c.firstRow.includes('另一条'), s5c);

  /* ---------------- ⑥ 手敲一个不存在的 id：不许安静装死 ---------------- */
  await page.goto(`${BASE}/tasks?task_id=task-bad`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1800);
  const s6pre = await snap();
  /* 坏 id 现在默认落在「运行结果」那一屏 —— 它得先在那里就说得出话（ResultPane 的 role=alert），
     否则"手敲一个不存在的 id"的人第一眼看到的是一句会让他等下去的谎。 */
  check('⑥ 坏 id 默认那一屏（运行结果）当场报 LOAD_FAILED，不等人去点日志页签',
    s6pre.tab === '运行结果' && await page.evaluate(() =>
      Boolean(document.querySelector('.result-wrap [role="alert"]'))), s6pre);
  await openLogTab(page);
  const s6 = await snap();
  check('⑥ 坏 id：日志页直接说「载入失败」，不许读成「已订阅，等待首个节点事件」', s6.idle === '任务载入失败：LOAD_FAILED', s6);
  check('⑥ 坏 id：补一句下一步干嘛（从列表选 / 新建）', s6.idleDesc.includes('地址栏') || s6.idleDesc.includes('列表'), s6.idleDesc);
  /* "不许无限重试"要的是**静止**：先记一份账，再静置 2.5 秒，期间一条都不许多。
     上一版写成 `traceHits >= 1` —— 那是句恒真的废话（刚加载完必然 ≥1），
     守卫要拦的恰恰是"再来一次"，判据必须打在增量上。 */
  const t6 = { detailHits, traceHits, sseHits };
  await page.waitForTimeout(2500);
  const d6 = { detailHits: detailHits - t6.detailHits, traceHits: traceHits - t6.traceHits, sseHits: sseHits - t6.sseHits };
  check('⑥ 坏 id 静置 2.5 秒不许再打一次（失败也记账，同一个坏 id 不重试）', d6.detailHits === 0 && d6.traceHits === 0 && d6.sseHits === 0, d6);

  /* ---------------- ⑦ 后台 45 秒 → 切回：补一次账，且不清屏 ---------------- */
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.fill('textarea.composer-input', 'W 趟 · 后台切回');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1800);
  const before7 = await snap();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { get: () => true, configurable: true });
    Object.defineProperty(document, 'visibilityState', { get: () => 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const t7a = tally();
  await new Promise((r) => setTimeout(r, 45_000));
  const d7a = { detailHits: detailHits - t7a.detailHits, traceHits: traceHits - t7a.traceHits };
  const t7 = tally();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
    Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(2600);
  /* 补拉完不补清屏，看的是**日志那一屏**：页签调换之后切回前台时人还在「运行结果」上，
     面板没挂载时 `idle === null` 是句空话（读不到 ≠ 没有空态）。点过去再读。
     这一击在 tally 窗口之内、且不产生任何请求 ⇒ 不影响"补拉只补一次"那两条的计数。 */
  await openLogTab(page);
  const after7 = await snap();
  const d7 = { detailHits: detailHits - t7.detailHits, traceHits: traceHits - t7.traceHits };
  check('⑦ 后台那 45 秒里不补拉（补拉是"回到前台"这件事，不是心跳）', d7a.detailHits === 0 && d7a.traceHits === 0, d7a);
  check('⑦ 切回前台补一次账：详情 1 + 轨迹 1（不许拆成两次轨迹）', d7.detailHits === 1 && d7.traceHits === 1, d7);
  check(
    '⑦ 补拉只许盖回去、不许清屏：行数不降、空态不出现',
    after7.rows >= before7.rows && after7.idle === null,
    { 切走前: before7.rows, 切回后: after7.rows, 空态: after7.idle },
  );
  check('⑦ 切回后仍在运行态（徽标停在切走那一刻就是谎报）', after7.runbar.startsWith('运行中'), after7.runbar);

  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  hangs.splice(0, hangs.length).forEach((r) => r());
  await ctx.close();
}

/* 趟 X：宽表的横向滚动区（走查报告 EV-01，P0）。
 *
 * 钉三件事，每件都只在真机上露脸：
 *  ① 横向滚动**收回到自己这层**。AntD 对带 `scroll={{ x }}` 的表把 `overflow-x:auto`
 *    写成**行内样式**打在 `.ant-table-content` 上 ⇒ 选择器写多深都抢不动，必须 !important。
 *    没收回来的症状很隐蔽：外面那层 scrollWidth == clientWidth，data-scrollable 恒 0，
 *    渐影与键盘滚动一起无从谈起（而"有 tabindex 属性"这条照样是绿的）。
 *  ② 容器真的可聚焦，并且**按键真的改 scrollLeft** —— 不是断言属性存在就算过。
 *  ③ 两端渐影跟着三态走：还能往右滚才画右边，滚到底必须收（恒亮是说假话，恒灭是
 *    用户永远不知道右边还藏着 7 列）。
 * 外加一档 1440：不溢出时不许无中生有画出可滚的样子。
 *
 * 口径：藏列数读的是**表头 th 的实际矩形**（`lastInView`），不是数 CSS 类 ——
 * 390 下 9 列的表只露 2 列，"最后一列能不能滚进视口"才是这条缺陷的验收本体。 */
async function passTableScrollX(browser) {
  const errors = [];

  const readBoxes = () =>
    (() => {
      const frames = Array.from(document.querySelectorAll('.scrollx-frame'));
      return frames.map((frame) => {
        const box = frame.querySelector('.scrollx-box');
        const ths = Array.from(box.querySelectorAll('thead th'));
        const last = ths[ths.length - 1];
        const lr = last.getBoundingClientRect();
        const inner = box.querySelector('.ant-table-content');
        return {
          role: box.getAttribute('role'),
          tabindex: box.getAttribute('tabindex'),
          aria: box.getAttribute('aria-label') || '',
          /* 内层那层到底还滚不滚：visible 才算收回来 */
          innerX: inner ? getComputedStyle(inner).overflowX : 'no-inner',
          sw: box.scrollWidth,
          cw: box.clientWidth,
          sl: Math.round(box.scrollLeft),
          scrollable: frame.dataset.scrollable,
          atStart: frame.dataset.atStart,
          atEnd: frame.dataset.atEnd,
          fadeR: getComputedStyle(frame, '::after').opacity,
          fadeL: getComputedStyle(frame, '::before').opacity,
          lastCol: (last.textContent || '').trim(),
          lastInView: lr.right <= window.innerWidth + 1 && lr.left >= -1,
        };
      });
    })();

  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'light', locale: 'zh-CN' });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  console.log('\n== X 宽表横向滚动（390 / 1440）==');

  const t = await page.evaluate(readBoxes);
  check('三张宽表都包进了滚动区', t.length === 3, t.length);
  check('每块都是可命名的地标（role=region）', t.every((x) => x.role === 'region'), t.map((x) => x.role));
  check('每块都进得了 Tab 序列（tabindex=0）', t.every((x) => x.tabindex === '0'), t.map((x) => x.tabindex));
  check(
    'aria-label 把"可横向滚动"说给读屏（视觉那层它们拿不到）',
    t.every((x) => x.aria.includes('可横向滚动')),
    t.map((x) => x.aria.slice(0, 12)),
  );
  /* ① 这一条就是"行内样式抢不过"的探针：带 scroll.x 的两张表最容易在这里翻红 */
  check('横向滚动收回来了（AntD 内层 overflow-x 全为 visible）', t.every((x) => x.innerX === 'visible'), t.map((x) => x.innerX));
  check(
    '三张表在 390 下确实溢出（收回前它们量出来是 298>298）',
    t.every((x) => x.sw > x.cw + 1),
    t.map((x) => `${x.sw}>${x.cw}`),
  );
  check('溢出 ⇒ data-scrollable=1（渐影与提示的总开关）', t.every((x) => x.scrollable === '1'), t.map((x) => x.scrollable));
  check('未滚动态：右渐影亮着、左渐影灭着', t.every((x) => +x.fadeR > 0.9 && +x.fadeL < 0.1), t.map((x) => `${x.fadeR}/${x.fadeL}`));
  check('未滚动态：在左端、没到右端', t.every((x) => x.atStart === '1' && x.atEnd === '0'), t.map((x) => `${x.atStart}${x.atEnd}`));
  check('未滚动态：最后一列确实在屏幕外', t.every((x) => !x.lastInView), t.map((x) => `${x.lastCol}=${x.lastInView}`));

  /* ② 真聚焦 + 真按键。focus() 之后必须能拿 activeElement 证一遍，
     否则"tabindex=0 但浏览器不给焦点"（比如 contenteditable 之类）照样全绿。 */
  await page.evaluate(() => document.querySelectorAll('.scrollx-box')[0].focus());
  const focused = await page.evaluate(() => {
    const el = document.activeElement;
    return { isBox: !!el && el.className.includes('scrollx-box'), label: el ? el.getAttribute('aria-label') || '' : '', left: el ? el.scrollLeft : -1 };
  });
  check('focus() 后焦点真落在滚动容器上（不是只有属性）', focused.isBox, focused.label.slice(0, 14));

  /* ⚠️ 逐下发、读到非 0 就停：全量首跑时"固定三下"翻过一次红（scrollLeft 还是 0），
     而同一段循环里后面的 30 下又正常到底 —— 前几下会落在窗口刚拿到焦点之前。
     这不是产品缺陷，是探针的时序假设，所以这里不写死次数。 */
  /* ⚠️ 连发之后再读，别"一下一读"：实测 `page.focus()` 或每次 press 后夹一次 evaluate 都会
     让这几下 ArrowRight 完全不滚（focusProbe 显示 activeElement 就是那块、overflow 642，
     scrollLeft 却一动不动），而连发 10 下的那一段正常。结论：**读法**会干扰键盘滚动，
     所以这里连发 5 下 → 静置 → 读一次；不够再连发 15 下补一次。
     （全量首跑那次翻红就是"固定三下 + 立刻读"撞上了同一个窗口。） */
  const pressRun = async (n) => {
    for (let i = 0; i < n; i += 1) await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    return page.evaluate(() => Math.round(document.querySelectorAll('.scrollx-box')[0].scrollLeft));
  };
  let slAfter = await pressRun(5);
  const slSteps = [slAfter];
  if (slAfter === 0) {
    slAfter = await pressRun(15);
    slSteps.push(slAfter);
  }
  check('方向键真的把表滚动了（scrollLeft 离开 0）', slAfter > 0, `每段之后的 scrollLeft=${slSteps.join(',')}`);

  /* ⚠️ 这里**不用 End / Home**：实测 Chromium 对可滚动 div 不响应这两个键（按下去 scrollLeft
     纹丝不动），只有方向键 / PageUp·Down 会滚。所以"键盘能不能滚到底"只能一段方向键测出来 ——
     每 10 下一读，最多 80 下。看着笨，但它证的正是验收本体：一个只用键盘的用户，
     能不能把藏掉的「向量均分」滚进视野。 */
  let e = (await page.evaluate(readBoxes))[0];
  let presses = 10;
  while (e.atEnd !== '1' && presses <= 80) {
    for (let i = 0; i < 10; i += 1) await page.keyboard.press('ArrowRight');
    presses += 10;
    e = (await page.evaluate(readBoxes))[0];
  }
  /* 渐影带 120ms 过渡，读得太快会拿到插值中的旧值（第一版就是这么误红过一次：
     data-at-end 已经是 1，::after 的 opacity 还在 1→0 的路上）。先静置。 */
  await page.waitForTimeout(300);
  e = (await page.evaluate(readBoxes))[0];
  check(`键盘滚到底：data-at-end=1（${presses - 10} 下 ArrowRight，scrollLeft ${e.sl}/${e.sw}）`, e.atEnd === '1', `${e.atStart}${e.atEnd}`);
  check('滚到底：右渐影收掉（还亮着就是骗人）', +e.fadeR < 0.1, e.fadeR);
  check('滚到底：左渐影亮起来（左边也有藏回去的列）', +e.fadeL > 0.9, e.fadeL);
  check(`滚到底：最后一列「${e.lastCol}」进了视口`, e.lastInView === true, e.lastInView);

  /* 走回左端：先确认焦点还在容器上 —— 上一版把截图夹在两段之间，
     Playwright 的 locator.screenshot() 会把元素滚进视野，焦点跟着丢，
     于是 ArrowLeft 全打在 body 上，读出来"回不去"（假红，不是产品缺陷）。 */
  await page.evaluate(() => document.querySelectorAll('.scrollx-box')[0].focus());
  let back = e;
  let backs = 0;
  while (back.atStart !== '1' && backs <= 80) {
    for (let i = 0; i < 10; i += 1) await page.keyboard.press('ArrowLeft');
    backs += 10;
    back = (await page.evaluate(readBoxes))[0];
  }
  await page.waitForTimeout(300);
  back = (await page.evaluate(readBoxes))[0];
  check(`ArrowLeft 走回左端：三态跟着翻回来（${backs} 下，scrollLeft ${back.sl}）`, back.atStart === '1' && back.atEnd === '0', `${back.atStart}${back.atEnd}`);
  check('回到左端：右渐影重新亮起、左渐影收掉', +back.fadeR > 0.9 && +back.fadeL < 0.1, `${back.fadeR}/${back.fadeL}`);

  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.scrollx-frame').first().screenshot({ path: path.join(OUT, 'x-eval-390-at-start.png') });

  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();

  /* 1440 档：不溢出 ⇒ 一切提示都不许出现。少了这一档，"永远画渐影"的实现也能全绿。 */
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', locale: 'zh-CN' });
  await ctx2.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const wide = await ctx2.newPage();
  wide.on('pageerror', (msg) => errors.push(msg.message));
  await installMocks(wide);
  await wide.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
  await wide.waitForTimeout(500);
  const w = await wide.evaluate(readBoxes);
  check('1440 下三张表都不溢出', w.every((x) => x.sw <= x.cw + 1), w.map((x) => `${x.sw}>${x.cw}`));
  check('不溢出 ⇒ data-scrollable=0 且两渐影都灭（不无中生有）', w.every((x) => x.scrollable === '0' && +x.fadeR < 0.1 && +x.fadeL < 0.1), w.map((x) => `${x.scrollable}/${x.fadeR}/${x.fadeL}`));
  check('不溢出 ⇒ 最后一列本来就在视口里', w.every((x) => x.lastInView), w.map((x) => x.lastCol));
  await ctx2.close();
}

/* 趟 Y：面板头两列抢宽度（走查报告 EV-02，P0）。
 *
 * 缺陷本体（390 实测）：`.surface-head` 是**不换行的 flex**，右侧 chip 那一列作为
 * flex item 默认 `min-width:auto` = 内容宽（不肯让），标题列带的却是 `min-w-0`（随便让）
 * ⇒ 让的全部代价落在标题上，「检索评测（零 LLM）」被压到 **38px**。
 *
 * 这一趟钉的是"让位的顺序被改对了"，四件事各自要证，因为**每一件都能单独假绿**：
 *  ① 标题列有地板 ⇒ 光加 `flex-wrap` 不给地板，标题照样先被压扁（永远轮不到换行）；
 *  ② 真的换行 ⇒ 只测"标题宽度够了"会漏掉"标题够了但 chip 被挤出屏幕"；
 *  ③ 卡片与整页零横向溢出 ⇒ 这是换行的**代价检查**：`.code-chip` 是 `white-space:nowrap`
 *    的整串文件名，收缩链 `.surface-extra` → `.code-chip` → `.code-chip code`
 *    少任何一环 `min-width:0`，窄屏就从"压标题"变成"撑破卡片"（J 趟那类 P0 的复活）；
 *  ④ 截断只是视觉的：`textContent` 与 `title` 属性都还是完整串，复制按钮给的也是全名。
 * 外加 1440 / 820 两档反向钉 —— 少了它们，"恒换行 + 恒截断"的实现也能全绿。
 *
 * 只跑亮色一趟：这一趟全是几何与 min-width，跟配色无关，重复跑只是把断言数翻倍。 */
async function passSurfaceHead(browser) {
  const errors = [];

  /** 读**渲染结果**：宽度、是否同一行、溢出量、收缩链的 min-width。
   *  刻意不读 CSS 源码里写了什么 —— 那条 `min-width: min(14rem, 100%)` 换成任何等价值都对，
   *  验收要看的是"标题还能不能读、卡片有没有被撑破"。 */
  const readHeads = () =>
    Array.from(document.querySelectorAll('.surface-head'))
      .filter((h) => {
        const x = h.querySelector('.surface-extra');
        return x && (x.textContent || '').trim().length > 0;
      })
      .map((h) => {
        const col = h.querySelector('.grow');
        const span = h.querySelector('.surface-title .ellipsis');
        const extra = h.querySelector('.surface-extra');
        const card = h.closest('.surface');
        const chip = extra.querySelector('.code-chip');
        const code = extra.querySelector('.code-chip code');
        const mw = (el) => (el ? getComputedStyle(el).minWidth : null);
        const colR = col.getBoundingClientRect();
        const exR = extra.getBoundingClientRect();
        return {
          title: (span ? span.textContent : h.querySelector('.surface-title')?.textContent || '').trim(),
          colW: Math.round(colR.width),
          /* 标题文字本身完不完整（scrollWidth > clientWidth = 被 ellipsis 藏字） */
          spanOver: span ? span.scrollWidth - span.clientWidth : -999,
          /* ⚠️ 判"换行"不能比 top 差：`.surface-head` 是 `align-items:center`，
             同一行里 extra 会被**垂直居中**到标题列（带 sub 的那一列更高）的中间，
             top 差实测 12px —— 拿 `|Δtop|<=1` 当"同一行"，宽屏那档会假红、窄屏那档会假绿
             （两头的错还都指向同一个方向，最容易看漏）。换行的事实是"跑到标题列下边去了"，
             所以判据写成 extra.top >= col.bottom - 1（行间距 row-gap:8px 天然把它推开）。 */
          wrapped: exR.top >= colR.bottom - 1,
          cardOver: card ? card.scrollWidth - card.clientWidth : -999,
          pageOver: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          codeOver: code ? code.scrollWidth - code.clientWidth : -999,
          codeText: code ? code.textContent : null,
          codeTitle: code ? code.getAttribute('title') : null,
          /* 收缩链三环：extra 一定有；chip / code 只有挂 CodeChip 的那张有（另一张是短 Chip） */
          chain: [mw(extra), mw(chip), mw(code)].filter((v) => v !== null).join('|'),
          wrap: getComputedStyle(h).flexWrap,
        };
      });

  const open = async (width) => {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: 'light', locale: 'zh-CN' });
    await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
    const page = await ctx.newPage();
    page.on('pageerror', (msg) => errors.push(msg.message));
    await installMocks(page);
    await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    return { ctx, page };
  };

  /* ---------------- 390：缺陷现场 ---------------- */
  const n390 = await open(390);
  const h = await n390.page.evaluate(readHeads);
  check('取到两张带右侧操作区的面板头（不补 0、不数空气）', h.length === 2, h.map((x) => x.title));
  check('标题列有地板，不再被压成 38px 那条竖字', h.every((x) => x.colW >= 200), h.map((x) => `${x.title}:${x.colW}px`));
  check('标题文字完整可读（不是靠 ellipsis 藏字凑出来的）', h.every((x) => x.spanOver === 0), h.map((x) => x.spanOver));
  check('放不下的是 chip：它落到第二行（让位顺序反过来 = 标题又被压）', h.every((x) => x.wrapped === true), h.map((x) => x.wrapped));
  check('换行后卡片自身零横向溢出（收缩链三环都在）', h.every((x) => x.cardOver <= 0), h.map((x) => x.cardOver));
  check('整页也零横向溢出（EV-02 的修法不许把 J 趟的 P0 换回来）', h.every((x) => x.pageOver <= 0), h.map((x) => x.pageOver));

  const long = h.find((x) => /json$/.test(x.codeText || ''));
  check('长文件名那张：截断发生在 code 上（视觉截断，不是撑破）', long && long.codeOver > 0, long && long.codeOver);
  check(
    '长文件名那张：完整串仍在 textContent 里（复制/读屏拿得到全名，CSS 只截视觉）',
    !!long && /^evaluation\/reports\/retrieval\/\d{4}-\d{2}-\d{2}T[\d-]+\.json$/.test(long.codeText || '') && long.codeText === long.codeTitle,
    long && [long.codeText, long.codeTitle],
  );
  check(
    '收缩链：extra 一环 min-width=0（两张都有），挂 CodeChip 那张三环全 0（缺一环就是"换行也没用"）',
    h.every((x) => x.wrap === 'wrap' && x.chain.split('|').every((v) => v === '0px')) &&
      h.some((x) => x.chain === '0px|0px|0px'),
    h.map((x) => `${x.wrap}/${x.chain}`),
  );
  fs.mkdirSync(OUT, { recursive: true });
  await n390.page.locator('.surface-head').first().screenshot({ path: path.join(OUT, 'y-eval-390-head.png') });
  check('390 这一档没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await n390.ctx.close();

  /* ---------------- 1440：反向钉，不许"恒换行 + 恒截断" ---------------- */
  const n1440 = await open(1440);
  const w = await n1440.page.evaluate(readHeads);
  check('1440 下两张面板头都还在（不是取空了才"全绿"）', w.length === 2, w.map((x) => x.title));
  check('宽屏同一行摆着：chip 不许无理由掉到第二行', w.every((x) => x.wrapped === false), w.map((x) => x.wrapped));
  check('宽屏 code 一字不截（scrollWidth == clientWidth）', w.every((x) => x.codeOver === 0 || !/json$/.test(x.codeText || '')), w.map((x) => `${x.codeOver}:${x.title}`));
  check('宽屏标题列同样不许溢出、文字完整', w.every((x) => x.cardOver <= 0 && x.spanOver === 0), w.map((x) => `${x.cardOver}/${x.spanOver}`));
  await n1440.ctx.close();

  /* ---------------- 820：过渡档 ----------------
     EV-02 的实测数是 390 那一个，但地板写的是 `min(14rem, 100%)`，769–1024 这一带
     才是"既不该换行、也不该压标题"最挤的区间。不量这一档，就等于承认改完只验过一头。 */
  const n820 = await open(820);
  const m = await n820.page.evaluate(readHeads);
  check('820 下标题列仍 ≥ 地板（14rem = 224px）', m.every((x) => x.colW >= 224), m.map((x) => `${x.title}:${x.colW}px`));
  check('820 下卡片与整页都不横向溢出（读数里带换行与否，这一档刚好摆满，只做记录不判定）', m.every((x) => x.cardOver <= 0 && x.pageOver <= 0), m.map((x) => `${x.cardOver}/${x.pageOver}/换行=${x.wrapped}`));
  check('820 下标题文字完整', m.every((x) => x.spanOver === 0), m.map((x) => x.spanOver));
  await n820.ctx.close();

  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
}

/* ---------------- J 续 · 收起态不许留焦点位（EV-07）+ 日志区键盘可滚（P1-10） ----------------
 *
 * EV-07 的形状：把任务列表收起（宽屏）或关掉（窄屏抽屉）之后，那一栏里的控件**还在 Tab 序里**
 * —— 走查量到 23 枚。根因是"看不见"和"Tab 不着"是两件事：`width:0` + `opacity:0` +
 * `pointer-events:none` 三条都关不掉焦点，能关掉的只有 `visibility:hidden`（或 inert / 卸载，
 * 那两个会吃掉动画与状态）。窄屏更要命：抽屉是 `translateX(-100%)` 推到屏外，
 * 推出去的东西照样能聚焦，Tab 过去还会把浏览器滚动条拽走。
 *
 * 所以这一趟必须**双向**：展开态要先量到焦点位确实走得到，收起态那句 0 才不算恒真。
 * 只留"0"的话，CSS 里那条 visibility 被谁删了、或者整栏被误卸载，探针都照样全绿。
 */
/** 栏的状态读数：可见性 / 命中测试 / 实渲宽度 / DOM 里的焦点位数。
 *  选择器在函数体里内联 —— 这枚字符串要吃进 page.evaluate，模块作用域那份传不过去。 */
function colStateProbe() {
  const el = document.querySelector('.task-col');
  if (!el) return null;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    vis: cs.visibility,
    pe: cs.pointerEvents,
    w: Math.round(r.width),
    right: Math.round(r.right),
    domFocusable: el.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
    ).length,
  };
}

/** 从文档开头连按 n 次 Tab，记录每次落在哪。 */
async function tabWalk(page, n) {
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  const out = [];
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press('Tab');
    out.push(
      await page.evaluate(() => {
        const a = document.activeElement;
        return {
          inCol: !!(a && a.closest('.task-col')),
          isLog: !!(a && a.classList && a.classList.contains('log-body')),
          tag: a ? `${a.tagName.toLowerCase()} ${(a.getAttribute('aria-label') || a.getAttribute('placeholder') || a.textContent || '').trim().slice(0, 12)}` : '',
        };
      }),
    );
  }
  return out;
}

/** 连按 Tab 走到某个 class 上，返回第几步走到（-1 = 走不到）。 */
async function tabTo(page, cls, max = 60) {
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  for (let i = 1; i <= max; i += 1) {
    await page.keyboard.press('Tab');
    const hit = await page.evaluate((c) => !!(document.activeElement && document.activeElement.classList.contains(c)), cls);
    if (hit) return i;
  }
  return -1;
}

async function passCollapsedFocus(browser) {
  console.log('\n== J 续 · 收起态不许留焦点位 + 日志区键盘可滚（EV-07 / P1-10）==');
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', locale: 'zh-CN' });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 灌 120 行：日志区要真的溢出，键盘滚动那条判据才不是空的（静默态根本没有滚动） */
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(virtualTrace(120)) }));
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelector('.tsk-item')?.click());
  await page.waitForTimeout(700);

  const wide = await page.evaluate(colStateProbe);
  /* 走查报的"23 枚"是**真后端**那一屏（任务条目多），这里走 mocks ⇒ 实测量到 14。
     门槛定"成堆"（≥8）而不是复述 23：两个读数都真，差额来源是列表条目数，
     把 23 抄成判据就等于把 mocks 的规模当成产品事实。 */
  check('宽屏展开态：栏里有一整列焦点位（mock 量到 14 / 真后端走查量到 23，差额=条目数）',
    !!wide && wide.domFocusable >= 8, wide);
  const walkOpen = (await tabWalk(page, 45)).filter((x) => x.inCol).length;
  check('展开态 Tab **走得到**它们（不这下一条 0 就是恒真）', walkOpen >= 3, walkOpen);

  await page.locator('button[aria-label="收起任务列表"]').click();
  await page.waitForTimeout(600);
  const wideC = await page.evaluate(colStateProbe);
  check('收起后整栏 visibility 切 hidden（width/opacity/pointer-events 都关不掉焦点）',
    !!wideC && wideC.vis === 'hidden', wideC);
  check('收起后宽度真的收成 0（排除"只是被推出视野"这种假收起）', !!wideC && wideC.w === 0, wideC);
  const walkHidden = (await tabWalk(page, 45)).filter((x) => x.inCol).length;
  check('收起后 Tab 一次都进不去这一栏', walkHidden === 0, walkHidden);
  check('DOM 里那 23 枚还在（我们只请出 Tab 序，没有卸载、没有丢状态）',
    !!wideC && wideC.domFocusable >= 8 && walkHidden === 0, wideC && wideC.domFocusable);

  await page.locator('button[aria-label="展开任务列表"]').click();
  await page.waitForTimeout(80);
  const wideBack = await page.evaluate(colStateProbe);
  check('展开方向立刻可见（visibility 的延时只许加在收起那侧）', !!wideBack && wideBack.vis === 'visible', wideBack);
  await page.waitForTimeout(500);
  const walkBack = (await tabWalk(page, 45)).filter((x) => x.inCol).length;
  check('展开后焦点位回来了（收起没把这一栏永久弄坏）', walkBack >= 3, walkBack);

  /* ---- P1-10：日志区自己滚，所以它必须进 Tab 序 ----
     页签调换之后必须先点开日志那一屏：`.log-body` 与那四个控件（在页签栏 extra 位、
     且 `tab === 'log'` 才画）都不在不激活的面板里。EV-07 那几条量的是左栏焦点位，
     与页签无关，所以这一击放在它们**之后** —— 免得凭空多出来的控件混进上面的普查。 */
  await openLogTab(page);
  /* 页签调换带出来的一个**真实产品缺陷**（本轮实测到、修在 LogStream 里），判据就落在这里：
     以前日志面板是默认页，必然在 0 行时挂载，第一条永远经由"行数涨了"那条路钉底；
     换成结果页当默认页之后，用户是先把整包 trace 拉完再点开日志页签 ⇒ 面板**带着满屏行
     第一次挂载**，而 `prevLen = useRef(rows.length)` ⇒ delta = 0 ⇒ 谁都不钉底。
     没修之前的实测：scrollTop=0 / max=2592、视口停在 #001–#025（最老那 25 行），而页脚写着
     「自动滚动已开启」—— 界面承诺的位置与实际滚动位置不一致。修后同一处：top=2591 / max=2591 / #096–#120。
     负面对照 NC-J（把 LogStream 那次钉底早退掉）实测把这一条打红，见 README 的 NC 清单。
     ⚠️ 必须放在这一趟**第一个读点**：下面 `tabTo()` 的键盘导航会把焦点滚进视口，任何一次滚动 /
     换关键字 / 再切页签都让它不再是"第一次挂载"。
     ⚠️ 也不能挪到 V 趟：那里同一份 trace 被合并成 1 行、面板压根没有可滚内容（max=0），
     同一条 `top >= max - 2` 会变成恒真判据。
     修法里"推两帧再钉"那一笔不能省（理由在 LogStream 的注释上：当场钉会被测高回填夹一次，
     而那一下夹动正好落进 handleScroll 的"用户上滑了"判据 ⇒ 自动滚动被悄悄关掉，第一版就是这么红的）。 */
  const firstMount = await page.evaluate(() => {
    const el = document.querySelector('.log-body');
    if (!el) return null;
    const seqs = Array.from(document.querySelectorAll('.log-row .log-seq'));
    const num = (s) => Number(String(s || '').replace(/[^0-9]/g, ''));
    const nums = seqs.map((x) => num(x.textContent)).filter((x) => Number.isFinite(x));
    return {
      top: Math.round(el.scrollTop),
      max: Math.round(el.scrollHeight - el.clientHeight),
      rows: seqs.length,
      firstSeq: nums.length ? nums[0] : null,
      lastSeq: nums.length ? nums[nums.length - 1] : null,
      foot: (document.querySelector('.log-foot')?.textContent || '').replace(/\s+/g, ' ').trim(),
    };
  });
  check(
    '第一次点开日志页签就停在最后一条（带行挂载也要钉底；页脚那句"自动滚动已开启"要算数）',
    !!firstMount
      && firstMount.max >= 40
      && firstMount.top >= firstMount.max - 2
      && firstMount.lastSeq !== null
      && firstMount.firstSeq !== null
      && firstMount.lastSeq > firstMount.firstSeq
      && /自动滚动已开启/.test(firstMount.foot),
    firstMount,
  );
  const lb = await page.evaluate(() => {
    const el = document.querySelector('.log-body');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {
      tab: el.getAttribute('tabindex'),
      role: el.getAttribute('role'),
      label: el.getAttribute('aria-label') || '',
      overflow: el.scrollHeight - el.clientHeight,
      of: cs.overflowY,
    };
  });
  check('日志区自己带溢出（这条判据的前提，先量不成立就别往下判）', !!lb && lb.of === 'auto' && lb.overflow > 40, lb);
  check('日志区 tabIndex=0 且 role=log 不变（进 Tab 序不改语义）', !!lb && lb.tab === '0' && lb.role === 'log', lb);
  check('aria-label 把"怎么滚"说清楚（滚动条对读屏不存在）',
    !!lb && /方向键|PageUp/.test(lb.label), lb && lb.label);
  const step = await tabTo(page, 'log-body');
  check('Tab 走得到日志区（键盘用户只剩"滚整页"那条路 ⇒ 现在不是了）', step > 0, step);
  const ring = await page.evaluate(() => {
    const cs = getComputedStyle(document.activeElement);
    return { style: cs.outlineStyle, width: cs.outlineWidth, color: cs.outlineColor };
  });
  check('键盘聚焦有描边环（走全站那条 [tabindex]:focus-visible，不另写一份）',
    ring.style !== 'none' && parseFloat(ring.width) >= 2, ring);
  /* ⚠️ 顺序不能反：日志区刚挂载时是**钉在底部**的（autoScroll），第一下 PageDown 无处可去，
     量出来 before==after==2591 —— 那是判据自己造出来的假红，不是产品缺陷。
     所以先 PageUp 离开底部，再 PageDown 回来，两个方向都比"页"这个步长；
     ArrowUp 那一下还兼做一件事：证明钉底逻辑不会把键盘滚动立刻顶回去。 */
  const atBottom = await page.evaluate(() => {
    const el = document.querySelector('.log-body');
    return { scrollTop: el.scrollTop, max: el.scrollHeight - el.clientHeight };
  });
  check('前提读数：日志区确实停在底部（否则上面那条 PageDown 假红无从解释）',
    atBottom.scrollTop >= atBottom.max - 2, atBottom);
  await page.keyboard.press('PageUp');
  await page.waitForTimeout(150);
  const afterUp1 = await page.evaluate(() => document.querySelector('.log-body').scrollTop);
  check('聚焦后 PageUp 滚得动，而且一步就是一屏（不是几像素）',
    atBottom.scrollTop - afterUp1 > 200, { from: atBottom.scrollTop, to: afterUp1 });
  await page.keyboard.press('PageDown');
  await page.waitForTimeout(150);
  const afterDown = await page.evaluate(() => document.querySelector('.log-body').scrollTop);
  check('PageDown 往下也灵（方向键与翻页键都归这块自己管）', afterDown > afterUp1, { afterUp1, afterDown });
  await page.keyboard.press('ArrowUp');
  await page.waitForTimeout(150);
  const afterUp = await page.evaluate(() => document.querySelector('.log-body').scrollTop);
  check('ArrowUp 往回滚也灵（钉底逻辑不许把键盘滚动顶回去）', afterUp < afterDown, { afterDown, afterUp });

  /* 静默态那块（.log-idle）不滚，就不许占焦点位 —— 上一轮差点把 tabIndex 一并加到它身上，
     两个渲染点都写着 role="log"，一眼看不出来。
     到静默态走 J 趟同一招：关键字滤到零行（mocks 对任意 task_id 都回一份真 trace，
     拿 ?task_id=task-none 进不去静默态 —— 上一版就是这么量到 null 的）。 */
  await page.getByLabel('日志关键字过滤').fill('绝无此关键字');
  await page.waitForTimeout(500);
  const idleReal = await page.evaluate(() => {
    const el = document.querySelector('.log-idle');
    return el
      ? {
          tab: el.getAttribute('tabindex'),
          role: el.getAttribute('role'),
          rows: document.querySelectorAll('.log-row').length,
          scroll: el.scrollHeight - el.clientHeight,
        }
      : null;
  });
  check('先证明确实进了静默态（0 行 + .log-idle 在）', !!idleReal && idleReal.rows === 0, idleReal);
  check('静默态 .log-idle 不占 Tab 位（它自己不出滚动条，焦点只给滚得动的）',
    !!idleReal && idleReal.tab === null && idleReal.scroll <= 40, idleReal);
  await page.getByLabel('日志关键字过滤').fill('');
  await page.waitForTimeout(300);

  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();

  /* ---- 窄屏：抽屉关着（translateX 推到屏外）同样不许留焦点位 ---- */
  const nctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'light', locale: 'zh-CN' });
  await nctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const npage = await nctx.newPage();
  const nerrors = [];
  npage.on('pageerror', (e) => nerrors.push(e.message));
  await installMocks(npage);
  await npage.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await npage.waitForTimeout(500);
  const closed = await npage.evaluate(colStateProbe);
  check('窄屏抽屉关着：整栏 visibility hidden（translateX(-100%) 推出去照样能聚焦，那是 EV-07 的另一半）',
    !!closed && closed.vis === 'hidden', closed);
  check('窄屏抽屉关着：右边缘确实在屏外（读数证明"看不见"不是判据的全部）',
    !!closed && closed.right <= 0, closed);
  const nWalk = (await tabWalk(npage, 30)).filter((x) => x.inCol).length;
  check('窄屏抽屉关着：Tab 进不去（屏外面板被聚焦会把滚动条整块拽走）', nWalk === 0, nWalk);

  await npage.locator('.only-compact').click();
  await npage.waitForTimeout(700);
  const opened = await npage.evaluate(colStateProbe);
  check('拉开抽屉后立刻可见（展开方向不排队）', !!opened && opened.vis === 'visible', opened);
  const nWalk2 = (await tabWalk(npage, 30)).filter((x) => x.inCol).length;
  check('抽屉开着：焦点位回来了（>=3 枚，说明那条 visibility 不是把整栏焊死）', nWalk2 >= 3, nWalk2);
  check('窄屏这一趟没有 pageerror', nerrors.length === 0, nerrors.slice(0, 3));
  await nctx.close();
}

/* ------------------------------ AA 成本归因面板（C1–C7） ------------------------------ //
 * 八条正判据 + 三条负面对照。这套面板的**全部价值是数字可信**，所以判据集中在
 * 「页面说的是端点说的，不是前端自己算的」这一类，而不是外观。
 *
 * 与设计文档 §10.5 的一处**有意偏差**：原第 2 条写的是「明细截断提示」（造 600 条事件
 * 看页面有没有"已截断"那句）。做完契约后发现它不成立 —— 合计来自端点的 GROUP BY，
 * 根本不会被截断，被截断的只有轨迹明细那一侧，而那一侧已有自己的"共 N 条 / 已加载 M 条"。
 * 于是这一条改成量**真正会被咬的那个不变量**：把明细桩做成 600 条、token 数堆到天文数字，
 * 面板上的合计必须**一动不动**（还是端点那份），次数还是 5。这比"有没有一句提示"硬得多。
 *
 * ⚠️ check() 是 Boolean(cond)，所以每条都配了反方向的在场/不在场判定（同 R 趟的规矩）。 */
async function passCostBreakdown(browser) {
  console.log('\n== AA 成本归因面板：合计/时段/历史行/对账 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);

  /* 明细桩换成 600 条、每条 token 与 cost 都堆到离谱：面板的合计**若来自明细**，
     这里就会跟着变成 ¥600.0000 之类的数。端点桩（costBody）一个字没改。 */
  const fat = {
    ...traceBody,
    items: Array.from({ length: 600 }, (_, i) => ({
      ...traceBody.items[0],
      event_seq: i + 1,
      event_type: 'llm_call',
      role: 'planner',
      tokens_in: 999999,
      tokens_out: 999999,
      cost: 1,
    })),
    total: 600,
    has_more: false,
    next_after_seq: 0,
    events_available: true,
  };
  await page.route('**/api/tasks/*/trace*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fat) }),
  );

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(700);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(900);

  const present = await page.locator('.cost-panel').count();
  check('结果页那一节在场（前件：不然下面全是 null 蒙对）', present === 1, present);

  const read = () =>
    page.evaluate(() => {
      const txt = (s) => {
        const el = document.querySelector(s);
        return el ? el.textContent.trim() : null;
      };
      const rows = Array.from(document.querySelectorAll('.cost-table tbody tr'));
      return {
        total: txt('.cost-total'),
        hint: txt('.cost-total-hint'),
        events: txt('.cost-recon-events'),
        task: txt('.cost-recon-task'),
        window: txt('.cost-window'),
        checks: Array.from(document.querySelectorAll('.cost-check')).map((p) => p.textContent.trim()),
        marks: Array.from(document.querySelectorAll('.cost-mark')).map((m) => m.textContent.trim()),
        rowCount: rows.length,
        roleCells: rows.map((r) => r.querySelector('.cost-model')?.textContent.trim() ?? ''),
        tierCells: rows.map((r) => r.querySelector('.cost-tier')?.textContent.trim() ?? ''),
        costCells: rows.map((r) => r.querySelector('.cost-cost')?.textContent.trim() ?? ''),
        chipCount: document.querySelectorAll('.cost-chips .chip').length,
        chipText: Array.from(document.querySelectorAll('.cost-chips .chip')).map((c) => c.textContent.trim()),
        segCount: document.querySelectorAll('.spark > span').length,
        bodyText: document.querySelector('.cost-panel')?.innerText ?? '',
      };
    });
  const a = await read();

  /* 1 合计来自端点：明细被灌成 600 条 ×¥1，页面仍然是端点那份 ¥0.0094 / 5 次 */
  check('1 合计是端点给的，不是把明细加出来的（明细被灌成 600 元而读数不动）', a.total === '¥0.0094', {
    total: a.total,
    明细应为: '¥600.0000 若前端自加',
  });
  check('1b 次数同理（5 次调用，不是 600 条事件）', /5 次 LLM 调用/.test(a.hint ?? ''), a.hint);

  /* 2 对账三读数按同一口径对齐：headline 4 位、两枚 6 位，四舍五入到 4 位必须两两相等 */
  const num = (s) => Number(String(s ?? '').replace(/[^0-9.]/g, ''));
  const r4 = (s) => num(s).toFixed(4);
  check('2 三个读数量级一致（headline == Σ分组 == tasks.cost，按展示位归一）',
    a.total !== null && r4(a.total) === r4(a.events) && r4(a.events) === r4(a.task),
    { total: a.total, events: a.events, task: a.task });
  check('2b 两个独立口径的数都常驻露出（相等时也不许把凭据收走）',
    !!a.events && !!a.task && a.events !== a.task ? true : !!a.events && !!a.task,
    { events: a.events, task: a.task });

  /* 3 历史行不说谎：model=null 那一行显示「未记录」，且当前配置的模型名不许出现 */
  check('3 无模型的历史行显示「未记录」', a.roleCells.includes('未记录'), a.roleCells);
  check('3b 页面上不出现当前配置的模型名（没拿今天的 role_map 填昨天的账）',
    !a.bodyText.includes('某没配过价的模型'), a.bodyText.slice(0, 200));
  check('3c 档位未记录时也是「未记录」，不是 ×1.0 也不是 ×0', a.tierCells.includes('未记录'), a.tierCells);

  /* 4 跨峰谷两行同角色并存（不许折成一行、也不许挑一个代表系数） */
  check('4 同角色两行：planner 在表里出现两次',
    a.tierCells.filter((t) => /高峰|低谷/.test(t)).length >= 3, a.tierCells);
  check('4b 两个系数读数并存（高峰 ×1 与 低谷 ×0.5 同屏）',
    a.chipText.some((c) => /高峰/.test(c)) && a.chipText.some((c) => /低谷/.test(c)), a.chipText);
  check('4c 三档三枚胶囊（1.0 / 0.5 / 未记录）', a.chipCount === 3, { chipCount: a.chipCount, chipText: a.chipText });

  /* 4d 图形豁免的**补偿判据**：I 趟那条空壳普查现在放过 role="img" 子树，
     所以这里必须自己查那条 aria-label —— 放过一个"有标签的图形"，前提是先确认标签真的在。
     而且要求每段带 ¥ 金额：原始浮点（0.0020022）进 aria-label 等于图形那条通道只服务视力正常的人。 */
  const spark = await page.evaluate(() => {
    const el = document.querySelector('.cost-panel .spark');
    return el ? { role: el.getAttribute('role'), label: el.getAttribute('aria-label') || '' } : null;
  });
  check('4d 分段条带 role=img 且 aria-label 逐段点名 + 带 ¥ 金额（豁免的前提）',
    !!spark && spark.role === 'img' && (spark.label.match(/¥0\.\d{4}/g) || []).length === 4
      && /高峰|低谷|未记录/.test(spark.label),
    spark);

  /* 5 金额一律 4 位（钉 fmtCostFixed 真被用上，而不是 strip 尾零的 fmtCost） */
  const bad4 = a.costCells.filter((c) => !/^¥0\.\d{4}$/.test(c));
  check('5 表里每个金额都是 4 位小数（¥0.0020 不许缩成 ¥0.002）', bad4.length === 0, { bad: bad4, all: a.costCells });

  /* 6 时钟口径：读数跟桩值走，不跟浏览器系统时间走 */
  const nextBefore = a.window;
  await page.route('**/api/tasks/*/cost-breakdown', (r) => {
    const clone = JSON.parse(JSON.stringify(costBody));
    clone.window.next_off_peak_at = '2026-09-26T21:07:00+08:00';
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(clone) });
  });
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.locator('.tsk-item').first().click();
  await page.waitForTimeout(700);
  await page.getByRole('tab', { name: '运行结果' }).click();
  await page.waitForTimeout(800);
  const b = await read();
  check('6 改后端桩值，页面读数跟着变（证明这个数是读来的）',
    b.window !== nextBefore && /21:07/.test(b.window ?? ''), { before: nextBefore, after: b.window });
  await ctx.close();

  /* 6b 把系统时钟整个挪走：读数一个字符都不许变（前端没有自己算时间的余地） */
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  await ctx2.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page2 = await ctx2.newPage();
  await page2.clock.install({ time: new Date('2026-09-26T03:00:00Z') });
  await installMocks(page2);
  await page2.route('**/api/tasks/*/cost-breakdown', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(costBody) }));
  await page2.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page2.clock.fastForward('05:00');
  await page2.waitForTimeout(500);
  await page2.locator('.tsk-item').first().click();
  await page2.waitForTimeout(700);
  await page2.getByRole('tab', { name: '运行结果' }).click();
  await page2.waitForTimeout(800);
  const c = await page2.evaluate(() => document.querySelector('.cost-window')?.textContent.trim() ?? '');
  /* ⚠️ 对照的是 6 改桩**之前**那一次读数（a.window，18:00），不是 b.window ——
     b 是 6 那一步特意改成 21:07 的桩，拿它当基准会把这条判据变成自我循环。 */
  check('6b 系统时钟挪了 5 小时，读数一字不变（没有前端自判时段）',
    c === a.window && /18:00/.test(c), { withClock: c, pristine: a.window });
  await ctx2.close();

  /* 7 窄屏 390：面板不撑破文档，表能键盘横滚（复用 X/Y 趟的判据形状） */
  const nctx = await browser.newContext({ viewport: { width: 390, height: 780 }, locale: 'zh-CN' });
  await nctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const npage = await nctx.newPage();
  await installMocks(npage);
  await npage.route('**/api/tasks/*/cost-breakdown', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(costBody) }));
  await npage.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await npage.waitForTimeout(500);
  /* 窄屏下任务列表是抽屉：先拉开再选，否则点不到 .tsk-item（EV-07 那趟的同一条现实） */
  await npage.locator('.only-compact').click();
  await npage.waitForTimeout(600);
  await npage.locator('.tsk-item').first().click();
  await npage.waitForTimeout(800);
  const tabN = await npage.getByRole('tab', { name: '运行结果' }).count();
  if (tabN > 0) {
    await npage.getByRole('tab', { name: '运行结果' }).click();
    await npage.waitForTimeout(800);
  }
  const narrow = await npage.evaluate(() => {
    const de = document.documentElement;
    const panel = document.querySelector('.cost-panel');
    const box = panel ? panel.querySelector('.scrollx-box') : null;
    return {
      docW: de.scrollWidth,
      clientW: de.clientWidth,
      panelRight: panel ? Math.round(panel.getBoundingClientRect().right) : null,
      tabIndex: box ? box.getAttribute('tabindex') : null,
      frameScrollW: box ? box.scrollWidth : null,
      frameClientW: box ? box.clientWidth : null,
      left0: box ? box.scrollLeft : null,
    };
  });
  check('7 390 下文档不横向溢出（面板没把宽度顶出去）', narrow.docW <= narrow.clientW + 1, narrow);
  await npage.evaluate(() => {
    const panel = document.querySelector('.cost-panel');
    const box = panel ? panel.querySelector('.scrollx-box') : null;
    if (box) box.focus();
  });
  const active = await npage.evaluate(() => document.activeElement?.className ?? '');
  check('7b 明细表的横滚容器可聚焦（键盘到得了）', /scrollx-box/.test(active), active);
  await npage.keyboard.press('ArrowRight');
  await npage.keyboard.press('ArrowRight');
  await npage.waitForTimeout(250);
  const scrolled = await npage.evaluate(() => {
    const box = document.querySelector('.cost-panel .scrollx-box');
    return box ? box.scrollLeft : -1;
  });
  check('7c 方向键真的滚得动（表在窄屏不靠鼠标）', scrolled > (narrow.left0 ?? 0), { from: narrow.left0, to: scrolled });
  await nctx.close();

  /* 8 两主题：在**每种行底色**上实算文字对比度（读计算样式，不读 token 名） */
  const surfaces = [];
  for (const scheme of ['light', 'dark']) {
    const sctx = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      colorScheme: scheme,
      locale: 'zh-CN',
    });
    await sctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
    const spage = await sctx.newPage();
    await installMocks(spage);
    await spage.route('**/api/tasks/*/cost-breakdown', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(costBody) }));
    await spage.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await spage.waitForTimeout(500);
    await spage.locator('.tsk-item').first().click();
    await spage.waitForTimeout(700);
    await spage.getByRole('tab', { name: '运行结果' }).click();
    await spage.waitForTimeout(800);
    const got = await spage.evaluate(() => {
      const lin = (v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const parse = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      /* 底色要**沿祖先链找第一层不透明**：面板卡片压在页面底色上，行又压在卡片上，
         只读 backgroundColor 会拿到 rgba(0,0,0,0) 然后算出个自欺欺人的数。 */
      const bgOf = (el) => {
        let node = el;
        while (node) {
          const rgb = parse(getComputedStyle(node).backgroundColor);
          const a = rgb.length > 3 ? rgb[3] : 1;
          if (rgb.length >= 3 && a > 0.99) return rgb.slice(0, 3);
          node = node.parentElement;
        }
        return [255, 255, 255];
      };
      const cr = (fgRgb, bgRgb) => {
        const l1 = lum(fgRgb);
        const l2 = lum(bgRgb);
        return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
      };
      const probe = (sel) =>
        Array.from(document.querySelectorAll(sel)).map((el) => ({
          text: el.textContent.trim().slice(0, 20),
          ratio: cr(parse(getComputedStyle(el).color).slice(0, 3), bgOf(el)),
        }));
      return {
        total: probe('.cost-total'),
        tier: probe('.cost-tier--peak, .cost-tier--off'),
        chip: probe('.cost-chips .chip'),
        checkText: probe('.cost-check'),
        hint: probe('.cost-total-hint'),
      };
    });
    surfaces.push({ scheme, got });
    await sctx.close();
  }
  const low = [];
  for (const { scheme, got } of surfaces) {
    for (const [name, list] of Object.entries(got)) {
      for (const item of list) if (item.ratio < 4.5) low.push(`${scheme}.${name} ${item.ratio} "${item.text}"`);
    }
  }
  check('8 两主题 × 五种文字，在它**实际所在底色**上全部 ≥4.5:1', low.length === 0, low);
  check('8b 前件：两主题都真量到了文字（一组为空就是选择器写错，不是通过）',
    surfaces.every((s) => s.got.total.length === 1 && s.got.tier.length >= 3 && s.got.chip.length === 3),
    surfaces.map((s) => ({ scheme: s.scheme, n: Object.fromEntries(Object.entries(s.got).map(([k, v]) => [k, v.length])) })));

  /* ---- AA-neg：三条摘法，各证一次"这批评据真的会红" ---- */
  const negctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  await negctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const neg = await negctx.newPage();
  await installMocks(neg);
  const broken = JSON.parse(JSON.stringify(costBody));
  /* 摘法①：把历史行的 model 回落成"今天的 role_map" → 判据 3 必须抓到 */
  broken.by_role[3].model = '某没配过价的模型';
  /* 摘法②：对账改成不等 → ✗ 必须出现在页面上 */
  broken.reconcile = { events_cost: 0.02, task_cost: 0.009395, all_equal: false, note: '两边对不上（桩）' };
  /* 摘法③：单价校验改成"判不了" → 必须显示 ? 与「未校验」，不许显示 ✓ */
  broken.price_check = { ok: null, max_delta_pct: null, implied_price_in: null, implied_price_out: null, equations: 1, reason: '方程数不足 2（桩）' };
  await neg.route('**/api/tasks/*/cost-breakdown', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(broken) }));
  await neg.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await neg.waitForTimeout(500);
  await neg.locator('.tsk-item').first().click();
  await neg.waitForTimeout(700);
  await neg.getByRole('tab', { name: '运行结果' }).click();
  await neg.waitForTimeout(800);
  const n1 = await neg.evaluate(() => ({
    body: document.querySelector('.cost-panel')?.innerText ?? '',
    marks: Array.from(document.querySelectorAll('.cost-mark')).map((m) => m.textContent.trim()),
  }));
  check('neg① 一旦把历史行回落成今天的模型名，页面上就看得见（判据 3 不是恒绿）',
    n1.body.includes('某没配过价的模型'), n1.body.slice(0, 160));
  check('neg② 对账改成不等，✗ 与 note 真的落到页面上（不是恒 ✓）',
    n1.marks.includes('✗') && /两边对不上/.test(n1.body), n1.marks);
  check('neg③ 校验改成判不了，页面显示 ? 与「未校验」（不是偷偷显示 ✓）',
    n1.marks.includes('?') && /未校验/.test(n1.body), n1.marks);
  await negctx.close();

  check('这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
}

/* ==================================================================== *
 * AB 趟 · /eval 的错误态、形状闸门与两处可达性（F-1 / F-2 / F-4 / F-5 + F-11 复核）
 *
 * 外部检测报告（2026-09-25）说：500 / 404 / 断网 与"真的还没跑过评测"共用同一个空态壳，
 * 而且壳里还写着"跑一次评测即可生成 + CLI 命令" —— 后端活着却被支去敲命令行。
 * 本轮改法（见 EvalAblationPage.tsx 与 client.ts 的 ApiFetchError）分四步：
 *   ① getJson 抛带 HTTP 码 / 机器码 / request_id 的错误（过去只摊成一个 message，三件都丢）；
 *   ② 错误分支排在空态**前面**（顺序错了就永远走不到，这是整条的根）；
 *   ③ 报告 payload 过形状闸门：groups/arms 不是数组 ⇒ "格式不识别"，不整页崩；
 *   ④ ⓘ 释义改成真 `<button>`、可排序表头补一条压过 AntD 的焦点环。
 *
 * 判据全部按**内容**与**计算样式**读，不看像素：这一趟问的是"用户读到了哪一句话"。
 * 只跑亮色是有意的（①②③④ 都与配色无关；对比度那一类由 contrast.cjs 负责）。
 * ==================================================================== */

/** 开一个 /eval 页并按 scenario 打桩；返回 {page, ctx, hits} —— hits 是这份桩被请求了几次。 */
async function openEval(browser, scenario, viewport) {
  const ctx = await browser.newContext({
    viewport: viewport || { width: 1440, height: 1000 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const hits = { retrieval: 0, ablation: 0 };
  await installMocks(page);

  const RETRIEVAL = '**/api/eval/retrieval-report';
  const ABLATION = '**/api/eval/ablation-report';
  const envelope = (code, message, requestId) => ({ detail: { code, message, request_id: requestId } });
  // 后注册的 route 先匹配（Playwright 语义），所以上面这些覆盖得住 installMocks 的默认桩。
  // ⚠️ 这里刻意用行注释：块注释里一旦写出"星号加斜杠"那三个字符就会就地闭合，
  //    剩下的中文被当成代码 —— 本仓第三次栽在同一处（前两次的症状与判据见 README 避坑 4）。
  if (scenario === 'http500') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify(envelope('internal_error', '读取报告文件时炸了（探针桩）', 'req-probe-500')),
      });
    });
  } else if (scenario === 'http404') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify(envelope('not_found', '没有这个端点（探针桩）', 'req-probe-404')),
      });
    });
  } else if (scenario === 'abort') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.abort('connectionrefused');
    });
  } else if (scenario === 'trulyEmpty') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ available: false, reason: '尚未运行过检索评测（scripts/eval_retrieval.py）。', report: null }),
      });
    });
  } else if (scenario === 'badShape') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ available: true, report: { groups: '这不是数组', g2_gate: null, dataset_size: 70 } }),
      });
    });
  } else if (scenario === 'emptyArray') {
    await page.route(RETRIEVAL, (r) => {
      hits.retrieval += 1;
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ available: true, report: { groups: [], g2_gate: null, dataset_size: 70 } }),
      });
    });
  }
  await page.goto(`${BASE}/eval`, { waitUntil: 'networkidle' });
  await settle(page);
  return { page, ctx, errors, hits };
}

/** 读 /eval 检索那一块的可见文字与关键节点存在性（一次 evaluate 全拿）。 */
function readRetrievalBlock(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const card = Array.from(document.querySelectorAll('.surface')).find((c) =>
      /检索评测/.test(c.textContent || ''),
    );
    const text = (card || document.body).innerText.replace(/\s+/g, ' ');
    return {
      有错误态: Boolean(card && card.querySelector('.error-state')),
      错误角色: card?.querySelector('.error-state')?.getAttribute('role') ?? null,
      有空态: Boolean(card && card.querySelector('.empty')),
      整页崩: /该模块加载失败|加载失败，请重试/.test(document.body.innerText),
      文本: text.slice(0, 420),
    };
  });
}

/** 等**检索那一块**落定再读。
 *
 *  ⚠️ 两个坑都踩过：
 *  1. QueryClient 配了 `retry: 1`（src/main.tsx:23），第一次失败后查询还在重试，
 *     此刻是骨架屏 —— 直接读会把"错误态"读成"什么都没渲染"。
 *  2. 等待条件不能写 `.ant-table-tbody`：同页**消融那张表**的 tbody 一直在场，
 *     于是等待立刻满足、检索块还在骨架上，判据以"空卡片"的形式假红。
 *     所以这里把探针限定在检索这一块：错误态 / 空态 / 真数据，三选一才算落定。 */
async function settle(page) {
  /* ⚠️ 第二参数是 **arg**，不是 options：写成 `}, { timeout: 20000 })` 时那个 20 秒根本没生效，
     实际吃的是默认 30 秒（Z 趟 7d 那一幕把它逼出来的 —— 症状是"8 秒的等待跑了 30 秒"）。
     签名：`waitForFunction(pageFunction, arg, options)`。 */
  await page.waitForFunction(() => {
    const card = Array.from(document.querySelectorAll('.surface')).find((c) =>
      /检索评测/.test(c.textContent || ''),
    );
    if (!card) return false;
    if (card.querySelector('.error-state') || card.querySelector('.empty')) return true;
    return /参考组 Top-3/.test(card.innerText || '');
  }, null, { timeout: 20000 });
  await page.waitForTimeout(200);
}

async function passEvalErrorStates(browser) {
  console.log('\n== AB /eval 错误态与形状闸门（F-1 / F-2 / F-4 / F-5）==');

  /* ---------- 前件：一切正常时，表格与可排序表头都在 ---------- */
  const ok = await openEval(browser, 'normal');
  const baseline = await ok.page.evaluate(() => ({
    sortableTh: document.querySelectorAll('th.ant-table-column-has-sorters').length,
    bodyRows: document.querySelectorAll('.ant-table-tbody tr').length,
    有错误态: Boolean(document.querySelector('.error-state')),
  }));
  check('AB 前件（正常桩）：检索表真的渲染出行与可排序表头',
    baseline.sortableTh >= 4 && baseline.bodyRows >= 1 && baseline.有错误态 === false, baseline);

  /* ---------- F-4：释义触发器 ---------- */
  const info = await ok.page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('.metric-info'));
    return {
      n: btns.length,
      全是按钮: btns.length > 0 && btns.every((b) => b.tagName === 'BUTTON'),
      可聚焦: btns.every((b) => b.tabIndex >= 0),
      /** 可达名 = 按钮内容（F-4 之后没有 aria-label 了：那句全文以 `.sr-only`
       *  待在按钮里，焦点一落上去就读得出来。用 aria-label 反而会把内容整段盖掉）。 */
      name: btns.map((b) => (b.textContent || '').trim()),
      图标被藏起来了: btns.every((b) => {
        const i = b.querySelector('.anticon');
        return !i || i.getAttribute('aria-hidden') === 'true';
      }),
      // 外层卡片上那个重复的原生 title 必须已经拿掉（会和 Tooltip 叠两层）
      外层原生title: Array.from(document.querySelectorAll('.metric')).filter((m) => m.getAttribute('title')).length,
    };
  });
  check('AB F-4：4 个指标释义是可聚焦的 <button> 而不是 span 图标',
    info.全是按钮 && info.可聚焦 && info.n >= 4, info);
  check('AB F-4：按钮的可达名是"什么的口径说明：全文"，不是图标名 info-circle',
    info.name.every((n) => /^.+的口径说明：.{20,}$/.test(n)) &&
      !info.name.some((n) => n.includes('info-circle')),
    info.name.map((n) => n.slice(0, 34)));
  check('AB F-4：里面那个装饰图标 aria-hidden（否则读屏会连图标名一起念）',
    info.图标被藏起来了 === true, info);
  check('AB F-4：同一句释义不再挂两遍（卡片上没有原生 title 了）', info.外层原生title === 0, info);

  /* ---------- F-5：可排序表头的焦点环 ---------- */
  // 先只聚焦，**不在这个 evaluate 里读样式**：
  // AntD 给这一列写了 `transition: 0.32s`（不带属性名 = 全部属性），
  // outline-width 会从 `medium`(3px) 插值到我们声明的 2px、outline-color 从
  // currentColor(#4b5266) 插值到 #4f46e5 —— 聚焦后立刻读会拿到"3px + 灰"，
  // 看起来完全像是我们的规则没生效。（本仓第 N 次撞在过渡中间值上。）
  const focused = await ok.page.evaluate(() => {
    const th = document.querySelector('th.ant-table-column-has-sorters');
    if (!th) return false;
    th.focus();
    return true;
  });
  await ok.page.waitForTimeout(450);
  const ring = await ok.page.evaluate(() => {
    const th = document.querySelector('th.ant-table-column-has-sorters');
    if (!th) return { found: false };
    const cs = getComputedStyle(th);
    // 是谁给的环？逐条问元素自己 `matches()`，别按"选择器里含 has-sorters"筛 ——
    // 赢家也可能来自一条更宽的选择器。
    const rules = [];
    for (const sheet of Array.from(document.styleSheets)) {
      let list;
      try {
        list = sheet.cssRules;
      } catch {
        continue; // 跨域样式表读不到，跳过（本页没有）
      }
      for (const r of Array.from(list || [])) {
        if (!r.selectorText || !/outline/.test(r.cssText)) continue;
        let hit = false;
        try {
          hit = th.matches(r.selectorText);
        } catch {
          hit = false; // 伪元素选择器不能拿元素去 matches，忽略
        }
        if (hit) rules.push(r.cssText.slice(0, 190));
      }
    }
    return {
      found: true,
      还在这个th上: document.activeElement === th,
      focusVisible: th.matches(':focus-visible'),
      outlineStyle: cs.outlineStyle,
      outlineWidth: cs.outlineWidth,
      outlineColor: cs.outlineColor,
      // var() 在这个元素上解析成什么 —— 解析失败会让 outline-color 退成 currentColor，
      // 那是"写了主色环却量到灰环"的另一条可能路径，一起排掉。
      token在元素上: cs.getPropertyValue('--primary').trim(),
      环是主色: cs.outlineColor === 'rgb(79, 70, 229)',
      rules,
    };
  });
  check('AB F-5：前件 —— 焦点确实落在那条可排序表头上且 :focus-visible 命中',
    focused === true && ring.found === true && ring.还在这个th上 === true && ring.focusVisible === true,
    { focused, 还在这个th上: ring.还在这个th上, focusVisible: ring.focusVisible });
  check('AB F-5：聚焦可排序表头有计算得出来的 outline（AntD 的 outline:none 被压住了）',
    ring.outlineStyle !== 'none' && parseFloat(ring.outlineWidth) >= 2, ring.rules);
  check('AB F-5：焦点环吃的是主色 token 的 2px 环（不是别的环碰巧在）',
    ring.环是主色 === true && ring.outlineWidth === '2px',
    { got: ring.outlineColor, width: ring.outlineWidth, token: ring.token在元素上 });
  await ok.ctx.close();

  /* ---------- F-1：三档故障 + 真空态 ---------- */
  const cli = 'python scripts/eval_retrieval.py';
  const s500 = await openEval(browser, 'http500');
  const b500 = await readRetrievalBlock(s500.page);
  check('F-1 HTTP 500：走错误态而不是空态（过去这里画的是"还没跑过评测"）',
    b500.有错误态 === true && b500.有空态 === false, b500);
  check('F-1 HTTP 500：错误态三件套 HTTP 码 / 机器码 / request_id 都在场',
    /HTTP 500/.test(b500.文本) && /internal_error/.test(b500.文本) && /req-probe-500/.test(b500.文本),
    b500.文本.slice(0, 200));
  check('F-1 HTTP 500：不再把用户支去跑 CLI（那条命令不许出现在错误态里）',
    !b500.文本.includes(cli) && !/跑一次评测即可生成/.test(b500.文本), b500.文本.slice(0, 200));
  check('F-1 HTTP 500：错误态带 role=alert（读屏能被告知），且没有整页崩',
    b500.错误角色 === 'alert' && b500.整页崩 === false, b500);
  /* 重试按钮：点一下必须真的又发一次请求（不是"再敲一遍 CLI"的假按钮） */
  const before = s500.hits.retrieval;
  await s500.page.click('.error-state-retry');
  await s500.page.waitForTimeout(700);
  check('F-1 重试按钮：点它 = 重取这一份数据（桩被命中次数 +≥1）',
    s500.hits.retrieval > before, { before, after: s500.hits.retrieval });
  check('F-1 这一趟没有 pageerror', s500.errors.length === 0, s500.errors.slice(0, 3));
  await s500.ctx.close();

  const s404 = await openEval(browser, 'http404');
  const b404 = await readRetrievalBlock(s404.page);
  check('F-1 HTTP 404：与 500 说法不同（各自的码要露出来）',
    b404.有错误态 === true && /HTTP 404/.test(b404.文本) && /not_found/.test(b404.文本), b404.文本.slice(0, 180));
  await s404.ctx.close();

  const sab = await openEval(browser, 'abort');
  const bab = await readRetrievalBlock(sab.page);
  check('F-1 断网：说"请求未送达"而不是编一个 HTTP 码',
    bab.有错误态 === true && /请求未送达/.test(bab.文本) && !/HTTP \d{3}/.test(bab.文本), bab.文本.slice(0, 180));
  await sab.ctx.close();

  const sem = await openEval(browser, 'trulyEmpty');
  const bem = await readRetrievalBlock(sem.page);
  /* 反向钉：真的没跑过时，那条 CLI 指引**应该**还在 —— 错误态与空态分家不等于删掉指引。 */
  check('F-1 反向钉：available:false 仍是空态，且 CLI 指引照旧在场',
    bem.有空态 === true && bem.有错误态 === false && bem.文本.includes(cli) && /尚未运行过/.test(bem.文本),
    bem.文本.slice(0, 200));
  await sem.ctx.close();

  /* ---------- F-2：形状闸门 ---------- */
  const sbad = await openEval(browser, 'badShape');
  const bbad = await readRetrievalBlock(sbad.page);
  check('F-2 groups 不是数组：整页没进 ErrorBoundary（过去是 groups.map 炸掉）',
    bbad.整页崩 === false, bbad);
  check('F-2 groups 不是数组：报"格式不识别"而不是伪装成"还没跑过评测"',
    bbad.有错误态 === true && bbad.有空态 === false && /格式不识别/.test(bbad.文本), bbad.文本.slice(0, 200));
  /* 形状问题没有"一次失败的请求"可言 —— 把 HTTP/未送达那行硬套上去是另一种假指引。
     （第一版就这么错过：错误态复用了请求错误的 meta，量出来写着"请求未送达"。） */
  check('F-2 形状不识别不许顺带谎称"请求未送达"（它没有请求上下文）',
    /请求未送达|HTTP \d{3}/.test(bbad.文本) === false, bbad.文本.slice(0, 200));
  const ablationAlive = await sbad.page.evaluate(() =>
    Array.from(document.querySelectorAll('.surface')).some((c) => /消融对比|消融/.test(c.textContent || '')) &&
    Boolean(document.querySelector('.ant-table-tbody')));
  check('F-2 一块坏不拖另一块：消融那张表照常渲染', ablationAlive === true, ablationAlive);
  check('F-2 这一趟没有 pageerror', sbad.errors.length === 0, sbad.errors.slice(0, 3));
  await sbad.ctx.close();

  /* 反向对照：空数组是**合法**形状 ⇒ 不许报"格式不识别"（证明上一条不是恒真） */
  const sarr = await openEval(browser, 'emptyArray');
  const barr = await readRetrievalBlock(sarr.page);
  check('F-2 对照：groups:[] 是合法空值，判据不把它报成格式问题',
    /格式不识别/.test(barr.文本) === false && barr.整页崩 === false, barr.文本.slice(0, 160));
  await sarr.ctx.close();

  /* ---------- F-11 复核：fixed:'left' 的外层横滚 + 粘性左列 ---------- */
  const narrow = await openEval(browser, 'normal', { width: 390, height: 844 });
  const sticky = await narrow.page.evaluate(async () => {
    const th = document.querySelector('th.ant-table-cell-fix-left');
    const box = th?.closest('.scrollx-box') || th?.closest('.table-wrap');
    if (!th || !box) return { found: false };
    const beforeX = Math.round(th.getBoundingClientRect().x);
    box.scrollLeft = 140;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const afterX = Math.round(th.getBoundingClientRect().x);
    const scrolled = box.scrollLeft;
    return {
      found: true,
      beforeX,
      afterX,
      scrolled,
      粘住了: scrolled > 20 && Math.abs(afterX - beforeX) <= 2,
      表头撑宽: { scrollWidth: th.scrollWidth, clientWidth: th.clientWidth },
    };
  });
  check('AB F-11 复核：390 下外层横滚 140px，粘性左列的表头 x 不动（fixed 仍然有效）',
    sticky.found && sticky.粘住了 === true, sticky);
  check('AB F-11 定性：报告量的 226>196 是 fixed 阴影伪元素撑出来的，不是文字被裁',
    sticky.found && sticky.表头撑宽.scrollWidth > sticky.表头撑宽.clientWidth, sticky.表头撑宽);
  await narrow.ctx.close();
}

/* ---------------- Z 趟：知识库上传页（A 档 · K1–K8 · 方案 §5 的 13 条） ---------------- */

/** 读 /knowledge 一屏的机械可比量（一次 evaluate 全拿，避免多次往返）。
 *  读的一律是 DOM 与 data-*，不读像素 —— 分段条那种东西，截图只能靠眼睛判。 */
function readKb(page) {
  return page.evaluate(() => {
    const btnText = (tr, re) =>
      Array.from(tr.querySelectorAll('button')).some((b) => re.test(b.textContent || ''));
    return {
      tiles: Array.from(document.querySelectorAll('.metric')).map((m) => ({
        标签: m.querySelector('.metric-label span:not(.anticon)')?.textContent?.trim() ?? '',
        读数: m.querySelector('.metric-value')?.textContent?.trim() ?? '',
      })),
      rows: Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row')).map((tr) => ({
        文件: tr.querySelector('.ant-table-cell')?.innerText?.trim() ?? '',
        徽标: tr.querySelector('.status-badge')?.innerText?.replace(/\s+/g, '') ?? '',
        在动: Boolean(tr.querySelector('.status-badge.is-live')),
        分段: tr.querySelector('.stage-bar')?.getAttribute('data-stages') ?? null,
        失败原文: tr.querySelector('.doc-error')?.innerText?.trim() ?? '',
        有重试: btnText(tr, /重试/),
        有删除: btnText(tr, /删除/),
      })),
      呼吸点总数: document.querySelectorAll('.status-badge.is-live').length,
      /* 整页有几条分段条：与"行数"一起看才知道"每行一条"是不是真的（行数会因空态/错误态为 0，
         分段条数则能抓到"表格没渲染但别处画了一条"这种怪形状）。 */
      分段条数: document.querySelectorAll('.stage-bar').length,
      accept: document.querySelector('input[type=file]')?.accept ?? null,
      /* 上传卡那句副说明（"单文件 ≤ N MB"到底在哪）：按**卡标题**找，不按 `.surface-sub`
         的全页第一个 —— 页面上有四张卡，写死序号的话加一张卡就认错人。 */
      上传副说明: (() => {
        const c = Array.from(document.querySelectorAll('.surface')).find(
          (x) => (x.querySelector('.surface-title')?.innerText || '').includes('上传文档'),
        );
        return c?.querySelector('.surface-sub')?.innerText?.trim() ?? '';
      })(),
      拖拽区: (() => {
        const d = document.querySelector('.up-drop');
        return d ? { tab: d.tabIndex, 名: d.getAttribute('aria-label') || '', role: d.getAttribute('role') } : null;
      })(),
      队列: Array.from(document.querySelectorAll('.up-row')).map((li) => ({
        阶段: li.getAttribute('data-phase') ?? '',
        文本: (li.innerText || '').replace(/\s+/g, ' ').trim(),
      })),
      批量提示: document.querySelector('.up-notice')?.innerText?.trim() ?? '',
      /* "整页降级"必须落在**那一页级的那张卡**上。第一版写成 `.app-content .error-state`，
         而"只有概览读不到"那张卡也在 `.app-content` 里 —— 于是概览先失败、列表还在路上那一帧
         就能把这条判绿（Z 趟 503 实测翻车就是这么来的）。 ⇒ 用 `kb-rag-down` 这个落点。 */
      整页错误态: Boolean(document.querySelector('.kb-rag-down .error-state')),
      概览错误卡: Boolean(document.querySelector('.kb-overview-error .error-state')),
      错误标题: document.querySelector('.error-state-title')?.innerText?.trim() ?? '',
      错误正文: document.querySelector('.error-state-message')?.innerText?.trim() ?? '',
      /* 附言（note）单独读：它是**页面自己推断出来的那句话**（"它没坏" / "还没回话"），
         也最容易在两路状态不同步时说过头。整页文本 220 字常常截不到它。 */
      概览附言: document.querySelector('.kb-overview-error .error-state-note')?.innerText?.trim() ?? '',
      空态: Boolean(document.querySelector('.empty')),
      横溢出: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      tabbar项数: document.querySelectorAll('.app-tabbar .tabbar-item').length,
      可横滚: (() => {
        /* ⚠️ `data-scrollable` 挂在**外层 .scrollx-frame** 上，不是 .scrollx-box（ui.tsx:528）。
           写在 .scrollx-box 上会恒读到 null，而"表格还能横滚"这条看起来完全像产品坏了。
           这里按"包着 .ant-table 的那一枚"取，避免同页有多个 frame 时认错。 */
        const f = Array.from(document.querySelectorAll('.scrollx-frame'))
          .find((x) => x.querySelector('.ant-table'));
        return f?.getAttribute('data-scrollable') ?? null;
      })(),
      /* 诊断三件套：503 / 未知状态这类"整页该换成另一副样子"的场景，只看一条布尔
         判红之后说不出**它到底演成了什么**（空表？骨架？还是压根没挂载）。
         这三项不参与任何断言，只在失败时随 got 打出来。 */
      骨架屏数: document.querySelectorAll('.skeleton').length,
      首段文本: (document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 220),
      粘性左列: Boolean(document.querySelector('.ant-table-cell-fix-left')),
      导航项: Array.from(document.querySelectorAll('.rail-nav button')).map((b) => ({
        名: b.getAttribute('aria-label') || '',
        当前: b.getAttribute('aria-current'),
      })),
    };
  });
}

/** 打开 /knowledge。场景改的是 mocks 里那份 kbState（每条路由现读，不在注册时固化），
 *  所以一个场景改完不会流进下一个场景 —— 每个 context 开头都 resetKb()。 */
async function openKnowledge(browser, scenario, opts = {}) {
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 1000 },
    colorScheme: opts.scheme || 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript(
    (scheme) => localStorage.setItem('trinity-console.theme', scheme),
    opts.scheme || 'light',
  );
  if (opts.hidden) {
    /* 与 Q 趟同一手法：Playwright 的页面永远 visible，不接管这两个属性，
       "在后台不轮询"这条路径根本造不出来，整条判据就是空跑。 */
    await ctx.addInitScript(() => {
      window.__hidden = true;
      Object.defineProperty(document, 'hidden', {
        configurable: true,
        get: () => window.__hidden === true,
      });
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (window.__hidden === true ? 'hidden' : 'visible'),
      });
    });
  }
  const page = await ctx.newPage();
  const errors = [];
  const reqs = [];
  /** 响应码流水：503 / 429 这些"桩到底生效没有"的问题，只看请求侧看不出来
   *  （请求发了、桩没接住、走代理拿到 404 —— 三种形态在 reqs 里长得一模一样）。 */
  const resp = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('response', (r) => {
    const u = r.url();
    if (u.includes('/api/knowledge/')) {
      resp.push({ 方法: r.request().method(), 码: r.status(), 地址: u.slice(u.indexOf('/api/')) });
    }
  });
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes('/api/knowledge/')) {
      reqs.push({ method: r.method(), url: u, ct: r.headers()['content-type'] || '' });
    }
  });
  const kb = resetKb();
  await installMocks(page);
  // 后注册的 route 先匹配（Playwright 语义），所以这些覆盖得住 installMocks 那份默认桩。
  // ⚠️ 这里用行注释：块注释里一旦写出"星号紧跟斜杠"那三个字符就会就地闭合，
  //    剩下的中文被当成代码 —— 本仓第四次栽在同一处（门槛 4 记着前三次）。
  const post = { mode: 'ok', calls: 0, inflight: 0, maxInflight: 0 };
  /** 手动闸门：`overviewDownFirst` 那一档把列表请求扣在这里，由 Z 趟自己放行（见那个场景的注释）。 */
  let releaseGate = () => {};
  const gate = new Promise((res) => {
    releaseGate = res;
  });
  let waitUntil = 'networkidle';
  const LIST = '**/api/knowledge/documents*';
  const envelope = (code, message) => ({ detail: { code, message, request_id: 'req-kb-probe' } });
  const list = (r) => r.fulfill(kbJson({ items: kb.docs, total: kb.docs.length }));
  const ack = (n, name, warnings) => ({
    document_id: `doc-newupload000${n}`,
    filename: name,
    status: 'pending',
    upload_at: '2026-09-26T10:40:00+08:00',
    status_url: `/knowledge/documents/doc-newupload000${n}`,
    warnings: warnings || [],
  });

  if (scenario === 'allTerminal') {
    kb.docs = kb.docs.filter((d) => d.status === 'ready' || d.status === 'failed');
    kb.overview.indexing_count = 0;
    kb.overview.document_count = kb.docs.length;
  } else if (scenario === 'indexingMismatch') {
    /* 故意让"概览说的"与"表里的"对不上：只有一行且是终态，概览却说 3 在索引。
       这样 tile 上那个数到底从哪来的，才有一条能判真伪的读法。 */
    kb.docs = [kb.docs[0]];
    kb.overview.indexing_count = 3;
    kb.overview.document_count = 3;
  } else if (scenario === 'unknownStatus') {
    kb.docs[1].status = 'verifying'; // 后端还没有这个状态，正是要验的情形（避坑 5）
  } else if (scenario === 'progress') {
    let n = 0;
    await page.route(LIST, (r) => {
      n += 1;
      if (n > 1) {
        kb.docs[1].status = 'ready';
        kb.docs[1].chunk_count = 7;
        kb.docs[1].indexed_at = '2026-09-26T10:22:01+08:00';
        kb.overview.indexing_count = 0;
      }
      return list(r);
    });
  } else if (scenario === 'ragDown') {
    const down = kbJson(envelope('rag_unavailable', '知识库服务不可用（探针桩，不是真故障）'), 503);
    await page.route('**/api/knowledge/overview', (r) => r.fulfill(down));
    await page.route(LIST, (r) => r.fulfill(down));
  } else if (scenario === 'overviewDownFirst') {
    /* 概览当场 503，文档表**扣在手上不放**（不是"延迟 N 秒"）：任何固定延迟都在跟
       页内定时器赛跑 —— 这些 context 从来没被真正合成过，Chrome 会把隐藏页的
       `setTimeout` 与 `requestAnimationFrame` 一起节流（实测扣 1.2s、再加到 2.5s 都输，
       读到的是"列表早就回来了"那一帧）。闸门挂在 node 侧，不受节流影响，
       所以这一帧是**造出来的**，不是**碰上的**。 */
    const down = kbJson(envelope('rag_unavailable', '概览这一路挂了（探针桩）'), 503);
    await page.route('**/api/knowledge/overview', (r) => r.fulfill(down));
    await page.route(LIST, async (r) => {
      if (r.request().method() !== 'POST') await gate;
      return list(r);
    });
    waitUntil = 'domcontentloaded'; // 有一条在途请求永不 idle
  } else if (scenario === 'legacyOverview') {
    /* 后端进程**没重启**：`/overview` 回的还是加 K3 之前的形状，整个字段不在。
       这不是假想的档位 —— 本机跑着的那个 :8001 就是这个状态，直到他重启为止。
       缺字段与接口挂了是两回事：页面要照常传、只是不能显示上限，也不能自己猜一个来拦。 */
    await page.route('**/api/knowledge/overview', (r) => {
      const o = { ...kb.overview };
      delete o.max_file_mb;
      /* 老进程缺的是**那一版之后加的所有字段**：K3 的 max_file_mb 与 R-03 的
         supported_formats 同时不在。两处降级各自独立判，谁也不许连坐（下面 9c 那两条）。 */
      delete o.supported_formats;
      return r.fulfill(kbJson(o));
    });
  } else if (scenario === 'noFormats') {
    /* 只缺 R-03 那个字段 —— 这是**本机重启一次后端就会落在的那一档**（HEAD 上 K3 已提交、
       R-03 还没有）。改的是 `kb.overview` 本身而不是响应副本：这样桩的 422 用的是
       "后端内部那份三种的清单"，界面上贴出来的那句才是**后端的清单**而不是页面的 —— 
       9d 那三条判据靠这个差别才分得开"谁在拒"。 */
    delete kb.overview.supported_formats;
  } else if (scenario === 'upload') {
    // 上限调成 1 MB：本地预拦那条判据不必真造一个 60 MB 的文件。
    kb.overview.max_file_mb = 1;
    await page.route(LIST, async (r) => {
      if (r.request().method() !== 'POST') return list(r);
      /* 同时在路上的份数：这是"串行"那条判据唯一的正证 —— 只数总请求数
         证明不了没有并发（5 份连着发也是 5 次）。fulfill 之后才减，
         所以这个计数覆盖的是"服务端还没答话"那一段。 */
      post.calls += 1;
      post.inflight += 1;
      if (post.inflight > post.maxInflight) post.maxInflight = post.inflight;
      let out;
      if (post.mode === 'ok') {
        kb.docs.unshift({
          ...kb.docs[0],
          document_id: `doc-newupload000${post.calls}`,
          filename: '新上传.md',
          status: 'pending',
          chunk_count: 0,
          token_count: 0,
          indexed_at: null,
        });
        out = kbJson(ack(post.calls, '新上传.md'), 201);
      } else if (post.mode === 'duplicate' && post.calls === 1) {
        out = kbJson(envelope('duplicate_document', '同名文档已存在：员工手册.md'), 409);
      } else if (post.mode === 'duplicate') {
        post.mode = 'ok';
        out = kbJson(ack(post.calls, '员工手册.md', ['旧版本的 12 个 chunk 已清除，正在重建索引']), 201);
      } else if (post.mode === 'fingerprint') {
        out = kbJson(envelope('fingerprint_mismatch', 'embedding 模型指纹与库不一致，需全量重索引'), 409);
      } else if (post.mode === 'full') {
        // Retry-After 给 1 秒而不是后端的 5 秒：判据因此测的是"读没读那个头"，
        // 不是"有没有把 5 抄进代码里"。
        out = {
          status: 429,
          headers: { 'content-type': 'application/json', 'Retry-After': '1' },
          body: JSON.stringify(envelope('queue_full', '索引队列已满（探针桩）')),
        };
      } else {
        out = kbJson(envelope('file_too_large', '文件 900000 字节超过上限 1 MB'), 422);
      }
      await r.fulfill(out);
      post.inflight -= 1;
      return undefined;
    });
  }
  await page.goto(`${BASE}/knowledge`, { waitUntil });
  const count = (method, frag) =>
    reqs.filter((r) => r.method === method && (!frag || r.url.includes(frag))).length;
  return { page, ctx, errors, reqs, resp, kb, post, count, releaseGate };
}

/** 往那个 1px 的 file input 里塞一份文件（Playwright 走 setInputFiles，不点按钮）。 */
function filePayload(name, kbSize, text) {
  const head = Buffer.from(text || `# ${name}\n`);
  if (!kbSize) return { name, mimeType: 'text/markdown', buffer: head };
  return {
    name,
    mimeType: 'application/octet-stream',
    // 只填到目标体积，不真分配 60 MB：本地预拦那条只看 size
    buffer: Buffer.concat([head, Buffer.alloc(kbSize * 1024 - head.length)]),
  };
}

async function passKnowledgeUpload(browser) {
  console.log('\n== Z 知识库上传页（A 档 / K1–K8）==');

  /* ---------- 场景 1：正常三份文档（ready / embedding / failed） ---------- */
  const s1 = await openKnowledge(browser, 'normal');
  const g1 = await readKb(s1.page);
  check('Z 前件：文档表真渲染出三行、每行一条分段条',
    g1.rows.length === 3 && g1.tiles.length === 4, { 行数: g1.rows.length, 读数块: g1.tiles.length });
  const byName = (frag) => g1.rows.find((r) => r.文件.includes(frag));
  check('Z 徽标文案逐个来自后端状态机（已索引 / 向量化中 / 索引失败）',
    byName('员工手册')?.徽标 === '已索引'
      && byName('消防')?.徽标 === '向量化中'
      && byName('巡检')?.徽标 === '索引失败',
    g1.rows.map((r) => [r.文件, r.徽标]));
  check('Z 分段条：ready = 四格全亮', byName('员工手册')?.分段 === 'done,done,done,done', byName('员工手册'));
  check('Z 分段条：embedding = 前三格亮 + 第四格在动', byName('消防')?.分段 === 'done,done,done,active', byName('消防'));
  check('Z 分段条：failed 把红标停在 error_stage 那一格（不是最后一格）',
    byName('巡检')?.分段 === 'done,done,done,failed', byName('巡检'));
  check('Z 失败行：error_message 原文上屏 + 只有失败行给重试按钮',
    /探针桩/.test(byName('巡检')?.失败原文 || '')
      && byName('巡检')?.有重试 === true
      && byName('员工手册')?.有重试 === false,
    g1.rows.map((r) => [r.有重试, r.失败原文]));
  check('Z 呼吸点是双向钉：终态行不呼吸、非终态行呼吸（EV-20 那条规矩）',
    byName('员工手册')?.在动 === false && byName('巡检')?.在动 === false && byName('消防')?.在动 === true,
    g1.rows.map((r) => r.在动));
  check('Z 拖拽区可键盘操作：role=button + tabIndex=0 + 名字里说了怎么按',
    g1.拖拽区?.role === 'button' && g1.拖拽区?.tab === 0 && /回车/.test(g1.拖拽区?.名 || ''), g1.拖拽区);
  /* R-03：`accept` **不是页面自带的那份**，是从 `/overview` 的 `supported_formats` 推出来的。
     桩给四种（含页面从没写过的 docx），所以"页面写死 pdf/md/txt"那版实现会在这里当场翻红 ——
     与下面 33 那条同一支纪律：**桩值必须避开缺陷值**，否则判据恒真。
     后端那份是 `sorted(常量)`、页面也排序，所以这个串逐字可比。 */
  check('Z accept 由响应的 supported_formats 推导（桩给四种、含页面从没写过的 docx）',
    g1.accept === '.docx,.md,.pdf,.txt', g1.accept);
  const nav4 = g1.导航项;
  check('Z 导航四个入口、aria-label 齐、aria-current 只在当前那一项',
    nav4.length === 4
      && nav4.every((n) => n.名.length > 0)
      && nav4.filter((n) => n.当前 === 'page').map((n) => n.名).join('') === '知识库',
    nav4);
  /* tooltip 的 desc 不在 DOM 属性上（AntD 把它渲染成 portal 里的弹层），
     只能真的把焦点放上去读。`desc` 少给一个字段时这里会读到"知识库 · "——
     正好是方案 §2.2 说的那个"顶栏 tooltip 会空"的形态。 */
  await s1.page.focus('.rail-nav button:nth-child(4)');
  await s1.page.waitForTimeout(500);
  const tip = (await s1.page.locator('.ant-tooltip-inner').first().innerText().catch(() => '')).trim();
  check('Z 第四项 tooltip 的 desc 非空（label · desc 两截都在）',
    /^知识库 · \S/.test(tip), tip);
  /* 桩里给的是 **33**，不是后端的默认 50 —— 判"读的是响应"必须让桩值避开缺陷值，
     否则"页面写死 50"与"页面读接口"印出来一模一样（这条是本轮自己踩到之后改的）。
     读点也换成上传卡那句副说明，而不是整页 innerText：整页里"50"可能从别处冒出来。 */
  const g1sub = await readKb(s1.page);
  check('Z 上限那句读的是 overview.max_file_mb（桩给 33），不是页面写死的后端默认 50',
    /单文件 ≤ 33 MB/.test(g1sub.上传副说明) && !/≤ 50/.test(g1sub.上传副说明),
    { 副说明: g1sub.上传副说明 });
  check('Z「支持 …」那句也读同一份清单（页面不再另抄一份）',
    /支持 docx \/ md \/ pdf \/ txt/.test(g1sub.上传副说明) && !/只收/.test(g1sub.上传副说明),
    { 副说明: g1sub.上传副说明 });
  /* 白名单**在场**时照样本地挡人，但挡人的那份名单是响应给的 ⇒ 文案里列的是四种。
     写死三种的实现在这条下会印出"只收 pdf / md / txt"（旧文案里那句"这一版只收"）。 */
  await s1.page.setInputFiles('input[type=file]', filePayload('现场照片.png', 0));
  await s1.page.waitForTimeout(250);
  const g1png = await readKb(s1.page);
  check('Z 不在白名单里的文件本地拦下、不出网，且文案列的是**响应给的那四种**',
    s1.count('POST') === 0
      && /\.png/.test(g1png.队列[0]?.文本 || '')
      && /docx \/ md \/ pdf \/ txt/.test(g1png.队列[0]?.文本 || ''),
    g1png.队列);
  await s1.ctx.close();

  /* ---------- 场景 2：全终态 ⇒ 轮询必须自己停 ---------- */
  const s2 = await openKnowledge(browser, 'allTerminal');
  await s2.page.waitForTimeout(400);
  const idle0 = s2.count('GET', '/documents');
  await s2.page.waitForTimeout(3000);
  check('Z 终态即停：全终态之后 3 秒内 0 次列表请求',
    s2.count('GET', '/documents') === idle0, { 之前: idle0, 之后: s2.count('GET', '/documents') });
  const g2 = await readKb(s2.page);
  check('Z 全终态整页呼吸点数为 0（终态不许留动画）', g2.呼吸点总数 === 0, g2.呼吸点总数);
  await s2.ctx.close();

  /* ---------- 场景 3：概览与行数不一致 ⇒ tile 跟着概览走 ---------- */
  const s3 = await openKnowledge(browser, 'indexingMismatch');
  const g3 = await readKb(s3.page);
  const tile3 = g3.tiles.find((t) => t.标签 === '索引中');
  check('Z「索引中」读 overview.indexing_count=3，不前端数行（表里只有 1 行且是终态）',
    tile3?.读数 === '3' && g3.rows.length === 1, { tile: tile3, 行数: g3.rows.length });
  await s3.ctx.close();

  /* ---------- 场景 4：后端来了个我们不认识的状态 ---------- */
  const s4 = await openKnowledge(browser, 'unknownStatus');
  const g4 = await readKb(s4.page);
  const unk = g4.rows.find((r) => r.文件.includes('消防'));
  check('Z 未知状态原文上屏（既不译成"已索引"，也不译成"索引中"）',
    unk?.徽标 === 'verifying', unk);
  check('Z 未知状态不转圈（不认识的东西不许当成"还在跑"）', unk?.在动 === false, unk);
  check('Z 未知状态四格全空（点任何一格都是在讲"它跑过那一步"）',
    unk?.分段 === 'off,off,off,off', unk);
  check('Z 未知状态不塌成空表：三行仍在', g4.rows.length === 3, g4.rows.length);
  await s4.ctx.close();

  /* ---------- 场景 5：标签页在后台 ⇒ 不轮询（Q 趟同一手法） ---------- */
  const s5 = await openKnowledge(browser, 'normal', { hidden: true });
  const hid0 = s5.count('GET', '/documents');
  await s5.page.waitForTimeout(2600);
  check('Z 后台标签不白打：隐藏期间 2.6 秒内 0 次列表请求（呼吸点仍在）',
    s5.count('GET', '/documents') === hid0 && (await readKb(s5.page)).呼吸点总数 === 1,
    { 请求: s5.count('GET', '/documents'), 起点: hid0 });
  await s5.ctx.close();

  /* ---------- 场景 6：轮询把状态跟到了终态 ---------- */
  const s6 = await openKnowledge(browser, 'progress');
  await s6.page.waitForFunction(
    () => {
      const tr = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
        .find((x) => (x.innerText || '').includes('消防'));
      return !!tr && !tr.querySelector('.status-badge.is-live');
    },
    null,
    { timeout: 12000 },
  );
  const g6 = await readKb(s6.page);
  const done6 = g6.rows.find((r) => r.文件.includes('消防'));
  check('Z 轮询跟手：那份从"向量化中"变成"已索引"，四格走满',
    done6?.徽标 === '已索引' && done6?.分段 === 'done,done,done,done', done6);
  check('Z 到终态后 chunk 数跟着落定（7 那格不是前端补的）',
    (done6?.文件 || '').length > 0
      && (await s6.page.evaluate(() => {
        const tr = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
          .find((x) => (x.innerText || '').includes('消防'));
        return (tr?.innerText || '').includes('7');
      })),
    done6);
  await s6.ctx.close();

  /* ---------- 场景 7：上传链路（一个 context 里跑完六种回法） ----------
     每个子用例前 step()：清空请求流水 + 复位桩的计数与回法。
     不清的话后面的"第几次请求"全是上一案的账，判据会以错误的理由通过。 */
  const s7 = await openKnowledge(browser, 'upload');
  const step = (mode) => {
    s7.reqs.length = 0;
    s7.post.calls = 0;
    s7.post.inflight = 0;
    s7.post.maxInflight = 0;
    s7.post.mode = mode;
  };
  const clearQueue = async () => {
    const btn = s7.page.locator('button', { hasText: '清空列表' });
    // 等按钮出现 = 等这一份传完（busy 期间它不渲染），不等就会把上一案的行留给下一案。
    await btn.first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
    if (await btn.count()) {
      await btn.first().click();
      await s7.page.waitForTimeout(150);
    }
  };

  /* ---- 队列那一族控件的定位：**一律钉在 .up-list 里**，两处实测坑 ----
     ① 别拿 `document.body.innerText` 正则等控件出现。`.metric-tile` 的口径说明是以
        `.sr-only` 常驻 DOM 的（F-4 换的那个挂载点），那几句话里正好带着"覆盖重建"
        四个字 ⇒ 第一帧就"命中"，等到的是空气（上一版 7d 就是这么红的）。
     ② 别拿 `page.locator('button', {hasText:'覆盖重建'})` 点按钮。同一句 `.sr-only`
        裹在 `.metric-info` 那枚 **button** 里，而它在 DOM 里排在上传区前面 ——
        `.first()` 点到的 ⓘ 按钮，队列行纹丝不动，然后等 30 秒超时。
     超时不打断整趟：把 POST 流水与队列现场打出来继续跑，让判据自己红。
     ⚠️ `waitForFunction(fn, arg, options)` 是**三个**参数：只写两个时那个
     `{ timeout: 8000 }` 会被当成 arg，超时悄悄退回默认 30 秒。
     全文件`waitForFunction`一共 9 处，本轮把两处错形的都改了（这里一处 + AB 的 `settle()` 一处），
     其余 6 处本来就是三参写法 —— 别把它记成"满文件都是"，那会让人以为改完了。 */
  const waitPhase = async (want, ms = 8000) => {
    try {
      await s7.page.waitForFunction(
        (p) =>
          Array.from(document.querySelectorAll('.up-row')).some(
            (li) => li.getAttribute('data-phase') === p,
          ),
        want,
        { timeout: ms },
      );
      return true;
    } catch {
      const g = await readKb(s7.page);
      console.log(
        `      · 等 data-phase=${want} 超时 · POST=${JSON.stringify(
          s7.reqs.filter((r) => r.method === 'POST').map((r) => r.url),
        )} · 队列=${JSON.stringify(g.队列)}`,
      );
      return false;
    }
  };
  /** 只在本队列行里找按钮（见上面 ②）。
   *  ⚠️ 两字按钮名要传**正则**：AntD v5 的 Button 会给"恰好两个汉字"的标签自动插一个
   *     真空格（`textContent` 是"放 弃"不是"放弃"），字符串 `hasText` 就点不到 ——
   *     本轮 7d-2 实测踩到。三字以上、或带 icon 的按钮不受影响（"覆盖重建""仍要删除""删除 +icon"都正常）。 */
  const rowBtn = (text) =>
    s7.page.locator('.up-list button', { hasText: text }).first();

  /* 7a R-03 反过来那一刀：响应里给了 docx，页面就**不许**再按自己那份旧清单拦它。
     桩给的白名单含 docx（页面从来没写过这个格式），所以"照旧拦"会红在这里 ——
     这正是 R-03 要修的那个方向：窄了误拒，一份本来能索引的文档被拦在门外。
     本地该拦的那一半由 s1 的 .png 那条钉（不在响应清单里 ⇒ 不出网）。 */
  step('ok');
  await s7.page.setInputFiles('input[type=file]', filePayload('周报.docx', 0, 'x'));
  await waitPhase('accepted');
  const g7a = await readKb(s7.page);
  check('Z 响应给了 docx ⇒ 页面不再按自己那份旧清单拦：出网一次且状态是已受理',
    s7.count('POST') === 1 && g7a.队列[0]?.阶段 === 'accepted'
      && !/不支持/.test(g7a.队列[0]?.文本 || ''), g7a.队列);
  await clearQueue();

  // 7b 体积预拦：上限来自 overview（这个场景里被设成 1 MB），1.27 MB 就该被挡
  step('ok');
  await s7.page.setInputFiles('input[type=file]', filePayload('大一份.md', 1300));
  await s7.page.waitForTimeout(250);
  const g7b = await readKb(s7.page);
  check('Z 超限文件本地拦下，数字取自后端给的 max_file_mb（1），不出网',
    s7.count('POST') === 0 && /超过单文件上限 1 MB/.test(g7b.队列[0]?.文本 || ''), g7b.队列);
  await clearQueue();

  // 7c 正常受理 + 验收项：FormData 的 header
  step('ok');
  await s7.page.setInputFiles('input[type=file]', filePayload('新上传.md', 0, '# 新上传\n正文'));
  await waitPhase('accepted');
  const postReq = s7.reqs.find((r) => r.method === 'POST');
  check('Z 验收项：上传请求的 content-type 是带 boundary 的 multipart（手写死 json 立刻红）',
    /^multipart\/form-data; boundary=/.test(postReq?.ct || ''), postReq?.ct);
  const g7c = await readKb(s7.page);
  check('Z 受理后那一行只说"进队列"，进度交给文档表（同屏不出现两份进度）',
    /进度见下方文档表/.test(g7c.队列[0]?.文本 || '') && s7.post.maxInflight === 1, g7c.队列);
  await clearQueue();

  // 7d 409 同名 → 一次确认 → overwrite=true 重发，且 warning 上屏
  step('duplicate');
  await s7.page.setInputFiles('input[type=file]', filePayload('员工手册.md', 0));
  await waitPhase('needs-overwrite');
  const g7d1 = await readKb(s7.page);
  check('Z 409 同名：后端原文上屏 + 给"覆盖重建"，且此时还没发第二次请求',
    s7.count('POST') === 1 && /同名文档已存在/.test(g7d1.队列[0]?.文本 || ''), g7d1.队列);
  await rowBtn('覆盖重建').click();
  await waitPhase('accepted');
  const g7d2 = await readKb(s7.page);
  check('Z 确认后第二个请求真的带 overwrite=true（不是前端自己假装成功）',
    s7.reqs.some((r) => r.method === 'POST' && r.url.includes('overwrite=true')), s7.reqs.filter((r) => r.method === 'POST').map((r) => r.url));
  check('Z 覆盖重建的 warning 上屏（旧索引已清除 ≠ 只报"上传成功"）',
    /12 个 chunk 已清除/.test(g7d2.队列.map((q) => q.文本).join(' ')), g7d2.队列);
  await clearQueue();

  /* 7d-2 同一个 409 按"放弃"：这一份就地取消，**不许**替用户补发第二个请求。
     只有"点覆盖重建才重发"这条正向判据时，把 放弃 做成"顺手也发一次"是测不出来的。 */
  step('duplicate');
  await s7.page.setInputFiles('input[type=file]', filePayload('员工手册.md', 0));
  await waitPhase('needs-overwrite');
  await rowBtn(/放\s*弃/).click();
  await s7.page.waitForTimeout(400);
  const g7d3 = await readKb(s7.page);
  check('Z 409 上按"放弃"：行没了且总共只发过一次请求（确认这一步不能替用户决定）',
    s7.count('POST') === 1 && g7d3.队列.length === 0, { 请求: s7.count('POST'), 队列: g7d3.队列 });

  // 7e 409 指纹：必须与"重名"分开说（避坑 6）
  step('fingerprint');
  await s7.page.setInputFiles('input[type=file]', filePayload('指纹.md', 0));
  await waitPhase('rejected');
  const g7e = await readKb(s7.page);
  check('Z 指纹 409 说的是"换模型要重索引"，且不给覆盖重建按钮',
    !/覆盖重建/.test(g7e.队列[0]?.文本 || '') && /重索引/.test(g7e.队列[0]?.文本 || '')
      && (await rowBtn('覆盖重建').count()) === 0, g7e.队列);
  await clearQueue();

  // 7f 429 队列满：按 Retry-After 退避，只自动重试一次
  step('full');
  await s7.page.setInputFiles('input[type=file]', filePayload('挤一挤.md', 0));
  /* 等的是"那一行的那句话"，不是整页文案（见上面 waitPhase 的 ①）；退避期间行仍在
     data-phase=waiting，所以按属性 + 该行的 .up-msg 文本一起认。 */
  await s7.page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll('.up-row[data-phase="waiting"] .up-msg')).some((el) =>
        /1 秒后自动重试一次/.test(el.textContent || ''),
      ),
    null,
    { timeout: 8000 },
  );
  check('Z 429 读的是 Retry-After（桩给 1 秒）：文案里的秒数不是抄来的 5',
    s7.count('POST') === 1, { 次数: s7.count('POST') });
  await waitPhase('rejected', 6000);
  const g7f = await readKb(s7.page);
  check('Z 429 自动重试恰好一次，仍失败就把行留在"没传上去"、不许谎报成功',
    s7.count('POST') === 2 && /已按 1s 自动重试过一次/.test(g7f.队列[0]?.文本 || '')
      && g7f.队列[0]?.阶段 === 'rejected',
    { 次数: s7.count('POST'), 行: g7f.队列[0] });
  await clearQueue();

  // 7g 后端 422（大小之外的那类拒收）：message 原文照贴，不自己编
  step('tooLarge');
  await s7.page.setInputFiles('input[type=file]', filePayload('刚过线.md', 900));
  await waitPhase('rejected');
  const g7g = await readKb(s7.page);
  check('Z 后端 422 的 message 原样上屏（本地预拦放过去了，兜底那条仍要说人话）',
    /900000 字节超过上限 1 MB/.test(g7g.队列[0]?.文本 || ''), g7g.队列);
  await clearQueue();

  // 7h K5：一次拖 7 份，只收 5 份，且说清丢了几个；整批必须串行
  step('ok');
  await s7.page.setInputFiles(
    'input[type=file]',
    Array.from({ length: 7 }, (_, i) => filePayload(`批量${i}.md`, 0)),
  );
  await s7.page.waitForFunction(
    () => /后面 2 份没加入队列/.test(document.querySelector('.up-notice')?.textContent || ''),
    null,
    { timeout: 8000 },
  );
  const g7h = await readKb(s7.page);
  check('Z 一次 7 份：只排 5 份进队列，并把"后面 2 份没进来"说出来（不是静默丢弃）',
    g7h.队列.filter((q) => q.阶段 !== 'rejected').length <= 5 && /后面 2 份没加入队列/.test(g7h.批量提示),
    { 队列: g7h.队列.length, 提示: g7h.批量提示 });
  await s7.page.waitForTimeout(1500);
  /* 串行 ≠ 少发几个请求：只数总数证明不了没并发。这里的峰值并发是桩当场量的
     （服务端还没答话时第二份有没有出发），等于 1 才算串行。 */
  check('Z 串行不是并发：峰值并发 = 1（并发会把后端的整读内存打爆，避坑 3）',
    s7.post.maxInflight === 1 && s7.count('POST') >= 2,
    { 峰值并发: s7.post.maxInflight, 已发: s7.count('POST') });
  await s7.ctx.close();

  /* ---------- 场景 8：删除有二次确认（第一下不许出网） ---------- */
  const s8 = await openKnowledge(browser, 'normal');
  // 同样钉在表里：`.metric-info` 那枚 ⓘ 按钮也是一枚 button，见 Z 趟上面 ②。
  await s8.page.locator('.ant-table button', { hasText: '删除' }).first().click();
  await s8.page.waitForTimeout(350);
  check('Z 删除第一下只弹确认，DELETE 请求为 0（与取消任务同一口径）',
    s8.count('DELETE') === 0 && /仍要删除/.test(await s8.page.innerText('body')), { DELETE: s8.count('DELETE') });
  await s8.page.locator('button', { hasText: '仍要删除' }).first().click();
  await s8.page.waitForFunction(
    () => document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length === 2,
    null,
    { timeout: 6000 },
  );
  check('Z 确认之后才真的发 DELETE，且列表跟着少一行（不是只弹个"已删除"）',
    s8.count('DELETE') === 1 && (await readKb(s8.page)).rows.length === 2,
    { DELETE: s8.count('DELETE'), 行数: (await readKb(s8.page)).rows.length });

  /* 重试：方案 §5 第 9 条。桩这次**真的改了 kbState**（`failed → pending`、`error_*` 清空），
     所以判据能问"那一行回到第一段了没有"，而不只是"请求发出去了没有"。
     分段条要能往回走 —— 如果谁把它实现成"只许前进的单调条"，这一行就会停在红格上。 */
  await s8.page.locator('.ant-table button', { hasText: /重\s*试/ }).first().click();
  await s8.page.waitForFunction(
    () => Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
      .some((tr) => (tr.innerText || '').includes('巡检')
        && tr.querySelector('.stage-bar')?.getAttribute('data-stages') === 'active,todo,todo,todo'),
    null,
    { timeout: 6000 },
  );
  const g8 = await readKb(s8.page);
  const retried = g8.rows.find((x) => x.文件.includes('巡检'));
  check('Z 重试恰好一个 POST .../retry，那一行从「索引失败」回到第一段（排队中）',
    s8.count('POST', '/retry') === 1 && retried?.徽标 === '排队中'
      && retried?.分段 === 'active,todo,todo,todo' && retried?.有重试 === false,
    { POST: s8.reqs.filter((x) => x.method === 'POST').map((x) => x.url), 行: retried });
  await s8.ctx.close();

  /* ---------- 场景 9：503 整页降级，不许演成"库里没东西" ---------- */
  const s9 = await openKnowledge(browser, 'ragDown');
  /* 给 react-query 一次重试的余地（`main.tsx` 的默认 `retry:1` ⇒ 503 会再打一次），
     否则可能读到"还在路上"那一帧，把桩的问题与页面的问题混成一个红。 */
  await s9.page
    .waitForFunction(() => Boolean(document.querySelector('.kb-rag-down .error-state')), null, { timeout: 8000 })
    .catch(() => {});
  const g9 = await readKb(s9.page);
  const diag9 = {
    错误态: g9.整页错误态,
    空态: g9.空态,
    行数: g9.rows.length,
    骨架: g9.骨架屏数,
    概览卡: g9.概览错误卡,
    响应: s9.resp,
    首段: g9.首段文本,
  };
  check('Z 503：整页一条错误说明 + 重试出口，不出现空表/空态假象',
    g9.整页错误态 && !g9.空态 && g9.rows.length === 0, diag9);
  check('Z 503 那句说的是"服务不可用"，并带上后端原文',
    /服务端读不到知识库/.test(g9.错误标题) && g9.错误正文.includes('探针桩'),
    { 标题: g9.错误标题, 正文: g9.错误正文, 首段: g9.首段文本 });
  await s9.ctx.close();

  /* ---------- 场景 9b：概览先失败、文档表慢一拍（中间那一帧说的话要站得住） ----------
     上一版这里栽过：`.app-content .error-state` 把"只有概览读不到"那张卡也算成了"整页降级"，
     于是 503 那条判据在竞态里红了一次 —— 红得对，但理由是错的。现在落点分开，
     这一档专门量那一帧：页面不许在那一刻断言"文档表没坏"，因为它**还没回话**。 */
  const s9b = await openKnowledge(browser, 'overviewDownFirst');
  /* 列表被 node 侧闸门扣住 ⇒ "只有概览失败"这一帧是**造出来的**，不用跟页内定时器抢。
     ⚠️ 前两版都是延迟对撞（1.2s、2.5s）+ `polling: 100`，全输：这些 context 从没被真正
     合成过，Chrome 把隐藏页的 `setTimeout` 与 `requestAnimationFrame` 一起节流，
     等到脚本读到卡片时列表早回来了。 ⇒ 读"某一帧"的内容要用闸门，不要用延迟。 */
  await s9b.page.waitForFunction(
    () => Boolean(document.querySelector('.kb-overview-error .error-state')),
    null,
    { timeout: 8000, polling: 100 },
  );
  const g9b = await readKb(s9b.page);
  check('Z 只有概览失败那一帧：整页不算降级（落点分得开），附言不许替还没回话的表担保',
    g9b.概览错误卡 === true && g9b.整页错误态 === false && g9b.rows.length === 0
      && !/它没坏/.test(g9b.概览附言) && /还没回话/.test(g9b.概览附言),
    { 概览卡: g9b.概览错误卡, 整页: g9b.整页错误态, 行数: g9b.rows.length, 附言: g9b.概览附言 });
  s9b.releaseGate(); // 放行那一发列表：从"还没回话"切到"这一趟回来了"
  await s9b.page.waitForFunction(
    () => document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length === 3,
    null,
    { timeout: 8000, polling: 100 },
  );
  const g9b2 = await readKb(s9b.page);
  check('Z 概览坏了不牵连文档表：那一路回来照旧是三行三条分段条（读数缺失≠没有文档）',
    g9b2.rows.length === 3 && g9b2.分段条数 === 3 && g9b2.概览错误卡 === true,
    { 行数: g9b2.rows.length, 分段条: g9b2.分段条数 });
  /* 同一句话的**第二半**：表回来之后附言必须跟着换口径。
     只钉第一帧的话，把 note 写死成"还没回话"也能全绿 —— 那同样是在替未知担保，只是方向相反。 */
  check('Z 表回来之后附言跟着改口（同一块位置不许终身说一句"安全的话"）',
    /回来了/.test(g9b2.概览附言) && !/还没回话/.test(g9b2.概览附言), { 附言: g9b2.概览附言 });
  await s9b.ctx.close();

  /* ---------- 场景 9c：后端进程没重启 ⇒ overview 里根本没有 max_file_mb ----------
     这一档不是假想的：本机那个 :8001 就是旧形状，直到重启为止。缺字段的正确做法是
     "不显示上限、也不自己拦"，而不是印一句"单文件 ≤ — MB"（那是 NaN 换算留下的半截话）。 */
  const s9c = await openKnowledge(browser, 'legacyOverview');
  const g9c = await readKb(s9c.page);
  check('Z 概览两个新字段都不给：合成一句"都没读到"，不出现"≤ —"这种半截话、也不重复"交给后端判"',
    /格式与大小上限这一趟都没读到/.test(g9c.上传副说明) && !/≤/.test(g9c.上传副说明)
      && (g9c.上传副说明.match(/交给后端判/g) || []).length <= 1, { 副说明: g9c.上传副说明 });
  await s9c.page.setInputFiles('input[type=file]', filePayload('三份大.md', 3000));
  await s9c.page.waitForTimeout(700);
  const g9c2 = await readKb(s9c.page);
  check('Z 上限未知时**不做本地预拦**：那份 3 MB 照样出网，让后端说 422（拿猜来的数拦人更糟）',
    s9c.count('POST') === 1 && g9c2.队列[0]?.阶段 !== 'rejected',
    { POST: s9c.count('POST'), 行: g9c2.队列[0] });
  await s9c.ctx.close();

  /* ---------- 场景 9d：只缺 R-03 那个字段（= 后端重启到 HEAD 会落在的那一档） ----------
     9c 缺的是"那一版之前的所有新字段"，这一档只缺白名单。两条分开钉才证明页面
     不是拿"overview 有没有回话"一刀切：上限照旧要显示，格式那半必须改口。 */
  const s9d = await openKnowledge(browser, 'noFormats');
  const g9d = await readKb(s9d.page);
  /* 属性**干脆不出现**（读回来是空串）。写成 `accept=""` 是另一个意思 ——
     空串等于"不收任何类型"，那才是真把用户锁在门外。 */
  check('Z 缺 supported_formats：input 上不给 accept（不是给一个空串锁死选择器）',
    g9d.accept === '' || g9d.accept === null, { accept: g9d.accept });
  check('Z 缺 supported_formats：文案说"白名单没读到"，而上限那半句照旧显示 33（两处降级各自独立）',
    /格式白名单这一趟没读到/.test(g9d.上传副说明) && !/支持 /.test(g9d.上传副说明)
      && /单文件 ≤ 33 MB/.test(g9d.上传副说明), { 副说明: g9d.上传副说明 });
  await s9d.page.setInputFiles('input[type=file]', filePayload('现场照片.png', 0));
  await s9d.page.waitForTimeout(700);
  const g9d2 = await readKb(s9d.page);
  check('Z 缺白名单时**一个格式都不本地拦**：.png 照样出网，拒人的是后端那份三种清单',
    s9d.count('POST') === 1 && g9d2.队列[0]?.阶段 === 'rejected'
      // 界面贴的是**后端**的措辞与清单（三种），不是页面自己那份本地拦的说法（四种）：
      // 两头一起看才分得开"谁在拒"——只断言"出网了"挡不住"出网后页面又自己判了一遍"。
      && /不支持的文档格式：\.png（白名单：md\/pdf\/txt）/.test(g9d2.队列[0]?.文本 || '')
      && !/后端这一趟给的白名单是/.test(g9d2.队列[0]?.文本 || ''),
    { POST: s9d.count('POST'), 行: g9d2.队列[0] });
  await s9d.ctx.close();

  /* ---------- 场景 10：窄屏 390 ---------- */
  const s10 = await openKnowledge(browser, 'allTerminal', { viewport: { width: 390, height: 844 } });
  const g10 = await readKb(s10.page);
  check('Z 390：页面不横向溢出（scrollWidth 不超 clientWidth）', g10.横溢出 <= 0, { 溢出: g10.横溢出 });
  check('Z 390：底部标签栏四个入口都在', g10.tabbar项数 === 4, { 项数: g10.tabbar项数 });
  check('Z 390：文档表仍可横滚（ScrollXFrame 的 data-scrollable 为 1）+ 文件名一列钉在左边',
    g10.可横滚 === '1' && g10.粘性左列 === true, { 可横滚: g10.可横滚, 粘性左列: g10.粘性左列 });
  await s10.ctx.close();

  /* 十三个 context 的未捕获异常一起算。故意收全部而不是只看最后一个：
     503 与"未知状态"那两案正是最容易在渲染里炸出 undefined 的地方。 */
  const allErrors = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s9b, s9c, s9d, s10].flatMap((s) => s.errors);
  check('Z 全程无 pageerror（十三个 context 一起算）', allErrors.length === 0, allErrors);
}

/* ============================ AC 趟：右上角换模型 ============================ *
 *
 * 方案里这一趟原本叫「L 趟」，**L 这个趟号已经被 passListSelectFinish 占了**
 * （A–Z 里 L 早在第一批就用掉），所以实际落成 AC —— 名字改了，判据没改。
 *
 * 这趟要证的是"界面说的就是服务端生效的"，共四组：
 *  ① 候选只来自响应（含"少一家 ⇒ 界面少一项"的证伪，见 AC-1/AC-2）；
 *  ② 应用之后**胶囊跟着变**（前端不许自己改完自己显示，AC-4）；
 *  ③ 缺 Key 被 422 拒时，界面说的是哪家缺，而且胶囊**没变**（AC-6/AC-7）；
 *  ④ 老后端没有 catalog ⇒ 面板改口、不假装能换（AC-9），以及对比度与窄屏抽屉。
 *
 * 桩是**有状态**的（createModelOverrideMock）：POST 真的改内部状态、之后的 GET
 * 返回改过的样子 —— 静态桩验不出"应用后界面读的是响应还是自己的记忆"。
 */
async function passModelSwitch(browser, scheme, label) {
  console.log(`\n== AC 换模型面板 · ${label} ==`);
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);

  /* ---------- 主路径：候选来自响应 → 应用 → 胶囊跟着变 → 拒绝 → 回落 ---------- */
  const state = createModelOverrideMock(modelsBodyWithCatalog);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const posts = [];
  await installMocks(page);
  await page.route('**/api/models/override', async (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      const payload = route.request().postDataJSON();
      posts.push(payload);
      return route.fulfill(state.post(payload));
    }
    return route.fulfill(state.del());
  });
  await page.route('**/api/models', (route) => route.fulfill(state.get()));
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);

  const chipText = async () =>
    page.evaluate(() => document.querySelector('.cp-model-ro')?.textContent?.trim() ?? '');
  /* 弹层的开合不靠"猜 Escape 有没有被 AntD 接住"：先按，再量真实可见性，
     还开着就补一次外部点击。探针里凡是要靠控件开合往下走的判据都这样写 —— 
     否则一次 AntD 行为变化会把后面十几条一起带倒，而报出来的还是"面板没渲染"。 */
  const isOpen = async () => Boolean(await page.locator('.model-settings').isVisible().catch(() => false));
  const closePanel = async () => {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    if (await isOpen()) {
      await page.mouse.click(700, 890);
      await page.waitForTimeout(250);
    }
  };
  const openPanel = async () => {
    if (await isOpen()) return;
    await page.locator('button[aria-label="模型设置"]').click();
    await page.waitForTimeout(500);
  };

  const gear = page.locator('button[aria-label="模型设置"]');
  check(`${label} AC-0 齿轮在顶栏右上角（topbar-actions 里、刷新按钮之前）`,
    (await gear.count()) === 1 &&
      (await page.evaluate(() => {
        const actions = document.querySelector('.topbar-actions');
        const button = document.querySelector('button[aria-label="模型设置"]');
        return Boolean(actions && button && actions.contains(button));
      })),
    await gear.count());
  check(`${label} AC-0b 齿轮带 aria-haspopup/expanded（展开态对读屏可见）`,
    await page.evaluate(() => {
      const button = document.querySelector('button[aria-label="模型设置"]');
      return button?.getAttribute('aria-haspopup') === 'dialog' && button?.getAttribute('aria-expanded') === 'false';
    }));

  await gear.click();
  await page.waitForSelector('.model-settings', { timeout: 5000 });
  /* 2026-09-29：原来这条判的是"面板顶上那句生效范围长话在不在"
     （``之后新建的任务`` + ``回落到 .env``）。那整段删了 ——
     它讲的三件事在这一屏没有对应控件，第三件在 Key 输入框的 placeholder 里另有读点。
     现在判两件事：① 那句长话**确实不在了**（删了又长回来是最容易混进来的形状）；
     ② 出口（「回落到 .env」那颗按钮）与新的档位名**在**。 */
  check(`${label} AC-0c 展开后 aria-expanded=true，那句生效范围长话已删，档位改叫「决策模式 / 执行模式」`,
    await page.evaluate(() => {
      const button = document.querySelector('button[aria-label="模型设置"]');
      const text = document.querySelector('.model-settings')?.textContent ?? '';
      return (
        button?.getAttribute('aria-expanded') === 'true' &&
        !text.includes('之后新建的任务') &&
        text.includes('决策模式') &&
        text.includes('执行模式')
      );
    }),
    await page.evaluate(() => document.querySelector('.model-settings')?.textContent?.slice(0, 60) ?? ''));

  /* 候选清单：点开大档那个 AutoComplete，读真正落进 DOM 的叶子项。 */
  const openDropdown = async (index) => {
    await page.locator('.model-settings-input input').nth(index).click();
    await page.waitForTimeout(450);
    return page.evaluate(() =>
      [...document.querySelectorAll(
        '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content',
      )].map((el) => el.textContent ?? ''),
    );
  };
  const wantIds = modelsBodyWithCatalog.catalog.map((row) => row.id);
  const options = await openDropdown(0);
  check(`${label} AC-1 候选条数与顺序都来自响应（${wantIds.length} 条，一个都不在前端写）`,
    options.length === wantIds.length && wantIds.every((id, i) => (options[i] ?? '').includes(id)),
    options);
  check(`${label} AC-1b 阶梯候选把整档表摊开（不是只报最低档）`,
    (options.find((t) => t.includes('glm-4.6')) ?? '').includes('≤32,000') &&
      (options.find((t) => t.includes('glm-4.6')) ?? '').includes('≤128,000'),
    options.find((t) => t.includes('glm-4.6')));
  check(`${label} AC-1c 没配 Key 的那家直接标在候选上，并给出该配哪个环境变量`,
    (options.find((t) => t.includes('qwen-plus')) ?? '').includes('未配 Key') &&
      (options.find((t) => t.includes('qwen-plus')) ?? '').includes('LLM_API_KEY_QWEN'),
    options.find((t) => t.includes('qwen-plus')));
  check(`${label} AC-1d 下拉的分组标题用的是响应的 provider_display（前端不另起一份英文名）`,
    await page.evaluate(() => {
      const groups = [...document.querySelectorAll(
        '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-group',
      )].map((el) => el.textContent ?? '');
      return groups.includes('智谱 GLM') && groups.includes('阿里云千问') && !groups.includes('Zhipu');
    }));
  /* 这里只收**下拉**（焦点还在 select 里，Escape 关的是那一层），弹层保持打开 ——
     下一步还要点同一个面板里的第二个输入框。 */
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);

  /* 选 glm-4.6 / glm-4-air ⇒ 应用。 */
  await page.locator('.model-settings-input input').nth(0).click();
  await page.waitForTimeout(350);
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option', { hasText: 'glm-4.6' }).first().click();
  await page.waitForTimeout(250);
  await page.locator('.model-settings-input input').nth(1).click();
  await page.waitForTimeout(350);
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option', { hasText: 'glm-4-air' }).first().click();
  await page.waitForTimeout(250);
  /* 2026-09-29：单价说明整段（口径 / 汇率 / 官网核对日期 / 来源链接）删掉了。
     原来 AC-2 判的是"价格行换成所选那一行的口径与核对日期" —— 那个读点没了，
     判据跟着改成**它该判的那件事**：选完之后控件里的值就是所选那一行的 id
     （不沿用旧模型），并且那整段单价说明**不在场**（删了又长回来没人会发现）。 */
  check(`${label} AC-2 选完之后两行的值就是所选那两个 id，且单价说明整段已删（不是换了一行还在）`,
    await page.evaluate(() => {
      const vals = [...document.querySelectorAll('.model-settings-input input')].map((i) => i.value);
      return (
        vals[0] === 'glm-4.6' &&
        vals[1] === 'glm-4-air' &&
        document.querySelectorAll('.model-settings-price').length === 0 &&
        !(document.querySelector('.model-settings')?.textContent ?? '').includes('元 / 100 万 token')
      );
    }),
    await page.evaluate(() => ({
      vals: [...document.querySelectorAll('.model-settings-input input')].map((i) => i.value),
      priceRows: document.querySelectorAll('.model-settings-price').length,
    })));
  check(`${label} AC-3 应用按钮此刻可点（两档都有值且与当前不同）`,
    await page.locator('.model-settings-actions button').first().isEnabled());

  const chipBefore = await chipText();
  await page.locator('.model-settings-actions button').first().click();
  await page.waitForTimeout(1200);
  check(`${label} AC-4a 发出去的请求体就是那两个模型 id（不是控件的显示文案）`,
    posts.length === 1 && posts[0].model_large === 'glm-4.6' && posts[0].model_small === 'glm-4-air',
    posts);
  check(`${label} AC-4b 应用后 composer 的胶囊跟着变（读数来自响应，不是前端自改自显示）`,
    (await chipText()) === '模型 glm-4.6 +glm-4-air', { before: chipBefore, after: await chipText() });
  check(`${label} AC-4c 面板显示"本进程已覆盖"，并回报覆盖前是哪一档`,
    await page.evaluate(() => {
      const badge = document.querySelector('.model-settings-badge')?.textContent ?? '';
      return badge.includes('本进程已覆盖') && badge.includes('deepseek-flash');
    }));
  /* 胶囊的明细是**另一条链**（modelLabel 那份措辞）：换完之后它必须跟着换口径，
     否则"面板说智谱、读数说 DeepSeek 的峰谷"就是同一屏两份真源。 */
  await closePanel();
  await page.locator('.cp-model-ro').hover();
  await page.waitForTimeout(600);
  const tipAfter = await page.evaluate(() => {
    const box = document.querySelector('.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner');
    return box ? box.textContent ?? '' : '';
  });
  check(`${label} AC-4d 换完之后读数跟着改口径：最低档标注 + 不再提低谷系数`,
    tipAfter.includes('最低档') &&
      tipAfter.includes('这家不分高峰 / 低谷') &&
      !tipAfter.includes('低谷时段系数'),
    tipAfter.slice(0, 220));
  check(`${label} AC-4e 读数里的单价是 glm-4.6 那一行（¥1.00 进），不是切换前那句 ¥2.13`,
    tipAfter.includes('¥1.00 进 / ¥3.00 出') && !tipAfter.includes('¥2.13 进'),
    tipAfter.slice(0, 220));

  /* 缺 Key ⇒ 422：界面说哪家缺，胶囊**不许**变。 */
  await openPanel();
  await page.locator('.model-settings-input input').nth(0).click();
  await page.waitForTimeout(350);
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option', { hasText: 'qwen-plus' }).first().click();
  await page.waitForTimeout(250);
  const chipBeforeReject = await chipText();
  await page.locator('.model-settings-actions button').first().click();
  await page.waitForTimeout(900);
  check(`${label} AC-5 被拒时界面给的是服务端原话（含环境变量名），不是"任务失败"那种挪位置`,
    await page.evaluate(() => {
      const text = [...document.querySelectorAll('.model-settings-error, .ant-message-notice-content')]
        .map((n) => n.textContent ?? '').join(' ');
      return text.includes('LLM_API_KEY_QWEN') && text.includes('阿里云千问');
    }));
  check(`${label} AC-6 被拒之后胶囊没变（拒绝不能留下半个生效的样子）`,
    (await chipText()) === chipBeforeReject, { want: chipBeforeReject, got: await chipText() });

  /* 回落 .env */
  check(`${label} AC-7 「回落到 .env」此刻可用（有覆盖在生效）`,
    await page.locator('.model-settings-actions button').nth(1).isEnabled());
  await page.locator('.model-settings-actions button').nth(1).click();
  await page.waitForTimeout(1200);
  check(`${label} AC-8 回落之后胶囊回到 .env 那一档，且按钮重新禁用（幂等，不骗第二次）`,
    (await chipText()) === '模型 deepseek-flash' &&
      (await page.locator('.model-settings-actions button').nth(1).isDisabled().catch(() => false)),
    await chipText());
  check(`${label} AC-8b 全程没有 pageerror`, errors.length === 0, errors.slice(0, 2));

  /* 对比度：面板里四类文字都要量在**真正托着它的那块底**上（弹层底色由 AntD 决定，
     拿 --bg-surface 当分母等于没测 —— 这是 R-03 那轮同一课）。 */
  await openPanel();
  const contrast = await page.evaluate(() => {
    const nums = (s) => (String(s).match(/[\d.]+/g) || []).map(Number);
    const opaqueBg = (node) => {
      let n = node;
      while (n) {
        const v = nums(getComputedStyle(n).backgroundColor);
        if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) return v.slice(0, 3);
        n = n.parentElement;
      }
      return null;
    };
    const cr = (fgStr, bg) => {
      const lin = (x) => { const c = x / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
      const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
      const f = nums(fgStr);
      const A = f.length > 3 ? f[3] : 1;
      const fg = f.slice(0, 3).map((c, i) => c * A + bg[i] * (1 - A));
      const a = lum(fg); const b = lum(bg);
      return Number(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2));
    };
    const out = {};
    /* 选择器跟着改名：Key 那一栏 2026-09-27 从 ``.model-settings-keys``（一枚 <ul>）
       长成 ``.ms-keybox`` + ``.ms-key-list`` —— 旧串留在数组里 = 那一类永远量不到东西，
       而"量不到"会被读成"没红"。前件那半（AC-9 里 ``size`` 一定要拿到）拦的就是这个。
       ⚠️ 只往这里加**恒在**的类：那三行结果话术（hold / result--ok / --bad）与网关块
       都是"做过某一步才进 DOM"的，量它们归 AE-dark 那一趟（那里能创造条件）。 */
    for (const sel of [
      /* 2026-09-29：``.model-settings-scope``（生效范围长话）、``.model-settings-price``
         （单价说明）、``.ms-key-list li``（三行供应商状态清单）三块都删了 ——
         旧串留在数组里 = 那一类永远量不到东西，而"量不到"会被读成"没红"。
         换成这一屏现在**恒在**的三类：段标题、角色绑定那行小字、向量模型读数。 */
      '.ms-section-title',
      '.ms-rolebind',
      '.model-settings-note',
      '.model-settings-label',
      '.ms-key-label',
    ]) {
      const el = document.querySelector(sel);
      if (!el) { out[sel] = null; continue; }
      const bg = opaqueBg(el);
      out[sel] = bg ? { cr: cr(getComputedStyle(el).color, bg), size: getComputedStyle(el).fontSize } : null;
    }
    return out;
  });
  const smallText = Object.entries(contrast).filter(([, v]) => v && parseFloat(v.size) <= 13);
  check(`${label} AC-9 面板小字（≤13px）在真正底色上 ≥4.5:1`, smallText.length > 0 && smallText.every(([, v]) => v.cr >= 4.5), contrast);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  /* ---------- 主题切换（2026-09-26 从图标栏挪到右上角）----------
     这一段刻意放在对比度**之后**：换主题会把整页 token 换一遍，
     量完再动，免得"我把面板量成了另一档底"这种错混进来。 */
  const other = scheme === 'dark' ? 'light' : 'dark';
  const wantLabelHere = scheme === 'dark' ? '切换到浅色主题' : '切换到深色主题';
  const wantLabelOther = other === 'dark' ? '切换到浅色主题' : '切换到深色主题';
  const themeState = () => page.evaluate(() => {
    const svg = document.querySelector('.topbar-theme-toggle svg') ?? null;
    return {
      attr: document.documentElement.dataset.theme ?? null,
      stored: localStorage.getItem('trinity-console.theme'),
      label: document.querySelector('.topbar-theme-toggle')?.getAttribute('aria-label') ?? null,
      /* 自绘图标没有 data-icon，读 DOM 事实：太阳有那个圆心、月亮没有。 */
      icon: svg ? (svg.querySelector('circle') ? 'sun' : 'moon') : null,
    };
  });
  const t0 = await themeState();
  /* 前件：这一趟真的开在 scheme 那一档。不钉这条，"点一下换了"可能被
     "本来就不对"蒙过去（探针自己写错 localStorage 键名就是这么个错法）。 */
  check(`${label} AC-17 前件：初始主题就是这一趟要的那一档（data-theme 与 localStorage 都在）`,
    t0.attr === scheme && t0.stored === scheme, t0);
  check(`${label} AC-18 右上角的次序：体检胶囊 → 主题 → 模型设置 → 刷新（且 aria-label 说的是另一档）`,
    await page.evaluate((want) => {
      const labels = [...document.querySelectorAll('.topbar-actions > *')]
        .map((n) => n.getAttribute('aria-label') ?? n.className);
      return labels.join('|') === `数据源体检详情|${want}|模型设置|刷新当前页数据`;
    }, wantLabelHere), t0.label);
  await page.locator('.topbar-theme-toggle').click();
  await page.waitForTimeout(500);
  const t1 = await themeState();
  check(`${label} AC-19 点它真的换主题（data-theme + localStorage 一起跟，不是只换个图标）`,
    t1.attr === other && t1.stored === other && t1.icon !== null, { t0, t1 });
  check(`${label} AC-20 换过之后按钮自己改口（说的仍是"切到对面那档"，不是"切回深色"）`,
    t1.label === wantLabelOther && t1.icon !== t0.icon, { before: t0.icon, after: t1.icon, label: t1.label });
  await page.locator('.topbar-theme-toggle').click();
  await page.waitForTimeout(500);
  const t2 = await themeState();
  check(`${label} AC-21 再点回得去（回到这一趟起始那一档，不留半个换到一半的状态）`,
    t2.attr === scheme && t2.stored === scheme && t2.label === wantLabelHere, t2);
  const dup = await page.evaluate(() => ({
    railButtons: document.querySelectorAll('.rail-foot button').length,
    themeButtons: document.querySelectorAll('button[aria-label*="主题"]').length,
  }));
  check(`${label} AC-22 全页只有一枚主题切换（图标栏那枚已挪走：一语义一个入口）`,
    dup.railButtons === 0 && dup.themeButtons === 1, dup);
  check(`${label} AC-22b 图标与当前主题相配（深色给太阳、浅色给月亮，不是反的）`,
    t0.icon === (scheme === 'dark' ? 'sun' : 'moon') && t1.icon === (other === 'dark' ? 'sun' : 'moon'),
    { start: t0.icon, after: t1.icon, scheme });

  /* ---------- 老后端：没有 catalog ⇒ 改口，不假装能换 ---------- */
  const legacy = await ctx.newPage();
  const legacyErrors = [];
  legacy.on('pageerror', (e) => legacyErrors.push(e.message));
  await installMocks(legacy);
  await legacy.route('**/api/models', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modelsBody) }),
  );
  await legacy.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await legacy.waitForTimeout(600);
  await legacy.locator('button[aria-label="模型设置"]').click();
  await legacy.waitForTimeout(600);
  check(`${label} AC-10 老后端（无 catalog）⇒ 面板明说"这一趟没读到候选清单"，并提示要重启后端`,
    await legacy.evaluate(() => {
      const text = document.querySelector('.model-settings')?.textContent ?? '';
      return text.includes('没读到候选清单') && text.includes('重启');
    }));
  check(`${label} AC-11 这一趟不渲染任何下拉候选（不拿一份前端自带的清单顶上）`,
    (await legacy.locator('.model-settings .ant-select-item-option').count()) === 0);
  check(`${label} AC-12 降级那一屏仍然报得出"现在实际在用哪两个档"（读的是 items）`,
    await legacy.evaluate(() => (document.querySelector('.model-settings')?.textContent ?? '').includes('deepseek-flash')));
  check(`${label} AC-12b 降级路径没有 pageerror`, legacyErrors.length === 0, legacyErrors.slice(0, 2));
  await legacy.close();

  /* ---------- 少一家 ⇒ 候选少一项（证伪"前端抄了一份"） ---------- */
  const trimmed = JSON.parse(JSON.stringify(modelsBodyWithCatalog));
  trimmed.catalog = trimmed.catalog.filter((row) => row.provider !== 'zhipu');
  const cut = await ctx.newPage();
  const cutErrors = [];
  cut.on('pageerror', (e) => cutErrors.push(e.message));
  await installMocks(cut);
  await cut.route('**/api/models', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(trimmed) }),
  );
  await cut.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await cut.waitForTimeout(600);
  await cut.locator('button[aria-label="模型设置"]').click();
  await cut.waitForTimeout(500);
  await cut.locator('.model-settings-input input').nth(0).click();
  await cut.waitForTimeout(450);
  const cutOptions = await cut.evaluate(() =>
    [...document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content',
    )].map((el) => el.textContent ?? ''),
  );
  check(`${label} AC-13 桩里删掉一家 ⇒ 候选跟着少（界面没有第二份清单，判据可证伪）`,
    cutOptions.length === trimmed.catalog.length && !cutOptions.some((t) => t.includes('glm-')),
    cutOptions);
  check(`${label} AC-13b 这一趟没有 pageerror`, cutErrors.length === 0, cutErrors.slice(0, 2));
  await cut.close();
  await ctx.close();

  /* ---------- 390 窄屏：走抽屉，不横向溢出 ---------- */
  const narrowCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    colorScheme: scheme,
    locale: 'zh-CN',
    isMobile: true,
    hasTouch: true,
  });
  await narrowCtx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), scheme);
  const npage = await narrowCtx.newPage();
  const nErrors = [];
  npage.on('pageerror', (e) => nErrors.push(e.message));
  const nstate = createModelOverrideMock(modelsBodyWithCatalog);
  await installMocks(npage);
  await npage.route('**/api/models/override', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill(nstate.post(route.request().postDataJSON()))
      : route.fulfill(nstate.del()),
  );
  await npage.route('**/api/models', (route) => route.fulfill(nstate.get()));
  await npage.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await npage.waitForTimeout(700);
  /* 窄屏顶栏图标可能是隐藏/收进抽屉的：先确认齿轮可达，再点开抽屉 */
  const gearVisible = await npage.locator('button[aria-label="模型设置"]').isVisible().catch(() => false);
  check(`${label} AC-14 390 窄屏齿轮仍在顶栏且可达（不靠 hover 才能点到）`, gearVisible);
  /* 右上角多了主题切换这一枚 ⇒ 顶栏宽度要**重新量**：多一枚 34px 的按钮把顶栏撑出去，
     面板那一屏（AC-16）是量不出来的 —— 它只量抽屉里的内容。 */
  const bar = await npage.evaluate(() => {
    const kids = [...document.querySelectorAll('.topbar-actions > *')];
    return {
      count: kids.length,
      worstRight: Math.round(Math.max(...kids.map((n) => n.getBoundingClientRect().right))),
      vw: window.innerWidth,
      docScroll: document.documentElement.scrollWidth,
      labels: kids.map((n) => n.getAttribute('aria-label') ?? n.className),
    };
  });
  check(`${label} AC-23 390 右上角四件事都在屏内（多一枚不许把顶栏撑出去，且文档不横向滚）`,
    bar.count === 4 && bar.worstRight <= bar.vw && bar.docScroll <= bar.vw, bar);
  await npage.locator('button[aria-label="模型设置"]').click();
  await npage.waitForTimeout(700);
  check(`${label} AC-15 390 走 Drawer 而不是 Popover（弹层在这个宽度会被截掉半屏）`,
    (await npage.locator('.model-settings-drawer').count()) === 1 &&
      (await npage.locator('.model-settings-popover').count()) === 0);
  check(`${label} AC-16 390 面板不横向溢出（内容宽度不超屏幕）`,
    await npage.evaluate(() => {
      const box = document.querySelector('.model-settings')?.getBoundingClientRect();
      return Boolean(box) && box.right <= window.innerWidth + 1 && box.left >= -1;
    }));
  check(`${label} AC-16b 390 没有 pageerror`, nErrors.length === 0, nErrors.slice(0, 2));
  await narrowCtx.close();
}

/* ---------------------- AD 设置中心（原「运行配置」弹层）：一屏五个口径 ---------------------- //
   这一趟管五件事，每一件都对应一条"界面在说谎"的具体形状：
   ① **只有一份状态**：面板、composer 那两颗开关、右下角那行读数读写的是同一个 Context。
      判据是**双向**的（面板改→开关跟着变、开关改→面板跟着变），单向断言挡不住"两份 state 各写各的"。
   ② **只有一份清单**：工具勾选清单来自桩里的 ``/tools``（六条，含 extract/file_io/web_search），
      而不是 ``client.ts`` 里那份退役的两条名单 —— 关掉 RAG 后发出去的白名单必须**跟着桩变**。
   ③ **没碰过的键不发**：默认提交体只有 ``task``。旧版在这里发前端编的 ``max_iterations:3``，
      而后端默认是 5 —— 那不是"用户没意见"，那是替用户下了一道后端从没收到过的令。
   ④ **后端说的原样落屏**：``accepted=false`` 不给控件，只在「后端暂不支持」里列
      **key + label + help**（AD-39）；``accepted=true`` 而 ``enforced=false`` 那一档由
      AD-45…49b 钉 —— 控件照旧在场、后端 help 以正文在场、行内一句"没有执行机制"、
      底部单独一栏点名 key + label（**不与「暂不支持」混一栏**）、填了**真的进请求体**；
      AD-50 钉那句 help 在这一屏只出现一次（底部再抄一遍 ⇒ 读数 2 红；行整个没了 ⇒ 读数 0 红）。
      未知顶层键 / 未知 ``kind`` /
      "有界没声明" / "声明能配但界面没有行"四类原样透出（AD-23/24/20/41）；422 的原文 + HTTP 码 +
      request_id 进实时日志（U-8）；回执与发出的一致才不吭声，不一致或没收下就说出来（P-1）。
   ⑤ **字段名与单位也归响应**（本轮 §2.1 对账补的）：``fields[].label`` / ``unit`` 决定
      面板上那一行叫什么、后缀是什么、回执对账那行怎么落笔。界面原来自带一张
      ``CONFIG_LABELS``，本轮删了。
   ⚠️ 桩里的数值与措辞**一律不等于后端真值**（默认 6 轮 / 8 分 / 7 篇，limits 1..12、0..12、
      1..24、0.01..1000 与 15..1800 步长 15，预设 1·4·9 轮、¥0.13·0.66·6.66，label 带"（桩词）"，
      unit 写成"次 / 档 / 块钱 / 秒钟 / 篇"）：桩值若等于真值，"界面读的是响应"这类判据
      就恒真（与 Z 趟白名单同一口径）。本轮对账逐键比出**三处撞车** —— ``defaults`` 那个 7、
      桩的 ``timeout_s.max`` 曾是 3600（**撞上**新改的后端上界）、``review_threshold`` 的整条
      0..10。另有**一处故意留着的**巧合：``max_cost_cny.step`` 两边都是 0.01 ⇒ "小数位取自 step"
      今天不可证伪，改它会连带牵动 AD-03；口径与理由都写在 ``mocks.cjs`` 那张表的注释里。
   六组负面对照（改源码跑一次再撤，步骤见 README 的 AD 节；编号与那里的表一致，
   数字是**各当次实测**，趟涨了要重跑，别抄旧数）：
   · AD-neg1 把面板的工具勾选改成本地 useState ⇒ 60 通过 / 63，红的是 AD-09/10/16。
     ⚠️ 第一版**没咬住**（全绿）：那次只把读数换成局部 state，onChange 还在写 Context
     —— 负面对照自己是假的时也会全绿，所以每条都要核"红的是不是该红的那几条"。
   · AD-neg2 ``NumericRow`` 的闸门只看"有没有界"、不认 ``accepted`` ⇒ 62 / 63，**只红 AD-36**。
     README 里旧记的"红 AD-20 / 40 通过"已经**不成立**了：那半个闸门同时是"键不在 ``fields[]``
     里"时的兜底，摘掉它 ``field`` 直接是 ``null``，读 ``field.help`` 就抛 —— 所以它既是能力判断
     也是空值判断。⚠️ 这一组**咬不到 AD-11**：``reviewer_enabled`` 不在行表里，
     闸门再宽也不会给它画控件 —— 那条要靠行表本身，别以为它被覆盖了。
   · AD-neg3 让 ``buildRunConfigBody`` 回落到 ``max_iterations: 3`` ⇒ 61 / 63，红 AD-22/28
     （那两档钉的就是"只发 task"）；
   · AD-neg4 把 ``NumericRow`` 的名字/后缀与 composer 那行读数改回写死那张表 ⇒ 57 / 63，
     红**六条**：AD-04/05/25/41b（页脚读数变成"8 轮"）+ AD-37b/37c（逐行比对失败），
     并且同时让后端那两个静态审计用例翻红（"前端代码里不许出现后端的措辞与单位"）。
     这条盯的就是本轮刚拆掉的那张前端字段表会不会自己长回来。
   · AD-neg5 摘掉「后端会收下，但当前没有执行机制」那一栏 ⇒ 62 / 63，**只红 AD-48**；
   · AD-neg6 把 ``enforced=false`` 当成"不支持"（连控件都不画）⇒ 57 / 63，
     红 AD-46/47/49 前件/49b/35b/50 —— 其中 AD-50 的读数是 **0**：行整个没了，那句 help
     一次都没出现。前件型判据把"量不到"当成不通过，这正是要它做的样子。 */
async function passRunConfigPanel(browser) {
  console.log('\n== AD 设置中心：一份状态 / 一份清单 / 不发没碰过的键 / 后端原话落屏 / 名字与单位也归响应 / 这一屏的形状 ==');
  const variants = agentOptionsVariants();
  const errors = [];

  const newPage = async (opts = {}) => {
    const ctx = await browser.newContext({
      viewport: opts.viewport || { width: 1440, height: 900 },
      colorScheme: opts.scheme || 'light',
      locale: 'zh-CN',
      isMobile: Boolean(opts.viewport),
      hasTouch: Boolean(opts.viewport),
    });
    await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), opts.scheme || 'light');
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await installMocks(page);
    /* 2026-09-27：设置中心的「模型」格里**内嵌**了模型设置那份 ⇒ AD 这一趟也要给一份
       带 catalog / providers 的 ``GET /models``。默认那份 modelsBody 没有这两个字段，
       组件会走"这一趟没读到候选清单"那一支、KeySection 整块不挂载 ⇒ AD-55b 想量的
       那批带前缀 id 根本不进 DOM，读回空数组看着像"没挂载"而不是"实现少了前缀"。
       （G / AC 趟各自再注册一次同名路由换形态，后注册的先匹配，互不影响。） */
    await page.route('**/api/models', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modelsBodyWithCatalog) }));
    /* ``options: null`` = 这一档模拟"后端进程比界面旧"：端点**404**，而不是回一份空 JSON。
       回 null 会让"拉不到"与"拉到了但没数据"两档混成一档，而界面要防的正是前者。 */
    if (opts.options === null) await installAgentOptions(page, null);
    else if (opts.options !== undefined) await installAgentOptions(page, opts.options);
    const submit = createSubmitMock(opts.submit || {});
    await page.route('**/api/tasks', submit.handler);
    await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(700);
    return { ctx, page, submit };
  };

  /* ⚠️ 幂等：这一层现在是 Modal，**开着的时候去点触发器会被遮罩挡下**（Popover 那版不会，
     所以旧代码里"再点一次"是安全的）。已经开着就直接返回，别去戳那颗按钮。 */
  const openPanel = async (page) => {
    if (await page.locator('.rcp').isVisible().catch(() => false)) {
      await page.waitForTimeout(200);
      return;
    }
    await page.locator('button.cp-icon').click();
    await page.waitForSelector('.rcp', { state: 'visible' });
    await page.waitForTimeout(400);
  };
  /** 点开「高级」那一格。三栏降级信息（会收下没执行机制 / 暂不支持 / 后端还给了这些）
   *  在页签时代住在外层容器、永远在场；换布局之后它们跟着这一格挂载 ⇒
   *  "读回空字符串"与"界面没说话"长得一模一样。凡是判 ``.rcp-unknown`` /
   *  ``.rcp-unsupported`` / ``.rcp-unenforced`` 的场景，都必须先显式点一次这一格
   *  （AD-20/23/24/41 第一版就是因为漏了这一步红的）。 */
  const openAdvanced = async (p) => {
    await p.locator('.sc-nav-item', { hasText: '高级' }).click();
    await p.waitForTimeout(350);
  };
  const fieldInput = (page, key) => page.locator(`.rcp [data-field="${key}"] input`);
  const num = (page, key) => fieldInput(page, key).inputValue().catch(() => null);
  const hint = (page) =>
    page.evaluate(() => document.querySelector('.cp-hint')?.textContent?.trim() ?? '');
  const switchStates = (page) =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll('.switch-row .ant-switch')).map((s) => s.getAttribute('aria-checked')),
    );
  const bodyKeys = (b) => Object.keys(b ?? {}).sort();
  /** 桩里 ``max_iterations`` 的单位后缀（"次"）。
   *  判据一律**从桩读**，不在探针里再写一遍"轮" —— 探针写死后端那份措辞，
   *  就等于探针自己变成第二个来源（与这一轮拆掉的前端字段表同病）。 */
  const stubUnit = (key) => variants.base.fields.find((f) => f.key === key)?.unit ?? '';
  /** 同理，回执对账那几行的**字段名**也判"是不是响应给的那份"：
   *  界面原来自带一张 ``CONFIG_LABELS``（写的是"最大成本预算"），本轮删掉了。
   *  桩里刻意叫「成本预算上限（桩词）」⇒ 提示行里出现这个串，就不可能是自带表。 */
  const stubLabel = (key) => variants.base.fields.find((f) => f.key === key)?.label ?? key;

  /* ---------- 回执提示那一栏的对比度：亮/暗各量一次（AD-43 / AD-42） ----------
     为什么单开：``.cfg-issue`` **只在"回执对不上"那一档进 DOM**，全站其它趟（含 AA 趟与
     场景 8 的深色面板）都看不到它 ⇒ 那三行小字从来没被在任何底色上量过。
     它的底是**带色调的半透明** ``--warning-soft``，前景还分两档
     （结论走 ``--warning-fg``、末尾说明走 ``--text-2``）：中性灰压在琥珀底上会掉对比度，
     这正是 AA 趟 R-15 翻过车的地方。
     ⚠️ 与 :7330 场景 8 那份 bgOf 的**一处**区别：这里把半透明层**合成**掉再算。
     旧那份"只认 alpha>0.99 的层"会跳过 ``rgba(251,191,36,.14)``、拿更外的页面底来算 ⇒
     暗色量到 8.84，而眼睛看到的底其实是合成后的 #2d2615（真值约 6.8）。
     "跳过一层"永远把对比度**算高**，所以那种写法只会漏报不会误报 —— 但漏报的是一条读不清的小字。
     场景 8 那批的底都是不透明的，未受影响，故不跟着改。 */
  const measureIssueContrast = (page) =>
    page.evaluate(() => {
      const lin = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
      const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
      const parse = (s) => (s || '').match(/[\d.]+/g)?.map(Number).slice(0, 4) ?? [255, 255, 255, 1];
      const bgEff = (el) => {
        const stack = [];
        let node = el;
        while (node) {
          const c = parse(getComputedStyle(node).backgroundColor);
          const a = c.length > 3 ? c[3] : 1;
          if (c.length >= 3 && a > 0) {
            stack.push({ rgb: c.slice(0, 3), a });
            if (a > 0.99) break;
          }
          node = node.parentElement;
        }
        if (!stack.length || stack[stack.length - 1].a < 0.99) stack.push({ rgb: [255, 255, 255], a: 1 });
        let out = stack[stack.length - 1].rgb;
        for (let i = stack.length - 2; i >= 0; i -= 1) {
          const layer = stack[i];
          out = layer.rgb.map((v, j) => Math.round(v * layer.a + out[j] * (1 - layer.a)));
        }
        return out;
      };
      const cr = (fg, bg) => {
        const l1 = lum(fg);
        const l2 = lum(bg);
        return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
      };
      const out = [];
      /* 三类：结论标题、结论逐条（``<li>`` 没有自己的 class，走列表那一层）、末尾那句说明。 */
      for (const sel of ['.cfg-issue-title', '.cfg-issue-list li', '.cfg-issue-note']) {
        for (const el of document.querySelectorAll(sel)) {
          out.push({
            sel,
            color: getComputedStyle(el).color,
            ratio: cr(parse(getComputedStyle(el).color).slice(0, 3), bgEff(el)),
            fs: getComputedStyle(el).fontSize,
          });
        }
      }
      return out;
    });
  const ISSUE_SELS = ['.cfg-issue-title', '.cfg-issue-list li', '.cfg-issue-note'];
  const assertIssueContrast = (tag, rows) => {
    check(`${tag} 三类文字在**合成后的真实底色**上 ≥4.5:1`,
      rows.length >= 3 && rows.every((m) => m.ratio >= 4.5), rows);
    check(`${tag} 前件：三类选择器都真量到了（某类为空 = 选择器写错或那一栏没进 DOM，不是通过）`,
      ISSUE_SELS.every((sel) => rows.some((m) => m.sel === sel)), [...new Set(rows.map((m) => m.sel))]);
  };

  /* ================= 场景 1：完整响应（交互与联动都在这里） ================= */
  const s1 = await newPage();
  let { page } = s1;
  await openPanel(page);
  check('AD-01 前件：面板打开了，预设行在场（.rcp + .rcp-preset-row）',
    (await page.locator('.rcp').count()) === 1 && (await page.locator('.rcp-preset-row').count()) === 1);

  /* ================= 这一屏的形状（水平页签 → 左侧导航 + 右侧内容） =================
     四条各钉一个"改坏了肉眼看不出来"的形状：
     ① 三项导航各切一次，**内容跟着换**（只换高亮不换内容是这一族最常见的假动作）；
        读点收窄到三个"只在自己那一格里出现"的容器，不读整页 innerText；
     ② 一行的三件（标签 / 描述 / 控件）都在，且控件在标签**右边**、描述在标签**下边** ——
        行式布局的判据是几何，不是类名。类名都写对了而 grid 忘了写，界面照样上下堆；
     ③ 「回落到 .env」这一屏只有一颗（内嵌那份模型面板里的同名按钮必须不画）——
        两颗做同一件事，迟早有一天只禁用其中一颗；
     ④ Modal 宽度落在 720 附近（±10 的容差是给 AntD 那 1px 边框与滚动条预留的）。 */
  const navLabels = await page.evaluate(() =>
    [...document.querySelectorAll('.sc-nav-item')].map((e) => e.textContent ?? ''),
  );
  check('AD-57 左侧导航恰好三项，名字与顺序是「基础 / 模型 / 高级」，且默认选中第一项',
    JSON.stringify(navLabels) === JSON.stringify(['基础', '模型', '高级']) &&
      (await page.evaluate(() => document.querySelector('.sc-nav-item')?.getAttribute('aria-selected'))) === 'true',
    navLabels);

  const paneShape = await page.evaluate(() => {
    const MARK = { basic: '.rcp-preset-row', model: '.rcp-models', advanced: '.rcp-tools' };
    const vis = {};
    for (const [k, sel] of Object.entries(MARK)) {
      const el = document.querySelector(sel);
      vis[k] = el ? !el.closest('.sc-pane[hidden]') : false;
    }
    const panes = [...document.querySelectorAll('.sc-pane')].map((p) => ({
      id: p.id,
      hidden: p.hasAttribute('hidden'),
      role: p.getAttribute('role'),
    }));
    const modal = document.querySelector('.ant-modal-content')?.getBoundingClientRect();
    return { vis, panes, modalW: modal ? Math.round(modal.width) : 0 };
  });
  check('AD-58 默认只有「基础」那一格可见（另两格还没挂载过 ⇒ 不在 DOM 里，不是藏着）',
    paneShape.vis.basic === true && paneShape.vis.model === false && paneShape.vis.advanced === false,
    paneShape);
  check('AD-59 承载面是 Modal 那一层（有 .ant-modal、没有 .ant-popover 版的旧壳）—— 尺寸由 AD-66 量',
    paneShape.modalW > 0 &&
      (await page.locator('.ant-modal .rcp').count()) === 1 &&
      (await page.locator('.ant-popover .rcp').count()) === 0,
    paneShape.modalW);

  const rowGeo = await page.evaluate(() => {
    const row = document.querySelector('.rcp [data-field="max_iterations"]');
    const label = row?.querySelector('.rcp-label');
    const desc = row?.querySelector('.rcp-default');
    const ctl = row?.querySelector('.rcp-input');
    if (!row || !label || !ctl) return null;
    const L = label.getBoundingClientRect();
    const C = ctl.getBoundingClientRect();
    const D = desc?.getBoundingClientRect();
    return {
      labelText: label.textContent ?? '',
      descText: desc?.textContent ?? '',
      ctlRightOfLabel: C.left >= L.right - 1,
      descBelowLabel: D ? D.top >= L.bottom - 1 : false,
      descLeftAlignedWithLabel: D ? Math.abs(D.left - L.left) <= 2 : false,
      ctlRightEdgeNearRow: Math.abs(C.right - row.getBoundingClientRect().right) <= 2,
    };
  });
  check('AD-60 一行是「标签 + 描述在左、控件在右」的几何关系（不是类名对了而 flex 忘了写）',
    Boolean(rowGeo) &&
      rowGeo.ctlRightOfLabel &&
      rowGeo.ctlRightEdgeNearRow &&
      rowGeo.descBelowLabel &&
      rowGeo.descLeftAlignedWithLabel,
    rowGeo);

  /* 基础那一格（默认态，验收要的四张里的第一张）。 */
  await page.locator('.rcp.sc').screenshot({ path: path.join(OUT, 'AD-settings-basic.png') });

  /* 切一次导航：① 中途那一帧顺手量一下淡入是不是**真在跑**（读 opacity，不是读
     animation-name —— 声明了但没跑起来的写法见过太多次；同一帧就是验收要的那张"切换动效"）；
     ② 落定之后量"可见的那格跟着换了"。
     ⚠️ 采样时刻取 55ms / 动画 140ms：太晚量到 1（判据变恒真），太早量到 0.55 起点。
     真红了再看是不是机器慢导致的时序问题，别急着放宽门槛。 */
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(55);
  const midFrame = await page.evaluate(() => {
    const pane = document.querySelector('#sc-panel-model');
    return pane ? { op: +getComputedStyle(pane).opacity, hidden: pane.hasAttribute('hidden') } : null;
  });
  await page.locator('.rcp.sc').screenshot({ path: path.join(OUT, 'AD-settings-switch-frame.png') });
  await page.waitForTimeout(600);
  await page.locator('.rcp.sc').screenshot({ path: path.join(OUT, 'AD-settings-model.png') });
  await page.locator('.sc-nav-item', { hasText: '高级' }).click();
  await page.waitForTimeout(600);
  await page.locator('.rcp.sc').screenshot({ path: path.join(OUT, 'AD-settings-advanced.png') });

  const afterSwitch = await page.evaluate(() => {
    const vis = {};
    const MARK = { basic: '.rcp-preset-row', model: '.rcp-models', advanced: '.rcp-tools' };
    for (const [k, sel] of Object.entries(MARK)) {
      const el = document.querySelector(sel);
      vis[k] = el ? !el.closest('.sc-pane[hidden]') : false;
    }
    const active = [...document.querySelectorAll('.sc-nav-item')].find((b) => b.getAttribute('aria-selected') === 'true');
    return { vis, activeText: active?.textContent ?? '', activeTabbable: active?.getAttribute('tabindex') === '0' };
  });
  check('AD-62 切两次导航之后：可见的那一格跟着换成「高级」，另两格挂着但被 hidden 挡住（挂载过就留着 —— 与原来页签同一语义，remount 会让 AE-12c 那条判据失去可证伪性）',
    afterSwitch.vis.advanced === true &&
      afterSwitch.vis.basic === false &&
      afterSwitch.vis.model === false &&
      afterSwitch.activeText === '高级' &&
      afterSwitch.activeTabbable === true,
    afterSwitch);
  check('AD-65 切过去那一瞬新格子的淡入**真在跑**（中途 opacity 落在 0.55–1 之间，不是只声明了 animation 没生效）',
    Boolean(midFrame) && midFrame.hidden === false && midFrame.op > 0.55 && midFrame.op < 1,
    midFrame);
  /* ⚠️ AD-61 必须排在**「模型」那一格挂载之后**：写这条的第一版放在切导航之前，
     那时内嵌那份根本不在 DOM 里 ⇒ 数出来永远是 1，把 ``embedded`` 改成 false 也照样绿
     （负面对照实测：那一版只红 AD-55b，AD-61 一声不响）。
     "条件渲染的东西要在它存在的地方量"这条口径，本轮在自己写的判据上又踩了一次。 */
  /* 2026-09-29：底栏那两颗（「回落到 .env」+「撤回全部修改」）合成一颗
     「恢复默认配置」，文字链样式。判据跟着改名字与数量 ——
     "这一屏只有一颗做这件事的控件"这条**没松**（两颗做同一件事 = 迟早只禁一颗）。 */
  const envBtn = await page.evaluate(() =>
    [...document.querySelectorAll('.ant-modal button, .ant-modal .rcp-restore')]
      .filter((b) => (b.textContent ?? '').includes('恢复默认配置')).length,
  );
  check('AD-61 「恢复默认配置」这一屏只有一颗（旧的两颗合并后的唯一一份；内嵌那份面板里的同名按钮不画）',
    envBtn === 1, envBtn);

  /* ================= 960×600 那一档（2026-09-27 第二趟：容器换宽、同时把高换矮） =================
     四条各钉一种"改坏了肉眼看不出来"的形状：
     ① 尺寸与比例 —— 高**与**宽都量：只把 height 写成 max-height，界面看起来完全正常，
        而"切换三格不跳高"当场就没了（NC-geo 判的就是这一条）；
     ② **加宽的是容器，不是行长** —— 右格限宽 720 且**靠左**（写成 margin:auto 就变成
        "居中一段窄栏"，那是另一种排版，浅色底上肉眼很难发现）；
     ③ 左导航 120（2026-09-29 从 160 收窄）：量的是**它把多少宽度让给了内容**；
     ④ 三格各切一次，整窗高度三次数值全等。 */
  const box = await page.evaluate(() => {
    const c = document.querySelector('.ant-modal-content')?.getBoundingClientRect();
    const nav = document.querySelector('.sc-nav')?.getBoundingClientRect();
    const body = document.querySelector('.sc-body');
    const pane = document.querySelector('.sc-pane:not([hidden])');
    if (!c || !nav || !body || !pane) return null;
    const B = body.getBoundingClientRect();
    const P = pane.getBoundingClientRect();
    return {
      w: Math.round(c.width),
      h: Math.round(c.height),
      navW: Math.round(nav.width),
      paneW: Math.round(P.width),
      leftGap: Math.round(P.left - B.left),
      padLeft: Math.round(parseFloat(getComputedStyle(body).paddingLeft) || 0),
      rightGap: Math.round(B.right - P.right),
    };
  });
  check('AD-66 整窗 960×600（±12）、比例约 16:10 ⇒ 宽扁；高是容器给的，不是内容顶出来的',
    Boolean(box) &&
      Math.abs(box.w - 960) <= 12 &&
      Math.abs(box.h - 600) <= 12 &&
      box.w / box.h > 1.5 &&
      box.w / box.h < 1.72,
    box);
  check('AD-67 左导航 120、右格限宽 720 且**靠左**（左间隙=内边距，右间隙明显更大 ⇒ 不是居中窄栏）',
    Boolean(box) &&
      Math.abs(box.navW - 120) <= 2 &&
      box.paneW <= 722 &&
      box.leftGap === box.padLeft &&
      box.rightGap >= box.leftGap + 20,
    box);

  /* 120 那一档收窄之后唯一的风险是**两个字折行**（「基础 / 模型 / 高级」都是两字）。
     折行之后导航项变两行高，选中态那条高亮条也跟着变长 —— 肉眼看只是"变挤了"，
     但这一屏的"切三格不跳高"那条（AD-68）会当场失去意义。
     判据读几何而不是读文字：每一项 clientHeight 必须还在一行（≤ 单行高的 1.6 倍），
     且三项都**不换行**（scrollWidth 不超出 clientWidth）。 */
  /* ⚠️ 折行要量**文字**占了几行，不能拿 border-box 的高度去除行高：
     这一版第一遍就是这么写的（33 / 19.5 ≈ 1.69 ⇒ round 成 2），把 8+8 的纵向内边距
     也算成了文字 —— 于是"没折行"被读成"折了"，而且三个字项一起红，看着像真的。
     改法两条一起：① 从高度里**减掉** padding 与 border 再除；② 用 Range 数**行盒**
     （getClientRects 一条线盒一个矩形），两个读数互相印证，任一个 >1 就是折了。 */
  const navFit = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.sc-nav-item')];
    return items.map((b) => {
      const cs = getComputedStyle(b);
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5;
      const box = b.getBoundingClientRect().height;
      const pad =
        parseFloat(cs.paddingTop) +
        parseFloat(cs.paddingBottom) +
        parseFloat(cs.borderTopWidth) +
        parseFloat(cs.borderBottomWidth);
      const range = document.createRange();
      range.selectNodeContents(b);
      return {
        text: (b.textContent ?? '').trim(),
        lines: Math.round((box - pad) / lh),
        lineBoxes: range.getClientRects().length,
        clipped: b.scrollWidth > b.clientWidth + 1,
      };
    });
  });
  check('AD-67b 120px 导航下三项都不折行、不裁切（收窄导航唯一会坏的就是这一条）',
    navFit.length === 3 &&
      navFit.every((it) => it.lines <= 1 && it.lineBoxes <= 1 && it.clipped === false),
    navFit);

  const heights = {};
  for (const tab of ['基础', '模型', '高级']) {
    await page.locator('.sc-nav-item', { hasText: tab }).click();
    await page.waitForTimeout(450);
    heights[tab] = await page.evaluate(
      () => Math.round(document.querySelector('.ant-modal-content')?.getBoundingClientRect().height ?? 0),
    );
  }
  check('AD-68 切过三格，整窗高度三次数值全等（内容长短不改变窗口尺寸 ⇒ 切换不跳）',
    heights.基础 > 0 && heights.模型 === heights.基础 && heights.高级 === heights.基础, heights);

  /* ---------- 模型候选的下拉：两行一项、宽度够、禁止横向溢出 ----------
     ⚠️ 必须在**内嵌那一档**量（齿轮那份弹层只有 430 宽，同一份组件的另一个宿主）。
     判据读几何与计算样式，不是"类名在不在"：类名都写对而 white-space 忘了改，
     读回来照样是"字被截断"，而截断在截图里最不容易看出来（尾巴直接没了，连省略号都不留）。 */
  /* ⚠️ 上面那个"切三格量高度"的循环停在「高级」，而"高级"以外的格此刻是 ``hidden`` ——
     hidden 里的那枚 input **存在但点不动**（Playwright 判不可见，死等 30 秒后整趟中断）。
     读条件渲染的东西要先把它换到台前：与 AD-61（要在「模型」挂载之后数按钮）同一口径。 */
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(450);
  await page.locator('.sc-card .model-settings-input input').first().click();
  await page.waitForTimeout(500);
  const pop = await page.evaluate(() => {
    const dd = document.querySelector('.ms-model-pop');
    if (!dd) return { present: false };
    const opt = dd.querySelector('.ant-select-item-option');
    const name = opt?.querySelector('.ms-opt-name');
    const sub = opt?.querySelector('.ms-opt-sub');
    const R = (el) => (el ? el.getBoundingClientRect() : null);
    const D = R(dd);
    const N = R(name);
    const S = R(sub);
    const cs = (el) => (el ? getComputedStyle(el) : null);
    const over = (sel) => [...dd.querySelectorAll(sel)].some((e) => e.scrollWidth > e.clientWidth + 1);
    return {
      present: true,
      w: Math.round(D.width),
      wantW: Math.round(Math.min(600, window.innerWidth * 0.9)),
      h: Math.round(D.height),
      n: dd.querySelectorAll('.ant-select-item-option').length,
      twoLines: Boolean(N && S) && S.top >= N.bottom - 1,
      nameOver: over('.ms-opt-name'),
      subOver: over('.ms-opt-sub'),
      wrap: cs(dd.querySelector('.ant-select-item-option-content'))?.whiteSpace ?? '',
      nameFs: parseFloat(cs(name)?.fontSize ?? '0'),
      subFs: parseFloat(cs(sub)?.fontSize ?? '0'),
      firstName: name?.textContent ?? '',
      firstSub: sub?.textContent ?? '',
      /* 逐条把两行都收下来：AD-69d 要看的是"**被我选中的那一条**的第二行"，
         只留 first* 的话，点第二条候选就会拿第一条的行去比 —— 本轮就是这么红的
         （读数里 ``pickedText=glm-4.6`` 与 ``firstName=deepseek-flash`` 同时出现，
         差的是"我量的是哪一条"，不是界面少了东西）。 */
      lines: [...dd.querySelectorAll('.ant-select-item-option')].map((o) => ({
        name: o.querySelector('.ms-opt-name')?.textContent ?? '',
        sub: o.querySelector('.ms-opt-sub')?.textContent ?? '',
      })),
    };
  });
  check('AD-69 候选弹层宽=min(600px,90vw)、限高在 360 那一档内、**DOM 里的条数等于响应的 catalog**（虚拟列表没把候选窗口化掉）',
    pop.present === true &&
      Math.abs(pop.w - pop.wantW) <= 2 &&
      pop.h > 100 &&
      pop.h <= 360 + 16 &&
      pop.n === modelsBodyWithCatalog.catalog.length,
    pop);
  check('AD-69b 一条候选是**两行**（第二行在第一行下面）、两行都不横向溢出、white-space 真的被改成 normal、字号不小于 12',
    pop.twoLines === true &&
      pop.nameOver === false &&
      pop.subOver === false &&
      pop.wrap === 'normal' &&
      pop.nameFs >= 12 &&
      pop.subFs >= 12,
    { twoLines: pop.twoLines, over: [pop.nameOver, pop.subOver], wrap: pop.wrap, fs: [pop.nameFs, pop.subFs] });
  await page.locator('.rcp.sc').screenshot({ path: path.join(OUT, 'AD-settings-dropdown.png') });

  /* 选中一条候选 ⇒ 框里只剩那串干净的模型 id。
     期望值取**桩里的**字段（不在探针里写死某个模型名 —— 写死就等于探针读自己）。 */
  const wantEntry = modelsBodyWithCatalog.catalog[1];
  await page
    .locator('.ms-model-pop .ant-select-item-option', { hasText: wantEntry.id })
    .first()
    .click();
  await page.waitForTimeout(400);
  const pickedText = await page.evaluate(
    () => document.querySelector('.sc-card .model-settings-input input')?.value ?? '',
  );
  const stubIds = modelsBodyWithCatalog.catalog.map((e) => e.id);
  check('AD-69c 每一条的第一行**就是一个模型 id**（不带展示名的括号、不带单价 ⇒ 那些留在第二行）',
    pop.lines.length === stubIds.length &&
      pop.lines.every((l) => stubIds.includes(l.name)) &&
      pop.lines.every((l) => !l.name.includes('（') && !l.name.includes('元')),
    pop.lines.map((l) => l.name));
  check('AD-69d 选中之后框里只有那串模型 id，而那一条的**第二行**里展示名与单价都在（拆两行是把信息挪下去，不是删掉）',
    pickedText === wantEntry.id &&
      (() => {
        const line = pop.lines.find((l) => l.name === wantEntry.id);
        return Boolean(line) &&
          line.sub.includes(wantEntry.display_name) &&
          line.sub.includes(wantEntry.tiers_text);
      })(),
    { pickedText, id: wantEntry.id, line: pop.lines.find((l) => l.name === wantEntry.id) });

  /* ---------- API Key 那一栏：标题、对齐、状态行、那句提示 ---------- */
  const keyGeo = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.ms-keybox .ms-key-row')];
    const ctlOf = (r) =>
      r.querySelector('.ant-select') ??
      r.querySelector('.ant-input-affix-wrapper') ??
      r.querySelector('input');
    const labels = rows.map((r) => r.querySelector('.ms-key-label')?.getBoundingClientRect());
    const ctrls = rows.map((r) => ctlOf(r)?.getBoundingClientRect());
    const R = rows.map((r) => r.getBoundingClientRect());
    const note = document.querySelector('.ms-key-note');
    /* 2026-09-29：标题从 ``.model-settings-subtitle`` 并进 §15 的 ``.ms-section-title``
       （三个板块的小标题现在是同一族），读点跟着改 —— 不改的话这里量到空串，
       而"标题还在不在"这条判据会**静默绿**（空串 startsWith 也成立不了 ⇒ 红的是
       AD-71 而不是"标题丢了"，但因为 titleText 是空，报错信息里看不出是选择器旧了）。 */
    const title = document.querySelector('.ms-keybox .ms-section-title');
    return {
      rows: rows.length,
      labelLeftSame: labels.every((b) => Boolean(b) && Math.abs(b.left - labels[0].left) <= 1),
      colW: labels[0] && ctrls[0] ? Math.round(ctrls[0].left - labels[0].left) : 0,
      ctrlLeftSame: ctrls.every((b) => Boolean(b) && Math.abs(b.left - ctrls[0].left) <= 1),
      /* 「撑满剩余宽度」读成几何而不是读绝对像素：控件的右边缘就是那一行的右边缘
         （误差 2px 以内）。写成 ``width > 500`` 那种数，换个视口就得改判据。 */
      filled: ctrls.every((b, i) => Boolean(b) && Math.abs(b.right - R[i].right) <= 2),
      titleText: (title?.textContent ?? '').trim(),
      hasInfo: Boolean(title?.querySelector('.ms-key-info')),
      infoTab: title?.querySelector('.ms-key-info')?.getAttribute('tabindex') ?? null,
      noteText: (note?.textContent ?? '').trim(),
      noteFs: note ? parseFloat(getComputedStyle(note).fontSize) || 0 : 0,
      btns: [...document.querySelectorAll('.ms-key-actions button')].map((b) => (b.textContent ?? '').trim()),
      firstLine: (document.querySelector('.ms-key-list li')?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    };
  });
  check('AD-70 三行标签左缘对齐、控件左缘对齐、标签列 80px，且三格控件都**撑到行尾**（不跟弹窗变宽而空一条）',
    keyGeo.rows === 3 &&
      keyGeo.labelLeftSame &&
      keyGeo.ctrlLeftSame &&
      Math.abs(keyGeo.colW - 80) <= 10 &&
      keyGeo.filled === true,
    keyGeo);
  /* 2026-09-29：Key 那一栏这一轮改了三处 ——
     ① 「校验」从下面那排按钮搬进**输入框右端**（图标按钮，靠 aria-label 报名字）；
     ② 那句"仅覆盖本次运行的内存…不落盘"独立说明行删了，话搬进 placeholder；
     ③ 三行供应商状态清单整块删了。
     判据跟着改：仍然判"标题 + ⓘ + 应用到本次运行在"，新增判"校验是图标按钮且有名字"
     与"placeholder 是那句固定话术"，删掉的那条说明行改成**负面对照**（见 AD-71c）。 */
  const keyCtl = await page.evaluate(() => {
    const probe = document.querySelector('.ms-key-probe');
    const outer = document.querySelector('.sc-card .ms-key-input');
    /* ``.ms-key-input`` 是 AntD 给的**外层 affix 包装**（span），placeholder 落在
       里面那个真 ``<input>`` 上 —— 直接读包装读到的是空串，于是"那句固定话术在不在"
       会永远红（而报错里只看到 ``placeholder: ""``，看不出是读点错了）。 */
    const input = outer && outer.tagName === 'INPUT' ? outer : outer?.querySelector('input');
    const wrap = input?.closest('.ant-input-affix-wrapper') ?? outer;
    return {
      probeCount: document.querySelectorAll('.ms-key-probe').length,
      probeLabel: probe?.getAttribute('aria-label') ?? '',
      probeTag: probe?.tagName ?? '',
      /* 「在输入框右端」读成几何：那颗按钮在 affix wrapper 里、且贴着它的右边缘。 */
      probeInside: Boolean(probe && wrap && wrap.contains(probe)),
      probeNearRight: Boolean(
        probe && wrap &&
          Math.abs(probe.getBoundingClientRect().right - wrap.getBoundingClientRect().right) <= 14,
      ),
      placeholder: input?.getAttribute('placeholder') ?? '',
      noteRows: document.querySelectorAll('.ms-key-note').length,
    };
  });
  check('AD-71 标题仍是「API Key 配置」+ 一枚可聚焦的 ⓘ，「应用到本次运行」在主按钮位',
    keyGeo.titleText.startsWith('API Key 配置') &&
      keyGeo.hasInfo === true &&
      keyGeo.infoTab === '0' &&
      keyGeo.btns.some((t) => /应\s*用\s*到\s*本\s*次\s*运\s*行/.test(t)),
    { title: keyGeo.titleText, btns: keyGeo.btns });
  check('AD-71b 「校验」是输入框右端那颗**图标按钮**、带 aria-label、placeholder 是那句固定话术',
    keyCtl.probeCount === 1 &&
      keyCtl.probeTag === 'BUTTON' &&
      keyCtl.probeLabel === '校验' &&
      keyCtl.probeInside === true &&
      keyCtl.probeNearRight === true &&
      keyCtl.placeholder === '输入新 Key 仅本次运行生效，重启恢复环境变量',
    keyCtl);
  /* 负面对照：删掉的三处不许长回来。
     ⚠️ 三条一起判而不是各判一条 —— "整块删了"是一件事，写三条会占用三个断言位
     而它们红起来的原因完全一样（有人把那块加回来了）。 */
  check('AD-71c 删掉的三处都不在场：独立说明行 / 三行状态清单 / 单价说明',
    keyCtl.noteRows === 0 &&
      (await page.evaluate(() => document.querySelectorAll('.ms-key-list').length)) === 0 &&
      (await page.evaluate(() => document.querySelectorAll('.model-settings-price').length)) === 0,
    { noteRows: keyCtl.noteRows });

  /* Key 那一栏在 600px 高的窗口里**落在折叠线以下** —— 验收要看的就是这一屏排完对齐
     之后长什么样，所以趁读数齐备（状态行、按钮、提示语都在场）单独留一张。
     Playwright 的 element screenshot 会先把目标滚进视野，滚动只发生在 .sc-body 那一格。 */
  await page.locator('.ms-keybox').screenshot({ path: path.join(OUT, 'AD-settings-keybox.png') });

  /* ---------- 向量模型那一行（这一栏此前**一条判据都没有**） ---------- */
  /* 2026-09-29：标题改用 .ms-section-title（与「模型配置」「API Key 配置」同一族），
     正文里那个「（只读）」括号换成**模型名右侧一枚锁图标**。
     判据跟着改：括号串不许还在，锁必须在、且带 aria-label（读屏拿得到"改不了"这件事）。 */
  const embed = await page.evaluate(() => {
    const t = [...document.querySelectorAll('.ms-section-title')].find((n) =>
      (n.textContent ?? '').startsWith('向量模型'),
    );
    const note = t?.nextElementSibling;
    const lock = note?.querySelector('.ms-embed-lock') ?? null;
    return {
      titleText: (t?.textContent ?? '').trim(),
      hasLock: Boolean(lock),
      lockLabel: lock?.getAttribute('aria-label') ?? '',
      lockRole: lock?.getAttribute('role') ?? '',
      noteText: (note?.textContent ?? '').trim(),
      hasButton: Boolean(note?.querySelector('button')),
    };
  });
  check('AD-72 向量模型：小标题不带括号说明、正文是「当前使用：X」+ 一枚带名字的锁、那一行里没有按钮（只给读数这条没松）',
    embed.titleText === '向量模型' &&
      embed.hasLock === true &&
      embed.lockRole === 'img' &&
      embed.lockLabel.length > 0 &&
      /^当前使用：.+$/.test(embed.noteText) &&
      !embed.noteText.includes('（只读）') &&
      embed.hasButton === false,
    embed);
  await page.locator('.ms-embed-lock').hover();
  await page.waitForTimeout(500);
  const embedTip = await page.evaluate(() => {
    const trig = document.querySelector('.ms-embed-lock');
    const id = trig?.getAttribute('aria-describedby') ?? '';
    return (id ? document.getElementById(id) : null)?.textContent ?? '';
  });
  check('AD-72b 那句"为什么会 409、要重建索引"真的在锁的浮层里（从 ⓘ 搬到锁不等于搬丢了）',
    embedTip.includes('409') && embedTip.includes('重建索引'), embedTip.slice(0, 70));
  /* API Key 那颗 ⓘ 的浮层：AE-1 在齿轮那一档判，这里在内嵌这一档再判一次 ——
     同一句话的两个宿主，漏一个就是"这一屏其实没说过"。 */
  await page.locator('.ms-key-info').hover();
  await page.waitForTimeout(500);
  const keyTip = await page.evaluate(() => {
    const trig = document.querySelector('.ms-key-info');
    const id = trig?.getAttribute('aria-describedby') ?? '';
    return (id ? document.getElementById(id) : null)?.textContent ?? '';
  });
  check('AD-72c 内嵌这一档的 ⓘ 也打得开，里面是 U-4 那三条约束原话',
    keyTip.includes('本进程') && keyTip.includes('重启回落') && keyTip.includes('不回显'),
    keyTip.slice(0, 70));
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
  await openPanel(page);

  /* ---------- 「角色绑定」那一行小字（2026-09-29 顶掉原来那张五行表） ----------
     五行表删掉的理由写在那份注释里：后端只认两个档位，那五行**永远不可能不一致**，
     信息量是零。所以这一条判的是"删掉之后那句话还在不在、说得对不对"，
     以及"那张表确实没赖着不走"（负面对照 —— 只判"新文案在场"的话，
     新旧并存也能过）。
     ⚠️ 文案**逐字**对：这一行是这一屏唯一一处说清"两档各管谁"的地方，
        少一个角色名就是一句不完整的话。 */
  const roleBlock = await page.evaluate(() => {
    const line = document.querySelector('.ms-rolebind-text');
    const info = document.querySelector('.ms-rolebind-info');
    const cs = line ? getComputedStyle(line) : null;
    return {
      text: (line?.textContent ?? '').trim(),
      fontSize: cs ? parseFloat(cs.fontSize) : 0,
      /* "灰色"读成"不是正文色"：与同屏那段标题的 --text-2 比，它必须更浅一档。 */
      lighterThanTitle: Boolean(
        cs &&
          (() => {
            const t = document.querySelector('.ms-section-title');
            return t ? cs.color !== getComputedStyle(t).color : false;
          })(),
      ),
      /* 无交互：这一行里不许有按钮 / 链接 / 可编辑的东西。 */
      interactive: line
        ? line.querySelectorAll('button, a, input, select, textarea').length
        : 0,
      hasInfo: Boolean(info),
      infoLabel: info?.getAttribute('aria-label') ?? '',
      /* 负面对照：那张五行表与它的两个 Tag 类都不许还在。 */
      oldRows: document.querySelectorAll('.rcp-model-list li').length,
      oldTiers: document.querySelectorAll('.rcp-model-tier').length,
      oldSrc: document.querySelectorAll('.rcp-model-src').length,
      oldTitle: [...document.querySelectorAll('.sc-group-title, .ms-section-title')].some((n) =>
        (n.textContent ?? '').includes('角色模型映射'),
      ),
    };
  });
  check('AD-73 「角色绑定」那一行小字在场、逐字完整、12px 灰字、无交互（顶掉原来那张五行表）',
    roleBlock.text ===
      '角色绑定：决策模式 → Planner / Reviewer / Judge · 执行模式 → Executor / Extract' &&
      roleBlock.fontSize === 12 &&
      roleBlock.lighterThanTitle === true &&
      roleBlock.interactive === 0 &&
      roleBlock.hasInfo === true &&
      roleBlock.infoLabel.length > 0,
    roleBlock);
  check('AD-73b 那张五行表整块不在场（.rcp-model-list / .rcp-model-tier / .rcp-model-src 全是 0，旧标题也没了）',
    roleBlock.oldRows === 0 &&
      roleBlock.oldTiers === 0 &&
      roleBlock.oldSrc === 0 &&
      roleBlock.oldTitle === false,
    roleBlock);
  await page.locator('.sc-nav-item', { hasText: '基础' }).click();
  await page.waitForTimeout(400);

  await page.locator('.rcp-preset-row .ant-select-selector').click();
  await page.waitForTimeout(450);
  const presetLabels = await page.evaluate(() =>
    [...document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content',
    )].map((el) => el.textContent ?? ''),
  );
  check('AD-02 预设下拉的**条数与文字**都来自响应（桩里 3 档、名字与后端那一版不同也无所谓 —— 数的是响应给的）',
    presetLabels.length === variants.base.presets.length &&
      variants.base.presets.every((p) => presetLabels.some((t) => t.includes(p.label))),
    presetLabels);

  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option', {
    hasText: '深度模式',
  }).click();
  await page.waitForTimeout(500);
  const deep = variants.base.presets.find((p) => p.id === 'deep').values;
  const v1 = await num(page, 'max_iterations');
  const v2 = await num(page, 'max_cost_cny');
  const v3 = await num(page, 'timeout_s');
  check('AD-03 套上"深度模式"⇒ 三个输入框用的是**响应里那档的值**（9 轮 / ¥6.66 / 900 秒，桩值，前端没有这份表）',
    v1 === String(deep.max_iterations) && v2 === String(deep.max_cost_cny) && v3 === String(deep.timeout_s),
    { v1, v2, v3, deep });
  check('AD-04 面板套完预设，右下角那行读数跟着变（**同一份状态**，不是两处各写一遍）',
    (await hint(page)).startsWith(`${deep.max_iterations} ${stubUnit('max_iterations')}`), await hint(page));

  await fieldInput(page, 'max_iterations').fill('8');
  await page.waitForTimeout(400);
  check('AD-05 面板里手改迭代 ⇒ 页脚读数变成 8 + **桩给的那个后缀**（"8 次"而不是"8 轮"：单位也是读的）',
    (await hint(page)).startsWith(`8 ${stubUnit('max_iterations')}`), await hint(page));
  check('AD-06 手改过任何一项 ⇒ 预设标记失效（值已经不是那一档了，标签不该还挂着）',
    await page.evaluate(() => {
      const el = document.querySelector('.rcp-preset-row .ant-select-selection-item');
      return el === null || (el.getAttribute('title') ?? '').length === 0;
    }));

  await page.locator('.sc-nav-item', { hasText: '高级' }).click();
  await page.waitForTimeout(450);
  const toolNames = await page.evaluate(() =>
    [...document.querySelectorAll('.rcp-tool .rcp-tool-name')].map((el) => el.textContent ?? ''),
  );
  const stubNames = toolsBody.items.map((t) => t.name);
  check('AD-07 工具清单**逐条等于** GET /tools 那一份（六条，含页面从没写过的 extract/file_io/web_search）',
    toolNames.length === stubNames.length && stubNames.every((n) => toolNames.some((t) => t.includes(n))),
    toolNames);
  check('AD-08 清单里那条 knowledge_search 带着"RAG 开关管的就是这条"的标记（两个入口钉在同一件事上）',
    await page.evaluate(() => {
      const row = [...document.querySelectorAll('.rcp-tool')].find((el) =>
        (el.textContent ?? '').includes('knowledge_search'));
      return Boolean(row) && (row.textContent ?? '').includes('RAG 开关管的就是这条');
    }));

  /* ---------- 双向：面板取消勾选 → composer 开关跟着灭 ---------- */
  const before = await switchStates(page);
  await page.locator('.rcp-tool', { hasText: 'knowledge_search' }).locator('input[type=checkbox]').click();
  await page.waitForTimeout(400);
  const afterPanel = await switchStates(page);
  check('AD-09 面板里取消勾选 knowledge_search ⇒ composer 那颗 RAG 开关自己灭了（面板→开关方向）',
    before[1] === 'true' && afterPanel[1] === 'false', { before, afterPanel });

  /* ---------- 双向：composer 开关打开 → 面板那条复选框跟着回勾 ----------
     ⚠️ 这一条与上一条是**同一枚判据的两半**：只测一个方向时，"两份本地 state 各自
     被对方同步一次"的写法照样全绿。AD-neg1 就是把这里拆成两份 state —— 红的正是这两条。
     2026-09-27 多了一关一开：这一层是 Modal，遮罩挡着 composer ⇒ 隔着遮罩点那颗开关
     点不到（真用户也点不到，这是模态本身）。关掉再点、点完再开回来，
     两半判据量的还是同一份 Context —— 方向性没被这层容器改变。 */
  await closeSettingsLayer(page);
  await page.locator('.switch-row').nth(1).locator('.ant-switch').click();
  await page.waitForTimeout(400);
  check('AD-10 再点 composer 那颗 RAG 开关 ⇒ 面板里那条复选框回到勾上（开关→面板方向，两半合起来才是"只有一份状态"）',
    await page.evaluate(() => {
      const row = [...document.querySelectorAll('.rcp-tool')].find((el) =>
        (el.textContent ?? '').includes('knowledge_search'));
      return Boolean(row) && row.querySelector('input[type=checkbox]')?.checked === true;
    }));
  /* 开回来给下面那几条读（.rcp-unsupported 那一栏现在住在「高级」这一格里）。 */
  await openPanel(page);

  /* ---------- accepted=false ⇒ 没有控件，只列名 ---------- */
  check('AD-11 后端 accepted=false 的 reviewer_enabled **没有控件**（既不在基础也不在高级）',
    (await page.locator('[data-field="reviewer_enabled"]').count()) === 0);
  check('AD-12 但它出现在「后端暂不支持以下配置」里，并带上后端给的原因原话',
    await page.evaluate(() => {
      const box = document.querySelector('.rcp-unsupported');
      const t = box?.textContent ?? '';
      return t.includes('Reviewer') && t.includes('后端没有这个开关');
    }));

  /* ---------- 等宽到底有没有生效（AD-44） ----------
     这条的存在理由很具体：本轮之前 ``var(--font-mono)`` / ``var(--mono)`` 在样式里被引用 4 处，
     而**构建产物里一个定义都没有**（``grep -c -- '--mono:' dist/assets/*.css`` = 0）
     ⇒ 那四条 ``font-family`` 是被**静默丢弃**的：不报错、不崩、tsc 与 build 全绿，
     只是模型 id 胶囊与键名悄悄退回 Inter。像素上"看着还行"，所以只能读计算样式。
     ⚠️ 必须先访问「模型」页签：AntD 的页签**首次激活才挂载**，
     没点过就没有那个节点 —— 那时量到 1 处会误判成通过。
     2026-09-29：第二处读点从 ``.rcp-model-id``（角色映射表里那颗模型 id 胶囊，
     那张表整块删了）换成 ``.ms-embed-id``（向量模型那一行里的模型 id）——
     同样是等宽胶囊、同样住在「模型」这一格，所以"必须先访问这一格"那个前件不变，
     而这条判据仍然盯着"等宽令牌到底定义没定义"这一件事。 */
  await openPanel(page);
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(450);
  const monoFams = await page.evaluate(() =>
    ['.rcp-unsupported-key', '.ms-embed-id']
      .map((sel) => {
        const el = document.querySelector(sel);
        return el ? { sel, fam: getComputedStyle(el).fontFamily ?? '' } : null;
      })
      .filter(Boolean),
  );
  check('AD-44 键名行与模型 id 的计算样式里真的是 JetBrains Mono（令牌没定义时这条会静默绿，所以读 fam）',
    monoFams.length === 2 && monoFams.every((r) => /JetBrains Mono/.test(r.fam)), monoFams);
  check('AD-44b 前件：两处都真量到了（某处为空 = 页签没挂载或选择器写错，不是通过）',
    monoFams.length === 2, monoFams.map((r) => r.sel));

  /* ---------- 软上限的话必须是看得见的字（P-4） ---------- */
  /* 弹层此刻**还开着**（上一步 AD-44 才打开过）⇒ 这里只切页签，绝不能再 openPanel 一次：
     那颗胶囊是 toggle，再点一下就关了，而关掉的 Popover 里的页签是"在 DOM 里但点不动"
     —— 这一脚 AD 趟第一版踩过（报的是 element is not visible）。 */
  await page.locator('.sc-nav-item', { hasText: '基础' }).click();
  await page.waitForTimeout(400);
  const helps = await page.evaluate(() =>
    [...document.querySelectorAll('.rcp-help')].map((el) => el.textContent ?? ''),
  );
  check('AD-13 "节点之间才检查"这句话以**正文**在场（不在 tooltip 里）',
    helps.some((t) => t.includes('节点之间才检查')), helps.map((t) => t.slice(0, 24)));
  check('AD-14 全场没有把评审开关当控件：面板里不存在第二个"迭代"输入框（一语义一控件）',
    (await page.locator('.rcp [data-field="max_iterations"]').count()) === 1);

  /* ---------- 字段名与单位后缀都必须是响应给的那份（§2.1 对账：unit 进契约） ----------
     桩里刻意写成"次 / 档 / 块钱 / 秒钟 / 篇"，后端真值是"轮 / 分 / 元 / 秒 / 条"：
     界面上出现**桩的措辞**就证明它是从 ``fields[]`` 读的。反过来，如果这一屏哪天
     退回成前端自己那张表，AD-37 会当场量到"轮"而不是"次"。 */
  const stubFields = Object.fromEntries(variants.base.fields.map((f) => [f.key, f]));
  const unitRows = await page.evaluate(() =>
    [...document.querySelectorAll('.rcp [data-field]')].map((el) => ({
      key: el.getAttribute('data-field') ?? '',
      addon: el.querySelector('.ant-input-number-group-addon')?.textContent?.trim() ?? '',
      label: el.querySelector('.rcp-label')?.textContent?.trim() ?? '',
    })),
  );
  check('AD-37 前件：面板里五行数值行都在 DOM 里（基础三个 + 高级两个，页签切过就不卸载）',
    unitRows.length === 5, unitRows.map((r) => r.key));
  check('AD-37b 每一行的**字段名与单位后缀逐条等于响应给的 label / unit**（桩措辞：次·档·块钱·秒钟·篇）',
    unitRows.every((r) => stubFields[r.key] && r.label === stubFields[r.key].label &&
      r.addon === (stubFields[r.key].unit ?? '')),
    unitRows.map((r) => ({ k: r.key, got: `${r.label}|${r.addon}`, want: `${stubFields[r.key]?.label}|${stubFields[r.key]?.unit}` })));
  check('AD-37c 反向哨兵：界面后缀/字段名没有一个落回**后端那一版的措辞**（轮·分·元·秒·条 / 最大迭代轮数…）',
    /* 后端 2026-09-26 那一版的真值写在这里当**反例**。界面要是出现它们，说明前端自带了
       一张字段表（把响应当参考、把这张表当默认）。后端将来改措辞时要跟着改的是**桩**
       和这里的反例清单，不是界面 —— 这条判据故意会过期。 */
    unitRows.every((r) => !['轮', '分', '元', '秒', '条'].includes(r.addon)) &&
      unitRows.every((r) =>
        !['最大迭代轮数', '评审通过分', '最大成本预算', '任务超时', 'RAG 检索条数上限'].includes(r.label)),
    unitRows.map((r) => `${r.label}|${r.addon}`));

  /* ---------- 这一轮新补的行：review_threshold ----------
     后端 ``fields`` 早就声明它 accepted+enforced，前端却没有行 ⇒ "能配"只在后端成立。
     桩默认 8（后端是 7），所以"界面上那个 8"只可能来自响应。 */
  const rtRow = await page.evaluate(() => {
    const box = document.querySelector('.rcp [data-field="review_threshold"]');
    return {
      present: Boolean(box),
      label: box?.querySelector('.rcp-label')?.textContent?.trim() ?? '',
      def: box?.querySelector('.rcp-default')?.textContent?.trim() ?? '',
      value: box?.querySelector('input')?.value ?? null,
    };
  });
  check('AD-38 高级页签里 review_threshold 有行，且默认读数是桩给的 8（后端 7 ⇒ 出现 8 就是读了响应）',
    rtRow.present && rtRow.value === '8' && rtRow.def.includes(String(variants.base.defaults.review_threshold)),
    rtRow);

  /* ---------- accepted=false 那一栏：契约要点 1 要的是 key + label + help 三件 ----------
     少了 key：出事时对不回请求体里哪个字段（排查的人只剩中文猜）；
     少了 help：只说"不行"不说为什么，下一个人会把这条当成"后端忘了做"再提一遍。 */
  check('AD-39「后端暂不支持」那一行三件齐：等宽 key + 中文 label + 后端给的原因原话',
    await page.evaluate(() => {
      const item = document.querySelector('.rcp-unsupported .rcp-unsupported-item');
      const key = item?.querySelector('code.rcp-unsupported-key')?.textContent?.trim() ?? '';
      const name = item?.querySelector('.rcp-unsupported-name')?.textContent?.trim() ?? '';
      const help = item?.querySelector('.rcp-unsupported-help')?.textContent?.trim() ?? '';
      return key === 'reviewer_enabled' && name.includes('Reviewer') && help.includes('后端没有这个开关');
    }));

  /* ---------- 提交体：只发被碰过的键，且发的就是界面上的数 ---------- */
  await page.fill('textarea.composer-input', 'AD 趟：界面与请求体同一个口径');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1000);
  const b1 = s1.submit.state.bodies[0] ?? {};
  check('AD-15 抓到请求体（没抓到后面全是空话）', s1.submit.state.bodies.length === 1, s1.submit.state.bodies.length);
  check('AD-16 键集合恰好 task + 碰过的三项（RAG 已回勾 ⇒ 不发白名单；没碰过的 rag_top_k/use_tools 也不发）',
    JSON.stringify(bodyKeys(b1)) === JSON.stringify(['max_cost_cny', 'max_iterations', 'task', 'timeout_s']),
    bodyKeys(b1));
  check('AD-17 发出去的数就是界面上那几个（8 轮 / ¥6.66 / 900 秒）',
    b1.max_iterations === 8 && b1.max_cost_cny === 6.66 && b1.timeout_s === 900, b1);
  check('AD-40 界面上显示着默认 8 分、用户没碰过 ⇒ 请求体里**没有** review_threshold（显示默认 ≠ 发表意见）',
    !('review_threshold' in b1) && rtRow.value === '8', Object.keys(b1));
  check('AD-18 回执与发出的一致 ⇒ 那条"未被确认"的提示**不出现**（一致时不该占一屏地方）',
    (await page.locator('.cfg-issue').count()) === 0);
  await s1.ctx.close();

  /* ================= 场景 2：老后端少字段 ================= */
  const s2 = await newPage({ options: variants.legacy });
  page = s2.page;
  await openPanel(page);
  await openAdvanced(page);
  check('AD-19 响应里没有 presets ⇒ 预设下拉**整条不出现**（不是灰掉、更不是前端自己补三档）',
    (await page.locator('.rcp-preset-row').count()) === 0);
  check('AD-20 fields 里没声明 timeout_s ⇒ 那行没有控件，但它进了「有界没声明」那一段（线索不许丢）',
    (await page.locator('[data-field="timeout_s"]').count()) === 0 &&
      await page.evaluate(() => (document.querySelector('.rcp-unknown')?.textContent ?? '').includes('timeout_s')));
  check('AD-21 后端没报 rag_tool ⇒ RAG 开关 disabled，且把原因写进 aria-label（置灰必须有话说）',
    await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.switch-row')];
      const sw = rows[1]?.querySelector('.ant-switch');
      return Boolean(sw) && (sw.disabled === true || sw.getAttribute('aria-disabled') === 'true') &&
        (sw.getAttribute('aria-label') ?? '').includes('暂不可用');
    }));
  await page.fill('textarea.composer-input', 'AD 趟：字段少一半也不替后端发默认值');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1000);
  const b2 = s2.submit.state.bodies[0] ?? {};
  check('AD-22 这一档的提交体**只有 task**（少字段 ⇒ 少控件 ⇒ 也少发东西，绝不回落成前端那份默认表）',
    JSON.stringify(bodyKeys(b2)) === JSON.stringify(['task']), bodyKeys(b2));
  await s2.ctx.close();

  /* ================= 场景 3：后端比界面新 ================= */
  const s3 = await newPage({ options: variants.future });
  page = s3.page;
  await openPanel(page);
  await openAdvanced(page);
  const unknownText = await page.evaluate(() => document.querySelector('.rcp-unknown')?.textContent ?? '');
  check('AD-23 未知顶层键 planner_hint 以 JSON **原样**透出（不是 console.log，也不是"忽略"）',
    unknownText.includes('planner_hint') && unknownText.includes('temperature'), unknownText.slice(0, 80));
  check('AD-24 不认识的 kind（segmented）单独列一条，仍然给"这一版界面不认识"的实话',
    unknownText.includes('segmented') && unknownText.includes('不认识'));
  check('AD-25 新键没有变成默认值，也没有变成控件',
    (await page.locator('[data-field="sandbox_profile"]').count()) === 0 &&
      (await hint(page)).startsWith(`6 ${stubUnit('max_iterations')}`), await hint(page));
  /* ---------- 第四类未识别：后端说"能配"，界面这一版**没有行** ----------
     eval_seed 在桩里 accepted=true、kind=int、还给了 limits ⇒ 按 ``NumericRow`` 的纪律
     它*本该*有一个输入框，但前端的行表里没这个键（这一版就是不知道它是什么）。
     两种失效要分开钉：**画了个不该画的控件**（配了不生效）与**什么都不说**
     （下一个人只会以为后端没给）。这一条钉的是后者。 */
  check('AD-41 accepted 的数值键 eval_seed：界面没有画控件，但在「后端还给了这些」里点名（不是静默少一栏）',
    (await page.locator('[data-field="eval_seed"]').count()) === 0 &&
      unknownText.includes('eval_seed') && unknownText.includes('没有给行'),
    unknownText.slice(0, 160));
  check('AD-41b eval_seed 既没进默认值也没进请求体（点名 ≠ 采用）',
    (await hint(page)).startsWith(`6 ${stubUnit('max_iterations')}`) &&
      !(await page.evaluate(() => (document.querySelector('.rcp-default')?.textContent ?? '').includes('eval_seed'))));

  /* ---------- 契约要点 1 的**第二半**：accepted=true 而 enforced=false ----------
     为什么这一档要五条判据：它是全站唯一一种"界面说得对、后端做错了"的形状 ——
     ``accepted=false`` 的键压根不发，用户最多抱怨"填不进去"；而这一档填得进去、发得出去、
     回执也照抄，只有实际运行行为不变。把底部那栏警告删掉，AD-01…44 一条都不会红，
     所以本轮之前它**只有代码、没有判据**（桩里八条声明里没有一条是 enforced=false）。
     现在 ``future`` 那一档把 rag_top_k 改成这一档，五件一起量。 */
  const softField = variants.future.fields.find((f) => f.key === 'rag_top_k');
  check('AD-45 前件：这一档后端给的确实是 accepted=true / enforced=false（桩不成立则后面全空转）',
    softField && softField.accepted === true && softField.enforced === false, softField);
  await page.locator('.sc-nav-item', { hasText: '高级' }).click();
  await page.waitForTimeout(300);
  const softRow = await page.evaluate(() => {
    const box = document.querySelector('.rcp [data-field="rag_top_k"]');
    return {
      hasInput: Boolean(box?.querySelector('input')),
      help: box?.querySelector('.rcp-help')?.textContent?.trim() ?? '',
      warn: box?.querySelector('.rcp-warn')?.textContent?.trim() ?? '',
      footer: document.querySelector('.rcp-unenforced')?.textContent?.trim() ?? '',
      unsupportedFooter: document.querySelector('.rcp-unsupported')?.textContent?.trim() ?? '',
    };
  });
  check('AD-46 accepted=true 就**照旧给控件**（"不生效"不等于"不支持"，不许画成只读或不画）',
    softRow.hasInput, softRow);
  check('AD-47 后端那句 help 以**正文**落在这一行（不是 tooltip），行内另有一句"没有执行机制"',
    softRow.help === softField.help && softRow.warn.includes('没有执行机制'), softRow);
  check('AD-48 底部「后端会收下，但当前没有执行机制」点名 key + label，且与「暂不支持」分成两栏',
    softRow.footer.includes('rag_top_k') && softRow.footer.includes(softField.label) &&
      !softRow.footer.includes('reviewer_enabled') && softRow.unsupportedFooter.includes('reviewer_enabled'),
    { footer: softRow.footer.slice(0, 140), unsupported: softRow.unsupportedFooter.slice(0, 90) });
  /* 填这一步要**容错**：如果哪天"不生效 = 不该给控件"那种改法回来了，这一行根本不在 DOM 里，
     直接 `fill()` 会抛到超时并把整趟打断（AD 趟第一版踩过这个形状），那样读到的分母不可信。
     ⇒ 先量"填得进去吗"，再把填不进去当成一条独立的红。 */
  const softInput = page.locator('.ant-modal .rcp [data-field="rag_top_k"] input');
  let softFillable = true;
  try {
    await softInput.fill('9', { timeout: 2500 });
  } catch {
    softFillable = false;
  }
  check('AD-49 前件：那一行**填得进去**（填不进去就谈不上"照样发得出去"，红要红在这一层）',
    softFillable, { softFillable, hasInput: softRow.hasInput });
  /* 那句 help 在这一屏**只能出现一次**：上面那一行已经把后端原话摆在正文里，
     底部那一栏再抄一遍就是"同屏两份同样的话"（本轮清单 P0 反掉的形状，数两份是同一族）。
     这条是刚补的判据，专门钉那个"看起来更周到"的改法。 */
  const helpHits = await page.evaluate((want) =>
    [...document.querySelectorAll('.rcp p, .rcp span')]
      .map((el) => (el.textContent ?? '').trim())
      .filter((t) => t === want).length, softField.help);
  check('AD-50 后端那句 help 在这一屏只出现**一次**（行内那份；底部再抄一遍就红）',
    helpHits === 1, helpHits);
  await page.waitForTimeout(250);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
  await page.fill('textarea.composer-input', 'AD 趟：收了但不执行的那条照样要发出去');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(900);
  const b3 = s3.submit.state.bodies[0] ?? {};
  check('AD-49b 改了它**真的进请求体**（accepted=true ⇒ 发；界面不许"反正不生效"就替用户不发）',
    b3.rag_top_k === 9, b3);
  await s3.ctx.close();

  /* ================= 场景 4：端点整个不存在（没重启的后端） ================= */
  const s4 = await newPage({ options: null, submit: {} });
  page = s4.page;
  await openPanel(page);
  check('AD-26 读不到 /config/agent-options ⇒ 面板整块降级并**明说按后端默认值提交**',
    (await page.locator('.rcp--degraded').count()) === 1 &&
      (await page.evaluate(() => document.querySelector('.rcp')?.textContent ?? '')).includes('按后端默认值提交'));
  check('AD-27 降级那一屏没有假控件：一个输入框都不画（数 DOM 不是数文案）',
    (await page.locator('.rcp .ant-input-number').count()) === 0);
  await page.fill('textarea.composer-input', 'AD 趟：降级时只发任务文本');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1000);
  const b4 = s4.submit.state.bodies[0] ?? {};
  check('AD-28 降级的请求体**只有 task** —— 不发任何前端造的默认值（P-8 的判据本体）',
    JSON.stringify(bodyKeys(b4)) === JSON.stringify(['task']), bodyKeys(b4));
  await s4.ctx.close();

  /* ================= 场景 5：老 ack 静默丢键（P-1） ================= */
  const s5 = await newPage({ submit: { oldAck: true } });
  page = s5.page;
  await openPanel(page);
  await fieldInput(page, 'max_cost_cny').fill('0.42');
  await page.waitForTimeout(300);
  await page.fill('textarea.composer-input', 'AD 趟：后端没收下要说得出');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1600);
  /* ⚠️ 等 1.6 秒不是随手加的：这一条之后 SSE 会走到终态、终态会整包补拉 trace，
     而补拉就是 ``replaceEvents`` —— 只写进日志缓冲区的那条告警会被**盖掉**。
     判据量的是运行条下面那条**常驻**提示（`record.configEchoIssue`），
     它不住在缓冲区里，所以不会被下一次对账抹干净 —— 这正是它存在的全部理由。 */
  const issueText = await page.evaluate(
    () => document.querySelector('.cfg-issue')?.textContent ?? '',
  );
  check('AD-29 回执里没有 run_config ⇒ 运行条下方出现常驻提示，点名发出过的那一项（预算）',
    issueText.includes('后端没有回报运行配置') && issueText.includes(stubLabel('max_cost_cny')),
    issueText.slice(0, 60));
  /* ---------- 提示行的名字必须是响应给的那份 ----------
     界面原来在这里用**自己那张** ``CONFIG_LABELS``（"最大成本预算"），而后端 label 是
     "最大成本预算"、桩里是"成本预算上限（桩词）"：本轮把这张表删了，改读 ``fields[]``。
     所以量的是"有没有出现桩里那个独有的说法"，而不是"有没有出现中文名字"。 */
  check('AD-29a 提示行用的字段名 = 响应里的 label（界面那张自带表已经删干净，不是换了个写法）',
    issueText.includes(stubLabel('max_cost_cny')) && !issueText.includes('最大成本预算'),
    issueText.slice(0, 90));
  check('AD-29b 提示的语义是"未确认"而不是"任务失败"（data-code 说得清是哪一种）',
    await page.evaluate(() => document.querySelector('.cfg-issue')?.getAttribute('data-code') === 'RUN_CONFIG_UNACKNOWLEDGED'));
  check('AD-29c 整包补拉之后提示仍在（日志会被 replaceEvents 盖掉，这一条不会）',
    (await page.locator('.cfg-issue').count()) === 1);
  /* 这一栏**只在"回执对不上"那一档进 DOM**，全站其它趟都碰不到它 ⇒ 亮色顺手量一次。 */
  assertIssueContrast('AD-43 亮色·回执提示', await measureIssueContrast(page));
  await s5.ctx.close();

  /* ================= 场景 5c：同一栏在暗色下再量一次（AD-42） ================= */
  const s5c = await newPage({ scheme: 'dark', submit: { oldAck: true } });
  page = s5c.page;
  await openPanel(page);
  await fieldInput(page, 'max_cost_cny').fill('0.42');
  await page.waitForTimeout(300);
  await page.fill('textarea.composer-input', 'AD 趟：暗色下这条提示也得读得出');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1600);
  assertIssueContrast('AD-42 暗色·回执提示', await measureIssueContrast(page));
  await s5c.ctx.close();

  /* ================= 场景 5b：收了，但用的是**钳过之后**的值 ================= */
  const s5b = await newPage({ submit: { clampIterations: true } });
  page = s5b.page;
  await openPanel(page);
  await fieldInput(page, 'max_iterations').fill('8');
  await page.waitForTimeout(300);
  await page.fill('textarea.composer-input', 'AD 趟：后端钳过就得说钳到几');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1200);
  const clampText = await page.evaluate(() => document.querySelector('.cfg-issue')?.textContent ?? '');
  check('AD-29d 回执把 8 钳成 4 ⇒ 界面报的是**服务端实际用的那个数**，不是自己发出去的 8（读回执不读本地）',
    clampText.includes('发出的是 8') && clampText.includes('服务端实际用的是 4'),
    clampText.slice(0, 80));
  check('AD-29e 这一档的 data-code 是 MISMATCH（与"整个没回报"分开说，两种坑的补救不一样）',
    await page.evaluate(() => document.querySelector('.cfg-issue')?.getAttribute('data-code') === 'RUN_CONFIG_MISMATCH'));
  await s5b.ctx.close();

  /* ================= 场景 6：422 原样落屏（U-8） ================= */
  const s6 = await newPage({ submit: { always422: true } });
  page = s6.page;
  await openPanel(page);
  await fieldInput(page, 'max_cost_cny').fill('200');
  await page.waitForTimeout(300);
  await page.fill('textarea.composer-input', 'AD 趟：422 的原文要在正看着的这一屏');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1100);
  const errLine = await page.evaluate(() =>
    [...document.querySelectorAll('.log-msg')].map((el) => el.textContent ?? '').join('\n'),
  );
  check('AD-30 422 的 HTTP 码、后端的 code、request_id 与**服务端原话**四样都进了实时日志',
    errLine.includes('HTTP 422') && errLine.includes('invalid_request') &&
      errLine.includes('req-ad-422') && errLine.includes('less than or equal to 1000'),
    errLine.slice(0, 120));
  check('AD-31 那一行是 error 级（`.log-row--error`，不是被折叠成一条 info，也不许只在 toast 里闪一下）',
    await page.evaluate(() =>
      [...document.querySelectorAll('.log-row--error .log-msg')].some((el) =>
        (el.textContent ?? '').includes('req-ad-422'),
      ),
    ));
  check('AD-32 失败之后页签停在「实时日志」（错误落在眼前，不是隔壁）',
    await page.evaluate(() =>
      document.querySelector('.ant-tabs-tab-active')?.textContent?.includes('日志') ?? false));
  await s6.ctx.close();

  /* ================= 场景 7：390 走抽屉，不横向溢出 ================= */
  const s7 = await newPage({ viewport: { width: 390, height: 844 } });
  page = s7.page;
  await page.locator('button.cp-icon').click();
  await page.waitForSelector('.rcp', { state: 'visible' });
  await page.waitForTimeout(500);
  check('AD-33 390 挂的是 Drawer，Modal 那条路整条不在 DOM 里（两套容器不许同时在场）',
    (await page.locator('.rcp-drawer').count()) === 1 && (await page.locator('.ant-modal').count()) === 0);
  check('AD-34 390 打开面板后文档零横向溢出（180px 导航 + 白卡片那一档在 390 上会压回上下堆，这是这一趟新增的唯一理由）',
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, vw: window.innerWidth })));
  await s7.ctx.close();

  /* ================= 场景 8：深色下面板小字的对比度（在**它自己那块底色**上量） ========== */
  /* 深色这一档**换成 future 那份桩**（原来是 base）：为的是 ``.rcp-warn`` 那一行
     （accepted=true / enforced=false 的行内警告，自带 --warning-soft 底色）在深色里
     进得来 DOM —— base 那档八条声明全是 enforced=true，那一行永远不渲染，
     于是它成了"新写的文字从没被量过"的那一类。future 是 base 的超集，
     原来那七类照样量得到。 */
  const s8 = await newPage({ scheme: 'dark', options: variants.future });
  page = s8.page;
  await openPanel(page);
  /* 两个页签都要点：`.rcp-tool-*` 在高级、`.rcp-model-*` 在模型，而 AntD 的页签
     **首次激活才挂载** —— 少点一个，那一族的类就是空数组，量不到东西不等于通过。 */
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(400);
  await page.locator('.sc-nav-item', { hasText: '高级' }).click();
  await page.waitForTimeout(400);
  /* ⚠️ 这一档还要把**候选下拉打开**再量：``.ms-opt-name`` / ``.ms-opt-sub`` 是 2026-09-27
     第二趟新写的两行候选，而那层弹层挂在 body 上、底色是 AntD 的 ``colorBgElevated``
     —— 不是 ``--bg-surface``。"往上层找第一层不透明底"这套量法对它同样成立，
     但**必须先让它出现在 DOM 里**，否则就是"新写的字从没在任何底色上量过"（下面 AD-35b
     那条前件拦的正是这个：数组里点了名而 DOM 里没有 ⇒ 红，不放过）。
     ⚠️ 打开下拉要点得动那一格 —— 停在「高级」时模型那格是 ``hidden``，
     hidden 里的 input 存在但**点不动**（Playwright 判不可见 ⇒ 死等 30 秒中断整趟），
     所以这里量完高级的类之后再点回「模型」。 */
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(400);
  await page.locator('.sc-card .model-settings-input input').first().click();
  await page.waitForTimeout(500);
  /* 小字的类清单（只写**一份**，下面那条前件复用同一个数组 —— 两份清单就有
     "改了判据忘了改前件"的那天，本轮之前这里正是抄了两遍）。
     面板正文、标签、默认读数、工具名，「后端暂不支持」那一栏的三类
     （标题下的中文 label、等宽 key、原因原话），**行内那句"没有执行机制"**
     （``.rcp-warn``，自带 warning 底色），2026-09-27 界面优化那一趟加的四类
     （底部读数、左导航项、档位 Tag、生效来源），再加第二趟那一轮新写的三类
     （候选弹层两行 + 「应用到本次运行」旁边那句）。
     ⚠️ ``.sc-nav-item`` 顶掉了原来的「去设置」link 按钮：它是这一屏**唯一一处**
     同一语义出现在两种底色上的文字（选中项压在 --primary-soft 上、未选中压在
     Modal 的 --bg-app 上），下面那个循环会把三个节点各量一次 ——
     正是"同一语义要在每种行底色上各量一次"那条口径。
     后两类是同一族：key 那行是**唯一一处**把机器名摆给业务用户看的地方，
     它读不读得出来必须量；警告那行是**唯一一处**带底色的行内小字。 */
  const AA_CLASSES = [
    '.rcp-help',
    '.rcp-label',
    '.rcp-default',
    '.rcp-tool-name',
    '.rcp-unsupported-name',
    '.rcp-unsupported-key',
    '.rcp-unsupported-help',
    '.rcp-warn',
    /* 2026-09-29：``.rcp-footer-hint``（那句"已改 N 项 / 没有改动"）随底栏定形删掉了，
       换成这三类本轮**新写**的字：恢复默认配置那颗文字链、段标题、角色绑定那行小字。
       ⚠️ 文字链是 12px --text-2、角色绑定是 12px --text-3 —— 这一屏现在唯一两处
          12px 灰字，压在卡片底上，必须各自量一次（"同一语义要在每种行底色上各量一次"）。 */
    '.rcp-restore',
    '.ms-section-title',
    '.ms-rolebind',
    /* 原来这一类是「去设置」那颗 link 按钮（模型区那枚）。那颗按钮随"模型设置内嵌进
       设置中心"一起没了 ⇒ 换成左导航项：它是这一屏**唯一一处同一语义出现在两种底色上**
       的文字（选中项压在 --primary-soft 上、未选中压在 Modal 的 --bg-app 上），
       下面那个循环会把三个节点各量一次，正是"同一语义要在每种行底色上各量一次"那条口径。 */
    '.sc-nav-item',
    /* 2026-09-29：``.rcp-model-tier`` 与 ``.rcp-model-src`` 随那张五行角色表一起删了
       ⇒ 从清单里去掉（留着会让下面"各类都真量到了"那条永远红）。
       ``.ms-key-note``（那句"…不落盘"）也随独立说明行删了。 */
    /* ↓ 2026-09-27 第二趟新增的两类：候选弹层那两行（压在 colorBgElevated 上），
       都是**恒在场**的字（下拉那句要先打开 ⇒ 见上面）。 */
    '.ms-opt-name',
    '.ms-opt-sub',
  ];
  const measured = await page.evaluate((classes) => {
    const lin = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const parse = (s) => (s || '').match(/[\d.]+/g)?.map(Number).slice(0, 4) ?? [255, 255, 255];
    /* 底色要**往上一层层找**第一个不透明的祖先：面板里 .rcp-tool 有自己的底色、
       「后端暂不支持」那块是 sunken，直接取 parentElement 会量到透明色然后蒙对。
       （同一口径在 AA 趟 :5448 已经踩过一次。） */
    const bgOf = (el) => {
      let node = el;
      while (node) {
        const rgb = parse(getComputedStyle(node).backgroundColor);
        const a = rgb.length > 3 ? rgb[3] : 1;
        if (rgb.length >= 3 && a > 0.99) return rgb.slice(0, 3);
        node = node.parentElement;
      }
      return [255, 255, 255];
    };
    const cr = (fg, bg) => {
      const l1 = lum(fg);
      const l2 = lum(bg);
      return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
    };
    const out = [];
    for (const sel of classes) {
      for (const el of document.querySelectorAll(sel)) {
        out.push({
          sel,
          text: (el.textContent ?? '').trim().slice(0, 16),
          ratio: cr(parse(getComputedStyle(el).color).slice(0, 3), bgOf(el)),
          fs: getComputedStyle(el).fontSize,
        });
      }
    }
    return out;
  }, AA_CLASSES);
  const low = measured.filter((m) => m.ratio < 4.5);
  check(`AD-35 深色下面板 ${AA_CLASSES.length} 类小字在**各自实际所在底色**上 ≥4.5:1`,
    measured.length >= AA_CLASSES.length && low.length === 0, low);
  check(`AD-35b 前件：${AA_CLASSES.length} 类选择器都真量到了（某类为空就是选择器写错、页签没挂载，不是通过）`,
    AA_CLASSES.every((sel) => measured.some((m) => m.sel === sel)),
    [...new Set(measured.map((m) => m.sel))]);
  await s8.ctx.close();

  /* ================= 场景 9：界面优化那一趟新增的三件东西 =================
     底部那栏（改动读数 + 撤回）、「去设置」那颗跨组件入口、以及高危 Tooltip 的来源。
     为什么单开一档而不是塞进 s1：s1 已经用完它的请求体断言（AD-15…17、40），
     这一档要的是**干净的一份草稿** —— 撤回之后提交必须只剩 task，
     跟 s1 那"碰过三项"的草稿共用一个 context 就会互相污染。 */
  const s9 = await newPage({ options: variants.base });
  page = s9.page;
  await openPanel(page);
  await page.locator('.sc-nav-item', { hasText: '高级' }).click();
  await page.waitForTimeout(400);
  /* 2026-09-29：底栏那句"已改 N 项 / 没有改动"的读数换成**一枚 dirty 小圆点**，
     两颗按钮合成一颗「恢复默认配置」（文字链）。判据跟着换读点 ——
     但**三件事一件没松**：① 未改时是灰的；② 改一项 ⇒ 变橙、且"改了"这件事
     读屏与鼠标都拿得到；③ 点恢复 ⇒ 状态真的回去（不是只改文案）。
     ⚠️ 圆点的两态**不只判颜色**：还判 ``data-dirty`` 与 aria-label ——
        只判背景色的话，一个"永远是橙的点"能过 ② 却过不了 ①，反过来也一样；
        而真正的坑是"颜色对了、状态没跟着走"（那正是这一条要钉的形状）。 */
  const dotState = () =>
    page.evaluate(() => {
      const d = document.querySelector('.rcp-dirty');
      if (!d) return null;
      const cs = getComputedStyle(d);
      const r = d.getBoundingClientRect();
      const foot = document.querySelector('.rcp-footer')?.getBoundingClientRect();
      return {
        data: d.getAttribute('data-dirty'),
        bg: cs.backgroundColor,
        radius: cs.borderRadius,
        round: Math.abs(r.width - r.height) <= 1 && r.width >= 8 && r.width <= 14,
        label: d.getAttribute('aria-label') ?? '',
        /* 位置：底栏**右侧**（离右边缘比离左边缘近）—— 口径钉的是"底栏右侧"。 */
        onRight: Boolean(foot && foot.right - r.right < r.left - foot.left),
      };
    });
  const restoreDisabled = () =>
    page.evaluate(() => document.querySelector('.rcp-restore')?.disabled ?? null);
  const toolChecked = () =>
    page.evaluate(() =>
      [...document.querySelectorAll('.rcp-tool input[type=checkbox]')].map((c) => c.checked),
    );
  const dotTip = async () => {
    await page.locator('.rcp-dirty').hover();
    await page.waitForTimeout(500);
    return page.evaluate(() => {
      const trig = document.querySelector('.rcp-dirty');
      const id = trig?.getAttribute('aria-describedby') ?? '';
      return (id ? document.getElementById(id) : null)?.textContent ?? '';
    });
  };

  const gray = await dotState();
  check('AD-51 前件：底部那栏在场，且没改过东西时小圆点是**灰的**、提示说"未修改，按后端默认值运行"、恢复是 disabled（读数与控件同一份来源）',
    (await page.locator('.rcp-footer').count()) === 1 &&
      gray?.data === '0' &&
      gray.label === '未修改，按后端默认值运行' &&
      gray.round === true &&
      gray.onRight === true &&
      (await restoreDisabled()) === true,
    gray);
  check('AD-51b 灰态那颗的悬停提示就是那句话（搬进 tooltip 不等于搬丢了）',
    (await dotTip()).includes('未修改，按后端默认值运行'), await dotTip());

  await page.locator('.rcp-tool', { hasText: 'code_exec' }).locator('input[type=checkbox]').click();
  await page.waitForTimeout(350);
  const orange = await dotState();
  check('AD-52 取消一个工具勾选 ⇒ 小圆点变**橙**（data-dirty=1、底色真的换了、提示改口）、恢复亮起来（改动看得见，不是等提交才发现）',
    orange?.data === '1' &&
      orange.bg !== gray?.bg &&
      orange.label === '已修改，应用后生效' &&
      (await restoreDisabled()) === false &&
      (await toolChecked()).filter((c) => !c).length === 1,
    { gray, orange, disabled: await restoreDisabled(), checked: await toolChecked() });
  check('AD-52b 橙态那颗的悬停提示跟着改口（两态各一句完整的话，不是只换颜色）',
    (await dotTip()).includes('已修改，应用后生效'), await dotTip());

  await page.locator('.rcp-restore').click();
  await page.waitForTimeout(400);
  const back = await dotState();
  check('AD-53 点「恢复默认配置」⇒ 六条勾选全回来、小圆点回灰、恢复重新 disabled（撤的是状态，不是只改文案）',
    (await toolChecked()).every(Boolean) &&
      back?.data === '0' &&
      back.bg === gray?.bg &&
      (await restoreDisabled()) === true,
    { checked: await toolChecked(), back, gray: gray?.bg });

  /* ---------- 高危 Tooltip 的那句实现描述，来源必须是响应 ----------
     前端原来自己写"高危工具：默认需要人工确认（HITL）才执行"，本轮把"沙箱 / Python /
     超时上限"这一段接回 ``GET /tools`` 的 ``description``。桩里那句写的是**最多 20 秒**，
     而后端真值是 30 秒 ⇒ 浮层里出现 20 就证明它读的是响应；出现 30 就是前端又抄了一份
     （与 AD-37c 同形的反向哨兵：那个"30"是后端真值，写在这里当反例，会随实现过期）。
     顺序有讲究：这一段必须在"去设置"之前 —— 那颗按钮会把弹层关掉（AD-55b 判的就是这件事），
     而提交任务也会让弹层收起（AD-09/10 那条老坑），所以**提交放在最后**。 */
  const stubExec = toolsBody.items.find((t) => t.danger_level === 'high') ?? {};
  const stubDesc = String(stubExec.description ?? '');
  await page.locator('.rcp-tool-danger').first().hover();
  await page.waitForTimeout(500);
  /* 读点**收窄到这颗触发器自己那枚浮层**：AntD 把 ``aria-describedby`` 挂在触发元素上，
     顺着 id 取才准。第一版这里写成"把所有 ``.ant-tooltip`` 拼起来"，于是把 composer
     那颗悬停提示（现在叫"设置（基础 / 模型 / 高级）"，改名之前叫"运行配置（预设 / 迭代 / …）"）
     也读了进来 —— 判据照旧绿，但它已经不再只检查它声称检查的东西。 */
  const tipText = await page.evaluate(() => {
    const trig = document.querySelector('.rcp-tool-danger');
    const id = trig?.getAttribute('aria-describedby') ?? '';
    return (id ? document.getElementById(id) : null)?.textContent ?? '';
  });
  check('AD-56 前件：顺着 aria-describedby 真取到了这颗触发器的浮层（取不到=交互或读点写错，不是"没有 30 秒"所以通过）',
    tipText.length > 0, tipText.slice(0, 40));
  check('AD-56b 高危 Tooltip 里有**桩那句 description**（沙箱/Python/超时那一段来自响应）',
    Boolean(stubDesc) && tipText.includes(stubDesc.slice(0, 18)), { stub: stubDesc.slice(0, 28), tip: tipText.slice(0, 90) });
  check('AD-56c 反向哨兵：Tooltip 里不许出现后端真值那个"30 秒"（出现=前端又抄了一份实现描述）',
    !/最多 30 秒/.test(tipText) && /20 秒/.test(tipText), tipText.slice(0, 90));

  /* ---------- 「模型」这一项：内嵌的就是齿轮那份组件，不是第二份 UI ----------
     原来这里是一颗「去设置」跨组件按钮 + 一条 window 事件，判的是"点了能把顶栏那层打开、
     自己这层收起"。现在模型设置**内嵌在这一项里** ⇒ 那颗按钮与事件桥一起删了，判据换成
     三条更要紧的：① 内嵌那份真在场；② 这一屏**只有一份** ``.model-settings``，
     且它的 id 带 ``sc-`` 前缀（两份同 id 挂在一起 = 探针与读屏软件量的不是它声称的那一份，
     ``getElementById`` 只会拿到文档里第一个）；③ 旧的入口与它的事件桥确实没了
     —— 两个入口做同一件事，必然有一天只改一份（R-03 那轮"两份清单"的同形病）。 */
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(700);
  check('AD-55 前件：「模型」项里内嵌的那份模型设置进了 DOM（.sc-card 里恰好一份 .model-settings）',
    (await page.locator('.sc-card .model-settings').count()) === 1 &&
      (await page.locator('.model-settings').count()) === 1,
    await page.evaluate(() => document.querySelectorAll('.model-settings').length));
  const keyIds = await page.evaluate(() =>
    [...document.querySelectorAll('[id*="model-key"], [id^="model-large"], [id^="model-small"]')].map((e) => e.id),
  );
  check('AD-55b 内嵌那份的 id 全部带 sc- 前缀、且没有一份未加前缀的混进来（重复 id 会让判据量错那一份）',
    keyIds.length > 0 &&
      keyIds.every((id) => id.startsWith('sc-')) &&
      new Set(keyIds).size === keyIds.length,
    keyIds);
  check('AD-55c 旧的那颗「去设置」与它的 window 事件桥都不在界面上了（留着就是两个入口做同一件事）',
    (await page.locator('button.rcp-model-goto').count()) === 0);
  /* Esc 关得掉这一层：Modal 的焦点圈与关闭手势是真在，不是"打开就回不去"。
     ⚠️ 关掉之后 ``.rcp`` 仍留在 DOM 里（AntD 不卸载），所以判的是**可见性**不是存在性 ——
     与 AD-55b 上面那句注释同一口径，别把"在不在"当"开没开"。 */
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  check('AD-55d Esc 关得掉这一层（可见性变 false，而不是元素被卸载 —— 后者是另一件事）',
    (await page.locator('.rcp').first().isVisible()) === false);

  /* 这一条才是 AD-53 的"为什么"：Context 里的 ``reset()`` 从来没有 UI 调用过，
     所以"撤回"以前只是导出的一个函数。如果它清的不是**同一份**状态，
     上一条（界面）会照样绿、这一条（请求体）才红 —— 两头都判才不可能恒真。 */
  await page.fill('textarea.composer-input', 'AD 趟：撤回之后提交，只剩任务文本');
  await closeSettingsLayer(page);
  await page.locator('button.cp-submit').click();
  await page.waitForTimeout(1000);
  const b9 = s9.submit.state.bodies[0] ?? {};
  check('AD-54 撤回之后提交 ⇒ 请求体里只有 task（没留下被撤回那一项的 enabled_tools）',
    JSON.stringify(bodyKeys(b9)) === JSON.stringify(['task']) && !('enabled_tools' in b9),
    bodyKeys(b9));

  /* ---------- 快捷示例（2026-09-27 从这一屏搬到任务输入框下方） ----------
     这三颗在探针里**一条判据都没读过**（改之前 grep ``cfg-ex`` / 示例 = 0 命中）⇒
     "搬丢了"这件事不会有人发现，正是这一轮最容易留下的那种洞。所以搬完补两条：
     ① 位置：在 textarea **下面**那一排、仍在 .composer 里，而设置那一屏里已经没有它们；
     ② 动作：三颗各点一次，每次都把某条正文填进输入框 + 焦点回到那格 + 三条互不相同，
        并且**不发请求**（"发出去"那一步归用户，这条纪律从搬到之前没变）。
     ⚠️ 判据里不写示例正文的字面量：那是前端常量，写死就等于探针读自己 ——
        改成"三条互不相同且都非空"，实现里换文案它照样成立。
     ⚠️ 点之前必须先 Esc 把这一层收掉：Modal 有遮罩，Playwright 的 click 会做命中测试，
        隔着遮罩点芯片会 TimeoutError（而 ``fill`` 不做命中测试 ⇒ 上面 AD-53/54 那两下没受影响）。 */
  await closeSettingsLayer(page);
  const exGeo = await page.evaluate(() => {
    const box = document.querySelector('.composer-examples');
    const ta = document.querySelector('textarea.composer-input');
    const btns = box ? [...box.querySelectorAll('button.cfg-ex')] : [];
    return {
      n: btns.length,
      belowTextarea: Boolean(box && ta) && box.getBoundingClientRect().top >= ta.getBoundingClientRect().bottom - 1,
      inComposer: Boolean(box?.closest('.composer')),
      stillInPanel: Boolean(document.querySelector('.rcp .cfg-ex')),
    };
  });
  check('AD-63 三颗快捷示例现在住在任务输入框下方那一排（在 .composer 里、textarea 之下），设置那一屏里已经没有它们',
    exGeo.n === 3 && exGeo.belowTextarea && exGeo.inComposer && !exGeo.stillInPanel, exGeo);

  const beforeExLen = await page.evaluate(
    () => (document.querySelector('textarea.composer-input')?.value ?? '').length,
  );
  const fills = [];
  for (let i = 0; i < 3; i += 1) {
    await page.locator('.composer-examples button.cfg-ex').nth(i).click();
    await page.waitForTimeout(220);
    fills.push(
      await page.evaluate(() => ({
        len: (document.querySelector('textarea.composer-input')?.value ?? '').length,
        focused: String(document.activeElement?.className ?? '').includes('composer-input'),
      })),
    );
  }
  const bodiesAfterEx = s9.submit.state.bodies.length;
  check('AD-64 三颗各点一次 ⇒ 每次都填进一条**互不相同**的正文、焦点回到输入框、且一次请求都没多发',
    fills.every((f) => f.len > 8 && f.focused) &&
      new Set(fills.map((f) => f.len)).size === 3 &&
      fills[0].len !== beforeExLen &&
      bodiesAfterEx === 1,
    { fills, bodiesAfterEx });

  await s9.ctx.close();

  /* ================= 场景 10：「模型」Tab 一屏可见 + 档位改名 + 跨组件的 dirty 连线 =================
     2026-09-29：原来这一档量的是"角色来源不唯一 ⇒ 逐行 Tag 回来"。
     那张五行角色表整块删掉了（后端只认两个档位、没有 per-role 语义 ⇒ 那五行永远不可能
     不一致），"混档"这个形状**在界面上不再有对应物** —— 判据跟着删，
     不为保留判据而保留冗余 UI（这正是"改了判据忘了改界面"的反面）。
     换成三条这一轮真正要钉的：① 一屏可见；② 档位改名；③ 改档位 ⇒ 底栏小圆点变橙。 */
  const s10 = await newPage({ options: variants.base });
  await openPanel(s10.page);
  await s10.page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await s10.page.waitForTimeout(550);
  const tabShape = await s10.page.evaluate(() => {
    const body = document.querySelector('.sc-body');
    const pane = document.querySelector('#sc-panel-model');
    return {
      /* "一屏可见"读成几何：这一格的滚动容器**根本不需要滚**
         （scrollHeight ≤ clientHeight），而不是"滚一点点也能看完"。 */
      overflow: body ? Math.max(0, body.scrollHeight - body.clientHeight) : -1,
      paneH: pane ? Math.round(pane.getBoundingClientRect().height) : 0,
      labels: [...document.querySelectorAll('.sc-card .model-settings-label')].map((n) =>
        (n.textContent ?? '').trim(),
      ),
    };
  });
  check('AD-74 「模型」那一格一屏可见（滚动容器纵向溢出 0 —— 不用滚就能读完，验收第 7 条）',
    tabShape.overflow === 0 && tabShape.paneH > 0, tabShape);
  check('AD-74b 两个档位改叫「决策模式 / 执行模式」，旧名「强档 / 快档」整屏 0 命中',
    tabShape.labels.length === 2 &&
      tabShape.labels[0].startsWith('决策模式') &&
      tabShape.labels[1].startsWith('执行模式') &&
      !/强档|快档/.test(
        await s10.page.evaluate(() => document.querySelector('.rcp')?.textContent ?? ''),
      ),
    tabShape.labels);

  /* 跨组件那条新连线：下拉框的状态住在 ``ModelSettings`` 里，
     小圆点住在 ``RunConfigPanel`` 的底栏里。断了的表现是"改了档位而圆点不动" ——
     肉眼几乎看不出来（两个控件离得远，且都不报错），只能靠这条钉。 */
  const dotInS10 = () =>
    s10.page.evaluate(
      () => document.querySelector('.rcp-dirty')?.getAttribute('data-dirty') ?? null,
    );
  const before10 = await dotInS10();
  await s10.page.locator('.sc-card .model-settings-input input').first().fill('glm-4.6');
  await s10.page.waitForTimeout(400);
  const after10 = await dotInS10();
  check('AD-75 改「决策模式」那个下拉框 ⇒ 底栏小圆点跟着变橙（草稿真的报到了那枚点上）',
    before10 === '0' && after10 === '1', { before10, after10 });

  await s10.page.locator('.rcp-restore').click();
  await s10.page.waitForTimeout(600);
  const restoredVal = await s10.page
    .locator('.sc-card .model-settings-input input')
    .first()
    .inputValue();
  check('AD-75b 点恢复 ⇒ 小圆点回灰**且**下拉框回到服务端那份值（不是只把点改灰）',
    (await dotInS10()) === '0' && restoredVal !== 'glm-4.6',
    { dot: await dotInS10(), restoredVal });
  await s10.ctx.close();

  check('AD-36 这一趟所有场景都没有 pageerror', errors.length === 0, errors.slice(0, 3));
}

/* ================= AE：模型设置面板收 Key（U-1…U-7）+ 模型下拉标识 =================
   这一趟判的四件事，每件都对着一条"看起来正常但会骗人"的形状：

   ① **屏幕上到底留不留得下那串值**（补充约束 1）：输入 → blur → 再聚焦，
      ``input.value`` 必须是真空串，而且不许自动回填。
      ⚠️ 这条必须与 AE-2b（打字时框里**确实**有值）成对读 —— 只判"空"的话，
      一个从头就填不进去的输入框也能把它喂绿。
   ② **那句超时到底是谁说的**（补充约束 2）：桩里 ``timeout_s=4.5``，后端真值是 3.0。
      界面印 4.5 ⇒ 读的是响应；印 3 ⇒ 前端写死了（与 AD-56b 同形的反向哨兵）。
   ③ **值只走 POST body**（U-1/U-3 的边界）：URL 必须是常量、不含 query、不含那串值，
      而且**明文只能出现在请求体这一处**。
   ④ **网关档不画输入框**（U-5）：那一档"能填、会发、什么都不改变"，
      所以整块控件必须缺席，只点名。这一条与"非网关那档必须有框"成对读。

   外加补充约束 4 的出口（⑤那颗）：下拉标识加在本面板那两行真正能改模型的地方；
   AE-11/12/13 判的就是这条链 ——
   切完之后「运行配置」那一屏的当前模型读数必须跟着变（靠 invalidate，不靠 remount：
   全站 ``staleTime=30s``，不 invalidate 就停在旧的那份）。
   2026-09-29：「角色模型映射」那五行表换成了一行「角色绑定」小字 ⇒
   AE-11b 改成判"那一行是纯文本、能改模型的入口只有两个档位"，
   AE-11/12 前半段的读点也跟着从 ``.rcp-model-id`` 换成那两个档位输入框的 value。 */
async function passModelKey(browser) {
  console.log('\n== AE 面板收 Key：失焦真空串 / 只走 body / 原话落屏 / 网关档不画框 / 下拉切换两边同步 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), 'light');
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  const state = createModelOverrideMock(modelsBodyWithCatalog);
  /** 两个 Key 端点的每一次请求：URL 与解析出来的请求体（判"值只在 body"就靠它）。 */
  const keyCalls = [];
  /** ``GET /config/agent-options`` 被拉了几次 —— AE-13 的第一半（成对读的那半）。 */
  let optionsHits = 0;
  /* agent-options 跟着**同一份覆盖状态**走，与后端 api/routes/config.py:252-256 同形。
     桩不跟着动的话，"改完之后那一屏的模型名也换了"这条判据根本没有对手。 */
  const liveOptions = () => {
    const o = JSON.parse(JSON.stringify(agentOptionsBody));
    const ov = state.body().override;
    for (const row of o.models.roles) {
      row.model = row.tier === 'large' ? ov.model_large : ov.model_small;
      row.source = ov.source;
    }
    return o;
  };

  await installMocks(page);
  await page.route('**/api/config/agent-options', (r) => {
    optionsHits += 1;
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveOptions()) });
  });
  await page.route('**/api/models', (r) => r.fulfill(state.get()));
  /* ⚠️ 换模型那条**也必须接**：不接的话它会经 vite 代理打到本机 8001 上那个真后端，
     于是 AE-12 判的是"真后端收了没"（本机没配智谱 Key ⇒ 422），而桩里的 override 纹丝不动
     ⇒ AE-12b/12c 一起红，红得像 invalidate 没生效。第一版就在这里摔的。 */
  await page.route('**/api/models/override', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill(state.post(route.request().postDataJSON()));
    return route.fulfill(state.del());
  });
  // 先注册长的那条：两条 glob 各自精确到 /key 与 /key/validate，不会互吞
  await page.route('**/api/models/key/validate', (r) => {
    const payload = r.request().postDataJSON();
    keyCalls.push({ kind: 'validate', url: r.request().url(), body: payload });
    return r.fulfill(state.validateKey(payload));
  });
  await page.route('**/api/models/key', (r) => {
    const payload = r.request().postDataJSON();
    keyCalls.push({ kind: 'apply', url: r.request().url(), body: payload });
    return r.fulfill(state.postKey(payload));
  });
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);

  const gear = page.locator('button[aria-label="模型设置"]');
  const isOpen = async () => Boolean(await page.locator('.model-settings').isVisible().catch(() => false));
  const openPanel = async () => {
    if (await isOpen()) return;
    await gear.click();
    await page.waitForSelector('.model-settings', { timeout: 5000 });
    await page.waitForTimeout(500);
  };
  const closePanel = async () => {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    if (await isOpen()) {
      await page.mouse.click(700, 890);
      await page.waitForTimeout(300);
    }
  };
  const keyInput = page.locator('#model-key-input');
  const keyValue = () => keyInput.inputValue();
  const blurKey = () => page.evaluate(() => document.getElementById('model-key-input')?.blur());
  /* 两个汉字的按钮名一律走 :func:`buttonRx`（模块级那条注释解释了为什么不能传字面串）。 */
  /** 点一颗 Key 栏的按钮，返回**它实际发出了几次请求**。
   *  返回值是这条链上唯一能证伪"点了没反应"的量：文案对不对是第二件事，
   *  第一下压根没发请求的话，界面显示的永远是上一次的读数（本轮就是这样被抓到的）。 */
  /** 2026-09-29：三行供应商状态清单删掉了，那串「名称（状态） · 来源：…」的读点
   *  **只剩「供应商」那一格本身**（Select 显示的就是选中项的 label，串里同样带
   *  状态与来路）。所以这里的"那一行"改读那一格的显示值 ——
   *  字串形状没变，读点换了一个，AE-7b/8/8e/9/10c 那几条一字不用改。
   *  ⚠️ 走 ``.ant-select-selection-item`` 而不是 ``.ms-key-select`` 的 textContent：
   *     后者会把隐藏的 placeholder 与其它 span 一起带进来。 */
  const pickedLine = () =>
    page.evaluate(
      () =>
        document.querySelector('.ms-key-select .ant-select-selection-item')?.textContent ?? '',
    );
  /** 「校验」2026-09-29 搬进了输入框右端（图标按钮），不再住在 ``.ms-key-actions`` 里。 */
  const probeBtn = page.locator('.ms-key-probe');
  const clickBtn = async (text) => {
    const before = keyCalls.length;
    if (text === '校验') await probeBtn.click();
    else await page.locator('.ms-key-actions button').filter({ hasText: buttonRx(text) }).first().click();
    await page.waitForTimeout(500);
    return keyCalls.length - before;
  };
  const resultText = () =>
    page.evaluate(() => document.querySelector('.ms-key-result')?.textContent ?? '');
  const pickProvider = async (display) => {
    await page.locator('.ms-key-select').click();
    await page.waitForTimeout(400);
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option', {
        hasText: display,
      })
      .first()
      .click();
    await page.waitForTimeout(450);
  };

  await openPanel();

  /* ---------- ① 框在不在、标题与那颗 ⓘ 说的是不是 U-4 那句 ----------
     2026-09-27 第二趟：标题从一整句缩成「API Key 配置」四个字，那三条约束搬进 ⓘ。
     ⚠️ 所以这一条**不能只判标题**（判"标题里有重启回落"会变成永远红），也不能只判
     "浮层里有没有那句话" —— 浮层是 hover 才挂的，读点写错就是恒真。
     两条一起判：标题在场（说明结论摆在明面）+ 顺着 ``aria-describedby`` 真取到浮层
     且里面是原话（说明来路没丢）。与 AD-56 那对高危 Tooltip 同一口径。 */
  /* 2026-09-29：标题并进 §15 的 ``.ms-section-title``（与 AD-71 同一处改名，
     这里不改就读到空串 ⇒ 这条判据恒红，而报错里看不出是选择器旧了）。 */
  const title = await page.evaluate(
    () => document.querySelector('.ms-keybox .ms-section-title')?.textContent?.trim() ?? '',
  );
  await page.locator('.ms-key-info').hover();
  await page.waitForTimeout(500);
  const titleTip = await page.evaluate(() => {
    const trig = document.querySelector('.ms-key-info');
    const id = trig?.getAttribute('aria-describedby') ?? '';
    return (id ? document.getElementById(id) : null)?.textContent ?? '';
  });
  check('AE-1 Key 那一栏在模型设置面板里（不是藏在别处），标题是「API Key 配置」+ 那三条原话在 ⓘ 的浮层里',
    title.startsWith('API Key 配置') &&
      (await keyInput.count()) === 1 &&
      titleTip.includes('本进程') &&
      titleTip.includes('重启回落') &&
      titleTip.includes('不回显'),
    { title, tip: titleTip.slice(0, 60), inputs: await keyInput.count() });
  check('AE-1b 眼睛图标在（Input.Password 本体）且 Base URL 那格是只读的',
    await page.evaluate(() => ({
      eye: document.querySelectorAll('.ms-keybox .ant-input-password-icon').length,
      readonly: document.querySelector('.ms-key-baseurl')?.getAttribute('readonly'),
      editable: document.querySelector('.ms-key-baseurl')?.getAttribute('contenteditable'),
    })).then((r) => r.eye === 1 && r.readonly === '' && r.editable !== 'true'),
    await page.evaluate(() => ({
      eye: document.querySelectorAll('.ms-keybox .ant-input-password-icon').length,
      ro: document.querySelector('.ms-key-baseurl')?.outerHTML.slice(0, 60),
    })));
  check('AE-1c 默认落在**当前强模型那一家**（不是列表第一家那么随机），且该行在状态清单里被标出',
    (await pickedLine()).includes('DeepSeek'), await pickedLine());

  /* ---------- ② 补充约束 1：blur 真清空、且不回填 ---------- */
  const STUB_KEY = 'sk-AEOK-zhipu-abcdef123456';
  await keyInput.click();
  await keyInput.fill(STUB_KEY);
  const typed = await keyValue();
  check('AE-2b 前件：打字时框里**确实**有那串值（没有这一条，AE-2 的"空"是恒真）',
    typed === STUB_KEY, typed);
  await blurKey();
  await page.waitForTimeout(300);
  const afterBlur = await keyValue().catch(() => null);
  await keyInput.click();
  await page.waitForTimeout(300);
  const afterFocus = await keyValue();
  check('AE-2 输入 → blur → 再聚焦：value 是**真空串**且没有自动回填（录屏安全）',
    afterBlur === '' && afterFocus === '', { afterBlur, afterFocus });
  check('AE-3 blur 之后如实说明"框空了但那一把还在内存里待提交"（不说谎也不含糊）',
    await page.evaluate(() => {
      const n = document.querySelector('.ms-key-hold');
      return Boolean(n && n.textContent.includes('输入框已经清空') && n.textContent.includes('待提交'));
    }));
  /* 产物留在这儿更合适：`.ms-key-hold` 已在，但校验结果、下拉箭头那些要到后面几步才在场
     —— 截图统一放在各自那一步"信息最全的一刻"，见 AE-4d 之后与 AE-10 之后。 */

  /* ---------- ③ 校验：三分支的**桩原话**落屏 ----------
     每一次点击都记"实际发出了几次请求"：文案对不对是第二件事，
     **第一下就得有反应**是这件事。本轮就是被这条抓出问题的 ——
     "已暂存"那行原来夹在输入框与按钮中间，blur 时插进来把按钮顶下去一整行，
     mouseup 落在空处，用户要点第二下才有反应（现象叫"点了校验没反应"）。 */
  const d1 = await clickBtn('校验');
  const okLine = await resultText();
  check('AE-4 校验通过那行说的是**桩给的**模型条数（7 个）与桩那句 detail',
    okLine.includes('鉴权通过，端点报出 7 个模型'), okLine);
  check('AE-4b 那句"超时上限"读的是响应的 timeout_s=4.5 —— 印出 3 就是前端写死（后端真值 3.0）',
    okLine.includes('4.5') && !/超时上限 3\b/.test(okLine), okLine);
  check('AE-4c 端点与上面那格一致时**不再重复一遍** base_url（同屏不许两份同数）',
    !/https?:\/\//.test(okLine), okLine);
  check('AE-4d 焦点还在输入框时点第一下**就**发出请求（按钮不许因为 blur 引起的布局跳动而吃掉这一击）',
    d1 === 1, d1);
  /* 验收④那张：Key 输入框（此刻是空的，正是拍下来该长的样子）+「校验」+ 结果那句
     + 绿/黄状态点，全在一帧里。⚠️ 这是**探针驱动之后**的状态 ⇒ 文件名带 AE 前缀，
     不复用出厂态那批截图的名字（同一文件盖两次会分不清是哪一态）。 */
  await page.locator('.ms-keybox').screenshot({ path: path.join(OUT, 'AE-keybox-validated.png') });
  /* 整屏那一帧要趁**还没翻网关档**的时候拍：只有这一刻是"两行下拉箭头 + Key 输入框 +
     校验按钮 + 绿/黄状态点 + 校验结果"同时在场（验收④要的就是这一张）。 */
  await page.locator('.model-settings').screenshot({ path: path.join(OUT, 'AE-panel-with-key.png') });

  await keyInput.fill('sk-AEBAD-zhipu-000000000000');
  const d2 = await clickBtn('校验');
  const badLine = await resultText();
  check('AE-5 失败那行是**供应商原话**（桩里的 1002 Wrong API key），不是界面编的"Key 无效"',
    badLine.includes('Wrong API key') && badLine.includes('1002') && d2 === 1, badLine);
  check('AE-5b 失败态走 --danger 那一档（类名换了，不是只改文案）',
    await page.evaluate(() => document.querySelector('.ms-key-result')?.className ?? '').then((c) => c.includes('ms-key-result--bad')),
    await page.evaluate(() => document.querySelector('.ms-key-result')?.className ?? ''));

  await keyInput.fill('sk-AESLOW-zhipu-00000000');
  await clickBtn('校验');
  const slowLine = await resultText();
  check('AE-6 超时那一档给的是可行动的那句（检查网络或 base_url），并按响应的 4.5 秒说',
    slowLine.includes('校验超时') && slowLine.includes('base_url') && slowLine.includes('4.5'), slowLine);

  /* ---------- ④ 值只走 body ---------- */
  const urls = keyCalls.map((c) => c.url);
  check('AE-7 三趟校验的 URL 都是常量路径、没有 query、没有一次带上那串值',
    urls.length >= 3 && urls.every((u) => u.endsWith('/api/models/key/validate') && !u.includes('?') && !u.includes('sk-AE')),
    urls);
  check('AE-7b 校验没有把状态改走：一次 /models/key 都没发，那一行还写着环境变量',
    keyCalls.every((c) => c.kind === 'validate') && (await pickedLine()).includes('LLM_API_KEY'),
    { kinds: keyCalls.map((c) => c.kind), line: await pickedLine() });
  check('AE-7c 明文出现在且仅出现在请求体里（三趟校验的 body.api_key 都带着它，URL 一个都没）',
    keyCalls.every((c) => String(c.body.api_key ?? '').startsWith('sk-AE')) &&
      keyCalls.every((c) => !c.url.includes(String(c.body.api_key ?? 'sk-AE'))),
    keyCalls.map((c) => ({ url: c.url.slice(-24), has: String(c.body.api_key ?? '').slice(0, 6) })));

  /* ---------- ⑤ 应用 / 撤回：那一行的来源跟着变 ---------- */
  await keyInput.fill(STUB_KEY);
  await clickBtn('应用到本次运行');
  const appliedLine = await pickedLine();
  check('AE-8 应用之后那一行改口成"本次进程里填的"（key_source=runtime 真的落到了视图上）',
    appliedLine.includes('本次进程里填的') && appliedLine.includes('重启后回落到 LLM_API_KEY'),
    appliedLine);
  check('AE-8b 应用请求体里 provider 是选中的那一家，且带了明文（唯一允许的地方）',
    keyCalls.some((c) => c.kind === 'apply' && c.body.provider === 'deepseek' && c.body.api_key === STUB_KEY),
    keyCalls.filter((c) => c.kind === 'apply').map((c) => ({ provider: c.body.provider, len: String(c.body.api_key).length })));
  check('AE-8c 应用之后输入框被清干净（草稿不留着，免得下一次误发给别家）',
    (await keyValue()) === '' &&
      (await page.locator('.ms-key-hold').count()) === 0,
    await keyValue());

  const revokeBtn = page.locator('.ms-key-actions button').filter({ hasText: buttonRx('撤回') }).first();
  check('AE-8d 已填过的那家才给「撤回」按钮（没填过时不给一个按了没用的按钮）',
    (await revokeBtn.count()) === 1);
  await revokeBtn.click();
  await page.waitForTimeout(600);
  check('AE-8e 撤回之后那一行回到"环境变量 …"（空串 = 回落，不是"删掉这一家"）',
    (await pickedLine()).includes('环境变量 LLM_API_KEY'), await pickedLine());

  /* ---------- ⑥ 切供应商：状态跟着变 + 草稿必须丢掉 ---------- */
  await pickProvider('阿里云千问');
  /* 2026-09-29：占位符改成**一句固定话术**（"输入新 Key 仅本次运行生效，重启恢复环境变量"），
     不再按"这家配没配过 Key"分两种、也不再塞环境变量名 ⇒ 原来那半条"占位符跟着变成它自己的
     环境变量"的判据**失去对手**，删掉。环境变量名由「供应商」那一格负责（AE-9 前半条判的
     就是它），同一句话不在两个控件上各说一遍。 */
  check('AE-9 切到缺 Key 那家 ⇒ 那一格的话跟着变成它自己的名称与环境变量',
    (await pickedLine()).includes('阿里云千问') &&
      (await pickedLine()).includes('LLM_API_KEY_QWEN'),
    { line: await pickedLine() });
  await keyInput.fill('sk-AEOK-qwen-aaaaaaaaaaaa');
  await pickProvider('DeepSeek');
  check('AE-9b 换供应商 ⇒ 手上那把草稿被丢掉（校验按钮 disabled，不会把给千问的发给 DeepSeek）',
    await probeBtn.isDisabled(), await keyInput.inputValue());

  /* ---------- ⑦ 网关档（U-5）：不画输入框、只点名 ---------- */
  const beforeFlip = await keyInput.count();
  state.body().providers.find((p) => p.provider === 'deepseek').env_channel = true;
  state.body().providers.find((p) => p.provider === 'deepseek').key_env_var = 'LLM_API_KEY';
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await openPanel();
  check('AE-10 网关档：输入框整块**缺席**，只点名"这把不会被用到"与它跟着的那把（U-5）',
    (await keyInput.count()) === 0 &&
      (await page.locator('.ms-key-gateway').count()) === 1 &&
      (await page.evaluate(() => document.querySelector('.ms-key-gateway')?.textContent ?? '')).includes('不会被用到'),
    { inputs: await keyInput.count(), text: await page.evaluate(() => document.querySelector('.ms-key-gateway')?.textContent ?? '') });
  check('AE-10b 前件：翻桩之前这档**是有**输入框的（缺席不是"从来没画过"）',
    beforeFlip === 1, beforeFlip);
  check('AE-10c 网关档那句仍然说得出"跟着 .env 的 LLM_API_KEY"（旧版一句"已配置"两个意思，本轮修的就是它）',
    (await pickedLine()).includes('LLM_API_KEY'), await pickedLine());
  /* 网关档那一帧：这一档**没有**输入框，只有点名那句 —— 与上面那张对照着看。 */
  await page.locator('.ms-keybox').screenshot({ path: path.join(OUT, 'AE-keybox-gateway.png') });
  state.body().providers.find((p) => p.provider === 'deepseek').env_channel = false;

  /* ---------- ⑧ 下拉标识（补充约束 4 走了第 ⑤ 那颗出口）---------- */
  const caret = await page.evaluate(() => ({
    carets: document.querySelectorAll('.model-settings-row .ms-caret').length,
    combos: document.querySelectorAll('.model-settings-input input').length,
  }));
  check('AE-11 两行模型控件都带上了下拉箭头（标识加在**真能改模型**的那两处）',
    caret.carets === 2 && caret.combos === 2, caret);
  /* 整张面板那一帧（**网关档状态下**的：这一趟跑到这里 deepseek 已被翻成 env 通道，
     所以这张里没有 Key 输入框 —— 有输入框的那张是 AE-panel-with-key.png）。 */
  await page.locator('.model-settings').screenshot({ path: path.join(OUT, 'AE-panel-gateway.png') });

  /* ---------- ⑨ 切换模型 ⇒ 请求体 + 另一屏的读数 ---------- */
  await closePanel();
  await page.locator('button.cp-icon').click();
  await page.waitForSelector('.rcp', { state: 'visible' });
  await page.locator('.sc-nav-item', { hasText: '模型' }).click();
  await page.waitForTimeout(450);
  /* 2026-09-29：原来这条判的是「角色模型映射」那五行是 ``<code>`` 纯文本、没有第二处下拉。
     那五行整块删了（换成一行「角色绑定」小字）⇒ 判据跟着换读点，
     但**它要钉的那件事一件没变**：能改模型的入口在这一屏**只有那两个档位**，
     per-role 那条语义不存在，界面上也不许出现第二个能改模型的地方。
     ⚠️ 前半条判"那一行是纯文本"（里面不许有 select / input / button ——
        有就等于给一个后端不认的语义做了控件），后半条判"档位下拉恰好两个"。 */
  const modelRows = () =>
    page.evaluate(() =>
      [...document.querySelectorAll('.sc-card .model-settings-input input')].map((i) => i.value),
    );
  check('AE-11b 「角色绑定」那一行是纯文本，能改模型的控件**只有那两个档位**（出口⑤，per-role 那条语义不许有入口）',
    await page.evaluate(() => {
      const line = document.querySelector('.ms-rolebind');
      return (
        Boolean(line) &&
        line.querySelectorAll('select, input, button, .ant-select').length === 0 &&
        document.querySelectorAll('.rcp-model-id').length === 0 &&
        document.querySelectorAll('.sc-card .model-settings-input').length === 2
      );
    }),
    await page.evaluate(() => ({
      rolebindControls: document.querySelector('.ms-rolebind')?.querySelectorAll('select, input, button, .ant-select').length,
      oldRows: document.querySelectorAll('.rcp-model-id').length,
      tierCombos: document.querySelectorAll('.sc-card .model-settings-input').length,
    })));
  const beforeRows = await modelRows();
  const hitsBefore = optionsHits;
  /* 2026-09-27：这里不再去开顶栏那颗齿轮 —— 模型设置已经**内嵌在这一格里**，
     同一组件、同一份查询缓存，打在哪一份上都走同一条写路径。刻意选内嵌这一份来打字，
     判据才说得清"设置中心里那两行是真能改模型的"（而不是"还得回齿轮那里改"）。
     读点一律带 ``.sc-card`` 前缀：齿轮那份此刻是关着的，不加前缀也只剩一份，
     但"哪天它没关干净就量错对象"这种洞要提前堵（AE-11 那批量的是齿轮那份，跑在这段之前）。 */
  await page.locator('.sc-card .model-settings-input input').first().fill('glm-4.6');
  await page.waitForTimeout(300);
  await page
    .locator('.sc-card .model-settings-actions button')
    .filter({ hasText: buttonRx('应用') })
    .first()
    .click();
  await page.waitForTimeout(900);
  const overridePosts = (state.calls.post ?? []).slice(-1)[0] ?? {};
  check('AE-12 下拉/输入切到 glm-4.6 ⇒ 请求体里的 model_large 就是它（不是界面显示的那个）',
    overridePosts.model_large === 'glm-4.6', overridePosts);
  check('AE-12b 换完之后重新拉了一次 agent-options（invalidate 真发了；不 invalidate 就靠 30s 缓存停在旧名上）',
    optionsHits > hitsBefore, { before: hitsBefore, after: optionsHits });
  await page.waitForTimeout(500);
  check('AE-12c「设置」里「模型」那一格的当前模型跟着换成 glm-4.6（同屏两份同数里，两份必须同一份来源）',
    (await modelRows())[0] === 'glm-4.6' && beforeRows[0] !== 'glm-4.6',
    { before: beforeRows, after: await modelRows() });

  check('AE-13 这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

/* AE-dark：Key 那一栏里"做过某一步才进 DOM"的那五类小字，在**深色弹层底**上各量一次。
   为什么不并进 AE：AE 只跑亮色（行为判据要的是稳定），而这五类里有两类是**带底色**的块
   （``--warning-soft`` 的网关提示、结果那行），深色下那两个 soft 是 ``rgba(...,0.14)`` ——
   按旧那份"只认 alpha>0.99 的层"会跳过它、拿更外面的弹层底来算，永远把对比度**算高**。
   这里按 AD 趟那份写法把半透明层**合成**掉再算（同一课：跳过一层只会漏报，不会误报）。 */
async function passModelKeyDark(browser) {
  console.log('\n== AE-dark 面板收 Key 那五类小字在深色弹层底上的对比度 ==');
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    locale: 'zh-CN',
  });
  await ctx.addInitScript((s) => localStorage.setItem('trinity-console.theme', s), 'dark');
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const state = createModelOverrideMock(modelsBodyWithCatalog);
  await installMocks(page);
  await page.route('**/api/models', (r) => r.fulfill(state.get()));
  await page.route('**/api/models/key/validate', (r) => r.fulfill(state.validateKey(r.request().postDataJSON())));
  await page.route('**/api/models/key', (r) => r.fulfill(state.postKey(r.request().postDataJSON())));

  /* 先把默认那一家翻成网关档：这样第一次开面板就有 ``.ms-key-gateway`` 那块带底的提示。 */
  state.body().providers.find((p) => p.provider === 'deepseek').env_channel = true;
  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.locator('button[aria-label="模型设置"]').click();
  await page.waitForSelector('.ms-key-gateway', { timeout: 5000 });
  await page.waitForTimeout(400);

  const measure = () =>
    page.evaluate(() => {
      const lin = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
      const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
      const parse = (s) => (String(s).match(/[\d.]+/g) || []).map(Number).slice(0, 4);
      /** 把途经的半透明层**逐层合成**到一个不透明底上（深色弹层那两枚 soft 就是这个形状）。 */
      const stack = (el) => {
        const out = [];
        let n = el;
        while (n && out.length < 8) {
          const v = parse(getComputedStyle(n).backgroundColor || '');
          if (v.length >= 3) out.push(v[3] === undefined ? [v[0], v[1], v[2], 1] : v.slice(0, 4));
          n = n.parentElement;
        }
        let base = out.find((c) => c.length < 4 || c[3] > 0.99);
        if (!base) return null;
        let acc = base.slice(0, 3);
        for (let i = out.indexOf(base) - 1; i >= 0; i -= 1) {
          const c = out[i];
          const a = c[3] === undefined ? 1 : c[3];
          acc = acc.map((old, k) => c[k] * a + old * (1 - a));
        }
        return acc;
      };
      const cr = (fgStr, bg) => {
        const f = parse(fgStr);
        const a = f.length > 3 ? f[3] : 1;
        const fg = f.slice(0, 3).map((c, i) => c * a + bg[i] * (1 - a));
        const x = lum(fg);
        const y = lum(bg);
        return Number(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2));
      };
      const out = [];
      /* 2026-09-29：``.ms-key-list li`` 随状态清单一起删了 ⇒ 换成 ``.ms-embed-lock``
         那一行（向量模型读数，恒在场）。 */
      for (const sel of ['.ms-key-gateway', '.ms-key-label', '.model-settings-note']) {
        const el = document.querySelector(sel);
        if (!el) { out.push({ sel, cr: null }); continue; }
        const bg = stack(el);
        out.push({ sel, cr: bg ? cr(getComputedStyle(el).color, bg) : null, size: getComputedStyle(el).fontSize });
      }
      return out;
    });
  const gatewayRead = await measure();
  check('AE-dark-1 网关提示那块（warning-soft 底 + warning-fg 字）在深色弹层上 ≥4.5:1',
    gatewayRead.some((r) => r.sel === '.ms-key-gateway' && r.cr !== null && r.cr >= 4.5), gatewayRead);

  /* 翻回非网关档，把"输入 → blur → 校验通过 → 校验失败"这四类小字逐一造出来。 */
  state.body().providers.find((p) => p.provider === 'deepseek').env_channel = false;
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.locator('button[aria-label="模型设置"]').click();
  await page.waitForSelector('#model-key-input', { timeout: 5000 });
  await page.waitForTimeout(400);
  await page.locator('#model-key-input').fill('sk-AEOK-zhipu-abcdef123456');
  await page.evaluate(() => document.getElementById('model-key-input')?.blur());
  await page.waitForTimeout(300);
  await page.locator('.ms-key-probe').click();
  await page.waitForTimeout(600);
  const okRead = await measure();
  const okLineCr = await page.evaluate(() => {
    const el = document.querySelector('.ms-key-result--ok');
    if (!el) return null;
    const lin = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const f = (String(getComputedStyle(el).color).match(/[\d.]+/g) || []).map(Number);
    const a = f.length > 3 ? f[3] : 1;
    /* 结果那行**没有自带底色** ⇒ 底就是弹层那块（深色下是柔和深灰，不是 --bg-surface）。 */
    let n = el;
    let bg = null;
    while (n && !bg) {
      const v = (String(getComputedStyle(n).backgroundColor).match(/[\d.]+/g) || []).map(Number);
      if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) bg = v.slice(0, 3);
      n = n.parentElement;
    }
    if (!bg) return null;
    const fg = f.slice(0, 3).map((c, i) => c * a + bg[i] * (1 - a));
    const x = lum(fg);
    const y = lum(bg);
    return Number(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2));
  });
  check('AE-dark-2 「已暂存待提交」那行与「校验通过」那行在深色弹层上 ≥4.5:1',
    okRead.some((r) => r.sel === '.ms-key-label' && r.cr !== null && r.cr >= 4.5) &&
      okLineCr !== null && okLineCr >= 4.5,
    { label: okRead.find((r) => r.sel === '.ms-key-label'), okLineCr });
  /* 深色那一帧（验收④：深色面板要有呼吸感，且上面那些读数在深色下同一套话术）。 */
  await page.locator('.ms-keybox').screenshot({ path: path.join(OUT, 'AE-keybox-dark.png') });

  await page.locator('#model-key-input').fill('sk-AEBAD-zhipu-000000000');
  await page.locator('.ms-key-probe').click();
  await page.waitForTimeout(600);
  const badCr = await page.evaluate(() => {
    const el = document.querySelector('.ms-key-result--bad');
    if (!el) return null;
    const lin = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const f = (String(getComputedStyle(el).color).match(/[\d.]+/g) || []).map(Number);
    let n = el;
    let bg = null;
    while (n && !bg) {
      const v = (String(getComputedStyle(n).backgroundColor).match(/[\d.]+/g) || []).map(Number);
      if (v.length >= 3 && (v.length < 4 || v[3] > 0.99)) bg = v.slice(0, 3);
      n = n.parentElement;
    }
    if (!bg) return null;
    const a = f.length > 3 ? f[3] : 1;
    const fg = f.slice(0, 3).map((c, i) => c * a + bg[i] * (1 - a));
    const x = lum(fg);
    const y = lum(bg);
    return Number(((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2));
  });
  check('AE-dark-3 「校验没通过」那行（danger-fg）在深色弹层上 ≥4.5:1',
    badCr !== null && badCr >= 4.5, badCr);
  /* 2026-09-29：``list``（三行状态清单）删了 ⇒ 换成 ``probe``（校验图标按钮，恒在场
     只在这一趟的非网关档）。"读不到不等于通过"这条口径没变，只是换了读点。 */
  check('AE-dark-4 前件：这四类读点在深色这一趟都真进 DOM 了（读不到不等于通过）',
    await page.evaluate(() => ({
      gateway: document.querySelectorAll('.ms-key-gateway').length,
      label: document.querySelectorAll('.ms-key-label').length,
      hold: document.querySelectorAll('.ms-key-hold').length,
      probe: document.querySelectorAll('.ms-key-probe').length,
      bad: document.querySelectorAll('.ms-key-result--bad').length,
    })).then((r) => r.label >= 2 && r.probe === 1 && r.bad === 1),
    await page.evaluate(() => ({
      gateway: document.querySelectorAll('.ms-key-gateway').length,
      label: document.querySelectorAll('.ms-key-label').length,
      probe: document.querySelectorAll('.ms-key-probe').length,
      bad: document.querySelectorAll('.ms-key-result--bad').length,
    })));
  check('AE-dark-5 深色这一趟没有 pageerror', errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

/* ============================ AF 逐段揭示（打字机） ============================
 *
 * 这一趟测的是「任务与日志页产品化」那一轮的第三条：答案**逐段**出现。
 *
 * 为什么走前端而不是后端真流式（三条结构性的账，报告里逐条带 file:line）：
 *   ① `api/queue.py` 的 worker 是**线程池里同步**跑的，每 publish 一次都要
 *      `call_soon_threadsafe` 穿回事件循环；
 *   ② 订阅队列 maxsize = 256，溢出是**丢事件**（打 WARNING）—— 逐 token 必然溢；
 *   ③ 最终答案出自 Reviewer 的 **JSON 模式**结构化输出
 *      （`response_format={"type":"json_object"}` + 校验失败重投），
 *      原始增量落下来是拼不上的 JSON 碎片，不是答案文本。
 * ⇒ 按这一轮明确允许的降级做：**后端一次性返回完整答案，前端把全文逐段揭示**。
 *
 * ⚠️ 这组判据两头都失效得起来，所以两头都钉：
 *   - 演过头：历史任务（不是本次看着跑的）也逐字敲 ⇒ 屏幕在演"正在生成"，而答案早就在库里。
 *     这一头由 V 趟②最后那条「历史任务不重播打字机」钉。
 *   - 演不出来：`skip` 被写成恒真（或 rAF 根本没跑）⇒ 用户看不到"结果在长出来"，
 *     而界面看起来完全正常。这一头由下面 AF-3 的"真的出现过中间态"钉住。
 */
const AF_ANSWER = [
  '# 整机功耗估算',
  '',
  '结论：**约 6,120 W**（1024 路 × 单路 5.977 W = 6,120.4 W）。',
  '',
  '- 单路拆分：摄像头 4.2 W + PoE 线路损耗 0.9 W + 交换机分摊 0.877 W',
  '- 留 20% 余量 ⇒ 上电总容量按 7,344 W 规划',
  '- 依据编号：IEEE 802.3at（Type 2），单口上限 30 W',
  '',
  '```python',
  'per_port = 4.2 + 0.9 + 0.877',
  'total_w = 1024 * per_port  # 6120.4',
  '```',
].join('\n');

/** 三帧节点事件 + 一帧 done：够让阶段文案走一遍"思考 → 执行 → 复核"，
 *  也把任务推到终态（终态之后详情接口才回答案，见下面的状态机桩）。 */
function afFrames() {
  const f = [];
  const push = (event, seq, payload) =>
    f.push(`event: ${event}\ndata: ${JSON.stringify({ seq, ts: new Date().toISOString(), ...payload })}\n\n`);
  push('snapshot', 1, { status: 'running', progress: null });
  push('node', 2, { node: 'planner', update: { plan: ['拆三步'] }, status: 'running' });
  push('node', 3, { node: 'executor', update: { ok: true }, status: 'running' });
  push('node', 4, { node: 'reviewer', update: { review_result: true }, status: 'running' });
  push('done', 5, { status: 'done' });
  return f.join('');
}

async function passAnswerReveal(browser, reduceMotion, label) {
  console.log(`\n== AF 逐段揭示 · ${label} ==`);
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    locale: 'zh-CN',
    reducedMotion: reduceMotion ? 'reduce' : 'no-preference',
    // AF-6 要读剪贴板；授不授都写明，读不到时那条判据会标出来而不是假装过
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  await ctx.addInitScript(() => localStorage.setItem('trinity-console.theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await installMocks(page);
  /* 有状态的详情桩（与 L 趟同一形状）：**这一条的流被请求过**之后详情才回终态 + 带全文。
     没有这层状态机，"答案正在长出来"那一帧根本不存在 —— 接口一上来就给全文的话，
     揭示动画在页面上跑完了也没人看见，AF-3 就成了恒真。 */
  const streamed = new Set();
  const idOf = (u) => decodeURIComponent((u.match(/tasks\/([^/?#]+)/) || [])[1] || '');
  await page.route('**/api/tasks/*', (r) => {
    const u = r.request().url();
    const id = idOf(u);
    if (u.includes('/trace')) {
      return r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: id, total: 0, items: [] }),
      });
    }
    return r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        streamed.has(id)
          ? { ...detail, task_id: id, status: 'done', final_answer: AF_ANSWER, duration_ms: 4200 }
          : { ...detail, task_id: id, status: 'running', final_answer: null, duration_ms: null },
      ),
    });
  });
  await page.route('**/sse/tasks/*/*', async (r) => {
    const id = idOf(r.request().url());
    streamed.add(id);
    /* 延 700ms 再给帧：AF-1/2 要读的是"还没有任何节点交卷"那一档的通用那句，
     立刻应答的话 250ms 时任务已经终态、思考行早被答案顶掉了（第一版就是这么红的）。 */
    await new Promise((res) => setTimeout(res, 700));
    return r.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
      body: afFrames(),
    });
  });
  // 每次提交给一个新 id：AF-8 要的是"换一条新的，账也是新的"
  let acks = 0;
  await page.route('**/api/tasks', (r) => {
    const id = `task-AF-${(acks += 1)}`;
    return r.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: id,
        status: 'queued',
        stream_url: `/tasks/${id}/stream`,
        poll_url: `/tasks/${id}`,
        cancel_url: `/tasks/${id}/cancel`,
        submitted_at: new Date().toISOString(),
        estimated_cost_cny: 0.0042,
        warnings: null,
      }),
    });
  });

  const answerLen = () =>
    page.evaluate(() => (document.querySelector('.answer')?.textContent || '').trim().length);

  await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('.composer-input').fill('1024 路摄像头整机功耗怎么估算？给出算式与结果');
  await closeSettingsLayer(page);
  await page.locator('.cp-submit').click();

  /* ---- AF-1/2：跑动中先有思考态，且它没在演结果 ---- */
  await page.waitForTimeout(250);
  const th = await page.evaluate(readThinking);
  check(`AF-${label} 1 提交后这一屏挂思考态（三点 + 一句阶段文案）`,
    th.present === true && /^Agent 正在/.test(th.text), th.text);
  check(`AF-${label} 2 跑动中不演答案：没有 .answer、也没有消耗指标`,
    th.answer === false && th.metrics === 0, th);
  if (reduceMotion) {
    /* 减动档的三点**必须在思考那一屏就停住** —— 判据要读的是"动画确实存在时它是 none"，
     等答案出来再读，思考行已经收掉，那条就变成在比 `!d || ...` 的前半截（恒真）。
     读数与 B 趟那六条同源：`animation-name` + `animation-duration` 两个都看，
     只读一个会被默认值骗过去（全站那条口径见 README）。 */
    check(`AF-${label} 2b 减动档下那三点当场就停了（name=none，duration 也被清过）`,
      th.dotAnim === 'none' && th.dotPeers.every((n) => n === 'none') && parseFloat(th.dotDuration) < 0.01,
      { dotAnim: th.dotAnim, dotPeers: th.dotPeers, dotDuration: th.dotDuration });
  }

  /* ---- 两张验收截图（他这一轮点名要的）：思考态 + 流式结果态 ----
     口径：截的是 `.pane` 整块（页签栏 + 面板），不是只裁那个小盒子 ——
     要看得出"此刻人在哪一屏"，光有那行字没有页签上下文会读成一张别的界面。 */
  fs.mkdirSync(OUT, { recursive: true });
  await page.locator('.pane').screenshot({ path: path.join(OUT, `af-${label}-thinking.png`) });

  /* ---- AF-3/4：终态之后答案**真的出现过中间态**，最后落到整段 ----
     采样口径：`.answer` 一出现就每 90ms 读一次长度，读 24 次（≈2.2 秒）。
     `RevealedAnswer` 是 rAF + 50ms 节流、30 帧见底 ⇒ 全程约 1.5 秒，这个窗口取得到。 */
  await page.waitForSelector('.answer', { timeout: 15000 });
  const samples = [];
  let clickedMid = false;
  for (let i = 0; i < 24; i += 1) {
    const n = await answerLen();
    samples.push(n);
    /* 复制那一击打在**动画还在跑的时候**（第一个半截读数上）：播完之后才点，
       "复制的是全文"这句话顺带成立，抓不到"复制跟着屏幕上那半截走"这个失效。 */
    if (!clickedMid && n > 0 && n < AF_ANSWER.length * 0.8) {
      clickedMid = true;
      await page
        .evaluate(() => {
          const btn = document.querySelector('.sec-label--answer .copy-btn');
          if (btn) btn.click();
          return Boolean(btn);
        })
        .catch(() => false);
      /* 流式结果态那张：正卡在动画中间的时候截（播完再截就和普通结果页没区别了）。
         只截非减动那一档 —— 减动档压根没有中间态。 */
      if (!reduceMotion) {
        await page.locator('.result-wrap').screenshot({
          path: path.join(OUT, 'af-revealing.png'),
        });
      }
    }
    await page.waitForTimeout(90);
  }
  const full = await answerLen();
  const partials = samples.filter((n) => n > 0 && n < full);
  const grew = samples.some((n, i) => i > 0 && n > samples[i - 1]);
  if (reduceMotion) {
    check(`AF-${label} 3 减动档不放动画：一次都没出现半截答案（prefers-reduced-motion 的硬要求）`,
      partials.length === 0 && samples.every((n) => n === full), { 前六个采样: samples.slice(0, 6), full });
  } else {
    check(`AF-${label} 3 真的出现过半截答案（揭示动画在跑，不是"恒 skip"）`,
      partials.length >= 2 && grew, { 前十个采样: samples.slice(0, 10), full });
    /* 播完了没有：**末尾四拍长度不再变** + 答案里那句"最靠后"的原文在场。
       ⚠️ 不许拿 `full === AF_ANSWER.length` 判 —— 屏上是 markdown **渲染后**的文本，
       `#` / `**` / 围栏那三行反引号都不成字，实测渲染体 235 字 vs 源串 260 字。
       上一版写的是"只许变小不许变大"配一个 0.75 的比例，那是我在猜长度：
       真正的口径是"最后一行有没有吐完"，所以直接查最末那句。 */
    const tail = await page.evaluate(() =>
      (document.querySelector('.answer')?.textContent || '').includes('total_w = 1024 * per_port'),
    );
    check(`AF-${label} 4 播完之后停在整段（末尾四拍不再增长 + 最末那句代码在场）`,
      samples.slice(-4).every((n) => n === full) && full === Math.max(...samples) && tail === true,
      { 末尾四拍: samples.slice(-4), full, 最末那句在场: tail });
    /* 中间态不许把**已经给得出**的东西一起藏掉：消耗、复制按钮都在场。
       （答案在长，但"这条任务花了多少钱"从终态那一刻就是定数，没有理由等动画。） */
    const during = await page.evaluate(() => ({
      metrics: document.querySelectorAll('.metric-grid .metric').length,
      copy: document.querySelectorAll('.copy-btn').length,
      thinking: document.querySelectorAll('.thinking').length,
    }));
    check(`AF-${label} 5 播完之后指标三格在场、思考行收掉（整屏不许一起等动画）`,
      during.metrics === 3 && during.copy >= 2 && during.thinking === 0, during);
    await page.locator('.result-wrap').screenshot({ path: path.join(OUT, 'af-result-full.png') });
    /* 复制走的是**全文**：`<CopyButton text={result.finalAnswer}>` 传的是完整串，
       揭示只喂给 AnswerView 一份前缀 ⇒ 中途那一次点击也必须拿到全文。
       前件是"那一击确实打在半截的时候"（clickedMid），少了它这条会退化成恒真。
       读回来看的是**逐字等于原文**（含 `**` 与 ```python 那些 markdown 记号）——
       渲染后的正文里没有这些字，所以剪贴板里带着它们，就证明拿的是源串而不是屏幕上那截。 */
    check(`AF-${label} 6a 前件：复制那一击打在动画中间（不这么做下面那条会恒真）`,
      clickedMid === true, clickedMid);
    const clip = await page
      .evaluate(async () => {
        await new Promise((r) => setTimeout(r, 250)); // 等 useCopy 那一次 await 落回
        try {
          return { text: await navigator.clipboard.readText() };
        } catch (e) {
          return { err: `剪贴板读不了：${String(e)}` };
        }
      })
      .catch((e) => ({ err: `剪贴板读不了：${String(e)}` }));
    /* 剪贴板里必须是**整篇源串**（含 `**` 与 ```python 那些 markdown 记号）：
       渲染后的正文里没有这些字（实测渲染体 235 字 vs 源串 260 字），所以只要它们在场，
       就证明复制拿的是源串、不是屏幕上那半截。
       ⚠️ 换行要归一：Windows 的剪贴板把 `\n` 写成 `\r\n`（实测 260 → 271，多的 11 个
       正好是源串里的 11 个换行），逐字比之前先换回 `\n`，否则这条永远差 11 个字符。 */
    const clipOk =
      clip.err === undefined &&
      typeof clip.text === 'string' &&
      clip.text.replace(/\r\n/g, '\n') === AF_ANSWER;
    check(`AF-${label} 6 剪贴板里是整篇原文（不跟着屏幕上那半截走；读不到就明写未验证）`,
      clip.err === undefined ? clipOk : true,
      clip.err
        ? `未验证 —— ${clip.err}`
        : { 换行归一后等于原文: clipOk, 剪贴板长度: clip.text.length, 源串长度: AF_ANSWER.length });
    /* ---- AF-7：切走再回来不许重播（第二次看的人没有理由再等一遍） ---- */
    await page.getByRole('tab', { name: /实时日志/ }).click();
    await page.waitForTimeout(600);
    await page.getByRole('tab', { name: '运行结果' }).click();
    await page.waitForTimeout(150);
    const again = await answerLen();
    check(`AF-${label} 7 切页签再回来：整段就在屏幕上（没有重播一遍打字机）`,
      again >= full * 0.98, { 回来后: again, 全文: full });
    /* ---- AF-8：换一个任务，"播过了"那本账不许带过去 ---- */
    await page.locator('.composer-input').fill('换个问法：再核一遍上一步的算法');
    await closeSettingsLayer(page);
    await page.locator('.cp-submit').click();
    /* 1.1 秒是掐着算的：桩把首帧延到 700ms，之后还要一次 pullDetail 的往返 ⇒
       答案大约在 0.9~1.0 秒落地，动画本身 1.5 秒 ⇒ 这一拍正落在动画中间。
       早了答案还没来（读到 0，看不出增长），晚了播完了（也看不出增长）——
       两头都会让这条变成"恒假"或"恒真"，所以写明这里的算术。 */
    await page.waitForTimeout(1100);
    const second = [];
    for (let i = 0; i < 8; i += 1) {
      second.push(await answerLen());
      await page.waitForTimeout(90);
    }
    check('AF-normal 8 再提交一条：账是新的（这一条也走了一遍逐段揭示，没被上一条的账跳过）',
      second.some((n, i) => i > 0 && n > second[i - 1]), second);
  }

  check(`AF-${label} 这一趟没有 pageerror`, errors.length === 0, errors.slice(0, 3));
  await ctx.close();
}

async function run() {
  /* ONLY=C 只跑某几趟（逗号分隔趟号），改一处 CSS 时不必等全量九趟。
     全量验收仍然要跑不带 ONLY 的整支。 */
  const only = process.env.ONLY ? new Set(process.env.ONLY.split(',')) : null;
  const all = [
    ['A', () => passReplay(browser, 'light', 'light')],
    ['A', () => passReplay(browser, 'dark', 'dark')],
    ['B', () => passRunning(browser, 'light', 'light')],
    ['B', () => passRunning(browser, 'dark', 'dark')],
    ['C', () => passVirtual(browser)],
    ['D', () => passJargon(browser)],
    ['E', () => passCitations(browser)],
    ['F', () => passExpandCost(browser)],
    ['G', () => passModelReadout(browser, 'light', 'light')],
    ['G', () => passModelReadout(browser, 'dark', 'dark')],
    ['H', () => passResultCenter(browser, 'light', 'light')],
    ['H', () => passResultCenter(browser, 'dark', 'dark')],
    ['I', () => passResultPolish(browser, 'light', 'light')],
    ['I', () => passResultPolish(browser, 'dark', 'dark')],
    ['J', () => passNarrowOverflow(browser)],
    ['J', () => passCollapsedFocus(browser)],
    ['K', () => passTraceSelection(browser)],
    ['L', () => passListSelectFinish(browser)],
    ['M', () => passRenderCount(browser)],
    ['N', () => passLateResponse(browser)],
    ['O', () => passStreamDrop(browser)],
    ['P', () => passCancelOutcome(browser)],
    ['Q', () => passHiddenProbe(browser)],
    ['R', () => passComposerSettings(browser)],
    ['S', () => passCsvDownload(browser)],
    ['T', () => passRunbarAnnounce(browser)],
    ['U', () => passAnswerMemo(browser)],
    ['V', () => passTickerAndMount(browser)],
    ['W', () => passUrlRestore(browser)],
    ['X', () => passTableScrollX(browser)],
    ['Y', () => passSurfaceHead(browser)],
    ['AA', () => passCostBreakdown(browser)],
    ['AB', () => passEvalErrorStates(browser)],
    ['Z', () => passKnowledgeUpload(browser)],
    ['AC', () => passModelSwitch(browser, 'light', 'light')],
    ['AC', () => passModelSwitch(browser, 'dark', 'dark')],
    ['AD', () => passRunConfigPanel(browser)],
    ['AE', () => passModelKey(browser)],
    ['AE', () => passModelKeyDark(browser)],
    ['AF', () => passAnswerReveal(browser, false, 'normal')],
    ['AF', () => passAnswerReveal(browser, true, 'reduce')],
  ];
  const browser = await chromium.launch({ executablePath: CHROME });
  /* 开页数 / 导航数：**量出来的**，不是手数的。README 里那条 removeChild flake 的复现率
     （1/22、0/2）分母就是这个数 —— 以前写在注释里靠手数，加一趟就漂移一次而没人回头改，
     于是"复现率"这个口径慢慢变成一个说不出来源的数。现在每趟跑完自己报。
     口径：开页 = 新建一个 page（新 context 里的那一枚也算）；导航 = 一次 goto/reload。 */
  const navStats = { pages: 0, goes: 0 };
  const origNewContext = browser.newContext.bind(browser);
  browser.newContext = async (...ca) => {
    const ctx = await origNewContext(...ca);
    const origNewPage = ctx.newPage.bind(ctx);
    ctx.newPage = async (...pa) => {
      const p = await origNewPage(...pa);
      navStats.pages += 1;
      for (const m of ['goto', 'reload']) {
        const orig = p[m].bind(p);
        p[m] = (...a) => {
          navStats.goes += 1;
          return orig(...a);
        };
      }
      return p;
    };
    return ctx;
  };
  try {
    for (const [tag, fn] of all) if (!only || only.has(tag)) await fn();
  } finally {
    await browser.close();
  }
  console.log(
    `\nrunning probe: ${pass} 通过 / ${pass + fails.length} 断言` +
      ` · 本次开页 ${navStats.pages}（导航 ${navStats.goes}）`,
  );
  if (fails.length) {
    console.error('\n失败：\n' + fails.map((f) => `  ✗ ${f}`).join('\n'));
    process.exitCode = 1;
  }
}

run().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
