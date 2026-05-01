FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EDMG_STUDIO_HOME=/studio \
    EDMG_STUDIO_DATA_DIR=/studio/data \
    EDMG_STUDIO_MODELS_DIR=/studio/models \
    EDMG_STUDIO_CACHE_DIR=/studio/cache \
    EDMG_STUDIO_LOGS_DIR=/studio/logs \
    EDMG_STUDIO_EXTERNAL_DIR=/studio/external \
    EDMG_FFMPEG_PATH=ffmpeg \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    git \
    libgomp1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/edmg/python_backend

# Hyperlift builds from the repo root, so copy only the backend subtree.
COPY studio/edmg-studio/python_backend/ /opt/edmg/python_backend/

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -e ".[studio_bundle]"

RUN mkdir -p /studio/data /studio/models /studio/cache /studio/logs /studio/external

CMD ["sh", "-lc", "edmg-studio-backend serve --host 0.0.0.0 --port ${PORT:-8080}"]
