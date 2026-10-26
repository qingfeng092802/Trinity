"""实验矩阵配置（M3 · T2）：ArmConfig + YAML 装配 + **严格单变量强制校验**。

为什么这层要用代码强制（m3_design.md D11）：v3 的核心卖点是"每个组件的独立贡献都能量化"，
而人写 YAML 时最容易犯的错就是"顺手多改一个旋钮"——一个臂同时改了分块和融合，
跑出来的提升就永远说不清归因谁。所以这里不是"建议单变量"，是**多改一个字段就拒绝执行**。

设计要点：

1. **臂 = 基线 + overrides**。YAML 里每条臂只写 ``changes``（相对基线的差分），
   因此"改动超过 1 个字段"从构造上就是可疑的，而不是靠事后发现；
2. **惰性字段不参与归因**。``rrf_k`` 在 ``fusion=weighted`` 下根本不被读取，
   ``temperature`` 在纯检索臂（phase=A）下无意义 —— 改一个两边都不生效的字段等于没改，
   但改一个"一边生效一边不生效"的字段是偷偷换了实验条件，必须拦；
3. **``index_key()`` 决定索引能否复用**。§8.3 实测：ONNX 重建 41 s、torch 重建 287 s、
   重排臂 15.7 min，所以 runner 必须按 ``index_key`` 分组跑臂（同组只建一次库），
   否则光索引就白烧 4 倍时间；
4. **组合臂（E6 全链路最优）显式声明 ``role="combo"``**，它天生是多变量，
   不允许伪装成单变量臂来报"某组件贡献 X pp"。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "ARM_FIELD_NAMES",
    "BASELINE_DEFAULTS",
    "IDENTITY_FIELDS",
    "ArmConfig",
    "ExperimentError",
    "Matrix",
    "build_matrix",
    "load_matrix",
    "phase_arms",
    "resolve_arm",
]

Role = Literal["baseline", "ablation", "combo"]
Phase = Literal["A", "B"]

#: 这些字段只描述"这是哪条臂、什么时候跑"，不是实验变量，永远不进 diff
IDENTITY_FIELDS: frozenset[str] = frozenset({"arm_id", "role", "phase", "notes"})

#: 基线默认值 = M2 已交付配置（ONNX bge-small + 加权融合 0.4:0.6 + heading 分块 + 无重排）
BASELINE_DEFAULTS: dict[str, Any] = {
    "embed_backend": "fastembed",
    "embed_model": "BAAI/bge-small-zh-v1.5",
    "chunk_mode": "heading",
    "chunk_size": 500,
    "chunk_overlap": 80,
    "fusion": "weighted",
    "bm25_weight": 0.4,
    "vector_weight": 0.6,
    "rrf_k": 60,
    "fetch_k": 20,
    "top_k": 5,
    "reranker": None,
    "rerank_backend": "transformers",
    "prompt": None,
    "temperature": 0.0,
    "jieba_userdict": False,
}


class ExperimentError(ValueError):
    """实验矩阵非法：多变量、typo、缺基线等，一律早失败。"""


@dataclass(frozen=True, slots=True)
class ArmConfig:
    """一条实验臂的完整、可哈希配置快照。

    Attributes:
        arm_id: 臂标识（矩阵内唯一），如 ``A-E2a-3``。
        role: ``baseline`` 只有一个；``ablation`` 强制单变量；``combo`` 允许多变量但须显式声明。
        phase: ``A`` 只跑检索侧（零 LLM 成本）；``B`` 需要生成与 judge。
        embed_backend / embed_model: 嵌入运行时与模型。**跨模型对比必须锁同一 backend**
            （实测 fastembed 只支持 bge-small-zh，base/large 会 ``ValueError``）。
        fusion: ``weighted`` 为 M2 既有口径；``rrf`` 为 M3 新增；
            ``bm25_only`` / ``vector_only`` 是单路对照（不等价于把权重设成 1/0，
            因为单路臂不做融合，语义更清楚）。
        reranker: ``None`` 表示不精排；否则为模型名。
        temperature: 钉死 0.0。它是被控制的常量而不是旋钮，改动会让"生成结果不可复现"，
            校验会把它当成一次真实变量变更来计数。
    """

    arm_id: str
    role: Role = "ablation"
    phase: Phase = "A"
    notes: str = ""

    embed_backend: Literal["fastembed", "torch"] = "fastembed"
    embed_model: str = "BAAI/bge-small-zh-v1.5"

    chunk_mode: Literal["heading", "fixed", "semantic"] = "heading"
    chunk_size: int = 500
    chunk_overlap: int = 80

    fusion: Literal["weighted", "rrf", "bm25_only", "vector_only"] = "weighted"
    bm25_weight: float = 0.4
    vector_weight: float = 0.6
    rrf_k: int = 60

    fetch_k: int = 20
    top_k: int = 5

    reranker: str | None = None
    rerank_backend: Literal["transformers", "sentence-transformers"] = "transformers"

    prompt: str | None = None
    temperature: float = 0.0

    jieba_userdict: bool = False

    def __post_init__(self) -> None:
        if not self.arm_id or not self.arm_id.strip():
            raise ExperimentError("arm_id 不能为空")
        if self.role not in ("baseline", "ablation", "combo"):
            raise ExperimentError(f"未知 role：{self.role!r}")
        if self.phase not in ("A", "B"):
            raise ExperimentError(f"未知 phase：{self.phase!r}")
        if self.top_k < 1:
            raise ExperimentError(f"top_k 必须 ≥1，收到 {self.top_k}")
        if self.fetch_k < self.top_k:
            raise ExperimentError(f"fetch_k（{self.fetch_k}）必须 ≥ top_k（{self.top_k}），否则精排无候选空间")
        if self.chunk_size <= self.chunk_overlap:
            raise ExperimentError(f"chunk_overlap（{self.chunk_overlap}）必须 < chunk_size（{self.chunk_size}）")
        if self.rrf_k < 1:
            raise ExperimentError(f"rrf_k 必须 ≥1，收到 {self.rrf_k}")
        if self.fusion == "weighted" and abs(self.bm25_weight + self.vector_weight - 1.0) > 1e-6:
            # 与 config.py 的 _validate_rag_params 相反：这里**不归一、不静默 warn**，
            # 因为归一化会把实验参数改掉（m3_design.md D8 的第 6 条陷阱）
            raise ExperimentError(
                f"weighted 融合下 bm25_weight+vector_weight 必须 = 1，"
                f"实得 {self.bm25_weight + self.vector_weight:.3f}"
            )
        if self.phase == "B" and not self.prompt:
            raise ExperimentError(f"臂 {self.arm_id}：phase=B 必须指定 prompt 版本")
        if self.phase == "A" and self.prompt:
            raise ExperimentError(f"臂 {self.arm_id}：phase=A 不该带 prompt（检索臂零 LLM 调用）")

    # ------------------------------------------------------------------ #
    def active_fields(self) -> frozenset[str]:
        """本臂里"真的会被代码读到"的字段。惰性字段改了也不影响行为。"""
        active = {
            "embed_backend",
            "embed_model",
            "chunk_mode",
            "chunk_size",
            "chunk_overlap",
            "fusion",
            "fetch_k",
            "top_k",
            "reranker",
            "jieba_userdict",
        }
        if self.fusion == "weighted":
            active |= {"bm25_weight", "vector_weight"}
        if self.fusion == "rrf":
            active.add("rrf_k")
        if self.reranker is not None:
            active.add("rerank_backend")
        if self.phase == "B":
            active |= {"prompt", "temperature"}
        return frozenset(active)

    def experiment_fields(self) -> dict[str, Any]:
        """全部实验变量（不含身份字段）。"""
        return {k: v for k, v in asdict(self).items() if k not in IDENTITY_FIELDS}

    def diff_from(self, baseline: "ArmConfig") -> dict[str, tuple[Any, Any]]:
        """与基线逐项对比，返回 ``{字段: (基线值, 本臂值)}``（含惰性字段）。"""
        mine, theirs = self.experiment_fields(), baseline.experiment_fields()
        return {
            key: (theirs[key], mine[key])
            for key in mine
            if key in theirs and mine[key] != theirs[key]
        }

    def effective_changes(self, baseline: "ArmConfig") -> dict[str, tuple[Any, Any]]:
        """真正影响行为的改动。

        规则：某字段两边都惰性 → 不算改动（改了也是空操作，另由 :meth:`validate` 提示）；
        一边生效一边不生效 → **算改动**（等于偷偷换了实验条件）。
        """
        changes = self.diff_from(baseline)
        mine, theirs = self.active_fields(), baseline.active_fields()
        return {k: v for k, v in changes.items() if k in mine or k in theirs}

    def inert_changes(self, baseline: "ArmConfig") -> dict[str, tuple[Any, Any]]:
        """两边都不生效的改动（空操作）。不违规，但必须在清单里露出来。"""
        changes = self.diff_from(baseline)
        mine, theirs = self.active_fields(), baseline.active_fields()
        return {k: v for k, v in changes.items() if k not in mine and k not in theirs}

    def index_key(self, corpus_fingerprint: str = "") -> str:
        """决定"同一份索引能不能复用"的指纹。

        只有影响**入库内容**的字段进这个键：嵌入后端/模型、分块策略与参数、jieba 词典
        （它改变 BM25 词条，从而改变倒排索引）。融合方式、top_k、重排、prompt 都只影响
        查询侧，换它们不必重建 —— §8.3 的排期分组就靠这个键。
        """
        payload = {
            "corpus": corpus_fingerprint,
            "embed_backend": self.embed_backend,
            "embed_model": self.embed_model,
            "chunk_mode": self.chunk_mode,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "jieba_userdict": self.jieba_userdict,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

    def validate(self, baseline: "ArmConfig") -> list[str]:
        """返回该臂的违规说明；空列表即合法。"""
        problems: list[str] = []
        effective = self.effective_changes(baseline)
        inert = self.inert_changes(baseline)

        if self.role == "baseline":
            if effective:
                problems.append(f"基线臂 {self.arm_id} 不该与自身有差异：{sorted(effective)}")
            return problems

        if not effective and not inert:
            problems.append(f"臂 {self.arm_id} 与基线完全相同，跑了没有任何信息量")
        elif not effective and inert:
            problems.append(
                f"臂 {self.arm_id} 只改了惰性字段 {sorted(inert)}，"
                f"在当前 fusion/reranker/phase 下这些值根本不被读取，等价于没改"
            )
        elif self.role == "ablation" and len(effective) > 1:
            detail = "、".join(f"{k}: {a!r}→{b!r}" for k, (a, b) in sorted(effective.items()))
            problems.append(
                f"臂 {self.arm_id} 声明为单变量消融，却实际改了 {len(effective)} 个生效字段 → {detail}。"
                f"要么拆成多条臂，要么显式改成 role=combo 并在报告里放弃逐组件归因"
            )
        elif self.role == "combo" and not self.notes:
            problems.append(f"组合臂 {self.arm_id} 必须用 notes 写清它组合了哪几项，便于报告归因")

        if inert and effective:
            problems.append(
                f"臂 {self.arm_id} 除生效改动外还带着惰性改动 {sorted(inert)}，"
                f"YAML 里删掉它们，别把无意义差异带进报表"
            )
        return problems


ARM_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in fields(ArmConfig))


def resolve_arm(
    arm_id: str,
    changes: Mapping[str, Any],
    *,
    parent: ArmConfig,
    role: Role = "ablation",
    phase: Phase | str | None = None,
    notes: str = "",
) -> ArmConfig:
    """父配置 + overrides → 一条臂。键写错立刻报错，绝不静默忽略。

    ``phase`` 是臂级属性（决定这条臂要不要花 API 钱），与 ``role`` 一样在 YAML 条目上写，
    **不走 changes** —— changes 里只允许出现实验变量。
    """
    unknown = sorted(set(changes) - ARM_FIELD_NAMES)
    if unknown:
        raise ExperimentError(
            f"臂 {arm_id} 含未知字段 {unknown}；可用字段见 ArmConfig"
            f"（拼错一个字母就会让该臂静默退化成基线，所以这里直接拒绝）"
        )
    frozen = {"arm_id", "role", "phase", "notes"} & set(changes)
    if frozen:
        raise ExperimentError(f"臂 {arm_id} 试图通过 changes 覆盖身份字段 {sorted(frozen)}")
    return replace(
        parent,
        arm_id=arm_id,
        role=role,
        phase=parent.phase if phase is None else str(phase),
        notes=notes,
        **dict(changes),
    )


@dataclass(frozen=True, slots=True)
class Matrix:
    """一次消融实验的完整矩阵。

    每个 **phase 各需一个基线**：Phase A 的臂不测生成，Phase B 才引入 prompt/温度，
    拿 Phase A 基线去比 Phase B 臂会把"开始测生成"误判成一次普通变量变更。
    """

    baseline: ArmConfig
    arms: tuple[ArmConfig, ...]
    source: str = ""
    #: arm_id → 参照臂 arm_id。默认走本 phase 基线；"参照物不是生产基线"的臂
    #: （如跨模型对比必须锁同一后端）要显式声明，见 ``reference_for``。
    references: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.baseline.role != "baseline":
            raise ExperimentError("baseline 臂的 role 必须是 baseline")

    @property
    def all_arms(self) -> tuple[ArmConfig, ...]:
        """基线在前、其余按 arm_id 排序 —— 报表顺序稳定，复跑才能逐位比对。"""
        return tuple(sorted(self._unique_arms(), key=lambda a: (a.role != "baseline", a.arm_id)))

    def _unique_arms(self) -> list[ArmConfig]:
        seen: dict[str, ArmConfig] = {}
        for arm in (self.baseline, *self.arms):
            seen.setdefault(arm.arm_id, arm)
        return list(seen.values())

    def baseline_for(self, arm: ArmConfig) -> ArmConfig:
        """该臂所属 phase 的参照基线。"""
        for item in self._unique_arms():
            if item.role == "baseline" and item.phase == arm.phase:
                return item
        return self.baseline

    def reference_for(self, arm: ArmConfig) -> ArmConfig:
        """该臂的归因参照物：显式 ``reference`` 优先，否则本 phase 基线。

        为什么不能一律对基线比：§8.3 实测 fastembed 只支持 bge-small-zh，
        所以"比 bge-small 与 bge-base 两个模型"只能是 **torch-small vs torch-base** 这一对。
        硬拿 ONNX 生产基线当参照，那条臂就同时改了后端和模型两件事 ——
        而这正是本模块要拦的错误。
        """
        target = self.references.get(arm.arm_id)
        if target is None:
            return self.baseline_for(arm)
        for item in self._unique_arms():
            if item.arm_id == target:
                return item
        raise ExperimentError(f"臂 {arm.arm_id} 的 reference 指向不存在的臂 {target!r}")

    def phases(self) -> tuple[str, ...]:
        return tuple(sorted({arm.phase for arm in self.all_arms}))

    def validate(self) -> list[str]:
        """整个矩阵的违规清单（一次全报，别让人一轮轮试错）。"""
        problems: list[str] = []
        arms = self._unique_arms()
        all_ids = [self.baseline.arm_id, *(arm.arm_id for arm in self.arms)]
        duplicated = sorted({arm_id for arm_id in all_ids if all_ids.count(arm_id) > 1})
        if duplicated:
            problems.append(f"arm_id 重复（含与基线同名）：{duplicated}")

        for phase in self.phases():
            baselines = [arm for arm in arms if arm.role == "baseline" and arm.phase == phase]
            if len(baselines) != 1:
                problems.append(
                    f"phase={phase} 必须有且仅有一个基线臂，实得 {[b.arm_id for b in baselines]}"
                )
        for arm in arms:
            if arm.role == "baseline":
                continue
            try:
                reference = self.reference_for(arm)
            except ExperimentError as exc:
                problems.append(str(exc))
                continue
            if reference.phase != arm.phase:
                problems.append(
                    f"臂 {arm.arm_id}（phase={arm.phase}）的参照 {reference.arm_id}"
                    f"（phase={reference.phase}）跨了阶段，指标集不同不可比"
                )
            problems.extend(arm.validate(reference))
        return problems

    def index_groups(self) -> dict[str, list[ArmConfig]]:
        """按 ``index_key`` 分组，供 runner 复用索引（每组只建一次库）。"""
        groups: dict[str, list[ArmConfig]] = {}
        for arm in self.all_arms:
            groups.setdefault(arm.index_key(), []).append(arm)
        return groups

    def summary_lines(self) -> Iterable[str]:
        """人读摘要（启动时打印，让人在花钱前看见实验设计长什么样）。"""
        for arm in self.all_arms:
            reference = self.reference_for(arm)
            changes = arm.effective_changes(reference)
            rendered = "（基线）" if arm.role == "baseline" else "、".join(
                f"{k}={b!r}" for k, (_, b) in sorted(changes.items())
            )
            note = "" if arm.role == "baseline" else f"   [参照 {reference.arm_id}]"
            yield f"  {arm.arm_id:<16} phase={arm.phase} role={arm.role:<8} {rendered}{note}"


def load_matrix(path: Path | str) -> Matrix:
    """从 YAML 读实验矩阵。

    文件结构（``role`` / ``phase`` / ``reference`` 是臂级属性，只能写在条目上；
    ``changes`` 里**只允许出现实验变量**，写错字段名立刻报错）::

        baseline:
          arm_id: A-BASE
          phase: A
          overrides: {}              # 可选：再覆盖 BASELINE_DEFAULTS
        arms:
          - arm_id: A-E2a-3
            changes: {fusion: rrf}                        # 单变量：只改融合
          - arm_id: A-E1-model-1
            reference: A-E1-model-0                     # 归因参照物不是生产基线
            changes: {embed_model: BAAI/bge-base-zh-v1.5}
          - arm_id: B-E4a
            phase: B
            changes: {prompt: answer_cot}
          - arm_id: A-E6
            role: combo
            notes: 语义分块+混合+重排+溯源，组合臂不做逐组件归因
            changes: {fusion: rrf, reranker: bge-reranker-base}
    """
    try:
        import yaml  # noqa: PLC0415 - 只有走 YAML 才需要
    except ImportError as exc:  # pragma: no cover
        raise ExperimentError(f"需要 PyYAML 读取实验矩阵：{exc}") from exc

    file_path = Path(path)
    if not file_path.is_file():
        raise ExperimentError(f"实验矩阵文件不存在：{file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ExperimentError(f"{file_path} 顶层必须是 mapping，实得 {type(raw).__name__}")
    return build_matrix(raw, source=str(file_path))


def build_matrix(raw: Mapping[str, Any], *, source: str = "") -> Matrix:
    """从已解析的 dict 装配矩阵（脚本与单测共用，不必落 YAML 文件）。"""
    baseline_raw = raw.get("baseline")
    if not isinstance(baseline_raw, Mapping):
        raise ExperimentError("矩阵必须有 baseline: 段")
    baseline_id = str(baseline_raw.get("arm_id", "A-BASE"))
    overrides = dict(baseline_raw.get("overrides") or {})
    bad = sorted(set(overrides) - ARM_FIELD_NAMES)
    if bad:
        raise ExperimentError(f"baseline.overrides 含未知字段 {bad}")
    try:
        baseline = ArmConfig(arm_id=baseline_id, role="baseline",
                             phase=str(baseline_raw.get("phase", "A")), **overrides)
    except TypeError as exc:
        raise ExperimentError(f"基线臂参数非法：{exc}") from exc

    arms: list[ArmConfig] = []
    references: dict[str, str] = {}
    #: 装配顺序 = YAML 书写顺序；``reference`` 既是归因参照物，也是**继承的父配置**。
    #: 所以 A-E1-torch-base 写在 A-E1-backend 之后，只声明 embed_model 就能拿到
    #: 「torch + bge-base」——若把 reference 只当比较标签用，它会退化成「ONNX + bge-base」，
    #: 一个字段没多改，实验条件却完全错了。
    built: dict[str, ArmConfig] = {baseline.arm_id: baseline}
    for entry in raw.get("arms") or []:
        if not isinstance(entry, Mapping):
            raise ExperimentError(f"arms 的每一项必须是 mapping，实得 {type(entry).__name__}")
        arm_id = str(entry.get("arm_id", ""))
        if not arm_id:
            raise ExperimentError("arms 有条目缺 arm_id")
        if arm_id in built:
            raise ExperimentError(f"arm_id 重复：{arm_id}")
        role = str(entry.get("role", "ablation"))
        ref_name = entry.get("reference")
        parent = baseline
        if ref_name is not None:
            references[arm_id] = str(ref_name)
            if str(ref_name) not in built:
                raise ExperimentError(
                    f"臂 {arm_id} 的 reference={ref_name!r} 还没定义；"
                    f"被参照的臂必须在 YAML 里写在它前面（reference 同时决定继承的父配置）"
                )
            parent = built[str(ref_name)]
        phase = str(entry.get("phase", parent.phase))
        try:
            arm = resolve_arm(
                arm_id,
                dict(entry.get("changes") or {}),
                parent=parent,
                role=role,
                phase=phase,
                notes=str(entry.get("notes", "")),
            )
        except ExperimentError as exc:
            raise ExperimentError(f"{arm_id}: {exc}") from exc
        except TypeError as exc:
            raise ExperimentError(f"{arm_id}: 参数类型非法：{exc}") from exc
        arms.append(arm)
        built[arm_id] = arm
    if not arms:
        raise ExperimentError("矩阵里一条对照臂都没有，没有可跑的实验")
    return Matrix(baseline=baseline, arms=tuple(arms), source=source, references=references)


def phase_arms(matrix: Matrix, phase: Phase) -> Sequence[ArmConfig]:
    """挑出某一阶段的臂（Phase A 先跑、零成本，Phase B 才花钱）。"""
    return tuple(arm for arm in matrix.all_arms if arm.phase == phase)
