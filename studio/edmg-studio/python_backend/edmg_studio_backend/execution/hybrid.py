"""SSH Linux video workers with a pre-launch WSL backup and local project ownership."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid
import zipfile

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LinuxVideoNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    host: str = ""
    port: int = Field(default=22, ge=1, le=65535)
    user: str = "root"
    identity_file: str = ""
    python: str = ""
    backend_root: str = ""
    models_root: str = ""
    staging_root: str = "/tmp/edmg-hybrid"
    distro: str = "Ubuntu"

    @field_validator("host", "user", "distro")
    @classmethod
    def safe_identity(cls, value: str) -> str:
        if value and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,253}", value)):
            raise ValueError("Use a hostname, IPv4 address, username, or distribution name without shell characters")
        return value

    @field_validator("python", "backend_root", "models_root", "staging_root")
    @classmethod
    def linux_path(cls, value: str) -> str:
        if value and (not value.startswith("/") or any(c in value for c in "\r\n\x00") or ".." in value.split("/")):
            raise ValueError("Worker paths must be absolute Linux paths without traversal")
        return value.rstrip("/") if value != "/" else value


class HybridVideoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remote: LinuxVideoNode = Field(default_factory=LinuxVideoNode)
    wsl_backup: LinuxVideoNode = Field(default_factory=LinuxVideoNode)
    engines: list[str] = Field(default_factory=lambda: ["svd", "animatediff", "ltx_25", "hunyuan_video15"], max_length=4)
    allow_local_fallback: bool = True
    timeout_seconds: int = Field(default=7200, ge=30, le=86400)

    @field_validator("engines")
    @classmethod
    def supported_engines(cls, values: list[str]) -> list[str]:
        if any(v not in {"svd", "animatediff", "ltx_25", "hunyuan_video15"} for v in values):
            raise ValueError("Unsupported hybrid video engine")
        return list(dict.fromkeys(values))


def load_settings() -> HybridVideoSettings:
    filename = os.getenv("EDMG_HYBRID_CONFIG_PATH", "")
    if not filename or not Path(filename).is_file():
        return HybridVideoSettings()
    return HybridVideoSettings.model_validate_json(Path(filename).read_text(encoding="utf-8"))


class LinuxVideoTransport:
    def __init__(self, node: LinuxVideoNode, *, wsl: bool = False):
        self.node, self.wsl = node, wsl
        if not node.python or not node.backend_root or not node.models_root:
            raise ValueError("Configure worker Python, backend package root, and models root")
        if not wsl and (not node.host or not node.identity_file):
            raise ValueError("Configure the remote SSH host and private key path")

    def command(self, args: list[str]) -> list[str]:
        if self.wsl:
            return ["wsl.exe", "--distribution", self.node.distro, "--exec", *args]
        return ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={Path(self.node.identity_file).parent / 'known_hosts'}",
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
                "-p", str(self.node.port), "-i", self.node.identity_file,
                f"{self.node.user}@{self.node.host}", shlex.join(args)]

    def worker_command(self, *args: str) -> list[str]:
        return self.command(["env", f"PYTHONPATH={self.node.backend_root}",
                             "EDMG_HUNYUAN15_RUNNER=external", f"EDMG_HUNYUAN15_PYTHON={self.node.python}", self.node.python,
                             "-m", "edmg_studio_backend.execution.video_worker", *args])

    def probe(self, model_names: tuple[str, str] | None = None) -> dict:
        arguments = ["--probe", "--models-root", self.node.models_root]
        if model_names:
            arguments.extend(["--video-model", f"{self.node.models_root}/{model_names[0]}"])
            if model_names[1]:
                arguments.extend(["--base-model", f"{self.node.models_root}/{model_names[1]}"])
        result = subprocess.run(self.worker_command(*arguments),
                                capture_output=True, text=True, timeout=20, check=False)
        if result.returncode != 0:
            raise RuntimeError("Linux worker probe failed; verify SSH trust, Python environment, and backend checkout")
        report = json.loads(result.stdout)
        expected_worker = hashlib.sha256(Path(__file__).with_name("video_worker.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if report.get("protocol_version") != 1 or report.get("worker_sha256") != expected_worker:
            raise RuntimeError("Linux worker source version does not match the coordinator")
        if not report.get("cuda") or not report.get("models_present") or report.get("requested_models_present") is False:
            raise RuntimeError("Linux worker needs usable CUDA and an installed models directory")
        return report

    def copy(self, local: Path, remote: str, *, download: bool = False) -> None:
        if self.wsl:
            from .staging import windows_path_to_wsl
            source, target = (remote, windows_path_to_wsl(local)) if download else (windows_path_to_wsl(local), remote)
            command = self.command(["cp", "--", source, target])
            cwd = None
        else:
            target = f"{self.node.user}@{self.node.host}:{remote}"
            command = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", f"UserKnownHostsFile={Path(self.node.identity_file).parent / 'known_hosts'}",
                       "-o", "ConnectTimeout=8", "-P", str(self.node.port), "-i", self.node.identity_file,
                       *([target, local.name] if download else [local.name, target])]
            cwd = local.parent
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=300, check=False)
        if result.returncode != 0:
            raise RuntimeError("Linux worker asset transfer failed")


def read_frames(archive: Path, *, expected_frames: int, width: int, height: int, request_sha256: str):
    from PIL import Image
    frames = []
    with zipfile.ZipFile(archive) as bundle:
        expected = [f"frames/{i:06d}.png" for i in range(expected_frames)]
        if bundle.namelist() != ["receipt.json", *expected]:
            raise RuntimeError("Worker returned an unexpected frame inventory")
        if any(entry.file_size > max(1024 * 1024, width * height * 8) for entry in bundle.infolist()):
            raise RuntimeError("Worker frame exceeds the allowed size")
        receipt = json.loads(bundle.read("receipt.json"))
        if receipt.get("frames") != expected_frames or receipt.get("width") != width or receipt.get("height") != height or receipt.get("request_sha256") != request_sha256:
            raise RuntimeError("Worker receipt does not match requested media")
        for name in expected:
            with bundle.open(name) as stream, Image.open(stream) as frame:
                if frame.size != (width, height):
                    raise RuntimeError("Worker returned an unexpected frame size")
                frames.append(frame.convert("RGB"))
    return frames, receipt


def try_generate(parameters: dict):
    settings = load_settings()
    if parameters["engine"] not in settings.engines or not (settings.remote.enabled or settings.wsl_backup.enabled):
        return None
    if os.getenv("EDMG_HYBRID_DISABLED_FOR_JOB") == "1":
        return None
    from ..config import Settings
    models_root = Settings().models_dir.resolve()
    model_names = []
    for key in ("video_model_dir", "base_model_dir"):
        if key not in parameters:
            continue
        try:
            model_names.append(Path(parameters[key]).resolve().relative_to(models_root).as_posix())
        except ValueError:
            # Explicit BYOM paths outside the catalog retain their local route.
            if settings.allow_local_fallback:
                return None
            raise RuntimeError("Hybrid models must reside under the coordinator models directory")
    selected = None
    observations = []
    for node, wsl in ((settings.remote, False), (settings.wsl_backup, True)):
        if not node.enabled:
            continue
        try:
            transport = LinuxVideoTransport(node, wsl=wsl)
            requested_models = (model_names[0], model_names[1] if parameters["engine"] == "animatediff" else "") if model_names else None
            transport.probe(requested_models)
            selected = transport
            break
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            observations.append(f"{'wsl' if wsl else 'remote'}: {type(exc).__name__}")
    if selected is None:
        if settings.allow_local_fallback:
            return None
        raise RuntimeError("No configured Linux video worker is reachable: " + "; ".join(observations))
    cancel_check = parameters.pop("cancel_check", None)
    if cancel_check:
        cancel_check()
    local_root = Path(parameters.pop("workspace") or parameters["video_model_dir"])
    local = local_root / ".hybrid-video" / uuid.uuid4().hex
    local.mkdir(parents=True)
    remote = f"{selected.node.staging_root}/{local.name}"
    result = subprocess.run(selected.command(["mkdir", "-p", "--", remote]), capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError("Could not create worker attempt staging")
    image = parameters.pop("init_image", None)
    if image is not None:
        image.convert("RGB").save(local / "source.png")
        selected.copy(local / "source.png", f"{remote}/source.png")
    for key, relative in zip(("video_model_dir", "base_model_dir"), model_names, strict=True):
        parameters[key] = f"{selected.node.models_root}/{relative}"
    parameters.update(workspace=remote, init_image=f"{remote}/source.png" if image is not None else None,
                      timeout_seconds=settings.timeout_seconds, device="cuda")
    request = local / "request.json"
    request.write_text(json.dumps(parameters), encoding="utf-8")
    selected.copy(request, f"{remote}/request.json")
    with (local / "worker.log").open("wb") as log:
        process = subprocess.Popen(selected.worker_command("--request", f"{remote}/request.json"), stdout=log, stderr=log)
        deadline = time.monotonic() + settings.timeout_seconds + 30
        try:
            while process.poll() is None:
                if cancel_check:
                    cancel_check()
                if time.monotonic() > deadline:
                    raise TimeoutError("Linux video worker timed out")
                time.sleep(0.5)
            if process.returncode:
                raise RuntimeError(f"Linux video worker failed; attempt log: {local / 'worker.log'}")
        except BaseException:
            try:
                subprocess.run(selected.worker_command("--cancel", f"{remote}/request.json"),
                               capture_output=True, timeout=15, check=False)
            finally:
                process.kill()
                process.wait(timeout=10)
            raise
    if cancel_check:
        cancel_check()
    archive = local / "result.zip"
    selected.copy(archive, f"{remote}/result.zip", download=True)
    frames, receipt = read_frames(archive, expected_frames=parameters["num_frames"], width=parameters["width"], height=parameters["height"], request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    receipt.update(node="wsl" if selected.wsl else "remote", host=selected.node.distro if selected.wsl else selected.node.host,
                   probe_failures=observations)
    (local / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return frames
