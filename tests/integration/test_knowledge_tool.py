"""knowledge_search 工具集成测试（T04）：注册与注入 / 调用 / 失败语义 / trace 落库（A3）。

零真实模型与零真实 token：``RAG_FAKE_EMBEDDER=1``（MockEmbedder）+ 真
sqlite-vec + 真 jieba/BM25；LLM 走脚本化 ``MockLLMAdapter``（executor 决策
直接指定 ``tool_name="knowledge_search"``，走 ``build_runner`` 真实装配路径）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import reset_settings_cache  # noqa: E402
from core.agent.planner import PLAN_SCHEMA  # noqa: E402
from core.tools.builtin import load_builtin_tools, knowledge_search  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402
from core.workflow.state import ExecutorDecision, ReviewVerdict  # noqa: E402
from tests.integration.conftest import (  # noqa: E402
    Recorder,
    _apply_api_env,
    _start_client,
    poll_terminal,
)
from tests.integration.mock_llm import MockLLMAdapter  # noqa: E402

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# 夹具与语料
# --------------------------------------------------------------------------- #
def _rag_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, **overrides: str) -> None:
    """知识库 + API 测试环境：临时库 + Mock embedder + 真 sqlite-vec。"""
    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("EMBEDDING_DIM", "8")
    monkeypatch.setenv("RAG_FAKE_EMBEDDER", "1")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "sqlite-vec")
    monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path / "fe_cache"))
    monkeypatch.setenv("LLM_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("KNOWLEDGE_MAX_FILE_MB", "1")
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def rag_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    """知识库测试客户端；前后清理模块级服务注入，防止跨测试串号。"""
    _rag_env(monkeypatch, tmp_path)
    knowledge_search.set_knowledge_service(None)
    recorder = Recorder()
    try:
        with _start_client(monkeypatch, recorder) as client:
            client._m1_recorder = recorder  # type: ignore[attr-defined]
            yield client  # type: ignore[misc]
    finally:
        knowledge_search.set_knowledge_service(None)
        reset_settings_cache()


_MD = (
    "# 综合布线系统\n\n综合布线支持语音数据图像业务。\n\n"
    "## 六类线施工\n\n六类线弯曲半径不小于线缆外径 4 倍。\n"
)


def upload_and_wait_ready(client: TestClient, filename: str, data: bytes) -> dict:
    response = client.post(
        "/knowledge/documents", files={"file": (filename, data)}
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["document_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/knowledge/documents/{document_id}").json()
        if body.get("status") == "ready":
            return body
        time.sleep(0.1)
    raise AssertionError(f"文档未 ready：{body}")


# --------------------------------------------------------------------------- #
# 工具注册 / 注入 / 调用
# --------------------------------------------------------------------------- #
def test_knowledge_search_registered_by_default() -> None:
    """第 6 个内置工具：BUILTIN_REGISTRARS 默认注册，无需任何注入即可拿到 spec。"""
    registry = load_builtin_tools(ToolRegistry())
    spec = registry.get("knowledge_search")
    assert spec.danger_level == "low"
    assert spec.timeout == 10
    assert spec.retry == 1
    # Schema 由 Annotated 自动生成
    props = spec.parameters["properties"]
    assert props["query"]["type"] == "string"
    assert props["top_k"]["type"] == "integer"
    assert props["top_k"]["minimum"] == 1 and props["top_k"]["maximum"] == 20
    assert props["top_k"].get("default") == 5


def test_invoke_after_upload_returns_citation(rag_env: TestClient) -> None:
    """验收：上传 → ready → 工具调用 200 success，result 含来源引用与相关度。"""
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    response = rag_env.post(
        "/tools/knowledge_search/invoke",
        json={"args": {"query": "综合布线系统", "top_k": 3}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success", body["result"]
    result = body["result"]
    assert "共命中" in result
    assert "buxian.md" in result, f"来源引用缺失：{result}"
    assert "chunk" in result
    assert "相关度" in result
    assert body["duration_ms"] >= 0


def test_invoke_empty_kb_returns_failed_with_clear_reason(rag_env: TestClient) -> None:
    """验收：空库调用 → HTTP 200 但 status='failed'，原因明确（executor 拿到不崩）。"""
    response = rag_env.post(
        "/tools/knowledge_search/invoke",
        json={"args": {"query": "门禁系统两种联网方式"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert "知识库为空" in body["result"]


def test_tool_without_service_injection_fails_clearly() -> None:
    """未注入服务（等价 rag 依赖缺失）→ 结构化失败字符串，不抛异常穿透。"""
    knowledge_search.set_knowledge_service(None)
    try:
        registry = load_builtin_tools(ToolRegistry())
        record = registry.call("knowledge_search", {"query": "综合布线"})
        assert record["status"] == "failed"
        assert "知识库服务不可用" in record["result"]
        assert record["duration_ms"] >= 0
    finally:
        knowledge_search.set_knowledge_service(None)


def test_invalid_query_and_top_k_failed(rag_env: TestClient) -> None:
    """空 query / 超 1000 字符 / top_k 越界 → 全部 status='failed'，不抛异常。"""
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    cases = [
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "综合布线", "top_k": 0},
        {"query": "综合布线", "top_k": 21},
    ]
    for args in cases:
        response = rag_env.post(
            "/tools/knowledge_search/invoke", json={"args": args}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "failed", f"args={args} 应失败：{body}"
        # 业务校验（query 空/超长）报「检索失败」；pydantic 校验（top_k 越界）报「参数校验失败」
        assert "检索失败" in body["result"] or "参数校验失败" in body["result"]


# --------------------------------------------------------------------------- #
# Mock LLM 任务级 trace 验收（A3）
# --------------------------------------------------------------------------- #
def _make_scripted_factory(recorder: Recorder, tool_query: str | None):
    """脚本化 runner 工厂：第 1 步 executor 决策调 knowledge_search（tool_query 非空时）。"""

    def factory(item: Any) -> Any:
        from api.deps import get_trace_store
        from api.runner import build_runner
        from config import get_settings

        counters = {"executor": 0}

        def responder(schema: Any, _text: str) -> Any:
            recorder.record(item.task_id)
            if schema is PLAN_SCHEMA:
                return ["检索知识库", "形成结论"]
            if schema is ExecutorDecision:
                counters["executor"] += 1
                if counters["executor"] == 1 and tool_query:
                    return {
                        "thought": "查知识库",
                        "tool_name": "knowledge_search",
                        "tool_args": {"query": tool_query, "top_k": 3},
                        "answer": "",
                    }
                return {
                    "thought": "汇总",
                    "tool_name": None,
                    "tool_args": {},
                    "answer": "本步结论",
                }
            if schema is ReviewVerdict:
                return {
                    "pass": True,
                    "score": 9,
                    "comment": "结构完整",
                    "final_answer": "这是 Mock 生成的最终答案。",
                }
            raise AssertionError(f"未预期的 schema：{schema}")

        return build_runner(
            item,
            settings=get_settings(),
            trace_store=get_trace_store(),
            llm=MockLLMAdapter(responder),
        )

    return factory


def _script_factory(monkeypatch: pytest.MonkeyPatch, tool_query: str | None) -> Recorder:
    """把**存活队列实例**上的 runner 工厂换成脚本化版本。

    关键：``get_task_queue()`` 是 lifespan 期间创建的 lru_cache 单例，创建时已把
    录制工厂捕获为 ``queue.factory``——只替换 ``deps.default_runner_factory``
    并清缓存影响不到已存在的队列，必须直接替换实例属性（monkeypatch 保证还原）。
    """
    recorder = Recorder()
    import api.deps as deps_mod

    queue = deps_mod.get_task_queue()
    monkeypatch.setattr(
        queue._worker,  # noqa: SLF001 - 测试需要替换存活 worker 的工厂，task worker 内部持有
        "factory",
        lambda item: _make_scripted_factory(recorder, tool_query)(item),
    )
    return recorder


def _trace_tool_calls(client: TestClient, task_id: str) -> list[dict[str, Any]]:
    from api.deps import get_trace_store

    calls: list[dict[str, Any]] = []
    for record in get_trace_store().for_task(task_id):
        calls.extend(record.tool_calls)
    return calls


def test_trace_records_knowledge_search_call(
    rag_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 A3：任务执行中调用 knowledge_search → trace 记录含 query/top_k/命中/来源/耗时。"""
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    _script_factory(monkeypatch, tool_query="六类线施工规范")
    submit = rag_env.post(
        "/tasks",
        json={"task": "根据知识库说明六类线施工规范", "use_tools": True},
    )
    assert submit.status_code == 201, submit.text
    task_id = submit.json()["task_id"]
    final = poll_terminal(rag_env, task_id)
    assert final["status"] == "done", final

    calls = _trace_tool_calls(rag_env, task_id)
    ks_calls = [call for call in calls if call["name"] == "knowledge_search"]
    assert ks_calls, "trace 中必须有 knowledge_search 调用记录"
    call = ks_calls[0]
    assert call["args"]["query"] == "六类线施工规范"
    assert call["args"]["top_k"] == 3
    assert call["status"] == "success"
    assert call["duration_ms"] >= 0
    assert "相关度" in call["result"] and "chunk" in call["result"]
    assert "buxian.md" in call["result"]


def test_trace_has_no_knowledge_search_for_plain_task(
    rag_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 A3 反向：「1+1 等于几」类纯推理任务 → trace 无 knowledge_search 调用。"""
    _script_factory(monkeypatch, tool_query=None)
    submit = rag_env.post(
        "/tasks", json={"task": "1+1 等于几", "use_tools": True}
    )
    assert submit.status_code == 201, submit.text
    task_id = submit.json()["task_id"]
    final = poll_terminal(rag_env, task_id)
    assert final["status"] == "done", final

    calls = _trace_tool_calls(rag_env, task_id)
    assert not [call for call in calls if call["name"] == "knowledge_search"]


# --------------------------------------------------------------------------- #
# 提示词增量（§3.4 逐字落盘校验）
# --------------------------------------------------------------------------- #
def test_prompts_contain_knowledge_search_rules() -> None:
    prompts_dir = PROJECT_ROOT / "core" / "llm" / "prompts" / "v1"
    planner = (prompts_dir / "planner.md").read_text(encoding="utf-8")
    executor = (prompts_dir / "executor.md").read_text(encoding="utf-8")
    assert "用 knowledge_search 检索知识库获取〈X〉" in planner
    assert "不要硬塞检索步骤" in planner
    assert "引用 knowledge_search 的结果时" in executor
    assert "检索失败时说明原因并继续可完成的步骤" in executor
