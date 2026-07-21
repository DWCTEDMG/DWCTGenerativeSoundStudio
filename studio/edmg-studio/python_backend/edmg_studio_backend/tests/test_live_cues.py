from __future__ import annotations

from edmg_studio_backend.domain.live_cues import compile_live_cues


def test_compile_live_cues_from_music_graph() -> None:
    graph = {
        "tempo": {"bpm": 120},
        "timebase": {"durationSeconds": 16.0},
        "sections": [{"start": 0.0, "end": 8.0, "label": "intro"}, {"start": 8.0, "end": 16.0, "label": "drop"}],
        "beats": [{"t": 0.0}, {"t": 0.5}, {"t": 1.0}, {"t": 1.5}],
        "energy": [0.2, 0.5, 0.8, 0.4],
    }
    cues = compile_live_cues(graph)
    assert cues["schemaVersion"] == "1.0"
    assert cues["event_count"] >= 2
    assert "/edmg/section" in cues["transports"]["osc"]
    kinds = {event["kind"] for event in cues["events"]}
    assert "section" in kinds
    assert "beat" in kinds
