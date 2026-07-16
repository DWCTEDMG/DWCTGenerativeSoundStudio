from __future__ import annotations

from typing import Any, Literal

MotionPhrase = Literal["prepare", "accent", "travel", "settle", "contrast"]

PHRASE_DEFAULTS: dict[MotionPhrase, dict[str, Any]] = {
    "prepare": {"zoom_end": 1.03, "pan_y_end": -2, "strength": 0.25},
    "accent": {"zoom_end": 1.12, "pan_x_end": 8, "strength": 0.55},
    "travel": {"zoom_end": 1.06, "pan_x_start": -10, "pan_x_end": 10, "strength": 0.4},
    "settle": {"zoom_end": 1.0, "pan_x_end": 0, "pan_y_end": 0, "strength": 0.2},
    "contrast": {"zoom_start": 1.08, "zoom_end": 0.98, "pan_y_start": -4, "pan_y_end": 4, "strength": 0.5},
}


def compile_motion_phrase(
    phrase: MotionPhrase,
    *,
    start_s: float,
    end_s: float,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a named motion grammar phrase into a timeline motion clip payload."""
    if phrase not in PHRASE_DEFAULTS:
        raise ValueError(f"Unknown motion phrase: {phrase}")
    if end_s <= start_s:
        raise ValueError("end_s must be greater than start_s")
    data = dict(PHRASE_DEFAULTS[phrase])
    if overrides:
        data.update(overrides)
    return {
        "id": f"motion_{phrase}_{int(start_s * 1000)}_{int(end_s * 1000)}",
        "start_s": float(start_s),
        "end_s": float(end_s),
        "data": {
            **data,
            "motion_preset": phrase,
            "motion_label": phrase.replace("_", " ").title(),
            "motion_grammar": phrase,
        },
    }


def apply_motion_phrases_to_timeline(
    timeline: dict[str, Any] | None,
    phrases: list[dict[str, Any]],
    *,
    overwrite_motion_track: bool = False,
) -> dict[str, Any]:
    """Insert compiled motion phrases onto the motion track."""
    next_tl = dict(timeline or {})
    tracks = list(next_tl.get("tracks") or [])
    motion_idx = next((i for i, t in enumerate(tracks) if str(t.get("type") or "").lower() == "motion"), -1)
    if motion_idx < 0:
        tracks.append({"id": "motion", "name": "Motion", "type": "motion", "clips": []})
        motion_idx = len(tracks) - 1
    track = dict(tracks[motion_idx])
    clips = [] if overwrite_motion_track else list(track.get("clips") or [])
    for item in phrases:
        phrase = str(item.get("phrase") or "travel")
        clip = compile_motion_phrase(
            phrase,  # type: ignore[arg-type]
            start_s=float(item.get("start_s") or 0.0),
            end_s=float(item.get("end_s") or (float(item.get("start_s") or 0.0) + 2.0)),
            overrides=item.get("overrides") if isinstance(item.get("overrides"), dict) else None,
        )
        clips.append(clip)
    track["clips"] = clips
    tracks[motion_idx] = track
    next_tl["tracks"] = tracks
    return next_tl
