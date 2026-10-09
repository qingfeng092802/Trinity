"""错误分类与批处理快速失败。

背景（真事）：跑全量 50 条评测时，DeepSeek 返回 **402 Insufficient Balance**，
结果被误诊成「模型不支持 response_format=json_object」，于是每条样本
先降级重试 3 次、再纯文本重试 3 次，整批白跑 18 分钟，日志还把人往错方向带。

这里把两条规则钉死：

1. **重试只按状态码细分**：401/402/403/404/400/422 重试无用；429 与 5xx 才重试。
2. **json 模式降级只在真的与 json 有关时触发**：``invalid_request_error`` 这种
   到处都在用的通用 code 不能当标志。
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import pytest

from config import PROJECT_ROOT
from core.llm import adapter as adapter_module
from core.llm.adapter import (
    LLMNotRetryableError,
    _looks_like_json_mode_rejection,
    _raise_if_non_retryable,
    is_non_retryable,
    is_retryable,
    status_is_retryable,
)
from evaluation import batch as batch_module
from evaluation.batch import BatchRun, run_batch
from evaluation.dataset import EvalItem
from evaluation.trace import TraceStore

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


class FakeStatusError(Exception):
    """模拟 openai.APIStatusError：带 status_code 的 HTTP 错误。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Error code: {status} - {message}")
        self.status_code = status


def make_items(count: int) -> list[EvalItem]:
    """造几条评测样本。"""
    return [
        EvalItem(id=f"t{index:03d}", task=f"任务 {index}", expected_criteria=["标准"])
        for index in range(1, count + 1)
    ]


class TestRetryClassification:
    """哪些错误值得重试。判定分两个维度：异常类型 + 状态码，两边都要对。"""

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
    def test_client_status_is_not_retryable(self, status: int) -> None:
        assert status_is_retryable(status) is False
        assert is_non_retryable(FakeStatusError(status, "boom")) is True

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_rate_limit_and_server_status_is_retryable(self, status: int) -> None:
        assert status_is_retryable(status) is True

    def test_no_status_means_connection_level(self) -> None:
        assert status_is_retryable(None) is True

    def test_known_transient_type_with_retryable_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """两个维度都满足才会重试。这里把假异常登记进已知瞬时类型。"""
        monkeypatch.setattr(adapter_module, "RETRYABLE_ERRORS", (FakeStatusError,))
        assert is_retryable(FakeStatusError(503, "unavailable")) is True
        assert is_retryable(FakeStatusError(429, "rate limit")) is True
        assert is_retryable(FakeStatusError(402, "Insufficient Balance")) is False

    def test_connection_error_is_retryable(self) -> None:
        assert is_retryable(ConnectionError("连接被重置")) is True

    def test_unknown_exception_type_is_never_retried(self) -> None:
        # 不认识自己的异常类型就不该重试，否则会把代码 bug 当网络问题反复跑
        assert is_retryable(ValueError("不是网络问题")) is False

    def test_insufficient_balance_is_translated(self) -> None:
        with pytest.raises(LLMNotRetryableError, match="余额不足"):
            _raise_if_non_retryable(FakeStatusError(402, "Insufficient Balance"))

    def test_server_error_is_not_translated(self) -> None:
        # 5xx 属于可重试，不该被翻译成「重试无用」
        _raise_if_non_retryable(FakeStatusError(503, "service unavailable"))


class TestJsonModeDowngrade:
    """json 模式降级的判定条件。"""

    def test_402_insufficient_balance_is_not_json_rejection(self) -> None:
        """回归：402 的响应体里 code 就是 invalid_request_error，不能被当成 json 模式问题。"""
        exc = FakeStatusError(
            402,
            "{'error': {'message': 'Insufficient Balance', 'type': 'unknown_error', "
            "'code': 'invalid_request_error'}}",
        )
        assert _looks_like_json_mode_rejection(exc) is False

    def test_401_auth_error_is_not_json_rejection(self) -> None:
        assert _looks_like_json_mode_rejection(FakeStatusError(401, "Invalid API key")) is False

    def test_real_json_rejection_is_detected(self) -> None:
        exc = FakeStatusError(400, "response_format type json_object is not supported")
        assert _looks_like_json_mode_rejection(exc) is True

    def test_bad_request_without_json_hint_is_not_rejection(self) -> None:
        assert _looks_like_json_mode_rejection(FakeStatusError(400, "model not found")) is False


class TestBatchFailFast:
    """批处理遇到「重试无用」的错误要立刻停。"""

    @staticmethod
    def _patch_runner(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
        """让编排器一跑就抛指定异常。"""

        class ExplodingRunner:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def run(self, task: str) -> dict[str, Any]:
                raise exc

        monkeypatch.setattr(batch_module, "WorkflowRunner", ExplodingRunner)

    @staticmethod
    def _patch_failed_state(monkeypatch: pytest.MonkeyPatch, comment: str) -> None:
        """让编排器返回一个失败状态（模拟节点层把异常吞掉后的样子）。"""

        class FailedStateRunner:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def run(self, task: str) -> dict[str, Any]:
                return {
                    "task": task,
                    "task_id": "task-stub",
                    "status": "failed",
                    "iteration": 0,
                    "review_comment": comment,
                    "final_answer": "",
                }

        monkeypatch.setattr(batch_module, "WorkflowRunner", FailedStateRunner)

    def _store(self) -> TraceStore:
        return TraceStore(TEST_SCRATCH_ROOT / f"batch-{uuid4().hex[:10]}.db")

    def test_aborts_on_insufficient_balance_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_runner(monkeypatch, LLMNotRetryableError("账户余额不足：去控制台充值"))
        store = self._store()
        try:
            result = run_batch(make_items(5), run_judge=False, use_tools=False, store=store)
        finally:
            store.close()

        assert len(result.outcomes) == 1  # 只跑了第一条就停
        assert result.outcomes[0].status == "failed"
        assert "余额不足" in result.abort_reason

    def test_aborts_when_node_swallowed_error_into_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真实路径：节点层把异常转成失败状态，异常根本不会传到批处理。

        所以必须能从状态文本里认出「重试无用」，否则整批会挨个白跑一遍。
        """
        comment = (
            "planner 异常：LLMNotRetryableError: LLM 调用失败（HTTP 402）："
            "账户余额不足：去供应商控制台充值后再跑（这不是代码问题，重试无用）"
        )
        self._patch_failed_state(monkeypatch, comment)
        store = self._store()
        try:
            result = run_batch(make_items(5), run_judge=False, use_tools=False, store=store)
        finally:
            store.close()

        assert len(result.outcomes) == 1
        assert "余额不足" in result.abort_reason

    def test_keeps_going_on_ordinary_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """普通异常（如单条任务崩了）不能触发整批中止。"""
        self._patch_runner(monkeypatch, RuntimeError("这条任务自己崩了"))
        store = self._store()
        try:
            result = run_batch(make_items(3), run_judge=False, use_tools=False, store=store)
        finally:
            store.close()

        assert len(result.outcomes) == 3  # 全跑完
        assert result.abort_reason == ""
        assert all(item.status == "failed" for item in result.outcomes)

    def test_ordinary_failed_state_does_not_abort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_failed_state(monkeypatch, "reviewer 异常：SchemaError: 输出不符合契约")
        store = self._store()
        try:
            result = run_batch(make_items(3), run_judge=False, use_tools=False, store=store)
        finally:
            store.close()

        assert len(result.outcomes) == 3
        assert result.abort_reason == ""

    def test_batch_run_defaults(self) -> None:
        empty = BatchRun()
        assert empty.count == 0
        assert empty.abort_reason == ""


class TestBatchProgressCallback:
    """进度回调的契约（CLI 与 UI 都依赖它）。"""

    def test_callback_receives_each_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[int, str, str | None]] = []

        class ExplodingRunner:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def run(self, task: str) -> dict[str, Any]:
                raise RuntimeError("崩")

        monkeypatch.setattr(batch_module, "WorkflowRunner", ExplodingRunner)
        store = TraceStore(TEST_SCRATCH_ROOT / f"batch-{uuid4().hex[:10]}.db")
        try:
            run_batch(
                make_items(2),
                run_judge=False,
                use_tools=False,
                store=store,
                on_item=lambda index, item, outcome, error: seen.append(
                    (index, item.id, outcome.status if outcome else None)
                ),
            )
        finally:
            store.close()

        assert seen == [(1, "t001", "failed"), (2, "t002", "failed")]

    def test_callback_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self_started = time.perf_counter()

        class ExplodingRunner:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def run(self, task: str) -> dict[str, Any]:
                raise RuntimeError("崩")

        monkeypatch.setattr(batch_module, "WorkflowRunner", ExplodingRunner)
        store = TraceStore(TEST_SCRATCH_ROOT / f"batch-{uuid4().hex[:10]}.db")
        try:
            result = run_batch(make_items(1), run_judge=False, use_tools=False, store=store)
        finally:
            store.close()

        assert result.count == 1
        assert time.perf_counter() - self_started < 10
