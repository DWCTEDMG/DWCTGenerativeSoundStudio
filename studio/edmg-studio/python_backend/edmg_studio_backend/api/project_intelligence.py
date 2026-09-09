from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from ..revisions import RevisionRoute
from ..schemas import (
    CreativeDirectionApplyRequest,
    VisualDNAFeedbackRequest,
    VisualDNAUpdateRequest,
)
from ..services.visual_dna import (
    build_prompt_hints,
    record_render_feedback,
    trait_id,
    update_visual_dna,
)
from ..store.projects import ProjectStore


@dataclass(frozen=True)
class ProjectIntelligenceDependencies:
    get_store: Callable[[], ProjectStore]
    load_visual_dna: Callable[[Any], Any]
    save_visual_dna: Callable[[Any, Any], Any]
    suggest_relinks: Callable[[Any, dict[str, Any]], dict[str, Any]]
    collect_project_bundle: Callable[[Any, Any], dict[str, Any]]
    list_director_modes: Callable[[], Any]
    build_creative_direction: Callable[..., dict[str, Any]]
    merge_creative_timeline_patch: Callable[..., dict[str, Any]]


def create_project_intelligence_router(deps: ProjectIntelligenceDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)

    def project(project_id: str):
        value = deps.get_store().get(project_id)
        if not value:
            raise HTTPException(404, "Project not found")
        return value

    @router.get("/v1/director_modes")
    def get_director_modes():
        return {"ok": True, "modes": deps.list_director_modes()}

    @router.get("/v1/projects/{project_id}/visual_dna")
    def get_project_visual_dna(project_id: str):
        dna = deps.load_visual_dna(project(project_id))
        traits = [{"id": trait_id(str(item.scope), item.value), **item.model_dump(mode="json")} for item in dna.trait_memory]
        return {"ok": True, "visual_dna": dna.model_dump(mode="json"), "traits": traits, "prompt_hints": build_prompt_hints(dna)}

    @router.get("/v1/projects/{project_id}/health/relink")
    def get_project_relink_suggestions(project_id: str):
        value = project(project_id)
        return deps.suggest_relinks(deps.get_store().project_dir(project_id), value.meta)

    @router.post("/v1/projects/{project_id}/health/collect")
    def post_collect_project(project_id: str):
        project(project_id)
        project_dir = deps.get_store().project_dir(project_id)
        destination = project_dir.parent / f"{project_id}_collect_{time.strftime('%Y%m%d-%H%M%S')}"
        return deps.collect_project_bundle(project_dir, destination)

    @router.post("/v1/projects/{project_id}/visual_dna/feedback")
    def post_project_visual_dna_feedback(project_id: str, req: VisualDNAFeedbackRequest):
        value = project(project_id)
        saved = deps.save_visual_dna(value, record_render_feedback(deps.load_visual_dna(value), feedback=req.feedback))
        return {"ok": True, "visual_dna": saved.model_dump(mode="json"), "prompt_hints": build_prompt_hints(saved)}

    @router.post("/v1/projects/{project_id}/visual_dna/update")
    def post_project_visual_dna_update(project_id: str, req: VisualDNAUpdateRequest):
        value = project(project_id)
        updated = update_visual_dna(deps.load_visual_dna(value), identity=req.identity, continuity=req.continuity,
                                   approve_trait_ids=list(req.approve_trait_ids or []),
                                   deprecate_trait_ids=list(req.deprecate_trait_ids or []), notes=req.notes)
        saved = deps.save_visual_dna(value, updated)
        traits = [{"id": trait_id(str(item.scope), item.value), **item.model_dump(mode="json")} for item in saved.trait_memory]
        return {"ok": True, "visual_dna": saved.model_dump(mode="json"), "traits": traits, "prompt_hints": build_prompt_hints(saved)}

    @router.get("/v1/projects/{project_id}/creative_direction")
    def get_creative_direction(project_id: str, variant_index: int = 0, preset: str = "cinematic",
                               director_mode: str | None = None, sensitivity: float = 1.0):
        payload = deps.build_creative_direction(project(project_id), variant_index=variant_index, preset=preset,
                                                sensitivity=sensitivity, director_mode=director_mode)
        return {"ok": True, "creative_direction": payload}

    @router.post("/v1/projects/{project_id}/creative_direction/apply_timeline_patch")
    def apply_creative_direction_timeline_patch(project_id: str, req: CreativeDirectionApplyRequest):
        value = project(project_id)
        payload = deps.build_creative_direction(value, variant_index=int(req.variant_index or 0),
                                                preset=str(req.preset or "cinematic"), sensitivity=float(req.sensitivity or 1.0),
                                                director_mode=req.director_mode)
        patch = payload.get("timeline_patch", {}).get("timeline") if isinstance(payload.get("timeline_patch"), dict) else {}
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(400, "Creative direction timeline patch is unavailable")
        base = value.meta.get("timeline") if isinstance(value.meta.get("timeline"), dict) else {}
        merged = deps.merge_creative_timeline_patch(base, patch, overwrite_tracks=bool(req.overwrite_tracks),
                                                    overwrite_camera=bool(req.overwrite_camera))
        value.meta["timeline"] = merged
        value.meta["last_creative_direction"] = {
            "variant_index": int(req.variant_index or 0), "preset": str(payload.get("preset") or req.preset or "cinematic"),
            "director_mode": str(payload.get("director_mode") or req.director_mode or "narrative"),
            "sensitivity": float(req.sensitivity or 1.0), "applied_at": time.time(),
        }
        deps.get_store().save(value)
        return {"ok": True, "timeline": merged, "creative_direction": payload}

    return router
