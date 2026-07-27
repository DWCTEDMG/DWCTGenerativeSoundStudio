from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.services.system_readiness import (
    DISK_BLOCK_FREE_GB,
    assess_system_readiness,
)


def _ready_ffmpeg(_path: str) -> dict:
    return {"ok": True, "path": "ffmpeg", "version": "ffmpeg version 7.0"}


def _ready_runtime() -> dict:
    return {
        "ok": True,
        "python_version": "3.12.0",
        "uv_version": "0.11.28",
        "accelerator_profile": "cpu",
        "lock_check": "ok",
        "sync_health": "synchronized",
    }


def _cpu_hardware() -> dict:
    return {
        "backend": "cpu",
        "device": "cpu",
        "device_name": "CPU",
        "available_backends": ["cpu"],
        "vram_gb": 0.0,
        "ram_gb": 16.0,
    }


def test_system_readiness_reports_ready_when_dependencies_and_paths_are_healthy(tmp_path: Path):
    data = tmp_path / "data"
    models = tmp_path / "models"
    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    for path in (data, models, cache, logs):
        path.mkdir(parents=True, exist_ok=True)
    (models / "demo.bin").write_bytes(b"x")

    class Usage:
        total = 100 * 1024**3
        free = 20 * 1024**3

    from edmg_studio_backend.services import system_readiness

    original_disk_usage = system_readiness.shutil.disk_usage
    system_readiness.shutil.disk_usage = lambda _path: Usage()
    try:
        report = assess_system_readiness(
            ffmpeg_path="ffmpeg",
            data_dir=data,
            models_dir=models,
            cache_dir=cache,
            logs_dir=logs,
            check_ffmpeg=_ready_ffmpeg,
            check_runtime=_ready_runtime,
            hardware_profile=lambda: {
                "backend": "cuda",
                "device": "cuda",
                "device_name": "Test GPU",
                "available_backends": ["cpu", "cuda"],
                "vram_gb": 12.0,
                "ram_gb": 32.0,
            },
        )
    finally:
        system_readiness.shutil.disk_usage = original_disk_usage

    assert report["schema_version"] == 1
    assert report["ok"] is True
    assert report["ready"] is True
    assert report["summary"] == "Ready"
    assert report["checks"]["ffmpeg"]["status"] == "ok"
    assert report["checks"]["runtime"]["accelerator_profile"] == "cpu"
    assert report["checks"]["gpu"]["device_name"] == "Test GPU"
    assert report["checks"]["writable_paths"]["ok"] is True
    assert report["checks"]["models"]["entry_count"] == 1


def test_system_readiness_blocks_on_missing_ffmpeg_and_warns_without_gpu(tmp_path: Path):
    data = tmp_path / "data"
    models = tmp_path / "models"
    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    for path in (data, models, cache, logs):
        path.mkdir(parents=True, exist_ok=True)

    report = assess_system_readiness(
        ffmpeg_path="missing-ffmpeg",
        data_dir=data,
        models_dir=models,
        cache_dir=cache,
        logs_dir=logs,
        check_ffmpeg=lambda _path: {
            "ok": False,
            "path": "missing-ffmpeg",
            "hint": "Install FFmpeg",
        },
        check_runtime=_ready_runtime,
        hardware_profile=_cpu_hardware,
    )

    assert report["ok"] is False
    assert report["ready"] is False
    assert report["summary"] == "Blocked"
    assert report["checks"]["ffmpeg"]["status"] == "blocked"
    assert report["checks"]["gpu"]["status"] == "warn"
    assert report["checks"]["models"]["status"] == "warn"
    assert "Install FFmpeg" in report["checks"]["ffmpeg"]["hint"]


def test_system_readiness_blocks_unwritable_paths(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    models = tmp_path / "models"
    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    for path in (data, models, cache, logs):
        path.mkdir(parents=True, exist_ok=True)

    real_write_text = Path.write_text

    def deny_write(self: Path, *args, **kwargs):
        if self.parent == data:
            raise PermissionError("denied")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", deny_write)

    report = assess_system_readiness(
        ffmpeg_path="ffmpeg",
        data_dir=data,
        models_dir=models,
        cache_dir=cache,
        logs_dir=logs,
        check_ffmpeg=_ready_ffmpeg,
        check_runtime=_ready_runtime,
        hardware_profile=_cpu_hardware,
    )

    assert report["ok"] is False
    assert report["checks"]["writable_paths"]["status"] == "blocked"
    assert any(
        item["label"] == "data" and item["writable"] is False
        for item in report["checks"]["writable_paths"]["paths"]
    )
    failed_path = next(
        item for item in report["checks"]["writable_paths"]["paths"]
        if item["label"] == "data"
    )
    assert failed_path["error"] == "Path is not writable"
    assert "denied" not in failed_path["error"]


def test_system_readiness_marks_low_disk_as_blocked(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    models = tmp_path / "models"
    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    for path in (data, models, cache, logs):
        path.mkdir(parents=True, exist_ok=True)

    class Usage:
        total = 100 * 1024**3
        free = int((DISK_BLOCK_FREE_GB / 2) * 1024**3)

    monkeypatch.setattr(
        "edmg_studio_backend.services.system_readiness.shutil.disk_usage",
        lambda _path: Usage(),
    )

    report = assess_system_readiness(
        ffmpeg_path="ffmpeg",
        data_dir=data,
        models_dir=models,
        cache_dir=cache,
        logs_dir=logs,
        check_ffmpeg=_ready_ffmpeg,
        check_runtime=_ready_runtime,
        hardware_profile=_cpu_hardware,
    )

    assert report["ok"] is False
    assert report["checks"]["disk"]["status"] == "blocked"
