from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .deforum_schedule import ScheduleInput, coerce_schedule_pairs, evaluate_schedule


@dataclass(frozen=True)
class DeforumMotionScheduleBundle:
    zoom: tuple[tuple[int, float], ...] = ()
    angle: tuple[tuple[int, float], ...] = ()
    translation_x: tuple[tuple[int, float], ...] = ()
    translation_y: tuple[tuple[int, float], ...] = ()
    strength_schedule: tuple[tuple[int, float], ...] = ()
    cfg_scale_schedule: tuple[tuple[int, float], ...] = ()
    steps_schedule: tuple[tuple[int, float], ...] = ()
    denoise_schedule: tuple[tuple[int, float], ...] = ()

    def has_camera_motion(self) -> bool:
        return bool(self.zoom or self.angle or self.translation_x or self.translation_y)

    def has_diffusion_controls(self) -> bool:
        return bool(
            self.strength_schedule
            or self.cfg_scale_schedule
            or self.steps_schedule
            or self.denoise_schedule
        )


@dataclass(frozen=True)
class DeforumMotionState:
    zoom: float = 1.0
    angle: float = 0.0
    translation_x: float = 0.0
    translation_y: float = 0.0
    strength: float | None = None
    cfg: float | None = None
    steps: float | None = None
    denoise: float | None = None

    def to_renderer_params(self) -> dict[str, float]:
        out: dict[str, float] = {
            "zoom": float(self.zoom),
            "pan_x": float(self.translation_x),
            "pan_y": float(self.translation_y),
            "rotation_deg": float(self.angle),
        }
        if self.strength is not None:
            out["strength"] = float(self.strength)
        if self.cfg is not None:
            out["cfg"] = float(self.cfg)
        if self.steps is not None:
            out["steps"] = float(self.steps)
        if self.denoise is not None:
            out["denoise"] = float(self.denoise)
        return out


def _merge_pairs(*pair_sets: tuple[tuple[int, float], ...]) -> tuple[tuple[int, float], ...]:
    merged: dict[int, float] = {}
    for pairs in pair_sets:
        for frame, value in pairs:
            merged[int(frame)] = float(value)
    return tuple(sorted(merged.items(), key=lambda item: item[0]))


def merge_motion_schedule_bundles(*bundles: DeforumMotionScheduleBundle) -> DeforumMotionScheduleBundle:
    if not bundles:
        return DeforumMotionScheduleBundle()
    return DeforumMotionScheduleBundle(
        zoom=_merge_pairs(*(bundle.zoom for bundle in bundles)),
        angle=_merge_pairs(*(bundle.angle for bundle in bundles)),
        translation_x=_merge_pairs(*(bundle.translation_x for bundle in bundles)),
        translation_y=_merge_pairs(*(bundle.translation_y for bundle in bundles)),
        strength_schedule=_merge_pairs(*(bundle.strength_schedule for bundle in bundles)),
        cfg_scale_schedule=_merge_pairs(*(bundle.cfg_scale_schedule for bundle in bundles)),
        steps_schedule=_merge_pairs(*(bundle.steps_schedule for bundle in bundles)),
        denoise_schedule=_merge_pairs(*(bundle.denoise_schedule for bundle in bundles)),
    )


def motion_bundle_from_mapping(data: dict[str, Any] | None) -> DeforumMotionScheduleBundle:
    source = data if isinstance(data, dict) else {}

    def _pick(*keys: str) -> ScheduleInput:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
        return None

    return DeforumMotionScheduleBundle(
        zoom=tuple(coerce_schedule_pairs(_pick("zoom", "zoom_schedule"))),
        angle=tuple(coerce_schedule_pairs(_pick("angle", "rotation_deg", "rotation_schedule", "rotation_z_schedule"))),
        translation_x=tuple(coerce_schedule_pairs(_pick("translation_x", "pan_x", "pan_x_schedule"))),
        translation_y=tuple(coerce_schedule_pairs(_pick("translation_y", "pan_y", "pan_y_schedule"))),
        strength_schedule=tuple(coerce_schedule_pairs(_pick("strength_schedule", "strength"))),
        cfg_scale_schedule=tuple(coerce_schedule_pairs(_pick("cfg_scale_schedule", "cfg"))),
        steps_schedule=tuple(coerce_schedule_pairs(_pick("steps_schedule", "steps"))),
        denoise_schedule=tuple(coerce_schedule_pairs(_pick("denoise_schedule", "denoise"))),
    )


def _clamp(value: float | None, lo: float, hi: float) -> float | None:
    if value is None:
        return None
    return max(lo, min(hi, float(value)))


def evaluate_motion_state(
    frame_idx: int,
    schedules: DeforumMotionScheduleBundle | dict[str, Any] | None,
    *,
    defaults: dict[str, float] | None = None,
) -> DeforumMotionState:
    bundle = schedules if isinstance(schedules, DeforumMotionScheduleBundle) else motion_bundle_from_mapping(schedules)
    base = dict(defaults or {})

    zoom = evaluate_schedule(bundle.zoom, frame_idx, default=float(base.get("zoom", 1.0)))
    angle = evaluate_schedule(bundle.angle, frame_idx, default=float(base.get("angle", 0.0)))
    tx = evaluate_schedule(bundle.translation_x, frame_idx, default=float(base.get("translation_x", 0.0)))
    ty = evaluate_schedule(bundle.translation_y, frame_idx, default=float(base.get("translation_y", 0.0)))

    strength = _clamp(evaluate_schedule(bundle.strength_schedule, frame_idx, default=base.get("strength")), 0.01, 0.99)
    cfg = _clamp(evaluate_schedule(bundle.cfg_scale_schedule, frame_idx, default=base.get("cfg")), 1.0, 30.0)
    steps = _clamp(evaluate_schedule(bundle.steps_schedule, frame_idx, default=base.get("steps")), 4.0, 80.0)
    denoise = _clamp(evaluate_schedule(bundle.denoise_schedule, frame_idx, default=base.get("denoise")), 0.01, 0.99)

    return DeforumMotionState(
        zoom=float(zoom if zoom is not None else 1.0),
        angle=float(angle if angle is not None else 0.0),
        translation_x=float(tx if tx is not None else 0.0),
        translation_y=float(ty if ty is not None else 0.0),
        strength=strength,
        cfg=cfg,
        steps=steps,
        denoise=denoise,
    )
