from __future__ import annotations

from typing import Any

LIVE_CUE_SCHEMA_VERSION = "1.0"

OSC_PATHS = {
    "section": "/edmg/section",
    "beat": "/edmg/beat",
    "energy": "/edmg/energy",
    "cue": "/edmg/cue",
}

MIDI_NOTE_BASE = 36  # C2


def compile_live_cues(music_graph: dict[str, Any] | None, *, max_events: int = 256) -> dict[str, Any]:
    """Compile Music Graph into a stable OSC/MIDI/WebSocket cue protocol preview."""
    graph = dict(music_graph or {})
    sections = [item for item in list(graph.get("sections") or []) if isinstance(item, dict)]
    beats = [item for item in list(graph.get("beats") or []) if isinstance(item, dict)]
    energy = list(graph.get("energy") or [])
    duration_s = float(((graph.get("timebase") or {}) if isinstance(graph.get("timebase"), dict) else {}).get("durationSeconds") or 0.0)
    bpm = float(((graph.get("tempo") or {}) if isinstance(graph.get("tempo"), dict) else {}).get("bpm") or 0.0)

    events: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        start = float(section.get("start") or 0.0)
        label = str(section.get("label") or f"section_{index + 1}")
        events.append(
            {
                "id": f"section-{index}",
                "t": start,
                "kind": "section",
                "label": label,
                "confidence": float(section.get("confidence") or 1.0),
                "osc": {"address": OSC_PATHS["section"], "args": [index, label, start]},
                "midi": {"type": "note_on", "channel": 1, "note": MIDI_NOTE_BASE + (index % 12), "velocity": 90},
                "ws": {"type": "section", "index": index, "label": label, "t": start},
            }
        )

    # Subsample beats so long tracks stay bounded.
    stride = max(1, len(beats) // max(32, max_events // 4)) if beats else 1
    for index, beat in enumerate(beats[::stride]):
        t = float(beat.get("t") or 0.0)
        events.append(
            {
                "id": f"beat-{index}",
                "t": t,
                "kind": "beat",
                "label": "beat",
                "confidence": float(beat.get("confidence") or 1.0),
                "osc": {"address": OSC_PATHS["beat"], "args": [index, t]},
                "midi": {"type": "clock", "channel": 1, "note": MIDI_NOTE_BASE + 12, "velocity": 64},
                "ws": {"type": "beat", "index": index, "t": t},
            }
        )

    if energy:
        sample_count = min(16, len(energy))
        for index in range(sample_count):
            ratio = index / max(1, sample_count - 1)
            t = duration_s * ratio if duration_s > 0 else float(index)
            value = float(energy[int(ratio * (len(energy) - 1))])
            events.append(
                {
                    "id": f"energy-{index}",
                    "t": t,
                    "kind": "energy",
                    "label": "energy",
                    "confidence": 0.7,
                    "osc": {"address": OSC_PATHS["energy"], "args": [value, t]},
                    "midi": {"type": "cc", "channel": 1, "controller": 1, "value": int(max(0, min(127, value * 127)))},
                    "ws": {"type": "energy", "value": value, "t": t},
                }
            )

    events = sorted(events, key=lambda item: (float(item.get("t") or 0.0), str(item.get("id") or "")))[:max_events]
    return {
        "schemaVersion": LIVE_CUE_SCHEMA_VERSION,
        "advisory_only": True,
        "bpm": bpm,
        "duration_s": duration_s,
        "transports": {
            "osc": list(OSC_PATHS.values()),
            "midi": ["note_on", "clock", "cc"],
            "websocket": ["section", "beat", "energy", "cue"],
        },
        "world_adapters": {
            "touchdesigner": {"status": "preview", "ingest": "osc+ws"},
            "unreal": {"status": "preview", "ingest": "live_control_bridge"},
        },
        "event_count": len(events),
        "events": events,
        "notes": [
            "Compiled from Music Graph; runtime OSC/MIDI/WebSocket publishers remain experimental.",
            "Use Unreal live_control_bridge export for world handoff until live publishers ship.",
        ],
    }
