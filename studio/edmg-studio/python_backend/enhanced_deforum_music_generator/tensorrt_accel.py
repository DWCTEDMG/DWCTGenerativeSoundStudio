"""Optional TensorRT acceleration for Diffusers pipelines.

This module provides a *safe, additive* hook that speeds up the heavy denoiser
of a Diffusers pipeline (the ``transformer`` or ``unet`` submodule) using
Torch-TensorRT, while always falling back to plain PyTorch when anything is
missing or fails. Enabling it never changes pipeline outputs' shape/semantics
and never breaks a working install.

Why Torch-TensorRT (and not a standalone TensorRT engine)?
---------------------------------------------------------
Diffusers video pipelines (Wan, HunyuanVideo, CogVideoX, SVD, LTX) are large
multi-module models with dynamic shapes that do not cleanly export to a single
ONNX/TensorRT engine. ``torch.compile(module, backend="torch_tensorrt")``
compiles the supported subgraphs in place and transparently falls back to eager
PyTorch for anything unsupported, which is the only robust way to apply TensorRT
to these pipelines today.

CUDA version note
-----------------
Torch-TensorRT must match the CUDA build of the installed ``torch``. This
project ships ``torch ...+cu124`` (CUDA 12.4), so install the matching
Torch-TensorRT (which bundles its own TensorRT 10.x for CUDA 12). A standalone
TensorRT built for a different CUDA toolkit (e.g. CUDA 13.x) is NOT used by this
path and should not be on ``PATH`` at the same time to avoid DLL conflicts.

    # Into the backend venv (matches torch 2.6 + cu124):
    python -m pip install torch-tensorrt==2.6.0

Enable via the CLI flag ``--accel tensorrt`` or the environment variable
``EDMG_TRT_ACCEL=1``.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

# Submodule names, in priority order, that hold the heavy per-step denoiser.
_DENOISER_ATTRS = ("transformer", "unet")

# Truthy environment values that turn the hook on without a CLI flag.
_TRUTHY = {"1", "true", "yes", "on"}

Logger = Callable[[str], None]


def env_enabled() -> bool:
    """Return True if ``EDMG_TRT_ACCEL`` requests TensorRT acceleration."""
    return os.environ.get("EDMG_TRT_ACCEL", "").strip().lower() in _TRUTHY


def is_available() -> bool:
    """Return True if Torch-TensorRT can be imported in this environment."""
    try:
        import torch_tensorrt  # noqa: F401
    except Exception:
        return False
    return True


def _log(logger: Optional[Logger], message: str) -> None:
    (logger or print)(message)


def _compile_module(module: Any, *, dynamic: bool, logger: Optional[Logger]) -> Any:
    """Wrap a single ``nn.Module`` with the Torch-TensorRT compile backend.

    Returns the compiled module on success, or the original module on any
    failure so the caller can keep running on eager PyTorch.
    """
    try:
        import torch
        import torch_tensorrt  # noqa: F401  # registers the "torch_tensorrt" backend
    except Exception as exc:  # pragma: no cover - depends on optional dep
        _log(
            logger,
            "[trt-accel] torch-tensorrt not installed; using eager PyTorch. "
            f"({exc})",
        )
        return module

    try:
        compiled = torch.compile(module, backend="torch_tensorrt", dynamic=dynamic)
        _log(logger, "[trt-accel] denoiser compiled with Torch-TensorRT backend.")
        return compiled
    except Exception as exc:  # pragma: no cover - hardware/version dependent
        _log(
            logger,
            f"[trt-accel] compilation failed; falling back to eager PyTorch. ({exc})",
        )
        return module


def accelerate_pipe(
    pipe: Any,
    *,
    enabled: bool,
    dynamic: bool = False,
    logger: Optional[Logger] = None,
) -> Any:
    """Optionally TensorRT-accelerate ``pipe`` in place and return it.

    The pipeline is returned unchanged when ``enabled`` is False, when
    Torch-TensorRT is unavailable, or when no compatible denoiser submodule is
    found. Compilation is lazy: the first inference step triggers the actual
    TensorRT build, so the initial run is slower while later runs are faster.
    """
    if not enabled:
        return pipe

    if not is_available():
        _log(
            logger,
            "[trt-accel] requested but torch-tensorrt is not installed; "
            "continuing without acceleration. Install with: "
            "python -m pip install torch-tensorrt==2.6.0",
        )
        return pipe

    target_attr = next(
        (a for a in _DENOISER_ATTRS if getattr(pipe, a, None) is not None),
        None,
    )
    if target_attr is None:
        _log(
            logger,
            "[trt-accel] no 'transformer'/'unet' submodule found on pipeline; "
            "skipping acceleration.",
        )
        return pipe

    module = getattr(pipe, target_attr)
    compiled = _compile_module(module, dynamic=dynamic, logger=logger)
    if compiled is not module:
        setattr(pipe, target_attr, compiled)
        _log(logger, f"[trt-accel] accelerated pipeline.{target_attr}.")
    return pipe


def resolve_enabled(cli_choice: Optional[str]) -> bool:
    """Combine the CLI ``--accel`` choice with the env var.

    ``cli_choice`` is one of ``None``/``"none"``/``"tensorrt"``. The env var acts
    as a fallback default when no explicit CLI choice is given.
    """
    if cli_choice == "tensorrt":
        return True
    if cli_choice == "none":
        return False
    return env_enabled()
