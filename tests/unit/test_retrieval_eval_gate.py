"""G2 门禁的参照组条款（F2-01）：参照组缺席时**不许**打绿。

缺陷形状：原先 `run_eval` / `render_markdown` 都用
`next(..., group_results[0])` 找参照组 0.4:0.6，找不到就**静默回落到第一组**，
于是 `--weights 1.0:0.0` 单组跑也会印「G2（0.4:0.6 top-3 = xx% 通过）」并退出码 0
—— 那个绿没有任何一次 0.4:0.6 的测量支撑。

这几条用例只验判据本身（不加载模型、不跑评测）：`build_g2_gate` 的三态、
CLI 的退出码 0/1/2、stdout/stderr 的措辞，以及"标签从数据取而不是写死"。
每条都配了正反两侧，防止判据恒真。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import retrieval_eval as re_eval  # noqa: E402
from evaluation.retrieval_eval import (  # noqa: E402
    G2_TOP3_THRESHOLD,
    build_g2_gate,
    main,
    render_markdown,
)


def _group(bm25: float, vector: float, top3: float) -> dict[str, Any]:
    """造一组"跑完了"的结果，只填判据真正会读的字段。"""
    return {
        "weights": {"bm25": bm25, "vector": vector},
        "top_k": 5,
        "total": 70,
        "top1_rate": top3,
        "top3_rate": top3,
        "hit5_rate": top3,
        "mrr": top3,
        "bm25_score_mean": 1.0,
        "vector_score_mean": 0.0,
        "details": [
            {
                "id": "q01",
                "type": "参数",
                "rank": 1,
                "hit_document": "zonghebuxian.md",
                "top_score": 1.0,
            }
        ],
    }


def _report(groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": "2026-10-04 00:00:00",
        "dataset": "evaluation/dataset/retrieval_eval_cmrc.jsonl",
        "dataset_size": 70,
        "fixtures": ["cmrc_1.md"],
        "embedding_model": "bge-small-zh-v1.5",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "groups": groups,
        "g2_gate": build_g2_gate(groups),
        "report_paths": {"json": "eval.json", "markdown": "eval.md"},
    }


# ---------- build_g2_gate：三态都要能翻 ----------


def test_reference_group_absent_is_not_green() -> None:
    """只有 1.0:0.0 一组 ⇒ 无法判定，且 passed 必须为 False（旧行为：拿它冒充参照组打绿）。"""
    gate = build_g2_gate([_group(1.0, 0.0, 1.0)])

    assert gate["evaluable"] is False
    assert gate["passed"] is False
    assert gate["reference_top3_rate"] is None
    assert "无法判定 G2" in gate["reason"]
    assert "参照组 0.4:0.6" in gate["reason"]
    assert gate["scanned_groups"] == ["1.0:0.0"]


def test_reference_group_present_uses_threshold() -> None:
    """反面对照：参照组在场时门槛照旧生效，别把修复写成"永远红"。"""
    at_threshold = build_g2_gate([_group(0.4, 0.6, G2_TOP3_THRESHOLD)])
    below_threshold = build_g2_gate([_group(0.4, 0.6, G2_TOP3_THRESHOLD - 0.01)])

    assert at_threshold["evaluable"] is True
    assert at_threshold["passed"] is True
    assert below_threshold["evaluable"] is True
    assert below_threshold["passed"] is False
    assert below_threshold["reference_top3_rate"] == pytest.approx(
        G2_TOP3_THRESHOLD - 0.01
    )


def test_reference_group_wins_over_first_group() -> None:
    """参照组不是第一组时也要认它：拿第一组的数判 G2 就是本条缺陷的另一半。"""
    groups = [_group(1.0, 0.0, 1.0), _group(0.4, 0.6, 0.10)]
    gate = build_g2_gate(groups)

    assert gate["evaluable"] is True
    assert gate["reference_top3_rate"] == 0.10
    assert gate["passed"] is False


# ---------- render_markdown：标签从数据取，措辞不骗人 ----------


def test_markdown_g2_label_is_read_from_gate_not_hardcoded() -> None:
    """桩里把参照组换成 0.5:0.5 —— 报告若写死 0.4:0.6 就会露馅。"""
    groups = [_group(0.5, 0.5, 1.0)]
    report = _report(groups)
    report["g2_gate"] = build_g2_gate(groups, reference_weights=(0.5, 0.5))
    markdown = render_markdown(report)

    assert "参照组 0.5:0.5" in markdown
    assert "0.4:0.6" not in markdown


def test_markdown_detail_section_does_not_call_it_reference() -> None:
    """参照组缺席时，明细那节必须明写"非参照组"，不能顶着"（参照组）"的标题。"""
    markdown = render_markdown(_report([_group(1.0, 0.0, 1.0)]))

    assert "非参照组" in markdown
    assert "（参照组 1.0:0.0）" not in markdown
    assert "无法判定 G2" in markdown


def test_markdown_detail_section_uses_reference_group_when_present() -> None:
    """反面对照：参照组在场时仍按它出明细，且不出现"非参照组"字样。"""
    groups = [_group(1.0, 0.0, 1.0), _group(0.4, 0.6, 0.95)]
    markdown = render_markdown(_report(groups))

    assert "逐条明细（参照组 0.4:0.6）" in markdown
    assert "非参照组" not in markdown
    assert "✅ 通过" in markdown


# ---------- main：退出码 0/1/2 ----------


@pytest.fixture()
def stub_run_eval(monkeypatch: pytest.MonkeyPatch):
    """把 run_eval 换成"直接返回造好的报告"，CLI 的判据路径照样真走。"""
    holder: dict[str, dict[str, Any]] = {}

    def _fake(**_kwargs: Any) -> dict[str, Any]:
        return holder["report"]

    monkeypatch.setattr(re_eval, "run_eval", _fake)
    return holder


def test_cli_returns_non_zero_and_names_reference_group(
    stub_run_eval: dict[str, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """他点名的那条：`--weights 1.0:0.0` 单组跑 ⇒ 退出码非 0 且 stderr 含"参照组"。"""
    stub_run_eval["report"] = _report([_group(1.0, 0.0, 1.0)])

    rc = main(["--weights", "1.0:0.0"])
    captured = capsys.readouterr()

    assert rc != 0
    assert rc == 2
    assert "参照组" in captured.err
    assert "无法判定 G2" in captured.err
    assert "通过" not in captured.out  # stdout 不许再出现一句"通过"


def test_cli_zero_when_reference_passes(
    stub_run_eval: dict[str, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    stub_run_eval["report"] = _report([_group(0.4, 0.6, 0.95)])

    assert main([]) == 0
    assert "参照组 0.4:0.6" in capsys.readouterr().out


def test_cli_one_when_reference_below_threshold(
    stub_run_eval: dict[str, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    stub_run_eval["report"] = _report([_group(0.4, 0.6, 0.10)])

    assert main([]) == 1
    assert "未通过" in capsys.readouterr().out
