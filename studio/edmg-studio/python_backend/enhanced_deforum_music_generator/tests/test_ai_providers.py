from __future__ import annotations

from enhanced_deforum_music_generator.core import ai_providers


def test_hf_provider_blocks_remote_code_and_remote_attention_kernels(monkeypatch):
    received: dict[str, object] = {}

    def fake_pipeline(task: str, **kwargs: object):
        received["task"] = task
        received.update(kwargs)
        return object()

    monkeypatch.setattr(ai_providers, "_TF_OK", True)
    monkeypatch.setattr(ai_providers, "pipeline", fake_pipeline)

    provider = ai_providers.HFTransformersProvider(
        ai_providers.AIProviderConfig(provider="transformers", model="attacker/model")
    )

    assert provider._pipeline is not None
    assert received == {
        "task": "text-generation",
        "model": "attacker/model",
        "trust_remote_code": False,
        "model_kwargs": {"attn_implementation": "eager"},
    }


def test_hf_provider_falls_back_when_safe_model_loading_fails(monkeypatch):
    def fail_pipeline(*_args: object, **_kwargs: object):
        raise RuntimeError("model rejected")

    monkeypatch.setattr(ai_providers, "_TF_OK", True)
    monkeypatch.setattr(ai_providers, "pipeline", fail_pipeline)

    provider = ai_providers.HFTransformersProvider(
        ai_providers.AIProviderConfig(provider="transformers", model="broken/model")
    )

    assert provider._pipeline is None
    assert provider.generate_prompts("lyrics", 2) == []
