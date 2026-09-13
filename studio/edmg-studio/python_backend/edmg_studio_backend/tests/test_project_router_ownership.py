from fastapi.routing import APIRoute

from edmg_studio_backend.app import app
from edmg_studio_backend.revisions import RevisionRoute

EXTRACTED_PATHS = {
    "/v1/cloud/aws/test",
    "/v1/cloud/aws/bundle",
    "/v1/cloud/azure/test",
    "/v1/cloud/hf/status",
    "/v1/cloud/hf/test",
    "/v1/cloud/hf/settings",
    "/v1/cloud/lightning/bundle",
    "/v1/director_modes",
    "/v1/projects/{project_id}/preview/frame",
    "/v1/projects/{project_id}/preview/segment",
    "/v1/projects/{project_id}/preview/diffusion_segment",
    "/v1/projects/{project_id}/audio",
    "/v1/projects/{project_id}/analyze_audio",
    "/v1/projects/{project_id}/assets/audio",
    "/v1/projects/{project_id}/assets/overlay",
    "/v1/projects/{project_id}/assets/mask",
    "/v1/projects/{project_id}/media-pool",
    "/v1/projects/{project_id}/media-pool/import",
    "/v1/projects/{project_id}/media-pool/{asset_id}/probe",
    "/v1/projects/{project_id}/media-pool/{asset_id}/relink",
    "/v1/projects/{project_id}/media-pool/{asset_id}/waveform",
    "/v1/projects/{project_id}/media-pool/{asset_id}/thumbnail",
    "/v1/projects/{project_id}/media-pool/{asset_id}/proxy",
    "/v1/projects/{project_id}/plan",
    "/v1/projects/{project_id}/analyze_and_plan",
    "/v1/projects/{project_id}/timeline/apply_plan",
    "/v1/projects/{project_id}/plan/variant",
    "/v1/projects/{project_id}/planner_lab/import",
    "/v1/projects/{project_id}/reactive_lab/apply",
    "/v1/projects/{project_id}/visual_dna",
    "/v1/projects/{project_id}/visual_dna/feedback",
    "/v1/projects/{project_id}/visual_dna/update",
    "/v1/projects/{project_id}/health/relink",
    "/v1/projects/{project_id}/health/collect",
    "/v1/projects/{project_id}/creative_direction",
    "/v1/projects/{project_id}/creative_direction/apply_timeline_patch",
    "/v1/projects/{project_id}/codex/render-review",
    "/v1/projects/{project_id}/assets",
    "/v1/projects/{project_id}/assets/refs",
    "/v1/projects/{project_id}/export/comfyui_workflows",
    "/v1/projects/{project_id}/assemble_video",
    "/v1/projects/{project_id}/export/deforum",
    "/v1/projects/{project_id}/unreal/preview",
    "/v1/projects/{project_id}/export/unreal",
    "/v1/projects/{project_id}/import/unreal",
    "/v1/projects/{project_id}/unreal/import-plan",
    "/v1/projects/{project_id}/outputs",
    "/v1/projects/{project_id}/file",
}


def api_routes():
    for registered in app.routes:
        yield from (
            route
            for route in getattr(
                getattr(registered, "original_router", None), "routes", [registered]
            )
            if isinstance(route, APIRoute)
        )


def test_extracted_project_routes_are_owned_outside_app_module():
    routes = list(api_routes())
    selected = [route for route in routes if route.path in EXTRACTED_PATHS]
    assert {route.path for route in selected} == EXTRACTED_PATHS
    assert all(route.endpoint.__module__.startswith("edmg_studio_backend.api.") for route in selected)


def test_extracted_project_routes_preserve_revision_enforcement():
    project_routes = [
        route
        for route in api_routes()
        if route.path in EXTRACTED_PATHS and "/projects/{project_id}/" in route.path
    ]
    assert project_routes
    assert all(isinstance(route, RevisionRoute) for route in project_routes)


def test_extracted_project_routes_have_no_duplicate_method_path_pairs():
    pairs = [
        (method, route.path)
        for route in api_routes()
        if route.path in EXTRACTED_PATHS
        for method in route.methods
    ]
    assert len(pairs) == len(set(pairs))


def test_no_direct_app_routes_remain():
    direct = [route.path for route in api_routes() if route.endpoint.__module__ == "edmg_studio_backend.app"]
    assert direct == []
