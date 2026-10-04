from __future__ import annotations

import json

import pytest
import requests

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


def test_server_context_is_bounded_and_partial_scene_edits_keep_source_metadata(monkeypatch):
    source = _document()
    source["scenes"].append({"scene_id": "scene-2", "start_sample": "48000", "end_sample": "96000",
                             "intent": "Keep", "renderer_hints": {"custom": "original"}})
    source["scenes"][0]["renderer_hints"] = {"custom": "preserved"}
    captured = {}
    provider = director_providers.OpenAICompatibleNemotronProvider(
        director_providers.ProviderEndpoint("http://director/v1", "served-nemotron"))

    def reply(messages):
        captured["request"] = json.loads(messages[1]["content"])
        answer = _plan("Directed")
        return json.dumps(answer)

    monkeypatch.setattr(provider, "_request", reply)
    plan = provider.plan(context={"source_document": source, "audio_path": "C:/private/song.wav",
        "video_assets": ["C:/private/scene.mp4"],
        "audio_evidence": {"features": {"energy": list(range(10000))}}}, instruction="Direct",
        mode="standard", specialist_results=[], correlation_id="corr-1")
    assert len(json.dumps(captured["request"])) < 35000
    assert "audio_path" not in captured["request"]["context"]
    assert captured["request"]["context"]["video_assets"] == ["scene.mp4"]
    assert len(captured["request"]["context"]["audio_evidence"]["features"]["energy"]["samples"]) == 24
    assert [scene.scene_id for scene in plan.document.scenes] == ["scene-1", "scene-2"]
    assert plan.document.scenes[0].renderer_hints["custom"] == "preserved"
    assert plan.document.scenes[1].renderer_hints["custom"] == "original"


def test_server_unchanged_compact_scene_preserves_full_intent(monkeypatch):
    source = _document("Detailed direction " * 100)
    copied = _plan(source["scenes"][0]["intent"][:400])
    provider = director_providers.OpenAICompatibleNemotronProvider(
        director_providers.ProviderEndpoint("http://director/v1", "served-nemotron"))
    monkeypatch.setattr(provider, "_request", lambda _messages: json.dumps(copied))
    plan = provider.plan(context={"source_document": source}, instruction="Change scene one",
        mode="standard", specialist_results=[], correlation_id="corr-1")
    assert plan.document.scenes[0].intent == source["scenes"][0]["intent"]
    assert plan.diagnostics["no_scene_edits"] is True


def test_server_capacity_error_is_actionable_without_leaking_response_body():
    response = requests.Response()
    response.status_code = 503
    response._content = b'{"error":"internal account identifier"}'
    with pytest.raises(director_providers.UserFacingError) as caught:
        director_providers._content(response)
    assert caught.value.code == "DIRECTOR_SERVER_BUSY"
    assert "internal account" not in str(caught.value)


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
    assert settings["primary_endpoint"] == "http://localhost:8000/v1"
    assert settings["primary_execution"] == "local"
    assert settings["default_quality"] == "advanced"
    assert settings["specialist_routing"] == "always_video"


def test_server_job_does_not_load_local_weights_or_send_local_audio_path(monkeypatch):
    calls = []
    class Server:
        def __init__(self, config):
            assert config.model == "served-nemotron"
        def plan(self, **kwargs):
            calls.append(kwargs)
            return DirectorPlan.model_validate(_plan())
    monkeypatch.setattr(director_providers, "OpenAICompatibleNemotronProvider", Server)
    monkeypatch.setattr(director_providers, "LocalNemotronProvider", lambda *a, **k: pytest.fail("local weights used"))
    result = director_providers.run_nemotron_director_job({
        "document": _document(), "instruction": "Direct", "source_revision": 4,
        "audio_path": "C:/private/song.wav", "audio_evidence": {"sections": ["intro"]},
        "director_provider_settings": {"primary_execution": "server", "primary_endpoint": "http://localhost:8000/v1",
            "primary_server_model": "served-nemotron", "specialist_enabled": False},
    })
    assert "audio_path" not in calls[0]["context"]
    assert calls[0]["context"]["audio_evidence"]["sections"] == ["intro"]
    assert result["provenance"]["execution"] == "server"
    assert result["provenance"]["model_id"] == "served-nemotron"


def test_server_cosmos_and_local_nemotron_can_coexist(monkeypatch):
    class Local:
        def __init__(self, *a, **k): pass
        def plan(self, **kwargs):
            assert len(kwargs["specialist_results"]) == 1
            return DirectorPlan.model_validate(_plan())
    class Server:
        def __init__(self, config): assert config.model == "served-cosmos"
        def analyze(self, request): return SpecialistResult(request_id=request.request_id, evidence=["motion"])
    monkeypatch.setattr(director_providers, "LocalNemotronProvider", Local)
    monkeypatch.setattr(director_providers, "OpenAICompatibleCosmosProvider", Server)
    result = director_providers.run_nemotron_director_job({
        "document": _document(), "instruction": "Direct", "source_revision": 4, "director_quality": "advanced",
        "director_provider_settings": {"primary_model_path": "C:/models/nemotron", "specialist_routing": "always_video",
            "specialist_execution": "server", "specialist_endpoint": "http://localhost:8001/v1", "specialist_server_model": "served-cosmos"},
    })
    assert result["provenance"]["specialist"]["status"] == "used"


def test_endpoint_credentials_are_never_persisted(tmp_path):
    settings = DirectorRuntimeSettingsStore(tmp_path).update({
        "primary_execution": "server", "primary_endpoint": "https://user:secret@example.test/v1",
        "primary_api_key": "secret", "specialist_endpoint": "https://example.test/v1?token=secret",
    })
    assert settings["primary_endpoint"] == settings["specialist_endpoint"] == ""
    assert "secret" not in json.dumps(settings)
