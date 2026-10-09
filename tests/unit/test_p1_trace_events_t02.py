"""P1 阶段二（T02 + 缺陷 A/B）单测：工具白名单语义、终态判定、事件埋点。

本文件只覆盖**本次改造新增的行为**，与 T01 交付的 ``test_task_events.py``
（表结构 / event_seq / NULL 语义那批）刻意分开，避免同文件多处编辑冲突。

覆盖：

* 缺陷 A：``use_tools`` 三态语义 + ``enabled_tools`` 精确白名单
  （``api.runner.resolve_tool_names`` / ``ToolRegistry.restrict_to``）；
* 缺陷 B：``api.runner.decide_terminal_status`` 的单一出口判定；
* T02 埋点：``QueueItem`` 三态字段、终态事件携带 error_code、
  ``EventRecord`` 落盘字段映射（K7）。
"""

from __future__ import annotations

import pytest

from api.queue import CancelToken, QueueItem
from api.runner import (
    ALL_TOOL_NAMES,
    SAFE_TOOL_SUBSET,
    decide_terminal_status,
    resolve_tool_names,
)
from api.schemas import KNOWN_TOOL_NAMES, TaskSubmitRequest
from core.tools.builtin import load_builtin_tools
from core.tools.registry import ToolRegistry


def _item(*, use_tools: bool | None = None, enabled_tools: list[str] | None = None) -> QueueItem:
    """构造一个最小 QueueItem（工具字段可覆盖）。"""
    return QueueItem(
        task_id="task-test",
        task="任务",
        max_iterations=3,
        review_threshold=7,
        use_tools=use_tools,
        run_judge=False,
        difficulty=None,
        submitted_at=0.0,
        cancel=CancelToken(task_id="task-test"),
        enabled_tools=enabled_tools,
    )


class TestResolveToolNames:
    """缺陷 A：``use_tools`` 三态 + ``enabled_tools`` 白名单。"""

    def test_none_means_full_set(self) -> None:
        """不传 ``use_tools``（None）→ 全量装配（向后兼容）。"""
        assert resolve_tool_names(_item(use_tools=None)) == ALL_TOOL_NAMES

    def test_true_means_full_set(self) -> None:
        """``use_tools=True`` → 全量装配。"""
        assert resolve_tool_names(_item(use_tools=True)) == ALL_TOOL_NAMES

    def test_false_means_safe_subset_not_empty(self) -> None:
        """★ 缺陷 A 核心：``use_tools=False`` 不再「零工具」，而是安全子集。"""
        names = resolve_tool_names(_item(use_tools=False))
        assert names == SAFE_TOOL_SUBSET
        assert "knowledge_search" in names, "用户要的是关掉高危工具，不是关掉知识库检索"
        assert "calculator" in names
        assert "code_exec" not in names, "高危工具必须排除"
        # file_io / web_search / extract 已随工具面收敛下线，不在安全子集内
        for retired in ("file_io", "web_search", "extract"):
            assert retired not in names

    def test_enabled_tools_wins_over_use_tools(self) -> None:
        """``enabled_tools`` 非空 → 最高优先级，精确装配。"""
        names = resolve_tool_names(_item(use_tools=True, enabled_tools=["knowledge_search"]))
        assert names == ("knowledge_search",)

    def test_enabled_tools_orders_by_builtin(self) -> None:
        """``enabled_tools`` 顺序归一为内置顺序（提示词展示稳定）。"""
        names = resolve_tool_names(
            _item(enabled_tools=["knowledge_search", "calculator", "code_exec"])
        )
        assert names == ("calculator", "knowledge_search", "code_exec")

    def test_unknown_names_filtered(self) -> None:
        """未知名被过滤（合法名保留），不抛。"""
        names = resolve_tool_names(_item(enabled_tools=["nope", "calculator"]))
        assert names == ("calculator",)


class TestToolRegistryRestrict:
    """``ToolRegistry.restrict_to`` 裁剪白名单。"""

    def test_restrict_keeps_only_allowed(self) -> None:
        registry = load_builtin_tools(ToolRegistry())
        registry.restrict_to({"knowledge_search", "calculator"})
        assert registry.names() == ["calculator", "knowledge_search"]

    def test_restrict_hides_from_describe(self) -> None:
        registry = load_builtin_tools(ToolRegistry())
        registry.restrict_to({"knowledge_search"})
        described = registry.describe()
        assert "knowledge_search" in described
        assert "code_exec" not in described
        assert "file_io" not in described

    def test_restrict_is_idempotent_intersection(self) -> None:
        registry = load_builtin_tools(ToolRegistry())
        registry.restrict_to({"calculator", "knowledge_search", "code_exec"})
        registry.restrict_to({"code_exec"})
        assert registry.names() == ["code_exec"]


class TestDecideTerminalStatus:
    """缺陷 B：单一出口的终态判定。"""

    def test_answer_with_running_status_is_done(self) -> None:
        """有答案 + 正常收敛 → done。"""
        assert decide_terminal_status({"status": "running", "final_answer": "答案"}) == (
            "done",
            None,
            None,
        )

    def test_aborted_with_answer_is_done(self) -> None:
        """★ 缺陷 B 核心：aborted 带完整答案 → 修正为 done（不能语义矛盾）。"""
        status, error_code, error_message = decide_terminal_status(
            {"status": "aborted", "final_answer": "907 字的完整答案"}
        )
        assert status == "done"
        assert error_code is None
        assert error_message is None

    def test_aborted_without_answer_stays_aborted(self) -> None:
        """无答案 → aborted（真·没交付）。"""
        assert decide_terminal_status({"status": "aborted", "final_answer": "   "}) == (
            "aborted",
            None,
            None,
        )

    def test_failed_carries_error_code(self) -> None:
        """failed 必须带 error_code / error_message（不允许 NULL）。"""
        status, code, message = decide_terminal_status(
            {"status": "failed", "review_comment": "planner 异常：PlanError: 计划为空"}
        )
        assert status == "failed"
        assert code == "node_failed"
        assert message

    def test_canceled_carries_code(self) -> None:
        """canceled 有 error_code（可查询），但语义是「取消」不是「失败」。"""
        status, code, _ = decide_terminal_status({"status": "canceled"})
        assert status == "canceled"
        assert code == "canceled_by_user"

    def test_done_status_preserved(self) -> None:
        assert decide_terminal_status({"status": "done", "final_answer": "x"})[0] == "done"


class TestSubmitRequestTools:
    """``TaskSubmitRequest`` 的工具字段校验（缺陷 A 的 API 契约层）。"""

    def test_default_is_none(self) -> None:
        request = TaskSubmitRequest(task="hi")
        assert request.use_tools is None
        assert request.enabled_tools is None

    def test_use_tools_false_preserved(self) -> None:
        assert TaskSubmitRequest(task="hi", use_tools=False).use_tools is False

    def test_enabled_tools_dedup_keeps_order(self) -> None:
        request = TaskSubmitRequest(
            task="hi", enabled_tools=["knowledge_search", "calculator", "knowledge_search"]
        )
        assert request.enabled_tools == ["knowledge_search", "calculator"]

    def test_enabled_tools_unknown_rejected(self) -> None:
        with pytest.raises(ValueError):
            TaskSubmitRequest(task="hi", enabled_tools=["definitely_not_a_tool"])

    def test_enabled_tools_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            TaskSubmitRequest(task="hi", enabled_tools=[])


class TestKnownToolNamesAlignment:
    """``KNOWN_TOOL_NAMES`` 必须与内置注册集合一致（否则校验会与运行时脱节）。"""

    def test_matches_builtin_registry(self) -> None:
        registry = load_builtin_tools(ToolRegistry())
        assert set(registry.names()) == set(KNOWN_TOOL_NAMES)

    def test_safe_subset_is_subset_of_known(self) -> None:
        assert set(SAFE_TOOL_SUBSET) <= set(KNOWN_TOOL_NAMES)


__all__ = ["TestDecideTerminalStatus", "TestResolveToolNames"]
