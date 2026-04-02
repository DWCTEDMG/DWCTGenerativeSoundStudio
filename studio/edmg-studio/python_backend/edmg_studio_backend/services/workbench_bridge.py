from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any


DEFAULT_NEGATIVE_PROMPT = "blurry, low quality, watermark, text, logo"


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clamp_unit(value: Any) -> float:
    number = _coerce_float(value, 0.0)
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _parse_clock(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value or "").strip()
    if not text:
        return 0.0
    if re.fullmatch(r"[-+]?\d*\.?\d+", text):
        return max(0.0, float(text))
    parts = text.split(":")
    try:
        if len(parts) == 2:
            mins = int(parts[0] or 0)
            secs = float(parts[1] or 0.0)
            return max(0.0, mins * 60.0 + secs)
        if len(parts) == 3:
            hours = int(parts[0] or 0)
            mins = int(parts[1] or 0)
            secs = float(parts[2] or 0.0)
            return max(0.0, hours * 3600.0 + mins * 60.0 + secs)
    except Exception:
        return 0.0
    return 0.0


def _approximate_beat_times(duration_s: float, bpm: float) -> list[float]:
    if duration_s <= 0 or bpm <= 0:
        return []
    step = 60.0 / max(1e-6, bpm)
    out: list[float] = []
    current = 0.0
    while current <= duration_s + 1e-6:
        out.append(round(current, 4))
        current += step
    return out


def _combine_text_parts(parts: list[Any]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw in parts:
        if isinstance(raw, list):
            for item in raw:
                text = str(item or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    lines.append(text)
            continue
        text = str(raw or "").strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return "\n".join(lines)


def planner_lab_to_project_analysis(raw_analysis: dict[str, Any] | None) -> dict[str, Any]:
    analysis = raw_analysis if isinstance(raw_analysis, dict) else {}
    basic = analysis.get("basicInfo") if isinstance(analysis.get("basicInfo"), dict) else {}
    spectral = analysis.get("spectralFeatures") if isinstance(analysis.get("spectralFeatures"), dict) else {}
    emotions = analysis.get("emotions") if isinstance(analysis.get("emotions"), list) else []
    themes = analysis.get("themes") if isinstance(analysis.get("themes"), list) else []
    imagery = analysis.get("visualImagery") if isinstance(analysis.get("visualImagery"), list) else []
    duration_s = max(0.0, _coerce_float(basic.get("durationSeconds") or basic.get("duration")))
    bpm = max(0.0, _coerce_float(basic.get("tempo")))
    energy_curve = [_clamp_unit(value) for value in list(analysis.get("energyCurve") or [])]
    beat_times = _approximate_beat_times(duration_s, bpm)

    tags: list[str] = []
    for item in themes:
        if isinstance(item, dict):
            text = str(item.get("theme") or "").strip()
            if text:
                tags.append(text)
    for item in imagery[:6]:
        if isinstance(item, dict):
            text = str(item.get("element") or "").strip()
            if text:
                tags.append(text)
    for item in emotions[:4]:
        if isinstance(item, dict):
            text = str(item.get("emotion") or "").strip()
            if text:
                tags.append(text)

    transcript_text = _combine_text_parts(
        [
            analysis.get("hookLine"),
            analysis.get("narrativeStructure"),
            analysis.get("notes"),
            [item.get("theme") for item in themes if isinstance(item, dict)],
        ]
    )

    return {
        "source": "planner_lab",
        "features": {
            "duration_s": duration_s,
            "duration": duration_s,
            "bpm": bpm,
            "tempo_bpm": bpm,
            "tempo": bpm,
            "beats": beat_times,
            "beat_times": beat_times,
            "energy_curve": energy_curve,
            "energy": energy_curve,
            "brightness": _coerce_float(spectral.get("brightness")),
            "warmth": _coerce_float(spectral.get("warmth")),
            "dynamic_range": _coerce_float(spectral.get("dynamicRange")),
            "zero_crossing_rate": _coerce_float(spectral.get("zeroCrossingRate")),
            "average_energy": _coerce_float(spectral.get("averageEnergy")),
            "motion_bias": _coerce_float(spectral.get("motionBias")),
            "sample_rate": _coerce_int(basic.get("sampleRate")),
            "channels": _coerce_int(basic.get("channels")),
            "musical_key": str(basic.get("key") or ""),
        },
        "transcript": {"text": transcript_text},
        "tags": tags,
    }


def _fallback_scene_timing(index: int, total: int, duration_s: float) -> tuple[float, float]:
    safe_total = max(1, total)
    slice_s = duration_s / safe_total if duration_s > 0 else 1.0
    start_s = max(0.0, float(index) * slice_s)
    end_s = duration_s if index == safe_total - 1 and duration_s > 0 else max(start_s + 0.25, float(index + 1) * slice_s)
    return start_s, end_s


def planner_lab_to_canonical_plan(
    raw_analysis: dict[str, Any] | None,
    raw_plan: dict[str, Any] | None,
    raw_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = raw_analysis if isinstance(raw_analysis, dict) else {}
    plan = raw_plan if isinstance(raw_plan, dict) else {}
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    basic = analysis.get("basicInfo") if isinstance(analysis.get("basicInfo"), dict) else {}
    duration_s = max(0.0, _coerce_float(basic.get("durationSeconds") or basic.get("duration")))
    scene_plan = plan.get("scenePlan") if isinstance(plan.get("scenePlan"), list) else []
    scene_plan_by_id = {
        int(item.get("id")): item
        for item in scene_plan
        if isinstance(item, dict) and isinstance(item.get("id"), (int, float))
    }

    raw_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    scenes: list[dict[str, Any]] = []
    total = len(raw_scenes)
    for index, raw_scene in enumerate(raw_scenes):
        if not isinstance(raw_scene, dict):
            continue
        scene_id = _coerce_int(raw_scene.get("id"), index + 1)
        timing = scene_plan_by_id.get(scene_id, {})
        start_s = _parse_clock(timing.get("startTime"))
        end_s = _parse_clock(timing.get("endTime"))
        if end_s <= start_s:
            start_s, end_s = _fallback_scene_timing(len(scenes), max(1, total), duration_s or float(total))
        scenes.append(
            {
                "id": scene_id,
                "name": str(raw_scene.get("title") or raw_scene.get("name") or f"Scene {scene_id}").strip(),
                "start_s": start_s,
                "end_s": end_s,
                "prompt": str(raw_scene.get("text") or raw_scene.get("prompt") or "").strip(),
                "negative_prompt": str(raw_scene.get("negativePrompt") or raw_scene.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT).strip(),
                "approved": bool(raw_scene.get("approved")),
                "locked": bool(raw_scene.get("locked")),
                "status": str(raw_scene.get("status") or "draft"),
                "rationale": str(raw_scene.get("rationale") or "").strip(),
                "shot_type": str(raw_scene.get("shotType") or timing.get("shotType") or "").strip(),
                "transition_cue": str(raw_scene.get("transitionCue") or timing.get("transitionCue") or "").strip(),
                "continuity_note": str(raw_scene.get("continuityNote") or timing.get("continuityNote") or "").strip(),
                "segment": _coerce_int(raw_scene.get("segment")),
                "score": deepcopy(raw_scene.get("score")) if isinstance(raw_scene.get("score"), dict) else {},
                "prompt_variants": deepcopy(raw_scene.get("variants")) if isinstance(raw_scene.get("variants"), list) else [],
            }
        )

    title = str(plan.get("executiveSummary") or basic.get("fileName") or "Planner Lab Import").strip()
    variant_name = str(settings.get("promptStyle") or "planner-lab").strip() or "planner-lab"

    return {
        "title": title,
        "duration_s": duration_s or max((_coerce_float(scene.get("end_s")) for scene in scenes), default=0.0),
        "source": "planner_lab",
        "planner_lab": {
            "direction": deepcopy(plan.get("direction")) if isinstance(plan.get("direction"), dict) else {},
            "keyword_bank": deepcopy(plan.get("keywordBank")) if isinstance(plan.get("keywordBank"), list) else [],
            "render_manifest": deepcopy(plan.get("renderManifest")) if isinstance(plan.get("renderManifest"), dict) else {},
            "approval_checklist": deepcopy(plan.get("approvalChecklist")) if isinstance(plan.get("approvalChecklist"), list) else [],
            "rerender_suggestions": deepcopy(plan.get("rerenderSuggestions")) if isinstance(plan.get("rerenderSuggestions"), list) else [],
            "repair_passes": deepcopy(plan.get("repairPasses")) if isinstance(plan.get("repairPasses"), list) else [],
            "settings": deepcopy(settings),
        },
        "variants": [
            {
                "index": 0,
                "name": f"Planner Lab / {variant_name}",
                "duration_s": duration_s,
                "scenes": scenes,
                "source": "planner_lab",
            }
        ],
    }


def _parse_schedule_points(schedule: str) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for part in str(schedule or "").split(","):
        raw = part.strip()
        if not raw:
            continue
        match = re.match(r"^(\d+)\s*:\s*\(?\s*([-+]?\d*\.?\d+)\s*\)?$", raw)
        if not match:
            continue
        points.append((int(match.group(1)), float(match.group(2))))
    return sorted(points, key=lambda item: item[0])


def _schedule_value(points: list[tuple[int, float]], frame: int, default: float) -> float:
    if not points:
        return default
    if frame <= points[0][0]:
        return float(points[0][1])
    if frame >= points[-1][0]:
        return float(points[-1][1])
    for index in range(len(points) - 1):
        fa, va = points[index]
        fb, vb = points[index + 1]
        if fa <= frame <= fb:
            if fb <= fa:
                return float(vb)
            weight = float(frame - fa) / float(fb - fa)
            return float(va) * (1.0 - weight) + float(vb) * weight
    return default


def build_reactive_camera_keyframes(schedules: dict[str, Any] | None, *, fps: int, duration_s: float) -> list[dict[str, float]]:
    raw_schedules = schedules if isinstance(schedules, dict) else {}
    zoom_points = _parse_schedule_points(str(raw_schedules.get("zoom") or ""))
    rot_points = _parse_schedule_points(str(raw_schedules.get("rotation_z") or ""))
    frame_points = sorted({frame for frame, _ in zoom_points} | {frame for frame, _ in rot_points})
    if not frame_points:
        if duration_s <= 0:
            return []
        return [{"t": 0.0, "zoom": 1.0, "pan_x": 0.0, "pan_y": 0.0, "rotation_deg": 0.0}]

    keyframes: list[dict[str, float]] = []
    for frame in frame_points:
        keyframes.append(
            {
                "t": max(0.0, float(frame) / float(max(1, fps))),
                "zoom": _schedule_value(zoom_points, frame, 1.0),
                "pan_x": 0.0,
                "pan_y": 0.0,
                "rotation_deg": _schedule_value(rot_points, frame, 0.0),
            }
        )

    if duration_s > 0 and keyframes[-1]["t"] < duration_s:
        last_frame = int(round(duration_s * max(1, fps)))
        keyframes.append(
            {
                "t": duration_s,
                "zoom": _schedule_value(zoom_points, last_frame, keyframes[-1]["zoom"]),
                "pan_x": 0.0,
                "pan_y": 0.0,
                "rotation_deg": _schedule_value(rot_points, last_frame, keyframes[-1]["rotation_deg"]),
            }
        )
    return keyframes


def _reactive_duration(payload: dict[str, Any]) -> float:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    keyframes = payload.get("keyframes") if isinstance(payload.get("keyframes"), list) else []
    fps = max(1, _coerce_int(metadata.get("fps"), 24))
    total_frames = max(0, _coerce_int(metadata.get("totalFrames"), 0))
    end_points = [
        _coerce_float(section.get("endTime"))
        for section in sections
        if isinstance(section, dict)
    ]
    time_points = [
        _coerce_float(frame.get("time"))
        for frame in keyframes
        if isinstance(frame, dict)
    ]
    return max([0.0, *end_points, *time_points, (float(total_frames - 1) / float(fps)) if total_frames > 0 else 0.0])


def _upsert_track(
    tracks: list[dict[str, Any]],
    *,
    track_id: str,
    track_name: str,
    track_type: str,
    clips: list[dict[str, Any]],
    overwrite: bool,
) -> list[dict[str, Any]]:
    next_tracks = [deepcopy(track) for track in tracks if isinstance(track, dict)]
    existing_index = next(
        (
            index
            for index, track in enumerate(next_tracks)
            if str(track.get("id") or "") == track_id
            or str(track.get("type") or "").lower() == track_type.lower()
        ),
        -1,
    )
    next_track = {"id": track_id, "name": track_name, "type": track_type, "clips": clips}
    if existing_index >= 0:
        if overwrite or not next_tracks[existing_index].get("clips"):
            next_tracks[existing_index] = {**next_tracks[existing_index], **next_track}
    else:
        next_tracks.append(next_track)
    return next_tracks


def merge_reactive_lab_into_timeline(
    base_timeline: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    *,
    overwrite_motion_track: bool = True,
    overwrite_camera: bool = True,
) -> dict[str, Any]:
    source_timeline = base_timeline if isinstance(base_timeline, dict) else {}
    source_payload = payload if isinstance(payload, dict) else {}
    metadata = source_payload.get("metadata") if isinstance(source_payload.get("metadata"), dict) else {}
    schedules = source_payload.get("schedules") if isinstance(source_payload.get("schedules"), dict) else {}
    handoff_manifest = source_payload.get("handoff_manifest") if isinstance(source_payload.get("handoff_manifest"), dict) else {}
    sections = source_payload.get("sections") if isinstance(source_payload.get("sections"), list) else []
    cue_events = source_payload.get("cue_events") if isinstance(source_payload.get("cue_events"), list) else []
    repair_suggestions = source_payload.get("repair_suggestions") if isinstance(source_payload.get("repair_suggestions"), list) else []
    fps = max(1, _coerce_int(metadata.get("fps"), 24))
    duration_s = _reactive_duration(source_payload)

    motion_schedules = {
        "zoom_schedule": str(schedules.get("zoom") or ""),
        "rotation_y_schedule": str(schedules.get("rotation_y") or ""),
        "rotation_schedule": str(schedules.get("rotation_z") or ""),
        "rotation_z_schedule": str(schedules.get("rotation_z") or ""),
        "translation_z_schedule": str(schedules.get("translation_z") or ""),
        "strength_schedule": str(schedules.get("strength") or ""),
        "cfg_scale_schedule": str(schedules.get("cfg_scale") or ""),
        "brightness_schedule": str(schedules.get("brightness") or ""),
    }

    motion_data = {
        "motion_schedules": motion_schedules,
        "strength_schedule": motion_schedules["strength_schedule"],
        "cfg_scale_schedule": motion_schedules["cfg_scale_schedule"],
        "zoom_schedule": motion_schedules["zoom_schedule"],
        "rotation_schedule": motion_schedules["rotation_schedule"],
        "rotation_y_schedule": motion_schedules["rotation_y_schedule"],
        "translation_z_schedule": motion_schedules["translation_z_schedule"],
        "brightness_schedule": motion_schedules["brightness_schedule"],
        "render_mode": str(metadata.get("renderMode") or handoff_manifest.get("renderMode") or ""),
        "schedule_stride": _coerce_int(metadata.get("scheduleStride") or handoff_manifest.get("scheduleStride"), 1),
        "approved_section_ids": deepcopy(handoff_manifest.get("approvedSectionIds")) if isinstance(handoff_manifest.get("approvedSectionIds"), list) else [],
        "cue_events": deepcopy(cue_events),
        "repair_suggestions": deepcopy(repair_suggestions),
    }

    motion_clip = {
        "id": "edmg_reactive_motion_0",
        "start_s": 0.0,
        "end_s": duration_s or max(1.0, float(len(sections) or 1)),
        "data": motion_data,
    }

    timeline = deepcopy(source_timeline)
    tracks = timeline.get("tracks") if isinstance(timeline.get("tracks"), list) else []
    timeline["tracks"] = _upsert_track(
        tracks,
        track_id="edmg_motion",
        track_name="EDMG Motion",
        track_type="motion",
        clips=[motion_clip],
        overwrite=overwrite_motion_track,
    )

    render_settings = timeline.get("render") if isinstance(timeline.get("render"), dict) else {}
    timeline["render"] = {**render_settings, "fps_output": fps}
    timeline["fps_output"] = fps

    existing_camera = timeline.get("camera") if isinstance(timeline.get("camera"), dict) else {}
    existing_keyframes = existing_camera.get("keyframes") if isinstance(existing_camera.get("keyframes"), list) else []
    reactive_keyframes = build_reactive_camera_keyframes(schedules, fps=fps, duration_s=duration_s)
    if overwrite_camera or not existing_keyframes:
        timeline["camera"] = {**existing_camera, "keyframes": reactive_keyframes}

    timeline["reactive_lab"] = {
        "metadata": deepcopy(metadata),
        "sections": deepcopy(sections),
        "cue_events": deepcopy(cue_events),
        "repair_suggestions": deepcopy(repair_suggestions),
        "handoff_manifest": deepcopy(handoff_manifest),
    }
    return timeline
