from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = (
    REPO_ROOT
    / "studio"
    / "nvidia-kit"
    / "extensions"
    / "edmg.ai_director"
    / "edmg"
    / "ai_director"
    / "backend_client.py"
)
SMOKE_SCRIPT = REPO_ROOT / "studio" / "nvidia-kit" / "tools" / "smoke_ai_director_backend.py"
SAMPLE_PLAN = REPO_ROOT / "studio" / "nvidia-kit" / "sample_projects" / "audio_reactive_stage" / "scene_plan.json"


def _load_client_module():
    spec = importlib.util.spec_from_file_location("backend_client", CLIENT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _send_json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/v1/nvidia/status":
            self._send_json({"ok": True, "nvidia": {"enabled": True, "profile": "omniverse"}})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/v1/usd/scene-plan":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self._send_json(
            {
                "ok": True,
                "scene_plan": payload,
                "usd_stage": {
                    "format": "usda",
                    "text": '#usda 1.0\ncustom string edmg:projectId = "sample"\n',
                },
            }
        )


def test_kit_backend_client_reads_status_and_scene_plan():
    module = _load_client_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client = module.EdmgBackendClient(base_url=base_url)

        status = client.nvidia_status()
        usda = client.scene_plan_usda({"project_id": "sample", "scenes": []})

        assert status["nvidia"]["enabled"] is True
        assert usda.startswith("#usda 1.0")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_kit_backend_smoke_script_writes_optional_usda(tmp_path):
    out_path = tmp_path / "from_backend.usda"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SMOKE_SCRIPT),
                "--backend-url",
                f"http://127.0.0.1:{server.server_port}",
                "--scene-plan",
                str(SAMPLE_PLAN),
                "--output-usda",
                str(out_path),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        assert "Smoke complete" in result.stdout
        assert out_path.read_text(encoding="utf-8").startswith("#usda 1.0")
    finally:
        server.shutdown()
        thread.join(timeout=5)
