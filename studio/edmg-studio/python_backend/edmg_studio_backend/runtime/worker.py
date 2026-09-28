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
                from .adapters import ComponentAdapterRegistry
                from .cache import build_engine_identity
                from .routes import discover_compilers, resolve_runtime_route
                from .sources import SourceKind, classify_model_source
                adapter = ComponentAdapterRegistry().require(
                    str(command.get("model_family", "sd15")),
                    str(command.get("component", "vae_decoder")),
                )
                model_dir = Path(command["model_dir"])
                source = classify_model_source(
                    model_dir, model_id=adapter.model_id or "", model_family=adapter.model_family,
                    component=adapter.component,
                )
                route = resolve_runtime_route(source, adapter, discover_compilers())
                if not route.supported:
                    raise RuntimeError(route.reason or "TensorRT route is unsupported")
                selected_route = route.selected_route
                selected_compiler = route.compiler
                if source.kind in {SourceKind.PYTORCH_CHECKPOINT, SourceKind.HUGGINGFACE}:
                    import torch
                    import torch_tensorrt
                    import tensorrt as trt
                    torch.cuda.set_device(int(command["device"]))
                    torch_tensorrt.runtime.set_multi_device_safe_mode(True)
                    from .torch_builder import (
                        compile_torch_component, load_cached_torch_component,
                        load_registered_component,
                    )
                    props = torch.cuda.get_device_properties(int(command["device"]))
                    identity = build_engine_identity(
                        source=source, route=route.selected_route, compiler=route.compiler,
                        versions={"torch": torch.__version__, "torch_tensorrt": torch_tensorrt.__version__,
                                  "tensorrt": trt.__version__, "cuda": torch.version.cuda},
                        precision=command["precision"], profile={"input": command["shape"]},
                        device={"compute_capability": f"{props.major}.{props.minor}", "index": int(command["device"])},
                    )
                    input_names = (("latent",) if adapter.component == "vae_decoder" else
                                   ("sample", "timestep", "encoder_hidden_states"))
                    cached = load_cached_torch_component(
                        data_dir=Path(configuration["data_dir"]), identity=identity,
                        input_names=input_names, device=f"cuda:{command['device']}",
                    )
                    if cached:
                        executor, manifest, cache_status = cached
                    else:
                        if not command.get("allow_build"):
                            executor, manifest, cache_status = adapter.prepare(
                                Path(configuration["data_dir"]), model_dir, command["shape"],
                                command["precision"], int(command["device"]), False,
                                validation_limits=command.get("validation_limits"),
                            )
                            selected_route = "huggingface_onnx_tensorrt"
                            selected_compiler = "onnx+tensorrt"
                        else:
                            module, args, kwargs, input_names = load_registered_component(
                                adapter.loader_id or "", model_dir, command["shape"], command["precision"],
                                int(command["device"]), source.kind.value,
                            )
                            with torch.inference_mode():
                                reference = module(*args, **kwargs)
                            def validate(compiled):
                                from .policy import RuntimePolicy
                                from .validation import evaluate_validation, tensor_validation_metrics
                                with torch.inference_mode():
                                    actual = compiled(*args, **kwargs)
                                if hasattr(actual, "sample"):
                                    actual = actual.sample
                                if isinstance(actual, (tuple, list)):
                                    actual = actual[0]
                                limits = command.get("validation_limits") or RuntimePolicy().validation_limits(
                                    command["precision"], adapter.component,
                                )
                                metrics = tensor_validation_metrics(reference, actual)
                                passed, failures = evaluate_validation(metrics, limits)
                                return {
                                    "passed": passed, "failures": failures,
                                    "limits": limits, **metrics,
                                }
                            try:
                                executor, manifest, cache_status = compile_torch_component(
                                    data_dir=Path(configuration["data_dir"]), identity=identity, module=module,
                                    example_args=args, example_kwargs=kwargs, input_names=input_names, validate=validate,
                                )
                            except Exception as exc:
                                if "model is not fully supported" not in str(exc):
                                    raise
                                del module, args, kwargs
                                torch.cuda.empty_cache()
                                executor, manifest, cache_status = adapter.prepare(
                                    Path(configuration["data_dir"]), model_dir, command["shape"],
                                    command["precision"], int(command["device"]), True,
                                    validation_limits=command.get("validation_limits"),
                                    progress=lambda stage: atomic_write(
                                        root / "progress.json",
                                        json.dumps(stage if isinstance(stage, dict) else {"stage": stage}).encode(),
                                    ),
                                )
                                selected_route = "huggingface_onnx_tensorrt"
                                selected_compiler = "onnx+tensorrt"
                elif source.kind is SourceKind.TENSORRT_ENGINE:
                    import torch
                    import tensorrt as trt
                    from .prebuilt import admit_prebuilt_engine
                    engine_path = source.files[0]
                    component = adapter.component
                    expected_inputs = {"latent"} if component == "vae_decoder" else {
                        "sample", "timestep", "encoder_hidden_states",
                    }
                    expected_outputs = {"image"} if component == "vae_decoder" else {"noise_pred"}
                    props = torch.cuda.get_device_properties(int(command["device"]))
                    identity = build_engine_identity(
                        source=source, route=route.selected_route, compiler=route.compiler,
                        versions={"tensorrt": trt.__version__, "cuda": torch.version.cuda},
                        precision=command["precision"], profile={"input": command["shape"]},
                        device={"compute_capability": f"{props.major}.{props.minor}", "index": int(command["device"])},
                    )
                    dtype = torch.float16 if command["precision"] == "fp16" else torch.float32
                    def validate_prebuilt(candidate):
                        if component == "vae_decoder":
                            values = {"latent": torch.zeros(tuple(command["shape"]), device=f"cuda:{command['device']}", dtype=dtype)}
                        else:
                            shape = tuple(command["shape"])
                            values = {
                                "sample": torch.zeros(shape, device=f"cuda:{command['device']}", dtype=dtype),
                                "timestep": torch.tensor([500.0], device=f"cuda:{command['device']}", dtype=dtype),
                                "encoder_hidden_states": torch.zeros((shape[0], 77, 768), device=f"cuda:{command['device']}", dtype=dtype),
                            }
                        outputs = candidate(values)
                        tensors = outputs.values() if isinstance(outputs, dict) else [outputs]
                        passed = all(bool(torch.isfinite(value).all()) for value in tensors)
                        return {"passed": passed, "quality_scope": "prebuilt_binding_shape_finite_execution"}
                    executor, manifest, cache_status = admit_prebuilt_engine(
                        data_dir=Path(configuration["data_dir"]), engine_path=engine_path,
                        identity=identity, device=int(command["device"]),
                        expected_inputs=expected_inputs, expected_outputs=expected_outputs,
                        validate=validate_prebuilt,
                    )
                else:
                    executor, manifest, cache_status = adapter.prepare(
                        Path(configuration["data_dir"]), model_dir, command["shape"],
                        command["precision"], int(command["device"]), bool(command["allow_build"]),
                        validation_limits=command.get("validation_limits"),
                        progress=lambda stage: atomic_write(root / "progress.json", json.dumps(stage if isinstance(stage, dict) else {"stage": stage}).encode()))
                result = {"manifest": manifest, "cache": cache_status,
                          "source_kind": source.kind.value, "selected_route": selected_route,
                          "compiler": selected_compiler}
            elif command["operation"] == "execute":
                import torch
                if executor is None:
                    raise RuntimeError("No component has been prepared")
                input_names = command.get("input_names")
                if input_names:
                    values = {
                        name: torch.from_numpy(
                            np.load(root / f"{sequence}-input-{index}.npy", allow_pickle=False)
                        )
                        for index, name in enumerate(input_names)
                    }
                else:
                    values = torch.from_numpy(np.load(root / f"{sequence}-input.npy", allow_pickle=False))
                started = time.perf_counter()
                with torch.inference_mode():
                    output = executor(values)
                result = {"inference_s": time.perf_counter() - started}
                if isinstance(output, dict):
                    result["output_names"] = list(output)
                    for index, (name, value) in enumerate(output.items()):
                        if not torch.isfinite(value).all():
                            raise RuntimeError(f"TensorRT returned nonfinite output for {name!r}")
                        np.save(root / f"{sequence}-output-{index}.npy", value.cpu().numpy(), allow_pickle=False)
                else:
                    if not torch.isfinite(output).all():
                        raise RuntimeError("TensorRT returned nonfinite component output")
                    np.save(root / f"{sequence}-output.npy", output.cpu().numpy(), allow_pickle=False)
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
