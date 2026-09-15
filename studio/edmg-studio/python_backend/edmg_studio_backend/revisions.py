"""Bind interactive requests to the store's compare-and-set contract."""
import json
import os
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException
from fastapi.routing import APIRoute

revision_context: ContextVar[dict | None] = ContextVar("project_revision", default=None)
background_context: ContextVar[dict | None] = ContextVar("background_project_updates", default=None)


def staged_media_path(path: Path) -> Path:
    """Redirect worker media writes to attempt-local staging until publication."""
    background = background_context.get()
    if background is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    staging_root = background.get("media_staging_root")
    project_root = background.get("media_project_root")
    if not isinstance(staging_root, Path) or not isinstance(project_root, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    relative = path.resolve().relative_to(project_root.resolve())
    staged = staging_root / relative
    staged.parent.mkdir(parents=True, exist_ok=True)
    return staged


def published_media_path(path: Path) -> Path:
    background = background_context.get()
    if background is None:
        return path
    staging_root = background.get("media_staging_root")
    project_root = background.get("media_project_root")
    if not isinstance(staging_root, Path) or not isinstance(project_root, Path):
        return path
    try:
        published = project_root / path.resolve().relative_to(staging_root.resolve())
    except ValueError:
        return path
    artifact = (path, published)
    if artifact not in background.setdefault("media_artifacts", []):
        background["media_artifacts"].append(artifact)
    return published


@contextmanager
def staged_media_publication(
    artifacts: list[tuple[Path, Path]],
    associated_paths: list[Path] | None = None,
):
    missing = [staged for staged, _published in artifacts if not staged.is_file()]
    if missing:
        raise FileNotFoundError(f"Staged media artifact is missing: {missing[0]}")
    backups: list[tuple[Path, Path | None]] = []
    try:
        backup_root = artifacts[0][0].parent if artifacts else None
        for index, published in enumerate(associated_paths or []):
            backup = backup_root / f".metadata-backup-{index}-{published.name}" if backup_root else None
            if published.exists() and backup is not None:
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(published, backup)
            else:
                backup = None
            backups.append((published, backup))
        offset = len(backups)
        for index, (staged, published) in enumerate(artifacts, start=offset):
            published.parent.mkdir(parents=True, exist_ok=True)
            backup = staged.parent / f".publish-backup-{index}-{published.name}"
            if published.exists():
                os.replace(published, backup)
            else:
                backup = None
            backups.append((published, backup))
            os.replace(staged, published)
        yield
    except BaseException:
        for published, backup in reversed(backups):
            if published.exists():
                published.unlink()
            if backup is not None and backup.exists():
                os.replace(backup, published)
        raise
    finally:
        for _published, backup in backups:
            if backup is not None:
                backup.unlink(missing_ok=True)
        for staged, _published in artifacts:
            shutil.rmtree(staged.parent, ignore_errors=True)


def merge_owned_fields(current: dict, baseline: dict, edited: dict) -> dict:
    """Apply only a worker's changes; reject conflicting scalar replacements."""
    from copy import deepcopy
    result = deepcopy(current)
    for key in baseline.keys() | edited.keys():
        if key in baseline and key in edited and baseline[key] == edited[key]:
            continue
        if key not in edited:
            if result.get(key) == baseline[key]:
                result.pop(key, None)
            continue
        old, new, latest = baseline.get(key), edited[key], result.get(key)
        if isinstance(old, dict) and isinstance(new, dict) and isinstance(latest, dict):
            result[key] = merge_owned_fields(latest, old, new)
        elif isinstance(old, list) and isinstance(new, list) and isinstance(latest, list) and new[:len(old)] == old:
            result[key] = latest + [deepcopy(item) for item in new[len(old):] if item not in latest]
        elif latest == old or latest == new or key not in result:
            result[key] = deepcopy(new)
        else:
            raise ValueError(f"Background update conflicts with newer project field: {key}")
    return result


def request_revision(project_id: str, fallback: int | None) -> int | None:
    context = revision_context.get()
    return context["revision"] if context and context["project_id"] == project_id else fallback


def record_revision(project_id: str, revision: int) -> None:
    context = revision_context.get()
    if context and context["project_id"] == project_id:
        context["revision"] = revision


class RevisionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            from .store.projects import StaleProjectRevisionError

            project_id = request.path_params.get("project_id")
            suffix = request.url.path.split(f"/projects/{project_id}", 1)[-1]
            readonly = suffix.endswith(("/preflight", "/preview", "/validate")) or suffix == "/media-urls"
            if not project_id or request.method not in {"POST", "PUT", "PATCH", "DELETE"} or readonly or suffix.startswith("/jobs/"):
                return await handler(request)
            supplied = request.headers.get("if-match")
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await request.json()
                except (ValueError, UnicodeDecodeError) as exc:
                    raise HTTPException(422, "Request body must be valid JSON") from exc
                if isinstance(body, dict):
                    supplied = body.get("expected_revision") if body.get("expected_revision") is not None else supplied
            elif "multipart/form-data" in content_type:
                form = await request.form()
                supplied = form.get("expected_revision", supplied)
            try:
                if supplied is not None and (isinstance(supplied, bool) or not str(supplied).isdecimal() or int(supplied) < 1):
                    raise ValueError()
                expected = int(supplied) if supplied is not None else None
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, "expected_revision must be a positive integer") from exc
            context = {"project_id": project_id, "revision": expected}
            token = revision_context.set(context)
            try:
                response = await handler(request)
                if response.status_code < 300 and context["revision"] is not None:
                    response.headers["X-Project-Revision"] = str(context["revision"])
                    if "application/json" in (response.media_type or "") and hasattr(response, "body"):
                        data = json.loads(response.body)
                        if isinstance(data, dict):
                            data["revision"] = context["revision"]
                            response.body = json.dumps(data, ensure_ascii=False).encode()
                            response.headers["content-length"] = str(len(response.body))
                return response
            except StaleProjectRevisionError as exc:
                raise HTTPException(409, {"code": "PROJECT_REVISION_CONFLICT", "message": str(exc),
                    "expected_revision": exc.expected_revision, "current_revision": exc.actual_revision}) from exc
            finally:
                revision_context.reset(token)

        return handle
