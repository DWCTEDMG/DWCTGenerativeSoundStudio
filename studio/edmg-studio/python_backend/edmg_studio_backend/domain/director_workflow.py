"""Audio-to-direction drafts shared by both Workspace clients.

Preparation uses Studio's existing local planner and schedule compiler. It does
not load a model, submit a provider job, or replace approved project content.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from .director_scene import (
    DirectorDocument,
    ExtensibleModel,
    SceneSpec,
    compile_scene,
    variant_prompt_source_hash,
)
from .editor_commands import digest, execute
from .planner_schedule import apply_schedule, compile_schedule
from .project_time import ProjectClock, int64
from .workspace_reactive import apply_overrides, reactive_projection


class DirectionDraft(ExtensibleModel):
    version: Literal[2] = 2
    handoff_version: Literal[1] = 1
    draft_id: str
    status: Literal["draft", "applied"] = "draft"
    source_revision: int
    source_fingerprint: str
    document: DirectorDocument
    schedule: dict
    source_variant: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    variant_index: int = Field(default=0, ge=0)
    reactive_overrides: dict = Field(default_factory=dict)
    reactive_extensions: dict = Field(default_factory=dict)
    timeline_context: dict = Field(default_factory=dict)
    context_digest: str = ""
    context_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_handoff(cls, value):
        if isinstance(value, dict):
            version = value.get("version", 1)
            if version == 1:
                value = {**value, "version": 2, "handoff_version": 1}
            elif version != 2:
                raise ValueError(f"Unsupported Director workflow version {version}; this server supports versions 1-2")
            if value.get("handoff_version", 1) != 1:
                raise ValueError("Unsupported Director/Reactive handoff version")
        return value


def timeline_context(project, start_sample: str, end_sample: str) -> dict:
    """Build bounded, server-authoritative context for an exact timeline range."""
    start, end = int64(start_sample), int64(end_sample)
    if start < 0 or end <= start or str(start) != start_sample or str(end) != end_sample:
        raise ValueError("Selected range must use canonical sample strings with end after start")
    timeline = project.meta.get("timeline") or {}
    clock = ProjectClock.from_timeline(timeline)
    scenes = DirectorDocument.model_validate(
        (project.meta.get("director_workflow") or {}).get("document")
        or project.meta.get("director_document") or {}
    ).scenes
    ordered = sorted(scenes, key=lambda scene: int(scene.start_sample))
    selected = [scene for scene in ordered if int(scene.end_sample) > start and int(scene.start_sample) < end]
    selected_ids = {scene.scene_id for scene in selected}
    indices = [index for index, scene in enumerate(ordered) if scene.scene_id in selected_ids]
    neighbors = []
    if indices:
        neighbor_indices = {max(0, min(indices) - 1), min(len(ordered) - 1, max(indices) + 1)} - set(indices)
        neighbors = [ordered[index].model_dump(mode="json") for index in sorted(neighbor_indices)]

    def position(item):
        if "position_sample" in item:
            return int(item["position_sample"])
        return clock.samples(item.get("time_s", item.get("t", 0)))

    markers = [deepcopy(item) for item in timeline.get("markers", [])
               if isinstance(item, dict) and start <= position(item) < end]
    clips = []
    for track in timeline.get("tracks", []):
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips", []):
            if not isinstance(clip, dict):
                continue
            clip_start = int(clip.get("start_sample", clock.samples(clip.get("start_s", 0))))
            clip_end = int(clip.get("end_sample", clock.samples(clip.get("end_s", 0))))
            if clip_end <= start or clip_start >= end:
                continue
            data = clip.get("data") if isinstance(clip.get("data"), dict) else {}
            clips.append({
                "track_id": track.get("id"), "track_type": track.get("type"),
                "clip_id": clip.get("id"), "name": clip.get("name"),
                "start_sample": str(clip_start), "end_sample": str(clip_end),
                "media_asset_id": data.get("media_asset_id", clip.get("media_asset_id")),
                "active_take_id": data.get("active_take_id"),
                "takes": deepcopy(data.get("takes") or []),
            })
    analysis = project.meta.get("analysis") or {}
    transcript = analysis.get("transcript") or {}
    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    selected_segments = [deepcopy(segment) for segment in segments if isinstance(segment, dict)
                         and clock.samples(segment.get("end", segment.get("end_s", 0))) > start
                         and clock.samples(segment.get("start", segment.get("start_s", 0))) < end]
    context = {
        "version": 1,
        "selected_range": {"start_sample": start_sample, "end_sample": end_sample},
        "selected_scenes": [scene.model_dump(mode="json") for scene in selected],
        "neighbor_scenes": neighbors,
        "markers": markers,
        "transcript": {"text": str(transcript.get("text", ""))[:8000], "segments": selected_segments[:200]}
        if isinstance(transcript, dict) else {"text": str(transcript)[:8000], "segments": []},
        "lyrics": deepcopy(analysis.get("lyrics") or []),
        "analysis_excerpt": {key: deepcopy(analysis.get(key)) for key in
                             ("revision", "summary", "tags", "features") if key in analysis},
        "clips": clips,
    }
    return context


def set_timeline_context(draft: DirectionDraft, context: dict, revision: int) -> None:
    if context.get("version") != 1:
        raise ValueError("Unsupported timeline context version")
    draft.timeline_context = deepcopy(context)
    draft.context_digest = digest(context)
    draft.context_revision = revision


def source_fingerprint(project) -> str:
    return digest({key: project.meta.get(key) for key in
                   ("analysis", "audio", "director_document", "last_plan", "timeline")})


def workflow_state(project) -> dict:
    raw = project.meta.get("director_workflow")
    if not raw:
        return {"ok": True, "revision": project.revision, "status": "not_prepared", "draft": None,
                "director_job": deepcopy(project.meta.get("director_job"))}
    draft = DirectionDraft.model_validate(raw)
    stale = draft.status == "draft" and draft.source_fingerprint != source_fingerprint(project)
    clock = ProjectClock.from_timeline(project.meta.get("timeline") or {})
    plan = deepcopy(project.meta.get("last_plan") or {"title": project.name, "variants": []})
    variants = plan.setdefault("variants", [])
    variant = variant_from_document(draft.document, draft.source_variant, clock)
    variant["schedule_draft"] = deepcopy(draft.schedule)
    if draft.variant_index < len(variants):
        variants[draft.variant_index] = variant
    elif draft.variant_index == len(variants):
        variants.append(variant)
    plan["duration_s"] = draft.schedule["transport"]["duration_s"]
    return {"ok": True, "revision": project.revision,
            "status": "stale" if stale else draft.status, "draft": draft.model_dump(mode="json"),
            "reactive": reactive_projection(draft, clock), "plan": plan,
            "timeline_context": deepcopy(draft.timeline_context),
            "context_revision": draft.context_revision,
            "director_job": deepcopy(project.meta.get("director_job"))}


def scene_from_plan(scene: dict, index: int, clock: ProjectClock) -> SceneSpec:
    """Keep source fields/extensions while adding exact Director positions."""
    character = str(scene.get("character_lock") or "").strip()
    retained = deepcopy(scene.get("director_scene") or {})
    source_scene = {key: deepcopy(value) for key, value in scene.items()
                    if key not in ("director_scene", "director_source_prompt")}
    intent = (retained.get("intent") if scene.get("prompt") == scene.get("director_source_prompt") else None)
    return SceneSpec.model_validate({
        **retained,
        "scene_id": str(scene.get("id") or scene.get("scene_id") or f"audio-scene-{index + 1}"),
        "start_sample": str(clock.samples(scene.get("start_s", 0))),
        "end_sample": str(clock.samples(scene["end_s"])),
        "intent": str(intent or scene.get("prompt") or scene.get("name") or f"Scene {index + 1}"),
        "actions": [str(scene["action"])] if scene.get("action") else [],
        "camera": {**deepcopy(retained.get("camera") or {}), "movement": str(scene.get("camera") or ""), "shot_type": str(scene.get("shot_type") or "")},
        "environment": {**deepcopy(retained.get("environment") or {}), "location": str(scene.get("setting") or ""),
                        "secondary_motion": [str(scene["environment_motion"])] if scene.get("environment_motion") else []},
        "subjects": deepcopy(retained.get("subjects")) or ([{"id": "primary", "appearance_notes": [character], "appearance_lock": True}] if character else []),
        "renderer_hints": {**deepcopy(retained.get("renderer_hints") or {}), "source": "audio_analysis", "source_scene": source_scene,
                           "locked": bool(scene.get("locked"))},
    })


def variant_from_document(document: DirectorDocument, source_variant: dict, clock: ProjectClock) -> dict:
    originals = {str(scene.get("id") or scene.get("scene_id") or f"audio-scene-{index + 1}"): scene
                 for index, scene in enumerate(source_variant.get("scenes") or [])}
    scenes = []
    for scene in document.scenes:
        original = deepcopy(originals.get(scene.scene_id) or scene.renderer_hints.get("source_scene") or {})
        if original.get("locked"):
            original.setdefault("id", scene.scene_id)
            scenes.append(original)
            continue
        original.pop("render_prompt", None)
        prompt_packages = {
            engine: compile_scene(scene, document.story_bible, engine)
            for engine in ("hunyuan_video15", "ltx_25", "external")
        }
        original.update({
            "id": scene.scene_id, "start_s": float(clock.seconds(scene.start_sample)),
            "end_s": float(clock.seconds(scene.end_sample)),
            "prompt": prompt_packages["hunyuan_video15"]["prompt"],
            "action": "; ".join(scene.actions), "camera": scene.camera.movement,
            "setting": scene.environment.location, "shot_type": scene.camera.shot_type,
            "environment_motion": "; ".join(scene.environment.secondary_motion),
        })
        scene_source_hash = variant_prompt_source_hash(original)
        for package in prompt_packages.values():
            package["scene_source_hash"] = scene_source_hash
        original["director_scene"] = scene.model_dump(mode="json")
        original["director_source_prompt"] = original["prompt"]
        original["director_prompt_packages"] = prompt_packages
        scenes.append(original)
    return {**deepcopy(source_variant), "name": "Reviewed audio direction", "source": "director_workflow",
            "scenes": scenes}


def _schedule(project, document: DirectorDocument, source_variant: dict, revision: int, variant_index: int = 0) -> dict:
    clock = ProjectClock.from_timeline(project.meta.get("timeline") or {})
    analysis = project.meta.get("analysis") or {}
    duration = max(float(clock.seconds(scene.end_sample)) for scene in document.scenes)
    duration = max(duration, float(analysis.get("duration_s") or (analysis.get("features") or {}).get("duration_s") or 0))
    return compile_schedule(project_id=project.id, project_revision=revision, variant_index=variant_index,
                            variant=variant_from_document(document, source_variant, clock), analysis=analysis,
                            fps=float(clock.fps), duration_s=duration)


def prepare_workflow(project, plan_builder, *, resulting_revision: int,
                     source: str = "analysis", variant_index: int | None = None) -> DirectionDraft:
    analysis = project.meta.get("analysis") or {}
    if not analysis and not project.meta.get("last_plan") and not project.meta.get("director_document", {}).get("scenes"):
        raise ValueError("Analyze the project audio before preparing direction")
    analysis_revision = int(analysis.get("revision") or 1) if analysis else None
    clock = ProjectClock.from_timeline(project.meta.get("timeline") or {})
    saved = DirectorDocument.model_validate(project.meta.get("director_document") or {})
    plan = project.meta.get("last_plan") or {}
    variants = plan.get("variants") or []
    previous = project.meta.get("director_workflow") or {}
    if variant_index is None:
        variant_index = int(previous.get("variant_index") or 0)
    if variants and not 0 <= variant_index < len(variants):
        variant_index = 0
    source_variant = deepcopy(variants[variant_index]) if variants else deepcopy(previous.get("source_variant") or {})
    if source == "analysis" and previous.get("status") == "draft":
        # Reanalysis retains a user's reviewed draft, including unsaved-to-timeline
        # direction. The prior snapshot also remains in project history.
        saved = DirectorDocument.model_validate(previous["document"])
    if saved.scenes and source != "planner":
        # Reanalysis suggests new rhythm/energy scheduling without rewriting
        # approved identity, text, timing, or user-owned extension fields.
        document = saved.model_copy(deep=True)
    else:
        if not source_variant.get("scenes"):
            plan = plan_builder(project)
            source_variant = deepcopy(plan["variants"][0])
        scenes = [scene_from_plan(scene, index, clock)
                  for index, scene in enumerate(source_variant.get("scenes") or [])]
        bible = saved.story_bible.model_copy(deep=True)
        if not bible.project_theme:
            bible.project_theme = project.name
        if not bible.visual_style:
            bible.visual_style = ", ".join(str(tag) for tag in (analysis.get("tags") or [])[:5])
        if not bible.narrative_summary:
            transcript = analysis.get("transcript") or {}
            bible.narrative_summary = str(analysis.get("summary") or
                                         (transcript.get("text") if isinstance(transcript, dict) else transcript) or "")[:8000]
        document = saved.model_copy(update={"story_bible": bible, "scenes": scenes}, deep=True)
        if source == "planner":
            locked = {scene.scene_id: scene for scene in saved.scenes if scene.renderer_hints.get("locked")}
            document.scenes = [locked.pop(scene.scene_id, scene) for scene in document.scenes]
            document.scenes.extend(locked.values())
            document.scenes.sort(key=lambda scene: int(scene.start_sample))
    if not document.scenes:
        raise ValueError("The analyzed audio did not produce any valid scene ranges")
    document.analysis_revision = analysis_revision
    overrides = deepcopy(previous.get("reactive_overrides") or {})
    schedule = apply_overrides(_schedule(project, document, source_variant, resulting_revision, variant_index), overrides)
    if source == "planner" and variants:
        variants[variant_index]["schedule_draft"] = deepcopy(schedule)
    fingerprint = source_fingerprint(project)
    draft = DirectionDraft(
        draft_id=digest({"source": fingerprint, "document": document.model_dump(mode="json"), "schedule": schedule}),
        source_revision=resulting_revision, source_fingerprint=fingerprint, document=document,
        schedule=schedule, source_variant=source_variant, variant_index=variant_index, reactive_overrides=overrides,
        reactive_extensions=deepcopy(previous.get("reactive_extensions") or {}),
        timeline_context=deepcopy(previous.get("timeline_context") or {}),
        context_digest=str(previous.get("context_digest") or ""),
        context_revision=previous.get("context_revision"),
        provenance={"planner": "studio_local_audio_planner" if source == "analysis" and not variants else str(plan.get("source") or source), "analysis_revision": analysis_revision,
                    "inference": False, "output_policy": "draft", "sample_rate": clock.sample_rate,
                    "frame_rate": clock.to_dict()["frame_rate"]},
        warnings=list(schedule.get("warnings") or []),
    )
    if saved.scenes or variants:
        draft.warnings.append("Existing scene timing and creative choices were retained; review the updated music schedule.")
    active_ids = {key["id"] for kind in ("camera_keys", "motion_keys") for key in schedule[kind]}
    if overrides.keys() - active_ids:
        draft.warnings.append("Some manually refined keyframes no longer match scene timing. They are retained for placement review.")
    if previous and previous.get("draft_id") != draft.draft_id:
        history = project.meta.setdefault("director_workflow_history", [])
        history.append(deepcopy(previous))
        project.meta["director_workflow_history"] = history[-10:]
    project.meta["director_workflow"] = draft.model_dump(mode="json")
    return draft


def reviewed_draft(project, draft_id: str, document: DirectorDocument | None) -> DirectionDraft:
    draft = DirectionDraft.model_validate(project.meta.get("director_workflow") or {})
    if draft.draft_id != draft_id or draft.status != "draft":
        raise ValueError("This draft was replaced or already applied. Refresh the Workspace draft.")
    if draft.source_fingerprint != source_fingerprint(project):
        raise ValueError("The project sources changed. Prepare and review an updated draft before applying.")
    if draft.timeline_context and (
        draft.context_revision != draft.source_revision
        or draft.context_digest != digest(draft.timeline_context)
    ):
        raise ValueError("The captured timeline context changed. Generate and review a current draft before applying.")
    document = (document or draft.document).model_copy(deep=True)
    if document.analysis_revision != draft.document.analysis_revision:
        raise ValueError("Keep the draft linked to its source analysis revision")
    if not document.scenes:
        raise ValueError("A direction draft needs at least one scene")
    previous = {scene.scene_id: scene for scene in draft.document.scenes}
    candidate = {scene.scene_id: scene for scene in document.scenes}
    existing = bool(project.meta.get("director_document", {}).get("scenes") or project.meta.get("last_plan"))
    if existing:
        if previous.keys() != candidate.keys():
            raise ValueError("Keep the approved scene set when updating audio direction")
        for scene_id, before in previous.items():
            after = candidate[scene_id]
            if (before.start_sample, before.end_sample) != (after.start_sample, after.end_sample):
                raise ValueError("Keep approved scene timing when updating audio direction")
            if before.renderer_hints.get("locked") and before != after:
                raise ValueError("Unlock this scene in the editor before changing its direction")
            subjects = {subject.id: subject for subject in after.subjects}
            for subject in before.subjects:
                if subject.appearance_lock:
                    replacement = subjects.get(subject.id)
                    if replacement is None or not replacement.appearance_lock or replacement.appearance_notes != subject.appearance_notes:
                        raise ValueError("Keep locked subject appearances when updating audio direction")
    if draft.document != document:
        draft.schedule = apply_overrides(_schedule(project, document, draft.source_variant, project.revision + 1, draft.variant_index), draft.reactive_overrides)
    draft.document = document
    return draft


def apply_workflow(project, draft: DirectionDraft) -> None:
    clock = ProjectClock.from_timeline(project.meta.get("timeline") or {})
    timeline = apply_schedule(project.meta.get("timeline") or {}, draft.schedule)
    reactive = reactive_projection(draft, clock)
    timeline["reactive_lab"] = deepcopy(reactive)
    execute(project.meta, {"operation_id": "director-workflow:" + draft.draft_id,
                          "action": "replace", "label": "Apply Director scene schedule", "timeline": timeline})
    # Keep alternate variants and prior approved documents available for review.
    project.meta.setdefault("director_document_history", []).append(deepcopy(project.meta.get("director_document") or {}))
    project.meta["director_document_history"] = project.meta["director_document_history"][-10:]
    project.meta["director_document"] = draft.document.model_dump(mode="json")
    plan = deepcopy(project.meta.get("last_plan") or {})
    variants = plan.setdefault("variants", [])
    variant = variant_from_document(draft.document, draft.source_variant, clock)
    variant["schedule_draft"] = deepcopy(draft.schedule)
    if draft.variant_index < len(variants):
        project.meta.setdefault("director_plan_history", []).append(deepcopy(variants[draft.variant_index]))
        project.meta["director_plan_history"] = project.meta["director_plan_history"][-10:]
        variants[draft.variant_index] = variant
    else:
        variants.append(variant)
    plan.setdefault("title", project.name)
    plan["duration_s"] = draft.schedule["transport"]["duration_s"]
    project.meta["last_plan"] = plan
    project.meta.setdefault("reactive_lab_history", []).append(deepcopy(project.meta.get("last_reactive_lab") or {}))
    project.meta["reactive_lab_history"] = project.meta["reactive_lab_history"][-10:]
    project.meta["last_reactive_lab"] = reactive
    draft.status = "applied"
    project.meta["director_workflow"] = draft.model_dump(mode="json")
