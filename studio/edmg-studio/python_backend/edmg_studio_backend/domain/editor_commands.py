"""Persistent timeline transactions shared by native and browser editors.

Legacy JSON fields remain intact; exact sample fields supplement the render-facing
seconds projection. No command reads, writes or deletes the referenced media.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from fractions import Fraction
from uuid import NAMESPACE_URL, uuid4, uuid5

from .project_time import ProjectClock, int64, nearest

HISTORY_LIMIT = 200
RECEIPT_LIMIT = 2048

CLIP_PROPERTY_FIELDS = {
    "name",
    "prompt",
    "negative_prompt",
    "source_in_s",
    "source_out_s",
    "speed",
    "volume",
    "fade_in_s",
    "fade_out_s",
    "muted",
    "opacity",
    "blend_mode",
}
CAMERA_FIELDS = {
    "t",
    "zoom",
    "pan_x",
    "pan_y",
    "pan_z",
    "rotation_deg",
    "pitch",
    "yaw",
    "roll",
    "easing",
}
MODULATION_FIELDS = {
    "strength_schedule",
    "cfg_scale_schedule",
    "steps_schedule",
    "zoom_schedule",
    "rotation_schedule",
    "rotation_y_schedule",
    "translation_x_schedule",
    "translation_y_schedule",
    "translation_z_schedule",
    "pan_x_schedule",
    "pan_y_schedule",
    "brightness_schedule",
}


class EditorConflict(ValueError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def normalize_timeline(source: dict, baseline: dict | None = None) -> dict:
    if not isinstance(source, dict):
        raise ValueError("Timeline must be an object")
    result = deepcopy(source)
    if baseline and "timebase" not in result and "timebase" in baseline:
        result["timebase"] = deepcopy(baseline["timebase"])
    clock = ProjectClock.from_timeline(result)
    if baseline and clock.sample_rate != ProjectClock.from_timeline(baseline).sample_rate:
        raise ValueError("Changing the project sample rate requires an explicit timeline rebase")
    result["timebase"] = clock.to_dict()
    result["editor_version"] = 1
    tracks = result.setdefault("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("Timeline tracks must be an array")
    previous = {
        c.get("id"): c for t in (baseline or {}).get("tracks", []) for c in t.get("clips", [])
    }
    ids: set[str] = set()
    for ti, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise ValueError("Track must be an object")
        track.setdefault("id", str(uuid5(NAMESPACE_URL, f"edmg:track:{ti}")))
        _unique_id(track["id"], ids)
        clips = track.setdefault("clips", [])
        if not isinstance(clips, list):
            raise ValueError("Track clips must be an array")
        for ci, clip in enumerate(clips):
            if not isinstance(clip, dict):
                raise ValueError("Clip must be an object")
            clip.setdefault("id", str(uuid5(NAMESPACE_URL, f"edmg:clip:{track['id']}:{ci}")))
            _unique_id(clip["id"], ids)
            old = previous.get(clip["id"], {})
            for seconds_key, sample_key in (("start_s", "start_sample"), ("end_s", "end_sample")):
                # Legacy clients edit seconds; retain exact values if its projection is unchanged.
                changed = seconds_key in clip and clip.get(seconds_key) != old.get(seconds_key)
                if baseline and not changed and sample_key not in clip and sample_key in old:
                    position = int64(old[sample_key])
                elif sample_key in clip and (
                    not baseline or not changed or clip.get(sample_key) != old.get(sample_key)
                ):
                    position = int64(clip[sample_key])
                else:
                    position = clock.samples(clip.get(seconds_key, 0))
                if position < 0:
                    raise ValueError("Timeline clips cannot start or end before zero")
                clip[sample_key] = str(position)
                clip[seconds_key] = float(clock.seconds(position))
            if int(clip["end_sample"]) < int(clip["start_sample"]):
                raise ValueError("Clip end precedes its start")
            data = clip.get("data") if isinstance(clip.get("data"), dict) else clip
            old_data = old.get("data") if isinstance(old.get("data"), dict) else old
            for seconds_key, sample_key, remainder_key in (
                ("source_in_s", "source_offset_sample", "source_offset_remainder"),
                ("source_out_s", "source_end_sample", "source_end_remainder"),
            ):
                seconds_changed = seconds_key in data and data.get(seconds_key) != old_data.get(seconds_key)
                exact_missing = seconds_key in data and sample_key not in data
                # Replacement clients edit seconds; if they changed, regenerate exact
                # metadata even when a queued snapshot still carries an older sample.
                exact_stale = bool(baseline and sample_key in data and seconds_changed)
                if exact_missing or exact_stale:
                    rate = int64(data.get("source_sample_rate", clock.sample_rate))
                    if rate <= 0:
                        raise ValueError("Source sample rate must be positive")
                    exact = Fraction(str(data[seconds_key])) * rate
                    rounded = int64(nearest(exact))
                    data[sample_key], data[remainder_key] = str(rounded), str(exact - rounded)
    return result


def _unique_id(value: object, seen: set[str]) -> None:
    if not isinstance(value, str) or not value or value in seen:
        raise ValueError("Track and clip IDs must be nonempty and unique")
    seen.add(value)


def history_state(meta: dict) -> dict:
    history = meta.get("editor_history") or {}
    undo, redo = history.get("undo", []), history.get("redo", [])
    actual = digest(meta.get("timeline") or {})
    valid = history.get("head", actual) == actual
    return {
        "can_undo": bool(undo) and valid,
        "can_redo": bool(redo) and valid,
        "undo_label": undo[-1]["label"] if undo and valid else None,
        "redo_label": redo[-1]["label"] if redo and valid else None,
        "external_change": not valid,
    }


def _changes(before: object, after: object, path: tuple = ()) -> tuple[list, list]:
    """Store field deltas, rather than 200 copies of a large timeline."""
    undo, redo = [], []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            child = (*path, key)
            if key not in before:
                undo.append({"path": child, "remove": True})
                redo.append({"path": child, "value": deepcopy(after[key])})
            elif key not in after:
                undo.append({"path": child, "value": deepcopy(before[key])})
                redo.append({"path": child, "remove": True})
            else:
                u, r = _changes(before[key], after[key], child)
                undo.extend(u)
                redo.extend(r)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (old, new) in enumerate(zip(before, after, strict=True)):
            u, r = _changes(old, new, (*path, index))
            undo.extend(u)
            redo.extend(r)
    elif before != after:
        undo.append({"path": path, "value": deepcopy(before)})
        redo.append({"path": path, "value": deepcopy(after)})
    return undo, redo


def _apply_changes(source: dict, changes: list) -> dict:
    result = deepcopy(source)
    for change in changes:
        path = change["path"]
        if not path:
            result = deepcopy(change["value"])
            continue
        target = result
        for key in path[:-1]:
            target = target[key]
        if change.get("remove"):
            del target[path[-1]]
        else:
            target[path[-1]] = deepcopy(change["value"])
    return result


def execute(meta: dict, command: dict) -> None:
    """Mutate a store transaction's private project; caller commits atomically."""
    before = deepcopy(meta.get("timeline") or {})
    history = deepcopy(meta.get("editor_history") or {"undo": [], "redo": [], "receipts": {}})
    operation_id = command["operation_id"]
    fingerprint = digest({k: v for k, v in command.items() if k != "expected_revision"})
    if operation_id in history["receipts"]:
        if history["receipts"][operation_id] != fingerprint:
            raise EditorConflict("Operation ID was already used for a different command")
        raise EditorConflict("Operation already committed; reload the current editor state")
    action = command["action"]
    if history.get("head", digest(before)) != digest(before):
        if action in {"undo", "redo"}:
            raise EditorConflict("Timeline changed outside command history; reload before editing")
        history["undo"], history["redo"] = [], []
    if action in {"undo", "redo"}:
        source, target = ("undo", "redo") if action == "undo" else ("redo", "undo")
        if not history[source]:
            raise ValueError(f"Nothing to {action}")
        entry = history[source].pop()
        after = _apply_changes(before, entry[action])
        history[target].append(entry)
    else:
        after = normalize_timeline(before)
        if action == "replace":
            proposed = command.get("timeline")
            if not isinstance(proposed, dict):
                raise ValueError("Replacement requires a timeline")
            after = normalize_timeline(proposed, normalize_timeline(before))
            _preserve_locked(normalize_timeline(before), after)
        else:
            operations = command.get("operations") or []
            if not 1 <= len(operations) <= 200:
                raise ValueError("An edit requires between 1 and 200 operations")
            for operation in operations:
                _edit(after, operation)
            after = normalize_timeline(after)
        undo, redo = _changes(before, after)
        if redo:
            history["undo"].append(
                {"label": command.get("label") or action, "undo": undo, "redo": redo}
            )
            history["redo"] = []
        history["undo"] = history["undo"][-HISTORY_LIMIT:]
    history["head"] = digest(after)
    history["receipts"][operation_id] = fingerprint
    history["receipts"] = dict(list(history["receipts"].items())[-RECEIPT_LIMIT:])
    meta["timeline"], meta["editor_history"] = after, history


def _preserve_locked(before: dict, after: dict) -> None:
    before_camera = before.get("camera") or {}
    after_camera = after.get("camera") or {}
    if before_camera.get("locked") and after_camera != before_camera:
        if after_camera.get("locked") is not False or {**after_camera, "locked": True} != before_camera:
            raise ValueError("Unlock the camera lane before editing it")
    candidates = {t.get("id"): t for t in after.get("tracks", [])}
    for track in before.get("tracks", []):
        replacement = candidates.get(track.get("id"))
        if track.get("locked") and replacement != track:
            # Explicit unlock is legal; editing any other field while locked is not.
            if replacement is None or {**replacement, "locked": True} != track:
                raise ValueError("Unlock the track before editing it")
        clips = {c.get("id"): c for c in (replacement or {}).get("clips", [])}
        for clip in track.get("clips", []):
            new = clips.get(clip.get("id"))
            if (
                clip.get("locked")
                and new != clip
                and (new is None or {**new, "locked": True} != clip)
            ):
                raise ValueError("Unlock the clip before editing it")


def _edit(timeline: dict, op: dict) -> None:
    kind = op.get("kind")
    tracks = timeline["tracks"]
    if kind in {"add_camera_keyframe", "update_camera_keyframe", "delete_camera_keyframe"}:
        _edit_camera(timeline, op)
        return
    if kind == "add_track":
        track_type = op.get("track_type", "video")
        if track_type not in {
            "audio",
            "video",
            "midi",
            "instrument",
            "folder",
            "group",
            "fx",
            "marker",
            "tempo",
            "signature",
            "automation",
            "ai_visual",
            "prompt",
            "scene",
            "reference",
            "master",
        }:
            raise ValueError("Unsupported track type")
        tracks.append(
            {
                "id": op.get("new_id") or str(uuid4()),
                "type": track_type,
                "name": str(op.get("name") or track_type.title()),
                "clips": [],
            }
        )
        return
    track = next((t for t in tracks if t["id"] == op.get("track_id")), None)
    if track is None:
        raise ValueError("Track not found")
    if kind == "set_track_lock":
        if type(op.get("value")) is not bool:
            raise ValueError("Lock state must be boolean")
        track["locked"] = op["value"]
        return
    if kind == "set_track_state":
        fields = ("locked", "muted", "solo", "record_armed", "input_monitoring")
        provided = [field for field in fields if field in op]
        if not provided:
            raise ValueError("At least one track state value is required")
        if any(type(op[field]) is not bool for field in provided):
            raise ValueError("Track state values must be boolean")
        if track.get("locked") and not (provided == ["locked"] and op["locked"] is False):
            raise ValueError("Unlock the track before editing it")
        for field in provided:
            track[field] = op[field]
        return
    if track.get("locked"):
        raise ValueError("Unlock the track before editing it")
    if kind == "add_clip":
        clock = ProjectClock.from_timeline(timeline)
        start = clock.samples(op.get("start_seconds", 0))
        end = clock.samples(op.get("end_seconds", 1))
        if start < 0 or end <= start:
            raise ValueError("A new clip requires a positive duration at a nonnegative position")
        clip_data = deepcopy(op.get("data")) if isinstance(op.get("data"), dict) else {}
        clip_data.setdefault("name", str(op.get("name") or "Clip"))
        media_asset_id = op.get("media_asset_id")
        if media_asset_id is not None and (not isinstance(media_asset_id, str) or not media_asset_id):
            raise ValueError("Media asset ID must be a nonempty string")
        track["clips"].append(
            {
                "id": op.get("new_id") or str(uuid4()),
                "type": str(op.get("type") or track.get("type") or "video"),
                "start_sample": str(start),
                "end_sample": str(end),
                "data": clip_data,
                **({"media_asset_id": media_asset_id} if media_asset_id else {}),
                **({"source_path": op["source_path"]} if op.get("source_path") else {}),
            }
        )
        return
    if kind == "reorder_track":
        index = op.get("index")
        if type(index) is not int or not 0 <= index < len(tracks):
            raise ValueError("Invalid destination track index")
        tracks.remove(track)
        tracks.insert(index, track)
        return
    clip = next((c for c in track["clips"] if c["id"] == op.get("clip_id")), None)
    if clip is None:
        raise ValueError("Clip not found")
    if kind == "set_clip_lock":
        if type(op.get("value")) is not bool:
            raise ValueError("Lock state must be boolean")
        clip["locked"] = op["value"]
        return
    if clip.get("locked"):
        raise ValueError("Unlock the clip before editing it")
    if kind == "set_clip_property":
        _set_clip_property(clip, op)
        return
    if kind == "set_modulation":
        if str(track.get("type") or "").lower() not in {"motion", "automation", "ai_visual"}:
            raise ValueError("Modulation edits require a motion or automation track")
        field = op.get("field")
        if field not in MODULATION_FIELDS:
            raise ValueError("Unsupported modulation field")
        value = op.get("value")
        if value is not None and not isinstance(value, str):
            raise ValueError("Modulation schedules must be strings or null")
        data = clip.setdefault("data", {})
        if not isinstance(data, dict):
            raise ValueError("Clip data must be an object")
        data[field] = value
        return
    start, end = int64(clip["start_sample"]), int64(clip["end_sample"])
    clock = ProjectClock.from_timeline(timeline)
    if kind in {"move", "trim", "split"}:
        position = int64(op.get("position"))
        if op.get("snap") == "frame":
            position = clock.snap_frame(position)
        elif op.get("snap") not in {None, "off", "sample"}:
            raise ValueError("Unsupported snap mode")
        if position < 0:
            raise ValueError("Position cannot be negative")
    if kind == "move":
        clip["start_sample"], clip["end_sample"] = str(position), str(int64(position + end - start))
    elif kind == "trim":
        edge = op.get("edge")
        if edge == "start" and start <= position < end:
            _advance_source(clip, position - start, clock)
            clip["start_sample"] = str(position)
        elif edge == "end" and start < position <= end:
            _set_source_end(clip, position - start, clock)
            clip["end_sample"] = str(position)
        else:
            raise ValueError("Trim must shorten the selected edge within the clip")
    elif kind == "split":
        if not start < position < end:
            raise ValueError("Split must be inside the clip")
        right = deepcopy(clip)
        right["id"] = op.get("new_id") or str(uuid4())
        right["start_sample"] = str(position)
        _advance_source(right, position - start, clock)
        _set_source_end(clip, position - start, clock)
        clip["end_sample"] = str(position)
        track["clips"].insert(track["clips"].index(clip) + 1, right)
    elif kind == "duplicate":
        copy = deepcopy(clip)
        copy["id"] = op.get("new_id") or str(uuid4())
        copy["start_sample"], copy["end_sample"] = str(end), str(int64(end + end - start))
        track["clips"].append(copy)
    elif kind == "delete":
        track["clips"].remove(clip)
    elif kind == "set_mute":
        if type(op.get("value")) is not bool:
            raise ValueError("Mute state must be boolean")
        clip["muted"] = op["value"]
    else:
        raise ValueError("Unsupported timeline operation")


def _set_clip_property(clip: dict, op: dict) -> None:
    field = op.get("field")
    if field not in CLIP_PROPERTY_FIELDS:
        raise ValueError("Unsupported clip property")
    value = op.get("value")
    if field in {"speed", "volume", "fade_in_s", "fade_out_s", "source_in_s", "source_out_s", "opacity"}:
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            raise ValueError(f"{field} must be a finite number")
        value = float(value)
        if field == "speed" and not 0.25 <= value <= 4:
            raise ValueError("Playback speed must be between 0.25 and 4")
        if field == "volume" and not 0 <= value <= 2:
            raise ValueError("Volume must be between 0 and 2")
        if field in {"fade_in_s", "fade_out_s", "source_in_s", "source_out_s"} and value < 0:
            raise ValueError(f"{field} cannot be negative")
        if field == "opacity" and not 0 <= value <= 1:
            raise ValueError("Opacity must be between 0 and 1")
    elif field == "muted" and type(value) is not bool:
        raise ValueError("Muted state must be boolean")
    elif field in {"name", "prompt", "negative_prompt", "blend_mode"} and not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    data = clip.setdefault("data", {})
    if not isinstance(data, dict):
        raise ValueError("Clip data must be an object")
    data[field] = value
    if field == "source_in_s":
        _set_exact_source_property(data, value, "source_offset_sample", "source_offset_remainder")
    elif field == "source_out_s":
        _set_exact_source_property(data, value, "source_end_sample", "source_end_remainder")


def _set_exact_source_property(data: dict, seconds: float, sample_key: str, remainder_key: str) -> None:
    rate = int64(data.get("source_sample_rate", 48_000))
    if rate <= 0:
        raise ValueError("Source sample rate must be positive")
    exact = Fraction(str(seconds)) * rate
    rounded = int64(nearest(exact))
    data["source_sample_rate"] = rate
    data[sample_key], data[remainder_key] = str(rounded), str(exact - rounded)


def _edit_camera(timeline: dict, op: dict) -> None:
    camera = timeline.setdefault("camera", {})
    if not isinstance(camera, dict):
        raise ValueError("Timeline camera must be an object")
    if camera.get("locked"):
        raise ValueError("Unlock the camera lane before editing it")
    keyframes = camera.setdefault("keyframes", [])
    if not isinstance(keyframes, list):
        raise ValueError("Camera keyframes must be an array")
    kind = op["kind"]
    if kind == "add_camera_keyframe":
        values = op.get("values")
        if not isinstance(values, dict):
            raise ValueError("A camera keyframe requires values")
        keyframe = {"id": op.get("new_id") or str(uuid4())}
        _update_camera_values(keyframe, values)
        keyframe.setdefault("t", 0.0)
        keyframes.append(keyframe)
    else:
        keyframe_id = op.get("keyframe_id")
        index = op.get("index")
        keyframe = next((item for item in keyframes if item.get("id") == keyframe_id), None)
        if keyframe is None and type(index) is int and 0 <= index < len(keyframes):
            keyframe = keyframes[index]
        if keyframe is None:
            raise ValueError("Camera keyframe not found")
        if kind == "delete_camera_keyframe":
            keyframes.remove(keyframe)
        else:
            values = op.get("values")
            if not isinstance(values, dict) or not values:
                raise ValueError("Camera update requires values")
            _update_camera_values(keyframe, values)
    keyframes.sort(key=lambda item: float(item.get("t", 0)))


def _update_camera_values(keyframe: dict, values: dict) -> None:
    if not values.keys() <= CAMERA_FIELDS:
        raise ValueError("Unsupported camera keyframe field")
    for field, value in values.items():
        if field == "easing":
            if not isinstance(value, str):
                raise ValueError("Camera easing must be a string")
        else:
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ValueError(f"Camera {field} must be a finite number")
            value = float(value)
            if field == "t" and value < 0:
                raise ValueError("Camera time cannot be negative")
            if field == "zoom" and value <= 0:
                raise ValueError("Camera zoom must be positive")
        keyframe[field] = value


def _advance_source(clip: dict, delta: int, clock: ProjectClock) -> None:
    data = clip.get("data") if isinstance(clip.get("data"), dict) else clip
    rate = int64(data.get("source_sample_rate", clock.sample_rate))
    if rate <= 0:
        raise ValueError("Source sample rate must be positive")
    speed = Fraction(str(data.get("speed", 1)))
    if speed <= 0:
        raise ValueError("Playback rate must be positive")
    offset = (
        Fraction(int64(data["source_offset_sample"]))
        + Fraction(data.get("source_offset_remainder", "0"))
        if "source_offset_sample" in data
        else Fraction(str(data.get("source_in_s", 0))) * rate
    )
    offset += Fraction(delta, clock.sample_rate) * rate * speed
    rounded = int64(nearest(offset))
    data["source_sample_rate"], data["source_offset_sample"] = rate, str(rounded)
    data["source_offset_remainder"] = str(offset - rounded)
    data["source_in_s"] = float(offset / rate)


def _set_source_end(clip: dict, delta: int, clock: ProjectClock) -> None:
    boundary = deepcopy(clip)
    _advance_source(boundary, delta, clock)
    target = clip.get("data") if isinstance(clip.get("data"), dict) else clip
    source = boundary.get("data") if isinstance(boundary.get("data"), dict) else boundary
    target["source_out_s"] = source["source_in_s"]
    target["source_end_sample"] = source["source_offset_sample"]
    target["source_end_remainder"] = source["source_offset_remainder"]
