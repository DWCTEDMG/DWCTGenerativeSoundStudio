from __future__ import annotations

import math
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import UserFacingError
from . import tensorrt_standalone
from .ffmpeg import assemble_image_sequence, interpolate_video_fps, mux_audio
from .internal_video import InternalVideoSettings

ProgressFn = Callable[[str, int, int, str | None], None]
LogFn = Callable[[str], None]
CancelFn = Callable[[], None]


def _noop_log(_line: str) -> None:
    return None


def _noop_progress(_stage: str, _current: int, _total: int, _message: str | None = None) -> None:
    return None


def _noop_cancel() -> None:
    return None


def _duration_from_scenes(scenes: list[dict[str, Any]], fallback: float) -> float:
    ends: list[float] = []
    for index, scene in enumerate(scenes):
        start = float(scene.get("start_s", index * 5.0) or 0.0)
        end = float(scene.get("end_s", start + 5.0) or (start + 5.0))
        ends.append(max(start + 0.5, end))
    return max(0.5, max(ends) if ends else float(fallback or 5.0))


def _scene_for_time(scenes: list[dict[str, Any]], t: float) -> dict[str, Any]:
    if not scenes:
        return {"prompt": "cinematic music video keyframe"}
    for index, scene in enumerate(scenes):
        start = float(scene.get("start_s", index * 5.0) or 0.0)
        end = float(scene.get("end_s", start + 5.0) or (start + 5.0))
        if start <= t < end:
            return scene
    return scenes[-1]


def _keyframe_times(scenes: list[dict[str, Any]], duration_s: float, interval_s: float) -> list[float]:
    times = {0.0}
    for index, scene in enumerate(scenes):
        times.add(max(0.0, float(scene.get("start_s", index * 5.0) or 0.0)))
    interval = max(0.5, float(interval_s or 5.0))
    t = 0.0
    while t < duration_s:
        times.add(round(t, 3))
        t += interval
    out = sorted(t for t in times if 0.0 <= t < duration_s)
    if len(out) > 48:
        stride = max(1, int(math.ceil(len(out) / 48)))
        out = out[::stride]
        if 0.0 not in out:
            out.insert(0, 0.0)
    return out or [0.0]


def _prompt_for_scene(scene: dict[str, Any]) -> str:
    prompt = str(scene.get("prompt") or scene.get("description") or "").strip()
    return prompt or "cinematic music video keyframe, detailed, high quality"


def _negative_for_scene(scene: dict[str, Any], fallback: str) -> str:
    return str(scene.get("negative_prompt") or fallback or "blurry, low quality, watermark, text, logo")


def _ease01(value: float) -> float:
    v = max(0.0, min(1.0, float(value)))
    return v * v * (3.0 - 2.0 * v)


def _motion_frame(
    image_path: Path,
    *,
    width: int,
    height: int,
    progress: float,
    direction: int,
    next_image_path: Path | None = None,
) -> Any:
    from PIL import Image, ImageOps

    img = Image.open(image_path).convert("RGB")
    img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
    p = max(0.0, min(1.0, float(progress)))
    if next_image_path is not None and next_image_path.exists() and p >= 0.68:
        nxt = Image.open(next_image_path).convert("RGB")
        nxt = ImageOps.fit(nxt, (width, height), method=Image.Resampling.LANCZOS)
        img = Image.blend(img, nxt, _ease01((p - 0.68) / 0.32))

    eased = _ease01(p)
    zoom = 1.02 + 0.14 * eased
    crop_w = max(1, int(width / zoom))
    crop_h = max(1, int(height / zoom))
    max_x = max(0, width - crop_w)
    max_y = max(0, height - crop_h)
    bias_x = 0.5 + (0.34 * direction * (eased - 0.5))
    bias_y = 0.5 - (0.24 * direction * (eased - 0.5))
    left = int(max_x * max(0.0, min(1.0, bias_x)))
    top = int(max_y * max(0.0, min(1.0, bias_y)))
    return img.crop((left, top, left + crop_w, top + crop_h)).resize((width, height), Image.Resampling.LANCZOS)


def render_tensorrt_video_variant(
    *,
    ffmpeg_path: str,
    project_id: str,
    project_dir: Path,
    variant: dict[str, Any],
    scenes: list[dict[str, Any]],
    audio_path: Path | None,
    settings: InternalVideoSettings,
    bundle_path: Path,
    model_id: str = "local_sd15_tensorrt_bundle",
    log_fn: LogFn | None = None,
    progress_fn: ProgressFn | None = None,
    cancel_check_fn: CancelFn | None = None,
) -> Path:
    """Render a local video using TensorRT SD1.5 keyframes plus Studio assembly."""

    log = log_fn or _noop_log
    progress = progress_fn or _noop_progress
    check_cancel = cancel_check_fn or _noop_cancel

    resolved_bundle_path = Path(bundle_path).expanduser().resolve()
    if not resolved_bundle_path.is_dir():
        raise UserFacingError(
            "The resolved TensorRT bundle folder is unavailable",
            hint="Open Models and verify the canonical TensorRT bundle before rendering.",
            code="TRT_MODEL_NOT_FOUND",
            status_code=400,
        )

    width = 512
    height = 512
    fps_render = max(1, int(settings.fps_render or 1))
    fps_output = max(1, int(settings.fps_output or fps_render))
    duration_s = _duration_from_scenes(scenes, float(variant.get("duration_s") or 0.0))
    render_frames = max(1, int(math.ceil(duration_s * fps_render)))
    key_times = _keyframe_times(scenes, duration_s, float(settings.keyframe_interval_s or 5.0))
    total_units = max(1, len(key_times) + render_frames + 3)
    seed_base = int(settings.seed if settings.seed is not None else time.time()) & 0xFFFFFFFF

    variant_index = int(variant.get("index") or 0)
    work_tag = f"internal_trt_v{variant_index:02d}_{int(time.time())}"
    out_root = project_dir / "outputs" / "tensorrt_video" / work_tag
    key_dir = out_root / "keyframes"
    frames_dir = out_root / "frames"
    video_dir = project_dir / "outputs" / "videos"
    key_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    log(
        f"TensorRT video: model={model_id} keyframes={len(key_times)} "
        f"frames={render_frames} fps_render={fps_render} fps_output={fps_output}"
    )

    rendered_keys: list[tuple[float, Path]] = []
    for index, key_time in enumerate(key_times):
        check_cancel()
        scene = _scene_for_time(scenes, key_time)
        frame_seed = (seed_base + index) & 0xFFFFFFFF
        progress("trt_keyframes", index, total_units, f"Rendering TensorRT keyframe {index + 1}/{len(key_times)}")
        result = tensorrt_standalone.run_job(
            project_id,
            None,  # keep per-frame progress under this video job's control
            {
                "model_id": model_id,
                "model_path": str(resolved_bundle_path),
                "workflow_family": "sd15",
                "prompt": _prompt_for_scene(scene),
                "negative_prompt": _negative_for_scene(scene, settings.negative_prompt),
                "width": width,
                "height": height,
                "steps": max(1, min(80, int(settings.steps or 12))),
                "cfg": float(settings.cfg or 7.0),
                "sampler": str(settings.sampler or "pndm"),
                "seed": frame_seed,
                "batch_size": 1,
            },
        )
        src = Path(str(result.get("output_path") or ""))
        if not src.exists():
            raise RuntimeError("TensorRT keyframe render did not produce an image")
        dest = key_dir / f"key_{index:04d}.png"
        shutil.copy2(src, dest)
        rendered_keys.append((key_time, dest))

    key_index = 0
    for frame_idx in range(render_frames):
        check_cancel()
        t = frame_idx / float(fps_render)
        while key_index + 1 < len(rendered_keys) and rendered_keys[key_index + 1][0] <= t:
            key_index += 1
        current_t, current_img = rendered_keys[key_index]
        next_t = rendered_keys[key_index + 1][0] if key_index + 1 < len(rendered_keys) else duration_s
        next_img = rendered_keys[key_index + 1][1] if key_index + 1 < len(rendered_keys) else None
        span = max(0.001, next_t - current_t)
        local_progress = (t - current_t) / span
        frame = _motion_frame(
            current_img,
            width=width,
            height=height,
            progress=local_progress,
            direction=-1 if key_index % 2 else 1,
            next_image_path=next_img,
        )
        frame.save(frames_dir / f"frame_{frame_idx:06d}.png")
        if frame_idx % max(1, fps_render) == 0 or frame_idx == render_frames - 1:
            progress(
                "trt_frames",
                len(key_times) + frame_idx,
                total_units,
                f"Building TensorRT video frame {frame_idx + 1}/{render_frames}",
            )

    raw_mp4 = video_dir / f"{work_tag}_raw.mp4"
    interp_mp4 = video_dir / f"{work_tag}_interp.mp4"
    final_mp4 = video_dir / f"{work_tag}.mp4"

    progress("assemble", len(key_times) + render_frames, total_units, "Assembling TensorRT frame sequence")
    assemble_image_sequence(ffmpeg_path=ffmpeg_path, frames_dir=frames_dir, out_mp4=raw_mp4, fps=fps_render)

    if fps_output != fps_render:
        progress("interpolate", total_units - 2, total_units, f"Interpolating TensorRT video to {fps_output} fps")
        interpolate_video_fps(
            ffmpeg_path=ffmpeg_path,
            in_mp4=raw_mp4,
            out_mp4=interp_mp4,
            fps_out=fps_output,
            engine=str(settings.interpolation_engine or "auto"),
        )
    else:
        shutil.copy2(raw_mp4, interp_mp4)

    if audio_path and audio_path.exists():
        progress("muxing", total_units - 1, total_units, "Muxing project audio into TensorRT video")
        mux_audio(ffmpeg_path=ffmpeg_path, video_mp4=interp_mp4, audio_path=audio_path, out_mp4=final_mp4)
    else:
        shutil.copy2(interp_mp4, final_mp4)

    progress("complete", total_units, total_units, f"Saved {final_mp4.name}")
    return final_mp4
