"""B-1（P0）：``run_python`` 子进程的环境变量必须是**白名单**，不是全量继承。

背景：本机实测（外部检测报告 2026-09-25 B-1）在 ``code_exec`` 里 print 环境就能拿到
``ANTHROPIC_API_KEY`` 真值 —— 因为旧实现是 ``env = dict(os.environ)``。跑在这里的是
**模型生成的代码**，一次提示注入就足够把密钥带走。

判据口径：断言的是"子进程能看到**哪些名字**"这个**上界**，与父进程实际有多少变量无关
（本机 88 个、CI 上可能是 30 个，都不影响这条判据成立）。

不用 pytest 的 ``tmp_path``（本机沙箱对递归删除 fail-closed），落盘都在
``data/.test-scratch/``（已 gitignore）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from config import PROJECT_ROOT
from core.tools.sandbox import SANDBOX_ENV_ALLOWLIST, run_python, sandbox_env

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"

#: 本模块**自己**注入的假密钥。断言只看这个值与这个名字，不去碰宿主上真实存在的密钥。
SENTINEL_NAME = "LLM_API_KEY"
SENTINEL_VALUE = "sentinel-should-never-cross-into-the-child"

#: 子进程里一定允许出现的两个（由 :func:`sandbox_env` 自己写死，不算"继承"）
_FORCED = {"PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"}


@pytest.fixture
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """独立的沙箱工作目录（避开 tmp_path，见模块 docstring）。"""
    del tmp_path_factory  # 只用项目内 scratch
    path = TEST_SCRATCH_ROOT / f"sandbox-env-{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _child_env_names(workspace: Path, extra: dict[str, str] | None = None) -> set[str]:
    """真的起一个子进程，把它看到的变量名集合拿回来。"""
    code = "import json, os\nprint(json.dumps(sorted(os.environ)))"
    result = run_python(code, timeout=30, cwd=workspace, extra_env=extra)
    assert result.timed_out is False, result.brief()
    assert result.returncode == 0, result.brief()
    return set(json.loads(result.stdout.strip()))


# --------------------------------------------------------------------------- #
# 白名单本身
# --------------------------------------------------------------------------- #
class TestAllowlistContents:
    """名单是"少而必需"，不是"看起来全"。"""

    def test_密钥类变量名一律不在名单里(self) -> None:
        for name in ("LLM_API_KEY", "API_AUTH_TOKEN", "ANTHROPIC_API_KEY", "DB_URL", "HF_TOKEN"):
            assert name not in SANDBOX_ENV_ALLOWLIST, f"{name} 不该被继承进沙箱"

    def test_解释器指向类变量不在名单里(self) -> None:
        # PYTHONPATH / PYTHONHOME 会把子进程的 import 指回项目环境，
        # 等于给模型生成的代码一条 import 平台内部模块（进而读 .env）的路。
        assert "PYTHONPATH" not in SANDBOX_ENV_ALLOWLIST
        assert "PYTHONHOME" not in SANDBOX_ENV_ALLOWLIST
        assert "VIRTUAL_ENV" not in SANDBOX_ENV_ALLOWLIST

    def test_跑起来必需的几项确实在(self) -> None:
        # Windows 缺 SystemRoot 会让子进程里的 socket/ssl 直接报错；
        # PATH 缺了 shutil.which 与再起子进程全废。这两条是"白名单不能矫枉过正"的锚。
        for name in ("PATH", "SYSTEMROOT" if os.name == "nt" else "HOME"):
            assert name in SANDBOX_ENV_ALLOWLIST, f"{name} 必须放行，否则沙箱不工作"


# --------------------------------------------------------------------------- #
# 真实子进程
# --------------------------------------------------------------------------- #
class TestChildProcessEnvironment:
    """端到端：让子进程自己报告它看到了什么。"""

    def test_哨兵密钥不出现在子进程里(self, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SENTINEL_NAME, SENTINEL_VALUE)
        # 前件（反向钉）：父进程确实带着它 —— 否则下面那条断言是恒真的空判。
        assert os.environ.get(SENTINEL_NAME) == SENTINEL_VALUE

        names = _child_env_names(workspace)
        assert SENTINEL_NAME not in names, f"子进程读到了 {SENTINEL_NAME}"

    def test_子进程看到的名集合有上界且与父进程规模无关(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 再塞十个假变量进去：上界不该动 —— 判据是"名单"，不是"少了几十个"。
        for index in range(10):
            monkeypatch.setenv(f"FAKE_INJECT_{index}", "x")
        names = _child_env_names(workspace)
        assert names <= SANDBOX_ENV_ALLOWLIST | _FORCED, f"越界继承：{sorted(names - SANDBOX_ENV_ALLOWLIST - _FORCED)}"
        assert not {n for n in names if n.startswith("FAKE_INJECT_")}

    def test_哨兵值也不许从任何名字里漏出来(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 只查名字会被"改个名再 dump"绕过；这里连值一起查。
        monkeypatch.setenv(SENTINEL_NAME, SENTINEL_VALUE)
        code = "import os\nprint('|'.join(f'{k}={v}' for k, v in sorted(os.environ.items())))"
        result = run_python(code, timeout=30, cwd=workspace)
        assert SENTINEL_VALUE not in result.stdout

    def test_白名单没有把子进程弄坏(self, workspace: Path) -> None:
        """tempfile / Path.home() / shutil.which 都要还能用，否则是矫枉过正。"""
        code = (
            "import shutil, tempfile\n"
            "from pathlib import Path\n"
            "print('tmp', bool(tempfile.gettempdir()))\n"
            "print('home', Path.home().exists())\n"
            "print('which', shutil.which('python') is not None or shutil.which('cmd') is not None)\n"
        )
        result = run_python(code, timeout=30, cwd=workspace)
        assert result.returncode == 0, result.brief()
        assert "tmp True" in result.stdout
        assert "home True" in result.stdout
        assert "which True" in result.stdout, "PATH 没放行成功"

    def test_显式追加的变量仍然生效(self, workspace: Path) -> None:
        # extra_env 是调用方主动写的白名单外通道（模型不可控），必须保留可用。
        names = _child_env_names(workspace, {"RUNTIME_ONLY": "1"})
        assert "RUNTIME_ONLY" in names


# --------------------------------------------------------------------------- #
# 纯函数侧
# --------------------------------------------------------------------------- #
class TestSandboxEnvPure:
    def test_不回写进程环境(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SENTINEL_NAME, SENTINEL_VALUE)
        before = dict(os.environ)
        env = sandbox_env()
        assert dict(os.environ) == before, "sandbox_env 改了父进程环境"
        assert SENTINEL_NAME not in env

    def test_两项写死口径(self) -> None:
        env = sandbox_env()
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"

    def test_读配置不会把密钥写回进程环境(self) -> None:
        """白名单能成立，前提是 `.env` 的值只活在 :class:`Settings` 里。

        今天成立（全仓除评测脚本里那几处显式注入外，没有 ``os.environ[...] =`` 写法），
        但这是"下一个改 config 的人顺手 setdefault 一下"就会静默失效的前提：
        一旦回写，父进程环境本身就带着密钥，白名单挡得住「继承」、挡不住「自己写进去」。
        所以钉一条：读一遍配置，环境变量的**名字集合**不许变。
        """
        from config import get_settings, reset_settings_cache

        reset_settings_cache()
        before = set(os.environ)
        get_settings()
        reset_settings_cache()
        assert set(os.environ) == before, "读配置改了进程环境"
