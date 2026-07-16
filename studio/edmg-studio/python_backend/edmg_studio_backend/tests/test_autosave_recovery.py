from __future__ import annotations

import json
from pathlib import Path

from edmg_studio_backend.store.autosave import AutosaveJournal
from edmg_studio_backend.store.projects import ProjectStore


def test_autosave_journal_recovers_after_forced_interrupt(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Crash Recovery")
    journal = AutosaveJournal(store.project_dir(proj.id))

    dirty_meta = {
        "timeline": {"layers": [{"id": "L1", "name": "unsaved layer"}]},
        "audio": {"filename": "tone.wav", "size_bytes": 128},
    }
    journal.write_journal(project_id=proj.id, meta=dirty_meta, reason="timeline_edit", dirty=True)
    journal.write_snapshot(project_id=proj.id, meta=dirty_meta, reason="pre_crash")

    # Simulate process death before project.json catch-up: committed file stays older.
    committed = store.get(proj.id)
    assert committed is not None
    assert committed.meta.get("timeline") in (None, {})

    candidate = journal.latest_valid_recovery()
    assert candidate is not None
    assert candidate.kind == "journal"
    recovered_meta = candidate.payload["meta"]
    assert recovered_meta["timeline"]["layers"][0]["id"] == "L1"

    # Apply recovery into the durable project manifest.
    committed.meta = dict(recovered_meta)
    store.save(committed)
    journal.mark_clean()

    reopened = store.get(proj.id)
    assert reopened is not None
    assert reopened.meta["timeline"]["layers"][0]["name"] == "unsaved layer"
    assert journal.read_journal()["dirty"] is False


def test_corrupt_journal_falls_back_to_snapshot(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Snapshot Fallback")
    journal = AutosaveJournal(store.project_dir(proj.id))
    good = {"timeline": {"layers": [{"id": "ok"}]}}
    journal.write_snapshot(project_id=proj.id, meta=good, reason="checkpoint")
    journal.journal_path.write_text("{not-json", encoding="utf-8")

    candidate = journal.latest_valid_recovery()
    assert candidate is not None
    assert candidate.kind == "snapshot"
    assert candidate.payload["meta"]["timeline"]["layers"][0]["id"] == "ok"
