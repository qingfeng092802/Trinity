"""规则断言引擎 + 套件指标汇总 单测（P2 评测台 T02）。

覆盖设计文档 §7 对 T02 的验收要点（四类边界）+ 补充要求：

1. **重复工具折叠**：真实 executor 连续调 3 次 ``knowledge_search`` → 断言按折叠后序列比较；
2. **额外工具允许 / 禁止**：``subset`` / ``exact_sequence`` / ``set`` / ``none`` 四种 mode 各自行为；
3. **数字边界**：``450`` **不能**匹配 ``4500``（朴素子串的经典陷阱，靠 ``regex`` 数字边界守住）；
4. **负样本免责措辞**：各种"如实说不知道"的表达都能通过、而真编造不能通过。

另覆盖：``max_steps=None`` 跳过、``grade=null`` 不误判、``tool_source`` 正确溯源、
断言引擎遇内部异常不抛、以及 :func:`evaluation.metrics.summarize_suite` 的各指标分母口径。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.assertions import (
    RuleEngine,
    check_max_cost,
    check_max_latency,
    check_max_steps,
    check_max_tool_calls,
    check_no_fabrication,
    check_no_tool_failure,
    check_result_contains,
    check_terminal_status,
    check_tool_sequence,
    collapse_repeats,
    count_tool_failures,
    evaluate_task,
    is_subsequence,
)
from evaluation.contracts import (
    ASSERT_MAX_COST,
    ASSERT_MAX_LATENCY,
    ASSERT_MAX_STEPS,
    ASSERT_MAX_TOOL_CALLS,
    ASSERT_NO_FABRICATION,
    ASSERT_NO_TOOL_FAILURE,
    ASSERT_RESULT_CONTAINS,
    ASSERT_TERMINAL_STATUS,
    CHANNEL_DIRECT,
    STATUS_ABORTED,
    STATUS_DONE,
    STATUS_FAILED,
    TOOL_SOURCE_TASK_EVENTS,
    TOOL_SOURCE_TRACES,
    TaskRun,
    normalize,
)
from evaluation.metrics import (
    latency_success_only,
    make_suite_row,
    percentile_nearest_rank,
    summarize_suite,
)
from evaluation.taskset import EvalTask

#: 真实 executor 连续重复调用的工具名
KS = "knowledge_search"
CALC = "calculator"

#: T05 真实诚实回答（逐字取自 _t05_neg_diag_out_20260919_0003.json 的 final_answer，
#: yq-smoke-neg · 直调通道 eval-yq-smoke-neg-0-c1a934b3），句子级豁免修复的靶案例
T05_HONEST_ANSWER = (
    "知识库中没有关于「深圳市云启智能科技有限公司」员工食堂餐费补助标准的相关记录，"
    "因此无法给出具体金额（元/天），也不提供任何推测数字。\n\n"
    "说明：知识库中与「餐费」相关的量化标准只有《员工手册》第 6.4 条的"
    "「出差伙食补贴 100 元/人/天」（依据《员工手册》第 6.4 条，包干发放、不需发票，"
    "当日往返不足 8 小时不予发放），该条属于差旅费口径，与「员工食堂餐费补助」"
    "不是同一项目，不能作为本问题的答案。此外知识库中仅有出差住宿费上限、通讯费补贴、"
    "差旅交通费、报销审批与时效、休假与薪酬、考勤与工时等条目，均未涉及员工食堂补助标准。"
)


# --------------------------------------------------------------------------- #
# 构造夹具
# --------------------------------------------------------------------------- #
def make_task(**overrides: Any) -> EvalTask:
    """构造一条最小可用评测任务（字段可覆盖）。"""
    payload: dict[str, Any] = {
        "id": "yq-test-001",
        "category": "single_doc_lookup",
        "difficulty": "easy",
        "source": "01_员工手册.md 第 6.2 条",
        "prompt": "占位问题",
    }
    payload.update(overrides)
    return EvalTask.model_validate(payload)


def make_run(**overrides: Any) -> TaskRun:
    """构造一条规范化产物；``tool_calls`` 默认与 ``tool_sequence`` 一致。"""
    kwargs: dict[str, Any] = {
        "task_id": "task-abc123",
        "final_answer": "",
        "status": STATUS_DONE,
        "steps": 3,
        "iterations": 0,
        "tool_sequence": [],
        "tool_calls": 0,
        "tool_failures": 0,
        "cost": 0.0,
        "duration_ms": 1000,
        "channel": CHANNEL_DIRECT,
        "tool_source": TOOL_SOURCE_TASK_EVENTS,
    }
    kwargs.update(overrides)
    if "tool_calls" not in overrides:
        kwargs["tool_calls"] = len(kwargs["tool_sequence"])
    return TaskRun(**kwargs)


# --------------------------------------------------------------------------- #
# 边界 1：重复工具折叠
# --------------------------------------------------------------------------- #
class TestCollapseRepeats:
    """``collapse_repeats`` 语义：只折叠**相邻**重复，保留非相邻顺序。"""

    def test_collapse_adjacent_triple(self) -> None:
        assert collapse_repeats([KS, KS, KS]) == [KS]

    def test_collapse_keeps_non_adjacent(self) -> None:
        assert collapse_repeats([KS, CALC, KS]) == [KS, CALC, KS]

    def test_collapse_empty(self) -> None:
        assert collapse_repeats([]) == []

    def test_collapse_mixed_runs(self) -> None:
        assert collapse_repeats([KS, KS, CALC, CALC, CALC, KS]) == [KS, CALC, KS]

    def test_is_subsequence_order_sensitive(self) -> None:
        assert is_subsequence([KS], [KS, KS]) is True
        assert is_subsequence([CALC, KS], [KS, CALC]) is False
        assert is_subsequence([], [KS]) is True

    def test_real_three_step_plan_passes_after_collapse(self) -> None:
        """真实场景：一个 3 步计划产生 3 条同名 ``knowledge_search``。"""
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[KS, KS, KS], steps=3)
        outcome = check_tool_sequence(task, run)
        assert outcome is not None
        assert outcome.passed is True
        assert outcome.evidence["collapsed_actual"] == [KS]
        assert outcome.evidence["actual_sequence"] == [KS, KS, KS]


# --------------------------------------------------------------------------- #
# 边界 2：额外工具允许 / 禁止 + 四种 mode
# --------------------------------------------------------------------------- #
class TestToolSequenceModes:
    """四种工具匹配模式 + ``allow_extra`` 的开关行为。"""

    def test_subset_allows_extra_by_default(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[KS, CALC])
        assert check_tool_sequence(task, run).passed is True

    def test_subset_forbids_extra_when_allow_extra_false(self) -> None:
        task = make_task(
            expected_tools={"mode": "subset", "any_of": [KS], "allow_extra": False}
        )
        run = make_run(tool_sequence=[KS, CALC])
        outcome = check_tool_sequence(task, run)
        assert outcome.passed is False
        assert "额外工具" in outcome.reason

    def test_subset_fails_when_expected_missing(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS, CALC]})
        run = make_run(tool_sequence=[KS])
        assert check_tool_sequence(task, run).passed is False

    def test_exact_sequence_equal_after_collapse(self) -> None:
        task = make_task(
            expected_tools={"mode": "exact_sequence", "sequence": [KS, CALC]}
        )
        run = make_run(tool_sequence=[KS, KS, CALC])
        assert check_tool_sequence(task, run).passed is True

    def test_exact_sequence_order_matters(self) -> None:
        task = make_task(
            expected_tools={"mode": "exact_sequence", "sequence": [KS, CALC]}
        )
        run = make_run(tool_sequence=[CALC, KS])
        assert check_tool_sequence(task, run).passed is False

    def test_exact_sequence_extra_tool_fails(self) -> None:
        task = make_task(
            expected_tools={
                "mode": "exact_sequence",
                "sequence": [KS, CALC],
                "allow_extra": False,
            }
        )
        run = make_run(tool_sequence=[KS, CALC, KS])
        assert check_tool_sequence(task, run).passed is False

    def test_set_order_insensitive(self) -> None:
        task = make_task(expected_tools={"mode": "set", "any_of": [KS, CALC]})
        run = make_run(tool_sequence=[CALC, KS])
        assert check_tool_sequence(task, run).passed is True

    def test_set_deduplicates(self) -> None:
        task = make_task(expected_tools={"mode": "set", "any_of": [KS, CALC]})
        run = make_run(tool_sequence=[KS, KS, CALC, CALC])
        assert check_tool_sequence(task, run).passed is True

    def test_set_fails_on_missing(self) -> None:
        task = make_task(expected_tools={"mode": "set", "any_of": [KS, CALC]})
        run = make_run(tool_sequence=[KS])
        assert check_tool_sequence(task, run).passed is False

    def test_none_mode_requires_no_tool(self) -> None:
        task = make_task(expected_tools={"mode": "none"})
        assert check_tool_sequence(task, make_run(tool_sequence=[])).passed is True
        assert check_tool_sequence(task, make_run(tool_sequence=[KS])).passed is False

    def test_subset_soft_score_recorded(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS, CALC]})
        run = make_run(tool_sequence=[KS])
        outcome = check_tool_sequence(task, run)
        # 命中 1 / 期望 2 = 0.5
        assert outcome.evidence["soft_score"] == 0.5
        assert outcome.evidence["mode"] == "subset"

    def test_no_expected_tools_skips(self) -> None:
        task = make_task()
        assert check_tool_sequence(task, make_run()) is None


# --------------------------------------------------------------------------- #
# 边界 3：数字边界 450 ≠ 4500
# --------------------------------------------------------------------------- #
class TestResultContainsNumberBoundary:
    """数值精度必须靠带数字边界的 ``regex``，朴素 ``contains_all`` 会误命中。"""

    REGEX_450 = r"(?<![0-9])450(?![0-9])"

    def test_exact_number_matches(self) -> None:
        task = make_task(
            expected_result={"contains_all": ["450"], "regex": self.REGEX_450}
        )
        run = make_run(final_answer="住宿费上限为每人每晚 450 元。")
        outcome = check_result_contains(task, run)
        assert outcome.passed is True
        assert outcome.evidence["regex_ok"] is True

    def test_450_does_not_match_4500(self) -> None:
        task = make_task(
            expected_result={"contains_all": ["450"], "regex": self.REGEX_450}
        )
        run = make_run(final_answer="住宿费上限为每人每晚 4500 元。")
        outcome = check_result_contains(task, run)
        assert outcome.passed is False
        assert outcome.evidence["regex_ok"] is False
        assert "正则未命中" in outcome.reason
        # 反证：朴素子串匹配其实会误命中（这正是必须带 regex 的原因）
        assert "450" in normalize("住宿费上限为每人每晚 4500 元。")

    def test_without_regex_naive_substring_would_pass_4500(self) -> None:
        """仅 ``contains_all`` 无 ``regex`` 时，``4500`` 会被误判通过——记录这个陷阱。"""
        task = make_task(expected_result={"contains_all": ["450"]})
        run = make_run(final_answer="住宿费上限为 4500 元。")
        assert check_result_contains(task, run).passed is True

    def test_fullwidth_digits_normalized(self) -> None:
        """NFKC 归一化：全角 ``４５０`` 等价于 ``450``。"""
        task = make_task(
            expected_result={"contains_all": ["450"], "regex": self.REGEX_450}
        )
        run = make_run(final_answer="上限为４５０元")
        assert check_result_contains(task, run).passed is True

    def test_contains_any_group_hit(self) -> None:
        task = make_task(
            expected_result={"contains_any": [["450 元", "450元", "每晚 450"]]}
        )
        assert check_result_contains(task, make_run(final_answer="每晚450")).passed is True
        miss = check_result_contains(task, make_run(final_answer="上限为 450"))
        assert miss.passed is False
        assert miss.evidence["missing_contains_any"]

    def test_not_contains_guard(self) -> None:
        task = make_task(
            expected_result={"contains_all": ["450"], "not_contains": ["350"]}
        )
        bad = check_result_contains(task, make_run(final_answer="450 元，不是 350 元。"))
        assert bad.passed is False
        assert bad.evidence["forbidden_hits"] == ["350"]
        ok = check_result_contains(task, make_run(final_answer="450 元。"))
        assert ok.passed is True

    def test_contains_all_multiple_required(self) -> None:
        task = make_task(
            expected_result={"contains_all": ["直属主管", "部门负责人", "财务部"]}
        )
        run = make_run(final_answer="流程为：直属主管 → 财务部 审批。")
        outcome = check_result_contains(task, run)
        assert outcome.passed is False
        assert outcome.evidence["missing_contains_all"] == ["部门负责人"]


# --------------------------------------------------------------------------- #
# 边界 4：负样本免责措辞
# --------------------------------------------------------------------------- #
class TestNoFabrication:
    """负样本「不编造」：如实说不知道通过，真编造不通过。"""

    DISCLAIMER = [
        "查不到",
        "未收录",
        "未提及",
        "没有找到",
        "未找到",
        "资料中没有",
        "无法确认",
        "未包含",
        "知识库中",
    ]

    def _task(self, **extra: Any) -> EvalTask:
        expected = {"contains_any": [self.DISCLAIMER]}
        expected.update(extra.pop("expected_result", {}))
        return make_task(
            category="negative",
            expect_no_fabrication=True,
            expected_result=expected,
            **extra,
        )

    @pytest.mark.parametrize(
        "answer",
        [
            "知识库中未收录该信息，无法回答。",
            "没有找到相关规定。",
            "资料中没有关于食堂餐费的任何内容。",
            "该问题我无法确认，知识库中不包含此信息。",
            "抱歉，未找到相关制度条款。",
        ],
    )
    def test_disclaimer_phrasings_pass(self, answer: str) -> None:
        outcome = check_no_fabrication(self._task(), make_run(final_answer=answer))
        assert outcome is not None
        assert outcome.passed is True, outcome.reason

    @pytest.mark.parametrize(
        "answer",
        [
            "员工食堂每天的餐费补助标准是 30 元。",
            "每月补助 500 元，直接打入工资卡。",
            "食堂餐补上限为每人每天 40 元。",
        ],
    )
    def test_fabricated_answers_fail(self, answer: str) -> None:
        outcome = check_no_fabrication(self._task(), make_run(final_answer=answer))
        assert outcome.passed is False
        assert "缺少免责措辞" in outcome.reason

    def test_forbidden_value_blocks_even_with_disclaimer(self) -> None:
        """先说"查不到"又补一句编造数字：任务给了禁词就要拦。"""
        task = self._task(expected_result={"not_contains": ["30元", "30 元"]})
        run = make_run(final_answer="知识库中未收录，一般约为 30 元/天。")
        outcome = check_no_fabrication(task, run)
        assert outcome.passed is False
        assert outcome.evidence["forbidden_hits"]

    def test_disabled_flag_skips(self) -> None:
        task = make_task(category="negative", expect_no_fabrication=False)
        assert check_no_fabrication(task, make_run()) is None

    def test_evaluate_negative_emits_result_and_fabrication_outcomes(self) -> None:
        """负样本端到端：``result_contains``（免责措辞）与 ``no_fabrication`` 同时产出并通过。"""
        task = make_task(
            category="negative",
            expect_no_fabrication=True,
            expected_result={"contains_any": [["查不到", "未收录"]]},
            expected_tools={"mode": "subset", "any_of": [KS]},
        )
        run = make_run(final_answer="知识库中未收录该信息。", tool_sequence=[KS])
        result = evaluate_task(task, run)
        names = [o.name for o in result.outcomes]
        assert ASSERT_RESULT_CONTAINS in names
        assert ASSERT_NO_FABRICATION in names
        assert result.passed is True


class TestNoFabricationRegexGuard:
    """形态护栏 ``not_contains_regex``（T01 新接口）：清单外的编造值也要拦住。

    每条正则都在 ``normalize(answer)`` 之后的文本上 ``re.search``；
    命中任一条 + 免责措辞齐备 → 仍判编造（三个条件 AND）。
    """

    #: 与 yunqi_v1.yaml 负样本一致的形态护栏（金额 / 百分比 / 6 位代码 / 时刻）
    REGEXES = [
        r"\d+(?:\.\d+)?\s*(?:元|万元|块钱|块)",
        r"\d+(?:\.\d+)?\s*%",
        r"(?<!\d)\d{6}(?!\d)",
        r"\d{1,2}\s*[:：]\s*\d{2}",
    ]

    def _task(self, **extra: Any) -> EvalTask:
        expected = {"contains_any": [["未收录", "没有找到", "查不到"]]}
        expected.update(extra.pop("expected_result", {}))
        return make_task(
            category="negative",
            expect_no_fabrication=True,
            expected_result=expected,
            **extra,
        )

    def _regex_task(self, **extra: Any) -> EvalTask:
        return self._task(expected_result={"not_contains_regex": self.REGEXES}, **extra)

    def test_fabricated_amount_fails_without_exempt_marker(self) -> None:
        """编造句不含任何豁免标记 → 形态护栏必须拦下（指定 FAIL 案例）。"""
        run = make_run(final_answer="员工食堂餐费补助为每天 40 元，随工资发放。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is False
        hits = outcome.evidence["forbidden_regex_hits"]
        # normalize 去掉全部空白，故命中片段是 "40元" 而非 "40 元"
        assert hits and hits[0]["match"] == "40元"
        assert "命中形态护栏" in outcome.reason
        assert hits[0]["exempt_markers"] == []

    def test_fabricated_six_digit_code_fails(self) -> None:
        run = make_run(final_answer="知识库中未提及公司股票代码，据说为 002123。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is False
        assert outcome.evidence["forbidden_regex_hits"][0]["match"] == "002123"

    def test_fabricated_time_range_fails(self) -> None:
        run = make_run(final_answer="健身房开放时间为 10:30 到 20:30。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is False
        matches = [h["match"] for h in outcome.evidence["forbidden_regex_hits"]]
        assert "10:30" in matches

    def test_honest_answer_without_numbers_passes(self) -> None:
        run = make_run(final_answer="知识库中未收录食堂餐费补助的相关信息。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is True
        assert outcome.evidence["forbidden_regex_hits"] == []

    def test_clause_reference_not_flagged(self) -> None:
        """引用条款号不得误伤：数字后跟的是「条」而非金额单位。"""
        run = make_run(
            final_answer="知识库中未收录食堂补助，可参考《员工手册》第 6.1 条了解差旅补贴。"
        )
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is True
        assert outcome.evidence["forbidden_regex_hits"] == []

    def test_t05_real_honest_answer_passes(self) -> None:
        """★ 本次修复的存在理由：T05 真实诚实回答（合法引用 100 元/人/天）必须 PASS。

        逐字取自 _t05_neg_diag_out_20260919_0003.json 的 final_answer。
        改前（句子级豁免之前）该回答被通配金额正则误判 FAIL（命中「100元」）。
        """
        task = self._task(
            expected_result={
                # yq-smoke-neg 的真实免责清单（T05 回答命中「知识库中」）
                "contains_any": [[
                    "查不到", "未收录", "未提及", "没有找到", "未找到", "资料中没有",
                    "无法确认", "未包含", "知识库中", "没有相关", "无相关", "不包含",
                    "没有收录", "未见", "无法找到", "未提供", "没有提及", "查无",
                ]],
                "not_contains": ["30 元", "30元", "25 元", "25元", "20 元", "20元",
                                 "15 元", "15元", "50 元", "50元"],
                "not_contains_regex": [
                    r"\d+(?:\.\d+)?\s*(?:元|万元|块钱|块)",
                    r"\d+(?:\.\d+)?\s*%",
                ],
            }
        )
        run = make_run(final_answer=T05_HONEST_ANSWER)
        outcome = check_no_fabrication(task, run)
        assert outcome.passed is True, outcome.reason
        # 命中被豁免，且 evidence 能看出命中片段 + 所在句 + 豁免标记
        exempted = outcome.evidence["exempted_regex_hits"]
        assert exempted and exempted[0]["match"] == "100元"
        assert exempted[0]["exempt_markers"], "豁免必须给出标记归因"
        assert outcome.evidence["forbidden_regex_hits"] == []
        assert "已豁免" in outcome.reason

    def test_same_sentence_disclaimer_pardons_hit(self) -> None:
        """规则边界（既定口径）：同一句内「免责 + 编造」→ 按新规则豁免 → PASS。"""
        run = make_run(final_answer="未收录，据说每天 40 元。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is True
        assert outcome.evidence["exempted_regex_hits"][0]["exempt_markers"] == ["未收录"]

    def test_disclaimer_in_previous_sentence_does_not_exempt(self) -> None:
        """前句免责、编造句独立（按 `。` 切句后各自成句）→ 不豁免 → FAIL。

        ⚠️ 与任务描述的示例「未收录。据说每天 40 元。→ 预期 PASS」不一致：按既定
        规格实现后 `。` 是切分符，两句各自成句，编造句内无豁免标记 → FAIL。
        此处按规格钉死实际行为，待复核口径。
        """
        run = make_run(final_answer="未收录。据说每天 40 元。")
        outcome = check_no_fabrication(self._regex_task(), run)
        assert outcome.passed is False
        assert outcome.evidence["forbidden_regex_hits"][0]["match"] == "40元"

    def test_not_contains_list_not_exempted(self) -> None:
        """显式禁值清单不享受句子级豁免：同句有「未收录」也必须 FAIL。"""
        task = self._task(
            expected_result={
                "not_contains": ["30 元", "30元"],
                "not_contains_regex": self.REGEXES,
            }
        )
        run = make_run(final_answer="知识库中未收录，一般每天 30 元。")
        outcome = check_no_fabrication(task, run)
        assert outcome.passed is False
        assert outcome.evidence["forbidden_hits"]

    def test_empty_regex_list_behaves_like_before(self) -> None:
        """向后兼容：字段为空列表时与旧逻辑等价（只看免责措辞 + not_contains）。"""
        task = self._task()  # 不写 not_contains_regex → 默认空列表
        ok = check_no_fabrication(task, make_run(final_answer="知识库中未收录该信息。"))
        assert ok.passed is True
        # 40 元不在 not_contains 清单里、又没有形态护栏 → 与改动前一致：通过
        amount = check_no_fabrication(
            task, make_run(final_answer="知识库中未收录，一般每天 40 元。")
        )
        assert amount.passed is True
        assert amount.evidence["forbidden_regex_hits"] == []

    def test_regex_field_recorded_in_expected(self) -> None:
        outcome = check_no_fabrication(
            self._regex_task(), make_run(final_answer="知识库中未收录该信息。")
        )
        assert outcome.expected["not_contains_regex"] == self.REGEXES

    def test_invalid_regex_fails_closed_without_raising(self) -> None:
        """执行期非法正则 → 不裸抛，fail-closed 判失败（引擎红线）。"""
        bad_task = SimpleNamespace(
            max_steps=None,
            accepted_status=None,
            expected_tools=None,
            expect_no_fabrication=True,
            expected_result=SimpleNamespace(
                contains_any=[["未收录"]],
                not_contains=[],
                not_contains_regex=["("],  # re.compile 会抛 re.error
            ),
        )
        outcome = check_no_fabrication(bad_task, make_run())  # 不抛
        assert outcome.passed is False
        assert outcome.evidence["regex_errors"][0]["pattern"] == "("
        assert "断言内部错误" in outcome.reason


# --------------------------------------------------------------------------- #
# 跳过语义：max_steps=None、grade=null
# --------------------------------------------------------------------------- #
class TestSkipSemantics:
    """缺期望字段的断言跳过；``grade``/``score`` 为 ``None`` 不影响判定。"""

    def test_max_steps_none_skips(self) -> None:
        task = make_task()  # 未设 max_steps
        assert check_max_steps(task, make_run(steps=99)) is None

    def test_max_tool_calls_none_skips(self) -> None:
        assert check_max_tool_calls(make_task(), make_run(tool_sequence=[KS])) is None

    def test_max_cost_none_skips(self) -> None:
        assert check_max_cost(make_task(), make_run(cost=9.9)) is None

    def test_max_latency_none_skips(self) -> None:
        assert check_max_latency(make_task(), make_run(duration_ms=999999)) is None

    def test_evaluate_omits_skipped_assertions(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[KS])
        result = evaluate_task(task, run)
        names = [o.name for o in result.outcomes]
        assert ASSERT_MAX_STEPS not in names
        assert ASSERT_MAX_TOOL_CALLS not in names
        assert ASSERT_MAX_COST not in names
        assert ASSERT_MAX_LATENCY not in names
        # 恒开的两条要在
        assert ASSERT_TERMINAL_STATUS in names
        assert ASSERT_NO_TOOL_FAILURE in names
        assert result.passed is True

    def test_grade_null_does_not_fail(self) -> None:
        task = make_task()
        run = make_run(grade=None, score=None)
        result = evaluate_task(task, run)
        assert run.grade is None
        assert result.passed is True

    def test_max_steps_boundary_inclusive(self) -> None:
        task = make_task(max_steps=3)
        assert check_max_steps(task, make_run(steps=3)).passed is True
        assert check_max_steps(task, make_run(steps=4)).passed is False


# --------------------------------------------------------------------------- #
# tool_source 溯源
# --------------------------------------------------------------------------- #
class TestToolSourceTraceability:
    """工具次数/序列的取源必须写进 evidence，供跨基线口径溯源。"""

    def test_task_events_source_recorded(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[KS], tool_source=TOOL_SOURCE_TASK_EVENTS)
        outcome = check_tool_sequence(task, run)
        assert outcome.evidence["tool_source"] == TOOL_SOURCE_TASK_EVENTS

    def test_traces_fallback_source_on_tool_calls(self) -> None:
        task = make_task(max_tool_calls=5)
        run = make_run(tool_sequence=[KS, KS], tool_source=TOOL_SOURCE_TRACES)
        outcome = check_max_tool_calls(task, run)
        assert outcome.evidence["tool_source"] == TOOL_SOURCE_TRACES
        assert outcome.actual == 2

    def test_divergence_scenario_no_event_sink(self) -> None:
        """走 ``batch.py``（无 ``event_sink``）→ task_events 里 tool_call=0，
        回退旧 traces 才会看到真实调用数；断言据实记录取源。"""
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[], tool_source=TOOL_SOURCE_TASK_EVENTS)
        outcome = check_tool_sequence(task, run)
        assert outcome.passed is False  # 事件源为空 → 判失败
        assert outcome.evidence["tool_source"] == TOOL_SOURCE_TASK_EVENTS
        assert outcome.evidence["actual_sequence"] == []


# --------------------------------------------------------------------------- #
# 终态 / 工具失败 / 事件状态命名空间
# --------------------------------------------------------------------------- #
class TestStatusAndToolFailure:
    """两套 status 命名空间分别作用于不同断言。"""

    def test_terminal_default_accepts_done_only(self) -> None:
        task = make_task()
        assert check_terminal_status(task, make_run(status=STATUS_DONE)).passed is True
        blocked = check_terminal_status(task, make_run(status=STATUS_FAILED))
        assert blocked.passed is False
        assert blocked.expected == [STATUS_DONE]

    def test_terminal_accepted_status_widened(self) -> None:
        task = make_task(accepted_status=[STATUS_DONE, STATUS_ABORTED])
        assert check_terminal_status(task, make_run(status=STATUS_ABORTED)).passed is True

    def test_no_tool_failure(self) -> None:
        task = make_task()
        assert check_no_tool_failure(task, make_run(tool_failures=0)).passed is True
        bad = check_no_tool_failure(task, make_run(tool_failures=2, tool_calls=3))
        assert bad.passed is False
        assert bad.actual == 2

    def test_count_tool_failures_event_namespace(self) -> None:
        assert count_tool_failures(["success", "failed", "timeout"]) == 2
        assert count_tool_failures(["success", "success"]) == 0


# --------------------------------------------------------------------------- #
# 引擎绝不抛异常
# --------------------------------------------------------------------------- #
class TestEngineNeverRaises:
    """断言引擎自设红线：内部错误必须转成 ``passed=false`` + 可读 reason。"""

    def test_bad_max_steps_type_does_not_raise(self) -> None:
        bad_task = SimpleNamespace(
            max_steps="not-a-number",
            accepted_status=None,
            expected_result=None,
            expected_tools=None,
            expect_no_fabrication=False,
        )
        result = evaluate_task(bad_task, make_run(steps=1))  # 不抛
        assert result.passed is False
        failing = [o for o in result.outcomes if o.name == ASSERT_MAX_STEPS]
        assert len(failing) == 1
        assert "断言内部错误" in failing[0].reason
        assert failing[0].evidence["error_type"] == "ValueError"

    def test_bad_contains_any_type_does_not_raise(self) -> None:
        bad_task = SimpleNamespace(
            max_steps=None,
            accepted_status=None,
            expected_result=SimpleNamespace(
                contains_all=[], contains_any=5, regex=None, not_contains=[]
            ),
            expected_tools=None,
            expect_no_fabrication=False,
        )
        result = evaluate_task(bad_task, make_run())
        assert result.passed is False
        failing = [o for o in result.outcomes if o.name == ASSERT_RESULT_CONTAINS]
        assert len(failing) == 1
        assert "断言内部错误" in failing[0].reason

    def test_rule_engine_matches_evaluate_task(self) -> None:
        task = make_task(expected_tools={"mode": "subset", "any_of": [KS]})
        run = make_run(tool_sequence=[KS])
        assert RuleEngine(task).evaluate(run).as_dict() == evaluate_task(task, run).as_dict()


# --------------------------------------------------------------------------- #
# 套件指标汇总（§4 各指标分母口径）
# --------------------------------------------------------------------------- #
class TestSuiteMetrics:
    """``summarize_suite`` / ``make_suite_row`` / 分位算法。"""

    def _rows(self) -> list[dict[str, Any]]:
        # t1：有工具期望，成功
        t1 = make_task(id="yq-1", expected_tools={"mode": "subset", "any_of": [KS]})
        r1 = make_run(task_id="t1", status=STATUS_DONE, steps=3, tool_sequence=[KS],
                      cost=0.05, duration_ms=1000)
        # t2：有工具期望，失败（终态 failed + 未按期望调工具）
        t2 = make_task(id="yq-2", expected_tools={"mode": "subset", "any_of": [KS]})
        r2 = make_run(task_id="t2", status=STATUS_FAILED, steps=2, tool_sequence=[],
                      cost=0.02, duration_ms=500)
        # t3：无工具期望，成功
        t3 = make_task(id="yq-3")
        r3 = make_run(task_id="t3", status=STATUS_DONE, steps=4, cost=0.03, duration_ms=2000)
        return [
            make_suite_row(t1, r1, evaluate_task(t1, r1)),
            make_suite_row(t2, r2, evaluate_task(t2, r2)),
            make_suite_row(t3, r3, evaluate_task(t3, r3)),
        ]

    def test_pass_rate_counts_failure_in_denominator(self) -> None:
        metrics = summarize_suite(self._rows(), skipped=1)
        assert metrics.evaluated == 3
        assert metrics.skipped == 1
        assert metrics.passed == 2
        assert metrics.failed == 1
        assert metrics.pass_rate == pytest.approx(2 / 3, abs=1e-4)

    def test_tool_accuracy_denominator_is_tool_expected_tasks(self) -> None:
        metrics = summarize_suite(self._rows())
        # 只有 t1/t2 声明了 expected_tools；t1 通过、t2 未通过 → 1/2
        assert metrics.tool_expected_tasks == 2
        assert metrics.tool_accuracy == pytest.approx(0.5)

    def test_tool_accuracy_none_when_no_expectation(self) -> None:
        t3 = make_task(id="yq-3")
        r3 = make_run(task_id="t3", steps=4)
        metrics = summarize_suite([make_suite_row(t3, r3, evaluate_task(t3, r3))])
        assert metrics.tool_expected_tasks == 0
        assert metrics.tool_accuracy is None  # 不是 0%
        assert metrics.as_dict()["tool_accuracy"] is None

    def test_tool_call_success_rate_distinct_from_accuracy(self) -> None:
        metrics = summarize_suite(self._rows())
        # 实际发生 1 次工具调用、0 次失败 → 成功率 100%（与"调对没调对"无关）
        assert metrics.tool_calls == 1
        assert metrics.tool_failures == 0
        assert metrics.tool_call_success_rate == pytest.approx(1.0)

    def test_cost_and_steps(self) -> None:
        metrics = summarize_suite(self._rows())
        assert metrics.total_cost == pytest.approx(0.10, abs=1e-6)
        assert metrics.avg_cost == pytest.approx(0.033333, abs=1e-6)
        assert metrics.avg_steps == pytest.approx(3.0)

    def test_latency_percentiles(self) -> None:
        metrics = summarize_suite(self._rows())
        # 延迟 [500,1000,2000] → nearest-rank p50=索引1=1000, p95=索引2=2000
        assert metrics.p50_latency_ms == pytest.approx(1000.0)
        assert metrics.p95_latency_ms == pytest.approx(2000.0)
        assert metrics.max_latency_ms == pytest.approx(2000.0)
        assert metrics.avg_latency_ms == pytest.approx(3500 / 3)

    def test_latency_success_only(self) -> None:
        extra = latency_success_only(self._rows())
        # 仅 done 任务：t1=1000, t3=2000
        assert extra["count"] == 2
        assert extra["p50"] == pytest.approx(1000.0)
        assert extra["p95"] == pytest.approx(2000.0)

    def test_empty_suite(self) -> None:
        metrics = summarize_suite([])
        assert metrics.evaluated == 0
        assert metrics.pass_rate == 0.0
        assert metrics.tool_accuracy is None
        assert metrics.avg_steps == 0.0
        assert metrics.total_cost == 0.0
        assert metrics.p95_latency_ms == 0.0

    def test_percentile_nearest_rank(self) -> None:
        assert percentile_nearest_rank([1, 2, 3, 4], 0.5) == 2.0
        assert percentile_nearest_rank([10], 0.95) == 10.0
        assert percentile_nearest_rank([], 0.5) == 0.0
        assert percentile_nearest_rank([5, 1, 3], 1.0) == 5.0

    def test_repeat_std_recorded(self) -> None:
        metrics = summarize_suite(
            self._rows(), repeat_std={"pass_rate": 0.1, "avg_cost": 0.2}
        )
        assert metrics.std == {"pass_rate": 0.1, "avg_cost": 0.2}

    def test_make_suite_row_has_documented_keys(self) -> None:
        t1 = make_task(id="yq-1", expected_tools={"mode": "subset", "any_of": [KS]})
        r1 = make_run(task_id="t1", tool_sequence=[KS])
        row = make_suite_row(t1, r1, evaluate_task(t1, r1))
        for key in ("id", "passed", "tool_expected", "tool_passed", "failed_assertions"):
            assert key in row
        assert row["tool_expected"] is True
        assert row["tool_passed"] is True
