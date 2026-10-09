# M2 · RAG 知识库：从零复现手册

> 本手册覆盖 Trinity 多 Agent 平台的 RAG 知识库能力（M2）：上传企业文档 → 自动索引 →
> HTTP 检索 → Agent 通过 `knowledge_search` 工具引用作答 → 检索质量评测。
> 全程本地运行：embedding 用 bge-small-zh-v1.5（fastembed/ONNX），**零 API 成本、可断网**。

## 0. 前置条件

| 依赖 | 说明 |
|------|------|
| Python 3.13+（项目 venv） | `pip install -e ".[dev]"` 或 `uv sync` |
| rag 依赖 | `fastembed` / `sqlite-vec` / `jieba` / `rank-bm25`（pyproject 内置） |
| bge ONNX 权重 | 首次运行自动下载到 `FASTEMBED_CACHE_DIR`（约 100MB；也可用 hf-mirror 预下载） |
| 无需 GPU / 无需 LLM Key | 检索与评测零 LLM 调用；只有跑 Agent 任务才需要 `LLM_API_KEY` |

## 1. 配置（`.env` 关键项）

```ini
KNOWLEDGE_DIR=data/knowledge          # 文档与向量库落盘目录
EMBEDDING_PROVIDER=local              # M2 仅支持 local
EMBEDDING_MODEL_NAME=bge-small-zh-v1.5
EMBEDDING_DIM=512                     # ⚠️ 改维度/模型名 → 指纹变化 → 必须全量重索引
CHUNK_SIZE=500                        # token 窗口
CHUNK_OVERLAP=80
BM25_WEIGHT=0.4                       # 混合检索权重（与 VECTOR_WEIGHT 和 ≈1）
VECTOR_WEIGHT=0.6
VECTOR_STORE_BACKEND=sqlite-vec       # spike① 结论：CPython 3.14 下全链路通过
FASTEMBED_CACHE_DIR=data/models/fastembed_cache
```

## 2. 启动与上传

```bash
# 起 API（含 IndexWorker 索引线程；rag 依赖缺失时平台照常启动、/knowledge/* 返回 503）
python scripts/start_api.py

# 上传文档（五格式白名单：pdf / md / docx / txt / html；单文件 ≤ KNOWLEDGE_MAX_FILE_MB）
curl -F "file=@综合布线施工规范.md" http://127.0.0.1:8000/knowledge/documents
# → 201 {"document_id":"doc-xxxx","status":"pending",...}

# 轮询索引状态：pending → parsing → chunking → embedding → ready（失败隔离，单文档 failed 不影响其他）
curl http://127.0.0.1:8000/knowledge/documents/doc-xxxx
# 同名覆盖重建：加 ?overwrite=true；失败文档重试：POST /knowledge/documents/{id}/retry
```

## 3. 检索

```bash
curl -X POST http://127.0.0.1:8000/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"query":"六类线弯曲半径要求","top_k":3}'
# → 200 {"hits":[{score, bm25_score, vector_score, document_name, chunk_seq, text}...], "took_ms":...}
# 每请求可覆盖权重：{"query":"...","bm25_weight":1.0,"vector_weight":0.0}
```

语义：

* **混合检索**：BM25（jieba 分词）与向量（bge）双路各召回 top_k×4 → 候选集内 min-max 归一化 → 加权融合；
* **空库返回 200 + `hits: []`**（不是错误）；
* **指纹双闸**：改 `EMBEDDING_MODEL_NAME`/`EMBEDDING_DIM` 后检索入口返回 409 `fingerprint_mismatch`，
  提示全量重索引（换模型 ≠ 换 App，向量必须重建）；
* **`/health` 特判**：rag 组件故障只贡献 `degraded`（HTTP 200），平台其余功能照常。

## 4. Agent 工具（knowledge_search）

任务提交带 `use_tools: true` 时，executor 可调用第 6 个内置工具：

```
POST /tasks  {"task":"根据知识库说明六类线施工规范","use_tools":true}
```

* planner 提示词：要求依据知识库作答的任务会写明「用 knowledge_search 检索知识库获取〈X〉」；
* executor 提示词：引用检索结果必须标注来源（文档名 + 片段位置），失败时说明原因继续可完成步骤；
* 每次调用完整落入 trace（`TraceStore.for_task`）：query / top_k / 结果 / 来源引用 / 耗时；
* 单独调用：`POST /tools/knowledge_search/invoke` `{"args":{"query":"...","top_k":5}}`；
* 服务未注入 / 空库 / 指纹不匹配 → `status="failed"` + 明确原因（executor 拿到后不崩）。

## 5. 评测（零 LLM 调用，可断网跑）

```bash
# 默认三组权重对照（0.3:0.7 / 0.4:0.6 / 0.5:0.5），报告落 evaluation/reports/
python scripts/eval_retrieval.py

# 追加极端对照组（验证混合生效：组间两路均分不同 + 融合排序随权重变化）
python scripts/eval_retrieval.py --weights 0.3:0.7 --weights 0.4:0.6 --weights 0.5:0.5 \
    --weights 1.0:0.0 --weights 0.0:1.0

# 自定义数据集 / 种子文档
python scripts/eval_retrieval.py --dataset <jsonl> --fixtures <dir>
```

* 数据集格式（jsonl）：`{"id","type","query","expect_document","expect_keywords"}`；
  命中判定 = 文档匹配 **且** 含任一期望关键词（双条件，避免文档级虚高）；
* 指标：top-1 / top-3 / hit@5 / MRR + 逐条命中明细；
* **G2 出口门槛**：参照组 0.4:0.6 的 top-3 命中率 ≥ 80%（CLI 退出码 0=过 / 1=不过）。

**占位语料基线**（2026-09-17，4 份规范摘要 × 24 chunks × 26 条用例，真实 bge 模型）：
top-1 = top-3 = hit@5 = 100%，MRR = 1.0，G2 ✅。⚠️ 占位语料区分度低，此分数只证明
**链路正确**；正式效果指标待用户标注集（3-5 份真实弱电文档 + 自标 20+ 条，设计 A6）替换后出终版。

## 6. T01 Spike 结论（选型依据）

| # | 结论 | 依据 |
|---|------|------|
| ① | **sqlite-vec 转正**（弃 Chroma 主路径） | CPython 3.14 下 vec0 建表/插查/覆盖全通过；单文件与业务库同盘备份 |
| ② | **fastembed(ONNX) 转正**（sentence-transformers 被本机 Windows 应用控制策略拦截：sklearn 未签名 pyd） | dim=512、L2 归一、首查 ~0.1s，懒加载不拖启动 |
| ③ | 本地权重缓存 | `%TEMP%/fastembed_cache`（hf-mirror.com 下载）→ 项目 `data/models/fastembed_cache` |

## 7. 已知限制

1. **jieba 分词粒度**：「六类线」被切成 `['六类','线']`，BM25 是 token 级匹配，领域术语
   精确命中不保证（探针实测）。缓解：P2 加 `jieba.add_word` 自定义词典。
2. **归一化口径**：min-max 在单次查询候选集内做，不同查询间分数**不可比**（相对排序才有意义）。
3. **单 chunk > 480 tokens 仅告警不截断**：截断会破坏 `text == doc.text[start:end]` 切片不变量；
   bge max_seq 512 > 500 实际安全，fastembed 内部也会兜底截断。
4. **不做的**：reranker（M2 范围外，bge-reranker 留 M3+）、权限过滤、增量索引（重建即幂等）。
5. **索引吞吐**：50 页 PDF 实测 6.72s（指标 120s，18 倍余量，`scripts/bench_index.py`）。
