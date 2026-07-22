from __future__ import annotations

import json
import time
from pathlib import Path

from edmg_studio_backend.integrations.hf_bucket import (
    HFBucketModelCache,
    resolve_models_dir,
)
from edmg_studio_backend.services import hf_auth as hf_auth_module
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


def _disable_cached_hf_auth(monkeypatch) -> None:
    monkeypatch.setattr(hf_auth_module, "_hf_hub_cache_token", lambda: "")
    monkeypatch.setattr(hf_auth_module, "_hf_cli_token", lambda: "")


def _offline_manager(tmp_path, monkeypatch, *, cache: FakeHFBucketModelCache | None = None) -> ModelManager:
    def _offline_get(*_args, **_kwargs):
        raise RuntimeError("offline")

    _disable_cached_hf_auth(monkeypatch)
    for key in (
        "EDMG_AWS_MODEL_CACHE",
        "EDMG_S3_MODEL_CACHE",
        "EDMG_AWS_MODEL_CACHE_BUCKET",
        "EDMG_AWS_MODEL_BUCKET",
        "EDMG_S3_MODEL_CACHE_BUCKET",
        "EDMG_HF_BUCKET_MODEL_CACHE",
        "EDMG_MODEL_STORAGE_MODE",
        "EDMG_AWS_MODEL_CACHE_MODE",
        "EDMG_MODEL_CACHE_MODE",
        "EDMG_HF_TOKEN",
        "HF_TOKEN",
        "HUGGINGFACE_TOKEN",
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
        secrets=_FakeSecrets("settings-token-1234567890"),
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

    _disable_cached_hf_auth(monkeypatch)
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("EDMG_HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

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
            secrets_store=_FakeSecrets("settings-token-1234567890"),
    )

    assert cache is not None
    assert captured["token"] == "settings-token-1234567890"
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


def _wait_for_task(manager: ModelManager, task_id: str, *, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = next((t for t in manager.tasks.list() if t.id == task_id), None)
        if task is not None and task.status in {"done", "failed"}:
            return task
        time.sleep(0.02)
    raise AssertionError("model install task did not finish in time")


def test_install_hf_bucket_source_syncs_internal_controlnet(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch)

    model_id = "hf_bucket_sdxl_controlnet_canny_internal"
    entry = manager._find_entry(model_id)
    assert entry is not None
    assert entry.get("source") == "hf_bucket"
    assert entry.get("hf_bucket_id") == "gulle1155/controlnet-canny-sdxl-1.0-bucket"

    captured: dict = {}

    def _fake_sync(*, bucket, dest, remote_path, token):
        captured.update(
            {"bucket": bucket, "dest": Path(dest), "remote_path": remote_path, "token": token}
        )
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "config.json").write_text("{}", encoding="utf-8")
        (dest / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")
        return True

    monkeypatch.setattr(model_manager_module, "_hf_bucket_download_snapshot", _fake_sync)

    manager.accept_license(model_id, str(entry.get("license_id")))
    task = manager.install(model_id)
    finished = _wait_for_task(manager, task.id)

    assert finished.status == "done", finished.error
    assert captured["bucket"] == "gulle1155/controlnet-canny-sdxl-1.0-bucket"
    assert captured["token"] == "settings-token-1234567890"

    resolved = manager.resolve_installed_path(model_id, materialize_remote=False)
    expected = tmp_path / "home" / "models" / "internal" / "controlnet" / model_id
    assert resolved == expected
    assert (resolved / "config.json").exists()
    assert (resolved / "diffusion_pytorch_model.safetensors").exists()


def test_model_manager_builds_hf_cache_from_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDMG_HF_BUCKET_MODEL_CACHE", "1")
    monkeypatch.setenv("EDMG_HF_BUCKET_ID", "team/edmg-models")
    monkeypatch.delenv("EDMG_STUDIO_MODELS_DIR", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("EDMG_HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

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
        secrets=_FakeSecrets("settings-token-1234567890"),
    )

    cache_chain = getattr(manager.model_cache, "caches", [manager.model_cache])
    assert isinstance(cache_chain[0], _FakeHFCache)
    assert calls[0]["models_dir"] == tmp_path / "home" / "models"
    assert calls[0]["secrets_store"] is not None


def test_model_manager_keeps_s3_as_secondary_cache_when_hf_is_active(tmp_path, monkeypatch) -> None:
    calls: dict[str, list[str]] = {"hf_uploads": [], "s3_uploads": []}

    class _FakeHFCache:
        label = "Hugging Face bucket"
        settings = type("Settings", (), {"bucket": "team/hf", "prefix": "models"})()

        @classmethod
        def from_runtime(cls, *, models_dir=None, secrets_store=None):
            return cls()

        def model_exists(self, entry, path):
            return None

        def upload_model(self, entry, path):
            calls["hf_uploads"].append(str(path))
            return "hf/checkpoints/demo.safetensors"

    class _FakeS3Cache:
        label = "AWS S3 model cache"
        settings = type("Settings", (), {"bucket": "team-s3", "prefix": "models"})()

        @classmethod
        def from_env(cls):
            return cls()

        def model_exists(self, entry, path):
            return "models/checkpoints/demo.safetensors"

        def upload_model(self, entry, path):
            calls["s3_uploads"].append(str(path))
            return "models/checkpoints/demo.safetensors"

    monkeypatch.setattr(model_manager_module, "HFBucketModelCache", _FakeHFCache)
    monkeypatch.setattr(model_manager_module, "S3ModelCache", _FakeS3Cache)
    monkeypatch.setattr(model_manager_module, "AzureModelCache", None)
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "home" / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )

    entry = {"id": "demo", "kind": "checkpoint", "filename": "demo.safetensors"}
    model_path = tmp_path / "home" / "models" / "checkpoints" / "demo.safetensors"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"weights")

    assert "Hugging Face bucket primary" in manager._model_cache_label()
    assert manager._cache_model_exists(entry, model_path) == "models/checkpoints/demo.safetensors"
    assert manager._upload_to_model_cache(
        model_manager_module.ModelTask(id="test", name="upload"),
        entry,
        model_path,
    ) == "hf/checkpoints/demo.safetensors"
    assert calls["hf_uploads"] == [str(model_path)]
    assert calls["s3_uploads"] == [str(model_path)]


def test_snapshot_install_retries_a_rejected_cache_token_with_settings_token(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch)
    cache_token = "oauth-" + ("cache" * 8)
    settings_token = "hf_" + ("settings" * 6)
    manager.secrets = _FakeSecrets(settings_token)
    monkeypatch.setattr(hf_auth_module, "_hf_hub_cache_token", lambda: cache_token)
    monkeypatch.setattr(hf_auth_module, "_hf_cli_token", lambda: "")

    attempts: list[str | bool] = []

    class _RejectedTokenError(RuntimeError):
        response = type("Response", (), {"status_code": 401})()

    def _fake_snapshot_download(*, local_dir, token, **_kwargs):
        attempts.append(token)
        if token == cache_token:
            raise _RejectedTokenError("401 Client Error: invalid user token")
        assert token == settings_token
        target = Path(local_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_index.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(model_manager_module, "snapshot_download", _fake_snapshot_download)
    entry = {
        "id": "hf_auth_snapshot",
        "name": "HF authenticated snapshot",
        "kind": "diffusers",
        "source": "hf",
        "hf_repo_id": "example/internal-model",
        "target": {"engine": "internal", "folder": "diffusers"},
    }
    task = model_manager_module.ModelTask(id="test", name="install")

    manager._install_file_model(task, entry)

    assert attempts == [cache_token, settings_token]
    assert (tmp_path / "home" / "models" / "internal" / "diffusers" / "hf_auth_snapshot" / "model_index.json").exists()
    assert "hf_cache was rejected" in task.last_log


def test_snapshot_install_falls_back_when_hf_transfer_is_enabled_but_missing(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch)
    monkeypatch.setattr(model_manager_module.hf_hub_constants, "HF_HUB_ENABLE_HF_TRANSFER", True)
    monkeypatch.setattr(model_manager_module.hf_hub_constants, "HF_HUB_DISABLE_XET", False)
    monkeypatch.setenv("EDMG_HF_TRANSFER_CONCURRENCY", "3")
    attempts = 0
    xet_disabled_during_download: list[bool] = []

    def _fake_snapshot_download(*, local_dir, **_kwargs):
        nonlocal attempts
        attempts += 1
        xet_disabled_during_download.append(model_manager_module.hf_hub_constants.HF_HUB_DISABLE_XET)
        if attempts == 1:
            raise ValueError(
                "Fast download using 'hf_transfer' is enabled "
                "(HF_HUB_ENABLE_HF_TRANSFER=1) but 'hf_transfer' package is not available "
                "in your environment. Try `pip install hf_transfer`."
            )
        target = Path(local_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_index.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(model_manager_module, "snapshot_download", _fake_snapshot_download)
    entry = {
        "id": "hf_transfer_fallback",
        "name": "HF transfer fallback",
        "kind": "diffusers",
        "source": "hf",
        "hf_repo_id": "example/internal-model",
        "target": {"engine": "internal", "folder": "diffusers"},
    }
    task = model_manager_module.ModelTask(id="test", name="install")

    manager._install_file_model(task, entry)

    assert attempts == 2
    assert xet_disabled_during_download == [True, True]
    assert model_manager_module.hf_hub_constants.HF_TRANSFER_CONCURRENCY == 3
    assert model_manager_module.hf_hub_constants.HF_HUB_ENABLE_HF_TRANSFER is False
    assert model_manager_module.hf_hub_constants.HF_HUB_DISABLE_XET is False
    assert "continuing with the standard Hugging Face downloader" in task.last_log
    assert (
        tmp_path
        / "home"
        / "models"
        / "internal"
        / "diffusers"
        / "hf_transfer_fallback"
        / "model_index.json"
    ).exists()


def test_file_install_retries_anonymously_after_rejected_hf_auth(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch)
    cache_token = "oauth-" + ("cache" * 8)
    manager.secrets = _FakeSecrets("")
    monkeypatch.setattr(hf_auth_module, "_hf_hub_cache_token", lambda: cache_token)
    monkeypatch.setattr(hf_auth_module, "_hf_cli_token", lambda: "")

    attempts: list[dict[str, str]] = []

    def _fake_download_stream(_task, _url, dest, headers=None):
        attempts.append(dict(headers or {}))
        if headers:
            raise model_manager_module.UserFacingError("Download unauthorized")
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"weights")

    monkeypatch.setattr(manager, "_download_stream", _fake_download_stream)
    entry = {
        "id": "hf_auth_checkpoint",
        "name": "HF public checkpoint",
        "kind": "checkpoint",
        "source": "hf",
        "filename": "model.safetensors",
        "hf_url": "https://huggingface.co/example/model/resolve/main/model.safetensors",
        "target": {"engine": "comfyui", "folder": "checkpoints"},
    }
    task = model_manager_module.ModelTask(id="test", name="install")

    manager._install_file_model(task, entry)

    assert len(attempts) == 2
    assert attempts[0]["Authorization"] == f"Bearer {cache_token}"
    assert attempts[1] == {}
    assert (tmp_path / "home" / "models" / "checkpoints" / "model.safetensors").read_bytes() == b"weights"
    assert "Downloaded without Hugging Face authentication" in task.last_log
