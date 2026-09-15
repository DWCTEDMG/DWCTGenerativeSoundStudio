from __future__ import annotations

from typing import Any

GENERATION_SCHEMA_VERSION = "1.0"
INTERNAL_PROVIDER_ID = "edmg.internal"
COMFYUI_PROVIDER_ID = "comfyui"
STABILITY_PROVIDER_ID = "stability"
FIREFLY_PROVIDER_ID = "adobe.firefly"
IMAGINEART_PROVIDER_ID = "imagineart"
COSMOS_PROVIDER_ID = "nvidia.cosmos"
AZURE_FOUNDRY_PROVIDER_ID = "azure.foundry.cosmos"

PROVIDER_OPERATIONS = {
    INTERNAL_PROVIDER_ID: ("video",),
    COMFYUI_PROVIDER_ID: ("image", "video"),
    STABILITY_PROVIDER_ID: ("image",),
    FIREFLY_PROVIDER_ID: ("image", "video"),
    IMAGINEART_PROVIDER_ID: ("image", "video"),
    COSMOS_PROVIDER_ID: ("video",),
    AZURE_FOUNDRY_PROVIDER_ID: ("video",),
}


def provider_supports(provider_id: str, operation: str) -> bool:
    return operation in PROVIDER_OPERATIONS.get(provider_id, ())


def _readiness(status: dict[str, Any], key: str, *ready_keys: str) -> tuple[bool, str]:
    provider = status.get(key) if isinstance(status.get(key), dict) else {}
    ready = all(bool(provider.get(item)) for item in ready_keys)
    return ready, str(provider.get("note") or ("Ready" if ready else "Configure this provider in Settings."))


def generation_provider_definitions(provider_status: dict[str, Any]) -> dict[str, Any]:
    hardware = provider_status.get("hardware") if isinstance(provider_status.get("hardware"), dict) else {}
    backend = str(hardware.get("backend") or "cpu").strip().lower()
    comfy = provider_status.get("comfyui") if isinstance(provider_status.get("comfyui"), dict) else {}
    firefly_ready, firefly_note = _readiness(provider_status, "firefly", "configured", "enabled")
    stability_ready, stability_note = _readiness(provider_status, "stability", "configured", "enabled")
    imagineart_ready, imagineart_note = _readiness(provider_status, "imagineart", "configured", "enabled")
    cosmos_ready, cosmos_note = _readiness(provider_status, "cosmos", "configured", "enabled")
    azure_ready, azure_note = _readiness(provider_status, "azure_foundry", "configured", "enabled", "has_api_key")
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
                "readiness_detail": f"Internal renderer available through {backend}.",
            },
            {
                "id": COMFYUI_PROVIDER_ID,
                "name": "ComfyUI",
                "kind": "local",
                "operations": list(PROVIDER_OPERATIONS[COMFYUI_PROVIDER_ID]),
                "capabilities": ["text_to_image", "image_to_image", "image_to_video", "durable_queue"],
                "renderer_ids": ["auto", "animatediff", "svd"],
                "ready": bool(comfy.get("ready")),
                "readiness_detail": str(comfy.get("detail") or "Start ComfyUI and verify its model nodes."),
            },
            {
                "id": STABILITY_PROVIDER_ID,
                "name": "Stability AI",
                "kind": "hosted",
                "operations": list(PROVIDER_OPERATIONS[STABILITY_PROVIDER_ID]),
                "capabilities": ["text_to_image", "image_to_image", "durable_queue"],
                "renderer_ids": [],
                "ready": stability_ready,
                "readiness_detail": stability_note,
            },
            {
                "id": FIREFLY_PROVIDER_ID,
                "name": "Adobe Firefly",
                "kind": "hosted",
                "operations": list(PROVIDER_OPERATIONS[FIREFLY_PROVIDER_ID]),
                "capabilities": ["text_to_image", "text_to_video", "custom_models", "durable_queue"],
                "renderer_ids": [],
                "ready": firefly_ready,
                "readiness_detail": firefly_note,
            },
            {
                "id": IMAGINEART_PROVIDER_ID,
                "name": "ImagineArt",
                "kind": "hosted",
                "operations": list(PROVIDER_OPERATIONS[IMAGINEART_PROVIDER_ID]),
                "capabilities": ["text_to_image", "text_to_video", "image_to_video", "durable_queue"],
                "renderer_ids": [],
                "ready": imagineart_ready,
                "readiness_detail": imagineart_note,
            },
            {
                "id": COSMOS_PROVIDER_ID,
                "name": "NVIDIA Cosmos NIM",
                "kind": "self_hosted",
                "operations": list(PROVIDER_OPERATIONS[COSMOS_PROVIDER_ID]),
                "capabilities": ["text_to_video", "image_to_video", "durable_queue"],
                "renderer_ids": [],
                "ready": cosmos_ready,
                "readiness_detail": cosmos_note,
            },
            {
                "id": AZURE_FOUNDRY_PROVIDER_ID,
                "name": "Azure AI Foundry Cosmos",
                "kind": "hosted",
                "operations": list(PROVIDER_OPERATIONS[AZURE_FOUNDRY_PROVIDER_ID]),
                "capabilities": ["text_to_video", "image_to_video", "durable_queue"],
                "renderer_ids": [],
                "ready": azure_ready,
                "readiness_detail": azure_note,
            },
        ],
    }


def normalize_provider_result(provider_id: str, operation: str, result: dict[str, Any]) -> dict[str, Any]:
    raw_items = result.get("results") if isinstance(result.get("results"), list) else [result]
    artifacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            failures.append({"message": "Provider returned an invalid result item."})
            continue
        error = raw_item.get("error") or raw_item.get("message")
        if raw_item.get("ok") is False or error:
            failure = {"message": str(error or "Provider generation failed")}
            for key in ("scene_index", "hint", "code"):
                if raw_item.get(key) is not None:
                    failure[key] = raw_item[key]
            failures.append(failure)
            continue
        path = raw_item.get("path") or raw_item.get(operation) or raw_item.get("saved")
        if not isinstance(path, str) or not path.strip():
            failures.append({
                "scene_index": raw_item.get("scene_index"),
                "message": "Provider completed without an artifact path.",
            })
            continue
        artifact: dict[str, Any] = {"kind": operation, "path": path.replace("\\", "/")}
        aliases = {
            "generation_id": "provider_generation_id",
            "scene_index": "scene_index",
            "model": "model",
            "seed": "seed",
            "width": "width",
            "height": "height",
            "duration_s": "duration_s",
            "frames": "frames",
            "fps": "fps",
        }
        for source, target in aliases.items():
            value = raw_item.get(source, result.get(source))
            if value is not None:
                artifact[target] = value
        artifacts.append(artifact)
    normalized = {
        "ok": bool(artifacts),
        "provider_id": provider_id,
        "operation": operation,
        "artifacts": artifacts,
        "failures": failures,
        "partial_failure": bool(artifacts and failures),
    }
    for key in ("usage", "cost"):
        if isinstance(result.get(key), dict):
            normalized[key] = dict(result[key])
    return normalized


def normalized_generation_job(job: Any) -> dict[str, Any]:
    payload = job.payload if isinstance(getattr(job, "payload", None), dict) else {}
    metadata = payload.get("_generation") if isinstance(payload.get("_generation"), dict) else {}
    result = job.result if isinstance(getattr(job, "result", None), dict) else {}
    progress = job.progress if isinstance(getattr(job, "progress", None), dict) else {}
    artifacts = [dict(item) for item in result.get("artifacts", []) if isinstance(item, dict)]
    if not artifacts:
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            artifacts.append(dict(artifact))
        elif isinstance(result.get("video"), str) and result["video"].strip():
            artifacts.append({"kind": "video", "path": result["video"]})
        elif isinstance(result.get("saved"), str) and result["saved"].strip():
            artifacts.append({"kind": str(metadata.get("operation") or "image"), "path": result["saved"]})

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
        "failures": [dict(item) for item in result.get("failures", []) if isinstance(item, dict)],
        "partial_failure": bool(result.get("partial_failure")),
        "usage": dict(result["usage"]) if isinstance(result.get("usage"), dict) else None,
        "cost": dict(result["cost"]) if isinstance(result.get("cost"), dict) else None,
        "error": getattr(job, "error", None),
        "created_at": getattr(job, "created_at", None),
        "updated_at": getattr(job, "updated_at", None),
        "attempt": int(getattr(job, "attempt", 0) or 0),
        "priority": int(getattr(job, "priority", 0) or 0),
    }
