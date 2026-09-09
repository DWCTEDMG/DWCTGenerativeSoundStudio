from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, File, UploadFile

from ..revisions import RevisionRoute


@dataclass(frozen=True)
class ProjectMediaDependencies:
    preview_frame: Callable[..., Any]
    preview_segment: Callable[..., Any]
    preview_diffusion_segment: Callable[..., Any]
    upload_audio: Callable[..., Any]
    get_audio: Callable[..., Any]
    upload_overlay: Callable[..., Any]
    upload_mask: Callable[..., Any]
    analyze_audio: Callable[..., Any]
    multipart_available: bool


def create_project_media_router(deps: ProjectMediaDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)

    @router.head("/v1/projects/{project_id}/preview/frame", include_in_schema=False)
    @router.get("/v1/projects/{project_id}/preview/frame")
    def preview_frame(project_id: str, t: float = 0.0, w: int = 768, h: int = 432, force: int = 0):
        return deps.preview_frame(project_id, t, w, h, force)

    @router.head("/v1/projects/{project_id}/preview/segment", include_in_schema=False)
    @router.get("/v1/projects/{project_id}/preview/segment")
    def preview_segment(project_id: str, start_s: float = 0.0, end_s: float = 5.0, w: int = 768, h: int = 432, fps: int = 6, force: int = 0):
        return deps.preview_segment(project_id, start_s, end_s, w, h, fps, force)

    @router.head("/v1/projects/{project_id}/preview/diffusion_segment", include_in_schema=False)
    @router.get("/v1/projects/{project_id}/preview/diffusion_segment")
    def preview_diffusion_segment(project_id: str, start_s: float = 0.0, end_s: float = 2.0, w: int = 512, h: int = 512, fps: int = 2, steps: int = 6, cfg: float = 7.0, strength: float = 0.45, model_id: str = "auto", variant_index: int = 0, seed: int = 1337, prompt: str | None = None, force: int = 0):
        return deps.preview_diffusion_segment(project_id, start_s, end_s, w, h, fps, steps, cfg, strength, model_id, variant_index, seed, prompt, force)

    if deps.multipart_available:
        @router.post("/v1/projects/{project_id}/assets/audio")
        async def upload_audio(project_id: str, file: UploadFile = File(...)): return await deps.upload_audio(project_id, file)
        @router.post("/v1/projects/{project_id}/assets/overlay")
        async def upload_overlay_asset(project_id: str, file: UploadFile = File(...)): return await deps.upload_overlay(project_id, file)
        @router.post("/v1/projects/{project_id}/assets/mask")
        async def upload_mask_asset(project_id: str, file: UploadFile = File(...)): return await deps.upload_mask(project_id, file)
    else:
        @router.post("/v1/projects/{project_id}/assets/audio")
        async def upload_audio(project_id: str): return await deps.upload_audio(project_id)
        @router.post("/v1/projects/{project_id}/assets/overlay")
        async def upload_overlay_asset(project_id: str): return await deps.upload_overlay(project_id)
        @router.post("/v1/projects/{project_id}/assets/mask")
        async def upload_mask_asset(project_id: str): return await deps.upload_mask(project_id)

    @router.head("/v1/projects/{project_id}/audio", include_in_schema=False)
    @router.get("/v1/projects/{project_id}/audio")
    def get_project_audio(project_id: str): return deps.get_audio(project_id)

    @router.post("/v1/projects/{project_id}/analyze_audio")
    def analyze_audio(project_id: str): return deps.analyze_audio(project_id)

    return router
