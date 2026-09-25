"""Linux entry point for manifest-scoped HunyuanVideo-1.5 execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ..execution.contracts import ExecutionManifest, ExecutionResult, ResultArtifact


def _local_path(value: str) -> Path:
    """Resolve a worker path, including WSL paths during native Windows tests."""

    if os.name == "nt" and value.startswith("/mnt/"):
        parts = PurePosixPath(value).parts
        if len(parts) >= 4 and len(parts[2]) == 1:
            return Path(f"{parts[2].upper()}:\\", *parts[3:])
    return Path(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, relative_path: str, media_type: str) -> ResultArtifact:
    return ResultArtifact(
        relative_path=relative_path,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        media_type=media_type,
    )


def _write_receipt(root: Path, relative_path: str, payload: dict[str, Any]) -> ResultArtifact:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return _artifact(path, relative_path, "application/json")


def _distributed_cuda_failure(stderr: str, gpu_count: int) -> bool:
    text = str(stderr or "").lower()
    return gpu_count > 1 and (
        "ncclunhandledcudaerror" in text
        or ("distbackenderror" in text and "cuda failure 999" in text)
        or ("nccl error" in text and "cuda failure 999" in text)
    )


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Manifest parameter {name} must be an object")
    return value


def _run_checked(
    run: Callable[..., Any],
    command: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
) -> Any:
    result = run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if int(result.returncode) != 0:
        detail = str(result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(detail)
    return result


def run_manifest(
    manifest_path: Path,
    *,
    run: Callable[..., Any] = subprocess.run,
) -> Path:
    manifest = ExecutionManifest.model_validate_json(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.engine != "hunyuan_video15" or manifest.environment != "wsl":
        raise ValueError("Hunyuan execution worker requires a WSL Hunyuan manifest")
    parameters = dict(manifest.parameters)
    request = _require_mapping(parameters.get("request"), "request")
    companions = _require_mapping(parameters.get("companions"), "companions")
    required_companions = ("llm", "byt5", "glyph", "vision")
    if any(not str(companions.get(name) or "").strip() for name in required_companions):
        raise ValueError("Hunyuan companion model paths are incomplete")
    model_path = str(parameters.get("model_path") or "").strip()
    if not model_path:
        raise ValueError("Hunyuan model_path is required")
    gpu_indices = [str(item).strip() for item in parameters.get("wsl_gpu_indices", [])]
    if not gpu_indices or len(gpu_indices) != len(set(gpu_indices)) or any(
        not item.isdecimal() for item in gpu_indices
    ):
        raise ValueError("wsl_gpu_indices must contain unique nonnegative indices")

    input_root = _local_path(manifest.input_root)
    output_root = _local_path(manifest.output_root)
    cancel_path = _local_path(manifest.cancel_token_path)
    output_root.mkdir(parents=True, exist_ok=True)
    logs = output_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if cancel_path.exists():
        raise RuntimeError("Hunyuan execution was canceled before launch")

    request_payload = dict(request)
    source_image = str(parameters.get("source_image") or "").strip()
    if source_image:
        request_payload["image"] = str(input_root / source_image)
    request_path = output_root / "hunyuan-request.json"
    request_path.write_text(json.dumps(request_payload), encoding="utf-8")
    raw_output = output_root / "raw-output.mp4"
    worker_pid = output_root / "worker.pid"
    timeout = float(parameters.get("timeout_seconds") or 7200)
    python = str(parameters.get("python") or sys.executable)

    attempts = [gpu_indices]
    if len(gpu_indices) > 1:
        attempts.append(gpu_indices[:1])
    for attempt_index, selected_gpus in enumerate(attempts):
        command = [
            python,
            "-m",
            "torch.distributed.run",
            "--standalone",
            "--nproc_per_node",
            str(len(selected_gpus)),
            "-m",
            "edmg_studio_backend.services.hunyuan_video15_worker",
            "--request",
            str(request_path),
            "--model",
            model_path,
            "--llm",
            str(companions["llm"]),
            "--byt5",
            str(companions["byt5"]),
            "--glyph",
            str(companions["glyph"]),
            "--vision",
            str(companions["vision"]),
            "--output",
            str(raw_output),
            "--pid-file",
            str(worker_pid),
        ]
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = ",".join(selected_gpus)
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        result = run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        (logs / "worker.stdout.log").write_text(str(result.stdout or ""), encoding="utf-8")
        (logs / "worker.stderr.log").write_text(str(result.stderr or ""), encoding="utf-8")
        if int(result.returncode) == 0:
            break
        if attempt_index == 0 and _distributed_cuda_failure(result.stderr, len(selected_gpus)):
            (logs / "worker.stdout.log").replace(logs / "worker.distributed.stdout.log")
            (logs / "worker.stderr.log").replace(logs / "worker.distributed.stderr.log")
            continue
        raise RuntimeError(str(result.stderr or result.stdout or "Hunyuan worker failed").strip())
    if not raw_output.is_file() or raw_output.stat().st_size <= 0:
        raise RuntimeError("Hunyuan worker did not produce a non-empty MP4")
    if cancel_path.exists():
        raise RuntimeError("Hunyuan execution was canceled before validation")

    final_relative = "outputs/video.mp4"
    final_output = output_root / final_relative
    final_output.parent.mkdir(parents=True, exist_ok=True)
    source_audio = str(parameters.get("source_audio") or "").strip()
    if source_audio:
        audio_path = input_root / source_audio
        if not audio_path.is_file():
            raise RuntimeError("Manifest source audio is missing")
        _run_checked(
            run,
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_output),
                "-i",
                str(audio_path),
                "-shortest",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                str(final_output),
            ],
            timeout=timeout,
        )
    else:
        shutil.copy2(raw_output, final_output)

    probe = _run_checked(
        run,
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(final_output),
        ],
        timeout=min(timeout, 60),
    )
    probe_payload = json.loads(str(probe.stdout or "{}"))
    stream_types = {
        str(item.get("codec_type"))
        for item in probe_payload.get("streams", [])
        if isinstance(item, dict)
    }
    if "video" not in stream_types or (source_audio and "audio" not in stream_types):
        raise RuntimeError("Hunyuan final MP4 failed required stream validation")

    motion_evidence = parameters.get("motion_evidence")
    motion_validated = isinstance(motion_evidence, dict) and motion_evidence.get("status") == "pass"
    receipts = [
        _write_receipt(
            output_root,
            "receipts/model.json",
            {"model_path": model_path, "worker": "hunyuan_video15", "gpu_indices": gpu_indices},
        ),
        _write_receipt(
            output_root,
            "receipts/motion.json",
            dict(motion_evidence) if isinstance(motion_evidence, dict) else {"status": "unvalidated"},
        ),
        _write_receipt(
            output_root,
            "receipts/segment.json",
            {
                "mode": request_payload.get("mode"),
                "frames": request_payload.get("frames"),
                "fps": request_payload.get("fps"),
                "artifact": final_relative,
            },
        ),
    ]
    if source_audio:
        receipts.append(
            _write_receipt(
                output_root,
                "receipts/source-audio.json",
                {
                    "relative_path": source_audio,
                    "sha256": _sha256(input_root / source_audio),
                },
            )
        )
    receipts.append(
        _write_receipt(
            output_root,
            "receipts/runtime.json",
            {
                "environment": "wsl",
                "physical_gpu_device_ids": manifest.physical_gpu_device_ids,
                "wsl_gpu_indices": gpu_indices,
                "streams": sorted(stream_types),
                "artifact_validated": True,
                "runtime_qualified": bool(motion_validated and "video" in stream_types),
            },
        )
    )
    execution_result = ExecutionResult(
        project_id=manifest.project_id,
        job_id=manifest.job_id,
        attempt=manifest.attempt,
        environment="wsl",
        status="succeeded",
        artifacts=[_artifact(final_output, final_relative, "video/mp4")],
        receipts=receipts,
    )
    result_path = output_root / "execution-result.json"
    result_path.write_text(execution_result.model_dump_json(indent=2), encoding="utf-8")
    return result_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-from-manifest", action="store_true")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    if not args.config_from_manifest:
        parser.error("--config-from-manifest is required")
    run_manifest(Path(args.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
