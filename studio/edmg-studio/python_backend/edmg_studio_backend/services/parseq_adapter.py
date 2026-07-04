from __future__ import annotations

import math
from typing import Any

from .deforum_normalize import DEFAULT_NEGATIVE_PROMPT, render_prompt_from_scene
from .deforum_schedule import coerce_schedule_pairs


_DEFORUM_FIELD_MAP: dict[str, str] = {
    "zoom": "deforum_zoom",
    "angle": "deforum_angle",
    "rotation_z": "deforum_angle",
    "translation_x": "deforum_translation_x",
    "translation_y": "deforum_translation_y",
    "translation_z": "deforum_translation_z",
    "rotation_3d_x": "deforum_rotation_3d_x",
    "rotation_3d_y": "deforum_rotation_3d_y",
    "rotation_3d_z": "deforum_rotation_3d_z",
    "fov": "deforum_fov",
    "strength": "deforum_strength_schedule",
    "strength_schedule": "deforum_strength_schedule",
    "cfg": "deforum_cfg_scale_schedule",
    "cfg_scale": "deforum_cfg_scale_schedule",
    "cfg_scale_schedule": "deforum_cfg_scale_schedule",
    "steps": "deforum_steps_schedule",
    "steps_schedule": "deforum_steps_schedule",
    "denoise": "deforum_denoise_schedule",
    "denoise_schedule": "deforum_denoise_schedule",
}

_VIDEO_FIELD_MAP: dict[str, str] = {
    "motion_score": "video_model_motion_score_schedule",
    "video_model_motion_score": "video_model_motion_score_schedule",
    "noise_aug": "video_model_noise_aug_schedule",
    "noise_aug_strength": "video_model_noise_aug_schedule",
    "video_model_noise_aug_strength": "video_model_noise_aug_schedule",
    "anchor_strength": "anchor_strength_schedule",
}


def _finite_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    return out if math.isfinite(out) else float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _frame(seconds: Any, fps: int) -> int:
    return max(0, int(round(_finite_float(seconds, 0.0) * float(max(1, fps)))))


def _schedule_string(pairs: list[tuple[int, float]]) -> str:
    dedup: dict[int, float] = {}
    for frame, value in pairs:
        dedup[max(0, int(frame))] = float(value)
    return ", ".join(f"{frame}:({value:.4f})" for frame, value in sorted(dedup.items()))


def _schedule_from_manifest_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    pairs = coerce_schedule_pairs(value)
    if not pairs:
        return None
    return _schedule_string([(frame, val) for frame, val in pairs])


def _analysis_features(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    features = analysis.get("features")
    return features if isinstance(features, dict) else {}


def _scene_energy(scene: dict[str, Any], index: int, features: dict[str, Any]) -> float:
    for key in ("energy", "energy_score", "avgEnergy", "avg_energy"):
        if scene.get(key) is not None:
            return _clamp(_finite_float(scene.get(key), 0.5), 0.0, 1.0)
    curve = features.get("energy_curve")
    if isinstance(curve, list) and curve:
        return _clamp(_finite_float(curve[min(index, len(curve) - 1)], 0.5), 0.0, 1.0)
    return _clamp(_finite_float(features.get("energy"), 0.5), 0.0, 1.0)


def _scene_peak(scene: dict[str, Any], energy: float, features: dict[str, Any]) -> float:
    for key in ("peak_energy", "peak", "maxEnergy", "max_energy"):
        if scene.get(key) is not None:
            return _clamp(_finite_float(scene.get(key), energy), 0.0, 1.0)
    return _clamp(max(energy, _finite_float(features.get("onset_density"), energy)), 0.0, 1.0)


def build_parseq_manifest(
    *,
    variant: dict[str, Any],
    analysis: dict[str, Any] | None,
    fps: int,
    duration_s: float,
) -> dict[str, Any]:
    """Build a Studio-native Parseq-compatible motion document.

    The format intentionally stays plain JSON: schedules are Deforum-style
    strings, while keyframes carry the editable source values Studio used to
    generate those schedules.
    """
    fps = max(1, int(fps or 24))
    duration_s = max(0.5, float(duration_s or 0.5))
    features = _analysis_features(analysis)
    bpm = _finite_float(features.get("bpm"), _finite_float(variant.get("bpm"), 120.0))
    scenes = [scene for scene in list(variant.get("scenes") or []) if isinstance(scene, dict)]
    if not scenes:
        scenes = [{"start_s": 0.0, "end_s": duration_s, "prompt": render_prompt_from_scene({})}]

    schedules: dict[str, list[tuple[int, float]]] = {
        "zoom": [],
        "translation_x": [],
        "translation_y": [],
        "translation_z": [],
        "rotation_3d_y": [],
        "rotation_3d_z": [],
        "strength": [],
        "cfg_scale": [],
        "steps": [],
        "denoise": [],
        "motion_score": [],
        "noise_aug_strength": [],
        "anchor_strength": [],
    }
    prompts: dict[str, str] = {}
    negative_prompts: dict[str, str] = {}
    keyframes: list[dict[str, Any]] = []

    for index, scene in enumerate(scenes):
        start_s = _finite_float(scene.get("start_s"), index * duration_s / max(1, len(scenes)))
        end_s = _finite_float(scene.get("end_s"), start_s + max(1.0, duration_s / max(1, len(scenes))))
        start_s = _clamp(start_s, 0.0, duration_s)
        end_s = _clamp(max(start_s + (1.0 / fps), end_s), start_s + (1.0 / fps), duration_s)
        frame = _frame(start_s, fps)
        energy = _scene_energy(scene, index, features)
        peak = _scene_peak(scene, energy, features)
        direction = -1.0 if index % 2 else 1.0
        prompt = render_prompt_from_scene(scene, fallback="cinematic music-video scene")
        negative = str(scene.get("negative_prompt") or scene.get("negativePrompt") or "").strip()

        motion_score = _clamp(1.0 + ((energy * 0.72) + (peak * 0.28)) * 6.0, 1.0, 7.0)
        zoom = 1.0 + energy * 0.16
        pan_x = direction * energy * 24.0
        pan_y = (peak - 0.5) * 14.0
        dolly = -energy * 18.0
        yaw = direction * energy * 5.0
        roll = direction * peak * 1.25
        strength = _clamp(0.32 + energy * 0.26, 0.25, 0.72)
        denoise = _clamp(0.28 + peak * 0.22, 0.22, 0.62)
        cfg = _clamp(6.0 + energy * 2.0, 5.0, 9.5)
        steps = _clamp(10.0 + peak * 10.0, 8.0, 28.0)
        noise_aug = _clamp(0.015 + energy * 0.075, 0.0, 0.12)
        anchor_strength = _clamp(0.16 + (1.0 - energy) * 0.16, 0.12, 0.36)

        schedules["zoom"].append((frame, zoom))
        schedules["translation_x"].append((frame, pan_x))
        schedules["translation_y"].append((frame, pan_y))
        schedules["translation_z"].append((frame, dolly))
        schedules["rotation_3d_y"].append((frame, yaw))
        schedules["rotation_3d_z"].append((frame, roll))
        schedules["strength"].append((frame, strength))
        schedules["cfg_scale"].append((frame, cfg))
        schedules["steps"].append((frame, steps))
        schedules["denoise"].append((frame, denoise))
        schedules["motion_score"].append((frame, motion_score))
        schedules["noise_aug_strength"].append((frame, noise_aug))
        schedules["anchor_strength"].append((frame, anchor_strength))
        prompts[str(frame)] = prompt
        if negative:
            negative_prompts[str(frame)] = negative
        keyframes.append(
            {
                "frame": frame,
                "time_s": round(start_s, 3),
                "label": str(scene.get("name") or scene.get("title") or f"Scene {index + 1}"),
                "energy": round(energy, 4),
                "peak_energy": round(peak, 4),
                "prompt": prompt,
                "motion_score": round(motion_score, 4),
                "noise_aug_strength": round(noise_aug, 4),
                "anchor_strength": round(anchor_strength, 4),
            }
        )

    end_frame = _frame(duration_s, fps)
    if end_frame > 0:
        for field, pairs in schedules.items():
            if pairs and pairs[-1][0] < end_frame:
                pairs.append((end_frame, pairs[-1][1]))

    return {
        "format": "edmg_parseq_motion_manifest",
        "version": 1,
        "source": "studio",
        "fps": fps,
        "bpm": round(bpm, 3),
        "duration_s": round(duration_s, 3),
        "max_frames": end_frame,
        "managed_fields": sorted(schedules.keys()),
        "keyframes": keyframes,
        "prompts": prompts,
        "negative_prompts": negative_prompts,
        "schedules": {field: _schedule_string(pairs) for field, pairs in schedules.items() if pairs},
    }


def _schedules_from_keyframes(keyframes: Any) -> dict[str, str]:
    if not isinstance(keyframes, list):
        return {}
    field_pairs: dict[str, list[tuple[int, float]]] = {}
    for item in keyframes:
        if not isinstance(item, dict):
            continue
        try:
            frame = max(0, int(item.get("frame")))
        except Exception:
            continue
        for field in set(_DEFORUM_FIELD_MAP) | set(_VIDEO_FIELD_MAP):
            if item.get(field) is None:
                continue
            try:
                value = float(item.get(field))
            except Exception:
                continue
            field_pairs.setdefault(field, []).append((frame, value))
    return {field: _schedule_string(pairs) for field, pairs in field_pairs.items() if pairs}


def parseq_manifest_to_internal_overrides(manifest: dict[str, Any] | None) -> dict[str, Any]:
    source = manifest if isinstance(manifest, dict) else {}
    schedules: dict[str, Any] = {}
    for key in ("schedules", "deforum", "motion_schedules"):
        raw = source.get(key)
        if isinstance(raw, dict):
            schedules.update(raw)
    schedules.update({k: v for k, v in _schedules_from_keyframes(source.get("keyframes")).items() if k not in schedules})

    overrides: dict[str, Any] = {}
    diagnostics: list[str] = []
    for source_field, target_field in {**_DEFORUM_FIELD_MAP, **_VIDEO_FIELD_MAP}.items():
        if source_field not in schedules:
            continue
        schedule = _schedule_from_manifest_value(schedules.get(source_field))
        if schedule:
            overrides[target_field] = schedule
        else:
            diagnostics.append(f"ignored_empty_schedule:{source_field}")

    prompts = source.get("prompts")
    if isinstance(prompts, dict) and prompts:
        overrides["deforum_prompts"] = {str(k): str(v) for k, v in prompts.items() if str(v).strip()}
    else:
        prompt_pairs: dict[str, str] = {}
        for item in source.get("keyframes") or []:
            if not isinstance(item, dict) or not item.get("prompt"):
                continue
            try:
                frame = max(0, int(item.get("frame")))
            except Exception:
                continue
            prompt_pairs[str(frame)] = str(item.get("prompt") or "")
        if prompt_pairs:
            overrides["deforum_prompts"] = prompt_pairs

    negative_prompts = source.get("negative_prompts")
    if isinstance(negative_prompts, dict) and negative_prompts:
        overrides["deforum_negative_prompts"] = {
            str(k): str(v) for k, v in negative_prompts.items() if str(v).strip()
        }

    schedule_count = len([key for key in overrides if key not in {"deforum_prompts", "deforum_negative_prompts"}])
    return {
        "ok": True,
        "overrides": overrides,
        "summary": {
            "format": str(source.get("format") or "parseq"),
            "fps": int(_finite_float(source.get("fps"), 24)),
            "bpm": _finite_float(source.get("bpm"), 0.0) or None,
            "duration_s": _finite_float(source.get("duration_s"), 0.0) or None,
            "keyframes": len(source.get("keyframes") or []),
            "schedules": schedule_count,
            "prompts": len(overrides.get("deforum_prompts") or {}),
            "diagnostics": diagnostics,
        },
    }


def build_render_recipe_graph(
    *,
    manifest: dict[str, Any] | None,
    internal_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = internal_request if isinstance(internal_request, dict) else {}
    parseq = parseq_manifest_to_internal_overrides(manifest)
    keyframe_renderer = str(request.get("video_model_keyframe_renderer") or "internal")
    motion_engine = str(request.get("video_model_engine") or "auto")
    temporal_mode = str(request.get("temporal_mode") or "frame_img2img")
    nodes = [
        {"id": "analysis", "label": "Analysis + transcript", "type": "input"},
        {"id": "storyboard", "label": "Storyboard prompts", "type": "planner"},
        {
            "id": "motion_sequencer",
            "label": "Parseq-style motion sequencer",
            "type": "schedule",
            "schedules": int((parseq.get("summary") or {}).get("schedules") or 0),
        },
        {
            "id": "anchors",
            "label": "Storyboard anchors",
            "type": "image_generator",
            "engine": "TensorRT SD1.5" if keyframe_renderer == "tensorrt_sd15" else "Internal diffusion",
        },
        {
            "id": "motion",
            "label": "Full-motion adapter",
            "type": "video_model" if temporal_mode == "video_model" else "temporal_renderer",
            "engine": motion_engine,
        },
        {"id": "interpolation", "label": "FPS interpolation", "type": "post"},
        {"id": "mux", "label": "Audio mux + final MP4", "type": "output"},
    ]
    edges = [
        {"from": "analysis", "to": "storyboard"},
        {"from": "analysis", "to": "motion_sequencer"},
        {"from": "storyboard", "to": "anchors"},
        {"from": "motion_sequencer", "to": "anchors"},
        {"from": "anchors", "to": "motion"},
        {"from": "motion_sequencer", "to": "motion"},
        {"from": "motion", "to": "interpolation"},
        {"from": "interpolation", "to": "mux"},
    ]
    return {
        "version": 1,
        "source": "studio_native",
        "nodes": nodes,
        "edges": edges,
        "summary": (
            "Transcript/storyboard prompts generate anchors; Parseq-style schedules drive camera, diffusion controls, "
            "motion score, noise augmentation, and anchor blending before interpolation and mux."
        ),
    }
