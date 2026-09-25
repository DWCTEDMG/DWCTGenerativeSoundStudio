"""Immutable contracts exchanged across Studio execution boundaries."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

ExecutionEnvironment: TypeAlias = Literal["auto", "windows", "wsl", "external"]
ResolvedExecutionEnvironment: TypeAlias = Literal["windows", "wsl", "external"]
RuntimeProfile: TypeAlias = Literal["standard", "hybrid_gpu", "external_linux"]
ExecutionStatus: TypeAlias = Literal["succeeded", "failed", "canceled"]
ExecutionFailureCode: TypeAlias = Literal[
    "EXECUTION_ENVIRONMENT_UNAVAILABLE",
    "EXECUTION_ENVIRONMENT_NOT_SUPPORTED",
    "EXECUTION_GPU_NOT_VISIBLE",
    "EXECUTION_GPU_BUSY",
    "EXECUTION_MANIFEST_INVALID",
    "EXECUTION_RESULT_INVALID",
    "EXECUTION_WORKER_TIMEOUT",
    "EXECUTION_WORKER_EXITED",
    "EXECUTION_ATTEMPT_OBSOLETE",
    "EXECUTION_PUBLICATION_REJECTED",
]

Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _validate_relative_artifact_path(value: str) -> str:
    if not value or len(value) > 2048 or "\x00" in value or "\\" in value:
        raise ValueError("relative_path must be a canonical relative POSIX path")
    raw_parts = value.split("/")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError("relative_path must remain below its declared root")
    return value


class ExecutionPreference(FrozenContract):
    environment: ExecutionEnvironment = "auto"
    gpu_device_id: str | None = Field(default=None, min_length=1, max_length=256)
    allow_environment_fallback: bool = True


class ManifestArtifact(FrozenContract):
    relative_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    media_type: str | None = Field(default=None, min_length=1, max_length=160)

    _relative_path = field_validator("relative_path")(_validate_relative_artifact_path)


class ResultArtifact(FrozenContract):
    relative_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    media_type: str | None = Field(default=None, min_length=1, max_length=160)

    _relative_path = field_validator("relative_path")(_validate_relative_artifact_path)


class ExecutionFailure(FrozenContract):
    code: ExecutionFailureCode
    message: str = Field(min_length=1, max_length=8000)
    details: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)


class ExecutionManifest(FrozenContract):
    schema_version: Literal[1] = 1
    project_id: Identifier
    job_id: Identifier
    attempt: int = Field(ge=0)
    engine: str = Field(min_length=1, max_length=160)
    environment: ResolvedExecutionEnvironment
    physical_gpu_device_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    input_root: str = Field(min_length=1, max_length=4096)
    output_root: str = Field(min_length=1, max_length=4096)
    inputs: list[ManifestArtifact] = Field(default_factory=list, max_length=4096)
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=512)
    cancel_token_path: str = Field(min_length=1, max_length=4096)

    @field_validator("physical_gpu_device_ids")
    @classmethod
    def validate_unique_physical_gpus(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("physical_gpu_device_ids must be unique")
        return value


class ExecutionResult(FrozenContract):
    schema_version: Literal[1] = 1
    project_id: Identifier
    job_id: Identifier
    attempt: int = Field(ge=0)
    environment: ResolvedExecutionEnvironment
    status: ExecutionStatus
    artifacts: list[ResultArtifact] = Field(default_factory=list, max_length=4096)
    receipts: list[ResultArtifact] = Field(default_factory=list, max_length=4096)
    error: ExecutionFailure | None = None

    @model_validator(mode="after")
    def validate_error_for_status(self) -> ExecutionResult:
        if self.status == "failed" and self.error is None:
            raise ValueError("failed execution result requires an error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("successful execution result cannot contain an error")
        return self


def assert_result_matches_manifest(
    manifest: ExecutionManifest,
    result: ExecutionResult,
) -> None:
    """Reject a result that belongs to another project, job, attempt, or environment."""

    expected = (
        manifest.project_id,
        manifest.job_id,
        manifest.attempt,
        manifest.environment,
    )
    actual = (
        result.project_id,
        result.job_id,
        result.attempt,
        result.environment,
    )
    if actual != expected:
        raise ValueError("execution result identity does not match execution manifest")
