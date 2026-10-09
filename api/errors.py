"""统一错误模型：错误码枚举 + ``ApiError`` + 三个异常处理器 + ``request_id``。

统一响应体（PRD §P0-1）::

    { "detail": { "code": "task_not_found", "message": "任务不存在：task-xxx",
                  "request_id": "a1b2c3d4e5f6" } }

为什么自己定义 ``ApiError`` 而不是到处 ``raise HTTPException``：
``HTTPException`` 的 ``detail`` 是一个自由形态字段，各路由想写什么写什么，
客户端没法稳定地 ``switch (detail.code)``。统一成枚举 + 固定信封之后，
``code`` 是可穷举的契约，``message`` 只负责给人看。

``request_id`` 用 ``ContextVar`` 而不是塞进 ``request.state``：worker 线程里
记日志时也想要这个 id，而 ``request.state`` 拿不到（线程里没有 request 对象）。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from enum import Enum
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

#: 当前请求的 id（中间件写入，异常处理器与日志读取）
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """生成一个新的请求 id（12 位 hex，够短也够唯一）。"""
    return uuid4().hex[:12]


def current_request_id() -> str:
    """取当前请求 id；中间件未写入时返回空串（例如单元测试里直接调函数）。"""
    return request_id_ctx.get()


class ErrorCode(str, Enum):
    """机器可读的错误码（对外契约，改动即破坏性变更）。"""

    TASK_NOT_FOUND = "task_not_found"
    TASK_ID_CONFLICT = "task_id_conflict"
    QUEUE_FULL = "queue_full"
    TASK_ALREADY_FINISHED = "task_already_finished"
    TOOL_NOT_FOUND = "tool_not_found"
    UNAUTHORIZED = "unauthorized"
    PEAK_BLOCKED = "peak_blocked"
    INVALID_REQUEST = "invalid_request"
    INTERNAL_ERROR = "internal_error"
    #: 通用「资源/路由不存在」。**路由级** 404（URL 写错、静态文件缺失）走这个，
    #: 领域级 404（任务/文档/工具不存在）由各路由显式 raise 自己的码，见
    #: :func:`_code_for_status` 的说明。
    NOT_FOUND = "not_found"
    # ---- 知识库 / RAG（m2_design.md §7.3）----
    DOCUMENT_NOT_FOUND = "document_not_found"
    DUPLICATE_DOCUMENT = "duplicate_document"
    UNSUPPORTED_FORMAT = "unsupported_format"
    FILE_TOO_LARGE = "file_too_large"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    RAG_UNAVAILABLE = "rag_unavailable"


class ApiError(Exception):
    """业务异常：带错误码、HTTP 状态码与自定义响应头。

    Args:
        code: :class:`ErrorCode` 成员（或它的字符串值）。
        message: 给人看的一句话说明。
        status: HTTP 状态码。
        **headers: 要一并写回的响应头（如 ``Retry-After``）。

            注意：用 ``**headers`` 收集时键里的 ``-`` 无法写成 Python 标识符，
            调用方需要写成 ``ApiError(..., **{"Retry-After": "5"})``。
    """

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        status: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        **headers: str,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code) if not isinstance(code, ErrorCode) else code
        self.message = message
        self.status = status
        self.headers: dict[str, str] = dict(headers)

    def __str__(self) -> str:
        """便于日志里一眼看清是哪个码。"""
        return f"[{self.code.value}] {self.message}"


def error_body(code: str, message: str) -> dict[str, Any]:
    """组装统一错误信封。"""
    return {
        "detail": {
            "code": code,
            "message": message,
            "request_id": current_request_id(),
        }
    }


def _code_for_status(http_status: int) -> str:
    """把裸 HTTP 状态码翻译成错误码（给 Starlette 抛的 404/405 之类兜底）。

    这个函数**只在没有任何路由显式给出错误码时**被调用——``_handle_http_exception``
    收到的是 Starlette 自己抛的 ``HTTPException``。领域级错误（任务/文档/工具不存在）
    由各路由 ``raise ApiError(ErrorCode.XXX_NOT_FOUND, ..., status=404)`` 显式声明，
    走 ``_handle_api_error``，根本不会经过这里。

    因此 404 必须给**通用码**而不是 ``TASK_NOT_FOUND``：把任意 404 都标成
    ``task_not_found`` 会让客户端把「URL 写错」误判成「任务不存在」，与模块顶部
    宣称的「code 是可穷举契约」自相矛盾。路由级 404 与领域级 404 是两回事。

    Args:
        http_status: 裸 HTTP 状态码。

    Returns:
        对应的错误码字符串。
    """
    if http_status == status.HTTP_401_UNAUTHORIZED:
        return ErrorCode.UNAUTHORIZED.value
    if http_status == status.HTTP_404_NOT_FOUND:
        # 通用码；领域级 404 由路由显式声明，见上方说明。
        return ErrorCode.NOT_FOUND.value
    if http_status == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return ErrorCode.INVALID_REQUEST.value
    if http_status >= 500:
        return ErrorCode.INTERNAL_ERROR.value
    phrase = HTTPStatus(http_status).name.lower()
    return phrase


def _validation_message(exc: RequestValidationError) -> str:
    """把 Pydantic 的校验错误压成一句话（不给客户端看内部字段名以外的东西）。"""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        parts.append(f"{location or '请求体'}: {error.get('msg', '不合法')}")
    return "；".join(parts[:5]) or "请求参数校验失败"


def install_exception_handlers(app: FastAPI) -> None:
    """挂上三个异常处理器，把一切出口收敛成同一个信封。

    Args:
        app: FastAPI 应用实例。
    """

    async def _handle_api_error(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ApiError)  # noqa: S101 - 本处理器只注册给 ApiError
        if exc.status >= 500:
            logger.warning("API 业务异常 %s: %s", exc.code.value, exc.message)
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code.value, exc.message),
            headers=exc.headers or None,
        )

    async def _handle_validation_error(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101 - 见上
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(ErrorCode.INVALID_REQUEST.value, _validation_message(exc)),
        )

    async def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - 见上
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                _code_for_status(exc.status_code),
                str(exc.detail),
            ),
            headers=dict(exc.headers) if exc.headers else None,
        )

    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 只记日志、**不回显堆栈**：把内部异常细节发给客户端等于泄露实现。
        logger.exception("未捕获异常：%s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(ErrorCode.INTERNAL_ERROR.value, "服务内部错误，请查看服务日志"),
        )

    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)


def json_error(
    code: ErrorCode,
    message: str,
    http_status: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """手工构造错误响应（中间件里没有异常可抛时用）。

    ``headers`` 用于携带 ``WWW-Authenticate`` 这类协议要求的响应头——
    鉴权中间件捕获 ``ApiError`` 后走这里，若丢掉 headers，
    401 就不再返回 ``WWW-Authenticate: Bearer``，违反 RFC 6750。
    """
    return JSONResponse(
        status_code=http_status, content=error_body(code.value, message), headers=headers
    )


__all__ = [
    "ApiError",
    "ErrorCode",
    "current_request_id",
    "error_body",
    "install_exception_handlers",
    "json_error",
    "new_request_id",
    "request_id_ctx",
]
