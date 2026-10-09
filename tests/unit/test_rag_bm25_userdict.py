"""M3 · T3-2 单测：BM25 自定义词典臂（A-DICT）。

守两件事：① 词典真的改变切分与召回；② **不污染全局 jieba** —— 消融 runner 在同一进程里
依次跑多条臂，若词典是全局加载的，"没开词典"的臂会静默吃到词典，两臂之差直接归零。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.bm25 import BM25Index, _tokenize  # noqa: E402

pytestmark = pytest.mark.unit

#: m2_rag.md §7.1 记录的已知问题：默认词典把「六类线」切成「六类/线」
_TERM = "六类线"
_SENTENCE = "六类线的最大施工弯曲半径为线径的四倍"


@pytest.fixture
def userdict(tmp_path: Path) -> str:
    path = tmp_path / "terms.txt"
    path.write_text(f"{_TERM} 200 n\n四倍 100 n\n", encoding="utf-8")
    return str(path)


def _chunks() -> list[SimpleNamespace]:
    """≥4 条语料：rank_bm25 用的是不带 +1 的 Robertson idf，
    2 条语料里 df=1 会让 idf 恰好用 log(1)=0、整条查询得分归零（踩过一次）。"""
    return [
        SimpleNamespace(chunk_id="a:0", text=_SENTENCE),
        SimpleNamespace(chunk_id="b:0", text="综合布线系统支持语音数据图像业务"),
        SimpleNamespace(chunk_id="c:0", text="安防监控系统图像分辨率为1080P"),
        SimpleNamespace(chunk_id="d:0", text="门禁控制器通过RS485总线联网"),
    ]


# --------------------------------------------------------------------------- #
def test_default_dictionary_splits_the_term() -> None:
    """对照前提：默认词典下「六类线」确实是碎切，且 M2 路径不建私有分词器。"""
    assert _TERM not in _tokenize(_SENTENCE)
    index = BM25Index()
    index.rebuild(_chunks())
    assert index._tokenizer is None, "无词典时必须走全局分词（不多载一份词典）"


def test_userdict_keeps_the_term_whole(userdict: str) -> None:
    index = BM25Index(userdict=userdict)
    index.rebuild(_chunks())
    assert index.size() == 4
    assert _TERM in index._tokens(_SENTENCE), "词典生效后整词成一个 token"
    hits = index.search(_TERM, 5)
    assert hits and hits[0][0] == "a:0", "整词命中必须回到含该术语的 chunk"


def test_userdict_removes_the_fragment_false_hit(userdict: str) -> None:
    """臂效果的真实度量：**排序**，不是分数。

    挂词典后查询从两个 token（六类/线）变成一个（六类线），BM25 的可加项少了一项，
    绝对分数反而会下降（实测 1.50 → 0.78）—— 词典改变了切分，也就改变了分数量纲，
    所以跨臂只能比 Recall/MRR/nDCG，比原始分或归一分都是错的。
    碎切的代价是可观测的假命中：只含「六类」碎片、与「六类线」无关的 chunk 也会被召回。
    """
    corpus = [
        SimpleNamespace(chunk_id="a:0", text=_SENTENCE),
        SimpleNamespace(chunk_id="g:0", text="机柜内已安装六类配线架并标注端口"),
        SimpleNamespace(chunk_id="c:0", text="安防监控系统图像分辨率为1080P"),
        SimpleNamespace(chunk_id="d:0", text="门禁控制器通过RS485总线联网"),
        SimpleNamespace(chunk_id="f:0", text="机房接地电阻要求不大于四欧姆"),
    ]
    with_dict = BM25Index(userdict=userdict)
    with_dict.rebuild(corpus)
    without = BM25Index()
    without.rebuild(corpus)

    hits = without.search(_TERM, 5)
    dict_ids = [chunk_id for chunk_id, _ in with_dict.search(_TERM, 5)]
    assert {chunk_id for chunk_id, _ in hits} == {"a:0", "g:0"}, (
        "对照前提：默认词典把查询切成 六类/线 两个碎片，只含「六类」的无关 chunk 也被召回"
    )
    assert hits[0][0] == "a:0"
    assert dict_ids == ["a:0"], "挂词典后只留整词命中的 chunk"


def test_userdict_does_not_leak_into_global_tokenizer(userdict: str) -> None:
    """私有分词器纪律：挂过词典之后，全局 jieba 的切分结果必须原样不变。"""
    before = _tokenize(_SENTENCE)
    indexed = BM25Index(userdict=userdict)
    indexed.rebuild(_chunks())
    assert indexed.search(_TERM, 1)
    assert _tokenize(_SENTENCE) == before, "词典不得写进全局 jieba"
    plain = BM25Index()
    plain.rebuild(_chunks())
    assert _TERM not in _tokenize(_SENTENCE), "新建的无词典索引也不得继承词典"


def test_tokenizer_is_lazy_and_cached(userdict: str) -> None:
    index = BM25Index(userdict=userdict)
    assert index._tokenizer is None, "构造不得加载词典"
    index.rebuild(_chunks())
    first = index._tokenizer
    index.rebuild(_chunks())
    assert index._tokenizer is first, "词典只加载一次"


def test_missing_userdict_file_fails_loudly(tmp_path: Path) -> None:
    index = BM25Index(userdict=str(tmp_path / "没有这个文件.txt"))
    with pytest.raises(FileNotFoundError, match="自定义词典不存在"):
        index.rebuild(_chunks())


def test_blank_userdict_keeps_the_m2_path() -> None:
    """空串/纯空白 = 不启用，走 M2 的全局分词路径（默认行为零变化）。"""
    for value in ("", "   "):
        index = BM25Index(userdict=value)
        index.rebuild(_chunks())
        assert index._tokenizer is None, "空词典不得建私有分词器"
        assert index.search("弯曲半径", 5)
