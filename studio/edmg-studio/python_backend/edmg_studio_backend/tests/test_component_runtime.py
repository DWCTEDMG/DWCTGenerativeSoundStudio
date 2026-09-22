import json
from types import SimpleNamespace

import pytest

from edmg_studio_backend.runtime.cache import EngineCache, engine_key
from edmg_studio_backend.runtime.manager import (
    RuntimeManager,
    RuntimePlan,
    RuntimeRegistry,
    RuntimeSelector,
    pipeline_runtime_metadata,
)
from edmg_studio_backend.runtime.policy import RuntimePolicy, load_policy
from edmg_studio_backend.runtime.policy import resolve_policy
from edmg_studio_backend.services.render_settings import RenderSettingsStore


def test_optional_policy_preserves_old_settings(tmp_path):
    store = RenderSettingsStore(tmp_path)
    store.update({"cuda": {"enabled": True}})
    assert load_policy(tmp_path).mode == "auto"
    store.update({"runtime": {"enabled": False, "mode": "compatibility"}})
    assert not load_policy(tmp_path).enabled
    assert store.get()["cuda"]["enabled"]


def test_request_override_is_isolated_and_global_disable_wins(tmp_path):
    store = RenderSettingsStore(tmp_path)
    store.update({"runtime": {"mode": "performance", "precision": "fp16", "strict": True}})
    before = store.get()
    first = resolve_policy(tmp_path, {"enabled": False, "strict": False, "allow_fallback": True})
    second = resolve_policy(tmp_path)
    assert not first.enabled and not first.strict and first.allow_fallback
    assert second.enabled and second.strict and second.mode == "performance"
    assert first.precision == "fp16"
    assert first.model_dump_json() != second.model_dump_json()
    assert store.get() == before
    store.update({"runtime": {"enabled": False}})
    assert not resolve_policy(tmp_path, {"enabled": True, "mode": "tensorrt"}).enabled


def test_operation_policy_cannot_change_worker_or_cache_configuration(tmp_path):
    from pydantic import ValidationError
    for value in ({"package_path": "other"}, {"auto_build": True}, {"mode": "invalid"}):
        with pytest.raises(ValidationError):
            resolve_policy(tmp_path, value)


def test_generation_and_layer_contracts_preserve_operation_policy():
    from edmg_studio_backend.schemas import GenerationRequest, LayeredAnimateRequest, RenderScenesRequest
    override = {"enabled": False, "precision": "fp32", "allow_fallback": True}
    request = GenerationRequest.model_validate({"operation": "video", "parameters": {"runtime": override}})
    assert request.model_dump()["parameters"]["runtime"]["enabled"] is False
    assert RenderScenesRequest(runtime=override).model_dump()["runtime"]["enabled"] is False
    request = LayeredAnimateRequest(source_asset="frame.png", runtime=override)
    assert request.model_dump()["runtime"]["precision"] == "fp32"


def test_registry_does_not_admit_unconverted_components():
    from edmg_studio_backend.runtime.manager import RuntimeRegistry
    components = RuntimeRegistry().component_status()
    admitted = [(c["model_family"], c["component"]) for c in components if c["status"] == "adapter_available"]
    assert admitted == [("sd15", "vae_decoder")]
    assert {c["model_family"] for c in components} >= {"ltx_25", "wan", "hunyuan_video15", "qwen", "whisper"}


def test_request_off_never_starts_worker(tmp_path, monkeypatch):
    import torch
    import edmg_studio_backend.runtime.manager as module
    monkeypatch.setattr(module, "RuntimeProcess", lambda *a: pytest.fail("TensorRT worker started while disabled"))
    manager = RuntimeManager(resolve_policy(tmp_path, {"enabled": False}), tmp_path, tmp_path, lambda value, **kw: (value,))
    value = SimpleNamespace(device=torch.device("cuda:0"))
    assert manager.decode(value, return_dict=False) == (value,)


def test_cached_pipeline_is_partitioned_by_effective_request_policy(tmp_path, monkeypatch):
    import edmg_studio_backend.services.internal_video as video
    import edmg_studio_backend.config as config
    monkeypatch.setattr(config, "Settings", lambda: SimpleNamespace(data_dir=tmp_path))
    keys = []
    sentinel = object()
    monkeypatch.setattr(video._PipelineCache, "get", lambda key: keys.append(key) or sentinel)
    assert video._try_load_diffusers(tmp_path, "cuda", runtime={"enabled": False}) is sentinel
    assert video._try_load_diffusers(tmp_path, "cuda", runtime={"mode": "tensorrt"}) is sentinel
    assert video._try_load_diffusers(tmp_path, "cuda", runtime={"enabled": False}) is sentinel
    assert keys[0] != keys[1]
    assert keys[0] == keys[2]


def test_internal_settings_payload_keeps_render_override():
    from edmg_studio_backend.app import _internal_settings_from_payload
    override = {"enabled": False}
    settings = _internal_settings_from_payload({"runtime": override}, model_id="test", render_tier="auto", device_preference="cuda")
    assert settings.runtime == override


def test_explicit_legacy_routes_cannot_bypass_disabled_policy(tmp_path, monkeypatch):
    import edmg_studio_backend.app as app
    from edmg_studio_backend.errors import UserFacingError
    from edmg_studio_backend.schemas import TensorRTStandaloneRenderRequest
    monkeypatch.setattr(app, "settings", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(app, "_resolve_installed_model_path", lambda *a, **kw: pytest.fail("model loaded while disabled"))
    RenderSettingsStore(tmp_path).update({"runtime": {"enabled": False}})
    with pytest.raises(UserFacingError, match="disabled"):
        app._server_resolved_tensorrt_payload(TensorRTStandaloneRenderRequest(runtime={"enabled": True}))
    with pytest.raises(UserFacingError, match="disabled"):
        app._resolved_tensorrt_execution_payload({})
    with pytest.raises(UserFacingError, match="disabled"):
        app._tensorrt_render_preflight_data("unused", {})


@pytest.mark.parametrize("change", [{"enabled": False}, {"mode": "pytorch_cuda"}, {"mode": "cpu"}, {"cache_enabled": False}])
def test_policy_can_disable_acceleration(change):
    assert not RuntimeSelector.permits_tensorrt(RuntimePolicy(**change), "sd15", "vae_decoder", "cuda:1")


@pytest.mark.parametrize("model,component,device", [("hunyuan", "transformer", "cuda:0"), ("sd15", "unet", "cuda"), ("sd15", "vae_decoder", "cpu")])
def test_no_guessed_model_or_cpu_support(model, component, device):
    assert not RuntimeSelector.permits_tensorrt(RuntimePolicy(), model, component, device)


def test_compatibility_never_compiles():
    assert not RuntimeSelector.may_build(RuntimePolicy(mode="compatibility"))
    assert not RuntimeSelector.may_build(RuntimePolicy())
    assert RuntimeSelector.may_build(RuntimePolicy(mode="performance"))


def test_corrupted_engine_is_quarantined(tmp_path):
    cache = EngineCache(tmp_path)
    identity = {"weights": "abc", "gpu": "sm86", "shape": [1, 4, 64, 64]}
    key = engine_key(identity)
    cache.publish(identity, b"trusted-local-build", {"passed": True}, {"beneficial": True})
    assert cache.lookup(identity)
    (cache.directory(key) / "engine.plan").write_bytes(b"corrupt")
    assert cache.lookup(identity) is None
    assert cache.read(key)["state"] == "quarantined"
    assert len(list((cache.root / "quarantine").glob("*.plan"))) == 1


def test_identity_change_invalidates_and_clear_preserves_weights(tmp_path):
    cache = EngineCache(tmp_path)
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    identity = {"weights": "abc", "precision": "fp16", "gpu": "sm86"}
    cache.publish(identity, b"engine", {"passed": True}, {})
    for key in identity:
        assert cache.lookup({**identity, key: "changed"}) is None
    cache.clear(engine_key(identity))
    assert weights.read_bytes() == b"weights"
    with pytest.raises(ValueError):
        cache.clear("../model.safetensors")


def test_unvalidated_engine_cannot_publish(tmp_path):
    with pytest.raises(ValueError):
        EngineCache(tmp_path).publish({}, b"bad", {"passed": False}, {})


def test_failed_worker_falls_back_once_without_changing_latent(tmp_path, monkeypatch):
    import torch
    import edmg_studio_backend.runtime.manager as module
    calls = []
    original = lambda value, **kwargs: calls.append(value) or ("reference",)
    starts = []
    def broken(*args, **kwargs):
        starts.append(True)
        raise RuntimeError("simulated native worker failure")
    monkeypatch.setattr(module, "RuntimeProcess", broken)
    value = SimpleNamespace(device=torch.device("cuda:1"), dtype=torch.float16, shape=(1, 4, 64, 64))
    manager = RuntimeManager(RuntimePolicy(), tmp_path, tmp_path, original)
    assert manager.decode(value, return_dict=False) == ("reference",)
    assert manager.decode(value, return_dict=False) == ("reference",)
    assert calls == [value, value] and len(starts) == 1
    assert manager.plan.selected == "pytorch_cuda"
    assert len(manager.plan.fallback_history) == 1


def test_strict_failure_does_not_fallback(tmp_path):
    manager = RuntimeManager(RuntimePolicy(strict=True), tmp_path, tmp_path, lambda *a: pytest.fail("fallback"))
    with pytest.raises(RuntimeError, match="strict"):
        manager._fallback(RuntimeError("broken"))
    with pytest.raises(RuntimeError, match="fallback is disabled"):
        manager.decode(SimpleNamespace(device="cuda:0"))


def test_runtime_api_validates_policy_and_reuses_job_store(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from edmg_studio_backend.api.runtime import create_runtime_router
    from edmg_studio_backend.store.jobs import JobStore
    from edmg_studio_backend.store.projects import ProjectStore
    import edmg_studio_backend.runtime.service as runtime_service

    models_dir = tmp_path / "models"
    settings = SimpleNamespace(data_dir=tmp_path, models_dir=models_dir)
    store = ProjectStore(tmp_path / "projects")
    jobs = JobStore(tmp_path / "projects")
    render_settings = RenderSettingsStore(tmp_path)
    monkeypatch.setattr(runtime_service, "discover", lambda package_path: {
        "installed": False,
        "package_path": "",
        "python_binding_found": False,
        "downloaded_packages": [],
        "status": "not_installed",
        "explicit_package_missing": False,
    })
    app = FastAPI()
    app.include_router(create_runtime_router(settings, lambda: store, lambda: jobs, render_settings, lambda: {"backend": "cpu"}))
    try:
        with TestClient(app) as client:
            assert client.post("/v1/runtime/settings", json={"mode": "unknown"}).status_code == 422
            assert client.post("/v1/runtime/jobs", json={"width": 513}).status_code == 422
            first = client.post("/v1/runtime/jobs", json={}).json()
            second = client.post("/v1/runtime/jobs", json={"operation": "optimize"}).json()
            assert first["project_id"] == second["project_id"]
            assert jobs.get(first["project_id"], first["job_id"]).type == "runtime_optimization"
            response = client.get("/v1/runtime/status")
            assert response.status_code == 200
            status = response.json()
            assert status["diagnostics_scope"] == "last_run_receipt_not_live_health"
            assert status["state"] == "not_installed"
            assert not status["installed"] and not status["available"]
            assert not status["healthy"] and not status["compatible"] and not status["accelerating"]
            component = next(value for value in status["components"] if value["model_family"] == "sd15" and value["component"] == "vae_decoder")
            assert not component["optimization_eligible"]
            assert component["optimization_reason"] == "tensorrt_not_installed"
            disabled = client.post("/v1/runtime/settings", json={"enabled": False})
            assert disabled.status_code == 200
            assert disabled.json()["state"] == "disabled"
            assert not disabled.json()["available"]
            assert client.post("/v1/runtime/jobs", json={}).status_code == 409
            assert client.delete("/v1/runtime/tensorrt/cache/not-an-id").status_code == 400
    finally:
        jobs.close()


def test_runtime_status_reports_qualified_component_evidence(tmp_path, monkeypatch):
    import edmg_studio_backend.runtime.service as runtime_service

    monkeypatch.setattr(runtime_service, "discover", lambda package_path: {
        "installed": True,
        "package_path": "",
        "python_binding_found": True,
        "downloaded_packages": [],
        "status": "unprobed",
        "explicit_package_missing": False,
    })
    models_dir = tmp_path / "models"
    (models_dir / "internal" / "diffusers" / "hf_sd15_internal").mkdir(parents=True)
    receipt = {
        "healthy": True,
        "status": "ready",
        "version": "10.9",
        "cuda": "12.8",
        "devices": [{"index": 1, "name": "Test GPU"}],
        "tested_at": 1234.0,
        "package_path": "",
    }
    (tmp_path / "tensorrt").mkdir()
    (tmp_path / "tensorrt" / "diagnostics.json").write_text(json.dumps(receipt))
    identity = {"model": "sd15", "component": "vae_decoder", "profile": {"input": [1, 4, 64, 64]}}
    EngineCache(tmp_path).publish(identity, b"engine", {"passed": True}, {"beneficial": True, "tensorrt_s": 0.1})

    status = runtime_service.runtime_status(tmp_path, {"backend": "cuda"}, models_dir)
    assert status["installed"] and status["available"] and status["healthy"] and status["compatible"]
    assert not status["accelerating"]
    assert status["tensorrt_version"] == "10.9"
    RenderSettingsStore(tmp_path).update({"runtime": {"enabled": False}})
    disabled = runtime_service.runtime_status(tmp_path, {"backend": "cuda"}, models_dir)
    assert disabled["state"] == "disabled" and disabled["available"]
    assert not next(value for value in disabled["components"] if value["component"] == "vae_decoder")["optimization_eligible"]
    assert status["pytorch_cuda_available"]
    assert status["supported_component_count"] == 1
    component = next(value for value in status["components"] if value["model_family"] == "sd15" and value["component"] == "vae_decoder")
    assert component["optimization_eligible"]
    assert component["validated_engine_count"] == 1
    assert component["profile_coverage"] == [{"input": [1, 4, 64, 64]}]
    assert component["last_benchmark"]["beneficial"]


def test_runtime_metadata_reports_actual_tensorrt_selection():
    plan = RuntimePlan(
        "tensorrt",
        selected="tensorrt",
        device="cuda:0",
        precision="fp32",
        component="vae_decoder",
        engine_id="a" * 64,
        cache="hit",
    )
    manager = SimpleNamespace(plan=plan)
    vae = SimpleNamespace(_edmg_runtime=manager)
    pipes = SimpleNamespace(
        txt2img=SimpleNamespace(vae=vae),
        backend="diffusers",
        device="cuda",
    )
    metadata = pipeline_runtime_metadata(pipes)
    assert metadata["selected"] == "tensorrt"
    assert metadata["component"] == "vae_decoder"
    assert metadata["engine_id"] == "a" * 64


def test_component_runtime_does_not_claim_unet_but_standalone_does():
    capabilities = RuntimeRegistry().capabilities
    assert "unet" not in capabilities["tensorrt"]["sd15"]
    assert capabilities["tensorrt_standalone"]["sd15"] == ["unet"]


def test_validation_policy_has_separate_fp32_and_fp16_limits():
    policy = RuntimePolicy()
    fp32 = policy.validation_limits("fp32")
    fp16 = policy.validation_limits("fp16")
    assert fp32["max_absolute_error"] < fp16["max_absolute_error"]
    assert fp32["min_psnr_db"] > fp16["min_psnr_db"]
