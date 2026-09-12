from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import random
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..errors import UserFacingError
from .model_weights import diffusers_weight_load_kwargs

logger = logging.getLogger(__name__)

_VIDEO_PIPELINE_CACHE: dict[tuple[str, str, str, str], Any] = {}

SVD_CONDITIONING_FPS = 7
SVD_MIN_GUIDANCE_SCALE = 1.0
SVD_MAX_GUIDANCE_SCALE = 3.0
ANIMATEDIFF_MAX_GUIDANCE_SCALE = 7.5
HUNYUAN_DEFAULT_FPS = 24
HUNYUAN_ENV_PREFIX = "EDMG_HUNYUAN15_"
HUNYUAN_COMPANIONS = {
    "llm": ("LLM_PATH", ("config.json",)),
    "byt5": ("BYT5_PATH", ("config.json",)),
    "glyph": (
        "GLYPH_PATH",
        ("assets/color_idx.json", "assets/multilingual_10-lang_idx.json", "checkpoints/byt5_model.pt"),
    ),
    "vision": ("VISION_PATH", ("image_encoder/config.json", "feature_extractor/preprocessor_config.json")),
}


@dataclass(frozen=True)
class HunyuanRunnerConfig:
    mode: str
    python: str
    repo: str
    distro: str | None
    timeout_s: float
    companions: Mapping[str, str]


def hunyuan_runner_config(environ: Mapping[str, str] | None = None) -> HunyuanRunnerConfig:
    env = os.environ if environ is None else environ
    mode = str(env.get(f"{HUNYUAN_ENV_PREFIX}RUNNER") or "").strip().lower()
    timeout_raw = str(env.get(f"{HUNYUAN_ENV_PREFIX}TIMEOUT_SECONDS") or "3600")
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 0
    return HunyuanRunnerConfig(
        mode=mode,
        python=str(env.get(f"{HUNYUAN_ENV_PREFIX}PYTHON") or "").strip(),
        repo=str(env.get(f"{HUNYUAN_ENV_PREFIX}REPO") or "").strip(),
        distro=str(env.get(f"{HUNYUAN_ENV_PREFIX}WSL_DISTRO") or "").strip() or None,
        timeout_s=timeout_s,
        companions={key: str(env.get(f"{HUNYUAN_ENV_PREFIX}{name}") or "").strip()
                    for key, (name, _required) in HUNYUAN_COMPANIONS.items()},
    )


def _runner_prefix(config: HunyuanRunnerConfig) -> list[str]:
    if config.mode == "wsl":
        command = ["wsl.exe"]
        if config.distro:
            command.extend(["--distribution", config.distro])
        return [*command, "--exec"]
    return []


HUNYUAN_CONFIG_FIELDS = {
    "mode": "RUNNER",
    "python": "PYTHON",
    "repo": "REPO",
    "distro": "WSL_DISTRO",
    "timeout_s": "TIMEOUT_SECONDS",
    **{key: env_name for key, (env_name, _required) in HUNYUAN_COMPANIONS.items()},
}


def _launcher_env_path() -> Path:
    override = os.getenv("EDMG_LAUNCHER_ENV", "").strip()
    return Path(override).expanduser() if override else Path(__file__).resolve().parents[3] / "launcher_env.json"


def hunyuan_runner_status(*, probe: bool = False) -> dict[str, Any]:
    config = hunyuan_runner_config()
    issues = validate_hunyuan_runner(probe=probe)
    return {
        "config": {
            "mode": config.mode,
            "python": config.python,
            "repo": config.repo,
            "distro": config.distro or "",
            "timeout_s": config.timeout_s,
            **config.companions,
        },
        "issues": issues,
        "ready": not issues,
        "probe_requested": probe,
    }


def update_hunyuan_runner_config(values: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, str] = {}
    for field, env_name in HUNYUAN_CONFIG_FIELDS.items():
        if field not in values:
            continue
        value = values[field]
        if field == "timeout_s":
            try:
                timeout_s = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("timeout_s must be a positive number") from exc
            if not 0 < timeout_s <= 86400:
                raise ValueError("timeout_s must be between 1 and 86400 seconds")
            text = str(timeout_s)
        else:
            text = str(value or "").strip()
            if len(text) > 2048:
                raise ValueError(f"{field} cannot exceed 2048 characters")
            if field == "mode" and text.lower() not in {"", "wsl", "external"}:
                raise ValueError("mode must be 'wsl' or 'external'")
            if field == "distro" and len(text) > 128:
                raise ValueError("distro cannot exceed 128 characters")
        updates[f"{HUNYUAN_ENV_PREFIX}{env_name}"] = text

    path = _launcher_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Launcher configuration is not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("Launcher configuration must contain a JSON object")
        data = loaded
    data.update(updates)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    for key, value in updates.items():
        os.environ[key] = value
    return hunyuan_runner_status(probe=False)


def _wsl_path(path: Path | str, config: HunyuanRunnerConfig) -> str:
    value = str(path)
    if config.mode != "wsl":
        return value
    if value.startswith("/"):
        return value
    proc = subprocess.run(
        [*_runner_prefix(config), "wslpath", "-a", value], capture_output=True, text=True, timeout=30, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = (proc.stderr or proc.stdout or "wslpath returned no path").strip()
        raise RuntimeError(f"Could not map Windows path into WSL: {detail[-1000:]}")
    return proc.stdout.strip()


def validate_hunyuan_runner(*, probe: bool = True) -> list[str]:
    config = hunyuan_runner_config()
    issues: list[str] = []
    if config.mode not in {"wsl", "external"}:
        issues.append(f"Set {HUNYUAN_ENV_PREFIX}RUNNER to 'wsl' or 'external'.")
    if not config.python:
        issues.append(f"Set {HUNYUAN_ENV_PREFIX}PYTHON to the Linux Python executable.")
    if not config.repo:
        issues.append(f"Set {HUNYUAN_ENV_PREFIX}REPO to the official HunyuanVideo-1.5 checkout.")
    if config.mode == "wsl" and shutil.which("wsl.exe") is None:
        issues.append("wsl.exe is unavailable; install WSL2 or select the external runner.")
    if config.timeout_s <= 0:
        issues.append(f"{HUNYUAN_ENV_PREFIX}TIMEOUT_SECONDS must be positive.")
    for key, (env_name, _required) in HUNYUAN_COMPANIONS.items():
        if not config.companions[key]:
            issues.append(f"Set {HUNYUAN_ENV_PREFIX}{env_name} to the separately downloaded {key} assets.")
    if issues or not probe:
        return issues
    script = (
        "import importlib.util,json,os,sys;"
        "required=json.loads(sys.argv[1]);"
        "missing=[p for p in required if not os.path.isfile(p)];"
        "repo=sys.argv[2];"
        "sys.path.insert(0,repo);"
        "mods=[m for m in ('torch','hyvideo','imageio','einops') if importlib.util.find_spec(m) is None];"
        "missing += ([] if os.path.isfile(os.path.join(repo,'hyvideo','pipelines','hunyuan_video_pipeline.py')) else [repo]);"
        "print(json.dumps({'missing':missing,'modules':mods}));"
        "raise SystemExit(bool(missing or mods))"
    )
    required: list[str] = []
    for key, (_env_name, names) in HUNYUAN_COMPANIONS.items():
        root = config.companions[key]
        path_type = PurePosixPath if config.mode in {"wsl", "external"} and root.startswith("/") else Path
        required.extend(str(path_type(root) / name) for name in names)
    try:
        mapped_required = [_wsl_path(path, config) for path in required]
        command = [*_runner_prefix(config), config.python, "-c", script,
                   json.dumps(mapped_required), _wsl_path(config.repo, config)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return [f"Hunyuan Linux runner probe failed: {exc}"]
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "probe failed without output").strip()[-2000:]
        issues.append(f"Hunyuan Linux environment is incomplete: {detail}")
    return issues


def validate_video_model_layout(engine: str, model_dir: Path) -> None:
    """Reject mismatched or incomplete internal video assets before loading Diffusers."""

    engine_l = str(engine or "").strip().lower()
    model_dir = Path(model_dir)
    if engine_l == "ltx_25":
        from .engine_packages import MANIFESTS, validate_package
        result = validate_package(model_dir, MANIFESTS["hf_ltx_25_distilled_internal"])
        if not result["valid"]:
            raise UserFacingError("LTX-2.5 package is incomplete", hint="; ".join(result["issues"]),
                                  code="INTERNAL_VIDEO_MODEL_LAYOUT_INVALID", status_code=400)
        return
    if engine_l not in {"svd", "animatediff", "hunyuan_video15"}:
        raise UserFacingError(
            f"Unknown internal video model engine: {engine}",
            hint="Choose auto, SVD image-to-video, AnimateDiff SD1.5, or HunyuanVideo-1.5.",
            code="INTERNAL_VIDEO_MODEL_ENGINE_UNKNOWN",
            status_code=400,
        )

    if not model_dir.is_dir():
        raise UserFacingError(
            "Internal video model is not installed",
            hint="Open Models and install the selected internal video model, then retry.",
            code="INTERNAL_VIDEO_MODEL_NOT_INSTALLED",
            status_code=400,
        )

    if engine_l == "hunyuan_video15":
        config_names = ("config.json",)
    elif engine_l == "svd":
        config_names = ("model_index.json",)
    elif engine_l == "animatediff":
        config_names = ("config.json",)
    else:
        config_names = ("config.json",)
    config_name = next((name for name in config_names if (model_dir / name).is_file()), config_names[0])
    config_path = model_dir / config_name
    if not config_path.is_file():
        model_label = {
            "svd": "SVD pipeline",
            "animatediff": "AnimateDiff motion adapter",
            "hunyuan_video15": "HunyuanVideo-1.5 pipeline",
        }[engine_l]
        raise UserFacingError(
            f"Selected internal video model is not a complete {model_label}",
            hint=(
                f"Open Models and reinstall the {model_label}. The selected folder is missing "
                f"{', '.join(config_names)}, so Studio will not start the render."
            ),
            code="INTERNAL_VIDEO_MODEL_LAYOUT_INVALID",
            status_code=400,
        )

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserFacingError(
            "Selected internal video model has an unreadable configuration",
            hint=f"Open Models and reinstall the selected video model; {config_name} is invalid.",
            code="INTERNAL_VIDEO_MODEL_LAYOUT_INVALID",
            status_code=400,
        ) from exc

    class_name = str(config.get("_class_name") or "") if isinstance(config, dict) else ""
    expected_class = {
        "svd": "StableVideoDiffusionPipeline",
        "animatediff": "MotionAdapter",
        "hunyuan_video15": "HunyuanVideo15Pipeline",
    }[engine_l]
    class_matches = (
        expected_class.lower() in class_name.lower()
        if engine_l != "hunyuan_video15"
        else class_name == "HunyuanVideo_1_5_Pipeline"
    )
    if not class_matches:
        raise UserFacingError(
            "Selected internal video model does not match the adapter engine",
            hint=(
                f"The {engine_l} engine expected {expected_class}, but the selected model declares "
                f"{class_name}. Choose the matching video model and retry."
            ),
            code="INTERNAL_VIDEO_MODEL_ENGINE_MODEL_MISMATCH",
            status_code=400,
        )

    if engine_l == "animatediff":
        weight_files = [
            path
            for path in model_dir.glob("diffusion_pytorch_model*")
            if path.is_file() and path.name != config_name
        ]
        if not weight_files:
            raise UserFacingError(
                "Selected AnimateDiff motion adapter is incomplete",
                hint=(
                    "Open Models and reinstall AnimateDiff Motion Adapter. The selected folder "
                    "does not contain its diffusion_pytorch_model weights."
                ),
                code="INTERNAL_VIDEO_MODEL_LAYOUT_INVALID",
                status_code=400,
            )


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


def clear_video_pipeline_cache() -> None:
    _VIDEO_PIPELINE_CACHE.clear()


def _cleanup_cuda(device: str) -> None:
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


def _is_cuda_out_of_memory(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "cuda out of memory" in message
        or "torch.cuda.outofmemoryerror" in message
        or ("out of memory" in message and "cuda" in message)
    )


def _raise_cuda_oom(engine: str, exc: Exception) -> None:
    clear_video_pipeline_cache()
    raise UserFacingError(
        f"Internal {engine} video model ran out of CUDA memory",
        hint=(
            "Studio will fit 6 GB CUDA best with CPU offload, 8-12 frames per scene, "
            "20-25 temporal steps, and a conservative adapter canvas near 640x360. "
            "Reduce canvas size or frames per scene before reducing denoising quality."
        ),
        code="INTERNAL_VIDEO_MODEL_CUDA_OOM",
        status_code=400,
    ) from exc


def _normalize_frames(raw_frames: Any) -> list[Any]:
    frames = raw_frames
    if hasattr(frames, "frames"):
        frames = frames.frames
    if frames is None:
        return []
    if isinstance(frames, (list, tuple)) and frames and isinstance(frames[0], (list, tuple)):
        frames = frames[0]
    # Diffusers normally returns PIL output as [batch][time]. Explicit PIL
    # output below keeps that contract, but accepting an array/tensor batch here
    # makes the adapter fail predictably if a future pipeline changes defaults.
    ndim = getattr(frames, "ndim", None)
    if isinstance(ndim, int) and ndim == 5:
        frames = frames[0]
    try:
        return list(frames)
    except TypeError as exc:
        raise RuntimeError("Internal video model returned a non-iterable frame payload.") from exc


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
    # Diffusers on PyTorch 2.x uses AttnProcessor2_0/SDPA by default. Calling
    # enable_attention_slicing() replaces that processor with a sliced
    # implementation and can make video denoising dramatically slower. Keep
    # native SDPA unless a separately installed xFormers backend is selected.
    if hasattr(pipe, "enable_vae_slicing"):
        try:
            pipe.enable_vae_slicing()
        except Exception as exc:
            logger.debug("Unable to enable VAE slicing for internal video pipeline: %s", exc)
    if hasattr(pipe, "enable_vae_tiling"):
        try:
            pipe.enable_vae_tiling()
        except Exception as exc:
            logger.debug("Unable to enable VAE tiling for internal video pipeline: %s", exc)
    # HunyuanVideo-1.5 exposes tiling on the VAE rather than the pipeline in
    # current Diffusers releases. Keep this capability optional so older SVD
    # and AnimateDiff fakes/runtimes remain compatible.
    vae = getattr(pipe, "vae", None)
    if vae is not None and hasattr(vae, "enable_tiling"):
        try:
            vae.enable_tiling()
        except Exception as exc:
            logger.debug("Unable to enable VAE tiling on internal video VAE: %s", exc)
    if (
        device == "cuda"
        and importlib.util.find_spec("xformers") is not None
        and hasattr(pipe, "enable_xformers_memory_efficient_attention")
    ):
        try:
            pipe.enable_xformers_memory_efficient_attention()
            logger.info("Internal video attention backend: xFormers")
        except Exception as exc:
            logger.warning("xFormers activation failed; retaining PyTorch SDPA: %s", exc)
    elif device == "cuda":
        logger.info("Internal video attention backend: PyTorch SDPA")
    if cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
        try:
            pipe.enable_model_cpu_offload()
            logger.info("Internal video memory strategy: model CPU offload")
            return pipe
        except Exception as exc:
            logger.warning("Model CPU offload failed; trying sequential CPU offload: %s", exc)
    if cpu_offload and hasattr(pipe, "enable_sequential_cpu_offload"):
        try:
            pipe.enable_sequential_cpu_offload()
            logger.warning(
                "Internal video memory strategy: sequential CPU offload; this fallback can be extremely slow"
            )
            return pipe
        except Exception as exc:
            logger.warning("Sequential CPU offload failed; moving the full pipeline to %s: %s", device, exc)
    if hasattr(pipe, "to"):
        pipe = pipe.to(device)
        logger.info("Internal video memory strategy: full pipeline on %s", device)
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

    key = ("svd", str(model_dir), device, f"{dtype}|offload={int(bool(cpu_offload))}")
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
        from diffusers import AnimateDiffPipeline, DDIMScheduler, MotionAdapter  # type: ignore
    except Exception as exc:
        raise UserFacingError(
            "Internal AnimateDiff support is not installed",
            hint="Upgrade/install diffusers with AnimateDiff support, then install the internal AnimateDiff motion adapter from Models.",
            code="INTERNAL_VIDEO_MODEL_DEPS",
            status_code=500,
        ) from exc

    key = ("animatediff", f"{base_model_dir}|{adapter_dir}", device, f"{dtype}|offload={int(bool(cpu_offload))}")
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
    scheduler = getattr(pipe, "scheduler", None)
    scheduler_config = getattr(scheduler, "config", None)
    if scheduler_config is not None:
        pipe.scheduler = DDIMScheduler.from_config(
            scheduler_config,
            beta_schedule="linear",
            timestep_spacing="linspace",
            steps_offset=1,
            clip_sample=False,
        )
    pipe = _optimize_pipeline(pipe, device, cpu_offload=cpu_offload)
    _VIDEO_PIPELINE_CACHE[key] = pipe
    return pipe


def _stop_hunyuan_process(proc: subprocess.Popen[str], config: HunyuanRunnerConfig, pid_file: Path) -> None:
    if proc.poll() is not None:
        return
    if config.mode == "wsl":
        try:
            linux_pid = int(pid_file.read_text(encoding="ascii").strip())
            subprocess.run(
                [*_runner_prefix(config), "kill", "-TERM", str(linux_pid)],
                capture_output=True, timeout=10, check=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _decode_video(path: Path, *, width: int, height: int) -> list[Any]:
    import cv2  # type: ignore
    from PIL import Image  # type: ignore

    capture = cv2.VideoCapture(str(path))
    frames: list[Any] = []
    try:
        if not capture.isOpened():
            raise RuntimeError("HunyuanVideo-1.5 output is not a readable MP4 video")
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(frame).convert("RGB").resize((int(width), int(height))))
    finally:
        capture.release()
    return frames


def _run_hunyuan(
    model_dir: Path, *, init_image: Any | None, prompt: str, negative_prompt: str,
    width: int, height: int, num_frames: int, fps: int, steps: int, cfg: float,
    seed: int, device: str, dtype: str, cpu_offload: bool,
    cancel_check: Callable[[], Any] | None, workspace: Path,
) -> list[Any]:
    issues = validate_hunyuan_runner()
    if issues:
        raise UserFacingError(
            "HunyuanVideo-1.5 Linux runtime is not configured",
            hint="; ".join(issues), code="INTERNAL_VIDEO_MODEL_DEPS", status_code=422,
        )
    config = hunyuan_runner_config()
    if not str(device).lower().startswith("cuda"):
        raise UserFacingError(
            "HunyuanVideo-1.5 requires a CUDA device",
            hint="Select a CUDA device such as cuda:0.", code="INTERNAL_VIDEO_MODEL_DEVICE", status_code=422,
        )
    try:
        gpu_index = int(str(device).split(":", 1)[1]) if ":" in str(device) else 0
    except ValueError as exc:
        raise UserFacingError("Invalid CUDA device", hint="Use cuda:N, for example cuda:0.",
                              code="INTERNAL_VIDEO_MODEL_DEVICE", status_code=422) from exc
    dtype_l = str(dtype).strip().lower()
    dtype_l = {"auto": "bfloat16", "bf16": "bfloat16", "fp16": "float16", "fp32": "float32"}.get(dtype_l, dtype_l)
    if dtype_l not in {"bfloat16", "float16", "float32"}:
        raise UserFacingError("Unsupported Hunyuan dtype", hint="Choose bfloat16, float16, or float32.",
                              code="INTERNAL_VIDEO_MODEL_CONFIG", status_code=422)
    resolution = "480p"
    work = Path(workspace) / ".hunyuan-runs" / uuid.uuid4().hex
    work.mkdir(parents=True)
    request_path = work / "request.json"
    output_path = work / "output.mp4"
    image_path = work / "input.png"
    pid_path = work / "worker.pid"
    try:
        if init_image is not None:
            init_image.convert("RGB").resize((int(width), int(height))).save(image_path)
        request = {
            "mode": "i2v" if init_image is not None else "t2v", "resolution": resolution,
            "prompt": str(prompt or "cinematic subject motion"), "negative_prompt": str(negative_prompt or ""),
            "width": int(width), "height": int(height), "frames": int(num_frames), "fps": int(fps),
            "steps": int(steps), "guidance_scale": float(cfg), "seed": int(seed), "dtype": dtype_l,
            "cpu_offload": bool(cpu_offload), "cfg_distilled": init_image is None,
            "step_distilled": init_image is not None,
            "image": _wsl_path(image_path, config) if init_image is not None else None,
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        backend_root = Path(__file__).resolve().parents[2]
        python_path = os.pathsep.join((config.repo, str(backend_root)))
        command = [*_runner_prefix(config)]
        if config.mode == "wsl":
            python_path = ":".join((_wsl_path(config.repo, config), _wsl_path(backend_root, config)))
            command.extend(["env", f"CUDA_VISIBLE_DEVICES={gpu_index}",
                            "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
                            f"PYTHONPATH={python_path}"])
        command.extend([
            config.python, "-m", "edmg_studio_backend.services.hunyuan_video15_worker",
            "--request", _wsl_path(request_path, config),
            "--model", _wsl_path(model_dir, config), "--llm", _wsl_path(config.companions["llm"], config),
            "--byt5", _wsl_path(config.companions["byt5"], config), "--glyph", _wsl_path(config.companions["glyph"], config),
            "--vision", _wsl_path(config.companions["vision"], config), "--output", _wsl_path(output_path, config),
            "--pid-file", _wsl_path(pid_path, config),
        ])
        child_env = os.environ.copy()
        child_env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
        child_env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        child_env["PYTHONPATH"] = python_path
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=config.mode == "external", env=child_env)
        started = time.monotonic()
        while True:
            try:
                if cancel_check and cancel_check():
                    raise RuntimeError("HunyuanVideo-1.5 generation was cancelled")
                remaining = config.timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError(f"Hunyuan generation exceeded {config.timeout_s:g} seconds")
                stdout, stderr = proc.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
            except BaseException:
                _stop_hunyuan_process(proc, config, pid_path)
                raise
        if proc.returncode:
            detail = (stderr or stdout or "worker exited without diagnostics").strip()[-4000:]
            raise RuntimeError(f"HunyuanVideo-1.5 Linux worker failed ({proc.returncode}): {detail}")
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise RuntimeError("HunyuanVideo-1.5 worker did not produce a non-empty MP4")
        frames = _decode_video(output_path, width=width, height=height)
        if len(frames) != int(num_frames):
            raise RuntimeError(f"HunyuanVideo-1.5 MP4 has {len(frames)} frames; expected {int(num_frames)}")
        return frames
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
    workspace: Path | None = None,
    cancel_check: Any | None = None,
    generation_mode: str = "auto",
    chunk_frames: int | None = None,
    chunk_overlap: int = 2,
    chunk_callback: Callable[[int, int], Any] | None = None,
) -> list[Any]:
    """Generate PIL frames with an internal video model.

    SVD is image-to-video and uses ``init_image``. AnimateDiff is text-to-video
    through a motion adapter and uses the internal SD1.5 base model. Hunyuan
    runs the official native pipeline in an explicitly configured Linux process.
    """
    if num_frames <= 0:
        return []
    if not video_model_dir.exists():
        raise UserFacingError(
            "Internal video model is not installed",
            hint="Open Models and install a qualified internal video model, then retry.",
            code="INTERNAL_VIDEO_MODEL_NOT_INSTALLED",
            status_code=400,
        )

    engine_l = str(engine or "svd").strip().lower()
    if engine_l == "ltx_25":
        from .ltx_25_runtime import generate_ltx_frames

        validate_video_model_layout(engine_l, video_model_dir)
        requested_frames = int(num_frames)
        legal_frames = max(1, ((requested_frames - 1 + 7) // 8) * 8 + 1)
        frames = generate_ltx_frames(
            package_root=video_model_dir,
            workspace=Path(workspace or video_model_dir),
            prompt=prompt,
            width=int(width),
            height=int(height),
            num_frames=legal_frames,
            fps=float(fps),
            seed=int(seed if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)),
            device=device,
            init_image=init_image,
            cpu_offload=cpu_offload,
            fp8=str(dtype or "").strip().lower().startswith("fp8"),
            cancel_check=cancel_check,
        )
        return frames[:requested_frames]
    validate_video_model_layout(engine_l, video_model_dir)
    dtype_l = "float16" if str(dtype or "auto").strip().lower() == "auto" and device == "cuda" else str(dtype or "float32")
    if engine_l == "hunyuan_video15":
        from PIL import Image  # type: ignore

        used_seed = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
        mode = str(generation_mode or "auto").strip().lower()
        if mode not in {"auto", "t2v", "i2v"}:
            raise UserFacingError("Unsupported Hunyuan generation mode", hint="Choose auto, t2v, or i2v.",
                                  code="HUNYUAN_GENERATION_MODE_INVALID", status_code=422)
        if mode == "i2v" and init_image is None:
            raise UserFacingError("Hunyuan I2V requires a source image", hint="Select an existing project image as source_asset.",
                                  code="HUNYUAN_I2V_SOURCE_REQUIRED", status_code=422)
        first_image = None if mode == "t2v" else init_image
        limit = max(2, int(chunk_frames or num_frames))
        overlap_limit = max(0, int(chunk_overlap))
        chunks = max(1, math.ceil(max(0, int(num_frames) - limit) / max(1, limit - overlap_limit)) + 1)
        result: list[Any] = []
        chunk_index = 0
        while len(result) < int(num_frames):
            if cancel_check:
                cancel_check()
            overlap = min(overlap_limit, len(result), limit - 1)
            request_frames = min(limit, int(num_frames) - len(result) + overlap)
            model_frames = max(1, ((request_frames - 1 + 3) // 4) * 4 + 1)
            anchor = first_image if not result else result[-1]
            generated = _run_hunyuan(
                video_model_dir, init_image=anchor, prompt=prompt, negative_prompt=negative_prompt,
                width=width, height=height, num_frames=model_frames, fps=fps or HUNYUAN_DEFAULT_FPS,
                steps=steps, cfg=cfg, seed=used_seed + chunk_index, device=device, dtype=dtype_l,
                cpu_offload=cpu_offload, cancel_check=cancel_check,
                workspace=Path(workspace or video_model_dir),
            )
            if len(generated) != model_frames:
                raise RuntimeError(
                    f"Hunyuan chunk {chunk_index + 1} produced {len(generated)} frames; "
                    f"expected {model_frames}"
                )
            generated = generated[:request_frames]
            if overlap:
                tail = result[-overlap:]
                result[-overlap:] = [
                    Image.blend(old.convert("RGB"), new.convert("RGB"), (index + 1) / (overlap + 1))
                    for index, (old, new) in enumerate(zip(tail, generated[:overlap], strict=True))
                ]
            result.extend(generated[overlap:])
            chunk_index += 1
            if chunk_callback:
                chunk_callback(chunk_index, chunks)
        if len(result) != int(num_frames):
            raise RuntimeError(f"Hunyuan chunk stitching produced {len(result)} frames; expected {int(num_frames)}")
        return result

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
            "output_type": "pil",
        }
        try:
            # SVD's fps value is model micro-conditioning, not the render or
            # export rate. Its guidance schedule is likewise distinct from the
            # still-image CFG control used for storyboard anchors.
            kwargs["fps"] = SVD_CONDITIONING_FPS
            kwargs["min_guidance_scale"] = SVD_MIN_GUIDANCE_SCALE
            kwargs["max_guidance_scale"] = SVD_MAX_GUIDANCE_SCALE
            result = pipe(**kwargs)
        except TypeError:
            kwargs.pop("fps", None)
            kwargs.pop("min_guidance_scale", None)
            kwargs.pop("max_guidance_scale", None)
            kwargs["guidance_scale"] = SVD_MAX_GUIDANCE_SCALE
            try:
                result = pipe(**kwargs)
            except Exception as exc:
                _cleanup_cuda(device)
                if _is_cuda_out_of_memory(exc):
                    _raise_cuda_oom("SVD", exc)
                raise
        except Exception as exc:
            _cleanup_cuda(device)
            if _is_cuda_out_of_memory(exc):
                _raise_cuda_oom("SVD", exc)
            raise
        frames = _normalize_frames(result)
        if not frames:
            raise RuntimeError(f"SVD returned no frames (seed={used_seed}).")
        rgb_frames = _to_rgb_frames(frames, width=width, height=height)
        if len(rgb_frames) != int(num_frames):
            raise RuntimeError(
                f"SVD returned {len(rgb_frames)} frames; expected {int(num_frames)} (seed={used_seed})."
            )
        return rgb_frames

    if engine_l == "animatediff":
        pipe = _load_animatediff_pipeline(
            adapter_dir=video_model_dir,
            base_model_dir=base_model_dir,
            device=device,
            dtype=dtype_l,
            cpu_offload=cpu_offload,
        )
        try:
            result = pipe(
                prompt=str(prompt or "cinematic subject motion"),
                negative_prompt=str(negative_prompt or ""),
                num_frames=int(num_frames),
                num_inference_steps=int(steps),
                # Storyboard CFG schedules can legitimately run hotter for
                # still anchors, but the v1.5-2 motion adapter degrades into
                # oversaturated structure at those values. Preserve lower
                # authored values while enforcing the adapter's quality ceiling.
                guidance_scale=max(1.0, min(float(cfg), ANIMATEDIFF_MAX_GUIDANCE_SCALE)),
                generator=generator,
                width=int(width),
                height=int(height),
                output_type="pil",
            )
        except Exception as exc:
            _cleanup_cuda(device)
            if _is_cuda_out_of_memory(exc):
                _raise_cuda_oom("AnimateDiff", exc)
            raise
        frames = _normalize_frames(result)
        if not frames:
            raise RuntimeError(f"AnimateDiff returned no frames (seed={used_seed}).")
        rgb_frames = _to_rgb_frames(frames, width=width, height=height)
        if len(rgb_frames) != int(num_frames):
            raise RuntimeError(
                f"AnimateDiff returned {len(rgb_frames)} frames; expected {int(num_frames)} (seed={used_seed})."
            )
        return rgb_frames

    raise UserFacingError(
        f"Unknown internal video model engine: {engine}",
        hint="Choose auto, svd, animatediff, or hunyuan_video15.",
        code="INTERNAL_VIDEO_MODEL_ENGINE_UNKNOWN",
        status_code=400,
    )
