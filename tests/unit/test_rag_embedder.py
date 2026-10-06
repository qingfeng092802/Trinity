"""``rag/embedder.py`` 单元测试：指纹口径 + MockEmbedder 确定性（T02）。

真实 fastembed 加载/推理走 scripts/smoke_t02.py --real 与 bench_index.py
（单元测试不下载权重、不加载模型，遵循 D6 测试资源纪律）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.embedder import (  # noqa: E402
    FastembedBgeEmbedder,
    MockEmbedder,
    TorchBgeEmbedder,
    create_embedder,
    fingerprint_of,
)
from rag.exceptions import EmbeddingError  # noqa: E402


def test_fingerprint_format() -> None:
    expected = hashlib.sha1(b"bge-small-zh-v1.5:512").hexdigest()[:16]
    assert fingerprint_of("bge-small-zh-v1.5", 512) == expected
    embedder = FastembedBgeEmbedder(model_name="bge-small-zh-v1.5", dim=512)
    assert embedder.fingerprint() == expected
    assert embedder.dim() == 512
    assert "bge-small-zh-v1.5" in embedder.name()


def test_fingerprint_changes_with_model_or_dim() -> None:
    base = fingerprint_of("bge-small-zh-v1.5", 512)
    assert fingerprint_of("bge-large-zh-v1.5", 512) != base
    assert fingerprint_of("bge-small-zh-v1.5", 768) != base


def test_mock_embedder_deterministic_and_normalized() -> None:
    embedder = MockEmbedder(dim=64)
    vectors = embedder.embed(["六类线弯曲半径", "门禁联网方式", "六类线弯曲半径"])
    assert len(vectors) == 3
    assert vectors[0] == vectors[2], "同文本必须恒同向量（确定性）"
    assert vectors[0] != vectors[1]
    for vector in vectors:
        assert len(vector) == 64
        norm = sum(component**2 for component in vector) ** 0.5
        assert abs(norm - 1.0) < 1e-6, "输出必须 L2 归一"


def test_mock_embedder_health_check() -> None:
    ok, detail = MockEmbedder().health_check()
    assert ok
    assert detail


def test_fastembed_health_check_without_load() -> None:
    """health_check 不允许加载权重——只报告依赖状态。"""
    ok, detail = FastembedBgeEmbedder().health_check()
    assert isinstance(ok, bool)
    assert detail


# --------------------------------------------------------------------------- #
# torch 后端（M3 · E1）：全程用假模型，不下载权重、不跑真前向
# --------------------------------------------------------------------------- #
# ⚠️ "用假模型"挡不住 import：``_FakeModel.__call__`` 里要真造 tensor，
# ``_install_fake_transformers`` 要 monkeypatch 真模块，``health_check()`` 问的就是
# "这两个包能不能 import"。所以本机没装 torch/transformers（4GB 显存装不下那条链）时，
# 下面三条是**跳过**而不是失败 —— 断言文本一个字没动，只是不再在缺包环境里跑。
_HAS_TORCH_STACK = all(
    importlib.util.find_spec(name) is not None for name in ("torch", "transformers")
)
needs_torch_stack = pytest.mark.skipif(
    not _HAS_TORCH_STACK,
    reason="本机无 torch/transformers：CLS 池化与延迟加载路径需 2GB+ 依赖，见 README",
)

_CLS_VECTORS = {"甲": [3.0, 4.0, 0.0], "乙": [0.0, 0.0, 5.0]}


class _FakeTokenizer:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def __call__(self, texts: list[str], **_kwargs: object) -> dict[str, list[str]]:
        self.batches.append(list(texts))
        return {"input_ids": list(texts)}


class _FakeModel:
    """``last_hidden_state[:, 0]`` 是真向量，``[:, 1]`` 全是 100 —— 用来抓池化方式。"""

    def __init__(self, hidden_size: int = 3) -> None:
        self.config = SimpleNamespace(hidden_size=hidden_size)
        self.calls = 0
        self.eval_called = False

    def eval(self) -> None:
        self.eval_called = True

    def __call__(self, input_ids: list[str], **_kwargs: object):
        import torch

        self.calls += 1
        cls = torch.tensor([_CLS_VECTORS[token] for token in input_ids], dtype=torch.float32)
        junk = torch.full_like(cls.unsqueeze(1), 100.0)
        return SimpleNamespace(last_hidden_state=torch.cat([cls.unsqueeze(1), junk], dim=1))


def _install_fake_transformers(monkeypatch, model: _FakeModel, tokenizer: _FakeTokenizer) -> None:
    import transformers

    class _Auto:
        @staticmethod
        def from_pretrained(_name: str, **_kwargs: object):
            return model

    class _AutoTok:
        @staticmethod
        def from_pretrained(_name: str, **_kwargs: object):
            return tokenizer

    monkeypatch.setattr(transformers, "AutoModel", _Auto)
    monkeypatch.setattr(transformers, "AutoTokenizer", _AutoTok)


def test_torch_fingerprint_isolates_the_backend() -> None:
    """同模型同维度、只换运行时：指纹必须不同，否则切换后端时指纹闸放行、直接查旧库。"""
    onnx = FastembedBgeEmbedder(model_name="bge-small-zh-v1.5", dim=512)
    torch_backend = TorchBgeEmbedder(model_name="bge-small-zh-v1.5", dim=512)
    assert torch_backend.fingerprint() != onnx.fingerprint()
    assert torch_backend.fingerprint() == fingerprint_of("torch:bge-small-zh-v1.5", 512)
    assert torch_backend.name() == "torch/bge-small-zh-v1.5"


def test_torch_embedder_construction_validation() -> None:
    with pytest.raises(EmbeddingError, match="model_name"):
        TorchBgeEmbedder(model_name="   ", dim=512)
    with pytest.raises(EmbeddingError, match="dim"):
        TorchBgeEmbedder(model_name="BAAI/bge-base-zh-v1.5", dim=0)
    with pytest.raises(EmbeddingError, match="batch_size"):
        TorchBgeEmbedder(model_name="BAAI/bge-base-zh-v1.5", dim=768, batch_size=0)


@needs_torch_stack
def test_torch_embedder_defers_weight_load() -> None:
    embedder = TorchBgeEmbedder(model_name="BAAI/bge-base-zh-v1.5", dim=768)
    assert embedder._model is None, "构造不得加载权重"
    assert embedder.embed([]) == []
    assert embedder._model is None, "空输入不得触发加载"
    ok, detail = embedder.health_check()
    assert ok and "首次 embed 时加载" in detail


@needs_torch_stack
def test_torch_embed_uses_cls_pooling_and_l2(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLS 池化 + L2 归一；均值池化或漏归一都会被这组数抓到。"""
    model, tokenizer = _FakeModel(), _FakeTokenizer()
    _install_fake_transformers(monkeypatch, model, tokenizer)
    embedder = TorchBgeEmbedder(
        model_name="BAAI/bge-small-zh-v1.5", dim=3, batch_size=1
    )

    vectors = embedder.embed(["甲", "乙"])
    assert vectors[0] == pytest.approx([0.6, 0.8, 0.0])
    assert vectors[1] == pytest.approx([0.0, 0.0, 1.0])
    assert model.calls == 2, "batch_size=1 时必须分批"
    assert model.eval_called, "推理前必须 eval()（dropout 不关会不确定）"
    assert tokenizer.batches == [["甲"], ["乙"]]


@needs_torch_stack
def test_torch_embed_rejects_dim_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置维度 ≠ 模型真实输出维度 → 当场报错，不能让向量库静默错位。"""
    _install_fake_transformers(monkeypatch, _FakeModel(hidden_size=3), _FakeTokenizer())
    embedder = TorchBgeEmbedder(model_name="BAAI/bge-small-zh-v1.5", dim=8)
    with pytest.raises(EmbeddingError, match="维度和模型不匹配"):
        embedder.embed(["甲"])


def test_create_embedder_dispatches_on_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_FAKE_EMBEDDER", raising=False)
    settings = SimpleNamespace(
        embedding_backend="torch",
        embedding_model_name="BAAI/bge-base-zh-v1.5",
        embedding_dim=768,
        embedding_batch_size=8,
        hf_cache_dir=Path("data/models/hf"),
    )
    embedder = create_embedder(settings)
    assert isinstance(embedder, TorchBgeEmbedder)
    assert embedder.dim() == 768 and embedder.name() == "torch/BAAI/bge-base-zh-v1.5"
