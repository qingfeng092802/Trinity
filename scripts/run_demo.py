#!/usr/bin/env python
"""一键跑通多 Agent 编排链路（planner → executor → reviewer）。

用法::

    python scripts/run_demo.py                              # 内置示例任务
    python scripts/run_demo.py "把这段话改写成三条要点"
    python scripts/run_demo.py --max-iterations 2 --threshold 8
    python scripts/run_demo.py --json                       # 附带最终状态 JSON
    python scripts/run_demo.py --dry-run                    # 只打印编排拓扑，不调模型

退出码：0 = 任务完成或按门禁收口；1 = 任务失败（节点异常 / 配置错误）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings, get_settings  # noqa: E402 - 必须在补 sys.path 之后导入
from core.agent.base import ListTraceSink, NodeContext  # noqa: E402
from core.llm.pricing import is_peak, next_off_peak, status_line, window_description  # noqa: E402
from core.tools.builtin import load_builtin_tools  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402
from core.workflow.graph import NODE_ORDER, WorkflowRunner  # noqa: E402
from core.workflow.state import WorkflowConfig  # noqa: E402

DEFAULT_TASK = "用三句话说明：企业为什么需要在 RAG 知识库里加入混合检索（BM25 + 向量）"
LINE = "=" * 78
SUB = "-" * 78


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Trinity · 编排链路 Demo")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK, help="要执行的任务")
    parser.add_argument("--max-iterations", type=int, default=None, help="覆盖最大迭代轮数")
    parser.add_argument("--threshold", type=int, default=None, help="覆盖评审通过线（0-10）")
    parser.add_argument("--no-tools", action="store_true", help="不接入工具层（纯推理模式）")
    parser.add_argument("--hitl", action="store_true", help="高危工具需在终端人工确认")
    parser.add_argument(
        "--allow-peak",
        action="store_true",
        help="确认按高峰价执行（默认高峰计费时段直接拒绝运行）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印编排拓扑，不调用模型")
    parser.add_argument("--json", action="store_true", help="附加输出最终状态 JSON")
    parser.add_argument("--verbose", action="store_true", help="打印 INFO 级日志")
    return parser.parse_args(argv)


def console_approver(name: str, args: dict[str, Any]) -> bool:
    """命令行里的人工确认。

    stdin 不是交互终端时一律拒绝——fail-closed，绝不能因为「无人值守」就悄悄放行。
    """
    if not sys.stdin.isatty():
        print(f" [HITL] {name} 需要人工确认，但当前不是交互终端，按拒绝处理")
        return False
    answer = input(f" [HITL] 允许执行高危工具 {name}({args})？[y/N] ").strip().lower()
    return answer in {"y", "yes"}


def build_tool_registry(settings: Settings, *, hitl: bool) -> ToolRegistry:
    """装好 5 个内置工具，并按需开启 HITL。"""
    return load_builtin_tools(
        ToolRegistry(
            settings=settings,
            enable_hitl=hitl,
            hitl_approver=console_approver if hitl else None,
        )
    )


def print_topology(config: WorkflowConfig, registry: ToolRegistry | None) -> None:
    """打印编排拓扑与生效参数。"""
    settings = get_settings()
    print(LINE)
    print(" Trinity · 编排链路 Demo")
    print(LINE)
    print(f" 拓扑      START → {' → '.join(NODE_ORDER)} ─┬─ pass → END")
    print("                                          └─ fail → executor（iteration+1）")
    print(f" 模型      planner/reviewer={settings.llm_model_large}")
    print(f"           executor={settings.llm_model_small}")
    print(f" 端点      {settings.llm_base_url}")
    print(
        f" 门禁      最大迭代 {config.max_iterations} 轮 / "
        f"评审通过线 {config.review_threshold} 分"
    )
    if registry is None:
        print(" 工具      未接入（纯推理模式）")
    else:
        print(f" 工具      {len(registry.names())} 个：{', '.join(registry.names())}")
        if registry.enable_hitl:
            print("           HITL 已开启：高危工具会在终端要求确认")
    print(SUB)


def describe_update(node: str, update: Mapping[str, Any]) -> list[str]:
    """把一个节点产出的状态增量翻译成几行可读输出。"""
    lines: list[str] = []
    if node == "planner":
        for index, step in enumerate(update.get("plan") or [], 1):
            lines.append(f"      {index}. {step}")
    elif node == "executor":
        results = update.get("execution_results") or []
        if results:
            last = max(results, key=lambda item: item["step_index"])
            lines.append(
                f"      第 {last['step_index'] + 1} 步 [{last['status']}] {last['subtask']}"
            )
            lines.append(f"      结论：{last['output'][:160]}")
            for call in last["tool_calls"]:
                lines.append(
                    f"      工具 {call['name']} → {call['status']}（{call['duration_ms']}ms）"
                )
    elif node == "reviewer":
        lines.append(
            f"      pass={update.get('review_result')} score={update.get('review_score')} "
            f"iteration={update.get('iteration')} status={update.get('status')}"
        )
        lines.append(f"      意见：{update.get('review_comment', '')}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    args = parse_args(argv)
    settings = get_settings()
    settings.setup_logging()
    if not args.verbose:
        logging.getLogger().setLevel(logging.WARNING)

    overrides: dict[str, int] = {}
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.threshold is not None:
        overrides["review_threshold"] = args.threshold
    config = WorkflowConfig.from_settings(settings)
    if overrides:
        config = config.model_copy(update=overrides)

    registry = None if args.no_tools else build_tool_registry(settings, hitl=args.hitl)
    print_topology(config, registry)
    print(f" 任务      {args.task}")
    print(SUB)

    if args.dry_run:
        print(" [dry-run] 未调用模型，拓扑与配置如上。")
        return 0

    if not settings.llm_configured:
        print(" [错误] 未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填入真实 Key。")
        return 1

    # 高峰计费时段（周一至周五 09:00-12:00、14:00-18:00 北京时间）默认拒绝执行：
    # 同样的 token 要付 2 倍价钱。
    print(f" {status_line()}")
    if is_peak() and not args.allow_peak:
        resume_at = next_off_peak().strftime("%H:%M")
        print(f" [拒绝执行] 现在是高峰计费时段（{window_description()}），单价是低谷的 2 倍。")
        print(f" 建议 {resume_at} 之后再跑；确认要按高峰价跑就加 --allow-peak。")
        return 1

    trace = ListTraceSink()
    runner = WorkflowRunner(
        NodeContext.create(
            settings=settings,
            config=config,
            trace_sink=trace,
            tool_invoker=registry,
        )
    )

    try:
        collected: dict[str, Any] = {}
        for node, update in runner.stream(args.task):
            # stream 模式拿到的是状态增量，这里合并成一份可读的最终状态（messages 太长，略过）
            collected.update({key: value for key, value in update.items() if key != "messages"})
            print(f" [{node}] 完成")
            for line in describe_update(node, update):
                print(line)
    except Exception as exc:  # noqa: BLE001 - demo 脚本需要把任何异常转成可读结论
        print(f"\n [失败] {type(exc).__name__}: {exc}")
        return 1

    status = collected.get("status", "unknown")
    print(SUB)
    print(f" 结果      status={status}")
    print(
        f" 迭代      {collected.get('iteration', 0)} 轮 | "
        f"评审 {collected.get('review_score', 0)} 分"
    )
    print(f" 意见      {collected.get('review_comment', '')}")
    if collected.get("final_answer"):
        print(" 答案：")
        for line in str(collected["final_answer"]).splitlines():
            print(f"   {line}")
    summary = trace.summary()
    print(SUB)
    print(
        f" 埋点      {summary['count']} 条 / 失败 {summary['failed']} 条 / "
        f"耗时 {summary['duration_ms']}ms / 成本 ¥{summary['cost']}"
    )
    print(" 轨迹：")
    for record in trace.records:
        print(
            f"   - {record.role:<8} step={record.step} {record.status:<7} "
            f"{record.duration_ms:>6}ms  in={record.token_in} out={record.token_out} "
            f"¥{record.cost:.6f}"
        )
    print(SUB)
    print(" 提示      阶段 3 会把这份 trace 落进 SQLite，阶段 4 支持按 task_id 回放。")

    if args.json:
        print(SUB)
        payload = {
            "task": args.task,
            "task_id": collected.get("task_id"),
            "status": status,
            "config": config.model_dump(),
            "plan": collected.get("plan"),
            "execution_results": collected.get("execution_results"),
            "final_answer": collected.get("final_answer"),
            "trace": [record.model_dump() for record in trace.records],
            "summary": summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
