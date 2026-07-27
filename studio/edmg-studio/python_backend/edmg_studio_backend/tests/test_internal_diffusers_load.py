from __future__ import annotations

from pathlib import Path

import pytest

from edmg_studio_backend.services import internal_video as iv
from edmg_studio_backend.services.model_manager import ModelManager
from edmg_studio_backend.tests.safetensors_test_utils import (
    write_minimal_safetensors,
)


def _write_lfs_pointer(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
        "size 123456\n",
        encoding="utf-8",
    )


def test_diffusers_from_pretrained_prefers_safetensors() -> None:
    kwargs = iv._diffusers_from_pretrained_kwargs(
        extra={"torch_dtype": "float16", "safety_checker": None}
    )
    assert kwargs["use_safetensors"] is True
    assert kwargs["torch_dtype"] == "float16"
    assert kwargs["safety_checker"] is None


def test_diffusers_model_load_kwargs_uses_real_fp16_bin_when_safetensors_is_lfs_pointer(tmp_path: Path) -> None:
    _write_lfs_pointer(tmp_path / "unet" / "diffusion_pytorch_model.fp16.safetensors")
    (tmp_path / "unet" / "diffusion_pytorch_model.fp16.bin").write_bytes(b"real fp16 bin weights")
    (tmp_path / "text_encoder").mkdir(parents=True)
    write_minimal_safetensors(
        tmp_path / "text_encoder" / "model.fp16.safetensors"
    )

    kwargs = iv._diffusers_model_load_kwargs(tmp_path, "cuda")

    assert kwargs["variant"] == "fp16"
    assert kwargs["use_safetensors"] is False


def test_diffusers_model_load_kwargs_uses_real_fp16_bin_when_safetensors_peer_is_missing(tmp_path: Path) -> None:
    (tmp_path / "unet").mkdir(parents=True)
    (tmp_path / "unet" / "diffusion_pytorch_model.fp16.bin").write_bytes(b"real fp16 bin weights")
    (tmp_path / "text_encoder").mkdir(parents=True)
    write_minimal_safetensors(
        tmp_path / "text_encoder" / "model.fp16.safetensors"
    )

    kwargs = iv._diffusers_model_load_kwargs(tmp_path, "cuda")

    assert kwargs["variant"] == "fp16"
    assert kwargs["use_safetensors"] is False


def test_diffusers_model_load_kwargs_keeps_real_fp16_safetensors_preferred(tmp_path: Path) -> None:
    (tmp_path / "unet").mkdir(parents=True)
    write_minimal_safetensors(
        tmp_path / "unet" / "diffusion_pytorch_model.fp16.safetensors"
    )

    kwargs = iv._diffusers_model_load_kwargs(tmp_path, "cuda")

    assert kwargs["variant"] == "fp16"
    assert kwargs["use_safetensors"] is True


def test_diffusers_model_load_kwargs_prefers_complete_default_over_leftover_fp16(
    tmp_path: Path,
) -> None:
    (tmp_path / "model_index.json").write_text(
        '{"unet":["diffusers","UNet2DConditionModel"]}',
        encoding="utf-8",
    )
    write_minimal_safetensors(
        tmp_path / "unet" / "diffusion_pytorch_model.safetensors"
    )
    write_minimal_safetensors(
        tmp_path / "unet" / "diffusion_pytorch_model.fp16.safetensors"
    )

    kwargs = iv._diffusers_model_load_kwargs(tmp_path, "cuda")

    assert "variant" not in kwargs
    assert kwargs["use_safetensors"] is True


def test_diffusers_model_load_kwargs_uses_complete_default_bin_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / "model_index.json").write_text(
        '{"unet":["diffusers","UNet2DConditionModel"]}',
        encoding="utf-8",
    )
    unet = tmp_path / "unet"
    unet.mkdir()
    (unet / "diffusion_pytorch_model.bin").write_bytes(b"default bin weights")
    corrupt_safe = unet / "diffusion_pytorch_model.safetensors"
    corrupt_safe.write_bytes((100).to_bytes(8, "little") + b"{}")

    kwargs = iv._diffusers_model_load_kwargs(tmp_path, "cuda")

    assert "variant" not in kwargs
    assert kwargs["use_safetensors"] is False


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


def test_reraise_snapshot_load_error_wraps_git_lfs_message(tmp_path: Path) -> None:
    with pytest.raises(iv.UserFacingError) as exc:
        iv._reraise_snapshot_load_error(
            RuntimeError("You seem to have cloned a repository without having git-lfs installed."),
            tmp_path,
        )
    assert exc.value.code == "MODEL_SNAPSHOT_LFS_POINTER"


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
    write_minimal_safetensors(
        unet_dir / "diffusion_pytorch_model.safetensors"
    )
    text_dir = model_dir / "text_encoder"
    text_dir.mkdir()
    write_minimal_safetensors(text_dir / "model.safetensors")
    vae_dir = model_dir / "vae"
    vae_dir.mkdir()
    (vae_dir / "config.json").write_text("{}", encoding="utf-8")

    missing = manager.missing_diffusers_components("hf_sd15_internal")

    assert missing == ["vae"]
