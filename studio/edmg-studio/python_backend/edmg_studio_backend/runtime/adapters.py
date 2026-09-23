"""TensorRT component declarations and executable adapter lookup."""
from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComponentAdapter:
    model_family: str
    component: str
    fallback_runtime: str
    supported: bool = False
    buildable: bool = False
    reason: str | None = None
    precisions: tuple[str, ...] = ("fp32", "fp16")
    model_id: str | None = None
    builder_module: str | None = None
    builder_function: str | None = None

    def status(self) -> dict:
        value = asdict(self)
        value.pop("builder_module")
        value.pop("builder_function")
        value["status"] = "adapter_available" if self.supported else "unsupported"
        value["requires_engine_validation"] = self.supported
        return value

    def model_dir(self, models_dir: Path) -> Path | None:
        if self.model_id is None:
            return None
        return models_dir / "internal" / "diffusers" / self.model_id

    def prepare(self, *args, **kwargs):
        if not self.buildable or not self.builder_module or not self.builder_function:
            raise RuntimeError(f"No TensorRT builder is registered for {self.model_family}/{self.component}")
        module = importlib.import_module(self.builder_module, package=__package__)
        return getattr(module, self.builder_function)(*args, **kwargs)


_FAMILIES = {
    "sd15": ("vae_decoder", "text_encoder", "unet"),
    "sdxl": ("vae_decoder", "text_encoder", "unet"),
    "sd3": ("vae_decoder", "text_encoder", "transformer"),
    "flux": ("vae_decoder", "text_encoder", "transformer"),
    "svd": ("vae_decoder", "vision_encoder", "unet"),
    "animatediff": ("vae_decoder", "text_encoder", "unet"),
    "ltx_25": ("vae_decoder", "text_encoder", "transformer"),
    "wan": ("vae_decoder", "text_encoder", "transformer"),
    "hunyuan_video15": ("vae_decoder", "text_encoder", "transformer"),
    "qwen": ("language_model",),
    "whisper": ("audio_encoder", "decoder"),
}

_BUILDERS = {
    ("sd15", "vae_decoder"): ("hf_sd15_internal", ".builder", "prepare_component"),
    ("sd15", "unet"): ("hf_sd15_internal", ".unet_builder", "prepare_unet"),
}


def _fallback(family: str) -> str:
    if family == "qwen":
        return "llama_cpp"
    if family == "whisper":
        return "ctranslate2"
    return "existing_model_runtime"


def _reason(family: str, component: str) -> str | None:
    if (family, component) in _BUILDERS:
        return None
    if family == "qwen":
        return "Qwen is served by the dedicated llama.cpp provider; it is not a diffusion component"
    if family == "whisper":
        return "Whisper remains on the validated CTranslate2 provider"
    if component in {"text_encoder", "vision_encoder"}:
        return "Encoder remains on the existing model runtime until a model-specific export is qualified"
    return "No validated model-specific TensorRT graph adapter is installed"


class ComponentAdapterRegistry:
    def __init__(self) -> None:
        self._adapters = {}
        for family, components in _FAMILIES.items():
            for component in components:
                registration = _BUILDERS.get((family, component))
                self._adapters[(family, component)] = ComponentAdapter(
                    model_family=family,
                    component=component,
                    fallback_runtime=_fallback(family),
                    supported=registration is not None,
                    buildable=registration is not None,
                    reason=_reason(family, component),
                    model_id=registration[0] if registration else None,
                    builder_module=registration[1] if registration else None,
                    builder_function=registration[2] if registration else None,
                )

    def get(self, model_family: str, component: str) -> ComponentAdapter | None:
        return self._adapters.get((model_family, component))

    def require(self, model_family: str, component: str) -> ComponentAdapter:
        adapter = self.get(model_family, component)
        if adapter is None or not adapter.buildable:
            raise RuntimeError(f"No buildable TensorRT adapter for {model_family}/{component}")
        return adapter

    def statuses(self) -> list[dict]:
        return [adapter.status() for adapter in self._adapters.values()]

    def supported_components(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for adapter in self._adapters.values():
            if adapter.supported:
                result.setdefault(adapter.model_family, []).append(adapter.component)
        return result
