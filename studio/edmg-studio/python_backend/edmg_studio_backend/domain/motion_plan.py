"""Canonical, reviewable motion handoff for Director and Reactive Lab."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import Field

from .director_scene import ExtensibleModel


class MotionPlan(ExtensibleModel):
    """Constrained motion/camera output owned by a Director draft."""

    version: Literal[1] = 1
    status: Literal["draft", "reviewed", "applied"] = "draft"
    source_direction_draft_id: str = ""
    source_revision: int = Field(default=1, ge=1)
    reactive_overrides: dict = Field(default_factory=dict)
    reactive_extensions: dict = Field(default_factory=dict)
    camera_schedule: list[dict] = Field(default_factory=list)
    motion_schedule: list[dict] = Field(default_factory=list)
    beat_markers: list[dict] = Field(default_factory=list)
    cue_events: list[dict] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    repair_suggestions: list[dict] = Field(default_factory=list)
    schedules: dict = Field(default_factory=dict)
    handoff_manifest: dict = Field(default_factory=dict)
    parseq_manifest: dict | None = None
    metadata: dict = Field(default_factory=dict)
    review: dict = Field(default_factory=dict)

    @classmethod
    def from_reactive_projection(cls, draft, projection: dict, *,
                                 status: Literal["draft", "reviewed", "applied"] = "draft",
                                 review: dict | None = None) -> "MotionPlan":
        handoff = deepcopy(projection.get("handoff_manifest") or {})
        parseq = projection.get("parseq_manifest") or handoff.get("parseq_manifest")
        return cls(
            status=status,
            source_direction_draft_id=draft.draft_id,
            source_revision=draft.source_revision,
            reactive_overrides=deepcopy(draft.reactive_overrides),
            reactive_extensions=deepcopy(draft.reactive_extensions),
            camera_schedule=deepcopy(draft.schedule.get("camera_keys") or []),
            motion_schedule=deepcopy(draft.schedule.get("motion_keys") or []),
            beat_markers=deepcopy(projection.get("beat_markers") or []),
            cue_events=deepcopy(projection.get("cue_events") or []),
            sections=deepcopy(projection.get("sections") or []),
            repair_suggestions=deepcopy(projection.get("repair_suggestions") or []),
            schedules=deepcopy(projection.get("schedules") or {}),
            handoff_manifest=handoff,
            parseq_manifest=deepcopy(parseq) if isinstance(parseq, dict) else None,
            metadata=deepcopy(projection.get("metadata") or {}),
            review=deepcopy(review or {}),
        )
