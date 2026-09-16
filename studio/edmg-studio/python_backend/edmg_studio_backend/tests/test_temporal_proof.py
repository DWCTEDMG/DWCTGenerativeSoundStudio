from __future__ import annotations

from pathlib import Path

from edmg_studio_backend.services.temporal_proof import build_temporal_proof, validate_temporal_proof


def _proof(project: Path, *, route: str = "internal"):
    artifact = project / "renders" / "video.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"real-render-bytes")
    return build_temporal_proof(
        project_dir=project,
        project_id="project-1",
        project_revision=7,
        artifact_path=artifact,
        schedule_identity="schedule-sha256",
        model_fingerprint="model-sha256",
        runtime_fingerprint="runtime-sha256",
        device_fingerprint="cuda-device-sha256",
        codec="h264",
        width=1920,
        height=1080,
        frame_rate=24,
        duration_seconds=2,
        has_audio=True,
        motion_evidence={
            "status": "pass",
            "failures": [],
            "frame_count": 12,
            "perceptually_unique_frames": 12,
            "meaningful_transition_count": 8,
            "required_meaningful_transition_count": 3,
            "motion_quartiles": [0, 1, 2, 3],
            "thresholds": {
                "minimum_frames": 8,
                "minimum_unique_frames": 4,
                "minimum_motion_quartiles": 3,
            },
        },
        lineage={"render_job_id": "job-1", "source_artifacts": ["audio.wav"]},
        route=route,
    )


def test_valid_temporal_proof_verifies_artifact_and_hash(tmp_path):
    proof = _proof(tmp_path)
    assert validate_temporal_proof(proof, project_dir=tmp_path) == []


def test_temporal_proof_rejects_hosted_and_still_claims(tmp_path):
    proof = _proof(tmp_path, route="hosted")
    proof.motion_evidence = {"status": "still", "unique_frame_count": 1, "meaningful_transition_count": 0}
    issues = validate_temporal_proof(proof, project_dir=tmp_path)
    assert any("internal motion artifact" in issue for issue in issues)
    assert any("temporal sequence" in issue for issue in issues)


def test_temporal_proof_rejects_modified_artifact(tmp_path):
    proof = _proof(tmp_path)
    (tmp_path / proof.artifact_path).write_bytes(b"tampered")
    assert any("hash" in issue for issue in validate_temporal_proof(proof, project_dir=tmp_path))
