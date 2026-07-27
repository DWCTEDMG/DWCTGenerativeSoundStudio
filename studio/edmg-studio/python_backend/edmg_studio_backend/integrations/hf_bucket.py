"""Hugging Face bucket model cache.

Implements the same model-cache contract used by :class:`S3ModelCache`
(``edmg_studio_backend.integrations.aws``) so the existing
:class:`ModelManager` can store/restore weights in a Hugging Face *bucket*
(``hf://buckets/<namespace>/<name>``) without any other code changes.

Storage layout
---------------
The bucket is treated as a 1:1 *mirror* of the Studio models directory.
A local file at ``<models_dir>/checkpoints/foo.safetensors`` maps to the
bucket path ``checkpoints/foo.safetensors`` (optionally under a configured
prefix). This matches the layout produced by ``hf sync <models_dir>
hf://buckets/<id>`` so weights uploaded that way are picked up directly.

Enable with environment variables (see ``from_env``)::

    EDMG_HF_BUCKET_MODEL_CACHE=1
    EDMG_HF_BUCKET_ID=namespace/bucket-name
    # optional:
    EDMG_HF_BUCKET_PREFIX=
    EDMG_STUDIO_MODELS_DIR=...   # already set by the launcher
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..services.hf_auth import resolve_hf_token as _resolve_hf_auth_token

logger = logging.getLogger(__name__)
_HELPER_CONTRACT_VERSION = 1
_HELPER_BASENAME = "edmg-hf-bucket-helper.exe" if os.name == "nt" else "edmg-hf-bucket-helper"
_BUCKET_SYNC_EXCLUDES = [
    ".cache/**",
    "**/.cache/**",
    "*.incomplete",
    "**/*.incomplete",
    "*.partial",
    "**/*.partial",
    "*.part",
    "**/*.part",
    "*.tmp",
    "**/*.tmp",
]
_SNAPSHOT_MANIFEST_NAME = "edmg-model-cache-manifest.json"
_SNAPSHOT_MANIFEST_SCHEMA_VERSION = 1
_SNAPSHOT_SELECTION_PROFILE = "default-inference-v1"
_PARTIAL_FILE_SUFFIXES = (".incomplete", ".partial", ".part", ".tmp")
_COMPONENT_METADATA_NAMES = frozenset(
    {
        "added_tokens.json",
        "config.json",
        "feature_extractor_config.json",
        "generation_config.json",
        "merges.txt",
        "preprocessor_config.json",
        "processor_config.json",
        "scheduler_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer_config.json",
        "vocab.json",
        "vocab.txt",
    }
)
_WEIGHT_BASES = (
    "diffusion_pytorch_model",
    "model",
    "pytorch_model",
)
_TEXT_WEIGHT_BASES = (
    "model",
    "pytorch_model",
    "diffusion_pytorch_model",
)
_CONFIG_ONLY_COMPONENT_MARKERS = (
    "feature_extractor",
    "image_processor",
    "processor",
    "scheduler",
    "tokenizer",
)


class HFBucketCapabilityError(RuntimeError):
    """The isolated Bucket transport is not installed or is incompatible."""


class HFBucketOperationError(RuntimeError):
    """A Bucket transport operation failed."""


@dataclass(frozen=True)
class _SnapshotPlan:
    files: tuple[str, ...]
    kind: str


def _snapshot_path(path: str) -> str:
    normalized = _normalize_remote(path)
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("../")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return ""
    return normalized


def _is_partial_or_cache_path(path: str) -> bool:
    normalized = _snapshot_path(path)
    if not normalized:
        return True
    parts = tuple(part.lower() for part in normalized.split("/"))
    return ".cache" in parts or parts[-1].endswith(_PARTIAL_FILE_SUFFIXES)


def _is_disallowed_variant_path(path: str) -> bool:
    normalized = _snapshot_path(path).lower()
    if not normalized:
        return True
    parts = normalized.split("/")
    name = parts[-1]
    if any(part in {"flax", "onnx", "openvino"} for part in parts[:-1]):
        return True
    if any(marker in name for marker in (".fp16.", ".bf16.", ".fp32.", "non_ema", "non-ema")):
        return True
    return name.endswith((".gguf", ".msgpack", ".onnx", ".onnx_data", ".xml"))


def _component_metadata(paths: set[str], component: str) -> set[str]:
    prefix = f"{component}/"
    return {
        path
        for path in paths
        if path.startswith(prefix)
        and "/" not in path[len(prefix) :]
        and path.rsplit("/", 1)[-1].lower() in _COMPONENT_METADATA_NAMES
        and not _is_partial_or_cache_path(path)
    }


def _complete_sharded_weight_set(
    component_files: set[str],
    *,
    base: str,
    extension: str,
) -> tuple[str, ...]:
    index_name = f"{base}.{extension}.index.json"
    if index_name not in component_files:
        return ()
    shard_pattern = re.compile(
        rf"^{re.escape(base)}-(?P<number>[0-9]{{5}})-of-(?P<total>[0-9]{{5}})\.{re.escape(extension)}$"
    )
    shards: list[tuple[int, int, str]] = []
    for name in component_files:
        match = shard_pattern.fullmatch(name)
        if match:
            shards.append((int(match.group("number")), int(match.group("total")), name))
    if not shards:
        return ()
    totals = {total for _, total, _ in shards}
    if len(totals) != 1:
        return ()
    total = totals.pop()
    if total < 1 or {number for number, _, _ in shards} != set(range(1, total + 1)):
        return ()
    return (index_name, *(name for _, _, name in sorted(shards)))


def _select_default_weight_set(paths: set[str], component: str = "") -> tuple[str, ...]:
    prefix = f"{component}/" if component else ""
    component_files = {
        path[len(prefix) :]
        for path in paths
        if path.startswith(prefix)
        and "/" not in path[len(prefix) :]
        and not _is_partial_or_cache_path(path)
        and not _is_disallowed_variant_path(path)
    }
    bases = _TEXT_WEIGHT_BASES if "text_encoder" in component or component in {
        "image_encoder",
        "safety_checker",
    } else _WEIGHT_BASES
    for extension in ("safetensors", "bin"):
        for base in bases:
            unsharded = f"{base}.{extension}"
            if unsharded in component_files:
                return (f"{prefix}{unsharded}",)
            sharded = _complete_sharded_weight_set(
                component_files,
                base=base,
                extension=extension,
            )
            if sharded:
                return tuple(f"{prefix}{name}" for name in sharded)
    return ()


def _model_index_components(model_index: dict[str, Any]) -> list[tuple[str, Any]]:
    components: list[tuple[str, Any]] = []
    for name, descriptor in model_index.items():
        if str(name).startswith("_") or not isinstance(descriptor, (list, tuple)):
            continue
        if not descriptor or not any(item is not None for item in descriptor):
            continue
        normalized = _snapshot_path(str(name))
        if not normalized or "/" in normalized:
            raise HFBucketOperationError(
                f"Diffusers model_index.json contains an unsafe component name: {name!r}"
            )
        components.append((normalized, descriptor))
    if not components:
        raise HFBucketOperationError(
            "Diffusers model_index.json does not declare any runnable components"
        )
    return components


def _component_is_config_only(component: str, descriptor: Any) -> bool:
    lowered = component.lower()
    descriptor_text = " ".join(str(value) for value in descriptor).lower()
    return any(marker in lowered for marker in _CONFIG_ONLY_COMPONENT_MARKERS) or any(
        marker in descriptor_text
        for marker in ("featureextractor", "imageprocessor", "scheduler", "tokenizer")
    )


def _select_diffusers_snapshot(
    paths: set[str],
    model_index: dict[str, Any],
) -> _SnapshotPlan:
    if "model_index.json" not in paths:
        raise HFBucketOperationError("Diffusers bucket snapshot is missing model_index.json")
    selected = {"model_index.json"}
    for component, descriptor in _model_index_components(model_index):
        metadata = _component_metadata(paths, component)
        if not metadata:
            raise HFBucketOperationError(
                f"Diffusers bucket snapshot is missing metadata for component {component!r}"
            )
        selected.update(metadata)
        if _component_is_config_only(component, descriptor):
            continue
        weights = _select_default_weight_set(paths, component)
        if not weights:
            raise HFBucketOperationError(
                "Diffusers bucket snapshot has no exact default safetensors or bin weights "
                f"for component {component!r}; fp16/bf16/fp32, non-EMA, ONNX, OpenVINO, "
                "Flax, GGUF, and root checkpoint variants are intentionally not restored"
            )
        selected.update(weights)
    return _SnapshotPlan(tuple(sorted(selected)), "diffusers")


def _select_standalone_snapshot(paths: set[str]) -> _SnapshotPlan:
    metadata = {
        path
        for path in paths
        if "/" not in path
        and path.lower() in _COMPONENT_METADATA_NAMES
        and not _is_partial_or_cache_path(path)
    }
    if "config.json" not in metadata:
        raise HFBucketOperationError(
            "Bucket model directory is missing the required config.json metadata"
        )
    weights = _select_default_weight_set(paths)
    if not weights:
        raise HFBucketOperationError(
            "Bucket model directory has no exact default safetensors or bin weights; "
            "partial and alternate inference variants are not considered runnable"
        )
    return _SnapshotPlan(tuple(sorted(metadata | set(weights))), "standalone")


def _entry_expects_diffusers(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
    return (
        str(entry.get("kind") or "").strip().lower() == "diffusers"
        or str(target.get("folder") or "").strip().lower() == "diffusers"
    )


def _select_snapshot_plan(
    paths: set[str],
    *,
    model_index: dict[str, Any] | None,
    model_entry: dict[str, Any] | None = None,
) -> _SnapshotPlan:
    safe_paths = {
        normalized
        for path in paths
        if (normalized := _snapshot_path(path)) and not _is_partial_or_cache_path(normalized)
    }
    if model_index is not None:
        return _select_diffusers_snapshot(safe_paths, model_index)
    if "model_index.json" in safe_paths or _entry_expects_diffusers(model_entry):
        raise HFBucketOperationError(
            "Diffusers bucket snapshot is missing a readable model_index.json"
        )
    return _select_standalone_snapshot(safe_paths)


def _build_snapshot_manifest(
    plan: _SnapshotPlan,
    sizes: dict[str, int],
    *,
    model_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in plan.files:
        size = sizes.get(path)
        if not isinstance(size, int) or size <= 0:
            raise HFBucketOperationError(
                f"Cannot publish a model-cache manifest for missing or empty file: {path}"
            )
        files.append({"path": path, "size": size})
    return {
        "schema_version": _SNAPSHOT_MANIFEST_SCHEMA_VERSION,
        "selection_profile": _SNAPSHOT_SELECTION_PROFILE,
        "kind": plan.kind,
        "model_id": _first_string((model_entry or {}).get("id")) or None,
        "files": files,
    }


def _validate_snapshot_manifest(
    manifest: Any,
    plan: _SnapshotPlan,
    remote_sizes: dict[str, int | None],
) -> bool:
    if not isinstance(manifest, dict):
        return False
    if manifest.get("schema_version") != _SNAPSHOT_MANIFEST_SCHEMA_VERSION:
        return False
    if manifest.get("selection_profile") != _SNAPSHOT_SELECTION_PROFILE:
        return False
    if manifest.get("kind") != plan.kind:
        return False
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        return False
    declared: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            return False
        path = _snapshot_path(str(record.get("path") or ""))
        size = record.get("size")
        if (
            not path
            or path == _SNAPSHOT_MANIFEST_NAME
            or path in declared
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            return False
        declared[path] = size
    if set(declared) != set(plan.files):
        return False
    return all(
        isinstance(remote_sizes.get(path), int)
        and remote_sizes[path] == declared_size
        and declared_size > 0
        for path, declared_size in declared.items()
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_remote(path: str) -> str:
    return str(path or "").strip().strip("/").replace("\\", "/")


def parse_bucket_id(bucket: str) -> str:
    """Normalize a bucket reference into a bare ``namespace/name`` id.

    Tolerates a full ``hf://buckets/<namespace>/<name>`` URI being pasted in.
    """
    resolved = str(bucket or "").strip()
    if "buckets/" in resolved:
        resolved = resolved.split("buckets/", 1)[1]
    return resolved.strip().strip("/")


@dataclass(frozen=True)
class _TransportCommand:
    argv: tuple[str, ...]
    kind: str
    source: str


def _helper_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("EDMG_HF_BUCKET_HELPER", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise HFBucketCapabilityError(
                f"EDMG_HF_BUCKET_HELPER does not point to a file: {path}"
            )
        return [path]

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / _HELPER_BASENAME)
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
        candidates.append(bundle_root / _HELPER_BASENAME)
        candidates.append(bundle_root.parent / _HELPER_BASENAME)
    return candidates


def _command_supports_buckets(argv: tuple[str, ...]) -> bool:
    """Return whether a candidate CLI implements the modern Bucket commands."""
    try:
        result = subprocess.run(
            [*argv, "buckets", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0


def _resolve_transport_command() -> _TransportCommand:
    for candidate in _helper_candidates():
        if candidate.is_file():
            return _TransportCommand(
                (str(candidate),),
                "json-helper",
                f"packaged:{candidate}",
            )

    helper_on_path = (
        shutil.which(_HELPER_BASENAME)
        or shutil.which("edmg-hf-bucket-helper")
    )
    if helper_on_path:
        return _TransportCommand(
            (helper_on_path,),
            "json-helper",
            f"path:{helper_on_path}",
        )

    explicit_cli = os.getenv("EDMG_HF_CLI", "").strip()
    if explicit_cli:
        explicit_path = Path(explicit_cli).expanduser()
        if not explicit_path.is_file():
            raise HFBucketCapabilityError(
                f"EDMG_HF_CLI does not point to a file: {explicit_path}"
            )
        command = (str(explicit_path),)
        if not _command_supports_buckets(command):
            raise HFBucketCapabilityError(
                "EDMG_HF_CLI does not support Hugging Face Buckets: "
                f"{explicit_path}"
            )
        return _TransportCommand(
            command,
            "hf-cli",
            f"configured:{explicit_path}",
        )

    # Prefer the standalone CLI in an isolated uv tool environment. This keeps
    # Transformers 4.x and huggingface_hub 0.x inside the backend environment.
    uvx = shutil.which("uvx")
    if uvx:
        command = (uvx, "hf")
        if _command_supports_buckets(command):
            return _TransportCommand(
                command,
                "hf-cli",
                f"uvx:{uvx}",
            )

    # Use a regular hf executable only when it actually supports Buckets.
    hf_cli = shutil.which("hf")
    if hf_cli:
        command = (hf_cli,)
        if _command_supports_buckets(command):
            return _TransportCommand(
                command,
                "hf-cli",
                f"hf-cli:{hf_cli}",
            )

    raise HFBucketCapabilityError(
        "Hugging Face Bucket support is unavailable. The packaged "
        f"{_HELPER_BASENAME} is missing, `uvx hf` is unavailable, and no "
        "modern `hf` CLI with Bucket support was found on PATH."
    )


def _redact(text: str, token: str) -> str:
    message = str(text or "").strip()
    if token:
        message = message.replace(token, "[REDACTED]")
    return message[:4000]


def _json_payload(stdout: str) -> Any:
    text = str(stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise HFBucketOperationError("Hugging Face Bucket transport returned invalid JSON")


class _BucketTransport:
    """One-shot subprocess client for the isolated modern Hub runtime."""

    def __init__(
        self,
        *,
        token: str = "",
        command: _TransportCommand | None = None,
    ):
        self._token = str(token or "").strip()
        self._command = command

    def _resolved_command(self) -> _TransportCommand:
        if self._command is None:
            self._command = _resolve_transport_command()
        return self._command

    @property
    def source(self) -> str:
        return self._resolved_command().source

    def _environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._token:
            env["HF_TOKEN"] = self._token
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
        return env

    def _effective_token(self) -> str:
        return self._token or str(
            os.getenv("HF_TOKEN") or os.getenv("EDMG_HF_TOKEN") or ""
        ).strip()

    def _run_process(
        self,
        argv: list[str],
        *,
        stdin: str | None = None,
        expect_json: bool = False,
    ) -> Any:
        try:
            result = subprocess.run(
                argv,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._environment(),
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                ),
                check=False,
            )
        except OSError as exc:
            raise HFBucketCapabilityError(
                f"Could not start Hugging Face Bucket transport ({self.source}): {exc}"
            ) from exc
        payload = None
        if expect_json and result.stdout.strip():
            try:
                payload = _json_payload(result.stdout)
            except HFBucketOperationError:
                if result.returncode == 0:
                    raise
        if result.returncode != 0:
            message = ""
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
                elif error:
                    message = str(error)
            message = message or result.stderr or result.stdout
            raise HFBucketOperationError(
                _redact(message, self._effective_token())
                or f"Hugging Face Bucket transport exited with code {result.returncode}"
            )
        return payload if expect_json else result.stdout.strip()

    def _helper(self, operation: str, **payload: Any) -> dict[str, Any]:
        request = {
            "contract_version": _HELPER_CONTRACT_VERSION,
            "operation": operation,
            **payload,
        }
        response = self._run_process(
            list(self._resolved_command().argv),
            stdin=json.dumps(request, ensure_ascii=False),
            expect_json=True,
        )
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise HFBucketOperationError("Hugging Face Bucket helper returned an invalid response")
        if response.get("contract_version") != _HELPER_CONTRACT_VERSION:
            raise HFBucketCapabilityError(
                "Hugging Face Bucket helper protocol is incompatible with this Studio build"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise HFBucketOperationError("Hugging Face Bucket helper omitted its result")
        return result

    def _cli(self, args: list[str], *, expect_json: bool = False) -> Any:
        return self._run_process(
            [*self._resolved_command().argv, *args],
            expect_json=expect_json,
        )

    def capabilities(self) -> dict[str, Any]:
        if self._resolved_command().kind == "json-helper":
            return self._helper("capabilities")
        output = self._cli(["version"], expect_json=False)
        return {
            "contract_version": _HELPER_CONTRACT_VERSION,
            "helper_version": None,
            "huggingface_hub_version": None,
            "operations": ["bucket_info", "list", "download", "upload", "sync"],
            "cli": True,
            "output": output if isinstance(output, str) else None,
        }

    def bucket_info(self, bucket: str) -> dict[str, Any]:
        if self._resolved_command().kind == "json-helper":
            return self._helper("bucket_info", bucket=bucket).get("bucket") or {}
        result = self._cli(["buckets", "info", bucket], expect_json=True)
        return result if isinstance(result, dict) else {}

    def list_entries(
        self,
        bucket: str,
        *,
        prefix: str = "",
        recursive: bool = False,
    ) -> list[dict[str, Any]]:
        if self._resolved_command().kind == "json-helper":
            result = self._helper(
                "list",
                bucket=bucket,
                prefix=prefix,
                recursive=recursive,
            )
            entries = result.get("entries")
        else:
            target = self.bucket_uri(bucket, prefix)
            args = ["buckets", "list", target]
            if recursive:
                args.append("--recursive")
            args += ["--format", "json"]
            result = self._cli(args, expect_json=True)
            entries = result.get("items") if isinstance(result, dict) else result
        if not isinstance(entries, list):
            raise HFBucketOperationError("Hugging Face Bucket listing returned no entry list")
        return [entry for entry in entries if isinstance(entry, dict)]

    def file_exists(self, bucket: str, remote_path: str) -> bool:
        remote = _normalize_remote(remote_path)
        if self._resolved_command().kind == "json-helper":
            result = self._helper("paths_info", bucket=bucket, paths=[remote])
            entries = result.get("entries")
        else:
            entries = self.list_entries(bucket, prefix=remote, recursive=True)
        return any(_normalize_remote(str(entry.get("path") or "")) == remote for entry in entries or [])

    def download_file(self, bucket: str, remote_path: str, local_path: Path) -> None:
        remote = _normalize_remote(remote_path)
        if self._resolved_command().kind == "json-helper":
            self._helper(
                "download",
                bucket=bucket,
                remote_path=remote,
                local_path=str(local_path),
            )
            return
        self._cli(
            [
                "buckets",
                "cp",
                self.bucket_uri(bucket, remote),
                str(local_path),
            ]
        )

    def upload_file(self, bucket: str, local_path: Path, remote_path: str) -> None:
        remote = _normalize_remote(remote_path)
        if self._resolved_command().kind == "json-helper":
            self._helper(
                "upload",
                bucket=bucket,
                local_path=str(local_path),
                remote_path=remote,
            )
            return
        self._cli(
            [
                "buckets",
                "cp",
                str(local_path),
                self.bucket_uri(bucket, remote),
            ]
        )

    def sync(
        self,
        bucket: str,
        *,
        source: str,
        dest: str,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> None:
        included = [str(pattern) for pattern in (include or []) if str(pattern).strip()]
        excluded = [str(pattern) for pattern in (exclude or []) if str(pattern).strip()]
        if self._resolved_command().kind == "json-helper":
            self._helper(
                "sync",
                bucket=bucket,
                source=source,
                dest=dest,
                include=included,
                exclude=excluded,
            )
            return
        args = ["buckets", "sync", source, dest]
        for pattern in included:
            args += ["--include", pattern]
        for pattern in excluded:
            args += ["--exclude", pattern]
        self._cli(args)

    @staticmethod
    def bucket_uri(bucket: str, remote_path: str = "") -> str:
        base = f"hf://buckets/{parse_bucket_id(bucket)}"
        remote = _normalize_remote(remote_path)
        return f"{base}/{remote}" if remote else base


@dataclass(frozen=True)
class HFBucketCacheSettings:
    bucket: str  # bucket id: "namespace/name"
    models_dir: Path
    prefix: str = ""
    token: str = ""


def _hf_bucket_enabled() -> bool:
    return _truthy(os.getenv("EDMG_HF_BUCKET_MODEL_CACHE")) or _truthy(
        os.getenv("EDMG_HF_MODEL_CACHE")
    )


def _configured_bucket_id(*, bucket: str | None = None) -> str:
    resolved = (
        str(bucket or "").strip()
        or os.getenv("EDMG_HF_BUCKET_ID", "").strip()
        or os.getenv("EDMG_HF_MODEL_BUCKET", "").strip()
        or os.getenv("EDMG_HF_BUCKET", "").strip()
    )
    if "buckets/" in resolved:
        resolved = resolved.split("buckets/", 1)[1]
    return resolved.strip().strip("/")


def resolve_models_dir(*, models_dir: Path | None = None) -> Path:
    """Resolve the Studio models directory (mirrors ``Settings.models_dir`` fallback)."""
    if models_dir is not None:
        return Path(models_dir).expanduser().resolve()

    raw = (
        os.getenv("EDMG_STUDIO_MODELS_DIR", "").strip()
        or os.getenv("EDMG_HF_BUCKET_MODELS_DIR", "").strip()
    )
    if raw:
        return Path(raw).expanduser().resolve()

    data_dir = Path(os.getenv("EDMG_STUDIO_DATA_DIR", "./data")).expanduser().resolve()
    studio_home_raw = os.getenv("EDMG_STUDIO_HOME", "").strip()
    if studio_home_raw:
        studio_home = Path(studio_home_raw).expanduser().resolve()
    else:
        studio_home = data_dir.parent.resolve()
    return (studio_home / "models").resolve()


def resolve_hf_token(*, secrets_store: Any | None = None) -> tuple[str, str]:
    return _resolve_hf_auth_token(secrets_store=secrets_store)


def settings_from_env(
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    token: str | None = None,
    models_dir: Path | None = None,
) -> HFBucketCacheSettings:
    resolved_bucket = (
        str(bucket or "").strip()
        or os.getenv("EDMG_HF_BUCKET_ID", "").strip()
        or os.getenv("EDMG_HF_MODEL_BUCKET", "").strip()
        or os.getenv("EDMG_HF_BUCKET", "").strip()
    )
    if not resolved_bucket:
        raise RuntimeError(
            "Set EDMG_HF_BUCKET_ID to the Hugging Face bucket id (namespace/name) for the model cache."
        )
    # Tolerate a full hf:// URI being pasted in.
    if "buckets/" in resolved_bucket:
        resolved_bucket = resolved_bucket.split("buckets/", 1)[1]
    resolved_bucket = resolved_bucket.strip().strip("/")

    resolved_models_dir = resolve_models_dir(models_dir=models_dir)

    resolved_token = str(token or "").strip()
    if not resolved_token:
        resolved_token, _ = resolve_hf_token()

    return HFBucketCacheSettings(
        bucket=resolved_bucket,
        models_dir=resolved_models_dir,
        prefix=_normalize_remote(
            str(prefix or "").strip() or os.getenv("EDMG_HF_BUCKET_PREFIX", "").strip()
        ),
        token=resolved_token,
    )


class HFBucketModelCache:
    """Model cache backed by a Hugging Face bucket (Xet-backed storage)."""

    label = "Hugging Face bucket"

    def __init__(self, settings: HFBucketCacheSettings):
        self.settings = settings
        self._token = settings.token or None
        self._transport = _BucketTransport(token=settings.token)

    @classmethod
    def from_env(cls) -> HFBucketModelCache | None:
        return cls.from_runtime()

    @classmethod
    def from_runtime(
        cls,
        *,
        models_dir: Path | None = None,
        secrets_store: Any | None = None,
    ) -> HFBucketModelCache | None:
        if not _hf_bucket_enabled():
            return None
        token, _ = resolve_hf_token(secrets_store=secrets_store)
        return cls(
            settings_from_env(
                models_dir=models_dir,
                token=token or None,
            )
        )

    # ------------------------------------------------------------------
    # remote-path resolution (mirror of models_dir, with explicit overrides)
    # ------------------------------------------------------------------
    def _explicit_remote(self, entry: dict[str, Any]) -> str | None:
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        explicit = _first_string(
            entry.get("hf_bucket_path"),
            entry.get("hf_key"),
            entry.get("bucket_path"),
            entry.get("s3_key"),  # set by ModelManager from a recorded cloud object
            entry.get("key"),
            target.get("hf_bucket_path"),
            target.get("hf_key"),
            target.get("bucket_path"),
            target.get("s3_key"),
            target.get("key"),
        )
        return _normalize_remote(explicit) if explicit else None

    def _relative_to_models(self, path: Path) -> str | None:
        try:
            rel = Path(path).resolve().relative_to(self.settings.models_dir)
        except (ValueError, OSError):
            return None
        return rel.as_posix()

    def _fallback_remote(self, entry: dict[str, Any], path: Path) -> str:
        """Mirror path used when ``path`` is not under models_dir (e.g. a temp staging dir).

        Mirrors ``ModelManager._models_dest`` so uploads from cloud-only temp dirs
        still land at the canonical bucket location:
          - internal engine -> ``internal/<folder>/<id>`` (snapshot directory)
          - otherwise        -> ``<folder>/<filename>`` (single ComfyUI file)
        """
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        engine = str(target.get("engine") or entry.get("engine") or "comfyui").strip().lower()
        folder = _normalize_remote(str(target.get("folder") or "checkpoints")) or "checkpoints"
        if engine == "internal":
            model_id = _first_string(entry.get("id"), path.name) or "model"
            return _normalize_remote(f"internal/{folder}/{model_id}")
        filename = _first_string(entry.get("filename"), path.name) or "model.safetensors"
        return _normalize_remote(f"{folder}/{filename}")

    def _with_prefix(self, remote: str) -> str:
        remote = _normalize_remote(remote)
        if self.settings.prefix:
            return _normalize_remote(f"{self.settings.prefix}/{remote}")
        return remote

    def remote_path_for(self, entry: dict[str, Any], path: Path) -> str:
        explicit = self._explicit_remote(entry)
        if explicit:
            return explicit
        rel = self._relative_to_models(Path(path))
        if rel is None:
            rel = self._fallback_remote(entry, Path(path))
        return self._with_prefix(rel)

    # ------------------------------------------------------------------
    # single-file model operations
    # ------------------------------------------------------------------
    def _file_exists(self, remote: str) -> bool:
        return self._transport.file_exists(self.settings.bucket, _normalize_remote(remote))

    def model_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        remote = self.remote_path_for(entry, Path(path))
        return remote if self._file_exists(remote) else None

    def download_model(self, entry: dict[str, Any], dest: Path) -> bool:
        remote = self.remote_path_for(entry, Path(dest))
        if not self._file_exists(remote):
            return False
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".hf.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        self._transport.download_file(self.settings.bucket, remote, tmp)
        os.replace(tmp, dest)
        return True

    def upload_model(self, entry: dict[str, Any], path: Path) -> str:
        path = Path(path)
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Model cache upload source is not a file: {path}")
        remote = self.remote_path_for(entry, path)
        self._transport.upload_file(self.settings.bucket, path, remote)
        return remote

    # ------------------------------------------------------------------
    # directory (snapshot) operations
    # ------------------------------------------------------------------
    def _bucket_uri(self, remote_dir: str) -> str:
        return self._transport.bucket_uri(self.settings.bucket, remote_dir)

    def _iter_remote_file_entries(self, remote_dir: str) -> dict[str, dict[str, Any]]:
        remote_dir = _normalize_remote(remote_dir)
        out: dict[str, dict[str, Any]] = {}
        items = self._transport.list_entries(
            self.settings.bucket,
            prefix=remote_dir,
            recursive=True,
        )
        for item in items:
            if str(item.get("type") or "").lower() in {"directory", "folder"}:
                continue
            rel = _normalize_remote(str(item.get("path") or ""))
            if not rel:
                continue
            if remote_dir and not (rel == remote_dir or rel.startswith(remote_dir + "/")):
                continue
            relative = rel[len(remote_dir) :].lstrip("/") if remote_dir else rel
            relative = _snapshot_path(relative)
            if not relative:
                continue
            size_value = item.get("size")
            size = (
                int(size_value)
                if isinstance(size_value, int)
                and not isinstance(size_value, bool)
                and size_value >= 0
                else None
            )
            out[relative] = {"path": rel, "size": size}
        return out

    def _iter_remote_files(self, remote_dir: str) -> list[str]:
        return [
            str(entry["path"])
            for entry in self._iter_remote_file_entries(remote_dir).values()
        ]

    def _download_remote_json(
        self,
        remote_dir: str,
        relative_path: str,
        entries: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        entry = entries.get(relative_path)
        if not entry:
            raise HFBucketOperationError(
                f"Bucket model directory is missing required metadata: {relative_path}"
            )
        listed_size = entry.get("size")
        if isinstance(listed_size, int) and listed_size > 2 * 1024 * 1024:
            raise HFBucketOperationError(
                f"Bucket model metadata is unexpectedly large: {relative_path}"
            )
        remote_path = _normalize_remote(f"{remote_dir}/{relative_path}")
        with tempfile.TemporaryDirectory(prefix="edmg-hf-bucket-metadata-") as temp_dir:
            local_path = Path(temp_dir) / Path(relative_path).name
            self._transport.download_file(self.settings.bucket, remote_path, local_path)
            try:
                if local_path.stat().st_size > 2 * 1024 * 1024:
                    raise HFBucketOperationError(
                        f"Bucket model metadata is unexpectedly large: {relative_path}"
                    )
                payload = json.loads(local_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HFBucketOperationError(
                    f"Bucket model metadata is not valid JSON: {relative_path}"
                ) from exc
        if not isinstance(payload, dict):
            raise HFBucketOperationError(
                f"Bucket model metadata must contain a JSON object: {relative_path}"
            )
        return payload

    def _remote_snapshot_plan(
        self,
        remote_dir: str,
        entries: dict[str, dict[str, Any]],
        *,
        model_entry: dict[str, Any] | None,
        require_manifest: bool = False,
    ) -> _SnapshotPlan:
        paths = set(entries)
        model_index = (
            self._download_remote_json(remote_dir, "model_index.json", entries)
            if "model_index.json" in paths
            else None
        )
        plan = _select_snapshot_plan(
            paths,
            model_index=model_index,
            model_entry=model_entry,
        )
        if _SNAPSHOT_MANIFEST_NAME in paths:
            manifest = self._download_remote_json(
                remote_dir,
                _SNAPSHOT_MANIFEST_NAME,
                entries,
            )
            remote_sizes = {
                path: entry.get("size")
                for path, entry in entries.items()
            }
            if not _validate_snapshot_manifest(manifest, plan, remote_sizes):
                raise HFBucketOperationError(
                    "Hugging Face bucket model-cache manifest is invalid or does not "
                    "match the complete remote inference snapshot"
                )
        elif require_manifest:
            raise HFBucketOperationError(
                "Hugging Face bucket model directory has no EDMG model-cache manifest"
            )
        return plan

    @staticmethod
    def _local_snapshot_plan(
        path: Path,
        *,
        model_entry: dict[str, Any] | None,
    ) -> tuple[_SnapshotPlan, dict[str, int]]:
        paths: set[str] = set()
        sizes: dict[str, int] = {}
        for candidate in path.rglob("*"):
            if not candidate.is_file():
                continue
            relative = _snapshot_path(candidate.relative_to(path).as_posix())
            if not relative or _is_partial_or_cache_path(relative):
                continue
            paths.add(relative)
            try:
                sizes[relative] = candidate.stat().st_size
            except OSError as exc:
                raise HFBucketOperationError(
                    f"Could not inspect model-cache upload file: {candidate}"
                ) from exc
        model_index: dict[str, Any] | None = None
        if "model_index.json" in paths:
            try:
                payload = json.loads((path / "model_index.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HFBucketOperationError(
                    "Local Diffusers snapshot has an invalid model_index.json"
                ) from exc
            if not isinstance(payload, dict):
                raise HFBucketOperationError(
                    "Local Diffusers model_index.json must contain a JSON object"
                )
            model_index = payload
        plan = _select_snapshot_plan(
            paths,
            model_index=model_index,
            model_entry=model_entry,
        )
        for selected in plan.files:
            if sizes.get(selected, 0) <= 0:
                raise HFBucketOperationError(
                    f"Local inference snapshot contains a missing or empty file: {selected}"
                )
        return plan, sizes

    def model_directory_complete(
        self,
        remote_prefix: str,
        model_entry: dict[str, Any] | None = None,
    ) -> bool:
        """Return whether a remote model directory is a bounded runnable snapshot.

        A valid EDMG manifest is enforced when present. Older bucket directories
        without a manifest are accepted only when their listed files form a
        complete default-weight inference snapshot. Cache entries, partial files,
        config-only directories, and alternate-format dumps never count.
        """

        remote_dir = _normalize_remote(remote_prefix)
        entries = self._iter_remote_file_entries(remote_dir)
        if not entries:
            return False
        try:
            self._remote_snapshot_plan(
                remote_dir,
                entries,
                model_entry=model_entry,
            )
            return True
        except HFBucketOperationError as exc:
            logger.warning("Ignoring incomplete Hugging Face bucket model %s: %s", remote_dir, exc)
            return False

    def model_directory_exists(self, entry: dict[str, Any], path: Path) -> str | None:
        remote_dir = self.remote_path_for(entry, Path(path))
        return (
            remote_dir
            if self.model_directory_complete(remote_dir, model_entry=entry)
            else None
        )

    def download_model_directory(self, entry: dict[str, Any], dest: Path) -> bool:
        remote_dir = self.remote_path_for(entry, Path(dest))
        entries = self._iter_remote_file_entries(remote_dir)
        if not entries:
            return False
        plan = self._remote_snapshot_plan(
            remote_dir,
            entries,
            model_entry=entry,
        )
        included = list(plan.files)
        if _SNAPSHOT_MANIFEST_NAME in entries:
            included.append(_SNAPSHOT_MANIFEST_NAME)
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        self._transport.sync(
            self.settings.bucket,
            source=self._bucket_uri(remote_dir),
            dest=str(dest),
            include=included,
            exclude=_BUCKET_SYNC_EXCLUDES,
        )
        local_plan, _ = self._local_snapshot_plan(dest, model_entry=entry)
        return local_plan == plan

    def upload_model_directory(self, entry: dict[str, Any], path: Path) -> str:
        path = Path(path)
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"Model cache upload source is not a directory: {path}")
        plan, sizes = self._local_snapshot_plan(path, model_entry=entry)
        remote_dir = self.remote_path_for(entry, path)
        self._transport.sync(
            self.settings.bucket,
            source=str(path),
            dest=self._bucket_uri(remote_dir),
            include=list(plan.files),
            exclude=_BUCKET_SYNC_EXCLUDES,
        )
        manifest = _build_snapshot_manifest(plan, sizes, model_entry=entry)
        with tempfile.TemporaryDirectory(prefix="edmg-hf-bucket-manifest-") as temp_dir:
            manifest_path = Path(temp_dir) / _SNAPSHOT_MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._transport.upload_file(
                self.settings.bucket,
                manifest_path,
                _normalize_remote(f"{remote_dir}/{_SNAPSHOT_MANIFEST_NAME}"),
            )
        return remote_dir


def download_bucket_snapshot(
    *,
    bucket: str,
    dest: Path,
    remote_path: str = "",
    token: str | None = None,
) -> bool:
    """Sync a Hugging Face bucket directory into ``dest``.

    Used to install a model whose weights live directly in a bucket
    (``hf://buckets/<namespace>/<name>``) rather than the shared model-cache
    mirror. ``remote_path`` selects a sub-directory of the bucket; an empty
    value mirrors the bucket root. Returns ``True`` when at least one file was
    written to ``dest``.
    """
    bucket_id = parse_bucket_id(bucket)
    if not bucket_id:
        raise RuntimeError("Missing Hugging Face bucket id (namespace/name).")
    remote = _normalize_remote(remote_path)
    base = f"hf://buckets/{bucket_id}"
    source = f"{base}/{remote}" if remote else base
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _BucketTransport(token=token or "").sync(
        bucket_id,
        source=source,
        dest=str(dest),
        exclude=_BUCKET_SYNC_EXCLUDES,
    )
    return any(dest.rglob("*"))


def download_bucket_file(
    *,
    bucket: str,
    remote_path: str,
    dest: Path,
    token: str | None = None,
) -> bool:
    """Download a single file from a Hugging Face bucket into ``dest``."""
    bucket_id = parse_bucket_id(bucket)
    if not bucket_id:
        raise RuntimeError("Missing Hugging Face bucket id (namespace/name).")
    remote = _normalize_remote(remote_path)
    if not remote:
        raise RuntimeError("Missing Hugging Face bucket file path.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".hf.tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    _BucketTransport(token=token or "").download_file(bucket_id, remote, tmp)
    os.replace(tmp, dest)
    return dest.exists()


def describe_status(
    *, models_dir: Path | None = None, secrets_store: Any | None = None
) -> dict[str, Any]:
    bucket = _configured_bucket_id()
    prefix = _normalize_remote(os.getenv("EDMG_HF_BUCKET_PREFIX", "").strip())
    token, token_source = resolve_hf_token(secrets_store=secrets_store)

    resolved_models_dir = resolve_models_dir(models_dir=models_dir)

    active = False
    active_error: str | None = None
    transport_source: str | None = None
    if _hf_bucket_enabled():
        try:
            cache = HFBucketModelCache.from_runtime(
                models_dir=resolved_models_dir,
                secrets_store=secrets_store,
            )
            active = cache is not None
            if cache is not None:
                transport_source = cache._transport.source
        except Exception:
            logger.exception("Hugging Face bucket status check failed")
            active_error = "Hugging Face bucket status check failed"

    return {
        "ok": True,
        "provider": "huggingface_bucket",
        "enabled": _hf_bucket_enabled(),
        "active": active,
        "active_error": active_error,
        "transport": transport_source,
        "bucket": bucket or None,
        "prefix": prefix or None,
        "models_dir": str(resolved_models_dir),
        "has_token": bool(token),
        "token_source": token_source or None,
        "token_note": (
            "Runtime model cache uses HF_TOKEN/EDMG_HF_TOKEN env vars, then `hf auth login` "
            "or the Hugging Face Hub token cache, then Settings → Tokens."
        ),
    }


def test_credentials(
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    models_dir: Path | None = None,
    secrets_store: Any | None = None,
) -> dict[str, Any]:
    token, token_source = resolve_hf_token(secrets_store=secrets_store)

    settings = settings_from_env(
        bucket=bucket,
        prefix=prefix,
        token=token,
        models_dir=models_dir,
    )
    cache = HFBucketModelCache(settings)
    capabilities = cache._transport.capabilities()
    cache._transport.bucket_info(settings.bucket)
    prefix_filter = settings.prefix or None
    items = cache._transport.list_entries(
        settings.bucket,
        prefix=prefix_filter or "",
        recursive=False,
    )
    sample_paths: list[str] = []
    for item in items:
        rel = _normalize_remote(str(item.get("path") or ""))
        if rel:
            sample_paths.append(rel)
        if len(sample_paths) >= 5:
            break

    return {
        "ok": True,
        "provider": "huggingface_bucket",
        "bucket": settings.bucket,
        "prefix": settings.prefix or None,
        "models_dir": str(settings.models_dir),
        "token_source": token_source or None,
        "authentication": token_source or "anonymous",
        "sample_paths": sample_paths,
        "bucket_uri": cache._bucket_uri(""),
        "transport": cache._transport.source,
        "capabilities": capabilities,
    }
