from __future__ import annotations

import json
import os
import re
from pathlib import Path

__all__ = ['app']

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _load_launcher_env() -> None:
    """Load env-style keys into the process environment before config is read.

    Sources are applied in priority order (highest first). ``setdefault`` is
    used throughout, so a value set by a higher-priority source (or already
    present in the real environment) is never overwritten by a lower one:

      1. ``$EDMG_LAUNCHER_ENV`` (explicit override path), if set.
      2. ``launcher_env.json`` at the Studio root - local, machine-specific
         config written by the desktop launcher (gitignored). Holds storage
         paths, backend URLs, etc.
      3. ``launcher_env.defaults.json`` at the Studio root - tracked, committed
         project defaults that ship with the repo (e.g. the Hugging Face bucket
         model-cache settings) so a fresh clone works without machine setup.

    This lets the backend pick up configuration even when started directly
    (external mode) rather than spawned by the launcher.

    Only keys shaped like environment variables (``UPPER_SNAKE_CASE``) with
    scalar values are imported; camelCase launcher-internal keys are ignored.
    Secrets (tokens, keys) are never stored here - HF auth uses the locally
    saved ``hf auth login`` token.
    """
    studio_root = Path(__file__).resolve().parents[2]
    candidates: list[Path] = []
    override = os.getenv("EDMG_LAUNCHER_ENV", "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(studio_root / "launcher_env.json")
    candidates.append(studio_root / "launcher_env.defaults.json")

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
        # Continue to lower-priority sources; setdefault keeps earlier wins.


_load_launcher_env()
