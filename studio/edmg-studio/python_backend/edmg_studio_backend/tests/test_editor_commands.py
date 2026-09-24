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


def test_marker_commands_are_exact_sorted_persistent_and_reversible(editor):
    first = submit(
        editor,
        operations=[
            {
                "kind": "add_marker",
                "new_id": "outro",
                "name": "Outro",
                "position": "9007199254740993",
            },
            {"kind": "add_marker", "new_id": "intro", "name": "Intro", "position": "24000"},
        ],
    )
    assert first.status_code == 200, first.text
    assert [marker["id"] for marker in first.json()["timeline"]["markers"]] == ["intro", "outro"]
    assert first.json()["timeline"]["markers"][1]["position_sample"] == "9007199254740993"

    moved = submit(
        editor,
        operations=[{"kind": "move_marker", "marker_id": "outro", "position": "12000"}],
    )
    assert moved.status_code == 200, moved.text
    assert [marker["id"] for marker in moved.json()["timeline"]["markers"]] == ["outro", "intro"]
    assert submit(editor, action="undo").json()["timeline"] == first.json()["timeline"]
    deleted = submit(
        editor,
        operations=[{"kind": "delete_marker", "marker_id": "intro"}],
    )
    assert deleted.status_code == 200, deleted.text
    assert [marker["id"] for marker in deleted.json()["timeline"]["markers"]] == ["outro"]


def test_marker_commands_reject_duplicate_ids_and_invalid_positions(editor):
    assert (
        submit(
            editor,
            operations=[
                {"kind": "add_marker", "new_id": "clip", "name": "Duplicate", "position": "0"}
            ],
        ).status_code
        == 422
    )
    assert (
        submit(
            editor,
            operations=[{"kind": "add_marker", "new_id": "bad", "name": "Bad", "position": "-1"}],
        ).status_code
        == 422
    )


def test_replacement_marker_time_edit_regenerates_stale_exact_position():
    baseline = normalize_timeline(
        {
            "timebase": {"sample_rate": 48000, "frame_rate": {"numerator": 30, "denominator": 1}},
            "tracks": [],
            "markers": [{"id": "cue", "name": "Cue", "time_s": 1.0}],
        }
    )
    proposed = deepcopy(baseline)
    proposed["markers"][0]["time_s"] = 2.0

    normalized = normalize_timeline(proposed, baseline)

    assert normalized["markers"][0]["position_sample"] == "96000"
    assert normalized["markers"][0]["time_s"] == 2.0


def test_legacy_marker_time_is_preserved_without_changing_its_shape():
    marker = {"id": "planner", "t": 1.25, "label": "Cue"}

    normalized = normalize_timeline({"tracks": [], "markers": [deepcopy(marker)]})

    assert normalized["markers"] == [marker]


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
        "schema_version": 1,
        "id": "artifact-generated",
        "kind": "video",
        "path": "outputs/videos/generated.mp4",
        "content_hash": "abc",
        "engine": "comfyui",
        "provider": "local",
        "model": {"id": "hunyuan-video", "revision": "r2"},
        "project_revision": 3,
        "plan_revision": "plan-2",
        "source_assets": [{"id": "audio-source"}],
        "lineage": {"parents": ["artifact-parent"]},
    }
    video.with_suffix(".mp4.artifact.json").write_text(json.dumps(manifest), encoding="utf-8")
    body = {
        "operation_id": "insert-generated",
        "expected_revision": store.get(pid).revision,
        "artifact_path": "outputs/videos/generated.mp4",
        "start_seconds": 2,
        "duration_seconds": 3,
    }
    url = f"/v1/projects/{pid}/editor/insert-artifact"
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["replayed"] is True
    project = store.get(pid)
    assert project.meta["media_pool"] == [
        {
            "id": "artifact-generated",
            "version_id": "artifact-generated",
            "artifact_id": "artifact-generated",
            "path": "outputs/videos/generated.mp4",
            "kind": "video",
            "manifest_path": "outputs/videos/generated.mp4.artifact.json",
            "content_hash": "abc",
            "renderer_id": "comfyui",
            "provider_id": "local",
            "model": {"id": "hunyuan-video", "revision": "r2"},
            "project_revision": 3,
            "plan_revision": "plan-2",
            "source_assets": [{"id": "audio-source"}],
            "lineage": {"parents": ["artifact-parent"]},
        }
    ]
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
    job_store = SimpleNamespace(
        get=lambda project_id, job_id: job if (project_id, job_id) == (pid, job.id) else None
    )
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
    meta["timeline"]["tracks"][0]["clips"][0]["muted"] = True
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


def test_add_clip_accepts_exact_samples_and_preserves_media_asset_on_undo(editor):
    store, pid, _ = editor
    project = store.get(pid)
    project.meta["timeline"]["media_pool"] = [{"id": "audio-asset", "path": "assets/audio/source.wav"}]
    store.save(project)

    response = submit(
        editor,
        operations=[
            {"kind": "add_track", "track_type": "audio", "new_id": "audio"},
            {
                "kind": "add_clip", "track_id": "audio", "new_id": "audio-clip",
                "start_sample": "17", "end_sample": "48017", "media_asset_id": "audio-asset",
            },
        ],
    )

    assert response.status_code == 200, response.text
    assert response.json()["timeline"]["tracks"][-1]["clips"][0]["start_sample"] == "17"
    assert submit(editor, action="undo").status_code == 200
    assert store.get(pid).meta["timeline"]["media_pool"][0]["id"] == "audio-asset"


@pytest.mark.parametrize(
    "clip",
    [
        {"start_sample": "01", "end_sample": "2"},
        {"start_sample": 1, "end_sample": 2},
        {"start_sample": "1", "end_sample": "2", "start_seconds": 0},
        {"start_sample": "1", "end_sample": "2", "media_asset_id": "missing"},
    ],
)
def test_add_clip_rejects_invalid_exact_samples_and_unknown_media(editor, clip):
    response = submit(
        editor,
        operations=[
            {"kind": "add_track", "track_type": "audio", "new_id": "audio"},
            {"kind": "add_clip", "track_id": "audio", "new_id": "audio-clip", **clip},
        ],
    )

    assert response.status_code == 422


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
    assert [track["id"] for track in editor[0].get(editor[1]).meta["timeline"]["tracks"]] == [
        "video"
    ]


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
    assert (
        submit(
            editor,
            operations=[{"kind": "set_track_state", "track_id": "video", "locked": True}],
        ).status_code
        == 200
    )
    assert (
        submit(
            editor,
            operations=[{"kind": "set_track_state", "track_id": "video", "muted": True}],
        ).status_code
        == 422
    )
    assert (
        submit(
            editor,
            operations=[
                {"kind": "set_track_state", "track_id": "video", "locked": False, "muted": True}
            ],
        ).status_code
        == 422
    )
    assert (
        submit(
            editor,
            operations=[{"kind": "set_track_state", "track_id": "video", "locked": False}],
        ).status_code
        == 200
    )


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
    store.mutate(
        pid, lambda project: project.meta["timeline"].update({"camera": {"keyframes": []}})
    )
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
    assert (
        submit(editor, action="undo").json()["timeline"]["camera"]["keyframes"][0]["id"]
        == "camera-new"
    )

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


def phase6_timeline():
    value = timeline()
    value["media_pool"] = [{"id": "asset", "path": "take.wav", "vendor": {"keep": True}}]
    value["tracks"][0]["clips"] = [
        {"id": "previous", "start_sample": "0", "end_sample": "48000", "data": {}},
        value["tracks"][0]["clips"][0],
        {"id": "next", "start_sample": "240000", "end_sample": "336000", "data": {}},
    ]
    value["editing"] = {
        "schema_version": 1,
        "automation_lanes": [],
        "takes": [],
        "comp_ranges": [],
        "crossfades": [],
        "vendor": {"keep": True},
    }
    return normalize_timeline(value)


def test_phase6_automation_exact_samples_extensions_and_undo_redo():
    meta = {"timeline": phase6_timeline()}
    command = {
        "operation_id": "phase6-auto",
        "action": "edit",
        "label": "Automation",
        "operations": [
            {
                "kind": "add_automation_lane",
                "lane_id": "gain",
                "track_id": "video",
                "target": "volume",
                "mode": "touch",
                "min_value": 0,
                "max_value": 2,
            },
            {
                "kind": "upsert_automation_point",
                "lane_id": "gain",
                "point_id": "point",
                "sample": "9007199254740993",
                "value": 1.25,
                "curve": "smooth",
                "tension": 0.2,
            },
        ],
    }
    execute(meta, command)
    lane = meta["timeline"]["editing"]["automation_lanes"][0]
    assert lane["points"][0]["sample"] == "9007199254740993"
    committed = deepcopy(meta["timeline"])
    execute(meta, {"operation_id": "undo-auto", "action": "undo"})
    assert meta["timeline"]["editing"]["automation_lanes"] == []
    assert committed["editing"]["automation_lanes"][0]["id"] == "gain"
    execute(meta, {"operation_id": "redo-auto", "action": "redo"})
    assert (
        meta["timeline"]["editing"]["automation_lanes"][0]["points"][0]["sample"]
        == "9007199254740993"
    )
    assert committed["editing"]["vendor"] == {"keep": True}
    assert meta["timeline"]["editing"]["vendor"] == {"keep": True}


def test_phase6_takes_comp_fades_process_and_crossfade():
    meta = {"timeline": phase6_timeline()}
    execute(
        meta,
        {
            "operation_id": "phase6-edit",
            "action": "edit",
            "operations": [
                {
                    "kind": "add_take",
                    "track_id": "video",
                    "clip_id": "clip",
                    "take_id": "take",
                    "media_asset_id": "asset",
                },
                {"kind": "select_take", "track_id": "video", "clip_id": "clip", "take_id": "take"},
                {
                    "kind": "set_comp_range",
                    "track_id": "video",
                    "clip_id": "clip",
                    "comp_id": "comp",
                    "take_id": "take",
                    "start_sample": "48000",
                    "end_sample": "96000",
                },
                {
                    "kind": "set_fades",
                    "track_id": "video",
                    "clip_id": "clip",
                    "fade_in_samples": "1200",
                    "fade_out_samples": "2400",
                },
                {
                    "kind": "set_process",
                    "track_id": "video",
                    "clip_id": "clip",
                    "playback_rate": 1.25,
                    "stretch_ratio": 0.8,
                    "algorithm": "resample",
                },
                {"kind": "slide", "track_id": "video", "clip_id": "clip", "delta_samples": "12000"},
                {
                    "kind": "nudge",
                    "track_id": "video",
                    "clip_id": "next",
                    "delta_samples": "-24000",
                },
                {
                    "kind": "set_crossfade",
                    "track_id": "video",
                    "left_clip_id": "clip",
                    "right_clip_id": "next",
                    "crossfade_id": "xf",
                    "start_sample": "240000",
                    "end_sample": "252000",
                    "curve": "s_curve",
                },
            ],
        },
    )
    editing = meta["timeline"]["editing"]
    assert meta["timeline"]["tracks"][0]["clips"][1]["data"]["active_take_id"] == "take"
    assert editing["comp_ranges"][0]["start_sample"] == "60000"
    assert editing["crossfades"][0]["id"] == "xf"
    assert meta["timeline"]["tracks"][0]["clips"][1]["data"]["process"]["stretch_ratio"] == 0.8


def test_phase6_project_media_pool_validates_takes_without_copying_into_timeline(editor):
    store, pid, client = editor
    project = store.get(pid)
    project.meta["media_pool"] = [{"id": "project-asset", "path": "take.wav"}]
    project.meta["timeline"] = phase6_timeline()
    project.meta["timeline"].pop("media_pool")
    store.save(project)

    response = submit(editor, operations=[{
        "kind": "add_take", "track_id": "video", "clip_id": "clip",
        "take_id": "project-take", "media_asset_id": "project-asset",
    }])

    assert response.status_code == 200, response.text
    assert response.json()["timeline"]["editing"]["takes"][0]["media_asset_id"] == "project-asset"
    assert "media_pool" not in response.json()["timeline"]
    assert client.get(f"/v1/projects/{pid}/editor").status_code == 200


def test_phase6_move_and_trim_reconcile_owned_comp_ranges():
    base = phase6_timeline()
    base["editing"]["takes"] = [{"id": "take", "clip_id": "clip", "media_asset_id": "asset"}]
    base["editing"]["comp_ranges"] = [
        {"id": "left", "clip_id": "clip", "take_id": "take", "start_sample": "48000", "end_sample": "72000"},
        {"id": "middle", "clip_id": "clip", "take_id": "take", "start_sample": "72000", "end_sample": "168000"},
        {"id": "right", "clip_id": "clip", "take_id": "take", "start_sample": "168000", "end_sample": "240000"},
    ]
    meta = {"timeline": normalize_timeline(base)}
    execute(meta, {"operation_id": "move-comp", "action": "edit", "operations": [
        {"kind": "move", "track_id": "video", "clip_id": "clip", "position": "60000"}
    ]})
    assert [(c["start_sample"], c["end_sample"]) for c in meta["timeline"]["editing"]["comp_ranges"]] == [
        ("60000", "84000"), ("84000", "180000"), ("180000", "252000")
    ]
    execute(meta, {"operation_id": "trim-comp", "action": "edit", "operations": [
        {"kind": "trim", "track_id": "video", "clip_id": "clip", "edge": "start", "position": "90000"},
        {"kind": "trim", "track_id": "video", "clip_id": "clip", "edge": "end", "position": "200000"},
    ]})
    comps = meta["timeline"]["editing"]["comp_ranges"]
    assert [(c["id"], c["take_id"], c["start_sample"], c["end_sample"]) for c in comps] == [
        ("middle", "take", "90000", "180000"), ("right", "take", "180000", "200000")
    ]


def crossfade_timeline():
    value = phase6_timeline()
    previous, clip, next_clip = value["tracks"][0]["clips"]
    previous["start_sample"], previous["end_sample"] = "0", "100"
    clip["start_sample"], clip["end_sample"] = "80", "180"
    next_clip["start_sample"], next_clip["end_sample"] = "160", "260"
    value["editing"]["crossfades"] = [
        {"id": "left-xf", "track_id": "video", "left_clip_id": "previous", "right_clip_id": "clip",
         "start_sample": "80", "end_sample": "100", "curve": "linear"},
        {"id": "right-xf", "track_id": "video", "left_clip_id": "clip", "right_clip_id": "next",
         "start_sample": "160", "end_sample": "180", "curve": "equal_power"},
    ]
    return normalize_timeline(value)


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ({"kind": "move", "track_id": "video", "clip_id": "clip", "position": "90"},
         [("left-xf", "90", "100"), ("right-xf", "160", "180")]),
        ({"kind": "trim", "track_id": "video", "clip_id": "clip", "edge": "start", "position": "90"},
         [("left-xf", "90", "100"), ("right-xf", "160", "180")]),
        ({"kind": "nudge", "track_id": "video", "clip_id": "clip", "delta_samples": "10"},
         [("left-xf", "90", "100"), ("right-xf", "160", "180")]),
        ({"kind": "ripple", "track_id": "video", "from_sample": "0", "delta_samples": "10"},
         [("left-xf", "90", "110"), ("right-xf", "170", "190")]),
        ({"kind": "range_edit", "track_id": "video", "start_sample": "0", "end_sample": "260",
          "range_action": "move", "delta_samples": "10"},
         [("left-xf", "90", "110"), ("right-xf", "170", "190")]),
        ({"kind": "range_edit", "track_id": "video", "start_sample": "80", "end_sample": "180",
          "range_action": "move", "delta_samples": "10"},
         [("left-xf", "90", "100"), ("right-xf", "160", "180")]),
        ({"kind": "move", "track_id": "video", "clip_id": "clip", "position": "110"},
         [("right-xf", "160", "180")]),
    ],
)
def test_phase6_bounds_changes_reconcile_crossfades_and_history(operation, expected):
    meta = {"timeline": crossfade_timeline()}
    before = deepcopy(meta["timeline"])
    execute(meta, {"operation_id": f"xf-{operation['kind']}", "action": "edit", "operations": [operation]})
    committed = deepcopy(meta["timeline"])
    assert [(item["id"], item["start_sample"], item["end_sample"])
            for item in committed["editing"]["crossfades"]] == expected
    execute(meta, {"operation_id": f"undo-xf-{operation['kind']}", "action": "undo"})
    assert meta["timeline"] == before
    execute(meta, {"operation_id": f"redo-xf-{operation['kind']}", "action": "redo"})
    assert meta["timeline"] == committed


def test_phase6_existing_editing_ids_cannot_change_owners_and_rejections_are_atomic():
    base = crossfade_timeline()
    base["editing"]["takes"] = [
        {"id": "take-a", "clip_id": "previous", "media_asset_id": "asset"},
        {"id": "take-b", "clip_id": "clip", "media_asset_id": "asset"},
    ]
    base["editing"]["comp_ranges"] = [
        {"id": "owned-comp", "clip_id": "previous", "take_id": "take-a",
         "start_sample": "10", "end_sample": "20"}
    ]
    base["tracks"][0]["clips"][0]["locked"] = True
    meta = {"timeline": normalize_timeline(base)}
    for operation, message in (
        ({"kind": "set_comp_range", "track_id": "video", "clip_id": "clip", "comp_id": "owned-comp",
          "take_id": "take-b", "start_sample": "100", "end_sample": "120"}, "owned by another clip"),
        ({"kind": "set_crossfade", "track_id": "video", "left_clip_id": "clip", "right_clip_id": "next",
          "crossfade_id": "left-xf", "start_sample": "160", "end_sample": "170"}, "different endpoints"),
    ):
        before = deepcopy(meta)
        with pytest.raises(ValueError, match=message):
            execute(meta, {"operation_id": f"steal-{operation['kind']}", "action": "edit", "operations": [operation]})
        assert meta == before


@pytest.mark.parametrize(
    ("delta", "left_end", "right_start"),
    [(12000, "59000", "252000"), (-12000, "35000", "228000")],
)
def test_phase6_slide_reconciles_neighbor_sources_comps_crossfades_and_history(
    delta, left_end, right_start
):
    base = phase6_timeline()
    clips = base["tracks"][0]["clips"]
    for clip, offset in zip(clips, (0, 48000, 240000), strict=True):
        clip["data"].update(
            source_sample_rate=48000,
            source_offset_sample=str(offset),
            source_offset_remainder="0",
        )
    base["editing"]["takes"] = [
        {"id": "left-take", "clip_id": "previous", "media_asset_id": "asset"},
        {"id": "center-take", "clip_id": "clip", "media_asset_id": "asset"},
        {"id": "right-take", "clip_id": "next", "media_asset_id": "asset"},
    ]
    base["editing"]["comp_ranges"] = [
        {"id": "left-comp", "clip_id": "previous", "take_id": "left-take", "start_sample": "36000", "end_sample": "48000"},
        {"id": "center-comp", "clip_id": "clip", "take_id": "center-take", "start_sample": "60000", "end_sample": "228000"},
        {"id": "right-comp", "clip_id": "next", "take_id": "right-take", "start_sample": "240000", "end_sample": "264000"},
    ]
    base["editing"]["crossfades"] = [
        {"id": "invalidated", "track_id": "video", "left_clip_id": "previous", "right_clip_id": "clip", "start_sample": "47000", "end_sample": "48000", "curve": "linear"}
    ]
    # Make the crossfade initially valid without changing the slide-neighbor ordering.
    clips[1]["start_sample"] = "47000"
    meta = {"timeline": normalize_timeline(base)}
    before = deepcopy(meta["timeline"])
    execute(meta, {"operation_id": f"slide-{delta}", "action": "edit", "operations": [
        {"kind": "slide", "track_id": "video", "clip_id": "clip", "delta_samples": str(delta)}
    ]})
    committed = deepcopy(meta["timeline"])
    result_clips = committed["tracks"][0]["clips"]
    assert result_clips[0]["data"]["source_end_sample"] == left_end
    assert result_clips[2]["data"]["source_offset_sample"] == right_start
    assert all(
        int(next(c for c in result_clips if c["id"] == comp["clip_id"])["start_sample"])
        <= int(comp["start_sample"]) < int(comp["end_sample"])
        <= int(next(c for c in result_clips if c["id"] == comp["clip_id"])["end_sample"])
        for comp in committed["editing"]["comp_ranges"]
    )
    assert committed["editing"]["crossfades"] == []
    execute(meta, {"operation_id": f"undo-slide-{delta}", "action": "undo"})
    assert meta["timeline"] == before
    execute(meta, {"operation_id": f"redo-slide-{delta}", "action": "redo"})
    assert meta["timeline"] == committed


def test_phase6_direct_and_range_duplicate_clone_take_arrangements():
    base = phase6_timeline()
    base["editing"]["takes"] = [
        {"id": "take-a", "clip_id": "clip", "media_asset_id": "asset"},
        {"id": "take-b", "clip_id": "clip", "media_asset_id": "asset"},
    ]
    base["tracks"][0]["clips"][1]["data"]["active_take_id"] = "take-b"
    base["editing"]["comp_ranges"] = [
        {"id": "comp", "clip_id": "clip", "take_id": "take-b", "start_sample": "72000", "end_sample": "120000"}
    ]
    meta = {"timeline": normalize_timeline(base)}
    execute(meta, {"operation_id": "duplicate-direct", "action": "edit", "operations": [{
        "kind": "duplicate", "track_id": "video", "clip_id": "clip", "new_id": "copy",
        "new_take_ids": ["copy-take-a", "copy-take-b"], "new_comp_ids": ["copy-comp"],
    }]})
    copy = next(c for c in meta["timeline"]["tracks"][0]["clips"] if c["id"] == "copy")
    assert copy["data"]["active_take_id"] == "copy-take-b"
    assert ("copy-comp", "copy", "copy-take-b", "264000", "312000") in {
        (c["id"], c["clip_id"], c["take_id"], c["start_sample"], c["end_sample"])
        for c in meta["timeline"]["editing"]["comp_ranges"]
    }

    execute(meta, {"operation_id": "duplicate-range", "action": "edit", "operations": [{
        "kind": "range_edit", "track_id": "video", "start_sample": "48000", "end_sample": "240000",
        "range_action": "duplicate", "delta_samples": "400000", "new_ids": ["range-copy"],
        "new_take_ids": ["range-take-a", "range-take-b"], "new_comp_ids": ["range-comp"],
    }]})
    range_copy = next(c for c in meta["timeline"]["tracks"][0]["clips"] if c["id"] == "range-copy")
    assert range_copy["data"]["active_take_id"] == "range-take-b"
    assert next(c for c in meta["timeline"]["editing"]["comp_ranges"] if c["id"] == "range-comp")["start_sample"] == "472000"


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "duplicate", "track_id": "video", "clip_id": "clip", "new_id": "copy", "new_take_ids": [], "new_comp_ids": []},
        {"kind": "duplicate", "track_id": "video", "clip_id": "clip", "new_id": "copy", "new_take_ids": ["take"], "new_comp_ids": ["new-comp"]},
        {"kind": "duplicate", "track_id": "video", "clip_id": "clip", "new_id": "copy", "new_take_ids": ["new-id"], "new_comp_ids": ["new-id"]},
        {"kind": "range_edit", "track_id": "video", "start_sample": "48000", "end_sample": "240000", "range_action": "duplicate", "delta_samples": "300000", "new_ids": ["copy"], "new_take_ids": ["new-take"], "new_comp_ids": []},
    ],
)
def test_phase6_duplicate_rejects_missing_or_used_editing_ids_atomically(operation):
    base = phase6_timeline()
    base["editing"]["takes"] = [{"id": "take", "clip_id": "clip", "media_asset_id": "asset"}]
    base["editing"]["comp_ranges"] = [{"id": "comp", "clip_id": "clip", "take_id": "take", "start_sample": "72000", "end_sample": "120000"}]
    meta = {"timeline": normalize_timeline(base)}
    before = deepcopy(meta)
    with pytest.raises(ValueError):
        execute(meta, {"operation_id": "bad-duplicate", "action": "edit", "operations": [operation]})
    assert meta == before


def test_phase6_split_preserves_takes_partitions_comps_and_undo_redo():
    base = phase6_timeline()
    base["editing"]["takes"] = [
        {"id": "take-a", "clip_id": "clip", "media_asset_id": "asset"},
        {"id": "take-b", "clip_id": "clip", "media_asset_id": "asset"},
    ]
    base["tracks"][0]["clips"][1]["data"]["active_take_id"] = "take-b"
    base["editing"]["comp_ranges"] = [
        {"id": "left", "clip_id": "clip", "take_id": "take-a", "start_sample": "48000", "end_sample": "72000"},
        {"id": "cross", "clip_id": "clip", "take_id": "take-b", "start_sample": "72000", "end_sample": "168000"},
        {"id": "right", "clip_id": "clip", "take_id": "take-a", "start_sample": "168000", "end_sample": "240000"},
    ]
    meta = {"timeline": normalize_timeline(base)}
    before = deepcopy(meta["timeline"])
    operation = {
        "kind": "split", "track_id": "video", "clip_id": "clip", "position": "144000",
        "new_id": "split-right", "right_take_ids": ["right-take-a", "right-take-b"],
        "right_comp_ids": ["right-cross", "right-only"],
    }
    execute(meta, {"operation_id": "split-editing", "action": "edit", "operations": [operation]})
    committed = deepcopy(meta["timeline"])
    right_clip = meta["timeline"]["tracks"][0]["clips"][2]
    assert right_clip["data"]["active_take_id"] == "right-take-b"
    assert {(t["id"], t["clip_id"]) for t in committed["editing"]["takes"]} >= {
        ("right-take-a", "split-right"), ("right-take-b", "split-right")
    }
    assert [(c["id"], c["clip_id"], c["take_id"], c["start_sample"], c["end_sample"]) for c in committed["editing"]["comp_ranges"]] == [
        ("left", "clip", "take-a", "48000", "72000"),
        ("cross", "clip", "take-b", "72000", "144000"),
        ("right-cross", "split-right", "right-take-b", "144000", "168000"),
        ("right-only", "split-right", "right-take-a", "168000", "240000"),
    ]
    execute(meta, {"operation_id": "undo-split-editing", "action": "undo"})
    assert meta["timeline"] == before
    execute(meta, {"operation_id": "redo-split-editing", "action": "redo"})
    assert meta["timeline"] == committed


def test_phase6_split_requires_all_deterministic_editing_ids_atomically():
    base = phase6_timeline()
    base["editing"]["takes"] = [{"id": "take", "clip_id": "clip", "media_asset_id": "asset"}]
    base["editing"]["comp_ranges"] = [{"id": "comp", "clip_id": "clip", "take_id": "take", "start_sample": "120000", "end_sample": "168000"}]
    meta = {"timeline": normalize_timeline(base)}
    before = deepcopy(meta)
    with pytest.raises(ValueError, match="deterministic IDs"):
        execute(meta, {"operation_id": "bad-split", "action": "edit", "operations": [{
            "kind": "split", "track_id": "video", "clip_id": "clip", "position": "144000", "new_id": "right"
        }]})
    assert meta == before


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (90, [("left-xf", "previous", "clip", "80", "90")]),
        (150, [("left-xf", "previous", "clip", "80", "100")]),
    ],
)
def test_phase6_split_reconciles_crossfades_without_transferring_endpoints(position, expected):
    meta = {"timeline": crossfade_timeline()}
    execute(meta, {"operation_id": f"split-xf-{position}", "action": "edit", "operations": [{
        "kind": "split", "track_id": "video", "clip_id": "clip", "position": str(position),
        "new_id": "split-right", "right_take_ids": [], "right_comp_ids": [],
    }]})

    assert [
        (item["id"], item["left_clip_id"], item["right_clip_id"], item["start_sample"], item["end_sample"])
        for item in meta["timeline"]["editing"]["crossfades"]
    ] == expected
    assert all(
        "split-right" not in {item["left_clip_id"], item["right_clip_id"]}
        for item in meta["timeline"]["editing"]["crossfades"]
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["editing"]["automation_lanes"][0].update(track_id="audio"),
        lambda value: value["editing"]["takes"][1].update(clip_id="next"),
        lambda value: value["editing"]["comp_ranges"][0].update(clip_id="clip", take_id="take-b"),
        lambda value: value["editing"]["crossfades"][0].update(
            left_clip_id="clip", right_clip_id="next", start_sample="160", end_sample="170"
        ),
    ],
)
def test_phase6_replacement_rejects_editing_owner_reassignment_atomically(editor, mutate):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["tracks"].append({"id": "audio", "type": "audio", "clips": []})
    base["editing"]["automation_lanes"] = [{
        "id": "gain", "track_id": "video", "target": "volume", "mode": "read",
        "min_value": 0, "max_value": 1, "points": [],
    }]
    base["editing"]["takes"] = [
        {"id": "take-a", "clip_id": "previous", "media_asset_id": "asset"},
        {"id": "take-b", "clip_id": "clip", "media_asset_id": "asset"},
    ]
    base["editing"]["comp_ranges"] = [{
        "id": "owned-comp", "clip_id": "previous", "take_id": "take-a",
        "start_sample": "10", "end_sample": "20",
    }]
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    before = deepcopy(store.get(pid).meta)
    proposed = deepcopy(base)
    mutate(proposed)

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 422
    assert store.get(pid).meta == before


def test_phase6_replacement_allows_same_owner_take_and_lane_updates(editor):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["editing"]["automation_lanes"] = [{
        "id": "gain", "track_id": "video", "target": "volume", "mode": "read",
        "min_value": 0, "max_value": 1, "points": [],
    }]
    base["editing"]["takes"] = [
        {"id": "take", "clip_id": "clip", "media_asset_id": "asset"},
    ]
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    proposed = deepcopy(base)
    proposed["editing"]["automation_lanes"][0]["mode"] = "write"
    proposed["editing"]["takes"][0]["name"] = "Alternate"

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 200, response.text
    editing = response.json()["timeline"]["editing"]
    assert editing["automation_lanes"][0]["mode"] == "write"
    assert editing["takes"][0]["name"] == "Alternate"


def _minimal_editing_records(name, count):
    if name == "automation_lanes":
        return [
            {"id": f"lane-{index}", "track_id": "video", "target": "volume", "mode": "read",
             "min_value": 0, "max_value": 1, "points": []}
            for index in range(count)
        ]
    if name == "takes":
        return [
            {"id": f"take-{index}", "clip_id": "clip", "media_asset_id": "asset"}
            for index in range(count)
        ]
    if name == "comp_ranges":
        return [
            {"id": f"comp-{index}", "clip_id": "clip", "take_id": "take",
             "start_sample": str(index + 80), "end_sample": str(index + 81)}
            for index in range(count)
        ]
    return [
        {"id": f"crossfade-{index}", "track_id": "video", "left_clip_id": "previous",
         "right_clip_id": "clip", "start_sample": "80", "end_sample": "90"}
        for index in range(count)
    ]


@pytest.mark.parametrize("name", ["automation_lanes", "takes", "comp_ranges", "crossfades"])
def test_phase6_editing_collection_accepts_exact_limit(name):
    value = crossfade_timeline()
    value["tracks"][0]["clips"][1]["end_sample"] = "20000"
    value["editing"] = {
        "schema_version": 1,
        "automation_lanes": [],
        "takes": [],
        "comp_ranges": [],
        "crossfades": [],
    }
    if name == "comp_ranges":
        value["editing"]["takes"] = [
            {"id": "take", "clip_id": "clip", "media_asset_id": "asset"},
        ]
    value["editing"][name] = _minimal_editing_records(name, 10_000)

    assert len(normalize_timeline(value)["editing"][name]) == 10_000


@pytest.mark.parametrize("name", ["automation_lanes", "takes", "comp_ranges", "crossfades"])
def test_phase6_editing_collection_rejects_above_limit(name):
    value = phase6_timeline()
    value["editing"][name] = [{}] * 10_001

    with pytest.raises(ValueError, match="at most 10000"):
        normalize_timeline(value)


@pytest.mark.parametrize("record_type", ["automation_lanes", "takes", "comp_ranges", "crossfades"])
@pytest.mark.parametrize("change", ["create", "update", "delete"])
def test_phase6_replacement_rejects_locked_owner_editing_mutations_atomically(
    editor, record_type, change
):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["tracks"][0]["locked"] = True
    base["editing"]["automation_lanes"] = [{
        "id": "gain", "track_id": "video", "target": "volume", "mode": "read",
        "min_value": 0, "max_value": 1, "points": [],
    }]
    base["editing"]["takes"] = [{
        "id": "take", "clip_id": "clip", "media_asset_id": "asset",
    }]
    base["editing"]["comp_ranges"] = [{
        "id": "comp", "clip_id": "clip", "take_id": "take",
        "start_sample": "100", "end_sample": "120",
    }]
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    before = deepcopy(store.get(pid).meta)
    proposed = deepcopy(base)
    if change == "create":
        additions = {
            "automation_lanes": {
                "id": "pan", "track_id": "video", "target": "pan", "mode": "read",
                "min_value": -1, "max_value": 1, "points": [],
            },
            "takes": {"id": "take-new", "clip_id": "clip", "media_asset_id": "asset"},
            "comp_ranges": {
                "id": "comp-new", "clip_id": "clip", "take_id": "take",
                "start_sample": "120", "end_sample": "140",
            },
            "crossfades": {
                "id": "crossfade-new", "track_id": "video", "left_clip_id": "previous",
                "right_clip_id": "clip", "start_sample": "80", "end_sample": "90",
                "curve": "linear",
            },
        }
        proposed["editing"][record_type].append(additions[record_type])
    elif change == "delete":
        proposed["editing"][record_type] = []
        if record_type == "takes":
            proposed["editing"]["comp_ranges"] = []
    else:
        updates = {
            "automation_lanes": ("mode", "write"),
            "takes": ("name", "Alternate"),
            "comp_ranges": ("end_sample", "130"),
            "crossfades": ("curve", "equal_power"),
        }
        key, value = updates[record_type]
        proposed["editing"][record_type][0][key] = value

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 422
    assert store.get(pid).meta == before


def test_phase6_replacement_rejects_unlock_plus_editing_mutation_atomically(editor):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["tracks"][0]["locked"] = True
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    before = deepcopy(store.get(pid).meta)
    proposed = deepcopy(base)
    proposed["tracks"][0]["locked"] = False
    proposed["editing"]["crossfades"][0]["curve"] = "equal_power"

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 422
    assert store.get(pid).meta == before


@pytest.mark.parametrize("record_type", ["takes", "comp_ranges", "crossfades"])
def test_phase6_replacement_rejects_locked_clip_editing_updates_atomically(editor, record_type):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["tracks"][0]["clips"][1]["locked"] = True
    base["editing"]["takes"] = [{
        "id": "take", "clip_id": "clip", "media_asset_id": "asset",
    }]
    base["editing"]["comp_ranges"] = [{
        "id": "comp", "clip_id": "clip", "take_id": "take",
        "start_sample": "100", "end_sample": "120",
    }]
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    before = deepcopy(store.get(pid).meta)
    proposed = deepcopy(base)
    key, value = {
        "takes": ("name", "Alternate"),
        "comp_ranges": ("end_sample", "130"),
        "crossfades": ("curve", "equal_power"),
    }[record_type]
    proposed["editing"][record_type][0][key] = value

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 422
    assert store.get(pid).meta == before


def test_phase6_replacement_allows_explicit_owner_unlock_without_editing_mutation(editor):
    store, pid, _ = editor
    base = crossfade_timeline()
    base["tracks"][0]["locked"] = True
    store.mutate(pid, lambda project: project.meta.update(timeline=deepcopy(base)))
    proposed = deepcopy(base)
    proposed["tracks"][0]["locked"] = False

    response = submit(editor, action="replace", timeline=proposed)

    assert response.status_code == 200, response.text
    assert response.json()["timeline"]["tracks"][0]["locked"] is False


def test_phase6_take_source_range_active_take_and_typed_extensions_round_trip():
    base = phase6_timeline()
    base["tracks"][0]["clips"][1]["data"].update(
        {
            "fades": {
                "in_samples": "1",
                "out_samples": "2",
                "curve": "linear",
                "vendor": "fade",
            },
            "process": {
                "playback_rate": 1,
                "stretch_ratio": 1,
                "algorithm": "resample",
                "vendor": "process",
            },
        }
    )
    meta = {"timeline": normalize_timeline(base)}
    execute(
        meta,
        {
            "operation_id": "source-range",
            "action": "edit",
            "operations": [
                {
                    "kind": "add_take",
                    "track_id": "video",
                    "clip_id": "clip",
                    "take_id": "take",
                    "media_asset_id": "asset",
                    "source_range": {
                        "sample_rate": 44100,
                        "start_sample": "9007199254740993",
                        "start_remainder": "1/2",
                        "end_sample": "9007199254741993",
                        "end_remainder": "-1/2",
                        "vendor": True,
                    },
                },
                {"kind": "select_take", "track_id": "video", "clip_id": "clip", "take_id": "take"},
                {"kind": "set_fades", "track_id": "video", "clip_id": "clip", "fade_in_samples": "3", "fade_out_samples": "4", "curve": "s_curve"},
                {"kind": "set_process", "track_id": "video", "clip_id": "clip", "playback_rate": 1.5, "stretch_ratio": 0.75, "algorithm": "phase_vocoder"},
            ],
        },
    )
    editing = meta["timeline"]["editing"]
    assert editing["takes"][0]["source_range"]["start_sample"] == "9007199254740993"
    assert editing["takes"][0]["source_range"]["vendor"] is True
    data = meta["timeline"]["tracks"][0]["clips"][1]["data"]
    assert data["active_take_id"] == "take"
    assert data["fades"]["vendor"] == "fade"
    assert data["process"]["vendor"] == "process"


def test_phase6_rejects_global_id_collision_bad_source_and_active_take_owner():
    meta = {"timeline": phase6_timeline()}
    for operation in (
        {"kind": "add_automation_lane", "lane_id": "clip", "track_id": "video", "target": "volume", "mode": "read", "min_value": 0, "max_value": 1},
        {"kind": "add_take", "track_id": "video", "clip_id": "clip", "take_id": "take", "media_asset_id": "asset", "source_range": {"sample_rate": 48000, "start_sample": "01"}},
    ):
        before = deepcopy(meta)
        with pytest.raises(ValueError):
            execute(meta, {"operation_id": str(uuid4()), "action": "edit", "operations": [operation]})
        assert meta == before

    invalid = phase6_timeline()
    invalid["editing"]["takes"] = [{"id": "take", "clip_id": "previous", "media_asset_id": "asset"}]
    invalid["tracks"][0]["clips"][1]["data"]["active_take_id"] = "take"
    with pytest.raises(ValueError, match="owned"):
        normalize_timeline(invalid)

    inverted = phase6_timeline()
    inverted["editing"]["takes"] = [{
        "id": "take", "clip_id": "clip", "media_asset_id": "asset",
        "source_range": {
            "sample_rate": 48000, "start_sample": "10", "start_remainder": "1/2",
            "end_sample": "10", "end_remainder": "-1/2",
        },
    }]
    with pytest.raises(ValueError, match="end cannot precede"):
        normalize_timeline(inverted)


def test_phase6_invalid_batch_is_atomic_and_locked_ripple_rejected():
    base = phase6_timeline()
    base["tracks"][0]["clips"][1]["locked"] = True
    meta = {"timeline": base}
    before = deepcopy(meta)
    with pytest.raises(ValueError):
        execute(
            meta,
            {
                "operation_id": "bad",
                "action": "edit",
                "operations": [
                    {
                        "kind": "set_fades",
                        "track_id": "video",
                        "clip_id": "clip",
                        "fade_in_samples": "1",
                        "fade_out_samples": "1",
                    },
                    {
                        "kind": "ripple",
                        "track_id": "video",
                        "from_sample": "0",
                        "delta_samples": "1",
                    },
                ],
            },
        )
    assert meta == before


def test_phase6_rejects_invalid_schema_targets_and_comp_overlap():
    bad = phase6_timeline()
    bad["editing"] = {"schema_version": 2}
    with pytest.raises(ValueError):
        normalize_timeline(bad)
    meta = {"timeline": phase6_timeline()}
    with pytest.raises(ValueError):
        execute(
            meta,
            {
                "operation_id": "target",
                "action": "edit",
                "operations": [
                    {
                        "kind": "add_automation_lane",
                        "lane_id": "bad",
                        "track_id": "video",
                        "target": "plugin:",
                        "mode": "read",
                        "min_value": 0,
                        "max_value": 1,
                    }
                ],
            },
        )
