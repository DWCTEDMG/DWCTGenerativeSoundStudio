from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

RENDER_PROFILE_SCHEMA_VERSION = "1.0"
ACCEPTED_RENDER_SNAPSHOT_KEY = "_accepted_render_snapshot"
ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY = "_accepted_render_snapshot_digest"


class RenderProfileOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: Literal["fast", "balanced", "quality", "ultra"] = "balanced"
    width: int = Field(default=1024, ge=64, le=16384)
    height: int = Field(default=576, ge=64, le=16384)
    fps: int = Field(default=30, ge=1, le=240)
    renderer_id: str = Field(default="auto", min_length=1, max_length=160)


class ProjectRenderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = RENDER_PROFILE_SCHEMA_VERSION
    id: str = Field(default="default", min_length=1, max_length=160)
    name: str = Field(default="Project render profile", min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    shared: RenderProfileOptions = Field(default_factory=RenderProfileOptions)
    renderer_options: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)


class AcceptedRenderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = RENDER_PROFILE_SCHEMA_VERSION
    payload: dict[str, JsonValue]
    render_profile: ProjectRenderProfile | None = None


def canonical_render_snapshot_json(snapshot: AcceptedRenderSnapshot | dict[str, Any]) -> str:
    value = snapshot.model_dump(mode="json") if isinstance(snapshot, AcceptedRenderSnapshot) else snapshot
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_snapshot_digest(snapshot: AcceptedRenderSnapshot | dict[str, Any]) -> str:
    encoded = canonical_render_snapshot_json(snapshot).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def accept_render_payload(
    payload: dict[str, Any],
    *,
    render_profile: ProjectRenderProfile | dict[str, Any] | None = None,
) -> dict[str, Any]:
    accepted_payload = deepcopy(payload)
    accepted_payload.pop(ACCEPTED_RENDER_SNAPSHOT_KEY, None)
    accepted_payload.pop(ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY, None)
    profile = None if render_profile is None else ProjectRenderProfile.model_validate(render_profile)
    snapshot = AcceptedRenderSnapshot(payload=accepted_payload, render_profile=profile)
    snapshot_data = snapshot.model_dump(mode="json")
    accepted_payload[ACCEPTED_RENDER_SNAPSHOT_KEY] = snapshot_data
    accepted_payload[ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY] = render_snapshot_digest(snapshot_data)
    return accepted_payload


def retain_accepted_render_snapshot(original: dict[str, Any], replacement: dict[str, Any]) -> dict[str, Any]:
    snapshot = original.get(ACCEPTED_RENDER_SNAPSHOT_KEY)
    digest = original.get(ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY)
    if not isinstance(snapshot, dict) or not isinstance(digest, str):
        return deepcopy(replacement)
    AcceptedRenderSnapshot.model_validate(snapshot)
    if render_snapshot_digest(snapshot) != digest:
        raise ValueError("Accepted render snapshot digest does not match the stored snapshot")
    retained = deepcopy(replacement)
    retained[ACCEPTED_RENDER_SNAPSHOT_KEY] = deepcopy(snapshot)
    retained[ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY] = digest
    return retained


def accepted_render_request_matches(accepted: dict[str, Any], requested: dict[str, Any]) -> bool:
    snapshot = accepted.get(ACCEPTED_RENDER_SNAPSHOT_KEY)
    digest = accepted.get(ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY)
    if not isinstance(snapshot, dict) or not isinstance(digest, str):
        return accepted == requested
    try:
        validated = AcceptedRenderSnapshot.model_validate(snapshot)
    except ValueError:
        return False
    return render_snapshot_digest(snapshot) == digest and validated.payload == requested


def is_render_job_type(job_type: str) -> bool:
    normalized = str(job_type).strip().lower()
    return normalized in {"internal_video", "provider_generation"} or any(
        token in normalized for token in ("render", "animation", "assemble")
    )
