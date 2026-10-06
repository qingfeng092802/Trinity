"""knowledge_search：检索本地知识库并返回带来源引用的相关片段（T04 · 第 6 个内置工具）。

契约（m2_design.md §1.5 / §7.4）：

* **模块级零 rag import**——RAG 依赖的探活在 ``KnowledgeService`` 内部完成，
  本模块只认「被注入的服务对象」；未装 rag 依赖的环境注册照常成功、
  调用时返回结构化失败字符串，平台其余 5 个工具照常（懒加载纪律 G4）；
* 服务注入走 :func:`set_knowledge_service`（由 ``api.deps.get_tool_registry``
  与 ``api.runner.build_runner`` 在装配工具注册表后调用）；
* **失败字符串化**：服务未注入 / 空库 / 指纹不匹配 / 检索异常一律抛
  :class:`KnowledgeSearchError`，由 ``ToolRegistry.call`` 兜底编码为
  ``status="failed"``——异常绝不穿透到 executor（与 calculator 同模式）；
* **引用行完整优先**：单条片段原文截 500 字符；总长超预算时按档位收缩
  原文预算（500→300→150→0），引用行（【n】文档名 · chunk …）始终保留，
  保证 ``ToolCallRecord.result`` 不会被 registry 的 4000 字符截断腰斩。
"""

from __future__ import annotations

import logging
import threading
from typing import Annotated, Any

from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec
from core.tools.task_context import clamp_top_k, default_top_k, task_top_k

logger = logging.getLogger(__name__)

#: 检索条数的默认值 —— **读部署配置**，不写死数字（2026-09-26 之前这里写的是字面量 5，
#: 而 ``settings.knowledge_top_k`` 是个零消费者的死字段：两份口径、其中一份还是摆设）。
#: ⚠️ Python 的默认参数在 import 期只求值一次 ⇒ 改 ``KNOWLEDGE_TOP_K`` 要重启进程才生效。
_DEFAULT_TOP_K = default_top_k()

#: 检索问题的长度上限（§1.5 契约：1..1000 字符）
MAX_QUERY_LENGTH = 1000

#: 单条片段原文的展示上限（字符）
MAX_SNIPPET_LENGTH = 500

#: 工具结果的总长预算（字符）——留出余量，避免被 registry 的 RESULT_LIMIT=4000 截断
RESULT_BUDGET = 3800

#: 总长超预算时的原文收缩档位（字符），0 表示只保留引用行
SNIPPET_BUDGET_LADDER: tuple[int, ...] = (500, 300, 150, 0)

# --------------------------------------------------------------------------- #
# 服务注入（模块级单例；api 层装配时调用 set_knowledge_service）
# --------------------------------------------------------------------------- #
_SERVICE: Any | None = None
_SERVICE_LOCK = threading.Lock()


def set_knowledge_service(service: Any | None) -> None:
    """注入（或用 ``None`` 清除）知识库服务实例。

    由 ``api.deps.get_tool_registry`` 与 ``api.runner.build_runner`` 在
    ``load_builtin_tools`` 之后调用——注册先于注入（T04 子步骤 4）。
    测试用它做显式隔离（注入/清除配对出现）。
    """
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service


def _get_service() -> Any | None:
    """取当前注入的知识库服务（未注入返回 ``None``）。"""
    with _SERVICE_LOCK:
        return _SERVICE


class KnowledgeSearchError(ValueError):
    """知识检索失败（服务不可用 / 空库 / 指纹不匹配 / 检索异常）。"""


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #
def knowledge_search(
    query: Annotated[
        str,
        Field(description="检索问题，1..1000 字符；用自然语言描述要查的知识点"),
    ],
    top_k: Annotated[int, Field(ge=1, le=20)] = _DEFAULT_TOP_K,
) -> str:
    """检索本地知识库并返回带来源引用的相关片段（文档名+chunk 位置+原文+相关度）。

    ``top_k`` 两件事分开看：

    * **默认值**来自 :func:`core.tools.task_context.default_top_k`
      （= ``settings.knowledge_top_k``，改 env 要重启进程 —— 默认参数 import 期只求值一次）；
    * **这条任务配了上限**时，模型要的量被夹到上限（:func:`clamp_top_k`）。
      夹的时候会在结果开头明说，因为 trace 里记的 ``tool_args`` 是**模型原话**
      （那是"模型要了几条"），而命中数是夹完之后的 —— 两个数并排着不解释，
      下一个人只会以为检索坏了。
    """
    asked = int(top_k)
    effective = clamp_top_k(asked, task_top_k())
    cleaned = query.strip()
    if not cleaned:
        raise KnowledgeSearchError("检索失败：检索问题不能为空")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise KnowledgeSearchError(
            f"检索失败：检索问题过长（{len(cleaned)} 字符，上限 {MAX_QUERY_LENGTH}）"
        )

    service = _get_service()
    if service is None:
        raise KnowledgeSearchError(
            "检索失败：知识库服务不可用（RAG 依赖未安装或服务未初始化），请检查部署"
        )

    try:
        from rag.exceptions import FingerprintMismatchError  # noqa: PLC0415 - 懒加载纪律 §7.4
    except Exception as exc:  # noqa: BLE001 - rag 依赖缺失也走结构化失败
        raise KnowledgeSearchError(f"检索失败：RAG 依赖不可用（{exc}）") from exc

    try:
        hits = service.search(cleaned, effective)
    except FingerprintMismatchError as exc:
        raise KnowledgeSearchError(f"检索失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 检索层异常统一字符串化，不让 executor 崩
        raise KnowledgeSearchError(f"检索失败：{exc}") from exc

    if not hits:
        if _knowledge_base_empty(service):
            raise KnowledgeSearchError("检索失败：知识库为空，请先上传文档（POST /knowledge/documents）")
        raise KnowledgeSearchError("检索失败：没有检索到相关片段，请换个问法或补充更多文档")

    text = _format_hits(hits)
    if effective < asked:
        text = (
            f"（本任务设了检索上限 {effective} 条：模型请求 {asked} 条已夹到 {effective}）\n"
            + text
        )
    return text


def _knowledge_base_empty(service: Any) -> bool:
    """判断库是否为空（chunks 表计数失败时按「非空」处理，报「未命中」更安全）。"""
    try:
        return int(service.database.count_chunks()) == 0
    except Exception:  # noqa: BLE001 - 探测失败不影响失败语义，只影响措辞
        return False


def _format_hits(hits: list[Any]) -> str:
    """把 ``SearchHit`` 列表渲染成带来源引用的文本（引用行完整优先）。"""
    for budget in SNIPPET_BUDGET_LADDER:
        text = _render(hits, budget)
        if len(text) <= RESULT_BUDGET:
            return text
    return _render(hits, 0)  # 兜底：极端情况下只保留引用行


def _render(hits: list[Any], snippet_budget: int) -> str:
    """按给定原文预算渲染结果；``snippet_budget=0`` 时只保留引用行。"""
    lines = [f"共命中 {len(hits)} 条相关片段："]
    for index, hit in enumerate(hits, start=1):
        citation = getattr(hit, "citation", None)
        cite_line = citation() if callable(citation) else (
            f"{hit.document_name or hit.document_id} · chunk {hit.chunk_seq}"
            f"（字符 {hit.start_char}-{hit.end_char}）"
        )
        # ↑ 这条兜底支**故意不套 safe_document_label**：本模块的设计纪律是"模块级零 rag
        #   import"（见文件头），而它只在 hits 不是真 SearchHit（测试替身）时才跑到 ——
        #   生产路径上 SearchHit 一定有 citation()，走的是上面那条已清洗的分支。
        lines.append(
            f"【{index}】{cite_line}｜相关度 {hit.score:.2f}"
            f"（BM25 {hit.bm25_score:.2f} / 向量 {hit.vector_score:.2f}）"
        )
        if snippet_budget > 0:
            snippet = hit.text[:snippet_budget]
            if len(hit.text) > snippet_budget:
                snippet += "…"
            lines.append(snippet)
    return "\n".join(lines)


def register(registry: ToolRegistry) -> ToolSpec:
    """把 knowledge_search 注册进给定注册表。"""
    return registry.register(
        knowledge_search,
        name="knowledge_search",
        description=(
            "检索本地知识库（用户上传的文档）。任务需要依据企业内部文档/上传资料"
            "作答时必须调用本工具，并基于返回片段与来源引用作答"
        ),
        danger_level="low",
        timeout=10,
        retry=1,
    )


__all__ = [
    "MAX_QUERY_LENGTH",
    "KnowledgeSearchError",
    "knowledge_search",
    "register",
    "set_knowledge_service",
]
