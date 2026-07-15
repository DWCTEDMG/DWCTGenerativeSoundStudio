from __future__ import annotations

import zipfile

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

    assert uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle", flavor="nvidia") == "cuda"
    assert uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle_directml", flavor="cpu") == "directml"
    with pytest.raises(uv_toolchain.ToolchainError, match="Conflicting backend selections"):
        uv_toolchain.profile_from_legacy_inputs(bundle="studio_bundle_directml", flavor="cuda")
    with pytest.raises(uv_toolchain.ToolchainError, match="Unsupported legacy backend bundle"):
        uv_toolchain.profile_from_legacy_inputs(bundle="download-latest", flavor="cpu")


def test_packaged_backend_cannot_sync_or_resolve_source_dependencies(monkeypatch):
    monkeypatch.setattr(uv_toolchain, "is_packaged_backend", lambda: True)

    with pytest.raises(uv_toolchain.ToolchainError, match="self-contained"):
        uv_toolchain.sync_frozen_project("cpu")


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


def test_uv_archive_extraction_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "uv.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../uv.exe", b"unsafe")

    with pytest.raises(uv_toolchain.ToolchainError, match="unsafe path"):
        uv_toolchain._extract_uv_archive(archive_path, tmp_path / "extract")
