"""评测集：加载、校验与统计。

评测集用 JSONL 存——一行一条，好处是 diff 友好、可以增量追加、单行损坏不影响整体。
每条三个必需字段：

* ``task``：任务原文（直接喂给编排图）；
* ``expected_criteria``：验收标准，**必须逐条可核对**（judge 就是照这个打分的，
  写「答案要好」这种空标准等于没标准）；
* ``difficulty``：``easy`` / ``medium`` / ``hard``，用于分层看指标。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

#: 默认评测集路径
DEFAULT_DATASET = PROJECT_ROOT / "evaluation" / "dataset" / "agent_tasks.jsonl"

#: 难度取值
Difficulty = Literal["easy", "medium", "hard"]

#: 难度展示顺序
DIFFICULTY_ORDER: tuple[str, ...] = ("easy", "medium", "hard")


class DatasetError(ValueError):
    """评测集文件损坏或字段不合法。"""


class EvalItem(BaseModel):
    """一条评测样本。"""

    id: str = Field(min_length=1, description="样本 id，如 t001（用于横向对比时对齐）")
    task: str = Field(min_length=1, description="任务原文")
    expected_criteria: list[str] = Field(
        min_length=1,
        description="验收标准；每条都要能用「是/否」核对，判断依据写在答案里",
    )
    difficulty: Difficulty = Field(default="medium", description="难度：easy / medium / hard")


def load_dataset(
    path: Path | str | None = None,
    *,
    difficulty: Difficulty | None = None,
    limit: int | None = None,
    ids: Sequence[str] | None = None,
) -> list[EvalItem]:
    """读取并校验评测集。

    Args:
        path: JSONL 路径，默认 ``evaluation/dataset/agent_tasks.jsonl``。
        difficulty: 只保留指定难度。
        limit: 只取前 N 条（跑真实评测时控制成本用）。
        ids: 只取指定 id。

    Raises:
        DatasetError: 文件不存在、某行 JSON 非法、或字段不符合契约。
    """
    target = Path(path) if path is not None else DEFAULT_DATASET
    if not target.is_file():
        raise DatasetError(f"评测集不存在：{target}")

    items: list[EvalItem] = []
    seen: set[str] = set()
    raw_lines = target.read_text(encoding="utf-8").splitlines()
    for lineno, raw in enumerate(raw_lines, 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            payload: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{target.name}:{lineno} JSON 非法：{exc.msg}") from exc
        try:
            item = EvalItem.model_validate(payload)
        except ValidationError as exc:
            raise DatasetError(
                f"{target.name}:{lineno} 字段不合法：{exc.errors()[0]['msg']}"
            ) from exc
        if item.id in seen:
            raise DatasetError(f"{target.name}:{lineno} 样本 id 重复：{item.id}")
        seen.add(item.id)
        items.append(item)

    if difficulty is not None:
        items = [item for item in items if item.difficulty == difficulty]
    if ids is not None:
        wanted = set(ids)
        items = [item for item in items if item.id in wanted]
    if limit is not None:
        items = items[: max(limit, 0)]

    logger.debug("评测集加载完成：%d 条（来源 %s）", len(items), target.name)
    return items


def dataset_stats(items: Sequence[EvalItem]) -> dict[str, int]:
    """按难度统计条数。"""
    stats: dict[str, int] = dict.fromkeys(DIFFICULTY_ORDER, 0)
    for item in items:
        stats[item.difficulty] = stats.get(item.difficulty, 0) + 1
    stats["total"] = len(items)
    return stats


__all__ = [
    "DEFAULT_DATASET",
    "DIFFICULTY_ORDER",
    "DatasetError",
    "Difficulty",
    "EvalItem",
    "dataset_stats",
    "load_dataset",
]
