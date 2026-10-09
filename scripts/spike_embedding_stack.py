#!/usr/bin/env python
"""Spike②：验证 torch + sentence-transformers 在 CPython 3.14 的可装可用。

流程（m2_design.md §0.2 风险② / §5 T01 子步骤 3）：
    import torch → import sentence_transformers → 确定性 encode 一句话出向量
    → 打印维度与耗时 → 输出选型结论

降级链（三级）：
    ① sentence-transformers + torch(CPU)   ← 本脚本验证
    ② fastembed（ONNX，无 torch 依赖）      ← ①失败时按脚本提示安装验证
    ③ 两者皆败 → 需人工决策（唯一升级点）

用法::

    .venv\\Scripts\\python.exe scripts\\spike_embedding_stack.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_TEXTS = ["综合布线系统中六类线的最大施工弯曲半径是多少？", "门禁系统常用两种联网方式"]


def _check_torch() -> tuple[bool, str]:
    """torch 可 import 且能做一次小张量运算。"""
    try:
        import torch

        probe = torch.ones(4, dtype=torch.float32).sum().item()
        return True, f"torch {torch.__version__}（sum={probe}）"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _check_sentence_transformers() -> tuple[bool, str]:
    """sentence-transformers 可 import（不加载真实权重）。"""
    try:
        import sentence_transformers

        return True, f"sentence-transformers {sentence_transformers.__version__}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _encode_smoke(dim: int = 512) -> tuple[bool, str]:
    """encode 冒烟：优先用本地已探测到的权重；探测不到时用最小测试模型。

    注意：真实 bge 权重可能尚未就位（权重探测是独立 spike），所以这里
    允许用 sentence-transformers 自带的极小 parphrase 模型在线下载；若网络
    不可用，只要求 import 链路通过即可给出「依赖可用 / 权重待补」的结论。
    """
    import sentence_transformers

    candidates: list[tuple[str, str]] = []
    settings_path = _probe_local_bge()
    if settings_path:
        candidates.append(("local-bge", settings_path))
    candidates.append(("hf-cache", "paraphrase-multilingual-MiniLM-L12-v2"))

    for name, model_ref in candidates:
        started = time.perf_counter()
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_ref)
            vectors = model.encode(
                SAMPLE_TEXTS, normalize_embeddings=True, batch_size=2, show_progress_bar=False
            )
            elapsed = time.perf_counter() - started
            shape = tuple(vectors.shape)  # type: ignore[union-attr]
            norm_ok = abs(float(vectors[0].dot(vectors[0])) - 1.0) < 0.01  # type: ignore[index]
            return (
                True,
                f"[{name}] {model_ref} encode {len(SAMPLE_TEXTS)} 句 {elapsed:.2f}s "
                f"shape={shape} L2归一={'OK' if norm_ok else 'NG'}",
            )
        except Exception as exc:  # noqa: BLE001 - 换下一个候选
            print(f"    尝试 {name}={model_ref} 失败：{type(exc).__name__}: {exc}")
    return False, f"encode 冒烟未成功（candidates={len(candidates)}，dim 预期 {dim}）"


def _probe_local_bge() -> str:
    """若本机已有 bge-small-zh-v1.5 权重（探测脚本回填 .env 或环境变量），优先用它。"""
    env_path = os.environ.get("EMBEDDING_MODEL_PATH", "").strip()
    env_file = PROJECT_ROOT / ".env"
    if not env_path and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("EMBEDDING_MODEL_PATH="):
                env_path = line.split("=", 1)[1].strip()
                break
    if env_path and Path(env_path, "config.json").is_file():
        return env_path
    return ""


def _has_cached_snapshot() -> bool:
    """fastembed 默认缓存（%TEMP%\\fastembed_cache）中是否已有可用的 ONNX snapshot。"""
    import tempfile

    cache = Path(tempfile.gettempdir()) / "fastembed_cache" / "models--Qdrant--bge-small-zh-v1.5"
    if not cache.is_dir():
        return False
    return any(
        (rev / "model_optimized.onnx").is_file() for rev in (cache / "snapshots").glob("*")
    )


def _check_fastembed() -> tuple[bool, str]:
    """降级链②：fastembed（ONNX）能否用本地 bge 权重离线 encode。

    fastembed 默认会去 HuggingFace 拉 ONNX 权重；本机若已有 bge-small-zh-v1.5
    原始权重（HF 格式），用 ``specific_model_path`` 直接指向即可离线加载
    （onnxruntime 直接读 model.onnx，不依赖 torch/sklearn）。
    """
    try:
        from fastembed import TextEmbedding
    except Exception as exc:  # noqa: BLE001
        return False, f"import 失败：{type(exc).__name__}: {exc}"

    model_ref = "BAAI/bge-small-zh-v1.5"
    # ① 权重已在 fastembed 缓存（%TEMP%\\fastembed_cache，spike 期间经 hf-mirror
    #   下载并手工物化 snapshot）→ 离线加载，禁止任何网络访问
    # ② 若缓存为空但本机有含 model_optimized.onnx 的目录 → specific_model_path
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    kwargs: dict[str, str] = {}
    label = "fastembed(离线缓存)"
    local = _probe_local_bge()
    if not _has_cached_snapshot() and local and Path(local, "model_optimized.onnx").is_file():
        kwargs["specific_model_path"] = local
        label = f"fastembed(本地权重 {Path(local).name})"
    started = time.perf_counter()
    try:
        model = TextEmbedding(model_ref, **kwargs)
        vectors = list(model.embed(SAMPLE_TEXTS))
        elapsed = time.perf_counter() - started
        import math

        dim = len(vectors[0])
        norm = math.sqrt(sum(x * x for x in vectors[0]))
        norm_ok = abs(norm - 1.0) < 0.05
        return (
            True,
            f"[{label}] encode {len(SAMPLE_TEXTS)} 句 {elapsed:.2f}s dim={dim} "
            f"L2≈{norm:.4f}（{'OK' if norm_ok else '未归一'}）",
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{label} 加载/encode 失败：{type(exc).__name__}: {exc}"


def main() -> int:
    print("=" * 64)
    print("Spike②  torch + sentence-transformers on CPython", sys.version.split()[0])
    print("=" * 64)

    torch_ok, torch_detail = _check_torch()
    print(f"[{'PASS' if torch_ok else 'FAIL'}] torch: {torch_detail}")

    st_ok, st_detail = _check_sentence_transformers()
    print(f"[{'PASS' if st_ok else 'FAIL'}] sentence-transformers: {st_detail}")

    encode_ok = False
    encode_detail = "跳过（依赖缺失）"
    if torch_ok and st_ok:
        print("-- encode 冒烟（可能需要下载极小测试模型，或命中本地权重）--")
        encode_ok, encode_detail = _encode_smoke()
        print(f"[{'PASS' if encode_ok else 'FAIL'}] encode: {encode_detail}")

    # ---- 降级链②：sentence-transformers 链路失败时验证 fastembed 兜底 ----
    fastembed_ok = False
    fastembed_detail = "跳过（sentence-transformers 链路已 PASS）"
    if not (st_ok and encode_ok):
        print("-- 降级链②：fastembed(ONNX) + 本地 bge 权重离线验证 --")
        fastembed_ok, fastembed_detail = _check_fastembed()
        print(f"[{'PASS' if fastembed_ok else 'FAIL'}] fastembed: {fastembed_detail}")

    print("-" * 64)
    if torch_ok and st_ok and encode_ok:
        print("结论：PASS —— sentence-transformers + torch(CPU) 可用，"
              "rag.embedder 按此实现（LocalBgeEmbedder）")
        return 0
    if torch_ok and st_ok:
        print("结论：PARTIAL —— 依赖可用但 encode 冒烟失败（权重未就位或网络受限）；"
              "依赖链本身可用，待权重就位后重跑 encode 即可转 PASS")
        return 0
    if fastembed_ok:
        print("结论：FALLBACK-PASS —— sentence-transformers 不可用（Windows 应用控制策略"
              "拦截 sklearn 未签名 pyd），但 fastembed(ONNX) + 本地 bge 权重可用；"
              "rag.embedder 建议按 fastembed 方案实现")
        return 0
    print("结论：FAIL —— sentence-transformers 与 fastembed 均不可用，需人工决策")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
