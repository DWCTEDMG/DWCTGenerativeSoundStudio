from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from edmg_studio_backend.execution.contracts import ExecutionFailure
from edmg_studio_backend.execution.contracts import ExecutionResult
from edmg_studio_backend.execution.staging import prepare_execution_attempt
from edmg_studio_backend.execution.wsl import ExecutionProcessResult
from edmg_studio_backend.services import hunyuan_execution_worker
from edmg_studio_backend.services import internal_video_models as ivm


class Cancellation:
    def __init__(self, canceled: bool = False):
        self.canceled = canceled

    def is_canceled(self) -> bool:
        return self.canceled


class FakeTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, prepared, command, cancellation):
        self.calls.append((prepared, tuple(command), cancellation))
        return self.result


def _prepared(tmp_path: Path, *, devices=("gpu-uuid:aaaa", "gpu-uuid:bbbb")):
    project = tmp_path / "project"
    source = project / "assets" / "source.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    return prepare_execution_attempt(
        project_root=project,
        project_id="project-1",
        job_id="job-1",
        attempt=3,
        engine="hunyuan_video15",
        environment="wsl",
        physical_gpu_device_ids=list(devices),
        inputs={"source/audio.wav": source},
        parameters={"generation_mode": "t2v"},
    )


def _config() -> ivm.HunyuanRunnerConfig:
    return ivm.HunyuanRunnerConfig(
        mode="wsl",
        python="/opt/hunyuan/bin/python",
        repo="/opt/HunyuanVideo-1.5",
        model_path="/models/hunyuan",
        distro="Ubuntu",
        timeout_s=7200,
        gpus="2,0",
        companions={
            "llm": "/models/llm",
            "byt5": "/models/byt5",
            "glyph": "/models/glyph",
            "vision": "/models/vision",
        },
    )


def test_adapter_acquires_physical_gpu_lease_and_invokes_manifest_worker(tmp_path, monkeypatch) -> None:
    prepared = _prepared(tmp_path)
    stdout = prepared.attempt_root / "stdout.log"
    stderr = prepared.attempt_root / "stderr.log"
    result_path = prepared.output_root / "execution-result.json"
    result_path.write_text("{}", encoding="utf-8")
    transport = FakeTransport(ExecutionProcessResult(True, stdout, stderr, result_path=result_path))
    leases = []

    @contextmanager
    def lease(device_ids, **kwargs):
        leases.append((tuple(device_ids), kwargs))
        yield SimpleNamespace(device_ids=tuple(device_ids))

    monkeypatch.setattr(ivm, "gpu_execution_lease", lease)
    adapter = ivm.WslHunyuanExecutionAdapter(_config(), transport=transport)
    cancellation = Cancellation()
    result = adapter.execute(prepared, cancellation=cancellation)

    assert result.succeeded
    assert leases == [
        (
            ("gpu-uuid:aaaa", "gpu-uuid:bbbb"),
            {
                "job_id": "job-1",
                "attempt": 3,
                "cancel_check": cancellation.is_canceled,
                "timeout_seconds": 7200,
            },
        )
    ]
    command = transport.calls[0][1]
    assert command[:3] == (
        "env",
        "CUDA_VISIBLE_DEVICES=2,0",
        "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
    )
    assert command[3].startswith("PYTHONPATH=/opt/HunyuanVideo-1.5:")
    assert command[-3:] == (
        "-m",
        "edmg_studio_backend.services.hunyuan_execution_worker",
        "--config-from-manifest",
    )


def test_adapter_rejects_non_wsl_or_missing_configuration(tmp_path) -> None:
    prepared = _prepared(tmp_path)
    invalid = ivm.HunyuanRunnerConfig(
        mode="external",
        python="",
        repo="",
        model_path="",
        distro=None,
        timeout_s=0,
        gpus="",
        companions={},
    )
    with pytest.raises(ValueError, match="WSL Hunyuan"):
        ivm.WslHunyuanExecutionAdapter(invalid, transport=FakeTransport(None))


def test_unrelated_worker_failure_remains_fail_closed_without_adapter_retry(tmp_path, monkeypatch) -> None:
    prepared = _prepared(tmp_path, devices=("gpu-uuid:aaaa",))
    failure = ExecutionFailure(
        code="EXECUTION_WORKER_EXITED",
        message="invalid model configuration",
    )
    transport = FakeTransport(
        ExecutionProcessResult(
            False,
            prepared.attempt_root / "stdout.log",
            prepared.attempt_root / "stderr.log",
            failure=failure,
        )
    )

    @contextmanager
    def lease(*_args, **_kwargs):
        yield SimpleNamespace()

    monkeypatch.setattr(ivm, "gpu_execution_lease", lease)
    result = ivm.WslHunyuanExecutionAdapter(_config(), transport=transport).execute(
        prepared,
        cancellation=Cancellation(),
    )

    assert not result.succeeded
    assert result.failure == failure
    assert len(transport.calls) == 1


def test_manifest_worker_retries_known_distributed_failure_and_writes_validated_receipts(tmp_path) -> None:
    project = tmp_path / "project"
    audio = project / "assets" / "source.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    prepared = prepare_execution_attempt(
        project_root=project,
        project_id="project-1",
        job_id="job-1",
        attempt=1,
        engine="hunyuan_video15",
        environment="wsl",
        physical_gpu_device_ids=["gpu-uuid:aaaa", "gpu-uuid:bbbb"],
        inputs={"source/audio.wav": audio},
        parameters={
            "request": {"mode": "t2v", "prompt": "moving subject", "frames": 17, "fps": 8},
            "model_path": "/models/hunyuan",
            "companions": {
                "llm": "/models/llm",
                "byt5": "/models/byt5",
                "glyph": "/models/glyph",
                "vision": "/models/vision",
            },
            "wsl_gpu_indices": ["2", "0"],
            "source_audio": "source/audio.wav",
            "motion_evidence": {"status": "pass", "frame_count": 17},
        },
    )
    commands = []
    torch_attempt = 0

    def run(command, **_kwargs):
        nonlocal torch_attempt
        commands.append(tuple(command))
        if "torch.distributed.run" in command:
            torch_attempt += 1
            if torch_attempt == 1:
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="torch.distributed.DistBackendError: NCCL error CUDA failure 999",
                )
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"raw-mp4")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"muxed-mp4")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[0] == "ffprobe":
            return SimpleNamespace(
                returncode=0,
                stdout='{"streams":[{"codec_type":"video"},{"codec_type":"audio"}]}',
                stderr="",
            )
        raise AssertionError(command)

    result_path = hunyuan_execution_worker.run_manifest(prepared.manifest_path, run=run)
    result = ExecutionResult.model_validate_json(result_path.read_text(encoding="utf-8"))

    assert result.status == "succeeded"
    assert {item.relative_path for item in result.receipts} == {
        "receipts/model.json",
        "receipts/motion.json",
        "receipts/runtime.json",
        "receipts/segment.json",
        "receipts/source-audio.json",
    }
    torch_commands = [command for command in commands if "torch.distributed.run" in command]
    assert "--nproc_per_node" in torch_commands[0]
    assert torch_commands[0][torch_commands[0].index("--nproc_per_node") + 1] == "2"
    assert torch_commands[1][torch_commands[1].index("--nproc_per_node") + 1] == "1"
    assert (prepared.output_root / "logs" / "worker.distributed.stderr.log").is_file()


def test_manifest_worker_does_not_retry_unrelated_failure(tmp_path) -> None:
    prepared = _prepared(tmp_path, devices=("gpu-uuid:aaaa", "gpu-uuid:bbbb"))
    payload = prepared.manifest.model_dump(mode="json")
    payload["parameters"] = {
        "request": {"mode": "t2v", "prompt": "moving subject", "frames": 17, "fps": 8},
        "model_path": "/models/hunyuan",
        "companions": {
            "llm": "/models/llm",
            "byt5": "/models/byt5",
            "glyph": "/models/glyph",
            "vision": "/models/vision",
        },
        "wsl_gpu_indices": ["2", "0"],
    }
    prepared.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    calls = 0

    def run(_command, **_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=1, stdout="", stderr="invalid configuration")

    with pytest.raises(RuntimeError, match="invalid configuration"):
        hunyuan_execution_worker.run_manifest(prepared.manifest_path, run=run)
    assert calls == 1
