#!/usr/bin/env python
"""启动前环境自检（doctor）：把「起不来」的原因在起之前就挑出来。

与 ``scripts/health_check.py`` 的分工
------------------------------------

``health_check.py`` 是**服务起来之后**的健康检查（含真实 LLM 调用），
doctor 是**服务起来之前**的体检，两者都零副作用地读取本地状态：

===============  ==========================================================
检查项           不通时的含义
===============  ==========================================================
Python 版本      低于 pyproject 的 requires-python → 依赖装不上
依赖完整性       pyproject 里声明的包没装全 → import 阶段就会崩
.env            没复制 .env → 一调用模型就失败（服务能起但不可用）
端口占用         API_HOST:API_PORT 已被占用 → uvicorn 起不来
数据库可写       data/ 不可写 → 任务结果无处落库
可选依赖         redis / fastembed 权重缺失 → 只降级，不阻塞
===============  ==========================================================

零网络、零 token：本脚本不发任何外部请求（Redis 探测例外，且只连本机配置的地址，
超时 1 秒即放弃）。

用法::

    python scripts/doctor.py            # 人类可读报表
    python scripts/doctor.py --json     # 机器可读，便于 CI / 容器 entrypoint 消费

退出码：``0`` 表示无阻塞项（warn 允许）；``1`` 表示存在 fail。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import socket
import sqlite3
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 让 ``python scripts/doctor.py`` 也能 import 到项目根目录下的 config / storage
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 让 ``python scripts/doctor.py`` 也能 import 到项目根目录下的 config / storage。
#:
#: **这里刻意「延迟 + 防护」式导入 ``config``，而不是顶层直接 ``from config import
#: get_settings``。** 原因：doctor 存在的唯一理由是诊断「干净 clone 缺依赖」，
#: 而 ``config`` 顶层会 ``import pydantic``。若在模块导入期就把它拉起来，裸环境
#: （只装了 pip、没装 pydantic）一执行 doctor 就会在 import 阶段抛
#: ``ModuleNotFoundError: No module named 'pydantic'``——恰恰在最需要它的场景下
#: 先自己崩掉，且 stdout 为空（traceback 走 stderr）。所以改成惰性获取：
#: 只有真正需要读配置的检查函数被调用时才 import，且失败时降级为一条 FAIL 项。
#:
#: 除本函数外，**本模块顶层不得再 import 任何第三方包**（stdlib 除外）；
#: 其余第三方依赖（redis / pydantic 等）一律走 ``importlib.import_module`` 惰性导入。
_SETTINGS_IMPORT_ERROR: str | None = None


def _get_settings() -> Any | None:
    """尝试获取全局配置；失败时返回 ``None`` 并记录原因（不抛异常）。

    Returns:
        ``Settings`` 实例；当 ``config`` / ``pydantic`` 不可用时返回 ``None``。
    """
    global _SETTINGS_IMPORT_ERROR
    try:
        from config import get_settings  # noqa: PLC0415 - 故意延迟导入，见上方说明
    except Exception as exc:  # noqa: BLE001 - 裸环境缺 pydantic 等，一律降级
        _SETTINGS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None
    try:
        return get_settings()
    except Exception as exc:  # noqa: BLE001 - 配置校验失败也降级，不让 doctor 崩
        _SETTINGS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def _settings_unavailable_check(name: str) -> Check:
    """当配置不可用时，统一给出一条 FAIL，附带可操作的修法。"""
    detail = (
        f"无法加载配置（{_SETTINGS_IMPORT_ERROR or '未知原因'}）——"
        "通常是因为依赖未装齐。修法：pip install -e \".[dev]\""
    )
    return Check(name, FAIL, detail, {"import_error": _SETTINGS_IMPORT_ERROR})


OK, WARN, FAIL = "ok", "warn", "fail"
_COLOR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
_RESET = "\033[0m"

#: 分发包名 → 导入模块名。列表里没出现的按「- 换成 _」推导，
#: 这张表只收「推导规则不覆盖」的历史遗留命名（PEP 8 vs PyPI 命名不一致）。
_IMPORT_NAME_OVERRIDES: dict[str, str] = {
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
}

#: 只做状态汇报、缺失不阻塞的可选依赖（redis 已移出主依赖，属 optional extra）
OPTIONAL_PACKAGES: tuple[str, ...] = ("redis",)


@dataclass
class Check:
    """单项检查结果。"""

    name: str
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        """是否为阻塞项。"""
        return self.status == FAIL


# --------------------------------------------------------------------------- #
# pyproject 读取（依赖清单的唯一真源）
# --------------------------------------------------------------------------- #
def load_pyproject() -> dict[str, Any]:
    """解析 ``pyproject.toml``。

    Returns:
        解析后的字典。

    Raises:
        FileNotFoundError: 文件不存在（说明不在项目根目录运行）。
        tomllib.TOMLDecodeError: 文件不是合法 TOML。
    """
    path = PROJECT_ROOT / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _distribution_name(spec: str) -> str:
    """把依赖声明（``"fastapi>=0.115"``）还原成分发包名（``fastapi``）。"""
    name = spec.strip()
    for marker in (">=", "<=", "==", "!=", "~=", ">", "<", "[", ";"):
        if marker in name:
            name = name.split(marker, 1)[0]
    return name.strip()


def _import_name(distribution: str) -> str:
    """把分发包名换算成可 import 的模块名。"""
    return _IMPORT_NAME_OVERRIDES.get(distribution, distribution.replace("-", "_"))


def _installed_version(distribution: str) -> str | None:
    """查已装版本；未安装返回 ``None``。

    刻意用 ``importlib.metadata`` 而不是直接 import：后者会触发三方库的
    重初始化副作用（如 langchain 的告警），doctor 要的是「装没装」不是「能不能用」。
    """
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def check_python(pyproject: dict[str, Any]) -> Check:
    """运行时 Python 版本必须满足 ``project.requires-python``。"""
    required = str(pyproject.get("project", {}).get("requires-python", ">=3.12"))
    digits = "".join(ch for ch in required if ch.isdigit() or ch == ".")
    parts = [int(part) for part in digits.split(".") if part]
    floor = tuple(parts[:2]) if len(parts) >= 2 else (3, 12)
    current = sys.version_info[:2]
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if current >= floor:
        return Check("Python 版本", OK, f"{version}（要求 >={'.'.join(map(str, floor))}）")
    return Check(
        "Python 版本",
        FAIL,
        f"{version} 低于 pyproject 要求的 >={'.'.join(map(str, floor))}（{sys.executable}）",
    )


def check_dependencies(pyproject: dict[str, Any]) -> Check:
    """逐条核对 pyproject 声明的**主依赖**是否都装上了。

    清单直接从 pyproject 读，不手抄一份 requirements——抄一份就一定会漂移。
    """
    declared = [_distribution_name(item) for item in pyproject["project"]["dependencies"]]
    missing = [name for name in declared if _installed_version(name) is None]
    versions = {name: _installed_version(name) for name in declared if _installed_version(name)}
    if missing:
        return Check(
            "依赖完整性",
            FAIL,
            "缺失：" + ", ".join(missing) + "（修法：pip install -e \".[dev]\" 或 docker compose build）",
            {"missing": missing, "installed": versions},
        )
    return Check(
        "依赖完整性",
        OK,
        f"{len(declared)} 个主依赖齐全",
        {"installed": versions},
    )


def check_optional_dependencies() -> Check:
    """可选依赖（redis）状态：没装只降级，不阻塞。

    redis 从主依赖移到 ``[project.optional-dependencies] redis`` 之后，
    ``storage.cache`` 会在导入失败时自动退化为进程内缓存，所以这里只告警。
    """
    states: dict[str, str] = {}
    for name in OPTIONAL_PACKAGES:
        version = _installed_version(name)
        states[name] = version or "未安装"
    if all(value == "未安装" for value in states.values()):
        return Check(
            "可选依赖",
            WARN,
            "redis 未安装 —— 缓存自动降级为进程内缓存（功能不受影响；"
            "需要时 pip install \".[redis]\" 或 docker compose --profile redis up）",
            states,
        )
    return Check("可选依赖", OK, " ".join(f"{k}={v}" for k, v in states.items()), states)


def check_embedding_weights() -> Check:
    """fastembed 权重缓存：没有也能起，首次索引时才联网下载（约 100MB）。"""
    settings = _get_settings()
    if settings is None:
        return _settings_unavailable_check("embedding 权重")
    cache_dir = settings.fastembed_cache_dir
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = [p for p in cache_dir.rglob("*") if p.is_file()]
    except OSError as exc:
        return Check("embedding 权重", WARN, f"缓存目录不可用：{cache_dir}（{exc}）")
    if not cached:
        return Check(
            "embedding 权重",
            WARN,
            f"{cache_dir} 为空 —— 首次索引知识库会联网下载 ONNX 权重（约 100MB）",
            {"cache_dir": str(cache_dir), "files": 0},
        )
    size_mb = sum(p.stat().st_size for p in cached) / 1024 / 1024
    return Check(
        "embedding 权重",
        OK,
        f"{cache_dir} 已缓存 {len(cached)} 个文件（{size_mb:.1f} MB）",
        {"cache_dir": str(cache_dir), "files": len(cached), "size_mb": round(size_mb, 1)},
    )


def check_env_file() -> Check:
    """.env 是否存在；不存在时服务能起，但一调用模型就失败。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return Check(
            ".env 文件",
            WARN,
            "未找到 .env —— 服务能起来，但调用模型会失败。"
            "修法：cp .env.example .env 后填入 LLM_API_KEY",
        )
    settings = _get_settings()
    if settings is None:
        return Check(
            ".env 文件",
            WARN,
            f".env 存在，但配置无法加载（{_SETTINGS_IMPORT_ERROR or '未知原因'}），"
            "无法确认 LLM_API_KEY 是否已配置",
        )
    if not settings.llm_configured:
        return Check(".env 文件", WARN, "存在但未配置 LLM_API_KEY（检索/评测不受影响）")
    return Check(".env 文件", OK, f"已加载，Key={settings.masked_api_key}")


def check_port() -> Check:
    """API 端口是否被占用。

    被占用只告警不算失败：可能是上一次的实例还在跑（正常），
    也可能是别的进程占了（换 ``API_PORT`` 即可）。
    """
    settings = _get_settings()
    if settings is None:
        return _settings_unavailable_check("端口占用")
    host = settings.api_host
    port = settings.api_port
    # 0.0.0.0 是不可连接的通配地址，探测时换成回环地址才有意义
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.5):
            return Check(
                "端口占用",
                WARN,
                f"{host}:{port} 已被占用 —— 换端口：set API_PORT=8001，"
                "或 docker compose 里改 ports 映射",
            )
    except OSError:
        return Check("端口占用", OK, f"{host}:{port} 空闲")


def check_database_writable() -> Check:
    """数据库可写性：目录能建 + SQLite 能建表能删表。

    非 SQLite 连接串（如 Postgres）不做探测——那属于部署方自己的连通性范畴。
    """
    settings = _get_settings()
    if settings is None:
        return _settings_unavailable_check("数据库")
    db_path = settings.db_path
    if db_path is None:
        return Check("数据库", WARN, f"非 SQLite 连接串，跳过本地写探测：{settings.db_url}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db_path), timeout=3)
    except (OSError, sqlite3.Error) as exc:
        return Check("数据库", FAIL, f"{db_path} 不可写：{type(exc).__name__}: {exc}")
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS _doctor_probe (id INTEGER)")
        connection.execute("DROP TABLE _doctor_probe")
        connection.commit()
    except sqlite3.Error as exc:
        connection.close()
        return Check("数据库", FAIL, f"{db_path} 可连接但不可写：{exc}")
    finally:
        connection.close()
    exists = "已存在" if db_path.exists() else "首次运行自动创建"
    return Check("数据库", OK, f"{db_path} 可读写（{exists}）")


def check_data_dirs_writable() -> Check:
    """运行期目录（workspace / knowledge / logs）能否建并写入。"""
    settings = _get_settings()
    if settings is None:
        return _settings_unavailable_check("数据目录")
    targets = {
        "workspace": settings.workspace_dir,
        "knowledge": settings.knowledge_dir,
        "logs": settings.log_dir,
    }
    broken: list[str] = []
    for label, target in targets.items():
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".doctor_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            broken.append(f"{label}({target}): {exc}")
    if broken:
        return Check("数据目录", FAIL, "不可写：" + "；".join(broken))
    return Check(
        "数据目录", OK, "workspace / knowledge / logs 均可读写", {"dirs": {k: str(v) for k, v in targets.items()}}
    )


def check_redis_reachable() -> Check:
    """Redis 直连探测：不通只告警（与 ``/health`` 的 degraded 口径一致）。"""
    settings = _get_settings()
    if settings is None:
        return _settings_unavailable_check("Redis 连通性")
    try:
        redis_module = importlib.import_module("redis")
    except ImportError:
        return Check(
            "Redis 连通性",
            WARN,
            "redis 包未安装，缓存降级为进程内缓存（pip install \".[redis]\"）",
        )
    try:
        client = redis_module.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.ping()
        client.close()
        return Check("Redis 连通性", OK, f"{settings.redis_url} 可用")
    except Exception as exc:  # noqa: BLE001 - 未启动 / 端口不通都算告警
        return Check(
            "Redis 连通性",
            WARN,
            f"{settings.redis_url} 不可用（{type(exc).__name__}）——"
            "平台会用进程内缓存，功能不受影响",
        )


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def run_all() -> list[Check]:
    """按「先环境、后配置、再外部依赖」的顺序执行全部检查。

    ``pyproject.toml`` 读取失败（不在项目根运行 / 文件损坏）不抛异常，
    而是把依赖相关两项标 FAIL，其余检查照跑——doctor 的诊断职责优先于自身鲁棒性。
    """
    try:
        pyproject: dict[str, Any] | None = load_pyproject()
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError) as exc:
        pyproject = None
        pyproject_error = f"{type(exc).__name__}: {exc}"
    else:
        pyproject_error = ""

    if pyproject is None:
        fail = Check(
            "pyproject 解析",
            FAIL,
            f"无法读取 {PROJECT_ROOT / 'pyproject.toml'}（{pyproject_error}）——"
            "请确认在项目根目录下运行 doctor",
        )
        dependency_checks: list[Check] = [
            fail,
            check_optional_dependencies(),
        ]
    else:
        dependency_checks = [
            check_python(pyproject),
            check_dependencies(pyproject),
            check_optional_dependencies(),
        ]

    return [
        *dependency_checks,
        check_embedding_weights(),
        check_env_file(),
        check_port(),
        check_database_writable(),
        check_data_dirs_writable(),
        check_redis_reachable(),
    ]


def render(checks: list[Check], use_color: bool = True) -> str:
    """把检查结果渲染成对齐的文本报表。"""
    width = max(len(check.name) for check in checks) + 2
    lines = ["", "=" * 78, " Trinity 启动前环境自检（doctor）", "=" * 78]
    for check in checks:
        label = check.status.upper()
        tag = f"{_COLOR[check.status]}{label:<4}{_RESET}" if use_color else f"{label:<4}"
        lines.append(f"[{tag}] {check.name.ljust(width)} {check.detail}")
    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    passed = len(checks) - failures - warnings
    lines.append("-" * 78)
    lines.append(f" 通过 {passed} / 告警 {warnings} / 失败 {failures}")
    if failures:
        lines.append(" 结论：存在阻塞项，先修上面标记为 FAIL 的检查再启动。")
    elif warnings:
        lines.append(" 结论：可以启动；告警项是可选能力，缺失时平台会自动降级。")
    else:
        lines.append(" 结论：环境完全就绪，直接启动即可。")
    lines.append("=" * 78)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数；``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        退出码：``0`` 无阻塞项，``1`` 存在 fail。
    """
    parser = argparse.ArgumentParser(description="Trinity 启动前环境自检（doctor）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    args = parser.parse_args(argv)

    checks = run_all()

    if args.json:
        payload = {
            "project_root": str(PROJECT_ROOT),
            "checks": [asdict(check) for check in checks],
            "summary": {
                "passed": sum(1 for check in checks if check.status == OK),
                "warnings": sum(1 for check in checks if check.status == WARN),
                "failures": sum(1 for check in checks if check.status == FAIL),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(checks, use_color=not args.no_color))

    return 1 if any(check.is_failure for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
