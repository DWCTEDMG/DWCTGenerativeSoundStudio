from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from edmg_studio_backend.execution.contracts import (
    ExecutionFailure,
    ExecutionManifest,
    ExecutionPreference,
    ExecutionResult,
    ManifestArtifact,
    ResultArtifact,
    assert_result_matches_manifest,
)
from edmg_studio_backend.schemas import InternalVideoRenderRequest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "execution_plane"
SHA256_A = "a" * 64
SHA256_B = "b" * 64


def _manifest() -> ExecutionManifest:
    return ExecutionManifest(
        project_id="project-1",
        job_id="job-1",
        attempt=2,
        engine="hunyuan_video15",
        environment="wsl",
        physical_gpu_device_ids=["gpu-nvidia-uuid-1"],
        input_root="/home/studio/jobs/job-1/attempt-2/inputs",
        output_root="/home/studio/jobs/job-1/attempt-2/outputs",
        inputs=[
            ManifestArtifact(
                relative_path="source/audio.wav",
                sha256=SHA256_A,
                size_bytes=4096,
                media_type="audio/wav",
            )
        ],
        parameters={"steps": 4, "prompt": "continuous lateral motion"},
        cancel_token_path="/home/studio/jobs/job-1/attempt-2/cancel.requested",
    )


def _result(**updates: object) -> ExecutionResult:
    values: dict[str, object] = {
        "project_id": "project-1",
        "job_id": "job-1",
        "attempt": 2,
        "environment": "wsl",
        "status": "succeeded",
        "artifacts": [
            ResultArtifact(
                relative_path="video/output.mp4",
                sha256=SHA256_B,
                size_bytes=8192,
                media_type="video/mp4",
            )
        ],
        "receipts": [
            ResultArtifact(
                relative_path="receipts/runtime.json",
                sha256=SHA256_A,
                size_bytes=512,
                media_type="application/json",
            )
        ],
    }
    values.update(updates)
    return ExecutionResult.model_validate(values)


def test_execution_manifest_and_result_round_trip_as_frozen_strict_contracts() -> None:
    manifest = _manifest()
    result = _result()

    assert ExecutionManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert ExecutionResult.model_validate_json(result.model_dump_json()) == result
    assert_result_matches_manifest(manifest, result)

    with pytest.raises(ValidationError, match="frozen"):
        manifest.attempt = 3
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ExecutionManifest.model_validate({**manifest.model_dump(), "unexpected": True})


def test_execution_contracts_fail_closed_on_unknown_schema_versions() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        ExecutionManifest.model_validate({**_manifest().model_dump(), "schema_version": 2})
    with pytest.raises(ValidationError, match="schema_version"):
        ExecutionResult.model_validate({**_result().model_dump(), "schema_version": 2})


@pytest.mark.parametrize(
    "relative_path",
    [
        "/etc/passwd",
        "../outside.bin",
        "nested/../../outside.bin",
        r"C:\\Windows\\system32\\config",
        r"\\server\\share\\outside.bin",
        "nested\\..\\outside.bin",
        "",
    ],
)
def test_artifact_paths_must_be_safe_relative_paths(relative_path: str) -> None:
    with pytest.raises(ValidationError, match="relative_path"):
        ManifestArtifact(
            relative_path=relative_path,
            sha256=SHA256_A,
            size_bytes=1,
        )


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "g" * 64, "sha256:" + "a" * 64])
def test_artifact_hashes_require_lowercase_sha256(sha256: str) -> None:
    with pytest.raises(ValidationError, match="sha256"):
        ResultArtifact(relative_path="output.mp4", sha256=sha256, size_bytes=1)


@pytest.mark.parametrize(
    "updates",
    [
        {"project_id": "project-2"},
        {"job_id": "job-2"},
        {"attempt": 3},
        {"environment": "windows"},
    ],
)
def test_result_identity_must_match_manifest(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="does not match execution manifest"):
        assert_result_matches_manifest(_manifest(), _result(**updates))


def test_failed_result_requires_typed_error_and_success_rejects_one() -> None:
    failure = ExecutionFailure(code="EXECUTION_WORKER_EXITED", message="worker exited with code 1")
    failed = _result(status="failed", artifacts=[], receipts=[], error=failure)
    assert failed.error == failure

    with pytest.raises(ValidationError, match="failed execution result requires an error"):
        _result(status="failed", artifacts=[], receipts=[], error=None)
    with pytest.raises(ValidationError, match="successful execution result cannot contain an error"):
        _result(error=failure)


def test_legacy_internal_video_request_keeps_normalized_fingerprint_and_omits_preference() -> None:
    fixture = FIXTURE_ROOT / "legacy_internal_video_request.json"
    request = InternalVideoRenderRequest.model_validate_json(fixture.read_text(encoding="utf-8"))
    normalized = request.model_dump(exclude_none=True)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert "execution_preference" not in normalized
    assert hashlib.sha256(encoded).hexdigest() == "4c9109657368b065412763de9b52684966d1e3a4de0f12c709c8fa6df4f88045"


def test_explicit_execution_preference_serializes_without_mutating_defaults() -> None:
    request = InternalVideoRenderRequest(
        execution_preference=ExecutionPreference(
            environment="wsl",
            gpu_device_id="gpu-nvidia-uuid-1",
            allow_environment_fallback=False,
        )
    )

    assert request.model_dump(exclude_none=True)["execution_preference"] == {
        "environment": "wsl",
        "gpu_device_id": "gpu-nvidia-uuid-1",
        "allow_environment_fallback": False,
    }
