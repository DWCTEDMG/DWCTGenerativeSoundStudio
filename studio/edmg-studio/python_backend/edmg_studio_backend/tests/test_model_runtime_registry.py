from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from edmg_studio_backend.services.hardware_memory import (
    meets_physical_ram_requirement,
    nvidia_gpu_profile,
)
from edmg_studio_backend.services.model_runtime_registry import (
    DEFAULT_RUNTIME_REGISTRY,
    ModelRuntimeRegistry,
    RuntimeAdapter,
    RuntimeDescriptor,
)


def descriptor(*, adapter_ready: bool = True) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        package_id="fixture",
        model_family="fixture_family",
        model_format="transformers",
        runtime_backend="fixture_backend",
        runtime_version="1",
        role="asr",
        capabilities=("transcription",),
        required_components=("config",),
        dependency_modules=("json",),
        supported_devices=("cpu", "cuda"),
        recommended_dtype="float32",
        minimum_vram_gb=0,
        minimum_ram_gb=1,
        adapter_ready=adapter_ready,
        smoke_test_supported=adapter_ready,
    )


def package_validation() -> dict:
    return {
        "valid": True,
        "repo_id": "fixture/repo",
        "revision": "a" * 40,
        "files": {"config.json": {"size_bytes": 2, "mtime_ns": 1, "sha256": "b" * 64}},
    }


def registry(tmp_path: Path, *, ready: bool = True, issues: list[str] | None = None) -> ModelRuntimeRegistry:
    result = ModelRuntimeRegistry()
    result.register(RuntimeAdapter(
        descriptor=descriptor(adapter_ready=ready),
        validate_config=lambda root: list(issues or []),
        smoke_test=lambda **kwargs: {"success": True, "text": "ok"},
    ))
    return result


def test_not_installed_is_distinct_from_runtime_unavailable(tmp_path):
    subject = registry(tmp_path)
    missing = subject.status("fixture", hardware={"backend": "cpu", "ram_gb": 8})
    assert missing["runtime_state"] == "not_installed"
    assert missing["validation_level"] == 0

    installed = subject.status(
        "fixture",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cpu", "ram_gb": 8},
    )
    assert installed["installed"]
    assert installed["runtime_state"] == "installed_runtime_unavailable"
    assert installed["validation_level"] == 3
    assert "smoke test" in installed["error"].lower()


def test_nominal_installed_ram_tolerates_os_reservation_but_not_undersized_systems():
    assert meets_physical_ram_requirement({"installed_ram_gb": 16, "ram_gb": 15.64}, 16)
    assert meets_physical_ram_requirement({"ram_gb": 15.64}, 16)
    assert not meets_physical_ram_requirement({"installed_ram_gb": 12, "ram_gb": 11.7}, 16)
    assert not meets_physical_ram_requirement({"installed_ram_gb": 16, "ram_gb": 15.64}, 32)


def test_configuration_error_stops_at_dependency_validation(tmp_path):
    status = registry(tmp_path, issues=["wrong format"]).status(
        "fixture",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cpu", "ram_gb": 8},
    )
    assert status["validation_level"] == 2
    assert status["error"] == "wrong format"


def test_successful_smoke_test_writes_fingerprinted_receipt(tmp_path):
    subject = registry(tmp_path)
    status = subject.smoke_test(
        "fixture",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cpu", "ram_gb": 8, "device_name": "CPU"},
    )
    assert status["runtime_ready"]
    assert status["runtime_state"] == "runtime_ready"
    assert status["validation_level"] == 5
    receipt = json.loads((tmp_path / "runtime-validation.json").read_text(encoding="utf-8"))
    assert receipt["fingerprint"] == status["fingerprint"]


def test_receipt_is_invalidated_by_package_or_hardware_change(tmp_path):
    subject = registry(tmp_path)
    validation = package_validation()
    hardware = {"backend": "cpu", "ram_gb": 8, "device_name": "CPU"}
    subject.smoke_test(
        "fixture",
        package_root=tmp_path,
        package_validation=validation,
        hardware=hardware,
    )
    changed = {**validation, "revision": "c" * 40}
    assert not subject.status(
        "fixture", package_root=tmp_path, package_validation=changed, hardware=hardware,
    )["runtime_ready"]
    assert not subject.status(
        "fixture", package_root=tmp_path, package_validation=validation,
        hardware={**hardware, "device_name": "Different CPU"},
    )["runtime_ready"]


def test_unimplemented_adapter_cannot_be_certified_by_forged_receipt(tmp_path):
    subject = registry(tmp_path, ready=False)
    status = subject.status(
        "fixture",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cpu", "ram_gb": 8},
    )
    (tmp_path / "runtime-validation.json").write_text(json.dumps({
        "success": True,
        "validation_level": 5,
        "fingerprint": status["fingerprint"],
    }), encoding="utf-8")
    status = subject.status(
        "fixture",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cpu", "ram_gb": 8},
    )
    assert not status["runtime_ready"]
    assert status["validation_level"] == 3


def test_duplicate_and_unknown_adapters_are_rejected(tmp_path):
    subject = registry(tmp_path)
    with pytest.raises(ValueError, match="already registered"):
        subject.register(RuntimeAdapter(descriptor=descriptor(), validate_config=lambda root: []))
    with pytest.raises(KeyError, match="No runtime adapter"):
        subject.status("unknown")


def test_hunyuan_adapter_is_implemented_but_fails_closed_without_runner(tmp_path, monkeypatch):
    for name in ("RUNNER", "PYTHON", "REPO", "LLM_PATH", "BYT5_PATH", "GLYPH_PATH", "VISION_PATH"):
        monkeypatch.delenv(f"EDMG_HUNYUAN15_{name}", raising=False)
    adapter = DEFAULT_RUNTIME_REGISTRY.adapter("hf_hunyuan_video15_internal")
    assert adapter.descriptor.adapter_ready
    assert adapter.descriptor.smoke_test_supported
    assert adapter.smoke_test is not None
    assert adapter.descriptor.dependency_modules == ()
    assert any("EDMG_HUNYUAN15_RUNNER" in issue for issue in adapter.validate_config(tmp_path))


def test_opt_in_real_model_runtime_smoke_tests():
    if os.environ.get("REAL_MODEL_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("Set REAL_MODEL_TESTS=1 to run destructive, hardware-dependent model inference")

    from edmg_studio_backend.services.engine_packages import MANIFESTS, validate_package

    model_ids = [
        value.strip()
        for value in os.environ.get("EDMG_REAL_MODEL_IDS", "").split(",")
        if value.strip()
    ]
    assert model_ids, "Set EDMG_REAL_MODEL_IDS to one or more comma-separated managed package IDs"
    try:
        roots = json.loads(os.environ.get("EDMG_REAL_MODEL_ROOTS", ""))
    except json.JSONDecodeError as exc:
        pytest.fail(f"EDMG_REAL_MODEL_ROOTS must be a JSON object: {exc}")
    assert isinstance(roots, dict), "EDMG_REAL_MODEL_ROOTS must map package IDs to installation directories"

    try:
        import psutil

        ram_gb = round(float(psutil.virtual_memory().total) / float(1024 ** 3), 2)
    except ImportError:
        ram_gb = 0.0
    device = os.environ.get("EDMG_REAL_MODEL_DEVICE", "cuda:0").strip().lower()
    hardware = {
        "backend": "cuda" if device.startswith("cuda") else "cpu",
        "device": device,
        "device_name": device,
        "ram_gb": ram_gb,
        "vram_gb": 0.0,
    }
    if device.startswith("cuda"):
        index = int(device.partition(":")[2] or "0")
        gpu = nvidia_gpu_profile()
        assert gpu is not None and gpu["index"] == index, f"Requested {device}, but CUDA is unavailable"
        hardware["device_name"] = gpu["name"]
        hardware["vram_gb"] = gpu["vram_gb"]

    for model_id in model_ids:
        assert model_id in MANIFESTS, f"Unknown managed runtime package: {model_id}"
        assert model_id in roots, f"EDMG_REAL_MODEL_ROOTS has no path for {model_id}"
        package_root = Path(str(roots[model_id])).expanduser().resolve()
        validation = validate_package(package_root, MANIFESTS[model_id])
        assert validation["valid"], f"{model_id} package validation failed: {validation['issues']}"
        result = DEFAULT_RUNTIME_REGISTRY.smoke_test(
            model_id,
            package_root=package_root,
            package_validation=validation,
            hardware=hardware,
        )
        assert result["runtime_ready"], f"{model_id} did not reach Level-5 readiness: {result['blockers']}"
