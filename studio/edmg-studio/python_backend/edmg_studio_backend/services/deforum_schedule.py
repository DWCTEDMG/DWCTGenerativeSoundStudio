from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

ScheduleInput = str | int | float | Mapping[int | str, Any] | Iterable[tuple[int | str, Any]] | None

_SCHEDULE_RE = re.compile(r"^(-?\d+)\s*:\s*\(?\s*([-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*\)?$")


def coerce_schedule_pairs(schedule: ScheduleInput) -> list[tuple[int, float]]:
    """Normalize Deforum-style schedule inputs into sorted (frame, value) pairs."""
    raw_pairs: list[tuple[Any, Any]] = []

    if schedule is None:
        return []

    if isinstance(schedule, (int, float)):
        raw_pairs.append((0, schedule))
    elif isinstance(schedule, str):
        for part in schedule.split(","):
            part = part.strip()
            if not part:
                continue
            match = _SCHEDULE_RE.match(part)
            if not match:
                continue
            raw_pairs.append((match.group(1), match.group(2)))
    elif isinstance(schedule, Mapping):
        raw_pairs.extend(schedule.items())
    else:
        for item in schedule:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            raw_pairs.append((item[0], item[1]))

    dedup: dict[int, float] = {}
    for raw_frame, raw_value in raw_pairs:
        try:
            frame = max(0, int(raw_frame))
            value = float(raw_value)
        except Exception:
            continue
        if not math.isfinite(value):
            continue
        dedup[frame] = value
    return sorted(dedup.items(), key=lambda item: item[0])


def evaluate_schedule(schedule: ScheduleInput, frame_idx: int, default: float | None = None) -> float | None:
    """Evaluate a numeric schedule with linear interpolation between keyframes."""
    pairs = coerce_schedule_pairs(schedule)
    if not pairs:
        return default

    frame = int(frame_idx)
    if frame <= pairs[0][0]:
        return float(pairs[0][1])
    if frame >= pairs[-1][0]:
        return float(pairs[-1][1])

    for index in range(len(pairs) - 1):
        left_frame, left_value = pairs[index]
        right_frame, right_value = pairs[index + 1]
        if left_frame <= frame <= right_frame:
            weight = (frame - left_frame) / max(1e-9, float(right_frame - left_frame))
            return float(left_value) * (1.0 - weight) + float(right_value) * weight

    return float(pairs[-1][1])
