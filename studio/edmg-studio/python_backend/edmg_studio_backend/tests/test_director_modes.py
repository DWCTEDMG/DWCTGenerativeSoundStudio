from __future__ import annotations

from edmg_studio_backend.domain.director_modes import (
    flavor_prompt,
    list_director_modes,
    normalize_director_mode,
    reactive_preset_for_mode,
)


def test_director_modes_normalize_and_flavor() -> None:
    assert normalize_director_mode("Lyric") == "lyric"
    assert normalize_director_mode("cinematic") == "narrative"
    assert reactive_preset_for_mode("performance") == "psychedelic"
    flavored = flavor_prompt("neon alley", "product")
    assert "product hero" in flavored.lower() or "brand-safe" in flavored.lower()
    modes = list_director_modes()
    assert {m["id"] for m in modes} == {
        "narrative",
        "performance",
        "abstract",
        "lyric",
        "product",
        "ambient",
    }
