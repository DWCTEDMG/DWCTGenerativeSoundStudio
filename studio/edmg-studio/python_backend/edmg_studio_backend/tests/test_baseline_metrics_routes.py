from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api.routers import create_system_router
from edmg_studio_backend.services.baseline_metrics import collect_baseline_metrics


def test_baseline_metrics_route_returns_stub_report():
    app = FastAPI()
    app.include_router(
        create_system_router(
            readiness_report=lambda: {"ok": True, "status": "ready"},
            baseline_metrics=collect_baseline_metrics,
        )
    )
    client = TestClient(app)
    resp = client.get("/v1/metrics/baseline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["schema_version"] == 1
    assert "launch" in body["samples"]
