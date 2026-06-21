from __future__ import annotations

from pathlib import Path

import pytest

from edmg_studio_backend.services import internal_video as iv
from edmg_studio_backend.services.model_manager import ModelManager


def test_diffusers_from_pretrained_prefers_safetensors() -> None:
    kwargs = iv._diffusers_from_pretrained_kwargs(
        extra={"torch_dtype": "float16", "safety_checker": None}
    )
    assert kwargs["use_safetensors"] is True
    assert kwargs["torch_dtype"] == "float16"
    assert kwargs["safety_checker"] is None


def test_reraise_snapshot_load_error_wraps_missing_weight_message(tmp_path: Path) -> None:
    with pytest.raises(iv.UserFacingError) as exc:
        iv._reraise_snapshot_load_error(
            RuntimeError(
                "Error no file named diffusion_pytorch_model.bin found in directory "
                f"{tmp_path / 'vae'}"
            ),
            tmp_path,
        )
    assert exc.value.code == "MODEL_SNAPSHOT_LOAD_FAILED"


def test_missing_diffusers_components_reports_vae(tmp_path, monkeypatch) -> None:
    def _offline_get(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        __import__("edmg_studio_backend.services.model_manager", fromlist=["requests"]).requests,
        "get",
        _offline_get,
    )
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )
    entry = {
        "id": "hf_sd15_internal",
        "kind": "diffusers",
        "target": {"engine": "internal", "folder": "diffusers"},
    }
    monkeypatch.setattr(manager, "_find_entry", lambda model_id: entry if model_id == "hf_sd15_internal" else None)

    model_dir = manager._internal_models_dir("diffusers") / "hf_sd15_internal"
    model_dir.mkdir(parents=True)
    (model_dir / "model_index.json").write_text(
        '{"_class_name":"StableDiffusionPipeline","vae":["diffusers","AutoencoderKL"],'
        '"unet":["diffusers","UNet2DConditionModel"],"text_encoder":["transformers","CLIPTextModel"]}',
        encoding="utf-8",
    )
    unet_dir = model_dir / "unet"
    unet_dir.mkdir()
    (unet_dir / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")
    text_dir = model_dir / "text_encoder"
    text_dir.mkdir()
    (text_dir / "model.safetensors").write_bytes(b"weights")
    vae_dir = model_dir / "vae"
    vae_dir.mkdir()
    (vae_dir / "config.json").write_text("{}", encoding="utf-8")

    missing = manager.missing_diffusers_components("hf_sd15_internal")

    assert missing == ["vae"]
