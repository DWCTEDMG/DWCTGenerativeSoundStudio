from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any

from ..errors import UserFacingError
from .model_weights import diffusers_weight_load_kwargs


_VIDEO_PIPELINE_CACHE: dict[tuple[str, str, str, str], Any] = {}


def dependency_status() -> dict[str, Any]:
    return {
        "diffusers_available": importlib.util.find_spec("diffusers") is not None,
        "torch_available": importlib.util.find_spec("torch") is not None,
        "pil_available": importlib.util.find_spec("PIL") is not None,
    }


def _parse_torch_dtype(dtype: str, device: str):
    import torch  # type: ignore

    raw = str(dtype or "").strip().lower()
    if raw in {"float32", "fp32"}:
        return torch.float32
    if raw in {"bfloat16", "bf16"}:
        return torch.bfloat16
    if device in {"cuda", "mps"}:
        return torch.float16
    return torch.float32


def _seeded_generator(seed: int | None, device: str):
    import torch  # type: ignore

    used_seed = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
    generator_device = device if device == "cuda" else "cpu"
    generator = torch.Generator(device=generator_device)
    generator.manual_seed(used_seed)
    return generator, used_seed


def _normalize_frames(raw_frames: Any) -> list[Any]:
    frames = raw_frames
    if hasattr(frames, "frames"):
        frames = frames.frames
    if isinstance(frames, (list, tuple)) and frames and isinstance(frames[0], (list, tuple)):
        frames = frames[0]
    return list(frames or [])


def _to_rgb_frames(frames: list[Any], *, width: int, height: int) -> list[Any]:
    from PIL import Image  # type: ignore

    out: list[Image.Image] = []
    for frame in frames:
        if frame is None:
            continue
        img = frame.convert("RGB") if hasattr(frame, "convert") else Image.fromarray(frame).convert("RGB")
        if img.size != (int(width), int(height)):
            img = img.resize((int(width), int(height)), resample=Image.LANCZOS)
        out.append(img)
    return out


def _optimize_pipeline(pipe: Any, device: str, *, cpu_offload: bool) -> Any:
    if hasattr(pipe, "enable_attention_slicing"):
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
    if device == "cuda" and hasattr(pipe, "enable_xformers_memory_efficient_attention"):
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass
    if cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
        try:
            pipe.enable_model_cpu_offload()
            return pipe
        except Exception:
            pass
    if hasattr(pipe, "to"):
        pipe = pipe.to(device)
    return pipe


def _video_model_base_load_kwargs(model_dir: Path, device: str) -> dict[str, object]:
    return diffusers_weight_load_kwargs(model_dir, device)


def _reraise_video_model_load_error(exc: Exception, model_dir: Path) -> None:
    message = str(exc).lower()
    if "git-lfs" in message or "git lfs" in message:
        raise UserFacingError(
            "Internal video model snapshot contains Git LFS pointer files",
            hint=(
                f"The Diffusers snapshot at {model_dir} has placeholder weight files instead of full model weights. "
                "Reinstall the internal base model in Models or run git lfs pull/re-sync for that snapshot, then retry."
            ),
            code="INTERNAL_VIDEO_MODEL_LFS_POINTER",
            status_code=400,
        ) from exc
    raise exc


def _load_svd_pipeline(model_dir: Path, *, device: str, dtype: str, cpu_offload: bool):
    try:
        from diffusers import StableVideoDiffusionPipeline  # type: ignore
    except Exception as exc:
        raise UserFacingError(
            "Internal SVD video support is not installed",
            hint="Install the Studio backend internal dependencies, then install the internal SVD video model from Models.",
            code="INTERNAL_VIDEO_MODEL_DEPS",
            status_code=500,
        ) from exc

    key = ("svd", str(model_dir), device, dtype)
    cached = _VIDEO_PIPELINE_CACHE.get(key)
    if cached is not None:
        return cached

    load_kwargs: dict[str, Any] = {"torch_dtype": _parse_torch_dtype(dtype, device)}
    load_kwargs.update(_video_model_base_load_kwargs(model_dir, device))
    try:
        pipe = StableVideoDiffusionPipeline.from_pretrained(str(model_dir), **load_kwargs)
    except Exception as exc:
        _reraise_video_model_load_error(exc, model_dir)
    pipe = _optimize_pipeline(pipe, device, cpu_offload=cpu_offload)
    _VIDEO_PIPELINE_CACHE[key] = pipe
    return pipe


def _load_animatediff_pipeline(
    *,
    adapter_dir: Path,
    base_model_dir: Path,
    device: str,
    dtype: str,
    cpu_offload: bool,
):
    try:
        from diffusers import AnimateDiffPipeline, MotionAdapter  # type: ignore
    except Exception as exc:
        raise UserFacingError(
            "Internal AnimateDiff support is not installed",
            hint="Upgrade/install diffusers with AnimateDiff support, then install the internal AnimateDiff motion adapter from Models.",
            code="INTERNAL_VIDEO_MODEL_DEPS",
            status_code=500,
        ) from exc

    key = ("animatediff", f"{base_model_dir}|{adapter_dir}", device, dtype)
    cached = _VIDEO_PIPELINE_CACHE.get(key)
    if cached is not None:
        return cached

    torch_dtype = _parse_torch_dtype(dtype, device)
    try:
        adapter = MotionAdapter.from_pretrained(str(adapter_dir), torch_dtype=torch_dtype)
    except Exception as exc:
        _reraise_video_model_load_error(exc, adapter_dir)
    load_kwargs: dict[str, Any] = {
        "motion_adapter": adapter,
        "torch_dtype": torch_dtype,
        "safety_checker": None,
        "requires_safety_checker": False,
    }
    load_kwargs.update(_video_model_base_load_kwargs(base_model_dir, device))
    try:
        pipe = AnimateDiffPipeline.from_pretrained(str(base_model_dir), **load_kwargs)
    except Exception as exc:
        _reraise_video_model_load_error(exc, base_model_dir)
    pipe = _optimize_pipeline(pipe, device, cpu_offload=cpu_offload)
    _VIDEO_PIPELINE_CACHE[key] = pipe
    return pipe


def generate_video_model_frames(
    *,
    engine: str,
    video_model_dir: Path,
    base_model_dir: Path,
    init_image: Any | None,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    steps: int,
    cfg: float,
    seed: int | None,
    device: str,
    dtype: str = "auto",
    motion_bucket_id: int = 127,
    noise_aug_strength: float = 0.02,
    decode_chunk_size: int = 8,
    cpu_offload: bool = False,
) -> list[Any]:
    """Generate PIL frames with an internal Diffusers video model.

    SVD is image-to-video and uses ``init_image``. AnimateDiff is text-to-video
    through a motion adapter and uses the internal SD1.5 base model.
    """
    if num_frames <= 0:
        return []
    if not video_model_dir.exists():
        raise UserFacingError(
            "Internal video model is not installed",
            hint="Open Models and install an internal SVD or AnimateDiff video model, then retry.",
            code="INTERNAL_VIDEO_MODEL_NOT_INSTALLED",
            status_code=400,
        )

    engine_l = str(engine or "svd").strip().lower()
    dtype_l = "float16" if str(dtype or "auto").strip().lower() == "auto" and device == "cuda" else str(dtype or "float32")
    generator, used_seed = _seeded_generator(seed, device)

    if engine_l == "svd":
        if init_image is None:
            raise UserFacingError(
                "SVD needs an input keyframe",
                hint="Run internal video with generated keyframes enabled, or provide a source image.",
                code="INTERNAL_VIDEO_MODEL_INPUT_MISSING",
                status_code=400,
            )
        pipe = _load_svd_pipeline(video_model_dir, device=device, dtype=dtype_l, cpu_offload=cpu_offload)
        image = init_image.convert("RGB").resize((int(width), int(height)))
        kwargs = {
            "image": image,
            "num_frames": int(num_frames),
            "num_inference_steps": int(steps),
            "generator": generator,
            "motion_bucket_id": int(motion_bucket_id),
            "noise_aug_strength": float(noise_aug_strength),
            "decode_chunk_size": int(decode_chunk_size),
        }
        try:
            kwargs["fps"] = int(fps)
            kwargs["min_guidance_scale"] = max(1.0, float(cfg) * 0.65)
            kwargs["max_guidance_scale"] = max(float(cfg), float(cfg) * 1.15)
            result = pipe(**kwargs)
        except TypeError:
            kwargs.pop("fps", None)
            kwargs.pop("min_guidance_scale", None)
            kwargs.pop("max_guidance_scale", None)
            kwargs["guidance_scale"] = float(cfg)
            result = pipe(**kwargs)
        frames = _normalize_frames(result)
        if not frames:
            raise RuntimeError(f"SVD returned no frames (seed={used_seed}).")
        return _to_rgb_frames(frames, width=width, height=height)

    if engine_l == "animatediff":
        pipe = _load_animatediff_pipeline(
            adapter_dir=video_model_dir,
            base_model_dir=base_model_dir,
            device=device,
            dtype=dtype_l,
            cpu_offload=cpu_offload,
        )
        result = pipe(
            prompt=str(prompt or "cinematic subject motion"),
            negative_prompt=str(negative_prompt or ""),
            num_frames=int(num_frames),
            num_inference_steps=int(steps),
            guidance_scale=float(cfg),
            generator=generator,
            width=int(width),
            height=int(height),
        )
        frames = _normalize_frames(result)
        if not frames:
            raise RuntimeError(f"AnimateDiff returned no frames (seed={used_seed}).")
        return _to_rgb_frames(frames, width=width, height=height)

    raise UserFacingError(
        f"Unknown internal video model engine: {engine}",
        hint="Choose auto, svd, or animatediff.",
        code="INTERNAL_VIDEO_MODEL_ENGINE_UNKNOWN",
        status_code=400,
    )
