from __future__ import annotations

import json
import os
import re
from pathlib import Path

__all__ = ['app']

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _load_launcher_env() -> None:
    """Load env-style keys from launcher_env.json into the process environment.

    The desktop launcher persists configuration (storage paths, backend URLs,
    optional model-cache settings, ...) to ``launcher_env.json`` at the Studio
    root. When the backend is started directly (external mode) instead of being
    spawned by the launcher, those values would otherwise be lost. We load them
    here, before any submodule reads configuration, using ``setdefault`` so an
    explicit value already present in the environment always wins.

    Only keys shaped like environment variables (``UPPER_SNAKE_CASE``) with
    scalar values are imported; camelCase launcher-internal keys are ignored.
    """
    override = os.getenv("EDMG_LAUNCHER_ENV", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path(__file__).resolve().parents[2] / "launcher_env.json")

    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
                continue
            if isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, (int, float)):
                value = str(value)
            elif not isinstance(value, str):
                continue
            os.environ.setdefault(key, value)
        break


_load_launcher_env()
