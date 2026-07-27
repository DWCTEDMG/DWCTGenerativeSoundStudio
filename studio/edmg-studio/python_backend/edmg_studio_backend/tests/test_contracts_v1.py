from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from edmg_studio_backend.contracts import (
    CONTRACT_MODELS,
    ArtifactManifestContract,
    CapabilityContract,
    CreativeIntentContract,
    CueContract,
    JobContract,
    MusicGraphContract,
    ProjectContract,
    RenderPlanContract,
    adapt_legacy_cue,
    adapt_legacy_job,
    adapt_legacy_project,
    adapt_legacy_render_plan,
    contract_schema_bundle,
)
from edmg_studio_backend.contracts.v1 import (
    AssetRef,
    CapabilityRequirement,
    CurveRef,
    Meter,
    MusicFeatureCurves,
    MusicTimebase,
    RenderAllocation,
    RenderTaskContract,
    TempoMap,
)


def _curves() -> MusicFeatureCurves:
    def curve(name: str) -> CurveRef:
        return CurveRef(id=name, values=[0.0, 0.5, 1.0], sample_hz=10.0)

    return MusicFeatureCurves(
        loudness=curve("loudness"),
        onset_strength=curve("onset-strength"),
        spectral_flux=curve("spectral-flux"),
        brightness=curve("brightness"),
        harmonicity=curve("harmonicity"),
        energy_arc=curve("energy-arc"),
    )


def _all_contracts():
    source = AssetRef(id="audio-1", relative_path="assets/audio/tiny.wav", media_type="audio/wav")
    task = RenderTaskContract(id="task-1", kind="render", inputs={}, outputs={})
    return [
        ProjectContract(id="project-1", name="Fixture Project"),
        MusicGraphContract(
            id="music-graph-1",
            source=source,
            timebase=MusicTimebase(sample_rate=48_000, fps_hint=30.0, duration_seconds=1.0),
            tempo=TempoMap(bpm=120.0, confidence=1.0),
            meter=Meter(numerator=4, denominator=4, confidence=1.0),
            features=_curves(),
        ),
        CreativeIntentContract(
            id="intent-1",
            project_id="project-1",
            director_mode="abstract",
            concept="A compact contract fixture",
        ),
        RenderPlanContract(
            id="plan-1",
            project_id="project-1",
            intent_revision="intent-1:1",
            project_revision="project-1:1",
            tasks=[task],
            allocations=[
                RenderAllocation(
                    task_id=task.id,
                    capability=CapabilityRequirement(
                        media="video", operation="generate", controls=["text"]
                    ),
                    preferred_provider="internal",
                )
            ],
        ),
        ArtifactManifestContract(
            id="artifact-1",
            project_id="project-1",
            relative_path="outputs/videos/proxy.mp4",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            plan_revision="plan-1:1",
            project_revision="project-1:1",
            engine="internal",
        ),
        CapabilityContract(
            id="internal-video-generate",
            provider_id="internal",
            media="video",
            operation="generate",
            controls=["text", "image"],
            resolutions=["1280x720"],
            deterministic=True,
            supports_cancel=True,
            locality="in_process",
        ),
        JobContract(
            id="job-1",
            project_id="project-1",
            job_type="render",
            status="queued",
        ),
        CueContract(
            id="cue-1",
            project_id="project-1",
            cue_type="beat",
            time_seconds=0.5,
        ),
    ]


def test_all_frozen_contracts_have_common_persisted_fields() -> None:
    contracts = _all_contracts()

    assert len(contracts) == len(CONTRACT_MODELS) == 8
    for contract in contracts:
        payload = contract.model_dump(mode="json")
        assert payload["schema_version"] == "1.0"
        assert payload["contract_type"] in CONTRACT_MODELS
        assert payload["id"]
        assert payload["created_at"].endswith("Z")
        assert payload["updated_at"].endswith("Z")


def test_contracts_reject_unknown_fields_and_invalid_references() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectContract(id="p1", name="Project", unknown=True)

    with pytest.raises(ValidationError, match="unknown task IDs"):
        RenderPlanContract(
            id="plan-1",
            project_id="p1",
            intent_revision="intent-1",
            project_revision="project-1",
            allocations=[
                RenderAllocation(
                    task_id="missing",
                    capability=CapabilityRequirement(media="video", operation="generate"),
                )
            ],
        )


def test_schema_bundle_contains_each_named_contract() -> None:
    bundle = contract_schema_bundle()

    assert bundle["schema_version"] == "1.0"
    assert set(bundle["contracts"]) == set(CONTRACT_MODELS)
    for contract_type, schema in bundle["contracts"].items():
        assert schema["title"]
        assert schema["properties"]["contract_type"]["const"] == contract_type
        assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_legacy_project_adapter_preserves_current_shape_and_extensions() -> None:
    adapted = adapt_legacy_project(
        {
            "id": "legacy-project",
            "name": "Legacy Project",
            "created_at": "2026-07-14 01:02:03",
            "meta": {
                "revision": 3,
                "audio": {"filename": "song.wav", "size_bytes": 42},
                "timeline": {"fps": 30},
                "existing_feature": {"enabled": True},
            },
            "future_field": {"keep": "me"},
        }
    )

    assert adapted.id == "legacy-project"
    assert adapted.revision == 3
    assert adapted.audio and adapted.audio.relative_path == "assets/audio/song.wav"
    assert adapted.timeline == {"fps": 30}
    assert adapted.metadata["existing_feature"] == {"enabled": True}
    assert adapted.extensions["legacy_top_level"] == {"future_field": {"keep": "me"}}
    assert adapted.created_at == datetime(2026, 7, 14, 1, 2, 3, tzinfo=UTC)


def test_legacy_job_plan_and_cue_adapters_preserve_render_path_data() -> None:
    job = adapt_legacy_job(
        {
            "id": "job-1",
            "project_id": "project-1",
            "type": "render_internal",
            "status": "running",
            "created_at": "2026-07-14 01:00:00",
            "updated_at": "2026-07-14 01:00:01",
            "payload": {"seed": 7},
            "progress": {"stage": "frames", "percent": 50.0},
        }
    )
    plan = adapt_legacy_render_plan(
        {
            "plan_id": "plan-1",
            "project_id": "project-1",
            "variant_index": 2,
            "created_at": "2026-07-14 01:00:00",
            "sections": [
                {
                    "scene_id": "scene-1",
                    "engine": "internal",
                    "estimated_seconds": 4.5,
                    "steps": [
                        {"id": "keyframe", "kind": "keyframe", "adapter": "internal", "inputs": {}},
                        {"id": "motion", "kind": "video", "adapter": "internal", "outputs": {"clip": "scene.mp4"}},
                    ],
                }
            ],
            "diagnostics": ["compatibility fixture"],
        }
    )
    cue = adapt_legacy_cue(
        {"cue_id": "cue-1", "frame": 15, "time_seconds": 0.5, "cue_type": "push", "instruction": "Move in"},
        project_id="project-1",
    )

    assert job.job_type == "render_internal"
    assert job.payload == {"seed": 7}
    assert [task.id for task in plan.tasks] == ["keyframe", "motion"]
    assert plan.dependencies[0].from_task == "keyframe"
    assert plan.dependencies[0].to_task == "motion"
    assert plan.allocations[0].preferred_provider == "internal"
    assert plan.estimates.seconds == 4.5
    assert plan.extensions["legacy_render_plan"]["variant_index"] == 2
    assert cue.frame == 15
    assert cue.payload == {"instruction": "Move in"}
