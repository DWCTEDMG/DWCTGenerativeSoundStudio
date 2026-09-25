from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..runtime.cache import EngineCache, atomic_write
from ..runtime.policy import RuntimePolicy
from ..runtime.service import runtime_status
from ..execution.policy import ExecutionSettings
from ..execution.status import execution_inventory_summary
from ..services.model_load_coordinator import ModelLoadTimeout, model_load_lock


class RuntimeJobRequest(BaseModel):
    operation: Literal["diagnose", "optimize", "optimize_all", "rebuild", "validate"] = "diagnose"
    model_family: Literal[
        "sd15", "sdxl", "sd3", "flux", "svd", "animatediff",
        "ltx_25", "wan", "hunyuan_video15", "qwen", "whisper",
    ] = "sd15"
    component: Literal[
        "vae_decoder", "text_encoder", "vision_encoder", "unet",
        "transformer", "language_model", "audio_encoder", "decoder",
    ] = "vae_decoder"
    device: int = Field(default=0, ge=0, le=63)
    width: int = Field(default=512, ge=64, le=1024, multiple_of=8)
    height: int = Field(default=512, ge=64, le=1024, multiple_of=8)
    precision: Literal["fp32", "fp16"] = "fp16"


def create_runtime_router(settings, get_store, get_jobs, render_settings, hardware):
    router = APIRouter(tags=["runtime"])

    @router.get("/v1/runtime/status")
    def status():
        return runtime_status(settings.data_dir, hardware(), settings.models_dir)

    @router.post("/v1/runtime/settings")
    def save_policy(policy: RuntimePolicy):
        render_settings.update({"runtime": policy.model_dump()})
        return runtime_status(settings.data_dir, hardware(), settings.models_dir)

    @router.post("/v1/runtime/jobs", status_code=202)
    def enqueue(payload: RuntimeJobRequest):
        if not render_settings.get()["runtime"]["enabled"]:
            raise HTTPException(409, "TensorRT is disabled")
        store, jobs = get_store(), get_jobs()
        marker = settings.data_dir / "tensorrt" / "project.json"
        with model_load_lock(settings.data_dir / "tensorrt" / "project-lock", timeout_s=5):
            project_id = None
            if marker.is_file():
                try:
                    project_id = json.loads(marker.read_text())["project_id"]
                    if not store.get(project_id):
                        project_id = None
                except (ValueError, KeyError, OSError):
                    project_id = None
            if project_id is None:
                project_id = store.create("Runtime diagnostics and optimization").id
                atomic_write(marker, json.dumps({"project_id": project_id}).encode())
        job = jobs.create(project_id, "runtime_optimization", payload.model_dump())
        return {"job_id": job.id, "project_id": project_id, "status": job.status}

    @router.delete("/v1/runtime/tensorrt/cache/{engine_id}")
    def clear_engine(engine_id: str):
        try:
            EngineCache(settings.data_dir).clear(engine_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ModelLoadTimeout as exc:
            raise HTTPException(409, "Engine is busy") from exc
        return {"ok": True}

    @router.get("/v1/execution/profile")
    def execution_profile():
        return ExecutionSettings.model_validate(render_settings.get().get("execution") or {}).model_dump(mode="json")

    @router.put("/v1/execution/profile")
    def save_execution_profile(profile: ExecutionSettings):
        render_settings.update({"execution": profile.model_dump(mode="json")})
        return ExecutionSettings.model_validate(render_settings.get().get("execution") or {}).model_dump(mode="json")

    @router.get("/v1/execution/inventory")
    def execution_inventory():
        return execution_inventory_summary(settings.models_dir, probe=False)

    @router.post("/v1/execution/wsl/probe")
    def probe_wsl_execution():
        return execution_inventory_summary(settings.models_dir, probe=True)

    return router
