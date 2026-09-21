from __future__ import annotations

import json
import atexit
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class RuntimeCanceled(RuntimeError):
    pass


class RuntimeProcess:
    """A persistent child per component/profile; native failures cannot poison CUDA in the renderer."""
    def __init__(self, data_dir: Path, package_path: str = "", *, cancel_check=None, progress=None):
        self.cancel_check = cancel_check
        self.data_dir = data_dir
        self.progress = progress
        self.sequence = 0
        work = data_dir / "tensorrt" / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="worker-", dir=work)
        self.root = Path(self.temporary.name)
        (self.root / "configuration.json").write_text(json.dumps({"data_dir": str(data_dir), "package_path": package_path}))
        logs = data_dir / "tensorrt" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"{self.root.name}.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[2]), env.get("PYTHONPATH", "")]))
        command = [sys.executable, "-m", "edmg_studio_backend.runtime.worker", str(self.root)]
        if getattr(sys, "frozen", False):
            command = [sys.executable, "runtime-worker", "--directory", str(self.root)]
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log,
                text=True, encoding="utf-8", env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self.log.close()
            self.temporary.cleanup()
            raise
        atexit.register(self.close)

    def request(self, operation: str, *, timeout_s=180, array=None, **payload):
        import numpy as np
        self.sequence += 1
        sequence = self.sequence
        if array is not None:
            np.save(self.root / f"{sequence}-input.npy", array, allow_pickle=False)
        try:
            self.process.stdin.write(json.dumps({"operation": operation, "sequence": sequence, **payload}) + "\n")
            self.process.stdin.flush()
            response = self.root / f"{sequence}.json"
            deadline = time.monotonic() + timeout_s
            previous_stage = ""
            while not response.exists():
                if self.cancel_check and self.cancel_check():
                    raise RuntimeCanceled("Runtime operation canceled")
                if self.process.poll() is not None:
                    raise RuntimeError(f"TensorRT worker exited ({self.process.returncode}); log: {self.log_path.name}")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"TensorRT {operation} timed out")
                if self.progress:
                    try:
                        stage = json.loads((self.root / "progress.json").read_text())["stage"]
                        if stage != previous_stage:
                            self.progress(stage)
                            previous_stage = stage
                    except (OSError, ValueError, KeyError):
                        pass
                time.sleep(0.001 if operation == "execute" else 0.05)
            document = json.loads(response.read_text())
            if not document["ok"]:
                raise RuntimeError(document["error"])
            result = document["result"]
            output = self.root / f"{sequence}-output.npy"
            if output.exists():
                result["output"] = np.load(output, allow_pickle=False)
            return result
        except BaseException as exc:
            if operation == "prepare" and not isinstance(exc, (RuntimeCanceled, KeyboardInterrupt, SystemExit)):
                try:
                    progress = json.loads((self.root / "progress.json").read_text())
                    if progress.get("engine_id"):
                        from .cache import EngineCache
                        EngineCache(self.data_dir).quarantine(progress["engine_id"], str(exc))
                except (OSError, ValueError):
                    pass
            self.close()
            raise
        finally:
            for suffix in (".json", "-input.npy", "-output.npy"):
                (self.root / f"{sequence}{suffix}").unlink(missing_ok=True)

    def close(self):
        atexit.unregister(self.close)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        self.log.close()
        self.temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
