import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edmg_studio_backend.api.director import create_director_router
from edmg_studio_backend.api.director_workflow import create_workflow_router
from edmg_studio_backend.domain.director_scene import (
    DirectorDocument,
    SceneSpec,
    StoryBible,
    compile_scene,
)
from edmg_studio_backend.domain.director_workflow import prepare_workflow
from edmg_studio_backend.revisions import revision_context
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore


def scene(**changes):
    return SceneSpec.model_validate(
        {
            "scene_id": "arrival",
            "start_sample": "9007199254740993",
            "end_sample": "9007199255028993",
            "intent": "A traveler enters town",
            "subjects": [{"id": "traveler", "appearance_lock": True}],
            "actions": ["walks across the road", "looks toward the window"],
            "environment": {"secondary_motion": ["fog drifts across the road"]},
            **changes,
        }
    )


def test_compilers_preserve_exact_range_identity_constraints_and_provenance():
    bible = StoryBible(
        characters={"traveler": "A traveler in a charcoal coat"}, forbidden_changes=["coat color"]
    )
    hunyuan = compile_scene(scene(), bible, "hunyuan_video15")
    ltx = compile_scene(scene(), bible, "ltx_25")
    assert hunyuan["prompt"] != ltx["prompt"]
    assert hunyuan["source_hash"] == ltx["source_hash"]
    assert hunyuan["start_sample"] == "9007199254740993"
    assert hunyuan["status"] == "prepared"
    for package in [hunyuan, ltx]:
        for expected in ["charcoal coat", "fog drifts", "coat color", "Preserve appearance"]:
            assert expected in package["prompt"]
    changed = compile_scene(scene(intent="Different scene"), bible, "hunyuan_video15")
    assert changed["source_hash"] != hunyuan["source_hash"]


@pytest.mark.parametrize(
    "changes",
    [
        {"end_sample": "0"},
        {"start_sample": "9223372036854775808"},
        {"start_sample": 9007199254740993},
        {"camera": {"motion_strength": 2}},
        {"subjects": [{"id": "x"}, {"id": "x"}]},
    ],
)
def test_scene_rejects_invalid_timing_and_structure(changes):
    with pytest.raises((ValidationError, ValueError)):
        scene(**changes)


def test_duplicate_scene_ids_rejected():
    with pytest.raises(ValidationError):
        DirectorDocument(scenes=[scene(), scene()])


def test_project_direction_roundtrip_compilation_and_revision_conflict(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("Director")
    app = FastAPI()
    app.include_router(create_director_router(lambda: store))
    document = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    document["extension"] = {"future": True}
    document["story_bible"]["project_theme"] = "Arrival"
    with TestClient(app) as client:
        path = f"/v1/projects/{project.id}/director"
        initial = client.get(path + "/document").json()
        result = client.post(
            path + "/document",
            json={"expected_revision": initial["revision"], "document": document},
        )
        assert result.status_code == 200, result.text
        saved = result.json()
        assert saved["document"]["story_bible"]["revision"] == 2
        assert saved["document"]["extension"] == {"future": True}
        assert (
            client.post(
                path + "/document",
                json={"expected_revision": initial["revision"], "document": document},
            ).status_code
            == 409
        )
        assert client.get(path + "/document").json() == saved
        compiled = client.get(path + "/prompts?engine=ltx_25")
        assert compiled.status_code == 200
        assert compiled.json()["packages"][0]["scene_id"] == "arrival"
        assert store.get(project.id).revision == saved["revision"]
        assert client.get(path + "/prompts?engine=invalid").status_code == 422
    loaded = ProjectStore(tmp_path).get(project.id)
    assert loaded.meta["director_document"]["scenes"][0]["start_sample"] == "9007199254740993"


def test_director_queue_is_idempotent_and_never_applies_draft(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Queued Director")
    project.meta["director_document"] = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    store.save(project)
    jobs = JobStore(tmp_path / "projects")

    class Models:
        available = True

        def installed_path(self, model_id):
            return tmp_path if self.available else None

    models = Models()
    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: jobs, lambda: models))
    with TestClient(app) as client:
        path = f"/v1/projects/{project.id}/director/generate"
        body = {
            "expected_revision": store.get(project.id).revision,
            "operation_id": "direction-1",
            "instruction": "Add more motion",
        }
        first = client.post(path, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["revision"] == body["expected_revision"] + 1
        body["expected_revision"] = first.json()["revision"]
        assert client.post(path, json=body).json()["job_id"] == first.json()["job_id"]
        assert (
            client.post(path, json={**body, "instruction": "Different direction"}).status_code
            == 409
        )
        assert store.get(project.id).revision == body["expected_revision"]
        assert store.get(project.id).meta["director_job"]["job_id"] == first.json()["job_id"]
        job = jobs.get(project.id, first.json()["job_id"])
        assert job.type == "qwen_director"
        assert job.payload["document"] == project.meta["director_document"]
        models.available = False
        before = store.get(project.id).meta
        unavailable = client.post(path, json={**body, "operation_id": "direction-2"})
        assert unavailable.status_code == 422
        assert unavailable.json()["detail"]["code"] == "DIRECTOR_MODEL_NOT_INSTALLED"
        assert store.get(project.id).meta == before


def test_director_generation_cancels_job_when_project_changes_during_queueing(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Concurrent Director")
    project.meta["director_document"] = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    store.save(project)
    jobs = JobStore(tmp_path / "projects")

    class Models:
        def installed_path(self, _model_id):
            return tmp_path

    original_mutate = store.mutate
    raced = False

    def mutate_after_concurrent_change(project_id, mutator, *, expected_revision=None):
        nonlocal raced
        if not raced:
            raced = True
            token = revision_context.set(None)
            try:
                original_mutate(project_id, lambda value: value.meta.update(concurrent_edit=True))
            finally:
                revision_context.reset(token)
        return original_mutate(project_id, mutator, expected_revision=expected_revision)

    monkeypatch.setattr(store, "mutate", mutate_after_concurrent_change)
    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: jobs, lambda: Models()))
    body = {
        "expected_revision": project.revision,
        "operation_id": "raced-direction",
        "instruction": "Add a slow orbit",
    }
    with TestClient(app) as client:
        path = f"/v1/projects/{project.id}/director/generate"
        conflicted = client.post(path, json=body)
        assert conflicted.status_code == 409
        job = jobs.list_for_project(project.id)[0]
        assert job.status == "canceled"
        assert "director_job" not in store.get(project.id).meta

        body["expected_revision"] = store.get(project.id).revision
        retry = client.post(path, json=body)
        assert retry.status_code == 409
        assert "prior Director request conflicted" in retry.json()["detail"]


def test_director_generation_preserves_job_persisted_by_concurrent_retry(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Concurrent duplicate Director")
    project.meta["director_document"] = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    store.save(project)
    jobs = JobStore(tmp_path / "projects")

    class Models:
        def installed_path(self, _model_id):
            return tmp_path

    original_mutate = store.mutate
    raced = False

    def mutate_after_duplicate_persists(project_id, mutator, *, expected_revision=None):
        nonlocal raced
        if not raced:
            raced = True
            job = jobs.list_for_project(project_id)[0]
            token = revision_context.set(None)
            try:
                original_mutate(
                    project_id,
                    lambda value: value.meta.update(director_job={"job_id": job.id}),
                )
            finally:
                revision_context.reset(token)
        return original_mutate(project_id, mutator, expected_revision=expected_revision)

    monkeypatch.setattr(store, "mutate", mutate_after_duplicate_persists)
    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: jobs, lambda: Models()))
    body = {
        "expected_revision": project.revision,
        "operation_id": "duplicate-direction",
        "instruction": "Add a slow orbit",
    }
    with TestClient(app) as client:
        response = client.post(f"/v1/projects/{project.id}/director/generate", json=body)
        assert response.status_code == 200
        job = jobs.list_for_project(project.id)[0]
        assert response.json()["job_id"] == job.id
        assert job.status == "queued"
        assert store.get(project.id).meta["director_job"]["job_id"] == job.id


def test_workspace_draft_reports_waiting_progress_and_hides_canceled_output(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Director progress")
    jobs = JobStore(store.projects_dir)
    try:
        job = jobs.create(project.id, "qwen_director", {})
        unrelated = jobs.create(project.id, "assemble_variant", {})
        jobs.update_progress(
            project.id, job.id, stage="waiting_for_model", current=0, total=1,
            message="Waiting for the current local model job to finish",
        )
        app = FastAPI()
        app.include_router(create_director_router(lambda: store, lambda: jobs))
        with TestClient(app) as client:
            path = f"/v1/projects/{project.id}/director/drafts/{job.id}"
            waiting = client.get(path).json()
            assert waiting["progress"]["stage"] == "waiting_for_model"
            assert "Waiting" in waiting["progress"]["message"]
            assert waiting["result"] is None
            assert client.get(path.replace(job.id, unrelated.id)).status_code == 404
            jobs.cancel(project.id, job.id)
            job.status = "succeeded"
            job.result = {"document": "late output"}
            jobs.save(job)
            canceled = client.get(path).json()
            assert canceled["status"] == "canceled"
            assert canceled["result"] is None
            assert store.get(project.id).revision == project.revision
    finally:
        jobs.close()


def test_director_generation_persists_resolved_workspace_policy(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Resolved Director")
    project.meta["director_document"] = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    store.save(project)
    jobs = JobStore(tmp_path / "projects")

    class Models:
        def installed_path(self, _model_id):
            return tmp_path

    app = FastAPI()
    app.include_router(
        create_director_router(
            lambda: store,
            lambda: jobs,
            lambda: Models(),
            lambda: {"backend": "cpu", "ram_gb": 32.0, "cpu_threads": 16},
            lambda: {
                "runtime_path": "C:\\Studio\\llama-server.exe",
                "gpu_layers": "7",
                "context_length": 12288,
                "batch_size": 32,
                "ubatch_size": 8,
                "cuda_graphs": True,
            },
        )
    )
    with TestClient(app) as client:
        path = f"/v1/projects/{project.id}/director/generate"
        response = client.post(
            path,
            json={
                "expected_revision": project.revision,
                "operation_id": "resolved-policy-1",
                "instruction": "Keep the approved character identity and add a slow camera move.",
                "mode": "fast",
                "renderer_engine": "external",
                "allow_external": True,
            },
        )

    assert response.status_code == 200, response.text
    job = jobs.get(project.id, response.json()["job_id"])
    assert job.payload["model_id"] == "hf_qwen3_vl_8b_director"
    assert job.payload["mode"] == "fast"
    assert job.payload["renderer_engine"] == "external"
    assert job.payload["allow_external"] is True
    assert job.payload["readiness"]["director"]["ready"] is True
    assert job.payload["readiness"]["renderer"]["engine"] == "external"
    assert job.payload["runtime_path"] == "C:\\Studio\\llama-server.exe"
    assert job.payload["gpu_layers"] == "7"
    assert job.payload["context_length"] == 12288
    assert job.payload["batch_size"] == 32
    assert job.payload["ubatch_size"] == 8
    assert job.payload["cuda_graphs"] is True


def test_reviewed_draft_apply_checks_baseline_and_preserves_job(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Draft review")
    baseline = DirectorDocument(scenes=[scene()])
    project.meta["director_document"] = baseline.model_dump(mode="json")
    store.save(project)
    jobs = JobStore(tmp_path / "projects")
    job = jobs.create(
        project.id,
        "qwen_director",
        {
            "document": baseline.model_dump(mode="json"),
            "source_revision": store.get(project.id).revision,
        },
    )
    proposal = baseline.model_copy(deep=True)
    proposal.scenes[0].actions = ["walks slowly toward the window"]
    job.result = {
        "status": "draft",
        "document": proposal.model_dump(mode="json"),
        "provenance": {"test_fixture": True},
    }
    job.status = "succeeded"
    jobs.save(job)
    store.mutate(project.id, lambda value: value.meta.update(director_job={
        "version": 1,
        "job_id": job.id,
        "status": "review_ready",
        "reviewed": False,
        "instruction": "Add a slow walk",
    }))
    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: jobs))
    with TestClient(app) as client:
        path = f"/v1/projects/{project.id}/director/drafts/{job.id}"
        assert client.get(path).json()["result"]["status"] == "draft"
        revision = store.get(project.id).revision
        unreviewed = client.post(path + "/apply", json={"expected_revision": revision})
        assert unreviewed.status_code == 409
        reviewed = client.post(path + "/review", json={"expected_revision": revision})
        assert reviewed.status_code == 200, reviewed.text
        result = client.post(path + "/apply", json={"expected_revision": reviewed.json()["revision"]})
        assert result.status_code == 200, result.text
        assert result.json()["document"]["scenes"][0]["actions"] == proposal.scenes[0].actions
        workflow = store.get(project.id).meta["director_workflow"]
        assert workflow["document"] == result.json()["document"]
        assert workflow["schedule"]["motion_keys"]
        assert workflow["schedule"]["camera_keys"]
        # Retrying against a freshly loaded revision must not overwrite newer direction.
        assert (
            client.post(
                path + "/apply", json={"expected_revision": result.json()["revision"]}
            ).status_code
            == 409
        )
        assert jobs.get(project.id, job.id).result == job.result
        assert store.get(project.id).meta["director_applied_job"]["job_id"] == job.id


def test_director_jobs_recover_pending_review_ready_and_reviewed_after_restart(tmp_path):
    root = tmp_path / "projects"
    store = ProjectStore(root)
    project = store.create("Recover Director jobs")
    document = DirectorDocument(scenes=[scene()]).model_dump(mode="json")
    project.meta["director_document"] = document
    store.save(project)
    jobs = JobStore(root)
    pending = jobs.create(project.id, "qwen_director", {"document": document})
    ready = jobs.create(project.id, "qwen_director", {"document": document})
    ready.result = {"status": "draft", "document": document}
    ready.status = "succeeded"
    jobs.save(ready)
    reviewed = jobs.create(project.id, "qwen_director", {"document": document})
    reviewed.result = {"status": "draft", "document": document}
    reviewed.status = "succeeded"
    jobs.save(reviewed)
    project = store.get(project.id)
    project.meta["director_applied_job"] = {"job_id": reviewed.id}
    store.save(project)
    jobs.close()

    restarted_jobs = JobStore(root)
    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: restarted_jobs))
    with TestClient(app) as client:
        response = client.get(f"/v1/projects/{project.id}/director/drafts")
        assert response.status_code == 200, response.text
        statuses = {item["job_id"]: item["status"] for item in response.json()["director_jobs"]}

    assert statuses[pending.id] == "queued"
    assert statuses[ready.id] == "review_ready"
    assert statuses[reviewed.id] == "reviewed"
    restarted_jobs.close()


def test_workflow_recovers_exact_context_and_reviewed_job_after_restart(tmp_path):
    root = tmp_path / "projects"
    store = ProjectStore(root)
    project = store.create("Recover workflow job")
    project.meta["analysis"] = {"revision": 1, "duration_s": 2, "features": {"bpm": 120}}
    project.meta["timeline"] = {"timebase": {"sample_rate": 48000}, "tracks": [], "markers": []}
    prepare_workflow(
        project,
        lambda _: {"variants": [{"scenes": [{"id": "scene-1", "start_s": 0, "end_s": 2,
                                                "prompt": "A dancer crosses a neon room"}]}]},
        resulting_revision=project.revision + 1,
    )
    store.save(project)
    jobs = JobStore(root)

    class Models:
        def installed_path(self, _model_id):
            return tmp_path

    app = FastAPI()
    app.include_router(create_director_router(lambda: store, lambda: jobs, lambda: Models()))
    with TestClient(app) as client:
        generated = client.post(
            f"/v1/projects/{project.id}/director/generate",
            json={"expected_revision": store.get(project.id).revision, "operation_id": "recover-1",
                  "instruction": "Keep the dancer centered", "start_sample": "0", "end_sample": "48000"},
        )
        assert generated.status_code == 200, generated.text
        job = jobs.get(project.id, generated.json()["job_id"])
        job.status = "succeeded"
        job.result = {"status": "draft", "document": job.payload["document"]}
        jobs.save(job)
    jobs.close()

    restarted_jobs = JobStore(root)
    restarted = FastAPI()
    restarted.include_router(create_workflow_router(lambda: store, lambda _: {}, lambda: restarted_jobs))
    restarted.include_router(create_director_router(lambda: store, lambda: restarted_jobs, lambda: Models()))
    with TestClient(restarted) as client:
        workflow_path = f"/v1/projects/{project.id}/director/workflow"
        recovered = client.get(workflow_path)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["director_job"]["status"] == "review_ready"
        assert recovered.json()["timeline_context"]["selected_range"] == {
            "start_sample": "0", "end_sample": "48000"
        }
        assert recovered.json()["context_revision"] == generated.json()["revision"]

        reviewed = client.post(
            f"/v1/projects/{project.id}/director/drafts/{job.id}/review",
            json={"expected_revision": recovered.json()["revision"]},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["director_job"]["reviewed_job_id"] == job.id
        assert reviewed.json()["director_job"]["status"] == "reviewed"
        assert client.get(workflow_path).json()["director_job"]["status"] == "reviewed"
    restarted_jobs.close()
