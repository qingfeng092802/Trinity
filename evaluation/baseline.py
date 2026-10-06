"""P2 评测台 · 基线存储与回归 diff（设计文档 §3.4 / §7 T04）。

本模块是评测台「能不能回答『我改了 Prompt / 换了模型之后，到底变好没有』」的**归因层**：

* **可比性元信息采集**（模型名 / Prompt 文件哈希 / 任务集哈希 / 代码指纹 / 关键 config）
  ——「指标变了」只有在这些维度一致时才谈得上归因。
* **基线读写**（``evaluation/baselines/<name>.json``，落盘格式 = :meth:`BaselineModel.as_dict`）。
* **可比性守卫**：模型 / Prompt 哈希 / 任务集哈希任一不一致 → **先输出硬警告**
  （说明哪一维变了、因此 delta 不可直接归因），而不是闷头给 delta。
* **逐指标 delta**：方向 / 绝对差 / 相对百分比 / 容忍带 / 是否「无显著变化」。
  容忍带内的变化**一律标注「无显著变化」**，绝不夸成「变好」（设计文档 §9.8 不美化数字）。
* **逐任务回归/改善清单**：pass→fail（regressed）/ fail→pass（improved）/ 新增 / 消失。
* **Markdown 渲染**：人可读报告，供 ``scripts/run_eval.py --compare``（T05）调用。

设计约束（务必遵守）
--------------------
* 只依赖**冻结契约** ``evaluation/contracts.py`` 与 ``evaluation/taskset.py``；
  落盘结构一律复用 :class:`BaselineModel`，**不另造 schema**。
* ``tool_accuracy`` 可能为 ``None``（无任务带期望工具，见设计文档 §4.2）——delta 与渲染
  **必须 null 安全**，绝不把 ``None`` 当 0 算出「下降 100%」这类假信号。
* ``repeat > 1`` 时容忍带 = ``max(固定带, 2σ)``；``repeat == 1`` 用固定带。
* 本目录**不是 git 仓库**，代码指纹优先取 ``git rev-parse HEAD``，取不到则优雅回退为
  相关源码文件的 sha256 字典。

单位约定（沿用契约，勿改）
--------------------------
* 时间：北京时间 ISO-8601 ``+08:00``（复用 ``core.llm.pricing.now``）。
* 成本：CNY 元（``round(x, 6)``）；比率：``round(x, 4)``。
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT
from evaluation.contracts import (
    CHANNEL_DIRECT,
    CHANNELS,
    METRIC_AVG_COST,
    METRIC_AVG_STEPS,
    METRIC_KEYS,
    METRIC_PASS_RATE,
    METRIC_P95_LATENCY,
    METRIC_TOOL_ACCURACY,
    BaselineDiff,
    BaselineModel,
    MetricDelta,
    SuiteMetrics,
    Tolerances,
    round_cost,
    round_ratio,
)
from evaluation.taskset import Defaults, EvalTaskSet

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 基线目录（一次「晋级」= 把某次运行另存为 ``<name>.json``）
BASELINE_DIR: Path = PROJECT_ROOT / "evaluation" / "baselines"

#: 基线 schema 版本（与 ``BaselineModel.schema_version`` 默认值一致）
DEFAULT_SCHEMA_VERSION: int = 1

#: 采样温度（设计文档 §1.2：复用适配器默认 ``temperature=0.0`` 降方差）
DEFAULT_TEMPERATURE: float = 0.0

#: Prompt 资产根目录（``core/llm/prompts/v1/*.md``）
PROMPTS_DIR: Path = PROJECT_ROOT / "core" / "llm" / "prompts"

#: 代码指纹默认覆盖的源码（相对 ``PROJECT_ROOT`` 的 glob；文件不存在则跳过）
DEFAULT_CODE_PATTERNS: tuple[str, ...] = (
    "evaluation/*.py",
    "core/agent/**/*.py",
    "core/llm/**/*.py",
    "core/llm/prompts/**/*",
)

#: 指标极性：判定「改善 / 退化」用（up 是否等于变好）
_METRIC_POLARITY: dict[str, str] = {
    METRIC_PASS_RATE: "higher_better",
    METRIC_TOOL_ACCURACY: "higher_better",
    METRIC_AVG_STEPS: "lower_better",
    METRIC_AVG_COST: "lower_better",
    METRIC_P95_LATENCY: "lower_better",
}

#: 指标中文名（报告可读性）
_METRIC_LABELS: dict[str, str] = {
    METRIC_PASS_RATE: "通过率 pass_rate",
    METRIC_TOOL_ACCURACY: "工具准确率 tool_accuracy",
    METRIC_AVG_STEPS: "平均步数 avg_steps",
    METRIC_AVG_COST: "平均成本 avg_cost(CNY)",
    METRIC_P95_LATENCY: "P95 延迟 p95_latency_ms",
}

#: 判定标签（用于 Markdown）
_JUDGMENT_LABELS: dict[str, str] = {
    "undetermined": "未参与对比",
    "no_significant_change": "无显著变化（在波动带内）",
    "improved": "改善",
    "degraded": "退化",
}

#: 浮点比较用极小容差（避免 0.05 vs 0.04999999 的边界误判）
_EPS: float = 1e-9


class BaselineError(ValueError):
    """基线文件缺失 / 损坏，或输入不合法（错误信息务必人可读，不含裸 traceback）。"""


# --------------------------------------------------------------------------- #
# 时间与哈希小工具
# --------------------------------------------------------------------------- #
def now_cn() -> datetime:
    """当前北京时间（复用 ``core.llm.pricing.now``，保证全项目时间口径一致）。

    惰性 import：避免评测台仅做静态 diff 时也把 LLM 适配层拉进来。
    """
    from core.llm.pricing import now as _now

    return _now()


def iso_now() -> str:
    """当前北京时间 ISO-8601 字符串（含 ``+08:00`` 偏移）。"""
    return now_cn().isoformat()


def new_run_id(moment: datetime | None = None) -> str:
    """按北京时间生成 ``run-YYYYmmdd-HHMMSS`` 形式的运行 id（复现性溯源用）。"""
    stamp = moment if moment is not None else now_cn()
    return "run-" + stamp.strftime("%Y%m%d-%H%M%S")


def sha256_file(path: Path | str) -> str:
    """对文件内容取 sha256（分块读，避免大文件整块入内存）。"""
    digest = hashlib.sha256()
    with open(Path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """对文本取 sha256（UTF-8 编码）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relative_key(path: Path, base: Path) -> str:
    """把文件路径渲染成稳定键：优先相对 ``PROJECT_ROOT``，否则相对 ``base``。"""
    for anchor in (PROJECT_ROOT, base):
        try:
            return path.relative_to(anchor).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _iter_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    """按 glob 收集去重后的文件（跳过 ``__pycache__``），按路径排序保证可复现。"""
    found: set[Path] = set()
    for pattern in patterns:
        found.update(root.glob(pattern))
    files = [
        path
        for path in found
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return sorted(files)


# --------------------------------------------------------------------------- #
# 可比性元信息采集
# --------------------------------------------------------------------------- #
def prompts_metadata(root: Path | str | None = None) -> dict[str, Any]:
    """采集 Prompt 资产的可比性元信息。

    Returns:
        ``{"versions": {role: "v1"}, "files_sha256": {相对路径: sha256}}``。
        ``versions`` 由 ``prompts/<version>/<role>.md`` 的目录名与文件名推导
        （例：``core/llm/prompts/v1/executor.md`` → ``{"executor": "v1"}``）。
    """
    base = Path(root) if root is not None else PROMPTS_DIR
    files_sha256: dict[str, str] = {}
    versions: dict[str, str] = {}
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            files_sha256[_relative_key(path, base)] = sha256_file(path)
            version = path.parent.name
            role = path.stem
            if path.name != ".gitkeep" and version.startswith("v"):
                versions.setdefault(role, version)
    return {"versions": versions, "files_sha256": files_sha256}


def _git_commit(root: Path) -> str | None:
    """取 ``git rev-parse HEAD``；非 git 环境 / git 不可用 / 超时 → ``None``。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def code_metadata(
    root: Path | str | None = None,
    *,
    patterns: Sequence[str] | None = None,
    use_git: bool = True,
) -> dict[str, Any]:
    """采集代码指纹。

    设计文档 §3.4：**优先** git commit；**非 git 环境优雅回退**为相关源码文件的
    sha256 字典（``evaluation/*.py``、``core/agent/*.py``、``core/llm/**``）。

    Args:
        root: 项目根（默认 ``PROJECT_ROOT``）。
        patterns: 覆盖 ``DEFAULT_CODE_PATTERNS``；文件不存在自动跳过。
        use_git: 是否尝试 git（测试里可关闭以保证确定性）。

    Returns:
        ``{"git_commit": str | None, "sources_sha256": {相对路径: sha256}}``。
    """
    root_path = Path(root) if root is not None else PROJECT_ROOT
    pats = tuple(patterns) if patterns is not None else DEFAULT_CODE_PATTERNS
    sources = {
        _relative_key(path, root_path): sha256_file(path)
        for path in _iter_files(root_path, pats)
    }
    return {
        "git_commit": _git_commit(root_path) if use_git else None,
        "sources_sha256": sources,
    }


def model_metadata(settings: Any | None = None) -> dict[str, Any]:
    """采集模型维度的可比性元信息（模型名 / embedding 名 / 温度）。"""
    info: dict[str, Any] = {"temperature": DEFAULT_TEMPERATURE}
    if settings is not None:
        info["llm_model_large"] = settings.llm_model_large
        info["llm_model_small"] = settings.llm_model_small
        info["embedding_model_name"] = settings.embedding_model_name
    return info


def config_metadata(settings: Any | None = None, *, taskset: EvalTaskSet | None = None) -> dict[str, Any]:
    """采集关键 config（决定性参数）。

    取值优先级：任务集 ``defaults`` > 全局 ``settings`` > 任务集 schema 默认值。
    """
    defaults = taskset.defaults if taskset is not None else Defaults()
    info: dict[str, Any] = {
        "max_iterations": defaults.max_iterations,
        "review_threshold": defaults.review_threshold,
        "temperature": DEFAULT_TEMPERATURE,
    }
    if settings is not None:
        info["bm25_weight"] = settings.bm25_weight
        info["vector_weight"] = settings.vector_weight
        info["embedding_dim"] = settings.embedding_dim
    return info


def taskset_metadata(taskset: EvalTaskSet, *, path: Path | str | None = None) -> dict[str, Any]:
    """采集任务集元信息（名字 / 哈希 / 条数 / id 哈希）。

    ``sha256`` 用 :meth:`EvalTaskSet.canonical_hash`（同内容同哈希、改一字必变），
    是「两份数据能不能直接比」的第一判据。
    """
    path_str = ""
    if path is not None:
        candidate = Path(path)
        try:
            path_str = candidate.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            path_str = candidate.as_posix()
    return {
        "name": taskset.name,
        "version": taskset.version,
        "path": path_str,
        "sha256": taskset.canonical_hash(),
        "task_count": len(taskset.tasks),
        "task_ids_hash": taskset.task_ids_hash(),
    }


def _resolve_settings(settings: Any | None) -> Any | None:
    """给定 ``settings`` 为空时惰性取全局配置单例；失败则返回 ``None``（不致命）。"""
    if settings is not None:
        return settings
    try:
        from config import get_settings

        return get_settings()
    except Exception:  # pragma: no cover - 配置不可用不应阻断基线构建
        logger.warning("全局配置不可用，模型/成本元信息将缺省", exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# 逐任务条目与基线构建
# --------------------------------------------------------------------------- #
def make_per_task_entry(
    *,
    task_id: str,
    passed: bool,
    category: str = "",
    difficulty: str = "",
    status: str = "unknown",
    steps: int = 0,
    iterations: int = 0,
    tool_calls: int = 0,
    tool_failures: int = 0,
    cost: float = 0.0,
    duration_ms: int = 0,
    tool_sequence: Sequence[str] | None = None,
    failed_assertions: Sequence[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """构造一条标准化 ``per_task`` 记录（字段与设计文档 §3.4 的示例对齐）。

    ``failed_assertions`` 是「变化原因的可追线索」：任务从 pass 变 fail 时，
    报告里逐条列出未通过的断言名（源自 ``TaskAssertionResult.failed_names()``）。
    """
    return {
        "id": str(task_id),
        "category": category,
        "difficulty": difficulty,
        "passed": bool(passed),
        "status": status,
        "steps": int(steps),
        "iterations": int(iterations),
        "tool_calls": int(tool_calls),
        "tool_failures": int(tool_failures),
        "cost": round_cost(cost),
        "duration_ms": int(duration_ms),
        "tool_sequence": list(tool_sequence or ()),
        "failed_assertions": list(failed_assertions or ()),
        "error": error,
    }


def build_baseline(
    *,
    metrics: SuiteMetrics,
    per_task: Sequence[Mapping[str, Any]] = (),
    taskset: EvalTaskSet | None = None,
    taskset_path: Path | str | None = None,
    settings: Any | None = None,
    channel: str = CHANNEL_DIRECT,
    repeat: int = 1,
    run_id: str | None = None,
    created_at: str | None = None,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> BaselineModel:
    """把一次运行的指标与逐任务结果组装成可落盘的 :class:`BaselineModel`。

    Args:
        metrics: 套件指标（``SuiteMetrics``）。
        per_task: 逐任务记录列表（建议用 :func:`make_per_task_entry` 构造）。
        taskset: 任务集对象（记录名字 / 哈希 / 条数）。
        taskset_path: 任务集文件路径（记录用；``None`` 则为空串）。
        settings: 全局配置（``None`` 时惰性取 ``get_settings()``）。
        channel: 执行通道（``direct`` / ``api``，必须取 ``CHANNEL_*`` 常量）。
        repeat: 重复采样次数（``>=1``）。
        run_id: 运行 id（``None`` 时按当前北京时间生成）。
        created_at: 时间戳（``None`` 时取当前北京时间 ISO-8601）。
        schema_version: schema 版本。

    Raises:
        BaselineError: ``channel`` 非法或 ``repeat < 1``。
    """
    if channel not in CHANNELS:
        raise BaselineError(f"非法的执行通道 channel={channel!r}，应为 {CHANNELS} 之一")
    if int(repeat) < 1:
        raise BaselineError(f"repeat 必须 >= 1，实际 {repeat!r}")

    resolved_settings = _resolve_settings(settings)
    config = config_metadata(resolved_settings, taskset=taskset)
    # ``run_id`` 无独立契约字段，落进自由格式的 config（设计文档要求记录 run_id 与时间戳）。
    config["run_id"] = run_id if run_id is not None else new_run_id()

    return BaselineModel(
        schema_version=schema_version,
        created_at=created_at if created_at is not None else iso_now(),
        taskset=taskset_metadata(taskset, path=taskset_path) if taskset is not None else {},
        model=model_metadata(resolved_settings),
        prompts=prompts_metadata(),
        code_fingerprint=code_metadata(),
        config=config,
        channel=channel,
        repeat=int(repeat),
        metrics=metrics,
        per_task=[dict(item) for item in per_task],
    )


# --------------------------------------------------------------------------- #
# 基线读写
# --------------------------------------------------------------------------- #
def baseline_path(name: str | Path, directory: Path | str | None = None) -> Path:
    """解析基线文件路径。

    * 绝对路径（或含目录分隔符的路径）→ 直接使用，缺 ``.json`` 后缀自动补；
    * 纯名字 → ``<directory>/<name>.json``（``directory`` 默认 :data:`BASELINE_DIR`）。
    """
    raw = Path(name)
    if raw.is_absolute() or raw.parent != Path("."):
        return raw if raw.suffix == ".json" else raw.with_suffix(".json")
    target_dir = Path(directory) if directory is not None else BASELINE_DIR
    candidate = target_dir / raw
    return candidate if candidate.suffix == ".json" else candidate.with_suffix(".json")


def save_baseline(
    model: BaselineModel,
    name: str | Path,
    *,
    directory: Path | str | None = None,
) -> Path:
    """把基线模型落盘为 JSON（格式 = :meth:`BaselineModel.as_dict`），返回写入路径。"""
    path = baseline_path(name, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.as_dict()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("基线已保存：%s", path)
    return path


def load_baseline(name: str | Path, *, directory: Path | str | None = None) -> BaselineModel:
    """读取基线文件并还原成 :class:`BaselineModel`。

    Raises:
        BaselineError: 文件不存在 / 不是合法 JSON / 顶层不是对象（**人可读错误**，
            绝不放裸 ``FileNotFoundError`` traceback）。
    """
    path = baseline_path(name, directory)
    if not path.is_file():
        raise BaselineError(f"基线文件不存在：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"基线文件不是合法 JSON：{path}（{exc.msg}，第 {exc.lineno} 行）") from exc
    if not isinstance(raw, Mapping):
        raise BaselineError(f"基线文件顶层必须是对象（mapping）：{path}")
    return BaselineModel.from_dict(raw)


# --------------------------------------------------------------------------- #
# 指标 delta 与容忍带
# --------------------------------------------------------------------------- #
def _metric_value(metrics: SuiteMetrics, key: str) -> float | None:
    """取某指标的数值；缺失或 ``None`` 返回 ``None``（null 安全）。"""
    value = getattr(metrics, key, None)
    if value is None:
        return None
    return float(value)


def metric_tolerance(key: str, baseline_value: float | None, tolerances: Tolerances) -> float | None:
    """把容忍带折算成**与指标同单位**的绝对带。

    * 绝对带指标（``pass_rate`` / ``tool_accuracy`` / ``avg_steps``）直接用；
    * 相对带指标（``avg_cost`` / ``p95_latency_ms``）乘以基线值折算为绝对值。
    """
    if key == METRIC_PASS_RATE:
        return tolerances.pass_rate
    if key == METRIC_TOOL_ACCURACY:
        return tolerances.tool_accuracy
    if key == METRIC_AVG_STEPS:
        return tolerances.avg_steps
    if key == METRIC_AVG_COST:
        if baseline_value is None:
            return None
        return tolerances.avg_cost_rel * abs(baseline_value)
    if key == METRIC_P95_LATENCY:
        if baseline_value is None:
            return None
        return tolerances.p95_latency_rel * abs(baseline_value)
    return None


def compute_metric_delta(
    key: str,
    baseline_value: float | None,
    current_value: float | None,
    tolerance: float | None,
) -> MetricDelta:
    """计算单个指标的 delta（null 安全）。

    Args:
        key: 指标名（``METRIC_*``）。
        baseline_value / current_value: 基线 / 当前指标值；任一为 ``None`` →
            ``delta``/``delta_pct`` 均 ``None`` 且 ``direction="undetermined"``，
            **绝不把 ``None`` 当 0**（否则 ``tool_accuracy=None`` 会假造「下降 100%」）。
        tolerance: **已解析成与指标同单位**的绝对容忍带（由 :func:`metric_tolerance`
            折算，必要时已被 :func:`resolve_tolerances` 按 ``2σ`` 放宽）；``None`` →
            ``within_tolerance=False``。
    """
    if baseline_value is None or current_value is None:
        return MetricDelta(
            name=key,
            baseline=baseline_value,
            current=current_value,
            delta=None,
            delta_pct=None,
            direction="undetermined",
            tolerance=None,
            within_tolerance=False,
        )

    delta = current_value - baseline_value
    delta_pct = round_ratio(delta / baseline_value) if baseline_value != 0 else None
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"
    within = tolerance is not None and abs(delta) <= tolerance + _EPS
    return MetricDelta(
        name=key,
        baseline=baseline_value,
        current=current_value,
        delta=delta,
        delta_pct=delta_pct,
        direction=direction,
        tolerance=tolerance,
        within_tolerance=within,
    )


def resolve_tolerances(
    current: BaselineModel,
    base: BaselineModel,
    tolerances: Tolerances | None = None,
) -> dict[str, float]:
    """把容忍带解析成**逐指标绝对值**带（含 ``repeat>1`` 的 ``2σ`` 放宽）。

    单线逻辑（团队仲裁：σ 一律以**指标自身绝对单位**记录，不按指标相对化）：

    * ``tolerances`` 为空 → 用 ``Tolerances.for_task_count(task_count)``（小样本收紧）；
    * 每个指标的固定带先由 :func:`metric_tolerance` **折算成绝对值**
      （相对带指标 ``avg_cost`` / ``p95_latency_ms`` 乘以基线值）；
    * ``repeat > 1`` 时再统一 ``max(绝对带, 2σ)`` —— σ 直接取
      ``SuiteMetrics.std[key]``（**绝对单位**：比例 / 步数 / **元** / **毫秒**），
      因此**不需要按指标切换 σ 的单位**，无两套规则并存的分支。

    Args:
        current: 本次运行基线模型（提供 ``repeat`` 与 ``std``）。
        base: 参照基线模型（``current.std`` 缺失时回退其 ``std``）。
        tolerances: 固定带；``None`` 时按任务数推导。

    Returns:
        指标名 → **绝对**容忍带（与指标同单位）；相对带指标若基线值为 ``None`` 则缺省。
    """
    task_count = current.metrics.evaluated or len(current.per_task)
    fixed = tolerances if tolerances is not None else Tolerances.for_task_count(task_count)

    sigma_by_metric: dict[str, float] = {}
    if current.repeat > 1:
        sigma_by_metric = dict(current.metrics.std) or dict(base.metrics.std) or {}

    resolved: dict[str, float] = {}
    for key in METRIC_KEYS:
        abs_tol = metric_tolerance(key, _metric_value(base.metrics, key), fixed)
        if abs_tol is None:
            continue
        sigma = float(sigma_by_metric.get(key, 0.0) or 0.0)
        if current.repeat > 1 and sigma > 0.0:
            abs_tol = max(abs_tol, 2.0 * sigma)
        resolved[key] = abs_tol
    return resolved


def classify_metric_change(key: str, delta: MetricDelta) -> str:
    """把 delta 归成四类之一（供测试与渲染统一口径）。

    Returns:
        ``"undetermined"``（任一为空）/ ``"no_significant_change"``（带内）/
        ``"improved"`` / ``"degraded"``（带外，按指标极性判定）。
    """
    if delta.delta is None or delta.direction == "undetermined":
        return "undetermined"
    if delta.within_tolerance:
        return "no_significant_change"
    polarity = _METRIC_POLARITY.get(key, "higher_better")
    better_up = polarity == "higher_better"
    is_up = delta.delta > 0
    return "improved" if is_up == better_up else "degraded"


# --------------------------------------------------------------------------- #
# 可比性守卫
# --------------------------------------------------------------------------- #
def comparability_warnings(base: BaselineModel, current: BaselineModel) -> list[str]:
    """比较两份数据的可比性元信息，返回**硬警告**清单（空 = 可直接归因）。

    检查三个决定归因的维度（设计文档 §3.4）：模型 / Prompt 文件哈希 / 任务集哈希。
    任一方缺元信息亦视为不可核验，同样告警。
    """
    warnings: list[str] = []

    base_model = dict(base.model or {})
    curr_model = dict(current.model or {})
    for key, label in (
        ("llm_model_large", "强模型 llm_model_large"),
        ("llm_model_small", "快模型 llm_model_small"),
    ):
        b_val = base_model.get(key)
        c_val = curr_model.get(key)
        if b_val != c_val:
            if b_val is None or c_val is None:
                warnings.append(
                    f"可比性守卫：{label} 元信息缺失（baseline={b_val!r} → current={c_val!r}），无法核验可比性"
                )
            else:
                warnings.append(
                    f"可比性守卫：{label} 已变更（baseline={b_val!r} → current={c_val!r}），指标 delta 不可直接归因"
                )

    base_prompts = dict((base.prompts or {}).get("files_sha256", {}) or {})
    curr_prompts = dict((current.prompts or {}).get("files_sha256", {}) or {})
    if base_prompts and curr_prompts:
        changed_files = sorted(
            path
            for path in set(base_prompts) | set(curr_prompts)
            if base_prompts.get(path) != curr_prompts.get(path)
        )
        if changed_files:
            warnings.append(
                f"可比性守卫：Prompt 文件哈希已变更（{len(changed_files)} 个：{changed_files}），"
                "指标 delta 不可直接归因于代码或任务集改动"
            )
    elif base_prompts or curr_prompts:
        warnings.append(
            "可比性守卫：Prompt 文件哈希元信息不对称"
            f"（baseline {len(base_prompts)} 个 / current {len(curr_prompts)} 个），无法核验 Prompt 是否变化"
        )

    base_ts = (base.taskset or {}).get("sha256")
    curr_ts = (current.taskset or {}).get("sha256")
    if base_ts != curr_ts:
        if base_ts is None or curr_ts is None:
            warnings.append(
                f"可比性守卫：任务集哈希元信息缺失（baseline={base_ts!r} → current={curr_ts!r}），无法核验可比性"
            )
        else:
            warnings.append(
                f"可比性守卫：任务集哈希已变更（baseline={base_ts} → current={curr_ts}），"
                "任务不可一一对应，指标 delta 不可直接归因"
            )

    if not base_model and not curr_model and not base_prompts and not curr_prompts and not base_ts and not curr_ts:
        warnings.append(
            "可比性守卫：两份数据均缺少可比性元信息（模型 / Prompt 哈希 / 任务集哈希全空），无法核验可比性"
        )

    return warnings


# --------------------------------------------------------------------------- #
# 逐任务回归 / 改善
# --------------------------------------------------------------------------- #
def _index_by_id(per_task: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """按 ``id`` 建索引（跳过无 id 的记录）。"""
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in per_task:
        task_id = item.get("id")
        if task_id is not None:
            indexed[str(task_id)] = item
    return indexed


def diff_per_task(
    base_per_task: Sequence[Mapping[str, Any]],
    current_per_task: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """对比两份逐任务结果，产出回归 / 改善 / 变化 / 不变 / 新增 / 消失。

    * ``regressed``: ``pass`` → ``fail``
    * ``improved``: ``fail`` → ``pass``
    * ``changed``: 结果发生变化的任务（= ``regressed ∪ improved``）
    * ``unchanged``: 两份都在且结果一致的任务
    * ``added`` / ``removed``: 仅在一边出现的任务 id（任务集成员变化）
    """
    base_map = _index_by_id(base_per_task)
    curr_map = _index_by_id(current_per_task)
    base_ids = set(base_map)
    curr_ids = set(curr_map)

    added = sorted(curr_ids - base_ids)
    removed = sorted(base_ids - curr_ids)

    regressed: list[str] = []
    improved: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for task_id in sorted(base_ids & curr_ids):
        base_passed = bool(base_map[task_id].get("passed"))
        curr_passed = bool(curr_map[task_id].get("passed"))
        if base_passed and not curr_passed:
            regressed.append(task_id)
            changed.append(task_id)
        elif not base_passed and curr_passed:
            improved.append(task_id)
            changed.append(task_id)
        else:
            unchanged.append(task_id)

    notes: list[str] = []
    if added:
        notes.append(f"[任务集变更] 新出现的任务 {len(added)} 条：{added}")
    if removed:
        notes.append(f"[任务集变更] 消失的任务 {len(removed)} 条：{removed}")

    return {
        "regressed": regressed,
        "improved": improved,
        "changed": changed,
        "unchanged": unchanged,
        "added": added,
        "removed": removed,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# 主入口：diff
# --------------------------------------------------------------------------- #
def diff(
    current: BaselineModel,
    base: BaselineModel,
    tolerances: Tolerances | None = None,
    *,
    force: bool = False,
) -> BaselineDiff:
    """对比 ``current``（本次）与 ``base``（基线）。

    Args:
        current: 本次运行基线模型。
        base: 参照基线模型。
        tolerances: 容忍带；``None`` 时按任务数自动推导（``repeat > 1`` 再按 2σ 放宽）。
        force: 越过可比性守卫（``--force-compare``）——仍保留警告，但 ``comparable`` 置真。

    Returns:
        :class:`BaselineDiff`：可比性警告 + 逐指标 delta + 逐任务回归/改善清单。
    """
    hard_warnings = comparability_warnings(base, current)
    per = diff_per_task(base.per_task, current.per_task)
    absolute_tolerances = resolve_tolerances(current, base, tolerances)

    metric_deltas = {
        key: compute_metric_delta(
            key,
            _metric_value(base.metrics, key),
            _metric_value(current.metrics, key),
            absolute_tolerances.get(key),
        )
        for key in METRIC_KEYS
    }

    warnings = list(hard_warnings) + list(per["notes"])
    return BaselineDiff(
        comparability_warnings=warnings,
        comparable=(not hard_warnings) or force,
        metric_deltas=metric_deltas,
        regressed=list(per["regressed"]),
        improved=list(per["improved"]),
        changed=list(per["changed"]),
        unchanged=list(per["unchanged"]),
        aborted_prematurely=False,
    )


# --------------------------------------------------------------------------- #
# Markdown 渲染
# --------------------------------------------------------------------------- #
def _fmt_value(key: str, value: float | None) -> str:
    """把指标值渲染成人可读字符串（``None`` → ``—``）。"""
    if value is None:
        return "—"
    if key in (METRIC_PASS_RATE, METRIC_TOOL_ACCURACY):
        return f"{value * 100:.1f}%"
    if key == METRIC_AVG_STEPS:
        return f"{value:.2f}"
    if key == METRIC_AVG_COST:
        return f"{value:.4f}"
    if key == METRIC_P95_LATENCY:
        return f"{value:.0f} ms"
    return f"{value:.4f}"


def _fmt_delta(key: str, delta: MetricDelta) -> str:
    """把绝对 delta 渲染成人可读字符串（带单位）。"""
    if delta.delta is None:
        return "—"
    if key in (METRIC_PASS_RATE, METRIC_TOOL_ACCURACY):
        return f"{delta.delta * 100:+.1f} pp"
    if key == METRIC_AVG_STEPS:
        return f"{delta.delta:+.2f}"
    if key == METRIC_AVG_COST:
        return f"{delta.delta:+.4f}"
    if key == METRIC_P95_LATENCY:
        return f"{delta.delta:+.0f} ms"
    return f"{delta.delta:+.4f}"


def _fmt_pct(delta: MetricDelta) -> str:
    """把相对 delta 渲染成百分比字符串（``delta_pct`` 为 ``None`` → ``—``）。"""
    if delta.delta_pct is None:
        return "—"
    return f"{delta.delta_pct * 100:+.1f}%"


def _fmt_tolerance(key: str, delta: MetricDelta) -> str:
    """渲染容忍带（已折算为绝对单位）；``None`` → ``—``。"""
    if delta.tolerance is None:
        return "—"
    return _fmt_value(key, delta.tolerance).lstrip("+")


def render_markdown(
    diff_result: BaselineDiff,
    *,
    base: BaselineModel | None = None,
    current: BaselineModel | None = None,
    title: str = "P2 评测台 · 基线回归报告",
) -> str:
    """渲染人可读的 Markdown 报告（供 ``--compare`` 使用）。

    内容（设计文档 §3.4）：
    1. 可比性守卫（若有警告，最前，醒目）；
    2. 逐指标 delta 表格（基线 → 当前，Δ / Δ% / 容忍带 / 判定）；
    3. 回归/改善清单；
    4. 失败任务明细（需传入 ``current``）。

    **不美化数字**：指标变差如实显示；带内变化标注「无显著变化」而非「变好」。
    """
    lines: list[str] = [f"# {title}", "", f"生成时间：{iso_now()}", ""]

    # ---- 1. 可比性守卫（最先输出）
    lines.append("## 1. 可比性守卫")
    lines.append("")
    if diff_result.comparability_warnings:
        verdict = "可直接归因" if diff_result.comparable else "**不可直接比较（delta 仅供参考）**"
        lines.append(f"⚠️ 结论：{verdict}")
        lines.append("")
        for warning in diff_result.comparability_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("✅ 模型 / Prompt 哈希 / 任务集哈希一致，delta 可直接归因。")
    lines.append("")

    # ---- 2. 指标对比
    lines.append("## 2. 指标对比")
    lines.append("")
    lines.append("| 指标 | 基线 | 当前 | Δ | Δ% | 容忍带 | 判定 |")
    lines.append("|------|------|------|---|----|--------|------|")
    for key in METRIC_KEYS:
        delta = diff_result.metric_deltas.get(key)
        if delta is None:
            continue
        label = _METRIC_LABELS.get(key, key)
        judgment = _JUDGMENT_LABELS.get(classify_metric_change(key, delta), "—")
        lines.append(
            f"| {label} | {_fmt_value(key, delta.baseline)} | {_fmt_value(key, delta.current)} "
            f"| {_fmt_delta(key, delta)} | {_fmt_pct(delta)} | {_fmt_tolerance(key, delta)} | {judgment} |"
        )
    lines.append("")

    # ---- 3. 回归 / 改善
    lines.append("## 3. 回归 / 改善")
    lines.append("")
    lines.append(
        f"- **回归（pass→fail）** {len(diff_result.regressed)} 条："
        + (", ".join(diff_result.regressed) or "无")
    )
    lines.append(
        f"- **改善（fail→pass）** {len(diff_result.improved)} 条："
        + (", ".join(diff_result.improved) or "无")
    )
    if diff_result.unchanged:
        lines.append(f"- 结果未变 {len(diff_result.unchanged)} 条")
    lines.append("")

    # ---- 任务集成员变化（需 base/current）
    if base is not None and current is not None:
        per = diff_per_task(base.per_task, current.per_task)
        if per["added"] or per["removed"]:
            lines.append("## 3.1 任务集成员变化")
            lines.append("")
            lines.append(f"- 新增：{per['added'] or '无'}")
            lines.append(f"- 消失：{per['removed'] or '无'}")
            lines.append("")

    # ---- 4. 失败任务明细
    if current is not None:
        lines.append("## 4. 失败任务明细（当前运行）")
        lines.append("")
        failed = [item for item in current.per_task if not item.get("passed")]
        if not failed:
            lines.append("无失败任务。")
        else:
            lines.append("| 任务 | 类别 | 状态 | 失败断言 | 错误 |")
            lines.append("|------|------|------|----------|------|")
            for item in failed:
                failed_names = item.get("failed_assertions") or []
                error = item.get("error") or ""
                lines.append(
                    f"| {item.get('id', '')} | {item.get('category', '')} | {item.get('status', '')} "
                    f"| {', '.join(str(x) for x in failed_names) or '—'} | {error} |"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "BASELINE_DIR",
    "DEFAULT_CODE_PATTERNS",
    "DEFAULT_SCHEMA_VERSION",
    "DEFAULT_TEMPERATURE",
    "PROMPTS_DIR",
    "BaselineError",
    "baseline_path",
    "build_baseline",
    "classify_metric_change",
    "code_metadata",
    "comparability_warnings",
    "compute_metric_delta",
    "config_metadata",
    "diff",
    "diff_per_task",
    "iso_now",
    "load_baseline",
    "make_per_task_entry",
    "metric_tolerance",
    "model_metadata",
    "new_run_id",
    "now_cn",
    "prompts_metadata",
    "render_markdown",
    "resolve_tolerances",
    "save_baseline",
    "sha256_file",
    "sha256_text",
    "taskset_metadata",
]
