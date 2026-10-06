"""M3 · T3-3 单测：消融 runner 的判分口径、参数漂移核对、预算闸门。

真跑（建库 + 检索）由 ``scripts/run_ablation.py`` 承担；本文件只钉住
"runner 会不会把结论算错"的那几处纯逻辑 —— 它们出错时报表看起来完全正常。
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.ablation import (  # noqa: E402
    INDEX_SECONDS_PER_1K_DOCS,
    QUERY_SECONDS,
    REFUSAL_CORRECT_KEY,
    RERANK_LOAD_SECONDS,
    RERANK_SECONDS_PER_QUERY,
    AblationError,
    ArmGenerator,
    ArmOutcome,
    CostBudget,
    CostLimitExceeded,
    GoldenQuestion,
    apply_arm_env,
    apply_arm_env_reset,
    compare_arms,
    doc_key,
    embed_dim_for_model,
    estimate_seconds,
    evaluate_arm,
    load_golden_set,
    run_matrix,
    significance_family,
    stratified_limit,
    summarize,
    verify_arm_settings,
)
from evaluation.experiment import BASELINE_DEFAULTS, ArmConfig, ExperimentError, Matrix  # noqa: E402
from evaluation.generation_metrics import GenerationScore  # noqa: E402

pytestmark = pytest.mark.unit


def _baseline(**overrides: Any) -> ArmConfig:
    return ArmConfig(arm_id=overrides.pop("arm_id", "A-BASE"), role="baseline", **overrides)


def _arm(**overrides: Any) -> ArmConfig:
    """消融臂（role=ablation）—— 忘了用它会因为 role=baseline 被 compare_arms 跳过。"""
    return ArmConfig(arm_id=overrides.pop("arm_id"), role="ablation", **overrides)


def _question(
    qid: str,
    *,
    expected: tuple[str, ...],
    qtype: str = "factual",
    ground_truth: tuple[str, ...] = (),
) -> GoldenQuestion:
    return GoldenQuestion(
        qid=qid,
        track="A",
        qtype=qtype,
        query=f"{qid} 的问题",
        expected_doc_ids=expected,
        ground_truth=ground_truth,
    )


def _no_loader() -> Any:
    """元数据回填桩：判分只用 document_id，不需要正文。"""
    return lambda ids: {}


def _tiny_corpus(tmp_path: Path, *, questions: int = 2) -> tuple[Path, Path]:
    """一个够跑通 runner 前置检查的最小语料 + 题集（不建库，所以毫秒级）。"""
    fixtures = tmp_path / "fx"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "doc-a.md").write_text("# 标题\n\n六类线的弯曲半径为四倍。", encoding="utf-8")
    rows = [
        {
            "id": f"q{index}",
            "track": "A",
            "type": "factual",
            "query": f"q{index} 的问题",
            "expected_doc_ids": ["A"],
            "ground_truth": ["四倍"],
        }
        for index in range(1, questions + 1)
    ]
    return fixtures, _write_jsonl(tmp_path / "golden.jsonl", rows)


# --------------------------------------------------------------------------- #
# 文档键与维度
# --------------------------------------------------------------------------- #
def test_doc_key_matches_index_naming() -> None:
    """索引侧叫 ``doc-cmrc_TRAIN_837``，金标集里叫 ``TRAIN_837`` —— 键必须对齐。"""
    assert doc_key("doc-cmrc_TRAIN_837") == "TRAIN_837"
    assert doc_key("doc-cmrc_DEV_1003") == "DEV_1003"
    assert doc_key("doc-anfangjiankong") == "anfangjiankong", "轨道 B：stem 即键"


def test_embed_dim_is_a_closed_table() -> None:
    assert embed_dim_for_model("BAAI/bge-small-zh-v1.5") == 512
    assert embed_dim_for_model("BAAI/bge-base-zh-v1.5") == 768
    assert embed_dim_for_model("BAAI/bge-large-zh-v1.5") == 1024
    with pytest.raises(AblationError, match="未知嵌入模型"):
        embed_dim_for_model("BAAI/bge-huge-zh-v9.9")


# --------------------------------------------------------------------------- #
# 金标集
# --------------------------------------------------------------------------- #
def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return path


def test_load_golden_set_reads_all_fields(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "g.jsonl",
        [
            {
                "id": "A-factual-001",
                "track": "A",
                "type": "factual",
                "query": " 六类线的弯曲半径是多少？ ",
                "expected_doc_ids": ["TRAIN_837"],
                "expected_document": "cmrc_TRAIN_837.md",
                "heldout_document": None,
                "ground_truth": ["不大于 30mm", "约为线径的四倍"],
            },
            {
                "id": "A-refusal-001",
                "track": "A",
                "type": "refusal",
                "query": "库里没有的问题",
                "expected_doc_ids": [],
                "expected_document": None,
                "heldout_document": "cmrc_TRAIN_9999.md",
            },
        ],
    )
    items = load_golden_set(path)
    assert [item.qid for item in items] == ["A-factual-001", "A-refusal-001"]
    assert items[0].query == "六类线的弯曲半径是多少？", "题干要 strip"
    assert items[0].expected_doc_ids == ("TRAIN_837",)
    assert items[0].reference == "不大于 30mm；约为线径的四倍", "Phase B 的 context_recall 吃这个"
    assert items[1].reference == "", "没标注的题不给参考答案，评分器会把该列记 None"
    assert items[1].is_refusal and items[1].expected_doc_ids == ()
    assert not items[0].is_refusal


def test_track_a_300_dataset_invariants() -> None:
    """轨道 A 300 题集（D14 选项①）的不变量。数据集也是代码：它悄悄退化时，
    整张消融表会看起来正常而结论全错，所以这里直接钉住真实文件。"""
    path = PROJECT_ROOT / "evaluation/dataset/golden_a_cmrc300.jsonl"
    if not path.is_file():
        pytest.skip("300 题集未生成（scripts/build_golden_set.py --factual 165 --term 45 --refusal 90）")
    items = load_golden_set(path)

    assert len(items) == 300
    counts = {qtype: sum(1 for item in items if item.qtype == qtype) for qtype in ("factual", "term", "refusal")}
    assert counts == {"factual": 165, "term": 45, "refusal": 90}, "配比按 55/15/30 等比放大"
    assert len({item.qid for item in items}) == 300
    assert len({item.query for item in items}) == 300, "题干不能重复"
    refusals = [item for item in items if item.is_refusal]
    assert len(refusals) == 90 and all(not item.expected_doc_ids for item in refusals)
    # Phase B 的 context_recall 靠 reference；非拒答题没有 gold 会让那一列整臂变 None
    assert all(item.reference for item in items if not item.is_refusal)


def test_reference_tolerates_a_bare_string_ground_truth(tmp_path: Path) -> None:
    """CMRC 的 gold 是数组，自建轨道 B 手写时可能直接给一个字符串 —— 两种都得认，
    而且不能把字符串按字符拆开。"""
    path = _write_jsonl(
        tmp_path / "g.jsonl",
        [{"id": "B-term-001", "track": "B", "type": "term", "query": "什么是 PoE", "ground_truth": "以太网供电"}],
    )

    assert load_golden_set(path)[0].reference == "以太网供电"


@pytest.mark.parametrize(
    "row",
    [
        {"id": "x", "track": "A", "type": "factual"},
        {"track": "A", "type": "factual", "query": "q"},
    ],
)
def test_load_golden_set_rejects_incomplete_rows(tmp_path: Path, row: dict) -> None:
    path = _write_jsonl(tmp_path / "g.jsonl", [row])
    with pytest.raises(AblationError, match="缺字段"):
        load_golden_set(path)


def test_load_golden_set_rejects_duplicate_ids_and_empty_file(tmp_path: Path) -> None:
    row = {
        "id": "x",
        "track": "A",
        "type": "factual",
        "query": "q",
        "expected_doc_ids": ["D"],
    }
    with pytest.raises(AblationError, match="重复"):
        load_golden_set(_write_jsonl(tmp_path / "dup.jsonl", [row, dict(row)]))
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(AblationError, match="为空"):
        load_golden_set(empty)


# --------------------------------------------------------------------------- #
# 参数落地与漂移
# --------------------------------------------------------------------------- #
def test_apply_arm_env_derives_dim_and_userdict() -> None:
    arm = _baseline(arm_id="A-DICT", jieba_userdict=True, chunk_mode="semantic")
    try:
        written = apply_arm_env(arm)
        assert written["EMBEDDING_DIM"] == "512", "维度从模型表推导，臂上不给 dim 旋钮"
        assert written["CHUNK_MODE"] == "semantic"
        assert written["JIEBA_USERDICT"].endswith("m3_terms.txt")
        assert os.environ["EMBEDDING_BACKEND"] == "fastembed", "env 真的被写进去了"
    finally:
        apply_arm_env_reset()
    assert "EMBEDDING_BACKEND" not in os.environ, "复位必须干净"


def test_query_side_params_never_touch_env() -> None:
    """fusion/rrf_k/reranker 走构造器，不写 env —— 写了就会有第二份可能不一致的真相。"""
    arm = _arm(arm_id="A-E3", fusion="rrf", rrf_k=20, reranker="BAAI/bge-reranker-base")
    try:
        written = apply_arm_env(arm)
    finally:
        apply_arm_env_reset()
    assert not {"HYBRID_FUSION", "RRF_K", "RERANKER_MODEL"} & set(written)


def _settings_like(arm: ArmConfig, **overrides: Any) -> SimpleNamespace:
    values = {
        "embedding_backend": arm.embed_backend,
        "embedding_model_name": arm.embed_model,
        "embedding_dim": embed_dim_for_model(arm.embed_model),
        "chunk_mode": arm.chunk_mode,
        "chunk_size": arm.chunk_size,
        "chunk_overlap": arm.chunk_overlap,
        "jieba_userdict": "",
    }
    return SimpleNamespace(**{**values, **overrides})


def test_verify_arm_settings_passes_and_catches_drift() -> None:
    """env 名字拼错 → 该臂其实跑的是基线。这道核对是唯一能发现它的地方。"""
    arm = _arm(arm_id="A-E2a-rrf", fusion="rrf")
    verify_arm_settings(arm, _settings_like(arm))
    with pytest.raises(AblationError, match="参数漂移"):
        verify_arm_settings(arm, _settings_like(arm, embedding_model_name="BAAI/bge-base-zh-v1.5"))
    with pytest.raises(AblationError, match="A-E2a-rrf"):
        verify_arm_settings(arm, _settings_like(arm, chunk_size=256))


# --------------------------------------------------------------------------- #
# 预算闸门
# --------------------------------------------------------------------------- #
def test_estimate_seconds_arithmetic() -> None:
    """闸门要的是"常量 × 题数"这个算式本身。数值一律取实测标定，别手写回旧估计。"""
    baseline = _baseline()
    one_thousand_docs = estimate_seconds([baseline], docs=1000, questions=100)
    assert one_thousand_docs == pytest.approx(
        INDEX_SECONDS_PER_1K_DOCS["fastembed"] + 100 * QUERY_SECONDS
    )
    torch_arm = _baseline(embed_backend="torch")
    assert estimate_seconds([torch_arm], docs=1000, questions=0) == pytest.approx(
        INDEX_SECONDS_PER_1K_DOCS["torch"]
    )
    rerank = _baseline(arm_id="A-E3", reranker="BAAI/bge-reranker-base")
    assert estimate_seconds([rerank], docs=1000, questions=100) == pytest.approx(
        INDEX_SECONDS_PER_1K_DOCS["fastembed"]
        + RERANK_LOAD_SECONDS
        + 100 * (QUERY_SECONDS + RERANK_SECONDS_PER_QUERY["BAAI/bge-reranker-base"])
    )


def test_cost_constants_are_the_measured_track_a_ones() -> None:
    """轨道 A 15 臂全量实跑（2026-09-19）标定的四个数。它们决定"这趟要不要 3 小时"，
    改回拍脑袋的估计会让预算闸门系统性偏低 —— 所以钉在这里，而不是只写在注释里。"""
    assert INDEX_SECONDS_PER_1K_DOCS["fastembed"] == pytest.approx(55.0, abs=1.0)
    assert INDEX_SECONDS_PER_1K_DOCS["torch"] == pytest.approx(265.0, abs=5.0)
    assert RERANK_SECONDS_PER_QUERY["BAAI/bge-reranker-base"] == pytest.approx(11.2, abs=0.5)
    assert RERANK_SECONDS_PER_QUERY["BAAI/bge-reranker-v2-m3"] > (
        RERANK_SECONDS_PER_QUERY["BAAI/bge-reranker-base"] * 2
    ), "v2-m3 实测是 base 的 2.8 倍（p50 31.1s vs 11.2s）"
    assert RERANK_LOAD_SECONDS == pytest.approx(330.0, abs=10.0)


def test_estimate_seconds_rejects_unknown_reranker() -> None:
    arm = _baseline(arm_id="A-E3-x", reranker="some/unknown-reranker")
    with pytest.raises(AblationError, match="未知重排模型"):
        estimate_seconds([arm], docs=10, questions=10)


def _phase_b_matrix(*arms: ArmConfig) -> Matrix:
    baseline = _baseline(arm_id="B-BASE", phase="B", prompt="answer_basic")
    return Matrix(baseline=baseline, arms=arms)


def _stub_settings(*, configured: bool) -> SimpleNamespace:
    return SimpleNamespace(llm_configured=configured)


def _stub_llm_group(monkeypatch: Any) -> list[str]:
    """把建库/跑臂那一层整个换掉：闸门测试要验的是"根本没走到那一步"。"""
    from evaluation import ablation as ablation_module

    calls: list[str] = []
    monkeypatch.setattr(
        ablation_module, "_run_index_group", lambda key, arms, **kwargs: calls.append(key) or {}
    )
    return calls


def test_phase_b_refuses_without_api_key_before_reading_data(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """缺 Key 要在读数据集**之前**拒。一个要花钱的跑批先烧掉几十分钟索引才发现没 Key，
    是最贵的一种失败。"""
    from evaluation import ablation as ablation_module

    reads: list[int] = []
    monkeypatch.setattr(ablation_module, "_fresh_settings", lambda: _stub_settings(configured=False))
    monkeypatch.setattr(
        ablation_module, "load_golden_set", lambda *a, **k: reads.append(1) or []
    )
    with pytest.raises(AblationError, match="LLM_API_KEY"):
        run_matrix(
            _phase_b_matrix(),
            dataset=Path("unused.jsonl"),
            fixtures=tmp_path,
            out_dir=tmp_path / "o",
            phase="B",
        )
    assert reads == [], "缺件检查必须排在读数据集前面"


@pytest.mark.parametrize(
    ("overrides", "expect"),
    [
        ({"prompt": "answer_weird"}, "prompt 版本"),
        ({"prompt": "answer_basic", "top_k": 20}, "上限"),
    ],
)
def test_phase_b_gate_checks_prompt_role_and_material_cap(
    monkeypatch: Any, tmp_path: Path, overrides: dict, expect: str
) -> None:
    """未登记的 prompt 版本与超过【材料10】的臂都不该进入花钱的路径。"""
    from evaluation import ablation as ablation_module

    monkeypatch.setattr(ablation_module, "_fresh_settings", lambda: _stub_settings(configured=True))
    arm = _arm(arm_id="B-E9", phase="B", **overrides)
    with pytest.raises(AblationError, match=expect):
        run_matrix(
            _phase_b_matrix(arm),
            dataset=Path("unused.jsonl"),
            fixtures=tmp_path,
            out_dir=tmp_path / "o",
            phase="B",
        )


def test_phase_b_preflight_rejects_projected_cost(monkeypatch: Any, tmp_path: Path) -> None:
    """单价 × 题数 × 臂数超闸门 → 启动前就拒，一臂都不该开跑（§5「先 smoke 再全量」）。"""
    from evaluation import ablation as ablation_module

    monkeypatch.setattr(ablation_module, "_fresh_settings", lambda: _stub_settings(configured=True))
    calls = _stub_llm_group(monkeypatch)
    fixtures, dataset = _tiny_corpus(tmp_path)

    with pytest.raises(AblationError, match="预估成本"):
        run_matrix(
            _phase_b_matrix(_phase_b_arm()),
            dataset=dataset,
            fixtures=fixtures,
            out_dir=tmp_path / "o",
            phase="B",
            unit_cost_cny=1.0,
            max_cost_cny=3.0,
        )
    assert calls == []


def test_phase_b_without_unit_price_still_runs(monkeypatch: Any, tmp_path: Path) -> None:
    """单价没标定时不能拿"估不出来"当理由拒跑（smoke 自己就是第一次跑）；只警告。"""
    from evaluation import ablation as ablation_module

    monkeypatch.setattr(ablation_module, "_fresh_settings", lambda: _stub_settings(configured=True))
    monkeypatch.setattr(ablation_module, "PHASE_B_UNIT_COST_CNY", None)
    calls = _stub_llm_group(monkeypatch)
    fixtures, dataset = _tiny_corpus(tmp_path)

    run_matrix(
        _phase_b_matrix(),
        dataset=dataset,
        fixtures=fixtures,
        out_dir=tmp_path / "o",
        phase="B",
    )
    assert calls, "没单价也要放行，逐题累计的硬闸兜底"


def test_budget_breach_writes_partial_report_and_stops(monkeypatch: Any, tmp_path: Path) -> None:
    """烧穿闸门：已跑完的臂要留在盘上，同时整趟非 0 退出、汇总里写清中止原因。"""
    from evaluation import ablation as ablation_module

    monkeypatch.setattr(ablation_module, "_fresh_settings", lambda: _stub_settings(configured=True))
    fixtures, dataset = _tiny_corpus(tmp_path)
    out = tmp_path / "o"

    def _boom(key: str, arms: Any, **kwargs: Any) -> dict[str, ArmOutcome]:
        raise ablation_module.CostLimitExceeded(f"闸门：跑到 {key} 已花超")

    monkeypatch.setattr(ablation_module, "_run_index_group", _boom)
    with pytest.raises(ablation_module.CostLimitExceeded, match="闸门"):
        run_matrix(
            _phase_b_matrix(),
            dataset=dataset,
            fixtures=fixtures,
            out_dir=out,
            phase="B",
        )
    summary = json.loads((out / "ablation_summary.json").read_text(encoding="utf-8"))
    assert summary["cost_gate"]["aborted"], "中止原因必须落在报表里，不然读回端会当成完整一趟"
    assert summary["cost_gate"]["max_cost_cny"] == pytest.approx(30.0)


def test_cli_survives_a_gbk_console(monkeypatch: Any) -> None:
    """跑成功了、却在最后 print 单价那一步 UnicodeEncodeError 退码 1 —— 本机控制台默认
    GBK，而文案里有「¥」。这类"评测其实成了"的收尾事故最难查，所以直接钉住。"""
    import io

    from evaluation import ablation as ablation_module

    buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buffer, encoding="gbk", errors="strict"))
    monkeypatch.setattr(
        ablation_module,
        "run_matrix",
        lambda *args, **kwargs: {"phase": "B", "arms": {"B-BASE": {"cost": {"unit_cost_cny": 0.042}}}},
    )

    code = ablation_module.main(["--phase", "B", "--out", "unused"])
    sys.stdout.flush()

    assert code == 0
    assert "0.0420" in buffer.getvalue().decode("utf-8")


def test_run_matrix_preflights_the_userdict_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A-DICT 缺词典要在**建库之前**就拒，不能跑到那一臂才炸（那时已烧掉几十分钟）。"""
    from evaluation import ablation as ablation_module

    fixtures = tmp_path / "fx"
    fixtures.mkdir()
    (fixtures / "doc-a.md").write_text("# 标题\n\n六类线的弯曲半径为四倍。", encoding="utf-8")
    dataset = _write_jsonl(
        tmp_path / "g.jsonl",
        [{"id": "x", "track": "A", "type": "factual", "query": "弯曲半径", "expected_doc_ids": ["a"]}],
    )
    monkeypatch.setattr(ablation_module, "_userdict_path", lambda: str(tmp_path / "没有这个词典.txt"))
    arm = _arm(arm_id="A-DICT", jieba_userdict=True)
    matrix = Matrix(baseline=_baseline(), arms=(arm,))
    with pytest.raises(AblationError, match="词典"):
        run_matrix(
            matrix,
            dataset=dataset,
            fixtures=fixtures,
            out_dir=tmp_path / "out",
            only_arms=["A-DICT"],
        )


def test_multiplier_requires_exact_division() -> None:
    """fetch_k 不整除 top_k 时实际候选池会和臂声明不一致 → 拒。"""
    from evaluation.ablation import _multiplier

    assert _multiplier(_arm(arm_id="x", fetch_k=20, top_k=5)) == 4
    assert _multiplier(_arm(arm_id="y", fetch_k=50, top_k=5)) == 10
    with pytest.raises(AblationError, match="整除"):
        _multiplier(_arm(arm_id="z", fetch_k=15, top_k=4))


def test_dict_arms_dropped_in_sweep_but_not_when_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """整批扫 Phase A 缺词典 → 只跳那一臂；显式 --arm A-DICT → 拒跑整趟。"""
    from evaluation import ablation as ablation_module

    baseline = _baseline()
    dict_arm = _arm(arm_id="A-DICT", jieba_userdict=True)
    monkeypatch.setattr(ablation_module, "_userdict_path", lambda: str(tmp_path / "无.txt"))
    assert ablation_module._drop_unrunnable_dict_arms([baseline, dict_arm], []) == [baseline]
    with pytest.raises(AblationError, match="显式点名"):
        ablation_module._drop_unrunnable_dict_arms([baseline, dict_arm], ["A-DICT"])
    # 词典真的存在时，两条臂都该留下
    monkeypatch.setattr(ablation_module, "_userdict_path", lambda: str(Path(__file__)))
    assert ablation_module._drop_unrunnable_dict_arms([baseline, dict_arm], []) == [
        baseline,
        dict_arm,
    ]


# --------------------------------------------------------------------------- #
# 单臂判分
# --------------------------------------------------------------------------- #
class StubRetriever:
    """按题目返回固定命中的检索器桩（document_id 用真实命名规则）。"""

    def __init__(self, hits_by_query: dict[str, list[str]]) -> None:
        self._hits_by_query = hits_by_query
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int, *, metadata_loader: Any = None) -> list[Any]:
        self.calls.append((query, top_k))
        return [
            SimpleNamespace(document_id=f"doc-cmrc_{key}") for key in self._hits_by_query[query]
        ]


def test_evaluate_arm_metric_math() -> None:
    """拒答题不进均值；第 2 名命中 → MRR=0.5、nDCG=1/log2(3)。"""
    questions = [
        _question("q1", expected=("A",)),
        _question("q2", expected=(), qtype="refusal"),
    ]
    retriever = StubRetriever(
        {"q1 的问题": ["X", "A", "Y"], "q2 的问题": ["Z"]}
    )
    arm = _baseline(top_k=3)
    outcome = evaluate_arm(arm, questions, retriever, _no_loader())

    assert outcome.metrics["recall_at_3"] == pytest.approx(1.0), "只有 q1 计分"
    assert outcome.metrics["mrr_at_3"] == pytest.approx(0.5)
    assert outcome.metrics["ndcg_at_3"] == pytest.approx(1 / math.log2(3))
    assert outcome.metrics["hit_rate_at_3"] == pytest.approx(1.0)
    assert outcome.metrics["questions_scored"] == 1.0
    assert outcome.metrics["questions_total"] == 2.0
    assert outcome.per_question[1]["recall_at_k"] is None, "拒答题必须记 None 而不是 0"
    assert outcome.per_question[0]["retrieved_doc_ids"] == ["X", "A", "Y"]
    assert outcome.cost["cost_cny"] == 0.0 and outcome.cost["e2e_p95_ms"] is None
    assert set(retriever.calls) == {("q1 的问题", 3), ("q2 的问题", 3)}


def test_evaluate_arm_latency_percentiles() -> None:
    questions = [_question(f"q{index}", expected=("A",)) for index in range(20)]
    retriever = StubRetriever({f"q{index} 的问题": ["A"] for index in range(20)})
    outcome = evaluate_arm(_baseline(top_k=1), questions, retriever, _no_loader())
    assert outcome.cost["retrieval_p50_ms"] >= 0.0
    assert outcome.cost["retrieval_p95_ms"] >= outcome.cost["retrieval_p50_ms"]


def test_duplicate_document_slots_cannot_inflate_ndcg() -> None:
    """长 passage 切成多 chunk → 同一篇文档可能占两个槽。文档粒度判分必须先保序去重，
    否则 nDCG 会把同一篇的增益计两次，算出 >1 的分数（实测漏网时最高 1.63）。"""
    questions = [_question("q1", expected=("A",))]
    retriever = StubRetriever({"q1 的问题": ["A", "B", "A", "C", "D"]})
    outcome = evaluate_arm(_arm(arm_id="x", top_k=5), questions, retriever, _no_loader())
    row = outcome.per_question[0]

    assert row["retrieved_chunk_doc_ids"] == ["A", "B", "A", "C", "D"], "原始 chunk 序要留着可审计"
    assert row["retrieved_doc_ids"] == ["A", "B", "C", "D"], "去重后必须保序"
    assert outcome.metrics["ndcg_at_5"] == pytest.approx(1.0), "首命中的文档级 nDCG 就是 1，不能更多"
    assert outcome.metrics["recall_at_5"] == pytest.approx(1.0)
    assert outcome.metrics["mrr_at_5"] == pytest.approx(1.0)


def test_by_type_breakdown_is_reported() -> None:
    """聚合均值会抹平题型分化（术语题 nDCG 明显低于事实题），必须分题型落盘。"""
    questions = [
        _question("q1", expected=("A",)),
        _question("q2", expected=("A",)),
        _question("q3", expected=(), qtype="refusal"),
    ]
    retriever = StubRetriever({"q1 的问题": ["A"], "q2 的问题": ["B"], "q3 的问题": ["C"]})
    outcome = evaluate_arm(_arm(arm_id="x", top_k=1), questions, retriever, _no_loader())
    assert outcome.by_type["factual"] == {
        "n": 2,
        "scored": 2,
        "recall_at_1": pytest.approx(0.5),
        "mrr_at_1": pytest.approx(0.5),
        "ndcg_at_1": pytest.approx(0.5),
    }
    assert outcome.by_type["refusal"]["scored"] == 0
    assert outcome.by_type["refusal"]["recall_at_1"] is None


# --------------------------------------------------------------------------- #
# Phase B：生成通路接线
# --------------------------------------------------------------------------- #
class StubAnswerer:
    """假 :class:`rag.answer.RagAnswerer`：只认注入的 search 闭包，其余字段照实返回。"""

    def __init__(
        self,
        search: Any,
        *,
        prompt: str = "answer_basic",
        top_k: int = 5,
        answer: str = "四倍。【材料1】",
        refused: bool = False,
        cost: float = 0.01,
    ) -> None:
        self._search = search
        self._prompt = prompt
        self._top_k = top_k
        self._answer = answer
        self._refused = refused
        self._cost = cost

    def answer(self, question: str) -> Any:
        hits = self._search(question, self._top_k)
        return SimpleNamespace(
            question=question,
            answer=self._answer,
            prompt=self._prompt,
            contexts=hits,
            citations=[1],
            valid_citations=[1],
            invalid_citations=[],
            refused=self._refused,
            usage=SimpleNamespace(cost=self._cost, token_in=900, token_out=120),
            retrieval_ms=4,
            latency_ms=1400,
            citation_rate=None if self._refused else 1.0,
        )


class StubScorer:
    """假 :class:`evaluation.generation_metrics.GenerationScorer`，记下它看到的那批材料。"""

    def __init__(self, *, cost: float = 0.004, **metrics: float | None) -> None:
        self._cost = cost
        self._metrics = {"faithfulness": 0.8, "context_precision": 0.5,
                         "answer_relevancy": 0.9, "context_recall": 0.5}
        self._metrics.update(metrics)
        self.seen: list[dict[str, Any]] = []

    def score(self, **kwargs: Any) -> GenerationScore:
        self.seen.append(kwargs)
        refused = kwargs["refused"]
        return GenerationScore(
            metrics={name: (None if refused else value) for name, value in self._metrics.items()},
            refusal_correct=(refused == kwargs["expected_refusal"]),
            hallucination=None if refused else round(1.0 - float(self._metrics["faithfulness"]), 4),
            cost_cny=self._cost,
        )


def _phase_b_arm(**overrides: Any) -> ArmConfig:
    return _arm(arm_id="B-E4-cot", phase="B", prompt="answer_cot", **overrides)


def _generator(
    arm: ArmConfig, retriever: Any, scorer: Any, *, refused: bool = False, **kwargs: Any
) -> ArmGenerator:
    return ArmGenerator(
        arm=arm,
        retriever=retriever,
        metadata_loader=_no_loader(),
        scorer=scorer,
        answerer_factory=lambda search: StubAnswerer(
            search, prompt=str(arm.prompt), top_k=arm.top_k, refused=refused
        ),
        **kwargs,
    )


def test_phase_b_retrieves_once_and_scores_those_very_hits() -> None:
    """★ 一题只检索一次，且四指标吃的材料**就是**检索指标判的那批 —— 分两次检索的话
    "检索变好"与"答案变好"就对不上，逐题 diff 会全是假差异。"""
    arm = _phase_b_arm()
    questions = [_question("q1", expected=("A",), ground_truth=("四倍",))]
    retriever = StubRetriever({"q1 的问题": ["A", "B"]})
    scorer = StubScorer()

    outcome = evaluate_arm(
        arm, questions, retriever, _no_loader(), generator=_generator(arm, retriever, scorer)
    )

    assert retriever.calls == [("q1 的问题", 5)], "只能检索一次"
    row = outcome.per_question[0]
    assert row["retrieved_doc_ids"] == ["A", "B"]
    assert [hit.document_id for hit in scorer.seen[0]["materials"]] == ["doc-cmrc_A", "doc-cmrc_B"]
    assert scorer.seen[0]["reference"] == "四倍", "参考答案要喂给 context_recall"
    assert row["ndcg_at_k"] == pytest.approx(1.0)
    assert row["e2e_ms"] == pytest.approx(1400.0)
    assert row["latency_ms"] == pytest.approx(4.0), "检索延迟与端到端延迟分开记"


def test_phase_b_metrics_and_cost_roll_up() -> None:
    arm = _phase_b_arm()
    questions = [_question("q1", expected=("A",)), _question("q2", expected=("B",))]
    retriever = StubRetriever({"q1 的问题": ["A"], "q2 的问题": ["B"]})
    outcome = evaluate_arm(
        arm,
        questions,
        retriever,
        _no_loader(),
        generator=_generator(arm, retriever, StubScorer(cost=0.004)),
    )

    assert outcome.metrics["faithfulness"] == pytest.approx(0.8)
    assert outcome.metrics["hallucination_rate"] == pytest.approx(0.2)
    assert outcome.metrics["refusal_accuracy"] == pytest.approx(1.0), "两题都不该拒答，也没拒"
    assert outcome.metrics["citation_rate"] == pytest.approx(1.0)
    assert outcome.cost["cost_cny"] == pytest.approx(0.028), "生成 + judge 都要计"
    assert outcome.cost["unit_cost_cny"] == pytest.approx(0.014), "smoke 打印的就是它"
    assert outcome.cost["e2e_p95_ms"] == pytest.approx(1400.0)
    assert outcome.cost["avg_tokens_in"] == 900
    assert outcome.by_type["factual"]["faithfulness"] == pytest.approx(0.8), "分题型也要带生成列"


def test_phase_b_refusal_scores_only_the_binary_column() -> None:
    """拒答题没有实质答案 → 四个连续指标全 None，只进"拒答是否正确"那一列。
    错误拒答若被当成 0 分混进 faithfulness 均值，会把幻觉率算歪。"""
    arm = _phase_b_arm()
    questions = [_question("q9", expected=(), qtype="refusal")]
    retriever = StubRetriever({"q9 的问题": ["Z"]})

    outcome = evaluate_arm(
        arm,
        questions,
        retriever,
        _no_loader(),
        generator=_generator(arm, retriever, StubScorer(), refused=True),
    )
    row = outcome.per_question[0]

    assert row["refused"] is True and row["refusal_correct"] is True
    assert row["faithfulness"] is None
    assert outcome.metrics["faithfulness"] is None, "没有可算的题就是 n/a，不是 0"
    assert outcome.metrics["refusal_accuracy"] == pytest.approx(1.0)
    assert outcome.metrics["answers_refused"] == 1.0


def test_budget_breach_stops_mid_arm() -> None:
    """逐题累计的硬闸：第二题就把整趟掐掉，不能等臂跑完再看。"""
    arm = _phase_b_arm()
    questions = [_question(f"q{i}", expected=("A",)) for i in range(3)]
    retriever = StubRetriever({f"q{i} 的问题": ["A"] for i in range(3)})
    budget = CostBudget(cap_cny=0.02, spent_cny=0.0)
    generator = _generator(arm, retriever, StubScorer(cost=0.004), budget=budget)

    with pytest.raises(CostLimitExceeded, match="成本闸门"):
        for question in questions:
            generator.run(question)
    assert budget.spent_cny == pytest.approx(0.028), "超线那题的钱也已经花出去了，要如实记"


def test_significance_family_differs_by_phase() -> None:
    """Phase B 的主判分换成生成侧两列 + 两个二值检查，不复用 Phase A 的排名族。"""
    assert significance_family("A") == (("ndcg_at_k", "mrr_at_k"), ("hit_at_k",))
    assert significance_family("B") == (
        ("faithfulness", "context_recall"),
        ("hit_at_k", "refusal_correct"),
    )
    with pytest.raises(AblationError, match="未知 phase"):
        significance_family("C")


def test_compare_arms_phase_b_uses_generation_family() -> None:
    baseline = _baseline(arm_id="B-BASE", phase="B", prompt="answer_basic")
    arm = _phase_b_arm()
    matrix = Matrix(baseline=baseline, arms=(arm,))
    outcomes = {
        "B-BASE": _outcome(
            baseline, [1.0, 0.0, 1.0], faithfulness=[0.5, 0.5, 1.0], context_recall=[0.5, 0.5, 0.5]
        ),
        "B-E4-cot": _outcome(
            arm, [1.0, 1.0, 1.0], faithfulness=[1.0, 0.5, 1.0], context_recall=[1.0, 0.5, 0.0]
        ),
    }

    names = [item.metric for item in compare_arms(outcomes, matrix, phase="B")]

    assert names == [
        "B-E4-cot:faithfulness",
        "B-E4-cot:context_recall",
        "B-E4-cot:hit_at_k",
        "B-E4-cot:refusal_correct",
    ]


def test_summarize_phase_b_table_shows_cost_per_question() -> None:
    baseline = _baseline(arm_id="B-BASE", phase="B", prompt="answer_basic")
    arm = _phase_b_arm()
    matrix = Matrix(baseline=baseline, arms=(arm,))
    outcomes = {
        "B-BASE": _outcome(
            baseline, [1.0, 0.0], faithfulness=[0.5, 0.5], context_recall=[0.5, 0.5]
        ),
        "B-E4-cot": _outcome(
            arm, [1.0, 1.0], faithfulness=[1.0, 0.5], context_recall=[1.0, 0.5]
        ),
    }
    for outcome in outcomes.values():
        outcome.metrics.update(
            {"faithfulness": 0.8, "context_recall": 0.5, "hallucination_rate": 0.2,
             "refusal_accuracy": 1.0, "citation_rate": 0.9}
        )
        outcome.cost = {"retrieval_p95_ms": 4.0, "e2e_p95_ms": 1400.0, "unit_cost_cny": 0.014}
    report = {
        "phase": "B", "questions": 2, "corpus_docs": 5, "index_groups": {"g": []},
        "estimated_seconds": 60, "cost_cny_total": 0.028,
        "cost_gate": {"max_cost_cny": 30.0, "unit_cost_cny": 0.014, "spent_cny": 0.028},
    }

    table = summarize(report, outcomes, compare_arms(outcomes, matrix, phase="B"), matrix)

    assert "# Phase B 生成侧消融表" in table
    assert "faithfulness | context_recall | 幻觉率 | 拒答准确 | 引用率" in table
    assert "Δfaithfulness" in table
    assert "0.8000" in table and "0.0140" in table
    assert "闸门内已花 ¥0.0280 / 上限 ¥30.0" in table
    assert "一题只检索一次" in table


# --------------------------------------------------------------------------- #
# 配对检验与摘要表
# --------------------------------------------------------------------------- #
def _outcome(
    arm: ArmConfig,
    recalls: list[float | None],
    *,
    faithfulness: list[float | None] | None = None,
    context_recall: list[float | None] | None = None,
    refused: list[bool] | None = None,
) -> ArmOutcome:
    """造一臂的配对观测。``faithfulness`` 等生成列只有 Phase B 的用例才传。"""
    outcome = ArmOutcome(arm=arm, metrics={"recall_at_5": 0.5})
    outcome.per_question = [
        {
            "qid": f"q{index}",
            "recall_at_k": value,
            "ndcg_at_k": value,
            "mrr_at_k": value,
            "hit_at_k": bool(value),
            "faithfulness": None if faithfulness is None else faithfulness[index],
            "context_recall": None if context_recall is None else context_recall[index],
            REFUSAL_CORRECT_KEY: True if refused is None else refused[index],
        }
        for index, value in enumerate(recalls)
    ]
    return outcome


def test_compare_arms_pairs_against_reference_and_skips_none() -> None:
    baseline = _baseline()
    arm = _arm(arm_id="A-E2a-rrf", fusion="rrf")
    matrix = Matrix(baseline=baseline, arms=(arm,))
    outcomes = {
        "A-BASE": _outcome(baseline, [1.0, 0.0, 1.0, None, 0.0]),
        "A-E2a-rrf": _outcome(arm, [1.0, 1.0, 0.0, None, 1.0]),
    }
    comparisons = compare_arms(outcomes, matrix)
    metrics = [item.metric for item in comparisons]
    assert metrics == ["A-E2a-rrf:ndcg_at_k", "A-E2a-rrf:mrr_at_k", "A-E2a-rrf:hit_at_k"]
    assert "A-E2a-rrf:recall_at_k" not in metrics, (
        "D13：Recall@5 贴顶，只作天花板检查，不进主判分"
    )
    ndcg = comparisons[0]
    assert ndcg.n_pairs == 4 and ndcg.n_used == 4, "None 那题必须从配对里剔掉"
    assert ndcg.p_raw != ndcg.p_raw, "不做显著性检验：p 必须是 NaN，不能给伪精确数值"
    assert ndcg.detail["rel_lift"] == pytest.approx(0.5), "0.5 → 0.75，相对基线 +50%"
    assert ndcg.mean_baseline == pytest.approx(2 / 4) and ndcg.mean_arm == pytest.approx(3 / 4)


def test_compare_arms_missing_reference_fails_loudly() -> None:
    """reference 指向不存在的臂 → 报错，不能悄悄退化成"跟基线比"。"""
    baseline = _baseline()
    arm = _arm(arm_id="A-E2a-rrf", fusion="rrf")
    matrix = Matrix(baseline=baseline, arms=(arm,), references={"A-E2a-rrf": "A-MISSING"})
    with pytest.raises(ExperimentError, match="不存在"):
        compare_arms({"A-E2a-rrf": _outcome(arm, [1.0])}, matrix)


def test_compare_arms_skips_failed_arms() -> None:
    """失败臂没有配对观测，必须整条跳过 —— 否则它会把显著性族的分母算歪。"""
    baseline = _baseline()
    arm = _arm(arm_id="A-E3", reranker="BAAI/bge-reranker-base")
    matrix = Matrix(baseline=baseline, arms=(arm,))
    failed = ArmOutcome(arm=arm, error="EmbeddingError: 权重下载失败")
    outcomes = {"A-BASE": _outcome(baseline, [1.0, 0.0]), "A-E3": failed}
    assert compare_arms(outcomes, matrix) == []


def test_summarize_renders_one_row_per_arm() -> None:
    baseline = _baseline()
    arm = _arm(arm_id="A-E2a-rrf", fusion="rrf")
    matrix = Matrix(baseline=baseline, arms=(arm,))
    outcomes = {
        "A-BASE": _outcome(baseline, [1.0, 0.0]),
        "A-E2a-rrf": _outcome(arm, [1.0, 1.0]),
    }
    outcomes["A-E2a-rrf"].cost = {"retrieval_p95_ms": 123.4}
    outcomes["A-E2a-rrf"].metrics = {
        "recall_at_5": 0.75,
        "ndcg_at_5": 0.5,
        "mrr_at_5": 0.6,
        "hit_rate_at_5": 1.0,
    }
    outcomes["A-E2a-rrf"].by_type = {
        "term": {"n": 1, "scored": 1, "ndcg_at_5": 0.2},
        "factual": {"n": 1, "scored": 1, "ndcg_at_5": 0.8},
    }
    failed = _baseline(arm_id="A-E3", reranker="BAAI/bge-reranker-base")
    outcomes["A-E3"] = ArmOutcome(arm=failed, error="EmbeddingError: 权重下载失败")
    report = {"phase": "A", "questions": 2, "corpus_docs": 5, "index_groups": {"x": []}, "estimated_seconds": 60, "cost_cny_total": 0.0}
    table = summarize(report, outcomes, compare_arms(outcomes, matrix), matrix)

    assert "| A-BASE | （参照基线） |" in table
    assert "fusion='rrf'" in table, "改动列要直接可读"
    assert "| 0.5000 | 0.6000 | 1.0000 | 0.7500 | 0.2000 | 0.8000 | 123 |" in table, (
        "D13 列序：nDCG/MRR 打头，Recall 退到天花板检查位，分题型 nDCG 要单列"
    )
    assert "| +0.5000 | +100.0% |" in table, "Δ 与相对基线的提升百分比必须并列露出"
    assert "ΔnDCG | 相对基线" in table
    assert "不做显著性检验" in table
    assert "Recall@k(天花板)" in table
    assert "❌ EmbeddingError" in table, "失败臂要在表里露出来，不能被静默丢弃"


def test_baseline_defaults_stay_the_single_source() -> None:
    """臂默认值 = M2 生产配置；这里钉住，防止有人改 BASELINE_DEFAULTS 让历史报表失效。"""
    arm = _baseline()
    assert BASELINE_DEFAULTS["fusion"] == "weighted"
    assert (arm.fusion, arm.chunk_mode, arm.top_k, arm.fetch_k) == ("weighted", "heading", 5, 20)
    assert arm.embed_model == BASELINE_DEFAULTS["embed_model"]


def _load_failure_script() -> Any:
    """按文件路径加载 ``scripts/analyze_ablation_failures.py``（scripts 不是包）。"""
    import importlib.util

    path = PROJECT_ROOT / "scripts" / "analyze_ablation_failures.py"
    spec = importlib.util.spec_from_file_location("analyze_ablation_failures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 先注册再 exec：模块级 dataclass 的 __module__ 解析要靠 sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failure_attribution_helpers() -> None:
    """报告「失败案例归因」一节的两类计数出自这个脚本，判据错了整段就是编的。

    只测两个纯函数 —— 它们出错时输出仍然「看起来正常」：
    * ``arm_rows`` 必须把拒答题（``hit_at_k is None``）挡在计分集之外。挡不住的话 F1 会把
      90 道拒答全算成「未召回」，失败率直接虚高到 45%；
    * ``_type_of`` 是「F1/F2 按题型」那两行的取值口径，qid 对不上必须落「未知」
      而不是报 KeyError —— 新旧报表 qid 本就不同源。
    """
    script = _load_failure_script()

    rows = [
        {"qid": "q1", "hit_at_k": 0.0},
        {"qid": "q2", "hit_at_k": 1.0},
        {"qid": "q3", "hit_at_k": None},  # 拒答题：不计检索分
        {"qid": "q4"},  # 连键都没有
    ]
    assert [r["qid"] for r in script.arm_rows({"per_question": rows})] == ["q1", "q2"]

    questions = {"q1": {"type": "term"}, "q2": {}}
    assert script._type_of({"qid": "q1"}, questions) == "term"
    assert script._type_of({"qid": "q2"}, questions) == "未知", "题集里没有 type 字段也要兜住"
    assert script._type_of({"qid": "q-missing"}, questions) == "未知", "qid 对不上不许抛异常"

    # F1/F2 判据本身（脚本内联，这里钉死口径，防止有人改成形容词）
    assert [r["qid"] for r in script.arm_rows({"per_question": rows}) if r["hit_at_k"] == 0.0] == ["q1"]
    assert [r["qid"] for r in script.arm_rows({"per_question": rows})
            if r["hit_at_k"] == 1.0 and (r.get("mrr_at_k") or 0) < 1.0] == ["q2"]


def test_smoke_limit_stratifies_by_question_type() -> None:
    """``--limit`` 必须按题型分层取样，而不是取前 N 条。

    前缀截断在真实题集上等价于「15 道全事实题」，两条真实代价：
    T5-2 的出口门槛要求 smoke 证明「拒答题命中模板」—— 那种 smoke 一道拒答题都遇不到；
    真发生拒答时 judge 一次都不调，纯事实题量出的 ¥/题 偏高，成本预检因此会
    把其实跑得完的一趟误拒在闸门外。
    """
    pool = (
        [_question(f"A-factual-{i:03d}", expected=("D1",)) for i in range(165)]
        + [_question(f"A-term-{i:03d}", expected=("D1",), qtype="term") for i in range(45)]
        + [_question(f"A-refusal-{i:03d}", expected=(), qtype="refusal") for i in range(90)]
    )

    def mix(rows: list[GoldenQuestion]) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[row.qtype] = out.get(row.qtype, 0) + 1
        return out

    picked = stratified_limit(pool, 15)
    assert len(picked) == 15
    # 占比 8.25 / 2.25 / 4.5 → 取整 8/2/4，余下的 1 个名额按最大余数给小数部分最大的拒答层
    assert mix(picked) == {"factual": 8, "term": 2, "refusal": 5}
    for qtype in ("factual", "term", "refusal"):
        want = [q.qid for q in pool if q.qtype == qtype][: mix(picked)[qtype]]
        assert [q.qid for q in picked if q.qtype == qtype] == want, "题型内要保持文件顺序"
    assert [q.qid for q in stratified_limit(pool, 15)] == [q.qid for q in picked], "同参数必得同一子集"

    # N 很小时候最大余数法不保证三层齐全（term 只占 15%，会被挤掉）——
    # 换来的是大 N 下占比保真。真正要紧的是拒答层从 N=2 起就必然在，smoke 要验的那条路径不会漏。
    assert mix(stratified_limit(pool, 3)) == {"factual": 2, "refusal": 1}
    assert mix(stratified_limit(pool, 2)) == {"factual": 1, "refusal": 1}
    assert "refusal" in mix(stratified_limit(pool, 5))

    assert stratified_limit(pool, 0) == pool
    assert len(stratified_limit(pool, 300)) == 300
    assert len(stratified_limit(pool, 999)) == 300, "limit 超过题数就用全量，不要报错"


def _load_corpus_a_script() -> Any:
    """按文件路径加载 ``scripts/build_corpus_a.py``（scripts 不是包）。"""
    import importlib.util

    path = PROJECT_ROOT / "scripts" / "build_corpus_a.py"
    spec = importlib.util.spec_from_file_location("build_corpus_a", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_corpus_a_refusal_audit_flags_any_variant_leak(tmp_path: Path) -> None:
    """方案 A 的代价条款：语料拉满后必然有拒答题重新可答，脏题要按**任一变体**判。

    只查主答案会漏掉一批（同一份数据实测 137 vs 141），拒答率的分母就是假的。
    """
    script = _load_corpus_a_script()
    fixtures = tmp_path / "fixtures_cmrc_a"
    fixtures.mkdir()
    texts = {"D1": "承压部件的检查口径见附表。", "D2": "另有一篇写锅炉的水循环。"}
    for doc, text in texts.items():
        (fixtures / f"cmrc_{doc}.md").write_text(text, encoding="utf-8")
    assert set(script.read_corpus_dir(fixtures)) == {"D1", "D2"}, "文件名前后缀要剥成 doc-key"

    rows = [
        {"id": "A-refusal-001", "track": "A", "type": "refusal", "query": "检查口径在哪？",
         "ground_truth": ["清洁版里没有的说法", "检查口径"], "heldout_document": "cmrc_D9.md",
         "answer_start": [-1, 7], "source": "cmrc2018:train"},
        {"id": "A-refusal-002", "track": "A", "type": "refusal", "query": "水循环有几种？",
         "ground_truth": ["自然循环与强制循环"], "heldout_document": "cmrc_D8.md",
         "answer_start": [-1], "source": "cmrc2018:train"},
        {"id": "A-factual-001", "track": "A", "type": "factual", "query": "附表讲什么？",
         "ground_truth": ["检查口径"], "heldout_document": None, "answer_start": [7],
         "source": "cmrc2018:train"},
    ]
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    items, qids = script.load_refusals(dataset)
    assert qids == ["A-refusal-001", "A-refusal-002"], "只审计拒答层，且顺序与 items 对齐"
    audit = script.build_audit(items, qids, texts, tool="test")
    assert (audit["refusal_total"], audit["dirty_count"], audit["clean_count"]) == (2, 1, 1)
    assert audit["dirty"][0]["qid"] == "A-refusal-001", "只有第二个变体命中也算脏"
    assert audit["dirty"][0]["hit_docs"] == ["D1"]


def test_corpus_a_refuses_to_silently_change_corpus(tmp_path: Path) -> None:
    """现行 1,000 篇目录必须逐字节对得上，对不上就拒绝落盘 —— "不能悄悄换语料"的机器版。"""
    script = _load_corpus_a_script()
    passages = {"D1": "承压部件的检查口径见附表。", "D2": "另有一篇写锅炉的水循环。"}
    base = tmp_path / "fixtures_cmrc"
    base.mkdir()
    (base / "cmrc_D1.md").write_text("被人改过的正文", encoding="utf-8")
    out = tmp_path / "fixtures_cmrc_a"
    assert script.emit_corpus(passages, set(passages), out, base) == 1
    assert not out.exists(), "冲突时一个字都不该写"

    (base / "cmrc_D1.md").write_text(passages["D1"], encoding="utf-8")
    assert script.emit_corpus(passages, set(passages), out, base) == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["cmrc_D1.md", "cmrc_D2.md"]
    assert script.emit_corpus(passages, set(passages), out, base) == 0, "重复跑要幂等"
