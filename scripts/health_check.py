#!/usr/bin/env python
"""环境自检脚本。

一条命令确认「依赖 / 配置 / 目录 / Redis / LLM」是否就绪，是每个阶段开工前的第一道门禁。

用法::

    python scripts/health_check.py              # 全量自检（真实调用一次 LLM，消耗极少 token）
    python scripts/health_check.py --skip-llm   # 只查本地环境，零 token 消耗
    python scripts/health_check.py --json       # 输出机器可读结果，便于 CI / 脚本消费

退出码：``0`` 表示无 fail（warn 允许）；``1`` 表示存在 fail。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 让 ``python scripts/health_check.py`` 也能 import 到项目根目录下的 config / core
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402  必须在补齐 sys.path 之后导入

OK, WARN, FAIL = "ok", "warn", "fail"
_COLOR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
_RESET = "\033[0m"

#: 本工程声明的最低 Python 版本，需与 pyproject.toml 的 requires-python 保持一致
MIN_PYTHON: tuple[int, int] = (3, 11)

#: 阶段 0 必须可导入的依赖
REQUIRED_PACKAGES: tuple[str, ...] = (
    "pydantic",
    "pydantic_settings",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "tenacity",
    "sqlalchemy",
)

#: 用到才需要、缺失只告警不阻塞的依赖
#: （原先这里还有 ``streamlit`` —— 那套控制台 2026-09-27 整目录删除，探测项跟着摘掉；
#:  ``ui`` extra 也从 pyproject 消失，别再把它加回来）
OPTIONAL_PACKAGES: tuple[str, ...] = ("redis", "tiktoken", "jsonschema")


@dataclass
class Check:
    """单项检查结果。"""

    name: str
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        return self.status == FAIL


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def check_python() -> Check:
    """运行时 Python 版本必须满足 ``MIN_PYTHON``。"""
    current = sys.version_info
    version = f"{current.major}.{current.minor}.{current.micro}"
    required = ".".join(str(part) for part in MIN_PYTHON)
    if tuple(current[:2]) >= MIN_PYTHON:
        return Check("Python 版本", OK, f"{version} ({sys.executable})")
    return Check("Python 版本", FAIL, f"{version} 低于 {required}（{sys.executable}）")


def _module_version(name: str) -> str:
    """读取已安装包版本。

    优先用 importlib.metadata 查询分发元数据（不会触发三方库的弃用告警），
    元数据缺失时退化为读取模块的 ``__version__`` 属性。
    """
    try:
        return importlib.metadata.version(name.replace("_", "-"))
    except importlib.metadata.PackageNotFoundError:
        try:
            module = importlib.import_module(name)
        except ImportError:
            return "?"
        return str(getattr(module, "__version__", "?"))


def check_dependencies() -> Check:
    """检查关键依赖是否已安装，并输出版本号。"""
    versions: dict[str, str] = {}
    missing: list[str] = []
    for name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
            continue
        versions[name] = _module_version(name)

    optional_missing = []
    for name in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(name)
        except ImportError:
            optional_missing.append(name)
            continue
        versions[name] = _module_version(name)

    if missing:
        return Check(
            "依赖完整性",
            FAIL,
            "缺失必需依赖：" + ", ".join(missing) + "（先执行 uv sync）",
            {"missing": missing, "versions": versions},
        )
    detail = " ".join(f"{k}={v}" for k, v in versions.items())
    if optional_missing:
        detail += f" | 可选未装：{', '.join(optional_missing)}"
    return Check("依赖完整性", OK, detail, {"versions": versions})


def check_config() -> Check:
    """.env / 环境变量是否可解析，并回显关键配置。"""
    settings = get_settings()
    info = {
        "provider": settings.llm_provider,
        "base_url": settings.llm_base_url,
        "model_large": settings.llm_model_large,
        "model_small": settings.llm_model_small,
        "max_iterations": settings.max_iterations,
        "review_threshold": settings.review_threshold,
        "tool_timeout": settings.tool_timeout,
        "enable_hitl": settings.enable_hitl,
    }
    detail = (
        f"{info['provider']} | {info['base_url']} | "
        f"large={info['model_large']} small={info['model_small']}"
    )
    return Check("配置加载", OK, detail, info)


def check_api_key() -> Check:
    """API Key 是否存在且非占位值。"""
    settings = get_settings()
    if not settings.llm_configured:
        return Check(
            "API Key",
            FAIL,
            "未配置 LLM_API_KEY（请 cp .env.example .env 后填入真实 Key）",
        )
    raw = settings.llm_api_key.get_secret_value()
    if "xxxx" in raw.lower() or raw.startswith("sk-your"):
        return Check("API Key", FAIL, f"仍是占位值：{settings.masked_api_key}")
    return Check("API Key", OK, settings.masked_api_key)


def check_workspace() -> Check:
    """工具沙箱目录必须存在且可读写（阶段 2 的 file_io 依赖它）。"""
    settings = get_settings()
    target = settings.workspace_dir
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".health_check_probe"
        probe.write_text("ok", encoding="utf-8")
        content = probe.read_text(encoding="utf-8")
        probe.unlink()
        if content != "ok":
            return Check("沙箱目录", FAIL, f"{target} 写入后读回不一致")
        return Check("沙箱目录", OK, f"{target} 可读写")
    except OSError as exc:
        return Check("沙箱目录", FAIL, f"{target} 不可读写：{exc}")


def check_database() -> Check:
    """SQLite 落盘目录是否可创建。"""
    settings = get_settings()
    db_path = settings.db_path
    if db_path is None:
        return Check("数据库", WARN, f"非 SQLite 连接串，跳过目录检查：{settings.db_url}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Check("数据库", FAIL, f"无法创建目录 {db_path.parent}：{exc}")
    exists = "已存在" if db_path.exists() else "首次运行时自动创建"
    return Check("数据库", OK, f"{db_path}（{exists}）")


def check_redis() -> Check:
    """Redis 直连探测。阶段 0-3 用到缓存前都可缺失，因此只告警。"""
    settings = get_settings()
    try:
        import redis
    except ImportError:
        return Check("Redis", WARN, "redis 包未安装（阶段 4 需要，先执行 uv sync）")
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        client.close()
        return Check("Redis", OK, f"{settings.redis_url} 连接正常")
    except Exception as exc:  # noqa: BLE001 - 未启动 / 端口不通都算告警
        return Check(
            "Redis",
            WARN,
            f"连接失败：{type(exc).__name__}（阶段 0-3 不阻塞；阶段 4 前用 "
            "docker compose up -d redis 启动）",
        )


def check_llm() -> Check:
    """真实调用一次 LLM，确认网络 / Key / 模型名三者都对。"""
    settings = get_settings()
    if not settings.llm_configured:
        return Check("LLM 连通性", FAIL, "缺少 API Key，跳过真实调用")
    try:
        from core.llm.adapter import LLMAdapter

        adapter = LLMAdapter(settings=settings, max_tokens=16)
        started = time.perf_counter()
        reply = adapter.invoke(
            [
                {"role": "system", "content": "你是一个连通性探针，只需原样回复指定单词。"},
                {"role": "user", "content": "Reply with exactly one word: pong"},
            ],
            model=settings.llm_model_large,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        reply_text = reply.strip()
        matched = "pong" in reply_text.lower()
        usage = adapter.last_usage.as_dict()
        detail = (
            f"{settings.llm_model_large} 回复 {reply_text[:40]!r}，"
            f"{elapsed}ms，in={usage['token_in']} out={usage['token_out']} "
            f"cost=¥{usage['cost']:.6f}"
        )
        return Check(
            "LLM 连通性",
            OK if matched else WARN,
            detail if matched else detail + "（未包含 pong，但请求成功）",
            usage,
        )
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要把所有异常转成结论
        return Check(
            "LLM 连通性",
            FAIL,
            f"{type(exc).__name__}: {str(exc)[:200]}",
        )


def check_llm_json() -> Check:
    """验证 JSON 链路：response_format + 抽取 + Pydantic 校验。"""
    settings = get_settings()
    if not settings.llm_configured:
        return Check("LLM JSON 链路", FAIL, "缺少 API Key，跳过")
    try:
        from core.llm.adapter import LLMAdapter

        adapter = LLMAdapter(settings=settings, max_tokens=64)
        schema = {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        }
        raw = adapter.invoke_json(
            [{"role": "user", "content": '返回 JSON：{"status": "pong", "ok": true}'}],
            schema,
            model=settings.llm_model_small,
        )
        # schema 声明的是 object，但 invoke_json 也可能返回 list（数组型契约），这里收窄
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if str(data.get("status", "")).lower() == "pong":
            return Check("LLM JSON 链路", OK, f"解析成功：{data}", data)
        return Check("LLM JSON 链路", WARN, f"结构正确但内容不符预期：{raw}", data)
    except Exception as exc:  # noqa: BLE001
        return Check("LLM JSON 链路", FAIL, f"{type(exc).__name__}: {str(exc)[:200]}")


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def run_all(skip_llm: bool = False) -> list[Check]:
    """按依赖顺序执行所有检查。"""
    checks = [
        check_python(),
        check_dependencies(),
        check_config(),
        check_api_key(),
        check_workspace(),
        check_database(),
        check_redis(),
    ]
    if not skip_llm:
        checks.append(check_llm())
        checks.append(check_llm_json())
    return checks


def render(checks: list[Check], use_color: bool = True) -> str:
    """把检查结果渲染成对齐的文本报表。"""
    width = max(len(c.name) for c in checks) + 2
    lines = ["", "=" * 78, " Trinity 环境自检报告", "=" * 78]
    for check in checks:
        label = check.status.upper()
        tag = f"{_COLOR[check.status]}{label:<4}{_RESET}" if use_color else f"{label:<4}"
        lines.append(f"[{tag}] {check.name.ljust(width)} {check.detail}")
    failures = sum(1 for c in checks if c.status == FAIL)
    warnings = sum(1 for c in checks if c.status == WARN)
    passed = len(checks) - failures - warnings
    lines.append("-" * 78)
    lines.append(f" 通过 {passed} / 告警 {warnings} / 失败 {failures}")
    if failures:
        lines.append(" 结论：存在阻塞项，请先修复上面标记为 FAIL 的检查。")
    elif warnings:
        lines.append(" 结论：核心链路可用，告警项属于后续阶段依赖，可在对应阶段处理。")
    else:
        lines.append(" 结论：环境完全就绪，可以进入阶段 1。")
    lines.append("=" * 78)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="Trinity 环境自检")
    parser.add_argument("--skip-llm", action="store_true", help="跳过真实 LLM 调用，零 token")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.setup_logging()

    checks = run_all(skip_llm=args.skip_llm)

    if args.json:
        payload = {
            "project_root": str(PROJECT_ROOT),
            "checks": [asdict(c) for c in checks],
            "summary": {
                "passed": sum(1 for c in checks if c.status == OK),
                "warnings": sum(1 for c in checks if c.status == WARN),
                "failures": sum(1 for c in checks if c.status == FAIL),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(checks, use_color=not args.no_color))

    return 1 if any(c.is_failure for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
