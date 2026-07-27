from __future__ import annotations

from edmg_studio_backend.services.model_catalog import built_in_catalog
from edmg_studio_backend.services.tensorrt_standalone import DEFAULT_SD15_BASE_MODEL


def test_sd15_uses_the_canonical_hugging_face_repository() -> None:
    canonical_repo = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    entries = {entry["id"]: entry for entry in built_in_catalog()}

    assert entries["hf_sd15_internal"]["hf_repo_id"] == canonical_repo
    assert entries["local_sd15_tensorrt_bundle"]["render"]["base_model_id"] == canonical_repo
    assert DEFAULT_SD15_BASE_MODEL == canonical_repo
