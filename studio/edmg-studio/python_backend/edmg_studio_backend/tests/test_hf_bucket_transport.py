from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import edmg_studio_backend as backend_package
from edmg_studio_backend.integrations import hf_bucket


def test_json_helper_receives_token_only_in_environment(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        request = json.loads(kwargs["input"])
        assert "token" not in request
        response = {
            "contract_version": 1,
            "ok": True,
            "result": {
                "entries": [
                    {"type": "file", "path": "weights/model.safetensors", "size": 7}
                ]
            },
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(hf_bucket.subprocess, "run", fake_run)
    command = hf_bucket._TransportCommand(
        ("C:/Program Files/EDMG/edmg-hf-bucket-helper.exe",),
        "json-helper",
        "test",
    )
    transport = hf_bucket._BucketTransport(token="hf_secret_token", command=command)

    entries = transport.list_entries("team/models", prefix="weights", recursive=True)

    assert entries[0]["path"] == "weights/model.safetensors"
    assert calls[0]["argv"] == ["C:/Program Files/EDMG/edmg-hf-bucket-helper.exe"]
    assert "hf_secret_token" not in calls[0]["input"]
    assert calls[0]["env"]["HF_TOKEN"] == "hf_secret_token"
    if os.name == "nt":
        assert calls[0]["creationflags"] == hf_bucket.subprocess.CREATE_NO_WINDOW


def test_explicit_missing_helper_is_a_clear_capability_failure(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing-helper.exe"
    monkeypatch.setenv("EDMG_HF_BUCKET_HELPER", str(missing))

    with pytest.raises(hf_bucket.HFBucketCapabilityError, match="does not point to a file"):
        hf_bucket._resolve_transport_command()


def test_helper_sync_excludes_cache_and_partial_artifacts(monkeypatch) -> None:
    captured_request: dict = {}

    def fake_run(_argv, **kwargs):
        captured_request.update(json.loads(kwargs["input"]))
        response = {
            "contract_version": 1,
            "ok": True,
            "result": {"source": "C:/models", "dest": "hf://buckets/team/models"},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(hf_bucket.subprocess, "run", fake_run)
    command = hf_bucket._TransportCommand(("helper.exe",), "json-helper", "test")
    transport = hf_bucket._BucketTransport(command=command)

    transport.sync(
        "team/models",
        source="C:/models",
        dest="hf://buckets/team/models",
        exclude=hf_bucket._BUCKET_SYNC_EXCLUDES,
    )

    assert "**/.cache/**" in captured_request["exclude"]
    assert "**/*.incomplete" in captured_request["exclude"]
    assert "**/*.tmp" in captured_request["exclude"]


def test_directory_listing_failure_is_not_swallowed(tmp_path) -> None:
    settings = hf_bucket.HFBucketCacheSettings(
        bucket="team/models",
        models_dir=tmp_path,
    )
    cache = object.__new__(hf_bucket.HFBucketModelCache)
    cache.settings = settings
    cache._token = None

    class FailingTransport:
        def list_entries(self, *_args, **_kwargs):
            raise hf_bucket.HFBucketOperationError("bucket helper failed")

    cache._transport = FailingTransport()

    with pytest.raises(hf_bucket.HFBucketOperationError, match="bucket helper failed"):
        cache.model_directory_exists({"id": "demo"}, Path(tmp_path / "internal" / "demo"))


def test_frozen_runtime_searches_executable_sibling_for_launcher_defaults(
    tmp_path, monkeypatch
) -> None:
    executable = tmp_path / "edmg-studio-backend.exe"
    executable.write_bytes(b"launcher")
    internal = tmp_path / "_internal"
    internal.mkdir()
    monkeypatch.setattr(backend_package.sys, "frozen", True, raising=False)
    monkeypatch.setattr(backend_package.sys, "executable", str(executable))
    monkeypatch.setattr(backend_package.sys, "_MEIPASS", str(internal), raising=False)

    candidates = backend_package._launcher_env_candidates()

    packaged_local = tmp_path / "launcher_env.json"
    packaged_defaults = tmp_path / "launcher_env.defaults.json"
    assert packaged_local in candidates
    assert packaged_defaults in candidates
    assert candidates.index(packaged_local) < candidates.index(packaged_defaults)
