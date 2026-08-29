from __future__ import annotations

from edmg_studio_backend.services.model_catalog import built_in_catalog
from edmg_studio_backend.services.model_manager import (
    _entry_support_flags,
    _normalize_catalog_entry,
)
from edmg_studio_backend.services.tensorrt_standalone import DEFAULT_SD15_BASE_MODEL


def test_sd15_uses_the_canonical_hugging_face_repository() -> None:
    canonical_repo = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    entries = {entry["id"]: entry for entry in built_in_catalog()}

    assert entries["hf_sd15_internal"]["hf_repo_id"] == canonical_repo
    assert entries["local_sd15_tensorrt_bundle"]["render"]["base_model_id"] == canonical_repo
    assert DEFAULT_SD15_BASE_MODEL == canonical_repo


def test_flux_schnell_is_a_native_txt2img_keyframe_model() -> None:
    entry = {item["id"]: item for item in built_in_catalog()}["hf_flux1_schnell_internal"]
    normalized = _normalize_catalog_entry(entry)

    assert entry["hf_repo_id"] == "black-forest-labs/FLUX.1-schnell"
    assert entry["license_id"] == "Apache-2.0"
    assert entry["family"] == "flux"
    assert entry["target"] == {"engine": "internal", "folder": "diffusers"}
    assert entry["supports_internal_video"] is False
    assert entry["render"]["render_modes"] == ["stills", "internal_video_keyframes"]
    assert normalized["supports_internal_video"] is False
    assert normalized["render"]["render_modes"] == ["stills", "internal_video_keyframes"]
    assert _entry_support_flags(entry) == {
        "supports_txt2img": True,
        "supports_img2img": False,
        "supports_inpaint": False,
        "supports_outpaint": False,
        "supports_controlnet": False,
    }
