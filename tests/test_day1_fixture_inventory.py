from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from edmg_studio_backend.contracts import adapt_legacy_project

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "day1"
MANIFEST_PATH = FIXTURE_ROOT / "goldens" / "manifest.json"


def test_day1_fixture_generator_is_reproducible() -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_day1_fixtures.py"), "--check"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_day1_manifest_hashes_every_small_payload() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "1.0"
    assert manifest["license"] == "CC0-1.0"
    assert {entry["path"] for entry in manifest["files"]} == {
        "audio/tiny_pulse.wav",
        "media/reference_frame.svg",
        "project/project.json",
    }
    for entry in manifest["files"]:
        path = FIXTURE_ROOT / entry["path"]
        payload = path.read_bytes()
        assert len(payload) == entry["size_bytes"]
        assert len(payload) < 64 * 1024
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert not path.is_symlink()


def test_tiny_audio_golden_properties() -> None:
    with wave.open(str(FIXTURE_ROOT / "audio" / "tiny_pulse.wav"), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8_000
        assert wav.getnframes() == 8_000
        assert wav.getnframes() / wav.getframerate() == 1.0


def test_reference_media_is_standalone_64px_svg() -> None:
    root = ET.parse(FIXTURE_ROOT / "media" / "reference_frame.svg").getroot()

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["width"] == "64"
    assert root.attrib["height"] == "64"
    assert not any("href" in key for element in root.iter() for key in element.attrib)


def test_legacy_project_fixture_adapts_without_losing_metadata() -> None:
    payload = json.loads((FIXTURE_ROOT / "project" / "project.json").read_text(encoding="utf-8"))
    project = adapt_legacy_project(payload)

    assert project.contract_type == "edmg.project"
    assert project.schema_version == "1.0"
    assert project.id == "day1-fixture-project"
    assert project.audio and project.audio.relative_path == "assets/audio/tiny_pulse.wav"
    assert project.timeline["fps"] == 30
    assert project.metadata["reference_media"][0]["id"] == "reference-frame"
