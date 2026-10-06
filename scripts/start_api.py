#!/usr/bin/env python
"""一键启动 REST API：检查环境 → 打印端点 → 拉起 uvicorn。

用 Python 而不是 ``.ps1`` 写入口，因为 Windows PowerShell 5.1 读无 BOM 的脚本会按
ANSI 解码，中文会变乱码。（这里原先写的是"与 ``scripts/start_ui.py`` 保持同一风格"——
那个脚本和它启动的 Streamlit 控制台已在 2026-09-27 删除，风格约束本身不变。）

两个刻意的默认值
----------------

1. **不开 ``--reload``**（设计文档 R15）：reload 会起子进程，于是线程池与
   任务队列出现两份，行为诡异且极难排查。改代码请手动重启。
2. **只绑 ``127.0.0.1``**：M1 没有用户体系，默认不该把端口暴露出去。
   要容器部署请显式 ``--host 0.0.0.0`` 并先设 ``API_AUTH_TOKEN``。

用法::

    .venv\\Scripts\\python.exe scripts\\start_api.py
    .venv\\Scripts\\python.exe scripts\\start_api.py --port 8080
    .venv\\Scripts\\python.exe scripts\\start_api.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="一键启动 Trinity REST API")
    parser.add_argument("--host", default=None, help="监听地址（默认取 API_HOST，即 127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取 API_PORT，即 8000）")
    parser.add_argument("--skip-check", action="store_true", help="跳过启动前的环境自检")
    return parser.parse_args(argv)


def _resolve_python() -> Path:
    """挑一个能用的解释器：优先 .venv，其次当前解释器。

    没有 ``.venv`` 时不硬失败——很多机器用 conda / 系统 Python 也能跑，
    这时继续用 ``sys.executable`` 并提示一句即可。
    """
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.is_file():
        return venv_python
    print("[提示] 没找到 .venv，改用当前解释器：")
    print(f"       {sys.executable}")
    print("       （建议先跑 `uv sync --extra dev` 建独立环境）")
    return Path(sys.executable)


def preflight(python: Path) -> int:
    """启动前检查：依赖与 .env。返回退出码，0 表示可以继续。"""
    if not (PROJECT_ROOT / ".env").is_file():
        print("[警告] 没找到 .env —— 服务能起来，但一调用模型就会失败。")
        print("       修法：复制 .env.example 为 .env 并填入 LLM_API_KEY。")

    probe = subprocess.run(
        [str(python), "-c", "import fastapi, uvicorn"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        print("[错误] 当前解释器缺少 fastapi / uvicorn：")
        print("       跑 `uv sync --extra dev`（或 `uv sync`）后再启动。")
        print(probe.stderr.strip())
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    args = parse_args(argv)
    python = _resolve_python()

    code = preflight(python)
    if code != 0:
        return code

    from config import get_settings

    settings = get_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port

    print("\n=== REST API ===")
    print(f" 地址          http://{host}:{port}")
    print(f" 交互式文档    http://{host}:{port}/docs")
    print(" 端点          POST /tasks · GET /tasks/{id} · GET /tasks/{id}/stream")
    print("               POST /tasks/{id}/cancel · POST /tools/{name}/invoke")
    print("               GET /eval · GET /health")
    print(f" 并发上限      {settings.api_max_concurrent_tasks}（队列容量 {settings.api_queue_max_size}）")
    print(f" 鉴权          {'已开启（API_AUTH_TOKEN）' if settings.api_auth_enabled else '未开启，仅本机可访问'}")
    if not settings.llm_configured:
        print("[警告] LLM_API_KEY 未配置：任务会被受理，但执行时大概率失败。")
    print(" 停止          Ctrl+C\n")

    command = [
        str(python),
        "-m",
        "uvicorn",
        "api.main:app",
        "--host",
        str(host),
        "--port",
        str(port),
    ]
    try:
        return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
