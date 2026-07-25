from __future__ import annotations

import json

from edmg_studio_backend.services.visual_dna import (
    build_prompt_hints,
    create_default_visual_dna,
    ingest_planner_payload,
    ingest_reactive_payload,
    load_visual_dna,
    record_render_feedback,
    save_visual_dna,
    visual_dna_json_schema,
)


def test_visual_dna_ingestion_persistence_and_feedback(tmp_path):
    dna = create_default_visual_dna("proj-123", "Neon Drive")

    planner_analysis = {
        "themes": [{"theme": "future nostalgia"}],
        "visualImagery": [{"element": "neon skyline"}],
    }
    planner_plan = {
        "scenes": [
            {
                "id": 1,
                "approved": True,
                "status": "approved",
                "text": "neon skyline, rain-slick street, lead silhouette",
                "negativePrompt": "muddy lighting, blurry face",
                "shotType": "tracking side profile",
                "transitionCue": "lift into chorus",
                "continuityNote": "keep the same reflective jacket silhouette",
            }
        ]
    }
    dna = ingest_planner_payload(
        dna,
        analysis=planner_analysis,
        plan=planner_plan,
        settings={"promptStyle": "cinematic"},
    )

    reactive_payload = {
        "metadata": {"renderMode": "performance-led"},
        "sections": [{"label": "chorus", "approved": True}],
        "schedules": {"zoom": "0:(1.0), 48:(1.2)", "rotation_y": "0:(0),48:(6)"},
        "repair_suggestions": [{"issue": "face drift", "action": "reuse anchor seed"}],
    }
    dna = ingest_reactive_payload(dna, payload=reactive_payload)

    dna = record_render_feedback(
        dna,
        feedback={
            "render_id": "render-001",
            "engine": "internal",
            "model": "hf_sdxl_internal",
            "user_outcome": "approved",
            "context": "continuity-heavy sequence",
            "palette_signature": ["electric cyan", "black chrome"],
            "motif_tags": ["lead silhouette", "wet street"],
            "positive_fragments": ["cinematic night performance", "volumetric haze"],
            "negative_fragments": ["muddy lighting", "broken anatomy"],
            "continuity_score": 0.91,
            "subject_anchor": "female lead in reflective jacket",
            "environment_anchor": "wet asphalt boulevard",
        },
    )

    saved = save_visual_dna(tmp_path, dna)
    reloaded = load_visual_dna(tmp_path, project_id="proj-123", project_name="Neon Drive")
    raw = json.loads((tmp_path / "analysis" / "visual_dna.json").read_text(encoding="utf-8"))

    assert raw["project_id"] == "proj-123"
    assert "future nostalgia" in reloaded.identity.core_themes
    assert "neon skyline" in reloaded.identity.motifs
    assert "tracking side profile" in reloaded.identity.camera_language
    assert "keep the same reflective jacket silhouette" in reloaded.continuity.transition_rules
    assert reloaded.engine_memory["internal"].approved_count == 1
    assert reloaded.engine_memory["internal"].success_rate == 1.0
    assert reloaded.learning_state.sources["planner_imports"] == 1
    assert reloaded.learning_state.sources["reactive_imports"] == 1
    assert reloaded.learning_state.sources["approved_renders"] == 1
    assert reloaded.learning_state.confidence > 0.0
    assert saved.fingerprints[-1].palette_signature == ["electric cyan", "black chrome"]


def test_visual_dna_prompt_hints_and_schema_support_lists():
    dna = create_default_visual_dna("proj-456")
    dna = record_render_feedback(
        dna,
        feedback={
            "render_id": "render-002",
            "engine": "comfyui_motion",
            "user_outcome": "needs_repair",
            "positive_fragments": ["hero frame", "concert backlight"],
            "negative_fragments": ["text", "watermark"],
            "failure_pattern": "identity drift",
            "mitigation": "increase anchor strength",
        },
    )

    hints = build_prompt_hints(dna)
    schema = visual_dna_json_schema()

    assert "hero frame" in hints["positive_fragments"]
    assert "text" in hints["negative_fragments"]
    assert dna.quality_memory.common_failures[0].pattern == "identity drift"
    assert schema["title"] == "ProjectVisualDNA"
