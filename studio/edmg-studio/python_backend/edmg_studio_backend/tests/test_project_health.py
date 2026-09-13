from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.services.project_health import (
    assess_project_health,
    build_asset_index,
    suggest_relinks,
)
from edmg_studio_backend.store.projects import ProjectStore


def test_asset_index_reports_missing_audio(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Health")
    pdir = store.project_dir(proj.id)
    audio_dir = pdir / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "present.wav").write_bytes(b"RIFF")
    meta = {"audio": {"filename": "missing.wav", "size_bytes": 10}, "timeline": {"layers": []}}
    index = build_asset_index(pdir, meta)
    assert index["missing_count"] >= 1
    assert any(m["path"].endswith("missing.wav") for m in index["missing"])

    health = assess_project_health(pdir, meta)
    assert health["status"] == "error"
    assert health["ok"] is False


def test_asset_index_includes_canonical_pool_and_clip_references(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    candidate = project_dir / "assets" / "media" / "replacement.mov"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"video")
    meta = {
        "timeline": {
            "media_pool": [{
                "id": "media-1",
                "path": "assets/media/replacement.mov",
                "derivatives": {"proxy": {"path": "cache/media/missing.mp4"}},
            }],
            "tracks": [{"clips": [{"media_asset_id": "media-1"}]}],
        },
    }

    index = build_asset_index(project_dir, meta)

    assert index["missing_count"] == 0
    record = next(item for item in index["assets"] if item["path"].endswith("replacement.mov"))
    assert record["asset_id"] == "media-1"
    assert record["referenced"] is True


def test_missing_canonical_original_and_relink_suggestion_include_asset_id(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    candidate = project_dir / "assets" / "alternate" / "clip.wav"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"audio")
    meta = {"timeline": {"media_pool": [{"id": "media-2", "path": "assets/media/clip.wav"}]}}

    index = build_asset_index(project_dir, meta)
    suggestions = suggest_relinks(project_dir, meta)

    assert index["missing"] == [{"path": "assets/media/clip.wav", "reason": "missing", "asset_id": "media-2"}]
    assert suggestions["suggestions"] == [{
        "missing": "assets/media/clip.wav",
        "candidate": "assets/alternate/clip.wav",
        "asset_id": "media-2",
    }]
