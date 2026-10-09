"""版本号一致性护栏（对应 known_residuals.md 的 G-5，关闭条件②）。

G-5 原话：``pyproject.toml`` 的 ``version`` 与 ``api/__init__.py`` 的
``__version__`` 是两份手写的同一数，没有单一真源，改版本时漏一处就会让
"包说 0.2.0、``/openapi.json`` 的 ``info.version`` 还说 0.1.0"。

这里不改成运行时读 ``importlib.metadata``（G-5 已论证：未安装时
``PackageNotFoundError``，反而更糟），而是**留手写位、加断言**——
漏改一处就立刻变红，不再静默漂移。
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
API_INIT = ROOT / "api" / "__init__.py"
CORE_INIT = ROOT / "core" / "__init__.py"
PKG_JSON = ROOT / "web-react" / "package.json"

LITERAL = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _literal_version(path: Path) -> str:
    m = LITERAL.search(path.read_text(encoding="utf-8"))
    assert m, "%s 里找不到 __version__ 字面量" % path
    return m.group(1)


def test_python_runtime_version_matches_pyproject():
    want = _pyproject_version()
    for p in (API_INIT, CORE_INIT):
        got = _literal_version(p)
        assert got == want, (
            "%s 的 __version__=%s 与 pyproject.toml 的 version=%s 不一致"
            "（改版本号时漏改了一处）" % (p.name, got, want)
        )


def test_frontend_package_version_matches_pyproject():
    want = _pyproject_version()
    got = json.loads(PKG_JSON.read_text(encoding="utf-8"))["version"]
    assert got == want, (
        "web-react/package.json 的 version=%s 与 pyproject.toml 的 version=%s 不一致"
        "（全仓对外只报一个版本号）" % (got, want)
    )
