from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepend_env_path(key: str, value: Path) -> None:
    normalized = str(value)
    if not normalized:
        return
    current = os.environ.get(key, "")
    parts = [part for part in current.split(os.pathsep) if part]
    if normalized in parts:
        return
    os.environ[key] = os.pathsep.join([normalized, *parts]) if parts else normalized


bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
bundled_nltk_data = bundle_root / "nltk_data"
if bundled_nltk_data.exists():
    _prepend_env_path("NLTK_DATA", bundled_nltk_data)

os.environ.setdefault("MPLBACKEND", "Agg")
