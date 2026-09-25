"""Attempt-scoped worker staging and fail-closed result admission."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import ContextManager, Protocol

from pydantic import JsonValue, ValidationError

from .contracts import (
    ExecutionManifest,
    ExecutionResult,
    ManifestArtifact,
    ResolvedExecutionEnvironment,
    ResultArtifact,
    assert_result_matches_manifest,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_REPARSE_POINT = 0x400


class PublicationGuard(Protocol):
    def __call__(
        self,
        project_id: str,
        job_id: str,
        *,
        attempt: int,
    ) -> ContextManager[bool]: ...


class ExecutionAdmissionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedExecutionAttempt:
    project_root: Path
    attempt_root: Path
    input_root: Path
    output_root: Path
    manifest_path: Path
    manifest: ExecutionManifest


@dataclass(frozen=True)
class AdmittedArtifact:
    contract: ResultArtifact
    staged_path: Path


@dataclass(frozen=True)
class AdmittedExecutionResult:
    prepared: PreparedExecutionAttempt
    result: ExecutionResult
    artifacts: tuple[AdmittedArtifact, ...]
    receipts: tuple[AdmittedArtifact, ...]
    admission_marker: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return True


def _resolved_below(path: Path, root: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Path escapes its declared execution root: {path}",
        ) from exc
    return resolved


def windows_path_to_wsl(path: Path) -> str:
    raw = str(path)
    windows = PureWindowsPath(raw)
    if raw.startswith("\\\\") or str(windows.drive).startswith("\\\\"):
        raise ValueError("UNC paths are not supported for local WSL execution")
    if windows.drive and len(windows.drive) == 2 and windows.drive[1] == ":":
        drive = windows.drive[0].lower()
        parts = [part for part in windows.parts[1:] if part not in {"\\", "/"}]
        return "/".join(("", "mnt", drive, *parts))
    resolved = path.resolve()
    return resolved.as_posix()


def _worker_path(path: Path, environment: ResolvedExecutionEnvironment) -> str:
    return windows_path_to_wsl(path) if environment == "wsl" else str(path.resolve())


def _validate_identifier(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError(f"{name} contains unsafe path characters")
    return normalized


def prepare_execution_attempt(
    *,
    project_root: Path,
    project_id: str,
    job_id: str,
    attempt: int,
    engine: str,
    environment: ResolvedExecutionEnvironment,
    physical_gpu_device_ids: Sequence[str],
    inputs: Mapping[str, Path],
    parameters: Mapping[str, JsonValue],
) -> PreparedExecutionAttempt:
    root = Path(project_root).expanduser().resolve(strict=True)
    selected_project_id = _validate_identifier(project_id, "project_id")
    selected_job_id = _validate_identifier(job_id, "job_id")
    selected_attempt = int(attempt)
    if selected_attempt < 0:
        raise ValueError("attempt must be nonnegative")
    attempt_root = root / ".job-staging" / selected_job_id / f"attempt-{selected_attempt}"
    input_root = attempt_root / "inputs"
    output_root = attempt_root / "outputs"
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_inputs: list[ManifestArtifact] = []
    for relative_path, source_path in sorted(inputs.items()):
        contract = ManifestArtifact(
            relative_path=str(relative_path),
            sha256="0" * 64,
            size_bytes=0,
        )
        source = Path(source_path)
        resolved_source = _resolved_below(source, root)
        if source.is_symlink() or _is_reparse_point(source) or not resolved_source.is_file():
            raise ValueError(f"Execution input must be a regular project file: {source}")
        destination = input_root / contract.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_source, destination)
        destination.chmod(destination.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        manifest_inputs.append(
            ManifestArtifact(
                relative_path=contract.relative_path,
                sha256=_sha256(destination),
                size_bytes=destination.stat().st_size,
            )
        )

    cancel_token_path = attempt_root / "cancel.requested"
    manifest = ExecutionManifest(
        project_id=selected_project_id,
        job_id=selected_job_id,
        attempt=selected_attempt,
        engine=str(engine).strip(),
        environment=environment,
        physical_gpu_device_ids=list(physical_gpu_device_ids),
        input_root=_worker_path(input_root, environment),
        output_root=_worker_path(output_root, environment),
        inputs=manifest_inputs,
        parameters=dict(parameters),
        cancel_token_path=_worker_path(cancel_token_path, environment),
    )
    manifest_path = attempt_root / "execution-manifest.json"
    temporary = attempt_root / ".execution-manifest.tmp"
    temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return PreparedExecutionAttempt(
        project_root=root,
        attempt_root=attempt_root,
        input_root=input_root,
        output_root=output_root,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def _validate_media_type(artifact: ResultArtifact) -> None:
    suffix = Path(artifact.relative_path).suffix.lower()
    expected = {
        "application/json": {".json"},
        "video/mp4": {".mp4"},
        "audio/wav": {".wav", ".wave"},
    }.get(artifact.media_type or "")
    if expected is not None and suffix not in expected:
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Artifact extension does not match media type: {artifact.relative_path}",
        )


def _admit_artifact(
    output_root: Path,
    artifact: ResultArtifact,
) -> AdmittedArtifact:
    candidate = output_root / artifact.relative_path
    if candidate.is_symlink() or _is_reparse_point(candidate):
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Artifact cannot be a link or reparse point: {artifact.relative_path}",
        )
    try:
        resolved = _resolved_below(candidate, output_root)
    except FileNotFoundError as exc:
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Declared execution artifact is missing: {artifact.relative_path}",
        ) from exc
    if not resolved.is_file():
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Declared execution artifact is not a regular file: {artifact.relative_path}",
        )
    if resolved.stat().st_size != artifact.size_bytes or _sha256(resolved) != artifact.sha256:
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Execution artifact hash or size does not match: {artifact.relative_path}",
        )
    _validate_media_type(artifact)
    return AdmittedArtifact(contract=artifact, staged_path=resolved)


def admit_execution_result(
    prepared: PreparedExecutionAttempt,
    result_path: Path,
    *,
    publication_guard: PublicationGuard,
) -> AdmittedExecutionResult:
    marker = prepared.attempt_root / ".execution-admitted.json"
    candidate_result = Path(result_path)
    if candidate_result.is_symlink() or _is_reparse_point(candidate_result):
        raise ExecutionAdmissionError("EXECUTION_RESULT_INVALID", "Execution result path is unsafe")
    try:
        resolved_result = _resolved_below(candidate_result, prepared.output_root)
    except (FileNotFoundError, ExecutionAdmissionError) as exc:
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            "Execution result must be a regular file inside the attempt output root",
        ) from exc
    if not resolved_result.is_file():
        raise ExecutionAdmissionError("EXECUTION_RESULT_INVALID", "Execution result is not a file")
    try:
        result = ExecutionResult.model_validate_json(resolved_result.read_text(encoding="utf-8"))
        assert_result_matches_manifest(prepared.manifest, result)
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise ExecutionAdmissionError("EXECUTION_RESULT_INVALID", str(exc)) from exc
    if result.status != "succeeded":
        raise ExecutionAdmissionError(
            "EXECUTION_RESULT_INVALID",
            f"Only successful execution results can be admitted, received {result.status}",
        )

    with publication_guard(
        prepared.manifest.project_id,
        prepared.manifest.job_id,
        attempt=prepared.manifest.attempt,
    ) as active:
        if not active:
            raise ExecutionAdmissionError(
                "EXECUTION_ATTEMPT_OBSOLETE",
                "Execution attempt is canceled, replaced, or no longer active",
            )
        if marker.exists():
            raise ExecutionAdmissionError(
                "EXECUTION_PUBLICATION_REJECTED",
                "Execution result was already admitted",
            )
        artifacts = tuple(_admit_artifact(prepared.output_root, item) for item in result.artifacts)
        receipts = tuple(_admit_artifact(prepared.output_root, item) for item in result.receipts)
        temporary = prepared.attempt_root / ".execution-admitted.tmp"
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": result.project_id,
                    "job_id": result.job_id,
                    "attempt": result.attempt,
                    "result_sha256": _sha256(resolved_result),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(marker)
    return AdmittedExecutionResult(
        prepared=prepared,
        result=result,
        artifacts=artifacts,
        receipts=receipts,
        admission_marker=marker,
    )
