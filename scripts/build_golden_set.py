#!/usr/bin/env python
"""Golden Set 构建（M3 · T1）：CMRC2018 → 轨道 A 语料 + 题目 + 溯源清单。

口径来源（m3_design.md D5 / D6；下列百分比都能由本脚本自身的判据复算，
2026-09-20 已复算过一遍，早期探针给的 19.7%/84.7% 已按复算值改掉）：

* 语料 = CMRC train+validation 合并、**按 passage 去重**（CMRC 一行一题，同一篇正文被
  复制多份，不去重会把语料量虚高约 4 倍）→ seed 固定切 1,000 篇入库 + 200 篇留出；
* **拒答题构造协议**：留出 200 篇不入库 ⇒ 其下问题即库外题。但实测 **16.8%**（141/837）
  的留出题，其标准答案 span 本来就出现在入库语料里 —— 不过滤就有约 1/6 是「伪拒答」，
  拒答率指标被直接污染。故伪拒答过滤默认开，且剔除量写进清单可查；
* **事实题超采模糊题**：实测 86.6% 的入库事实题答案 span 全库唯一，字面即可唯一定位，
  等于 BM25 主场。为给向量/混合臂留出区分度，事实题按 ``--ambiguous-ratio``
  主动超采「答案 span 出现在 ≥2 篇」的那 13.4%，默认 40%；
* 多跳题**不在本脚本范围**：CMRC 是单 passage 抽取式，造不出真多跳。轨道 B 的 50 题
  （多跳 30 + 术语 15 + 事实 5，见 m3_design.md D6 的分配表）走人工，要等你提供 3–5 份
  长文档才出得来，届时产物另存 ``evaluation/dataset/golden_trackB_*.jsonl``（**目前还没有这个文件**）。

产物（seed 固定 ⇒ 逐字节可复现）::

    <out>/fixtures_cmrc/cmrc_<DOCID>.md    轨道 A 语料（1 篇 = 1 文件 = 1 chunk）
    <out>/dataset/golden_a_cmrc.jsonl      轨道 A 题目（factual / term / refusal）
    <out>/dataset/golden_manifest.json     溯源清单（seed、池子大小、剔除量、配比、指纹）

JSONL 一行一条，字段同时兼容 M2 的 ``retrieval_eval``（``expected_document``）
与 M3 消融 runner（``expected_doc_ids``）::

    {"id":"A-factual-001","track":"A","type":"factual","query":"...","ground_truth":["哥吉拉"],
     "expected_doc_ids":["TRAIN_837"],"expected_document":"cmrc_TRAIN_837.md",
     "heldout_document":null,"answer_start":[1],"source":"cmrc2018:train"}

拒答题（``type=refusal``）的 ``expected_doc_ids`` 为 ``[]``、``expected_document`` 为
``null`` —— 它的正确期望是「检索不到任何东西」，留出篇章只记在 ``heldout_document`` 里。

用法::

    python scripts/build_golden_set.py --dry-run     # 只看配比，不落盘
    python scripts/build_golden_set.py               # 正式生成
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ------------------------------- 默认口径 ---------------------------------- #
#: 语料/留出切分（D6）
DEFAULT_SEED = 7
DEFAULT_CORPUS_DOCS = 1000
DEFAULT_HELD_DOCS = 200

#: 轨道 A 题型配比（轨道 B 人工补，两轨合计 150，见 m3_design.md D6 的分配表）
DEFAULT_FACTUAL = 55
DEFAULT_TERM = 15
DEFAULT_REFUSAL = 30

#: 事实题里「答案 span 非全库唯一」的目标占比
DEFAULT_AMBIGUOUS_RATIO = 0.4

#: 术语/编号题判据：答案含数字或拉丁串（型号、条款号、"4 倍"这类），靠 BM25 字面精确匹配
TERM_PATTERN = re.compile(r"[0-9０-９]|[A-Za-z]{2,}")

#: CMRC id 形如 DEV_8_QUERY_3 / TRAIN_2619_QUERY_0，前两段是篇级键
DOC_KEY_PATTERN = re.compile(r"^([A-Z]+_\d+)_")

#: 同一篇最多出几题（保题目多样性，别让 30 道拒答题全砸在几篇百科上）
PER_DOC_CAP = 2

#: 干净拒答池最少应为需求题数的该倍数，不足则告警
MIN_REFUSAL_POOL_FACTOR = 4

#: 语料文件名前缀；expected_document 由它拼，避免两处手写歪
FILE_PREFIX = "cmrc_"

#: 字符 ↔ token 换算系数，与 rag/splitter.py 的 CHARS_PER_TOKEN 同口径
CHARS_PER_TOKEN = 1.6


@dataclass(slots=True)
class QAPair:
    """一条 CMRC 标注（题目级，正文不放进来——语料过大，按 doc 去 passages 查）。"""

    doc: str
    question: str
    answers: list[str]
    answer_start: list[int]
    source: str

    @property
    def main_answer(self) -> str:
        return self.answers[0] if self.answers else ""


@dataclass(slots=True)
class Pool:
    """一个题型的抽样池：需求/实抽/池大小/剔除量全部留痕，报告要引用。"""

    want: int
    picked: int = 0
    pool_size: int = 0
    dropped_leak: int = 0
    notes: list[str] = field(default_factory=list)


# ------------------------------- 读取层 ----------------------------------- #
def _resolve_dir(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _iter_parquet(cmrc_dir: Path, splits: list[str], columns: list[str]):
    """按 split 逐个 yield (split, row)。只读需要的列，别把整表 ×2 拉进内存。"""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(f"需要 pyarrow 读 parquet（pip install pyarrow）：{exc}") from exc

    for split in splits:
        files = sorted(cmrc_dir.glob(f"cmrc_{split}*.parquet"))
        if not files:
            raise SystemExit(f"找不到 {split} 的 parquet：{cmrc_dir}/cmrc_{split}*.parquet")
        for path in files:
            for row in pq.ParquetFile(path).read(columns).to_pylist():
                yield split, row


def doc_key_of(row_id: str) -> str:
    """从 CMRC 行 id 抽篇级键；抽不出来就是数据格式变了，必须炸得早。"""
    match = DOC_KEY_PATTERN.match(row_id)
    if not match:
        raise ValueError(f"无法从 CMRC id 解析篇级键：{row_id!r}")
    return match.group(1)


def read_cmrc(cmrc_dir: Path, splits: list[str]) -> tuple[list[QAPair], dict[str, str]]:
    """一次遍历同时得到（题目列表, 篇级正文表）。

    无答案行直接丢弃 —— 该镜像里根本没有不可回答题（实测空答案 0 行），
    真出现空答案说明数据版本变了，靠留出协议自己造拒答题。
    """
    items: list[QAPair] = []
    passages: dict[str, str] = {}
    for split, row in _iter_parquet(cmrc_dir, splits, ["id", "context", "question", "answers"]):
        doc = doc_key_of(str(row["id"]))
        passages.setdefault(doc, str(row["context"]).strip())
        answers = [str(t).strip() for t in (row["answers"].get("text") or []) if str(t).strip()]
        if not answers:
            continue
        items.append(
            QAPair(
                doc=doc,
                question=str(row["question"]).strip(),
                answers=answers,
                answer_start=[int(x) for x in (row["answers"].get("answer_start") or [])],
                source=f"cmrc2018:{split}",
            )
        )
    if not items or not passages:
        raise SystemExit("CMRC 读出来是空的，检查 parquet 是否损坏")
    return items, passages


def split_docs(
    docs: list[str], *, seed: int, corpus_n: int, held_n: int
) -> tuple[set[str], set[str]]:
    """seed 固定切分：入库语料篇集与留出题源篇集，二者不交。"""
    ordered = sorted(docs)
    random.Random(seed).shuffle(ordered)
    if corpus_n + held_n > len(ordered):
        raise SystemExit(f"语料池只有 {len(ordered)} 篇，不够切 {corpus_n}+{held_n}")
    return set(ordered[:corpus_n]), set(ordered[corpus_n : corpus_n + held_n])


# ------------------------------- 判据层 ----------------------------------- #
def answer_corpus_docs(items: list[QAPair], corpus_docs: set[str], passages: dict[str, str]) -> list[set[str]]:
    """每题的**任一**可接受答案变体命中了哪些入库篇章。返回与 items 等长的集合列表。

    必须按「任一变体」算而不是只按主答案：判分接受 ``answers.text`` 里的任何一个，
    所以只要有一个变体在库里字面可得，这道留出题就不是干净的库外题。
    只查主答案会少剔掉一批（同一份数据实测 137 vs 141 条），拒答率被虚高。

    两个判据共用它：|命中| == 1 → 字面唯一定位（BM25 主场）；|命中| == 0 → 真库外。
    13k 题 × 1k 篇 × 去重后 1~3 个变体的子串扫描，本机十几秒量级，一次跑完可接受。
    """
    corpus = [(doc, passages[doc]) for doc in sorted(corpus_docs)]
    hits: list[set[str]] = []
    for item in items:
        variants = list(dict.fromkeys(a for a in item.answers if a))
        if not variants:
            hits.append(set())
            continue
        hits.append({doc for doc, text in corpus if any(v in text for v in variants)})
    return hits


def is_term(item: QAPair) -> bool:
    return any(TERM_PATTERN.search(answer) for answer in item.answers)


# ------------------------------- 抽样层 ----------------------------------- #
def sample_spread(candidates: list[QAPair], *, want: int, rng: random.Random) -> list[QAPair]:
    """按篇多样性抽样：先每篇出一题，不够再放宽到第二题，避免题源扎堆。"""
    if want <= 0 or not candidates:
        return []
    by_doc: dict[str, list[QAPair]] = {}
    for item in candidates:
        by_doc.setdefault(item.doc, []).append(item)
    for bucket in by_doc.values():
        rng.shuffle(bucket)
    doc_keys = sorted(by_doc)
    rng.shuffle(doc_keys)

    picked: list[QAPair] = []
    chosen_ids: set[int] = set()
    for round_no in range(1, PER_DOC_CAP + 1):
        for doc in doc_keys:
            taken_this_round = 0
            for item in by_doc[doc]:
                if len(picked) >= want:
                    return picked
                if id(item) in chosen_ids or taken_this_round >= round_no:
                    continue
                picked.append(item)
                chosen_ids.add(id(item))
                taken_this_round += 1
    return picked


# ------------------------------- 组装层 ----------------------------------- #
def build(
    items: list[QAPair],
    passages: dict[str, str],
    corpus_docs: set[str],
    held_docs: set[str],
    *,
    seed: int,
    factual: int,
    term: int,
    refusal: int,
    ambiguous_ratio: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """产出（题目行, 清单）。"""
    rng = random.Random(seed)
    hits = answer_corpus_docs(items, corpus_docs, passages)

    in_corpus = [(i, it) for i, it in enumerate(items) if it.doc in corpus_docs]
    held = [(i, it) for i, it in enumerate(items) if it.doc in held_docs]

    # ---- 拒答：留出篇 ∧ 答案 span 在入库语料里零命中 ----
    refusal_pool = [(i, it) for i, it in held if not hits[i]]
    leak_dropped = len(held) - len(refusal_pool)
    refusal_picked = sample_spread([it for _, it in refusal_pool], want=refusal, rng=rng)
    pool_size_needed = refusal * MIN_REFUSAL_POOL_FACTOR

    # ---- 事实：先剔术语型，再按 span 唯一性分桶超采模糊题 ----
    factual_all = [(i, it) for i, it in in_corpus if not is_term(it)]
    ambiguous = [it for i, it in factual_all if len(hits[i]) > 1]
    unique = [it for i, it in factual_all if len(hits[i]) == 1]
    want_ambiguous = min(round(factual * ambiguous_ratio), len(ambiguous))
    fact_ambiguous = sample_spread(ambiguous, want=want_ambiguous, rng=rng)
    fact_unique = sample_spread(unique, want=factual - len(fact_ambiguous), rng=rng)
    fact_picked = fact_ambiguous + fact_unique
    ambiguous_taken = len(fact_ambiguous)

    # ---- 术语：答案含数字/拉丁串，且字面能在入库语料里定位 ----
    term_pool = [it for i, it in in_corpus if is_term(it) and hits[i]]
    term_picked = sample_spread(term_pool, want=term, rng=rng)

    rows: list[dict[str, Any]] = []

    def emit(question_type: str, chosen: list[QAPair], *, answerable: bool = True) -> None:
        """answerable=False（拒答题）时**不写 expected_document / expected_doc_ids**。

        拒答题的正确期望是「什么都检索不到」，所以 expected_doc_ids 必须是空列表；
        留出题源那篇只作为出处记在 heldout_document 里。若把它的 id 写进
        expected_document，检索指标会把「命中留出篇章」当成正确，而它永远不在库内
        （M2 的 retrieval_eval 按 document_name 等值匹配同样会误判成 0 命中）。
        """
        for item in chosen:
            stem = f"{FILE_PREFIX}{item.doc}.md"
            rows.append(
                {
                    "id": f"A-{question_type}-{len(rows) + 1:03d}",
                    "track": "A",
                    "type": question_type,
                    "query": item.question,
                    "ground_truth": item.answers,
                    "expected_doc_ids": [item.doc] if answerable else [],
                    "expected_document": stem if answerable else None,
                    "heldout_document": None if answerable else stem,
                    "answer_start": item.answer_start,
                    "source": item.source,
                }
            )

    emit("factual", fact_picked)
    emit("term", term_picked)
    emit("refusal", refusal_picked, answerable=False)

    corpus_chars = sum(len(passages[d]) for d in corpus_docs)
    pools = {
        "factual": Pool(
            want=factual,
            picked=len(fact_picked),
            pool_size=len(factual_all),
            notes=[
                f"模糊池（答案 span 出现在 ≥2 篇）{len(ambiguous)} 篇题 / 唯一池 {len(unique)} 题",
                f"目标超采比例 {ambiguous_ratio:.0%} → 事实题里实际模糊题 {ambiguous_taken} 道"
                f"（{ambiguous_taken / max(len(fact_picked), 1):.0%}）",
            ],
        ),
        "term": Pool(want=term, picked=len(term_picked), pool_size=len(term_pool)),
        "refusal": Pool(
            want=refusal,
            picked=len(refusal_picked),
            pool_size=len(refusal_pool),
            dropped_leak=leak_dropped,
            notes=[
                f"留出题 {len(held)} 条中 {leak_dropped} 条"
                f"（{leak_dropped / max(len(held), 1):.1%}）答案 span 命中入库语料，判为伪拒答已剔除",
            ],
        ),
    }

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tool": "scripts/build_golden_set.py",
        "dataset": "hfl/cmrc2018 (cc-by-sa-4.0) via hf-mirror",
        "seed": seed,
        "splits_used": "train+validation",
        "corpus_docs": len(corpus_docs),
        "held_docs": len(held_docs),
        "corpus_chars": corpus_chars,
        "corpus_tokens_est": round(corpus_chars / CHARS_PER_TOKEN),
        "rows_total": len(rows),
        "pools": {name: asdict(p) for name, p in pools.items()},
        "track_b": "多跳 30 + 术语 15 + 事实 5 走人工（等长文档语料），不在本脚本内",
    }
    if len(refusal_picked) < refusal:
        manifest["warnings"] = [
            f"干净拒答题只抽到 {len(refusal_picked)}/{refusal}，请增大 --held-docs（池子需 ≥{pool_size_needed}）"
        ]
    return rows, manifest


def write_outputs(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    passages: dict[str, str],
    corpus_docs: set[str],
    out_dir: Path,
    *,
    dry_run: bool,
) -> None:
    fixtures_dir = out_dir / "fixtures_cmrc"
    dataset_dir = out_dir / "dataset"
    if dry_run:
        print(f"[dry-run] 不落盘。语料 → {fixtures_dir}，题目 → {dataset_dir / 'golden_a_cmrc.jsonl'}")
        return
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for doc in sorted(corpus_docs):
        (fixtures_dir / f"{FILE_PREFIX}{doc}.md").write_text(passages[doc], encoding="utf-8")
    with (dataset_dir / "golden_a_cmrc.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (dataset_dir / "golden_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def render_summary(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = ["=" * 72, " Golden Set · 轨道 A（CMRC）", "=" * 72]
    lines.append(
        f" 语料 : {manifest['corpus_docs']} 篇 / {manifest['corpus_chars']:,} 字 /"
        f" ≈{manifest['corpus_tokens_est']:,} tokens（1 篇 ≈ 1 chunk）"
    )
    lines.append(f" 留出 : {manifest['held_docs']} 篇（拒答题源） | seed={manifest['seed']}")
    lines.append(f" 题量 : {manifest['rows_total']} 道（轨道 B 另计）")
    for name in ("factual", "term", "refusal"):
        pool = manifest["pools"][name]
        lines.append(
            f"   {name:<8} {pool['picked']:>3}/{pool['want']} 道   池={pool['pool_size']:>5}   "
            f"伪拒答剔除={pool['dropped_leak']}"
        )
        for note in pool["notes"]:
            lines.append(f"            · {note}")
    for warning in manifest.get("warnings", []):
        lines.append(f"   ⚠️  {warning}")
    digest = hashlib.sha256(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows).encode("utf-8")
    ).hexdigest()[:12]
    lines.append(f" 数据集指纹 : {digest}（同 seed 复跑必须一致，不一致即随机性失控）")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 M3 Golden Set 轨道 A（CMRC2018）")
    parser.add_argument("--cmrc-dir", default="data/cmrc", help="cmrc_{train,validation}*.parquet 所在目录")
    parser.add_argument("--splits", default="train,validation", help="逗号分隔；test 是盲测集，默认不用")
    parser.add_argument("--out-dir", default="evaluation", help="产物根目录（下建 fixtures_cmrc/ 与 dataset/）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--corpus-docs", type=int, default=DEFAULT_CORPUS_DOCS)
    parser.add_argument("--held-docs", type=int, default=DEFAULT_HELD_DOCS)
    parser.add_argument("--factual", type=int, default=DEFAULT_FACTUAL)
    parser.add_argument("--term", type=int, default=DEFAULT_TERM)
    parser.add_argument("--refusal", type=int, default=DEFAULT_REFUSAL)
    parser.add_argument("--ambiguous-ratio", type=float, default=DEFAULT_AMBIGUOUS_RATIO)
    parser.add_argument("--dry-run", action="store_true", help="只算配比不落盘")
    args = parser.parse_args(argv)

    cmrc_dir = _resolve_dir(args.cmrc_dir)
    out_dir = _resolve_dir(args.out_dir)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]

    items, passages = read_cmrc(cmrc_dir, splits)
    corpus_docs, held_docs = split_docs(
        list(passages), seed=args.seed, corpus_n=args.corpus_docs, held_n=args.held_docs
    )
    print(f"[info] {len(items)} 题 / {len(passages)} 篇唯一 passage → 入库 {len(corpus_docs)}，留出 {len(held_docs)}")

    rows, manifest = build(
        items,
        passages,
        corpus_docs,
        held_docs,
        seed=args.seed,
        factual=args.factual,
        term=args.term,
        refusal=args.refusal,
        ambiguous_ratio=args.ambiguous_ratio,
    )
    write_outputs(rows, manifest, passages, corpus_docs, out_dir, dry_run=args.dry_run)
    print(render_summary(manifest, rows))
    return 0


__all__ = ["QAPair", "build", "doc_key_of", "main", "read_cmrc", "split_docs"]

if __name__ == "__main__":
    sys.exit(main())
