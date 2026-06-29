from __future__ import annotations

import pytest

from edmg_studio_backend import app as backend_app


def test_normalize_plan_payload_clamps_scene_count_and_duration():
    plan = {
        "source": "ai",
        "variants": [
            {
                "duration_s": None,
                "scenes": [
                    {"start_s": 0.0, "end_s": 0.4, "prompt": "a"},
                    {"start_s": 0.4, "end_s": 0.8, "prompt": "b"},
                    {"start_s": 0.8, "end_s": 1.2, "prompt": "c"},
                ],
            }
        ],
    }

    normalized = backend_app._normalize_plan_payload(
        plan,
        requested_variants=1,
        requested_max_scenes=1,
        duration_s_hint=2.0,
    )

    scenes = normalized["variants"][0]["scenes"]
    assert len(scenes) == 1
    assert scenes[0]["start_s"] == 0.0
    assert scenes[0]["end_s"] == 2.0
    assert normalized["variants"][0]["duration_s"] == 2.0
    assert normalized["duration_s"] == 2.0


def test_normalize_plan_payload_limits_variants():
    plan = {
        "source": "ai",
        "variants": [
            {"duration_s": 1.0, "scenes": [{"start_s": 0.0, "end_s": 1.0, "prompt": "a"}]},
            {"duration_s": 1.0, "scenes": [{"start_s": 0.0, "end_s": 1.0, "prompt": "b"}]},
        ],
    }

    normalized = backend_app._normalize_plan_payload(
        plan,
        requested_variants=1,
        requested_max_scenes=4,
        duration_s_hint=1.0,
    )

    assert len(normalized["variants"]) == 1


def test_normalize_plan_payload_expands_stale_plan_to_duration_hint():
    plan = {
        "source": "local",
        "duration_s": 60.0,
        "variants": [
            {
                "duration_s": 60.0,
                "scenes": [
                    {"start_s": 0.0, "end_s": 30.0, "prompt": "opening"},
                    {"start_s": 30.0, "end_s": 60.0, "prompt": "finale"},
                ],
            }
        ],
    }

    normalized = backend_app._normalize_plan_payload(
        plan,
        requested_variants=1,
        requested_max_scenes=4,
        duration_s_hint=329.995,
    )

    variant = normalized["variants"][0]
    assert normalized["duration_s"] == 329.995
    assert variant["duration_s"] == 329.995
    assert variant["scenes"][0]["end_s"] == pytest.approx(164.9975)
    assert variant["scenes"][1]["start_s"] == pytest.approx(164.9975)
    assert variant["scenes"][-1]["end_s"] == 329.995


def test_normalize_plan_payload_rebalances_compressed_early_scenes():
    scenes = [
        {"start_s": float(index * 5), "end_s": float((index + 1) * 5), "prompt": f"scene {index}"}
        for index in range(11)
    ]
    scenes.append({"start_s": 55.0, "end_s": 330.0, "prompt": "oversized final scene"})
    plan = {"variants": [{"duration_s": 330.0, "scenes": scenes}]}

    normalized = backend_app._normalize_plan_payload(
        plan,
        requested_variants=1,
        requested_max_scenes=12,
        duration_s_hint=330.0,
    )

    normalized_scenes = normalized["variants"][0]["scenes"]
    assert normalized_scenes[1]["start_s"] == pytest.approx(27.5)
    assert normalized_scenes[6]["start_s"] == pytest.approx(165.0)
    assert normalized_scenes[-1]["start_s"] == pytest.approx(302.5)
    assert normalized_scenes[-1]["end_s"] == 330.0
