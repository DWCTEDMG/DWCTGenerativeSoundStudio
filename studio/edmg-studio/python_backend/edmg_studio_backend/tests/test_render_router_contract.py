import ast
from pathlib import Path

from fastapi.routing import APIRoute

from edmg_studio_backend.app import app
from edmg_studio_backend.revisions import RevisionRoute

RENDER_ROUTES = {
    ("POST", "/v1/projects/{project_id}/render/cosmos/scene"),
    ("POST", "/v1/projects/{project_id}/render/cosmos/all_scenes"),
    ("POST", "/v1/projects/{project_id}/render/azure_foundry/scene"),
    ("POST", "/v1/projects/{project_id}/render/azure_foundry/all_scenes"),
    ("POST", "/v1/projects/{project_id}/render/firefly/scenes"),
    ("POST", "/v1/projects/{project_id}/render/firefly/video"),
    ("POST", "/v1/projects/{project_id}/render/firefly/assemble"),
    ("POST", "/v1/projects/{project_id}/render/imagineart/scenes"),
    ("POST", "/v1/projects/{project_id}/render/imagineart/video"),
    ("POST", "/v1/projects/{project_id}/render/imagineart/assemble"),
    ("POST", "/v1/projects/{project_id}/render/stills/scenes"),
    ("POST", "/v1/projects/{project_id}/render/comfyui/scenes"),
    ("POST", "/v1/projects/{project_id}/render/tensorrt-standalone"),
    ("POST", "/v1/projects/{project_id}/render/tensorrt-deforum"),
    ("POST", "/v1/projects/{project_id}/render/tensorrt-standalone/preview"),
    ("POST", "/v1/projects/{project_id}/render/internal/video"),
    ("GET", "/v1/projects/{project_id}/render/motion_sequencer"),
    ("POST", "/v1/projects/{project_id}/render/motion_sequencer/apply"),
    ("POST", "/v1/projects/{project_id}/render/internal/preflight"),
    ("POST", "/v1/projects/{project_id}/render/comfyui/motion_scenes"),
    ("GET", "/v1/render/route"),
    ("POST", "/v1/render/route/preferences"),
    ("POST", "/v1/projects/{project_id}/render/video/smart"),
    ("GET", "/v1/projects/{project_id}/pipeline/validate"),
    ("POST", "/v1/projects/{project_id}/render/conductor/plan"),
    ("POST", "/v1/projects/{project_id}/render/conductor/promote"),
    ("GET", "/v1/projects/{project_id}/render/performer/plan"),
    ("POST", "/v1/projects/{project_id}/render/performer/plan"),
    ("POST", "/v1/projects/{project_id}/render/performer/run"),
    ("POST", "/v1/projects/{project_id}/pipeline/run"),
    ("GET", "/v1/render/animation_presets"),
    ("POST", "/v1/projects/{project_id}/render/auto"),
    ("POST", "/v1/projects/{project_id}/render/animate_layers"),
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


def test_app_module_contains_no_http_route_decorators():
    app_path = Path(__file__).parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    decorators = [
        decorator
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "app"
        and decorator.func.attr in http_methods
    ]
    assert decorators == []


def test_render_route_inventory_and_ownership_are_exact():
    routes = list(api_routes())
    owned = {
        (method, route.path)
        for route in routes
        if route.endpoint.__module__ == "edmg_studio_backend.api.render"
        for method in route.methods
    }
    assert owned == RENDER_ROUTES
    assert len(owned) == len(RENDER_ROUTES)


def test_project_render_routes_preserve_revision_enforcement():
    project_routes = [
        route
        for route in api_routes()
        if ("POST", route.path) in RENDER_ROUTES and "/projects/{project_id}/" in route.path
    ]
    assert project_routes
    assert all(isinstance(route, RevisionRoute) for route in project_routes)


def test_render_openapi_contract_preserves_deprecation_and_all_operations():
    schema = app.openapi()
    documented = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"}
        and (method.upper(), path) in RENDER_ROUTES
    }
    assert documented == RENDER_ROUTES
    assert schema["paths"]["/v1/projects/{project_id}/render/tensorrt-deforum"]["post"]["deprecated"] is True
