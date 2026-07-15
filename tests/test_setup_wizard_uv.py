from __future__ import annotations

from pathlib import Path

import pytest

from edmg_studio_backend.services import setup_wizard
from edmg_studio_backend.uv_toolchain import ToolchainError


def test_setup_profile_requires_exact_public_name():
    assert setup_wizard.resolve_setup_accelerator_profile({"accelerator_profile": "cuda"}) == "cuda"

    with pytest.raises(ToolchainError, match="Choose exactly one of: cpu, directml, cuda"):
        setup_wizard.resolve_setup_accelerator_profile({"accelerator_profile": "nvidia"})


def test_setup_profile_preserves_validated_legacy_payloads(monkeypatch):
    assert setup_wizard.resolve_setup_accelerator_profile(
        {"bundle": "studio_bundle", "flavor": "nvidia"}
    ) == "cuda"

    monkeypatch.setattr("edmg_studio_backend.uv_toolchain.platform.system", lambda: "Windows")
    assert setup_wizard.resolve_setup_accelerator_profile(
        {"bundle": "studio_bundle_directml", "flavor": "cpu"}
    ) == "directml"


def test_setup_profile_rejects_conflicting_new_and_legacy_fields():
    with pytest.raises(ToolchainError, match="Conflicting accelerator selections"):
        setup_wizard.resolve_setup_accelerator_profile(
            {
                "accelerator_profile": "cpu",
                "bundle": "studio_bundle",
                "flavor": "nvidia",
            }
        )


def test_setup_profile_rejects_unknown_legacy_bundle():
    with pytest.raises(ToolchainError, match="Unsupported legacy backend bundle"):
        setup_wizard.resolve_setup_accelerator_profile(
            {"bundle": "resolve-whatever-is-latest", "flavor": "cpu"}
        )


def test_source_backend_install_uses_one_frozen_profile(monkeypatch, tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    synced: list[str] = []

    monkeypatch.setattr(setup_wizard, "is_packaged_backend", lambda: False)
    monkeypatch.setattr(setup_wizard, "_backend_root", lambda: tmp_path)
    monkeypatch.setattr(setup_wizard, "sync_frozen_project", synced.append)
    monkeypatch.setattr(
        setup_wizard,
        "check_backend_bundle",
        lambda **kwargs: {
            "ok": True,
            "accelerator_profile": kwargs["accelerator_profile"],
            "sync_health": "ok",
        },
    )

    task = setup_wizard.SetupTask(id="sync", name="sync")
    setup_wizard.install_backend_bundle(task, accelerator_profile="cuda")

    assert synced == ["cuda"]
    assert task.progress == 1.0
    assert "synchronized and healthy" in task.last_log


def test_packaged_backend_install_is_a_noop_without_uv(monkeypatch):
    monkeypatch.setattr(setup_wizard, "is_packaged_backend", lambda: True)
    monkeypatch.setattr(
        setup_wizard,
        "sync_frozen_project",
        lambda _profile: pytest.fail("packaged setup must not invoke uv"),
    )
    monkeypatch.setattr(
        setup_wizard,
        "check_backend_bundle",
        lambda **_kwargs: {"ok": True, "immutable": True, "accelerator_profile": "cpu"},
    )

    task = setup_wizard.SetupTask(id="packaged", name="packaged")
    setup_wizard.install_backend_bundle(task, accelerator_profile="cpu")

    assert task.progress == 1.0
    assert "self-contained" in task.last_log


def test_backend_bundle_status_is_a_legacy_alias_for_toolchain_status(monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake_status(*, profile: str, check_sync: bool):
        calls.append((profile, check_sync))
        return {
            "ok": True,
            "packaged": False,
            "immutable": False,
            "accelerator_profile": profile,
            "sync_health": "ok",
        }

    monkeypatch.setattr(setup_wizard, "toolchain_status", fake_status)

    status = setup_wizard.check_backend_bundle(accelerator_profile="cuda")

    assert calls == [("cuda", True)]
    assert status["bundle"] == "locked-project"
    assert status["profile"] == "cuda"
    assert status["missing"] == []


def test_default_packaged_status_uses_manifest_profile_not_source_default(monkeypatch):
    calls: list[tuple[str | None, bool]] = []

    monkeypatch.setattr(setup_wizard, "is_packaged_backend", lambda: True)

    def fake_status(*, profile: str | None, check_sync: bool):
        calls.append((profile, check_sync))
        return {
            "ok": True,
            "packaged": True,
            "immutable": True,
            "accelerator_profile": "cuda",
            "sync_health": "bundled",
        }

    monkeypatch.setattr(setup_wizard, "toolchain_status", fake_status)

    status = setup_wizard.check_backend_bundle()

    assert calls == [(None, True)]
    assert status["ok"] is True
    assert status["profile"] == "cuda"
