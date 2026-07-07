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


def test_openai_compat_defaults_to_hosted_nvidia_endpoint(monkeypatch):
    monkeypatch.setattr(studio_app, "secrets", _FakeSecrets())
    monkeypatch.setenv("EDMG_AI_PROVIDER", "openai_compat")
    monkeypatch.delenv("EDMG_AI_OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.delenv("EDMG_AI_OPENAI_COMPAT_MODEL", raising=False)

    config = studio_app._setup_ai_config()

    assert config["provider"] == "openai_compat"
    assert config["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert config["model"] == "nvidia/llama-3.1-nemotron-ultra-253b-v1"


def test_openai_compat_migrates_legacy_local_qwen_default(monkeypatch):
    monkeypatch.setattr(studio_app, "secrets", _FakeSecrets())
    monkeypatch.setenv("EDMG_AI_PROVIDER", "openai_compat")
    monkeypatch.setenv("EDMG_AI_OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("EDMG_AI_OPENAI_COMPAT_MODEL", "qwen3-8b")

    config = studio_app._setup_ai_config()

    assert config["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert config["model"] == "nvidia/llama-3.1-nemotron-ultra-253b-v1"
