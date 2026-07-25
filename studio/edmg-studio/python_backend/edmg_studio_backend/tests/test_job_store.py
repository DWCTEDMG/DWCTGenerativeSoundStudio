from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from edmg_studio_backend.store.jobs import JobStore, _CORRUPTED_QUARANTINE_SUFFIX


def test_job_store_create_claim_and_idempotency(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "projects", db_path=tmp_path / "jobs.sqlite")
    first = store.create("proj1", "internal_video", {"fps": 24}, idempotency_key="render-a")
    second = store.create("proj1", "internal_video", {"fps": 30}, idempotency_key="render-a")
    assert first.id == second.id
    assert second.payload["fps"] == 24

    claimed = store.claim_next_queued(lease_seconds=60.0, owner="worker-1")
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "running"
    assert store.claim_next_queued() is None

    claimed.status = "succeeded"
    claimed.result = {"ok": True}
    store.save(claimed)
    events = store.list_events("proj1", first.id)
    assert any(e["event_type"] == "created" for e in events)
    assert any(e["event_type"] == "claimed" for e in events)
    store.close()


def test_job_store_migrates_json_and_recovers_expired_lease(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    job_dir = projects / "proj2" / "jobs"
    job_dir.mkdir(parents=True)
    legacy_id = "legacyjob00000000000000000001"
    (job_dir / f"{legacy_id}.json").write_text(
        '{"id":"%s","project_id":"proj2","type":"analyze","status":"queued",'
        '"created_at":"2026-07-15 00:00:00","updated_at":"2026-07-15 00:00:00",'
        '"payload":{"x":1}}' % legacy_id,
        encoding="utf-8",
    )
    store = JobStore(projects, db_path=tmp_path / "jobs.sqlite")
    migrated = store.get("proj2", legacy_id)
    assert migrated is not None
    assert migrated.type == "analyze"

    claimed = store.claim_next_queued(lease_seconds=0.05, owner="worker-temp")
    assert claimed is not None
    time.sleep(0.08)
    recovered = store.claim_next_queued(lease_seconds=30.0, owner="worker-2")
    assert recovered is not None
    assert recovered.id == claimed.id
    assert recovered.status == "running"
    store.close()


def test_job_store_cancel_retry_and_progress(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "projects", db_path=tmp_path / "jobs.sqlite")
    job = store.create("proj3", "layered_animation", {})
    store.update_progress("proj3", job.id, stage="frames", current=2, total=10, message="rendering")
    canceled = store.cancel("proj3", job.id)
    assert canceled is not None
    assert canceled.status == "canceled"
    retried = store.retry("proj3", job.id)
    assert retried is not None
    assert retried.status == "queued"
    assert retried.attempt == 1
    store.close()


def test_job_store_pauses_queued_work_without_letting_a_worker_claim_it(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "projects", db_path=tmp_path / "jobs.sqlite")
    job = store.create("proj4", "internal_video", {})

    paused = store.pause("proj4", job.id)
    assert paused is not None
    assert paused.status == "paused"
    assert store.claim_next_queued() is None

    resumed = store.resume("proj4", job.id)
    assert resumed is not None
    assert resumed.status == "queued"
    claimed = store.claim_next_queued(owner="worker-1")
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"

    event_types = [event["event_type"] for event in store.list_events("proj4", job.id)]
    assert "paused" in event_types
    assert "resumed" in event_types
    store.close()


def test_job_store_migrate_skips_unreadable_project_dirs(tmp_path: Path) -> None:
    """WinError 1392-style OSError on jobs_dir.exists() must not crash JobStore init."""
    projects = tmp_path / "projects"
    good = projects / "goodproj" / "jobs"
    good.mkdir(parents=True)
    legacy_id = "legacyjob00000000000000000002"
    (good / f"{legacy_id}.json").write_text(
        '{"id":"%s","project_id":"goodproj","type":"analyze","status":"queued",'
        '"created_at":"2026-07-15 00:00:00","updated_at":"2026-07-15 00:00:00",'
        '"payload":{}}' % legacy_id,
        encoding="utf-8",
    )
    bad = projects / "badproj"
    bad.mkdir()

    real_exists = Path.exists

    def exists_side_effect(self: Path) -> bool:
        # Simulate corrupt volume: listing yields the project, but jobs/ is unreadable.
        if self == bad / "jobs":
            raise OSError(1392, "The file or directory is corrupted and unreadable")
        return real_exists(self)

    with patch.object(Path, "exists", exists_side_effect):
        store = JobStore(projects, db_path=tmp_path / "jobs.sqlite")
    try:
        migrated = store.get("goodproj", legacy_id)
        assert migrated is not None
        quarantined = projects / f"badproj{_CORRUPTED_QUARANTINE_SUFFIX}"
        assert quarantined.is_dir()
        assert not (projects / "badproj").exists()
    finally:
        store.close()


def test_job_store_migrate_skips_already_quarantined_dirs(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    quarantined = projects / f"deadproj{_CORRUPTED_QUARANTINE_SUFFIX}"
    (quarantined / "jobs").mkdir(parents=True)
    (quarantined / "jobs" / "ignored.json").write_text("{}", encoding="utf-8")

    store = JobStore(projects, db_path=tmp_path / "jobs.sqlite")
    try:
        # Quarantined trees are skipped entirely (not double-renamed, not migrated).
        assert quarantined.is_dir()
        assert store.list_all() == []
    finally:
        store.close()
