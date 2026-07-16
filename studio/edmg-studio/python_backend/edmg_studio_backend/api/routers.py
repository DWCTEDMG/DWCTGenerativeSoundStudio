from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from ..domain.motion_grammar import apply_motion_phrases_to_timeline
from ..domain.music_graph import music_graph_from_analysis
from ..domain.live_cues import compile_live_cues
from ..domain.stem_modulation import mute_lane, normalize_modulation_matrix, scale_lane
from ..schemas import (
    AutosaveRequest,
    MotionPhrasesApplyRequest,
    ProjectCreateRequest,
    RecoveryApplyRequest,
    StemModulationUpdateRequest,
    TimelineUpdateRequest,
)
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
