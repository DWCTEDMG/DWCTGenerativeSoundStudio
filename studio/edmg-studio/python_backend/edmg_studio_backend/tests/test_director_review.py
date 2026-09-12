from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api.director_review import create_director_review_router
from edmg_studio_backend.domain.director_review import (
    DimensionScore,
    ReviewRequest,
    aggregate_scores,
    sample_timestamps,
)
from edmg_studio_backend.domain.director_workflow import prepare_workflow
from edmg_studio_backend.services import director_review as service
from edmg_studio_backend.store.projects import ProjectStore


def _plan(_project):
    return {"variants": [{"scenes": [
        {"id": "first", "start_s": 0, "end_s": 2, "prompt": "red traveler in forest",
         "character_lock": "red coat"},
        {"id": "next", "start_s": 2, "end_s": 4, "prompt": "blue city at night",
         "character_lock": "blue coat"},
    ]}]}


@pytest.fixture
def project_state(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    project = store.create("Review")
    project.meta["analysis"] = {"revision": 1, "duration_s": 4}
    project.meta["timeline"] = {"timebase": {"sample_rate": 48000, "fps": 24}, "tracks": []}
    project.meta["last_plan"] = _plan(project)
    prepare_workflow(project, _plan, resulting_revision=project.revision + 1)
    store.save(project)
    video = store.project_dir(project.id) / "outputs" / "videos" / "render.mp4"
    video.write_bytes(b"video artifact")
    return store, store.get(project.id), video


def _fake_media(monkeypatch):
    monkeypatch.setattr(service, "_probe_duration_seconds", lambda _ffmpeg, _path: 10.0)
    monkeypatch.setattr(service, "ensure_ffmpeg", lambda _path: "ffmpeg")

    def run(command, **_kwargs):
        Path(command[-1]).write_bytes(("frame:" + command[5]).encode())
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(service.subprocess, "run", run)


def test_sampling_is_deterministic_bounded_and_persists_hashes(project_state, monkeypatch):
    store, project, video = project_state
    _fake_media(monkeypatch)
    assert sample_timestamps(10, 3) == [1.666667, 5.0, 8.333333]
    request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4", sample_count=3)
    report = service.create_review(project=project, project_dir=store.project_dir(project.id), request=request,
                                   ffmpeg_path="ffmpeg", prior_reports=[])
    assert [item.timestamp_seconds for item in report.samples] == sample_timestamps(10, 3)
    for item in report.samples:
        frame = store.project_dir(project.id) / item.path
        assert item.sha256 == hashlib.sha256(frame.read_bytes()).hexdigest()
        assert "base64" not in item.model_dump_json()
    assert video.exists()


def test_score_aggregation_ignores_unassessed_dimensions():
    dimensions = [
        DimensionScore(dimension="artifact_detection_quality", state="assessed", score=0.8),
        DimensionScore(dimension="character_consistency", state="not_assessed"),
        DimensionScore(dimension="previous_scene_continuity", state="assessed", score=0.4),
    ]
    assert aggregate_scores(dimensions) == (0.6, 0.4)


def test_request_hard_caps_samples_and_retries():
    with pytest.raises(ValueError):
        ReviewRequest(expected_revision=1, artifact_path="outputs/videos/a.mp4", sample_count=13)
    with pytest.raises(ValueError):
        ReviewRequest(expected_revision=1, artifact_path="outputs/videos/a.mp4", max_attempts=6)


def test_understanding_fallback_is_explicit_and_deterministic_review_completes(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4",
                            request_clip_understanding=True)
    report = service.create_review(project=project, project_dir=store.project_dir(project.id), request=request,
                                   ffmpeg_path="ffmpeg", prior_reports=[])
    assert report.status == "completed"
    assert report.clip_understanding.state == "unavailable"
    assert report.provenance["clip_understanding_ran"] is False
    assert next(item for item in report.dimensions if item.dimension == "character_consistency").state == "not_assessed"
    assert report.disposition == "correction_recommended"
    assert report.correction_plan.state == "unavailable"
    assert any(item.code == "semantic_review_incomplete" for item in report.findings)


@pytest.mark.parametrize("failure", [RuntimeError("provider failed"), TimeoutError("provider timed out"), "invalid"])
def test_understanding_failure_preserves_deterministic_report(project_state, monkeypatch, failure):
    store, project, _ = project_state
    _fake_media(monkeypatch)

    def understanding(_video, _samples):
        if isinstance(failure, Exception):
            raise failure
        return failure

    request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4",
                            request_clip_understanding=True)
    report = service.create_review(project=project, project_dir=store.project_dir(project.id), request=request,
                                   ffmpeg_path="ffmpeg", prior_reports=[], understanding=understanding)
    assert report.status == "completed"
    assert report.clip_understanding.state == "unavailable"
    assert report.disposition == "correction_recommended"


@pytest.mark.parametrize("artifact", ["../escape.mp4", "outputs/images/render.mp4", "C:\\escape.mp4"])
def test_artifact_path_is_confined(project_state, artifact):
    store, project, _ = project_state
    with pytest.raises(ValueError):
        service.resolve_video_artifact(store.project_dir(project.id), artifact)


def test_review_api_persistence_idempotency_retry_and_correction_apply(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    app = FastAPI()
    app.include_router(create_director_review_router(
        lambda: store,
        "ffmpeg",
        understanding=lambda _video, _samples: {
            "detail": "Test semantic review",
            "scores": {name: 0.5 for name in service.REVIEW_DIMENSIONS
                       if name not in {"artifact_detection_quality", "previous_scene_continuity"}},
        },
    ))
    path = f"/v1/projects/{project.id}/director/reviews"
    body = {"expected_revision": project.revision, "artifact_path": "outputs/videos/render.mp4",
            "sample_count": 2, "threshold": 1.0, "max_attempts": 1,
            "request_clip_understanding": True, "target_scene_id": "first"}
    with TestClient(app) as client:
        created = client.post(path, json=body)
        assert created.status_code == 200, created.text
        report = created.json()["report"]
        assert report["retry"]["result"] == "exhausted"
        assert report["retry"]["attempt"] == 1
        assert report["source_draft_id"]
        assert report["source_draft_fingerprint"]
        assert report["retry_chain_id"] == report["report_id"]
        assert report["correction_plan"]["state"] == "proposed"
        repeated = client.post(path, json=body)
        assert repeated.status_code == 200 and repeated.json()["replayed"] is True
        assert repeated.json()["report"]["report_id"] == report["report_id"]
        assert len(client.get(path).json()["reports"]) == 1

        stale = client.post(f"{path}/{report['report_id']}/apply", json={"expected_revision": project.revision - 1})
        assert stale.status_code == 409
        applied = client.post(f"{path}/{report['report_id']}/apply", json={"expected_revision": project.revision})
        assert applied.status_code == 200, applied.text

    saved = store.get(project.id)
    document = saved.meta["director_workflow"]["document"]
    assert [scene["scene_id"] for scene in document["scenes"]] == ["first", "next"]
    assert [(scene["start_sample"], scene["end_sample"]) for scene in document["scenes"]] == [
        ("0", "96000"), ("96000", "192000")]
    assert document["scenes"][1]["renderer_hints"]["director_review_guidance"]
    assert document["scenes"][1]["subjects"][0]["appearance_lock"] is True
    assert document["scenes"][1]["subjects"][0]["appearance_notes"] == ["blue coat"]


def test_review_api_rejects_stale_revision_before_sampling(project_state, monkeypatch):
    store, project, _ = project_state
    sampled = []
    monkeypatch.setattr(service, "extract_samples", lambda *_args, **_kwargs: sampled.append(True))
    app = FastAPI()
    app.include_router(create_director_review_router(lambda: store, "ffmpeg"))

    with TestClient(app) as client:
        response = client.post(
            f"/v1/projects/{project.id}/director/reviews",
            json={"expected_revision": project.revision - 1, "artifact_path": "outputs/videos/render.mp4"},
        )

    assert response.status_code == 409
    assert sampled == []


def test_review_api_requires_explicit_eligible_retry_chain(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    app = FastAPI()
    app.include_router(create_director_review_router(lambda: store, "ffmpeg"))
    path = f"/v1/projects/{project.id}/director/reviews"
    body = {"expected_revision": project.revision, "artifact_path": "outputs/videos/render.mp4",
            "sample_count": 2, "threshold": 1.0, "max_attempts": 2, "target_scene_id": "first"}

    with TestClient(app) as client:
        first = client.post(path, json=body).json()["report"]
        assert first["retry"]["attempt"] == 1
        assert first["retry"]["result"] == "recommended"

        replay = client.post(path, json=body).json()
        assert replay["replayed"] is True
        assert replay["report"]["retry"]["attempt"] == 1

        retry_body = {**body, "retry_of_report_id": first["report_id"], "sample_count": 3}
        second = client.post(path, json=retry_body).json()["report"]
        assert second["retry"]["attempt"] == 2
        assert second["retry"]["result"] == "exhausted"
        assert second["retry_chain_id"] == first["retry_chain_id"]
        assert [item["report_id"] for item in second["retry"]["history"]] == [
            first["report_id"], second["report_id"]]

        retry_replay = client.post(path, json=retry_body)
        assert retry_replay.status_code == 200
        assert retry_replay.json()["replayed"] is True
        assert retry_replay.json()["report"]["report_id"] == second["report_id"]

        ineligible = client.post(path, json={**retry_body, "retry_of_report_id": second["report_id"]})
        assert ineligible.status_code == 400

        branched = client.post(path, json={**retry_body, "sample_count": 4})
        assert branched.status_code == 409

        missing = client.post(path, json={**body, "retry_of_report_id": "0" * 64})
        assert missing.status_code == 404


def test_retry_attempts_are_bounded_and_never_loop(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    prior = []
    for count in range(1, 3):
        request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4",
                                sample_count=count, threshold=1.0, max_attempts=2, target_scene_id="first")
        report = service.create_review(project=project, project_dir=store.project_dir(project.id), request=request,
                                       ffmpeg_path="ffmpeg", prior_reports=prior)
        prior.append(report)
    assert [item.retry.attempt for item in prior] == [1, 2]
    assert [item.retry.result for item in prior] == ["recommended", "exhausted"]
    assert len(prior[-1].retry.history) == 2


def test_partial_semantic_coverage_cannot_approve(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4",
                            request_clip_understanding=True, threshold=0.5)
    report = service.create_review(
        project=project, project_dir=store.project_dir(project.id), request=request,
        ffmpeg_path="ffmpeg", prior_reports=[],
        understanding=lambda _video, _samples: {"scores": {"character_consistency": 1.0}},
    )
    assert report.disposition == "correction_recommended"
    assert report.correction_plan.state == "unavailable"
    assert any(item.code == "semantic_review_incomplete" for item in report.findings)


def test_low_complete_semantic_review_produces_correction_guidance(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    semantic = {name: 0.25 for name in service.REVIEW_DIMENSIONS
                if name not in {"artifact_detection_quality", "previous_scene_continuity"}}
    request = ReviewRequest(expected_revision=project.revision, artifact_path="outputs/videos/render.mp4",
                            request_clip_understanding=True, threshold=0.75, target_scene_id="first")
    report = service.create_review(
        project=project, project_dir=store.project_dir(project.id), request=request,
        ffmpeg_path="ffmpeg", prior_reports=[],
        understanding=lambda _video, _samples: {"scores": semantic},
    )
    assert report.disposition == "correction_recommended"
    assert report.correction_plan.state == "proposed"
    assert report.correction_plan.guidance


def test_apply_rejects_report_from_replaced_director_draft(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    semantic = {name: 0.25 for name in service.REVIEW_DIMENSIONS
                if name not in {"artifact_detection_quality", "previous_scene_continuity"}}
    app = FastAPI()
    app.include_router(create_director_review_router(
        lambda: store, "ffmpeg", understanding=lambda _video, _samples: {"scores": semantic}))
    path = f"/v1/projects/{project.id}/director/reviews"
    body = {"expected_revision": project.revision, "artifact_path": "outputs/videos/render.mp4",
            "threshold": 0.75, "request_clip_understanding": True, "target_scene_id": "first"}
    with TestClient(app) as client:
        report = client.post(path, json=body).json()["report"]
        current = store.get(project.id)
        current.meta["director_workflow"]["draft_id"] = "replacement-draft"
        store.save(current)
        response = client.post(f"{path}/{report['report_id']}/apply",
                               json={"expected_revision": current.revision})
    assert response.status_code == 409
    assert "draft changed" in response.json()["detail"]


def test_apply_rejects_second_report_after_first_changes_same_draft(project_state, monkeypatch):
    store, project, _ = project_state
    _fake_media(monkeypatch)
    semantic = {name: 0.25 for name in service.REVIEW_DIMENSIONS
                if name not in {"artifact_detection_quality", "previous_scene_continuity"}}
    app = FastAPI()
    app.include_router(create_director_review_router(
        lambda: store, "ffmpeg", understanding=lambda _video, _samples: {"scores": semantic}))
    path = f"/v1/projects/{project.id}/director/reviews"
    body = {"expected_revision": project.revision, "artifact_path": "outputs/videos/render.mp4",
            "threshold": 0.75, "request_clip_understanding": True, "target_scene_id": "first"}
    with TestClient(app) as client:
        first = client.post(path, json=body).json()["report"]
        second = client.post(path, json={**body, "sample_count": 5}).json()["report"]
        applied = client.post(f"{path}/{first['report_id']}/apply",
                              json={"expected_revision": project.revision})
        assert applied.status_code == 200
        stale = client.post(f"{path}/{second['report_id']}/apply",
                            json={"expected_revision": applied.json()["revision"]})
    assert stale.status_code == 409
    assert "draft changed" in stale.json()["detail"]
