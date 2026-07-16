from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
_CORRUPTED_QUARANTINE_SUFFIX = ".__corrupted_quarantine"


@dataclass
class Project:
    id: str
    name: str
    created_at: str
    meta: dict[str, Any]
    schema_version: int = CURRENT_SCHEMA_VERSION


MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Promote pre-versioned project.json documents to schema_version 1."""
    next_data = dict(data)
    next_data["schema_version"] = 1
    meta = dict(next_data.get("meta") or {})
    next_data["meta"] = meta
    return next_data


# Target version -> migration from previous version.
PROJECT_MIGRATIONS: dict[int, MigrationFn] = {
    1: _migrate_v0_to_v1,
}


def validate_project_document(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Project document must be an object")
    project_id = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    created_at = str(data.get("created_at") or "").strip()
    if not project_id:
        raise ValueError("Project document is missing id")
    if not name:
        raise ValueError("Project document is missing name")
    if not created_at:
        raise ValueError("Project document is missing created_at")
    meta = data.get("meta")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ValueError("Project meta must be an object")
    schema_version = int(data.get("schema_version") or 0)
    if schema_version < 0:
        raise ValueError("schema_version must be >= 0")
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported project schema_version {schema_version}; "
            f"this Studio build supports up to {CURRENT_SCHEMA_VERSION}"
        )
    return {
        "id": project_id,
        "name": name,
        "created_at": created_at,
        "meta": meta,
        "schema_version": schema_version,
    }


def migrate_project_document(data: dict[str, Any]) -> tuple[dict[str, Any], bool, list[int]]:
    """Return (document, changed, applied_versions)."""
    current = validate_project_document(data)
    applied: list[int] = []
    version = int(current.get("schema_version") or 0)
    changed = False
    while version < CURRENT_SCHEMA_VERSION:
        target = version + 1
        migrator = PROJECT_MIGRATIONS.get(target)
        if migrator is None:
            raise ValueError(f"No migration registered for project schema_version {target}")
        current = validate_project_document(migrator(current))
        version = int(current["schema_version"])
        applied.append(target)
        changed = True
    if int(current["schema_version"]) != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Project migration stopped at schema_version {current['schema_version']}"
        )
    return current, changed, applied


class ProjectStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.projects_dir = self.base_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _proj_dir(self, project_id: str) -> Path:
        d = self.projects_dir / project_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "assets" / "audio").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "overlays").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "masks").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        (d / "analysis").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "images").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "videos").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "deforum").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "unreal").mkdir(parents=True, exist_ok=True)
        (d / "jobs").mkdir(parents=True, exist_ok=True)
        return d

    def _project_path(self, project_id: str) -> Path:
        return self.projects_dir / project_id / "project.json"

    def _backup_before_migration(self, project_path: Path, from_version: int) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = project_path.with_name(f"project.v{from_version}.{stamp}.bak.json")
        shutil.copy2(project_path, backup)
        return backup

    def _write_atomic(self, project_path: Path, payload: dict[str, Any]) -> None:
        project_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = project_path.with_name(project_path.name + ".tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, project_path)

    def _to_project(self, data: dict[str, Any]) -> Project:
        validated = validate_project_document(data)
        return Project(
            id=validated["id"],
            name=validated["name"],
            created_at=validated["created_at"],
            meta=dict(validated["meta"]),
            schema_version=int(validated["schema_version"]),
        )

    def _load_document(self, project_id: str, *, persist_migrations: bool = True) -> dict[str, Any] | None:
        project_path = self._project_path(project_id)
        try:
            if not project_path.exists():
                return None
            raw = json.loads(project_path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("Unreadable project document %s: %s", project_path, exc)
            return None
        from_version = int((raw or {}).get("schema_version") or 0)
        migrated, changed, _applied = migrate_project_document(raw)
        if changed and persist_migrations:
            self._backup_before_migration(project_path, from_version)
            self._write_atomic(project_path, migrated)
        return migrated

    def list(self) -> list[Project]:
        out: list[Project] = []
        try:
            entries = sorted(self.projects_dir.iterdir())
        except OSError as exc:
            logger.warning("Cannot list projects directory %s: %s", self.projects_dir, exc)
            return out
        for d in entries:
            if d.name.endswith(_CORRUPTED_QUARANTINE_SUFFIX):
                continue
            try:
                if not d.is_dir():
                    continue
                data = self._load_document(d.name)
                if data is None:
                    continue
                out.append(self._to_project(data))
            except OSError as exc:
                logger.warning("Skipping unreadable project directory %s: %s", d, exc)
                continue
            except Exception:
                continue
        return out

    def create(self, name: str) -> Project:
        pid = uuid.uuid4().hex
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        proj = Project(
            id=pid,
            name=name,
            created_at=created_at,
            meta={},
            schema_version=CURRENT_SCHEMA_VERSION,
        )
        self.save(proj)
        self._proj_dir(pid)
        return proj

    def get(self, project_id: str) -> Project | None:
        try:
            data = self._load_document(project_id)
        except Exception:
            return None
        if data is None:
            return None
        return self._to_project(data)

    def save(self, proj: Project) -> None:
        d = self._proj_dir(proj.id)
        target = d / "project.json"
        schema_version = int(getattr(proj, "schema_version", CURRENT_SCHEMA_VERSION) or CURRENT_SCHEMA_VERSION)
        if schema_version != CURRENT_SCHEMA_VERSION:
            migrated, _, _ = migrate_project_document(
                {
                    "id": proj.id,
                    "name": proj.name,
                    "created_at": proj.created_at,
                    "meta": proj.meta,
                    "schema_version": schema_version,
                }
            )
            payload = migrated
            proj.schema_version = CURRENT_SCHEMA_VERSION
            proj.meta = dict(migrated["meta"])
        else:
            payload = {
                "id": proj.id,
                "name": proj.name,
                "created_at": proj.created_at,
                "meta": proj.meta,
                "schema_version": CURRENT_SCHEMA_VERSION,
            }
        validate_project_document(payload)
        self._write_atomic(target, payload)

    def project_dir(self, project_id: str) -> Path:
        return self._proj_dir(project_id)

    def set_audio(self, project_id: str, filename: str, bytes_len: int) -> None:
        proj = self.get(project_id)
        if not proj:
            raise KeyError("Project not found")
        proj.meta["audio"] = {"filename": filename, "size_bytes": bytes_len}
        self.save(proj)
