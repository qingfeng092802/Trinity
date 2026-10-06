"""实验矩阵单测（M3 · T2 出口门槛：必须证明"多改一个字段会被拒绝执行"）。

这里测的是 M3 的立身之本 —— 严格单变量不是文档里的一句口号，
而是 ``ArmConfig.validate()`` 会抛出来的错误。所以下面每个"应当失败"的用例
都比"应当通过"的用例更重要。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.experiment import (  # noqa: E402
    ArmConfig,
    ExperimentError,
    Matrix,
    build_matrix,
    load_matrix,
    phase_arms,
    resolve_arm,
)

pytestmark = pytest.mark.unit

MATRIX_YAML = PROJECT_ROOT / "evaluation" / "dataset" / "matrix_m3.yaml"


def _arm(arm_id: str, changes: dict[str, Any], **kw: Any) -> ArmConfig:
    baseline = kw.pop("parent", None) or ArmConfig(arm_id="A-BASE", role="baseline")
    return resolve_arm(arm_id, changes, parent=baseline, **kw)


# --------------------------------------------------------------------------- #
# 合法：单变量
# --------------------------------------------------------------------------- #
def test_single_change_is_accepted() -> None:
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-E2a-rrf", {"fusion": "rrf"}, parent=baseline)
    assert arm.validate(baseline) == []
    assert arm.effective_changes(baseline) == {"fusion": ("weighted", "rrf")}


def test_rrf_arm_keeps_weighted_weights_without_counting_them_as_changes() -> None:
    """``fusion=weighted`` 下 ``rrf_k`` 不被读取，所以基线预置 rrf_k=60 不算差异；
    而 rrf 臂里 ``bm25_weight`` 反过来变惰性 —— 两边都不生效的字段不进 effective_changes。"""
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-E2a-rrf", {"fusion": "rrf"}, parent=baseline)
    assert "bm25_weight" not in arm.active_fields()
    assert "rrf_k" in arm.active_fields()


# --------------------------------------------------------------------------- #
# 应当失败：多变量（T2 的核心门槛）
# --------------------------------------------------------------------------- #
def test_two_effective_changes_are_rejected() -> None:
    """同时改分块和融合 → 提升归因不到任何一个组件，必须拒绝。"""
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-BAD", {"chunk_mode": "semantic", "fusion": "rrf"}, parent=baseline)
    problems = arm.validate(baseline)
    assert len(problems) == 1
    assert "单变量消融" in problems[0]
    assert "chunk_mode" in problems[0] and "fusion" in problems[0]


def test_three_effective_changes_listed_in_error() -> None:
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm(
        "A-BAD3",
        {"chunk_mode": "semantic", "fusion": "rrf", "embed_backend": "torch"},
        parent=baseline,
    )
    problems = arm.validate(baseline)
    assert problems and "3 个生效字段" in problems[0]


def test_identical_to_baseline_is_rejected() -> None:
    """空 changes 的臂跑了没有任何信息量，白烧一轮索引。"""
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-CLONE", {}, parent=baseline)
    problems = arm.validate(baseline)
    assert problems and "与基线完全相同" in problems[0]


def test_inert_only_change_is_rejected() -> None:
    """只改 ``rrf_k`` 而 fusion 仍是 weighted —— 值变了但代码根本不读它，等价于没改。

    这是最阴的一种错：YAML 看上去改了东西，报表里两臂逐位相同，
    然后有人会把"无差异"解读成"这个参数不敏感"。
    """
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-NOOP", {"rrf_k": 20}, parent=baseline)
    problems = arm.validate(baseline)
    assert problems and "惰性字段" in problems[0]


def test_effective_change_plus_inert_change_is_flagged() -> None:
    """合法的单变量 + 一个手滑带进来的惰性改动，也要报出来，别让它进报表。

    ``rerank_backend`` 在 ``reranker=None`` 时两边都不被读取：
    它不构成第二个实验变量（所以不该拦"多变量"），但它是无意义差异，
    留着会让报表里两臂的 config 快照长得不一样，读报表的人要白白困惑。
    """
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-MIX", {"fusion": "rrf", "rerank_backend": "sentence-transformers"}, parent=baseline)
    problems = arm.validate(baseline)
    assert len(problems) == 1 and "惰性改动" in problems[0]


def test_weight_change_across_fusion_modes_counts_as_a_variable() -> None:
    """``bm25_weight`` 在基线（weighted）里生效、在 rrf 臂里不生效 ——
    按"一边生效即算改动"的规则，这仍然算第二个变量，必须拦。

    反过来想更清楚：如果允许它随便写，那就没人会去核对"这个值到底被没被读到"。
    """
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    arm = _arm("A-MIX2", {"fusion": "rrf", "bm25_weight": 0.1}, parent=baseline)
    problems = arm.validate(baseline)
    assert problems and "单变量消融" in problems[0]


# --------------------------------------------------------------------------- #
# 组合臂
# --------------------------------------------------------------------------- #
def test_combo_arm_allows_multi_change_but_requires_notes() -> None:
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    changes = {"fusion": "rrf", "reranker": "BAAI/bge-reranker-base"}
    assert _arm("A-E6", changes, parent=baseline, role="combo", notes="混合+重排").validate(baseline) == []
    problems = _arm("A-E6", changes, parent=baseline, role="combo").validate(baseline)
    assert problems and "notes" in problems[0]


# --------------------------------------------------------------------------- #
# 装配期防呆
# --------------------------------------------------------------------------- #
def test_unknown_field_name_raises() -> None:
    """YAML 里把 chunk_size 拼成 chunk_szie，必须炸而不是悄悄按默认值跑。"""
    with pytest.raises(ExperimentError, match="未知字段"):
        _arm("A-TYPO", {"chunk_szie": 300})


def test_identity_field_cannot_be_set_via_changes() -> None:
    with pytest.raises(ExperimentError, match="身份字段"):
        _arm("A-X", {"arm_id": "OTHER"})


def test_reference_is_also_the_inherited_parent() -> None:
    """回归用例：reference 不只是比较标签，它决定继承哪份父配置。

    A-E1-torch-base 只声明 embed_model，必须从 A-E1-backend 继承到 ``embed_backend=torch``。
    若实现成"一律从 A-BASE 继承"，这条臂会静默变成 ONNX + bge-base，
    而 ONNX 后端压根不支持 bge-base —— 一个字段没多改，实验条件却完全不同。
    """
    matrix = build_matrix(
        {
            "baseline": {"arm_id": "A-BASE"},
            "arms": [
                {"arm_id": "A-E1-backend", "changes": {"embed_backend": "torch"}},
                {
                    "arm_id": "A-E1-torch-base",
                    "reference": "A-E1-backend",
                    "changes": {"embed_model": "BAAI/bge-base-zh-v1.5"},
                },
            ],
        }
    )
    arm = next(item for item in matrix.all_arms if item.arm_id == "A-E1-torch-base")
    assert arm.embed_backend == "torch"
    assert arm.embed_model == "BAAI/bge-base-zh-v1.5"
    assert matrix.validate() == []
    assert arm.effective_changes(matrix.reference_for(arm)) == {
        "embed_model": ("BAAI/bge-small-zh-v1.5", "BAAI/bge-base-zh-v1.5")
    }


def test_reference_must_be_defined_earlier() -> None:
    with pytest.raises(ExperimentError, match="还没定义"):
        build_matrix(
            {
                "baseline": {"arm_id": "A-BASE"},
                "arms": [
                    {"arm_id": "A-2", "reference": "A-1", "changes": {"fusion": "rrf"}},
                    {"arm_id": "A-1", "changes": {"reranker": "x"}},
                ],
            }
        )


def test_missing_phase_baseline_is_reported() -> None:
    """有 phase=B 的臂却没有 phase=B 的基线 → 归因无参照，必须报。"""
    matrix = build_matrix(
        {
            "baseline": {"arm_id": "A-BASE"},
            "arms": [{"arm_id": "B-ONE", "phase": "B", "reference": "A-BASE",
                      "changes": {"prompt": "answer_basic"}}],
        }
    )
    problems = matrix.validate()
    assert any("phase=B 必须有且仅有一个基线臂" in p for p in problems)


# --------------------------------------------------------------------------- #
# 参数合法性：宁可不跑，也不要静默改参数
# --------------------------------------------------------------------------- #
def test_weighted_weights_must_sum_to_one_without_normalizing() -> None:
    """与 ``config.py`` 的 `_validate_rag_params`（归一 + warn）刻意相反：
    这里直接拒绝。静默归一会让"BM25 权重 0.5"的臂实际跑成别的值（m3_design.md 陷阱 6）。"""
    with pytest.raises(ExperimentError, match="必须 = 1"):
        ArmConfig(arm_id="A-W", bm25_weight=0.5, vector_weight=0.3)
    with pytest.raises(ExperimentError, match="必须 = 1"):
        ArmConfig(arm_id="A-W", bm25_weight=0.8, vector_weight=0.8)
    # 单路融合不做归一检查：两个权重根本不被读取
    ArmConfig(arm_id="A-V", fusion="vector_only", bm25_weight=0.0, vector_weight=0.0)


def test_fetch_k_must_cover_top_k() -> None:
    with pytest.raises(ExperimentError, match="fetch_k"):
        ArmConfig(arm_id="A-F", fetch_k=3, top_k=5)


def test_chunk_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ExperimentError, match="chunk_overlap"):
        ArmConfig(arm_id="A-C", chunk_size=500, chunk_overlap=500)


def test_phase_a_must_not_carry_prompt() -> None:
    """检索臂要零 LLM 调用（可断网跑），带 prompt 说明 phase 写错了。"""
    with pytest.raises(ExperimentError, match="不该带 prompt"):
        ArmConfig(arm_id="A-X", phase="A", prompt="answer_basic")


def test_phase_b_requires_prompt() -> None:
    with pytest.raises(ExperimentError, match="必须指定 prompt"):
        ArmConfig(arm_id="B-X", phase="B")


# --------------------------------------------------------------------------- #
# 索引复用（§8.3 的排期依据）
# --------------------------------------------------------------------------- #
def test_fusion_and_rerank_changes_reuse_index() -> None:
    """融合/重排/prompt 只影响查询侧 —— 换它们不该重建索引。"""
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    assert _arm("A-RRF", {"fusion": "rrf"}, parent=baseline).index_key() == baseline.index_key()
    assert _arm("A-RK", {"reranker": "x"}, parent=baseline).index_key() == baseline.index_key()
    assert _arm("A-TOP", {"top_k": 3}, parent=baseline).index_key() == baseline.index_key()


def test_embedding_and_chunking_changes_require_reindex() -> None:
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    assert _arm("A-EM", {"embed_model": "other"}, parent=baseline).index_key() != baseline.index_key()
    assert _arm("A-CK", {"chunk_size": 300}, parent=baseline).index_key() != baseline.index_key()
    # jieba 词典改变 BM25 词条 → 倒排索引也变了
    assert _arm("A-JD", {"jieba_userdict": True}, parent=baseline).index_key() != baseline.index_key()


def test_index_key_includes_corpus_fingerprint() -> None:
    baseline = ArmConfig(arm_id="A-BASE", role="baseline")
    assert baseline.index_key("v1") != baseline.index_key("v2")


# --------------------------------------------------------------------------- #
# 真实矩阵文件
# --------------------------------------------------------------------------- #
def test_shipped_matrix_validates_clean() -> None:
    """仓库里那份 YAML 必须一条违规都没有 —— 它是 runner 的直接输入。"""
    matrix = load_matrix(MATRIX_YAML)
    assert matrix.validate() == []
    # 精简版只保留检索侧 Phase A（零 LLM）；Phase B 生成侧已移除
    assert matrix.phases() == ("A",)
    assert 4 <= len(matrix.all_arms) <= 6


def test_shipped_matrix_arm_ids_unique() -> None:
    matrix = load_matrix(MATRIX_YAML)
    ids = [arm.arm_id for arm in matrix.all_arms]
    assert len(ids) == len(set(ids))


def test_phase_split_is_zero_cost_versus_paid() -> None:
    """全矩阵必须零 LLM：任何一臂带上 prompt 就意味着要花钱调生成，与
    「零 LLM 可复现评测」的北极星冲突。这条守住的就是那道成本闸门。"""
    matrix = load_matrix(MATRIX_YAML)
    assert all(arm.prompt is None for arm in matrix.all_arms)
    assert matrix.phases() == ("A",)


def test_temperature_is_pinned_to_zero_everywhere() -> None:
    """温度是被控制的常量。任何一臂改了它，单变量原则从第一步就破。"""
    matrix = load_matrix(MATRIX_YAML)
    assert {arm.temperature for arm in matrix.all_arms} == {0.0}


def test_baseline_is_production_config_not_something_new() -> None:
    """基线必须等于 M2 已交付配置，否则"相比基线提升 X"这句话失去意义。"""
    baseline = load_matrix(MATRIX_YAML).baseline
    assert baseline.embed_backend == "fastembed"
    assert baseline.embed_model == "BAAI/bge-small-zh-v1.5"
    assert baseline.fusion == "weighted"
    assert (baseline.bm25_weight, baseline.vector_weight) == (0.4, 0.6)
    assert baseline.reranker is None
    assert baseline.chunk_mode == "heading"


def test_index_grouping_shares_one_index_across_query_side_arms() -> None:
    """4 条臂全是查询侧变量（fusion / reranker 都不改变索引），应当共用同一份库。
    若分组数逼近臂数，说明 index_key 收了不该收的字段。"""
    matrix = load_matrix(MATRIX_YAML)
    groups = matrix.index_groups()
    assert len(groups) < len(matrix.all_arms) / 2
    biggest = max(groups.values(), key=len)
    assert {arm.arm_id for arm in biggest} >= {
        "A-BASE",
        "A-BM25",
        "A-VECTOR",
        "A-RRF",
    }


def test_matrix_requires_at_least_one_arm() -> None:
    with pytest.raises(ExperimentError, match="一条对照臂都没有"):
        build_matrix({"baseline": {"arm_id": "A-BASE"}, "arms": []})


def test_matrix_rejects_non_baseline_primary() -> None:
    with pytest.raises(ExperimentError, match="role 必须是 baseline"):
        Matrix(baseline=ArmConfig(arm_id="X"), arms=())
