"""任务集 schema / 加载 / 哈希 单测（P2 评测台 T01）。

覆盖设计文档 §7 对 T01 的验收要点：

* ``load_taskset()`` 对非法 YAML / 缺字段 / id 重复报**可读错误且带行号**
  （对齐 ``evaluation/dataset.py:74-94`` 的风格）；
* ``canonical_hash()`` 稳定（同内容同哈希、改一字必变）与 ``task_ids_hash()`` 顺序无关；
* ``yunqi_v1.yaml`` 恰好 40 条、``yunqi_smoke.yaml`` 恰好 5 条、每条 id 唯一；
* 40 条里每个 ``expected_result`` 的来源 ``source`` 非空且可回指真实文档。
"""

from __future__ import annotations

import re

import pytest

from evaluation.contracts import normalize
from evaluation.taskset import (
    CATEGORY_ORDER,
    DEFAULT_TASKSET,
    SMOKE_TASKSET,
    EvalTask,
    EvalTaskSet,
    ExpectedResult,
    TasksetError,
    load_taskset,
    parse_taskset,
)

#: 期望的分类分布（设计文档 §5.3 + T01 口径）
EXPECTED_MAIN_COUNTS: dict[str, int] = {
    "single_doc_lookup": 12,
    "cross_doc_consistency": 8,
    "numeric_reasoning": 7,
    "boundary": 5,
    "negative": 6,
    "multi_tool": 2,
}

#: 4 份云启智能文档的文件名前缀（source 必须回指其中之一）
_DOC_PREFIXES = ("01_", "02_", "03_", "04_")


# --------------------------------------------------------------------------- #
# 加载与统计
# --------------------------------------------------------------------------- #
class TestLoadMainTaskSet:
    """主任务集的条数、唯一性、来源。"""

    def test_main_exists_and_loads(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        assert taskset.name == "yunqi-agent-v1"
        assert taskset.version == 1

    def test_main_has_exactly_40_tasks(self) -> None:
        assert len(load_taskset(DEFAULT_TASKSET).tasks) == 40

    def test_main_category_distribution(self) -> None:
        counts = load_taskset(DEFAULT_TASKSET).category_counts()
        assert counts == EXPECTED_MAIN_COUNTS

    def test_task_ids_unique(self) -> None:
        ids = [t.id for t in load_taskset(DEFAULT_TASKSET).tasks]
        assert len(ids) == len(set(ids))

    def test_every_task_has_nonempty_source(self) -> None:
        for task in load_taskset(DEFAULT_TASKSET).tasks:
            assert task.source.strip(), f"{task.id} 的 source 为空"
            assert task.source != "TODO"

    def test_non_negative_source_points_to_real_doc(self) -> None:
        for task in load_taskset(DEFAULT_TASKSET).tasks:
            if task.category == "negative":
                assert "未收录" in task.source, f"{task.id} 负样本 source 未标注未收录"
                continue
            assert any(p in task.source for p in _DOC_PREFIXES), (
                f"{task.id} 的 source 未回指 4 份文档：{task.source}"
            )

    def test_every_task_has_prompt(self) -> None:
        for task in load_taskset(DEFAULT_TASKSET).tasks:
            assert task.prompt.strip()

    def test_non_negative_tasks_have_expected_result(self) -> None:
        for task in load_taskset(DEFAULT_TASKSET).tasks:
            if task.category != "negative":
                assert task.expected_result is not None, f"{task.id} 缺 expected_result"

    def test_negative_tasks_flag_no_fabrication(self) -> None:
        negatives = [t for t in load_taskset(DEFAULT_TASKSET).tasks if t.category == "negative"]
        assert negatives, "主任务集必须含负样本"
        for task in negatives:
            assert task.expect_no_fabrication is True, f"{task.id} 负样本未开启不编造断言"
            assert task.expected_result is not None
            assert task.expected_result.contains_any, f"{task.id} 负样本应有免责措辞 contains_any"

    def test_all_categories_covered(self) -> None:
        counts = load_taskset(DEFAULT_TASKSET).category_counts()
        for category in CATEGORY_ORDER:
            assert counts[category] > 0, f"分类 {category} 无任务"


class TestLoadSmokeTaskSet:
    """冒烟子集恰好 5 条、覆盖 5 类含 1 负样本。"""

    def test_smoke_has_exactly_5_tasks(self) -> None:
        assert len(load_taskset(SMOKE_TASKSET).tasks) == 5

    def test_smoke_ids_unique(self) -> None:
        ids = [t.id for t in load_taskset(SMOKE_TASKSET).tasks]
        assert len(ids) == len(set(ids))

    def test_smoke_covers_5_distinct_categories(self) -> None:
        categories = [t.category for t in load_taskset(SMOKE_TASKSET).tasks]
        assert len(set(categories)) == 5
        assert categories.count("negative") == 1

    def test_smoke_all_tagged(self) -> None:
        for task in load_taskset(SMOKE_TASKSET).tasks:
            assert "smoke" in task.tags

    def test_smoke_select_by_tag_matches(self) -> None:
        smoke = load_taskset(SMOKE_TASKSET)
        assert len(smoke.select(tag="smoke").tasks) == 5


# --------------------------------------------------------------------------- #
# 哈希稳定性
# --------------------------------------------------------------------------- #
def _minimal_payload(prompt: str) -> dict:
    """构造一份最小可用任务集 payload（用于哈希比对）。"""
    return {
        "version": 1,
        "name": "h",
        "description": "d",
        "defaults": {"max_iterations": 3, "review_threshold": 7, "use_tools": True,
                     "run_judge": False, "timeout_s": 150},
        "tasks": [
            {
                "id": "t1",
                "category": "single_doc_lookup",
                "difficulty": "easy",
                "tags": ["a"],
                "source": "01_员工手册.md 第 1.2 条",
                "prompt": prompt,
                "expected_result": {"contains_all": ["450"]},
            }
        ],
    }


class TestHashing:
    """canonical_hash / task_ids_hash 的稳定性与敏感性。"""

    def test_same_content_same_hash(self) -> None:
        a = EvalTaskSet.model_validate(_minimal_payload("同一段文字"))
        b = EvalTaskSet.model_validate(_minimal_payload("同一段文字"))
        assert a.canonical_hash() == b.canonical_hash()

    def test_reload_same_file_same_hash(self) -> None:
        assert load_taskset(DEFAULT_TASKSET).canonical_hash() == load_taskset(
            DEFAULT_TASKSET
        ).canonical_hash()

    def test_change_one_char_changes_hash(self) -> None:
        a = EvalTaskSet.model_validate(_minimal_payload("答案应是 450 元"))
        b = EvalTaskSet.model_validate(_minimal_payload("答案应是 450 元。"))
        assert a.canonical_hash() != b.canonical_hash()

    def test_hash_is_hex_sha256(self) -> None:
        digest = load_taskset(DEFAULT_TASKSET).canonical_hash()
        assert re.fullmatch(r"[0-9a-f]{64}", digest)

    def test_task_ids_hash_order_independent(self) -> None:
        payload = _minimal_payload("x")
        second = dict(payload["tasks"][0])
        second["id"] = "t2"
        payload["tasks"] = [payload["tasks"][0], second]
        forward = EvalTaskSet.model_validate(payload)
        payload["tasks"] = [second, payload["tasks"][0]]
        reversed_set = EvalTaskSet.model_validate(payload)
        assert forward.task_ids_hash() == reversed_set.task_ids_hash()
        # 但 canonical_hash 对顺序敏感（顺序也是内容）
        assert forward.canonical_hash() != reversed_set.canonical_hash()

    def test_main_and_smoke_hash_differ(self) -> None:
        assert (
            load_taskset(DEFAULT_TASKSET).canonical_hash()
            != load_taskset(SMOKE_TASKSET).canonical_hash()
        )


# --------------------------------------------------------------------------- #
# 错误处理（必须带行号）
# --------------------------------------------------------------------------- #
INVALID_YAML = "version: 1\nname: t\ntasks:\n  - id: a\n    category: [未闭合\n"

MISSING_SOURCE = (
    "version: 1\n"          # 1
    "name: t\n"             # 2
    "tasks:\n"              # 3
    "  - id: a\n"           # 4
    "    category: single_doc_lookup\n"   # 5
    "    difficulty: easy\n"              # 6
    "    prompt: \"hi\"\n"                # 7
)

DUPLICATE_ID = (
    "version: 1\n"          # 1
    "name: t\n"             # 2
    "tasks:\n"              # 3
    "  - id: dup\n"         # 4
    "    category: single_doc_lookup\n"   # 5
    "    difficulty: easy\n"              # 6
    "    source: \"01_员工手册.md 第 1.2 条\"\n"   # 7
    "    prompt: \"p\"\n"                 # 8
    "  - id: dup\n"         # 9
    "    category: negative\n"            # 10
    "    difficulty: easy\n"              # 11
    "    source: \"知识库未收录\"\n"      # 12
    "    prompt: \"p\"\n"                 # 13
)

UNKNOWN_FIELD = (
    "version: 1\n"
    "name: t\n"
    "tasks:\n"
    "  - id: a\n"
    "    category: single_doc_lookup\n"
    "    difficulty: easy\n"
    "    source: \"01_员工手册.md 第 1.2 条\"\n"
    "    prompt: \"p\"\n"
    "    bogus_field: 1\n"
)


class TestLoadErrors:
    """非法输入必须报可读错误且带行号。"""

    def test_missing_file(self) -> None:
        with pytest.raises(TasksetError, match="任务集不存在"):
            load_taskset("no_such_taskset.yaml")

    def test_invalid_yaml_reports_line(self) -> None:
        with pytest.raises(TasksetError) as excinfo:
            parse_taskset(INVALID_YAML, origin="bad.yaml")
        msg = str(excinfo.value)
        assert "bad.yaml" in msg
        assert "YAML 非法" in msg
        assert re.search(r":\d+", msg), f"错误信息缺少行号：{msg}"

    def test_missing_field_reports_line_and_path(self) -> None:
        with pytest.raises(TasksetError) as excinfo:
            parse_taskset(MISSING_SOURCE, origin="miss.yaml")
        msg = str(excinfo.value)
        assert "miss.yaml" in msg
        assert "字段不合法" in msg
        assert "source" in msg
        assert re.search(r":\d+ ", msg), f"错误信息缺少行号：{msg}"

    def test_duplicate_id_reports_line(self) -> None:
        with pytest.raises(TasksetError) as excinfo:
            parse_taskset(DUPLICATE_ID, origin="dup.yaml")
        msg = str(excinfo.value)
        assert "dup.yaml" in msg
        assert "id 重复" in msg
        assert ":9" in msg, f"重复 id 应指向第 9 行：{msg}"

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(TasksetError) as excinfo:
            parse_taskset(UNKNOWN_FIELD, origin="extra.yaml")
        msg = str(excinfo.value)
        assert "字段不合法" in msg
        assert "bogus_field" in msg

    def test_empty_content(self) -> None:
        with pytest.raises(TasksetError, match="任务集为空"):
            parse_taskset("", origin="empty.yaml")

    def test_top_level_not_mapping(self) -> None:
        with pytest.raises(TasksetError, match="顶层必须是映射"):
            parse_taskset("- just\n- a list\n", origin="list.yaml")

    def test_tasks_min_length(self) -> None:
        with pytest.raises(TasksetError, match="字段不合法"):
            parse_taskset("version: 1\nname: t\ntasks: []\n", origin="none.yaml")


# --------------------------------------------------------------------------- #
# 切片
# --------------------------------------------------------------------------- #
class TestSelect:
    """select() 的过滤语义。"""

    def test_select_by_category(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        negatives = taskset.select(categories=["negative"])
        assert len(negatives.tasks) == EXPECTED_MAIN_COUNTS["negative"]
        assert all(t.category == "negative" for t in negatives.tasks)

    def test_select_by_ids(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        picked = taskset.select(ids=["yq-hr-001", "yq-neg-001"])
        assert {t.id for t in picked.tasks} == {"yq-hr-001", "yq-neg-001"}

    def test_select_limit(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        assert len(taskset.select(limit=3).tasks) == 3

    def test_select_does_not_mutate_original(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        taskset.select(limit=1)
        assert len(taskset.tasks) == 40

    def test_get_by_id(self) -> None:
        taskset = load_taskset(DEFAULT_TASKSET)
        assert isinstance(taskset.get("yq-hr-001"), EvalTask)
        assert taskset.get("nope") is None


# --------------------------------------------------------------------------- #
# schema 默认值
# --------------------------------------------------------------------------- #
class TestSchemaDefaults:
    """默认值与非负约束。"""

    def test_default_expected_tools_mode_is_subset(self) -> None:
        task = EvalTask.model_validate(
            {
                "id": "x",
                "category": "single_doc_lookup",
                "source": "s",
                "prompt": "p",
                "expected_tools": {"any_of": ["knowledge_search"]},
            }
        )
        assert task.expected_tools is not None
        assert task.expected_tools.mode == "subset"
        assert task.expected_tools.collapse_repeats is True
        assert task.expected_tools.allow_extra is True

    def test_defaults_applied(self) -> None:
        taskset = parse_taskset("version: 1\nname: t\ntasks:\n  - id: a\n    category: boundary\n    source: s\n    prompt: p\n", origin="d.yaml")
        assert taskset.defaults.max_iterations == 3
        assert taskset.defaults.review_threshold == 7
        assert taskset.defaults.use_tools is True
        assert taskset.defaults.run_judge is False
        assert taskset.defaults.timeout_s == 150
        assert taskset.tasks[0].requires_ready_docs is True
        assert taskset.tasks[0].expect_no_fabrication is False

    def test_regex_empty_string_becomes_none(self) -> None:
        task = EvalTask.model_validate(
            {
                "id": "x",
                "category": "single_doc_lookup",
                "source": "s",
                "prompt": "p",
                "expected_result": {"contains_all": ["1"], "regex": "  "},
            }
        )
        assert task.expected_result is not None
        assert task.expected_result.regex is None

    def test_not_contains_regex_defaults_empty(self) -> None:
        result = ExpectedResult()
        assert result.not_contains == []
        assert result.not_contains_regex == []

    def test_invalid_not_contains_regex_rejected(self) -> None:
        with pytest.raises(TasksetError, match="字段不合法"):
            parse_taskset(
                "version: 1\nname: t\ntasks:\n  - id: a\n    category: negative\n"
                "    source: s\n    prompt: p\n"
                "    expected_result:\n      not_contains_regex: ['(']\n",
                origin="badre.yaml",
            )


# --------------------------------------------------------------------------- #
# 负样本「不编造」护栏（T01 补丁：not_contains + not_contains_regex）
# --------------------------------------------------------------------------- #
def _no_fabrication_ok(task: EvalTask, answer: str) -> bool:
    """复刻 T02 的 ``no_fabrication`` 判定语义（仅用于本测试自证数据字段有效）。

    语义（与 ``evaluation/contracts.py`` 的 ``normalize`` 口径一致）：

    1. 答案归一化后必须命中 ``contains_any`` 的**至少一个免责措辞**；否则 FAIL。
    2. 归一化答案**不得**含 ``not_contains`` 里任一具体值；否则 FAIL。
    3. 归一化答案**不得**命中 ``not_contains_regex`` 里任一形态；否则 FAIL。

    三条都过才算 PASS。T02 的正式实现见 ``evaluation/assertions.py``（本文件不改它）。
    """
    result = task.expected_result
    assert result is not None
    norm = normalize(answer)

    if result.contains_any:
        hit = any(any(normalize(alt) in norm for alt in group) for group in result.contains_any)
        if not hit:
            return False
    for bad in result.not_contains:
        if normalize(bad) in norm:
            return False
    for pattern in result.not_contains_regex:
        if re.search(pattern, norm):
            return False
    return True


def _negatives() -> list[EvalTask]:
    return [t for t in load_taskset(DEFAULT_TASKSET).tasks if t.category == "negative"]


class TestNegativeFabricationGuard:
    """6 条负样本的编造护栏必须存在且行为正确。"""

    def test_every_negative_has_a_guard(self) -> None:
        negatives = _negatives()
        assert len(negatives) == 6
        for task in negatives:
            result = task.expected_result
            assert result is not None
            assert result.not_contains or result.not_contains_regex, (
                f"{task.id} 既无 not_contains 也无 not_contains_regex，编造护栏为空"
            )

    def test_patterns_compile(self) -> None:
        for task in _negatives() + [
            t for t in load_taskset(SMOKE_TASKSET).tasks if t.category == "negative"
        ]:
            result = task.expected_result
            assert result is not None
            for pattern in result.not_contains_regex:
                re.compile(pattern)  # 不抛即通过

    def test_smoke_negative_has_guard(self) -> None:
        negatives = [t for t in load_taskset(SMOKE_TASKSET).tasks if t.category == "negative"]
        assert negatives
        result = negatives[0].expected_result
        assert result is not None
        assert result.not_contains and result.not_contains_regex

    # --- ★ 团队要求的两条对照回答：一条必须 FAIL、一条必须 PASS ---

    def test_fabricated_answer_fails(self) -> None:
        """带免责措辞但编造了具体数字 → 必须 FAIL。"""
        task = load_taskset(DEFAULT_TASKSET).get("yq-neg-001")
        assert task is not None
        fabricated = (
            "关于员工食堂餐费补助，公司规定为每天 30 元，随工资发放。"
            "（注：知识库中未收录该制度细节）"
        )
        assert _no_fabrication_ok(task, fabricated) is False

    def test_honest_answer_passes(self) -> None:
        """如实说查不到、不给数字 → 必须 PASS。"""
        task = load_taskset(DEFAULT_TASKSET).get("yq-neg-001")
        assert task is not None
        honest = "知识库中未收录员工食堂餐费补助相关制度，无法给出具体标准。"
        assert _no_fabrication_ok(task, honest) is True

    def test_clause_number_is_not_a_fabrication(self) -> None:
        """引用条款号（如『第 6.1 条』）属于合法回答，不得被金额/时刻形态误伤。"""
        task = load_taskset(DEFAULT_TASKSET).get("yq-neg-001")
        assert task is not None
        answer = "知识库中未收录该内容，可参考《员工手册》第 6.1 条与《财务报销制度》第 2.3 条。"
        assert _no_fabrication_ok(task, answer) is True

    def test_honest_disclaimer_passes_for_all_negatives(self) -> None:
        """通用免责回答对全部 6 条都不得误报。"""
        generic = "知识库中未收录相关信息，无法确认，无法给出具体标准。"
        for task in _negatives():
            assert _no_fabrication_ok(task, generic) is True, f"{task.id} 误报了诚实回答"

    def test_fabricated_variants_flagged(self) -> None:
        """各形态的编造变体都必须被抓。"""
        cases: dict[str, str] = {
            "yq-neg-001": "员工食堂餐费补助标准为每人每天 25 元。",
            "yq-neg-002": "公司股票代码是 002594。",
            "yq-neg-003": "员工健身房开放时间为 07:00-22:00。",
            "yq-neg-004": "子女教育补贴为每月 1000 元。",
            "yq-neg-005": "员工停车费补贴为每月 300 元。",
            "yq-neg-006": "公司的主要竞争对手是华为技术有限公司。",
        }
        taskset = load_taskset(DEFAULT_TASKSET)
        for task_id, answer in cases.items():
            task = taskset.get(task_id)
            assert task is not None
            assert _no_fabrication_ok(task, answer) is False, f"{task_id} 未抓住编造：{answer}"

    def test_stock_code_does_not_match_credit_code(self) -> None:
        """6 位代码形态不得误伤 8 位以上连续数字（如统一社会信用代码）。"""
        task = load_taskset(DEFAULT_TASKSET).get("yq-neg-002")
        assert task is not None
        answer = "知识库中未收录该公司的股票代码。"
        assert _no_fabrication_ok(task, answer) is True
        # 8 位连续数字不应被 6 位代码模式命中
        assert re.search(r"(?<!\d)\d{6}(?!\d)", normalize("91440300")) is None
