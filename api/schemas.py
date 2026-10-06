"""Pydantic 请求 / 响应契约（对应设计文档 §3.1）。

三条约定：

1. **时间一律北京时间 ISO-8601 带 ``+08:00``**，由 :func:`core.llm.pricing.now`
   生成；从 DB 读出的 naive UTC 时间统一经 :func:`to_cn` 转换。
2. **金额一律 ``round(x, 6)``**。
3. 请求模型用 ``field_validator`` 先 ``strip()`` 再校验长度，
   这样 ``"   "`` 与 ``""`` 都会落到 422，而不是被当成合法输入塞进编排内核。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.constants import MAX_TASK_CHARS, TASK_ID_PATTERN
from core.llm.pricing import CN_TZ, now

Difficulty = Literal["easy", "medium", "hard"]

#: 全部内置工具名（``POST /tasks`` 的 ``enabled_tools`` 合法性校验用）。
#: 就地声明、**刻意不 import** ``core.tools``——API 契约层不耦合编排内核
#: （与 :class:`ToolSpecView.danger_level` 同一纪律）。与
#: ``core.tools.builtin.BUILTIN_REGISTRARS`` 的注册集保持一致。
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {"calculator", "knowledge_search", "code_exec"}
)


# --------------------------------------------------------------------------- #
# 时间工具
# --------------------------------------------------------------------------- #
def to_cn(moment: datetime | None) -> datetime:
    """把 DB 里的 naive UTC 时间转成北京时间（带 ``+08:00``）。

    Args:
        moment: 可能是 naive（SQLite ``CURRENT_TIMESTAMP``）或带时区的 datetime。

    Returns:
        北京时间 datetime；入参为 ``None`` 时返回当前北京时间。
    """

    if moment is None:
        return now()
    if moment.tzinfo is None:
        from datetime import timezone

        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(CN_TZ)


# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #
class ErrorBody(BaseModel):
    """错误详情（``detail`` 字段的内容）。"""

    code: str = Field(description="机器可读的错误码")
    message: str = Field(description="给人看的一句话说明")
    request_id: str = Field(default="", description="请求 id，便于在服务端日志里定位")


class ErrorResponse(BaseModel):
    """统一错误响应体。"""

    detail: ErrorBody


# --------------------------------------------------------------------------- #
# POST /tasks
# --------------------------------------------------------------------------- #
#: 运行期可配字段的边界 —— **只在这里写一次**。
#:
#: 两个消费者都读它：① 下面 ``Field`` 的 ``ge`` / ``le``（服务端真拒的那种）；
#: ② ``GET /config/agent-options`` 的 ``limits``（界面 InputNumber 的 min/max）。
#: 分成两处写就会分叉：界面允许填 60 秒、后端只收 30 秒那种 422，
#: 或者反过来 —— 所以这条不是整理，是防一个具体的失效模式（方案 §4 P-3）。
#:
#: ⚠️ ``max_iterations`` 这里的上界是 **10**，而 ``WorkflowConfig`` / ``Settings``
#: 各自允许到 50（``core/workflow/state.py`` 与 ``config.py``）。抬界要三处一起抬，
#: 只抬一处会得到"配置页给不出那个选项"或"给了但后端拒收"。
RUN_CONFIG_LIMITS: dict[str, dict[str, float]] = {
    "max_iterations": {"min": 1, "max": 10, "step": 1},
    "review_threshold": {"min": 0, "max": 10, "step": 1},
    "rag_top_k": {"min": 1, "max": 20, "step": 1},
    # ⚠️ 这两条的数值**照方案 §2.1 的契约表**（预算上界 50 元、超时 30–3600 秒步长 30）。
    # 改这里等于改契约：界面 InputNumber 的界、请求模型的 ge/le、探针桩三者一起动，
    # 少动一处就得到"界面让填、后端拒收"那种 422（§4 P-3）。
    "max_cost_cny": {"min": 0.01, "max": 50.0, "step": 0.01},
    "timeout_s": {"min": 30, "max": 3600, "step": 30},
}


class TaskSubmitRequest(BaseModel):
    """提交任务的请求体。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task": "用三句话说明什么是 RAG",
                "use_tools": True,
                "enabled_tools": ["knowledge_search", "calculator"],
                "max_iterations": 3,
                "review_threshold": 7,
                "run_judge": False,
                "difficulty": "easy",
            }
        }
    )

    task: str = Field(description="任务描述，去空白后长度 1..4000")
    task_id: str | None = Field(
        default=None,
        pattern=TASK_ID_PATTERN,
        description="客户端指定 id；不传则由服务端生成 task-<hex12>",
    )
    use_tools: bool | None = Field(
        default=None,
        description=(
            "工具装配开关（三态，向后兼容）：不传（null）= 全量装配（现状行为）；"
            "true = 全量装配；false = **低风险安全子集**（calculator/knowledge_search，"
            "排除高危 code_exec），不再等同「零工具」"
        ),
    )
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "精确工具白名单（最高优先级，覆盖 use_tools）；元素须为内置工具名之一："
            "calculator/knowledge_search/code_exec"
        ),
    )
    max_iterations: int | None = Field(
        default=None,
        ge=RUN_CONFIG_LIMITS["max_iterations"]["min"],
        le=RUN_CONFIG_LIMITS["max_iterations"]["max"],
        description="迭代上限；不传取全局 settings",
    )
    review_threshold: int | None = Field(
        default=None,
        ge=RUN_CONFIG_LIMITS["review_threshold"]["min"],
        le=RUN_CONFIG_LIMITS["review_threshold"]["max"],
        description="评审通过线；不传取全局 settings",
    )
    #: —— 以下三条是「运行配置面板」新增的运行期闸门（方案 U-3 / U-4）——
    #: ⚠️ 三条都是**软**限制：编排跑在 worker 线程的同步循环里，只在**节点之间**检查，
    #: 所以最坏情况还会再多跑一个完整节点（含一次 LLM 调用与其重试）。
    #: 界面必须把这句原样显示出来，不能只写"预算 / 超时"。
    max_cost_cny: float | None = Field(
        default=None,
        ge=RUN_CONFIG_LIMITS["max_cost_cny"]["min"],
        le=RUN_CONFIG_LIMITS["max_cost_cny"]["max"],
        description=(
            "成本预算上限（元）；节点之间检查，达到即按取消路径中断。"
            "读的是 llm_call 事件累加，不是 tasks.cost（运行中那一列恒为 0）"
        ),
    )
    timeout_s: int | None = Field(
        default=None,
        ge=RUN_CONFIG_LIMITS["timeout_s"]["min"],
        le=RUN_CONFIG_LIMITS["timeout_s"]["max"],
        description="任务超时（秒）；节点之间检查的软超时，不传=不设限",
    )
    rag_top_k: int | None = Field(
        default=None,
        ge=RUN_CONFIG_LIMITS["rag_top_k"]["min"],
        le=RUN_CONFIG_LIMITS["rag_top_k"]["max"],
        description=(
            "本任务的检索条数**上限**；模型自己传得更少时尊重模型，传得更多时夹到这里。"
            "不传=不额外限制（用部署默认 settings.knowledge_top_k）"
        ),
    )
    run_judge: bool = Field(default=False, description="是否跑一轮 LLM judge（多一轮成本）")
    difficulty: Difficulty | None = Field(default=None, description="难度标签，仅作标记")

    @field_validator("task")
    @classmethod
    def _strip_and_check(cls, value: str) -> str:
        """先 strip 再校验：纯空白必须落到 422，不能进编排内核。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("task 不能为空或纯空白")
        if len(cleaned) > MAX_TASK_CHARS:
            raise ValueError(f"task 长度不能超过 {MAX_TASK_CHARS} 字符")
        return cleaned

    @field_validator("enabled_tools")
    @classmethod
    def _check_enabled_tools(cls, value: list[str] | None) -> list[str] | None:
        """校验 ``enabled_tools``：去空白、去重、必须全是已知内置工具名。

        非法工具名按既有错误约定落到 **422**（与 ``task`` 格式校验同纪律），
        而不是静默忽略——静默忽略会让调用方以为「限定成功了」却装了个空表。
        同时禁止空列表：``[]`` 语义含糊（是「零工具」还是「没限制」），
        要限制为零工具请显式用 ``use_tools`` 的语义（当前最低为安全子集）。
        """
        if value is None:
            return None
        cleaned = [str(name).strip() for name in value if str(name).strip()]
        if not cleaned:
            raise ValueError("enabled_tools 不能是空列表；不需要限制请留空（null）")
        unknown = sorted(set(cleaned) - set(KNOWN_TOOL_NAMES))
        if unknown:
            raise ValueError(
                f"enabled_tools 含未注册的工具名：{unknown}；"
                f"可用：{sorted(KNOWN_TOOL_NAMES)}"
            )
        # 保序去重
        deduped: list[str] = []
        for name in cleaned:
            if name not in deduped:
                deduped.append(name)
        return deduped


class TaskRunConfigView(BaseModel):
    """服务端**实际收下**的运行期配置（201 回执里的一份）。

    存在的理由只有一条：界面显示"这条任务的预算是 ¥0.36"时，要读**这里**，
    不能读自己刚发出去的那份。请求模型的 ``extra`` 策略是忽略未知键 ⇒
    一台没重启的老后端会把新字段静默丢掉，届时这里回 ``null`` 而不是用户填的数 ——
    于是"你以为设了"这件事在界面上看得见（方案 P-1 的负面对照要的就是这一格）。
    """

    max_iterations: int = Field(description="服务端最终采用的迭代上限（含回落全局默认之后）")
    review_threshold: int = Field(
        description="服务端最终采用的评审通过线（含回落全局默认之后）；0 是合法值，不是「没填」"
    )
    max_cost_cny: float | None = Field(default=None, description="成本预算上限（元）；未收下=null")
    timeout_s: int | None = Field(default=None, description="超时（秒）；未收下=null")
    rag_top_k: int | None = Field(default=None, description="检索条数上限；null=不额外限制")
    use_tools: bool | None = Field(default=None, description="三态原样回报")
    enabled_tools: list[str] | None = Field(default=None, description="白名单原样回报；null=全量")


class TaskAcceptedResponse(BaseModel):
    """``POST /tasks`` 的 201 响应。"""

    task_id: str = Field(description="任务 id")
    status: Literal["queued", "running"] = Field(description="受理后的状态")
    queue_position: int = Field(description="排队位置，从 1 开始；已开跑为 0")
    submitted_at: datetime = Field(description="受理时间（北京时间 +08:00）")
    poll_url: str = Field(description="轮询地址")
    stream_url: str = Field(description="SSE 订阅地址")
    cancel_url: str = Field(description="取消地址")
    estimated_cost_cny: float = Field(description="成本粗估（元），仅供量级参考")
    peak_pricing: bool = Field(description="当前是否处于高峰计费时段")
    price_multiplier: float = Field(description="相对低谷的倍数：高峰 2.0 / 低谷 1.0")
    warnings: list[str] = Field(default_factory=list, description="受理时的提示（非致命）")
    #: 服务端实际收下的运行配置。⚠️ 前端渲染"这条任务的配置"时读这里，
    #: 不读自己发出去的那份（理由见 :class:`TaskRunConfigView`）。
    #: 可选是为了让**没重启的老后端**那份没有这个键的响应照样能解析。
    run_config: TaskRunConfigView | None = Field(
        default=None, description="服务端实际收下的运行配置；老后端无此字段=null"
    )


# --------------------------------------------------------------------------- #
# GET /config/agent-options —— 运行配置面板的唯一数据来源
# --------------------------------------------------------------------------- #
class AgentOptionField(BaseModel):
    """一个可配字段的"能不能填 / 填了有没有用"。

    ⚠️ ``accepted`` 与 ``enforced`` 是**两个独立的布尔**，不能合并成一个：
    前者说"后端收不收这个键"（收了不认 ⇒ Pydantic 的 ``extra="ignore"`` 会**静默丢掉**，
    那是最坏的一种失效：用户以为设了预算，任务照样把钱花完），
    后者说"设了之后有没有真的执行机制"。四种组合里只有 (True, True) 是"填了就管"。
    """

    key: str = Field(description="提交体里的键名")
    label: str = Field(description="界面用词")
    kind: str = Field(
        description=(
            "控件类型：int / money / duration / bool / select。"
            "⚠️ 刻意不写死成 Literal —— 后端将来给一个新 kind 时，"
            "界面要能原样透出这个值（不认识 ≠ 不存在），而不是在校验层报错或静默丢掉"
        )
    )
    #: 单位后缀（轮 / 分 / 元 / 秒 / 条）。放在契约里而不是前端常量里，理由与 label 一样：
    #: 前端自己有一张"哪个键是什么单位"的表，就是第二个口径（方案 §2 规矩 3）。
    unit: str | None = Field(default=None, description="数值键的单位后缀；非数值键为 null")
    accepted: bool = Field(description="后端**请求模型**收不收这个键（不收就别发）")
    enforced: bool = Field(description="收了之后有没有真的执行机制（软限制也要标出来）")
    help: str | None = Field(default=None, description="生效条件；界面必须把它显示出来")


class AgentOptionPreset(BaseModel):
    """一档预设（快速 / 标准 / 深度）。

    ⚠️ 预设的**值也来自后端**：前端写死三档数字，正面违反"严禁前端写死默认值与枚举"，
    而且会立刻与 ``defaults`` / ``limits`` 分叉（同一份配置两个真相）。
    """

    id: str = Field(description="预设 id，前端只当不透明键用")
    label: str = Field(description="预设名")
    values: dict[str, Any] = Field(
        default_factory=dict, description="要套到各字段上的值；前端不解释语义、原样套"
    )
    note: str | None = Field(
        default=None, description="这一档的口径说明（含换算，如果有）"
    )


class AgentRoleModelView(BaseModel):
    """某个编排角色这次用的是哪一档、从哪来。"""

    role: str = Field(description="planner / executor / reviewer / judge")
    tier: str = Field(description="large / small")
    model: str = Field(description="这次生效的模型 id")
    source: str = Field(description="env / override")


class AgentModelsView(BaseModel):
    """模型区（**只读**）。

    ⚠️ ``editable_here`` 恒为 ``False`` 不是偷懒：换模型的入口在顶栏齿轮，
    这里给第二颗下拉就会得到"两个入口、两个真相"（方案 U-2 拍的那一条，
    探针 AC-4 也钉着"不给用户第二个入口"）。
    """

    editable_here: bool = Field(default=False, description="这一栏能不能改模型")
    entry_point: str = Field(description="该去哪儿改（界面原样显示）")
    roles: list[AgentRoleModelView] = Field(description="每个角色这次用哪个模型")


class AgentToolsView(BaseModel):
    """工具区：清单**不在这里抄一份**，只给指针与默认勾选。

    ``source`` 指向 ``GET /tools``（活注册表）。⚠️ 不能在这里列工具名 ——
    内置模块里还留着三个已退役工具的 ``register()``，任何"从常量抄的清单"都会
    与真实注册结果分叉（方案 §1.4 / P-6）。
    """

    source: str = Field(default="/tools", description="清单的唯一来源（前端去那儿拉）")
    default_enabled: list[str] | None = Field(
        default=None, description="默认全勾时等价于不传 enabled_tools（=后端全量）"
    )
    rag_tool: str | None = Field(
        default=None,
        description=(
            "composer 上那颗「RAG」快捷开关对应的是哪个工具名。"
            "⚠️ 由后端说，不让前端写死这个字符串 —— 否则前端就藏了第二个名字口径。"
            "该工具没注册时给 null，界面就把开关置灰并说明原因，"
            "而不是拿一份猜的清单去算白名单"
        ),
    )


class AgentOptionsResponse(BaseModel):
    """``GET /config/agent-options`` —— 默认值 / 边界 / 预设 / 字段能力，一处给全。

    形状照 ``KnowledgeOverviewResponse`` 那条先例（"前端一律读这个字段、不写死数字"）。

    ⚠️ ``extra="allow"`` 是**故意的**：后端将来多给一个键时，它要能原样序列化出去，
    让前端把它列进"未识别"区。用严格模型把它在校验层丢掉，等于把"未知状态"
    伪装成"没有这个配置" —— 那是本项目明令禁止的静默隐藏。
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = Field(description="契约版本号；前端认不认识的版本都要能渲染")
    defaults: dict[str, Any] = Field(description="后端自己的默认值（前端不许再写一份）")
    limits: dict[str, dict[str, float]] = Field(
        description="各字段的 min/max/step，与请求模型的 Field 界**同源**"
    )
    presets: list[AgentOptionPreset] = Field(default_factory=list)
    fields: list[AgentOptionField] = Field(default_factory=list)
    models: AgentModelsView
    tools: AgentToolsView
    currency: str = Field(description="成本单位口径（全站是元，不是美元）")
    pricing_basis: str = Field(description="价格口径原话，界面直接显示")


# --------------------------------------------------------------------------- #
# GET /tasks/{id}
# --------------------------------------------------------------------------- #
class TaskProgress(BaseModel):
    """运行中的轻量进度视图（终态为 ``null``）。"""

    current_node: str | None = Field(default=None, description="最近完成的节点名")
    completed_nodes: list[str] = Field(default_factory=list, description="已完成的节点名")
    iteration: int = Field(default=0, description="当前迭代轮次")
    max_iterations: int = Field(default=0, description="迭代上限")
    elapsed_ms: int = Field(default=0, description="已耗时（毫秒）")


class TaskQueueInfo(BaseModel):
    """排队信息。"""

    position: int = Field(default=0, description="排队中 ≥1；running / 终态为 0")
    wait_seconds: float = Field(default=0.0, description="已等待秒数")


class TaskError(BaseModel):
    """失败原因（仅 ``failed`` 时非空）。"""

    code: str = Field(description="错误码，如 llm_not_retryable / node_failed")
    message: str = Field(description="失败说明")


class TaskView(BaseModel):
    """``GET /tasks/{id}`` 的 200 响应。"""

    task_id: str
    task: str
    status: str
    iterations: int = 0
    score: int | None = None
    grade: str | None = None
    final_answer: str = ""
    cost: float = 0.0
    duration_ms: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    difficulty: str | None = None
    created_at: datetime
    updated_at: datetime
    progress: TaskProgress | None = Field(default=None, description="终态为 null")
    queue: TaskQueueInfo = Field(default_factory=TaskQueueInfo)
    error: TaskError | None = Field(
        default=None,
        description="failed 时非空；canceled 仅在被运行期闸门（预算 / 超时）中断时非空"
        "（用户自己取消保持 null）",
    )


# --------------------------------------------------------------------------- #
# GET /tasks/{id}/cost-breakdown（成本归因面板；契约见 docs/cost_attribution_plan_2026-09-25.md §10.2h）
# --------------------------------------------------------------------------- #
class CostTotals(BaseModel):
    """整任务合计，**全量口径**（不受前端明细分页封顶影响 —— 那边 50×N 会截断）。"""

    calls: int = Field(default=0, description="llm_call 事件条数；只有这个类型带 token 与费用")
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = Field(default=0.0, description="人民币元")


class CostRoleRow(BaseModel):
    """一行 = 一个 ``(角色, 模型, 峰谷系数)`` 组合。

    同一次运行跨了 12:00 / 18:00 边界时，同一角色会出**两行**、两个系数 —— 这是有意的：
    挑一个「代表系数」盖掉差异，就是把真实分布抹平。
    """

    role: str | None = None
    model: str | None = Field(
        default=None,
        description="null = 这条历史记录时还没记模型；读取侧不许回落到当前 role_map（那是拿今天的账填昨天的坑）",
    )
    price_multiplier: float | None = Field(
        default=None,
        description="调用那一刻实际套用的系数（高峰 1.0 / 低谷 0.5）；null = 未记录，**不等于 1.0**",
    )
    peak: bool | None = Field(
        default=None,
        description="由 price_multiplier 推得；系数为 null 时同为 null（不知道就说不知道）。"
        "**该供应商不分峰谷时也是 null** —— 那 1.0 是「没有折扣」，不是「高峰」",
    )
    tiered: bool | None = Field(
        default=None,
        description=(
            "这个模型是否按**输入长度分档**计价。true ⇒ 下面的 unit_price_* 只是**下界**"
            "（这一行是 N 次调用的聚合，拿聚合 token 去选档会把单次长度当成总长度）；"
            "null = 模型没记进库（老任务）"
        ),
    )
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = Field(default=0.0, description="人民币元")
    unit_price_in: float | None = Field(default=None, description="元 / 100 万 token（全项目统一单位）")
    unit_price_out: float | None = Field(default=None, description="元 / 100 万 token")
    price_source: Literal["official_table", "settings_fallback", "unknown"] = Field(
        default="unknown",
        description="official_table=命中 MODEL_PRICES；settings_fallback=兜底单价；unknown=没记模型",
    )
    pricing_basis: str = Field(
        default="",
        description=(
            "这一行单价的口径原话（来自注册表那一家）。⚠️ 前端不许自己写死一句"
            "「按官网高峰价折算」盖在所有行上 —— 那是 DeepSeek 一家的口径，"
            "换成智谱/千问之后每一行都会被它说错（与 R-03 同一类：一句话服务多个来源）"
        ),
    )


class CostWindow(BaseModel):
    """计费时段事实，**全部后端算**。

    ⚠️ 前端不许自己判时段：``tasks.created_at`` 存的是 UTC，而
    :func:`core.llm.pricing.is_peak` 把无时区的串按北京时间解释 —— 拿字符串自判会整体
    错 8 小时（把半夜的半价标成高峰）。本模型里的 datetime 一律带 ``+08:00``。
    """

    is_peak_now: bool = Field(description="查询此刻是否高峰（与「本次运行跑在什么档」是两件事）")
    multiplier_now: float = Field(description="当前时段系数：1.0 高峰 / 0.5 低谷")
    next_off_peak_at: datetime | None = Field(
        default=None,
        description="下一次进入低谷的时刻（C7）；当前已是低谷时为 null，因为那时「下一次」没有意义",
    )
    window_desc: str = Field(default="", description="高峰窗口的可读描述，唯一来源 core.llm.pricing")


class PriceCheck(BaseModel):
    """单价反推（C6 守门人的服务端那一半）。

    单条 ``(tokens_in, tokens_out, cost)`` 解不出两个未知单价，必须**至少两条同单价的行
    联立**，第三行当独立验证。凑不齐方程就不判：``ok=None`` 并写清原因，
    **不许返回 True/0 蒙人** —— 那会把「没验过」读成「验过了」。
    """

    ok: bool | None = Field(
        default=None, description="true=反推单价与 resolve_price 的表内价在 ±0.5% 内对咬；null=判不了"
    )
    max_delta_pct: float | None = Field(
        default=None,
        description="三件事的最大相对偏差（百分数，0.12 表示 0.12%）：反推输入价 vs 表内、反推输出价 vs 表内、"
        "用反推单价**预测**其余各行的 cost vs 库里 cost。后一类必须一起算 —— 只拿前两行解方程再自比，"
        "等于让第三行失去否决权（拟合出来的数当然对得上自己）",
    )
    implied_price_in: float | None = Field(default=None, description="反推出的输入价，元 / 100 万 token")
    implied_price_out: float | None = Field(default=None, description="反推出的输出价，元 / 100 万 token")
    equations: int = Field(default=0, description="参与联立的方程条数；<2 时无解，ok 必为 null")
    reason: str | None = Field(default=None, description="判不了的原因；判得了时为 null")


class CostReconcile(BaseModel):
    """对账位：``Σ by_role.cost`` 与 ``tasks.cost`` 必须相等。

    两者是**独立算出来**的：前者是本端点对 ``task_events`` 的 ``GROUP BY``，
    后者来自 ``evaluation/metrics.py:83`` 对 ``traces`` 记录求和后 ``round(…, 6)``
    再经 ``mark_terminal`` 落库 —— 两条路径、两张表，谁漂了这里就会分开。
    不等就说明有人换了聚合源、漏了 ``event_type`` 过滤，或写入侧加了新事件类型没同步口径。

    ⚠️ ``all_equal`` 可以是 ``None``：``tasks.cost`` **只在落终态时写**，未进终态的任务
    库里恒为 0，而它的事件已经在花钱（实测 ``task-1365c179c055``：``status=running``、
    ``tasks.cost=0``、``Σ llm_call.cost=0.0126``）。这时说「不等」是假警报，
    说「相等」是撒谎，所以只如实标「不适用」。
    """

    events_cost: float = Field(default=0.0, description="Σ by_role.cost（实时值，未终态也在增长）")
    task_cost: float = Field(default=0.0, description="tasks.cost（终态才写入；未终态恒为 0）")
    all_equal: bool | None = Field(
        default=None,
        description="两者在 1e-6 元容差内相等；null=任务未进终态，对账不适用（不是「不等」）",
    )
    note: str = Field(default="", description="不等或不适用时说实话：哪两个数、差多少、为什么")


class CostBreakdownResponse(BaseModel):
    """``GET /tasks/{id}/cost-breakdown`` 的 200 响应。"""

    task_id: str
    generated_at: datetime = Field(description="服务器北京时间 +08:00；前端不许另读本地时钟")
    totals: CostTotals = Field(default_factory=CostTotals)
    by_role: list[CostRoleRow] = Field(default_factory=list)
    window: CostWindow
    price_check: PriceCheck = Field(default_factory=PriceCheck)
    reconcile: CostReconcile = Field(default_factory=CostReconcile)


# --------------------------------------------------------------------------- #
# POST /tasks/{id}/cancel
# --------------------------------------------------------------------------- #
class CancelResponse(BaseModel):
    """``POST /tasks/{id}/cancel`` 的 200 响应。"""

    task_id: str
    status: Literal["canceled"] = "canceled"
    canceled_at: datetime = Field(description="取消生效时间（北京时间 +08:00）")
    mode: Literal["queued_dropped", "node_boundary"] = Field(
        description="queued_dropped=排队期直接丢弃（零 LLM 调用）；node_boundary=节点边界停止"
    )
    note: str = Field(description="取消语义说明（含已知限制 L1）")


# --------------------------------------------------------------------------- #
# POST /tools/{name}/invoke
# --------------------------------------------------------------------------- #
class ToolInvokeRequest(BaseModel):
    """单工具调用请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {"args": {"expression": "1+1"}}})

    args: dict[str, Any] = Field(default_factory=dict, description="工具入参对象")


class ToolHitlInfo(BaseModel):
    """HITL 决策结果（无论放行与否都会填，便于客户端展示原因）。"""

    required: bool = Field(default=False, description="本次调用是否触发了高危审批")
    approved: bool = Field(default=False, description="是否已放行")
    reason: str | None = Field(default=None, description="拒绝理由；放行时为 null")


class ToolInvokeResponse(BaseModel):
    """单工具调用响应。**工具执行失败也返回 HTTP 200**（见 PRD L6）。"""

    name: str
    args: dict[str, Any]
    result: str = Field(description="工具返回值（字符串化）；失败时是失败原因")
    status: Literal["success", "failed", "timeout"] = Field(
        description="调用结果；客户端必须判断它是否等于 success"
    )
    duration_ms: int = 0
    hitl: ToolHitlInfo = Field(default_factory=ToolHitlInfo)


# --------------------------------------------------------------------------- #
# GET /tools
# --------------------------------------------------------------------------- #
class ToolSpecView(BaseModel):
    """单个内置工具的规格视图（``GET /tools`` 的列表项）。

    **刻意不复用** :class:`core.tools.registry.ToolSpec`：后者带一个被
    ``Field(exclude=True)`` 标注的回调字段，而 ``exclude=True`` 只作用于
    ``model_dump()`` 的默认行为，**不能**保证它作为 FastAPI ``response_model``
    时被自动剔除——``Callable`` 字段会污染 OpenAPI schema 并可能触发序列化告警。

    本模型**逐字段挑出** 6 个可公开字段，**完全不含工具实现回调**，从类型层面
    杜绝工具实现泄漏到 API 响应。

    ``danger_level`` 就地声明 ``Literal["low", "high"]``（与
    ``core.tools.registry.ToolDanger`` 同值），**刻意不 import registry**——
    避免 API 契约层耦合编排内核。
    """

    name: str = Field(description="工具名，调用时使用（如 calculator）")
    description: str = Field(description="给模型看的一句话说明：做什么、什么时候用")
    danger_level: Literal["low", "high"] = Field(
        description="危险级别；high 表示会执行代码/写文件，调用前需人工确认"
    )
    timeout: int = Field(description="单次调用墙钟超时（秒），0 表示不限制")
    retry: int = Field(description="失败重试次数（指数退避）；超时不重试")
    parameters: dict[str, Any] = Field(description="入参的 JSON Schema（type/properties/required）")


class ToolListResponse(BaseModel):
    """``GET /tools`` 的 200 响应（只读快照，恒返回全部内置工具）。"""

    items: list[ToolSpecView] = Field(description="全部内置工具规格，按名称字母序排列")
    total: int = Field(description="工具总数，与 items 长度一致")


# --------------------------------------------------------------------------- #
# GET /models
# --------------------------------------------------------------------------- #
class PriceTierView(BaseModel):
    """一个价格档（阶梯计价时一个模型有多条）。单位：**元 / 100 万 token**。"""

    max_input_tokens: int | None = Field(
        description="本档的**输入** token 上限（含）；null = 不分档 / 官网没写更高一档"
    )
    price_in_per_million_cny: float = Field(description="输入单价（元 / 100 万 token）")
    price_out_per_million_cny: float = Field(description="输出单价（元 / 100 万 token）")
    note: str = Field(default="", description="官网那一行的附加口径（例：思考模式输出另计更高价）")


class ModelCatalogEntry(BaseModel):
    """候选清单里的一行 = 一个**核过价**的模型（设置面板的下拉就读这个，前端一份都不抄）。

    ⚠️ 只有 ``resolve_price`` 走得进注册表的模型才会出现在这里。自由填的 id 也能用，
    但它不在 catalog 里、单价会标成 ``settings_fallback`` ⇒ 界面必须写"兜底单价 · 未核价"，
    不许把它排进官方价那一列（换模型方案 T-3）。
    """

    id: str = Field(description="模型 id（发给供应商的 model 字段）")
    display_name: str = Field(description="人话名称，来自官网那一行")
    provider: str = Field(description="供应商标识")
    provider_display: str = Field(description="供应商人话名称")
    tiers: list[PriceTierView] = Field(description="全部价格档；不分档时只有一条")
    tiered: bool = Field(
        description="是否按输入长度分档。true 时单看一个数会低估长上下文 ⇒ 页面要把整档摊开"
    )
    tiers_text: str = Field(description="阶梯的人话一行，与 tiers 同一来源生成")
    pricing_basis: str = Field(description="这一行的单价口径（含'原价/含折扣''思考模式另计'等）")
    price_source_url: str = Field(description="官网价格页 URL（可核对）")
    price_checked_on: str = Field(description="核对日期 YYYY-MM-DD（价格会变，没日期等于没来源）")
    suggested_for: list[Literal["large", "small"]] = Field(
        description="官网定位给的档位提示（排序/标注用，不限制可选）"
    )
    key_configured: bool = Field(
        description="这个模型会用的那把 Key 配了没有；false ⇒ 选中它会被写端点当场拒"
    )
    base_url: str = Field(description="选中它之后请求真正会打的端点（按路由规则算出来的）")
    endpoint_source: Literal["env", "provider_env", "provider_default"] = Field(
        description="端点从哪来：.env 那一家 / 那家的覆盖 / 注册表默认"
    )
    key_env_var: str = Field(
        description="该配哪个环境变量才有 Key（只有变量名，**没有 Key 本身**）"
    )


class ProviderKeyView(BaseModel):
    """一家供应商的 Key / 端点状态。

    ⚠️ 五个"Key 相关"的字段分得很细是有理由的：``key_configured`` 与 ``base_url`` 说的是
    **请求真正会用的那把/那个地址**（自建网关时那是 ``.env`` 那一家），
    ``own_key_*`` 说的是**这家的环境变量里到底有没有值**。以前只有前者，于是
    ``LLM_PROVIDER=custom`` 的部署下界面上"智谱 GLM：已配置"其实指的是网关那把 Key ——
    一句话两个意思。加了输入框之后这件事必须能分开说，否则用户填完智谱的 Key、
    那个点还是网关的状态，界面就在说谎。
    """

    provider: str = Field(description="供应商标识")
    display_name: str = Field(description="人话名称")
    model_count: int = Field(description="注册表里这家有几种模型")
    key_configured: bool = Field(description="请求真正会用的那把 Key 配了没有")
    key_env_var: str = Field(description="Key 的环境变量名（大写；不含 Key 值）——**请求真正用的那把**")
    key_source: Literal["env", "runtime", "none"] = Field(
        description="那把 Key 从哪来：env=环境变量、runtime=本次进程里面板填的、none=没有"
    )
    own_key_configured: bool = Field(
        description="这家自己的那个字段（``own_key_env_var``）到底有没有值 —— "
        "与 ``key_configured`` 不同：后者答的是「请求发得出去吗」，这条答的是「这家的 Key 在不在」"
    )
    own_key_env_var: str = Field(description="这家自己的 Key 变量名（大写；不含 Key 值）")
    env_channel: bool = Field(
        description="True = 当前所有请求都走 .env 那一家（自建网关），"
        "填这家的 Key **不会被用到** ⇒ 界面必须点名、不给输入框"
    )
    base_url: str = Field(description="这家会被用到的端点（.env 那一家报的是 llm_base_url）")
    base_url_env_var: str = Field(description="这家端点的覆盖变量名；空串 = 不提供覆盖")
    peak_off_peak: bool = Field(
        description="这家是否分高峰/低谷计价。false 时低谷折扣**不许**套到它头上"
    )


class ModelKeyRequest(BaseModel):
    """``POST /models/key`` 的请求体：把某家的 Key 放进**本次进程**。

    三条边界（与 :mod:`core.llm.runtime` 的覆盖层同一口径）：不落盘、不写 ``.env``、
    不替换 ``get_settings()`` 单例，重启自动回落。``api_key`` 传空串 = 撤掉这一家。

    ⚠️ 值只走 POST body：不进 URL、不进 query —— 那两个地方会被访问日志、
    浏览器历史和代理日志各留一份副本。
    """

    provider: str = Field(min_length=1, max_length=32, description="供应商标识（deepseek/zhipu/qwen）")
    api_key: str = Field(
        default="", max_length=256, description="明文 Key；空串 = 撤回这一家，回落环境变量"
    )

    @field_validator("api_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        """先 ``strip()``：从聊天窗口里带出的首尾空白不是 Key 的一部分。"""
        return value.strip()


class ModelKeyProbeRequest(BaseModel):
    """``POST /models/key/validate`` 的请求体：拿这把 Key 去问一次 ``GET /models``。

    这里**没有 Base URL 的位置**（刻意的）：端点由后端按供应商查表给，
    能填地址的这个入口就变成"带着别人的 Key 往任意地址发请求"的探针。
    """

    provider: str = Field(min_length=1, max_length=32, description="供应商标识")
    api_key: str = Field(min_length=1, max_length=256, description="待校验的明文 Key（不落屏、不回显）")

    @field_validator("api_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ModelKeyProbeView(BaseModel):
    """一次校验的答复。**没有任何字段装 Key**（连脱敏串都不给 —— 需求里没有它）。"""

    ok: bool = Field(description="鉴权过没过")
    provider: str = Field(description="探的是哪家")
    base_url: str = Field(description="实际打到的端点（后端算出来的，不是用户填的）")
    http_status: int | None = Field(default=None, description="HTTP 状态码；连不上时为 null")
    model_count: int | None = Field(default=None, description="成功时报出的模型个数；没解析出来为 null")
    detail: str = Field(description="给人看的那句：成功是「拿到几个模型」，失败是**供应商原话**")
    latency_ms: int = Field(description="这趟探测耗时（毫秒）")
    timeout_s: float = Field(description="超时上限（秒），界面要说「3 秒」就读这里")


class ModelOverrideView(BaseModel):
    """本进程的模型覆盖状态（``None`` = 还在用 ``.env`` 的值）。"""

    model_large: str = Field(description="当前生效的强模型档")
    model_small: str = Field(description="当前生效的快模型档")
    source: Literal["env", "override"] = Field(
        description="这两个值是 .env 来的，还是本次在面板上改的"
    )
    applied_at: datetime | None = Field(
        default=None, description="覆盖生效时刻（北京时间 +08:00）；source=env 时为 null"
    )
    version: int = Field(description="覆盖代号（每次 apply/reset 各加一，用于解释缓存作废）")
    previous_large: str = Field(default="", description="覆盖前的强模型档（回落时的参照）")
    previous_small: str = Field(default="", description="覆盖前的快模型档")


class ModelSpecView(BaseModel):
    """单个模型的注册表视图（``GET /models`` 的列表项）。

    刻意只放**服务端知道的事实**：id、档位、被哪几个编排角色使用、单价与其来源。

    * 不报上下文长度、不报"支持函数调用"这类能力声明——本仓库没有一份可核对的
      供应商元数据，写出来就是编的（对齐 ``.env.example`` 里"以官网为准"的口径）。
    * ``price_*`` 的单位是**元 / 100 万 token**，与
      :data:`core.llm.adapter.MODEL_PRICES` 和 ``Settings.llm_price_in/out`` 同源；
      这个单位在 2026-09-24 之前一度被标成"元/token"，两者差 10⁶ 倍，
      用例见 ``tests/unit/test_adapter_json.py``。
    * ``price_*`` 是**不知道本次多长时**的报价（阶梯模型取最低档），
      真正记账按 ``token_in`` 选档 ⇒ 两者可以不同，``tiers`` 里能看到完整口径。
    """

    id: str = Field(description="模型 id，与发给供应商的 model 字段一致")
    provider: str = Field(
        description="这个模型**属于**哪家（按模型 id 路由出来的，不是 settings.llm_provider）"
    )
    provider_display: str = Field(default="", description="供应商人话名称")
    tier: Literal["large", "small"] = Field(
        description="档位：large=强模型（planner/reviewer），small=快模型（executor/extract 工具）"
    )
    roles: list[str] = Field(description="实际使用这个模型的角色，来自编排层调用点，不是猜的")
    price_in_per_million_cny: float = Field(
        description="输入单价（元 / 100 万 token）；表中没有该模型时为 Settings 兜底值"
    )
    price_out_per_million_cny: float = Field(description="输出单价（元 / 100 万 token）")
    price_source: Literal["official_table", "settings_fallback"] = Field(
        description="official_table=命中 MODEL_PRICES（精确或前缀）；settings_fallback=退回兜底单价"
    )
    configured: bool = Field(
        description=(
            "**这个模型会用的那把 Key** 配了没有（多家并存后按模型所属供应商判，"
            "不再等于 settings.llm_configured）；不返回 Key 本身"
        )
    )
    base_url: str = Field(default="", description="这个模型的请求实际打到的端点")
    endpoint_source: Literal["env", "provider_env", "provider_default"] = Field(
        default="env", description="端点从哪来的"
    )
    known: bool = Field(
        default=True, description="注册表里有没有这一行；false = .env 里写的自由值"
    )
    tiered: bool = Field(default=False, description="是否按输入长度分档计价")
    tiers: list[PriceTierView] = Field(
        default_factory=list, description="全部分档；未登记的模型为空"
    )
    pricing_basis: str = Field(default="", description="这一行的单价口径（人话）")
    peak_off_peak: bool = Field(
        default=True, description="这家是否分峰谷；false 时低谷折扣不参与记账"
    )


class ModelListResponse(BaseModel):
    """``GET /models`` 的 200 响应（注册表 + 候选清单 + 生效来源，供只读展示与设置面板）。"""

    items: list[ModelSpecView] = Field(description="按 large→small 排列；两档同 id 时合并为一条")
    total: int = Field(description="模型条数（1 或 2）")
    role_map: dict[str, str] = Field(
        description=(
            "角色 → **实际调用的模型 id**（如 planner→deepseek-v4-pro、executor→deepseek-flash）。"
            "**由 items 派生**，不是第二份手写的表 —— 不可能与 items 里的 roles 互相打脸。"
            "刻意映射到 id 而不是档位：两档配成同一个模型时「档位」会说谎"
            "（executor 设计走快模型，但那台部署的快模型恰好就是强模型的 id），"
            "id 永远是真的。想知道某角色走哪档，看它落在哪一条 item 的 roles 里。"
        )
    )
    default_model: str = Field(
        description="调用方不指定 model 时适配层实际使用的模型（llm_model_large）"
    )
    pricing_basis: str = Field(
        description=(
            "整体口径说明。**逐条口径看 items[i].pricing_basis / catalog[i].pricing_basis** —— "
            "多家供应商的计价规则不同（DeepSeek 分峰谷、智谱与千问按输入长度分档），"
            "这一句只解释兜底单价"
        )
    )
    off_peak_multiplier: float = Field(
        description="低谷价系数（只对分峰谷的家生效；其余家记账系数恒为 1.0）"
    )
    catalog: list[ModelCatalogEntry] = Field(
        description="候选清单（只含核过价的行）；设置面板的下拉就读这一份"
    )
    providers: list[ProviderKeyView] = Field(description="每家的 Key / 端点状态（只读）")
    override: ModelOverrideView = Field(description="当前生效来源：.env 还是本次覆盖")
    fallback_price_in_per_million_cny: float = Field(
        description="未登记模型的兜底输入单价（settings.llm_price_in）"
    )
    fallback_price_out_per_million_cny: float = Field(
        description="未登记模型的兜底输出单价（settings.llm_price_out）"
    )


class ModelOverrideRequest(BaseModel):
    """``POST /models/override`` 的请求体：两个档位各给一个模型 id。

    ⚠️ 这里**没有 Key 的位置**，也不会有：Key 只从环境变量来（方案 L-1），
    面板上出现的只有"哪家已配 / 哪家缺"。
    """

    model_large: str = Field(min_length=1, max_length=64, description="强模型档的模型 id")
    model_small: str = Field(min_length=1, max_length=64, description="快模型档的模型 id")

    @field_validator("model_large", "model_small")
    @classmethod
    def _strip(cls, value: str) -> str:
        """先 ``strip()`` 再交给内核校验：``"   "`` 要落到 422，而不是被当成合法模型名。"""
        return value.strip()


class ModelOverrideAck(BaseModel):
    """``POST /models/override`` / ``DELETE /models/override`` 的 200 响应。

    带整份新状态（与 ``GET /models`` 同形状），前端拿到后直接覆盖查询缓存 ——
    界面显示的必须是**响应给的**，不许自己改完就显示（换模型方案 T-7）。
    """

    changed: bool = Field(description="这次调用真的改了东西吗（提交与当前相同的值时为 false）")
    message: str = Field(description="人话结果，含'重启后回落到 .env'这一句")
    state: ModelListResponse = Field(description="覆盖后的完整注册表视图")


class ModelKeyAck(BaseModel):
    """``POST /models/key`` 的 200 响应：整份新状态（与 ``GET /models`` 同形状）。

    ⚠️ 响应里**永远不回填用户刚打进去的那串**：界面要显示「已配置（本进程填的）」
    读的是 ``providers[].key_configured`` / ``key_source``，而不是自己留着明文 ——
    少留一份明文就少一处外泄面（录屏、DevTools 的 Network 面板、react-query 缓存）。
    """

    changed: bool = Field(description="有没有真的改（重复提交同一个值是 false，撤回没填过的那家也是 false）")
    message: str = Field(description="人话结果，含「只在这一次进程里生效，重启回落 .env」这一句")
    state: ModelListResponse = Field(description="放 Key 之后的完整注册表视图")


# --------------------------------------------------------------------------- #
# GET /eval
# --------------------------------------------------------------------------- #
class EvalListResponse(BaseModel):
    """评测记录分页结果。"""

    items: list[dict[str, Any]] = Field(description="EvalRecord.as_dict() 的列表")
    total: int = Field(description="符合条件的总条数（不受 limit 影响）")
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# GET /health
# --------------------------------------------------------------------------- #
class CheckResult(BaseModel):
    """单项健康检查；``extra`` 字段（如队列计数）走 ``model_extra``。"""

    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "degraded", "fail"] = Field(description="本项状态")
    detail: str = Field(default="", description="可读说明")


class HealthResponse(BaseModel):
    """``GET /health`` 的响应。"""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_seconds: int = 0
    checks: dict[str, CheckResult] = Field(description="api / database / redis / llm / queue / rag")


# --------------------------------------------------------------------------- #
# GET /tasks（任务列表）
# --------------------------------------------------------------------------- #
class TaskListResponse(BaseModel):
    """``GET /tasks`` 的 200 响应（分页 + 按 ``updated_at`` 倒序）。"""

    items: list[TaskView] = Field(description="当前页任务视图（活动态含实时 progress/queue）")
    total: int = Field(description="过滤后的任务总数（不受 limit/offset 影响）")
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# GET /stats/dashboard
# --------------------------------------------------------------------------- #
class TodayStat(BaseModel):
    """今日指标（完成率只认 ``done``，平均分只算有 score 的任务）。"""

    count: int = Field(default=0, description="今日任务数")
    done_count: int = Field(default=0, description="今日 done 任务数")
    completion_rate: float = Field(default=0.0, description="完成率（done / 总数，0..1）")
    avg_score: float | None = Field(
        default=None, description="平均评分；无任何带分任务时为 null"
    )
    total_cost: float = Field(default=0.0, description="今日累计成本（元）")


class DailyStat(BaseModel):
    """单日聚合（近 14 天，无数据日补零）。日期为北京时间。"""

    date: str = Field(description="日期 YYYY-MM-DD（北京时间）")
    count: int = 0
    done_count: int = 0
    cost: float = 0.0
    avg_score: float | None = None


class DashboardSystemInfo(BaseModel):
    """系统状态面板数据（取数方式与 ``GET /health`` 一致，零 token）。"""

    peak_pricing: bool = Field(description="当前是否处于高峰计费时段")
    price_multiplier: float = Field(
        description="时段系数（core.llm.pricing.price_multiplier：高峰 1.0 / 低谷 0.5）；"
        "相对低谷的倍数请用 2×（低谷 0.5 的倒数）表述"
    )
    next_off_peak: str = Field(description="下一次进入低谷的时刻（北京时间 ISO-8601）")
    llm_configured: bool = Field(description="LLM API Key 是否已配置")
    cache_backend: Literal["redis", "memory"] = Field(description="缓存后端")
    db_ok: bool = Field(description="SQLite 是否可读写（SELECT 1 探活）")


class DashboardStatsResponse(BaseModel):
    """``GET /stats/dashboard`` 的 200 响应。"""

    today: TodayStat
    daily: list[DailyStat] = Field(description="近 14 天逐日数据，按日期升序（今天在末尾）")
    system: DashboardSystemInfo
    generated_at: datetime = Field(description="生成时刻（北京时间 +08:00）")


# --------------------------------------------------------------------------- #
# 知识库 /knowledge（m2_design.md §3.1，T03）
# --------------------------------------------------------------------------- #
DocumentStatus = Literal["pending", "parsing", "chunking", "embedding", "ready", "failed"]


class DocumentUploadResponse(BaseModel):
    """``POST /knowledge/documents`` 的 201 响应。"""

    document_id: str = Field(description="文档 id（doc-<hex12>）")
    filename: str
    status: Literal["pending"] = "pending"
    upload_at: datetime = Field(description="受理时间（北京时间 +08:00）")
    status_url: str = Field(description="轮询地址 GET /knowledge/documents/{id}")
    warnings: list[str] = Field(default_factory=list, description="受理提示（如覆盖重建）")


class DocumentView(BaseModel):
    """``GET /knowledge/documents/{id}`` 与列表项的 200 响应。"""

    document_id: str
    filename: str
    size_bytes: int
    format: str
    status: DocumentStatus
    error_stage: str | None = Field(default=None, description="失败阶段（parsing/chunking/embedding/queue/dedup/unknown）")
    error_message: str | None = None
    chunk_count: int = 0
    token_count: int = 0
    embedding_fingerprint: str = ""
    created_at: datetime = Field(description="北京时间 +08:00")
    updated_at: datetime = Field(description="北京时间 +08:00")
    indexed_at: datetime | None = Field(default=None, description="索引完成时间；失败为 null")


class DocumentListResponse(BaseModel):
    """``GET /knowledge/documents`` 的 200 响应。"""

    items: list[DocumentView]
    total: int


class RetryResponse(BaseModel):
    """``POST /knowledge/documents/{id}/retry`` 的 200 响应。"""

    document_id: str
    status: Literal["pending"] = "pending"
    queued: bool = Field(description="是否已成功入队")


class KnowledgeSearchRequest(BaseModel):
    """``POST /knowledge/search`` 请求体。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"query": "六类线施工弯曲半径要求", "top_k": 5}}
    )

    query: str = Field(description="检索问题，去空白后长度 1..1000")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")
    bm25_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="BM25 权重；不传取全局配置（0.4）"
    )
    vector_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="向量权重；与 bm25_weight 之和必须 ≈1"
    )

    @field_validator("query")
    @classmethod
    def _strip_and_check(cls, value: str) -> str:
        """先 strip 再校验（与 TaskSubmitRequest 同纪律）。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query 不能为空或纯空白")
        if len(cleaned) > 1000:
            raise ValueError("query 长度不能超过 1000 字符")
        return cleaned

    @model_validator(mode="after")
    def _check_weights(self) -> "KnowledgeSearchRequest":
        """显式给权重时两者之和必须 ≈1（±0.01），且不能同时给一个。"""
        if self.bm25_weight is None and self.vector_weight is None:
            return self
        if self.bm25_weight is None or self.vector_weight is None:
            raise ValueError("bm25_weight 与 vector_weight 必须成对出现")
        if abs(self.bm25_weight + self.vector_weight - 1.0) > 0.01:
            raise ValueError(
                f"bm25_weight({self.bm25_weight}) + vector_weight({self.vector_weight}) 必须 ≈ 1"
            )
        return self


class SearchHitView(BaseModel):
    """一条检索命中（分数为**单次查询内归一化的相对分**，L5）。"""

    document_name: str
    chunk_seq: int
    start_char: int
    end_char: int
    text: str
    bm25_score: float
    vector_score: float
    score: float


class KnowledgeSearchResponse(BaseModel):
    """``POST /knowledge/search`` 的 200 响应（空库返回 ``hits: []``，不是报错）。"""

    query: str
    top_k: int
    took_ms: int
    hits: list[SearchHitView]


class KnowledgeOverviewResponse(BaseModel):
    """``GET /knowledge/overview`` 的 200 响应。"""

    document_count: int
    chunk_count: int
    token_count: int
    ready_count: int
    failed_count: int
    indexing_count: int
    fingerprint: str = Field(description="库级 embedding 指纹；空表示尚未有文档完成索引")
    vector_backend: str
    embedding_model: str
    last_indexed_at: datetime | None = None
    #: K3（2026-09-25 拍板"加字段"）：让"单文件 ≤ N MB"在**点上传之前**就看得见，
    #: 而不是等 422。唯一来源是 ``settings.knowledge_max_file_mb``（config.py:209），
    #: 前端一律读这个字段、不写死数字 —— 写死之后改配置的人只会看到"界面在骗人"。
    #: 422 的原文照旧兜底显示（那条 message 里带的是服务端当场算出的真实上限）。
    max_file_mb: int = Field(description="单文件大小上限（MB），来自服务端配置")
    #: R-03（2026-09-26）：能收哪些格式也随概览给，界面不再自带清单。
    #: 唯一来源是 ``api.constants.DOC_SUPPORTED_FORMATS``（经 ``rag.service.supported_formats()``），
    #: 与 422 ``unsupported_format`` 的判定**同一份**——所以"页面说支持"与"后端真收"不会分家。
    #: 排序后返回，为了两件事：``<input accept>`` 的字符串可比（探针要逐字对），
    #: 以及同一份常量在不同进程印出同一个顺序。前端拿到 ``[]`` 或缺字段 ⇒ 按"没读到"降级。
    supported_formats: list[str] = Field(
        description="上传白名单（小写扩展名、不带点、已排序），来自后端常量"
    )


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}/trace（P1-A 轨迹回放，设计文档 §6.2 / §6.3）
#
# 本节为 **trace 专属区**：只在此处新增类，不改动上方任何既有模型。
# 新增类统一带 ``Trace`` / ``TaskEvent`` 前缀，避免与其它线程正在改的
# task/状态模型撞名。
# --------------------------------------------------------------------------- #
class TaskEventView(BaseModel):
    """单条轨迹事件（``GET /tasks/{id}/trace`` 的列表项，设计文档 §6.2）。

    ``arguments`` 在本层从 DB 的 JSON 串**反序列化为对象**（``dict``）；
    这是展示层职责（``storage.models.TaskEventRecord.as_dict`` 刻意不解析）。
    """

    event_seq: int = Field(description="全局单调序，回放排序的唯一依据")
    step: int = Field(description="编排轮次（0 起），跨角色可比")
    sub_step: int | None = Field(default=None, description="轮内子步骤下标；非子步骤事件为 null")
    event_type: str = Field(description="事件类型，见 constants.TASK_EVENT_TYPES")
    role: str | None = Field(default=None, description="角色；任务级事件为 null")
    node: str | None = Field(default=None, description="节点名；任务级事件为 null")
    thought: str = Field(default="", description="LLM 思考/决策文本；无为空串")
    tool_name: str | None = Field(default=None, description="工具名；非工具事件为 null")
    arguments: dict[str, Any] | None = Field(
        default=None, description="工具入参（对象形态）；非工具事件为 null（不用 {} 混淆）"
    )
    observation: str = Field(default="", description="工具返回或节点输出；无为空串")
    latency_ms: int = Field(default=0, description="本次事件耗时（毫秒）")
    tokens_in: int = Field(default=0)
    tokens_out: int = Field(default=0)
    cost: float = Field(default=0.0, description="本次事件成本（元）")
    status: str = Field(default="success", description="单条事件状态，见 constants.TASK_EVENT_STATUSES")
    error_code: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    sse_seq: int | None = Field(default=None, description="与 EventBus 事件的旁挂参考；不参与排序")
    created_at: datetime = Field(description="事件时间（北京时间 +08:00）")


class TaskTraceResponse(BaseModel):
    """``GET /tasks/{task_id}/trace`` 的 200 响应（设计文档 §6.2）。

    老任务（``events_available=false``）同样是 200：任务**确实存在**，
    只是轨迹不可追溯。「任务不存在」才走 404（§5.3）。
    """

    task_id: str = Field(description="任务 id")
    items: list[TaskEventView] = Field(default_factory=list, description="按 event_seq 升序")
    total: int = Field(description="该任务事件总数（不受 limit 影响）")
    limit: int = Field(description="本次请求的页大小")
    after_seq: int = Field(description="本次请求的游标（页内游标，不跨库重建）")
    has_more: bool = Field(description="是否还有下一页")
    next_after_seq: int | None = Field(
        default=None, description="下一页游标；has_more=false 时为 null"
    )
    events_available: bool = Field(
        description="false=该任务无事件数据（P1-A 之前的老任务），items 恒为空"
    )
    unavailable_reason: str | None = Field(
        default=None, description="events_available=false 时给出人话原因"
    )


__all__ = [
    "CancelResponse",
    "CheckResult",
    "DailyStat",
    "DashboardStatsResponse",
    "DashboardSystemInfo",
    "Difficulty",
    "DocumentListResponse",
    "DocumentStatus",
    "DocumentUploadResponse",
    "DocumentView",
    "ErrorBody",
    "ErrorResponse",
    "EvalListResponse",
    "HealthResponse",
    "KNOWN_TOOL_NAMES",
    "KnowledgeOverviewResponse",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResponse",
    "RetryResponse",
    "SearchHitView",
    "TaskAcceptedResponse",
    "TaskError",
    "TaskEventView",
    "TaskListResponse",
    "TaskProgress",
    "TaskQueueInfo",
    "TaskSubmitRequest",
    "TaskTraceResponse",
    "TaskView",
    "TodayStat",
    "ToolHitlInfo",
    "ToolInvokeRequest",
    "ToolInvokeResponse",
    "ToolListResponse",
    "ToolSpecView",
    "to_cn",
]
