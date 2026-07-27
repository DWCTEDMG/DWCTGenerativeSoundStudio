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
