"""知识库 API 集成测试（T03）：上传三格式（pdf/md/txt）/ 失败隔离 / 409/422 / 检索 / 指纹闸 /
health 特判 / KB-01 删除与覆盖连带删磁盘原件。

零真实模型：``RAG_FAKE_EMBEDDER=1``（MockEmbedder，确定性哈希向量）+ 真
sqlite-vec + 真 jieba/BM25——整条 API→service→worker→store 链路都走真实现，
只有向量化是桩（设计 D6 测试资源纪律）。
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
from tests.integration.conftest import (  # noqa: E402
    Recorder,
    _apply_api_env,
    _start_client,
)
from tests.unit._rag_fixtures import build_text_pdf  # noqa: E402

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# 夹具与工具
# --------------------------------------------------------------------------- #
def _rag_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, **overrides: str) -> None:
    """知识库测试环境：临时库 + Mock embedder + 真 sqlite-vec。"""
    _apply_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("EMBEDDING_DIM", "8")
    monkeypatch.setenv("RAG_FAKE_EMBEDDER", "1")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "sqlite-vec")
    monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path / "fe_cache"))
    # llm 探活用假 Key 保持 ok（隔离变量：health 只由 rag/redis 驱动）
    monkeypatch.setenv("LLM_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("KNOWLEDGE_MAX_FILE_MB", "1")
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def rag_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    """知识库测试客户端（lifespan 起 IndexWorker，退出停 worker 与队列）。"""
    _rag_env(monkeypatch, tmp_path)
    recorder = Recorder()
    with _start_client(monkeypatch, recorder) as client:
        client._m1_recorder = recorder  # type: ignore[attr-defined]
        yield client  # type: ignore[misc]
    reset_settings_cache()


def upload(client: TestClient, filename: str, data: bytes, *, overwrite: bool = False):
    return client.post(
        f"/knowledge/documents?overwrite={str(overwrite).lower()}",
        files={"file": (filename, data)},
    )


def poll_document(client: TestClient, document_id: str, statuses: set[str], timeout: float = 30.0) -> dict:
    """轮询文档直到进入期望状态（索引是后台线程，毫秒级完成）。"""
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        response = client.get(f"/knowledge/documents/{document_id}")
        body = response.json()
        if response.status_code == 200 and body.get("status") in statuses:
            return body
        time.sleep(0.1)
    raise AssertionError(f"文档 {document_id} 在 {timeout}s 内未到 {statuses}：{body}")


def upload_and_wait_ready(client: TestClient, filename: str, data: bytes) -> dict:
    response = upload(client, filename, data)
    assert response.status_code == 201, response.text
    return poll_document(client, response.json()["document_id"], {"ready"})


def _blank_pdf_bytes(pages: int = 1) -> bytes:
    """无文本层的 PDF（扫描件模拟）：只有空白 content stream。"""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Length 10 >>\nstream\nBT ET end\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


_MD = (
    "# 综合布线系统\n\n综合布线支持语音数据图像业务。\n\n"
    "## 六类线施工\n\n六类线弯曲半径不小于线缆外径 4 倍。\n"
)
_TXT = "安防监控点位应覆盖出入口与大堂。\n\n存储时长不低于 90 天。\n"


# --------------------------------------------------------------------------- #
# 上传与索引
# --------------------------------------------------------------------------- #
def test_upload_three_formats_and_ready(rag_env: TestClient, tmp_path: Any) -> None:
    """白名单收敛后只保证 pdf / md / txt 三种格式上传→解析→索引→ready 全通。"""
    cases = [
        ("buxian.md", _MD.encode("utf-8")),
        ("anfang.txt", _TXT.encode("utf-8")),
        ("sample.pdf", _pdf_bytes(tmp_path)),
    ]
    for filename, data in cases:
        body = upload_and_wait_ready(rag_env, filename, data)
        assert body["status"] == "ready", f"{filename} 未 ready：{body}"
        assert body["chunk_count"] >= 1
        assert body["embedding_fingerprint"]


def _pdf_tmp(tmp_path: Any) -> Path:
    return tmp_path / "gen.pdf"


def _pdf_bytes(tmp_path: Any) -> bytes:
    path = _pdf_tmp(tmp_path)
    build_text_pdf(path, pages=2)
    return path.read_bytes()


def test_duplicate_filename_409_then_overwrite(rag_env: TestClient) -> None:
    first = upload_and_wait_ready(rag_env, "doc.md", _MD.encode("utf-8"))
    conflict = upload(rag_env, "doc.md", _MD.encode("utf-8"))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "duplicate_document"

    overwritten = upload(rag_env, "doc.md", _MD.encode("utf-8"), overwrite=True)
    assert overwritten.status_code == 201
    warnings = overwritten.json()["warnings"]
    assert warnings and "overwrite" in warnings[0]
    new_id = overwritten.json()["document_id"]
    assert new_id != first["document_id"]
    body = poll_document(rag_env, new_id, {"ready"})
    # 旧记录已被清除：列表里只有一份 doc.md
    listing = rag_env.get("/knowledge/documents").json()
    names = [item["filename"] for item in listing["items"]]
    assert names.count("doc.md") == 1
    assert listing["total"] == 1


def test_corrupt_pdf_failed_isolation(rag_env: TestClient) -> None:
    good = upload_and_wait_ready(rag_env, "good.md", _MD.encode("utf-8"))
    bad_response = upload(rag_env, "corrupt.pdf", b"%PDF-1.4 broken content")
    assert bad_response.status_code == 201
    bad = poll_document(rag_env, bad_response.json()["document_id"], {"failed"})
    assert bad["error_stage"] == "parsing"
    assert bad["error_message"]
    # 失败隔离：好文档不受影响
    assert rag_env.get(f"/knowledge/documents/{good['document_id']}").json()["status"] == "ready"


def test_scan_like_pdf_reports_missing_text_layer(rag_env: TestClient) -> None:
    response = upload(rag_env, "scan.pdf", _blank_pdf_bytes())
    assert response.status_code == 201
    body = poll_document(rag_env, response.json()["document_id"], {"failed"})
    assert body["error_stage"] == "parsing"
    assert "文本层缺失" in body["error_message"]


def test_unsupported_format_422(rag_env: TestClient) -> None:
    response = upload(rag_env, "evil.xyz", b"whatever")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_format"


def test_file_too_large_422(rag_env: TestClient) -> None:
    big = b"x" * (1 * 1024 * 1024 + 1)  # 配置下限 1MB，多 1 字节即超限
    response = upload(rag_env, "big.txt", big)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "file_too_large"


def test_empty_file_422(rag_env: TestClient) -> None:
    response = upload(rag_env, "empty.txt", b"")
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# CRUD 与重试
# --------------------------------------------------------------------------- #
def test_get_document_404(rag_env: TestClient) -> None:
    response = rag_env.get("/knowledge/documents/doc-nonexistent")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"


def test_list_documents(rag_env: TestClient) -> None:
    upload_and_wait_ready(rag_env, "a.md", _MD.encode("utf-8"))
    upload_and_wait_ready(rag_env, "b.txt", _TXT.encode("utf-8"))
    listing = rag_env.get("/knowledge/documents").json()
    assert listing["total"] == 2
    assert {item["filename"] for item in listing["items"]} == {"a.md", "b.txt"}


def test_delete_document(rag_env: TestClient) -> None:
    body = upload_and_wait_ready(rag_env, "del.md", _MD.encode("utf-8"))
    document_id = body["document_id"]
    response = rag_env.delete(f"/knowledge/documents/{document_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert rag_env.get(f"/knowledge/documents/{document_id}").status_code == 404
    # 概览应归零
    overview = rag_env.get("/knowledge/overview").json()
    assert overview["document_count"] == 0
    assert overview["chunk_count"] == 0


# --------------------------------------------------------------------------- #
# KB-01：删除 / 覆盖必须连带删磁盘原件
#
# 为什么单独钉：这条缺陷的症状是"不报错只留垃圾"——库里少一行、磁盘多一个孤儿，
# 界面上完全看不出来。实测过现网账不平（files/ 7 个文件 vs documents 4 行，
# 三个 fmt_smoke 孤儿的 id 在库里查不到），所以判据要看**磁盘**，不能只看接口返回。
# --------------------------------------------------------------------------- #
def _files_dir(tmp_path: Any) -> Path:
    return Path(tmp_path) / "knowledge" / "files"


def test_delete_document_removes_original_file(rag_env: TestClient, tmp_path: Any) -> None:
    body = upload_and_wait_ready(rag_env, "kb01.md", _MD.encode("utf-8"))
    document_id = body["document_id"]
    files = _files_dir(tmp_path)
    originals = [p for p in files.iterdir() if p.name.startswith(f"{document_id}_")]
    assert len(originals) == 1, f"上传后磁盘上应有该文档的原件，实际：{[p.name for p in files.iterdir()]}"

    assert rag_env.delete(f"/knowledge/documents/{document_id}").status_code == 200

    left = [p.name for p in files.iterdir()] if files.exists() else []
    assert not any(name.startswith(f"{document_id}_") for name in left), f"记录已删但原件还在（KB-01 复发）：{left}"


def test_overwrite_removes_old_original_file(rag_env: TestClient, tmp_path: Any) -> None:
    """覆盖重建会换 document_id ⇒ 旧原件必须跟着旧记录一起走，否则每次覆盖留一个孤儿。"""
    first = upload_and_wait_ready(rag_env, "ov.md", _MD.encode("utf-8"))
    files = _files_dir(tmp_path)
    assert len([p for p in files.iterdir()]) == 1

    second = upload(rag_env, "ov.md", _TXT.encode("utf-8"), overwrite=True)
    assert second.status_code == 201
    new_id = second.json()["document_id"]
    assert new_id != first["document_id"]
    poll_document(rag_env, new_id, {"ready"})

    names = [p.name for p in files.iterdir()]
    assert len(names) == 1, f"覆盖后磁盘上应只剩新原件，实际：{names}"
    assert names[0].startswith(f"{new_id}_")


def test_purge_refuses_to_delete_outside_files_dir(tmp_path: Any) -> None:
    """反向钉那两道校验：路径不在 files/ 下、或前缀对不上 ⇒ **不许删**。

    宁可留孤儿，不可误删：`file_path` 是库里存的字符串，一条被改坏的记录如果指向
    别人的文件（或任意系统路径），删除动作就不能碰它。这里用一枚只带 `settings` 的
    桩对象直接调那枚清理函数，绕开整条 app 链路 —— 要测的是判断分支，不是夹具。
    """
    from types import SimpleNamespace

    from rag.service import KnowledgeService

    class _Stub:
        settings = SimpleNamespace(knowledge_dir=Path(tmp_path) / "knowledge")
        _unlink_original = KnowledgeService._unlink_original

    stub = _Stub()
    victim = Path(tmp_path) / "重要数据.md"  # 故意放在 files/ 之外
    victim.write_text("别删我", encoding="utf-8")

    stub._unlink_original("doc-abc123", SimpleNamespace(file_path=str(victim)))
    assert victim.exists(), "越界路径被删了（前缀/目录两道校验形同虚设）"

    impersonated = _files_dir(tmp_path)
    impersonated.mkdir(parents=True, exist_ok=True)
    other = impersonated / "doc-zzz999_别人的原件.md"
    other.write_text("别删我", encoding="utf-8")
    stub._unlink_original("doc-abc123", SimpleNamespace(file_path=str(other)))
    assert other.exists(), "document_id 前缀不符却删了（会误删同名文档的原件）"

    # 对照：两条校验都过 ⇒ 必须真的删掉（否则 KB-01 的修复是空转）
    mine = impersonated / "doc-abc123_我的.md"
    mine.write_text("删我", encoding="utf-8")
    stub._unlink_original("doc-abc123", SimpleNamespace(file_path=str(mine)))
    assert not mine.exists(), "合法路径没删 —— 修复没生效，测试本身在空转"


def test_retry_failed_document(rag_env: TestClient) -> None:
    response = upload(rag_env, "scan.pdf", _blank_pdf_bytes())
    document_id = response.json()["document_id"]
    poll_document(rag_env, document_id, {"failed"})
    retry = rag_env.post(f"/knowledge/documents/{document_id}/retry")
    assert retry.status_code == 200
    assert retry.json() == {"document_id": document_id, "status": "pending", "queued": True}
    # 重试后仍失败（内容没变），但状态机走通
    body = poll_document(rag_env, document_id, {"failed"})
    assert body["error_stage"] == "parsing"
    # 非 failed 文档重试 → 422
    good = upload_and_wait_ready(rag_env, "ok.md", _MD.encode("utf-8"))
    conflict = rag_env.post(f"/knowledge/documents/{good['document_id']}/retry")
    assert conflict.status_code == 422


# --------------------------------------------------------------------------- #
# 检索
# --------------------------------------------------------------------------- #
def test_search_empty_knowledge_base(rag_env: TestClient) -> None:
    response = rag_env.post("/knowledge/search", json={"query": "六类线弯曲半径"})
    assert response.status_code == 200
    assert response.json()["hits"] == []


def test_search_invalid_query_422(rag_env: TestClient) -> None:
    for payload in ({"query": "   "}, {"query": ""}, {}):
        response = rag_env.post("/knowledge/search", json=payload)
        assert response.status_code == 422, payload


def test_search_returns_hits_with_citation(rag_env: TestClient) -> None:
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    response = rag_env.post("/knowledge/search", json={"query": "六类线弯曲半径要求", "top_k": 3})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["took_ms"] >= 0
    assert 1 <= len(body["hits"]) <= 3
    for hit in body["hits"]:
        # 结构断言（Mock 向量是随机哈希，排序不做语义假设）
        assert hit["document_name"] == "buxian.md"
        assert hit["chunk_seq"] >= 0
        assert hit["text"]
        assert 0.0 <= hit["score"] <= 1.0
        assert 0.0 <= hit["bm25_score"] <= 1.0
        assert 0.0 <= hit["vector_score"] <= 1.0
    # 纯 BM25 路（权重 1/0）应有召回且按 token 匹配排序。
    # 注意：jieba 会把「六类线」切成 ['六类','线']，BM25 是 token 级匹配，
    # 无法保证含完整「六类线」的 chunk 稳定排第一，因此只做 token 级 + 结构断言。
    pure = rag_env.post(
        "/knowledge/search", json={"query": "六类线", "bm25_weight": 1.0, "vector_weight": 0.0}
    )
    assert pure.status_code == 200
    hits = pure.json()["hits"]
    assert hits, "「六类线」拆词后（六类/线）在 BM25 路必须有召回"
    assert any("六类" in hit["text"] for hit in hits), (
        "BM25 召回结果中至少应有一个片段包含 token「六类」"
    )
    for hit in hits:
        assert hit["document_name"] == "buxian.md"
        assert 0.0 <= hit["bm25_score"] <= 1.0
        assert hit["score"] == pytest.approx(hit["bm25_score"], abs=1e-6)


def test_search_weights_route_must_differ(rag_env: TestClient) -> None:
    """权重数学验证：(1,0) 时 score ≡ bm25_score；(0,1) 时 score ≡ vector_score。"""
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    pure_bm25 = rag_env.post(
        "/knowledge/search", json={"query": "弯曲半径", "bm25_weight": 1.0, "vector_weight": 0.0}
    )
    pure_vector = rag_env.post(
        "/knowledge/search", json={"query": "弯曲半径", "bm25_weight": 0.0, "vector_weight": 1.0}
    )
    assert pure_bm25.status_code == 200 and pure_vector.status_code == 200
    for hit in pure_bm25.json()["hits"]:
        assert hit["score"] == pytest.approx(hit["bm25_score"], abs=1e-6)
    for hit in pure_vector.json()["hits"]:
        assert hit["score"] == pytest.approx(hit["vector_score"], abs=1e-6)
    # 权重和不等于 1 → 422
    bad = rag_env.post(
        "/knowledge/search", json={"query": "x", "bm25_weight": 0.2, "vector_weight": 0.2}
    )
    assert bad.status_code == 422


def test_fingerprint_mismatch_409(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """换 embedding 模型后检索 → 409 fingerprint_mismatch（Q7 双闸）。"""
    _rag_env(monkeypatch, tmp_path)
    with _start_client(monkeypatch, Recorder()) as client:
        response = upload(client, "buxian.md", _MD.encode("utf-8"))
        poll_document(client, response.json()["document_id"], {"ready"})
        ok = client.post("/knowledge/search", json={"query": "六类线"})
        assert ok.status_code == 200
    # 同一个库（同 tmp_path），换模型名重建服务
    _rag_env(monkeypatch, tmp_path, EMBEDDING_MODEL_NAME="bge-large-zh-v1.5")
    with _start_client(monkeypatch, Recorder()) as client:
        response = client.post("/knowledge/search", json={"query": "六类线"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "fingerprint_mismatch"


def test_overview带上传上限_且值来自配置_k3(rag_env: TestClient) -> None:
    """K3：界面上那句「单文件 ≤ N MB」必须读这个字段，N 不许前端写死。

    ``_rag_env`` 把上限设成 **1 MB**（不是默认的 50），所以断言读回 1 同时证明两件事：
    值真的来自 ``settings.knowledge_max_file_mb``，而且没有人在 schema 或路由里
    顺手写死一个常量 —— 写死 50 的实现在这个环境里会当场翻红。
    """
    body = rag_env.get("/knowledge/overview").json()
    assert body["max_file_mb"] == 1


def test_overview的上限随配置变_k3(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """换一档配置就得换一个数。

    上一条只排掉了"前端写死"，这一条排掉"后端写死"：两档都读同一个字段名，
    只有真跟着配置走才不会说谎。
    """
    _rag_env(monkeypatch, tmp_path, KNOWLEDGE_MAX_FILE_MB="7")
    reset_settings_cache()
    with _start_client(monkeypatch, Recorder()) as client:
        body = client.get("/knowledge/overview").json()
        assert body["max_file_mb"] == 7
    reset_settings_cache()


# --------------------------------------------------------------------------- #
# R-03：上传白名单只有一个来源（2026-09-26 拍板"进 /overview"）
# --------------------------------------------------------------------------- #
def test_overview的白名单等于后端真能解析的那份_r03(rag_env: TestClient) -> None:
    """界面那份清单**必须**与解析层同源，否则就是 R-03 记的那个最坏的中间态。

    第二行才是这场的重点：受理侧的 ``api.constants.DOC_SUPPORTED_FORMATS`` 与
    解析侧的 ``rag.parsers.SUPPORTED_FORMATS`` 必须一致。任何一处单独加回 docx，
    就会出现"界面收 docx、worker 解析器已经删了"——那种文档会被**受理**、
    然后异步索引当场失败（比误拒难查得多）。
    注意这条不是套套逻辑：它比的不是"响应 == 常量"，而是"受理侧 == 解析侧"。

    2026-10-02（Q7-09）之后这两个名字已经是**同一个对象**（解析侧改成 import），
    所以这条对解析侧退化成"值仍然等于受理侧"的一致性读数；真正钉住"不许再抄
    第二份字面量"的是 ``tests/unit/test_rag_parsers.py::test_supported_formats_whitelist``
    里那条 ``is`` 判据。这里保留原断言，是为了让"响应里那份 == 常量"这条契约
    在 API 层也有一处读数。
    """
    from api.constants import DOC_SUPPORTED_FORMATS
    from rag.parsers import SUPPORTED_FORMATS

    body = rag_env.get("/knowledge/overview").json()
    assert body["supported_formats"] == sorted(DOC_SUPPORTED_FORMATS)
    assert set(body["supported_formats"]) == set(SUPPORTED_FORMATS)


def test_白名单只有一份_响应判定与422文案跟着常量变_r03(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """三处消费者（/overview 的字段、422 的判定、422 那句里列的清单）必须一起动。

    把 ``rag.service`` 里那个名字换成四种（多加一个当下不收的 ``docx``），
    三处**同时**跟着变才算同源；哪里写死了清单，哪里就留在这里翻红。
    旧实现里 422 的文案写的是字面量 ``pdf/md/txt``，常量一改它就开始说谎 ——
    这条用例钉的就是那种写法不许回来。
    """
    import rag.service as rag_service

    _rag_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        rag_service, "DOC_SUPPORTED_FORMATS", frozenset({"pdf", "md", "txt", "docx"})
    )
    with _start_client(monkeypatch, Recorder()) as client:
        body = client.get("/knowledge/overview").json()
        assert body["supported_formats"] == ["docx", "md", "pdf", "txt"]
        # ① 判定跟着变：docx 这一趟被**受理**（异步解析会不会成是另一回事，
        #    解析层那份集合由上一条用例负责跟它对齐）
        ack = upload(client, "guocheng.docx", b"%PDF-fake-not-parsed")
        assert ack.status_code == 201, ack.text
        # ② 文案跟着变：拒的时候列出来的就是这四样
        bad = upload(client, "evil.xyz", b"whatever")
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "unsupported_format"
        assert "白名单：docx/md/pdf/txt" in bad.json()["detail"]["message"], bad.text
    reset_settings_cache()


def test_overview(rag_env: TestClient) -> None:
    empty = rag_env.get("/knowledge/overview").json()
    assert empty["document_count"] == 0
    assert empty["vector_backend"] == "sqlite-vec"
    upload_and_wait_ready(rag_env, "buxian.md", _MD.encode("utf-8"))
    overview = rag_env.get("/knowledge/overview").json()
    assert overview["document_count"] == 1
    assert overview["ready_count"] == 1
    assert overview["chunk_count"] >= 1
    assert overview["token_count"] >= 1
    assert overview["fingerprint"]
    assert overview["embedding_model"]


# --------------------------------------------------------------------------- #
# health rag 检查项（fail 只贡献 degraded）
# --------------------------------------------------------------------------- #
def test_health_contains_rag_check(rag_env: TestClient) -> None:
    response = rag_env.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "rag" in body["checks"]
    assert body["checks"]["rag"]["status"] in {"ok", "degraded", "fail"}


def test_health_rag_fail_degrades_not_unhealthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """store 起不来（chroma 未安装）→ rag=fail，但整体必须 degraded + 200。"""
    _rag_env(monkeypatch, tmp_path, VECTOR_STORE_BACKEND="chroma")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-dummy")  # llm 项保持 ok，隔离变量
    with _start_client(monkeypatch, Recorder()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["rag"]["status"] == "fail"
        # 检索端点同步降级为 503 rag_unavailable
        search = client.post("/knowledge/search", json={"query": "六类线"})
        assert search.status_code == 503
        assert search.json()["detail"]["code"] == "rag_unavailable"
