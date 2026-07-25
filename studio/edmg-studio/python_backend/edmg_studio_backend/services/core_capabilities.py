from __future__ import annotations

import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from enhanced_deforum_music_generator.style_transfer import StyleTransferEngine


CORE_STYLE_PRESET = "cinematic"
CORE_STYLE_STRENGTH = 0.7


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_as_float(item) for item in value]


def enrich_with_multitrack_defaults(analysis: Mapping[str, Any] | None) -> dict[str, Any]:
    """Attach the universal mixed-track fallback used by the core audio pipeline."""
    enriched = deepcopy(dict(analysis or {}))
    features = enriched.get("features")
    features = dict(features) if isinstance(features, Mapping) else {}
    enriched["features"] = features

    existing = features.get("multitrack")
    if isinstance(existing, Mapping) and existing.get("schema_version") == 1:
        return enriched

    beats = _as_float_list(features.get("beats") or features.get("beat_times"))
    energy = _as_float_list(features.get("energy") or features.get("energy_curve"))
    duration_s = _as_float(features.get("duration_s") or features.get("duration"))
    tempo_bpm = _as_float(features.get("bpm") or features.get("tempo_bpm") or features.get("tempo"))

    features["multitrack"] = {
        "schema_version": 1,
        "source": "mixed_fallback",
        "tracks": [
            {
                "name": "mixed",
                "weight": 1.0,
                "role": "full_mix",
                "available": True,
            }
        ],
        "dominant_tracks": ["mixed"],
        "combined": {
            "duration_s": duration_s,
            "tempo_bpm": tempo_bpm,
            "beat_count": len(beats),
            "energy_points": len(energy),
        },
    }
    return enriched


def resolve_style_preset(style_prefs: str | None) -> str:
    """Use an explicit recognized preference, otherwise retain Studio's cinematic baseline."""
    engine = StyleTransferEngine()
    requested = str(style_prefs or "").strip().lower()
    for preset in engine.available_styles():
        if preset in requested:
            return preset
    return CORE_STYLE_PRESET


def apply_core_style_direction(plan: Mapping[str, Any] | None, style_prefs: str | None) -> dict[str, Any]:
    """Apply the Studio art-direction baseline to every generated scene prompt."""
    styled_plan = deepcopy(dict(plan or {}))
    preset = resolve_style_preset(style_prefs)
    engine = StyleTransferEngine()

    for variant in styled_plan.get("variants") if isinstance(styled_plan.get("variants"), list) else []:
        if not isinstance(variant, dict):
            continue
        scenes = variant.get("scenes") if isinstance(variant.get("scenes"), list) else []
        prompts = {
            index: str(scene.get("prompt") or "").strip()
            for index, scene in enumerate(scenes)
            if isinstance(scene, dict) and str(scene.get("prompt") or "").strip()
        }
        styled_prompts = engine.apply_style_to_prompts(
            prompts,
            style_name=preset,
            strength=CORE_STYLE_STRENGTH,
        )
        for index, prompt in styled_prompts.items():
            scene = scenes[index]
            scene["prompt"] = prompt
            scene["style_direction"] = {
                "preset": preset,
                "strength": CORE_STYLE_STRENGTH,
                "source": "studio_core",
            }

    styled_plan["style_direction"] = {
        "preset": preset,
        "strength": CORE_STYLE_STRENGTH,
        "source": "studio_core",
    }
    return styled_plan


def development_profiling_enabled() -> bool:
    return os.getenv("EDMG_DEV_PROFILING", "").strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def development_timing(stage: str, timings_ms: dict[str, float]) -> Iterator[None]:
    """Record lightweight timings only when explicitly enabled for development."""
    if not development_profiling_enabled():
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        timings_ms[str(stage)] = round((time.perf_counter() - start) * 1000, 3)
