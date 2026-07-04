
from __future__ import annotations

import hashlib
import gc
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import UserFacingError
from .deforum_motion import DeforumMotionScheduleBundle, evaluate_motion_state
from .deforum_normalize import (
    DEFAULT_RENDER_PROMPT,
    UnifiedDeforumRenderContext,
    build_deforum_render_context,
    render_prompt_from_scene,
)
from .deforum_prompt_timeline import resolve_prompt_frame
from .deforum_schedule import coerce_schedule_pairs, evaluate_schedule
from .model_weights import diffusers_weight_load_kwargs

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageOps = None  # type: ignore

from .compositor import apply_timeline_layers
from .ffmpeg import assemble_image_sequence, interpolate_video_fps, mux_audio
from .internal_video_models import generate_video_model_frames


@dataclass(frozen=True)
class InternalVideoSettings:
    fps_render: int = 2
    fps_output: int = 24
    width: int = 768
    height: int = 432

    steps: int = 15
    cfg: float = 7.0
    sampler: str = "euler"
    seed: int | None = None
    keyframe_interval_s: float = 5.0

    interpolation_engine: str = "auto"  # auto|minterpolate|fps|rife
    negative_prompt: str = "blurry, low quality, watermark, text, logo"
    model_id: str = "hf_sd15_internal"
    loras: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    vae: str | None = None
    hires_fix: dict[str, Any] | None = None
    refiner: dict[str, Any] | None = None
    upscaler: str | None = None
    render_tier: str = "auto"
    device_preference: str = "auto"

    # Temporal consistency
    temporal_mode: str = "frame_img2img"  # off|keyframes|frame_img2img|video_model
    temporal_strength: float = 0.35
    temporal_steps: int | None = None
    refine_every_n_frames: int = 1
    anchor_strength: float = 0.20
    prompt_blend: bool = True
    resume_existing_frames: bool = True
    motion_strategy: str = "manual"  # manual|storyboard_full_motion
    storyboard_shot_max_s: float = 4.0
    deforum_overrides: dict[str, Any] | None = None
    # Internal video-model adapter. SVD is image-to-video from generated
    # keyframes; AnimateDiff is text-to-video through a Diffusers motion adapter.
    video_model_engine: str = "auto"  # auto|svd|animatediff
    video_model_id: str | None = None
    video_model_path: str | None = None
    video_model_max_frames_per_scene: int = 25
    video_model_motion_bucket_id: int = 127
    video_model_noise_aug_strength: float = 0.02
    video_model_decode_chunk_size: int = 8
    video_model_dtype: str = "auto"
    video_model_cpu_offload: bool = False
    video_model_motion_score_mode: str = "auto"  # auto|manual|off
    video_model_manual_motion_score: int = 4
    video_model_anchor_mode: str = "start"  # start|end|loop
    video_model_prompt_refine: bool = True
    video_model_scene_motion: str = "subject"  # camera|subject|scene
    video_model_keyframe_renderer: str = "internal"  # internal|tensorrt_sd15
    video_model_keyframe_model_id: str | None = None
    # Image animation: an uploaded still used to seed the first keyframe (img2img).
    source_asset: str | None = None
    source_strength: float = 0.55

    # Proxy renderer (CPU, no diffusion) visual expansion. These only affect the
    # local draft/proxy path and keep it fully GPU-free.
    proxy_motion: bool = True   # Ken-Burns zoom/pan from camera keyframes + scene energy
    proxy_finish: bool = True   # vignette + film-grain finishing pass


def normalize_internal_motion_strategy(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"storyboard", "storyboard_full_motion", "full_motion_storyboard", "auto_storyboard"}:
        return "storyboard_full_motion"
    return "manual"


def normalize_video_model_keyframe_renderer(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"trt", "tensorrt", "tensorrt_sd15", "sd15_tensorrt", "trt_sd15"}:
        return "tensorrt_sd15"
    return "internal"


def normalize_video_model_scene_motion(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"camera", "camera_only", "atmosphere", "ambient"}:
        return "camera"
    if raw in {"scene", "whole_scene", "full_scene", "objects", "object_motion", "living_scene"}:
        return "scene"
    return "subject"


class _PipelineCache:
    _cache: dict[tuple[str, str, str], Any] = {}

    @classmethod
    def get(cls, key: tuple[str, str, str]) -> Any | None:
        return cls._cache.get(key)

    @classmethod
    def set(cls, key: tuple[str, str, str], value: Any) -> None:
        cls._cache[key] = value

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()


class _EmbedCache:
    _cache: dict[tuple[str, str], Any] = {}

    @classmethod
    def get(cls, key: tuple[str, str]) -> Any | None:
        return cls._cache.get(key)

    @classmethod
    def set(cls, key: tuple[str, str], value: Any) -> None:
        cls._cache[key] = value

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()


class _ControlNetCache:
    _cache: dict[tuple[str, str, str], Any] = {}

    @classmethod
    def get(cls, key: tuple[str, str, str]) -> Any | None:
        return cls._cache.get(key)

    @classmethod
    def set(cls, key: tuple[str, str, str], value: Any) -> None:
        cls._cache[key] = value

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()


_STILL_PIPELINE_LOCK = threading.Lock()


def _cuda_total_vram_gb(device: str) -> float:
    if str(device or "").lower() != "cuda":
        return 0.0
    try:
        import torch  # type: ignore

        if not (getattr(torch, "cuda", None) and torch.cuda.is_available()):
            return 0.0
        props = torch.cuda.get_device_properties(0)
        return round(float(getattr(props, "total_memory", 0.0)) / float(1024 ** 3), 2)
    except Exception:
        return 0.0


def _cleanup_torch_cuda(device: str) -> None:
    gc.collect()
    if str(device or "").lower() != "cuda":
        return
    try:
        import torch  # type: ignore

        if getattr(torch, "cuda", None) and torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


def _release_still_pipeline_memory(pipes: _Pipes | None, device: str, *, log_fn=None) -> None:
    for pipe in (
        getattr(pipes, "txt2img", None),
        getattr(pipes, "img2img", None),
        getattr(pipes, "inpaint", None),
    ):
        if hasattr(pipe, "to"):
            try:
                pipe.to("cpu")
            except Exception:
                pass
    _PipelineCache.clear()
    _EmbedCache.clear()
    _ControlNetCache.clear()
    _cleanup_torch_cuda(device)
    if log_fn:
        log_fn("Released still-image diffusion pipelines before loading the internal video model.")


def _fit_multiple_of_8(width: int, height: int, *, max_width: int, max_height: int) -> tuple[int, int]:
    width_i = max(64, int(width))
    height_i = max(64, int(height))
    scale = min(1.0, float(max_width) / float(width_i), float(max_height) / float(height_i))
    out_w = max(64, int(math.floor((width_i * scale) / 8.0) * 8))
    out_h = max(64, int(math.floor((height_i * scale) / 8.0) * 8))
    return out_w, out_h


def _video_model_adapter_canvas(
    *,
    engine: str,
    width: int,
    height: int,
    device: str,
    cpu_offload: bool,
) -> tuple[int, int, str | None]:
    engine_l = str(engine or "").lower()
    if engine_l not in {"animatediff", "svd"} or str(device or "").lower() != "cuda":
        return int(width), int(height), None
    vram_gb = _cuda_total_vram_gb(device)
    if vram_gb <= 0.0:
        return int(width), int(height), None
    if vram_gb <= 6.5:
        max_w, max_h = (576, 320) if engine_l == "svd" else (640, 384)
        adapter_w, adapter_h = _fit_multiple_of_8(int(width), int(height), max_width=max_w, max_height=max_h)
        if (adapter_w, adapter_h) != (int(width), int(height)):
            label = "SVD" if engine_l == "svd" else "AnimateDiff"
            return adapter_w, adapter_h, f"6 GB CUDA {label} canvas capped to {adapter_w}x{adapter_h}"
    elif vram_gb <= 8.5 and not bool(cpu_offload):
        max_w, max_h = (640, 360) if engine_l == "svd" else (704, 448)
        adapter_w, adapter_h = _fit_multiple_of_8(int(width), int(height), max_width=max_w, max_height=max_h)
        if (adapter_w, adapter_h) != (int(width), int(height)):
            label = "SVD" if engine_l == "svd" else "AnimateDiff"
            return adapter_w, adapter_h, f"8 GB CUDA {label} canvas capped to {adapter_w}x{adapter_h}"
    return int(width), int(height), None


def _stable_seed_int(*parts: Any, fallback: int = 0) -> int:
    raw = "|".join(str(part) for part in parts if part is not None)
    if not raw:
        return int(fallback)
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return int(digest, 16)



def _json_digest(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = repr(value)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _timeline_render_fingerprint(timeline: dict[str, Any] | None) -> Any:
    if not isinstance(timeline, dict):
        return None
    cleaned: dict[str, Any] = {}
    for k, v in timeline.items():
        if k in {"trash_layers", "trash_clips", "history", "future", "selection"}:
            continue
        cleaned[k] = v
    return cleaned


def _build_proxy_work_tag(
    *,
    variant_index: int,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    settings: "InternalVideoSettings",
) -> str:
    payload = {
        "variant_index": int(variant_index),
        "fps_render": int(settings.fps_render),
        "fps_output": int(settings.fps_output),
        "width": int(settings.width),
        "height": int(settings.height),
        "keyframe_interval_s": float(settings.keyframe_interval_s),
        "interpolation_engine": str(settings.interpolation_engine),
        "render_tier": str(settings.render_tier),
        "device_preference": str(settings.device_preference),
        "proxy_motion": bool(settings.proxy_motion),
        "proxy_finish": bool(settings.proxy_finish),
        "scene_digest": _json_digest(scenes or []),
        "timeline_digest": _json_digest(_timeline_render_fingerprint(timeline)),
        "mode": "proxy",
    }
    raw = repr(sorted(payload.items())).encode("utf-8", errors="ignore")
    sig = hashlib.sha1(raw).hexdigest()[:10]
    return (
        f"proxy_v{int(variant_index):02d}_"
        f"{int(settings.width)}x{int(settings.height)}_{int(settings.fps_render)}rf_{int(settings.fps_output)}of_{sig}"
    )


def describe_proxy_render_cache(
    *,
    project_dir: Path,
    variant_index: int,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    settings: "InternalVideoSettings",
    total_frames: int,
) -> dict[str, Any]:
    work_tag = _build_proxy_work_tag(
        variant_index=variant_index,
        scenes=scenes,
        timeline=timeline,
        settings=settings,
    )
    out_frames = project_dir / "outputs" / "frames_proxy" / work_tag
    raw_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_raw.mp4"
    interp_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_interp.mp4"
    final_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}.mp4"
    meta_json = project_dir / "outputs" / "videos" / f"{work_tag}.render.json"
    frame_count = 0
    if out_frames.exists():
        try:
            frame_count = len(list(out_frames.glob("frame_*.png")))
        except Exception:
            frame_count = 0
    return {
        "work_tag": work_tag,
        "frames_dir": str(out_frames),
        "render_meta_path": str(meta_json),
        "raw_mp4": str(raw_mp4),
        "interp_mp4": str(interp_mp4),
        "final_mp4": str(final_mp4),
        "frames_present": frame_count,
        "frames_expected": int(total_frames),
        "frames_complete": bool(frame_count >= int(total_frames)),
        "raw_exists": raw_mp4.exists(),
        "interp_exists": interp_mp4.exists(),
        "final_exists": final_mp4.exists(),
        "render_meta_exists": meta_json.exists(),
    }


def _build_work_tag(
    *,
    variant_index: int,
    variant: dict[str, Any] | None,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    model_dir: Path,
    settings: "InternalVideoSettings",
) -> str:
    render_sig = _render_signature(
        variant_index=variant_index,
        model_dir=model_dir,
        settings=settings,
        variant=variant,
        scenes=scenes,
        timeline=timeline,
    )
    return (
        f"internal_v{int(variant_index):02d}_"
        f"{int(settings.width)}x{int(settings.height)}_{int(settings.fps_render)}rf_{int(settings.fps_output)}of_{render_sig}"
    )


def describe_internal_render_cache(
    *,
    project_dir: Path,
    variant_index: int,
    variant: dict[str, Any] | None,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    model_dir: Path,
    settings: "InternalVideoSettings",
    total_frames: int,
) -> dict[str, Any]:
    work_tag = _build_work_tag(
        variant_index=variant_index,
        variant=variant,
        scenes=scenes,
        timeline=timeline,
        model_dir=model_dir,
        settings=settings,
    )
    out_frames = project_dir / "outputs" / "frames_internal" / work_tag
    raw_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_raw.mp4"
    interp_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_interp.mp4"
    final_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}.mp4"
    meta_json = project_dir / "outputs" / "videos" / f"{work_tag}.render.json"
    frame_count = 0
    if out_frames.exists():
        try:
            frame_count = len(list(out_frames.glob("frame_*.png")))
        except Exception:
            frame_count = 0
    return {
        "work_tag": work_tag,
        "frames_dir": str(out_frames),
        "render_meta_path": str(meta_json),
        "raw_mp4": str(raw_mp4),
        "interp_mp4": str(interp_mp4),
        "final_mp4": str(final_mp4),
        "frames_present": frame_count,
        "frames_expected": int(total_frames),
        "frames_complete": bool(frame_count >= int(total_frames)),
        "raw_exists": raw_mp4.exists(),
        "interp_exists": interp_mp4.exists(),
        "final_exists": final_mp4.exists(),
        "render_meta_exists": meta_json.exists(),
    }


def _render_signature(
    *,
    variant_index: int,
    model_dir: Path,
    settings: "InternalVideoSettings",
    variant: dict[str, Any] | None = None,
    scenes: list[dict[str, Any]] | None = None,
    timeline: dict[str, Any] | None = None,
) -> str:
    payload = {
        "variant_index": int(variant_index),
        "model_dir": str(model_dir),
        "fps_render": int(settings.fps_render),
        "fps_output": int(settings.fps_output),
        "width": int(settings.width),
        "height": int(settings.height),
        "steps": int(settings.steps),
        "cfg": float(settings.cfg),
        "sampler": str(settings.sampler),
        "seed": settings.seed,
        "keyframe_interval_s": float(settings.keyframe_interval_s),
        "interpolation_engine": str(settings.interpolation_engine),
        "model_id": str(settings.model_id),
        "loras_digest": _json_digest(list(settings.loras)),
        "vae": str(settings.vae or ""),
        "hires_fix": settings.hires_fix or None,
        "refiner": settings.refiner or None,
        "upscaler": str(settings.upscaler or ""),
        "render_tier": str(settings.render_tier),
        "device_preference": str(settings.device_preference),
        "temporal_mode": str(settings.temporal_mode),
        "temporal_strength": float(settings.temporal_strength),
        "temporal_steps": int(settings.temporal_steps or 0),
        "refine_every_n_frames": int(settings.refine_every_n_frames),
        "anchor_strength": float(settings.anchor_strength),
        "prompt_blend": bool(settings.prompt_blend),
        "motion_strategy": normalize_internal_motion_strategy(settings.motion_strategy),
        "storyboard_shot_max_s": float(_storyboard_shot_max_s(settings)),
        "video_model_engine": str(settings.video_model_engine),
        "video_model_id": str(settings.video_model_id or ""),
        "video_model_path": str(settings.video_model_path or ""),
        "video_model_max_frames_per_scene": int(settings.video_model_max_frames_per_scene),
        "video_model_motion_bucket_id": int(settings.video_model_motion_bucket_id),
        "video_model_noise_aug_strength": float(settings.video_model_noise_aug_strength),
        "video_model_decode_chunk_size": int(settings.video_model_decode_chunk_size),
        "video_model_dtype": str(settings.video_model_dtype),
        "video_model_cpu_offload": bool(settings.video_model_cpu_offload),
        "video_model_motion_score_mode": str(settings.video_model_motion_score_mode),
        "video_model_manual_motion_score": int(settings.video_model_manual_motion_score),
        "video_model_anchor_mode": str(settings.video_model_anchor_mode),
        "video_model_prompt_refine": bool(settings.video_model_prompt_refine),
        "video_model_scene_motion": normalize_video_model_scene_motion(settings.video_model_scene_motion),
        "video_model_keyframe_renderer": normalize_video_model_keyframe_renderer(settings.video_model_keyframe_renderer),
        "video_model_keyframe_model_id": str(settings.video_model_keyframe_model_id or ""),
        "source_asset": str(settings.source_asset or ""),
        "source_strength": float(settings.source_strength),
        "deforum_overrides": settings.deforum_overrides or None,
        "variant_motion_digest": _json_digest((variant or {}).get("motion_schedules") if isinstance(variant, dict) else None),
        "variant_prompt_digest": _json_digest((variant or {}).get("prompts") if isinstance(variant, dict) else None),
        "scenes_digest": _json_digest(scenes or []),
        "timeline_digest": _json_digest(_timeline_render_fingerprint(timeline)),
    }
    raw = repr(sorted(payload.items())).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:10]


def _frame_path(frames_dir: Path, fi: int) -> Path:
    return frames_dir / f"frame_{fi:06d}.png"


def _require_pillow() -> None:
    if Image is None:
        raise UserFacingError(
            "Pillow is not installed",
            hint="Install backend deps including Pillow, then retry.",
            code="INTERNAL_DEPS",
            status_code=500,
        )


@dataclass
class _Pipes:
    txt2img: Any
    img2img: Any
    device: str
    inpaint: Any | None = None
    family: str = "sd15"
    backend: str = "diffusers"


def _model_family_from_dir(model_dir: Path) -> str:
    family = "sd15"
    mi = model_dir / "model_index.json"
    if mi.exists():
        try:
            j = json.loads(mi.read_text(encoding="utf-8"))
            cls = str(j.get("_class_name") or "")
            if "StableDiffusion3" in cls:
                family = "sd3"
            elif ("XL" in cls) or ("XLPipeline" in cls):
                family = "sdxl"
        except Exception:
            family = "sd15"
    return family


def _diffusers_from_pretrained_kwargs(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prefer safetensors weights; bucket/local snapshots rarely ship legacy .bin files."""
    kwargs: dict[str, Any] = {"use_safetensors": True}
    if extra:
        kwargs.update(extra)
    return kwargs


def _diffusers_model_load_kwargs(model_dir: Path, device: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    kwargs = _diffusers_from_pretrained_kwargs(extra=extra)
    kwargs.update(diffusers_weight_load_kwargs(model_dir, device))
    return kwargs


def _reraise_snapshot_load_error(exc: Exception, model_dir: Path) -> None:
    message = str(exc).lower()
    if "git-lfs" in message or "git lfs" in message:
        raise UserFacingError(
            "Internal diffusion model snapshot contains Git LFS pointer files",
            hint=(
                f"The Diffusers snapshot at {model_dir} has placeholder weight files instead of full model weights. "
                "Reinstall the model in Models or run git lfs pull/re-sync for that snapshot, then retry."
            ),
            code="MODEL_SNAPSHOT_LFS_POINTER",
            status_code=400,
        ) from exc
    if any(
        token in message
        for token in ("no file named", "does not appear to have", "safetensors", "not found in directory")
    ):
        raise UserFacingError(
            "Internal diffusion model failed to load",
            hint=(
                f"The Diffusers snapshot at {model_dir} is incomplete or missing weight files. "
                "Reinstall the model in Models or re-sync from the Hugging Face bucket, then retry."
            ),
            code="MODEL_SNAPSHOT_LOAD_FAILED",
            status_code=400,
        ) from exc
    raise exc


def _try_load_diffusers(model_dir: Path, device: str, *, role: str = "video") -> _Pipes:
    try:
        import json
        import torch  # type: ignore
        from diffusers import (  # type: ignore
            StableDiffusion3InpaintPipeline,
            StableDiffusion3Img2ImgPipeline,
            StableDiffusion3Pipeline,
            StableDiffusionInpaintPipeline,
            StableDiffusionImg2ImgPipeline,
            StableDiffusionPipeline,
            StableDiffusionXLInpaintPipeline,
            StableDiffusionXLImg2ImgPipeline,
            StableDiffusionXLPipeline,
        )
    except Exception as e:
        raise UserFacingError(
            "Internal diffusion engine is not installed",
            hint="Install internal deps (diffusers + torch). Then download the internal SD model in Models.",
            code="INTERNAL_DEPS",
            status_code=500,
        ) from e

    cache_key = (str(model_dir), device, str(role or "video"))
    cached = _PipelineCache.get(cache_key)
    if cached is not None:
        return cached

    # TF32 / cuDNN benchmark flags are set at app startup by _apply_cuda_startup_flags()
    # in app.py, so we don't need to re-apply them here on every pipeline load.
    family = _model_family_from_dir(model_dir)

    torch_dtype = torch.float16 if device in ("cuda", "rocm") else torch.float32

    if family == "sd3":
        txt = StableDiffusion3Pipeline.from_pretrained(
            str(model_dir),
            **_diffusers_model_load_kwargs(model_dir, device, extra={"torch_dtype": torch_dtype}),
        )
        if hasattr(txt, "enable_attention_slicing"):
            txt.enable_attention_slicing()
        if device == "cuda" and hasattr(txt, "enable_xformers_memory_efficient_attention"):
            try:
                txt.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        txt = txt.to(device)

        img = StableDiffusion3Img2ImgPipeline(**txt.components)
        if hasattr(img, "enable_attention_slicing"):
            img.enable_attention_slicing()
        if device == "cuda" and hasattr(img, "enable_xformers_memory_efficient_attention"):
            try:
                img.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        img = img.to(device)

        inpaint = StableDiffusion3InpaintPipeline(**txt.components)
        if hasattr(inpaint, "enable_attention_slicing"):
            inpaint.enable_attention_slicing()
        if device == "cuda" and hasattr(inpaint, "enable_xformers_memory_efficient_attention"):
            try:
                inpaint.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        inpaint = inpaint.to(device)

        pipes = _Pipes(txt2img=txt, img2img=img, inpaint=inpaint, device=device, family="sd3", backend="diffusers")
    elif family == "sdxl":
        txt = StableDiffusionXLPipeline.from_pretrained(
            str(model_dir),
            **_diffusers_model_load_kwargs(
                model_dir,
                device,
                extra={
                    "torch_dtype": torch_dtype,
                    "safety_checker": None,
                    "requires_safety_checker": False,
                }
            ),
        )
        if hasattr(txt, "enable_attention_slicing"):
            txt.enable_attention_slicing()
        if device == "cuda" and hasattr(txt, "enable_xformers_memory_efficient_attention"):
            try:
                txt.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        txt = txt.to(device)

        img = StableDiffusionXLImg2ImgPipeline(**txt.components)
        if hasattr(img, "enable_attention_slicing"):
            img.enable_attention_slicing()
        if device == "cuda" and hasattr(img, "enable_xformers_memory_efficient_attention"):
            try:
                img.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        img = img.to(device)

        inpaint = StableDiffusionXLInpaintPipeline(**txt.components)
        if hasattr(inpaint, "enable_attention_slicing"):
            inpaint.enable_attention_slicing()
        if device == "cuda" and hasattr(inpaint, "enable_xformers_memory_efficient_attention"):
            try:
                inpaint.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        inpaint = inpaint.to(device)

        pipes = _Pipes(txt2img=txt, img2img=img, inpaint=inpaint, device=device, family="sdxl", backend="diffusers")
    else:
        txt = StableDiffusionPipeline.from_pretrained(
            str(model_dir),
            **_diffusers_model_load_kwargs(
                model_dir,
                device,
                extra={
                    "torch_dtype": torch_dtype,
                    "safety_checker": None,
                    "requires_safety_checker": False,
                }
            ),
        )
        if hasattr(txt, "enable_attention_slicing"):
            txt.enable_attention_slicing()
        if device == "cuda" and hasattr(txt, "enable_xformers_memory_efficient_attention"):
            try:
                txt.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        txt = txt.to(device)

        img = StableDiffusionImg2ImgPipeline(**txt.components)
        if hasattr(img, "enable_attention_slicing"):
            img.enable_attention_slicing()
        if device == "cuda" and hasattr(img, "enable_xformers_memory_efficient_attention"):
            try:
                img.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        img = img.to(device)

        inpaint = StableDiffusionInpaintPipeline(**txt.components)
        if hasattr(inpaint, "enable_attention_slicing"):
            inpaint.enable_attention_slicing()
        if device == "cuda" and hasattr(inpaint, "enable_xformers_memory_efficient_attention"):
            try:
                inpaint.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        inpaint = inpaint.to(device)

        pipes = _Pipes(txt2img=txt, img2img=img, inpaint=inpaint, device=device, family="sd15", backend="diffusers")

    _PipelineCache.set(cache_key, pipes)
    return pipes


def _try_load_directml(model_dir: Path, *, role: str = "video") -> _Pipes:
    family = _model_family_from_dir(model_dir)
    if family not in {"sd15", "sdxl"}:
        raise UserFacingError(
            "DirectML acceleration currently supports SD 1.5 and SDXL only.",
            hint="Use SDXL or SD 1.5 for AMD / DirectML renders, or switch device preference to CPU for SD3.5.",
            code="DIRECTML_MODEL_UNSUPPORTED",
            status_code=400,
        )

    try:
        import onnxruntime as ort  # type: ignore
        from optimum.onnxruntime import (  # type: ignore
            ORTStableDiffusionImg2ImgPipeline,
            ORTStableDiffusionPipeline,
            ORTStableDiffusionXLImg2ImgPipeline,
            ORTStableDiffusionXLPipeline,
        )
    except Exception as e:
        raise UserFacingError(
            "DirectML runtime is not installed.",
            hint="Open Setup and install the AMD / DirectML backend runtime, then retry.",
            code="DIRECTML_DEPS",
            status_code=500,
        ) from e

    providers = list(ort.get_available_providers() or [])
    if "DmlExecutionProvider" not in providers:
        raise UserFacingError(
            "DirectML execution provider is unavailable in this backend environment.",
            hint="Reinstall the AMD / DirectML backend runtime from Setup, then retry.",
            code="DIRECTML_UNAVAILABLE",
            status_code=500,
        )

    cache_key = (str(model_dir), "directml", str(role or "video"))
    cached = _PipelineCache.get(cache_key)
    if cached is not None:
        return cached

    common_kwargs = {
        "export": True,
        "provider": "DmlExecutionProvider",
    }
    if family == "sdxl":
        txt = ORTStableDiffusionXLPipeline.from_pretrained(str(model_dir), **common_kwargs)
        img = ORTStableDiffusionXLImg2ImgPipeline.from_pretrained(str(model_dir), **common_kwargs)
        pipes = _Pipes(txt2img=txt, img2img=img, inpaint=None, device="directml", family="sdxl", backend="directml")
    else:
        txt = ORTStableDiffusionPipeline.from_pretrained(str(model_dir), **common_kwargs)
        img = ORTStableDiffusionImg2ImgPipeline.from_pretrained(str(model_dir), **common_kwargs)
        pipes = _Pipes(txt2img=txt, img2img=img, inpaint=None, device="directml", family="sd15", backend="directml")

    _PipelineCache.set(cache_key, pipes)
    return pipes


def _try_load_pipelines(model_dir: Path, device: str, *, role: str = "video") -> _Pipes:
    try:
        if device == "directml":
            return _try_load_directml(model_dir, role=role)
        return _try_load_diffusers(model_dir, device=device, role=role)
    except UserFacingError:
        raise
    except Exception as exc:
        _reraise_snapshot_load_error(exc, model_dir)


def _device_auto(preference: str = "auto") -> str:
    pref = str(preference or "auto").strip().lower()
    try:
        import torch  # type: ignore
    except Exception:
        torch = None  # type: ignore

    def _cuda_ok() -> bool:
        try:
            return bool(torch is not None and getattr(torch, "cuda", None) is not None and torch.cuda.is_available())
        except Exception:
            return False

    def _mps_ok() -> bool:
        try:
            backends = getattr(torch, "backends", None)
            mps = getattr(backends, "mps", None)
            return bool(mps is not None and mps.is_available())
        except Exception:
            return False

    def _directml_ok() -> bool:
        if pref != "directml" and pref != "auto" and pref not in {"cuda", "mps", "cpu"}:
            return False
        try:
            import onnxruntime as ort  # type: ignore

            return "DmlExecutionProvider" in list(ort.get_available_providers() or [])
        except Exception:
            return False

    if pref == "cuda" and _cuda_ok():
        return "cuda"
    if pref == "mps" and _mps_ok():
        return "mps"
    if pref == "directml" and _directml_ok():
        return "directml"
    if pref == "cpu":
        return "cpu"
    if _cuda_ok():
        return "cuda"
    if _mps_ok():
        return "mps"
    if _directml_ok():
        return "directml"
    return "cpu"


def _encode_prompt(pipes: _Pipes, prompt: str) -> Any:
    """Return an encoded prompt representation.

    SD1.5 path: returns text-encoder embeddings (fast + blendable).
    SDXL / SD3 path: returns the prompt string (we rely on pipeline internal encoding).
    """
    prompt = str(prompt or "").strip() or "cinematic"
    if pipes.family != "sd15" or pipes.backend == "directml":
        # Keep it simple & robust for SDXL: use native pipeline encoding.
        return prompt

    import torch  # type: ignore

    key = (pipes.device, prompt)
    cached = _EmbedCache.get(key)
    if cached is not None:
        return cached

    tokenizer = pipes.txt2img.tokenizer
    text_encoder = pipes.txt2img.text_encoder

    inputs = tokenizer(
        prompt,
        padding="max_length",
        max_length=tokenizer.model_max_length,
        truncation=True,
        return_tensors="pt",
    )
    ids = inputs.input_ids.to(pipes.device)
    with torch.no_grad():
        embeds = text_encoder(ids)[0]
    _EmbedCache.set(key, embeds)
    return embeds


def _blend_embeds(a: Any, b: Any, w: float) -> Any:
    import torch  # type: ignore

    w = float(max(0.0, min(1.0, w)))
    if isinstance(a, str) or isinstance(b, str):
        # SDXL path: we can't blend embeddings safely here; pick a side deterministically.
        return str(b) if w >= 0.5 else str(a)
    return a * (1.0 - w) + b * w


def _ken_burns_frame(
    img: "Image.Image",
    out_w: int,
    out_h: int,
    zoom: float,
    pan_x: float,
    pan_y: float,
    rotation_deg: float = 0.0,
) -> "Image.Image":
    w, h = img.size

    if abs(rotation_deg) > 0.01:
        _fill = (0, 0, 0, 0) if img.mode == "RGBA" else None
        img = img.rotate(float(rotation_deg), resample=Image.BICUBIC, expand=True, fillcolor=_fill)
        w, h = img.size

    zw, zh = int(round(w * zoom)), int(round(h * zoom))
    imz = img.resize((max(1, zw), max(1, zh)), resample=Image.BICUBIC)

    cx, cy = imz.width // 2, imz.height // 2
    x0 = int(round(cx - out_w / 2 + pan_x))
    y0 = int(round(cy - out_h / 2 + pan_y))
    x0 = max(0, min(x0, imz.width - out_w))
    y0 = max(0, min(y0, imz.height - out_h))
    return imz.crop((x0, y0, x0 + out_w, y0 + out_h))


def _perspective_coeffs(
    dst_pts: list[tuple[float, float]],
    src_pts: list[tuple[float, float]],
) -> tuple[float, ...]:
    """Solve the 8 perspective coefficients for ``Image.transform(PERSPECTIVE)``.

    ``dst_pts`` are output-image corner positions, ``src_pts`` the matching
    source-image corners. PIL maps each output point back into the source using
    the returned coefficients.
    """
    import numpy as np  # type: ignore

    matrix = []
    for (dx, dy), (sx, sy) in zip(dst_pts, src_pts, strict=False):
        matrix.append([dx, dy, 1.0, 0.0, 0.0, 0.0, -sx * dx, -sx * dy])
        matrix.append([0.0, 0.0, 0.0, dx, dy, 1.0, -sy * dx, -sy * dy])
    a = np.array(matrix, dtype=np.float64)
    b = np.array([coord for point in src_pts for coord in point], dtype=np.float64)
    solution = np.linalg.solve(a, b)
    return tuple(float(v) for v in solution)


def _project_image_corners(
    w: int,
    h: int,
    *,
    rot_x_deg: float,
    rot_y_deg: float,
    rot_z_deg: float,
    translation_x: float,
    translation_y: float,
    translation_z: float,
    fov_deg: float,
) -> list[tuple[float, float]]:
    """Project the image-plane corners through a simple pinhole camera.

    Returns the four destination corner positions (top-left, top-right,
    bottom-right, bottom-left) after applying 3D rotations (pitch/yaw/roll),
    translation, and a dolly along Z. With neutral parameters the corners map
    back to the original rectangle, so the transform reduces to identity.
    """
    fov = max(10.0, min(179.0, float(fov_deg or 70.0)))
    focal = (0.5 * float(w)) / math.tan(math.radians(fov) / 2.0)
    half_w, half_h = float(w) / 2.0, float(h) / 2.0
    corners = [
        (-half_w, -half_h, 0.0),
        (half_w, -half_h, 0.0),
        (half_w, half_h, 0.0),
        (-half_w, half_h, 0.0),
    ]

    rx, ry, rz = (math.radians(rot_x_deg), math.radians(rot_y_deg), math.radians(rot_z_deg))
    cos_x, sin_x = math.cos(rx), math.sin(rx)
    cos_y, sin_y = math.cos(ry), math.sin(ry)
    cos_z, sin_z = math.cos(rz), math.sin(rz)

    def _rotate(x: float, y: float, z: float) -> tuple[float, float, float]:
        # pitch (X axis)
        y1 = y * cos_x - z * sin_x
        z1 = y * sin_x + z * cos_x
        x1 = x
        # yaw (Y axis)
        x2 = x1 * cos_y + z1 * sin_y
        z2 = -x1 * sin_y + z1 * cos_y
        y2 = y1
        # roll (Z axis)
        x3 = x2 * cos_z - y2 * sin_z
        y3 = x2 * sin_z + y2 * cos_z
        return x3, y3, z2

    distance = focal
    min_depth = 0.1 * focal
    out: list[tuple[float, float]] = []
    for cx, cy, cz in corners:
        rxp, ryp, rzp = _rotate(cx, cy, cz)
        xc = rxp + float(translation_x)
        yc = ryp + float(translation_y)
        zc = distance - float(translation_z) + rzp
        if zc < min_depth:
            zc = min_depth
        u = focal * xc / zc + half_w
        v = focal * yc / zc + half_h
        out.append((u, v))
    return out


def _apply_camera_3d(
    img: "Image.Image",
    out_w: int,
    out_h: int,
    *,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
    rotation_deg: float = 0.0,
    translation_z: float = 0.0,
    rotation_3d_x: float = 0.0,
    rotation_3d_y: float = 0.0,
    fov_deg: float = 70.0,
) -> "Image.Image":
    """Apply full (2D + 3D) camera motion to a frame.

    3D pitch/yaw/dolly are applied first as a perspective warp, then the
    existing 2D zoom/pan/roll crop runs on top. When no 3D component is active
    this is bit-identical to :func:`_ken_burns_frame`, preserving the legacy
    2D-only behavior.
    """
    has_3d = (
        abs(float(translation_z)) > 1e-4
        or abs(float(rotation_3d_x)) > 1e-4
        or abs(float(rotation_3d_y)) > 1e-4
    )
    if not has_3d:
        return _ken_burns_frame(
            img, out_w, out_h, zoom=zoom, pan_x=pan_x, pan_y=pan_y, rotation_deg=rotation_deg
        )

    w, h = img.size
    dst = _project_image_corners(
        w,
        h,
        rot_x_deg=float(rotation_3d_x),
        rot_y_deg=float(rotation_3d_y),
        rot_z_deg=0.0,
        translation_x=0.0,
        translation_y=0.0,
        translation_z=float(translation_z),
        fov_deg=float(fov_deg),
    )
    src = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    try:
        coeffs = _perspective_coeffs(dst, src)
        _fill = (0, 0, 0, 0) if img.mode == "RGBA" else None
        warped = img.transform(
            (w, h), Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC, fillcolor=_fill
        )
    except Exception:
        warped = img
    return _ken_burns_frame(
        warped, out_w, out_h, zoom=zoom, pan_x=pan_x, pan_y=pan_y, rotation_deg=rotation_deg
    )



def _generate_txt2img(
    pipes: _Pipes,
    prompt_embeds: Any,
    negative_embeds: Any,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
) -> "Image.Image":
    g = None
    if pipes.device != "directml":
        import torch  # type: ignore

        g = torch.Generator(device=pipes.device if pipes.device != "mps" else "cpu")
        g.manual_seed(int(seed))

    if pipes.family != "sd15" or pipes.backend == "directml" or isinstance(prompt_embeds, str):
        prompt = str(prompt_embeds or "").strip() or "cinematic"
        negative = str(negative_embeds or "").strip()
        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative,
            width=int(width),
            height=int(height),
            num_inference_steps=int(steps),
            guidance_scale=float(cfg),
        )
        if g is not None:
            kwargs["generator"] = g
        out = pipes.txt2img(**kwargs)
        return out.images[0]

    kwargs = dict(
        prompt=None,
        width=int(width),
        height=int(height),
        num_inference_steps=int(steps),
        guidance_scale=float(cfg),
        prompt_embeds=prompt_embeds,
        negative_prompt_embeds=negative_embeds,
    )
    if g is not None:
        kwargs["generator"] = g
    out = pipes.txt2img(**kwargs)
    return out.images[0]


def _generate_img2img(
    pipes: _Pipes,
    init_image: "Image.Image",
    prompt_embeds: Any,
    negative_embeds: Any,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
    strength: float,
) -> "Image.Image":
    g = None
    if pipes.device != "directml":
        import torch  # type: ignore

        g = torch.Generator(device=pipes.device if pipes.device != "mps" else "cpu")
        g.manual_seed(int(seed))

    if pipes.family != "sd15" or pipes.backend == "directml" or isinstance(prompt_embeds, str):
        prompt = str(prompt_embeds or "").strip() or "cinematic"
        negative = str(negative_embeds or "").strip()
        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative,
            image=init_image,
            strength=float(max(0.0, min(1.0, strength))),
            width=int(width),
            height=int(height),
            num_inference_steps=int(steps),
            guidance_scale=float(cfg),
        )
        if g is not None:
            kwargs["generator"] = g
        out = pipes.img2img(**kwargs)
        return out.images[0]

    kwargs = dict(
        prompt=None,
        image=init_image,
        strength=float(max(0.0, min(1.0, strength))),
        width=int(width),
        height=int(height),
        num_inference_steps=int(steps),
        guidance_scale=float(cfg),
        prompt_embeds=prompt_embeds,
        negative_prompt_embeds=negative_embeds,
    )
    if g is not None:
        kwargs["generator"] = g
    out = pipes.img2img(**kwargs)
    return out.images[0]


def _generate_tensorrt_sd15_keyframe(
    *,
    project_id: str | None,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    seed: int,
    model_id: str | None,
) -> "Image.Image":
    if not project_id:
        raise UserFacingError(
            "TensorRT keyframe anchors need a project id",
            hint="Use the Studio render endpoint so TensorRT anchors can write into the project runtime folder.",
            code="TRT_ANCHOR_PROJECT_MISSING",
            status_code=400,
        )
    if ImageOps is None:
        raise UserFacingError(
            "Pillow image operations are unavailable",
            hint="Install Pillow in the backend environment and retry.",
            code="PILLOW_UNAVAILABLE",
            status_code=500,
        )

    from . import tensorrt_standalone

    result = tensorrt_standalone.run_job(
        project_id,
        None,
        {
            "model_id": str(model_id or "local_sd15_tensorrt_bundle"),
            "workflow_family": "sd15",
            "prompt": str(prompt or "cinematic music video keyframe"),
            "negative_prompt": str(negative_prompt or "blurry, low quality, watermark, text, logo"),
            "steps": max(1, min(80, int(steps))),
            "cfg": float(cfg),
            "sampler": str(sampler or "pndm"),
            "seed": int(seed) & 0xFFFFFFFF,
            "batch_size": 1,
        },
    )
    src = Path(str(result.get("output_path") or ""))
    if not src.exists():
        raise RuntimeError("TensorRT SD1.5 keyframe render did not produce an image")
    image = Image.open(src).convert("RGB")
    if image.size != (int(width), int(height)):
        image = ImageOps.fit(image, (int(width), int(height)), method=Image.LANCZOS)
    return image


def _generate_inpaint(
    pipes: _Pipes,
    init_image: "Image.Image",
    mask_image: "Image.Image",
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
    strength: float,
) -> "Image.Image":
    if pipes.inpaint is None:
        raise UserFacingError(
            "Internal inpaint pipeline is unavailable for this model/backend.",
            hint="Use a supported internal diffusers model, or switch the still model to a Comfy checkpoint.",
            code="INTERNAL_INPAINT_UNAVAILABLE",
            status_code=400,
        )

    g = None
    if pipes.device != "directml":
        import torch  # type: ignore

        g = torch.Generator(device=pipes.device if pipes.device != "mps" else "cpu")
        g.manual_seed(int(seed))

    kwargs = dict(
        prompt=str(prompt or "").strip() or "cinematic",
        negative_prompt=str(negative_prompt or "").strip(),
        image=init_image,
        mask_image=mask_image,
        strength=float(max(0.0, min(1.0, strength))),
        width=int(width),
        height=int(height),
        num_inference_steps=int(steps),
        guidance_scale=float(cfg),
    )
    if g is not None:
        kwargs["generator"] = g
    out = pipes.inpaint(**kwargs)
    return out.images[0]


def _load_controlnet_model(model_dir: Path, family: str, device: str) -> Any:
    if family not in {"sd15", "sdxl"}:
        raise UserFacingError(
            "Internal ControlNet is only available for SD 1.5 and SDXL in this phase.",
            hint="Use an SD 1.5 or SDXL internal still model for ControlNet, or switch to a Comfy checkpoint.",
            code="INTERNAL_CONTROLNET_UNSUPPORTED",
            status_code=400,
        )

    cache_key = (str(model_dir), family, device)
    cached = _ControlNetCache.get(cache_key)
    if cached is not None:
        return cached

    try:
        import torch  # type: ignore
        from diffusers import ControlNetModel  # type: ignore
    except Exception as e:
        raise UserFacingError(
            "Internal ControlNet runtime is not installed.",
            hint="Install the internal diffusers runtime and retry.",
            code="INTERNAL_DEPS",
            status_code=500,
        ) from e

    torch_dtype = torch.float16 if device in ("cuda", "rocm") else torch.float32
    controlnet = ControlNetModel.from_pretrained(
        str(model_dir),
        **_diffusers_model_load_kwargs(model_dir, device, extra={"torch_dtype": torch_dtype}),
    )
    if device != "directml":
        controlnet = controlnet.to(device)
    _ControlNetCache.set(cache_key, controlnet)
    return controlnet


def _build_controlnet_pipeline(
    pipes: _Pipes,
    *,
    controlnet_dirs: list[Path],
) -> Any:
    if pipes.family not in {"sd15", "sdxl"}:
        raise UserFacingError(
            "Internal ControlNet is only available for SD 1.5 and SDXL in this phase.",
            hint="Use an SD 1.5 or SDXL internal still model for ControlNet, or switch to a Comfy checkpoint.",
            code="INTERNAL_CONTROLNET_UNSUPPORTED",
            status_code=400,
        )

    try:
        from diffusers import (  # type: ignore
            MultiControlNetModel,
            StableDiffusionControlNetPipeline,
            StableDiffusionXLControlNetPipeline,
        )
    except Exception as e:
        raise UserFacingError(
            "Internal ControlNet runtime is not installed.",
            hint="Install the internal diffusers runtime and retry.",
            code="INTERNAL_DEPS",
            status_code=500,
        ) from e

    models = [_load_controlnet_model(model_dir, pipes.family, pipes.device) for model_dir in controlnet_dirs]
    if not models:
        raise UserFacingError(
            "No internal ControlNet models were provided.",
            hint="Choose one or more compatible internal ControlNet units before retrying.",
            code="INTERNAL_CONTROLNET_MISSING",
            status_code=400,
        )
    controlnet = models[0] if len(models) == 1 else MultiControlNetModel(models)
    base_components = dict(getattr(pipes.txt2img, "components", {}) or {})
    base_components.pop("controlnet", None)
    if pipes.family == "sdxl":
        pipeline = StableDiffusionXLControlNetPipeline(controlnet=controlnet, **base_components)
    else:
        pipeline = StableDiffusionControlNetPipeline(controlnet=controlnet, **base_components)
    if hasattr(pipeline, "enable_attention_slicing"):
        pipeline.enable_attention_slicing()
    if pipes.device == "cuda" and hasattr(pipeline, "enable_xformers_memory_efficient_attention"):
        try:
            pipeline.enable_xformers_memory_efficient_attention()
        except Exception:
            pass
    if pipes.device != "directml":
        pipeline = pipeline.to(pipes.device)
    return pipeline


def _apply_loras(pipeline: Any, loras: tuple[dict[str, Any], ...]) -> list[str]:
    loaded: list[str] = []
    weights: list[float] = []
    if not loras or not hasattr(pipeline, "load_lora_weights"):
        return loaded
    for idx, item in enumerate(loras):
        lora_path = str(item.get("path") or item.get("filename") or item.get("name") or "").strip()
        if not lora_path:
            continue
        adapter_name = f"edmg_lora_{idx}"
        pipeline.load_lora_weights(lora_path, adapter_name=adapter_name)
        loaded.append(adapter_name)
        weights.append(float(item.get("weight", 1.0)))
    if loaded and hasattr(pipeline, "set_adapters"):
        try:
            pipeline.set_adapters(loaded, adapter_weights=weights)
        except TypeError:
            pipeline.set_adapters(loaded, weights)
    return loaded


def _clear_loras(pipeline: Any, adapter_names: list[str]) -> None:
    if not adapter_names:
        return
    try:
        if hasattr(pipeline, "delete_adapters"):
            pipeline.delete_adapters(adapter_names)
        elif hasattr(pipeline, "unload_lora_weights"):
            pipeline.unload_lora_weights()
    except Exception:
        pass


def _load_render_image(path: Path, *, mode: str, size: tuple[int, int] | None = None) -> "Image.Image":
    _require_pillow()
    with Image.open(path) as image:
        result = image.convert(mode)
        if size is not None and result.size != size:
            resample = Image.BICUBIC if mode != "L" else Image.BILINEAR
            result = result.resize(size, resample=resample)
        return result


def _fit_render_image(image: "Image.Image", *, size: tuple[int, int], mode: str) -> "Image.Image":
    if image.size == size:
        return image.copy()
    target_w, target_h = size
    resample = Image.BICUBIC if mode != "L" else Image.BILINEAR
    scale = max(target_w / max(1, image.width), target_h / max(1, image.height))
    resized = image.resize(
        (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
        resample=resample,
    )
    left = max(0, int(round((resized.width - target_w) / 2)))
    top = max(0, int(round((resized.height - target_h) / 2)))
    return resized.crop((left, top, left + target_w, top + target_h))


def _load_render_source_image(path: Path, *, size: tuple[int, int]) -> "Image.Image":
    _require_pillow()
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        return _fit_render_image(rgb, size=size, mode="RGB")


def _pil_upscale_resample(upscaler: str | None) -> int:
    raw = str(upscaler or "").strip().lower()
    if raw.startswith("latent_"):
        raw = raw[len("latent_") :]
    elif raw.startswith("pixel_"):
        raw = raw[len("pixel_") :]
    mapping = {
        "nearest": Image.NEAREST,
        "nearest-exact": Image.NEAREST,
        "nearest_exact": Image.NEAREST,
        "bilinear": Image.BILINEAR,
        "area": Image.BOX,
        "bicubic": Image.BICUBIC,
        "bislerp": Image.BICUBIC,
        "lanczos": Image.LANCZOS,
    }
    return mapping.get(raw, Image.LANCZOS)


def _upscale_render_image(image: "Image.Image", *, scale: float, upscaler: str | None) -> "Image.Image":
    normalized_scale = float(max(1.0, scale))
    target_size = (
        max(1, int(round(image.width * normalized_scale))),
        max(1, int(round(image.height * normalized_scale))),
    )
    if target_size == image.size:
        return image.copy()
    return image.resize(target_size, resample=_pil_upscale_resample(upscaler))


def _apply_hires_fix(
    pipes: _Pipes,
    image: "Image.Image",
    *,
    prompt_embeds: Any,
    negative_embeds: Any,
    settings: InternalVideoSettings,
    seed: int,
) -> "Image.Image":
    hires_cfg = settings.hires_fix if isinstance(settings.hires_fix, dict) and settings.hires_fix.get("enabled", True) else None
    if not hires_cfg:
        return image
    scale = float(hires_cfg.get("scale") or 1.0)
    if scale <= 1.0:
        return image
    upscaled = _upscale_render_image(
        image,
        scale=scale,
        upscaler=str(hires_cfg.get("upscaler") or settings.upscaler or ""),
    )
    return _generate_img2img(
        pipes,
        upscaled,
        prompt_embeds,
        negative_embeds,
        upscaled.width,
        upscaled.height,
        int(hires_cfg.get("steps") or settings.steps),
        float(settings.cfg),
        int(seed) + 1,
        float(max(0.0, min(1.0, hires_cfg.get("denoise", 0.35)))),
    )


def _apply_refiner(
    base_pipes: _Pipes,
    image: "Image.Image",
    *,
    prompt: str,
    negative_prompt: str,
    settings: InternalVideoSettings,
    seed: int,
    device: str,
    log_fn=None,
) -> "Image.Image":
    refiner_cfg = settings.refiner if isinstance(settings.refiner, dict) else None
    if not refiner_cfg:
        return image

    refiner_pipes = base_pipes
    refiner_model = str(refiner_cfg.get("model") or "").strip()
    refiner_path_raw = str(refiner_cfg.get("path") or "").strip()
    if refiner_model and not refiner_path_raw:
        raise UserFacingError(
            "Internal refiner model is not installed",
            hint="Install or select a compatible internal refiner model before enabling the refiner pass.",
            code="INTERNAL_REFINER_MISSING",
            status_code=400,
        )

    if refiner_path_raw:
        refiner_dir = Path(refiner_path_raw)
        if not refiner_dir.exists():
            raise UserFacingError(
                "Internal refiner model path does not exist",
                hint="Reinstall the selected internal refiner model, then retry.",
                code="INTERNAL_REFINER_MISSING",
                status_code=400,
            )
        base_path_raw = str(refiner_cfg.get("base_path") or "").strip()
        should_load_dedicated_refiner = True
        if base_path_raw:
            should_load_dedicated_refiner = refiner_dir.resolve() != Path(base_path_raw).resolve()
        if should_load_dedicated_refiner:
            refiner_pipes = _try_load_pipelines(refiner_dir, device=device, role="still")
            if callable(log_fn):
                log_fn(f"Using dedicated refiner model: {refiner_model or refiner_dir.name}")

    prompt_embeds = _encode_prompt(refiner_pipes, prompt)
    negative_embeds = _encode_prompt(refiner_pipes, negative_prompt) if negative_prompt else ""
    switch_at = float(refiner_cfg.get("switch_at", 0.8))
    switch_at = max(0.0, min(1.0, switch_at))
    refiner_steps = int(refiner_cfg.get("steps") or max(6, round(int(settings.steps) * max(0.2, 1.0 - switch_at))))
    return _generate_img2img(
        refiner_pipes,
        image,
        prompt_embeds,
        negative_embeds,
        image.width,
        image.height,
        refiner_steps,
        float(settings.cfg),
        int(seed) + 2,
        float(max(0.05, min(1.0, 1.0 - switch_at))),
    )


def render_internal_still_image(
    *,
    model_dir: Path,
    settings: InternalVideoSettings,
    workflow_family: str,
    prompt: str,
    source_image_path: Path | None = None,
    mask_image_path: Path | None = None,
    controlnet_units: list[dict[str, Any]] | None = None,
    denoise_strength: float = 0.75,
    log_fn=None,
) -> dict[str, Any]:
    family = _model_family_from_dir(model_dir)
    requested_device = _device_auto(settings.device_preference)
    device = requested_device
    if requested_device == "directml" and (
        workflow_family in {"inpaint", "outpaint", "controlnet"} or bool(settings.loras) or family == "sd3"
    ):
        device = "cpu"
    pipes = _try_load_pipelines(model_dir, device=device, role="still")
    width = int(settings.width)
    height = int(settings.height)
    negative_prompt = str(settings.negative_prompt or "").strip()
    seed = int(settings.seed if settings.seed is not None else _stable_seed_int(prompt, width, height, workflow_family, fallback=1337))
    prompt_embeds = _encode_prompt(pipes, prompt)
    negative_embeds = _encode_prompt(pipes, negative_prompt) if negative_prompt else ""

    def _log(message: str) -> None:
        if callable(log_fn):
            log_fn(message)

    with _STILL_PIPELINE_LOCK:
        pipeline = None
        adapter_targets: list[tuple[Any, list[str]]] = []

        def _apply_pipeline_loras(target: Any) -> None:
            if target is None:
                return
            if any(existing is target for existing, _ in adapter_targets):
                return
            adapter_targets.append((target, _apply_loras(target, settings.loras)))

        try:
            if workflow_family == "controlnet":
                units = list(controlnet_units or [])
                controlnet_dirs = [Path(str(unit.get("path") or "")) for unit in units if str(unit.get("path") or "").strip()]
                pipeline = _build_controlnet_pipeline(pipes, controlnet_dirs=controlnet_dirs)
            elif workflow_family in {"inpaint", "outpaint"}:
                pipeline = pipes.inpaint
            elif workflow_family == "img2img":
                pipeline = pipes.img2img
            else:
                pipeline = pipes.txt2img
            for candidate in (pipes.txt2img, pipes.img2img, pipes.inpaint, pipeline):
                _apply_pipeline_loras(candidate)

            if workflow_family == "img2img":
                if source_image_path is None:
                    raise UserFacingError(
                        "No source image selected for img2img",
                        hint="Choose a project source image before running img2img.",
                        code="IMG2IMG_SOURCE_MISSING",
                        status_code=400,
                    )
                init_image = _load_render_source_image(source_image_path, size=(width, height))
                image = _generate_img2img(
                    pipes,
                    init_image,
                    prompt_embeds,
                    negative_embeds,
                    width,
                    height,
                    int(settings.steps),
                    float(settings.cfg),
                    seed,
                    float(max(0.0, min(1.0, denoise_strength))),
                )
            elif workflow_family in {"inpaint", "outpaint"}:
                if source_image_path is None or mask_image_path is None:
                    raise UserFacingError(
                        "Source image or mask is missing for inpaint/outpaint",
                        hint="Choose both a source image and a mask before running the render.",
                        code="INPAINT_ASSETS_MISSING",
                        status_code=400,
                    )
                init_image = _load_render_source_image(source_image_path, size=(width, height))
                mask_image = _load_render_image(mask_image_path, mode="L", size=(width, height))
                image = _generate_inpaint(
                    pipes,
                    init_image,
                    mask_image,
                    prompt=str(prompt or ""),
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    steps=int(settings.steps),
                    cfg=float(settings.cfg),
                    seed=seed,
                    strength=float(max(0.0, min(1.0, denoise_strength))),
                )
            elif workflow_family == "controlnet":
                units = list(controlnet_units or [])
                if not units:
                    raise UserFacingError(
                        "No compatible ControlNet units were provided.",
                        hint="Attach one or more ControlNet units before running the render.",
                        code="CONTROLNET_MISSING",
                        status_code=400,
                    )
                control_images = [
                    _load_render_image(Path(str(unit.get("reference_path") or unit.get("path_reference") or unit.get("reference_image_path") or "")), mode="RGB", size=(width, height))
                    for unit in units
                ]
                scales = [float(unit.get("strength", 0.8)) for unit in units]
                starts = [float(unit.get("start_percent", 0.0)) for unit in units]
                ends = [float(unit.get("end_percent", 1.0)) for unit in units]
                g = None
                if device != "directml":
                    import torch  # type: ignore

                    g = torch.Generator(device=device if device != "mps" else "cpu")
                    g.manual_seed(seed)
                kwargs = {
                    "prompt": str(prompt or "").strip() or "cinematic",
                    "negative_prompt": negative_prompt,
                    "image": control_images[0] if len(control_images) == 1 else control_images,
                    "width": width,
                    "height": height,
                    "num_inference_steps": int(settings.steps),
                    "guidance_scale": float(settings.cfg),
                    "controlnet_conditioning_scale": scales[0] if len(scales) == 1 else scales,
                    "control_guidance_start": starts[0] if len(starts) == 1 else starts,
                    "control_guidance_end": ends[0] if len(ends) == 1 else ends,
                }
                if g is not None:
                    kwargs["generator"] = g
                image = pipeline(**kwargs).images[0]
            else:
                image = _generate_txt2img(
                    pipes,
                    prompt_embeds,
                    negative_embeds,
                    width,
                    height,
                    int(settings.steps),
                    float(settings.cfg),
                    seed,
                )
            image = _apply_hires_fix(
                pipes,
                image,
                prompt_embeds=prompt_embeds,
                negative_embeds=negative_embeds,
                settings=settings,
                seed=seed,
            )
            image = _apply_refiner(
                pipes,
                image,
                prompt=str(prompt or ""),
                negative_prompt=negative_prompt,
                settings=settings,
                seed=seed,
                device=device,
                log_fn=log_fn,
            )
            if device != requested_device:
                _log(f"Internal still render fell back from {requested_device} to {device} for {workflow_family}.")
            return {
                "image": image,
                "device": device,
                "requested_device": requested_device,
                "family": pipes.family,
                "backend": pipes.backend,
                "seed": seed,
            }
        finally:
            for target, adapters in adapter_targets:
                _clear_loras(target, adapters)


def _scene_keyframe_times(scenes: list[dict[str, Any]], interval_s: float) -> list[float]:
    times: list[float] = []
    for sc in scenes:
        start = float(sc.get("start_s", 0.0))
        end = float(sc.get("end_s", start + 5.0))
        t = start
        while t < end - 1e-6:
            times.append(t)
            t += max(0.5, float(interval_s))
    if not times:
        times = [0.0]
    times = sorted(set([round(x, 3) for x in times]))
    return times


def _infer_duration(scenes: list[dict[str, Any]]) -> float:
    if not scenes:
        return 60.0
    return float(scenes[-1].get("end_s", 60.0))


def _prompt_at_time(scenes: list[dict[str, Any]], t: float, timeline: Any | None = None) -> str:
    """Return prompt text at time t.

    Priority:
      1) DAW timeline prompt track (if present): timeline.tracks[*].type=="prompt"
      2) legacy timeline.prompt_regions (if present)
      3) plan scenes
    """
    if timeline:
        # New DAW tracks schema
        tracks = timeline.get("tracks") if isinstance(timeline, dict) else None
        if isinstance(tracks, list):
            for tr in tracks:
                if not isinstance(tr, dict):
                    continue
                if str(tr.get("type") or "").lower() != "prompt":
                    continue
                clips = tr.get("clips")
                if not isinstance(clips, list):
                    continue
                for cl in clips:
                    if not isinstance(cl, dict):
                        continue
                    s = float(cl.get("start_s", 0.0))
                    e = float(cl.get("end_s", s + 5.0))
                    if s <= t < e:
                        data = cl.get("data") or {}
                        p = str((data.get("prompt") if isinstance(data, dict) else "") or "").strip()
                        if p:
                            return p

        # Back-compat: prompt_regions
        regs = timeline.get("prompt_regions") if isinstance(timeline, dict) else None
        if isinstance(regs, list):
            for r in regs:
                if not isinstance(r, dict):
                    continue
                s = float(r.get("start_s", 0.0))
                e = float(r.get("end_s", s + 5.0))
                if s <= t < e:
                    p = str(r.get("prompt") or "").strip()
                    if p:
                        return p

    for sc in scenes:
        s = float(sc.get("start_s", 0.0))
        e = float(sc.get("end_s", s + 5.0))
        if s <= t < e:
            return render_prompt_from_scene(sc, fallback="")
    return render_prompt_from_scene(scenes[0], fallback="") if scenes else DEFAULT_RENDER_PROMPT



def _key_times_bracket(key_times: list[float], t: float) -> tuple[float, float, float]:
    if not key_times:
        return 0.0, 0.0, 0.0
    if t <= key_times[0]:
        return key_times[0], key_times[0], 0.0
    if t >= key_times[-1]:
        return key_times[-1], key_times[-1], 0.0
    a = key_times[0]
    b = key_times[-1]
    for i in range(len(key_times) - 1):
        if key_times[i] <= t <= key_times[i + 1]:
            a, b = key_times[i], key_times[i + 1]
            break
    u = (t - a) / max(1e-9, (b - a))
    w = _ease01(u)
    return a, b, w


def _ease01(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3.0 - 2.0 * u)




def _parse_deforum_schedule(s: str) -> list[tuple[int, float]]:
    """Back-compat wrapper around the shared schedule parser."""
    return coerce_schedule_pairs(s)


def _eval_schedule(pairs: list[tuple[int, float]], frame: int) -> float | None:
    return evaluate_schedule(pairs, frame, default=None)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _build_unified_deforum_context(
    *,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    variant: dict[str, Any] | None,
    settings: InternalVideoSettings,
    fps: int,
) -> UnifiedDeforumRenderContext:
    return build_deforum_render_context(
        scenes=scenes,
        timeline=timeline,
        variant=variant,
        fps=max(1, int(fps)),
        default_negative_prompt=str(settings.negative_prompt or ""),
        overrides=settings.deforum_overrides,
    )


def _prompt_text_for_frame(
    *,
    frame_idx: int,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    deforum_context: UnifiedDeforumRenderContext,
    fps: int,
) -> str:
    prompt = resolve_prompt_frame(deforum_context.prompts, frame_idx, default="")
    if str(prompt or "").strip():
        return str(prompt).strip()
    return _prompt_at_time(scenes, float(frame_idx) / float(max(1, fps)), timeline=timeline) or DEFAULT_RENDER_PROMPT


def _negative_prompt_for_frame(
    *,
    frame_idx: int,
    settings: InternalVideoSettings,
    deforum_context: UnifiedDeforumRenderContext,
) -> str:
    prompt = resolve_prompt_frame(deforum_context.negative_prompts, frame_idx, default=str(settings.negative_prompt or ""))
    return str(prompt or settings.negative_prompt or "")


def _motion_params_at_time(
    t: float,
    timeline: dict[str, Any] | None,
    *,
    deforum_motion: DeforumMotionScheduleBundle | None = None,
    fps: int = 24,
) -> dict[str, float] | None:
    frame = int(round(float(t) * float(max(1, fps))))
    motion = deforum_motion
    if motion is None:
        motion = build_deforum_render_context(
            scenes=[],
            timeline=timeline,
            variant=None,
            fps=max(1, int(fps)),
            default_negative_prompt="",
        ).motion
    if not motion.has_camera_motion() and not motion.has_diffusion_controls():
        return None

    state = evaluate_motion_state(frame, motion)
    out = state.to_renderer_params()
    if "steps" not in out and "strength" in out:
        out["steps"] = _clamp(15.0 * (0.70 + 0.90 * float(out["strength"])), 6.0, 40.0)
    if "denoise" not in out and "strength" in out:
        out["denoise"] = _clamp(float(out["strength"]), 0.01, 0.99)
    return out


_CAMERA_KEYFRAME_FIELDS: tuple[tuple[str, float], ...] = (
    ("zoom", 1.0),
    ("pan_x", 0.0),
    ("pan_y", 0.0),
    ("rotation_deg", 0.0),
    ("translation_z", 0.0),
    ("rotation_3d_x", 0.0),
    ("rotation_3d_y", 0.0),
    ("rotation_3d_z", 0.0),
    ("fov", 70.0),
)


@dataclass(frozen=True)
class _CameraComponents:
    """Full camera pose at a point in time (2D Ken-Burns + 3D Deforum motion)."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    rotation_deg: float = 0.0
    translation_z: float = 0.0
    rotation_3d_x: float = 0.0
    rotation_3d_y: float = 0.0
    rotation_3d_z: float = 0.0
    fov: float = 70.0

    @property
    def roll_deg(self) -> float:
        return float(self.rotation_deg) + float(self.rotation_3d_z)


def _camera_keyframes_are_actionable(points: list[dict[str, Any]]) -> bool:
    if len(points) >= 2:
        return True
    if len(points) != 1:
        return False
    point = points[0]
    return any(
        abs(float(point.get(key, default)) - float(default)) > 1e-4
        for key, default in _CAMERA_KEYFRAME_FIELDS
    )


def _camera_keyframe_components(point: dict[str, Any]) -> _CameraComponents:
    values = {key: float(point.get(key, default)) for key, default in _CAMERA_KEYFRAME_FIELDS}
    return _CameraComponents(**values)


def _lerp_camera_components(a: _CameraComponents, b: _CameraComponents, w: float) -> _CameraComponents:
    iw = 1.0 - w
    return _CameraComponents(
        zoom=a.zoom * iw + b.zoom * w,
        pan_x=a.pan_x * iw + b.pan_x * w,
        pan_y=a.pan_y * iw + b.pan_y * w,
        rotation_deg=a.rotation_deg * iw + b.rotation_deg * w,
        translation_z=a.translation_z * iw + b.translation_z * w,
        rotation_3d_x=a.rotation_3d_x * iw + b.rotation_3d_x * w,
        rotation_3d_y=a.rotation_3d_y * iw + b.rotation_3d_y * w,
        rotation_3d_z=a.rotation_3d_z * iw + b.rotation_3d_z * w,
        fov=a.fov * iw + b.fov * w,
    )


def _camera_components_at_time(
    t: float,
    *,
    timeline: dict[str, Any] | None,
    fallback_interval_s: float,
    deforum_motion: DeforumMotionScheduleBundle | None = None,
    fps: int = 24,
) -> _CameraComponents:
    """Full camera evaluator (2D + 3D).

    Timeline format (optional):
      timeline["camera"]["keyframes"] = [{"t":0,"zoom":1.0,"pan_x":0,"pan_y":0,
        "rotation_deg":0,"translation_z":0,"rotation_3d_x":0,"rotation_3d_y":0,
        "rotation_3d_z":0,"fov":70}, ...]

    Resolution order: timeline camera keyframes -> Deforum motion schedules
    (variant/timeline/overrides) -> deterministic 2D fallback.
    """
    if timeline and isinstance(timeline, dict):
        cam = timeline.get("camera")
        if isinstance(cam, dict):
            kfs = cam.get("keyframes")
            if isinstance(kfs, list):
                pts = [x for x in kfs if isinstance(x, dict) and "t" in x]
                pts.sort(key=lambda d: float(d.get("t", 0.0)))
                if _camera_keyframes_are_actionable(pts):
                    if t <= float(pts[0]["t"]):
                        return _camera_keyframe_components(pts[0])
                    if t >= float(pts[-1]["t"]):
                        return _camera_keyframe_components(pts[-1])

                    a, b = pts[0], pts[-1]
                    for i in range(len(pts) - 1):
                        ta, tb = float(pts[i]["t"]), float(pts[i + 1]["t"])
                        if ta <= t <= tb:
                            a, b = pts[i], pts[i + 1]
                            break
                    ta, tb = float(a["t"]), float(b["t"])
                    u = (t - ta) / max(1e-9, (tb - ta))
                    w = _ease01(u)
                    return _lerp_camera_components(
                        _camera_keyframe_components(a), _camera_keyframe_components(b), w
                    )

    # If camera keyframes are missing, fall back to motion track clips (DAW).
    mp = _motion_params_at_time(t, timeline, deforum_motion=deforum_motion, fps=fps)
    if mp:
        return _CameraComponents(
            zoom=float(mp.get("zoom", 1.0)),
            pan_x=float(mp.get("pan_x", 0.0)),
            pan_y=float(mp.get("pan_y", 0.0)),
            rotation_deg=float(mp.get("rotation_deg", 0.0)),
            translation_z=float(mp.get("translation_z", 0.0)),
            rotation_3d_x=float(mp.get("rotation_3d_x", 0.0)),
            rotation_3d_y=float(mp.get("rotation_3d_y", 0.0)),
            rotation_3d_z=float(mp.get("rotation_3d_z", 0.0)),
            fov=float(mp.get("fov", 70.0)),
        )

    # fallback deterministic motion (2D Ken-Burns drift)
    phase = (t / max(0.001, fallback_interval_s))
    zoom = 1.0 + 0.06 * _ease01((t % fallback_interval_s) / max(0.001, fallback_interval_s))
    pan_x = 8.0 * math.sin(2.0 * math.pi * phase)
    pan_y = 5.0 * math.sin(2.0 * math.pi * phase + 1.2)
    return _CameraComponents(zoom=zoom, pan_x=pan_x, pan_y=pan_y)


def _camera_at_time(
    t: float,
    *,
    timeline: dict[str, Any] | None,
    fallback_interval_s: float,
    deforum_motion: DeforumMotionScheduleBundle | None = None,
    fps: int = 24,
) -> tuple[float, float, float, float]:
    """Backward-compatible 2D camera evaluator (zoom, pan_x, pan_y, rotation_deg)."""
    c = _camera_components_at_time(
        t,
        timeline=timeline,
        fallback_interval_s=fallback_interval_s,
        deforum_motion=deforum_motion,
        fps=fps,
    )
    return c.zoom, c.pan_x, c.pan_y, c.rotation_deg


def _apply_camera_components_absolute(
    img: "Image.Image", out_w: int, out_h: int, comp: _CameraComponents
) -> "Image.Image":
    """Apply an absolute camera pose to a (static) source frame."""
    return _apply_camera_3d(
        img,
        out_w,
        out_h,
        zoom=comp.zoom,
        pan_x=comp.pan_x,
        pan_y=comp.pan_y,
        rotation_deg=comp.roll_deg,
        translation_z=comp.translation_z,
        rotation_3d_x=comp.rotation_3d_x,
        rotation_3d_y=comp.rotation_3d_y,
        fov_deg=comp.fov,
    )


def _apply_camera_components_delta(
    prev_frame: "Image.Image",
    out_w: int,
    out_h: int,
    comp: _CameraComponents,
    prev: _CameraComponents,
) -> "Image.Image":
    """Warp the previous frame by the per-frame camera delta (img2img path)."""
    rz = comp.zoom / max(1e-6, prev.zoom)
    return _apply_camera_3d(
        prev_frame,
        out_w,
        out_h,
        zoom=rz,
        pan_x=comp.pan_x - prev.pan_x,
        pan_y=comp.pan_y - prev.pan_y,
        rotation_deg=comp.roll_deg - prev.roll_deg,
        translation_z=comp.translation_z - prev.translation_z,
        rotation_3d_x=comp.rotation_3d_x - prev.rotation_3d_x,
        rotation_3d_y=comp.rotation_3d_y - prev.rotation_3d_y,
        fov_deg=comp.fov,
    )


def _write_runtime_checkpoint(checkpoint_json: Path, state: dict[str, Any]) -> None:
    checkpoint_json.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_json.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_checkpoint_emitter(
    *,
    checkpoint_json: Path,
    project_dir: Path,
    work_tag: str,
    render_mode: str,
    variant_index: int,
    total_frames: int,
    fps_render: int,
    chunk_plan: dict[str, Any] | None,
    checkpoint_fn=None,
):
    plan = dict(chunk_plan or {})
    frames_per_chunk = max(1, int(plan.get("frames_per_chunk") or total_frames or 1))
    checkpoint_interval_frames = max(1, int(plan.get("checkpoint_interval_frames") or max(1, fps_render * 15)))
    estimated_chunks = max(1, int(plan.get("estimated_chunks") or math.ceil(max(1, total_frames) / max(1, frames_per_chunk))))
    strategy = str(plan.get("strategy") or ("resume_friendly_chunks" if total_frames > frames_per_chunk else "single_pass"))
    enabled = bool(plan.get("enabled", total_frames > frames_per_chunk))
    notes = list(plan.get("notes") or [])
    state: dict[str, Any] = {
        "status": "pending",
        "render_mode": str(render_mode),
        "work_tag": str(work_tag),
        "variant_index": int(variant_index),
        "total_frames": int(total_frames),
        "fps_render": int(fps_render),
        "frames_rendered": 0,
        "frames_reused": 0,
        "completed_frames": 0,
        "last_completed_frame": -1,
        "next_frame_index": 0,
        "frames_per_chunk": int(frames_per_chunk),
        "estimated_chunks": int(estimated_chunks),
        "completed_chunks": 0,
        "current_chunk_index": 1 if total_frames > 0 else 0,
        "current_chunk_progress_frames": 0,
        "checkpoint_interval_frames": int(checkpoint_interval_frames),
        "resume_recommended": bool(plan.get("resume_recommended", enabled)),
        "chunking_enabled": enabled,
        "chunk_strategy": strategy,
        "notes": notes,
        "can_resume": True,
        "outputs": {
            "checkpoint_json": str(checkpoint_json.relative_to(project_dir)),
            "raw_exists": False,
            "interp_exists": False,
            "final_exists": False,
        },
    }
    last_emitted = {"stage": None, "completed_frames": -1, "ts": 0.0}

    def _emit(
        *,
        stage: str,
        status: str = "running",
        force: bool = False,
        final: bool = False,
        message: str | None = None,
        frame_event: str | None = None,
        rendered_delta: int = 0,
        reused_delta: int = 0,
        extra_outputs: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        if rendered_delta:
            state["frames_rendered"] = min(int(total_frames), int(state.get("frames_rendered", 0)) + int(rendered_delta))
        if reused_delta:
            state["frames_reused"] = min(int(total_frames), int(state.get("frames_reused", 0)) + int(reused_delta))
        completed_frames = min(int(total_frames), int(state.get("frames_rendered", 0)) + int(state.get("frames_reused", 0)))
        state["status"] = str(status or ("complete" if final else "running"))
        state["stage"] = str(stage or "running")
        state["completed_frames"] = completed_frames
        state["last_completed_frame"] = completed_frames - 1 if completed_frames > 0 else -1
        state["next_frame_index"] = min(int(total_frames), completed_frames)
        state["current_chunk_index"] = min(int(estimated_chunks), max(1, (completed_frames // max(1, frames_per_chunk)) + 1)) if total_frames > 0 else 0
        state["completed_chunks"] = min(int(estimated_chunks), completed_frames // max(1, frames_per_chunk))
        if completed_frames >= int(total_frames) and total_frames > 0:
            state["completed_chunks"] = int(estimated_chunks)
        state["current_chunk_progress_frames"] = completed_frames % max(1, frames_per_chunk)
        if completed_frames >= int(total_frames) and total_frames > 0:
            state["current_chunk_progress_frames"] = 0
        percent = 100.0 if total_frames <= 0 else round((completed_frames / float(max(1, total_frames))) * 100.0, 1)
        state["resume_percent"] = percent
        state["updated_at"] = time.time()
        if frame_event:
            state["frame_event"] = str(frame_event)
        if message:
            state["message"] = str(message)
        outputs = dict(state.get("outputs") or {})
        if extra_outputs:
            outputs.update({k: bool(v) for k, v in extra_outputs.items()})
        state["outputs"] = outputs

        should_emit = force or final
        now = time.time()
        if not should_emit:
            if last_emitted["stage"] != stage:
                should_emit = True
            elif completed_frames in (0, int(total_frames)):
                should_emit = True
            elif completed_frames - int(last_emitted["completed_frames"]) >= checkpoint_interval_frames:
                should_emit = True
            elif completed_frames > 0 and (completed_frames % max(1, frames_per_chunk) == 0):
                should_emit = True
            elif frame_event and completed_frames != int(last_emitted["completed_frames"]):
                if completed_frames <= max(12, fps_render * 8):
                    should_emit = True
                elif (now - float(last_emitted["ts"] or 0.0)) >= 1.0:
                    should_emit = True
        if should_emit:
            _write_runtime_checkpoint(checkpoint_json, state)
            if checkpoint_fn:
                checkpoint_fn(dict(state))
            last_emitted["stage"] = str(stage)
            last_emitted["completed_frames"] = int(completed_frames)
            last_emitted["ts"] = float(now)
        return dict(state)

    return _emit





def render_internal_video_variant(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    project_id: str | None = None,
    variant: dict[str, Any],
    scenes: list[dict[str, Any]],
    audio_path: Path | None,
    model_dir: Path,
    settings: InternalVideoSettings,
    timeline: dict[str, Any] | None = None,
    log_fn=None,
    progress_fn=None,
    cancel_check_fn=None,
    chunk_plan: dict[str, Any] | None = None,
    checkpoint_fn=None,
    source_image_path: Path | None = None,
) -> Path:
    """Render an internal baseline music video.

    Modes:
      - off/keyframes: SD keyframes + Ken Burns + optional overlays
      - frame_img2img: sequential img2img refinement per frame for temporal consistency

    Image animation:
      - when ``source_image_path`` is provided (or ``settings.source_asset`` resolves),
        the first keyframe is seeded from that image via img2img so any painting or
        photo can be "brought to life" with motion + prompt evolution.
    """
    _require_pillow()

    device = _device_auto(settings.device_preference)
    keyframe_renderer = normalize_video_model_keyframe_renderer(settings.video_model_keyframe_renderer)
    use_tensorrt_keyframes = settings.temporal_mode == "video_model" and keyframe_renderer == "tensorrt_sd15"
    if use_tensorrt_keyframes and device != "cuda":
        raise UserFacingError(
            "TensorRT SD1.5 storyboard anchors require CUDA",
            hint="Switch Device to CUDA or use Internal diffusion keyframes for SVD/AnimateDiff anchors.",
            code="TRT_ANCHOR_CUDA_REQUIRED",
            status_code=400,
        )
    pipes = None if use_tensorrt_keyframes else _try_load_pipelines(model_dir, device=device)

    out_w, out_h = settings.width, settings.height
    fps_r = max(1, int(settings.fps_render))
    fps_schedule = max(1, int(settings.fps_output))
    duration_s = float(variant.get("duration_s") or _infer_duration(scenes))
    total_frames = int(math.ceil(duration_s * fps_r))
    deforum_context = _build_unified_deforum_context(
        scenes=scenes,
        timeline=timeline,
        variant=variant,
        settings=settings,
        fps=fps_schedule,
    )

    work_tag = _build_work_tag(
        variant_index=int(variant.get("index", 0)),
        variant=variant,
        scenes=scenes,
        timeline=timeline,
        model_dir=model_dir,
        settings=settings,
    )
    out_frames = project_dir / "outputs" / "frames_internal" / work_tag
    out_frames.mkdir(parents=True, exist_ok=True)

    key_times = _scene_keyframe_times(scenes, settings.keyframe_interval_s)
    total_units = max(1, len(key_times) + total_frames + 3)
    cache_info = describe_internal_render_cache(
        project_dir=project_dir,
        variant_index=int(variant.get("index", 0)),
        variant=variant,
        scenes=scenes,
        timeline=timeline,
        model_dir=model_dir,
        settings=settings,
        total_frames=total_frames,
    )
    raw_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_raw.mp4"
    interp_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_interp.mp4"
    final_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}.mp4"
    meta_json = project_dir / "outputs" / "videos" / f"{work_tag}.render.json"
    checkpoint_json = project_dir / "outputs" / "videos" / f"{work_tag}.checkpoint.json"
    emit_checkpoint = _build_checkpoint_emitter(
        checkpoint_json=checkpoint_json,
        project_dir=project_dir,
        work_tag=work_tag,
        render_mode="diffusion",
        variant_index=int(variant.get("index", 0)),
        total_frames=total_frames,
        fps_render=fps_r,
        chunk_plan=chunk_plan,
        checkpoint_fn=checkpoint_fn,
    )
    if progress_fn:
        progress_fn("preparing", 0, total_units, f"Preparing internal render on {device}")
    emit_checkpoint(stage="preparing", status="running", force=True, message=f"Preparing internal render on {device}")

    default_negative_embeds = None if use_tensorrt_keyframes else _encode_prompt(pipes, settings.negative_prompt)
    if log_fn:
        log_fn(
            f"Render cache tag={work_tag} resume_existing_frames={'yes' if settings.resume_existing_frames else 'no'}"
        )
        if use_tensorrt_keyframes:
            log_fn(
                "Video-model storyboard anchors: TensorRT SD1.5 keyframes enabled. "
                "SVD will use these images directly; AnimateDiff still loads its SD1.5 Diffusers base and uses anchors for shot blending."
            )
        log_fn(
            f"Cache status frames={cache_info['frames_present']}/{cache_info['frames_expected']} "
            f"raw={'yes' if cache_info['raw_exists'] else 'no'} "
            f"interp={'yes' if cache_info['interp_exists'] else 'no'} "
            f"final={'yes' if cache_info['final_exists'] else 'no'}"
        )

    if settings.resume_existing_frames and final_mp4.exists():
        final_mtime = final_mp4.stat().st_mtime
        audio_ok = (audio_path is None) or (not audio_path.exists()) or (final_mtime >= audio_path.stat().st_mtime)
        if audio_ok:
            emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Reusing completed render {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": True})
            if progress_fn:
                progress_fn("complete", total_units, total_units, f"Reusing completed render {final_mp4.name}")
            if log_fn:
                log_fn(f"Reusing completed render {final_mp4.name}")
            return final_mp4


    # Generate temporally consistent keyframes
    key_imgs: dict[float, Image.Image] = {}
    prev_key_img: Image.Image | None = None
    prev_key_prompt: str = ""
    for i, t in enumerate(key_times):
        if cancel_check_fn:
            cancel_check_fn()
        schedule_frame = int(round(float(t) * float(fps_schedule)))
        p = _prompt_text_for_frame(
            frame_idx=schedule_frame,
            scenes=scenes,
            timeline=timeline,
            deforum_context=deforum_context,
            fps=fps_schedule,
        ) or "cinematic"
        negative_prompt = _negative_prompt_for_frame(frame_idx=schedule_frame, settings=settings, deforum_context=deforum_context)
        negative_embeds = None
        if not use_tensorrt_keyframes:
            negative_embeds = (
                default_negative_embeds
                if negative_prompt == settings.negative_prompt
                else _encode_prompt(pipes, negative_prompt)  # type: ignore[arg-type]
            )
        seed = _stable_seed_int("key", settings.seed, t, p, work_tag)
        if log_fn:
            prompt_preview = " ".join(str(p or "").split())[:220]
            log_fn(f"Keyframe {i+1}/{len(key_times)} t={t:.2f}s seed={seed} device={device} prompt={prompt_preview!r}")
        if progress_fn:
            progress_fn("keyframes", i, total_units, f"Generating keyframe {i+1}/{len(key_times)}")
        emit_checkpoint(stage="keyframes", status="running", message=f"Generating keyframe {i+1}/{len(key_times)}")
        mpk = _motion_params_at_time(t, timeline, deforum_motion=deforum_context.motion, fps=fps_schedule)
        cfgk = float((mpk or {}).get('cfg', settings.cfg))
        stepsk = int(float((mpk or {}).get('steps', settings.steps)))
        denk = float((mpk or {}).get('denoise', (mpk or {}).get('strength', settings.temporal_strength)))
        seed_from_source = i == 0 and source_image_path is not None
        if use_tensorrt_keyframes:
            img = _generate_tensorrt_sd15_keyframe(
                project_id=project_id,
                prompt=p,
                negative_prompt=negative_prompt,
                width=out_w,
                height=out_h,
                steps=stepsk,
                cfg=cfgk,
                sampler=settings.sampler,
                seed=seed,
                model_id=settings.video_model_keyframe_model_id or "local_sd15_tensorrt_bundle",
            )
        else:
            pe = _encode_prompt(pipes, p)  # type: ignore[arg-type]
            if seed_from_source:
                # Image animation: bring the uploaded still to life as the first keyframe.
                try:
                    base_src = _load_render_source_image(source_image_path, size=(out_w, out_h))
                    img = _generate_img2img(
                        pipes,  # type: ignore[arg-type]
                        init_image=base_src,
                        prompt_embeds=pe,
                        negative_embeds=negative_embeds,
                        width=out_w,
                        height=out_h,
                        steps=stepsk,
                        cfg=cfgk,
                        seed=seed,
                        strength=max(0.05, min(0.95, float(settings.source_strength))),
                    )
                    if log_fn:
                        log_fn(f"Seeded first keyframe from source image {Path(source_image_path).name}")
                except Exception as e:  # pragma: no cover - depends on runtime model
                    if log_fn:
                        log_fn(f"Source image seed failed ({e}); falling back to txt2img")
                    img = _generate_txt2img(pipes, pe, negative_embeds, out_w, out_h, stepsk, cfgk, seed)  # type: ignore[arg-type]
            elif prev_key_img is None or settings.temporal_mode in ("off",):
                img = _generate_txt2img(pipes, pe, negative_embeds, out_w, out_h, stepsk, cfgk, seed)  # type: ignore[arg-type]
            else:
                # Keyframe continuity: anchor to previous keyframe to keep style stable.
                img = _generate_img2img(
                    pipes,  # type: ignore[arg-type]
                    init_image=prev_key_img,
                    prompt_embeds=pe,
                    negative_embeds=negative_embeds,
                    width=out_w,
                    height=out_h,
                    steps=max(6, int(settings.temporal_steps or max(8, settings.steps - 3))),
                    cfg=cfgk,
                    seed=seed,
                    strength=max(0.05, min(0.95, denk)),
                )
        key_imgs[t] = img
        prev_key_img = img
        prev_key_prompt = p
        if progress_fn:
            progress_fn("keyframes", i + 1, total_units, f"Ready keyframe {i+1}/{len(key_times)}")
        emit_checkpoint(stage="keyframes", status="running", message=f"Ready keyframe {i+1}/{len(key_times)}")

    def _save_frame(img: Image.Image, fi: int, t: float) -> Path:
        if timeline:
            img = apply_timeline_layers(img, project_dir=project_dir, timeline=timeline, t=t)
        p = _frame_path(out_frames, fi)
        img.save(p)
        return p

    frame_paths: list[Path] = []

    if settings.temporal_mode == "video_model":
        pe = None
        negative_embeds = None
        default_negative_embeds = None
        _release_still_pipeline_memory(pipes, device, log_fn=log_fn)
        pipes = None  # type: ignore[assignment]

        video_model_path = Path(str(settings.video_model_path or ""))
        if not settings.video_model_id or not video_model_path.exists():
            raise UserFacingError(
                "Internal video motion model is not installed",
                hint="Open Models and install Internal SVD or Internal AnimateDiff, then retry with Temporal mode set to Internal video model.",
                code="INTERNAL_VIDEO_MODEL_NOT_INSTALLED",
                status_code=400,
            )

        engine = str(settings.video_model_engine or "svd").strip().lower()
        if engine == "auto":
            engine = "animatediff" if "animatediff" in str(settings.video_model_id or "").lower() else "svd"
        if engine == "animatediff" and _model_family_from_dir(model_dir) != "sd15":
            raise UserFacingError(
                "AnimateDiff internal motion needs an SD 1.5 internal base model",
                hint="Switch Internal model to Stable Diffusion v1.5, or use the SVD internal video model with SDXL/SD3 keyframes.",
                code="INTERNAL_VIDEO_MODEL_BASE_UNSUPPORTED",
                status_code=400,
            )

        if log_fn:
            log_fn(
                f"Internal video model adapter: engine={engine} model_id={settings.video_model_id} "
                f"path={video_model_path}"
            )

        source_scenes = [sc for sc in scenes if isinstance(sc, dict)] or [{"start_s": 0.0, "end_s": duration_s, "prompt": DEFAULT_RENDER_PROMPT}]
        sorted_scenes = _storyboard_scene_windows(scenes=source_scenes, duration_s=duration_s, settings=settings)
        max_scene_frames = max(2, int(settings.video_model_max_frames_per_scene or 25))
        fi_cursor = 0
        if log_fn and normalize_internal_motion_strategy(settings.motion_strategy) == "storyboard_full_motion":
            log_fn(
                f"Storyboard full motion: generated anchors with {len(sorted_scenes)} short motion shots "
                f"(max { _storyboard_shot_max_s(settings):.1f}s each)."
            )
        for scene_index, scene in enumerate(sorted_scenes):
            if cancel_check_fn:
                cancel_check_fn()
            try:
                start_s = max(0.0, float(scene.get("start_s", 0.0) or 0.0))
            except Exception:
                start_s = 0.0
            try:
                end_s = float(scene.get("end_s", 0.0) or 0.0)
            except Exception:
                end_s = 0.0
            if end_s <= start_s:
                next_start = (
                    float(sorted_scenes[scene_index + 1].get("start_s", duration_s) or duration_s)
                    if scene_index + 1 < len(sorted_scenes)
                    else duration_s
                )
                end_s = max(start_s + (1.0 / fps_r), next_start)

            start_f = max(fi_cursor, int(round(start_s * fps_r)))
            end_f = min(total_frames, max(start_f + 1, int(round(end_s * fps_r))))
            if scene_index == len(sorted_scenes) - 1:
                end_f = total_frames
            if start_f >= total_frames or end_f <= start_f:
                continue

            while fi_cursor < start_f and fi_cursor < total_frames:
                t = fi_cursor / fps_r
                a_t, b_t, w = _key_times_bracket(key_times, t)
                filler = key_imgs[a_t].convert("RGB")
                if a_t != b_t:
                    filler = Image.blend(filler, key_imgs[b_t].convert("RGB"), float(w))
                frame_paths.append(_save_frame(filler.resize((out_w, out_h), resample=Image.LANCZOS), fi_cursor, t))
                fi_cursor += 1

            scene_frame_count = max(1, end_f - start_f)
            if settings.resume_existing_frames and all(_frame_path(out_frames, fi).exists() for fi in range(start_f, end_f)):
                for fi in range(start_f, end_f):
                    existing = _frame_path(out_frames, fi)
                    frame_paths.append(existing)
                    fi_cursor = fi + 1
                    emit_checkpoint(stage="frames", status="running", message=f"Reusing video-model frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
                continue

            adapter_frames = min(max_scene_frames, max(2, scene_frame_count))
            if engine == "svd":
                adapter_frames = min(adapter_frames, 25)
                cuda_vram = _cuda_total_vram_gb(device)
                if cuda_vram and cuda_vram <= 6.5:
                    adapter_frames = min(adapter_frames, 8)
                elif cuda_vram and cuda_vram <= 8.5 and not bool(settings.video_model_cpu_offload):
                    adapter_frames = min(adapter_frames, 12)
            elif engine == "animatediff":
                cuda_vram = _cuda_total_vram_gb(device)
                if cuda_vram and cuda_vram <= 6.5:
                    adapter_frames = min(adapter_frames, 12)
                elif cuda_vram and cuda_vram <= 8.5 and not bool(settings.video_model_cpu_offload):
                    adapter_frames = min(adapter_frames, 16)

            schedule_frame = int(round(start_s * float(fps_schedule)))
            prompt = _prompt_text_for_frame(
                frame_idx=schedule_frame,
                scenes=scenes,
                timeline=timeline,
                deforum_context=deforum_context,
                fps=fps_schedule,
            ) or render_prompt_from_scene(scene, fallback=DEFAULT_RENDER_PROMPT)
            negative_prompt = _negative_prompt_for_frame(frame_idx=schedule_frame, settings=settings, deforum_context=deforum_context)
            start_anchor_img, end_anchor_img = _video_anchor_images(
                key_imgs=key_imgs,
                key_times=key_times,
                start_s=start_s,
                end_s=end_s,
                duration_s=duration_s,
                fps_render=fps_r,
                width=out_w,
                height=out_h,
            )
            anchor_mode = _normalize_video_anchor_mode(settings.video_model_anchor_mode)
            init_img = end_anchor_img if anchor_mode == "end" else start_anchor_img
            score_info = video_model_scene_motion_score(
                scene=scene,
                timeline=timeline,
                start_s=start_s,
                end_s=end_s,
                duration_s=duration_s,
                settings=settings,
            )
            prompt_for_model = _refine_video_model_prompt(prompt, score_info=score_info, settings=settings)
            motion_bucket_id = _video_model_motion_bucket_for_score(settings, score_info)
            seed = _stable_seed_int("video-model", settings.seed, scene_index, prompt_for_model, motion_bucket_id, anchor_mode, work_tag)

            if progress_fn:
                progress_fn("video_model", len(key_times) + fi_cursor, total_units, f"Generating {engine} scene {scene_index+1}/{len(sorted_scenes)}")
            emit_checkpoint(stage="video_model", status="running", message=f"Generating {engine} scene {scene_index+1}/{len(sorted_scenes)}")
            if log_fn:
                prompt_preview = " ".join(prompt_for_model.split())[:220]
                score_label = score_info.get("motion_score")
                source_scene = scene.get("_storyboard_source_scene_index")
                shot_index = scene.get("_storyboard_shot_index")
                shot_count = scene.get("_storyboard_shot_count")
                storyboard_label = (
                    f" scene={int(source_scene) + 1} shot={int(shot_index) + 1}/{int(shot_count)}"
                    if source_scene is not None and shot_index is not None and shot_count
                    else ""
                )
                log_fn(
                    f"Generating {engine} scene {scene_index+1}/{len(sorted_scenes)} "
                    f"frames={adapter_frames} seed={seed} anchor={anchor_mode}{storyboard_label} "
                    f"motion_score={score_label} motion_bucket={motion_bucket_id} prompt={prompt_preview!r}"
                )

            adapter_w, adapter_h, adapter_note = _video_model_adapter_canvas(
                engine=engine,
                width=out_w,
                height=out_h,
                device=device,
                cpu_offload=bool(settings.video_model_cpu_offload),
            )
            if adapter_note and log_fn:
                log_fn(f"{adapter_note}; final frames will be resized to {out_w}x{out_h}.")

            generated = generate_video_model_frames(
                engine=engine,
                video_model_dir=video_model_path,
                base_model_dir=model_dir,
                init_image=init_img,
                prompt=prompt_for_model,
                negative_prompt=negative_prompt,
                width=adapter_w,
                height=adapter_h,
                num_frames=adapter_frames,
                fps=fps_r,
                steps=int(settings.temporal_steps or settings.steps),
                cfg=float(settings.cfg),
                seed=seed,
                device=device,
                dtype=str(settings.video_model_dtype or "auto"),
                motion_bucket_id=int(motion_bucket_id),
                noise_aug_strength=float(settings.video_model_noise_aug_strength),
                decode_chunk_size=int(settings.video_model_decode_chunk_size),
                cpu_offload=bool(settings.video_model_cpu_offload),
            )
            if not generated:
                raise RuntimeError(f"Internal {engine} adapter returned no frames.")
            if anchor_mode == "end":
                generated = list(reversed(generated))
            generated = _apply_video_anchor_frames(
                [frame.convert("RGB") for frame in generated],
                anchor_mode=anchor_mode,
                start_img=start_anchor_img,
                end_img=end_anchor_img,
                anchor_strength=float(settings.anchor_strength),
            )

            for local_i, fi in enumerate(range(start_f, end_f)):
                if cancel_check_fn:
                    cancel_check_fn()
                existing = _frame_path(out_frames, fi)
                if settings.resume_existing_frames and existing.exists():
                    frame_paths.append(existing)
                    fi_cursor = fi + 1
                    emit_checkpoint(stage="frames", status="running", message=f"Reusing video-model frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
                    continue
                src_i = int(round((local_i / max(1, scene_frame_count - 1)) * max(0, len(generated) - 1)))
                fr = generated[max(0, min(len(generated) - 1, src_i))].resize((out_w, out_h), resample=Image.LANCZOS)
                t = fi / fps_r
                frame_paths.append(_save_frame(fr, fi, t))
                fi_cursor = fi + 1
                if progress_fn:
                    progress_fn("frames", len(key_times) + fi + 1, total_units, f"Rendered video-model frame {fi+1}/{total_frames}")
                emit_checkpoint(stage="frames", status="running", message=f"Rendered video-model frame {fi+1}/{total_frames}", frame_event="rendered", rendered_delta=1)

        while fi_cursor < total_frames:
            t = fi_cursor / fps_r
            a_t, b_t, w = _key_times_bracket(key_times, t)
            filler = key_imgs[a_t].convert("RGB")
            if a_t != b_t:
                filler = Image.blend(filler, key_imgs[b_t].convert("RGB"), float(w))
            frame_paths.append(_save_frame(filler.resize((out_w, out_h), resample=Image.LANCZOS), fi_cursor, t))
            fi_cursor += 1

    elif settings.temporal_mode != "frame_img2img":
        for fi in range(total_frames):
            if cancel_check_fn:
                cancel_check_fn()
            t = fi / fps_r
            existing = _frame_path(out_frames, fi)
            if settings.resume_existing_frames and existing.exists():
                frame_paths.append(existing)
                if progress_fn:
                    progress_fn("frames", len(key_times) + fi + 1, total_units, f"Reusing frame {fi+1}/{total_frames}")
                emit_checkpoint(stage="frames", status="running", message=f"Reusing frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
                if log_fn and fi % max(1, fps_r * 10) == 0:
                    log_fn(f"Reused cached frame {fi+1}/{total_frames}")
                continue

            a, b, w = _key_times_bracket(key_times, t)
            src = key_imgs[a].convert("RGB")
            if a != b:
                src = Image.blend(src, key_imgs[b].convert("RGB"), float(w))
            comp = _camera_components_at_time(
                t,
                timeline=timeline,
                fallback_interval_s=settings.keyframe_interval_s,
                deforum_motion=deforum_context.motion,
                fps=fps_schedule,
            )
            fr = _apply_camera_components_absolute(src, out_w, out_h, comp)
            frame_paths.append(_save_frame(fr, fi, t))
            if progress_fn:
                progress_fn("frames", len(key_times) + fi + 1, total_units, f"Rendered frame {fi+1}/{total_frames}")
            emit_checkpoint(stage="frames", status="running", message=f"Rendered frame {fi+1}/{total_frames}", frame_event="rendered", rendered_delta=1)
            if log_fn and fi % max(1, fps_r * 3) == 0:
                log_fn(f"Rendered frame {fi+1}/{total_frames}")
    else:
        prev_frame = key_imgs[key_times[0]].resize((out_w, out_h), resample=Image.LANCZOS)
        prev_comp = _camera_components_at_time(
            0.0,
            timeline=timeline,
            fallback_interval_s=settings.keyframe_interval_s,
            deforum_motion=deforum_context.motion,
            fps=fps_schedule,
        )

        refine_every = max(1, int(settings.refine_every_n_frames))
        steps_refine = int(settings.temporal_steps or max(8, settings.steps - 3))

        for fi in range(total_frames):
            if cancel_check_fn:
                cancel_check_fn()
            t = fi / fps_r
            existing = _frame_path(out_frames, fi)
            schedule_frame = int(round(float(t) * float(fps_schedule)))

            a_t, b_t, w = _key_times_bracket(key_times, t)
            comp = _camera_components_at_time(
                t,
                timeline=timeline,
                fallback_interval_s=settings.keyframe_interval_s,
                deforum_motion=deforum_context.motion,
                fps=fps_schedule,
            )

            if settings.resume_existing_frames and existing.exists():
                try:
                    prev_frame = Image.open(existing).convert("RGB").resize((out_w, out_h), resample=Image.LANCZOS)
                    prev_comp = comp
                    frame_paths.append(existing)
                    if progress_fn:
                        progress_fn("frames", len(key_times) + fi + 1, total_units, f"Reusing frame {fi+1}/{total_frames}")
                    emit_checkpoint(stage="frames", status="running", message=f"Reusing frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
                    if log_fn and fi % max(1, fps_r * 10) == 0:
                        log_fn(f"Reused cached frame {fi+1}/{total_frames}")
                    continue
                except Exception:
                    pass

            mp = _motion_params_at_time(t, timeline, deforum_motion=deforum_context.motion, fps=fps_schedule)

            a_frame = int(round(float(a_t) * float(fps_schedule)))
            b_frame = int(round(float(b_t) * float(fps_schedule)))
            a_prompt = _prompt_text_for_frame(
                frame_idx=a_frame,
                scenes=scenes,
                timeline=timeline,
                deforum_context=deforum_context,
                fps=fps_schedule,
            ) or "cinematic"
            b_prompt = _prompt_text_for_frame(
                frame_idx=b_frame,
                scenes=scenes,
                timeline=timeline,
                deforum_context=deforum_context,
                fps=fps_schedule,
            ) or a_prompt
            a_e = _encode_prompt(pipes, a_prompt)
            b_e = _encode_prompt(pipes, b_prompt)
            pe = _blend_embeds(a_e, b_e, w) if settings.prompt_blend else a_e
            negative_prompt = _negative_prompt_for_frame(frame_idx=schedule_frame, settings=settings, deforum_context=deforum_context)
            negative_embeds = (
                default_negative_embeds
                if negative_prompt == settings.negative_prompt
                else _encode_prompt(pipes, negative_prompt)
            )

            init = _apply_camera_components_delta(prev_frame, out_w, out_h, comp, prev_comp)

            # Blend in keyframe anchors to prevent drift.
            anchor = key_imgs[a_t]
            if a_t != b_t:
                anchor = Image.blend(key_imgs[a_t].convert("RGB"), key_imgs[b_t].convert("RGB"), float(w))
            if settings.anchor_strength > 0:
                init = Image.blend(init.convert("RGB"), anchor.convert("RGB"), float(settings.anchor_strength))

            seed = _stable_seed_int("frame", settings.seed, fi, f"{t:.3f}", work_tag)
            if fi % refine_every == 0:
                if log_fn and fi % max(1, fps_r * 3) == 0:
                    log_fn(f"Refining frame {fi+1}/{total_frames} strength={settings.temporal_strength:.2f} steps={steps_refine}")
                out = _generate_img2img(
                    pipes,
                    init_image=init,
                    prompt_embeds=pe,
                    negative_embeds=negative_embeds,
                    width=out_w,
                    height=out_h,
                    steps=int(float((mp or {}).get('steps', steps_refine))),
                    cfg=float((mp or {}).get('cfg', settings.cfg)),
                    seed=seed,
                    strength=float((mp or {}).get('denoise', (mp or {}).get('strength', settings.temporal_strength))),
                )
                prev_frame = out.resize((out_w, out_h), resample=Image.LANCZOS)
            else:
                prev_frame = init.resize((out_w, out_h), resample=Image.LANCZOS)

            prev_comp = comp
            frame_paths.append(_save_frame(prev_frame, fi, t))
            if progress_fn:
                progress_fn("frames", len(key_times) + fi + 1, total_units, f"Rendered frame {fi+1}/{total_frames}")
            emit_checkpoint(stage="frames", status="running", message=f"Rendered frame {fi+1}/{total_frames}", frame_event="rendered", rendered_delta=1)

    if cancel_check_fn:
        cancel_check_fn()

    raw_mp4.parent.mkdir(parents=True, exist_ok=True)
    if settings.resume_existing_frames and cache_info["frames_complete"] and raw_mp4.exists():
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, f"Reusing raw MP4 {raw_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing raw MP4 {raw_mp4.name}", extra_outputs={"raw_exists": True})
        if log_fn:
            log_fn(f"Reusing raw MP4 {raw_mp4.name}")
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, "Assembling raw MP4")
        emit_checkpoint(stage="assembling", status="running", force=True, message="Assembling raw MP4")
        if log_fn:
            log_fn("Assembling raw MP4 from rendered frames")
        assemble_image_sequence(
            ffmpeg_path=ffmpeg_path,
            frames_dir=out_frames,
            out_mp4=raw_mp4,
            fps=fps_r,
            glob_pattern="frame_*.png",
            audio_path=None,
        )

    if cancel_check_fn:
        cancel_check_fn()

    if int(settings.fps_output) == int(fps_r):
        if not interp_mp4.exists() or interp_mp4.stat().st_mtime < raw_mp4.stat().st_mtime:
            interp_mp4.write_bytes(raw_mp4.read_bytes())
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Keeping FPS at {int(settings.fps_output)}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Keeping FPS at {int(settings.fps_output)}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
        if log_fn:
            log_fn(f"Skipping interpolation because fps_output matches fps_render ({int(settings.fps_output)})")
    elif settings.resume_existing_frames and interp_mp4.exists() and raw_mp4.exists() and interp_mp4.stat().st_mtime >= raw_mp4.stat().st_mtime:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Reusing interpolated MP4 {interp_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing interpolated MP4 {interp_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
        if log_fn:
            log_fn(f"Reusing interpolated MP4 {interp_mp4.name}")
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Interpolating to {int(settings.fps_output)} fps")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Interpolating to {int(settings.fps_output)} fps", extra_outputs={"raw_exists": raw_mp4.exists()})
        if log_fn:
            log_fn(f"Interpolating to {int(settings.fps_output)} fps via {settings.interpolation_engine}")
        interpolate_video_fps(
            ffmpeg_path=ffmpeg_path,
            in_mp4=raw_mp4,
            out_mp4=interp_mp4,
            fps_out=int(settings.fps_output),
            engine=settings.interpolation_engine,
        )

    if cancel_check_fn:
        cancel_check_fn()

    if settings.resume_existing_frames and final_mp4.exists():
        final_mtime = final_mp4.stat().st_mtime
        audio_ok = (audio_path is None) or (not audio_path.exists()) or (final_mtime >= audio_path.stat().st_mtime)
        interp_ok = interp_mp4.exists() and final_mtime >= interp_mp4.stat().st_mtime
    else:
        audio_ok = False
        interp_ok = False

    if audio_ok and interp_ok:
        if progress_fn:
            progress_fn("muxing", total_units, total_units, f"Reusing final video {final_mp4.name}")
        emit_checkpoint(stage="muxing", status="running", force=True, message=f"Reusing final video {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": True})
        if log_fn:
            log_fn(f"Reusing final video {final_mp4.name}")
    else:
        if progress_fn:
            progress_fn("muxing", total_units, total_units, "Muxing audio and finalizing video")
        emit_checkpoint(stage="muxing", status="running", force=True, message="Muxing audio and finalizing video", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists()})
        if audio_path and audio_path.exists():
            mux_audio(ffmpeg_path=ffmpeg_path, video_mp4=interp_mp4, audio_path=audio_path, out_mp4=final_mp4)
        else:
            final_mp4.write_bytes(interp_mp4.read_bytes())
    meta = {
        "work_tag": work_tag,
        "completed_at": __import__("time").time(),
        "variant_index": int(variant.get("index", 0)),
        "settings": {
            "fps_render": int(settings.fps_render),
            "fps_output": int(settings.fps_output),
            "width": int(settings.width),
            "height": int(settings.height),
            "steps": int(settings.steps),
            "cfg": float(settings.cfg),
            "sampler": str(settings.sampler),
            "seed": settings.seed,
            "keyframe_interval_s": float(settings.keyframe_interval_s),
            "interpolation_engine": str(settings.interpolation_engine),
            "temporal_mode": str(settings.temporal_mode),
            "temporal_strength": float(settings.temporal_strength),
            "temporal_steps": int(settings.temporal_steps or 0),
            "refine_every_n_frames": int(settings.refine_every_n_frames),
            "anchor_strength": float(settings.anchor_strength),
            "prompt_blend": bool(settings.prompt_blend),
            "motion_strategy": normalize_internal_motion_strategy(settings.motion_strategy),
            "storyboard_shot_max_s": float(_storyboard_shot_max_s(settings)),
            "video_model_engine": str(settings.video_model_engine),
            "video_model_id": str(settings.video_model_id or ""),
            "video_model_path": str(settings.video_model_path or ""),
            "video_model_max_frames_per_scene": int(settings.video_model_max_frames_per_scene),
            "video_model_motion_bucket_id": int(settings.video_model_motion_bucket_id),
            "video_model_noise_aug_strength": float(settings.video_model_noise_aug_strength),
            "video_model_decode_chunk_size": int(settings.video_model_decode_chunk_size),
            "video_model_dtype": str(settings.video_model_dtype),
            "video_model_cpu_offload": bool(settings.video_model_cpu_offload),
            "video_model_motion_score_mode": str(settings.video_model_motion_score_mode),
            "video_model_manual_motion_score": int(settings.video_model_manual_motion_score),
            "video_model_anchor_mode": str(settings.video_model_anchor_mode),
            "video_model_prompt_refine": bool(settings.video_model_prompt_refine),
            "video_model_scene_motion": normalize_video_model_scene_motion(settings.video_model_scene_motion),
            "video_model_keyframe_renderer": normalize_video_model_keyframe_renderer(settings.video_model_keyframe_renderer),
            "video_model_keyframe_model_id": str(settings.video_model_keyframe_model_id or ""),
            "resume_existing_frames": bool(settings.resume_existing_frames),
            "model_id": str(settings.model_id),
            "negative_prompt": str(settings.negative_prompt),
            "loras": list(settings.loras),
            "vae": settings.vae,
            "refiner": settings.refiner,
        },
        "frames": {
            "expected": int(total_frames),
            "present": len(list(out_frames.glob("frame_*.png"))),
            "dir": str(out_frames),
        },
        "outputs": {
            "raw_mp4": str(raw_mp4),
            "interp_mp4": str(interp_mp4),
            "final_mp4": str(final_mp4),
            "checkpoint_json": str(checkpoint_json),
        },
        "timeline_digest": _json_digest(_timeline_render_fingerprint(timeline)),
        "scene_digest": _json_digest(scenes or []),
    }
    try:
        meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Internal render complete: {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": final_mp4.exists()})
    if log_fn:
        log_fn(f"Internal render complete: {final_mp4.name}")

    return final_mp4


def render_stability_hosted_video_variant(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    variant: dict[str, Any],
    scenes: list[dict[str, Any]],
    audio_path: Path | None,
    settings: InternalVideoSettings,
    stability_api_key: str,
    hosted_settings: dict[str, Any],
    timeline: dict[str, Any] | None = None,
    log_fn=None,
    progress_fn=None,
    cancel_check_fn=None,
    chunk_plan: dict[str, Any] | None = None,
    checkpoint_fn=None,
) -> Path:
    _require_pillow()

    from .stability_platform import StabilityPlatformClient

    service = str(hosted_settings.get("service") or "sd3").strip().lower()
    model = str(hosted_settings.get("model") or "sd3.5-large-turbo").strip().lower()
    style_preset = str(hosted_settings.get("style_preset") or "none").strip().lower()
    output_format = str(hosted_settings.get("output_format") or "png").strip().lower()
    hosted_strength = float(hosted_settings.get("strength") or settings.temporal_strength or 0.55)
    hosted_cfg_scale = float(hosted_settings.get("cfg_scale") or settings.cfg or 6.5)
    client = StabilityPlatformClient(stability_api_key)

    out_w, out_h = settings.width, settings.height
    fps_r = max(1, int(settings.fps_render))
    fps_schedule = max(1, int(settings.fps_output))
    duration_s = float(variant.get("duration_s") or _infer_duration(scenes))
    total_frames = int(math.ceil(duration_s * fps_r))
    deforum_context = _build_unified_deforum_context(
        scenes=scenes,
        timeline=timeline,
        variant=variant,
        settings=settings,
        fps=fps_schedule,
    )

    provider_marker = Path(f"stability_platform/{service}/{model or 'default'}")
    work_tag = _build_work_tag(
        variant_index=int(variant.get("index", 0)),
        variant=variant,
        scenes=scenes,
        timeline=timeline,
        model_dir=provider_marker,
        settings=settings,
    )
    out_frames = project_dir / "outputs" / "frames_internal" / work_tag
    out_frames.mkdir(parents=True, exist_ok=True)

    key_times = _scene_keyframe_times(scenes, settings.keyframe_interval_s)
    total_units = max(1, len(key_times) + total_frames + 3)
    cache_info = describe_internal_render_cache(
        project_dir=project_dir,
        variant_index=int(variant.get("index", 0)),
        variant=variant,
        scenes=scenes,
        timeline=timeline,
        model_dir=provider_marker,
        settings=settings,
        total_frames=total_frames,
    )
    raw_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_raw.mp4"
    interp_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_interp.mp4"
    final_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}.mp4"
    meta_json = project_dir / "outputs" / "videos" / f"{work_tag}.render.json"
    checkpoint_json = project_dir / "outputs" / "videos" / f"{work_tag}.checkpoint.json"
    emit_checkpoint = _build_checkpoint_emitter(
        checkpoint_json=checkpoint_json,
        project_dir=project_dir,
        work_tag=work_tag,
        render_mode="hosted",
        variant_index=int(variant.get("index", 0)),
        total_frames=total_frames,
        fps_render=fps_r,
        chunk_plan=chunk_plan,
        checkpoint_fn=checkpoint_fn,
    )
    if progress_fn:
        progress_fn("preparing", 0, total_units, f"Preparing hosted Stability render via {service}")
    emit_checkpoint(stage="preparing", status="running", force=True, message=f"Preparing hosted Stability render via {service}")

    if log_fn:
        log_fn(
            f"Hosted Stability render cache tag={work_tag} service={service} model={model or 'default'} "
            f"resume_existing_frames={'yes' if settings.resume_existing_frames else 'no'}"
        )
        log_fn(
            f"Cache status frames={cache_info['frames_present']}/{cache_info['frames_expected']} "
            f"raw={'yes' if cache_info['raw_exists'] else 'no'} "
            f"interp={'yes' if cache_info['interp_exists'] else 'no'} "
            f"final={'yes' if cache_info['final_exists'] else 'no'}"
        )

    if settings.resume_existing_frames and final_mp4.exists():
        final_mtime = final_mp4.stat().st_mtime
        audio_ok = (audio_path is None) or (not audio_path.exists()) or (final_mtime >= audio_path.stat().st_mtime)
        if audio_ok:
            emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Reusing completed hosted render {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": True})
            if progress_fn:
                progress_fn("complete", total_units, total_units, f"Reusing completed hosted render {final_mp4.name}")
            if log_fn:
                log_fn(f"Reusing completed hosted render {final_mp4.name}")
            return final_mp4

    key_imgs: dict[float, Image.Image] = {}
    prev_key_img: Image.Image | None = None
    supports_init = service in {"sd3", "ultra"}
    for i, t in enumerate(key_times):
        if cancel_check_fn:
            cancel_check_fn()
        schedule_frame = int(round(float(t) * float(fps_schedule)))
        prompt = _prompt_text_for_frame(
            frame_idx=schedule_frame,
            scenes=scenes,
            timeline=timeline,
            deforum_context=deforum_context,
            fps=fps_schedule,
        ) or "cinematic"
        negative_prompt = _negative_prompt_for_frame(frame_idx=schedule_frame, settings=settings, deforum_context=deforum_context)
        seed = int(hash(f"hosted-key:{t}:{prompt}") & 0x7FFFFFFF)
        if progress_fn:
            progress_fn("keyframes", i, total_units, f"Generating hosted keyframe {i+1}/{len(key_times)}")
        emit_checkpoint(stage="keyframes", status="running", message=f"Generating hosted keyframe {i+1}/{len(key_times)}")
        if log_fn:
            log_fn(f"Hosted keyframe {i+1}/{len(key_times)} t={t:.2f}s seed={seed} service={service} model={model or 'default'}")

        key_result = client.generate_image(
            prompt=prompt,
            width=out_w,
            height=out_h,
            service=service,
            model=model,
            style_preset=style_preset,
            negative_prompt=negative_prompt,
            seed=seed,
            init_image=(prev_key_img if supports_init and prev_key_img is not None and settings.temporal_mode != "off" else None),
            strength=hosted_strength,
            cfg_scale=hosted_cfg_scale,
            output_format=output_format,
        )
        img = key_result.image
        key_imgs[t] = img
        prev_key_img = img
        if progress_fn:
            progress_fn("keyframes", i + 1, total_units, f"Ready hosted keyframe {i+1}/{len(key_times)}")
        emit_checkpoint(stage="keyframes", status="running", message=f"Ready hosted keyframe {i+1}/{len(key_times)}")

    def _save_frame(img: Image.Image, fi: int, t: float) -> Path:
        if timeline:
            img = apply_timeline_layers(img, project_dir=project_dir, timeline=timeline, t=t)
        p = _frame_path(out_frames, fi)
        img.save(p)
        return p

    for fi in range(total_frames):
        if cancel_check_fn:
            cancel_check_fn()
        t = fi / fps_r
        existing = _frame_path(out_frames, fi)
        if settings.resume_existing_frames and existing.exists():
            if progress_fn:
                progress_fn("frames", len(key_times) + fi + 1, total_units, f"Reusing hosted frame {fi+1}/{total_frames}")
            emit_checkpoint(stage="frames", status="running", message=f"Reusing hosted frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
            continue

        a, _b, _w = _key_times_bracket(key_times, t)
        src = key_imgs[a]
        comp = _camera_components_at_time(
            t,
            timeline=timeline,
            fallback_interval_s=settings.keyframe_interval_s,
            deforum_motion=deforum_context.motion,
            fps=fps_schedule,
        )
        fr = _apply_camera_components_absolute(src, out_w, out_h, comp)
        _save_frame(fr, fi, t)
        if progress_fn:
            progress_fn("frames", len(key_times) + fi + 1, total_units, f"Rendered hosted frame {fi+1}/{total_frames}")
        emit_checkpoint(stage="frames", status="running", message=f"Rendered hosted frame {fi+1}/{total_frames}", frame_event="rendered", rendered_delta=1)
        if log_fn and fi % max(1, fps_r * 3) == 0:
            log_fn(f"Rendered hosted frame {fi+1}/{total_frames}")

    if cancel_check_fn:
        cancel_check_fn()

    raw_mp4.parent.mkdir(parents=True, exist_ok=True)
    if settings.resume_existing_frames and cache_info["frames_complete"] and raw_mp4.exists():
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, f"Reusing hosted raw MP4 {raw_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing hosted raw MP4 {raw_mp4.name}", extra_outputs={"raw_exists": True})
        if log_fn:
            log_fn(f"Reusing hosted raw MP4 {raw_mp4.name}")
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, "Assembling hosted raw MP4")
        emit_checkpoint(stage="assembling", status="running", force=True, message="Assembling hosted raw MP4")
        if log_fn:
            log_fn("Assembling hosted raw MP4 from rendered frames")
        assemble_image_sequence(
            ffmpeg_path=ffmpeg_path,
            frames_dir=out_frames,
            out_mp4=raw_mp4,
            fps=fps_r,
            glob_pattern="frame_*.png",
            audio_path=None,
        )

    if cancel_check_fn:
        cancel_check_fn()

    if int(settings.fps_output) == int(fps_r):
        if not interp_mp4.exists() or interp_mp4.stat().st_mtime < raw_mp4.stat().st_mtime:
            interp_mp4.write_bytes(raw_mp4.read_bytes())
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Keeping FPS at {int(settings.fps_output)}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Keeping FPS at {int(settings.fps_output)}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
    elif settings.resume_existing_frames and interp_mp4.exists() and raw_mp4.exists() and interp_mp4.stat().st_mtime >= raw_mp4.stat().st_mtime:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Reusing hosted interpolated MP4 {interp_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing hosted interpolated MP4 {interp_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Interpolating to {int(settings.fps_output)} fps")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Interpolating to {int(settings.fps_output)} fps", extra_outputs={"raw_exists": raw_mp4.exists()})
        interpolate_video_fps(
            ffmpeg_path=ffmpeg_path,
            in_mp4=raw_mp4,
            out_mp4=interp_mp4,
            fps_out=int(settings.fps_output),
            engine=settings.interpolation_engine,
        )

    if cancel_check_fn:
        cancel_check_fn()

    if settings.resume_existing_frames and final_mp4.exists():
        final_mtime = final_mp4.stat().st_mtime
        audio_ok = (audio_path is None) or (not audio_path.exists()) or (final_mtime >= audio_path.stat().st_mtime)
        interp_ok = interp_mp4.exists() and final_mtime >= interp_mp4.stat().st_mtime
    else:
        audio_ok = False
        interp_ok = False

    if audio_ok and interp_ok:
        if progress_fn:
            progress_fn("muxing", total_units, total_units, f"Reusing hosted final video {final_mp4.name}")
        emit_checkpoint(stage="muxing", status="running", force=True, message=f"Reusing hosted final video {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": True})
    else:
        if progress_fn:
            progress_fn("muxing", total_units, total_units, "Muxing audio and finalizing hosted video")
        emit_checkpoint(stage="muxing", status="running", force=True, message="Muxing audio and finalizing hosted video", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists()})
        if audio_path and audio_path.exists():
            mux_audio(ffmpeg_path=ffmpeg_path, video_mp4=interp_mp4, audio_path=audio_path, out_mp4=final_mp4)
        else:
            final_mp4.write_bytes(interp_mp4.read_bytes())

    meta = {
        "work_tag": work_tag,
        "completed_at": __import__("time").time(),
        "variant_index": int(variant.get("index", 0)),
        "render_mode": "hosted",
        "hosted_provider": {
            "service": service,
            "model": model,
            "style_preset": style_preset,
            "output_format": output_format,
            "strength": hosted_strength,
            "cfg_scale": hosted_cfg_scale,
        },
        "settings": {
            "fps_render": int(settings.fps_render),
            "fps_output": int(settings.fps_output),
            "width": int(settings.width),
            "height": int(settings.height),
            "keyframe_interval_s": float(settings.keyframe_interval_s),
            "interpolation_engine": str(settings.interpolation_engine),
            "temporal_mode": "keyframes",
            "resume_existing_frames": bool(settings.resume_existing_frames),
            "model_id": str(settings.model_id),
        },
        "frames": {
            "expected": int(total_frames),
            "present": len(list(out_frames.glob("frame_*.png"))),
            "dir": str(out_frames),
        },
        "outputs": {
            "raw_mp4": str(raw_mp4),
            "interp_mp4": str(interp_mp4),
            "final_mp4": str(final_mp4),
            "checkpoint_json": str(checkpoint_json),
        },
        "timeline_digest": _json_digest(_timeline_render_fingerprint(timeline)),
        "scene_digest": _json_digest(scenes or []),
    }
    try:
        meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Hosted render complete: {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": final_mp4.exists()})
    if log_fn:
        log_fn(f"Hosted render complete: {final_mp4.name}")
    return final_mp4


def _proxy_scene_at_time(scenes: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    for sc in scenes or []:
        try:
            start = float(sc.get("start_s", 0.0) or 0.0)
            end = float(sc.get("end_s", start) or start)
        except Exception:
            continue
        if start <= t < max(start, end):
            return sc
    return (scenes or [None])[-1]


def _proxy_palette(prompt: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    raw = hashlib.sha1((prompt or "proxy").encode("utf-8", errors="ignore")).digest()
    a = (40 + raw[0] % 80, 40 + raw[1] % 80, 60 + raw[2] % 80)
    b = (100 + raw[3] % 100, 80 + raw[4] % 100, 100 + raw[5] % 100)
    c = (180 + raw[6] % 60, 160 + raw[7] % 60, 180 + raw[8] % 60)
    return a, b, c


def _wrap_text(text: str, width: int = 28) -> list[str]:
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words:
        return []
    lines: list[str] = []
    line = words[0]
    for w in words[1:]:
        if len(line) + 1 + len(w) <= width:
            line += " " + w
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines[:4]


def _proxy_camera_at_time(timeline: dict[str, Any] | None, t: float) -> dict[str, float]:
    """Linear-interpolate camera zoom/pan from timeline camera keyframes (proxy path)."""
    phase = (float(t) % 8.0) / 8.0
    eased = _ease01(phase)
    default = {
        "zoom": 1.03 + 0.12 * eased,
        "pan_x": math.sin((float(t) / 7.0) * 2.0 * math.pi),
        "pan_y": math.sin((float(t) / 11.0) * 2.0 * math.pi + 1.1) * 0.7,
    }
    cam = (timeline or {}).get("camera") if isinstance(timeline, dict) else None
    kfs = cam.get("keyframes") if isinstance(cam, dict) else None
    if not isinstance(kfs, list) or not kfs:
        return default
    pts: list[tuple[float, dict[str, Any]]] = []
    for k in kfs:
        if not isinstance(k, dict):
            continue
        try:
            pts.append((float(k.get("t", 0.0) or 0.0), k))
        except Exception:
            continue
    if not pts:
        return default
    pts.sort(key=lambda item: item[0])

    def _pick(k: dict[str, Any]) -> dict[str, float]:
        return {
            "zoom": float(k.get("zoom", 1.0) or 1.0),
            "pan_x": float(k.get("pan_x", 0.0) or 0.0),
            "pan_y": float(k.get("pan_y", 0.0) or 0.0),
        }

    if t <= pts[0][0]:
        return _pick(pts[0][1])
    if t >= pts[-1][0]:
        return _pick(pts[-1][1])
    for i in range(len(pts) - 1):
        ta, ka = pts[i]
        tb, kb = pts[i + 1]
        if ta <= t <= tb:
            w = (t - ta) / max(1e-6, tb - ta)

            def _lerp(key: str, dflt: float) -> float:
                return float(ka.get(key, dflt) or dflt) * (1.0 - w) + float(kb.get(key, dflt) or dflt) * w

            return {"zoom": _lerp("zoom", 1.0), "pan_x": _lerp("pan_x", 0.0), "pan_y": _lerp("pan_y", 0.0)}
    return default


def _proxy_energy_at_time(scene: dict[str, Any] | None, t: float, duration_s: float) -> float:
    """Best-effort 0..1 energy for a scene so proxies pulse with the track."""
    scene = scene or {}
    for key in ("energy", "avg_energy", "peak_energy"):
        val = scene.get(key) if isinstance(scene, dict) else None
        if val is None:
            continue
        try:
            return max(0.0, min(1.0, float(val)))
        except Exception:
            continue
    if duration_s <= 0:
        return 0.5
    # Gentle breathing curve so the draft is never perfectly static.
    return max(0.0, min(1.0, 0.5 + 0.18 * math.sin((t / max(1e-6, duration_s)) * 2.0 * math.pi)))


def _normalize_video_motion_score_mode(mode: Any) -> str:
    mode_l = str(mode or "auto").strip().lower()
    return mode_l if mode_l in {"auto", "manual", "off"} else "auto"


def _normalize_video_anchor_mode(mode: Any) -> str:
    mode_l = str(mode or "start").strip().lower()
    return mode_l if mode_l in {"start", "end", "loop"} else "start"


def _clamp_video_motion_score(value: Any, *, default: int = 4) -> int:
    try:
        raw = int(round(float(value)))
    except Exception:
        raw = int(default)
    return max(1, min(7, raw))


def _coerce_unit_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return max(0.0, min(1.0, out))


def _scene_energy_values(scene: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not isinstance(scene, dict):
        return None, None
    energy = None
    peak = None
    for key in ("energy", "avg_energy", "avgEnergy", "intensity", "scene_intensity"):
        energy = _coerce_unit_float(scene.get(key))
        if energy is not None:
            break
    for key in ("peak_energy", "peakEnergy", "onset_energy", "transient_energy"):
        peak = _coerce_unit_float(scene.get(key))
        if peak is not None:
            break
    return energy, peak


def _iter_timeline_sections(timeline: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(timeline, dict):
        return []
    candidates: list[Any] = []
    for key in ("sections", "scene_sections"):
        value = timeline.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    reactive = timeline.get("reactive_lab")
    if isinstance(reactive, dict):
        for key in ("sections", "phrases", "segments"):
            value = reactive.get(key)
            if isinstance(value, list):
                candidates.extend(value)
    return [item for item in candidates if isinstance(item, dict)]


def _timeline_energy_for_range(timeline: dict[str, Any] | None, start_s: float, end_s: float) -> tuple[float | None, float | None]:
    sections = _iter_timeline_sections(timeline)
    if not sections:
        return None, None
    weighted = 0.0
    peak = 0.0
    total = 0.0
    for section in sections:
        try:
            sec_start = float(section.get("start_s", section.get("start", 0.0)) or 0.0)
            sec_end = float(section.get("end_s", section.get("end", sec_start)) or sec_start)
        except Exception:
            continue
        overlap = max(0.0, min(end_s, sec_end) - max(start_s, sec_start))
        if overlap <= 0:
            continue
        energy, section_peak = _scene_energy_values(section)
        if energy is None:
            continue
        weighted += energy * overlap
        peak = max(peak, section_peak if section_peak is not None else energy)
        total += overlap
    if total <= 0:
        return None, None
    return max(0.0, min(1.0, weighted / total)), max(0.0, min(1.0, peak))


def _timeline_event_density(timeline: dict[str, Any] | None, start_s: float, end_s: float) -> float:
    if not isinstance(timeline, dict):
        return 0.0
    reactive = timeline.get("reactive_lab")
    sources: list[Any] = []
    if isinstance(reactive, dict):
        for key in ("cue_events", "onset_events", "beat_markers", "beats"):
            value = reactive.get(key)
            if isinstance(value, list):
                sources.extend(value)
    for key in ("cue_events", "onset_events", "beat_markers", "beats"):
        value = timeline.get(key)
        if isinstance(value, list):
            sources.extend(value)
    if not sources:
        return 0.0
    count = 0
    for event in sources:
        if isinstance(event, dict):
            raw_t = event.get("time_s", event.get("t", event.get("start_s")))
        else:
            raw_t = event
        try:
            t = float(raw_t)
        except Exception:
            continue
        if start_s <= t < end_s:
            count += 1
    duration = max(0.25, end_s - start_s)
    return max(0.0, min(1.0, count / max(1.0, duration * 2.0)))


def video_model_scene_motion_score(
    *,
    scene: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
    start_s: float,
    end_s: float,
    duration_s: float,
    settings: InternalVideoSettings,
) -> dict[str, Any]:
    mode = _normalize_video_motion_score_mode(settings.video_model_motion_score_mode)
    manual_score = _clamp_video_motion_score(settings.video_model_manual_motion_score)
    scene_energy, scene_peak = _scene_energy_values(scene)
    timeline_energy, timeline_peak = _timeline_energy_for_range(timeline, start_s, end_s)
    event_density = _timeline_event_density(timeline, start_s, end_s)

    source = "fallback"
    energy = 0.5
    peak = 0.5
    if scene_energy is not None:
        energy = scene_energy
        peak = scene_peak if scene_peak is not None else scene_energy
        source = "scene"
    elif timeline_energy is not None:
        energy = timeline_energy
        peak = timeline_peak if timeline_peak is not None else timeline_energy
        source = "timeline"
    elif duration_s > 0:
        mid_t = (float(start_s) + float(end_s)) * 0.5
        energy = _proxy_energy_at_time(scene, mid_t, duration_s)
        peak = energy

    if event_density > 0:
        energy = max(energy, min(1.0, energy + event_density * 0.18))
        peak = max(peak, min(1.0, event_density))
        source = f"{source}+events" if source != "fallback" else "events"

    if mode == "off":
        score: int | None = None
    elif mode == "manual":
        score = manual_score
        source = "manual"
    else:
        blended = max(0.0, min(1.0, (float(energy) * 0.75) + (float(peak) * 0.25)))
        score = _clamp_video_motion_score(1.0 + blended * 6.0)

    return {
        "start_s": round(float(start_s), 3),
        "end_s": round(float(end_s), 3),
        "energy": round(float(energy), 3),
        "peak_energy": round(float(peak), 3),
        "event_density": round(float(event_density), 3),
        "motion_score": score,
        "source": source,
    }


def video_model_scene_motion_scores(
    *,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    settings: InternalVideoSettings,
    duration_s: float,
) -> list[dict[str, Any]]:
    valid_scenes = [scene for scene in scenes if isinstance(scene, dict)] or [{"start_s": 0.0, "end_s": duration_s}]
    out: list[dict[str, Any]] = []
    for index, scene in enumerate(valid_scenes):
        try:
            start_s = max(0.0, float(scene.get("start_s", 0.0) or 0.0))
        except Exception:
            start_s = 0.0
        try:
            end_s = float(scene.get("end_s", 0.0) or 0.0)
        except Exception:
            end_s = 0.0
        if end_s <= start_s:
            next_start = (
                float(valid_scenes[index + 1].get("start_s", duration_s) or duration_s)
                if index + 1 < len(valid_scenes)
                else duration_s
            )
            end_s = max(start_s + 0.5, next_start)
        item = video_model_scene_motion_score(
            scene=scene,
            timeline=timeline,
            start_s=start_s,
            end_s=end_s,
            duration_s=duration_s,
            settings=settings,
        )
        item["scene_index"] = index
        out.append(item)
    return out


def _storyboard_shot_max_s(settings: InternalVideoSettings) -> float:
    try:
        value = float(settings.storyboard_shot_max_s or 4.0)
    except Exception:
        value = 4.0
    return max(1.0, min(12.0, value))


def _storyboard_scene_windows(
    *,
    scenes: list[dict[str, Any]],
    duration_s: float,
    settings: InternalVideoSettings,
) -> list[dict[str, Any]]:
    valid_scenes = [scene for scene in scenes if isinstance(scene, dict)] or [
        {"start_s": 0.0, "end_s": duration_s, "prompt": DEFAULT_RENDER_PROMPT}
    ]
    strategy = normalize_internal_motion_strategy(settings.motion_strategy)
    max_shot_s = _storyboard_shot_max_s(settings)
    windows: list[dict[str, Any]] = []

    for scene_index, scene in enumerate(valid_scenes):
        try:
            start_s = max(0.0, float(scene.get("start_s", 0.0) or 0.0))
        except Exception:
            start_s = 0.0
        try:
            end_s = float(scene.get("end_s", 0.0) or 0.0)
        except Exception:
            end_s = 0.0
        if end_s <= start_s:
            next_start = (
                float(valid_scenes[scene_index + 1].get("start_s", duration_s) or duration_s)
                if scene_index + 1 < len(valid_scenes)
                else duration_s
            )
            end_s = max(start_s + 0.5, next_start)

        duration = max(0.5, end_s - start_s)
        shot_count = 1
        if strategy == "storyboard_full_motion":
            shot_count = max(1, int(math.ceil(duration / max_shot_s)))
        for shot_index in range(shot_count):
            shot_start = start_s + (duration * (shot_index / shot_count))
            shot_end = start_s + (duration * ((shot_index + 1) / shot_count))
            if shot_index == shot_count - 1:
                shot_end = end_s
            shot = dict(scene)
            shot["start_s"] = round(float(shot_start), 3)
            shot["end_s"] = round(float(shot_end), 3)
            shot["_storyboard_source_scene_index"] = scene_index
            shot["_storyboard_shot_index"] = shot_index
            shot["_storyboard_shot_count"] = shot_count
            shot["_storyboard_original_start_s"] = round(float(start_s), 3)
            shot["_storyboard_original_end_s"] = round(float(end_s), 3)
            shot["_storyboard_motion_strategy"] = strategy
            windows.append(shot)
    return windows


def _motion_intent_for_score(score: Any) -> dict[str, str]:
    if score is None:
        return {
            "subject_motion": "prompt-led subject motion",
            "camera_motion": "steady cinematic camera",
            "environment_motion": "subtle atmosphere",
        }
    score_i = _clamp_video_motion_score(score)
    if score_i <= 2:
        return {
            "subject_motion": "restrained breathing motion",
            "camera_motion": "slow locked-off push",
            "environment_motion": "soft ambient drift",
        }
    if score_i >= 6:
        return {
            "subject_motion": "energetic beat-reactive movement",
            "camera_motion": "assertive dolly or orbit",
            "environment_motion": "visible particles, light, or fabric motion",
        }
    return {
        "subject_motion": "controlled music-reactive movement",
        "camera_motion": "smooth forward glide",
        "environment_motion": "moderate atmospheric motion",
    }


def describe_storyboard_motion_plan(
    *,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    settings: InternalVideoSettings,
    duration_s: float,
) -> dict[str, Any] | None:
    strategy = normalize_internal_motion_strategy(settings.motion_strategy)
    if strategy != "storyboard_full_motion":
        return None
    keyframe_renderer = normalize_video_model_keyframe_renderer(settings.video_model_keyframe_renderer)
    anchor_source = (
        "source_image"
        if settings.source_asset
        else ("tensorrt_sd15_keyframe" if keyframe_renderer == "tensorrt_sd15" else "generated_scene_keyframe")
    )

    windows = _storyboard_scene_windows(scenes=scenes, duration_s=duration_s, settings=settings)
    shots: list[dict[str, Any]] = []
    for shot in windows:
        start_s = float(shot.get("start_s") or 0.0)
        end_s = float(shot.get("end_s") or max(start_s + 0.5, duration_s))
        score_info = video_model_scene_motion_score(
            scene=shot,
            timeline=timeline,
            start_s=start_s,
            end_s=end_s,
            duration_s=duration_s,
            settings=settings,
        )
        prompt = render_prompt_from_scene(shot, fallback=DEFAULT_RENDER_PROMPT)
        intent = _motion_intent_for_score(score_info.get("motion_score"))
        source_scene_index = int(shot.get("_storyboard_source_scene_index", 0) or 0)
        shot_index = int(shot.get("_storyboard_shot_index", 0) or 0)
        shot_count = int(shot.get("_storyboard_shot_count", 1) or 1)
        shots.append(
            {
                "scene_index": source_scene_index,
                "shot_index": shot_index,
                "shot_count": shot_count,
                "start_s": round(start_s, 3),
                "end_s": round(end_s, 3),
                "prompt": " ".join(prompt.split())[:240],
                "anchor_source": anchor_source,
                "keyframe_renderer": keyframe_renderer,
                "scene_motion": normalize_video_model_scene_motion(settings.video_model_scene_motion),
                "transition": "continue scene motion" if shot_index else "start from generated visual anchor",
                **intent,
                "motion_score": score_info.get("motion_score"),
                "motion_source": score_info.get("source"),
            }
        )

    return {
        "strategy": strategy,
        "anchor_source": anchor_source,
        "keyframe_renderer": keyframe_renderer,
        "keyframe_model_id": (
            settings.video_model_keyframe_model_id or "local_sd15_tensorrt_bundle"
            if keyframe_renderer == "tensorrt_sd15"
            else None
        ),
        "shot_max_s": _storyboard_shot_max_s(settings),
        "scene_count": len([scene for scene in scenes if isinstance(scene, dict)]),
        "shot_count": len(shots),
        "shots": shots,
    }


def _video_model_motion_bucket_for_score(settings: InternalVideoSettings, score_info: dict[str, Any]) -> int:
    base_bucket = max(1, min(255, int(settings.video_model_motion_bucket_id or 127)))
    if _normalize_video_motion_score_mode(settings.video_model_motion_score_mode) == "off":
        return base_bucket
    score = score_info.get("motion_score")
    if score is None:
        return base_bucket
    score_i = _clamp_video_motion_score(score)
    mapped = int(round(72 + ((score_i - 1) / 6.0) * 120))
    return max(1, min(255, int(round((mapped * 0.75) + (base_bucket * 0.25)))))


def _refine_video_model_prompt(
    prompt: str,
    *,
    score_info: dict[str, Any],
    settings: InternalVideoSettings,
) -> str:
    base = " ".join(str(prompt or DEFAULT_RENDER_PROMPT).split()) or DEFAULT_RENDER_PROMPT
    additions: list[str] = []
    score = score_info.get("motion_score")
    mode = _normalize_video_motion_score_mode(settings.video_model_motion_score_mode)
    scene_motion = normalize_video_model_scene_motion(settings.video_model_scene_motion)
    if mode != "off" and score is not None and "motion score" not in base.lower():
        additions.append(f"{_clamp_video_motion_score(score)} motion score.")
    if bool(settings.video_model_prompt_refine):
        if score is not None:
            score_i = _clamp_video_motion_score(score)
            if score_i <= 2:
                additions.append("Slow restrained subject motion with subtle pose changes.")
            elif score_i >= 6:
                additions.append("Energetic music-reactive subject motion with clear pose and object transitions.")
            else:
                additions.append("Controlled music-reactive subject motion with visible changes between frames.")
        if scene_motion == "camera":
            additions.append("Camera motion is primary with only gentle atmosphere movement.")
        elif scene_motion == "scene":
            additions.append(
                "Animate the whole scene: foreground subject changes pose, clothing or hair moves, props shift, "
                "lights flicker, particles, water, smoke, dust, trees, and background atmosphere move naturally."
            )
            additions.append("Camera motion is secondary; the visible objects themselves move through the shot.")
        else:
            additions.append(
                "Animate visible subjects and foreground objects: walking, turning, gesturing, breathing, "
                "cloth or hair sway, and reactive environmental motion."
            )
        anchor_mode = _normalize_video_anchor_mode(settings.video_model_anchor_mode)
        if anchor_mode == "end":
            additions.append("Resolve into the ending anchor.")
        elif anchor_mode == "loop":
            additions.append("Connect the opening anchor into a seamless loop.")
        else:
            additions.append("Preserve the opening anchor.")
    if not additions:
        return base
    return f"{base.rstrip('. ')}. {' '.join(additions)}"


def describe_internal_video_model_preflight(
    *,
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any] | None,
    settings: InternalVideoSettings,
    duration_s: float,
    total_frames: int,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hw = hardware or {}
    engine = str(settings.video_model_engine or "svd").strip().lower()
    if engine == "auto":
        engine = "animatediff" if "animatediff" in str(settings.video_model_id or "").lower() else "svd"
    mode = _normalize_video_motion_score_mode(settings.video_model_motion_score_mode)
    anchor_mode = _normalize_video_anchor_mode(settings.video_model_anchor_mode)
    keyframe_renderer = normalize_video_model_keyframe_renderer(settings.video_model_keyframe_renderer)
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    if int(settings.width) % 8 != 0 or int(settings.height) % 8 != 0:
        warnings.append(
            f"Internal video models expect dimensions divisible by 8; requested {int(settings.width)}x{int(settings.height)} may fail or force a resize."
        )
        checks.append({"name": "dimensions", "status": "warn"})
    else:
        checks.append({"name": "dimensions", "status": "ok"})

    if engine == "svd" and int(settings.video_model_max_frames_per_scene or 25) > 25:
        warnings.append("SVD supports short image-to-video windows; Studio will cap generated adapter frames to 25 per scene.")
        checks.append({"name": "frame_count", "status": "warn", "cap": 25})
    elif engine == "animatediff" and int(settings.video_model_max_frames_per_scene or 25) > 32:
        warnings.append("AnimateDiff works best with shorter context windows; consider 16-32 generated frames per scene before scaling up.")
        checks.append({"name": "frame_count", "status": "warn", "recommended_max": 32})
    else:
        checks.append({"name": "frame_count", "status": "ok"})

    backend = str(settings.device_preference or "").strip().lower()
    if backend in {"", "auto"}:
        backend = str(hw.get("backend") or hw.get("device") or "cpu").lower()
    dtype = str(settings.video_model_dtype or "auto").strip().lower()
    if backend == "cpu" and dtype in {"float16", "bfloat16"}:
        warnings.append("float16/bfloat16 video-model precision is a GPU setting; CPU runs should use auto or float32.")
        checks.append({"name": "dtype", "status": "warn"})
    else:
        checks.append({"name": "dtype", "status": "ok"})

    vram_gb = float(hw.get("vram_gb") or hw.get("cuda_vram_gb") or 0.0)
    if backend == "cuda" and engine == "animatediff" and vram_gb and vram_gb <= 8.5 and not bool(settings.video_model_cpu_offload):
        warnings.append("AnimateDiff on low-VRAM CUDA should use CPU offload before rendering.")
        checks.append({"name": "offload", "status": "warn"})
    else:
        checks.append({"name": "offload", "status": "ok"})

    if keyframe_renderer == "tensorrt_sd15":
        checks.append({"name": "keyframe_renderer", "status": "ok", "renderer": "tensorrt_sd15"})
        if engine == "animatediff":
            warnings.append("TensorRT SD1.5 anchors can guide AnimateDiff shot blending, but AnimateDiff is still text-to-video and still loads its SD1.5 Diffusers base.")
    else:
        checks.append({"name": "keyframe_renderer", "status": "ok", "renderer": "internal"})

    scene_scores = video_model_scene_motion_scores(
        scenes=scenes,
        timeline=timeline,
        settings=settings,
        duration_s=duration_s,
    )
    storyboard_motion_plan = describe_storyboard_motion_plan(
        scenes=scenes,
        timeline=timeline,
        settings=settings,
        duration_s=duration_s,
    )

    return {
        "engine": engine,
        "motion_score_mode": mode,
        "manual_motion_score": _clamp_video_motion_score(settings.video_model_manual_motion_score),
        "anchor_mode": anchor_mode,
        "prompt_refine": bool(settings.video_model_prompt_refine),
        "scene_motion": normalize_video_model_scene_motion(settings.video_model_scene_motion),
        "keyframe_renderer": keyframe_renderer,
        "keyframe_model_id": (
            settings.video_model_keyframe_model_id or "local_sd15_tensorrt_bundle"
            if keyframe_renderer == "tensorrt_sd15"
            else None
        ),
        "motion_strategy": normalize_internal_motion_strategy(settings.motion_strategy),
        "storyboard_motion_plan": storyboard_motion_plan,
        "total_frames": int(total_frames),
        "max_frames_per_scene": int(settings.video_model_max_frames_per_scene or 25),
        "scene_scores": scene_scores,
        "checks": checks,
        "warnings": warnings,
    }


def _key_image_at_time(
    key_imgs: dict[float, Image.Image],
    key_times: list[float],
    t: float,
    *,
    width: int,
    height: int,
) -> Image.Image:
    a_t, b_t, w = _key_times_bracket(key_times, t)
    img = key_imgs[a_t].convert("RGB")
    if a_t != b_t:
        img = Image.blend(img, key_imgs[b_t].convert("RGB"), float(w))
    return img.resize((int(width), int(height)), resample=Image.LANCZOS)


def _video_anchor_images(
    *,
    key_imgs: dict[float, Image.Image],
    key_times: list[float],
    start_s: float,
    end_s: float,
    duration_s: float,
    fps_render: int,
    width: int,
    height: int,
) -> tuple[Image.Image, Image.Image]:
    start_img = _key_image_at_time(key_imgs, key_times, float(start_s), width=width, height=height)
    end_probe = min(float(duration_s), max(float(start_s), float(end_s) - (1.0 / max(1, int(fps_render)))))
    end_img = _key_image_at_time(key_imgs, key_times, end_probe, width=width, height=height)
    return start_img, end_img


def _apply_video_anchor_frames(
    frames: list[Image.Image],
    *,
    anchor_mode: str,
    start_img: Image.Image,
    end_img: Image.Image,
    anchor_strength: float,
) -> list[Image.Image]:
    if not frames:
        return frames
    mode = _normalize_video_anchor_mode(anchor_mode)
    out = [frame.convert("RGB") for frame in frames]
    edge = max(1, min(8, max(1, len(out) // 4)))
    blend_max = max(0.20, min(0.85, 0.35 + float(anchor_strength) * 0.5))
    start = start_img.convert("RGB").resize(out[0].size, resample=Image.LANCZOS)
    tail_target = start if mode == "loop" else end_img.convert("RGB").resize(out[-1].size, resample=Image.LANCZOS)

    if mode in {"start", "loop"}:
        for i in range(edge):
            alpha = blend_max * (1.0 - (i / max(1, edge)))
            out[i] = Image.blend(out[i], start, alpha)
    if mode in {"end", "loop"}:
        for i in range(edge):
            idx = len(out) - 1 - i
            alpha = blend_max * (1.0 - (i / max(1, edge)))
            out[idx] = Image.blend(out[idx], tail_target, alpha)
    return out


def _proxy_resample():
    return getattr(getattr(Image, "Resampling", Image), "BILINEAR", 2)


def _apply_proxy_motion(img: Image.Image, camera: dict[str, float], energy: float) -> Image.Image:
    """Apply a Ken-Burns style zoom/pan crop driven by camera keyframes + energy."""
    w, h = img.size
    if w < 4 or h < 4:
        return img
    zoom = max(1.0, min(2.2, float(camera.get("zoom", 1.0) or 1.0) + 0.06 * float(energy)))
    if zoom <= 1.0001:
        return img
    cw = w / zoom
    ch = h / zoom
    max_off_x = (w - cw) / 2.0
    max_off_y = (h - ch) / 2.0
    pan_x = float(camera.get("pan_x", 0.0) or 0.0)
    pan_y = float(camera.get("pan_y", 0.0) or 0.0)
    cx = w / 2.0 + max(-max_off_x, min(max_off_x, pan_x * w * 0.1))
    cy = h / 2.0 + max(-max_off_y, min(max_off_y, pan_y * h * 0.1))
    left = max(0.0, min(w - cw, cx - cw / 2.0))
    top = max(0.0, min(h - ch, cy - ch / 2.0))
    box = (int(left), int(top), int(left + cw), int(top + ch))
    return img.crop(box).resize((w, h), _proxy_resample())


def _apply_proxy_finish(img: Image.Image, energy: float) -> Image.Image:
    """Vignette + subtle film grain so the local proxy reads as a finished draft."""
    w, h = img.size
    if w < 4 or h < 4:
        return img
    out = img.convert("RGB")
    # Vignette: darken edges using a radial mask (C-level, fast).
    try:
        mask = Image.radial_gradient("L").resize((w, h), _proxy_resample())
        strength = 0.55
        edge = mask.point(lambda v: int(v * strength))
        black = Image.new("RGB", (w, h), (0, 0, 0))
        out = Image.composite(black, out, edge)
    except Exception:
        pass
    # Film grain: blend low-alpha noise, slightly stronger on high-energy beats.
    try:
        sigma = 14.0 + 26.0 * max(0.0, min(1.0, float(energy)))
        noise = Image.effect_noise((w, h), sigma).convert("RGB")
        alpha = 0.05 + 0.05 * max(0.0, min(1.0, float(energy)))
        out = Image.blend(out, noise, alpha)
    except Exception:
        pass
    return out


def _build_proxy_base_frame(
    *,
    width: int,
    height: int,
    t: float,
    duration_s: float,
    scene: dict[str, Any] | None,
) -> Image.Image:
    _require_pillow()
    scene = scene or {}
    prompt = str(scene.get("prompt") or scene.get("name") or "EDMG Studio draft proxy")
    a, b, c = _proxy_palette(prompt)
    img = Image.new("RGB", (int(width), int(height)), color=a)
    px = img.load()
    for y in range(int(height)):
        mix = y / max(1, int(height) - 1)
        row = tuple(int(a[i] * (1.0 - mix) + b[i] * mix) for i in range(3))
        for x in range(int(width)):
            px[x, y] = row
    draw = ImageDraw.Draw(img) if ImageDraw is not None else None
    font = ImageFont.load_default() if ImageFont is not None else None
    if draw is not None:
        band_h = max(44, int(height * 0.16))
        draw.rectangle([(0, height - band_h), (width, height)], fill=(10, 10, 14))
        prog = 0.0 if duration_s <= 0 else max(0.0, min(1.0, t / duration_s))
        draw.rectangle([(0, height - 8), (int(width * prog), height)], fill=c)
        scene_label = str(scene.get("name") or scene.get("emotion") or "Draft proxy")
        draw.text((18, 18), scene_label[:48], fill=(245, 245, 245), font=font)
        draw.text((18, height - band_h + 10), f"t={t:05.2f}s / {duration_s:05.2f}s", fill=(240, 240, 240), font=font)
        for idx, line in enumerate(_wrap_text(prompt, width=30)):
            draw.text((18, 50 + idx * 18), line, fill=(255, 255, 255), font=font)
    return img


def render_internal_proxy_video_variant(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    variant: dict[str, Any],
    scenes: list[dict[str, Any]],
    audio_path: Path | None,
    settings: InternalVideoSettings,
    timeline: dict[str, Any] | None = None,
    log_fn=None,
    progress_fn=None,
    cancel_check_fn=None,
    chunk_plan: dict[str, Any] | None = None,
    checkpoint_fn=None,
) -> Path:
    """Render a local draft/proxy video with no diffusion dependency.

    This keeps the EDMG Studio loop productive even when ComfyUI or internal SD
    models are not installed yet. The proxy video visualizes pacing, scene prompt
    changes, and timeline overlays/text/masks using only Pillow + FFmpeg.
    """
    _require_pillow()

    out_w, out_h = settings.width, settings.height
    fps_r = max(1, int(settings.fps_render))
    fps_out = max(1, int(settings.fps_output))
    duration_s = float(variant.get("duration_s") or _infer_duration(scenes))
    total_frames = int(math.ceil(duration_s * fps_r))

    work_tag = _build_proxy_work_tag(
        variant_index=int(variant.get("index", 0)),
        scenes=scenes,
        timeline=timeline,
        settings=settings,
    )
    out_frames = project_dir / "outputs" / "frames_proxy" / work_tag
    out_frames.mkdir(parents=True, exist_ok=True)

    cache_info = describe_proxy_render_cache(
        project_dir=project_dir,
        variant_index=int(variant.get("index", 0)),
        scenes=scenes,
        timeline=timeline,
        settings=settings,
        total_frames=total_frames,
    )
    total_units = max(1, total_frames + 3)
    raw_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_raw.mp4"
    interp_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}_interp.mp4"
    final_mp4 = project_dir / "outputs" / "videos" / f"{work_tag}.mp4"
    meta_json = project_dir / "outputs" / "videos" / f"{work_tag}.render.json"
    checkpoint_json = project_dir / "outputs" / "videos" / f"{work_tag}.checkpoint.json"
    emit_checkpoint = _build_checkpoint_emitter(
        checkpoint_json=checkpoint_json,
        project_dir=project_dir,
        work_tag=work_tag,
        render_mode="proxy",
        variant_index=int(variant.get("index", 0)),
        total_frames=total_frames,
        fps_render=fps_r,
        chunk_plan=chunk_plan,
        checkpoint_fn=checkpoint_fn,
    )

    emit_checkpoint(stage="preparing", status="running", force=True, message="Preparing proxy render")

    if settings.resume_existing_frames and final_mp4.exists():
        final_mtime = final_mp4.stat().st_mtime
        audio_ok = (audio_path is None) or (not audio_path.exists()) or (final_mtime >= audio_path.stat().st_mtime)
        if audio_ok:
            emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Reusing completed proxy render {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": True})
            if progress_fn:
                progress_fn("complete", total_units, total_units, f"Reusing completed proxy render {final_mp4.name}")
            if log_fn:
                log_fn(f"Reusing completed proxy render {final_mp4.name}")
            return final_mp4

    if log_fn:
        log_fn(
            f"Proxy render cache tag={work_tag} resume_existing_frames={'yes' if settings.resume_existing_frames else 'no'}"
        )
        log_fn(
            f"Cache status frames={cache_info['frames_present']}/{cache_info['frames_expected']} "
            f"raw={'yes' if cache_info['raw_exists'] else 'no'} "
            f"interp={'yes' if cache_info['interp_exists'] else 'no'} "
            f"final={'yes' if cache_info['final_exists'] else 'no'}"
        )

    for fi in range(total_frames):
        if cancel_check_fn:
            cancel_check_fn()
        t = fi / fps_r
        existing = _frame_path(out_frames, fi)
        if settings.resume_existing_frames and existing.exists():
            if progress_fn:
                progress_fn("frames", fi + 1, total_units, f"Reusing proxy frame {fi+1}/{total_frames}")
            emit_checkpoint(stage="frames", status="running", message=f"Reusing proxy frame {fi+1}/{total_frames}", frame_event="reused", reused_delta=1)
            continue
        scene = _proxy_scene_at_time(scenes, t)
        img = _build_proxy_base_frame(width=out_w, height=out_h, t=t, duration_s=duration_s, scene=scene)
        try:
            img = apply_timeline_layers(img, project_dir=project_dir, timeline=(timeline or {}), t=float(t))
        except Exception:
            pass
        if settings.proxy_motion or settings.proxy_finish:
            try:
                energy = _proxy_energy_at_time(scene, t, duration_s)
                if settings.proxy_motion:
                    img = _apply_proxy_motion(img, _proxy_camera_at_time(timeline, t), energy)
                if settings.proxy_finish:
                    img = _apply_proxy_finish(img, energy)
            except Exception:
                pass
        img.save(existing)
        if progress_fn:
            progress_fn("frames", fi + 1, total_units, f"Rendered proxy frame {fi+1}/{total_frames}")
        emit_checkpoint(stage="frames", status="running", message=f"Rendered proxy frame {fi+1}/{total_frames}", frame_event="rendered", rendered_delta=1)
        if log_fn and fi % max(1, fps_r * 4) == 0:
            log_fn(f"Rendered proxy frame {fi+1}/{total_frames}")

    raw_mp4.parent.mkdir(parents=True, exist_ok=True)
    if settings.resume_existing_frames and cache_info["frames_complete"] and raw_mp4.exists():
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, f"Reusing proxy raw MP4 {raw_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing proxy raw MP4 {raw_mp4.name}", extra_outputs={"raw_exists": True})
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 2, total_units, "Assembling proxy raw MP4")
        emit_checkpoint(stage="assembling", status="running", force=True, message="Assembling proxy raw MP4")
        assemble_image_sequence(
            ffmpeg_path=ffmpeg_path,
            frames_dir=out_frames,
            out_mp4=raw_mp4,
            fps=fps_r,
            glob_pattern="frame_*.png",
            audio_path=None,
        )

    if fps_out == fps_r:
        if not interp_mp4.exists() or interp_mp4.stat().st_mtime < raw_mp4.stat().st_mtime:
            interp_mp4.write_bytes(raw_mp4.read_bytes())
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Keeping proxy FPS at {fps_out}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Keeping proxy FPS at {fps_out}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
    elif settings.resume_existing_frames and interp_mp4.exists() and interp_mp4.stat().st_mtime >= raw_mp4.stat().st_mtime:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Reusing interpolated proxy MP4 {interp_mp4.name}")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Reusing interpolated proxy MP4 {interp_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": True})
    else:
        if progress_fn:
            progress_fn("assembling", total_units - 1, total_units, f"Interpolating proxy render to {fps_out} fps")
        emit_checkpoint(stage="assembling", status="running", force=True, message=f"Interpolating proxy render to {fps_out} fps", extra_outputs={"raw_exists": raw_mp4.exists()})
        interpolate_video_fps(
            ffmpeg_path=ffmpeg_path,
            in_mp4=raw_mp4,
            out_mp4=interp_mp4,
            fps_out=fps_out,
            engine=settings.interpolation_engine,
        )

    if audio_path and audio_path.exists():
        if progress_fn:
            progress_fn("muxing", total_units, total_units, "Muxing proxy render audio")
        emit_checkpoint(stage="muxing", status="running", force=True, message="Muxing proxy render audio", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists()})
        mux_audio(ffmpeg_path=ffmpeg_path, video_mp4=interp_mp4, audio_path=audio_path, out_mp4=final_mp4)
    else:
        final_mp4.write_bytes(interp_mp4.read_bytes())
        if progress_fn:
            progress_fn("muxing", total_units, total_units, f"Saved proxy render {final_mp4.name}")
        emit_checkpoint(stage="muxing", status="running", force=True, message=f"Saved proxy render {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists()})

    meta = {
        "work_tag": work_tag,
        "completed_at": __import__("time").time(),
        "variant_index": int(variant.get("index", 0)),
        "render_mode": "proxy",
        "settings": {
            "fps_render": int(settings.fps_render),
            "fps_output": int(settings.fps_output),
            "width": int(settings.width),
            "height": int(settings.height),
            "interpolation_engine": str(settings.interpolation_engine),
            "resume_existing_frames": bool(settings.resume_existing_frames),
            "model_id": str(settings.model_id or "proxy_draft"),
        },
        "frames": {
            "expected": int(total_frames),
            "present": len(list(out_frames.glob("frame_*.png"))),
            "dir": str(out_frames),
        },
        "outputs": {
            "raw_mp4": str(raw_mp4),
            "interp_mp4": str(interp_mp4),
            "final_mp4": str(final_mp4),
            "checkpoint_json": str(checkpoint_json),
        },
        "timeline_digest": _json_digest(_timeline_render_fingerprint(timeline)),
        "scene_digest": _json_digest(scenes or []),
    }
    try:
        meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    emit_checkpoint(stage="complete", status="complete", force=True, final=True, message=f"Proxy render complete: {final_mp4.name}", extra_outputs={"raw_exists": raw_mp4.exists(), "interp_exists": interp_mp4.exists(), "final_exists": final_mp4.exists()})
    if log_fn:
        log_fn(f"Proxy render complete: {final_mp4.name}")

    return final_mp4



def render_internal_diffusion_preview_segment(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    scenes: list[dict[str, Any]],
    model_dir: Path,
    settings: InternalVideoSettings,
    timeline: dict[str, Any] | None,
    start_s: float,
    end_s: float,
    fps: int,
    out_mp4: Path,
    prompt_override: str | None = None,
    seed: int | None = None,
    force: bool = False,
    log_fn=None,
) -> Path:
    """Render a short cached diffusion preview clip (low-res, low steps).

    Intended for quick "look" checks inside the Timeline page. This is NOT a full render:
      - capped duration
      - no audio mux
      - low FPS and low steps by default (caller should set settings.steps/settings.cfg)

    Cache keys and directories are managed by the caller (backend endpoint).
    """
    _require_pillow()

    start = max(0.0, float(start_s))
    end = max(start + 0.05, float(end_s))
    # protect the machine: keep previews short
    end = min(end, start + 10.0)
    fps_i = max(1, min(12, int(fps)))

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists() and not force:
        return out_mp4

    # tmp frames directory
    frames_dir = out_mp4.parent / f"_tmp_{out_mp4.stem}"
    if frames_dir.exists():
        try:
            for f in frames_dir.glob("*.png"):
                f.unlink(missing_ok=True)
        except Exception:
            pass
    frames_dir.mkdir(parents=True, exist_ok=True)

    device = _device_auto(settings.device_preference)
    pipes = _try_load_pipelines(model_dir, device=device)

    try:
        import torch  # type: ignore
    except Exception:
        torch = None  # type: ignore

    # Stable seed for repeatable previews
    base_seed = int(seed) if seed is not None else int(settings.seed or 1337)
    gen = None
    try:
        if torch is not None:
            gen = torch.Generator(device=device).manual_seed(base_seed)
    except Exception:
        gen = None

    # Render frames
    n = int(math.ceil((end - start) * fps_i))
    prev_img = None
    fps_schedule = max(1, int(settings.fps_output))
    deforum_context = _build_unified_deforum_context(
        scenes=scenes,
        timeline=timeline,
        variant=None,
        settings=settings,
        fps=fps_schedule,
    )

    # Limit preview cost even if user set aggressive settings
    steps = max(1, min(int(settings.steps), 30))
    cfg = float(settings.cfg)

    for i in range(n):
        t = start + (i / fps_i)
        schedule_frame = int(round(float(t) * float(fps_schedule)))

        prompt = (prompt_override or "").strip()
        if not prompt:
            prompt = _prompt_text_for_frame(
                frame_idx=schedule_frame,
                scenes=scenes,
                timeline=timeline,
                deforum_context=deforum_context,
                fps=fps_schedule,
            )
        neg = _negative_prompt_for_frame(frame_idx=schedule_frame, settings=settings, deforum_context=deforum_context)

        # camera motion (camera keyframes -> motion track -> fallback)
        comp = _camera_components_at_time(
            t,
            timeline=timeline,
            fallback_interval_s=settings.keyframe_interval_s,
            deforum_motion=deforum_context.motion,
            fps=fps_schedule,
        )

        # low-cost temporal continuity
        use_img2img = (settings.temporal_mode or "").lower() == "frame_img2img" and prev_img is not None
        strength = float(settings.temporal_strength if use_img2img else 1.0)

        try:
            if use_img2img:
                # img2img path
                img = pipes.img2img(
                    prompt=prompt,
                    negative_prompt=neg,
                    image=prev_img,
                    strength=strength,
                    guidance_scale=cfg,
                    num_inference_steps=steps,
                    generator=gen,
                ).images[0]
            else:
                img = pipes.txt2img(
                    prompt=prompt,
                    negative_prompt=neg,
                    width=int(settings.width),
                    height=int(settings.height),
                    guidance_scale=cfg,
                    num_inference_steps=steps,
                    generator=gen,
                ).images[0]
        except Exception as e:
            raise UserFacingError(
                "Diffusion preview failed",
                hint=f"Try lower resolution/steps, or switch internal model. Error: {e}",
                code="DIFF_PREVIEW",
                status_code=500,
            ) from e

        # Apply camera transform and overlays at absolute time t
        try:
            fr = _apply_camera_components_absolute(img, int(settings.width), int(settings.height), comp)
        except Exception:
            fr = img

        try:
            fr = apply_timeline_layers(fr, project_dir=project_dir, timeline=(timeline or {}), t=float(t))
        except Exception:
            pass

        fr.save(frames_dir / f"frame_{i:06d}.png")
        prev_img = img

        if log_fn and i % max(1, fps_i * 2) == 0:
            log_fn(f"Diffusion preview frame {i+1}/{n}")

    assemble_image_sequence(
        ffmpeg_path=ffmpeg_path,
        frames_dir=frames_dir,
        out_mp4=out_mp4,
        fps=fps_i,
        glob_pattern="frame_*.png",
        audio_path=None,
    )

    # cleanup
    try:
        for f in frames_dir.glob("*.png"):
            f.unlink(missing_ok=True)
        frames_dir.rmdir()
    except Exception:
        pass

    return out_mp4
