"""Admission of managed prebuilt TensorRT engines inside the runtime worker."""
from __future__ import annotations

from pathlib import Path

from .cache import EngineCache, engine_key


def admit_prebuilt_engine(*, data_dir: Path, engine_path: Path, identity: dict,
                          device: int, expected_inputs: set[str], expected_outputs: set[str],
                          validate, executor_factory=None):
    path = Path(engine_path).resolve()
    if path.suffix.lower() not in {".engine", ".plan"} or not path.is_file() or path.is_symlink():
        raise RuntimeError("Prebuilt TensorRT engine must be a managed .engine or .plan file")
    blob = path.read_bytes()
    if not blob:
        raise RuntimeError("Prebuilt TensorRT engine is empty")
    if executor_factory is None:
        from .executor import TensorExecutor
        executor_factory = TensorExecutor
    executor = executor_factory(blob, device)
    actual_inputs = set(executor.inputs)
    actual_outputs = set(executor.outputs)
    if actual_inputs != set(expected_inputs) or actual_outputs != set(expected_outputs):
        raise RuntimeError(
            "Prebuilt TensorRT bindings do not match the registered component contract; "
            f"inputs={sorted(actual_inputs)}, outputs={sorted(actual_outputs)}"
        )
    validation = validate(executor)
    if validation.get("passed") is not True:
        raise RuntimeError("Prebuilt TensorRT execution validation failed")
    cache = EngineCache(data_dir)
    found = cache.lookup(identity)
    if found:
        return executor, found[1], "ready"
    manifest = cache.publish(identity, blob, validation, {"beneficial": False, "scope": "prebuilt_admission"})
    manifest = cache.state(engine_key(identity), identity, "ready",
                           engine_sha256=manifest["engine_sha256"], validation=validation,
                           benchmark=manifest["benchmark"], size_bytes=len(blob),
                           admitted_prebuilt=True, source="edmg_local_build")
    return executor, manifest, "admitted"
