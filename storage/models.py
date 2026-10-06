"""SQLAlchemy 数据模型（阶段 4 的业务表 + M2 知识库三表 + P1-A 轨迹事件表）。

七张表各有明确职责，刻意**不与 evaluation/trace.py 的 ``traces`` 表重叠**：

* ``tasks`` —— 一条任务一行，存最终状态与成本，UI 的任务列表直接读它；
* ``agents`` —— Agent 角色的注册表（名字、职责、用哪个模型、提示词版本），
  给「工具与 Agent 管理」页做配置用；
* ``eval_records`` —— 每次 judge 评测一条，issues/suggestions 以 JSON 文本落库；
* ``documents`` / ``chunks``（M2）—— 知识文档与其切分片段的元数据，
  向量本体放 vec0 虚拟表（同 .db 文件，chunk_id 关联）；
* ``knowledge_meta``（M2）—— 库级 key/value（当前 embedding 指纹等）；
* ``task_events``（P1-A）—— **轨迹回放的唯一真源**：每个编排事件一行，
  ``event_seq`` 全局单调整序。它取代 ``traces`` 承担「可回放」职责。

节点级埋点（planner/executor/reviewer 每一步）的**旧表** ``traces`` 仍归
``evaluation.TraceStore`` 全权管理：它是高频写入，用裸 sqlite3 更轻，也不该被
两套 ORM 同时写。自 P1-A 起 ``traces`` **冻结**：只用于 ``TaskOutcome`` 汇总
（cost/duration/tool_counts），不再作为轨迹回放的数据源（其 ``step`` 语义错序，
见 ``docs/p1_trace_events_design.md`` §0.1-3）；回放请用 ``task_events``。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """声明式基类。"""


class TaskRecord(Base):
    """任务主表：一次编排运行的最终快照。"""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    final_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 失败原因的机器可读码（见 api/errors.py::ErrorCode 与 api/runner.py::classify_error）
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 失败原因的人话说明，供 GET /tasks/{id}.error 与页面直接展示
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "task_id": self.task_id,
            "task": self.task,
            "status": self.status,
            "iterations": self.iterations,
            "score": self.score,
            "grade": self.grade,
            "final_answer": self.final_answer,
            "cost": round(self.cost, 6),
            "duration_ms": self.duration_ms,
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "difficulty": self.difficulty,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentRecord(Base):
    """Agent / 角色注册表：描述平台里有哪些角色、各自用什么模型。"""

    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    @property
    def enabled_bool(self) -> bool:
        """``enabled`` 在 SQLite 里存 0/1，这里统一转 bool。"""
        return bool(self.enabled)

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "enabled": self.enabled_bool,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalRecord(Base):
    """评测记录表：每次 judge 打分一条。"""

    __tablename__ = "eval_records"

    eval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str] = mapped_column(String(16), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    issues: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    suggestions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    trace_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    @staticmethod
    def dumps(value: Any) -> str:
        """列表字段落库前序列化。"""
        return json.dumps(value, ensure_ascii=False)

    def loads_issues(self) -> list[str]:
        """取回 issues 列表。"""
        return list(json.loads(self.issues))

    def loads_suggestions(self) -> list[str]:
        """取回 suggestions 列表。"""
        return list(json.loads(self.suggestions))

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "eval_id": self.eval_id,
            "task_id": self.task_id,
            "score": self.score,
            "grade": self.grade,
            "reasoning": self.reasoning,
            "issues": self.loads_issues(),
            "suggestions": self.loads_suggestions(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeMeta(Base):
    """知识库级元信息（key/value）：当前存库级 embedding 指纹等。

    设计文档 m2_design.md §1.4：检索入口先比对 ``current_fingerprint``，
    不一致返回 409 ``fingerprint_mismatch``（提示全量重索引）。
    """

    __tablename__ = "knowledge_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    #: 库级当前 embedding 指纹的键名（KnowledgeService 读写共用）
    FINGERPRINT_KEY: str = "current_fingerprint"

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentRecord(Base):
    """知识文档主表：一份上传文档一行，五阶段索引状态机在此推进。

    状态机（唯一来源 api/constants.py::DOC_*）：``pending → parsing →
    chunking → embedding → ready``；任一阶段失败 → ``failed``，并把阶段与
    原因写进 ``error_stage`` / ``error_message``（文档级失败隔离，G4）。
    状态迁移只能走 ``Database.mark_document_*`` 的 CAS 通道。
    """

    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 原始文件落盘位置（knowledge_dir/files/{document_id}_{safe_name}）
    file_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: sha256 文件内容，overwrite 判断与「已索引跳过」去重用
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 本文档索引完成时的 embedding 指纹（与库级指纹比对，判定 ready 有效性）
    embedding_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    #: 索引完成时间（ready 时写入）；失败为 NULL
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "file_hash": self.file_hash,
            "status": self.status,
            "error_stage": self.error_stage,
            "error_message": self.error_message,
            "chunk_count": self.chunk_count,
            "token_count": self.token_count,
            "embedding_fingerprint": self.embedding_fingerprint,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }


class ChunkRecord(Base):
    """chunk 元数据表：向量放 vec0 虚表（同 .db 文件），文本与位置在这里。

    ``chunk_id`` 全局唯一且格式与 :class:`rag.types.Chunk` 一致；
    ``(document_id, seq)`` 加唯一约束防重复写入（设计文档 A1）。
    """

    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 标题路径快照（JSON 数组字符串），来源引用展示用
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("document_id", "seq", name="uq_chunks_document_seq"),
    )

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。"""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "seq": self.seq,
            "text": self.text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "heading_path": self.heading_path,
            "token_estimate": self.token_estimate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TaskEventRecord(Base):
    """轨迹事件表（P1-A）：``task_events`` 一行 = 一次编排事件。

    这是「真实可回放的轨迹时间线」的数据层基础（``docs/p1_trace_events_design.md``
    §3.2 给出规范 DDL，本模型与之逐列等价）。

    关键设计（设计文档 §1.1 / §1.2 / §3.4）：

    * ``event_seq`` —— ``INTEGER PRIMARY KEY AUTOINCREMENT``，**全局单调、永不复用**
      （借 ``sqlite_sequence`` 保证删除最大行后新 id 不会撞旧 id）。
      这是**回放排序的唯一依据**，绝不用 timestamp 排序。
    * ``step`` —— **编排轮次**（0 起），跨角色可比：planner=0，
      第 N 轮 executor/reviewer = N-1。旧 ``traces.step`` 的「executor 用子步骤下标、
      其余用 iteration」是错序元凶，本表把它拆成 ``step`` + ``sub_step`` 两列。
    * ``sub_step`` —— 轮内子步骤下标，仅 executor/tool 事件有值，其余为 NULL。

    NULL 语义（设计文档 §3.4，**最容易被追问**）：

    * ``tool_name`` / ``arguments`` / ``role`` / ``node`` / ``sub_step`` /
      ``error_*`` / ``sse_seq`` —— **NULL 表示「不存在」**（可用 ``IS NULL`` 查询）；
    * ``thought`` / ``observation`` —— **空串表示「值为空」**（NOT NULL DEFAULT ''）；
    * ★ ``arguments`` 禁止默认 ``'{}'``：``NULL``（非工具事件）与 ``'{}'``（无参
      工具调用）在语义上完全不同，落默认值会让
      ``WHERE arguments IS NULL`` 漏掉非工具事件。

    与 ``tasks`` 的外键：**刻意不加** ``REFERENCES tasks(task_id)``（设计文档 §5.3）。
    失败任务可能在 ``tasks`` 尚无行时先写事件，加外键会引入「先写 events 后写
    tasks」的顺序耦合；改为应用层保证——删任务时由 ``Database.delete_task()``
    连带删事件（同事务）。
    """

    __tablename__ = "task_events"

    #: ① 全局单调序：本表唯一的排序依据。AUTOINCREMENT 保证删除后不复用 id。
    event_seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: ② 归属
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: ③ 顺序：step 为「编排轮次」(0 起)，sub_step 为轮内子步骤下标
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sub_step: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: ④ 过程内容
    node: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thought: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: NULL = 非工具事件（关键 NULL 语义）
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: JSON 串；NULL = 非工具事件。禁止默认 '{}'，见类 docstring。
    arguments: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: ⑤ 计量（来自 adapter.last_usage，落盘时机见设计文档 §7.2）
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: 本次调用用的模型 id。**NULL = 这条历史记录时还没记**（成本归因两列于
    #: 2026-09-25 补上），与空串不同：空串是"知道但没名字"，NULL 是"不知道"。
    #: ⚠️ 不许在读取侧回落到"当前 ``role_map`` 里的模型"——那等于拿今天的配置填昨天的账。
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 本次调用**实际套用**的峰谷价格系数（高峰 1.0 / 低谷 0.5，来自
    #: ``core.llm.pricing.price_multiplier()``，在调用那一刻取值）。
    #: 与 ``cost`` 必须来自同一个取值：一次跨 12:00 / 18:00 边界的调用若事后重算，
    #: 钱按 A 系数、标签按 B 系数，两份账会自相矛盾且不报错。
    #: ⚠️ NULL ≠ 1.0：NULL 是"没记录"，1.0 是"确定跑在高峰"。
    price_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: ⑥ 状态与失败
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: ⑦ 与 EventBus 的旁挂参考（不参与排序，可 NULL）
    sse_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # 主查询：按 task 拉时间线，且按全局序稳定排序（覆盖索引 + 天然有序）
        Index("idx_task_events_task_seq", "task_id", "event_seq"),
        # 次要查询：按角色过滤（前端「只看 executor」）
        Index("idx_task_events_task_role", "task_id", "role"),
        # ★ 关键：SQLite 方言的 AUTOINCREMENT。
        # 默认情况下 SQLAlchemy 只生成 `INTEGER PRIMARY KEY`（裸 rowid），它虽然
        # 也会自增，但**会复用**已删除的最大 id（SQLite 规范），不满足「全局单调、
        # 永不复用」的硬要求。`sqlite_autoincrement=True` 才会渲染出
        # `INTEGER PRIMARY KEY AUTOINCREMENT`，借 sqlite_sequence 保证不复用
        # （设计文档 §1.1 / §3.2）。
        {"sqlite_autoincrement": True},
    )

    def as_dict(self) -> dict[str, Any]:
        """转成可直接 json.dumps 的字典。

        ``arguments`` 保持原始 JSON 串（不在此处 ``json.loads``）：解析成对象是
        **展示层（API View）** 的职责（设计文档 §6.2 的 ``arguments`` 是 object），
        存储模型不应替调用方决定「要不要解析」。

        ``created_at`` 以 ISO 字符串返回（与既有模型的 ``as_dict`` 同一约定）。
        """
        return {
            "event_seq": self.event_seq,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "role": self.role,
            "step": self.step,
            "sub_step": self.sub_step,
            "node": self.node,
            "thought": self.thought,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "observation": self.observation,
            "latency_ms": self.latency_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": round(self.cost, 6),
            #: 原样返回、不做回落：``None`` 表示"这条没记"，展示层负责说「未记录」。
            "model": self.model,
            "price_multiplier": self.price_multiplier,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "sse_seq": self.sse_seq,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


__all__ = [
    "AgentRecord",
    "Base",
    "ChunkRecord",
    "DocumentRecord",
    "EvalRecord",
    "KnowledgeMeta",
    "TaskEventRecord",
    "TaskRecord",
]
