from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.integrations import hf_bucket as hf_bucket_integration
from edmg_studio_backend.services import hf_auth as hf_auth_module


class _FakeSecrets:
    def __init__(self, token: str = ""):
        self._token = token

    def get(self, name: str) -> str:
        if name == "hf_token":
            return self._token
        return ""


def _disable_cached_hf_auth(monkeypatch) -> None:
    monkeypatch.setattr(hf_auth_module, "_hf_hub_cache_token", lambda: "")
    monkeypatch.setattr(hf_auth_module, "_hf_cli_token", lambda: "")


def test_describe_status_active_without_explicit_models_dir_env(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.delenv("EDMG_STUDIO_MODELS_DIR", raising=False)

    class _FakeCache:
        label = "Hugging Face bucket"

    monkeypatch.setattr(
        hf_bucket_integration,
        "HFBucketModelCache",
        type(
            "HFBucketModelCache",
            (),
            {"from_runtime": classmethod(lambda cls, **kwargs: _FakeCache())},
        ),
    )

    status = hf_bucket_integration.describe_status(
        models_dir=models_dir,
        secrets_store=_FakeSecrets("settings-token-1234567890"),
    )

    assert status["active"] is True
    assert status["models_dir"] == str(models_dir.resolve())


def test_describe_status_reports_env_configuration(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.setenv("EDMG_HF_BUCKET_PREFIX", "weights")
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_1234567890")
    monkeypatch.delenv("EDMG_STUDIO_MODELS_DIR", raising=False)

    status = hf_bucket_integration.describe_status(
        models_dir=models_dir,
        secrets_store=_FakeSecrets("settings-token-1234567890"),
    )

    assert status["provider"] == "huggingface_bucket"
    assert status["enabled"] is True
    assert status["bucket"] == "team/edmg-models"
    assert status["prefix"] == "weights"
    assert status["models_dir"] == str(models_dir.resolve())
    assert status["has_token"] is True
    assert status["token_source"] == "env:HF_TOKEN"


def test_test_credentials_uses_settings_token_when_env_missing(monkeypatch):
    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("EDMG_HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

    class _FakeApi:
        def list_bucket_tree(self, bucket, *, prefix=None, recursive=False, token=None):
            assert bucket == "team/edmg-models"
            assert token == "settings-token-1234567890"
            return [SimpleNamespace(path="checkpoints/demo.safetensors")]

    class _FakeCache:
        settings = SimpleNamespace(
            bucket="team/edmg-models",
            prefix="",
            models_dir=Path("/tmp/models"),
        )
        _api = _FakeApi()
        _token = "settings-token-1234567890"

        def _bucket_uri(self, remote_dir: str) -> str:
            return f"hf://buckets/team/edmg-models/{remote_dir}".rstrip("/")

    monkeypatch.setattr(
        hf_bucket_integration,
        "settings_from_env",
        lambda **kwargs: SimpleNamespace(
            bucket="team/edmg-models",
            prefix="",
            models_dir=Path("/tmp/models"),
        ),
    )
    monkeypatch.setattr(hf_bucket_integration, "HFBucketModelCache", lambda settings: _FakeCache())

    result = hf_bucket_integration.test_credentials(
        bucket="team/edmg-models",
        models_dir=Path("/tmp/models"),
            secrets_store=_FakeSecrets("settings-token-1234567890"),
    )

    assert result["ok"] is True
    assert result["token_source"] == "settings"
    assert result["sample_paths"] == ["checkpoints/demo.safetensors"]


def test_test_credentials_falls_back_when_list_bucket_tree_missing(monkeypatch):
    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    class _LegacyApi:
        pass

    class _FakeCache:
        settings = SimpleNamespace(
            bucket="team/edmg-models",
            prefix="",
            models_dir=Path("/tmp/models"),
        )
        _api = _LegacyApi()
        _token = "settings-token-1234567890"

        def _bucket_uri(self, remote_dir: str) -> str:
            return f"hf://buckets/team/edmg-models/{remote_dir}".rstrip("/")

    monkeypatch.setattr(
        hf_bucket_integration,
        "settings_from_env",
        lambda **kwargs: SimpleNamespace(
            bucket="team/edmg-models",
            prefix="",
            models_dir=Path("/tmp/models"),
        ),
    )
    monkeypatch.setattr(hf_bucket_integration, "HFBucketModelCache", lambda settings: _FakeCache())
    monkeypatch.setattr(
        hf_bucket_integration,
        "_list_bucket_tree",
        lambda api, bucket_id, *, prefix=None, recursive=False, token=None: [
            SimpleNamespace(path="checkpoints/legacy.safetensors")
        ],
    )

    result = hf_bucket_integration.test_credentials(
        bucket="team/edmg-models",
        models_dir=Path("/tmp/models"),
        secrets_store=_FakeSecrets("settings-token-1234567890"),
    )

    assert result["ok"] is True
    assert result["sample_paths"] == ["checkpoints/legacy.safetensors"]


def test_test_credentials_requires_a_token(monkeypatch):
    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("EDMG_HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="No Hugging Face token found"):
        hf_bucket_integration.test_credentials(
            bucket="team/edmg-models",
            models_dir=Path("/tmp/models"),
            secrets_store=_FakeSecrets(""),
        )


def test_cloud_hf_routes_expose_status_and_test(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    monkeypatch.setattr(
        backend_app,
        "settings",
        SimpleNamespace(
            data_dir=tmp_path / "data",
            models_dir=models_dir,
            worker_autostart=False,
        ),
    )
    monkeypatch.setattr(backend_app.worker, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backend_app,
        "secrets",
        _FakeSecrets("settings-token-1234567890"),
    )
    monkeypatch.setattr(
        hf_bucket_integration,
        "describe_status",
        lambda **kwargs: {"ok": True, "provider": "huggingface_bucket", "enabled": False},
    )
    monkeypatch.setattr(
        hf_bucket_integration,
        "test_credentials",
        lambda **kwargs: {"ok": True, "provider": "huggingface_bucket", "bucket": "team/edmg-models"},
    )

    with TestClient(backend_app.app) as client:
        status = client.get("/v1/cloud/hf/status")
        status.raise_for_status()
        assert status.json()["provider"] == "huggingface_bucket"

        tested = client.post("/v1/cloud/hf/test", json={"bucket": "team/edmg-models", "prefix": "weights"})
        tested.raise_for_status()
        assert tested.json()["bucket"] == "team/edmg-models"
