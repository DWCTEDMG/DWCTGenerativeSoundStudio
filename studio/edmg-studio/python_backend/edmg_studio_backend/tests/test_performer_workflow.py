from __future__ import annotations

from edmg_studio_backend.domain.performer_workflow import build_performer_workflow_plan
from edmg_studio_backend.render_conductor.planner import build_advisory_render_plan
from edmg_studio_backend.schemas import ProjectSnapshot, RenderIntent


def test_performer_workflow_plan_routes_performance_scenes() -> None:
    plan = build_performer_workflow_plan(
        project_id="proj-1",
        variant_index=0,
        scenes=[
            {"id": "scene-1", "start_s": 0.0, "end_s": 4.0, "prompt": "lead performer under stage lights"},
            {"id": "scene-2", "start_s": 4.0, "end_s": 8.0, "prompt": "abstract color wash"},
        ],
        music_graph={"schemaVersion": "1.0", "sections": [{"start": 0.0, "end": 4.0, "energy": 0.8}]},
        director_mode="performance",
        environment={"engines": {"hosted_video": {"available": True}}},
    )
    assert plan["tasks"]
    assert plan["tasks"][0]["engine"] == "hosted_video"
    assert plan["tasks"][0]["model"]["repo_id"] == "Wan-AI/Wan2.2-S2V-14B"
    assert plan["tasks"][0]["provenance"]["lane"] == "experimental_high_end"


def test_advisory_plan_records_music_graph_diagnostics() -> None:
    snapshot = ProjectSnapshot(
        project_id="proj-123",
        analysis={
            "sections": [{"start": 0.0, "end": 5.0, "label": "intro", "energy": 0.4}],
            "beats": [0.0, 1.0, 2.0],
            "tags": ["pulse"],
        },
        plan={
            "variants": [
                {
                    "scenes": [
                        {"id": "scene-1", "start_s": 0.0, "end_s": 5.0, "prompt": "performer close-up on stage"},
                    ]
                }
            ]
        },
    )
    intent = RenderIntent(project_id="proj-123", variant_index=0)
    environment = {
        "director_mode": "performance",
        "engines": {
            "internal": {"available": True},
            "hosted_video": {"available": True, "quality_score": 0.8, "speed_score": 0.82},
            "proxy": {"available": True},
        },
    }
    plan = build_advisory_render_plan(intent, snapshot, environment=environment)
    joined = " ".join(plan.diagnostics)
    assert "music_graph_schema=1.0" in joined
    assert "music_graph_sections=1" in joined
    assert plan.sections[0].engine == "hosted_video"
