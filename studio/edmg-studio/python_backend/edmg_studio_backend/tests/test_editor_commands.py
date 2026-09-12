import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api.editor import create_editor_router
from edmg_studio_backend.domain.editor_commands import execute, normalize_timeline
from edmg_studio_backend.store.projects import ProjectStore


def timeline():
    return {
        "fps": 30,
        "extension": {"keep": True},
        "tracks": [
            {
                "id": "video",
                "type": "video",
                "clips": [
                    {
                        "id": "clip",
                        "start_s": 1,
                        "end_s": 5,
                        "data": {"source_in_s": 2, "source_sample_rate": 44100, "speed": 2},
                        "custom": "retained",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def editor(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("Editor")
    project.meta["timeline"] = timeline()
    store.save(project)
    app = FastAPI()
    app.include_router(create_editor_router(lambda: store))
    with TestClient(app) as client:
        yield store, project.id, client


def submit(editor, *, action="edit", operations=None, **kwargs):
    store, pid, client = editor
    body = {
        "operation_id": str(uuid4()),
        "expected_revision": store.get(pid).revision,
        "action": action,
        "operations": operations or [],
        **kwargs,
    }
    return client.post(f"/v1/projects/{pid}/editor/commands", json=body)


def test_grouped_edit_undo_redo_persists_across_store_reload(editor):
    store, pid, client = editor
    result = submit(
        editor,
        operations=[
            {"kind": "move", "track_id": "video", "clip_id": "clip", "position": "96000"},
            {
                "kind": "split",
                "track_id": "video",
                "clip_id": "clip",
                "position": "144000",
                "new_id": "right",
            },
        ],
    )
    assert result.status_code == 200, result.text
    clips = result.json()["timeline"]["tracks"][0]["clips"]
    assert clips[0]["start_sample"] == "96000"
    assert clips[0]["end_sample"] == "144000"
    assert clips[1]["data"]["source_offset_sample"] == "176400"
    assert clips[0]["data"]["source_end_sample"] == "176400"
    assert clips[1]["custom"] == "retained"
    assert result.json()["history"]["can_undo"]
    persisted = ProjectStore(store.project_dir(pid).parent.parent).get(pid)
    assert persisted is not None and persisted.meta["editor_history"]["undo"]
    undone = submit(editor, action="undo")
    assert undone.status_code == 200
    assert undone.json()["timeline"] == normalize_timeline(timeline())
    redone = submit(editor, action="redo")
    assert redone.json()["timeline"] == result.json()["timeline"]


def test_retry_is_idempotent_and_changed_reuse_rejected(editor):
    store, pid, client = editor
    body = {
        "operation_id": "retry",
        "expected_revision": store.get(pid).revision,
        "action": "edit",
        "operations": [{"kind": "duplicate", "track_id": "video", "clip_id": "clip"}],
    }
    url = f"/v1/projects/{pid}/editor/commands"
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["revision"] == second.json()["revision"]
    assert second.json()["replayed"]
    body["operations"][0]["kind"] = "delete"
    assert client.post(url, json=body).status_code == 409


def test_invalid_batch_has_no_partial_commit(editor):
    store, pid, _ = editor
    before = store.get(pid)
    result = submit(
        editor,
        operations=[
            {"kind": "delete", "track_id": "video", "clip_id": "clip"},
            {"kind": "delete", "track_id": "missing", "clip_id": "clip"},
        ],
    )
    assert result.status_code == 422
    assert store.get(pid).revision == before.revision
    assert store.get(pid).meta == before.meta


def test_external_edit_cannot_be_overwritten_by_undo(editor):
    store, pid, client = editor
    assert (
        submit(
            editor, operations=[{"kind": "duplicate", "track_id": "video", "clip_id": "clip"}]
        ).status_code
        == 200
    )
    store.mutate(pid, lambda p: p.meta["timeline"].update({"extension": "external"}))
    result = submit(editor, action="undo")
    assert result.status_code == 409
    assert client.get(f"/v1/projects/{pid}/editor").json()["history"]["external_change"]


def test_stale_revision_is_rejected(editor):
    store, pid, _ = editor
    response = submit(
        editor, action="replace", timeline=timeline(), expected_revision=store.get(pid).revision - 1
    )
    assert response.status_code == 409


def test_insert_artifact_is_revision_safe_idempotent_and_updates_media_pool(editor):
    store, pid, client = editor
    project_dir = store.project_dir(pid)
    video = project_dir / "outputs" / "videos" / "generated.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    manifest = {
        "schema_version": 1, "id": "artifact-generated", "kind": "video",
        "path": "outputs/videos/generated.mp4", "content_hash": "abc",
        "engine": "comfyui", "provider": "local", "model": {"id": "hunyuan-video", "revision": "r2"},
        "project_revision": 3, "plan_revision": "plan-2", "source_assets": [{"id": "audio-source"}],
        "lineage": {"parents": ["artifact-parent"]},
    }
    video.with_suffix(".mp4.artifact.json").write_text(json.dumps(manifest), encoding="utf-8")
    body = {
        "operation_id": "insert-generated", "expected_revision": store.get(pid).revision,
        "artifact_path": "outputs/videos/generated.mp4", "start_seconds": 2, "duration_seconds": 3,
    }
    url = f"/v1/projects/{pid}/editor/insert-artifact"
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["replayed"] is True
    project = store.get(pid)
    assert project.meta["media_pool"] == [{
        "id": "artifact-generated", "version_id": "artifact-generated", "artifact_id": "artifact-generated",
        "path": "outputs/videos/generated.mp4", "kind": "video",
        "manifest_path": "outputs/videos/generated.mp4.artifact.json", "content_hash": "abc",
        "renderer_id": "comfyui", "provider_id": "local",
        "model": {"id": "hunyuan-video", "revision": "r2"},
        "project_revision": 3, "plan_revision": "plan-2", "source_assets": [{"id": "audio-source"}],
        "lineage": {"parents": ["artifact-parent"]},
    }]
    clips = project.meta["timeline"]["tracks"][0]["clips"]
    assert len(clips) == 2 and clips[-1]["source_path"] == "outputs/videos/generated.mp4"
    assert clips[-1]["media_asset_id"] == "artifact-generated"
    assert clips[-1]["data"]["artifact_id"] == "artifact-generated"
    changed = dict(body, duration_seconds=4)
    assert client.post(url, json=changed).status_code == 409
    stale = dict(body, operation_id="other", expected_revision=body["expected_revision"])
    assert client.post(url, json=stale).status_code == 409


def test_insert_render_result_resolves_completed_job_artifact(editor):
    store, pid, _ = editor
    project_dir = store.project_dir(pid)
    video = project_dir / "outputs" / "videos" / "render.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    manifest = {
        "schema_version": 1,
        "id": "artifact-render",
        "kind": "video",
        "path": "outputs/videos/render.mp4",
        "engine": "hunyuan_video15",
    }
    video.with_suffix(".mp4.artifact.json").write_text(json.dumps(manifest), encoding="utf-8")
    job = SimpleNamespace(
        id="job-render",
        project_id=pid,
        type="internal_video",
        status="succeeded",
        result={"artifact": {"path": "outputs/videos/render.mp4"}},
    )
    job_store = SimpleNamespace(get=lambda project_id, job_id: job if (project_id, job_id) == (pid, job.id) else None)
    app = FastAPI()
    app.include_router(create_editor_router(lambda: store, lambda: job_store, lambda _path: 4.25))
    with TestClient(app) as client:
        body = {
            "job_id": job.id,
            "expected_revision": store.get(pid).revision,
            "start_s": 2.5,
        }
        first = client.post(f"/v1/projects/{pid}/timeline/insert-render-result", json=body)
        second = client.post(f"/v1/projects/{pid}/timeline/insert-render-result", json=body)

    assert first.status_code == second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["job_id"] == job.id
    inserted = store.get(pid).meta["timeline"]["tracks"][0]["clips"][-1]
    assert inserted["source_path"] == "outputs/videos/render.mp4"
    assert inserted["start_s"] == 2.5
    assert inserted["end_s"] == 6.75


def test_precise_sample_survives_legacy_round_trip():
    initial = timeline()
    clip = initial["tracks"][0]["clips"][0]
    clip["start_sample"], clip["end_sample"] = "9007199254740993", "9007199254788993"
    precise = normalize_timeline(initial)
    roundtrip = normalize_timeline(deepcopy(precise), precise)
    assert roundtrip["tracks"][0]["clips"][0]["start_sample"] == "9007199254740993"
    old_client = deepcopy(precise)
    del old_client["tracks"][0]["clips"][0]["start_sample"]
    del old_client["tracks"][0]["clips"][0]["end_sample"]
    assert (
        normalize_timeline(old_client, precise)["tracks"][0]["clips"][0]["start_sample"]
        == "9007199254740993"
    )
    edited = deepcopy(precise)
    edited["tracks"][0]["clips"][0]["start_s"] = 3
    assert normalize_timeline(edited, precise)["tracks"][0]["clips"][0]["start_sample"] == "144000"


def test_new_clip_source_seconds_create_exact_sample_metadata():
    source = timeline()
    source["tracks"][0]["clips"][0]["data"].update({"source_in_s": 1.25, "source_out_s": 3.5})
    normalized = normalize_timeline(source)
    data = normalized["tracks"][0]["clips"][0]["data"]
    assert data["source_offset_sample"] == "55125"
    assert data["source_offset_remainder"] == "0"
    assert data["source_end_sample"] == "154350"
    assert data["source_end_remainder"] == "0"


def test_queued_source_edits_replace_stale_exact_sample_metadata():
    initial = normalize_timeline(timeline())
    first = deepcopy(initial)
    first["tracks"][0]["clips"][0]["data"]["source_in_s"] = 3
    first = normalize_timeline(first, initial)
    second = deepcopy(initial)
    second["tracks"][0]["clips"][0]["data"]["source_in_s"] = 4
    second = normalize_timeline(second, first)
    data = second["tracks"][0]["clips"][0]["data"]
    assert data["source_in_s"] == 4
    assert data["source_offset_sample"] == "176400"
    assert data["source_offset_remainder"] == "0"


def test_locked_tracks_and_media_paths_are_protected(editor):
    store, pid, _ = editor
    store.mutate(pid, lambda p: p.meta["timeline"]["tracks"][0].update({"locked": True}))
    assert (
        submit(
            editor, operations=[{"kind": "delete", "track_id": "video", "clip_id": "clip"}]
        ).status_code
        == 422
    )
    modified = timeline()
    modified["tracks"][0]["clips"] = []
    assert submit(editor, action="replace", timeline=modified).status_code == 422
    store.mutate(pid, lambda p: p.meta["timeline"]["tracks"][0].update({"locked": False}))
    modified = timeline()
    modified["tracks"][0]["clips"][0]["source_path"] = "../outside.mp4"
    assert submit(editor, action="replace", timeline=modified).status_code == 422


def test_locked_camera_is_protected_from_replacement(editor):
    store, pid, _ = editor
    store.mutate(
        pid,
        lambda p: p.meta["timeline"].update(
            {"camera": {"locked": True, "keyframes": [{"id": "camera-1", "t": 1}]}}
        ),
    )
    modified = deepcopy(store.get(pid).meta["timeline"])
    modified["camera"]["keyframes"] = []
    assert submit(editor, action="replace", timeline=modified).status_code == 422
    without_camera = deepcopy(store.get(pid).meta["timeline"])
    del without_camera["camera"]
    assert submit(editor, action="replace", timeline=without_camera).status_code == 422
    unlocked = deepcopy(store.get(pid).meta["timeline"])
    unlocked["camera"]["locked"] = False
    response = submit(editor, action="replace", timeline=unlocked)
    assert response.status_code == 200, response.text
    assert response.json()["timeline"]["camera"] == unlocked["camera"]


def test_history_is_bounded_and_new_edit_discards_redo():
    meta = {"timeline": timeline()}
    for index in range(205):
        execute(
            meta,
            {
                "operation_id": str(index),
                "action": "edit",
                "operations": [
                    {
                        "kind": "set_mute",
                        "track_id": "video",
                        "clip_id": "clip",
                        "value": bool(index % 2),
                    }
                ],
            },
        )
    assert len(meta["editor_history"]["undo"]) == 200
    execute(meta, {"operation_id": "undo", "action": "undo"})
    assert len(meta["editor_history"]["redo"]) == 1
    execute(
        meta,
        {
            "operation_id": "new",
            "action": "edit",
            "operations": [{"kind": "add_track", "track_type": "audio"}],
        },
    )
    assert not meta["editor_history"]["redo"]


def test_history_field_deltas_do_not_duplicate_whole_timeline():
    meta = {"timeline": normalize_timeline(timeline())}
    meta["timeline"]["extension"]["large_reference"] = "x" * 100000
    execute(
        meta,
        {
            "operation_id": "move",
            "action": "edit",
            "operations": [
                {"kind": "move", "track_id": "video", "clip_id": "clip", "position": "144000"}
            ],
        },
    )
    import json

    assert len(json.dumps(meta["editor_history"])) < 3000


def test_adding_clip_preserves_audio_track_and_batch_undo(editor):
    store, pid, _ = editor
    response = submit(
        editor,
        operations=[
            {"kind": "add_track", "track_type": "audio", "new_id": "audio"},
            {
                "kind": "add_clip",
                "track_id": "audio",
                "new_id": "audio-clip",
                "start_seconds": "1",
                "end_seconds": "2",
            },
        ],
    )
    assert response.status_code == 200, response.text
    audio = response.json()["timeline"]["tracks"][-1]
    assert audio["type"] == "audio"
    assert audio["clips"][0]["start_sample"] == "48000"
    assert submit(editor, action="undo").status_code == 200
    assert len(store.get(pid).meta["timeline"]["tracks"]) == 1


def test_track_order_and_professional_state_are_persistent_and_reversible(editor):
    response = submit(
        editor,
        operations=[
            {"kind": "add_track", "track_type": "audio", "new_id": "dialogue", "name": "Dialogue"},
            {"kind": "reorder_track", "track_id": "dialogue", "index": 0},
            {
                "kind": "set_track_state",
                "track_id": "dialogue",
                "muted": True,
                "solo": False,
                "record_armed": True,
                "input_monitoring": True,
            },
        ],
    )

    assert response.status_code == 200, response.text
    track = response.json()["timeline"]["tracks"][0]
    assert track == {
        "id": "dialogue",
        "type": "audio",
        "name": "Dialogue",
        "clips": [],
        "muted": True,
        "solo": False,
        "record_armed": True,
        "input_monitoring": True,
    }
    assert submit(editor, action="undo").status_code == 200
    assert [track["id"] for track in editor[0].get(editor[1]).meta["timeline"]["tracks"]] == ["video"]


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "set_track_state", "track_id": "video"},
        {"kind": "set_track_state", "track_id": "video", "muted": 1},
    ],
)
def test_track_state_rejects_missing_or_non_boolean_values(editor, operation):
    assert submit(editor, operations=[operation]).status_code == 422


def test_locked_track_state_requires_a_separate_unlock(editor):
    assert submit(
        editor,
        operations=[{"kind": "set_track_state", "track_id": "video", "locked": True}],
    ).status_code == 200
    assert submit(
        editor,
        operations=[{"kind": "set_track_state", "track_id": "video", "muted": True}],
    ).status_code == 422
    assert submit(
        editor,
        operations=[
            {"kind": "set_track_state", "track_id": "video", "locked": False, "muted": True}
        ],
    ).status_code == 422
    assert submit(
        editor,
        operations=[{"kind": "set_track_state", "track_id": "video", "locked": False}],
    ).status_code == 200


def test_repeated_source_trims_retain_fractional_resampling_phase():
    from fractions import Fraction

    from edmg_studio_backend.domain.editor_commands import _advance_source
    from edmg_studio_backend.domain.project_time import ProjectClock

    clip = {"data": {"source_in_s": 0, "source_sample_rate": 44100}}
    for _ in range(1000):
        _advance_source(clip, 1, ProjectClock())
    data = clip["data"]
    exact = Fraction(int(data["source_offset_sample"])) + Fraction(data["source_offset_remainder"])
    assert exact == Fraction(1000 * 44100, 48000)


def test_legacy_save_uses_same_history_and_exact_fields(editor):
    from edmg_studio_backend.api.routers import create_project_router

    store, pid, client = editor
    client.app.include_router(
        create_project_router(
            get_store=lambda: store,
            project_response=lambda p: {"project": p.__dict__},
            assess_health=lambda *_: {},
        )
    )
    assert (
        submit(
            editor,
            operations=[
                {"kind": "set_mute", "track_id": "video", "clip_id": "clip", "value": True}
            ],
        ).status_code
        == 200
    )
    current = deepcopy(store.get(pid).meta["timeline"])
    current["tracks"][0]["clips"][0]["start_s"] = 2
    response = client.post(
        f"/v1/projects/{pid}/timeline",
        json={"timeline": current, "expected_revision": store.get(pid).revision},
    )
    assert response.status_code == 200, response.text
    assert response.json()["timeline"]["tracks"][0]["clips"][0]["start_sample"] == "96000"
    undone = submit(editor, action="undo")
    assert undone.json()["timeline"]["tracks"][0]["clips"][0]["start_sample"] == "48000"


def test_property_camera_and_modulation_edits_are_persistent_and_reversible(editor):
    store, pid, _ = editor

    def add_command_targets(project):
        project.meta["timeline"]["tracks"].append(
            {
                "id": "motion",
                "type": "motion",
                "clips": [{"id": "motion-clip", "start_s": 0, "end_s": 5, "data": {}}],
            }
        )
        project.meta["timeline"]["camera"] = {
            "keyframes": [{"id": "camera-1", "t": 0, "zoom": 1.0}]
        }

    store.mutate(pid, add_command_targets)
    response = submit(
        editor,
        label="Edit prompt, camera, and modulation",
        operations=[
            {
                "kind": "set_clip_property",
                "track_id": "video",
                "clip_id": "clip",
                "field": "prompt",
                "value": "Updated prompt",
            },
            {
                "kind": "update_camera_keyframe",
                "keyframe_id": "camera-1",
                "values": {"t": 2.5, "zoom": 1.25, "pan_x": 4},
            },
            {
                "kind": "set_modulation",
                "track_id": "motion",
                "clip_id": "motion-clip",
                "field": "strength_schedule",
                "value": "0:(0.35), 24:(0.6)",
            },
        ],
    )
    assert response.status_code == 200, response.text
    edited = response.json()["timeline"]
    assert edited["tracks"][0]["clips"][0]["data"]["prompt"] == "Updated prompt"
    assert edited["camera"]["keyframes"][0]["t"] == 2.5
    assert edited["camera"]["keyframes"][0]["zoom"] == 1.25
    assert edited["tracks"][1]["clips"][0]["data"]["strength_schedule"] == "0:(0.35), 24:(0.6)"
    assert response.json()["history"]["undo_label"] == "Edit prompt, camera, and modulation"

    undone = submit(editor, action="undo")
    assert undone.status_code == 200
    restored = undone.json()["timeline"]
    assert "prompt" not in restored["tracks"][0]["clips"][0]["data"]
    assert restored["camera"]["keyframes"][0]["t"] == 0
    assert "strength_schedule" not in restored["tracks"][1]["clips"][0]["data"]
    assert undone.json()["history"]["redo_label"] == "Edit prompt, camera, and modulation"

    redone = submit(editor, action="redo")
    assert redone.status_code == 200
    assert redone.json()["timeline"] == edited


def test_source_property_edit_rebuilds_exact_sample_position(editor):
    store, pid, _ = editor

    def add_exact_source_position(project):
        data = project.meta["timeline"]["tracks"][0]["clips"][0].setdefault("data", {})
        data.update(
            {
                "source_in_s": 1.0,
                "source_sample_rate": 48_000,
                "source_offset_sample": "48000",
            }
        )

    store.mutate(pid, add_exact_source_position)
    response = submit(
        editor,
        operations=[
            {
                "kind": "set_clip_property",
                "track_id": "video",
                "clip_id": "clip",
                "field": "source_in_s",
                "value": 2.0,
            }
        ],
    )

    assert response.status_code == 200, response.text
    data = response.json()["timeline"]["tracks"][0]["clips"][0]["data"]
    assert data["source_in_s"] == 2.0
    assert data["source_offset_sample"] == "96000"


def test_camera_keyframe_add_delete_and_lock_are_command_safe(editor):
    store, pid, _ = editor
    store.mutate(pid, lambda project: project.meta["timeline"].update({"camera": {"keyframes": []}}))
    added = submit(
        editor,
        operations=[
            {
                "kind": "add_camera_keyframe",
                "new_id": "camera-new",
                "values": {"t": 1.5, "zoom": 1.1, "rotation_deg": 2},
            }
        ],
    )
    assert added.status_code == 200, added.text
    assert added.json()["timeline"]["camera"]["keyframes"][0]["id"] == "camera-new"
    deleted = submit(
        editor,
        operations=[{"kind": "delete_camera_keyframe", "keyframe_id": "camera-new"}],
    )
    assert deleted.status_code == 200
    assert deleted.json()["timeline"]["camera"]["keyframes"] == []
    assert submit(editor, action="undo").json()["timeline"]["camera"]["keyframes"][0]["id"] == "camera-new"

    store.mutate(pid, lambda project: project.meta["timeline"]["camera"].update({"locked": True}))
    rejected = submit(
        editor,
        operations=[
            {
                "kind": "update_camera_keyframe",
                "keyframe_id": "camera-new",
                "values": {"zoom": 2},
            }
        ],
    )
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            {
                "kind": "set_clip_property",
                "track_id": "video",
                "clip_id": "clip",
                "field": "source_path",
                "value": "outside.mp4",
            },
            "Unsupported clip property",
        ),
        (
            {
                "kind": "set_clip_property",
                "track_id": "video",
                "clip_id": "clip",
                "field": "speed",
                "value": 10,
            },
            "Playback speed",
        ),
        (
            {
                "kind": "set_modulation",
                "track_id": "video",
                "clip_id": "clip",
                "field": "strength_schedule",
                "value": "0:(1)",
            },
            "motion or automation track",
        ),
    ],
)
def test_typed_editor_operations_reject_unsafe_or_unbounded_values(editor, operation, message):
    store, pid, _ = editor
    before = deepcopy(store.get(pid).meta)
    response = submit(editor, operations=[operation])
    assert response.status_code == 422
    assert message in response.text
    assert store.get(pid).meta == before
