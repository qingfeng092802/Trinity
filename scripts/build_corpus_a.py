#!/usr/bin/env python
"""语料方案 A（m3_design.md §8.15）落盘：把 CMRC 余下 2,051 篇当干扰篇补进语料，**题集一个字不动**。

一次做完三件事：

1. **补语料** → ``evaluation/fixtures_cmrc_a/``：seed=7 的 1,000 篇入库集 + ``全部唯一 passage −
   200 篇留出`` = 3,051 篇，正文与文件名沿用 :mod:`build_golden_set` 的同一份 ``read_cmrc``，
   所以与现行 1,000 篇逐字节相同。现行目录**只读**，且同名文件逐个比对，内容不一致就退出码 1
   —— 这条是 §8.15 里"不能悄悄换语料"那句的技术版本。
2. **审计拒答集** → ``evaluation/dataset/refusal_audit_a.json``：留出协议的定义是"答案 span 不在
   *入库语料* 里"，语料一拉满就必然有一部分拒答题的答案重新变得字面可得（判据与建题集时同一条：
   **任一**答案变体命中即算脏）。逐题列出命中的篇章，Phase B 的"正确拒答率"按
   ``refusal_total − dirty_count`` 这个分母读，否则脏题会把结论压低。
3. **清单** → ``evaluation/dataset/corpus_a_manifest.json``：3,051 个 doc-key + 12 位指纹。
   **语料目录本身不入库**（14 MB 文本一旦进 git 历史就撤不掉），入库的是这份清单 ——
   有 ``data/cmrc/*.parquet`` 时一条命令再生，``--audit-only`` 则逐 key 校验目录与清单是否一致。

用法::

    python scripts/build_corpus_a.py --dry-run      # 只看会写什么、脏几道，不落盘
    python scripts/build_corpus_a.py                # 落盘（需要 data/cmrc/*.parquet）
    python scripts/build_corpus_a.py --audit-only   # 语料已在：校验 key 清单 + 重算拒答审计（不读 parquet）

退出码：0 成功；1 与既有语料冲突 / 题集缺字段 / 补完之后篇数不增（说明 parquet 变了）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from build_golden_set import (  # noqa: E402
    DEFAULT_CORPUS_DOCS,
    DEFAULT_HELD_DOCS,
    DEFAULT_SEED,
    FILE_PREFIX,
    QAPair,
    _resolve_dir,
    answer_corpus_docs,
    read_cmrc,
    split_docs,
)

BASE_FIXTURES = PROJECT_ROOT / "evaluation" / "fixtures_cmrc"
A_FIXTURES = PROJECT_ROOT / "evaluation" / "fixtures_cmrc_a"
DATASET = PROJECT_ROOT / "evaluation" / "dataset" / "golden_a_cmrc300.jsonl"
AUDIT = PROJECT_ROOT / "evaluation" / "dataset" / "refusal_audit_a.json"
MANIFEST = PROJECT_ROOT / "evaluation" / "dataset" / "corpus_a_manifest.json"


def key_digest(keys: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()[:12]


def check_manifest(path: Path, docs: dict[str, str]) -> int:
    """语料目录必须与清单里的 doc-key 集合完全一致 —— 少一篇、多一篇都算换语料。"""
    if not path.exists():
        print(f"[warn] 没有清单 {path.name}，跳过一致性校验（第一次跑就是没有，正常）")
        return 0
    expected = set(json.loads(path.read_text(encoding="utf-8"))["a_docs"])
    missing, extra = sorted(expected - set(docs)), sorted(set(docs) - expected)
    if missing or extra:
        print(f"[error] 语料与清单不符：缺 {len(missing)} 篇 {missing[:3]} / 多 {len(extra)} 篇 {extra[:3]}")
        return 1
    print(f"[info] 语料 {len(docs)} 篇与清单逐 key 相符（指纹 {key_digest(expected)}）")
    return 0


def read_corpus_dir(path: Path) -> dict[str, str]:
    """把一个语料目录读成 ``{doc_key: 正文}``，审计只认盘上真实存在的东西。"""
    docs: dict[str, str] = {}
    for file in sorted(path.glob(f"{FILE_PREFIX}*.md")):
        docs[file.name[len(FILE_PREFIX):-3]] = file.read_text(encoding="utf-8")
    if not docs:
        raise SystemExit(f"{path} 里一篇语料都没有，先去掉 --audit-only 补语料")
    return docs


def load_refusals(path: Path) -> tuple[list[QAPair], list[str]]:
    """题集里的拒答题 → ``(与答案判据对齐的 QAPair 列表, 同序 qid 列表)``。"""
    items: list[QAPair] = []
    qids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "refusal":
            continue
        variants = [str(a).strip() for a in (row.get("ground_truth") or []) if str(a).strip()]
        qid = str(row.get("id") or "")
        if not variants or not qid:
            raise SystemExit(f"拒答题字段不全（要 id + 非空 ground_truth）：{qid or row}")
        items.append(
            QAPair(
                doc=str(row.get("heldout_document") or "")[len(FILE_PREFIX):-3],
                question=str(row.get("query") or ""),
                answers=variants,
                answer_start=[int(x) for x in (row.get("answer_start") or [])],
                source=str(row.get("source") or ""),
            )
        )
        qids.append(qid)
    if not items:
        raise SystemExit(f"{path} 里没有 type=refusal 的行")
    return items, qids


def emit_corpus(
    passages: dict[str, str],
    a_docs: set[str],
    out_dir: Path,
    base_dir: Path,
    *,
    dry_run: bool = False,
) -> int:
    """写方案 A 的语料目录；返回退出码（与既有语料对不上 = 1）。"""
    if base_dir.is_dir():
        base_docs = read_corpus_dir(base_dir)
        missing = sorted(set(base_docs) - a_docs)
        changed = sorted(d for d, text in base_docs.items() if passages.get(d) != text)
        if missing or changed:
            print(
                f"[error] 现行语料 {base_dir.name}/ 与 parquet 对不上："
                f"缺 {missing[:3]} / 正文不一致 {changed[:3]} → 先查是不是有人改过语料"
            )
            return 1
        print(f"[info] 现行 {len(base_docs)} 篇逐字节复核通过（本脚本不写这个目录）")
    conflicts: list[str] = []
    for doc in sorted(a_docs):
        target = out_dir / f"{FILE_PREFIX}{doc}.md"
        text = passages[doc]
        if target.exists() and target.read_text(encoding="utf-8") != text:
            conflicts.append(target.name)
    if conflicts:
        print(f"[error] {len(conflicts)} 个同名文件内容与 CMRC 不一致，拒绝覆盖：{conflicts[:5]}")
        return 1
    if dry_run:
        new = sum(1 for doc in a_docs if not (out_dir / f"{FILE_PREFIX}{doc}.md").exists())
        print(f"[dry-run] 不落盘。{len(a_docs)} 篇 → {out_dir}（其中需新写 {new} 篇）")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for doc in sorted(a_docs):
        target = out_dir / f"{FILE_PREFIX}{doc}.md"
        if not target.exists():
            target.write_text(passages[doc], encoding="utf-8")
            written += 1
    print(f"[info] 语料 {len(a_docs)} 篇就位 → {out_dir.name}/（本次新写 {written} 篇）")
    return 0


def build_audit(
    items: list[QAPair],
    qids: list[str],
    docs: dict[str, str],
    **meta: Any,
) -> dict[str, Any]:
    hits = answer_corpus_docs(items, set(docs), docs)
    dirty = [
        {"qid": qid, "query": item.question, "heldout_document": f"{FILE_PREFIX}{item.doc}.md",
         "hit_docs": sorted(found)}
        for item, qid, found in zip(items, qids, hits)
        if found
    ]
    return {
        **meta,
        "refusal_total": len(items),
        "dirty_count": len(dirty),
        "dirty_ratio": round(len(dirty) / max(len(items), 1), 4),
        "clean_count": len(items) - len(dirty),
        "dirty": dirty,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="语料方案 A：补干扰篇 + 审计拒答集（题集一个字不动）")
    parser.add_argument("--cmrc-dir", default="data/cmrc", help="cmrc_{train,validation}*.parquet 所在目录")
    parser.add_argument("--splits", default="train,validation")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="必须与建题集时同一个 seed")
    parser.add_argument("--corpus-docs", type=int, default=DEFAULT_CORPUS_DOCS)
    parser.add_argument("--held-docs", type=int, default=DEFAULT_HELD_DOCS)
    parser.add_argument("--fixtures-out", default=str(A_FIXTURES), help="方案 A 语料目录")
    parser.add_argument("--base-fixtures", default=str(BASE_FIXTURES), help="现行 1,000 篇目录（只读校验）")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--audit-out", default=str(AUDIT))
    parser.add_argument("--manifest-out", default=str(MANIFEST), help="doc-key 清单（语料目录不入库，靠它定基准）")
    parser.add_argument("--audit-only", action="store_true", help="语料已就位，只重算审计（不读 parquet）")
    parser.add_argument("--dry-run", action="store_true", help="只看会写什么、脏几道，不落盘")
    args = parser.parse_args(argv)

    out_dir = _resolve_dir(args.fixtures_out)
    dataset = _resolve_dir(args.dataset)
    code = 0
    if args.audit_only:
        docs = read_corpus_dir(out_dir)
        code = check_manifest(_resolve_dir(args.manifest_out), docs)
    else:
        _, passages = read_cmrc(_resolve_dir(args.cmrc_dir),
                                [s.strip() for s in args.splits.split(",") if s.strip()])
        corpus_docs, held_docs = split_docs(
            list(passages), seed=args.seed, corpus_n=args.corpus_docs, held_n=args.held_docs
        )
        if len(passages) - len(held_docs) <= len(corpus_docs):
            raise SystemExit(
                f"补完只有 {len(passages) - len(held_docs)} 篇，不比现行 {len(corpus_docs)} 篇多"
                " —— parquet 被换小了？"
            )
        a_docs = set(passages) - held_docs
        print(
            f"[info] {len(passages)} 篇唯一 passage = 入库 {len(corpus_docs)} + 干扰 "
            f"{len(a_docs) - len(corpus_docs)}；留出 {len(held_docs)} 篇仍然不入库"
        )
        code = emit_corpus(passages, a_docs, out_dir, _resolve_dir(args.base_fixtures),
                           dry_run=args.dry_run)
        docs = (
            read_corpus_dir(out_dir)
            if not args.dry_run
            else {doc: passages[doc] for doc in a_docs}
        )
        if not args.dry_run:
            code = check_manifest(_resolve_dir(args.manifest_out), docs) or code

    items, qids = load_refusals(dataset)
    audit = build_audit(
        items,
        qids,
        docs,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        tool="scripts/build_corpus_a.py",
        dataset=dataset.name,
        corpus_dir=out_dir.name,
        corpus_docs=len(docs),
        seed=args.seed,
        rule="拒答题的任一答案变体在语料正文里字面出现即判脏（与 build_golden_set 同一条判据）",
    )
    print(
        f"[info] 拒答题 {audit['refusal_total']} 道 → 在 {audit['corpus_docs']} 篇语料下"
        f"已可字面作答 {audit['dirty_count']} 道（{audit['dirty_ratio']:.1%}）："
        f"{[d['qid'] for d in audit['dirty']]}"
    )
    print(f"        ⇒ Phase B 的拒答率分母读 {audit['clean_count']}，不是 {audit['refusal_total']}")
    if args.dry_run:
        print("[dry-run] 不落盘")
        return code
    audit_out = _resolve_dir(args.audit_out)
    audit_out.parent.mkdir(parents=True, exist_ok=True)
    audit_out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 审计 → {audit_out.relative_to(PROJECT_ROOT)}")
    if not args.audit_only:
        manifest_out = _resolve_dir(args.manifest_out)
        manifest_out.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "tool": "scripts/build_corpus_a.py",
                    "splits_used": args.splits,
                    "seed": args.seed,
                    "tracked_corpus_docs": args.corpus_docs,
                    "held_docs": args.held_docs,
                    "fixtures": out_dir.name,
                    "a_docs_total": len(docs),
                    "a_key_digest": key_digest(set(docs)),
                    "a_docs": sorted(docs),
                    "refusal_audit": audit_out.name,
                    "dirty_refusals": audit["dirty_count"],
                    "note": "语料目录本身不入库（见 .gitignore），有 data/cmrc/*.parquet 时用本脚本"
                            "一条命令再生；doc-key 集合以本清单为准，跑 --audit-only 会逐 key 校验。",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            f"[info] 清单 → {manifest_out.relative_to(PROJECT_ROOT)}"
            f"（{len(docs)} 个 doc-key，指纹 {key_digest(set(docs))}）"
        )
    return code


__all__ = ["build_audit", "emit_corpus", "load_refusals", "main", "read_corpus_dir"]

if __name__ == "__main__":
    sys.exit(main())
