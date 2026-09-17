from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from edmg_studio_backend.services import model_runtime_registry as runtime_module
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


def test_hunyuan_adapter_validates_model_files_without_requiring_runner(tmp_path, monkeypatch):
    for name in ("RUNNER", "PYTHON", "REPO", "LLM_PATH", "BYT5_PATH", "GLYPH_PATH", "VISION_PATH"):
        monkeypatch.delenv(f"EDMG_HUNYUAN15_{name}", raising=False)
    monkeypatch.setattr(
        "edmg_studio_backend.services.internal_video_models.validate_hunyuan_runner",
        lambda **_kwargs: pytest.fail("runtime probe must not run during package validation"),
    )
    adapter = DEFAULT_RUNTIME_REGISTRY.adapter("hf_hunyuan_video15_internal")
    assert adapter.descriptor.adapter_ready
    assert adapter.descriptor.smoke_test_supported
    assert adapter.smoke_test is not None
    assert adapter.descriptor.dependency_modules == ()
    issues = adapter.validate_config(tmp_path)
    assert issues
    assert not any("EDMG_HUNYUAN15_RUNNER" in issue for issue in issues)
    assert any("missing" in issue.lower() for issue in issues)


def test_hunyuan_wsl_uses_driver_visible_cuda_without_promoting_native_runtimes(monkeypatch):
    monkeypatch.setenv("EDMG_HUNYUAN15_RUNNER", "wsl")
    hardware = {
        "backend": "cpu",
        "device": "cpu",
        "device_name": "CPU",
        "vram_gb": 0,
        "ram_gb": 128,
        "llama_backend": "cuda",
        "llama_device": "cuda:0",
        "llama_device_name": "NVIDIA RTX A6000",
        "llama_vram_gb": 48,
    }

    hunyuan = DEFAULT_RUNTIME_REGISTRY.status("hf_hunyuan_video15_internal", hardware=hardware)
    assert hunyuan["hardware_compatible"]
    assert hunyuan["device"] == "cuda:0"

    native = DEFAULT_RUNTIME_REGISTRY._runtime_hardware("fixture", hardware)
    assert native["backend"] == "cpu"
    assert native["device"] == "cpu"


def test_hunyuan_requires_matching_level_five_smoke_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("EDMG_HUNYUAN15_RUNNER", "wsl")
    adapter = DEFAULT_RUNTIME_REGISTRY.adapter("hf_hunyuan_video15_internal")
    subject = ModelRuntimeRegistry()
    subject.register(RuntimeAdapter(
        descriptor=adapter.descriptor,
        validate_config=lambda root: [],
        smoke_test=adapter.smoke_test,
    ))
    status = subject.status(
        "hf_hunyuan_video15_internal",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cuda", "device": "cuda:0", "vram_gb": 48, "ram_gb": 128},
    )

    assert not status["runtime_ready"]
    assert status["runtime_state"] == "installed_runtime_unavailable"
    assert status["validation_level"] == 3
    assert status["smoke_test_required"] is True
    assert not status["smoke_tested"]
    assert any("smoke test" in blocker.lower() for blocker in status["blockers"])

    receipt_path = tmp_path / "runtime-validation.json"
    legacy_receipt = {
        "schema_version": 1,
        "package_id": "hf_hunyuan_video15_internal",
        "receipt_timestamp": "2026-01-01T00:00:00+00:00",
        "validation_level": 5,
        "success": True,
        "fingerprint": status["fingerprint"],
    }
    receipt_path.write_text(json.dumps(legacy_receipt), encoding="utf-8")
    assert not subject.status(
        "hf_hunyuan_video15_internal", package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cuda", "device": "cuda:0", "vram_gb": 48, "ram_gb": 128},
    )["runtime_ready"]

    motion_evidence = {
        "status": "pass", "failures": [], "frame_count": 9,
        "perceptually_unique_frames": 9, "meaningful_transition_count": 8,
        "required_meaningful_transition_count": 3, "motion_quartiles": [0, 1, 2, 3],
    }
    receipt_path.write_text(json.dumps({
        **legacy_receipt, "result": {"motion_evidence": motion_evidence},
    }), encoding="utf-8")
    qualified = subject.status(
        "hf_hunyuan_video15_internal",
        package_root=tmp_path,
        package_validation=package_validation(),
        hardware={"backend": "cuda", "device": "cuda:0", "vram_gb": 48, "ram_gb": 128},
    )
    assert qualified["runtime_ready"]
    assert qualified["validation_level"] == 5
    assert qualified["smoke_tested"]




@pytest.mark.parametrize("evidence", [
    None,
    {},
    {"status": "fail", "failures": ["frozen"], "frame_count": 9,
     "perceptually_unique_frames": 9, "meaningful_transition_count": 8,
     "required_meaningful_transition_count": 3, "motion_quartiles": [0, 1, 2, 3]},
    {"status": "pass", "failures": [], "frame_count": 8,
     "perceptually_unique_frames": 8, "meaningful_transition_count": 7,
     "required_meaningful_transition_count": 3, "motion_quartiles": [0, 1, 2, 3]},
])
def test_video_smoke_test_refuses_invalid_motion_receipt(tmp_path, evidence):
    adapter = DEFAULT_RUNTIME_REGISTRY.adapter("hf_hunyuan_video15_internal")
    subject = ModelRuntimeRegistry()
    subject.register(RuntimeAdapter(descriptor=adapter.descriptor, validate_config=lambda root: [],
                                    smoke_test=lambda **kwargs: {"success": True, "motion_evidence": evidence}))
    with pytest.raises(RuntimeError, match="temporal motion evidence"):
        subject.smoke_test(
            "hf_hunyuan_video15_internal", package_root=tmp_path,
            package_validation=package_validation(),
            hardware={"backend": "cuda", "device": "cuda:0", "vram_gb": 48, "ram_gb": 128},
        )
    assert not (tmp_path / "runtime-validation.json").exists()

def _motion_frames(count: int = 9) -> list[Image.Image]:
    frames = []
    for index in range(count):
        frame = Image.new("RGB", (64, 64), "black")
        ImageDraw.Draw(frame).rectangle((index * 5, 24, index * 5 + 12, 36), fill="white")
        frames.append(frame)
    return frames


@pytest.mark.parametrize("smoke_name,module_name,generator_name", [
    ("_smoke_test_hunyuan", "edmg_studio_backend.services.internal_video_models", "generate_video_model_frames"),
    ("_smoke_test_ltx_25", "edmg_studio_backend.services.ltx_25_runtime", "generate_ltx_frames"),
])
def test_level_five_video_smoke_requires_distributed_motion(tmp_path, monkeypatch, smoke_name, module_name, generator_name):
    import importlib

    module = importlib.import_module(module_name)
    if smoke_name == "_smoke_test_ltx_25":
        monkeypatch.setattr(module, "ltx_runtime_config", lambda: type("Config", (), {"smoke_timeout_s": 30})())
    smoke = getattr(runtime_module, smoke_name)

    monkeypatch.setattr(module, generator_name, lambda **_kwargs: [Image.new("RGB", (64, 64), "black")] * 9)
    with pytest.raises(RuntimeError, match="temporal motion"):
        smoke(package_root=tmp_path, hardware={"backend": "cpu"})

    sparse = [Image.new("RGB", (64, 64), "black") for _ in range(9)]
    sparse[-1] = Image.new("RGB", (64, 64), "white")
    monkeypatch.setattr(module, generator_name, lambda **_kwargs: sparse)
    with pytest.raises(RuntimeError, match="motion_not_distributed|meaningful"):
        smoke(package_root=tmp_path, hardware={"backend": "cpu"})

    monkeypatch.setattr(module, generator_name, lambda **_kwargs: _motion_frames())
    result = smoke(package_root=tmp_path, hardware={"backend": "cpu"})
    assert result["motion_evidence"]["status"] == "pass"


def test_level_five_video_smoke_rejects_insufficient_frames(tmp_path, monkeypatch):
    from edmg_studio_backend.services import internal_video_models

    monkeypatch.setattr(internal_video_models, "generate_video_model_frames", lambda **_kwargs: _motion_frames(7))
    with pytest.raises(RuntimeError, match="too_few_frames"):
        runtime_module._smoke_test_hunyuan(package_root=tmp_path, hardware={"backend": "cpu"})

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
