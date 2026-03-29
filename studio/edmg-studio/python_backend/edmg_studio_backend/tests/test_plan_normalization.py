from __future__ import annotations

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
