"""One explicitly supported component: the unmodified SD1.5 AutoencoderKL decoder."""
from __future__ import annotations

import importlib.metadata
import json
import time
from pathlib import Path

from .cache import EngineCache, digest_file, engine_key
from .executor import TensorExecutor
from .resources import require_build_memory, workspace_bytes
from .validation import (
    VALIDATION_SCHEMA,
    aggregate_validation_metrics,
    default_validation_limits,
    evaluate_validation,
    tensor_validation_metrics,
)

ADAPTER_VERSION = 3


def component_identity(
    model_dir: Path,
    shape: list[int],
    precision: str,
    device: int,
    compiler: str,
    selected_workspace_bytes: int,
) -> dict:
    import torch
    import tensorrt as trt
    root = model_dir / "vae"
    config = root / "config.json"
    weights = sorted(root.glob("*.safetensors"))
    if not config.is_file() or not weights:
        raise RuntimeError("SD1.5 VAE configuration and safetensors weights are required")
    settings = json.loads(config.read_text())
    if settings.get("_class_name") != "AutoencoderKL" or settings.get("latent_channels") != 4:
        raise RuntimeError("This VAE has not declared support for the SD1.5 decoder adapter")
    if len(shape) != 4 or shape[0] != 1 or shape[1] != 4 or not all(8 <= v <= 128 for v in shape[2:]):
        raise RuntimeError("Supported VAE profiles: batch 1, four channels, 64 to 1024 output pixels per axis")
    props = torch.cuda.get_device_properties(device)
    return {"model": "sd15", "model_id": model_dir.name,
            "component": "vae_decoder", "weights": {p.name: digest_file(p) for p in weights},
            "config_sha256": digest_file(config), "tensorrt": trt.__version__, "cuda": torch.version.cuda,
            "torch": torch.__version__, "gpu_arch": f"sm{props.major}{props.minor}",
            "gpu_name": props.name, "gpu_uuid": str(getattr(props, "uuid", device)),
            "precision": precision, "profile": {"input": shape}, "compiler": compiler,
            "compiler_settings": {
                "workspace_bytes": selected_workspace_bytes,
                "tf32": False,
                **({"onnx": importlib.metadata.version("onnx")} if compiler == "onnx" else {}),
            },
            "diffusers": importlib.metadata.version("diffusers"), "plugins": {},
            "mutations": {"lora": [], "controlnet": [], "ip_adapter": [], "refit": False},
            "adapter_version": ADAPTER_VERSION}


def prepare_component(data_dir: Path, model_dir: Path, shape: list[int], precision: str,
                      device: int, allow_build: bool,
                      validation_limits: dict | None = None,
                      progress=lambda stage: None):
    import torch
    import tensorrt as trt
    # Prefer the already-installed Torch-TensorRT combination when compatible.
    compiler = "onnx"
    try:
        version = importlib.metadata.version("torch-tensorrt")
        if int(trt.__version__.split(".")[0]) == 10 and version.split("+")[0] == torch.__version__.split("+")[0]:
            compiler = "torch_tensorrt:" + version
    except importlib.metadata.PackageNotFoundError:
        pass
    selected_workspace_bytes = workspace_bytes(torch, device)
    identity = component_identity(model_dir, shape, precision, device, compiler, selected_workspace_bytes)
    cache = EngineCache(data_dir)
    key = engine_key(identity)
    with cache.lock(key, timeout_s=1800):
        found = cache.lookup(identity)
        if found:
            path, manifest = found
            progress({"stage": "loading_engine", "engine_id": key})
            try:
                return TensorExecutor(path.read_bytes(), device), manifest, "hit"
            except Exception as exc:
                cache.quarantine(key, str(exc))
                raise
        previous = cache.read(key)
        if previous and previous.get("state") in {"failed", "quarantined"}:
            raise RuntimeError("Engine is disabled after a previous failure; clear it to retry")
        if not allow_build:
            raise RuntimeError("No validated engine for this profile; compilation is disabled by policy")
        require_build_memory(torch, device, selected_workspace_bytes)
        cache.state(key, identity, "building")
        try:
            from diffusers import AutoencoderKL
            dtype = torch.float16 if precision == "fp16" else torch.float32
            torch.cuda.set_device(device)
            progress("loading_reference")
            vae = AutoencoderKL.from_pretrained(str(model_dir / "vae"), local_files_only=True,
                                                use_safetensors=True, torch_dtype=dtype).to(f"cuda:{device}").eval()

            class Decoder(torch.nn.Module):
                def __init__(self, module):
                    super().__init__()
                    self.vae = module

                def forward(self, latent):
                    return self.vae.decode(latent, return_dict=False)[0]

            module = Decoder(vae).eval()
            generator = torch.Generator(device=f"cuda:{device}").manual_seed(1729)
            sample = torch.randn(shape, generator=generator, device=f"cuda:{device}", dtype=dtype)
            progress("exporting")
            started = time.perf_counter()
            with torch.inference_mode():
                if compiler.startswith("torch_tensorrt"):
                    import torch_tensorrt
                    exported = torch.export.export(module, (sample,))
                    progress("building")
                    engine = torch_tensorrt.dynamo.convert_exported_program_to_serialized_trt_engine(
                        exported, arg_inputs=[sample], device=f"cuda:{device}",
                        workspace_size=selected_workspace_bytes, disable_tf32=True,
                        use_explicit_typing=True)
                else:
                    graph = cache.directory(key) / "decoder.onnx"
                    try:
                        torch.onnx.export(module, (sample,), str(graph), input_names=["latent"],
                                          output_names=["image"], opset_version=18, dynamo=False)
                        logger = trt.Logger(trt.Logger.WARNING)
                        builder = trt.Builder(logger)
                        flags = 0 if int(trt.__version__.split(".")[0]) >= 11 else 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
                        network = builder.create_network(flags)
                        parser = trt.OnnxParser(network, logger)
                        if not parser.parse_from_file(str(graph)):
                            raise RuntimeError("TensorRT ONNX parse failed: " + str(parser.get_error(0)))
                        config = builder.create_builder_config()
                        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, selected_workspace_bytes)
                        progress("building")
                        serialized = builder.build_serialized_network(network, config)
                        engine = bytes(serialized) if serialized is not None else None
                    finally:
                        graph.unlink(missing_ok=True)
                if not engine:
                    raise RuntimeError("Component compiler produced no engine")
                build_s = time.perf_counter() - started
                cache.state(key, identity, "validating")
                progress("validating")
                executor = TensorExecutor(bytes(engine), device)
                validation_rows = []
                fixed_seeds = (1729, 42, 7)
                for seed in fixed_seeds:
                    generator.manual_seed(seed)
                    latent = torch.randn(shape, generator=generator, device=sample.device, dtype=dtype)
                    reference = module(latent)
                    actual = executor(latent)
                    validation_rows.append({
                        "seed": seed,
                        **tensor_validation_metrics(reference, actual),
                    })

                limits = dict(validation_limits or default_validation_limits(precision))
                validation = aggregate_validation_metrics(validation_rows)
                passed, failures = evaluate_validation(validation, limits)
                validation.update({
                    "passed": passed,
                    "validation_schema": VALIDATION_SCHEMA,
                    "limits": limits,
                    "fixed_seeds": list(fixed_seeds),
                    "quality_scope": "component_numeric_plus_image_statistics",
                    "failures": failures,
                    "max_relative_error_is_diagnostic_only": True,
                })

                if not passed:
                    cache.state(
                        key,
                        identity,
                        "failed",
                        reason="VAE numerical validation failed",
                        validation=validation,
                    )
                    raise RuntimeError(
                        "VAE numerical validation failed: "
                        + json.dumps(
                            {
                                "max": validation["max_absolute_error"],
                                "mean": validation["mean_absolute_error"],
                                "rmse": validation["rmse"],
                                "p99": validation["p99_absolute_error"],
                                "psnr_db": validation["psnr_db"],
                                "ssim_global": validation["ssim_global"],
                                "failures": failures,
                            },
                            sort_keys=True,
                        )
                    )
                progress("benchmarking")
                timings = {}
                for name, fn in (("pytorch_s", module), ("tensorrt_s", executor)):
                    fn(sample)
                    torch.cuda.synchronize(device)
                    start = time.perf_counter()
                    for _ in range(5):
                        fn(sample)
                    torch.cuda.synchronize(device)
                    timings[name] = (time.perf_counter() - start) / 5
                timings["build_s"] = build_s
                timings["beneficial"] = timings["tensorrt_s"] < timings["pytorch_s"] * 0.95
                manifest = cache.publish(identity, bytes(engine), validation, timings)
            del module, vae
            torch.cuda.empty_cache()
            return executor, manifest, "built"
        except Exception as exc:
            previous = cache.read(key) or {}
            detail = {}
            if isinstance(previous.get("validation"), dict):
                detail["validation"] = previous["validation"]
            cache.state(key, identity, "failed", reason=str(exc), **detail)
            raise
