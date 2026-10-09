#!/usr/bin/env python
"""批量评测 CLI（**两个模式共用同一入口**，设计文档 §5.1：不新起第二套 CLI）。

* **criteria 模式（既有、默认）**——读 JSONL 评测集（``evaluation/dataset/agent_tasks.jsonl``），
  走 ``evaluation.batch.run_batch``，用 LLM Judge 打分，产出 ``BatchMetrics`` 报表。
  参数：``--dataset / --limit / --difficulty / --no-judge / --no-tools / --max-iterations /
  --threshold / --db / --no-db / --allow-peak / --json / --dry-run / --verbose``。
* **套件模式（P2 新增）**——读 YAML 任务集（``evaluation/tasksets/yunqi_v1.yaml`` 等），
  走 ``evaluation.harness.EvalHarness`` + ``evaluation.assertions`` 规则断言，
  用 ``evaluation.metrics.summarize_suite`` 汇总 ``SuiteMetrics``，可选落基线并回归对比。
  参数：``--taskset / --tag / --baseline / --compare / --via-api / --repeat /
  --cost-cap-cny / --force-compare``。

进入套件模式的判据：给出任一 ``--taskset / --tag / --baseline / --compare / --via-api``，
或 ``--repeat != 1``，或显式 ``--cost-cap-cny``；否则走既有 criteria 模式（**原路径逐字保留**）。

用法::

    # criteria 模式（既有行为，未变）
    python scripts/run_eval.py --dry-run
    python scripts/run_eval.py --limit 10 --json data/eval_report.json

    # 套件模式 · 冒烟（先看计划再真跑）
    python scripts/run_eval.py --tag smoke --dry-run
    python scripts/run_eval.py --tag smoke --limit 3

    # 套件模式 · 保存基线 / 二次运行并对比
    python scripts/run_eval.py --taskset main --limit 0 --baseline nightly-20260918
    python scripts/run_eval.py --taskset main --limit 0 --compare nightly-20260918

    # 套件模式 · HTTP 金标准通道（打真实 8000 服务，成本自负）
    python scripts/run_eval.py --taskset smoke --limit 1 --via-api

退出码：0 = 至少有一条跑完；1 = 全部失败或参数错误。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings, get_settings  # noqa: E402 - 必须在补 sys.path 之后导入
from core.llm.pricing import is_peak, next_off_peak, status_line, window_description  # noqa: E402
from evaluation.batch import BatchRun, run_batch  # noqa: E402
from evaluation.dataset import EvalItem, dataset_stats, load_dataset  # noqa: E402
from evaluation.metrics import TaskOutcome, format_report, summarize  # noqa: E402
from evaluation.trace import TraceStore  # noqa: E402
from storage.db import Database  # noqa: E402

# --------------------------------------------------------------------------- #
# P2 评测台（套件模式）新增依赖 —— 只读复用 T01~T04 交付，不改写其口径
# --------------------------------------------------------------------------- #
from evaluation.assertions import evaluate_task  # noqa: E402
from evaluation.baseline import (  # noqa: E402
    BaselineError,
    build_baseline,
    diff,
    load_baseline,
    make_per_task_entry,
    render_markdown,
    save_baseline,
)
from evaluation.contracts import (  # noqa: E402
    CHANNEL_API,
    CHANNEL_DIRECT,
    METRIC_KEYS,
    STATUS_DONE,
    round_cost,
)
from evaluation.harness import EvalHarness  # noqa: E402
from evaluation.metrics import make_suite_row, summarize_suite  # noqa: E402
from evaluation.taskset import (  # noqa: E402
    DEFAULT_TASKSET,
    SMOKE_TASKSET,
    EvalTask,
    EvalTaskSet,
    load_taskset,
)

#: 单条任务的成本估算（元）。取自真实跑通的观测值：
#: planner 340in/90out + executor 1300in/470out + reviewer 2850in/206out ≈ ¥0.015，
#: 加上 judge 约 ¥0.004，取 0.02 作为偏保守的估计。
ESTIMATED_COST_PER_TASK = 0.02

#: 套件模式单条任务的成本估算（元）。取自设计文档 §5.2 实测：含 3 次工具调用的任务
#: 约 36s / ¥0.052；任务集未写 ``est_cost_cny`` 时用这个兜底。
SUITE_ESTIMATED_COST_PER_TASK = 0.052

DEFAULT_LIMIT = 5

#: 对比报告落盘目录（与既有 ``evaluation/reports/`` 同源）
REPORTS_DIR = PROJECT_ROOT / "evaluation" / "reports"

#: ``--taskset`` 的别名 → 实际路径（方便 ``--taskset smoke`` 这种短写法）
TASKSET_ALIASES: dict[str, Path] = {
    "main": DEFAULT_TASKSET,
    "v1": DEFAULT_TASKSET,
    "yunqi_v1": DEFAULT_TASKSET,
    "smoke": SMOKE_TASKSET,
    "yunqi_smoke": SMOKE_TASKSET,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Trinity · 批量评测")
    parser.add_argument(
        "--dataset",
        default=None,
        help="评测集 JSONL 路径（默认 evaluation/dataset/agent_tasks.jsonl）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            f"最多跑几条（0 = 全部；criteria 模式默认 {DEFAULT_LIMIT}，"
            "套件模式默认全部）"
        ),
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        default=None,
        help="只跑指定难度",
    )
    parser.add_argument("--no-judge", action="store_true", help="不调用 LLM Judge，只看流程指标")
    parser.add_argument("--no-tools", action="store_true", help="不接入工具层（纯推理模式）")
    parser.add_argument("--max-iterations", type=int, default=None, help="覆盖最大迭代轮数")
    parser.add_argument("--threshold", type=int, default=None, help="覆盖评审通过线")
    parser.add_argument("--db", default=None, help="Trace 落库路径（默认 data/trinity.db）")
    parser.add_argument("--no-db", action="store_true", help="不写业务表（只看报表）")
    parser.add_argument(
        "--allow-peak",
        action="store_true",
        help="确认按高峰价执行（默认高峰计费时段直接拒绝运行）",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="把完整报表写进指定 JSON 文件",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印样本与成本估算，不调用模型")
    parser.add_argument("--verbose", action="store_true", help="打印 INFO 级日志")

    # ---------------------- P2 评测台（套件模式）新增参数 ---------------------- #
    parser.add_argument(
        "--taskset",
        default=None,
        metavar="PATH",
        help=(
            "P2 任务集 YAML 路径（或别名 main / smoke）；给定时进入套件模式。"
            "默认 evaluation/tasksets/yunqi_v1.yaml"
        ),
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="套件模式：只跑带该 tag 的任务（可重复；未显式给 --taskset 时 smoke 标签指向冒烟子集）",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        metavar="NAME",
        help="套件模式：把本次运行的指标与逐任务结果另存为基线 evaluation/baselines/<NAME>.json",
    )
    parser.add_argument(
        "--compare",
        default=None,
        metavar="NAME",
        help="套件模式：与指定基线对比并打印 Markdown 回归报告（同时落盘到 evaluation/reports/）",
    )
    parser.add_argument(
        "--via-api",
        action="store_true",
        help="套件模式：走 HTTP 金标准通道（POST /tasks + 轮询 /trace，打真实 8000 服务）",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="套件模式：同一任务重复采样次数（默认 1；>1 时报告带 std）",
    )
    parser.add_argument(
        "--cost-cap-cny",
        type=float,
        default=None,
        help="套件模式：累计成本上限（元），超过立即中止剩余任务",
    )
    parser.add_argument(
        "--force-compare",
        action="store_true",
        help="套件模式：越过基线可比性守卫（仍保留警告）",
    )
    return parser.parse_args(argv)


def build_config(settings: Settings, args: argparse.Namespace) -> Any:
    """按命令行覆盖项构造编排参数。"""
    from core.workflow.state import WorkflowConfig

    config = WorkflowConfig.from_settings(settings)
    overrides: dict[str, int] = {}
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.threshold is not None:
        overrides["review_threshold"] = args.threshold
    return config.model_copy(update=overrides) if overrides else config


def print_plan(items: list[EvalItem], args: argparse.Namespace) -> None:
    """dry-run：打印将要评测的样本与成本估算。"""
    stats = dataset_stats(items)
    print("=" * 78)
    print(" 评测计划（dry-run，未调用模型）")
    print("=" * 78)
    print(
        f" 样本数    {stats['total']}"
        f"（easy {stats['easy']} / medium {stats['medium']} / hard {stats['hard']}）"
    )
    print(
        f" 编排参数  最大迭代 {args.max_iterations or '（配置默认）'}"
        f" / 通过线 {args.threshold or '（配置默认）'}"
    )
    print(f" 工具      {'关闭' if args.no_tools else '5 个内置工具'}")
    print(f" 评测      {'关闭' if args.no_judge else 'LLM Judge'}")
    print(f" 计费      {status_line()}")
    print("-" * 78)
    for item in items:
        print(f" [{item.id}] ({item.difficulty}) {item.task[:56]}")
    print("-" * 78)
    total_cost = ESTIMATED_COST_PER_TASK * stats["total"]
    print(f" 预估成本  ≈ ¥{ESTIMATED_COST_PER_TASK:.3f} × {stats['total']} = ¥{total_cost:.3f}")
    print(" 说明      单条约 4500 输入 + 800 输出 token，加 judge 约 ¥0.004（取自实测）")
    print("=" * 78)


def _progress(index: int, item: EvalItem, outcome: TaskOutcome | None, error: str | None) -> None:
    """每跑完一条打印一行。"""
    prefix = f" [{index}] {item.id} ({item.difficulty})"
    if outcome is None:
        print(f"{prefix} 执行异常：{error}")
        return
    score_text = "未评分"
    if outcome.score is not None:
        score_text = f"{outcome.score}分/{outcome.grade}"
    print(
        f"{prefix} status={outcome.status} {score_text} "
        f"迭代{outcome.iterations} 工具{outcome.tool_calls}次 "
        f"{outcome.duration_ms / 1000:.1f}s ¥{outcome.cost:.4f}"
    )


# =========================================================================== #
# criteria 模式（既有路径，逐字保留）
# =========================================================================== #
def run_criteria(args: argparse.Namespace, settings: Settings) -> int:
    """既有 criteria 模式主流程（JSONL + judge）。"""
    try:
        items = load_dataset(
            args.dataset,
            difficulty=args.difficulty,
            limit=None if args.limit == 0 else args.limit,
        )
    except Exception as exc:  # noqa: BLE001 - 参数/文件问题转成可读结论
        print(f" [错误] 评测集加载失败：{exc}")
        return 1

    if not items:
        print(" [错误] 筛选后没有样本，检查 --difficulty / --limit")
        return 1

    if args.dry_run:
        print_plan(items, args)
        return 0

    if not settings.llm_configured:
        print(" [错误] 未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填入真实 Key。")
        return 1

    # 高峰计费时段（周一至周五 09:00-12:00、14:00-18:00 北京时间）拒绝执行：
    # 同样的 token 要付 2 倍价钱，批量评测最该避开这个窗口。
    print(f" {status_line()}")
    if is_peak() and not args.allow_peak:
        resume_at = next_off_peak().strftime("%H:%M")
        print(f" [拒绝执行] 现在是高峰计费时段（{window_description()}），单价是低谷的 2 倍。")
        print(f" 建议 {resume_at} 之后再跑；确认要按高峰价跑就加 --allow-peak。")
        return 1

    database: Database | None = None
    if not args.no_db:
        database = Database()
        database.init_db()

    print("=" * 78)
    print(f" 批量评测开始：{len(items)} 条样本")
    print(
        f" judge {'关闭' if args.no_judge else '开启'}"
        f" / 工具 {'关闭' if args.no_tools else '接入'}"
    )
    print("=" * 78)

    started = time.time()
    with TraceStore(args.db) as store:
        batch: BatchRun = run_batch(
            items,
            settings=settings,
            config=build_config(settings, args),
            use_tools=not args.no_tools,
            run_judge=not args.no_judge,
            store=store,
            database=database,
            on_item=_progress,
        )
        metrics = summarize(batch.outcomes)
        trace_total = store.aggregate()

    print()
    if batch.abort_reason:
        print(" [中止] " + batch.abort_reason)
        print(" 整批提前停止：这类错误重试无用。修好后重跑同一条命令即可。")
        print()
    print(format_report(metrics, batch.outcomes, title="批量评测报表"))
    total_tokens = trace_total["token_in"] + trace_total["token_out"]
    print(f" Trace 落库    {trace_total['records']} 条埋点，累计 token {total_tokens}")
    print(f" 墙钟耗时      {time.time() - started:.1f}s")

    if args.json_path:
        payload: dict[str, Any] = {
            "metrics": metrics.as_dict(),
            "outcomes": [
                {
                    "task": item.task,
                    "task_id": item.task_id,
                    "status": item.status,
                    "iterations": item.iterations,
                    "duration_ms": item.duration_ms,
                    "cost": item.cost,
                    "tool_calls": item.tool_calls,
                    "tool_failures": item.tool_failures,
                    "score": item.score,
                    "grade": item.grade,
                }
                for item in batch.outcomes
            ],
            "eval_results": batch.eval_results,
            "trace_summary": trace_total,
        }
        target = Path(args.json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" 报表已写入    {target}")

    return 0 if metrics.completed > 0 else 1


# =========================================================================== #
# 套件模式（P2 新增）
# =========================================================================== #
def is_suite_mode(args: argparse.Namespace) -> bool:
    """判定是否走套件模式（给出任一新增开关 / 非默认 repeat）。"""
    return bool(
        args.taskset
        or args.tag
        or args.baseline
        or args.compare
        or args.via_api
        or args.cost_cap_cny is not None
        or args.repeat != 1
    )


def resolve_taskset_path(args: argparse.Namespace) -> Path:
    """解析任务集路径：支持别名，且 ``--tag smoke`` 未给 --taskset 时自动指向冒烟子集。"""
    if args.taskset:
        key = str(args.taskset).strip()
        if key in TASKSET_ALIASES:
            return TASKSET_ALIASES[key]
        return Path(key)
    # 主任务集**没有** smoke 标签（T01 已核实），故 --tag smoke 自动落到冒烟子集
    if args.tag and "smoke" in set(args.tag):
        return SMOKE_TASKSET
    return DEFAULT_TASKSET


def select_tasks(taskset: EvalTaskSet, args: argparse.Namespace) -> EvalTaskSet:
    """按 ``--tag / --difficulty / --limit`` 切片（不修改原任务集）。"""
    limit = None if (args.limit is None or args.limit == 0) else int(args.limit)
    return taskset.select(
        tags=args.tag,
        difficulties=[args.difficulty] if args.difficulty else None,
        limit=limit,
    )


def print_suite_plan(taskset: EvalTaskSet, selected: EvalTaskSet, args: argparse.Namespace) -> None:
    """套件模式 dry-run：打印将跑的任务与成本估算（不调用模型）。"""
    repeat = max(int(args.repeat), 1)
    print("=" * 78)
    print(" P2 套件评测计划（dry-run，未调用模型）")
    print("=" * 78)
    print(
        f" 任务集    {taskset.name}（v{taskset.version}，全集 {len(taskset.tasks)} 条，"
        f"本次选中 {len(selected.tasks)} 条）"
    )
    print(f" 通道      {'HTTP · --via-api（金标准）' if args.via_api else '直调 · WorkflowRunner（默认）'}")
    print(f" repeat    {repeat}")
    if args.tag:
        print(f" tag 过滤  {', '.join(args.tag)}")
    if args.difficulty:
        print(f" 难度过滤  {args.difficulty}")
    if args.cost_cap_cny is not None:
        print(f" 成本上限  ¥{args.cost_cap_cny:.3f}")
    print(f" 计费      {status_line()}")
    print("-" * 78)
    est_total = 0.0
    for task in selected.tasks:
        est = task.est_cost_cny if task.est_cost_cny is not None else SUITE_ESTIMATED_COST_PER_TASK
        est_total += est
        print(f" [{task.id}] ({task.category}/{task.difficulty}) est¥{est:.3f} {task.prompt[:40]}")
    print("-" * 78)
    print(
        f" 预估成本  ≈ ¥{est_total:.3f}/轮 × repeat {repeat} = ¥{est_total * repeat:.3f}"
        "（粗略值，仅用于预算）"
    )
    print(" 说明      单条实测约 36s / ¥0.052（真实 LLM）；失败/跳过不计入通过率分母")
    print("=" * 78)


def _suite_progress(index: int, task: EvalTask, run: Any) -> None:
    """套件模式每跑完一条打印一行。"""
    print(
        f" [{index}] {task.id} ({task.category}/{task.difficulty}) "
        f"status={run.status} 步数{run.steps} 工具{run.tool_calls}次 "
        f"{run.duration_ms / 1000:.1f}s ¥{run.cost:.4f}"
    )


def _evaluate_suite(
    selected: EvalTaskSet, report: Any
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    """对每条 ``TaskRun`` 跑规则断言，拍成套件行。

    Returns:
        ``(flat_rows, per_task, per_repeat)``：

        * ``flat_rows``：每次运行一行（喂 :func:`summarize_suite`）；
        * ``per_task``：``task.id → [row, ...]``（``repeat`` 次）；
        * ``per_repeat``：``repeat_index → [row, ...]``（``repeat>1`` 时算 std 用）。
    """
    flat_rows: list[dict[str, Any]] = []
    per_task: dict[str, list[dict[str, Any]]] = {}
    per_repeat: dict[int, list[dict[str, Any]]] = {}
    for task in selected.tasks:
        bucket: list[dict[str, Any]] = []
        for repeat_index, run in enumerate(report.runs_for(task.id)):
            result = evaluate_task(task, run)
            row = make_suite_row(task, run, result)
            # make_suite_row 不含 error，这里补上（基线 per_task 要能写明失败原因，设计 §3.4）
            row["error"] = run.error
            flat_rows.append(row)
            bucket.append(row)
            per_repeat.setdefault(repeat_index, []).append(row)
        per_task[task.id] = bucket
    return flat_rows, per_task, per_repeat


def _repeat_std(
    per_repeat: dict[int, list[dict[str, Any]]], repeat: int
) -> dict[str, float]:
    """``repeat>1`` 时逐指标总体标准差（键名见 ``contracts.METRIC_KEYS``）。

    口径：把每次重复采样视为「一轮套件运行」，对逐轮指标取 ``pstdev``。
    单位沿用指标自身（比率 0~1 / 步数 / **元** / **毫秒**），**不做任何换算**。
    """
    groups = [per_repeat[index] for index in sorted(per_repeat) if per_repeat[index]]
    if repeat <= 1 or len(groups) < 2:
        return {}
    # 采样不完整（某些任务没跑满 repeat 次）时，分组长度不一致会污染口径 → 直接放弃 std
    if len({len(group) for group in groups}) != 1:
        return {}
    group_metrics = [summarize_suite(group) for group in groups]
    std: dict[str, float] = {}
    for key in METRIC_KEYS:
        values = [getattr(metrics, key, None) for metrics in group_metrics]
        if any(value is None for value in values):
            continue
        std[key] = round(statistics.pstdev([float(value) for value in values]), 6)
    return std


def _mean_int(values: list[int]) -> int:
    """整数均值（四舍五入）；空列表返回 0。"""
    return int(round(sum(values) / len(values))) if values else 0


def _pick_status(statuses: list[str]) -> str:
    """从 ``repeat`` 次运行里挑一个代表终态（不美化：有非 done 就报非 done）。"""
    if not statuses:
        return "unknown"
    if all(status == statuses[0] for status in statuses):
        return statuses[0]
    for status in statuses:
        if status != STATUS_DONE:
            return status
    return statuses[0]


def _aggregate_per_task(task: EvalTask, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """把某任务的（``repeat`` 个）运行行聚合成一条基线 ``per_task`` 记录。

    ``repeat == 1`` 时即该次运行的逐字投影；``repeat > 1`` 时取均值 / 并集，
    且 ``passed`` 采用**全通过才为真**（严格口径，不美化）。
    """
    if not rows:
        return make_per_task_entry(task_id=task.id, passed=False, category=task.category,
                                  difficulty=task.difficulty, status="unknown")
    count = len(rows)
    passed = all(bool(row.get("passed")) for row in rows)
    failed_assertions: list[str] = []
    for row in rows:
        for name in row.get("failed_assertions") or []:
            if name not in failed_assertions:
                failed_assertions.append(name)
    error: str | None = next(
        (run.get("error") for run in rows if run.get("error")), None
    )
    return make_per_task_entry(
        task_id=task.id,
        passed=passed,
        category=task.category,
        difficulty=task.difficulty,
        status=_pick_status([str(row.get("status", "")) for row in rows]),
        steps=_mean_int([int(row.get("steps", 0) or 0) for row in rows]),
        iterations=_mean_int([int(row.get("iterations", 0) or 0) for row in rows]),
        tool_calls=_mean_int([int(row.get("tool_calls", 0) or 0) for row in rows]),
        tool_failures=_mean_int([int(row.get("tool_failures", 0) or 0) for row in rows]),
        cost=round_cost(sum(float(row.get("cost", 0.0) or 0.0) for row in rows) / count),
        duration_ms=_mean_int([int(row.get("duration_ms", 0) or 0) for row in rows]),
        tool_sequence=list(rows[0].get("tool_sequence") or []),
        failed_assertions=failed_assertions,
        error=error,
    )


def print_suite_report(
    report: Any,
    metrics: Any,
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    wall_s: float,
) -> None:
    """打印套件报表（五项主指标 + 逐任务明细）。"""
    line = "=" * 78
    taskset_name = str((report.taskset or {}).get("name", "?"))
    print()
    print(line)
    print(f" P2 套件评测报表：{taskset_name}   通道 {report.channel}   repeat {report.repeat}")
    print(line)
    print(f" 任务数(评估)   {metrics.evaluated}    跳过 {metrics.skipped}")
    print(
        f" ① 通过率       {metrics.pass_rate * 100:.1f}%"
        f"  （passed {metrics.passed} / failed {metrics.failed}）"
    )
    if metrics.tool_accuracy is None:
        print(" ② 工具准确率   —（本批无工具期望任务，不作 0% 处理）")
    else:
        print(
            f" ② 工具准确率   {metrics.tool_accuracy * 100:.1f}%"
            f"  （|T|={metrics.tool_expected_tasks} 条期望工具）"
        )
    print(
        f" ③ 平均步数     {metrics.avg_steps:.2f} 步"
        f"  （iterations {metrics.avg_iterations:.2f} / tool_calls {metrics.avg_tool_calls:.2f}）"
    )
    print(
        f" ④ 成本         总计 ¥{metrics.total_cost:.6f}"
        f"    平均 ¥{metrics.avg_cost:.6f}/任务"
    )
    print(
        f" ⑤ 延迟         avg {metrics.avg_latency_ms:.0f}ms  p50 {metrics.p50_latency_ms:.0f}ms"
        f"  p95 {metrics.p95_latency_ms:.0f}ms  max {metrics.max_latency_ms:.0f}ms"
    )
    print(
        f" 工具调用       {metrics.tool_calls} 次，失败 {metrics.tool_failures} 次"
        f"    成功率 {metrics.tool_call_success_rate * 100:.1f}%"
    )
    if metrics.std:
        joined = "  ".join(f"{key}={value:.4f}" for key, value in metrics.std.items())
        print(f" 波动(std)      {joined}")
    print(f" 墙钟/隔离库    {wall_s:.1f}s    {report.db_path or '（未隔离：HTTP 通道）'}")
    if report.aborted:
        print(f" [中止] {report.abort_reason}")
    for skipped in report.skipped:
        print(f" [跳过] {skipped.task_id}：{skipped.reason}")
    print("-" * 78)
    for row in rows:
        verdict = "PASS" if row.get("passed") else "FAIL"
        failed = row.get("failed_assertions") or []
        tail = f"  失败断言={failed}" if failed else ""
        print(
            f" [{row.get('id')}] {verdict} status={row.get('status')} "
            f"步{row.get('steps')} ¥{float(row.get('cost', 0.0)):.4f}{tail}"
        )
    print(line)


def _build_baseline_model(
    *,
    taskset: EvalTaskSet,
    selected: EvalTaskSet,
    report: Any,
    metrics: Any,
    per_task: dict[str, list[dict[str, Any]]],
    settings: Settings,
    taskset_path: Path,
) -> Any:
    """组装可落盘的基线模型。

    ★ 任务集哈希取**全集**（设计文档 §3「切片后的哈希与全集不同，基线比对对全集取哈希」）。
    """
    entries = [_aggregate_per_task(task, per_task.get(task.id, [])) for task in selected.tasks]
    return build_baseline(
        metrics=metrics,
        per_task=entries,
        taskset=taskset,
        taskset_path=taskset_path,
        settings=settings,
        channel=report.channel,
        repeat=report.repeat,
    )


def _write_compare_markdown(markdown: str, name: str) -> Path:
    """把对比 Markdown 落盘到 ``evaluation/reports/``（时间戳唯一，避免互相覆盖）。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = REPORTS_DIR / f"compare_{name}_{stamp}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


def _print_and_persist_compare(
    current_model: Any, args: argparse.Namespace, *, aborted: bool = False
) -> Any | None:
    """加载基线 → diff → 打印并落盘 Markdown 报告；失败返回 ``None``。"""
    try:
        base_model = load_baseline(args.compare)
    except BaselineError as exc:
        print(f" [错误] 基线加载失败（--compare {args.compare}）：{exc}")
        return None

    result = diff(current_model, base_model, force=args.force_compare)
    # 成本护栏（--cost-cap-cny）等导致整批提前中止 → 显式标注，防止「未跑完的指标」
    # 被误当成完整基线对比（设计 §5.2；diff() 自身固定置 False，由调用方按实际修正）
    if aborted:
        result.aborted_prematurely = True
    markdown = render_markdown(
        result,
        base=base_model,
        current=current_model,
        title=f"P2 评测台 · 基线回归报告（base={args.compare}）",
    )
    saved_path = _write_compare_markdown(markdown, str(args.compare))

    print()
    print("=" * 78)
    print(f" 基线对比 Markdown 报告（base={args.compare}；已落盘 {saved_path}）")
    print("=" * 78)
    if not result.comparable:
        print(" [!] 可比性守卫未通过：delta 不可直接归因（确认要强比可加 --force-compare）。")
    print(markdown)
    return result


def _write_suite_json(
    args: argparse.Namespace,
    *,
    report: Any,
    metrics: Any,
    per_task_entries: list[dict[str, Any]],
    diff_result: Any | None,
) -> None:
    """把套件运行的完整报表写进 ``--json``。"""
    if not args.json_path:
        return
    payload: dict[str, Any] = {
        "mode": "suite",
        "channel": report.channel,
        "repeat": report.repeat,
        "taskset": dict(report.taskset or {}),
        "metrics": metrics.as_dict(),
        "per_task": per_task_entries,
        "runs": [run.as_dict() for run in report.runs],
        "skipped": [item.as_dict() for item in report.skipped],
        "aborted": report.aborted,
        "abort_reason": report.abort_reason,
        "cost_total": report.cost_total,
        "wall_ms": report.wall_ms,
        "db_path": report.db_path,
    }
    if diff_result is not None:
        payload["baseline_diff"] = diff_result.as_dict()
    target = Path(args.json_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f" 报表已写入    {target}")


def run_suite(args: argparse.Namespace, settings: Settings) -> int:
    """套件模式主流程（YAML 任务集 + 规则断言 + 基线回归）。"""
    taskset_path = resolve_taskset_path(args)
    try:
        taskset = load_taskset(taskset_path)
    except Exception as exc:  # noqa: BLE001 - 文件/格式问题转成可读结论
        print(f" [错误] 任务集加载失败（{taskset_path}）：{exc}")
        return 1

    selected = select_tasks(taskset, args)
    if not selected.tasks:
        print(" [错误] 筛选后没有任务，检查 --tag / --difficulty / --limit")
        return 1

    if args.dry_run:
        print_suite_plan(taskset, selected, args)
        return 0

    if not settings.llm_configured:
        print(" [错误] 未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填入真实 Key。")
        return 1

    # 高峰计费时段硬拦（与 criteria 模式同源，criteria 护栏原样复用）
    print(f" {status_line()}")
    if is_peak() and not args.allow_peak:
        resume_at = next_off_peak().strftime("%H:%M")
        print(f" [拒绝执行] 现在是高峰计费时段（{window_description()}），单价是低谷的 2 倍。")
        print(f" 建议 {resume_at} 之后再跑；确认要按高峰价跑就加 --allow-peak。")
        return 1

    channel = CHANNEL_API if args.via_api else CHANNEL_DIRECT
    repeat = max(int(args.repeat), 1)

    print("=" * 78)
    print(
        f" P2 套件评测开始：{taskset.name} · 选中 {len(selected.tasks)} 条"
        f" · 通道 {channel} · repeat {repeat}"
    )
    print("=" * 78)

    # ★ 显式开启知识库注入：直调通道默认 inject_knowledge=False（T03 尚未把「任务集含
    #   requires_ready_docs 时自动开启」落地），不开启则检索类任务全部查不到 → 全灭。
    harness = EvalHarness(
        selected,
        channel=channel,
        repeat=repeat,
        cost_cap_cny=args.cost_cap_cny,
        settings=settings,
        source_db_path=args.db,
        inject_knowledge=True,
        on_run=_suite_progress,
    )

    started = time.time()
    with harness:
        report = harness.run_all()
    wall_s = time.time() - started

    rows, per_task, per_repeat = _evaluate_suite(selected, report)
    repeat_std = _repeat_std(per_repeat, repeat)
    metrics = summarize_suite(rows, skipped=len(report.skipped), repeat_std=repeat_std)
    # SuiteReport.metrics 由 T03 刻意留空，这里用 T02 的汇总函数填（唯一口径）
    report.metrics = metrics

    print_suite_report(report, metrics, rows, args, wall_s=wall_s)

    per_task_entries = [_aggregate_per_task(task, per_task.get(task.id, [])) for task in selected.tasks]
    current_model = _build_baseline_model(
        taskset=taskset,
        selected=selected,
        report=report,
        metrics=metrics,
        per_task=per_task,
        settings=settings,
        taskset_path=taskset_path,
    )

    if args.baseline:
        saved = save_baseline(current_model, args.baseline)
        print(f" 基线已保存    {saved}")

    diff_result = (
        _print_and_persist_compare(current_model, args, aborted=report.aborted)
        if args.compare
        else None
    )

    _write_suite_json(
        args,
        report=report,
        metrics=metrics,
        per_task_entries=per_task_entries,
        diff_result=diff_result,
    )

    # 退出码约定：0 = 至少有一条以 done 跑完；1 = 全部失败 / 全跳过 / 参数错误
    return 0 if any(run.is_done() for run in report.runs) else 1


def main(argv: list[str] | None = None) -> int:
    """脚本入口：按命令行开关分派 criteria / 套件两种模式。"""
    args = parse_args(argv)
    settings = get_settings()
    settings.setup_logging()
    if not args.verbose:
        logging.getLogger().setLevel(logging.WARNING)

    if is_suite_mode(args):
        return run_suite(args, settings)

    # criteria 模式：--limit 缺省回填既有默认值（保持原行为不变）
    if args.limit is None:
        args.limit = DEFAULT_LIMIT
    return run_criteria(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
