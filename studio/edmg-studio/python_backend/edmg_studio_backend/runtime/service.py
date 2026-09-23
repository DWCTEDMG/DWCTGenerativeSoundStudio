from __future__ import annotations

import json
import time
from pathlib import Path

from .adapters import ComponentAdapterRegistry
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
    model_installed: bool,
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
        and model_installed
    )
    reason = None
    if not adapter_available:
        reason = declared.get("reason") or "component_not_converted"
    elif not policy_enabled:
        reason = "tensorrt_disabled"
    elif not package_available:
        reason = "tensorrt_not_installed"
    elif not compatible:
        reason = "diagnostics_not_ready"
    elif not model_installed:
        reason = "managed_model_not_installed"
    if not adapter_available:
        display_state = "unsupported"
    elif not policy_enabled:
        display_state = "disabled"
    elif not package_available or not compatible:
        display_state = "incompatible"
    elif latest and latest.get("state") == "ready":
        display_state = "validated"
    elif latest and latest.get("state") in {"failed", "quarantined"}:
        display_state = "invalid"
    elif latest:
        display_state = latest.get("state", "adapter_available")
    else:
        display_state = "adapter_available"
    return {
        **declared,
        "adapter_status": declared["status"],
        "status": display_state,
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
    adapter_registry = ComponentAdapterRegistry()
    components = []
    for component in RuntimeRegistry().component_status():
        adapter = adapter_registry.get(component["model_family"], component["component"])
        model_dir = adapter.model_dir(models_dir) if adapter and models_dir else None
        components.append(_component_runtime_status(
            component,
            engines,
            policy_enabled=policy.enabled,
            package_available=installed,
            compatible=compatible,
            model_installed=bool(model_dir and model_dir.is_dir()),
        ))
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
        "supported_component_count": sum(
            1 for component in components if component["adapter_status"] == "adapter_available"
        ),
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
        operation = str(payload.get("operation", "optimize"))
        model_family = str(payload.get("model_family", "sd15"))
        requested_component = str(payload.get("component", "vae_decoder"))
        registry = ComponentAdapterRegistry()
        components = (
            registry.supported_components().get(model_family, [])
            if operation == "optimize_all"
            else [requested_component]
        )
        if not components:
            raise RuntimeError(f"No buildable TensorRT adapters for {model_family}")
        precision = payload.get("precision", "fp16")
        cache = EngineCache(data_dir)
        results = []
        for component in components:
            adapter = registry.require(model_family, component)
            model_dir = adapter.model_dir(models_dir)
            if model_dir is None or not model_dir.is_dir():
                raise RuntimeError(
                    f"Install managed model {adapter.model_id} before optimizing {model_family}/{component}"
                )
            if operation == "rebuild":
                matching = [
                    entry["engine_id"] for entry in cache.entries()
                    if entry.get("identity", {}).get("model") == model_family
                    and entry.get("identity", {}).get("component") == component
                ]
                for engine_id in matching:
                    cache.clear(engine_id)
            shape = [1, 4, int(payload["height"]) // 8, int(payload["width"]) // 8]
            result = process.request(
                "prepare", timeout_s=1800, model_dir=str(model_dir),
                shape=shape,
                precision=precision, device=device, model_family=model_family, component=component,
                allow_build=operation != "validate",
                validation_limits=policy.validation_limits(precision, component),
            )
            if operation == "validate":
                import numpy as np

                dtype = np.float16 if precision == "fp16" else np.float32
                generator = np.random.default_rng(1729)
                if component == "unet":
                    execution = process.request("execute", arrays={
                        "sample": generator.standard_normal(shape).astype(dtype),
                        "timestep": np.array([500.0], dtype=dtype),
                        "encoder_hidden_states": generator.standard_normal((1, 77, 768)).astype(dtype),
                    })
                else:
                    execution = process.request(
                        "execute", array=generator.standard_normal(shape).astype(dtype),
                    )
                result["validation_execution"] = {
                    "passed": True,
                    "inference_s": execution.get("inference_s"),
                    "scope": "cached_engine_deserialize_and_execute",
                }
            cache.trim(int(policy.cache_limit_gb * 1024**3), keep=result["manifest"]["engine_id"])
            results.append({**result, "model_family": model_family, "component": component})
        if len(results) == 1:
            return {**results[0], "operation": operation}
        return {"operation": operation, "model_family": model_family, "components": results}
