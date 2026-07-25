from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from enhanced_deforum_music_generator.core.deforum_schedule_format import format_schedule

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

REQUIRED = [
    FIXTURES / "README.md",
    FIXTURES / "audio" / "short_tone_1s.wav",
    FIXTURES / "audio" / "LANDR-Walkin' In That Rundown Town-Warm-Medium-REV_V1.wav",
    FIXTURES / "projects" / "starter_project.golden.json",
    FIXTURES / "analysis" / "beat_grid.golden.json",
    FIXTURES / "analysis" / "sections.golden.json",
    FIXTURES / "schedules" / "zoom_schedule.golden.json",
    FIXTURES / "media" / "frame_probe.golden.json",
]


@pytest.mark.parametrize("path", REQUIRED, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_required_fixtures_exist(path: Path) -> None:
    assert path.is_file(), f"Missing fixture: {path}"


def test_short_tone_matches_frame_probe_golden() -> None:
    golden = json.loads((FIXTURES / "media" / "frame_probe.golden.json").read_text(encoding="utf-8"))
    audio_path = FIXTURES / golden["audio_fixture"]
    expected = golden["expected"]
    size = audio_path.stat().st_size
    assert expected["min_size_bytes"] <= size <= expected["max_size_bytes"]
    with wave.open(str(audio_path), "rb") as handle:
        assert handle.getframerate() == expected["sample_rate"]
        assert handle.getnchannels() == expected["channels"]
        assert handle.getsampwidth() == expected["sample_width_bytes"]
        duration = handle.getnframes() / float(handle.getframerate())
        assert abs(duration - expected["duration_s"]) < 0.05


def test_starter_project_golden_shape() -> None:
    project = json.loads((FIXTURES / "projects" / "starter_project.golden.json").read_text(encoding="utf-8"))
    assert project["schema_version"] == 1
    assert project["meta"]["audio"]["filename"] == "short_tone_1s.wav"
    assert project["meta"]["timeline"]["duration_s"] == 1.0
    assert len(project["meta"]["timeline"]["layers"]) == 1


def test_zoom_schedule_golden_matches_formatter() -> None:
    golden = json.loads((FIXTURES / "schedules" / "zoom_schedule.golden.json").read_text(encoding="utf-8"))
    formatted = format_schedule(
        [(int(frame), float(value)) for frame, value in golden["keyframes"]],
        precision=int(golden["precision"]),
    )
    assert formatted == golden["formatted"]


def test_analysis_goldens_are_versioned() -> None:
    beats = json.loads((FIXTURES / "analysis" / "beat_grid.golden.json").read_text(encoding="utf-8"))
    sections = json.loads((FIXTURES / "analysis" / "sections.golden.json").read_text(encoding="utf-8"))
    assert beats["schema_version"] == 1
    assert sections["schema_version"] == 1
    assert beats["beats"][0]["time_s"] == 0.0
    assert sections["sections"][0]["end_s"] == 1.0
