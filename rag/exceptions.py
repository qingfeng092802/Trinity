"""RAG 异常层级：基类 + 各阶段子类（设计文档 m2_design.md §3.2）。

纪律（与 M1 工具边界一致）：

* 这些异常允许在 rag 包内部抛出，但**必须**在 ``IndexWorker`` 与
  ``knowledge_search`` 工具边界被捕获并编码成状态 / 失败字符串，绝不冒泡到
  FastAPI 请求处理之外；
* ``FingerprintMismatchError`` 是唯一会被 ``api/routes/knowledge.py`` 翻译成
  409 ``fingerprint_mismatch`` 的类型——它是「用户可修复」的预期分支，
  不是系统故障。
"""

from __future__ import annotations


class RagError(Exception):
    """RAG 模块所有异常的基类。

    Args:
        message: 给人看的一句话说明（会写进 documents.error_message 或工具结果）。
        stage: 发生阶段（parsing / chunking / embedding / storage / retrieval）。
    """

    def __init__(self, message: str, *, stage: str = "unknown") -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


class ParserError(RagError):
    """文档解析失败：损坏文件、文本层缺失（扫描件）等。

    ``stage`` 固定为 ``parsing``。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="parsing")


class SplitterError(RagError):
    """切分失败：参数非法（chunk_size 越界）等。``stage`` 固定为 ``chunking``。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="chunking")


class EmbeddingError(RagError):
    """向量化失败：模型路径无效、依赖缺失、推理异常等。``stage`` 为 ``embedding``。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="embedding")


class StoreError(RagError):
    """向量库读写失败：sqlite-vec 加载失败、chroma 目录不可写等。

    ``stage`` 固定为 ``storage``。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="storage")


class FingerprintMismatchError(RagError):
    """模型指纹与库级指纹不一致（换模型后未重索引）。

    ``stage`` 固定为 ``retrieval``；API 层捕获后返回 409 ``fingerprint_mismatch``。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="retrieval")


__all__ = [
    "EmbeddingError",
    "FingerprintMismatchError",
    "ParserError",
    "RagError",
    "SplitterError",
    "StoreError",
]
