from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def preflight(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "studio/edmg-studio/scripts/linux_backend_preflight.py"
    spec = importlib.util.spec_from_file_location("linux_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.sys, "version_info", (3, 12))
    monkeypatch.setattr(module.sys, "argv", [str(path)])
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    return module


def test_auto_without_gpu_does_not_fall_back_to_cpu(preflight, monkeypatch, capsys):
    policy = preflight.runpy.run_path(str(Path(__file__).resolve().parents[1] /
        "studio/edmg-studio/python_backend/edmg_studio_backend/uv_toolchain.py"))
    resolver = policy["resolve_accelerator_profile"]
    monkeypatch.setitem(resolver.__globals__, "installed_accelerator_profile", lambda: None)
    monkeypatch.setitem(resolver.__globals__, "detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(preflight.runpy, "run_path", lambda _: policy)
    assert preflight.main() == 1
    assert "CPU fallback is disabled" in capsys.readouterr().err


def test_installed_cuda_is_preserved_without_visible_gpu(preflight, monkeypatch, capsys):
    policy = preflight.runpy.run_path(str(Path(__file__).resolve().parents[1] /
        "studio/edmg-studio/python_backend/edmg_studio_backend/uv_toolchain.py"))
    monkeypatch.setitem(policy["resolve_accelerator_profile"].__globals__, "installed_accelerator_profile", lambda: "cuda")
    monkeypatch.setattr(preflight.runpy, "run_path", lambda _: policy)
    assert preflight.main() == 0
    assert capsys.readouterr().out == "cuda\n"


def test_active_environment_is_inspected(preflight, monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.sys, "argv", ["preflight", "--env-mode", "active"])
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))
    def resolve(_):
        assert preflight.os.environ["UV_PROJECT_ENVIRONMENT"] == str(tmp_path)
        return "cuda"
    monkeypatch.setattr(preflight.runpy, "run_path", lambda _: {"resolve_accelerator_profile": resolve})
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "previous")
    assert preflight.main() == 0


def test_missing_media_tool_blocks_startup(preflight, monkeypatch, capsys):
    monkeypatch.setattr(preflight.runpy, "run_path", lambda _: {"resolve_accelerator_profile": lambda _: "cpu"})
    def missing(*args, **kwargs):
        raise FileNotFoundError("ffmpeg is unavailable")
    monkeypatch.setattr(preflight.subprocess, "run", missing)
    assert preflight.main() == 1
    assert "ffmpeg is unavailable" in capsys.readouterr().err
