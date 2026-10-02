"""Provider-neutral, versioned contracts for AI Director planning.

Model output is deliberately represented as untrusted proposal data.  Only the
existing Director review/apply workflow may turn a validated plan into project
state, keeping provider code outside the mutation boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .director_scene import DirectorDocument

DIRECTOR_PLAN_SCHEMA_VERSION = "1.0"
NEMOTRON_MODEL_ID = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16"
COSMOS_MODEL_ID = "nvidia/Cosmos-Reason2-8B"


class SpecialistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    task: Literal["video_analysis", "continuity", "motion", "spatial", "physical"]
    instruction: str = Field(min_length=1, max_length=16_000)
    context: dict[str, Any] = Field(default_factory=dict)


class SpecialistResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = DIRECTOR_PLAN_SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    specialist: Literal["cosmos_reason2"] = "cosmos_reason2"
    evidence: list[str] = Field(default_factory=list, max_length=128)
    continuity_risks: list[str] = Field(default_factory=list, max_length=128)
    motion_notes: list[str] = Field(default_factory=list, max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DirectorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(min_length=1, max_length=120)
    rationale: str = Field(default="", max_length=2_000)
    preferred_renderer: str | None = Field(default=None, max_length=80)


class DirectorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = DIRECTOR_PLAN_SCHEMA_VERSION
    correlation_id: str = Field(min_length=1, max_length=128)
    director_model: str = Field(min_length=1, max_length=256)
    mode: Literal["fast", "standard", "advanced"] = "standard"
    document: DirectorDocument
    decisions: list[DirectorDecision] = Field(default_factory=list, max_length=256)
    specialist_results: list[SpecialistResult] = Field(default_factory=list, max_length=32)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_scenes(self) -> "DirectorPlan":
        if not self.document.scenes:
            raise ValueError("DirectorPlan must contain at least one scene")
        return self


def validate_plan_locks(plan: DirectorPlan, context: dict[str, Any]) -> DirectorPlan:
    """Reject plans that change locked scenes or locked timeline ranges."""

    locked_scene_ids = {
        str(value) for value in context.get("locked_scene_ids", []) if str(value).strip()
    }
    source_document = context.get("source_document")
    if locked_scene_ids and isinstance(source_document, dict):
        original = DirectorDocument.model_validate(source_document)
        original_by_id = {scene.scene_id: scene for scene in original.scenes}
        proposed_by_id = {scene.scene_id: scene for scene in plan.document.scenes}
        for scene_id in locked_scene_ids:
            if scene_id not in original_by_id or proposed_by_id.get(scene_id) != original_by_id[scene_id]:
                raise ValueError(f"DirectorPlan changes locked scene {scene_id}")
    return plan
