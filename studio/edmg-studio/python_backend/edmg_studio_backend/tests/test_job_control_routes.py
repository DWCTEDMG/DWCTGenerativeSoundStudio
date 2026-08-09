from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore


def test_execute_job_preserves_curated_error_and_terminalizes_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Curated failure")
    checkpoint_rel = "outputs/videos/render.checkpoint.json"
    checkpoint_path = store.project_dir(project.id) / checkpoint_rel
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "status": "running",
        "stage": "video_model",
        "total_frames": 24,
        "completed_frames": 0,
        "can_resume": True,
        "resume_recommended": True,
        "outputs": {"checkpoint_json": checkpoint_rel, "final_exists": False},
    }
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    job = jobs.create(project.id, "internal_video", {})
    job.progress = {"runtime_checkpoint": checkpoint}
    jobs.save(job)

    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(
        backend_app,
        "_run_internal_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UserFacingError(
                "Selected model does not match its engine",
                hint="Choose the matching SVD or AnimateDiff model.",
                code="INTERNAL_VIDEO_MODEL_ENGINE_MODEL_MISMATCH",
            )
        ),
    )

    backend_app._execute_job(job)

    saved = jobs.get(project.id, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.error is not None
    assert "Selected model does not match its engine" in saved.error
    assert "Fix: Choose the matching SVD or AnimateDiff model." in saved.error
    assert "Code: INTERNAL_VIDEO_MODEL_ENGINE_MODEL_MISMATCH" in saved.error
    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert saved_checkpoint["status"] == "failed"
    assert saved_checkpoint["stage"] == "failed"
    assert saved_checkpoint["can_resume"] is False
    assert saved_checkpoint["resume_recommended"] is False
    assert saved.progress is not None
    assert saved.progress["stage"] == "failed"
    assert saved.progress["message"] == "Selected model does not match its engine"


def test_execute_job_redacts_unhandled_render_exception(tmp_path: Path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Generic failure")
    job = jobs.create(project.id, "internal_video", {})
    secret = "token=do-not-leak path=C:\\private\\model"

    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(
        backend_app,
        "_run_internal_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    backend_app._execute_job(job)

    saved = jobs.get(project.id, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.error == "Render job failed."
    assert "do-not-leak" not in jobs.log_path(project.id, job.id).read_text(encoding="utf-8")


def test_execute_job_terminalizes_outer_progress_without_runtime_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Early failure")
    job = jobs.create(project.id, "internal_video", {})
    job.progress = {
        "stage": "queued",
        "current": 0,
        "total": 24,
        "percent": 0.0,
        "message": "Queued",
    }
    jobs.save(job)

    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(
        backend_app,
        "_run_internal_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("early crash")),
    )

    backend_app._execute_job(job)

    saved = jobs.get(project.id, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.progress is not None
    assert saved.progress["stage"] == "failed"
    assert saved.progress["message"] == "Render job failed."
    assert saved.progress["current"] == 0
    assert saved.progress["percent"] == 0.0
    assert "runtime_checkpoint" not in saved.progress


def test_generic_internal_retry_repairs_legacy_video_model_pair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Legacy retry")
    source = jobs.create(
        project.id,
        "internal_video",
        {
            "model_id": "hf_sd15_internal",
            "temporal_mode": "video_model",
            "video_model_engine": "svd",
            "video_model_id": backend_app.INTERNAL_ANIMATEDIFF_VIDEO_MODEL_ID,
        },
    )
    source.status = "failed"
    jobs.save(source)
    captured: dict[str, object] = {}

    def fake_preflight(_project_id: str, payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {
            "mode": "diffusion",
            "model_id": "hf_sd15_internal",
            "estimated_frames": 24,
            "settings": {
                "temporal_mode": "video_model",
                "temporal_steps": 6,
                "video_model_engine": "svd",
                "video_model_id": backend_app.INTERNAL_SVD_VIDEO_MODEL_ID,
                "video_model_max_frames_per_scene": 8,
                "video_model_decode_chunk_size": 1,
                "video_model_cpu_offload": True,
            },
        }

    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(backend_app, "_internal_render_preflight_data", fake_preflight)

    with TestClient(backend_app.app) as client:
        response = client.post(f"/v1/projects/{project.id}/jobs/{source.id}/retry")

    assert response.status_code == 200
    assert captured["video_model_engine"] == "svd"
    assert captured["video_model_id"] == backend_app.INTERNAL_SVD_VIDEO_MODEL_ID
    saved = jobs.get(project.id, source.id)
    assert saved is not None
    assert saved.status == "queued"
    assert saved.payload["video_model_engine"] == "svd"
    assert saved.payload["video_model_id"] == backend_app.INTERNAL_SVD_VIDEO_MODEL_ID
    assert saved.payload["temporal_steps"] == 6
    assert "Normalized legacy" in jobs.log_path(project.id, source.id).read_text(encoding="utf-8")


def test_generic_retry_rejects_active_jobs_before_mutating_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Active retry guard")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    preflight_called = False

    def fail_preflight(*_args, **_kwargs):
        nonlocal preflight_called
        preflight_called = True
        raise AssertionError("active jobs must be rejected before preflight")

    monkeypatch.setattr(backend_app, "_internal_render_preflight_data", fail_preflight)

    with TestClient(backend_app.app) as client:
        for status in ("queued", "paused", "running"):
            source = jobs.create(
                project.id,
                "internal_video",
                {
                    "video_model_engine": "svd",
                    "video_model_id": backend_app.INTERNAL_ANIMATEDIFF_VIDEO_MODEL_ID,
                },
            )
            source.status = status
            jobs.save(source)
            original_payload = dict(source.payload)

            response = client.post(f"/v1/projects/{project.id}/jobs/{source.id}/retry")

            assert response.status_code == 409
            saved = jobs.get(project.id, source.id)
            assert saved is not None
            assert saved.status == status
            assert saved.payload == original_payload

    assert preflight_called is False


def test_unexpected_render_worker_exit_terminalizes_resumable_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Worker crash")
    checkpoint_rel = "outputs/videos/crash.checkpoint.json"
    checkpoint_path = store.project_dir(project.id) / checkpoint_rel
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "status": "running",
        "stage": "frames",
        "total_frames": 24,
        "completed_frames": 6,
        "can_resume": True,
        "resume_recommended": True,
        "outputs": {"checkpoint_json": checkpoint_rel, "final_exists": False},
    }
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    job = jobs.create(project.id, "internal_video", {})
    job.progress = {
        "stage": "frames",
        "current": 6,
        "total": 24,
        "percent": 25.0,
        "message": "Rendering frame 6/24",
        "runtime_checkpoint": checkpoint,
    }
    jobs.save(job)

    class FailedProcess:
        returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(
        backend_app.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FailedProcess(),
    )
    monkeypatch.setattr(
        backend_app,
        "_render_worker_command",
        lambda *_args, **_kwargs: ["fake-render-worker"],
    )

    backend_app._run_job_in_subprocess(job)

    saved = jobs.get(project.id, job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.error == "Render worker process exited unexpectedly (exit code -9)."
    assert saved.progress is not None
    assert saved.progress["stage"] == "failed"
    assert saved.progress["current"] == 6
    assert saved.progress["percent"] == 25.0
    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert saved_checkpoint["status"] == "failed"
    assert saved_checkpoint["completed_frames"] == 6
    assert saved_checkpoint["can_resume"] is True
    assert saved_checkpoint["resume_recommended"] is True


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
