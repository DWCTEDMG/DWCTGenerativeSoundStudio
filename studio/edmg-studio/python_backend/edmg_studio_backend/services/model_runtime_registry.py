"""Runtime qualification for manifest-managed model packages.

Package installation and runtime qualification are intentionally independent.
A runtime is ready only after a real smoke test writes a receipt tied to the
package, adapter, dependencies, and selected hardware.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import tempfile
import wave
import zlib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ValidationState = Literal[
    "not_installed",
    "installed_runtime_unavailable",
    "runtime_degraded",
    "runtime_ready",
]

RUNTIME_RECEIPT = "runtime-validation.json"
REGISTRY_VERSION = 1


@dataclass(frozen=True)
class RuntimeDescriptor:
    package_id: str
    model_family: str
    model_format: str
    runtime_backend: str
    runtime_version: str
    role: str
    capabilities: tuple[str, ...]
    required_components: tuple[str, ...]
    dependency_modules: tuple[str, ...]
    supported_devices: tuple[str, ...]
    recommended_dtype: str
    minimum_vram_gb: float
    minimum_ram_gb: float
    adapter_ready: bool
    smoke_test_supported: bool
    implementation_error: str | None = None


@dataclass(frozen=True)
class RuntimeAdapter:
    descriptor: RuntimeDescriptor
    validate_config: Callable[[Path], list[str]]
    smoke_test: Callable[..., Mapping[str, Any]] | None = None


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid JSON configuration: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid JSON configuration: {path.name} must contain an object")
    return value


def _validate_qwen(root: Path) -> list[str]:
    models = sorted(root.glob("*.gguf"))
    main = [path for path in models if not path.name.lower().startswith("mmproj-")]
    projectors = [path for path in models if path.name.lower().startswith("mmproj-")]
    issues: list[str] = []
    if len(main) != 1:
        issues.append("Expected exactly one Qwen3-VL GGUF model file.")
    if len(projectors) != 1:
        issues.append("Expected exactly one Qwen3-VL multimodal projector file.")
    if main and "qwen3vl" not in main[0].name.lower().replace("-", ""):
        issues.append("The GGUF model filename is not a Qwen3-VL package artifact.")
    if projectors and "qwen3vl" not in projectors[0].name.lower().replace("-", ""):
        issues.append("The projector does not match the Qwen3-VL package family.")
    if main and projectors:
        main_name = main[0].name.lower().replace("-", "").replace("_", "")
        projector_name = projectors[0].name.lower().replace("-", "").replace("_", "")
        for size in ("8b", "30b"):
            if (size in main_name) != (size in projector_name):
                issues.append("The Qwen3-VL GGUF model and projector sizes do not match.")
                break
    try:
        from .llama_cpp_director import resolve_llama_server

        resolve_llama_server()
    except RuntimeError as exc:
        issues.append(str(exc))
    return issues


def _validate_whisper(root: Path) -> list[str]:
    try:
        config = _json_object(root / "config.json")
    except ValueError as exc:
        return [str(exc)]
    issues: list[str] = []
    if str(config.get("model_type") or "").lower() != "whisper":
        issues.append("config.json is not a Transformers Whisper configuration.")
    if not (root / "model.safetensors").is_file():
        issues.append("Transformers Whisper model.safetensors is missing.")
    return issues


def _validate_hunyuan(root: Path) -> list[str]:
    issues: list[str] = []
    try:
        _json_object(root / "config.json")
        _json_object(root / "scheduler" / "scheduler_config.json")
        _json_object(root / "vae" / "config.json")
    except ValueError as exc:
        issues.append(str(exc))
    required = (
        "transformer/480p_t2v_distilled/config.json",
        "transformer/480p_t2v_distilled/diffusion_pytorch_model.safetensors",
        "transformer/480p_i2v_step_distilled/config.json",
        "transformer/480p_i2v_step_distilled/diffusion_pytorch_model.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        issues.append("Required managed Hunyuan components are missing: " + ", ".join(missing))
    from .internal_video_models import validate_hunyuan_runner
    issues.extend(validate_hunyuan_runner())
    return issues


def _smoke_test_hunyuan(
    *, package_root: Path, hardware: Mapping[str, Any],
    cancel_check: Callable[[], Any] | None = None, **_kwargs: Any,
) -> Mapping[str, Any]:
    from .internal_video_models import generate_video_model_frames

    frames = generate_video_model_frames(
        engine="hunyuan_video15", video_model_dir=package_root, base_model_dir=package_root,
        init_image=None, prompt="A red cube slowly rotates on a black background",
        negative_prompt="text, watermark", width=256, height=256, num_frames=9, fps=24,
        steps=2, cfg=1.0, seed=1, device=ModelRuntimeRegistry._device(hardware),
        dtype="bfloat16", cpu_offload=True, workspace=package_root, cancel_check=cancel_check,
    )
    if len(frames) != 9:
        raise RuntimeError(f"Hunyuan smoke test decoded {len(frames)} frames instead of 9")
    return {"success": True, "device": ModelRuntimeRegistry._device(hardware), "dtype": "bfloat16",
            "frames": len(frames), "official_pipeline": "HunyuanVideo_1_5_Pipeline.create_pipeline"}


def _validate_ltx(root: Path) -> list[str]:
    required = (
        "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "vae/ltx-2.5-video-vae-bf16.safetensors",
        "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "model_patches/ltx-2.5-duration-head-bf16.safetensors",
        "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    )
    missing = [name for name in required if not (root / name).is_file()]
    issues = (["Required LTX-2.5 components are missing: " + ", ".join(missing)] if missing else [])
    if not issues:
        try:
            from .ltx_25_runtime import validate_runtime_version

            validate_runtime_version()
        except Exception as exc:
            issues.append(str(exc))
    return issues


def _smoke_test_ltx_25(
    *,
    package_root: Path,
    hardware: Mapping[str, Any],
    cancel_check: Callable[[], bool] | None = None,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    from .ltx_25_runtime import generate_ltx_frames

    device = ModelRuntimeRegistry._device(hardware)
    frames = generate_ltx_frames(
        package_root=package_root,
        workspace=package_root,
        prompt="A single white circle on a black background, static camera",
        width=64,
        height=64,
        num_frames=9,
        fps=8,
        seed=1,
        device=device,
        cpu_offload=True,
        cancel_check=cancel_check,
        timeout_s=float(os.environ.get("EDMG_LTX25_SMOKE_TIMEOUT_SECONDS", "600")),
    )
    if not frames:
        raise RuntimeError("LTX-2.5 smoke test returned no decoded frames")
    return {"success": True, "device": device, "dtype": "bfloat16", "frame_count": len(frames)}


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")


def _smoke_test_qwen_gguf(
    *,
    package_root: Path,
    hardware: Mapping[str, Any],
    cancel_check: Callable[[], bool] | None = None,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    from ..domain.director_scene import DirectorDocument
    from .llama_cpp_director import LlamaCppDirectorBackend
    from .qwen_director import validate_proposal

    document = DirectorDocument.model_validate({
        "scenes": [{"scene_id": "smoke", "start_sample": "0", "end_sample": "48000", "intent": "A black frame"}]
    })
    raw_scanline = b"\x00\x00\x00\x00"
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
        + _png_chunk(b"IDAT", zlib.compress(raw_scanline))
        + _png_chunk(b"IEND", b"")
    )
    image_name = ""
    backend = LlamaCppDirectorBackend(
        package_root,
        device=ModelRuntimeRegistry._device(hardware),
        context_length=8192,
        timeout_s=180,
    )
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image:
            image.write(png)
            image_name = image.name
        backend.start(cancel_check=cancel_check)
        text = backend.generate(
            document,
            "Return this DirectorDocument unchanged. Inspect the attached black pixel before responding.",
            image_paths=[image_name],
            max_tokens=1024,
            cancel_check=cancel_check,
        )
        validate_proposal(text, document)
        return {"success": True, "device": backend.device, "dtype": "gguf", "multimodal": True}
    finally:
        backend.close()
        if image_name:
            Path(image_name).unlink(missing_ok=True)


def _smoke_test_transformers_whisper(
    *,
    package_root: Path,
    hardware: Mapping[str, Any],
    cancel_check: Callable[[], bool] | None = None,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    from edmg_ai_service.asr import transcribe_detailed, unload_transformers_whisper_models

    device = ModelRuntimeRegistry._device(hardware)
    sample_rate = 16_000
    sample_count = sample_rate
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
            temporary_name = temporary.name
        with wave.open(temporary_name, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(b"\x00\x00" * sample_count)
        result = transcribe_detailed(
            temporary_name,
            model_size=str(package_root),
            provider="transformers_whisper",
            device=device,
            fallback_to_whisper=False,
            cancel_check=cancel_check,
        )
        if not isinstance(result.get("text"), str) or not isinstance(result.get("segments"), list):
            raise RuntimeError("Whisper returned an invalid transcription result")
        return {
            "success": True,
            "device": result.get("device"),
            "dtype": result.get("compute_type"),
            "duration_s": result.get("duration_s"),
            "segment_count": result.get("segment_count"),
        }
    finally:
        unload_transformers_whisper_models()
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


class ModelRuntimeRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        package_id = adapter.descriptor.package_id
        if package_id in self._adapters:
            raise ValueError(f"Runtime adapter already registered: {package_id}")
        self._adapters[package_id] = adapter

    def adapter(self, package_id: str) -> RuntimeAdapter:
        try:
            return self._adapters[package_id]
        except KeyError as exc:
            raise KeyError(f"No runtime adapter is registered for {package_id}") from exc

    def descriptors(self) -> list[dict[str, Any]]:
        return [asdict(self._adapters[key].descriptor) for key in sorted(self._adapters)]

    @staticmethod
    def _number(hardware: Mapping[str, Any], key: str) -> float:
        try:
            value = float(hardware.get(key) or 0)
            return value if math.isfinite(value) else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _dependency_status(modules: tuple[str, ...]) -> tuple[dict[str, bool], dict[str, str]]:
        available: dict[str, bool] = {}
        versions: dict[str, str] = {}
        for module in modules:
            try:
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False
            available[module] = found
            if found:
                distribution = module.replace("_", "-")
                try:
                    versions[module] = importlib.metadata.version(distribution)
                except importlib.metadata.PackageNotFoundError:
                    versions[module] = "unknown"
        return available, versions

    @staticmethod
    def _device(hardware: Mapping[str, Any]) -> str:
        requested = str(hardware.get("device") or "").strip().lower()
        if requested.startswith("cuda:"):
            return requested
        return "cuda:0" if str(hardware.get("backend") or "").lower() == "cuda" else "cpu"

    @staticmethod
    def _fingerprint(
        descriptor: RuntimeDescriptor,
        package_validation: Mapping[str, Any],
        dependency_versions: Mapping[str, str],
        hardware: Mapping[str, Any],
    ) -> str:
        payload = {
            "registry_version": REGISTRY_VERSION,
            "descriptor": asdict(descriptor),
            "package": {
                "repo_id": package_validation.get("repo_id"),
                "revision": package_validation.get("revision"),
                "files": package_validation.get("files", {}),
            },
            "dependencies": dict(dependency_versions),
            "hardware": {
                "backend": hardware.get("backend"),
                "device": ModelRuntimeRegistry._device(hardware),
                "device_name": hardware.get("device_name"),
            },
        }
        if descriptor.package_id == "hf_hunyuan_video15_internal":
            from .internal_video_models import hunyuan_runner_config
            runner = hunyuan_runner_config()
            payload["external_runtime"] = {
                "mode": runner.mode, "python": runner.python, "repo": runner.repo,
                "distro": runner.distro, "companions": dict(runner.companions),
            }
        elif descriptor.package_id == "hf_ltx_25_distilled_internal":
            from .ltx_25_runtime import runtime_identity
            try:
                payload["external_runtime"] = runtime_identity()
            except Exception:
                payload["external_runtime"] = {
                    "python": os.environ.get("EDMG_LTX25_PYTHON", "").strip(),
                    "ltx_pipelines_version": "unavailable",
                }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def status(
        self,
        package_id: str,
        *,
        package_root: Path | None = None,
        package_validation: Mapping[str, Any] | None = None,
        hardware: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapter(package_id)
        descriptor = adapter.descriptor
        hw = dict(hardware or {})
        validation = dict(package_validation or {})
        installed = bool(package_root and validation.get("valid"))
        dependencies, dependency_versions = self._dependency_status(descriptor.dependency_modules)
        blockers: list[str] = []
        validation_level = 1 if installed else 0

        if not installed:
            blockers.append("Install or revalidate the required package files in Models.")
        missing_dependencies = [name for name, found in dependencies.items() if not found]
        blockers.extend(f"Missing runtime dependency: {name}" for name in missing_dependencies)

        backend = str(hw.get("backend") or "").lower()
        hardware_known = bool(hw)
        hardware_issues: list[str] = []
        if hardware_known and backend not in descriptor.supported_devices:
            hardware_issues.append(
                f"Requires one of these compute backends: {', '.join(descriptor.supported_devices)}."
            )
        if descriptor.minimum_vram_gb and (
            backend != "cuda" or self._number(hw, "vram_gb") < descriptor.minimum_vram_gb
        ):
            hardware_issues.append(
                f"Requires CUDA and at least {descriptor.minimum_vram_gb:g} GB VRAM on one GPU."
            )
        if hardware_known and self._number(hw, "ram_gb") < descriptor.minimum_ram_gb:
            hardware_issues.append(
                f"Requires at least {descriptor.minimum_ram_gb:g} GB system RAM."
            )
        blockers.extend(hardware_issues)

        dependencies_ready = not missing_dependencies
        hardware_compatible = not hardware_issues
        if installed and dependencies_ready and hardware_compatible:
            validation_level = 2

        config_issues: list[str] = []
        if installed and package_root is not None:
            config_issues = adapter.validate_config(package_root)
            blockers.extend(config_issues)
            if not config_issues and validation_level >= 2:
                validation_level = 3

        if descriptor.implementation_error:
            blockers.append(descriptor.implementation_error)
        if not descriptor.adapter_ready:
            blockers.append(f"The {descriptor.runtime_backend} runtime adapter is not available in this build.")

        fingerprint = self._fingerprint(descriptor, validation, dependency_versions, hw)
        receipt: dict[str, Any] = {}
        if package_root is not None:
            try:
                value = json.loads((package_root / RUNTIME_RECEIPT).read_text(encoding="utf-8"))
                receipt = value if isinstance(value, dict) else {}
            except (OSError, ValueError, TypeError):
                receipt = {}
        smoke_valid = bool(
            receipt.get("success") is True
            and receipt.get("validation_level") == 5
            and receipt.get("fingerprint") == fingerprint
        )
        if smoke_valid and descriptor.adapter_ready and not blockers:
            validation_level = 5
        elif installed and descriptor.adapter_ready and validation_level == 3:
            blockers.append("Run the model runtime smoke test to initialize and qualify this installation.")

        runtime_ready = validation_level == 5 and not blockers
        state: ValidationState = (
            "runtime_ready" if runtime_ready else
            "installed_runtime_unavailable" if installed else
            "not_installed"
        )
        return {
            "package_id": package_id,
            "model_family": descriptor.model_family,
            "format": descriptor.model_format,
            "runtime_backend": descriptor.runtime_backend,
            "runtime_version": descriptor.runtime_version,
            "role": descriptor.role,
            "capabilities": list(descriptor.capabilities),
            "required_components": list(descriptor.required_components),
            "supported_devices": list(descriptor.supported_devices),
            "recommended_dtype": descriptor.recommended_dtype,
            "installed": installed,
            "runtime_ready": runtime_ready,
            "runtime_state": state,
            "validation_level": validation_level,
            "adapter_ready": descriptor.adapter_ready,
            "dependencies_ready": dependencies_ready,
            "dependencies": dependencies,
            "dependency_versions": dependency_versions,
            "hardware_known": hardware_known,
            "hardware_compatible": hardware_compatible,
            "hardware_requirements": {
                "min_vram_gb": descriptor.minimum_vram_gb,
                "min_ram_gb": descriptor.minimum_ram_gb,
                "per_device_vram": True,
                "provisional": False,
            },
            "device": self._device(hw) if hardware_known else None,
            "dtype": descriptor.recommended_dtype if hardware_known else None,
            "smoke_test_supported": descriptor.smoke_test_supported,
            "smoke_tested": smoke_valid,
            "fingerprint": fingerprint,
            "error": blockers[0] if blockers else None,
            "blockers": list(dict.fromkeys(blockers)),
            "config_issues": config_issues,
        }

    def smoke_test(
        self,
        package_id: str,
        *,
        package_root: Path,
        package_validation: Mapping[str, Any],
        hardware: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        adapter = self.adapter(package_id)
        status = self.status(
            package_id,
            package_root=package_root,
            package_validation=package_validation,
            hardware=hardware,
        )
        if status["validation_level"] < 3:
            raise RuntimeError(status["error"] or "Runtime prerequisites are incomplete")
        if adapter.smoke_test is None:
            raise RuntimeError("This runtime does not provide a smoke test")
        result = dict(adapter.smoke_test(package_root=package_root, hardware=dict(hardware), **kwargs))
        if result.get("success") is not True:
            raise RuntimeError(str(result.get("error") or "Runtime smoke test did not return a valid result"))
        receipt = {
            "schema_version": 1,
            "validation_level": 5,
            "success": True,
            "fingerprint": status["fingerprint"],
            "runtime_backend": adapter.descriptor.runtime_backend,
            "result": result,
        }
        temporary = package_root / f".{RUNTIME_RECEIPT}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, package_root / RUNTIME_RECEIPT)
        return self.status(
            package_id,
            package_root=package_root,
            package_validation=package_validation,
            hardware=hardware,
        )


def _descriptor(
    package_id: str,
    family: str,
    model_format: str,
    backend: str,
    role: str,
    capabilities: tuple[str, ...],
    components: tuple[str, ...],
    modules: tuple[str, ...],
    devices: tuple[str, ...],
    dtype: str,
    vram: float,
    ram: float,
    error: str,
) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        package_id=package_id,
        model_family=family,
        model_format=model_format,
        runtime_backend=backend,
        runtime_version="1",
        role=role,
        capabilities=capabilities,
        required_components=components,
        dependency_modules=modules,
        supported_devices=devices,
        recommended_dtype=dtype,
        minimum_vram_gb=vram,
        minimum_ram_gb=ram,
        adapter_ready=False,
        smoke_test_supported=False,
        implementation_error=error,
    )


def create_default_registry() -> ModelRuntimeRegistry:
    registry = ModelRuntimeRegistry()
    for package_id, descriptor, validator in (
        (
            "hf_qwen3_vl_8b_gguf_director",
            RuntimeDescriptor(
                package_id="hf_qwen3_vl_8b_gguf_director", model_family="qwen3_vl", model_format="gguf",
                runtime_backend="llama_cpp_qwen3_vl", runtime_version="llama.cpp-v0.4.0",
                role="director", capabilities=("text-generation", "vision-language", "structured-director"),
                required_components=("model_gguf", "vision_projector", "llama_server"),
                dependency_modules=(), supported_devices=("cpu", "cuda"), recommended_dtype="q4_k_m",
                minimum_vram_gb=0, minimum_ram_gb=16, adapter_ready=True, smoke_test_supported=True,
            ),
            _validate_qwen,
        ),
        (
            "hf_qwen3_vl_30b_gguf_director",
            RuntimeDescriptor(
                package_id="hf_qwen3_vl_30b_gguf_director", model_family="qwen3_vl", model_format="gguf",
                runtime_backend="llama_cpp_qwen3_vl", runtime_version="llama.cpp-v0.4.0",
                role="director", capabilities=("text-generation", "vision-language", "structured-director"),
                required_components=("model_gguf", "vision_projector", "llama_server"),
                dependency_modules=(), supported_devices=("cpu", "cuda"), recommended_dtype="q4_k_m",
                minimum_vram_gb=0, minimum_ram_gb=32, adapter_ready=True, smoke_test_supported=True,
            ),
            _validate_qwen,
        ),
        (
            "hf_hunyuan_video15_internal",
            RuntimeDescriptor(
                package_id="hf_hunyuan_video15_internal", model_family="hunyuan_video15",
                model_format="native_hunyuan15", runtime_backend="hyvideo15_linux_subprocess",
                runtime_version="official-create-pipeline-v1", role="video",
                capabilities=("text-to-video", "image-to-video"),
                required_components=("transformer", "scheduler", "vae", "external_qwen_text_encoder",
                                     "external_byt5", "external_glyph", "external_siglip"),
                dependency_modules=(), supported_devices=("cuda",), recommended_dtype="bfloat16",
                minimum_vram_gb=14, minimum_ram_gb=64, adapter_ready=True, smoke_test_supported=True,
            ),
            _validate_hunyuan,
        ),
        (
            "hf_whisper_large_v3_turbo_internal",
            RuntimeDescriptor(
                package_id="hf_whisper_large_v3_turbo_internal",
                model_family="whisper",
                model_format="transformers",
                runtime_backend="transformers_whisper",
                runtime_version="1",
                role="asr",
                capabilities=("transcription", "language-detection", "timestamps"),
                required_components=("model", "processor", "tokenizer"),
                dependency_modules=("torch", "transformers", "librosa"),
                supported_devices=("cpu", "cuda"),
                recommended_dtype="float16",
                minimum_vram_gb=0,
                minimum_ram_gb=8,
                adapter_ready=True,
                smoke_test_supported=True,
            ),
            _validate_whisper,
        ),
        (
            "hf_ltx_25_distilled_internal",
            RuntimeDescriptor(
                package_id="hf_ltx_25_distilled_internal", model_family="ltx_25", model_format="ltx25",
                runtime_backend="ltx_pipelines_distilled", runtime_version="ltx-pipelines==1.3.0",
                role="video", capabilities=("text-to-video", "image-to-video", "audio"),
                required_components=("transformer", "gemma_text_encoder", "video_vae", "audio_vae", "duration_head", "spatial_upsampler"),
                dependency_modules=(), supported_devices=("cuda",), recommended_dtype="bfloat16",
                minimum_vram_gb=5, minimum_ram_gb=36, adapter_ready=True, smoke_test_supported=True,
            ),
            _validate_ltx,
        ),
    ):
        registry.register(RuntimeAdapter(
            descriptor=descriptor,
            validate_config=validator,
            smoke_test=(
                _smoke_test_transformers_whisper
                if package_id == "hf_whisper_large_v3_turbo_internal"
                else _smoke_test_hunyuan
                if package_id == "hf_hunyuan_video15_internal"
                else _smoke_test_qwen_gguf
                if package_id in {"hf_qwen3_vl_8b_gguf_director", "hf_qwen3_vl_30b_gguf_director"}
                else _smoke_test_ltx_25
                if package_id == "hf_ltx_25_distilled_internal"
                else None
            ),
        ))
    return registry


DEFAULT_RUNTIME_REGISTRY = create_default_registry()
