from __future__ import annotations

import base64
import json
import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ..errors import UserFacingError


DEFAULT_SD15_BASE_MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"


def _runtime_store():
    from .. import app as studio_app

    return studio_app.store


def _runtime_jobs():
    from .. import app as studio_app

    return studio_app.jobs


def _update_progress(
    project_id: str,
    job_id: str | None,
    *,
    stage: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if not job_id:
        return
    jobs = _runtime_jobs()
    job = jobs.get(project_id, job_id)
    if not job:
        return
    total = max(1, int(total))
    job.progress = {
        "stage": stage,
        "current": int(current),
        "total": total,
        "percent": max(0.0, min(1.0, float(current) / float(total))),
        "message": message,
    }
    jobs.save(job)


def _existing_path(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
    except Exception:
        return None
    return path if path.exists() else None


def _resolve_bundle_dir(model_id: str | None, payload: dict[str, Any]) -> Path:
    for key in ("model_path", "bundle_path", "source_path"):
        path = _existing_path(payload.get(key))
        if path is not None:
            return path

    model_path = _existing_path(model_id)
    if model_path is not None:
        return model_path

    for env_name in ("EDMG_TENSORRT_SD15_BUNDLE", "EDMG_TENSORRT_MODEL_DIR"):
        path = _existing_path(os.getenv(env_name))
        if path is not None:
            return path

    raise UserFacingError(
        f"TensorRT model {model_id or '(none)'} is not installed.",
        hint=(
            "Install or import a TensorRT runtime bundle in Models, or set "
            "EDMG_TENSORRT_SD15_BUNDLE to a folder containing engine/ and onnx/."
        ),
        code="TRT_MODEL_NOT_FOUND",
        status_code=400,
    )


def _find_unet_engine(bundle_dir: Path) -> Path:
    candidates = [
        bundle_dir / "engine" / "unet.engine",
        bundle_dir / "engine" / "unet.plan",
        bundle_dir / "engine" / "unet_b1_workspace4096.engine",
    ]
    engine_dir = bundle_dir / "engine"
    if engine_dir.exists():
        candidates.extend(sorted(engine_dir.glob("*unet*.engine")))
        candidates.extend(sorted(engine_dir.glob("*unet*.plan")))
        candidates.extend(sorted(engine_dir.glob("*.engine")))
        candidates.extend(sorted(engine_dir.glob("*.plan")))
    candidates.extend(sorted(bundle_dir.rglob("*.engine")))
    candidates.extend(sorted(bundle_dir.rglob("*.plan")))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue

    raise UserFacingError(
        f"No usable UNet .engine or .plan file found in {bundle_dir}.",
        hint="The failed 0-byte unet.engine is ignored. Build or copy a non-empty TensorRT UNet engine into the bundle's engine folder.",
        code="TRT_ENGINE_NOT_FOUND",
        status_code=400,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _infer_base_model_ref(bundle_dir: Path, payload: dict[str, Any]) -> str:
    explicit_path = str(payload.get("base_model_path") or "").strip()
    if explicit_path:
        return explicit_path

    config = _read_json(bundle_dir / "onnx" / "unet" / "config.json")
    name_or_path = str(config.get("_name_or_path") or "").strip()
    if name_or_path:
        path = Path(name_or_path)
        if path.name == "unet":
            path = path.parent
        if path.exists() and (path / "model_index.json").exists():
            return str(path)

    explicit_model_id = str(payload.get("base_model_id") or "").strip()
    if explicit_model_id:
        return explicit_model_id

    env_model = str(os.getenv("EDMG_TENSORRT_BASE_MODEL") or "").strip()
    return env_model or DEFAULT_SD15_BASE_MODEL


def _component_ref(base_model_ref: str, subfolder: str) -> tuple[str, dict[str, Any]]:
    base_path = Path(base_model_ref)
    if base_path.exists():
        return str(base_path / subfolder), {}
    return base_model_ref, {"subfolder": subfolder}


def _compiled_profile_size(bundle_dir: Path) -> tuple[int, int]:
    config = _read_json(bundle_dir / "onnx" / "unet" / "config.json")
    sample_size = int(config.get("sample_size") or 64)
    return sample_size * 8, sample_size * 8


def _validate_profile(bundle_dir: Path, payload: dict[str, Any]) -> tuple[int, int]:
    profile_width, profile_height = _compiled_profile_size(bundle_dir)
    width = int(payload.get("width") or profile_width)
    height = int(payload.get("height") or profile_height)
    if width != profile_width or height != profile_height:
        raise UserFacingError(
            "TensorRT engine profile does not match the requested image size.",
            hint=(
                f"This bundle was compiled for {profile_width}x{profile_height}. "
                f"Set the Render size to {profile_width}x{profile_height}, or rebuild the engine for {width}x{height}."
            ),
            code="TRT_PROFILE_MISMATCH",
            status_code=400,
        )
    if int(payload.get("batch_size") or 1) != 1:
        raise UserFacingError(
            "This TensorRT engine was compiled for batch size 1.",
            hint="Set TRT Batch Size to 1, or rebuild the engine with a larger max batch profile.",
            code="TRT_BATCH_UNSUPPORTED",
            status_code=400,
        )
    return width, height


def _prompt_from_project(project_id: str, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("prompt") or "").strip()
    if explicit:
        return explicit

    proj = _runtime_store().get(project_id)
    plan = (proj.meta.get("last_plan") if proj else {}) or {}
    variants = plan.get("variants") if isinstance(plan, dict) else []
    variant_index = int(payload.get("variant_index") or 0)
    if isinstance(variants, list) and 0 <= variant_index < len(variants):
        variant = variants[variant_index] if isinstance(variants[variant_index], dict) else {}
        scenes = variant.get("scenes") if isinstance(variant, dict) else []
        if isinstance(scenes, list) and scenes:
            scene = scenes[0] if isinstance(scenes[0], dict) else {}
            prompt = str(scene.get("prompt_pack") or scene.get("prompt") or "").strip()
            if prompt:
                return prompt
    return "cinematic music video keyframe, detailed, high quality"


def _load_scheduler(bundle_dir: Path, base_model_ref: str, sampler: str):
    from diffusers import DDIMScheduler, DPMSolverMultistepScheduler, EulerDiscreteScheduler, PNDMScheduler

    sampler_name = str(sampler or "").strip().lower()
    config = _read_json(bundle_dir / "onnx" / "scheduler" / "scheduler_config.json")
    class_name = str(config.get("_class_name") or "PNDMScheduler")
    scheduler_cls: Any
    if sampler_name in {"euler", "euler_ancestral"}:
        scheduler_cls = EulerDiscreteScheduler
    elif sampler_name.startswith("dpm"):
        scheduler_cls = DPMSolverMultistepScheduler
    elif sampler_name == "ddim":
        scheduler_cls = DDIMScheduler
    else:
        scheduler_cls = {
            "DDIMScheduler": DDIMScheduler,
            "DPMSolverMultistepScheduler": DPMSolverMultistepScheduler,
            "EulerDiscreteScheduler": EulerDiscreteScheduler,
            "PNDMScheduler": PNDMScheduler,
        }.get(class_name, PNDMScheduler)

    scheduler_dir = bundle_dir / "onnx" / "scheduler"
    if scheduler_dir.exists():
        return scheduler_cls.from_pretrained(str(scheduler_dir))
    ref, kwargs = _component_ref(base_model_ref, "scheduler")
    return scheduler_cls.from_pretrained(ref, **kwargs)


def _encode_prompt(
    *,
    base_model_ref: str,
    prompt: str,
    negative_prompt: str,
    device: str,
    dtype: Any,
):
    import torch
    from transformers import CLIPTextModel, CLIPTokenizer

    tokenizer_ref, tokenizer_kwargs = _component_ref(base_model_ref, "tokenizer")
    text_ref, text_kwargs = _component_ref(base_model_ref, "text_encoder")
    tokenizer = CLIPTokenizer.from_pretrained(tokenizer_ref, **tokenizer_kwargs)
    text_encoder = CLIPTextModel.from_pretrained(text_ref, torch_dtype=dtype, **text_kwargs)
    text_encoder = text_encoder.to(device)

    def encode(text: str):
        tokens = tokenizer(
            text,
            padding="max_length",
            max_length=tokenizer.model_max_length,
            truncation=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            return text_encoder(tokens.input_ids.to(device))[0].to(dtype=dtype)

    prompt_embeds = encode(prompt)
    negative_embeds = encode(negative_prompt)
    del text_encoder
    torch.cuda.empty_cache()
    return prompt_embeds, negative_embeds


class _TRTUnetRunner:
    def __init__(self, engine_path: Path, device: str):
        import tensorrt
        import torch

        self.tensorrt = tensorrt
        self.torch = torch
        self.device = device
        self.logger = tensorrt.Logger(tensorrt.Logger.INFO)
        tensorrt.init_libnvinfer_plugins(self.logger, namespace="")
        with open(engine_path, "rb") as f, tensorrt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())
        if not self.engine:
            raise UserFacingError(
                f"Failed to deserialize TensorRT engine from {engine_path.name}",
                hint="Rebuild the engine with the installed TensorRT version on this GPU.",
                code="TRT_DESERIALIZE_FAILED",
                status_code=400,
            )
        self.context = self.engine.create_execution_context()
        self.dtype_map = {
            tensorrt.DataType.FLOAT: torch.float32,
            tensorrt.DataType.HALF: torch.float16,
            tensorrt.DataType.INT32: torch.int32,
            tensorrt.DataType.INT8: torch.int8,
            tensorrt.DataType.BOOL: torch.bool,
        }

    def close(self) -> None:
        if getattr(self, "context", None) is not None:
            del self.context
            self.context = None
        if getattr(self, "engine", None) is not None:
            del self.engine
            self.engine = None

    def __del__(self):
        self.close()

    def _coerce_input(self, name: str, tensor):
        expected_shape = tuple(self.engine.get_tensor_shape(name))
        dtype = self.dtype_map.get(self.engine.get_tensor_dtype(name), tensor.dtype)
        if name == "timestep" and len(expected_shape) == 0 and tensor.numel() == 1:
            tensor = tensor.reshape(())
        elif name == "timestep" and tensor.ndim == 0:
            tensor = tensor.reshape(1)
        tensor = tensor.to(device=self.device, dtype=dtype)
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()
        return tensor

    def run(self, *, sample, timestep, encoder_hidden_states):
        torch = self.torch
        trt = self.tensorrt
        inputs = {
            "sample": sample,
            "timestep": timestep,
            "encoder_hidden_states": encoder_hidden_states,
        }
        output_buffers: dict[str, Any] = {}

        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            mode = self.engine.get_tensor_mode(name)
            if mode == trt.TensorIOMode.INPUT:
                tensor = inputs.get(name)
                if tensor is None:
                    raise UserFacingError(
                        f"TensorRT engine input '{name}' is not supported by the SD1.5 renderer.",
                        hint="Use an SD1.5 UNet engine exported from Diffusers/Optimum with sample, timestep, and encoder_hidden_states inputs.",
                        code="TRT_INPUT_UNSUPPORTED",
                        status_code=400,
                    )
                tensor = self._coerce_input(name, tensor)
                engine_shape = tuple(self.engine.get_tensor_shape(name))
                if len(engine_shape) == len(tuple(tensor.shape)):
                    self.context.set_input_shape(name, tuple(tensor.shape))
                self.context.set_tensor_address(name, tensor.data_ptr())
                inputs[name] = tensor

        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            mode = self.engine.get_tensor_mode(name)
            if mode != trt.TensorIOMode.OUTPUT:
                continue
            shape = tuple(int(dim) for dim in self.context.get_tensor_shape(name))
            dtype = self.dtype_map.get(self.engine.get_tensor_dtype(name), torch.float16)
            output = torch.empty(shape, dtype=dtype, device=self.device)
            self.context.set_tensor_address(name, output.data_ptr())
            output_buffers[name] = output

        stream = torch.cuda.current_stream().cuda_stream
        if not self.context.execute_async_v3(stream_handle=stream):
            raise UserFacingError(
                "TensorRT UNet execution failed.",
                hint="Check that the engine profile matches the requested image size and TensorRT version.",
                code="TRT_EXECUTION_FAILED",
                status_code=500,
            )
        if "out_sample" in output_buffers:
            return output_buffers["out_sample"]
        if output_buffers:
            return next(iter(output_buffers.values()))
        raise UserFacingError(
            "TensorRT engine did not expose an output tensor.",
            hint="Rebuild the UNet engine and verify it has an out_sample output.",
            code="TRT_OUTPUT_MISSING",
            status_code=400,
        )


def _decode_latents(base_model_ref: str, latents, *, device: str, dtype: Any) -> Image.Image:
    import numpy as np
    import torch
    from diffusers import AutoencoderKL

    vae_ref, vae_kwargs = _component_ref(base_model_ref, "vae")
    vae = AutoencoderKL.from_pretrained(vae_ref, torch_dtype=torch.float32, **vae_kwargs)
    # Decode on CPU for the standalone TensorRT path. The UNet is accelerated by
    # TensorRT; CPU VAE decode avoids CUDA/cuDNN version mismatches in mixed local
    # environments and frees VRAM after the large engine is released.
    vae = vae.to("cpu")
    scale = float(getattr(vae.config, "scaling_factor", 0.18215) or 0.18215)
    latents = latents.detach().to(device="cpu", dtype=torch.float32)
    with torch.no_grad():
        image = vae.decode(latents / scale).sample
    image = (image / 2 + 0.5).clamp(0, 1)
    image = image.detach().cpu().permute(0, 2, 3, 1).float().numpy()[0]
    image = (image * 255).round().astype(np.uint8)
    del vae
    if device == "cuda":
        torch.cuda.empty_cache()
    return Image.fromarray(image)


def _render_sd15_tensorrt(project_id: str, job_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:
        raise UserFacingError(
            "PyTorch is not installed in the backend environment.",
            hint="Install the Studio CUDA backend bundle, then retry TensorRT rendering.",
            code="TRT_TORCH_MISSING",
            status_code=500,
        ) from exc

    if not (getattr(torch, "cuda", None) and torch.cuda.is_available()):
        raise UserFacingError(
            "TensorRT rendering requires CUDA.",
            hint="Use an NVIDIA GPU backend with CUDA available, or render with the internal/proxy path.",
            code="TRT_CUDA_UNAVAILABLE",
            status_code=400,
        )

    model_id = str(payload.get("model_id") or "").strip()
    bundle_dir = _resolve_bundle_dir(model_id, payload)
    engine_path = _find_unet_engine(bundle_dir)
    width, height = _validate_profile(bundle_dir, payload)
    workflow_family = str(payload.get("workflow_family") or "sd15").strip().lower()
    if workflow_family not in {"sd15", "stable-diffusion-v1-5", "stable_diffusion_v1_5"}:
        raise UserFacingError(
            "This TensorRT renderer currently supports SD1.5 UNet engines only.",
            hint="Use the local SD1.5 TensorRT bundle, or add a model-specific TensorRT adapter for SDXL/SD3.5.",
            code="TRT_FAMILY_UNSUPPORTED",
            status_code=400,
        )

    prompt = _prompt_from_project(project_id, payload)
    negative_prompt = str(payload.get("negative_prompt") or "blurry, low quality, watermark, text, logo")
    steps = max(1, min(80, int(payload.get("steps") or 28)))
    cfg = float(payload.get("cfg") or 7.0)
    seed = payload.get("seed")
    seed_value = int(seed if seed is not None else time.time()) & 0xFFFFFFFF
    sampler = str(payload.get("sampler") or "pndm")
    base_model_ref = _infer_base_model_ref(bundle_dir, payload)

    device = "cuda"
    dtype = torch.float16
    total = steps + 4
    _update_progress(
        project_id,
        job_id,
        stage="loading",
        current=0,
        total=total,
        message=f"Loading SD1.5 text encoder for TensorRT render ({Path(base_model_ref).name or base_model_ref})",
    )

    prompt_embeds, negative_embeds = _encode_prompt(
        base_model_ref=base_model_ref,
        prompt=prompt,
        negative_prompt=negative_prompt,
        device=device,
        dtype=dtype,
    )

    scheduler = _load_scheduler(bundle_dir, base_model_ref, sampler)
    scheduler.set_timesteps(steps, device=device)
    generator = torch.Generator(device=device).manual_seed(seed_value)
    latents = torch.randn(
        (1, 4, height // 8, width // 8),
        generator=generator,
        device=device,
        dtype=dtype,
    )
    latents = latents * scheduler.init_noise_sigma

    _update_progress(
        project_id,
        job_id,
        stage="loading",
        current=1,
        total=total,
        message=f"Deserializing TensorRT UNet engine: {engine_path.name}",
    )
    runner = _TRTUnetRunner(engine_path, device)
    try:
        for index, timestep in enumerate(scheduler.timesteps):
            latent_model_input = scheduler.scale_model_input(latents, timestep)
            timestep_tensor = timestep
            if not torch.is_tensor(timestep_tensor):
                timestep_tensor = torch.tensor([float(timestep)], device=device, dtype=dtype)
            if torch.is_tensor(timestep_tensor) and timestep_tensor.ndim == 0:
                timestep_tensor = timestep_tensor.reshape(1)

            with torch.no_grad():
                if cfg > 1.0:
                    noise_uncond = runner.run(
                        sample=latent_model_input,
                        timestep=timestep_tensor,
                        encoder_hidden_states=negative_embeds,
                    )
                    noise_text = runner.run(
                        sample=latent_model_input,
                        timestep=timestep_tensor,
                        encoder_hidden_states=prompt_embeds,
                    )
                    noise_pred = noise_uncond + cfg * (noise_text - noise_uncond)
                else:
                    noise_pred = runner.run(
                        sample=latent_model_input,
                        timestep=timestep_tensor,
                        encoder_hidden_states=prompt_embeds,
                    )
                latents = scheduler.step(noise_pred, timestep, latents).prev_sample

            _update_progress(
                project_id,
                job_id,
                stage="denoising",
                current=index + 2,
                total=total,
                message=f"TensorRT denoising step {index + 1}/{steps}",
            )
    finally:
        runner.close()
        del runner
        torch.cuda.empty_cache()

    _update_progress(
        project_id,
        job_id,
        stage="decoding",
        current=steps + 2,
        total=total,
        message="Decoding TensorRT latents with SD1.5 VAE",
    )
    image = _decode_latents(base_model_ref, latents, device=device, dtype=dtype)

    out_dir = _runtime_store().project_dir(project_id) / "renders" / "tensorrt"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"trt_sd15_{int(time.time())}_{seed_value}.png"
    image.save(out_file)

    _update_progress(
        project_id,
        job_id,
        stage="finished",
        current=total,
        total=total,
        message="TensorRT SD1.5 render complete",
    )
    return {
        "ok": True,
        "engine_used": str(engine_path),
        "bundle_dir": str(bundle_dir),
        "base_model": base_model_ref,
        "output_path": str(out_file),
        "prompt": prompt,
        "seed": seed_value,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg,
    }


def run_job(project_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a standalone SD1.5 TensorRT image generation job."""
    proj = _runtime_store().get(project_id)
    if not proj:
        raise UserFacingError("Project not found")
    if not payload.get("model_id") and not payload.get("model_path"):
        raise UserFacingError("No model_id specified for TensorRT render")
    return _render_sd15_tensorrt(project_id, job_id, payload)


def run_preview(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a small synchronous SD1.5 TensorRT preview."""
    preview_payload = dict(payload)
    preview_payload["steps"] = min(int(preview_payload.get("steps") or 4), 4)
    result = _render_sd15_tensorrt(project_id, None, preview_payload)
    img = Image.open(result["output_path"]).convert("RGB")
    img.thumbnail((512, 512))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "ok": True,
        "engine_used": result["engine_used"],
        "image": f"data:image/jpeg;base64,{b64_image}",
        "output_path": result["output_path"],
    }
