from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import tensorrt_standalone as standalone_module
from edmg_studio_backend.services.model_manager import ModelManager
from edmg_studio_backend.services.tensorrt_bundle_migration import (
    MANIFEST_FILENAME,
    REQUIRED_ONNX_FILES,
    TensorRTBundleContract,
    TensorRTBundleMigration,
)
from edmg_studio_backend.services.tensorrt_standalone import (
    _component_ref,
    _find_unet_engine,
    _infer_base_model_ref,
    _resolve_bundle_contract,
    _validate_profile,
)

BASE_MODEL_ID = "runwayml/stable-diffusion-v1-5"
BASE_MODEL_REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"


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


def _write_ready_contract(tmp_path: Path) -> TensorRTBundleContract:
    models_dir = tmp_path / "models"
    legacy = models_dir / "internal" / "tensorrt"
    legacy.mkdir(parents=True)
    for name in (
        "text_encoder.engine",
        "unet_b1_workspace4096.engine",
        "vae_decoder.engine",
        "vae_encoder.engine",
    ):
        (legacy / name).write_bytes(f"verified-{name}".encode())
    migration = TensorRTBundleMigration(models_dir)
    migration.migrate()

    onnx_rows: list[dict[str, object]] = []
    for role, relative in REQUIRED_ONNX_FILES.items():
        path = migration.canonical_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_index":
            payload = json.dumps({"_name_or_path": BASE_MODEL_ID}).encode()
        elif role == "unet_config":
            payload = json.dumps(
                {
                    "sample_size": 64,
                    "_name_or_path": (
                        "C:/hf/models--runwayml--stable-diffusion-v1-5/"
                        f"snapshots/{BASE_MODEL_REVISION}/unet"
                    ),
                }
            ).encode()
        elif path.suffix == ".json":
            payload = b"{}"
        else:
            payload = f"verified-{role}".encode()
        path.write_bytes(payload)
        onnx_rows.append(
            {
                "role": role,
                "path": relative,
                "size_bytes": len(payload),
                "mtime_ns": path.stat().st_mtime_ns,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    manifest_path = migration.canonical_root / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["profile"] = {
        "width": 512,
        "height": 512,
        "batch_size": 1,
        "sample_size": 64,
        "verified": True,
    }
    manifest["base_model"] = {
        "id": BASE_MODEL_ID,
        "revision": BASE_MODEL_REVISION,
        "verified": True,
    }
    manifest["onnx"] = {"verified": True, "files": onnx_rows}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return migration.validate_bundle_root(
        migration.canonical_root,
        verify_engine_hashes=True,
    )


def test_find_unet_engine_uses_exact_manifest_role(tmp_path):
    contract = _write_ready_contract(tmp_path)

    engine = _find_unet_engine(contract)

    assert engine.name == "unet_b1_workspace4096.engine"


def test_validate_profile_rejects_mismatched_image_size(tmp_path):
    contract = _write_ready_contract(tmp_path)

    with pytest.raises(UserFacingError) as exc:
        _validate_profile(contract, {"width": 1024, "height": 1024, "batch_size": 1})

    assert exc.value.code == "TRT_PROFILE_MISMATCH"
    assert "512x512" in (exc.value.hint or "")


def test_infer_base_model_ref_uses_pinned_manifest_coordinates(tmp_path):
    contract = _write_ready_contract(tmp_path)

    assert _infer_base_model_ref(contract) == (BASE_MODEL_ID, BASE_MODEL_REVISION)


def test_remote_component_loads_are_pinned_to_manifest_revision():
    reference, kwargs = _component_ref(BASE_MODEL_ID, BASE_MODEL_REVISION, "text_encoder")

    assert reference == BASE_MODEL_ID
    assert kwargs == {
        "subfolder": "text_encoder",
        "revision": BASE_MODEL_REVISION,
    }


def test_runtime_resolver_rejects_unmanifested_external_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    bundle = _write_bundle(tmp_path)
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )
    monkeypatch.setenv("EDMG_TENSORRT_SD15_BUNDLE", str(bundle))
    monkeypatch.delenv("EDMG_TENSORRT_MODEL_DIR", raising=False)
    monkeypatch.setattr(standalone_module, "_runtime_model_manager", lambda: manager)

    with pytest.raises(UserFacingError) as exc:
        _resolve_bundle_contract("local_sd15_tensorrt_bundle", {})

    assert exc.value.code == "TRT_BUNDLE_UNVERIFIED"


def test_runtime_resolver_returns_same_verified_contract_as_model_manager(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    expected = _write_ready_contract(tmp_path / "ready")
    manager = ModelManager(
        tmp_path / "data",
        tmp_path / "manager_models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )
    monkeypatch.setenv("EDMG_TENSORRT_SD15_BUNDLE", str(expected.root))
    monkeypatch.delenv("EDMG_TENSORRT_MODEL_DIR", raising=False)
    monkeypatch.setattr(standalone_module, "_runtime_model_manager", lambda: manager)

    resolved = _resolve_bundle_contract("local_sd15_tensorrt_bundle", {})

    assert resolved.root == expected.root
    assert resolved.engine_paths["unet"] == expected.engine_paths["unet"]
    assert resolved.base_model_id == BASE_MODEL_ID
    assert resolved.base_model_revision == BASE_MODEL_REVISION


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
