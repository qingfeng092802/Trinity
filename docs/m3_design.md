# M3 设计 · 消融评测与组件可插拔（v3 落地版）

> 本文档把《通用 RAG Agent 性能优化与评测系统 v3》**按本机实测环境**落到 Trinity 上。
> 只覆盖 M3，不扩大到 MCP / 前端重设计。
> 前置阅读：`docs/m2_rag.md`（RAG 全链路 + T01 Spike 结论）、`docs/m2_design.md §7`（纪律）。

> [!WARNING]
> **2026-09-21 收敛变更（精简版）—— 本文件以下四处已失效，以代码为准：**
> 1. **显著性检验整条删除**：`evaluation/stats.py`（McNemar / Wilcoxon / Holm-Bonferroni）已删除，
>    比对接论改为报「相对基线的绝对提升 Δ」与「相对提升百分比 rel_lift」
>    （见 `evaluation/ablation.py::PairedComparison`）。
> 2. **失败归因 F1..F5 → 只留 F1/F2**：`scripts/analyze_ablation_failures.py` 现在只报
>    「未召回」与「召回未居首」，F3/F4/F5 的判据与依赖函数已移除。
> 3. **矩阵 22 臂 → 5 臂**：见 `evaluation/dataset/matrix_m3.yaml`，Phase B 未跑。
> 4. **知识库格式 5 → 3**：`rag/parsers.py` / `api/constants.py` 白名单收敛到 `pdf / md / txt`，
>    docx / html 的解析链路与 `python-docx` 依赖已移除。

---

## 0. 结论先行

**做什么**：在已交付的 RAG 链路上补齐「组件可插拔 + 严格单变量消融 + 显著性检验」，
产出**真实测得**的质量/延迟/成本三轴报告。

**P0（必做，决定这个项目的成败）**

| # | 项 | 为什么是 P0 |
|---|---|---|
| P0-1 | **换掉 4.4KB 占位语料**，建 150 题 Golden Set + ≥50 篇文档语料 | 现有语料 top-1=top-3=100%（`m2_rag.md §5` 自认「区分度低」）。语料没有区分度，所有配置都满分，**消融无从谈起**。这是 v3 spec 完全没意识到的第一阻塞项。 |
| P0-2 | Phase A：检索侧消融（E1 嵌入 / E2a 融合 / E2b 分块 / E3 重排），**零 LLM 调用** | 纯函数指标 Recall@5 / MRR@5 / nDCG@5，不花一分钱、可断网跑、20 分钟出真实数字。先拿到一批能对外引用的硬结论。 |
| P0-3 | 直接「检索→生成」通路 + 防幻觉/拒答 Prompt + 引用校验 | 现状 **完全没有** 这条通路（见 §2 缺口表），E4/E6 全被它卡住。 |
| P0-4 | 生成侧四指标（**RAGAS 口径自实现**）+ 成本/延迟统计 + McNemar/Wilcoxon | 「能归因」的凭据。复用 `Usage` 与 `TraceStore.aggregate`，成本侧几乎白拿。 |

**P1**：E5 工具提示词三组（basic/guided/strict）、Streamlit 对比页、参数敏感性扫描。
**P2**：父子文档分块（需 schema 迁移）、ragas 库交叉校验、查询改写（HyDE）。

**一句话卖点仍成立**：v3 的核心竞争力是「证明每个组件值不值得加、代价多少」，
而 Trinity 已有 21.4K LOC 真实工程底座 + 379 测试，比 v3 从零写的可信度**更高**。

---

## 1. 与《v3 最终版》的分歧（逐条否决理由）

v3 spec 有 8 处与本机环境/现有工程冲突，不修就开工必翻车。

| # | v3 原文 | 实测环境 | 本方案改法 |
|---|---|---|---|
| 1 | 生成用 `Qwen2-7B-Instruct` 本地 | GPU 只有 **RTX 3050 Laptop / 4GB 显存** | 改 **DeepSeek API**（`.env` 已配真 key，`LLM_PROVIDER=deepseek`）。本地 7B 需 ≥14GB fp16，物理不可能；4GB 连 3B int4 都吃紧且质量塌陷，消融的绝对值失去意义。 |
| 2 | `pip install ... ragas trulens sentence-transformers FlagEmbedding` | **Smart App Control = On**；`ragas 0.4.3` 硬依赖 `scikit-network`(Cython .pyd) + `datasets>=4.0`(pyarrow) + `langchain`/`langchain-community`/`instructor` | **不装 ragas、不装 trulens**（见 D2）。`trulens` 与 ragas 0.4 双 LLM 栈冲突且年久失修，纯风险无收益。 |
| 3 | RAGAS 代码用 `from ragas.metrics import faithfulness` + `Dataset.from_dict` | 这是 **ragas 0.1 时代 API**，0.2+ 已改成 `SingleTurnSample` + `llm=` 注入 | 作废。无论自实现还是将来接 ragas，都不能照抄这段。 |
| 4 | 嵌入比 5 个模型（BGE-base/large/m3/Qwen2-Embedding/text2vec） | `langchain_env` 有 **torch 2.13.0+cpu 可用**（实测 matmul OK），但 sentence-transformers 依赖 sklearn；transformers 未装 | 砍到 **3 个可比臂**（D3）：bge-small-zh-v1.5(现有) / bge-base-zh-v1.5 / bge-m3 或 DashScope 向量 API。`Qwen2-Embedding` 需要新栈，边际收益低，P2 再说。 |
| 5 | `vector_store: chroma` 开发 / FAISS 压测 | M2 已拍板 **sqlite-vec 转正**（`m2_rag.md §6`） | 沿用 sqlite-vec。消融要的是「同一份索引换检索策略」，换向量库是无关变量，**必须钉死不动**。 |
| 6 | 量化成果表 P95 延迟 420ms→1200ms | 这是本地小模型量级；走 DeepSeek，端到端 P95 实际 **2–8 秒** | 报告拆两段口径：**检索侧延迟**（ms，本地，含重排）与**端到端延迟**（s，含生成）。混在一张表里会被一眼读出两套口径。 |
| 7 | 「CMRC2018 50 组对应 50 篇百科文档」 | `huggingface.co` 直连 **不通**（curl 000）；`raw.githubusercontent.com` 同样不通；`hf-mirror.com` **可用**：`hfl/cmrc2018` 三个 split 已实测直下成功（train 3,365,898B / val 1,136,115B / test 394,683B parquet，cc-by-sa-4.0，`resolve/main/data/*.parquet` 302→cas-bridge 200） | 走 hf-mirror 直下 parquet（D5）。但**实测否决了 spec 的两个隐含假设**：① 镜像里**没有不可回答题**，拒答 30 题仍需自己构造；② 每篇 passage 中位仅 453 字，**一篇文档 = 一个 chunk**，分块策略在这份语料上**根本不可消融**（见 §7 陷阱 13）。 |
| 8 | 「150 题 = 公开 50 + 自建 100」 | 自建 100 题需人工标注参考答案；且 CMRC passage 太短（中位 453 字）**撑不起分块消融** | 改 **双轨道：CMRC 100 + 自建长文档 50**（D6）。标注量减半且拒答用「留出段落」协议构造；自建那 50 题用**能源/电力规程语料**，形成相对通用 Web 背景的差异化资产，同时是 E2b 唯一的试验田。 |

> **命名冲突提醒**：`m1_prd.md:447` 与 `m2_prd.md:246` 都把 **M3 = MCP 工具协议**。
> 本方案占用 M3 编号，MCP 顺延为 M4。要么认了这个改法，要么把本项目叫 `M2.5`。

---

## 2. 缺口盘点（精确到 file:line）

### 已有、直接复用（这是复用 Trinity 的全部理由）

| 能力 | 位置 | 复用方式 |
|---|---|---|
| 混合检索 + **权重可注入做对照** | `rag/retriever.py:65` `search(..., weights=(bm25,vector))`，注释已写「允许 (1,0)/(0,1) 做单路对照（评测用）」 | 纯向量/纯 BM25 两个臂**零改动**即得 |
| Embedding 可插拔协议 | `rag/embedder.py:44` `@runtime_checkable EmbeddingProvider`（`name/dim/fingerprint/embed/health_check`）+ `create_embedder` 工厂 | 新嵌入模型 = 新实现类，**协议已备好** |
| 向量库可插拔协议 | `rag/vector_store.py:47` `VectorStore` | 不动 |
| 结构感知分块 + 字符区间不变量 | `rag/splitter.py`（`text == doc.text[start:end]`，`heading_path`） | 语义分块的「按标题装箱」逻辑直接改它 |
| 一次性索引 + 临时库隔离 | `retrieval_eval.py:111 index_fixtures` / `:261 _prepare_env`（`DB_URL=sqlite:///<tmp>/eval.db` + `reset_settings_cache()`） | 消融 runner 的「每臂一库」照抄这套 |
| **成本/token/延迟统计** | `core/llm/adapter.py:175 Usage`（`token_in/token_out/cost/duration_ms/attempts`）、`evaluation/trace.py:223 aggregate` | P95/平均 token/单次成本**已解决**，别再写一遍 |
| 结构化输出调用 | `adapter.py:548 invoke_model(messages, PydanticModel)` | 四指标的判定式 prompt 全靠它，**这是自实现 ragas 的可行性基础** |
| Mock LLM | `tests/integration/mock_llm.py:23 MockLLMAdapter` | 消融 runner 的单测用它，零 token |
| 报表渲染 | `evaluation/metrics.py:226 format_report`（含 CJK 双宽对齐 `_display_width`） | 消融报表沿用 |
| Streamlit 页内直读 DB | `ui/pages/4_batch_eval.py:29 get_database()` 模式 + pandas `st.dataframe` | 新页 `5_ablation.py` 同构 |

### 真缺口（要新写的）

| # | 缺什么 | 证据 | 影响 |
|---|---|---|---|
| G1 | **RRF 融合** | 现融合是 min-max 归一 + 加权和（`retriever.py:101-113`），全仓无 `rrf` | E2a 少一个臂 |
| G2 | **Reranker 阶段** | `m2_rag.md:116` 明写「reranker 留 M3+」；无 `Reranker` Protocol | E3 整组 |
| G3 | **直接检索→生成通路** | `core/llm/prompts/v1/` 只有 planner/executor/reviewer/judge；RAG 仅作为 `knowledge_search` 工具存在 | **E4/E6 全卡在这** |
| G4 | **参考答案 + doc-id 标注** | `knowledge_eval.jsonl` 26 条，字段只有 `expect_document/expect_keywords`，**无 `ground_truth`** | faithfulness / context_recall 无法算 |
| G5 | **nDCG / Recall@k 纯函数** | 现只有 top1/top3/hit@5/MRR（`retrieval_eval.py:199 evaluate`） | 检索专项指标 |
| G6 | **显著性检验** | 全仓无 `scipy.stats` 使用（scipy 本身在 conda 环境可用） | 「差异不是随机波动」的凭据 |
| G7 | **实验矩阵 YAML + 单变量校验** | 全仓**零 YAML 支持**（grep `yaml/safe_load` 无命中）；`config.py:38` 是单层 `Settings(BaseSettings)` + `lru_cache(1)` | 「严格单变量」目前只是口号 |
| G8 | **引用溯源校验 / 拒答判定** | 无 `〖材料N〗` 解析、无拒答检测 | E4 四个臂的观测指标 |
| G9 | 语义/父子分块模式开关 | 只有单一 heading-aware 策略；`chunks` 表无 `parent_chunk_id`（`storage/models.py:241-265`） | E2b 三个臂 |

---

## 3. 决策记录

**D1 · 落点 = Trinity 增量 M3，不另起仓库。**
理由：v3 要的五层里 3.1/3.2/3.5 已存在且质量不低（懒加载纪律、TYPE_CHECKING、`slots=True`、不变量注释）。
对外叙事升级成「**已上线的多 Agent 平台补齐量化评测层**」比「又一个从零 RAG demo」强，
且能引用 379 个测试证明不是玩具。**代价**：必须尊重既有口径，见 D7。

**D2 · 四指标自实现，不引入 ragas 库。**（本方案最重要的工程判断）
- ragas 0.4.3 硬拉 `scikit-network`（Cython 编译产物）+ `datasets`/`pyarrow`（大体积 .pyd）。
  本机 Smart App Control **On**，对未签名二进制的拦截正是历史上 sentence-transformers 翻车的位置。
- ragas 要求 async LangChain Runnable，而 `adapter.py` **全同步**（无 `ainvoke`）。接进去等于再造一层异步壳。
- ragas 依赖 `langchain`/`langchain-community`，与本项目 `langchain-core 1.x + langgraph 1.2` 同装极易 resolver 打架。
- **成本账**：faithfulness（陈述拆解 + 逐条 NLI）、answer_relevancy（反生成 3 问 + 本地向量余弦）、
  context_precision（逐 chunk 相关判定）、context_recall（要点拆解 + 覆盖判定）——
  四条全是「prompt + `invoke_model(PydanticModel)` + 一个公式」，**约 400 行**，
  且能复用既有重试、token 统计、成本控制。
- **对外表述口径**（比"调库"更值钱，且完全诚实）：
  > 按 RAGAS 论文口径自实现 faithfulness / answer_relevancy / context_precision / context_recall 四指标评分器；
  > 未引入 ragas 库，因其依赖 langchain-community 与项目 langchain-core 1.x 冲突、且 scikit-network 二进制被本机应用控制策略拦截。
  > 追问「为什么不直接用 ragas」→ 这就是答案，是加分项不是心虚项。
- **P2 兜底**：若需要外部背书，在 30 题子集上单跑 `ragas.faithfulness` 与自实现做一致性对照（Spearman ρ）。装不上就放弃，不影响主线。

**D3 · 嵌入/重排走 `transformers + torch(cpu)`，绕开 sentence-transformers。**
`langchain_env`(py3.10) 已实测 `torch 2.13.0+cpu` 可 import 可 matmul。只需补
`transformers`（纯 py）+ 直接 `AutoTokenizer/AutoModel` 手写 mean-pool/CLS-pool —— bge 系列就是 CLS + normalize，20 行。
这条路**不碰 sklearn**，避开当年那个坑。
⚠️ **T0 先做可行性 spike**：pip 装 `transformers` 后能否 `AutoModel.from_pretrained` + `tokenizer(...)` 真跑一次前向。
失败降级：(a) `fastembed` 支持的中文子集（bge-small/bge-base-zh-v1.5，ONNX 路径已在 M2 验证）；
(b) DashScope `text-embedding-v3` API（花钱但只按 chunk 数计，50 篇语料 ≈ ¥0.1 级别）。

**D4 · 生成与 judge 都用 DeepSeek（同模型、temperature=0）。**
生成 `LLM_MODEL_LARGE`，judge 也用同一模型 —— judge 与被评模型同源会让指标偏乐观，
这是**已知偏差，必须写进报告的「局限」段**，别假装没有。若要更可信 judge（P1 选项）：
`LLM_MODEL_JUDGE` 指到更强档，成本约 ×3–5。

**D5 · 公开基准走 hf-mirror 直下 parquet，不装 `datasets`。**（T0 已实测跑通）
`hfl/cmrc2018` 三个 split 可由
`https://hf-mirror.com/datasets/hfl/cmrc2018/resolve/main/data/{train,validation,test}-00000-of-00001.parquet` 直接 curl 拿下。
**实测结构**（2026-09-18，用 pyarrow 21.0.0 读出）：

| 事实 | 实测值 | 对设计的影响 |
|---|---|---|
| schema | `id` / `context` / `question` / `answers{text[], answer_start[]}` | **无 `is_impossible` 字段** |
| 空答案行数 | train 0 / validation 0 / test 0（共 14,363 行） | ❌ **我上一版说"CMRC 自带不可回答题"是错的**，镜像里没有。拒答 30 题必须自己构造 |
| `id` 前缀 | `TRAIN_2619` / `DEV_8` / `TRIAL_154`，与 `context` **严格 1:1**（2403/2403、848/848、256/256） | ✅ 文档级分组干净，可直接当 `expected_doc_ids` 的映射键 |
| passage 长度 | min 195 / **median 453** / max 980 字 | ⚠️ 折成 token（`CHARS_PER_TOKEN=1.6`）中位仅 **283 tokens < chunk_size 500** → **一篇文档恰好一个 chunk**，见 D6 的轨道拆分 |
| 每篇题数 | 1–6（众数 2–5） | 题量充足：train 10,142 题可选 |
| 答案多样性 | validation 有 912/3219 行 `answers.text` 含**多个不同**答案 | 判分必须接受**任一**变体，不能只比第一个 |

读 parquet 只需 `pyarrow`（或 `fastparquet` 兜底），**不引入 `datasets` 整个栈**。

**D6 · Golden Set = 150 题，但拆成两条语料轨道。**（v3 的单轨道设计不成立）

**为什么必须拆**：E2b（分块策略消融）在 CMRC 语料上是**空实验** —— 每篇 passage 只有 ~283 tokens，
fixed / heading / semantic 三种策略切出来**都是同一个单 chunk**，三臂结果必然逐位相同。
拿这种语料跑 E2b 会得到「分块策略无影响」的**假结论**，写进报告就是自埋雷。

| 轨道 | 语料 | 题量 | 能消融什么 | 不能消融什么 |
|---|---|---|---|---|
| **A** | CMRC passage 抽 **1,000 篇**（≈45 万字，1000-way 检索，难度足够） | 100 | E1 嵌入、E2a 融合、E3 重排、E4 Prompt、拒答、术语 | ❌ E2b 分块（1 doc = 1 chunk） |
| **B** | 自建长文档 **3–5 份**（能源/电力规程、弱电安防规范，每份 ≥3,000 字带多级标题） | 50 | **E2b 分块策略**、多跳、术语编号 | — |

**题量分配（严格 150，且沿用 v3 的 40/20/20/20 比例）**

| 题型 | 总数 | 轨道 A（CMRC） | 轨道 B（自建长文档） |
|---|---|---|---|
| 事实型 | 60 | 55 | 5 |
| 术语/编号 | 30 | 15 | 15 |
| 多跳推理 | 30 | 0（CMRC 造不出真多跳） | 30 |
| 库外拒答 | 30 | 30（留出篇章） | 0 |
| **合计** | **150** | **100** | **50** |

分块消融（E2b）只在轨道 B 上报数，因此轨道 B 必须同时含**术语和多跳**两类跨段题——
它们对分块边界最敏感，是 E2b 真正的观测点。

**拒答 30 题的构造协议（替代那个不存在的 `is_impossible`）**：
从 **3,251 篇**候选里划出 **200 篇「留出题源」不入库**，其下问题即天然的库外题
（标准答案在语料里根本检索不到）。这套"留出段落即不可答"正是 SQuAD 2.0 负样本的构造法，**协议可复述、可复现**。
> **候选池大小已复核（2026-09-20）**：原文写的是「1,200 篇候选」，实测 CMRC train 2,403 篇 +
> validation 848 篇唯一 passage（与官方数字逐位相同）合计 **3,251 篇**；入库只用 1,000 篇 ⇒
> **还有 2,051 篇现成的干扰篇，零下载**（这正是 §8.13-2 那条"只能加干扰篇"的出路为什么便宜）。
⚠️ **已知漏洞必须写进报告**：CMRC 是百度百科条目，模型可能凭参数知识直接答对而无需检索
—— 对强制溯源的臂这就是"凭空作答"，正是要测的失败模式，所以**仍算有效拒答题**；
但为压低参数泄漏，留出集**优先抽长尾条目**（按 passage 内实体词频排序取最生僻的 200 篇）。

**D6 参数已用真实数据核算**（下列数字全部出自 `scripts/build_golden_set.py --dry-run` 的实际输出，
seed=7、train+validation 合并去重，可复跑复核，不是估计）：

| 量 | 实测值 | 影响 |
|---|---|---|
| 语料池 | CMRC 去重后 **3,251 篇唯一 passage / 13,361 题** | 池子够大，1,000+200 的切法有余量 |
| 轨道 A 语料 | **1,000 篇 = 517,527 字 ≈ 323,454 tokens**（`CHARS_PER_TOKEN=1.6`） | 每篇 ~323 tokens < `chunk_size=500` → **每篇恰好 1 个 chunk**（1000-way 检索）。这把 §7 陷阱 13 从推断变成事实 |
| 拒答池 | 留出 200 篇 → 837 题，**伪拒答 141 条 = 16.8%** 已剔除，干净池 **696** | ⚠️ 有约 1/6 的"库外题"答案 span 本来就能在入库语料里字面找到，不过滤则拒答率指标被污染。脚本按**任一可接受变体**判定（只查主答案会漏剔到 137 条），过滤动作与数量落进 `golden_manifest.json` |
| 事实题唯一性 | factual 池 2,921 题里**答案全库唯一 2,530 题 = 86.6%**，非唯一仅 391 题 | ⚠️ 这份语料**天生偏爱 BM25**。故 `--ambiguous-ratio`（默认 0.4）主动超采那 13.4% 的模糊题，实测事实题 40 道里 16 道为模糊题。不这么做的后果：E2a 大概率得到"混合检索相对 BM25 无显著提升"——**那是数据集设计的错，不是系统的错**，报告必须能区分这两件事 |
| 术语题池 | 1,183 题（答案含数字/拉丁串且库内字面可定位） | 这类型题是 BM25 的送分题，专门用来验证"精确匹配靠关键词"这条假设 |

**判分口径**：`ground_truth` = `answers.text` 全列表（接受任一变体）+ `answer_start` 供引用校验。
⚠️ CMRC 是**抽取式短 span**（中位几到十几字），RAGAS 的 context_recall「要点拆解」在这种答案上会退化成
「span 是否出现在检索结果里」≈ Recall@k 本身，**两个指标高度共线**。
→ 轨道 A 用 **span 命中**做检索侧真值，**claim 拆解式的 context_recall 只在轨道 B（整句答案）上报**，
报告里分别标注口径。混着报平均数会被判定为指标注水。

多跳 30 题若人工不够，允许 LLM 辅助出题，但报告与 README 必须标注「LLM 辅助构造 + 人工复核 100%」——
**评测集造假是这个项目唯一会一票否决的事**。

**D7 · 不动 M2 既有口径。**
min-max 加权融合保留为 `fusion="weighted"`（M2 的 Q8/D4 拍板依据还在），RRF 是**新增一个臂**而非替换。
否则等于推翻已交付结论，且丢掉「weighted vs RRF 谁更好」这个天然实验点。

**D8 · 配置走新模块 + YAML，不塞进 `Settings`。**
`config.py:208` 的 `_validate_rag_params` 会把 `bm25_weight+vector_weight` **归一并 warn**，
`@lru_cache(1) get_settings()`（`config.py:329`）是进程级单例。把 10 个实验旋钮塞进去会：
① 破坏不 sum 到 1 的对照臂；② 逼着每臂 reload 单例。
→ 新建 `evaluation/experiment.py`：frozen dataclass `ArmConfig` + YAML loader + 单变量 diff 校验；
按既有模式**显式传参**（`retriever.search(weights=...)`、`service.search(weights=...)` 已是这个套路）。

**D9 · 每臂一个临时 DB + 每臂一次索引重建。**
沿用 `_prepare_env`。`check_fingerprint`（`service.py:280`）对换模型的臂必然 409，隔离库是唯一干净解。

**D10 · 先 Phase A（零成本）再 Phase B（花钱），两阶段出口。**
E1/E2a/E2b 主要影响**检索侧**，纯函数指标就够（Recall@5/MRR/nDCG）；
只有 E3 的 context_precision、E4 的 faithfulness、E6 需要生成与 judge。
→ 半天内拿到真实检索结论，再决定要不要花钱跑生成侧。**这是把预算花在刀刃上的唯一办法。**

**D11 · 严格单变量用代码强制，不靠自觉。**
runner 启动时校验：每个臂与 baseline 的 `ArmConfig` diff **必须恰好 1 个字段**，否则拒绝执行并打印 diff。
这是 v3「E2a/E2b 必须拆开」的工程化落地，也是「怎么保证单变量」的硬答案。

**D12 · 显著性检验配多重比较校正，并对功效说实话。**
McNemar 精确二项检验（配对二值：是否命中 / 是否正确拒答）、Wilcoxon 符号秩（配对连续：四指标）。
7 臂 × 4 指标 = 28 个检验 → **Holm–Bonferroni 校正**，否则必有假阳性。
功效（n=150，α=0.05，power≈0.8）粗算：
- 二值指标（McNemar）：不一致对占比 ~15% 时，能稳定检出 **≥10pp** 差异；5pp 级别 power 约 0.5，**大概率不显著**。
- 连续指标（Wilcoxon）：中等效应量 d≈0.3 时 power 尚可，**≥8pp** 稳。
→ 报告里 0.72→0.74 这类必须写 `n.s.`，**不许**写成"提升"。这条既是学术诚实，也是经得起追问的盾。

**D13 · Phase A 的主判分指标是 nDCG@5 与 MRR@5；Recall@5 降为"天花板检查"。**（2026-09-19 拍板）
依据不是偏好而是实测：轨道 A 的基线 Recall@5 = **0.9571**（1,000 篇 / 70 道计分题），只剩 3 题空间，
"最优臂 Recall@5 提升 ≥5pp 且 p<0.05"这条门槛在轨道 A 上**按构造不可能满足**（详见 §8.9）。
排名类指标还有 4–9pp 余量，而且题型分化恰好落在排名上：术语/编号题 Recall@5 满分、
nDCG@5 却是全场最低的 0.9128。三处配套改动同步落地：
① §6 的 T4 出口门槛改判 nDCG/MRR；② §7 陷阱 1 的判据从"Recall 落在 0.6–0.8"改成
"Recall ≤0.95 **且** nDCG 有 ≥5pp 余量"；③ runner 的显著性族从 `{recall, ndcg, hit}` 换成
`{ndcg, mrr, hit}`。**轨道 B 到手后 Recall@5 重新升回主指标**（长文档、chunk 多，命中率才降得下来）。

**D14 · n=100 的显著性墙怎么破：走「轨道 A 免费扩到 300 题」，不走「放松校正口径」**。（2026-09-20 拍板）
§8.10 的算术是硬的：只有 8 个非零差异对时 Wilcoxon 双侧 p 的下界就是 2/2⁸ = 0.0078，
而 42 元 Holm 族要求 p < 0.00119 ⇒ **n=100 上任何结果都不可能过校正**。三条出路里：
① 加题（把非零对做多）；② 只预注册单主检验（把族从 42 压到 1~3）；③ 承认 n.s.、改报效应量。
选 ①，因为它是唯一**既不改判分口径、又不花 API 钱**的一条 —— Phase A 的 15 臂全在本地模型上。
②③ 都要在报告里写"我们把检验标准改了"，而追问"为什么改"的答案只能是"样本不够"，
那不如一开始就把样本够起来。执行与实测见 §8.13。
**结果（2026-09-20 当日关闭）：墙确实被推开** —— `A-E2a-vector` 与 `A-E3-base` 两条在 n=100 过不了
校正的对比，n=300 分别给出 p=0.0130 ✓（负向）与 p_raw=0.000473 ✓（正向），见 §8.14。
D14 本身关闭，但它顺带顶破的**语料天花板判据另开一条待拍**（§8.13-2）。

**D15 · 语料天花板走方案 A：只加干扰篇、题集一个字不动；拒答集的重算推到 Phase B 之前**。（2026-09-20 拍板）
三点曲线（§8.15）量完后三条出路里选 A：Phase A 现在就把语料拉到 **3,051 篇**（CMRC 全量 − 200 篇留出）。
理由是它**零成本买到术语列的分辨力**（term nDCG 0.9573 → 0.9176），而题集指纹不变 ⇒ 与 §8.10/§8.13/§8.14
三张历史表严格可比；B（全量重建）会让三张表全部作废，C（语料 3,000 + 留出 251）留到 Phase B 之前再做，
因为那时还没有任何 Phase B 数字、不存在可比性损失。
**代价写死在这里**：90 道拒答题有 **6 道（6.7%）** 在新语料下答案重新字面可得，
Phase B 的"正确拒答率"分母必须读 **84** —— 见 §8.17。
**D13 那条 Recall@5 ≤0.95 的判据仍然没过，也仍然没改**：A 只把语料拉满，Recall 卡在 0.9762 的结构性地板上。
是否把判据改成"≤0.98 且未召回 ≥5 题"是另一件事，**不在本条里替他拍**。

---

## 4. 架构与插入点

```
M2 已有                                  M3 新增（★）
─────────────────────────────────────────────────────────────
ui/pages/4_batch_eval.py          ★5_ablation.py  矩阵对比页
        │                                │
api/ ── core/workflow/graph.py    ★evaluation/ablation.py  矩阵 runner
        │                          ★evaluation/generation_metrics.py 四指标
        │                          ★evaluation/stats.py  McNemar/Wilcoxon/Holm
rag/service.py:319 search()  ──── ★query_rewrite（P2）
        │
rag/retriever.py:101 融合  ───────★fusion="weighted"|"rrf" 分支
                     :113 截断前 ─★Reranker 精排（candidate pool 内）
rag/splitter.py        ──────────★mode="heading"|"semantic"（父子 P2）
rag/embedder.py:工厂   ──────────★TorchBgeEmbedder / FastembedEmbedder / ApiEmbedder
core/llm/prompts/v1/   ──────────★answer_basic / answer_grounding / answer_refusal / answer_cot.md
                           +     ★citation.py 〖材料N〗 解析与校验
```

### 4.1 RRF（G1）

`HybridRetriever.__init__` 加 `fusion: Literal["weighted","rrf"] = "weighted"`（放在 `candidate_multiplier` 旁，`retriever.py:45-54`），
`search()` 在 `:101` 处分支。RRF 不需要归一化（只用秩），正好绕开 min-max 的「跨查询不可比」限制（`m2_rag.md §7.2`）：

```python
def _rrf(id_lists: list[list[str]], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ids in id_lists:
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores
```

⚠️ `SearchHit.bm25_score/vector_score`（`types.py:115`）文档语义是「min-max 归一后」，RRF 臂复用这两个字段会撒谎。
决定：RRF 臂把它们填**原始**分并在 `m3_design` 记录口径变化，或加 `rrf_score` 字段。倾向后者（诚实且不动既有断言）。

### 4.2 Reranker（G2）

新增 `rag/reranker.py`：

```python
@runtime_checkable
class Reranker(Protocol):
    name: str
    def rerank(self, query: str, candidates: list[SearchHit], *, top_n: int) -> list[SearchHit]: ...
```

实现：`CrossEncoderReranker`（transformers `AutoModelForSequenceClassification`，bge-reranker 系），
`NoopReranker`（基线臂，零成本）。
**插入位置必须在 `retriever.py:113` 的 `fused = fused[:top_k]` 之前**，作用域是 candidate pool
（`fetch_k=20 → top_k=5`）。放进 `service.search` 之后是错的——那时候选已被砍到 5 条，无精排空间。

CPU 成本预估（必须实测，不要引用 spec 的 440ms）：bge-reranker-base 278M 参数、8 CPU 线程、
20 候选 × ~400 token → **单查询 1.5–5s**。这会让检索侧 P95 从百毫秒级跳到秒级，
比 v3 表里的「+440ms」严重得多。**这一条本身就是 E3 最有价值的结论。**

### 4.3 直接生成通路（G3，最关键的缺失件）

新增 `rag/answer.py`：

```python
@dataclass(slots=True)
class RagAnswer:
    question: str
    answer: str                 # CoT 版已剥掉 <思考> 段；幻觉编号已被删除
    prompt: str                 # 实际用的模板角色名（臂字段回写，便于逐题核对）
    contexts: list[SearchHit]   # 送进 prompt 的材料，顺序即 【材料N】 编号
    citations: list[int]        # 解析出的全部被引编号
    valid_citations: list[int]  # 编号在 1..len(contexts) 内
    invalid_citations: list[int]  # 编造出来的编号（单列上报，正文里已删）
    refused: bool               # 命中拒答模板
    usage: Usage                # token / cost / 延迟，直接来自 adapter.last_usage
    retrieval_ms: int          # ★检索侧延迟，与端到端分开计
    latency_ms: int             # ★端到端延迟
```

`RagAnswerer.answer(question, *, prompt="answer_basic", top_k=5)`：
`service.search` → 编号化材料列表 → `render_prompt("answer_*")` → `adapter.invoke` →
`citation.parse` → 无效引用**从正文删除**（否则忠实度评分会去核对一个不存在的材料）→ 拒答判定
（匹配「根据现有资料无法回答」等模板串，串与 prompt 的耦合有单测钉住）。
检索以 callable 注入（`RagAnswerer.from_service(service)` 走生产通路，
runner 用自己的闭包换融合/重排），所以 Phase B 各臂只换检索、不换生成口径。

**prompt 版本就是 E4 的四个臂**：`answer_basic` / `answer_cot` / `answer_grounding`(溯源) / `answer_refusal`(溯源+拒答指令)。
放 `core/llm/prompts/v1/`，沿用 `string.Template` + `load_prompt`（`core/agent/base.py:120`）。

⚠️ v3 那句「`temperature` 设为 0.1」——**消融实验里温度必须钉死**（建议 0.0），
且 `get_adapter(temperature=...)` 是 `lru_cache(4)`（`adapter.py:706`），
E4 若要改温度的臂需 `reset_adapters()`。温度作为**固定常量**而非旋钮，否则单变量原则从第一步就破了。
→ 已按这条实现：`rag/answer.py:ANSWER_TEMPERATURE = 0.0`，`answer()` **不接受** temperature 参数，
每次调用仍显式把 0.0 传给 `adapter.invoke`（防适配器被别处以别的温度缓存复用）。

### 4.4 分块策略（G9）

`mode="heading"`（现状）/ `mode="semantic"`（标题边界优先 + 段内相似度低谷处断开）/
`mode="parent_child"`（P2）。
父子需要 `chunks.parent_chunk_id` 新列 —— nullable + `storage/migrations.py` 迁移，老代码不受影响；
但因需改 schema 且收益不确定，**降到 P2**，E2b 只做 fixed / heading / semantic 三臂。

### 4.5 指标层（G5 + 四指标）

`evaluation/retrieval_metrics.py`（纯函数，零 LLM）：`recall_at_k` / `mrr_at_k` / `ndcg_at_k`。
⚠️ v3 的 `recall_at_k` 分母用 `len(expected_ids)`、`mrr_at_k` 只取第一个命中 ——
两个都照抄会被追问。补上：`expected_ids` 为空时返回 None 而非 0（拒答题不该进检索指标均值），
且 nDCG 的二值增益口径在文档里写明。

`evaluation/generation_metrics.py`（LLM judge）：
四指标各自 = 1–2 次 `invoke_model(...)` + 一个公式。
**批量合并调用省 token**：faithfulness 的逐条 NLI 一次请求判完全部陈述；
context_precision 的 top-5 判定合并为一次请求。这能把 judge 成本压到 v3 方案的 1/3。

`evaluation/stats.py`：`mcnemar_exact` / `wilcoxon_paired`（scipy.stats）/ `holm_bonferroni`。

---

## 5. 实验矩阵（重算，两阶段）

基线 = `bge-small-zh-v1.5` + `hybrid weighted 0.4:0.6` + `heading` 分块 + 无重排 + `answer_basic` + `top_k=5`。

### Phase A — 检索侧，**零 API 成本**，可断网

| 臂 | 相对基线唯一改动 | 观测 |
|---|---|---|
| A-BASE | —（ONNX `fastembed/bge-small-zh-v1.5`，生产默认档） | Recall@5 / MRR@5 / nDCG@5 / 检索 P95 |
| A-E1-model-1 | embed = torch `bge-base-zh-v1.5` | 同上 |
| A-E1-model-2 | embed = torch `bge-large-zh-v1.5`（时间不够可砍） | 同上 |
| A-E1-backend | embed = **torch** `bge-small-zh-v1.5`（同模型换 runtime，与 A-BASE 一起构成「runtime 单变量」对照） | 同上 + 索引重建耗时 |
| A-E2a-1 | fusion = vector-only (0:1) | 同上 |
| A-E2a-2 | fusion = bm25-only (1:0) | 同上 |
| A-E2a-3 | fusion = **rrf**, k=60 | 同上 |
| A-E2b-1 | chunk = fixed(256/32) —— **仅轨道 B 出题** | 同上 |
| A-E2b-2 | chunk = semantic —— **仅轨道 B 出题** | 同上 |
| A-E3a | rerank = bge-reranker-base | 同上 + 重排延迟（实测 6.27 s/查询，见 §8.3） |
| A-E3b | rerank = bge-reranker-v2-m3 | 同上 |
| A-SENS | rrf k ∈ {20,60,100} / fetch_k ∈ {10,20,50} / chunk_size ∈ {256,500,800} | 参数敏感性（P1） |

⚠️ **E1 的三条臂必须锁在同一个 runtime（torch）里比模型**，否则"换了个嵌入模型"实际同时换了
运行时，违反 D11 的单变量原则——实测 `fastembed` 只支持 bge-**small**-zh，base/large 都报
`ValueError: Model ... is not supported`，所以想跨尺寸比模型就只能统一走 torch。
A-E1-backend 那条是**故意**做的 runtime 单变量对照（同模型 small，ONNX vs torch），它本身是结论不是噪声。

**按实测耗时排期（§8.3），runner 必须按「索引可否复用」分组，否则白烧 4 倍时间**：

| 组 | 是否重建索引 | 单臂成本 |
|---|---|---|
| E2a（换融合）、E3（换重排） | **复用** | 融合臂 ≈ 55s（150 题 × 39ms）；重排臂 ≈ **15.7 min** |
| E1-model（换嵌入，torch） | 重建 | ≈ 290s + 查询侧 |
| E1-backend / E2b（换分块） | 重建 | ONNX 臂 ≈ 43s；torch 臂 ≈ 290s |
| 模型加载（一次性，进程内复用） | — | small 11s / base 55s / rerank-base 129s |

**Phase A 合计：实测外推 65–90 分钟机器时间，¥0。**（不是先前写的 25–45 分钟）

### Phase B — 生成侧，花 API 钱

| 臂 | 唯一改动 | 观测 |
|---|---|---|
| B-BASE | — | 四指标 + 幻觉率 + 拒答率 + 端到端 P95 + token 成本 |
| B-E4a/b/c | prompt = cot / grounding / refusal | 同上 |
| B-E6 | Phase A 最优组合（全链路） | 全部 |
| B-E3' | grounding + rerank | faithfulness、context_precision（补齐 v3 的 E3 生成侧结论） |

≈ **6 臂** × 150 = **900 次生成 + ≤4,500 次 judge 调用**（拒答题一次 judge 都不调，
所以真实调用量按可答题占比 ≈ 3,150 次；臂数与 §8.16-1 彩排的一致，旧稿写"7 臂"是笔误）。

### 成本与时长（自己按公式复算，别信任何人的表）

按 `.env` 单价 ¥2/M in、¥8/M out，token 估算系数 `CHARS_PER_TOKEN=1.6`：

- 生成：in ≈ 5 chunk × 350 tok + 指令 ≈ 2,000；out ≈ 250 → 每臂 ≈ 2.1M in + 0.26M out ≈ ¥4.2 + ¥2.1 = **¥6.3/臂**
- judge（合并调用后）：≈ 3.5k in + 0.8k out / 题 → 每臂 ≈ 0.53M in + 0.12M out ≈ **¥1.9/臂**
- **7 臂合计 ≈ ¥57（高峰）/ ≈ ¥29（非高峰 5 折，`.env` 注释记录的工作日错峰）**
  > **这张表已作废（2026-09-20 复核，见 §8.16-3）**："每臂 ≈ 2.1M in"其实是 7 臂合计
  > （2,000 tok/题 × 150 题 = 0.3M），而同一张表里 judge 那行按臂算 ⇒ 单位混了，¥57 不可用。
  > 用本地实测的模板与材料重量 + 仓库单价表重算：**6 臂 × 150 题 ≈ ¥13.6 高峰、× 300 题 ≈ ¥27 高峰**
  > ⇒ 题量不是预算瓶颈。
- 墙钟：7,350 次调用，并发 5、均 3s/次 → **≈ 1.5 小时**；含重试与限流 **2–4 小时**

> 我之前问你的时候说「十几个小时 + 真实花费」，那是按 ragas 每样本 10–20 次调用估的。
> 合并调用 + 砍臂数之后**实际是几十块钱、2–4 小时**，比预估轻一个数量级。

**预算闸门**：runner 必须 `--max-cost` 默认 ¥30，先跑 15 题 smoke 打印实测单题成本，
再按 `实测单价 × 题数 × 臂数` 预检，超闸门直接拒绝启动。**先 smoke 再全量，没有例外。**

### 单组输出（对齐 v3 规范，两处修正）

```json
{
  "arm_id": "A-E2a-3",
  "diff_from_baseline": {"fusion": "weighted->rrf"},
  "config": {"embedding": "bge-small-zh-v1.5", "fusion": "rrf", "rrf_k": 60,
             "chunk_mode": "heading", "chunk_size": 500, "reranker": null,
             "prompt": null, "top_k": 5, "fetch_k": 20, "temperature": 0.0},
  "metrics": {"recall_at_5": 0.0, "mrr_at_5": 0.0, "ndcg_at_5": 0.0,
              "faithfulness": null, "context_precision": null, "answer_relevancy": null,
              "context_recall": null, "hallucination_rate": null, "refusal_accuracy": null},
  "cost": {"retrieval_p95_ms": 0, "e2e_p95_ms": null, "avg_tokens_in": 0,
           "avg_tokens_out": 0, "cost_cny": 0.0},
  "significance": {"vs": "A-BASE", "test": "wilcoxon", "stat": 0.0,
                   "p_raw": 0.0, "p_holm": 0.0, "n": 150, "power_note": "≥10pp 才可检出"},
  "per_question": [{"qid": "...", "type": "factual", "recall_at_5": 0.0,
                    "retrieved_doc_ids": [], "expected_doc_ids": [], "latency_ms": 0}]
}
```

修正点：① 延迟拆 `retrieval_p95_ms` / `e2e_p95_ms`（分歧表第 6 条）；
② 每臂落 `per_question` 明细，**McNemar/Wilcoxon 需要配对原始数据，只有均值就算不出 p 值**。

---

## 6. 里程碑

| 任务 | 内容 | 出口门槛 | 工时 | 状态 |
|---|---|---|---|---|
| **T0** | 环境复活 + spike：确认哪个解释器能跑 Trinity；SAC 下 `transformers`+`torch` 能否真跑一次前向与一次 reranker 前向 | 一条命令能 `import rag.service` 且 `pytest -q` 全绿；嵌入臂 ≥2 个可跑 | 0.5d | ✅ 完成（§8） |
| **T1** | 语料 + Golden Set：hf-mirror 下 CMRC（D5 已验证可下），写 `scripts/build_golden_set.py`，自建轨道 B 长文档 3–5 份 + 多跳 30 题 | 150 题、四类配比达标、**抽检 20 题标注正确率 100%**、拒答题 100% 来自「留出 200 篇」且**断言其 gold passage 不在索引库内** | 1d | 🟡 轨道 A **已按 D14 扩到 300 题**（165 事实 / 45 术语 / 90 拒答，语料一字未动，指纹与 qid 陷阱见 §8.13）；**轨道 B 等你提供 3–5 份规程文档** |
| **T2** | `experiment.py`（ArmConfig + YAML + **单变量 diff 强制**）+ 检索纯函数指标 + `stats.py` | 单测覆盖 diff 校验拒绝多变量；nDCG/MRR 与手算样例一致 | 0.5d | ✅ 完成（§8.6，+61 测试） |
| **T3** | RRF + Reranker + 分块 mode + 每臂临时库 runner | `pytest` 全绿；`fusion="weighted"` 结果与 M2 报表**逐位一致**（回归保护） | 1d | ✅ 完成（§8.7 组件 / §8.8 runner；515 tests 全绿，M2 报表逐字段一致已实测） |
| **T4** | **Phase A 全量真跑** + 检索侧消融表 + Wilcoxon | 产出 ≥9 臂真实数字；**主判 D13 的 nDCG@5 / MRR@5**：最优臂相对基线 nDCG@5 提升 ≥3pp 且校正后 p<0.05；Recall@5 只作天花板检查（基线 ≤0.95 即算语料合格，否则回 T1 加难度） | 0.5d | ✅ **门槛达成**（§8.10 + §8.13 + §8.14）：≥9 臂 ✓（n=300 的 13 臂 + 精排两臂趟）；最优臂 `A-E3-base` ΔnDCG@5 **+3.66pp ✓**、**原始 p 0.000473 < 0.00119 ⇒ 42 元族校正后 0.0199 ✓**（15 个非零对全同号、零回归，逐条可解释）；Recall 天花板 0.9857 **✗ 语料侧未解决**（子决定见 §8.13-2，且 hit@5 的 McNemar p=0.5 反过来给 D13 换指标提供了对照背书）。**〔口径补注 2026-10-04：这句"门槛达成"当时是以 42 元族校正后 p<0.05 判的，该检验 2026-09-21 已整条删除，现判据为 Δ + 波动带 ⇒ 结论沿用、判据换人〕** |
| **T5** | 直接生成通路 `RagAnswerer` + 4 版 prompt + 引用校验 + 拒答判定 | smoke 15 题端到端跑通、无效引用被剔除、拒答题命中模板 | 1d | 🟡 代码已落地（`rag/answer.py` + `rag/citation.py` + 4 版模板，26 单测全绿、mypy 干净：假适配器已验证"无效引用被剔除""拒答命中模板"两条）；**smoke 15 题等 `LLM_API_KEY`** —— Key 由你自己写进 `.env`（我不读那个文件），写好我立刻跑 |
| **T6** | 四指标评分器 + **Phase B 全量真跑**（smoke → 预检 → 全量） | 6 臂真实四指标 + 成本表；总花费 ≤¥60；显著性列齐 | 1d | 🟡 **代码侧全部落地、且已做无 Key 彩排（§8.16）**：6 条臂的准入检查全过（矩阵合法、四版 prompt 已登记、`top_k=5` 未超引用上限），成本按本地实测重量重算为 **6 臂 × 300 题 ≈ ¥27 高峰** ⇒ 题量不是瓶颈。彩排同时抓到并修掉一个真 bug：**`--limit` 原来取前 N 题 ⇒ smoke 15 题全是事实题**，既验不到"拒答题命中模板"这条门槛、又把单价高估到可能误拒全量（已改为按题型最大余数分层）。**只剩 smoke 单价与真跑，两件都前置在同一把 Key 上** |
| **T7** | 报告 + `ui/pages/5_ablation.py` + README/对外表述口径 + 失败案例归因 | 报告含「局限」段（judge 同源、LLM 辅助出题、多跳人工量）；页面能读 reports 并对比两臂 | 1d | 🟡 **页面已交付并真渲染验证**（15 臂总表 / 42 行显著性 / 100 题逐题 diff，见 §8.11）；剩报告正文与对外材料填数（等 Phase B 数字） |

**合计 ≈ 6.5 人日**（v3 的 16 天估算里，一半的时间是在重做你已经有的东西）。
T4 是**全项目最关键的分叉点**：Phase A 若拿不出有区分度的差异，说明语料或题目太难/太易，
必须回 T1 调数据集，**不要带着满分语料往下烧钱跑 Phase B**。

---

## 7. 避坑清单（这个项目会死在这些地方）

1. **占位语料满分陷阱**（最致命）。4 篇 1.1KB 文档上所有配置都 100%。~~判据：基线 Recall@5 必须落在 0.6–0.8~~
   → **D13 已按实测改判据**：基线 **Recall@5 ≤ 0.95** 且 **nDCG@5 有 ≥5pp 余量**才算语料合格
   （轨道 A 实测 Recall 0.957 / nDCG 0.966，命中率高到没差别，排名才是有差别的那一维）。
   高于 0.9 就加文档/加干扰项/去掉 `expect_keywords` 的双条件宽松度。
   > **D14 执行后的更新（§8.13）**：扩到 300 题后这条判据**两条都不过了**
   > （Recall 0.9857、nDCG 余量 4.14pp），且 `--ambiguous-ratio` 0.4→0.75 只动千分位。
   > 也就是说**加题数救不了天花板，只有加干扰篇能救** —— 这条陷阱仍然活着，只是换了触发条件。
2. **`.venv` 已经废了**。实测 `.venv/Scripts/python.exe` 被拦（`ApplicationFailedException`），
   里面 `import numpy` 都失败。→ **T0 第一件事**：改用 conda env 或 `python -m venv`（实测 conda 建的 venv 可跑），
   **不要用 uv 建的 venv 解释器**（SAC 拦 uv 的 redirector，不拦 conda 的）。
   M2 文档里「sentence-transformers 被 sklearn 未签名 pyd 拦截」的结论要**重测**——很可能当时真正的原因是解释器根本没起来。
3. **`sqlite-vec` 的选型是在 CPython 3.14 上 spike 的**（`m2_rag.md §6`），换到 py3.10/3.13 需重新确认 vec0 可用，
   不可用则 `VECTOR_STORE_BACKEND=chroma` 兜底 —— 但**所有臂必须用同一个后端**。
4. **别照抄 v3 的量化表**。那列数字（Faith. 0.72→0.90、P95 420ms、拒答 40%→92%）是**目标示例**，
   照抄出去就是造假，被追问「0.72 怎么测的」直接穿。只写自己跑出来的，带指标定义与 n。
5. **judge 与被评模型同源偏差**（D4 已记）。报告「局限」段必须写：judge = deepseek-flash，
   同家族打分存在自增强偏好；未做人工复核比例 X%。诚实写出来是加分，藏起来是雷。
6. **`Settings` 的权重归一 validator 会静默改掉你的实验参数**（`config.py:208`），
   跑出来的「BM25 单路」臂可能实际是别的权重。→ 一切实验参数走 `ArmConfig` 显式传参，**绝不经 Settings**。
7. **`lru_cache` 三连**：`get_settings`(1) / `get_adapter`(4) / `get_knowledge_service`。
   跨臂切换必漏改，`reset_settings_cache()` + `reset_adapters()` + 重置 service 单例要包成一个 `arm_teardown()`。
8. **多跳与拒答的标注造假**。LLM 辅助出题必须人工 100% 复核并在 README 标注；
   拒答正确性的判定不能只靠字符串匹配，要落人工抽检样本。
9. **把不显著的差异说成提升**（D12）。28 个检验不校正必出假阳性。
10. **重排/父子分块无限制扩臂**。每加一个臂 ≈ +¥8 + 20min。臂数上限在 smoke 前定死。
11. **`chunk_id` 不可作为跨臂标注键**（D6）。只有 `document_id` 稳定。
12. **父项 `m2_rag.md §7.1` 的 jieba 术语切分问题**在 E2a 的「术语/编号精确匹配」20 题上会直接决定 BM25 臂的成败 ——
    这不是 bug，**这是一个可以主动讲的实验发现**。✅ T3-2 已落地：`rag/bm25.py` 的 `userdict` 走
    **私有 `jieba.Tokenizer`**（不用全局 `jieba.add_word` / `load_userdict`，那会污染同进程的其他臂），
    对照效果见 §8.7-4（假命中被消除，但**分数不可跨臂比较**）。
13. **短 passage 语料让分块消融变成空实验**（T0 实测：CMRC 中位 453 字 = 283 tokens < `chunk_size=500`）。
    fixed/heading/semantic 三臂会切出逐位相同的结果，得出「分块无影响」的**假结论**。→ D6 双轨道强制拆分，
    **E2b 只在自建长文档轨道上报数**。
14. **抽取式短 span 让 context_recall 与 Recall@k 共线**（span 拆解只剩 1 个 claim）。混在一张均值表里报 = 指标注水。
    → claim 拆解式 context_recall 只在整句答案的轨道 B 上报（D6 判分口径）。
15. **README 的 `pip install -e .` 是坏的**（T0 实测）：仓库根是 `api/ core/ rag/ evaluation/ storage/ ui/ scripts/`
    多顶层包 + `config.py` 的**平铺布局**，setuptools 自动发现在 editable 安装阶段直接报
    `Failed to build ... when getting requirements to build editable`。
    → 别踩这条：依赖按 `pyproject` 清单显式 `pip install`，测试靠根目录 `conftest.py` 把 rootdir 前置进 `sys.path` 即可跑。
    若要修，就在 `pyproject.toml` 里显式写 `[tool.setuptools] packages = [...]`（属于对既有工程的改动，需你点头）。

---

## 8. T0 实测结论（2026-09-18 ~ 09-19，已完成）

### 8.1 环境基线（定稿）

| 项 | 结论 |
|---|---|
| 解释器 | **`<USER_HOME>\venvs\trinity-m3` = Python 3.12.13**（uv 托管的基础解释器 + stdlib `python -m venv` 建的虚拟环境）。仓库里那个 `.venv`（uv 建、CPython 3.14.6）被 SAC 拦死、**已作废但未删除** |
| 装依赖 | `pip install -e .` **失败**（平铺多顶层包布局，setuptools 自动发现在 editable 阶段直接拒绝）→ 按 `pyproject` 的清单显式安装 |
| PyPI 源 | 必须走 `https://mirrors.aliyun.com/pypi/simple`（实测 8.8 MB/s，对比 pypi.org 直连的 156 kB/s 与反复断流） |
| torch | **不要用 `download.pytorch.org/whl/cpu`** —— 实测掉到 35 kB/s 并断流重启。PyPI 上的 `torch-2.14.0-cp312-cp312-win_amd64.whl` 本身就只有 118 MB，**就是 CPU 版**，走 aliyun 直接装 |
| HF 下载 | 双条件缺一不可：`HF_ENDPOINT=https://hf-mirror.com` **且** `HF_HUB_DISABLE_XET=1`。只设前者的话元数据能拿到、blob 仍去打 `cas-server.xethub.hf.co` 并返回 **401** |
| 磁盘 | 未开开发者模式 → HF hub 缓存以**副本**而非符号链接存盘，同一模型多份权重要按 2× 估容量 |
| 依赖漏项 | `fastembed` 是运行时真实后端但 **`pyproject` 里没声明**；已补 `fastembed>=0.4`。后果链见 §8.5 |

### 8.2 Smart App Control 真相：D3 的降级分支可以划掉

| 组件 | 3.12 实测 |
|---|---|
| `torch 2.14.0+cpu` | ✅ import + 真实 matmul（512×768 @ 768×512 = 3.1 ms，8 线程，`cuda available=False`） |
| `transformers 5.17.0` + `tokenizers 0.23.2` | ✅ bge-base-zh-v1.5 真跑前向，dim=768，**L2 归一断言通过** |
| `bge-reranker-base`（`AutoModelForSequenceClassification`） | ✅ 真跑前向，20 候选分数分布合理（top1=9.153 / top20=4.390） |
| **`sentence-transformers 6.0.1` + `scikit-learn 1.9.1`** | ✅ **装得上也跑得通**（加载 12.0 s，encode 110 ms） |

**M2 的那句历史结论被推翻。** `m2_rag.md §6` 写「sentence-transformers 被本机 Windows 应用控制策略拦截
（sklearn 未签名 pyd）」——在 3.12 上**不成立**。合理解释：当时 spike 跑在 **CPython 3.14**
（`spike_embedding_stack.py:2` 自证），3.14 太新无预编译 wheel → pip 源码自编译 → 产物未签名 → 被 SAC 拦；
而预编译 wheel 路径（3.10/3.12/3.13）根本不会触发。那套 `.venv` 的解释器现在连 `import numpy` 都做不到，
进一步说明当时的失败里有相当比例不是"包被拦"。
→ **D3 的降级分支（fastembed 中文子集 + DashScope API embed）从"必需"降为"备用"。**
→ 顺带：`m3_design.md` 的 E1/E3 可以直接用标准 `SentenceTransformer` / `CrossEncoder` API，不必手写 CLS-pooling。

### 8.3 耗时基线（Phase A 排期的真正依据，全实测）

| 路径 | 模型加载 | 单条 | 1000 篇索引重建 |
|---|---|---|---|
| ONNX `fastembed/bge-small-zh-v1.5`（dim 512） | 11.0 s | **39 ms** | **≈ 41 s** |
| torch `transformers/bge-base-zh-v1.5`（dim 768） | 54.5 s | 280 ms | ≈ **287 s**（4.8 min） |
| torch `bge-reranker-base`，20 候选/查询 | 129.4 s | ~~6.27 s/查询~~ → **11.19 s**（p95 12.47 s，见 §8.10） | 100 题一轮 ≈ **1 115 s**（18.6 min） |
| torch `bge-reranker-v2-m3`，20 候选/查询 | 324.9 s | **31.09 s**（p95 39.87 s） | 100 题一轮 ≈ **3 449 s**（57.5 min） |

> ⚠️ 这行的 6.27 s 是**轨道 A 口径**（CMRC 长 passage，padding 顶到 512）。T3-1 复核补记：
> 延迟随**候选长度**而非候选条数走，同一实现在 M2 短 chunk 语料上只要 **1.1 s/查询**，
> 而 batch 从 20 切到 8 几乎不省（6.01 → 5.76 s）。细节见 **§8.7-1**。
> **T4 全量实跑（§8.10）再校准：base 实际 11.19 s/查询、v2-m3 31.09 s/查询，比这张表又慢 1.8×/5×**
> —— 因为 spike 那轮是单查询串行、缓存热的状态，真跑时向量召回 + 元数据回填 + 20 条长正文一起进 batch。
> runner 的排期常量已同步改成 11.2 / 33.0（单测钉住），别再沿用本表第一版的数字。

三个必须据此改设计的后果：

1. **v3 spec 的「Reranker 延迟 +440ms」低估了 14 倍。** CPU 上开 bge-reranker-base，检索侧从
   几十毫秒级直接跳到 **6.3 秒/查询**。E3 的真实结论会长成"重排是用一个数量级的延迟买精度"，
   报告里的 P95 必须按这个量级写，不能沿用 spec 的表。
2. **E1 不许混 runtime 比模型。** 实测 `fastembed` 只支持 bge-**small**-zh，
   `bge-base-zh-v1.5` / `bge-large-zh-v1.5` 均 `ValueError: Model ... is not supported`。
   所以"ONNX-small vs torch-base"同时改了**模型和运行时两件事**，违反单变量。定稿拆成两条：
   - **E1-model（锁 torch runtime，纯模型对比）**：bge-small-zh / bge-base-zh /（bge-large-zh 视时间）；
   - **E1-backend（生产默认档，单列）**：ONNX/bge-small。它的价值恰恰是"同一模型换运行时快 **7×**"这条独立发现。
   - 报告里两者分开命名，**不许**合并成"换个嵌入模型提升 X pp"。
3. **Phase A 排期从 §5 写的"25–45 分钟"改成实测 65–90 分钟**，仍然 **¥0**。
   换分块/换嵌入都要重建索引（ONNX 臂 41 s、torch 臂 287 s），换融合策略可复用索引（只付查询侧 45 s/150 题），
   重排臂每个 15.7 min。runner 必须按「索引可复用性」分组排臂，否则白烧 4 倍时间。
   > **T4 实跑校准（§8.10）**：15 臂 / 7 组 / 100 题实际 **1h43m**，其中重排两臂占 76 min。
   > 索引重建实测 ONNX 组 **41–66 s**、torch/bge-base **259 s**（常量已改成 55/265，缓存冷的下载另计：
   > bge-large 那组 1 019 s）。排期误差的方向始终是"低估"，所以新模型/新臂第一次跑要先量再排。

### 8.4 T1 轨道 A 已顺手做完

- `scripts/build_golden_set.py`（ruff 全绿）；默认参数即 D6 的配比，seed=7 复跑数据集指纹稳定为
  **`e9a8230f2381`**，可复现性已实测验证（同 seed 两次跑逐字节一致）
- 产物：`evaluation/fixtures_cmrc/` 1,000 篇语料（4.5 MB）、`evaluation/dataset/golden_a_cmrc.jsonl`
  **100 题**（factual 55 / term 15 / refusal 30，落在 150 的轨道 A 配额上）、
  `golden_manifest.json`（池子大小、伪拒答剔除数、配比、指纹）
- 抽检：100 题覆盖 **98 个不同篇章**（`PER_DOC_CAP=2` 的分篇抽样生效）、题干无重复、
  可答题的 `expected_document` 全部指向真实存在的语料文件
- 关键口径：拒答题 `expected_doc_ids=[]`、`expected_document=null`，留出篇章只记在 `heldout_document`。
  写错的话检索指标会把"命中了留出篇章"判成正确（M2 的 `retrieval_eval` 同样会误判为 0 命中）
- 实测数字与由此产生的两个坑，全部记在 **D6 的核算表**（伪拒答 16.8%、答案全库唯一 86.6% → BM25 主场）
- **待办**：轨道 B 的 50 题（多跳 30 + 术语 15 + 事实 5）**要你提供 3–5 份能源/电力规程或弱电安防文档**
  （每份 ≥3,000 字、带多级标题）。这不是脚本能造的，也是 §6 里唯一卡在你身上的输入
- **2026-09-20 追加**：同一脚本、同一份语料、同一 seed 又切了一份 **300 题**的
  `golden_a_cmrc300.jsonl`（D14 选项 ①），旧的 100 题文件原样保留 —— 见 §8.13

### 8.5 pytest 结论与 T0 遗留项

**底座可运行：`379 tests / 0 failed / 0 errors / 0 skipped`，33 s**（junit XML 计数，连跑 3 次、
两种目录顺序均为全绿）。M2 的 379 个测试在 3.12 上不需要任何修改即通过 —— D1「复用而非重写」的前提成立。

1. **`test_api_stream.py::test_stream_full_sequence` 是负载敏感的时序 flaky，不是 bug。**
   它只在「同一时刻后台正在从 hf-mirror 拉 1.1 GB 权重」的那几次全量跑里失败
   （`assert 0 >= 2`，SSE 事件一个都没收到）；单独跑、以及下载结束后连跑 3 次全量均通过。
   夹具里 `API_SSE_HEARTBEAT_SECONDS=0.1`（`tests/integration/conftest.py:105`）在无争用的机器上够，
   在 CPU 被 torch 前向占满时不够。
   **对 M3 的直接影响**：消融 runner 会把 CPU 打满，此时若有人同时跑测试就会看到假失败。
   T3 的 runner 必须（a）用进程内并发上限（默认 ≤ `cpu_count-2`）、（b）在文档里写明
   "跑实验期间不要并行跑 integration 测试"，并把这条 heartbeat 断言改成轮询式（对齐
   `conftest.poll_terminal` 已有的写法）。
2. **`health.py:133-141` 的 rag 特判会让配置缺陷变得不可见。**
   `llm=fail` 与 `rag=fail` 同时发生时整体只算 degraded/200，而 `test_health_shape_and_checks` 断言 503 ——
   所以最初那次失败**表面是测试挂、实质是「`fastembed` 漏声明」被健康检查的降级逻辑吞掉了**。
   补上 `pyproject` 的 `fastembed>=0.4` 后测试即回到应有断言。
   这类"降级逻辑掩盖缺陷"的模式必须在 M3 防住：**臂级健康检查失败要让该臂整体失败，不许降级继续**
   （否则某臂的嵌入模型没加载成功，会静默产出"该臂全 0 分"的假结论，比崩溃危险得多）。
3. **HF/PyPI 的镜像与 xet 开关要进代码，不能只写在文档里。**
   `HF_HUB_DISABLE_XET=1` 缺失时权重下载会以 401 失败且报错信息指向一个看似无关的 CAS 服务。
   T3 的 runner 启动时统一 `os.environ.setdefault(...)`（已照此改了 `scripts/spike_m3_stack.py`）。

---

### 8.6 T2 完成：实验矩阵 + 检索指标 + 显著性检验

新增三个模块 + 三个测试文件，**全量 440 tests / 0 failed（33 s）**（T0 是 379，T2 净增 61）。

| 模块 | 职责 |
|---|---|
| `evaluation/experiment.py` | `ArmConfig`（frozen+slots，可哈希）+ YAML 装配 + **单变量强制校验** + `index_key()` |
| `evaluation/retrieval_metrics.py` | `recall_at_k` / `precision_at_k` / `hit_at_k` / `mrr_at_k` / `ndcg_at_k`，纯函数零 LLM |
| `evaluation/stats.py` | `mcnemar_exact` / `wilcoxon_paired` / `holm_bonferroni` / `compare_*` / `adjust_family` |
| `evaluation/dataset/matrix_m3.yaml` | **22 条臂**的完整矩阵（16 条 Phase A + 6 条 Phase B），`validate()` 零违规 |

**四个值得记下来的设计判断：**

1. **`reference` 既是归因参照物，也是继承的父配置。** 装配顺序 = YAML 书写顺序。
   所以 `A-E1-torch-base` 只写 `embed_model` 就能从 `A-E1-backend` 继承到 `embed_backend=torch`。
   如果把 `reference` 实现成单纯的"比较标签"，这条臂会静默退化成 **ONNX + bge-base** ——
   字段一个没多改、实验条件却完全不同，而且 ONNX 后端根本不支持 bge-base。
   这条有专门的回归用例 `test_reference_is_also_the_inherited_parent` 钉住。
2. **惰性字段单独分类，是这套校验里最有价值的部分。** 只改 `rrf_k` 而 `fusion` 仍是 `weighted`
   的臂，两臂结果**逐位相同**，报表里会呈现"该参数不敏感"的假结论 —— 而 YAML 看上去明明改了东西。
   所以 `active_fields()` 按 `fusion` / `reranker` / `phase` 判定哪些字段真的被代码读到，
   两边都不生效的改动直接拒绝执行。
3. **`weighted` 下权重之和 ≠ 1 时这里抛错，而 `config.py:_validate_rag_params` 是归一 + warn。**
   两者刻意相反：实验参数被静默归一，跑出来的就不是你以为的那个配置（§7 陷阱 6）。
4. **`index_key()` 把 §8.3 的排期结论变成结构性事实**：22 条臂按索引指纹只分成 **8 组**，
   其中一组 15 条臂共用一份索引（融合/重排/top_k/prompt 全在查询侧，不动索引）。
   runner 只要按这个分组跑，就自动省掉 ~64% 的索引重建。

**指标口径的两个要点**（写进测试断言，防止将来被"顺手改一下"）：

* 期望集为空 → 返回 `None` 而**不是 0**。30 道拒答题若按 0 计入，会把 Recall@5 系统性压低约 18%，
  且 Wilcoxon 的配对里会凭空出现大量假差异；
* `precision_at_k` 分母用 `k` 而非实际返回条数 —— 否则"只召回 1 条且恰好命中"算满分 1.0。

**顺带发现（未修，一行可修）**：`pytest.mark.unit` / `pytest.mark.integration` 在
`pyproject.toml` 的 `[tool.pytest.ini_options]` 里没注册，每次跑都刷 `PytestUnknownMarkWarning`。
补 `markers = ["unit", "integration"]` 即可，属于既有配置改动，等你点头。

---

### 8.7 T3 完成：RRF + 精排 + 三种分块 + torch 后端 + 词典臂

代码落点与旋钮（ruff 干净；**494 tests 全绿**，M2 原有 379 个测试零修改仍通过）：

| 组件 | 位置 | Settings 键 / 矩阵字段 |
|---|---|---|
| RRF 融合 + 两个单路口径 | `rag/retriever.py` 的 `_fuse()` / `rrf_scores()` | `HYBRID_FUSION` / `fusion`，`RRF_K` / `rrf_k` |
| 精排阶段（在截断之前） | `rag/retriever.py:search` 末段 + `rag/reranker.py` | `RERANKER_MODEL` / `reranker` |
| 分块三档 heading/fixed/semantic | `rag/splitter.py:mode` | `CHUNK_MODE` / `chunk_mode` |
| torch 嵌入后端 | `rag/embedder.py:TorchBgeEmbedder` | `EMBEDDING_BACKEND` / `embed_backend` |
| jieba 自定义词典 | `rag/bm25.py:userdict`（私有 Tokenizer） | `JIEBA_USERDICT` / `jieba_userdict` |

Settings 里新增这些字段**只为线上档与手工 env 对照**；runner 一律显式构造组件、
不经 Settings（陷阱 6 依然有效，那条 validator 只会改权重）。

**回归保护是实测的，不是"测试全绿"自我安慰**：`fusion=weighted` 下重跑 M2 的 5 组权重评测，
与 `evaluation/reports/eval_20260917_202506.json` **逐字段相同**（只允许 `generated_at` 与
`took_ms` 变），26 题 × 5 组 × 全部 details 一起比。T3 动的正是 M2 的核心路径，只有这条 diff 能证明没改坏。

**四个新增实测发现**（都要进报告口径）：

1. **重排延迟 ∝ 候选长度，不是 ∝ 候选条数** —— 给 §8.3 那个单一数字补上条件。
   同一台机器、同一份权重、20 候选/查询：
   * M2 种子文档（chunk 短）：**1.1 s/查询**；
   * CMRC 真实 passage（p50 501 字，padding 后张量宽度顶到 512）：
     **单批 20 条 = 6.01 s**、**生产 batch=8 = 5.76 s**，5 轮全落在 5.65–6.53 s。
   → §8.3 的 6.27 s 没被推翻，它是「轨道 A 口径」的真值；把 batch 从 20 切到 8 省不了多少
   （成本在 padding 到本批最长，不在批大小）。排期仍按 **150 题 ≈ 15 min/重排臂**，
   但轨道 B（长文档）要按更长候选重测一次。
2. **`CHARS_PER_TOKEN=1.6` 对中文偏乐观约 20%**。实测 bge 词表：20 对 (query, passage)
   共 11,220 字符 → **8,455 tokens**，即 **1.33 字符/token**。后果：splitter 认定
   「≤480 tokens」的 768 字 chunk，真实约 577 tokens，**尾部 ~13% 已被 max_seq=512 静默截断**。
   E3 的「重排误排：长文本截断」归因与 E2b 的 chunk_size 敏感性都必须按这个口径复核。
3. **semantic 阈值是定标出来的，不是拍的**：CMRC 120 对**不同 passage** 的相邻余弦
   min 0.242 / p25 0.329 / 中位 0.367 / p75 0.411 / max 0.546 → 取 `SEMANTIC_SIM_THRESHOLD=0.35`
   （分布下沿）。0.45 会把约七成边界判成低谷，退化成「一段一 chunk」，等于没做语义切分。
   ⚠️ CMRC 训练集没有文章 id 列，拿不到「同文章相邻段落」的对照组，所以这是**下界估计**，
   轨道 B 到手后复核（与陷阱 13 同源）。
4. **词典臂只能比排序，不能比分数**。挂上「六类线」后查询从 `六类/线` 两个 token 变成一个，
   BM25 可加项少一项，实测 top1 分数 **1.50 → 0.78（不升反降）**。切分变了，分数量纲就变了
   —— A-DICT 与 A-E2a 各臂一律只报 Recall/MRR/nDCG。顺带两条硬事实：
   ① `rank_bm25` 用的是不带 +1 的 Robertson idf，**2 条语料里 df=1 会让 idf 恰为 log(1)=0**，
   小样本夹具必须 ≥4 条 chunk 才拿得到非零分数；
   ② 词典走 `jieba.Tokenizer()` **私有实例**，不用全局 `jieba.load_userdict()` ——
   后者会污染同进程的其他臂，runner 单进程跑多臂时会静默串味（报表上看不出来）。

**指纹纪律的延伸**：`TorchBgeEmbedder.fingerprint() = sha1("torch:{model}:{dim}")`，
与 ONNX 同模型同维度也**不同**。否则换后端时指纹闸放行、直接查旧 runtime 建的库，
E1-backend 这条臂的结论当场作废。代价是每次换后端强制重建一次（轨道 A 实测 41 s/1000 篇）。

**仍待真跑确认（TODO，不写进结论）**：`bge-large-zh` 臂要同时改 `EMBEDDING_DIM=1024`
（`TorchBgeEmbedder` 有维度守卫，配错当场报错而不是静默错位）；A-DICT 的词典文件
（从 golden set 术语表生成）随 T3-3 的 runner 一起落地。

---

### 8.8 T3-3 完成：消融 runner + CLI + 预算闸门

`evaluation/ablation.py`（新增）+ `scripts/run_ablation.py`。**515 tests 全绿**。

```bash
python scripts/run_ablation.py --list                                # 只看矩阵计划
python scripts/run_ablation.py --arm A-BASE --arm A-E2a-rrf --limit 20   # smoke
python scripts/run_ablation.py --phase A --out evaluation/reports/ablation
```

行为：按 `Matrix.index_groups()` 分组 → 每组一套**临时**索引库（`DB_URL`/`KNOWLEDGE_DIR`
指向临时目录，跑完连句柄一起释放）→ 组内每臂只重建查询侧组件 → 输出
`ablation_summary.json` + `arm_<id>.json`（含 `per_question` 配对原始观测）+ `ablation_table.md`。
退出码：0 全跑通 / 1 参数漂移·预算超限·某臂失败 / 2 矩阵非法。

**端到端 smoke 已通过**（`RAG_FAKE_EMBEDDER=1`、轨道 A 1000 篇、12 题、3 臂）：
分组建库 2 次而不是 3 次（`A-E2a-rrf` 复用 `A-BASE` 的库，`index_reused=true`），
表、JSON、Holm 校正列齐全。**数字本身无意义**（哈希向量），证明的只是管道。

smoke 逼出来的三处修正 —— 都是"错了也看不出来"那类：

1. `verify_arm_settings` **只能核索引侧字段**。第一版把 `hybrid_fusion`/`rrf_k`/`reranker_model`
   也一起核，结果同组第二臂（rrf）被报成"参数漂移"：一个 Settings 被组内多臂共享，
   而查询侧参数压根不经 Settings（由臂配置直接构造）。现在 env 只写索引侧 7 个键，
   查询侧一律显式传构造器 —— 少一份可能不一致的"假真相"。
2. `hit_at_k` 对拒答题必须记 **None 而不是 False**。拒答 30/100 题按 False 入均值的话，
   命中率会被系统性压低约三分之一，且 Wilcoxon 配对里凭空多出大量"基线错/新臂也对"的假差异。
3. **前置检查的顺序**：Phase B 的拒绝要在读数据集之前；A-DICT 缺词典的预检要在建库之前。
   否则烧掉几十分钟才告诉用户"词典文件不存在"。

预算闸门：Phase A 的 `cost_cny` 恒为 0（零 API 调用），真正限的是时间 ——
`estimate_seconds()` 用 §8.3/§8.7 的实测常量算预估，超过 `--max-seconds` 直接拒跑。
Phase B 另有金钱闸：启动前按 smoke 实测单价 × 题数 × 臂数预检（`--unit-cost-cny` 没传就只警告），
跑起来后逐题累计，触到 `--max-cost-cny`（默认 ¥30）立刻抛 `CostLimitExceeded` 停掉整趟 ——
已跑完的臂照样落盘，汇总里写明中止原因（细节见 §8.12）。

**T4 入口已就绪**，但两件事要先定：① 轨道 A 基线 Recall 是否落在 0.6–0.8（陷阱 1，
mock smoke 里是 0.5，真模型上大概率不同）；② A-DICT 臂依赖轨道 B 术语表，
轨道 A 上没有可提取的行业术语，**该臂现在会在预检处被拒**（这是有意的，不编造词典文件）。

---

### 8.9 T4 开工前的第一手数字：轨道 A 的 Recall@5 已经贴顶（要你拍板改判分主指标）

`A-BASE`（ONNX bge-small + weighted 0.4:0.6 + heading 500/80 + fetch20→top5）在
**轨道 A 全 100 题 / 1000 篇语料**上的实测（`evaluation/reports/ablation/baseline100/`）：

| 题型 | n | 计分 | Recall@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| factual | 55 | 55 | 0.9455 | 0.9182 | 0.9803 |
| term（术语/编号） | 15 | 15 | **1.0000** | 0.8833 | **0.9128** |
| refusal（库外） | 30 | 0 | n/a（正确排除） | n/a | n/a |
| **合计** | 100 | 70 | **0.9571** | 0.9107 | 0.9658 |

检索延迟 p50 **32 ms** / p95 **42 ms**（与 §8.3 的 39 ms 一致）。

> **口径更正（追算后）**：上表的 nDCG 是**文档级去重之前**算的，同一篇文档占两个槽会把增益计两次，
> 所以合计 0.9658、factual 0.9803 都偏高。去重后（`ablation_table.md` 现值）：
> **基线 nDCG@5 = 0.9226**、factual 0.9253、term 0.9128（术语题那一列本来就没重复槽，数值未变）。
> Recall@5 / MRR@5 与 hit 未受影响的那部分仍成立，但 MRR 也随去重略升（重复槽不再把首命中往后挤）。
> "term 的 nDCG 全场最低"这个结论**不变**，且更强：0.9128 vs 事实题 0.9253。

**结论：陷阱 1 在轨道 A 上以另一种形式复现了。** 不是满分，但 Recall@5 = 0.957 只剩 3 题的
提升空间 —— 任何臂都不可能在这上面做出 ≥5pp 且 p<0.05 的差异。§6 里 T4 那条出口门槛
（"最优臂 Recall@5 提升 ≥5pp 且 p<0.05"）**按现在的写法在轨道 A 上必然判负**，
而判负的原因不是系统没优化好，是指标选错了。

真正有区分度的地方，数据里看得很清楚：

* **排名质量**：MRR@5 = 0.911、nDCG@5 = 0.966 都有 4–9pp 的余量，够 Wilcoxon 说话；
* **题型分化**：术语/编号题 Recall@5 满分，但 nDCG@5 只有 0.9128（全场最低），
  而且它比事实题的 nDCG 低 6.8pp —— 这正是 jieba 碎切"该命中第 1 的排到第 3、4"的指纹。
  聚合均值会把这件事完全抹平，所以 runner 已按题型分别落 `by_type`（本轮加的）。

**已拍板（D13）**：Phase A 的主判分指标改成 **nDCG@5 与 MRR@5**，
Recall@5 降级为"天花板检查"（只用来证明语料没简单到没救）；
术语/编号那 15 题单独成列，作为 E2a/E-DICT 的主要观察面。runner 的显著性族同步改为
`{ndcg_at_5, mrr_at_5, hit@5}`。轨道 B（长文档）到手后，Recall@5 重新升回主指标 ——
那边 chunk 多、gold 只有 1 篇，命中率才有下降空间。

**为什么这是好消息**：贴顶的 Recall 配上不贴顶的 nDCG，恰好是"检索召回够用、排序不够好"的诊断，
而排序正是重排臂（E3）和融合臂（E2a）该发挥作用的地方。报告里这一段可以写成
"我们发现基准指标饱和，于是改用排名指标"，比"我们跑了个 95% 的检索"有说服力得多。

---

### 8.10 T4 实跑：轨道 A 15 臂全量数字（两条门槛没过，且不是巧合）

**跑法**：`scripts/run_ablation.py --phase A --max-seconds 10800`，16:17 → 18:00，墙钟 **1h43m**，
15 臂 / 7 个索引组 / 100 题 / 1000 篇语料，**API 成本 ¥0**，无失败臂。A-DICT 在预检处被跳过
（词典要等轨道 B 的术语表，见 §8.9 尾注）。

**判分口径是追算出来的，不是重跑出来的。** 这趟跑到一半我才把 D13 的显著性族和
文档级去重落进代码，进程里仍是旧口径；每臂的逐题原始观测（含 `retrieved_doc_ids`）都增量落过盘，
所以用 `scripts/rebuild_ablation_report.py --dir evaluation/reports/ablation/phaseA`
重打分 + 重做配对检验即可。**下表与 `ablation_table.md` 都是追算后的口径**
（nDCG 已无 >1 的假分数，族 = {nDCG@5, MRR@5, hit@5}）。

| 臂 | 唯一改动 | nDCG@5 | MRR@5 | 命中率 | Recall@5 | 术语nDCG | 事实nDCG | P95(ms) | 历史校正后 p（检验已删除，仅留档） |
|---|---|---|---|---|---|---|---|---|---|
| A-BASE | （参照基线） | 0.9226 | 0.9107 | 0.9571 | 0.9571 | 0.9128 | 0.9253 | 34 | — |
| A-E1-backend | embed_backend='torch' | 0.9226 | 0.9107 | 0.9571 | 0.9571 | 0.9128 | 0.9253 | 30 | 1.0000 |
| A-E1-torch-base | embed_model='…base' | 0.9385 | 0.9321 | 0.9571 | 0.9571 | 0.9620 | 0.9320 | 58 | 1.0000 |
| A-E1-torch-large | embed_model='…large' | 0.9361 | 0.9286 | 0.9571 | 0.9571 | 0.9508 | 0.9320 | 250 | 1.0000 |
| A-E2a-bm25 | fusion='bm25_only' | **0.9450** | 0.9362 | 0.9714 | 0.9714 | 0.9754 | 0.9367 | 26 | 1.0000 |
| A-E2a-rrf | fusion='rrf' | 0.9398 | 0.9286 | 0.9714 | 0.9714 | 0.9508 | 0.9368 | 35 | 1.0000 |
| A-E2a-vector | fusion='vector_only' | 0.8519 | 0.8500 | 0.8571 | 0.8571 | 0.8000 | 0.8660 | 25 | 0.3958 |
| A-E2b-fixed | chunk_mode='fixed' | 0.9226 | 0.9107 | 0.9571 | 0.9571 | 0.9128 | 0.9253 | 29 | 1.0000 |
| A-E2b-semantic | chunk_mode='semantic' | 0.9226 | 0.9107 | 0.9571 | 0.9571 | 0.9128 | 0.9253 | 26 | 1.0000 |
| A-E3-base | reranker='…bge-reranker-base' | **0.9857** | **0.9857** | 0.9857 | 0.9857 | **1.0000** | 0.9818 | 12 468 | 0.3958 |
| A-E3-m3 | reranker='…v2-m3' | 0.9857 | 0.9857 | 0.9857 | 0.9857 | 1.0000 | 0.9818 | **39 868** | 0.3958 |
| A-SENS-chunk256 | chunk_size=256 | 0.9332 | 0.9250 | 0.9571 | 0.9571 | 0.9374 | 0.9320 | 30 | 1.0000 |
| A-SENS-fetch50 | fetch_k=50 | 0.9317 | 0.9179 | 0.9714 | 0.9714 | 0.9508 | 0.9264 | 70 | 1.0000 |
| A-SENS-rrf-k100 | rrf_k=100 | 0.9345 | 0.9214 | 0.9714 | 0.9714 | 0.9262 | 0.9368 | 32 | 1.0000 |
| A-SENS-rrf-k20 | rrf_k=20 | 0.9398 | 0.9286 | 0.9714 | 0.9714 | 0.9508 | 0.9368 | 42 | 1.0000 |

（`k=5`；术语列 n=15、事实列 n=55，拒答 30 题不计分。A-E1-* 参照 `A-E1-backend`，
`A-SENS-chunk256` 参照 `A-E2b-fixed`，`A-SENS-*rrf/fetch*` 参照 `A-E2a-rrf` —— 都不是基线，见 D11/D12 的参照臂条款。）
> 上表末列是**校正后** p；原始 p 只有三行 <0.05（`A-E3-base` / `A-E3-m3` / `A-E2a-vector` 均 **0.0097**，
> 其余 ≥0.08），完整 12 列（含 ΔnDCG、原始 p、校正后 p 并列）以 `ablation_table.md` 为准。
>
> **⚠️ 口径（2026-10-04 补）**：这一列的检验（原 `evaluation/stats.py` 的 McNemar / Wilcoxon /
> Holm–Bonferroni）已于 **2026-09-21 整条删除**，今天的代码不产 p 值 —— 比对结论只报 `delta` /
> `rel_lift`，落盘字段是 `"significance_removed": true`（`evaluation/ablation.py:775`），
> `p_raw` / `p_adjusted` 保留在契约里但一律 `None`（`:739-740` 自己写明"读到的任何 p 值都应当被忽略"）。
> 所以本表与下文引用的 p 都是**当时的历史留档**，现在判"达标"用的是 Δ + 波动带。
> 另：`ablation_table.md` 落在 `evaluation/reports/`，被 `.gitignore:54` 挡住 ⇒ **干净 clone 里它不存在**，
> 要复核这张表要么复跑 `scripts/run_ablation.py --phase A`，要么直接读本表。

**七条发现**

1. **精排是唯一有实质收益的检索组件**：nDCG@5 0.9226 → 0.9857（**+6.31pp**），MRR +7.50pp，
   术语题 nDCG 0.9128 → **1.0000**（15/15 首槽命中）。代价：P95 34 ms → **12 468 ms（×367）**。
   逐题看是 8 个非零差异、**8 胜 0 负**，原始 p=0.00965 —— 效应真实且方向一致，但见第 7 条。
2. **v2-m3 该砍**：与 base 的三列指标**逐位相同**（0.9857/0.9857/0.9857），P95 却 39 868 ms（×3.2）。
   矩阵里该臂 notes 已改成"已砍，Phase B 只带 base"（臂保留在矩阵里，历史报表仍可复算）。
3. **默认融合权重在轨道 A 上是错的**：`bm25_only` 0.9450 **> 生产基线 weighted(0.4:0.6) 0.9226**，
   `vector_only` 0.8519（−7.07pp）。也就是说向量分支在百科语料上净拖后腿，BM25 才是主力。
   RRF 0.9398 比 weighted 好 1.72pp，且 `rrf_k` 20/60 **完全同分**、k=100 只降 0.5pp → 融合超参不敏感，
   报告里不值得单列调参表（这条本身是个可讲的"我试过调，它不敏感"）。
4. **ONNX 化不改结果，只改延迟**：`A-E1-backend`（torch/bge-small vs ONNX/bge-small）
   **100/100 题 top-5 逐位一致**、四指标全等、P95 30 vs 34 ms。这是"量化/换运行时是纯工程收益"的硬证据。
5. **嵌入模型加大不买精度**：base +1.59pp、large +1.35pp（768→1024 维反而略降），
   P95 30 → 58 → **250 ms**，而且 bge-large 冷下载把那一组索引从预估 265 s 拖到 **1 019 s**。
   → 生产留 small/base，对外材料里**不许**写"换更大嵌入模型提升 X pp"。
6. **E2b 三条臂在轨道 A 上没有区分度 —— 但这不等于"分块无影响"**：
   1000 篇 CMRC 语料实测 **100% 是单段落**（无空行分块、无标题），长度 276–978 字、p50 468 ≤ chunk_size 500
   → heading / fixed / semantic 三种 mode 产出**同一套 chunk**，于是 100/100 题 top-5 与四指标全等。
   唯一真被切开的是 `chunk_size=256` 组（+1.05pp nDCG，2 个非零差异）。
   报表里这三行必须标"**语料结构使该变量不可测**"，并在轨道 B（长文档、多级标题）上重跑。
7. **天花板检查按字面写是没过的**：门槛是"基线 Recall@5 ≤0.95 算语料合格"，实测 **0.9571**，
   差 0.7pp ≈ 1 题。同时 nDCG@5 有 7.7pp 余量 —— 也就是 D13 判断的"排序不饱和"成立、
   "命中饱和"临界。这条要么承认轨道 A 偏易（回 T1 加难题/加干扰篇），要么承认定得过严 → 见 D14。

**排期常量已按实测重写**（`evaluation/ablation.py` 顶部，单测钉住）：
重排单查询 6.0/12.0 s → **11.2 / 33.0 s**，冷加载 130 → **330 s**，索引重建 41/287 → **55/265 s/1k 篇（权重已缓存）**。
本趟预估 52.5 min vs 实际 103 min，低估全部来自重排常量 —— **耗时尚可预测的前提是先量过一遍**，
第 3 次校准（§8.3 → §8.7-1 → 本轮）都是同一个方向：低效估计。

**显著性的硬事实（这条决定 D14）**：族大小 42（14 个有效比较 × 3 指标），
Holm 最小乘数 42 ⇒ 需要原始 p < 0.05/42 = **0.00119**。
而 Wilcoxon 在只有 8 个非零差异时，**能取到的最小双侧 p 就是 2/2⁸ = 0.0078**（8 胜 0 负已是最好结果）。
→ 不是"这次没测出来"，是**这个样本量下任何结果都不可能通过校正**。要么把非零对做多一点（加题），
要么把族缩小（只预注册主检验），要么改报效应量。

---

### 8.11 T5 / T6-1 / T7 代码全部落地（等 Key 的只剩"真跑"那一步）

Key 还是 401，所以把**不花钱的活推到底**了。三件事都带单测，579 tests 全绿、新文件 mypy 干净：

| 件 | 落点 | 已验证到什么程度 | 还差什么 |
|---|---|---|---|
| T5 生成通路 | `rag/answer.py` + `rag/citation.py` + 4 版 `answer_*.md` | 26 单测走假适配器：端到端一次生成、幻觉编号被删、拒答命中模板、温度恒 0 | 真跑 15 题（Key） |
| T6-1 四指标 | `evaluation/generation_metrics.py` + 5 版 `metric_*.md` | 15 单测钉住口径与**"一题恰好 5 次 judge 调用"**这条成本不变量 | smoke 单价实测 → `--max-cost` 预检 → Phase B 真跑（Key） |
| T7 页面 | `ui/pages/5_ablation.py` + `evaluation/ablation.py` 的读回端 | 真浏览器 + 真 Phase A 报表：15 臂总表 / 42 行显著性族 / 100 题逐题 diff 都渲染出来了 | 报告正文 + README/对外表述口径填数（等 Phase B） |

**页面的一条硬约束：只读不算。** 所有指标、p 值、Δ 都来自 runner 落盘的 `ablation_summary.json`；
读取端函数（`discover_report_dirs` / `load_report` / `metric_rows` / `significance_rows` / `diff_rows`）
就写在 `evaluation/ablation.py` 的落盘函数旁边 —— 写字段名的人同时负责读字段名。
页面上重新推导一遍指标，只会产出一张"看起来正常但和报表不一致"的表。

两个实现细节值得记：

1. **逐题 diff 按 `qid` 对齐，不按行号。** 某臂少跑几题（smoke 截断、单臂失败）时按行号对齐会整体错位，
   而错位后的表看起来完全正常 —— 这类 bug 只有真数据能暴露，所以单测里专门造了左右臂题集不同的用例。
2. **`parents[1]` 写错让页面永远显示"还没有报表"**，且不报错。这条已经补成单测
   （`test_page_module_points_at_the_real_reports_root`），并注明是拿浏览器渲染出来才发现的 ——
   不是假想的防御。顺带说明本机的验证边界：Qoder 内嵌浏览器视口 0×0，`st.dataframe` 是 canvas 渲染，
   **截图和单元格文本都读不到**，只能验证"页面挂载 + 控件数量 + caption 文案"，视觉效果要你亲眼看一眼。

---

### 8.12 T6-2：Phase B 接进 runner（代码侧完成，等 Key 的只剩"真跑"）

把"Phase B 一律拒跑"那扇门拆掉的同时，钉了三件事。853 tests 全绿（+15 条 Phase B 用例），
改动文件的 `ruff F,E9` 干净。

| 决定 | 落点 | 为什么这样切 |
|---|---|---|
| **一题只检索一次** | `ArmGenerator._capture_search` 闭包 | `RagAnswerer.search` 注入的是本臂检索器的闭包，闭包把这批 `SearchHit` 抄出来给检索指标用。分两次检索的话"生成看到的材料"与"判分看到的材料"可能不是同一批，逐题 diff 会全是假差异。单测直接断言检索器 `calls` 长度为 1、且评分器收到的 `materials` 就是那批 hit |
| **成本闸双层** | `CostBudget` + `--unit-cost-cny` / `--max-cost-cny`（默认 ¥30） | 预检要单价，单价只能从 smoke 来；没标定不能拿"估不出来"当理由拒跑（smoke 自己就是第一次跑），所以那种情况只警告、靠逐题累计的硬闸兜底。硬闸抛 `CostLimitExceeded`（`AblationError` 子类）才能穿过"单臂失败要进报表"那层 `except Exception` —— 烧穿闸门是整趟的停止信号，不是某一臂的失败 |
| **显著性族按 phase 换** | `significance_family()` | Phase A = nDCG/MRR + hit@k；Phase B = faithfulness/context_recall + hit@k/拒答正确。把两组指标塞进同一个族只会让 Holm 乘数翻倍、把真有信号那列的 p 值推高。nDCG 在 Phase B 表里保留一列，标注"(传导)"，只读不进族 |
| **缺件检查排在读数据之前** | `_require_generation_ready()` | 没 Key / prompt 版本未登记 / `top_k > 10`（引用编号只到【材料10】）三种情况都在建库前拒。`phase=B 必须有 prompt` 由 `ArmConfig.__post_init__` 把门，runner 不重复一遍 |

顺手修的两个真 bug（都不是假想防御）：

1. **`@k` 被写死成 `@5`**：摘要表和页面的指标列都按 `ndcg_at_5` 取值，而报表里的键跟着各臂自己的
   `top_k` 落（`ndcg_at_3` / `ndcg_at_10`）—— 那些臂整行 n/a，看着像"没跑"。现在两侧都按本臂的 k
   取、取不到再退回历史报表的 `@5` 口径。
2. **Phase B 的逐题 diff 会被筛成空表**：过滤器原来只看"检索排序是否相同"，而 E4 家族
   **检索完全相同、只换 prompt**（正是最有看头的那组对照）。差异判据改成"排序或任一指标不同"，
   diff 表补上忠实度/要点召回/拒答对/答案四对列。

另外两件口径：`GoldenQuestion` 新增 `ground_truth` → `reference`，CMRC 的 gold 是**抽取式答案 span**
而不是完整参考段落，所以轨道 A 的 context_recall 偏低是口径如此，别读成"模型不行"；
页面上的表现在会**丢掉整列无值的列**，Phase A 报表不再挂一排全 n/a 的生成列。

验证边界同 §8.11：本机 `st.dataframe` 是 canvas、视口 0×0，页面只能用 `AppTest` 无头验证
（Phase B 假报表跑通：总表 2 行 24 列含 faithfulness、diff 表 1 行含"忠实度·B-BASE / 答案·…"、
成本闸 caption 生效、零异常）。**还差的是真数字，不是代码。**

---

### 8.13 D14 选项 ① 执行完毕：轨道 A 扩到 300 题，功效墙实测拆掉

全仓 **855 tests / 0 failed**（+2 条：300 题数据集不变量、GBK 控制台下的 CLI 存活）。

选 ① 的理由只有一个：**它是唯一既不改判分口径、又不花钱的一条**，而 Phase A 全是本地模型。
一趟 `python scripts/build_golden_set.py --factual 165 --term 45 --refusal 90 --out-dir <临时目录>`
就出新题集 —— 该脚本按固定文件名写 `dataset/golden_a_cmrc.jsonl`，所以产物是**改名后**放进
`evaluation/dataset/` 的（直接写默认目录会覆盖 100 题那套和它的 manifest）。
语料侧**一字未动** —— `evaluation/fixtures_cmrc/` 那 1,000 篇与 100 题趟逐字节相同，
所以两趟报表可以直接对照。新集 `evaluation/dataset/golden_a_cmrc300.jsonl`，
seed=7、指纹 **`2852b3e5a73d`**，旧的 100 题文件原样保留。

| | 100 题趟 | 300 题趟 |
|---|---|---|
| 配比（事实/术语/拒答） | 55 / 15 / 30 | 165 / 45 / 90 |
| 计分题（拒答不计分） | 70 | 210 |
| 伪拒答剔除 | 141 / 837（16.8%） | 同一批（协议与语料未变） |
| 基线 Recall@5 | 0.9571 | **0.9857** |
| 基线 nDCG@5 | 0.9226 | **0.9586** |

**四条后果，每条都带数。**

1. **qid 不能跨报表 join，但内容是真子集。** `emit()` 的编号是全局流水号，`--factual` 一改，
   `A-factual-056` 之后的号全变：两趟只有 **22/100** 个 qid 指向同一道题。100/100 道旧题的 query
   与 `expected_doc_ids` 都完整保留在新集里（补了单测 `test_track_a_300_dataset_invariants` 钉住），
   但**跨趟对齐必须按 query 文本**。顺带白捡一次复现性验证：按 query 对齐后，两趟 A-BASE 的
   100 道题 top-5 篇章顺序**逐条相同**、nDCG 无一差异 —— 检索通路对题目集合大小是确定性的。

2. **加题 ≠ 加难度，这次反而更容易，于是 D13 的语料判据两条都过不了。**
   原来那 70 道计分题在这趟里的 nDCG 均值仍是 0.9226，**新增的 140 道是 0.9766**，
   合起来把基线推到 0.9586 ⇒ Recall@5 0.9857 > 0.95 越界，nDCG 余量 1−0.9586 = **4.14pp < 5pp** 也越界。
   而且 D6 设计的那个难度杠杆是**零效应**的 —— 把 `--ambiguous-ratio`（事实题里"答案 span 出现在 ≥2 篇"
   的超采比例）从 0.4 抬到 0.6、0.75，基线只动了千分位：

   | `--ambiguous-ratio` | 基线 Recall@5 | 基线 nDCG@5 |
   |---|---|---|
   | 0.40（默认） | 0.9857 | 0.9586 |
   | 0.60 | 0.9857 | 0.9604 |
   | 0.75 | 0.9810 | 0.9613 |

   → "超采模糊题能给向量/混合臂留区分度"在 1000 篇规模上被证伪：答案 span 出现在 ≥2 篇，
   仍然是 BM25 的主场。**要压天花板只能加干扰篇**（语料 1000 → 3000+ 篇，索引重建 ≈ ×3、仍然 ¥0），
   或者承认轨道 A 就是"命中饱和、排序有余量"的语料、把 D13 的 0.95 改成实测达得到的数。
   **这条要你再拍一次板，我不替你改判据。**
   > **已实测，见 §8.15**：干扰篇在 CMRC 内部就够（2,051 篇现成），但量出来的结论是
   > "nDCG 余量救得回、Recall@5 有 0.9762 的地板救不回" ⇒ 出路 A/C + 改判据。

3. **功效墙拆掉了 —— 13 臂 / 7 索引组 / 300 题 / ¥0、无失败臂**（A-DICT 仍在预检跳过；重排两臂另算，见第 4 条）：

   ```
   python scripts/run_ablation.py --phase A --dataset evaluation/dataset/golden_a_cmrc300.jsonl \
     --out evaluation/reports/ablation/phaseA300_cheap --arm A-BASE --arm A-E1-backend \
     --arm A-E1-torch-base --arm A-E1-torch-large --arm A-E2a-bm25 --arm A-E2a-rrf \
     --arm A-E2a-vector --arm A-E2b-fixed --arm A-E2b-semantic --arm A-SENS-chunk256 \
     --arm A-SENS-fetch50 --arm A-SENS-rrf-k100 --arm A-SENS-rrf-k20        # 35.6 min / ¥0
   ```

   补上 `--arm A-E3-base`（以及要复核才带的 `A-E3-m3`）就是完整的 15 臂 n=300 报表，族大小从 36 变 42。
   **但记得同时抬 `--max-seconds`**：全 15 臂在 300 题上的预估是 240 min，而闸门默认 180 min，
   不抬就是启动即拒（退出码 1，且不会烧一分钟）：

   ```
   python scripts/run_ablation.py --phase A --dataset evaluation/dataset/golden_a_cmrc300.jsonl \
     --out evaluation/reports/ablation/phaseA300 --max-seconds 21600     # 全 15 臂，≈4 h / ¥0
   ```

   只想验 D14 那条门槛的话，跑 `A-BASE + A-E3-base` 两臂就够（≈56 min），
   代价是族只有 3 元、校正后 p 与 42 元族不可直接比 —— 报告里必须写明族大小。

   | 臂 | ΔnDCG@5 | 非零对 | 该非零对下最小可达 p | p_raw | 校正后 p（36 元族） |
   |---|---|---|---|---|---|
   | **A-E2a-vector** | **−4.17pp** | **16** | **3.1e-05** | **0.000383** | **0.0130 ✓** |
   | A-E2a-bm25 | +0.67pp | 23 | 2.4e-07 | 0.4577 | 1.0 n.s. |
   | A-E1-torch-base | +1.08pp | 11 | 9.8e-04 | 0.1431 | 1.0 n.s. |
   | A-E1-torch-large | +1.00pp | 13 | 2.4e-04 | 0.2885 | 1.0 n.s. |
   | A-E2a-rrf | −0.16pp | 9 | 3.9e-03 | 0.8124 | 1.0 n.s. |
   | A-SENS-fetch50 | −0.48pp | 3 | 2.5e-01 | 0.1088 | 1.0 n.s. |
   | A-SENS-chunk256 | +0.13pp | 7 | 1.6e-02 | 0.9314 | 1.0 n.s. |
   | A-SENS-rrf-k100 / k20 | −0.18 / +0.06pp | 1 / 1 | 1.0 | 0.3173 | 1.0 n.s. |
   | A-E1-backend、A-E2b-fixed/semantic | 0.00pp | **0** | — | 1.0 | 结构不可测（见 §8.10-6） |

   三条读数：
   - **`A-E2a-vector` 同一臂、同一判据：校正后 p 从 n=100 的 0.3958（n.s.）变成 n=300 的 0.0130 ✓**
     （原始 p 0.0097 → 0.000383；非零对 8 → 16）—— D14 选 ① 的机制假设被直接验证。
     它是个**负向**结论（纯向量臂显著更差），但"能不能过校正"不分方向。
   - **"过不了校正"和"没有效应"从此是两件事**：n=100 时两者混在一起无法区分（任何 p 都过不了 42 元族）；
     n=300 时 bm25 有 23 个非零对（最小可达 2.4e-07，理论上连 42 元族都过得去）却实测 p_raw=0.4577
     ⇒ 那是**真的没效应**。报告里"哪些差异我们检出了、哪些差异确实不存在"这一段，靠的就是这个区分。
   - 小样本上的"收益"会被稀释：`A-SENS-chunk256` 在 n=100 是 **+1.05pp / 2 个非零对**，
     n=300 缩到 **+0.13pp / 7 对**。这就是 D12 说的陷阱长什么样。
     嵌入模型两臂则复现了量级（base +1.08 / large +1.00，n=100 是 +1.59/+1.35），
     P95 85.8 vs **308.9 ms** ⇒ **"换更大 embedding 涨点"依然不许写进对外材料**。

4. **排期第 4 次低估，而且低估的地方变了**：预估 1190 s vs 实际 **35.6 min**（×1.8）。
   拆开看，**查询侧根本不是大头**（13 臂 × 300 题总共 **3.4 min**：复用索引的臂 8.9–16.9 s，
   两条 torch 臂 24.1 / 60.9 s），
   7 个索引组重建合计 **32 min**，其中 bge-large 那一组单独 **1314.7 s（21.9 min）**、torch-base 319 s。
   → 结论对排期有用：**题数几乎不要钱，语料规模才要钱**（且换嵌入模型/分块参数都得重付这笔）。
   重排两臂没进这趟：`A-E3-base` 按 11.19 s/题 × 300 ≈ **56 min**、`A-E3-m3` ≈ **155 min**（该臂已判可砍）。

**顺手修的两个真问题**（都不是假想防御）：

1. `main()` 里的 GBK 防护原来写在 `parse_args` 之后 ⇒ `--help` 和参数报错走 argparse 自己的 usage
   打印时照样 `UnicodeEncodeError`（本会话第一次撞上，是跑完 15 臂后 print 单价那一步：评测成功却退出 1）。
   已挪到 `ArgumentParser` 构造之前，`test_cli_survives_a_gbk_console` 覆盖。
2. `scripts/build_golden_set.py` 文档字符串里三个"实测"百分比**与脚本自己写进清单的值不符**
   （早期一次性探针的 19.7% / 84.7% / 163，vs 复算的 16.8% / 86.6% / 141）。已按复算值改掉，
   并注明 137 那条是"只查主答案"的口径。**教训：文档里引用自己的实测值，得标清它是哪段代码算出来的。**

**还差什么**：只剩 `A-E3-base` 的 300 题真跑 —— 那才是 D14 出口门槛"最优臂 nDCG@5 ≥3pp 且校正后 p<0.05"的最后一块。
按 n=100 的 8 胜 0 负外推，非零对会在十几个的量级、能过 42 元族；**但外推不是结果**，所以 §6 T4 那一格先不写 ✓。

> **一条免掉 3.5 小时的判据（预注册，写在结果之前）**：不必为这一条重跑全 15 臂。
> Holm 的第一步乘数就是族大小，而**原始 p 与族无关** ⇒ 只要两臂趟（`A-BASE` + `A-E3-base`，族只有 3 元）
> 量出的 **p_raw < 0.05/42 = 0.00119**，它在完整的 42 元族里同样过得去（反之若 p_raw ≥ 0.00119，
> 跑满 15 臂只会让它更难通过，不会救回来）。粗略地说就是"非零对 ≥11 且全同号"（2/2¹¹ = 9.8e-04
> < 1.19e-03），但**差值有并列时实测 p 会高于这个理论下界**（n=100 的重排臂 8 对全同号，
> 下界 0.0078、实测 0.0097），所以判据以**报表里的 p_raw** 为准：
> 2026-09-20 08:25 起的是这趟两臂跑（预估 63 min / ¥0，`--out evaluation/reports/ablation/phaseA300_rerank`），
> 读 **p_raw** 而不是 `p_adjusted`（两臂趟的族只有 3 元，那个校正后 p 与 42 元族不可比）。

---

### 8.14 T4 出口门槛判定：精排在 300 题上 p_raw=0.000473 ⇒ D14 关闭

两臂趟 `A-BASE` + `A-E3-base` 于 300 题实跑（08:25 → 09:13，**48 min / ¥0**，无失败臂）。
**上一节那条预注册判据被满足，所以 T4 的第四条门槛现在可以打 ✓：**

| 判据 | n=100 | **n=300** |
|---|---|---|
| 最优臂 ΔnDCG@5 ≥ +3pp | +6.31pp ✓ | **+3.66pp ✓**（0.9586 → **0.9952**） |
| 校正后 p < 0.05（42 元族） | 原始 p 0.0097 → 下界不可能 ✗ | **原始 p 0.000473 < 0.00119** ⇒ 42 元族校正后 **0.0199 ✓** |
| 非零对（Wilcoxon） | 8（8 胜 0 负） | **15（15 胜 0 负）**，理论下界 2/2¹⁵ = 6.1e-05 |
| 基线 Recall@5 ≤ 0.95（语料天花板） | 0.9571 ⚠️ | 0.9857 **✗ 仍未过**（子决定，见 §8.13-2） |

**四个读数**

1. **归因表把显著性解释得比 p 值更清楚**（`scripts/analyze_ablation_failures.py`）：
   基线 F2「召回未居首」13 道 → 精排 **0 道**、F1「未召回」3 道 → **1 道**、F4「只本臂失」**0 道**、
   只本臂得 2 道。13 + 2 = **15 = 非零对数**，且全部同号 —— 也就是说那 15 个非零对**逐条可解释**，
   不是分布尾巴上的噪声。这是本报告里唯一一条"效应量、机制、显著性三者对齐"的结论。
2. **效应随语料变易而缩水**：同一臂从 +6.31pp（n=100）掉到 +3.66pp（n=300），因为基线被 300 题趟
   抬高了 3.6pp（0.9226 → 0.9586，§8.13-2）。门槛 ≥3pp 现在只剩 **0.66pp 余量** ——
   如果按"加干扰篇"把语料规模再扩一档，基线会更高还是更低**未知**，
   所以 D14 之后**不要再动题量来调难度**，那是 §8.13-2 已经证伪过的杠杆。
3. **Recall@5 检不出、nDCG/MRR 检得出**（同一批题、同一臂）：hit@5 的 McNemar 是 2 胜 0 负但
   p_raw = **0.5**（不一致对太少），而 nDCG/MRR 的 p_raw = 0.000473。
   ⇒ **D13 换主判指标这件事现在有对照实验背书了**，不是判断而是测量。
4. **术语/编号题 nDCG@5 = 1.0000（45/45 首槽命中）**；检索 P95 在 300 题上是 **10 523 ms**
   （n=100 的 12 468 ms 的 0.84 倍，样本更大反而更稳）。精排的代价仍然要按"每查询 +10 s"报，
   不能只报精度。

**排期第 5 次校准，第一次是估高**：预估 63 min vs 实际 **48 min**（×0.76）。
上一下调（重排常量 §8.10）之后终于估准方向反了 —— 说明常量没错、错在把"索引重建"当线性放大项。
`A-E3-m3` 那 155 min 没跑，也不必跑：n=100 已证它与 base 三列指标逐位相同、慢 3.2×（§8.10-2）。

**T4 现在算交付**：15 臂真实数字齐（13 臂在 n=300、2 臂在 n=100 + 精排在 n=300）、
Wilcoxon/McNemar + Holm 全表落盘、出口门槛四查三过 + 一条已明确标为"语料侧未解决"。
剩下的两件事**都不在 Phase A**：轨道 B 语料（E2b/A-DICT 仍不可测）与 Phase B 真跑（等 Key）。

---

### 8.15 把"只能加干扰篇"从推测变成实测：三语料规模的天花板曲线

§8.13-2 留了个子决定：基线 Recall@5 = 0.9857 顶破 D13 的 ≤0.95，我判断"只能加干扰篇"。
这话当时是**推测**，现在量完了 —— 而且前提是错的（好消息）：
CMRC train+validation 实际有 **3,251 篇**唯一 passage（D6 原文写的"1,200 篇候选"已复核改掉），
入库只用了 1,000 篇 ⇒ **2,051 篇干扰篇零下载可用**。

**做法**（题集完全不动，只换 `--fixtures`，所以三点之间严格可比）：
把 `spare = 3,251 篇 − 1,000 入库 − 200 留出` 按 doc-key 升序补进语料目录，
每档跑一次 `A-BASE`（300 题、¥0、单臂 13–18 s + 索引 99–141 s）：

| 语料 | Recall@5 | MRR@5 | nDCG@5 | nDCG 余量 | 未召回/210 | P95 ms | 事实 nDCG | 术语 nDCG |
|---|---|---|---|---|---|---|---|---|
| 1,000 篇（现行） | 0.9857 | 0.9495 | 0.9586 | 4.14pp ✗ | 3 | 41.2 | 0.9590 | 0.9573 |
| 2,000 篇 | 0.9762 | 0.9374 | 0.9470 | **5.30pp ✓** | 5 | 38.4 | 0.9498 | 0.9369 |
| **3,051 篇（CMRC 全量）** | **0.9762** ✗ | 0.9282 | 0.9401 | **5.99pp ✓** | 5 | 57.8 | 0.9462 | **0.9176** |

**四条结论**

1. **加干扰篇救得回 nDCG 那半边判据，救不回 Recall 那半边。** nDCG 余量 4.14 → 5.99pp
   ⇒ "≥5pp 余量"在 **2,000 篇**就恢复；但 Recall@5 掉过 0.95pp 之后**卡在 0.9762 一动不动**
   （2,000 与 3,051 同样是 5 道未召回），离 ≤0.95 还差 2.6pp ≈ **再错 5 道题**。
   而 3,251 篇就是 CMRC 的全部 —— 这条判据在 CMRC 上有**下不去的地板**。
2. **地板是结构性的**：§8.13/§8.14 的归因已指出基线未召回的 3 道里有 2 道是
   「**它们**以什么为食？」「**这本书**有什么参考价值？」这类**无字面锚点的篇章内指代题**，
   它们与语料规模无关（加大语料只会更难，不会变得可检）。
   指望"扩语料把 Recall 压到 0.95 以下"是在等一类不会来的错误。
3. **扩语料买到的是"术语/编号"那一列的分辨力**：term nDCG 0.9573 → **0.9176**（−3.97pp），
   factual 只降 1.28pp。区分度恰好加在轨道 B 最关心的一类题型上 —— 这是"现在就把语料拉满"的正面理由。
4. **代价很小**：索引重建 99 s（2,000 篇）/ 141 s（3,051 篇），查询 P95 41 → 58 ms，两档合计 4 min、**¥0**。

**但有一笔必须付的账**：留出协议的定义是"答案 span 不在**入库语料**里"。语料 1,000 → 3,051 之后，
现有 90 道拒答题里 **6 道（6.7%）** 的答案已经字面可得（2,000 篇档 5 道）。检索指标不受影响
（拒答本来不计分），但 **Phase B 的"正确拒答率"会被这 6 道直接压低** ⇒ 不能悄悄换语料。

**三条出路（要拍板）**

| 方案 | 做法 | 代价 | 什么时候用 |
|---|---|---|---|
| **A. 只加干扰篇、题集不动** | `--fixtures` 指到补好的 3,051 篇目录 | 报表须注明"6/90 拒答题在此语料下已可字面作答"；Phase B 拒答率按 84 道口径算 | **Phase A 现在就用**（¥0 / 4 min，术语列立刻有分辨力，且三张历史表仍可比） |
| **B. 全量重建** | `--corpus-docs 3051 --held-docs 200` 重跑 `build_golden_set.py` | 协议自洽，但题集指纹变 ⇒ 与 §8.10/§8.13/§8.14 三张表**全部不可比** | 不推荐（等于愿意重跑全部 15 臂才划算） |
| **C. 语料 3,000 + 留出 251** | `--corpus-docs 3000 --held-docs 251`，拒答集在新语料下重算 | 题集指纹同样变，但**自洽且拒答池更大** | **Phase B 开跑之前必须切到这里**（拒答率是 Phase B 判据，不能带 6 道脏题去烧钱） |

**推荐组合**：Phase A 走 A、报表标脏；Phase B 之前走 C 重建一次（那时还没有任何 Phase B 数字，
不存在可比性损失）。同时把 D13 的 Recall 判据改成"**Recall@5 ≤0.98 且未召回题数 ≥5**"——
0.95 是在"占位语料满分"的恐惧下拍的数，实测表明 CMRC 的地板在 0.9762；
**判据要写量得出的数**，否则每趟实跑都要"未过"一次、每次都得像 §8.10-7 那样解释一遍。

复算：`spare` 按 doc-key 升序补进一个临时语料目录（3,051 个 `cmrc_<DOCID>.md`，正文直接取
`build_golden_set.read_cmrc()` 的 `passages[doc]`，与入库那 1,000 篇同一份文本同一写法），
然后 `python scripts/run_ablation.py --phase A --dataset evaluation/dataset/golden_a_cmrc300.jsonl
--fixtures <该目录> --out <报表目录> --arm A-BASE`。题集一个字不改，所以三点只差语料。

---

### 8.16 Phase B 就绪清单：彩排过了一遍，抓到 smoke 取样一个真 bug

Key 仍 401（`scripts/health_check.py` 于 2026-09-20 复核：6 通过 / 1 警告（Redis 未起，Phase B 不需要）/ 2 失败（LLM 主通路与 JSON 通路都 401））。
所以把"key 到位那天会炸的东西"先全验一遍。

**1) 预检彩排：除了 key，Phase B 没有别的拦路**

拿假 `settings(llm_configured=True)` 走真实 `_require_generation_ready()`：
6 条臂（`B-BASE` / `B-E4-cot` / `B-E4-grounding` / `B-E4-refusal` / `B-E3-rerank` / `B-E6-best`）
**全部通过** —— 矩阵合法、四版 prompt 都在 `core/llm/prompts/v1/answer_*.md` 且已登记、
`top_k=5` 没超【材料10】上限。（顺带修一处口径：§6 T6 那格写的"7 臂"实际是 **6 臂**。）

**2) 抓到一个会让 smoke 白跑的真 bug：`--limit` 是前缀截断**

题集按题型分块排列（事实→术语→拒答），所以 `--limit 15` 取到的是 **15 道全事实题**：

- T5-2 的出口门槛要求 smoke 证明"**拒答题命中模板**" —— 这种 smoke 一道拒答题都遇不到，门槛不可能被验到；
- 更要紧的是**单价标定被系统性高估**：真发生拒答时 `GenerationScorer.score()` 直接 `skipped="refused"`、
  **一次 judge 都不调**（`evaluation/generation_metrics.py:202`），拿纯事实题的单价去预检含 30% 拒答的全量，
  会把其实跑得完的一趟误拒在闸门外。

已改成**按题型分层抽样（最大余数法）**，题型内保持文件顺序 ⇒ 同参数必得同一子集。真实 300 题集上的混合：

| `--limit` | 旧（前缀） | 新（分层） |
|---|---|---|
| 3 | factual×3 | factual×2 refusal×1 |
| 15 | factual×15 | **factual×8 term×2 refusal×5** |
| 60 | factual×60 | factual×33 term×9 refusal×18 |
| 150 | factual×150 | factual×83 term×22 refusal×45 |

副产品：**`--limit` 现在是预算旋钮** —— 想花 150 题的钱就从 300 题集里拿一个占比保真的子集，
不用另存文件。（单测 `test_smoke_limit_stratifies_by_question_type` 钉住混合与确定性。）

**3) 成本口径纠正：§5 那张"7 臂 ≈ ¥57"混了单位，实测便宜得多**

§5 写"每臂 ≈ 2.1M in"，但 2,000 tok/题 × 150 题 = 0.3M —— **2.1M 是 7 臂合计**，
同一张表里 judge 那行又是按臂算的 ⇒ ¥57 这个总数不可用。用本地量到的真实件重
（四版生成模板 276–425 字符；真实 top-5 材料 p50 411 字符、均值 453 ⇒ 一批 ≈ 1,417 tokens）
乘仓库单价表（`MODEL_PRICES["deepseek-flash"] = (2.13, 8.52)` 元/百万 token，低谷 ×0.5）：

| 每臂每题 | token in | token out | ¥/题（高峰） |
|---|---|---|---|
| 生成 | ≈ 1,700（材料 1,417 + 模板与题面） | 假设 250 | **¥0.0058** |
| judge（5 次，材料在 3 次里重复） | ≈ 4,600 | ≈ 400 | **¥0.0132** |
| 可答题合计 | | | **¥0.0190** |
| 拒答题合计（judge 全跳） | ≈ 1,700 | ≈ 250 | **¥0.0058** |

按 150 题分层混合（82+23 可答、45 拒答）算：**每臂 ≈ ¥2.3 → 6 臂 ≈ ¥13.6 高峰 / ¥6.8 低谷**；
**300 题 × 6 臂 ≈ ¥27 高峰 / ¥14 低谷** ⇒ **题量不是预算瓶颈**，§6 T6 的"总花费 ≤¥60"在 300 题上也成立。
⚠️ 但 runner 默认闸门是 `--max-cost-cny 30`：300 题 × 6 臂高峰 ≈ ¥27 已经在闸门口上，
**跑之前按方案明确抬一次**，别指望默认值。（输出 250 tok 是假设，其余都是量出来的；smoke 一跑就换成实测单价。）

**4) key 到位后的命令序列（照抄即可，两步没有例外）**

```bash
python scripts/health_check.py                       # 两条 LLM 检查从 FAIL 变 OK
# ① smoke 15 题（分层，必然含 5 道拒答）→ 打印实测 ¥/题
python scripts/run_ablation.py --phase B --arm B-BASE --limit 15
# ② 用那个单价预检全量，再真跑（6 臂 × 300 题；错峰跑单价减半）
python scripts/run_ablation.py --phase B --limit 300 --unit-cost-cny <①打印的数> --max-cost-cny 40
```

**5) 一条必须写进报表脚注的纪律：拒答会让四指标的分母变小**

`GenerationScorer.score()` 遇到 `refused=True` 直接 `skipped="refused"`、**四个连续指标全记 None**
（只有 `refusal_correct` 进二值列）。于是 `B-E4-refusal` 这类"鼓励拒答"的臂会天然抬高 faithfulness 均值
—— 它不是答得准，是把没把握的题**跳过**了。配对这边由 `compare_arms` 的
`n_pairs / n_used / dropped` 三列如实反映（Phase A 三列都是 210/210/0；Phase B 预期会出现 dropped > 0）。
**读表规则：任何四指标都要连着 `n_used` 一起读**，只报均值等于奖励"少答多拒"。
这也是 §8.12 把 faithfulness/context_recall 与 hit@k/拒答正确率**放进同一个校正族**的理由 ——
单看任何一列都会被这个臂骗到。

**6) Phase B 之前必须先做的两件事（都要他动口）**

1. **拒答题集按 §8.15 的方案 C 重建一次**（语料 3,000 + 留出 251）。理由不是审美：
   现在这 90 道里有 **6 道答案在扩库后的语料里字面可得**，而"正确拒答率"是 Phase B 的判据之一，
   带 6 道脏题去烧钱 = 结论直接坏。
2. **定 Phase B 的题量**（150 省钱、300 才与检索侧同题量）—— 成本上两者都在 ¥60 内（第 3 点已算）。

轨道 B 的 50 题（多跳 30 + 术语 15 + 事实 5）仍然没有：**Phase B 不阻塞**（轨道 A 照样能出四指标与
拒答率），但"多跳"这一类的生成质量结论必须等长文档语料，报表里要按 §8.10-6 标"该题型未测"。

**7) §8.13–§8.15 的数字做过机器复查（不是手抄校对）**

**§8.13–§8.15 与被拆出来的报告 `docs/m3_ablation_report.md` 都做过机器复查（不是手抄校对）**

一次性脚本读落盘 `ablation_summary.json` 现读现比：**246 项、0 不一致**。覆盖 §2 主表 14 行**逐格**
（四指标 / 题型分解 / P95 / Δ / 校正后 p 或"0 非零对"）、§4 五类判据（**从 `per_question` 逐题重算**，
不是复述归因脚本的输出）、§5 全部 p 与非零对与 2/2^m、§6 三点天花板、§7 秒数与倍数。
查到并改掉三处：① §0/§4 原写"90 道库外题各返回 5 篇"⇒ 实测 **87 道 5 篇、3 道因文档级去重剩 4 篇**
（判据是"≥1 篇"所以结论不变，但表述过强）；② `A-SENS-chunk256`@100 的 Δ 由四舍五入后的均值相减得到
**+1.06pp** ⇒ 逐题重算真值 **+1.05pp**（本节第 6 点与 §8.13 同步改掉 —— **不要用表里的显示值相减**）；
③ 查询侧合计 ≈2.5 min ⇒ **3.4 min**（漏了 torch 两臂 24.1 / 60.9 s，见第 4 点）。
另有一处 §5 表格自校：`m=15` 的最小可达 p 写成 3.1e-05，真值 **6.1e-05**（2/2^15）。
脚本没进 CI：**文档不是判分产物，钉死它会逼着人改数据而不是改文档**。要重校就按 §8.16-4 的报表目录现读现比。

---

### 8.17 D15 执行：方案 A 落盘脚本 + 拒答集脏题审计（题集指纹一个字节没动）

`scripts/build_corpus_a.py` 一次做两件事，**都只依赖 `build_golden_set` 已有的判据**（同一份
`read_cmrc` / `split_docs` / `answer_corpus_docs`，不复制规则）：

1. **补语料** `evaluation/fixtures_cmrc_a/` = 3,051 篇 = 现行 1,000 篇 + **2,051 篇干扰篇**
   （= 3,251 篇唯一 passage − 200 篇留出）。落盘前先做一件必须必须做的事：
   **把现行 `fixtures_cmrc/` 的 1,000 个文件逐个与 parquet 比字节**，对不上就退出码 1 且一个字都不写
   —— 这就是 §8.15 那句"不能悄悄换语料"的机器版本（单测 `test_corpus_a_refuses_to_silently_change_corpus` 钉住）。
   同名输出文件内容不一致同样拒写；重复跑幂等（第二次"新写 0 篇"）。
2. **审计拒答集** `evaluation/dataset/refusal_audit_a.json`：90 道里 **6 道（6.7%）** 在 3,051 篇下
   答案重新字面可得 —— `A-refusal-233 / 251 / 252 / 264 / 273 / 292`，每道都记了命中篇章。
   **判据与建题集时同一条：任一答案变体命中即算脏**（只查主答案会少判一批，实测 137 vs 141）。
   这 6 道是从 §8.15 的推测值**独立复算**出来的，两边对上才算数。
   ⇒ Phase B 的"正确拒答率"分母读 **84**；这条在读表纪律里已经有一起（§8.16-6 的"连着 n_used 读"）。

```bash
python scripts/build_corpus_a.py --dry-run     # 只看会写什么、脏几道
python scripts/build_corpus_a.py               # 落盘（需要未入库的 data/cmrc/*.parquet）
python scripts/build_corpus_a.py --audit-only  # 语料已在，只重算审计（零下载、零模型）
```

**复跑口径的变化**：14 臂（13 便宜臂 + `A-E3-base`）**一趟跑完**，所以 Holm 族是 13 × 3 = **39 元**
（不再是"13 臂趟 36 元 + 精排趟 3 元"），§8.14 那条"读原始 p 再乘 42"的预注册判据在 A 口径下**不再需要**
—— 精排与基线同趟，`p_adjusted` 直接就是族里的答案。runner 预估 6,976 s（≈116 min），
已知常量的老问题还在：bge-large 那组按 265 s/1k 篇估 = 808 s，1,000 篇实测 1,314.7 s ⇒ 3,051 篇这趟
真实量级是 **≈66 min**，整趟实际会落在 2~3 h（第 6 次校准，跑完回写 §7）。

**这趟复跑没跑完，原因在机器不在代码**。9 个 fastembed 臂落盘后 `A-E3-base` 抛
`OSError: 页面文件太小，无法完成操作。(os error 1455)`（在 `from_pretrained` 里，被
`rag/reranker.py:198` 包成 `RerankerError`），runner 按设计把失败记进 `arm_A-E3-base.json` 的
`error` 字段并继续跑其余臂；随后进程在装载 bge-base 权重时被系统终止。当时物理内存只剩
**0.9 GB / 15.9 GB** —— 1,000 篇那趟能过是因为同时驻留的东西少。
⇒ **复跑等腾内存或抬页面文件再来**；⚠️ 后台包装器报的 `exit 0` 是它自己那句 `echo` 的返回值，
**不能当成功看**（判存活要看 `ablation_summary.json` 在不在 + `Get-CimInstance Win32_Process`）。

**但语料目录的等价性已经被这一趟验掉了**：新 `fixtures_cmrc_a/` 上的 `A-BASE` 与 §8.15 用 TEMP 目录
跑的那趟 —— 300 题 **top-5 逐题相同（300/300）**，四指标与题型分解**逐位相同**
（Recall@5 0.9761904762 / MRR 0.9281746032 / nDCG 0.9400589458 / 术语 0.9175886261 / 事实 0.9461872148），
P95 54.9 vs 57.8 ms（同配置抖动，见 §8.16-3）。⇒ 2,051 篇干扰篇补得对，方案 A 的语料可以直接用。

**复跑本身：2026-09-20 拍"先不跑"**，主表留在 1,000 篇口径，A 只作为已备好的语料与协议存在。

**语料目录不入库，入库的是 doc-key 清单**（3,051 篇 = 14 MB 文本；进 git 历史就撤不掉）：
`scripts/build_corpus_a.py` 落盘语料的同时写 `evaluation/dataset/corpus_a_manifest.json`
（55 KB，含 3,051 个 doc-key 与指纹 `2b933d331576`），`.gitignore` 里把 `evaluation/fixtures_cmrc_a/` 排掉。
之后 `--audit-only` 会**逐 key 比对目录与清单**（缺篇/多篇都退出码 1）—— 这条与"逐字节复核现行 1,000 篇"
是同一族防护：一个管正文，一个管集合。代价说清楚：**新克隆没有 `data/cmrc/*.parquet` 就再生不出 A 口径语料**，
但题集指纹、拒答审计与三点天花板曲线都不依赖它（都在已入库的产物里）。

---

## 9. 对外表述口径（等真实数字填进来，现在只有骨架）

> **通用 RAG Agent 性能优化与消融评测系统（Trinity M3）** | LangGraph、FastAPI、sqlite-vec、BM25、DeepSeek API | 个人项目
> - 在已交付的多 Agent 平台（Python 50,903 行 + 前端 `web-react/src` 14,110 行；全仓离线用例 1,051 条通过 / 收编 1,055 条，抄进对外材料前要按下面的口径注复算）上增量实现 RAG 消融评测层：嵌入/融合/分块/重排/Prompt **五类组件配置驱动可插拔**，runner 以「与基线恰好差一个字段」的强制校验保证严格单变量，每臂独立临时索引库互不污染
> - 构建 150 题中英双源 Golden Set（CMRC2018 公开基准 100 + 自建能源/弱电规程 50，覆盖事实/术语/多跳/库外拒答四类），**拒答题用「留出 200 篇 + 伪拒答过滤」协议构造**（实测 16.8% 的留出题答案 span 本来就落在入库语料里，不过滤即污染拒答率）；**检索侧另按同一份语料扩出 300 题副集专治统计功效**（§8.13）。检索指标用纯函数零成本实现，生成指标**按 RAGAS 口径自实现**四评分器（未引入 ragas：其 langchain-community 依赖与项目 langchain-core 1.x 冲突、scikit-network 二进制被本机应用控制策略拦截）
> - 跑通 15 组严格单变量对照（轨道 A，300 题 / 1,000 篇 1000-way 检索）：〔检索侧已实测完 —— 精排 nDCG@5 **0.9586→0.9952（+3.66pp）**、Wilcoxon 原始 p=0.000473（Holm 42 元族校正后 p=0.0199 ✓），但检索 P95 从 **41 ms → 10 523 ms（×255）**；纯向量融合相对混合检索 nDCG@5 **−4.17pp**（p=0.0130 ✓，16 个非零对里 13 对是它独有的失败）；纯 BM25 0.9654 **反而优于**混合 0.9586；换更大 embedding（bge-small→base→large）只买到 +1.0pp 且 P95 41→86→**309 ms** ⇒ 对外材料里不写"更大模型更准"。生成侧四指标〔待 Phase B：faithfulness x.xx→x.xx、库外正确拒答率 xx%→xx%〕〕
> - **刻意不做配对显著性检验，只报 Δ 与逐题判据**（理由：4~6 臂 × 50 题的样本量给不出可信 p 值，与其报一个伪精确的 `p=0.031` 不如老老实实报 `delta` 与 `rel_lift`；决策与字段留档见 `evaluation/ablation.py:735-740`）+ **两类可复算的失败判据**（F1 未召回 = `hit@k==0`；F2 召回未居首 = `hit@k==1 且 mrr<1`，见 `scripts/analyze_ablation_failures.py`；原 F3~F5 已于 2026-09-21 连同依赖移除）+ 场景化选型建议。消融总表与两类归因现由控制台 `EvalAblationPage` 读 `/eval/ablation-report` 展示（原 Streamlit「任意两臂逐题 diff」对比页随 `ui/` 于 2026-09-27 删除，读取端 `evaluation/ablation.py:1400` 的 `diff_rows()` 今天无消费者，见账本 R-13）
> - **已知局限（主动写）**：judge 与生成同源（DeepSeek 家族）存在自偏好；**生成侧仍是 150 题量级**（每题 6 次 LLM 调用，成本随题数线性），只有检索侧扩到 300 题 —— 轨道 A 实测：n=100 时 8 个非零对的 Wilcoxon 最小可达 p=0.0078，**任何结果都过不了 42 元 Holm 族**；扩到 300 题后同一批臂里 `vector_only` 的退化（p=0.013 ✓）与精排的收益（原始 p=0.000473 ✓）双双被检出，**但轨道 A 语料已到顶**（CMRC 全部 3,251 篇都用上，基线 Recall@5 有 0.9762 的地板，术语/编号题是唯一还在涨区分度的一类）；未达显著的差异一律标注为 n.s. 而非"提升"
>
> **口径注（2026-10-04 复算）**：① 上面第 3、5 条里的 p 值（0.000473 / 0.0199 / 0.0130 / 0.0078 / 0.3958）**全部是 2026-09-21 检验删除之前的历史留档**，今天的代码不产 p 值（落盘字段 `"significance_removed": true`，`evaluation/ablation.py:775`），它们只用来解释"为什么当初这么判"，别当成当前输出；② 规模数字给可复算口径 ——
> `git ls-files '*.py' | xargs wc -l` = **50,903**、
> `git ls-files web-react/src | grep -E "\.(ts|tsx)$" | xargs wc -l` = **14,110**、
> `python -m pytest --collect-only -q` 逐文件计数求和 = **本趟 1,055 条收编**（全量跑 1,051 passed / 4 skipped，skip 那 4 条要 torch）。
> ⚠️ 这三个数里只有两行代码量相对稳定，**用例数是每加一条就变的量**（这一段上一版写的「857」就是这么过期的，
> 而且是没人发现）⇒ 抄进对外材料前先跑上面那条命令现取，并在句子里带上"截至 <日期>"；
> 行数与用例数都不许当常量留着复用。原先写的「21K 行」按四种口径都复算不出来，已作废。

投法（沿用 v3 §11，但重心按 M3 实际）：
- RAG/大模型应用岗 → 检索消融 + nDCG/MRR 口径 + 成本权衡
- 通用 Agent 岗 → 先讲 M1/M2 的三角色编排与 6 个工具，再讲 M3 的评测层（E5 工具指标 P1 补上后更硬）
- 架构/平台岗 → 配置驱动可插拔 + 五层解耦 + 每臂隔离索引 + 断点续跑
