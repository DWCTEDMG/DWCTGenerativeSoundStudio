from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


TORCH_PACKAGES = ("torch", "torchaudio", "torchvision")
CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
CUDA_TORCH_INDEX_PATTERN = re.compile(r"^https://download\.pytorch\.org/whl/cu\d+$")
BACKEND_ROOT = Path(__file__).resolve().parents[1] / "python_backend"


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _normalized_index(value: str) -> str:
    return value.strip().rstrip("/")


def _locked_registry(lock: dict[str, Any], package_name: str, version: str) -> str:
    normalized = _normalized_name(package_name)
    registries: set[str] = set()
    for package in lock.get("package", []):
        if _normalized_name(str(package.get("name", ""))) != normalized:
            continue
        if str(package.get("version", "")) != version:
            continue
        source = package.get("source") or {}
        registry = _normalized_index(str(source.get("registry", "")))
        if registry:
            registries.add(registry)
    if len(registries) != 1:
        choices = ", ".join(sorted(registries)) or "none"
        raise RuntimeError(
            f"Expected exactly one locked registry for {package_name}=={version}; found {choices}"
        )
    return next(iter(registries))


def _validate_torch_index(profile: str, index: str) -> None:
    if profile in {"cpu", "directml"}:
        if index != CPU_TORCH_INDEX:
            raise RuntimeError(
                f"{profile} must use {CPU_TORCH_INDEX}; lock selected {index}"
            )
        return
    if profile == "cuda":
        if not CUDA_TORCH_INDEX_PATTERN.fullmatch(index):
            raise RuntimeError(
                f"cuda must use a fixed PyTorch CUDA index; lock selected {index}"
            )
        return
    raise RuntimeError(f"Unsupported accelerator profile: {profile}")


def collect_provenance(lock_path: Path, profile: str) -> dict[str, Any]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(
            f"Release provenance must run on Python 3.12; got {platform.python_version()}"
        )
    if profile not in {"cpu", "directml", "cuda"}:
        raise RuntimeError(f"Unsupported accelerator profile: {profile}")

    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)

    torch_packages: list[dict[str, str]] = []
    indexes: set[str] = set()
    for package_name in TORCH_PACKAGES:
        version = importlib.metadata.version(package_name)
        index = _locked_registry(lock, package_name, version)
        indexes.add(index)
        torch_packages.append(
            {"name": package_name, "version": version, "index": index}
        )

    if len(indexes) != 1:
        raise RuntimeError(
            "Torch-family packages must resolve from one explicit index; found "
            + ", ".join(sorted(indexes))
        )
    torch_index = next(iter(indexes))
    _validate_torch_index(profile, torch_index)

    # The helper is launched by absolute path from the frozen project, so
    # Python places this script directory (not python_backend) on sys.path.
    backend_root = str(BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from pyinstaller_support import pinned_nltk_resource_manifest

    return {
        "pythonVersion": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
        "pyinstallerVersion": importlib.metadata.version("pyinstaller"),
        "torchIndex": torch_index,
        "torchPackages": torch_packages,
        "nltkResources": pinned_nltk_resource_manifest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect lock-backed EDMG release provenance"
    )
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=("cpu", "directml", "cuda"))
    args = parser.parse_args()
    payload = collect_provenance(args.lock.resolve(), args.profile)
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
