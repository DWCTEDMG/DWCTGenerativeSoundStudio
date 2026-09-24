from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .render_settings import _config_dir

DEFAULT_DIRECTOR_RUNTIME_SETTINGS: dict[str, Any] = {
    "runtime_path": "",
    "gpu_layers": "auto",
    "gpu_devices": "auto",
    "tensor_split": "auto",
    "dense_device_map": "balanced_low_0",
    "context_length": 8192,
    "batch_size": 64,
    "ubatch_size": 16,
    "cuda_graphs": False,
}

_DENSE_DEVICE_MAPS = {"auto", "balanced", "balanced_low_0", "sequential"}


def _gpu_devices(value: Any) -> str:
    requested = str(value or "auto").strip().lower()
    if requested in {"", "auto", "all"}:
        return "auto"
    parts = [part.strip() for part in requested.split(",") if part.strip()]
    if not parts or any(not part.isdigit() for part in parts):
        return "auto"
    indexes = [int(part) for part in parts]
    if len(set(indexes)) != len(indexes):
        return "auto"
    return ",".join(str(index) for index in indexes)


def _tensor_split(value: Any) -> str:
    requested = str(value or "auto").strip().lower()
    if requested in {"", "auto"}:
        return "auto"
    try:
        weights = [float(part.strip()) for part in requested.split(",") if part.strip()]
    except ValueError:
        return "auto"
    if not weights or any(weight <= 0 for weight in weights):
        return "auto"
    return ",".join(f"{weight:g}" for weight in weights)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


class DirectorRuntimeSettingsStore:
    def __init__(self, data_dir: Path):
        self._path = _config_dir(data_dir) / "director_runtime.json"

    def get(self) -> dict[str, Any]:
        try:
            current = json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        except (OSError, json.JSONDecodeError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        return self._sanitize({**DEFAULT_DIRECTOR_RUNTIME_SETTINGS, **current})

    def update(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        settings = self._sanitize({**self.get(), **(payload if isinstance(payload, dict) else {})})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        temporary.replace(self._path)
        return settings

    @staticmethod
    def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
        requested_layers = str(payload.get("gpu_layers", "auto")).strip().lower()
        if requested_layers != "auto":
            try:
                requested_layers = str(max(0, min(128, int(requested_layers))))
            except ValueError:
                requested_layers = "auto"
        batch_size = _bounded_int(payload.get("batch_size"), default=64, minimum=8, maximum=512)
        ubatch_size = _bounded_int(payload.get("ubatch_size"), default=16, minimum=1, maximum=batch_size)
        dense_device_map = str(payload.get("dense_device_map") or "balanced_low_0").strip().lower()
        if dense_device_map not in _DENSE_DEVICE_MAPS:
            dense_device_map = "balanced_low_0"
        return {
            "runtime_path": str(payload.get("runtime_path") or "").strip(),
            "gpu_layers": requested_layers,
            "gpu_devices": _gpu_devices(payload.get("gpu_devices")),
            "tensor_split": _tensor_split(payload.get("tensor_split")),
            "dense_device_map": dense_device_map,
            "context_length": _bounded_int(
                payload.get("context_length"), default=8192, minimum=8192, maximum=32768
            ),
            "batch_size": batch_size,
            "ubatch_size": ubatch_size,
            "cuda_graphs": bool(payload.get("cuda_graphs", False)),
        }
