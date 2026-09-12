"""Bounded local evidence collection for Director Review."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any

from ..domain.continuity_validation import validate_project_continuity
from ..domain.director_review import (
    REVIEW_DIMENSIONS,
    ClipUnderstandingResult,
    CorrectionPlan,
    DimensionScore,
    FrameEvidence,
    RetryAttempt,
    RetryPolicy,
    ReviewFinding,
    ReviewReport,
    aggregate_scores,
    sample_timestamps,
    stable_digest,
    utc_now,
)
from ..domain.director_scene import DirectorDocument
from .ffmpeg import _probe_duration_seconds, ensure_ffmpeg

VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_video_artifact(project_dir: Path, artifact_path: str) -> tuple[str, Path]:
    value = str(artifact_path or "").strip().replace("\\", "/")
    relative = Path(value)
    windows = PureWindowsPath(value)
    if not value or relative.is_absolute() or windows.is_absolute() or windows.drive or ".." in relative.parts:
        raise ValueError("artifact_path must be project-relative")
    root = project_dir.resolve()
    candidate = (root / relative).resolve()
    videos = (root / "outputs" / "videos").resolve()
    try:
        candidate.relative_to(videos)
    except ValueError as exc:
        raise ValueError("artifact_path must identify a rendered project video") from exc
    if candidate.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("artifact_path must identify a supported video")
    if not candidate.is_file():
        raise ValueError("Rendered video artifact not found")
    return str(candidate.relative_to(root)).replace("\\", "/"), candidate


def extract_samples(ffmpeg_path: str, project_dir: Path, video: Path, report_id: str,
                    duration: float, count: int) -> list[FrameEvidence]:
    executable = ensure_ffmpeg(ffmpeg_path)
    root = project_dir.resolve()
    output_dir = (root / "reviews" / "director" / "samples" / report_id).resolve()
    output_dir.relative_to(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    samples: list[FrameEvidence] = []
    for index, timestamp in enumerate(sample_timestamps(duration, count)):
        output = output_dir / f"frame-{index + 1:02d}.jpg"
        proc = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.6f}",
             "-i", str(video), "-frames:v", "1", "-q:v", "2", "-y", str(output)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not output.is_file():
            raise RuntimeError(f"FFmpeg frame extraction failed at {timestamp:.6f}s: {(proc.stderr or '').strip()}")
        samples.append(FrameEvidence(timestamp_seconds=timestamp,
                                     path=str(output.relative_to(root)).replace("\\", "/"),
                                     sha256=sha256_file(output), bytes=output.stat().st_size))
    return samples


def _continuity_evidence(meta: dict[str, Any]) -> tuple[DimensionScore, list[ReviewFinding]]:
    validation = validate_project_continuity(
        plan=meta.get("last_plan"), visual_dna=meta.get("visual_dna"),
        conductor_plan=meta.get("last_conductor_plan"),
    )
    warnings = list(validation.get("warnings") or [])
    if not validation.get("scene_count"):
        return DimensionScore(dimension="previous_scene_continuity", state="not_assessed",
                              evidence=["No pre-render scene continuity data was available."]), []
    penalty = min(1.0, sum(0.35 if item.get("severity") == "error" else
                           0.15 if item.get("severity") == "warn" else 0.05 for item in warnings))
    findings = [ReviewFinding(code=str(item.get("code") or "continuity_warning"),
                              severity="error" if item.get("severity") == "error" else
                                       "warning" if item.get("severity") == "warn" else "info",
                              dimension="previous_scene_continuity", message=str(item.get("message") or ""),
                              scene_id=str(item.get("scene_id")) if item.get("scene_id") else None)
                for item in warnings]
    return DimensionScore(dimension="previous_scene_continuity", state="assessed",
                          score=round(1.0 - penalty, 4),
                          evidence=[f"Existing pre-render continuity validation produced {len(warnings)} warning(s)."]), findings


def _correction(meta: dict[str, Any], target_scene_id: str | None,
                findings: list[ReviewFinding]) -> CorrectionPlan:
    raw = meta.get("director_workflow")
    if not isinstance(raw, dict) or raw.get("status") != "draft":
        return CorrectionPlan(state="unavailable", guidance=["Prepare a Director workflow draft before applying correction guidance."])
    document = DirectorDocument.model_validate(raw.get("document") or {})
    index = next((i for i, scene in enumerate(document.scenes) if scene.scene_id == target_scene_id), None)
    target_index = (index + 1) if index is not None else None
    if target_index is None or target_index >= len(document.scenes):
        return CorrectionPlan(state="unavailable", guidance=["Identify a scene that has a following scene to correct."])
    target = document.scenes[target_index]
    if target.renderer_hints.get("locked"):
        return CorrectionPlan(state="unavailable", target_scene_id=target.scene_id,
                              guidance=["The next scene is locked; unlock it before applying guidance."])
    guidance = [item.message[:500] for item in findings if item.severity != "info"][:10]
    if not guidance:
        return CorrectionPlan(state="not_needed", target_scene_id=target.scene_id)
    proposed = document.model_copy(deep=True)
    hints = deepcopy(proposed.scenes[target_index].renderer_hints)
    hints["director_review_guidance"] = guidance
    proposed.scenes[target_index].renderer_hints = hints
    return CorrectionPlan(state="proposed", target_scene_id=target.scene_id, guidance=guidance,
                          director_document=proposed.model_dump(mode="json"))


def create_review(*, project: Any, project_dir: Path, request: Any, ffmpeg_path: str,
                  prior_reports: list[ReviewReport],
                  understanding: Callable[[Path, list[FrameEvidence]], dict[str, Any]] | None = None) -> ReviewReport:
    relative, video = resolve_video_artifact(project_dir, request.artifact_path)
    artifact_hash = sha256_file(video)
    fingerprint = stable_digest({"project_id": project.id, "project_revision": project.revision,
                                 "artifact_path": relative, "artifact_sha256": artifact_hash,
                                 **request.model_dump(mode="json", exclude={"expected_revision", "artifact_path"})})
    report_id = fingerprint
    workflow = project.meta.get("director_workflow") or {}
    source_draft_id = str(workflow.get("draft_id") or "") or None
    source_draft_fingerprint = stable_digest(workflow.get("document")) if workflow.get("document") else None
    duration = _probe_duration_seconds(ffmpeg_path, video)
    if duration is None:
        raise ValueError("Unable to determine rendered video duration with ffprobe")
    samples = extract_samples(ffmpeg_path, project_dir, video, report_id, duration, request.sample_count)

    scores = [DimensionScore(dimension=name, state="not_assessed",
                             evidence=["Local frame/probe evidence cannot support this semantic dimension."])
              for name in REVIEW_DIMENSIONS]
    quality = next(item for item in scores if item.dimension == "artifact_detection_quality")
    quality.state, quality.score = "assessed", 1.0
    quality.evidence = [f"FFmpeg decoded {len(samples)} deterministic sample frame(s)."]
    continuity, findings = _continuity_evidence(project.meta)
    scores[scores.index(next(item for item in scores if item.dimension == "previous_scene_continuity"))] = continuity

    if not request.request_clip_understanding:
        clip = ClipUnderstandingResult(requested=False, state="disabled",
                                       detail="Clip understanding was not requested; no model was invoked.")
    elif understanding is None:
        clip = ClipUnderstandingResult(requested=True, state="unavailable",
                                       detail="Clip understanding capability is unavailable; deterministic review completed.")
    else:
        try:
            result = understanding(video, samples)
            if not isinstance(result, dict):
                raise TypeError("Clip understanding returned an invalid response")
        except (RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            clip = ClipUnderstandingResult(
                requested=True,
                state="unavailable",
                detail=f"Clip understanding failed; deterministic review completed: {exc}",
            )
        else:
            clip = ClipUnderstandingResult(requested=True, state="available",
                                           detail=str(result.get("detail") or "Clip understanding completed."))
            supplied = result.get("scores") if isinstance(result.get("scores"), dict) else {}
            by_name = {item.dimension: item for item in scores}
            for name, value in supplied.items():
                if name in by_name and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 1:
                    by_name[name].state, by_name[name].score = "assessed", float(value)
                    by_name[name].evidence = ["Explicit clip-understanding capability output."]

    aggregate, continuity_score = aggregate_scores(scores)
    semantic_dimensions = {
        "character_consistency", "wardrobe_consistency", "environment_consistency",
        "intended_action_presence", "subject_motion", "camera_motion",
        "temporal_coherence", "visual_style_consistency",
    }
    semantic_assessed = all(
        item.dimension in semantic_dimensions and item.state == "assessed" for item in scores
        if item.dimension in semantic_dimensions
    )
    if not semantic_assessed:
        findings.append(ReviewFinding(
            code="semantic_review_incomplete",
            severity="warning",
            dimension="clip_understanding",
            message="Deterministic evidence cannot approve semantic continuity; inspect the sampled frames or enable clip understanding.",
        ))
    attempt = prior_reports[-1].retry.attempt + 1 if prior_reports else 1
    semantic_values = [item.score for item in scores
                       if item.dimension in semantic_dimensions and item.state == "assessed" and item.score is not None]
    semantic_score = round(sum(semantic_values) / len(semantic_values), 4) if semantic_assessed else None
    approved = semantic_assessed and semantic_score is not None and semantic_score >= request.threshold
    if semantic_assessed and not approved:
        for item in scores:
            if item.dimension in semantic_dimensions and item.score is not None and item.score < request.threshold:
                findings.append(ReviewFinding(
                    code="semantic_score_below_threshold",
                    severity="warning",
                    dimension=item.dimension,
                    message=f"{item.dimension.replace('_', ' ').title()} scored {item.score:.0%}, below the {request.threshold:.0%} approval threshold.",
                ))
    retry_result = "approved" if approved else "exhausted" if attempt >= request.max_attempts else "recommended"
    disposition = "approved" if approved else "correction_exhausted" if retry_result == "exhausted" else "correction_recommended"
    created = utc_now()
    history = [RetryAttempt(attempt=item.retry.attempt, report_id=item.report_id,
                            created_at=item.created_at, aggregate_score=item.aggregate_score,
                            disposition=item.disposition) for item in prior_reports]
    history.append(RetryAttempt(attempt=attempt, report_id=report_id, created_at=created,
                                aggregate_score=aggregate, disposition=disposition))
    correction = (
        CorrectionPlan(state="not_needed")
        if approved
        else CorrectionPlan(
            state="unavailable",
            guidance=["Complete semantic review before applying automatic next-scene guidance."],
        )
        if not semantic_assessed
        else _correction(project.meta, request.target_scene_id, findings)
    )
    return ReviewReport(
        report_id=report_id, request_fingerprint=fingerprint, project_id=project.id,
        project_revision=project.revision, source_draft_id=source_draft_id,
        source_draft_fingerprint=source_draft_fingerprint,
        retry_chain_id=prior_reports[0].retry_chain_id if prior_reports else report_id,
        artifact_path=relative, artifact_sha256=artifact_hash,
        artifact_bytes=video.stat().st_size, created_at=created, duration_seconds=duration,
        disposition=disposition, samples=samples, dimensions=scores, aggregate_score=aggregate,
        continuity_score=continuity_score, threshold=request.threshold, findings=findings,
        correction_plan=correction,
        retry=RetryPolicy(threshold=request.threshold, max_attempts=request.max_attempts,
                          attempt=attempt, result=retry_result, history=history),
        clip_understanding=clip,
        provenance={"reviewer": "studio_deterministic_v1", "ffmpeg": True,
                    "clip_understanding_ran": clip.state == "available", "inline_base64": False},
    )
