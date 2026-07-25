"""Unit tests for the AI animation auto-configure module."""

from __future__ import annotations

from edmg_studio_backend.services import animation_autoconfig as ac

_TIER_DEFAULTS = {
    "width": 768,
    "height": 432,
    "steps": 20,
    "cfg": 6.5,
    "fps_output": 24,
    "fps_render": 2,
    "keyframe_interval_s": 5.0,
    "temporal_mode": "frame_img2img",
}


def test_presets_listed_and_unique():
    presets = ac.list_presets()
    ids = [p["id"] for p in presets]
    assert len(ids) == len(set(ids))
    for required in ("draft_fast", "full_motion", "cinematic_3d", "image_animation"):
        assert required in ids
    # public payload shape
    sample = presets[0]
    for key in ("id", "label", "description", "quality", "motion", "is_3d", "engine_hint"):
        assert key in sample


def test_resolve_preset_unknown_returns_none():
    assert ac.resolve_preset("does_not_exist") is None
    assert ac.resolve_preset(None) is None
    assert ac.resolve_preset("cinematic_3d").id == "cinematic_3d"


def test_motion_schedule_none_is_empty():
    assert ac.build_motion_schedule("none", duration_s=10, fps=24) == {}


def test_motion_schedule_2d_has_no_3d_keys():
    sched = ac.build_motion_schedule("full", duration_s=10, fps=24)
    assert "zoom" in sched and "translation_x" in sched
    for k in ("translation_z", "rotation_3d_x", "rotation_3d_y"):
        assert k not in sched


def test_motion_schedule_3d_has_3d_keys_scaled_to_duration():
    sched = ac.build_motion_schedule("full_3d", duration_s=10, fps=24)
    assert "translation_z" in sched
    assert "rotation_3d_y" in sched
    assert "fov" in sched
    # schedule end frame should reflect duration*fps = 240
    assert "240:(" in sched["translation_z"]


def test_schedule_to_request_overrides_maps_keys():
    sched = ac.build_motion_schedule("full_3d", duration_s=4, fps=24)
    overrides = ac.schedule_to_request_overrides(sched)
    assert "deforum_translation_z" in overrides
    assert "deforum_rotation_3d_y" in overrides
    assert all(k.startswith("deforum_") for k in overrides)


def test_resolve_engine_explicit_and_auto():
    internal_preset = ac.resolve_preset("full_motion")
    comfy_preset = ac.resolve_preset("comfyui_animatediff")
    # explicit internal always internal
    assert ac.resolve_engine(comfy_preset, "internal", comfyui_available=True) == "internal"
    # explicit comfyui requires availability
    assert ac.resolve_engine(internal_preset, "comfyui", comfyui_available=True) == "comfyui"
    assert ac.resolve_engine(internal_preset, "comfyui", comfyui_available=False) == "internal"
    # auto follows preset hint
    assert ac.resolve_engine(comfy_preset, "auto", comfyui_available=True) == "comfyui"
    assert ac.resolve_engine(comfy_preset, "auto", comfyui_available=False) == "internal"
    assert ac.resolve_engine(internal_preset, "auto", comfyui_available=True) == "internal"


def test_build_autoconfig_internal_3d_includes_motion_overrides():
    preset = ac.resolve_preset("cinematic_3d")
    cfg = ac.build_autoconfig(
        preset,
        engine="auto",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="quality",
        preferred_model="hf_sdxl_internal",
        device_preference="cuda",
        duration_s=8.0,
        fps=24,
        comfyui_available=False,
    )
    assert cfg.engine == "internal"
    req = cfg.internal_request
    assert req["deforum_translation_z"]
    assert req["deforum_rotation_3d_y"]
    assert req["render_tier"] == "quality"
    assert req["temporal_mode"] == "frame_img2img"
    assert req["model_id"] == "hf_sdxl_internal"
    assert cfg.comfyui_request is None


def test_build_autoconfig_full_motion_uses_storyboard_video_model():
    preset = ac.resolve_preset("full_motion")
    cfg = ac.build_autoconfig(
        preset,
        engine="internal",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="quality",
        preferred_model="hf_sdxl_internal",
        device_preference="cuda",
        duration_s=8.0,
        fps=24,
        comfyui_available=False,
    )
    req = cfg.internal_request
    assert req["temporal_mode"] == "video_model"
    assert req["motion_strategy"] == "storyboard_full_motion"
    assert req["video_model_engine"] == "auto"
    assert req["video_model_motion_score_mode"] == "auto"
    assert req["video_model_scene_motion"] == "scene"
    assert req["video_model_apply_timeline_camera"] is True
    assert req["video_model_noise_aug_strength"] >= 0.06
    assert any("storyboard full motion" in note.lower() for note in cfg.notes)


def test_build_autoconfig_full_motion_uses_tensorrt_storyboard_anchors_when_available():
    preset = ac.resolve_preset("full_motion")
    cfg = ac.build_autoconfig(
        preset,
        engine="internal",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="quality",
        preferred_model="hf_sdxl_internal",
        device_preference="cuda",
        duration_s=8.0,
        fps=24,
        comfyui_available=False,
        tensorrt_sd15_available=True,
    )
    req = cfg.internal_request
    assert req["temporal_mode"] == "video_model"
    assert req["motion_strategy"] == "storyboard_full_motion"
    assert req["video_model_keyframe_renderer"] == "tensorrt_sd15"
    assert req["video_model_keyframe_model_id"] == "local_sd15_tensorrt_bundle"
    assert any("tensorrt sd1.5 storyboard anchors" in note.lower() for note in cfg.notes)


def test_build_autoconfig_image_animation_sets_source():
    preset = ac.resolve_preset("image_animation")
    cfg = ac.build_autoconfig(
        preset,
        engine="internal",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="balanced",
        duration_s=6.0,
        fps=24,
        source_asset="assets/refs/painting.png",
        comfyui_available=False,
    )
    assert cfg.uses_source_image is True
    assert cfg.internal_request["source_asset"] == "assets/refs/painting.png"
    assert 0.05 <= cfg.internal_request["source_strength"] <= 0.95


def test_build_autoconfig_image_animation_without_source_warns():
    preset = ac.resolve_preset("image_animation")
    cfg = ac.build_autoconfig(
        preset,
        engine="internal",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="balanced",
        duration_s=6.0,
        fps=24,
        source_asset=None,
        comfyui_available=False,
    )
    assert cfg.uses_source_image is False
    assert "source_asset" not in cfg.internal_request
    assert any("no source image" in n.lower() for n in cfg.notes)


def test_build_autoconfig_comfyui_path_builds_motion_request():
    preset = ac.resolve_preset("comfyui_animatediff")
    cfg = ac.build_autoconfig(
        preset,
        engine="auto",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="balanced",
        duration_s=8.0,
        fps=24,
        comfyui_available=True,
    )
    assert cfg.engine == "comfyui"
    assert cfg.comfyui_request is not None
    assert cfg.comfyui_request["engine"] == "animatediff"


def test_build_autoconfig_comfyui_downgrade_when_unavailable():
    preset = ac.resolve_preset("comfyui_animatediff")
    cfg = ac.build_autoconfig(
        preset,
        engine="comfyui",
        tier_defaults=_TIER_DEFAULTS,
        applied_tier="balanced",
        duration_s=8.0,
        fps=24,
        comfyui_available=False,
    )
    assert cfg.engine == "internal"
    assert any("comfyui not reachable" in n.lower() for n in cfg.notes)
