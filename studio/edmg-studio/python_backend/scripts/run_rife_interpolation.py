from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _studio_root() -> Path:
    configured = os.getenv("EDMG_STUDIO_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _tool_root() -> Path:
    configured = os.getenv("EDMG_RIFE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (_studio_root() / "python_backend" / "data" / "tools" / "Practical-RIFE").resolve()


def _ffmpeg_path() -> Path:
    configured = os.getenv("EDMG_FFMPEG_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file():
            return candidate
    bundled = _studio_root() / "electron-resources" / "bin" / "ffmpeg.exe"
    if bundled.is_file():
        return bundled.resolve()
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("FFmpeg is unavailable; set EDMG_FFMPEG_PATH")
    return Path(found).resolve()


def _ffprobe_path(ffmpeg: Path) -> Path:
    configured = os.getenv("EDMG_FFPROBE_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file():
            return candidate
    sibling = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
    if sibling.is_file():
        return sibling
    found = shutil.which("ffprobe")
    if not found:
        raise RuntimeError("FFprobe is unavailable; set EDMG_FFPROBE_PATH")
    return Path(found).resolve()


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    process = subprocess.run(command, cwd=cwd, env=env, text=True)
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {command[0]}")


def _probe_video(ffprobe: Path, path: Path) -> dict[str, object]:
    process = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"FFprobe rejected the interpolated output: {process.stderr.strip()[:1000]}")
    payload = json.loads(process.stdout or "{}")
    if not payload.get("streams"):
        raise RuntimeError("Interpolated output contains no video stream")
    return payload


def _probe() -> int:
    root = _tool_root()
    model = root / "train_log" / "flownet.pkl"
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        devices = [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]
    except Exception as exc:  # pragma: no cover - diagnostic path
        cuda_available = False
        devices = []
        torch_error = str(exc)
    else:
        torch_error = None
    result = {
        "ok": cuda_available and model.is_file() and (_ffmpeg_path().is_file()),
        "provider": "rife_cuda",
        "runtime": str(root),
        "model": str(model),
        "model_present": model.is_file(),
        "cuda_available": cuda_available,
        "cuda_devices": devices,
        "selected_device": os.getenv("EDMG_INTERPOLATION_CUDA_DEVICE", "2"),
        "nvenc": "h264_nvenc",
        "torch_error": torch_error,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="EDMG CUDA RIFE interpolation with NVENC output")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        return _probe()
    if args.input is None or args.output is None or args.fps is None:
        parser.error("--input, --output, and --fps are required unless --probe is used")
    if args.fps <= 0:
        parser.error("--fps must be positive")

    source = args.input.expanduser().resolve(strict=True)
    destination = args.output.expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = _tool_root()
    inference = root / "inference_video.py"
    model = root / "train_log" / "flownet.pkl"
    if not inference.is_file() or not model.is_file():
        raise RuntimeError(f"RIFE runtime is incomplete at {root}")

    ffmpeg = _ffmpeg_path()
    ffprobe = _ffprobe_path(ffmpeg)
    device = os.getenv("EDMG_INTERPOLATION_CUDA_DEVICE", "2").strip() or "2"
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = device
    environment.setdefault("PYTHONUTF8", "1")
    compatibility_entry = Path(__file__).with_name("rife_compat_entry.py").resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="edmg-rife-", dir=destination.parent) as temp_dir:
        stage = Path(temp_dir) / "rife-stage.mp4"
        encoded = Path(temp_dir) / "nvenc-stage.mp4"
        _run(
            [
                sys.executable,
                str(compatibility_entry),
                str(inference),
                "--video",
                str(source),
                "--output",
                str(stage),
                "--fps",
                str(args.fps),
                "--model",
                str(root / "train_log"),
                "--fp16",
            ],
            cwd=root,
            env=environment,
        )
        _probe_video(ffprobe, stage)
        _run(
            [
                str(ffmpeg),
                "-y",
                "-i",
                str(stage),
                "-an",
                "-c:v",
                "h264_nvenc",
                "-gpu",
                device,
                "-preset",
                "p5",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                "18",
                "-b:v",
                "0",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(encoded),
            ]
        )
        result = _probe_video(ffprobe, encoded)
        os.replace(encoded, destination)
        print(
            json.dumps(
                {
                    "ok": True,
                    "provider": "rife_cuda",
                    "cuda_device": device,
                    "encoder": "h264_nvenc",
                    "output": str(destination),
                    "probe": result,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
