from __future__ import annotations

import pytest

from edmg_studio_backend.render_conductor.planner import (
    NoRealRenderRouteError,
    build_advisory_render_plan,
)
from edmg_studio_backend.schemas import (
    EngineOutcomeMemory,
    PerformerWorkflowRunRequest,
    ProjectSnapshot,
    ProjectVisualDNA,
    RenderConductorPlanRequest,
    RenderIntent,
)


def test_new_workflow_defaults_only_allow_real_render_routes():
    intent = RenderIntent(project_id="proj-defaults")
    request = RenderConductorPlanRequest()
    performer = PerformerWorkflowRunRequest()

    assert "proxy" not in intent.allowed_engines
    assert "proxy" not in request.allowed_engines
    assert "tensorrt_standalone" in intent.allowed_engines
    assert "tensorrt_standalone" in request.allowed_engines
    assert performer.provider == "auto"
    assert performer.allow_mock_fallback is False


def test_advisory_render_plan_routes_by_scene_profile_and_dna_bias():
    visual_dna = ProjectVisualDNA(
        project_id="proj-123",
        identity={"motifs": ["neon skyline", "lead silhouette"]},
        prompt_guidance={"positive_fragments": ["cinematic night performance"]},
        engine_memory={
            "internal": EngineOutcomeMemory(
                success_rate=0.95,
                best_for=["continuity-heavy sequences"],
            )
        },
        learning_state={"confidence": 0.82},
    )
    snapshot = ProjectSnapshot(
        project_id="proj-123",
        project_name="Neon Drive",
        analysis={
            "sections": [
                {"start_s": 0.0, "end_s": 5.0, "energy": 0.42},
                {"start_s": 5.0, "end_s": 8.0, "energy": 0.92},
            ]
        },
        plan={
            "variants": [
                {
                    "scenes": [
                        {
                            "id": "scene-1",
                            "start_s": 0.0,
                            "end_s": 5.0,
                            "prompt": "keep the same reflective-jacket lead in a neon skyline",
                            "continuity_note": "preserve the same lead silhouette",
                            "approved": True,
                        },
                        {
                            "id": "scene-2",
                            "start_s": 5.0,
                            "end_s": 7.0,
                            "prompt": "hero glitch burst transition with strobe impact",
                        },
                    ]
                }
            ]
        },
        timeline={},
        visual_dna=visual_dna,
    )
    intent = RenderIntent(
        project_id="proj-123",
        variant_index=0,
        quality_tier="balanced",
        continuity_priority=0.6,
        speed_priority=0.8,
        style_lock_strength=0.8,
        sections=[
            {
                "scene_id": "scene-2",
                "continuity_priority": 0.1,
                "creative_goal": "make the transition hit harder than continuity lock",
            }
        ],
    )
    environment = {
        "engines": {
            "internal": {"available": True, "quality_score": 0.9, "speed_score": 0.55},
            "comfyui_motion": {"available": True, "quality_score": 0.82, "speed_score": 0.62},
            "comfyui_still": {"available": True, "quality_score": 0.88, "speed_score": 0.4},
            "hosted_video": {"available": False},
            "deforum_export": {"available": False},
        }
    }

    plan = build_advisory_render_plan(intent, snapshot, environment=environment)

    assert plan.advisory_only is True
    assert len(plan.sections) == 2
    assert plan.sections[0].scene_id == "scene-1"
    assert plan.sections[0].engine == "internal"
    assert any(step.kind == "repair_continuity" for step in plan.sections[0].steps)
    assert "project DNA motifs in play" in plan.sections[0].rationale

    assert plan.sections[1].scene_id == "scene-2"
    assert plan.sections[1].engine == "comfyui_motion"
    assert any(step.kind == "render_motion" for step in plan.sections[1].steps)
    assert plan.fallback_branches[1].reroute_to == "internal"
    assert any(item.startswith("visual_dna_confidence=") for item in plan.diagnostics)
    assert plan.estimates is not None
    assert len(plan.tasks) >= 3
    assert all(task.cache_key for task in plan.tasks)


def test_advisory_render_plan_rejects_when_only_proxy_is_available():
    snapshot = ProjectSnapshot(
        project_id="proj-789",
        plan={
            "variants": [
                {
                    "scenes": [
                        {
                            "id": 1,
                            "start_s": 0.0,
                            "end_s": 3.0,
                            "prompt": "short test scene",
                        }
                    ]
                }
            ]
        },
    )
    intent = RenderIntent(project_id="proj-789", variant_index=0, allowed_engines=["proxy"])

    with pytest.raises(NoRealRenderRouteError) as exc_info:
        build_advisory_render_plan(
            intent,
            snapshot,
            environment={
                "engines": {
                    "proxy": {"available": True},
                }
            },
        )

    assert "No real render route is available" in str(exc_info.value)
    assert "requested_engines=proxy" in exc_info.value.diagnostics
    assert "available_genuine_engines=none" in exc_info.value.diagnostics


def test_advisory_render_plan_selects_available_tensorrt_runtime():
    snapshot = ProjectSnapshot(
        project_id="proj-trt",
        plan={
            "variants": [
                {
                    "scenes": [
                        {
                            "id": "scene-1",
                            "start_s": 0.0,
                            "end_s": 3.0,
                            "prompt": "short test scene",
                        }
                    ]
                }
            ]
        },
    )
    intent = RenderIntent(
        project_id="proj-trt",
        variant_index=0,
        allowed_engines=["internal", "tensorrt_standalone"],
    )

    plan = build_advisory_render_plan(
        intent,
        snapshot,
        environment={
            "engines": {
                "internal": {"available": False},
                "tensorrt_standalone": {
                    "available": True,
                    "quality_score": 0.95,
                    "speed_score": 0.95,
                },
                "proxy": {"available": True},
            }
        },
    )

    assert plan.sections[0].engine == "tensorrt_standalone"
    assert all(branch.reroute_to != "proxy" for branch in plan.fallback_branches)
