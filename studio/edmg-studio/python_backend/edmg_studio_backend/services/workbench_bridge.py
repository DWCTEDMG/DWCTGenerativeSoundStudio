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
    if ":" not in text:
        try:
            number = float(text)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, number) if math.isfinite(number) else 0.0
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
    text = str(schedule or "")
    if len(text) > 65_536:
        raise ValueError("Schedule text exceeds the 65536-character limit")
    parts = text.split(",")
    if len(parts) > 4_096:
        raise ValueError("Schedule contains more than 4096 points")

    points: list[tuple[int, float]] = []
    for part in parts:
        raw = part.strip()
        if not raw:
            continue
        frame_text, separator, value_text = raw.partition(":")
        frame_text = frame_text.strip()
        value_text = value_text.strip()
        if not separator or not frame_text.isdecimal() or len(frame_text) > 12:
            continue
        if value_text.startswith("(") and value_text.endswith(")"):
            value_text = value_text[1:-1].strip()
        elif value_text.startswith("(") or value_text.endswith(")"):
            continue
        if not value_text or len(value_text) > 64:
            continue
        try:
            frame = int(frame_text)
            value = float(value_text)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        points.append((frame, value))
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
    pan_x_points = _parse_schedule_points(str(raw_schedules.get("translation_x") or raw_schedules.get("pan_x") or ""))
    pan_y_points = _parse_schedule_points(str(raw_schedules.get("translation_y") or raw_schedules.get("pan_y") or ""))
    frame_points = sorted(
        {frame for frame, _ in zoom_points}
        | {frame for frame, _ in rot_points}
        | {frame for frame, _ in pan_x_points}
        | {frame for frame, _ in pan_y_points}
    )
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
                "pan_x": _schedule_value(pan_x_points, frame, 0.0),
                "pan_y": _schedule_value(pan_y_points, frame, 0.0),
                "rotation_deg": _schedule_value(rot_points, frame, 0.0),
            }
        )

    if duration_s > 0 and keyframes[-1]["t"] < duration_s:
        last_frame = int(round(duration_s * max(1, fps)))
        keyframes.append(
            {
                "t": duration_s,
                "zoom": _schedule_value(zoom_points, last_frame, keyframes[-1]["zoom"]),
                "pan_x": _schedule_value(pan_x_points, last_frame, keyframes[-1]["pan_x"]),
                "pan_y": _schedule_value(pan_y_points, last_frame, keyframes[-1]["pan_y"]),
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
        "translation_x_schedule": str(schedules.get("translation_x") or ""),
        "translation_y_schedule": str(schedules.get("translation_y") or ""),
        "pan_x_schedule": str(schedules.get("translation_x") or ""),
        "pan_y_schedule": str(schedules.get("translation_y") or ""),
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
        "translation_x_schedule": motion_schedules["translation_x_schedule"],
        "translation_y_schedule": motion_schedules["translation_y_schedule"],
        "pan_x_schedule": motion_schedules["pan_x_schedule"],
        "pan_y_schedule": motion_schedules["pan_y_schedule"],
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
    if duration_s > 0:
        timeline["duration_s"] = duration_s
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


def _slugify(value: Any, default: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or default


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _scene_bounds(scene: dict[str, Any], *, index: int, total: int, duration_s: float) -> tuple[float, float]:
    start_s = max(0.0, _coerce_float(scene.get("start_s")))
    end_s = max(0.0, _coerce_float(scene.get("end_s")))
    if end_s <= start_s:
        return _fallback_scene_timing(index, total, duration_s)
    return start_s, end_s


def _timeline_fps(timeline: dict[str, Any]) -> int:
    render = timeline.get("render") if isinstance(timeline.get("render"), dict) else {}
    return max(1, _coerce_int(render.get("fps_output") or timeline.get("fps_output"), 24))


def _scene_approved(scene: dict[str, Any], index: int, approved_section_ids: set[str]) -> bool:
    candidates = {
        str(scene.get("id") or "").strip(),
        str(scene.get("scene_id") or "").strip(),
        str(index + 1),
        str(_coerce_int(scene.get("id"), index + 1)),
    }
    candidates.discard("")
    if approved_section_ids.intersection(candidates):
        return True
    return bool(scene.get("approved"))


def _repair_actions_for_scene(
    scene: dict[str, Any],
    *,
    index: int,
    repair_suggestions: list[dict[str, Any]],
) -> list[str]:
    actions: list[str] = []
    scene_keys = {
        str(scene.get("id") or "").strip(),
        str(scene.get("scene_id") or "").strip(),
        str(index + 1),
        str(_coerce_int(scene.get("id"), index + 1)),
    }
    scene_keys.discard("")
    for suggestion in repair_suggestions:
        text = str(suggestion.get("action") or suggestion.get("issue") or "").strip()
        if not text:
            continue
        suggestion_keys = {
            str(suggestion.get("sectionId") or "").strip(),
            str(suggestion.get("section_id") or "").strip(),
            str(suggestion.get("sceneId") or "").strip(),
            str(suggestion.get("scene_id") or "").strip(),
        }
        suggestion_keys.discard("")
        if not suggestion_keys or scene_keys.intersection(suggestion_keys):
            if text not in actions:
                actions.append(text)
    return actions


def _engine_hint_for_scene(scene: dict[str, Any], *, approved: bool, render_mode: str, has_reactive_timeline: bool) -> str:
    render_mode_l = str(render_mode or "").strip().lower()
    if "performance" in render_mode_l or "motion" in render_mode_l:
        return "comfyui_motion"
    if approved:
        return "internal"
    if has_reactive_timeline:
        return "deforum_export"
    return "internal"


def build_unreal_bridge_preview(
    project_id: str,
    project_name: str | None,
    analysis: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
    *,
    variant_index: int = 0,
) -> dict[str, Any]:
    source_analysis = analysis if isinstance(analysis, dict) else {}
    source_plan = plan if isinstance(plan, dict) else {}
    source_timeline = timeline if isinstance(timeline, dict) else {}
    variants = source_plan.get("variants") if isinstance(source_plan.get("variants"), list) else []
    diagnostics: list[str] = []
    vi = int(variant_index or 0)
    if vi < 0 or vi >= len(variants):
        diagnostics.append("variant_index_out_of_range")
        vi = 0
    variant = variants[vi] if variants and isinstance(variants[vi], dict) else {}
    scenes = _dict_items(variant.get("scenes"))
    if not scenes:
        diagnostics.append("no_variant_scenes")

    features = source_analysis.get("features") if isinstance(source_analysis.get("features"), dict) else {}
    basic = source_analysis.get("basicInfo") if isinstance(source_analysis.get("basicInfo"), dict) else {}
    fps = _timeline_fps(source_timeline)
    duration_s = max(
        0.0,
        _coerce_float(
            variant.get("duration_s")
            or source_plan.get("duration_s")
            or features.get("duration_s")
            or features.get("duration")
            or basic.get("durationSeconds")
            or basic.get("duration")
        ),
    )
    audio_path = str(
        source_analysis.get("audio_path")
        or source_analysis.get("audioPath")
        or source_analysis.get("source_path")
        or source_analysis.get("path")
        or ""
    ).strip() or None
    bpm = max(
        0.0,
        _coerce_float(
            features.get("bpm")
            or features.get("tempo_bpm")
            or features.get("tempo")
            or basic.get("tempo")
        ),
    )
    beat_times_raw = features.get("beat_times") or features.get("beats") or source_analysis.get("beat_times") or []
    beat_times = sorted(
        max(0.0, _coerce_float(value))
        for value in list(beat_times_raw)
        if isinstance(value, (int, float, str))
    )
    if len(beat_times) > 64:
        diagnostics.append("beat_times_truncated")
        beat_times = beat_times[:64]

    reactive = source_timeline.get("reactive_lab") if isinstance(source_timeline.get("reactive_lab"), dict) else {}
    reactive_sections = _dict_items(reactive.get("sections"))
    cue_events = _dict_items(reactive.get("cue_events"))
    repair_suggestions = _dict_items(reactive.get("repair_suggestions"))
    handoff_manifest = reactive.get("handoff_manifest") if isinstance(reactive.get("handoff_manifest"), dict) else {}
    reactive_metadata = reactive.get("metadata") if isinstance(reactive.get("metadata"), dict) else {}
    approved_section_ids = {
        str(value).strip()
        for value in list(handoff_manifest.get("approvedSectionIds") or [])
        if str(value).strip()
    }
    render_mode = str(reactive_metadata.get("renderMode") or handoff_manifest.get("renderMode") or "").strip()
    schedule_stride = max(
        1,
        _coerce_int(reactive_metadata.get("scheduleStride") or handoff_manifest.get("scheduleStride"), 1),
    )

    sequence_name = f"{_slugify(project_name or project_id, 'edmg')}_MainSequence"
    shots: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    handoff_sections: list[dict[str, Any]] = []
    default_total = max(1, len(scenes))
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("id") or scene.get("scene_id") or f"scene-{index + 1}").strip()
        title = str(scene.get("name") or scene.get("title") or f"Scene {index + 1}").strip() or f"Scene {index + 1}"
        start_s, end_s = _scene_bounds(scene, index=index, total=default_total, duration_s=duration_s or float(default_total))
        start_frame = max(0, int(round(start_s * fps)))
        end_frame = max(start_frame, int(round(end_s * fps)))
        shot_id = f"shot_{index + 1:03d}_{_slugify(scene_id or title, f'scene_{index + 1}')}"
        continuity_note = str(scene.get("continuity_note") or scene.get("continuityNote") or "").strip()
        transition_cue = str(scene.get("transition_cue") or scene.get("transitionCue") or "").strip()
        shot_type = str(scene.get("shot_type") or scene.get("shotType") or "").strip()
        approved = _scene_approved(scene, index, approved_section_ids)

        shots.append(
            {
                "shot_id": shot_id,
                "scene_id": scene_id,
                "title": title,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "prompt": str(scene.get("prompt") or "").strip() or None,
                "continuity_tags": [
                    tag
                    for tag in [continuity_note, transition_cue, "approved" if approved else "draft"]
                    if tag
                ],
                "camera_tags": [tag for tag in [shot_type] if tag],
                "approved": approved,
            }
        )
        markers.append({"label": title, "frame": start_frame, "time_seconds": round(start_s, 4)})
        handoff_sections.append(
            {
                "shot_id": shot_id,
                "scene_id": scene_id,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "prompt": str(scene.get("prompt") or "").strip() or None,
                "negative_prompt": str(scene.get("negative_prompt") or "").strip() or None,
                "continuity_note": continuity_note or None,
                "approved": approved,
                "engine_hint": _engine_hint_for_scene(
                    scene,
                    approved=approved,
                    render_mode=render_mode,
                    has_reactive_timeline=bool(reactive),
                ),
                "repair_actions": _repair_actions_for_scene(scene, index=index, repair_suggestions=repair_suggestions),
            }
        )

    for cue_index, cue_event in enumerate(cue_events):
        cue_time = max(0.0, _coerce_float(cue_event.get("time")))
        cue_frame = max(0, _coerce_int(cue_event.get("frame"), int(round(cue_time * fps))))
        cue_label = str(cue_event.get("cueType") or cue_event.get("label") or f"cue-{cue_index + 1}").strip()
        markers.append({"label": cue_label, "frame": cue_frame, "time_seconds": round(cue_time, 4)})
    markers.sort(key=lambda marker: (marker["frame"], marker["label"]))

    section_events: list[dict[str, Any]] = []
    if reactive_sections:
        for index, section in enumerate(reactive_sections):
            section_id = str(
                section.get("id")
                or section.get("sectionId")
                or section.get("sceneId")
                or section.get("label")
                or f"section-{index + 1}"
            ).strip()
            label = str(section.get("label") or section.get("name") or section_id).strip() or section_id
            time_seconds = max(0.0, _coerce_float(section.get("startTime") or section.get("start_s")))
            has_energy = section.get("avgEnergy") is not None or section.get("energy") is not None
            section_events.append(
                {
                    "section_id": section_id,
                    "label": label,
                    "time_seconds": time_seconds,
                    "energy": _clamp_unit(section.get("avgEnergy") or section.get("energy")) if has_energy else None,
                    "continuity_priority": 1.0 if bool(section.get("approved")) else 0.65,
                }
            )
    else:
        for index, scene in enumerate(scenes):
            scene_id = str(scene.get("id") or scene.get("scene_id") or f"scene-{index + 1}").strip()
            title = str(scene.get("name") or scene.get("title") or scene_id).strip() or scene_id
            start_s, _end_s = _scene_bounds(scene, index=index, total=default_total, duration_s=duration_s or float(default_total))
            section_events.append(
                {
                    "section_id": scene_id,
                    "label": title,
                    "time_seconds": start_s,
                    "energy": None,
                    "continuity_priority": 1.0 if bool(scene.get("approved")) else 0.65,
                }
            )

    preview_cue_events = [
        {
            "cue_id": str(cue.get("id") or f"cue-{index + 1}"),
            "frame": max(0, _coerce_int(cue.get("frame"), 0)),
            "time_seconds": max(0.0, _coerce_float(cue.get("time"))),
            "cue_type": str(cue.get("cueType") or cue.get("type") or "cue").strip() or "cue",
            "instruction": str(cue.get("instruction") or cue.get("action") or "").strip() or None,
        }
        for index, cue in enumerate(cue_events)
    ]

    camera = source_timeline.get("camera") if isinstance(source_timeline.get("camera"), dict) else {}
    camera_keyframes = [deepcopy(frame) for frame in list(camera.get("keyframes") or []) if isinstance(frame, dict)]
    if len(camera_keyframes) > 12:
        diagnostics.append("camera_keyframes_truncated")
        camera_keyframes = camera_keyframes[:12]

    return {
        "project_id": project_id,
        "project_name": project_name,
        "variant_index": vi,
        "source": "studio_project",
        "diagnostics": diagnostics,
        "shot_metadata_export": {
            "engine": "unreal",
            "handoff_kind": "shot_metadata_export",
            "sequence_name": sequence_name,
            "fps": fps,
            "duration_seconds": duration_s,
            "audio_path": audio_path,
            "project_fields": ["project_id", "project_name", "fps", "audio_path"],
            "shot_fields": [
                "shot_id",
                "scene_id",
                "start_frame",
                "end_frame",
                "prompt",
                "continuity_tags",
            ],
            "marker_fields": ["label", "frame", "time_seconds"],
            "shots": shots,
            "markers": markers,
        },
        "render_handoff": {
            "engine": "unreal",
            "handoff_kind": "render_handoff",
            "execution_owner": "external_runtime",
            "return_owner": "studio",
            "render_mode": render_mode,
            "schedule_stride": schedule_stride,
            "approved_section_ids": sorted(approved_section_ids),
            "expected_inputs": ["shot_manifest.json", "audio_markers.json", "style_packet.json"],
            "expected_outputs": ["shot_render.mov", "alpha_pass.mov", "metadata.json"],
            "assembly_mode": "ffmpeg_back_in_studio",
            "sections": handoff_sections,
        },
        "live_control_bridge": {
            "engine": "unreal",
            "handoff_kind": "live_control_bridge",
            "cadence_hz": 30,
            "bpm": bpm,
            "transports": {
                "osc": ["/edmg/section", "/edmg/beat", "/edmg/camera"],
                "websocket": ["section_change", "beat_pulse", "lighting_envelope"],
                "remote_control": ["sequence.PlayRate", "camera.FocalLength", "lights.Intensity"],
            },
            "section_payload_fields": ["section_id", "energy", "continuity_priority"],
            "section_events": section_events,
            "cue_events": preview_cue_events,
            "beat_times": beat_times,
            "camera_keyframes": camera_keyframes,
        },
    }


def build_unreal_bridge_export_payloads(
    *,
    project_id: str,
    project_name: str | None,
    variant_index: int,
    preview: dict[str, Any] | None,
    analysis: dict[str, Any] | None,
    visual_dna: dict[str, Any] | None,
    created_at: str,
) -> dict[str, dict[str, Any]]:
    source_preview = preview if isinstance(preview, dict) else {}
    shot_metadata = deepcopy(source_preview.get("shot_metadata_export") or {})
    render_handoff = deepcopy(source_preview.get("render_handoff") or {})
    live_control = deepcopy(source_preview.get("live_control_bridge") or {})
    source_analysis = analysis if isinstance(analysis, dict) else {}
    source_visual_dna = visual_dna if isinstance(visual_dna, dict) else {}

    features = source_analysis.get("features") if isinstance(source_analysis.get("features"), dict) else {}
    transcript = source_analysis.get("transcript") if isinstance(source_analysis.get("transcript"), dict) else {}
    tags = [
        str(tag).strip()
        for tag in list(source_analysis.get("tags") or [])
        if str(tag).strip()
    ]
    energy_curve = [
        _clamp_unit(value)
        for value in list(features.get("energy_curve") or [])
        if isinstance(value, (int, float))
    ][:128]
    beat_times = [
        max(0.0, _coerce_float(value))
        for value in list(live_control.get("beat_times") or [])
        if isinstance(value, (int, float, str))
    ]

    audio_markers = {
        "project_id": project_id,
        "project_name": project_name,
        "variant_index": int(variant_index or 0),
        "sequence_name": str(shot_metadata.get("sequence_name") or ""),
        "audio_path": str(shot_metadata.get("audio_path") or "") or None,
        "fps": _coerce_int(shot_metadata.get("fps"), 24),
        "bpm": _coerce_float(live_control.get("bpm")),
        "markers": deepcopy(shot_metadata.get("markers") or []),
        "beat_times": beat_times,
        "cue_events": deepcopy(live_control.get("cue_events") or []),
        "section_events": deepcopy(live_control.get("section_events") or []),
    }

    style_packet = {
        "project_id": project_id,
        "project_name": project_name,
        "variant_index": int(variant_index or 0),
        "sequence_name": str(shot_metadata.get("sequence_name") or ""),
        "analysis_context": {
            "tags": tags[:24],
            "transcript": str(transcript.get("text") or "").strip(),
            "tempo_bpm": _coerce_float(
                features.get("bpm") or features.get("tempo_bpm") or features.get("tempo")
            ),
            "musical_key": str(features.get("musical_key") or ""),
            "energy_curve": energy_curve,
        },
        "visual_dna": {
            "identity": deepcopy(source_visual_dna.get("identity") or {}),
            "continuity": deepcopy(source_visual_dna.get("continuity") or {}),
            "prompt_guidance": deepcopy(source_visual_dna.get("prompt_guidance") or {}),
        },
        "render_hints": {
            "render_mode": str(render_handoff.get("render_mode") or ""),
            "approved_section_ids": deepcopy(render_handoff.get("approved_section_ids") or []),
            "assembly_mode": str(render_handoff.get("assembly_mode") or ""),
        },
    }

    return_contract = {
        "project_id": project_id,
        "project_name": project_name,
        "variant_index": int(variant_index or 0),
        "return_owner": str(render_handoff.get("return_owner") or "studio"),
        "assembly_mode": str(render_handoff.get("assembly_mode") or "ffmpeg_back_in_studio"),
        "expected_outputs": deepcopy(render_handoff.get("expected_outputs") or []),
        "unreal_consumer": {
            "repo_relative_script": "studio/edmg-studio/tools/unreal/import_unreal_bridge_bundle.py",
            "default_content_path": "/Game/EDMG/Sequences",
            "default_return_dir": "returned",
        },
        "delivery_notes": [
            "Studio remains the assembly owner for the final mux and output bundle.",
            "Rendered files should preserve scene and shot ordering from shot_manifest.json.",
        ],
    }

    files = [
        {"path": "shot_manifest.json", "kind": "shot_metadata_export"},
        {"path": "audio_markers.json", "kind": "audio_markers"},
        {"path": "style_packet.json", "kind": "style_packet"},
        {"path": "render_handoff.json", "kind": "render_handoff"},
        {"path": "live_control_bridge.json", "kind": "live_control_bridge"},
        {"path": "return_contract.json", "kind": "return_contract"},
    ]
    bundle_manifest = {
        "schema_version": 1,
        "export_family": "unreal_bridge_bundle",
        "created_at": created_at,
        "project_id": project_id,
        "project_name": project_name,
        "variant_index": int(variant_index or 0),
        "sequence_name": str(shot_metadata.get("sequence_name") or ""),
        "files": files,
    }

    return {
        "bundle_manifest.json": bundle_manifest,
        "shot_manifest.json": shot_metadata,
        "audio_markers.json": audio_markers,
        "style_packet.json": style_packet,
        "render_handoff.json": render_handoff,
        "live_control_bridge.json": live_control,
        "return_contract.json": return_contract,
    }
