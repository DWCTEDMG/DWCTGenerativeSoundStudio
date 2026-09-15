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
EDITING_SCHEMA_VERSION = 1
MAX_EDITING_COLLECTION_ITEMS = 10_000
MAX_AUTOMATION_POINTS = 100_000
FADE_CURVES = {"linear", "equal_power", "s_curve"}
PROCESS_ALGORITHMS = {"resample", "phase_vocoder"}

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


def normalize_timeline(
    source: dict, baseline: dict | None = None, project_media_pool: object = None
) -> dict:
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
                seconds_changed = seconds_key in data and data.get(seconds_key) != old_data.get(
                    seconds_key
                )
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
    markers = result.setdefault("markers", [])
    if not isinstance(markers, list):
        raise ValueError("Timeline markers must be an array")
    previous_markers = {
        marker.get("id"): marker
        for marker in (baseline or {}).get("markers", [])
        if isinstance(marker, dict)
    }
    for index, marker in enumerate(markers):
        if not isinstance(marker, dict):
            raise ValueError("Timeline marker must be an object")
        marker.setdefault("id", str(uuid5(NAMESPACE_URL, f"edmg:marker:{index}")))
        _unique_id(marker["id"], ids)
        legacy_marker = "position_sample" not in marker and "time_s" not in marker and "t" in marker
        if not legacy_marker:
            marker.setdefault("name", str(marker.get("label") or f"Marker {index + 1}"))
        old = previous_markers.get(marker["id"], {})
        seconds_changed = "time_s" in marker and marker.get("time_s") != old.get("time_s")
        if "position_sample" in marker and (not baseline or not seconds_changed):
            position = int64(marker["position_sample"])
        else:
            position = clock.samples(marker.get("time_s", marker.get("t", 0)))
        if position < 0:
            raise ValueError("Timeline markers cannot be before zero")
        if not legacy_marker:
            marker["position_sample"] = str(position)
            marker["time_s"] = float(clock.seconds(position))
    markers.sort(key=lambda marker: _marker_sample(marker, clock))
    _normalize_editing(result, ids, project_media_pool)
    return result


def _sample_text(value: object, name: str, *, signed: bool = False) -> str:
    sample = int64(value)
    if not signed and sample < 0:
        raise ValueError(f"{name} cannot be negative")
    text = str(sample)
    if not isinstance(value, str) or value != text:
        raise ValueError(f"{name} must be a canonical int64 sample string")
    return text


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _validate_target(target: object) -> str:
    parts = target.split(":") if isinstance(target, str) else []
    valid = (
        target in {"volume", "pan", "mute"}
        or (len(parts) == 2 and parts[0] in {"send", "render"} and bool(parts[1]))
        or (len(parts) == 3 and parts[0] == "plugin" and bool(parts[1]) and bool(parts[2]))
    )
    if not valid:
        raise ValueError("Invalid automation target")
    return target


def _validate_target_reference(target: str, track_ids: set[str]) -> None:
    parts = target.split(":")
    if len(parts) == 2 and parts[0] == "send" and parts[1] not in track_ids:
        raise ValueError("Automation send target track not found")


def _media_asset_ids(pool: object) -> set[str]:
    if pool is None:
        return set()
    if not isinstance(pool, list):
        raise ValueError("Project media pool must be an array")
    return {
        item.get("id")
        for item in pool
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _normalize_editing(
    timeline: dict, timeline_ids: set[str], project_media_pool: object = None
) -> None:
    editing = timeline.get("editing")
    if editing is None:
        return
    if not isinstance(editing, dict) or editing.get("schema_version") != EDITING_SCHEMA_VERSION:
        raise ValueError("Unsupported editing schema version")
    lanes = editing.setdefault("automation_lanes", [])
    takes = editing.setdefault("takes", [])
    comps = editing.setdefault("comp_ranges", [])
    crossfades = editing.setdefault("crossfades", [])
    collections = (lanes, takes, comps, crossfades)
    if not all(isinstance(value, list) for value in collections):
        raise ValueError("Editing collections must be arrays")
    if any(len(value) > MAX_EDITING_COLLECTION_ITEMS for value in collections):
        raise ValueError("Editing collections must contain at most 10000 items")
    editing_ids, take_map = set(timeline_ids), {}
    track_ids = {track["id"] for track in timeline["tracks"]}
    clip_ranges = {
        clip["id"]: (int(clip["start_sample"]), int(clip["end_sample"]))
        for track in timeline["tracks"]
        for clip in track["clips"]
    }
    assets = _media_asset_ids(project_media_pool) | _media_asset_ids(timeline.get("media_pool"))
    editing_ids.update(assets)
    for lane in lanes:
        if not isinstance(lane, dict):
            raise ValueError("Automation lane must be an object")
        _unique_id(lane.get("id"), editing_ids)
        if lane.get("track_id") not in track_ids:
            raise ValueError("Automation lane track not found")
        _validate_target_reference(_validate_target(lane.get("target")), track_ids)
        if lane.get("mode") not in {"read", "write", "touch"}:
            raise ValueError("Invalid automation mode")
        minimum, maximum = (
            _finite(lane.get("min_value"), "Automation minimum"),
            _finite(lane.get("max_value"), "Automation maximum"),
        )
        if maximum <= minimum:
            raise ValueError("Automation maximum must exceed minimum")
        points = lane.setdefault("points", [])
        if not isinstance(points, list) or len(points) > MAX_AUTOMATION_POINTS:
            raise ValueError("Automation points must be a bounded array")
        previous = -1
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("Automation point must be an object")
            _unique_id(point.get("id"), editing_ids)
            sample = int(_sample_text(point.get("sample"), "Automation sample"))
            if sample <= previous:
                raise ValueError("Automation points must have unique increasing samples")
            value = _finite(point.get("value"), "Automation value")
            if not minimum <= value <= maximum:
                raise ValueError("Automation value outside lane bounds")
            if point.get("curve", "linear") not in {"step", "linear", "smooth"}:
                raise ValueError("Invalid automation curve")
            tension = _finite(point.get("tension", 0), "Automation tension")
            if not -1 <= tension <= 1:
                raise ValueError("Automation tension outside bounds")
            previous = sample
    for take in takes:
        if not isinstance(take, dict):
            raise ValueError("Take must be an object")
        _unique_id(take.get("id"), editing_ids)
        if take.get("clip_id") not in clip_ranges or take.get("media_asset_id") not in assets:
            raise ValueError("Invalid take reference")
        _normalize_source_range(take.get("source_range"), "Take source range")
        take_map[take["id"]] = take["clip_id"]
    ranges = {}
    for comp in comps:
        if not isinstance(comp, dict):
            raise ValueError("Comp range must be an object")
        _unique_id(comp.get("id"), editing_ids)
        clip_id, take_id = comp.get("clip_id"), comp.get("take_id")
        start, end = (
            int(_sample_text(comp.get("start_sample"), "Comp start")),
            int(_sample_text(comp.get("end_sample"), "Comp end")),
        )
        if (
            take_map.get(take_id) != clip_id
            or clip_id not in clip_ranges
            or not clip_ranges[clip_id][0] <= start < end <= clip_ranges[clip_id][1]
        ):
            raise ValueError("Invalid comp range reference or bounds")
        ranges.setdefault(clip_id, []).append((start, end))
    for values in ranges.values():
        values.sort()
        if any(right[0] < left[1] for left, right in zip(values, values[1:], strict=False)):
            raise ValueError("Comp ranges cannot overlap")
    clips = {clip["id"]: clip for track in timeline["tracks"] for clip in track["clips"]}
    clip_tracks = {
        clip["id"]: track["id"] for track in timeline["tracks"] for clip in track["clips"]
    }
    for crossfade in crossfades:
        if not isinstance(crossfade, dict):
            raise ValueError("Crossfade must be an object")
        _unique_id(crossfade.get("id"), editing_ids)
        left, right = (
            clips.get(crossfade.get("left_clip_id")),
            clips.get(crossfade.get("right_clip_id")),
        )
        start = int(_sample_text(crossfade.get("start_sample"), "Crossfade start"))
        end = int(_sample_text(crossfade.get("end_sample"), "Crossfade end"))
        if (
            left is None
            or right is None
            or left is right
            or clip_tracks[left["id"]] != crossfade.get("track_id")
            or clip_tracks[right["id"]] != crossfade.get("track_id")
            or end <= start
            or start < max(int(left["start_sample"]), int(right["start_sample"]))
            or end > min(int(left["end_sample"]), int(right["end_sample"]))
        ):
            raise ValueError("Crossfade must lie within two overlapping clips on its track")
        if crossfade.get("curve", "equal_power") not in FADE_CURVES:
            raise ValueError("Invalid crossfade curve")
    for clip_id, clip in clips.items():
        data = clip.get("data") if isinstance(clip.get("data"), dict) else clip
        active_take = data.get("active_take_id")
        if active_take is not None and take_map.get(active_take) != clip_id:
            raise ValueError("Active take must reference a take owned by its clip")
        fades = data.get("fades")
        if fades is not None:
            if not isinstance(fades, dict):
                raise ValueError("Clip fades must be an object")
            fade_in = int(_sample_text(fades.get("in_samples"), "Fade in"))
            fade_out = int(_sample_text(fades.get("out_samples"), "Fade out"))
            if fade_in + fade_out > int(clip["end_sample"]) - int(clip["start_sample"]):
                raise ValueError("Fades cannot overlap beyond clip duration")
            if fades.get("curve", "equal_power") not in FADE_CURVES:
                raise ValueError("Invalid fade curve")
        process = data.get("process")
        if process is not None:
            if not isinstance(process, dict):
                raise ValueError("Clip process must be an object")
            rate = _finite(process.get("playback_rate"), "Playback rate")
            ratio = _finite(process.get("stretch_ratio"), "Stretch ratio")
            if not 0.25 <= rate <= 4 or not 0.25 <= ratio <= 4:
                raise ValueError("Process rates must be between 0.25 and 4")
            if process.get("algorithm") not in PROCESS_ALGORITHMS:
                raise ValueError("Invalid process algorithm")


def _normalize_source_range(value: object, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    rate = value.get("sample_rate")
    if type(rate) is not int or rate <= 0:
        raise ValueError(f"{name} sample rate must be a positive integer")
    start = int(_sample_text(value.get("start_sample"), f"{name} start"))
    end_value = value.get("end_sample")
    remainders = {}
    for key in ("start_remainder", "end_remainder"):
        remainder = value.get(key, "0")
        try:
            fraction = Fraction(remainder)
            if (
                not isinstance(remainder, str)
                or str(fraction) != remainder
                or (fraction.denominator == 1 and fraction != 0)
                or abs(fraction.numerator) >= fraction.denominator
            ):
                raise ValueError
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"{name} {key} must be a canonical rational string") from None
        remainders[key] = fraction
    if end_value is not None:
        end = int(_sample_text(end_value, f"{name} end"))
        if Fraction(end) + remainders["end_remainder"] < Fraction(start) + remainders["start_remainder"]:
            raise ValueError(f"{name} end cannot precede its start")


def _editing(timeline: dict) -> dict:
    value = timeline.setdefault(
        "editing",
        {
            "schema_version": EDITING_SCHEMA_VERSION,
            "automation_lanes": [],
            "takes": [],
            "comp_ranges": [],
            "crossfades": [],
        },
    )
    if not isinstance(value, dict):
        raise ValueError("Timeline editing document must be an object")
    return value


def _shift_clip_editing(timeline: dict, clip_ids: set[str], delta: int) -> None:
    editing = timeline.get("editing")
    if not isinstance(editing, dict) or not delta:
        return
    for comp in editing.get("comp_ranges", []):
        if comp.get("clip_id") in clip_ids:
            comp["start_sample"] = str(int64(comp["start_sample"]) + delta)
            comp["end_sample"] = str(int64(comp["end_sample"]) + delta)
    for crossfade in editing.get("crossfades", []):
        if {crossfade.get("left_clip_id"), crossfade.get("right_clip_id")} <= clip_ids:
            crossfade["start_sample"] = str(int64(crossfade["start_sample"]) + delta)
            crossfade["end_sample"] = str(int64(crossfade["end_sample"]) + delta)


def _trim_clip_comp_ranges(timeline: dict, clip_id: str, start: int, end: int) -> None:
    editing = timeline.get("editing")
    if not isinstance(editing, dict):
        return
    retained = []
    for comp in editing.get("comp_ranges", []):
        if comp.get("clip_id") != clip_id:
            retained.append(comp)
            continue
        comp_start = max(int64(comp["start_sample"]), start)
        comp_end = min(int64(comp["end_sample"]), end)
        if comp_start < comp_end:
            comp["start_sample"], comp["end_sample"] = str(comp_start), str(comp_end)
            retained.append(comp)
    editing["comp_ranges"] = retained


def _reconcile_crossfades(timeline: dict, clip_ids: set[str]) -> None:
    editing = timeline.get("editing")
    if not isinstance(editing, dict):
        return
    clips = {
        clip["id"]: clip for track in timeline.get("tracks", []) for clip in track.get("clips", [])
    }
    retained = []
    for crossfade in editing.get("crossfades", []):
        if not clip_ids.intersection(
            {crossfade.get("left_clip_id"), crossfade.get("right_clip_id")}
        ):
            retained.append(crossfade)
            continue
        left, right = clips.get(crossfade.get("left_clip_id")), clips.get(
            crossfade.get("right_clip_id")
        )
        if left is not None and right is not None:
            overlap_start = max(int64(left["start_sample"]), int64(right["start_sample"]))
            overlap_end = min(int64(left["end_sample"]), int64(right["end_sample"]))
            start = max(int64(crossfade["start_sample"]), overlap_start)
            end = min(int64(crossfade["end_sample"]), overlap_end)
            if start < end:
                crossfade["start_sample"], crossfade["end_sample"] = str(start), str(end)
                retained.append(crossfade)
    editing["crossfades"] = retained


def _duplicate_clip_editing(
    timeline: dict, source_clips: list[dict], duplicate_clips: list[dict], op: dict
) -> None:
    editing = timeline.get("editing")
    takes = [] if not isinstance(editing, dict) else [
        take
        for source in source_clips
        for take in editing.get("takes", [])
        if take.get("clip_id") == source["id"]
    ]
    comps = [] if not isinstance(editing, dict) else [
        comp
        for source in source_clips
        for comp in editing.get("comp_ranges", [])
        if comp.get("clip_id") == source["id"]
    ]
    take_ids, comp_ids = op.get("new_take_ids"), op.get("new_comp_ids")
    if len(takes) != len(take_ids or []) or len(comps) != len(comp_ids or []):
        raise ValueError("Duplication requires deterministic IDs for every duplicated take and comp range")
    supplied = [
        *(clip["id"] for clip in duplicate_clips),
        *(take_ids or []),
        *(comp_ids or []),
    ]
    existing = {
        item.get("id")
        for collection in ("automation_lanes", "takes", "comp_ranges", "crossfades")
        for item in (editing or {}).get(collection, [])
        if isinstance(item, dict)
    } | {
        item.get("id")
        for track in timeline.get("tracks", [])
        for item in [track, *track.get("clips", [])]
        if isinstance(item, dict)
    } | {
        marker.get("id") for marker in timeline.get("markers", []) if isinstance(marker, dict)
    } | _media_asset_ids(timeline.get("media_pool"))
    if (
        any(not isinstance(item, str) or not item for item in supplied)
        or len(set(supplied)) != len(supplied)
        or set(supplied) & existing
    ):
        raise ValueError("Duplicate editing IDs must be nonempty, unique, and unused")
    if not isinstance(editing, dict):
        return

    clip_map = dict(zip((clip["id"] for clip in source_clips), duplicate_clips, strict=True))
    take_map = dict(zip((take["id"] for take in takes), take_ids or [], strict=True))
    for take in takes:
        duplicate = deepcopy(take)
        duplicate.update(id=take_map[take["id"]], clip_id=clip_map[take["clip_id"]]["id"])
        editing["takes"].append(duplicate)
    for source in source_clips:
        source_data = source.get("data") if isinstance(source.get("data"), dict) else source
        duplicate = clip_map[source["id"]]
        duplicate_data = duplicate.get("data") if isinstance(duplicate.get("data"), dict) else duplicate
        if source_data.get("active_take_id") is not None:
            duplicate_data["active_take_id"] = take_map[source_data["active_take_id"]]
    for comp, new_id in zip(comps, comp_ids or [], strict=True):
        duplicate = deepcopy(comp)
        duplicate.update(
            id=new_id,
            clip_id=clip_map[comp["clip_id"]]["id"],
            take_id=take_map[comp["take_id"]],
            start_sample=str(
                int64(comp["start_sample"])
                + int64(clip_map[comp["clip_id"]]["start_sample"])
                - next(int64(source["start_sample"]) for source in source_clips if source["id"] == comp["clip_id"])
            ),
            end_sample=str(
                int64(comp["end_sample"])
                + int64(clip_map[comp["clip_id"]]["start_sample"])
                - next(int64(source["start_sample"]) for source in source_clips if source["id"] == comp["clip_id"])
            ),
        )
        editing["comp_ranges"].append(duplicate)


def _split_clip_editing(timeline: dict, clip: dict, right: dict, position: int, op: dict) -> None:
    editing = timeline.get("editing")
    if not isinstance(editing, dict):
        return
    clip_id, right_id = clip["id"], right["id"]
    takes = [take for take in editing.get("takes", []) if take.get("clip_id") == clip_id]
    right_comps = [
        comp
        for comp in editing.get("comp_ranges", [])
        if comp.get("clip_id") == clip_id and int64(comp["end_sample"]) > position
    ]
    take_ids, comp_ids = op.get("right_take_ids"), op.get("right_comp_ids")
    if len(takes) != len(take_ids or []) or len(right_comps) != len(comp_ids or []):
        raise ValueError("Split requires deterministic IDs for every right-side take and comp range")
    supplied = [*(take_ids or []), *(comp_ids or [])]
    existing = {
        item.get("id")
        for collection in ("automation_lanes", "takes", "comp_ranges", "crossfades")
        for item in editing.get(collection, [])
        if isinstance(item, dict)
    } | {
        item.get("id")
        for track in timeline.get("tracks", [])
        for item in [track, *track.get("clips", [])]
        if isinstance(item, dict)
    } | {
        marker.get("id")
        for marker in timeline.get("markers", [])
        if isinstance(marker, dict)
    } | {
        asset.get("id")
        for asset in timeline.get("media_pool", [])
        if isinstance(asset, dict)
    }
    if any(not isinstance(item, str) or not item for item in supplied) or len(set(supplied)) != len(supplied) or set(supplied) & existing:
        raise ValueError("Split editing IDs must be nonempty, unique, and unused")

    take_map = dict(zip((take["id"] for take in takes), take_ids or [], strict=True))
    duplicates = []
    for take in takes:
        duplicate = deepcopy(take)
        duplicate["id"], duplicate["clip_id"] = take_map[take["id"]], right_id
        duplicates.append(duplicate)
    editing.setdefault("takes", []).extend(duplicates)
    right_data = right.get("data") if isinstance(right.get("data"), dict) else right
    if right_data.get("active_take_id") is not None:
        right_data["active_take_id"] = take_map[right_data["active_take_id"]]

    right_id_map = dict(zip((comp["id"] for comp in right_comps), comp_ids or [], strict=True))
    retained, duplicates = [], []
    for comp in editing.get("comp_ranges", []):
        if comp.get("clip_id") != clip_id:
            retained.append(comp)
            continue
        original_start, original_end = int64(comp["start_sample"]), int64(comp["end_sample"])
        if original_start < position:
            comp["end_sample"] = str(min(original_end, position))
            retained.append(comp)
        if original_end > position:
            duplicate = deepcopy(comp)
            duplicate.update(
                id=right_id_map[comp["id"]],
                clip_id=right_id,
                take_id=take_map[comp["take_id"]],
                start_sample=str(max(original_start, position)),
                end_sample=str(original_end),
            )
            duplicates.append(duplicate)
    editing["comp_ranges"] = retained + duplicates


def _remove_clip_editing(timeline: dict, clip_id: str) -> None:
    editing = timeline.get("editing")
    if not isinstance(editing, dict):
        return
    take_ids = {
        take.get("id") for take in editing.get("takes", []) if take.get("clip_id") == clip_id
    }
    editing["takes"] = [take for take in editing.get("takes", []) if take.get("clip_id") != clip_id]
    editing["comp_ranges"] = [
        comp
        for comp in editing.get("comp_ranges", [])
        if comp.get("clip_id") != clip_id and comp.get("take_id") not in take_ids
    ]
    editing["crossfades"] = [
        crossfade
        for crossfade in editing.get("crossfades", [])
        if clip_id not in {crossfade.get("left_clip_id"), crossfade.get("right_clip_id")}
    ]


def _automation_edit(timeline: dict, op: dict) -> None:
    editing, kind = _editing(timeline), op["kind"]
    lanes = editing.setdefault("automation_lanes", [])
    lane = next((item for item in lanes if item.get("id") == op.get("lane_id")), None)
    if kind == "add_automation_lane":
        if lane is not None:
            raise ValueError("Automation lane ID already exists")
        lanes.append(
            {
                "id": op.get("lane_id"),
                "track_id": op.get("track_id"),
                "target": op.get("target"),
                "mode": op.get("mode"),
                "min_value": op.get("min_value"),
                "max_value": op.get("max_value"),
                "points": [],
            }
        )
    elif lane is None:
        raise ValueError("Automation lane not found")
    elif kind == "delete_automation_lane":
        lanes.remove(lane)
    elif kind == "set_automation_mode":
        lane["mode"] = op.get("mode")
    elif kind == "upsert_automation_point":
        points = lane.setdefault("points", [])
        point = next((item for item in points if item.get("id") == op.get("point_id")), None)
        values = {
            "id": op.get("point_id"),
            "sample": op.get("sample"),
            "value": op.get("value"),
            "curve": op.get("curve", "linear"),
            "tension": op.get("tension", 0),
        }
        if point is None:
            points.append(values)
        else:
            point.update(values)
        points.sort(key=lambda item: int64(item.get("sample")))
    elif kind == "delete_automation_point":
        point = next(
            (item for item in lane.get("points", []) if item.get("id") == op.get("point_id")), None
        )
        if point is None:
            raise ValueError("Automation point not found")
        lane["points"].remove(point)


def _advanced_edit(timeline: dict, track: dict, clip: dict | None, op: dict) -> None:
    kind, clock = op["kind"], ProjectClock.from_timeline(timeline)
    if kind == "ripple":
        origin, delta = (
            int(_sample_text(op.get("from_sample"), "Ripple origin")),
            int(_sample_text(op.get("delta_samples"), "Ripple delta", signed=True)),
        )
        if origin < 0:
            raise ValueError("Ripple origin cannot be negative")
        shifted = set()
        for item in track["clips"]:
            if int64(item["start_sample"]) >= origin:
                if item.get("locked"):
                    raise ValueError("Unlock affected clips before ripple editing")
                start, end = int64(item["start_sample"]) + delta, int64(item["end_sample"]) + delta
                if start < 0:
                    raise ValueError("Ripple would move a clip before zero")
                item["start_sample"], item["end_sample"] = str(start), str(end)
                shifted.add(item["id"])
        _shift_clip_editing(timeline, shifted, delta)
        _reconcile_crossfades(timeline, shifted)
        return
    if kind == "range_edit":
        start, end, delta, action = (
            int(_sample_text(op.get("start_sample"), "Range start")),
            int(_sample_text(op.get("end_sample"), "Range end")),
            int(_sample_text(op.get("delta_samples", "0"), "Range delta", signed=True)),
            op.get("range_action"),
        )
        selected = [
            item
            for item in track["clips"]
            if int64(item["start_sample"]) >= start and int64(item["end_sample"]) <= end
        ]
        if end <= start or action not in {"delete", "move", "duplicate"}:
            raise ValueError("Invalid range edit")
        if any(item.get("locked") for item in selected):
            raise ValueError("Unlock affected clips before range editing")
        if action == "delete":
            for item in selected:
                _remove_clip_editing(timeline, item["id"])
            track["clips"][:] = [item for item in track["clips"] if item not in selected]
        else:
            copies = deepcopy(selected) if action == "duplicate" else selected
            duplicate_ids = op.get("new_ids")
            if action == "duplicate" and (
                not isinstance(duplicate_ids, list)
                or len(duplicate_ids) != len(copies)
                or any(not isinstance(item, str) or not item for item in duplicate_ids)
                or len(set(duplicate_ids)) != len(duplicate_ids)
            ):
                raise ValueError("Range duplication requires one unique deterministic new ID per selected clip")
            existing_ids = {
                item.get("id")
                for candidate_track in timeline.get("tracks", [])
                for item in [candidate_track, *candidate_track.get("clips", [])]
                if isinstance(item, dict)
            }
            if action == "duplicate" and set(duplicate_ids) & existing_ids:
                raise ValueError("Range duplicate clip IDs must be unused")
            for item in copies:
                new_start, new_end = (
                    int64(item["start_sample"]) + delta,
                    int64(item["end_sample"]) + delta,
                )
                if new_start < 0:
                    raise ValueError("Range edit would move a clip before zero")
                item["start_sample"], item["end_sample"] = str(new_start), str(new_end)
                if action == "duplicate":
                    index = copies.index(item)
                    item["id"] = duplicate_ids[index]
            if action == "duplicate":
                _duplicate_clip_editing(timeline, selected, copies, op)
                track["clips"].extend(copies)
            else:
                shifted = {item["id"] for item in selected}
                _shift_clip_editing(timeline, shifted, delta)
                _reconcile_crossfades(timeline, shifted)
        return
    if clip is None:
        raise ValueError("Clip not found")
    start, end, delta = (
        int64(clip["start_sample"]),
        int64(clip["end_sample"]),
        int(_sample_text(op.get("delta_samples", "0"), "Edit delta", signed=True)),
    )
    data = clip.setdefault("data", {})
    if kind == "nudge":
        if start + delta < 0:
            raise ValueError("Edit would move clip before zero")
        clip["start_sample"], clip["end_sample"] = str(start + delta), str(end + delta)
        _shift_clip_editing(timeline, {clip["id"]}, delta)
        _reconcile_crossfades(timeline, {clip["id"]})
    elif kind == "slide":
        ordered = sorted(track["clips"], key=lambda item: int64(item["start_sample"]))
        index = ordered.index(clip)
        if index == 0 or index == len(ordered) - 1:
            raise ValueError("Slide requires adjacent clips")
        left, right = ordered[index - 1], ordered[index + 1]
        right_start = int64(right["start_sample"])
        if left.get("locked") or right.get("locked"):
            raise ValueError("Unlock adjacent clips before sliding")
        new_start, new_end = start + delta, end + delta
        if new_start <= int64(left["start_sample"]) or new_end >= int64(right["end_sample"]):
            raise ValueError("Slide would consume an adjacent clip")
        left["end_sample"], clip["start_sample"], clip["end_sample"], right["start_sample"] = (
            str(new_start),
            str(new_start),
            str(new_end),
            str(new_end),
        )
        _set_source_end(left, new_start - int64(left["start_sample"]), clock)
        _advance_source(right, new_end - right_start, clock)
        _shift_clip_editing(timeline, {clip["id"]}, delta)
        _trim_clip_comp_ranges(timeline, left["id"], int64(left["start_sample"]), new_start)
        _trim_clip_comp_ranges(timeline, right["id"], new_end, int64(right["end_sample"]))
        _reconcile_crossfades(timeline, {left["id"], clip["id"], right["id"]})
    elif kind == "slip":
        _advance_source(clip, delta, clock)
    elif kind == "set_fades":
        fade_in, fade_out = (
            int(_sample_text(op.get("fade_in_samples"), "Fade in")),
            int(_sample_text(op.get("fade_out_samples"), "Fade out")),
        )
        if fade_in < 0 or fade_out < 0 or fade_in + fade_out > end - start:
            raise ValueError("Fades cannot overlap beyond clip duration")
        curve = op.get("curve", "equal_power")
        if curve not in FADE_CURVES:
            raise ValueError("Invalid fade curve")
        fades = data.get("fades") if isinstance(data.get("fades"), dict) else {}
        fades.update({"in_samples": str(fade_in), "out_samples": str(fade_out), "curve": curve})
        data["fades"] = fades
    elif kind == "set_process":
        rate, ratio = (
            _finite(op.get("playback_rate"), "Playback rate"),
            _finite(op.get("stretch_ratio"), "Stretch ratio"),
        )
        if not 0.25 <= rate <= 4 or not 0.25 <= ratio <= 4:
            raise ValueError("Process rates must be between 0.25 and 4")
        algorithm = op.get("algorithm", "resample")
        if algorithm not in PROCESS_ALGORITHMS:
            raise ValueError("Invalid process algorithm")
        process = data.get("process") if isinstance(data.get("process"), dict) else {}
        process.update({"playback_rate": rate, "stretch_ratio": ratio, "algorithm": algorithm})
        data["process"] = process
    elif kind in {"add_take", "select_take", "set_comp_range"}:
        takes, comps = (
            _editing(timeline).setdefault("takes", []),
            _editing(timeline).setdefault("comp_ranges", []),
        )
        if kind == "add_take":
            value = {
                "id": op.get("take_id"),
                "clip_id": clip["id"],
                "media_asset_id": op.get("media_asset_id"),
            }
            if "source_range" in op:
                value["source_range"] = deepcopy(op["source_range"])
            takes.append(value)
        elif kind == "select_take":
            if not any(
                t.get("id") == op.get("take_id") and t.get("clip_id") == clip["id"] for t in takes
            ):
                raise ValueError("Take not found for clip")
            data["active_take_id"] = op["take_id"]
        else:
            existing = next((c for c in comps if c.get("id") == op.get("comp_id")), None)
            if existing is not None and existing.get("clip_id") != clip["id"]:
                raise ValueError("Comp range ID is already owned by another clip")
            value = {
                "id": op.get("comp_id"),
                "clip_id": clip["id"],
                "take_id": op.get("take_id"),
                "start_sample": op.get("start_sample"),
                "end_sample": op.get("end_sample"),
            }
            if existing is None:
                comps.append(value)
            else:
                existing.update(value)
    else:
        raise ValueError("Unsupported advanced operation")


def _unique_id(value: object, seen: set[str]) -> None:
    if not isinstance(value, str) or not value or value in seen:
        raise ValueError("Track and clip IDs must be nonempty and unique")
    seen.add(value)


def _marker_sample(marker: dict, clock: ProjectClock) -> int:
    if "position_sample" in marker:
        return int64(marker["position_sample"])
    return clock.samples(marker.get("time_s", marker.get("t", 0)))


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
        media_pool = meta.get("media_pool")
        after = normalize_timeline(before, project_media_pool=media_pool)
        if action == "replace":
            proposed = command.get("timeline")
            if not isinstance(proposed, dict):
                raise ValueError("Replacement requires a timeline")
            normalized_before = normalize_timeline(before, project_media_pool=media_pool)
            after = normalize_timeline(proposed, normalized_before, media_pool)
            _validate_replacement_editing(normalized_before, after)
            _preserve_locked(normalized_before, after)
        else:
            operations = command.get("operations") or []
            if not 1 <= len(operations) <= 200:
                raise ValueError("An edit requires between 1 and 200 operations")
            for operation in operations:
                if not isinstance(operation, dict) or not isinstance(operation.get("kind"), str):
                    raise ValueError("Each edit operation must be an object with a kind")
                _edit(after, operation)
            after = normalize_timeline(after, project_media_pool=media_pool)
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
        if (
            after_camera.get("locked") is not False
            or {**after_camera, "locked": True} != before_camera
        ):
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


def _validate_replacement_editing(before: dict, after: dict) -> None:
    before_editing = before.get("editing") if isinstance(before.get("editing"), dict) else {}
    after_editing = after.get("editing") if isinstance(after.get("editing"), dict) else {}

    def records(editing: dict, name: str) -> dict:
        return {item["id"]: item for item in editing.get(name, []) if isinstance(item, dict)}

    before_lanes, after_lanes = records(before_editing, "automation_lanes"), records(
        after_editing, "automation_lanes"
    )
    before_takes, after_takes = records(before_editing, "takes"), records(
        after_editing, "takes"
    )
    before_comps, after_comps = records(before_editing, "comp_ranges"), records(after_editing, "comp_ranges")
    before_crossfades, after_crossfades = records(before_editing, "crossfades"), records(after_editing, "crossfades")
    for record_id in before_lanes.keys() & after_lanes.keys():
        if before_lanes[record_id].get("track_id") != after_lanes[record_id].get("track_id"):
            raise ValueError("Existing automation lane IDs cannot change track ownership")
    for record_id in before_takes.keys() & after_takes.keys():
        if before_takes[record_id].get("clip_id") != after_takes[record_id].get("clip_id"):
            raise ValueError("Existing take IDs cannot change clip ownership")
    for record_id in before_comps.keys() & after_comps.keys():
        if before_comps[record_id].get("clip_id") != after_comps[record_id].get("clip_id"):
            raise ValueError("Existing comp IDs cannot change clip ownership")
    for record_id in before_crossfades.keys() & after_crossfades.keys():
        old, new = before_crossfades[record_id], after_crossfades[record_id]
        if any(
            old.get(key) != new.get(key)
            for key in ("track_id", "left_clip_id", "right_clip_id")
        ):
            raise ValueError("Existing crossfade IDs cannot change track or endpoint ownership")

    locked_tracks = {
        track.get("id") for track in before.get("tracks", []) if track.get("locked") is True
    }
    clip_tracks = {
        clip.get("id"): track.get("id")
        for track in before.get("tracks", [])
        for clip in track.get("clips", [])
    }
    clip_tracks.update(
        {
            clip.get("id"): track.get("id")
            for track in after.get("tracks", [])
            for clip in track.get("clips", [])
        }
    )
    locked_clips = {
        clip.get("id")
        for track in before.get("tracks", [])
        for clip in track.get("clips", [])
        if clip.get("locked") is True
    }

    def touches_locked(name: str, record: dict) -> bool:
        if name == "automation_lanes":
            target = record.get("target")
            send_track = target.split(":", 1)[1] if isinstance(target, str) and target.startswith("send:") else None
            return record.get("track_id") in locked_tracks or send_track in locked_tracks
        if name in {"takes", "comp_ranges"}:
            clip_id = record.get("clip_id")
            return clip_id in locked_clips or clip_tracks.get(clip_id) in locked_tracks
        endpoints = {record.get("left_clip_id"), record.get("right_clip_id")}
        return (
            record.get("track_id") in locked_tracks
            or bool(endpoints & locked_clips)
            or any(clip_tracks.get(clip_id) in locked_tracks for clip_id in endpoints)
        )

    for name in ("automation_lanes", "takes", "comp_ranges", "crossfades"):
        old_records, new_records = records(before_editing, name), records(after_editing, name)
        for record_id in old_records.keys() | new_records.keys():
            old, new = old_records.get(record_id), new_records.get(record_id)
            if old == new:
                continue
            if (old is not None and touches_locked(name, old)) or (
                new is not None and touches_locked(name, new)
            ):
                raise ValueError("Unlock the editing owner before changing its editing records")


def _edit(timeline: dict, op: dict) -> None:
    kind = op.get("kind")
    tracks = timeline["tracks"]
    if kind in {
        "add_automation_lane",
        "delete_automation_lane",
        "set_automation_mode",
        "upsert_automation_point",
        "delete_automation_point",
    }:
        if kind == "add_automation_lane":
            owner = next((item for item in tracks if item.get("id") == op.get("track_id")), None)
            if owner is None or owner.get("locked"):
                raise ValueError("Automation owner track not found or locked")
        else:
            lane = next(
                (
                    item
                    for item in _editing(timeline).get("automation_lanes", [])
                    if item.get("id") == op.get("lane_id")
                ),
                None,
            )
            owner = next(
                (item for item in tracks if lane and item.get("id") == lane.get("track_id")), None
            )
            if owner is None or owner.get("locked"):
                raise ValueError("Automation owner track not found or locked")
        _automation_edit(timeline, op)
        return
    if kind in {"add_camera_keyframe", "update_camera_keyframe", "delete_camera_keyframe"}:
        _edit_camera(timeline, op)
        return
    if kind in {"add_marker", "move_marker", "delete_marker"}:
        _edit_marker(timeline, op)
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
        if media_asset_id is not None and (
            not isinstance(media_asset_id, str) or not media_asset_id
        ):
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
    if kind in {"ripple", "range_edit"}:
        _advanced_edit(timeline, track, clip, op)
        return
    if kind == "set_crossfade":
        left = next((c for c in track["clips"] if c["id"] == op.get("left_clip_id")), None)
        right = next((c for c in track["clips"] if c["id"] == op.get("right_clip_id")), None)
        start, end = (
            int(_sample_text(op.get("start_sample"), "Crossfade start")),
            int(_sample_text(op.get("end_sample"), "Crossfade end")),
        )
        if (
            left is None
            or right is None
            or left.get("locked")
            or right.get("locked")
            or end <= start
            or start < max(int64(left["start_sample"]), int64(right["start_sample"]))
            or end > min(int64(left["end_sample"]), int64(right["end_sample"]))
        ):
            raise ValueError("Crossfade must lie within two unlocked overlapping clips")
        crossfade_id = op.get("crossfade_id")
        if not isinstance(crossfade_id, str) or not crossfade_id:
            raise ValueError("Crossfade ID is required")
        crossfades = _editing(timeline).setdefault("crossfades", [])
        value = {
            "id": crossfade_id,
            "track_id": track["id"],
            "left_clip_id": left["id"],
            "right_clip_id": right["id"],
            "start_sample": str(start),
            "end_sample": str(end),
            "curve": str(op.get("curve") or "equal_power"),
        }
        existing = next((item for item in crossfades if item.get("id") == crossfade_id), None)
        if existing is not None and (
            existing.get("track_id") != track["id"]
            or existing.get("left_clip_id") != left["id"]
            or existing.get("right_clip_id") != right["id"]
        ):
            raise ValueError("Crossfade ID is already owned by different endpoints")
        if existing is None:
            crossfades.append(value)
        else:
            existing.update(value)
        return
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
    if kind in {
        "nudge",
        "slip",
        "slide",
        "set_fades",
        "set_process",
        "add_take",
        "select_take",
        "set_comp_range",
    }:
        _advanced_edit(timeline, track, clip, op)
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
        _shift_clip_editing(timeline, {clip["id"]}, position - start)
        clip["start_sample"], clip["end_sample"] = str(position), str(int64(position + end - start))
        _reconcile_crossfades(timeline, {clip["id"]})
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
        _trim_clip_comp_ranges(
            timeline, clip["id"], int64(clip["start_sample"]), int64(clip["end_sample"])
        )
        _reconcile_crossfades(timeline, {clip["id"]})
    elif kind == "split":
        if not start < position < end:
            raise ValueError("Split must be inside the clip")
        right = deepcopy(clip)
        right["id"] = op.get("new_id") or str(uuid4())
        if not isinstance(right["id"], str) or not right["id"]:
            raise ValueError("Split clip ID must be a nonempty string")
        if any(
            item.get("id") == right["id"]
            for candidate_track in tracks
            for item in [candidate_track, *candidate_track.get("clips", [])]
        ):
            raise ValueError("Split clip ID is already in use")
        right["start_sample"] = str(position)
        _advance_source(right, position - start, clock)
        _split_clip_editing(timeline, clip, right, position, op)
        _set_source_end(clip, position - start, clock)
        clip["end_sample"] = str(position)
        track["clips"].insert(track["clips"].index(clip) + 1, right)
        _reconcile_crossfades(timeline, {clip["id"]})
    elif kind == "duplicate":
        copy = deepcopy(clip)
        copy["id"] = op.get("new_id") or str(uuid4())
        if not isinstance(copy["id"], str) or not copy["id"]:
            raise ValueError("Duplicate clip ID must be a nonempty string")
        if any(
            item.get("id") == copy["id"]
            for candidate_track in tracks
            for item in [candidate_track, *candidate_track.get("clips", [])]
        ):
            raise ValueError("Duplicate clip ID is already in use")
        copy["start_sample"], copy["end_sample"] = str(end), str(int64(end + end - start))
        _duplicate_clip_editing(timeline, [clip], [copy], op)
        track["clips"].append(copy)
    elif kind == "delete":
        _remove_clip_editing(timeline, clip["id"])
        track["clips"].remove(clip)
    elif kind == "set_mute":
        if type(op.get("value")) is not bool:
            raise ValueError("Mute state must be boolean")
        clip["muted"] = op["value"]
    else:
        raise ValueError("Unsupported timeline operation")


def _edit_marker(timeline: dict, op: dict) -> None:
    markers = timeline.setdefault("markers", [])
    if not isinstance(markers, list):
        raise ValueError("Timeline markers must be an array")
    kind = op["kind"]
    if kind == "add_marker":
        marker_id = op.get("new_id") or str(uuid4())
        if not isinstance(marker_id, str) or not marker_id:
            raise ValueError("Marker ID must be a nonempty string")
        if any(marker.get("id") == marker_id for marker in markers):
            raise ValueError("Marker ID is already in use")
        marker = {
            "id": marker_id,
            "name": str(op.get("name") or "Marker"),
            "position_sample": str(_marker_position(timeline, op)),
        }
        if op.get("color") is not None:
            if not isinstance(op["color"], str):
                raise ValueError("Marker color must be a string")
            marker["color"] = op["color"]
        markers.append(marker)
    else:
        marker = next((item for item in markers if item.get("id") == op.get("marker_id")), None)
        if marker is None:
            raise ValueError("Marker not found")
        if kind == "delete_marker":
            markers.remove(marker)
        else:
            marker["position_sample"] = str(_marker_position(timeline, op))
    clock = ProjectClock.from_timeline(timeline)
    markers.sort(key=lambda marker: _marker_sample(marker, clock))


def _marker_position(timeline: dict, op: dict) -> int:
    position = int64(op.get("position"))
    if op.get("snap") == "frame":
        position = ProjectClock.from_timeline(timeline).snap_frame(position)
    elif op.get("snap") not in {None, "off", "sample"}:
        raise ValueError("Unsupported snap mode")
    if position < 0:
        raise ValueError("Position cannot be negative")
    return position


def _set_clip_property(clip: dict, op: dict) -> None:
    field = op.get("field")
    if field not in CLIP_PROPERTY_FIELDS:
        raise ValueError("Unsupported clip property")
    value = op.get("value")
    if field in {
        "speed",
        "volume",
        "fade_in_s",
        "fade_out_s",
        "source_in_s",
        "source_out_s",
        "opacity",
    }:
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
    elif field in {"name", "prompt", "negative_prompt", "blend_mode"} and not isinstance(
        value, str
    ):
        raise ValueError(f"{field} must be a string")
    data = clip.setdefault("data", {})
    if not isinstance(data, dict):
        raise ValueError("Clip data must be an object")
    data[field] = value
    if field == "source_in_s":
        _set_exact_source_property(data, value, "source_offset_sample", "source_offset_remainder")
    elif field == "source_out_s":
        _set_exact_source_property(data, value, "source_end_sample", "source_end_remainder")


def _set_exact_source_property(
    data: dict, seconds: float, sample_key: str, remainder_key: str
) -> None:
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
    if offset < 0:
        raise ValueError("Source offset cannot be negative")
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
