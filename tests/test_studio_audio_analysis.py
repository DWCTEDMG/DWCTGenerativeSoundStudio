from __future__ import annotations

import json
from pathlib import Path

import pytest

from edmg_studio_backend import app as studio_app
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore


def _make_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    proj = store.create("Longform Analysis Test")
    return store, jobs, proj


def test_analyze_audio_builds_rich_longform_payload(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    audio_path = store.project_dir(proj.id) / "assets" / "audio" / "track.wav"
    audio_path.write_bytes(b"fake-wav")
    store.set_audio(proj.id, "track.wav", audio_path.stat().st_size)
    proj = store.get(proj.id)
    assert proj is not None
    proj.meta["last_plan"] = {"variants": [{"scenes": []}]}
    proj.meta["timeline"] = {"layers": [{"id": "authored"}]}
    store.save(proj)

    monkeypatch.setattr(
        studio_app,
        "_collect_audio_analysis_features",
        lambda _path: {
            "duration_s": 612.0,
            "bpm": 122.0,
            "tempo_bpm": 122.0,
            "beats": [0.5, 1.0, 1.5],
            "energy": [0.2, 0.7, 0.4, 0.8, 0.3],
            "onset_strength": [0.1, 0.5, 0.9],
        },
    )
    monkeypatch.setattr(
        studio_app.ai,
        "transcribe",
        lambda _audio_path, model_size="small", **_kwargs: {
            "text": (
                "Neon streets open into the skyline. "
                "The chorus lifts the crowd through electric rain. "
                "A final dawn lands over mirrored glass."
            ),
            "language": "en",
            "duration_s": 612.0,
            "duration_after_vad_s": 598.0,
            "segment_count": 3,
            "word_count": 21,
            "model_size": model_size,
            "source": "faster_whisper",
            "segments": [
                {"start": 0.0, "end": 18.0, "text": "Neon streets open into the skyline."},
                {"start": 296.0, "end": 332.0, "text": "The chorus lifts the crowd through electric rain."},
                {"start": 586.0, "end": 612.0, "text": "A final dawn lands over mirrored glass."},
            ],
        },
    )

    result = studio_app.analyze_audio(proj.id)

    analysis = result["analysis"]
    assert analysis["duration_s"] == 612.0
    assert analysis["transcript"]["language"] == "en"
    assert analysis["transcript"]["segment_count"] == 3
    assert analysis["summary"].startswith("Neon streets open into the skyline.")
    assert "neon" in analysis["tags"]
    assert analysis["themes"]
    assert len(analysis["sections"]) >= 3
    assert analysis["analysis_path"] == "analysis/audio_analysis.json"

    snapshot_path = store.project_dir(proj.id) / "analysis" / "audio_analysis.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["transcript"]["segments"][1]["text"] == "The chorus lifts the crowd through electric rain."
    assert snapshot["summary"] == analysis["summary"]

    saved_proj = store.get(proj.id)
    assert saved_proj is not None
    assert saved_proj.meta["last_plan"] == proj.meta["last_plan"]
    assert saved_proj.meta["director_workflow"]["status"] == "draft"
    assert saved_proj.meta["director_workflow"]["schedule"]["motion_keys"]
    assert saved_proj.meta["timeline"] == {"layers": [{"id": "authored"}]}
    payload = studio_app._build_creative_direction_payload(saved_proj, 0, "cinematic", 1.0)
    assert payload["sections"]
    assert payload["transcript_summary"] == analysis["summary"]
    assert payload["narrative_analysis"]["segment_count"] == 3


def test_creative_direction_scene_overrides_update_payload_and_timeline(tmp_path):
    store, _jobs, proj = _make_project(tmp_path)
    proj.meta["analysis"] = {
        "duration_s": 10.0,
        "features": {"duration_s": 10.0, "energy": [0.25, 0.75]},
    }
    proj.meta["last_plan"] = {
        "variants": [
            {
                "scenes": [
                    {
                        "name": "Original scene",
                        "start_s": 0.0,
                        "end_s": 10.0,
                        "prompt": "original prompt",
                    }
                ]
            }
        ]
    }
    store.save(proj)

    payload = studio_app._build_creative_direction_payload(
        proj,
        0,
        "cinematic",
        1.0,
        scene_overrides=[
            {
                "index": 0,
                "name": "Final chorus",
                "prompt": "custom prism skyline",
                "camera_hint": "Orbit the performer.",
                "motion_hint": "Pulse on every downbeat.",
                "director_mode": "performance",
            }
        ],
    )

    scene = payload["scenes"][0]
    assert scene["name"] == "Final chorus"
    assert scene["prompt"] == "custom prism skyline"
    assert scene["camera_hint"] == "Orbit the performer."
    assert scene["motion_hint"] == "Pulse on every downbeat."
    assert scene["director_mode"] == "performance"
    prompt_clip = payload["timeline_patch"]["timeline"]["tracks"][0]["clips"][0]
    assert "custom prism skyline" in prompt_clip["data"]["prompt"]
    assert "Orbit the performer." in prompt_clip["data"]["prompt"]


def test_analyze_audio_surfaces_no_speech_after_vad_status(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    audio_path = store.project_dir(proj.id) / "assets" / "audio" / "instrumental.wav"
    audio_path.write_bytes(b"fake-wav")
    store.set_audio(proj.id, "instrumental.wav", audio_path.stat().st_size)

    monkeypatch.setattr(
        studio_app,
        "_collect_audio_analysis_features",
        lambda _path: {
            "duration_s": 374.8,
            "bpm": 60.0,
            "tempo_bpm": 60.0,
            "beats": [1.0, 2.0, 3.0],
            "energy": [0.3, 0.5, 0.4, 0.6],
            "onset_strength": [0.2, 0.4, 0.7],
        },
    )
    monkeypatch.setattr(
        studio_app.ai,
        "transcribe",
        lambda _audio_path, model_size="small", **_kwargs: {
            "text": "",
            "language": "en",
            "duration_s": 374.8,
            "duration_after_vad_s": 0.0,
            "segment_count": 0,
            "word_count": 0,
            "model_size": "medium",
            "source": "faster_whisper",
            "segments": [],
            "note": "No speech detected after VAD.",
        },
    )

    result = studio_app.analyze_audio(proj.id)

    analysis = result["analysis"]
    assert analysis["summary"].startswith("No speech detected after VAD.")
    assert analysis["transcript"]["note"] == "No speech detected after VAD."
    assert analysis["sections"]

    saved_proj = store.get(proj.id)
    assert saved_proj is not None
    payload = studio_app._build_creative_direction_payload(saved_proj, 0, "cinematic", 1.0)
    assert payload["transcript_summary"].startswith("No speech detected after VAD.")


def test_transcript_normalization_preserves_safe_runtime_provenance_and_is_idempotent():
    raw = {
        "text": "A clear vocal line.",
        "provider": "faster_whisper",
        "device": "cpu",
        "compute_type": "int8",
        "requested_device": "cuda",
        "device_fallback_used": True,
        "device_fallback_note": "CUDA ASR unavailable; used CPU.",
        "source_audio_path": "separated/vocals.wav",
        "vocal_separation": {
            "enabled": True,
            "available": False,
            "source": "demucs",
            "error": "model unavailable",
            "unsafe": {"ignored": True},
        },
        "unsafe": {"secret": "ignored"},
    }

    normalized = studio_app._normalize_transcript_payload(raw)
    repeated = studio_app._normalize_transcript_payload(normalized)

    assert repeated == normalized
    assert normalized["provider"] == "faster_whisper"
    assert normalized["device"] == "cpu"
    assert normalized["requested_device"] == "cuda"
    assert normalized["device_fallback_used"] is True
    assert normalized["note"] == "CUDA ASR unavailable; used CPU."
    assert normalized["vocal_separation"] == {
        "source": "demucs",
        "error": "model unavailable",
        "enabled": True,
        "available": False,
    }
    assert "unsafe" not in normalized
    assert studio_app._analysis_summary_text(normalized, normalized["text"], []) == (
        "A clear vocal line. CUDA ASR unavailable; used CPU."
    )


def test_analyze_audio_failure_preserves_previous_analysis_and_plan(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    audio_path = store.project_dir(proj.id) / "assets" / "audio" / "track.wav"
    audio_path.write_bytes(b"fake-wav")
    store.set_audio(proj.id, "track.wav", audio_path.stat().st_size)
    proj = store.get(proj.id)
    assert proj is not None
    proj.meta["analysis"] = {"features": {"bpm": 100}}
    proj.meta["last_plan"] = {"variants": [{"name": "Previous"}]}
    store.save(proj)

    def fail_feature_collection(_path):
        raise RuntimeError("feature extraction failed")

    monkeypatch.setattr(studio_app, "_collect_audio_analysis_features", fail_feature_collection)

    with pytest.raises(RuntimeError, match="feature extraction failed"):
        studio_app.analyze_audio(proj.id)

    saved = store.get(proj.id)
    assert saved is not None
    assert saved.meta["analysis"] == {"features": {"bpm": 100}}
    assert saved.meta["last_plan"] == {"variants": [{"name": "Previous"}]}
