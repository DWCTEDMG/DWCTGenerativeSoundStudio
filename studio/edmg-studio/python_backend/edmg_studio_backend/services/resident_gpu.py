"""Coordinate an optional resident Director container with GPU render jobs.

The lease is deliberately a no-op unless a host coordinator socket is configured.
This keeps normal CPU and single-runtime deployments independent of Docker-host access.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket


@contextlib.contextmanager
def resident_gpu_lease(job):
    path = os.getenv("EDMG_GPU_COORDINATOR_SOCKET", "").strip()
    if not path or job.type not in {"internal_video", "internal_still_scene", "qwen_director", "runtime_optimization"}:
        yield
        return
    director = job.type == "qwen_director" and job.payload.get("provider") == "nemotron"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1800)
    try:
        client.connect(path)
        client.sendall(json.dumps({"mode": "director" if director else "render"}).encode() + b"\n")
        response = client.makefile("rb").readline(4096)
        result = json.loads(response)
        if not result.get("ready"):
            raise RuntimeError("GPU handoff failed: " + str(result.get("error", "coordinator unavailable")))
        yield
    finally:
        client.close()
