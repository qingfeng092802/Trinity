"""阶段 3 单测（二）：评测集加载、指标汇总、LLM Judge。

Judge 用集成测试里那份 MockLLMAdapter（同一份假适配器实现，避免两处漂移）。
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import pytest

from config import PROJECT_ROOT
from core.agent.base import TraceRecord
from evaluation.dataset import (
    DEFAULT_DATASET,
    DIFFICULTY_ORDER,
    DatasetError,
    EvalItem,
    dataset_stats,
    load_dataset,
)
from evaluation.judge import (
    EvalResult,
    JudgeError,
    JudgeVerdict,
    LLMJudge,
    evaluate_state,
    grade_for,
)
from evaluation.metrics import (
    GRADE_ORDER,
    BatchMetrics,
    TaskOutcome,
    format_report,
    summarize,
)
from tests.integration.mock_llm import MockLLMAdapter

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


def make_record(role: str = "planner", step: int = 0, **overrides: Any) -> TraceRecord:
    """造一条埋点。"""
    base: dict[str, Any] = {
        "trace_id": f"task-1-{role}-{step}",
        "task_id": "task-1",
        "step": step,
        "role": role,
        "input": "in",
        "output": "out",
        "tool_calls": [],
        "timestamp": time.time(),
        "duration_ms": 100,
        "status": "success",
        "token_in": 10,
        "token_out": 5,
        "cost": 0.001,
    }
    base.update(overrides)
    return TraceRecord.model_validate(base)


def make_outcome(**overrides: Any) -> TaskOutcome:
    """造一条任务产物。"""
    base: dict[str, Any] = {
        "task": "t",
        "task_id": "task-1",
        "status": "done",
        "iterations": 0,
        "duration_ms": 1000,
        "token_in": 100,
        "token_out": 50,
        "cost": 0.01,
        "tool_calls": 1,
        "tool_failures": 0,
    }
    base.update(overrides)
    return TaskOutcome(**base)


# --------------------------------------------------------------------------- #
# 评测集
# --------------------------------------------------------------------------- #
class TestDataset:
    """50 条评测集的加载与校验。"""

    def test_loads_full_dataset(self) -> None:
        items = load_dataset()
        assert len(items) == 50
        assert len({item.id for item in items}) == 50
        assert all(item.expected_criteria for item in items)

    def test_stats_match_total(self) -> None:
        stats = dataset_stats(load_dataset())
        assert stats["total"] == 50
        assert sum(stats[level] for level in DIFFICULTY_ORDER) == 50
        assert stats["easy"] >= 15 and stats["hard"] >= 8

    def test_difficulty_filter(self) -> None:
        items = load_dataset(difficulty="hard")
        assert items and all(item.difficulty == "hard" for item in items)

    def test_limit(self) -> None:
        assert len(load_dataset(limit=3)) == 3
        assert load_dataset(limit=0) == []

    def test_ids_filter(self) -> None:
        items = load_dataset(ids=["t001", "t050"])
        assert {item.id for item in items} == {"t001", "t050"}

    def test_default_path_exists(self) -> None:
        assert DEFAULT_DATASET.is_file()

    def test_missing_file_raises(self) -> None:
        with pytest.raises(DatasetError, match="评测集不存在"):
            load_dataset(TEST_SCRATCH_ROOT / "no-such-file.jsonl")

    def test_bad_json_reports_line_number(self) -> None:
        path = TEST_SCRATCH_ROOT / f"bad-{uuid4().hex[:8]}.jsonl"
        good = '{"id":"a","task":"x","expected_criteria":["c"]}\n'
        path.write_text(good + "{不是 JSON }\n", encoding="utf-8")
        with pytest.raises(DatasetError, match=":2 JSON 非法"):
            load_dataset(path)

    def test_invalid_field_is_rejected(self) -> None:
        path = TEST_SCRATCH_ROOT / f"invalid-{uuid4().hex[:8]}.jsonl"
        path.write_text(
            '{"id":"a","task":"x","expected_criteria":["c"],"difficulty":"insane"}\n',
            encoding="utf-8",
        )
        with pytest.raises(DatasetError, match="字段不合法"):
            load_dataset(path)

    def test_empty_criteria_is_rejected(self) -> None:
        path = TEST_SCRATCH_ROOT / f"empty-{uuid4().hex[:8]}.jsonl"
        path.write_text('{"id":"a","task":"x","expected_criteria":[]}\n', encoding="utf-8")
        with pytest.raises(DatasetError, match="字段不合法"):
            load_dataset(path)

    def test_duplicate_id_is_rejected(self) -> None:
        path = TEST_SCRATCH_ROOT / f"dup-{uuid4().hex[:8]}.jsonl"
        line = '{"id":"a","task":"x","expected_criteria":["c"]}\n'
        path.write_text(line + line, encoding="utf-8")
        with pytest.raises(DatasetError, match="id 重复"):
            load_dataset(path)


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #
class TestMetrics:
    """汇总口径：完成率只认 done，平均分只在评测过的任务上求。"""

    def test_empty_input(self) -> None:
        metrics = summarize([])
        assert metrics.tasks == 0
        assert metrics.completion_rate == 0.0
        assert metrics.avg_score is None
        assert set(metrics.grade_distribution) == set(GRADE_ORDER)

    def test_completion_counts_only_done(self) -> None:
        metrics = summarize(
            [
                make_outcome(status="done"),
                make_outcome(status="done"),
                make_outcome(status="aborted"),
                make_outcome(status="failed"),
            ]
        )
        assert (metrics.completed, metrics.aborted, metrics.failed) == (2, 1, 1)
        assert metrics.completion_rate == pytest.approx(0.5)

    def test_avg_score_ignores_unjudged(self) -> None:
        metrics = summarize(
            [
                make_outcome(score=8, grade="good"),
                make_outcome(score=6, grade="fair"),
                make_outcome(),  # 未评测
                make_outcome(),  # 未评测
            ]
        )
        assert metrics.judged == 2
        assert metrics.avg_score == pytest.approx(7.0)

    def test_grade_distribution(self) -> None:
        metrics = summarize(
            [
                make_outcome(score=9, grade="excellent"),
                make_outcome(score=8, grade="good"),
                make_outcome(score=8, grade="good"),
            ]
        )
        assert metrics.grade_distribution["good"] == 2
        assert metrics.grade_distribution["excellent"] == 1
        assert metrics.grade_distribution["poor"] == 0

    def test_tool_success_rate_by_calls(self) -> None:
        metrics = summarize(
            [
                make_outcome(tool_calls=4, tool_failures=1),
                make_outcome(tool_calls=0, tool_failures=0),
            ]
        )
        assert metrics.tool_calls == 4
        assert metrics.tool_success_rate == pytest.approx(0.75)

    def test_cost_and_duration_totals(self) -> None:
        metrics = summarize([make_outcome(cost=0.01), make_outcome(cost=0.03, duration_ms=3000)])
        assert metrics.total_cost == pytest.approx(0.04)
        assert metrics.avg_cost == pytest.approx(0.02)
        assert metrics.total_duration_ms == 4000
        assert metrics.avg_duration_ms == pytest.approx(2000.0)

    def test_as_dict_is_json_ready(self) -> None:
        import json

        payload = summarize([make_outcome(score=7, grade="good")]).as_dict()
        assert json.loads(json.dumps(payload))["avg_score"] == 7.0

    def test_format_report_contains_key_lines(self) -> None:
        outcomes = [make_outcome(score=9, grade="excellent")]
        text = format_report(summarize(outcomes), outcomes)
        assert "批量评测报表" in text
        assert "完成率 100.0%" in text
        assert "平均分        9.00" in text
        assert "excellent:1" in text
        assert "成功率 100.0%" in text


class TestOutcomeFromState:
    """从最终状态 + 埋点还原产物。"""

    def test_aggregates_records(self) -> None:
        records = [
            make_record(
                role="planner",
                step=0,
                token_in=100,
                token_out=50,
                cost=0.01,
                duration_ms=200,
            ),
            make_record(
                role="executor",
                step=0,
                token_in=300,
                token_out=70,
                cost=0.02,
                duration_ms=300,
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {},
                        "result": "1",
                        "status": "success",
                        "duration_ms": 1,
                    },
                    {
                        "name": "web_search",
                        "args": {},
                        "result": "boom",
                        "status": "failed",
                        "duration_ms": 2,
                    },
                ],
            ),
        ]
        state = {"task": "算个数", "task_id": "task-1", "status": "done", "iteration": 1}
        outcome = TaskOutcome.from_state(state, records, score=9, grade="excellent")
        assert outcome.duration_ms == 500
        assert outcome.token_in == 400
        assert outcome.cost == pytest.approx(0.03)
        assert (outcome.tool_calls, outcome.tool_failures) == (2, 1)
        assert (outcome.score, outcome.grade) == (9, "excellent")

    def test_handles_missing_keys(self) -> None:
        outcome = TaskOutcome.from_state({}, [])
        assert outcome.status == "unknown"
        assert outcome.cost == 0.0


# --------------------------------------------------------------------------- #
# Judge
# --------------------------------------------------------------------------- #
class TestGradeMapping:
    """等级由分数推导，不由模型自报。"""

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (10, "excellent"),
            (9, "excellent"),
            (8, "good"),
            (7, "good"),
            (5, "fair"),
            (4, "poor"),
            (0, "poor"),
        ],
    )
    def test_bands(self, score: int, expected: str) -> None:
        assert grade_for(score) == expected


class TestLLMJudge:
    """评测器行为（用 Mock LLM，不联网）。"""

    def _judge(self, payload: Any) -> tuple[LLMJudge, MockLLMAdapter]:
        llm = MockLLMAdapter(lambda schema, text: payload)
        return LLMJudge(llm=llm), llm

    def test_evaluate_builds_result(self) -> None:
        payload = {
            "score": 8,
            "reasoning": "三条标准里满足两条",
            "issues": ["缺少数据来源", "  "],
            "suggestions": ["补充引用链接"],
        }
        judge, llm = self._judge(payload)
        records = [make_record(role="planner", step=0), make_record(role="reviewer", step=0)]

        result = judge.evaluate(
            task="解释混合检索",
            criteria=["点明组合", "说明目的", "控制字数"],
            final_answer="混合检索是……",
            task_id="task-1",
            records=records,
            status="done",
            iterations=1,
        )

        assert isinstance(result, EvalResult)
        assert result.score == 8
        assert result.grade == "good"
        assert result.issues == ["缺少数据来源"]  # 空白项被丢掉
        assert result.suggestions == ["补充引用链接"]
        assert result.trace_refs == [record.trace_id for record in records]
        assert result.reasoning == "三条标准里满足两条"
        assert result.task_id == "task-1"
        # 提示词里必须带上验收标准与执行摘要
        prompt = llm.calls[0]["text"]
        assert "控制字数" in prompt
        assert "节点埋点" in prompt

    def test_aborted_status_is_visible_to_judge(self) -> None:
        judge, llm = self._judge({"score": 3, "reasoning": "", "issues": [], "suggestions": []})
        judge.evaluate(
            task="难任务",
            criteria=["标准一"],
            final_answer="草稿",
            task_id="task-2",
            records=[make_record()],
            status="aborted",
            iterations=3,
        )
        prompt = llm.calls[0]["text"]
        assert "aborted" in prompt
        assert "迭代轮数：3" in prompt

    def test_empty_criteria_raises(self) -> None:
        judge, _ = self._judge({"score": 0})
        with pytest.raises(JudgeError, match="没有验收标准"):
            judge.evaluate(task="x", criteria=[], final_answer="y", task_id="t")

    def test_empty_records_is_tolerated(self) -> None:
        judge, _ = self._judge({"score": 5, "reasoning": "r", "issues": [], "suggestions": []})
        result = judge.evaluate(task="x", criteria=["c"], final_answer="y", task_id="t", records=[])
        assert result.trace_refs == []
        assert result.grade == "fair"

    def test_evaluate_state_convenience(self) -> None:
        judge, _ = self._judge({"score": 9, "reasoning": "ok", "issues": [], "suggestions": []})
        state = {
            "task": "任务",
            "task_id": "task-9",
            "final_answer": "答案",
            "status": "done",
            "iteration": 0,
        }
        result = evaluate_state(state, criteria=["c"], records=[], llm=judge.llm)
        assert result.task_id == "task-9"
        assert result.grade == "excellent"

    def test_verdict_contract(self) -> None:
        verdict = JudgeVerdict(score=7)
        assert verdict.issues == [] and verdict.suggestions == []

    def test_judge_prompt_exists(self) -> None:
        from core.agent.base import prompt_path

        assert prompt_path("judge", "v1").is_file()

    def test_batch_metrics_type(self) -> None:
        assert isinstance(summarize([make_outcome()]), BatchMetrics)
        assert isinstance(EvalItem(id="x", task="y", expected_criteria=["z"]), EvalItem)
