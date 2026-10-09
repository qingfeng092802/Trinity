"""全局配置（pydantic-settings 单一真源）。

三条纪律（设计文档 §9）：

1. **默认值只有一个真相**：编排参数由 :meth:`WorkflowConfig.from_settings`
   从这里推导，禁止在第二处再写一份默认值。
2. **SecretStr 判空统一写法**：``settings.api_auth_token.get_secret_value().strip()``
   —— ``bool(SecretStr)`` 取决于 ``__len__``，语义隐晦，禁止直接真值判断。
3. **路径一律解析成绝对路径**：``workspace_dir`` 与 ``db_url`` 里的相对路径
   都相对 ``PROJECT_ROOT`` 解析，避免「从哪个目录启动」改变行为。

环境变量命名与字段一一对应（大小写不敏感）：``LLM_API_KEY`` → ``llm_api_key``、
``DB_URL`` → ``db_url``、``API_MAX_CONCURRENT_TASKS`` → ``api_max_concurrent_tasks`` …
可选的 ``.env`` 文件在进程启动时加载（存在才读，缺失不报错）。
"""

from __future__ import annotations

import logging
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 项目根目录（config.py 所在目录）
PROJECT_ROOT: Path = Path(__file__).resolve().parent

#: SQLite 连接串前缀
_SQLITE_PREFIX = "sqlite:///"

#: 默认数据目录
DATA_DIR: Path = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """平台全部可调参数。

    所有字段都可以用同名环境变量覆盖（如 ``LLM_API_KEY``、``DB_URL``）；
    ``.env`` 文件存在时自动加载，优先级：环境变量 > .env > 字段默认值。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ LLM --
    llm_provider: str = Field(default="deepseek", description="LLM 供应商标识")
    llm_api_key: SecretStr = Field(default=SecretStr(""), description="供应商 API Key")
    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1", description="OpenAI 兼容端点（自动去尾斜杠）"
    )
    llm_model_large: str = Field(
        default="deepseek-flash", description="planner/reviewer/judge 用的强模型"
    )
    llm_model_small: str = Field(
        default="deepseek-flash", description="executor 用的快模型"
    )
    llm_json_mode: bool = Field(
        default=True, description="优先尝试 response_format=json_object（不支持时自动降级）"
    )
    llm_timeout: float = Field(default=120.0, gt=0, description="单次 LLM 请求超时（秒）")
    llm_max_retries: int = Field(default=3, ge=1, le=10, description="瞬时错误的最大尝试次数")
    #: 兜底单价（元 / 100 万 token），仅当模型不在 core.llm.adapter.MODEL_PRICES 时使用。
    #: 单位刻意与 ``MODEL_PRICES``、``.env.example`` 以及消费方的公式
    #: ``token / 1_000_000 × 单价``（``core/llm/adapter.py``、``api/runner.py``）保持一致。
    #: 默认值取 deepseek-flash 的官方高峰价折算人民币，与表内同价 ⇒ 「表内」与「兜底」
    #: 两条路径对同一官方价必须算出同一个成本（用例见 tests/unit/test_adapter_json.py）。
    #: ⚠️ 这里曾经写成 ``2.13e-6`` 并标注「元/token」：数值本身是**每 token** 的价，
    #: 却被按「每 100 万 token」用，于是**没配 .env 的人**会把 100 万 token 估成
    #: 1e-5 元 —— 低估 10⁶ 倍。带 ``.env``（填 2.0/8.0）的机器上看不出问题。
    llm_price_in: float = Field(default=2.13, ge=0, description="输入单价兜底值（元 / 100 万 token）")
    llm_price_out: float = Field(default=8.52, ge=0, description="输出单价兜底值（元 / 100 万 token）")

    # ------------------------------------------------ 多家 Key / 多家端点（换供应商）--
    #: 换供应商用的另两把 Key（方案 L-1：每家一把环境变量 Key，页面**只读**展示脱敏态）。
    #: ⚠️ 三条硬约束：① 接口**不接收**运行时传入的 Key；② 这几个字段的明文**永不**进响应、
    #: 日志与异常串，能出现的只有 ``core.llm.providers.masked()`` 之后的脱敏串；
    #: ③ 本文件（``.env``）**永远不被代码改写** —— 覆盖只活到进程重启（``core/llm/runtime.py``）。
    #: 空串 = 那一家没配 ⇒ ``POST /models/override`` 当场拒，并说清是哪家缺；
    #: 不这么做的话症状会挪到"任务失败：未配置 LLM_API_KEY"，用户看不出是设置没生效。
    #: ⚠️ 加一家要**两处同改**：``core/llm/providers.py`` 的 ``PROVIDERS`` 加一行，
    #: 这里加两行。``extra="ignore"`` 会把没登记的 ``LLM_API_KEY_XXX`` 静默丢掉，
    #: 少了这里的字段就是"环境变量明明配了却没生效"，而且不报错。
    llm_api_key_zhipu: SecretStr = Field(
        default=SecretStr(""), description="智谱 Key（环境变量 LLM_API_KEY_ZHIPU）"
    )
    llm_base_url_zhipu: str = Field(
        default="", description="智谱端点覆盖（LLM_BASE_URL_ZHIPU）；空=用注册表里的官网端点"
    )
    llm_api_key_qwen: SecretStr = Field(
        default=SecretStr(""), description="千问 Key（环境变量 LLM_API_KEY_QWEN）"
    )
    llm_base_url_qwen: str = Field(
        default="", description="千问端点覆盖（LLM_BASE_URL_QWEN）；空=用注册表里的官网端点"
    )

    # -------------------------------------------------------------- 编排 ----
    max_iterations: int = Field(default=5, ge=1, le=50, description="executor 整轮执行上限")
    review_threshold: int = Field(default=7, ge=0, le=10, description="reviewer 通过线")

    # -------------------------------------------------------------- 工具 ----
    tool_timeout: int = Field(default=30, gt=0, description="单次工具调用超时（秒）")
    tool_retry: int = Field(default=2, ge=0, description="工具失败重试次数")
    enable_hitl: bool = Field(
        default=False,
        description=(
            "高危工具是否**发起人工确认**。⚠️ 它不控制有没有门禁：关掉它不等于放行，"
            "而是「没有人可问」⇒ 高危调用一律拒绝（fail-closed 与默认值无关，"
            "见 core/tools/registry.py::_hitl_denial 与 api/routes/tools.py 的决策表）。"
            "2026-10-02 修 Q5-01 之前，False 在编排通道上是 fail-open。"
        ),
    )

    # -------------------------------------------------------------- 存储 ----
    db_url: str = Field(
        default="sqlite:///data/trinity.db", description="SQLAlchemy 连接串"
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0", description="Redis 连接串（不可用自动降级内存）"
    )
    cache_ttl_seconds: int = Field(default=3600, ge=1, description="缓存默认存活秒数")

    # -------------------------------------------------------- 工作区/日志 ----
    workspace_dir: Path = Field(
        default=DATA_DIR / "workspace", description="工具沙箱根目录（自动转绝对路径）"
    )
    log_level: str = Field(default="INFO", description="日志级别（DEBUG/INFO/WARNING/ERROR）")
    log_dir: Path = Field(default=DATA_DIR / "logs", description="日志文件目录")

    # ---------------------------------------------------------------- API ----
    api_host: str = Field(default="127.0.0.1", description="REST API 监听地址")
    api_port: int = Field(default=8000, ge=1, le=65535, description="REST API 监听端口")
    api_max_concurrent_tasks: int = Field(
        default=3, ge=1, le=64, description="同时执行的任务数上限"
    )
    api_queue_max_size: int = Field(default=50, ge=1, description="等待队列容量")
    api_sse_heartbeat_seconds: float = Field(
        default=15.0, gt=0, description="SSE 心跳间隔（秒）"
    )
    api_auth_token: SecretStr = Field(
        default=SecretStr(""), description="Bearer Token；为空表示免鉴权（仅本机部署）"
    )
    api_block_peak_tasks: bool = Field(
        default=False, description="高峰计费时段是否硬拦任务提交"
    )
    api_allow_high_risk_override: bool = Field(
        default=False, description="允许 ?approve_high_risk=true 放行高危工具（默认 fail-closed）"
    )

    # ---------------------------------------------------- 知识库 / RAG ----
    knowledge_dir: Path = Field(
        default=DATA_DIR / "knowledge",
        description="知识库根目录（files/ 子目录存上传原件），相对路径相对 PROJECT_ROOT",
    )
    embedding_provider: Literal["local", "api"] = Field(
        default="local",
        description="embedding 提供商；M2 仅实现 local，api 为接口预留",
    )
    embedding_backend: Literal["fastembed", "torch"] = Field(
        default="fastembed",
        description=(
            "本地向量化的运行时：fastembed=ONNX（M2 生产档，实测最快但只支持 bge-small-zh）；"
            "torch=transformers（E1 臂，可跑 bge-base/large）。两者指纹不同，切换必然触发重建"
        ),
    )
    hf_cache_dir: Path = Field(
        default=DATA_DIR / "models" / "hf",
        description="torch/transformers 权重缓存目录（相对路径相对 PROJECT_ROOT；HF_CACHE_DIR 可覆盖）",
    )
    embedding_model_path: str = Field(
        default="",
        description="bge 权重目录绝对路径；空 → 由 scripts/probe_bge_weights.py 探测后回填 .env",
    )
    embedding_model_name: str = Field(
        default="bge-small-zh-v1.5", description="embedding 模型名（指纹与展示用）"
    )
    embedding_dim: int = Field(
        default=512, ge=8, le=4096, description="embedding 向量维度（bge-small-zh-v1.5=512）"
    )
    embedding_batch_size: int = Field(
        default=32, ge=1, le=256, description="CPU 批量推理大小；降速预案第一步调 8"
    )
    chunk_size: int = Field(
        default=500,
        ge=32,
        le=2000,
        description=(
            "chunk 窗口（token 口径，设计文档默认 500）。"
            "注意：设计文档 §7.1 要求『chunk_size 校验 ≤480』与默认 500 冲突："
            "此处按默认 500 落地，480 的单 chunk 有效上限由 splitter 截断保证（T02）。"
        ),
    )
    chunk_overlap: int = Field(
        default=80, ge=0, description="相邻 chunk 重叠 token 数"
    )
    chunk_mode: Literal["heading", "fixed", "semantic"] = Field(
        default="heading",
        description="切分模式：heading=M2 结构感知默认；fixed=无视边界纯滑窗；semantic=段落相似度低谷处断开",
    )
    #: 检索融合的默认权重。**2026-10-03 从 0.4:0.6 改成 1.0:0.0（= 纯 BM25）**，依据是一次
    #: 同索引、同口径的五组对照（`evaluation/reports/eval_20261003_000400.md|.json`，
    #: 新度量 `1-d²/2`、1000 篇 CMRC、70 道计分题，top-1 / top-3 / hit@5 / MRR）：
    #:
    #: | 权重 | top-1 | top-3 | hit@5 | MRR |
    #: |---|---|---|---|---|
    #: | 0.3:0.7 | 87.14% | 90.00% | 92.86% | 0.8905 |
    #: | 0.4:0.6（旧默认） | 88.57% | 94.29% | 95.71% | 0.9131 |
    #: | 0.5:0.5 | **94.29%** | 97.14% | 97.14% | 0.9548 |
    #: | **1.0:0.0（现默认）** | 91.43% | **95.71%** | 97.14% | **0.9362** |
    #: | 0.0:1.0 | 85.71% | 87.14% | 87.14% | 0.8643 |
    #:
    #: 选 1.0:0.0 的理由：三项主指标最优（top-1 / top-3 / MRR），hit@5 与 0.5:0.5 打平，
    #: 且与消融报告的 A-BM25 臂同源 —— 口径统一；而旧默认 0.4:0.6 **四项全部输给纯 BM25**
    #: （-2.86 / -1.42 / -1.43pp 与 -0.0231）。混合检索**保留为可选项**：0.5:0.5 是唯一
    #: 反超档（top-1 94.29%），也就是说"混合的收益只在特定权重下出现"，不是一句话能否。
    #: ⚠️ 两条如实的限制：① `rag/retriever.py:141` 的向量路是**无条件执行**的，
    #: 权重给 0 也照样嵌一次查询向量（`bm25_only` 那档也不跳），所以这个默认值省的是
    #: 排序质量、不是延迟；② 消融矩阵的基线仍钉在 0.4:0.6（`evaluation/experiment.py:57-58`
    #: 的 `BASELINE_DEFAULTS`）—— 那是"相比 M2 已交付配置提升 X"这句话的参照物，
    #: 跟着改会作废 A-* 全部对照（见 docs/m3_ablation_report.md 的单变量约束），故**刻意不跟着动**。
    bm25_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="混合检索 BM25 权重（与 vector_weight 之和 ≈1）；默认 1.0 = 纯 BM25，依据见字段上方注释与 docs/m3_ablation_report.md",
    )
    vector_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="混合检索向量权重（与 bm25_weight 之和 ≈1）；默认 0，仍可配（0.5:0.5 是唯一反超档）",
    )
    hybrid_fusion: Literal["weighted", "rrf", "bm25_only", "vector_only"] = Field(
        default="weighted",
        description=(
            "融合口径：weighted=M2 的 min-max 加权和（默认）；rrf/bm25_only/vector_only"
            "为 M3 消融臂口径（m3_design.md §4.1）"
        ),
    )
    rrf_k: int = Field(
        default=60, ge=0, description="RRF 平滑常数 k；仅 hybrid_fusion=rrf 时被读取"
    )
    reranker_model: str = Field(
        default="",
        description=(
            "交叉编码重排模型名；空 → 不精排。⚠️ 本机 CPU 实测 20 候选/查询 ≈6.27s"
            "（m3_design.md §8.3），线上默认关闭，只用于消融实验"
        ),
    )
    jieba_userdict: str = Field(
        default="",
        description=(
            "jieba 自定义词典路径（每行『词语 词频 词性』）；空 → 用默认词典。"
            "词典只作用于本索引的私有分词器，不改全局 jieba"
        ),
    )
    knowledge_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "检索默认返回条数：knowledge_search 工具签名上那个默认值的唯一来源，"
            "也是 GET /config/agent-options 报给前端的 defaults.rag_top_k"
            "（2026-09-26 之前这条是死字段，零消费者）"
        ),
    )
    knowledge_max_file_mb: int = Field(
        default=50, ge=1, le=2048, description="单文件上传上限（MB）"
    )
    vector_store_backend: Literal["sqlite-vec", "chroma"] = Field(
        default="sqlite-vec",
        description="向量库后端；spike 结论固化，sqlite-vec 受阻时降级 chroma",
    )
    knowledge_queue_max_size: int = Field(
        default=20, ge=1, le=1000, description="索引队列容量，满 → 429"
    )
    fastembed_cache_dir: Path = Field(
        default=DATA_DIR / "models" / "fastembed_cache",
        description="fastembed ONNX 权重缓存目录（相对路径相对 PROJECT_ROOT）",
    )

    # ------------------------------------------------------------ 校验器 ----
    @field_validator("llm_base_url", "llm_base_url_zhipu", "llm_base_url_qwen")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        """端点去尾斜杠：拼接 path 时避免出现双斜杠。

        三家一起过这同一条校验器 —— ``core/llm/runtime.py`` 会直接拿这些字段的值建
        ``ChatOpenAI``，那里没有第二次机会补斜杠。（新加一家时记得把字段名加进来。）
        """
        return value.strip().rstrip("/")

    @field_validator("workspace_dir", "log_dir", "hf_cache_dir")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        """相对路径统一相对 PROJECT_ROOT 解析。"""
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("knowledge_dir")
    @classmethod
    def _absolute_knowledge_dir(cls, value: Path) -> Path:
        """知识库目录相对路径统一相对 PROJECT_ROOT 解析。"""
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("fastembed_cache_dir")
    @classmethod
    def _absolute_fastembed_cache_dir(cls, value: Path) -> Path:
        """fastembed 缓存目录相对路径统一相对 PROJECT_ROOT 解析。"""
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def _validate_rag_params(self) -> "Settings":
        """RAG 参数的组合校验（设计文档 §5 T01 子步骤 5）。

        * chunk_overlap 必须 < chunk_size；
        * bm25_weight + vector_weight 应 ≈1（±0.01）——偏差时告警并归一化，
          两者全 0 视为配置错误直接报错；
        * embedding_provider="api" 在 M2 未实现，启动即报错（§0.3 第 6 条）。
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap({self.chunk_overlap}) 必须小于 chunk_size({self.chunk_size})"
            )
        total = self.bm25_weight + self.vector_weight
        if total <= 0:
            raise ValueError("bm25_weight 与 vector_weight 不能同时为 0")
        if abs(total - 1.0) > 0.01:
            warnings.warn(
                f"bm25_weight({self.bm25_weight}) + vector_weight({self.vector_weight})"
                f" = {total:.4f} ≠ 1，已按比例归一化",
                stacklevel=2,
            )
            self.bm25_weight = round(self.bm25_weight / total, 6)
            self.vector_weight = round(self.vector_weight / total, 6)
        if self.embedding_provider == "api":
            raise ValueError(
                "embedding_provider='api' 在 M2 未实现：请使用 local，或等待接口预留启用"
            )
        return self

    # ------------------------------------------------------------ 派生属性 ----
    @property
    def llm_configured(self) -> bool:
        """是否配置了可用的 API Key（空串 / 纯空白都算未配置）。"""
        return bool(self.llm_api_key.get_secret_value().strip())

    @property
    def masked_api_key(self) -> str:
        """脱敏后的 Key（前 3 后 2 + ``...``），供自检与页面展示。"""
        raw = self.llm_api_key.get_secret_value().strip()
        if not raw:
            return "（未配置）"
        if len(raw) <= 6:
            return "***"
        return f"{raw[:3]}...{raw[-2:]}"

    @property
    def api_auth_enabled(self) -> bool:
        """是否启用 Bearer 鉴权（``API_AUTH_TOKEN`` 非空即启用）。"""
        return bool(self.api_auth_token.get_secret_value().strip())

    @property
    def resolved_db_url(self) -> str:
        """把 SQLite 相对路径解析成相对 ``PROJECT_ROOT`` 的绝对路径。"""
        if not self.db_url.startswith(_SQLITE_PREFIX):
            return self.db_url
        raw = self.db_url[len(_SQLITE_PREFIX) :]
        if not raw:
            return self.db_url
        path = Path(raw)
        if path.is_absolute():
            return self.db_url
        return _SQLITE_PREFIX + (PROJECT_ROOT / path).as_posix()

    @property
    def db_path(self) -> Path | None:
        """SQLite 数据库文件路径；非 SQLite 连接串返回 ``None``。"""
        if not self.resolved_db_url.startswith(_SQLITE_PREFIX):
            return None
        raw = self.resolved_db_url[len(_SQLITE_PREFIX) :]
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    # ------------------------------------------------------------ 运维方法 ----
    def setup_logging(self) -> None:
        """初始化根日志（幂等）：控制台 + ``log_dir`` 下的文件（可选）。"""
        level = getattr(logging, self.log_level, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            force=True,
        )
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                self.log_dir / "app.log", encoding="utf-8"
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
            )
            logging.getLogger().addHandler(file_handler)
        except OSError:  # pragma: no cover - 文件日志失败不阻断启动
            logging.getLogger().warning("日志文件不可写，仅保留控制台日志")

    def ensure_dirs(self) -> None:
        """确保运行期需要的目录存在（workspace / 数据库父目录 / 日志 / 知识库）。"""
        try:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover - 只读盘等极端场景
            logging.getLogger(__name__).warning("工作区目录创建失败：%s", self.workspace_dir)
        try:
            (self.knowledge_dir / "files").mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover
            logging.getLogger(__name__).warning("知识库目录创建失败：%s", self.knowledge_dir)
        try:
            self.fastembed_cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover
            logging.getLogger(__name__).warning(
                "fastembed 缓存目录创建失败：%s", self.fastembed_cache_dir
            )
        db_path = self.db_path
        if db_path is not None:
            try:
                db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:  # pragma: no cover
                logging.getLogger(__name__).warning("数据库目录创建失败：%s", db_path.parent)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局配置单例（测试改环境变量后须先 :func:`reset_settings_cache`）。"""
    return Settings()


def reset_settings_cache() -> None:
    """清空配置单例缓存（测试切换环境变量后必须调用）。"""
    get_settings.cache_clear()


# 启动时把项目根目录放进 PATH 环境变量无意义，这里仅保证 data 目录存在，
# 让「克隆后直接 import」也能工作（数据库等懒创建，不在此处建表）。
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:  # pragma: no cover
    pass

__all__ = ["DATA_DIR", "PROJECT_ROOT", "Settings", "get_settings", "reset_settings_cache"]
