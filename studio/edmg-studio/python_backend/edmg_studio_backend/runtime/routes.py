"""Truthful route resolution without importing optional native runtimes."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from .sources import ModelSourceDescriptor, SourceKind


@dataclass(frozen=True)
class CompilerAvailability:
    torch_tensorrt: bool = False
    torch_compile_tensorrt: bool = False


@dataclass(frozen=True)
class RuntimeRouteDecision:
    requested_runtime: str = "tensorrt"
    selected_runtime: str = "pytorch_cuda"
    selected_route: str = "existing_runtime"
    compiler: str | None = None
    supported: bool = False
    reason: str | None = None
    fallback_runtime: str = "pytorch_cuda"


def discover_compilers(find_spec=importlib.util.find_spec) -> CompilerAvailability:
    torch_trt = find_spec("torch_tensorrt") is not None
    compile_backend = False
    if torch_trt and find_spec("torch") is not None:
        try:
            import torch
            compile_backend = any(name in {"tensorrt", "torch_tensorrt"}
                                  for name in torch._dynamo.list_backends())
        except Exception:
            compile_backend = False
    return CompilerAvailability(torch_tensorrt=torch_trt, torch_compile_tensorrt=compile_backend)


def resolve_runtime_route(descriptor: ModelSourceDescriptor, adapter,
                          compilers: CompilerAvailability) -> RuntimeRouteDecision:
    fallback = getattr(adapter, "fallback_runtime", "pytorch_cuda") if adapter else "pytorch_cuda"
    if descriptor.kind is SourceKind.GGUF:
        return RuntimeRouteDecision(selected_runtime="llama_cpp", selected_route="llama_cpp",
                                    supported=True, fallback_runtime="llama_cpp",
                                    reason="GGUF is executed by the dedicated llama.cpp provider")
    if descriptor.kind is SourceKind.UNKNOWN:
        return RuntimeRouteDecision(fallback_runtime=fallback, selected_runtime=fallback,
                                    reason=descriptor.reason or "Unsupported model source")
    if adapter is None or descriptor.kind.value not in getattr(adapter, "source_kinds", ()):
        return RuntimeRouteDecision(fallback_runtime=fallback, selected_runtime=fallback,
                                    reason=f"No registered TensorRT adapter for {descriptor.kind.value}")
    if descriptor.kind is SourceKind.ONNX:
        return RuntimeRouteDecision(selected_runtime="tensorrt", selected_route="onnx_parser",
                                    compiler="tensorrt", supported=True, fallback_runtime=fallback)
    if descriptor.kind is SourceKind.TENSORRT_ENGINE:
        return RuntimeRouteDecision(selected_runtime="tensorrt", selected_route="prebuilt_engine",
                                    compiler="tensorrt", supported=True, fallback_runtime=fallback)
    if descriptor.kind in {SourceKind.PYTORCH_CHECKPOINT, SourceKind.HUGGINGFACE}:
        if descriptor.kind is SourceKind.HUGGINGFACE and descriptor.architecture:
            admitted = getattr(adapter, "architectures", ())
            if admitted and descriptor.architecture not in admitted:
                return RuntimeRouteDecision(fallback_runtime=fallback, selected_runtime=fallback,
                                            reason=f"Architecture {descriptor.architecture} has no registered loader")
        if compilers.torch_tensorrt:
            route = "huggingface_torch_tensorrt" if descriptor.kind is SourceKind.HUGGINGFACE else "torch_tensorrt"
            return RuntimeRouteDecision(selected_runtime="tensorrt", selected_route=route,
                                        compiler="torch_tensorrt", supported=True, fallback_runtime=fallback)
        if compilers.torch_compile_tensorrt:
            return RuntimeRouteDecision(selected_runtime="tensorrt", selected_route="torch_compile_tensorrt",
                                        compiler="torch_compile:tensorrt", supported=True, fallback_runtime=fallback)
        return RuntimeRouteDecision(fallback_runtime=fallback, selected_runtime=fallback,
                                    reason="Torch-TensorRT compiler/backend is not installed")
    return RuntimeRouteDecision(fallback_runtime=fallback, selected_runtime=fallback,
                                reason="Unsupported TensorRT source route")
