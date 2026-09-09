from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, File, UploadFile

from ..revisions import RevisionRoute
from ..schemas import (
    AssembleVideoRequest,
    BuildUnrealImportPlanRequest,
    ExportDeforumRequest,
    ExportUnrealBridgeRequest,
    ImportUnrealBridgeReturnRequest,
)


@dataclass(frozen=True)
class ProjectOutputDependencies:
    list_assets: Callable[..., Any]
    upload_ref: Callable[..., Any]
    export_comfyui_workflows: Callable[..., Any]
    assemble_video: Callable[..., Any]
    export_deforum: Callable[..., Any]
    unreal_preview: Callable[..., Any]
    export_unreal: Callable[..., Any]
    import_unreal: Callable[..., Any]
    unreal_import_plan: Callable[..., Any]
    list_outputs: Callable[..., Any]
    get_file: Callable[..., Any]
    multipart_available: bool


def create_project_output_router(deps: ProjectOutputDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)

    @router.get("/v1/projects/{project_id}/assets")
    def list_assets(project_id: str):
        return deps.list_assets(project_id)

    if deps.multipart_available:

        @router.post("/v1/projects/{project_id}/assets/refs")
        async def upload_ref(project_id: str, file: UploadFile = File(...)):
            return await deps.upload_ref(project_id, file)

    else:

        @router.post("/v1/projects/{project_id}/assets/refs")
        async def upload_ref(project_id: str):
            return await deps.upload_ref(project_id)

    @router.get("/v1/projects/{project_id}/export/comfyui_workflows")
    def export_comfyui_workflows(
        project_id: str,
        variant_index: int = 0,
        model_id: str | None = None,
        workflow_family: str = "auto",
        source_asset: str | None = None,
        reference_asset: str | None = None,
        inpaint_mask: str | None = None,
        controlnet_model: str | None = None,
        conditioning_mode: str = "raw",
        width: int | None = None,
        height: int | None = None,
        steps: int | None = None,
        cfg: float | None = None,
        sampler: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        denoise_strength: float | None = None,
        loras_json: str | None = None,
        outpaint_json: str | None = None,
        controlnet_units_json: str | None = None,
        hires_fix_json: str | None = None,
        refiner_json: str | None = None,
        upscaler: str | None = None,
    ):
        return deps.export_comfyui_workflows(
            project_id, variant_index, model_id, workflow_family, source_asset,
            reference_asset, inpaint_mask, controlnet_model, conditioning_mode,
            width, height, steps, cfg, sampler, negative_prompt, seed,
            denoise_strength, loras_json, outpaint_json, controlnet_units_json,
            hires_fix_json, refiner_json, upscaler,
        )

    @router.post("/v1/projects/{project_id}/assemble_video")
    def assemble_video(project_id: str, req: AssembleVideoRequest):
        return deps.assemble_video(project_id, req)

    @router.post("/v1/projects/{project_id}/export/deforum")
    def export_deforum(project_id: str, req: ExportDeforumRequest):
        return deps.export_deforum(project_id, req)

    @router.get("/v1/projects/{project_id}/unreal/preview")
    def unreal_preview(project_id: str, variant_index: int = 0):
        return deps.unreal_preview(project_id, variant_index)

    @router.post("/v1/projects/{project_id}/export/unreal")
    def export_unreal(project_id: str, req: ExportUnrealBridgeRequest):
        return deps.export_unreal(project_id, req)

    @router.post("/v1/projects/{project_id}/import/unreal")
    def import_unreal(project_id: str, req: ImportUnrealBridgeReturnRequest):
        return deps.import_unreal(project_id, req)

    @router.post("/v1/projects/{project_id}/unreal/import-plan")
    def unreal_import_plan(project_id: str, req: BuildUnrealImportPlanRequest):
        return deps.unreal_import_plan(project_id, req)

    @router.get("/v1/projects/{project_id}/outputs")
    def list_outputs(project_id: str):
        return deps.list_outputs(project_id)

    @router.head("/v1/projects/{project_id}/file", include_in_schema=False)
    @router.get("/v1/projects/{project_id}/file")
    def get_file(project_id: str, path: str):
        return deps.get_file(project_id, path)

    return router
