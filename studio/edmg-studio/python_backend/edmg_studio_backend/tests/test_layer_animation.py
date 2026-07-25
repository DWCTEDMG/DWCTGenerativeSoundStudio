"""Tests for object/layer animation (parallax / masked / segment)."""

from __future__ import annotations

from pathlib import Path

import pytest

from edmg_studio_backend.services import internal_video as iv
from edmg_studio_backend.services import layer_animation as la

Image = pytest.importorskip("PIL.Image")


def _img(w=128, h=96):
    im = iv.Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 2 % 256, y * 2 % 256, (x + y) % 256)
    return im


def _mask(w=128, h=96, *, left=True):
    m = iv.Image.new("L", (w, h), 0)
    px = m.load()
    for y in range(h):
        for x in range(w):
            inside = x < w // 2 if left else x >= w // 2
            px[x, y] = 255 if inside else 0
    return m


def test_scaled_components_parallax_math():
    comp = iv._CameraComponents(zoom=1.2, pan_x=40.0, translation_z=100.0, rotation_3d_y=20.0)
    near = la._scaled_components(comp, 1.0)
    far = la._scaled_components(comp, 0.0)
    assert near.pan_x == pytest.approx(40.0)
    assert near.translation_z == pytest.approx(100.0)
    # far layer barely reacts
    assert far.pan_x == pytest.approx(0.0)
    assert far.translation_z == pytest.approx(0.0)
    assert far.zoom == pytest.approx(1.0)
    # half depth = half excursion
    mid = la._scaled_components(comp, 0.5)
    assert mid.pan_x == pytest.approx(20.0)
    assert mid.zoom == pytest.approx(1.1)


def test_parallax_layers_have_increasing_depth():
    layers = la.parallax_layers_from_image(_img(), 128, 96, bands=3)
    assert layers[0].name == "background"
    band_depths = [lyr.depth for lyr in layers if lyr.name.startswith("band_")]
    assert band_depths == sorted(band_depths)
    assert layers[0].depth < band_depths[-1]


def test_apply_alpha_matches_mask():
    base = _img()
    mask = _mask(left=True)
    rgba = la._apply_alpha(base, mask)
    assert rgba.mode == "RGBA"
    assert rgba.split()[-1].tobytes() == mask.tobytes()


def test_layers_from_masks_builds_object_layers():
    base = _img()
    specs = [{"mask": _mask(left=True), "depth": 1.0, "name": "obj_a"}]
    layers = la.layers_from_masks(base, 128, 96, specs)
    assert [lyr.name for lyr in layers] == ["background", "obj_a"]
    assert layers[1].depth == 1.0


def test_auto_segment_uses_fallback_without_rembg():
    layers, method = la.auto_segment_layers(_img(), 128, 96, mode="subject")
    assert [lyr.name for lyr in layers] == ["background", "subject"]
    # background nearly static, subject moves
    assert layers[0].depth < layers[1].depth
    assert method in ("rembg", "saliency_fallback")


def test_auto_segment_background_mode_moves_background():
    layers, _ = la.auto_segment_layers(_img(), 128, 96, mode="background")
    bg = next(lyr for lyr in layers if lyr.name == "background")
    subj = next(lyr for lyr in layers if lyr.name == "subject")
    assert bg.depth > subj.depth


def test_compose_frame_changes_with_motion():
    from edmg_studio_backend.services.deforum_motion import motion_bundle_from_mapping

    layers = la.parallax_layers_from_image(_img(), 128, 96, bands=3)
    bundle = motion_bundle_from_mapping({"translation_x": "0:(0), 48:(60)", "translation_z": "0:(0), 48:(80)"})
    f0 = la.compose_layered_frame(layers, 128, 96, t=0.0, fps=24, motion_bundle=bundle)
    f1 = la.compose_layered_frame(layers, 128, 96, t=1.5, fps=24, motion_bundle=bundle)
    assert f0.size == (128, 96)
    assert f0.tobytes() != f1.tobytes()


def test_build_layers_unknown_mode_raises():
    from edmg_studio_backend.errors import UserFacingError

    with pytest.raises(UserFacingError):
        la.build_layers(_img(), 128, 96, mode="nonsense")


def test_render_layered_animation_parallax(tmp_path):
    src = tmp_path / "src.png"
    _img(256, 144).save(src)
    res = la.render_layered_animation(
        ffmpeg_path="ffmpeg",
        source_image_path=src,
        out_dir=tmp_path / "out",
        mode="parallax",
        motion_schedule={"translation_x": "0:(0), 24:(40)", "translation_z": "0:(0), 24:(60)"},
        fps=12,
        duration_s=1.0,
        width=256,
        height=144,
        bands=3,
    )
    assert res["ok"] is True
    assert res["frames"] == 12
    assert Path(res["video"]).exists()
    assert Path(res["video"]).stat().st_size > 0


def test_diffusion_refine_invokes_img2img(tmp_path, monkeypatch):
    """Refine path runs img2img over each composited frame (model monkeypatched)."""
    src = tmp_path / "src.png"
    _img(256, 144).save(src)

    calls = {"n": 0}

    def fake_load_pipelines(model_dir, device="cpu", **kw):
        return object()  # sentinel pipes

    def fake_encode_prompt(pipes, prompt):
        return f"enc:{prompt}"

    def fake_img2img(pipes, *, init_image, prompt_embeds, negative_embeds, width, height, steps, cfg, seed, strength):
        calls["n"] += 1
        # return a recognizable solid-red frame to prove refinement replaced the composite
        return iv.Image.new("RGB", (width, height), (255, 0, 0))

    monkeypatch.setattr(iv, "_try_load_pipelines", fake_load_pipelines)
    monkeypatch.setattr(iv, "_encode_prompt", fake_encode_prompt)
    monkeypatch.setattr(iv, "_generate_img2img", fake_img2img)

    model_dir = tmp_path / "fake_model"
    model_dir.mkdir()
    res = la.render_layered_animation(
        ffmpeg_path="ffmpeg",
        source_image_path=src,
        out_dir=tmp_path / "out_refine",
        mode="parallax",
        motion_schedule={"translation_x": "0:(0), 12:(30)"},
        fps=6,
        duration_s=1.0,
        width=256,
        height=144,
        diffusion_refine=True,
        refine_model_dir=model_dir,
        refine_device="cpu",
        refine_prompt="oil painting, vivid",
        refine_denoise=0.3,
        refine_steps=8,
    )
    assert res["diffusion_refined"] is True
    assert res["refined_frames"] == 6
    assert calls["n"] == 6
    # the saved frames should be the refined (solid red) output
    frame0 = iv.Image.open(tmp_path / "out_refine" / "frames" / "frame_000000.png").convert("RGB")
    assert frame0.getpixel((10, 10)) == (255, 0, 0)


def test_diffusion_refine_without_model_falls_back(tmp_path):
    src = tmp_path / "src.png"
    _img(256, 144).save(src)
    res = la.render_layered_animation(
        ffmpeg_path="ffmpeg",
        source_image_path=src,
        out_dir=tmp_path / "out_norefine",
        mode="parallax",
        motion_schedule={"translation_x": "0:(0), 12:(30)"},
        fps=6,
        duration_s=1.0,
        width=256,
        height=144,
        diffusion_refine=True,
        refine_model_dir=None,  # no model -> graceful compositing-only
    )
    assert res["ok"] is True
    assert res["diffusion_refined"] is False
    assert res["refined_frames"] == 0


def test_render_layered_animation_segment(tmp_path):
    src = tmp_path / "src.png"
    _img(256, 144).save(src)
    res = la.render_layered_animation(
        ffmpeg_path="ffmpeg",
        source_image_path=src,
        out_dir=tmp_path / "out_seg",
        mode="segment",
        motion_schedule={"translation_x": "0:(0), 24:(30)", "rotation_3d_y": "0:(0), 24:(12)"},
        fps=12,
        duration_s=1.0,
        width=256,
        height=144,
    )
    assert res["ok"] is True
    assert res["layers"] == ["background", "subject"]
