from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class JobPriorityRequest(BaseModel):
    priority: int = Field(ge=-100, le=100, strict=True)


@dataclass(frozen=True)
class JobRouterDependencies:
    get_store: Callable[[], Any]
    get_jobs: Callable[[], Any]
    job_detail_payload: Callable[..., dict[str, Any]]
    repair_legacy_selection: Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]]
    internal_render_preflight: Callable[[str, dict[str, Any]], dict[str, Any]]
    persist_resolved_payload: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    enqueue_from_source: Callable[..., dict[str, Any]]
    mutate_artifacts: Callable[..., dict[str, Any]]
    dispatch_job: Callable[[Any], None]
    normalize_generation_job: Callable[[Any], dict[str, Any]]


def create_jobs_router(deps: JobRouterDependencies) -> APIRouter:
    router = APIRouter(tags=["jobs"])

    def project_or_404(project_id: str) -> Any:
        project = deps.get_store().get(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        return project

    def job_or_404(project_id: str, job_id: str) -> Any:
        job = deps.get_jobs().get(project_id, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @router.get("/v1/jobs")
    def list_jobs():
        return {"jobs": [job.__dict__ for job in deps.get_jobs().list_all()]}

    @router.get("/v1/generation/jobs")
    def list_generation_jobs():
        jobs = [job for job in deps.get_jobs().list_all() if job.type == "internal_video"]
        return {"schema_version": "1.0", "jobs": [deps.normalize_generation_job(job) for job in jobs]}

    @router.get("/v1/projects/{project_id}/jobs")
    def list_project_jobs(project_id: str):
        project_or_404(project_id)
        return {"jobs": [job.__dict__ for job in deps.get_jobs().list_for_project(project_id)]}

    @router.get("/v1/projects/{project_id}/generation/jobs")
    def list_project_generation_jobs(project_id: str):
        project_or_404(project_id)
        jobs = [
            job for job in deps.get_jobs().list_for_project(project_id) if job.type == "internal_video"
        ]
        return {
            "schema_version": "1.0",
            "jobs": [deps.normalize_generation_job(job) for job in jobs],
        }

    @router.get("/v1/projects/{project_id}/jobs/{job_id}")
    def get_project_job(project_id: str, job_id: str, tail_lines: int = 80):
        project_or_404(project_id)
        return deps.job_detail_payload(
            project_id, job_or_404(project_id, job_id), tail_lines=tail_lines
        )

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/cancel")
    def cancel_job(project_id: str, job_id: str):
        project_or_404(project_id)
        job = deps.get_jobs().cancel(project_id, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.status != "canceled":
            raise HTTPException(
                409,
                {
                    "code": "JOB_ALREADY_TERMINAL",
                    "message": "The completed job could not be canceled.",
                    "status": job.status,
                },
            )
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/pause")
    def pause_job(project_id: str, job_id: str):
        project_or_404(project_id)
        current = job_or_404(project_id, job_id)
        if current.status != "queued":
            raise HTTPException(409, "Only queued jobs can be paused")
        job = deps.get_jobs().pause(project_id, job_id)
        if not job or job.status != "paused":
            raise HTTPException(409, "Job could not be paused because its state changed")
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/resume")
    def resume_job(project_id: str, job_id: str):
        project_or_404(project_id)
        current = job_or_404(project_id, job_id)
        if current.status != "paused":
            raise HTTPException(409, "Only paused jobs can be resumed")
        job = deps.get_jobs().resume(project_id, job_id)
        if not job or job.status != "queued":
            raise HTTPException(409, "Job could not be resumed because its state changed")
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/priority")
    def set_job_priority(project_id: str, job_id: str, request: JobPriorityRequest):
        project_or_404(project_id)
        current = job_or_404(project_id, job_id)
        if current.status not in ("queued", "paused"):
            raise HTTPException(409, "Only queued or paused jobs can be reprioritized")
        job = deps.get_jobs().set_priority(project_id, job_id, request.priority)
        if not job:
            raise HTTPException(409, "Job could not be reprioritized because its state changed")
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/retry")
    def retry_job(project_id: str, job_id: str):
        project_or_404(project_id)
        source_job = job_or_404(project_id, job_id)
        if source_job.status not in ("succeeded", "failed", "canceled"):
            raise HTTPException(409, "Only completed, failed, or canceled jobs can be retried")
        legacy_selection_note: str | None = None
        retry_payload: dict[str, Any] | None = None
        if source_job.type == "internal_video":
            retry_payload, legacy_selection_note = deps.repair_legacy_selection(
                deepcopy(source_job.payload or {})
            )
            preflight = deps.internal_render_preflight(project_id, retry_payload)
            retry_payload = deps.persist_resolved_payload(retry_payload, preflight)
        jobs = deps.get_jobs()
        job = jobs.retry(project_id, job_id, payload=retry_payload)
        if not job:
            raise HTTPException(409, "Job could not be retried because its state changed")
        if legacy_selection_note:
            jobs.append_log(project_id, job.id, legacy_selection_note)
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/resume_from_checkpoint")
    def resume_internal_job(project_id: str, job_id: str):
        project_or_404(project_id)
        source_job = job_or_404(project_id, job_id)
        if source_job.type != "internal_video":
            raise HTTPException(
                400, "Resume from checkpoint is only available for internal render jobs"
            )
        if source_job.status in ("queued", "paused", "running"):
            raise HTTPException(
                409, "Job is still active. Resume or cancel it before resuming from checkpoint."
            )
        return deps.enqueue_from_source(
            project_id,
            source_job,
            resume_existing_frames=True,
            queue_action="resume_from_checkpoint",
        )

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/restart_clean")
    def restart_internal_job_clean(project_id: str, job_id: str):
        project_or_404(project_id)
        source_job = job_or_404(project_id, job_id)
        if source_job.type != "internal_video":
            raise HTTPException(400, "Clean restart is only available for internal render jobs")
        if source_job.status in ("queued", "paused", "running"):
            raise HTTPException(
                409, "Job is still active. Resume or cancel it before starting a clean restart."
            )
        return deps.enqueue_from_source(
            project_id, source_job, resume_existing_frames=False, queue_action="restart_clean"
        )

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/clear_cached_frames")
    def clear_project_job_cached_frames(project_id: str, job_id: str):
        project_or_404(project_id)
        return deps.mutate_artifacts(
            project_id,
            job_or_404(project_id, job_id),
            clear_cached_frames=True,
            drop_checkpoint=False,
        )

    @router.post("/v1/projects/{project_id}/jobs/{job_id}/drop_checkpoint")
    def drop_project_job_checkpoint(project_id: str, job_id: str):
        project_or_404(project_id)
        return deps.mutate_artifacts(
            project_id,
            job_or_404(project_id, job_id),
            clear_cached_frames=False,
            drop_checkpoint=True,
        )

    @router.get("/v1/projects/{project_id}/jobs/{job_id}/log")
    def get_job_log(project_id: str, job_id: str):
        project_or_404(project_id)
        log_path = deps.get_jobs().log_path(project_id, job_id)
        if not log_path.exists():
            return {"ok": True, "log": ""}
        return {"ok": True, "log": log_path.read_text(encoding="utf-8", errors="ignore")}

    @router.get("/v1/projects/{project_id}/jobs/{job_id}/events")
    def get_job_events(project_id: str, job_id: str):
        project_or_404(project_id)
        job_or_404(project_id, job_id)
        return {"ok": True, "events": deps.get_jobs().list_events(project_id, job_id)}

    @router.post("/v1/jobs/tick")
    def tick_worker():
        job = deps.get_jobs().claim_next_queued()
        if not job:
            return {"ok": True, "note": "no queued jobs"}
        deps.dispatch_job(job)
        latest = deps.get_jobs().get(job.project_id, job.id) or job
        return {"ok": True, "job": latest.__dict__}

    return router
