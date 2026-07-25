from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from edmg_studio_backend import app as studio_app
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore
from PIL import Image


pytestmark = pytest.mark.skipif(
    os.getenv("EDMG_ENABLE_LIVE_STILL_SMOKE") != "1",
    reason="Set EDMG_ENABLE_LIVE_STILL_SMOKE=1 to run live still-image smoke tests against installed models.",
)


def _make_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    proj = store.create("Live Still Smoke")
    store.save(proj)
    return store, jobs, proj


def _write_source_assets(store: ProjectStore, project_id: str) -> tuple[str, str]:
    project_dir = store.project_dir(project_id)
    refs_dir = project_dir / "assets" / "refs"
    masks_dir = project_dir / "assets" / "masks"
    refs_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    source_path = refs_dir / "source.png"
    mask_path = masks_dir / "mask.png"
    Image.new("RGB", (768, 512), (36, 54, 92)).save(source_path)
    Image.new("L", (768, 512), 255).save(mask_path)
    return "assets/refs/source.png", "assets/masks/mask.png"


def _installed_or_skip(model_id: str) -> Path:
    installed = studio_app.models.installed_path(model_id)
    if installed is None or not installed.exists():
        pytest.skip(f"{model_id} is not installed in this workspace.")
    return installed


def _run_internal_live(tmp_path: Path, payload: dict[str, object]) -> dict[str, object]:
    store, jobs, proj = _make_project(tmp_path)
    studio_app.store = store  # type: ignore[attr-defined]
    studio_app.jobs = jobs  # type: ignore[attr-defined]
    result = studio_app._run_internal_still_scene(proj.id, "live-internal", payload)
    assert Path(str(result["saved"])).exists()
    return result


def test_internal_sdxl_txt2img_smoke(tmp_path):
    _installed_or_skip("hf_sdxl_internal")
    result = _run_internal_live(
        tmp_path,
        {
            "variant_index": 0,
            "scene_index": 0,
            "model_id": "hf_sdxl_internal",
            "family": "sdxl",
            "workflow_family": "txt2img",
            "prompt": "Studio smoke test skyline, crisp detail, volumetric dusk light",
            "negative_prompt": "blurry, watermark",
            "seed": 101,
            "width": 768,
            "height": 512,
            "steps": 12,
            "cfg": 6.5,
            "sampler": "euler",
            "hires_fix": {"enabled": True, "scale": 1.25, "denoise": 0.25, "upscaler": "pixel_lanczos"},
            "out_path": str(tmp_path / "data" / "outputs" / "images" / "sdxl_txt2img.png"),
        },
    )
    metadata = json.loads(Path(str(result["metadata_path"])).read_text(encoding="utf-8"))
    assert metadata["base_model"]["model_id"] == "hf_sdxl_internal"


def test_internal_sd35_outpaint_smoke(tmp_path):
    _installed_or_skip("hf_sd35_medium_internal")
    store, jobs, proj = _make_project(tmp_path)
    studio_app.store = store  # type: ignore[attr-defined]
    studio_app.jobs = jobs  # type: ignore[attr-defined]
    source_asset, _mask_asset = _write_source_assets(store, proj.id)

    result = studio_app._run_internal_still_scene(
        proj.id,
        "live-outpaint",
        {
            "variant_index": 0,
            "scene_index": 0,
            "model_id": "hf_sd35_medium_internal",
            "family": "sd35",
            "workflow_family": "outpaint",
            "prompt": "Expand the frame naturally with coherent architecture and clouds",
            "negative_prompt": "blurry, seams",
            "seed": 202,
            "width": 768,
            "height": 512,
            "steps": 10,
            "cfg": 6.0,
            "sampler": "euler",
            "source_asset": source_asset,
            "outpaint": {"top_px": 64, "right_px": 96, "bottom_px": 32, "left_px": 32},
            "denoise_strength": 0.55,
            "out_path": str(tmp_path / "data" / "outputs" / "images" / "sd35_outpaint.png"),
        },
    )
    assert Path(str(result["saved"])).exists()


def test_internal_sdxl_controlnet_smoke(tmp_path):
    _installed_or_skip("hf_sdxl_internal")
    try:
        studio_app.models.resolve_internal_asset("hf_sdxl_controlnet_canny_internal", folder="controlnet", allowed_kinds={"controlnet"})
    except Exception:
        pytest.skip("Internal SDXL ControlNet model is not installed.")

    store, jobs, proj = _make_project(tmp_path)
    studio_app.store = store  # type: ignore[attr-defined]
    studio_app.jobs = jobs  # type: ignore[attr-defined]
    source_asset, _mask_asset = _write_source_assets(store, proj.id)

    result = studio_app._run_internal_still_scene(
        proj.id,
        "live-controlnet",
        {
            "variant_index": 0,
            "scene_index": 0,
            "model_id": "hf_sdxl_internal",
            "family": "sdxl",
            "workflow_family": "controlnet",
            "prompt": "Architectural smoke test with strong edge structure",
            "negative_prompt": "blurry",
            "seed": 303,
            "width": 768,
            "height": 512,
            "steps": 10,
            "cfg": 6.0,
            "sampler": "euler",
            "controlnet_units": [
                {
                    "model": "hf_sdxl_controlnet_canny_internal",
                    "reference_asset": source_asset,
                    "conditioning_mode": "edge",
                    "strength": 0.7,
                    "start_percent": 0.0,
                    "end_percent": 1.0,
                }
            ],
            "out_path": str(tmp_path / "data" / "outputs" / "images" / "sdxl_controlnet.png"),
        },
    )
    assert Path(str(result["saved"])).exists()


@pytest.mark.skipif(
    os.getenv("EDMG_ENABLE_LIVE_COMFY_STILL_SMOKE") != "1",
    reason="Set EDMG_ENABLE_LIVE_COMFY_STILL_SMOKE=1 to include live ComfyUI still smoke tests.",
)
def test_comfy_sdxl_txt2img_smoke(tmp_path, monkeypatch):
    _installed_or_skip("hf_sdxl_base_1_0")
    node_url = os.getenv("EDMG_LIVE_COMFYUI_URL") or "http://127.0.0.1:8188"

    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)
    monkeypatch.setattr(studio_app.comfy_pool, "acquire", lambda req: node_url)
    monkeypatch.setattr(studio_app.comfy_pool, "release", lambda url: None)

    result = studio_app._run_comfyui_scene(
        proj.id,
        "live-comfy",
        {
            "variant_index": 0,
            "scene_index": 0,
            "model_id": "hf_sdxl_base_1_0",
            "prompt": "Studio smoke test for ComfyUI, cinematic skyline, clean detail",
            "negative_prompt": "blurry, watermark",
            "seed": 404,
            "width": 768,
            "height": 512,
            "steps": 16,
            "cfg": 6.5,
            "sampler": "euler",
            "workflow_family": "txt2img",
            "out_path": str(tmp_path / "data" / "outputs" / "images" / "comfy_sdxl.png"),
        },
    )
    assert Path(str(result["saved"])).exists()
