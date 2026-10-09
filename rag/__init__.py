"""RAG 知识库包：解析 → 切分 → 向量化 → 混合检索（M2）。

**懒加载纪律（设计文档 §7.4 G4 的生命线）**：

本 ``__init__.py`` **禁止** import 任何子模块。``sentence-transformers`` /
``torch`` / ``sqlite_vec`` / ``jieba`` 等重依赖只允许在各自模块的**函数体内**
import——未装 RAG 依赖的环境必须还能正常启动平台、跑通 5 个旧工具，
``/health`` 的 rag 检查项 fail 只贡献 degraded。

各模块职责（T01 只落 types / exceptions，其余在 T02/T03 实现）：

* :mod:`rag.types`        —— 数据类：ParsedBlock / ParsedDocument / Chunk / SearchHit
* :mod:`rag.exceptions`   —— 异常层级：RagError 基类 + 五个子类
* :mod:`rag.parsers`      —— 文档解析（T02）
* :mod:`rag.splitter`     —— 结构感知切分（T02）
* :mod:`rag.embedder`     —— EmbeddingProvider 协议与实现（T02）
* :mod:`rag.vector_store` —— VectorStore 协议与实现（T02）
* :mod:`rag.bm25`         —— BM25 内存索引（T03）
* :mod:`rag.retriever`    —— 混合检索（T03）
* :mod:`rag.reranker`     —— 交叉编码精排（M3 · T3-1）
* :mod:`rag.citation`     —— 引用编号解析/校验与拒答判定（M3 · T5）
* :mod:`rag.answer`       —— 直接生成通路 RagAnswerer（M3 · T5）
* :mod:`rag.ingest`       —— 索引 worker（T02）
* :mod:`rag.service`      —— KnowledgeService 门面（T03）
"""

#: 包版本（与平台里程碑对齐）
__version__ = "0.2.0"

__all__ = ["__version__"]
