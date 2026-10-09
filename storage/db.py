"""SQLAlchemy 引擎、会话与业务表门面。

三点刻意的设计：

1. **SQLite 打开 ``check_same_thread=False``**：Streamlit 每个会话都是独立线程，
   不打开这个开关会在页面上随机报 ``SQLite objects created in a thread``。
2. **``save_eval_result`` 只吃 Mapping，不 import ``evaluation.judge``**：
   保持 ``storage`` 层轻量、可单独测试，也避免 storage → evaluation → LLM 适配层
   这条反向依赖。
3. **状态迁移一律走 CAS**（:meth:`Database.mark_running` /
   :meth:`Database.mark_terminal` / :meth:`Database.mark_canceled`）：
   M1 的 API 进程里，「取消 handler（事件循环线程）」与「worker（线程池）」会
   同时抢着写同一行的 ``status``。用锁会让 worker 持锁做 DB 写、顺带阻塞整个
   事件循环；改成单条 ``UPDATE ... WHERE status = ...`` 把仲裁交给 SQLite 的写
   串行化，两全其美。**因此禁止用 :meth:`Database.save_task` 改 ``status``**。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, create_engine, delete, event, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from api.constants import (
    DOC_CHUNKING,
    DOC_EMBEDDING,
    DOC_FAILED,
    DOC_PARSING,
    DOC_PENDING,
    DOC_READY,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    SQLITE_BUSY_TIMEOUT_MS,
    TASK_EVT_LLM_CALL,
)
from config import PROJECT_ROOT, Settings, get_settings
from storage.migrations import (
    ensure_task_error_columns,
    ensure_task_event_cost_columns,
    ensure_task_events_table,
)
from storage.models import (
    AgentRecord,
    Base,
    ChunkRecord,
    DocumentRecord,
    EvalRecord,
    KnowledgeMeta,
    TaskEventRecord,
    TaskRecord,
)

logger = logging.getLogger(__name__)

#: 首次建表时预置的角色（模型号留空表示跟随全局配置）
DEFAULT_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("planner", "planner", "把任务拆解成 3-5 个可执行子步骤，输出 JSON 数组"),
    ("executor", "executor", "逐条执行子步骤，决定调用工具还是直接输出结论"),
    ("reviewer", "reviewer", "对整份交付做质量门禁，通过时给出可交付终稿"),
    ("judge", "judge", "按验收标准打分，供横向比较不同版本的平台"),
)


def _utcnow() -> datetime:
    """当前 UTC 时间（naive）。

    与 SQLite 的 ``CURRENT_TIMESTAMP`` 同一口径：``TaskRecord.created_at`` 的
    ``server_default=func.now()`` 拿到的就是 UTC naive，手工赋值必须跟它对齐，
    否则同一个表里会混进两套时区，排序与展示全乱。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """给每个新建的 SQLite 连接设置 WAL + 写冲突排队 + 落盘策略。

    这是**全项目唯一**设置 SQLite PRAGMA 的地方（SQLAlchemy 连接侧）。
    注意 ``evaluation/trace.py`` 的 ``TraceStore`` 用的是独立的裸 sqlite3 连接，
    那条连接**也必须**设同样三个 PRAGMA——只改一边等于没改（设计文档 §8.6）。

    三条 PRAGMA 的理由：

    * ``journal_mode=WAL``：允许「多读 + 单写」并发，M1 的三个 worker 线程不会互相堵死；
    * ``busy_timeout=5000``：抢不到写锁时排队 5 秒，而不是立刻抛 ``database is locked``；
    * ``synchronous=NORMAL``：WAL 下的推荐档位，兼顾性能与持久性。
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error as exc:  # pragma: no cover - 只在极端环境下触发
        logger.warning("设置 SQLite PRAGMA 失败（降级为默认模式）：%s", exc)
    finally:
        cursor.close()


def _create_engine(url: str, *, echo: bool = False) -> Engine:
    """建引擎；SQLite 额外放开跨线程检查（Streamlit 多线程要用）并挂 PRAGMA 回调。"""
    if url.startswith("sqlite"):
        engine = create_engine(url, echo=echo, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url, echo=echo)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


class Database:
    """业务表的统一入口。"""

    def __init__(
        self,
        db_url: str | None = None,
        *,
        settings: Settings | None = None,
        echo: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.url = db_url or self.settings.resolved_db_url
        self.engine = _create_engine(self.url, echo=echo)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    # ------------------------------------------------------------ 生命周期 --
    def init_db(self) -> None:
        """建表 → 补列 → 建事件表 → 预置角色（幂等）。

        ``create_all`` 只会建**不存在**的表，不会给老库加列，所以建表之后
        必须再跑一次 :func:`~storage.migrations.ensure_task_error_columns`。

        再跑一次 :func:`~storage.migrations.ensure_task_events_table` 是为了
        **显式建索引**（``create_all`` 也会建表与索引，但手工迁移路径需要它；
        用 ``IF NOT EXISTS`` 保证两条路径幂等共存，设计文档 §5.2）。

        第三次 :func:`~storage.migrations.ensure_task_event_cost_columns` 补成本归因两列，
        **必须排在建表之后**：老库里 ``task_events`` 已存在而 ``create_all`` 不会给它加列，
        不补这两列，成本面板对老数据只能永远显示「未记录」。
        """
        Base.metadata.create_all(self.engine)
        ensure_task_error_columns(self.db_path)
        ensure_task_events_table(self.db_path)
        ensure_task_event_cost_columns(self.db_path)
        self._seed_agents()
        logger.info("数据库就绪：%s", self.url)

    @property
    def db_path(self) -> Path | None:
        """SQLite 数据库文件路径；非 SQLite 时返回 ``None``。

        刻意从 ``self.url`` 推导而不是取 ``settings.db_path``：调用方可以显式传
        ``db_url``（测试就是这么做的），那时配置里的路径跟本实例无关。
        """
        prefix = "sqlite:///"
        if not self.url.startswith(prefix):
            return None
        raw = self.url[len(prefix) :]
        path = Path(raw)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """拿一个会话，退出时自动关闭；异常自动回滚。"""
        handle = self._factory()
        try:
            yield handle
            handle.commit()
        except Exception:
            handle.rollback()
            raise
        finally:
            handle.close()

    def _seed_agents(self) -> None:
        """预置角色表。两道防线缺一不可。

        1. 先查出已存在的名字，避免每次启动都发一遍 INSERT；
        2. 真正的写入走 ``INSERT OR IGNORE``：``agents.name`` 有唯一约束，而
           ``init_db()`` 会被多个入口并发调用（API lifespan、Streamlit 每个会话线程、
           测试夹具）。两个会话可能各自查不到对方**尚未提交**的那行、于是都决定插入，
           后提交的那个原本会抛 ``IntegrityError`` 把建库整个弄崩。
        """
        with self.session() as handle:
            existing = set(handle.execute(select(AgentRecord.name)).scalars())
            missing = [row for row in DEFAULT_AGENTS if row[0] not in existing]
            if not missing:
                return
            handle.execute(
                sqlite_insert(AgentRecord)
                .prefix_with("OR IGNORE")
                .values(
                    [
                        {
                            "name": name,
                            "role": role,
                            "description": description,
                            "model": "",
                            "prompt_version": "v1",
                            "enabled": 1,
                        }
                        for name, role, description in missing
                    ]
                )
            )

    # ---------------------------------------------------------------- tasks --
    def save_task(self, **fields: Any) -> TaskRecord:
        """按 ``task_id`` 做 upsert。"""
        task_id = str(fields.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id 不能为空")
        with self.session() as handle:
            record = handle.get(TaskRecord, task_id)
            if record is None:
                record = TaskRecord(task_id=task_id, task=str(fields.get("task", "")))
                handle.add(record)
            for key, value in fields.items():
                if key != "task_id" and hasattr(record, key):
                    setattr(record, key, value)
            handle.flush()
            return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        """按 id 取任务。"""
        with self.session() as handle:
            return handle.get(TaskRecord, task_id)

    # ------------------------------------------------- 状态迁移（CAS） --
    def mark_running(self, task_id: str) -> bool:
        """``queued`` → ``running``。

        Returns:
            ``True`` 表示抢到了执行权；``False`` 表示该任务在排队期已被取消，
            调用方**必须**直接返回，一个 token 都不要花。
        """
        return self._cas(task_id, (STATUS_QUEUED,), STATUS_RUNNING)

    def mark_terminal(self, task_id: str, *, status: str, **fields: Any) -> bool:
        """``running`` → ``status``（``done`` / ``aborted`` / ``failed``）。

        Args:
            task_id: 任务 id。
            status: 目标终态。
            **fields: 要一并写入的字段，键必须是 :class:`TaskRecord` 上真实存在的列。

        Returns:
            ``True`` 表示落库成功；``False`` 表示任务已被取消，调用方应**丢弃**
            本次结果而不是覆盖 ``canceled``。

        Raises:
            ValueError: ``fields`` 里出现非法列名（防注入 / 防手滑拼错）。
        """
        return self._cas(task_id, (STATUS_RUNNING,), status, **fields)

    def mark_canceled(
        self,
        task_id: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """``queued`` 或 ``running`` → ``canceled``。

        Returns:
            ``True`` 表示这次取消生效；``False`` 表示任务已是终态（返回 409）。

        ⚠️ 默认**不写** ``error_*``（K3：用户取消不是失败，那两列保持 NULL）。
        只有运行期闸门（预算 / 超时）中断任务时才带这两个参数 —— 那种"取消"不是用户点的，
        留 NULL 就等于让它看起来像"我自己取消的"，那是会误导人的空值。
        """
        fields: dict[str, object] = {}
        if error_code is not None:
            fields["error_code"] = error_code
        if error_message is not None:
            fields["error_message"] = error_message
        return self._cas(task_id, (STATUS_QUEUED, STATUS_RUNNING), STATUS_CANCELED, **fields)

    def fail_interrupted_tasks(
        self,
        *,
        error_code: str = "process_restarted",
        error_message: str = "服务进程重启，任务随进程一起中断（未自动续跑）",
    ) -> int:
        """启动时把库里所有**非终态**任务判为失败，返回处理条数。

        为什么需要它：任务跑在**本进程的内存队列**里（``api/queue.py``），既没有持久化
        工作队列也没有续跑能力。进程被硬杀 / 重启后，``tasks`` 行仍停在 ``queued`` /
        ``running``，而队列里已经什么都没有 —— 数据库与真实状态**脱钩**。本机实测过一条
        挂了 3 天的 ``running``（``task-1365c179c055``），前端「运行中」筛选会永久挂着它。
        每次硬重启都会新增一条，所以这不是环境项，是缺机制的必然产物。

        为什么是 ``failed`` 而不是 ``canceled``：取消是用户意图，这里有的是"没人负责了"，
        两者在报表里必须分得开（``canceled`` 的 ``error_code`` 按 K3 保持 NULL）。

        ⚠️ **单 worker 前提**：这条 UPDATE 判的是"整个库里没有跑着的任务"，只有当
        启动方确定本进程是唯一执行者时才成立（``Dockerfile`` 里 uvicorn 不带 ``--workers``，
        本机也是单进程）。若将来上多 worker，得先给任务加 owner/lease，否则第二个 worker
        启动时会把第一个 worker 正在跑的任务判死。

        刻意**不**补写 ``task_events``：事件的最后一条停在哪儿就是哪儿，编一条 ``done``
        出来等于造数。回放页看到的是"跑到第几步就没了"，这恰好是事实。

        Args:
            error_code: 写进 ``tasks.error_code`` 的机器码（前端按它出文案）。
            error_message: 人类可读原因。

        Returns:
            被改判的任务条数（0 是常态 —— 正常关停路径自己会把任务落终态）。
        """
        with self.session() as handle:
            result = handle.execute(
                update(TaskRecord)
                .where(TaskRecord.status.in_((STATUS_QUEUED, STATUS_RUNNING)))
                .values(
                    status=STATUS_FAILED,
                    error_code=error_code,
                    error_message=error_message,
                    updated_at=_utcnow(),
                )
            )
            return int(result.rowcount or 0)

    def _cas(
        self,
        task_id: str,
        expected: tuple[str, ...],
        target: str,
        **fields: Any,
    ) -> bool:
        """单条 ``UPDATE ... WHERE status IN (...)`` 的比较并交换。

        以影响行数判定成败：SQLite 对同一行的写会串行化，所以「取消」与「落终态」
        同时发生时必然有一个 rowcount 为 0，两种结果都自洽，不存在终态被覆盖。
        """
        allowed = set(TaskRecord.__table__.columns.keys())
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"mark_terminal 收到非法字段名：{unknown}")

        values: dict[str, Any] = {"status": target, "updated_at": _utcnow()}
        values.update(fields)
        with self.session() as handle:
            result = handle.execute(
                update(TaskRecord)
                .where(TaskRecord.task_id == task_id, TaskRecord.status.in_(expected))
                .values(**values)
            )
            return result.rowcount == 1

    def list_tasks(self, limit: int = 100, *, status: str | None = None) -> list[TaskRecord]:
        """任务列表，按创建时间倒序。"""
        with self.session() as handle:
            stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(TaskRecord.status == status)
            return list(handle.scalars(stmt))

    def list_tasks_page(
        self,
        *,
        statuses: Sequence[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TaskRecord], int]:
        """按 ``updated_at`` 倒序的分页任务列表（只读，返回 ``(页内行, 总数)``）。

        ``total`` 是**过滤后的总数**（不受 limit/offset 影响），调用方据此渲染分页。
        ``statuses`` 为 ``None`` 或空序列表示不过滤；终态与活动态都从这里出，
        运行中 / 排队中的实时 progress 由 API 层再叠加内存态。
        """
        with self.session() as handle:
            stmt = select(TaskRecord)
            count_stmt = select(func.count()).select_from(TaskRecord)
            if statuses:
                stmt = stmt.where(TaskRecord.status.in_(statuses))
                count_stmt = count_stmt.where(TaskRecord.status.in_(statuses))
            total = int(handle.scalar(count_stmt) or 0)
            stmt = (
                stmt.order_by(TaskRecord.updated_at.desc(), TaskRecord.task_id)
                .limit(limit)
                .offset(offset)
            )
            rows = list(handle.scalars(stmt))
        return rows, total

    def list_tasks_since(self, since_utc_naive: datetime) -> list[TaskRecord]:
        """取 ``created_at >= since`` 的全部任务（Dashboard 按日聚合用，只读）。

        Args:
            since_utc_naive: UTC naive 下界（与 ``CURRENT_TIMESTAMP`` 同口径）。
        """
        with self.session() as handle:
            stmt = (
                select(TaskRecord)
                .where(TaskRecord.created_at >= since_utc_naive)
                .order_by(TaskRecord.created_at)
            )
            return list(handle.scalars(stmt))

    def delete_task(self, task_id: str) -> bool:
        """删一条任务；返回是否真的删掉了。

        P1-A（设计文档 §5.3）：``task_events`` **刻意不加** ``REFERENCES tasks``
        外键，改为**应用层连带删除**。此处在**同一事务**内先删该任务的事件再删
        任务行，保证不留孤儿事件（「删任务 → 重新开始」不会残留轨迹）。
        """
        with self.session() as handle:
            existed = handle.get(TaskRecord, task_id) is not None
            if existed:
                handle.execute(
                    delete(TaskEventRecord).where(TaskEventRecord.task_id == task_id)
                )
                handle.execute(delete(TaskRecord).where(TaskRecord.task_id == task_id))
            return existed

    # --------------------------------------------------------------- agents --
    def upsert_agent(
        self,
        name: str,
        *,
        role: str = "",
        description: str = "",
        model: str = "",
        prompt_version: str = "v1",
        enabled: bool = True,
    ) -> AgentRecord:
        """新增或更新一个角色。"""
        with self.session() as handle:
            record = handle.get(AgentRecord, name)
            if record is None:
                record = AgentRecord(name=name)
                handle.add(record)
            record.role = role or record.role or name
            record.description = description or record.description
            record.model = model
            record.prompt_version = prompt_version
            record.enabled = 1 if enabled else 0
            handle.flush()
            return record

    def list_agents(self) -> list[AgentRecord]:
        """全部角色。"""
        with self.session() as handle:
            return list(handle.scalars(select(AgentRecord).order_by(AgentRecord.name)))

    def set_agent_enabled(self, name: str, enabled: bool) -> bool:
        """启停一个角色；返回是否找到了它。"""
        with self.session() as handle:
            record = handle.get(AgentRecord, name)
            if record is None:
                return False
            record.enabled = 1 if enabled else 0
            return True

    # ---------------------------------------------------------------- evals --
    def save_eval_result(
        self,
        result: Mapping[str, Any],
        *,
        eval_id: str | None = None,
    ) -> EvalRecord:
        """直接吃 ``EvalResult.model_dump()``，避免 storage 反向依赖 evaluation。"""
        payload = dict(result)
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("EvalResult 缺少 task_id，无法落库")
        record_id = eval_id or f"eval-{task_id}-{uuid4().hex[:8]}"
        with self.session() as handle:
            record = handle.get(EvalRecord, record_id)
            if record is None:
                record = EvalRecord(eval_id=record_id, task_id=task_id)
                handle.add(record)
            record.score = int(payload.get("score", 0))
            record.grade = str(payload.get("grade", ""))
            record.reasoning = str(payload.get("reasoning", ""))
            record.issues = EvalRecord.dumps(payload.get("issues") or [])
            record.suggestions = EvalRecord.dumps(payload.get("suggestions") or [])
            record.trace_refs = EvalRecord.dumps(payload.get("trace_refs") or [])
            handle.flush()
            return record

    def list_evals(
        self,
        task_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[EvalRecord]:
        """评测记录，按创建时间倒序（支持分页）。"""
        with self.session() as handle:
            stmt = (
                select(EvalRecord)
                .order_by(EvalRecord.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if task_id:
                stmt = stmt.where(EvalRecord.task_id == task_id)
            return list(handle.scalars(stmt))

    def count_evals(self, task_id: str | None = None) -> int:
        """评测记录总条数（``GET /eval`` 的 ``total`` 字段要用）。

        必须单独 count，不能用 ``len(list_evals(...))``——后者受 ``limit`` 截断，
        会得到一个假的「总数」。
        """
        with self.session() as handle:
            stmt = select(func.count()).select_from(EvalRecord)
            if task_id:
                stmt = stmt.where(EvalRecord.task_id == task_id)
            return int(handle.scalar(stmt) or 0)

    # ---------------------------------------------------------------- 统计 --
    def stats(self) -> dict[str, Any]:
        """看板用的一口统计。"""
        with self.session() as handle:
            total = handle.scalar(select(func.count()).select_from(TaskRecord)) or 0
            by_status: dict[str, int] = {}
            rows = handle.execute(
                select(TaskRecord.status, func.count()).group_by(TaskRecord.status)
            )
            for status, count in rows:
                by_status[str(status)] = int(count)
            total_cost = handle.scalar(select(func.sum(TaskRecord.cost))) or 0.0
            avg_score = handle.scalar(select(func.avg(EvalRecord.score)))
            eval_count = handle.scalar(select(func.count()).select_from(EvalRecord)) or 0
        return {
            "tasks": int(total),
            "by_status": by_status,
            "total_cost": round(float(total_cost), 6),
            "eval_count": int(eval_count),
            "avg_score": None if avg_score is None else round(float(avg_score), 2),
        }

    # ----------------------------------------------------------- task_events --
    # P1-A：轨迹事件表（回放唯一真源）。三个纪律（设计文档 §7.5 / §12 K2）：
    #   1. record_event 内部失败**只 logger.warning，绝不抛**（纪律同
    #      TraceStore.add）——节点埋点不得因落盘失败而中断整个任务；
    #   2. 逐条 INSERT + COMMIT，不做批量缓冲（缓冲 = 崩溃时缓冲区全丢，
    #      与本设计「抗崩溃」的核心目标冲突）；
    #   3. 读取一律用 event_seq 游标，**禁止 OFFSET**（分页稳定、不受并发写入
    #      影响，设计文档 §3.3）。
    def record_event(self, **fields: Any) -> int | None:
        """落一条轨迹事件，返回新行的 ``event_seq``（失败返回 ``None``）。

        ``event_seq`` 由 SQLite ``AUTOINCREMENT`` 分配，**调用方不得预填**
        （``**fields`` 里若有 ``event_seq`` 也会被忽略并覆盖为真实值）。

        Args:
            **fields: 事件列（``task_id`` / ``event_type`` / ``step`` / ``role`` /
                ``tool_name`` / ``arguments`` …）。``arguments`` 应为 JSON 串或
                ``None``（本方法不做序列化，序列化是 ``EventRecord.to_row()`` 的职责，
                以保持 storage 层只吃「已成型的数据」）。未知列名会被忽略，
                避免污染。

        Returns:
            新行的 ``event_seq``；任何异常（``SQLAlchemyError`` / 其它）都返回
            ``None`` 并记 WARNING，**绝不抛**。
        """
        task_id = str(fields.get("task_id") or "").strip()
        event_type = str(fields.get("event_type") or "").strip()
        if not task_id or not event_type:
            logger.warning("record_event 缺少 task_id/event_type，已丢弃本次事件")
            return None
        allowed = set(TaskEventRecord.__table__.columns.keys()) - {"event_seq"}
        payload = {key: value for key, value in fields.items() if key in allowed}
        try:
            with self.session() as handle:
                record = TaskEventRecord(**payload)
                handle.add(record)
                handle.flush()
                return int(record.event_seq)
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            # 与 TraceStore.add 同纪律：观测失败不该升级为业务失败。
            logger.warning("写入 task_events 失败（回放将缺失该事件）：%s", exc)
            return None

    def list_events(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
        role: str | None = None,
    ) -> list[TaskEventRecord]:
        """按 ``event_seq`` 游标拉取某任务的时间线（升序）。

        用 ``WHERE task_id=? AND event_seq>? ORDER BY event_seq LIMIT ?``
        —— 命中 ``idx_task_events_task_seq`` 覆盖索引，且是**稳定游标**，
        比 ``OFFSET`` 更稳（不受并发写入影响，设计文档 §3.3）。

        Args:
            task_id: 任务 id。
            after_seq: 游标；返回 ``event_seq`` **严格大于**此值的事件。
            limit: 页大小（调用方负责收敛到 ``TRACE_MAX_LIMIT``）。
            role: 可选，按角色过滤（前端「只看 executor」）。

        Returns:
            按 ``event_seq`` 升序的事件行；无数据返回 ``[]``。
        """
        if limit <= 0:
            return []
        with self.session() as handle:
            stmt = (
                select(TaskEventRecord)
                .where(
                    TaskEventRecord.task_id == task_id,
                    TaskEventRecord.event_seq > int(after_seq),
                )
                .order_by(TaskEventRecord.event_seq)
                .limit(int(limit))
            )
            if role:
                stmt = stmt.where(TaskEventRecord.role == role)
            return list(handle.scalars(stmt))

    def count_events(self, task_id: str, *, role: str | None = None) -> int:
        """某任务的事件总数（``GET /trace`` 的 ``total`` 字段）。

        必须单独 count，不能用 ``len(list_events(...))``——后者受 ``limit``
        截断，会得到一个假的「总数」（同 ``count_evals`` 的纪律）。

        Args:
            task_id: 任务 id。
            role: 可选，按角色过滤计数。
        """
        with self.session() as handle:
            stmt = (
                select(func.count())
                .select_from(TaskEventRecord)
                .where(TaskEventRecord.task_id == task_id)
            )
            if role:
                stmt = stmt.where(TaskEventRecord.role == role)
            return int(handle.scalar(stmt) or 0)

    def cost_breakdown(self, task_id: str) -> list[dict[str, Any]]:
        """按 ``(角色, 模型, 峰谷系数)`` 聚合某任务的 LLM 花费用量（成本归因面板的数据源）。

        三条口径写在这里，因为它们都是"不报错但会算错"的那类：

        1. **只算 ``event_type='llm_call'``**。其余事件类型（``node_end`` /
           ``tool_call`` / ``running`` / ``done``）的 token 与 cost 全是 0，
           不过滤不会把钱算错，但会把**调用次数**按事件数翻倍 —— 次数是这份面板
           的核心读数之一，所以过滤是判据而不是修饰。
        2. **分组带上 ``price_multiplier`` 是故意的**：同一次运行跨过 12:00 / 18:00
           边界时，同一角色会有两种系数 ⇒ 自然出两行、两个系数。若只按角色分组，
           就得再挑一个"代表系数"盖掉差异，那是把真实信息抹平。
        3. **``None`` 原样带出，不在这里回落**。老任务没有 ``model`` / 系数，
           回落成"今天的 ``role_map`` 与现在的时段"等于拿今天的账填昨天的坑。

        合计一律由本方法的**全量分组**得出，不要用前端拉到的明细去加：
        ``GET /tasks/{id}/trace`` 的游标封顶（``limit=50`` × 若干页）会让 >封顶的任务
        在页面上"少算"，而这里没有封顶。

        Args:
            task_id: 任务 id。

        Returns:
            按 ``cost`` 倒序的分组列表，每行 ``{role, model, price_multiplier,
            calls, tokens_in, tokens_out, cost}``；没有 LLM 调用时返回 ``[]``。
        """
        cost_sum = func.coalesce(func.sum(TaskEventRecord.cost), 0.0)
        with self.session() as handle:
            rows = handle.execute(
                select(
                    TaskEventRecord.role,
                    TaskEventRecord.model,
                    TaskEventRecord.price_multiplier,
                    func.count().label("calls"),
                    func.coalesce(func.sum(TaskEventRecord.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(TaskEventRecord.tokens_out), 0).label("tokens_out"),
                    cost_sum.label("cost"),
                )
                .where(
                    TaskEventRecord.task_id == task_id,
                    TaskEventRecord.event_type == TASK_EVT_LLM_CALL,
                )
                .group_by(
                    TaskEventRecord.role,
                    TaskEventRecord.model,
                    TaskEventRecord.price_multiplier,
                )
                .order_by(cost_sum.desc())
            ).all()
        return [
            {
                "role": None if row[0] is None else str(row[0]),
                "model": None if row[1] is None else str(row[1]),
                "price_multiplier": None if row[2] is None else float(row[2]),
                "calls": int(row[3]),
                "tokens_in": int(row[4]),
                "tokens_out": int(row[5]),
                "cost": float(row[6]),
            }
            for row in rows
        ]

    def sum_llm_cost(self, task_id: str) -> float:
        """某任务**到目前为止**的 LLM 花费合计（元），给运行中的成本闸门用。

        ⚠️ 为什么单独有这一条而不复用 :meth:`cost_breakdown`：闸门每跑完一个节点就要
        读一次，分组 + 排序是白付的开销；更重要的是这两处的**失败后果不同** ——
        面板少算一行只是数字难看，闸门读错方向会提前掐掉一条正常任务。

        ⚠️ 为什么不能读 ``tasks.cost`` 那一列：运行中的任务那一列**恒为 0**，钱只在
        ``llm_call`` 事件里（``api/routes/tasks.py`` 里记着实跑观察
        ``running、tasks.cost=0、Σ llm_call=0.0126``）。拿它当闸门等于闸门永不触发，
        而且看起来一切正常 —— 这是"不报错只算错"那一类，所以口径写在这儿。

        过滤条件与 :meth:`cost_breakdown` 第 1 条同口径：只算 ``event_type='llm_call'``。

        Args:
            task_id: 任务 id。

        Returns:
            花费合计（元）；没有 LLM 调用时为 ``0.0``。
        """
        with self.session() as handle:
            value = handle.scalar(
                select(func.coalesce(func.sum(TaskEventRecord.cost), 0.0)).where(
                    TaskEventRecord.task_id == task_id,
                    TaskEventRecord.event_type == TASK_EVT_LLM_CALL,
                )
            )
        return float(value or 0.0)

    def max_event_seq(self, task_id: str) -> int:
        """某任务当前的**最大** ``event_seq``（0 表示该任务尚无事件）。

        供任务级事件（``done`` / ``failed`` / ``canceled``）取 ``step = 当前最大
        step`` 时参考（设计文档 §1.2），以及前端判断「有没有新事件」。
        """
        with self.session() as handle:
            value = handle.scalar(
                select(func.max(TaskEventRecord.event_seq)).where(
                    TaskEventRecord.task_id == task_id
                )
            )
            return int(value or 0)

    # ---------------------------------------------------------------- 维护 --
    def clear_all(self) -> None:
        """清空业务表（测试与「重新开始」用；不动 traces 表）。

        ★ X3（设计文档 §0.2）：**必须连带清空 ``task_events``**，否则「重新开始」
        之后旧任务的事件会残留，与「清空 tasks」后的空列表状态自相矛盾。
        ``traces`` 表仍按既定纪律不动（它归 ``TraceStore`` 全权管理，
        ``evaluation/trace.py::TraceStore.clear()`` 是清它的唯一入口）。
        """
        with self.session() as handle:
            handle.execute(delete(TaskEventRecord))
            handle.execute(delete(EvalRecord))
            handle.execute(delete(TaskRecord))
            handle.execute(delete(AgentRecord))

    # ------------------------------------------------------------ documents --
    # 设计文档 §7.2：状态迁移只允许 IndexWorker 经 mark_document_* 的 CAS 通道写；
    # 路由层只写 pending（INSERT）与终态删除，禁止绕过。
    def save_document(self, **fields: Any) -> DocumentRecord:
        """按 ``document_id`` 做 upsert（仅 ``pending`` 插入与少量展示字段更新用）。"""
        document_id = str(fields.get("document_id") or "").strip()
        if not document_id:
            raise ValueError("document_id 不能为空")
        with self.session() as handle:
            record = handle.get(DocumentRecord, document_id)
            if record is None:
                record = DocumentRecord(document_id=document_id)
                handle.add(record)
            for key, value in fields.items():
                if key != "document_id" and hasattr(record, key):
                    setattr(record, key, value)
            handle.flush()
            return record

    def get_document(self, document_id: str) -> DocumentRecord | None:
        """按 id 取文档。"""
        with self.session() as handle:
            return handle.get(DocumentRecord, document_id)

    def find_document_by_hash(self, file_hash: str) -> DocumentRecord | None:
        """按内容哈希找已 ``ready`` 的文档（file_hash 去重跳过用）。"""
        with self.session() as handle:
            stmt = select(DocumentRecord).where(
                DocumentRecord.file_hash == file_hash,
                DocumentRecord.status == DOC_READY,
            )
            return handle.scalars(stmt).first()

    def find_document_by_filename(self, filename: str) -> DocumentRecord | None:
        """按文件名找文档（同名冲突 409 判定用）。"""
        with self.session() as handle:
            stmt = (
                select(DocumentRecord)
                .where(DocumentRecord.filename == filename)
                .order_by(DocumentRecord.created_at.desc())
            )
            return handle.scalars(stmt).first()

    def list_documents(self, *, statuses: Sequence[str] | None = None) -> list[DocumentRecord]:
        """文档列表，按创建时间倒序；``statuses`` 为空表示不过滤。"""
        with self.session() as handle:
            stmt = select(DocumentRecord).order_by(DocumentRecord.created_at.desc())
            if statuses:
                stmt = stmt.where(DocumentRecord.status.in_(statuses))
            return list(handle.scalars(stmt))

    def list_documents_by_hash(self, file_hash: str) -> list[DocumentRecord]:
        """同 ``file_hash`` 的全部文档（含非 ready，失败隔离测试用）。"""
        with self.session() as handle:
            stmt = select(DocumentRecord).where(DocumentRecord.file_hash == file_hash)
            return list(handle.scalars(stmt))

    def mark_document_stage(self, document_id: str, target: str) -> bool:
        """索引阶段推进 CAS：按 ``DOC_STAGE_FLOW`` 的前置态约束推进一格。

        ``target`` 必须是 ``parsing / chunking / embedding`` 之一；前置态为
        ``pending``（进 parsing）或上一阶段。返回 ``False`` 表示状态已被并发
        改动（如删除/取消），调用方应立即放弃本次处理。
        """
        preconditions: dict[str, tuple[str, ...]] = {
            DOC_PARSING: ("pending",),
            DOC_CHUNKING: (DOC_PARSING,),
            DOC_EMBEDDING: (DOC_CHUNKING,),
        }
        expected = preconditions.get(target)
        if expected is None:
            raise ValueError(f"mark_document_stage 不接受目标状态：{target}")
        return self._cas_document(document_id, expected, target)

    def mark_document_ready(
        self, document_id: str, *, fingerprint: str, chunk_count: int, token_count: int
    ) -> bool:
        """``embedding`` → ``ready``（写指纹与统计）。"""
        return self._cas_document(
            document_id,
            ("embedding",),
            DOC_READY,
            embedding_fingerprint=fingerprint,
            chunk_count=chunk_count,
            token_count=token_count,
            indexed_at=_utcnow(),
            error_stage=None,
            error_message=None,
        )

    def mark_document_failed(self, document_id: str, *, stage: str, message: str) -> bool:
        """任一非终态 → ``failed``（错误阶段与原因落库，文档级失败隔离）。"""
        from api.constants import DOC_INDEXING_STATUSES

        return self._cas_document(
            document_id,
            tuple(DOC_INDEXING_STATUSES),
            DOC_FAILED,
            error_stage=stage,
            error_message=message,
        )

    def reset_document_pending(self, document_id: str, *, from_statuses: tuple[str, ...]) -> bool:
        """终态/任意态 → ``pending``（重试与全量重索引的复位通道，CAS）。

        复位时清掉错误字段；入队由调用方（KnowledgeService）负责，失败要回滚
        到原状态的话由调用方自行处理（重索引是幂等的，无需严格回滚）。
        """
        return self._cas_document(
            document_id,
            tuple(from_statuses),
            DOC_PENDING,
            error_stage=None,
            error_message=None,
        )

    def _cas_document(
        self,
        document_id: str,
        expected: tuple[str, ...],
        target: str,
        **fields: Any,
    ) -> bool:
        """documents 表的单条 CAS ``UPDATE``（与 tasks 的 ``_cas`` 同一纪律）。"""
        allowed = set(DocumentRecord.__table__.columns.keys())
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"文档 CAS 收到非法字段名：{unknown}")
        values: dict[str, Any] = {"status": target, "updated_at": _utcnow()}
        values.update(fields)
        with self.session() as handle:
            result = handle.execute(
                update(DocumentRecord)
                .where(
                    DocumentRecord.document_id == document_id,
                    DocumentRecord.status.in_(expected),
                )
                .values(**values)
            )
            return result.rowcount == 1

    def delete_document(self, document_id: str) -> bool:
        """删文档记录（chunks 与向量由调用方连带清理）。"""
        with self.session() as handle:
            existed = handle.get(DocumentRecord, document_id) is not None
            if existed:
                handle.execute(
                    delete(DocumentRecord).where(DocumentRecord.document_id == document_id)
                )
            return existed

    # --------------------------------------------------------------- chunks --
    def save_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> int:
        """批量写 chunk 元数据（先清掉同文档旧 chunk，保证重索引幂等）。"""
        if not chunks:
            return 0
        document_ids = {str(item["document_id"]) for item in chunks}
        with self.session() as handle:
            for document_id in document_ids:
                handle.execute(
                    delete(ChunkRecord).where(ChunkRecord.document_id == document_id)
                )
            for item in chunks:
                handle.add(
                    ChunkRecord(
                        chunk_id=str(item["chunk_id"]),
                        document_id=str(item["document_id"]),
                        seq=int(item["seq"]),
                        text=str(item["text"]),
                        start_char=int(item.get("start_char", 0)),
                        end_char=int(item.get("end_char", 0)),
                        heading_path=str(item.get("heading_path", "[]")),
                        token_estimate=int(item.get("token_estimate", 0)),
                    )
                )
            return len(chunks)

    def list_chunks(self, document_id: str) -> list[ChunkRecord]:
        """某文档的全部 chunk，按 ``seq`` 升序。"""
        with self.session() as handle:
            stmt = (
                select(ChunkRecord)
                .where(ChunkRecord.document_id == document_id)
                .order_by(ChunkRecord.seq)
            )
            return list(handle.scalars(stmt))

    def list_all_chunks(self) -> list[ChunkRecord]:
        """全库 chunk（BM25 全量重建用，设计文档 Q4）。"""
        with self.session() as handle:
            stmt = select(ChunkRecord).order_by(ChunkRecord.chunk_id)
            return list(handle.scalars(stmt))

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRecord]:
        """按 id 批量取 chunk（检索命中回填元数据用）。"""
        if not chunk_ids:
            return []
        with self.session() as handle:
            stmt = select(ChunkRecord).where(ChunkRecord.chunk_id.in_(list(chunk_ids)))
            return list(handle.scalars(stmt))

    def count_chunks(self) -> int:
        """全库 chunk 总数（知识库概览用）。"""
        with self.session() as handle:
            return int(handle.scalar(select(func.count()).select_from(ChunkRecord)) or 0)

    def delete_chunks(self, document_id: str) -> int:
        """删某文档全部 chunk 元数据；返回删除条数。"""
        with self.session() as handle:
            result = handle.execute(
                delete(ChunkRecord).where(ChunkRecord.document_id == document_id)
            )
            return int(result.rowcount or 0)

    # ----------------------------------------------------------------- meta --
    def get_meta(self, key: str) -> str | None:
        """读库级 meta（如当前 embedding 指纹）。"""
        with self.session() as handle:
            record = handle.get(KnowledgeMeta, key)
            return None if record is None else record.value

    def set_meta(self, key: str, value: str) -> None:
        """写库级 meta（upsert）。"""
        with self.session() as handle:
            record = handle.get(KnowledgeMeta, key)
            if record is None:
                record = KnowledgeMeta(key=key, value=value)
                handle.add(record)
            else:
                record.value = value

    def dispose(self) -> None:
        """释放连接池。"""
        self.engine.dispose()


__all__ = ["DEFAULT_AGENTS", "Database"]
