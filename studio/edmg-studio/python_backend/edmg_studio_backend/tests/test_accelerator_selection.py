from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from edmg_studio_backend import uv_toolchain as toolchain
from edmg_studio_backend.api.setup import create_setup_router
from edmg_studio_backend.services import internal_video, setup_wizard


@pytest.fixture
def no_gpu(monkeypatch):
    monkeypatch.delenv("EDMG_BACKEND_ACCELERATOR_PROFILE", raising=False)
    monkeypatch.setattr(toolchain, "installed_accelerator_profile", lambda: None)
    monkeypatch.setattr(toolchain, "detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Linux")


def test_auto_never_chooses_cpu_or_changes_dependencies(no_gpu):
    with pytest.raises(toolchain.ToolchainError, match="CPU fallback is disabled"):
        toolchain.active_accelerator_profile()
    status = toolchain.toolchain_status(check_sync=False)
    assert status["accelerator_profile"] == "unavailable"
    assert status["ok"] is False
    assert toolchain.resolve_accelerator_profile("cpu") == "cpu"


def test_gpu_selection_and_environment_precedence(no_gpu, monkeypatch):
    monkeypatch.setattr(toolchain, "detect_nvidia_gpu", lambda: True)
    assert toolchain.resolve_accelerator_profile("auto") == "cuda"
    assert setup_wizard.resolve_setup_accelerator_profile({}) == "cuda"
    assert setup_wizard.resolve_setup_accelerator_profile({"accelerator_profile": "auto"}) == "cuda"
    monkeypatch.setenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cpu")
    assert toolchain.active_accelerator_profile() == "cpu"
    # A new explicit automatic selection supersedes a previous CPU choice.
    assert toolchain.resolve_accelerator_profile("auto") == "cuda"


def test_cuda_installation_survives_missing_driver(no_gpu, monkeypatch):
    monkeypatch.setattr(toolchain, "installed_accelerator_profile", lambda: "cuda")
    assert toolchain.resolve_accelerator_profile() == "cuda"


def test_windows_gpu_lane_is_directml_without_cuda(no_gpu, monkeypatch):
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Windows")
    assert toolchain.resolve_accelerator_profile() == "directml"
    monkeypatch.setattr(toolchain, "detect_nvidia_gpu", lambda: True)
    assert toolchain.resolve_accelerator_profile() == "cuda"


def test_profile_inspects_selected_environment_not_running_python(tmp_path, monkeypatch):
    site = tmp_path / "Lib" / "site-packages" / "torch-2.11.0.dist-info"
    site.mkdir(parents=True)
    (site / "METADATA").write_text("Metadata-Version: 2.1\nName: torch\nVersion: 2.11.0+cu130\n")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path))
    assert toolchain.installed_accelerator_profile() == "cuda"


@pytest.mark.parametrize("output,code,expected", [("GPU 0: NVIDIA A6000", 0, True), ("no devices", 0, False), ("GPU 0: NVIDIA", 1, False)])
def test_nvidia_probe_requires_successful_device_output(monkeypatch, output, code, expected):
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=code, stdout=output))
    assert toolchain.detect_nvidia_gpu() is expected


def test_probe_timeout_is_not_cpu_selection(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 5)
    monkeypatch.setattr(toolchain.subprocess, "run", timeout)
    assert toolchain.detect_nvidia_gpu() is False


@pytest.mark.parametrize("cuda,mps,dml,expected", [(True, True, True, "cuda"), (False, True, True, "mps"), (False, False, True, "directml")])
def test_render_auto_prefers_supported_gpu(monkeypatch, cuda, mps, dml, expected):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps))))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(get_available_providers=lambda: ["DmlExecutionProvider"] if dml else []))
    assert internal_video._device_auto("auto") == expected


def test_render_does_not_silently_fall_back_from_requested_gpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(get_available_providers=lambda: []))
    for device in ("auto", "cuda", "mps", "directml"):
        with pytest.raises(RuntimeError, match="fallback"):
            internal_video._device_auto(device)
    assert internal_video._device_auto("cpu") == "cpu"


@pytest.mark.parametrize("profile", ["cuda", "directml"])
def test_comfy_routes_resolve_automatic_profile_before_starting_tasks(profile, tmp_path):
    calls = []
    def start(name, action, *args, **kwargs):
        calls.append((name, args))
        return SimpleNamespace(to_dict=lambda: {"name": name})
    deps = SimpleNamespace(
        settings=SimpleNamespace(external_dir=tmp_path, data_dir=tmp_path, models_dir=tmp_path),
        tasks=SimpleNamespace(start=start), resolve_profile=lambda payload: profile,
        install_comfy=lambda: None, start_comfy=lambda: None,
    )
    router = create_setup_router(deps)
    for suffix in ("install", "start"):
        endpoint = next(route.endpoint for route in router.routes if route.path == f"/v1/setup/comfyui/portable/{suffix}")
        if profile == "cuda":
            endpoint({})
            assert calls[-1][1][1] == "nvidia"
        else:
            count = len(calls)
            with pytest.raises(HTTPException, match="no CPU fallback"):
                endpoint({})
            assert len(calls) == count
        endpoint({"flavor": "cpu"})
        assert calls[-1][1][1] == "cpu"
