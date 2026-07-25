from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore


def test_pause_and_resume_job_routes_require_the_expected_state(tmp_path: Path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Queue controls")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    job = jobs.create(project.id, "internal_video", {})

    with TestClient(backend_app.app) as client:
        paused = client.post(f"/v1/projects/{project.id}/jobs/{job.id}/pause")
        assert paused.status_code == 200
        assert paused.json()["job"]["status"] == "paused"

        checkpoint_resume = client.post(
            f"/v1/projects/{project.id}/jobs/{job.id}/resume_from_checkpoint",
        )
        assert checkpoint_resume.status_code == 409

        resumed = client.post(f"/v1/projects/{project.id}/jobs/{job.id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["job"]["status"] == "queued"

        invalid_resume = client.post(f"/v1/projects/{project.id}/jobs/{job.id}/resume")
        assert invalid_resume.status_code == 409

        claimed = jobs.claim_next_queued(owner="test-worker")
        assert claimed is not None
        cannot_pause_running = client.post(f"/v1/projects/{project.id}/jobs/{job.id}/pause")
        assert cannot_pause_running.status_code == 409
