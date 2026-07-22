from __future__ import annotations

import time
import uuid
from typing import Any

from .music_graph import section_energy_at_time


WAN_S2V_MODEL = {
    "id": "wan_s2v_14b",
    "repo_id": "Wan-AI/Wan2.2-S2V-14B",
    "display_name": "Wan2.2 S2V 14B",
    "lane": "experimental_high_end",
    "capability": "audio_driven_performance_video",
    "license": "research",
    "hardware_hint_gb": 80,
}


def _scene_id(scene: dict[str, Any], index: int) -> str:
    raw = scene.get("id") or scene.get("scene_id")
    if raw is None:
        return f"scene-{index + 1}"
    return str(raw)


def _performance_scene(scene: dict[str, Any]) -> bool:
    prompt = " ".join(str(scene.get(key) or "") for key in ("name", "prompt", "creative_goal", "continuity_note")).lower()
    tokens = ("performer", "performance", "lip sync", "singer", "vocalist", "stage", "live")
    return any(token in prompt for token in tokens)


def build_performer_workflow_plan(
    *,
    project_id: str,
    variant_index: int,
    scenes: list[dict[str, Any]],
    music_graph: dict[str, Any] | None,
    director_mode: str | None = None,
    environment: dict[str, Any] | None = None,
    scene_ids: list[str] | None = None,
    model_id: str = "wan_s2v_14b",
) -> dict[str, Any]:
    """Plan audio-driven performer scenes through the external/high-end lane (W6-05 partial)."""
    selected_ids = {str(item).strip() for item in (scene_ids or []) if str(item).strip()}
    engines = (environment or {}).get("engines") if isinstance((environment or {}).get("engines"), dict) else {}
    hosted = engines.get("hosted_video") if isinstance(engines.get("hosted_video"), dict) else {}
    hosted_available = bool(hosted.get("available", False))
    mode = str(director_mode or "").strip().lower()
    model = dict(WAN_S2V_MODEL)
    if model_id and model_id != WAN_S2V_MODEL["id"]:
        model = {**model, "requested_id": model_id}

    tasks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        sid = _scene_id(scene, index)
        if selected_ids and sid not in selected_ids:
            continue
        if selected_ids or _performance_scene(scene) or mode == "performance":
            start_s = float(scene.get("start_s") or 0.0)
            end_s = float(scene.get("end_s") or start_s + 5.0)
            duration_s = max(0.5, end_s - start_s)
            midpoint = (start_s + end_s) / 2.0
            energy = section_energy_at_time(music_graph, midpoint, default=0.55)
            tasks.append(
                {
                    "scene_id": sid,
                    "engine": "hosted_video",
                    "model": model,
                    "audio_window": {"start_s": start_s, "end_s": end_s, "duration_s": duration_s},
                    "energy": round(energy, 3),
                    "provenance": {
                        "lane": model["lane"],
                        "capability": model["capability"],
                        "music_graph_schema": (music_graph or {}).get("schemaVersion"),
                        "director_mode": mode or None,
                    },
                    "notes": [
                        "Audio-driven performer workflow routes through hosted/high-end selection with explicit provenance.",
                        f"Target model: {model['display_name']} ({model['repo_id']}).",
                    ],
                }
            )

    if not tasks and scenes:
        fallback = scenes[0] if isinstance(scenes[0], dict) else {}
        sid = _scene_id(fallback, 0)
        start_s = float(fallback.get("start_s") or 0.0)
        end_s = float(fallback.get("end_s") or start_s + 5.0)
        tasks.append(
            {
                "scene_id": sid,
                "engine": "hosted_video",
                "model": model,
                "audio_window": {"start_s": start_s, "end_s": end_s, "duration_s": max(0.5, end_s - start_s)},
                "energy": 0.5,
                "provenance": {
                    "lane": model["lane"],
                    "capability": model["capability"],
                    "music_graph_schema": (music_graph or {}).get("schemaVersion"),
                    "director_mode": mode or None,
                    "fallback": True,
                },
                "notes": ["Default performer task created from the first storyboard scene."],
            }
        )

    if not hosted_available:
        warnings.append(
            {
                "code": "hosted_lane_unavailable",
                "severity": "warning",
                "message": "Hosted/high-end performer lane is unavailable in the current environment; plan is advisory only.",
            }
        )
    warnings.append(
        {
            "code": "experimental_model",
            "severity": "info",
            "message": f"{model['display_name']} remains experimental and is not a normal desktop default.",
        }
    )

    return {
        "schema_version": 1,
        "plan_id": f"performer-{uuid.uuid4().hex[:12]}",
        "project_id": project_id,
        "variant_index": int(variant_index),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "advisory_only": True,
        "model": model,
        "tasks": tasks,
        "warnings": warnings,
        "summary": f"Performer workflow for {len(tasks)} scene(s) via {model['display_name']} ({model['lane']}).",
    }
