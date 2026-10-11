"""Bounded Linux video worker. Run through SSH or WSL; no public listener."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import zipfile


def render(request: Path) -> None:
    from PIL import Image
    from ..services.internal_video_models import generate_video_model_frames
    parameters = json.loads(request.read_text(encoding="utf-8"))
    parameters.pop("timeout_seconds")
    source = parameters.pop("init_image")
    image = Image.open(source).convert("RGB") if source else None
    for key in ("video_model_dir", "base_model_dir", "workspace"):
        parameters[key] = Path(parameters[key])
    frames = generate_video_model_frames(**parameters, init_image=image)
    if len(frames) != parameters["num_frames"]:
        raise RuntimeError("Worker produced an unexpected frame count")
    root = request.parent
    receipt = {"schema_version": 1, "engine": parameters["engine"], "frames": len(frames),
               "width": parameters["width"], "height": parameters["height"],
               "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest()}
    with zipfile.ZipFile(root / "result.tmp", "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("receipt.json", json.dumps(receipt))
        for index, frame in enumerate(frames):
            if frame.size != (parameters["width"], parameters["height"]):
                raise RuntimeError("Worker produced an unexpected frame size")
            import io
            output = io.BytesIO()
            frame.save(output, format="PNG")
            bundle.writestr(f"frames/{index:06d}.png", output.getvalue())
    (root / "result.tmp").replace(root / "result.zip")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--probe", action="store_true")
    actions.add_argument("--request", type=Path)
    actions.add_argument("--cancel", type=Path)
    actions.add_argument("--render", type=Path)
    parser.add_argument("--models-root", type=Path)
    parser.add_argument("--video-model", type=Path)
    parser.add_argument("--base-model", type=Path)
    args = parser.parse_args()
    # The worker never dispatches recursively, including when launcher defaults
    # happen to contain a coordinator configuration path.
    os.environ.pop("EDMG_HYBRID_CONFIG_PATH", None)
    if args.probe:
        import torch
        print(json.dumps({"cuda": torch.cuda.is_available(), "devices": torch.cuda.device_count(),
                          "protocol_version": 1, "worker_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                          "models_present": bool(args.models_root and args.models_root.is_dir()),
                          "requested_models_present": all(p.is_dir() for p in (args.video_model, args.base_model) if p is not None)}))
        return
    if args.render:
        render(args.render)
        return
    if args.cancel:
        (args.cancel.parent / "cancel.requested").touch()
        return
    request = args.request.resolve(strict=True)
    parameters = json.loads(request.read_text(encoding="utf-8"))
    timeout = int(parameters["timeout_seconds"])
    if not 30 <= timeout <= 86400:
        raise ValueError("Invalid worker timeout")
    # A single node lease prevents separate coordinator attempts from competing
    # for all GPU memory. It also fails cleanly rather than waiting indefinitely.
    import fcntl
    with (request.parent.parent / "node.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def interrupted(signum, frame):
            raise KeyboardInterrupt("Worker connection closed or process stopped")
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        child = subprocess.Popen([sys.executable, "-m", "edmg_studio_backend.execution.video_worker", "--render", str(request)],
                                 start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if (request.parent / "cancel.requested").exists():
                    raise RuntimeError("Video worker canceled")
                if time.monotonic() > deadline:
                    raise TimeoutError("Video worker timeout")
                time.sleep(0.5)
            if child.returncode:
                raise RuntimeError("Video generation process failed")
        finally:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)


if __name__ == "__main__":
    main()
