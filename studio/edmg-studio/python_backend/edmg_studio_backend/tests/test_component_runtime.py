from types import SimpleNamespace

import pytest

from edmg_studio_backend.runtime.cache import EngineCache, engine_key
from edmg_studio_backend.runtime.manager import RuntimeManager, RuntimeSelector
from edmg_studio_backend.runtime.policy import RuntimePolicy, load_policy
from edmg_studio_backend.services.render_settings import RenderSettingsStore


def test_optional_policy_preserves_old_settings(tmp_path):
    store = RenderSettingsStore(tmp_path)
    store.update({"cuda": {"enabled": True}})
    assert load_policy(tmp_path).mode == "auto"
    store.update({"runtime": {"enabled": False, "mode": "compatibility"}})
    assert not load_policy(tmp_path).enabled
    assert store.get()["cuda"]["enabled"]


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


def test_runtime_api_validates_policy_and_reuses_job_store(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from edmg_studio_backend.api.runtime import create_runtime_router
    from edmg_studio_backend.store.jobs import JobStore
    from edmg_studio_backend.store.projects import ProjectStore
    settings = SimpleNamespace(data_dir=tmp_path)
    store = ProjectStore(tmp_path / "projects")
    jobs = JobStore(tmp_path / "projects")
    render_settings = RenderSettingsStore(tmp_path)
    app = FastAPI()
    app.include_router(create_runtime_router(settings, lambda: store, lambda: jobs, render_settings, lambda: {}))
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
            assert response.json()["diagnostics_scope"] == "last_run_receipt_not_live_health"
            assert client.post("/v1/runtime/settings", json={"enabled": False}).status_code == 200
            assert client.post("/v1/runtime/jobs", json={}).status_code == 409
            assert client.delete("/v1/runtime/tensorrt/cache/not-an-id").status_code == 400
    finally:
        jobs.close()
