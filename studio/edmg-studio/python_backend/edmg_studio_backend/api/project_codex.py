from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..revisions import RevisionRoute
from ..store.projects import ProjectStore


@dataclass(frozen=True)
class ProjectCodexDependencies:
    get_store: Callable[[], ProjectStore]
    run_render_review: Callable[..., dict[str, Any]]


def create_project_codex_router(deps: ProjectCodexDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)

    @router.post("/v1/projects/{project_id}/codex/render-review")
    def codex_render_review(project_id: str, payload: dict[str, Any]):
        project = deps.get_store().get(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        latest = project.meta.get("last_internal_render") if isinstance(project.meta, dict) else None
        return deps.run_render_review(
            project_dir=Path(deps.get_store().project_dir(project_id)), project_id=project_id,
            variant_index=int((payload or {}).get("variant_index") or 0),
            latest_render=latest if isinstance(latest, dict) else {}, prompt_extra=str((payload or {}).get("note") or ""),
        )

    return router
