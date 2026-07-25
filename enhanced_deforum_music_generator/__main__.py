from __future__ import annotations

from pathlib import Path


_MAIN_FILE = (
    Path(__file__).resolve().parents[1]
    / "studio"
    / "edmg-studio"
    / "python_backend"
    / "enhanced_deforum_music_generator"
    / "__main__.py"
)

if not _MAIN_FILE.exists():
    raise ImportError(f"Canonical module entrypoint not found at {_MAIN_FILE}")

globals()["__file__"] = str(_MAIN_FILE)
exec(compile(_MAIN_FILE.read_text(encoding="utf-8"), str(_MAIN_FILE), "exec"), globals(), globals())
