"""``GET /stats/dashboard`` 与 ``/console`` 静态托管的集成测试。

聚合口径逐项验证（零真实 LLM 调用，任务行直接经 ``Database.save_task`` 造数）：

* 完成率只认 ``done``（aborted / failed / canceled 都不算）；
* 平均分跳过 ``score=None`` 的行（不参与平均，既不拉低也不抬高）；
* daily 序列近 14 天无数据日补零；
* system 字段与 ``core.llm.pricing`` / 缓存降级 / DB 探活一致；
* ``/console`` 这条路由**已经不存在**（2026-09-27 摘掉静态托管并删掉 ``web/``）：
  未启用鉴权时整棵树 404 JSON，启用鉴权时仍然是 401 —— 鉴权中间件跑在路由之前。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from api.deps import get_database
from config import reset_settings_cache
from core.llm.pricing import is_peak, price_multiplier
from tests.integration.conftest import Recorder, _apply_api_env, _start_client


def _seed_task(task_id: str, status: str, *, score: int | None = None, cost: float = 0.0) -> None:
    """直接往 tasks 表写一行终态数据（created_at 取 server_default，即今天）。"""
    database = get_database()
    database.save_task(
        task_id=task_id,
        task=f"测试任务 {task_id}",
        status=status,
        iterations=1,
        score=score,
        grade="good" if score is not None else None,
        final_answer=f"{task_id} 的答案",
        cost=cost,
        duration_ms=1500,
        tool_calls=0,
        tool_failures=0,
    )


@pytest.fixture()
def seeded_env(api_env: TestClient) -> TestClient:
    """预置两行今天的任务：一条 done（score=8，cost 0.5）、一条 failed（无分，cost 0.25）。"""
    _seed_task("task-stat-done-01", "done", score=8, cost=0.5)
    _seed_task("task-stat-fail-01", "failed", score=None, cost=0.25)
    return api_env


class TestDashboardToday:
    """today 聚合口径。"""

    def test_today_counts_and_rate(self, seeded_env: TestClient) -> None:
        body = seeded_env.get("/stats/dashboard").json()
        today = body["today"]
        assert today["count"] >= 2
        done_keys = [t for t in (today,) if t["done_count"] >= 1]
        assert done_keys, "done 任务未被计入"
        assert today["done_count"] >= 1

    def test_completion_rate_only_counts_done(self, seeded_env: TestClient) -> None:
        """2 条任务里 1 条 done、1 条 failed → 完成率恰好 0.5（failed 不算完成）。"""
        body = seeded_env.get("/stats/dashboard").json()
        today = body["today"]
        expected = today["done_count"] / today["count"]
        assert today["completion_rate"] == pytest.approx(expected)

    def test_avg_score_skips_null(self, seeded_env: TestClient) -> None:
        """failed 行 score=None：平均分只由 done 行的 8 分构成，不受影响。"""
        body = seeded_env.get("/stats/dashboard").json()
        today = body["today"]
        assert today["avg_score"] == pytest.approx(8.0)

    def test_total_cost_rounded(self, seeded_env: TestClient) -> None:
        body = seeded_env.get("/stats/dashboard").json()
        assert body["today"]["total_cost"] == pytest.approx(0.75)


class TestDashboardDaily:
    """近 14 天逐日序列。"""

    def test_daily_has_14_days_ascending(self, seeded_env: TestClient) -> None:
        daily = seeded_env.get("/stats/dashboard").json()["daily"]
        assert len(daily) == 14
        dates = [item["date"] for item in daily]
        assert dates == sorted(dates)

    def test_daily_today_has_data(self, seeded_env: TestClient) -> None:
        body = seeded_env.get("/stats/dashboard").json()
        today_entry = body["daily"][-1]  # 升序，最后一天是今天
        assert today_entry["count"] >= 2
        assert today_entry["done_count"] >= 1
        assert today_entry["avg_score"] == pytest.approx(8.0)

    def test_daily_zero_fill(self, seeded_env: TestClient) -> None:
        """无数据日必须补零而不是缺条目。"""
        body = seeded_env.get("/stats/dashboard").json()
        daily = body["daily"]
        empty_days = [item for item in daily if item["count"] == 0]
        assert empty_days, "测试库只有今天的任务，前 13 天应全部为空"
        for item in empty_days:
            assert item["count"] == 0
            assert item["done_count"] == 0
            assert item["cost"] == 0.0
            assert item["avg_score"] is None
        # 今天在末尾，倒数第二天无数据（窗口内造数都在今天）
        assert daily[-2]["count"] == 0


class TestDashboardSystem:
    """system 字段与既有健康检查 / 计费口径一致。"""

    def test_system_fields(self, seeded_env: TestClient) -> None:
        body = seeded_env.get("/stats/dashboard").json()
        system = body["system"]
        assert system["peak_pricing"] is is_peak()
        assert system["price_multiplier"] == pytest.approx(price_multiplier())
        assert system["next_off_peak"]  # 非空 ISO 字符串
        assert system["llm_configured"] is False  # conftest 把 LLM_API_KEY 清空
        assert system["cache_backend"] == "memory"  # Redis 指向不可达端口 → 内存降级
        assert system["db_ok"] is True

    def test_generated_at_is_cn_time(self, seeded_env: TestClient) -> None:
        body = seeded_env.get("/stats/dashboard").json()
        assert body["generated_at"].endswith("+08:00")


# --------------------------------------------------------------------------- #
# /console：整条路由已摘除（2026-09-27 删 ``web/`` 与静态托管；2026-09-25 先摘了鉴权豁免）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def auth_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[TestClient]:
    """开启 API_AUTH_TOKEN 的档位：数据接口与 /console 一族都要 Bearer。"""
    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_TOKEN", "stats-token-123")
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client
    reset_settings_cache()


#: 摘托管前真实存在过的路径（HTML + 两份子资源）+ 目录形式，一条都不许还能拿到。
CONSOLE_PATHS = (
    "/console",
    "/console/",
    "/console/index.html",
    "/console/app.js",
    "/console/style.css",
)


class TestConsoleRouteGone:
    """``/console`` 不再是"能拿到 HTML 的路径"。原来这里两条断 200，现在改口断 404。

    拆成三条是因为"404"有好几种假绿法，一条判据挡不住：

    * 只测 ``/console`` 一个路径 ⇒ "挂载还在、只是目录被删空了"同样是 404，
      子资源那一族没测到；
    * 只测状态码 ⇒ 哪天冒出个 catch-all 兜底路由返回目录页，状态码会变了但没人看内容；
      所以第二条钉"404 必须是路由未命中的 JSON 错误体"；
    * 只测行为 ⇒ "路由注册表里到底还有没有 /console"没人管（``app.mount`` 残留而目录
      已删，表现也是 404，但下一个人会以为它还能用）。第三条直接读 ``app.routes``。
    """

    def test_console_paths_all_404(self, api_env: TestClient) -> None:
        for path in CONSOLE_PATHS:
            response = api_env.get(path)
            assert response.status_code == 404, (
                f"{path} 返回 {response.status_code} ⇒ 静态托管没摘干净"
            )

    def test_404_is_the_json_error_envelope(self, api_env: TestClient) -> None:
        """404 出自路由未命中，不是某个兜底 HTML 页换了状态码。"""
        response = api_env.get("/console")
        assert "application/json" in response.headers["content-type"]
        assert response.json()["detail"]["code"] == "not_found"

    def test_no_console_route_is_registered(self, api_env: TestClient) -> None:
        app = api_env.app  # type: ignore[attr-defined]
        registered = [str(getattr(route, "path", "")) for route in app.routes]
        leftovers = [p for p in registered if p == "/console" or p.startswith("/console/")]
        assert leftovers == [], f"路由表里还剩 {leftovers} ⇒ mount 或它的名字还在"


class TestConsoleRequiresAuth:
    """启用鉴权后 ``/console`` 一族的口径（前两条是**实测**，别按直觉改）：

    * 不带 token ⇒ **401**（不是 404）：鉴权中间件在最外层、跑在路由匹配之前，
      "这条路径存不存在"轮不到回答 —— 所以它**不能**被当成"路由还在"的证据；
    * 带 token ⇒ **404**：过了鉴权也确实拿不到东西，托管与目录一起没了。

    两条合起来钉的是"摘除没有顺手打开一扇新门"：既没把 /console 变成免鉴权可达，
    也没让 401 退化成 200。
    """

    def test_console_html_requires_token(self, auth_env: TestClient) -> None:
        response = auth_env.get("/console")
        assert response.status_code == 401, "这里应当是中间件先拦，不是路由先答"
        # RFC 6750：401 必须带 WWW-Authenticate，否则客户端没有"该带什么"的口径
        assert response.headers.get("www-authenticate", "").lower().startswith("bearer")

    def test_console_assets_require_token(self, auth_env: TestClient) -> None:
        """前缀豁免是"整棵树"，所以子资源也必须拦下来（哪怕它已经 404）。"""
        for path in ("/console/index.html", "/console/app.js", "/console/style.css"):
            assert auth_env.get(path).status_code == 401, f"{path} 未被鉴权拦截"

    def test_console_with_token_is_404(self, auth_env: TestClient) -> None:
        response = auth_env.get("/console", headers={"Authorization": "Bearer stats-token-123"})
        assert response.status_code == 404, "带 token 还能拿到 HTML ⇒ 托管没摘干净"

    def test_data_api_requires_token(self, auth_env: TestClient) -> None:
        for path in ("/tasks", "/stats/dashboard"):
            response = auth_env.get(path)
            assert response.status_code == 401, f"{path} 未被鉴权拦截"

    def test_data_api_with_token_ok(self, auth_env: TestClient) -> None:
        headers = {"Authorization": "Bearer stats-token-123"}
        assert auth_env.get("/stats/dashboard", headers=headers).status_code == 200
        assert auth_env.get("/tasks", headers=headers).status_code == 200


class TestAuthExemptList:
    """豁免名单本身的账：只摘了 console，其余一项没动。"""

    def test_console_is_no_longer_exempt(self) -> None:
        from api.constants import AUTH_EXEMPT_PREFIXES, is_auth_exempt

        assert "/console" not in AUTH_EXEMPT_PREFIXES
        for path in ("/console", "/console/", "/console/app.js", "/console/anything/new.js"):
            assert is_auth_exempt(path) is False, f"{path} 仍在免鉴权名单里"

    def test_docs_family_still_exempt(self) -> None:
        """Swagger 那一族必须留着：摘了它 ``/docs`` 打不开，调试入口就没了。"""
        from api.constants import is_auth_exempt

        for path in ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"):
            assert is_auth_exempt(path) is True, f"{path} 不该被摘"
        assert is_auth_exempt("/health") is True

    def test_前缀匹配带边界_b4(self) -> None:
        """B-4：旧实现是 ``path.startswith(prefixes)``，那是**子串**匹配不是前缀匹配。

        ``/docsx`` 命中 ``/docs`` ⇒ 免鉴权。今天没有以它开头的路由（属埋雷未爆），
        但豁免名单就是"多一个字符少一道门"的地方 —— ``/console`` 在这里出过一次事。
        """
        from api.constants import is_auth_exempt

        for path in (
            "/docsx",
            "/docsx/anything",
            "/redocx",
            "/openapi.json.evil",
            "/openapi.jsonp",
            "/healthz",
            "/documentation",
        ):
            assert is_auth_exempt(path) is False, f"{path} 被当成免鉴权了"

        # 真正的子资源路径仍然要放行，别把门禁修成把门焊死。
        for path in ("/docs", "/docs/", "/docs/swagger-ui.css", "/redoc", "/redoc/bundle.js"):
            assert is_auth_exempt(path) is True, f"{path} 该放行"
