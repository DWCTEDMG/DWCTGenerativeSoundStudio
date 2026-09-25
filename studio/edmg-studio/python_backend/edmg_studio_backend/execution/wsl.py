"""Bounded, argument-safe WSL process transport for execution workers."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import ExecutionFailure
from .staging import PreparedExecutionAttempt, windows_path_to_wsl


class CancellationToken(Protocol):
    def is_canceled(self) -> bool: ...


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    canceled: bool = False


class ProcessRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        cancel_check: Callable[[], bool],
        stdout_path: Path,
        stderr_path: Path,
        grace_seconds: float,
    ) -> ProcessOutcome: ...


@dataclass(frozen=True)
class WslProbeResult:
    ready: bool
    distro: str
    failure: ExecutionFailure | None = None


@dataclass(frozen=True)
class ExecutionProcessResult:
    succeeded: bool
    stdout_path: Path
    stderr_path: Path
    result_path: Path | None = None
    failure: ExecutionFailure | None = None


class SubprocessRunner:
    """Run an owned process without a shell and bound its lifetime."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        cancel_check: Callable[[], bool],
        stdout_path: Path,
        stderr_path: Path,
        grace_seconds: float,
    ) -> ProcessOutcome:
        started = time.monotonic()
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                tuple(args),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                creationflags=creationflags,
            )
            while process.poll() is None:
                canceled = cancel_check()
                timed_out = time.monotonic() - started >= timeout_seconds
                if canceled or timed_out:
                    process.terminate()
                    try:
                        process.wait(timeout=grace_seconds)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=max(1.0, grace_seconds))
                    return ProcessOutcome(
                        returncode=process.returncode if process.returncode is not None else -1,
                        timed_out=timed_out,
                        canceled=canceled,
                    )
                time.sleep(0.05)
            return ProcessOutcome(returncode=int(process.returncode or 0))


def _truncate_log(path: Path, maximum: int) -> None:
    if maximum < 1 or not path.exists() or path.stat().st_size <= maximum:
        return
    with path.open("rb") as stream:
        stream.seek(-maximum, os.SEEK_END)
        tail = stream.read(maximum)
    path.write_bytes(tail)


def _is_wsl_environment_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "wsl_e_distro_not_found",
            "no distribution with the supplied name",
            "distribution is not running",
            "the windows subsystem for linux",
            "wsl service",
        )
    )


class WslExecutionTransport:
    def __init__(
        self,
        distro: str,
        *,
        runner: ProcessRunner | None = None,
        timeout_seconds: float = 24 * 60 * 60,
        grace_seconds: float = 5.0,
        result_wait_seconds: float = 2.0,
        max_log_bytes: int = 4 * 1024 * 1024,
    ):
        selected = str(distro).strip()
        if not selected:
            raise ValueError("WSL distribution is required")
        if timeout_seconds <= 0 or grace_seconds < 0 or result_wait_seconds < 0:
            raise ValueError("WSL execution time bounds must be nonnegative and timeout positive")
        if max_log_bytes < 1:
            raise ValueError("WSL log limit must be positive")
        self.distro = selected
        self.runner = runner or SubprocessRunner()
        self.timeout_seconds = float(timeout_seconds)
        self.grace_seconds = float(grace_seconds)
        self.result_wait_seconds = float(result_wait_seconds)
        self.max_log_bytes = int(max_log_bytes)

    def probe(self, distro: str, timeout_seconds: float) -> WslProbeResult:
        selected = str(distro).strip()
        if not selected:
            return WslProbeResult(
                ready=False,
                distro=selected,
                failure=ExecutionFailure(
                    code="EXECUTION_ENVIRONMENT_UNAVAILABLE",
                    message="WSL distribution is required",
                ),
            )
        with tempfile.TemporaryDirectory(prefix="edmg-wsl-probe-") as temporary:
            root = Path(temporary)
            stdout_path = root / "stdout.log"
            stderr_path = root / "stderr.log"
            try:
                outcome = self.runner.run(
                    (
                        "wsl.exe",
                        "--distribution",
                        selected,
                        "--exec",
                        "/usr/bin/env",
                        "true",
                    ),
                    timeout_seconds=float(timeout_seconds),
                    cancel_check=lambda: False,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    grace_seconds=self.grace_seconds,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return WslProbeResult(
                    ready=False,
                    distro=selected,
                    failure=ExecutionFailure(
                        code="EXECUTION_ENVIRONMENT_UNAVAILABLE",
                        message=str(exc),
                    ),
                )
            stderr = outcome.stderr or (
                stderr_path.read_text(encoding="utf-8", errors="replace")
                if stderr_path.exists()
                else ""
            )
            if outcome.returncode == 0 and not outcome.timed_out:
                return WslProbeResult(ready=True, distro=selected)
            return WslProbeResult(
                ready=False,
                distro=selected,
                failure=ExecutionFailure(
                    code="EXECUTION_ENVIRONMENT_UNAVAILABLE",
                    message=stderr.strip() or "WSL distribution probe failed",
                ),
            )

    def execute(
        self,
        prepared: PreparedExecutionAttempt,
        command: Sequence[str],
        cancellation: CancellationToken,
    ) -> ExecutionProcessResult:
        selected_command = tuple(str(item) for item in command)
        if not selected_command or any(not item for item in selected_command):
            raise ValueError("WSL worker command cannot be empty")
        log_root = prepared.attempt_root / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        stdout_path = log_root / "wsl-worker.stdout.log"
        stderr_path = log_root / "wsl-worker.stderr.log"
        cancel_path = prepared.attempt_root / "cancel.requested"

        def is_canceled() -> bool:
            canceled = bool(cancellation.is_canceled())
            if canceled:
                cancel_path.touch(exist_ok=True)
            return canceled

        is_canceled()
        args = (
            "wsl.exe",
            "--distribution",
            self.distro,
            "--exec",
            *selected_command,
            "--manifest",
            windows_path_to_wsl(prepared.manifest_path),
        )
        try:
            outcome = self.runner.run(
                args,
                timeout_seconds=self.timeout_seconds,
                cancel_check=is_canceled,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                grace_seconds=self.grace_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            outcome = ProcessOutcome(returncode=-1, stderr=str(exc))
            stderr_path.write_text(str(exc), encoding="utf-8")
        _truncate_log(stdout_path, self.max_log_bytes)
        _truncate_log(stderr_path, self.max_log_bytes)
        stderr = outcome.stderr or (
            stderr_path.read_text(encoding="utf-8", errors="replace")
            if stderr_path.exists()
            else ""
        )
        details = {
            "returncode": outcome.returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        if outcome.canceled or cancellation.is_canceled():
            cancel_path.touch(exist_ok=True)
            return ExecutionProcessResult(
                succeeded=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure=ExecutionFailure(
                    code="EXECUTION_ATTEMPT_OBSOLETE",
                    message="WSL execution was canceled",
                    details=details,
                ),
            )
        if outcome.timed_out:
            return ExecutionProcessResult(
                succeeded=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure=ExecutionFailure(
                    code="EXECUTION_WORKER_TIMEOUT",
                    message="WSL worker exceeded its execution timeout",
                    details=details,
                ),
            )
        if outcome.returncode != 0:
            environment_failed = _is_wsl_environment_failure(stderr)
            return ExecutionProcessResult(
                succeeded=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure=ExecutionFailure(
                    code=(
                        "EXECUTION_ENVIRONMENT_UNAVAILABLE"
                        if environment_failed
                        else "EXECUTION_WORKER_EXITED"
                    ),
                    message=stderr.strip() or f"WSL worker exited with code {outcome.returncode}",
                    details=details,
                ),
            )

        result_path = prepared.output_root / "execution-result.json"
        deadline = time.monotonic() + self.result_wait_seconds
        while not result_path.is_file() and time.monotonic() < deadline:
            if is_canceled():
                break
            time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
        if not result_path.is_file():
            return ExecutionProcessResult(
                succeeded=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure=ExecutionFailure(
                    code="EXECUTION_RESULT_INVALID",
                    message="WSL worker exited successfully without an execution result",
                    details=details,
                ),
            )
        return ExecutionProcessResult(
            succeeded=True,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            result_path=result_path,
        )
