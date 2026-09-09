"""Load CTranslate2's CUDA 12 cuBLAS alongside the CUDA 13 Torch runtime.

Only the two versioned cuBLAS libraries are preloaded. Adding a toolkit's bin
directory to PATH would let unrelated cuDNN DLLs shadow Torch's matched set.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path

_LIBRARIES = ("cublasLt64_12.dll", "cublas64_12.dll")
_handles: list = []
_loaded_paths: tuple[str, ...] = ()
_lock = threading.Lock()


def _candidate_directories():
    if getattr(sys, "frozen", False):
        roots = [Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))]
    else:
        roots = [Path(sys.prefix) / "Lib" / "site-packages"]
    for root in roots:
        yield root / "torch" / "lib"
        yield root / "ctranslate2"
        yield root / "nvidia" / "cublas" / "bin"
    for name, value in sorted(os.environ.items(), reverse=True):
        if name.upper().startswith("CUDA_PATH_V12_") and value:
            yield Path(value) / "bin"
    toolkit_root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA GPU Computing Toolkit" / "CUDA"
    for version in sorted(toolkit_root.glob("v12.*"), reverse=True):
        yield version / "bin"


def preload_cuda12_cublas() -> tuple[str, ...]:
    """Reuse an installed complete CUDA 12 pair and retain its process handles."""
    global _loaded_paths
    if sys.platform != "win32":
        return ()
    with _lock:
        if _loaded_paths:
            return _loaded_paths
        for directory in _candidate_directories():
            paths = tuple(directory / name for name in _LIBRARIES)
            if not all(path.is_file() for path in paths):
                continue
            loaded = []
            try:
                for path in paths:
                    loaded.append(ctypes.WinDLL(str(path.resolve())))
            except OSError as exc:
                raise RuntimeError(
                    f"CUDA transcription could not load the cuBLAS 12 pair in {directory}: {exc}"
                ) from exc
            _handles.extend(loaded)
            _loaded_paths = tuple(str(path.resolve()) for path in paths)
            return _loaded_paths
    raise RuntimeError(
        "CUDA transcription requires cublas64_12.dll and cublasLt64_12.dll from CUDA 12. "
        "Install the CUDA 12 cuBLAS runtime or include its matched pair in the Studio runtime; "
        "the CUDA 13 Torch/TensorRT profile can remain selected."
    )
