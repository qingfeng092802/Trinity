"""阶段 2 工具层的「无 pytest」冒烟验证。

为什么需要它：本机沙箱对递归删除是 fail-closed 的，而 pytest 会话会回收系统临时目录
里的历史 ``pytest-of-*`` 目录，因此 pytest 在这台机器上会被直接拦下。本脚本用
**直接执行**覆盖同一批关键路径，作为 pytest 之外的替代验证手段。

规范来源仍然是测试套件：``tests/unit/test_tools.py``（40+ 用例，覆盖同样的行为），
本脚本只是「跑不起来时的手动版」，两者断言口径保持一致。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_tools.py

只写 ``data/.test-scratch/ws``（已 gitignore），**不做任何删除动作**。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402 - 必须在补 sys.path 之后导入
from core.agent.base import ToolInvoker  # noqa: E402
from core.llm.adapter import Usage  # noqa: E402
from core.tools.builtin import code_exec as code_exec_module  # noqa: E402
from core.tools.builtin import extract as extract_module  # noqa: E402
from core.tools.builtin import load_builtin_tools  # noqa: E402
from core.tools.builtin import web_search as web_search_module  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402
from core.tools.sandbox import run_python, workspace_root  # noqa: E402

WORKSPACE = PROJECT_ROOT / "data" / ".test-scratch" / "ws"
get_settings().workspace_dir = WORKSPACE
WORKSPACE.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """记录一条断言结果。"""
    RESULTS.append((name, bool(ok), detail))


def build_registry(*, hitl: bool = False, approver: Any = None) -> ToolRegistry:
    """装好 5 个内置工具的注册表。"""
    return load_builtin_tools(
        ToolRegistry(settings=get_settings(), enable_hitl=hitl, hitl_approver=approver)
    )


class FakeAdapter:
    """extract 用的假适配器（不联网）。"""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.settings = get_settings()
        self.last_usage = Usage(model="fake")

    def invoke_json(self, messages: Any, schema: Any, model: str | None = None, **_: Any) -> Any:
        return self.payload


def section(title: str) -> None:
    """打印分节标题。"""
    print(f"\n== {title} ==")


# --------------------------------------------------------------------------- #
def main() -> int:
    """跑完全部冒烟检查，返回退出码。"""
    section("注册与清单")
    reg = build_registry()
    check(
        "注册表：5 个内置工具齐全",
        reg.names() == ["calculator", "code_exec", "extract", "file_io", "web_search"],
        ", ".join(reg.names()),
    )
    described = reg.describe()
    check(
        "注册表：清单带签名与危险级别",
        "- calculator(expression: string)" in described and "（高危，需人工确认）" in described,
    )
    check("注册表：未注册工具返回 failed", reg.call("nope", {})["status"] == "failed")

    section("参数校验")
    record = reg.call("calculator", {})
    check("参数：缺必填被拦", record["status"] == "failed" and "参数校验失败" in record["result"])
    record = reg.call("calculator", {"expression": "1+1", "verbose": True})
    check("参数：多余字段被拦", record["status"] == "failed" and "verbose" in record["result"])
    check("参数：类型不符被拦", reg.call("calculator", {"expression": 123})["status"] == "failed")

    section("沙箱路径围栏")
    record = reg.call("file_io", {"path": "../outside.txt"})
    check(
        "沙箱：../ 越界被拒",
        record["status"] == "failed" and "路径被沙箱拒绝" in record["result"],
    )
    record = reg.call("file_io", {"path": str(Path.home() / "host.txt")})
    check("沙箱：外部绝对路径被拒", record["status"] == "failed")
    record = reg.call("file_io", {"path": "notes/a.md", "mode": "write", "content": "第一行"})
    check(
        "沙箱：区内写入成功",
        record["status"] == "success" and (WORKSPACE / "notes" / "a.md").is_file(),
    )
    record = reg.call("file_io", {"path": "notes/a.md", "mode": "read"})
    check("沙箱：区内读取回环", record["status"] == "success" and record["result"] == "第一行")

    section("超时终止")

    def slow_tool() -> str:
        time.sleep(2)
        return "too late"

    reg.register(slow_tool, name="slow_tool", timeout=1, retry=0)
    started = time.perf_counter()
    record = reg.call("slow_tool", {})
    elapsed = time.perf_counter() - started
    check("超时：看门线程拦住并记 timeout", record["status"] == "timeout", f"{elapsed:.2f}s")
    check("超时：调用方及时返回（<1.8s）", elapsed < 1.8, f"{elapsed:.2f}s")

    started = time.perf_counter()
    proc = run_python("import time\ntime.sleep(30)\nprint('never')", timeout=1, cwd=WORKSPACE)
    elapsed = time.perf_counter() - started
    check("超时：子进程被 kill", proc.timed_out and "never" not in proc.stdout, f"{elapsed:.2f}s")
    check("超时：沙箱脚本已自清理", list((WORKSPACE / ".sandbox").glob("*.py")) == [])

    code_exec_module.EXEC_TIMEOUT_SECONDS = 1
    started = time.perf_counter()
    record = reg.call("code_exec", {"code": "import time\ntime.sleep(30)"})
    check(
        "超时：code_exec 端到端记 timeout",
        record["status"] == "timeout",
        f"{time.perf_counter() - started:.2f}s",
    )
    code_exec_module.EXEC_TIMEOUT_SECONDS = 30
    record = reg.call("code_exec", {"code": "print(sum(range(101)))"})
    check(
        "code_exec：正常执行取回 stdout",
        record["status"] == "success" and "5050" in record["result"],
    )

    section("重试")
    flaky_calls: list[int] = []

    def flaky() -> str:
        flaky_calls.append(1)
        if len(flaky_calls) <= 2:
            raise ValueError("临时故障")
        return "ok"

    reg.register(flaky, name="flaky", timeout=5, retry=2)
    record = reg.call("flaky", {})
    check(
        "重试：失败两次后成功",
        record["status"] == "success" and "重试后成功" in record["result"],
        f"调用 {len(flaky_calls)} 次",
    )

    broken_calls: list[int] = []

    def always_broken() -> str:
        broken_calls.append(1)
        raise RuntimeError("就是不灵")

    reg.register(always_broken, name="broken", timeout=5, retry=2)
    record = reg.call("broken", {})
    check(
        "重试：耗尽后记 failed",
        record["status"] == "failed" and "RuntimeError" in record["result"],
        f"调用 {len(broken_calls)} 次",
    )

    slow_calls: list[int] = []

    def always_slow() -> str:
        slow_calls.append(1)
        time.sleep(2)
        return "x"

    reg.register(always_slow, name="always_slow", timeout=1, retry=3)
    record = reg.call("always_slow", {})
    check(
        "重试：超时不重试",
        record["status"] == "timeout" and len(slow_calls) == 1,
        f"调用 {len(slow_calls)} 次",
    )

    section("HITL 门禁")
    denied = build_registry(hitl=True).call("code_exec", {"code": "print(1)"})
    check(
        "HITL：无审批回调 → fail-closed",
        denied["status"] == "failed" and "fail-closed" in denied["result"],
    )
    seen: list[str] = []

    def reject(name: str, args: dict[str, Any]) -> bool:
        seen.append(name)
        return False

    denied = build_registry(hitl=True, approver=reject).call("code_exec", {"code": "print(1)"})
    check("HITL：人工拒绝", denied["status"] == "failed" and "人工拒绝" in denied["result"])
    allowed = build_registry(hitl=True, approver=lambda name, args: True).call(
        "code_exec", {"code": "print('ok')"}
    )
    check("HITL：人工放行后正常执行", allowed["status"] == "success" and "ok" in allowed["result"])

    def boom(name: str, args: dict[str, Any]) -> bool:
        raise RuntimeError("审批系统挂了")

    failed = build_registry(hitl=True, approver=boom).call("code_exec", {"code": "print(1)"})
    check(
        "HITL：审批异常也 fail-closed",
        failed["status"] == "failed" and "按拒绝处理" in failed["result"],
    )
    check(
        "HITL：低危工具不受门禁影响",
        build_registry(hitl=True).call("calculator", {"expression": "1+1"})["status"] == "success",
    )

    section("calculator")
    for expression, expected in [
        ("(3+5)*2", "16"),
        ("2**10", "1024"),
        ("sqrt(2)", "1.414213562"),
        ("max(3, 7, 5) + min(1, 0)", "7"),
        ("-3 * (2 + 1) % 4", "3"),
        ("log(100, 10)", "2"),
    ]:
        out = reg.call("calculator", {"expression": expression})
        check(
            f"calculator：{expression} = {expected}",
            out["status"] == "success" and expected in out["result"],
            out["result"][:40],
        )
    for expression in [
        "__import__('os').system('echo hi')",
        "open('x')",
        "1 +",
        "foo(1)",
        "1/0",
        "9**9**9",
        "'a' * 3",
        "lambda: 1",
    ]:
        out = reg.call("calculator", {"expression": expression})
        check(f"calculator：拒绝 {expression[:26]}", out["status"] == "failed", out["result"][:60])

    section("web_search（注入后端，不联网）")
    hits = [{"title": "标题", "url": "https://example.com", "snippet": "摘要"}]
    web_search_module._BACKEND = lambda query, limit: hits * limit
    out = reg.call("web_search", {"query": "储能", "num_results": 2})
    check(
        "web_search：注入后端返回结果",
        out["status"] == "success" and out["result"].count("https://example.com") == 2,
    )

    def broken_search(query: str, limit: int) -> list[dict[str, str]]:
        raise web_search_module.SearchError("搜索服务不可用")

    web_search_module._BACKEND = broken_search
    out = reg.call("web_search", {"query": "x"})
    check(
        "web_search：后端不可用如实报错",
        out["status"] == "failed" and "搜索服务不可用" in out["result"],
    )
    web_search_module._BACKEND = None

    section("extract（假适配器）")
    extract_module.get_adapter = lambda: FakeAdapter({"company": "云启智能"})  # type: ignore[assignment]
    out = reg.call("extract", {"text": "深圳市云启智能科技有限公司", "schema": '{"type":"object"}'})
    check(
        "extract：抽取成功",
        out["status"] == "success" and json.loads(out["result"])["company"] == "云启智能",
    )
    out = reg.call("extract", {"text": "x", "schema": "{不是 JSON"})
    check(
        "extract：schema 非法被拦",
        out["status"] == "failed" and "不是合法 JSON" in out["result"],
    )

    section("与编排层对接")
    check("协议：ToolRegistry 满足 ToolInvoker", isinstance(reg, ToolInvoker))
    check("协议：workspace_root 指向临时工作区", workspace_root() == WORKSPACE)

    section("汇总")
    failures = [(name, detail) for name, ok, detail in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        suffix = f"  | {detail}" if detail and not ok else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")
    print("-" * 72)
    passed = len(RESULTS) - len(failures)
    print(f"合计 {len(RESULTS)} 项，通过 {passed} 项，失败 {len(failures)} 项")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
