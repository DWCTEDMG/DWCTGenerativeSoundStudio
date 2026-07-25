from __future__ import annotations

import json

from edmg_studio_backend.services.baseline_metrics import (
    baseline_timer,
    collect_baseline_metrics,
    record_baseline_sample,
    reset_baseline_samples,
)


def test_record_and_collect_baseline_samples():
    reset_baseline_samples()
    record_baseline_sample("launch", 1200.0)
    record_baseline_sample("launch", 900.0)
    report = collect_baseline_metrics()
    assert report["ok"] is True
    assert report["schema_version"] == 1
    assert report["stub"] is True
    launch = report["samples"]["launch"]
    assert launch["count"] == 2
    assert launch["last_ms"] == 900.0
    assert launch["budget_ms"] == 8000.0
    assert launch["within_budget"] is True


def test_baseline_timer_records_elapsed_ms():
    reset_baseline_samples()
    with baseline_timer("timeline_load"):
        pass
    report = collect_baseline_metrics()
    assert report["samples"]["timeline_load"]["count"] == 1
    assert report["samples"]["timeline_load"]["last_ms"] >= 0.0


def test_env_json_injects_samples(monkeypatch):
    reset_baseline_samples()
    monkeypatch.setenv(
        "EDMG_BASELINE_METRICS_JSON",
        json.dumps({"analysis": 45_000, "render_plan": [1200, 980]}),
    )
    report = collect_baseline_metrics()
    analysis = report["samples"]["analysis"]
    assert analysis["count"] == 1
    assert analysis["last_ms"] == 45_000.0
    render_plan = report["samples"]["render_plan"]
    assert render_plan["count"] == 2
    assert render_plan["within_budget"] is True
