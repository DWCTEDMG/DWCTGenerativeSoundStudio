from __future__ import annotations

from edmg_studio_backend.render_conductor.planner import promote_proxy_sections
from edmg_studio_backend.schemas import AssemblyPlan, RenderPlan, RenderSectionPlan
from edmg_studio_backend.services.visual_dna import trait_id, update_visual_dna
from edmg_studio_backend.schemas import ProjectVisualDNA, TraitObservation


def test_promote_proxy_sections_upgrades_proxy_lanes() -> None:
    plan = RenderPlan(
        plan_id="plan-test",
        project_id="p1",
        summary="Advisory",
        sections=[
            RenderSectionPlan(scene_id="scene-0", engine="proxy", rationale="proxy fallback"),
            RenderSectionPlan(scene_id="scene-1", engine="internal", rationale="already hero"),
        ],
        assembly=AssemblyPlan(expected_output_path="out.mp4"),
    )
    updated, promoted = promote_proxy_sections(
        plan,
        target_engine="internal",
        quality_tier="quality",
        reason="hero pass",
    )
    assert promoted == ["scene-0"]
    by_id = {section.scene_id: section for section in updated.sections}
    assert by_id["scene-0"].engine == "internal"
    assert "quality_tier=quality" in " ".join(by_id["scene-0"].notes)
    assert by_id["scene-1"].engine == "internal"


def test_update_visual_dna_approve_and_deprecate() -> None:
    dna = ProjectVisualDNA(
        project_id="p1",
        trait_memory=[
            TraitObservation(scope="motif", value="neon skyline", state="observed", weight=0.4),
            TraitObservation(scope="palette", value="magenta", state="observed", weight=0.5),
        ],
    )
    approve_id = trait_id("motif", "neon skyline")
    deprecate_id = trait_id("palette", "magenta")
    updated = update_visual_dna(
        dna,
        approve_trait_ids=[approve_id],
        deprecate_trait_ids=[deprecate_id],
        identity={"motifs": ["neon skyline", "lead silhouette"]},
    )
    by_value = {trait.value: trait for trait in updated.trait_memory}
    assert by_value["neon skyline"].state == "declared"
    assert by_value["magenta"].state == "deprecated"
    assert "neon skyline" in updated.identity.motifs
    assert updated.learning_state.sources.get("approved_traits", 0) >= 1
