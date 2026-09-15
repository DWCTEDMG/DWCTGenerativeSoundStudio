from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from edmg_studio_backend.services.support_bundle import (
    BundleLimits,
    DiagnosticRoot,
    build_support_bundle,
)


def _read_bundle(payload: bytes) -> tuple[set[str], dict[str, str], dict]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        content = {
            name: archive.read(name).decode("utf-8")
            for name in names
            if name != "manifest.json"
        }
        manifest = json.loads(archive.read("manifest.json"))
    return names, content, manifest


def test_bundle_redacts_structured_secrets_paths_and_bearer_tokens(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "state.json").write_text(
        json.dumps(
            {
                "api_key": "top-secret",
                "nested": {"password": "hunter2"},
                "message": "read C:\\Users\\artist\\private\\take.wav",
            }
        ),
        encoding="utf-8",
    )
    (logs / "backend.log").write_text(
        "Authorization: Bearer abc.def-123\ncache=/home/artist/private/cache.bin\n",
        encoding="utf-8",
    )

    names, content, manifest = _read_bundle(
        build_support_bundle([DiagnosticRoot("logs", logs)])
    )

    assert names == {"logs/state.json", "logs/backend.log", "manifest.json"}
    combined = "\n".join(content.values())
    assert "top-secret" not in combined
    assert "hunter2" not in combined
    assert "abc.def-123" not in combined
    assert "C:\\Users\\artist" not in combined
    assert "/home/artist" not in combined
    assert "[REDACTED]" in combined
    assert "[LOCAL_PATH]" in combined
    assert manifest["schema_version"] == 1


def test_bundle_excludes_private_media_unknown_types_and_oversized_files(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "voice.wav").write_bytes(b"private audio")
    (logs / "frame.png").write_bytes(b"private image")
    (logs / "dump.bin").write_bytes(b"binary")
    (logs / "large.log").write_text("x" * 20, encoding="utf-8")
    (logs / "safe.log").write_text("ok", encoding="utf-8")

    names, _, manifest = _read_bundle(
        build_support_bundle(
            [DiagnosticRoot("logs", logs)],
            limits=BundleLimits(max_files=5, max_file_bytes=10, max_total_bytes=100),
        )
    )

    assert names == {"logs/safe.log", "manifest.json"}
    omitted = {item["path"]: item["reason"] for item in manifest["omitted"]}
    assert omitted["logs/voice.wav"] == "private_media"
    assert omitted["logs/frame.png"] == "private_media"
    assert omitted["logs/dump.bin"] == "file_type"
    assert omitted["logs/large.log"] == "file_size"


def test_bundle_rejects_symlinks(tmp_path: Path):
    logs = tmp_path / "logs"
    outside = tmp_path / "outside.log"
    logs.mkdir()
    outside.write_text("token=must-not-escape", encoding="utf-8")
    link = logs / "linked.log"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    names, content, manifest = _read_bundle(
        build_support_bundle([DiagnosticRoot("logs", logs)])
    )

    assert names == {"manifest.json"}
    assert not content
    assert {item["reason"] for item in manifest["omitted"]} == {"symlink"}
