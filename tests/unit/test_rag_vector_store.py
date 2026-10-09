"""``rag/vector_store.py`` 单元测试：sqlite-vec 主路径 + 工厂校验（T02）。

sqlite-vec 未安装时自动 skip 并提示（设计 D6：装上后真用，没装不红）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.types import Chunk

try:
    import sqlite_vec  # noqa: F401

    HAS_SQLITE_VEC = True
except ImportError:  # pragma: no cover
    HAS_SQLITE_VEC = False

pytestmark = pytest.mark.skipif(not HAS_SQLITE_VEC, reason="sqlite-vec 未安装")


DIM = 8


def _chunk(document_id: str, seq: int, text: str = "片段") -> Chunk:
    return Chunk(
        document_id=document_id,
        seq=seq,
        text=text,
        start_char=seq * 10,
        end_char=seq * 10 + 10,
    )


def _vector(seed: int) -> list[float]:
    return [(seed + j) % 7 + 0.1 for j in range(DIM)]


# --------------------------------------------------------------------------- #
def test_add_query_roundtrip(tmp_path: Path) -> None:
    from rag.vector_store import SQLiteVecStore

    store = SQLiteVecStore(tmp_path / "t.db", dim=DIM)
    doc = "doc-vec00000001"
    chunks = [_chunk(doc, seq) for seq in range(10)]
    store.add(chunks, [_vector(seq) for seq in range(10)])
    assert store.count() == 10
    assert store.backend_name() == "sqlite-vec"

    hits = store.query(_vector(3), top_k=5)
    assert len(hits) == 5
    top_id, top_score = hits[0]
    assert top_id == f"{doc}:0003"
    assert 0.0 <= top_score <= 1.0
    # 相似度降序
    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)
    store.close()


def test_persistence_after_reopen(tmp_path: Path) -> None:
    """持久化验收：关闭后重开连接，查询仍命中。"""
    from rag.vector_store import SQLiteVecStore

    db_path = tmp_path / "persist.db"
    doc = "doc-vec00000002"
    store = SQLiteVecStore(db_path, dim=DIM)
    store.add([_chunk(doc, 0), _chunk(doc, 1)], [_vector(0), _vector(1)])
    store.close()

    reopened = SQLiteVecStore(db_path, dim=DIM)
    assert reopened.count() == 2
    hits = reopened.query(_vector(1), top_k=2)
    assert hits[0][0] == f"{doc}:0001"
    reopened.close()


def test_delete_document_prefix_scoped(tmp_path: Path) -> None:
    from rag.vector_store import SQLiteVecStore

    store = SQLiteVecStore(tmp_path / "del.db", dim=DIM)
    doc_a, doc_b = "doc-vec0000000a", "doc-vec0000000b"
    store.add(
        [_chunk(doc_a, 0), _chunk(doc_a, 1), _chunk(doc_b, 0)],
        [_vector(0), _vector(1), _vector(2)],
    )
    store.delete_document(doc_a)
    assert store.count() == 1
    remaining = store.query(_vector(2), top_k=5)
    assert remaining[0][0] == f"{doc_b}:0000"
    store.close()


def test_overwrite_same_chunk_id(tmp_path: Path) -> None:
    from rag.vector_store import SQLiteVecStore

    store = SQLiteVecStore(tmp_path / "ow.db", dim=DIM)
    doc = "doc-vec00000003"
    store.add([_chunk(doc, 0)], [_vector(0)])
    store.add([_chunk(doc, 0)], [_vector(5)])  # INSERT OR REPLACE
    assert store.count() == 1
    hits = store.query(_vector(5), top_k=1)
    assert hits[0][0] == f"{doc}:0000"
    store.close()


def test_factory_rejects_unknown_backend(tmp_path: Path) -> None:
    from rag.exceptions import StoreError
    from rag.vector_store import create_vector_store

    class _FakeSettings:
        vector_store_backend = "milvus"

        knowledge_dir = tmp_path

    with pytest.raises(StoreError, match="未知向量库后端"):
        create_vector_store(_FakeSettings(), dim=DIM)  # type: ignore[arg-type]


def test_factory_sqlite_uses_settings_db_path(tmp_path: Path) -> None:
    from rag.vector_store import create_vector_store

    class _FakeSettings:
        vector_store_backend = "sqlite-vec"
        db_path = tmp_path / "main.db"
        knowledge_dir = tmp_path

    store = create_vector_store(_FakeSettings(), dim=DIM)  # type: ignore[arg-type]
    assert store.backend_name() == "sqlite-vec"
    store.add([_chunk("doc-vec00000004", 0)], [_vector(1)])
    assert store.count() == 1
    store.close()


# --------------------------------------------------------------------------- #
# Q7-01（2026-10-02）：vec0 的 distance 是 L2，出口必须是换算后的真余弦。
#   这两条用例是**改前必红**的形状 —— 旧实现 ``1-d`` 在下面第一组数据上就把
#   真余弦 0.5 打成 0.0，而它恰好是"融合里向量那一档大面积并列"的成因。
#   失败即说明有人把换算改回去了，可以整段删掉这层兼容。
# --------------------------------------------------------------------------- #
def test_l2_distance_to_cosine_conversion_table() -> None:
    """纯函数面：单位向量下 ``d = √(2-2cos)`` ⇒ ``cos = 1 - d²/2``。"""
    from math import sqrt

    from rag.vector_store import _l2_distance_to_cosine

    assert _l2_distance_to_cosine(0.0) == pytest.approx(1.0)  # 同向
    assert _l2_distance_to_cosine(1.0) == pytest.approx(0.5)  # 60°，旧写法在这里给 0.0
    assert _l2_distance_to_cosine(sqrt(2.0)) == pytest.approx(0.0)  # 正交
    assert _l2_distance_to_cosine(2.0) == 0.0  # 反向：负余弦压到 0（口径见函数注释）


def test_query_returns_true_cosine_for_unit_vectors(tmp_path: Path) -> None:
    """端到端面：真用 vec0 存三条单位向量，出口分数必须等于真余弦。

    这条比上一条贵（要建虚拟表），但它钉的是"vec0 默认度量到底是 L2 还是 cosine"
    这个**只有实跑才知道**的事实；如果哪天升级 sqlite-vec 改了默认度量，
    这条会红，而纯函数那条不会 —— 两条都要留。
    """
    from rag.vector_store import SQLiteVecStore

    dim = 3
    doc = "doc-vec00000009"
    store = SQLiteVecStore(tmp_path / "cos.db", dim=dim)
    unit = [
        [1.0, 0.0, 0.0],  # 与查询向量同向 ⇒ 真余弦 1.0
        [0.5, 0.8660254037844386, 0.0],  # 夹角 60° ⇒ 真余弦 0.5（旧写法在这里给 0.0）
        [-1.0, 0.0, 0.0],  # 反向 ⇒ 负余弦压到 0
    ]
    chunks = [_chunk(doc, seq) for seq in range(len(unit))]
    store.add(chunks, unit)

    hits = dict(store.query([1.0, 0.0, 0.0], top_k=len(unit)))
    assert hits[f"{doc}:0000"] == pytest.approx(1.0, abs=1e-6)
    assert hits[f"{doc}:0001"] == pytest.approx(0.5, abs=1e-6)
    assert hits[f"{doc}:0002"] == pytest.approx(0.0, abs=1e-6)
    store.close()
