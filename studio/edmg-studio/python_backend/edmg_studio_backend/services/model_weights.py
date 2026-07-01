from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec"
_DIFFUSERS_WEIGHT_PATTERNS = ("*.safetensors", "*.bin", "*.ckpt")


@dataclass(frozen=True)
class DiffusersWeightSummary:
    has_lfs_pointer: bool = False
    has_fp16_safetensors_pointer: bool = False
    has_fp16_safetensors: bool = False
    has_fp16_bin: bool = False
    has_fp16_bin_without_safetensors_peer: bool = False


def is_lfs_pointer_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size > 4096:
            return False
        with path.open("rb") as handle:
            return handle.read(256).startswith(_LFS_POINTER_PREFIX)
    except OSError:
        return False


def is_real_weight_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0 and not is_lfs_pointer_file(path)
    except OSError:
        return False


def summarize_diffusers_weights(model_dir: Path) -> DiffusersWeightSummary:
    has_lfs_pointer = False
    has_fp16_safetensors_pointer = False
    has_fp16_safetensors = False
    has_fp16_bin = False
    has_fp16_bin_without_safetensors_peer = False
    for pattern in _DIFFUSERS_WEIGHT_PATTERNS:
        try:
            candidates = model_dir.rglob(pattern)
            for candidate in candidates:
                name = candidate.name.lower()
                if is_lfs_pointer_file(candidate):
                    has_lfs_pointer = True
                    if name.endswith(".fp16.safetensors"):
                        has_fp16_safetensors_pointer = True
                    continue
                if not is_real_weight_file(candidate):
                    continue
                if name.endswith(".fp16.safetensors"):
                    has_fp16_safetensors = True
                elif name.endswith(".fp16.bin"):
                    has_fp16_bin = True
                    safetensors_peer = candidate.with_suffix(".safetensors")
                    if not is_real_weight_file(safetensors_peer):
                        has_fp16_bin_without_safetensors_peer = True
                if (
                    has_lfs_pointer
                    and has_fp16_safetensors_pointer
                    and has_fp16_safetensors
                    and has_fp16_bin
                    and has_fp16_bin_without_safetensors_peer
                ):
                    return DiffusersWeightSummary(
                        has_lfs_pointer=has_lfs_pointer,
                        has_fp16_safetensors_pointer=has_fp16_safetensors_pointer,
                        has_fp16_safetensors=has_fp16_safetensors,
                        has_fp16_bin=has_fp16_bin,
                        has_fp16_bin_without_safetensors_peer=has_fp16_bin_without_safetensors_peer,
                    )
        except OSError:
            continue
    return DiffusersWeightSummary(
        has_lfs_pointer=has_lfs_pointer,
        has_fp16_safetensors_pointer=has_fp16_safetensors_pointer,
        has_fp16_safetensors=has_fp16_safetensors,
        has_fp16_bin=has_fp16_bin,
        has_fp16_bin_without_safetensors_peer=has_fp16_bin_without_safetensors_peer,
    )


def diffusers_weight_load_kwargs(model_dir: Path, device: str) -> dict[str, object]:
    summary = summarize_diffusers_weights(model_dir)
    kwargs: dict[str, object] = {}
    if device in {"cuda", "rocm"} and (summary.has_fp16_safetensors or summary.has_fp16_bin):
        kwargs["variant"] = "fp16"
    if (
        summary.has_fp16_bin
        and (summary.has_fp16_safetensors_pointer or summary.has_fp16_bin_without_safetensors_peer)
    ):
        kwargs["use_safetensors"] = False
    return kwargs
