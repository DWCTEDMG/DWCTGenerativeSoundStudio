from __future__ import annotations

from fastapi.routing import APIRoute

from edmg_studio_backend import app as backend


EXPECTED_JOB_ROUTES = {
    ("GET", "/v1/jobs"),
    ("GET", "/v1/generation/jobs"),
    ("GET", "/v1/projects/{project_id}/jobs"),
    ("GET", "/v1/projects/{project_id}/generation/jobs"),
    ("GET", "/v1/projects/{project_id}/jobs/{job_id}"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/cancel"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/pause"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/resume"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/priority"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/retry"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/resume_from_checkpoint"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/restart_clean"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/clear_cached_frames"),
    ("POST", "/v1/projects/{project_id}/jobs/{job_id}/drop_checkpoint"),
    ("GET", "/v1/projects/{project_id}/jobs/{job_id}/log"),
    ("GET", "/v1/projects/{project_id}/jobs/{job_id}/events"),
    ("POST", "/v1/jobs/tick"),
}


def test_job_route_contract_and_ownership() -> None:
    routes = []
    for registered in backend.app.routes:
        candidates = getattr(getattr(registered, "original_router", None), "routes", [registered])
        routes.extend(
            route
            for route in candidates
            if isinstance(route, APIRoute) and (
                route.path in {"/v1/jobs", "/v1/generation/jobs"} or "/jobs" in route.path
            )
        )
    actual = {
        (method, route.path)
        for route in routes
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }

    assert actual == EXPECTED_JOB_ROUTES
    assert len(routes) == len(EXPECTED_JOB_ROUTES)
    assert all(route.endpoint.__module__ == "edmg_studio_backend.api.jobs" for route in routes)
