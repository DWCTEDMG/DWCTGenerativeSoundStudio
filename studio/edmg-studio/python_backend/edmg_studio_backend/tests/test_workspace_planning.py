import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from edmg_ai_service.providers.openai_compat import OpenAICompatPlanner
from edmg_ai_service.schemas import PlanRequest, PlanResponse
from edmg_studio_backend.services.workspace_planning import plan_with_provider


def test_audio_is_sent_as_multimodal_content_not_saved_in_receipt(monkeypatch):
    sent = {}
    def post(url, **kwargs):
        sent.update(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "choices": [{"message": {"content": json.dumps({"variants": [{
                "name": "Music", "logline": "A journey", "scenes": [
                    {"start_s": 0, "end_s": 12, "prompt": "Moving sculpture"}]}]})}}]})
    monkeypatch.setattr("edmg_ai_service.providers.openai_compat.requests.post", post)
    request = PlanRequest(duration_s=12, input_audio={"data": "audio", "format": "wav"})
    response = OpenAICompatPlanner(base_url="http://localhost:8000", api_key=None, model="audio-model").plan(request)
    assert response.provider == "openai_compat"
    assert sent["messages"][1]["content"][1]["input_audio"] == request.input_audio
    assert "input_audio" not in request.model_dump()


def test_failed_selected_provider_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr("edmg_ai_service.provider_factory.build_provider", lambda _: SimpleNamespace(
        plan=lambda request: PlanResponse(provider="rule_based", variants=[])))
    with pytest.raises(RuntimeError, match="selected provider"):
        plan_with_provider({"duration_s": 12}, provider="ollama", model="missing-model")


def test_request_model_does_not_mutate_global_settings(monkeypatch):
    from edmg_ai_service.config import Settings
    before = Settings()
    seen = []
    def build(settings):
        seen.append(settings)
        return SimpleNamespace(plan=lambda request: PlanResponse(provider="ollama", model=settings.ollama_model, variants=[]))
    monkeypatch.setattr("edmg_ai_service.provider_factory.build_provider", build)
    result = plan_with_provider({"duration_s": 12}, provider="ollama", model="request-model")
    assert result["model"] == "request-model"
    assert Settings() == before
    assert seen[0].ollama_model == "request-model"


def test_non_audio_provider_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr("edmg_ai_service.provider_factory.build_provider", lambda _: object())
    with pytest.raises(ValueError, match="audio-capable"):
        plan_with_provider({}, provider="ollama", model=None, audio_path=tmp_path / "track.wav")


def test_selected_provider_publishes_one_shared_editable_draft(monkeypatch, tmp_path):
    from edmg_studio_backend import app as backend
    from edmg_studio_backend.schemas import PlanRequest as StudioPlanRequest
    from edmg_studio_backend.store.projects import ProjectStore
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Test")
    project.meta["analysis"] = {"revision": 1, "duration_s": 12, "features": {"duration_s": 12, "bpm": 120}}
    store.save(project)
    monkeypatch.setattr(backend, "store", store)
    monkeypatch.setattr("edmg_studio_backend.services.workspace_planning.plan_with_provider", lambda *args, **kwargs: {
        "provider": "openai_compat", "model": "test", "variants": [{"name": "New direction", "logline": "A journey",
        "scenes": [{"start_s": 0, "end_s": 12, "prompt": "New generated sculpture"}]}]})
    backend.generate_plan(project.id, StudioPlanRequest(provider="openai_compat", model="test", user_notes="My story", num_variants=1), "ai")
    saved = store.get(project.id)
    assert saved.meta["workspace_command"]["brief"] == "My story"
    assert saved.meta["director_workflow"]["status"] == "draft"
    assert "New generated sculpture" in str(saved.meta["director_workflow"]["document"])


def test_strict_ai_failure_preserves_project(monkeypatch, tmp_path):
    from edmg_studio_backend import app as backend
    from edmg_studio_backend.errors import UserFacingError
    from edmg_studio_backend.schemas import PlanRequest as StudioPlanRequest
    from edmg_studio_backend.store.projects import ProjectStore
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Keep me")
    store.save(project)
    monkeypatch.setattr(backend, "store", store)
    monkeypatch.setattr(backend.ai, "plan", lambda _: {"provider": "rule_based", "variants": []})
    with pytest.raises(UserFacingError):
        backend.generate_plan(project.id, StudioPlanRequest(), "ai")
    assert store.get(project.id).meta == project.meta


@pytest.mark.skipif(not os.environ.get("STUDIO_TEST_AUDIO"), reason="Set STUDIO_TEST_AUDIO to test a real track")
def test_real_track_analysis_to_editable_draft_and_timeline(tmp_path):
    from edmg_ai_service.audio import lightweight_audio_features
    from edmg_ai_service.providers.fallback import RuleBasedPlanner
    from edmg_studio_backend.store.projects import ProjectStore
    from edmg_studio_backend.domain.planner_schedule import attach_schedule_drafts
    from edmg_studio_backend.domain.director_workflow import reviewed_draft, apply_workflow

    path = Path(os.environ["STUDIO_TEST_AUDIO"])
    features = lightweight_audio_features(str(path))
    assert features["duration_s"] > 0
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Command center audio test")
    project.meta["analysis"] = {"revision": 1, "duration_s": features["duration_s"], "features": features}
    plan = RuleBasedPlanner().plan(PlanRequest(duration_s=features["duration_s"], bpm=features["bpm"], num_variants=1)).model_dump()
    project.meta["last_plan"] = plan
    attach_schedule_drafts(project, resulting_revision=project.revision + 1)
    saved = project.meta["director_workflow"]
    draft = reviewed_draft(project, saved["draft_id"], None)
    assert draft.document.scenes
    assert draft.schedule["camera_keys"] and draft.schedule["motion_keys"]
    apply_workflow(project, draft)
    store.save(project)
    reopened = store.get(project.id)
    assert reopened.meta["timeline"]["tracks"]
    assert reopened.meta["director_document"]["scenes"]
    print(f"Real audio: {features['duration_s']:.3f}s, {features['bpm']:.2f} BPM; shared draft and timeline persisted")
