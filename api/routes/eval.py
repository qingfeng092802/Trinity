"""评测查询：``GET /eval`` + ``GET /eval/retrieval-report``（**均只读**）。

M1 **不提供**触发批量评测的接口（PRD §6 Out of Scope，P2-1 才做），
所以这里只有读：按 ``task_id`` 过滤、按创建时间倒序、支持分页。

``total`` 必须走 ``Database.count_evals`` 单独 count，不能用
``len(list_evals(...))``——后者受 ``limit`` 截断，会得到一个假的「总数」。

``GET /eval/retrieval-report`` 是**零计算**的只读透传：它不跑评测，只把
``scripts/eval_retrieval.py`` 落盘的最新一份 JSON 报告原样返回给前端。
评测本身仍由 CLI 触发，API 不承担计算职责（保持「API 只读」的既有纪律）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from api.deps import get_database
from api.schemas import EvalListResponse

#: 检索评测报告目录（与 ``evaluation/retrieval_eval.py`` 的 --report-dir 默认值一致）
REPORT_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "reports"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["eval"])


@router.get(
    "/eval",
    response_model=EvalListResponse,
    summary="查询评测记录（只读）",
)
def list_eval_records(
    task_id: str | None = Query(default=None, description="按任务 id 过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="每页条数 1..200"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> EvalListResponse:
    """查询 judge 评测记录。

    Args:
        task_id: 只返回该任务的记录；不传返回全部。
        limit: 每页条数（1..200，越界 422 由 Pydantic 自动处理）。
        offset: 偏移量（≥0）。

    Returns:
        分页结果；空库返回 ``items=[]``、``total=0``。
    """
    database = get_database()
    records = database.list_evals(task_id, limit=limit, offset=offset)
    return EvalListResponse(
        items=[record.as_dict() for record in records],
        total=database.count_evals(task_id),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/eval/retrieval-report",
    summary="读取最近一次检索评测报告（只读，不触发计算）",
)
def latest_retrieval_report() -> dict[str, Any]:
    """把 ``evaluation/reports/`` 下最新一份 ``eval_*.json`` 原样返回。

    **不做任何计算、不做任何补零**：报告不存在就返回 ``available=false``，
    由前端显式显示「待测」，绝不预填数字。

    Returns:
        ``available=true`` 时附带 ``report``（CLI 落盘的原始 JSON）与
        ``report_file``；否则只给 ``available=false`` 与 ``reason``。
    """
    if not REPORT_DIR.is_dir():
        return {"available": False, "reason": f"报告目录不存在：{REPORT_DIR}"}

    candidates = sorted(REPORT_DIR.glob("eval_*.json"))
    if not candidates:
        return {"available": False, "reason": "尚未运行过检索评测（scripts/eval_retrieval.py）"}

    latest = candidates[-1]
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("检索评测报告读取失败：%s", exc)
        return {"available": False, "reason": f"报告解析失败：{exc}"}

    return {"available": True, "report_file": latest.name, "report": report}


@router.get(
    "/eval/ablation-report",
    summary="读取最近一次消融报表（只读，不触发计算）",
)
def latest_ablation_report() -> dict[str, Any]:
    """把 ``evaluation/reports/ablation/ablation_summary.json`` 原样返回 + 两类失败归因。

    与 ``/eval/retrieval-report`` 同一条纪律：**零计算、不补零**。
    唯一的服务端加工是 F1/F2 归因计数（纯计数、不引入任何估计值）：
    * **F1 未召回**：``hit_at_k == 0``
    * **F2 召回未居首**：``hit_at_k == 1 且 mrr_at_k < 1``

    Returns:
        ``available=true`` 时附带 ``report``、``report_file``、``arms``（每臂
        nDCG/MRR/命中率/Δ/相对基线）、``attribution``（每臂 F1/F2 计数）；
        否则只给 ``available=false`` 与 ``reason``。
    """
    summary_path = ABLATION_DIR / "ablation_summary.json"
    if not summary_path.is_file():
        return {"available": False, "reason": "尚未运行过消融（scripts/run_ablation.py）"}

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("消融报表读取失败：%s", exc)
        return {"available": False, "reason": f"报表解析失败：{exc}"}

    return {
        "available": True,
        "report_file": summary_path.name,
        "report": summary,
        "arms": _arm_rows(summary),
        "attribution": _failure_attribution(summary),
    }


#: 消融报表目录（与 ``scripts/run_ablation.py`` 的 --out 默认值一致）
ABLATION_DIR = REPORT_DIR / "ablation"


def _arm_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """把 ``significance.family`` 摊平成「一臂一行」，前端不用自己拼。"""
    by_arm: dict[str, dict[str, Any]] = {}
    for item in ((summary.get("significance") or {}).get("family") or []):
        arm_id, _, metric = str(item.get("metric", "")).partition(":")
        row = by_arm.setdefault(arm_id, {"arm_id": arm_id})
        if metric in ("ndcg_at_k", "mrr_at_k", "hit_at_k"):
            row[metric] = item.get("mean_arm")
            row[f"baseline_{metric}"] = item.get("mean_baseline")
            row[f"delta_{metric}"] = item.get("delta")
            row[f"rel_lift_{metric}"] = item.get("rel_lift")
        row["n_used"] = item.get("n_used")
    return sorted(by_arm.values(), key=lambda row: row["arm_id"])


def _failure_attribution(summary: dict[str, Any]) -> dict[str, dict[str, int]]:
    """F1/F2 计数（判据与 ``scripts/analyze_ablation_failures.py`` 完全一致）。"""
    out: dict[str, dict[str, int]] = {}
    for arm_id, arm in (summary.get("arms") or {}).items():
        rows = [r for r in (arm.get("per_question") or []) if r.get("hit_at_k") is not None]
        f1 = sum(1 for r in rows if r["hit_at_k"] == 0.0)
        f2 = sum(1 for r in rows if r["hit_at_k"] == 1.0 and (r.get("mrr_at_k") or 0) < 1.0)
        out[arm_id] = {"scored": len(rows), "f1": f1, "f2": f2, "clean": len(rows) - f1 - f2}
    return out


__all__ = ["router"]
