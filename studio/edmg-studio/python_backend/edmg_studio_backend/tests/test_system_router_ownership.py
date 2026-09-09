from __future__ import annotations

from fastapi.routing import APIRoute

from edmg_studio_backend import app as app_module

EXTRACTED_ROUTES = {
    "/health",
    "/v1/security/status",
    "/v1/settings/render_profiles",
    "/v1/hardware",
    "/v1/settings/render_providers",
    "/v1/settings/transcription",
    "/v1/config",
    "/v1/settings/secrets/status",
    "/v1/settings/secrets/set",
    "/v1/settings/secrets/clear",
    "/v1/setup/status",
    "/v1/setup/tasks",
    "/v1/setup/tasks/{task_id}/cancel",
    "/v1/setup/ollama/install_managed",
    "/v1/setup/ollama/download_and_run",
    "/v1/setup/ollama/start_managed",
    "/v1/setup/ollama/pull",
    "/v1/setup/7zip/install",
    "/v1/setup/backend/install",
    "/v1/setup/full/install",
    "/v1/setup/comfyui/portable/install",
    "/v1/setup/comfyui/portable/start",
    "/v1/setup/comfyui/portable/stop",
    "/v1/setup/edmg/install",
    "/v1/ai/status",
    "/v1/worker/status",
    "/v1/comfyui/nodes",
    "/v1/comfyui/object_info",
    "/v1/comfyui/capabilities",
    "/v1/edmg/status",
    "/v1/edmg/verify",
    "/v1/edmg/deforum_template",
    "/v1/codex/status",
}


def test_system_routes_are_owned_by_extracted_modules():
    routes = []
    for registered in app_module.app.routes:
        routes.extend(
            route
            for route in getattr(
                getattr(registered, "original_router", None), "routes", [registered]
            )
            if isinstance(route, APIRoute)
        )
    owned = [route for route in routes if route.path in EXTRACTED_ROUTES]

    assert {route.path for route in owned} == EXTRACTED_ROUTES
    assert all(route.endpoint.__module__.startswith("edmg_studio_backend.api.") for route in owned)
    assert all(route.endpoint.__module__ != "edmg_studio_backend.app" for route in owned)


def test_extracted_system_routes_have_no_duplicate_method_path_pairs():
    routes = []
    for registered in app_module.app.routes:
        routes.extend(getattr(getattr(registered, "original_router", None), "routes", [registered]))
    pairs = [
        (method, route.path)
        for route in routes
        if isinstance(route, APIRoute) and route.path in EXTRACTED_ROUTES
        for method in route.methods
    ]
    assert len(pairs) == len(set(pairs))
