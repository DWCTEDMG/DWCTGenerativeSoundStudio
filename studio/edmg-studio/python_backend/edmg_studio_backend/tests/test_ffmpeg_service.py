from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


def test_image_sequence_uses_escaped_temporary_concat_manifest(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    frames_dir = tmp_path / "frames'quoted"
    frame = frames_dir / "frame_000001.png"
    out_mp4 = tmp_path / "output.mp4"
    ffmpeg.write_bytes(b"exe")
    frames_dir.mkdir()
    frame.write_bytes(b"frame")

    observed_manifest: Path | None = None

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        nonlocal observed_manifest
        assert shell is False
        observed_manifest = Path(cmd[cmd.index("-i") + 1])
        manifest = observed_manifest.read_text(encoding="utf-8")
        assert manifest.startswith("ffconcat version 1.0\n")
        assert "frames'\\''quoted" in manifest
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.assemble_image_sequence(
        ffmpeg_path=str(ffmpeg),
        frames_dir=frames_dir,
        out_mp4=out_mp4,
        fps=24,
    )

    assert observed_manifest is not None
    assert not observed_manifest.exists()


def test_rife_template_is_expanded_as_argv_without_a_shell(tmp_path, monkeypatch) -> None:
    in_mp4 = tmp_path / "input;not-a-command.mp4"
    out_mp4 = tmp_path / "output video.mp4"
    in_mp4.write_bytes(b"video")

    observed: dict[str, object] = {}

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        observed["cmd"] = cmd
        observed["shell"] = shell
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.interpolate_video_fps(
        ffmpeg_path="unused",
        in_mp4=in_mp4,
        out_mp4=out_mp4,
        fps_out=48,
        engine="rife",
        rife_cmd='rife --input "{in}" --output "{out}" --fps {fps}',
    )

    assert observed["shell"] is False
    assert observed["cmd"] == [
        "rife",
        "--input",
        str(in_mp4.resolve()),
        "--output",
        str(out_mp4.resolve()),
        "--fps",
        "48",
    ]


@pytest.mark.parametrize(
    "placeholder",
    [
        "{in.__class__}",
        "{in[0]}",
        "{in!r}",
        "{fps:04d}",
        "{}",
    ],
)
def test_rife_template_rejects_non_exact_placeholders(tmp_path, placeholder) -> None:
    in_mp4 = tmp_path / "input.mp4"
    in_mp4.write_bytes(b"video")

    with pytest.raises(ValueError, match="exact"):
        ffmpeg_service._rife_command_args(
            f"rife --input {placeholder}",
            in_mp4=in_mp4,
            out_mp4=tmp_path / "output.mp4",
            fps=48,
        )


def test_rife_template_allows_escaped_literal_braces(tmp_path) -> None:
    in_mp4 = tmp_path / "input.mp4"
    in_mp4.write_bytes(b"video")

    args = ffmpeg_service._rife_command_args(
        "rife --metadata={{safe}} --input={in}",
        in_mp4=in_mp4,
        out_mp4=tmp_path / "output.mp4",
        fps=48,
    )

    assert args == ["rife", "--metadata={safe}", f"--input={in_mp4.resolve()}"]
