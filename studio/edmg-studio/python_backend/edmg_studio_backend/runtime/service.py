from __future__ import annotations

import json
import time
from pathlib import Path

from .cache import EngineCache, atomic_write
from .manager import RuntimeRegistry
from .package import discover
from .policy import load_policy
from .process import RuntimeProcess


def runtime_status(data_dir: Path, hardware: dict) -> dict:
    policy = load_policy(data_dir)
    package = discover(policy.package_path)
    report = None
    try:
        receipt = json.loads((data_dir / "tensorrt" / "diagnostics.json").read_text())
        if receipt.get("package_path") == policy.package_path:
            report = receipt
    except (OSError, ValueError):
        pass
    engines = EngineCache(data_dir).entries()
    return {"settings": policy.model_dump(), "hardware": hardware, "package": package,
            "diagnostics": report, "diagnostics_scope": "last_run_receipt_not_live_health",
            "state": "disabled" if not policy.enabled else package["status"],
            "capabilities": RuntimeRegistry().capabilities, "engines": engines,
            "cache_bytes": sum(e.get("size_bytes", 0) for e in engines if e.get("state") == "ready"),
            "accelerating": False, "acceleration_scope": "reported_in_each_render_result"}


def run_runtime_job(job, data_dir: Path, models_dir: Path, cancel_check, progress):
    policy = load_policy(data_dir)
    if not policy.enabled:
        raise RuntimeError("TensorRT is disabled in Settings")
    payload = job.payload
    with RuntimeProcess(data_dir, policy.package_path, cancel_check=cancel_check, progress=progress) as process:
        device = int(payload.get("device", 0))
        try:
            report = process.request("diagnose", device=device)
        except Exception as exc:
            from .process import RuntimeCanceled
            if isinstance(exc, RuntimeCanceled):
                raise
            report = {"healthy": False, "status": "broken", "reason": str(exc)}
        receipt = {**report, "tested_at": time.time(), "package_path": policy.package_path}
        atomic_write(data_dir / "tensorrt" / "diagnostics.json", json.dumps(receipt).encode())
        if payload.get("operation") == "diagnose":
            return receipt
        if not report.get("healthy"):
            raise RuntimeError(report.get("reason", "TensorRT diagnostics failed"))
        model_dir = models_dir / "internal" / "diffusers" / "hf_sd15_internal"
        if not model_dir.is_dir():
            raise RuntimeError("Install the managed SD1.5 model before optimizing its decoder")
        result = process.request("prepare", timeout_s=1800, model_dir=str(model_dir),
            shape=[1, 4, int(payload["height"]) // 8, int(payload["width"]) // 8],
            precision=payload.get("precision", "fp16"), device=device, allow_build=True)
        EngineCache(data_dir).trim(int(policy.cache_limit_gb * 1024**3), keep=result["manifest"]["engine_id"])
        return result
