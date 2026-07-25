from __future__ import annotations

import hashlib
import json
from typing import Any

from ..schemas import (
    PlanWarning,
    RenderIntent,
    RenderPlan,
    RenderPlanDependency,
    RenderPlanEstimates,
    RenderStep,
    RenderTaskNode,
)


def _stable_hash(parts: dict[str, Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def step_cache_key(
    *,
    project_id: str,
    variant_index: int,
    scene_id: str,
    step: RenderStep,
    engine: str,
    quality_tier: str,
) -> str:
    digest = _stable_hash(
        {
            "project_id": project_id,
            "variant_index": variant_index,
            "scene_id": scene_id,
            "step_id": step.id,
            "kind": step.kind,
            "adapter": step.adapter,
            "engine": engine,
            "quality_tier": quality_tier,
            "inputs": step.inputs,
        }
    )
    return f"rp1:{project_id}:v{variant_index}:{scene_id}:{step.kind}:{digest}"


def _section_step_dependencies(scene_id: str, steps: list[RenderStep]) -> list[RenderPlanDependency]:
    deps: list[RenderPlanDependency] = []
    previous_id: str | None = None
    for step in steps:
        if previous_id:
            deps.append(RenderPlanDependency(**{"from": previous_id, "to": step.id}))
        previous_id = step.id
    if steps:
        deps.append(RenderPlanDependency(**{"from": steps[-1].id, "to": f"{scene_id}-assemble-link"}))
    return deps


def _plan_warnings(plan: RenderPlan, environment: dict[str, Any] | None) -> list[PlanWarning]:
    warnings: list[PlanWarning] = []
    engines = (environment or {}).get("engines") if isinstance((environment or {}).get("engines"), dict) else {}
    for section in plan.sections:
        engine_info = engines.get(section.engine, {}) if isinstance(engines, dict) else {}
        if not bool(engine_info.get("available", True)):
            warnings.append(
                PlanWarning(
                    code="engine_unavailable",
                    message=f"{section.scene_id} routes to {section.engine}, which is unavailable in the current environment.",
                    severity="warning",
                    scene_id=section.scene_id,
                )
            )
        if section.continuity_risk >= 0.72:
            warnings.append(
                PlanWarning(
                    code="continuity_risk",
                    message=f"{section.scene_id} has elevated continuity risk ({section.continuity_risk:.2f}).",
                    severity="warning",
                    scene_id=section.scene_id,
                )
            )
        if section.engine == "proxy":
            warnings.append(
                PlanWarning(
                    code="proxy_lane",
                    message=f"{section.scene_id} is on the proxy lane; promote before final export.",
                    severity="info",
                    scene_id=section.scene_id,
                )
            )
    for diagnostic in plan.diagnostics:
        if diagnostic.startswith("visual_dna_confidence="):
            try:
                confidence = float(diagnostic.split("=", 1)[1])
            except ValueError:
                confidence = 1.0
            if confidence < 0.35:
                warnings.append(
                    PlanWarning(
                        code="low_visual_dna_confidence",
                        message="Visual DNA confidence is low; review approved traits before locking style.",
                        severity="info",
                    )
                )
    if plan.advisory_only:
        warnings.append(
            PlanWarning(
                code="advisory_only",
                message="Plan is advisory; execution still uses existing Studio render routes.",
                severity="info",
            )
        )
    return warnings


def enrich_render_plan(
    plan: RenderPlan | dict[str, Any],
    *,
    intent: RenderIntent | dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
) -> RenderPlan:
    plan_obj = plan if isinstance(plan, RenderPlan) else RenderPlan.model_validate(plan)
    intent_obj = None
    if intent is not None:
        intent_obj = intent if isinstance(intent, RenderIntent) else RenderIntent.model_validate(intent)
    quality_tier = str(intent_obj.quality_tier if intent_obj else "balanced")

    tasks: list[RenderTaskNode] = []
    dependencies: list[RenderPlanDependency] = []
    total_seconds = 0.0
    total_cost = 0.0
    updated_sections = []

    for section in plan_obj.sections:
        per_step_seconds = (
            section.estimated_seconds / max(len(section.steps), 1) if section.estimated_seconds else 0.0
        )
        enriched_steps: list[RenderStep] = []
        for step in section.steps:
            cache_key = step.cache_key or step_cache_key(
                project_id=plan_obj.project_id,
                variant_index=plan_obj.variant_index,
                scene_id=section.scene_id,
                step=step,
                engine=section.engine,
                quality_tier=quality_tier,
            )
            enriched_step = step.model_copy(update={"cache_key": cache_key})
            enriched_steps.append(enriched_step)
            depends_on = [enriched_steps[-2].id] if len(enriched_steps) > 1 else []
            tasks.append(
                RenderTaskNode(
                    id=enriched_step.id,
                    scene_id=section.scene_id,
                    step_kind=enriched_step.kind,
                    adapter=enriched_step.adapter,
                    cache_key=cache_key,
                    depends_on=depends_on,
                    estimated_seconds=round(per_step_seconds, 2),
                )
            )
        dependencies.extend(_section_step_dependencies(section.scene_id, enriched_steps))
        total_seconds += float(section.estimated_seconds or 0.0)
        total_cost += float(section.estimated_cost or 0.0)
        updated_sections.append(section.model_copy(update={"steps": enriched_steps}))

    assembly_id = "assembly-final"
    tasks.append(
        RenderTaskNode(
            id=assembly_id,
            scene_id="*",
            step_kind="assemble",
            adapter="system",
            cache_key=f"rp1:{plan_obj.project_id}:v{plan_obj.variant_index}:assembly:{plan_obj.assembly.mode}",
            depends_on=[task.id for task in tasks if task.scene_id != "*"][-3:],
            estimated_seconds=round(max(2.0, total_seconds * 0.05), 1),
        )
    )
    for section in plan_obj.sections:
        section_steps = [task.id for task in tasks if task.scene_id == section.scene_id]
        if section_steps:
            dependencies.append(RenderPlanDependency(**{"from": section_steps[-1], "to": assembly_id}))

    estimates = RenderPlanEstimates(
        seconds=round(total_seconds + tasks[-1].estimated_seconds, 1),
        cost=round(total_cost, 3),
        task_count=len(tasks),
    )
    warnings = _plan_warnings(plan_obj, environment)

    return plan_obj.model_copy(
        update={
            "sections": updated_sections,
            "tasks": tasks,
            "dependencies": dependencies,
            "estimates": estimates,
            "warnings": warnings,
        }
    )
