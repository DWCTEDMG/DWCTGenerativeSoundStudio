from __future__ import annotations

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.provider_generation import (
    generation_provider_definitions,
    normalized_generation_job,
)
from edmg_studio_backend.schemas import GenerationRequest
from edmg_studio_backend.store.jobs import Job, JobStore
from edmg_studio_backend.store.projects import ProjectStore
from edmg_studio_backend.tests.revision_client import TestClient


def test_generation_request_preserves_internal_render_parameters() -> None:
    request = GenerationRequest.model_validate(
        {
            "provider_id": "edmg.internal",
            "renderer_id": "ltx_25",
            "priority": 50,
            "parameters": {
                "temporal_mode": "video_model",
                "video_model_engine": "ltx_25",
                "video_model_id": "hf_ltx_25_distilled_internal",
                "parseq_manifest": {"rendered_frames": [0, 12]},
            },
        }
    )

    assert request.parameters.video_model_engine == "ltx_25"
    assert request.parameters.parseq_manifest == {"rendered_frames": [0, 12]}
    assert request.priority == 50


def test_generation_request_rejects_unadvertised_renderer() -> None:
    try:
        GenerationRequest.model_validate({"renderer_id": "legacy_renderer"})
    except ValueError:
        pass
    else:
        raise AssertionError("unadvertised renderers must be rejected")


def test_normalized_generation_job_maps_provider_state_and_artifact() -> None:
    job = Job(
        id="job-1",
        project_id="project-1",
        type="internal_video",
        status="succeeded",
        created_at="2026-09-13 12:00:00",
        updated_at="2026-09-13 12:01:00",
        payload={
            "_generation": {
                "provider_id": "edmg.internal",
                "renderer_id": "hunyuan_video15",
                "operation": "video",
            }
        },
        result={"artifact": {"kind": "video", "path": "outputs/final.mp4"}},
        progress={"percent": 100, "stage": "complete"},
    )

    normalized = normalized_generation_job(job)

    assert normalized["provider_id"] == "edmg.internal"
    assert normalized["renderer_id"] == "hunyuan_video15"
    assert normalized["status"] == "succeeded"
    assert normalized["artifacts"] == [{"kind": "video", "path": "outputs/final.mp4"}]


def test_provider_definition_reports_canonical_internal_capabilities() -> None:
    definitions = generation_provider_definitions({"hardware": {"backend": "cuda"}})

    provider = definitions["providers"][0]
    assert provider["id"] == "edmg.internal"
    assert provider["ready"] is True
    assert provider["hardware_backend"] == "cuda"
    assert "durable_queue" in provider["capabilities"]


def test_generation_submission_persists_normalized_metadata_priority_and_idempotency(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Normalized generation")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backend_app,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {
            "mode": "hosted",
            "model_id": "hosted",
            "estimated_frames": 24,
        },
    )
    request = {
        "provider_id": "edmg.internal",
        "renderer_id": "ltx_25",
        "idempotency_key": "generation-1",
        "priority": 42,
        "parameters": {"video_model_engine": "hunyuan_video15"},
    }

    with TestClient(backend_app.app) as client:
        first = client.post(f"/v1/projects/{project.id}/generation", json=request)
        second = client.post(f"/v1/projects/{project.id}/generation", json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    first_generation = first.json()["generation"]
    assert second.json()["generation"]["job_id"] == first_generation["job_id"]
    assert first_generation["provider_id"] == "edmg.internal"
    assert first_generation["renderer_id"] == "ltx_25"
    assert first_generation["priority"] == 42
    saved = jobs.get(project.id, first_generation["job_id"])
    assert saved is not None
    assert saved.payload["_generation"]["provider_id"] == "edmg.internal"
    assert saved.payload["_generation"]["renderer_id"] == "ltx_25"
    assert saved.payload["video_model_engine"] == "ltx_25"
    assert saved.payload["temporal_mode"] == "video_model"
    assert len(jobs.list_for_project(project.id)) == 1
    assert len(store.get(project.id).meta["jobs"]) == 1


def test_idempotent_generation_replay_skips_changed_preflight(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Idempotent replay")
    existing = jobs.create(
        project.id,
        "internal_video",
        {"_generation": {"provider_id": "edmg.internal", "renderer_id": "auto"}},
        idempotency_key="accepted-request",
    )
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backend_app,
        "_internal_render_preflight_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preflight must not run")),
    )

    with TestClient(backend_app.app) as client:
        response = client.post(
            f"/v1/projects/{project.id}/generation",
            json={"idempotency_key": "accepted-request"},
        )

    assert response.status_code == 200
    assert response.json()["generation"]["job_id"] == existing.id
    assert response.json()["preflight"] == {}


def test_generation_submission_rejects_invalid_contract_and_missing_project() -> None:
    with TestClient(backend_app.app) as client:
        invalid_provider = client.post(
            "/v1/projects/missing/generation",
            json={"provider_id": "legacy.provider"},
        )
        invalid_operation = client.post(
            "/v1/projects/missing/generation",
            json={"operation": "image"},
        )
        missing_project = client.post(
            "/v1/projects/missing/generation",
            json={"provider_id": "edmg.internal", "operation": "video"},
        )

    assert invalid_provider.status_code == 422
    assert invalid_operation.status_code == 422
    assert missing_project.status_code == 404
