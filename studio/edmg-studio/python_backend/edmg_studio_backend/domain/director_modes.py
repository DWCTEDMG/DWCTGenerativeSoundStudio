from __future__ import annotations

from typing import Any, Literal

DirectorMode = Literal["narrative", "performance", "abstract", "lyric", "product", "ambient"]

DIRECTOR_MODES: tuple[DirectorMode, ...] = (
    "narrative",
    "performance",
    "abstract",
    "lyric",
    "product",
    "ambient",
)

# Legacy creative presets map into director modes for compatibility.
LEGACY_PRESET_TO_MODE: dict[str, DirectorMode] = {
    "cinematic": "narrative",
    "psychedelic": "abstract",
    "ambient": "ambient",
}

MODE_PROFILES: dict[DirectorMode, dict[str, Any]] = {
    "narrative": {
        "label": "Narrative",
        "summary": "Story beats, continuity, and subject arcs.",
        "prompt_bias": "coherent story beat, clear subject continuity, cinematic framing",
        "camera_bias": "motivated camera moves that serve the story beat",
        "motion_bias": "prepare then settle; avoid gratuitous whip pans",
        "reactive_profile": "cinematic",
        "hero_preference": "quality",
    },
    "performance": {
        "label": "Performance",
        "summary": "Stage energy, crowd pulse, and accent hits.",
        "prompt_bias": "live performance energy, stage lights, kinetic presence",
        "camera_bias": "accent-driven push-ins and whip accents on drops",
        "motion_bias": "accent and travel phrases on beat peaks",
        "reactive_profile": "psychedelic",
        "hero_preference": "quality",
    },
    "abstract": {
        "label": "Abstract",
        "summary": "Texture, geometry, and non-literal motion.",
        "prompt_bias": "abstract geometry, optical texture, non-literal motifs",
        "camera_bias": "orbital and morphing framing with soft continuity",
        "motion_bias": "contrast and travel; prioritize texture morphs",
        "reactive_profile": "psychedelic",
        "hero_preference": "balanced",
    },
    "lyric": {
        "label": "Lyric",
        "summary": "Word-timed emphasis and typography-friendly cues.",
        "prompt_bias": "lyric emphasis, readable visual metaphor, word-timed accents",
        "camera_bias": "hold frames for lyric lines; gentle push on key phrases",
        "motion_bias": "settle during lines; accent on punch words",
        "reactive_profile": "cinematic",
        "hero_preference": "balanced",
    },
    "product": {
        "label": "Product",
        "summary": "Clean hero object, brand-safe palette, controlled motion.",
        "prompt_bias": "product hero shot, clean studio light, brand-safe palette",
        "camera_bias": "stable tripod and controlled orbit around subject",
        "motion_bias": "prepare and settle; minimal chaos",
        "reactive_profile": "ambient",
        "hero_preference": "ultra",
    },
    "ambient": {
        "label": "Ambient",
        "summary": "Atmosphere, slow drift, low flash risk.",
        "prompt_bias": "atmospheric drift, soft haze, contemplative environment",
        "camera_bias": "slow drift and gentle parallax",
        "motion_bias": "prepare and settle only; accessibility-friendly rates",
        "reactive_profile": "ambient",
        "hero_preference": "draft",
    },
}


def normalize_director_mode(value: str | None, *, fallback: DirectorMode = "narrative") -> DirectorMode:
    raw = str(value or "").strip().lower()
    if raw in DIRECTOR_MODES:
        return raw  # type: ignore[return-value]
    if raw in LEGACY_PRESET_TO_MODE:
        return LEGACY_PRESET_TO_MODE[raw]
    return fallback


def director_mode_profile(mode: str | None) -> dict[str, Any]:
    normalized = normalize_director_mode(mode)
    profile = dict(MODE_PROFILES[normalized])
    profile["id"] = normalized
    return profile


def reactive_preset_for_mode(mode: str | None) -> str:
    return str(director_mode_profile(mode).get("reactive_profile") or "cinematic")


def flavor_prompt(prompt: str, mode: str | None) -> str:
    profile = director_mode_profile(mode)
    bias = str(profile.get("prompt_bias") or "").strip()
    base = str(prompt or "").strip()
    if not bias:
        return base
    if bias.casefold() in base.casefold():
        return base
    return f"{base}, {bias}".strip(", ")


def list_director_modes() -> list[dict[str, Any]]:
    return [director_mode_profile(mode) for mode in DIRECTOR_MODES]
