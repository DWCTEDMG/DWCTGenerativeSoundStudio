from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests

from ..uv_toolchain import (
    ACCELERATOR_PROFILES,
    ToolchainError,
    active_accelerator_profile,
    is_packaged_backend,
    normalize_accelerator_profile,
    profile_from_legacy_inputs,
    sync_frozen_project,
    toolchain_status,
)

try:
    import py7zr  # type: ignore
except Exception:  # pragma: no cover
    py7zr = None


logger = logging.getLogger(__name__)


@dataclass
class SetupTask:
    id: str
    name: str
    status: str = "queued"  # queued|running|done|failed|canceled
    progress: Optional[float] = None
    last_log: str = ""
    error: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "last_log": self.last_log,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "cancel_requested": self.cancel_requested,
        }


class SetupTaskCanceled(Exception):
    """Raised when a setup task is canceled and should stop promptly."""


class SetupTaskManager:
    """Very small in-memory task runner for installer operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, SetupTask] = {}

    def list(self) -> list[SetupTask]:
        with self._lock:
            # newest first
            return sorted(self._tasks.values(), key=lambda t: (t.started_at or 0), reverse=True)

    def start(self, name: str, fn, *args, **kwargs) -> SetupTask:
        task = SetupTask(id=str(uuid.uuid4())[:8], name=name, status="queued")
        with self._lock:
            self._tasks[task.id] = task

        def runner():
            if task.cancel_requested:
                task.status = "canceled"
                task.started_at = time.time()
                task.ended_at = task.started_at
                if not task.last_log:
                    task.last_log = "Canceled before start."
                return
            task.status = "running"
            task.started_at = time.time()
            try:
                self.check_canceled(task)
                fn(task, *args, **kwargs)
                self.check_canceled(task)
                task.status = "done"
            except SetupTaskCanceled as e:
                task.status = "canceled"
                if str(e):
                    task.last_log = str(e)
            except Exception as e:
                if task.cancel_requested:
                    task.status = "canceled"
                    task.last_log = str(e) or "Canceled."
                else:
                    task.status = "failed"
                    task.error = str(e)
                    task.last_log = (task.last_log + "\n" if task.last_log else "") + f"ERROR: {e}"
            finally:
                task.ended_at = time.time()

        threading.Thread(target=runner, daemon=True).start()
        return task

    def cancel(self, task_id: str) -> SetupTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status in ("done", "failed", "canceled"):
                return task
            task.cancel_requested = True
            if task.status == "queued":
                task.status = "canceled"
                task.last_log = task.last_log or "Canceled before start."
                now = time.time()
                task.started_at = task.started_at or now
                task.ended_at = now
            elif task.status == "running" and "Cancel requested" not in task.last_log:
                task.last_log = "Cancel requested — stopping after current step."
            return task

    @staticmethod
    def log(task: SetupTask, msg: str) -> None:
        task.last_log = msg

    @staticmethod
    def set_progress(task: SetupTask, v: Optional[float]) -> None:
        task.progress = v

    @staticmethod
    def check_canceled(task: SetupTask, message: str = "Setup task canceled.") -> None:
        if getattr(task, "cancel_requested", False):
            raise SetupTaskCanceled(message)


def _run_subprocess(
    task: SetupTask,
    args: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    creationflags: int = 0,
) -> None:
    proc = subprocess.Popen(args, cwd=cwd, env=env, creationflags=creationflags)
    try:
        while True:
            SetupTaskManager.check_canceled(task)
            code = proc.poll()
            if code is not None:
                if code != 0:
                    raise subprocess.CalledProcessError(code, args)
                return
            time.sleep(0.25)
    except SetupTaskCanceled:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        raise


def _extract_zip_with_cancel(task: SetupTask, archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    base_dir = dest_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        total = max(1, len(members))
        for index, member in enumerate(members, start=1):
            SetupTaskManager.check_canceled(task)
            target_path = (dest_dir / Path(member.filename)).resolve()
            if not target_path.is_relative_to(base_dir):
                raise ValueError(f"Unsafe path in archive: {member.filename}")
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
            SetupTaskManager.set_progress(task, max(task.progress or 0.0, min(0.98, 0.8 + (index / total) * 0.18)))


# ------------------------------ Ollama ------------------------------

def _env_truthy(name: str) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}

def _ollama_base(url: str) -> str:
    return (url or "http://127.0.0.1:11434").rstrip("/")


def _managed_ollama_models_dir(models_dir: Path) -> Path:
    explicit = str(os.environ.get("OLLAMA_MODELS") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (models_dir / "ollama").resolve()


def _ollama_host_value(url: str) -> str:
    parsed = urlparse(_ollama_base(url))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 11434)
    return f"{host}:{port}"


def managed_ollama_launch_script_path(external_dir: Path) -> Path:
    script_name = "start_ollama_studio.bat" if platform.system() == "Windows" else "start_ollama_studio.sh"
    return (external_dir.resolve() / "ollama" / script_name).resolve()


def _find_ollama_exe(external_dir: Path | None = None) -> str:
    env = os.environ.get("EDMG_OLLAMA_PATH")
    if env and Path(env).exists():
        return env

    ignore_system = _env_truthy("EDMG_SETUP_IGNORE_SYSTEM_OLLAMA")
    candidates: list[Path] = []
    if external_dir is not None:
        external_root = external_dir.expanduser().resolve()
        if platform.system() == "Windows":
            candidates.extend(
                [
                    external_root / "ollama" / "ollama.exe",
                    external_root / "bin" / "ollama.exe",
                ]
            )
        else:
            candidates.extend(
                [
                    external_root / "ollama" / "ollama",
                    external_root / "bin" / "ollama",
                ]
            )

    if platform.system() == "Windows" and not ignore_system:
        local_appdata = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        candidates.append(local_appdata / "Programs" / "Ollama" / "ollama.exe")
        program_files = os.environ.get("ProgramFiles", "").strip()
        if program_files:
            candidates.append(Path(program_files) / "Ollama" / "ollama.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    if not ignore_system:
        which = shutil.which("ollama") or shutil.which("ollama.exe")
        if which:
            return which

    raise RuntimeError("Ollama executable not found. Install Ollama or set EDMG_OLLAMA_PATH.")


def write_managed_ollama_launch_script(
    external_dir: Path,
    models_dir: Path,
    ollama_url: str,
    ollama_exe: str | None = None,
) -> Path:
    script_dir = (external_dir / "ollama").resolve()
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = managed_ollama_launch_script_path(external_dir)
    models_root = _managed_ollama_models_dir(models_dir)
    host_value = _ollama_host_value(ollama_url)
    command = ollama_exe or "ollama"
    if platform.system() == "Windows":
        content = (
            "@echo off\n"
            "setlocal\n"
            f"set \"OLLAMA_MODELS={models_root}\"\n"
            f"set \"OLLAMA_HOST={host_value}\"\n"
            f"\"{command}\" serve\n"
        )
    else:
        escaped_command = str(command).replace('"', '\\"')
        escaped_models_root = str(models_root).replace('"', '\\"')
        content = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"export OLLAMA_MODELS=\"{escaped_models_root}\"\n"
            f"export OLLAMA_HOST=\"{host_value}\"\n"
            f"exec \"{escaped_command}\" serve\n"
        )
    script_path.write_text(content, encoding="utf-8")
    if platform.system() != "Windows":
        script_path.chmod(0o755)
    return script_path


def check_ollama(ollama_url: str, model: str) -> dict[str, Any]:
    base = _ollama_base(ollama_url)
    try:
        r = requests.get(f"{base}/api/tags", timeout=2.5)
        r.raise_for_status()
        data = r.json()
        models = [m.get("name") for m in (data.get("models") or []) if isinstance(m, dict)]
        present = (model in models) if model else False
        return {
            "ok": True,
            "url": base,
            "model": model,
            "model_present": present,
            "models": models[:50],
        }
    except Exception:
        logger.warning("Ollama status probe failed", exc_info=True)
        return {
            "ok": False,
            "url": base,
            "model": model,
            "model_present": False,
            "hint": "Install Ollama and ensure it is running (it exposes http://127.0.0.1:11434).",
            "error": "Ollama status probe failed",
        }


class OllamaManagedProcess:
    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.exe_path: Optional[str] = None
        self.models_dir: Optional[Path] = None
        self.url: Optional[str] = None
        self.script_path: Optional[Path] = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, task: SetupTask, external_dir: Path, models_dir: Path, ollama_url: str) -> None:
        base = _ollama_base(ollama_url)
        if check_ollama(base, "").get("ok"):
            SetupTaskManager.log(task, f"Ollama is already reachable at {base}.")
            return

        exe = _find_ollama_exe(external_dir)
        models_root = _managed_ollama_models_dir(models_dir)
        models_root.mkdir(parents=True, exist_ok=True)
        external_dir.mkdir(parents=True, exist_ok=True)
        script_path = write_managed_ollama_launch_script(external_dir, models_dir, base, exe)

        if self.running():
            SetupTaskManager.log(task, f"Studio-managed Ollama is already running with models at {self.models_dir}.")
            return

        env = os.environ.copy()
        env["OLLAMA_MODELS"] = str(models_root)
        env["OLLAMA_HOST"] = _ollama_host_value(base)

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        SetupTaskManager.log(task, f"Starting Studio-managed Ollama with models in {models_root}…")
        self.proc = subprocess.Popen(
            [exe, "serve"],
            cwd=str(external_dir.resolve()),
            env=env,
            creationflags=creationflags,
        )
        self.exe_path = exe
        self.models_dir = models_root
        self.url = base
        self.script_path = script_path

        try:
            for _ in range(160):
                SetupTaskManager.check_canceled(task, "Managed Ollama startup canceled.")
                if check_ollama(base, "").get("ok"):
                    SetupTaskManager.log(task, f"Ollama is running. Studio models path: {models_root}")
                    return
                if self.proc.poll() is not None:
                    break
                time.sleep(0.25)
        except SetupTaskCanceled:
            self.stop()
            raise

        if check_ollama(base, "").get("ok"):
            SetupTaskManager.log(task, f"Ollama is running. Studio models path: {models_root}")
            return

        raise RuntimeError(
            f"Ollama did not become ready at {base}. Try running {script_path} manually or finish the Ollama install first."
        )

    def stop(self) -> None:
        if self.proc and self.running():
            try:
                self.proc.terminate()
            except Exception:
                pass


def download_and_install_ollama(
    task: SetupTask,
    dest_dir: Path,
    external_dir: Path | None = None,
    models_dir: Path | None = None,
    ollama_url: str | None = None,
) -> None:
    """Install Ollama silently into the Studio-managed external-tools root."""

    if external_dir is None:
        raise RuntimeError("Managed Ollama install requires a Studio external tools directory.")

    if platform.system().lower() == "linux":
        if models_dir is None:
            raise RuntimeError("Linux Ollama setup requires a Studio models directory.")
        base = _ollama_base(ollama_url or os.environ.get("EDMG_AI_OLLAMA_URL") or "http://127.0.0.1:11434")
        parsed = urlparse(base)
        port = str(parsed.port or (443 if parsed.scheme == "https" else 11434))
        studio_home = _infer_studio_home(external_dir, models_dir)
        models_root = (models_dir.expanduser().resolve() / "ollama").resolve()
        env = os.environ.copy()
        env["EDMG_STUDIO_HOME"] = str(studio_home)
        env["OLLAMA_MODELS"] = str(models_root)
        env["EDMG_AI_OLLAMA_URL"] = base
        env["OLLAMA_PORT"] = port
        env["OLLAMA_PULL_MODEL"] = "0"
        env["OLLAMA_START"] = "1"
        _run_linux_setup_script(task, "setup_linux_ollama.sh", env)
        SetupTaskManager.set_progress(task, 1.0)
        SetupTaskManager.log(
            task,
            f"Linux Ollama setup is ready at {base}. Studio-managed models live under {env['OLLAMA_MODELS']}.",
        )
        return

    if platform.system().lower() != "windows":
        raise RuntimeError("Managed Ollama install is implemented for Windows and Linux.")

    dest_dir = dest_dir.expanduser().resolve()
    external_dir = external_dir.expanduser().resolve()
    install_dir = (external_dir / "ollama").resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    version = str(os.environ.get("EDMG_OLLAMA_VERSION", "")).strip()
    release_url = (
        f"https://api.github.com/repos/ollama/ollama/releases/tags/{version}"
        if version
        else "https://api.github.com/repos/ollama/ollama/releases/latest"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "EDMG-Studio",
    }
    SetupTaskManager.check_canceled(task, "Managed Ollama install canceled.")
    SetupTaskManager.log(task, "Resolving official Ollama standalone archive…")
    release = requests.get(release_url, headers=headers, timeout=60)
    release.raise_for_status()
    release_data = release.json()
    assets = release_data.get("assets") or []

    requested_asset = str(os.environ.get("EDMG_OLLAMA_ASSET", "")).strip().lower()
    machine = platform.machine().lower()
    preferred_names = []
    if requested_asset:
        preferred_names.append(requested_asset)
    if "arm" in machine:
        preferred_names.append("ollama-windows-arm64.zip")
    else:
        preferred_names.append("ollama-windows-amd64.zip")

    asset = None
    for preferred_name in preferred_names:
        asset = next((entry for entry in assets if str(entry.get("name", "")).lower() == preferred_name), None)
        if asset:
            break
    if asset is None:
        raise RuntimeError(f"Could not locate a supported Ollama standalone zip in release assets: {preferred_names}")

    asset_name = str(asset.get("name") or "ollama-windows.zip")
    asset_url = str(asset.get("browser_download_url") or "").strip()
    if not asset_url:
        raise RuntimeError("Selected Ollama release asset is missing a download URL.")

    archive_path = dest_dir / asset_name
    SetupTaskManager.log(task, f"Downloading {asset_name}…")
    try:
        with requests.get(asset_url, headers=headers, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            got = 0
            with open(archive_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    SetupTaskManager.check_canceled(task, "Managed Ollama install canceled.")
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        SetupTaskManager.set_progress(task, min(0.8, got / total))

        SetupTaskManager.check_canceled(task, "Managed Ollama install canceled.")
        SetupTaskManager.log(task, f"Extracting {asset_name} into {install_dir}…")
        _extract_zip_with_cancel(task, archive_path, install_dir)
    except SetupTaskCanceled:
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    SetupTaskManager.set_progress(task, 0.9)

    exe = _find_ollama_exe(external_dir)
    if models_dir is not None:
        script_path = write_managed_ollama_launch_script(
            external_dir,
            models_dir,
            ollama_url or "http://127.0.0.1:11434",
            exe,
        )
        models_root = _managed_ollama_models_dir(models_dir)
        SetupTaskManager.log(
            task,
            f"Ollama is installed at {exe}. Studio-managed models live under {models_root}. Helper script: {script_path}"
        )
    else:
        SetupTaskManager.log(task, f"Ollama is installed at {exe}.")
    SetupTaskManager.set_progress(task, 1.0)


def pull_ollama_model(task: SetupTask, ollama_url: str, model: str) -> None:
    base = _ollama_base(ollama_url)
    if not model:
        raise RuntimeError("No model specified")

    SetupTaskManager.log(task, f"Pulling model {model}…")
    # Ollama supports streaming progress updates by default.
    # We parse JSON lines and surface the latest status.
    with requests.post(
        f"{base}/api/pull",
        json={"model": model, "stream": True},
        stream=True,
        timeout=60 * 60,
    ) as r:
        r.raise_for_status()
        last = ""
        for line in r.iter_lines(decode_unicode=True):
            SetupTaskManager.check_canceled(task, f"Model pull canceled for {model}.")
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            status = obj.get("status") or ""
            digest = obj.get("digest")
            total = obj.get("total")
            completed = obj.get("completed")

            msg = status
            if digest:
                msg += f" ({str(digest)[:12]})"
            if total and completed:
                try:
                    p = float(completed) / float(total)
                    SetupTaskManager.set_progress(task, max(0.0, min(0.99, p)))
                except Exception:
                    pass

            if msg and msg != last:
                SetupTaskManager.log(task, msg)
                last = msg

    SetupTaskManager.set_progress(task, 1.0)
    SetupTaskManager.log(task, f"Model {model} is ready.")


# ------------------------------ ComfyUI Portable ------------------------------

COMFY_REPO = "comfyanonymous/ComfyUI"


def _github_latest_assets(repo: str) -> list[dict[str, Any]]:
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("assets") or []


def _pick_portable_asset(assets: list[dict[str, Any]], flavor: str) -> dict[str, Any]:
    flavor = (flavor or "cpu").lower()
    # Heuristics across historical naming.
    candidates: list[dict[str, Any]] = []
    for a in assets:
        name = (a.get("name") or "").lower()
        if "portable" not in name:
            continue
        if not name.endswith((".7z", ".zip")):
            continue
        candidates.append(a)

    def score(a: dict[str, Any]) -> int:
        name = (a.get("name") or "").lower()
        s = 0
        if flavor == "cpu":
            if "cpu" in name:
                s += 5
            if "or_cpu" in name or "cpu_or" in name:
                s += 3
            if "nvidia" in name or "cu" in name:
                s -= 2
        else:
            if "nvidia" in name or "cu" in name:
                s += 5
            if "cpu" in name:
                s -= 2
        # prefer smaller artifacts when tie
        try:
            size = int(a.get("size") or 0)
            s += max(0, 3 - int(size / (1024 * 1024 * 1024)))
        except Exception:
            pass
        return s

    if not candidates:
        raise RuntimeError("No portable assets found in latest ComfyUI release.")

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def _legacy_external_root(data_dir: Path | None) -> Path | None:
    if data_dir is None:
        return None
    return (data_dir / "third_party").resolve()


def linux_comfyui_root(external_dir: Path) -> Path:
    return (external_dir / "ComfyUI").resolve()


def comfy_portable_root(external_dir: Path, data_dir: Path | None = None) -> Path:
    if platform.system().lower() == "linux":
        return linux_comfyui_root(external_dir)

    preferred = (external_dir / "ComfyUI_windows_portable").resolve()
    if (preferred / "ComfyUI").exists() and (preferred / "python_embeded").exists():
        return preferred

    legacy_root = _legacy_external_root(data_dir)
    if legacy_root is not None:
        legacy = (legacy_root / "ComfyUI_windows_portable").resolve()
        if (legacy / "ComfyUI").exists() and (legacy / "python_embeded").exists():
            return legacy

    return preferred


def comfy_portable_installed(external_dir: Path, data_dir: Path | None = None) -> bool:
    root = comfy_portable_root(external_dir, data_dir)
    if platform.system().lower() == "linux":
        return (root / "main.py").exists()
    return (root / "ComfyUI").exists() and (root / "python_embeded").exists()



def _find_7z_exe(external_dir: Path, data_dir: Path | None = None) -> str:
    """Locate a 7-Zip CLI that supports BCJ2 (required for some .7z archives).

    Resolution order:
    1) EDMG_7Z_PATH env var
    2) bundled inside the Studio external-tools root (external/bin/7z.exe)
    3) legacy bundled path alongside the Studio data dir (data/third_party/bin/7z.exe)
    4) common system install paths
    5) PATH
    """
    env = os.environ.get("EDMG_7Z_PATH")
    if env and Path(env).exists():
        return env

    ignore_system = _env_truthy("EDMG_SETUP_IGNORE_SYSTEM_7Z")
    bundled_names = ("7z.exe", "7za.exe", "7zr.exe", "7zz.exe") if platform.system() == "Windows" else ("7zz", "7za", "7zr")
    for bundled_name in bundled_names:
        bundled = (external_dir / "bin" / bundled_name).resolve()
        if bundled.exists():
            return str(bundled)

    legacy_root = _legacy_external_root(data_dir)
    if legacy_root is not None:
        for bundled_name in bundled_names:
            legacy_bundled = (legacy_root / "bin" / bundled_name).resolve()
            if legacy_bundled.exists():
                return str(legacy_bundled)

    candidates = []
    if platform.system() == "Windows" and not ignore_system:
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            program_files = os.environ.get(env_name, "").strip()
            if program_files:
                candidates.append(Path(program_files) / "7-Zip" / "7z.exe")
    for c in candidates:
        if c.exists():
            return str(c)

    if not ignore_system:
        which = shutil.which("7z") or shutil.which("7z.exe") or shutil.which("7zz") or shutil.which("7zz.exe")
        if which:
            return which

    raise RuntimeError("7-Zip CLI not found. Install 7-Zip or bundle 7z.exe and/or set EDMG_7Z_PATH.")


def _extract_7z_cli(task: SetupTask, external_dir: Path, archive: Path, out_parent: Path, data_dir: Path | None = None) -> None:
    seven = _find_7z_exe(external_dir, data_dir)
    SetupTaskManager.log(task, f"Using 7-Zip: {seven}")
    out_parent.mkdir(parents=True, exist_ok=True)
    # `x` preserves folders; `-y` assumes Yes on all queries.
    cmd = [seven, "x", str(archive), f"-o{str(out_parent)}", "-y"]
    SetupTaskManager.log(task, "Extract command: " + " ".join(cmd))
    _run_subprocess(task, cmd)


def _yaml_quote(value: str) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def ensure_comfyui_model_paths(external_dir: Path, models_dir: Path, data_dir: Path | None = None) -> Path | None:
    root = comfy_portable_root(external_dir, data_dir)
    if not (root / "ComfyUI").exists():
        return None

    yaml_path = root / "ComfyUI" / "extra_model_paths.yaml"
    base_path = _yaml_quote(str(models_dir.resolve()))
    content = (
        "edmg_studio:\n"
        f"  base_path: {base_path}\n"
        "  checkpoints: checkpoints\n"
        "  loras: loras\n"
        "  embeddings: embeddings\n"
        "  vae: vae\n"
        "  controlnet: controlnet\n"
        "  upscale_models: upscale_models\n"
        "  clip: clip\n"
        "  clip_vision: clip_vision\n"
    )
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


def install_linux_comfyui_sidecar(
    task: SetupTask,
    external_dir: Path,
    flavor: str,
    data_dir: Path | None = None,
    models_dir: Path | None = None,
    *,
    start: bool = False,
) -> Path:
    root = linux_comfyui_root(external_dir)
    studio_home = _infer_studio_home(external_dir, models_dir)
    env = os.environ.copy()
    env["EDMG_STUDIO_HOME"] = str(studio_home)
    env["COMFY_ROOT"] = str(root)
    env.setdefault("COMFY_HOST", "127.0.0.1")
    env.setdefault("COMFY_PORT", "8188")
    env["COMFY_PYTHON_BIN"] = sys.executable
    env["COMFY_START"] = "1" if start else "0"
    env["COMFY_INSTALL_MODELS"] = "0"

    _run_linux_setup_script(task, "setup_linux_comfyui.sh", env)
    SetupTaskManager.set_progress(task, 1.0)
    SetupTaskManager.log(task, f"Linux ComfyUI setup is ready at {root}.")
    return root


def download_and_extract_portable(
    task: SetupTask,
    external_dir: Path,
    flavor: str,
    data_dir: Path | None = None,
    models_dir: Path | None = None,
) -> Path:
    if platform.system().lower() == "linux":
        return install_linux_comfyui_sidecar(task, external_dir, flavor, data_dir, models_dir, start=False)

    if platform.system().lower() != "windows":
        raise RuntimeError("ComfyUI Portable setup is implemented for Windows; Linux uses the sidecar installer.")

    assets = _github_latest_assets(COMFY_REPO)
    asset = _pick_portable_asset(assets, flavor)

    url = asset.get("browser_download_url")
    name = asset.get("name")
    if not url or not name:
        raise RuntimeError("Portable download URL not found.")

    dest_root = (external_dir / "ComfyUI_windows_portable").resolve()
    tmp_dir = (external_dir / "_downloads").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    archive = tmp_dir / name

    SetupTaskManager.log(task, f"Downloading ComfyUI Portable ({flavor})…")
    backup: Path | None = None
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with open(archive, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    SetupTaskManager.check_canceled(task, "ComfyUI Portable install canceled.")
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        SetupTaskManager.set_progress(task, min(0.7, (got / total) * 0.7))
                        SetupTaskManager.log(task, f"Downloading… {int((got/total)*100)}%")

        SetupTaskManager.check_canceled(task, "ComfyUI Portable install canceled.")
        SetupTaskManager.log(task, "Extracting ComfyUI Portable…")
        SetupTaskManager.set_progress(task, 0.75)

        # Clear existing
        if dest_root.exists():
            # keep user models if they already have
            # (best-effort; don't delete if there's a chance the user put models there)
            backup = dest_root.parent / f"ComfyUI_windows_portable_backup_{int(time.time())}"
            dest_root.rename(backup)

        dest_root.parent.mkdir(parents=True, exist_ok=True)

        if str(archive).lower().endswith(".7z"):
            _extract_7z_cli(task, external_dir, archive, dest_root.parent, data_dir)
        else:
            _extract_zip_with_cancel(task, archive, dest_root.parent)
    except SetupTaskCanceled:
        try:
            archive.unlink(missing_ok=True)
        except Exception:
            pass
        if backup is not None and backup.exists() and not dest_root.exists():
            try:
                backup.rename(dest_root)
            except Exception:
                pass
        raise

    # Some archives include a top-level folder; normalize to expected name.
    # Find a folder that contains python_embeded + ComfyUI.
    parent = dest_root.parent
    found = None
    for p in parent.iterdir():
        if not p.is_dir():
            continue
        if (p / "python_embeded").exists() and (p / "ComfyUI").exists():
            found = p
            break
    if found and found.name != dest_root.name:
        # Move/rename into place
        if dest_root.exists():
            # should not, but guard
            pass
        found.rename(dest_root)

    if not comfy_portable_installed(external_dir, data_dir):
        raise RuntimeError("ComfyUI Portable extraction completed, but expected folders were not found.")

    if models_dir is not None:
        yaml_path = ensure_comfyui_model_paths(external_dir, models_dir, data_dir)
        if yaml_path is not None:
            SetupTaskManager.log(task, f"Configured external model paths: {yaml_path}")

    SetupTaskManager.set_progress(task, 1.0)
    SetupTaskManager.log(task, "ComfyUI Portable installed.")
    return dest_root


class ComfyPortableProcess:
    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.root: Optional[Path] = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(
        self,
        task: SetupTask,
        external_dir: Path,
        flavor: str,
        host: str = "127.0.0.1",
        port: int = 8188,
        data_dir: Path | None = None,
        models_dir: Path | None = None,
    ) -> None:
        if platform.system().lower() == "linux":
            root = linux_comfyui_root(external_dir)
            main = root / "main.py"
            if not main.exists():
                raise RuntimeError("Linux ComfyUI is not installed yet. Click Install first.")

            if self.running():
                SetupTaskManager.log(task, "ComfyUI is already running.")
                return

            flavor_lower = (flavor or "cpu").lower()
            args = [
                sys.executable,
                str(main),
                "--listen",
                host,
                "--port",
                str(port),
            ]
            if flavor_lower == "cpu":
                args.append("--cpu")
            elif flavor_lower in ("nvidia", "cuda"):
                args += [
                    "--cuda-malloc",
                    "--use-pytorch-cross-attention",
                ]

            comfy_env = os.environ.copy()
            if flavor_lower in ("nvidia", "cuda"):
                comfy_env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
                comfy_env.setdefault("CUDA_LAUNCH_BLOCKING", "0")
                comfy_env.setdefault("TORCH_CUDNN_BENCHMARK", "1")
                comfy_env.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

            SetupTaskManager.log(task, f"Starting Linux ComfyUI ({flavor_lower})...")
            self.proc = subprocess.Popen(
                args,
                cwd=str(root),
                env=comfy_env,
            )
            self.root = root

            try:
                for _ in range(90):
                    SetupTaskManager.check_canceled(task, "ComfyUI startup canceled.")
                    try:
                        r = requests.get(f"http://{host}:{port}/object_info", timeout=1.0)
                        if r.status_code == 200:
                            SetupTaskManager.log(task, "ComfyUI is running.")
                            return
                    except Exception:
                        pass
                    if self.proc.poll() is not None:
                        break
                    time.sleep(1.0)
            except SetupTaskCanceled:
                self.stop()
                raise

            if self.proc.poll() is not None:
                raise RuntimeError("ComfyUI exited before it became reachable.")
            SetupTaskManager.log(task, "ComfyUI started (still warming up).")
            return

        if platform.system().lower() != "windows":
            raise RuntimeError("ComfyUI Portable auto-start is currently implemented for Windows.")

        if not comfy_portable_installed(external_dir, data_dir):
            raise RuntimeError("ComfyUI Portable is not installed yet. Click Install first.")

        root = comfy_portable_root(external_dir, data_dir)
        py = root / "python_embeded" / "python.exe"
        main = root / "ComfyUI" / "main.py"
        if not py.exists() or not main.exists():
            raise RuntimeError("ComfyUI Portable install looks incomplete.")

        if models_dir is not None:
            ensure_comfyui_model_paths(external_dir, models_dir, data_dir)

        if self.running():
            SetupTaskManager.log(task, "ComfyUI is already running.")
            return

        flavor_lower = (flavor or "cpu").lower()
        args = [
            str(py),
            "-s",
            str(main),
            "--listen",
            host,
            "--port",
            str(port),
            "--windows-standalone-build",
        ]
        if flavor_lower == "cpu":
            args.insert(3, "--cpu")
        elif flavor_lower in ("nvidia", "cuda"):
            # CUDA-optimised flags: let PyTorch manage CUDA memory via
            # its own allocator and use cross-attention for speed
            args += [
                "--cuda-malloc",
                "--use-pytorch-cross-attention",
            ]

        # CUDA environment tweaks when optimize_comfyui is on
        comfy_env = os.environ.copy()
        if flavor_lower in ("nvidia", "cuda"):
            # Expandable CUDA memory segments prevent fragmentation OOMs
            comfy_env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            comfy_env.setdefault("CUDA_LAUNCH_BLOCKING", "0")
            # cuDNN determinism off for speed; benchmark mode on
            comfy_env.setdefault("TORCH_CUDNN_BENCHMARK", "1")
            comfy_env.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

        # Hide console window.
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        SetupTaskManager.log(task, f"Starting ComfyUI Portable ({flavor_lower})…")
        self.proc = subprocess.Popen(
            args, cwd=str(root),
            env=comfy_env if flavor_lower in ("nvidia", "cuda") else None,
            creationflags=creationflags,
        )
        self.root = root

        # Wait a bit for port to open
        try:
            for _ in range(80):
                SetupTaskManager.check_canceled(task, "ComfyUI startup canceled.")
                try:
                    r = requests.get(f"http://{host}:{port}/system_stats", timeout=1.0)
                    if r.status_code == 200:
                        SetupTaskManager.log(task, "ComfyUI is running.")
                        return
                except Exception:
                    pass
                time.sleep(0.25)
        except SetupTaskCanceled:
            self.stop()
            raise

        SetupTaskManager.log(task, "ComfyUI started (still warming up). If it doesn't come online, try again or install GPU-compatible build.")

    def stop(self) -> None:
        if self.proc and self.running():
            try:
                self.proc.terminate()
            except Exception:
                pass


def check_ffmpeg(ffmpeg_path: str) -> dict[str, Any]:
    hint = "Packaged EDMG Studio should include bundled FFmpeg. If this is a dev checkout, install FFmpeg and add it to PATH, or set EDMG_FFMPEG_PATH to the ffmpeg executable."
    try:
        r = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=3)
        ok = r.returncode == 0
        return {
            "ok": ok,
            "path": ffmpeg_path,
            "version": (r.stdout.splitlines()[0] if r.stdout else None),
            "hint": None if ok else hint,
        }
    except Exception:
        logger.warning("FFmpeg status probe failed for %s", ffmpeg_path, exc_info=True)
        return {
            "ok": False,
            "path": ffmpeg_path,
            "error": "FFmpeg status probe failed",
            "hint": hint,
        }


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _studio_root() -> Path:
    return _backend_root().parent


def _infer_studio_home(external_dir: Path | None = None, models_dir: Path | None = None) -> Path:
    if external_dir is not None:
        external = external_dir.expanduser().resolve()
        if external.name.lower() in {"external", "external_tools", "tools"}:
            return external.parent
    if models_dir is not None:
        models = models_dir.expanduser().resolve()
        if models.name.lower() == "models":
            return models.parent
    return Path(os.environ.get("EDMG_STUDIO_HOME") or (Path.home() / "edmg-studio-home")).expanduser().resolve()


def _linux_setup_script(name: str) -> Path:
    return (_studio_root() / "scripts" / name).resolve()


def _run_linux_setup_script(
    task: SetupTask,
    script_name: str,
    env: dict[str, str],
) -> None:
    if platform.system().lower() != "linux":
        raise RuntimeError(f"{script_name} is only available on Linux.")
    script = _linux_setup_script(script_name)
    if not script.exists():
        raise RuntimeError(f"Linux setup script not found: {script}")
    bash = shutil.which("bash")
    if not bash:
        raise RuntimeError("bash is required for Linux setup tasks.")
    SetupTaskManager.log(task, f"Running Linux setup script: {script}")
    _run_subprocess(task, [bash, str(script)], cwd=str(_studio_root()), env=env)


def resolve_setup_accelerator_profile(payload: dict[str, Any] | None = None) -> str:
    """Resolve the new exact profile field or a validated legacy Setup payload.

    ``accelerator_profile`` intentionally accepts only the public profile names.
    The old bundle/flavor fields remain as a migration bridge, but mixed payloads
    must resolve to the same profile so stale clients cannot silently override a
    user's explicit selection.
    """

    data = payload or {}
    raw_profile = str(data.get("accelerator_profile") or "").strip().lower()
    bundle = str(data.get("bundle") or "").strip() or None
    flavor = str(data.get("flavor") or "").strip() or None

    if raw_profile:
        if raw_profile not in ACCELERATOR_PROFILES:
            allowed = ", ".join(ACCELERATOR_PROFILES)
            raise ToolchainError(
                f"Unsupported accelerator_profile {data.get('accelerator_profile')!r}. "
                f"Choose exactly one of: {allowed}."
            )
        resolved = normalize_accelerator_profile(raw_profile)
        if bundle is not None or flavor is not None:
            legacy = profile_from_legacy_inputs(bundle=bundle, flavor=flavor)
            if legacy != resolved:
                raise ToolchainError(
                    f"Conflicting accelerator selections: accelerator_profile={resolved!r}, "
                    f"but legacy bundle/flavor fields resolve to {legacy!r}."
                )
        return resolved

    return profile_from_legacy_inputs(bundle=bundle, flavor=flavor)


def check_backend_bundle(
    bundle: str | None = None,
    flavor: str | None = None,
    *,
    accelerator_profile: str | None = None,
    check_sync: bool = True,
) -> dict[str, Any]:
    """Compatibility wrapper around the locked uv project health report."""

    profile_requested = not (accelerator_profile is None and bundle is None and flavor is None)
    if profile_requested:
        resolved_profile = resolve_setup_accelerator_profile(
            {
                "accelerator_profile": accelerator_profile,
                "bundle": bundle,
                "flavor": flavor,
            }
        )
        status = dict(toolchain_status(profile=resolved_profile, check_sync=check_sync))
    elif is_packaged_backend():
        # The packaged profile is a build property recorded in its signed-off
        # release manifest; it must not fall back to the source default (CPU).
        status = dict(toolchain_status(profile=None, check_sync=check_sync))
        resolved_profile = str(status.get("accelerator_profile") or "unknown").strip().lower()
    else:
        resolved_profile = active_accelerator_profile()
        status = dict(toolchain_status(profile=resolved_profile, check_sync=check_sync))

    installed_profile = str(status.get("accelerator_profile") or "").strip().lower()
    if profile_requested and status.get("immutable") and installed_profile != resolved_profile:
        status.update(
            {
                "ok": False,
                "sync_health": "profile-mismatch",
                "hint": (
                    f"This application contains the {installed_profile or 'unknown'} backend profile. "
                    f"Install the EDMG Studio build produced for {resolved_profile}."
                ),
            }
        )

    # Preserve the legacy response keys for older desktop clients while the UI
    # migrates to the richer top-level `toolchain` object.
    status.update(
        {
            "bundle": "locked-project",
            "profile": resolved_profile,
            "python": sys.executable if not status.get("packaged") else "bundled",
            "backend_root": str(_backend_root()),
            "missing": [] if status.get("ok") else ["frozen environment out of sync"],
        }
    )
    return status


def install_backend_bundle(
    task: SetupTask,
    bundle: str | None = None,
    flavor: str | None = None,
    *,
    accelerator_profile: str | None = None,
) -> None:
    """Synchronize one exact accelerator profile from the committed uv lock."""

    resolved_profile = resolve_setup_accelerator_profile(
        {
            "accelerator_profile": accelerator_profile,
            "bundle": bundle,
            "flavor": flavor,
        }
    )

    if is_packaged_backend():
        status = check_backend_bundle(accelerator_profile=resolved_profile, check_sync=False)
        if not status.get("ok"):
            raise ToolchainError(str(status.get("hint") or "Packaged backend profile mismatch."))
        SetupTaskManager.set_progress(task, 1.0)
        SetupTaskManager.log(
            task,
            f"The packaged {resolved_profile} backend is self-contained; no Python dependency changes are needed.",
        )
        return

    root = _backend_root()
    if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
        raise ToolchainError(f"The locked backend project is incomplete under {root}.")

    SetupTaskManager.set_progress(task, 0.1)
    SetupTaskManager.log(
        task,
        f"Checking uv.lock and synchronizing the frozen {resolved_profile} backend profile…",
    )
    sync_frozen_project(resolved_profile)

    SetupTaskManager.set_progress(task, 0.9)
    status = check_backend_bundle(accelerator_profile=resolved_profile)
    if not status.get("ok"):
        raise ToolchainError(str(status.get("hint") or "The frozen backend environment is not healthy."))

    SetupTaskManager.set_progress(task, 1.0)
    SetupTaskManager.log(
        task,
        f"Locked backend profile {resolved_profile} is synchronized and healthy.",
    )


def _resolve_7zip_cli_download(page_url: str, html: str) -> tuple[str, str]:
    """Return the portable 7-Zip CLI URL and filename from the upstream download page."""

    patterns = (
        r'href="([^"]*7zr\.exe[^"]*)"',
        r"href='([^']*7zr\.exe[^']*)'",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            break
    if not match:
        raise RuntimeError("Could not locate portable 7-Zip CLI link on 7-zip.org download page.")

    href = match.group(1).strip()
    url = urljoin(page_url, href)
    fname = Path(urlparse(url).path).name or "7zr.exe"
    return url, fname


def _7zip_cli_download_candidates(page_url: str, html: str | None = None) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    explicit = str(os.environ.get("EDMG_7ZIP_URL") or "").strip()
    if explicit:
        candidates.append((explicit, Path(urlparse(explicit).path).name or "7zr.exe"))

    candidates.append(("https://github.com/ip7z/7zip/releases/latest/download/7zr.exe", "7zr.exe"))

    if html:
        try:
            candidates.append(_resolve_7zip_cli_download(page_url, html))
        except Exception:
            pass

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, fname in candidates:
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((url, fname))
    return deduped


def download_and_install_7zip(task: SetupTask, external_dir: Path, data_dir: Path | None = None) -> None:
    """Download a portable 7-Zip CLI into the Studio external-tools root."""
    if platform.system() != "Windows":
        SetupTaskManager.log(task, "7-Zip install is Windows-only; skipping.")
        return

    try:
        existing = _find_7z_exe(external_dir, data_dir)
        SetupTaskManager.log(task, f"7-Zip already available at: {existing}")
        return
    except Exception:
        pass

    dest_dir = (external_dir / "bin").resolve()
    download_dir = (external_dir / "_downloads").resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    page_url = "https://7-zip.org/download.html"
    html: str | None = None
    try:
        SetupTaskManager.check_canceled(task, "7-Zip download canceled.")
        SetupTaskManager.log(task, f"Fetching 7-Zip download page: {page_url}")
        r = requests.get(page_url, timeout=30)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        SetupTaskManager.log(task, f"7-Zip page fetch unavailable; falling back to direct release URL. ({exc})")

    last_error: Exception | None = None
    portable_exe = dest_dir / "7zr.exe"
    for url, fname in _7zip_cli_download_candidates(page_url, html):
        archive = download_dir / fname
        portable_exe = dest_dir / fname
        try:
            SetupTaskManager.log(task, f"Downloading portable 7-Zip CLI: {url}")
            with requests.get(url, stream=True, timeout=60) as rr:
                rr.raise_for_status()
                total = int(rr.headers.get("content-length") or "0")
                got = 0
                with open(archive, "wb") as f:
                    for chunk in rr.iter_content(chunk_size=1024 * 1024):
                        SetupTaskManager.check_canceled(task, "7-Zip download canceled.")
                        if not chunk:
                            continue
                        f.write(chunk)
                        got += len(chunk)
                        if total > 0:
                            task.progress = min(0.95, got / total)

            SetupTaskManager.check_canceled(task, "7-Zip download canceled.")
            shutil.copy2(archive, portable_exe)
            break
        except SetupTaskCanceled:
            try:
                archive.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        except Exception as exc:
            last_error = exc
            SetupTaskManager.log(task, f"Portable 7-Zip download failed from {url}: {exc}")
    else:
        if last_error is not None:
            raise RuntimeError(str(last_error))
        raise RuntimeError("Could not resolve a portable 7-Zip CLI download URL.")

    task.progress = 0.97
    SetupTaskManager.log(task, f"Validating portable 7-Zip CLI: {portable_exe}")
    probe = subprocess.run([str(portable_exe), "i"], capture_output=True, text=True, timeout=10)
    if probe.returncode != 0:
        raise RuntimeError(f"Portable 7-Zip validation failed: {probe.stderr or probe.stdout or 'unknown error'}")

    seven = _find_7z_exe(external_dir, data_dir)
    task.progress = 1.0
    SetupTaskManager.log(task, f"Portable 7-Zip CLI is ready: {seven}")
