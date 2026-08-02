from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "edmg_installer.py"
INSTALLER_GUI_PATH = REPO_ROOT / "installer_gui.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "edmg_installer_test_module", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_installer_gui_module():
    spec = importlib.util.spec_from_file_location(
        "installer_gui_test_module", INSTALLER_GUI_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_hugging_face_cache_env(cache_root: Path) -> dict[str, str]:
    huggingface = cache_root / "huggingface"
    return {
        "HF_HOME": str(huggingface),
        "HF_HUB_CACHE": str(huggingface / "hub"),
        "HF_XET_CACHE": str(huggingface / "xet"),
        "HF_ASSETS_CACHE": str(huggingface / "assets"),
        "HUGGINGFACE_HUB_CACHE": str(huggingface / "hub"),
        "HUGGINGFACE_ASSETS_CACHE": str(huggingface / "assets"),
        "TRANSFORMERS_CACHE": str(cache_root / "transformers"),
    }


@pytest.mark.parametrize(
    ("windows_style", "expected_python_suffix"),
    [
        (False, "bin/python"),
        (True, "Scripts/python.exe"),
    ],
)
def test_install_uses_pinned_uv_for_venv_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    windows_style: bool,
    expected_python_suffix: str,
) -> None:
    module = _load_module()
    uv_bin = tmp_path / "toolchain" / "uv"
    venv_dir = tmp_path / "standalone-env"
    requirements = tmp_path / "requirements-minimal.txt"
    requirements.write_text("requests>=2\n", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(module, "_is_windows", lambda: windows_style)
    monkeypatch.setattr(module, "_resolve_uv", lambda env=None: uv_bin)
    monkeypatch.setattr(module, "_select_requirements", lambda _mode: requirements)
    monkeypatch.setattr(module, "_post_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "_run",
        lambda cmd, *, cwd=None, env=None: commands.append(list(cmd)) or 0,
    )

    rc = module.install(
        mode="minimal",
        backend="cpu",
        venv=str(venv_dir),
        cache_root=str(tmp_path / "cache"),
        skip_torch=True,
        skip_corpora=True,
        skip_models=True,
        skip_whisper=True,
    )

    assert rc == 0
    assert commands[0] == [
        str(uv_bin),
        "venv",
        "--python",
        "3.12",
        "--seed",
        str(venv_dir),
    ]
    installed_python = commands[1][4].replace("\\", "/")
    assert installed_python.endswith(expected_python_suffix)
    assert commands[1] == [
        str(uv_bin),
        "pip",
        "install",
        "--python",
        str(module._venv_python(venv_dir)),
        "-r",
        str(requirements),
    ]
    assert commands[2] == [
        str(uv_bin),
        "pip",
        "install",
        "--python",
        str(module._venv_python(venv_dir)),
        "-e",
        ".",
    ]


def test_install_uses_current_python_when_venv_is_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    uv_bin = tmp_path / "toolchain" / "uv"
    requirements = tmp_path / "requirements-standard.txt"
    requirements.write_text("requests>=2\n", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(module, "_resolve_uv", lambda env=None: uv_bin)
    monkeypatch.setattr(module, "_select_requirements", lambda _mode: requirements)
    monkeypatch.setattr(module, "_post_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "_run",
        lambda cmd, *, cwd=None, env=None: commands.append(list(cmd)) or 0,
    )

    rc = module.install(
        mode="standard",
        backend="cpu",
        venv=None,
        cache_root=None,
        skip_torch=True,
        skip_corpora=True,
        skip_models=True,
        skip_whisper=True,
    )

    assert rc == 0
    assert commands == [
        [
            str(uv_bin),
            "pip",
            "install",
            "--python",
            sys.executable,
            "-r",
            str(requirements),
        ],
        [
            str(uv_bin),
            "pip",
            "install",
            "--python",
            sys.executable,
            "-e",
            ".",
        ],
    ]


def test_managed_env_routes_uv_python_and_hugging_face_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    cache_root = tmp_path / "cache-root"
    expected_hugging_face = _expected_hugging_face_cache_env(cache_root)
    for key in expected_hugging_face:
        monkeypatch.setenv(key, rf"G:\stale-cache\{key}")

    env = module._managed_env(cache_root)

    assert env is not None
    assert env["UV_CACHE_DIR"] == str(cache_root / "uv")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(cache_root / "python")
    assert env["EDMG_UV_INSTALL_ROOT"] == str(cache_root / "toolchain" / "uv")
    for key, value in expected_hugging_face.items():
        assert env[key] == value


def test_legacy_gui_installer_overrides_inherited_hugging_face_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_installer_gui_module()
    cache_root = tmp_path / "installer-cache"
    expected = _expected_hugging_face_cache_env(cache_root)
    for key in expected:
        monkeypatch.setenv(key, rf"G:\stale-cache\{key}")

    env = module.build_managed_env(cache_root)

    for key, value in expected.items():
        assert env[key] == value
