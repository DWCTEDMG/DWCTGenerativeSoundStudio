"""Tests for the ComfyUI regional (per-object) motion workflow builder."""

from __future__ import annotations

from edmg_studio_backend.integrations import comfyui as cf


def _classes(workflow):
    return [node["class_type"] for node in workflow.values()]


def test_regional_workflow_has_core_animatediff_nodes():
    wf = cf.regional_motion_workflow(
        checkpoint="sd.safetensors",
        base_prompt="neon city street",
        negative_prompt="blurry",
        seed=7,
        width=512,
        height=288,
        steps=20,
        cfg=7.0,
        sampler="euler",
        frames=16,
        motion_model_name="mm_sd_v15_v2.ckpt",
        regions=[],
    )
    classes = _classes(wf)
    for required in ("CheckpointLoaderSimple", "ADE_AnimateDiffLoaderGen1", "KSampler", "SaveImage"):
        assert required in classes
    # No regions -> no masking nodes
    assert "ConditioningSetMask" not in classes


def test_regional_workflow_builds_one_chain_per_region():
    regions = [
        {"prompt": "glowing eyes", "mask_filename": "eyes.png", "strength": 1.0},
        {"prompt": "waving flag", "mask_filename": "flag.png", "strength": 0.8},
    ]
    wf = cf.regional_motion_workflow(
        checkpoint="sd.safetensors",
        base_prompt="castle",
        negative_prompt="blurry",
        seed=1,
        width=512,
        height=288,
        steps=20,
        cfg=7.0,
        sampler="euler",
        frames=16,
        motion_model_name="mm.ckpt",
        regions=regions,
    )
    classes = _classes(wf)
    assert classes.count("ConditioningSetMask") == 2
    assert classes.count("ConditioningCombine") == 2
    assert classes.count("LoadImage") == 2
    assert classes.count("ImageToMask") == 2
    # KSampler positive should reference the last ConditioningCombine
    ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
    pos_ref = ksampler["inputs"]["positive"][0]
    assert wf[pos_ref]["class_type"] == "ConditioningCombine"


def test_regional_workflow_skips_incomplete_regions():
    regions = [
        {"prompt": "", "mask_filename": "x.png"},  # no prompt
        {"prompt": "subject", "mask_filename": ""},  # no mask
        {"prompt": "good", "mask_filename": "ok.png"},
    ]
    wf = cf.regional_motion_workflow(
        checkpoint="sd.safetensors",
        base_prompt="scene",
        negative_prompt="bad",
        seed=1,
        width=512,
        height=288,
        steps=20,
        cfg=7.0,
        sampler="euler",
        frames=8,
        motion_model_name="mm.ckpt",
        regions=regions,
    )
    assert _classes(wf).count("ConditioningSetMask") == 1
