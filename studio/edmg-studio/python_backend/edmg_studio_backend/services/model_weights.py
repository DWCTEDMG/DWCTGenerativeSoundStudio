from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec"
_DIFFUSERS_WEIGHT_PATTERNS = ("*.safetensors", "*.bin", "*.ckpt")
_DEFAULT_WEIGHT_STEMS = ("diffusion_pytorch_model", "pytorch_model", "model")
_WEIGHTLESS_COMPONENT_MARKERS = (
    "Tokenizer",
    "TokenizerFast",
    "Scheduler",
    "ImageProcessor",
    "FeatureExtractor",
    "SafetyChecker",
)


@dataclass(frozen=True)
class DiffusersWeightSummary:
    has_lfs_pointer: bool = False
    has_complete_default_safetensors: bool = False
    has_complete_default_bin: bool = False
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
        if not path.is_file():
            return False
        stat = path.stat()
        if stat.st_size <= 0 or is_lfs_pointer_file(path):
            return False
        if path.name.lower().endswith(".safetensors"):
            return _is_valid_safetensors(
                str(path.resolve()),
                int(stat.st_size),
                int(stat.st_mtime_ns),
            )
        return True
    except OSError:
        return False


@lru_cache(maxsize=512)
def _is_valid_safetensors(path: str, size: int, mtime_ns: int) -> bool:
    del mtime_ns
    if size <= 8:
        return False
    try:
        with Path(path).open("rb") as handle:
            header_size_raw = handle.read(8)
            if len(header_size_raw) != 8:
                return False
            header_size = int.from_bytes(header_size_raw, "little", signed=False)
            if header_size <= 1 or header_size > size - 8:
                return False
            header = json.loads(handle.read(header_size).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(header, dict):
        return False
    ranges: list[tuple[int, int]] = []
    for name, metadata in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(metadata, dict):
            return False
        offsets = metadata.get("data_offsets")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(value, int) for value in offsets)
        ):
            return False
        start, end = offsets
        if start < 0 or end < start:
            return False
        ranges.append((start, end))
    if not ranges:
        return False
    data_size = size - 8 - header_size
    cursor = 0
    for start, end in sorted(ranges):
        if start != cursor or end > data_size:
            return False
        cursor = end
    return cursor == data_size


def _required_components(model_dir: Path) -> list[Path]:
    model_index = model_dir / "model_index.json"
    try:
        payload = json.loads(model_index.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    components: list[Path] = []
    for name, spec in payload.items():
        if not isinstance(name, str) or not isinstance(spec, list) or len(spec) < 2:
            continue
        class_name = str(spec[1] or "")
        if not class_name or any(
            marker in class_name for marker in _WEIGHTLESS_COMPONENT_MARKERS
        ):
            continue
        components.append(model_dir / name)
    return components


def _component_has_default_format(component_dir: Path, extension: str) -> bool:
    for stem in _DEFAULT_WEIGHT_STEMS:
        if is_real_weight_file(component_dir / f"{stem}.{extension}"):
            return True
        index_path = component_dir / f"{stem}.{extension}.index.json"
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        weight_map = payload.get("weight_map") if isinstance(payload, dict) else None
        filenames = {
            str(filename).replace("\\", "/").strip()
            for filename in (weight_map or {}).values()
            if str(filename).strip()
        }
        shard_pattern = re.compile(
            rf"^{re.escape(stem)}-\d{{5}}-of-\d{{5}}\.{re.escape(extension)}$",
            re.IGNORECASE,
        )
        if filenames and all(
            "/" not in filename
            and shard_pattern.fullmatch(filename) is not None
            and is_real_weight_file(component_dir / filename)
            for filename in filenames
        ):
            return True
    return False


def _has_complete_default_format(model_dir: Path, extension: str) -> bool:
    components = _required_components(model_dir)
    if components:
        return all(
            _component_has_default_format(component, extension)
            for component in components
        )
    return _component_has_default_format(model_dir, extension)


def summarize_diffusers_weights(model_dir: Path) -> DiffusersWeightSummary:
    has_lfs_pointer = False
    has_complete_default_safetensors = _has_complete_default_format(
        model_dir,
        "safetensors",
    )
    has_complete_default_bin = _has_complete_default_format(model_dir, "bin")
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
                        has_complete_default_safetensors=has_complete_default_safetensors,
                        has_complete_default_bin=has_complete_default_bin,
                        has_fp16_safetensors_pointer=has_fp16_safetensors_pointer,
                        has_fp16_safetensors=has_fp16_safetensors,
                        has_fp16_bin=has_fp16_bin,
                        has_fp16_bin_without_safetensors_peer=has_fp16_bin_without_safetensors_peer,
                    )
        except OSError:
            continue
    return DiffusersWeightSummary(
        has_lfs_pointer=has_lfs_pointer,
        has_complete_default_safetensors=has_complete_default_safetensors,
        has_complete_default_bin=has_complete_default_bin,
        has_fp16_safetensors_pointer=has_fp16_safetensors_pointer,
        has_fp16_safetensors=has_fp16_safetensors,
        has_fp16_bin=has_fp16_bin,
        has_fp16_bin_without_safetensors_peer=has_fp16_bin_without_safetensors_peer,
    )


def diffusers_weight_load_kwargs(model_dir: Path, device: str) -> dict[str, object]:
    summary = summarize_diffusers_weights(model_dir)
    kwargs: dict[str, object] = {}
    if summary.has_complete_default_safetensors:
        return kwargs
    if summary.has_complete_default_bin:
        kwargs["use_safetensors"] = False
        return kwargs
    if device in {"cuda", "rocm"} and (summary.has_fp16_safetensors or summary.has_fp16_bin):
        kwargs["variant"] = "fp16"
    if (
        summary.has_fp16_bin
        and (summary.has_fp16_safetensors_pointer or summary.has_fp16_bin_without_safetensors_peer)
    ):
        kwargs["use_safetensors"] = False
    return kwargs
