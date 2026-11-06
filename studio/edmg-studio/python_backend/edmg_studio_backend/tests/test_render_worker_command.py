from __future__ import annotations

from edmg_studio_backend import app as backend_app


def test_render_worker_command_uses_python_module_in_source_mode(monkeypatch) -> None:
    monkeypatch.setattr(backend_app.sys, "executable", r"C:\Python312\python.exe")
    monkeypatch.delattr(backend_app.sys, "frozen", raising=False)

    assert backend_app._render_worker_command("project-123", "job-456") == [
        r"C:\Python312\python.exe",
        "-m",
        "edmg_studio_backend",
        "run-job",
        "--project",
        "project-123",
        "--job",
        "job-456",
    ]


def test_render_worker_command_calls_frozen_backend_cli_directly(monkeypatch) -> None:
    monkeypatch.setattr(backend_app.sys, "executable", r"C:\EDMG Studio\edmg-studio-backend.exe")
    monkeypatch.setattr(backend_app.sys, "frozen", True, raising=False)

    assert backend_app._render_worker_command("project-123", "job-456") == [
        r"C:\EDMG Studio\edmg-studio-backend.exe",
        "run-job",
        "--project",
        "project-123",
        "--job",
        "job-456",
    ]


def test_render_worker_command_carries_the_claimed_attempt():
    assert backend_app._render_worker_command("project", "job", attempt=3)[-2:] == ["--attempt", "3"]


def test_nemotron_worker_can_use_an_isolated_dependency_overlay(monkeypatch) -> None:
    monkeypatch.delattr(backend_app.sys, "frozen", raising=False)
    monkeypatch.setattr(backend_app.shutil, "which", lambda name: "/opt/uv" if name == "uv" else None)

    command = backend_app._render_worker_command(
        "project-123",
        "job-456",
        dependency_overlays=("transformers==5.6.0",),
    )

    assert command[:9] == [
        "/opt/uv",
        "run",
        "--project",
        str(backend_app.Path(backend_app.__file__).resolve().parents[1]),
        "--frozen",
        "--no-sync",
        "--with",
        "transformers==5.6.0",
        "python",
    ]
    assert command[-6:] == [
        "edmg_studio_backend",
        "run-job",
        "--project",
        "project-123",
        "--job",
        "job-456",
    ]


def test_dependency_overlay_finds_standard_per_user_uv(monkeypatch, tmp_path) -> None:
    uv = tmp_path / ".local" / "bin" / ("uv.exe" if backend_app.os.name == "nt" else "uv")
    uv.parent.mkdir(parents=True)
    uv.touch()
    monkeypatch.delattr(backend_app.sys, "frozen", raising=False)
    monkeypatch.delenv("EDMG_UV_BIN", raising=False)
    monkeypatch.setattr(backend_app.shutil, "which", lambda _name: None)
    monkeypatch.setattr(backend_app.Path, "home", lambda: tmp_path)

    command = backend_app._render_worker_command(
        "project", "job", dependency_overlays=("transformers==5.6.0",),
    )

    assert command[0] == str(uv)
