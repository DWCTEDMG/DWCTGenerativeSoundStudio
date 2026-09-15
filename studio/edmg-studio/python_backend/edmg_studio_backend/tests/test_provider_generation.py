from __future__ import annotations

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.provider_generation import (
    generation_provider_definitions,
    normalize_provider_result,
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


def test_generation_request_validates_effective_hunyuan_chunk_geometry() -> None:
    try:
        GenerationRequest.model_validate(
            {
                "renderer_id": "hunyuan_video15",
                "parameters": {
                    "hunyuan_chunk_frames": 2,
                    "hunyuan_chunk_overlap": 2,
                },
            }
        )
    except ValueError as error:
        assert "chunk overlap must be smaller" in str(error)
    else:
        raise AssertionError("renderer-level Hunyuan selection must validate chunk geometry")

    ltx_request = GenerationRequest.model_validate(
        {
            "renderer_id": "ltx_25",
            "parameters": {
                "video_model_engine": "hunyuan_video15",
                "hunyuan_chunk_frames": 2,
                "hunyuan_chunk_overlap": 2,
            },
        }
    )
    assert ltx_request.parameters.video_model_engine == "ltx_25"

    try:
        GenerationRequest.model_validate(
            {"renderer_id": "hunyuan_video15", "parameters": None}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("explicit malformed generation parameters must be rejected")


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


def test_provider_definitions_are_complete_and_readiness_isolated() -> None:
    definitions = generation_provider_definitions(
        {
            "hardware": {"backend": "cpu"},
            "comfyui": {"ready": False, "detail": "offline"},
            "firefly": {"configured": True, "enabled": True},
            "stability": {"configured": False, "enabled": True},
            "imagineart": {"configured": True, "enabled": True},
            "cosmos": {"configured": True, "enabled": True},
            "azure_foundry": {"configured": True, "enabled": True, "has_api_key": True},
        }
    )

    providers = {provider["id"]: provider for provider in definitions["providers"]}
    assert set(providers) == {
        "edmg.internal", "comfyui", "stability", "adobe.firefly", "imagineart",
        "nvidia.cosmos", "azure.foundry.cosmos",
    }
    assert providers["comfyui"]["ready"] is False
    assert providers["adobe.firefly"]["ready"] is True
    assert providers["stability"]["ready"] is False
    assert providers["azure.foundry.cosmos"]["ready"] is True


def test_generation_request_rejects_credentials_recursively() -> None:
    for parameters in (
        {"api_key": "forbidden"},
        {"nested": {"client-secret": "forbidden"}},
        {"items": [{"authorization": "Bearer forbidden"}]},
    ):
        try:
            GenerationRequest.model_validate(
                {"provider_id": "stability", "operation": "image", "parameters": parameters}
            )
        except ValueError as error:
            assert "Credential-like field" in str(error)
        else:
            raise AssertionError("credentials must never enter durable generation payloads")


def test_provider_result_preserves_multiple_artifacts_failures_usage_and_cost() -> None:
    result = normalize_provider_result(
        "adobe.firefly",
        "image",
        {
            "results": [
                {"ok": True, "path": "stills/one.png", "scene_index": 0, "generation_id": "gen-1"},
                {"ok": False, "scene_index": 1, "error": "policy rejected", "code": "POLICY"},
            ],
            "usage": {"images": 1},
            "cost": {"amount": 0.04, "currency": "USD"},
        },
    )

    assert result["partial_failure"] is True
    assert result["artifacts"][0]["provider_generation_id"] == "gen-1"
    assert result["failures"] == [{"message": "policy rejected", "scene_index": 1, "code": "POLICY"}]
    assert result["usage"] == {"images": 1}
    assert result["cost"]["currency"] == "USD"


def test_provider_result_preserves_user_facing_failure_message() -> None:
    result = normalize_provider_result(
        "stability",
        "image",
        {"results": [{"ok": False, "scene_index": 0, "message": "quota exhausted", "code": "QUOTA"}]},
    )

    assert result["failures"] == [{"message": "quota exhausted", "scene_index": 0, "code": "QUOTA"}]


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
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backend_app,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {"mode": "hosted", "model_id": "hosted", "estimated_frames": 1},
    )

    with TestClient(backend_app.app) as client:
        accepted = client.post(
            f"/v1/projects/{project.id}/generation",
            json={"idempotency_key": "accepted-request"},
        )
    existing_job_id = accepted.json()["generation"]["job_id"]

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
    assert response.json()["generation"]["job_id"] == existing_job_id
    assert response.json()["preflight"] == {}


def test_hosted_generation_submission_is_durable_and_idempotent(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Hosted generation")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    request = {
        "provider_id": "adobe.firefly",
        "operation": "image",
        "idempotency_key": "hosted-generation-1",
        "priority": 18,
        "parameters": {"variant_index": 0, "width": 768, "height": 432},
    }

    with TestClient(backend_app.app) as client:
        first = client.post(f"/v1/projects/{project.id}/generation", json=request)
        second = client.post(f"/v1/projects/{project.id}/generation", json=request)
        project_jobs = client.get(f"/v1/projects/{project.id}/generation/jobs")
        all_jobs = client.get("/v1/generation/jobs")

    assert first.status_code == 200
    assert second.status_code == 200
    generation = first.json()["generation"]
    assert generation["job_id"] == second.json()["generation"]["job_id"]
    assert generation["provider_id"] == "adobe.firefly"
    assert generation["operation"] == "image"
    saved = jobs.get(project.id, generation["job_id"])
    assert saved is not None
    assert saved.type == "provider_generation"
    assert saved.payload["_generation"]["provider_id"] == "adobe.firefly"
    assert len(jobs.list_for_project(project.id)) == 1
    assert [item["job_id"] for item in project_jobs.json()["jobs"]] == [generation["job_id"]]
    assert generation["job_id"] in {item["job_id"] for item in all_jobs.json()["jobs"]}


def test_hosted_generation_rejects_idempotency_collision(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Hosted collision")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)

    with TestClient(backend_app.app) as client:
        first = client.post(
            f"/v1/projects/{project.id}/generation",
            json={
                "provider_id": "stability",
                "operation": "image",
                "idempotency_key": "collision",
                "parameters": {"variant_index": 0},
            },
        )
        collision = client.post(
            f"/v1/projects/{project.id}/generation",
            json={
                "provider_id": "stability",
                "operation": "image",
                "idempotency_key": "collision",
                "parameters": {"variant_index": 1},
            },
        )

    assert first.status_code == 200
    assert collision.status_code == 409


def test_comfyui_generation_replays_children_with_priority_and_rejects_collision(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("ComfyUI generation")
    project.meta["last_plan"] = {
        "variants": [{"scenes": [{"prompt": "first"}, {"prompt": "second"}]}]
    }
    store.save(project)
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    request = {
        "provider_id": "comfyui",
        "operation": "image",
        "idempotency_key": "comfy-batch",
        "priority": 37,
        "parameters": {"variant_index": 0, "width": 768, "height": 432},
    }

    with TestClient(backend_app.app) as client:
        first = client.post(f"/v1/projects/{project.id}/generation", json=request)
        replay = client.post(f"/v1/projects/{project.id}/generation", json=request)
        collision = client.post(
            f"/v1/projects/{project.id}/generation",
            json={**request, "parameters": {**request["parameters"], "width": 1024}},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert collision.status_code == 409
    first_jobs = first.json()["generations"]
    assert [item["job_id"] for item in replay.json()["generations"]] == [
        item["job_id"] for item in first_jobs
    ]
    assert len(first_jobs) == 2
    assert all(item["priority"] == 37 for item in first_jobs)
    assert len(jobs.list_for_project(project.id)) == 2


def test_comfyui_generation_collision_does_not_create_partial_batch(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("ComfyUI atomic collision")
    project.meta["last_plan"] = {
        "variants": [{"scenes": [{"prompt": "first"}, {"prompt": "second"}]}]
    }
    store.save(project)
    jobs.create(
        project.id,
        "comfyui_scene",
        {"different": True},
        idempotency_key="comfy-atomic:scene:0001",
    )
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)

    with TestClient(backend_app.app) as client:
        response = client.post(
            f"/v1/projects/{project.id}/generation",
            json={
                "provider_id": "comfyui",
                "operation": "image",
                "idempotency_key": "comfy-atomic",
                "parameters": {"variant_index": 0},
            },
        )

    assert response.status_code == 409
    persisted = jobs.list_for_project(project.id)
    assert len(persisted) == 1
    assert persisted[0].idempotency_key == "comfy-atomic:scene:0001"


def test_legacy_comfyui_route_keeps_plain_request_body(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Legacy ComfyUI route")
    project.meta["last_plan"] = {"variants": [{"scenes": [{"prompt": "first"}]}]}
    store.save(project)
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)

    with TestClient(backend_app.app) as client:
        response = client.post(
            f"/v1/projects/{project.id}/render/comfyui/scenes",
            json={"variant_index": 0},
        )

    assert response.status_code == 200
    assert response.json()["enqueued"] == 1


def test_comfyui_replay_repairs_project_job_mirror(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("ComfyUI mirror repair")
    project.meta["last_plan"] = {"variants": [{"scenes": [{"prompt": "first"}]}]}
    store.save(project)
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    request = {
        "provider_id": "comfyui",
        "operation": "image",
        "idempotency_key": "comfy-mirror",
        "parameters": {"variant_index": 0},
    }

    with TestClient(backend_app.app) as client:
        first = client.post(f"/v1/projects/{project.id}/generation", json=request)
        store.mutate(project.id, lambda current: current.meta.__setitem__("jobs", []))
        replay = client.post(f"/v1/projects/{project.id}/generation", json=request)

    assert first.status_code == 200
    assert replay.status_code == 200
    repaired = store.get(project.id)
    assert repaired is not None
    assert [item["id"] for item in repaired.meta["jobs"]] == [first.json()["generation"]["job_id"]]


def test_stale_generation_revision_is_rejected_before_queue_commit(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Stale generation")
    project.meta["last_plan"] = {"variants": [{"scenes": [{"prompt": "first"}]}]}
    store.save(project)
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)

    with TestClient(backend_app.app) as client:
        response = client.post(
            f"/v1/projects/{project.id}/generation",
            headers={"If-Match": str(project.revision - 1)},
            json={
                "provider_id": "comfyui",
                "operation": "image",
                "idempotency_key": "stale-generation",
                "parameters": {"variant_index": 0},
            },
        )

    assert response.status_code == 409
    assert jobs.list_for_project(project.id) == []


def test_internal_generation_rejects_idempotency_collision(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Internal collision")
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backend_app,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {"mode": "hosted", "model_id": "hosted", "estimated_frames": 1},
    )
    request = {
        "provider_id": "edmg.internal",
        "operation": "video",
        "idempotency_key": "internal-collision",
        "parameters": {"width": 768},
    }

    with TestClient(backend_app.app) as client:
        first = client.post(f"/v1/projects/{project.id}/generation", json=request)
        replay = client.post(f"/v1/projects/{project.id}/generation", json=request)
        collision = client.post(
            f"/v1/projects/{project.id}/generation",
            json={**request, "parameters": {"width": 1024}},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["generation"]["job_id"] == first.json()["generation"]["job_id"]
    assert collision.status_code == 409


def test_provider_worker_normalizes_mixed_batch_results(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Worker adapter")
    job = jobs.create(project.id, "provider_generation", {})
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    monkeypatch.setattr(
        backend_app,
        "render_firefly_scenes",
        lambda _project_id, _request: {
            "results": [
                {"ok": True, "scene_index": 0, "path": "stills/scene_0000.png"},
                {"ok": False, "scene_index": 1, "error": "policy rejected"},
            ]
        },
    )

    result = backend_app._run_provider_generation(
        project.id,
        job.id,
        {
            "variant_index": 0,
            "_generation": {"provider_id": "adobe.firefly", "operation": "image"},
        },
    )

    assert result["partial_failure"] is True
    assert result["artifacts"][0]["path"] == "stills/scene_0000.png"
    assert result["failures"][0]["scene_index"] == 1


def test_canceled_provider_attempt_does_not_publish_staged_media(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Canceled provider artifact")
    job = jobs.create(
        project.id,
        "provider_generation",
        {"_generation": {"provider_id": "adobe.firefly", "operation": "image"}},
    )
    target = store.project_dir(project.id) / "stills" / "scene_0000.png"
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)

    def write_then_cancel(_project_id, _request):
        from edmg_studio_backend.revisions import published_media_path, staged_media_path

        staged = staged_media_path(target)
        staged.write_bytes(b"stale")
        published_media_path(staged)
        jobs.cancel(project.id, job.id)
        return {"results": [{"ok": True, "scene_index": 0, "path": "stills/scene_0000.png"}]}

    monkeypatch.setattr(backend_app, "render_firefly_scenes", write_then_cancel)
    backend_app._execute_job(job)

    assert not target.exists()
    assert jobs.get(project.id, job.id).status == "canceled"


def test_active_provider_attempt_promotes_staged_media(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Published provider artifact")
    job = jobs.create(
        project.id,
        "provider_generation",
        {"_generation": {"provider_id": "adobe.firefly", "operation": "image"}},
    )
    target = store.project_dir(project.id) / "stills" / "scene_0000.png"
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)

    def write_staged(_project_id, _request):
        from edmg_studio_backend.revisions import published_media_path, staged_media_path

        staged = staged_media_path(target)
        staged.write_bytes(b"published")
        return {
            "results": [{
                "ok": True,
                "scene_index": 0,
                "path": published_media_path(staged).relative_to(store.project_dir(project.id)).as_posix(),
            }]
        }

    monkeypatch.setattr(backend_app, "render_firefly_scenes", write_staged)
    backend_app._execute_job(job)

    persisted = jobs.get(project.id, job.id)
    assert target.read_bytes() == b"published"
    assert persisted.status == "succeeded"
    assert persisted.result["artifacts"][0]["path"] == "stills/scene_0000.png"


def test_obsolete_provider_attempt_cannot_replace_newer_artifact(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Obsolete provider artifact")
    job = jobs.create(
        project.id,
        "provider_generation",
        {"_generation": {"provider_id": "adobe.firefly", "operation": "image"}},
    )
    target = store.project_dir(project.id) / "stills" / "scene_0000.png"
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)

    def supersede_attempt(_project_id, _request):
        from edmg_studio_backend.revisions import staged_media_path

        staged_media_path(target).write_bytes(b"obsolete")
        jobs.cancel(project.id, job.id)
        retried = jobs.retry(project.id, job.id)
        assert retried is not None and retried.attempt == job.attempt + 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"newer")
        return {"results": [{"ok": True, "scene_index": 0, "path": "stills/scene_0000.png"}]}

    monkeypatch.setattr(backend_app, "render_firefly_scenes", supersede_attempt)
    backend_app._execute_job(job)

    assert target.read_bytes() == b"newer"
    persisted = jobs.get(project.id, job.id)
    assert persisted.attempt == 1
    assert persisted.progress is None


def test_failed_partial_scene_is_not_registered_for_publication(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Partial provider artifact")
    job = jobs.create(
        project.id,
        "provider_generation",
        {"_generation": {"provider_id": "adobe.firefly", "operation": "image"}},
    )
    project_dir = store.project_dir(project.id)
    successful = project_dir / "stills" / "scene_0000.png"
    failed = project_dir / "stills" / "scene_0001.png"
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)

    def write_partial(_project_id, _request):
        from edmg_studio_backend.revisions import published_media_path, staged_media_path

        staged_success = staged_media_path(successful)
        staged_success.write_bytes(b"success")
        published_media_path(staged_success)
        staged_media_path(failed)
        return {
            "results": [
                {"ok": True, "scene_index": 0, "path": "stills/scene_0000.png"},
                {"ok": False, "scene_index": 1, "error": "provider write failed"},
            ]
        }

    monkeypatch.setattr(backend_app, "render_firefly_scenes", write_partial)
    backend_app._execute_job(job)

    persisted = jobs.get(project.id, job.id)
    assert successful.read_bytes() == b"success"
    assert not failed.exists()
    assert persisted.status == "succeeded"
    assert persisted.result["partial_failure"] is True


def test_provider_batch_promotion_rolls_back_on_replace_failure(tmp_path, monkeypatch) -> None:
    from edmg_studio_backend import revisions

    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    project = store.create("Provider promotion rollback")
    job = jobs.create(
        project.id,
        "provider_generation",
        {"_generation": {"provider_id": "adobe.firefly", "operation": "image"}},
    )
    project_dir = store.project_dir(project.id)
    targets = [project_dir / "stills" / f"scene_{index:04d}.png" for index in range(2)]
    for index, target in enumerate(targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"original-{index}".encode())
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)

    def write_batch(_project_id, _request):
        results = []
        for index, target in enumerate(targets):
            staged = revisions.staged_media_path(target)
            staged.write_bytes(f"replacement-{index}".encode())
            published = revisions.published_media_path(staged)
            results.append({"ok": True, "scene_index": index, "path": published.relative_to(project_dir).as_posix()})
        return {"results": results}

    real_replace = revisions.os.replace

    def fail_second_promotion(source, destination):
        source_path = revisions.Path(source)
        destination_path = revisions.Path(destination)
        if source_path.name == "scene_0001.png" and destination_path == targets[1]:
            raise OSError("simulated promotion failure")
        real_replace(source, destination)

    monkeypatch.setattr(backend_app, "render_firefly_scenes", write_batch)
    monkeypatch.setattr(revisions.os, "replace", fail_second_promotion)
    backend_app._execute_job(job)

    assert targets[0].read_bytes() == b"original-0"
    assert targets[1].read_bytes() == b"original-1"
    assert jobs.get(project.id, job.id).status == "failed"


def test_generation_submission_rejects_invalid_contract_and_missing_project() -> None:
    with TestClient(backend_app.app) as client:
        invalid_provider = client.post(
            "/v1/projects/missing/generation",
            json={"provider_id": "legacy.provider"},
        )
        invalid_operation = client.post(
            "/v1/projects/missing/generation",
            json={"provider_id": "edmg.internal", "operation": "image"},
        )
        missing_project = client.post(
            "/v1/projects/missing/generation",
            json={"provider_id": "edmg.internal", "operation": "video"},
        )

    assert invalid_provider.status_code == 422
    assert invalid_operation.status_code == 422
    assert missing_project.status_code == 404
