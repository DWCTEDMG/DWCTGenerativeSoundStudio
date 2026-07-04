from __future__ import annotations

from edmg_studio_backend.services import parseq_adapter


def test_parseq_manifest_exports_storyboard_schedules_and_prompts():
    variant = {
        "fps": 24,
        "duration_s": 6.0,
        "scenes": [
            {"start_s": 0.0, "end_s": 3.0, "prompt": "neon alley", "energy": 0.25},
            {"start_s": 3.0, "end_s": 6.0, "prompt": "bright chorus skyline", "energy": 0.85},
        ],
    }
    manifest = parseq_adapter.build_parseq_manifest(
        variant=variant,
        analysis={"features": {"bpm": 128, "energy": 0.5}},
        fps=24,
        duration_s=6.0,
    )

    assert manifest["format"] == "edmg_parseq_motion_manifest"
    assert manifest["fps"] == 24
    assert manifest["bpm"] == 128
    assert manifest["prompts"]["0"] == "neon alley"
    assert "72" in manifest["prompts"]
    assert "motion_score" in manifest["schedules"]
    assert "noise_aug_strength" in manifest["schedules"]
    assert "cfg_scale" in manifest["schedules"]


def test_parseq_manifest_to_internal_overrides_maps_video_and_deforum_schedules():
    manifest = {
        "format": "edmg_parseq_motion_manifest",
        "fps": 12,
        "keyframes": [
            {"frame": 0, "prompt": "first", "motion_score": 2, "noise_aug_strength": 0.02},
            {"frame": 24, "prompt": "second", "motion_score": 7, "noise_aug_strength": 0.11},
        ],
        "schedules": {
            "zoom": "0:(1.0), 24:(1.2)",
            "cfg_scale": "0:(6.0), 24:(8.0)",
            "steps": "0:(10), 24:(18)",
            "anchor_strength": "0:(0.20), 24:(0.35)",
        },
    }
    parsed = parseq_adapter.parseq_manifest_to_internal_overrides(manifest)
    overrides = parsed["overrides"]

    assert overrides["deforum_zoom"] == "0:(1.0), 24:(1.2)"
    assert overrides["deforum_cfg_scale_schedule"] == "0:(6.0), 24:(8.0)"
    assert overrides["deforum_steps_schedule"] == "0:(10), 24:(18)"
    assert overrides["video_model_motion_score_schedule"] == "0:(2.0000), 24:(7.0000)"
    assert overrides["video_model_noise_aug_schedule"] == "0:(0.0200), 24:(0.1100)"
    assert overrides["anchor_strength_schedule"] == "0:(0.20), 24:(0.35)"
    assert overrides["deforum_prompts"] == {"0": "first", "24": "second"}
    assert parsed["summary"]["schedules"] >= 6


def test_render_recipe_graph_describes_studio_native_pipeline():
    graph = parseq_adapter.build_render_recipe_graph(
        manifest={"schedules": {"motion_score": "0:(4)"}, "keyframes": []},
        internal_request={"temporal_mode": "video_model", "video_model_engine": "svd", "video_model_keyframe_renderer": "tensorrt_sd15"},
    )

    assert graph["source"] == "studio_native"
    labels = [node["label"] for node in graph["nodes"]]
    assert "Parseq-style motion sequencer" in labels
    assert any(node.get("engine") == "TensorRT SD1.5" for node in graph["nodes"])
    assert any(node.get("engine") == "svd" for node in graph["nodes"])
