from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from ..uv_toolchain import ToolchainError


@dataclass(frozen=True)
class SetupRouterDependencies:
    settings: Any
    tasks: Any
    compute_status: Callable[..., dict[str, Any]]
    resolve_profile: Callable[[dict[str, Any]], str]
    check_backend: Callable[..., dict[str, Any]]
    install_backend: Callable[..., None]
    install_ollama: Callable[..., None]
    start_ollama: Callable[..., None]
    pull_ollama: Callable[..., None]
    install_7zip: Callable[..., None]
    find_7zip: Callable[..., str]
    check_ollama: Callable[..., dict[str, Any]]
    ai_config: Callable[[], dict[str, Any]]
    comfy_installed: Callable[..., bool]
    install_comfy: Callable[..., None]
    start_comfy: Callable[..., None]
    stop_comfy: Callable[[], None]
    comfy_diagnose: Callable[[dict[str, Any]], dict[str, Any]]
    hardware: Callable[[], dict[str, Any]]
    cuda_enabled: Callable[[], bool]
    install_edmg: Callable[..., None]
    check_canceled: Callable[[Any, str], None]
    task_log: Callable[[Any, str], None]


def create_setup_router(deps: SetupRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/v1/setup", tags=["setup"])
    cache_ttl_s = 30.0
    cache_lock = threading.Lock()
    status_cache: dict[bool, tuple[float, dict[str, Any]]] = {}

    def clear_status_cache() -> None:
        with cache_lock:
            status_cache.clear()

    router.clear_status_cache = clear_status_cache  # type: ignore[attr-defined]

    @router.get("/status")
    def setup_status(refresh: bool = False, include_optional: bool = False):
        now = time.monotonic()
        cache_key = bool(include_optional)
        cached = False
        with cache_lock:
            entry = status_cache.get(cache_key)
            if not refresh and entry and now - entry[0] < cache_ttl_s:
                checked_at, payload = entry
                result = deepcopy(payload)
                cached = True
            else:
                result = deps.compute_status(include_optional=include_optional)
                checked_at = time.monotonic()
                status_cache[cache_key] = (checked_at, deepcopy(result))
        result["tasks"] = [task.to_dict() for task in deps.tasks.list()[:10]]
        result["status_cache"] = {
            "cached": cached,
            "age_seconds": round(max(0.0, time.monotonic() - checked_at), 3),
            "ttl_seconds": cache_ttl_s,
        }
        return result

    @router.get("/tasks")
    def setup_task_list():
        tasks = [task.to_dict() for task in deps.tasks.list()[:10]]
        return {
            "ok": True,
            "active": any(task["status"] in ("queued", "running") for task in tasks),
            "tasks": tasks,
        }

    @router.post("/tasks/{task_id}/cancel")
    def setup_task_cancel(task_id: str):
        task = deps.tasks.cancel(task_id)
        if task is None:
            raise HTTPException(404, f"Setup task not found: {task_id}")
        return {"ok": True, "task": task.to_dict()}

    @router.post("/ollama/install_managed")
    def setup_ollama_install_managed():
        task = deps.tasks.start(
            "install_managed_ollama",
            deps.install_ollama,
            deps.settings.external_dir / "_installers",
            deps.settings.external_dir,
            deps.settings.models_dir,
            os.getenv("EDMG_AI_OLLAMA_URL", "http://127.0.0.1:11434"),
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/ollama/download_and_run")
    def setup_ollama_download_and_run():
        return setup_ollama_install_managed()

    @router.post("/ollama/start_managed")
    def setup_ollama_start_managed():
        task = deps.tasks.start(
            "start_managed_ollama",
            deps.start_ollama,
            deps.settings.external_dir,
            deps.settings.models_dir,
            os.getenv("EDMG_AI_OLLAMA_URL", "http://127.0.0.1:11434"),
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/ollama/pull")
    def setup_ollama_pull(payload: dict[str, Any]):
        model = (payload or {}).get("model") or os.getenv("EDMG_AI_OLLAMA_MODEL", "qwen3:8b")
        url = os.getenv("EDMG_AI_OLLAMA_URL", "http://127.0.0.1:11434")
        task = deps.tasks.start(f"pull_model:{model}", deps.pull_ollama, url, model)
        return {"ok": True, "task": task.to_dict()}

    @router.post("/7zip/install")
    def setup_7zip_install():
        task = deps.tasks.start(
            "install_7zip", deps.install_7zip, deps.settings.external_dir, deps.settings.data_dir
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/backend/install")
    def setup_backend_install(payload: dict[str, Any]):
        try:
            profile = deps.resolve_profile(payload)
        except ToolchainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        status = deps.check_backend(accelerator_profile=profile, check_sync=False)
        if status.get("immutable"):
            raise HTTPException(
                status_code=409,
                detail=str(
                    status.get("hint")
                    or "This packaged backend is self-contained; install another application build to change profiles."
                ),
            )
        task = deps.tasks.start(
            f"sync_backend_profile:{profile}", deps.install_backend, accelerator_profile=profile
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/full/install")
    def setup_full_install(payload: dict[str, Any]):
        try:
            profile = deps.resolve_profile(payload)
        except ToolchainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        toolchain = deps.check_backend(accelerator_profile=profile, check_sync=False)
        if toolchain.get("immutable") and not toolchain.get("ok"):
            raise HTTPException(
                status_code=409,
                detail=str(
                    toolchain.get("hint")
                    or "The packaged backend profile does not match this setup request."
                ),
            )
        flavor = {"cpu": "cpu", "directml": "amd", "cuda": "nvidia"}[profile]
        port = int((payload or {}).get("comfy_port") or 8188)
        model = (payload or {}).get("model") or os.getenv("EDMG_AI_OLLAMA_MODEL", "qwen3:8b")
        ollama_url = os.getenv("EDMG_AI_OLLAMA_URL", "http://127.0.0.1:11434")
        ai_config = deps.ai_config()

        def run(task):
            deps.check_canceled(task, "Full setup canceled.")
            deps.install_backend(task, accelerator_profile=profile)
            deps.check_canceled(task, "Full setup canceled.")
            try:
                deps.find_7zip(deps.settings.external_dir, deps.settings.data_dir)
            except Exception:
                deps.install_7zip(task, deps.settings.external_dir, deps.settings.data_dir)
            deps.check_canceled(task, "Full setup canceled.")
            if ai_config.get("ollama_required"):
                status = deps.check_ollama(ollama_url, model)
                if not status.get("ok"):
                    try:
                        deps.start_ollama(
                            task, deps.settings.external_dir, deps.settings.models_dir, ollama_url
                        )
                    except Exception:
                        deps.install_ollama(
                            task,
                            deps.settings.external_dir / "_installers",
                            deps.settings.external_dir,
                            deps.settings.models_dir,
                            ollama_url,
                        )
                        deps.start_ollama(
                            task, deps.settings.external_dir, deps.settings.models_dir, ollama_url
                        )
                else:
                    deps.task_log(task, "Ollama is already reachable.")
                if not deps.check_ollama(ollama_url, model).get("model_present"):
                    deps.pull_ollama(task, ollama_url, model)
                else:
                    deps.task_log(task, f"Ollama model {model} is already present.")
            else:
                deps.task_log(
                    task,
                    f"Skipping Ollama install because Studio AI is configured for {ai_config.get('label')}.",
                )
            deps.check_canceled(task, "Full setup canceled.")
            if not deps.comfy_installed(deps.settings.external_dir, deps.settings.data_dir):
                deps.install_comfy(
                    task,
                    deps.settings.external_dir,
                    flavor,
                    deps.settings.data_dir,
                    deps.settings.models_dir,
                )
            else:
                deps.task_log(task, "ComfyUI Portable is already installed.")
            try:
                ready = deps.comfy_diagnose({})
                comfy_ready = bool(ready.get("compatible") or ready.get("busy_compatible"))
            except Exception:
                comfy_ready = False
            if comfy_ready:
                deps.task_log(task, "ComfyUI is already reachable.")
            else:
                deps.start_comfy(
                    task,
                    deps.settings.external_dir,
                    flavor,
                    "127.0.0.1",
                    port,
                    deps.settings.data_dir,
                    deps.settings.models_dir,
                )

        task = deps.tasks.start(f"full_setup:{profile}:{ai_config.get('provider')}", run)
        return {"ok": True, "task": task.to_dict()}

    @router.post("/comfyui/portable/install")
    def setup_comfyui_portable_install(payload: dict[str, Any]):
        flavor = (payload or {}).get("flavor") or "cpu"
        task = deps.tasks.start(
            f"install_comfyui_portable:{flavor}",
            deps.install_comfy,
            deps.settings.external_dir,
            flavor,
            deps.settings.data_dir,
            deps.settings.models_dir,
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/comfyui/portable/start")
    def setup_comfyui_portable_start(payload: dict[str, Any]):
        flavor = str((payload or {}).get("flavor") or "auto").strip().lower()
        if flavor == "auto":
            hardware = deps.hardware()
            flavor = (
                "nvidia"
                if str(hardware.get("backend") or "cpu").lower() == "cuda" and deps.cuda_enabled()
                else "cpu"
            )
        port = int((payload or {}).get("port") or 8188)
        task = deps.tasks.start(
            f"start_comfyui_portable:{flavor}",
            deps.start_comfy,
            deps.settings.external_dir,
            flavor,
            "127.0.0.1",
            port,
            deps.settings.data_dir,
            deps.settings.models_dir,
        )
        return {"ok": True, "task": task.to_dict()}

    @router.post("/comfyui/portable/stop")
    def setup_comfyui_portable_stop():
        deps.stop_comfy()
        return {"ok": True}

    @router.post("/edmg/install")
    def setup_edmg_install(payload: dict[str, Any]):
        mode = str((payload or {}).get("mode") or "standard").strip().lower() or "standard"
        backend = str((payload or {}).get("backend") or "cpu").strip().lower() or "cpu"
        task = deps.tasks.start(
            f"install_edmg_core:{mode}:{backend}",
            deps.install_edmg,
            deps.settings.data_dir,
            mode=mode,
            backend=backend,
        )
        return {"ok": True, "task": task.to_dict()}

    return router
