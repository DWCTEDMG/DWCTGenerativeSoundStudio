from __future__ import annotations

import time
import uuid
from typing import Any

TEMPLATE_PACKAGE_SCHEMA_VERSION = 1


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _collect_model_refs(meta: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    for key in ("last_internal_render", "last_comfy_render", "last_animation_autoconfig"):
        block = meta.get(key)
        if not isinstance(block, dict):
            continue
        for field in ("model_id", "checkpoint", "internal_model_id", "video_model_id"):
            value = block.get(field)
            if isinstance(value, str) and value.strip():
                refs.add(value.strip())
    intent = meta.get("last_conductor_intent")
    if isinstance(intent, dict):
        for engine in intent.get("allowed_engines") or []:
            if isinstance(engine, str) and engine.strip():
                refs.add(f"engine:{engine.strip()}")
    return sorted(refs)


def _collect_asset_refs(meta: dict[str, Any]) -> list[str]:
    assets: set[str] = set()
    audio = meta.get("audio")
    if isinstance(audio, dict) and isinstance(audio.get("filename"), str):
        assets.add(str(audio["filename"]))
    refs = meta.get("refs")
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, str) and item.strip():
                assets.add(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                assets.add(str(item["path"]))
    return sorted(assets)


def export_template_package(
    *,
    project_id: str,
    project_name: str | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    plan = meta.get("last_plan") if isinstance(meta.get("last_plan"), dict) else {}
    variants = plan.get("variants") if isinstance(plan.get("variants"), list) else []
    scene_count = 0
    if variants and isinstance(variants[0], dict):
        scenes = variants[0].get("scenes")
        scene_count = len(scenes) if isinstance(scenes, list) else 0

    package_id = f"tpl-{project_id}-{uuid.uuid4().hex[:8]}"
    models = _collect_model_refs(meta)
    assets = _collect_asset_refs(meta)
    visual_dna = meta.get("visual_dna") if isinstance(meta.get("visual_dna"), dict) else None
    director = meta.get("director") if isinstance(meta.get("director"), dict) else None

    return {
        "schema_version": TEMPLATE_PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "version": "1.0.0",
        "name": project_name or project_id,
        "exported_at": _utc_now(),
        "source_project_id": project_id,
        "permissions": ["local_use", "share_readonly"],
        "dependencies": [],
        "models": models,
        "assets": assets,
        "compatibility": {
            "studio_min": "0.1.0",
            "python": "3.12",
            "requires_models_installed": bool(models),
        },
        "payload": {
            "director_mode": director.get("mode") if director else meta.get("director_mode"),
            "visual_dna": visual_dna,
            "scene_count": scene_count,
            "animation_preset": meta.get("last_animation_preset"),
            "render_preset": meta.get("last_render_preset"),
            "conductor_intent": meta.get("last_conductor_intent"),
        },
    }


def import_template_package(
    package: dict[str, Any],
    *,
    merge: bool = True,
) -> dict[str, Any]:
    if not isinstance(package, dict):
        raise ValueError("Template package must be an object")
    schema_version = int(package.get("schema_version") or 0)
    if schema_version != TEMPLATE_PACKAGE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported template package schema_version={schema_version}")

    payload = package.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Template package payload is required")

    applied: dict[str, Any] = {"fields": [], "package_id": package.get("package_id"), "merge": merge}
    patch: dict[str, Any] = {}

    if payload.get("visual_dna") is not None:
        patch["visual_dna"] = payload["visual_dna"]
        applied["fields"].append("visual_dna")
    if payload.get("director_mode") is not None:
        patch["director_mode"] = payload["director_mode"]
        applied["fields"].append("director_mode")
    if payload.get("animation_preset") is not None:
        patch["last_animation_preset"] = payload["animation_preset"]
        applied["fields"].append("last_animation_preset")
    if payload.get("render_preset") is not None:
        patch["last_render_preset"] = payload["render_preset"]
        applied["fields"].append("last_render_preset")
    if payload.get("conductor_intent") is not None:
        patch["last_conductor_intent"] = payload["conductor_intent"]
        applied["fields"].append("last_conductor_intent")

    if not patch:
        raise ValueError("Template package payload did not contain importable fields")

    applied["patch"] = patch
    applied["models_required"] = list(package.get("models") or [])
    applied["assets_referenced"] = list(package.get("assets") or [])
    return applied
