from __future__ import annotations

from edmg_studio_backend.domain.render_plan_v1 import enrich_render_plan, step_cache_key
from edmg_studio_backend.domain.template_packages import export_template_package, import_template_package
from edmg_studio_backend.render_conductor.planner import build_advisory_render_plan
from edmg_studio_backend.schemas import ProjectSnapshot, RenderIntent, RenderStep


def test_step_cache_key_is_stable_for_same_inputs():
    step = RenderStep(
        id="scene-1-motion",
        kind="render_motion",
        adapter="internal",
        inputs={"scene_id": "scene-1", "duration_s": 4.0},
        outputs={"clip": "scene:scene-1:clip"},
    )
    first = step_cache_key(
        project_id="proj-a",
        variant_index=0,
        scene_id="scene-1",
        step=step,
        engine="internal",
        quality_tier="balanced",
    )
    second = step_cache_key(
        project_id="proj-a",
        variant_index=0,
        scene_id="scene-1",
        step=step,
        engine="internal",
        quality_tier="balanced",
    )
    assert first == second
    assert first.startswith("rp1:proj-a:v0:scene-1:render_motion:")


def test_enrich_render_plan_builds_task_graph_and_estimates():
    snapshot = ProjectSnapshot(
        project_id="proj-graph",
        plan={
            "variants": [
                {
                    "scenes": [
                        {"id": "scene-1", "start_s": 0.0, "end_s": 4.0, "prompt": "test scene"},
                    ]
                }
            ]
        },
    )
    intent = RenderIntent(project_id="proj-graph", variant_index=0)
    base = build_advisory_render_plan(
        intent,
        snapshot,
        environment={"engines": {"internal": {"available": True}, "proxy": {"available": True}}},
    )
    enriched = enrich_render_plan(base, intent=intent, environment={"engines": {"internal": {"available": True}}})

    assert enriched.estimates is not None
    assert enriched.estimates.task_count >= 3
    assert len(enriched.tasks) == enriched.estimates.task_count
    assert all(task.cache_key for task in enriched.tasks)
    assert len(enriched.dependencies) >= 2
    assert any(task.step_kind == "assemble" for task in enriched.tasks)
    assert any(w.code == "advisory_only" for w in enriched.warnings)


def test_export_and_import_template_package_round_trip():
    meta = {
        "visual_dna": {"version": 1, "project_id": "p1", "identity": {"motifs": ["neon"]}},
        "director_mode": "performance",
        "last_internal_render": {"model_id": "hf_sdxl_internal"},
        "audio": {"filename": "track.wav"},
        "last_plan": {"variants": [{"scenes": [{"id": "s1"}]}]},
    }
    exported = export_template_package(project_id="p1", project_name="Demo", meta=meta)
    assert exported["schema_version"] == 1
    assert "hf_sdxl_internal" in exported["models"]
    assert "track.wav" in exported["assets"]

    applied = import_template_package(exported, merge=True)
    assert "visual_dna" in applied["fields"]
    assert applied["patch"]["director_mode"] == "performance"
