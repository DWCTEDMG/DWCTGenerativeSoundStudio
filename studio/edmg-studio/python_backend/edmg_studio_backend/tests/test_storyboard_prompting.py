from __future__ import annotations

from edmg_ai_service.providers.fallback import RuleBasedPlanner
from edmg_ai_service.providers.storyboard_contract import storyboard_system_prompt
from edmg_ai_service.schemas import PlanRequest
from edmg_studio_backend import app as app_module
from edmg_studio_backend.services import internal_video
from edmg_studio_backend.services.internal_video import InternalVideoSettings


def test_rule_based_planner_outputs_motion_and_continuity_storyboard_contract() -> None:
    response = RuleBasedPlanner().plan(
        PlanRequest(
            title="Copper Orchid",
            duration_s=16.0,
            bpm=128.0,
            tags=["automaton", "orchids", "glasshouse"],
            user_notes="Keep one copper robot recognizable throughout.",
            num_variants=1,
            max_scenes=4,
        )
    )

    scenes = response.variants[0].scenes
    assert len(scenes) >= 3
    assert scenes[0].start_s == 0.0
    assert scenes[-1].end_s == 16.0
    assert all(
        left.end_s == right.start_s
        for left, right in zip(scenes, scenes[1:], strict=False)
    )
    assert all(scene.subject for scene in scenes)
    assert all(scene.action for scene in scenes)
    assert all(scene.camera for scene in scenes)
    assert all(scene.motion for scene in scenes)
    assert all(scene.environment_motion for scene in scenes)
    assert all(scene.continuity for scene in scenes)
    assert all(scene.transition for scene in scenes)
    assert len({scene.subject for scene in scenes}) == 1
    assert "preserve identity" in str(scenes[1].continuity).lower()
    assert "frozen pose" in str(scenes[0].negative_prompt).lower()
    assert "storyboard sheet" not in scenes[0].prompt.lower()


def test_ai_storyboard_contract_requires_filmable_temporal_fields() -> None:
    contract = storyboard_system_prompt().lower()

    assert "strict json" in contract
    assert "subject" in contract
    assert "action" in contract
    assert "environment_motion" in contract
    assert "continuity" in contract
    assert "transition" in contract
    assert "never a collage" in contract
    assert "frozen poses" in contract


def test_plan_enrichment_preserves_authored_motion_and_adds_render_contract() -> None:
    plan = {
        "variants": [
            {
                "visual_motifs": ["copper automaton"],
                "scenes": [
                    {
                        "start_s": 0.0,
                        "end_s": 4.0,
                        "prompt": "A copper automaton beside white orchids.",
                        "subject": "the same copper automaton with one blue glass eye",
                        "action": "turns its head and raises its right hand",
                        "camera": "slow left-to-right tracking move",
                        "motion": "progressive head, shoulder, and hand movement",
                        "environment_motion": "orchid petals sway and rain moves down the glass",
                        "continuity": "preserve the blue eye, copper plating, orchids, and screen direction",
                        "transition": "match-action continuation",
                    }
                ],
            }
        ]
    }

    enriched = app_module._enrich_normalized_plan(plan, {"tags": ["glasshouse"]})
    scene = enriched["variants"][0]["scenes"][0]

    assert scene["storyboard"]["shot_action"] == "turns its head and raises its right hand"
    assert scene["storyboard"]["camera_move"] == "slow left-to-right tracking move"
    assert scene["storyboard"]["environment_motion"] == (
        "orchid petals sway and rain moves down the glass"
    )
    assert scene["continuity_note"].startswith("preserve the blue eye")
    assert "visible action:" in scene["prompt_pack"].lower()
    assert "environment motion:" in scene["prompt_pack"].lower()
    assert "frozen pose" in scene["negative_prompt"].lower()


def test_plan_enrichment_preserves_structured_legacy_continuity_metadata() -> None:
    structured_continuity = {"subject": "performer", "wardrobe": "silver coat"}
    plan = {
        "variants": [
            {
                "scenes": [
                    {
                        "start_s": 0.0,
                        "end_s": 4.0,
                        "prompt": "A performer enters the light.",
                        "continuity": structured_continuity,
                        "continuity_note": "preserve the performer and silver coat",
                    }
                ]
            }
        ]
    }

    enriched = app_module._enrich_normalized_plan(plan, {})
    scene = enriched["variants"][0]["scenes"][0]

    assert scene["continuity"] == structured_continuity
    assert scene["continuity_note"] == "preserve the performer and silver coat"
    assert scene["storyboard"]["continuity"] == (
        "preserve the performer and silver coat"
    )


def test_storyboard_motion_plan_exposes_shot_phase_and_identity_contract() -> None:
    scene = {
        "start_s": 0.0,
        "end_s": 8.0,
        "prompt": "Copper automaton in a rain-soaked glasshouse.",
        "subject": "the same copper automaton with one blue glass eye",
        "action": "walks past the orchids and reaches toward the window",
        "camera": "measured left-to-right tracking move",
        "motion": "walking, head turn, and reaching gesture",
        "environment_motion": "petals sway and rain travels down the glass",
        "continuity": "preserve the blue eye, copper plating, and left-to-right screen direction",
        "transition": "match dissolve",
    }
    settings = InternalVideoSettings(
        motion_strategy="storyboard_full_motion",
        storyboard_shot_max_s=4.0,
        keyframe_continuity_mode="project",
        temporal_mode="video_model",
        video_model_motion_score_mode="manual",
        video_model_manual_motion_score=5,
        video_model_scene_motion="scene",
        video_model_prompt_refine=True,
    )

    plan = internal_video.describe_storyboard_motion_plan(
        scenes=[scene],
        timeline=None,
        settings=settings,
        duration_s=8.0,
    )

    assert plan is not None
    assert plan["shot_count"] == 2
    first, second = plan["shots"]
    assert first["shot_phase"] == "establish"
    assert second["shot_phase"] == "resolve"
    assert first["subject_anchor"] == "the same copper automaton with one blue glass eye"
    assert first["shot_action"] == "walks past the orchids and reaches toward the window"
    assert "same face" in first["prompt"].lower()
    assert "continuous motion window" in second["prompt"].lower()
