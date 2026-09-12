"""Typed, deterministic Director review contracts and scoring."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REVIEW_DIMENSIONS = (
    "character_consistency",
    "wardrobe_consistency",
    "environment_consistency",
    "intended_action_presence",
    "subject_motion",
    "camera_motion",
    "artifact_detection_quality",
    "temporal_coherence",
    "previous_scene_continuity",
    "visual_style_consistency",
)
MAX_SAMPLES = 12
MAX_RETRY_ATTEMPTS = 5


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReviewRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    artifact_path: str = Field(min_length=1, max_length=1024)
    sample_count: int = Field(default=6, ge=1, le=MAX_SAMPLES)
    threshold: float = Field(default=0.75, ge=0, le=1)
    max_attempts: int = Field(default=2, ge=1, le=MAX_RETRY_ATTEMPTS)
    request_clip_understanding: bool = False
    target_scene_id: str | None = Field(default=None, min_length=1, max_length=128)
    retry_of_report_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FrameEvidence(StrictModel):
    timestamp_seconds: float = Field(ge=0)
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class DimensionScore(StrictModel):
    dimension: Literal[
        "character_consistency", "wardrobe_consistency", "environment_consistency",
        "intended_action_presence", "subject_motion", "camera_motion",
        "artifact_detection_quality", "temporal_coherence",
        "previous_scene_continuity", "visual_style_consistency",
    ]
    state: Literal["assessed", "not_assessed", "unavailable"]
    score: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class ReviewFinding(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    dimension: str
    message: str
    scene_id: str | None = None


class ClipUnderstandingResult(StrictModel):
    requested: bool
    state: Literal["disabled", "available", "unavailable"]
    capability: str = "clip_understanding"
    detail: str


class CorrectionPlan(StrictModel):
    state: Literal["not_needed", "proposed", "unavailable", "applied"]
    target_scene_id: str | None = None
    guidance: list[str] = Field(default_factory=list, max_length=10)
    director_document: dict[str, Any] | None = None
    applied_revision: int | None = None


class RetryAttempt(StrictModel):
    attempt: int = Field(ge=1, le=MAX_RETRY_ATTEMPTS)
    report_id: str
    created_at: str
    aggregate_score: float | None = Field(default=None, ge=0, le=1)
    disposition: str


class RetryPolicy(StrictModel):
    threshold: float = Field(ge=0, le=1)
    max_attempts: int = Field(ge=1, le=MAX_RETRY_ATTEMPTS)
    attempt: int = Field(ge=1, le=MAX_RETRY_ATTEMPTS)
    result: Literal["approved", "recommended", "exhausted"]
    history: list[RetryAttempt] = Field(default_factory=list)


class ReviewReport(StrictModel):
    schema_version: Literal[1] = 1
    report_id: str
    request_fingerprint: str
    project_id: str
    project_revision: int = Field(ge=1)
    source_draft_id: str | None = None
    source_draft_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retry_chain_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(ge=0)
    status: Literal["completed"] = "completed"
    disposition: Literal["approved", "correction_recommended", "correction_exhausted"]
    created_at: str
    duration_seconds: float = Field(gt=0)
    samples: list[FrameEvidence]
    dimensions: list[DimensionScore]
    aggregate_score: float | None = Field(default=None, ge=0, le=1)
    continuity_score: float | None = Field(default=None, ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    findings: list[ReviewFinding] = Field(default_factory=list)
    correction_plan: CorrectionPlan
    retry: RetryPolicy
    clip_understanding: ClipUnderstandingResult
    provenance: dict[str, Any]


class ApplyCorrectionRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def stable_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sample_timestamps(duration_seconds: float, count: int) -> list[float]:
    """Select bin midpoints, avoiding unstable first/last frames."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("Rendered video duration must be positive and finite")
    bounded_count = max(1, min(MAX_SAMPLES, int(count)))
    return [round(duration_seconds * (index + 0.5) / bounded_count, 6) for index in range(bounded_count)]


def aggregate_scores(dimensions: list[DimensionScore]) -> tuple[float | None, float | None]:
    assessed = [item.score for item in dimensions if item.state == "assessed" and item.score is not None]
    continuity_names = {"previous_scene_continuity", "temporal_coherence"}
    continuity = [item.score for item in dimensions
                  if item.dimension in continuity_names and item.state == "assessed" and item.score is not None]
    aggregate = round(sum(assessed) / len(assessed), 4) if assessed else None
    continuity_score = round(sum(continuity) / len(continuity), 4) if continuity else None
    return aggregate, continuity_score
