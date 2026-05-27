from __future__ import annotations

from typing import Any


REQUIRED_SCENE_FIELDS = ("id", "start_s", "end_s", "prompt")


def _as_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"{field} must be a number") from exc


def _usd_string(value: Any) -> str:
    text = str(value if value is not None else "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _usd_identifier(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    chars: list[str] = []
    for char in raw:
        if char.isalnum() or char == "_":
            chars.append(char)
        elif char in ("-", " ", "."):
            chars.append("_")
    identifier = "".join(chars).strip("_")
    if not identifier:
        identifier = fallback
    if not (identifier[0].isalpha() or identifier[0] == "_"):
        identifier = f"_{identifier}"
    return identifier


def _usd_number(value: float | int | None) -> str:
    if value is None:
        return "0"
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def validate_scene_plan(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if not str(payload.get("project_id") or "").strip():
        errors.append("project_id is required")
    if not str(payload.get("title") or "").strip():
        errors.append("title is required")

    try:
        duration_s = _as_number(payload.get("duration_s"), "duration_s")
        if duration_s <= 0:
            errors.append("duration_s must be greater than 0")
    except ValueError as exc:
        duration_s = 0.0
        errors.append(str(exc))

    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes must be a non-empty array")
        return errors

    previous_end = 0.0
    seen_ids: set[str] = set()
    for index, raw_scene in enumerate(scenes):
        prefix = f"scenes[{index}]"
        if not isinstance(raw_scene, dict):
            errors.append(f"{prefix} must be an object")
            continue

        for field in REQUIRED_SCENE_FIELDS:
            if raw_scene.get(field) in (None, ""):
                errors.append(f"{prefix}.{field} is required")

        scene_id = str(raw_scene.get("id") or "").strip()
        if scene_id:
            if scene_id in seen_ids:
                errors.append(f"{prefix}.id must be unique")
            seen_ids.add(scene_id)

        try:
            start_s = _as_number(raw_scene.get("start_s"), f"{prefix}.start_s")
            end_s = _as_number(raw_scene.get("end_s"), f"{prefix}.end_s")
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if start_s < 0:
            errors.append(f"{prefix}.start_s must be >= 0")
        if end_s <= start_s:
            errors.append(f"{prefix}.end_s must be greater than start_s")
        if start_s < previous_end:
            errors.append(f"{prefix}.start_s overlaps the previous scene")
        if duration_s and end_s > duration_s:
            errors.append(f"{prefix}.end_s exceeds duration_s")
        previous_end = max(previous_end, end_s)

    return errors


def normalize_scene_plan(payload: dict[str, Any]) -> dict[str, Any]:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        scenes = []

    normalized_scenes: list[dict[str, Any]] = []
    for raw_scene in scenes:
        if not isinstance(raw_scene, dict):
            continue
        normalized_scenes.append(
            {
                "id": str(raw_scene.get("id") or "").strip(),
                "start_s": _as_number(raw_scene.get("start_s"), "scene.start_s"),
                "end_s": _as_number(raw_scene.get("end_s"), "scene.end_s"),
                "prompt": str(raw_scene.get("prompt") or "").strip(),
                "camera": str(raw_scene.get("camera") or "").strip(),
                "look": str(raw_scene.get("look") or "").strip(),
                "motion": str(raw_scene.get("motion") or "").strip(),
                "usd_variant": str(raw_scene.get("usd_variant") or "").strip(),
            }
        )

    return {
        "project_id": str(payload.get("project_id") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "duration_s": _as_number(payload.get("duration_s"), "duration_s"),
        "bpm": _as_number(payload.get("bpm"), "bpm") if payload.get("bpm") not in (None, "") else None,
        "provider": str(payload.get("provider") or "").strip(),
        "scenes": normalized_scenes,
    }


def scene_plan_usd_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_scene_plan(payload)
    return {
        "edmg:projectId": normalized["project_id"],
        "edmg:title": normalized["title"],
        "edmg:durationSeconds": normalized["duration_s"],
        "edmg:bpm": normalized["bpm"],
        "edmg:provider": normalized["provider"],
        "edmg:sceneCount": len(normalized["scenes"]),
    }


def scene_plan_usda_text(payload: dict[str, Any]) -> str:
    normalized = normalize_scene_plan(payload)
    project_id = normalized["project_id"]
    title = normalized["title"]
    duration_s = float(normalized["duration_s"])
    bpm = normalized["bpm"]
    provider = normalized["provider"]
    end_frame = max(1, int(round(duration_s * 24.0)))

    lines = [
        "#usda 1.0",
        "(",
        '    defaultPrim = "EDMGScenePlan"',
        "    metersPerUnit = 1",
        "    timeCodesPerSecond = 24",
        "    startTimeCode = 0",
        f"    endTimeCode = {end_frame}",
        ")",
        "",
        'def Xform "EDMGScenePlan"',
        "{",
        f"    custom string edmg:projectId = {_usd_string(project_id)}",
        f"    custom string edmg:title = {_usd_string(title)}",
        f"    custom double edmg:durationSeconds = {_usd_number(duration_s)}",
        f"    custom double edmg:bpm = {_usd_number(bpm)}",
        f"    custom string edmg:provider = {_usd_string(provider)}",
        f"    custom int edmg:sceneCount = {len(normalized['scenes'])}",
        "",
        '    def Scope "Scenes"',
        "    {",
    ]

    for index, scene in enumerate(normalized["scenes"], start=1):
        prim_name = _usd_identifier(scene.get("id"), f"Scene_{index:03d}")
        lines.extend(
            [
                f'        def Xform "{prim_name}"',
                "        {",
                f"            custom string edmg:id = {_usd_string(scene.get('id'))}",
                f"            custom double edmg:startSeconds = {_usd_number(scene.get('start_s'))}",
                f"            custom double edmg:endSeconds = {_usd_number(scene.get('end_s'))}",
                f"            custom string edmg:prompt = {_usd_string(scene.get('prompt'))}",
                f"            custom string edmg:camera = {_usd_string(scene.get('camera'))}",
                f"            custom string edmg:look = {_usd_string(scene.get('look'))}",
                f"            custom string edmg:motion = {_usd_string(scene.get('motion'))}",
                f"            custom string edmg:variant = {_usd_string(scene.get('usd_variant'))}",
                "        }",
            ]
        )

    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"
