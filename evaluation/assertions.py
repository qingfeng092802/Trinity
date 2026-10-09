"""规则断言引擎：把一次任务执行（``TaskRun``）对照任务期望（``EvalTask``）判成结构化结果。

设计依据：``docs/p2_eval_harness_design.md`` §3.2 / §3.3 / §9（逐条对齐）。

职责边界
--------
本模块**只依赖冻结契约** ``evaluation/contracts.py``（以及事件级常量 ``api.constants``），
**不 import** ``harness`` / ``baseline`` / ``batch``。任务的期望结构（``EvalTask``）以
``TYPE_CHECKING`` 前向引用方式标注，运行时按属性鸭子类型读取，避免与 ``taskset`` 形成
运行时耦合。

九类断言（名字取 ``contracts.ASSERT_*``，禁止自造字符串）
--------------------------------------------------------
+---------------------+----------------------------+------------------------------+
| 断言                 | 触发条件                    | 判据                          |
+=====================+============================+==============================+
| ``result_contains``  | 有 ``expected_result``      | contains_all/any/regex/       |
|                      |                            | not_contains 全过             |
| ``tool_sequence``    | 有 ``expected_tools``       | 按 mode 匹配（见下）          |
| ``max_steps``        | 有 ``max_steps``            | ``run.steps <= max``          |
| ``terminal_status``  | 恒开                        | ``run.status in accepted``    |
| ``no_tool_failure``  | 恒开                        | ``run.tool_failures == 0``    |
| ``max_tool_calls``   | 有 ``max_tool_calls``       | ``run.tool_calls <= max``     |
| ``max_cost``         | 有 ``max_cost_cny``         | ``run.cost <= max``（CNY）    |
| ``max_latency``      | 有 ``max_latency_ms``       | ``run.duration_ms <= max``    |
| ``no_fabrication``   | ``expect_no_fabrication``   | 负样本：含免责措辞且无编造词  |
+---------------------+----------------------------+------------------------------+

关键口径（既定口径，硬约束）
----------------------------
* ``tool_calls`` 权威源 = ``task_events`` 的 ``tool_call`` 事件数，回退旧 ``traces``；
  断言**不重新取源**，只消费 ``run.tool_calls`` 并在 ``evidence`` 里带上 ``run.tool_source``
  以便报告溯源（不同源数字不可跨基线直接比较）。
* ``steps`` = **节点执行次数**（``node_end`` 事件数），**不是** ``run.iterations``；
  断言只用 ``run.steps``。
* ``max_steps`` 为 ``None``（契约内是 ``int | None``）→ **跳过该断言**，不判失败。
* ``grade`` 可为 ``null``（Q7）→ 断言**从不**消费 ``grade``，故为 ``null`` 不会误判。
* 负样本默认不调 judge（Q6）→ ``no_fabrication`` 用**纯规则**：
  ① 命中免责措辞（``expected_result.contains_any``，表达"不知道"）；
  ② 未出现被任务标注为「编造」的禁词（``expected_result.not_contains``，不豁免）；
  ③ 未命中形态护栏（``expected_result.not_contains_regex``：带单位的金额/时刻/
  独立 6 位代码等形态，清单外的编造值也能拦），且命中所在句**不含豁免标记**
  （句子级豁免，见 :func:`check_no_fabrication` docstring）。三者同时成立才通过。
* **断言引擎自身绝不抛异常**：任何内部错误都转成 ``passed=false`` + 可读 ``reason``
  （见 :func:`_safe_check`）。

状态命名空间（务必区分，§9.6）
-----------------------------
* **事件级** status（``api.constants.STATUS_SUCCESS`` = ``success`` / ``failed`` / ``timeout``）
  描述单条工具调用/事件的成败——用于判定「工具失败」。
* **任务级** status（``contracts.STATUS_DONE`` = ``done`` / ``aborted`` / ``failed`` /
  ``canceled``）描述整条任务的状态机——用于 ``terminal_status`` 断言。
  两者**不复用**同一组字面量。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from api.constants import STATUS_SUCCESS

from evaluation.contracts import (
    ASSERT_MAX_COST,
    ASSERT_MAX_LATENCY,
    ASSERT_MAX_STEPS,
    ASSERT_MAX_TOOL_CALLS,
    ASSERT_NO_FABRICATION,
    ASSERT_NO_TOOL_FAILURE,
    ASSERT_RESULT_CONTAINS,
    ASSERT_TERMINAL_STATUS,
    ASSERT_TOOL_SEQUENCE,
    DEFAULT_ACCEPTED_STATUS,
    AssertionOutcome,
    TaskAssertionResult,
    TaskRun,
    normalize,
    round_cost,
)

if TYPE_CHECKING:  # 仅类型标注，运行时按属性鸭子类型读取，避免与 taskset 形成运行时耦合
    from evaluation.taskset import EvalTask

#: 取证时截取答案头部的长度（对齐设计文档 §3.2 evidence 里的 ``final_answer_head``）
ANSWER_HEAD_LIMIT = 300

#: 工具序列四种匹配模式（与 ``taskset.ExpectedTools.mode`` 的 Literal 一致）
MODE_NONE = "none"
MODE_SUBSET = "subset"
MODE_EXACT_SEQUENCE = "exact_sequence"
MODE_SET = "set"
TOOL_MODES: tuple[str, ...] = (MODE_NONE, MODE_SUBSET, MODE_EXACT_SEQUENCE, MODE_SET)


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def _answer_head(text: str, limit: int = ANSWER_HEAD_LIMIT) -> str:
    """取答案前 ``limit`` 个字符（取证用，避免把整篇答案塞进报告）。"""
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


def count_tool_failures(statuses: Sequence[str]) -> int:
    """按**事件级** status 命名空间统计工具调用失败次数。

    Args:
        statuses: 每次工具调用的事件 status（``success`` / ``failed`` / ``timeout``）。

    Returns:
        status ``!= STATUS_SUCCESS`` 的条数。这是「调用本身成不成功」的口径，
        与「有没有调对工具」（``tool_sequence`` 断言）**严格区分**。
    """
    return sum(1 for status in statuses if status != STATUS_SUCCESS)


def collapse_repeats(names: Sequence[str]) -> list[str]:
    """折叠**连续重复**的工具名（``[ks, ks, ks] → [ks]``，设计文档 §3.1）。

    真实 executor 一次节点内每个子步骤最多调 1 个工具（``core/workflow/state.py`` 的
    ``ExecutorDecision`` 只有一个 ``tool_name``），所以一个 3 步计划会产生 3 条同名
    ``knowledge_search``；工具断言默认按折叠后序列比较，否则严格相等会全判失败。

    只折叠**相邻**重复，不折叠非相邻（``[ks, calc, ks]`` 保持原样）——顺序信息要保留。
    """
    collapsed: list[str] = []
    for name in names:
        if not collapsed or collapsed[-1] != name:
            collapsed.append(name)
    return collapsed


def is_subsequence(expected: Sequence[str], actual: Sequence[str]) -> bool:
    """判断 ``expected`` 是否为 ``actual`` 的**子序列**（保序、可重、允许额外）。

    ``subset`` 模式的核心：期望工具按顺序都能在实际序列里找到即可，
    中间夹带的其他工具被跳过（是否允许夹带由 ``allow_extra`` 另判）。
    """
    iterator = iter(actual)
    return all(any(item == wanted for item in iterator) for wanted in expected)


def _base_evidence(run: TaskRun) -> dict[str, Any]:
    """所有断言共用的取证底座：任务 id、取源、可跳转回放的 trace 提示。"""
    evidence: dict[str, Any] = {
        "task_id": run.task_id,
        "tool_source": run.tool_source,
        "trace_hint": f"GET /tasks/{run.task_id}/trace?after_seq=0",
    }
    # harness 若把原始工具事件塞进 meta（设计文档 §3.2 的 tool_events），一并带上便于归因
    tool_events = run.meta.get("tool_events") if isinstance(run.meta, dict) else None
    if tool_events:
        evidence["tool_events"] = tool_events
    return evidence


# --------------------------------------------------------------------------- #
# 断言 1：result_contains
# --------------------------------------------------------------------------- #
def check_result_contains(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """结果包含断言（有 ``expected_result`` 才判）。

    四项子判据全部通过才算过：

    * ``contains_all``：归一化后每条都必须出现；
    * ``contains_any``：每个内层组至少命中一个（同一事实的多种写法）；
    * ``regex``：对**归一化后**的答案做 ``re.search``（数值精度用；正则自带数字边界
      ``(?<!\\d)…(?!\\d)``，故 ``450`` 不会命中 ``4500``）；
    * ``not_contains``：默认留空的反例护栏，出现即失败。

    注意 ``contains_all`` 是**朴素子串**匹配——单靠它 ``450`` 会命中 ``4500``，
    所以数值类期望**必须**同时给 ``regex``（见 :func:`_check_number_boundary` 的单测）。
    """
    expected_result = getattr(task, "expected_result", None)
    if expected_result is None:
        return None

    contains_all = list(getattr(expected_result, "contains_all", []) or [])
    contains_any = list(getattr(expected_result, "contains_any", []) or [])
    regex = getattr(expected_result, "regex", None)
    not_contains = list(getattr(expected_result, "not_contains", []) or [])

    answer = run.final_answer or ""
    normalized = normalize(answer)

    missing_all = [item for item in contains_all if normalize(item) not in normalized]

    missing_any: list[list[str]] = []
    for group in contains_any:
        options = list(group or [])
        if not any(normalize(option) in normalized for option in options):
            missing_any.append(options)

    regex_ok = True
    regex_error: str | None = None
    if regex:
        try:
            regex_ok = re.search(regex, normalized) is not None
        except re.error as exc:  # 非法正则视为该子判据不通过（不抛给上层）
            regex_ok = False
            regex_error = str(exc)

    forbidden_hits = [item for item in not_contains if normalize(item) in normalized]

    passed = not missing_all and not missing_any and regex_ok and not forbidden_hits

    if passed:
        reason = "结果断言通过：必含子串 / 多写法 / 正则 / 反例护栏全部满足"
    else:
        parts: list[str] = []
        if missing_all:
            parts.append(f"缺少必含子串 {missing_all}")
        if missing_any:
            parts.append(f"多写法组均未命中：{missing_any}")
        if regex and not regex_ok:
            parts.append(
                f"正则未命中：{regex!r}" + (f"（{regex_error}）" if regex_error else "")
            )
        if forbidden_hits:
            parts.append(f"出现反例禁词 {forbidden_hits}")
        reason = "结果断言失败：" + "；".join(parts)

    evidence: dict[str, Any] = {
        **_base_evidence(run),
        "final_answer_head": _answer_head(answer),
        "normalized_answer": _answer_head(normalized),
        "missing_contains_all": missing_all,
        "missing_contains_any": missing_any,
        "regex": regex,
        "regex_ok": regex_ok,
        "regex_error": regex_error,
        "forbidden_hits": forbidden_hits,
    }
    expected_repr = {
        "contains_all": contains_all,
        "contains_any": contains_any,
        "regex": regex,
        "not_contains": not_contains,
    }
    return AssertionOutcome(
        name=ASSERT_RESULT_CONTAINS,
        passed=passed,
        expected=expected_repr,
        actual=_answer_head(answer),
        reason=reason,
        evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# 断言 2：tool_sequence
# --------------------------------------------------------------------------- #
def check_tool_sequence(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """工具序列断言（有 ``expected_tools`` 才判，四种 mode 互斥）。

    * ``none``：不得调用任何工具（判原始序列为空）；
    * ``subset``（默认）：期望是实际的**子序列**（保序、可重）；``allow_extra=false``
      时额外要求实际不出现期望之外的工具名；
    * ``exact_sequence``：折叠后**严格顺序相等**；
    * ``set``：折叠后**无序集合相等**。

    ``collapse_repeats=true``（默认）时先把期望与实际的**连续重复**各自折叠。
    ``subset``/``set`` 另算软分 ``soft_score``（命中期望去重集 / 期望去重集），
    写进 ``evidence`` 供 :func:`evaluation.metrics.summarize_suite` 汇总 ``tool_accuracy_soft``。
    """
    expected_tools = getattr(task, "expected_tools", None)
    if expected_tools is None:
        return None

    mode = getattr(expected_tools, "mode", MODE_SUBSET) or MODE_SUBSET
    any_of = list(getattr(expected_tools, "any_of", []) or [])
    sequence = list(getattr(expected_tools, "sequence", []) or [])
    collapse = bool(getattr(expected_tools, "collapse_repeats", True))
    allow_extra = bool(getattr(expected_tools, "allow_extra", True))

    raw_actual = list(run.tool_sequence or [])
    collapsed_actual = collapse_repeats(raw_actual) if collapse else raw_actual

    expected_list: list[str]
    if mode == MODE_NONE:
        expected_list = []
        passed = len(raw_actual) == 0
        reason = (
            "工具断言通过：未调用任何工具（mode=none）"
            if passed
            else f"工具断言失败：mode=none 要求不调用工具，实际调用 {raw_actual}"
        )
    elif mode == MODE_EXACT_SEQUENCE:
        expected_list = collapse_repeats(sequence) if collapse else sequence
        passed = collapsed_actual == expected_list
        reason = (
            "工具断言通过：折叠后严格序列相等"
            if passed
            else (
                f"工具断言失败：期望序列 {expected_list} ≠ 实际序列 {collapsed_actual}"
                f"（mode=exact_sequence，collapse_repeats={collapse}）"
            )
        )
    elif mode == MODE_SET:
        expected_list = collapse_repeats(any_of) if collapse else any_of
        expected_set = set(expected_list)
        actual_set = set(collapsed_actual)
        passed = expected_set == actual_set
        reason = (
            "工具断言通过：折叠后集合相等（mode=set）"
            if passed
            else (
                f"工具断言失败：期望工具集合 {sorted(expected_set)} ≠ "
                f"实际集合 {sorted(actual_set)}（mode=set）"
            )
        )
    else:  # MODE_SUBSET（默认）
        expected_list = collapse_repeats(any_of) if collapse else any_of
        passed = is_subsequence(expected_list, collapsed_actual)
        extra_tools = sorted(set(collapsed_actual) - set(expected_list))
        if passed and not allow_extra and extra_tools:
            passed = False
            reason = (
                f"工具断言失败：subset 期望 {expected_list} 是实际子序列，"
                f"但 allow_extra=false 且出现额外工具 {extra_tools}"
            )
        elif passed:
            reason = (
                f"工具断言通过：期望 {expected_list} 是实际 {collapsed_actual} 的子序列"
                f"（allow_extra={allow_extra}）"
            )
        else:
            reason = (
                f"工具断言失败：期望 {expected_list} 不是实际 {collapsed_actual} 的子序列"
                "（mode=subset）"
            )

    soft_score: float | None = None
    if mode in (MODE_SUBSET, MODE_SET):
        expected_dedup = set(collapse_repeats(any_of) if collapse else any_of)
        if expected_dedup:
            soft_score = len(set(collapsed_actual) & expected_dedup) / len(expected_dedup)

    evidence: dict[str, Any] = {
        **_base_evidence(run),
        "mode": mode,
        "expected_tools": expected_list,
        "actual_sequence": raw_actual,
        "collapsed_actual": collapsed_actual,
        "collapse_repeats": collapse,
        "allow_extra": allow_extra,
        "soft_score": soft_score,
    }
    expected_repr = {
        "mode": mode,
        "expected": expected_list,
        "collapse_repeats": collapse,
        "allow_extra": allow_extra,
    }
    return AssertionOutcome(
        name=ASSERT_TOOL_SEQUENCE,
        passed=passed,
        expected=expected_repr,
        actual=raw_actual,
        reason=reason,
        evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# 断言 3：max_steps（None 跳过）
# --------------------------------------------------------------------------- #
def check_max_steps(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """步数上限断言。

    ``max_steps`` 为 ``None`` → **跳过**（返回 ``None``，不判失败）。

    ★ 口径：``run.steps`` = 节点执行次数（``node_end`` 事件数），**不是**
    ``run.iterations``（后者是"被 reviewer 打回的轮数"，首轮成功任务会得 0）。
    """
    limit = getattr(task, "max_steps", None)
    if limit is None:
        return None
    limit_int = int(limit)
    passed = int(run.steps) <= limit_int
    reason = (
        f"步数断言通过：{run.steps} 步 ≤ 上限 {limit_int} 步"
        if passed
        else f"步数断言失败：实际 {run.steps} 步 > 上限 {limit_int} 步（口径=节点执行次数）"
    )
    return AssertionOutcome(
        name=ASSERT_MAX_STEPS,
        passed=passed,
        expected=limit_int,
        actual=int(run.steps),
        reason=reason,
        evidence={
            **_base_evidence(run),
            "steps": int(run.steps),
            "iterations": int(run.iterations),
            "steps_definition": "节点执行次数（node_end 事件数），非 iterations",
        },
    )


# --------------------------------------------------------------------------- #
# 断言 4：terminal_status（恒开）
# --------------------------------------------------------------------------- #
def check_terminal_status(task: "EvalTask", run: TaskRun) -> AssertionOutcome:
    """任务终态断言（恒开，不可跳过）。

    可接受终态 = ``task.accepted_status``（任务可放宽为含 ``aborted``），缺省 = ``[done]``。
    任务级 status 命名空间（``done`` / ``aborted`` / ``failed`` / ``canceled``）。
    """
    accepted_raw = getattr(task, "accepted_status", None)
    accepted = list(accepted_raw) if accepted_raw else list(DEFAULT_ACCEPTED_STATUS)
    passed = run.status in accepted
    reason = (
        f"终态断言通过：{run.status} ∈ {accepted}"
        if passed
        else (
            f"终态断言失败：{run.status} ∉ {accepted}"
            + (f"（error={run.error}）" if run.error else "")
        )
    )
    return AssertionOutcome(
        name=ASSERT_TERMINAL_STATUS,
        passed=passed,
        expected=accepted,
        actual=run.status,
        reason=reason,
        evidence={
            **_base_evidence(run),
            "status": run.status,
            "error": run.error,
            "channel": run.channel,
        },
    )


# --------------------------------------------------------------------------- #
# 断言 5：no_tool_failure（恒开）
# --------------------------------------------------------------------------- #
def check_no_tool_failure(task: "EvalTask", run: TaskRun) -> AssertionOutcome:
    """工具失败断言（恒开）：不得有 ``status != success`` 的工具调用。

    ★ 与 ``tool_sequence`` **严格区分**：本断言看「调了但失败」，``tool_sequence``
    看「有没有按期望调对」。
    """
    failures = int(run.tool_failures)
    passed = failures == 0
    reason = (
        "工具失败断言通过：未出现失败的工具调用"
        if passed
        else f"工具失败断言失败：{failures} 次工具调用非 {STATUS_SUCCESS}（事件级 status 口径）"
    )
    return AssertionOutcome(
        name=ASSERT_NO_TOOL_FAILURE,
        passed=passed,
        expected=0,
        actual=failures,
        reason=reason,
        evidence={
            **_base_evidence(run),
            "tool_failures": failures,
            "tool_calls": int(run.tool_calls),
        },
    )


# --------------------------------------------------------------------------- #
# 断言 6：max_tool_calls
# --------------------------------------------------------------------------- #
def check_max_tool_calls(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """工具调用次数上限断言（有 ``max_tool_calls`` 才判）。

    ★ ``run.tool_calls`` 权威源 = ``task_events`` 的 ``tool_call`` 事件数，回退旧 ``traces``；
    ``evidence.tool_source`` 记录实际取源，供报告溯源（不同源数字不可跨基线直接比较）。
    """
    limit = getattr(task, "max_tool_calls", None)
    if limit is None:
        return None
    limit_int = int(limit)
    calls = int(run.tool_calls)
    passed = calls <= limit_int
    reason = (
        f"工具次数断言通过：{calls} 次 ≤ 上限 {limit_int} 次"
        if passed
        else f"工具次数断言失败：实际 {calls} 次 > 上限 {limit_int} 次"
    )
    return AssertionOutcome(
        name=ASSERT_MAX_TOOL_CALLS,
        passed=passed,
        expected=limit_int,
        actual=calls,
        reason=reason,
        evidence={
            **_base_evidence(run),
            "tool_calls": calls,
            "tool_source": run.tool_source,
        },
    )


# --------------------------------------------------------------------------- #
# 断言 7：max_cost（CNY）
# --------------------------------------------------------------------------- #
def check_max_cost(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """成本上限断言（有 ``max_cost_cny`` 才判），单位 CNY 元，比较前 ``round(x, 6)``。"""
    limit = getattr(task, "max_cost_cny", None)
    if limit is None:
        return None
    limit_rounded = round_cost(limit)
    cost_rounded = round_cost(run.cost)
    passed = cost_rounded <= limit_rounded
    reason = (
        f"成本断言通过：¥{cost_rounded:.6f} ≤ 上限 ¥{limit_rounded:.6f}"
        if passed
        else f"成本断言失败：实际 ¥{cost_rounded:.6f} > 上限 ¥{limit_rounded:.6f}"
    )
    return AssertionOutcome(
        name=ASSERT_MAX_COST,
        passed=passed,
        expected=limit_rounded,
        actual=cost_rounded,
        reason=reason,
        evidence={
            **_base_evidence(run),
            "cost": cost_rounded,
            "unit": "CNY",
        },
    )


# --------------------------------------------------------------------------- #
# 断言 8：max_latency
# --------------------------------------------------------------------------- #
def check_max_latency(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """延迟上限断言（有 ``max_latency_ms`` 才判）。

    延迟主口径 = ``run.duration_ms``（各节点耗时求和，去掉排队等待）；
    墙钟 ``run.wall_ms`` 仅作旁参取证，不参与判定。
    """
    limit = getattr(task, "max_latency_ms", None)
    if limit is None:
        return None
    limit_int = int(limit)
    duration = int(run.duration_ms)
    passed = duration <= limit_int
    reason = (
        f"延迟断言通过：{duration} ms ≤ 上限 {limit_int} ms"
        if passed
        else f"延迟断言失败：实际 {duration} ms > 上限 {limit_int} ms（口径=duration_ms）"
    )
    return AssertionOutcome(
        name=ASSERT_MAX_LATENCY,
        passed=passed,
        expected=limit_int,
        actual=duration,
        reason=reason,
        evidence={
            **_base_evidence(run),
            "duration_ms": duration,
            "wall_ms": int(run.wall_ms),
        },
    )


# --------------------------------------------------------------------------- #
# 断言 9：no_fabrication（负样本，纯规则）
# --------------------------------------------------------------------------- #
#: 形态护栏的**句子级豁免**：把归一化后的回答按这些字符切成句子（T05 校准口径）
SENTENCE_DELIMITERS: str = "。；;！？\n"

#: 免责类豁免标记：命中所在句子里出现任一即豁免该句的形态命中
FABRIC_EXEMPT_MARKERS: tuple[str, ...] = (
    "未收录",
    "没有找到",
    "无法给出",
    "不是同一项目",
    "不能作为",
    "并非",
    "未规定",
    "未涉及",
    "不予",
    "仅供参考",
)

#: 引用类豁免：书名号引用（《…》）/ 条款号引用（第 N 条）
_EXEMPT_QUOTE_RE = re.compile(r"《[^》]{1,40}》")
_EXEMPT_CLAUSE_RE = re.compile(r"第\d+(?:\.\d+)?条")


def split_sentences(normalized: str) -> list[tuple[int, int, str]]:
    """把归一化后的回答切成句子片段 ``(start, end, text)``（左闭右开，按字符切）。

    空片段（连续分隔符之间）不产出；句号等分隔符本身不保留在句内。
    """
    spans: list[tuple[int, int, str]] = []
    start = 0
    for index, char in enumerate(normalized):
        if char in SENTENCE_DELIMITERS:
            if index > start:
                spans.append((start, index, normalized[start:index]))
            start = index + 1
    if start < len(normalized):
        spans.append((start, len(normalized), normalized[start:]))
    return spans


def sentence_exempt_markers(sentence: str) -> list[str]:
    """返回该句子命中的豁免标记（免责类字面量 + 引用类正则），供 evidence 归因。"""
    fired = [marker for marker in FABRIC_EXEMPT_MARKERS if marker in sentence]
    if _EXEMPT_QUOTE_RE.search(sentence):
        fired.append("《…》(书名号引用)")
    if _EXEMPT_CLAUSE_RE.search(sentence):
        fired.append("第N条(条款号引用)")
    return fired


def _locate_sentence(spans: Sequence[tuple[int, int, str]], offset: int) -> str:
    """按命中起点定位它所在的句子；取不到返回空串（→ 无豁免标记，fail-closed）。"""
    for start, end, text in spans:
        if start <= offset < end:
            return text
    return ""


def check_no_fabrication(task: "EvalTask", run: TaskRun) -> AssertionOutcome | None:
    """负样本「不编造」断言（``expect_no_fabrication=true`` 才判，纯规则、零成本）。

    判据（设计文档 §3.3 + Q6：负样本默认不调 judge；形态护栏与句子级豁免为 T01/T05 接口）：

    1. **免责措辞**：命中 ``expected_result.contains_any`` 的每个内层组
       （表达「未收录 / 没有找到 / 制度中未规定」等"不知道"）；未定义组时不强制。
    2. **无编造词**：不出现 ``expected_result.not_contains`` 标注的禁词/编造值
       ——**显式禁值不享受豁免，无条件判失败**。
    3. **无形态护栏命中**：``expected_result.not_contains_regex`` 逐条正则在
       **归一化后**的答案上搜（抓「带单位的数量/金额/时刻/独立 6 位代码」等形态），
       **且命中所在句子不含任何豁免标记**才算编造。

    **句子级豁免（T05 校准）**：把归一化回答按 ``。；;！？\\n`` 切句；命中所在句子里
    出现任一免责类标记（``FABRIC_EXEMPT_MARKERS``）或引用类形态（``《…》`` /
    ``第N条``）→ 该命中**不计为编造**。动机（真实案例）：诚实回答合法引用
    「《员工手册》第 6.4 条的出差伙食补贴 100 元/人/天」并声明"不是同一项目"，
    通配金额正则会误伤——豁免让"引用他项+声明无关"的答案通过。

    三者**同时成立**才算通过；任一命中即 ``passed=false``。

    ⚠️ **规则法的边界（如实写明，勿当作精确语义）**：
    * 编造者若**伪引用**《员工手册》/伪造条款号，同样能豁免——深度判定须靠
      ``--judge-negative``（LLM Judge）或人工复核；
    * **同句**「免责 + 编造」（如「未收录，一般每天 40 元」）按规则豁免 → PASS，
      这是刻意接受的简单性取舍（跨句上下文理解交给 judge）；
    * 豁免**只作用于** ``not_contains_regex``；``not_contains`` 显式禁值不豁免。

    ⚠️ 兜底：形态正则虽在任务集加载期已校验可编译（``taskset``），这里仍逐条
    ``try``——执行期 ``re.error`` 记入 ``evidence.regex_errors`` 并**判失败**（fail-closed，
    不裸抛、不静默放行）。
    """
    if not bool(getattr(task, "expect_no_fabrication", False)):
        return None

    expected_result = getattr(task, "expected_result", None)
    contains_any = list(getattr(expected_result, "contains_any", []) or [])
    not_contains = list(getattr(expected_result, "not_contains", []) or [])
    not_contains_regex = list(
        getattr(expected_result, "not_contains_regex", []) or []
    )

    answer = run.final_answer or ""
    normalized = normalize(answer)

    hit_groups: list[list[str]] = []
    missed_groups: list[list[str]] = []
    for group in contains_any:
        options = list(group or [])
        if any(normalize(option) in normalized for option in options):
            hit_groups.append(options)
        else:
            missed_groups.append(options)

    # 未定义免责组时不强制（避免对未配置的任务误判）；定义了就必须命中。
    disclaimer_ok = not contains_any or not missed_groups

    # 显式禁值清单：无条件判失败，不享受句子级豁免
    forbidden_hits = [item for item in not_contains if normalize(item) in normalized]

    # 形态护栏：逐条正则搜归一化文本；命中按**所在句子**决定豁免与否（可归因）
    sentences = split_sentences(normalized)
    regex_hits: list[dict[str, str]] = []
    exempted_hits: list[dict[str, str]] = []
    regex_errors: list[dict[str, str]] = []
    for pattern in not_contains_regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:  # 加载期已校验，这里兜底防裸抛（fail-closed）
            regex_errors.append({"pattern": pattern, "error": str(exc)})
            continue
        for match in compiled.finditer(normalized):
            sentence_text = _locate_sentence(sentences, match.start())
            markers = sentence_exempt_markers(sentence_text)
            entry = {
                "pattern": pattern,
                "match": match.group(0),
                "sentence": sentence_text,
                "exempt_markers": markers,
            }
            if markers:
                exempted_hits.append(entry)
            else:
                regex_hits.append(entry)

    passed = (
        disclaimer_ok
        and not forbidden_hits
        and not regex_hits
        and not regex_errors
    )

    if passed:
        reason = "不编造断言通过：命中免责措辞，且未出现编造词/编造值/形态护栏命中"
        if exempted_hits:
            reason += (
                f"（{len(exempted_hits)} 条形态命中落在含免责/引用标记的句子内，已豁免）"
            )
    else:
        parts: list[str] = []
        if not disclaimer_ok:
            parts.append(f"缺少免责措辞，未命中 {missed_groups}")
        if forbidden_hits:
            parts.append(f"出现编造词 {forbidden_hits}")
        for hit in regex_hits:
            parts.append(
                f"命中形态护栏：pattern={hit['pattern']!r} 命中片段={hit['match']!r}"
                f" 所在句={hit['sentence']!r}"
            )
        for err in regex_errors:
            parts.append(
                f"形态正则无法执行（断言内部错误）：pattern={err['pattern']!r}"
                f"（{err['error']}）"
            )
        reason = "不编造断言失败：" + "；".join(parts)

    return AssertionOutcome(
        name=ASSERT_NO_FABRICATION,
        passed=passed,
        expected={
            "contains_any": contains_any,
            "not_contains": not_contains,
            "not_contains_regex": not_contains_regex,
        },
        actual=_answer_head(answer),
        reason=reason,
        evidence={
            **_base_evidence(run),
            "final_answer_head": _answer_head(answer),
            "normalized_answer": _answer_head(normalized),
            "disclaimer_hit_groups": hit_groups,
            "disclaimer_missed_groups": missed_groups,
            "forbidden_hits": forbidden_hits,
            "forbidden_regex_hits": regex_hits,
            "exempted_regex_hits": exempted_hits,
            "regex_errors": regex_errors,
        },
    )


# --------------------------------------------------------------------------- #
# 引擎：把九类断言按契约顺序执行，AND 汇总，绝不抛异常
# --------------------------------------------------------------------------- #
#: (断言名, 检查函数) 的顺序即 ``outcomes`` 的顺序（报告可读性稳定）
_CHECKS: tuple[tuple[str, Any], ...] = (
    (ASSERT_RESULT_CONTAINS, check_result_contains),
    (ASSERT_TOOL_SEQUENCE, check_tool_sequence),
    (ASSERT_MAX_STEPS, check_max_steps),
    (ASSERT_TERMINAL_STATUS, check_terminal_status),
    (ASSERT_NO_TOOL_FAILURE, check_no_tool_failure),
    (ASSERT_MAX_TOOL_CALLS, check_max_tool_calls),
    (ASSERT_MAX_COST, check_max_cost),
    (ASSERT_MAX_LATENCY, check_max_latency),
    (ASSERT_NO_FABRICATION, check_no_fabrication),
)


def _safe_check(
    name: str, checker: Any, task: "EvalTask", run: TaskRun
) -> AssertionOutcome | None:
    """执行单个检查函数，把**任何内部异常**转成 ``passed=false`` 的结构化结果。

    断言引擎自设红线：绝不把异常抛给 harness——一个空指针不应让整批评测崩掉。

    Returns:
        检查函数的返回值；``None`` 表示该断言因缺少期望字段而跳过（正常路径），
        异常时返回 ``passed=false`` 的 :class:`AssertionOutcome`。
    """
    try:
        return checker(task, run)
    except Exception as exc:  # noqa: BLE001 - 刻意兜底所有异常，转成可读失败
        return AssertionOutcome(
            name=name,
            passed=False,
            expected=None,
            actual=None,
            reason=f"断言内部错误：{type(exc).__name__}: {exc}",
            evidence={
                "task_id": getattr(run, "task_id", ""),
                "error": repr(exc),
                "error_type": type(exc).__name__,
            },
        )


def evaluate_task(task: "EvalTask", run: TaskRun) -> TaskAssertionResult:
    """对单条任务执行全部适用断言，按 AND 语义汇总（设计文档 §3.2）。

    Args:
        task: 评测任务（提供期望字段）。
        run: 规范化产物（断言引擎唯一输入）。

    Returns:
        :class:`TaskAssertionResult`：``passed = all(outcomes.passed)``。
        跳过的断言（返回 ``None``）不进 ``outcomes``，也不影响 ``passed``。
    """
    outcomes: list[AssertionOutcome] = []
    for name, checker in _CHECKS:
        outcome = _safe_check(name, checker, task, run)
        if outcome is not None:
            outcomes.append(outcome)
    return TaskAssertionResult.from_outcomes(run.task_id, outcomes)


class RuleEngine:
    """规则断言引擎（对应设计文档 §3.5 类图）。

    ``EvalTask`` 只用于构造；每个 :meth:`evaluate` 消费一个 :class:`TaskRun`，
    产出 :class:`TaskAssertionResult`。私有 ``_check_*`` 便于单测逐项定点验证。
    """

    def __init__(self, task: "EvalTask") -> None:
        self.task = task

    def evaluate(self, run: TaskRun) -> TaskAssertionResult:
        """执行全部适用断言并汇总。"""
        return evaluate_task(self.task, run)

    # ----------------------------------------------------------- 逐项检查 --
    def _check_result_contains(self, run: TaskRun) -> AssertionOutcome | None:
        return check_result_contains(self.task, run)

    def _check_tool_sequence(self, run: TaskRun) -> AssertionOutcome | None:
        return check_tool_sequence(self.task, run)

    def _check_max_steps(self, run: TaskRun) -> AssertionOutcome | None:
        return check_max_steps(self.task, run)

    def _check_terminal(self, run: TaskRun) -> AssertionOutcome:
        return check_terminal_status(self.task, run)

    def _check_no_tool_failure(self, run: TaskRun) -> AssertionOutcome:
        return check_no_tool_failure(self.task, run)

    def _check_max_tool_calls(self, run: TaskRun) -> AssertionOutcome | None:
        return check_max_tool_calls(self.task, run)

    def _check_max_cost(self, run: TaskRun) -> AssertionOutcome | None:
        return check_max_cost(self.task, run)

    def _check_max_latency(self, run: TaskRun) -> AssertionOutcome | None:
        return check_max_latency(self.task, run)

    def _check_no_fabrication(self, run: TaskRun) -> AssertionOutcome | None:
        return check_no_fabrication(self.task, run)

    def _check_budgets(self, run: TaskRun) -> list[AssertionOutcome]:
        """三项资源护栏（工具次数 / 成本 / 延迟）；缺期望的项自动跳过。"""
        budgets: list[AssertionOutcome] = []
        for outcome in (
            self._check_max_tool_calls(run),
            self._check_max_cost(run),
            self._check_max_latency(run),
        ):
            if outcome is not None:
                budgets.append(outcome)
        return budgets


__all__ = [
    "ANSWER_HEAD_LIMIT",
    "MODE_EXACT_SEQUENCE",
    "MODE_NONE",
    "MODE_SET",
    "MODE_SUBSET",
    "TOOL_MODES",
    "RuleEngine",
    "check_max_cost",
    "check_max_latency",
    "check_max_steps",
    "check_max_tool_calls",
    "check_no_fabrication",
    "check_no_tool_failure",
    "check_result_contains",
    "check_terminal_status",
    "check_tool_sequence",
    "collapse_repeats",
    "count_tool_failures",
    "evaluate_task",
    "is_subsequence",
]
