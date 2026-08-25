from __future__ import annotations

import math
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from string import Formatter
from typing import Any


def ensure_ffmpeg(ffmpeg_path: str) -> str:
    if os.path.isabs(ffmpeg_path) and Path(ffmpeg_path).exists():
        return ffmpeg_path
    found = shutil.which(ffmpeg_path)
    if not found:
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg and ensure it's on PATH, or set EDMG_FFMPEG_PATH."
        )
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


def _ffconcat_quote(path: Path) -> str:
    """Return an ffconcat-safe, absolute file path.

    The concat demuxer parses its input as a directive file, so writing a raw
    filename would let quotes or newlines alter the manifest. Resolve inputs
    before serialization and use the demuxer's documented single-quote
    escaping form.
    """
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"Media input is not a file: {path}")
    value = resolved.as_posix()
    if any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("Media paths cannot contain NUL or newline characters")
    return "'" + value.replace("'", "'\\''") + "'"


def _write_concat_manifest(directory: Path, prefix: str, lines: list[str]) -> Path:
    # Callers derive this directory from a root-confined ProjectStore output.
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=prefix,
        suffix=".ffconcat",
        # The directory is the validated output parent described above.
        dir=directory,
        delete=False,
    ) as manifest:
        manifest.write("ffconcat version 1.0\n")
        manifest.write("\n".join(lines))
        manifest.write("\n")
        return Path(manifest.name)


def _rife_command_args(template: str, *, in_mp4: Path, out_mp4: Path, fps: int) -> list[str]:
    """Expand a configured RIFE command without invoking a command shell."""
    try:
        parts = shlex.split(template, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError("EDMG_RIFE_CMD contains invalid quoting") from exc
    if os.name == "nt":
        parts = [
            part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'} else part
            for part in parts
        ]
    if not parts:
        raise ValueError("EDMG_RIFE_CMD must contain an executable")
    values = {
        # Render inputs and outputs come from root-confined project paths; these
        # resolves canonicalize them before shell-free argv construction.
        "in": str(in_mp4.expanduser().resolve(strict=True)),
        "out": str(out_mp4.expanduser().resolve(strict=False)),
        "fps": str(int(fps)),
    }
    try:
        parsed_parts = [list(Formatter().parse(part)) for part in parts]
    except ValueError as exc:
        raise ValueError("EDMG_RIFE_CMD contains invalid placeholder syntax") from exc
    for parsed_part in parsed_parts:
        for _literal, field_name, format_spec, conversion in parsed_part:
            if field_name is None:
                continue
            if field_name not in values or format_spec or conversion:
                raise ValueError(
                    "EDMG_RIFE_CMD may only use exact {in}, {out}, and {fps} placeholders"
                )
    try:
        args = [part.format_map(values) for part in parts]
    except (KeyError, ValueError, AttributeError, IndexError) as exc:
        raise ValueError("EDMG_RIFE_CMD may only use {in}, {out}, and {fps} placeholders") from exc
    if any("\x00" in arg for arg in args):
        raise ValueError("EDMG_RIFE_CMD arguments cannot contain NUL characters")
    return args


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


def _probe_frame_rate(ffmpeg_path: str, media_path: Path) -> float | None:
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
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        value = str(line or "").strip()
        if not value or value == "0/0":
            continue
        try:
            if "/" in value:
                num_s, den_s = value.split("/", 1)
                num = float(num_s)
                den = float(den_s)
                if den == 0:
                    continue
                rate = num / den
            else:
                rate = float(value)
        except Exception:
            continue
        if rate > 0:
            return rate
    return None


def has_video_stream(ffmpeg_path: str, media_path: Path) -> bool | None:
    """Best-effort probe for a video stream in a media container."""
    if not media_path.exists():
        return False
    try:
        ffprobe = ensure_ffprobe(ffmpeg_path)
    except RuntimeError:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False
    stream_lines = [
        line.strip().lower() for line in (proc.stdout or "").splitlines() if line.strip()
    ]
    return any(line == "video" for line in stream_lines)


def has_audio_stream(ffmpeg_path: str, media_path: Path) -> bool | None:
    """Best-effort probe for an audio stream in a media container."""
    if not media_path.exists():
        return False
    try:
        ffprobe = ensure_ffprobe(ffmpeg_path)
    except RuntimeError:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    return any(line.strip().lower() == "audio" for line in (proc.stdout or "").splitlines())


class TimelineRenderCanceled(RuntimeError):
    pass


_TIMELINE_VIDEO_SUFFIXES = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
_TIMELINE_IMAGE_SUFFIXES = {
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}


def _timeline_clip_values(clip: dict[str, Any]) -> dict[str, Any]:
    values = dict(clip.get("data") or {}) if isinstance(clip.get("data"), dict) else {}
    values.update({key: value for key, value in clip.items() if key != "data"})
    return values


def _timeline_tracks(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    tracks = timeline.get("tracks")
    if isinstance(tracks, list):
        projected.extend(track for track in tracks if isinstance(track, dict))
    layers = timeline.get("layers")
    if isinstance(layers, list):
        projected.extend(
            {
                "id": str(layer.get("id") or f"layer-{index}"),
                "name": str(layer.get("name") or layer.get("id") or f"Layer {index + 1}"),
                "is_layer": True,
                "clips": (layer["clips"] if isinstance(layer.get("clips"), list) else [layer]),
            }
            for index, layer in enumerate(layers)
            if isinstance(layer, dict)
        )
    if projected:
        return projected
    clips = timeline.get("clips")
    if isinstance(clips, list):
        return [{"id": "legacy-clips", "clips": clips}]
    return []


def _resolve_timeline_source(project_dir: Path, source_value: Any) -> tuple[str, Path, str]:
    source = str(source_value or "").strip().replace("\\", "/")
    if not source:
        raise ValueError("Timeline clip is missing source_path")
    relative = Path(source)
    windows_path = PureWindowsPath(str(source_value or ""))
    if (
        relative.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or source.startswith(("/", "\\"))
        or any(part == ".." for part in relative.parts)
    ):
        raise ValueError("Timeline source_path must be project-relative")
    project_root = project_dir.resolve()
    candidates = (
        [
            project_root / "outputs" / "videos" / relative,
            project_root / relative,
        ]
        if len(relative.parts) == 1
        else [project_root / relative]
    )
    resolved: Path | None = None
    for candidate in candidates:
        candidate = candidate.resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("Timeline source_path escapes the project directory") from exc
        if candidate.is_file():
            resolved = candidate
            break
    if resolved is None:
        raise ValueError(f"Timeline visual source does not exist: {source}")
    suffix = resolved.suffix.lower()
    if suffix in _TIMELINE_VIDEO_SUFFIXES:
        source_kind = "video"
    elif suffix in _TIMELINE_IMAGE_SUFFIXES:
        source_kind = "image"
    else:
        raise ValueError(f"Timeline source is not a supported visual file: {source}")
    return resolved.relative_to(project_root).as_posix(), resolved, source_kind


def _atempo_filters(speed: float) -> list[str]:
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.8g}")
    return filters


def prepare_timeline_render_plan(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    timeline: dict[str, Any],
) -> dict[str, Any]:
    """Validate a saved timeline and return the only data persisted in the render job."""
    if not isinstance(timeline, dict):
        raise ValueError("Project timeline must be an object")
    prepared_tracks: list[dict[str, Any]] = []
    try:
        timeline_duration = float(timeline.get("duration_s", timeline.get("duration", 0.0)) or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Timeline duration must be numeric") from exc
    if not math.isfinite(timeline_duration) or timeline_duration < 0:
        raise ValueError("Timeline duration must be a finite non-negative number")
    for track_index, track in enumerate(_timeline_tracks(timeline)):
        is_layer = bool(track.get("is_layer", False))
        prepared_clips: list[dict[str, Any]] = []
        raw_clips = track.get("clips")
        if not isinstance(raw_clips, list):
            continue
        for clip_index, raw_clip in enumerate(raw_clips):
            if not isinstance(raw_clip, dict):
                continue
            clip = _timeline_clip_values(raw_clip)
            source_value = clip.get("source_path")
            if not str(source_value or "").strip():
                continue
            source_relative, source_path, source_kind = _resolve_timeline_source(
                project_dir, source_value
            )
            if has_video_stream(ffmpeg_path, source_path) is not True:
                raise ValueError(f"Timeline source has no video stream: {source_relative}")
            try:
                start = float(clip.get("start_s", clip.get("timeline_start_s", 0.0)))
                end = float(clip.get("end_s", clip.get("timeline_end_s", start)))
                speed = float(clip.get("speed", 1.0))
                source_in = float(clip.get("source_in_s", 0.0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has invalid numeric values"
                ) from exc
            if not all(math.isfinite(value) for value in (start, end, speed, source_in)):
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} numeric values must be finite"
                )
            if start < 0 or end <= start:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has an invalid start/end"
                )
            if speed <= 0 or speed > 16:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has an invalid speed"
                )
            source_out_value = clip.get("source_out_s")
            try:
                source_out = (
                    float(source_out_value)
                    if source_out_value is not None
                    else source_in + ((end - start) * speed)
                )
                volume = float(clip.get("volume", 1.0))
                fade_in = float(clip.get("fade_in_s", 0.0))
                fade_out = float(clip.get("fade_out_s", 0.0))
                opacity = float(clip.get("opacity", 1.0))
                brightness = float(clip.get("brightness", 0.0))
                contrast = float(clip.get("contrast", 1.0))
                saturation = float(clip.get("saturation", 1.0))
                rotation_degrees = float(clip.get("rotation_deg", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has invalid numeric values"
                ) from exc
            if not all(
                math.isfinite(value)
                for value in (
                    source_out,
                    volume,
                    fade_in,
                    fade_out,
                    opacity,
                    brightness,
                    contrast,
                    saturation,
                    rotation_degrees,
                )
            ):
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} numeric values must be finite"
                )
            if source_in < 0 or source_out <= source_in:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has an invalid source range"
                )
            required_source_duration = (end - start) * speed
            if source_out - source_in + 0.001 < required_source_duration:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} source range is too short"
                )
            fit_mode = str(clip.get("fit_mode") or "contain").strip().lower()
            if fit_mode not in {"contain", "cover", "stretch"}:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} has an invalid fit mode"
                )
            if not 0.0 <= opacity <= 1.0:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} opacity must be between 0 and 1"
                )
            if not -1.0 <= brightness <= 1.0:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} brightness must be between -1 and 1"
                )
            if not 0.0 <= contrast <= 2.0:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} contrast must be between 0 and 2"
                )
            if not 0.0 <= saturation <= 3.0:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} saturation must be between 0 and 3"
                )
            rotation = int(rotation_degrees)
            if rotation_degrees != rotation or rotation not in {0, 90, 180, 270}:
                raise ValueError(
                    f"Timeline clip {track_index + 1}.{clip_index + 1} rotation must be 0, 90, 180, or 270"
                )
            prepared_clips.append(
                {
                    "id": str(clip.get("id") or f"clip-{track_index}-{clip_index}"),
                    "source_path": source_relative,
                    "source_kind": source_kind,
                    "is_layer": is_layer,
                    "start_s": start,
                    "end_s": end,
                    "source_in_s": source_in,
                    "source_out_s": source_out,
                    "speed": speed,
                    "volume": max(0.0, min(16.0, volume)),
                    "muted": bool(clip.get("muted", clip.get("mute", False))),
                    "fade_in_s": max(0.0, fade_in),
                    "fade_out_s": max(0.0, fade_out),
                    "fit_mode": fit_mode,
                    "opacity": opacity,
                    "brightness": brightness,
                    "contrast": contrast,
                    "saturation": saturation,
                    "rotation_deg": rotation,
                    "flip_horizontal": bool(clip.get("flip_horizontal", False)),
                    "has_audio": source_kind == "video"
                    and has_audio_stream(ffmpeg_path, source_path) is not False,
                }
            )
            timeline_duration = max(timeline_duration, end)
        prepared_clips.sort(key=lambda item: (item["start_s"], item["end_s"], item["id"]))
        for previous, current in zip(prepared_clips, prepared_clips[1:], strict=False):
            if current["start_s"] < previous["end_s"] - 0.001:
                track_name = str(track.get("name") or track.get("id") or track_index + 1)
                raise ValueError(
                    f"Overlapping clips in timeline track {track_name!r} are not supported"
                )
        if prepared_clips:
            prepared_tracks.append(
                {
                    "id": str(track.get("id") or f"track-{track_index}"),
                    "is_layer": is_layer,
                    "clips": prepared_clips,
                }
            )
    if not prepared_tracks:
        raise ValueError("Timeline contains no renderable video clips")
    return {"duration_s": timeline_duration, "tracks": prepared_tracks}


def build_timeline_render_command(
    *,
    ffmpeg_path: str,
    project_dir: Path,
    timeline: dict[str, Any],
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    video_codec: str,
    audio_codec: str,
    quality: int,
) -> tuple[list[str], float]:
    """Build a shell-free FFmpeg command for a flattened edited timeline."""
    plan = prepare_timeline_render_plan(
        ffmpeg_path=ffmpeg_path,
        project_dir=project_dir,
        timeline=timeline,
    )
    duration_s = float(plan["duration_s"])
    clips = [clip for track in plan["tracks"] for clip in track["clips"]]

    codec_options = {
        "h264": ("libx264", "yuv420p", ".mp4"),
        "hevc": ("libx265", "yuv420p", ".mp4"),
        "prores": ("prores_ks", "yuv422p10le", ".mov"),
    }
    if video_codec not in codec_options:
        raise ValueError(f"Unsupported video codec: {video_codec}")
    if (video_codec == "prores" and audio_codec != "pcm_s16le") or (
        video_codec != "prores" and audio_codec != "aac"
    ):
        raise ValueError("Invalid video/audio codec combination")
    expected_suffix = codec_options[video_codec][2]
    if output_path.suffix.lower() != expected_suffix:
        raise ValueError(f"{video_codec} output must use {expected_suffix}")

    command = [ensure_ffmpeg(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        if clip["source_kind"] == "image":
            command.extend(["-loop", "1", "-framerate", f"{fps:.8g}"])
        command.extend(["-i", str(project_dir / clip["source_path"])])
    black_input = len(clips)
    silence_input = black_input + 1
    command.extend(
        [
            "-f",
            "lavfi",
            "-t",
            f"{duration_s:.6f}",
            "-i",
            f"color=c=black:s={width}x{height}:r={fps:.8g}",
            "-f",
            "lavfi",
            "-t",
            f"{duration_s:.6f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ]
    )

    filters: list[str] = [
        f"[{black_input}:v]trim=duration={duration_s:.6f},setpts=PTS-STARTPTS[vbase]"
    ]
    current_video = "vbase"
    audio_labels = [f"{silence_input}:a"]
    for input_index, clip in enumerate(clips):
        start = float(clip["start_s"])
        duration = float(clip["end_s"]) - start
        source_in = float(clip["source_in_s"])
        source_out = float(clip["source_out_s"])
        speed = float(clip["speed"])
        video_filters = [
            f"trim=start={source_in:.6f}:end={source_out:.6f}",
            f"setpts=(PTS-STARTPTS)/{speed:.8g}",
            f"trim=duration={duration:.6f}",
        ]
        rotation = int(clip["rotation_deg"])
        if rotation == 90:
            video_filters.append("transpose=clock")
        elif rotation == 180:
            video_filters.extend(["hflip", "vflip"])
        elif rotation == 270:
            video_filters.append("transpose=cclock")
        if clip["flip_horizontal"]:
            video_filters.append("hflip")

        fit_mode = str(clip["fit_mode"])
        transparent_padding = False
        if fit_mode == "cover":
            video_filters.extend(
                [
                    f"scale={width}:{height}:force_original_aspect_ratio=increase",
                    f"crop={width}:{height}",
                ]
            )
        elif fit_mode == "stretch":
            video_filters.append(f"scale={width}:{height}")
        else:
            video_filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
            if clip["is_layer"]:
                transparent_padding = True
            else:
                video_filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")

        brightness = float(clip["brightness"])
        contrast = float(clip["contrast"])
        saturation = float(clip["saturation"])
        if brightness != 0.0 or contrast != 1.0 or saturation != 1.0:
            video_filters.append(
                f"eq=brightness={brightness:.8g}:contrast={contrast:.8g}:saturation={saturation:.8g}"
            )
        opacity = float(clip["opacity"])
        if clip["is_layer"]:
            video_filters.append("format=rgba")
            if transparent_padding:
                video_filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0")
        elif opacity < 1.0:
            video_filters.append("format=rgba")
        if opacity < 1.0:
            video_filters.append(f"colorchannelmixer=aa={opacity:.8g}")
        video_filters.extend([f"fps={fps:.8g}", "setsar=1"])
        fade_in = min(float(clip["fade_in_s"]), duration)
        fade_out = min(float(clip["fade_out_s"]), duration)
        fade_alpha = ":alpha=1" if clip["is_layer"] else ""
        if fade_in > 0:
            video_filters.append(f"fade=t=in:st=0:d={fade_in:.6f}{fade_alpha}")
        if fade_out > 0:
            video_filters.append(
                f"fade=t=out:st={duration - fade_out:.6f}:d={fade_out:.6f}{fade_alpha}"
            )
        video_filters.append(f"setpts=PTS+{start:.6f}/TB")
        filters.append(f"[{input_index}:v:0]{','.join(video_filters)}[vc{input_index}]")
        filters.append(
            f"[{current_video}][vc{input_index}]overlay=eof_action=pass:shortest=0[vo{input_index}]"
        )
        current_video = f"vo{input_index}"

        if clip["has_audio"]:
            audio_filters = [
                f"atrim=start={source_in:.6f}:end={source_out:.6f}",
                "asetpts=PTS-STARTPTS",
                *_atempo_filters(speed),
                f"atrim=duration={duration:.6f}",
                "aresample=48000",
                "aformat=sample_rates=48000:channel_layouts=stereo",
                f"volume={0.0 if clip['muted'] else clip['volume']:.8g}",
            ]
            if fade_in > 0:
                audio_filters.append(f"afade=t=in:st=0:d={fade_in:.6f}")
            if fade_out > 0:
                audio_filters.append(f"afade=t=out:st={duration - fade_out:.6f}:d={fade_out:.6f}")
            audio_filters.extend(
                [
                    f"adelay={int(round(start * 1000))}:all=1",
                    f"apad=whole_dur={duration_s:.6f}",
                    f"atrim=duration={duration_s:.6f}",
                ]
            )
            filters.append(f"[{input_index}:a:0]{','.join(audio_filters)}[ac{input_index}]")
            audio_labels.append(f"ac{input_index}")
    if len(audio_labels) == 1:
        filters.append(
            f"[{audio_labels[0]}]atrim=duration={duration_s:.6f},asetpts=PTS-STARTPTS[aout]"
        )
    else:
        filters.append(
            "".join(f"[{label}]" for label in audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,"
            + f"atrim=duration={duration_s:.6f}[aout]"
        )
    video_encoder, pixel_format, _ = codec_options[video_codec]
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{current_video}]",
            "-map",
            "[aout]",
            "-c:v",
            video_encoder,
            "-pix_fmt",
            pixel_format,
        ]
    )
    if video_codec == "prores":
        command.extend(["-profile:v", "3"])
    else:
        command.extend(["-crf", str(quality)])
    command.extend(["-c:a", audio_codec])
    if audio_codec == "aac":
        command.extend(["-b:a", "192k"])
    if video_codec != "prores":
        command.extend(["-movflags", "+faststart"])
    command.extend(["-t", f"{duration_s:.6f}", str(output_path)])
    return command, duration_s


def render_timeline_edited_master(
    *,
    command: list[str],
    output_path: Path,
    duration_s: float,
    is_canceled: Callable[[], bool] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Run an edited-master command while polling the persistent cancel flag."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while proc.poll() is None:
            if is_canceled and is_canceled():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                raise TimelineRenderCanceled("Timeline render canceled")
            if on_progress:
                elapsed = time.monotonic() - started
                on_progress(min(0.95, elapsed / max(duration_s, 1.0)))
            time.sleep(0.1)
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            message = (stderr or "").strip()
            raise RuntimeError(
                f"FFmpeg timeline render failed ({proc.returncode}): {message[-2000:]}"
            )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise RuntimeError("FFmpeg timeline render did not produce an output file")
        if on_progress:
            on_progress(1.0)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        output_path.unlink(missing_ok=True)
        raise


def _video_output_is_usable(ffmpeg_path: str, media_path: Path) -> bool:
    if not media_path.exists():
        return False
    try:
        if media_path.stat().st_size <= 0:
            return False
    except OSError:
        return False
    stream_status = has_video_stream(ffmpeg_path, media_path)
    return stream_status is not False


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
        vf_parts.append(
            f"tpad=stop_mode=clone:stop_duration={max(0.0, target_duration_s - actual_duration_s):.6f}"
        )
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
    fps: int = 30,
) -> None:
    """Concatenates still images with explicit per-image durations."""
    if len(image_paths) != len(durations_s):
        raise ValueError("image_paths and durations_s length mismatch")
    if not image_paths:
        raise ValueError("No images to assemble")

    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for p, d in zip(image_paths, durations_s, strict=True):
        d = float(d)
        if not math.isfinite(d):
            raise ValueError("Image durations must be finite numbers")
        d = max(0.1, d)
        lines.append(f"file {_ffconcat_quote(p)}")
        lines.append(f"duration {d}")
    lines.append(f"file {_ffconcat_quote(image_paths[-1])}")
    list_file = _write_concat_manifest(out_mp4.parent, ".concat_", lines)

    cmd = [
        ffmpeg,
        "-y",
        "-r",
        str(int(fps)),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
    ]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path), "-shortest"]
    cmd += ["-vf", "format=yuv420p", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")
    finally:
        list_file.unlink(missing_ok=True)


def assemble_image_sequence(
    ffmpeg_path: str,
    frames_dir: Path,
    out_mp4: Path,
    fps: int = 24,
    glob_pattern: str = "*.png",
    audio_path: Path | None = None,
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
    list_file = _write_concat_manifest(
        out_mp4.parent,
        ".frames_",
        [f"file {_ffconcat_quote(path)}" for path in frames],
    )

    raw_out = out_mp4
    if audio_path and audio_path.exists():
        raw_out = out_mp4.with_name(f"{out_mp4.stem}.rawvideo{out_mp4.suffix}")

    cmd = [
        ffmpeg,
        "-y",
        "-r",
        str(int(fps)),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
    ]
    cmd += ["-vf", "format=yuv420p", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw_out)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")
        if audio_path and audio_path.exists():
            mux_audio(
                ffmpeg_path=ffmpeg_path, video_mp4=raw_out, audio_path=audio_path, out_mp4=out_mp4
            )
            try:
                raw_duration = _probe_duration_seconds(ffmpeg_path, raw_out)
                final_video_duration = _probe_duration_seconds(ffmpeg_path, out_mp4)
                if (
                    raw_duration is not None
                    and final_video_duration is not None
                    and abs(final_video_duration - raw_duration)
                    > max(0.03, (1.0 / max(1, int(fps))) + 0.005)
                ):
                    _normalize_video_duration(
                        ffmpeg_path,
                        video_mp4=out_mp4,
                        target_duration_s=raw_duration,
                        actual_duration_s=final_video_duration,
                    )
                    remux_out = out_mp4.with_name(f"{out_mp4.stem}.remux{out_mp4.suffix}")
                    mux_audio(
                        ffmpeg_path=ffmpeg_path,
                        video_mp4=out_mp4,
                        audio_path=audio_path,
                        out_mp4=remux_out,
                    )
                    remux_out.replace(out_mp4)
            finally:
                raw_out.unlink(missing_ok=True)
    finally:
        list_file.unlink(missing_ok=True)


def concat_videos(
    ffmpeg_path: str, video_paths: list[Path], out_mp4: Path, audio_path: Path | None = None
) -> None:
    """Concatenate multiple MP4 clips (same codec/params recommended)."""
    if not video_paths:
        raise ValueError("No video clips to concatenate")
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    list_file = _write_concat_manifest(
        out_mp4.parent,
        ".concat_vid_",
        [f"file {_ffconcat_quote(path)}" for path in video_paths],
    )

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path), "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {proc.stderr[:2000]}")
    finally:
        list_file.unlink(missing_ok=True)


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

    input_fps = _probe_frame_rate(ffmpeg_path, in_mp4)
    if input_fps is not None and math.isclose(input_fps, float(fps_out), rel_tol=0.0, abs_tol=0.01):
        shutil.copyfile(in_mp4, out_mp4)
        if _video_output_is_usable(ffmpeg_path, out_mp4):
            return

    engine_l = (engine or "auto").lower().strip()
    rife_cmd = rife_cmd or os.getenv("EDMG_RIFE_CMD")

    if engine_l in ("auto", "rife") and rife_cmd:
        # User supplies a command template, because RIFE CLIs vary.
        # Template fields: {in}, {out}, {fps}
        cmd = _rife_command_args(rife_cmd, in_mp4=in_mp4, out_mp4=out_mp4, fps=fps_out)
        proc = subprocess.run(cmd, shell=False, capture_output=True, text=True)
        if proc.returncode != 0:
            if engine_l == "rife":
                raise RuntimeError(f"RIFE command failed: {proc.stderr[:2000]}")
        elif _video_output_is_usable(ffmpeg_path, out_mp4):
            return
        elif engine_l == "rife":
            raise RuntimeError("RIFE command produced an output without a video stream")

    ffmpeg = ensure_ffmpeg(ffmpeg_path)

    def _run_interpolation_filter(vf: str, *, normalize_duration: bool) -> None:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(in_mp4),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg interpolate failed: {proc.stderr[:2000]}")
        if not _video_output_is_usable(ffmpeg_path, out_mp4):
            return
        if normalize_duration:
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

    # Prefer minterpolate when available, but short clips can produce a container
    # with no streams. Fall back to plain FPS duplication and finally to the input
    # clip rather than returning a false-success empty MP4.
    use_mi = engine_l in ("auto", "minterpolate") and ffmpeg_has_filter(ffmpeg_path, "minterpolate")
    filter_attempts: list[tuple[str, bool]] = []
    if use_mi:
        filter_attempts.append(
            (
                f"minterpolate=fps={fps_out}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                True,
            )
        )
    filter_attempts.append((f"fps={fps_out}", False))

    for vf, normalize_duration in filter_attempts:
        _run_interpolation_filter(vf, normalize_duration=normalize_duration)
        if _video_output_is_usable(ffmpeg_path, out_mp4):
            return

    if _video_output_is_usable(ffmpeg_path, in_mp4):
        shutil.copyfile(in_mp4, out_mp4)
        if _video_output_is_usable(ffmpeg_path, out_mp4):
            return

    raise RuntimeError(f"Interpolated output is missing a video stream: {out_mp4}")


def mux_audio(
    ffmpeg_path: str,
    video_mp4: Path,
    audio_path: Path,
    out_mp4: Path,
) -> None:
    """Attach audio to a video (re-encodes audio to AAC for compatibility)."""
    ffmpeg = ensure_ffmpeg(ffmpeg_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    video_duration_s = _probe_duration_seconds(ffmpeg_path, video_mp4)
    cmd = [ffmpeg, "-y", "-i", str(video_mp4), "-i", str(audio_path)]
    if video_duration_s is not None:
        cmd += [
            "-filter_complex",
            f"[1:a]apad,atrim=duration={video_duration_s:.6f}[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
        ]
    cmd += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if video_duration_s is None:
        cmd.append("-shortest")
    cmd.append(str(out_mp4))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg mux failed: {proc.stderr[:2000]}")
