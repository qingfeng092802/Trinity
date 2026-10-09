#!/usr/bin/env python
"""探测本机是否已有 BAAI/bge-small-zh-v1.5 权重（其他项目遗留或已下载缓存等）。

探测顺序（m2_design.md §1.4，**只探测不下载**）：
    ① 环境变量 EMBEDDING_MODEL_PATH / .env 已固化值
    ② 常见根目录扫描：<USER_HOME>\\、C:\\、D:\\、E:\\（存在才扫）下
       目录名匹配 *ragflow* / *bge-small-zh* / models--BAAI--bge-small-zh-v1.5
       （HF cache 形式），并校验 config.json 存在判定为有效权重
    ③ 无命中 → 输出 hf-mirror.com 下载命令（**不执行**，需人工确认后手动跑）

命中后把路径回填 .env 的 EMBEDDING_MODEL_PATH（带注释标记）。

用法::

    .venv\\Scripts\\python.exe scripts\\probe_bge_weights.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 有效权重的判定文件（bge 系列必有）
WEIGHT_MARKER_FILES = ("config.json", "modules.json")

#: 目录名匹配模式（任一命中即候选）
NAME_PATTERNS = (
    re.compile(r"bge[-_]?small[-_]?zh", re.IGNORECASE),
    re.compile(r"models--BAAI--bge-small-zh-v1\.5", re.IGNORECASE),
    re.compile(r"ragflow", re.IGNORECASE),
)

#: 扫描根目录：默认取本文件所在盘（不硬编码任何具体盘符），可用环境变量
#: BGE_SCAN_ROOTS 覆盖（用 os.pathsep 分隔；Windows 为 `;`、POSIX 为 `:`）。
#: 不扫用户主目录与系统盘，避免触碰 .ssh / 应用凭据等敏感目录。
#: 存在才扫；每根最多下探 6 层。
def _default_scan_roots() -> tuple[Path, ...]:
    override = os.environ.get("BGE_SCAN_ROOTS", "").strip()
    if override:
        return tuple(Path(p) for p in override.split(os.pathsep) if p.strip())
    return (Path(Path(__file__).resolve().anchor),)


SCAN_ROOTS = _default_scan_roots()
MAX_DEPTH = 6

#: 无论多深都跳过的目录名（敏感 / 无关，防御性裁剪）
PRUNED_DIRNAMES = frozenset(
    {
        "$recycle.bin",
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "appdata",
        "node_modules",
        "__pycache__",
        ".git",
        ".ssh",
        ".gnupg",
        "codebuddyextension",
        "site-packages",
        ".venv",
        "venv",
    }
)

#: HF cache 里真实权重所在的子目录形态
HF_SNAPSHOT_SUBDIR = Path("snapshots")


def is_valid_weight_dir(path: Path) -> bool:
    """目录包含 config.json 等标记文件即视为有效 bge 权重。"""
    return path.is_dir() and any((path / marker).is_file() for marker in WEIGHT_MARKER_FILES)


def iter_candidate_dirs(root: Path) -> list[Path]:
    """在 root 下按名字模式搜候选目录（受 MAX_DEPTH 与 PRUNED_DIRNAMES 限制）。"""
    hits: list[Path] = []
    root_depth = len(root.parts)
    for current, dirnames, _filenames in os.walk(root, onerror=lambda _e: None):
        # 防御性裁剪：敏感与无关目录一律不进入（不枚举、不读内容）
        dirnames[:] = [
            name for name in dirnames if name.lower() not in PRUNED_DIRNAMES
        ]
        here = Path(current)
        if len(here.parts) - root_depth >= MAX_DEPTH:
            dirnames[:] = []  # 不再下探
            continue
        for name in list(dirnames):
            if any(pattern.search(name) for pattern in NAME_PATTERNS):
                candidate = here / name
                if is_valid_weight_dir(candidate):
                    hits.append(candidate)
                else:
                    # HF cache 目录（models--BAAI--bge-*）权重在 snapshots/<rev>/ 下
                    snapshots = candidate / HF_SNAPSHOT_SUBDIR
                    if snapshots.is_dir():
                        for revision in snapshots.iterdir():
                            if is_valid_weight_dir(revision):
                                hits.append(revision)
    return hits


def find_weights() -> list[Path]:
    """完整探测：env 固化值优先，其次各扫描根。"""
    hits: list[Path] = []

    env_value = os.environ.get("EMBEDDING_MODEL_PATH", "").strip()
    if env_value:
        path = Path(env_value)
        if is_valid_weight_dir(path):
            print(f"[HIT] ① .env/环境变量已固化且有效：{path}")
            hits.append(path)
        else:
            print(f"[MISS] ① .env/环境变量 EMBEDDING_MODEL_PATH={env_value} 无效（缺 config.json）")

    if hits:
        return hits

    seen: set[str] = set()
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        print(f"[SCAN] ② 扫描 {root}（≤{MAX_DEPTH} 层）…")
        for hit in iter_candidate_dirs(root):
            if str(hit).lower() in seen:
                continue
            seen.add(str(hit).lower())
            print(f"[HIT] ② {hit}")
            hits.append(hit)
            if len(hits) >= 3:
                return hits
    return hits


def suggest_download() -> str:
    """输出下载命令（不执行——需人工确认后手动跑）。"""
    lines = [
        "未在本机发现 bge-small-zh-v1.5 权重。下载命令（确认后执行，约 100MB）：",
        "  PowerShell:",
        '    $env:HF_ENDPOINT = "https://hf-mirror.com"',
        "    hf download BAAI/bge-small-zh-v1.5 --local-dir "
        + str(PROJECT_ROOT / "data" / "models" / "bge-small-zh-v1.5"),
        "  （hf 命令来自 huggingface_hub[cli]；未安装时先：uv pip install -U \"huggingface_hub[cli]\"）",
    ]
    return "\n".join(lines)


def backfill_env(path_value: str) -> None:
    """把命中路径回填 .env 的 EMBEDDING_MODEL_PATH（幂等：已存在则替换）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print("[WARN] .env 不存在，跳过回填（请人工创建）")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("EMBEDDING_MODEL_PATH="):
            lines[index] = f"EMBEDDING_MODEL_PATH={path_value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"EMBEDDING_MODEL_PATH={path_value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[BACKFILL] .env 的 EMBEDDING_MODEL_PATH 已回填：{path_value}")


def main() -> int:
    print("=" * 64)
    print("bge-small-zh-v1.5 权重探测（只探测，不下载）")
    print("=" * 64)
    hits = find_weights()
    print("-" * 64)
    if hits:
        best = hits[0]
        print(f"结论：命中 {len(hits)} 处，采用第一处：{best}")
        print("验证要点：config.json / modules.json 在位即判定有效（tokenizers 等随目录携带）")
        backfill_env(str(best))
        return 0
    print(suggest_download())
    print("结论：未命中 —— 等确认后执行上述下载命令，再重跑本脚本回填 .env")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
