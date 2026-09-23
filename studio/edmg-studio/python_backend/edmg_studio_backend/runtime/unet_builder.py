"""Managed SD1.5 UNet TensorRT build, validation, and cache integration."""
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

ADAPTER_VERSION = 2
CONTEXT_TOKENS = 77


def component_identity(
    model_dir: Path,
    profile: dict,
    precision: str,
    device: int,
    workspace_bytes: int,
) -> dict:
    import torch
    import tensorrt as trt

    root = model_dir / "unet"
    config = root / "config.json"
    weights = sorted(root.glob("*.safetensors"))
    if not config.is_file() or not weights:
        raise RuntimeError("SD1.5 UNet configuration and safetensors weights are required")
    settings = json.loads(config.read_text())
    if settings.get("_class_name") != "UNet2DConditionModel":
        raise RuntimeError("This model has not declared support for the SD1.5 UNet adapter")
    if int(settings.get("in_channels", 0)) != 4 or int(settings.get("cross_attention_dim", 0)) != 768:
        raise RuntimeError("The managed UNet does not match the SD1.5 four-channel/768-context contract")
    props = torch.cuda.get_device_properties(device)
    return {
        "model": "sd15",
        "model_id": model_dir.name,
        "component": "unet",
        "weights": {path.name: digest_file(path) for path in weights},
        "config_sha256": digest_file(config),
        "tensorrt": trt.__version__,
        "cuda": torch.version.cuda,
        "torch": torch.__version__,
        "gpu_arch": f"sm{props.major}{props.minor}",
        "gpu_name": props.name,
        "gpu_uuid": str(getattr(props, "uuid", device)),
        "precision": precision,
        "profile": profile,
        "compiler": "onnx",
        "compiler_settings": {
            "workspace_bytes": workspace_bytes,
            "tf32": False,
            "opset": 18,
            "onnx": importlib.metadata.version("onnx"),
        },
        "diffusers": importlib.metadata.version("diffusers"),
        "plugins": {},
        "mutations": {"lora": [], "controlnet": [], "ip_adapter": [], "refit": False},
        "adapter_version": ADAPTER_VERSION,
    }


def _profile(shape: list[int]) -> dict:
    if len(shape) != 4 or shape[0] != 1 or shape[1] != 4:
        raise RuntimeError("SD1.5 UNet requires a batch-one, four-channel latent shape")
    height, width = (int(shape[2]), int(shape[3]))
    if not (8 <= height <= 128 and 8 <= width <= 128):
        raise RuntimeError("SD1.5 UNet latent dimensions must represent 64 to 1024 output pixels")
    minimum = [1, 4, max(8, height // 2), max(8, width // 2)]
    optimum = [1, 4, height, width]
    maximum = [2, 4, min(128, height * 2), min(128, width * 2)]
    return {
        "sample": {"min": minimum, "opt": optimum, "max": maximum},
        "timestep": {"min": [1], "opt": [1], "max": [1]},
        "encoder_hidden_states": {
            "min": [1, CONTEXT_TOKENS, 768],
            "opt": [1, CONTEXT_TOKENS, 768],
            "max": [2, CONTEXT_TOKENS, 768],
        },
    }


def prepare_unet(
    data_dir: Path,
    model_dir: Path,
    shape: list[int],
    precision: str,
    device: int,
    allow_build: bool,
    validation_limits: dict | None = None,
    progress=lambda stage: None,
):
    import torch
    import tensorrt as trt
    from diffusers import UNet2DConditionModel

    if precision not in {"fp16", "fp32"}:
        raise RuntimeError(f"Unsupported SD1.5 UNet precision: {precision}")
    torch.cuda.set_device(device)
    selected_workspace_bytes = workspace_bytes(torch, device)
    profile = _profile(shape)
    identity = component_identity(model_dir, profile, precision, device, selected_workspace_bytes)
    cache = EngineCache(data_dir)
    key = engine_key(identity)
    with cache.lock(key, timeout_s=1800):
        found = cache.lookup(identity)
        if found:
            path, manifest = found
            return TensorExecutor(path.read_bytes(), device), manifest, "hit"
        previous = cache.read(key)
        if previous and previous.get("state") in {"failed", "quarantined"}:
            raise RuntimeError("Engine is disabled after a previous failure; clear it to retry")
        if not allow_build:
            raise RuntimeError("No validated UNet engine for this profile; compilation is disabled by policy")
        require_build_memory(torch, device, selected_workspace_bytes)
        cache.state(key, identity, "building")
        try:
            dtype = torch.float16 if precision == "fp16" else torch.float32
            progress("loading_reference")
            unet = UNet2DConditionModel.from_pretrained(
                str(model_dir / "unet"),
                local_files_only=True,
                use_safetensors=True,
                torch_dtype=dtype,
            ).to(f"cuda:{device}").eval()

            class Denoiser(torch.nn.Module):
                def __init__(self, module):
                    super().__init__()
                    self.unet = module

                def forward(self, sample, timestep, encoder_hidden_states):
                    return self.unet(
                        sample,
                        timestep,
                        encoder_hidden_states=encoder_hidden_states,
                        return_dict=False,
                    )[0]

            module = Denoiser(unet).eval()
            generator = torch.Generator(device=f"cuda:{device}").manual_seed(1729)

            def inputs(seed: int, batch: int = 1):
                generator.manual_seed(seed)
                return {
                    "sample": torch.randn(
                        (batch, 4, shape[2], shape[3]), generator=generator,
                        device=f"cuda:{device}", dtype=dtype,
                    ),
                    "timestep": torch.tensor([500.0], device=f"cuda:{device}", dtype=dtype),
                    "encoder_hidden_states": torch.randn(
                        (batch, CONTEXT_TOKENS, 768), generator=generator,
                        device=f"cuda:{device}", dtype=dtype,
                    ),
                }

            sample = inputs(1729)
            graph = cache.directory(key) / "unet.onnx"
            progress("exporting")
            started = time.perf_counter()
            try:
                torch.onnx.export(
                    module,
                    tuple(sample.values()),
                    str(graph),
                    input_names=list(sample),
                    output_names=["noise_pred"],
                    dynamic_axes={
                        "sample": {0: "batch", 2: "latent_height", 3: "latent_width"},
                        "encoder_hidden_states": {0: "batch"},
                        "noise_pred": {0: "batch", 2: "latent_height", 3: "latent_width"},
                    },
                    opset_version=18,
                    dynamo=False,
                )
                logger = trt.Logger(trt.Logger.WARNING)
                builder = trt.Builder(logger)
                flags = 0 if int(trt.__version__.split(".")[0]) >= 11 else 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
                network = builder.create_network(flags)
                parser = trt.OnnxParser(network, logger)
                if not parser.parse_from_file(str(graph)):
                    errors = "; ".join(str(parser.get_error(index)) for index in range(parser.num_errors))
                    raise RuntimeError(f"TensorRT UNet ONNX parse failed: {errors}")
                config = builder.create_builder_config()
                config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, selected_workspace_bytes)
                optimization = builder.create_optimization_profile()
                for name, shapes in profile.items():
                    accepted = optimization.set_shape(name, shapes["min"], shapes["opt"], shapes["max"])
                    if accepted is False:
                        raise RuntimeError(f"TensorRT rejected the UNet optimization profile for {name!r}")
                if not optimization:
                    raise RuntimeError("TensorRT rejected the completed UNet optimization profile")
                config.add_optimization_profile(optimization)
                progress("building")
                serialized = builder.build_serialized_network(network, config)
                engine = bytes(serialized) if serialized is not None else None
            finally:
                graph.unlink(missing_ok=True)
            if not engine:
                raise RuntimeError("SD1.5 UNet compiler produced no engine")
            build_s = time.perf_counter() - started
            cache.state(key, identity, "validating")
            progress("validating")
            executor = TensorExecutor(engine, device)
            rows = []
            with torch.inference_mode():
                validation_cases = ((1729, 1), (42, 1), (7, 2))
                for seed, batch in validation_cases:
                    values = inputs(seed, batch)
                    reference = module(*values.values())
                    actual = executor(values)["noise_pred"]
                    rows.append({"seed": seed, "batch": batch, **tensor_validation_metrics(reference, actual)})
            limits = dict(validation_limits or default_validation_limits(precision))
            validation = aggregate_validation_metrics(rows)
            passed, failures = evaluate_validation(validation, limits)
            validation.update({
                "passed": passed,
                "validation_schema": VALIDATION_SCHEMA,
                "limits": limits,
                "fixed_seeds": [seed for seed, _ in validation_cases],
                "validated_batches": sorted({batch for _, batch in validation_cases}),
                "quality_scope": "unet_numeric_fixed_seed",
                "failures": failures,
            })
            if not passed:
                cache.state(key, identity, "failed", reason="UNet numerical validation failed", validation=validation)
                raise RuntimeError("UNet numerical validation failed: " + json.dumps(failures))
            timings = {"build_s": build_s}
            for name, function in (("pytorch_s", lambda: module(*sample.values())),
                                   ("tensorrt_s", lambda: executor(sample))):
                function()
                torch.cuda.synchronize(device)
                begin = time.perf_counter()
                for _ in range(3):
                    function()
                torch.cuda.synchronize(device)
                timings[name] = (time.perf_counter() - begin) / 3
            timings["beneficial"] = timings["tensorrt_s"] < timings["pytorch_s"] * 0.95
            manifest = cache.publish(identity, engine, validation, timings)
            del module, unet
            torch.cuda.empty_cache()
            return executor, manifest, "built"
        except Exception as exc:
            previous = cache.read(key) or {}
            detail = {"validation": previous["validation"]} if isinstance(previous.get("validation"), dict) else {}
            cache.state(key, identity, "failed", reason=str(exc), **detail)
            raise
