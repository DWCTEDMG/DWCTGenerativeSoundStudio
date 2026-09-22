from __future__ import annotations

import json
import time
from pathlib import Path

from .cache import EngineCache, atomic_write
from .manager import RuntimeRegistry
from .package import discover
from .policy import load_policy
from .process import RuntimeProcess


def _component_runtime_status(
    declared: dict,
    engines: list[dict],
    *,
    policy_enabled: bool,
    package_available: bool,
    compatible: bool,
    managed_model_installed: bool,
) -> dict:
    model_family = str(declared["model_family"])
    component = str(declared["component"])
    component_engines = [
        engine for engine in engines
        if engine.get("identity", {}).get("model") == model_family
        and engine.get("identity", {}).get("component") == component
    ]
    ready_engines = [engine for engine in component_engines if engine.get("state") == "ready"]
    latest = max(component_engines, key=lambda value: float(value.get("updated_at", 0)), default=None)
    adapter_available = declared["status"] == "adapter_available"
    eligible = bool(
        adapter_available
        and policy_enabled
        and package_available
        and compatible
        and managed_model_installed
    )
    reason = None
    if not adapter_available:
        reason = "component_not_converted"
    elif not policy_enabled:
        reason = "tensorrt_disabled"
    elif not package_available:
        reason = "tensorrt_not_installed"
    elif not compatible:
        reason = "diagnostics_not_ready"
    elif not managed_model_installed:
        reason = "managed_model_not_installed"
    return {
        **declared,
        "optimization_eligible": eligible,
        "optimization_reason": reason,
        "validated_engine_count": len(ready_engines),
        "profile_coverage": [engine["identity"].get("profile", {}) for engine in ready_engines],
        "last_benchmark": latest.get("benchmark") if latest else None,
        "last_engine_state": latest.get("state") if latest else "missing",
        "last_engine_id": latest.get("engine_id") if latest else None,
        "last_failure": latest.get("reason") if latest and latest.get("state") in {"failed", "quarantined"} else None,
    }


def runtime_status(data_dir: Path, hardware: dict, models_dir: Path | None = None) -> dict:
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
    installed = bool(package["installed"])
    available = installed
    healthy = bool(report and report.get("healthy") is True)
    compatible = bool(healthy and report.get("status") == "ready")
    receipt_state = report.get("status") if report else None
    state = "disabled" if not policy.enabled else receipt_state or package["status"]
    managed_model_installed = bool(
        models_dir and (models_dir / "internal" / "diffusers" / "hf_sd15_internal").is_dir()
    )
    components = [
        _component_runtime_status(
            component,
            engines,
            policy_enabled=policy.enabled,
            package_available=installed,
            compatible=compatible,
            managed_model_installed=managed_model_installed,
        )
        for component in RuntimeRegistry().component_status()
    ]
    return {
        "settings": policy.model_dump(),
        "hardware": hardware,
        "package": package,
        "diagnostics": report,
        "diagnostics_scope": "last_run_receipt_not_live_health",
        "state": state,
        "installed": installed,
        "available": available,
        "healthy": healthy,
        "compatible": compatible,
        "accelerating": False,
        "acceleration_scope": "reported_in_each_render_result",
        "tensorrt_version": report.get("version") if report else None,
        "cuda_status": report.get("cuda") if report else None,
        "pytorch_cuda_available": hardware.get("backend") == "cuda",
        "gpus": report.get("devices", []) if report else [],
        "supported_component_count": sum(1 for component in components if component["status"] == "adapter_available"),
        "capabilities": RuntimeRegistry().capabilities,
        "engines": engines,
        "components": components,
        "cache_bytes": sum(engine.get("size_bytes", 0) for engine in engines if engine.get("state") == "ready"),
    }


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
        precision = payload.get("precision", "fp16")
        result = process.request("prepare", timeout_s=1800, model_dir=str(model_dir),
            shape=[1, 4, int(payload["height"]) // 8, int(payload["width"]) // 8],
            precision=precision, device=device, allow_build=True,
            validation_limits=policy.validation_limits(precision))
        EngineCache(data_dir).trim(int(policy.cache_limit_gb * 1024**3), keep=result["manifest"]["engine_id"])
        return result
