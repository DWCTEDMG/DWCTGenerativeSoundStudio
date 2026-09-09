from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderRouterDependencies:
    ai_status: Callable[[], Any]
    ai_config: Callable[[], dict[str, Any]]
    get_worker: Callable[[], Any]
    comfy_nodes: Callable[[], Any]
    comfy_object_info: Callable[[], dict[str, Any]]
    comfy_capabilities: Callable[[], dict[str, Any]]
    edmg_status: Callable[[], dict[str, Any]]
    edmg_verify: Callable[[], dict[str, Any]]
    edmg_template: Callable[[], dict[str, Any]]


def create_provider_router(deps: ProviderRouterDependencies) -> APIRouter:
    router = APIRouter(tags=["providers"])

    @router.get("/v1/ai/status")
    def ai_status():
        return {"ok": True, "ai": deps.ai_status(), "ai_config": deps.ai_config()}

    @router.get("/v1/worker/status")
    def worker_status():
        worker = deps.get_worker()
        if worker is None:
            return {"ok": True, "running": False}
        return {"ok": True, **worker.status().__dict__}

    @router.get("/v1/comfyui/nodes")
    def comfyui_nodes():
        return {"ok": True, "nodes": deps.comfy_nodes()}

    @router.get("/v1/comfyui/object_info")
    def comfyui_object_info():
        try:
            return deps.comfy_object_info()
        except Exception as exc:
            logger.exception("ComfyUI node discovery failed")
            raise HTTPException(502, "ComfyUI node discovery failed") from exc

    @router.get("/v1/comfyui/capabilities")
    def comfyui_capabilities():
        try:
            return deps.comfy_capabilities()
        except Exception as exc:
            logger.exception("ComfyUI queue discovery failed")
            raise HTTPException(502, "ComfyUI queue discovery failed") from exc

    @router.get("/v1/edmg/status")
    def edmg_status():
        return deps.edmg_status()

    @router.post("/v1/edmg/verify")
    def edmg_verify():
        return deps.edmg_verify()

    @router.get("/v1/edmg/deforum_template")
    def edmg_template():
        try:
            return deps.edmg_template()
        except Exception:
            return {"note": "EDMG Core not installed or template unavailable."}

    return router
