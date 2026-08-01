"""Collect TensorRT libraries without Linux-to-Windows builder resources.

TensorRT's Linux wheel includes optional ``libnvinfer_builder_resource_win_*``
libraries for building Windows engines from a Linux host. EDMG Studio does not
use that cross-platform build mode, and bundling those resources adds roughly
1.8 GiB to the Linux CUDA backend. Native builder resources remain available
for Studio's optional Torch-TensorRT compilation path.
"""

from pathlib import Path

from PyInstaller.compat import is_linux
from PyInstaller.utils.hooks import PY_DYLIB_PATTERNS, collect_dynamic_libs

_WINDOWS_CROSS_BUILDER_PREFIX = "libnvinfer_builder_resource_win_"

_search_patterns = list(PY_DYLIB_PATTERNS)
if is_linux:
    _search_patterns.append("*.so.*")

binaries = collect_dynamic_libs("tensorrt_libs", search_patterns=_search_patterns)

if is_linux:
    binaries = [
        binary
        for binary in binaries
        if not Path(binary[0]).name.startswith(_WINDOWS_CROSS_BUILDER_PREFIX)
    ]
