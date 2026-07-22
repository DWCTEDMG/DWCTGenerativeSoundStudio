from __future__ import annotations

import os
from pathlib import Path


def safe_join(base: Path, rel: str) -> Path:
    """Join an untrusted relative path beneath *base* without allowing escape."""
    base_path = os.path.realpath(os.fspath(base))
    candidate = os.path.realpath(os.path.join(base_path, rel))
    if candidate != base_path and not candidate.startswith(base_path + os.sep):
        raise ValueError("Unsafe path")
    return Path(candidate)
