"""Backend-only component selection, observable fallback and job-local circuit breaker."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .adapters import ComponentAdapterRegistry
from .cache import EngineCache
from .policy import RuntimePolicy
from .process import RuntimeCanceled, RuntimeProcess

logger = logging.getLogger(__name__)


class RuntimeAdapter(Protocol):
    runtime_id: str

    def supports(self, model: str, component: str) -> bool: ...
    def execute(self, value): ...
    def cleanup(self) -> None: ...


@dataclass(frozen=True)
class RuntimeRegistry:
    # Package admission is still owned by ModelRuntimeRegistry. These are execution capabilities.
    capabilities: dict = field(default_factory=lambda: {
        "pytorch_cuda": {"role": "existing_internal_pipelines"},
        "tensorrt": {**ComponentAdapterRegistry().supported_components(), "precision": ["fp32", "fp16"]},
        "tensorrt_standalone": {
            "sd15": ["unet"],
            "role": "verified_sd15_bundle_renderer",
        },
        "llama_cpp": {"role": "existing_qwen_gguf"},
        "ctranslate2": {"role": "existing_faster_whisper"},
        "cpu": {"role": "explicit_existing_fallback"},
    })

    def component_status(self) -> list[dict]:
        """Admission inventory, distinct from per-engine or full-model qualification."""
        return ComponentAdapterRegistry().statuses()


class RuntimeSelector:
    @staticmethod
    def permits_tensorrt(policy: RuntimePolicy, model: str, component: str, device: str) -> bool:
        supported = component in RuntimeRegistry().capabilities["tensorrt"].get(model, [])
        return bool(supported and device.startswith("cuda") and policy.enabled and policy.cache_enabled
                    and policy.mode not in {"pytorch_cuda", "cpu"})

    @staticmethod
    def requires_tensorrt(policy: RuntimePolicy) -> bool:
        return bool(policy.enabled and policy.strict and policy.mode not in {"pytorch_cuda", "cpu"})

    @staticmethod
    def may_build(policy: RuntimePolicy) -> bool:
        # Automatic mode never interrupts a render for compilation; Optimize is explicit.
        return policy.auto_build and policy.mode in {"performance", "tensorrt"}


@dataclass
class RuntimePlan:
    requested: str
    selected: str = "pytorch_cuda"
    device: str = "cuda:0"
    precision: str = "auto"
    component: str = "vae_decoder"
    engine_id: str | None = None
    cache: str = "missing"
    fallback_history: list[str] = field(default_factory=list)


class RuntimeManager:
    def __init__(self, policy: RuntimePolicy, data_dir: Path, model_dir: Path, original_decode):
        self.policy, self.data_dir, self.model_dir = policy, data_dir, model_dir
        self.original_decode = original_decode
        self.process = None
        self.profile = None
        self.disabled = False
        self.measured_profile = None
        self.plan = RuntimePlan(policy.mode)

    def cleanup(self):
        if self.process:
            self.process.close()
            self.process = None

    def _fallback(self, exc):
        self.cleanup()
        self.disabled = True
        self.plan.selected = "pytorch_cuda"
        self.plan.fallback_history.append(str(exc))
        logger.warning("[Runtime] VAE TensorRT fallback to PyTorch CUDA: %s", exc)
        if self.policy.strict or not self.policy.allow_fallback:
            raise RuntimeError(f"TensorRT strict execution failed: {exc}") from exc

    def decode(self, value, return_dict=True, generator=None, **kwargs):
        import torch
        device = str(value.device)
        self.plan.device = device
        if self.disabled and (self.policy.strict or not self.policy.allow_fallback):
            raise RuntimeError("TensorRT strict execution remains failed for this pipeline; fallback is disabled")
        if not RuntimeSelector.permits_tensorrt(self.policy, "sd15", "vae_decoder", device):
            if RuntimeSelector.requires_tensorrt(self.policy):
                raise RuntimeError(f"Strict TensorRT VAE execution is unavailable on {device}")
            return self.original_decode(value, return_dict=return_dict, generator=generator, **kwargs)
        if self.disabled:
            return self.original_decode(value, return_dict=return_dict, generator=generator, **kwargs)
        try:
            vae = getattr(self.original_decode, "__self__", None)
            if getattr(vae, "use_tiling", False) or getattr(vae, "use_slicing", False):
                raise RuntimeError("Tiled or sliced VAE decoding uses the PyTorch reference")
            if kwargs:
                raise RuntimeError("Custom VAE decode arguments require PyTorch")
            precision = "fp16" if value.dtype == torch.float16 else "fp32"
            if self.policy.precision not in {"auto", precision}:
                raise RuntimeError("Requested precision differs from the reference VAE")
            profile = (tuple(value.shape), device, precision)
            if self.profile != profile:
                self.cleanup()
                self.process = RuntimeProcess(self.data_dir, self.policy.package_path)
                result = self.process.request("prepare", timeout_s=1800,
                    model_dir=str(self.model_dir), shape=list(value.shape), precision=precision,
                    device=value.device.index or 0, component="vae_decoder",
                    allow_build=RuntimeSelector.may_build(self.policy),
                    validation_limits=self.policy.validation_limits(precision, "vae_decoder"))
                manifest = result["manifest"]
                self.plan.engine_id = manifest["engine_id"]
                self.plan.cache = result["cache"]
                self.plan.precision = precision
                if self.policy.mode in {"auto", "compatibility"} and not manifest["benchmark"].get("beneficial"):
                    raise RuntimeError("The validated TensorRT engine has no measured component speed benefit")
                self.profile = profile
            started = time.perf_counter()
            result = self.process.request("execute", array=value.detach().cpu().numpy())
            output = torch.from_numpy(result["output"]).to(device=value.device, dtype=value.dtype)
            torch.cuda.synchronize(value.device)
            roundtrip_s = time.perf_counter() - started
            if output.ndim != 4 or output.shape != (value.shape[0], 3, value.shape[2] * 8, value.shape[3] * 8):
                raise RuntimeError("TensorRT VAE returned an invalid output profile")
            if self.policy.mode in {"auto", "compatibility"} and self.measured_profile != profile:
                # Include IPC, transfers and synchronization, not just engine kernel time.
                started = time.perf_counter()
                reference = self.original_decode(value, return_dict=False)
                torch.cuda.synchronize(value.device)
                reference_s = time.perf_counter() - started
                self.measured_profile = profile
                if roundtrip_s >= reference_s * 0.95:
                    self.cleanup()
                    self.disabled = True
                    self.plan.fallback_history.append("TensorRT round-trip is not faster than PyTorch for this profile")
                    if not return_dict:
                        return reference
                    from diffusers.models.autoencoders.vae import DecoderOutput
                    return DecoderOutput(sample=reference[0])
            self.plan.selected = "tensorrt"
            logger.info("[Runtime] %s", asdict(self.plan))
            if not return_dict:
                return (output,)
            from diffusers.models.autoencoders.vae import DecoderOutput
            return DecoderOutput(sample=output)
        except RuntimeCanceled:
            self.cleanup()
            raise
        except Exception as exc:
            self._fallback(exc)
            # Reuse the exact latent; no prompt, RNG or denoising restart.
            return self.original_decode(value, return_dict=return_dict, generator=generator, **kwargs)


class UnetRuntimeManager:
    def __init__(self, policy: RuntimePolicy, data_dir: Path, model_dir: Path, original_forward):
        self.policy, self.data_dir, self.model_dir = policy, data_dir, model_dir
        self.original_forward = original_forward
        self.process = None
        self.profile = None
        self.disabled = False
        self.measured_profile = None
        self.plan = RuntimePlan(policy.mode, component="unet")

    def cleanup(self):
        if self.process:
            self.process.close()
            self.process = None

    def _fallback(self, exc):
        self.cleanup()
        self.disabled = True
        self.plan.selected = "pytorch_cuda"
        self.plan.fallback_history.append(str(exc))
        logger.warning("[Runtime] UNet TensorRT fallback to PyTorch CUDA: %s", exc)
        if self.policy.strict or not self.policy.allow_fallback:
            raise RuntimeError(f"TensorRT strict execution failed: {exc}") from exc

    def _reference_only(self, reason, sample, timestep, encoder_hidden_states, *args, **kwargs):
        if reason not in self.plan.fallback_history:
            self.plan.fallback_history.append(reason)
            logger.info("[Runtime] UNet retained PyTorch CUDA: %s", reason)
        if self.policy.strict or not self.policy.allow_fallback:
            raise RuntimeError(f"TensorRT cannot execute this UNet call: {reason}")
        return self.original_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)

    def forward(self, sample, timestep, encoder_hidden_states, *args, **kwargs):
        import torch

        device = str(sample.device)
        self.plan.device = device
        if self.disabled and (self.policy.strict or not self.policy.allow_fallback):
            raise RuntimeError("TensorRT strict execution remains failed for this pipeline; fallback is disabled")
        if not RuntimeSelector.permits_tensorrt(self.policy, "sd15", "unet", device):
            if RuntimeSelector.requires_tensorrt(self.policy):
                raise RuntimeError(f"Strict TensorRT UNet execution is unavailable on {device}")
            return self.original_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)
        if self.disabled:
            return self.original_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)

        return_dict = kwargs.get("return_dict", True)
        unsupported = {name for name, value in kwargs.items() if name != "return_dict" and value is not None}
        module = getattr(self.original_forward, "__self__", None)
        mutations = getattr(module, "peft_config", None)
        if args or unsupported or mutations:
            reason = "LoRA or additional UNet conditioning requires the PyTorch reference"
            return self._reference_only(
                reason, sample, timestep, encoder_hidden_states, *args, **kwargs,
            )

        try:
            if sample.ndim != 4 or sample.shape[0] not in {1, 2} or sample.shape[1] != 4:
                raise RuntimeError(f"UNet input shape {tuple(sample.shape)} is outside the admitted SD1.5 contract")
            if encoder_hidden_states.ndim != 3 or encoder_hidden_states.shape[0] != sample.shape[0]:
                raise RuntimeError("UNet conditioning batch does not match the latent batch")
            precision = "fp16" if sample.dtype == torch.float16 else "fp32"
            if self.policy.precision not in {"auto", precision}:
                raise RuntimeError("Requested precision differs from the reference UNet")
            profile = (tuple(sample.shape[2:]), device, precision)
            if self.profile != profile:
                self.cleanup()
                self.process = RuntimeProcess(self.data_dir, self.policy.package_path)
                result = self.process.request(
                    "prepare",
                    timeout_s=1800,
                    model_dir=str(self.model_dir),
                    shape=[1, 4, int(sample.shape[2]), int(sample.shape[3])],
                    precision=precision,
                    device=sample.device.index or 0,
                    component="unet",
                    allow_build=RuntimeSelector.may_build(self.policy),
                    validation_limits=self.policy.validation_limits(precision, "unet"),
                )
                manifest = result["manifest"]
                self.plan.engine_id = manifest["engine_id"]
                self.plan.cache = result["cache"]
                self.plan.precision = precision
                if self.policy.mode in {"auto", "compatibility"} and not manifest["benchmark"].get("beneficial"):
                    raise RuntimeError("The validated TensorRT UNet has no measured component speed benefit")
                self.profile = profile

            if not torch.is_tensor(timestep):
                timestep = torch.tensor([float(timestep)], device=sample.device, dtype=sample.dtype)
            elif timestep.ndim == 0:
                timestep = timestep.reshape(1)
            started = time.perf_counter()
            result = self.process.request(
                "execute",
                arrays={
                    "sample": sample.detach().cpu().numpy(),
                    "timestep": timestep.detach().cpu().numpy(),
                    "encoder_hidden_states": encoder_hidden_states.detach().cpu().numpy(),
                },
            )
            output = torch.from_numpy(result["outputs"]["noise_pred"]).to(
                device=sample.device,
                dtype=sample.dtype,
            )
            torch.cuda.synchronize(sample.device)
            roundtrip_s = time.perf_counter() - started
            if output.shape != sample.shape:
                raise RuntimeError("TensorRT UNet returned an invalid output shape")
            if self.policy.mode in {"auto", "compatibility"} and self.measured_profile != profile:
                started = time.perf_counter()
                reference = self.original_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)
                torch.cuda.synchronize(sample.device)
                reference_s = time.perf_counter() - started
                self.measured_profile = profile
                if roundtrip_s >= reference_s * 0.95:
                    self.cleanup()
                    self.disabled = True
                    self.plan.fallback_history.append("TensorRT round-trip is not faster than PyTorch for this profile")
                    return reference
            self.plan.selected = "tensorrt"
            logger.info("[Runtime] %s", asdict(self.plan))
            if not return_dict:
                return (output,)
            from diffusers.models.unets.unet_2d_condition import UNet2DConditionOutput
            return UNet2DConditionOutput(sample=output)
        except RuntimeCanceled:
            self.cleanup()
            raise
        except Exception as exc:
            self._fallback(exc)
            return self.original_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)


def install_pipeline_runtime(pipes, model_dir: Path, *, policy=None):
    from ..config import Settings
    from .policy import load_policy
    data_dir = Settings().data_dir
    policy = policy or load_policy(data_dir)
    pipes.runtime_policy = policy.model_dump()
    if pipes.family != "sd15" or not str(pipes.device).startswith("cuda"):
        if RuntimeSelector.requires_tensorrt(policy):
            raise RuntimeError(
                f"Strict TensorRT requires a supported SD1.5 CUDA pipeline; got family={pipes.family}, device={pipes.device}"
            )
        return
    from ..services.model_weights import diffusers_weight_load_kwargs
    vae = getattr(pipes.txt2img, "vae", None)
    alternate_weights = diffusers_weight_load_kwargs(model_dir, "cuda")
    if alternate_weights:
        logger.info("[Runtime] Alternate VAE weight layouts retain PyTorch VAE execution")
    elif vae is not None and getattr(vae, "_edmg_runtime", None) is None:
        manager = RuntimeManager(policy, data_dir, model_dir, vae.decode)
        vae._edmg_runtime = manager
        vae.decode = manager.decode
    unet = getattr(pipes.txt2img, "unet", None)
    if unet is not None and getattr(unet, "_edmg_runtime", None) is None:
        manager = UnetRuntimeManager(policy, data_dir, model_dir, unet.forward)
        unet._edmg_runtime = manager
        unet.forward = manager.forward


def release_pipeline_runtime(pipe):
    for component in ("vae", "unet"):
        manager = getattr(getattr(pipe, component, None), "_edmg_runtime", None)
        if manager:
            manager.cleanup()


def pipeline_runtime_metadata(pipes, operation=None) -> dict:
    if pipes is None:
        return {"selected": "existing_video_model_runtime", "operation": operation,
                "reason": "No converted TensorRT component is installed for this pipeline"}
    managers = [
        manager for manager in (
            getattr(getattr(pipes.txt2img, "unet", None), "_edmg_runtime", None),
            getattr(getattr(pipes.txt2img, "vae", None), "_edmg_runtime", None),
        ) if manager is not None
    ]
    if managers:
        plans = [asdict(manager.plan) for manager in managers]
        active = [plan for plan in plans if plan["selected"] == "tensorrt"]
        primary = active[0] if active else plans[0]
        return {
            "selected": "tensorrt" if active else "pytorch_cuda",
            "requested": managers[0].plan.requested,
            "device": managers[0].plan.device,
            "precision": primary["precision"],
            "component": primary["component"],
            "engine_id": primary["engine_id"],
            "cache": primary["cache"],
            "fallback_history": primary["fallback_history"],
            "components": plans,
            "operation": operation,
        }
    return {
        "selected": pipes.backend, "device": pipes.device,
        "requested": getattr(pipes, "runtime_policy", {}).get("mode", "auto"),
        "operation": operation,
        "reason": "Existing model runtime; no eligible TensorRT component selected",
    }
