"""阶段 1 的纯逻辑单测：状态契约、路由优先级、提示词变量完整性。"""

from __future__ import annotations

import pytest

from config import get_settings
from core.agent.base import (
    PromptNotFoundError,
    PromptRenderError,
    prompt_path,
    render_prompt,
)
from core.workflow.conditions import CONTINUE_NODE, STOP_NODE, should_continue
from core.workflow.state import (
    WorkflowConfig,
    draft_answer,
    format_results,
    initial_state,
    is_terminal,
    normalize_steps,
    numbered,
)

ROLES = ("planner", "executor", "reviewer", "judge")


class TestInitialState:
    """初始状态必须字段齐全，否则下游节点到处写 ``.get()`` 兜底会埋 bug。"""

    def test_all_contract_keys_present(self) -> None:
        state = initial_state("写一份周报", task_id="t-1")
        assert set(state) == {
            "task",
            "task_id",
            "plan",
            "current_step",
            "execution_results",
            "review_result",
            "review_score",
            "review_comment",
            "iteration",
            "messages",
            "final_answer",
            "status",
        }
        assert state["task_id"] == "t-1"
        assert state["status"] == "running"

    def test_task_id_is_generated_when_absent(self) -> None:
        assert initial_state("x")["task_id"].startswith("task-")

    def test_empty_task_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="task 不能为空"):
            initial_state("   ")


class TestNormalizeSteps:
    """planner 输出清洗：脏数据不能带进状态。"""

    def test_drops_blank_and_strips(self) -> None:
        assert normalize_steps(["  第一步  ", "", "   ", "第二步"]) == ["第一步", "第二步"]

    def test_truncates_to_five(self) -> None:
        assert len(normalize_steps([f"第{i}步" for i in range(9)])) == 5

    def test_handles_none(self) -> None:
        assert normalize_steps(None) == []


class TestHelpers:
    """渲染辅助函数。"""

    def test_numbered(self) -> None:
        assert numbered(["a", "b"]) == "1. a\n2. b"
        assert numbered([]) == "（无计划）"

    def test_format_results_includes_tool_calls(self) -> None:
        text = format_results(
            [
                {
                    "step_index": 0,
                    "subtask": "查资料",
                    "output": "查到了",
                    "status": "success",
                    "tool_calls": [
                        {
                            "name": "web_search",
                            "args": {"q": "x"},
                            "result": "3 条",
                            "status": "success",
                            "duration_ms": 12,
                        }
                    ],
                }
            ]
        )
        assert "第 1 步" in text and "web_search" in text and "12ms" in text

    def test_draft_answer_is_empty_without_results(self) -> None:
        assert draft_answer(None) == ""
        assert draft_answer([]) == ""


class TestRouting:
    """条件边优先级：终态 > 通过 > 迭代上限 > 重做。"""

    def test_terminal_status_always_stops(self) -> None:
        for status in ("done", "failed", "aborted"):
            assert should_continue({"status": status, "review_result": False}) == STOP_NODE

    def test_pass_stops(self) -> None:
        state = initial_state("t")
        state["review_result"] = True
        assert should_continue(state) == STOP_NODE

    def test_iteration_limit_stops(self) -> None:
        state = initial_state("t")
        state["iteration"] = 3
        state["review_result"] = False
        config = WorkflowConfig(max_iterations=3)
        assert should_continue(state, config) == STOP_NODE

    def test_failure_below_limit_loops_back(self) -> None:
        state = initial_state("t")
        state["iteration"] = 1
        state["review_score"] = 4
        config = WorkflowConfig(max_iterations=3)
        assert should_continue(state, config) == CONTINUE_NODE
        # 这里原来还有一句 ``assert "回退 executor 重做" in route_reason(state, config)``
        # （2026-10-02 删，理由见 ``core/workflow/conditions.py`` 末尾）：
        # ``route_reason`` 把 should_continue 的四条判定镜像重抄了一遍再翻成文案，
        # 那句断言读的是**重抄的那一份**，生产里没人调用它 —— 它红了也不代表
        # 路由错了，只代表文案变了。真正要钉的走向判定留在上一行。


class TestWorkflowConfig:
    """编排参数必须与全局 Settings 同源，避免两份默认值打架。"""

    def test_from_settings_mirrors_settings(self) -> None:
        settings = get_settings()
        config = WorkflowConfig.from_settings(settings)
        assert config.max_iterations == settings.max_iterations
        assert config.review_threshold == settings.review_threshold
        assert config.enable_hitl == settings.enable_hitl

    def test_is_terminal(self) -> None:
        state = initial_state("t")
        assert is_terminal(state) is False
        state["status"] = "aborted"
        assert is_terminal(state) is True


class TestPromptContract:
    """提示词文件与节点的变量约定必须对齐。

    提示词里写错一个 ``$var``，只有在真实调用时才会炸；这里用测试提前锁住。
    """

    def test_prompt_files_exist(self) -> None:
        for role in ROLES:
            assert prompt_path(role, "v1").is_file(), f"缺少提示词：{role}/v1"

    def test_missing_prompt_raises(self) -> None:
        # 用真实不存在的角色名：阶段 3 补上 judge.md 之后，judge 已经有了提示词
        with pytest.raises(PromptNotFoundError):
            render_prompt("no_such_role", "v1", task="x")

    def test_planner_prompt_renders(self) -> None:
        text = render_prompt("planner", "v1", task="把这句话拆开")
        assert "把这句话拆开" in text
        assert "$task" not in text

    def test_executor_prompt_renders(self) -> None:
        text = render_prompt(
            "executor",
            "v1",
            task="总任务",
            plan="1. 甲\n2. 乙",
            step_index=1,
            total_steps=2,
            subtask="甲",
            history="（无）",
            feedback="（首轮执行，暂无评审意见）",
            tool_section="当前没有接入任何工具",
        )
        assert "甲" in text
        assert "tool_name" in text
        # 渲染后不应再有未替换的占位符
        assert "$" not in text

    def test_reviewer_prompt_renders_and_declares_final_answer(self) -> None:
        text = render_prompt(
            "reviewer",
            "v1",
            task="总任务",
            plan="1. 甲",
            results="第 1 步 甲",
            draft="草稿",
            threshold=7,
            executed_steps=1,
            total_steps=1,
        )
        assert "`pass`" in text
        assert "`final_answer`" in text
        assert "7" in text

    def test_judge_prompt_renders_and_declares_fields(self) -> None:
        text = render_prompt(
            "judge",
            "v1",
            task="总任务",
            criteria="1. 标准一\n2. 标准二",
            execution="终态：done，迭代轮数：0",
            answer="交付内容",
            status="done",
        )
        assert "标准二" in text
        assert "交付内容" in text
        assert "`score`" in text and "`issues`" in text
        # grade 不在契约里：它由代码从分数推导，不该让模型自报
        assert "`grade`" not in text
        assert "$" not in text

    def test_render_reports_missing_variable(self) -> None:
        with pytest.raises(PromptRenderError, match="缺少变量"):
            render_prompt("judge", "v1", task="只有 task")
