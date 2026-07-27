from __future__ import annotations

from pathlib import Path

import pytest

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import internal_video_models as ivm
from edmg_studio_backend.tests.safetensors_test_utils import (
    write_minimal_safetensors,
)


def _write_lfs_pointer(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
        "size 123456\n",
        encoding="utf-8",
    )


def test_video_model_load_kwargs_uses_real_fp16_bin_when_safetensors_is_lfs_pointer(tmp_path: Path) -> None:
    _write_lfs_pointer(tmp_path / "unet" / "diffusion_pytorch_model.fp16.safetensors")
    (tmp_path / "unet" / "diffusion_pytorch_model.fp16.bin").write_bytes(b"real fp16 bin weights")
    (tmp_path / "text_encoder").mkdir(parents=True)
    write_minimal_safetensors(
        tmp_path / "text_encoder" / "model.fp16.safetensors"
    )

    kwargs = ivm._video_model_base_load_kwargs(tmp_path, "cuda")

    assert kwargs["variant"] == "fp16"
    assert kwargs["use_safetensors"] is False


def test_video_model_load_kwargs_keeps_real_fp16_safetensors_preferred(tmp_path: Path) -> None:
    (tmp_path / "unet").mkdir(parents=True)
    write_minimal_safetensors(
        tmp_path / "unet" / "diffusion_pytorch_model.fp16.safetensors"
    )

    kwargs = ivm._video_model_base_load_kwargs(tmp_path, "cuda")

    assert kwargs["variant"] == "fp16"
    assert "use_safetensors" not in kwargs


def test_video_model_load_error_wraps_git_lfs_message(tmp_path: Path) -> None:
    with pytest.raises(UserFacingError) as exc:
        ivm._reraise_video_model_load_error(
            RuntimeError("You seem to have cloned a repository without having git-lfs installed."),
            tmp_path,
        )
    assert exc.value.code == "INTERNAL_VIDEO_MODEL_LFS_POINTER"


def test_video_model_cache_key_separates_cpu_offload(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeAdapter:
        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

    class FakePipe:
        def __init__(self) -> None:
            self.offload = False

        @classmethod
        def from_pretrained(cls, *_args, **kwargs):
            calls.append(dict(kwargs))
            return cls()

        def enable_attention_slicing(self):
            return None

        def enable_model_cpu_offload(self):
            self.offload = True
            return None

        def to(self, _device):
            return self

    monkeypatch.setitem(
        __import__("sys").modules,
        "diffusers",
        type(
            "FakeDiffusers",
            (),
            {
                "AnimateDiffPipeline": FakePipe,
                "MotionAdapter": FakeAdapter,
            },
        ),
    )
    monkeypatch.setattr(ivm, "_parse_torch_dtype", lambda _dtype, _device: "float16")
    ivm.clear_video_pipeline_cache()

    first = ivm._load_animatediff_pipeline(
        adapter_dir=tmp_path / "adapter",
        base_model_dir=tmp_path / "base",
        device="cuda",
        dtype="float16",
        cpu_offload=False,
    )
    second = ivm._load_animatediff_pipeline(
        adapter_dir=tmp_path / "adapter",
        base_model_dir=tmp_path / "base",
        device="cuda",
        dtype="float16",
        cpu_offload=True,
    )

    assert first is not second
    assert len(calls) == 2
    assert second.offload is True


def test_cuda_oom_message_becomes_user_facing_error() -> None:
    assert ivm._is_cuda_out_of_memory(RuntimeError("CUDA out of memory. Tried to allocate 2 GiB."))
    with pytest.raises(UserFacingError) as exc:
        ivm._raise_cuda_oom("AnimateDiff", RuntimeError("CUDA out of memory"))
    assert exc.value.code == "INTERNAL_VIDEO_MODEL_CUDA_OOM"
