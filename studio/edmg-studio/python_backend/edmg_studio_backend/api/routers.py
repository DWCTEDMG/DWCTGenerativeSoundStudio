from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from ..domain.continuity_validation import validate_project_continuity
from ..domain.live_assets import compile_live_assets, sample_bounded_modulation
from ..domain.motion_grammar import apply_motion_phrases_to_timeline
from ..domain.music_graph import music_graph_from_analysis
from ..domain.live_cues import compile_live_cues
from ..domain.render_plan_v1 import enrich_render_plan
from ..domain.stem_modulation import mute_lane, normalize_modulation_matrix, scale_lane
from ..domain.template_packages import export_template_package, import_template_package
from ..domain.variant_review import apply_variant_review_decision, collect_variant_review
from ..domain.world_adapters import export_touchdesigner_adapter, export_unreal_adapter, run_adapter_simulator
from ..schemas import (
    AutosaveRequest,
    LiveCuePublishRequest,
    LiveAssetModulationRequest,
    MotionPhrasesApplyRequest,
    ProjectCreateRequest,
    RecoveryApplyRequest,
    RenderPlan,
    StemModulationUpdateRequest,
    TemplatePackageImportRequest,
    TimelineUpdateRequest,
    VariantReviewDecisionRequest,
    WorldAdapterExportRequest,
)
from ..services.live_publishers import publish_status, start_live_publish, stop_live_publish
from ..store.autosave import AutosaveJournal
from ..store.projects import ProjectStore


def create_system_router(*, readiness_report: Callable[[], dict[str, Any]]) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/v1/system/readiness")
    def system_readiness() -> dict[str, Any]:
        return readiness_report()

    return router


def create_project_router(
    *,
    store: ProjectStore,
    project_response: Callable[[Any], dict[str, Any]],
    assess_health: Callable[..., dict[str, Any]],
) -> APIRouter:
    """Core project + durability routes extracted from the monolith for WP-09."""
    router = APIRouter(tags=["projects"])

    @router.get("/v1/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": [p.__dict__ for p in store.list()]}

    @router.post("/v1/projects")
    def create_project(req: ProjectCreateRequest) -> dict[str, Any]:
        proj = store.create(req.name)
        return project_response(proj)

    @router.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        return project_response(proj)

    @router.get("/v1/projects/{project_id}/health")
    def get_project_health(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        report = assess_health(store.project_dir(project_id), proj.meta)
        return {"ok": True, "health": report}

    @router.get("/v1/projects/{project_id}/music_graph")
    def get_project_music_graph(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        return {"ok": True, "music_graph": graph}

    @router.get("/v1/projects/{project_id}/live_assets")
    def get_project_live_assets(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        review = collect_variant_review(store.project_dir(project_id), meta)
        assets = compile_live_assets(
            variant_review=review,
            stem_modulation=meta.get("stem_modulation") if isinstance(meta.get("stem_modulation"), dict) else {},
            music_graph=graph,
        )
        return {"ok": True, "live_assets": assets}

    @router.post("/v1/projects/{project_id}/live_assets/modulation")
    def post_project_live_asset_modulation(project_id: str, req: LiveAssetModulationRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        review = collect_variant_review(store.project_dir(project_id), meta)
        assets = compile_live_assets(
            variant_review=review,
            stem_modulation=meta.get("stem_modulation") if isinstance(meta.get("stem_modulation"), dict) else {},
            music_graph=graph,
        )
        sample = sample_bounded_modulation(
            assets,
            t=float(req.t),
            stem_values=dict(req.stem_values or {}),
        )
        return {"ok": True, "live_assets": assets, "modulation": sample}

    @router.get("/v1/projects/{project_id}/live_cues")
    def get_project_live_cues(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        cues = compile_live_cues(graph)
        return {"ok": True, "live_cues": cues, "music_graph": graph}

    @router.post("/v1/projects/{project_id}/live_cues/publish/start")
    def start_project_live_cue_publish(project_id: str, req: LiveCuePublishRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        cues = compile_live_cues(graph)
        status = start_live_publish(
            project_id,
            cues,
            osc_host=req.osc_host,
            osc_port=req.osc_port,
            midi_enabled=req.midi_enabled,
            websocket_enabled=req.websocket_enabled,
            playback_speed=req.playback_speed,
        )
        return {"ok": True, "publish": status, "event_count": int(cues.get("event_count") or 0)}

    @router.post("/v1/projects/{project_id}/live_cues/publish/stop")
    def stop_project_live_cue_publish(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        return {"ok": True, "publish": stop_live_publish(project_id)}

    @router.get("/v1/projects/{project_id}/live_cues/publish/status")
    def get_project_live_cue_publish_status(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        return {"ok": True, "publish": publish_status(project_id)}

    @router.post("/v1/projects/{project_id}/world_adapters/export")
    def export_project_world_adapter(project_id: str, req: WorldAdapterExportRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
        analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
        graph = music_graph_from_analysis(
            analysis,
            audio_filename=str(audio.get("filename") or "") or None,
            duration_s=float(audio.get("duration_s") or 0) or None,
        )
        cues = compile_live_cues(graph)
        if req.adapter == "unreal":
            payload = export_unreal_adapter(
                cues,
                bridge={"variant_index": req.variant_index, "sequence_name": req.sequence_name},
            )
        else:
            payload = export_touchdesigner_adapter(cues)
        simulation = run_adapter_simulator(req.adapter, payload)
        return {"ok": True, "adapter": req.adapter, "payload": payload, "simulation": simulation}

    @router.get("/v1/projects/{project_id}/variant_review")
    def get_project_variant_review(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        review = collect_variant_review(store.project_dir(project_id), proj.meta)
        return {"ok": True, "variant_review": review}

    @router.post("/v1/projects/{project_id}/variant_review/decision")
    def post_project_variant_review_decision(project_id: str, req: VariantReviewDecisionRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        try:
            result = apply_variant_review_decision(
                store.project_dir(project_id),
                artifact_path=req.artifact_path,
                decision=req.decision,
                notes=req.notes,
                cherry_pick_traits=list(req.cherry_pick_traits or []),
                lock_fields=list(req.lock_fields or []),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        review = collect_variant_review(store.project_dir(project_id), proj.meta)
        return {"ok": True, **result, "variant_review": review}

    @router.get("/v1/projects/{project_id}/render/conductor/plan")
    def get_project_render_conductor_plan(project_id: str, variant_index: int = 0) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        stored = meta.get("last_conductor_plan") if isinstance(meta.get("last_conductor_plan"), dict) else None
        if not stored:
            return {"ok": True, "plan": None, "stored": False}
        intent = meta.get("last_conductor_intent") if isinstance(meta.get("last_conductor_intent"), dict) else None
        plan_obj = RenderPlan.model_validate(stored)
        if int(plan_obj.variant_index) != int(variant_index):
            return {"ok": True, "plan": None, "stored": False, "variant_index": variant_index}
        enriched = enrich_render_plan(plan_obj, intent=intent, environment=None)
        return {
            "ok": True,
            "plan": enriched.model_dump(mode="json"),
            "intent": intent,
            "stored": True,
        }

    @router.get("/v1/projects/{project_id}/template_package/export")
    def export_project_template_package(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        package = export_template_package(
            project_id=project_id,
            project_name=getattr(proj, "name", None),
            meta=dict(proj.meta or {}),
        )
        return {"ok": True, "package": package}

    @router.post("/v1/projects/{project_id}/template_package/import")
    def import_project_template_package(project_id: str, req: TemplatePackageImportRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        try:
            applied = import_template_package(req.package, merge=req.merge)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        patch = applied.get("patch") if isinstance(applied.get("patch"), dict) else {}
        if req.merge:
            proj.meta.update(patch)
        else:
            for key, value in patch.items():
                proj.meta[key] = value
        store.save(proj)
        return {"ok": True, "applied": applied, "project": project_response(proj)}

    @router.get("/v1/projects/{project_id}/render/conductor/continuity")
    def get_project_render_continuity(project_id: str, variant_index: int = 0) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        visual_dna = meta.get("visual_dna") if isinstance(meta.get("visual_dna"), dict) else {}
        conductor_plan = meta.get("last_conductor_plan") if isinstance(meta.get("last_conductor_plan"), dict) else None
        report = validate_project_continuity(
            plan=meta.get("last_plan") if isinstance(meta.get("last_plan"), dict) else {},
            visual_dna=visual_dna,
            conductor_plan=conductor_plan,
            variant_index=variant_index,
        )
        return {"ok": True, "continuity": report}

    @router.get("/v1/projects/{project_id}/timeline")
    def get_timeline(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        return {"ok": True, "timeline": proj.meta.get("timeline") or {"layers": []}}

    @router.post("/v1/projects/{project_id}/timeline")
    def set_timeline(project_id: str, req: TimelineUpdateRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        proj.meta["timeline"] = req.timeline or {"layers": []}
        journal = AutosaveJournal(store.project_dir(project_id))
        journal.write_journal(
            project_id=project_id,
            meta=proj.meta,
            reason="timeline_save",
            dirty=True,
        )
        store.save(proj)
        journal.write_snapshot(project_id=project_id, meta=proj.meta, reason="timeline_save")
        journal.mark_clean()
        return {"ok": True, "timeline": proj.meta["timeline"]}

    @router.post("/v1/projects/{project_id}/motion_grammar/apply")
    def apply_motion_grammar(project_id: str, req: MotionPhrasesApplyRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        try:
            next_timeline = apply_motion_phrases_to_timeline(
                proj.meta.get("timeline") if isinstance(proj.meta.get("timeline"), dict) else {},
                list(req.phrases or []),
                overwrite_motion_track=bool(req.overwrite_motion_track),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        proj.meta["timeline"] = next_timeline
        store.save(proj)
        return {"ok": True, "timeline": next_timeline}

    @router.get("/v1/projects/{project_id}/stem_modulation")
    def get_stem_modulation(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        matrix = normalize_modulation_matrix(proj.meta.get("stem_modulation"))
        return {"ok": True, "matrix": matrix}

    @router.post("/v1/projects/{project_id}/stem_modulation")
    def update_stem_modulation(project_id: str, req: StemModulationUpdateRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        matrix = normalize_modulation_matrix(req.matrix or proj.meta.get("stem_modulation"))
        if req.mute_lane_id:
            matrix = mute_lane(matrix, req.mute_lane_id, bool(req.muted) if req.muted is not None else True)
        if req.scale_lane_id is not None and req.scale is not None:
            matrix = scale_lane(matrix, req.scale_lane_id, float(req.scale))
        proj.meta["stem_modulation"] = matrix
        store.save(proj)
        return {"ok": True, "matrix": matrix}

    @router.post("/v1/projects/{project_id}/autosave")
    def autosave_project(project_id: str, req: AutosaveRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        meta = dict(proj.meta or {})
        if isinstance(req.meta, dict) and req.meta:
            meta.update(req.meta)
        if req.timeline is not None:
            meta["timeline"] = req.timeline or {"layers": []}
        journal = AutosaveJournal(store.project_dir(project_id))
        payload = journal.write_journal(
            project_id=project_id,
            meta=meta,
            reason=req.reason or "autosave",
            dirty=True,
        )
        return {
            "ok": True,
            "autosave": {
                "saved_at": payload.get("saved_at"),
                "reason": payload.get("reason"),
                "dirty": True,
            },
        }

    @router.get("/v1/projects/{project_id}/recovery")
    def get_project_recovery(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        journal = AutosaveJournal(store.project_dir(project_id))
        candidates = journal.list_recovery_candidates()
        return {
            "ok": True,
            "needs_recovery": any(c.kind == "journal" for c in candidates),
            "candidates": [
                {
                    "kind": c.kind,
                    "saved_at": c.saved_at,
                    "reason": c.reason,
                    "path": c.path.name,
                }
                for c in candidates
            ],
        }

    @router.post("/v1/projects/{project_id}/recovery/apply")
    def apply_project_recovery(project_id: str, req: RecoveryApplyRequest) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        journal = AutosaveJournal(store.project_dir(project_id))
        source = str(req.source or "journal").strip().lower()
        payload: dict[str, Any] | None = None
        if source == "journal":
            payload = journal.read_journal()
        elif source == "snapshot":
            name = str(req.snapshot_name or "").strip()
            if not name:
                latest = next((c for c in journal.list_recovery_candidates() if c.kind == "snapshot"), None)
                if latest is None:
                    raise HTTPException(404, "No recovery snapshot found")
                payload = latest.payload
            else:
                snap_path = (journal.snapshot_dir / Path(name).name).resolve()
                if snap_path.parent != journal.snapshot_dir.resolve() or not snap_path.exists():
                    raise HTTPException(404, "Recovery snapshot not found")
                try:
                    loaded = json.loads(snap_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise HTTPException(400, f"Invalid recovery snapshot: {exc}") from exc
                payload = loaded if isinstance(loaded, dict) else None
        else:
            raise HTTPException(400, "source must be 'journal' or 'snapshot'")
        if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
            raise HTTPException(404, "No valid recovery payload found")
        proj.meta = dict(payload["meta"])
        store.save(proj)
        journal.write_snapshot(project_id=project_id, meta=proj.meta, reason="recovery_applied")
        journal.mark_clean()
        return {"ok": True, "project": proj.__dict__, "recovered_from": source}

    @router.post("/v1/projects/{project_id}/recovery/discard")
    def discard_project_recovery(project_id: str) -> dict[str, Any]:
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        journal = AutosaveJournal(store.project_dir(project_id))
        journal.mark_clean()
        return {"ok": True, "discarded": True}

    return router
