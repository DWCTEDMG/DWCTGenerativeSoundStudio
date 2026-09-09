"""Pinned, selective packages for the new internal engine.

Installing artifacts is independent of execution admission. Never infer a usable
adapter from importability, an installed directory, or a user benchmark flag.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from .model_runtime_registry import DEFAULT_RUNTIME_REGISTRY

MANIFESTS = json.loads(Path(__file__).with_name("engine_package_manifests.json").read_text(encoding="utf-8"))
STANDARD_GGUF_ID = "hf_qwen3_vl_8b_gguf_director"
HIGH_GGUF_ID = "hf_qwen3_vl_30b_gguf_director"

# Preliminary admission targets, not benchmarked performance promises. VRAM is
# per device; do not sum multiple GPUs without a model-parallel implementation.
PROFILES = {
    STANDARD_GGUF_ID: ("qwen3_vl_gguf", "director", 0, 16, ("llama_cpp",)),
    HIGH_GGUF_ID: ("qwen3_vl_gguf", "director", 0, 32, ("llama_cpp",)),
    "hf_hunyuan_video15_internal": ("hunyuan_video15", "video", 14, 64, ()),
    "hf_whisper_large_v3_turbo_internal": ("whisper_transformers", "asr", 0, 8, ("torch", "transformers")),
    "hf_ltx_25_distilled_internal": ("ltx_25", "video", 5, 36, ("torch", "ltx_core", "ltx_pipelines")),
}
RUNTIME_BLOCKERS = {
    "qwen3_vl_gguf": ["Install a supported llama-server build and run the model runtime smoke test before using this Director package."],
    "hunyuan_video15": ["Configure the explicit WSL2 or external Linux Python runner and qualify it with the runtime smoke test.", "Separate Qwen2.5-VL, ByT5, Glyph-SDXL-v2, and gated FLUX.1-Redux-dev assets are required and are not included in the Tencent package."],
    "whisper_transformers": ["Run the model runtime smoke test before selecting the managed Transformers Whisper provider."],
    "ltx_25": ["Configure ltx-pipelines 1.3.0 in the isolated runtime and run the model runtime smoke test."],
}


def package_manifest(model_id: str) -> dict[str, Any] | None:
    return MANIFESTS.get(model_id)


def checked_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    files = manifest["files"]
    if not files:
        raise ValueError("Package has no required files")
    names = set()
    for item in files:
        name = item["path"]
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or any(part in {".", ".."} for part in name.split("/"))
                or any(char in name for char in "\\:*?[]") or name in names):
            raise ValueError("Package paths must be unique, literal relative paths")
        if item["size_bytes"] <= 0 or len(item["sha256"]) != 64:
            raise ValueError("Package file integrity metadata is invalid")
        names.add(name)
    return files


def safe_file(root: Path, name: str) -> Path:
    root = Path(root)
    candidate = root / name
    if root.is_symlink() or root.is_junction():
        raise ValueError("Package root must not be a link")
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink() or part.is_junction():
            raise ValueError("Package components must not be links")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Package file escapes its installation directory")
    return candidate


def validate_package(root: Path, manifest: dict[str, Any], *, verify_hashes: bool = False,
                     cancel_check: Callable[[], None] | None = None) -> dict[str, Any]:
    """Fast probes use size and the stamps recorded after full SHA-256 validation.

    Full validation is mandatory before publication. A changed file invalidates
    the receipt; Revalidate in Models performs the full check again.
    """
    problems: list[str] = []
    stamps: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    if not verify_hashes:
        try:
            receipt = json.loads(safe_file(root, "model.json").read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                receipt = {}
            if receipt.get("repo_id") != manifest["repo_id"] or receipt.get("revision") != manifest["revision"]:
                problems.append("Package receipt is missing or belongs to a different revision.")
        except (OSError, ValueError, TypeError):
            problems.append("Package needs installation or full validation.")
    for item in checked_files(manifest):
        name = item["path"]
        if cancel_check:
            cancel_check()
        try:
            path = safe_file(root, name)
            stat = path.stat()
            if not path.is_file() or stat.st_size != item["size_bytes"]:
                raise ValueError("missing or incorrect file size")
            stamp = {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": item["sha256"]}
            if verify_hashes:
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    while chunk := source.read(8 * 1024 * 1024):
                        if cancel_check:
                            cancel_check()
                        digest.update(chunk)
                if digest.hexdigest() != item["sha256"]:
                    raise ValueError("SHA-256 mismatch")
                if path.stat().st_mtime_ns != stat.st_mtime_ns:
                    raise ValueError("file changed during validation")
            elif receipt.get("files", {}).get(name) != stamp:
                raise ValueError("file changed or has not been verified")
            stamps[name] = stamp
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            problems.append(f"{name}: {exc}")
    return {"valid": not problems, "issues": problems, "files": stamps,
            "repo_id": manifest["repo_id"], "revision": manifest["revision"], "schema_version": 1}


def runtime_status(
    model_id: str,
    hardware: dict[str, Any] | None = None,
    *,
    package_root: Path | None = None,
    package_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the backward-compatible package status plus qualification details."""
    status = DEFAULT_RUNTIME_REGISTRY.status(
        model_id,
        package_root=package_root,
        package_validation=package_validation,
        hardware=hardware,
    )
    status["engine"] = PROFILES[model_id][0]
    return status
