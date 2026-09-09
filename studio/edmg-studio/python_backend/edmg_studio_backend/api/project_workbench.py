from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from ..revisions import RevisionRoute
from ..schemas import (
    ApplyPlanRequest,
    PlannerLabImportRequest,
    PlanRequest,
    ReactiveLabApplyRequest,
    StoryboardVariantUpdateRequest,
)


@dataclass(frozen=True)
class ProjectWorkbenchDependencies:
    plan: Callable[..., Any]
    analyze_and_plan: Callable[..., Any]
    apply_plan: Callable[..., Any]
    update_variant: Callable[..., Any]
    import_planner_lab: Callable[..., Any]
    apply_reactive_lab: Callable[..., Any]


def create_project_workbench_router(deps: ProjectWorkbenchDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)
    @router.post("/v1/projects/{project_id}/plan")
    def generate_plan(project_id: str, req: PlanRequest, mode: str = "auto"): return deps.plan(project_id, req, mode)
    @router.post("/v1/projects/{project_id}/analyze_and_plan")
    def analyze_and_build_plan(project_id: str, req: PlanRequest, mode: str = "auto"): return deps.analyze_and_plan(project_id, req, mode)
    @router.post("/v1/projects/{project_id}/timeline/apply_plan")
    def apply_plan_to_timeline(project_id: str, req: ApplyPlanRequest): return deps.apply_plan(project_id, req)
    @router.post("/v1/projects/{project_id}/plan/variant")
    def update_plan_variant(project_id: str, req: StoryboardVariantUpdateRequest): return deps.update_variant(project_id, req)
    @router.post("/v1/projects/{project_id}/planner_lab/import")
    def import_planner_lab(project_id: str, req: PlannerLabImportRequest): return deps.import_planner_lab(project_id, req)
    @router.post("/v1/projects/{project_id}/reactive_lab/apply")
    def apply_reactive_lab(project_id: str, req: ReactiveLabApplyRequest): return deps.apply_reactive_lab(project_id, req)
    return router
