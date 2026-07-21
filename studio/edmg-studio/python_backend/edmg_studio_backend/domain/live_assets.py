from __future__ import annotations

from typing import Any

from .stem_modulation import normalize_modulation_matrix

LIVE_ASSET_SCHEMA_VERSION = "1.0"
DEFAULT_LATENCY_BUDGET_MS = 16
DEFAULT_MAX_UPDATE_HZ = 30


def compile_live_asset_packs(
    variant_review: dict[str, Any] | None,
    *,
    max_packs: int = 8,
    max_assets_per_pack: int = 4,
) -> list[dict[str, Any]]:
    """Build precomputed live asset packs from approved variant review artifacts."""
    review = dict(variant_review or {})
    groups = [item for item in list(review.get("groups") or []) if isinstance(item, dict)]
    packs: list[dict[str, Any]] = []
    for group in groups:
        variant_index = int(group.get("variant_index") or 0)
        artifacts = [
            item
            for item in list(group.get("artifacts") or [])
            if isinstance(item, dict)
            and str(item.get("review_state") or "") in {"approved", "cherry_picked"}
        ][:max_assets_per_pack]
        if not artifacts:
            continue
        packs.append(
            {
                "id": f"pack-v{variant_index}",
                "variant_index": variant_index,
                "label": str(group.get("label") or f"Variant {variant_index + 1}"),
                "precomputed": True,
                "latency_budget_ms": DEFAULT_LATENCY_BUDGET_MS,
                "never_blocks_on_diffusion": True,
                "assets": [
                    {
                        "path": str(item.get("path") or ""),
                        "name": str(item.get("name") or ""),
                        "kind": str(item.get("kind") or "video"),
                        "review_state": str(item.get("review_state") or ""),
                        "engine": str(item.get("engine") or ""),
                    }
                    for item in artifacts
                ],
            }
        )
    return packs[:max_packs]


def compile_bounded_modulation_channels(
    stem_modulation: dict[str, Any] | None,
    *,
    max_channels: int = 16,
) -> list[dict[str, Any]]:
    """Expose stem modulation lanes as bounded real-time channels."""
    matrix = normalize_modulation_matrix(stem_modulation)
    channels: list[dict[str, Any]] = []
    for lane in list(matrix.get("lanes") or []):
        if not isinstance(lane, dict):
            continue
        mapping = lane.get("mapping") if isinstance(lane.get("mapping"), dict) else {}
        channels.append(
            {
                "id": str(lane.get("id") or f"lane_{len(channels) + 1}"),
                "source": str(lane.get("source") or "energy"),
                "target": str(lane.get("target") or "camera.zoom"),
                "confidence": float(lane.get("confidence") or 0.5),
                "muted": bool(mapping.get("muted")),
                "scale": float(mapping.get("scale") or 1.0),
                "smoothing": float(mapping.get("smoothing") or 0.35),
                "range": {
                    "min": float(mapping.get("min") or 0.0),
                    "max": float(mapping.get("max") or 1.0),
                },
            }
        )
        if len(channels) >= max_channels:
            break
    return channels


def compile_live_assets(
    *,
    variant_review: dict[str, Any] | None,
    stem_modulation: dict[str, Any] | None,
    music_graph: dict[str, Any] | None = None,
    max_packs: int = 8,
    max_channels: int = 16,
) -> dict[str, Any]:
    """Compile precomputed packs and bounded modulation for the real-time lane."""
    packs = compile_live_asset_packs(variant_review, max_packs=max_packs)
    channels = compile_bounded_modulation_channels(stem_modulation, max_channels=max_channels)
    graph = dict(music_graph or {})
    duration_s = float(
        ((graph.get("timebase") or {}) if isinstance(graph.get("timebase"), dict) else {}).get("durationSeconds") or 0.0
    )
    return {
        "schema_version": LIVE_ASSET_SCHEMA_VERSION,
        "ready": bool(packs or channels),
        "never_blocks_on_diffusion": True,
        "latency_budget_ms": DEFAULT_LATENCY_BUDGET_MS,
        "max_update_hz": DEFAULT_MAX_UPDATE_HZ,
        "duration_s": duration_s,
        "pack_count": len(packs),
        "channel_count": len(channels),
        "packs": packs,
        "modulation": {
            "bounded": True,
            "channels": channels,
            "max_update_hz": DEFAULT_MAX_UPDATE_HZ,
        },
    }


def sample_bounded_modulation(
    live_assets: dict[str, Any] | None,
    *,
    t: float,
    stem_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return instantaneous bounded modulation values without touching the render queue."""
    assets = dict(live_assets or {})
    channels = list(((assets.get("modulation") or {}) if isinstance(assets.get("modulation"), dict) else {}).get("channels") or [])
    values = dict(stem_values or {})
    outputs: list[dict[str, Any]] = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if channel.get("muted"):
            continue
        source = str(channel.get("source") or "energy")
        raw = float(values.get(source, values.get("energy", 0.5)))
        scale = float(channel.get("scale") or 1.0)
        smoothing = float(channel.get("smoothing") or 0.35)
        value_range = channel.get("range") if isinstance(channel.get("range"), dict) else {}
        minimum = float(value_range.get("min") or 0.0)
        maximum = float(value_range.get("max") or 1.0)
        scaled = max(minimum, min(maximum, raw * scale))
        blended = (scaled * (1.0 - smoothing)) + (scaled * smoothing)
        outputs.append(
            {
                "channel_id": str(channel.get("id") or source),
                "target": str(channel.get("target") or "camera.zoom"),
                "value": round(blended, 4),
                "t": round(float(t), 4),
            }
        )
    return {
        "ok": True,
        "instant": True,
        "never_blocks_on_diffusion": True,
        "latency_budget_ms": DEFAULT_LATENCY_BUDGET_MS,
        "t": round(float(t), 4),
        "outputs": outputs[:16],
    }
