FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    git \
    libgomp1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/edmg/python_backend

COPY studio/edmg-studio/python_backend/ /opt/edmg/python_backend/

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -e ".[audio,asr]"

CMD ["sh", "-lc", "python -m edmg_ai_service.cli serve --host 0.0.0.0 --port ${PORT:-8080}"]
