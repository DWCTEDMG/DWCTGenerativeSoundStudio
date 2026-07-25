from __future__ import annotations

from edmg_studio_backend.domain.understand_corrections import apply_understand_corrections


def test_apply_understand_corrections_updates_analysis_and_invalidates_plans() -> None:
    meta = {
        "analysis": {
            "sections": [{"start": 0.0, "end": 4.0, "label": "intro"}],
            "features": {"bpm": 120.0},
        },
        "last_conductor_plan": {"plan_id": "old"},
        "last_conductor_intent": {"quality_tier": "balanced"},
    }
    result = apply_understand_corrections(
        meta,
        sections=[{"start": 0.0, "end": 8.0, "label": "verse", "energy": 0.7}],
        tempo_bpm=128.0,
        reason="workspace_edit",
    )
    assert result["changed"] == ["sections", "tempo"]
    assert result["invalidated"] == ["last_conductor_plan", "last_conductor_intent"]
    assert meta["analysis"]["sections"][0]["label"] == "verse"
    assert meta["analysis"]["features"]["bpm"] == 128.0
    assert "last_conductor_plan" not in meta
    assert meta["analysis"]["analysisRuns"][-1]["sources"] == ["understand_corrections"]


def test_apply_understand_corrections_noop_when_empty() -> None:
    meta = {"analysis": {"sections": []}, "last_conductor_plan": {"plan_id": "keep"}}
    result = apply_understand_corrections(meta)
    assert result["changed"] == []
    assert result["invalidated"] == []
    assert "last_conductor_plan" in meta
