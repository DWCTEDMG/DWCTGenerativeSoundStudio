from __future__ import annotations

import json

import pytest

from edmg_studio_backend.domain.director_plan import (
    DirectorPlan,
    SpecialistResult,
    validate_plan_locks,
)
from edmg_studio_backend.services import director_providers
from edmg_studio_backend.services.director_runtime_settings import DirectorRuntimeSettingsStore


def _document(intent: str = "Original") -> dict:
    return {
        "version": 1,
        "scenes": [{
            "scene_id": "scene-1", "start_sample": "0", "end_sample": "48000",
            "intent": intent,
        }],
    }


def _plan(intent: str = "Directed") -> dict:
    return {
        "schema_version": "1.0", "correlation_id": "corr-1",
        "director_model": "nvidia/nemotron", "mode": "standard",
        "document": _document(intent), "decisions": [], "specialist_results": [],
        "diagnostics": {},
    }


def test_director_plan_is_versioned_and_rejects_empty_document():
    assert DirectorPlan.model_validate(_plan()).schema_version == "1.0"
    invalid = _plan()
    invalid["document"] = {"version": 1, "scenes": []}
    with pytest.raises(ValueError, match="at least one scene"):
        DirectorPlan.model_validate(invalid)


def test_locked_scene_change_is_rejected():
    plan = DirectorPlan.model_validate(_plan("Changed"))
    with pytest.raises(ValueError, match="locked scene"):
        validate_plan_locks(plan, {"locked_scene_ids": ["scene-1"], "source_document": _document()})


def test_cosmos_routing_is_advanced_and_video_sensitive():
    assert not director_providers.should_route_cosmos("standard", "always_video", {"video_assets": ["x"]})
    assert director_providers.should_route_cosmos("advanced", "always_video", {})
    assert director_providers.should_route_cosmos("advanced", "automatic", {"video_assets": ["x"]})
    assert not director_providers.should_route_cosmos("advanced", "automatic", {})


def test_nemotron_provider_repairs_invalid_json_once(monkeypatch):
    responses = iter(["not-json", json.dumps(_plan())])
    provider = director_providers.OpenAICompatibleNemotronProvider(
        director_providers.ProviderEndpoint("http://director/v1", "nvidia/nemotron")
    )
    monkeypatch.setattr(provider, "_request", lambda _messages: next(responses))
    plan = provider.plan(context={"source_document": _document()}, instruction="Direct",
                         mode="standard", specialist_results=[], correlation_id="corr-1")
    assert plan.document.scenes[0].intent == "Directed"


def test_advanced_job_degrades_when_cosmos_is_unavailable(monkeypatch):
    class Nemotron:
        def __init__(self, _path, **_kwargs): pass
        def plan(self, **_kwargs): return DirectorPlan.model_validate(_plan())

    class Cosmos:
        def __init__(self, _path, **_kwargs): pass
        def analyze(self, _request): raise ValueError("offline")

    monkeypatch.setattr(director_providers, "LocalNemotronProvider", Nemotron)
    monkeypatch.setattr(director_providers, "LocalCosmosProvider", Cosmos)
    result = director_providers.run_nemotron_director_job({
        "document": _document(), "instruction": "Direct", "source_revision": 4,
        "director_quality": "advanced", "video_assets": ["reference.mp4"],
        "director_provider_settings": {
            "primary_model_path": "C:/models/nemotron", "specialist_model_path": "C:/models/cosmos",
            "specialist_enabled": True, "specialist_routing": "automatic",
        },
    })
    assert result["status"] == "draft"
    assert result["provenance"]["specialist"]["status"] == "unavailable"
    assert result["provenance"]["plan_validation"] == "passed"


def test_runtime_settings_default_to_nemotron_and_sanitize_routing(tmp_path):
    settings = DirectorRuntimeSettingsStore(tmp_path).update({
        "default_quality": "advanced", "specialist_routing": "always_video",
        "primary_endpoint": "http://localhost:8000/v1/",
    })
    assert settings["primary_provider"] == "nemotron"
    assert settings["primary_model"] == "hf_nemotron3_nano_omni_30b_a3b_reasoning_bf16"
    assert "primary_endpoint" not in settings
    assert settings["default_quality"] == "advanced"
    assert settings["specialist_routing"] == "always_video"
