"""Tests for the expanded CPU proxy renderer (no diffusion / no GPU).

These cover the new motion + finishing capabilities added to the internal
renderer's proxy path so the local draft loop produces richer output.
"""
from __future__ import annotations

import shutil

import pytest

from edmg_studio_backend.services.internal_video import (
    InternalVideoSettings,
    _apply_proxy_finish,
    _apply_proxy_motion,
    _build_proxy_base_frame,
    _proxy_camera_at_time,
    _proxy_energy_at_time,
    render_internal_proxy_video_variant,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _sample_scenes():
    return [
        {"start_s": 0.0, "end_s": 1.0, "name": "Intro", "prompt": "neon skyline", "energy": 0.2},
        {"start_s": 1.0, "end_s": 2.0, "name": "Drop", "prompt": "strobing crowd", "energy": 0.9},
    ]


def _sample_timeline():
    return {
        "camera": {
            "keyframes": [
                {"t": 0.0, "zoom": 1.0, "pan_x": 0.0, "pan_y": 0.0},
                {"t": 2.0, "zoom": 1.4, "pan_x": 0.5, "pan_y": -0.3},
            ]
        }
    }


def test_camera_interpolation_endpoints_and_midpoint():
    timeline = _sample_timeline()
    assert _proxy_camera_at_time(timeline, 0.0)["zoom"] == pytest.approx(1.0)
    assert _proxy_camera_at_time(timeline, 2.0)["zoom"] == pytest.approx(1.4)
    mid = _proxy_camera_at_time(timeline, 1.0)
    assert 1.0 < mid["zoom"] < 1.4
    # Out-of-range clamps to the nearest keyframe.
    assert _proxy_camera_at_time(timeline, 99.0)["zoom"] == pytest.approx(1.4)


def test_camera_defaults_without_keyframes():
    cam = _proxy_camera_at_time({}, 5.0)
    assert cam["zoom"] > 1.0
    assert abs(cam["pan_x"]) > 0.01 or abs(cam["pan_y"]) > 0.01


def test_energy_prefers_scene_value_then_breathes():
    assert _proxy_energy_at_time({"energy": 0.75}, 0.0, 10.0) == pytest.approx(0.75)
    breathed = _proxy_energy_at_time({}, 2.5, 10.0)
    assert 0.0 <= breathed <= 1.0


def test_motion_and_finish_preserve_frame_size_and_alter_pixels():
    scenes = _sample_scenes()
    base = _build_proxy_base_frame(width=160, height=90, t=1.5, duration_s=2.0, scene=scenes[1])
    assert base.size == (160, 90)

    moved = _apply_proxy_motion(base, {"zoom": 1.4, "pan_x": 0.5, "pan_y": -0.3}, energy=0.9)
    assert moved.size == (160, 90)
    # Zoom-in must actually change the framing.
    assert list(moved.getdata()) != list(base.getdata())

    finished = _apply_proxy_finish(moved, energy=0.9)
    assert finished.size == (160, 90)
    # Vignette must darken the corners relative to the center.
    corner = finished.getpixel((1, 1))
    center = finished.getpixel((80, 45))
    assert sum(corner) < sum(center)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")
def test_render_internal_proxy_video_produces_mp4(tmp_path):
    project_dir = tmp_path / "proj"
    (project_dir / "outputs").mkdir(parents=True, exist_ok=True)
    settings = InternalVideoSettings(
        fps_render=2,
        fps_output=2,
        width=128,
        height=72,
        render_tier="draft",
        proxy_motion=True,
        proxy_finish=True,
    )
    out = render_internal_proxy_video_variant(
        ffmpeg_path=shutil.which("ffmpeg"),
        project_dir=project_dir,
        variant={"index": 0, "duration_s": 1.0},
        scenes=_sample_scenes(),
        audio_path=None,
        settings=settings,
        timeline=_sample_timeline(),
    )
    assert out.exists()
    assert out.suffix == ".mp4"
    assert out.stat().st_size > 0
