from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .render_settings import _config_dir

DEFAULT_DIRECTOR_RUNTIME_SETTINGS: dict[str, Any] = {
    "primary_provider": "nemotron",
    "primary_model": "hf_nemotron3_nano_omni_30b_a3b_reasoning_bf16",
    "primary_execution": "local",
    "primary_endpoint": "https://integrate.api.nvidia.com/v1",
    "primary_server_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "default_quality": "standard",
    "specialist_enabled": True,
    "specialist_model": "hf_cosmos_reason2_8b",
    "specialist_execution": "local",
    "specialist_endpoint": "https://integrate.api.nvidia.com/v1",
    "specialist_server_model": "nvidia/cosmos-reason2-8b",
    "specialist_routing": "automatic",
    "timeout_s": 180,
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


def _endpoint(value: Any) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        return ""
    try:
        parsed = urlsplit(endpoint)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
    except ValueError:
        return ""
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if (parsed.hostname or "").endswith((".services.ai.azure.com", ".openai.azure.com")):
        if parsed.scheme != "https":
            return ""
        endpoint = endpoint.removesuffix("/chat/completions")
        if not urlsplit(endpoint).path.strip("/"):
            endpoint += "/openai/v1"
    return endpoint


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
            "primary_provider": "nemotron",
            # Managed identities stay pinned; server settings are independent,
            # retained when switching back to local execution, and contain no keys.
            "primary_model": DEFAULT_DIRECTOR_RUNTIME_SETTINGS["primary_model"],
            **{
                f"{role}_execution": "server" if payload.get(f"{role}_execution") == "server" else "local"
                for role in ("primary", "specialist")
            },
            **{f"{role}_endpoint": _endpoint(payload.get(f"{role}_endpoint")) for role in ("primary", "specialist")},
            **{
                f"{role}_server_model": str(payload.get(f"{role}_server_model") or DEFAULT_DIRECTOR_RUNTIME_SETTINGS[f"{role}_server_model"]).strip()[:256]
                for role in ("primary", "specialist")
            },
            "default_quality": str(payload.get("default_quality") or "standard").strip().lower()
                if str(payload.get("default_quality") or "standard").strip().lower() in {"fast", "standard", "advanced"} else "standard",
            "specialist_enabled": bool(payload.get("specialist_enabled", True)),
            "specialist_model": DEFAULT_DIRECTOR_RUNTIME_SETTINGS["specialist_model"],
            "specialist_routing": str(payload.get("specialist_routing") or "automatic").strip().lower()
                if str(payload.get("specialist_routing") or "automatic").strip().lower() in {"automatic", "always_video", "off"} else "automatic",
            "timeout_s": _bounded_int(payload.get("timeout_s"), default=180, minimum=10, maximum=1800),
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
