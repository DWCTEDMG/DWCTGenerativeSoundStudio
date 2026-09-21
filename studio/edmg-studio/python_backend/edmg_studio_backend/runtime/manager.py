"""Backend-only component selection, observable fallback and job-local circuit breaker."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

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
        "tensorrt": {"sd15": ["vae_decoder"], "precision": ["fp32", "fp16"]},
        "llama_cpp": {"role": "existing_qwen_gguf"},
        "ctranslate2": {"role": "existing_faster_whisper"},
        "cpu": {"role": "explicit_existing_fallback"},
    })


class RuntimeSelector:
    @staticmethod
    def permits_tensorrt(policy: RuntimePolicy, model: str, component: str, device: str) -> bool:
        supported = component in RuntimeRegistry().capabilities["tensorrt"].get(model, [])
        return bool(supported and device.startswith("cuda") and policy.enabled and policy.cache_enabled
                    and policy.mode not in {"pytorch_cuda", "cpu"})

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
        if self.disabled or not RuntimeSelector.permits_tensorrt(self.policy, "sd15", "vae_decoder", device):
            return self.original_decode(value, return_dict=return_dict, generator=generator, **kwargs)
        try:
            vae = getattr(self.original_decode, "__self__", None)
            if getattr(vae, "use_tiling", False) or getattr(vae, "use_slicing", False):
                raise RuntimeError("Tiled or sliced VAE decoding uses the PyTorch reference")
            if kwargs or generator is not None:
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
                    device=value.device.index or 0, allow_build=RuntimeSelector.may_build(self.policy))
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
            if self.plan.engine_id and self.profile is not None:
                EngineCache(self.data_dir).quarantine(self.plan.engine_id, str(exc))
            self._fallback(exc)
            # Reuse the exact latent; no prompt, RNG or denoising restart.
            return self.original_decode(value, return_dict=return_dict, generator=generator, **kwargs)


def install_pipeline_runtime(pipes, model_dir: Path):
    from ..config import Settings
    from .policy import load_policy
    data_dir = Settings().data_dir
    policy = load_policy(data_dir)
    if pipes.family != "sd15" or not RuntimeSelector.permits_tensorrt(policy, pipes.family, "vae_decoder", pipes.device):
        return
    from ..services.model_weights import diffusers_weight_load_kwargs
    if diffusers_weight_load_kwargs(model_dir, "cuda"):
        logger.info("[Runtime] Alternate VAE weight layouts retain PyTorch execution")
        return
    vae = getattr(pipes.txt2img, "vae", None)
    if vae is None or getattr(vae, "_edmg_runtime", None) is not None:
        return
    manager = RuntimeManager(policy, data_dir, model_dir, vae.decode)
    vae._edmg_runtime = manager
    vae.decode = manager.decode


def release_pipeline_runtime(pipe):
    manager = getattr(getattr(pipe, "vae", None), "_edmg_runtime", None)
    if manager:
        manager.cleanup()


def pipeline_runtime_metadata(pipes) -> dict:
    if pipes is None:
        return {"selected": "existing_video_model_runtime"}
    manager = getattr(getattr(pipes.txt2img, "vae", None), "_edmg_runtime", None)
    return asdict(manager.plan) if manager else {"selected": pipes.backend, "device": pipes.device}
