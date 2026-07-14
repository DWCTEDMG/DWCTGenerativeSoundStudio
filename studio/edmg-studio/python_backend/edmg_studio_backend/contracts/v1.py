"""Version 1 cross-domain contracts for persisted Studio documents.

These models deliberately live beside the existing API schemas.  They freeze the
inter-domain and on-disk vocabulary without forcing a rewrite of the current
project store, Render Conductor, or canonical internal renderer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

CONTRACT_SCHEMA_VERSION = "1.0"


def utc_now() -> datetime:
    """Return a timezone-aware timestamp suitable for persisted contracts."""

    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Strict base for contract components."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VersionedDocument(ContractModel):
    """Fields shared by every top-level persisted contract."""

    schema_version: Literal["1.0"] = CONTRACT_SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: object) -> object:
        if value in (None, ""):
            return utc_now()
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> VersionedDocument:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class AssetRef(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    relative_path: str = Field(min_length=1, max_length=2048)
    media_type: str | None = Field(default=None, max_length=160)
    content_hash: str | None = Field(default=None, max_length=160)
    size_bytes: int | None = Field(default=None, ge=0)


class ProjectContract(VersionedDocument):
    """Authored project state; derived analysis and render output stay referenced."""

    contract_type: Literal["edmg.project"] = "edmg.project"
    name: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    audio: AssetRef | None = None
    timeline: dict[str, JsonValue] = Field(default_factory=dict)
    music_graph_ref: AssetRef | None = None
    creative_intent_ref: AssetRef | None = None
    render_plan_refs: list[AssetRef] = Field(default_factory=list)
    artifact_refs: list[AssetRef] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)


class TimedEvent(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    time_seconds: float = Field(ge=0.0)
    value: JsonValue = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TimedRange(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> TimedRange:
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return self


class SectionRange(TimedRange):
    label: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0.0, le=1.0)


class TimedWord(TimedRange):
    text: str = Field(min_length=1, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class WeightedTag(ContractModel):
    tag: str = Field(min_length=1, max_length=160)
    weight: float = Field(ge=0.0, le=1.0)


class CurveRef(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    asset: AssetRef | None = None
    values: list[float] | None = None
    sample_hz: float | None = Field(default=None, gt=0.0)
    units: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_curve_source(self) -> CurveRef:
        if self.asset is None and self.values is None:
            raise ValueError("a curve must contain inline values or reference an asset")
        return self


class MusicTimebase(ContractModel):
    sample_rate: int = Field(gt=0)
    fps_hint: float | None = Field(default=None, gt=0.0)
    duration_seconds: float = Field(ge=0.0)


class TempoMap(ContractModel):
    bpm: float = Field(gt=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    variable_tempo: list[TimedEvent] = Field(default_factory=list)


class Meter(ContractModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)


class StemAnalysis(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=120)
    asset: AssetRef | None = None
    features: dict[str, CurveRef] = Field(default_factory=dict)


class LyricsAnalysis(ContractModel):
    language: str | None = Field(default=None, max_length=40)
    words: list[TimedWord] = Field(default_factory=list)
    lines: list[TimedRange] = Field(default_factory=list)


class HarmonyAnalysis(ContractModel):
    key: str | None = Field(default=None, max_length=80)
    chords: list[TimedEvent] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class MusicFeatureCurves(ContractModel):
    loudness: CurveRef
    onset_strength: CurveRef
    spectral_flux: CurveRef
    brightness: CurveRef
    harmonicity: CurveRef
    energy_arc: CurveRef


class MusicSemantics(ContractModel):
    tags: list[WeightedTag] = Field(default_factory=list)
    section_tags: dict[str, list[WeightedTag]] = Field(default_factory=dict)


class AnalysisProvenance(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    analyzer: str = Field(min_length=1, max_length=160)
    analyzer_version: str = Field(min_length=1, max_length=120)
    source_hash: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=utc_now)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class MusicGraphContract(VersionedDocument):
    contract_type: Literal["edmg.music_graph"] = "edmg.music_graph"
    source: AssetRef
    timebase: MusicTimebase
    tempo: TempoMap
    meter: Meter
    beats: list[TimedEvent] = Field(default_factory=list)
    bars: list[TimedRange] = Field(default_factory=list)
    sections: list[SectionRange] = Field(default_factory=list)
    stems: list[StemAnalysis] = Field(default_factory=list)
    lyrics: LyricsAnalysis | None = None
    harmony: HarmonyAnalysis | None = None
    features: MusicFeatureCurves
    semantics: MusicSemantics | None = None
    analysis_runs: list[AnalysisProvenance] = Field(default_factory=list)


DirectorMode = Literal["narrative", "performance", "abstract", "lyric", "product", "ambient"]


class WorldBible(ContractModel):
    summary: str = Field(default="", max_length=4000)
    locations: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


class ContinuityAnchor(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    reference_asset_ids: list[str] = Field(default_factory=list)


class VisualGrammar(ContractModel):
    palette: list[str] = Field(default_factory=list)
    texture: list[str] = Field(default_factory=list)
    lenses: list[str] = Field(default_factory=list)
    composition_rules: list[str] = Field(default_factory=list)
    motion_character: list[str] = Field(default_factory=list)
    forbidden_traits: list[str] = Field(default_factory=list)


class CreativeBudget(ContractModel):
    priority: Literal["speed", "balanced", "quality"] = "balanced"
    max_compute_minutes: float | None = Field(default=None, gt=0.0)
    max_cost: float | None = Field(default=None, ge=0.0)


class AccessibilityIntent(ContractModel):
    avoid_flashes_above_hz: float | None = Field(default=None, gt=0.0)
    safe_text_zones: bool | None = None


class CreativeIntentContract(VersionedDocument):
    contract_type: Literal["edmg.creative_intent"] = "edmg.creative_intent"
    project_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(default=1, ge=1)
    director_mode: DirectorMode
    concept: str = Field(min_length=1, max_length=4000)
    audience: str | None = Field(default=None, max_length=1000)
    aspect_ratios: list[str] = Field(default_factory=lambda: ["16:9"])
    world: WorldBible = Field(default_factory=WorldBible)
    continuity: list[ContinuityAnchor] = Field(default_factory=list)
    visual_grammar: VisualGrammar = Field(default_factory=VisualGrammar)
    budget: CreativeBudget = Field(default_factory=CreativeBudget)
    accessibility: AccessibilityIntent | None = None


class CapabilityRequirement(ContractModel):
    media: Literal["image", "video", "audio", "mask", "depth", "scene"]
    operation: Literal["generate", "transform", "extend", "upscale", "interpolate", "assemble"]
    controls: list[
        Literal["text", "image", "first_frame", "last_frame", "audio", "pose", "depth", "mask"]
    ] = Field(default_factory=list)
    locality: Literal["in_process", "local_service", "remote"] | None = None


class RenderTaskContract(ContractModel):
    id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=160)
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    cache_key: str | None = Field(default=None, max_length=256)


class RenderDependency(ContractModel):
    from_task: str = Field(min_length=1, max_length=160)
    to_task: str = Field(min_length=1, max_length=160)


class RenderAllocation(ContractModel):
    task_id: str = Field(min_length=1, max_length=160)
    capability: CapabilityRequirement
    preferred_provider: str | None = Field(default=None, max_length=160)
    fallbacks: list[str] = Field(default_factory=list)


class RenderEstimates(ContractModel):
    seconds: float = Field(default=0.0, ge=0.0)
    vram_gb: float | None = Field(default=None, ge=0.0)
    disk_gb: float = Field(default=0.0, ge=0.0)
    cost: float | None = Field(default=None, ge=0.0)


class PlanWarning(ContractModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    severity: Literal["info", "warning", "error"] = "warning"
    task_id: str | None = Field(default=None, max_length=160)


class RenderPlanContract(VersionedDocument):
    contract_type: Literal["edmg.render_plan"] = "edmg.render_plan"
    project_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(default=1, ge=1)
    intent_revision: str = Field(min_length=1, max_length=160)
    project_revision: str = Field(min_length=1, max_length=160)
    tasks: list[RenderTaskContract] = Field(default_factory=list)
    dependencies: list[RenderDependency] = Field(default_factory=list)
    allocations: list[RenderAllocation] = Field(default_factory=list)
    estimates: RenderEstimates = Field(default_factory=RenderEstimates)
    warnings: list[PlanWarning] = Field(default_factory=list)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> RenderPlanContract:
        task_ids = {task.id for task in self.tasks}
        if len(task_ids) != len(self.tasks):
            raise ValueError("render task IDs must be unique")
        referenced = {
            value
            for dependency in self.dependencies
            for value in (dependency.from_task, dependency.to_task)
        }
        referenced.update(allocation.task_id for allocation in self.allocations)
        missing = sorted(referenced - task_ids)
        if missing:
            raise ValueError(f"render plan references unknown task IDs: {', '.join(missing)}")
        return self


class ModelIdentity(ContractModel):
    repository: str | None = Field(default=None, max_length=500)
    revision: str | None = Field(default=None, max_length=200)


class ArtifactManifestContract(VersionedDocument):
    contract_type: Literal["edmg.artifact"] = "edmg.artifact"
    project_id: str = Field(min_length=1, max_length=160)
    relative_path: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(min_length=8, max_length=160)
    source_asset_hashes: list[str] = Field(default_factory=list)
    scene_id: str | None = Field(default=None, max_length=160)
    plan_revision: str = Field(min_length=1, max_length=160)
    project_revision: str = Field(min_length=1, max_length=160)
    engine: str = Field(min_length=1, max_length=160)
    provider: str | None = Field(default=None, max_length=160)
    model: ModelIdentity = Field(default_factory=ModelIdentity)
    runtime_versions: dict[str, str] = Field(default_factory=dict)
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    seed: int | None = None
    hardware: dict[str, JsonValue] = Field(default_factory=dict)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    safety: dict[str, JsonValue] = Field(default_factory=dict)
    license: dict[str, JsonValue] = Field(default_factory=dict)
    parent_artifact_ids: list[str] = Field(default_factory=list)
    child_artifact_ids: list[str] = Field(default_factory=list)
    review_state: Literal["unreviewed", "approved", "rejected", "repair"] = "unreviewed"
    approved_visual_dna_updates: list[str] = Field(default_factory=list)


class CapabilityContract(VersionedDocument):
    contract_type: Literal["edmg.capability"] = "edmg.capability"
    provider_id: str = Field(min_length=1, max_length=160)
    media: Literal["image", "video", "audio", "mask", "depth", "scene"]
    operation: Literal["generate", "transform", "extend", "upscale", "interpolate", "assemble"]
    controls: list[
        Literal["text", "image", "first_frame", "last_frame", "audio", "pose", "depth", "mask"]
    ] = Field(default_factory=list)
    max_duration_seconds: float | None = Field(default=None, gt=0.0)
    resolutions: list[str] = Field(default_factory=list)
    deterministic: bool
    supports_cancel: bool
    locality: Literal["in_process", "local_service", "remote"]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled", "paused", "blocked"]


class JobContract(VersionedDocument):
    contract_type: Literal["edmg.job"] = "edmg.job"
    project_id: str = Field(min_length=1, max_length=160)
    job_type: str = Field(min_length=1, max_length=160)
    status: JobStatus
    priority: int = 0
    plan_id: str | None = Field(default=None, max_length=160)
    task_id: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, max_length=256)
    attempt: int = Field(default=0, ge=0)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    result: dict[str, JsonValue] | None = None
    error: str | None = Field(default=None, max_length=8000)
    progress: dict[str, JsonValue] | None = None


class CueContract(VersionedDocument):
    contract_type: Literal["edmg.cue"] = "edmg.cue"
    project_id: str = Field(min_length=1, max_length=160)
    cue_type: str = Field(min_length=1, max_length=160)
    time_seconds: float = Field(ge=0.0)
    frame: int | None = Field(default=None, ge=0)
    transport: Literal["internal", "osc", "midi", "websocket", "unreal", "touchdesigner"] = (
        "internal"
    )
    target: str | None = Field(default=None, max_length=500)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


CONTRACT_MODELS: dict[str, type[VersionedDocument]] = {
    "edmg.project": ProjectContract,
    "edmg.music_graph": MusicGraphContract,
    "edmg.creative_intent": CreativeIntentContract,
    "edmg.render_plan": RenderPlanContract,
    "edmg.artifact": ArtifactManifestContract,
    "edmg.capability": CapabilityContract,
    "edmg.job": JobContract,
    "edmg.cue": CueContract,
}


def contract_schema_bundle() -> dict[str, JsonValue]:
    """Return JSON Schema for every frozen v1 top-level contract."""

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contracts": {
            contract_type: model.model_json_schema()
            for contract_type, model in CONTRACT_MODELS.items()
        },
    }
