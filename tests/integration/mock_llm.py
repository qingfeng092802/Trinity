"""确定性 Mock LLM：让集成测试不触网、不消耗 token。

实现方式是继承 :class:`LLMAdapter` 并只替换 ``invoke_json``：节点实际走的是
``invoke_model`` → ``invoke_json`` 这条真实链路，所以测出来的是真实调用路径，
只是最后一跳被换成了查表。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, SecretStr

from config import Settings
from core.llm.adapter import LLMAdapter, Usage, to_messages
from core.workflow.state import ToolCallRecord

#: 响应函数：``(schema, 提示词全文) -> 预置 payload``
Responder = Callable[[Any, str], Any]


class MockLLMAdapter(LLMAdapter):
    """按 schema 派发预置响应的假适配器。

    Args:
        responder: 响应函数。节点用到的 schema 有 ``PLAN_SCHEMA``（dict）、
            ``ExecutorDecision``、``ReviewVerdict``（均为 Pydantic 模型类）。
    """

    #: 每次调用记进 ``llm_call`` 事件的假成本（元）。
    #: **做成类属性而不是字面量**，是因为预算闸门用例要同时满足两件互相拉扯的事：
    #: 上限必须 ≥ 服务端声明的 ``max_cost_cny`` 下限（否则 422，闸门根本没机会跑），
    #: 又必须在一两个节点内被越过（否则用例会一直等到超时）。写死成本就只能靠
    #: 一个恰好落在夹缝里的魔数 —— 下限一动它就静默失效。
    COST_PER_CALL: float = 0.000123

    def __init__(self, responder: Responder) -> None:
        super().__init__(settings=Settings(llm_api_key=SecretStr("mock-key")))
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def _client(self, model: str, temperature: float | None = None) -> Any:
        """任何真实客户端创建都说明测试写错了，直接炸掉而不是偷偷联网。"""
        raise AssertionError("MockLLMAdapter 不应创建真实客户端")

    def invoke_json(
        self,
        messages: Any,
        schema: Any,
        model: str | None = None,
        *,
        max_attempts: int = 2,
        on_text: Any = None,
    ) -> Any:
        # on_text 是流式回调用；桩走"查表"路径没有增量可推，接住即忽略
        text = "\n".join(str(message.content) for message in to_messages(messages))
        self.calls.append({"schema": schema, "model": model, "text": text})
        self.last_usage = Usage(
            model=model or "mock",
            token_in=42,
            token_out=17,
            cost=self.COST_PER_CALL,
            duration_ms=1,
        )
        payload = self.responder(schema, text)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            # 与真实适配器保持同一套校验口径：Pydantic 模型走 model_validate
            return schema.model_validate(payload).model_dump()
        return payload

    def calls_for(self, schema: Any) -> list[dict[str, Any]]:
        """按 schema 过滤调用记录，便于断言「某角色被调用了几次」。"""
        return [call for call in self.calls if call["schema"] is schema]


class StubToolInvoker:
    """满足 ``ToolInvoker`` 协议的最小工具层，用于验证 executor 的工具分支（阶段 2 前的替身）。"""

    def __init__(self, result: str = "工具返回：42") -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def describe(self) -> str:
        return "- calculator(expression: str)：计算一个算术表达式"

    def call(self, name: str, args: dict[str, Any]) -> ToolCallRecord:
        self.calls.append((name, args))
        return ToolCallRecord(
            name=name,
            args=args,
            result=self.result,
            status="success",
            duration_ms=3,
        )


__all__ = ["MockLLMAdapter", "Responder", "StubToolInvoker"]
