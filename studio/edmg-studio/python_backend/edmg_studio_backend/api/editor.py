"""Revision-checked persistent editor commands, independent of either desktop UI."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..domain.editor_commands import (
    EditorConflict,
    digest,
    execute,
    history_state,
    normalize_timeline,
)
from ..revisions import RevisionRoute, record_revision, revision_context
from ..store.projects import StaleProjectRevisionError
from .media import validate_timeline_media


class EditorCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1, strict=True)
    action: Literal["edit", "replace", "undo", "redo"]
    label: str = Field(default="Timeline edit", max_length=200)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    timeline: dict[str, Any] | None = None


class InsertArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1, strict=True)
    artifact_path: str = Field(min_length=1, max_length=1024)
    track_id: str | None = Field(default=None, max_length=128)
    start_seconds: float = Field(default=0, ge=0)
    duration_seconds: float = Field(gt=0)
    name: str | None = Field(default=None, max_length=200)


class InsertRenderResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1, strict=True)
    track_id: str | None = Field(default=None, max_length=128)
    start_s: float = Field(default=0, ge=0)


def create_editor_router(
    get_store,
    get_jobs=None,
    probe_duration: Callable[[Any], float | None] | None = None,
):
    router = APIRouter(route_class=RevisionRoute, tags=["editor"])

    def state(project):
        return {
            "ok": True,
            "revision": project.revision,
            "timeline": normalize_timeline(project.meta.get("timeline") or {}),
            "history": history_state(project.meta),
        }

    @router.get("/v1/projects/{project_id}/editor")
    def read(project_id: str):
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        try:
            return state(project)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/v1/projects/{project_id}/editor/commands")
    def command(project_id: str, request: EditorCommandRequest):
        store = get_store()
        payload = request.model_dump()
        fingerprint = digest({k: v for k, v in payload.items() if k != "expected_revision"})

        def current_project():
            # Inspect committed receipts before enforcing the original revision.
            # The actual mutation still uses the request's compare-and-set revision.
            token = revision_context.set(None)
            try:
                return store.get(project_id)
            finally:
                revision_context.reset(token)

        def replay(project):
            receipt = (
                (project.meta.get("editor_history") or {})
                .get("receipts", {})
                .get(request.operation_id)
            )
            if receipt is None:
                return None
            if receipt != fingerprint:
                raise HTTPException(
                    409,
                    {
                        "code": "EDITOR_OPERATION_CONFLICT",
                        "message": "Operation ID already used for different content",
                    },
                )
            record_revision(project_id, project.revision)
            return {**state(project), "replayed": True}

        project = current_project()
        if project is None:
            raise HTTPException(404, "Project not found")
        repeated = replay(project)
        if repeated is not None:
            return repeated

        def apply(project):
            execute(project.meta, payload)
            validate_timeline_media(store.project_dir(project_id), project.meta["timeline"])

        try:
            project = store.mutate(project_id, apply, expected_revision=request.expected_revision)
            return {**state(project), "replayed": False}
        except (StaleProjectRevisionError, EditorConflict) as exc:
            # Recheck under contention: an identical concurrent submission may have won.
            current = current_project()
            if current is not None:
                repeated = replay(current)
                if repeated is not None:
                    return repeated
            if isinstance(exc, StaleProjectRevisionError):
                raise
            raise HTTPException(
                409, {"code": "EDITOR_HISTORY_CONFLICT", "message": str(exc)}
            ) from exc
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/v1/projects/{project_id}/editor/insert-artifact")
    def insert_artifact(project_id: str, request: InsertArtifactRequest):
        store = get_store()
        relative = request.artifact_path.replace("\\", "/").strip("/")
        project_dir = store.project_dir(project_id).resolve()
        artifact_file = (project_dir / relative).resolve()
        if not artifact_file.is_relative_to(project_dir) or not artifact_file.is_file():
            raise HTTPException(422, {"code": "ARTIFACT_NOT_FOUND", "message": "Artifact must be an existing project file"})
        manifest_file = artifact_file.with_suffix(artifact_file.suffix + ".artifact.json")
        if not manifest_file.is_file():
            raise HTTPException(422, {"code": "ARTIFACT_MANIFEST_MISSING", "message": "Artifact manifest is missing"})
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(422, {"code": "ARTIFACT_MANIFEST_INVALID", "message": "Artifact manifest is invalid"}) from exc
        if manifest.get("kind") != "video" or manifest.get("path") != relative:
            raise HTTPException(422, {"code": "ARTIFACT_MANIFEST_MISMATCH", "message": "Artifact manifest does not match the requested video"})

        receipt_id = f"artifact:{request.operation_id}"
        artifact_id = str(manifest.get("id") or f"artifact-{request.operation_id}")
        clip_id = f"artifact-{request.operation_id}"
        manifest_relative = str(manifest_file.relative_to(project_dir)).replace("\\", "/")
        fingerprint = digest(request.model_dump(exclude={"expected_revision"}))

        def current_project():
            token = revision_context.set(None)
            try:
                return store.get(project_id)
            finally:
                revision_context.reset(token)

        def replay(project):
            receipt = ((project.meta.get("editor_history") or {}).get("receipts", {}).get(receipt_id))
            if receipt is None:
                return None
            if receipt != fingerprint:
                raise HTTPException(409, {"code": "EDITOR_OPERATION_CONFLICT", "message": "Operation ID already used for different content"})
            record_revision(project_id, project.revision)
            timeline = normalize_timeline(project.meta.get("timeline") or {})
            inserted_track = next(
                (
                    track
                    for track in timeline["tracks"]
                    if any(clip.get("id") == clip_id for clip in track.get("clips", []))
                ),
                None,
            )
            return {
                **state(project),
                "replayed": True,
                "artifact": manifest,
                "track_id": inserted_track.get("id") if inserted_track else None,
                "clip_id": clip_id,
                "media_asset_id": artifact_id,
            }

        project = current_project()
        if project is None:
            raise HTTPException(404, "Project not found")
        timeline = normalize_timeline(project.meta.get("timeline") or {})
        video_tracks = [
            track
            for track in timeline["tracks"]
            if track.get("type") == "video" and not track.get("locked", False)
        ]
        if request.track_id is not None:
            requested_track = next(
                (track for track in timeline["tracks"] if track.get("id") == request.track_id),
                None,
            )
            if requested_track is not None and (
                requested_track.get("type") != "video" or requested_track.get("locked", False)
            ):
                raise HTTPException(422, "Requested track must be an unlocked video track")
        track_id = request.track_id or (video_tracks[0]["id"] if video_tracks else f"generated-video-{request.operation_id}")
        operations: list[dict[str, Any]] = []
        if not any(track.get("id") == track_id for track in timeline["tracks"]):
            operations.append({"kind": "add_track", "new_id": track_id, "track_type": "video", "name": "Generated Video"})
        operations.append({
            "kind": "add_clip", "track_id": track_id,
            "new_id": clip_id, "name": request.name or artifact_file.stem,
            "start_seconds": request.start_seconds,
            "end_seconds": request.start_seconds + request.duration_seconds,
            "source_path": relative,
            "media_asset_id": artifact_id,
            "data": {"artifact_manifest": manifest_relative, "artifact_id": artifact_id},
        })
        command_payload = {
            "operation_id": receipt_id, "expected_revision": request.expected_revision,
            "action": "edit", "label": "Insert generated artifact", "operations": operations, "timeline": None,
        }
        repeated = replay(project)
        if repeated is not None:
            return repeated

        def apply(project):
            execute(project.meta, command_payload)
            project.meta["editor_history"]["receipts"][receipt_id] = fingerprint
            validate_timeline_media(project_dir, project.meta["timeline"])
            pool = project.meta.setdefault("media_pool", [])
            if not any(isinstance(item, dict) and item.get("path") == relative for item in pool):
                pool.append({
                    "id": artifact_id,
                    "version_id": artifact_id,
                    "artifact_id": artifact_id,
                    "path": relative,
                    "kind": "video",
                    "manifest_path": manifest_relative,
                    "content_hash": manifest.get("content_hash"),
                    "renderer_id": manifest.get("engine"),
                    "provider_id": manifest.get("provider"),
                    "model": deepcopy(manifest.get("model") or {}),
                    "project_revision": manifest.get("project_revision"),
                    "plan_revision": manifest.get("plan_revision"),
                    "source_assets": deepcopy(manifest.get("source_assets") or []),
                    "lineage": deepcopy(manifest.get("lineage") or {"parents": []}),
                })

        try:
            project = store.mutate(project_id, apply, expected_revision=request.expected_revision)
            return {
                **state(project),
                "replayed": False,
                "artifact": manifest,
                "track_id": track_id,
                "clip_id": clip_id,
                "media_asset_id": artifact_id,
            }
        except StaleProjectRevisionError:
            current = current_project()
            repeated = replay(current) if current is not None else None
            if repeated is not None:
                return repeated
            raise
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/v1/projects/{project_id}/timeline/insert-render-result")
    def insert_render_result(project_id: str, request: InsertRenderResultRequest):
        if get_jobs is None or probe_duration is None:
            raise HTTPException(501, "Render-result insertion is not configured")
        job = get_jobs().get(project_id, request.job_id)
        if job is None:
            raise HTTPException(404, "Render job not found")
        if job.status != "succeeded" or job.type != "internal_video":
            raise HTTPException(409, "Only completed internal video renders can be inserted")
        result = job.result if isinstance(job.result, dict) else {}
        artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
        artifact_path = str(artifact.get("path") or result.get("video") or "").strip()
        if not artifact_path:
            raise HTTPException(422, "Render job has no video artifact")
        project_dir = get_store().project_dir(project_id).resolve()
        media_path = (project_dir / artifact_path.replace("\\", "/").strip("/")).resolve()
        duration_seconds = probe_duration(media_path)
        if duration_seconds is None or duration_seconds <= 0:
            raise HTTPException(422, "Render artifact duration could not be determined")
        response = insert_artifact(
            project_id,
            InsertArtifactRequest(
                operation_id=f"render-job-{request.job_id}",
                expected_revision=request.expected_revision,
                artifact_path=artifact_path,
                track_id=request.track_id,
                start_seconds=request.start_s,
                duration_seconds=duration_seconds,
            ),
        )
        return {**response, "job_id": request.job_id}

    return router
