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


def test_configured_wsl_gpu_mapping_is_available_without_model_probe(tmp_path, monkeypatch):
    from edmg_studio_backend.execution import status
    calls = []
    config = SimpleNamespace(mode="wsl", distro="Ubuntu", python="/python", repo="/repo",
                             model_path="/model", companions={"llm": "/llm"})
    monkeypatch.setattr(status.internal_video_models, "hunyuan_runner_config", lambda: config)
    monkeypatch.setattr(status.internal_video_models, "hunyuan_runner_status", lambda **_: {"issues": []})
    monkeypatch.setattr(status, "discover_windows_gpus", lambda _: [])
    monkeypatch.setattr(status, "discover_wsl_gpus", lambda _, distro: calls.append(distro) or [])
    # A different model's historical receipt must not qualify WSL.
    receipt = tmp_path / "whisper/runtime-validation.json"
    receipt.parent.mkdir()
    receipt.write_text('{"success":true,"validation_level":5}')
    payload = status.execution_inventory_summary(tmp_path, probe=False)
    assert calls == ["Ubuntu"]
    assert payload["probe_performed"] is False
    assert payload["wsl"]["readiness"]["runtime_qualified"] is False


def test_wsl_qualification_requires_current_hunyuan_motion_receipt(tmp_path, monkeypatch):
    import json
    import os
    from edmg_studio_backend.execution import status

    config = SimpleNamespace(mode="wsl", distro="Ubuntu", python="/python", repo="/repo",
                             model_path="/model", companions={"llm": "/llm"})
    monkeypatch.setattr(status.internal_video_models, "hunyuan_runner_config", lambda: config)
    monkeypatch.setattr(status.internal_video_models, "hunyuan_runner_status", lambda **_: {"issues": []})
    monkeypatch.setattr(status, "discover_windows_gpus", lambda _: [])
    monkeypatch.setattr(status, "discover_wsl_gpus", lambda *_: [])
    launcher = tmp_path / "launcher.json"
    launcher.write_text("{}")
    monkeypatch.setattr(status, "launcher_env_path", lambda: launcher)
    receipt = tmp_path / "internal/video/hf_hunyuan_video15_internal/runtime-validation.json"
    receipt.parent.mkdir(parents=True)
    payload = {"package_id": "hf_hunyuan_video15_internal",
               "runtime_backend": "hyvideo15_linux_subprocess", "success": True,
               "validation_level": 5, "result": {"motion_evidence": {"status": "pass"}}}
    receipt.write_text(json.dumps(payload))
    os.utime(launcher, (100, 100))
    os.utime(receipt, (200, 200))
    assert status.execution_inventory_summary(tmp_path)["wsl"]["readiness"]["runtime_qualified"]
    os.utime(launcher, (300, 300))
    assert not status.execution_inventory_summary(tmp_path)["wsl"]["readiness"]["runtime_qualified"]
    os.utime(receipt, (400, 400))
    payload["result"]["motion_evidence"]["status"] = "fail"
    receipt.write_text(json.dumps(payload))
    assert not status.execution_inventory_summary(tmp_path)["wsl"]["readiness"]["runtime_qualified"]
