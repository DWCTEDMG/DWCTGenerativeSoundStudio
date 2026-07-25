from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AssetRecord:
    path: str
    role: str
    exists: bool
    bytes: int | None
    sha256: str | None
    referenced: bool


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path, project_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_dir.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def build_asset_index(project_dir: Path, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Index project media and report missing/changed references."""
    meta = dict(meta or {})
    assets_root = project_dir / "assets"
    records: list[AssetRecord] = []
    referenced: set[str] = set()

    audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
    audio_name = str(audio.get("filename") or "").strip()
    if audio_name:
        referenced.add(f"assets/audio/{Path(audio_name).name}")

    timeline = meta.get("timeline") if isinstance(meta.get("timeline"), dict) else {}
    for layer in timeline.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        for key in ("path", "file", "src", "overlay"):
            val = layer.get(key)
            if isinstance(val, str) and val.strip():
                referenced.add(val.replace("\\", "/").lstrip("./"))

    if assets_root.exists():
        for path in assets_root.rglob("*"):
            if not path.is_file():
                continue
            rel = _rel(path, project_dir)
            role = "audio" if "/audio/" in rel.replace("\\", "/") else "asset"
            records.append(
                AssetRecord(
                    path=rel,
                    role=role,
                    exists=True,
                    bytes=path.stat().st_size,
                    sha256=_sha256_file(path),
                    referenced=rel in referenced or any(rel.endswith(r.split("/")[-1]) for r in referenced),
                )
            )

    missing: list[dict[str, Any]] = []
    for ref in sorted(referenced):
        target = (project_dir / ref).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except Exception:
            missing.append({"path": ref, "reason": "outside_project"})
            continue
        if not target.exists():
            missing.append({"path": ref, "reason": "missing"})
            if not any(r.path == ref for r in records):
                records.append(
                    AssetRecord(
                        path=ref,
                        role="audio" if ref.startswith("assets/audio/") else "asset",
                        exists=False,
                        bytes=None,
                        sha256=None,
                        referenced=True,
                    )
                )

    total_bytes = sum(int(r.bytes or 0) for r in records if r.exists)
    return {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "asset_count": len(records),
        "missing_count": len(missing),
        "total_bytes": total_bytes,
        "disk_estimate_gb": round(total_bytes / (1024**3), 4),
        "missing": missing,
        "assets": [
            {
                "path": r.path,
                "role": r.role,
                "exists": r.exists,
                "bytes": r.bytes,
                "sha256": r.sha256,
                "referenced": r.referenced,
            }
            for r in records
        ],
    }


def assess_project_health(project_dir: Path, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    index = build_asset_index(project_dir, meta)
    issues: list[dict[str, str]] = []
    for miss in index.get("missing") or []:
        issues.append(
            {
                "code": "missing_asset",
                "severity": "error",
                "message": f"Missing asset: {miss.get('path')}",
            }
        )
    journal = project_dir / "autosave.journal.json"
    if journal.exists():
        try:
            data = json.loads(journal.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("dirty"):
                issues.append(
                    {
                        "code": "dirty_autosave",
                        "severity": "warning",
                        "message": "Unsaved autosave journal is present",
                    }
                )
        except Exception:
            issues.append(
                {
                    "code": "corrupt_autosave",
                    "severity": "warning",
                    "message": "Autosave journal is unreadable",
                }
            )
    status = "ok"
    if any(i["severity"] == "error" for i in issues):
        status = "error"
    elif issues:
        status = "warning"
    return {
        "ok": status == "ok",
        "status": status,
        "issues": issues,
        "asset_index": index,
        "actions": [
            "relink_missing",
            "cleanup_unreferenced",
            "collect_project",
        ],
    }


def collect_project_bundle(project_dir: Path, dest_dir: Path) -> dict[str, Any]:
    """Copy project files into a portable bundle directory (best-effort)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel(path, project_dir)
        if "/frames_internal/" in rel.replace("\\", "/") or "/previews/" in rel.replace("\\", "/"):
            skipped.append(rel)
            continue
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            copied.append(rel)
        except OSError:
            skipped.append(rel)
    return {
        "ok": True,
        "dest": str(dest_dir),
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "copied": copied[:200],
        "skipped": skipped[:200],
    }


def suggest_relinks(project_dir: Path, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Suggest replacements for missing referenced assets by filename match."""
    index = build_asset_index(project_dir, meta)
    suggestions: list[dict[str, str]] = []
    present = {
        Path(a["path"]).name: a["path"]
        for a in index.get("assets") or []
        if a.get("exists")
    }
    for miss in index.get("missing") or []:
        name = Path(str(miss.get("path") or "")).name
        if name and name in present:
            suggestions.append({"missing": str(miss.get("path")), "candidate": present[name]})
    return {"ok": True, "suggestions": suggestions, "missing_count": index.get("missing_count", 0)}
