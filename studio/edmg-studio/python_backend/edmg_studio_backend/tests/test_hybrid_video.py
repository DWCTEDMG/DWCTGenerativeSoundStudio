from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from PIL import Image
from pydantic import ValidationError

from edmg_studio_backend.execution import hybrid


def configured():
    return hybrid.HybridVideoSettings(
        remote=hybrid.LinuxVideoNode(enabled=True, host="100.1.2.3", identity_file="/keys/key",
            python="/venv/bin/python", backend_root="/backend", models_root="/models"),
        wsl_backup=hybrid.LinuxVideoNode(enabled=True, python="/wsl/python",
            backend_root="/backend", models_root="/models"))


def test_remote_commands_require_host_trust_and_quote_paths():
    config = configured().remote.model_copy(update={"backend_root": "/backend with spaces"})
    command = hybrid.LinuxVideoTransport(config).worker_command("--probe")
    assert "StrictHostKeyChecking=yes" in command
    assert "BatchMode=yes" in command
    assert f"UserKnownHostsFile={Path('/keys/key').parent / 'known_hosts'}" in command
    assert "'PYTHONPATH=/backend with spaces'" in command[-1]


@pytest.mark.parametrize("field,value", [("host", "-oProxyCommand=bad"), ("user", "root;bad"),
    ("python", "relative/python"), ("models_root", "/models/../etc")])
def test_rejects_unsafe_worker_configuration(field, value):
    with pytest.raises(ValidationError):
        hybrid.LinuxVideoNode(**{field: value})


def test_disabled_routing_keeps_local_path(monkeypatch):
    monkeypatch.setattr(hybrid, "load_settings", lambda: hybrid.HybridVideoSettings())
    assert hybrid.try_generate({"engine": "svd"}) is None


def test_explicit_job_environment_keeps_local_path(monkeypatch):
    monkeypatch.setattr(hybrid, "load_settings", configured)
    monkeypatch.setenv("EDMG_HYBRID_DISABLED_FOR_JOB", "1")
    assert hybrid.try_generate({"engine": "svd"}) is None


def test_prelaunch_failure_tries_wsl_then_local(monkeypatch):
    monkeypatch.setattr(hybrid, "load_settings", configured)
    visited = []
    def probe(self, *_):
        visited.append(self.wsl)
        raise RuntimeError("unreachable")
    monkeypatch.setattr(hybrid.LinuxVideoTransport, "probe", probe)
    assert hybrid.try_generate({"engine": "svd"}) is None
    assert visited == [False, True]


def test_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setattr(hybrid, "load_settings", lambda: configured().model_copy(update={"allow_local_fallback": False}))
    monkeypatch.setattr(hybrid.LinuxVideoTransport, "probe", lambda self, *_: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError, match="No configured Linux"):
        hybrid.try_generate({"engine": "svd"})


def archive(tmp_path, *, digest="a" * 64, extra=None):
    path = tmp_path / "frames.zip"
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format="PNG")
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("receipt.json", json.dumps({"frames": 1, "width": 16, "height": 16, "request_sha256": digest}))
        bundle.writestr("frames/000000.png", output.getvalue())
        if extra:
            bundle.writestr(extra, b"bad")
    return path


def test_validated_frames_return_to_coordinator(tmp_path):
    frames, receipt = hybrid.read_frames(archive(tmp_path), expected_frames=1, width=16, height=16, request_sha256="a" * 64)
    assert frames[0].getpixel((0, 0)) == (255, 0, 0)
    assert receipt["frames"] == 1


def test_obsolete_request_cannot_publish_frames(tmp_path):
    with pytest.raises(RuntimeError, match="receipt"):
        hybrid.read_frames(archive(tmp_path, digest="b" * 64), expected_frames=1, width=16, height=16, request_sha256="a" * 64)


def test_unexpected_archive_paths_are_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="inventory"):
        hybrid.read_frames(archive(tmp_path, extra="../escape"), expected_frames=1, width=16, height=16, request_sha256="a" * 64)


def test_configuration_roundtrips_through_native_api(tmp_path):
    from edmg_studio_backend.tests.test_execution_api import _client
    client, _ = _client(tmp_path)
    payload = configured().model_dump(mode="json")
    response = client.put("/v1/execution/hybrid", json=payload)
    assert response.status_code == 200
    assert client.get("/v1/execution/hybrid").json() == payload


def test_enabled_incomplete_node_cannot_be_saved(tmp_path):
    from edmg_studio_backend.tests.test_execution_api import _client
    client, _ = _client(tmp_path)
    response = client.put("/v1/execution/hybrid", json={"remote": {"enabled": True}})
    assert response.status_code == 422


def test_internal_video_pipeline_uses_hybrid_frames_before_local_weights(tmp_path, monkeypatch):
    from edmg_studio_backend.services import internal_video_models
    frames = [Image.new("RGB", (16, 16), "blue")]
    monkeypatch.setenv("EDMG_HYBRID_CONFIG_PATH", str(tmp_path / "configuration.json"))
    calls = []
    def remote(parameters):
        calls.append(parameters)
        return frames
    monkeypatch.setattr(hybrid, "try_generate", remote)
    result = internal_video_models.generate_video_model_frames(engine="svd",
        video_model_dir=tmp_path / "not-installed", base_model_dir=tmp_path / "base",
        init_image=frames[0], prompt="test", negative_prompt="", width=16, height=16,
        num_frames=1, fps=24, steps=2, cfg=1.0, seed=1, device="cuda", workspace=tmp_path)
    assert result is frames
    assert calls[0]["seed"] == 1


def test_linux_worker_receipt_binds_exact_request(tmp_path, monkeypatch):
    from edmg_studio_backend.execution.video_worker import render
    from edmg_studio_backend.services import internal_video_models
    monkeypatch.setattr(internal_video_models, "generate_video_model_frames",
        lambda **_: [Image.new("RGB", (16, 16), "green")])
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"engine": "svd", "video_model_dir": str(tmp_path),
        "base_model_dir": str(tmp_path), "workspace": str(tmp_path), "init_image": None,
        "width": 16, "height": 16, "num_frames": 1, "timeout_seconds": 30}))
    render(request)
    frames, receipt = hybrid.read_frames(tmp_path / "result.zip", expected_frames=1,
        width=16, height=16, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert len(frames) == 1
    assert receipt["engine"] == "svd"


def test_running_attempt_cancellation_does_not_launch_backup(tmp_path, monkeypatch):
    from edmg_studio_backend import config
    monkeypatch.setattr(config, "Settings", lambda: SimpleNamespace(models_dir=tmp_path))
    monkeypatch.setattr(hybrid, "load_settings", configured)
    probes, commands, stopped = [], [], []
    monkeypatch.setattr(hybrid.LinuxVideoTransport, "probe", lambda self, *_: probes.append(self.wsl) or {})
    monkeypatch.setattr(hybrid.LinuxVideoTransport, "copy", lambda *a, **k: None)
    monkeypatch.setattr(hybrid.subprocess, "run", lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0))
    process = SimpleNamespace(poll=lambda: None, kill=lambda: stopped.append("kill"), wait=lambda **_: stopped.append("wait"))
    monkeypatch.setattr(hybrid.subprocess, "Popen", lambda *a, **k: process)
    checks = []
    def cancel():
        checks.append(True)
        if len(checks) > 1:
            raise RuntimeError("test cancellation")
    with pytest.raises(RuntimeError, match="test cancellation"):
        hybrid.try_generate({"engine": "svd", "video_model_dir": tmp_path / "video", "base_model_dir": tmp_path / "base",
            "workspace": tmp_path, "init_image": None, "cancel_check": cancel})
    assert probes == [False]
    assert stopped == ["kill", "wait"]
    assert any("--cancel" in command[-1] for command in commands)
