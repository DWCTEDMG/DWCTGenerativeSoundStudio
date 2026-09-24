from __future__ import annotations

import json

from edmg_studio_backend.runtime.adapters import ComponentAdapterRegistry
from edmg_studio_backend.runtime.cache import EngineCache, build_engine_identity, engine_key
from edmg_studio_backend.runtime.routes import CompilerAvailability, resolve_runtime_route
from edmg_studio_backend.runtime.sources import SourceKind, classify_model_source
from edmg_studio_backend.runtime.prebuilt import admit_prebuilt_engine


def test_classifies_supported_source_formats(tmp_path):
    cases = {
        "model.onnx": SourceKind.ONNX,
        "model.pt": SourceKind.PYTORCH_CHECKPOINT,
        "model.pth": SourceKind.PYTORCH_CHECKPOINT,
        "model.engine": SourceKind.TENSORRT_ENGINE,
        "model.plan": SourceKind.TENSORRT_ENGINE,
        "model.gguf": SourceKind.GGUF,
    }
    for filename, expected in cases.items():
        root = tmp_path / filename.replace(".", "_")
        root.mkdir()
        (root / filename).write_bytes(filename.encode())
        result = classify_model_source(
            root, model_id="fixture", model_family="sd15", component="unet"
        )
        assert result.kind is expected
        assert result.hashes


def test_huggingface_safetensors_requires_config_and_complete_shards(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"architectures": ["UNet2DConditionModel"]}), encoding="utf-8"
    )
    (root / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {
            "a": "model-00001-of-00002.safetensors",
            "b": "model-00002-of-00002.safetensors",
        }}), encoding="utf-8"
    )
    (root / "model-00001-of-00002.safetensors").write_bytes(b"one")

    missing = classify_model_source(
        root, model_id="fixture", model_family="sd15", component="unet"
    )
    assert missing.kind is SourceKind.UNKNOWN
    assert "model-00002-of-00002.safetensors" in (missing.reason or "")

    (root / "model-00002-of-00002.safetensors").write_bytes(b"two")
    complete = classify_model_source(
        root, model_id="fixture", model_family="sd15", component="unet"
    )
    assert complete.kind is SourceKind.HUGGINGFACE
    assert complete.architecture == "UNet2DConditionModel"


def test_ambiguous_directory_fails_without_admitted_format(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"onnx")
    (tmp_path / "model.plan").write_bytes(b"plan")
    result = classify_model_source(
        tmp_path, model_id="fixture", model_family="sd15", component="unet"
    )
    assert result.kind is SourceKind.UNKNOWN
    assert "ambiguous" in (result.reason or "").lower()


def test_routes_onnx_torch_hf_prebuilt_and_gguf(tmp_path):
    registry = ComponentAdapterRegistry()
    sd15 = registry.require("sd15", "unet")
    compilers = CompilerAvailability(torch_tensorrt=True, torch_compile_tensorrt=True)

    expectations = {
        "model.onnx": "onnx_parser",
        "model.pt": "torch_tensorrt",
        "model.engine": "prebuilt_engine",
    }
    for filename, expected in expectations.items():
        root = tmp_path / filename.replace(".", "_")
        root.mkdir()
        (root / filename).write_bytes(filename.encode())
        source = classify_model_source(
            root, model_id="fixture", model_family="sd15", component="unet"
        )
        decision = resolve_runtime_route(source, sd15, compilers)
        assert decision.selected_route == expected
        assert decision.supported

    gguf_root = tmp_path / "gguf"
    gguf_root.mkdir()
    (gguf_root / "model.gguf").write_bytes(b"gguf")
    gguf = classify_model_source(
        gguf_root, model_id="qwen", model_family="qwen", component="language_model"
    )
    decision = resolve_runtime_route(
        gguf, registry.get("qwen", "language_model"), compilers
    )
    assert decision.selected_runtime == "llama_cpp"
    assert decision.selected_route == "llama_cpp"
    assert decision.supported


def test_missing_torch_tensorrt_is_truthful_fallback(tmp_path):
    (tmp_path / "model.pth").write_bytes(b"checkpoint")
    source = classify_model_source(
        tmp_path, model_id="fixture", model_family="sd15", component="unet"
    )
    decision = resolve_runtime_route(
        source,
        ComponentAdapterRegistry().require("sd15", "unet"),
        CompilerAvailability(),
    )
    assert not decision.supported
    assert decision.selected_runtime == "existing_model_runtime"
    assert "Torch-TensorRT" in (decision.reason or "")


def test_multi_source_cache_identity_tracks_route_compiler_and_source(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"graph-v1")
    source = classify_model_source(
        tmp_path, model_id="fixture", model_family="sd15", component="unet"
    )
    first = build_engine_identity(
        source=source, route="onnx_parser", compiler="tensorrt",
        versions={"tensorrt": "10.15"}, precision="fp16",
        profile={"input": [1, 4, 64, 64]}, device={"compute_capability": "8.6"},
    )
    second = build_engine_identity(
        source=source, route="onnx_parser", compiler="tensorrt",
        versions={"tensorrt": "11.0"}, precision="fp16",
        profile={"input": [1, 4, 64, 64]}, device={"compute_capability": "8.6"},
    )
    assert first["source_kind"] == "onnx"
    assert "architecture" not in first
    assert engine_key(first) != engine_key(second)


def test_prebuilt_engine_is_published_only_after_binding_and_execution_validation(tmp_path):
    engine_path = tmp_path / "fixture.plan"
    engine_path.write_bytes(b"serialized-engine")

    class Executor:
        inputs = ["sample"]
        outputs = ["latent"]

    executor, manifest, state = admit_prebuilt_engine(
        data_dir=tmp_path / "data", engine_path=engine_path,
        identity={"model": "sd15", "component": "unet", "route": "prebuilt_engine"},
        device=0, expected_inputs={"sample"}, expected_outputs={"latent"},
        validate=lambda value: {"passed": True, "finite": True},
        executor_factory=lambda _blob, _device: Executor(),
    )
    assert executor.inputs == ["sample"]
    assert manifest["state"] == "ready"
    assert manifest["admitted_prebuilt"] is True
    assert state == "admitted"


def test_prebuilt_engine_binding_mismatch_is_not_published(tmp_path):
    engine_path = tmp_path / "fixture.engine"
    engine_path.write_bytes(b"serialized-engine")

    class Executor:
        inputs = ["wrong"]
        outputs = ["latent"]

    import pytest
    with pytest.raises(RuntimeError, match="bindings"):
        admit_prebuilt_engine(
            data_dir=tmp_path / "data", engine_path=engine_path,
            identity={"model": "sd15", "component": "unet", "route": "prebuilt_engine"},
            device=0, expected_inputs={"sample"}, expected_outputs={"latent"},
            validate=lambda value: {"passed": True},
            executor_factory=lambda _blob, _device: Executor(),
        )
    assert EngineCache(tmp_path / "data").entries() == []
