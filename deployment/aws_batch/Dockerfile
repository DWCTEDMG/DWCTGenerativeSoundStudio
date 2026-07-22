# checkov:skip=CKV_DOCKER_2:Finite AWS Batch worker; Batch monitors the entrypoint exit status and this image exposes no service endpoint.
FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV HOME=/home/edmg \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 edmg \
    && useradd --system --uid 10001 --gid edmg --create-home --home-dir /home/edmg edmg

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
RUN mkdir -p /data \
    && chown -R edmg:edmg /data /home/edmg

# This is a finite AWS Batch worker, not a service. AWS Batch uses the
# entrypoint's exit status; an HTTP or process-only HEALTHCHECK would be false.
USER edmg

ENTRYPOINT ["uv", "run", "--project", "/app/python_backend", "--frozen", "--no-sync", "python", "/app/worker.py"]
