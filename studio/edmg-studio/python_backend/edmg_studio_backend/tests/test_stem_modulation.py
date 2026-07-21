from __future__ import annotations

from edmg_studio_backend.domain.stem_modulation import mute_lane, normalize_modulation_matrix, scale_lane


def test_stem_modulation_normalize_mute_scale() -> None:
    matrix = normalize_modulation_matrix(
        {
            "lanes": [
                {
                    "id": "kick_zoom",
                    "source": "drums",
                    "target": "camera.zoom",
                    "mapping": {"scale": 1.2},
                }
            ]
        }
    )
    assert matrix["lanes"][0]["mapping"]["smoothing"] == 0.35
    muted = mute_lane(matrix, "kick_zoom", True)
    assert muted["lanes"][0]["mapping"]["muted"] is True
    scaled = scale_lane(muted, "kick_zoom", 2.0)
    assert scaled["lanes"][0]["mapping"]["scale"] == 2.0
