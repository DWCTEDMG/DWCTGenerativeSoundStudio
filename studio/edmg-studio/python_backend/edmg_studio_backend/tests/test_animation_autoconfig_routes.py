"""Route tests for the AI auto-configure + animate endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore


def _make_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    proj = store.create("AutoAnimate Test")
    proj.meta = {
        "timeline": {"layers": [], "camera": {"keyframes": []}},
        "last_plan": {
            "variants": [
                {
                    "index": 0,
                    "fps": 24,
                    "duration_s": 6.0,
                    "scenes": [
                        {"start_s": 0.0, "end_s": 3.0, "prompt": "neon city"},
                        {"start_s": 3.0, "end_s": 6.0, "prompt": "sunrise skyline"},
                    ],
                }
            ]
        },
    }
    store.save(proj)
    return store, jobs, proj


def _patch(monkeypatch, store, jobs, *, comfy_available=False):
    monkeypatch.setattr(backend_app, "store", store)
    monkeypatch.setattr(backend_app, "jobs", jobs)
    # Keep tests deterministic: never let the background worker execute jobs.
    monkeypatch.setattr(backend_app.worker, "start", lambda *a, **k: None)
    monkeypatch.setattr(backend_app, "_comfyui_available_quick", lambda: comfy_available)


def test_list_animation_presets():
    with TestClient(backend_app.app) as client:
        resp = client.get("/v1/render/animation_presets")
        resp.raise_for_status()
        data = resp.json()
        assert data["ok"] is True
        ids = [p["id"] for p in data["presets"]]
        assert "cinematic_3d" in ids
        assert "image_animation" in ids


def test_auto_dry_run_cinematic_3d(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "cinematic_3d", "engine": "internal", "run": False},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["ok"] is True
        assert data["launched"] is False
        assert data["engine"] == "internal"
        req = data["config"]["internal_request"]
        assert "deforum_translation_z" in req
        assert "deforum_rotation_3d_y" in req


def test_auto_dry_run_image_animation_with_source(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={
                "preset": "image_animation",
                "engine": "internal",
                "run": False,
                "source_asset": "assets/refs/painting.png",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["config"]["uses_source_image"] is True
        assert data["config"]["internal_request"]["source_asset"] == "assets/refs/painting.png"


def test_auto_dry_run_comfyui_engine(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs, comfy_available=True)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "comfyui_animatediff", "engine": "comfyui", "run": False},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["engine"] == "comfyui"
        assert data["config"]["comfyui_request"]["engine"] == "animatediff"
        assert data["comfyui_available"] is True


def test_auto_run_internal_launches_job(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "draft_fast", "engine": "internal", "run": True},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["launched"] is True
        assert data["engine"] == "internal"
        assert data["job"]["type"] == "internal_video"
        assert data["job"]["status"] == "queued"
        # The launched job payload carries the AI-chosen render settings.
        assert data["job"]["payload"]["render_tier"] in ("draft", "balanced", "quality", "auto")


def test_auto_unknown_preset_is_400(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "nope", "run": False},
        )
        assert resp.status_code == 400


def _upload_ref_image(store, proj, name="painting.png", size=(256, 144)):
    from PIL import Image

    refs = store.project_dir(proj.id) / "assets" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 60, 90)).save(refs / name)
    return f"assets/refs/{name}"


def test_animate_layers_parallax_launches_job(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    ref = _upload_ref_image(store, proj)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/animate_layers",
            json={"source_asset": ref, "mode": "parallax", "fps": 12, "duration_s": 1.0, "width": 256, "height": 256},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["ok"] is True
        assert data["job"]["type"] == "layered_animation"
        assert data["job"]["payload"]["mode"] == "parallax"
        assert data["job"]["payload"]["motion_schedule"]  # AI-built motion schedule


def test_animate_layers_masked_requires_mask(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    ref = _upload_ref_image(store, proj)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/animate_layers",
            json={"source_asset": ref, "mode": "masked", "masks": []},
        )
        assert resp.status_code == 400


def test_animate_layers_missing_source_is_400(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/animate_layers",
            json={"source_asset": "assets/refs/missing.png", "mode": "parallax"},
        )
        assert resp.status_code == 400


def test_auto_routes_parallax_preset_to_layered_job(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    ref = _upload_ref_image(store, proj)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "parallax_animation", "run": True, "source_asset": ref},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["launched"] is True
        assert data["animation_mode"] == "parallax"
        assert data["job"]["type"] == "layered_animation"


def test_auto_masked_preset_defers_to_animate_layers(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    _patch(monkeypatch, store, jobs)
    ref = _upload_ref_image(store, proj)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "masked_object_motion", "run": True, "source_asset": ref},
        )
        resp.raise_for_status()
        data = resp.json()
        # masked needs explicit masks -> not auto-launched
        assert data["launched"] is False
        assert any("mask" in n.lower() for n in data.get("notes", []))


def test_auto_requires_plan(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    proj = store.create("No Plan")
    proj.meta = {"timeline": {}}
    store.save(proj)
    _patch(monkeypatch, store, jobs)
    with TestClient(backend_app.app) as client:
        resp = client.post(
            f"/v1/projects/{proj.id}/render/auto",
            json={"preset": "balanced_motion", "run": False},
        )
        assert resp.status_code == 400
