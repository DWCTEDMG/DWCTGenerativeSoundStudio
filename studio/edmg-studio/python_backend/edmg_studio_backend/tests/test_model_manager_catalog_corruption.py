"""Catalog install probes must tolerate WinError 1392-style OSError from Path.exists()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from edmg_studio_backend.services.model_manager import (
    ModelManager,
    _CORRUPTED_QUARANTINE_SUFFIX,
    _path_exists_safe,
)


def _manager(tmp_path: Path) -> ModelManager:
    return ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )


def test_path_exists_safe_returns_false_on_oserror() -> None:
    real_exists = Path.exists

    def exists_side_effect(self: Path) -> bool:
        if self.name == "model_index.json":
            raise OSError(1392, "The file or directory is corrupted and unreadable")
        return real_exists(self)

    target = Path("E:/fake/hf_sdxl_internal/model_index.json")
    with patch.object(Path, "exists", exists_side_effect):
        assert _path_exists_safe(target) is False


def test_diffusers_snapshot_complete_skips_unreadable_model_index(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    snapshot = tmp_path / "models" / "internal" / "diffusers" / "hf_sdxl_internal"
    snapshot.mkdir(parents=True)
    model_index = snapshot / "model_index.json"
    model_index.write_text("{}", encoding="utf-8")

    real_exists = Path.exists

    def exists_side_effect(self: Path) -> bool:
        if self == model_index:
            raise OSError(1392, "The file or directory is corrupted and unreadable")
        return real_exists(self)

    with patch.object(Path, "exists", exists_side_effect):
        assert manager._diffusers_snapshot_complete(snapshot) is False

    quarantined = snapshot.with_name(f"{snapshot.name}{_CORRUPTED_QUARANTINE_SUFFIX}")
    assert quarantined.is_dir()
    assert not snapshot.exists()


def test_installed_map_marks_unreadable_internal_diffusers_not_installed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    snapshot = tmp_path / "models" / "internal" / "diffusers" / "hf_sdxl_internal"
    snapshot.mkdir(parents=True)
    model_index = snapshot / "model_index.json"
    model_index.write_text(
        '{"_class_name":"StableDiffusionXLPipeline","unet":["diffusers","UNet2DConditionModel"]}',
        encoding="utf-8",
    )

    entry = {
        "id": "hf_sdxl_internal",
        "kind": "diffusers",
        "source": "hf",
        "target": {"engine": "internal", "folder": "diffusers"},
    }

    real_exists = Path.exists

    def exists_side_effect(self: Path) -> bool:
        # Parent dir may report present; probing model_index.json raises like WinError 1392.
        if self == model_index:
            raise OSError(1392, "The file or directory is corrupted and unreadable")
        return real_exists(self)

    with patch.object(Path, "exists", exists_side_effect):
        installed = manager._installed_map([entry])

    assert installed["hf_sdxl_internal"] is False


def test_catalog_survives_unreadable_diffusers_snapshot(tmp_path: Path, monkeypatch) -> None:
    manager = _manager(tmp_path)
    snapshot = tmp_path / "models" / "internal" / "diffusers" / "hf_sdxl_internal"
    snapshot.mkdir(parents=True)
    model_index = snapshot / "model_index.json"
    model_index.write_text("{}", encoding="utf-8")

    def _offline_get(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        "edmg_studio_backend.services.model_manager.requests.get",
        _offline_get,
    )

    real_exists = Path.exists

    def exists_side_effect(self: Path) -> bool:
        if self == model_index:
            raise OSError(1392, "The file or directory is corrupted and unreadable")
        return real_exists(self)

    with patch.object(Path, "exists", exists_side_effect):
        result = manager.catalog()

    assert "catalog" in result
    assert "installed" in result
    assert result["installed"].get("hf_sdxl_internal") is False
