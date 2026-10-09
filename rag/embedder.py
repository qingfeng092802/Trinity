"""Embedding 提供商：协议 + fastembed(ONNX) / torch 两种实现 + 测试桩 + 工厂（T02，M3 · T3 加后端）。

选型落点（.env T01 spike 结论）：sentence-transformers 被本机 Windows 应用控制
策略拦截（sklearn 未签名 pyd），**fastembed(ONNX) 兜底方案转正**——
``TextEmbedding("BAAI/bge-small-zh-v1.5")`` + onnxruntime，dim=512，L2 归一。

纪律（m2_design.md §7.4）：

* ``fastembed`` / ``numpy`` 只在函数体内 import（``rag/__init__.py`` 不拉任何重依赖）；
* 权重**首次 ``embed()`` 才加载**（模型加载 5-15s，不能拖慢 API 启动）；
* ``fingerprint = sha1(f"{model_name}:{dim}")[:16]``（Q7 双闸的取值来源）；
* ONNX 权重缓存目录从 ``FASTEMBED_CACHE_PATH`` 环境变量读取（T01 spike 已把
  bge-small-zh-v1.5 缓存在 ``%TEMP%\\fastembed_cache``，运行时直接命中，不再下载）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from rag.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

#: fastembed 对 bge-small-zh-v1.5 的模型仓库名（无 org 前缀时自动补）
_FASTEMBED_REPO_PREFIX = "BAAI/"


def default_cache_dir() -> str:
    """fastembed 缓存目录解析：``FASTEMBED_CACHE_PATH`` → ``%TEMP%/fastembed_cache``。"""
    return os.environ.get("FASTEMBED_CACHE_PATH", "") or os.path.join(
        os.environ.get("TEMP", ""), "fastembed_cache"
    )


def fingerprint_of(model_name: str, dim: int) -> str:
    """模型指纹（唯一来源）：``sha1(f"{model_name}:{dim}")[:16]``。"""
    return hashlib.sha1(f"{model_name}:{dim}".encode("utf-8")).hexdigest()[:16]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """向量化的统一接口；检索/索引/测试桩都只认这个协议。"""

    def name(self) -> str: ...

    def dim(self) -> int: ...

    def fingerprint(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def health_check(self) -> tuple[bool, str]: ...


class FastembedBgeEmbedder:
    """fastembed(ONNX) + bge-small-zh-v1.5：懒加载、批量、L2 归一。"""

    def __init__(
        self,
        *,
        model_name: str = "bge-small-zh-v1.5",
        dim: int = 512,
        batch_size: int = 32,
        cache_dir: str = "",
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._batch_size = batch_size
        self._cache_dir = cache_dir or default_cache_dir()
        self._model: object | None = None

    # -- 协议实现 --
    def name(self) -> str:
        return f"fastembed/{self._model_name}"

    def dim(self) -> int:
        return self._dim

    def fingerprint(self) -> str:
        return fingerprint_of(self._model_name, self._dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化；输出 L2 归一到单位长度（bge 检索配 cosine）。"""
        if not texts:
            return []
        model = self._ensure_loaded()
        import numpy as np

        try:
            vectors = list(
                model.embed(texts, batch_size=self._batch_size)  # type: ignore[attr-defined]
            )
        except Exception as exc:  # noqa: BLE001 - 推理异常统一编码为 EmbeddingError
            raise EmbeddingError(f"fastembed 推理失败：{type(exc).__name__}: {exc}") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(f"fastembed 返回向量数({len(vectors)})与输入数({len(texts)})不一致")
        result: list[list[float]] = []
        for raw in vectors:
            array = np.asarray(raw, dtype="float32")
            norm = float(np.linalg.norm(array))
            result.append((array / norm if norm > 1e-12 else array).tolist())
        return result

    def health_check(self) -> tuple[bool, str]:
        """不加载权重也能回答的依赖/路径状态（/health.rag 用）。"""
        try:
            import fastembed

            version = getattr(fastembed, "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001
            return False, f"fastembed 未安装或不可用：{type(exc).__name__}: {exc}"
        cache_note = self._cache_dir or "（fastembed 默认缓存目录）"
        return True, f"fastembed {version} 就绪（模型 {self._model_name}，首次 embed 时加载；缓存：{cache_note}）"

    # -- 内部 --
    def _ensure_loaded(self):
        """首次调用时加载 ONNX 模型；失败统一抛 :class:`EmbeddingError`。"""
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingError(f"fastembed 未安装，无法向量化：{exc}") from exc

        repo_name = (
            self._model_name
            if "/" in self._model_name
            else f"{_FASTEMBED_REPO_PREFIX}{self._model_name}"
        )
        kwargs: dict[str, str] = {"model_name": repo_name}
        if self._cache_dir:
            kwargs["cache_dir"] = self._cache_dir
        started = time.perf_counter()
        try:
            self._model = TextEmbedding(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(
                f"fastembed 模型加载失败（{repo_name}，缓存目录 {self._cache_dir or '默认'}）：{exc}"
            ) from exc
        logger.info("fastembed 模型加载完成：%s（%.1fs）", repo_name, time.perf_counter() - started)
        return self._model


class TorchBgeEmbedder:
    """transformers + torch 直跑 bge：CLS pooling + L2 归一（M3 · E1 的 torch 后端臂）。

    三条不显然的口径，改代码前先读：

    * **不走 sentence-transformers**：它把 sklearn 拉进依赖闭包，本机 Windows 应用控制
      策略直接拦（模块头有记录）。``AutoModel`` + CLS pooling 就是它内部的实现；
    * **不加 bge 官方的查询指令前缀**（「为这个句子生成表示以用于检索相关文章：」）：
      M2 的 ONNX 基线没加，加了「换后端」就变成「换后端 + 换查询编码」两个变量，
      跨模型对比时 small/base/large 的编码也会因此不再一致；
    * **指纹带上后端**：``sha1("torch:{model}:{dim}")``。同模型同维度换 runtime，
      数值上几乎同解但**不逐位相同**；若与 ONNX 共用指纹，切换后端时指纹闸会放行、
      直接查旧库，E1-backend 这条臂的结论就废了（宁可强制重建一次）。
    """

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-base-zh-v1.5",
        dim: int = 768,
        batch_size: int = 32,
        cache_dir: str = "",
        max_seq: int = 512,
    ) -> None:
        if not model_name.strip():
            raise EmbeddingError("model_name 不能为空")
        if dim < 1:
            raise EmbeddingError(f"dim 必须 ≥ 1，收到 {dim}")
        if batch_size < 1:
            raise EmbeddingError(f"batch_size 必须 ≥ 1，收到 {batch_size}")
        self._model_name = model_name.strip()
        self._dim = dim
        self._batch_size = batch_size
        self._cache_dir = cache_dir
        self._max_seq = max_seq
        self._model: object | None = None
        self._tokenizer: object | None = None

    # -- 协议实现 --
    def name(self) -> str:
        return f"torch/{self._model_name}"

    def dim(self) -> int:
        return self._dim

    def fingerprint(self) -> str:
        return fingerprint_of(f"torch:{self._model_name}", self._dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化：CLS 池化 + L2 归一（与 fastembed 臂同一可比性口径）。"""
        if not texts:
            return []
        import torch

        tokenizer = self._ensure_loaded()
        vectors: list[list[float]] = []
        try:
            with torch.inference_mode():
                for offset in range(0, len(texts), self._batch_size):
                    batch = texts[offset : offset + self._batch_size]
                    encoded = tokenizer(
                        batch,
                        padding=True,
                        truncation=True,
                        max_length=self._max_seq,
                        return_tensors="pt",
                    )
                    hidden = self._model(**encoded).last_hidden_state  # type: ignore[attr-defined]
                    pooled = torch.nn.functional.normalize(hidden[:, 0, :], p=2, dim=1)
                    vectors.extend(row.tolist() for row in pooled)
        except Exception as exc:  # noqa: BLE001 - 推理异常统一编码为 EmbeddingError
            raise EmbeddingError(
                f"torch 推理失败（{self._model_name}）：{type(exc).__name__}: {exc}"
            ) from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(f"torch 返回向量数({len(vectors)})与输入数({len(texts)})不一致")
        return vectors

    def health_check(self) -> tuple[bool, str]:
        """只回答依赖状态，不加载权重（bge-base 冷加载实测 ~12s，不能进探活路径）。"""
        try:
            import transformers

            version = getattr(transformers, "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001
            return False, f"transformers 未安装或不可用：{type(exc).__name__}: {exc}"
        loaded = "权重已加载" if self._model is not None else "首次 embed 时加载"
        cache_note = self._cache_dir or "（huggingface 默认缓存目录）"
        return True, f"transformers {version} + torch 就绪（{self._model_name}，{loaded}；缓存：{cache_note}）"

    # -- 内部 --
    def _ensure_loaded(self):
        """首次调用时加载权重；顺带核对 ``dim`` 与模型真实输出维度是否一致。"""
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise EmbeddingError(f"transformers 未安装，无法向量化：{exc}") from exc

        kwargs = {"cache_dir": self._cache_dir} if self._cache_dir else {}
        started = time.perf_counter()
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name, **kwargs)
            self._model = AutoModel.from_pretrained(self._model_name, **kwargs)
            self._model.eval()
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(
                f"bge 权重加载失败（{self._model_name}，缓存 {self._cache_dir or '默认'}）：{exc}"
            ) from exc
        hidden = int(getattr(self._model.config, "hidden_size", self._dim))
        if hidden != self._dim:
            raise EmbeddingError(
                f"{self._model_name} 实际输出 {hidden} 维，配置 embedding_dim={self._dim}："
                "维度和模型不匹配会让向量库静默错位，必须改配置而不是继续跑"
            )
        logger.info("torch 模型加载完成：%s（%.1fs）", self._model_name, time.perf_counter() - started)
        return self._tokenizer


class MockEmbedder:
    """测试桩：确定性哈希向量（同文本恒同向量），零依赖、零下载。"""

    def __init__(self, *, dim: int = 64, model_name: str = "mock-embedder") -> None:
        self._dim = dim
        self._model_name = model_name

    def name(self) -> str:
        return self._model_name

    def dim(self) -> int:
        return self._dim

    def fingerprint(self) -> str:
        return fingerprint_of(self._model_name, self._dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib as _hashlib
        import math

        vectors: list[list[float]] = []
        for text in texts:
            digest = _hashlib.sha1(text.encode("utf-8")).digest()
            vector = [
                math.sin(int.from_bytes(digest[(index * 4) % len(digest) : (index * 4) % len(digest) + 4], "big"))
                for index in range(self._dim)
            ]
            norm = math.sqrt(sum(component * component for component in vector)) or 1.0
            vectors.append([component / norm for component in vector])
        return vectors

    def health_check(self) -> tuple[bool, str]:
        return True, "MockEmbedder 就绪（仅测试用）"


def _resolve_cache_dir(settings) -> str:
    """fastembed 缓存目录解析（唯一真源：``settings.fastembed_cache_dir``）。

    优先级：

    1. 环境变量 ``FASTEMBED_CACHE_DIR`` 显式覆盖；
    2. 配置目录（``data/models/fastembed_cache``）已有模型缓存 → 用它；
    3. 都为空但 T01 spike 的 ``%TEMP%/fastembed_cache`` 已有缓存 → 复用它
       （避免 ~100MB 的 ONNX 权重重复下载）；
    4. 兜底：配置目录（首次 embed 时由 fastembed 下载填充）。
    """
    env_dir = os.environ.get("FASTEMBED_CACHE_DIR", "").strip()
    if env_dir:
        return env_dir
    configured = str(settings.fastembed_cache_dir)
    try:
        if any(Path(configured).glob("models--*")):
            return configured
        temp_cache = Path(os.environ.get("TEMP", "")) / "fastembed_cache"
        if any(temp_cache.glob("models--*")):
            return str(temp_cache)
    except OSError:  # pragma: no cover - 磁盘枚举失败时走默认
        pass
    return configured


def _hf_cache_dir(settings) -> str:
    """torch/transformers 权重缓存目录：环境变量 ``HF_CACHE_DIR`` 优先，其次配置目录。"""
    env_dir = os.environ.get("HF_CACHE_DIR", "").strip()
    return env_dir or str(settings.hf_cache_dir)


def create_embedder(settings) -> EmbeddingProvider:
    """按配置构造 embedder。

    两个正交旋钮（E1 全部消融臂都从这里出来）：
    ``settings.embedding_backend`` 选运行时（fastembed=ONNX / torch=transformers），
    ``settings.embedding_model_name`` + ``embedding_dim`` 选模型。

    * 环境变量 ``RAG_FAKE_EMBEDDER=1`` → :class:`MockEmbedder`（测试/无网逃生门）；
    * ``embedding_backend == "torch"`` → :class:`TorchBgeEmbedder`；
    * 其余（M2 生产默认）→ :class:`FastembedBgeEmbedder`。
    """
    if os.environ.get("RAG_FAKE_EMBEDDER", "").strip().lower() in {"1", "true", "yes"}:
        logger.warning("RAG_FAKE_EMBEDDER=1：使用 MockEmbedder（哈希向量，仅测试用）")
        # model_name 必须沿用配置值：指纹 = sha1(model_name:dim)，Mock 桩若用
        # 自己的名字，检索入口指纹闸（check_fingerprint）会必然 409。
        return MockEmbedder(dim=settings.embedding_dim, model_name=settings.embedding_model_name)
    if settings.embedding_backend == "torch":
        return TorchBgeEmbedder(
            model_name=settings.embedding_model_name,
            dim=settings.embedding_dim,
            batch_size=settings.embedding_batch_size,
            cache_dir=_hf_cache_dir(settings),
        )
    return FastembedBgeEmbedder(
        model_name=settings.embedding_model_name,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        cache_dir=_resolve_cache_dir(settings),
    )


__all__ = [
    "EmbeddingProvider",
    "FastembedBgeEmbedder",
    "MockEmbedder",
    "TorchBgeEmbedder",
    "create_embedder",
    "default_cache_dir",
    "fingerprint_of",
]
