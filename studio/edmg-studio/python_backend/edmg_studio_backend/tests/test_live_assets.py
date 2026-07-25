from __future__ import annotations

from edmg_studio_backend.domain.live_assets import (
    compile_bounded_modulation_channels,
    compile_live_asset_packs,
    compile_live_assets,
    sample_bounded_modulation,
)


def test_compile_live_asset_packs_from_approved_variants() -> None:
    review = {
        "groups": [
            {
                "variant_index": 0,
                "label": "Warm",
                "artifacts": [
                    {
                        "path": "outputs/videos/internal_v00_demo.mp4",
                        "name": "internal_v00_demo.mp4",
                        "kind": "video",
                        "review_state": "approved",
                        "engine": "internal_video",
                    },
                    {
                        "path": "outputs/videos/internal_v00_alt.mp4",
                        "name": "internal_v00_alt.mp4",
                        "kind": "video",
                        "review_state": "unreviewed",
                        "engine": "internal_video",
                    },
                ],
            }
        ]
    }
    packs = compile_live_asset_packs(review)
    assert len(packs) == 1
    assert packs[0]["precomputed"] is True
    assert packs[0]["never_blocks_on_diffusion"] is True
    assert len(packs[0]["assets"]) == 1


def test_compile_bounded_modulation_channels_caps_lane_count() -> None:
    matrix = {
        "lanes": [
            {"id": f"lane-{index}", "source": "energy", "target": f"target.{index}"}
            for index in range(20)
        ]
    }
    channels = compile_bounded_modulation_channels(matrix, max_channels=4)
    assert len(channels) == 4


def test_sample_bounded_modulation_is_instant_and_bounded() -> None:
    assets = compile_live_assets(
        variant_review={"groups": []},
        stem_modulation={
            "lanes": [
                {
                    "id": "kick",
                    "source": "kick",
                    "target": "scale.pulse",
                    "mapping": {"min": 0.0, "max": 1.0, "scale": 1.0, "smoothing": 0.2},
                }
            ]
        },
    )
    sample = sample_bounded_modulation(assets, t=12.5, stem_values={"kick": 0.8})
    assert sample["instant"] is True
    assert sample["never_blocks_on_diffusion"] is True
    assert sample["outputs"][0]["target"] == "scale.pulse"
    assert 0.0 <= sample["outputs"][0]["value"] <= 1.0
