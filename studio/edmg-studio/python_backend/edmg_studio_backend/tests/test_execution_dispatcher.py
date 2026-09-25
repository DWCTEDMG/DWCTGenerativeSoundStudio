from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from edmg_studio_backend.execution.contracts import ExecutionPreference, ExecutionResult, ResultArtifact
from edmg_studio_backend.execution.dispatcher import (
    DispatchContext,
    ExecutionDispatchBlocked,
    ExecutionDispatcher,
)
from edmg_studio_backend.execution.policy import ExecutionCapabilities, ExecutionSettings


class _ActiveGuard:
    def __init__(self, active: bool):
        self.active = active

    def __enter__(self) -> bool:
        return self.active

    def __exit__(self, *_args) -> None:
        return None


def _write_result(context: DispatchContext, prepared) -> Path:
    output = prepared.output_root / "video.mp4"
    output.write_bytes(b"video")
    result = ExecutionResult(
        project_id=context.project_id,
        job_id=context.job_id,
        attempt=context.attempt,
        environment=prepared.manifest.environment,
        status="succeeded",
        artifacts=[ResultArtifact(
            relative_path="video.mp4",
            sha256=hashlib.sha256(b"video").hexdigest(),
            size_bytes=5,
            media_type="video/mp4",
        )],
    )
    path = prepared.output_root / "execution-result.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path


def test_dispatcher_resolves_prepares_runs_and_admits_current_attempt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "audio.wav"
    source.write_bytes(b"audio")
    dispatcher = ExecutionDispatcher(
        settings_provider=lambda: ExecutionSettings(runtime_profile="hybrid_gpu"),
        capabilities_provider=lambda: ExecutionCapabilities(
            supported_environments={"hunyuan_video15": frozenset({"wsl"})},
            gpu_environments=frozenset({"wsl"}),
        ),
        adapters={"wsl": _write_result},
    )
    context = DispatchContext(
        project_root=project,
        project_id="project-1",
        job_id="job-1",
        attempt=2,
        engine="hunyuan_video15",
        preference=ExecutionPreference(),
        physical_gpu_device_ids=("GPU-1",),
        inputs={"source.wav": source},
        parameters={"prompt": "neon"},
        publication_guard=lambda _project, _job, *, attempt: _ActiveGuard(attempt == 2),
    )

    dispatched = dispatcher.dispatch(context)

    assert dispatched.resolution.resolved_environment == "wsl"
    assert dispatched.result.status == "succeeded"
    assert dispatched.admitted.artifacts[0].staged_path.read_bytes() == b"video"


def test_dispatcher_blocks_external_and_never_invokes_local_adapter(tmp_path: Path) -> None:
    invoked = False

    def adapter(_context, _prepared):
        nonlocal invoked
        invoked = True
        raise AssertionError("must not execute")

    dispatcher = ExecutionDispatcher(
        settings_provider=lambda: ExecutionSettings(runtime_profile="external_linux"),
        capabilities_provider=lambda: ExecutionCapabilities(),
        adapters={"windows": adapter},
    )
    project = tmp_path / "project"
    project.mkdir()
    context = DispatchContext(
        project_root=project,
        project_id="project-1",
        job_id="job-1",
        attempt=0,
        engine="hunyuan_video15",
        preference=ExecutionPreference(environment="external"),
        publication_guard=lambda _project, _job, *, attempt: _ActiveGuard(True),
    )

    with pytest.raises(ExecutionDispatchBlocked, match="EXTERNAL_BACKEND_CLIENT_ONLY"):
        dispatcher.dispatch(context)
    assert not invoked
