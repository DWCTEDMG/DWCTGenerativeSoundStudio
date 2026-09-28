"""Worker-only Torch-TensorRT compilation helpers.

This module is safe to import for tests, but its default compiler/loader functions
import Torch-TensorRT and Diffusers only when called inside the runtime worker.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .cache import EngineCache, engine_key


class TorchCompiledExecutor:
    def __init__(self, module, input_names: tuple[str, ...], device):
        self.module = module
        self.input_names = input_names
        self.device = device

    def __call__(self, value):
        if isinstance(value, dict):
            args = [value[name] for name in self.input_names]
        elif len(self.input_names) == 1:
            args = [value]
        else:
            raise RuntimeError("Compiled Torch-TensorRT components require named inputs")
        if self.device is not None:
            args = [value.to(self.device) for value in args]
        output = self.module(*args)
        if hasattr(output, "sample"):
            output = output.sample
        if isinstance(output, (tuple, list)) and len(output) == 1:
            output = output[0]
        return output


def _default_compile(module, args, kwargs):
    import torch
    import torch_tensorrt
    compile_inputs = {"arg_inputs": list(args), "kwarg_inputs": kwargs} if kwargs else {
        "inputs": list(args)
    }
    is_torchscript = isinstance(
        module, (torch.jit.ScriptModule, torch.jit.ScriptFunction)
    ) or hasattr(module, "graph")
    compile_options = {"ir": "ts"} if is_torchscript else {}
    if is_torchscript:
        compile_options["enabled_precisions"] = {
            next(module.parameters()).dtype if any(True for _ in module.parameters()) else torch.float32
        }
    else:
        # A partially compiled Diffusers UNet can cross the PyTorch/TRT boundary many
        # times and has produced invalid results on the multi-GPU Windows lane.  Fail
        # truthfully on unsupported operators instead of admitting a divergent hybrid.
        compile_options["require_full_compilation"] = True
    return torch_tensorrt.compile(
        module.eval(), **compile_options, **compile_inputs,
        truncate_long_and_double=True,
    )


def _default_serialize(module) -> bytes:
    import torch
    import torch_tensorrt
    with tempfile.TemporaryDirectory(prefix="edmg-torchtrt-") as directory:
        if isinstance(module, torch.fx.GraphModule) or isinstance(
            module, torch.export.ExportedProgram
        ):
            path = Path(directory) / "program.ep"
            torch_tensorrt.save(
                module, str(path), output_format="exported_program", retrace=False,
            )
        else:
            path = Path(directory) / "program.ts"
            # Torch-TensorRT 2.11's public save helper rejects its own ScriptModule output
            # due to an inverted format guard.  Use PyTorch's canonical serializer.
            torch.jit.save(module, str(path))
        return path.read_bytes()


def compile_torch_component(*, data_dir: Path, identity: dict, module, example_args: tuple,
                            example_kwargs: dict, input_names: tuple[str, ...], compile_module=None,
                            serialize_module=None, validate=None):
    compile_module = compile_module or _default_compile
    serialize_module = serialize_module or _default_serialize
    validate = validate or (lambda _module: {"passed": False, "reason": "No validation contract"})
    compiled = compile_module(module, example_args, example_kwargs)
    validation = validate(compiled)
    if validation.get("passed") is not True:
        detail = validation.get("reason") or repr(validation)
        raise RuntimeError(f"Torch-TensorRT numerical validation failed: {detail}")
    artifact = serialize_module(compiled)
    if not artifact:
        raise RuntimeError("Torch-TensorRT produced an empty compiled artifact")
    cache = EngineCache(data_dir)
    try:
        import torch
        compiled_format = "exported_program" if isinstance(
            compiled, (torch.fx.GraphModule, torch.export.ExportedProgram)
        ) else "torchscript"
    except (AttributeError, ImportError):
        compiled_format = "torchscript"
    manifest = cache.publish(identity, artifact, validation, {"beneficial": False, "scope": "torch_compile"})
    manifest = cache.state(
        engine_key(identity), identity, "ready", engine_sha256=manifest["engine_sha256"],
        validation=validation, benchmark=manifest["benchmark"], size_bytes=len(artifact),
        compiled_torch=True, compiled_format=compiled_format, source="edmg_local_build",
    )
    example_tensors = [value for value in (*example_args, *example_kwargs.values()) if hasattr(value, "device")]
    device = example_tensors[0].device if example_tensors else None
    return TorchCompiledExecutor(compiled, input_names, device), manifest, "built"


def load_cached_torch_component(*, data_dir: Path, identity: dict,
                                input_names: tuple[str, ...], device):
    import torch
    found = EngineCache(data_dir).lookup(identity)
    if not found:
        return None
    path, manifest = found
    if manifest.get("compiled_format") == "exported_program":
        module = torch.export.load(str(path)).module()
    else:
        module = torch.jit.load(str(path), map_location=device).eval()
    return TorchCompiledExecutor(module, input_names, device), manifest, "ready"


def _load_checkpoint_module(model_dir: Path, torch, nn):
    checkpoints = sorted([*model_dir.glob("*.pt"), *model_dir.glob("*.pth")])
    if len(checkpoints) != 1:
        raise RuntimeError("PyTorch TensorRT routing requires exactly one managed .pt or .pth checkpoint")
    checkpoint = checkpoints[0]
    try:
        module = torch.jit.load(str(checkpoint), map_location="cpu")
    except Exception:
        # weights_only=True deliberately refuses arbitrary pickle execution.  A plain state
        # dict has no graph to compile, so it needs an architecture-specific HF/config loader.
        value = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if isinstance(value, nn.Module):
            module = value
        else:
            raise RuntimeError(
                "The managed PyTorch checkpoint contains weights but no executable graph; "
                "provide Hugging Face config+safetensors or a TorchScript .pt module"
            )
    return module


def load_registered_component(loader_id: str, model_dir: Path, shape: list[int], precision: str,
                              device: int, source_kind: str = "huggingface"):
    import torch
    from diffusers import AutoencoderKL, UNet2DConditionModel
    from torch import nn
    dtype = torch.float16 if precision == "fp16" else torch.float32
    target = f"cuda:{device}"
    if source_kind == "pytorch_checkpoint":
        module = _load_checkpoint_module(model_dir, torch, nn).to(device=target, dtype=dtype).eval()
        if loader_id == "sd15_vae_decoder":
            args = (torch.zeros(tuple(shape), device=target, dtype=dtype),)
            return module, args, {}, ("latent",)
        if loader_id == "sd15_unet":
            sample = torch.zeros(tuple(shape), device=target, dtype=dtype)
            timestep = torch.tensor([500.0], device=target, dtype=dtype)
            hidden = torch.zeros((shape[0], 77, 768), device=target, dtype=dtype)
            return module, (sample, timestep, hidden), {}, (
                "sample", "timestep", "encoder_hidden_states",
            )
        raise RuntimeError(f"No registered PyTorch checkpoint loader for {loader_id}")

    component_dir = model_dir / ("vae" if loader_id == "sd15_vae_decoder" else "unet")
    load_root = component_dir if (component_dir / "config.json").is_file() else model_dir
    load_kwargs = {} if load_root == component_dir else {
        "subfolder": "vae" if loader_id == "sd15_vae_decoder" else "unet"
    }
    if loader_id == "sd15_vae_decoder":
        vae = AutoencoderKL.from_pretrained(load_root, torch_dtype=dtype, **load_kwargs).to(target)
        class Decoder(nn.Module):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner
            def forward(self, latent):
                return self.owner.decode(latent, return_dict=False)[0]
        module = Decoder(vae).eval()
        latent = torch.zeros(tuple(shape), device=target, dtype=dtype)
        return module, (latent,), {}, ("latent",)
    if loader_id == "sd15_unet":
        unet = UNet2DConditionModel.from_pretrained(load_root, torch_dtype=dtype, **load_kwargs).to(target)
        class Denoiser(nn.Module):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner
            def forward(self, sample, timestep, encoder_hidden_states):
                return self.owner(sample, timestep, encoder_hidden_states, return_dict=False)[0]
        module = Denoiser(unet).eval()
        sample = torch.zeros(tuple(shape), device=target, dtype=dtype)
        timestep = torch.tensor([500.0], device=target, dtype=dtype)
        hidden = torch.zeros((shape[0], 77, 768), device=target, dtype=dtype)
        return module, (sample, timestep, hidden), {}, (
            "sample", "timestep", "encoder_hidden_states",
        )
    raise RuntimeError(f"No registered PyTorch loader for {loader_id}")
