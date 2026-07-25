from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error normalized below
        raise ValueError(f"Unable to read JSON payload: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _safe_asset_name(value: str, fallback: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    if stem and stem[0].isdigit():
        stem = f"EDMG_{stem}"
    return stem[:64] or fallback


def _normalize_content_path(value: str | None, fallback: str) -> str:
    raw = str(value or fallback).strip() or fallback
    raw = raw.replace("\\", "/")
    if not raw.startswith("/Game"):
        raw = f"/Game/{raw.lstrip('/')}"
    return raw.rstrip("/")


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class UnrealImportMarker:
    label: str
    frame: int
    time_seconds: float
    source: str


@dataclass(frozen=True)
class UnrealImportShot:
    shot_id: str
    scene_id: str
    title: str | None
    start_frame: int
    end_frame: int
    prompt: str | None
    continuity_tags: list[str]
    camera_tags: list[str]
    approved: bool
    camera_name: str


@dataclass(frozen=True)
class UnrealSequenceImportPlan:
    schema_version: int
    bundle_dir: str
    bundle_manifest_path: str
    asset_name: str
    asset_path: str
    content_path: str
    sequence_name: str
    fps: int
    playback_start: int
    playback_end: int
    duration_seconds: float
    audio_path: str | None
    expected_return_dir: str
    expected_outputs: list[str]
    shots: list[UnrealImportShot]
    markers: list[UnrealImportMarker]
    diagnostics: list[str]
    source_payloads: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["shots"] = [asdict(shot) for shot in self.shots]
        payload["markers"] = [asdict(marker) for marker in self.markers]
        return payload


def load_unreal_bridge_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir).expanduser().resolve()
    manifest_path = root / "bundle_manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Missing bundle manifest: {manifest_path}")

    manifest = _read_json_dict(manifest_path)
    if str(manifest.get("export_family") or "") != "unreal_bridge_bundle":
        raise ValueError("Unsupported export_family for Unreal bridge bundle")

    payload_names = {
        "shot_manifest": "shot_manifest.json",
        "audio_markers": "audio_markers.json",
        "style_packet": "style_packet.json",
        "render_handoff": "render_handoff.json",
        "live_control_bridge": "live_control_bridge.json",
        "return_contract": "return_contract.json",
    }
    payloads: dict[str, Any] = {
        "bundle_dir": str(root),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
    }
    for key, filename in payload_names.items():
        path = root / filename
        if not path.exists():
            raise ValueError(f"Missing required Unreal bundle payload: {path}")
        payloads[f"{key}_path"] = str(path)
        payloads[key] = _read_json_dict(path)
    return payloads


def build_unreal_sequence_import_plan(
    bundle_dir: str | Path,
    *,
    content_path: str | None = None,
    asset_name: str | None = None,
) -> UnrealSequenceImportPlan:
    bundle = load_unreal_bridge_bundle(bundle_dir)
    manifest = bundle["manifest"]
    shot_manifest = bundle["shot_manifest"]
    audio_markers = bundle["audio_markers"]
    render_handoff = bundle["render_handoff"]
    return_contract = bundle["return_contract"]

    sequence_name = str(shot_manifest.get("sequence_name") or manifest.get("sequence_name") or "EDMGSequence").strip()
    fps = max(1, _coerce_int(shot_manifest.get("fps") or audio_markers.get("fps"), 24))
    duration_seconds = max(0.0, _coerce_float(shot_manifest.get("duration_seconds"), 0.0))

    consumer_hints = (
        return_contract.get("unreal_consumer")
        if isinstance(return_contract.get("unreal_consumer"), dict)
        else {}
    )
    final_content_path = _normalize_content_path(
        content_path or consumer_hints.get("default_content_path"),
        "/Game/EDMG/Sequences",
    )
    final_asset_name = _safe_asset_name(asset_name or sequence_name, "EDMGSequence")
    asset_path = f"{final_content_path}/{final_asset_name}"

    diagnostics: list[str] = []
    shots: list[UnrealImportShot] = []
    approved_count = 0
    for index, raw_shot in enumerate(list(shot_manifest.get("shots") or [])):
        if not isinstance(raw_shot, dict):
            diagnostics.append(f"ignored_non_object_shot_{index + 1}")
            continue
        shot_id = str(raw_shot.get("shot_id") or f"shot_{index + 1:03d}").strip() or f"shot_{index + 1:03d}"
        scene_id = str(raw_shot.get("scene_id") or shot_id).strip() or shot_id
        start_frame = max(0, _coerce_int(raw_shot.get("start_frame"), index * fps))
        end_frame = max(start_frame + 1, _coerce_int(raw_shot.get("end_frame"), start_frame + fps))
        approved = bool(raw_shot.get("approved"))
        if approved:
            approved_count += 1
        shots.append(
            UnrealImportShot(
                shot_id=shot_id,
                scene_id=scene_id,
                title=str(raw_shot.get("title") or "").strip() or None,
                start_frame=start_frame,
                end_frame=end_frame,
                prompt=str(raw_shot.get("prompt") or "").strip() or None,
                continuity_tags=[
                    str(tag).strip()
                    for tag in list(raw_shot.get("continuity_tags") or [])
                    if str(tag).strip()
                ],
                camera_tags=[
                    str(tag).strip()
                    for tag in list(raw_shot.get("camera_tags") or [])
                    if str(tag).strip()
                ],
                approved=approved,
                camera_name=_safe_asset_name(f"{shot_id}_Cam", f"Shot{index + 1:03d}_Cam"),
            )
        )
    if not shots:
        raise ValueError("No shots found in Unreal bundle")
    if approved_count == 0:
        diagnostics.append("no_approved_shots")

    marker_rows: list[UnrealImportMarker] = []
    seen_markers: set[tuple[int, str, str]] = set()

    def push_marker(label: str, frame: int, time_seconds: float, source: str) -> None:
        safe_label = str(label or "").strip()
        if not safe_label:
            return
        entry = (max(0, int(frame)), safe_label, source)
        if entry in seen_markers:
            return
        seen_markers.add(entry)
        marker_rows.append(
            UnrealImportMarker(
                label=safe_label,
                frame=max(0, int(frame)),
                time_seconds=max(0.0, float(time_seconds)),
                source=source,
            )
        )

    for raw_marker in list(shot_manifest.get("markers") or []):
        if not isinstance(raw_marker, dict):
            continue
        push_marker(
            str(raw_marker.get("label") or ""),
            _coerce_int(raw_marker.get("frame"), 0),
            _coerce_float(raw_marker.get("time_seconds"), 0.0),
            "shot_manifest",
        )
    for raw_section in list(audio_markers.get("section_events") or []):
        if not isinstance(raw_section, dict):
            continue
        time_seconds = _coerce_float(raw_section.get("time_seconds"), 0.0)
        push_marker(
            str(raw_section.get("label") or raw_section.get("section_id") or ""),
            _coerce_int(raw_section.get("frame"), int(round(time_seconds * fps))),
            time_seconds,
            "section_event",
        )
    for raw_cue in list(audio_markers.get("cue_events") or []):
        if not isinstance(raw_cue, dict):
            continue
        cue_label = str(raw_cue.get("instruction") or raw_cue.get("cue_type") or raw_cue.get("cue_id") or "").strip()
        push_marker(
            cue_label,
            _coerce_int(raw_cue.get("frame"), 0),
            _coerce_float(raw_cue.get("time_seconds"), 0.0),
            "cue_event",
        )
    marker_rows.sort(key=lambda item: (item.frame, item.label, item.source))

    playback_start = min([shot.start_frame for shot in shots] + [marker.frame for marker in marker_rows] + [0])
    fallback_end = int(round(duration_seconds * fps)) if duration_seconds > 0 else 0
    playback_end = max(
        [shot.end_frame for shot in shots]
        + [marker.frame + 1 for marker in marker_rows]
        + [fallback_end, playback_start + 1]
    )

    expected_return_dir = str(Path(bundle["bundle_dir"]) / str(consumer_hints.get("default_return_dir") or "returned"))
    expected_outputs = [
        str(item).strip()
        for item in list(return_contract.get("expected_outputs") or render_handoff.get("expected_outputs") or [])
        if str(item).strip()
    ]
    if not expected_outputs:
        expected_outputs = ["shot_render.mov", "alpha_pass.mov", "metadata.json"]

    source_payloads = {
        "bundle_manifest": str(bundle["manifest_path"]),
        "shot_manifest": str(bundle["shot_manifest_path"]),
        "audio_markers": str(bundle["audio_markers_path"]),
        "style_packet": str(bundle["style_packet_path"]),
        "render_handoff": str(bundle["render_handoff_path"]),
        "live_control_bridge": str(bundle["live_control_bridge_path"]),
        "return_contract": str(bundle["return_contract_path"]),
    }

    return UnrealSequenceImportPlan(
        schema_version=1,
        bundle_dir=str(bundle["bundle_dir"]),
        bundle_manifest_path=str(bundle["manifest_path"]),
        asset_name=final_asset_name,
        asset_path=asset_path,
        content_path=final_content_path,
        sequence_name=sequence_name,
        fps=fps,
        playback_start=playback_start,
        playback_end=playback_end,
        duration_seconds=duration_seconds,
        audio_path=str(shot_manifest.get("audio_path") or audio_markers.get("audio_path") or "").strip() or None,
        expected_return_dir=expected_return_dir,
        expected_outputs=expected_outputs,
        shots=shots,
        markers=marker_rows,
        diagnostics=diagnostics,
        source_payloads=source_payloads,
    )


def write_unreal_sequence_import_plan(plan: UnrealSequenceImportPlan, output_path: str | Path) -> Path:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
