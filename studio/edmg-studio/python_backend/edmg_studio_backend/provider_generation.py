from __future__ import annotations

from typing import Any


GENERATION_SCHEMA_VERSION = "1.0"
INTERNAL_PROVIDER_ID = "edmg.internal"


def generation_provider_definitions(provider_status: dict[str, Any]) -> dict[str, Any]:
    hardware = provider_status.get("hardware") if isinstance(provider_status.get("hardware"), dict) else {}
    backend = str(hardware.get("backend") or "cpu").strip().lower()
    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "providers": [
            {
                "id": INTERNAL_PROVIDER_ID,
                "name": "EDMG Internal Renderer",
                "kind": "local",
                "operations": ["video"],
                "capabilities": [
                    "text_to_video",
                    "image_to_video",
                    "timeline_camera",
                    "temporal_continuity",
                    "durable_queue",
                ],
                "renderer_ids": ["auto", "diffusion", "tensorrt", "hunyuan_video15", "ltx_25"],
                "ready": backend in {"cpu", "cuda", "directml", "mps"},
                "hardware_backend": backend,
            }
        ],
    }


def normalized_generation_job(job: Any) -> dict[str, Any]:
    payload = job.payload if isinstance(getattr(job, "payload", None), dict) else {}
    metadata = payload.get("_generation") if isinstance(payload.get("_generation"), dict) else {}
    result = job.result if isinstance(getattr(job, "result", None), dict) else {}
    progress = job.progress if isinstance(getattr(job, "progress", None), dict) else {}
    artifacts: list[dict[str, Any]] = []
    artifact = result.get("artifact")
    if isinstance(artifact, dict):
        artifacts.append(dict(artifact))
    elif isinstance(result.get("video"), str) and result["video"].strip():
        artifacts.append({"kind": "video", "path": result["video"]})

    status = str(getattr(job, "status", "queued") or "queued").lower()
    if status not in {"queued", "paused", "running", "succeeded", "failed", "canceled", "blocked"}:
        status = "blocked"
    return {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "operation": str(metadata.get("operation") or "video"),
        "provider_id": str(metadata.get("provider_id") or INTERNAL_PROVIDER_ID),
        "renderer_id": str(metadata.get("renderer_id") or payload.get("video_model_engine") or payload.get("render_mode") or "auto"),
        "status": status,
        "progress": {
            "percent": float(progress.get("percent") or 0.0),
            "stage": str(progress.get("stage") or status),
            "message": str(progress.get("message") or ""),
            "current": progress.get("current"),
            "total": progress.get("total"),
        },
        "artifacts": artifacts,
        "error": getattr(job, "error", None),
        "created_at": getattr(job, "created_at", None),
        "updated_at": getattr(job, "updated_at", None),
        "attempt": int(getattr(job, "attempt", 0) or 0),
        "priority": int(getattr(job, "priority", 0) or 0),
    }
