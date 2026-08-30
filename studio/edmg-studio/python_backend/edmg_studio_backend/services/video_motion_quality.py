from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

MIN_VIDEO_MODEL_NATIVE_FRAMES = 8
MIN_VIDEO_MODEL_OUTPUT_FRAMES = 4
MAX_VIDEO_MODEL_FRAME_STRETCH = 2.0

_ANALYSIS_SIZE = (96, 54)
_PIXEL_DELTA_THRESHOLD = 3
_MEANINGFUL_MAE_THRESHOLD = 0.5
_MEANINGFUL_PIXEL_FRACTION = 0.005
_MAX_FROZEN_PAIR_RATIO = 0.80
_MAX_STATIC_HOLD_SECONDS = 2.0


def describe_video_model_frame_budget(
    *,
    native_frame_count: int,
    output_frame_count: int,
    fps: float,
) -> dict[str, Any]:
    """Describe whether a video-model shot has enough native temporal samples.

    Small native-to-output mismatches can be blended safely. Large mismatches
    would merely slow a short model result across a long authored scene, so the
    renderer rejects them before spending time on model inference.
    """

    native_frames = max(0, int(native_frame_count))
    output_frames = max(0, int(output_frame_count))
    fps_value = max(0.001, float(fps))
    stretch_ratio = (
        float(output_frames) / float(native_frames)
        if native_frames > 0
        else math.inf
    )
    issues: list[str] = []
    if native_frames < MIN_VIDEO_MODEL_NATIVE_FRAMES:
        issues.append("native_frame_count")
    if output_frames < MIN_VIDEO_MODEL_OUTPUT_FRAMES:
        issues.append("output_frame_count")
    if stretch_ratio > MAX_VIDEO_MODEL_FRAME_STRETCH:
        issues.append("frame_stretch_ratio")

    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "native_frame_count": native_frames,
        "output_frame_count": output_frames,
        "native_duration_s": round(native_frames / fps_value, 4),
        "output_duration_s": round(output_frames / fps_value, 4),
        "stretch_ratio": round(stretch_ratio, 4) if math.isfinite(stretch_ratio) else None,
        "minimum_native_frames": MIN_VIDEO_MODEL_NATIVE_FRAMES,
        "minimum_output_frames": MIN_VIDEO_MODEL_OUTPUT_FRAMES,
        "maximum_stretch_ratio": MAX_VIDEO_MODEL_FRAME_STRETCH,
    }


def temporal_blend_frame(
    frames: Sequence[Image.Image],
    *,
    output_index: int,
    output_frame_count: int,
) -> Image.Image:
    """Sample a model sequence without nearest-neighbor still-frame holds."""

    if not frames:
        raise ValueError("At least one generated frame is required.")
    if output_frame_count <= 1 or len(frames) == 1:
        return frames[0].convert("RGB").copy()

    clamped_index = max(0, min(int(output_index), int(output_frame_count) - 1))
    position = (
        float(clamped_index)
        / float(max(1, int(output_frame_count) - 1))
        * float(len(frames) - 1)
    )
    left_index = int(math.floor(position))
    right_index = min(len(frames) - 1, left_index + 1)
    left = frames[left_index].convert("RGB")
    if left_index == right_index:
        return left.copy()
    alpha = float(position - left_index)
    if alpha <= 1e-9:
        return left.copy()
    return Image.blend(left, frames[right_index].convert("RGB"), alpha)


def analyze_motion_images(
    frames: Sequence[Image.Image],
    *,
    fps: float,
    minimum_frames: int = MIN_VIDEO_MODEL_NATIVE_FRAMES,
) -> dict[str, Any]:
    """Measure distributed visible change in an uncompressed frame sequence."""

    fps_value = max(0.001, float(fps))
    normalized = [_analysis_frame(frame) for frame in frames]
    frame_count = len(normalized)
    signatures = [hashlib.sha256(frame.tobytes()).hexdigest() for frame in normalized]

    maes: list[float] = []
    changed_fractions: list[float] = []
    meaningful_indices: list[int] = []
    for index, (previous, current) in enumerate(
        zip(normalized, normalized[1:], strict=False)
    ):
        difference = ImageChops.difference(previous, current)
        histogram = difference.histogram()
        pixel_count = max(1, difference.width * difference.height)
        mae = sum(level * count for level, count in enumerate(histogram)) / pixel_count
        changed_fraction = sum(histogram[_PIXEL_DELTA_THRESHOLD + 1 :]) / pixel_count
        maes.append(float(mae))
        changed_fractions.append(float(changed_fraction))
        if (
            mae >= _MEANINGFUL_MAE_THRESHOLD
            and changed_fraction >= _MEANINGFUL_PIXEL_FRACTION
        ):
            meaningful_indices.append(index)

    pair_count = max(0, frame_count - 1)
    meaningful_count = len(meaningful_indices)
    frozen_pair_count = max(0, pair_count - meaningful_count)
    frozen_pair_ratio = frozen_pair_count / pair_count if pair_count else 1.0
    changed_pair_ratio = meaningful_count / pair_count if pair_count else 0.0
    longest_static_run_frames = _longest_static_run_frames(
        pair_count=pair_count,
        meaningful_indices=meaningful_indices,
    )
    longest_static_hold_s = max(0.0, (longest_static_run_frames - 1) / fps_value)
    covered_quartiles = sorted(
        {
            min(3, int(index * 4 / max(1, pair_count)))
            for index in meaningful_indices
        }
    )

    required_meaningful_pairs = max(3, int(math.ceil(pair_count * 0.25)))
    failures: list[str] = []
    minimum_frame_count = max(2, int(minimum_frames))
    if frame_count < minimum_frame_count:
        failures.append("too_few_frames")
    if len(set(signatures)) < 4:
        failures.append("too_few_unique_frames")
    if meaningful_count < required_meaningful_pairs:
        failures.append("too_few_meaningful_transitions")
    if frame_count >= minimum_frame_count and len(covered_quartiles) < 3:
        failures.append("motion_not_distributed")
    if frozen_pair_ratio > _MAX_FROZEN_PAIR_RATIO:
        failures.append("excessive_freeze_ratio")
    if longest_static_hold_s > _MAX_STATIC_HOLD_SECONDS:
        failures.append("static_hold_too_long")

    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "frame_count": frame_count,
        "perceptually_unique_frames": len(set(signatures)),
        "pair_count": pair_count,
        "meaningful_transition_count": meaningful_count,
        "required_meaningful_transition_count": required_meaningful_pairs,
        "changed_pair_ratio": round(changed_pair_ratio, 6),
        "frozen_pair_ratio": round(frozen_pair_ratio, 6),
        "longest_static_run_frames": longest_static_run_frames,
        "longest_static_hold_s": round(longest_static_hold_s, 4),
        "motion_quartiles": covered_quartiles,
        "mean_adjacent_mae": round(statistics.fmean(maes), 6) if maes else 0.0,
        "median_adjacent_mae": round(statistics.median(maes), 6) if maes else 0.0,
        "max_adjacent_mae": round(max(maes), 6) if maes else 0.0,
        "mean_changed_pixel_fraction": (
            round(statistics.fmean(changed_fractions), 6)
            if changed_fractions
            else 0.0
        ),
        "thresholds": {
            "minimum_frames": minimum_frame_count,
            "minimum_unique_frames": 4,
            "maximum_frozen_pair_ratio": _MAX_FROZEN_PAIR_RATIO,
            "maximum_static_hold_s": _MAX_STATIC_HOLD_SECONDS,
            "minimum_motion_quartiles": 3,
            "meaningful_mae": _MEANINGFUL_MAE_THRESHOLD,
            "meaningful_changed_pixel_fraction": _MEANINGFUL_PIXEL_FRACTION,
        },
    }


def analyze_motion_paths(
    frame_paths: Sequence[Path],
    *,
    fps: float,
    minimum_frames: int = MIN_VIDEO_MODEL_NATIVE_FRAMES,
) -> dict[str, Any]:
    frames: list[Image.Image] = []
    for path in frame_paths:
        with Image.open(path) as image:
            # Retain only the small analysis plane so long renders do not load
            # every full-resolution source frame into memory at once.
            frames.append(_analysis_frame(image))
    return analyze_motion_images(frames, fps=fps, minimum_frames=minimum_frames)


def _analysis_frame(frame: Image.Image) -> Image.Image:
    return frame.convert("L").resize(_ANALYSIS_SIZE, resample=Image.Resampling.BILINEAR)


def _longest_static_run_frames(
    *,
    pair_count: int,
    meaningful_indices: Sequence[int],
) -> int:
    if pair_count <= 0:
        return 1
    meaningful = set(int(index) for index in meaningful_indices)
    current_run = 1
    longest_run = 1
    for pair_index in range(pair_count):
        if pair_index in meaningful:
            current_run = 1
        else:
            current_run += 1
            longest_run = max(longest_run, current_run)
    return longest_run
