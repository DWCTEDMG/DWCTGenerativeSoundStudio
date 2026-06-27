from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def ensure_ffmpeg(ffmpeg_path: str) -> str:
    if os.path.isabs(ffmpeg_path) and Path(ffmpeg_path).exists():
        return ffmpeg_path
    found = shutil.which(ffmpeg_path)
    if not found:
        raise RuntimeError("FFmpeg not found. Install FFmpeg and ensure it's on PATH, or set EDMG_FFMPEG_PATH.")
    return found


def ensure_ffprobe(ffmpeg_path: str) -> str:
    explicit = os.getenv("EDMG_FFPROBE_PATH", "").strip()
    if explicit:
        if os.path.isabs(explicit) and Path(explicit).exists():
            return explicit
        found_explicit = shutil.which(explicit)
        if found_explicit:
            return found_explicit

    ffmpeg = Path(ensure_ffmpeg(ffmpeg_path))
    ffprobe_name = "ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe"
    sibling = ffmpeg.with_name(ffprobe_name)
    if sibling.exists():
        return str(sibling)
    found = shutil.which("ffprobe")
    if not found:
        raise RuntimeError("ffprobe not found. Install FFmpeg with ffprobe available on PATH.")
    return found


def _probe_duration_seconds(ffmpeg_path: str, media_path: Path) -> float | None:
    if not media_path.exists():
        return None
    try:
        ffprobe = ensure_ffprobe(ffmpeg_path)
    except RuntimeError:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        duration = float((proc.stdout or "").strip())
    except Exception:
        return None
    return duration if duration > 0 else None


def _normalize_video_duration(
    ffmpeg_path: str,
    *,
    video_mp4: Path,
    target_duration_s: float,
    actual_duration_s: float,
) -> None:
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    temp_mp4 = video_mp4.with_name(f"{video_mp4.stem}.durationfix{video_mp4.suffix}")
    vf_parts: list[str] = []
    if actual_duration_s < target_duration_s:
        vf_parts.append(f"tpad=stop_mode=clone:stop_duration={max(0.0, target_duration_s - actual_duration_s):.6f}")
    vf_parts.append(f"trim=duration={target_duration_s:.6f}")
    vf_parts.append("setpts=PTS-STARTPTS")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_mp4),
        "-vf",
        ",".join(vf_parts),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(temp_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg duration normalization failed: {proc.stderr[:2000]}")
    temp_mp4.replace(video_mp4)

def assemble_slideshow(
    ffmpeg_path: str,
    image_paths: list[Path],
    durations_s: list[float],
    out_mp4: Path,
    audio_path: Path | None = None,
    fps: int = 30
) -> None:
    """Concatenates still images with explicit per-image durations."""
    if len(image_paths) != len(durations_s):
        raise ValueError("image_paths and durations_s length mismatch")
    if not image_paths:
        raise ValueError("No images to assemble")

    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    list_file = out_mp4.parent / f".concat_{out_mp4.stem}.txt"
    lines: list[str] = []
    for p, d in zip(image_paths, durations_s):
        d = max(0.1, float(d))
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {d}")
    lines.append(f"file '{image_paths[-1].as_posix()}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        ffmpeg, "-y",
        "-r", str(int(fps)),
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
    ]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path), "-shortest"]
    cmd += [
        "-vf", "format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(out_mp4)
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")

def assemble_image_sequence(
    ffmpeg_path: str,
    frames_dir: Path,
    out_mp4: Path,
    fps: int = 24,
    glob_pattern: str = "*.png",
    audio_path: Path | None = None
) -> None:
    """Turns a directory of frame images into an MP4.

    Frames are read in lexicographic order, so name frames consistently:
      frame_000001.png, frame_000002.png, ...
    """
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    frames = sorted([p for p in frames_dir.glob(glob_pattern) if p.is_file()])
    if not frames:
        raise ValueError(f"No frames found in {frames_dir} ({glob_pattern})")

    # Create concat list to avoid relying on strict %06d numbering.
    list_file = out_mp4.parent / f".frames_{out_mp4.stem}.txt"
    list_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in frames]) + "\n", encoding="utf-8")

    cmd = [
        ffmpeg, "-y",
        "-r", str(int(fps)),
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
    ]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path)]
    cmd += [
        "-vf", "format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out_mp4)
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")

def concat_videos(
    ffmpeg_path: str,
    video_paths: list[Path],
    out_mp4: Path,
    audio_path: Path | None = None
) -> None:
    """Concatenate multiple MP4 clips (same codec/params recommended)."""
    if not video_paths:
        raise ValueError("No video clips to concatenate")
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    list_file = out_mp4.parent / f".concat_vid_{out_mp4.stem}.txt"
    list_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in video_paths]) + "\n", encoding="utf-8")

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path), "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")



def _ffmpeg_filters(ffmpeg_path: str) -> str:
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout + "\n" + proc.stderr
    except Exception:
        pass
    return ""

def ffmpeg_has_filter(ffmpeg_path: str, filter_name: str) -> bool:
    """Best-effort check whether FFmpeg build includes a given filter."""
    blob = _ffmpeg_filters(ffmpeg_path)
    return filter_name.lower() in blob.lower()

def interpolate_video_fps(
    ffmpeg_path: str,
    in_mp4: Path,
    out_mp4: Path,
    fps_out: int,
    *,
    engine: str = "auto",
    rife_cmd: str | None = None,
) -> None:
    """Interpolate a video to a higher FPS.

    Engines:
      - auto: prefer RIFE if rife_cmd provided, else ffmpeg minterpolate, else fps (dup).
      - rife: requires rife_cmd template (env EDMG_RIFE_CMD).
      - minterpolate: ffmpeg filter-based motion interpolation.
      - fps: simple frame duplication to target FPS (no motion estimation).
    """
    fps_out = int(fps_out)
    if fps_out <= 0:
        raise ValueError("fps_out must be > 0")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    engine_l = (engine or "auto").lower().strip()
    rife_cmd = rife_cmd or os.getenv("EDMG_RIFE_CMD")

    if engine_l in ("auto", "rife") and rife_cmd:
        # User supplies a command template, because RIFE CLIs vary.
        # Template fields: {in}, {out}, {fps}
        cmd = rife_cmd.format(**{"in": str(in_mp4), "out": str(out_mp4), "fps": str(fps_out)})
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"RIFE command failed: {proc.stderr[:2000]}")
        return

    ffmpeg = ensure_ffmpeg(ffmpeg_path)

    # Prefer minterpolate if available.
    use_mi = engine_l in ("auto", "minterpolate") and ffmpeg_has_filter(ffmpeg_path, "minterpolate")
    if use_mi:
        vf = f"minterpolate=fps={fps_out}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    else:
        # Fallback: duplicate frames to reach target FPS.
        vf = f"fps={fps_out}"

    cmd = [
        ffmpeg, "-y",
        "-i", str(in_mp4),
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg interpolate failed: {proc.stderr[:2000]}")
    if use_mi:
        input_duration = _probe_duration_seconds(ffmpeg_path, in_mp4)
        output_duration = _probe_duration_seconds(ffmpeg_path, out_mp4)
        tolerance_s = max(0.03, (1.0 / max(1, fps_out)) + 0.005)
        if (
            input_duration is not None
            and output_duration is not None
            and abs(output_duration - input_duration) > tolerance_s
        ):
            _normalize_video_duration(
                ffmpeg_path,
                video_mp4=out_mp4,
                target_duration_s=input_duration,
                actual_duration_s=output_duration,
            )

def mux_audio(
    ffmpeg_path: str,
    video_mp4: Path,
    audio_path: Path,
    out_mp4: Path,
) -> None:
    """Attach audio to a video (re-encodes audio to AAC for compatibility)."""
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_mp4),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg mux failed: {proc.stderr[:2000]}")
