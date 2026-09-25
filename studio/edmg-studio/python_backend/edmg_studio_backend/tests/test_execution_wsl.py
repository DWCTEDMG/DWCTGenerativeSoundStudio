from __future__ import annotations

import threading
import time
from pathlib import Path

from edmg_studio_backend.execution.staging import prepare_execution_attempt, windows_path_to_wsl
from edmg_studio_backend.execution.wsl import (
    ProcessOutcome,
    WslExecutionTransport,
)


class Cancellation:
    def __init__(self, canceled: bool = False):
        self.canceled = canceled

    def is_canceled(self) -> bool:
        return self.canceled


class FakeRunner:
    def __init__(self, outcome: ProcessOutcome, callback=None):
        self.outcome = outcome
        self.callback = callback
        self.calls: list[dict] = []

    def run(self, args, **kwargs):
        self.calls.append({"args": tuple(args), **kwargs})
        kwargs["stdout_path"].write_text(self.outcome.stdout, encoding="utf-8")
        kwargs["stderr_path"].write_text(self.outcome.stderr, encoding="utf-8")
        if self.callback:
            self.callback(args, kwargs)
        return self.outcome


def _prepared(tmp_path: Path):
    project = tmp_path / "project"
    source = project / "assets" / "source.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    return prepare_execution_attempt(
        project_root=project,
        project_id="project-1",
        job_id="job-1",
        attempt=0,
        engine="hunyuan_video15",
        environment="wsl",
        physical_gpu_device_ids=["gpu-uuid:aaaa"],
        inputs={"source.wav": source},
        parameters={},
    )


def test_execute_preserves_arguments_and_passes_one_manifest_path(tmp_path) -> None:
    prepared = _prepared(tmp_path)

    def write_result(_args, _kwargs):
        (prepared.output_root / "execution-result.json").write_text("{}", encoding="utf-8")

    runner = FakeRunner(ProcessOutcome(returncode=0, stdout="✓ generated", stderr=""), write_result)
    transport = WslExecutionTransport("Ubuntu", runner=runner)
    result = transport.execute(
        prepared,
        ["/opt/worker/python", "-m", "worker", "--prompt", "a; $(touch nope)"],
        Cancellation(),
    )

    call = runner.calls[0]
    assert call["args"] == (
        "wsl.exe",
        "--distribution",
        "Ubuntu",
        "--exec",
        "/opt/worker/python",
        "-m",
        "worker",
        "--prompt",
        "a; $(touch nope)",
        "--manifest",
        windows_path_to_wsl(prepared.manifest_path),
    )
    assert result.succeeded
    assert result.result_path == prepared.output_root / "execution-result.json"
    assert result.stdout_path.read_text(encoding="utf-8") == "✓ generated"


def test_probe_reports_ready_and_missing_distribution(tmp_path) -> None:
    ready_runner = FakeRunner(ProcessOutcome(0, "", ""))
    ready = WslExecutionTransport("Ubuntu", runner=ready_runner).probe("Ubuntu", 3)
    assert ready.ready
    assert ready_runner.calls[0]["args"] == (
        "wsl.exe",
        "--distribution",
        "Ubuntu",
        "--exec",
        "/usr/bin/env",
        "true",
    )

    missing_runner = FakeRunner(
        ProcessOutcome(1, "", "There is no distribution with the supplied name")
    )
    missing = WslExecutionTransport("Missing", runner=missing_runner).probe("Missing", 3)
    assert not missing.ready
    assert missing.failure.code == "EXECUTION_ENVIRONMENT_UNAVAILABLE"


def test_cancellation_creates_token_and_returns_typed_failure(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    cancellation = Cancellation(True)
    runner = FakeRunner(ProcessOutcome(returncode=-1, stdout="", stderr="", canceled=True))
    result = WslExecutionTransport("Ubuntu", runner=runner).execute(
        prepared,
        ["/opt/worker/python"],
        cancellation,
    )

    assert prepared.attempt_root.joinpath("cancel.requested").is_file()
    assert not result.succeeded
    assert result.failure.code == "EXECUTION_ATTEMPT_OBSOLETE"
    assert runner.calls[0]["grace_seconds"] == 5.0


def test_timeout_and_wsl_shutdown_are_distinct_typed_failures(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    timeout = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(-1, "", "timed out", timed_out=True)),
    ).execute(prepared, ["worker"], Cancellation())
    shutdown = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(1, "", "WSL_E_DISTRO_NOT_FOUND")),
    ).execute(prepared, ["worker"], Cancellation())

    assert timeout.failure.code == "EXECUTION_WORKER_TIMEOUT"
    assert shutdown.failure.code == "EXECUTION_ENVIRONMENT_UNAVAILABLE"


def test_nonzero_worker_exit_retains_attempt_logs(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    result = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(7, "worker out", "model failed")),
    ).execute(prepared, ["worker"], Cancellation())

    assert result.failure.code == "EXECUTION_WORKER_EXITED"
    assert result.failure.details["returncode"] == 7
    assert result.stdout_path.read_text(encoding="utf-8") == "worker out"
    assert result.stderr_path.read_text(encoding="utf-8") == "model failed"


def test_logs_are_bounded_after_process_exit(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    result = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(1, "x" * 200, "y" * 200)),
        max_log_bytes=64,
    ).execute(prepared, ["worker"], Cancellation())

    assert result.stdout_path.stat().st_size <= 64
    assert result.stderr_path.stat().st_size <= 64


def test_execute_waits_briefly_for_delayed_result_file(tmp_path) -> None:
    prepared = _prepared(tmp_path)

    def write_delayed(_args, _kwargs):
        def write():
            time.sleep(0.05)
            (prepared.output_root / "execution-result.json").write_text("{}", encoding="utf-8")

        threading.Thread(target=write, daemon=True).start()

    result = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(0, "", ""), write_delayed),
        result_wait_seconds=0.5,
    ).execute(prepared, ["worker"], Cancellation())

    assert result.succeeded


def test_zero_exit_without_result_is_invalid(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    result = WslExecutionTransport(
        "Ubuntu",
        runner=FakeRunner(ProcessOutcome(0, "", "")),
        result_wait_seconds=0,
    ).execute(prepared, ["worker"], Cancellation())

    assert not result.succeeded
    assert result.failure.code == "EXECUTION_RESULT_INVALID"
