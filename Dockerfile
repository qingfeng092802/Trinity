# ============================================================================
# Trinity 运行镜像
#
# 为什么是 python:3.12-slim 而不是 alpine
#   - 本项目依赖 numpy / tiktoken / sqlite-vec 等带原生扩展的包，
#     alpine 的 musl libc 会让 pip 走源码编译（慢、且经常缺 build 依赖）；
#   - slim（glibc）能直接吃 manylinux wheel，构建稳定、镜像也没有大多少。
#
# 为什么镜像能压到 ~600MB 以内
#   - 本地 embedding 走 fastembed（ONNX Runtime），**不装 torch**；
#     弃用的 sentence-transformers 已从依赖表删除，所以不会把 torch 拖进来
#     （torch wheel 单个体积就 800MB+，是镜像膨胀的第一大来源）。
#   - 只装 CPU 版依赖，不装 dev / ui extra。
#
# 构建:
#   docker build -t trinity:latest .
# 运行（推荐用 compose，见 docker-compose.yml）:
#   docker run --rm -p 8000:8000 --env-file .env -v trinity_data:/app/data \
#              trinity:latest
# ============================================================================

FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE：容器里 .pyc 无复用价值，省层体积；
# PYTHONUNBUFFERED：日志实时刷出，否则 docker logs 会攒批。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 依赖层单独一层：只要 pyproject 不变，改代码不会触发重装依赖。
COPY pyproject.toml README.md ./

# 关键点：本工程是**扁平布局**（config.py / api/ / core/ / storage/ ... 都在顶层，
# 没有 `src/` 包装层）。这里**只装第三方依赖**，不装项目自身——因为依赖层执行时
# 应用代码还没 COPY 进来（这是分层缓存换来的代价，值得），所以不能走 `pip install .`
# （它的构建后端要读目录树做包发现，此时目录是空的）。
# 依赖清单从 pyproject 的 dependencies 数组解析，不手抄第二份，避免漂移。
RUN pip install --upgrade pip && python - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]

# pip 不认 pyproject 的 PEP 621 依赖数组，这里逐条转成 pip 参数。
# --no-cache-dir 已在 ENV 里；镜像源显式指定保证构建可重复。
mirror = "https://mirrors.cloud.tencent.com/pypi/simple"
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-i", mirror, *project["dependencies"]],
    check=True,
)
PY

# 真正的应用代码
COPY . .

# 这里**刻意不再 `pip install .`**（旧版本有这一步，已删除）。三个理由：
#
# 1. 容器运行不需要它。CMD 是 `uvicorn api.main:app`，配合 ENV PYTHONPATH=/app，
#    Python 直接从 /app 解析 api/、core/、config.py —— 源码树就在工作目录里，
#    不需要把项目「安装」成包。
# 2. 旧注释给的理由（「让 setuptools 基于完整目录树做包发现」）**已经不成立**：
#    包发现在 pyproject 里由 [tool.setuptools.packages.find] 显式声明，运行时不再依赖。
# 3. 它曾是构建失败的根因（QA 实测）：当时 pyproject 没有 [build-system]，
#    这一步会因「Multiple top-level packages discovered」报错。现在即使能跑通，
#    在运行镜像里多装一份自身也是纯粹的浪费（多一层、多一份拷贝）。
#
# 注意：`pip install .` 的可安装性由 pyproject 的 [build-system] + packages.find 保证，
# 那是给「开发机上装包」用的，与镜像构建是两件事。

# 运行期需要的目录（挂载 volume 后会被覆盖，但卷首次创建时需要祖先目录存在）
RUN mkdir -p /app/data/workspace /app/data/knowledge/files /app/data/logs \
             /app/data/models/fastembed_cache

# 容器里必须绑 0.0.0.0 才对宿主可见；对外暴露前请务必设置 API_AUTH_TOKEN。
# PYTHONPATH=/app 是上面的前提：没有它 `uvicorn api.main:app` 找不到 api 包。
ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DB_URL=sqlite:///data/trinity.db \
    REDIS_URL=redis://redis:6379/0 \
    PYTHONPATH=/app

EXPOSE 8000

# 健康检查用项目自带的 /health：degraded 也是 200（有降级但能服务），
# 只有 unhealthy 才 503，与 PRD 口径一致。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status in (200,) else 1)"

# 直接用 uvicorn 而不是 scripts/start_api.py：start_api.py 的行为是「起子进程
# + 打印提示」，在容器里没有意义，还会让 PID 1 变成 python 而不是 uvicorn，
# 信号（SIGTERM）转发会变得不可靠，docker stop 变成 10 秒超时后 SIGKILL。
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
