#!/usr/bin/env python
"""Spike③（M3 T0）：验证消融实验栈在本机可装可用，产出 E1/E3 的耗时基线。

背景（m3_design.md D3 / §7 陷阱 2）：M2 的 `spike_embedding_stack.py` 是在
**CPython 3.14（uv 解释器）** 上做的，结论「sentence-transformers 被本机应用控制策略
拦截（sklearn 未签名 pyd）」存疑——3.14 无预编译 wheel 时 pip 会**源码自编译**，
产出的本地 .pyd 未签名，正是 Smart App Control 拦的那种；而预编译 wheel（如
`tokenizers`）实测可正常 import。本脚本在 **CPython 3.12** 上重测，把这个历史结论
钉死或推翻。

四项探针（前一项失败不阻断后一项，全部结果汇总成一张表）：
    ① torch CPU 可用性 + 真实 matmul
    ② transformers 直跑 bge 嵌入前向（D3 主路径，绕开 sentence-transformers）
    ③ transformers 直跑 bge-reranker 交叉编码前向（E3 的延迟真相）
    ④ sentence-transformers 可装可用（历史结论复测）

用法（必须用 3.12 那个 stdlib venv，**不要**用 uv 建的 `.venv`）::

    <USER_HOME>\\venvs\\trinity-m3\\Scripts\\python.exe scripts\\spike_m3_stack.py
    # 可选：--cmrc <parquet路径> 用真实语料测嵌入吞吐；--fast 只跑 ①②

耗时基线是 M3 成本模型的地基，不要引用外部文档里的数字，一切以本脚本输出为准。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 权重缓存放项目内（data/ 已 gitignore），别污染全局 HF 缓存
HF_CACHE_DIR = PROJECT_ROOT / "data" / "models" / "hf"

#: 本机 huggingface.co 直连不通，必须走镜像（m3_design.md 分歧表第 7 条）
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

#: E1 候选臂（D3：三个可比臂，砍掉需要新栈的 Qwen2-Embedding）
EMBED_MODEL = "BAAI/bge-base-zh-v1.5"

#: E3 候选臂（bge-reranker-v2-m3 体积 2.2GB，spike 先用 base 验通路）
RERANK_MODEL = "BAAI/bge-reranker-base"

#: 消融统一口径：fetch_k=20 → top_k=5（m3_design.md §5 基线配置）
RERANK_CANDIDATES = 20

#: 通过条件：向量各分量平方和 ≈ 1（bge 输出已 L2 归一）
NORM_TOLERANCE = 1e-3

#: 语料规模假设：轨道 A 抽 1000 篇 passage（D6）
CORPUS_PASSAGES = 1000


@dataclass(slots=True)
class ProbeResult:
    """一条探针的结论。"""

    name: str
    ok: bool
    detail: str
    timings: list[float] = field(default_factory=list)

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.timings) * 1000 if self.timings else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.timings:
            return 0.0
        ordered = sorted(self.timings)
        index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
        return ordered[index] * 1000


def _probe(name: str, ok: bool, detail: str, timings: list[float] | None = None) -> ProbeResult:
    return ProbeResult(name=name, ok=ok, detail=detail, timings=timings or [])


# --------------------------------------------------------------------------- #
# 探针①：torch CPU
# --------------------------------------------------------------------------- #
def probe_torch() -> ProbeResult:
    """torch 可 import 且能做真实矩阵运算（不只是 import 成功）。"""
    try:
        import torch

        torch.set_num_threads(min(8, os.cpu_count() or 4))
        a = torch.randn(512, 768)
        b = torch.randn(768, 512)
        elapsed = time.perf_counter()
        c = a @ b
        checksum = float(c.sum())
        ms = (time.perf_counter() - elapsed) * 1000
        return _probe(
            "torch-cpu",
            True,
            f"{torch.__version__} | threads={torch.get_num_threads()} | "
            f"512x768@768x512 = {ms:.1f}ms | checksum={checksum:.0f}",
        )
    except Exception as exc:  # noqa: BLE001
        return _probe("torch-cpu", False, f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# 公共：语料取样
# --------------------------------------------------------------------------- #
def _texts(args: argparse.Namespace) -> list[str]:
    """优先用真实 CMRC passage 测吞吐，取不到就退回代表性长度的合成文本。"""
    if args.cmrc and Path(args.cmrc).is_file():
        try:
            import pyarrow.parquet as pq

            table = pq.ParquetFile(args.cmrc).read(["context"])
            contexts = [str(x) for x in table.column("context").to_pylist()]
            return contexts[: args.limit]
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] 读 CMRC 失败，退回合成语料：{type(exc).__name__}: {exc}")
    filler = "综合布线系统中六类线的最大施工弯曲半径要求为线径的四倍施工时需要预留足够的操作空间并且避免弯折过度造成线芯损伤"
    unit = max(1, args.chars_per_doc // len(filler) + 1)
    return [filler * unit][: args.limit]


# --------------------------------------------------------------------------- #
# 探针②：bge 嵌入前向（D3 主路径）
# --------------------------------------------------------------------------- #
def probe_embed(args: argparse.Namespace) -> ProbeResult:
    """transformers 直跑 bge：CLS pooling + L2 归一，并量 E1 的索引重建成本。"""
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.embed_model, cache_dir=str(HF_CACHE_DIR))
        load = _timer()
        with load:
            model = AutoModel.from_pretrained(args.embed_model, cache_dir=str(HF_CACHE_DIR))
            model.eval()
        load_ms = load.value

        def embed_one(text: str) -> torch.Tensor:
            encoded = tokenizer(text, padding=False, truncation=True, max_length=512,
                                return_tensors="pt")
            with torch.inference_mode():
                out = model(**encoded).last_hidden_state[:, 0, :]  # bge = CLS pooling
            return torch.nn.functional.normalize(out, p=2, dim=1)[0]

        texts = _texts(args)
        if not texts:
            return _probe("embed-bge", False, "无可用语料文本")

        warm = embed_one(texts[0])  # 首次调用含图编译/缓存，不计入
        norm = float((warm * warm).sum())
        if abs(norm - 1.0) > NORM_TOLERANCE:
            return _probe("embed-bge", False, f"输出未归一（|v|^2={norm:.4f}），pooling 口径有误")

        # 单条计时（E1 每查询一次的开销）
        singles: list[float] = []
        for text in texts[: min(20, len(texts))]:
            started = time.perf_counter()
            embed_one(text)
            singles.append(time.perf_counter() - started)

        # 批量吞吐（E1 索引重建：1000 篇要多久）
        batch_started = time.perf_counter()
        _embed_batch(model, tokenizer, texts, batch_size=args.batch_size)
        batch_total = time.perf_counter() - batch_started

        dim = int(warm.shape[0])
        return _probe(
            "embed-bge",
            True,
            f"{args.embed_model} dim={dim} 归一✓ | 加载 {load_ms:.0f}ms | "
            f"单条 p50={statistics.median(singles)*1000:.0f}ms p95={_p95(singles):.0f}ms | "
            f"{len(texts)} 篇批式 {batch_total:.1f}s "
            f"→ {CORPUS_PASSAGES} 篇重建 ≈ {batch_total / len(texts) * CORPUS_PASSAGES:.0f}s",
            singles,
        )
    except Exception as exc:  # noqa: BLE001
        if args.verbose:
            traceback.print_exc()
        return _probe("embed-bge", False, f"{type(exc).__name__}: {exc}")


def _embed_batch(model, tokenizer, texts: list[str], *, batch_size: int) -> int:
    import torch

    vectors = 0
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            encoded = tokenizer(chunk, padding=True, truncation=True, max_length=512,
                                return_tensors="pt")
            out = model(**encoded).last_hidden_state[:, 0, :]
            vectors += out.shape[0]
    return vectors


# --------------------------------------------------------------------------- #
# 探针③：bge-reranker 交叉编码前向（E3 延迟真相）
# --------------------------------------------------------------------------- #
def probe_rerank(args: argparse.Namespace) -> ProbeResult:
    """单查询 = fetch_k 个候选逐对前向，这是 E3 的成本大头。"""
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.rerank_model, cache_dir=str(HF_CACHE_DIR))
        load = _timer()
        with load:
            model = AutoModelForSequenceClassification.from_pretrained(
                args.rerank_model, cache_dir=str(HF_CACHE_DIR)
            )
            model.eval()
        load_ms = load.value

        texts = _texts(args)
        query = texts[0]
        pairs = [[query, t] for t in texts[:RERANK_CANDIDATES]]

        first = _timer()
        with first:  # 首次含编译，单独报
            scores_first = _rerank(model, tokenizer, pairs)

        runs: list[float] = []
        for _ in range(args.rounds):
            started = time.perf_counter()
            scores = _rerank(model, tokenizer, pairs)
            runs.append(time.perf_counter() - started)

        if scores != scores_first:
            return _probe("rerank-bge", False, "两次前向结果不一致，temperature=0 前提被破坏")

        per_query = statistics.median(runs)
        return _probe(
            "rerank-bge",
            True,
            f"{args.rerank_model} | 加载 {load_ms:.0f}ms | 首跑 {first.value:.0f}ms | "
            f"{RERANK_CANDIDATES} 候选/查询 p50={per_query*1000:.0f}ms "
            f"p95={_p95(runs):.0f}ms | 150 题一轮 ≈ {per_query*150:.0f}s | "
            f"top1 分={scores[0]:.3f} top{RERANK_CANDIDATES} 分={scores[-1]:.3f}",
            runs,
        )
    except Exception as exc:  # noqa: BLE001
        if args.verbose:
            traceback.print_exc()
        return _probe("rerank-bge", False, f"{type(exc).__name__}: {exc}")


def _rerank(model, tokenizer, pairs: list[list[str]]) -> list[float]:
    import torch

    with torch.inference_mode():
        encoded = tokenizer(
            [p[0] for p in pairs], [p[1] for p in pairs],
            padding=True, truncation=True, max_length=512, return_tensors="pt",
        )
        logits = model(**encoded).logits[:, 0]
    return [float(x) for x in logits]


# --------------------------------------------------------------------------- #
# 探针④：sentence-transformers（历史结论复测）
# --------------------------------------------------------------------------- #
def probe_sentence_transformers(args: argparse.Namespace) -> ProbeResult:
    """当年被判「被 SAC 拦截（sklearn 未签名 pyd）」的那条路，在 3.12 上重测。"""
    try:
        import sklearn  # noqa: F401  ← 历史归因的靶子

        sklearn_version = getattr(sklearn, "__version__", "?")
    except Exception as exc:  # noqa: BLE001
        sklearn_version = f"FAIL({type(exc).__name__})"

    try:
        from sentence_transformers import SentenceTransformer

        started = time.perf_counter()
        model = SentenceTransformer(args.embed_model, cache_folder=str(HF_CACHE_DIR))
        load_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        vector = model.encode(["六类线弯曲半径是多少"], normalize_embeddings=True)
        encode_ms = (time.perf_counter() - started) * 1000
        return _probe(
            "sentence-transformers",
            True,
            f"sklearn={sklearn_version} | 加载 {load_ms:.0f}ms | encode {encode_ms:.0f}ms "
            f"dim={vector.shape[1]} → **历史结论被推翻**：3.12 预编译 wheel 路径可用",
        )
    except Exception as exc:  # noqa: BLE001
        if args.verbose:
            traceback.print_exc()
        kind = type(exc).__name__
        hint = (
            "（WinError 786 / '已阻止访问' 类 = SAC 真拦；其余多为依赖/版本问题，可修）"
            if "Windows" in str(exc) or "1260" in str(exc)
            else ""
        )
        message = f"sklearn={sklearn_version} | {kind}: {exc} {hint}"
        return _probe("sentence-transformers", False, message)


class _timer:
    """上下文计时器；退出 with 后读 ``.value``（毫秒）。"""

    def __init__(self) -> None:
        self._started = 0.0
        self.value = 0.0

    def __enter__(self) -> "_timer":
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.value = (time.perf_counter() - self._started) * 1000
        return False


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    return ordered[index] * 1000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3 T0 环境 spike：消融栈可装可用 + 耗时基线")
    parser.add_argument("--embed-model", default=EMBED_MODEL)
    parser.add_argument("--rerank-model", default=RERANK_MODEL)
    parser.add_argument("--cmrc", default="", help="CMRC2018 parquet 路径，用于真实语料吞吐")
    parser.add_argument("--limit", type=int, default=CORPUS_PASSAGES, help="语料条数上限")
    parser.add_argument("--chars-per-doc", type=int, default=453, help="合成语料的代表性长度")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--rounds", type=int, default=5, help="重排计时轮数")
    parser.add_argument("--fast", action="store_true", help="只跑 ①②，跳过下载更重的重排/ST")
    parser.add_argument("--verbose", action="store_true", help="打印完整堆栈")
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_ENDPOINT", DEFAULT_HF_ENDPOINT)
    #: 实测必需：hf-mirror 只代理普通 resolve 请求，xet 协议会直连
    #: cas-server.xethub.hf.co 并返回 401（T0 spike 踩到）。不关掉就走不通。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    #: fastembed 也要镜像 + 同一份 cache（它即使权重已缓存，仍会联网查 revision）
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(PROJECT_ROOT / "data" / "models" / "fastembed_cache"))
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:  # torch 本身就是被测对象之一，这里不能让 import 失败把整个脚本带走
        import torch

        torch_line = f"{torch.__version__} (cuda available={torch.cuda.is_available()})"
    except Exception as exc:  # noqa: BLE001
        torch_line = f"IMPORT FAILED: {type(exc).__name__}: {exc}"

    print("=" * 78)
    print(" M3 · T0 spike — 消融栈可行性与耗时基线")
    print("=" * 78)
    print(f" python     : {sys.version.split()[0]}  {sys.executable}")
    print(f" HF_ENDPOINT: {os.environ['HF_ENDPOINT']}")
    print(f" 权重缓存   : {HF_CACHE_DIR}")
    print(f" torch      : {torch_line}")
    print("-" * 78)

    results: list[ProbeResult] = [probe_torch()]
    results.append(probe_embed(args))
    if not args.fast:
        results.append(probe_rerank(args))
        results.append(probe_sentence_transformers(args))

    for item in results:
        print(f" [{'✅' if item.ok else '❌'}] {item.name:<24} {item.detail}")

    embeddable = any(r.name == "embed-bge" and r.ok for r in results)
    print("-" * 78)
    print(" 结论：", end="")
    if embeddable:
        print("E1 嵌入臂可跑（transformers 直连）。详见上表重排/ST 行，据此定 D3 是否需降级。")
    else:
        print("transformers 直连失败 → 走 D3 降级：fastembed 中文子集 + DashScope text-embedding API。")
    print("=" * 78)
    return 0 if embeddable else 1


__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
