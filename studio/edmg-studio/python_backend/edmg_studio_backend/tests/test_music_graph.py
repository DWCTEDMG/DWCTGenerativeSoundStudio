from __future__ import annotations

from edmg_studio_backend.domain.music_graph import music_graph_from_analysis, section_energy_at_time


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


def test_section_energy_at_time_reads_music_graph_sections() -> None:
    graph = music_graph_from_analysis(
        {"sections": [{"start": 0.0, "end": 4.0, "label": "intro", "energy": 0.2}]}
    )
    assert section_energy_at_time(graph, 2.0) == 0.2
    assert section_energy_at_time(graph, 9.0, default=0.5) == 0.5
