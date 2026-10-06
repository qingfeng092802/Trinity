"""条件边路由：reviewer 之后决定「继续重做」还是「结束」。

判定优先级（先命中先返回）：

1. 已进入终态（``done`` / ``failed`` / ``aborted``）→ 结束。
   这一条同时兜住了「节点抛异常被收敛成 failed」的情况，避免失败后还继续循环。
2. reviewer 判定通过 → 结束。
3. 迭代次数已达 ``max_iterations`` → 结束（强制收口，保证一定停机）。
4. 否则回退 executor 重做。
"""

from __future__ import annotations

from typing import Final, Literal

from core.workflow.state import TERMINAL_STATUSES, AgentState, WorkflowConfig

#: 条件边的路由取值
Route = Literal["executor", "end"]

#: 回退重做
CONTINUE_NODE: Final[Route] = "executor"
#: 收口结束（映射到 LangGraph 的 END）
STOP_NODE: Final[Route] = "end"


def should_continue(state: AgentState, config: WorkflowConfig | None = None) -> Route:
    """返回下一步走向：``"executor"`` 或 ``"end"``。

    Args:
        state: 当前状态。
        config: 编排参数；不传则取全局 ``Settings`` 推导出的默认值
            （图编排里会把 ``ctx.config`` 绑进来，保证与节点用的是同一份配置）。
    """
    if state.get("status") in TERMINAL_STATUSES:
        return STOP_NODE
    if state.get("review_result"):
        return STOP_NODE
    limit = (config or WorkflowConfig.from_settings()).max_iterations
    if int(state.get("iteration", 0)) >= limit:
        return STOP_NODE
    return CONTINUE_NODE


# 这里原来还有一个 ``route_reason(state, config)``（把上面那条判分链翻译成一句人话），
# 2026-10-02 删掉：它自述的读者是"demo / 轨迹回放"，而 Streamlit 演示页与 ``web/``
# 已在 09-27 删除（a58e563），现存的 ``/trace`` 回放读的是 ``task_events`` 表里的
# 字段，全仓没有任何生产调用点。留着真正的代价不是行数，而是它**镜像重抄**了
# :func:`should_continue` 的四条判定（批 1 **Q2-05** 记的就是这条）：改一处忘改另一处，
# 屏幕上那句"为什么回退"就会解释一个并没有发生的决策，而且不会有任何用例变红
# —— 原先唯一读它的那条断言（test_workflow_state.py）验的正是这句文案本身。
__all__ = ["CONTINUE_NODE", "STOP_NODE", "Route", "should_continue"]
