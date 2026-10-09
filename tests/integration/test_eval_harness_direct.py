"""T03 集成测试：**直调通道**端到端（零 token）+ 归一化适配器 + 一致性自检。

对齐 ``docs/p2_eval_harness_design.md`` §7 T03 验收要点：

1. 直调用 :class:`tests.integration.mock_llm.MockLLMAdapter` 跑通端到端（**零 token**）；
2. **关键断言**：直调通道下 ``task_events`` 真的产生数据（本任务要补的核心缺口——
   ``evaluation/batch.py`` 只挂 ``trace_sink`` 不挂 ``event_sink``，跑出的任务无任何事件）；
3. ``TaskRun`` 字段齐备（对照 ``evaluation/contracts.py``）、``tool_source`` 正确溯源；
4. ``event_sink`` / ``trace_sink`` 一致性自检生效（工具序列不一致时能报出来）。

**隔离库纪律**：直调通道写入的是 ``data/trinity.db`` 的**一致性副本**
（用 SQLite backup API 整库复制，含 RAG 向量库），跑完删除；本文件断言生产库未被污染。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.constants import TASK_EVT_NODE_END, TASK_EVT_TOOL_CALL, TRACE_MAX_LIMIT
from config import PROJECT_ROOT, Settings
from core.agent.base import TraceRecord
from core.agent.planner import PLAN_SCHEMA
from core.workflow.state import ExecutorDecision, ReviewVerdict
from evaluation.contracts import (
    CHANNEL_API,
    CHANNEL_DIRECT,
    STATUS_DONE,
    STATUS_FAILED,
    TOOL_SOURCE_TASK_EVENTS,
    TOOL_SOURCE_TRACES,
    TaskRun,
)
from evaluation.harness import (
    EvalHarness,
    SuiteReport,
    check_tool_consistency,
    to_taskrun_api,
    to_taskrun_direct,
)
from evaluation.taskset import Defaults, EvalTask, EvalTaskSet, ExpectedTools
from tests.integration.mock_llm import MockLLMAdapter

#: 运行库（含 4 份 ready 文档 + RAG 向量索引）；隔离副本的源
SOURCE_DB = PROJECT_ROOT / "data" / "trinity.db"

#: ``TaskRun`` 契约字段全集（对照 contracts.py 逐字段核对）
EXPECTED_TASKRUN_FIELDS = {
    "task_id",
    "final_answer",
    "status",
    "steps",
    "iterations",
    "tool_sequence",
    "tool_calls",
    "tool_failures",
    "cost",
    "duration_ms",
    "channel",
    "tool_source",
    "event_range",
    "error",
    "raw_summary",
    "wall_ms",
    "score",
    "grade",
    "meta",
}


# --------------------------------------------------------------------------- #
# 夹具与构造辅助
# --------------------------------------------------------------------------- #
def _ready_docs(db_path: Path) -> int:
    """只读查询源库里的 ``ready`` 文档数；表不存在按 0 处理。"""
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return int(con.execute("select count(*) from documents where status='ready'").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        con.close()


@pytest.fixture()
def make_harness(tmp_path: Path) -> Iterator[Any]:
    """构造 :class:`EvalHarness` 的工厂；退出时关闭并删掉隔离副本。

    显式传 ``source_db_path`` / ``eval_db_dir``，不依赖环境里的 ``DB_URL``，
    使本文件与 ``conftest`` 的临时库夹具互不干扰。
    """
    if not SOURCE_DB.is_file():
        pytest.skip(f"缺少含 RAG 索引的源库，无法验证隔离副本：{SOURCE_DB}")

    harnesses: list[EvalHarness] = []

    def _factory(taskset: EvalTaskSet, **kwargs: Any) -> EvalHarness:
        kwargs.setdefault("settings", Settings())
        if "source_db_path" not in kwargs:
            # 用默认源库时先确认它真播种过：没有 ready 文档的话，requires_ready_docs
            # 的任务会被整套 skip，断言以「runs=0」的形式假失败——那是环境缺播种，
            # 不是代码回归。播种：起服务后上传 data/demo_docs/ 那 4 份演示文档。
            if _ready_docs(SOURCE_DB) == 0:
                pytest.skip(f"源库没有 ready 文档，检索类任务无料可查：{SOURCE_DB}")
            kwargs["source_db_path"] = SOURCE_DB
        kwargs.setdefault("eval_db_dir", tmp_path / "eval_db")
        harness = EvalHarness(taskset, **kwargs)
        harnesses.append(harness)
        return harness

    yield _factory

    for harness in harnesses:
        try:
            harness.close()
        except Exception:  # noqa: BLE001 - 清理失败不影响测试结论
            pass


def _taskset(*tasks: EvalTask, **defaults: Any) -> EvalTaskSet:
    """用给定任务构造一个最小任务集（默认 use_tools=True，run_judge=False 省成本）。"""
    resolved = {
        "max_iterations": 3,
        "review_threshold": 7,
        "use_tools": True,
        "run_judge": False,
        "timeout_s": 60,
    }
    resolved.update(defaults)
    return EvalTaskSet(
        name="t03-harness",
        description="T03 集成测试任务集",
        defaults=Defaults(**resolved),
        tasks=list(tasks),
    )


def _task(task_id: str = "t03-001", *, requires_ready: bool = True) -> EvalTask:
    """一条最小任务：期望命中 ``calculator``（本地、无外部依赖）。"""
    return EvalTask(
        id=task_id,
        category="multi_tool",
        difficulty="easy",
        tags=["smoke"],
        source="T03 集成测试（本地计算，无外部依赖）",
        prompt="请帮我算一下 1+1，并用一句话给出结论。",
        expected_tools=ExpectedTools(mode="subset", any_of=["calculator"]),
        requires_ready_docs=requires_ready,
    )


def _tool_llm(*, tool_name: str | None = "calculator") -> MockLLMAdapter:
    """脚本化 Mock：executor 的**第一步**调用工具，其余步骤直接给结论。

    注意本 mock 带内部计数，**只适用于单次运行**（repeat>1 请用 :func:`_plain_llm`）。
    """
    counter = {"exec": 0}

    def responder(schema: Any, _text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return ["算一下", "给结论"]
        if schema is ExecutorDecision:
            counter["exec"] += 1
            if counter["exec"] == 1 and tool_name:
                return {
                    "thought": "需要算一下",
                    "tool_name": tool_name,
                    "tool_args": {"expression": "1+1"},
                    "answer": "",
                }
            return {"thought": "汇总", "tool_name": None, "tool_args": {}, "answer": "本步结论"}
        if schema is ReviewVerdict:
            return {
                "pass": True,
                "score": 9,
                "comment": "结构完整",
                "final_answer": "这是 Mock 生成的最终答案。",
            }
        raise AssertionError(f"未预期的 schema：{schema}")

    return MockLLMAdapter(responder)


def _plain_llm() -> MockLLMAdapter:
    """不调工具的确定性 Mock（可跨多次运行复用）。"""

    def responder(schema: Any, _text: str) -> Any:
        if schema is PLAN_SCHEMA:
            return ["写一句", "给结论"]
        if schema is ExecutorDecision:
            return {"thought": "直接给结论", "tool_name": None, "tool_args": {}, "answer": "本步结论"}
        if schema is ReviewVerdict:
            return {"pass": True, "score": 9, "comment": "ok", "final_answer": "终稿。"}
        raise AssertionError(f"未预期的 schema：{schema}")

    return MockLLMAdapter(responder)


def _record(task_id: str, *, tool_name: str | None, step: int = 0) -> TraceRecord:
    """构造一条旧 ``traces`` 埋点记录。"""
    tool_calls = (
        [{"name": tool_name, "args": {}, "result": "2", "status": "success", "duration_ms": 3}]
        if tool_name
        else []
    )
    return TraceRecord(
        trace_id=f"{task_id}-rec-{step}",
        task_id=task_id,
        step=step,
        role="executor",
        input="i",
        output="o",
        tool_calls=tool_calls,
        timestamp=float(step) + 1.0,
        duration_ms=5,
        status="success",
        cost=0.001,
    )


def _node_event(seq: int, event_type: str, *, role: str, step: int = 0, tool_name: str | None = None) -> dict[str, Any]:
    """构造一条 ``/trace`` 风格的事件 dict（HTTP 通道用）。"""
    return {
        "event_seq": seq,
        "step": step,
        "sub_step": 0 if tool_name else None,
        "event_type": event_type,
        "role": role,
        "node": role,
        "thought": "",
        "tool_name": tool_name,
        "arguments": {"query": "x"} if tool_name else None,
        "observation": "ok" if tool_name else "",
        "latency_ms": 3,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": 0.0,
        "status": "success",
        "error_code": None,
        "error_message": None,
        "sse_seq": None,
        "created_at": "2026-09-18T10:00:00+08:00",
    }


# --------------------------------------------------------------------------- #
# 1. 直调端到端 + ★ task_events 落盘（核心验收）
# --------------------------------------------------------------------------- #
def test_direct_channel_emits_task_events_and_complete_taskrun(make_harness: Any) -> None:
    """★ 直调通道跑通（零 token）：``task_events`` 真落盘 + ``TaskRun`` 字段齐备。"""
    harness = make_harness(_taskset(_task()), llm=_tool_llm(), channel=CHANNEL_DIRECT, repeat=1)

    report = harness.run_all()

    assert isinstance(report, SuiteReport)
    assert report.aborted is False
    assert report.skipped == []
    assert len(report.runs) == 1
    run = report.runs[0]

    # --- TaskRun 字段齐备（对照 contracts.py 逐字段核对）---
    assert set(run.as_dict().keys()) == EXPECTED_TASKRUN_FIELDS

    # --- 直调通道基本口径 ---
    assert run.channel == CHANNEL_DIRECT
    assert run.status == STATUS_DONE
    assert run.tool_source == TOOL_SOURCE_TASK_EVENTS
    assert run.tool_sequence == ["calculator"]
    assert run.tool_calls == 1
    assert run.tool_failures == 0
    assert run.steps >= 3  # planner + executor + reviewer
    assert run.iterations == 0  # 首轮通过，reviewer 不加一
    assert run.cost > 0
    assert run.final_answer.strip()
    assert run.event_range is not None and run.event_range[0] <= run.event_range[1]

    # --- 隔离副本：meta 记录实际库路径，且不是生产库 ---
    assert run.meta["db_path"] == str(harness.db_path)
    assert Path(harness.db_path) != SOURCE_DB

    # --- event_sink / trace_sink 一致性自检 ---
    consistency = run.meta["consistency"]
    assert consistency["checked"] is True
    assert consistency["matched"] is True, consistency["warning"]

    # ================= ★ 核心：task_events 真的落盘 =================
    events = harness.database.list_events(run.task_id, limit=TRACE_MAX_LIMIT)
    assert len(events) > 0, "直调通道必须产生 task_events（batch.py 缺 event_sink 的缺口）"
    event_types = [event.event_type for event in events]
    assert TASK_EVT_NODE_END in event_types
    assert TASK_EVT_TOOL_CALL in event_types

    # 用独立 sqlite3 连接直接读盘，证明数据真的写到了副本文件
    raw = sqlite3.connect(f"file:{Path(harness.db_path).as_posix()}?mode=ro", uri=True)
    try:
        total = raw.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id = ?", (run.task_id,)
        ).fetchone()[0]
        tool_total = raw.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id = ? AND event_type = 'tool_call'",
            (run.task_id,),
        ).fetchone()[0]
    finally:
        raw.close()
    assert total > 0
    assert total == len(events)
    assert tool_total == 1

    # --- 生产库未被污染 ---
    prod = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
    try:
        polluted = prod.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_id = ?", (run.task_id,)
        ).fetchone()[0]
    finally:
        prod.close()
    assert polluted == 0, "隔离副本必须保证生产库不被写入"


# --------------------------------------------------------------------------- #
# 2. tool_source 回退：无事件时溯源到旧 traces
# --------------------------------------------------------------------------- #
def test_tool_source_falls_back_to_traces_without_events() -> None:
    """无 ``task_events`` 时 ``tool_source`` 回退 ``traces``，工具序列仍可从旧表还原。"""
    records = [_record("task-x", tool_name="calculator")]
    state = {
        "task_id": "task-x",
        "final_answer": "答案是 2。",
        "status": "done",
        "iteration": 0,
        "review_score": 8,
    }

    run = to_taskrun_direct(state, records, [], db_path="/tmp/fake.db")

    assert run.tool_source == TOOL_SOURCE_TRACES
    assert run.tool_sequence == ["calculator"]
    assert run.tool_calls == 1
    assert run.steps == 1  # 回退 len(records)
    assert run.status == STATUS_DONE
    assert run.event_range is None
    assert run.meta["consistency"]["checked"] is False
    assert "warning" in run.meta


# --------------------------------------------------------------------------- #
# 3. 一致性自检：两侧工具序列不一致时必须报出
# --------------------------------------------------------------------------- #
def test_consistency_selfcheck_reports_mismatch() -> None:
    """``traces`` 工具序列 ≠ ``task_events`` 工具序列 → ``matched=False`` + warning。"""
    records = [_record("task-x", tool_name="calculator")]
    events = [
        _node_event(1, TASK_EVT_NODE_END, role="planner"),
        _node_event(2, TASK_EVT_TOOL_CALL, role="executor", tool_name="knowledge_search"),
    ]

    result = check_tool_consistency(records, events)
    assert result["checked"] is True
    assert result["matched"] is False
    assert result["warning"]
    assert result["traces_tool_sequence"] == ["calculator"]
    assert result["events_tool_sequence"] == ["knowledge_search"]

    # 归一化产物也应把该不一致带出来（隐患变可检测项）
    state = {"task_id": "task-x", "final_answer": "a", "status": "done", "iteration": 0}
    run = to_taskrun_direct(state, records, events)
    assert run.meta["consistency"]["matched"] is False
    assert run.tool_source == TOOL_SOURCE_TASK_EVENTS


# --------------------------------------------------------------------------- #
# 4. HTTP 通道归一化（用假 client，零网络、零 token）
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """最小 httpx.Response 替身。"""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHTTPClient:
    """模拟运行中的 :8000 服务：``POST /tasks`` → ``GET /tasks/{id}`` → ``/trace``。"""

    task_id = "task-fake000000001"

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.posted: tuple[str, dict[str, Any]] | None = None

    def __enter__(self) -> _FakeHTTPClient:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.posted = (url, dict(json or {}))
        return _FakeResponse(201, {"task_id": self.task_id, "status": "queued", "queue_position": 0})

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        if url == f"/tasks/{self.task_id}":
            return _FakeResponse(
                200,
                {
                    "task_id": self.task_id,
                    "task": "t",
                    "status": "done",
                    "iterations": 0,
                    "score": 8,
                    "grade": None,
                    "final_answer": "答案。",
                    "cost": 0.05,
                    "duration_ms": 36000,
                    "tool_calls": 1,
                    "tool_failures": 0,
                    "difficulty": "easy",
                    "error": None,
                },
            )
        if url.endswith("/trace"):
            items = [
                _node_event(1, TASK_EVT_NODE_END, role="planner"),
                _node_event(2, TASK_EVT_TOOL_CALL, role="executor", tool_name="knowledge_search"),
                _node_event(3, TASK_EVT_NODE_END, role="reviewer", step=1),
            ]
            return _FakeResponse(
                200,
                {
                    "task_id": self.task_id,
                    "items": items,
                    "total": len(items),
                    "limit": 200,
                    "after_seq": 0,
                    "has_more": False,
                    "next_after_seq": None,
                    "events_available": True,
                    "unavailable_reason": None,
                },
            )
        raise AssertionError(f"未预期的 GET：{url}")


def test_api_channel_normalization_with_fake_client(
    make_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP 通道适配器：submit → poll → trace → 归一化（用假 client，不触网）。"""
    fake = _FakeHTTPClient
    monkeypatch.setattr(httpx, "Client", fake)

    harness = make_harness(_taskset(_task()), llm=_plain_llm(), channel=CHANNEL_API, repeat=1)
    report = harness.run_all()

    assert len(report.runs) == 1
    run = report.runs[0]
    assert run.channel == CHANNEL_API
    assert run.status == STATUS_DONE
    assert run.tool_source == TOOL_SOURCE_TASK_EVENTS
    assert run.tool_sequence == ["knowledge_search"]
    assert run.tool_calls == 1
    assert run.steps == 2  # 两条 node_end
    assert run.cost == 0.05
    assert run.duration_ms == 36000
    assert run.score == 8
    assert run.grade is None
    assert run.event_range == (1, 3)
    assert run.meta["base_url"]
    # tasks.tool_calls(1) == /trace 工具事件数(1) → 无分歧标记
    assert "tool_calls_mismatch" not in run.meta


def test_api_old_task_without_events_falls_back_to_traces() -> None:
    """老任务（``events_available=false``）：``tool_source=traces``，无序列但保留计数。"""
    view = {
        "task_id": "task-old",
        "status": "done",
        "final_answer": "a",
        "tool_calls": 3,
        "tool_failures": 1,
        "cost": 0.02,
        "duration_ms": 100,
    }

    run = to_taskrun_api(view, [])

    assert run.tool_source == TOOL_SOURCE_TRACES
    assert run.tool_sequence == []
    assert run.tool_calls == 0  # 契约：tool_calls == len(tool_sequence)
    assert run.steps == 0
    assert run.raw_summary["tool_calls"] == 3
    assert run.meta["events_available"] is False
    assert "warning" in run.meta


# --------------------------------------------------------------------------- #
# 5. repeat：产出 N 个 TaskRun（聚合不在此处）
# --------------------------------------------------------------------------- #
def test_repeat_produces_n_runs(make_harness: Any) -> None:
    """``repeat=2`` → 同一任务产出 2 个独立 ``TaskRun``（task_id 唯一）。"""
    harness = make_harness(
        _taskset(_task()), llm=_plain_llm(), channel=CHANNEL_DIRECT, repeat=2
    )

    report = harness.run_all()

    assert len(report.runs) == 2
    assert len({run.task_id for run in report.runs}) == 2
    assert all(run.status == STATUS_DONE for run in report.runs)
    assert all(run.steps >= 3 for run in report.runs)


# --------------------------------------------------------------------------- #
# 6. 成本护栏：超限立即中止剩余任务
# --------------------------------------------------------------------------- #
def test_cost_cap_aborts_batch(make_harness: Any) -> None:
    """累计成本 > ``cost_cap_cny`` → 立刻停下剩余任务并标注原因。"""
    harness = make_harness(
        _taskset(_task("t03-a"), _task("t03-b")),
        llm=_plain_llm(),
        channel=CHANNEL_DIRECT,
        repeat=1,
        cost_cap_cny=0.0,
    )

    report = harness.run_all()

    assert report.aborted is True
    assert "成本护栏" in report.abort_reason
    assert len(report.runs) == 1  # 跑完第一条即触发中止
    assert report.cost_total > 0


# --------------------------------------------------------------------------- #
# 7. 前置条件：空知识库 → 检索类任务 skipped（证明副本是「真库」而非空库）
# --------------------------------------------------------------------------- #
def test_requires_ready_docs_skipped_on_empty_kb(
    make_harness: Any, tmp_path: Path
) -> None:
    """源库无 ``ready`` 文档时，``requires_ready_docs`` 任务被 skipped（不进分母）。"""
    from storage.db import Database

    empty_source = tmp_path / "empty_source.db"
    database = Database(f"sqlite:///{empty_source.as_posix()}")
    database.init_db()
    database.dispose()

    harness = make_harness(
        _taskset(_task("t03-skip", requires_ready=True)),
        llm=_plain_llm(),
        channel=CHANNEL_DIRECT,
        source_db_path=empty_source,
        eval_db_dir=tmp_path / "eval_db_skip",
    )

    report = harness.run_all()

    assert report.runs == []
    assert len(report.skipped) == 1
    assert report.skipped[0].task_id == "t03-skip"
    assert "知识库未就绪" in report.skipped[0].reason


# --------------------------------------------------------------------------- #
# 8. 终态判定：沿用 API 侧单一出口（失败态带 error）
# --------------------------------------------------------------------------- #
def test_direct_failed_state_normalized_with_error() -> None:
    """节点失败（``status=failed``）→ ``TaskRun.status=failed`` 且 ``error`` 非空。"""
    state = {
        "task_id": "task-fail",
        "final_answer": "",
        "status": "failed",
        "iteration": 0,
        "review_comment": "planner 异常：PlanError: plan 为空",
    }

    run = to_taskrun_direct(state, [], [])

    assert run.status == STATUS_FAILED
    assert run.error
    assert "PlanError" in run.error
    assert run.meta["non_retryable"] is False


def test_taskrun_contract_fields_are_complete() -> None:
    """回归哨兵：``TaskRun.as_dict()`` 的键集合 == 契约字段全集。"""
    sample = TaskRun(
        task_id="t",
        final_answer="",
        status=STATUS_DONE,
        steps=0,
        iterations=0,
        tool_sequence=[],
        tool_calls=0,
        tool_failures=0,
        cost=0.0,
        duration_ms=0,
        channel=CHANNEL_DIRECT,
        tool_source=TOOL_SOURCE_TASK_EVENTS,
    )
    assert set(sample.as_dict().keys()) == EXPECTED_TASKRUN_FIELDS


__all__ = ["EXPECTED_TASKRUN_FIELDS", "SOURCE_DB"]
