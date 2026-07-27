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


def test_interpolate_skips_reencode_when_input_already_matches_target_fps(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    in_mp4 = tmp_path / "in.mp4"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    in_mp4.write_bytes(b"same-fps-video")

    monkeypatch.setattr(ffmpeg_service, "_probe_frame_rate", lambda _ffmpeg_path, _media_path: 24.0)
    monkeypatch.setattr(ffmpeg_service, "_video_output_is_usable", lambda _ffmpeg_path, path: path.exists())

    def fake_run(*_args, **_kwargs):
        raise AssertionError("ffmpeg should not be invoked when the input already matches the requested FPS")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.interpolate_video_fps(
        ffmpeg_path=str(ffmpeg),
        in_mp4=in_mp4,
        out_mp4=out_mp4,
        fps_out=24,
        engine="auto",
    )

    assert out_mp4.read_bytes() == b"same-fps-video"


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


def test_assemble_image_sequence_muxes_audio_after_raw_encode_and_duration_fix(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    frames_dir = tmp_path / "frames"
    out_mp4 = tmp_path / "output.mp4"
    audio_path = tmp_path / "audio.wav"
    ffmpeg.write_bytes(b"exe")
    frames_dir.mkdir()
    for idx in range(2):
        (frames_dir / f"frame_{idx:06d}.png").write_bytes(b"frame")
    audio_path.write_bytes(b"audio")

    ffmpeg_calls: list[list[str]] = []
    mux_calls: list[dict[str, Path]] = []
    duration_calls: list[Path] = []
    normalized: list[dict[str, float | Path]] = []

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        ffmpeg_calls.append([str(part) for part in cmd])
        Path(cmd[-1]).write_bytes(b"raw-video")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_mux_audio(*, ffmpeg_path, video_mp4, audio_path, out_mp4):
        mux_calls.append(
            {
                "video_mp4": Path(video_mp4),
                "audio_path": Path(audio_path),
                "out_mp4": Path(out_mp4),
            }
        )
        Path(out_mp4).write_bytes(Path(video_mp4).read_bytes() + b"+mux")

    def fake_probe_duration(_ffmpeg_path: str, media_path: Path):
        duration_calls.append(Path(media_path))
        name = Path(media_path).name
        if ".rawvideo." in name:
            return 10.0
        if ".remux." in name:
            return 10.0
        if name == out_mp4.name:
            # Simulate audio mux trimming one frame from the visible video stream.
            return 9.8
        return None

    def fake_normalize_video_duration(ffmpeg_path, *, video_mp4, target_duration_s, actual_duration_s):
        normalized.append(
            {
                "video_mp4": Path(video_mp4),
                "target_duration_s": float(target_duration_s),
                "actual_duration_s": float(actual_duration_s),
            }
        )
        Path(video_mp4).write_bytes(Path(video_mp4).read_bytes() + b"+norm")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)
    monkeypatch.setattr(ffmpeg_service, "mux_audio", fake_mux_audio)
    monkeypatch.setattr(ffmpeg_service, "_probe_duration_seconds", fake_probe_duration)
    monkeypatch.setattr(ffmpeg_service, "_normalize_video_duration", fake_normalize_video_duration)

    ffmpeg_service.assemble_image_sequence(
        ffmpeg_path=str(ffmpeg),
        frames_dir=frames_dir,
        out_mp4=out_mp4,
        fps=6,
        audio_path=audio_path,
    )

    assert len(ffmpeg_calls) == 1
    assert len(mux_calls) == 2
    assert mux_calls[0]["video_mp4"].name == "output.rawvideo.mp4"
    assert mux_calls[0]["out_mp4"] == out_mp4
    assert normalized == [
        {
            "video_mp4": out_mp4,
            "target_duration_s": 10.0,
            "actual_duration_s": 9.8,
        }
    ]
    assert mux_calls[1]["video_mp4"] == out_mp4
    assert mux_calls[1]["out_mp4"].name == "output.remux.mp4"
    assert out_mp4.read_bytes().endswith(b"+norm+mux")
    assert not (tmp_path / "output.rawvideo.mp4").exists()
    assert not (tmp_path / "output.remux.mp4").exists()


def test_rife_template_is_expanded_as_argv_without_a_shell(tmp_path, monkeypatch) -> None:
    in_mp4 = tmp_path / "input;not-a-command.mp4"
    out_mp4 = tmp_path / "output video.mp4"
    in_mp4.write_bytes(b"video")

    observed: dict[str, object] = {}
    monkeypatch.delenv("EDMG_FFPROBE_PATH", raising=False)

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        observed["cmd"] = cmd
        observed["shell"] = shell
        out_mp4.write_bytes(b"output")
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


def test_interpolate_falls_back_to_fps_when_minterpolate_output_has_no_video_stream(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    in_mp4 = tmp_path / "in.mp4"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    in_mp4.write_bytes(b"valid-input")

    monkeypatch.setattr(ffmpeg_service, "ffmpeg_has_filter", lambda _ffmpeg_path, _filter_name: True)
    monkeypatch.setattr(ffmpeg_service, "_probe_frame_rate", lambda _ffmpeg_path, _media_path: None)
    monkeypatch.setattr(
        ffmpeg_service,
        "_video_output_is_usable",
        lambda _ffmpeg_path, path: path.exists() and path.read_bytes().startswith(b"valid"),
    )

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, timeout=None, shell=False):
        parts = [str(part) for part in (cmd if isinstance(cmd, list) else [cmd])]
        calls.append(parts)
        vf = parts[parts.index("-vf") + 1]
        if "minterpolate" in vf:
            out_mp4.write_bytes(b"invalid-mi")
        else:
            out_mp4.write_bytes(b"valid-fps")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.interpolate_video_fps(
        ffmpeg_path=str(ffmpeg),
        in_mp4=in_mp4,
        out_mp4=out_mp4,
        fps_out=24,
        engine="minterpolate",
    )

    assert out_mp4.read_bytes() == b"valid-fps"
    assert len(calls) == 2
    assert "minterpolate=fps=24" in calls[0][calls[0].index("-vf") + 1]
    assert calls[1][calls[1].index("-vf") + 1] == "fps=24"


def test_interpolate_copies_input_when_filter_outputs_are_invalid(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    in_mp4 = tmp_path / "in.mp4"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    in_mp4.write_bytes(b"valid-input")

    monkeypatch.setattr(ffmpeg_service, "ffmpeg_has_filter", lambda _ffmpeg_path, _filter_name: True)
    monkeypatch.setattr(ffmpeg_service, "_probe_frame_rate", lambda _ffmpeg_path, _media_path: None)
    monkeypatch.setattr(
        ffmpeg_service,
        "_video_output_is_usable",
        lambda _ffmpeg_path, path: path.exists() and path.read_bytes().startswith(b"valid"),
    )

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, timeout=None, shell=False):
        parts = [str(part) for part in (cmd if isinstance(cmd, list) else [cmd])]
        calls.append(parts)
        out_mp4.write_bytes(b"invalid-out")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.interpolate_video_fps(
        ffmpeg_path=str(ffmpeg),
        in_mp4=in_mp4,
        out_mp4=out_mp4,
        fps_out=24,
        engine="minterpolate",
    )

    assert out_mp4.read_bytes() == b"valid-input"
    assert len(calls) == 2


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


def test_mux_audio_matches_audio_length_to_known_video_duration(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    video_mp4 = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.wav"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    video_mp4.write_bytes(b"video")
    audio_path.write_bytes(b"audio")

    observed: list[str] = []

    monkeypatch.setattr(ffmpeg_service, "_probe_duration_seconds", lambda _ffmpeg_path, _path: 330.0)

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        nonlocal observed
        observed = [str(part) for part in cmd]
        out_mp4.write_bytes(b"muxed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.mux_audio(
        ffmpeg_path=str(ffmpeg),
        video_mp4=video_mp4,
        audio_path=audio_path,
        out_mp4=out_mp4,
    )

    assert "-filter_complex" in observed
    assert observed[observed.index("-filter_complex") + 1] == "[1:a]apad,atrim=duration=330.000000[aout]"
    assert observed[observed.index("-map") + 1] == "0:v:0"
    assert observed[observed.index("-map", observed.index("-map") + 1) + 1] == "[aout]"
    assert "-shortest" not in observed
    assert out_mp4.read_bytes() == b"muxed"


def test_mux_audio_falls_back_to_shortest_when_video_duration_is_unknown(tmp_path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    video_mp4 = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.wav"
    out_mp4 = tmp_path / "out.mp4"
    ffmpeg.write_bytes(b"exe")
    video_mp4.write_bytes(b"video")
    audio_path.write_bytes(b"audio")

    observed: list[str] = []

    monkeypatch.setattr(ffmpeg_service, "_probe_duration_seconds", lambda _ffmpeg_path, _path: None)

    def fake_run(cmd, capture_output=True, text=True, shell=False):
        nonlocal observed
        observed = [str(part) for part in cmd]
        out_mp4.write_bytes(b"muxed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_service.subprocess, "run", fake_run)

    ffmpeg_service.mux_audio(
        ffmpeg_path=str(ffmpeg),
        video_mp4=video_mp4,
        audio_path=audio_path,
        out_mp4=out_mp4,
    )

    assert "-filter_complex" not in observed
    assert "-map" not in observed
    assert "-shortest" in observed
    assert out_mp4.read_bytes() == b"muxed"
