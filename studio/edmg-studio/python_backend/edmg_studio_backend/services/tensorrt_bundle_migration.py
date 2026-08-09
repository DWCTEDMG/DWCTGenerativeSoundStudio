from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..errors import UserFacingError

MODEL_ID = "local_sd15_tensorrt_bundle"
CANONICAL_BUNDLE_DIRNAME = MODEL_ID
MANIFEST_FILENAME = "edmg-tensorrt-bundle.json"
MANIFEST_SCHEMA_VERSION = 1

EXTERNAL_BUNDLE_ENV_VARS = (
    "EDMG_TENSORRT_SD15_BUNDLE",
    "EDMG_TENSORRT_MODEL_DIR",
)

_ENGINE_NAMES: dict[str, tuple[str, ...]] = {
    "text_encoder": ("text_encoder.engine",),
    "unet": (
        "unet_b1_workspace4096.engine",
        "unet.engine",
        "unet.plan",
    ),
    "vae_decoder": ("vae_decoder.engine",),
    "vae_encoder": ("vae_encoder.engine",),
}
REQUIRED_ONNX_FILES: dict[str, str] = {
    "model_index": "onnx/model_index.json",
    "feature_extractor_config": "onnx/feature_extractor/preprocessor_config.json",
    "scheduler_config": "onnx/scheduler/scheduler_config.json",
    "text_encoder_config": "onnx/text_encoder/config.json",
    "text_encoder_model": "onnx/text_encoder/model.onnx",
    "tokenizer_merges": "onnx/tokenizer/merges.txt",
    "tokenizer_special_tokens": "onnx/tokenizer/special_tokens_map.json",
    "tokenizer_config": "onnx/tokenizer/tokenizer_config.json",
    "tokenizer_vocab": "onnx/tokenizer/vocab.json",
    "unet_config": "onnx/unet/config.json",
    "unet_model": "onnx/unet/model.onnx",
    "vae_decoder_config": "onnx/vae_decoder/config.json",
    "vae_decoder_model": "onnx/vae_decoder/model.onnx",
    "vae_encoder_config": "onnx/vae_encoder/config.json",
    "vae_encoder_model": "onnx/vae_encoder/model.onnx",
}
_STAGING_PREFIX = f".{CANONICAL_BUNDLE_DIRNAME}.import-"
_HASH_CHUNK_BYTES = 8 * 1024 * 1024
_DISK_SAFETY_BYTES = 64 * 1024 * 1024
_PINNED_REVISION = re.compile(r"^[0-9a-fA-F]{40,64}$")

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[int, int, int, int, str], None]


class TensorRTMigrationCancelled(Exception):
    """Raised when a cooperative legacy-engine import is cancelled."""


@dataclass(frozen=True)
class TensorRTBundleContract:
    """Validated, execution-ready SD 1.5 TensorRT bundle contract.

    Instances are created only by the fail-closed validator below.  Runtime
    callers consume these exact paths and pinned model coordinates instead of
    rediscovering files or accepting request/environment overrides directly.
    """

    root: Path
    manifest_path: Path
    engine_paths: dict[str, Path]
    onnx_paths: dict[str, Path]
    profile_width: int
    profile_height: int
    batch_size: int
    sample_size: int
    base_model_id: str
    base_model_revision: str


def _sha256_shape(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return len(raw) == 64 and all(character in "0123456789abcdef" for character in raw)


def _json_dict(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    except OSError:
        return False


def _strict_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _safe_manifest_path(value: Any, *, prefix: str) -> PurePosixPath | None:
    raw = str(value or "").replace("\\", "/").strip()
    candidate = PurePosixPath(raw)
    if (
        not raw
        or candidate.is_absolute()
        or not candidate.parts
        or candidate.parts[0] != prefix
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or ":" in raw
    ):
        return None
    return candidate


def _valid_hf_model_id(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw or "\\" in raw or ":" in raw or raw.startswith("/") or raw.endswith("/"):
        return False
    parts = raw.split("/")
    return bool(
        len(parts) == 2
        and all(part not in {"", ".", ".."} for part in parts)
        and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) for part in parts)
    )


def _hf_identity_from_reference(value: Any) -> tuple[str | None, str | None]:
    """Extract only an unambiguous Hub identity; never trust arbitrary paths."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None, None
    parts = [part for part in raw.split("/") if part]
    for index, part in enumerate(parts):
        if not part.startswith("models--"):
            continue
        encoded = part[len("models--") :]
        model_parts = encoded.split("--", 1)
        if len(model_parts) != 2 or not all(model_parts):
            return None, None
        model_id = "/".join(model_parts)
        revision = None
        if index + 2 < len(parts) and parts[index + 1] == "snapshots":
            revision = parts[index + 2]
        return model_id, revision

    trimmed = raw.removesuffix("/unet")
    if _valid_hf_model_id(trimmed):
        return trimmed, None
    return None, None


class TensorRTBundleMigration:
    """Detect and explicitly copy the pre-1.2 TensorRT engine layout.

    The legacy source is the direct contents of
    ``<models>/internal/tensorrt``.  The canonical bundle is a child named
    ``local_sd15_tensorrt_bundle``.  Detection is read-only.  Migration is an
    explicit, source-preserving operation that publishes a fully verified
    staging directory in one same-volume rename.
    """

    def __init__(self, models_dir: Path, *, copy_chunk_bytes: int = _HASH_CHUNK_BYTES):
        self.models_dir = Path(models_dir).expanduser().resolve()
        self.legacy_root = self.models_dir / "internal" / "tensorrt"
        self.canonical_root = self.legacy_root / CANONICAL_BUNDLE_DIRNAME
        self.copy_chunk_bytes = max(64 * 1024, int(copy_chunk_bytes))
        self._operation_lock = threading.Lock()
        self._hash_lock = threading.Lock()
        self._hash_cache: dict[tuple[str, int, int], str] = {}

    @staticmethod
    def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
        if cancel_check is not None and cancel_check():
            raise TensorRTMigrationCancelled("TensorRT engine copy cancelled")

    def _assert_managed_child(self, path: Path, *, staging: bool = False) -> None:
        root = self.legacy_root.resolve(strict=False)
        candidate = path.resolve(strict=False)
        if candidate.parent != root:
            raise RuntimeError("Refusing a TensorRT operation outside the managed runtime-bundle folder")
        if staging and not candidate.name.startswith(_STAGING_PREFIX):
            raise RuntimeError("Refusing to operate on an unrecognized TensorRT staging folder")

    def _discover_sources(self) -> tuple[dict[str, Path | None], list[str]]:
        selected: dict[str, Path | None] = {role: None for role in _ENGINE_NAMES}
        try:
            if not self.legacy_root.is_dir():
                return selected, []
            direct_files = [path for path in self.legacy_root.iterdir() if path.is_file() or path.is_symlink()]
        except OSError:
            return selected, []

        by_name = {path.name.lower(): path for path in direct_files}
        for role, preferred_names in _ENGINE_NAMES.items():
            candidates = [by_name[name.lower()] for name in preferred_names if name.lower() in by_name]
            if role == "unet":
                candidates.extend(
                    path
                    for path in sorted(direct_files, key=lambda item: item.name.lower())
                    if path.suffix.lower() in {".engine", ".plan"}
                    and "unet" in path.stem.lower()
                    and path not in candidates
                )
            selected[role] = next((path for path in candidates if _nonempty_file(path)), None)
            if selected[role] is None and candidates:
                selected[role] = candidates[0]

        selected_paths = {path for path in selected.values() if path is not None}
        extras = sorted(
            path.name
            for path in direct_files
            if path not in selected_paths and path.suffix.lower() in {".engine", ".plan"}
        )
        return selected, extras

    @staticmethod
    def _signature(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return int(stat.st_size), int(stat.st_mtime_ns)

    def _cached_sha256(
        self,
        path: Path,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> str:
        size, mtime_ns = self._signature(path)
        key = (os.path.normcase(str(path.resolve())), size, mtime_ns)
        with self._hash_lock:
            cached = self._hash_cache.get(key)
        if cached:
            return cached

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                self._raise_if_cancelled(cancel_check)
                chunk = handle.read(self.copy_chunk_bytes)
                if not chunk:
                    break
                digest.update(chunk)
        if self._signature(path) != (size, mtime_ns):
            raise UserFacingError(
                "A legacy TensorRT engine changed while Studio was verifying it",
                hint="Wait for any engine-building process to finish, then retry the import.",
                code="TRT_LEGACY_SOURCE_CHANGED",
                status_code=409,
            )
        value = digest.hexdigest()
        with self._hash_lock:
            self._hash_cache[key] = value
        return value

    def _manifest_source_hashes(self, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        rows = source.get("files") if isinstance(source, dict) else []
        if not isinstance(rows, list):
            return {}
        return {
            str(row.get("source_name") or "").lower(): row
            for row in rows
            if isinstance(row, dict) and row.get("source_name")
        }

    def _legacy_status(
        self,
        *,
        include_hashes: bool,
        known_hashes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        sources, extras = self._discover_sources()
        rows: list[dict[str, Any]] = []
        total_bytes = 0
        missing_roles: list[str] = []
        unusable_roles: list[str] = []

        for role, expected_names in _ENGINE_NAMES.items():
            path = sources.get(role)
            row: dict[str, Any] = {
                "role": role,
                "expected_names": list(expected_names),
                "name": path.name if path is not None else None,
                "present": path is not None,
                "non_empty": False,
                "safe_regular_file": False,
                "size_bytes": 0,
                "sha256": None,
                "hash_state": "not_available",
            }
            if path is None:
                missing_roles.append(role)
                rows.append(row)
                continue

            try:
                size, mtime_ns = self._signature(path)
                safe_regular = path.is_file() and not path.is_symlink()
            except OSError:
                unusable_roles.append(role)
                row["hash_state"] = "unreadable"
                rows.append(row)
                continue

            row["size_bytes"] = size
            row["non_empty"] = size > 0
            row["safe_regular_file"] = safe_regular
            if not safe_regular or size <= 0:
                unusable_roles.append(role)
                row["hash_state"] = "unsafe" if not safe_regular else "empty"
                rows.append(row)
                continue

            total_bytes += size
            known = known_hashes.get(path.name.lower())
            if (
                isinstance(known, dict)
                and int(known.get("size_bytes") or -1) == size
                and int(known.get("source_mtime_ns") or -1) == mtime_ns
                and _sha256_shape(known.get("sha256"))
            ):
                row["sha256"] = str(known["sha256"]).lower()
                row["hash_state"] = "verified_at_import"
            elif include_hashes:
                try:
                    row["sha256"] = self._cached_sha256(path)
                    row["hash_state"] = "verified_now"
                except (OSError, UserFacingError):
                    row["hash_state"] = "unreadable"
                    unusable_roles.append(role)
            else:
                row["hash_state"] = "pending_import_verification"
            rows.append(row)

        complete = not missing_roles and not unusable_roles and len(rows) == len(_ENGINE_NAMES)
        detected = any(bool(row["present"]) for row in rows)
        return {
            "detected": detected,
            "layout": "models/internal/tensorrt",
            "status": "ready_to_import" if complete else ("partial" if detected else "absent"),
            "expected_file_count": len(_ENGINE_NAMES),
            "usable_file_count": sum(
                1 for row in rows if row["present"] and row["non_empty"] and row["safe_regular_file"]
            ),
            "total_bytes": total_bytes,
            "files": rows,
            "missing_roles": sorted(set(missing_roles)),
            "unusable_roles": sorted(set(unusable_roles)),
            "extra_engine_files": extras,
            "source_preserved": True,
        }

    def _bundle_status(self, root: Path, *, include_hashes: bool) -> dict[str, Any]:
        """Validate one bundle root without inferring readiness from its contents."""

        root = Path(root).expanduser()
        try:
            exists = root.is_dir()
            safe_root = exists and not root.is_symlink()
        except OSError:
            exists = False
            safe_root = False

        manifest_path = root / MANIFEST_FILENAME
        manifest = _json_dict(manifest_path) if _nonempty_file(manifest_path) else {}
        source_section = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        raw_source_rows = source_section.get("files") if isinstance(source_section, dict) else []
        source_rows = (
            [row for row in raw_source_rows if isinstance(row, dict)]
            if isinstance(raw_source_rows, list)
            else []
        )
        roles = [str(row.get("role") or "").strip() for row in source_rows]
        source_names = [str(row.get("source_name") or "").strip() for row in source_rows]
        destinations = [
            str(row.get("destination") or "").replace("\\", "/").strip()
            for row in source_rows
        ]

        def safe_destination(row: dict[str, Any]) -> bool:
            source_name = str(row.get("source_name") or "").strip()
            candidate = _safe_manifest_path(row.get("destination"), prefix="engine")
            return bool(
                source_name
                and source_name not in {".", ".."}
                and "/" not in source_name
                and "\\" not in source_name
                and ":" not in source_name
                and candidate is not None
                and candidate.parts == ("engine", source_name)
            )

        def source_name_matches_role(row: dict[str, Any]) -> bool:
            role = str(row.get("role") or "").strip()
            source_name = str(row.get("source_name") or "").strip().lower()
            if role not in _ENGINE_NAMES:
                return False
            if source_name in {name.lower() for name in _ENGINE_NAMES[role]}:
                return True
            candidate = PurePosixPath(source_name)
            return bool(
                role == "unet"
                and "unet" in candidate.stem
                and candidate.suffix in {".engine", ".plan"}
            )

        manifest_valid = bool(
            manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION
            and manifest.get("manifest_kind") == "edmg.tensorrt.runtime_bundle"
            and manifest.get("model_id") == MODEL_ID
            and manifest.get("source_preserved") is True
            and len(source_rows) == len(_ENGINE_NAMES)
            and set(roles) == set(_ENGINE_NAMES)
            and len(set(roles)) == len(roles)
            and len(set(name.lower() for name in source_names)) == len(source_names)
            and len(set(destination.lower() for destination in destinations)) == len(destinations)
            and all(
                _sha256_shape(row.get("sha256"))
                and str(row.get("destination_sha256") or "").lower()
                == str(row.get("sha256") or "").lower()
                and _strict_positive_int(row.get("size_bytes"))
                and _strict_positive_int(row.get("destination_mtime_ns"))
                and safe_destination(row)
                and source_name_matches_role(row)
                for row in source_rows
            )
        )

        engine_dir = root / "engine"
        try:
            actual_engine_entries = sorted(
                (
                    path
                    for path in engine_dir.iterdir()
                    if path.suffix.lower() in {".engine", ".plan"}
                ),
                key=lambda path: path.name.lower(),
            ) if engine_dir.is_dir() and not engine_dir.is_symlink() else []
        except OSError:
            actual_engine_entries = []

        engine_rows: list[dict[str, Any]] = []
        engine_paths: dict[str, Path] = {}
        verified_copy = bool(manifest_valid and safe_root)
        for record in source_rows:
            role = str(record.get("role") or "").strip()
            destination = _safe_manifest_path(record.get("destination"), prefix="engine")
            path = root.joinpath(*destination.parts) if destination is not None else None
            try:
                safe_regular = bool(path and path.is_file() and not path.is_symlink())
                stat = path.stat() if safe_regular and path is not None else None
                size = int(stat.st_size) if stat is not None else 0
                mtime_ns = int(stat.st_mtime_ns) if stat is not None else 0
            except OSError:
                safe_regular = False
                size = 0
                mtime_ns = 0
            expected_size = record.get("size_bytes")
            size_matches = bool(_strict_positive_int(expected_size) and expected_size == size)
            expected_mtime_ns = record.get("destination_mtime_ns")
            mtime_matches = bool(
                _strict_positive_int(expected_mtime_ns) and expected_mtime_ns == mtime_ns
            )
            expected_hash = str(record.get("sha256") or "").lower()
            hash_matches: bool | None = None
            if include_hashes and safe_regular and size_matches and _sha256_shape(expected_hash):
                try:
                    assert path is not None
                    hash_matches = self._cached_sha256(path) == expected_hash
                except (OSError, UserFacingError):
                    hash_matches = False
            if not safe_regular or not size_matches or not mtime_matches or hash_matches is False:
                verified_copy = False
            if path is not None and safe_regular and role in _ENGINE_NAMES:
                engine_paths[role] = path
            engine_rows.append(
                {
                    "role": role,
                    "name": path.name if path is not None else str(record.get("source_name") or ""),
                    "size_bytes": size,
                    "non_empty": size > 0,
                    "safe_regular_file": safe_regular,
                    "manifest_size_matches": size_matches,
                    "manifest_mtime_matches": mtime_matches,
                    "hash_matches": hash_matches,
                }
            )

        declared_engine_paths = {destination.lower() for destination in destinations if destination}
        actual_engine_paths = {f"engine/{path.name}".lower() for path in actual_engine_entries}
        extra_engine_files = sorted(actual_engine_paths - declared_engine_paths)
        missing_engine_files = sorted(declared_engine_paths - actual_engine_paths)
        if manifest_valid and declared_engine_paths != actual_engine_paths:
            verified_copy = False
        engine_hashes_verified_now = bool(
            include_hashes
            and verified_copy
            and len(engine_rows) == len(_ENGINE_NAMES)
            and all(row["hash_matches"] is True for row in engine_rows)
        )
        unet_ready = bool(
            "unet" in engine_paths
            and verified_copy
        )

        onnx_section = manifest.get("onnx") if isinstance(manifest.get("onnx"), dict) else {}
        raw_onnx_rows = onnx_section.get("files") if isinstance(onnx_section, dict) else []
        onnx_rows = (
            [row for row in raw_onnx_rows if isinstance(row, dict)]
            if isinstance(raw_onnx_rows, list)
            else []
        )
        onnx_roles = [str(row.get("role") or "").strip() for row in onnx_rows]
        onnx_declared_paths = [
            str(row.get("path") or "").replace("\\", "/").strip()
            for row in onnx_rows
        ]

        def valid_onnx_record(row: dict[str, Any]) -> bool:
            role = str(row.get("role") or "").strip()
            candidate = _safe_manifest_path(row.get("path"), prefix="onnx")
            if not role or candidate is None:
                return False
            required_path = REQUIRED_ONNX_FILES.get(role)
            return bool(
                (required_path is None or candidate.as_posix() == required_path)
                and _strict_positive_int(row.get("size_bytes"))
                and _strict_positive_int(row.get("mtime_ns"))
                and _sha256_shape(row.get("sha256"))
            )

        onnx_manifest_valid = bool(
            onnx_section.get("verified") is True
            and len(onnx_rows) >= len(REQUIRED_ONNX_FILES)
            and set(REQUIRED_ONNX_FILES).issubset(onnx_roles)
            and len(set(onnx_roles)) == len(onnx_roles)
            and len(set(path.lower() for path in onnx_declared_paths)) == len(onnx_declared_paths)
            and all(valid_onnx_record(row) for row in onnx_rows)
        )

        onnx_root = root / "onnx"
        try:
            onnx_entries = list(onnx_root.rglob("*")) if onnx_root.is_dir() and not onnx_root.is_symlink() else []
        except OSError:
            onnx_entries = []
        unsafe_onnx_entry = False
        actual_onnx_paths: set[str] = set()
        for path in onnx_entries:
            try:
                if path.is_symlink():
                    unsafe_onnx_entry = True
                    continue
                if path.is_file():
                    if path.stat().st_size <= 0:
                        unsafe_onnx_entry = True
                    actual_onnx_paths.add(path.relative_to(root).as_posix().lower())
            except (OSError, ValueError):
                unsafe_onnx_entry = True

        onnx_file_rows: list[dict[str, Any]] = []
        onnx_paths: dict[str, Path] = {}
        onnx_files_valid = onnx_manifest_valid and not unsafe_onnx_entry
        for record in onnx_rows:
            role = str(record.get("role") or "").strip()
            relative = _safe_manifest_path(record.get("path"), prefix="onnx")
            path = root.joinpath(*relative.parts) if relative is not None else None
            try:
                safe_regular = bool(path and path.is_file() and not path.is_symlink())
                stat = path.stat() if safe_regular and path is not None else None
                size = int(stat.st_size) if stat is not None else 0
                mtime_ns = int(stat.st_mtime_ns) if stat is not None else 0
            except OSError:
                safe_regular = False
                size = 0
                mtime_ns = 0
            expected_size = record.get("size_bytes")
            size_matches = bool(_strict_positive_int(expected_size) and expected_size == size)
            expected_mtime_ns = record.get("mtime_ns")
            mtime_matches = bool(
                _strict_positive_int(expected_mtime_ns) and expected_mtime_ns == mtime_ns
            )
            if not safe_regular or not size_matches or not mtime_matches:
                onnx_files_valid = False
            if path is not None and safe_regular and role:
                onnx_paths[role] = path
            onnx_file_rows.append(
                {
                    "role": role,
                    "path": relative.as_posix() if relative is not None else None,
                    "size_bytes": size,
                    "safe_regular_file": safe_regular,
                    "manifest_size_matches": size_matches,
                    "manifest_mtime_matches": mtime_matches,
                }
            )
        declared_onnx_paths = {path.lower() for path in onnx_declared_paths if path}
        if declared_onnx_paths != actual_onnx_paths:
            onnx_files_valid = False
        onnx_ready = bool(onnx_manifest_valid and onnx_files_valid)

        manifest_profile = manifest.get("profile") if isinstance(manifest.get("profile"), dict) else {}
        profile_width = manifest_profile.get("width")
        profile_height = manifest_profile.get("height")
        profile_batch = manifest_profile.get("batch_size")
        profile_sample_size = manifest_profile.get("sample_size")
        unet_config_path = root / REQUIRED_ONNX_FILES["unet_config"]
        unet_config = _json_dict(unet_config_path) if _nonempty_file(unet_config_path) else {}
        config_sample_size = unet_config.get("sample_size")
        profile_metadata_ready = bool(
            manifest_profile.get("verified") is True
            and _strict_positive_int(profile_width)
            and _strict_positive_int(profile_height)
            and type(profile_batch) is int
            and profile_batch == 1
            and _strict_positive_int(profile_sample_size)
            and type(config_sample_size) is int
            and config_sample_size == profile_sample_size
            and profile_width == profile_sample_size * 8
            and profile_height == profile_sample_size * 8
        )

        manifest_base = manifest.get("base_model") if isinstance(manifest.get("base_model"), dict) else {}
        base_model_id = str(manifest_base.get("id") or "").strip()
        base_model_revision = str(manifest_base.get("revision") or "").strip().lower()
        model_index_path = root / REQUIRED_ONNX_FILES["model_index"]
        model_index = _json_dict(model_index_path) if _nonempty_file(model_index_path) else {}
        index_identity = _hf_identity_from_reference(model_index.get("_name_or_path"))
        unet_reference = str(unet_config.get("_name_or_path") or "").strip()
        unet_identity = _hf_identity_from_reference(unet_reference) if unet_reference else (None, None)
        identity_matches = bool(
            index_identity[0] == base_model_id
            and (index_identity[1] is None or index_identity[1].lower() == base_model_revision)
            and (
                not unet_reference
                or (
                    unet_identity[0] == base_model_id
                    and (unet_identity[1] is None or unet_identity[1].lower() == base_model_revision)
                )
            )
        )
        base_model_metadata_ready = bool(
            manifest_base.get("verified") is True
            and _valid_hf_model_id(base_model_id)
            and _PINNED_REVISION.fullmatch(base_model_revision)
            and identity_matches
        )

        gaps: list[str] = []
        if not safe_root:
            gaps.append("The bundle root must be a safe, non-symlink directory.")
        if not manifest_valid:
            gaps.append("A valid EDMG TensorRT bundle manifest with four exact engine records is required.")
        if not unet_ready:
            gaps.append("The manifest-selected UNet TensorRT engine is missing or unverified.")
        if not verified_copy:
            gaps.append("Every manifest engine must match its exact safe path, size, and verification record.")
        if not onnx_ready:
            gaps.append("The explicit verified ONNX component inventory is incomplete or no longer matches disk.")
        if not profile_metadata_ready:
            gaps.append("The explicit compiled width, height, batch, and integer sample-size profile is not verified.")
        if not base_model_metadata_ready:
            gaps.append("The matching SD 1.5 base-model ID and immutable revision are not explicitly verified.")

        renderer_ready = bool(
            safe_root
            and manifest_valid
            and unet_ready
            and verified_copy
            and onnx_ready
            and profile_metadata_ready
            and base_model_metadata_ready
        )
        contract = None
        if renderer_ready:
            contract = TensorRTBundleContract(
                root=root,
                manifest_path=manifest_path,
                engine_paths=engine_paths,
                onnx_paths=onnx_paths,
                profile_width=int(profile_width),
                profile_height=int(profile_height),
                batch_size=int(profile_batch),
                sample_size=int(profile_sample_size),
                base_model_id=base_model_id,
                base_model_revision=base_model_revision,
            )
        status = (
            "ready"
            if renderer_ready
            else ("engine_copy_incomplete_setup" if manifest_valid else ("incomplete" if exists else "absent"))
        )
        return {
            "exists": exists,
            "status": status,
            "manifest": {
                "name": MANIFEST_FILENAME,
                "schema_version": manifest.get("schema_version") if manifest else None,
                "valid": manifest_valid,
            },
            "engine_files": engine_rows,
            "engine_files_verified": verified_copy,
            "engine_hashes_verified_now": engine_hashes_verified_now,
            "extra_engine_files": extra_engine_files,
            "missing_engine_files": missing_engine_files,
            "unet_engine_ready": unet_ready,
            "onnx_files": onnx_file_rows,
            "onnx_manifest_valid": onnx_manifest_valid,
            "onnx_ready": onnx_ready,
            "profile_metadata_ready": profile_metadata_ready,
            "base_model_metadata_ready": base_model_metadata_ready,
            "base_model": {
                "id": base_model_id or None,
                "revision": base_model_revision or None,
            },
            "profile": {
                "width": profile_width if _strict_positive_int(profile_width) else None,
                "height": profile_height if _strict_positive_int(profile_height) else None,
                "batch_size": profile_batch if type(profile_batch) is int else None,
                "sample_size": profile_sample_size if _strict_positive_int(profile_sample_size) else None,
            },
            "renderer_ready": renderer_ready,
            "gaps": gaps,
            "_manifest_data": manifest,
            "_contract": contract,
        }

    def _canonical_status(self, *, include_hashes: bool) -> dict[str, Any]:
        status = self._bundle_status(self.canonical_root, include_hashes=include_hashes)
        status["layout"] = f"models/internal/tensorrt/{CANONICAL_BUNDLE_DIRNAME}"
        return status

    def validate_bundle_root(
        self,
        root: Path,
        *,
        verify_engine_hashes: bool = True,
    ) -> TensorRTBundleContract:
        """Return the shared runtime contract or reject the bundle fail-closed."""

        status = self._bundle_status(root, include_hashes=verify_engine_hashes)
        contract = status.get("_contract")
        if not isinstance(contract, TensorRTBundleContract) or (
            verify_engine_hashes and status.get("engine_hashes_verified_now") is not True
        ):
            gaps = [str(gap) for gap in status.get("gaps") or [] if str(gap).strip()]
            if verify_engine_hashes and status.get("engine_hashes_verified_now") is not True:
                gaps.append("The engine SHA-256 values were not verified against the manifest.")
            raise UserFacingError(
                "The TensorRT bundle is present but is not verified for execution",
                hint=" ".join(dict.fromkeys(gaps)) or "Complete and verify the bundle manifest, then retry.",
                code="TRT_BUNDLE_UNVERIFIED",
                status_code=409,
            )
        return contract

    def resolve_preferred_bundle(
        self,
        *,
        external_paths: Iterable[Path | str] = (),
        verify_engine_hashes: bool = True,
    ) -> TensorRTBundleContract | None:
        """Resolve canonical first, then only fully valid explicit overrides."""

        candidates: list[Path] = [self.canonical_root]
        candidates.extend(Path(path).expanduser() for path in external_paths if str(path or "").strip())
        candidates.extend(
            Path(raw).expanduser()
            for env_name in EXTERNAL_BUNDLE_ENV_VARS
            if (raw := str(os.getenv(env_name) or "").strip())
        )
        seen: set[str] = set()
        for candidate in candidates:
            try:
                key = os.path.normcase(str(candidate.resolve(strict=False)))
            except (OSError, RuntimeError):
                continue
            if key in seen:
                continue
            seen.add(key)
            try:
                return self.validate_bundle_root(
                    candidate,
                    verify_engine_hashes=verify_engine_hashes,
                )
            except UserFacingError:
                continue
        return None

    @staticmethod
    def _capacity_requirement(total_bytes: int) -> int:
        safety = max(_DISK_SAFETY_BYTES, int(total_bytes * 0.05))
        return total_bytes + safety

    def _disk_status(self, total_bytes: int) -> dict[str, Any]:
        required = self._capacity_requirement(total_bytes)
        try:
            free = int(shutil.disk_usage(self.legacy_root).free)
        except OSError:
            free = None
        return {
            "source_bytes": total_bytes,
            "safety_bytes": required - total_bytes,
            "required_free_bytes": required,
            "available_free_bytes": free,
            "enough_space": free is not None and free >= required,
        }

    def inspect(self, *, include_hashes: bool = False) -> dict[str, Any]:
        """Return a read-only legacy/canonical status report."""

        canonical = self._canonical_status(include_hashes=include_hashes)
        manifest = canonical.pop("_manifest_data", {})
        canonical.pop("_contract", None)
        canonical["origin"] = "canonical"
        canonical["selected"] = bool(canonical["renderer_ready"])

        external: list[dict[str, Any]] = []
        external_selected = False
        for env_name in EXTERNAL_BUNDLE_ENV_VARS:
            raw = str(os.getenv(env_name) or "").strip()
            if not raw:
                continue
            try:
                path = Path(raw).expanduser()
                status = self._bundle_status(path, include_hashes=include_hashes)
            except (OSError, RuntimeError):
                status = {
                    "exists": False,
                    "status": "incomplete",
                    "renderer_ready": False,
                    "gaps": ["The configured external bundle path is invalid or unreadable."],
                }
                path = Path(raw)
            status.pop("_manifest_data", None)
            status.pop("_contract", None)
            selected = bool(
                not canonical["renderer_ready"]
                and not external_selected
                and status.get("renderer_ready") is True
            )
            external_selected = external_selected or selected
            status.update(
                {
                    "origin": "external",
                    "environment": env_name,
                    "path": str(path),
                    "selected": selected,
                    "verification_state": (
                        (
                            "verified_now"
                            if status.get("engine_hashes_verified_now") is True
                            else "verified_contract"
                        )
                        if status.get("renderer_ready") is True
                        else "unverified"
                    ),
                }
            )
            external.append(status)

        legacy = self._legacy_status(
            include_hashes=include_hashes,
            known_hashes=(
                self._manifest_source_hashes(manifest)
                if canonical["manifest"]["valid"]
                else {}
            ),
        )
        disk = self._disk_status(int(legacy["total_bytes"])) if legacy["detected"] else {
            "source_bytes": 0,
            "safety_bytes": _DISK_SAFETY_BYTES,
            "required_free_bytes": _DISK_SAFETY_BYTES,
            "available_free_bytes": None,
            "enough_space": False,
        }

        blocked_reason: str | None = None
        if canonical["exists"]:
            blocked_reason = "canonical_ready" if canonical["renderer_ready"] else "canonical_exists"
        elif legacy["status"] == "absent":
            blocked_reason = "legacy_not_detected"
        elif legacy["status"] != "ready_to_import":
            blocked_reason = "legacy_incomplete"
        elif not disk["enough_space"]:
            blocked_reason = "insufficient_disk_space"

        return {
            "schema_version": 1,
            "model_id": MODEL_ID,
            "legacy": legacy,
            "canonical": canonical,
            "external": external,
            "selection": {
                "origin": (
                    "canonical"
                    if canonical["renderer_ready"]
                    else ("external" if external_selected else None)
                ),
                "renderer_ready": bool(canonical["renderer_ready"] or external_selected),
            },
            "migration": {
                "available": blocked_reason is None,
                "blocked_reason": blocked_reason,
                "copy_only": True,
                "source_will_be_preserved": True,
                "disk": disk,
            },
            "compatibility": {
                "legacy_detection_supported": True,
                "environment_bundle_override_supported": True,
                "removal_condition": (
                    "Keep legacy detection until at least one supported release cycle has shipped the explicit "
                    "copy workflow and release telemetry/support checks no longer find the root-level layout."
                ),
            },
        }

    def ensure_migration_available(self) -> dict[str, Any]:
        status = self.inspect(include_hashes=False)
        reason = status["migration"]["blocked_reason"]
        if reason is None:
            return status
        if reason == "legacy_not_detected":
            raise UserFacingError(
                "No legacy TensorRT engines were found",
                hint="Place the original engine set directly under Studio Home/models/internal/tensorrt, then refresh Models.",
                code="TRT_LEGACY_NOT_FOUND",
                status_code=404,
            )
        if reason == "legacy_incomplete":
            missing = status["legacy"]["missing_roles"] + status["legacy"]["unusable_roles"]
            raise UserFacingError(
                "The legacy TensorRT engine set is incomplete or unsafe to copy",
                hint=f"Repair or rebuild these engine roles first: {', '.join(sorted(set(missing))) or 'unknown'}.",
                code="TRT_LEGACY_PARTIAL",
                status_code=409,
            )
        if reason == "insufficient_disk_space":
            disk = status["migration"]["disk"]
            raise UserFacingError(
                "There is not enough free space to safely copy the TensorRT engines",
                hint=(
                    f"Free at least {int(disk['required_free_bytes'])} bytes on the Studio models drive. "
                    "Studio will not move or delete the legacy files."
                ),
                code="TRT_MIGRATION_DISK_SPACE",
                status_code=507,
            )
        raise UserFacingError(
            "The canonical TensorRT bundle folder already exists",
            hint=(
                "Studio will not overwrite it. Review the canonical bundle status in Models and complete its "
                "missing ONNX, base-model, and profile metadata requirements."
            ),
            code="TRT_CANONICAL_EXISTS",
            status_code=409,
        )

    def _copy_and_hash(
        self,
        source: Path,
        destination: Path,
        *,
        cancel_check: CancelCheck | None,
        on_chunk: Callable[[int], None],
    ) -> tuple[str, int, int]:
        source_size, source_mtime_ns = self._signature(source)
        digest = hashlib.sha256()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            while True:
                self._raise_if_cancelled(cancel_check)
                chunk = source_handle.read(self.copy_chunk_bytes)
                if not chunk:
                    break
                destination_handle.write(chunk)
                digest.update(chunk)
                on_chunk(len(chunk))
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        if self._signature(source) != (source_size, source_mtime_ns):
            raise UserFacingError(
                "A legacy TensorRT engine changed while Studio was copying it",
                hint="Wait for the engine-building process to finish, then retry.",
                code="TRT_LEGACY_SOURCE_CHANGED",
                status_code=409,
            )
        if destination.stat().st_size != source_size:
            raise UserFacingError(
                "Studio could not verify the copied TensorRT engine size",
                hint="Check the models drive for storage or filesystem errors, then retry.",
                code="TRT_MIGRATION_COPY_MISMATCH",
                status_code=500,
            )
        return digest.hexdigest(), source_size, source_mtime_ns

    @staticmethod
    def _write_manifest_atomic(path: Path, manifest: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _remove_staging(self, staging: Path) -> None:
        self._assert_managed_child(staging, staging=True)
        if not staging.exists():
            return
        if staging.is_symlink():
            raise RuntimeError("Refusing to follow an unexpected TensorRT staging symlink")
        shutil.rmtree(staging)

    def migrate(
        self,
        *,
        cancel_check: CancelCheck | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Copy verified legacy engines into the canonical bundle.

        The source files are opened read-only and never renamed or deleted.
        The destination is published only after every staged file passes a
        second SHA-256 read and the versioned manifest has been fsynced.
        """

        if not self._operation_lock.acquire(blocking=False):
            raise UserFacingError(
                "A TensorRT engine import is already running",
                hint="Wait for the active model task to finish or cancel it from Models.",
                code="TRT_MIGRATION_ACTIVE",
                status_code=409,
            )

        staging = self.legacy_root / f"{_STAGING_PREFIX}{uuid.uuid4().hex}.tmp"
        published = False
        try:
            self.ensure_migration_available()
            sources, _extras = self._discover_sources()
            if any(path is None or not _nonempty_file(path) for path in sources.values()):
                raise UserFacingError(
                    "The legacy TensorRT engine set changed before copying began",
                    hint="Refresh Models and verify the four expected engines before retrying.",
                    code="TRT_LEGACY_SOURCE_CHANGED",
                    status_code=409,
                )

            source_rows: list[tuple[str, Path, int, int]] = []
            for role in _ENGINE_NAMES:
                source = sources[role]
                assert source is not None
                size, mtime_ns = self._signature(source)
                source_rows.append((role, source, size, mtime_ns))
            total_bytes = sum(row[2] for row in source_rows)
            if not self._disk_status(total_bytes)["enough_space"]:
                self.ensure_migration_available()
                raise UserFacingError(
                    "There is not enough free space to safely copy the TensorRT engines",
                    hint="Free space on the Studio models drive and retry. The legacy files were not changed.",
                    code="TRT_MIGRATION_DISK_SPACE",
                    status_code=507,
                )

            self._raise_if_cancelled(cancel_check)
            self._assert_managed_child(staging, staging=True)
            staging.mkdir(parents=False, exist_ok=False)
            copied_bytes = 0
            manifest_files: list[dict[str, Any]] = []

            for file_index, (role, source, expected_size, expected_mtime_ns) in enumerate(source_rows):
                self._raise_if_cancelled(cancel_check)
                destination = staging / "engine" / source.name
                if progress is not None:
                    progress(
                        copied_bytes,
                        total_bytes,
                        file_index,
                        len(source_rows),
                        f"Copying {source.name}",
                    )

                def on_chunk(
                    count: int,
                    *,
                    current_file_index: int = file_index,
                    current_source_name: str = source.name,
                ) -> None:
                    nonlocal copied_bytes
                    copied_bytes += count
                    if progress is not None:
                        progress(
                            copied_bytes,
                            total_bytes,
                            current_file_index,
                            len(source_rows),
                            f"Copying {current_source_name}",
                        )

                source_sha, size, mtime_ns = self._copy_and_hash(
                    source,
                    destination,
                    cancel_check=cancel_check,
                    on_chunk=on_chunk,
                )
                if (size, mtime_ns) != (expected_size, expected_mtime_ns):
                    raise UserFacingError(
                        "A legacy TensorRT engine changed during import",
                        hint="Wait for engine generation to finish and retry.",
                        code="TRT_LEGACY_SOURCE_CHANGED",
                        status_code=409,
                    )

                if progress is not None:
                    progress(
                        copied_bytes,
                        total_bytes,
                        file_index,
                        len(source_rows),
                        f"Verifying {source.name}",
                    )
                destination_sha = self._cached_sha256(destination, cancel_check=cancel_check)
                if destination_sha != source_sha:
                    raise UserFacingError(
                        "A copied TensorRT engine failed SHA-256 verification",
                        hint="Check the models drive for storage or filesystem errors, then retry.",
                        code="TRT_MIGRATION_HASH_MISMATCH",
                        status_code=500,
                    )
                manifest_files.append(
                    {
                        "role": role,
                        "source_name": source.name,
                        "destination": f"engine/{source.name}",
                        "size_bytes": size,
                        "source_mtime_ns": mtime_ns,
                        "sha256": source_sha,
                        "destination_sha256": destination_sha,
                        "destination_mtime_ns": int(destination.stat().st_mtime_ns),
                    }
                )
                if progress is not None:
                    progress(
                        copied_bytes,
                        total_bytes,
                        file_index + 1,
                        len(source_rows),
                        f"Verified {source.name}",
                    )

            self._raise_if_cancelled(cancel_check)
            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "manifest_kind": "edmg.tensorrt.runtime_bundle",
                "model_id": MODEL_ID,
                "created_at": datetime.now(UTC).isoformat(),
                "operation": "legacy_engine_copy",
                "source_preserved": True,
                "source": {
                    "layout": "models/internal/tensorrt",
                    "files": manifest_files,
                },
                "canonical_layout": {
                    "root": f"models/internal/tensorrt/{CANONICAL_BUNDLE_DIRNAME}",
                    "engine_directory": "engine",
                    "onnx_directory": "onnx",
                },
                "profile": {
                    "width": 512,
                    "height": 512,
                    "batch_size": 1,
                    "sample_size": 64,
                    "source": "legacy_filename_convention",
                    "verified": False,
                },
                "base_model": {"id": None, "revision": None, "verified": False},
                "onnx": {
                    "verified": False,
                    "files": [],
                },
                "compatibility_at_import": {
                    "engine_files_verified": True,
                    "onnx_ready": False,
                    "profile_metadata_ready": False,
                    "base_model_metadata_ready": False,
                    "renderer_ready": False,
                    "gaps": [
                        "non-empty ONNX artifacts and UNet config",
                        "verified compiled width, height, and batch profile",
                        "verified matching SD 1.5 base-model metadata",
                    ],
                },
            }
            self._write_manifest_atomic(staging / MANIFEST_FILENAME, manifest)
            self._raise_if_cancelled(cancel_check)
            if self.canonical_root.exists():
                raise UserFacingError(
                    "The canonical TensorRT bundle appeared while Studio was importing",
                    hint="Studio did not overwrite it. Refresh Models and review its status.",
                    code="TRT_CANONICAL_EXISTS",
                    status_code=409,
                )
            self._assert_managed_child(self.canonical_root)
            staging.rename(self.canonical_root)
            published = True

            if progress is not None:
                progress(total_bytes, total_bytes, len(source_rows), len(source_rows), "Engine copy complete")
            return {
                "ok": True,
                "copied_file_count": len(manifest_files),
                "copied_bytes": total_bytes,
                "source_preserved": True,
                "canonical_renderer_ready": False,
                "status": self.inspect(include_hashes=False),
            }
        finally:
            try:
                if not published and staging.exists():
                    self._remove_staging(staging)
            finally:
                self._operation_lock.release()


__all__ = [
    "CANONICAL_BUNDLE_DIRNAME",
    "EXTERNAL_BUNDLE_ENV_VARS",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "MODEL_ID",
    "REQUIRED_ONNX_FILES",
    "TensorRTBundleContract",
    "TensorRTBundleMigration",
    "TensorRTMigrationCancelled",
]
