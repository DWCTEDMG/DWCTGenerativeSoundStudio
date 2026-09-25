from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api.runtime import create_runtime_router


class _SettingsStore:
    def __init__(self):
        self.value = {
            "runtime": {"enabled": False},
            "execution": {"runtime_profile": "standard", "model_environment_preferences": {}},
        }

    def get(self):
        return self.value

    def update(self, patch):
        for key, value in patch.items():
            self.value.setdefault(key, {}).update(value)
        return self.get()


def _client(tmp_path):
    app = FastAPI()
    render_settings = _SettingsStore()
    settings = SimpleNamespace(data_dir=tmp_path / "data", models_dir=tmp_path / "models")
    settings.data_dir.mkdir()
    settings.models_dir.mkdir()
    app.include_router(create_runtime_router(settings, lambda: None, lambda: None, render_settings, lambda: {}))
    return TestClient(app), render_settings


def test_execution_profile_defaults_to_standard_and_updates_atomically(tmp_path):
    client, render_settings = _client(tmp_path)
    assert client.get("/v1/execution/profile").json() == {
        "runtime_profile": "standard",
        "model_environment_preferences": {},
    }

    response = client.put("/v1/execution/profile", json={
        "runtime_profile": "hybrid_gpu",
        "model_environment_preferences": {"hunyuan_video15": "wsl"},
    })
    assert response.status_code == 200
    assert response.json()["runtime_profile"] == "hybrid_gpu"
    assert render_settings.get()["execution"]["model_environment_preferences"] == {
        "hunyuan_video15": "wsl"
    }


def test_execution_inventory_exposes_separate_readiness_layers_without_private_paths(tmp_path):
    client, _ = _client(tmp_path)
    payload = client.get("/v1/execution/inventory").json()
    readiness = payload["wsl"]["readiness"]
    assert set(readiness) == {
        "wsl_installed",
        "distribution_running",
        "worker_environment_present",
        "gpu_visible",
        "model_installed",
        "worker_launchable",
        "generation_started",
        "artifact_validated",
        "runtime_qualified",
    }
    assert "model_path" not in str(payload)
    assert isinstance(payload["blockers"], list)
