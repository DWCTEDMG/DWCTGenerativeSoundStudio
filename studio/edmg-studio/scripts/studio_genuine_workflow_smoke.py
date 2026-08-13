from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch


def _empty_comfy_diagnosis(*_args: Any, **_kwargs: Any) -> dict[str, list[Any]]:
    return {"compatible": [], "busy_compatible": []}


def run_genuine_workflow_smoke() -> dict[str, Any]:
    """Exercise planning and Timeline authoring without a configured renderer."""
    with tempfile.TemporaryDirectory(prefix="edmg_genuine_smoke_") as tmp:
        data_dir = Path(tmp) / "studio-data"

        import edmg_studio_backend.app as app_module
        from edmg_studio_backend.store.jobs import JobStore
        from edmg_studio_backend.store.projects import ProjectStore

        previous_store = app_module.store
        previous_jobs = app_module.jobs
        app_module.store = ProjectStore(data_dir)
        smoke_jobs = JobStore(app_module.store.projects_dir)
        app_module.jobs = smoke_jobs

        try:
            with (
                patch.object(app_module.models, "installed_path", return_value=None),
                patch.object(app_module.comfy_pool, "diagnose", side_effect=_empty_comfy_diagnosis),
                patch.object(app_module, "_hosted_stability_ready", return_value=False),
            ):
                project = app_module.store.create("Genuine Workflow Smoke")
                project_id = project.id

                plan = app_module.generate_plan(
                    project_id,
                    app_module.PlanRequest(
                        title="Genuine Workflow Smoke",
                        user_notes="Create a concise music-video edit.",
                        style_prefs="cinematic, rhythmic cuts",
                        num_variants=1,
                        max_scenes=3,
                    ),
                    mode="local",
                )
                timeline_result = app_module.apply_plan_to_timeline(
                    project_id,
                    app_module.ApplyPlanRequest(variant_index=0, overwrite=True),
                )

                render_error: dict[str, Any]
                try:
                    app_module.run_pipeline(project_id, variant_index=0, preset="balanced", mode="auto")
                except app_module.UserFacingError as exc:
                    render_error = {
                        "code": exc.code,
                        "message": exc.message,
                        "hint": exc.hint,
                        "status_code": exc.status_code,
                    }
                else:
                    raise AssertionError("A render job started without a genuine renderer")

                stored = app_module.store.get(project_id)
                if stored is None:
                    raise AssertionError("Project was not persisted")

                variants = list(plan.get("variants") or [])
                timeline = dict(timeline_result.get("timeline") or {})
                if not variants:
                    raise AssertionError("Local planning did not create a storyboard variant")
                if not timeline:
                    raise AssertionError("The storyboard was not applied to the Timeline")
                if render_error["code"] != "NO_RENDER_ROUTE":
                    raise AssertionError(f"Expected NO_RENDER_ROUTE, got {render_error['code']}")
                if app_module.jobs.list_for_project(project_id):
                    raise AssertionError("A render job was enqueued without a genuine renderer")

                report = {
                    "ok": True,
                    "project_id": project_id,
                    "plan_source": str(plan.get("source") or "local"),
                    "variant_count": len(variants),
                    "scene_count": len(variants[0].get("scenes") or []),
                    "timeline_track_count": len(timeline.get("tracks") or []),
                    "render_error": render_error,
                    "persisted": {
                        "has_plan": bool(stored.meta.get("last_plan")),
                        "has_timeline": bool(stored.meta.get("timeline")),
                    },
                }
                print(json.dumps(report, indent=2))
                return report
        finally:
            app_module.jobs = previous_jobs
            app_module.store = previous_store
            smoke_jobs.close()


if __name__ == "__main__":
    run_genuine_workflow_smoke()
