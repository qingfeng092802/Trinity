#!/usr/bin/env python
"""M1 真实 LLM 全链路实测（TestClient 进程内，不绑端口）。

用法（**必须在 DeepSeek 非高峰时段运行**，积分 5 折）::

    .venv\\Scripts\\python.exe scripts\\live_test_m1.py

特性
----
1. **高峰拒跑硬闸门**：启动即检查 ``core.llm.pricing.is_peak()``，
   高峰时段（周一至五 09:00-12:00、14:00-18:00）直接退出，不做任何 LLM 调用。
2. 进程内 ASGI（TestClient）——与既有 30 个集成测试同模式，已验证可行。
   HTTP 请求 -> 队列 -> 线程池 -> runner -> 真实 LLM 全链路真实走一遍。
3. 成本控制：只提交 **1 条**轻量任务，``run_judge=False``。
4. 全程落盘：报告写 ``docs/m1_live_test_report.md``，结论先行；
   任何异常（含 LLM 401/402/429）原样记录，不粉饰、不重试超过 1 次。
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，打印 ✅ 等 Unicode 字符会抛 UnicodeEncodeError
# （实测退出码 1 崩在最后一行 print，全链路其实已成功）——强制 UTF-8 输出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "docs" / "m1_live_test_report.md"

#: 轻量任务：答案短、大概率不触发工具、1 轮迭代可收
GOAL = "用三句话介绍综合布线系统中的水平子系统，面向刚入行的弱电设计新人。"

TERMINAL_EVENTS = {"done", "failed", "canceled"}
SSE_TIMEOUT_SECONDS = 420.0
POLL_DEADLINE_SECONDS = 480.0


def _peak_guard() -> str | None:
    """高峰时段返回拒绝原因（不调 LLM）；非高峰返回 None。"""
    from core.llm.pricing import is_peak, status_line

    if is_peak():
        return f"当前处于高峰计费时段（原价），按约定不跑真实 LLM。{status_line()}"
    return None


def read_sse(client: Any, task_id: str, t0: float) -> list[dict[str, Any]]:
    """订阅 SSE 流直到终态事件；返回事件列表（每项含 id/event/data/t）。"""
    events: list[dict[str, Any]] = []
    with client.stream("GET", f"/tasks/{task_id}/stream", timeout=SSE_TIMEOUT_SECONDS) as resp:
        if resp.status_code != 200:
            body = resp.read().decode("utf-8", errors="replace")[:300]
            return [{"event": "http_error", "data": {"code": resp.status_code, "body": body}, "t": round(time.time() - t0, 3)}]
        current: dict[str, Any] = {}
        for raw in resp.iter_lines():
            line = (raw or "").rstrip("\r")
            if not line:
                if current:
                    events.append(current)
                    if current.get("event") in TERMINAL_EVENTS:
                        return events
                    current = {}
                continue
            if line.startswith(":"):
                continue  # 注释帧（心跳保活注释）
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "id":
                current["id"] = value
            elif key == "event":
                current["event"] = value
                current.setdefault("t", round(time.time() - t0, 3))
            elif key == "data":
                try:
                    current["data"] = json.loads(value)
                except json.JSONDecodeError:
                    current["data_raw"] = value
        if current:  # 流正常关闭但最后帧无空行结尾
            events.append(current)
    return events


def summarize_event(evt: dict[str, Any]) -> str:
    """把一帧事件压成一行人话，供报告表格用。"""
    name = evt.get("event", "?")
    data = evt.get("data")
    if isinstance(data, dict):
        if name == "node":
            node = data.get("node") or data.get("name") or ""
            phase = data.get("phase") or data.get("kind") or ""
            return f"node={node} phase={phase}"
        if name in TERMINAL_EVENTS:
            return json.dumps({k: v for k, v in data.items() if k in ("status", "task_id", "iteration", "score", "cost")}, ensure_ascii=False)
        if name == "snapshot":
            return f"status={data.get('status')} progress={bool(data.get('progress'))}"
    if isinstance(data, str) and len(data) > 80:
        return data[:80] + "..."
    return json.dumps(data, ensure_ascii=False) if data is not None else "-"


def build_report(
    *,
    verdict: str,
    submit: dict[str, Any],
    events: list[dict[str, Any]],
    detail: dict[str, Any] | None,
    eval_row: dict[str, Any] | None,
    error: str | None,
    elapsed: float,
) -> str:
    """渲染 Markdown 报告（结论先行）。"""
    lines: list[str] = []
    lines.append("# M1 真实 LLM 全链路实测报告")
    lines.append("")
    lines.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')} · 方式：TestClient 进程内全链路 · 任务数：1")
    lines.append("")
    lines.append(f"## 结论：{verdict}")
    lines.append("")
    lines.append("## 任务信息")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| task_id | `{(detail or {}).get('task_id', submit.get('task_id', '?'))}` |")
    lines.append(f"| 任务描述 | {GOAL} |")
    lines.append(f"| 终态 | **{(detail or {}).get('status', '?')}** |")
    lines.append(f"| 耗时 | {(detail or {}).get('duration_ms', 0) / 1000:.1f} s（实测总耗时 {elapsed:.1f} s） |")
    lines.append(f"| 成本 | ¥{(detail or {}).get('cost', 0)}（价格倍率 {submit.get('price_multiplier', '?')}，高峰标记 {submit.get('peak_pricing', '?')}） |")
    score = (detail or {}).get("score")
    lines.append(f"| 评分 | {score if score is not None else '—'} / {(detail or {}).get('grade') or '—'} |")
    lines.append(f"| 迭代 | {(detail or {}).get('iterations', 0)} 次 · 工具调用 {(detail or {}).get('tool_calls', 0)} 次（失败 {(detail or {}).get('tool_failures', 0)}） |")
    lines.append(f"| 受理预估成本 | ¥{submit.get('estimated_cost_cny', '?')} |")
    lines.append("")
    if events:
        lines.append("## SSE 事件序列")
        lines.append("")
        lines.append("| # | 时刻(s) | 事件 | 内容 |")
        lines.append("|---|---|---|---|")
        for i, evt in enumerate(events, 1):
            lines.append(f"| {i} | {evt.get('t', '?')} | `{evt.get('event', '?')}` | {summarize_event(evt)} |")
        lines.append("")
    answer = (detail or {}).get("final_answer") or ""
    if answer:
        lines.append("## 最终答案（摘录前 600 字）")
        lines.append("")
        lines.append("```text")
        lines.append(answer[:600] + ("..." if len(answer) > 600 else ""))
        lines.append("```")
        lines.append("")
    if (detail or {}).get("error"):
        lines.append("## 失败原因")
        lines.append("")
        lines.append(f"- code: `{(detail or {}).get('error', {}).get('code', '?')}`")
        lines.append(f"- message: {(detail or {}).get('error', {}).get('message', '?')}")
        lines.append("")
    if eval_row is not None:
        lines.append("## 评测记录（GET /eval 最新一条）")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(eval_row, ensure_ascii=False, indent=2)[:1200])
        lines.append("```")
        lines.append("")
    if error:
        lines.append("## 异常")
        lines.append("")
        lines.append("```text")
        lines.append(error[:1500])
        lines.append("```")
        lines.append("")
    lines.append("## 已知限制提醒")
    lines.append("")
    lines.append("- Python 无法杀线程：取消/失败的最坏等待是当前节点超时（120s/节点）")
    lines.append("- 本报告为单任务实测，并发上限（3）由既有集成测试覆盖")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """入口：高峰拒跑 -> 提交 -> SSE -> 终态 -> 报告。"""
    refuse = _peak_guard()
    if refuse:
        print(f"[拒跑] {refuse}")
        return 2

    from fastapi.testclient import TestClient

    from api.main import app

    verdict = "❌ 未完成（见异常）"
    submit: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    detail: dict[str, Any] | None = None
    eval_row: dict[str, Any] | None = None
    error: str | None = None
    t0 = time.time()

    try:
        with TestClient(app) as client:
            health = client.get("/health").json()
            print(f"[health] {health.get('status')}")

            resp = client.post(
                "/tasks",
                json={"task": GOAL, "use_tools": True, "difficulty": "easy", "run_judge": False},
            )
            if resp.status_code not in (200, 201, 202):
                error = f"POST /tasks -> {resp.status_code}: {resp.text[:400]}"
                raise RuntimeError(error)
            submit = resp.json()
            task_id = submit["task_id"]
            print(f"[submit] task_id={task_id} queue_position={submit.get('queue_position')}")

            events = read_sse(client, task_id, t0)
            print(f"[sse] 收到 {len(events)} 帧，末帧: {events[-1].get('event') if events else '无'}")

            # 轮询终态兜底（SSE 万一提前断）
            deadline = time.time() + POLL_DEADLINE_SECONDS
            while time.time() < deadline:
                detail = client.get(f"/tasks/{task_id}").json()
                if detail.get("status") in {"done", "failed", "canceled"}:
                    break
                time.sleep(2)
            # eval 最新一条（可能含 token 明细；拿不到不影响结论）
            try:
                ev = client.get("/eval", params={"limit": 1, "offset": 0}).json()
                if ev.get("items"):
                    eval_row = ev["items"][0]
            except Exception:  # noqa: BLE001
                pass

        status = (detail or {}).get("status") if detail else None
        if status == "done":
            verdict = "✅ 全链路走通：提交 -> 队列 -> planner -> executor -> reviewer -> done"
        elif status:
            verdict = f"❌ 任务终态为 {status}（见失败原因/异常）"
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()
        print("[异常]", error[-800:])

    elapsed = time.time() - t0
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        build_report(verdict=verdict, submit=submit, events=events, detail=detail, eval_row=eval_row, error=error, elapsed=elapsed),
        encoding="utf-8",
    )
    print(f"[报告] {REPORT_PATH}")
    print(f"[结论] {verdict}")
    return 0 if verdict.startswith("✅") else 1


if __name__ == "__main__":
    raise SystemExit(main())
