from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from ..schemas import (
    EngineOutcomeMemory,
    ProjectVisualDNA,
    QualityFailurePattern,
    SuccessfulRenderCombination,
    TraitObservation,
    TraitScope,
    TraitState,
    VisualDNAFingerprint,
)

_TRAIT_SCOPE_LIMITS: dict[TraitScope, int] = {
    "theme": 8,
    "motif": 10,
    "palette": 8,
    "lighting": 6,
    "camera": 6,
    "texture": 6,
    "positive_prompt": 12,
    "negative_prompt": 12,
    "transition_rule": 8,
    "engine": 6,
    "failure": 8,
}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_text(value: Any, *, max_len: int = 260) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)[:max_len]


def _unique_strings(values: list[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _safe_text(raw)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _prompt_fragments(text: Any, *, limit: int = 4) -> list[str]:
    if isinstance(text, (list, tuple)):
        flattened: list[str] = []
        for item in text:
            flattened.extend(_prompt_fragments(item, limit=limit))
            if len(flattened) >= limit:
                break
        return _unique_strings(flattened, limit=limit)
    raw = _safe_text(text, max_len=600)
    if not raw:
        return []
    parts = re.split(r"[,\n;]+", raw)
    cleaned = [part.strip() for part in parts if part.strip()]
    if not cleaned:
        cleaned = [raw]
    return _unique_strings(cleaned, limit=limit)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp_unit(value: Any, default: float = 0.0) -> float:
    number = _coerce_float(value, default)
    if number != number:
        return float(default)
    return max(0.0, min(1.0, number))


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _extract_scenes(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = plan if isinstance(plan, dict) else {}
    raw_scenes = payload.get("scenes")
    if isinstance(raw_scenes, list):
        return [scene for scene in raw_scenes if isinstance(scene, dict)]
    variants = payload.get("variants")
    if isinstance(variants, list) and variants:
        scenes = variants[0].get("scenes") if isinstance(variants[0], dict) else None
        if isinstance(scenes, list):
            return [scene for scene in scenes if isinstance(scene, dict)]
    return []


def _observe_trait(
    dna: ProjectVisualDNA,
    *,
    scope: TraitScope,
    value: Any,
    source: str,
    state: TraitState = "observed",
    weight: float = 0.45,
) -> None:
    text = _safe_text(value)
    if not text:
        return
    normalized = text.casefold()
    for trait in dna.trait_memory:
        if trait.scope == scope and trait.value.casefold() == normalized:
            trait.evidence_count += 1
            trait.weight = min(1.0, max(trait.weight, weight) + 0.08)
            if source not in trait.sources:
                trait.sources.append(source)
            if trait.state != "declared":
                if state == "declared":
                    trait.state = "declared"
                elif trait.evidence_count >= 3:
                    trait.state = "reinforced"
                else:
                    trait.state = state
            return
    dna.trait_memory.append(
        TraitObservation(
            scope=scope,
            value=text,
            state=state,
            weight=max(0.0, min(1.0, float(weight))),
            evidence_count=1,
            sources=[source],
        )
    )


def _top_traits(dna: ProjectVisualDNA, scope: TraitScope, *, limit: int) -> list[str]:
    candidates = [trait for trait in dna.trait_memory if trait.scope == scope]
    ranked = sorted(
        candidates,
        key=lambda trait: (
            -float(trait.weight),
            -int(trait.evidence_count),
            0 if trait.state == "declared" else 1,
            trait.value.casefold(),
        ),
    )
    return [trait.value for trait in ranked[:limit]]


def _record_failure(
    dna: ProjectVisualDNA,
    *,
    pattern: Any,
    mitigation: Any = None,
    source: str,
) -> None:
    text = _safe_text(pattern)
    if not text:
        return
    mitigation_text = _safe_text(mitigation, max_len=400) or None
    for item in dna.quality_memory.common_failures:
        if item.pattern.casefold() == text.casefold():
            item.frequency += 1
            if mitigation_text and not item.mitigation:
                item.mitigation = mitigation_text
            _observe_trait(dna, scope="failure", value=text, source=source, state="observed", weight=0.5)
            return
    dna.quality_memory.common_failures.append(
        QualityFailurePattern(pattern=text, frequency=1, mitigation=mitigation_text)
    )
    _observe_trait(dna, scope="failure", value=text, source=source, state="observed", weight=0.5)


def _record_successful_combination(
    dna: ProjectVisualDNA,
    *,
    engine: str,
    model: str | None,
    context: str | None,
    score: float,
) -> None:
    engine_text = _safe_text(engine, max_len=80)
    if not engine_text:
        return
    model_text = _safe_text(model, max_len=160) or None
    context_text = _safe_text(context, max_len=260) or None
    for item in dna.quality_memory.successful_combinations:
        if (
            item.engine.casefold() == engine_text.casefold()
            and (item.model or "").casefold() == (model_text or "").casefold()
            and (item.context or "").casefold() == (context_text or "").casefold()
        ):
            item.score = max(item.score, _clamp_unit(score, 0.0))
            return
    dna.quality_memory.successful_combinations.append(
        SuccessfulRenderCombination(
            engine=engine_text,
            model=model_text,
            context=context_text,
            score=_clamp_unit(score, 0.0),
        )
    )


def _sync_curated_fields(dna: ProjectVisualDNA) -> None:
    dna.identity.core_themes = _top_traits(dna, "theme", limit=8)
    dna.identity.motifs = _top_traits(dna, "motif", limit=8)
    dna.identity.palette.dominant = _top_traits(dna, "palette", limit=6)
    dna.identity.lighting_language = _top_traits(dna, "lighting", limit=6)
    dna.identity.camera_language = _top_traits(dna, "camera", limit=6)
    dna.identity.texture_language = _top_traits(dna, "texture", limit=6)
    dna.prompt_guidance.positive_fragments = _top_traits(dna, "positive_prompt", limit=10)
    dna.prompt_guidance.negative_fragments = _top_traits(dna, "negative_prompt", limit=10)
    dna.continuity.transition_rules = _top_traits(dna, "transition_rule", limit=8)
    dna.trait_memory = sorted(
        dna.trait_memory,
        key=lambda trait: (-float(trait.weight), -int(trait.evidence_count), trait.value.casefold()),
    )[:64]
    dna.quality_memory.common_failures = sorted(
        dna.quality_memory.common_failures,
        key=lambda item: (-int(item.frequency), item.pattern.casefold()),
    )[:16]
    dna.quality_memory.successful_combinations = sorted(
        dna.quality_memory.successful_combinations,
        key=lambda item: (-float(item.score), item.engine.casefold(), (item.model or "").casefold()),
    )[:16]
    dna.fingerprints = dna.fingerprints[-24:]


def _recompute_confidence(dna: ProjectVisualDNA) -> None:
    counts = dna.learning_state.sources
    confidence = (
        min(3, int(counts.get("planner_imports", 0))) * 0.18
        + min(3, int(counts.get("reactive_imports", 0))) * 0.14
        + min(8, int(counts.get("approved_renders", 0))) * 0.06
        + min(6, int(counts.get("repair_renders", 0))) * 0.03
        + min(6, int(counts.get("rejected_renders", 0))) * 0.02
    )
    dna.learning_state.confidence = min(1.0, confidence)


def visual_dna_path(project_dir: Path) -> Path:
    return project_dir / "analysis" / "visual_dna.json"


def visual_dna_json_schema() -> dict[str, Any]:
    return ProjectVisualDNA.model_json_schema()


def create_default_visual_dna(project_id: str, project_name: str | None = None) -> ProjectVisualDNA:
    return ProjectVisualDNA(
        project_id=_safe_text(project_id, max_len=120) or "unknown-project",
        project_name=_safe_text(project_name, max_len=200) or None,
        updated_at=_utc_now(),
    )


def load_visual_dna(
    project_dir: Path,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> ProjectVisualDNA:
    path = visual_dna_path(project_dir)
    fallback = create_default_visual_dna(project_id or project_dir.name, project_name)
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        dna = ProjectVisualDNA.model_validate(payload)
    except Exception:
        return fallback
    updates: dict[str, Any] = {}
    if project_id and dna.project_id != project_id:
        updates["project_id"] = project_id
    if project_name and dna.project_name != project_name:
        updates["project_name"] = project_name
    if not dna.updated_at:
        updates["updated_at"] = _utc_now()
    if updates:
        dna = dna.model_copy(update=updates)
    return dna


def save_visual_dna(project_dir: Path, dna: ProjectVisualDNA) -> ProjectVisualDNA:
    normalized = dna.model_copy(deep=True, update={"updated_at": _utc_now()})
    _sync_curated_fields(normalized)
    _recompute_confidence(normalized)
    _write_json_atomic(visual_dna_path(project_dir), normalized.model_dump(mode="json"))
    return normalized


def ingest_planner_payload(
    dna: ProjectVisualDNA,
    *,
    analysis: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
    source_label: str = "planner_lab",
) -> ProjectVisualDNA:
    updated = dna.model_copy(deep=True)
    updated.learning_state.sources["planner_imports"] = int(
        updated.learning_state.sources.get("planner_imports", 0)
    ) + 1

    analysis_obj = analysis if isinstance(analysis, dict) else {}
    plan_obj = plan if isinstance(plan, dict) else {}
    settings_obj = settings if isinstance(settings, dict) else {}

    for item in list(analysis_obj.get("themes") or []):
        if isinstance(item, dict):
            _observe_trait(updated, scope="theme", value=item.get("theme"), source=source_label, weight=0.65)
    for item in list(analysis_obj.get("visualImagery") or []):
        if isinstance(item, dict):
            _observe_trait(updated, scope="motif", value=item.get("element"), source=source_label, weight=0.6)
    for item in list(plan_obj.get("keywordBank") or []):
        _observe_trait(updated, scope="motif", value=item, source=source_label, weight=0.45)

    style_hint = _safe_text(settings_obj.get("promptStyle") or settings_obj.get("style") or "")
    if style_hint:
        updated.prompt_guidance.style_bias[style_hint] = max(
            _clamp_unit(updated.prompt_guidance.style_bias.get(style_hint), 0.0),
            0.82,
        )

    scenes = _extract_scenes(plan_obj)
    approved_scenes = [
        scene
        for scene in scenes
        if bool(scene.get("approved")) or str(scene.get("status") or "").strip().lower() == "approved"
    ]
    focus_scenes = approved_scenes or scenes
    for scene in focus_scenes:
        for fragment in _prompt_fragments(scene.get("text") or scene.get("prompt")):
            _observe_trait(updated, scope="positive_prompt", value=fragment, source=source_label, weight=0.58)
        for fragment in _prompt_fragments(scene.get("negativePrompt") or scene.get("negative_prompt"), limit=3):
            _observe_trait(updated, scope="negative_prompt", value=fragment, source=source_label, weight=0.55)
        _observe_trait(updated, scope="camera", value=scene.get("shotType") or scene.get("shot_type"), source=source_label, weight=0.5)
        _observe_trait(
            updated,
            scope="transition_rule",
            value=scene.get("transitionCue") or scene.get("transition_cue"),
            source=source_label,
            weight=0.48,
        )
        continuity_note = _safe_text(scene.get("continuityNote") or scene.get("continuity_note"))
        if continuity_note:
            _observe_trait(
                updated,
                scope="transition_rule",
                value=continuity_note,
                source=source_label,
                weight=0.52,
            )

    updated.updated_at = _utc_now()
    _sync_curated_fields(updated)
    _recompute_confidence(updated)
    return updated


def ingest_reactive_payload(
    dna: ProjectVisualDNA,
    *,
    payload: dict[str, Any] | None,
    source_label: str = "reactive_lab",
) -> ProjectVisualDNA:
    updated = dna.model_copy(deep=True)
    updated.learning_state.sources["reactive_imports"] = int(
        updated.learning_state.sources.get("reactive_imports", 0)
    ) + 1

    reactive = payload if isinstance(payload, dict) else {}
    metadata = reactive.get("metadata") if isinstance(reactive.get("metadata"), dict) else {}
    schedules = reactive.get("schedules") if isinstance(reactive.get("schedules"), dict) else {}
    handoff = reactive.get("handoff_manifest") if isinstance(reactive.get("handoff_manifest"), dict) else {}

    render_mode = _safe_text(metadata.get("renderMode") or handoff.get("renderMode"), max_len=80)
    if render_mode:
        updated.prompt_guidance.style_bias["music_video"] = max(
            _clamp_unit(updated.prompt_guidance.style_bias.get("music_video"), 0.0),
            0.78,
        )
        _observe_trait(updated, scope="engine", value=render_mode, source=source_label, weight=0.42)

    if any(key in schedules for key in ("zoom", "translation_z")):
        _observe_trait(updated, scope="camera", value="push-in dynamics", source=source_label, weight=0.52)
    if any(key in schedules for key in ("rotation_y", "rotation_z")):
        _observe_trait(updated, scope="camera", value="orbit accents", source=source_label, weight=0.56)
    if any(key in schedules for key in ("brightness", "cfg_scale")):
        _observe_trait(updated, scope="lighting", value="contrast lift on musical peaks", source=source_label, weight=0.48)

    for section in list(reactive.get("sections") or []):
        if not isinstance(section, dict):
            continue
        _observe_trait(updated, scope="theme", value=section.get("label"), source=source_label, weight=0.4)
        if bool(section.get("approved")):
            label = _safe_text(section.get("label"))
            if label:
                _observe_trait(
                    updated,
                    scope="transition_rule",
                    value=f"Preserve continuity through {label} sections",
                    source=source_label,
                    weight=0.5,
                )

    for repair in list(reactive.get("repair_suggestions") or []):
        if not isinstance(repair, dict):
            continue
        _record_failure(
            updated,
            pattern=repair.get("issue") or repair.get("pattern"),
            mitigation=repair.get("action"),
            source=source_label,
        )

    updated.updated_at = _utc_now()
    _sync_curated_fields(updated)
    _recompute_confidence(updated)
    return updated


def record_render_feedback(
    dna: ProjectVisualDNA,
    *,
    feedback: dict[str, Any] | None,
    source_label: str = "render_feedback",
) -> ProjectVisualDNA:
    updated = dna.model_copy(deep=True)
    payload = feedback if isinstance(feedback, dict) else {}

    engine = _safe_text(payload.get("engine") or payload.get("render_mode") or "unknown", max_len=80)
    outcome = _safe_text(payload.get("user_outcome") or "unknown", max_len=40).lower()
    if outcome not in {"approved", "rejected", "needs_repair", "unknown"}:
        outcome = "unknown"

    fingerprint = VisualDNAFingerprint(
        render_id=_safe_text(payload.get("render_id") or f"render-{len(updated.fingerprints) + 1}", max_len=120),
        palette_signature=_unique_strings(list(payload.get("palette_signature") or []), limit=6),
        motif_tags=_unique_strings(list(payload.get("motif_tags") or []), limit=8),
        motion_profile=_safe_text(payload.get("motion_profile"), max_len=160) or None,
        continuity_score=_clamp_unit(payload.get("continuity_score"), 0.0)
        if payload.get("continuity_score") is not None
        else None,
        user_outcome=outcome,  # type: ignore[arg-type]
        engine=engine or None,
        model=_safe_text(payload.get("model"), max_len=160) or None,
        created_at=_safe_text(payload.get("created_at"), max_len=40) or _utc_now(),
    )
    updated.fingerprints.append(fingerprint)

    engine_memory = updated.engine_memory.setdefault(engine or "unknown", EngineOutcomeMemory())
    total_before = engine_memory.approved_count + engine_memory.rejected_count + engine_memory.repair_count
    if outcome == "approved":
        engine_memory.approved_count += 1
        updated.learning_state.sources["approved_renders"] = int(
            updated.learning_state.sources.get("approved_renders", 0)
        ) + 1
    elif outcome == "rejected":
        engine_memory.rejected_count += 1
        updated.learning_state.sources["rejected_renders"] = int(
            updated.learning_state.sources.get("rejected_renders", 0)
        ) + 1
    elif outcome == "needs_repair":
        engine_memory.repair_count += 1
        updated.learning_state.sources["repair_renders"] = int(
            updated.learning_state.sources.get("repair_renders", 0)
        ) + 1
    total_after = total_before + 1
    if total_after > 0:
        engine_memory.success_rate = engine_memory.approved_count / float(total_after)

    context = _safe_text(payload.get("context") or payload.get("creative_goal"), max_len=260) or None
    if outcome == "approved":
        if context:
            engine_memory.best_for = _unique_strings([*engine_memory.best_for, context], limit=6)
        _record_successful_combination(
            updated,
            engine=engine or "unknown",
            model=_safe_text(payload.get("model"), max_len=160) or None,
            context=context,
            score=fingerprint.continuity_score or engine_memory.success_rate,
        )
    elif outcome in {"rejected", "needs_repair"}:
        if context:
            engine_memory.avoid_for = _unique_strings([*engine_memory.avoid_for, context], limit=6)

    for color in fingerprint.palette_signature:
        _observe_trait(updated, scope="palette", value=color, source=source_label, weight=0.5)
    for motif in fingerprint.motif_tags:
        _observe_trait(updated, scope="motif", value=motif, source=source_label, weight=0.55)
    for fragment in _prompt_fragments(payload.get("positive_fragments"), limit=4):
        _observe_trait(updated, scope="positive_prompt", value=fragment, source=source_label, weight=0.5)
    for fragment in _prompt_fragments(payload.get("negative_fragments"), limit=4):
        _observe_trait(updated, scope="negative_prompt", value=fragment, source=source_label, weight=0.55)

    subject_anchor = _safe_text(payload.get("subject_anchor"))
    if subject_anchor:
        updated.continuity.subject_anchors = _unique_strings(
            [*updated.continuity.subject_anchors, subject_anchor],
            limit=8,
        )
    environment_anchor = _safe_text(payload.get("environment_anchor"))
    if environment_anchor:
        updated.continuity.environment_anchors = _unique_strings(
            [*updated.continuity.environment_anchors, environment_anchor],
            limit=8,
        )

    if payload.get("failure_pattern"):
        _record_failure(
            updated,
            pattern=payload.get("failure_pattern"),
            mitigation=payload.get("mitigation"),
            source=source_label,
        )

    updated.updated_at = _utc_now()
    _sync_curated_fields(updated)
    _recompute_confidence(updated)
    return updated


def trait_id(scope: str, value: str) -> str:
    return f"{str(scope).strip().lower()}:{_safe_text(value).casefold()}"


def update_visual_dna(
    dna: ProjectVisualDNA,
    *,
    identity: dict[str, Any] | None = None,
    continuity: dict[str, Any] | None = None,
    approve_trait_ids: list[str] | None = None,
    deprecate_trait_ids: list[str] | None = None,
    notes: str | None = None,
) -> ProjectVisualDNA:
    """Apply curated edits without silently rewriting the timeline."""
    updated = dna.model_copy(deep=True)
    source_label = "visual_dna_workspace"

    if isinstance(identity, dict) and identity:
        list_limits = {
            "core_themes": 8,
            "motifs": 10,
            "lighting_language": 6,
            "camera_language": 6,
            "texture_language": 6,
        }
        for key, limit in list_limits.items():
            if key in identity and isinstance(identity.get(key), list):
                setattr(updated.identity, key, _unique_strings(list(identity.get(key) or []), limit=limit))
        palette = identity.get("palette")
        if isinstance(palette, dict):
            if isinstance(palette.get("dominant"), list):
                updated.identity.palette.dominant = _unique_strings(list(palette.get("dominant") or []), limit=8)
            if isinstance(palette.get("avoid"), list):
                updated.identity.palette.avoid = _unique_strings(list(palette.get("avoid") or []), limit=8)

    if isinstance(continuity, dict) and continuity:
        for key in ("subject_anchors", "environment_anchors", "transition_rules"):
            if key in continuity and isinstance(continuity.get(key), list):
                setattr(
                    updated.continuity,
                    key,
                    _unique_strings(list(continuity.get(key) or []), limit=8),
                )

    approve = {str(item).strip().casefold() for item in (approve_trait_ids or []) if str(item).strip()}
    deprecate = {str(item).strip().casefold() for item in (deprecate_trait_ids or []) if str(item).strip()}
    for trait in updated.trait_memory:
        tid = trait_id(str(trait.scope), trait.value).casefold()
        if tid in approve:
            trait.state = "declared"
            trait.weight = min(1.0, max(trait.weight, 0.85))
            if source_label not in trait.sources:
                trait.sources.append(source_label)
            updated.learning_state.sources["approved_traits"] = int(
                updated.learning_state.sources.get("approved_traits", 0)
            ) + 1
        if tid in deprecate:
            trait.state = "deprecated"
            trait.weight = min(trait.weight, 0.2)
            if source_label not in trait.sources:
                trait.sources.append(source_label)
            updated.learning_state.sources["deprecated_traits"] = int(
                updated.learning_state.sources.get("deprecated_traits", 0)
            ) + 1

    note_text = _safe_text(notes, max_len=1000)
    if note_text:
        updated.learning_state.sources["workspace_notes"] = int(
            updated.learning_state.sources.get("workspace_notes", 0)
        ) + 1
        _observe_trait(
            updated,
            scope="theme",
            value=note_text[:160],
            source=source_label,
            state="declared",
            weight=0.7,
        )

    updated.updated_at = _utc_now()
    _sync_curated_fields(updated)
    _recompute_confidence(updated)
    return updated


def build_prompt_hints(dna: ProjectVisualDNA, *, limit: int = 8) -> dict[str, Any]:
    return {
        "positive_fragments": list(dna.prompt_guidance.positive_fragments[:limit]),
        "negative_fragments": list(dna.prompt_guidance.negative_fragments[:limit]),
        "core_themes": list(dna.identity.core_themes[:limit]),
        "motifs": list(dna.identity.motifs[:limit]),
        "palette": {
            "dominant": list(dna.identity.palette.dominant[: min(limit, 6)]),
            "avoid": list(dna.identity.palette.avoid[: min(limit, 6)]),
        },
        "camera_language": list(dna.identity.camera_language[:limit]),
        "lighting_language": list(dna.identity.lighting_language[:limit]),
        "continuity_anchors": {
            "subject": list(dna.continuity.subject_anchors[:limit]),
            "environment": list(dna.continuity.environment_anchors[:limit]),
            "rules": list(dna.continuity.transition_rules[:limit]),
        },
        "style_bias": dict(sorted(dna.prompt_guidance.style_bias.items(), key=lambda item: (-item[1], item[0]))[:limit]),
        "confidence": float(dna.learning_state.confidence),
    }
