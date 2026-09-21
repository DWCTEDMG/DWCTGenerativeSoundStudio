"""Package discovery and child-only activation; no environment installation."""
from __future__ import annotations

import importlib.util
import os
import sys
import zipfile
from pathlib import Path

from .cache import digest_file
from ..services.model_load_coordinator import model_load_lock

_DLL_HANDLES = []


def discover(package_path: str = "") -> dict:
    explicit = package_path or os.environ.get("EDMG_TENSORRT_ROOT", "")
    managed = Path(__file__).resolve().parents[3] / "tools" / "tensorrt"
    candidates = ([Path(explicit)] if explicit else []) + sorted(managed.glob("*"), reverse=True)
    # Report downloaded SDKs without modifying or activating them automatically.
    downloads = sorted((Path.home() / "Downloads").glob("TensorRT-*"), reverse=True)
    root = next((p.resolve() for p in candidates if (p / "python").is_dir()), None)
    try:
        binding = importlib.util.find_spec("tensorrt") is not None
    except (ImportError, ValueError):
        binding = False
    return {"installed": bool(root or binding), "package_path": str(root) if root else "",
            "python_binding_found": binding, "downloaded_packages": [str(p) for p in downloads],
            "status": "unprobed" if root or binding else "not_installed",
            "explicit_package_missing": bool(explicit and root is None)}


def activate(data_dir: Path, package_path: str = "") -> None:
    """Called exclusively inside the disposable TensorRT child process."""
    from ..cuda_dll_path import prepare_cuda_dll_path
    prepare_cuda_dll_path()
    found = discover(package_path)
    if found["explicit_package_missing"]:
        raise RuntimeError("The configured TensorRT package is missing")
    if not found["package_path"]:
        return
    if os.name != "nt":
        raise RuntimeError("Local SDK import currently supports Windows; use installed bindings on Linux")
    root = Path(found["package_path"])
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    wheels = list((root / "python").glob(f"tensorrt-*-{tag}-*-win_amd64.whl"))
    if len(wheels) != 1:
        raise RuntimeError("No unique TensorRT Python wheel matches this interpreter")
    wheel = wheels[0]
    target = data_dir / "tensorrt" / "bindings" / digest_file(wheel)
    with model_load_lock(target, timeout_s=30):
        if not (target / ".complete").exists():
            with zipfile.ZipFile(wheel) as archive:
                for member in archive.infolist():
                    destination = (target / member.filename).resolve()
                    if not destination.is_relative_to(target.resolve()):
                        raise ValueError("Unsafe TensorRT wheel member")
                archive.extractall(target)
            (target / ".complete").write_text(wheel.name)
    sys.path.insert(0, str(target))
    for directory in (root / "bin", root / "lib"):
        if directory.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    # PATH changes are confined to this child and preserve PyTorch's CUDA preference.
    os.environ["PATH"] = os.pathsep.join([os.environ.get("PATH", ""), str(root / "bin")])
