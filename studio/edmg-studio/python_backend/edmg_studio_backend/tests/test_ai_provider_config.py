from __future__ import annotations

from edmg_studio_backend import app as studio_app


class _FakeSecrets:
    def get(self, name: str) -> str | None:
        if name == "nvidia_api_key":
            return "nvapi-test"
        return None


def test_setup_ai_config_reports_diffusiongemma_nvidia_preset(monkeypatch):
    monkeypatch.setattr(studio_app, "secrets", _FakeSecrets())
    monkeypatch.setenv("EDMG_AI_PROVIDER", "nemotron_cloud")
    monkeypatch.setenv("EDMG_AI_NVIDIA_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("EDMG_AI_NVIDIA_MODEL", "google/diffusiongemma-26B-A4B-it")

    config = studio_app._setup_ai_config()

    assert config["provider"] == "nvidia_nim"
    assert config["model_family"] == "diffusiongemma"
    assert config["model"] == "google/diffusiongemma-26B-A4B-it"
    assert config["label"] == "DiffusionGemma (NVIDIA / OpenAI-compatible)"
    assert config["nvidia_api_key_configured"] is True
    assert "planning and prompt" in config["hint"]
    assert any(item["model"] == "google/diffusiongemma-26B-A4B-it" for item in config["model_presets"])
