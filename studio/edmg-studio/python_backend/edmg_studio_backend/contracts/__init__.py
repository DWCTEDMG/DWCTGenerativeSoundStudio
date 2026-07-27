"""Public, versioned contracts shared across Studio domains."""

from .compat import (
    adapt_legacy_cue,
    adapt_legacy_job,
    adapt_legacy_project,
    adapt_legacy_render_plan,
)
from .v1 import (
    CONTRACT_MODELS,
    CONTRACT_SCHEMA_VERSION,
    ArtifactManifestContract,
    CapabilityContract,
    CreativeIntentContract,
    CueContract,
    JobContract,
    MusicGraphContract,
    ProjectContract,
    RenderPlanContract,
    contract_schema_bundle,
)

__all__ = [
    "CONTRACT_MODELS",
    "CONTRACT_SCHEMA_VERSION",
    "ArtifactManifestContract",
    "CapabilityContract",
    "CreativeIntentContract",
    "CueContract",
    "JobContract",
    "MusicGraphContract",
    "ProjectContract",
    "RenderPlanContract",
    "adapt_legacy_cue",
    "adapt_legacy_job",
    "adapt_legacy_project",
    "adapt_legacy_render_plan",
    "contract_schema_bundle",
]
