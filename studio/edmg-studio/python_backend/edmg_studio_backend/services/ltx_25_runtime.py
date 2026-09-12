"""Isolated adapter for the official Lightricks LTX-2.5 distilled CLI."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import UserFacingError
from .launcher_environment import update_launcher_environment

LTX_PIPELINES_VERSION = "1.3.0"
LTX_PIPELINE_MODULE = "ltx_pipelines.distilled"
LTX_ENV_PREFIX = "EDMG_LTX25_"
_COMPONENT_FLAGS = (
    ("--transformer-path", "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors"),
    ("--text-encoder-path", "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"),
    ("--video-vae-path", "vae/ltx-2.5-video-vae-bf16.safetensors"),
    ("--audio-vae-path", "vae/ltx-2.5-audio-vae-bf16.safetensors"),
    ("--duration-head-path", "model_patches/ltx-2.5-duration-head-bf16.safetensors"),
    ("--spatial-upsampler-path", "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
)


def _runtime_error(message: str, hint: str) -> UserFacingError:
    return UserFacingError(message, hint=hint, code="LTX_25_RUNTIME_ERROR", status_code=422)


@dataclass(frozen=True)
class LtxRuntimeConfig:
    python: str
    timeout_s: float
    smoke_timeout_s: float


def ltx_runtime_config(environ: Mapping[str, str] | None = None) -> LtxRuntimeConfig:
    env = os.environ if environ is None else environ

    def timeout(name: str, fallback: float) -> float:
        try:
            return float(str(env.get(f"{LTX_ENV_PREFIX}{name}") or fallback))
        except ValueError:
            return 0.0

    return LtxRuntimeConfig(
        python=str(env.get(f"{LTX_ENV_PREFIX}PYTHON") or sys.executable).strip(),
        timeout_s=timeout("TIMEOUT_SECONDS", 3600.0),
        smoke_timeout_s=timeout("SMOKE_TIMEOUT_SECONDS", 600.0),
    )


def ltx_runtime_status(*, probe: bool = False) -> dict[str, Any]:
    config = ltx_runtime_config()
    issues: list[str] = []
    executable = Path(config.python).expanduser()
    if not executable.is_file():
        issues.append("Choose the Python executable from the isolated ltx-pipelines 1.3.0 environment.")
    if not 0 < config.timeout_s <= 86400:
        issues.append("Render timeout must be between 1 and 86400 seconds.")
    if not 0 < config.smoke_timeout_s <= 86400:
        issues.append("Smoke-test timeout must be between 1 and 86400 seconds.")
    identity: dict[str, str] | None = None
    if probe and not issues:
        try:
            identity = runtime_identity()
            validate_runtime_version()
        except UserFacingError as exc:
            issues.append(f"{exc.message} {exc.hint or ''}".strip())
    return {
        "config": {
            "python": config.python,
            "timeout_s": config.timeout_s,
            "smoke_timeout_s": config.smoke_timeout_s,
        },
        "identity": identity,
        "issues": issues,
        "ready": not issues,
        "probe_requested": probe,
        "required_version": LTX_PIPELINES_VERSION,
    }


def update_ltx_runtime_config(values: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "python": "PYTHON",
        "timeout_s": "TIMEOUT_SECONDS",
        "smoke_timeout_s": "SMOKE_TIMEOUT_SECONDS",
    }
    updates: dict[str, str] = {}
    for field, env_name in fields.items():
        if field not in values:
            continue
        value = values[field]
        if field.endswith("timeout_s"):
            try:
                timeout_s = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be a positive number") from exc
            if not 0 < timeout_s <= 86400:
                raise ValueError(f"{field} must be between 1 and 86400 seconds")
            text = str(timeout_s)
        else:
            text = str(value or "").strip()
            if not text:
                raise ValueError("python is required")
            if len(text) > 2048:
                raise ValueError("python cannot exceed 2048 characters")
        updates[f"{LTX_ENV_PREFIX}{env_name}"] = text

    update_launcher_environment(updates)
    return ltx_runtime_status(probe=False)


def _python_executable() -> str:
    executable = Path(ltx_runtime_config().python).expanduser()
    if not executable.is_file():
        raise _runtime_error(
            "The configured LTX-2.5 Python executable was not found",
            "Set EDMG_LTX25_PYTHON to the Python environment containing ltx-pipelines 1.3.0.",
        )
    return str(executable.resolve())


def runtime_identity() -> dict[str, str]:
    executable = _python_executable()
    try:
        installed = subprocess.check_output(
            [
                executable,
                "-c",
                "import importlib.metadata; print(importlib.metadata.version('ltx-pipelines'))",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise _runtime_error(
            "The official LTX-2.5 runtime is not installed",
            f"Install ltx-pipelines=={LTX_PIPELINES_VERSION} in EDMG_LTX25_PYTHON's environment.",
        ) from exc
    return {"python": executable, "ltx_pipelines_version": installed}


def validate_runtime_version() -> None:
    identity = runtime_identity()
    installed = identity["ltx_pipelines_version"]
    if installed != LTX_PIPELINES_VERSION:
        raise _runtime_error(
            "The LTX-2.5 runtime version is not qualified",
            f"Expected ltx-pipelines=={LTX_PIPELINES_VERSION}, but found {installed}.",
        )


def _device_environment(device: str) -> dict[str, str]:
    value = str(device or "").strip().lower()
    env = dict(os.environ)
    if value == "cuda" or value == "cuda:0":
        env["CUDA_VISIBLE_DEVICES"] = "0"
    elif value.startswith("cuda:") and value[5:].isdigit():
        env["CUDA_VISIBLE_DEVICES"] = value[5:]
    else:
        raise _runtime_error("Unsupported LTX-2.5 device", "Choose a specific CUDA device such as cuda:0.")
    return env


def build_command(
    *, package_root: Path, output_path: Path, prompt: str, width: int, height: int,
    num_frames: int, fps: float, seed: int, image_path: Path | None = None,
    offload: str = "none", fp8: bool = False,
) -> list[str]:
    if int(width) % 64 or int(height) % 64:
        raise _runtime_error("Invalid LTX-2.5 dimensions", "LTX-2.5 width and height must be divisible by 64.")
    if int(num_frames) <= 0 or (int(num_frames) - 1) % 8:
        raise _runtime_error("Invalid LTX-2.5 frame count", "LTX-2.5 requires num_frames = 8 * k + 1.")
    offload_value = str(offload).strip().lower()
    if offload_value not in {"none", "cpu", "disk"}:
        raise _runtime_error("Invalid LTX-2.5 offload mode", "Choose none, cpu, or disk.")
    command = [_python_executable(), "-m", LTX_PIPELINE_MODULE]
    for flag, relative in _COMPONENT_FLAGS:
        component = package_root / Path(relative)
        if not component.is_file():
            raise _runtime_error("LTX-2.5 package is incomplete", f"Missing required component: {relative}")
        command.extend((flag, str(component.resolve())))
    command.extend((
        "--prompt", str(prompt or "cinematic subject motion"),
        "--width", str(int(width)), "--height", str(int(height)),
        "--num-frames", str(int(num_frames)), "--frame-rate", str(float(fps)),
        "--seed", str(int(seed)), "--offload", offload_value,
        "--output-path", str(output_path.resolve()),
    ))
    if image_path is not None:
        command.extend(("--image", str(image_path.resolve()), "0", "1.0"))
    if fp8:
        command.extend(("--quantization", "fp8-cast"))
    return command


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _run(command: list[str], *, env: dict[str, str], timeout_s: float,
         cancel_check: Callable[[], Any] | None) -> tuple[str, str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", env=env, shell=False,
        creationflags=creationflags, start_new_session=os.name != "nt",
    )
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while True:
        try:
            if cancel_check is not None and cancel_check():
                raise RuntimeError("LTX-2.5 generation was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"LTX-2.5 generation exceeded {float(timeout_s):g} seconds")
            stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
        except BaseException:
            _terminate_process_tree(process)
            raise
    if process.returncode:
        detail = (stderr or stdout or "No diagnostic output was produced.").strip()[-4000:]
        raise _runtime_error("LTX-2.5 generation failed", detail)
    return stdout, stderr


def decode_mp4(path: Path) -> list[Any]:
    if path.suffix.lower() != ".mp4" or not path.is_file() or path.stat().st_size <= 0:
        raise _runtime_error("LTX-2.5 did not produce a valid MP4", "The output file is missing or empty.")
    try:
        import cv2
        from PIL import Image
    except ImportError as exc:
        raise _runtime_error("MP4 validation is unavailable", "Install the Studio core video dependencies.") from exc
    capture = cv2.VideoCapture(str(path))
    frames: list[Any] = []
    try:
        if not capture.isOpened():
            raise _runtime_error("LTX-2.5 produced an unreadable MP4", "OpenCV could not open the generated video stream.")
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    finally:
        capture.release()
    if not frames:
        raise _runtime_error("LTX-2.5 produced an invalid MP4", "The generated file contains no decodable video frames.")
    return frames


def generate_ltx_frames(
    *, package_root: Path, workspace: Path, prompt: str, width: int, height: int,
    num_frames: int, fps: float, seed: int, device: str, init_image: Any | None = None,
    cpu_offload: bool = False, fp8: bool = False, timeout_s: float | None = None,
    cancel_check: Callable[[], Any] | None = None,
) -> list[Any]:
    validate_runtime_version()
    workspace.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    output_path = workspace / f"ltx25-{token}.mp4"
    image_path = workspace / f"ltx25-{token}-conditioning.png" if init_image is not None else None
    try:
        if image_path is not None:
            init_image.convert("RGB").save(image_path)
        command = build_command(
            package_root=package_root, output_path=output_path, prompt=prompt,
            width=width, height=height, num_frames=num_frames, fps=fps, seed=seed,
            image_path=image_path, offload="cpu" if cpu_offload else "none", fp8=fp8,
        )
        _run(
            command, env=_device_environment(device),
            timeout_s=timeout_s or ltx_runtime_config().timeout_s,
            cancel_check=cancel_check,
        )
        return decode_mp4(output_path)
    finally:
        output_path.unlink(missing_ok=True)
        if image_path is not None:
            image_path.unlink(missing_ok=True)
