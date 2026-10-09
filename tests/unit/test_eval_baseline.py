"""基线存储与回归 diff 单测（P2 评测台 T04）。

覆盖设计文档 §7 对 T04 的验收要点：

1. **可比性守卫**：模型变 / Prompt hash 变 / 任务集 hash 变 —— 三种情况各自告警；
2. **容忍带判定正确**：带内 → 「无显著变化」；超出 → 标为改善 / 退化；
3. **regressed / improved 清单正确**；新增 / 消失任务识别；
4. **``tool_accuracy=None`` 不参与 delta**（不产生假信号）；
5. ``BaselineModel`` 的 ``as_dict`` / ``from_dict`` **往返一致**；
6. 读**不存在**的基线文件给可读错误（不是裸 traceback）。

外加：可比性元信息采集（Prompt 哈希 / 代码指纹非 git 回退）、``repeat>1`` 时的
2σ 放宽、Markdown 渲染的关键段落、save/load 往返。

全部用**构造**的 ``SuiteMetrics`` / 逐任务记录做单元级验证，不跑真实 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.baseline import (
    DEFAULT_TEMPERATURE,
    BaselineError,
    baseline_path,
    build_baseline,
    classify_metric_change,
    code_metadata,
    comparability_warnings,
    compute_metric_delta,
    diff,
    diff_per_task,
    load_baseline,
    make_per_task_entry,
    metric_tolerance,
    prompts_metadata,
    render_markdown,
    resolve_tolerances,
    save_baseline,
    sha256_file,
    sha256_text,
)
from evaluation.contracts import (
    CHANNEL_API,
    CHANNEL_DIRECT,
    METRIC_AVG_COST,
    METRIC_AVG_STEPS,
    METRIC_PASS_RATE,
    METRIC_P95_LATENCY,
    METRIC_TOOL_ACCURACY,
    BaselineModel,
    SuiteMetrics,
    Tolerances,
)
from evaluation.taskset import SMOKE_TASKSET, load_taskset

# --------------------------------------------------------------------------- #
# 构造器
# --------------------------------------------------------------------------- #
_CREATED_AT = "2026-09-18T14:00:00+08:00"


def suite(**overrides: object) -> SuiteMetrics:
    """构造一份带默认值的 ``SuiteMetrics``（可覆盖任意字段）。"""
    base: dict[str, object] = {
        "evaluated": 40,
        "skipped": 0,
        "passed": 30,
        "failed": 10,
        "pass_rate": 0.75,
        "tool_accuracy": 0.8,
        "tool_expected_tasks": 10,
        "tool_accuracy_soft": 0.85,
        "avg_steps": 3.0,
        "avg_iterations": 0.0,
        "avg_tool_calls": 3.0,
        "tool_calls": 120,
        "tool_failures": 0,
        "tool_call_success_rate": 1.0,
        "total_cost": 2.0,
        "avg_cost": 0.05,
        "avg_latency_ms": 30000.0,
        "p50_latency_ms": 28000.0,
        "p95_latency_ms": 60000.0,
        "max_latency_ms": 90000.0,
        "wall_ms": 0,
        "std": {},
    }
    base.update(overrides)
    return SuiteMetrics(**base)  # type: ignore[arg-type]


def make_model(
    *,
    metrics: SuiteMetrics | None = None,
    per_task: list[dict] | None = None,
    taskset_sha: str = "ts-sha-v1",
    model_large: str = "deepseek-flash",
    model_small: str = "deepseek-flash",
    prompt_files: dict[str, str] | None = None,
    repeat: int = 1,
    channel: str = CHANNEL_DIRECT,
) -> BaselineModel:
    """构造一份元信息齐全的 ``BaselineModel``（默认可比性一致）。"""
    return BaselineModel(
        schema_version=1,
        created_at=_CREATED_AT,
        taskset={
            "name": "yunqi-agent-v1",
            "version": 1,
            "path": "evaluation/tasksets/yunqi_v1.yaml",
            "sha256": taskset_sha,
            "task_count": 40,
            "task_ids_hash": "ids-hash",
        },
        model={
            "llm_model_large": model_large,
            "llm_model_small": model_small,
            "embedding_model_name": "bge-small-zh-v1.5",
            "temperature": DEFAULT_TEMPERATURE,
        },
        prompts={
            "versions": {"planner": "v1", "executor": "v1", "reviewer": "v1"},
            "files_sha256": prompt_files
            if prompt_files is not None
            else {"core/llm/prompts/v1/planner.md": "aaa"},
        },
        code_fingerprint={"git_commit": None, "sources_sha256": {"evaluation/baseline.py": "bbb"}},
        config={"max_iterations": 3, "review_threshold": 7, "temperature": DEFAULT_TEMPERATURE},
        channel=channel,
        repeat=repeat,
        metrics=metrics if metrics is not None else suite(),
        per_task=per_task if per_task is not None else [],
    )


def _pt(task_id: str, passed: bool, **overrides: object) -> dict:
    """便捷构造逐任务记录。"""
    return make_per_task_entry(task_id=task_id, passed=passed, **overrides)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. 可比性守卫
# --------------------------------------------------------------------------- #
class TestComparabilityGuard:
    """模型 / Prompt 哈希 / 任务集哈希变化 → 各自告警。"""

    def test_identical_metadata_no_warning(self) -> None:
        base = make_model()
        current = make_model()
        assert comparability_warnings(base, current) == []
        result = diff(current, base)
        assert result.comparable is True
        assert result.comparability_warnings == []

    def test_model_change_warns(self) -> None:
        base = make_model(model_large="deepseek-flash")
        current = make_model(model_large="deepseek-pro")
        warnings = comparability_warnings(base, current)
        assert warnings, "模型变化必须告警"
        assert any("llm_model_large" in w for w in warnings)
        result = diff(current, base)
        assert result.comparable is False
        assert result.comparability_warnings

    def test_model_small_change_warns(self) -> None:
        base = make_model(model_small="m-small")
        current = make_model(model_small="m-fast")
        assert any("llm_model_small" in w for w in comparability_warnings(base, current))

    def test_prompt_hash_change_warns(self) -> None:
        base = make_model(prompt_files={"core/llm/prompts/v1/executor.md": "old"})
        current = make_model(prompt_files={"core/llm/prompts/v1/executor.md": "new"})
        warnings = comparability_warnings(base, current)
        assert any("Prompt 文件哈希" in w for w in warnings), warnings
        assert diff(current, base).comparable is False

    def test_prompt_file_added_warns(self) -> None:
        base = make_model(prompt_files={"a.md": "x"})
        current = make_model(prompt_files={"a.md": "x", "b.md": "y"})
        assert any("Prompt 文件哈希" in w for w in comparability_warnings(base, current))

    def test_taskset_hash_change_warns(self) -> None:
        base = make_model(taskset_sha="ts-A")
        current = make_model(taskset_sha="ts-B")
        warnings = comparability_warnings(base, current)
        assert any("任务集哈希" in w for w in warnings), warnings
        assert diff(current, base).comparable is False

    def test_force_overrides_comparability(self) -> None:
        base = make_model(model_large="a")
        current = make_model(model_large="b")
        result = diff(current, base, force=True)
        assert result.comparable is True
        assert result.comparability_warnings, "强制比较仍须保留警告"

    def test_missing_metadata_warns(self) -> None:
        base = BaselineModel(metrics=suite(), per_task=[])
        current = make_model()
        assert comparability_warnings(base, current), "一方缺元信息必须告警"

    def test_all_metadata_absent_warns(self) -> None:
        base = BaselineModel(metrics=suite(), per_task=[])
        current = BaselineModel(metrics=suite(), per_task=[])
        warnings = comparability_warnings(base, current)
        assert any("缺少可比性元信息" in w for w in warnings), warnings


# --------------------------------------------------------------------------- #
# 2. 容忍带判定
# --------------------------------------------------------------------------- #
class TestTolerance:
    """带内 → 无显著变化；超出 → 改善 / 退化。"""

    def test_within_tolerance_is_no_significant_change(self) -> None:
        delta = compute_metric_delta(METRIC_PASS_RATE, 0.80, 0.82, 0.05)
        assert delta.delta is not None
        assert delta.within_tolerance is True
        assert classify_metric_change(METRIC_PASS_RATE, delta) == "no_significant_change"

    def test_exceed_improved(self) -> None:
        delta = compute_metric_delta(METRIC_PASS_RATE, 0.60, 0.90, 0.05)
        assert delta.within_tolerance is False
        assert classify_metric_change(METRIC_PASS_RATE, delta) == "improved"

    def test_exceed_degraded(self) -> None:
        delta = compute_metric_delta(METRIC_PASS_RATE, 0.90, 0.60, 0.05)
        assert classify_metric_change(METRIC_PASS_RATE, delta) == "degraded"

    def test_lower_is_better_metrics(self) -> None:
        # avg_steps 变大 = 退化；变小 = 改善（绝对带 0.5 步）
        up = compute_metric_delta(METRIC_AVG_STEPS, 3.0, 4.5, 0.5)
        down = compute_metric_delta(METRIC_AVG_STEPS, 3.0, 1.5, 0.5)
        assert classify_metric_change(METRIC_AVG_STEPS, up) == "degraded"
        assert classify_metric_change(METRIC_AVG_STEPS, down) == "improved"

    def test_relative_tolerance_avg_cost(self) -> None:
        # 相对带 ±20%：基线 0.05 → 折算绝对 0.01；差值 0.008 在带内，0.02 超带
        within = compute_metric_delta(METRIC_AVG_COST, 0.05, 0.058, 0.01)
        beyond = compute_metric_delta(METRIC_AVG_COST, 0.05, 0.07, 0.01)
        assert within.within_tolerance is True
        assert beyond.within_tolerance is False
        assert classify_metric_change(METRIC_AVG_COST, beyond) == "degraded"

    def test_relative_tolerance_p95_latency(self) -> None:
        # 相对带 ±30%：基线 60000ms → 折算绝对 18000ms
        within = compute_metric_delta(METRIC_P95_LATENCY, 60000.0, 70000.0, 18000.0)
        beyond = compute_metric_delta(METRIC_P95_LATENCY, 60000.0, 90000.0, 18000.0)
        assert within.within_tolerance is True  # 10000 <= 18000
        assert beyond.within_tolerance is False
        assert classify_metric_change(METRIC_P95_LATENCY, beyond) == "degraded"

    def test_metric_tolerance_absolute_vs_relative(self) -> None:
        tol = Tolerances()
        assert metric_tolerance(METRIC_PASS_RATE, 0.5, tol) == tol.pass_rate
        assert metric_tolerance(METRIC_AVG_STEPS, 3.0, tol) == tol.avg_steps
        assert metric_tolerance(METRIC_AVG_COST, 0.10, tol) == pytest.approx(0.02)
        assert metric_tolerance(METRIC_P95_LATENCY, 1000.0, tol) == pytest.approx(300.0)

    def test_repeat_widens_tolerance(self) -> None:
        # repeat=1：Δ0.10 超固定带 0.05 → 改善
        base_one = make_model(metrics=suite(pass_rate=0.80), repeat=1)
        curr_one = make_model(
            metrics=suite(pass_rate=0.90), repeat=1
        )
        res_one = diff(curr_one, base_one, Tolerances())
        assert classify_metric_change(
            METRIC_PASS_RATE, res_one.metric_deltas[METRIC_PASS_RATE]
        ) == "improved"

        # repeat=3：σ=0.10 → 带 = max(0.05, 2*0.10)=0.20 → Δ0.10 落带内
        base_multi = make_model(metrics=suite(pass_rate=0.80), repeat=3)
        curr_multi = make_model(
            metrics=suite(pass_rate=0.90, std={METRIC_PASS_RATE: 0.10}), repeat=3
        )
        res_multi = diff(curr_multi, base_multi, Tolerances())
        widened = res_multi.metric_deltas[METRIC_PASS_RATE]
        assert widened.tolerance == pytest.approx(0.20)
        assert widened.within_tolerance is True
        assert classify_metric_change(METRIC_PASS_RATE, widened) == "no_significant_change"

    def test_repeat_widens_avg_cost_absolute_sigma(self) -> None:
        # ★ σ 口径按既定口径 = **绝对单位（元）**。
        # 基线 0.05 → 固定相对带 0.20 → 折算绝对 0.01 元；
        # σ=0.03 元 → 2σ=0.06 元 → 放宽为 max(0.01, 0.06)=0.06 元（量纲正确，非比例）
        base = make_model(metrics=suite(avg_cost=0.05), repeat=3)
        current = make_model(
            metrics=suite(avg_cost=0.10, std={METRIC_AVG_COST: 0.03}), repeat=3
        )
        widened = diff(current, base, Tolerances()).metric_deltas[METRIC_AVG_COST]
        assert widened.tolerance == pytest.approx(0.06)
        assert widened.within_tolerance is True
        assert classify_metric_change(METRIC_AVG_COST, widened) == "no_significant_change"

        # 同数据 repeat=1（无 σ）→ 带仅 0.01 元，Δ0.05 元超带 → 退化
        base_one = make_model(metrics=suite(avg_cost=0.05), repeat=1)
        curr_one = make_model(metrics=suite(avg_cost=0.10), repeat=1)
        tight = diff(curr_one, base_one, Tolerances()).metric_deltas[METRIC_AVG_COST]
        assert tight.tolerance == pytest.approx(0.01)
        assert classify_metric_change(METRIC_AVG_COST, tight) == "degraded"

    def test_resolve_tolerances_small_sample_floor(self) -> None:
        # 小样本（5 条）→ pass_rate 绝对带收紧到 1/5 = 0.2
        current = make_model(metrics=suite(evaluated=5))
        base = make_model(metrics=suite(evaluated=5))
        resolved = resolve_tolerances(current, base)
        assert resolved[METRIC_PASS_RATE] == pytest.approx(0.2)

    def test_resolve_tolerances_returns_absolute_units(self) -> None:
        # 逐指标绝对值：avg_cost 相对带折算为「元」，p95 折算为「毫秒」
        current = make_model(metrics=suite(avg_cost=0.05, p95_latency_ms=60000.0))
        base = make_model(metrics=suite(avg_cost=0.05, p95_latency_ms=60000.0))
        resolved = resolve_tolerances(current, base)
        assert resolved[METRIC_AVG_COST] == pytest.approx(0.05 * Tolerances().avg_cost_rel)
        assert resolved[METRIC_P95_LATENCY] == pytest.approx(
            60000.0 * Tolerances().p95_latency_rel
        )


# --------------------------------------------------------------------------- #
# 3. 回归 / 改善清单
# --------------------------------------------------------------------------- #
class TestPerTaskDiff:
    """regressed / improved / changed / unchanged / added / removed。"""

    def test_regressed_and_improved(self) -> None:
        base = [_pt("t1", True), _pt("t2", False), _pt("t3", True)]
        current = [_pt("t1", False), _pt("t2", True), _pt("t3", True)]
        per = diff_per_task(base, current)
        assert per["regressed"] == ["t1"]
        assert per["improved"] == ["t2"]
        assert per["changed"] == ["t1", "t2"]
        assert per["unchanged"] == ["t3"]
        assert per["added"] == []
        assert per["removed"] == []

    def test_added_and_removed_tasks(self) -> None:
        base = [_pt("t1", True), _pt("t2", True)]
        current = [_pt("t1", True), _pt("t3", False)]
        per = diff_per_task(base, current)
        assert per["added"] == ["t3"]
        assert per["removed"] == ["t2"]
        assert per["regressed"] == []
        assert per["improved"] == []
        assert per["unchanged"] == ["t1"]
        assert any("新出现" in note for note in per["notes"])
        assert any("消失" in note for note in per["notes"])

    def test_diff_lists_and_warns_on_membership_change(self) -> None:
        base = make_model(per_task=[_pt("t1", True), _pt("t2", True)])
        current = make_model(per_task=[_pt("t1", True), _pt("t3", False)])
        result = diff(current, base)
        assert result.regressed == []
        assert result.improved == []
        assert any("任务集变更" in w for w in result.comparability_warnings)

    def test_regressed_task_carries_failed_assertions(self) -> None:
        base = [_pt("t1", True)]
        current = [_pt("t1", False, failed_assertions=["result_contains", "max_steps"])]
        result = diff(make_model(per_task=current), make_model(per_task=base))
        assert result.regressed == ["t1"]
        # 报告里失败明细能给出可追线索
        md = render_markdown(result, base=make_model(per_task=base), current=make_model(per_task=current))
        assert "result_contains" in md and "max_steps" in md


# --------------------------------------------------------------------------- #
# 4. tool_accuracy=None 的 null 安全
# --------------------------------------------------------------------------- #
class TestNullSafety:
    """``tool_accuracy=None`` 不参与 delta，不产生假信号。"""

    def test_none_current_is_undetermined(self) -> None:
        delta = compute_metric_delta(METRIC_TOOL_ACCURACY, 0.9, None, 0.05)
        assert delta.delta is None
        assert delta.delta_pct is None
        assert delta.direction == "undetermined"
        assert classify_metric_change(METRIC_TOOL_ACCURACY, delta) == "undetermined"
        # 绝不把 None 当 0（否则这里会得到 -0.9 的假「下降」）
        assert delta.delta != -0.9

    def test_none_baseline_is_undetermined(self) -> None:
        delta = compute_metric_delta(METRIC_TOOL_ACCURACY, None, 0.9, 0.05)
        assert delta.delta is None
        assert delta.direction == "undetermined"

    def test_both_none_is_undetermined(self) -> None:
        delta = compute_metric_delta(METRIC_TOOL_ACCURACY, None, None, 0.05)
        assert delta.delta is None
        assert classify_metric_change(METRIC_TOOL_ACCURACY, delta) == "undetermined"

    def test_diff_with_none_tool_accuracy(self) -> None:
        base = make_model(metrics=suite(pass_rate=0.8, tool_accuracy=None))
        current = make_model(metrics=suite(pass_rate=0.8, tool_accuracy=0.95))
        result = diff(current, base)
        ta = result.metric_deltas[METRIC_TOOL_ACCURACY]
        assert ta.delta is None
        assert ta.baseline is None
        assert classify_metric_change(METRIC_TOOL_ACCURACY, ta) == "undetermined"
        # 渲染必须 null 安全：显示占位符而非 0
        md = render_markdown(result)
        assert "未参与对比" in md

    def test_zero_baseline_has_no_pct(self) -> None:
        delta = compute_metric_delta(METRIC_AVG_COST, 0.0, 0.02, 0.0)
        assert delta.delta_pct is None


# --------------------------------------------------------------------------- #
# 5. round-trip
# --------------------------------------------------------------------------- #
class TestRoundTrip:
    """``BaselineModel.as_dict`` / ``from_dict`` 往返一致。"""

    def test_model_roundtrip(self) -> None:
        model = make_model(
            metrics=suite(pass_rate=0.5, tool_accuracy=None, avg_cost=0.031234),
            per_task=[_pt("t1", True, steps=3, cost=0.052, tool_sequence=["knowledge_search"])],
            repeat=2,
            channel=CHANNEL_API,
        )
        payload = model.as_dict()
        restored = BaselineModel.from_dict(payload)
        assert restored.as_dict() == payload

    def test_roundtrip_is_json_safe(self) -> None:
        model = make_model(per_task=[_pt("t1", False, failed_assertions=["terminal_status"])])
        text = json.dumps(model.as_dict(), ensure_ascii=False)
        restored = BaselineModel.from_dict(json.loads(text))
        assert restored.as_dict() == model.as_dict()

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        model = make_model(metrics=suite(), per_task=[_pt("t1", True)])
        path = save_baseline(model, "base1", directory=tmp_path)
        assert path.is_file()
        assert path.name == "base1.json"
        loaded = load_baseline("base1", directory=tmp_path)
        assert loaded.as_dict() == model.as_dict()

    def test_baseline_path_helper(self) -> None:
        assert baseline_path("foo").name == "foo.json"
        assert baseline_path("foo.json").name == "foo.json"
        explicit = baseline_path(Path("sub") / "bar")
        assert explicit.name == "bar.json"


# --------------------------------------------------------------------------- #
# 6. 错误处理
# --------------------------------------------------------------------------- #
class TestErrorHandling:
    """读不存在的基线必须给可读错误，而不是裸 traceback。"""

    def test_missing_baseline_readable_error(self, tmp_path: Path) -> None:
        with pytest.raises(BaselineError) as excinfo:
            load_baseline("no_such_baseline", directory=tmp_path)
        message = str(excinfo.value)
        assert "不存在" in message
        assert "no_such_baseline.json" in message
        assert "Traceback" not in message

    def test_corrupt_json_readable_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(BaselineError) as excinfo:
            load_baseline("broken", directory=tmp_path)
        assert "不是合法 JSON" in str(excinfo.value)

    def test_top_level_not_object(self, tmp_path: Path) -> None:
        bad = tmp_path / "list.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(BaselineError, match="顶层必须是对象"):
            load_baseline("list", directory=tmp_path)

    def test_build_baseline_rejects_bad_channel(self) -> None:
        with pytest.raises(BaselineError, match="channel"):
            build_baseline(metrics=suite(), channel="bogus")

    def test_build_baseline_rejects_bad_repeat(self) -> None:
        with pytest.raises(BaselineError, match="repeat"):
            build_baseline(metrics=suite(), repeat=0)


# --------------------------------------------------------------------------- #
# 元信息采集
# --------------------------------------------------------------------------- #
class TestMetadata:
    """Prompt 哈希 / 代码指纹（非 git 回退）/ config。"""

    def test_sha256_helpers(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello", encoding="utf-8")
        assert sha256_file(target) == sha256_text("hello")

    def test_prompts_metadata_stable_and_sensitive(self, tmp_path: Path) -> None:
        v1 = tmp_path / "v1"
        v1.mkdir()
        (v1 / "planner.md").write_text("Planner v1", encoding="utf-8")
        (v1 / "executor.md").write_text("Executor v1", encoding="utf-8")

        first = prompts_metadata(tmp_path)
        second = prompts_metadata(tmp_path)
        assert first == second
        assert len(first["files_sha256"]) == 2
        assert first["versions"]["planner"] == "v1"

        (v1 / "planner.md").write_text("Planner v1 CHANGED", encoding="utf-8")
        assert prompts_metadata(tmp_path)["files_sha256"] != first["files_sha256"]

    def test_code_metadata_non_git_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
        meta = code_metadata(tmp_path, patterns=["*.py"], use_git=True)
        # 非 git 目录 → git_commit 回退为 None，但 sources_sha256 仍产出
        assert meta["git_commit"] is None
        assert "mod.py" in meta["sources_sha256"]

    def test_real_prompts_dir_has_files(self) -> None:
        meta = prompts_metadata()
        assert meta["files_sha256"], "真实 Prompt 目录应能采集到文件"
        assert any(path.endswith("planner.md") for path in meta["files_sha256"])


# --------------------------------------------------------------------------- #
# build_baseline / config
# --------------------------------------------------------------------------- #
class TestBuildBaseline:
    """组装 BaselineModel 的元信息与默认值。"""

    def test_build_populates_metadata(self) -> None:
        taskset = load_taskset(SMOKE_TASKSET)
        model = build_baseline(
            metrics=suite(),
            per_task=[_pt("yq-smoke-lookup", True)],
            taskset=taskset,
            taskset_path=SMOKE_TASKSET,
            channel=CHANNEL_DIRECT,
            repeat=1,
            run_id="run-test",
            created_at=_CREATED_AT,
        )
        assert model.taskset["sha256"] == taskset.canonical_hash()
        assert model.taskset["task_ids_hash"] == taskset.task_ids_hash()
        assert model.taskset["name"] == taskset.name
        assert model.taskset["task_count"] == 5
        assert model.config["run_id"] == "run-test"
        assert model.created_at == _CREATED_AT
        assert model.channel == CHANNEL_DIRECT
        assert model.repeat == 1
        assert model.code_fingerprint.get("sources_sha256")
        assert model.prompts.get("files_sha256")

    def test_build_generates_run_id_and_timestamp(self) -> None:
        model = build_baseline(metrics=suite())
        assert str(model.config.get("run_id", "")).startswith("run-")
        assert model.created_at.endswith("+08:00")


# --------------------------------------------------------------------------- #
# Markdown 渲染
# --------------------------------------------------------------------------- #
class TestRender:
    """报告段落齐全，且不美化数字。"""

    def test_render_sections(self) -> None:
        base = make_model(
            metrics=suite(pass_rate=0.90, avg_cost=0.05),
            per_task=[_pt("t1", True), _pt("t2", True)],
        )
        current = make_model(
            metrics=suite(pass_rate=0.50, avg_cost=0.09),
            per_task=[_pt("t1", False, failed_assertions=["result_contains"], error="答案缺 450")],
        )
        result = diff(current, base)
        md = render_markdown(result, base=base, current=current)
        assert "可比性守卫" in md
        assert "指标对比" in md
        assert "回归 / 改善" in md
        assert "失败任务明细" in md
        assert "t1" in md
        assert "退化" in md  # pass_rate 从 0.90 掉到 0.50 必须如实显示为退化

    def test_render_comparability_warning_prominent(self) -> None:
        base = make_model(model_large="a")
        current = make_model(model_large="b")
        md = render_markdown(diff(current, base))
        assert "不可直接比较" in md

    def test_render_no_embellishment_of_degradation(self) -> None:
        base = make_model(metrics=suite(pass_rate=0.95))
        current = make_model(metrics=suite(pass_rate=0.60))
        md = render_markdown(diff(current, base))
        # 通过率 0.95 → 0.60 必须如实标为「退化」，绝不能因「想证明变好」而写成改善
        pass_rate_row = next(
            line for line in md.splitlines() if line.startswith("| 通过率 pass_rate")
        )
        assert "退化" in pass_rate_row
        assert "改善" not in pass_rate_row
        assert "无显著变化" not in pass_rate_row
