"""Disposable native-runtime host. Commands and arrays never use pickle."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .cache import atomic_write


def diagnose(device: int) -> dict:
    import importlib.util
    installed = importlib.util.find_spec("tensorrt") is not None
    result = {"installed": True, "import_ok": False, "runtime_ok": False, "builder_ok": False,
              "engine_test_ok": False, "inference_test_ok": False, "healthy": False, "status": "broken"}
    if not installed:
        result.update(installed=False, status="not_installed", reason="TensorRT Python bindings are absent")
        return result
    try:
        import torch
        import tensorrt as trt
        from .executor import TensorExecutor, identity_engine
        result.update(import_ok=True, version=trt.__version__, cuda=torch.version.cuda)
        result["devices"] = [{"id": i, "name": torch.cuda.get_device_name(i),
            "architecture": list(torch.cuda.get_device_capability(i)),
            "vram_bytes": torch.cuda.get_device_properties(i).total_memory} for i in range(torch.cuda.device_count())]
        if not torch.cuda.is_available():
            result["status"] = "incompatible"
            raise RuntimeError("PyTorch CUDA is unavailable; CPU is not an automatic fallback")
        torch.cuda.set_device(device)
        engine = identity_engine()
        result.update(builder_ok=True, engine_test_ok=True)
        executor = TensorExecutor(engine, device)
        result["runtime_ok"] = True
        value = torch.tensor([[1., 2., -3., 0.5]], device=f"cuda:{device}")
        actual = executor(value)
        if not torch.equal(actual, value * 2):
            raise RuntimeError("Synthetic engine output did not match its reference")
        result.update(inference_test_ok=True, healthy=True, status="ready", tested_device=device)
    except Exception as exc:
        result["reason"] = str(exc)
    return result


def serve(root: Path) -> None:
    import numpy as np
    configuration = json.loads((root / "configuration.json").read_text())
    from .package import activate
    activate(Path(configuration["data_dir"]), configuration.get("package_path", ""))
    executor = None
    manifest = None
    for line in sys.stdin:
        command = json.loads(line)
        sequence = int(command["sequence"])
        response_path = root / f"{sequence}.json"
        try:
            if command["operation"] == "diagnose":
                result = diagnose(int(command.get("device", 0)))
            elif command["operation"] == "prepare":
                from .builder import prepare_component
                executor, manifest, cache_status = prepare_component(
                    Path(configuration["data_dir"]), Path(command["model_dir"]), command["shape"],
                    command["precision"], int(command["device"]), bool(command["allow_build"]),
                    progress=lambda stage: atomic_write(root / "progress.json", json.dumps(stage if isinstance(stage, dict) else {"stage": stage}).encode()))
                result = {"manifest": manifest, "cache": cache_status}
            elif command["operation"] == "execute":
                import torch
                if executor is None:
                    raise RuntimeError("No component has been prepared")
                latent = torch.from_numpy(np.load(root / f"{sequence}-input.npy", allow_pickle=False))
                started = time.perf_counter()
                with torch.inference_mode():
                    output = executor(latent)
                if not torch.isfinite(output).all():
                    raise RuntimeError("TensorRT returned nonfinite component output")
                np.save(root / f"{sequence}-output.npy", output.cpu().numpy(), allow_pickle=False)
                result = {"inference_s": time.perf_counter() - started}
            else:
                raise ValueError("Unknown runtime operation")
            atomic_write(response_path, json.dumps({"ok": True, "result": result}, allow_nan=False).encode())
        except Exception as exc:
            if manifest and command["operation"] == "execute":
                from .cache import EngineCache
                EngineCache(Path(configuration["data_dir"])).quarantine(manifest["engine_id"], str(exc))
            atomic_write(response_path, json.dumps({"ok": False, "error": str(exc)}).encode())


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
