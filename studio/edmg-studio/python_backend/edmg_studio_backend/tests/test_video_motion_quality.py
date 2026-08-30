from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from edmg_studio_backend import app as app_module
from edmg_studio_backend.services.internal_video import (
    InternalVideoSettings,
    _cached_motion_validation_passed,
    _cached_native_motion_report,
    _use_direct_video_model_source_anchor,
    describe_internal_video_model_preflight,
)
from edmg_studio_backend.services.video_motion_quality import (
    analyze_motion_images,
    describe_video_model_frame_budget,
    temporal_blend_frame,
)


def _moving_square_frames(count: int = 8) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for index in range(count):
        frame = Image.new("RGB", (128, 72), (20, 24, 30))
        draw = ImageDraw.Draw(frame)
        left = 6 + index * 12
        draw.rectangle((left, 25, left + 13, 38), fill=(235, 210, 90))
        frames.append(frame)
    return frames


def test_two_long_still_holds_fail_distributed_motion_validation() -> None:
    first = Image.new("RGB", (128, 72), "black")
    second = Image.new("RGB", (128, 72), "white")

    report = analyze_motion_images([first] * 30 + [second] * 30, fps=1)

    assert report["status"] == "fail"
    assert report["perceptually_unique_frames"] == 2
    assert report["meaningful_transition_count"] == 1
    assert report["frozen_pair_ratio"] > 0.98
    assert report["longest_static_hold_s"] == 29.0
    assert "motion_not_distributed" in report["failures"]


def test_progressive_subject_motion_passes_validation() -> None:
    report = analyze_motion_images(_moving_square_frames(), fps=4)

    assert report["status"] == "pass"
    assert report["perceptually_unique_frames"] == 8
    assert report["meaningful_transition_count"] == 7
    assert report["motion_quartiles"] == [0, 1, 2, 3]
    assert report["longest_static_hold_s"] == 0.0


def test_temporal_blending_does_not_repeat_two_endpoint_frames() -> None:
    black = Image.new("RGB", (8, 8), "black")
    white = Image.new("RGB", (8, 8), "white")

    samples = [
        temporal_blend_frame([black, white], output_index=index, output_frame_count=5)
        for index in range(5)
    ]
    levels = [sample.getpixel((0, 0))[0] for sample in samples]

    assert levels == [0, 63, 127, 191, 255]
    assert len(set(levels)) == 5


def test_frame_budget_rejects_two_frames_stretched_across_a_minute() -> None:
    rejected = describe_video_model_frame_budget(
        native_frame_count=2,
        output_frame_count=60,
        fps=1,
    )
    accepted = describe_video_model_frame_budget(
        native_frame_count=8,
        output_frame_count=16,
        fps=4,
    )

    assert rejected["status"] == "fail"
    assert rejected["stretch_ratio"] == 30.0
    assert rejected["issues"] == ["native_frame_count", "frame_stretch_ratio"]
    assert accepted["status"] == "pass"
    assert accepted["stretch_ratio"] == 2.0


def test_frame_budget_requires_four_raw_output_frames_but_allows_native_downsampling() -> None:
    too_short = describe_video_model_frame_budget(
        native_frame_count=8,
        output_frame_count=2,
        fps=2,
    )
    accepted = describe_video_model_frame_budget(
        native_frame_count=8,
        output_frame_count=4,
        fps=2,
    )

    assert too_short["status"] == "fail"
    assert too_short["issues"] == ["output_frame_count"]
    assert accepted["status"] == "pass"


def test_preflight_blocks_the_failed_two_frame_motion_plan() -> None:
    report = describe_internal_video_model_preflight(
        scenes=[{"start_s": 0.0, "end_s": 60.0, "prompt": "robot among orchids"}],
        timeline=None,
        settings=InternalVideoSettings(
            fps_render=1,
            fps_output=1,
            temporal_mode="video_model",
            motion_strategy="manual",
            video_model_engine="svd",
            video_model_max_frames_per_scene=2,
            device_preference="cuda",
        ),
        duration_s=60.0,
        total_frames=60,
        hardware={"backend": "cuda", "vram_gb": 6.0},
    )

    density_check = next(item for item in report["checks"] if item["name"] == "motion_density")
    budget = report["motion_frame_budgets"][0]

    assert density_check["status"] == "error"
    assert budget["status"] == "fail"
    assert budget["native_frame_count"] == 2
    assert budget["output_frame_count"] == 60
    assert any("Motion-frame density is too low" in warning for warning in report["warnings"])


def test_preflight_accepts_eight_native_frames_for_one_short_shot() -> None:
    report = describe_internal_video_model_preflight(
        scenes=[{"start_s": 0.0, "end_s": 4.0, "prompt": "robot moving among orchids"}],
        timeline=None,
        settings=InternalVideoSettings(
            fps_render=2,
            fps_output=24,
            interpolation_engine="minterpolate",
            temporal_mode="video_model",
            motion_strategy="storyboard_full_motion",
            storyboard_shot_max_s=4.0,
            video_model_engine="svd",
            video_model_max_frames_per_scene=8,
            video_model_cpu_offload=True,
            device_preference="cuda",
        ),
        duration_s=4.0,
        total_frames=8,
        hardware={"backend": "cuda", "vram_gb": 6.0},
    )

    density_check = next(item for item in report["checks"] if item["name"] == "motion_density")
    budget = report["motion_frame_budgets"][0]

    assert density_check["status"] == "ok"
    assert budget["status"] == "pass"
    assert budget["native_frame_count"] == 8
    assert budget["output_frame_count"] == 8
    assert report["motion_validation_required"] is True


def test_storyboard_full_motion_preserves_selected_flux_source() -> None:
    source_asset = "outputs/images/flux-source.png"
    settings = InternalVideoSettings(
        motion_strategy="storyboard_full_motion",
        storyboard_shot_max_s=4.0,
        keyframe_interval_s=8.0,
        source_asset=source_asset,
    )

    resolved = app_module._apply_storyboard_full_motion_settings(settings, {})

    assert resolved.source_asset == source_asset
    assert resolved.keyframe_interval_s == 4.0
    assert resolved.keyframe_continuity_mode == "project"


def test_selected_source_is_direct_first_anchor_independent_of_keyframe_renderer() -> None:
    source = Path("source.png")

    assert _use_direct_video_model_source_anchor(
        keyframe_index=0,
        source_image_path=source,
        temporal_mode="video_model",
    )
    assert not _use_direct_video_model_source_anchor(
        keyframe_index=1,
        source_image_path=source,
        temporal_mode="video_model",
    )
    assert not _use_direct_video_model_source_anchor(
        keyframe_index=0,
        source_image_path=source,
        temporal_mode="keyframes",
    )


def test_cached_video_is_reusable_only_with_passing_native_and_output_motion(
    tmp_path,
) -> None:
    metadata_path = tmp_path / "render.json"
    metadata_path.write_text(
        """
        {
          "motion_validation": {
            "status": "pass",
            "expected_native_scene_count": 1,
            "native_scenes": [
              {"status": "pass", "scene_index": 0, "shot_index": 0}
            ],
            "output_sequence": {"status": "pass"}
          }
        }
        """,
        encoding="utf-8",
    )

    assert _cached_motion_validation_passed(metadata_path) is True

    metadata_path.write_text(
        '{"motion_validation":{"status":"pass","expected_native_scene_count":1,"native_scenes":[],"output_sequence":{"status":"pass"}}}',
        encoding="utf-8",
    )
    assert _cached_motion_validation_passed(metadata_path) is False

    metadata_path.write_text(
        '{"motion_validation":{"status":"pass","expected_native_scene_count":2,"native_scenes":[{"status":"pass","scene_index":0,"shot_index":0}],"output_sequence":{"status":"pass"}}}',
        encoding="utf-8",
    )
    assert _cached_motion_validation_passed(metadata_path) is False


def test_cached_scene_frames_require_a_matching_passing_native_motion_report(
    tmp_path,
) -> None:
    metadata_path = tmp_path / "render.json"
    metadata_path.write_text(
        """
        {
          "motion_validation": {
            "status": "pass",
            "expected_native_scene_count": 2,
            "native_scenes": [
              {"status": "pass", "scene_index": 2, "shot_index": 1},
              {"status": "fail", "scene_index": 2, "shot_index": 2}
            ],
            "output_sequence": {"status": "pass"}
          }
        }
        """,
        encoding="utf-8",
    )

    matched = _cached_native_motion_report(
        metadata_path,
        scene_index=2,
        shot_index=1,
    )

    assert matched is not None
    assert matched["status"] == "pass"
    assert (
        _cached_native_motion_report(
            metadata_path,
            scene_index=2,
            shot_index=2,
        )
        is None
    )
    assert (
        _cached_native_motion_report(
            metadata_path,
            scene_index=3,
            shot_index=1,
        )
        is None
    )
