FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install backend
COPY studio/edmg-studio/python_backend /app/python_backend
RUN cd /app/python_backend \
    && uv lock --check \
    && uv sync --frozen --no-dev \
        --extra cpu --extra core --extra audio --extra asr \
        --extra internal-video --extra aws

# Batch worker
COPY deployment/aws_batch/worker.py /app/worker.py

ENTRYPOINT ["uv", "run", "--project", "/app/python_backend", "--frozen", "--no-sync", "python", "/app/worker.py"]
