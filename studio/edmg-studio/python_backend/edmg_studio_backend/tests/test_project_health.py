from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.services.project_health import assess_project_health, build_asset_index
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
