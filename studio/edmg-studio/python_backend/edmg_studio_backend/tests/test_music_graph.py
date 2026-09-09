from __future__ import annotations

import json

from edmg_studio_backend.domain.music_graph import (
    MUSIC_GRAPH_CACHE_FILENAME,
    music_graph_for_project,
    music_graph_from_analysis,
    section_energy_at_time,
)


def test_music_graph_adapter_maps_legacy_analysis() -> None:
    graph = music_graph_from_analysis(
        {
            "features": {"bpm": 120, "duration_s": 8.0, "sample_rate": 44100},
            "beats": [0.0, 0.5, 1.0],
            "sections": [{"start": 0.0, "end": 4.0, "label": "intro", "energy": 0.42}],
            "tags": ["neon", "pulse"],
            "transcript": {"text": "lift the chorus", "language": "en"},
        },
        audio_filename="tone.wav",
    )
    assert graph["schemaVersion"] == "1.0"
    assert graph["tempo"]["bpm"] == 120
    assert len(graph["beats"]) == 3
    assert graph["sections"][0]["label"] == "intro"
    assert graph["source"]["filename"] == "tone.wav"
    assert graph["semantics"]["tags"][0]["tag"] == "neon"
    assert graph["lyrics"]["lines"][0]["text"] == "lift the chorus"
    assert isinstance(graph["stems"], list) and graph["stems"][0]["kind"] == "mixed"
    assert graph["analysisRuns"]
    assert len(graph["graphRevision"]) == 64
    assert graph["provenance"]["storage"] == "derived_in_memory"


def test_music_graph_adapter_is_deterministic_without_analysis_timestamp() -> None:
    analysis = {"features": {"bpm": 120}, "beats": [0.0, 0.5]}
    assert music_graph_from_analysis(analysis) == music_graph_from_analysis(analysis)


def test_project_music_graph_cache_is_reused_and_invalidated(tmp_path) -> None:
    project_dir = tmp_path / "project"
    meta = {
        "audio": {"filename": "song.wav", "duration_s": 8.0},
        "analysis": {"features": {"bpm": 120}, "sections": []},
    }
    first = music_graph_for_project(project_dir, meta)
    assert first["provenance"]["storage"] == "persistent_project_cache"
    cache_path = project_dir / "analysis" / MUSIC_GRAPH_CACHE_FILENAME
    first_bytes = cache_path.read_bytes()
    second = music_graph_for_project(project_dir, meta)
    assert second == first
    assert cache_path.read_bytes() == first_bytes
    assert json.loads(first_bytes)["graphRevision"] == first["graphRevision"]

    meta["analysis"]["features"]["bpm"] = 128
    changed = music_graph_for_project(project_dir, meta)
    assert changed["graphRevision"] != first["graphRevision"]
    assert changed["tempo"]["bpm"] == 128


def test_project_music_graph_survives_cache_write_failure(tmp_path, monkeypatch, caplog) -> None:
    project_dir = tmp_path / "project"
    meta = {"analysis": {"features": {"bpm": 120}}}

    def reject_replace(_source, _destination) -> None:
        raise PermissionError("cache is read-only")

    monkeypatch.setattr("edmg_studio_backend.domain.music_graph.os.replace", reject_replace)
    graph = music_graph_for_project(project_dir, meta)

    assert graph["tempo"]["bpm"] == 120
    assert graph["provenance"]["storage"] == "derived_in_memory"
    assert "Could not persist Music Graph cache" in caplog.text


def test_section_energy_at_time_reads_music_graph_sections() -> None:
    graph = music_graph_from_analysis(
        {"sections": [{"start": 0.0, "end": 4.0, "label": "intro", "energy": 0.2}]}
    )
    assert section_energy_at_time(graph, 2.0) == 0.2
    assert section_energy_at_time(graph, 9.0, default=0.5) == 0.5
