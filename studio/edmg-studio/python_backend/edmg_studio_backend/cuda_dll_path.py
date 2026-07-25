"""Ensure PyTorch's bundled CUDA/cuDNN DLLs win over system toolkit installs.

On Windows, a standalone CUDA Toolkit or cuDNN install on ``PATH`` can load
before the copies bundled inside the active ``torch`` wheel. Mixed cuDNN
sub-library versions then fail with ``CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH``.
Prepending ``torch/lib`` at process startup keeps the wheel's matched set together.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _torch_lib_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "torch" / "lib"
        if candidate.is_dir():
            return candidate

    for root in (Path(sys.prefix), Path(sys.base_prefix)):
        candidate = root / "Lib" / "site-packages" / "torch" / "lib"
        if candidate.is_dir():
            return candidate
    return None


def _blocked_path_entry(entry: str) -> bool:
    """True when a PATH entry can shadow PyTorch's bundled CUDA/cuDNN DLLs."""
    if not entry:
        return True
    norm = entry.replace("/", "\\").lower()
    if "\\cudnn\\" in norm:
        return True
    if "\\cuda\\v" in norm and "\\bin" in norm:
        return True
    if "\\cupti\\" in norm:
        return True
    return False


def prepare_cuda_dll_path() -> None:
    """Prefer the active venv's ``torch/lib`` directory on the DLL search path."""
    torch_lib = _torch_lib_dir()
    if torch_lib is None:
        return

    lib = str(torch_lib)
    path_key = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
    current = os.environ.get(path_key, "")
    parts = [p for p in current.split(os.pathsep) if p and p != lib and not _blocked_path_entry(p)]
    os.environ[path_key] = os.pathsep.join([lib, *parts])
