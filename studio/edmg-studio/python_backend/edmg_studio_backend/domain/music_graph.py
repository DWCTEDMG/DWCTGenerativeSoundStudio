from __future__ import annotations

from typing import Any


MUSIC_GRAPH_SCHEMA_VERSION = "1.0"


def music_graph_from_analysis(
    analysis: dict[str, Any] | None,
    *,
    audio_filename: str | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Compatibility adapter: map existing analysis meta into Music Graph v1 shape."""
    analysis = dict(analysis or {})
    features = dict(analysis.get("features") or {})
    beats_raw = analysis.get("beats") or features.get("beats") or []
    sections_raw = analysis.get("sections") or features.get("sections") or []
    bpm = float(features.get("bpm") or analysis.get("bpm") or 0.0)
    duration = float(
        duration_s
        or features.get("duration_s")
        or analysis.get("duration_s")
        or 0.0
    )

    beats: list[dict[str, Any]] = []
    for item in beats_raw:
        if isinstance(item, (int, float)):
            beats.append({"t": float(item), "confidence": 1.0})
        elif isinstance(item, dict) and "t" in item:
            beats.append({"t": float(item.get("t") or 0.0), "confidence": float(item["confidence"]) if item.get("confidence") is not None else 1.0})

    sections: list[dict[str, Any]] = []
    for item in sections_raw:
        if not isinstance(item, dict):
            continue
        sections.append(
            {
                "start": float(item.get("start") or item.get("start_s") or 0.0),
                "end": float(item.get("end") or item.get("end_s") or 0.0),
                "label": str(item.get("label") or item.get("name") or "section"),
                "confidence": float(item["confidence"]) if item.get("confidence") is not None else 1.0,
            }
        )

    return {
        "schemaVersion": MUSIC_GRAPH_SCHEMA_VERSION,
        "source": {"filename": audio_filename, "kind": "project_audio"},
        "timebase": {"sampleRate": int(features.get("sample_rate") or 44100), "durationSeconds": duration},
        "tempo": {"bpm": bpm, "confidence": float(features.get("bpm_confidence") or (0.5 if bpm else 0.0))},
        "meter": {
            "numerator": int(features.get("meter_numerator") or 4),
            "denominator": int(features.get("meter_denominator") or 4),
            "confidence": float(features.get("meter_confidence") or 0.5),
        },
        "beats": beats,
        "bars": [],
        "sections": sections,
        "energy": analysis.get("energy") or features.get("energy") or [],
        "stems": analysis.get("stems") or {},
        "lyrics": analysis.get("transcript") or analysis.get("lyrics"),
        "confidenceNotes": [
            "Compatibility adapter from legacy analysis meta; bars may be empty until re-analysis.",
        ],
    }
