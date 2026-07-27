from __future__ import annotations

import json
from pathlib import Path


def minimal_safetensors_bytes(*, data: bytes = b"\0\0\0\0") -> bytes:
    header = json.dumps(
        {
            "weight": {
                "dtype": "F32",
                "shape": [len(data) // 4],
                "data_offsets": [0, len(data)],
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    header += b" " * (-len(header) % 8)
    return len(header).to_bytes(8, "little") + header + data


def write_minimal_safetensors(path: Path, *, data: bytes = b"\0\0\0\0") -> None:
    """Write a structurally valid one-tensor safetensors fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(minimal_safetensors_bytes(data=data))
