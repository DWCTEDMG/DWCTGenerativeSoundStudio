from __future__ import annotations

from typing import Any


DEFAULT_MAPPING = {
    "smoothing": 0.35,
    "attack": 0.05,
    "release": 0.2,
    "min": 0.0,
    "max": 1.0,
    "muted": False,
    "scale": 1.0,
}


def normalize_modulation_matrix(matrix: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a stem→visual modulation matrix with safe defaults."""
    raw = dict(matrix or {})
    lanes = raw.get("lanes") if isinstance(raw.get("lanes"), list) else []
    out_lanes: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        mapping = dict(DEFAULT_MAPPING)
        mapping.update(lane.get("mapping") if isinstance(lane.get("mapping"), dict) else {})
        out_lanes.append(
            {
                "id": str(lane.get("id") or f"lane_{len(out_lanes)+1}"),
                "source": str(lane.get("source") or "energy"),
                "target": str(lane.get("target") or "camera.zoom"),
                "confidence": float(lane.get("confidence") or 0.5),
                "mapping": {
                    "smoothing": float(mapping["smoothing"]) if mapping.get("smoothing") is not None else 0.35,
                    "attack": float(mapping["attack"]) if mapping.get("attack") is not None else 0.05,
                    "release": float(mapping["release"]) if mapping.get("release") is not None else 0.2,
                    "min": float(mapping["min"]) if mapping.get("min") is not None else 0.0,
                    "max": float(mapping["max"]) if mapping.get("max") is not None else 1.0,
                    "muted": bool(mapping.get("muted")),
                    "scale": float(mapping.get("scale") or 1.0),
                },
            }
        )
    return {
        "schema_version": 1,
        "lanes": out_lanes,
        "baked": bool(raw.get("baked")),
    }


def mute_lane(matrix: dict[str, Any] | None, lane_id: str, muted: bool = True) -> dict[str, Any]:
    next_matrix = normalize_modulation_matrix(matrix)
    for lane in next_matrix["lanes"]:
        if lane["id"] == lane_id:
            lane["mapping"]["muted"] = bool(muted)
    return next_matrix


def scale_lane(matrix: dict[str, Any] | None, lane_id: str, scale: float) -> dict[str, Any]:
    next_matrix = normalize_modulation_matrix(matrix)
    for lane in next_matrix["lanes"]:
        if lane["id"] == lane_id:
            lane["mapping"]["scale"] = max(0.0, min(3.0, float(scale)))
    return next_matrix
