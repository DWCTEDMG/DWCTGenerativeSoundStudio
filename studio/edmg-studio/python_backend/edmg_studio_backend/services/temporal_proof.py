from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..schemas import TemporalProofReceipt

TEMPORAL_PROOF_VERSION = 1
_DISALLOWED_PROOF_ROUTES = {"still", "stills", "proxy", "hosted", "cache", "cached"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_temporal_proof(
    *,
    project_dir: Path,
    project_id: str,
    project_revision: int | str,
    artifact_path: Path,
    schedule_identity: str,
    model_fingerprint: str,
    runtime_fingerprint: str,
    device_fingerprint: str,
    codec: str,
    width: int,
    height: int,
    frame_rate: float,
    duration_seconds: float,
    has_audio: bool,
    motion_evidence: Mapping[str, Any],
    lineage: Mapping[str, Any],
    route: str = "internal",
) -> TemporalProofReceipt:
    root = project_dir.resolve()
    artifact = artifact_path.resolve()
    try:
        relative = artifact.relative_to(root)
    except ValueError as exc:
        raise ValueError("Temporal proof artifact must be inside the project directory") from exc
    if not artifact.is_file():
        raise ValueError("Temporal proof artifact does not exist")
    return TemporalProofReceipt(
        schema_version=TEMPORAL_PROOF_VERSION,
        receipt_timestamp=datetime.now(timezone.utc),
        project_id=project_id,
        project_revision=str(project_revision),
        applied_schedule_identity=schedule_identity,
        route=route,
        model_fingerprint=model_fingerprint,
        runtime_fingerprint=runtime_fingerprint,
        device_fingerprint=device_fingerprint,
        codec=codec,
        width=width,
        height=height,
        frame_rate=frame_rate,
        duration_seconds=duration_seconds,
        has_audio=has_audio,
        motion_evidence=dict(motion_evidence),
        artifact_path=relative.as_posix(),
        content_sha256=sha256_file(artifact),
        lineage=dict(lineage),
    )


def validate_temporal_proof(
    proof: TemporalProofReceipt | Mapping[str, Any],
    *,
    project_dir: Path,
) -> list[str]:
    receipt = proof if isinstance(proof, TemporalProofReceipt) else TemporalProofReceipt.model_validate(proof)
    issues: list[str] = []
    route = receipt.route.strip().lower()
    if route in _DISALLOWED_PROOF_ROUTES or route != "internal":
        issues.append("Only a locally rendered internal motion artifact can provide internal temporal proof.")
    evidence = receipt.motion_evidence
    failures = evidence.get("failures")
    if (
        str(evidence.get("status") or "").lower() != "pass"
        or not isinstance(failures, list)
        or failures
        or int(evidence.get("frame_count") or 0) < int(evidence.get("thresholds", {}).get("minimum_frames") or 2)
        or int(evidence.get("perceptually_unique_frames") or 0) < int(evidence.get("thresholds", {}).get("minimum_unique_frames") or 4)
        or int(evidence.get("meaningful_transition_count") or 0) < int(evidence.get("required_meaningful_transition_count") or 1)
        or len(evidence.get("motion_quartiles") or []) < int(evidence.get("thresholds", {}).get("minimum_motion_quartiles") or 3)
    ):
        issues.append("Motion evidence does not demonstrate a genuine distributed temporal sequence.")
    root = project_dir.resolve()
    artifact = (root / receipt.artifact_path).resolve()
    try:
        artifact.relative_to(root)
    except ValueError:
        issues.append("Artifact path escapes the project directory.")
        return issues
    if not artifact.is_file():
        issues.append("Referenced temporal artifact does not exist.")
    elif sha256_file(artifact) != receipt.content_sha256.lower():
        issues.append("Referenced temporal artifact hash does not match the receipt.")
    if not receipt.lineage:
        issues.append("Artifact lineage/provenance is required.")
    return issues


def write_temporal_proof(path: Path, proof: TemporalProofReceipt) -> None:
    path.write_text(json.dumps(proof.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
