"""Qwen3-VL Director adapter backed by a managed llama-server process."""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from ..domain.director_scene import DirectorDocument
from .model_load_coordinator import ModelLoadCanceled

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str, str], None]


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


def resolve_llama_server() -> Path:
    candidates = [
        os.getenv("EDMG_LLAMA_SERVER"),
        str(Path(os.getenv("EDMG_STUDIO_HOME", "")) / "tools" / "llama.cpp" / "llama-server.exe")
        if os.getenv("EDMG_STUDIO_HOME") else None,
        str(Path(__file__).resolve().parents[2] / "tools" / "llama.cpp" / "llama-server.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError(
        "llama.cpp runtime unavailable. Install the pinned CUDA llama-server build or set "
        "EDMG_LLAMA_SERVER to llama-server.exe."
    )


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
        gpu_layers: str | int = "all",
        context_length: int = 8192,
        timeout_s: float = 180.0,
    ) -> None:
        self.model_path, self.projector_path = discover_qwen_gguf(package_root)
        self.executable = resolve_llama_server()
        self.device = device.strip().lower()
        self.gpu_layers = str(gpu_layers)
        self.context_length = int(context_length)
        self.timeout_s = float(timeout_s)
        self.process: subprocess.Popen[str] | None = None
        self.base_url = ""
        self._process_env: dict[str, str] | None = None
        if self.device != "cpu" and not self.device.startswith("cuda:"):
            raise ValueError("llama.cpp device must be 'cpu' or 'cuda:N'.")
        if self.context_length < 8192:
            raise ValueError("Qwen3-VL multimodal inference requires a context length of at least 8192.")

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

    def start(self, *, cancel_check: CancelCheck | None = None) -> None:
        _check_cancelled(cancel_check)
        if self.process is not None:
            return
        port = _free_loopback_port()
        command = [
            str(self.executable), "-m", str(self.model_path), "--mmproj", str(self.projector_path),
            "--ctx-size", str(self.context_length), "--host", "127.0.0.1", "--port", str(port),
            "--parallel", "1", "--batch-size", "128", "--ubatch-size", "32",
            "--flash-attn", "off", "--cache-ram", "0", "--split-mode", "none",
            "--n-gpu-layers", "0" if self.device == "cpu" else self.gpu_layers,
        ]
        if self.device != "cpu":
            self._process_env = self._cuda_environment()
            self._process_env["GGML_CUDA_DISABLE_GRAPHS"] = "1"
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
        self.base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + self.timeout_s
        try:
            while time.monotonic() < deadline:
                _check_cancelled(cancel_check)
                if self.process.poll() is not None:
                    output = self.process.stdout.read() if self.process.stdout else ""
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
            raise RuntimeError(f"llama.cpp Director inference failed: {exc}") from exc

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
