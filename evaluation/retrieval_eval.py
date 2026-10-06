"""检索评测引擎（T05）：种子数据集 → 混合检索 → 命中率指标 → 报告落盘。

口径（m2_design.md §5 T05 / PRD P0-4 验收 2 / G2 出口）：

* **零 LLM 调用**（可断网跑）：只走 parse → split → embed → store → retrieve，
  embedding 用真实本地模型（默认 fastembed bge-small-zh-v1.5）；
* **命中判定**：``document_name == expect_document`` **且** 片段原文含
  ``expect_keywords`` 任一关键词——文档级 + 词级双条件，避免只按文档命中虚高；
* **指标**：top1 / top3 / hit@5 命中率 + MRR（命中排名倒数的均值）；
* **默认三组权重对照**（Q8 固化依据）：0.3/0.7、0.4/0.6、0.5/0.5（bm25:vector），
  另可用 ``--weights`` 追加任意组（如 1.0:0.0 与 0.0:1.0 验证混合生效）；
* **G2 出口门槛只认参照组**（``G2_REFERENCE_WEIGHTS`` = 0.4:0.6）：参照组没在本次扫描里时
  判**"无法判定"**——`g2_gate.evaluable=false`、`passed=false`、`reference_top3_rate=null`，
  CLI 退出码 **2**（0=通过 / 1=跑了但未达门槛 / 2=无法判定）。原先的写法会静默拿
  ``group_results[0]`` 冒充参照组，于是单组 ``--weights 1.0:0.0`` 也能印出
  "G2（0.4:0.6 top-3 = xx% 通过）"并退 0，门禁绿得没有任何依据；
* **报告**：``evaluation/reports/eval_YYYYMMDD_HHMMSS.{json,md}``。

数据集格式（jsonl，每行一条）::

    {"id": "q01", "type": "参数", "query": "六类线弯曲半径要求是多少",
     "expect_document": "zonghebuxian.md", "expect_keywords": ["4 倍"]}

**2026-09-21 口径统一（决策）**：默认语料从「4 篇弱电规程 / 50 题」换成
**与消融实验同一份基线** —— ``evaluation/fixtures_cmrc``（1 000 篇 CMRC2018）
配 ``evaluation/dataset/retrieval_eval_cmrc.jsonl``（70 道可计分题）。

换的理由是硬性的：4 篇文档只有 24 个 chunk，三组权重下 top1/top3/hit5/MRR
**全部 1.0000**，指标贴天花板、零区分度 —— 那样的「100%」没有评测价值，
只会让人觉得系统在玩具数据集上自嗨。

70 而非 100 的原因：源集 ``golden_a_cmrc.jsonl`` 有 30 道拒答题（``expected_doc_ids``
为空），检索层没有 gold 文档可判，与消融脚本剔除拒答题的口径一致
（``hit_at_k is None`` 不进计分集）。派生过程见
``evaluation/dataset/_derive_retrieval_from_cmrc.py``：**纯字段映射 + 逐字校验，
不生成任何新内容**。

原 50 题弱电领域集（``knowledge_eval.jsonl`` + ``evaluation/fixtures``）保留在仓库里，
用 ``--dataset`` / ``--fixtures`` 显式指定即可复跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.constants import DOC_READY  # noqa: E402
from rag.bm25 import BM25Index  # noqa: E402
from rag.embedder import create_embedder, fingerprint_of  # noqa: E402
from rag.parsers import parse  # noqa: E402
from rag.retriever import HybridRetriever  # noqa: E402
from rag.splitter import DocumentSplitter  # noqa: E402
from rag.types import SearchHit  # noqa: E402
from rag.vector_store import create_vector_store  # noqa: E402
from storage.db import Database  # noqa: E402

logger = logging.getLogger(__name__)

#: 默认权重对照组（bm25:vector），Q8 固化依据
DEFAULT_WEIGHT_GROUPS: tuple[tuple[float, float], ...] = ((0.3, 0.7), (0.4, 0.6), (0.5, 0.5))

#: G2 出口门槛：top-3 命中率
G2_TOP3_THRESHOLD = 0.8

#: G2 的参照组（bm25:vector）。门槛只认这一组的读数，标签与匹配都从这里取，
#: 不再在四处各硬写一遍 0.4:0.6（F2-01：原先参照组不在扫描里时会静默回落到
#: `group_results[0]`，拿别的组冒充参照组打绿并退出码 0）。
G2_REFERENCE_WEIGHTS: tuple[float, float] = (0.4, 0.6)

#: 支持 1..1000 检索同 T03 口径
MAX_QUERY_LENGTH = 1000


@dataclass(slots=True)
class EvalItem:
    """一条评测用例。"""

    id: str
    type: str
    query: str
    expect_document: str
    expect_keywords: list[str] = field(default_factory=list)


def load_dataset(path: Path) -> list[EvalItem]:
    """加载 jsonl 数据集；空行跳过，字段缺失即报错（数据集错误要尽早暴露）。"""
    items: list[EvalItem] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            try:
                items.append(
                    EvalItem(
                        id=str(raw["id"]),
                        type=str(raw.get("type", "unknown")),
                        query=str(raw["query"]).strip(),
                        expect_document=str(raw["expect_document"]),
                        expect_keywords=[str(k) for k in raw.get("expect_keywords", [])],
                    )
                )
            except KeyError as exc:
                raise ValueError(f"数据集第 {line_no} 行缺少字段：{exc}") from exc
    if not items:
        raise ValueError(f"数据集为空：{path}")
    return items


def is_hit(hit: SearchHit, item: EvalItem) -> bool:
    """命中判定：文档匹配 **且** 含任一期望关键词（关键词为空则只看文档）。"""
    if hit.document_name != item.expect_document:
        return False
    if not item.expect_keywords:
        return True
    return any(keyword in hit.text for keyword in item.expect_keywords)


def index_fixtures(
    fixtures_dir: Path,
    *,
    settings: Any,
    database: Database,
    embedder: Any,
    store: Any,
) -> dict[str, str]:
    """把 fixtures 目录的文档**同步**索引进评测库（复用 rag 公开 API，不起 worker）。

    Returns:
        ``{filename: document_id}`` 映射。
    """
    splitter = DocumentSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        mode=settings.chunk_mode,
        embedder=embedder,
    )
    fingerprint = embedder.fingerprint()
    indexed: dict[str, str] = {}
    for file_path in sorted(Path(fixtures_dir).iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() not in {".md", ".txt", ".pdf"}:
            continue
        document_id = f"doc-{file_path.stem}"[:32]
        parsed = parse(file_path, document_id)
        chunks = splitter.split(parsed)
        if not chunks:
            logger.warning("评测文档切分后为空，跳过：%s", file_path.name)
            continue
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        database.save_document(
            document_id=document_id,
            filename=file_path.name,
            file_path=str(file_path),
            size_bytes=file_path.stat().st_size,
            format=file_path.suffix.lstrip(".").lower(),
            file_hash=file_hash,
            status=DOC_READY,
        )
        database.save_chunks(
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "seq": chunk.seq,
                    "text": chunk.text,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
                    "token_estimate": chunk.token_estimate,
                }
                for chunk in chunks
            ]
        )
        store.delete_document(document_id)
        vectors = embedder.embed([chunk.text for chunk in chunks])
        store.add(chunks, vectors)
        indexed[file_path.name] = document_id
        logger.info("评测索引完成 %s：%d chunks", file_path.name, len(chunks))
    if not database.get_meta("current_fingerprint"):
        database.set_meta("current_fingerprint", fingerprint)
    return indexed


def make_metadata_loader(database: Database):
    """把命中 chunk 的文本/位置/文档名批量回填（与 KnowledgeService 同口径）。"""

    def loader(chunk_ids: list[str]) -> dict[str, SearchHit]:
        result: dict[str, SearchHit] = {}
        records = database.get_chunks(chunk_ids)
        name_by_doc: dict[str, str] = {}
        for record in records:
            if record.document_id not in name_by_doc:
                document = database.get_document(record.document_id)
                name_by_doc[record.document_id] = (
                    document.filename if document else record.document_id
                )
            result[record.chunk_id] = SearchHit(
                chunk_id=record.chunk_id,
                score=0.0,
                document_id=record.document_id,
                document_name=name_by_doc[record.document_id],
                chunk_seq=record.seq,
                start_char=record.start_char,
                end_char=record.end_char,
                text=record.text,
            )
        return result

    return loader


def evaluate(
    items: list[EvalItem],
    retriever: HybridRetriever,
    loader: Any,
    *,
    weights: tuple[float, float],
    top_k: int,
) -> dict[str, Any]:
    """跑一遍数据集，返回指标 + 逐条明细（top_k 至少 5，recall@5 才有意义）。"""
    recall_k = max(top_k, 5)
    details: list[dict[str, Any]] = []
    ranks: list[int] = []
    for item in items:
        started = time.perf_counter()
        hits = retriever.search(
            item.query[:MAX_QUERY_LENGTH],
            recall_k,
            weights=weights,
            metadata_loader=loader,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        rank = 0  # 0 表示未命中（1-based 排名从 1 起）
        for position, hit in enumerate(hits, start=1):
            if is_hit(hit, item):
                rank = position
                break
        ranks.append(rank)
        # 两路分数均值：权重改变融合排序，各组返回 top5 的两路分数分布不同，
        # 即混合检索生效的组间数字证据（归一化后 top1 分数恒为 1.0，均值才暴露差异）
        detail = {
            "id": item.id,
            "type": item.type,
            "query": item.query,
            "expect_document": item.expect_document,
            "rank": rank,
            "top_score": round(hits[0].score, 4) if hits else 0.0,
            "hit_document": hits[rank - 1].document_name if rank else "",
            "hit_chunk_seq": hits[rank - 1].chunk_seq if rank else -1,
            "took_ms": elapsed_ms,
        }
        if hits:
            detail["bm25_mean"] = round(sum(hit.bm25_score for hit in hits) / len(hits), 4)
            detail["vector_mean"] = round(sum(hit.vector_score for hit in hits) / len(hits), 4)
        details.append(detail)
    total = len(items)
    first_correct = [rank for rank in ranks if rank > 0]
    bm25_means = [detail["bm25_mean"] for detail in details if "bm25_mean" in detail]
    vector_means = [detail["vector_mean"] for detail in details if "vector_mean" in detail]
    return {
        "weights": {"bm25": weights[0], "vector": weights[1]},
        "top_k": recall_k,
        "total": total,
        "top1_rate": round(sum(1 for rank in ranks if rank == 1) / total, 4),
        "top3_rate": round(sum(1 for rank in ranks if 0 < rank <= 3) / total, 4),
        "hit5_rate": round(sum(1 for rank in ranks if 0 < rank <= 5) / total, 4),
        "mrr": round(sum(1.0 / rank for rank in first_correct) / total, 4),
        "bm25_score_mean": round(sum(bm25_means) / len(bm25_means), 4) if bm25_means else 0.0,
        "vector_score_mean": round(sum(vector_means) / len(vector_means), 4) if vector_means else 0.0,
        "details": details,
    }


def _weights_key(pair_or_dict: Any) -> dict[str, float]:
    """把 (bm25, vector) 或 {"bm25":…,"vector":…} 归一成组结果里 `weights` 那种 dict。"""
    if isinstance(pair_or_dict, dict):
        return {"bm25": pair_or_dict["bm25"], "vector": pair_or_dict["vector"]}
    return {"bm25": pair_or_dict[0], "vector": pair_or_dict[1]}


def _label(pair_or_dict: Any) -> str:
    """权重组的显示标签，**从数据取**，不写死。"""
    if isinstance(pair_or_dict, dict):
        return f"{pair_or_dict['bm25']}:{pair_or_dict['vector']}"
    return f"{pair_or_dict[0]}:{pair_or_dict[1]}"


def pick_reference_group(
    group_results: list[dict[str, Any]],
    *,
    reference_weights: tuple[float, float] | dict[str, float] = G2_REFERENCE_WEIGHTS,
) -> dict[str, Any] | None:
    """从本次扫描的组结果里挑出参照组；**没扫到就返回 None，不回落到第一组**。"""
    key = _weights_key(reference_weights)
    return next((result for result in group_results if result["weights"] == key), None)


def build_g2_gate(
    group_results: list[dict[str, Any]],
    *,
    reference_weights: tuple[float, float] | dict[str, float] = G2_REFERENCE_WEIGHTS,
) -> dict[str, Any]:
    """G2 门槛判定（F2-01：参照组缺席时不许打绿）。

    返回的 dict 里 `passed` 只有在**参照组真在本次扫描里**时才可能为 True；
    参照组缺失 ⇒ `evaluable=False` + `reason` 写明"无法判定 G2"，`passed=False`、
    `reference_top3_rate=None`，CLI 退出码 2（与"跑了但未达门槛"的 1 区分开）。
    """
    key = _weights_key(reference_weights)
    reference = pick_reference_group(group_results, reference_weights=reference_weights)
    gate: dict[str, Any] = {
        "threshold": G2_TOP3_THRESHOLD,
        "reference_group": key,
        "evaluable": reference is not None,
        "passed": False,
        "reference_top3_rate": None,
        "scanned_groups": [_label(result["weights"]) for result in group_results],
    }
    if reference is None:
        gate["reason"] = (
            f"本次扫描不含参照组 {_label(key)}（实到 {len(group_results)} 组："
            f"{'、'.join(gate['scanned_groups']) or '无'}），无法判定 G2"
        )
        return gate
    gate["reference_top3_rate"] = reference["top3_rate"]
    gate["passed"] = bool(reference["top3_rate"] >= G2_TOP3_THRESHOLD)
    return gate


def _prepare_env(work_dir: Path) -> None:
    """评测用隔离环境：独立临时库 + 临时知识目录（不污染项目 data/）。"""
    os.environ["DB_URL"] = f"sqlite:///{(work_dir / 'eval.db').as_posix()}"
    os.environ["KNOWLEDGE_DIR"] = str(work_dir / "knowledge")
    from config import reset_settings_cache

    reset_settings_cache()


def run_eval(
    *,
    dataset_path: Path,
    fixtures_dir: Path,
    report_dir: Path,
    weight_groups: list[tuple[float, float]] | None = None,
    top_k: int = 5,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """完整评测流程：隔离环境 → 索引 → 分组评测 → 报告落盘。

    Returns:
        报告 dict（同时写入 ``eval_YYYYMMDD_HHMMSS.{json,md}``）。
    """
    from config import get_settings

    groups = weight_groups or list(DEFAULT_WEIGHT_GROUPS)
    items = load_dataset(dataset_path)
    # ignore_cleanup_errors：Windows 上 SQLite 文件句柄释放存在竞态，清理失败不应掩盖评测结果
    temp_context = (
        tempfile.TemporaryDirectory(prefix="rag_eval_", ignore_cleanup_errors=True)
        if work_dir is None
        else None
    )
    root = Path(temp_context.name) if temp_context else Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    database: Database | None = None
    store: Any | None = None
    try:
        _prepare_env(root)
        settings = get_settings()
        database = Database()
        database.init_db()
        embedder = create_embedder(settings)
        store = create_vector_store(settings, dim=settings.embedding_dim)
        indexed = index_fixtures(
            fixtures_dir, settings=settings, database=database, embedder=embedder, store=store
        )
        logger.info("评测索引就绪：%d 份文档 / %d 条用例", len(indexed), len(items))
        bm25 = BM25Index(userdict=settings.jieba_userdict)
        bm25.rebuild(
            [
                SimpleNamespace(chunk_id=record.chunk_id, text=record.text)
                for record in database.list_all_chunks()
            ]
        )
        retriever = HybridRetriever(
            embedder=embedder,
            store=store,
            bm25=bm25,
            bm25_weight=settings.bm25_weight,
            vector_weight=settings.vector_weight,
        )
        loader = make_metadata_loader(database)

        group_results = [
            evaluate(items, retriever, loader, weights=group, top_k=top_k)
            for group in groups
        ]
    finally:
        # 显式释放连接，否则 Windows 上临时目录清理会因文件句柄未释放而失败
        if store is not None and hasattr(store, "close"):
            try:
                store.close()
            except Exception:  # noqa: BLE001 - 释放失败不影响结果
                logger.debug("评测向量库关闭异常", exc_info=True)
        if database is not None:
            try:
                database.dispose()
            except Exception:  # noqa: BLE001
                logger.debug("评测数据库释放异常", exc_info=True)
        if temp_context is not None:
            temp_context.cleanup()

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": str(dataset_path),
        "dataset_size": len(items),
        "fixtures": [
            path.name for path in sorted(Path(fixtures_dir).iterdir()) if path.is_file()
        ],
        "embedding_model": settings.embedding_model_name,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "groups": group_results,
        "g2_gate": build_g2_gate(group_results),
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"eval_{stamp}.json"
    md_path = report_dir / f"eval_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    report["report_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    logger.info("评测报告已落盘：%s / %s", json_path, md_path)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """报告 dict → Markdown（指标汇总表 + G2 结论 + 逐条明细）。"""
    lines: list[str] = [
        "# 检索评测报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 数据集：{report['dataset']}（{report['dataset_size']} 条）",
        f"- embedding 模型：{report['embedding_model']}",
        f"- 切分：chunk_size={report['chunk_size']} / overlap={report['chunk_overlap']}",
        f"- 种子文档：{'、'.join(report['fixtures'])}",
        "",
        "## 指标汇总",
        "",
        "> 两路均分随权重组变化：权重改变融合排序，各组返回 top5 的分数分布不同，",
        "> 即混合检索生效的组间数字证据（归一化后 top1 分数恒为 1.0，均值才暴露差异；",
        "> 相邻组均分相同说明该两组 top5 排序恰好一致）。权重路由的数学验证",
        "> （score ≡ 凸组合）见 tests/unit/test_rag_retriever.py。",
        "",
        "| 权重 (bm25:vector) | top-1 | top-3 | hit@5 | MRR | BM25 均分 | 向量均分 |",
        "|---|---|---|---|---|---|---|",
    ]
    for group in report["groups"]:
        weights = group["weights"]
        lines.append(
            f"| {weights['bm25']}:{weights['vector']} "
            f"| {group['top1_rate']:.2%} | {group['top3_rate']:.2%} "
            f"| {group['hit5_rate']:.2%} | {group['mrr']:.4f} "
            f"| {group['bm25_score_mean']:.4f} | {group['vector_score_mean']:.4f} |"
        )
    gate = report["g2_gate"]
    reference_label = _label(gate["reference_group"])
    lines += ["", "## G2 出口门槛", ""]
    if gate.get("evaluable", True):
        verdict = "✅ 通过" if gate["passed"] else "❌ 未通过"
        lines.append(
            f"- 参照组 {reference_label} 的 top-3 命中率 **{gate['reference_top3_rate']:.2%}**"
            f"（门槛 ≥ {gate['threshold']:.0%}）→ {verdict}"
        )
    else:
        reason = gate.get("reason", f"本次扫描不含参照组 {reference_label}，无法判定 G2")
        lines += [
            f"- {reason} → ⚠️ 无法判定",
            "- 这一格不写数：参照组没参与本次扫描，其余组不能替它判 G2（`passed=false`、CLI 退出码 2）。",
        ]
    detail_group = pick_reference_group(
        report["groups"], reference_weights=gate["reference_group"]
    )
    if detail_group is None:
        detail_group = report["groups"][0] if report["groups"] else None
        detail_heading = (
            f"## 逐条明细（**非参照组**：本次没有参照组，取扫描到的第一组 "
            f"{_label(detail_group['weights']) if detail_group else '—'}）"
            if detail_group
            else "## 逐条明细（本次无任何组）"
        )
    else:
        detail_heading = f"## 逐条明细（参照组 {_label(detail_group['weights'])}）"
    lines += [
        "",
        detail_heading,
        "",
        "| id | 题型 | 命中排名 | 命中文档 | 首条相关度 |",
        "|---|---|---|---|---|",
    ]
    for group in ([detail_group] if detail_group else []):
        for detail in group["details"]:
            lines.append(
                f"| {detail['id']} | {detail['type']} | "
                f"{detail['rank'] if detail['rank'] else '未命中'} "
                f"| {detail['hit_document'] or '-'} | {detail['top_score']} |"
            )
    return "\n".join(lines) + "\n"


def _parse_weight_groups(raw: list[str] | None) -> list[tuple[float, float]]:
    """解析 ``--weights 0.4:0.6``（可多次传入；不传用默认三组）。"""
    if not raw:
        return list(DEFAULT_WEIGHT_GROUPS)
    groups: list[tuple[float, float]] = []
    for token in raw:
        bm25_part, _, vector_part = token.partition(":")
        groups.append((float(bm25_part), float(vector_part)))
    return groups


def main(argv: list[str] | None = None) -> int:
    """CLI 入口（``scripts/eval_retrieval.py`` 转发到这里）。"""
    parser = argparse.ArgumentParser(description="知识库检索评测（零 LLM 调用）")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evaluation/dataset/retrieval_eval_cmrc.jsonl",
        help="评测数据集（jsonl）；默认与消融同基线（CMRC 1 000 篇 / 70 道可计分题）",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=PROJECT_ROOT / "evaluation/fixtures_cmrc",
        help="种子文档目录；默认 1 000 篇 CMRC，与消融同一份语料",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=PROJECT_ROOT / "evaluation/reports",
        help="报告输出目录",
    )
    parser.add_argument(
        "--weights",
        action="append",
        metavar="BM25:VECTOR",
        help="权重组（可多次传入，如 1.0:0.0；不传跑默认三组对照）",
    )
    parser.add_argument("--top-k", type=int, default=5, help="召回条数（≥5，recall@5 用）")
    parser.add_argument("--work-dir", type=Path, default=None, help="评测临时目录（默认系统临时目录）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    report = run_eval(
        dataset_path=args.dataset,
        fixtures_dir=args.fixtures,
        report_dir=args.report_dir,
        weight_groups=_parse_weight_groups(args.weights),
        top_k=args.top_k,
        work_dir=args.work_dir,
    )
    gate = report["g2_gate"]
    reference_label = _label(gate["reference_group"])
    print(f"\n评测完成：{len(report['groups'])} 组权重 × {report['dataset_size']} 条用例")
    print(f"报告：{report['report_paths']['markdown']}")
    if not gate.get("evaluable", True):
        # 参照组没参与本次扫描 —— 既不能打绿，也不该说成"未达门槛"，单独判 2 让门禁红。
        print(
            f"[G2] {gate.get('reason', f'本次扫描不含参照组 {reference_label}，无法判定 G2')}",
            file=sys.stderr,
        )
        return 2
    print(
        f"[G2] 参照组 {reference_label} top-3 = {gate['reference_top3_rate']:.2%}"
        f" ≥ {gate['threshold']:.0%} ⇒ {'通过' if gate['passed'] else '未通过'}"
    )
    return 0 if gate["passed"] else 1


__all__ = [
    "DEFAULT_WEIGHT_GROUPS",
    "EvalItem",
    "G2_REFERENCE_WEIGHTS",
    "G2_TOP3_THRESHOLD",
    "build_g2_gate",
    "evaluate",
    "index_fixtures",
    "is_hit",
    "load_dataset",
    "main",
    "pick_reference_group",
    "render_markdown",
    "run_eval",
]
