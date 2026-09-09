from __future__ import annotations

from edmg_studio_backend.app import app
from edmg_studio_backend.schemas import ProjectHealthResponse
from edmg_studio_backend.services.project_health import assess_project_health


def test_project_health_route_publishes_typed_openapi_contract(tmp_path) -> None:
    schema = app.openapi()
    response = schema["paths"]["/v1/projects/{project_id}/health"]["get"]["responses"]["200"]

    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProjectHealthResponse"
    }
    assert "ProjectHealthReport" in schema["components"]["schemas"]

    report = assess_project_health(tmp_path, {})
    typed = ProjectHealthResponse.model_validate({"ok": True, "health": report})
    assert typed.health.status == "ok"
