#!/usr/bin/env python
"""M1 真实 LLM 批量实测：6 条任务覆盖验收全场景（仅限 DeepSeek 低谷时段运行）。

场景矩阵：
  #1 轻量问答      —— done 主路径 + SSE 事件序列完整性
  #2 工具任务      —— executor 真实工具调用（calculator）
  #3 中文生成      —— reviewer 评分 + final_answer 质量
  #4/#5/#6 并发 3 条 —— 排队机制 + 并发上限观测；#5 中途取消（真实 LLM 取消语义）

用法::

    .venv\\Scripts\\python.exe scripts\\live_batch_m1.py

报告落盘 ``docs/m1_live_batch_report.md``（结论先行）。高峰时段直接拒跑（exit 2）。
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "docs" / "m1_live_batch_report.md"

TERMINAL_EVENTS = {"done", "failed", "canceled"}
TERMINAL_STATUSES = {"done", "failed", "canceled", "aborted"}
SSE_TIMEOUT = 420.0
POLL_DEADLINE = 420.0
CONCURRENT_DEADLINE = 480.0

# ---------------------------------------------------------------- 任务定义 --
PHASE_A = {"goal": "用三句话介绍综合布线系统中的水平子系统，面向刚入行的弱电设计新人。", "difficulty": "easy"}
PHASE_B = [
    {
        "name": "工具任务",
        "body": {
            "task": "某工商业储能项目装机 1MW/2MWh，按度电价差 0.7 元/kWh、每天两充两放且每次完整循环，理论日套利收入是多少元？请使用 calculator 工具计算。",
            "use_tools": True,
            "difficulty": "medium",
        },
    },
    {
        "name": "中文生成",
        "body": {
            "task": "为一份弱电智能化投标书写一段 200 字以内的公司资质说明段落，语气正式。",
            "use_tools": False,
            "difficulty": "medium",
        },
    },
]
PHASE_C = [
    "用一句话解释什么是门禁一卡通系统。",
    "列举安防监控系统由哪五部分组成，每部分一句话。",
    "解释 PoE 供电的优点，两句话。",
]


def read_sse(client: Any, task_id: str, t0: float) -> list[dict[str, Any]]:
    """读 SSE 流直到终态事件（用于 #1 的事件序列完整性验证）。"""
    events: list[dict[str, Any]] = []
    with client.stream("GET", f"/tasks/{task_id}/stream", timeout=SSE_TIMEOUT) as resp:
        if resp.status_code != 200:
            return [{"event": "http_error", "data": {"code": resp.status_code}, "t": round(time.time() - t0, 3)}]
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
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
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
        if current:
            events.append(current)
    return events


def poll_terminal(client: Any, task_id: str, deadline_s: float) -> dict[str, Any]:
    """轮询直到终态，返回最终 TaskView。"""
    deadline = time.time() + deadline_s
    detail: dict[str, Any] = {}
    while time.time() < deadline:
        detail = client.get(f"/tasks/{task_id}").json()
        if detail.get("status") in TERMINAL_STATUSES:
            return detail
        time.sleep(2)
    return detail  # 超时返回最后一次快照


def compact(evt: dict[str, Any]) -> str:
    name = evt.get("event", "?")
    data = evt.get("data")
    if isinstance(data, dict):
        if name == "node":
            return f"node={data.get('node') or data.get('name') or ''} phase={data.get('phase') or data.get('kind') or ''}"
        if name in TERMINAL_EVENTS:
            return json.dumps({k: v for k, v in data.items() if k in ("status", "task_id", "iteration", "score", "cost")}, ensure_ascii=False)
        if name == "snapshot":
            return f"status={data.get('status')}"
    return (json.dumps(data, ensure_ascii=False)[:80] if data is not None else "-")


def main() -> int:
    from core.llm.pricing import is_peak, status_line

    if is_peak():
        print(f"[拒跑] 高峰时段。{status_line()}")
        return 2

    from fastapi.testclient import TestClient

    from api.main import app

    t0 = time.time()
    rows: list[dict[str, Any]] = []
    sse_events: list[dict[str, Any]] = []
    cancel_info: dict[str, Any] = {}
    error: str | None = None

    try:
        with TestClient(app) as client:
            health = client.get("/health").json()
            print(f"[health] {health.get('status')}")

            # ---- 阶段 A：#1 SSE 主路径 ----
            print("[A] #1 轻量问答（SSE 模式）")
            resp = client.post("/tasks", json={**PHASE_A, "task": PHASE_A["goal"], "use_tools": False, "run_judge": False})
            task_id_a = resp.json()["task_id"]
            sse_events = read_sse(client, task_id_a, t0)
            detail_a = poll_terminal(client, task_id_a, POLL_DEADLINE)
            rows.append({"no": 1, "name": "轻量问答(SSE)", "task_id": task_id_a, "detail": detail_a, "events": len(sse_events)})

            # ---- 阶段 B：#2 工具 / #3 生成 ----
            for idx, spec in enumerate(PHASE_B, start=2):
                print(f"[B] #{idx} {spec['name']}")
                r = client.post("/tasks", json={**spec["body"], "run_judge": False})
                tid = r.json()["task_id"]
                detail = poll_terminal(client, tid, POLL_DEADLINE)
                rows.append({"no": idx, "name": spec["name"], "task_id": tid, "detail": detail, "events": None})

            # ---- 阶段 C：#4/#5/#6 并发 + #5 取消 ----
            print("[C] #4/#5/#6 并发提交，#5 取消实验")
            ids_c: list[str] = []
            for goal in PHASE_C:
                r = client.post("/tasks", json={"task": goal, "use_tools": False, "difficulty": "easy", "run_judge": False})
                ids_c.append(r.json()["task_id"])
            # 等 #5 进入 running（最多 60s），然后取消
            deadline = time.time() + 60
            while time.time() < deadline:
                st5 = client.get(f"/tasks/{ids_c[1]}").json().get("status")
                if st5 == "running":
                    break
                time.sleep(1)
            cr = client.post(f"/tasks/{ids_c[1]}/cancel")
            try:
                cancel_info = cr.json()
            except Exception:  # noqa: BLE001
                cancel_info = {"http": cr.status_code, "text": cr.text[:200]}
            print(f"[C] cancel -> {cancel_info.get('status')} mode={cancel_info.get('mode')}")
            # 等全部终态
            deadline = time.time() + CONCURRENT_DEADLINE
            while time.time() < deadline:
                states = [client.get(f"/tasks/{tid}").json().get("status") for tid in ids_c]
                if all(s in TERMINAL_STATUSES for s in states):
                    break
                time.sleep(2)
            for idx, (tid, goal) in enumerate(zip(ids_c, PHASE_C, strict=True), start=4):
                detail = client.get(f"/tasks/{tid}").json()
                rows.append({"no": idx, "name": f"并发-{goal[:10]}", "task_id": tid, "detail": detail, "events": None})

            # 系统观测：并发上限期间从未出现 running > 3（用 health queue extra 记录当前占用）
            h2 = client.get("/health").json()
            queue_check = h2.get("checks", {}).get("queue", {})
            rows.append({"no": "-", "name": "health.queue(终态后)", "task_id": "-", "detail": {"status": queue_check.get("status"), "extra": {k: v for k, v in queue_check.items() if k != "status"}}, "events": None})
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()
        print("[异常]", error[-600:])

    elapsed = time.time() - t0
    total_cost = sum(r["detail"].get("cost") or 0 for r in rows if isinstance(r.get("detail"), dict))
    done_n = sum(1 for r in rows if isinstance(r.get("detail"), dict) and r["detail"].get("status") == "done")
    canceled_n = sum(1 for r in rows if isinstance(r.get("detail"), dict) and r["detail"].get("status") == "canceled")
    failed_n = sum(1 for r in rows if isinstance(r.get("detail"), dict) and r["detail"].get("status") == "failed")

    # ---- 报告 ----
    lines: list[str] = []
    lines.append("# M1 真实 LLM 批量实测报告（6 条）")
    lines.append("")
    lines.append(f"> {time.strftime('%Y-%m-%d %H:%M:%S')} · 低谷 5 折 · TestClient 进程内 · 总耗时 {elapsed:.0f}s")
    lines.append("")
    ok = (done_n + canceled_n == len([r for r in rows if r["no"] != "-"])) and failed_n == 0 and not error
    lines.append(f"## 结论：{'✅ 全部符合预期' if ok else '⚠️ 存在未达预期项（见明细）'}")
    lines.append("")
    lines.append(f"- done: {done_n} · canceled: {canceled_n} · failed: {failed_n} · 总成本: ¥{round(total_cost, 4)}")
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    lines.append("| # | 场景 | task_id | 终态 | 成本(元) | 耗时(s) | 迭代 | 评分 | 事件数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        d = r.get("detail") or {}
        if "status" not in d and "extra" not in d:
            continue
        if "extra" in d:  # health 行
            lines.append(f"| - | {r['name']} | - | {d.get('status')} | - | - | - | - | {json.dumps(d.get('extra'), ensure_ascii=False)[:60]} |")
            continue
        lines.append(
            f"| {r['no']} | {r['name']} | `{r['task_id']}` | {d.get('status')} | {d.get('cost', 0)} | {round(d.get('duration_ms', 0)/1000, 1)} | {d.get('iterations', 0)} | {d.get('score') or '-'} | {r.get('events') if r.get('events') is not None else '-'} |"
        )
    lines.append("")
    if cancel_info:
        lines.append("## 取消实验（#5）")
        lines.append("")
        lines.append(f"- 响应：`{json.dumps(cancel_info, ensure_ascii=False)[:300]}`")
        lines.append("")
    if sse_events:
        lines.append("## #1 SSE 事件序列")
        lines.append("")
        lines.append("| # | 时刻(s) | 事件 | 内容 |")
        lines.append("|---|---|---|---|")
        for i, evt in enumerate(sse_events, 1):
            lines.append(f"| {i} | {evt.get('t','?')} | `{evt.get('event','?')}` | {compact(evt)} |")
        lines.append("")
    for r in rows:
        d = r.get("detail") or {}
        ans = d.get("final_answer") or ""
        if ans:
            lines.append(f"## #{r['no']} final_answer（前 300 字）")
            lines.append("")
            lines.append("```text")
            lines.append(ans[:300] + ("..." if len(ans) > 300 else ""))
            lines.append("```")
            lines.append("")
    if error:
        lines.append("## 异常")
        lines.append("")
        lines.append("```text")
        lines.append(error[:1500])
        lines.append("```")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[报告] {REPORT_PATH}")
    print(f"[结论] done={done_n} canceled={canceled_n} failed={failed_n} cost=¥{round(total_cost, 4)} elapsed={elapsed:.0f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
