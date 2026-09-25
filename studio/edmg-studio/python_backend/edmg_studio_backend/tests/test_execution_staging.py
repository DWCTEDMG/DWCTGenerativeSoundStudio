from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from edmg_studio_backend.execution.contracts import ExecutionResult, ResultArtifact
from edmg_studio_backend.execution.staging import (
    ExecutionAdmissionError,
    admit_execution_result,
    prepare_execution_attempt,
    windows_path_to_wsl,
)
from edmg_studio_backend.revisions import execution_publication_artifacts


class Guard:
    def __init__(self, active: bool = True):
        self.active = active
        self.calls: list[tuple[str, str, int]] = []

    @contextmanager
    def __call__(self, project_id: str, job_id: str, *, attempt: int):
        self.calls.append((project_id, job_id, attempt))
        yield self.active


def _prepare(tmp_path: Path, *, attempt: int = 2):
    project_root = tmp_path / "project"
    source = project_root / "assets" / "audio.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-audio")
    prepared = prepare_execution_attempt(
        project_root=project_root,
        project_id="project-1",
        job_id="job-1",
        attempt=attempt,
        engine="hunyuan_video15",
        environment="wsl",
        physical_gpu_device_ids=["gpu-uuid:aaaa"],
        inputs={"source/audio.wav": source},
        parameters={"steps": 4},
    )
    return project_root, source, prepared


def _write_success(prepared, *, artifact_path: str = "outputs/video.mp4") -> Path:
    artifact = prepared.output_root / artifact_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"fresh-video")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipt = prepared.output_root / "receipts/runtime.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"runtime_ready": true}', encoding="utf-8")
    result = ExecutionResult(
        project_id=prepared.manifest.project_id,
        job_id=prepared.manifest.job_id,
        attempt=prepared.manifest.attempt,
        environment=prepared.manifest.environment,
        status="succeeded",
        artifacts=[
            ResultArtifact(
                relative_path=artifact_path,
                sha256=digest,
                size_bytes=artifact.stat().st_size,
                media_type="video/mp4",
            )
        ],
        receipts=[
            ResultArtifact(
                relative_path="receipts/runtime.json",
                sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                size_bytes=receipt.stat().st_size,
                media_type="application/json",
            )
        ],
    )
    result_path = prepared.output_root / "execution-result.json"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result_path


def test_prepare_copies_immutable_inputs_and_writes_wsl_manifest(tmp_path) -> None:
    _project, source, prepared = _prepare(tmp_path)
    staged = prepared.input_root / "source" / "audio.wav"

    assert staged.read_bytes() == b"source-audio"
    assert staged != source
    assert prepared.manifest.inputs[0].sha256 == hashlib.sha256(b"source-audio").hexdigest()
    assert prepared.manifest.input_root.startswith("/mnt/")
    assert prepared.manifest.output_root.startswith("/mnt/")
    assert prepared.manifest_path.is_file()
    source.write_bytes(b"mutated-source")
    assert staged.read_bytes() == b"source-audio"


def test_windows_path_translation_is_deterministic_and_rejects_unc() -> None:
    assert windows_path_to_wsl(Path(r"C:\Studio Data\job 1")) == "/mnt/c/Studio Data/job 1"
    with pytest.raises(ValueError, match="UNC"):
        windows_path_to_wsl(Path(r"\\server\share\job"))


def test_admission_validates_hashes_and_returns_existing_publication_artifacts(tmp_path) -> None:
    project_root, _source, prepared = _prepare(tmp_path)
    result_path = _write_success(prepared)
    guard = Guard()

    admitted = admit_execution_result(prepared, result_path, publication_guard=guard)
    publications = execution_publication_artifacts(admitted, project_root)

    assert guard.calls == [("project-1", "job-1", 2)]
    assert admitted.result.status == "succeeded"
    assert publications == [
        (prepared.output_root / "outputs" / "video.mp4", project_root / "outputs" / "video.mp4"),
        (
            prepared.output_root / "receipts" / "runtime.json",
            project_root / "receipts" / "runtime.json",
        ),
    ]


def test_admission_rejects_tampered_artifact(tmp_path) -> None:
    _project, _source, prepared = _prepare(tmp_path)
    result_path = _write_success(prepared)
    (prepared.output_root / "outputs" / "video.mp4").write_bytes(b"tampered")

    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, result_path, publication_guard=Guard())
    assert caught.value.code == "EXECUTION_RESULT_INVALID"


def test_admission_rejects_manifest_identity_mismatch(tmp_path) -> None:
    _project, _source, prepared = _prepare(tmp_path)
    result_path = _write_success(prepared)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["project_id"] = "other-project"
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, result_path, publication_guard=Guard())
    assert caught.value.code == "EXECUTION_RESULT_INVALID"


def test_obsolete_or_canceled_attempt_cannot_publish(tmp_path) -> None:
    project_root, _source, prepared = _prepare(tmp_path, attempt=0)
    result_path = _write_success(prepared)

    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, result_path, publication_guard=Guard(active=False))
    assert caught.value.code == "EXECUTION_ATTEMPT_OBSOLETE"
    assert not (project_root / "outputs" / "video.mp4").exists()


def test_duplicate_admission_is_rejected(tmp_path) -> None:
    _project, _source, prepared = _prepare(tmp_path)
    result_path = _write_success(prepared)
    admit_execution_result(prepared, result_path, publication_guard=Guard())

    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, result_path, publication_guard=Guard())
    assert caught.value.code == "EXECUTION_PUBLICATION_REJECTED"


def test_result_and_artifacts_must_remain_inside_attempt_output(tmp_path) -> None:
    _project, _source, prepared = _prepare(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    link = prepared.output_root / "outputs" / "video.mp4"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    result = ExecutionResult(
        project_id="project-1",
        job_id="job-1",
        attempt=2,
        environment="wsl",
        status="succeeded",
        artifacts=[ResultArtifact(relative_path="outputs/video.mp4", sha256=digest, size_bytes=7)],
    )
    result_path = prepared.output_root / "execution-result.json"
    result_path.write_text(result.model_dump_json(), encoding="utf-8")

    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, result_path, publication_guard=Guard())
    assert caught.value.code == "EXECUTION_RESULT_INVALID"


def test_result_path_outside_attempt_is_rejected(tmp_path) -> None:
    _project, _source, prepared = _prepare(tmp_path)
    outside = tmp_path / "execution-result.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ExecutionAdmissionError) as caught:
        admit_execution_result(prepared, outside, publication_guard=Guard())
    assert caught.value.code == "EXECUTION_RESULT_INVALID"
