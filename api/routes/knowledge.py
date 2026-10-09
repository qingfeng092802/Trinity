"""知识库端点（m2_design.md §3.1 / T03）：上传、列表、详情、删除、重试、检索、概览。

路由纪律（设计 §4 / §7.5）：

* 全部用 ``def``（同步）：文件保存是同步 IO、``/search`` 可能触发 embedding
  模型首次加载——都不允许阻塞事件循环，交给 FastAPI 线程池；
* ``service is None``（rag 依赖缺失/初始化失败）→ 统一 503 ``rag_unavailable``；
* ``RagError`` → 按错误信息映射；``FingerprintMismatchError`` → 409；
* 上传是 multipart（``file`` 字段 + ``overwrite`` query 参数，A2）。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from api.deps import get_knowledge_service
from api.errors import ApiError, ErrorCode
from api.schemas import (
    DocumentListResponse,
    DocumentUploadResponse,
    DocumentView,
    KnowledgeOverviewResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RetryResponse,
    SearchHitView,
    to_cn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _service_or_503():
    """取知识库服务；不可用统一抛 503 ``rag_unavailable``。"""
    service = get_knowledge_service()
    if service is None:
        raise ApiError(
            ErrorCode.RAG_UNAVAILABLE,
            "知识库服务不可用（rag 依赖缺失或初始化失败）",
            status=503,
        )
    return service


def _view(record) -> DocumentView:
    """``DocumentRecord`` → ``DocumentView``（时间统一北京时间）。"""
    return DocumentView(
        document_id=record.document_id,
        filename=record.filename,
        size_bytes=record.size_bytes,
        format=record.format,
        status=record.status,
        error_stage=record.error_stage,
        error_message=record.error_message,
        chunk_count=record.chunk_count,
        token_count=record.token_count,
        embedding_fingerprint=record.embedding_fingerprint,
        created_at=to_cn(record.created_at),
        updated_at=to_cn(record.updated_at),
        indexed_at=to_cn(record.indexed_at) if record.indexed_at else None,
    )


def _map_rag_error(exc: Exception) -> ApiError:
    """``RagError`` → 业务 ``ApiError``（按 message 关键字映射错误码）。"""
    from rag.exceptions import FingerprintMismatchError, ParserError

    message = str(getattr(exc, "message", exc))
    if isinstance(exc, FingerprintMismatchError):
        return ApiError(ErrorCode.FINGERPRINT_MISMATCH, message, status=409)
    if "知识库服务不可用" in message or "rag 依赖不可用" in message:
        return ApiError(ErrorCode.RAG_UNAVAILABLE, message, status=503)
    if "仅 failed 文档可重试" in message or "重试状态竞争" in message:
        return ApiError(ErrorCode.INVALID_REQUEST, message, status=422)
    if "同名文档已存在" in message:
        return ApiError(ErrorCode.DUPLICATE_DOCUMENT, message, status=409)
    if "不支持的文档格式" in message:
        return ApiError(ErrorCode.UNSUPPORTED_FORMAT, message, status=422)
    if "索引队列已满" in message:
        return ApiError(ErrorCode.QUEUE_FULL, message, status=429, **{"Retry-After": "5"})
    if "文档不存在" in message:
        return ApiError(ErrorCode.DOCUMENT_NOT_FOUND, message, status=404)
    if isinstance(exc, ParserError):
        return ApiError(ErrorCode.UNSUPPORTED_FORMAT, message, status=422)
    return ApiError(ErrorCode.INTERNAL_ERROR, message, status=500)


# --------------------------------------------------------------------------- #
# 7 个端点
# --------------------------------------------------------------------------- #
@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=201,
    summary="上传文档（multipart，受理后异步索引）",
)
def upload_document(
    request: Request,
    file: UploadFile = File(description="文档文件（pdf/md/txt）"),
    overwrite: bool = Query(default=False, description="同名文档已存在时是否覆盖重建"),
) -> DocumentUploadResponse:
    """上传一份文档并进入异步索引队列（五阶段状态机见设计 §7.2）。"""
    service = _service_or_503()
    filename = file.filename or "unnamed"
    # 大小校验（超限直接 422，不落盘）
    settings = service.settings
    max_bytes = settings.knowledge_max_file_mb * 1024 * 1024
    payload = file.file.read()
    if len(payload) > max_bytes:
        raise ApiError(
            ErrorCode.FILE_TOO_LARGE,
            f"文件 {len(payload)} 字节超过上限 {settings.knowledge_max_file_mb} MB",
            status=422,
        )
    if not payload:
        raise ApiError(ErrorCode.INVALID_REQUEST, "上传文件为空", status=422)

    # 先落临时文件，service.ingest 负责拷贝到正式位置
    import tempfile
    from pathlib import Path

    tmp_dir = settings.knowledge_dir / "files"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".upload", delete=False)
    try:
        handle.write(payload)
        handle.close()
        summary = service.ingest(filename, Path(handle.name), overwrite=overwrite)
    except Exception as exc:  # noqa: BLE001 - 统一映射后重抛
        raise _map_rag_error(exc) from exc
    finally:
        Path(handle.name).unlink(missing_ok=True)

    from core.llm.pricing import now

    return DocumentUploadResponse(
        document_id=summary["document_id"],
        filename=summary["filename"],
        status="pending",
        upload_at=now(),
        status_url=str(request.url.path) + f"/{summary['document_id']}",
        warnings=summary["warnings"],
    )


@router.get("/documents", response_model=DocumentListResponse, summary="文档列表")
def list_documents() -> DocumentListResponse:
    """全部文档（创建时间倒序）。"""
    service = _service_or_503()
    records = service.list_documents()
    return DocumentListResponse(items=[_view(record) for record in records], total=len(records))


@router.get("/documents/{document_id}", response_model=DocumentView, summary="文档详情")
def get_document(document_id: str) -> DocumentView:
    """单文档详情（索引进度轮询用；状态机 pending→parsing→chunking→embedding→ready）。"""
    service = _service_or_503()
    record = service.get_document(document_id)
    if record is None:
        raise ApiError(ErrorCode.DOCUMENT_NOT_FOUND, f"文档不存在：{document_id}", status=404)
    return _view(record)


@router.delete("/documents/{document_id}", summary="删除文档")
def delete_document(document_id: str) -> JSONResponse:
    """删除文档及其全部 chunk 与向量（指纹基线不动）。"""
    service = _service_or_503()
    try:
        deleted = service.delete_document(document_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_rag_error(exc) from exc
    if not deleted:
        raise ApiError(ErrorCode.DOCUMENT_NOT_FOUND, f"文档不存在：{document_id}", status=404)
    return JSONResponse(status_code=200, content={"document_id": document_id, "deleted": True})


@router.post(
    "/documents/{document_id}/retry",
    response_model=RetryResponse,
    summary="重试失败文档",
)
def retry_document(document_id: str) -> RetryResponse:
    """``failed → pending`` 并重新入队（从 parsing 全量重跑，不做阶段断点）。"""
    service = _service_or_503()
    try:
        record = service.retry_document(document_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_rag_error(exc) from exc
    return RetryResponse(
        document_id=document_id,
        status="pending",
        queued=record is not None and record.status == "pending",
    )


@router.post("/search", response_model=KnowledgeSearchResponse, summary="知识库检索测试")
def search(payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    """BM25 + 向量混合检索（分数为单次查询内归一化的相对分，L5）。

    空库返回 ``200 + hits: []``（不是报错）；模型指纹不一致返回 409
    ``fingerprint_mismatch``（提示全量重索引）。
    """
    service = _service_or_503()
    weights = None
    if payload.bm25_weight is not None and payload.vector_weight is not None:
        weights = (payload.bm25_weight, payload.vector_weight)
    started = time.perf_counter()
    try:
        hits = service.search(payload.query, payload.top_k, weights=weights)
    except Exception as exc:  # noqa: BLE001
        raise _map_rag_error(exc) from exc
    took_ms = int((time.perf_counter() - started) * 1000)
    return KnowledgeSearchResponse(
        query=payload.query,
        top_k=payload.top_k,
        took_ms=took_ms,
        hits=[
            SearchHitView(
                document_name=hit.document_name,
                chunk_seq=hit.chunk_seq,
                start_char=hit.start_char,
                end_char=hit.end_char,
                text=hit.text,
                bm25_score=hit.bm25_score,
                vector_score=hit.vector_score,
                score=hit.score,
            )
            for hit in hits
        ],
    )


@router.get("/overview", response_model=KnowledgeOverviewResponse, summary="知识库概览")
def overview() -> KnowledgeOverviewResponse:
    """文档/chunk/token 计数与当前指纹（控制台知识库页数据源）。"""
    service = _service_or_503()
    try:
        data = service.overview()
    except Exception as exc:  # noqa: BLE001
        raise _map_rag_error(exc) from exc
    return KnowledgeOverviewResponse(
        document_count=data["document_count"],
        chunk_count=data["chunk_count"],
        token_count=data["token_count"],
        ready_count=data["ready_count"],
        failed_count=data["failed_count"],
        indexing_count=data["indexing_count"],
        fingerprint=data["fingerprint"],
        vector_backend=data["vector_backend"],
        embedding_model=data["embedding_model"],
        last_indexed_at=to_cn(data["last_indexed_at"]) if data["last_indexed_at"] else None,
        # K3：上限随概览一起给，前端不在界面上写死数字（也就不用跟 config 对账）。
        max_file_mb=service.settings.knowledge_max_file_mb,
        # R-03：白名单同理（值来自 rag.service.supported_formats()，与 422 的判定同一份）。
        supported_formats=data["supported_formats"],
    )


__all__ = ["router"]
