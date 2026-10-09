"""``GET /tasks`` 集成测试：分页、状态过滤、排序与内存态合并。

全部走 ``tests/integration/conftest.py`` 的 Mock 夹具，零真实 LLM 调用。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.integration.conftest import poll_terminal, wait_running


def _submit(client: TestClient, text: str) -> dict[str, Any]:
    """提交一条任务并返回 201 响应体（断言受理成功）。"""
    response = client.post("/tasks", json={"task": text})
    assert response.status_code == 201, response.text
    return response.json()


class TestTaskListBasics:
    """列表结构与分页。"""

    def test_empty_list(self, api_env: TestClient) -> None:
        """空库返回全零结构，不报错。"""
        body = api_env.get("/tasks").json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_pagination_and_total(self, api_env: TestClient) -> None:
        """total 是过滤后的总数；两页元素不相交。"""
        ids = [_submit(api_env, f"任务 {index}")["task_id"] for index in range(3)]
        for task_id in ids:
            poll_terminal(api_env, task_id)

        page1 = api_env.get("/tasks", params={"limit": 2, "offset": 0}).json()
        assert page1["total"] == 3
        assert len(page1["items"]) == 2
        assert page1["limit"] == 2
        assert page1["offset"] == 0

        page2 = api_env.get("/tasks", params={"limit": 2, "offset": 2}).json()
        assert page2["total"] == 3
        assert len(page2["items"]) == 1

        ids_page1 = {item["task_id"] for item in page1["items"]}
        ids_page2 = {item["task_id"] for item in page2["items"]}
        assert ids_page1.isdisjoint(ids_page2)
        assert ids_page1 | ids_page2 == set(ids)

    def test_limit_upper_bound_200(self, api_env: TestClient) -> None:
        """limit > 200 落到 422（FastAPI Query 约束）。"""
        response = api_env.get("/tasks", params={"limit": 201})
        assert response.status_code == 422

    def test_limit_below_one_rejected(self, api_env: TestClient) -> None:
        response = api_env.get("/tasks", params={"limit": 0})
        assert response.status_code == 422


class TestTaskListFilter:
    """status 过滤（单值 / 多值 / 非法值）。"""

    def test_filter_done(self, api_env: TestClient) -> None:
        # 先等两个任务都跑到终态，再断言 done 列表（提交是异步受理，直接查会有竞态）
        for goal in ("过滤测试 A", "过滤测试 B"):
            poll_terminal(api_env, _submit(api_env, goal)["task_id"])
        response = api_env.get("/tasks", params={"status": "done"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert all(item["status"] == "done" for item in body["items"])

    def test_filter_multi_value(self, api_env: TestClient) -> None:
        """多值过滤：running,queued 命中的全部是活动态。"""
        _submit(api_env, "多值过滤测试")
        response = api_env.get("/tasks", params={"status": "done,failed,canceled,aborted"})
        assert response.status_code == 200
        body = response.json()
        assert all(item["status"] in {"done", "failed", "canceled", "aborted"} for item in body["items"])

    def test_invalid_status_422(self, api_env: TestClient) -> None:
        response = api_env.get("/tasks", params={"status": "runningn,done"})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_request"

    def test_filter_no_match(self, api_env: TestClient) -> None:
        body = api_env.get("/tasks", params={"status": "queued"}).json()
        assert body["items"] == []
        assert body["total"] == 0


class TestTaskListOrdering:
    """按 updated_at 倒序。"""

    def test_updated_at_desc(self, api_env: TestClient) -> None:
        for index in range(3):
            task_id = _submit(api_env, f"排序测试 {index}")["task_id"]
            poll_terminal(api_env, task_id)
            time.sleep(0.01)
        body = api_env.get("/tasks", params={"limit": 10}).json()
        updated = [item["updated_at"] for item in body["items"]]
        assert updated == sorted(updated, reverse=True)


class TestTaskListMemoryMerge:
    """运行中 / 排队中的实时视图来自队列内存态。"""

    def test_running_view_has_progress(self, api_env: TestClient) -> None:
        """「慢」前缀触发 Mock LLM 的 0.6s 停顿，足够观察到 running。"""
        submitted = _submit(api_env, "慢：列表合并测试，观察运行中的实时视图")
        task_id = submitted["task_id"]
        wait_running(api_env, task_id)

        body = api_env.get("/tasks", params={"status": "running"}).json()
        matched = [item for item in body["items"] if item["task_id"] == task_id]
        assert matched, f"运行中任务未出现在列表：{body}"
        view = matched[0]
        assert view["status"] == "running"
        assert view["progress"] is not None
        assert view["progress"]["elapsed_ms"] >= 0
        assert view["queue"]["position"] == 0

        # 收尾：取消它，避免泄漏到下一个用例
        cancel = api_env.post(f"/tasks/{task_id}/cancel")
        assert cancel.status_code == 200
        poll_terminal(api_env, task_id)

    def test_terminal_view_progress_is_null(self, api_env: TestClient) -> None:
        """终态任务的 progress 必须为 null、queue.position 为 0。"""
        task_id = _submit(api_env, "终态视图测试")["task_id"]
        terminal = poll_terminal(api_env, task_id)
        assert terminal["status"] in {"done", "failed", "aborted", "canceled"}
        body = api_env.get("/tasks", params={"status": terminal["status"]}).json()
        view = next(item for item in body["items"] if item["task_id"] == task_id)
        assert view["progress"] is None
        assert view["queue"]["position"] == 0
