from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from edmg_studio_backend.integrations.aws import S3ModelCache, S3ModelCacheSettings
from edmg_studio_backend.services import model_manager as model_manager_module
from edmg_studio_backend.services.model_manager import ModelManager, ModelTask


class FakeS3ModelCache:
    label = "AWS S3 model cache"

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        directories: dict[str, dict[str, bytes]] | None = None,
    ):
        self.objects = dict(objects or {})
        self.directories = dict(directories or {})
        self.settings = SimpleNamespace(
            bucket="test-bucket",
            prefix="models",
            region="us-east-1",
            endpoint_url="",
        )
        self.downloads: list[str] = []

    def _key_for(self, entry: dict, path: Path, *, archive: bool = False) -> str:
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        uri = str(
            entry.get("s3_uri")
            or entry.get("aws_s3_uri")
            or target.get("s3_uri")
            or target.get("aws_s3_uri")
            or ""
        ).strip()
        if uri:
            parsed = urlparse(uri)
            return str(parsed.path).lstrip("/")

        key = str(
            entry.get("s3_key")
            or entry.get("aws_s3_key")
            or entry.get("object_key")
            or target.get("s3_key")
            or target.get("aws_s3_key")
            or target.get("object_key")
            or ""
        ).strip()
        if key:
            return key.strip("/")

        folder = str(target.get("folder") or "models").strip("/")
        model_id = str(entry.get("id") or path.stem)
        filename = path.name
        if archive and not filename.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz")):
            filename = f"{filename}.zip"
        return f"models/{folder}/{model_id}/{filename}"

    def model_exists(self, entry: dict, path: Path) -> str | None:
        key = self._key_for(entry, path)
        return key if key in self.objects else None

    def download_model(self, entry: dict, dest: Path) -> bool:
        key = self._key_for(entry, dest)
        payload = self.objects.get(key)
        if payload is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        self.downloads.append(key)
        return True

    def upload_model(self, entry: dict, path: Path) -> str:
        key = self._key_for(entry, path)
        self.objects[key] = path.read_bytes()
        return key

    def model_directory_exists(self, entry: dict, path: Path) -> str | None:
        key = self._key_for(entry, path, archive=True)
        return key if key in self.directories else None

    def download_model_directory(self, entry: dict, dest: Path) -> bool:
        key = self._key_for(entry, dest, archive=True)
        files = self.directories.get(key)
        if files is None:
            return False
        dest.mkdir(parents=True, exist_ok=True)
        for relative, payload in files.items():
            out = dest / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
        self.downloads.append(key)
        return True

    def upload_model_directory(self, entry: dict, path: Path) -> str:
        key = self._key_for(entry, path, archive=True)
        self.directories[key] = {
            str(candidate.relative_to(path).as_posix()): candidate.read_bytes()
            for candidate in path.rglob("*")
            if candidate.is_file()
        }
        return key


def _offline_manager(
    tmp_path,
    monkeypatch,
    objects: dict[str, bytes] | None = None,
    directories: dict[str, dict[str, bytes]] | None = None,
) -> ModelManager:
    def _offline_get(*_args, **_kwargs):
        raise RuntimeError("offline")

    for key in (
        "EDMG_AWS_MODEL_CACHE",
        "EDMG_S3_MODEL_CACHE",
        "EDMG_AWS_MODEL_CACHE_BUCKET",
        "EDMG_AWS_MODEL_BUCKET",
        "EDMG_S3_MODEL_CACHE_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(model_manager_module.requests, "get", _offline_get)
    monkeypatch.setenv("EDMG_MODEL_STORAGE_MODE", "local_cache")
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )
    manager.model_cache = FakeS3ModelCache(objects, directories)
    return manager


def _checkpoint_entry(model_id: str, filename: str, **extra) -> dict:
    entry = {
        "id": model_id,
        "name": "Hosted checkpoint",
        "kind": "checkpoint",
        "source": "hf",
        "filename": filename,
        "target": {"engine": "comfyui", "folder": "checkpoints"},
        "license_id": "test",
        "license_url": "",
    }
    entry.update(extra)
    return entry


def _internal_entry(model_id: str, **extra) -> dict:
    entry = {
        "id": model_id,
        "name": "Hosted internal model",
        "kind": "diffusers",
        "source": "hf",
        "target": {"engine": "internal", "folder": "diffusers"},
        "license_id": "test",
        "license_url": "",
    }
    entry.update(extra)
    return entry


def _diffusers_snapshot_files() -> dict[str, bytes]:
    model_index = {
        "_class_name": "StableDiffusionPipeline",
        "scheduler": ["diffusers", "DDIMScheduler"],
        "unet": ["diffusers", "UNet2DConditionModel"],
    }
    return {
        "model_index.json": json.dumps(model_index).encode("utf-8"),
        "unet/diffusion_pytorch_model.safetensors": b"weights",
    }


def test_s3_object_location_accepts_explicit_uri_key_and_archive_default() -> None:
    cache = S3ModelCache.__new__(S3ModelCache)
    cache.settings = S3ModelCacheSettings(bucket="default-bucket", prefix="models")

    uri_entry = {"s3_uri": "s3://hosted-bucket/path/to/model.safetensors"}
    assert cache.object_location_for(uri_entry, Path("model.safetensors")) == (
        "hosted-bucket",
        "path/to/model.safetensors",
    )

    key_entry = {"s3_key": "custom/path/model.safetensors"}
    assert cache.object_location_for(key_entry, Path("model.safetensors")) == (
        "default-bucket",
        "custom/path/model.safetensors",
    )

    archive_entry = {"id": "internal_demo", "target": {"folder": "diffusers"}}
    assert cache.object_key_for(archive_entry, Path("internal_demo"), archive=True) == (
        "models/diffusers/internal_demo/internal_demo.zip"
    )


def test_resolve_comfy_asset_materializes_cloud_record(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch, {"hosted/demo.safetensors": b"weights"})
    entry = _checkpoint_entry("hosted_demo", "demo.safetensors")
    manager.add_user_model(entry)
    manager._record_cloud_model(entry, "hosted/demo.safetensors", mode="cloud_only")

    assert manager.installed_path("hosted_demo") is None

    asset = manager.resolve_comfy_asset("hosted_demo", folder="checkpoints", allowed_kinds={"checkpoint"})

    resolved = Path(str(asset["path"]))
    assert resolved == tmp_path / "models" / "checkpoints" / "demo.safetensors"
    assert resolved.read_bytes() == b"weights"
    assert manager.model_cache.downloads == ["hosted/demo.safetensors"]
    assert manager.installed_path("hosted_demo") == resolved


def test_s3_source_installs_to_local_model_path(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(tmp_path, monkeypatch, {"hosted/source.safetensors": b"s3-weights"})
    entry = _checkpoint_entry(
        "s3_source",
        "source.safetensors",
        source="s3",
        s3_uri="s3://test-bucket/hosted/source.safetensors",
    )
    manager.add_user_model(entry)

    task = ModelTask(id="test", name="install")
    manager._install_file_model(task, entry)

    resolved = tmp_path / "models" / "checkpoints" / "source.safetensors"
    assert resolved.read_bytes() == b"s3-weights"
    assert manager._cloud_model_record("s3_source")["object"] == "hosted/source.safetensors"
    assert task.progress == 1.0


def test_internal_snapshot_materializes_from_cloud_record(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(
        tmp_path,
        monkeypatch,
        directories={"hosted/internal.zip": _diffusers_snapshot_files()},
    )
    entry = _internal_entry("internal_cloud")
    manager.add_user_model(entry)
    manager._record_cloud_model(entry, "hosted/internal.zip", mode="cloud_only")

    assert manager.installed_path("internal_cloud") is None

    resolved = manager.resolve_installed_path("internal_cloud", materialize_remote=True)

    assert resolved == tmp_path / "models" / "internal" / "diffusers" / "internal_cloud"
    assert (resolved / "model_index.json").exists()
    assert (resolved / "unet" / "diffusion_pytorch_model.safetensors").read_bytes() == b"weights"
    assert manager.model_cache.downloads == ["hosted/internal.zip"]
    assert manager.installed_path("internal_cloud") == resolved


def test_s3_source_internal_snapshot_installs_to_local_path(tmp_path, monkeypatch) -> None:
    manager = _offline_manager(
        tmp_path,
        monkeypatch,
        directories={"hosted/source-internal.zip": _diffusers_snapshot_files()},
    )
    entry = _internal_entry(
        "s3_internal_source",
        source="s3",
        s3_uri="s3://test-bucket/hosted/source-internal.zip",
    )
    manager.add_user_model(entry)

    task = ModelTask(id="test", name="install")
    manager._install_file_model(task, entry)

    resolved = tmp_path / "models" / "internal" / "diffusers" / "s3_internal_source"
    assert (resolved / "model_index.json").exists()
    assert manager._cloud_model_record("s3_internal_source")["object"] == "hosted/source-internal.zip"
    assert task.progress == 1.0
