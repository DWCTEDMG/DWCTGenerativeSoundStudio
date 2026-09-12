from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from edmg_studio_backend.contracts import (
    CONTRACT_MODELS,
    ArtifactManifestContract,
    CapabilityContract,
    CommandContract,
    CommandHistoryStateContract,
    CreativeIntentContract,
    CueContract,
    DirectorDocumentContract,
    HardwareProfileContract,
    JobContract,
    MusicGraphContract,
    ProjectContract,
    RenderPlanContract,
    adapt_legacy_cue,
    adapt_legacy_director_document,
    adapt_legacy_editor_command,
    adapt_legacy_job,
    adapt_legacy_project,
    adapt_legacy_render_plan,
    contract_schema_bundle,
    restore_legacy_director_document,
    restore_legacy_editor_command,
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
        DirectorDocumentContract(
            id="director-1", project_id="project-1",
            scenes=[{
                "scene_id": "scene-1", "start_sample": "9007199254740993",
                "end_sample": "9007199254788993", "intent": "A compact scene",
            }],
        ),
        CommandContract(
            id="operation-1", project_id="project-1", operation_id="operation-1",
            expected_revision=1, action="edit", label="Move clip",
            operations=[{"kind": "move", "track_id": "video", "clip_id": "clip-1", "position": "48000"}],
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
        HardwareProfileContract(
            id="workstation-1",
            backend="cuda",
            device="cuda:0",
            device_name="Fixture GPU",
            available_backends=["cpu", "cuda"],
            vram_gb=24.0,
            ram_gb=64.0,
            cpu_threads=16,
            platform="windows",
            machine="amd64",
            gpu_vendor="nvidia",
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

    assert len(contracts) == len(CONTRACT_MODELS) == 11
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


def test_hardware_profile_requires_cpu_fallback_and_available_selected_backend() -> None:
    common = {
        "id": "workstation-1", "device": "cuda:0", "device_name": "GPU",
        "cpu_threads": 8, "platform": "windows", "machine": "amd64",
    }
    with pytest.raises(ValidationError, match="selected hardware backend must be available"):
        HardwareProfileContract(backend="cuda", available_backends=["cpu"], **common)
    with pytest.raises(ValidationError, match="CPU must remain"):
        HardwareProfileContract(backend="cuda", available_backends=["cuda"], **common)


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
            "priority": 50,
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
    assert job.priority == 50
    assert [task.id for task in plan.tasks] == ["keyframe", "motion"]
    assert plan.dependencies[0].from_task == "keyframe"
    assert plan.dependencies[0].to_task == "motion"
    assert plan.allocations[0].preferred_provider == "internal"
    assert plan.estimates.seconds == 4.5
    assert plan.extensions["legacy_render_plan"]["variant_index"] == 2
    assert cue.frame == 15
    assert cue.payload == {"instruction": "Move in"}


def test_director_adapter_preserves_operational_extensions_and_exact_samples() -> None:
    source = {
        "version": 1,
        "analysis_revision": 7,
        "future_document": {"keep": True},
        "story_bible": {"revision": 2, "project_theme": "Arrival", "future_bible": "keep"},
        "scenes": [{
            "scene_id": "scene-1", "start_sample": "9007199254740993",
            "end_sample": "9007199254788993", "intent": "A traveler arrives",
            "subjects": [{"id": "traveler", "future_subject": 4}],
            "camera": {"reviewed_keyframes": [1, 2]},
            "renderer_hints": {"provider_id": "external"},
            "future_scene": {"keep": True},
        }],
    }

    contract = adapt_legacy_director_document(source, project_id="project-1", revision=9)
    restored = restore_legacy_director_document(contract)

    assert contract.schema_version == "1.0"
    assert contract.scenes[0].start_sample == "9007199254740993"
    assert contract.scenes[0].renderer_hints["provider_id"] == "external"
    assert restored["future_document"] == source["future_document"]
    assert restored["story_bible"]["future_bible"] == "keep"
    assert restored["scenes"][0]["future_scene"] == {"keep": True}
    assert restored["scenes"][0]["subjects"][0]["future_subject"] == 4
    assert restored["scenes"][0]["camera"]["reviewed_keyframes"] == [1, 2]


def test_editor_command_adapter_preserves_grouping_and_future_fields() -> None:
    source = {
        "operation_id": "operation-1", "expected_revision": 9, "action": "edit",
        "label": "Arrange scene", "timeline": None,
        "operations": [
            {"kind": "move", "track_id": "video", "clip_id": "a", "position": "9007199254740993"},
            {"kind": "set_mute", "track_id": "video", "clip_id": "b", "value": True},
        ],
        "future_request_field": {"keep": True},
    }

    contract = adapt_legacy_editor_command(source, project_id="project-1")
    restored = restore_legacy_editor_command(contract)

    assert contract.id == contract.operation_id == "operation-1"
    assert len(contract.operations) == 2
    assert contract.operations[0]["position"] == "9007199254740993"
    assert restored == source


def test_command_contract_enforces_action_payload_and_safe_history() -> None:
    with pytest.raises(ValidationError, match="require at least one operation"):
        CommandContract(
            id="op", project_id="project", operation_id="op", expected_revision=1,
            action="edit",
        )
    with pytest.raises(ValidationError, match="cannot include mutation payloads"):
        CommandContract(
            id="op", project_id="project", operation_id="op", expected_revision=1,
            action="undo", timeline={},
        )
    with pytest.raises(ValidationError, match="command ID must match"):
        CommandContract(
            id="contract-id", project_id="project", operation_id="operation-id",
            expected_revision=1, action="undo",
        )
    with pytest.raises(ValidationError, match="externally changed history"):
        CommandHistoryStateContract(can_undo=True, undo_label="Move", external_change=True)
