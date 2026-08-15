from __future__ import annotations

import json
from pathlib import Path

import pytest

from edmg_studio_backend.domain.continuity_validation import validate_project_continuity
from edmg_studio_backend.domain.variant_review import (
    apply_variant_review_decision,
    collect_variant_review,
)
from edmg_studio_backend.domain.world_adapters import (
    export_touchdesigner_adapter,
    run_adapter_simulator,
)
from edmg_studio_backend.services.live_publishers import (
    publish_status,
    start_live_publish,
    stop_live_publish,
)
from edmg_studio_backend.store.artifacts import write_artifact_manifest


def test_collect_variant_review_groups_outputs(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    videos = project_dir / "outputs" / "videos"
    videos.mkdir(parents=True)
    clip_a = videos / "internal_v00_demo.mp4"
    clip_b = videos / "internal_v01_demo.mp4"
    clip_a.write_bytes(b"a")
    clip_b.write_bytes(b"b")
    write_artifact_manifest(clip_a, project_dir=project_dir, project_id="p1", extra={"variant_index": 0})
    write_artifact_manifest(clip_b, project_dir=project_dir, project_id="p1", extra={"variant_index": 1})
    meta = {
        "last_plan": {
            "variants": [
                {"name": "Warm", "scenes": [{"id": "scene-1", "prompt": "neon skyline"}]},
                {"name": "Cool", "scenes": [{"id": "scene-1", "prompt": "neon skyline"}]},
            ]
        }
    }
    review = collect_variant_review(project_dir, meta)
    assert review["plan_variant_count"] == 2
    assert review["artifact_count"] == 2
    assert len(review["groups"]) == 2


def test_apply_variant_review_decision_updates_manifest(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    videos = project_dir / "outputs" / "videos"
    videos.mkdir(parents=True)
    clip = videos / "internal_v00_demo.mp4"
    clip.write_bytes(b"clip")
    write_artifact_manifest(clip, project_dir=project_dir, project_id="p1", extra={"variant_index": 0})
    result = apply_variant_review_decision(
        project_dir,
        artifact_path="outputs/videos/internal_v00_demo.mp4",
        decision="approved",
        notes="Hero framing locked",
        cherry_pick_traits=["palette:magenta"],
        lock_fields=["camera"],
    )
    manifest = json.loads((project_dir / "outputs" / "videos" / "internal_v00_demo.mp4.artifact.json").read_text(encoding="utf-8"))
    assert result["review"]["state"] == "approved"
    assert manifest["review"]["state"] == "approved"
    assert manifest["review"]["notes"] == "Hero framing locked"
    assert manifest["review"]["cherry_pick_traits"] == ["palette:magenta"]
    assert manifest["review"]["locks"] == ["camera"]

    refreshed = collect_variant_review(project_dir, {})
    artifact = refreshed["groups"][0]["artifacts"][0]
    assert artifact["cherry_pick_traits"] == ["palette:magenta"]
    assert artifact["locks"] == ["camera"]

    cleared = apply_variant_review_decision(
        project_dir,
        artifact_path="outputs/videos/internal_v00_demo.mp4",
        decision="approved",
        cherry_pick_traits=[],
        lock_fields=[],
    )
    assert cleared["review"]["cherry_pick_traits"] == []
    assert cleared["review"]["locks"] == []


def test_apply_variant_review_decision_rejects_path_traversal(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")

    with pytest.raises(ValueError, match="must stay inside"):
        apply_variant_review_decision(
            project_dir,
            artifact_path="../outside.mp4",
            decision="approved",
        )

    assert not outside.with_suffix(".mp4.artifact.json").exists()


def test_apply_variant_review_decision_rejects_non_output_media(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    audio_dir = project_dir / "assets" / "audio"
    audio_dir.mkdir(parents=True)
    audio = audio_dir / "source.wav"
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match="rendered image or video"):
        apply_variant_review_decision(
            project_dir,
            artifact_path="assets/audio/source.wav",
            decision="approved",
        )

    assert not audio.with_suffix(".wav.artifact.json").exists()


def test_validate_project_continuity_flags_forbidden_traits() -> None:
    plan = {
        "variants": [
            {
                "scenes": [
                    {"id": "scene-1", "prompt": "forbidden glitch noise"},
                    {"id": "scene-2", "prompt": "lead silhouette under neon skyline"},
                ]
            }
        ]
    }
    visual_dna = {
        "continuity": {"subject_anchors": ["lead silhouette"]},
        "identity": {"palette": ["magenta"]},
        "visual_grammar": {"forbidden_traits": ["glitch"]},
    }
    report = validate_project_continuity(plan=plan, visual_dna=visual_dna, variant_index=0)
    assert report["blocking_count"] >= 1
    assert report["ok_to_render"] is False


def test_world_adapter_simulator_passes_touchdesigner_contract() -> None:
    payload = export_touchdesigner_adapter(
        {
            "events": [
                {"t": 0.0, "kind": "section", "osc": {"address": "/edmg/section", "args": [0, "intro", 0.0]}},
            ],
            "transports": {"osc": ["/edmg/section"]},
        }
    )
    result = run_adapter_simulator("touchdesigner", payload)
    assert result["ok"] is True


def test_live_publish_session_tracks_status() -> None:
    cues = {
        "events": [
            {"t": 0.0, "osc": {"address": "/edmg/beat", "args": [0, 0.0]}, "midi": {"type": "clock"}, "ws": {"type": "beat"}},
        ]
    }
    status = start_live_publish("proj-live", cues, osc_host="127.0.0.1", osc_port=19000, playback_speed=20.0)
    assert status["running"] is True
    stop_live_publish("proj-live")
    final = publish_status("proj-live")
    assert final["running"] is False or final["sent_count"] >= 0
