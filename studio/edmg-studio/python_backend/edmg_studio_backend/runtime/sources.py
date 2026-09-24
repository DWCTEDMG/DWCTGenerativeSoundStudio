"""Side-effect-free model source detection for runtime routing."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .cache import digest_file


class SourceKind(str, Enum):
    ONNX = "onnx"
    PYTORCH_CHECKPOINT = "pytorch_checkpoint"
    HUGGINGFACE = "huggingface"
    TENSORRT_ENGINE = "tensorrt_engine"
    GGUF = "gguf"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelSourceDescriptor:
    model_id: str
    model_family: str
    component: str
    root: Path
    kind: SourceKind
    files: tuple[Path, ...] = ()
    hashes: dict[str, str] = field(default_factory=dict)
    architecture: str | None = None
    revision: str | None = None
    reason: str | None = None

    def identity_fields(self) -> dict[str, object]:
        value: dict[str, object] = {
            "source_kind": self.kind.value,
            "source_hashes": dict(sorted(self.hashes.items())),
        }
        if self.architecture:
            value["architecture"] = self.architecture
        if self.revision:
            value["revision"] = self.revision
        return value


def _descriptor(root: Path, *, kind: SourceKind, files: list[Path], model_id: str,
                model_family: str, component: str, architecture: str | None = None,
                revision: str | None = None, reason: str | None = None,
                hash_content: bool = True) -> ModelSourceDescriptor:
    return ModelSourceDescriptor(
        model_id=model_id, model_family=model_family, component=component, root=root,
        kind=kind, files=tuple(files),
        hashes={path.relative_to(root).as_posix(): digest_file(path) for path in files if path.is_file()} if hash_content else {},
        architecture=architecture, revision=revision, reason=reason,
    )


def classify_model_source(model_root: Path, *, model_id: str, model_family: str,
                          component: str, admitted_format: str | None = None,
                          hash_content: bool = True) -> ModelSourceDescriptor:
    root = Path(model_root).expanduser().resolve()
    if not root.is_dir():
        return _descriptor(root, kind=SourceKind.UNKNOWN, files=[], model_id=model_id,
                           model_family=model_family, component=component,
                           reason="Managed model root is unavailable")

    config_path = root / "config.json"
    index_paths = sorted(root.glob("*.safetensors.index.json"))
    safetensors = sorted(root.glob("*.safetensors"))
    if config_path.is_file() and (index_paths or safetensors):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            architectures = config.get("architectures") or []
            architecture = str(architectures[0]) if architectures else str(config.get("_class_name") or "") or None
            files = [config_path]
            if index_paths:
                index_path = index_paths[0]
                index = json.loads(index_path.read_text(encoding="utf-8"))
                shard_names = sorted(set((index.get("weight_map") or {}).values()))
                missing = [name for name in shard_names if not (root / name).is_file()]
                if missing:
                    return _descriptor(root, kind=SourceKind.UNKNOWN, files=[config_path, index_path],
                                       model_id=model_id, model_family=model_family, component=component,
                                       architecture=architecture,
                                       reason="Missing safetensors shard(s): " + ", ".join(missing))
                files.extend([index_path, *(root / name for name in shard_names)])
            else:
                files.extend(safetensors)
            return _descriptor(root, kind=SourceKind.HUGGINGFACE, files=files, model_id=model_id,
                               model_family=model_family, component=component, architecture=architecture,
                               revision=str(config.get("_commit_hash") or "") or None,
                               hash_content=hash_content)
        except (OSError, ValueError, TypeError) as exc:
            return _descriptor(root, kind=SourceKind.UNKNOWN, files=[], model_id=model_id,
                               model_family=model_family, component=component,
                               reason=f"Invalid Hugging Face model metadata: {exc}")

    candidates = {
        SourceKind.ONNX: sorted(root.glob("*.onnx")),
        SourceKind.PYTORCH_CHECKPOINT: sorted([*root.glob("*.pt"), *root.glob("*.pth")]),
        SourceKind.TENSORRT_ENGINE: sorted([*root.glob("*.engine"), *root.glob("*.plan")]),
        SourceKind.GGUF: sorted(root.glob("*.gguf")),
    }
    populated = [(kind, files) for kind, files in candidates.items() if files]
    aliases = {
        "onnx": SourceKind.ONNX, "pt": SourceKind.PYTORCH_CHECKPOINT,
        "pth": SourceKind.PYTORCH_CHECKPOINT, "pytorch": SourceKind.PYTORCH_CHECKPOINT,
        "engine": SourceKind.TENSORRT_ENGINE, "plan": SourceKind.TENSORRT_ENGINE,
        "tensorrt": SourceKind.TENSORRT_ENGINE, "gguf": SourceKind.GGUF,
    }
    admitted = aliases.get(str(admitted_format or "").lower())
    if admitted:
        files = candidates.get(admitted, [])
        if files:
            return _descriptor(root, kind=admitted, files=files, model_id=model_id,
                               model_family=model_family, component=component, hash_content=hash_content)
    if len(populated) > 1:
        return _descriptor(root, kind=SourceKind.UNKNOWN, files=[], model_id=model_id,
                           model_family=model_family, component=component,
                           reason="Ambiguous managed model directory contains multiple source formats")
    if len(populated) == 1:
        kind, files = populated[0]
        return _descriptor(root, kind=kind, files=files, model_id=model_id,
                           model_family=model_family, component=component, hash_content=hash_content)
    return _descriptor(root, kind=SourceKind.UNKNOWN, files=[], model_id=model_id,
                       model_family=model_family, component=component,
                       reason="No supported model source was detected")
