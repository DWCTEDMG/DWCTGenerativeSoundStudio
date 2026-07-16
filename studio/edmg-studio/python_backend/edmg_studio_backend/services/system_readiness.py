from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import os
import shutil


SCHEMA_VERSION = 1
DISK_WARN_FREE_GB = 5.0
DISK_BLOCK_FREE_GB = 1.0

Status = str  # "ok" | "warn" | "blocked"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_rank(status: Status) -> int:
    if status == "blocked":
        return 2
    if status == "warn":
        return 1
    return 0


def _worst_status(*statuses: Status) -> Status:
    return max(statuses, key=_status_rank)


def _check(
    *,
    status: Status,
    hint: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": status != "blocked",
        "status": status,
        **fields,
    }
    if hint:
        payload["hint"] = hint
    return payload


def _probe_writable(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".edmg_write_probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"path": str(path), "writable": True, "exists": True}
    except Exception as exc:
        return {
            "path": str(path),
            "writable": False,
            "exists": path.exists(),
            "error": str(exc),
        }


def _disk_usage_for(path: Path) -> dict[str, Any]:
    target = path
    while True:
        try:
            usage = shutil.disk_usage(target)
            free_gb = round(usage.free / float(1024**3), 2)
            total_gb = round(usage.total / float(1024**3), 2)
            if free_gb < DISK_BLOCK_FREE_GB:
                status: Status = "blocked"
                hint = f"Less than {DISK_BLOCK_FREE_GB:g} GB free at {target}."
            elif free_gb < DISK_WARN_FREE_GB:
                status = "warn"
                hint = f"Low disk space ({free_gb} GB free) at {target}."
            else:
                status = "ok"
                hint = None
            return {
                "path": str(path),
                "volume_path": str(target),
                "free_gb": free_gb,
                "total_gb": total_gb,
                "status": status,
                "hint": hint,
            }
        except FileNotFoundError:
            parent = target.parent
            if parent == target:
                return {
                    "path": str(path),
                    "volume_path": str(path),
                    "free_gb": 0.0,
                    "total_gb": 0.0,
                    "status": "blocked",
                    "hint": f"Path does not exist and could not be measured: {path}",
                }
            target = parent
        except Exception as exc:
            return {
                "path": str(path),
                "volume_path": str(target),
                "free_gb": 0.0,
                "total_gb": 0.0,
                "status": "blocked",
                "hint": f"Unable to measure disk space for {path}: {exc}",
            }


def _summarize(overall: Status) -> str:
    if overall == "blocked":
        return "Blocked"
    if overall == "warn":
        return "Degraded"
    return "Ready"


def assess_system_readiness(
    *,
    ffmpeg_path: str,
    data_dir: Path,
    models_dir: Path,
    cache_dir: Path,
    logs_dir: Path,
    external_dir: Path | None = None,
    check_ffmpeg: Callable[[str], Mapping[str, Any]],
    check_runtime: Callable[[], Mapping[str, Any]],
    hardware_profile: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a typed readiness report for Studio dependencies and storage."""

    ff_raw = dict(check_ffmpeg(ffmpeg_path) or {})
    ff_ok = bool(ff_raw.get("ok"))
    ffmpeg = _check(
        status="ok" if ff_ok else "blocked",
        path=ff_raw.get("path") or ffmpeg_path,
        version=ff_raw.get("version"),
        error=ff_raw.get("error"),
        hint=None
        if ff_ok
        else (
            str(ff_raw.get("hint") or "").strip()
            or "Install FFmpeg or set EDMG_FFMPEG_PATH to a working ffmpeg executable."
        ),
    )

    runtime_raw = dict(check_runtime() or {})
    runtime_ok = bool(runtime_raw.get("ok"))
    runtime = _check(
        status="ok" if runtime_ok else "blocked",
        python_version=runtime_raw.get("python_version"),
        uv_version=runtime_raw.get("uv_version"),
        accelerator_profile=runtime_raw.get("accelerator_profile")
        or runtime_raw.get("profile"),
        lock_check=runtime_raw.get("lock_check"),
        sync_health=runtime_raw.get("sync_health"),
        immutable=bool(runtime_raw.get("immutable")),
        lock_sha256=runtime_raw.get("lock_sha256"),
        hint=None
        if runtime_ok
        else (
            str(runtime_raw.get("hint") or "").strip()
            or "Repair the locked Python toolchain from Setup or the source launcher."
        ),
    )

    hw = dict(hardware_profile() or {})
    backends = list(hw.get("available_backends") or ["cpu"])
    accelerated = any(name in backends for name in ("cuda", "directml", "mps"))
    gpu = _check(
        status="ok" if accelerated else "warn",
        backend=hw.get("backend") or "cpu",
        device=hw.get("device") or "cpu",
        device_name=hw.get("device_name") or "CPU",
        available_backends=backends,
        vram_gb=float(hw.get("vram_gb") or 0.0),
        ram_gb=float(hw.get("ram_gb") or 0.0),
        supports_directml=bool(hw.get("supports_directml")),
        directml_runtime_ready=bool(hw.get("directml_runtime_ready")),
        hint=None
        if accelerated
        else "No local GPU accelerator detected. CPU rendering remains available but will be slower.",
    )

    path_specs = [
        ("data", Path(data_dir)),
        ("models", Path(models_dir)),
        ("cache", Path(cache_dir)),
        ("logs", Path(logs_dir)),
    ]
    if external_dir is not None:
        path_specs.append(("external", Path(external_dir)))

    writable_entries = []
    for label, path in path_specs:
        entry = _probe_writable(path)
        entry["label"] = label
        writable_entries.append(entry)
    blocked_writes = [item for item in writable_entries if not item.get("writable")]
    writable_paths = _check(
        status="blocked" if blocked_writes else "ok",
        paths=writable_entries,
        hint=(
            "Studio cannot write to: "
            + ", ".join(str(item["path"]) for item in blocked_writes)
            if blocked_writes
            else None
        ),
    )

    disk_entries = [_disk_usage_for(path) for _, path in path_specs]
    # De-dupe by volume so one low drive is not reported many times as separate blocks.
    seen_volumes: set[str] = set()
    unique_disk_entries: list[dict[str, Any]] = []
    for entry in disk_entries:
        volume = str(entry.get("volume_path") or entry.get("path") or "")
        if volume in seen_volumes:
            continue
        seen_volumes.add(volume)
        unique_disk_entries.append(entry)
    disk_status = "ok"
    for entry in unique_disk_entries:
        disk_status = _worst_status(disk_status, str(entry.get("status") or "ok"))
    disk_hint = next(
        (str(entry.get("hint")) for entry in unique_disk_entries if entry.get("hint")),
        None,
    )
    disk = _check(
        status=disk_status,
        paths=unique_disk_entries,
        warn_below_gb=DISK_WARN_FREE_GB,
        block_below_gb=DISK_BLOCK_FREE_GB,
        hint=disk_hint,
    )

    models_path = Path(models_dir)
    exists = models_path.exists()
    entry_count = 0
    if exists and models_path.is_dir():
        try:
            entry_count = sum(1 for _ in models_path.iterdir())
        except Exception:
            entry_count = 0
    if not exists:
        models_status: Status = "warn"
        models_hint = f"Models directory does not exist yet: {models_path}"
    elif entry_count <= 0:
        models_status = "warn"
        models_hint = (
            f"Models directory is empty ({models_path}). Install models from the Models page before rendering."
        )
    else:
        models_status = "ok"
        models_hint = None
    models = _check(
        status=models_status,
        models_dir=str(models_path),
        exists=exists,
        entry_count=entry_count,
        hint=models_hint,
    )

    checks = {
        "ffmpeg": ffmpeg,
        "runtime": runtime,
        "gpu": gpu,
        "disk": disk,
        "writable_paths": writable_paths,
        "models": models,
    }
    overall = "ok"
    for check in checks.values():
        overall = _worst_status(overall, str(check.get("status") or "ok"))

    return {
        "ok": overall != "blocked",
        "ready": overall == "ok",
        "summary": _summarize(overall),
        "status": overall,
        "schema_version": SCHEMA_VERSION,
        "checked_at": _utc_now(),
        "checks": checks,
    }
