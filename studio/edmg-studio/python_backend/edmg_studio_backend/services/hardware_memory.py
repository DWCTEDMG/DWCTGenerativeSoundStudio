"""Physical memory capacity and current OS-usable memory, reported separately."""
from __future__ import annotations

import ctypes
import math
import os
import platform
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any

_GIB = 1024 ** 3


def nvidia_gpu_profile() -> dict[str, Any] | None:
    """Probe the NVIDIA driver directly when Studio uses a CPU-only PyTorch wheel."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            index = int(parts[0])
            vram_gb = round(float(parts[2]) / 1024, 2)
        except ValueError:
            continue
        return {"index": index, "name": parts[1], "vram_gb": vram_gb}
    return None


def _windows_installed_ram_bytes() -> int | None:
    """Read SMBIOS capacity without counting reserved memory or the page file as usable."""
    if platform.system() != "Windows":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        probe = kernel32.GetPhysicallyInstalledSystemMemory
        probe.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        probe.restype = ctypes.c_int
        kilobytes = ctypes.c_ulonglong()
        if probe(ctypes.byref(kilobytes)) and kilobytes.value:
            return int(kilobytes.value) * 1024
    except (AttributeError, OSError, ValueError):
        pass
    return None


def memory_profile() -> dict[str, float | None]:
    """Keep usable total for budgeting; physical capacity is only an admission input."""
    usable_bytes = 0
    available_bytes: int | None = None
    try:
        import psutil

        memory = psutil.virtual_memory()
        usable_bytes = int(memory.total)
        available_bytes = int(memory.available)
    except (ImportError, AttributeError, OSError, ValueError):
        try:
            usable_bytes = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            pass
    installed_bytes = _windows_installed_ram_bytes()
    # Windows rejects malformed SMBIOS capacity smaller than OS-usable RAM;
    # keep this boundary for unsupported or inconsistent firmware reports too.
    if installed_bytes is not None and installed_bytes < usable_bytes:
        installed_bytes = None
    return {
        "ram_gb": round(max(0, usable_bytes) / _GIB, 2),
        "installed_ram_gb": round(installed_bytes / _GIB, 2) if installed_bytes is not None else None,
        "available_ram_gb": round(max(0, available_bytes) / _GIB, 2) if available_bytes is not None else None,
    }


def physical_ram_capacity_gb(hardware: Mapping[str, Any]) -> float:
    """Use observed installed capacity, falling back to the existing usable-total field."""
    for key in ("installed_ram_gb", "ram_gb"):
        try:
            value = float(hardware.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value
    return 0.0


def meets_physical_ram_requirement(hardware: Mapping[str, Any], required_gb: float) -> bool:
    """Admit nominal DIMM capacity without masking genuinely undersized systems."""
    installed = hardware.get("installed_ram_gb")
    try:
        installed_value = float(installed or 0)
    except (TypeError, ValueError):
        installed_value = 0.0
    if math.isfinite(installed_value) and installed_value > 0:
        return installed_value >= required_gb
    usable = physical_ram_capacity_gb(hardware)
    tolerance = max(0.5, required_gb * 0.03)
    return usable + tolerance >= required_gb
