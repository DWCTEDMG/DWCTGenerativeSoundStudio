from __future__ import annotations

import importlib.util
import platform
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


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("cuda", "cuda"),
        (" NVIDIA ", "cuda"),
        ("cpu", "cpu"),
        ("directml", "directml"),
        ("amd", "directml"),
        (None, "cpu"),
    ],
)
def test_main_preserves_selected_profile_and_optional_runtime_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requested: str | None, expected: str
) -> None:
    module = _load_module()
    # Canonical DirectML validation is Windows-only; this contract test is portable.
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    if requested is None:
        monkeypatch.delenv("EDMG_BACKEND_ACCELERATOR_PROFILE", raising=False)
    else:
        monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", requested)
    monkeypatch.setenv("EDMG_PYTEST_TEMP_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_resolve_uv", lambda: "uv")
    calls = []

    def capture_step(label, cwd, args, *, env):
        calls.append((args, env.copy()))
        return 0

    monkeypatch.setattr(module, "run_step", capture_step)

    assert module.main() == 0
    assert len(calls) == 4  # lock check, sync, repository tests, backend tests
    assert all(env["EDMG_BACKEND_ACCELERATOR_PROFILE"] == expected for _, env in calls)
    assert "--inexact" in calls[1][0]
    for args, _ in calls[1:]:
        extras = [args[index + 1] for index, arg in enumerate(args) if arg == "--extra"]
        assert extras == [expected, "core", "audio"]
        assert "--frozen" in args
    assert all("--no-sync" in args for args, _ in calls[2:])
    assert calls[0][1].get("EDMG_STUDIO_HOME") != calls[2][1]["EDMG_STUDIO_HOME"]
    assert calls[2][1]["EDMG_STUDIO_HOME"] == calls[3][1]["EDMG_STUDIO_HOME"]


@pytest.mark.parametrize("requested", ["nightly", "gpu", "cuda,cpu", "", " "])
def test_invalid_profile_fails_before_commands_or_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requested: str
) -> None:
    module = _load_module()
    test_root = tmp_path / "must-not-exist"
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", requested)
    monkeypatch.setenv("EDMG_PYTEST_TEMP_ROOT", str(test_root))

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid profile reached a toolchain command")

    monkeypatch.setattr(module, "_resolve_uv", forbidden)
    monkeypatch.setattr(module, "run_step", forbidden)
    with pytest.raises(RuntimeError, match="Unsupported accelerator profile"):
        module.main()
    assert not test_root.exists()


@pytest.mark.parametrize("failure_step", ["validate uv lock", "sync frozen test environment"])
def test_failed_cuda_preparation_never_retries_as_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_step: str
) -> None:
    module = _load_module()
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cuda")
    monkeypatch.setenv("EDMG_PYTEST_TEMP_ROOT", str(tmp_path / "unused"))
    monkeypatch.setattr(module, "_resolve_uv", lambda: "uv")
    calls = []

    def fail_step(label, cwd, args, *, env):
        calls.append(args)
        assert env["EDMG_BACKEND_ACCELERATOR_PROFILE"] == "cuda"
        return 12 if label == failure_step else 0

    monkeypatch.setattr(module, "run_step", fail_step)
    assert module.main() == 12
    assert len(calls) == (1 if failure_step == "validate uv lock" else 2)
    assert all("cpu" not in args for args in calls)
    assert not (tmp_path / "unused").exists()
