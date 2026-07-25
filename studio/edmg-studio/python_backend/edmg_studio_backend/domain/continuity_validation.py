from __future__ import annotations

from typing import Any

CONTINUITY_SCHEMA_VERSION = "1.0"


def _scene_list(plan: dict[str, Any] | None, variant_index: int) -> list[dict[str, Any]]:
    plan = dict(plan or {})
    variants = [item for item in list(plan.get("variants") or []) if isinstance(item, dict)]
    if not variants:
        return []
    safe_index = max(0, min(int(variant_index), len(variants) - 1))
    scenes = variants[safe_index].get("scenes")
    return [item for item in list(scenes or []) if isinstance(item, dict)]


def _scene_id(scene: dict[str, Any], index: int) -> str:
    raw = scene.get("id") or scene.get("scene_id")
    return str(raw) if raw is not None else f"scene-{index + 1}"


def _prompt_text(scene: dict[str, Any]) -> str:
    for key in ("prompt", "prompt_pack", "description", "visual_prompt"):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def validate_project_continuity(
    *,
    plan: dict[str, Any] | None,
    visual_dna: dict[str, Any] | None = None,
    conductor_plan: dict[str, Any] | None = None,
    variant_index: int = 0,
) -> dict[str, Any]:
    """Return early continuity warnings before costly renders (P4-06)."""
    scenes = _scene_list(plan, variant_index)
    dna = dict(visual_dna or {})
    continuity = dna.get("continuity") if isinstance(dna.get("continuity"), dict) else {}
    subject_anchors = {str(item).strip().lower() for item in list(continuity.get("subject_anchors") or []) if str(item).strip()}
    environment_anchors = {str(item).strip().lower() for item in list(continuity.get("environment_anchors") or []) if str(item).strip()}
    palette_traits = {
        str(item).strip().lower()
        for item in list((dna.get("identity") or {}).get("palette") or [])
        if str(item).strip()
    }
    forbidden = {
        str(item).strip().lower()
        for item in list((dna.get("visual_grammar") or {}).get("forbidden_traits") or [])
        if str(item).strip()
    }

    warnings: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes):
        scene_id = _scene_id(scene, index)
        prompt = _prompt_text(scene)
        continuity_note = str(scene.get("continuityNote") or scene.get("continuity_note") or "").strip()
        transition = str(scene.get("transitionCue") or scene.get("transition_cue") or "").strip()

        if index > 0:
            prev = scenes[index - 1]
            prev_prompt = _prompt_text(prev)
            if prev_prompt and prompt and prev_prompt.split()[0:3] != prompt.split()[0:3]:
                warnings.append(
                    {
                        "code": "subject_drift",
                        "severity": "warn",
                        "scene_id": scene_id,
                        "message": "Opening prompt drifts from the previous scene; check subject continuity.",
                    }
                )
            if not continuity_note and not transition:
                warnings.append(
                    {
                        "code": "missing_bridge",
                        "severity": "info",
                        "scene_id": scene_id,
                        "message": "No continuity note or transition cue between adjacent scenes.",
                    }
                )

        if subject_anchors and prompt:
            if not any(anchor in prompt for anchor in subject_anchors):
                warnings.append(
                    {
                        "code": "subject_anchor_missing",
                        "severity": "warn",
                        "scene_id": scene_id,
                        "message": "Scene prompt does not reference any Visual DNA subject anchor.",
                    }
                )
        if environment_anchors and prompt:
            if not any(anchor in prompt for anchor in environment_anchors):
                warnings.append(
                    {
                        "code": "environment_anchor_missing",
                        "severity": "info",
                        "scene_id": scene_id,
                        "message": "Scene prompt does not reference environment anchors.",
                    }
                )
        if palette_traits and prompt:
            if not any(color in prompt for color in palette_traits):
                warnings.append(
                    {
                        "code": "palette_gap",
                        "severity": "info",
                        "scene_id": scene_id,
                        "message": "Scene prompt omits declared palette traits.",
                    }
                )
        if forbidden and prompt:
            hits = [trait for trait in forbidden if trait in prompt]
            if hits:
                warnings.append(
                    {
                        "code": "forbidden_trait",
                        "severity": "error",
                        "scene_id": scene_id,
                        "message": f"Prompt references forbidden traits: {', '.join(hits)}.",
                        "traits": hits,
                    }
                )

    if isinstance(conductor_plan, dict):
        sections = [item for item in list(conductor_plan.get("sections") or []) if isinstance(item, dict)]
        for section in sections:
            risk = section.get("continuity_risk")
            try:
                risk_value = float(risk)
            except Exception:
                risk_value = 0.0
            if risk_value >= 0.65:
                warnings.append(
                    {
                        "code": "conductor_high_risk",
                        "severity": "warn",
                        "scene_id": str(section.get("scene_id") or ""),
                        "message": f"Render Conductor flagged continuity risk {risk_value:.2f}.",
                        "continuity_risk": risk_value,
                    }
                )

    blocking = [item for item in warnings if item.get("severity") == "error"]
    return {
        "schemaVersion": CONTINUITY_SCHEMA_VERSION,
        "variant_index": int(variant_index),
        "scene_count": len(scenes),
        "warning_count": len(warnings),
        "blocking_count": len(blocking),
        "ok_to_render": len(blocking) == 0,
        "warnings": warnings,
    }
