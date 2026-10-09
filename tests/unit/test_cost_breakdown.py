"""成本归因面板 · 刀 1（契约层）用例：T1–T7 + C6。

对应 ``docs/cost_attribution_plan_2026-09-25.md`` §10.3。全部走 fast 集：
不起队列、不碰真实 ``data/trinity.db``、零真实 token。

**为什么这些用例值得存在**（每条都写着「失败意味着什么」）：
面板的全部价值是数字可信，而它最容易说谎的三处是
①``event_type`` 过滤（次数会翻倍）、②``model IS NULL`` 的回落（拿今天的价填昨天的账）、
③单价反推（把「没验过」读成「验过了」）。C6 用的 fixture 是**库里五条真实运行**的
逐角色 ``(tokens_in, tokens_out, cost)``（``sqlite3 -readonly`` 查 ``task_events`` 得来，
见 ``_REAL_RUNS`` 的注释），不是拟合出来的数 —— 不造数是底线。

不用 pytest 的 ``tmp_path``：与 ``test_task_events.py`` 同一条本机约定
（沙箱对递归删除 fail-closed），库文件放 ``data/.test-scratch/``（已 gitignore）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.constants import STATUS_DONE, STATUS_RUNNING, TASK_EVT_LLM_CALL, TASK_EVT_NODE_END
from api.main import create_app
from api.routes import tasks as tasks_routes
from config import PROJECT_ROOT, Settings
from core.llm.adapter import LLMAdapter, MODEL_PRICES
from storage.db import Database
from storage.migrations import TASK_EVENTS_DDL, ensure_task_event_cost_columns
from storage.models import TaskEventRecord
from tests.unit.test_task_events import EXPECTED_COLUMNS

TEST_SCRATCH_ROOT = PROJECT_ROOT / "data" / ".test-scratch"

#: 表内高峰价（元 / 100 万 token），C6 的对照组。
#: 从 ``MODEL_PRICES`` 读而不是写死：表内价按官网调整时这条用例应当跟着走，
#: 而"调了价、反推立刻对不上"正是它要报出来的那件事。
TABLE_PRICE = MODEL_PRICES["deepseek-flash"]

#: 反推判据（百分数）。与被测实现里的 ``_PRICE_TOL_PCT`` 同值，但**故意不 import**：
#: 判据一旦从实现里借，实现把阈值改成 100% 也照样绿。这里独立声明，改阈值要靠人看见。
PRICE_TOL_PCT = 0.5

#: 库里五条真实运行（``1+1`` 问了五次）的逐角色用量。
#:
#: 来源：``task_events`` 表 ``event_type='llm_call'`` 按 ``(task_id, role)`` 求和
#: （只读查询，2026-09-25 量得）；``task_cost`` 是 ``tasks.cost`` 里**原样存着**的数
#: （= ``round(Σ, 6)``，见 ``evaluation/metrics.py:83``）；``multiplier`` 按
#: ``created_at``（UTC）换算北京时间后由 ``pricing.is_peak`` 判定 —— 只有第一条跑在
#: 23:34 的低谷，那正是「同一问题成本差 2.37×」的成因（方案 §1.5 结论 2）。
#:
#: ⚠️ 这五个 ``task_cost`` 与 Σ事件 cost 之间各有 1.9e-7 … 4.3e-7 的差（落库取整造成），
#: T1 的容差判据就是靠它来证明"1e-6 不是凑出来的"。
_REAL_RUNS: tuple[dict[str, Any], ...] = (
    {
        "task_id": "task-5ba7127ba5f0",
        "multiplier": 0.5,
        "task_cost": 0.00397,
        "roles": (("planner", 392, 68, 0.000707160), ("executor", 845, 203, 0.001764705), ("reviewer", 939, 117, 0.001498455)),
    },
    {
        "task_id": "task-ca988795dada",
        "multiplier": 1.0,
        "task_cost": 0.00826,
        "roles": (("planner", 392, 80, 0.001516560), ("executor", 950, 106, 0.002926620), ("reviewer", 1048, 186, 0.003816960)),
    },
    {
        "task_id": "task-b4abbf11e3db",
        "multiplier": 1.0,
        "task_cost": 0.009253,
        "roles": (("planner", 392, 92, 0.001618800), ("executor", 937, 114, 0.002967090), ("reviewer", 1011, 295, 0.004666830)),
    },
    {
        "task_id": "task-959b8c52f8a2",
        "multiplier": 1.0,
        "task_cost": 0.008959,
        "roles": (("planner", 392, 80, 0.001516560), ("executor", 926, 249, 0.004093860), ("reviewer", 996, 144, 0.003348360)),
    },
    {
        "task_id": "task-5e719c0be4bd",
        "multiplier": 1.0,
        "task_cost": 0.009395,
        "roles": (("planner", 392, 137, 0.002002200), ("executor", 1000, 67, 0.002700840), ("reviewer", 1111, 273, 0.004692390)),
    },
)

#: 迁移前的老表形状（没有 ``model`` / ``price_multiplier``），只给 T6 用。
#: 这里手写而不是从 ``TASK_EVENTS_DDL`` 抠两列：要模拟的就是"某一刻线上存在的库"，
#: 让它跟着 DDL 一起变就失去意义了。
_OLD_TABLE_DDL = """
CREATE TABLE task_events (
    event_seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    role          TEXT,
    step          INTEGER NOT NULL DEFAULT 0,
    sub_step      INTEGER,
    node          TEXT,
    thought       TEXT    NOT NULL DEFAULT '',
    tool_name     TEXT,
    arguments     TEXT,
    observation   TEXT    NOT NULL DEFAULT '',
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost          REAL    NOT NULL DEFAULT 0.0,
    status        TEXT    NOT NULL DEFAULT 'success',
    error_code    TEXT,
    error_message TEXT,
    sse_seq       INTEGER,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _scratch_path() -> Path:
    return TEST_SCRATCH_ROOT / f"cb-{uuid4().hex[:10]}.sqlite3"


@pytest.fixture()
def db_path() -> Path:
    return _scratch_path()


@pytest.fixture()
def database(db_path: Path) -> Iterator[Database]:
    """独立 SQLite 文件 + ``init_db``（启动链里含成本列迁移）。"""
    instance = Database(f"sqlite:///{db_path.as_posix()}")
    instance.init_db()
    yield instance
    instance.dispose()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, database: Database) -> Iterator[TestClient]:
    """把路由模块里的 ``get_database`` 换成 scratch 库。

    ⚠️ 必须 patch ``api.routes.tasks`` 侧的绑定：路由是 ``from api.deps import
    get_database``，那个名字已经进了本模块命名空间，patch ``api.deps`` 不生效
    （与 ``conftest._start_client`` 里 ``default_runner_factory`` 同一坑）。

    用 ``TestClient(app)`` 而**不进 context manager**：进了就跑 lifespan，而
    ``api/main.py`` 的启动钩子调的是 ``api.deps.get_database()``（**上面 patch 不到的那
    一个**）⇒ 会在真实 ``data/trinity.db`` 上建表补列，还会起一份线程池队列。
    本端点是纯 DB 读，不需要队列；``def`` 路由走线程池这件事 TestClient 照样覆盖。
    """
    monkeypatch.setattr(tasks_routes, "get_database", lambda: database)
    yield TestClient(create_app())


def _seed_task(
    database: Database,
    task_id: str,
    cost: float,
    *,
    status: str = STATUS_DONE,
) -> None:
    """造一条任务行（``cost`` = ``tasks.cost``，即 ``traces`` 侧求和后取整的账）。"""
    database.save_task(
        task_id=task_id,
        task="1+1 等于几",
        status=status,
        iterations=1,
        score=None,
        grade=None,
        final_answer="2",
        cost=cost,
        duration_ms=0,
        tool_calls=0,
        tool_failures=0,
    )


def _seed_llm_call(
    database: Database,
    task_id: str,
    role: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    *,
    model: str | None = "deepseek-flash",
    multiplier: float | None = 1.0,
    step: int = 0,
) -> None:
    """落一条 ``llm_call`` 事件（与 ``core/agent/base.py`` 的写入路径同一个入口）。"""
    assert (
        database.record_event(
            task_id=task_id,
            event_type=TASK_EVT_LLM_CALL,
            role=role,
            node=role,
            step=step,
            status="success",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            model=model,
            price_multiplier=multiplier,
        )
        is not None
    ), "record_event 返回 None = 写入失败，后面的断言全都没有意义"


def _seed_run(database: Database, run: dict[str, Any], *, cost_scale: float = 1.0) -> None:
    """按 ``_REAL_RUNS`` 的一条造完整任务（``cost_scale`` 给 C6 的负面对照用）。"""
    _seed_task(database, str(run["task_id"]), float(run["task_cost"]))
    for step, (role, tokens_in, tokens_out, cost) in enumerate(run["roles"]):
        _seed_llm_call(
            database,
            str(run["task_id"]),
            str(role),
            int(tokens_in),
            int(tokens_out),
            float(cost) * cost_scale,
            multiplier=float(run["multiplier"]),
            step=step,
        )


def _get(client: TestClient, task_id: str) -> dict[str, Any]:
    response = client.get(f"/tasks/{task_id}/cost-breakdown")
    assert response.status_code == 200, f"成本端点应 200，实际 {response.status_code}：{response.text}"
    return response.json()


def _raw_llm_sum(db_path: Path) -> tuple[int, int, int, float]:
    """**绕开被测代码**，用裸 SQL 数第三本账（T1 的第三方）。

    如果只拿端点的 ``totals`` 和端点的 ``by_role`` 比，那是自己跟自己对齐；
    这里直接从文件里 ``SELECT``，才构成"两个独立实现"。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0),"
            " COALESCE(SUM(cost),0.0) FROM task_events WHERE event_type = ?",
            (TASK_EVT_LLM_CALL,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]), int(row[1]), int(row[2]), float(row[3])


class TestTotalsAndReconcile:
    """T1 / T2：合计口径与对账。"""

    def test_t1_three_books_agree(self, client: TestClient, database: Database, db_path: Path) -> None:
        """T1：``Σ by_role.cost`` == 端点 ``totals.cost`` == 裸 SQL 的和 == ``tasks.cost``。

        失败意味着：``cost_breakdown`` 换了聚合源或漏了 ``event_type`` 过滤，
        于是面板上的「总花费」与任务列表里的花费开始各说各话。
        """
        run = _REAL_RUNS[4]
        _seed_run(database, run)

        body = _get(client, str(run["task_id"]))
        by_role_cost = sum(float(row["cost"]) for row in body["by_role"])
        calls, tokens_in, tokens_out, raw_cost = _raw_llm_sum(db_path)

        assert by_role_cost == pytest.approx(body["totals"]["cost"], abs=1e-12)
        assert calls == body["totals"]["calls"] == 3
        assert tokens_in == body["totals"]["tokens_in"]
        assert tokens_out == body["totals"]["tokens_out"]
        # 第三方：裸 SQL 的和与端点合计
        assert raw_cost == pytest.approx(body["totals"]["cost"], abs=1e-12)
        # 对账：真实任务的 ``tasks.cost`` 是 round(Σ, 6)，差额 4.3e-7（实测）必须在容差内
        assert float(run["task_cost"]) == pytest.approx(body["totals"]["cost"], abs=1e-6)
        assert body["reconcile"]["all_equal"] is True, f"真实数据把对账判红了：{body['reconcile']['note']}"
        assert body["reconcile"]["note"] == ""

    def test_t1_non_llm_events_excluded(
        self, client: TestClient, database: Database, db_path: Path
    ) -> None:
        """T1 反向钉：往 ``node_end`` 上塞 cost ⇒ **不许**进合计。

        失败意味着：``event_type='llm_call'`` 那条形而不用地写在了 ``cost_breakdown``
        的 docstring 里却没进 SQL，非 LLM 事件的 0 值开始混进次数与金额。
        """
        run = _REAL_RUNS[4]
        _seed_run(database, run)
        assert (
            database.record_event(
                task_id=str(run["task_id"]),
                event_type=TASK_EVT_NODE_END,
                role="executor",
                node="executor",
                step=9,
                status="success",
                cost=0.5,
                tokens_in=99,
                tokens_out=99,
            )
            is not None
        )

        body = _get(client, str(run["task_id"]))
        assert body["totals"]["calls"] == 3, "node_end 被当成一次 LLM 调用了"
        assert body["totals"]["cost"] == pytest.approx(float(run["task_cost"]), abs=1e-6)
        assert body["totals"]["tokens_in"] < 99 + 2803
        # 库里确实多了那 0.5 元 —— 证明"排除"是被过滤做到的，不是没写进去
        conn = sqlite3.connect(str(db_path))
        try:
            assert float(conn.execute("SELECT SUM(cost) FROM task_events").fetchone()[0]) > 0.5
        finally:
            conn.close()

    def test_t2_calls_counts_llm_call_only(self, client: TestClient, database: Database) -> None:
        """T2：``calls`` 是 ``llm_call`` 的条数，不是事件条数（实测差 4 倍）。

        失败意味着：次数读数被 ``node_end`` / ``tool_call`` / ``running`` 撑大 ——
        ``task-5e719c0be4bd`` 的 executor 就是 1 次调用对 4 条事件（真实库里量的）。
        """
        task_id = "task-t2-calls"
        _seed_task(database, task_id, 0.00270084)
        _seed_llm_call(database, task_id, "executor", 1000, 67, 0.00270084)
        # 同一次调用在库里的其余三条事件（都带 role=executor）
        for event_type, node in ((TASK_EVT_NODE_END, "executor"),):
            assert database.record_event(
                task_id=task_id, event_type=event_type, role="executor", node=node, step=0, status="success"
            )
        assert database.record_event(
            task_id=task_id, event_type="tool_call", role="executor", node="executor", step=0, status="success"
        )
        assert database.record_event(
            task_id=task_id, event_type="running", role=None, node=None, step=0, status="running"
        )

        body = _get(client, task_id)
        executor_rows = [row for row in body["by_role"] if row["role"] == "executor"]
        assert len(executor_rows) == 1
        assert executor_rows[0]["calls"] == 1, "次数把非 LLM 事件算进去了（不摘掉 event_type 过滤就会这样）"
        assert body["totals"]["calls"] == 1
        # 反向：事件总数确实是 4，说明上面那个 1 是"过滤"滤出来的，不是数据本来就只有 1 条
        assert database.count_events(task_id) == 4


class TestPriceCheck:
    """C6：单价反推（服务端那一半守门人）。"""

    @pytest.mark.parametrize("run", _REAL_RUNS, ids=lambda run: str(run["task_id"]))
    def test_c6_implied_price_matches_table(self, client: TestClient, database: Database, run: dict[str, Any]) -> None:
        """C6：五条真实运行各自反推出 ``TABLE_PRICE``，±容差内。

        每条都有 planner + executor 两行做方程、reviewer 一行做独立验证 ⇒
        ``equations == 3``。低谷那条（``multiplier=0.5``）也在同一对单价上对咬，
        说明系数是被正确解出的（否则它会反推出表内价的一半）。

        失败意味着：写入侧的 ``cost`` 与读取侧的单价表开始分叉 —— 比如单位口径
        漂了 10⁶ 倍，或者 ``price_multiplier`` 被套了两遍。
        """
        _seed_run(database, run)

        body = _get(client, str(run["task_id"]))
        check = body["price_check"]
        assert check["ok"] is True, f"真实账目反推不通过：{check}"
        assert check["reason"] is None
        assert check["equations"] == 3
        assert check["max_delta_pct"] is not None and check["max_delta_pct"] <= PRICE_TOL_PCT
        assert check["implied_price_in"] == pytest.approx(TABLE_PRICE[0], rel=PRICE_TOL_PCT / 100)
        assert check["implied_price_out"] == pytest.approx(TABLE_PRICE[1], rel=PRICE_TOL_PCT / 100)

    def test_c6_detects_perturbed_cost(self, client: TestClient, database: Database) -> None:
        """C6 反向钉：把其中一行的 ``cost`` 抬 1% ⇒ 判据必须翻红。

        上一那条用例只能证明"对得上时它说对"；这条证明"对不上时它说不对"。
        少了这条，``ok`` 完全可以是被硬编码的 ``True``。
        """
        run = _REAL_RUNS[4]
        _seed_task(database, str(run["task_id"]), float(run["task_cost"]))
        for step, (role, tokens_in, tokens_out, cost) in enumerate(run["roles"]):
            # 只扰动第一行：另外两行留着当独立验证
            scaled = float(cost) * (1.01 if step == 0 else 1.0)
            _seed_llm_call(
                database,
                str(run["task_id"]),
                str(role),
                int(tokens_in),
                int(tokens_out),
                scaled,
                multiplier=1.0,
                step=step,
            )

        body = _get(client, str(run["task_id"]))
        check = body["price_check"]
        assert check["ok"] is False, f"扰动 1% 没被抓出来：{check}"
        assert check["max_delta_pct"] is not None and check["max_delta_pct"] > PRICE_TOL_PCT
        assert check["reason"], "判不通过也要给原因，否则页面上只剩一个 ✗"

    def test_c6_refuses_to_guess(self, client: TestClient, database: Database) -> None:
        """C6 第三条腿：凑不齐两条同单价的方程 ⇒ ``ok is None``，**不是** ``True``。

        做法是让三个角色各自落在不同系数档（三个桶、每桶一行）。
        失败意味着：反推在"没验"的时候返回了 ``True``/``0``，于是面板把「没验过」
        显示成「验过了」—— 这个字段的全部意义就没了。
        """
        task_id = "task-c6-unguessable"
        _seed_task(database, task_id, 0.006)
        for step, multiplier in enumerate((1.0, 0.5, 0.75)):
            _seed_llm_call(
                database,
                task_id,
                f"role{step}",
                400 + step,
                90 + step,
                0.002 * (step + 1),
                multiplier=multiplier,
                step=step,
            )

        body = _get(client, task_id)
        check = body["price_check"]
        assert check["ok"] is None, f"方程不足时必须回答「判不了」：{check}"
        assert check["max_delta_pct"] is None
        assert check["reason"]


class TestLegacyRows:
    """T3 / T4：历史行与跨峰谷。"""

    def test_t3_null_model_does_not_fall_back(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T3：``model IS NULL`` 的旧行 ⇒ ``price_source="unknown"``、单价 ``None``。

        反向钉：把当前配置的模型名换成一个哨兵串，响应文本里**不许**出现它 ——
        出现即说明读取侧拿今天的 ``role_map`` 去填了昨天的账（不造数是底线）。
        """
        from config import get_settings

        sentinel = "model-from-todays-config-SHOULD-NOT-APPEAR"
        settings = get_settings()
        monkeypatch.setattr(settings, "llm_model_large", sentinel, raising=False)
        monkeypatch.setattr(settings, "llm_model_small", sentinel, raising=False)

        task_id = "task-t3-legacy"
        _seed_task(database, task_id, 0.00126735)
        _seed_llm_call(
            database, task_id, "planner", 418, 193, 0.00126735, model=None, multiplier=None
        )

        response = client.get(f"/tasks/{task_id}/cost-breakdown")
        assert response.status_code == 200
        body = response.json()
        assert sentinel not in response.text, "旧任务的响应里漏进了当前配置的模型名"

        row = body["by_role"][0]
        assert row["model"] is None
        assert row["price_multiplier"] is None
        assert row["peak"] is None, "系数没记 ⇒ peak 也必须 None，不许猜一个 False（False 读作「低谷」）"
        assert row["price_source"] == "unknown"
        assert row["unit_price_in"] is None
        assert row["unit_price_out"] is None
        # 钱还是要算进来的：NULL 的是"为什么"，不是"花了多少"
        assert body["totals"]["cost"] == pytest.approx(0.00126735, abs=1e-12)
        # 无 model ⇒ 无从反推单价，也必须老实说判不了
        assert body["price_check"]["ok"] is None

    def test_t4_role_spanning_peak_and_off_peak_makes_two_rows(
        self, client: TestClient, database: Database
    ) -> None:
        """T4：同一角色跨峰谷边界 ⇒ 两行、两个系数（方案 §5.5）。

        反向钉：两行的 ``role`` 必须相同 ⇒ 行数从 2 退回 1 就只能怪"按角色二次聚合"，
        而不是数据里真有别的角色。
        """
        task_id = "task-t4-boundary"
        _seed_task(database, task_id, 0.0024)
        _seed_llm_call(database, task_id, "planner", 392, 68, 0.001267, multiplier=1.0, step=0)
        _seed_llm_call(database, task_id, "planner", 392, 68, 0.001133, multiplier=0.5, step=1)

        body = _get(client, task_id)
        rows = body["by_role"]
        assert len(rows) == 2, f"跨峰谷必须留两行，实际 {rows}"
        assert {row["price_multiplier"] for row in rows} == {1.0, 0.5}
        assert {row["peak"] for row in rows} == {True, False}
        assert {row["role"] for row in rows} == {"planner"}
        assert body["totals"]["calls"] == 2, "两行是同一次运行的两次调用，不该被折叠成 1"


class TestEmptyAndMissing:
    """T5：空明细与 404 —— 「没花钱」和「没这条任务」是两种事实。"""

    def test_t5_terminal_task_without_llm_calls_is_200(self, client: TestClient, database: Database) -> None:
        task_id = "task-t5-empty"
        _seed_task(database, task_id, 0.0)
        assert database.record_event(
            task_id=task_id, event_type="running", role=None, node=None, step=0, status="running"
        )

        body = _get(client, task_id)
        assert body["by_role"] == []
        assert body["totals"] == {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0}
        assert body["price_check"]["ok"] is None and body["price_check"]["reason"]
        assert body["reconcile"]["all_equal"] is True  # 0 == 0，两本账都空
        assert body["reconcile"]["note"] == ""
        # 时段三件事照给（与本次运行无关，是「查询此刻」的事实）
        assert body["window"]["multiplier_now"] in (1.0, 0.5)
        assert isinstance(body["window"]["is_peak_now"], bool)
        # C7：低谷时「下一次」为 null，别让前端自己判断现在是哪一档
        assert (body["window"]["next_off_peak_at"] is None) is (not body["window"]["is_peak_now"])
        assert body["generated_at"].endswith("+08:00"), "时间必须带北京时间偏移（避坑 1）"

    def test_t5_unknown_task_is_404(self, client: TestClient) -> None:
        response = client.get("/tasks/task-does-not-exist/cost-breakdown")
        assert response.status_code == 404, "不存在的任务不许返回 200 空账（那读起来像「跑了但免费」）"
        # 错误体是 ``{"detail": {"code", "message", ...}}``；``code`` 是**领域码**
        # （路由显式 raise 的 TASK_NOT_FOUND），与 Starlette 兜底的通用 ``not_found`` 不同，
        # 与 ``test_trace_api.py:330`` 同一条口径。
        assert response.json()["detail"]["code"] == "task_not_found", response.text

    def test_running_task_reconcile_is_not_applicable(self, client: TestClient, database: Database) -> None:
        """未终态任务的对账是「不适用」而不是「不等」。

        实测依据：``task-1365c179c055`` 停在 ``running``、``tasks.cost=0``、
        Σ ``llm_call``=0.0126 元。判红是给一个根本不存在的账本找茬。
        """
        task_id = "task-running-partial"
        _seed_task(database, task_id, 0.0, status=STATUS_RUNNING)
        _seed_llm_call(database, task_id, "planner", 392, 68, 0.00070716)

        body = _get(client, task_id)
        assert body["reconcile"]["all_equal"] is None
        assert "不适用" in body["reconcile"]["note"]
        assert body["totals"]["cost"] == pytest.approx(0.00070716, abs=1e-12)


class TestMigrationAndSchemaSource:
    """T6 / T7：加列的迁移，以及「清单与 DDL 不许单边漂」。"""

    def test_t6_cost_columns_backfill_is_idempotent(self, db_path: Path) -> None:
        """T6：老库（无两列）补一次就有，再跑两次返回 ``[]``。

        失败意味着：启动链里的 ``ensure_task_event_cost_columns`` 不再幂等，
        每次重启都试图 ``ALTER`` 已存在的列（SQLite 会直接报错，被 warning 吞掉，
        于是新库永远缺列）。
        """
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(_OLD_TABLE_DDL)
            conn.commit()
        finally:
            conn.close()

        assert "model" not in _columns(db_path)
        first = ensure_task_event_cost_columns(db_path)
        assert sorted(first) == ["model", "price_multiplier"], f"首次应补两列，实际 {first}"
        assert ensure_task_event_cost_columns(db_path) == []
        assert ensure_task_event_cost_columns(db_path) == []
        columns = _columns(db_path)
        assert {"model", "price_multiplier"} <= columns

    def test_t6_non_sqlite_and_missing_file_are_noops(self, db_path: Path) -> None:
        """T6 附加：非 SQLite 传 ``None``、文件还不存在时都不抛。

        ``None`` 那条是整个迁移层的统一约定（PG 上这两列由 ``create_all`` 建），
        抛出来会把服务起不来。
        """
        assert ensure_task_event_cost_columns(None) == []
        assert ensure_task_event_cost_columns(_scratch_path()) == []

    def test_t7_checklist_ddl_and_orm_are_the_same_source(self) -> None:
        """T7：``EXPECTED_COLUMNS``、``TASK_EVENTS_DDL``、ORM 声明三者列集合必须全等。

        这条是给「改了 DDL 忘了清单」准备的：``test_task_events.py:115`` 那条全等
        会在**建表路径**上红，但那是"库里有没有"；本条比的是"三份声明有没有分叉"，
        比的是纸面。两边都要，缺一边就还有一条没人看的漂移路径。

        ⚠️ 判据是**集合全等**，不许改成 ``>=`` 或 ``issubset``：那等于把守门人拆了
        （多一列同样是要报警的事）。
        """
        from_ddl = _ddl_column_names(TASK_EVENTS_DDL)
        from_orm = set(TaskEventRecord.__table__.columns.keys())

        assert from_ddl == EXPECTED_COLUMNS, (
            f"DDL 与清单分叉 —— 只在 DDL 里：{from_ddl - EXPECTED_COLUMNS}，"
            f"只在清单里：{EXPECTED_COLUMNS - from_ddl}"
        )
        assert from_orm == EXPECTED_COLUMNS, (
            f"ORM 与清单分叉 —— 只在 ORM 里：{from_orm - EXPECTED_COLUMNS}，"
            f"只在清单里：{EXPECTED_COLUMNS - from_orm}"
        )
        # 成本归因那两列必须在，且在 ORM 侧可空（NULL=未记录，见 §10.2d）
        assert {"model", "price_multiplier"} <= EXPECTED_COLUMNS
        for name in ("model", "price_multiplier"):
            assert TaskEventRecord.__table__.columns[name].nullable is True


class TestWritePath:
    """W1 / W2 / W3：写入侧（``Usage`` → ``EventRecord`` → 两列）。

    这一组是补的，不是原本就有的：刀 1 第一版只有下面那 18 条读取侧用例，
    而 ``Usage.multiplier`` 这个字段**当时压根没落到盘上**（``_emit_events`` 吃的是
    ``getattr(usage, "multiplier", None)``，字段不存在就静默成 ``None``），
    18 条照样全绿 —— 因为没有一条走 ``core/agent/base.py`` 那三行。
    读取侧的用例验不出写入侧缺字段，而缺字段的后果是"迁移报成功、列永远 NULL、
    面板把所有调用都标成未记录"。教训写进 README：**端点绿灯不等于链路绿灯**。
    """

    def test_w1_node_lands_model_and_multiplier(
        self, client: TestClient, database: Database, db_path: Path
    ) -> None:
        """W1：真实埋点路径 ⇒ 两列非 NULL ⇒ 端点按系数分组、峰谷标出 ``False``。

        失败意味着：``_emit_events`` 的 ``model=`` / ``price_multiplier=`` 或
        ``EventRecord.to_row()`` 里那两个键被摘掉（``to_row`` 是**显式枚举**的字典，
        加字段不加工具行不会报错，只会静默丢）。
        """
        from core.agent.base import BaseNode, NodeContext
        from core.events import EventRecord
        from core.llm.adapter import Usage

        captured: list[EventRecord] = []

        class _ProbeNode(BaseNode):
            role = "planner"  # type: ignore[assignment]

            def run(self, state: Any) -> dict[str, Any]:  # noqa: D401 - 探针节点无业务
                return {"current_step": "拆解"}

        node = _ProbeNode(
            NodeContext.create(
                llm=cast(Any, object()),
                event_sink=lambda record: captured.append(record),
            )
        )
        # 一次跑在低谷（×0.5）的调用：cost 已按 0.5 算过，multiplier 必须记同一个数
        usage = Usage(
            model="deepseek-flash", token_in=392, token_out=68, cost=0.00070716, multiplier=0.5
        )
        node._emit_events(
            {"task_id": "task-w1", "task": "1+1"}, {"current_step": "拆解"}, "success", 12, 0, usage, True
        )

        assert len(captured) == 2, "一次调用一个节点 ⇒ L1 llm_call + L2 node_end 各一条"
        by_type = {record.event_type: record for record in captured}
        assert set(by_type) == {TASK_EVT_LLM_CALL, TASK_EVT_NODE_END}
        record = by_type[TASK_EVT_LLM_CALL]
        assert record.model == "deepseek-flash"
        assert record.price_multiplier == 0.5
        # 只有 llm_call 带这两件（§6 避坑 2）：node_end 上放值会让面板把一次调用数成两次
        assert by_type[TASK_EVT_NODE_END].model is None
        assert by_type[TASK_EVT_NODE_END].price_multiplier is None
        row = record.to_row()
        # to_row 是显式枚举：这两行是"字段没被静默丢掉"的直接证据
        assert row.get("model") == "deepseek-flash"
        assert row.get("price_multiplier") == 0.5

        assert database.record_event(**row) is not None
        _seed_task(database, "task-w1", 0.00070716)
        body = _get(client, "task-w1")
        assert body["by_role"][0]["price_multiplier"] == 0.5
        assert body["by_role"][0]["peak"] is False, "×0.5 必须读成低谷，不是 True 也不是 None"
        assert body["by_role"][0]["price_source"] == "official_table"
        assert body["reconcile"]["all_equal"] is True

    def test_w2_adapter_reads_the_clock_once(self) -> None:
        """W2：每个 ``Usage`` 构造点只读**一次**时段系数（§10.2b）。

        这条是**静态**判据（跑不到真实 ``_call``：测试无网络、``MockLLMAdapter`` 绕开了
        ``adapter._call``），钉的是"不许把时段系数当场调进 ``estimate_cost`` 又另读一次"。
        写错的后果不会报错，只会让 ``cost`` 与 ``multiplier`` 跨 12:00 / 18:00 边界时
        不同档 —— 两份自相矛盾的账。

        2026-09-26 换供应商后系数不再直接来自 ``price_multiplier()``：分不分峰谷是
        **供应商**的属性，所以读取点改成 ``runtime.effective_multiplier(``，
        真正读时钟的那一处收进了 runtime。于是这条判据管三件事：
        ① adapter 里每个 ``last_usage`` 构造点前恰读一次时钟（个数不写死，见下面那段）；② adapter 里不许再出现内联读时钟；
        ③ 全项目 ``price_multiplier()`` 的调用点只剩 runtime 那一处
        （多一处就多一个口径 —— 与 ``resolve_price`` 同源是同一条纪律）。

        失败意味着：有人把 ``mult`` 局部量改回了内联调用，或新增了一个**没配套读时钟**的
        ``last_usage`` 构造点（成对新增的第 3 处不会红 —— 那条不写死个数）。
        """
        source = (PROJECT_ROOT / "core" / "llm" / "adapter.py").read_text(encoding="utf-8")
        assert "multiplier=price_multiplier()" not in source, (
            "Usage 构造点上又出现了内联时段系数：cost 与 multiplier 会各自读时钟"
        )
        assert "price_multiplier()" not in source, "adapter 不该再直接读时钟（改走 runtime）"
        # ★ 改前这里写死 ``== 2``（非流式 ``_call`` + 流式 ``stream`` 各一处）。
        #   2026-10-02 删掉那条零调用的 ``adapter.stream()`` 后只剩 1 处 ——
        #   常数改不成对地绑在结构上，就会把"结构变了"误报成"账算错了"，
        #   而这条用例自己反对的正是那种两份账。所以改成与构造点配对计数。
        clock_reads = source.count("mult = runtime.effective_multiplier(")
        usage_writes = source.count("self.last_usage = Usage(")
        assert clock_reads >= 1, "adapter 里一次时钟都没读：last_usage 无从定档"
        assert clock_reads == usage_writes, (
            f"时钟读数({clock_reads}) ≠ last_usage 构造点({usage_writes}) ⇒ "
            "要么某个 Usage 没跟着定档，要么同一处读了第二次"
        )
        assert "multiplier=mult" in source and "cost=self.estimate_cost(" in source
        runtime_source = (PROJECT_ROOT / "core" / "llm" / "runtime.py").read_text(encoding="utf-8")
        assert runtime_source.count("price_multiplier()") == 1, (
            "读时钟的入口应当只有 runtime 那一处；两处就会各读各的档"
        )

    def test_w3_mock_usage_defaults_to_peak_multiplier(self) -> None:
        """W3：不填 ``multiplier`` 的 ``Usage``（Mock 路径）⇒ 记的是 1.0，**不是** NULL。

        写清楚这条不是为了夸它：``MockLLMAdapter`` 造 ``Usage`` 时不传时段系数，
        默认值 1.0 会一路进库。所以集成测试里看到的"全部高峰"是默认值，
        不是"当时真的在高峰"（方案 §10.2f 的提醒）。要测低谷必须在用例里显式给。
        """
        from core.llm.adapter import Usage

        assert Usage(model="deepseek-flash").multiplier == 1.0
        assert Usage(model="deepseek-flash", multiplier=0.5).multiplier == 0.5
        # as_dict 会把 multiplier 一起带出去（TraceRecord 构造是显式 kwargs，不受影响）
        assert "multiplier" in Usage(model="m", multiplier=0.5).as_dict()


    def test_w4_negative_control_missing_attribute(self, client: TestClient, database: Database) -> None:
        """W1 的负面对照：**不做源码破坏**，而是喂一个「没有 ``multiplier`` 属性」的用量对象。

        那正是我第一版的真实形状 —— ``Usage`` 上加了字段又「说」写好了，但
        ``_emit_events`` 吃的是 ``getattr(usage, "multiplier", None)``，字段不存在时
        静默变 ``None``，18 条读取侧用例全绿。所以这条用例断言的是**反方向的可见后果**：

        * ``record.price_multiplier is None``（把 W1 那行断言接回来就是红的）；
        * 端点读到的是 ``null`` + ``peak=null`` + ``price_source="unknown"``，
          **不是** 1.0 / ``True`` / 当前 ``role_map`` 里的模型 —— 缺证据时它必须说不知道。

        这样即便不去改生产代码，也能证明 W1 抓的是这条链路而不是恒绿。
        """
        from core.agent.base import BaseNode, NodeContext
        from core.events import EventRecord

        captured: list[EventRecord] = []

        class _BlindNode(BaseNode):
            role = "executor"  # type: ignore[assignment]

            def run(self, state: Any) -> dict[str, Any]:
                return {}

        node = _BlindNode(
            NodeContext.create(
                llm=cast(Any, object()), event_sink=lambda record: captured.append(record)
            )
        )

        class _LegacyUsage:  # 没有 multiplier / model 之外的时段信息
            model = "deepseek-flash"
            token_in = 1000
            token_out = 67
            cost = 0.00270084
            duration_ms = 42

        node._emit_events(
            {"task_id": "task-w4", "task": "1+1"},
            {},
            "success",
            42,
            0,
            cast(Any, _LegacyUsage()),
            True,
        )
        record = next(item for item in captured if item.event_type == TASK_EVT_LLM_CALL)
        assert record.price_multiplier is None
        assert record.model == "deepseek-flash", "model 一直有，只有系数是这次新加的"

        assert database.record_event(**record.to_row()) is not None
        _seed_task(database, "task-w4", 0.00270084)
        row = _get(client, "task-w4")["by_role"][0]
        assert row["price_multiplier"] is None
        assert row["peak"] is None, "系数没记 ⇒ 端点不许替它挑一档（1.0 会被读成「当时在高峰」）"
        assert row["model"] == "deepseek-flash"
        # 单价仍然可给（model 有 ⇒ 查表），这与"当时乘了几倍"是两件事
        assert row["price_source"] == "official_table"


class TestTieredProviderPricing:
    """换供应商之后，面板对"分档 / 不分峰谷"这两件事必须**改口**而不是硬判。

    两条都是"不报错、只算错或只说谎"的形状：

    * 智谱与千问按**输入长度**分档 ⇒ 同一个 ``(模型, 系数)`` 组里各次调用的单价可能不同，
      而反推的前提是"单价是常数"。硬判会得到一个与表内任何一档都对不上的数，
      面板把它显示成「单价漂移」—— 那是**假红**，而 C6 这条守门人的存在理由恰恰是
      "不许把没验过的东西显示成验过了"（反过来 ``ok=None`` 才是诚实的）。
    * 高峰/低谷是 DeepSeek 一家的规则。给智谱的行贴「高峰」，
      等于宣布一个并不存在的档位；给 ``1.0`` 贴上"低谷没记"又是另一种谎。
    """

    def _row(self, role: str, model: str, mult: float, tin: int, tout: int, cost: object) -> Any:
        from api.schemas import CostRoleRow

        return CostRoleRow(
            role=role,
            model=model,
            price_multiplier=mult,
            calls=1,
            tokens_in=tin,
            tokens_out=tout,
            cost=float(cost),
        )

    def test_阶梯模型的单价反推改判为判不了(self) -> None:
        from core.llm.adapter import resolve_price

        settings = Settings(_env_file=None)
        # 两行不同长度 ⇒ 不同档：单价不是常数，方程组的解必然与表内某档不符
        low_in, low_out = resolve_price("glm-4.6", settings, 10_000)[:2]
        high_in, high_out = resolve_price("glm-4.6", settings, 40_000)[:2]
        assert (low_in, low_out) != (high_in, high_out), "前提不成立：32K 边界两侧同价"
        rows = [
            self._row("planner", "glm-4.6", 1.0, 10_000, 500, (10_000 * low_in + 500 * low_out) / 1e6),
            self._row("executor", "glm-4.6", 1.0, 40_000, 800, (40_000 * high_in + 800 * high_out) / 1e6),
        ]
        check = tasks_routes._price_check(rows, settings)
        assert check.ok is None, "阶梯模型硬判会得到假红（把「没法判」显示成「单价漂移」）"
        assert "分档" in (check.reason or ""), check.reason

    def test_不分峰谷的家不贴峰谷标签(self) -> None:
        assert tasks_routes._peak_from_multiplier(1.0, "deepseek-flash") is True
        assert tasks_routes._peak_from_multiplier(0.5, "deepseek-flash") is False
        assert tasks_routes._peak_from_multiplier(1.0, "glm-4.6") is None, (
            "智谱没有峰谷档：这里的 1.0 是「没有折扣」，不是「高峰」"
        )
        assert tasks_routes._peak_from_multiplier(1.0, "qwen-plus") is None
        assert tasks_routes._peak_from_multiplier(None, "glm-4.6") is None

    def test_同一系数在两家含义不同但金额都算对(self) -> None:
        """记账方向：``×1.0`` 在 DeepSeek 是高峰价、在智谱是官网价 —— 金额对，标签各说各话，
        所以标签必须由"这家分不分峰谷"来决定，不能由系数决定。"""
        from core.llm.adapter import resolve_price

        settings = Settings(_env_file=None)
        adapter = LLMAdapter(settings=settings)
        # 低谷时刻 DeepSeek 打半价，智谱恒 1.0（effective_multiplier 的判据在
        # tests/unit/test_llm_providers.py 里直接钉 monkeypatch 后的系数）
        deep = adapter.estimate_cost(1_000_000, 0, model="deepseek-flash", multiplier=0.5)
        assert deep == pytest.approx(TABLE_PRICE[0] * 0.5, rel=1e-9)
        # 同一个 1_000_000 输入给 GLM-4.6：记账按**它落在的那一档**（2 元），
        # 而注册表"不知道多长"报的是最低档 1 元 ⇒ 报价是下界，不是同一个数，也不该是
        glm = adapter.estimate_cost(1_000_000, 0, model="glm-4.6", multiplier=1.0)
        assert glm == pytest.approx(2.0, rel=1e-9)
        assert resolve_price("glm-4.6", settings)[0] == 1.0

    def test_glm_按输入长度选到正确的档(self) -> None:
        """阶梯不是摆设：40K 输入的这一次调用必须按 2/6 那一档计，而不是最低档 1/3。"""
        from core.llm.adapter import resolve_price

        settings = Settings(_env_file=None)
        adapter = LLMAdapter(settings=settings)
        short = adapter.estimate_cost(10_000, 1_000, model="glm-4.6")
        long_ = adapter.estimate_cost(40_000, 1_000, model="glm-4.6")
        assert short == pytest.approx((10_000 * 1.0 + 1_000 * 3.0) / 1_000_000, rel=1e-9)
        assert long_ == pytest.approx((40_000 * 2.0 + 1_000 * 6.0) / 1_000_000, rel=1e-9)
        assert long_ > short
        # 注册表"不知道长度"时报的是最低档 ⇒ 是下界，页面必须连着 tiers 一起显示
        assert resolve_price("glm-4.6", settings)[:2] == (1.0, 3.0)


def _columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(task_events)")}
    finally:
        conn.close()


def _ddl_column_names(ddl: str) -> set[str]:
    """从 ``CREATE TABLE`` 文本里抠出列名（第一个 token）。

    只做"看得懂的 DDL"的解析：本仓库的规范 DDL 是一行一列、列名打头，
    出现解析不了的行就 ``AssertionError`` —— 静默跳过会让 T7 变成一条恒绿用例。
    """
    body = ddl.split("(", 1)[1].rsplit(")", 1)[0]
    names: set[str] = set()
    for line in body.splitlines():
        text = line.strip().rstrip(",").strip()
        if not text:
            continue
        first, *rest = text.split()
        if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        assert rest, f"DDL 行解析不出类型，T7 需要跟着改：{line!r}"
        names.add(first)
    return names


__all__ = ["_REAL_RUNS", "TABLE_PRICE"]
