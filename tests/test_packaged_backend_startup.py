"""Run against release bytes with EDMG_TEST_PACKAGED_BACKEND pointing to the exe."""

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest


def _packaged_environment(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("EDMG_", "PYTHON", "UV_"))}
    for suffix, folder in (("DATA", "data"), ("MODELS", "models"), ("CACHE", "cache"), ("LOGS", "logs"), ("EXTERNAL", "external")):
        env[f"EDMG_STUDIO_{suffix}_DIR"] = str(tmp_path / folder)
    env["EDMG_STUDIO_HOME"] = str(tmp_path)
    env["EDMG_BACKEND_AUTH_TOKEN"] = "packaged-startup-test-token"
    env["EDMG_AI_PROVIDER"] = "rule_based"
    return env


@pytest.mark.skipif(not os.environ.get("EDMG_TEST_PACKAGED_BACKEND"), reason="requires a built Windows backend")
def test_frozen_backend_starts_without_source_or_python_path(tmp_path):
    executable = Path(os.environ["EDMG_TEST_PACKAGED_BACKEND"]).resolve(strict=True)
    assert (executable.parent / "_internal" / "edmg_studio_backend" / "services" / "engine_package_manifests.json").is_file()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = _packaged_environment(tmp_path)
    with (tmp_path / "startup.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable), "serve", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                        payload = json.load(response)
                    assert payload["ok"] is True
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.5)
            log.flush()
            log.seek(0)
            pytest.fail(f"Frozen backend did not become healthy (exit={process.poll()}):\n{log.read()[-16000:]}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)


@pytest.mark.skipif(not os.environ.get("EDMG_TEST_PACKAGED_BACKEND"), reason="requires a built Windows backend")
def test_frozen_runtime_worker_accepts_protocol_commands(tmp_path):
    executable = Path(os.environ["EDMG_TEST_PACKAGED_BACKEND"]).resolve(strict=True)
    worker_dir = tmp_path / "worker"
    worker_dir.mkdir()
    (worker_dir / "configuration.json").write_text(
        json.dumps({"data_dir": str(tmp_path / "data"), "model_dir": str(tmp_path / "models")}),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [str(executable), "runtime-worker", "--directory", str(worker_dir)],
        cwd=tmp_path,
        env=_packaged_environment(tmp_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps({"sequence": 1, "operation": "diagnose"}) + "\n")
        process.stdin.flush()
        response = worker_dir / "1.json"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and process.poll() is None and not response.is_file():
            time.sleep(0.25)
        assert response.is_file(), f"Frozen runtime worker exited or timed out (exit={process.poll()})"
        payload = json.loads(response.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert "result" in payload
        assert "status" in payload["result"]
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)
