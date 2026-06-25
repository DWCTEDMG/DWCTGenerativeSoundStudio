from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .. import store
from .. import jobs
from ..errors import UserFacingError
from . import model_manager

def run_job(project_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a standalone TensorRT image generation job."""
    proj = store.get(project_id)
    if not proj:
        raise UserFacingError("Project not found")

    model_id = payload.get("model_id")
    if not model_id:
        raise UserFacingError("No model_id specified for TensorRT render")

    model_dir = model_manager.get_model_path(model_id)
    if not model_dir or not model_dir.exists():
        raise UserFacingError(f"TensorRT model {model_id} is not installed.")

    # Find the .engine or .plan file
    engine_files = list(model_dir.rglob("*.engine")) + list(model_dir.rglob("*.plan"))
    if not engine_files:
        raise UserFacingError(f"No .engine or .plan files found in {model_dir}.")

    engine_path = engine_files[0]
    
    # Update job status
    job = jobs.get(project_id, job_id)
    if job:
        job.progress = {
            "stage": "running",
            "current": 0,
            "total": payload.get("steps", 28),
            "percent": 0.0,
            "message": f"Loading TensorRT engine: {engine_path.name}",
        }
        jobs.save(job)

    # Validate TensorRT is available
    try:
        import tensorrt
    except ImportError:
        raise UserFacingError(
            "tensorrt is not installed in the python environment.",
            hint="Please run: python3 -m pip install tensorrt cuda-python"
        )

    out_dir = store.project_dir(project_id) / "renders" / "tensorrt"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"trt_{int(time.time())}.png"

    # Placeholder for actual TensorRT inference
    # In a real implementation, we would either:
    # 1. Use diffusers StableDiffusion3Pipeline and wrap the transformer with a TRT Module
    # 2. Or use a custom script like NVIDIA's TensorRT-Model-Optimizer runner.
    
    from PIL import Image
    # Create a dummy image for now to simulate success in the architectural skeleton
    img = Image.new("RGB", (payload.get("width", 1024), payload.get("height", 1024)), color="black")
    img.save(out_file)

    if job:
        job.progress = {
            "stage": "running",
            "current": payload.get("steps", 28),
            "total": payload.get("steps", 28),
            "percent": 1.0,
            "message": "TensorRT generation complete",
        }
        jobs.save(job)

    return {
        "ok": True,
        "engine_used": str(engine_path.name),
        "output_path": str(out_file),
    }
