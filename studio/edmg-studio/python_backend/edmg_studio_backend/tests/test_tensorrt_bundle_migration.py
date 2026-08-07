from __future__ import annotations

import hashlib
import json
import time
from collections import namedtuple
from pathlib import Path

import pytest

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import tensorrt_bundle_migration as migration_module
from edmg_studio_backend.services.model_manager import ModelManager
from edmg_studio_backend.services.tensorrt_bundle_migration import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    MODEL_ID,
    REQUIRED_ONNX_FILES,
    TensorRTBundleMigration,
    TensorRTMigrationCancelled,
)

ENGINE_PAYLOADS = {
    "text_encoder.engine": b"text-encoder-engine",
    "unet_b1_workspace4096.engine": b"unet-engine" * 64,
    "vae_decoder.engine": b"vae-decoder-engine",
    "vae_encoder.engine": b"vae-encoder-engine",
}
BASE_MODEL_ID = "runwayml/stable-diffusion-v1-5"
BASE_MODEL_REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"


def _write_legacy_engines(models_dir: Path, payloads: dict[str, bytes] | None = None) -> Path:
    root = models_dir / "internal" / "tensorrt"
    root.mkdir(parents=True)
    for name, payload in (payloads or ENGINE_PAYLOADS).items():
        (root / name).write_bytes(payload)
    return root


def _manager(tmp_path: Path) -> ModelManager:
    return ModelManager(
        tmp_path / "data",
        tmp_path / "models",
        tmp_path / "external",
        "http://127.0.0.1:8188",
        "http://127.0.0.1:11434",
    )


def _promote_ready_bundle(
    migration: TensorRTBundleMigration,
    *,
    sample_size: int | list[int] = 64,
    base_model_id: str = BASE_MODEL_ID,
    base_model_revision: str | None = BASE_MODEL_REVISION,
    profile_verified: bool = True,
    base_model_verified: bool = True,
    onnx_verified: bool = True,
    omit_onnx_role: str | None = None,
) -> None:
    manifest_path = migration.canonical_root / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    onnx_rows: list[dict[str, object]] = []
    for role, relative in REQUIRED_ONNX_FILES.items():
        if role == omit_onnx_role:
            continue
        path = migration.canonical_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if role == "model_index":
            payload = json.dumps(
                {
                    "_class_name": "StableDiffusionPipeline",
                    "_name_or_path": base_model_id,
                }
            ).encode()
        elif role == "unet_config":
            cache_id = base_model_id.replace("/", "--")
            payload = json.dumps(
                {
                    "_class_name": "UNet2DConditionModel",
                    "_name_or_path": (
                        f"C:/hf/models--{cache_id}/snapshots/{base_model_revision}/unet"
                    ),
                    "sample_size": sample_size,
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

    manifest["profile"] = {
        "width": 512,
        "height": 512,
        "batch_size": 1,
        "sample_size": sample_size,
        "source": "verified_engine_profile",
        "verified": profile_verified,
    }
    manifest["base_model"] = {
        "id": base_model_id,
        "revision": base_model_revision,
        "verified": base_model_verified,
    }
    manifest["onnx"] = {
        "verified": onnx_verified,
        "files": onnx_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _ready_migration(tmp_path: Path, name: str) -> TensorRTBundleMigration:
    models_dir = tmp_path / name
    _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)
    migration.migrate()
    _promote_ready_bundle(migration)
    return migration


def test_detector_is_read_only_when_legacy_layout_is_absent(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    migration = TensorRTBundleMigration(models_dir)

    status = migration.inspect()

    assert status["legacy"]["status"] == "absent"
    assert status["canonical"]["status"] == "absent"
    assert status["migration"]["available"] is False
    assert status["migration"]["blocked_reason"] == "legacy_not_detected"
    assert not models_dir.exists()


def test_detector_rejects_partial_and_zero_byte_engine_sets(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_legacy_engines(
        models_dir,
        {
            "text_encoder.engine": b"",
            "unet_b1_workspace4096.engine": b"unet",
        },
    )
    migration = TensorRTBundleMigration(models_dir)

    status = migration.inspect()

    assert status["legacy"]["status"] == "partial"
    assert status["legacy"]["missing_roles"] == ["vae_decoder", "vae_encoder"]
    assert status["legacy"]["unusable_roles"] == ["text_encoder"]
    assert status["migration"]["blocked_reason"] == "legacy_incomplete"
    with pytest.raises(UserFacingError) as exc:
        migration.migrate()
    assert exc.value.code == "TRT_LEGACY_PARTIAL"
    assert not migration.canonical_root.exists()


def test_detector_can_compute_sha256_without_writing(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    legacy = _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)

    status = migration.inspect(include_hashes=True)

    assert status["legacy"]["status"] == "ready_to_import"
    for row in status["legacy"]["files"]:
        expected = hashlib.sha256((legacy / row["name"]).read_bytes()).hexdigest()
        assert row["sha256"] == expected
        assert row["hash_state"] == "verified_now"
    assert {path.name for path in legacy.iterdir()} == set(ENGINE_PAYLOADS)


def test_migration_is_atomic_hash_verified_and_source_preserving(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    legacy = _write_legacy_engines(models_dir)
    source_before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in legacy.iterdir()
        if path.is_file()
    }
    progress_events: list[tuple[int, int, int, int, str]] = []
    migration = TensorRTBundleMigration(models_dir, copy_chunk_bytes=64 * 1024)

    result = migration.migrate(progress=lambda *event: progress_events.append(event))

    assert result["ok"] is True
    assert result["source_preserved"] is True
    assert result["canonical_renderer_ready"] is False
    assert progress_events
    canonical = migration.canonical_root
    manifest = json.loads((canonical / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["model_id"] == MODEL_ID
    assert manifest["source_preserved"] is True
    assert manifest["compatibility_at_import"]["renderer_ready"] is False
    assert manifest["profile"]["verified"] is False
    for record in manifest["source"]["files"]:
        name = record["source_name"]
        source_payload, source_mtime_ns = source_before[name]
        destination = canonical / record["destination"]
        assert (legacy / name).read_bytes() == source_payload
        assert (legacy / name).stat().st_mtime_ns == source_mtime_ns
        assert destination.read_bytes() == source_payload
        assert record["sha256"] == hashlib.sha256(source_payload).hexdigest()
        assert record["destination_sha256"] == record["sha256"]
        assert record["destination_mtime_ns"] == destination.stat().st_mtime_ns

    status = migration.inspect(include_hashes=True)
    assert status["canonical"]["manifest"]["valid"] is True
    assert status["canonical"]["engine_files_verified"] is True
    assert status["canonical"]["unet_engine_ready"] is True
    assert status["canonical"]["renderer_ready"] is False
    assert status["canonical"]["onnx_ready"] is False
    assert status["canonical"]["profile_metadata_ready"] is False
    assert status["canonical"]["base_model_metadata_ready"] is False
    assert status["migration"]["blocked_reason"] == "canonical_exists"
    assert not list(legacy.glob(".local_sd15_tensorrt_bundle.import-*.tmp"))


def test_unet_only_manifest_cannot_become_renderer_ready(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)
    migration.migrate()
    manifest_path = migration.canonical_root / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source"]["files"] = [
        row for row in manifest["source"]["files"] if row["role"] == "unet"
    ]
    manifest["profile"]["verified"] = True
    manifest["base_model"] = {
        "id": BASE_MODEL_ID,
        "revision": BASE_MODEL_REVISION,
        "verified": True,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    onnx_unet = migration.canonical_root / "onnx" / "unet"
    onnx_unet.mkdir(parents=True)
    (onnx_unet / "config.json").write_text(
        json.dumps({"sample_size": 64, "_name_or_path": BASE_MODEL_ID}),
        encoding="utf-8",
    )
    (onnx_unet / "model.onnx").write_bytes(b"onnx")

    status = migration.inspect(include_hashes=True)["canonical"]

    assert status["onnx_ready"] is False
    assert status["profile_metadata_ready"] is True
    assert status["base_model_metadata_ready"] is False
    assert status["manifest"]["valid"] is False
    assert status["engine_files_verified"] is False
    assert status["renderer_ready"] is False


def test_explicit_complete_manifest_produces_shared_runtime_contract(tmp_path: Path) -> None:
    migration = _ready_migration(tmp_path, "models")

    status = migration.inspect(include_hashes=True)["canonical"]
    contract = migration.validate_bundle_root(
        migration.canonical_root,
        verify_engine_hashes=True,
    )

    assert status["renderer_ready"] is True
    assert status["engine_hashes_verified_now"] is True
    assert status["onnx_manifest_valid"] is True
    assert status["profile"] == {
        "width": 512,
        "height": 512,
        "batch_size": 1,
        "sample_size": 64,
    }
    assert status["base_model"] == {
        "id": BASE_MODEL_ID,
        "revision": BASE_MODEL_REVISION,
    }
    assert contract.root == migration.canonical_root
    assert contract.engine_paths["unet"].name == "unet_b1_workspace4096.engine"
    assert contract.onnx_paths["unet_model"] == migration.canonical_root / "onnx/unet/model.onnx"
    assert contract.base_model_id == BASE_MODEL_ID
    assert contract.base_model_revision == BASE_MODEL_REVISION
    json.dumps(migration.inspect(include_hashes=False))


@pytest.mark.parametrize(
    ("promotion_kwargs", "failed_field"),
    [
        ({"profile_verified": False}, "profile_metadata_ready"),
        ({"base_model_verified": False}, "base_model_metadata_ready"),
        ({"base_model_revision": None}, "base_model_metadata_ready"),
        ({"base_model_revision": "main"}, "base_model_metadata_ready"),
        ({"sample_size": [64, 64]}, "profile_metadata_ready"),
        ({"onnx_verified": False}, "onnx_ready"),
        ({"omit_onnx_role": "vae_encoder_model"}, "onnx_ready"),
    ],
)
def test_bundle_readiness_requires_explicit_verified_contract_fields(
    tmp_path: Path,
    promotion_kwargs: dict[str, object],
    failed_field: str,
) -> None:
    models_dir = tmp_path / "models"
    _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)
    migration.migrate()
    _promote_ready_bundle(migration, **promotion_kwargs)

    status = migration.inspect(include_hashes=True)["canonical"]

    assert status[failed_field] is False
    assert status["renderer_ready"] is False
    with pytest.raises(UserFacingError) as exc:
        migration.validate_bundle_root(migration.canonical_root, verify_engine_hashes=True)
    assert exc.value.code == "TRT_BUNDLE_UNVERIFIED"


def test_unlisted_onnx_file_invalidates_complete_component_inventory(tmp_path: Path) -> None:
    migration = _ready_migration(tmp_path, "models")
    (migration.canonical_root / "onnx" / "unet" / "unexpected.data").write_bytes(b"extra")

    status = migration.inspect(include_hashes=True)["canonical"]

    assert status["onnx_ready"] is False
    assert status["renderer_ready"] is False


def test_same_size_engine_tamper_is_rejected_by_execution_validation(tmp_path: Path) -> None:
    migration = _ready_migration(tmp_path, "models")
    unet = migration.canonical_root / "engine" / "unet_b1_workspace4096.engine"
    original = unet.read_bytes()
    unet.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
    verifier = TensorRTBundleMigration(tmp_path / "models")

    status = verifier.inspect(include_hashes=True)["canonical"]

    assert status["engine_hashes_verified_now"] is False
    assert status["engine_files_verified"] is False
    assert status["renderer_ready"] is False
    with pytest.raises(UserFacingError) as exc:
        verifier.validate_bundle_root(verifier.canonical_root, verify_engine_hashes=True)
    assert exc.value.code == "TRT_BUNDLE_UNVERIFIED"


def test_resolver_prefers_valid_canonical_over_valid_external(tmp_path: Path) -> None:
    canonical = _ready_migration(tmp_path, "canonical_models")
    external = _ready_migration(tmp_path, "external_models")

    contract = canonical.resolve_preferred_bundle(
        external_paths=[external.canonical_root],
        verify_engine_hashes=True,
    )

    assert contract is not None
    assert contract.root == canonical.canonical_root


def test_external_override_is_unverified_until_same_contract_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path / "manager")
    external_models = tmp_path / "external_models"
    _write_legacy_engines(external_models)
    external = TensorRTBundleMigration(external_models)
    external.migrate()
    monkeypatch.setenv("EDMG_TENSORRT_SD15_BUNDLE", str(external.canonical_root))
    monkeypatch.delenv("EDMG_TENSORRT_MODEL_DIR", raising=False)

    assert manager.installed_path(MODEL_ID) is None
    status = manager.legacy_tensorrt_status(include_hashes=True)
    assert status["external"][0]["verification_state"] == "unverified"
    assert status["external"][0]["selected"] is False

    _promote_ready_bundle(external)

    assert manager.installed_path(MODEL_ID) == external.canonical_root
    status = manager.legacy_tensorrt_status(include_hashes=True)
    assert status["external"][0]["verification_state"] == "verified_now"
    assert status["external"][0]["selected"] is True


def test_unsafe_non_unet_destination_cannot_pass_metadata_only_validation(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)
    migration.migrate()
    unsafe_destination = migration.canonical_root / "engine" / "text_encoder.engine"
    unsafe_destination.unlink()
    unsafe_destination.mkdir()

    status = migration.inspect(include_hashes=False)["canonical"]
    text_encoder = next(
        row for row in status["engine_files"] if row["name"] == "text_encoder.engine"
    )

    assert text_encoder["safe_regular_file"] is False
    assert status["engine_files_verified"] is False
    assert status["renderer_ready"] is False


def test_migration_refuses_insufficient_disk_without_creating_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models_dir = tmp_path / "models"
    legacy = _write_legacy_engines(models_dir)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(migration_module.shutil, "disk_usage", lambda _path: usage(100, 99, 1))
    migration = TensorRTBundleMigration(models_dir)

    with pytest.raises(UserFacingError) as exc:
        migration.migrate()

    assert exc.value.code == "TRT_MIGRATION_DISK_SPACE"
    assert not migration.canonical_root.exists()
    assert {path.name for path in legacy.iterdir()} == set(ENGINE_PAYLOADS)


def test_cancelled_migration_removes_only_its_staging_copy(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    payloads = dict(ENGINE_PAYLOADS)
    payloads["unet_b1_workspace4096.engine"] = b"u" * (512 * 1024)
    legacy = _write_legacy_engines(models_dir, payloads)
    migration = TensorRTBundleMigration(models_dir, copy_chunk_bytes=64 * 1024)
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 5

    with pytest.raises(TensorRTMigrationCancelled):
        migration.migrate(cancel_check=cancel)

    assert not migration.canonical_root.exists()
    assert not list(legacy.glob(".local_sd15_tensorrt_bundle.import-*.tmp"))
    assert {path.name for path in legacy.iterdir()} == set(payloads)
    for name, payload in payloads.items():
        assert (legacy / name).read_bytes() == payload


def test_hash_verification_failure_cleans_staging_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models_dir = tmp_path / "models"
    legacy = _write_legacy_engines(models_dir)
    migration = TensorRTBundleMigration(models_dir)
    monkeypatch.setattr(migration, "_cached_sha256", lambda *_args, **_kwargs: "0" * 64)

    with pytest.raises(UserFacingError) as exc:
        migration.migrate()

    assert exc.value.code == "TRT_MIGRATION_HASH_MISMATCH"
    assert not migration.canonical_root.exists()
    assert not list(legacy.glob(".local_sd15_tensorrt_bundle.import-*.tmp"))
    assert {path.name for path in legacy.iterdir()} == set(ENGINE_PAYLOADS)


def test_model_manager_exposes_status_but_does_not_mark_engine_only_copy_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EDMG_TENSORRT_SD15_BUNDLE", raising=False)
    monkeypatch.delenv("EDMG_TENSORRT_MODEL_DIR", raising=False)
    manager = _manager(tmp_path)
    _write_legacy_engines(manager.models_dir)

    task = manager.import_legacy_tensorrt()
    deadline = time.monotonic() + 5
    while task.status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert task.status == "done"
    catalog = manager.catalog()
    assert catalog["tensorrt_migration"]["canonical"]["renderer_ready"] is False
    assert catalog["installed"][MODEL_ID] is False
    assert "source files remain in place" in task.last_log
