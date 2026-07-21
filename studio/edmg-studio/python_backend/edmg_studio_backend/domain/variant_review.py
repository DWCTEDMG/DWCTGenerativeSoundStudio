from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

VARIANT_REVIEW_SCHEMA_VERSION = "1.0"

_REVIEW_STATES = {"unreviewed", "approved", "rejected", "cherry_picked"}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _artifact_manifest_path(media_path: Path) -> Path:
    return media_path.with_suffix(media_path.suffix + ".artifact.json")


def _variant_index_from_name(name: str) -> int | None:
    match = re.search(r"(?:internal_v|variant[_-]?)(\d+)", name, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _artifact_entry(
    project_dir: Path,
    media_path: Path,
    *,
    kind: str,
) -> dict[str, Any] | None:
    if not media_path.exists() or not media_path.is_file():
        return None
    rel = str(media_path.relative_to(project_dir)).replace("\\", "/")
    manifest_path = _artifact_manifest_path(media_path)
    manifest = _read_json(manifest_path)
    metadata_path = media_path.with_suffix(media_path.suffix + ".meta.json")
    metadata = _read_json(metadata_path)
    variant_index = None
    if isinstance(manifest, dict):
        extra = manifest.get("extra") if isinstance(manifest.get("extra"), dict) else {}
        raw_index = extra.get("variant_index")
        if raw_index is not None:
            try:
                variant_index = int(raw_index)
            except Exception:
                variant_index = None
    if variant_index is None and isinstance(metadata, dict):
        raw_index = metadata.get("variant_index")
        if raw_index is not None:
            try:
                variant_index = int(raw_index)
            except Exception:
                variant_index = None
    if variant_index is None:
        variant_index = _variant_index_from_name(media_path.name)
    review = manifest.get("review") if isinstance(manifest, dict) and isinstance(manifest.get("review"), dict) else {}
    params = manifest.get("params") if isinstance(manifest, dict) and isinstance(manifest.get("params"), dict) else {}
    model = manifest.get("model") if isinstance(manifest, dict) and isinstance(manifest.get("model"), dict) else {}
    try:
        stat = media_path.stat()
        size_bytes = int(stat.st_size)
        modified_at = float(stat.st_mtime)
    except Exception:
        size_bytes = None
        modified_at = None
    return {
        "path": rel,
        "name": media_path.name,
        "kind": kind,
        "variant_index": variant_index if variant_index is not None else 0,
        "size_bytes": size_bytes,
        "modified_at": modified_at,
        "manifest_path": str(manifest_path.relative_to(project_dir)).replace("\\", "/") if manifest_path.exists() else None,
        "metadata_path": str(metadata_path.relative_to(project_dir)).replace("\\", "/") if metadata_path.exists() else None,
        "review_state": str(review.get("state") or "unreviewed"),
        "review_notes": str(review.get("notes") or ""),
        "cherry_pick_traits": list(review.get("cherry_pick_traits") or []) if isinstance(review.get("cherry_pick_traits"), list) else [],
        "engine": str((manifest or {}).get("engine") or (metadata or {}).get("engine") or ""),
        "model_id": str(model.get("id") or (metadata or {}).get("model_id") or "") if manifest or metadata else "",
        "seed": manifest.get("seed") if isinstance(manifest, dict) else metadata.get("seed") if isinstance(metadata, dict) else None,
        "params": params,
        "content_hash": manifest.get("content_hash") if isinstance(manifest, dict) else None,
        "provenance": {
            "parents": list((manifest.get("lineage") or {}).get("parents") or []) if isinstance(manifest, dict) else [],
            "source_assets": list(manifest.get("source_assets") or []) if isinstance(manifest, dict) else [],
        },
    }


def collect_variant_review(project_dir: Path, meta: dict[str, Any] | None) -> dict[str, Any]:
    """Build synchronized variant groups for the Review workspace."""
    meta = dict(meta or {})
    plan = meta.get("last_plan") if isinstance(meta.get("last_plan"), dict) else {}
    variants = [item for item in list(plan.get("variants") or []) if isinstance(item, dict)]
    plan_variant_count = len(variants)

    artifacts: list[dict[str, Any]] = []
    videos_dir = project_dir / "outputs" / "videos"
    images_dir = project_dir / "outputs" / "images"
    if videos_dir.exists():
        for media_path in sorted(videos_dir.glob("*"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            if media_path.suffix.lower() not in {".mp4", ".webm", ".mov"}:
                continue
            entry = _artifact_entry(project_dir, media_path, kind="video")
            if entry:
                artifacts.append(entry)
    if images_dir.exists():
        for media_path in sorted(images_dir.glob("*"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            if media_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            entry = _artifact_entry(project_dir, media_path, kind="image")
            if entry:
                artifacts.append(entry)

    grouped: dict[int, dict[str, Any]] = {}
    for index in range(max(plan_variant_count, 1)):
        variant = variants[index] if index < len(variants) else {}
        grouped[index] = {
            "variant_index": index,
            "label": str(variant.get("name") or variant.get("title") or f"Variant {index + 1}"),
            "mood": str(variant.get("mood") or ""),
            "scene_count": len(list(variant.get("scenes") or [])) if isinstance(variant.get("scenes"), list) else 0,
            "artifacts": [],
            "review_summary": {"approved": 0, "rejected": 0, "cherry_picked": 0, "unreviewed": 0},
        }

    for artifact in artifacts:
        index = int(artifact.get("variant_index") or 0)
        if index not in grouped:
            grouped[index] = {
                "variant_index": index,
                "label": f"Variant {index + 1}",
                "mood": "",
                "scene_count": 0,
                "artifacts": [],
                "review_summary": {"approved": 0, "rejected": 0, "cherry_picked": 0, "unreviewed": 0},
            }
        grouped[index]["artifacts"].append(artifact)
        state = str(artifact.get("review_state") or "unreviewed")
        if state not in grouped[index]["review_summary"]:
            state = "unreviewed"
        grouped[index]["review_summary"][state] = int(grouped[index]["review_summary"].get(state, 0)) + 1

    groups = [grouped[key] for key in sorted(grouped.keys())]
    compare_ready = any(len(group["artifacts"]) >= 2 for group in groups) or len(groups) >= 2
    return {
        "schemaVersion": VARIANT_REVIEW_SCHEMA_VERSION,
        "plan_variant_count": plan_variant_count,
        "artifact_count": len(artifacts),
        "compare_ready": compare_ready,
        "groups": groups,
        "notes": [
            "Compare variants with the same variant_index or across plan variants.",
            "Approval updates artifact manifests; rejected artifacts remain until cleanup policy expires.",
        ],
    }


def apply_variant_review_decision(
    project_dir: Path,
    *,
    artifact_path: str,
    decision: str,
    notes: str | None = None,
    cherry_pick_traits: list[str] | None = None,
    lock_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Persist review state on the artifact sidecar manifest."""
    state = str(decision or "").strip().lower()
    if state not in _REVIEW_STATES:
        raise ValueError(f"decision must be one of: {', '.join(sorted(_REVIEW_STATES))}")
    rel = str(artifact_path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("artifact_path is required")
    project_root = project_dir.resolve()
    media_path = (project_dir / rel).resolve()
    try:
        media_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("artifact_path must stay inside the project directory") from exc
    if not media_path.exists():
        raise ValueError("artifact media file not found")
    manifest_path = _artifact_manifest_path(media_path)
    manifest = _read_json(manifest_path) or {
        "schema_version": 1,
        "path": rel,
        "kind": "video" if media_path.suffix.lower() in {".mp4", ".webm", ".mov"} else "image",
        "review": {},
    }
    review = manifest.setdefault("review", {})
    if not isinstance(review, dict):
        review = {}
        manifest["review"] = review
    review["state"] = state
    review["notes"] = str(notes or "").strip()
    review["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if cherry_pick_traits:
        review["cherry_pick_traits"] = [str(item).strip() for item in cherry_pick_traits if str(item).strip()]
    if lock_fields:
        review["locks"] = [str(item).strip() for item in lock_fields if str(item).strip()]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(manifest_path)
    return {
        "ok": True,
        "artifact_path": rel,
        "manifest_path": str(manifest_path.relative_to(project_dir)).replace("\\", "/"),
        "review": review,
    }
