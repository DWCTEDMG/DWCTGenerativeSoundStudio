from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.store.artifacts import build_artifact_manifest, write_artifact_manifest


def test_write_artifact_manifest_next_to_output(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    out_dir = project_dir / "outputs" / "videos"
    out_dir.mkdir(parents=True)
    video = out_dir / "clip.mp4"
    video.write_bytes(b"fake-mp4-bytes")

    manifest_path = write_artifact_manifest(
        video,
        project_dir=project_dir,
        project_id="abc",
        engine="internal_video",
        model_id="sd15",
        seed=42,
        params={"fps": 24},
        source_assets=[{"role": "audio", "path": "assets/audio/a.wav"}],
        parents=["clip.render.json"],
    )
    assert manifest_path.exists()
    assert manifest_path.name == "clip.mp4.artifact.json"
    payload = build_artifact_manifest(
        artifact_path=video,
        project_dir=project_dir,
        project_id="abc",
        engine="internal_video",
    )
    assert payload["schema_version"] == 1
    assert payload["path"] == "outputs/videos/clip.mp4"
    assert payload["content_hash"]
    assert payload["bytes"] == len(b"fake-mp4-bytes")
