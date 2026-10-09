"""B-9（P1）：仓库里不许有"和同名原文件逐字节全等"的 ``_1`` 副本。

2026-09-26 清理掉 1,034 个（``evaluation/`` 全目录，逐字节比对后删除；``data/`` 那个
副本库 ``trinity_1.db`` **刻意留着**，因为 ``docs/known_residuals.md`` 与
``web-react/tools/uicheck/formula_hits.py`` 都把它当第二个库在查）。

为什么这不只是"死代码好不好看"的问题：

* ``evaluation/*.py`` 的 16 个副本（8,752 行）没人 import，但它们让 ruff/mypy/coverage
  的统计虚高，还触发 5 处 N999 非法模块名 —— 属于"读数失真"。
* **``evaluation/fixtures_cmrc/`` 里有 1,000 个副本，会被真的吃进语料**：
  ``retrieval_eval.py`` 用 ``iterdir()`` + 后缀过滤收集语料，``document_id`` 取
  ``doc-{stem}`` —— ``cmrc_DEV_1003_1.md`` 与 ``cmrc_DEV_1003.md`` 是两个不同的 id，
  于是"1 000 篇"变 2 000 篇，``ablation.py`` 报出来的 ``docs`` 也跟着翻倍。
  检索指标会在没人改任何算法的情况下漂掉，而且**不会报错**。

来源线索：``evaluation/reports/ablation/ablation_summary.json`` 里记的 ``fixtures``
路径是 ``…\\<某处>\\trinity-zipped\\evaluation\\fixtures_cmrc`` —— 这批副本极可能来自
一次"解压到已存在的目录 / 云盘同步冲突"，工具用 ``_1`` 后缀保住了两份。不查清来源
它还会再长出来，所以这里钉一条用例而不是一次性人工清理。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "evaluation"

#: 语料目录的既定口径（``evaluation/retrieval_eval.py`` 模块 docstring 与
#: ``scripts/build_golden_set.py`` 的产物约定）：1 篇 = 1 文件 = 1 chunk。
CMRC_FIXTURES = EVAL_DIR / "fixtures_cmrc"
CMRC_DOC_COUNT = 1000


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - 只为判"逐字节是否相同"，非安全用途


def _identical_copies(root: Path) -> list[str]:
    """返回 root 下"与同名原文件全等"的 ``X_1.ext`` 副本相对路径。

    刻意用"全等"而不是"名字像"来判：``cmrc_DEV_1.md`` 是真的第 1 号文档，
    ``fc_1.b_0`` 是 jieba 的模型文件 —— 按名字删会误伤，全等才是可证安全的子集。
    """
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        marker = f"_1{path.suffix}"
        index = path.name.find(marker)
        if index < 0:
            continue
        original = path.with_name(path.name[:index] + path.suffix)
        if not original.exists():
            continue  # 合法重名（如 cmrc_DEV_1.md），不是副本
        if _md5(path) == _md5(original):
            found.append(str(path.relative_to(PROJECT_ROOT)))
    return found


def test_evaluation_下没有全等副本() -> None:
    assert _identical_copies(EVAL_DIR) == [], "又长出 _1 副本了：先查同步/解压工具，再删干净"


def test_前件_目录里确实还有合法的重名文件() -> None:
    """证明上面那条不是"永远找不到所以永远绿"。

    ``cmrc_DEV_1.md`` 是真的 1 号文档（它的"原文件" ``cmrc_DEV.md`` 不存在），
    判据必须认得这种情形 —— 所以本模块用全等而不是名字模式定性。
    """
    legit = CMRC_FIXTURES / "cmrc_DEV_1.md"
    assert legit.exists(), "语料目录结构变了，本文件的判据要跟着改"
    assert not (CMRC_FIXTURES / "cmrc_DEV.md").exists()


@pytest.mark.parametrize(
    "fixtures_dir",
    [CMRC_FIXTURES, EVAL_DIR / "fixtures_cmrc_a"],
    ids=["cmrc-1000", "cmrc-a-3051"],
)
def test_语料篇数与文档口径一致(fixtures_dir: Path) -> None:
    """``iterdir()`` 吃什么，口径就得对得上 —— 副本混进来时这条会第一个红。"""
    expected = CMRC_DOC_COUNT if fixtures_dir == CMRC_FIXTURES else 3051
    _check_corpus_count(fixtures_dir, expected)


def _check_corpus_count(fixtures_dir: Path, expected: int) -> None:
    """数一篇一篇的语料，并按 loader 自己的后缀过滤器判口径。

    ``fixtures_cmrc_a/`` 是 ``scripts/build_corpus_a.py`` 的产物、**不入库**
    （.gitignore:57，14 MB），所以在没跑过那支脚本的机器上这一档只能 skip ——
    让它 FileNotFoundError 收工，等于把"本地跑得过"冒充成"判据通过了"。
    跳过分支本身由 :func:`test_缺语料的机器上是skip不是fail` 钉住。
    """
    if not fixtures_dir.is_dir():
        pytest.skip(f"{fixtures_dir.name} 不入库，这台机器上没建过这套语料")
    docs = [
        path
        for path in fixtures_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}
    ]
    assert len(docs) == expected, (
        f"{fixtures_dir.name} 实际 {len(docs)} 篇，口径 {expected} 篇："
        "多出来的就是被 iterdir 当语料吃的副本"
    )


def test_缺语料的机器上是skip不是fail() -> None:
    """前件：跳过这条分支得真的能走通。

    没有这一条，下一个把 ``pytest.skip`` 改成 ``assert dir.exists()`` 的人不会翻红，
    而那条改动在 CI 上表现为"整套口径用例突然全红"，很容易被误读成语料又脏了。
    """
    missing = EVAL_DIR / "fixtures_cmrc_no_such_dir"
    assert not missing.exists(), "探针目录竟然存在了，换一个名字"
    with pytest.raises(pytest.skip.Exception):
        _check_corpus_count(missing, CMRC_DOC_COUNT)


def test_副本库不在这个判据范围内() -> None:
    """钉住"我们刻意没删 ``data/trinity_1.db``"这件事，别让它悄悄进判据。"""
    copy_db = PROJECT_ROOT / "data" / "trinity_1.db"
    assert not copy_db.exists() or (PROJECT_ROOT / "docs" / "known_residuals.md").exists(), (
        "副本库还在，但引用它的文档没了 —— 要么删库，要么改判据，别两边挂着"
    )
