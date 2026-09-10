"""Qwen3-VL Director adapter backed by a managed llama-server process."""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import requests

from ..domain.director_scene import DirectorDocument
from .model_load_coordinator import ModelLoadCanceled

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str, str], None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlamaServerProbe:
    executable: Path
    version: str
    cuda_devices: tuple[str, ...]
    identity: str


@dataclass(frozen=True)
class LlamaLaunchPlan:
    device: str
    gpu_layers: int
    context_length: int
    batch_size: int
    ubatch_size: int
    cuda_graphs: bool
    hybrid: bool


def probe_llama_server(executable: Path) -> LlamaServerProbe:
    executable = executable.resolve(strict=True)
    version_result = subprocess.run(
        [str(executable), "--version"], check=False, capture_output=True, text=True, timeout=30,
    )
    version = (version_result.stdout or version_result.stderr).strip().splitlines()
    device_result = subprocess.run(
        [str(executable), "--list-devices"], check=False, capture_output=True, text=True, timeout=30,
    )
    if device_result.returncode != 0:
        raise RuntimeError(
            f"llama.cpp device probe failed for {executable}: "
            f"{(device_result.stderr or device_result.stdout).strip()}"
        )
    lines = [line.strip() for line in (device_result.stdout + "\n" + device_result.stderr).splitlines()]
    devices = tuple(line for line in lines if line.lower().startswith("cuda") and ":" in line)
    stat = executable.stat()
    identity = f"{executable}:{stat.st_size}:{stat.st_mtime_ns}:{version[0] if version else 'unknown'}"
    return LlamaServerProbe(executable, version[0] if version else "unknown", devices, identity)


def discover_qwen_gguf(package_root: Path) -> tuple[Path, Path]:
    root = package_root.resolve(strict=True)
    files = sorted(path for path in root.glob("*.gguf") if path.is_file())
    models = [path for path in files if not path.name.lower().startswith("mmproj-")]
    projectors = [path for path in files if path.name.lower().startswith("mmproj-")]
    if len(models) != 1:
        raise RuntimeError("Qwen3-VL package must contain exactly one main GGUF model.")
    if len(projectors) != 1:
        raise RuntimeError("Qwen3-VL package must contain exactly one multimodal projector GGUF.")

    def normalized(path: Path) -> str:
        return path.name.lower().replace("-", "").replace("_", "")

    if "qwen3vl" not in normalized(models[0]) or "qwen3vl" not in normalized(projectors[0]):
        raise RuntimeError("The GGUF model and projector are not a Qwen3-VL pair.")
    model_size = "30b" if "30b" in normalized(models[0]) else "8b" if "8b" in normalized(models[0]) else ""
    projector_size = "30b" if "30b" in normalized(projectors[0]) else "8b" if "8b" in normalized(projectors[0]) else ""
    if model_size and projector_size and model_size != projector_size:
        raise RuntimeError("The Qwen3-VL model and multimodal projector sizes do not match.")
    return models[0], projectors[0]


def resolve_llama_server(configured_path: str | Path | None = None) -> Path:
    explicit = str(configured_path or os.getenv("EDMG_LLAMA_SERVER", "")).strip()
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise RuntimeError(f"Configured llama.cpp runtime does not exist: {path}")
        return path.resolve()
    studio_home = os.getenv("EDMG_STUDIO_HOME", "").strip()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    candidates = [
        str(Path(studio_home) / "tools" / "llama.cpp" / "llama-server.exe") if studio_home else None,
        str(Path(__file__).resolve().parents[2] / "tools" / "llama.cpp" / "llama-server.exe"),
        str(Path(local_app_data) / "EDMG Studio" / "tools" / "llama.cpp" / "llama-server.exe")
        if local_app_data else None,
        shutil.which("llama-server.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError(
        "llama.cpp runtime unavailable. Install the pinned CUDA llama-server build or set "
        "EDMG_LLAMA_SERVER to llama-server.exe."
    )


def select_gpu_layers(*, model_bytes: int, vram_gb: float, requested: str | int = "auto") -> int:
    if str(requested).strip().lower() not in {"", "auto"}:
        value = int(requested)
        if value < 0:
            raise ValueError("GPU layers must be 'auto' or a non-negative integer.")
        return value
    if vram_gb <= 0 or model_bytes <= 0:
        return 0
    # Reserve at least 2.5 GiB for CUDA, KV cache, the projector, display use, and Studio.
    usable_gib = max(0.0, min(vram_gb * 0.60, vram_gb - 2.5))
    model_gib = model_bytes / 1024**3
    estimated_layers = 36 if model_gib < 8 else 64
    return max(0, min(estimated_layers - 1, int(estimated_layers * usable_gib / model_gib)))


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _check_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise ModelLoadCanceled("Director generation canceled")


def _image_content(image_paths: list[str] | None) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for value in image_paths or []:
        path = Path(value).resolve(strict=True)
        suffix = path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else None
        if mime is None:
            raise ValueError(f"Unsupported Director reference image type: {suffix or 'unknown'}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    return content


class LlamaCppDirectorBackend:
    def __init__(
        self,
        package_root: Path,
        *,
        device: str = "cpu",
        gpu_layers: str | int = "auto",
        context_length: int = 8192,
        batch_size: int = 64,
        ubatch_size: int = 16,
        cuda_graphs: bool = False,
        vram_gb: float = 0,
        executable: Path | None = None,
        timeout_s: float = 180.0,
    ) -> None:
        self.model_path, self.projector_path = discover_qwen_gguf(package_root)
        self.executable = executable.resolve(strict=True) if executable else resolve_llama_server()
        self.device = device.strip().lower()
        self.requested_gpu_layers = gpu_layers
        self.context_length = int(context_length)
        self.batch_size = int(batch_size)
        self.ubatch_size = int(ubatch_size)
        self.cuda_graphs = bool(cuda_graphs)
        self.vram_gb = float(vram_gb)
        self.timeout_s = float(timeout_s)
        self.process: subprocess.Popen[str] | None = None
        self.base_url = ""
        self._process_env: dict[str, str] | None = None
        self._output: list[str] = []
        self._attempt = 0
        if self.device != "cpu" and not self.device.startswith("cuda:"):
            raise ValueError("llama.cpp device must be 'cpu' or 'cuda:N'.")
        if self.context_length < 8192:
            raise ValueError("Qwen3-VL multimodal inference requires a context length of at least 8192.")
        if self.batch_size < 1 or self.ubatch_size < 1 or self.ubatch_size > self.batch_size:
            raise ValueError("llama.cpp batch sizes must be positive and ubatch must not exceed batch size.")
        layers = 0 if self.device == "cpu" else select_gpu_layers(
            model_bytes=self.model_path.stat().st_size, vram_gb=self.vram_gb, requested=gpu_layers,
        )
        self.plan = LlamaLaunchPlan(
            self.device, layers, self.context_length, self.batch_size, self.ubatch_size,
            self.cuda_graphs, self.device != "cpu" and layers > 0,
        )

    @property
    def gpu_layers(self) -> str:
        return str(self.plan.gpu_layers)

    def launch_configuration(self) -> dict[str, Any]:
        return {"executable": str(self.executable), **asdict(self.plan)}

    def _cuda_environment(self) -> dict[str, str]:
        index = int(self.device.split(":", 1)[1])
        probe = subprocess.run(
            [str(self.executable), "--list-devices"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            raise RuntimeError(f"llama.cpp CUDA device detection failed: {(probe.stderr or probe.stdout).strip()}")
        lines = [line.strip() for line in (probe.stdout + "\n" + probe.stderr).splitlines()]
        names = [line.split(":", 1)[0].strip() for line in lines if line.lower().startswith("cuda") and ":" in line]
        if index >= len(names):
            raise RuntimeError(f"llama.cpp CUDA backend does not expose requested device {self.device}.")
        environment = os.environ.copy()
        environment["CUDA_VISIBLE_DEVICES"] = str(index)
        return environment

    @staticmethod
    def _retryable_cuda_error(output: str) -> bool:
        value = output.lower()
        return any(token in value for token in (
            "out of memory", "failed to allocate", "allocation failed", "cuda error",
            "illegal memory access", "cublas_status_alloc_failed",
        ))

    def _fallback_plans(self) -> list[LlamaLaunchPlan]:
        plans = [self.plan]
        if self.plan.device == "cpu":
            return plans
        reduced = max(1, self.plan.gpu_layers // 2) if self.plan.gpu_layers else 0
        plans.append(replace(
            self.plan, gpu_layers=reduced, batch_size=max(16, self.plan.batch_size // 2),
            ubatch_size=max(8, min(self.plan.ubatch_size // 2, max(16, self.plan.batch_size // 2))),
            cuda_graphs=False, hybrid=reduced > 0,
        ))
        if reduced > 1:
            plans.append(replace(plans[-1], gpu_layers=max(1, reduced // 2)))
        plans.append(LlamaLaunchPlan("cpu", 0, self.context_length, 16, 8, False, False))
        unique: list[LlamaLaunchPlan] = []
        for plan in plans:
            if plan not in unique:
                unique.append(plan)
        return unique[:4]

    def _drain_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._output.append(line.rstrip())
                del self._output[:-200]
        except TypeError:
            return

    def _start_plan(self, plan: LlamaLaunchPlan, cancel_check: CancelCheck | None) -> None:
        self.plan = plan
        _check_cancelled(cancel_check)
        port = _free_loopback_port()
        command = [
            str(self.executable), "-m", str(self.model_path), "--mmproj", str(self.projector_path),
            "--ctx-size", str(self.context_length), "--host", "127.0.0.1", "--port", str(port),
            "--parallel", "1", "--batch-size", str(plan.batch_size), "--ubatch-size", str(plan.ubatch_size),
            "--flash-attn", "off", "--cache-ram", "0", "--split-mode", "none",
            "--n-gpu-layers", str(plan.gpu_layers),
        ]
        if plan.device != "cpu":
            self._process_env = self._cuda_environment()
            self._process_env["GGML_CUDA_DISABLE_GRAPHS"] = "0" if plan.cuda_graphs else "1"
            command.extend(["--device", "CUDA0", "--main-gpu", "0", "--no-mmproj-offload"])
        else:
            self._process_env = os.environ.copy()
            command.append("--no-mmproj-offload")
        self.process = subprocess.Popen(
            command,
            env=self._process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._drain_output, args=(self.process,), daemon=True).start()
        self.base_url = f"http://127.0.0.1:{port}"
        logger.info(
            "Starting Internal Director executable=%s model=%s projector=%s device=%s vram_gb=%.2f "
            "context=%d batch=%d ubatch=%d gpu_layers=%d hybrid=%s cuda_graphs=%s",
            self.executable, self.model_path, self.projector_path, plan.device, self.vram_gb,
            plan.context_length, plan.batch_size, plan.ubatch_size, plan.gpu_layers, plan.hybrid,
            plan.cuda_graphs,
        )
        deadline = time.monotonic() + self.timeout_s
        try:
            while time.monotonic() < deadline:
                _check_cancelled(cancel_check)
                if self.process.poll() is not None:
                    output = "\n".join(self._output)
                    raise RuntimeError(f"llama.cpp model load failed: {output[-2000:].strip()}")
                try:
                    response = requests.get(f"{self.base_url}/health", timeout=1)
                    if response.status_code == 200:
                        return
                except requests.RequestException:
                    pass
                time.sleep(0.1)
            raise TimeoutError("llama.cpp timed out while loading the Qwen3-VL model and projector.")
        except BaseException:
            self.close()
            raise

    def start(self, *, cancel_check: CancelCheck | None = None) -> None:
        if self.process is not None:
            return
        last_error: BaseException | None = None
        for attempt, plan in enumerate(self._fallback_plans(), start=1):
            self._attempt = attempt
            try:
                self._start_plan(plan, cancel_check)
                return
            except ModelLoadCanceled:
                raise
            except (RuntimeError, TimeoutError) as exc:
                last_error = exc
                output = str(exc)
                if (
                    not self._retryable_cuda_error(output)
                    or plan.device == "cpu"
                    or ("illegal memory access" in output.lower() and not plan.cuda_graphs)
                ):
                    raise
                logger.warning("Director CUDA attempt %d failed; retrying safer plan: %s", attempt, exc)
        if last_error:
            raise last_error

    def generate(
        self,
        document: DirectorDocument,
        instruction: str,
        *,
        image_paths: list[str] | None = None,
        max_tokens: int = 4096,
        cancel_check: CancelCheck | None = None,
    ) -> str:
        from .qwen_director import planning_messages

        _check_cancelled(cancel_check)
        if self.process is None:
            raise RuntimeError("llama.cpp Director backend is not initialized.")
        messages = planning_messages(document, instruction)
        messages[-1]["content"] = _image_content(image_paths) + messages[-1]["content"]
        payload = {"model": self.model_path.name, "messages": messages, "max_tokens": max_tokens, "stream": True, "temperature": 0}
        plans = self._fallback_plans()
        last_error: BaseException | None = None
        for index, plan in enumerate(plans):
            try:
                if index:
                    self.close()
                    logger.warning(
                        "Retrying Director inference with device=%s gpu_layers=%d batch=%d ubatch=%d cuda_graphs=%s",
                        plan.device, plan.gpu_layers, plan.batch_size, plan.ubatch_size, plan.cuda_graphs,
                    )
                    self._start_plan(plan, cancel_check)
                return self._generate_once(payload, cancel_check)
            except (RuntimeError, TimeoutError) as exc:
                last_error = exc
                diagnostics = f"{exc}\n{' '.join(self._output[-40:])}"
                if (
                    plan.device == "cpu"
                    or not self._retryable_cuda_error(diagnostics)
                    or ("illegal memory access" in diagnostics.lower() and not plan.cuda_graphs)
                ):
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("llama.cpp Director inference exhausted all launch plans.")

    def _generate_once(self, payload: dict[str, Any], cancel_check: CancelCheck | None) -> str:
        try:
            with requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=(5, self.timeout_s),
            ) as response:
                response.raise_for_status()
                chunks: list[str] = []
                for line in response.iter_lines(decode_unicode=True):
                    _check_cancelled(cancel_check)
                    if not line or not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    chunks.append(str(event.get("choices", [{}])[0].get("delta", {}).get("content") or ""))
                text = "".join(chunks).strip()
                if not text:
                    raise RuntimeError("llama.cpp returned an empty Director response.")
                return text
        except requests.Timeout as exc:
            raise TimeoutError("llama.cpp Director inference timed out.") from exc
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            detail = str(getattr(response, "text", "") or "").strip()
            raise RuntimeError(
                f"llama.cpp Director inference failed: {exc}{f': {detail[-2000:]}' if detail else ''}"
            ) from exc

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def __enter__(self) -> LlamaCppDirectorBackend:
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
