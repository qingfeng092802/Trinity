"""阶段 2 单测：参数校验、沙箱围栏、超时终止、指数退避重试、HITL 门禁。

重点覆盖三类「必须拦住」的情况——参数写错、路径越界、执行超时，
以及两类「必须如实上报」的情况——重试成功、重试耗尽。
"""

from __future__ import annotations

import json
import time
import typing
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import pytest
from pydantic import Field

from config import PROJECT_ROOT, get_settings
from core.llm.adapter import Usage
from core.tools.builtin import code_exec as code_exec_module
from core.tools.builtin import extract as extract_module
from core.tools.builtin import file_io as file_io_module
from core.tools.builtin import load_builtin_tools
from core.tools.builtin import web_search as web_search_module
from core.tools.registry import ToolRegistry, ToolSpec
from core.tools.sandbox import (
    SANDBOX_DIR_NAME,
    SandboxPathError,
    SandboxTimeout,
    resolve_workspace_path,
    retry_call,
    run_python,
    workspace_root,
)
from core.tools.validators import (
    ToolRegistrationError,
    ToolValidationError,
    build_params_model,
    json_schema_for,
    validate_args,
)

#: 对外暴露的 3 个工具（字母序，``registry.names()`` 的 sorted 保证）
BUILTIN_NAMES = [
    "calculator",
    "code_exec",
    "knowledge_search",
]

#: 收敛下线、但仍保留源码的 3 个工具（见 core.tools.builtin.RETIRED_BUILTIN_REGISTRARS）
RETIRED_NAMES = ["extract", "file_io", "web_search"]


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
#: 测试自己的临时工作区根目录（项目内，不碰系统临时目录）
TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """给沙箱一个项目内的临时工作区。

    刻意不用 pytest 的 ``tmp_path``：pytest 每个会话都会回收系统临时目录里的
    历史目录（``pytest-of-*`` / ``garbage-*``），本机沙箱对递归删除是
    fail-closed 的，一旦拦截整个测试进程会被打断。

    也**刻意不做 teardown 清理**：``shutil.rmtree`` 同样会触发拦截。这些目录
    在 ``data/.test-scratch`` 下，已加入 .gitignore，需要时手动删即可。
    """
    root = TEST_SCRATCH_ROOT / uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes").mkdir(exist_ok=True)
    monkeypatch.setattr(get_settings(), "workspace_dir", root, raising=False)
    yield root


#: 这两枚夹具要的是"工具真跑"，不是"门禁真开"。
#: 改前写的是 ``enable_hitl=False``（当时那等于高危直接放行）；Q5-01 把语义改成
#: "有没有门"与"要不要问人"分开之后，False 等于**一律拒绝**，于是这批用例
#: 必须换成"开 HITL + 一个总是批准的回调"，才能继续测沙箱本身的行为。
_APPROVE: Any = lambda name, args: True  # noqa: E731 - 夹具参数，不值得一个函数定义


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    """装好 **3 个对外工具** 的独立注册表（带总是批准的审批回调，便于直接调用）。"""
    return load_builtin_tools(
        ToolRegistry(settings=get_settings(), enable_hitl=True, hitl_approver=_APPROVE)
    )


@pytest.fixture
def retired_registry(workspace: Path) -> ToolRegistry:
    """额外装配已收敛下线的 3 个工具（file_io / web_search / extract）。

    这些工具的源码仍保留在 ``core/tools/builtin/``，只是**不再进默认注册表**。
    它们的回归测试因此必须自己显式注册，而不是依赖 ``load_builtin_tools``。
    """
    from core.tools.builtin import RETIRED_BUILTIN_REGISTRARS

    target = load_builtin_tools(
        ToolRegistry(settings=get_settings(), enable_hitl=True, hitl_approver=_APPROVE)
    )
    for registrar in RETIRED_BUILTIN_REGISTRARS:
        registrar(target)
    return target


@pytest.fixture
def hitl_registry(workspace: Path) -> Callable[[Any], ToolRegistry]:
    """按需构造带 HITL 的注册表。"""

    def _build(approver: Any = None) -> ToolRegistry:
        return load_builtin_tools(
            ToolRegistry(settings=get_settings(), enable_hitl=True, hitl_approver=approver)
        )

    return _build


class FakeAdapter:
    """只实现 extract 用到的那几个接口。"""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []
        self.settings = get_settings()
        self.last_usage = Usage(model="fake", token_in=1, token_out=1)

    def invoke_json(self, messages: Any, schema: Any, model: str | None = None, **_: Any) -> Any:
        self.calls.append({"schema": schema, "model": model})
        return self.payload


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #
class TestValidators:
    """函数签名 → Pydantic 模型 → JSON Schema。"""

    @staticmethod
    def _sample(
        query: Annotated[str, Field(description="查询词")],
        limit: Annotated[int, Field(ge=1, le=10, description="条数")] = 3,
    ) -> str:
        """示例工具。"""
        return f"{query}-{limit}"

    def test_schema_carries_descriptions_and_required(self) -> None:
        model = build_params_model("sample", self._sample)
        schema = json_schema_for(model)
        assert schema["properties"]["query"]["description"] == "查询词"
        assert schema["required"] == ["query"]
        assert "title" not in schema
        assert "title" not in schema["properties"]["query"]

    def test_missing_annotation_is_rejected(self) -> None:
        def bad(value) -> str:  # type: ignore[no-untyped-def]
            return str(value)

        with pytest.raises(ToolRegistrationError, match="缺少类型注解"):
            build_params_model("bad", bad)

    def test_varargs_is_rejected(self) -> None:
        def bad(*args: str) -> str:
            return "".join(args)

        with pytest.raises(ToolRegistrationError, match=r"\*args"):
            build_params_model("bad", bad)

    def test_validate_fills_defaults(self) -> None:
        model = build_params_model("sample", self._sample)
        merged = validate_args(model, {"query": "x"}, tool_name="sample")
        assert merged == {"query": "x", "limit": 3}

    def test_validate_rejects_unknown_field(self) -> None:
        model = build_params_model("sample", self._sample)
        with pytest.raises(ToolValidationError) as excinfo:
            validate_args(model, {"query": "x", "bogus": 1}, tool_name="sample")
        assert "bogus" in str(excinfo.value)

    def test_validate_reports_field_level_errors(self) -> None:
        model = build_params_model("sample", self._sample)
        with pytest.raises(ToolValidationError) as excinfo:
            validate_args(model, {"limit": 99}, tool_name="sample")
        # 缺失的必填字段和越界字段都要报出来，模型才知道一次改几处
        assert {item["field"] for item in excinfo.value.errors} == {"query", "limit"}
        assert "参数校验失败" in str(excinfo.value)

    def test_validate_rejects_non_object(self) -> None:
        model = build_params_model("sample", self._sample)
        with pytest.raises(ToolValidationError, match="必须是 JSON 对象"):
            validate_args(model, ["x"], tool_name="sample")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
class TestRegistry:
    """注册、查询与提示词渲染。"""

    def test_builtin_tools_are_registered(self, registry: ToolRegistry) -> None:
        assert registry.names() == BUILTIN_NAMES

    def test_describe_lists_signature_and_danger(self, registry: ToolRegistry) -> None:
        text = registry.describe()
        assert "- calculator(expression: string)" in text
        assert "code_exec" in text and "（高危，需人工确认）" in text
        assert len(text.splitlines()) == len(BUILTIN_NAMES)

    def test_duplicate_name_is_rejected(self, registry: ToolRegistry) -> None:
        with pytest.raises(ToolRegistrationError, match="工具名重复"):
            registry.register(lambda: "x", name="calculator")

    def test_get_unknown_tool_raises(self, registry: ToolRegistry) -> None:
        with pytest.raises(KeyError, match="未注册的工具"):
            registry.get("nope")

    def test_call_unknown_tool_returns_failed_record(self, registry: ToolRegistry) -> None:
        record = registry.call("nope", {})
        assert record["status"] == "failed"
        assert "未注册的工具" in record["result"]

    def test_spec_dump_excludes_func(self, registry: ToolRegistry) -> None:
        spec: ToolSpec = registry.get("calculator")
        dumped = spec.model_dump()
        assert "func" not in dumped
        assert dumped["parameters"]["properties"]["expression"]["type"] == "string"

    def test_defaults_come_from_settings(self, registry: ToolRegistry) -> None:
        settings = get_settings()
        assert registry.get("code_exec").retry <= settings.tool_retry
        assert registry.get("calculator").timeout == 5  # 工具自己声明了更紧的预算

    def test_load_builtin_tools_is_idempotent(self, registry: ToolRegistry) -> None:
        assert load_builtin_tools(registry).names() == BUILTIN_NAMES


# --------------------------------------------------------------------------- #
# 参数错误拦截（走完整 call 链路）
# --------------------------------------------------------------------------- #
class TestArgumentRejection:
    """参数不对时，工具不该被执行，且错误要能回灌给模型。"""

    def test_missing_required_argument(self, registry: ToolRegistry) -> None:
        record = registry.call("calculator", {})
        assert record["status"] == "failed"
        assert "参数校验失败" in record["result"]
        assert "expression" in record["result"]

    def test_wrong_type_argument(self, registry: ToolRegistry) -> None:
        record = registry.call("calculator", {"expression": 123})
        assert record["status"] == "failed"
        assert "参数校验失败" in record["result"]

    def test_unknown_argument_is_rejected(self, registry: ToolRegistry) -> None:
        record = registry.call("calculator", {"expression": "1+1", "verbose": True})
        assert record["status"] == "failed"
        assert "verbose" in record["result"]

    def test_sandbox_path_escape_is_rejected(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("file_io", {"path": "../outside.txt"})
        assert record["status"] == "failed"
        assert "路径被沙箱拒绝" in record["result"]


# --------------------------------------------------------------------------- #
# calculator
# --------------------------------------------------------------------------- #
class TestCalculator:
    """白名单 AST 求值：算得对，也拦得住。"""

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("(3+5)*2", "16"),
            ("2**10", "1024"),
            ("sqrt(2)", "1.414213562"),
            ("max(3, 7, 5) + min(1, 0)", "7"),
            ("-3 * (2 + 1) % 4", "3"),
            ("log(100, 10)", "2"),
        ],
    )
    def test_valid_expressions(
        self,
        registry: ToolRegistry,
        expression: str,
        expected: str,
    ) -> None:
        record = registry.call("calculator", {"expression": expression})
        assert record["status"] == "success"
        assert expected in record["result"]

    @pytest.mark.parametrize(
        "expression",
        [
            "__import__('os').system('echo hi')",
            "open('x')",
            "1 +",
            "foo(1)",
            "1/0",
            "9**9**9",
            "'a' * 3",
            "lambda: 1",
        ],
    )
    def test_rejected_expressions(self, registry: ToolRegistry, expression: str) -> None:
        record = registry.call("calculator", {"expression": expression})
        assert record["status"] == "failed"
        assert record["result"].strip()


# --------------------------------------------------------------------------- #
# 沙箱路径围栏
# --------------------------------------------------------------------------- #
class TestSandboxPaths:
    """工作区是唯一可读写位置。"""

    def test_parent_escape_is_blocked(self, workspace: Path) -> None:
        with pytest.raises(SandboxPathError, match="路径越界"):
            resolve_workspace_path("../sneaky.txt")

    def test_absolute_outside_is_blocked(self, workspace: Path) -> None:
        with pytest.raises(SandboxPathError, match="路径越界"):
            resolve_workspace_path(str(workspace.parent / "other.txt"))

    def test_nested_relative_path_is_allowed(self, workspace: Path) -> None:
        target = resolve_workspace_path("notes/todo.md", for_write=True)
        assert target == workspace / "notes" / "todo.md"
        assert target.parent.is_dir()

    def test_absolute_inside_is_allowed(self, workspace: Path) -> None:
        assert resolve_workspace_path(workspace / "notes") == workspace / "notes"

    def test_empty_path_is_blocked(self, workspace: Path) -> None:
        with pytest.raises(SandboxPathError, match="不能为空"):
            resolve_workspace_path("   ")

    def test_missing_file_is_reported(self, workspace: Path) -> None:
        with pytest.raises(SandboxPathError, match="文件不存在"):
            resolve_workspace_path("nope.txt", must_exist=True)


# --------------------------------------------------------------------------- #
# 超时终止
# --------------------------------------------------------------------------- #
class TestTimeout:
    """三种超时都要真的终止，并且状态记成 timeout。"""

    def test_registry_deadline_marks_timeout(self, registry: ToolRegistry) -> None:
        def slow() -> str:
            time.sleep(2)
            return "too late"

        registry.register(slow, name="slow_tool", timeout=1, retry=0)
        started = time.perf_counter()
        record = registry.call("slow_tool", {})
        elapsed = time.perf_counter() - started
        assert record["status"] == "timeout"
        assert "未返回" in record["result"]
        assert elapsed < 1.8

    def test_python_subprocess_is_killed(self, workspace: Path) -> None:
        started = time.perf_counter()
        result = run_python("import time\ntime.sleep(30)\nprint('never')", timeout=1, cwd=workspace)
        elapsed = time.perf_counter() - started
        assert result.timed_out is True
        assert elapsed < 10
        assert "never" not in result.stdout

    def test_sandbox_script_is_cleaned_up(self, workspace: Path) -> None:
        run_python("print('hi')", timeout=10, cwd=workspace)
        leftovers = list((workspace / SANDBOX_DIR_NAME).glob("*.py"))
        assert leftovers == []

    def test_code_exec_reports_timeout(
        self,
        registry: ToolRegistry,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(code_exec_module, "EXEC_TIMEOUT_SECONDS", 1)
        started = time.perf_counter()
        record = registry.call("code_exec", {"code": "import time\ntime.sleep(30)"})
        assert record["status"] == "timeout"
        assert time.perf_counter() - started < 10

    def test_code_exec_captures_stdout(self, registry: ToolRegistry) -> None:
        record = registry.call("code_exec", {"code": "print(sum(range(101)))"})
        assert record["status"] == "success"
        assert "5050" in record["result"]

    def test_code_exec_nonzero_exit_is_failed(self, registry: ToolRegistry) -> None:
        """BUG-01：脚本自己抛异常不是一次「成功」的调用。

        修之前 ``brief()`` 被当普通返回值交出去 —— status=success 配一整段 Traceback，
        下游（含前端工具卡徽章）只能靠嗅 "exit_code=" 这行文本反推真实结果。
        """
        record = registry.call("code_exec", {"code": "raise ValueError('boom')"})
        assert record["status"] == "failed"
        assert "exit_code=1" in record["result"]
        assert "ValueError: boom" in record["result"]
        # 走专用 except 分支：出参保持沙箱 brief 原文，不被冠上异常类名前缀
        assert not record["result"].startswith("SandboxFailed")

    def test_code_exec_zero_exit_stays_success(self, registry: ToolRegistry) -> None:
        """反向钉住：显式 exit(0) 不能被新判定误伤成失败。"""
        record = registry.call("code_exec", {"code": "import sys\nsys.exit(0)"})
        assert record["status"] == "success"
        assert "exit_code=0" in record["result"]


# --------------------------------------------------------------------------- #
# 重试
# --------------------------------------------------------------------------- #
class TestRetry:
    """指数退避重试的三种结局。"""

    def test_succeeds_after_two_failures(self, registry: ToolRegistry) -> None:
        calls: list[int] = []

        def flaky() -> str:
            calls.append(1)
            if len(calls) <= 2:
                raise ValueError("临时故障")
            return "ok"

        registry.register(flaky, name="flaky", timeout=5, retry=2)
        record = registry.call("flaky", {})
        assert record["status"] == "success"
        assert record["result"].startswith("ok")
        assert "重试后成功" in record["result"]
        assert len(calls) == 3

    def test_retry_exhausted_returns_failed(self, registry: ToolRegistry) -> None:
        calls: list[int] = []

        def always_broken() -> str:
            calls.append(1)
            raise RuntimeError("就是不灵")

        registry.register(always_broken, name="broken", timeout=5, retry=2)
        record = registry.call("broken", {})
        assert record["status"] == "failed"
        assert "RuntimeError" in record["result"]
        assert len(calls) == 3

    def test_timeout_is_not_retried(self, registry: ToolRegistry) -> None:
        calls: list[int] = []

        def always_slow() -> str:
            calls.append(1)
            time.sleep(2)
            return "x"

        registry.register(always_slow, name="always_slow", timeout=1, retry=3)
        record = registry.call("always_slow", {})
        assert record["status"] == "timeout"
        assert len(calls) == 1  # 超时不重试，避免把墙钟时间再赔一遍

    def test_retry_call_returns_attempt_count(self) -> None:
        state = {"n": 0}

        def flaky() -> str:
            state["n"] += 1
            if state["n"] == 1:
                raise ValueError("x")
            return "done"

        value, attempts = retry_call(flaky, retry=1, base_delay=0.01)
        assert (value, attempts) == ("done", 2)

    def test_retry_call_reraises_timeout(self) -> None:
        def boom() -> str:
            raise SandboxTimeout("超时了")

        with pytest.raises(SandboxTimeout):
            retry_call(boom, retry=3, base_delay=0.01)


# --------------------------------------------------------------------------- #
# HITL 门禁
# --------------------------------------------------------------------------- #
class TestHitl:
    """高危工具在开启 HITL 后必须过人工这道关，默认 fail-closed。"""

    def test_high_danger_denied_when_hitl_disabled(self, workspace: Path) -> None:
        """★ Q5-01 回归闸：``enable_hitl=False``（**默认值**）+ 高危 ⇒ 拒绝且代码没跑。

        改前这一条是放行的：判定写成 ``if not (self.enable_hitl and danger == "high"): return ""``，
        于是 ``.env`` 里一行 ``ENABLE_HITL=false`` 把 fail-closed 翻成 fail-open，
        编排链路里模型自己选的 ``code_exec`` 不经任何审批直接真跑。
        HTTP 单工具通道那条（``test_api_tools.py::test_high_risk_denied_when_hitl_disabled``）
        早就修了，本条补上编排通道 —— 从今天起两条通道是同一个答案。
        失败即说明有人把"有没有门"又挂回 ``enable_hitl`` 上，可以整段删掉这层兼容。
        """
        registry = load_builtin_tools(
            ToolRegistry(settings=get_settings(), enable_hitl=False)
        )
        record = registry.call("code_exec", {"code": "print('SENTINEL-CODE-RAN')"})
        assert record["status"] == "failed"
        assert "fail-closed" in record["result"]
        assert "SENTINEL-CODE-RAN" not in record["result"], "拒绝分支里代码绝不能真跑起来"

    def test_no_approver_means_denied(self, hitl_registry: Any) -> None:
        registry = hitl_registry(None)
        record = registry.call("code_exec", {"code": "print(1)"})
        assert record["status"] == "failed"
        assert "fail-closed" in record["result"]

    def test_denied_by_approver(self, hitl_registry: Any) -> None:
        seen: list[tuple[str, dict[str, Any]]] = []

        def approver(name: str, args: dict[str, Any]) -> bool:
            seen.append((name, args))
            return False

        registry = hitl_registry(approver)
        record = registry.call("code_exec", {"code": "print(1)"})
        assert record["status"] == "failed"
        assert "人工拒绝" in record["result"]
        assert seen and seen[0][0] == "code_exec"

    def test_approved_by_approver(self, hitl_registry: Any) -> None:
        registry = hitl_registry(lambda name, args: True)
        record = registry.call("code_exec", {"code": "print('ok')"})
        assert record["status"] == "success"
        assert "ok" in record["result"]

    def test_low_danger_is_not_gated(self, hitl_registry: Any) -> None:
        registry = hitl_registry(None)
        record = registry.call("calculator", {"expression": "1+1"})
        assert record["status"] == "success"

    def test_approver_exception_fails_closed(self, hitl_registry: Any) -> None:
        def broken(name: str, args: dict[str, Any]) -> bool:
            raise RuntimeError("审批系统挂了")

        registry = hitl_registry(broken)
        record = registry.call("code_exec", {"code": "print(1)"})
        assert record["status"] == "failed"
        assert "按拒绝处理" in record["result"]


# --------------------------------------------------------------------------- #
# file_io
# --------------------------------------------------------------------------- #
class TestFileIO:
    """读写与列目录。"""

    def test_write_then_read_roundtrip(self, retired_registry: ToolRegistry, workspace: Path) -> None:
        written = retired_registry.call(
            "file_io",
            {"path": "notes/a.md", "mode": "write", "content": "第一行"},
        )
        assert written["status"] == "success"
        assert (workspace / "notes" / "a.md").read_text(encoding="utf-8") == "第一行"

        read = retired_registry.call("file_io", {"path": "notes/a.md", "mode": "read"})
        assert read["status"] == "success"
        assert "第一行" in read["result"]

    def test_append_keeps_existing_content(self, retired_registry: ToolRegistry) -> None:
        retired_registry.call("file_io", {"path": "b.txt", "mode": "write", "content": "A"})
        retired_registry.call("file_io", {"path": "b.txt", "mode": "append", "content": "B"})
        read = retired_registry.call("file_io", {"path": "b.txt", "mode": "read"})
        assert read["result"] == "AB"

    def test_list_directory(self, retired_registry: ToolRegistry) -> None:
        retired_registry.call("file_io", {"path": "notes/x.md", "mode": "write", "content": "x"})
        record = retired_registry.call("file_io", {"path": "notes", "mode": "list"})
        assert record["status"] == "success"
        assert "x.md" in record["result"]

    def test_write_without_content_fails(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("file_io", {"path": "c.txt", "mode": "write"})
        assert record["status"] == "failed"
        assert "必须提供 content" in record["result"]

    def test_read_missing_file_fails(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("file_io", {"path": "ghost.txt", "mode": "read"})
        assert record["status"] == "failed"
        assert "不存在" in record["result"]


# --------------------------------------------------------------------------- #
# web_search
# --------------------------------------------------------------------------- #
class TestWebSearch:
    """搜索后端可插拔，且失败必须如实上报。"""

    def test_injected_backend(
        self,
        retired_registry: ToolRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hits = [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]
        monkeypatch.setattr(web_search_module, "_BACKEND", lambda query, limit: hits * limit)
        record = retired_registry.call("web_search", {"query": "储能", "num_results": 2})
        assert record["status"] == "success"
        assert "标题" in record["result"]
        assert record["result"].count("https://example.com") == 2

    def test_backend_failure_is_reported(
        self, retired_registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(query: str, limit: int) -> list[dict[str, str]]:
            raise web_search_module.SearchError("搜索服务不可用")

        monkeypatch.setattr(web_search_module, "_BACKEND", broken)
        record = retired_registry.call("web_search", {"query": "x"})
        assert record["status"] == "failed"
        assert "搜索服务不可用" in record["result"]

    def test_backend_can_be_disabled_by_env(
        self, retired_registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(web_search_module, "_BACKEND", None)
        monkeypatch.setenv(web_search_module.BACKEND_ENV, "none")
        record = retired_registry.call("web_search", {"query": "x"})
        assert record["status"] == "failed"
        assert "关闭" in record["result"]

    def test_empty_query_is_rejected(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("web_search", {"query": "   "})
        assert record["status"] == "failed"


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
class TestExtract:
    """LLM 抽取工具：schema 校验 + 结果格式化。"""

    def test_success(self, retired_registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeAdapter({"company": "云启智能"})
        monkeypatch.setattr(extract_module, "get_adapter", lambda: fake)
        record = retired_registry.call(
            "extract",
            {"text": "深圳市云启智能科技有限公司", "schema": '{"type":"object"}'},
        )
        assert record["status"] == "success"
        assert json.loads(record["result"])["company"] == "云启智能"
        assert fake.calls and fake.calls[0]["schema"] == {"type": "object"}

    def test_invalid_schema_json_is_rejected(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("extract", {"text": "x", "schema": "{不是 JSON"})
        assert record["status"] == "failed"
        assert "不是合法 JSON" in record["result"]

    def test_non_object_schema_is_rejected(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("extract", {"text": "x", "schema": '["a"]'})
        assert record["status"] == "failed"
        assert "必须是一个 JSON 对象" in record["result"]

    def test_empty_text_is_rejected(self, retired_registry: ToolRegistry) -> None:
        record = retired_registry.call("extract", {"text": "  ", "schema": '{"type":"object"}'})
        assert record["status"] == "failed"


# --------------------------------------------------------------------------- #
# 工作区
# --------------------------------------------------------------------------- #
class TestWorkspace:
    """工作区目录与内置工具函数。"""

    def test_workspace_root_is_created(self, workspace: Path) -> None:
        assert workspace_root() == workspace
        assert workspace.is_dir()

    def test_file_io_module_exposes_modes(self) -> None:
        assert set(typing.get_args(file_io_module.FileMode)) == {"read", "write", "append", "list"}

    def test_unregistered_tool_via_default_registry(self) -> None:
        from core.tools.registry import call_tool

        assert call_tool("does_not_exist", {})["status"] == "failed"
