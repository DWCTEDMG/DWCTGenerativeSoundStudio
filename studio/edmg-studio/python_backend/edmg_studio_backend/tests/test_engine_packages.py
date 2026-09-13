from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api.routers import create_models_router
from edmg_studio_backend.domain.director_readiness import resolve_director_readiness
from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import engine_packages as packages
from edmg_studio_backend.services.model_catalog import built_in_catalog, built_in_packs
from edmg_studio_backend.services.model_manager import ModelTask, ModelTaskCancelled
from edmg_studio_backend.tests.test_model_manager_downloads import _manager

IDS = tuple(packages.MANIFESTS)


@pytest.fixture
def tiny_packages(monkeypatch):
    manifests = copy.deepcopy(packages.MANIFESTS)
    for manifest in manifests.values():
        for item in manifest["files"]:
            body = ("fixture:" + item["path"]).encode()
            item["size_bytes"] = len(body)
            item["sha256"] = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(packages, "MANIFESTS", manifests)
    return manifests


def materialize(root, manifest):
    for item in manifest["files"]:
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("fixture:" + item["path"]).encode())


def test_catalog_exact_recommended_formats_and_no_wildcards():
    catalog = {entry["id"]: entry for entry in built_in_catalog()}
    for model_id, manifest in packages.MANIFESTS.items():
        entry = catalog[model_id]
        assert entry["installable"] and not entry["discovery_only"]
        assert entry["hf_repo_id"] == manifest["repo_id"]
        assert len(entry["hf_revision"]) == 40
        assert entry["required_files"] == [item["path"] for item in packages.checked_files(manifest)]
    ltx = catalog["hf_ltx_25_distilled_internal"]["required_files"]
    assert len(ltx) == 6
    assert "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" in ltx
    assert "Q4_K_M.gguf" in catalog[packages.STANDARD_GGUF_ID]["required_files"][0]
    assert catalog["hf_qwen3_vl_8b_director"]["kind"] == "transformers"
    hunyuan = catalog["hf_hunyuan_video15_internal"]["required_files"]
    assert len(hunyuan) == 8
    assert not any("720p" in name or "1080p" in name for name in hunyuan)


@pytest.mark.parametrize("model_id", IDS)
def test_selective_install_validate_corruption_and_uninstall(tmp_path, monkeypatch, tiny_packages, model_id):
    manager = _manager(tmp_path, monkeypatch)
    entry = manager._find_entry(model_id)
    manifest = tiny_packages[model_id]
    _, dest = manager._models_dest(entry)
    calls = []
    def download(task, **kwargs):
        calls.append(kwargs)
        assert kwargs["allow_patterns"] == [item["path"] for item in manifest["files"]]
        assert kwargs["revision"] == manifest["revision"]
        materialize(Path(kwargs["local_dir"]), manifest)
    monkeypatch.setattr(manager, "_download_hf_snapshot", download)
    # Broad cache restore must never run for an exact package.
    monkeypatch.setattr(manager, "_restore_snapshot_from_model_cache", lambda *_: pytest.fail("broad cache restore"))
    task = ModelTask(id="test", name="install")
    manager._install_engine_package(task, entry)
    assert len(calls) == 1
    assert manager.installed_path(model_id) == dest
    receipt = json.loads((dest / "model.json").read_text())
    assert receipt["revision"] == manifest["revision"]
    status = manager.engine_package_status(model_id, {"backend": "cuda", "vram_gb": 80, "ram_gb": 128})
    assert status["installed"] and status["hardware_compatible"]
    assert not status["runtime_ready"] and status["blockers"]
    first = dest / manifest["files"][0]["path"]
    first.write_bytes(b"x" * first.stat().st_size)
    assert manager.installed_path(model_id) is None
    with pytest.raises(UserFacingError, match="validation failed"):
        manager._validate_engine_package(task, entry)
    assert not (dest / "model.json").exists()
    manager._install_engine_package(task, entry)
    assert manager.installed_path(model_id)
    sibling = dest.parent / "other-provider"
    sibling.mkdir()
    (sibling / "keep").write_text("keep")
    manager._uninstall_engine_package(task, entry)
    assert not dest.exists()
    assert (sibling / "keep").read_text() == "keep"
    assert manager.installed_path(model_id) is None
    manager._uninstall_engine_package(task, entry)  # idempotent


@pytest.mark.parametrize("model_id", IDS)
def test_partial_packages_never_report_installed(tmp_path, monkeypatch, tiny_packages, model_id):
    manager = _manager(tmp_path, monkeypatch)
    manifest = tiny_packages[model_id]
    entry = manager._find_entry(model_id)
    _, dest = manager._models_dest(entry)
    materialize(dest, manifest)
    assert manager.installed_path(model_id) is None  # no verified receipt
    manager._validate_engine_package(ModelTask(id="t", name="validate"), entry)
    (dest / manifest["files"][-1]["path"]).unlink()
    assert manager.installed_path(model_id) is None
    assert manager.engine_package_status(model_id)["validation_issues"]


def test_cancelled_validation_does_not_publish(tmp_path, monkeypatch, tiny_packages):
    manager = _manager(tmp_path, monkeypatch)
    entry = manager._find_entry(IDS[0])
    _, dest = manager._models_dest(entry)
    materialize(dest, tiny_packages[IDS[0]])
    task = ModelTask(id="t", name="validate", cancel_requested=True)
    with pytest.raises(ModelTaskCancelled):
        manager._validate_engine_package(task, entry)
    assert not (dest / "model.json").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "a\\b", "a/*", "a/../b"])
def test_manifest_rejects_nonliteral_or_escaping_paths(name):
    with pytest.raises(ValueError):
        packages.checked_files({"files": [{"path": name, "size_bytes": 1, "sha256": "a" * 64}]})


def test_corrupt_receipt_and_link_are_not_installed(tmp_path, tiny_packages):
    manifest = tiny_packages[IDS[0]]
    materialize(tmp_path, manifest)
    (tmp_path / "model.json").write_text("[]")
    assert not packages.validate_package(tmp_path, manifest)["valid"]


def test_cuda_hardware_targets_do_not_certify_runtime():
    model_id = "hf_ltx_25_distilled_internal"
    assert not packages.runtime_status(model_id, {"backend": "cuda", "vram_gb": 6, "ram_gb": 16})["hardware_compatible"]
    assert not packages.runtime_status(model_id, {"backend": "cpu", "vram_gb": 80, "ram_gb": 128})["hardware_compatible"]
    status = packages.runtime_status(model_id, {"backend": "cuda", "vram_gb": 48, "ram_gb": 128})
    assert status["hardware_compatible"] and not status["runtime_ready"]
    readiness = resolve_director_readiness({"backend": "cuda", "vram_gb": 48, "ram_gb": 128},
        engine="ltx_25", installed_models={model_id: True, packages.STANDARD_GGUF_ID: True})
    assert readiness.director.model_id == packages.STANDARD_GGUF_ID
    assert not readiness.ready and not readiness.director.adapter_ready


def test_package_routes_are_exposed_without_other_provider_mutation(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(manager.tasks, "start", lambda name, fn, entry: calls.append((name, entry["id"])) or ModelTask(id="t", name=name))
    app = FastAPI()
    app.include_router(create_models_router(get_models=lambda: manager))
    with TestClient(app) as client:
        for action in ("uninstall", "validate"):
            response = client.post(f"/v1/models/{action}", json={"model_id": IDS[0]})
            assert response.status_code == 200
    assert len(calls) == 2
    with pytest.raises(UserFacingError):
        manager.uninstall("hf_sd15_internal")


def test_ltx_runtime_config_routes_are_exposed(tmp_path, monkeypatch):
    from edmg_studio_backend.services import ltx_25_runtime

    manager = _manager(tmp_path, monkeypatch)
    launcher = tmp_path / "launcher_env.json"
    monkeypatch.setenv("EDMG_LAUNCHER_ENV", str(launcher))
    monkeypatch.setattr(
        ltx_25_runtime,
        "runtime_identity",
        lambda: {"python": "qualified-python", "ltx_pipelines_version": "1.3.0"},
    )
    app = FastAPI()
    app.include_router(create_models_router(get_models=lambda: manager))

    with TestClient(app) as client:
        saved = client.post("/v1/runtimes/ltx-25/config", json={
            "python": str(Path(ltx_25_runtime.sys.executable)),
            "timeout_s": 7200,
            "smoke_timeout_s": 900,
        })
        probed = client.post("/v1/runtimes/ltx-25/probe")

    assert saved.status_code == 200
    assert probed.status_code == 200
    assert probed.json()["ready"] is True
    assert probed.json()["identity"]["ltx_pipelines_version"] == "1.3.0"


def test_install_requires_license_and_cloud_only_is_explicit(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    with pytest.raises(UserFacingError, match="License not accepted"):
        manager.install(IDS[0])
    monkeypatch.setattr(manager, "_model_storage_mode", lambda: "cloud_only")
    with pytest.raises(UserFacingError) as exc:
        manager._install_engine_package(ModelTask(id="t", name="install"), manager._find_entry(IDS[0]))
    assert exc.value.code == "MODEL_PACKAGE_LOCAL_REQUIRED"


def test_qwen_director_cuda_pack_metadata():
    pack = next(item for item in built_in_packs() if item["id"] == "qwen_director_cuda")
    assert pack["name"] == "Qwen Director CUDA Pack"
    assert pack["package_type"] == "dlc"
    assert pack["models"] == [packages.STANDARD_GGUF_ID]
    assert pack["platforms"] == ["windows"]
    assert pack["runtime_components"] == [{
        "id": "llama_cpp_cuda", "name": "llama.cpp CUDA", "version": "v0.4.0", "build": "b10809",
    }]
    assert pack["download_size_bytes"] == 6_425_456_698


def test_qwen_pack_requires_license_before_queueing(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(manager.tasks, "start", lambda *_args, **_kwargs: pytest.fail("task queued"))
    with pytest.raises(UserFacingError) as exc:
        manager.install_pack("qwen_director_cuda", {"backend": "cuda"})
    assert exc.value.code == "MODEL_LICENSE_NOT_ACCEPTED"


def test_existing_pinned_llama_cuda_runtime_is_reused(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from edmg_studio_backend.services import model_manager as model_manager_module

    manager = _manager(tmp_path, monkeypatch)
    executable = manager._llama_cuda_runtime_path()
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    (executable.parent / "runtime-install.json").write_text(json.dumps({
        **manager._LLAMA_CUDA_RECEIPT, "schema_version": 1,
    }))
    monkeypatch.setattr(model_manager_module, "probe_llama_server", lambda path: SimpleNamespace(cuda_devices=("CUDA0: fixture",)))
    persisted = []
    monkeypatch.setattr(model_manager_module, "update_launcher_environment", lambda updates: persisted.append(updates))
    monkeypatch.setattr(model_manager_module.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("installer invoked"))

    result = manager._install_llama_cuda_runtime(ModelTask(id="t", name="runtime"), tmp_path / "installer.ps1")

    assert result == executable.resolve()
    assert persisted == [{"EDMG_LLAMA_SERVER": str(executable.resolve())}]


def test_qwen_pack_worker_uses_exact_cuda_runtime_and_requires_ready(tmp_path, monkeypatch, tiny_packages):
    from edmg_studio_backend.services import model_manager as model_manager_module

    manager = _manager(tmp_path, monkeypatch)
    entry = manager._find_entry(packages.STANDARD_GGUF_ID)
    _, package_root = manager._models_dest(entry)

    def install_model(task, selected):
        assert selected["id"] == packages.STANDARD_GGUF_ID
        materialize(package_root, tiny_packages[packages.STANDARD_GGUF_ID])
        manager._validate_engine_package(task, selected)

    executable = manager._llama_cuda_runtime_path()
    observed = {}
    sequence = []

    def track_model(task, selected):
        sequence.append("model")
        install_model(task, selected)

    def install_runtime(_task, _script):
        sequence.append("runtime")
        return executable

    monkeypatch.setattr(manager, "_install_engine_package", track_model)
    monkeypatch.setattr(manager, "_install_llama_cuda_runtime", install_runtime)

    def smoke(model_id, **kwargs):
        observed.update(kwargs["hardware"])
        assert model_id == packages.STANDARD_GGUF_ID
        return {"runtime_ready": True, "blockers": []}

    monkeypatch.setattr(model_manager_module.DEFAULT_RUNTIME_REGISTRY, "smoke_test", smoke)
    task = ModelTask(id="t", name="pack", model_id="pack:qwen_director_cuda")
    manager._install_qwen_director_cuda_pack(task, tmp_path / "installer.ps1", {"backend": "cpu", "ram_gb": 64})

    assert sequence == ["runtime", "model"]
    assert observed["backend"] == "cpu"
    assert observed["ram_gb"] == 64
    assert observed["llama_backend"] == "cuda"
    assert observed["llama_server_path"] == str(executable.resolve())
    assert task.bytes_total == 6_425_456_698


def test_install_pack_route_preserves_tasks_and_adds_coordinated_task(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    observed = {}

    def install_pack(pack_id, hardware):
        observed.update(hardware)
        return [ModelTask(id="pack-task", name="pack", model_id=f"pack:{pack_id}")]

    monkeypatch.setattr(manager, "install_pack", install_pack)
    app = FastAPI()
    app.include_router(create_models_router(
        get_models=lambda: manager,
        get_hardware=lambda: {"backend": "cuda", "ram_gb": 64},
        get_director_runtime_settings=lambda: {"runtime_path": "configured.exe", "llama_backend": "cpu"},
    ))
    with TestClient(app) as client:
        response = client.post("/v1/models/install_pack", json={"pack_id": "qwen_director_cuda"})

    assert response.status_code == 200
    body = response.json()
    assert body["task"] == body["tasks"][0]
    assert observed["backend"] == "cuda"
    assert observed["llama_backend"] == "cpu"
    assert observed["llama_server_path"] == "configured.exe"
