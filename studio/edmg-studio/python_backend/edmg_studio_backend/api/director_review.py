"""Project-scoped Phase 10 Director Review API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..domain.director_review import ApplyCorrectionRequest, ReviewRequest, stable_digest
from ..domain.director_scene import DirectorDocument
from ..domain.director_workflow import reviewed_draft
from ..revisions import RevisionRoute
from ..services.director_review import create_review, resolve_video_artifact, sha256_file
from ..store.director_reviews import DirectorReviewStore


def create_director_review_router(get_store, ffmpeg_path: str, understanding=None):
    router = APIRouter(tags=["director review"], route_class=RevisionRoute)
    reports = DirectorReviewStore()

    def project(project_id: str):
        value = get_store().get(project_id)
        if value is None:
            raise HTTPException(404, "Project not found")
        return value

    @router.post("/v1/projects/{project_id}/director/reviews")
    def request_review(project_id: str, request: ReviewRequest):
        current = project(project_id)
        if current.revision != request.expected_revision:
            raise HTTPException(
                409,
                f"Project revision {request.expected_revision} is stale; current revision is {current.revision}",
            )
        directory = get_store().project_dir(project_id)
        try:
            with reports.transaction(directory):
                relative, _ = resolve_video_artifact(directory, request.artifact_path)
                video = (directory / relative).resolve()
                prior_reports = []
                if request.retry_of_report_id is not None:
                    try:
                        prior = reports.get(directory, request.retry_of_report_id)
                    except KeyError as exc:
                        raise HTTPException(404, "Referenced Director review report not found") from exc
                    if prior.project_id != project_id or prior.artifact_path != relative:
                        raise ValueError("retry_of_report_id must reference a review of the same artifact")
                    if prior.retry.result != "recommended":
                        raise ValueError("The referenced review is not eligible for another attempt")
                    if prior.retry.threshold != request.threshold or prior.retry.max_attempts != request.max_attempts:
                        raise ValueError("Retry threshold and maximum attempts must match the referenced review")
                    try:
                        prior_reports = [reports.get(directory, item.report_id) for item in prior.retry.history]
                    except KeyError as exc:
                        raise HTTPException(409, "Referenced Director review history is incomplete") from exc
                fingerprint_data = {"project_id": current.id, "project_revision": current.revision,
                                    "artifact_path": relative, "artifact_sha256": sha256_file(video),
                                    **request.model_dump(mode="json", exclude={"expected_revision", "artifact_path"})}
                existing = reports.find_by_fingerprint(directory, stable_digest(fingerprint_data))
                if existing is not None:
                    return {"ok": True, "replayed": True, "report": existing}
                if request.retry_of_report_id is not None:
                    chain = [item for item in reports.list(directory)
                             if item.retry_chain_id == prior.retry_chain_id]
                    if any(item.retry.attempt > prior.retry.attempt for item in chain):
                        raise HTTPException(409, "Retry this review chain from its latest report")
                report = create_review(project=current, project_dir=directory, request=request,
                                       ffmpeg_path=ffmpeg_path, prior_reports=prior_reports,
                                       understanding=understanding)
                latest = get_store().get(project_id)
                if latest is None or latest.revision != current.revision:
                    raise HTTPException(409, "Project changed while review evidence was being collected")
                reports.save(directory, report)
                return {"ok": True, "replayed": False, "report": report}
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/v1/projects/{project_id}/director/reviews")
    def list_reviews(project_id: str):
        project(project_id)
        return {"ok": True, "reports": reports.list(get_store().project_dir(project_id))}

    @router.get("/v1/projects/{project_id}/director/reviews/{report_id}")
    def get_review(project_id: str, report_id: str):
        project(project_id)
        try:
            return {"ok": True, "report": reports.get(get_store().project_dir(project_id), report_id)}
        except KeyError as exc:
            raise HTTPException(404, "Director review report not found") from exc

    @router.post("/v1/projects/{project_id}/director/reviews/{report_id}/apply")
    def apply_correction(project_id: str, report_id: str, request: ApplyCorrectionRequest):
        directory = get_store().project_dir(project_id)
        try:
            report = reports.get(directory, report_id)
        except KeyError as exc:
            raise HTTPException(404, "Director review report not found") from exc
        if report.correction_plan.state == "applied":
            current = project(project_id)
            return {"ok": True, "replayed": True, "revision": current.revision, "report": report}
        if report.correction_plan.state != "proposed" or report.correction_plan.director_document is None:
            raise HTTPException(409, "This report has no applicable correction proposal")

        def action(current):
            raw = current.meta.get("director_workflow") or {}
            if not report.source_draft_id or raw.get("draft_id") != report.source_draft_id:
                raise ValueError("The Director draft changed after this review. Run a new review before applying guidance.")
            if (not report.source_draft_fingerprint or
                    stable_digest(raw.get("document")) != report.source_draft_fingerprint):
                raise ValueError("The Director draft changed after this review. Run a new review before applying guidance.")
            draft = reviewed_draft(current, report.source_draft_id,
                                   DirectorDocument.model_validate(report.correction_plan.director_document))
            current.meta["director_workflow"] = draft.model_dump(mode="json")

        try:
            updated = get_store().mutate(project_id, action, expected_revision=request.expected_revision)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ValueError as exc:
            from ..store.projects import StaleProjectRevisionError
            if isinstance(exc, StaleProjectRevisionError):
                raise
            raise HTTPException(409, str(exc)) from exc
        report.correction_plan.state = "applied"
        report.correction_plan.applied_revision = updated.revision
        reports.save(directory, report)
        return {"ok": True, "replayed": False, "revision": updated.revision, "report": report}

    return router
