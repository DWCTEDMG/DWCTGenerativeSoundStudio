from __future__ import annotations

import json
import os

from edmg_studio_backend.services import model_cache_settings as settings_module
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


def test_nested_save_keeps_bucket_enabled_in_local_cache_mode(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    saved = store.update(
        {
            "storage_mode": "local_cache",
            "hf_bucket": {
                "enabled": True,
                "bucket": "team/models",
                "prefix": "weights",
            },
        }
    )

    assert saved["storage_mode"] == "local_cache"
    assert saved["hf_bucket"]["enabled"] is True
    assert ModelCacheSettingsStore(tmp_path).get() == saved

    cloud_only = store.update({"storage_mode": "cloud_only"})
    assert cloud_only["hf_bucket"]["enabled"] is True
    local_again = store.update({"storage_mode": "local_cache"})
    assert local_again["hf_bucket"]["enabled"] is True


def test_atomic_save_retries_transient_windows_replace_and_cleans_temp(tmp_path, monkeypatch) -> None:
    real_replace = settings_module.os.replace
    attempts = 0

    def flaky_replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            error = PermissionError("file is temporarily in use")
            error.winerror = 32
            raise error
        return real_replace(source, destination)

    monkeypatch.setattr(settings_module.os, "replace", flaky_replace)
    monkeypatch.setattr(settings_module.time, "sleep", lambda _seconds: None)

    saved = ModelCacheSettingsStore(tmp_path).update(
        {"hf_bucket": {"enabled": True, "bucket": "team/models"}}
    )

    assert attempts == 3
    assert saved["hf_bucket"]["enabled"] is True
    config_dir = tmp_path / "config"
    assert not list(config_dir.glob(".model_cache.json.*.tmp"))


def test_atomic_save_replaces_an_existing_file(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    first = store.update(
        {"hf_bucket": {"enabled": False, "bucket": "team/old"}, "storage_mode": "cloud_only"}
    )
    second = store.update(
        {"hf_bucket": {"enabled": True, "bucket": "team/new"}, "storage_mode": "local_cache"}
    )

    assert first["hf_bucket"]["enabled"] is False
    assert second["hf_bucket"]["enabled"] is True
    assert second["hf_bucket"]["bucket"] == "team/new"
    persisted = json.loads((tmp_path / "config" / "model_cache.json").read_text(encoding="utf-8"))
    assert persisted == second


def test_newer_valid_stranded_legacy_temp_is_recovered(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    destination = config_dir / "model_cache.json"
    legacy_temp = config_dir / "model_cache.json.tmp"
    destination.write_text(
        json.dumps(
            {
                "storage_mode": "local_cache",
                "hf_bucket": {"enabled": False, "bucket": "team/models", "prefix": ""},
            }
        ),
        encoding="utf-8",
    )
    legacy_temp.write_text(
        json.dumps(
            {
                "storage_mode": "local_cache",
                "hf_bucket": {"enabled": True, "bucket": "team/models", "prefix": "weights"},
            }
        ),
        encoding="utf-8",
    )
    destination.touch()
    legacy_temp.touch()
    # FAT/exFAT timestamp resolution can be coarse, so make the ordering explicit.
    destination_stat = destination.stat()
    os.utime(
        legacy_temp,
        ns=(destination_stat.st_atime_ns + 1_000_000_000, destination_stat.st_mtime_ns + 1_000_000_000),
    )

    recovered = ModelCacheSettingsStore(tmp_path).get()

    assert recovered["hf_bucket"]["enabled"] is True
    assert recovered["hf_bucket"]["prefix"] == "weights"
    assert not legacy_temp.exists()
    assert json.loads(destination.read_text(encoding="utf-8"))["hf_bucket"]["enabled"] is True


def test_invalid_stranded_legacy_temp_does_not_override_existing_file(tmp_path) -> None:
    store = ModelCacheSettingsStore(tmp_path)
    expected = store.update({"hf_bucket": {"enabled": False, "bucket": "team/models"}})
    legacy_temp = tmp_path / "config" / "model_cache.json.tmp"
    legacy_temp.write_text("{not json", encoding="utf-8")
    destination = tmp_path / "config" / "model_cache.json"
    stat = destination.stat()
    os.utime(
        legacy_temp,
        ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
    )

    assert ModelCacheSettingsStore(tmp_path).get() == expected
    assert legacy_temp.exists()
