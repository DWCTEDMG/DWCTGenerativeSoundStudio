from __future__ import annotations

from edmg_studio_backend.services.core_capabilities import (
    apply_core_style_direction,
    development_timing,
    enrich_with_multitrack_defaults,
    resolve_style_preset,
)


def test_multitrack_defaults_preserve_the_mixed_audio_analysis() -> None:
    enriched = enrich_with_multitrack_defaults(
        {
            "features": {
                "duration_s": 30.0,
                "bpm": 120.0,
                "beats": [0.0, 0.5, 1.0],
                "energy": [0.2, 0.7],
            }
        }
    )

    multitrack = enriched["features"]["multitrack"]
    assert multitrack["source"] == "mixed_fallback"
    assert multitrack["dominant_tracks"] == ["mixed"]
    assert multitrack["combined"]["tempo_bpm"] == 120.0
    assert multitrack["combined"]["energy_points"] == 2


def test_style_direction_applies_the_requested_preset_to_every_scene() -> None:
    plan = {
        "variants": [
            {
                "scenes": [
                    {"prompt": "A neon skyline at night"},
                    {"prompt": "A quiet silhouette in rain"},
                ]
            }
        ]
    }

    styled = apply_core_style_direction(plan, "anime with neon accents")

    assert styled["style_direction"]["preset"] == "anime"
    assert "anime style" in styled["variants"][0]["scenes"][0]["prompt"]
    assert styled["variants"][0]["scenes"][1]["style_direction"]["source"] == "studio_core"


def test_style_direction_uses_cinematic_as_the_core_default() -> None:
    assert resolve_style_preset("") == "cinematic"


def test_development_timing_only_records_when_explicitly_enabled(monkeypatch) -> None:
    timings: dict[str, float] = {}
    monkeypatch.delenv("EDMG_DEV_PROFILING", raising=False)
    with development_timing("disabled", timings):
        pass
    assert timings == {}

    monkeypatch.setenv("EDMG_DEV_PROFILING", "true")
    with development_timing("enabled", timings):
        pass
    assert "enabled" in timings
