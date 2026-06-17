"""Object / layer animation for the internal engine.

Animates *individual regions* of a still image instead of moving the whole
picture as one plane. The unifying primitive is a stack of RGBA **layers**, each
with its own depth (how strongly it reacts to the camera) and draw order. The
layers are warped independently with the 3D camera engine and alpha-composited,
which yields:

- **Parallax (2.5D)** - depth bands move by different amounts (option 1)
- **Mask-targeted motion** - a masked object moves over a held background (option 2)
- **Auto-segmentation** - a subject is auto-extracted (rembg if available, else a
  deterministic saliency fallback) and animated vs. the background (option 3)

ComfyUI regional / motion-mask animation (option 4) lives in
``integrations/comfyui.py`` and is wired through the render auto-config presets.

This module is pure compositing (no diffusion model required), so it runs and is
unit-testable without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import UserFacingError
from . import internal_video as iv
from .deforum_motion import DeforumMotionScheduleBundle, motion_bundle_from_mapping
from .ffmpeg import assemble_image_sequence

try:
    import numpy as np  # type: ignore
    from PIL import Image, ImageFilter  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore
    Image = None  # type: ignore
    ImageFilter = None  # type: ignore


def _require_pillow() -> None:
    if Image is None or np is None:
        raise UserFacingError(
            "Layer animation deps missing",
            hint="Install backend deps including Pillow + numpy, then retry.",
            code="INTERNAL_DEPS",
            status_code=500,
        )


@dataclass
class AnimationLayer:
    """One compositing layer.

    - ``rgba``: full-canvas RGBA image (object placed, rest transparent)
    - ``depth``: 0..1 motion response (near=1 reacts most, far~0 barely moves)
    - ``motion_scale``: extra multiplier on top of depth (e.g. hold a layer static)
    - ``order``: compositing order (low drawn first / behind)
    """

    name: str
    rgba: Image.Image
    depth: float = 1.0
    motion_scale: float = 1.0
    order: int = 0

    @property
    def factor(self) -> float:
        return max(0.0, float(self.depth) * float(self.motion_scale))


def _scaled_components(comp: iv._CameraComponents, factor: float) -> iv._CameraComponents:
    """Scale a camera pose by a depth factor (parallax)."""
    f = max(0.0, float(factor))
    return iv._CameraComponents(
        zoom=1.0 + (comp.zoom - 1.0) * f,
        pan_x=comp.pan_x * f,
        pan_y=comp.pan_y * f,
        rotation_deg=comp.rotation_deg * f,
        translation_z=comp.translation_z * f,
        rotation_3d_x=comp.rotation_3d_x * f,
        rotation_3d_y=comp.rotation_3d_y * f,
        rotation_3d_z=comp.rotation_3d_z * f,
        fov=comp.fov,
    )


def compose_layered_frame(
    layers: list[AnimationLayer],
    width: int,
    height: int,
    *,
    t: float,
    fps: int,
    motion_bundle: DeforumMotionScheduleBundle | None,
) -> Image.Image:
    """Composite all layers at time ``t`` with depth-scaled camera motion."""
    _require_pillow()
    if motion_bundle is not None and motion_bundle.has_camera_motion():
        base_comp = iv._camera_components_at_time(
            t, timeline=None, fallback_interval_s=1e9, deforum_motion=motion_bundle, fps=fps
        )
    else:
        base_comp = iv._CameraComponents()

    result = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    for layer in sorted(layers, key=lambda lyr: lyr.order):
        comp = _scaled_components(base_comp, layer.factor)
        warped = iv._apply_camera_components_absolute(layer.rgba, width, height, comp)
        if warped.mode != "RGBA":
            warped = warped.convert("RGBA")
        result = Image.alpha_composite(result, warped)
    return result.convert("RGB")


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _fit_canvas(img: Image.Image, width: int, height: int) -> Image.Image:
    return img.convert("RGB").resize((int(width), int(height)), resample=Image.LANCZOS)


def _apply_alpha(base_rgb: Image.Image, mask_l: Image.Image) -> Image.Image:
    rgba = base_rgb.convert("RGBA")
    r, g, b, _ = rgba.split()
    return Image.merge("RGBA", (r, g, b, mask_l.convert("L")))


def _horizontal_band_mask(width: int, height: int, index: int, bands: int) -> Image.Image:
    """Soft horizontal band mask (near=bottom). Bands overlap via feather."""
    bands = max(1, int(bands))
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    center = (index + 0.5) / bands
    half = (1.0 / bands) * 0.85
    # smooth trapezoid around the band center
    dist = np.abs(ys - center)
    alpha = np.clip(1.0 - (dist - half) / max(1e-3, half), 0.0, 1.0)
    alpha = np.broadcast_to(alpha, (height, width))
    return Image.fromarray((alpha * 255.0).astype(np.uint8), mode="L")


def _center_saliency_mask(width: int, height: int) -> Image.Image:
    """Deterministic fallback subject mask: soft centered ellipse."""
    yy = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    xx = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    # ellipse covering ~central 55% with feathered edge
    d = np.sqrt((xx / 0.55) ** 2 + (yy / 0.7) ** 2)
    alpha = np.clip(1.0 - (d - 0.6) / 0.5, 0.0, 1.0)
    return Image.fromarray((alpha * 255.0).astype(np.uint8), mode="L")


def segment_foreground_mask(img: Image.Image, width: int, height: int) -> tuple[Image.Image, str]:
    """Return (subject_mask_L, method). Uses rembg when installed, else fallback."""
    _require_pillow()
    try:  # pragma: no cover - exercised only when rembg is installed
        from rembg import remove as _rembg_remove  # type: ignore

        cut = _rembg_remove(img.convert("RGBA"))
        alpha = cut.split()[-1].resize((width, height), resample=Image.LANCZOS)
        if ImageFilter is not None:
            alpha = alpha.filter(ImageFilter.GaussianBlur(radius=2))
        return alpha, "rembg"
    except Exception:
        return _center_saliency_mask(width, height), "saliency_fallback"


# ---------------------------------------------------------------------------
# Decomposition into layers
# ---------------------------------------------------------------------------


def parallax_layers_from_image(
    img: Image.Image, width: int, height: int, *, bands: int = 3, background_motion: float = 0.12
) -> list[AnimationLayer]:
    """Option 1: split into depth bands (near=bottom) over a held background."""
    _require_pillow()
    bands = max(1, int(bands))
    base = _fit_canvas(img, width, height)
    layers = [AnimationLayer("background", base.convert("RGBA"), depth=background_motion, order=0)]
    for i in range(bands):
        depth = 0.45 + 0.55 * (i / max(1, bands - 1)) if bands > 1 else 1.0
        mask = _horizontal_band_mask(width, height, i, bands)
        layers.append(
            AnimationLayer(f"band_{i}", _apply_alpha(base, mask), depth=depth, order=i + 1)
        )
    return layers


def layers_from_masks(
    img: Image.Image,
    width: int,
    height: int,
    mask_specs: list[dict[str, Any]],
    *,
    background_motion: float = 0.1,
) -> list[AnimationLayer]:
    """Option 2: each provided mask becomes an independently-moving object layer."""
    _require_pillow()
    base = _fit_canvas(img, width, height)
    layers = [AnimationLayer("background", base.convert("RGBA"), depth=background_motion, order=0)]
    for idx, spec in enumerate(mask_specs or []):
        mask = spec.get("mask")
        if mask is None:
            continue
        mask_l = mask.convert("L").resize((width, height), resample=Image.LANCZOS)
        depth = float(spec.get("depth", 1.0))
        motion_scale = float(spec.get("motion_scale", 1.0))
        layers.append(
            AnimationLayer(
                spec.get("name", f"object_{idx}"),
                _apply_alpha(base, mask_l),
                depth=depth,
                motion_scale=motion_scale,
                order=idx + 1,
            )
        )
    return layers


def auto_segment_layers(
    img: Image.Image,
    width: int,
    height: int,
    *,
    mode: str = "subject",
    subject_motion: float = 1.0,
    background_motion: float = 0.12,
) -> tuple[list[AnimationLayer], str]:
    """Option 3: auto-extract a subject and animate subject or background.

    ``mode="subject"`` animates the subject over a near-static background;
    ``mode="background"`` parallaxes the background behind a near-static subject.
    Returns (layers, segmentation_method).
    """
    _require_pillow()
    base = _fit_canvas(img, width, height)
    subject_mask, method = segment_foreground_mask(img, width, height)
    subject_rgba = _apply_alpha(base, subject_mask)

    if mode == "background":
        bg_depth, subj_depth = 1.0, max(0.0, background_motion)
    else:  # subject
        bg_depth, subj_depth = max(0.0, background_motion), max(0.0, subject_motion)

    layers = [
        AnimationLayer("background", base.convert("RGBA"), depth=bg_depth, order=0),
        AnimationLayer("subject", subject_rgba, depth=subj_depth, order=1),
    ]
    return layers, method


def build_layers(
    img: Image.Image,
    width: int,
    height: int,
    *,
    mode: str,
    bands: int = 3,
    mask_specs: list[dict[str, Any]] | None = None,
    subject_motion: float = 1.0,
    background_motion: float = 0.12,
) -> tuple[list[AnimationLayer], str]:
    """Dispatch to the right decomposition. Returns (layers, method)."""
    m = (mode or "parallax").lower().strip()
    if m == "parallax":
        return parallax_layers_from_image(img, width, height, bands=bands, background_motion=background_motion), "parallax_bands"
    if m == "masked":
        return layers_from_masks(img, width, height, mask_specs or [], background_motion=background_motion), "masks"
    if m in ("segment", "subject"):
        return auto_segment_layers(img, width, height, mode="subject", subject_motion=subject_motion, background_motion=background_motion)
    if m == "background":
        return auto_segment_layers(img, width, height, mode="background", subject_motion=subject_motion, background_motion=background_motion)
    raise UserFacingError(
        f"Unknown layer-animation mode '{mode}'",
        hint="Use one of: parallax, masked, segment, background.",
        code="UNKNOWN_LAYER_MODE",
        status_code=400,
    )


# ---------------------------------------------------------------------------
# Renderer (pure compositing -> MP4)
# ---------------------------------------------------------------------------


def render_layered_animation(
    *,
    ffmpeg_path: str,
    source_image_path: Path,
    out_dir: Path,
    mode: str,
    motion_schedule: dict[str, Any] | None,
    fps: int = 24,
    duration_s: float = 5.0,
    width: int = 768,
    height: int = 432,
    bands: int = 3,
    mask_specs: list[dict[str, Any]] | None = None,
    subject_motion: float = 1.0,
    background_motion: float = 0.12,
    audio_path: Path | None = None,
    log_fn=None,
    progress_fn=None,
    cancel_check_fn=None,
    diffusion_refine: bool = False,
    refine_model_dir: Path | None = None,
    refine_device: str = "auto",
    refine_prompt: str = "",
    refine_negative: str = "blurry, low quality, watermark, text, logo",
    refine_denoise: float = 0.3,
    refine_steps: int = 20,
    refine_cfg: float = 7.0,
    refine_seed: int = 0,
) -> dict[str, Any]:
    """Render an object/layer animation to MP4.

    Base compositing needs no model. When ``diffusion_refine`` is set and a
    ``refine_model_dir`` resolves to an installed diffusers model, each composited
    frame is passed through img2img at ``refine_denoise`` to clean seams, fill
    disocclusion gaps generatively, and let ``refine_prompt`` restyle the moving
    objects. If the model can't load, it degrades gracefully to compositing-only.
    """
    _require_pillow()
    src = Image.open(source_image_path).convert("RGB")
    layers, method = build_layers(
        src,
        width,
        height,
        mode=mode,
        bands=bands,
        mask_specs=mask_specs,
        subject_motion=subject_motion,
        background_motion=background_motion,
    )
    bundle = motion_bundle_from_mapping(motion_schedule or {})

    # Optional diffusion refinement (reuses the internal engine's pipelines).
    pipes = None
    refine_active = False
    if diffusion_refine and refine_model_dir is not None:
        try:
            device = iv._device_auto(refine_device)
            pipes = iv._try_load_pipelines(Path(refine_model_dir), device=device)
            refine_active = True
            if log_fn:
                log_fn(f"Diffusion refine enabled (model={Path(refine_model_dir).name}, device={device})")
        except Exception as exc:  # pragma: no cover - depends on runtime model
            if log_fn:
                log_fn(f"Diffusion refine unavailable ({exc}); compositing only")
    elif diffusion_refine and refine_model_dir is None and log_fn:
        log_fn("Diffusion refine requested but no model installed; compositing only")

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, int(round(float(duration_s) * int(fps))))
    refined_frames = 0
    pe = ne = None
    if refine_active:
        pe = iv._encode_prompt(pipes, refine_prompt or "cinematic")
        ne = iv._encode_prompt(pipes, refine_negative or "")

    for fi in range(total):
        if cancel_check_fn:
            cancel_check_fn()
        t = fi / float(max(1, fps))
        frame = compose_layered_frame(layers, width, height, t=t, fps=fps, motion_bundle=bundle)
        if refine_active:
            try:
                fseed = iv._stable_seed_int("layer_refine", refine_seed, fi)
                frame = iv._generate_img2img(
                    pipes,
                    init_image=frame.convert("RGB"),
                    prompt_embeds=pe,
                    negative_embeds=ne,
                    width=width,
                    height=height,
                    steps=int(refine_steps),
                    cfg=float(refine_cfg),
                    seed=fseed,
                    strength=max(0.05, min(0.95, float(refine_denoise))),
                ).convert("RGB")
                refined_frames += 1
            except Exception as exc:  # pragma: no cover - depends on runtime model
                if log_fn:
                    log_fn(f"Refine failed on frame {fi} ({exc}); using composite")
        frame.save(frames_dir / f"frame_{fi:06d}.png")
        if progress_fn and (fi % max(1, total // 20 or 1) == 0):
            progress_fn("frames", fi + 1, total, f"{'Refined' if refine_active else 'Composited'} frame {fi + 1}/{total}")
        if log_fn and fi % max(1, fps * 2) == 0:
            log_fn(f"Layer-animation frame {fi + 1}/{total} ({method})")

    out_mp4 = out_dir / f"{(mode or 'layered').lower()}_animation.mp4"
    assemble_image_sequence(
        ffmpeg_path=ffmpeg_path,
        frames_dir=frames_dir,
        out_mp4=out_mp4,
        fps=int(fps),
        glob_pattern="frame_*.png",
        audio_path=audio_path,
    )
    return {
        "ok": True,
        "video": str(out_mp4),
        "frames": total,
        "layers": [lyr.name for lyr in layers],
        "segmentation": method,
        "mode": mode,
        "diffusion_refined": refine_active,
        "refined_frames": refined_frames,
    }
