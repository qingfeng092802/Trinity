"""code_exec：在受限子进程中执行 Python 代码。

这是整个工具集里最危险的一个（``danger_level="high"``），因为代码会**真实运行**。
安全边界由三层构成，但**三层的强度不一样**，别当成"围栏里随便跑"：

1. 子进程隔离 + 硬超时（:func:`core.tools.sandbox.run_python`，超时直接 kill）；
2. **环境变量白名单**（:data:`core.tools.sandbox.SANDBOX_ENV_ALLOWLIST`）：父进程带着
   ``LLM_API_KEY`` 之类的密钥，子进程**拿不到** —— 否则"print 一下环境"就是一条把密钥
   带走的通道，而触发它只需要一次提示注入；
3. 注册时 ``retry=0`` —— 有副作用的代码**绝不自动重跑**。

⚠️ **"工作目录固定在沙箱工作区"只约束相对路径的落点，不约束读**。代码里写
``open("../../.env")`` 或 ``Path("C:/Windows/win.ini")`` 一样打得开 —— 子进程与父进程
同一个用户身份。默认 cwd 是 ``data/workspace`` 只是为了让"写文件"有个落点，
不是读围栏。真要围住文件系统访问得上 Job Object / AppContainer（未实现，见
``core/tools/sandbox.py`` 模块 docstring 的"已知边界"）。同理，出网**没有**任何限制代码，
描述里那句"不要用它做网络请求"是**约定**，不是**强制**。

注意：``timeout=0`` 表示不在注册表层再加看门线程，超时由子进程自己管；
否则外层线程会先放弃等待，反而丢掉子进程已经产生的输出。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec
from core.tools.sandbox import SandboxFailed, SandboxTimeout, run_python, workspace_root

#: 子进程执行预算（秒），超时后强制终止
EXEC_TIMEOUT_SECONDS = 30


def code_exec(
    code: Annotated[
        str,
        Field(description="要执行的完整 Python 代码；用 print 输出结果"),
    ],
) -> str:
    """在受限子进程中执行 Python 代码并返回标准输出（会真实运行代码，请谨慎使用）。"""
    result = run_python(
        code,
        timeout=EXEC_TIMEOUT_SECONDS,
        cwd=workspace_root(),
    )
    if result.timed_out:
        # 超时要如实升级成 SandboxTimeout，让 ToolCallRecord.status 记成 timeout，
        # 而不是把「执行超时」当成一次成功的工具调用
        raise SandboxTimeout(result.brief())
    if result.returncode != 0:
        # 同理：脚本自己抛异常 / sys.exit(1) 不是一次成功的调用。以前只把 brief()
        # 当返回值交出去，于是 stderr 里整段 Traceback 被贴上 status=success，
        # 下游（含前端）只能靠嗅 "exit_code=" 这行文本反推真实结果。
        raise SandboxFailed(result.brief())
    return result.brief()


def register(registry: ToolRegistry) -> ToolSpec:
    """把 code_exec 注册进给定注册表。"""
    return registry.register(
        code_exec,
        name="code_exec",
        description=(
            f"在沙箱子进程里运行 Python 代码（最多 {EXEC_TIMEOUT_SECONDS} 秒）并取回 stdout。"
            "适合需要精确计算、字符串/数据处理、文件批处理验证的场景；"
            "不要用它做网络请求或安装依赖"
        ),
        danger_level="high",
        timeout=0,  # 超时交给子进程自己管，避免外层放弃等待而丢掉输出
        retry=0,  # 有副作用，绝不自动重跑
    )


__all__ = ["EXEC_TIMEOUT_SECONDS", "code_exec", "register"]
