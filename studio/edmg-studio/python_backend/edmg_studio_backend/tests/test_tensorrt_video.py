from __future__ import annotations

from pathlib import Path

from PIL import Image

from edmg_studio_backend import app as app_module
from edmg_studio_backend.services import internal_video
from edmg_studio_backend.services import tensorrt_video
from edmg_studio_backend.services import tensorrt_standalone
from edmg_studio_backend.services.internal_video import InternalVideoSettings


def test_stale_tensorrt_runtime_bundle_selection_maps_to_supported_video_bundle() -> None:
    payload = {"model_id": "hf_svd_xt_1_1_tensorrt_bundle"}

    assert app_module._payload_requests_tensorrt_video(payload) is True
    assert app_module._tensorrt_model_id_from_payload(payload) == "local_sd15_tensorrt_bundle"
    warning = app_module._tensorrt_requested_model_warning(payload) or ""
    assert "hf_svd_xt_1_1_tensorrt_bundle" in warning
    assert "discovery-only" in warning
    assert "SD1.5 keyframes" in warning


def test_render_tensorrt_video_variant_uses_keyframes_and_assembles_video(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "project"
    generated_dir = tmp_path / "generated"
    calls: list[dict] = []
    progress_events: list[tuple[str, int, int, str | None]] = []

    def fake_run_job(project_id: str, job_id: str | None, payload: dict) -> dict:
        calls.append({"project_id": project_id, "job_id": job_id, "payload": dict(payload)})
        generated_dir.mkdir(parents=True, exist_ok=True)
        out = generated_dir / f"key_{len(calls):04d}.png"
        Image.new("RGB", (512, 512), (40 * len(calls), 24, 96)).save(out)
        return {"output_path": str(out)}

    def fake_assemble(*, ffmpeg_path: str, frames_dir: Path, out_mp4: Path, fps: int) -> None:
        assert ffmpeg_path == "ffmpeg"
        assert fps == 2
        assert len(list(frames_dir.glob("frame_*.png"))) == 4
        out_mp4.write_bytes(b"raw")

    def fake_interpolate(*, ffmpeg_path: str, in_mp4: Path, out_mp4: Path, fps_out: int, engine: str) -> None:
        assert fps_out == 4
        assert engine == "fps"
        out_mp4.write_bytes(in_mp4.read_bytes() + b"-interp")

    def fake_mux(*, ffmpeg_path: str, video_mp4: Path, audio_path: Path, out_mp4: Path) -> None:
        assert audio_path.name == "song.wav"
        out_mp4.write_bytes(video_mp4.read_bytes() + b"-audio")

    monkeypatch.setattr(tensorrt_video.tensorrt_standalone, "run_job", fake_run_job)
    monkeypatch.setattr(tensorrt_video, "assemble_image_sequence", fake_assemble)
    monkeypatch.setattr(tensorrt_video, "interpolate_video_fps", fake_interpolate)
    monkeypatch.setattr(tensorrt_video, "mux_audio", fake_mux)

    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"wav")

    out = tensorrt_video.render_tensorrt_video_variant(
        ffmpeg_path="ffmpeg",
        project_id="p1",
        project_dir=project_dir,
        variant={"index": 2, "duration_s": 2.0},
        scenes=[{"start_s": 0, "end_s": 2, "prompt": "neon skyline"}],
        audio_path=audio_path,
        settings=InternalVideoSettings(
            fps_render=2,
            fps_output=4,
            steps=3,
            cfg=6.5,
            sampler="pndm",
            seed=123,
            keyframe_interval_s=1.0,
            interpolation_engine="fps",
        ),
        model_id="local_sd15_tensorrt_bundle",
        progress_fn=lambda stage, current, total, message=None: progress_events.append((stage, current, total, message)),
    )

    assert out.exists()
    assert out.read_bytes().endswith(b"-interp-audio")
    assert out.name.startswith("internal_trt_v02_")
    assert len(calls) == 2
    for call in calls:
        payload = call["payload"]
        assert call["project_id"] == "p1"
        assert call["job_id"] is None
        assert payload["model_id"] == "local_sd15_tensorrt_bundle"
        assert payload["width"] == 512
        assert payload["height"] == 512
        assert payload["batch_size"] == 1
    assert len(list((project_dir / "outputs" / "tensorrt_video").glob("*/frames/frame_*.png"))) == 4
    assert progress_events[-1][0] == "complete"


def test_tensorrt_sd15_keyframe_anchor_resizes_and_uses_bundle(tmp_path, monkeypatch) -> None:
    generated = tmp_path / "trt.png"
    Image.new("RGB", (512, 512), (12, 34, 56)).save(generated)
    calls: list[dict] = []

    def fake_run_job(project_id: str, job_id: str | None, payload: dict) -> dict:
        calls.append({"project_id": project_id, "job_id": job_id, "payload": dict(payload)})
        return {"output_path": str(generated)}

    monkeypatch.setattr(tensorrt_standalone, "run_job", fake_run_job)

    image = internal_video._generate_tensorrt_sd15_keyframe(
        project_id="p1",
        prompt="neon skyline",
        negative_prompt="blur",
        width=320,
        height=180,
        steps=4,
        cfg=6.5,
        sampler="pndm",
        seed=123,
        model_id="local_sd15_tensorrt_bundle",
    )

    assert image.size == (320, 180)
    assert calls[0]["project_id"] == "p1"
    assert calls[0]["job_id"] is None
    assert calls[0]["payload"]["model_id"] == "local_sd15_tensorrt_bundle"
    assert calls[0]["payload"]["workflow_family"] == "sd15"
    assert "width" not in calls[0]["payload"]
    assert "height" not in calls[0]["payload"]


def test_video_model_preflight_reports_tensorrt_anchor_renderer() -> None:
    preflight = internal_video.describe_internal_video_model_preflight(
        scenes=[{"start_s": 0, "end_s": 2, "prompt": "neon skyline"}],
        timeline=None,
        settings=InternalVideoSettings(
            temporal_mode="video_model",
            motion_strategy="storyboard_full_motion",
            video_model_engine="svd",
            video_model_keyframe_renderer="tensorrt_sd15",
            video_model_keyframe_model_id="local_sd15_tensorrt_bundle",
        ),
        duration_s=2.0,
        total_frames=4,
        hardware={"backend": "cuda", "vram_gb": 6.0},
    )

    assert preflight["keyframe_renderer"] == "tensorrt_sd15"
    assert preflight["keyframe_model_id"] == "local_sd15_tensorrt_bundle"
    assert preflight["storyboard_motion_plan"]["anchor_source"] == "tensorrt_sd15_keyframe"


def test_video_model_scene_motion_refines_prompt_and_preflight() -> None:
    settings = InternalVideoSettings(
        temporal_mode="video_model",
        motion_strategy="storyboard_full_motion",
        video_model_prompt_refine=True,
        video_model_scene_motion="scene",
        video_model_motion_score_mode="manual",
        video_model_manual_motion_score=6,
    )
    refined = internal_video._refine_video_model_prompt(  # noqa: SLF001 - pure prompt helper
        "cinematic figure in an old town",
        score_info={"motion_score": 6},
        settings=settings,
    )
    assert "whole scene" in refined
    assert "visible objects themselves move" in refined

    preflight = internal_video.describe_internal_video_model_preflight(
        scenes=[{"start_s": 0, "end_s": 2, "prompt": "cinematic figure in an old town"}],
        timeline=None,
        settings=settings,
        duration_s=2.0,
        total_frames=4,
        hardware={"backend": "cuda", "vram_gb": 12.0},
    )
    assert preflight["scene_motion"] == "scene"
    assert preflight["storyboard_motion_plan"]["shots"][0]["scene_motion"] == "scene"


def test_svd_low_vram_memory_safety_caps_settings_and_warns() -> None:
    settings = InternalVideoSettings(
        temporal_mode="video_model",
        video_model_engine="svd",
        video_model_id="hf_svd_xt_1_1_internal",
        video_model_max_frames_per_scene=25,
        video_model_decode_chunk_size=8,
        temporal_steps=20,
    )

    safe = app_module._apply_internal_video_model_memory_safety(
        settings,
        {"backend": "cuda", "vram_gb": 6.0},
    )
    warnings = app_module._internal_video_model_memory_warnings(
        safe,
        {"backend": "cuda", "vram_gb": 6.0},
    )

    assert safe.video_model_cpu_offload is True
    assert safe.video_model_max_frames_per_scene == 8
    assert safe.video_model_decode_chunk_size == 1
    assert safe.temporal_steps == 6
    assert any("6 GB CUDA SVD safety" in warning for warning in warnings)


def test_svd_low_vram_canvas_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(internal_video, "_cuda_total_vram_gb", lambda _device: 6.0)

    width, height, note = internal_video._video_model_adapter_canvas(  # noqa: SLF001 - pure sizing helper
        engine="svd",
        width=768,
        height=432,
        device="cuda",
        cpu_offload=True,
    )

    assert (width, height) == (568, 320)
    assert note == "6 GB CUDA SVD canvas capped to 568x320"
