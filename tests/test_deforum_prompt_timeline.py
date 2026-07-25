from __future__ import annotations

from edmg_studio_backend.services.deforum_prompt_timeline import normalize_prompt_map, resolve_prompt_frame


def test_prompt_timeline_latest_keyframe_wins_until_next_change():
    prompts = normalize_prompt_map({"0": "wide neon skyline", "12": "close-up chrome dancer", "24": "laser tunnel"})

    assert resolve_prompt_frame(prompts, 0) == "wide neon skyline"
    assert resolve_prompt_frame(prompts, 18) == "close-up chrome dancer"
    assert resolve_prompt_frame(prompts, 40) == "laser tunnel"


def test_negative_prompt_timeline_resolves_same_way():
    negatives = normalize_prompt_map({0: "blurry, watermark", 16: "overexposed, blurry"})

    assert resolve_prompt_frame(negatives, 8) == "blurry, watermark"
    assert resolve_prompt_frame(negatives, 16) == "overexposed, blurry"
