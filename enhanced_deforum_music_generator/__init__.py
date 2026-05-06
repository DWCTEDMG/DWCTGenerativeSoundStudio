"""Repo-root compatibility wrapper for the vendored EDMG engine package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_PKG_DIR = (
    Path(__file__).resolve().parents[1]
    / "studio"
    / "edmg-studio"
    / "python_backend"
    / "enhanced_deforum_music_generator"
)
_INIT_FILE = _PKG_DIR / "__init__.py"

if not _INIT_FILE.exists():
    raise ImportError(f"Canonical package not found at {_INIT_FILE}")

_SPEC = importlib.util.spec_from_file_location(
    __name__,
    _INIT_FILE,
    submodule_search_locations=[str(_PKG_DIR)],
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load canonical package spec from {_INIT_FILE}")

module = sys.modules[__name__]
module.__file__ = str(_INIT_FILE)
module.__package__ = __name__
module.__path__ = [str(_PKG_DIR)]  # type: ignore[attr-defined]
module.__spec__ = _SPEC  # type: ignore[attr-defined]
_SPEC.loader.exec_module(module)
