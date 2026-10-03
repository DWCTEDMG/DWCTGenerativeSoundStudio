"""Regression checks for patched Hono, Accelerate, and Virtualenv boundaries.

Virtualenv runtime checks require the optional dev dependency; run them in a
disposable environment with the exact version from the backend lockfile.
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import OrderedDict
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def test_virtualenv_lock_and_constraint_include_both_security_fixes():
    backend = ROOT / "studio/edmg-studio/python_backend"
    lock = tomllib.loads((backend / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "virtualenv"]
    assert versions and all(Version(v) >= Version("21.7.12") for v in versions)
    manifest = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    assert "virtualenv>=21.7.12,<22" in manifest["tool"]["uv"]["constraint-dependencies"]


def test_accelerate_manifest_and_lock_exclude_the_affected_range():
    backend = ROOT / "studio/edmg-studio/python_backend"
    lock = tomllib.loads((backend / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "accelerate"]
    assert versions and all(Version(v) >= Version("1.15.0") for v in versions)
    manifest = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    assert "accelerate>=1.15,<2" in manifest["project"]["optional-dependencies"]["internal-video"]


def test_director_hono_override_and_lock_include_boundary_escaping_fix():
    director = ROOT / "chatgpt-apps/edmg-director"
    manifest = json.loads((director / "package.json").read_text(encoding="utf-8"))
    assert Version(manifest["pnpm"]["overrides"]["hono"]) >= Version("4.13.7")
    lock = (director / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = re.findall(r"^  hono@([^:]+):", lock, re.MULTILINE)
    assert versions and all(Version(v) >= Version("4.13.7") for v in versions)


def test_virtualenv_runtime_matches_locked_candidate():
    pytest.importorskip("virtualenv")
    lock = tomllib.loads((ROOT / "studio/edmg-studio/python_backend/uv.lock").read_text(encoding="utf-8"))
    assert version("virtualenv") in [p["version"] for p in lock["package"] if p["name"] == "virtualenv"]


@pytest.mark.parametrize("boundary", ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_virtualenv_prompt_cannot_inject_configuration(tmp_path, boundary):
    cfg_module = pytest.importorskip("virtualenv.create.pyenv_cfg")
    cfg = cfg_module.PyEnvCfg(OrderedDict([
        ("home", "trusted-interpreter"),
        ("prompt", f'ordinary{boundary}home = attacker{boundary}prompt = forged'),
    ]), tmp_path / "pyvenv.cfg")
    cfg.write()
    assert cfg.refresh()["home"] == "trusted-interpreter"
    assert len(cfg.content) == 2
    cfg["prompt"] = "ordinary prompt"
    cfg.write()
    assert cfg.refresh()["prompt"] == "ordinary prompt"


@pytest.mark.parametrize("expected", ["0" * 64, None, "valid"])
def test_virtualenv_seed_digest_rejects_tampering_and_missing_metadata(tmp_path, monkeypatch, expected):
    periodic = pytest.importorskip("virtualenv.seed.wheels.periodic_update")
    wheel_type = pytest.importorskip("virtualenv.seed.wheels.util").Wheel
    path = tmp_path / "pip-26.0-py3-none-any.whl"
    path.write_bytes(b"harmless wheel fixture")
    wheel = wheel_type(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if expected == "valid" else expected
    monkeypatch.setattr(periodic, "_pypi_sha256_for_wheel", lambda _: digest)
    monkeypatch.setattr(periodic, "_DIGEST_RETRY_DELAYS", ())
    if expected == "valid":
        periodic.verify_wheel_digest(wheel)
    else:
        with pytest.raises(RuntimeError):
            periodic.verify_wheel_digest(wheel)


@pytest.mark.parametrize("expected", ["0" * 64, None, "valid"])
def test_virtualenv_download_admission_verifies_before_returning_wheel(tmp_path, monkeypatch, expected):
    acquire = pytest.importorskip("virtualenv.seed.wheels.acquire")
    periodic = pytest.importorskip("virtualenv.seed.wheels.periodic_update")
    wheel_type = pytest.importorskip("virtualenv.seed.wheels.util").Wheel
    path = tmp_path / "pip-26.0-py3-none-any.whl"
    path.write_bytes(b"harmless downloaded wheel fixture")
    wheel = wheel_type(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if expected == "valid" else expected
    monkeypatch.setattr(periodic, "_pypi_sha256_for_wheel", lambda _: digest)
    monkeypatch.setattr(periodic, "_DIGEST_RETRY_DELAYS", ())
    monkeypatch.setattr(acquire, "pip_wheel_env_run", lambda *_: {})
    monkeypatch.setattr(acquire, "Popen", lambda *a, **kw: SimpleNamespace(returncode=0, communicate=lambda: ("", "")))
    monkeypatch.setattr(acquire, "_find_downloaded_wheel", lambda *a: wheel)
    args = ("pip", "==26.0", "3.12", [], None, tmp_path, {})
    if expected == "valid":
        assert acquire.download_wheel(*args) is wheel
    else:
        with pytest.raises(RuntimeError):
            acquire.download_wheel(*args)
