"""版本号一致性护栏（G-5，关闭条件 ② 的扩展版）。

四个手写位：

* ``pyproject.toml`` 的 ``[project].version``
* ``api/__init__.py`` 的 ``__version__``
* ``core/__init__.py`` 的 ``__version__``
* ``web-react/package.json`` 的 ``version``

另外断言 ``web-react/package-lock.json`` 的根级 ``version`` 与
``packages[""].version`` 两个镜像字段（存在才断言，且至少要有一个）。

不改成运行时读 ``importlib.metadata``（未安装时 ``PackageNotFoundError``，
反而更糟），而是保留手写位、让漏改任一处立即变红。
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
API_INIT = ROOT / "api" / "__init__.py"
CORE_INIT = ROOT / "core" / "__init__.py"
PKG_JSON = ROOT / "web-react" / "package.json"
PKG_LOCK = ROOT / "web-react" / "package-lock.json"

#: ``re.MULTILINE`` + ``search``：只认行首的赋值，跳过 ``__all__`` 等引用；
#: 注释行以 ``#`` 开头，正则不会命中。多个赋值时取第一个。
LITERAL = re.compile(r'^\s*__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _literal_version(path: Path) -> str:
    match = LITERAL.search(path.read_text(encoding="utf-8"))
    assert match, f"{path} 里找不到可用的 __version__ 赋值"
    return match.group(1)


def test_python_runtime_version_matches_pyproject() -> None:
    want = _pyproject_version()
    for path in (API_INIT, CORE_INIT):
        got = _literal_version(path)
        assert got == want, (
            f"{path.relative_to(ROOT)} 的 __version__={got} 与 pyproject.toml 的 {want} 不一致"
            "（改版本号时漏改了一处）"
        )


def test_frontend_package_version_matches_pyproject() -> None:
    want = _pyproject_version()
    got = str(json.loads(PKG_JSON.read_text(encoding="utf-8"))["version"])
    assert got == want, (
        f"web-react/package.json 的 version={got} 与 pyproject.toml 的 {want} 不一致"
        "（全仓对外只报一个版本号）"
    )


def test_package_lock_version_mirrors_pyproject() -> None:
    want = _pyproject_version()
    lock = json.loads(PKG_LOCK.read_text(encoding="utf-8"))

    observed: list[tuple[str, str]] = []
    if "version" in lock:
        observed.append(("package-lock.json#version", str(lock["version"])))
    packages = lock.get("packages")
    package_root = packages.get("") if isinstance(packages, dict) else None
    if isinstance(package_root, dict) and "version" in package_root:
        observed.append(('package-lock.json#packages[""]', str(package_root["version"])))

    assert observed, "package-lock.json 中没有可对账的 version 字段"
    for label, got in observed:
        assert got == want, f"{label} 的 version={got} 与 pyproject.toml 的 {want} 不一致"
