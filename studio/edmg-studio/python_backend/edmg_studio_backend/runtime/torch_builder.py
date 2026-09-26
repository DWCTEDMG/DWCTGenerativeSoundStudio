"""Worker-only Torch-TensorRT compilation helpers.

This module is safe to import for tests, but its default compiler/loader functions
import Torch-TensorRT and Diffusers only when called inside the runtime worker.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .cache import EngineCache, engine_key


class TorchCompiledExecutor:
    def __init__(self, module, input_names: tuple[str, ...]):
        self.module = module
        self.input_names = input_names

    def __call__(self, value):
        if isinstance(value, dict):
            args = [value[name] for name in self.input_names]
        elif len(self.input_names) == 1:
            args = [value]
        else:
            raise RuntimeError("Compiled Torch-TensorRT components require named inputs")
        output = self.module(*args)
        if hasattr(output, "sample"):
            output = output.sample
        if isinstance(output, (tuple, list)) and len(output) == 1:
            output = output[0]
        return output


def _default_compile(module, args, kwargs):
    import torch
    import torch_tensorrt
    return torch_tensorrt.compile(
        module.eval(), ir="dynamo", arg_inputs=list(args), kwarg_inputs=kwargs,
        enabled_precisions={next(module.parameters()).dtype if any(True for _ in module.parameters()) else torch.float32},
    )


def _default_serialize(module) -> bytes:
    import torch_tensorrt
    with tempfile.TemporaryDirectory(prefix="edmg-torchtrt-") as directory:
        path = Path(directory) / "program.ep"
        torch_tensorrt.save(module, str(path), output_format="exported_program", retrace=False)
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
        raise RuntimeError(validation.get("reason") or "Torch-TensorRT numerical validation failed")
    artifact = serialize_module(compiled)
    if not artifact:
        raise RuntimeError("Torch-TensorRT produced an empty compiled artifact")
    cache = EngineCache(data_dir)
    manifest = cache.publish(identity, artifact, validation, {"beneficial": False, "scope": "torch_compile"})
    manifest = cache.state(
        engine_key(identity), identity, "ready", engine_sha256=manifest["engine_sha256"],
        validation=validation, benchmark=manifest["benchmark"], size_bytes=len(artifact),
        compiled_torch=True, source="edmg_local_build",
    )
    return TorchCompiledExecutor(compiled, input_names), manifest, "built"


def load_registered_component(loader_id: str, model_dir: Path, shape: list[int], precision: str,
                              device: int):
    import torch
    from diffusers import AutoencoderKL, UNet2DConditionModel
    from torch import nn
    dtype = torch.float16 if precision == "fp16" else torch.float32
    target = f"cuda:{device}"
    if loader_id == "sd15_vae_decoder":
        vae = AutoencoderKL.from_pretrained(model_dir, subfolder="vae", torch_dtype=dtype).to(target)
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
        unet = UNet2DConditionModel.from_pretrained(model_dir, subfolder="unet", torch_dtype=dtype).to(target)
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
