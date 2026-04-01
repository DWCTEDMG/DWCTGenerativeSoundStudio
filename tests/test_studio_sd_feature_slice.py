from __future__ import annotations

import json
from pathlib import Path

import pytest
from edmg_studio_backend import app as studio_app
from edmg_studio_backend.integrations import comfyui as comfy
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore
from PIL import Image


def _make_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    jobs = JobStore(store.projects_dir)
    proj = store.create("Stable Diffusion Slice")
    store.save(proj)
    return store, jobs, proj


def test_default_workflow_chains_loras_into_sampler():
    wf = comfy.default_workflow(
        checkpoint="base.safetensors",
        prompt="neon city",
        negative_prompt="low quality",
        seed=123,
        width=1024,
        height=576,
        steps=28,
        cfg=7.0,
        sampler="euler",
        loras=[
            {"filename": "style-a.safetensors", "weight": 0.8},
            {"filename": "style-b.safetensors", "weight": 1.15},
        ],
    )

    lora_nodes = {node_id: node for node_id, node in wf.items() if node.get("class_type") == "LoraLoader"}
    assert len(lora_nodes) == 2

    final_lora_node = sorted(lora_nodes.keys(), key=int)[-1]
    sampler = next(node for node in wf.values() if node.get("class_type") == "KSampler")
    positive = next(
        node for node in wf.values()
        if node.get("class_type") == "CLIPTextEncode" and node.get("inputs", {}).get("text") == "neon city"
    )

    assert sampler["inputs"]["model"] == [final_lora_node, 0]
    assert positive["inputs"]["clip"] == [final_lora_node, 1]


def test_run_comfyui_scene_writes_metadata_sidecar(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)
    monkeypatch.setattr(
        studio_app,
        "_resolve_comfy_still_selection",
        lambda **kwargs: {
            "checkpoint": "base.safetensors",
            "workflow_family": "txt2img",
            "controlnet_name": None,
            "conditioning_mode": "raw",
        },
    )
    monkeypatch.setattr(
        studio_app.models,
        "resolve_loras",
        lambda items: [
            {
                "name": "Cinematic Detail LoRA",
                "filename": "cinematic-detail.safetensors",
                "path": str(tmp_path / "cinematic-detail.safetensors"),
                "weight": 0.9,
                "clip_weight": 0.9,
            }
        ],
    )
    monkeypatch.setattr(studio_app.comfy_pool, "acquire", lambda req: "http://comfy.local")
    monkeypatch.setattr(studio_app.comfy_pool, "release", lambda url: None)
    monkeypatch.setattr(studio_app.comfy, "default_workflow", lambda **kwargs: {"ok": True, "workflow": kwargs})
    monkeypatch.setattr(studio_app.comfy, "submit_prompt", lambda url, wf: {"prompt_id": "prompt-123"})
    monkeypatch.setattr(studio_app.comfy, "get_history", lambda url, prompt_id: {"prompt-123": {"outputs": {}}})
    monkeypatch.setattr(
        studio_app.comfy,
        "extract_output_images",
        lambda history: [{"filename": "frame.png", "subfolder": "", "type": "output"}],
    )
    monkeypatch.setattr(studio_app.comfy, "extract_execution_error", lambda history: None)
    monkeypatch.setattr(studio_app.comfy, "download_image_bytes", lambda *args, **kwargs: b"fake-png")

    out_path = store.project_dir(proj.id) / "outputs" / "images" / "scene.png"
    result = studio_app._run_comfyui_scene(
        proj.id,
        "job12345",
        {
            "variant_index": 0,
            "scene_index": 0,
            "model_id": "hf_sd35_large_turbo_ckpt",
            "prompt": "A luminous skyline over water",
            "negative_prompt": "blurry, watermark",
            "seed": 77,
            "width": 1024,
            "height": 576,
            "steps": 30,
            "cfg": 7.5,
            "sampler": "euler",
            "workflow_family": "txt2img",
            "loras": [{"name": "cinematic-detail", "weight": 0.9}],
            "out_path": str(out_path),
        },
    )

    metadata_path = out_path.with_name(f"{out_path.name}.json")
    assert out_path.exists()
    assert metadata_path.exists()
    assert result["metadata_path"] == str(metadata_path)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["prompt"] == "A luminous skyline over water"
    assert metadata["base_model"]["checkpoint"] == "base.safetensors"
    assert metadata["loras"][0]["filename"] == "cinematic-detail.safetensors"
    assert metadata["output"]["image"].replace("\\", "/") == "outputs/images/scene.png"


def test_prepare_outpaint_assets_generates_canvas_and_mask(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    refs_dir = store.project_dir(proj.id) / "assets" / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    src = refs_dir / "source.png"
    Image.new("RGB", (64, 32), (20, 40, 60)).save(src)

    prepared = studio_app._prepare_still_scene_assets(
        proj.id,
        {
            "source_asset": "assets/refs/source.png",
            "outpaint": {"top_px": 10, "right_px": 5, "bottom_px": 0, "left_px": 3},
            "width": 64,
            "height": 32,
        },
        "outpaint",
    )

    assert prepared["mask_source"] == "generated_outpaint"
    assert prepared["source_path"] is not None
    assert prepared["mask_path"] is not None

    with Image.open(prepared["source_path"]) as expanded:
        assert expanded.size == (72, 42)
    with Image.open(prepared["mask_path"]) as mask:
        assert mask.size == (72, 42)


def test_prepare_outpaint_assets_prefers_explicit_mask_override(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    refs_dir = store.project_dir(proj.id) / "assets" / "refs"
    masks_dir = store.project_dir(proj.id) / "assets" / "masks"
    refs_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (64, 32), (20, 40, 60)).save(refs_dir / "source.png")
    Image.new("L", (64, 32), 255).save(masks_dir / "override.png")

    prepared = studio_app._prepare_still_scene_assets(
        proj.id,
        {
            "source_asset": "assets/refs/source.png",
            "inpaint_mask": "assets/masks/override.png",
            "outpaint": {"top_px": 10, "right_px": 5, "bottom_px": 0, "left_px": 3},
            "width": 64,
            "height": 32,
        },
        "outpaint",
    )

    assert prepared["mask_source"] == "explicit_mask_with_margins"
    with Image.open(prepared["source_path"]) as expanded:
        assert expanded.size == (72, 42)
    with Image.open(prepared["mask_path"]) as mask:
        assert mask.size == (72, 42)


def test_export_comfyui_workflows_writes_multi_controlnet_refs(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    proj.meta["last_plan"] = {
        "variants": [
            {
                "name": "Variant 1",
                "scenes": [{"start_s": 0, "end_s": 8, "prompt": "neon skyline"}],
            }
        ]
    }
    store.save(proj)

    refs_dir = store.project_dir(proj.id) / "assets" / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (255, 0, 0)).save(refs_dir / "source.png")
    Image.new("RGB", (64, 64), (0, 255, 0)).save(refs_dir / "depth.png")

    monkeypatch.setattr(
        studio_app,
        "_resolve_still_scene_selection",
        lambda **kwargs: {
            "checkpoint": "base.safetensors",
            "workflow_family": "controlnet",
            "controlnet_name": None,
            "conditioning_mode": "raw",
            "engine": "comfyui",
            "family": "sdxl",
        },
    )
    monkeypatch.setattr(
        studio_app,
        "_normalize_controlnet_units",
        lambda raw_units, **kwargs: [
            {
                "controlnet_name": "controlnet-canny.safetensors",
                "reference_asset": "assets/refs/source.png",
                "conditioning_mode": "edge",
                "strength": 0.8,
                "start_percent": 0.0,
                "end_percent": 1.0,
            },
            {
                "controlnet_name": "controlnet-depth.safetensors",
                "reference_asset": "assets/refs/depth.png",
                "conditioning_mode": "raw",
                "strength": 0.65,
                "start_percent": 0.1,
                "end_percent": 0.9,
            },
        ],
    )
    monkeypatch.setattr(studio_app, "_prepare_condition_image", lambda project_id, path, mode: path)
    monkeypatch.setattr(studio_app.comfy, "controlnet_workflow", lambda **kwargs: {"workflow": kwargs})

    result = studio_app.export_comfyui_workflows(
        proj.id,
        variant_index=0,
        model_id="hf_sdxl_base_1_0",
        workflow_family="controlnet",
        controlnet_units_json=json.dumps(
            [
                {
                    "model": "hf_sdxl_controlnet_canny",
                    "reference_asset": "assets/refs/source.png",
                    "conditioning_mode": "edge",
                },
                {
                    "model": "hf_sdxl_controlnet_depth",
                    "reference_asset": "assets/refs/depth.png",
                    "conditioning_mode": "raw",
                },
            ]
        ),
    )

    assert result["ok"] is True
    exported = store.project_dir(proj.id) / result["files"][0]
    payload = json.loads(exported.read_text(encoding="utf-8"))
    units = payload["workflow"]["controlnet_units"]
    assert len(units) == 2
    assert units[0]["reference_image"].startswith("refs/")
    assert units[1]["reference_image"].startswith("refs/")


def test_export_comfyui_workflows_rejects_internal_still_models(tmp_path, monkeypatch):
    store, jobs, proj = _make_project(tmp_path)
    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "jobs", jobs)

    proj.meta["last_plan"] = {
        "variants": [
            {
                "name": "Variant 1",
                "scenes": [{"start_s": 0, "end_s": 8, "prompt": "neon skyline"}],
            }
        ]
    }
    store.save(proj)

    monkeypatch.setattr(
        studio_app,
        "_resolve_still_scene_selection",
        lambda **kwargs: {
            "checkpoint": None,
            "workflow_family": "txt2img",
            "controlnet_name": None,
            "conditioning_mode": "raw",
            "engine": "internal",
            "family": "sdxl",
            "model_path": Path(tmp_path / "internal-model"),
        },
    )

    with pytest.raises(studio_app.UserFacingError) as exc:
        studio_app.export_comfyui_workflows(
            proj.id,
            variant_index=0,
            model_id="hf_sdxl_internal",
            workflow_family="txt2img",
        )

    assert exc.value.code == "EXPORT_ENGINE_UNSUPPORTED"
