"""Deterministic, memory-aware TensorRT builder resource selection."""
from __future__ import annotations


_MIB = 1024**2
_GIB = 1024**3


def workspace_bytes(torch, device: int) -> int:
    """Choose a stable workspace tier from total GPU capacity for cache identity."""
    properties = torch.cuda.get_device_properties(device)
    total_bytes = int(properties.total_memory)
    if total_bytes < 8 * _GIB:
        selected = 512 * _MIB
    elif total_bytes < 16 * _GIB:
        selected = 1024 * _MIB
    else:
        selected = 2 * _GIB

    return selected


def require_build_memory(torch, device: int, selected_workspace_bytes: int) -> None:
    """Reject a new engine build when current free VRAM cannot safely contain it."""
    free_bytes, _ = torch.cuda.mem_get_info(device)
    required_free = selected_workspace_bytes + 512 * _MIB
    if free_bytes < required_free:
        raise RuntimeError(
            "Insufficient free VRAM for TensorRT engine construction: "
            f"requires at least {required_free // _MIB} MiB, available {free_bytes // _MIB} MiB"
        )
