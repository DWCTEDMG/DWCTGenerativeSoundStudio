from __future__ import annotations

import asyncio
import hashlib
import sys
from array import array
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from edmg_studio_backend.services import media_pool as media_pool_module
from edmg_studio_backend.services.media_pool import MediaPoolService, _waveform_peaks
from edmg_studio_backend.store.projects import ProjectStore


def upload(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


def service(tmp_path, *, ffmpeg: str = "definitely-missing-ffmpeg"):
    store = ProjectStore(tmp_path)
    project = store.create("Media project")
    return MediaPoolService(store, ffmpeg, max_upload_bytes=1024), store, project.id


def test_import_uses_canonical_pool_deduplicates_and_preserves_unknown_fields(tmp_path):
    media, store, project_id = service(tmp_path)
    project = store.get(project_id)
    project.meta["unknown_project"] = {"keep": True}
    project.meta["timeline"] = {"unknown_timeline": 7, "media_pool": []}
    store.save(project)

    first = asyncio.run(media.import_media(project_id, upload("../unsafe song.WAV", b"first", "audio/wav")))
    duplicate = asyncio.run(media.import_media(project_id, upload("copy.wav", b"first", "audio/wav")))
    asset = first["asset"]

    assert duplicate["deduplicated"] is True
    assert duplicate["asset"]["id"] == asset["id"]
    assert asset["path"].startswith("assets/media/")
    assert ".." not in asset["path"]
    assert asset["sha256"] == hashlib.sha256(b"first").hexdigest()
    saved = store.get(project_id)
    assert saved.meta["unknown_project"] == {"keep": True}
    assert saved.meta["timeline"]["unknown_timeline"] == 7
    assert len(saved.meta["timeline"]["media_pool"]) == 1


def test_relink_preserves_stable_id_unknown_fields_and_validates_path(tmp_path):
    media, store, project_id = service(tmp_path)
    imported = asyncio.run(media.import_media(project_id, upload("source.wav", b"original", "audio/wav")))
    asset_id = imported["asset"]["id"]
    project = store.get(project_id)
    stored = project.meta["timeline"]["media_pool"][0]
    stored["plugin_data"] = {"keep": "yes"}
    stored["derivatives"] = {"waveform": {"path": "cache/media/stale.json"}}
    store.save(project)
    candidate = store.project_dir(project_id) / "assets" / "media" / "replacement.wav"
    candidate.write_bytes(b"replacement")

    result = media.relink(project_id, asset_id, "assets/media/replacement.wav")

    assert result["asset"]["id"] == asset_id
    assert result["asset"]["plugin_data"] == {"keep": "yes"}
    assert result["asset"]["derivatives"] == {}
    assert result["asset"]["sha256"] == hashlib.sha256(b"replacement").hexdigest()
    with pytest.raises(HTTPException) as unsafe:
        media.relink(project_id, asset_id, "../outside.wav")
    assert unsafe.value.status_code == 400


def test_relink_upload_manages_replacement_and_preserves_stable_id(tmp_path):
    media, store, project_id = service(tmp_path)
    imported = asyncio.run(media.import_media(project_id, upload("source.wav", b"original", "audio/wav")))
    asset_id = imported["asset"]["id"]
    previous_path = store.project_dir(project_id) / imported["asset"]["path"]

    result = asyncio.run(media.relink_upload(
        project_id,
        asset_id,
        upload("replacement.wav", b"replacement", "audio/wav"),
    ))

    assert result["asset"]["id"] == asset_id
    assert result["asset"]["path"].startswith("assets/media/")
    assert result["asset"]["sha256"] == hashlib.sha256(b"replacement").hexdigest()
    assert (store.project_dir(project_id) / result["asset"]["path"]).read_bytes() == b"replacement"
    assert not previous_path.exists()


def test_relink_upload_replaces_missing_managed_source(tmp_path):
    media, store, project_id = service(tmp_path)
    imported = asyncio.run(media.import_media(project_id, upload("source.wav", b"original", "audio/wav")))
    asset_id = imported["asset"]["id"]
    (store.project_dir(project_id) / imported["asset"]["path"]).unlink()

    result = asyncio.run(media.relink_upload(
        project_id,
        asset_id,
        upload("replacement.wav", b"replacement", "audio/wav"),
    ))

    replacement = store.project_dir(project_id) / result["asset"]["path"]
    assert result["ok"] is True
    assert result["asset"]["id"] == asset_id
    assert replacement.read_bytes() == b"replacement"


def test_thumbnail_generation_is_deterministic_and_cache_hit(tmp_path, monkeypatch):
    media, _, project_id = service(tmp_path, ffmpeg="ffmpeg")
    imported = asyncio.run(media.import_media(project_id, upload("clip.mp4", b"video", "video/mp4")))
    calls = []

    monkeypatch.setattr(media_pool_module, "ensure_ffmpeg", lambda _: "ffmpeg")

    def fake_run(command, timeout):
        calls.append((command, timeout))
        BytesIO()
        output = command[-1]
        from pathlib import Path
        Path(output).write_bytes(b"jpeg")

    monkeypatch.setattr(media, "_run", fake_run)
    first = media.thumbnail(project_id, imported["asset"]["id"], 320)
    second = media.thumbnail(project_id, imported["asset"]["id"], 320)

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["derivative"]["cache_key"] == second["derivative"]["cache_key"]
    assert len(calls) == 1
    assert first["derivative"]["path"].startswith(f"cache/media/{imported['asset']['sha256']}/")


def test_requested_probe_and_generation_surface_tool_errors(tmp_path):
    media, _, project_id = service(tmp_path)
    imported = asyncio.run(media.import_media(project_id, upload("clip.mp4", b"video", "video/mp4")))
    with pytest.raises(HTTPException) as probe_error:
        media.probe(project_id, imported["asset"]["id"])
    assert probe_error.value.status_code == 503
    with pytest.raises(HTTPException) as generation_error:
        media.thumbnail(project_id, imported["asset"]["id"], 320)
    assert generation_error.value.status_code == 503


def test_rejects_unsupported_and_oversized_uploads(tmp_path):
    media, _, project_id = service(tmp_path)
    with pytest.raises(HTTPException) as unsupported:
        asyncio.run(media.import_media(project_id, upload("notes.txt", b"text", "text/plain")))
    assert unsupported.value.status_code == 415

    media.max_upload_bytes = 3
    with pytest.raises(HTTPException) as oversized:
        asyncio.run(media.import_media(project_id, upload("song.wav", b"four", "audio/wav")))
    assert oversized.value.status_code == 413


@pytest.mark.parametrize(("sample_count", "bins"), [(65, 64), (4097, 4096)])
def test_waveform_peak_partition_preserves_requested_resolution(tmp_path, sample_count, bins):
    samples = array("h", range(sample_count))
    if sys.byteorder != "little":
        samples.byteswap()
    pcm = tmp_path / "samples.pcm"
    pcm.write_bytes(samples.tobytes())

    peaks = _waveform_peaks(pcm, sample_count, bins)

    assert len(peaks) == bins
