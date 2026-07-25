from __future__ import annotations

import json
import os
from pathlib import Path

from edmg_studio_backend.services.model_cache_settings import (
    DEFAULT_HF_BUCKET_ID,
    ModelCacheSettingsStore,
)


def test_defaults_enabled_with_default_bucket(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    cfg = store.get()
    assert cfg["storage_mode"] == "local_cache"
    assert cfg["hf_bucket"]["enabled"] is True
    assert cfg["hf_bucket"]["bucket"] == DEFAULT_HF_BUCKET_ID
    assert cfg["hf_bucket"]["prefix"] == ""


def test_tracked_launcher_defaults_keep_local_cache_mode() -> None:
    defaults_path = Path(__file__).resolve().parents[3] / "launcher_env.defaults.json"
    data = json.loads(defaults_path.read_text(encoding="utf-8"))

    assert data["EDMG_MODEL_STORAGE_MODE"] == "local_cache"


def test_update_persists_and_normalizes(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    cfg = store.update(
        {
            "enabled": True,
            # Tolerate a full hf:// URI and stray slashes being pasted in.
            "bucket": "hf://buckets/team/edmg-models/",
            "prefix": "/weights/",
            "storage_mode": "cloud_only",
        }
    )
    assert cfg["storage_mode"] == "cloud_only"
    assert cfg["hf_bucket"]["enabled"] is True
    assert cfg["hf_bucket"]["bucket"] == "team/edmg-models"
    assert cfg["hf_bucket"]["prefix"] == "weights"

    # Persisted across store instances.
    reloaded = ModelCacheSettingsStore(tmp_path).get()
    assert reloaded["storage_mode"] == "cloud_only"
    assert reloaded["hf_bucket"]["enabled"] is True
    assert reloaded["hf_bucket"]["bucket"] == "team/edmg-models"


def test_apply_to_env_force_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EDMG_HF_BUCKET_MODEL_CACHE", raising=False)
    monkeypatch.delenv("EDMG_HF_BUCKET_ID", raising=False)
    monkeypatch.delenv("EDMG_HF_BUCKET_PREFIX", raising=False)
    monkeypatch.setenv("EDMG_MODEL_STORAGE_MODE", "cloud_only")

    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": True, "bucket": "team/edmg-models", "prefix": "weights", "storage_mode": "local_cache"})
    store.apply_to_env(force=True)

    assert os.environ["EDMG_MODEL_STORAGE_MODE"] == "local_cache"
    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "1"
    assert os.environ["EDMG_HF_BUCKET_ID"] == "team/edmg-models"
    assert os.environ["EDMG_HF_BUCKET_PREFIX"] == "weights"


def test_apply_to_env_startup_does_not_override_explicit_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "explicit/from-launcher")
    monkeypatch.setenv("EDMG_MODEL_STORAGE_MODE", "cloud_only")
    monkeypatch.delenv("EDMG_HF_BUCKET_MODEL_CACHE", raising=False)

    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": True, "bucket": "team/edmg-models"})
    store.apply_to_env(force=False)

    # Explicit launcher HF bucket env wins; storage mode is intentionally
    # restored from Studio settings to avoid stale cloud_only sessions.
    assert os.environ["EDMG_MODEL_STORAGE_MODE"] == "local_cache"
    assert os.environ["EDMG_HF_BUCKET_ID"] == "explicit/from-launcher"
    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "1"


def test_apply_to_env_force_disable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": False, "bucket": "team/edmg-models"})
    store.apply_to_env(force=True)
    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "0"
