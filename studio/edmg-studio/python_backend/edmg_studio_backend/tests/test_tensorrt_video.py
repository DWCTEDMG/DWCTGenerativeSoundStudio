from __future__ import annotations

from pathlib import Path

from PIL import Image

from edmg_studio_backend import app as app_module
from edmg_studio_backend.services import tensorrt_video
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
