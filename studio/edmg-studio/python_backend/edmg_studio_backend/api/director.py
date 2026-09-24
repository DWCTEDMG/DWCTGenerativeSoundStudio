"""Project-owned Director state; preparing prompts never submits generation."""

from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..domain.director_readiness import (
    HIGH_TIER_DIRECTOR_MODEL_ID,
    HUNYUAN_MODEL_ID,
    LTX_MODEL_ID,
    STANDARD_DIRECTOR_MODEL_ID,
    resolve_director_readiness,
)
from ..domain.director_scene import DirectorDocument, compile_scene
from ..domain.director_workflow import (
    DirectionDraft,
    prepare_workflow,
    set_timeline_context,
    source_fingerprint,
    timeline_context,
    workflow_state,
)
from ..domain.editor_commands import digest
from ..revisions import RevisionRoute, revision_context
from ..services.engine_packages import HIGH_GGUF_ID, STANDARD_GGUF_ID
from ..services.qwen_director import validate_proposal


class DirectorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    document: DirectorDocument


class DirectorGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    operation_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=16000)
    mode: Literal["automatic", "fast", "quality", "maximum"] = "automatic"
    renderer_engine: str = Field(default="automatic", min_length=1, max_length=80)
    allow_external: bool = False
    start_sample: str | None = None
    end_sample: str | None = None
    model_id: Literal[
        "hf_qwen3_vl_8b_director", "hf_qwen3_vl_30b_director",
        "hf_qwen3_vl_8b_gguf_director", "hf_qwen3_vl_30b_gguf_director",
    ] | None = None


class DirectorApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


def create_director_router(
    get_store, get_jobs=None, get_models=None, get_hardware=None, get_runtime_settings=None,
):
    router = APIRouter(route_class=RevisionRoute, tags=["director"])

    def installed_models() -> dict[str, object]:
        """Return install availability and managed runtime qualification without loading weights."""

        model_ids = (
            STANDARD_DIRECTOR_MODEL_ID,
            HIGH_TIER_DIRECTOR_MODEL_ID,
            HUNYUAN_MODEL_ID,
            LTX_MODEL_ID,
            STANDARD_GGUF_ID,
            HIGH_GGUF_ID,
        )
        service = get_models() if get_models is not None else None
        if service is None:
            return {model_id: False for model_id in model_ids}
        available: dict[str, bool] = {}
        try:
            catalog = service.catalog()
            if isinstance(catalog, dict) and isinstance(catalog.get("installed"), dict):
                available.update(
                    {
                        str(model_id): bool(value)
                        for model_id, value in catalog["installed"].items()
                        if str(model_id) in model_ids
                    }
                )
        except Exception:
            # Readiness is diagnostic; an unavailable catalog must not take the
            # project document or editor offline.
            pass
        managed_ids = {HUNYUAN_MODEL_ID, LTX_MODEL_ID, STANDARD_GGUF_ID, HIGH_GGUF_ID}
        runtime_hardware = hardware_profile()
        if get_runtime_settings is not None:
            settings = dict(get_runtime_settings() or {})
            runtime_path = str(settings.pop("runtime_path", "") or "").strip()
            runtime_hardware.update(settings)
            if runtime_path:
                runtime_hardware["llama_server_path"] = runtime_path
        for model_id in model_ids:
            if model_id in managed_ids:
                try:
                    available[model_id] = service.engine_package_status(model_id, runtime_hardware)
                    continue
                except (AttributeError, KeyError, ValueError):
                    pass
            if model_id in available and available[model_id]:
                continue
            try:
                available[model_id] = bool(service.installed_path(model_id))
            except Exception:
                available[model_id] = False
        return available

    def hardware_profile() -> dict:
        if get_hardware is None:
            return {}
        try:
            value = get_hardware()
            return dict(value or {})
        except Exception:
            # A readiness card should show a blocked/unknown result rather than
            # make the Workspace unusable when a platform probe fails.
            return {}

    @router.get("/v1/projects/{project_id}/director/readiness")
    def readiness(
        project_id: str,
        mode: str = "automatic",
        engine: str = "automatic",
        allow_external: bool = False,
        model_id: str | None = None,
    ):
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        try:
            result = resolve_director_readiness(
                hardware_profile(),
                mode=mode,
                engine=engine,
                installed_models=installed_models(),
                allow_external=allow_external,
                director_model_id=model_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["project_id"] = project_id
        payload["project_revision"] = project.revision
        return {"ok": True, **payload}

    @router.post("/v1/projects/{project_id}/director/generate")
    def generate(project_id: str, request: DirectorGenerationRequest):
        if get_jobs is None or get_models is None:
            raise HTTPException(503, "Director job services are unavailable")
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        signature = digest(request.model_dump(mode="json", exclude={"expected_revision"}))
        existing = next((job for job in get_jobs().list_for_project(project_id)
                         if job.type == "qwen_director"
                         and job.idempotency_key == "director:" + request.operation_id), None)
        if existing is not None:
            if existing.payload.get("request_signature") != signature:
                raise HTTPException(409, "Operation ID already used for different direction")
            recovery = project.meta.get("director_job") or {}
            if recovery.get("job_id") != existing.id:
                raise HTTPException(
                    409, "The prior Director request conflicted with a project change; refresh and retry"
                )
            return {"ok": True, "revision": project.revision,
                    "job_id": existing.id, "status": existing.status,
                    "output_policy": "draft"}
        if project.revision != request.expected_revision:
            raise HTTPException(409, "Project changed; refresh direction before generating")
        model_id = request.model_id or STANDARD_DIRECTOR_MODEL_ID
        readiness_snapshot = None
        hardware = hardware_profile() if get_hardware is not None else {}
        runtime_settings = dict(get_runtime_settings() or {}) if get_runtime_settings is not None else {}
        if get_hardware is not None:
            try:
                readiness = resolve_director_readiness(
                    hardware,
                    mode=request.mode,
                    engine=request.renderer_engine,
                    installed_models=installed_models(),
                    allow_external=request.allow_external,
                    director_model_id=request.model_id,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if not readiness.director.ready:
                raise HTTPException(
                    422,
                    {
                        "message": readiness.director.reason,
                        "hint": " ".join(readiness.blockers or readiness.actions),
                        "code": "DIRECTOR_NOT_READY",
                    },
                )
            model_id = readiness.director.model_id
            readiness_snapshot = {
                "mode": readiness.requested_mode,
                "renderer_engine": readiness.requested_engine,
                "director": readiness.director.model_dump(mode="json"),
                "renderer": readiness.renderer.model_dump(mode="json"),
                "hardware_tier": readiness.hardware_tier,
            }
        if get_models().installed_path(model_id) is None:
            raise HTTPException(
                422, {"message": f"Director model {model_id} is not installed",
                      "hint": "Install the resolved model in Models, then retry. The current draft was not changed.",
                      "code": "DIRECTOR_MODEL_NOT_INSTALLED", "model_id": model_id,
                      "draft_unchanged": True}
            )
        workflow = project.meta.get("director_workflow") or {}
        document = DirectorDocument.model_validate(workflow.get("document") or project.meta.get("director_document") or {})
        if not document.scenes:
            raise HTTPException(422, "Save at least one scene range before generating direction")
        if (request.start_sample is None) != (request.end_sample is None):
            raise HTTPException(422, "Provide both start_sample and end_sample")
        start_sample = request.start_sample or min(document.scenes, key=lambda scene: int(scene.start_sample)).start_sample
        end_sample = request.end_sample or max(document.scenes, key=lambda scene: int(scene.end_sample)).end_sample
        try:
            context = timeline_context(project, start_sample, end_sample)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        context_digest = digest(context)

        if workflow:
            current_draft = DirectionDraft.model_validate(workflow)
            if current_draft.source_fingerprint != source_fingerprint(project):
                raise HTTPException(409, "Workspace draft changed; prepare a current draft before generating")
            set_timeline_context(current_draft, context, project.revision + 1)
            current_draft.source_revision = project.revision + 1
            workflow = current_draft.model_dump(mode="json")
        payload = {
            "document": document.model_dump(mode="json"),
            "instruction": request.instruction,
            "request_signature": signature,
            "source_revision": project.revision,
            "workflow_draft_id": workflow.get("draft_id"),
            "workflow_source_fingerprint": workflow.get("source_fingerprint"),
            "analysis_revision": (project.meta.get("analysis") or {}).get("revision"),
            "source_audio_hash": (project.meta.get("analysis") or {}).get("source_audio_hash"),
            "analyzer_version": (project.meta.get("analysis") or {}).get("analyzer_version"),
            "schedule": deepcopy(workflow.get("schedule") or {}),
            "reactive_overrides": deepcopy(workflow.get("reactive_overrides") or {}),
            "reactive_extensions": deepcopy(workflow.get("reactive_extensions") or {}),
            "workflow_variant_index": workflow.get("variant_index", 0),
            "timeline_context": context,
            "context_digest": context_digest,
            "context_revision": int(workflow.get("context_revision") or project.revision),
            "model_id": model_id,
            "mode": request.mode,
            "renderer_engine": request.renderer_engine,
            "allow_external": request.allow_external,
            "device": str(hardware.get("llama_device") or hardware.get("device") or "cpu"),
            "gpu_layers": runtime_settings.get("gpu_layers", "auto"),
            "gpu_devices": runtime_settings.get("gpu_devices", "auto"),
            "tensor_split": runtime_settings.get("tensor_split", "auto"),
            "dense_device_map": runtime_settings.get("dense_device_map", "balanced_low_0"),
            "context_length": int(runtime_settings.get("context_length", 8192)),
            "batch_size": int(runtime_settings.get("batch_size", 64)),
            "ubatch_size": int(runtime_settings.get("ubatch_size", 16)),
            "cuda_graphs": bool(runtime_settings.get("cuda_graphs", False)),
            "vram_gb": float(hardware.get("llama_vram_gb") or hardware.get("vram_gb") or 0),
        }
        runtime_path = str(runtime_settings.get("runtime_path") or "").strip()
        if runtime_path:
            payload["runtime_path"] = runtime_path
        if readiness_snapshot is not None:
            payload["readiness"] = readiness_snapshot
        job_store = get_jobs()
        generation_error: Exception | None = None
        project_store = get_store()
        with project_store.validated_revision_lock(project_id, expected_revision=request.expected_revision):
            job, created = job_store.create_with_status(
                project_id, "qwen_director", payload, idempotency_key="director:" + request.operation_id
            )
            if job.type != "qwen_director" or job.payload != payload:
                raise HTTPException(409, "Operation ID already used for different direction")

            def persist_generation(current, active_job):
                current.meta["workspace_command"] = {
                    "provider": "internal_qwen", "model": model_id,
                    "brief": request.instruction, "style": "", "native_audio": False,
                }
                if workflow:
                    current.meta["director_workflow"] = deepcopy(workflow)
                current.meta["director_generation_context"] = {
                    "version": 1, "revision": current.revision + 1,
                    "digest": context_digest, "context": deepcopy(context),
                }
                current.meta["director_job"] = {
                    "version": 1,
                    "job_id": job.id,
                    "status": active_job.status,
                    "reviewed": False,
                    "instruction": request.instruction,
                    "context": deepcopy(context),
                }

            with job_store.registration_guard(project_id, job.id) as registration:
                if not registration.active:
                    raise HTTPException(409, "Prior Director request conflicted; use a new operation ID")
                try:
                    project = project_store.mutate(
                        project_id,
                        lambda current: persist_generation(current, registration.job),
                        expected_revision=request.expected_revision,
                    )
                except Exception as original_error:
                    token = revision_context.set(None)
                    try:
                        latest = project_store.get(project_id)
                    except Exception:
                        latest = None
                    finally:
                        revision_context.reset(token)
                    recovery = (latest.meta.get("director_job") or {}) if latest is not None else {}
                    if recovery.get("job_id") == job.id:
                        return {"ok": True, "revision": latest.revision, "job_id": job.id,
                                "status": registration.job.status, "output_policy": "draft"}
                    if created:
                        registration.cancel()
                    generation_error = original_error
        if generation_error is not None:
            raise generation_error
        return {"ok": True, "revision": project.revision, "job_id": job.id,
                "status": registration.job.status, "output_policy": "draft"}

    def response(project):
        document = DirectorDocument.model_validate(project.meta.get("director_document") or {})
        jobs = [] if get_jobs is None else [
            {"job_id": job.id,
             "status": ("reviewed" if (project.meta.get("director_applied_job") or {}).get("job_id") == job.id
                        else "review_ready" if job.status == "succeeded" else job.status),
             "updated_at": job.updated_at, "error": job.error}
            for job in get_jobs().list_for_project(project.id) if job.type == "qwen_director"
        ]
        return {
            "ok": True,
            "revision": project.revision,
            "document": document.model_dump(mode="json"),
            "director_jobs": jobs,
        }

    @router.get("/v1/projects/{project_id}/director/drafts")
    def drafts(project_id: str):
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        return response(project)

    def director_job(project_id, job_id):
        if get_jobs is None:
            raise HTTPException(503, "Director job services are unavailable")
        job = get_jobs().get(project_id, job_id)
        if job is None or job.type != "qwen_director":
            raise HTTPException(404, "Director job not found")
        return job

    @router.get("/v1/projects/{project_id}/director/drafts/{job_id}")
    def draft(project_id: str, job_id: str):
        job = director_job(project_id, job_id)
        return {
            "ok": True,
            "job_id": job.id,
            "status": job.status,
            "error": job.error,
            "progress": job.progress,
            "result": job.result if job.status == "succeeded" else None,
        }

    @router.post("/v1/projects/{project_id}/director/drafts/{job_id}/review")
    def review_draft(project_id: str, job_id: str, request: DirectorApplyRequest):
        job = director_job(project_id, job_id)
        if job.status != "succeeded" or not job.result or job.result.get("status") != "draft":
            raise HTTPException(409, "Director draft is not ready for review")

        def review(project):
            recovery = project.meta.get("director_job") or {}
            if recovery.get("job_id") != job.id:
                raise HTTPException(409, "A newer Director job replaced this draft")
            project.meta["director_job"] = {
                **recovery,
                "status": "reviewed",
                "reviewed": True,
                "reviewed_job_id": job.id,
            }

        try:
            current = get_store().mutate(project_id, review, expected_revision=request.expected_revision)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        return {**workflow_state(current), "job_id": job.id, "job_status": "reviewed",
                "document": job.result["document"]}

    @router.post("/v1/projects/{project_id}/director/drafts/{job_id}/apply")
    def apply_draft(project_id: str, job_id: str, request: DirectorApplyRequest):
        job = director_job(project_id, job_id)
        if job.status != "succeeded" or not job.result or job.result.get("status") != "draft":
            raise HTTPException(409, "Director draft is not ready for review and application")
        workflow_draft_id = job.payload.get("workflow_draft_id")
        baseline = DirectorDocument.model_validate(job.payload["document"])
        import json

        try:
            proposal = validate_proposal(json.dumps(job.result["document"]), baseline)
        except (ValueError, KeyError) as exc:
            raise HTTPException(
                422, "Director draft violates approved project constraints"
            ) from exc

        def apply(project):
            recovery = project.meta.get("director_job") or {}
            if recovery.get("job_id") != job.id or recovery.get("reviewed_job_id") != job.id:
                raise HTTPException(409, "Director draft must be reviewed before application")
            if workflow_draft_id:
                workflow = DirectionDraft.model_validate(project.meta.get("director_workflow") or {})
                if (
                    workflow.draft_id != workflow_draft_id
                    or workflow.source_fingerprint != job.payload.get("workflow_source_fingerprint")
                    or workflow.source_fingerprint != source_fingerprint(project)
                    or workflow.context_digest != job.payload.get("context_digest")
                    or workflow.context_revision != job.payload.get("context_revision")
                ):
                    raise HTTPException(
                        409, "Workspace draft changed during generation; retain this result for review"
                    )
                current = workflow.document
            else:
                current = DirectorDocument.model_validate(project.meta.get("director_document") or {})
            if current != baseline:
                raise HTTPException(
                    409,
                    "Direction changed during generation; retain this draft for placement review",
                )
            project.meta["director_document"] = proposal.model_dump(mode="json")
            project.meta["director_applied_job"] = {
                "job_id": job.id,
                "source_revision": job.payload["source_revision"],
                "provenance": job.result.get("provenance", {}),
            }
            project.meta["director_job"] = {**recovery, "status": "applied", "reviewed": True,
                                            "reviewed_job_id": job.id}
            prepare_workflow(
                project, lambda _: project.meta.get("last_plan") or {},
                resulting_revision=project.revision + 1, source="director",
                variant_index=int(job.payload.get("workflow_variant_index") or 0),
            )

        try:
            return response(
                get_store().mutate(project_id, apply, expected_revision=request.expected_revision)
            )
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @router.get("/v1/projects/{project_id}/director/document")
    def read(project_id: str):
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        return response(project)

    @router.post("/v1/projects/{project_id}/director/document")
    def update(project_id: str, request: DirectorUpdate):
        def apply(project):
            previous = DirectorDocument.model_validate(project.meta.get("director_document") or {})
            document = request.document.model_copy(deep=True)
            # Revision belongs to the project service, not the client.
            old_bible = previous.story_bible.model_dump(exclude={"revision"})
            new_bible = document.story_bible.model_dump(exclude={"revision"})
            document.story_bible.revision = previous.story_bible.revision + (old_bible != new_bible)
            project.meta["director_document"] = document.model_dump(mode="json")
            if document.scenes:
                prepare_workflow(project, lambda _: project.meta.get("last_plan") or {},
                                 resulting_revision=project.revision + 1, source="director")

        try:
            return response(
                get_store().mutate(project_id, apply, expected_revision=request.expected_revision)
            )
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @router.get("/v1/projects/{project_id}/director/prompts")
    def prompts(project_id: str, engine: str = "hunyuan_video15"):
        project = get_store().get(project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        if engine not in {"hunyuan_video15", "ltx_25", "external"}:
            raise HTTPException(422, "Unsupported prompt compiler")
        document = DirectorDocument.model_validate(project.meta.get("director_document") or {})
        return {
            "ok": True,
            "revision": project.revision,
            "packages": [
                compile_scene(scene, document.story_bible, engine) for scene in document.scenes
            ],
        }

    return router
