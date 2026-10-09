"""工具执行沙箱：子进程隔离 + 超时终止 + 路径围栏 + 指数退避重试。

三层保护，各管一件事：

1. **路径围栏**（:func:`resolve_workspace_path`）：**工具自己的**文件读写都必须在
   ``settings.workspace_dir`` 内，``../`` 逃逸与指向外部的绝对路径一律拒绝。
2. **子进程 + 超时终止**（:func:`run_python`）：执行代码类工具时用独立进程，
   超时先 ``kill`` 再收集残留输出，保证调用方一定拿得到返回。
3. **看门线程**（:func:`run_with_deadline`）：给普通工具加一道墙钟上限。

⚠️ **围栏只管"工具暴露的入参"，不管"子进程里跑的代码"**。第 1 层拦的是
``file_io(path="../../etc/passwd")`` 这类**经过** :func:`resolve_workspace_path` 的访问；
``code_exec`` 起的子进程里，代码自己 ``open()`` 什么，本模块**拦不住** —— 子进程与父进程
同一个用户身份、同一个文件系统视野。 Windows 上要真正围住读得靠 AppContainer / Job Object
（见下方"已知边界"），那不是纯 Python 能补的洞。所以第 1 层能给的只有两件事：
①**环境变量白名单**（:data:`SANDBOX_ENV_ALLOWLIST`）—— 密钥不跟着进子进程；
②把这条边界写在这里，而不是写成"所有文件读写都在围栏内"（那是超卖）。

两个已知边界，写在这里避免误用：

* 子进程被 ``kill`` 的是**直接子进程**；如果被执行的代码自己又拉起了子进程，
  那些孙进程不保证被回收。真要强隔离得上容器。
* :func:`run_with_deadline` 用的是 daemon 线程，**Python 无法强杀线程**，它只能
  保证「调用方及时返回」，被放弃的那个线程仍会跑完。所以有副作用的工具要幂等，
  或者干脆用 :func:`run_python` 走子进程。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import uuid4

from config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: 子进程沙箱的脚本落盘目录名（在 workspace 内）
SANDBOX_DIR_NAME = ".sandbox"

#: Windows 下避免弹出控制台窗口
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

#: 子进程**允许继承**的环境变量名（按大写比较，Windows 上环境变量名大小写不敏感）。
#:
#: 为什么是白名单而不是"滤掉含 KEY/TOKEN/SECRET 的名字"：跑在这里的是**模型生成的代码**，
#: 一次提示注入就足够把环境打印出来。黑名单兜不住的那一类恰恰最贵 ——
#: 新密钥的名字不一定含这些词（``DB_URL`` 里带着口令、``*_API_BASE`` 露内网拓扑、
#: ``*_WEBHOOK`` 是一条现成的外发地址），而白名单默认拒绝一切新增。
#:
#: 每一项都是"子进程要能正常跑起来"的必需品，不是顺手多给的：
#:  - ``PATH`` / ``PATHEXT`` / ``COMSPEC``：``shutil.which``、代码里再起子进程；
#:  - ``SYSTEMROOT`` / ``WINDIR`` / ``SYSTEMDRIVE``：Windows 上缺了它，子进程里的
#:    ``socket`` / ``ssl`` 会直接报 ``OSError``（这是 Windows 的已知行为，不是洁癖）；
#:  - ``TEMP`` / ``TMP`` / ``TMPDIR`` 与 ``APPDATA`` / ``LOCALAPPDATA``：临时文件与缓存
#:    落点，缺了 pandas/matplotlib 会往只读位置写然后抛异常；
#:  - ``HOME`` / ``USERPROFILE`` / ``HOMEDRIVE`` / ``HOMEPATH``：``Path.home()``；
#:  - ``LANG`` / ``LC_ALL`` / ``TZ``：文本与时区口径。
#: 刻意**不给**的：``PYTHONPATH`` / ``PYTHONHOME``（会把解释器指回项目环境，等于给
#: 子进程一条 import 平台内部模块的路）、``VIRTUAL_ENV``、以及任何 ``LLM_*`` / ``API_*``。
#: ``PYTHONIOENCODING`` / ``PYTHONDONTWRITEBYTECODE`` 由 :func:`sandbox_env` 自己写死。
SANDBOX_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",
        "COMSPEC",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)


def sandbox_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """构造沙箱子进程的环境变量（**白名单**，见 :data:`SANDBOX_ENV_ALLOWLIST`）。

    Args:
        extra_env: 显式追加的变量。走这个参数进来的**不受白名单限制** —— 它是调用方
            主动写的，不是继承来的；``code_exec`` 这条模型可控的路径不传任何 extra_env。

    Returns:
        新字典；不修改 :data:`os.environ`。
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in SANDBOX_ENV_ALLOWLIST
    }
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    return env


class SandboxError(RuntimeError):
    """沙箱相关错误基类。"""


class SandboxTimeout(SandboxError):
    """工具/代码执行超时。"""


class SandboxPathError(SandboxError):
    """文件路径越出 workspace 围栏。"""


class SandboxFailed(SandboxError):
    """子进程**正常跑完但退出码非 0**（脚本自己抛异常、`sys.exit(1)`、命令失败）。

    为什么单独一个类而不是直接 ``raise SandboxError``：registry 对 ``SandboxTimeout``
    走的是 ``str(exc)`` 分支，出参里就是沙箱那几行原文；非零退出也该拿到同样的待遇。
    走通用 ``except Exception`` 会被冠上 ``SandboxFailed: `` 前缀，把
    ``exit_code=1 (86ms)`` 这行挤到中间去 —— 排查时第一眼想看的正是它。
    """


@dataclass(slots=True)
class ProcessResult:
    """一次子进程执行的结果。"""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    def brief(self, limit: int = 2000) -> str:
        """压成一段可直接作为工具返回值的文本。"""
        parts: list[str] = []
        if self.timed_out:
            parts.append("执行超时，进程已被强制终止")
        parts.append(f"exit_code={self.returncode} ({self.duration_ms}ms)")
        if self.stdout.strip():
            parts.append(f"stdout:\n{self.stdout.strip()}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{self.stderr.strip()}")
        return "\n".join(parts)[:limit]


def workspace_root() -> Path:
    """工具唯一可读写的根目录（不存在则创建）。"""
    root = get_settings().workspace_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_workspace_path(
    path: str | Path,
    *,
    must_exist: bool = False,
    for_write: bool = False,
) -> Path:
    """把工具传入的路径解析成 workspace 内的绝对路径。

    Args:
        path: 相对 workspace 的路径，或 workspace 内的绝对路径。
        must_exist: 为 True 时要求文件/目录已存在。
        for_write: 为 True 时自动创建父目录。

    Raises:
        SandboxPathError: 路径逃出 workspace，或违反 must_exist。
    """
    root = workspace_root()
    # 注意：Path("") 会变成 Path(".")，所以空值必须在构造 Path 之前拦
    raw_text = str(path).strip()
    if not raw_text:
        raise SandboxPathError("路径不能为空")
    raw = Path(raw_text)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise SandboxPathError(f"路径越界：只允许访问 {root} 内的文件（收到 {path}）")
    if must_exist and not resolved.exists():
        raise SandboxPathError(f"文件不存在：{resolved}")
    if for_write:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _terminate(proc: subprocess.Popen[str]) -> None:
    """尽最大努力终止子进程并回收。"""
    try:
        proc.kill()
    except Exception:  # noqa: BLE001 - 进程可能已退出，kill 失败无需上抛
        logger.debug("子进程 kill 失败（可能已退出）")
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001 - 同上，回收失败只记日志
        logger.warning("子进程回收超时")


def run_python(
    code: str,
    *,
    timeout: int,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> ProcessResult:
    """在独立子进程里执行一段 Python 代码，超时强制终止。

    Args:
        code: 要执行的代码。
        timeout: 墙钟超时（秒）。
        cwd: 子进程工作目录，默认 workspace 根目录（也是代码里相对路径的基准）。
        extra_env: 追加的环境变量。**父进程的环境不会全量继承**，只带
            :data:`SANDBOX_ENV_ALLOWLIST` 里那十几种 + 这里显式追加的（见 :func:`sandbox_env`）。

    Returns:
        :class:`ProcessResult`。超时不抛异常，而是把 ``timed_out=True`` 填好，
        让调用方（工具实现）自己决定怎么表达。
    """
    workdir = cwd or workspace_root()
    workdir.mkdir(parents=True, exist_ok=True)
    sandbox_dir = workdir / SANDBOX_DIR_NAME
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    script_path = sandbox_dir / f"run_{uuid4().hex[:8]}.py"
    script_path.write_text(code, encoding="utf-8")

    env = sandbox_env(extra_env)

    started = time.perf_counter()
    proc = subprocess.Popen(  # 命令与参数由本模块构造，不来自模型
        [sys.executable, "-X", "utf8", str(script_path)],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=_NO_WINDOW,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(proc)
        stdout, stderr = proc.communicate()
    finally:
        script_path.unlink(missing_ok=True)

    result = ProcessResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "",
        stderr=stderr or "",
        duration_ms=int((time.perf_counter() - started) * 1000),
        timed_out=timed_out,
    )
    logger.debug(
        "沙箱执行完成 timed_out=%s exit=%s %dms",
        result.timed_out,
        result.returncode,
        result.duration_ms,
    )
    return result


def run_with_deadline(func: Callable[[], T], timeout: int, *, tool_name: str = "") -> T:
    """给普通工具加一道墙钟上限。

    Raises:
        SandboxTimeout: 超时未返回（注意：线程无法强杀，见模块 docstring）。
    """
    if timeout <= 0:
        return func()

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = func()
        except BaseException as exc:  # noqa: BLE001 - 需要把任何异常带回主线程原样抛出
            box["error"] = exc

    thread = threading.Thread(target=_target, name=f"tool-{tool_name or 'anon'}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise SandboxTimeout(
            f"工具 {tool_name or '<anon>'} 超过 {timeout}s 未返回，已放弃等待（后台线程无法强杀）"
        )
    if "error" in box:
        raise box["error"]
    return cast(T, box["value"])


def retry_call(
    func: Callable[[], T],
    *,
    retry: int,
    base_delay: float = 0.2,
    max_delay: float = 2.0,
) -> tuple[T, int]:
    """指数退避重试。

    Returns:
        ``(返回值, 实际尝试次数)``。

    Raises:
        最后一次失败时原样抛出该异常。**超时不重试**：重跑一次只会再消耗一遍同样的
        墙钟时间，对调用方没有收益，这一点与「网络抖动重试」是两回事。
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return func(), attempt
        except SandboxTimeout:
            raise
        except Exception as exc:  # 重试策略要覆盖任意工具异常；失败超过次数后原样抛出
            if attempt > max(retry, 0):
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning("工具调用第 %d 次失败（%s），%.2fs 后重试", attempt, exc, delay)
            time.sleep(delay)


__all__ = [
    "SANDBOX_DIR_NAME",
    "SANDBOX_ENV_ALLOWLIST",
    "ProcessResult",
    "SandboxError",
    "SandboxFailed",
    "SandboxPathError",
    "SandboxTimeout",
    "resolve_workspace_path",
    "retry_call",
    "run_python",
    "run_with_deadline",
    "sandbox_env",
    "workspace_root",
]
