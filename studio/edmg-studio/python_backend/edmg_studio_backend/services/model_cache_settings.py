"""Persisted configuration for the runtime model cache (UI-driven).

The :class:`~edmg_studio_backend.services.model_manager.ModelManager` resolves
its cloud model cache from environment variables (see
``integrations/hf_bucket.py`` and ``integrations/aws.py``). Historically those
env vars could only be set by the launcher, so the Studio UI could not enable
or point the Hugging Face bucket cache.

This store persists the user's choice (in ``config/model_cache.json``) and
projects it onto ``os.environ`` so the existing env-based resolution keeps
working. The Hugging Face bucket is always preferred over AWS S3 / Azure when
enabled (``ModelManager._build_model_cache`` tries it first); this store simply
makes that path configurable and persistent from the UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Default bucket for this Studio install. Users can override it from the UI
# (Cloud → Hugging Face bucket) or via ``EDMG_HF_BUCKET_ID``.
DEFAULT_HF_BUCKET_ID = "gulle1155/DWCTedmgAIStudioModels"

DEFAULT_MODEL_CACHE_SETTINGS: dict[str, Any] = {
    # Local-first storage keeps usable models on disk and mirrors supported
    # installs into the configured remote caches. This is the normal Studio
    # mode; cloud_only remains available only when explicitly requested.
    "storage_mode": "local_cache",
    # Provider preference is HF bucket first; S3/Azure remain automatic
    # fallbacks resolved from their own env vars when HF is not enabled.
    "provider": "huggingface_bucket",
    "hf_bucket": {
        # Enabled by default so the Studio uses the configured bucket out of the
        # box. Override per-install from the UI (Cloud → Hugging Face bucket) or
        # with ``EDMG_HF_BUCKET_MODEL_CACHE=0`` (an explicit env var wins).
        "enabled": True,
        "bucket": DEFAULT_HF_BUCKET_ID,
        "prefix": "",
    },
}


def _config_dir(data_dir: Path) -> Path:
    p = (data_dir / "config").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


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


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_bucket(value: Any) -> str:
    text = str(value or "").strip()
    if "buckets/" in text:
        text = text.split("buckets/", 1)[1]
    return text.strip().strip("/")


def _normalize_prefix(value: Any) -> str:
    return str(value or "").strip().strip("/").replace("\\", "/")


def _normalize_storage_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"cloud_only", "s3_only", "remote_only"}:
        return "cloud_only"
    return "local_cache"


def _clone_defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_MODEL_CACHE_SETTINGS))


class ModelCacheSettingsStore:
    """Persist + apply the UI-selected model cache provider settings."""

    def __init__(self, data_dir: Path):
        self._path = _config_dir(data_dir) / "model_cache.json"

    def get(self) -> dict[str, Any]:
        current = _read_json(self._path, default={})
        return self._sanitize(current if isinstance(current, dict) else {})

    def update(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        current = self.get()
        incoming = payload if isinstance(payload, dict) else {}
        # Accept either a flat payload (enabled/bucket/prefix) or a nested one.
        hf_in = incoming.get("hf_bucket") if isinstance(incoming.get("hf_bucket"), dict) else incoming
        hf = current["hf_bucket"]
        if "enabled" in hf_in:
            hf["enabled"] = _truthy(hf_in.get("enabled"))
        if "bucket" in hf_in:
            hf["bucket"] = _normalize_bucket(hf_in.get("bucket"))
        if "prefix" in hf_in:
            hf["prefix"] = _normalize_prefix(hf_in.get("prefix"))
        if "storage_mode" in incoming:
            current["storage_mode"] = _normalize_storage_mode(incoming.get("storage_mode"))
        cleaned = self._sanitize(current)
        _write_json(self._path, cleaned)
        return cleaned

    def _sanitize(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = _clone_defaults()
        out["storage_mode"] = _normalize_storage_mode(payload.get("storage_mode", out["storage_mode"]))
        hf_in = payload.get("hf_bucket") if isinstance(payload.get("hf_bucket"), dict) else {}
        bucket = _normalize_bucket(hf_in.get("bucket", out["hf_bucket"]["bucket"]))
        out["hf_bucket"] = {
            "enabled": _truthy(hf_in.get("enabled", out["hf_bucket"]["enabled"])),
            "bucket": bucket or out["hf_bucket"]["bucket"],
            "prefix": _normalize_prefix(hf_in.get("prefix", out["hf_bucket"]["prefix"])),
        }
        return out

    def apply_to_env(self, *, force: bool = False) -> dict[str, Any]:
        """Project stored settings onto ``os.environ``.

        With ``force=False`` (startup) an explicit env var always wins, so a
        launcher-provided configuration is never clobbered. With ``force=True``
        (UI save) the stored settings become authoritative for this process.
        """
        cfg = self.get()
        hf = cfg["hf_bucket"]

        def _set(key: str, value: str) -> None:
            if force:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)

        # The persisted Studio storage mode is authoritative on startup. This
        # intentionally replaces stale shell values such as cloud_only when the
        # user switches back to local-first storage from the UI.
        os.environ["EDMG_MODEL_STORAGE_MODE"] = str(cfg.get("storage_mode") or "local_cache")

        if hf["enabled"] and hf["bucket"]:
            _set("EDMG_HF_BUCKET_MODEL_CACHE", "1")
            _set("EDMG_HF_BUCKET_ID", hf["bucket"])
            _set("EDMG_HF_BUCKET_PREFIX", hf["prefix"])
        elif force:
            # Explicit disable from the UI.
            os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] = "0"
        return cfg
