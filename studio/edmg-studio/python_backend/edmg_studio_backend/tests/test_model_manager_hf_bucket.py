from __future__ import annotations

import json
from pathlib import Path

from edmg_studio_backend.integrations.hf_bucket import (
    HFBucketModelCache,
    resolve_models_dir,
)
from edmg_studio_backend.services import model_manager as model_manager_module
from edmg_studio_backend.services.model_manager import ModelManager


class _FakeSecrets:
    def __init__(self, token: str = ""):
        self._token = token

    def get(self, name: str) -> str:
        if name == "hf_token":
            return self._token
        return ""


class FakeHFBucketModelCache:
    label = "Hugging Face bucket"

    def __init__(self, *, remote_dirs: set[str] | None = None):
        self.remote_dirs = set(remote_dirs or [])
        self.settings = type(
            "Settings",
            (),
            {"bucket": "team/edmg-models", "prefix": "", "models_dir": Path("/tmp/models")},
        )()

    def model_directory_exists(self, entry: dict, path: Path) -> str | None:
        model_id = str(entry.get("id") or path.name)
        remote = f"internal/diffusers/{model_id}"
        return remote if remote in self.remote_dirs else None

    def download_model_directory(self, entry: dict, dest: Path) -> bool:
        remote = self.model_directory_exists(entry, dest)
        if not remote:
            return False
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "model_index.json").write_text(
            json.dumps(
                {
                    "_class_name": "StableDiffusionXLPipeline",
                    "scheduler": ["diffusers", "DDIMScheduler"],
                    "unet": ["diffusers", "UNet2DConditionModel"],
                }
            ),
            encoding="utf-8",
        )
        unet_dir = dest / "unet"
        unet_dir.mkdir(parents=True, exist_ok=True)
        (unet_dir / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")
        return True


def _offline_manager(tmp_path, monkeypatch, *, cache: FakeHFBucketModelCache | None = None) -> ModelManager:
    def _offline_get(*_args, **_kwargs):
        raise RuntimeError("offline")

    for key in (
        "EDMG_AWS_MODEL_CACHE",
        "EDMG_S3_MODEL_CACHE",
        "EDMG_AWS_MODEL_CACHE_BUCKET",
        "EDMG_AWS_MODEL_BUCKET",
        "EDMG_S3_MODEL_CACHE_BUCKET",
        "EDMG_HF_BUCKET_MODEL_CACHE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(model_manager_module.requests, "get", _offline_get)
    monkeypatch.setenv("EDMG_STUDIO_HOME", str(tmp_path / "home"))
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "home" / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
        secrets=_FakeSecrets("settings-token"),
    )
    if cache is not None:
        manager.model_cache = cache
    return manager


def test_resolve_models_dir_falls_back_to_studio_home(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EDMG_STUDIO_MODELS_DIR", raising=False)
    monkeypatch.setenv("EDMG_STUDIO_HOME", str(tmp_path / "studio-home"))

    resolved = resolve_models_dir()

    assert resolved == (tmp_path / "studio-home" / "models").resolve()


def test_hf_bucket_from_runtime_uses_settings_token(tmp_path, monkeypatch) -> None:
    from edmg_studio_backend.integrations import hf_bucket as hf_bucket_module

    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("EDMG_HF_TOKEN", raising=False)

    captured: dict = {}

    def _fake_settings_from_env(**kwargs):
        captured.update(kwargs)
        return hf_bucket_module.HFBucketCacheSettings(
            bucket="team/edmg-models",
            models_dir=Path(kwargs["models_dir"]),
            token=str(kwargs.get("token") or ""),
        )

    monkeypatch.setattr(hf_bucket_module, "settings_from_env", _fake_settings_from_env)

    cache = HFBucketModelCache.from_runtime(
        models_dir=tmp_path / "models",
        secrets_store=_FakeSecrets("settings-token"),
    )

    assert cache is not None
    assert captured["token"] == "settings-token"
    assert captured["models_dir"] == tmp_path / "models"


def test_model_manager_detects_internal_model_in_hf_bucket(tmp_path, monkeypatch) -> None:
    cache = FakeHFBucketModelCache(remote_dirs={"internal/diffusers/hf_sdxl_internal"})
    manager = _offline_manager(tmp_path, monkeypatch, cache=cache)

    assert manager.installed_path("hf_sdxl_internal") is None
    assert manager.is_model_available("hf_sdxl_internal", probe_remote=True) is True
    assert manager.installed_internal_models()["hf_sdxl_internal"] is True

    resolved = manager.resolve_installed_path("hf_sdxl_internal", materialize_remote=True)

    assert resolved == tmp_path / "home" / "models" / "internal" / "diffusers" / "hf_sdxl_internal"
    assert (resolved / "model_index.json").exists()
    assert manager.installed_path("hf_sdxl_internal") == resolved


def test_model_manager_builds_hf_cache_from_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.delenv("EDMG_STUDIO_MODELS_DIR", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    calls: list[dict] = []

    class _FakeHFCache:
        label = "Hugging Face bucket"

        @classmethod
        def from_runtime(cls, *, models_dir=None, secrets_store=None):
            calls.append({"models_dir": models_dir, "secrets_store": secrets_store})
            return cls()

    monkeypatch.setattr(model_manager_module, "HFBucketModelCache", _FakeHFCache)
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "home" / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
        secrets=_FakeSecrets("settings-token"),
    )

    assert isinstance(manager.model_cache, _FakeHFCache)
    assert calls[0]["models_dir"] == tmp_path / "home" / "models"
    assert calls[0]["secrets_store"] is not None
