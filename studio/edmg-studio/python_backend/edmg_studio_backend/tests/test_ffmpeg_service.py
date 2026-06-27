from __future__ import annotations

import subprocess
from pathlib import Path

from edmg_studio_backend.services import ffmpeg as ffmpeg_service


def test_interpolate_minuterpolate_does_not_require_ffprobe(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    in_mp4 = tmp_path / "in.mp4"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    in_mp4.write_bytes(b"input")

    monkeypatch.delenv("EDMG_FFPROBE_PATH", raising=False)
    monkeypatch.setattr(ffmpeg_service.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ffmpeg_service, "ffmpeg_has_filter", lambda _ffmpeg_path, _filter_name: True)

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, timeout=None, shell=False):
        calls.append([str(part) for part in (cmd if isinstance(cmd, list) else [cmd])])
        assert cmd[0] == str(ffmpeg)
        out_mp4.write_bytes(b"output")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.interpolate_video_fps(
        ffmpeg_path=str(ffmpeg),
        in_mp4=in_mp4,
        out_mp4=out_mp4,
        fps_out=24,
        engine="minterpolate",
    )

    assert out_mp4.exists()
    assert len(calls) == 1
    assert any("minterpolate=fps=24" in part for part in calls[0])


def test_ensure_ffprobe_uses_explicit_env_path(tmp_path, monkeypatch) -> None:
    ffprobe = tmp_path / "ffprobe.exe"
    ffprobe.write_bytes(b"exe")
    monkeypatch.setenv("EDMG_FFPROBE_PATH", str(ffprobe))

    assert ffmpeg_service.ensure_ffprobe("missing-ffmpeg") == str(ffprobe)
