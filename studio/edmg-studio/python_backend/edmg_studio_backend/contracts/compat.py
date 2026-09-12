"""Compatibility adapters from current Studio JSON documents to v1 contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .v1 import (
    AssetRef,
    CapabilityRequirement,
    CommandContract,
    CueContract,
    DirectorCameraContract,
    DirectorDocumentContract,
    DirectorEnvironmentContract,
    DirectorSceneContract,
    DirectorStoryBibleContract,
    DirectorSubjectContract,
    JobContract,
    PlanWarning,
    ProjectContract,
    RenderAllocation,
    RenderDependency,
    RenderEstimates,
    RenderPlanContract,
    RenderTaskContract,
    utc_now,
)


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _timestamp(value: object, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        return fallback or utc_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _split_extensions(payload: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if key not in known}


def adapt_legacy_director_document(
    payload: Mapping[str, Any], *, project_id: str, revision: int = 1
) -> DirectorDocumentContract:
    """Adapt the extensible operational Director document without losing future fields."""

    source = _mapping(payload)
    bible_source = _mapping(source.get("story_bible"))
    bible_known = {
        "revision", "project_theme", "narrative_summary", "visual_style", "characters",
        "locations", "continuity_rules", "forbidden_changes",
    }
    bible = DirectorStoryBibleContract(
        revision=bible_source.get("revision", 1),
        project_theme=str(bible_source.get("project_theme") or ""),
        narrative_summary=str(bible_source.get("narrative_summary") or ""),
        visual_style=str(bible_source.get("visual_style") or ""),
        characters=_mapping(bible_source.get("characters")),
        locations=_mapping(bible_source.get("locations")),
        continuity_rules=list(bible_source.get("continuity_rules") or []),
        forbidden_changes=list(bible_source.get("forbidden_changes") or []),
        extensions=_split_extensions(bible_source, bible_known),
    )
    scenes: list[DirectorSceneContract] = []
    for scene_value in source.get("scenes") or []:
        scene = _mapping(scene_value)
        subjects = []
        for subject_value in scene.get("subjects") or []:
            subject = _mapping(subject_value)
            subject_known = {"id", "role", "appearance_lock", "appearance_notes", "expression"}
            subjects.append(DirectorSubjectContract(
                id=str(subject.get("id") or ""), role=str(subject.get("role") or "primary"),
                appearance_lock=bool(subject.get("appearance_lock", True)),
                appearance_notes=list(subject.get("appearance_notes") or []),
                expression=str(subject.get("expression") or ""),
                extensions=_split_extensions(subject, subject_known),
            ))
        camera = _mapping(scene.get("camera"))
        camera_known = {"shot_type", "movement", "stability", "motion_strength"}
        environment = _mapping(scene.get("environment"))
        environment_known = {"location_id", "location", "weather", "secondary_motion"}
        scene_known = {
            "scene_id", "start_sample", "end_sample", "intent", "continuity_mode", "subjects",
            "actions", "camera", "environment", "lighting", "renderer_hints",
        }
        scenes.append(DirectorSceneContract(
            scene_id=str(scene.get("scene_id") or ""),
            start_sample=scene.get("start_sample", "0"), end_sample=scene.get("end_sample"),
            intent=str(scene.get("intent") or ""),
            continuity_mode=scene.get("continuity_mode", "continuous"), subjects=subjects,
            actions=list(scene.get("actions") or []),
            camera=DirectorCameraContract(
                shot_type=str(camera.get("shot_type") or ""), movement=str(camera.get("movement") or ""),
                stability=str(camera.get("stability") or ""),
                motion_strength=camera.get("motion_strength", 0.4),
                extensions=_split_extensions(camera, camera_known),
            ),
            environment=DirectorEnvironmentContract(
                location_id=str(environment.get("location_id") or ""),
                location=str(environment.get("location") or ""), weather=str(environment.get("weather") or ""),
                secondary_motion=list(environment.get("secondary_motion") or []),
                extensions=_split_extensions(environment, environment_known),
            ),
            lighting=_mapping(scene.get("lighting")), renderer_hints=_mapping(scene.get("renderer_hints")),
            extensions=_split_extensions(scene, scene_known),
        ))
    known = {"version", "story_bible", "scenes", "analysis_revision"}
    return DirectorDocumentContract(
        id=f"{project_id}-director", project_id=project_id, revision=max(1, revision),
        operational_version=source.get("version", 1), story_bible=bible, scenes=scenes,
        analysis_revision=source.get("analysis_revision"),
        extensions=_split_extensions(source, known),
    )


def restore_legacy_director_document(contract: DirectorDocumentContract) -> dict[str, Any]:
    """Restore the operational ``version: 1`` shape with extensions in their original locations."""

    def merge(model, *, exclude: set[str]) -> dict[str, Any]:
        payload = model.model_dump(mode="json", exclude=exclude | {"extensions"})
        return {**payload, **model.extensions}

    scenes = []
    for scene in contract.scenes:
        payload = merge(scene, exclude=set())
        payload["subjects"] = [merge(subject, exclude=set()) for subject in scene.subjects]
        payload["camera"] = merge(scene.camera, exclude=set())
        payload["environment"] = merge(scene.environment, exclude=set())
        scenes.append(payload)
    return {
        "version": contract.operational_version,
        "story_bible": merge(contract.story_bible, exclude=set()),
        "scenes": scenes,
        "analysis_revision": contract.analysis_revision,
        **contract.extensions,
    }


def adapt_legacy_editor_command(
    payload: Mapping[str, Any], *, project_id: str
) -> CommandContract:
    """Adapt the operational editor command while retaining future request fields."""

    source = _mapping(payload)
    operation_id = str(source.get("operation_id") or "").strip()
    known = {
        "operation_id", "expected_revision", "action", "label", "operations", "timeline"
    }
    return CommandContract(
        id=operation_id,
        project_id=project_id,
        operation_id=operation_id,
        expected_revision=source.get("expected_revision"),
        action=source.get("action"),
        label=str(source.get("label") or "Timeline edit"),
        operations=list(source.get("operations") or []),
        timeline=_mapping(source.get("timeline")) if source.get("timeline") is not None else None,
        metadata={"legacy_request_extensions": _split_extensions(source, known)},
    )


def restore_legacy_editor_command(contract: CommandContract) -> dict[str, Any]:
    """Restore the current editor endpoint request shape."""

    extensions = _mapping(contract.metadata.get("legacy_request_extensions"))
    return {
        "operation_id": contract.operation_id,
        "expected_revision": contract.expected_revision,
        "action": contract.action,
        "label": contract.label,
        "operations": contract.operations,
        "timeline": contract.timeline,
        **extensions,
    }


def adapt_legacy_project(payload: Mapping[str, Any]) -> ProjectContract:
    """Adapt the current ``project.json`` shape without dropping extension data."""

    project_id = str(payload.get("id") or payload.get("project_id") or "").strip()
    name = str(payload.get("name") or payload.get("project_name") or "").strip()
    if not project_id or not name:
        raise ValueError("legacy project requires a stable id and name")

    created_at = _timestamp(payload.get("created_at"))
    updated_at = _timestamp(payload.get("updated_at"), fallback=created_at)
    metadata = _mapping(payload.get("meta") or payload.get("metadata"))
    audio_data = _mapping(metadata.get("audio"))
    audio: AssetRef | None = None
    filename = str(audio_data.get("filename") or "").strip()
    if filename:
        audio = AssetRef(
            id=f"{project_id}-audio",
            relative_path=f"assets/audio/{filename}",
            size_bytes=int(audio_data["size_bytes"]) if audio_data.get("size_bytes") is not None else None,
        )

    known = {"id", "project_id", "name", "project_name", "created_at", "updated_at", "meta", "metadata"}
    extensions = {str(key): value for key, value in payload.items() if key not in known}
    revision_raw = payload.get("revision")
    if revision_raw is None:
        revision_raw = metadata.get("revision", 1)
    try:
        revision = max(1, int(revision_raw))
    except (TypeError, ValueError):
        revision = 1

    return ProjectContract(
        id=project_id,
        name=name,
        revision=revision,
        created_at=created_at,
        updated_at=max(created_at, updated_at),
        audio=audio,
        timeline=_mapping(metadata.get("timeline")),
        metadata=metadata,
        extensions={"legacy_top_level": extensions} if extensions else {},
    )


def adapt_legacy_job(payload: Mapping[str, Any]) -> JobContract:
    """Adapt the process-local JSON job record to the frozen durable-job shape."""

    created_at = _timestamp(payload.get("created_at"))
    updated_at = _timestamp(payload.get("updated_at"), fallback=created_at)
    return JobContract(
        id=str(payload.get("id") or ""),
        project_id=str(payload.get("project_id") or ""),
        job_type=str(payload.get("type") or payload.get("job_type") or ""),
        status=str(payload.get("status") or "queued"),
        created_at=created_at,
        updated_at=max(created_at, updated_at),
        payload=_mapping(payload.get("payload")),
        result=_mapping(payload.get("result")) if payload.get("result") is not None else None,
        error=str(payload["error"]) if payload.get("error") is not None else None,
        progress=_mapping(payload.get("progress")) if payload.get("progress") is not None else None,
        priority=int(payload.get("priority") or 0),
    )


def adapt_legacy_render_plan(payload: Mapping[str, Any]) -> RenderPlanContract:
    """Represent the current section/step plan as a v1 task DAG.

    The original payload is retained in ``extensions`` so a round trip never
    silently loses current Render Conductor fields.
    """

    plan_id = str(payload.get("plan_id") or payload.get("id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if not plan_id or not project_id:
        raise ValueError("legacy render plan requires plan_id and project_id")

    tasks: list[RenderTaskContract] = []
    dependencies: list[RenderDependency] = []
    allocations: list[RenderAllocation] = []
    estimated_seconds = 0.0
    previous_by_section: dict[str, str] = {}

    for section_index, section_value in enumerate(payload.get("sections") or []):
        section = _mapping(section_value)
        scene_id = str(section.get("scene_id") or f"scene-{section_index}")
        estimated_seconds += float(section.get("estimated_seconds") or 0.0)
        for step_index, step_value in enumerate(section.get("steps") or []):
            step = _mapping(step_value)
            task_id = str(step.get("id") or f"{scene_id}-step-{step_index}")
            tasks.append(
                RenderTaskContract(
                    id=task_id,
                    kind=str(step.get("kind") or "render"),
                    inputs={"scene_id": scene_id, **_mapping(step.get("inputs"))},
                    outputs=_mapping(step.get("outputs")),
                )
            )
            previous = previous_by_section.get(scene_id)
            if previous:
                dependencies.append(RenderDependency(from_task=previous, to_task=task_id))
            previous_by_section[scene_id] = task_id
            allocations.append(
                RenderAllocation(
                    task_id=task_id,
                    capability=CapabilityRequirement(
                        media="video",
                        operation="assemble" if str(step.get("kind")) == "assemble" else "generate",
                        controls=["text"],
                    ),
                    preferred_provider=str(step.get("adapter") or section.get("engine") or "internal"),
                    fallbacks=[],
                )
            )

    created_at = _timestamp(payload.get("created_at"))
    diagnostics = [str(item) for item in payload.get("diagnostics") or []]
    variant_index = int(payload.get("variant_index") or 0)
    return RenderPlanContract(
        id=plan_id,
        project_id=project_id,
        revision=max(1, variant_index + 1),
        intent_revision=f"legacy-intent-{variant_index}",
        project_revision="legacy-project-1",
        created_at=created_at,
        updated_at=created_at,
        tasks=tasks,
        dependencies=dependencies,
        allocations=allocations,
        estimates=RenderEstimates(seconds=max(0.0, estimated_seconds), disk_gb=0.0),
        warnings=[PlanWarning(code="legacy-diagnostic", message=item) for item in diagnostics],
        extensions={"legacy_render_plan": dict(payload)},
    )


def adapt_legacy_cue(payload: Mapping[str, Any], *, project_id: str) -> CueContract:
    """Adapt existing Unreal/workbench cue events to the common cue contract."""

    cue_id = str(payload.get("cue_id") or payload.get("id") or "").strip()
    if not cue_id:
        raise ValueError("legacy cue requires cue_id or id")
    instruction = payload.get("instruction")
    cue_payload: dict[str, Any] = {}
    if instruction is not None:
        cue_payload["instruction"] = str(instruction)
    return CueContract(
        id=cue_id,
        project_id=project_id,
        cue_type=str(payload.get("cue_type") or payload.get("cueType") or "cue"),
        time_seconds=float(payload.get("time_seconds") or payload.get("time") or 0.0),
        frame=int(payload["frame"]) if payload.get("frame") is not None else None,
        transport="unreal" if payload.get("transport") == "unreal" else "internal",
        target=str(payload["target"]) if payload.get("target") is not None else None,
        payload=cue_payload,
    )
