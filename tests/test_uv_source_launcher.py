from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_launcher():
    path = (
        Path(__file__).resolve().parents[1]
        / "studio"
        / "edmg-studio"
        / "tools"
        / "run_uv_launcher.py"
    )
    spec = importlib.util.spec_from_file_location("run_uv_launcher_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_selection_prefers_explicit_closed_profile(monkeypatch):
    launcher = _load_launcher()
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cuda")
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: None)

    assert launcher.select_profile() == "cuda"

    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "nightly")
    with pytest.raises(launcher.ToolchainError, match="Choose exactly one"):
        launcher.select_profile()


def test_profile_selection_is_deterministic_for_detected_platform(monkeypatch):
    launcher = _load_launcher()
    monkeypatch.delenv("EDMG_BACKEND_ACCELERATOR_PROFILE", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "nvidia-smi" if name == "nvidia-smi" else None)
    assert launcher.select_profile() == "cuda"

    monkeypatch.setattr(launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    assert launcher.select_profile() == "directml"
    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    assert launcher.select_profile() == "cpu"


def test_main_syncs_then_runs_the_same_frozen_profile(monkeypatch):
    launcher = _load_launcher()
    calls = {}
    uv_path = Path("uv")

    monkeypatch.setattr(launcher, "select_profile", lambda: "cpu")

    def fake_sync(profile, *, install_uv):
        calls["sync"] = (profile, install_uv)
        return uv_path

    def fake_run(profile, command, *, install_uv):
        calls["run"] = (profile, command, install_uv)
        return ["uv", "run", "--frozen", "launcher_gui.py"], {"PROFILE": profile}

    def fake_subprocess_run(command, *, cwd, env, check):
        calls["subprocess"] = (command, cwd, env, check)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher, "sync_frozen_project", fake_sync)
    monkeypatch.setattr(launcher, "frozen_run_command", fake_run)
    monkeypatch.setattr(launcher.subprocess, "run", fake_subprocess_run)

    assert launcher.main() == 0
    assert calls["sync"] == ("cpu", True)
    assert calls["run"][0] == "cpu"
    assert calls["run"][2] is False
    assert calls["subprocess"][2]["EDMG_UV_BIN"] == str(uv_path)
