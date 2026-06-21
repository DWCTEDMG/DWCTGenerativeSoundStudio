from __future__ import annotations

import os

from edmg_studio_backend.services.model_cache_settings import (
    DEFAULT_HF_BUCKET_ID,
    ModelCacheSettingsStore,
)


def test_defaults_enabled_with_default_bucket(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    cfg = store.get()
    assert cfg["hf_bucket"]["enabled"] is True
    assert cfg["hf_bucket"]["bucket"] == DEFAULT_HF_BUCKET_ID
    assert cfg["hf_bucket"]["prefix"] == ""


def test_update_persists_and_normalizes(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    cfg = store.update(
        {
            "enabled": True,
            # Tolerate a full hf:// URI and stray slashes being pasted in.
            "bucket": "hf://buckets/team/edmg-models/",
            "prefix": "/weights/",
        }
    )
    assert cfg["hf_bucket"]["enabled"] is True
    assert cfg["hf_bucket"]["bucket"] == "team/edmg-models"
    assert cfg["hf_bucket"]["prefix"] == "weights"

    # Persisted across store instances.
    reloaded = ModelCacheSettingsStore(tmp_path).get()
    assert reloaded["hf_bucket"]["enabled"] is True
    assert reloaded["hf_bucket"]["bucket"] == "team/edmg-models"


def test_apply_to_env_force_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EDMG_HF_BUCKET_MODEL_CACHE", raising=False)
    monkeypatch.delenv("EDMG_HF_BUCKET_ID", raising=False)
    monkeypatch.delenv("EDMG_HF_BUCKET_PREFIX", raising=False)

    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": True, "bucket": "team/edmg-models", "prefix": "weights"})
    store.apply_to_env(force=True)

    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "1"
    assert os.environ["EDMG_HF_BUCKET_ID"] == "team/edmg-models"
    assert os.environ["EDMG_HF_BUCKET_PREFIX"] == "weights"


def test_apply_to_env_startup_does_not_override_explicit_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "explicit/from-launcher")
    monkeypatch.delenv("EDMG_HF_BUCKET_MODEL_CACHE", raising=False)

    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": True, "bucket": "team/edmg-models"})
    store.apply_to_env(force=False)

    # Explicit launcher env wins; stored config only fills missing vars.
    assert os.environ["EDMG_HF_BUCKET_ID"] == "explicit/from-launcher"
    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "1"


def test_apply_to_env_force_disable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    store = ModelCacheSettingsStore(tmp_path)
    store.update({"enabled": False, "bucket": "team/edmg-models"})
    store.apply_to_env(force=True)
    assert os.environ["EDMG_HF_BUCKET_MODEL_CACHE"] == "0"
