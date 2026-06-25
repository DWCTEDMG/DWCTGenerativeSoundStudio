from __future__ import annotations

import json

import pytest

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services.model_manager import ModelManager
from edmg_studio_backend.services.tensorrt_standalone import (
    _find_unet_engine,
    _infer_base_model_ref,
    _validate_profile,
)


def _write_bundle(tmp_path):
    bundle = tmp_path / "trt_bundle"
    (bundle / "engine").mkdir(parents=True)
    (bundle / "onnx" / "unet").mkdir(parents=True)
    (bundle / "engine" / "unet.engine").write_bytes(b"")
    (bundle / "engine" / "unet_b1_workspace4096.engine").write_bytes(b"engine")
    (bundle / "onnx" / "unet" / "config.json").write_text(
        json.dumps({"sample_size": 64}),
        encoding="utf-8",
    )
    return bundle


def test_find_unet_engine_ignores_zero_byte_engine(tmp_path):
    bundle = _write_bundle(tmp_path)

    engine = _find_unet_engine(bundle)

    assert engine.name == "unet_b1_workspace4096.engine"


def test_validate_profile_rejects_mismatched_image_size(tmp_path):
    bundle = _write_bundle(tmp_path)

    with pytest.raises(UserFacingError) as exc:
        _validate_profile(bundle, {"width": 1024, "height": 1024, "batch_size": 1})

    assert exc.value.code == "TRT_PROFILE_MISMATCH"
    assert "512x512" in (exc.value.hint or "")


def test_infer_base_model_ref_prefers_export_snapshot(tmp_path):
    bundle = _write_bundle(tmp_path)
    snapshot = tmp_path / "hf_snapshot"
    (snapshot / "unet").mkdir(parents=True)
    (snapshot / "model_index.json").write_text("{}", encoding="utf-8")
    (bundle / "onnx" / "unet" / "config.json").write_text(
        json.dumps({"sample_size": 64, "_name_or_path": str(snapshot / "unet")}),
        encoding="utf-8",
    )

    assert _infer_base_model_ref(bundle, {}) == str(snapshot)


def test_model_manager_resolves_local_runtime_bundle_directory(tmp_path):
    bundle = _write_bundle(tmp_path)
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )
    entry = {
        "id": "local_trt",
        "kind": "runtime_bundle",
        "source": "local",
        "source_path": str(bundle),
        "target": {"engine": "runtime_bundle", "folder": "tensorrt"},
    }

    mode, dest = manager._models_dest(entry)

    assert mode == "snapshot"
    assert dest.name == "local_trt"
    assert manager._local_installed_path(entry) == bundle
    assert manager._installed_map([entry])["local_trt"] is True
