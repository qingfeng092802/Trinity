"""给录屏采集播种知识库：把 ``data/demo_docs/`` 里**真能进库的三篇**示例文档传到正在跑的后端，并等索引到 ready。

为什么单独一个脚本而不是让录屏脚本自己传：GIF 里知识库那一屏要拍到"文档表 + chunk 读数"，
而索引是异步状态机（``pending → parsing → chunking → embedding → ready``，见 ``api/constants.py``
的 ``DOC_STAGE_FLOW``）。播种与录制分开，录屏脚本就只负责"看"，不会把等待时间拍进动画里。

⚠️ 后端必须起在**隔离的运行目录**上（临时 DB + 临时知识库），别把演示数据写进 ``data/``：

```bash
DB_URL="sqlite:///$TMP/trinity_demo/demo_tasks.db" \\
KNOWLEDGE_DIR="$TMP/trinity_demo/kb" WORKSPACE_DIR="$TMP/trinity_demo/workspace" \\
LOG_DIR="$TMP/trinity_demo/logs" \\
  python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

用法（仓库根，后端已在 :8001）：

```bash
python web-react/tools/uicheck/demo_kb_seed.py
```
"""
from __future__ import annotations

import pathlib
import sys
import time

import httpx

BASE = "http://127.0.0.1:8001"
ROOT = pathlib.Path(__file__).resolve().parents[3]
DEMO_DOCS = ROOT / "data" / "demo_docs"

#: 知识库**当前只收 md / pdf / txt**（唯一来源 ``api.constants.DOC_SUPPORTED_FORMATS``，
#: 2026-09-21 那次收敛把 docx/html 摘了，见 ``rag/parsers.py`` 的模块注释；csv 从来不在名单里）。
#: ``data/demo_docs/`` 里的 ``04_*.csv`` / ``04_*.html`` 是 P5 数据报告的样本，不是可上传素材 ——
#: 传上去会得到 422 ``unsupported_format``，所以这里刻意只取三篇真能进库的。
WANT = ("01_员工手册.md", "02_财务报销制度.txt", "03_考勤管理制度.txt")

TERMINAL = {"ready", "failed"}


def seed(client: httpx.Client) -> list[str]:
    """传三篇；**同名已存在就复用**（409 是这个端点的正常返回，不是失败）。

    为什么要容 409：录屏可能要重拍几遍，而知识库里留着上一遍的文档才是常态。
    重拍时把旧文档删掉重传会让 chunk 数与 token 数抖动，动画里的读数就对不上文案了。
    """
    ids: list[str] = []
    existing = {i["filename"]: i["document_id"] for i in client.get("/knowledge/documents").json()["items"]}
    for name in WANT:
        path = DEMO_DOCS / name
        if not path.is_file():
            raise SystemExit(f"缺示例文档：{path}")
        response = client.post(
            "/knowledge/documents",
            files={"file": (name, path.read_bytes(), "text/plain")},
        )
        if response.status_code == 409:
            doc_id = existing.get(name)
            print(f"  复用 {name} -> {doc_id} (已存在)")
            ids.append(str(doc_id))
            continue
        if response.status_code != 201:
            raise SystemExit(f"上传失败 {name}: {response.status_code} {response.text[:160]}")
        body = response.json()
        ids.append(str(body["document_id"]))
        print(f"  上传 {name} -> {body['document_id']} ({body['status']})")
    return [i for i in ids if i and i != "None"]


def wait_ready(client: httpx.Client, ids: list[str], seconds: float = 90.0) -> list[dict]:
    deadline = time.monotonic() + seconds
    items: list[dict] = []
    while time.monotonic() < deadline:
        time.sleep(1.0)
        body = client.get("/knowledge/documents").json()
        items = [i for i in body.get("items", []) if i.get("document_id") in ids]
        states = [(i["filename"], i["status"]) for i in items]
        if len(items) == len(ids) and all(s == "ready" for _, s in states):
            return items
        if any(s == "failed" for _, s in states):
            for i in items:
                if i["status"] == "failed":
                    print(f"  索引失败 {i['filename']}: {i.get('error_stage')} {i.get('error_message')}")
            raise SystemExit(1)
    print(f"  等待超时，末态：{[(i['filename'], i['status']) for i in items]}")
    raise SystemExit(1)


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        if client.get("/health").status_code != 200:
            raise SystemExit(":8001 上没有后端，先把隔离实例起起来（见模块 docstring）")
        print(f"上传示例文档（{len(WANT)} 篇）：")
        ids = seed(client)
        print("等索引状态机走完（最长 90 s）：")
        items = wait_ready(client, ids)
        total_chunks = sum(int(i.get("chunk_count") or 0) for i in items)
        for i in items:
            print(
                f"  ready {i['filename']:<28} format={i['format']:<4} "
                f"chunks={i['chunk_count']:<4} tokens={i['token_count']}"
            )
        print(f"合计 chunk = {total_chunks}（文档数 = {len(items)}）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
