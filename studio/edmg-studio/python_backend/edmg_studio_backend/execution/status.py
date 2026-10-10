"""Sanitized execution-plane readiness summaries for clients and operators."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..services import internal_video_models
from ..services.launcher_environment import launcher_env_path
from ..services.model_runtime_registry import execution_inventory_status
from .inventory import (
    CommandResult,
    GpuDiscoveryError,
    discover_windows_gpus,
    discover_wsl_gpus,
)

_READINESS_KEYS = (
    "wsl_installed",
    "distribution_running",
    "worker_environment_present",
    "gpu_visible",
    "model_installed",
    "worker_launchable",
    "generation_started",
    "artifact_validated",
    "runtime_qualified",
)


def execution_inventory_summary(models_dir: Path, *, probe: bool = False) -> dict[str, Any]:
    config = internal_video_models.hunyuan_runner_config()
    status = internal_video_models.hunyuan_runner_status(probe=probe)
    issues = [str(item) for item in status.get("issues") or []]
    wsl_installed = shutil.which("wsl.exe") is not None
    configured = config.mode == "wsl" and bool(config.distro)
    worker_environment_present = bool(config.python and config.repo)
    model_installed = bool(config.model_path and all(config.companions.values()))
    class Runner:
        def run(self, args: tuple[str, ...], timeout_seconds: float) -> CommandResult:
            result = subprocess.run(
                list(args), capture_output=True, text=True, timeout=timeout_seconds, check=False
            )
            return CommandResult(result.returncode, result.stdout, result.stderr)

    windows_gpus = []
    wsl_gpus = []
    discovery_blockers: list[dict[str, str]] = []
    try:
        windows_gpus = discover_windows_gpus(Runner())
    except GpuDiscoveryError as exc:
        discovery_blockers.append({"code": exc.code, "message": "Windows GPU inventory is unavailable."})
    # GPU discovery is a bounded inventory query, not a model/inference probe.
    # Native Models/Render must retain usable mappings on ordinary refreshes.
    if configured and config.distro:
        try:
            wsl_gpus = discover_wsl_gpus(Runner(), config.distro)
        except GpuDiscoveryError as exc:
            discovery_blockers.append({"code": exc.code, "message": "WSL GPU inventory is unavailable."})
    worker_launchable = bool(
        configured and wsl_installed and worker_environment_present and model_installed and not issues
    )
    # A Windows Whisper/LTX receipt cannot qualify the Ubuntu video worker.
    runtime_qualified = False
    receipt_path = Path(models_dir) / "internal/video/hf_hunyuan_video15_internal/runtime-validation.json"
    if configured and receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            runtime_qualified = (
                receipt.get("package_id") == "hf_hunyuan_video15_internal"
                and receipt.get("runtime_backend") == "hyvideo15_linux_subprocess"
                and receipt.get("success") is True
                and receipt.get("validation_level") == 5
                and receipt.get("result", {}).get("motion_evidence", {}).get("status") == "pass"
                # Configuration edits invalidate historical worker qualification.
                and launcher_env_path().is_file()
                and receipt_path.stat().st_mtime_ns >= launcher_env_path().stat().st_mtime_ns
            )
        except (OSError, ValueError, AttributeError):
            pass
    readiness = {
        "wsl_installed": wsl_installed,
        "distribution_running": bool(wsl_gpus),
        "worker_environment_present": worker_environment_present,
        "gpu_visible": bool(wsl_gpus),
        "model_installed": model_installed,
        "worker_launchable": worker_launchable,
        "generation_started": runtime_qualified,
        "artifact_validated": runtime_qualified,
        "runtime_qualified": runtime_qualified,
    }
    assert tuple(readiness) == _READINESS_KEYS
    blockers = list(discovery_blockers)
    if issues:
        blockers.append({
            "code": "WSL_RUNTIME_NOT_READY",
            "message": "The configured WSL worker is incomplete or failed its bounded probe.",
        })
    if not wsl_installed:
        blockers.insert(0, {
            "code": "WSL_NOT_INSTALLED",
            "message": "WSL2 is unavailable. Standard Windows execution remains available.",
        })
    inventory = execution_inventory_status(windows_gpus, wsl_gpus)
    return {
        "windows": {"available": True},
        "wsl": {
            "configured": configured,
            "distribution": config.distro or None,
            "readiness": readiness,
        },
        **inventory,
        "blockers": blockers,
        "probe_performed": probe,
    }
