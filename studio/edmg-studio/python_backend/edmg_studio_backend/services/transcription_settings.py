from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from .render_settings import _config_dir


TRANSCRIPTION_PROVIDERS = ("faster_whisper", "parakeet")
WHISPER_MODELS = ("turbo", "large-v3", "medium", "small")
PARAKEET_MODELS = (
    "nvidia/parakeet-tdt-0.6b-v3",
    "nvidia/parakeet-tdt-0.6b-v2",
)
TRANSCRIPTION_DEVICES = ("auto", "cuda", "cpu")
TRANSCRIPTION_COMPUTE_TYPES = ("auto", "float16", "int8", "int8_float16")

DEFAULT_TRANSCRIPTION_SETTINGS: dict[str, Any] = {
    "provider": "faster_whisper",
    "model": "turbo",
    "device": "auto",
    "compute_type": "auto",
    "fallback_to_whisper": True,
    "separate_vocals": False,
    "separation_model": "htdemucs",
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _clone_defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_TRANSCRIPTION_SETTINGS))


def normalize_provider(value: Any) -> str:
    provider = str(value or "").strip().lower().replace("-", "_")
    if provider in {"whisper", "fasterwhisper", "faster_whisper"}:
        return "faster_whisper"
    if provider in {"parakeet", "nvidia_parakeet", "nvidia-parakeet"}:
        return "parakeet"
    return DEFAULT_TRANSCRIPTION_SETTINGS["provider"]


def normalize_model(provider: str, value: Any) -> str:
    raw = str(value or "").strip()
    lower = raw.lower().replace("_", "-")
    if provider == "parakeet":
        if lower in {"v2", "parakeet-v2", "parakeet-tdt-0.6b-v2", "nvidia/parakeet-tdt-0.6b-v2"}:
            return "nvidia/parakeet-tdt-0.6b-v2"
        if lower in {"v3", "parakeet-v3", "parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3"}:
            return "nvidia/parakeet-tdt-0.6b-v3"
        return raw if raw in PARAKEET_MODELS else DEFAULT_TRANSCRIPTION_SETTINGS["model"]

    if lower in {"large-v3-turbo", "whisper-large-v3-turbo"}:
        return "turbo"
    if lower in WHISPER_MODELS:
        return lower
    return DEFAULT_TRANSCRIPTION_SETTINGS["model"]


def normalize_device(value: Any) -> str:
    device = str(value or "").strip().lower()
    return device if device in TRANSCRIPTION_DEVICES else DEFAULT_TRANSCRIPTION_SETTINGS["device"]


def normalize_compute_type(value: Any) -> str:
    compute_type = str(value or "").strip().lower()
    return (
        compute_type
        if compute_type in TRANSCRIPTION_COMPUTE_TYPES
        else DEFAULT_TRANSCRIPTION_SETTINGS["compute_type"]
    )


def transcription_dependency_status() -> dict[str, Any]:
    faster_whisper_available = importlib.util.find_spec("faster_whisper") is not None
    nemo_available = importlib.util.find_spec("nemo") is not None
    torch_available = importlib.util.find_spec("torch") is not None
    demucs_available = importlib.util.find_spec("demucs") is not None
    return {
        "faster_whisper_available": faster_whisper_available,
        "parakeet_available": bool(nemo_available and torch_available),
        "nemo_available": nemo_available,
        "torch_available": torch_available,
        "demucs_available": demucs_available,
        "parakeet_install_hint": 'Install optional dependencies with `pip install -e ".[parakeet]"` from python_backend.',
        "demucs_install_hint": 'Install optional dependencies with `pip install -e ".[source_separation]"` from python_backend.',
    }


class TranscriptionSettingsStore:
    def __init__(self, data_dir: Path):
        self._path = _config_dir(data_dir) / "transcription.json"

    def get(self) -> dict[str, Any]:
        current = _read_json(self._path, default={})
        if not isinstance(current, dict):
            current = {}
        merged = _clone_defaults()
        merged.update(current)
        return self._sanitize(merged)

    def update(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        current = self.get()
        incoming = payload if isinstance(payload, dict) else {}
        current.update(incoming)
        cleaned = self._sanitize(current)
        _write_json(self._path, cleaned)
        return cleaned

    def _sanitize(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = normalize_provider(payload.get("provider"))
        model = normalize_model(provider, payload.get("model"))
        if provider == "parakeet" and model not in PARAKEET_MODELS:
            model = "nvidia/parakeet-tdt-0.6b-v3"
        if provider == "faster_whisper" and model not in WHISPER_MODELS:
            model = DEFAULT_TRANSCRIPTION_SETTINGS["model"]

        return {
            "provider": provider,
            "model": model,
            "device": normalize_device(payload.get("device")),
            "compute_type": normalize_compute_type(payload.get("compute_type")),
            "fallback_to_whisper": bool(payload.get("fallback_to_whisper", True)),
            "separate_vocals": bool(payload.get("separate_vocals", False)),
            "separation_model": str(payload.get("separation_model") or "htdemucs").strip() or "htdemucs",
        }
