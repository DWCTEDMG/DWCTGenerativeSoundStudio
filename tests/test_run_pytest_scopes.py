from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_pytest_scopes.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_pytest_scopes_test_module", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_uv_prefers_active_uv_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    seen: list[str] = []

    def fake_run(command: list[str], capture_output: bool, text: bool, check: bool):
        seen.append(command[0])

        class Completed:
            returncode = 0
            stdout = f"uv {module.UV_VERSION} (x86_64-unknown-linux-gnu)\n"

        return Completed()

    monkeypatch.setenv("EDMG_UV_BIN", "")
    monkeypatch.setenv("UV", "/tmp/pinned-uv")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/local/bin/uv")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._resolve_uv() == "/tmp/pinned-uv"
    assert seen == ["/tmp/pinned-uv"]


def test_resolve_uv_rejects_wrong_version_even_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_run(command: list[str], capture_output: bool, text: bool, check: bool):
        class Completed:
            returncode = 0
            stdout = "uv 0.10.12 (x86_64-unknown-linux-gnu)\n"

        return Completed()

    monkeypatch.setenv("EDMG_UV_BIN", "/tmp/pinned-uv")
    monkeypatch.setenv("UV", "")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"Expected uv 0\.11\.28"):
        module._resolve_uv()


@pytest.mark.parametrize("profile", ["cpu", "cuda", "directml"])
@pytest.mark.parametrize("explicit", [False, True])
def test_selected_profile_is_preserved_in_sync_and_both_test_scopes(monkeypatch, tmp_path, profile, explicit):
    module = _load_module()
    calls = []
    monkeypatch.setattr(module, "_resolve_uv", lambda: "uv")
    monkeypatch.setenv("EDMG_PYTEST_TEMP_ROOT", str(tmp_path))
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cpu" if explicit else profile)

    def record(label, cwd, args, *, env):
        calls.append((label, args, env))
        return 0

    monkeypatch.setattr(module, "run_step", record)
    assert module.main(["--accelerator-profile", profile] if explicit else []) == 0
    assert len(calls) == 4
    for _, command, env in calls[1:]:
        extras = [command[i + 1] for i, arg in enumerate(command) if arg == "--extra"]
        assert set(extras) == {profile, "core", "audio"}
        assert env["EDMG_BACKEND_ACCELERATOR_PROFILE"] == profile
    assert "--inexact" in calls[1][1]  # Preserve installed ASR/model packages.


def test_invalid_profile_fails_before_sync(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "typo")
    monkeypatch.setattr(module, "_resolve_uv", lambda: pytest.fail("Must reject before running tools"))
    with pytest.raises(SystemExit) as error:
        module.main([])
    assert error.value.code == 2
