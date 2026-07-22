FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    EDMG_STUDIO_HOME=/studio \
    EDMG_STUDIO_DATA_DIR=/studio/data \
    EDMG_STUDIO_MODELS_DIR=/studio/models \
    EDMG_STUDIO_CACHE_DIR=/studio/cache \
    EDMG_STUDIO_LOGS_DIR=/studio/logs \
    EDMG_STUDIO_EXTERNAL_DIR=/studio/external \
    EDMG_FFMPEG_PATH=ffmpeg \
    HOME=/home/edmg \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    git \
    libgomp1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 edmg \
    && useradd --system --uid 10001 --gid edmg --create-home --home-dir /home/edmg edmg

WORKDIR /opt/edmg/python_backend

# Hyperlift builds from the repo root, so copy only the backend subtree.
COPY studio/edmg-studio/python_backend/ /opt/edmg/python_backend/

# Consume the same frozen CPU profile as the supported source runtime. Remote
# AI can still be selected at runtime without changing the dependency graph.
RUN uv lock --check \
    && uv sync --frozen --no-dev \
        --extra cpu --extra core --extra audio --extra asr \
        --extra internal-video --extra aws

RUN mkdir -p /studio/data /studio/models /studio/cache /studio/logs /studio/external \
    && chown -R edmg:edmg /studio /home/edmg

USER edmg

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT','8080'),timeout=4).read()"]

CMD ["sh", "-lc", "uv run --frozen --no-sync edmg-studio-backend serve --host 0.0.0.0 --port ${PORT:-8080}"]
