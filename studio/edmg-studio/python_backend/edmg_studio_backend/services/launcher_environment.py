"""Thread-safe persistence for the shared launcher environment file."""
from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_LAUNCHER_ENV_LOCK = threading.Lock()


def launcher_env_path() -> Path:
    override = os.getenv("EDMG_LAUNCHER_ENV", "").strip()
    return Path(override).expanduser() if override else Path(__file__).resolve().parents[3] / "launcher_env.json"


def update_launcher_environment(updates: Mapping[str, str]) -> None:
    path = launcher_env_path()
    with _LAUNCHER_ENV_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Launcher configuration is not valid JSON: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError("Launcher configuration must contain a JSON object")
            data = loaded
        data.update(updates)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

        for key, value in updates.items():
            os.environ[key] = value
