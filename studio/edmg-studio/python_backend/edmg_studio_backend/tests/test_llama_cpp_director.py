from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from edmg_studio_backend.domain.director_scene import DirectorDocument
from edmg_studio_backend.services import llama_cpp_director, qwen_director
from edmg_studio_backend.services.llama_cpp_director import (
    LlamaCppDirectorBackend,
    discover_qwen_gguf,
    resolve_llama_server,
    select_gpu_layers,
)
from edmg_studio_backend.services.model_load_coordinator import ModelLoadCanceled


def _document() -> DirectorDocument:
    return DirectorDocument.model_validate({
        "scenes": [{"scene_id": "one", "start_sample": "0", "end_sample": "48000", "intent": "Black frame"}]
    })


def _package(tmp_path, *, size="8B"):
    model = tmp_path / f"Qwen3VL-{size}-Instruct-Q4_K_M.gguf"
    projector = tmp_path / f"mmproj-Qwen3VL-{size}-Instruct-Q8_0.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")
    runtime = tmp_path / "llama-server.exe"
    runtime.write_bytes(b"runtime")
    return model, projector, runtime


def test_discovery_requires_one_matching_model_and_projector(tmp_path):
    model, projector, _runtime = _package(tmp_path)
    assert discover_qwen_gguf(tmp_path) == (model, projector)
    projector.rename(tmp_path / "mmproj-Qwen3VL-30B-Instruct-Q8_0.gguf")
    with pytest.raises(RuntimeError, match="sizes do not match"):
        discover_qwen_gguf(tmp_path)


def test_start_isolates_requested_cuda_device_and_loads_projector(tmp_path, monkeypatch):
    model, projector, runtime = _package(tmp_path)
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(runtime))
    commands = []

    class Process:
        stdout = SimpleNamespace(read=lambda: "")

        def __init__(self, command, **kwargs):
            commands.append((command, kwargs))

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(llama_cpp_director.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="CUDA0: NVIDIA RTX A6000\nCUDA1: NVIDIA RTX A6000", stderr="",
    ))
    monkeypatch.setattr(llama_cpp_director.subprocess, "Popen", Process)
    monkeypatch.setattr(llama_cpp_director.requests, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=200))
    backend = LlamaCppDirectorBackend(tmp_path, device="cuda:1")
    backend.start()
    command, kwargs = commands[0]
    assert command[command.index("-m") + 1] == str(model)
    assert command[command.index("--mmproj") + 1] == str(projector)
    assert command[command.index("--device") + 1] == "CUDA0"
    assert command[command.index("--parallel") + 1] == "1"
    assert command[command.index("--batch-size") + 1] == "64"
    assert command[command.index("--ubatch-size") + 1] == "16"
    assert command[command.index("--flash-attn") + 1] == "off"
    assert command[command.index("--cache-ram") + 1] == "0"
    assert "--no-mmproj-offload" in command
    assert command[command.index("--split-mode") + 1] == "none"
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert kwargs["env"]["GGML_CUDA_DISABLE_GRAPHS"] == "1"
    backend.close()


def test_auto_gpu_layers_are_partial_on_six_gib_and_manual_override_wins():
    model_bytes = 5 * 1024**3
    automatic = select_gpu_layers(model_bytes=model_bytes, vram_gb=6, requested="auto")
    assert 0 < automatic < 36
    assert select_gpu_layers(model_bytes=model_bytes, vram_gb=6, requested=7) == 7
    with pytest.raises(ValueError, match="non-negative"):
        select_gpu_layers(model_bytes=model_bytes, vram_gb=6, requested=-1)


def test_runtime_discovery_prefers_explicit_existing_path(tmp_path, monkeypatch):
    runtime = tmp_path / "llama-server.exe"
    runtime.write_bytes(b"runtime")
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(runtime))
    assert resolve_llama_server() == runtime.resolve()
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(tmp_path / "missing.exe"))
    with pytest.raises(RuntimeError, match="does not exist"):
        resolve_llama_server()


def test_runtime_discovery_prefers_configured_path_over_environment(tmp_path, monkeypatch):
    configured = tmp_path / "configured" / "llama-server.exe"
    configured.parent.mkdir()
    configured.write_bytes(b"configured")
    environment = tmp_path / "environment" / "llama-server.exe"
    environment.parent.mkdir()
    environment.write_bytes(b"environment")
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(environment))

    assert resolve_llama_server(configured) == configured.resolve()


def test_memory_failure_produces_bounded_hybrid_then_cpu_fallbacks(tmp_path, monkeypatch):
    _model, _projector, runtime = _package(tmp_path)
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(runtime))
    backend = LlamaCppDirectorBackend(tmp_path, device="cuda:0", gpu_layers=12, vram_gb=6)
    plans = backend._fallback_plans()
    assert len(plans) <= 4
    assert [plan.gpu_layers for plan in plans] == [12, 6, 3, 0]
    assert plans[-1].device == "cpu"
    assert plans[1].batch_size < plans[0].batch_size


def test_generation_memory_failure_restarts_with_safer_plan(tmp_path, monkeypatch):
    _model, _projector, runtime = _package(tmp_path)
    backend = LlamaCppDirectorBackend(
        tmp_path, executable=runtime, device="cuda:0", gpu_layers=12, vram_gb=6,
    )
    starts = []
    responses = iter([RuntimeError("CUDA out of memory"), "ok"])

    def generate_once(_payload, _cancel):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(backend, "_start_plan", lambda plan, _cancel: starts.append(plan))
    monkeypatch.setattr(backend, "close", lambda: setattr(backend, "process", None))
    monkeypatch.setattr(backend, "_generate_once", generate_once)
    backend.process = SimpleNamespace()

    assert backend.generate(_document(), "Return JSON") == "ok"
    assert [plan.gpu_layers for plan in starts] == [6]


def test_generate_sends_real_image_and_honors_cancellation(tmp_path, monkeypatch):
    _model, _projector, runtime = _package(tmp_path)
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    monkeypatch.setenv("EDMG_LLAMA_SERVER", str(runtime))
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=True):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": _document().model_dump_json()}}]})
            yield "data: [DONE]"

    def post(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(llama_cpp_director.requests, "post", post)
    backend = LlamaCppDirectorBackend(tmp_path)
    backend.process = SimpleNamespace(poll=lambda: None)
    backend.base_url = "http://127.0.0.1:1234"
    assert backend.generate(_document(), "Inspect", image_paths=[str(image)])
    content = captured["json"]["messages"][-1]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    with pytest.raises(ModelLoadCanceled):
        backend.generate(_document(), "Inspect", cancel_check=lambda: True)


def test_worker_routes_both_gguf_sizes_through_common_backend(tmp_path, monkeypatch):
    _package(tmp_path, size="30B")
    calls = []

    class Backend:
        device = "cpu"

        def __init__(self, root, **kwargs):
            calls.append(("init", root, kwargs))

        def start(self, **kwargs):
            calls.append(("start", kwargs))

        def generate(self, document, instruction, **kwargs):
            calls.append(("generate", instruction, kwargs))
            return document.model_dump_json()

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(llama_cpp_director, "LlamaCppDirectorBackend", Backend)
    payload = {
        "model_id": "hf_qwen3_vl_30b_gguf_director",
        "document": _document().model_dump(mode="json"),
        "instruction": "Add motion",
        "source_revision": 7,
        "device": "cpu",
        "runtime_path": str(tmp_path / "llama-server.exe"),
        "gpu_layers": "5",
        "context_length": 12288,
        "batch_size": 32,
        "ubatch_size": 8,
        "cuda_graphs": True,
        "vram_gb": 6,
    }
    result = qwen_director.run_director_job(
        payload, SimpleNamespace(installed_path=lambda _model_id: tmp_path),
    )
    assert result["status"] == "draft"
    assert result["provenance"]["runtime"] == "llama-server"
    init_options = calls[0][2]
    assert init_options["executable"] == tmp_path / "llama-server.exe"
    assert init_options["gpu_layers"] == "5"
    assert init_options["context_length"] == 12288
    assert init_options["batch_size"] == 32
    assert init_options["ubatch_size"] == 8
    assert init_options["cuda_graphs"] is True
    assert init_options["vram_gb"] == 6
    assert [call[0] for call in calls] == ["init", "start", "generate", "close"]
