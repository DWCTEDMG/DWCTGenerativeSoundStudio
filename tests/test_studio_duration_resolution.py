from __future__ import annotations

import wave
from pathlib import Path

import pytest

from edmg_studio_backend import app as studio_app
from edmg_studio_backend.store.projects import ProjectStore


def _write_silent_wav(path: Path, *, duration_s: float, sample_rate: int = 8000) -> None:
    frame_count = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frame_count)


def test_project_duration_resolution_prefers_audio_over_stale_plan(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "data")
    monkeypatch.setattr(studio_app, "store", store)

    proj = store.create("Duration mismatch")
    audio_path = store.project_dir(proj.id) / "assets" / "audio" / "full.wav"
    _write_silent_wav(audio_path, duration_s=3.25)
    store.set_audio(proj.id, "full.wav", audio_path.stat().st_size)

    proj = store.get(proj.id)
    assert proj is not None
    proj.meta.update(
        {
            "analysis": {"duration_s": 1.0},
            "last_plan": {
                "variants": [
                    {
                        "duration_s": 1.0,
                        "scenes": [{"start_s": 0.0, "end_s": 1.0, "prompt": "stale one-second plan"}],
                    }
                ]
            },
        }
    )
    store.save(proj)

    variant = proj.meta["last_plan"]["variants"][0]
    scenes = variant["scenes"]
    sources = studio_app._project_duration_sources(proj, variant, scenes)

    assert sources[0]["source"] == "audio"
    assert sources[0]["duration_s"] == pytest.approx(3.25)
    assert studio_app._resolved_project_duration_s(proj, variant, scenes) == pytest.approx(3.25)
    assert "current plan/scenes" in (studio_app._duration_mismatch_warning(sources) or "")
