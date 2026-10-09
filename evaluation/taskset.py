"""任务集（YAML）：schema 校验、加载、规范化序列化与 sha256 哈希。

为什么是 YAML 而不是 JSONL
--------------------------
既有的 ``evaluation/dataset.py`` 用 JSONL 存 criteria 型任务集，够用但不好写多行
``prompt`` 与嵌套 ``expected_result``。本模块引入 YAML（PyYAML）作为**人写入口**：
多行文本、注释、缩进嵌套都更贴合「手写任务集」的真实场景。

为什么要有 ``canonical_hash()``
------------------------------
基线（``evaluation/baselines/*.json``）要回答「这次和上次的指标能不能直接比」，
第一判据就是**任务集是否同一份**。因此本模块提供两个稳定指纹：

* :meth:`EvalTaskSet.canonical_hash` —— 对**规范化序列化**后的全文取 sha256；
  同内容同哈希、改一个字必变（``json.dumps(sort_keys=True)`` 保证键序无关）。
* :meth:`EvalTaskSet.task_ids_hash` —— 对**按 id 排序**拼接后的 id 列表取 sha256；
  与任务顺序无关，用于「只增删了任务、没改内容」的粗粒度守卫。

错误处理约定（对齐 ``evaluation/dataset.py:74-94`` 的风格）
----------------------------------------------------------
``load_taskset()`` 对**非法 YAML / 缺字段 / id 重复**都抛 :class:`TasksetError`
并给出**文件名 + 行号 + 人话原因**（行号由 ``yaml.compose`` 的节点 mark 反推，
Pydantic 校验错误按字段路径定位到 YAML 行）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

#: 默认任务集路径（主任务集）
DEFAULT_TASKSET = PROJECT_ROOT / "evaluation" / "tasksets" / "yunqi_v1.yaml"

#: 冒烟子集路径
SMOKE_TASKSET = PROJECT_ROOT / "evaluation" / "tasksets" / "yunqi_smoke.yaml"

#: 分类维度（设计文档 §5.3，共 6 类）
Category = Literal[
    "single_doc_lookup",
    "cross_doc_consistency",
    "numeric_reasoning",
    "boundary",
    "negative",
    "multi_tool",
]

#: 难度取值（与 ``evaluation/dataset.py`` 的 Difficulty 语义一致）
Difficulty = Literal["easy", "medium", "hard"]

#: 分类展示顺序
CATEGORY_ORDER: tuple[str, ...] = (
    "single_doc_lookup",
    "cross_doc_consistency",
    "numeric_reasoning",
    "boundary",
    "negative",
    "multi_tool",
)

#: 难度展示顺序
DIFFICULTY_ORDER: tuple[str, ...] = ("easy", "medium", "hard")


class TasksetError(ValueError):
    """任务集文件损坏、字段不合法或 id 重复。"""


# --------------------------------------------------------------------------- #
# Schema（Pydantic v2；字段名即 YAML 键）
# --------------------------------------------------------------------------- #
class ExpectedResult(BaseModel):
    """结果断言期望：归一化子串 + 正则 + 多可接受写法（设计文档 §3.1）。"""

    model_config = ConfigDict(extra="forbid")

    contains_all: list[str] = Field(
        default_factory=list, description="归一化后必须全部出现的子串"
    )
    contains_any: list[list[str]] = Field(
        default_factory=list,
        description="每个内层组至少命中一个（同一事实的多种写法）",
    )
    regex: str | None = Field(
        default=None,
        description="数值精度用；**必须带数字边界** (?<!\\d)…(?!\\d)，否则 450 会命中 4500",
    )
    not_contains: list[str] = Field(
        default_factory=list,
        description="反例护栏；默认留空，仅在 prompt 明确限定时使用（慎用）",
    )
    not_contains_regex: list[str] = Field(
        default_factory=list,
        description=(
            "形态护栏（正则列表）：命中的『带单位的数量/金额/时刻』视为编造，"
            "供负样本的 no_fabrication 断言使用。"
            "例：`\\d+(?:\\.\\d+)?\\s*(?:元|万元|块钱|块)` 抓金额、"
            "`\\d{1,2}\\s*[:：]\\s*\\d{2}` 抓时刻、`(?<!\\d)\\d{6}(?!\\d)` 抓 6 位代码。"
            "★ 切勿写成『禁止所有数字』：合法回答会引用条款号（如『《员工手册》第 6.1 条』）。"
            "字段为**追加**（T01 补丁），旧任务集不写该键即为空列表，向后兼容。"
        ),
    )

    @field_validator("regex")
    @classmethod
    def _non_empty_regex(cls, value: str | None) -> str | None:
        """空字符串归一为 ``None``（YAML 里写 `regex:` 会得到 None，写 ``""`` 视为未设置）。

        非空时必须能编译，否则加载即报错（带文件行号），不让坏正则在断言期才炸。
        """
        if value is not None and not value.strip():
            return None
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:  # pragma: no cover - 由非法输入触发
                raise ValueError(f"regex 非法：{value!r}（{exc}）") from exc
        return value

    @field_validator("not_contains_regex")
    @classmethod
    def _valid_regex_list(cls, value: list[str]) -> list[str]:
        """逐条校验形态正则可编译，报错信息会带上非法模式。"""
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"not_contains_regex 非法正则：{pattern!r}（{exc}）") from exc
        return value


class ExpectedTools(BaseModel):
    """工具序列断言期望（设计文档 §3.1，四种模式互斥）。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "subset", "exact_sequence", "set"] = Field(
        default="subset", description="none | subset | exact_sequence | set"
    )
    any_of: list[str] = Field(default_factory=list, description="subset / set 用的期望工具集")
    sequence: list[str] = Field(default_factory=list, description="exact_sequence 用的期望序列")
    collapse_repeats: bool = Field(
        default=True, description="先把实际与期望各自的连续重复折叠后再比较"
    )
    allow_extra: bool = Field(default=True, description="subset 下是否允许期望之外的额外工具")

    @field_validator("mode")
    @classmethod
    def _mode_consistent(cls, value: str) -> str:
        """模式取值由 Literal 保证，这里只做占位以便未来加跨字段校验。"""
        return value


class Defaults(BaseModel):
    """每条任务可继承的默认值（设计文档 §3.1，减少重复）。"""

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(default=3, ge=1, description="覆盖 settings.max_iterations")
    review_threshold: int = Field(default=7, ge=0, le=10, description="reviewer 通过阈值")
    use_tools: bool = Field(default=True, description="是否允许编排器使用工具")
    run_judge: bool = Field(default=False, description="规则断言为主，judge 默认关闭以省成本")
    timeout_s: int = Field(default=150, ge=1, description="单任务超时（秒）")


class EvalTask(BaseModel):
    """一条评测任务（YAML 里的一个列表项）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="唯一 id；跨基线对齐锚点")
    category: Category = Field(description="分类维度（见 CATEGORY_ORDER）")
    difficulty: Difficulty = Field(default="medium", description="easy / medium / hard")
    tags: list[str] = Field(default_factory=list, description="供 --tag 切片，如 smoke")
    source: str = Field(
        min_length=1,
        description="★ 期望值的出处（哪份文档的哪一条），人工可复核，禁止拍脑袋",
    )
    prompt: str = Field(min_length=1, description="任务原文，直接喂给编排图")
    expected_result: ExpectedResult | None = Field(
        default=None, description="结果断言期望；无则跳过 result_contains 断言"
    )
    expected_tools: ExpectedTools | None = Field(
        default=None, description="工具序列期望；无则跳过 tool_sequence 断言"
    )
    max_steps: int | None = Field(
        default=None, ge=0, description="步数上限（= 节点执行次数，不是 iterations）"
    )
    max_tool_calls: int | None = Field(default=None, ge=0, description="工具调用次数上限")
    max_cost_cny: float | None = Field(default=None, ge=0.0, description="成本上限（CNY 元）")
    max_latency_ms: int | None = Field(default=None, ge=0, description="延迟上限（毫秒）")
    expect_judge: bool = Field(default=False, description="是否额外跑一次 LLM Judge（辅助信号）")
    judge_min_score: int | None = Field(
        default=None, ge=0, le=10, description="仅 expect_judge=true 时生效"
    )
    expect_no_fabrication: bool = Field(
        default=False, description="负样本专用：附加「不编造」断言"
    )
    requires_ready_docs: bool = Field(
        default=True, description="前置条件：KB 就绪才跑；不满足则 skipped"
    )
    accepted_status: list[str] | None = Field(
        default=None,
        description="terminal_status 断言的可接受终态；缺省 = [done]（可放宽为含 aborted）",
    )
    est_cost_cny: float | None = Field(
        default=None, ge=0.0, description="单条预估成本（CNY 元），供 --dry-run 估总价"
    )
    notes: str | None = Field(default=None, description="人工备注（可选）")


class EvalTaskSet(BaseModel):
    """一份完整任务集。"""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1, description="schema 版本（兼容演进）")
    name: str = Field(min_length=1, description="任务集名（基线里记录）")
    description: str = Field(default="", description="人话描述")
    defaults: Defaults = Field(default_factory=Defaults, description="任务默认值")
    tasks: list[EvalTask] = Field(min_length=1, description="任务列表")

    # -------------------------------------------------------- 指纹 / 序列化 --
    def canonical_payload(self) -> dict[str, Any]:
        """规范化字典：先 ``model_dump(mode="json")``，键序由下游 ``sort_keys`` 决定。"""
        return self.model_dump(mode="json")

    def canonical_json(self) -> str:
        """规范化 JSON 文本（键排序、紧凑分隔、不转义非 ASCII）。

        同内容必得同文本——这是 :meth:`canonical_hash` 稳定的前提。
        """
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def canonical_hash(self) -> str:
        """对规范化 JSON 文本取 sha256；同内容同哈希、改一字必变。"""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def task_ids_hash(self) -> str:
        """对按 id 排序的 id 列表取 sha256（与任务顺序无关）。"""
        joined = "\n".join(sorted(task.id for task in self.tasks))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------- 统计 --
    def category_counts(self) -> dict[str, int]:
        """按分类统计条数（含全部 6 类，缺失的补 0）。"""
        counts: dict[str, int] = dict.fromkeys(CATEGORY_ORDER, 0)
        for task in self.tasks:
            counts[task.category] = counts.get(task.category, 0) + 1
        return counts

    def difficulty_counts(self) -> dict[str, int]:
        """按难度统计条数。"""
        counts: dict[str, int] = dict.fromkeys(DIFFICULTY_ORDER, 0)
        for task in self.tasks:
            counts[task.difficulty] = counts.get(task.difficulty, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        """一条便于打印/落库的摘要。"""
        return {
            "name": self.name,
            "version": self.version,
            "task_count": len(self.tasks),
            "sha256": self.canonical_hash(),
            "task_ids_hash": self.task_ids_hash(),
            "by_category": self.category_counts(),
            "by_difficulty": self.difficulty_counts(),
        }

    # -------------------------------------------------------------- 切片 --
    def select(
        self,
        *,
        tags: Sequence[str] | None = None,
        tag: str | None = None,
        ids: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        difficulties: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> EvalTaskSet:
        """按条件切片，返回**新的**任务集（不修改自身）。

        注意：切片后的 :meth:`canonical_hash` 与全集不同——基线比对请对**全集**取哈希。
        """
        wanted_tags: set[str] = set(tags or ())
        if tag is not None:
            wanted_tags.add(tag)
        wanted_ids = set(ids) if ids is not None else None
        wanted_categories = set(categories) if categories is not None else None
        wanted_difficulties = set(difficulties) if difficulties is not None else None

        tasks = list(self.tasks)
        if wanted_tags:
            tasks = [t for t in tasks if wanted_tags.intersection(t.tags)]
        if wanted_ids is not None:
            tasks = [t for t in tasks if t.id in wanted_ids]
        if wanted_categories is not None:
            tasks = [t for t in tasks if t.category in wanted_categories]
        if wanted_difficulties is not None:
            tasks = [t for t in tasks if t.difficulty in wanted_difficulties]
        if limit is not None:
            tasks = tasks[: max(int(limit), 0)]
        return self.model_copy(update={"tasks": tasks})

    def get(self, task_id: str) -> EvalTask | None:
        """按 id 取任务，找不到返回 ``None``。"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None


# --------------------------------------------------------------------------- #
# 加载与校验
# --------------------------------------------------------------------------- #
def _yaml_error_line(exc: yaml.YAMLError) -> int | None:
    """从 PyYAML 异常里取 1 起的行号（取不到返回 ``None``）。"""
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is not None:
        return int(mark.line) + 1
    return None


def _node_line(node: yaml.Node | None, loc: Sequence[Any]) -> int | None:
    """按 Pydantic 的错误 ``loc`` 路径在 YAML 节点树里定位 1 起的行号。

    路径形如 ``("tasks", 3, "expected_result", "regex")``。逐段下行：
    映射段按 key 取 value 节点，序列段按下标取子节点；走到哪算哪，
    取当前节点的 ``start_mark.line``（1 起）。
    """
    if node is None:
        return None
    current: yaml.Node = node
    for part in loc:
        if isinstance(current, yaml.MappingNode):
            found: yaml.Node | None = None
            for key_node, value_node in current.value:
                if getattr(key_node, "value", None) == str(part):
                    found = value_node
                    break
            current = found if found is not None else current
        elif isinstance(current, yaml.SequenceNode):
            try:
                index = int(part)
            except (TypeError, ValueError):
                return current.start_mark.line + 1
            if 0 <= index < len(current.value):
                current = current.value[index]
            else:
                return current.start_mark.line + 1
        else:
            return current.start_mark.line + 1
    return current.start_mark.line + 1


def parse_taskset(text: str, *, origin: str = "<string>") -> EvalTaskSet:
    """解析并校验任务集文本。

    Args:
        text: YAML 全文。
        origin: 出错信息里显示的文件名（默认 ``<string>``）。

    Raises:
        TasksetError: YAML 非法（给行号）/ 非映射 / 字段不合法（给行号）/ id 重复（给行号）。
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line = _yaml_error_line(exc)
        where = f"{origin}:{line}" if line is not None else origin
        raise TasksetError(f"{where} YAML 非法：{exc}") from exc

    if raw is None:
        raise TasksetError(f"{origin}:1 任务集为空")
    if not isinstance(raw, Mapping):
        raise TasksetError(f"{origin}:1 顶层必须是映射（mapping），实际是 {type(raw).__name__}")

    # 供校验错误定位用（compose 失败不致命，退回无行号）
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:  # pragma: no cover - safe_load 已先失败
        root = None

    try:
        taskset = EvalTaskSet.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = tuple(first.get("loc", ()))
        line = _node_line(root, loc)
        where = f"{origin}:{line}" if line is not None else origin
        path = ".".join(str(p) for p in loc) or "<root>"
        raise TasksetError(f"{where} 字段不合法（{path}）：{first.get('msg', '校验失败')}") from exc

    seen: set[str] = set()
    for index, task in enumerate(taskset.tasks):
        if task.id in seen:
            line = _node_line(root, ("tasks", index, "id"))
            where = f"{origin}:{line}" if line is not None else origin
            raise TasksetError(f"{where} 任务 id 重复：{task.id}")
        seen.add(task.id)

    logger.debug("任务集解析完成：%s（%d 条）", taskset.name, len(taskset.tasks))
    return taskset


def load_taskset(path: Path | str | None = None) -> EvalTaskSet:
    """读取并校验任务集文件（不做切片，返回全集——基线哈希基于全集）。

    Args:
        path: YAML 路径，默认 ``evaluation/tasksets/yunqi_v1.yaml``。

    Raises:
        TasksetError: 文件不存在或内容不合法（错误信息含文件名与行号）。
    """
    target = Path(path) if path is not None else DEFAULT_TASKSET
    if not target.is_file():
        raise TasksetError(f"任务集不存在：{target}")
    text = target.read_text(encoding="utf-8")
    return parse_taskset(text, origin=target.name)


__all__ = [
    "CATEGORY_ORDER",
    "DEFAULT_TASKSET",
    "DIFFICULTY_ORDER",
    "SMOKE_TASKSET",
    "Category",
    "Defaults",
    "Difficulty",
    "EvalTask",
    "EvalTaskSet",
    "ExpectedResult",
    "ExpectedTools",
    "TasksetError",
    "load_taskset",
    "parse_taskset",
]
