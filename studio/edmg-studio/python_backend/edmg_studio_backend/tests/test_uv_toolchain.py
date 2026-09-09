from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from edmg_studio_backend import uv_toolchain


def _extras(args: list[str]) -> list[str]:
    return [args[index + 1] for index, value in enumerate(args) if value == "--extra"]


@pytest.mark.parametrize("profile", ["cpu", "directml", "cuda"])
def test_frozen_project_args_select_exactly_one_accelerator(profile, monkeypatch):
    if profile == "directml":
        monkeypatch.setattr(uv_toolchain.platform, "system", lambda: "Windows")

    args = uv_toolchain.frozen_project_args("sync", profile)

    assert args[:3] == ["sync", "--frozen", "--no-default-groups"]
    selected = _extras(args)
    assert selected == [profile, *uv_toolchain.RUNTIME_CAPABILITY_EXTRAS]
    assert len(set(selected) & set(uv_toolchain.ACCELERATOR_PROFILES)) == 1


def test_legacy_profile_inputs_are_validated_and_conflicts_are_rejected(monkeypatch):
    monkeypatch.setattr(uv_toolchain.platform, "system", lambda: "Windows")

    assert (
        uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle", flavor="nvidia") == "cuda"
    )
    assert (
        uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle_directml", flavor="cpu")
        == "directml"
    )
    with pytest.raises(uv_toolchain.ToolchainError, match="Conflicting backend selections"):
        uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle_directml", flavor="cuda")
    with pytest.raises(uv_toolchain.ToolchainError, match="Unsupported legacy backend bundle"):
        uv_toolchain.profile_from_legacy_inputs(bundle="download-latest", flavor="cpu")


def test_packaged_backend_cannot_sync_or_resolve_source_dependencies(monkeypatch):
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: True)

    with pytest.raises(uv_toolchain.ToolchainError, match="self-contained"):
        uv_toolchain.sync_frozen_project("cpu")


def test_sync_frozen_project_can_force_a_reinstall(monkeypatch):
    commands: list[list[object]] = []
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: False)
    monkeypatch.setattr(uv_toolchain, "resolve_uv", lambda **_kwargs: Path("uv"))
    monkeypatch.setattr(uv_toolchain, "toolchain_environment", lambda **_kwargs: {})
    monkeypatch.setattr(uv_toolchain, "backend_root", lambda: Path("backend"))
    monkeypatch.setattr(
        uv_toolchain,
        "run_checked",
        lambda args, **_kwargs: commands.append(list(args)),
    )

    uv_toolchain.sync_frozen_project("cuda", reinstall=True)

    assert commands[0] == [Path("uv"), "lock", "--check"]
    assert commands[1][-1] == "--reinstall"
    assert "--inexact" not in commands[1]


def test_packaged_status_uses_build_manifest_without_requiring_uv(monkeypatch):
    manifest = {
        "pythonVersion": "3.12.10",
        "uvVersion": "0.11.28",
        "lockSha256": "a" * 64,
        "acceleratorProfile": "cuda",
        "capabilityExtras": ["core", "audio"],
        "torchPackages": [{"name": "torch", "version": "2.11.0+cu130"}],
        "torchIndex": uv_toolchain.TORCH_INDEXES["cuda"],
        "pyinstallerVersion": "6.17.0",
    }
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: True)
    monkeypatch.setattr(uv_toolchain, "_packaged_manifest", lambda: manifest)
    monkeypatch.setattr(
        uv_toolchain,
        "resolve_uv",
        lambda **_kwargs: pytest.fail("packaged status must not resolve uv"),
    )

    status = uv_toolchain.toolchain_status()

    assert status["ok"] is True
    assert status["immutable"] is True
    assert status["sync_health"] == "bundled"
    assert status["accelerator_profile"] == "cuda"
    assert status["python_version"] == "3.12.10"


def test_source_status_does_not_expose_toolchain_exception(monkeypatch):
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: False)
    monkeypatch.setattr(
        uv_toolchain,
        "resolve_uv",
        lambda **_kwargs: (_ for _ in ()).throw(
            uv_toolchain.ToolchainError("secret command diagnostics")
        ),
    )

    status = uv_toolchain.toolchain_status(profile="cpu")

    assert status["ok"] is False
    assert status["error"] == "Backend toolchain validation failed"
    assert "secret command diagnostics" not in status["error"]


@pytest.mark.parametrize("failure", [None, "lock", "sync"])
def test_source_readiness_allows_optional_packages_but_requires_locked_runtime(monkeypatch, failure):
    commands: list[list[object]] = []
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: False)
    monkeypatch.setattr(uv_toolchain, "resolve_uv", lambda **_kwargs: Path("uv"))
    monkeypatch.setattr(uv_toolchain, "uv_version", lambda _path: uv_toolchain.UV_REQUIRED_VERSION)
    monkeypatch.setattr(uv_toolchain, "lock_sha256", lambda: "a" * 64)
    monkeypatch.setattr(uv_toolchain.sys, "version_info", (3, 12, 10))
    monkeypatch.setattr(uv_toolchain, "_installed_version", lambda _name: "installed")

    def run_check(args, **kwargs):
        command = list(args)
        commands.append(command)
        assert kwargs["env"]["EDMG_BACKEND_ACCELERATOR_PROFILE"] == "cuda"
        assert kwargs["capture_output"] is True
        assert "--check" in command
        if command[1] == "sync":
            # Simulate an environment that also contains optional development
            # packages: exact sync would remove them and fail its check.
            if "--inexact" not in command:
                raise uv_toolchain.ToolchainError("Optional packages would be removed")
            assert "--frozen" in command
            assert _extras(command) == ["cuda", *uv_toolchain.RUNTIME_CAPABILITY_EXTRAS]
        if command[1] == failure:
            raise uv_toolchain.ToolchainError("Lock or required runtime is out of date")

    monkeypatch.setattr(uv_toolchain, "run_checked", run_check)

    status = uv_toolchain.toolchain_status(profile="cuda")

    assert status["ok"] is (failure is None)
    assert status["accelerator_profile"] == "cuda"
    assert status["lock_check"] == ("failed" if failure == "lock" else "ok")
    assert status["sync_health"] == ("ok" if failure is None else "failed")
    assert len(commands) == (1 if failure == "lock" else 2)
    assert commands[0] == [Path("uv"), "lock", "--check"]


def test_uv_archive_extraction_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "uv.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../uv.exe", b"unsafe")

    with pytest.raises(uv_toolchain.ToolchainError, match="unsafe path"):
        uv_toolchain._extract_uv_archive(archive_path, tmp_path / "extract")
