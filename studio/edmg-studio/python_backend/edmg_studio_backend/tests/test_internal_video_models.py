from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import internal_video_models as ivm
from edmg_studio_backend.tests.safetensors_test_utils import (
    write_minimal_safetensors,
)


def test_hunyuan_chunking_anchors_stitches_and_reports(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setattr(ivm, "validate_video_model_layout", lambda *_: None)
    calls = []

    def run(_model, **kwargs):
        calls.append(kwargs)
        base = len(calls) * 40
        return [Image.new("RGB", (2, 2), (base + i, 0, 0)) for i in range(kwargs["num_frames"])]

    monkeypatch.setattr(ivm, "_run_hunyuan", run)
    progress = []
    frames = ivm.generate_video_model_frames(
        engine="hunyuan_video15", video_model_dir=model, base_model_dir=model,
        init_image=None, prompt="motion", negative_prompt="", width=2, height=2,
        num_frames=9, fps=24, steps=2, cfg=1, seed=7, device="cuda",
        generation_mode="t2v", chunk_frames=5, chunk_overlap=2,
        chunk_callback=lambda current, total: progress.append((current, total)),
    )
    assert [call["num_frames"] for call in calls] == [5, 5, 3]
    assert calls[0]["init_image"] is None
    assert calls[1]["init_image"].getpixel((0, 0)) == (44, 0, 0)
    assert len(frames) == 9
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert frames[3].getpixel((0, 0))[0] not in {43, 80}


def test_hunyuan_i2v_requires_source(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setattr(ivm, "validate_video_model_layout", lambda *_: None)
    with pytest.raises(Exception) as exc:
        ivm.generate_video_model_frames(
            engine="hunyuan_video15", video_model_dir=model, base_model_dir=model,
            init_image=None, prompt="", negative_prompt="", width=2, height=2,
            num_frames=2, fps=24, steps=2, cfg=1, seed=1, device="cuda",
            generation_mode="i2v",
        )
    assert getattr(exc.value, "code", None) == "HUNYUAN_I2V_SOURCE_REQUIRED"


def test_hunyuan_cancels_between_chunks(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setattr(ivm, "validate_video_model_layout", lambda *_: None)
    calls = []
    monkeypatch.setattr(
        ivm,
        "_run_hunyuan",
        lambda _model, **kwargs: calls.append(kwargs)
        or [Image.new("RGB", (2, 2)) for _ in range(kwargs["num_frames"])],
    )

    def cancel():
        if calls:
            raise RuntimeError("canceled")

    with pytest.raises(RuntimeError, match="canceled"):
        ivm.generate_video_model_frames(
            engine="hunyuan_video15", video_model_dir=model, base_model_dir=model,
            init_image=None, prompt="", negative_prompt="", width=2, height=2,
            num_frames=8, fps=24, steps=2, cfg=1, seed=1, device="cuda",
            generation_mode="t2v", chunk_frames=5, chunk_overlap=2,
            cancel_check=cancel,
        )
    assert len(calls) == 1


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


def test_motion_adapter_layout_is_rejected_for_svd(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"_class_name": "MotionAdapter"}',
        encoding="utf-8",
    )
    (tmp_path / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")

    with pytest.raises(UserFacingError) as exc:
        ivm.validate_video_model_layout("svd", tmp_path)

    assert exc.value.code == "INTERNAL_VIDEO_MODEL_LAYOUT_INVALID"
    assert "model_index.json" in (exc.value.hint or "")
    assert str(tmp_path) not in exc.value.message
    assert str(tmp_path) not in (exc.value.hint or "")


def test_svd_layout_is_rejected_for_animatediff(tmp_path: Path) -> None:
    (tmp_path / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )

    with pytest.raises(UserFacingError) as exc:
        ivm.validate_video_model_layout("animatediff", tmp_path)

    assert exc.value.code == "INTERNAL_VIDEO_MODEL_LAYOUT_INVALID"
    assert "config.json" in (exc.value.hint or "")
    assert str(tmp_path) not in exc.value.message
    assert str(tmp_path) not in (exc.value.hint or "")


def test_video_model_layout_accepts_canonical_assets(tmp_path: Path) -> None:
    svd_dir = tmp_path / "svd"
    svd_dir.mkdir()
    (svd_dir / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )
    animatediff_dir = tmp_path / "animatediff"
    animatediff_dir.mkdir()
    (animatediff_dir / "config.json").write_text(
        '{"_class_name": "MotionAdapter"}',
        encoding="utf-8",
    )
    (animatediff_dir / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")

    ivm.validate_video_model_layout("svd", svd_dir)
    ivm.validate_video_model_layout("animatediff", animatediff_dir)


def test_hunyuan_layout_requires_official_upstream_config(tmp_path: Path) -> None:
    model_dir = tmp_path / "hunyuan"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        '{"_class_name": "HunyuanVideo_1_5_Pipeline"}', encoding="utf-8"
    )
    ivm.validate_video_model_layout("hunyuan_video15", model_dir)

    (model_dir / "config.json").write_text(
        '{"_class_name": "HunyuanVideo15Pipeline"}', encoding="utf-8"
    )
    with pytest.raises(UserFacingError, match="does not match"):
        ivm.validate_video_model_layout("hunyuan_video15", model_dir)


def test_hunyuan_wsl_runner_maps_paths_and_isolates_cuda(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "hunyuan"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        '{"_class_name": "HunyuanVideo_1_5_Pipeline"}', encoding="utf-8"
    )
    env = {
        "EDMG_HUNYUAN15_RUNNER": "wsl", "EDMG_HUNYUAN15_WSL_DISTRO": "Ubuntu",
        "EDMG_HUNYUAN15_PYTHON": "/opt/hunyuan/bin/python", "EDMG_HUNYUAN15_REPO": "/opt/HunyuanVideo-1.5",
        "EDMG_HUNYUAN15_LLM_PATH": "/models/qwen", "EDMG_HUNYUAN15_BYT5_PATH": "/models/byt5",
        "EDMG_HUNYUAN15_GLYPH_PATH": "/models/glyph", "EDMG_HUNYUAN15_VISION_PATH": "/models/siglip",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ivm, "validate_hunyuan_runner", lambda: [])
    monkeypatch.setattr(ivm, "_wsl_path", lambda path, _config: "/mnt/c/" + Path(path).name)
    monkeypatch.setattr(ivm, "_decode_video", lambda *_args, **_kwargs: [Image.new("RGB", (32, 32))] * 2)
    calls = []

    class Proc:
        returncode = 0
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            output = tmp_path / ".hunyuan-runs" / "run" / "output.mp4"
            output.write_bytes(b"mp4")
        def poll(self): return 0
        def communicate(self, timeout=None): return ("", "")

    # Keep generated files in tmp_path and resolve the mocked output by basename.
    monkeypatch.setattr(ivm.uuid, "uuid4", lambda: SimpleNamespace(hex="run"))
    monkeypatch.setattr(ivm.subprocess, "Popen", Proc)
    frames = ivm.generate_video_model_frames(
        engine="hunyuan_video15", video_model_dir=model_dir, base_model_dir=tmp_path,
        init_image=None, prompt="p", negative_prompt="n", width=32, height=32,
        num_frames=2, fps=24, steps=3, cfg=4.0, seed=7, device="cuda:2", workspace=tmp_path,
    )
    command, kwargs = calls[0]
    assert command[:4] == ["wsl.exe", "--distribution", "Ubuntu", "--exec"]
    assert "CUDA_VISIBLE_DEVICES=2" in command
    assert "-m" in command
    assert "edmg_studio_backend.services.hunyuan_video15_worker" in command
    assert any(value.startswith("PYTHONPATH=/mnt/c/HunyuanVideo-1.5:/mnt/c/python_backend") for value in command)
    assert len(frames) == 2
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "2"


def test_hunyuan_runner_fails_closed_without_explicit_configuration(monkeypatch) -> None:
    for name in ("RUNNER", "PYTHON", "REPO", "WSL_DISTRO", "LLM_PATH", "BYT5_PATH", "GLYPH_PATH", "VISION_PATH"):
        monkeypatch.delenv(f"EDMG_HUNYUAN15_{name}", raising=False)
    issues = ivm.validate_hunyuan_runner()
    assert any("RUNNER" in issue for issue in issues)
    assert any("VISION_PATH" in issue for issue in issues)


def test_hunyuan_wsl_probe_preserves_linux_companion_paths(monkeypatch) -> None:
    env = {
        "EDMG_HUNYUAN15_RUNNER": "wsl", "EDMG_HUNYUAN15_WSL_DISTRO": "Ubuntu",
        "EDMG_HUNYUAN15_PYTHON": "/opt/hunyuan/bin/python", "EDMG_HUNYUAN15_REPO": "/opt/HunyuanVideo-1.5",
        "EDMG_HUNYUAN15_LLM_PATH": "/models/qwen", "EDMG_HUNYUAN15_BYT5_PATH": "/models/byt5",
        "EDMG_HUNYUAN15_GLYPH_PATH": "/models/glyph", "EDMG_HUNYUAN15_VISION_PATH": "/models/siglip",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ivm.shutil, "which", lambda _name: "wsl.exe")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ivm.subprocess, "run", fake_run)

    assert ivm.validate_hunyuan_runner() == []
    required = captured["command"][captured["command"].index("-c") + 2]
    assert "\\\\models" not in required
    assert "/models/qwen/config.json" in required


def test_hunyuan_config_persists_allowlisted_values_and_preserves_launcher_settings(tmp_path, monkeypatch) -> None:
    launcher_env = tmp_path / "launcher_env.json"
    launcher_env.write_text(json.dumps({"EDMG_STUDIO_HOME": "C:/studio", "UNRELATED": "keep"}), encoding="utf-8")
    monkeypatch.setenv("EDMG_LAUNCHER_ENV", str(launcher_env))
    monkeypatch.setattr(ivm, "validate_hunyuan_runner", lambda **_kwargs: [])


    result = ivm.update_hunyuan_runner_config({
        "mode": "wsl",
        "distro": "Ubuntu",
        "python": "/opt/hunyuan/bin/python",
        "repo": "/opt/HunyuanVideo-1.5",
        "timeout_s": 1800,
        "llm": "/models/qwen",
        "byt5": "/models/byt5",
        "glyph": "/models/glyph",
        "vision": "/models/siglip",
        "ignored": "must not be persisted",
    })

    saved = json.loads(launcher_env.read_text(encoding="utf-8"))
    assert saved["UNRELATED"] == "keep"
    assert saved["EDMG_STUDIO_HOME"] == "C:/studio"
    assert saved["EDMG_HUNYUAN15_RUNNER"] == "wsl"
    assert saved["EDMG_HUNYUAN15_TIMEOUT_SECONDS"] == "1800.0"
    assert "ignored" not in json.dumps(saved)
    assert result["config"]["repo"] == "/opt/HunyuanVideo-1.5"


def test_hunyuan_config_rejects_invalid_mode_without_writing(tmp_path, monkeypatch) -> None:
    launcher_env = tmp_path / "launcher_env.json"
    launcher_env.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EDMG_LAUNCHER_ENV", str(launcher_env))

    with pytest.raises(ValueError, match="mode"):
        ivm.update_hunyuan_runner_config({"mode": "windows"})

    assert json.loads(launcher_env.read_text(encoding="utf-8")) == {}

def test_video_model_cache_key_separates_cpu_offload(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    scheduler_calls: list[dict[str, object]] = []
    attention_slicing_calls = 0

    class FakeAdapter:
        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

    class FakePipe:
        def __init__(self) -> None:
            self.offload = False
            self.scheduler = SimpleNamespace(config={"beta_schedule": "scaled_linear"})

        @classmethod
        def from_pretrained(cls, *_args, **kwargs):
            calls.append(dict(kwargs))
            return cls()

        def enable_attention_slicing(self):
            nonlocal attention_slicing_calls
            attention_slicing_calls += 1
            return None

        def enable_model_cpu_offload(self):
            self.offload = True
            return None

        def to(self, _device):
            return self

    class FakeScheduler:
        @classmethod
        def from_config(cls, config, **kwargs):
            scheduler_calls.append({"config": dict(config), **kwargs})
            return SimpleNamespace(config={**dict(config), **kwargs})

    monkeypatch.setitem(
        __import__("sys").modules,
        "diffusers",
        type(
            "FakeDiffusers",
            (),
            {
                "AnimateDiffPipeline": FakePipe,
                "DDIMScheduler": FakeScheduler,
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
    assert scheduler_calls == [
        {
            "config": {"beta_schedule": "scaled_linear"},
            "beta_schedule": "linear",
            "timestep_spacing": "linspace",
            "steps_offset": 1,
            "clip_sample": False,
        },
        {
            "config": {"beta_schedule": "scaled_linear"},
            "beta_schedule": "linear",
            "timestep_spacing": "linspace",
            "steps_offset": 1,
            "clip_sample": False,
        },
    ]
    assert second.offload is True
    assert attention_slicing_calls == 0


def test_svd_uses_native_conditioning_and_preserves_whole_pil_frames(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "svd"
    model_dir.mkdir()
    (model_dir / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    source_frames = [
        Image.new("RGB", (64, 40), color=(255, 0, 0)),
        Image.new("RGB", (64, 40), color=(0, 255, 0)),
    ]

    class FakePipe:
        def __call__(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(frames=[source_frames])

    monkeypatch.setattr(ivm, "_load_svd_pipeline", lambda *_args, **_kwargs: FakePipe())
    monkeypatch.setattr(ivm, "_seeded_generator", lambda seed, _device: (object(), int(seed or 0)))

    frames = ivm.generate_video_model_frames(
        engine="svd",
        video_model_dir=model_dir,
        base_model_dir=tmp_path / "base",
        init_image=Image.new("RGB", (64, 40), color="white"),
        prompt="single subject",
        negative_prompt="collage",
        width=64,
        height=40,
        num_frames=2,
        fps=2,
        steps=20,
        cfg=9.8,
        seed=123,
        device="cuda",
        decode_chunk_size=1,
        cpu_offload=True,
    )

    assert captured["fps"] == ivm.SVD_CONDITIONING_FPS
    assert captured["min_guidance_scale"] == ivm.SVD_MIN_GUIDANCE_SCALE
    assert captured["max_guidance_scale"] == ivm.SVD_MAX_GUIDANCE_SCALE
    assert captured["output_type"] == "pil"
    assert [frame.size for frame in frames] == [(64, 40), (64, 40)]
    assert frames[0].getpixel((0, 0)) == (255, 0, 0)
    assert frames[1].getpixel((0, 0)) == (0, 255, 0)


def test_video_model_rejects_incomplete_frame_sequences(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "svd"
    model_dir.mkdir()
    (model_dir / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )

    class FakePipe:
        def __call__(self, **_kwargs):
            return SimpleNamespace(frames=[[Image.new("RGB", (64, 40), color="white")]])

    monkeypatch.setattr(ivm, "_load_svd_pipeline", lambda *_args, **_kwargs: FakePipe())
    monkeypatch.setattr(ivm, "_seeded_generator", lambda seed, _device: (object(), int(seed or 0)))

    with pytest.raises(RuntimeError, match="returned 1 frames; expected 2"):
        ivm.generate_video_model_frames(
            engine="svd",
            video_model_dir=model_dir,
            base_model_dir=tmp_path / "base",
            init_image=Image.new("RGB", (64, 40), color="white"),
            prompt="single subject",
            negative_prompt="collage",
            width=64,
            height=40,
            num_frames=2,
            fps=2,
            steps=20,
            cfg=7.0,
            seed=123,
            device="cuda",
        )


def test_animatediff_requests_whole_pil_frames(tmp_path: Path, monkeypatch) -> None:
    adapter_dir = tmp_path / "animatediff"
    adapter_dir.mkdir()
    (adapter_dir / "config.json").write_text(
        '{"_class_name": "MotionAdapter"}',
        encoding="utf-8",
    )
    (adapter_dir / "diffusion_pytorch_model.safetensors").write_bytes(b"weights")
    captured: dict[str, object] = {}

    class FakePipe:
        def __call__(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                frames=[
                    [
                        Image.new("RGB", (64, 40), color=(0, 0, 255)),
                        Image.new("RGB", (64, 40), color=(255, 255, 0)),
                    ]
                ]
            )

    monkeypatch.setattr(ivm, "_load_animatediff_pipeline", lambda **_kwargs: FakePipe())
    monkeypatch.setattr(ivm, "_seeded_generator", lambda seed, _device: (object(), int(seed or 0)))

    frames = ivm.generate_video_model_frames(
        engine="animatediff",
        video_model_dir=adapter_dir,
        base_model_dir=tmp_path / "base",
        init_image=None,
        prompt="single subject walking",
        negative_prompt="collage",
        width=64,
        height=40,
        num_frames=2,
        fps=2,
        steps=20,
        cfg=9.8,
        seed=456,
        device="cuda",
    )

    assert captured["output_type"] == "pil"
    assert captured["guidance_scale"] == ivm.ANIMATEDIFF_MAX_GUIDANCE_SCALE
    assert [frame.size for frame in frames] == [(64, 40), (64, 40)]
    assert frames[0].getpixel((0, 0)) == (0, 0, 255)
    assert frames[1].getpixel((0, 0)) == (255, 255, 0)


def test_cuda_oom_message_becomes_user_facing_error() -> None:
    assert ivm._is_cuda_out_of_memory(RuntimeError("CUDA out of memory. Tried to allocate 2 GiB."))
    with pytest.raises(UserFacingError) as exc:
        ivm._raise_cuda_oom("AnimateDiff", RuntimeError("CUDA out of memory"))
    assert exc.value.code == "INTERNAL_VIDEO_MODEL_CUDA_OOM"
