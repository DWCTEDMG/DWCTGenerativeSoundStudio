"""Tests for full (2D + 3D) motion capabilities in the internal engine."""

from __future__ import annotations

import pytest

from edmg_studio_backend.services import internal_video as iv
from edmg_studio_backend.services.deforum_motion import (
    DeforumMotionScheduleBundle,
    evaluate_motion_state,
    merge_motion_schedule_bundles,
    motion_bundle_from_mapping,
)
from edmg_studio_backend.services.deforum_normalize import build_deforum_render_context

Image = pytest.importorskip("PIL.Image")


def _gradient_image(w: int = 64, h: int = 48):
    img = iv.Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 4 % 256, y * 5 % 256, (x + y) * 3 % 256)
    return img


# ---------------------------------------------------------------------------
# Motion model: schedules / state
# ---------------------------------------------------------------------------


def test_motion_bundle_parses_3d_fields_and_aliases():
    bundle = motion_bundle_from_mapping(
        {
            "translation_z": "0:(0), 10:(50)",
            "pitch": "0:(0), 10:(20)",  # alias -> rotation_3d_x
            "yaw": "0:(0), 10:(30)",  # alias -> rotation_3d_y
            "roll": "0:(0), 10:(15)",  # alias -> rotation_3d_z
            "fov": "0:(70)",
        }
    )
    assert bundle.has_3d_motion() is True
    assert bundle.has_camera_motion() is True
    assert bundle.translation_z and bundle.rotation_3d_x
    assert bundle.rotation_3d_y and bundle.rotation_3d_z


def test_evaluate_motion_state_interpolates_3d():
    bundle = motion_bundle_from_mapping(
        {
            "translation_z": "0:(0), 10:(50)",
            "rotation_3d_x": "0:(0), 10:(20)",
            "rotation_3d_y": "0:(0), 10:(30)",
            "rotation_3d_z": "0:(0), 10:(10)",
            "fov": "0:(70), 10:(50)",
        }
    )
    state = evaluate_motion_state(5, bundle)
    assert state.translation_z == pytest.approx(25.0)
    assert state.rotation_3d_x == pytest.approx(10.0)
    assert state.rotation_3d_y == pytest.approx(15.0)
    assert state.rotation_3d_z == pytest.approx(5.0)
    assert state.fov == pytest.approx(60.0)

    params = state.to_renderer_params()
    for key in ("translation_z", "rotation_3d_x", "rotation_3d_y", "rotation_3d_z", "fov"):
        assert key in params


def test_fov_is_clamped():
    bundle = motion_bundle_from_mapping({"fov": "0:(5)"})
    assert evaluate_motion_state(0, bundle).fov == pytest.approx(10.0)
    bundle = motion_bundle_from_mapping({"fov": "0:(400)"})
    assert evaluate_motion_state(0, bundle).fov == pytest.approx(179.0)


def test_3d_only_motion_counts_as_camera_motion():
    bundle = motion_bundle_from_mapping({"rotation_3d_y": "0:(0), 10:(30)"})
    assert bundle.has_2d_motion() is False
    assert bundle.has_3d_motion() is True
    assert bundle.has_camera_motion() is True


def test_merge_preserves_3d_fields():
    a = DeforumMotionScheduleBundle(translation_z=((0, 1.0),))
    b = DeforumMotionScheduleBundle(rotation_3d_y=((0, 5.0),))
    merged = merge_motion_schedule_bundles(a, b)
    assert merged.translation_z == ((0, 1.0),)
    assert merged.rotation_3d_y == ((0, 5.0),)


# ---------------------------------------------------------------------------
# Normalization: variant / overrides / timeline track
# ---------------------------------------------------------------------------


def test_build_context_picks_up_variant_3d_schedules():
    variant = {
        "motion_schedules": {
            "translation_z": "0:(0), 10:(50)",
            "rotation_3d_y": "0:(0), 10:(30)",
        }
    }
    ctx = build_deforum_render_context(
        scenes=[], timeline=None, variant=variant, fps=10, default_negative_prompt=""
    )
    assert ctx.motion.has_3d_motion() is True
    state = evaluate_motion_state(5, ctx.motion)
    assert state.translation_z == pytest.approx(25.0)
    assert state.rotation_3d_y == pytest.approx(15.0)


def test_build_context_request_override_3d():
    ctx = build_deforum_render_context(
        scenes=[],
        timeline=None,
        variant=None,
        fps=10,
        default_negative_prompt="",
        overrides={"deforum_rotation_3d_x": "0:(0), 10:(20)"},
    )
    assert ctx.motion.has_3d_motion() is True
    assert evaluate_motion_state(10, ctx.motion).rotation_3d_x == pytest.approx(20.0)


def test_motion_track_clip_3d_schedule():
    timeline = {
        "tracks": [
            {
                "type": "motion",
                "clips": [
                    {
                        "start_s": 0.0,
                        "end_s": 1.0,
                        "data": {"yaw": "0:(0), 10:(30)"},
                    }
                ],
            }
        ]
    }
    ctx = build_deforum_render_context(
        scenes=[], timeline=timeline, variant=None, fps=10, default_negative_prompt=""
    )
    assert ctx.motion.has_3d_motion() is True
    assert evaluate_motion_state(10, ctx.motion).rotation_3d_y == pytest.approx(30.0)


def test_camera_curve_keeps_velocity_through_interior_keyframe():
    timeline = {
        "camera": {
            "keyframes": [
                {"t": 0.0, "zoom": 1.0},
                {"t": 1.0, "zoom": 1.1},
                {"t": 2.0, "zoom": 1.2},
            ]
        }
    }

    before = iv._camera_components_at_time(0.99, timeline=timeline, fallback_interval_s=5.0).zoom
    center = iv._camera_components_at_time(1.0, timeline=timeline, fallback_interval_s=5.0).zoom
    after = iv._camera_components_at_time(1.01, timeline=timeline, fallback_interval_s=5.0).zoom

    assert center - before == pytest.approx(after - center, rel=1e-4)
    assert center - before > 0.0009


def test_camera_normalizer_coalesces_subframe_generated_pose_collision():
    points = [
        {"t": 0.0, "pan_x": 0.0},
        {"t": 5.0, "pan_x": 10.0},
        {"t": 5.05, "pan_x": -8.0},
    ]

    normalized = iv._normalize_camera_keyframes(points)

    assert len(normalized) == 2
    assert normalized[-1]["t"] == 5.0
    assert normalized[-1]["pan_x"] == -8.0


def test_camera_normalizer_preserves_explicit_cut_pose():
    points = [
        {"t": 0.0, "pan_x": 0.0},
        {"t": 5.0, "pan_x": 10.0, "easing": "cut"},
        {"t": 5.05, "pan_x": -8.0, "easing": "smoothstep"},
    ]

    normalized = iv._normalize_camera_keyframes(points)

    assert len(normalized) == 3
    assert normalized[1]["easing"] == "cut"


def test_camera_cut_switches_pose_at_exact_boundary():
    timeline = {
        "camera": {
            "keyframes": [
                {"t": 0.0, "pan_x": 1.0, "easing": "cut"},
                {"t": 1.0, "pan_x": 9.0, "easing": "smoothstep"},
            ]
        }
    }

    just_before = iv._camera_components_at_time(0.999, timeline=timeline, fallback_interval_s=5.0)
    at_cut = iv._camera_components_at_time(1.0, timeline=timeline, fallback_interval_s=5.0)

    assert just_before.pan_x == pytest.approx(1.0)
    assert at_cut.pan_x == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# Geometry: projection + perspective transform
# ---------------------------------------------------------------------------


def test_project_corners_neutral_is_identity():
    w, h = 64, 48
    dst = iv._project_image_corners(
        w,
        h,
        rot_x_deg=0.0,
        rot_y_deg=0.0,
        rot_z_deg=0.0,
        translation_x=0.0,
        translation_y=0.0,
        translation_z=0.0,
        fov_deg=70.0,
    )
    expected = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    for (ux, uy), (ex, ey) in zip(dst, expected, strict=False):
        assert ux == pytest.approx(ex, abs=1e-6)
        assert uy == pytest.approx(ey, abs=1e-6)


def test_project_corners_yaw_makes_trapezoid():
    w, h = 64, 48
    dst = iv._project_image_corners(
        w,
        h,
        rot_x_deg=0.0,
        rot_y_deg=25.0,
        rot_z_deg=0.0,
        translation_x=0.0,
        translation_y=0.0,
        translation_z=0.0,
        fov_deg=70.0,
    )
    # dst order: top-left, top-right, bottom-right, bottom-left
    left_edge_height = dst[3][1] - dst[0][1]
    right_edge_height = dst[2][1] - dst[1][1]
    # Positive yaw brings the right edge closer to the camera -> taller.
    assert right_edge_height > left_edge_height


def test_translation_z_dolly_in_enlarges():
    w, h = 64, 48
    dst = iv._project_image_corners(
        w,
        h,
        rot_x_deg=0.0,
        rot_y_deg=0.0,
        rot_z_deg=0.0,
        translation_x=0.0,
        translation_y=0.0,
        translation_z=100.0,  # dolly forward
        fov_deg=70.0,
    )
    # Corners should spread outside the original frame (zoom-in effect).
    assert dst[0][0] < 0.0 and dst[0][1] < 0.0
    assert dst[2][0] > w and dst[2][1] > h


def test_perspective_coeffs_identity_roundtrip():
    w, h = 64, 48
    src = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    coeffs = iv._perspective_coeffs(src, src)
    # Identity mapping: a == e == i_scale 1, others ~0
    assert coeffs[0] == pytest.approx(1.0, abs=1e-6)
    assert coeffs[4] == pytest.approx(1.0, abs=1e-6)
    assert coeffs[1] == pytest.approx(0.0, abs=1e-6)
    assert coeffs[3] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Frame warp application
# ---------------------------------------------------------------------------


def test_apply_camera_3d_no_3d_matches_ken_burns():
    img = _gradient_image()
    out_kb = iv._ken_burns_frame(img, img.width, img.height, zoom=1.0, pan_x=0.0, pan_y=0.0)
    out_3d = iv._apply_camera_3d(
        img,
        img.width,
        img.height,
        zoom=1.0,
        pan_x=0.0,
        pan_y=0.0,
        rotation_deg=0.0,
        translation_z=0.0,
        rotation_3d_x=0.0,
        rotation_3d_y=0.0,
    )
    assert out_3d.size == out_kb.size
    assert out_3d.tobytes() == out_kb.tobytes()


def test_apply_camera_3d_with_yaw_changes_pixels():
    img = _gradient_image()
    out_3d = iv._apply_camera_3d(
        img,
        img.width,
        img.height,
        zoom=1.0,
        rotation_3d_y=25.0,
    )
    assert out_3d.size == (img.width, img.height)
    assert out_3d.tobytes() != img.tobytes()


def test_pan_at_unit_zoom_adds_overscan_and_changes_pixels():
    img = _gradient_image()
    moved = iv._ken_burns_frame(
        img,
        img.width,
        img.height,
        zoom=1.0,
        pan_x=8.0,
        pan_y=0.0,
    )
    assert moved.size == img.size
    assert moved.tobytes() != img.tobytes()


def test_video_model_timeline_camera_overlay_applies_and_can_be_disabled():
    img = _gradient_image()
    timeline = {
        "camera": {
            "keyframes": [
                {"t": 0.0, "zoom": 1.0, "pan_x": 0.0, "rotation_3d_y": 0.0},
                {"t": 1.0, "zoom": 1.08, "pan_x": 8.0, "rotation_3d_y": 10.0},
            ]
        }
    }
    bypassed = iv._apply_video_model_timeline_camera(
        img,
        img.width,
        img.height,
        t=1.0,
        timeline=timeline,
        fallback_interval_s=5.0,
        deforum_motion=None,
        fps=24,
        enabled=False,
    )
    applied = iv._apply_video_model_timeline_camera(
        img,
        img.width,
        img.height,
        t=1.0,
        timeline=timeline,
        fallback_interval_s=5.0,
        deforum_motion=None,
        fps=24,
        enabled=True,
    )
    assert bypassed.tobytes() == img.tobytes()
    assert applied.tobytes() != bypassed.tobytes()


def test_video_model_timeline_camera_overlay_skips_unauthored_fallback():
    img = _gradient_image()
    applied = iv._apply_video_model_timeline_camera(
        img,
        img.width,
        img.height,
        t=1.0,
        timeline={},
        fallback_interval_s=5.0,
        deforum_motion=None,
        fps=24,
        enabled=True,
    )
    assert applied.tobytes() == img.tobytes()


def test_camera_components_delta_neutral_is_identity():
    img = _gradient_image()
    comp = iv._CameraComponents(rotation_3d_y=12.0, translation_z=30.0)
    out = iv._apply_camera_components_delta(img, img.width, img.height, comp, comp)
    # No frame-to-frame change -> identity (reduces to ken-burns identity).
    assert out.tobytes() == img.tobytes()


# ---------------------------------------------------------------------------
# Camera evaluator: timeline 3D keyframes
# ---------------------------------------------------------------------------


def test_camera_components_from_timeline_3d_keyframes():
    timeline = {
        "camera": {
            "keyframes": [
                {"t": 0.0, "rotation_3d_y": 0.0, "fov": 70.0},
                {"t": 1.0, "rotation_3d_y": 20.0, "fov": 50.0},
            ]
        }
    }
    comp = iv._camera_components_at_time(
        0.5, timeline=timeline, fallback_interval_s=5.0, fps=24
    )
    assert 0.0 < comp.rotation_3d_y < 20.0
    assert 50.0 < comp.fov < 70.0


def test_camera_components_from_motion_bundle_3d():
    bundle = motion_bundle_from_mapping({"rotation_3d_x": "0:(0), 24:(24)"})
    comp = iv._camera_components_at_time(
        1.0, timeline=None, fallback_interval_s=5.0, deforum_motion=bundle, fps=24
    )
    assert comp.rotation_3d_x == pytest.approx(24.0)


def test_camera_at_time_backward_compatible_tuple():
    result = iv._camera_at_time(0.0, timeline=None, fallback_interval_s=5.0, fps=24)
    assert isinstance(result, tuple) and len(result) == 4
    assert all(isinstance(v, float) for v in result)
