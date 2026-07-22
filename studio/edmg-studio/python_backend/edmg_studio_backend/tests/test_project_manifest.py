from __future__ import annotations

import json
from pathlib import Path

import pytest

from edmg_studio_backend.store.projects import (
    CURRENT_SCHEMA_VERSION,
    Project,
    ProjectStore,
    migrate_project_document,
    validate_project_document,
)


def test_validate_and_migrate_legacy_project_document() -> None:
    legacy = {
        "id": "abc123",
        "name": "Legacy",
        "created_at": "2026-01-01 00:00:00",
        "meta": {"timeline": {"layers": []}},
    }
    migrated, changed, applied = migrate_project_document(legacy)
    assert changed is True
    assert applied == [1]
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    validated = validate_project_document(migrated)
    assert validated["name"] == "Legacy"


def test_project_store_migrates_on_load_with_backup(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    project_id = "fixtureproj00000000000000000001"
    project_dir = store.project_dir(project_id)
    project_path = project_dir / "project.json"
    project_path.write_text(
        json.dumps(
            {
                "id": project_id,
                "name": "Needs Migration",
                "created_at": "2026-07-15 00:00:00",
                "meta": {"audio": {"filename": "a.wav", "size_bytes": 10}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = store.get(project_id)
    assert loaded is not None
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION
    saved = json.loads(project_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION
    backups = list(project_dir.glob("project.v0.*.bak.json"))
    assert len(backups) == 1


def test_project_store_save_is_atomic_and_versioned(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Atomic")
    proj.meta["width"] = 1280
    store.save(proj)

    path = store.project_dir(proj.id) / "project.json"
    assert not path.with_name("project.json.tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["meta"]["width"] == 1280
    assert store.get(proj.id) == Project(
        id=proj.id,
        name="Atomic",
        created_at=proj.created_at,
        meta={"width": 1280},
        schema_version=CURRENT_SCHEMA_VERSION,
    )


def test_unsupported_future_schema_is_rejected(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    project_id = "futureproj00000000000000000001"
    project_dir = store.project_dir(project_id)
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "id": project_id,
                "name": "Future",
                "created_at": "2026-07-15 00:00:00",
                "meta": {},
                "schema_version": CURRENT_SCHEMA_VERSION + 10,
            }
        ),
        encoding="utf-8",
    )
    assert store.get(project_id) is None


def test_project_store_rejects_project_id_path_traversal(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")

    with pytest.raises(ValueError, match="Invalid project identifier"):
        store.project_dir("../outside")

    assert not (tmp_path / "outside").exists()
