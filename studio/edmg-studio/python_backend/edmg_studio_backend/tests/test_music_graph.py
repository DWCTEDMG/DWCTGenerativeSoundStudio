from __future__ import annotations

from edmg_studio_backend.domain.music_graph import music_graph_from_analysis


def test_music_graph_adapter_maps_legacy_analysis() -> None:
    graph = music_graph_from_analysis(
        {
            "features": {"bpm": 120, "duration_s": 8.0, "sample_rate": 44100},
            "beats": [0.0, 0.5, 1.0],
            "sections": [{"start": 0.0, "end": 4.0, "label": "intro"}],
        },
        audio_filename="tone.wav",
    )
    assert graph["schemaVersion"] == "1.0"
    assert graph["tempo"]["bpm"] == 120
    assert len(graph["beats"]) == 3
    assert graph["sections"][0]["label"] == "intro"
    assert graph["source"]["filename"] == "tone.wav"
