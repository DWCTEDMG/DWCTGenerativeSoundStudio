from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from edmg_studio_backend import app as app_module
from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.schemas import InternalVideoRenderRequest, TensorRTStandaloneRenderRequest
from edmg_studio_backend.services import internal_video, tensorrt_standalone, tensorrt_video
from edmg_studio_backend.services.internal_video import InternalVideoSettings
from edmg_studio_backend.store.jobs import JobStore
from edmg_studio_backend.store.projects import ProjectStore
from edmg_studio_backend.tests.revision_client import TestClient


def _make_render_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    project = store.create("TensorRT Path Handoff")
    project.meta = {
        "last_plan": {
            "variants": [
                {
                    "index": 0,
                    "duration_s": 1.0,
                    "scenes": [{"start_s": 0.0, "end_s": 1.0, "prompt": "neon skyline"}],
                }
            ]
        }
    }
    store.save(project)
    return store, project


def test_internal_render_prioritizes_applied_director_document(tmp_path: Path) -> None:
    store, project = _make_render_project(tmp_path)
    project.meta["timeline"] = {
        "timebase": {"sample_rate": 48000, "frame_rate": 24},
    }
    project.meta["director_document"] = {
        "version": 1,
        "story_bible": {
            "project_theme": "Cosmic road",
            "visual_style": "living oil painting",
            "continuity_rules": ["Keep the traveler moving left to right"],
        },
        "scenes": [
            {
                "scene_id": "reviewed-scene-1",
                "start_sample": "0",
                "end_sample": "192000",
                "intent": "The traveler crosses the moonlit road.",
                "actions": ["walks steadily while the coat and hair move"],
                "camera": {"shot_type": "wide", "movement": "lateral dolly"},
                "environment": {
                    "location": "foggy rural town",
                    "secondary_motion": ["fog and lantern light move at different depths"],
                },
            }
        ],
    }
    project.meta["director_workflow"] = {"source_variant": {}}

    variant, used_fallback = app_module._internal_render_variant_or_fallback(project, 0)

    assert used_fallback is False
    assert variant["_render_plan_source"] == "applied_director_document"
    assert variant["duration_s"] == 4.0
    scene = variant["scenes"][0]
    ltx_package = scene["director_prompt_packages"]["ltx_25"]
    assert scene["id"] == "reviewed-scene-1"
    assert scene["start_s"] == 0.0
    assert scene["end_s"] == 4.0
    assert scene["director_scene"]["scene_id"] == "reviewed-scene-1"
    assert scene["action"] == "walks steadily while the coat and hair move"
    assert scene["camera"] == "lateral dolly"
    assert scene["environment_motion"] == "fog and lantern light move at different depths"
    assert ltx_package["engine"] == "ltx_25"
    assert ltx_package["scene_source_hash"]
    assert "walks steadily" in ltx_package["prompt"]
    assert scene["prompt"] != "neon skyline"


class _RunningJobs:
    def get(self, _project_id: str, _job_id: str):
        return SimpleNamespace(status="running", progress={})

    def append_log(self, *_args, **_kwargs) -> None:
        return None

    def update_progress(self, *_args, **_kwargs) -> None:
        return None


def test_internal_settings_parse_video_model_timeline_camera_toggle() -> None:
    default_settings = app_module._internal_settings_from_payload(
        {}, model_id="hf_sd15_internal", render_tier="balanced", device_preference="cuda"
    )
    disabled_settings = app_module._internal_settings_from_payload(
        {"video_model_apply_timeline_camera": "false"},
        model_id="hf_sd15_internal",
        render_tier="balanced",
        device_preference="cuda",
    )

    assert default_settings.video_model_apply_timeline_camera is True
    assert disabled_settings.video_model_apply_timeline_camera is False


def test_storyboard_full_motion_preserves_disabled_prompt_refinement() -> None:
    settings = app_module._internal_settings_from_payload(
        {
            "motion_strategy": "storyboard_full_motion",
            "storyboard_shot_max_s": 4.8,
            "keyframe_interval_s": 6.0,
            "video_model_prompt_refine": False,
        },
        model_id="hf_sd15_internal",
        render_tier="balanced",
        device_preference="cuda",
    )

    resolved = app_module._apply_storyboard_full_motion_settings(
        settings,
        {"video_model_scene_motion": "scene"},
    )

    assert resolved.video_model_prompt_refine is False
    assert resolved.video_model_motion_score_mode == "auto"
    assert resolved.video_model_scene_motion == "scene"
    assert resolved.keyframe_continuity_mode == "project"
    assert resolved.video_model_max_frames_per_scene >= 8
    assert resolved.keyframe_interval_s == 4.8


def test_storyboard_full_motion_preserves_explicit_motion_score_mode() -> None:
    settings = app_module._internal_settings_from_payload(
        {
            "motion_strategy": "storyboard_full_motion",
            "video_model_motion_score_mode": "manual",
            "video_model_manual_motion_score": 5,
        },
        model_id="hf_sd15_internal",
        render_tier="draft",
        device_preference="cuda",
    )

    resolved = app_module._apply_storyboard_full_motion_settings(settings, {})

    assert resolved.video_model_motion_score_mode == "manual"
    assert resolved.video_model_manual_motion_score == 5


def test_studio_resource_policy_reports_native_sdpa_on_6gb_cuda() -> None:
    policy = app_module._studio_native_resource_policy(
        settings_obj=InternalVideoSettings(
            temporal_mode="video_model",
            device_preference="cuda",
        ),
        hw={"backend": "cuda", "vram_gb": 6.0},
        model_family="sd15",
    )

    assert policy["attention_policy"] == "native_sdpa_with_vae_slicing_and_small_decode_chunks"


def test_internal_video_request_accepts_cinematic_both_anchor_mode() -> None:
    request = InternalVideoRenderRequest(video_model_anchor_mode="both")

    assert request.video_model_anchor_mode == "both"


def test_internal_video_request_validates_keyframe_continuity_mode() -> None:
    assert InternalVideoRenderRequest().keyframe_continuity_mode == "scene"
    assert (
        InternalVideoRenderRequest(keyframe_continuity_mode="project").keyframe_continuity_mode
        == "project"
    )

    with pytest.raises(ValueError):
        InternalVideoRenderRequest(keyframe_continuity_mode="sequence")  # type: ignore[arg-type]


def test_internal_video_request_rejects_invalid_hunyuan_chunk_overlap() -> None:
    with pytest.raises(ValueError, match="chunk overlap must be smaller"):
        InternalVideoRenderRequest(
            video_model_engine="hunyuan_video15",
            hunyuan_chunk_frames=8,
            hunyuan_chunk_overlap=8,
        )

    request = InternalVideoRenderRequest(
        video_model_engine="ltx_25",
        hunyuan_chunk_frames=2,
        hunyuan_chunk_overlap=2,
    )
    assert request.video_model_engine == "ltx_25"


def test_internal_video_request_validates_ltx_multi_gpu_contract() -> None:
    request = InternalVideoRenderRequest(
        video_model_engine="ltx_25",
        ltx_execution_mode="scene_parallel",
        ltx_cuda_devices=[0, 1, 2],
        ltx_scene_worker_cap=3,
        ltx_allow_mode_fallback=False,
    )

    assert request.ltx_cuda_devices == [0, 1, 2]
    with pytest.raises(ValueError, match="must be unique"):
        InternalVideoRenderRequest(ltx_cuda_devices=[0, 0])
    with pytest.raises(ValueError, match="requires scene continuity"):
        InternalVideoRenderRequest(
            ltx_execution_mode="scene_parallel",
            keyframe_continuity_mode="project",
        )


def test_ltx_execution_resolution_is_explicit_and_safe() -> None:
    settings = InternalVideoSettings(ltx_cuda_devices=(0, 1, 2), ltx_scene_worker_cap=3)
    assert internal_video.resolve_ltx_execution(
        settings,
        available_cuda_devices=(0, 1, 2),
        model_parallel_ready=False,
    ) == ("scene_parallel", (0, 1, 2))

    with pytest.raises(UserFacingError) as model_parallel_error:
        internal_video.resolve_ltx_execution(
            InternalVideoSettings(
                ltx_execution_mode="model_parallel",
                ltx_cuda_devices=(0, 1, 2),
                ltx_allow_mode_fallback=False,
            ),
            available_cuda_devices=(0, 1, 2),
            model_parallel_ready=False,
        )
    assert model_parallel_error.value.code == "LTX_MODEL_PARALLEL_UNAVAILABLE"

    with pytest.raises(UserFacingError) as unqualified_model_parallel_error:
        internal_video.resolve_ltx_execution(
            InternalVideoSettings(
                ltx_execution_mode="model_parallel",
                ltx_cuda_devices=(0, 1, 2),
                ltx_allow_mode_fallback=False,
            ),
            available_cuda_devices=(0, 1, 2),
            model_parallel_ready=True,
        )
    assert unqualified_model_parallel_error.value.code == "LTX_MODEL_PARALLEL_UNAVAILABLE"

    assert internal_video.resolve_ltx_execution(
        InternalVideoSettings(
            ltx_execution_mode="model_parallel",
            ltx_cuda_devices=(0, 1, 2),
            ltx_allow_mode_fallback=True,
        ),
        available_cuda_devices=(0, 1, 2),
        model_parallel_ready=True,
    ) == ("scene_parallel", (0, 1, 2))

    with pytest.raises(UserFacingError) as single_gpu_model_parallel_error:
        internal_video.resolve_ltx_execution(
            InternalVideoSettings(
                ltx_execution_mode="model_parallel",
                ltx_cuda_devices=(1,),
                ltx_allow_mode_fallback=True,
            ),
            available_cuda_devices=(0, 1),
            model_parallel_ready=True,
        )
    assert single_gpu_model_parallel_error.value.code == "LTX_MODEL_PARALLEL_UNAVAILABLE"

    assert internal_video.resolve_ltx_execution(
        InternalVideoSettings(
            ltx_execution_mode="scene_parallel",
            ltx_cuda_devices=(0,),
            ltx_allow_mode_fallback=True,
        ),
        available_cuda_devices=(0, 1, 2),
        model_parallel_ready=False,
    ) == ("single", (0,))

    assert internal_video.resolve_ltx_execution(
        InternalVideoSettings(
            ltx_execution_mode="single",
            ltx_cuda_devices=(1,),
            ltx_allow_mode_fallback=False,
        ),
        available_cuda_devices=(0, 1, 2),
        model_parallel_ready=False,
    ) == ("single", (1,))


def test_internal_settings_parse_keyframe_continuity_mode() -> None:
    default_settings = app_module._internal_settings_from_payload(
        {}, model_id="hf_sd15_internal", render_tier="balanced", device_preference="cuda"
    )
    project_settings = app_module._internal_settings_from_payload(
        {"keyframe_continuity_mode": "project"},
        model_id="hf_sd15_internal",
        render_tier="balanced",
        device_preference="cuda",
    )
    invalid_settings = app_module._internal_settings_from_payload(
        {"keyframe_continuity_mode": "sequence"},
        model_id="hf_sd15_internal",
        render_tier="balanced",
        device_preference="cuda",
    )

    assert default_settings.keyframe_continuity_mode == "scene"
    assert project_settings.keyframe_continuity_mode == "project"
    assert invalid_settings.keyframe_continuity_mode == "scene"

    resolved_payload = app_module._persist_resolved_internal_video_payload(
        {"keyframe_continuity_mode": "scene"},
        {"mode": "diffusion", "settings": {"keyframe_continuity_mode": "project"}},
    )
    assert resolved_payload["keyframe_continuity_mode"] == "project"


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
    bundle_path = tmp_path / "TensorRT Bundle With Spaces"
    bundle_path.mkdir()
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
        bundle_path=bundle_path,
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
        assert payload["model_path"] == str(bundle_path.resolve())
        assert payload["width"] == 512
        assert payload["height"] == 512
        assert payload["batch_size"] == 1
    assert len(list((project_dir / "outputs" / "tensorrt_video").glob("*/frames/frame_*.png"))) == 4
    assert progress_events[-1][0] == "complete"


def test_app_worker_passes_exact_preflight_bundle_path_to_tensorrt_video(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    bundle_path = tmp_path / "Canonical TensorRT Bundle With Spaces"
    bundle_path.mkdir()
    captured: dict = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        output = store.project_dir(project.id) / "outputs" / "videos" / "tensorrt.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", _RunningJobs())
    monkeypatch.setattr(
        app_module,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {
            "mode": "tensorrt",
            "model_id": "local_sd15_tensorrt_bundle",
            "model_path": str(bundle_path.resolve()),
            "estimated_frames": 2,
            "estimated_keyframes": 1,
            "warnings": [],
        },
    )
    monkeypatch.setattr(app_module, "render_tensorrt_video_variant", fake_render)

    result = app_module._run_internal_video(project.id, "job-1", {"render_mode": "tensorrt"})

    assert result["mode"] == "tensorrt"
    assert captured["bundle_path"] == bundle_path.resolve()
    assert captured["model_id"] == "local_sd15_tensorrt_bundle"


def test_standalone_worker_resolves_private_bundle_path_only_at_execution(tmp_path, monkeypatch) -> None:
    bundle_path = tmp_path / "Private TensorRT Bundle"
    bundle_path.mkdir()
    calls: list[tuple[str, str, dict]] = []

    def fake_run_job(project_id: str, job_id: str, payload: dict, *, cancel_check=None) -> dict:
        assert cancel_check is None
        calls.append((project_id, job_id, dict(payload)))
        return {"ok": True, "output_path": "outputs/stills/keyframe.png"}

    monkeypatch.setattr(
        app_module,
        "_resolve_installed_model_path",
        lambda model_id, *, materialize_remote: bundle_path
        if model_id == "local_sd15_tensorrt_bundle" and materialize_remote
        else None,
    )
    monkeypatch.setattr(tensorrt_standalone, "run_job", fake_run_job)
    persisted_payload = {"model_id": "local_sd15_tensorrt_bundle", "prompt": "neon skyline"}

    result = app_module._run_tensorrt_standalone("project-1", "job-1", persisted_payload)

    assert result["ok"] is True
    assert "model_path" not in persisted_payload
    assert calls == [
        (
            "project-1",
            "job-1",
            {
                "model_id": "local_sd15_tensorrt_bundle",
                "prompt": "neon skyline",
                "model_path": str(bundle_path.resolve()),
            },
        )
    ]


def test_app_worker_keeps_tensorrt_anchor_path_separate_from_video_model_path(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    base_path = tmp_path / "SD15 Base"
    svd_path = tmp_path / "SVD Motion Model"
    bundle_path = tmp_path / "TensorRT Anchor Bundle"
    for path in (base_path, svd_path, bundle_path):
        path.mkdir()
    settings = InternalVideoSettings(
        temporal_mode="video_model",
        device_preference="cuda",
        video_model_engine="svd",
        video_model_id="hf_svd_xt_1_1_internal",
        video_model_path=str(svd_path),
        video_model_keyframe_renderer="tensorrt_sd15",
        video_model_keyframe_model_id="local_sd15_tensorrt_bundle",
    )
    variant = project.meta["last_plan"]["variants"][0]
    captured: dict = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        output = store.project_dir(project.id) / "outputs" / "videos" / "anchor.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", _RunningJobs())
    monkeypatch.setattr(app_module, "_hardware_profile", lambda: {"backend": "cuda", "vram_gb": 12.0})
    monkeypatch.setattr(
        app_module,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {
            "mode": "diffusion",
            "estimated_frames": 2,
            "tier_plan": {"chunk_plan": {}},
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        app_module,
        "_resolve_internal_render_request",
        lambda _project_id, _payload: (
            project,
            variant,
            "hf_sd15_internal",
            base_path,
            bundle_path,
            settings,
        ),
    )
    monkeypatch.setattr(app_module, "render_internal_video_variant", fake_render)
    monkeypatch.setattr(app_module, "_load_render_checkpoint", lambda _path: None)

    result = app_module._run_internal_video(project.id, "job-2", {"render_mode": "diffusion"})

    assert result["mode"] == "diffusion"
    assert captured["model_dir"] == base_path
    assert captured["settings"].video_model_path == str(svd_path)
    assert captured["tensorrt_bundle_path"] == bundle_path
    assert result["artifact"] == {
        "path": "outputs/videos/anchor.mp4",
        "manifest_path": "outputs/videos/anchor.mp4.artifact.json",
        "kind": "video",
        "bytes": 5,
        "content_hash": None,
        "content_hash_alg": "sha256",
        "engine": "svd",
        "model": {"id": "hf_svd_xt_1_1_internal", "revision": None},
    }


def test_tensorrt_sd15_keyframe_anchor_resizes_and_uses_bundle(tmp_path, monkeypatch) -> None:
    generated = tmp_path / "trt.png"
    bundle_path = tmp_path / "TensorRT Anchor Bundle With Spaces"
    bundle_path.mkdir()
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
        model_path=bundle_path,
    )

    assert image.size == (320, 180)
    assert calls[0]["project_id"] == "p1"
    assert calls[0]["job_id"] is None
    assert calls[0]["payload"]["model_id"] == "local_sd15_tensorrt_bundle"
    assert calls[0]["payload"]["model_path"] == str(bundle_path.resolve())
    assert calls[0]["payload"]["workflow_family"] == "sd15"
    assert "width" not in calls[0]["payload"]
    assert "height" not in calls[0]["payload"]


def test_internal_request_resolves_distinct_server_side_tensorrt_anchor_path(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    base_path = tmp_path / "Internal SD15"
    svd_path = tmp_path / "Internal SVD"
    bundle_path = tmp_path / "Canonical TensorRT"
    for path in (base_path, svd_path, bundle_path):
        path.mkdir()
    (svd_path / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )

    class FakeModels:
        paths = {
            "hf_sd15_internal": base_path,
            "hf_svd_xt_1_1_internal": svd_path,
            "local_sd15_tensorrt_bundle": bundle_path,
        }

        def installed_path(self, model_id: str):
            return self.paths.get(model_id)

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "models", FakeModels())
    monkeypatch.setattr(app_module, "_hardware_profile", lambda: {"backend": "cuda", "vram_gb": 12.0})
    monkeypatch.setattr(
        app_module,
        "_build_internal_render_plan",
        lambda *_args, **_kwargs: {
            "preferred_internal_model": "hf_sd15_internal",
            "device_preference": "cuda",
            "defaults": {"temporal_mode": "video_model"},
            "applied_tier": "balanced",
        },
    )
    monkeypatch.setattr(app_module, "_render_provider_status", lambda _hw: {"settings": {"directml": {}}})
    monkeypatch.setattr(app_module, "_internal_model_family_for_request", lambda *_args: "sd15")
    monkeypatch.setattr(app_module, "_internal_model_hardware_issue", lambda *_args: None)
    monkeypatch.setattr(
        app_module,
        "_resolve_internal_video_model_selection",
        lambda *_args, **_kwargs: ("svd", "hf_svd_xt_1_1_internal", svd_path),
    )

    resolved = app_module._resolve_internal_render_request(
        project.id,
        {
            "model_id": "hf_sd15_internal",
            "device_preference": "cuda",
            "temporal_mode": "video_model",
            "video_model_engine": "svd",
            "video_model_id": "hf_svd_xt_1_1_internal",
            "video_model_keyframe_renderer": "tensorrt_sd15",
            "video_model_keyframe_model_id": "hf_svd_xt_1_1_tensorrt_bundle",
        },
    )

    _proj, _variant, model_id, resolved_base, resolved_bundle, settings = resolved
    assert model_id == "hf_sd15_internal"
    assert resolved_base == base_path
    assert settings.video_model_path == str(svd_path)
    assert settings.video_model_keyframe_model_id == "local_sd15_tensorrt_bundle"
    assert resolved_bundle == bundle_path.resolve()
    assert resolved_bundle not in {resolved_base, Path(settings.video_model_path)}


def test_internal_request_fails_preflight_when_tensorrt_anchor_bundle_is_missing(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    base_path = tmp_path / "Internal SD15"
    svd_path = tmp_path / "Internal SVD"
    base_path.mkdir()
    svd_path.mkdir()
    (svd_path / "model_index.json").write_text(
        '{"_class_name": "StableVideoDiffusionPipeline"}',
        encoding="utf-8",
    )

    class FakeModels:
        paths = {
            "hf_sd15_internal": base_path,
            "hf_svd_xt_1_1_internal": svd_path,
        }

        def installed_path(self, model_id: str):
            return self.paths.get(model_id)

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "models", FakeModels())
    monkeypatch.setattr(app_module, "_hardware_profile", lambda: {"backend": "cuda", "vram_gb": 12.0})
    monkeypatch.setattr(
        app_module,
        "_build_internal_render_plan",
        lambda *_args, **_kwargs: {
            "preferred_internal_model": "hf_sd15_internal",
            "device_preference": "cuda",
            "defaults": {"temporal_mode": "video_model"},
            "applied_tier": "balanced",
        },
    )
    monkeypatch.setattr(app_module, "_render_provider_status", lambda _hw: {"settings": {"directml": {}}})
    monkeypatch.setattr(app_module, "_internal_model_family_for_request", lambda *_args: "sd15")
    monkeypatch.setattr(app_module, "_internal_model_hardware_issue", lambda *_args: None)
    monkeypatch.setattr(
        app_module,
        "_resolve_internal_video_model_selection",
        lambda *_args, **_kwargs: ("svd", "hf_svd_xt_1_1_internal", svd_path),
    )

    with pytest.raises(UserFacingError) as exc:
        app_module._resolve_internal_render_request(
            project.id,
            {
                "model_id": "hf_sd15_internal",
                "device_preference": "cuda",
                "temporal_mode": "video_model",
                "video_model_engine": "svd",
                "video_model_id": "hf_svd_xt_1_1_internal",
                "video_model_keyframe_renderer": "tensorrt_sd15",
            },
        )

    assert exc.value.code == "TRT_ANCHOR_BUNDLE_NOT_INSTALLED"


def test_internal_request_resolves_explicit_hunyuan_without_still_model(tmp_path, monkeypatch) -> None:
    from edmg_studio_backend.services import engine_packages

    store, project = _make_render_project(tmp_path)
    hunyuan_path = tmp_path / "HunyuanVideo 1.5"
    hunyuan_path.mkdir()

    class FakeModels:
        def installed_path(self, model_id: str):
            return hunyuan_path if model_id == app_module.HUNYUAN_MODEL_ID else None

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "models", FakeModels())
    monkeypatch.setattr(app_module, "_hardware_profile", lambda: {"backend": "cuda", "vram_gb": 48.0})
    monkeypatch.setattr(app_module, "_build_internal_render_plan", lambda *_args, **_kwargs: {
        "preferred_internal_model": "hf_sd15_internal",
        "device_preference": "cuda",
        "defaults": {},
        "applied_tier": "quality",
    })
    monkeypatch.setattr(app_module, "_render_provider_status", lambda _hw: {"settings": {"directml": {}}})
    monkeypatch.setattr(engine_packages, "validate_package", lambda *args, **kwargs: {"valid": True})
    monkeypatch.setattr(engine_packages, "runtime_status", lambda *args, **kwargs: {"runtime_ready": True, "blockers": []})
    monkeypatch.setattr(app_module.internal_video_models, "validate_video_model_layout", lambda *args: None)

    resolved = app_module._resolve_internal_render_request(project.id, {
        "render_mode": "video_model",
        "model_id": "auto",
        "video_model_engine": "hunyuan_video15",
        "video_model_id": app_module.HUNYUAN_MODEL_ID,
    })

    assert resolved[2] == app_module.HUNYUAN_MODEL_ID
    assert resolved[3] == hunyuan_path
    assert resolved[5].temporal_mode == "video_model"
    assert resolved[5].video_model_path == str(hunyuan_path)


def test_anchorless_hunyuan_render_uses_native_text_to_video(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "hunyuan"
    model_path.mkdir()
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "red").save(source_path)
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        frames = []
        for index in range(kwargs["num_frames"]):
            frame = Image.new("RGB", (64, 64), "black")
            for x in range(8):
                for y in range(8):
                    frame.putpixel((index * 6 + x, 28 + y), (255, 255, 255))
            frames.append(frame)
        return frames

    monkeypatch.setattr(internal_video, "_device_auto", lambda _preference: "cpu")
    monkeypatch.setattr(internal_video, "validate_video_model_layout", lambda *_args: None)
    monkeypatch.setattr(internal_video, "generate_video_model_frames", fake_generate)
    monkeypatch.setattr(
        internal_video,
        "_try_load_pipelines",
        lambda *_args, **_kwargs: pytest.fail("still-image pipeline must not load"),
    )
    monkeypatch.setattr(
        internal_video,
        "_apply_video_anchor_frames",
        lambda *_args, **_kwargs: pytest.fail("anchor frames must not be applied"),
    )
    monkeypatch.setattr(
        internal_video,
        "assemble_image_sequence",
        lambda **kwargs: kwargs["out_mp4"].write_bytes(b"video"),
    )

    output = internal_video.render_internal_video_variant(
        ffmpeg_path="ffmpeg",
        project_dir=tmp_path,
        project_id="revision-proof-project",
        project_revision=37,
        variant={"index": 0, "duration_s": 4.0},
        scenes=[{"start_s": 0.0, "end_s": 4.0, "prompt": "a dancer spins"}],
        audio_path=None,
        model_dir=model_path,
        settings=InternalVideoSettings(
            width=64,
            height=64,
            fps_render=2,
            fps_output=2,
            temporal_mode="video_model",
            video_model_engine="hunyuan_video15",
            video_model_id=app_module.HUNYUAN_MODEL_ID,
            video_model_path=str(model_path),
            hunyuan_generation_mode="t2v",
            video_model_max_frames_per_scene=8,
            device_preference="cuda",
        ),
        source_image_path=source_path,
    )

    assert output.is_file()
    assert captured["init_image"] is None
    assert captured["base_model_dir"] == model_path
    assert captured["device"] == "cuda:0"
    proof = json.loads(output.with_suffix(output.suffix + ".temporal-proof.json").read_text(encoding="utf-8"))
    assert proof["project_id"] == "revision-proof-project"
    assert proof["project_revision"] == "37"


@pytest.mark.parametrize("always_static", [False, True])
def test_video_model_motion_retry_is_bounded(tmp_path, monkeypatch, always_static: bool) -> None:
    model_path = tmp_path / "hunyuan"
    model_path.mkdir()
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        if always_static or len(calls) == 1:
            return [Image.new("RGB", (64, 64), "black") for _ in range(kwargs["num_frames"])]
        frames = []
        for index in range(kwargs["num_frames"]):
            frame = Image.new("RGB", (64, 64), "black")
            for x in range(8):
                for y in range(8):
                    frame.putpixel((index * 6 + x, 28 + y), (255, 255, 255))
            frames.append(frame)
        return frames

    monkeypatch.setattr(internal_video, "validate_video_model_layout", lambda *_args: None)
    monkeypatch.setattr(internal_video, "generate_video_model_frames", fake_generate)
    monkeypatch.setattr(
        internal_video,
        "assemble_image_sequence",
        lambda **kwargs: kwargs["out_mp4"].write_bytes(b"video"),
    )
    settings = InternalVideoSettings(
        width=64,
        height=64,
        fps_render=2,
        fps_output=2,
        temporal_mode="video_model",
        video_model_engine="hunyuan_video15",
        video_model_id=app_module.HUNYUAN_MODEL_ID,
        video_model_path=str(model_path),
        hunyuan_generation_mode="t2v",
        video_model_max_frames_per_scene=8,
    )

    if always_static:
        with pytest.raises(UserFacingError) as exc_info:
            internal_video.render_internal_video_variant(
                ffmpeg_path="ffmpeg",
                project_dir=tmp_path,
                project_id="motion-retry-project",
                project_revision=1,
                variant={"index": 0, "duration_s": 4.0},
                scenes=[{"start_s": 0.0, "end_s": 4.0, "prompt": "a dancer spins"}],
                audio_path=None,
                model_dir=model_path,
                settings=settings,
            )
        assert exc_info.value.code == "INSUFFICIENT_TEMPORAL_MOTION"
        assert "after 3 attempts" in str(exc_info.value.hint)
        assert len(calls) == 3
        return

    output = internal_video.render_internal_video_variant(
        ffmpeg_path="ffmpeg",
        project_dir=tmp_path,
        project_id="motion-retry-project",
        project_revision=1,
        variant={"index": 0, "duration_s": 4.0},
        scenes=[{"start_s": 0.0, "end_s": 4.0, "prompt": "a dancer spins"}],
        audio_path=None,
        model_dir=model_path,
        settings=settings,
    )

    assert output.is_file()
    assert len(calls) == 2
    assert calls[0]["seed"] != calls[1]["seed"]
    metadata_paths = list((tmp_path / "outputs" / "videos").glob("*.render.json"))
    assert len(metadata_paths) == 1
    metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    assert len(metadata["motion_validation"]["native_scenes"]) == 1
    assert metadata["motion_validation"]["native_scenes"][0]["generation_attempt"] == 2


def test_ltx_motion_retry_changes_prompt_seed_and_conditioning() -> None:
    prompt = "A dancer moves through a living oil painting."
    first_prompt, first_strength = internal_video._video_model_motion_attempt_controls(  # noqa: SLF001
        engine="ltx_25", prompt=prompt, anchor_strength=0.2, attempt_index=0,
    )
    retry_prompt, retry_strength = internal_video._video_model_motion_attempt_controls(  # noqa: SLF001
        engine="ltx_25", prompt=prompt, anchor_strength=0.2, attempt_index=1,
    )
    final_prompt, final_strength = internal_video._video_model_motion_attempt_controls(  # noqa: SLF001
        engine="ltx_25", prompt=prompt, anchor_strength=0.2, attempt_index=2,
    )
    first_seed, _, _ = internal_video._video_model_motion_attempt_parameters(  # noqa: SLF001
        engine="ltx_25", seed=11, motion_bucket_id=127, noise_aug_strength=0.02, attempt_index=0,
    )
    retry_seed, _, _ = internal_video._video_model_motion_attempt_parameters(  # noqa: SLF001
        engine="ltx_25", seed=11, motion_bucket_id=127, noise_aug_strength=0.02, attempt_index=1,
    )

    assert first_prompt == prompt
    assert first_strength == pytest.approx(0.2)
    assert retry_seed != first_seed
    assert retry_strength == pytest.approx(0.14)
    assert final_strength == pytest.approx(0.08)
    assert "avoid static holds" in retry_prompt
    assert "no frozen intervals" in final_prompt

    unchanged_prompt, unchanged_strength = internal_video._video_model_motion_attempt_controls(  # noqa: SLF001
        engine="svd", prompt=prompt, anchor_strength=0.2, attempt_index=2,
    )
    assert unchanged_prompt == prompt
    assert unchanged_strength == pytest.approx(0.2)


def test_internal_video_request_rejects_flux_still_model(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    flux_path = tmp_path / "hf_flux1_schnell_internal"
    flux_path.mkdir()
    (flux_path / "model_index.json").write_text(
        '{"_class_name":"FluxPipeline"}',
        encoding="utf-8",
    )

    class FakeModels:
        def installed_path(self, model_id: str):
            return flux_path if model_id == "hf_flux1_schnell_internal" else None

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "models", FakeModels())
    monkeypatch.setattr(app_module, "_hardware_profile", lambda: {"backend": "cuda", "vram_gb": 6.0})
    monkeypatch.setattr(
        app_module,
        "_build_internal_render_plan",
        lambda *_args, **_kwargs: {
            "preferred_internal_model": "hf_sdxl_internal",
            "device_preference": "cuda",
            "defaults": {},
            "applied_tier": "draft",
        },
    )
    monkeypatch.setattr(app_module, "_render_provider_status", lambda _hw: {"settings": {"directml": {}}})

    with pytest.raises(UserFacingError) as exc:
        app_module._resolve_internal_render_request(
            project.id,
            {"model_id": "hf_flux1_schnell_internal", "device_preference": "cuda"},
        )

    assert exc.value.code == "FLUX_VIDEO_BASE_UNSUPPORTED"


def test_public_tensorrt_routes_reject_model_id_that_is_a_filesystem_path(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    local_directory = tmp_path / "client supplied local directory"
    local_directory.mkdir()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module.worker, "start", lambda *_args, **_kwargs: None)

    with TestClient(app_module.app) as client:
        for suffix in (
            "tensorrt-standalone",
            "tensorrt-standalone/preview",
            "tensorrt-deforum",
        ):
            response = client.post(
                f"/v1/projects/{project.id}/render/{suffix}",
                json={"model_id": str(local_directory)},
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "TRT_MODEL_UNSUPPORTED"
            assert "hint" in response.json()["error"]

    assert jobs.list_for_project(project.id) == []
    jobs.close()


def test_public_tensorrt_request_bounds_reject_unsafe_workloads(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module.worker, "start", lambda *_args, **_kwargs: None)

    invalid_payloads = [
        {"model_id": "local_sd15_tensorrt_bundle", "width": 16384},
        {"model_id": "local_sd15_tensorrt_bundle", "height": 1},
        {"model_id": "local_sd15_tensorrt_bundle", "steps": 100_000},
        {"model_id": "local_sd15_tensorrt_bundle", "batch_size": 100_000},
        {"model_id": "local_sd15_tensorrt_bundle", "prompt": "x" * 10_001},
    ]
    with TestClient(app_module.app) as client:
        for payload in invalid_payloads:
            response = client.post(
                f"/v1/projects/{project.id}/render/tensorrt-standalone",
                json=payload,
            )
            assert response.status_code == 422

    assert jobs.list_for_project(project.id) == []
    jobs.close()


def test_tensorrt_deforum_compatibility_route_queues_canonical_video(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    bundle_path = tmp_path / "Canonical TensorRT Bundle"
    bundle_path.mkdir()
    preflight_calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(
        app_module,
        "_server_resolved_tensorrt_payload",
        lambda req: {
            **req.model_dump(),
            "model_id": "local_sd15_tensorrt_bundle",
            "workflow_family": "sd15",
        },
    )
    monkeypatch.setattr(
        app_module,
        "_apply_active_parseq_motion",
        lambda _proj, payload: ({**payload, "parseq_applied": True}, {"summary": "applied"}),
    )
    monkeypatch.setattr(
        app_module,
        "_internal_render_preflight_data",
        lambda project_id, payload: preflight_calls.append((project_id, dict(payload)))
        or {
            "ok": True,
            "mode": "tensorrt",
            "model_id": "local_sd15_tensorrt_bundle",
            "model_path": str(bundle_path.resolve()),
            "estimated_frames": 12,
            "estimated_keyframes": 3,
            "settings": {"profile_width": 512, "profile_height": 512, "max_batch": 1},
        },
    )

    response = app_module.render_tensorrt_deforum(
        project.id,
        TensorRTStandaloneRenderRequest(
            variant_index=0,
            model_id="local_sd15_tensorrt_bundle",
            width=512,
            height=512,
        ),
    )

    queued = jobs.get(project.id, response["job"]["id"])
    assert queued is not None
    assert queued.type == "tensorrt_deforum"
    assert queued.payload["render_mode"] == "tensorrt"
    assert queued.payload["compatibility_source"] == "tensorrt-deforum"
    assert queued.payload["parseq_applied"] is True
    assert "model_path" not in queued.payload
    assert queued.progress["total"] == 18
    assert len(preflight_calls) == 1
    assert preflight_calls[0][0] == project.id
    assert preflight_calls[0][1]["render_mode"] == queued.payload["render_mode"]
    assert preflight_calls[0][1]["compatibility_source"] == queued.payload["compatibility_source"]
    assert response["preflight"]["settings"] == {
        "profile_width": 512,
        "profile_height": 512,
        "max_batch": 1,
    }
    assert "model_path" not in response["preflight"]
    assert response["compatibility"] == {
        "route": "tensorrt-deforum",
        "execution_mode": "canonical_tensorrt_keyframe_video",
        "legacy_deforum_schedule_applied": False,
    }
    jobs.close()


def test_public_render_preflight_recursively_removes_private_and_absolute_paths() -> None:
    public = app_module._public_render_preflight(
        {
            "ok": True,
            "model_id": "local_sd15_tensorrt_bundle",
            "model_path": r"C:\private\models\bundle",
            "cache": {
                "frames_dir": "/srv/edmg/private/frames",
                "render_meta_path": "file:///srv/edmg/private/render.json",
                "nested": [
                    "outputs/videos/public.mp4",
                    "/srv/edmg/private/final.mp4",
                    r"D:\private\final.mp4",
                    {"logical_id": "asset-123", "source_path": r"\\server\share\secret.bin"},
                ],
                "logical_video": "outputs/videos/public.mp4",
            },
            "settings": {"profile_width": 512, "profile_height": 512},
        }
    )

    qualification = public.pop("qualification")
    assert qualification["ready"] is False
    assert qualification["route"] == "unknown"
    assert qualification["blockers"] == ["Render preflight is incomplete or has an unknown route."]
    assert public == {
        "ok": True,
        "model_id": "local_sd15_tensorrt_bundle",
        "cache": {
            "nested": ["outputs/videos/public.mp4", {"logical_id": "asset-123"}],
            "logical_video": "outputs/videos/public.mp4",
        },
        "settings": {"profile_width": 512, "profile_height": 512},
    }


def test_legacy_tensorrt_deforum_job_executes_canonical_video_path(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    job = jobs.create(
        project.id,
        "tensorrt_deforum",
        {
            "model_id": "local_sd15_tensorrt_bundle",
            "deforum_settings": {"zoom": "0:(1.0)"},
        },
    )
    calls: list[tuple[str, str, dict]] = []
    absolute_video = str((tmp_path / "outputs" / "videos" / "canonical.mp4").resolve())

    def fake_run_internal_video(project_id: str, job_id: str, payload: dict) -> dict:
        calls.append((project_id, job_id, dict(payload)))
        return {
            "ok": True,
            "mode": "tensorrt",
            "video": "outputs/videos/canonical.mp4",
            "video_abs": absolute_video,
        }

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module, "_run_internal_video", fake_run_internal_video)

    app_module._execute_job(job)

    completed = jobs.get(project.id, job.id)
    assert completed is not None
    assert completed.status == "succeeded"
    assert calls[0][0:2] == (project.id, job.id)
    assert calls[0][2]["render_mode"] == "tensorrt"
    assert completed.result == {
        "ok": True,
        "mode": "tensorrt",
        "video": "outputs/videos/canonical.mp4",
        "compatibility_route": "tensorrt-deforum",
        "execution_mode": "canonical_tensorrt_keyframe_video",
        "legacy_deforum_schedule_applied": False,
        "output_path": "outputs/videos/canonical.mp4",
    }
    jobs.close()


def test_legacy_tensorrt_deforum_job_discards_untrusted_persisted_paths(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    untrusted_path = tmp_path / "Old client supplied path"
    untrusted_path.mkdir()
    job = jobs.create(
        project.id,
        "tensorrt_deforum",
        {
            "model_id": str(untrusted_path),
            "model_path": str(untrusted_path),
            "bundle_path": str(untrusted_path),
        },
    )
    calls: list[dict] = []

    def fake_run_internal_video(_project_id: str, _job_id: str, payload: dict) -> dict:
        calls.append(dict(payload))
        return {"ok": True, "video": "outputs/videos/canonical.mp4", "mode": "tensorrt"}

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module, "_run_internal_video", fake_run_internal_video)

    app_module._execute_job(job)

    completed = jobs.get(project.id, job.id)
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.payload["model_id"] == "local_sd15_tensorrt_bundle"
    assert completed.payload["render_mode"] == "tensorrt"
    assert "model_path" not in completed.payload
    assert "bundle_path" not in completed.payload
    assert calls == [completed.payload]
    jobs.close()


def test_legacy_tensorrt_video_uses_creative_fallback_when_project_has_no_saved_plan(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    project.meta.pop("last_plan", None)
    store.save(project)
    jobs = JobStore(store.projects_dir)
    job = jobs.create(project.id, "tensorrt_deforum", {"model_id": "local_sd15_tensorrt_bundle"})
    bundle_path = tmp_path / "verified-tensorrt-bundle"
    bundle_path.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(
        app_module,
        "_internal_render_preflight_data",
        lambda _project_id, _payload: {
            "ok": True,
            "mode": "tensorrt",
            "model_id": "local_sd15_tensorrt_bundle",
            "model_path": str(bundle_path),
            "estimated_frames": 4,
            "estimated_keyframes": 1,
        },
    )
    monkeypatch.setattr(
        app_module,
        "_creative_direction_fallback_variant",
        lambda _proj, _variant_index: {
            "index": 0,
            "duration_s": 2.0,
            "_fallback_plan_source": "creative_direction_fallback",
            "scenes": [{"start_s": 0.0, "end_s": 2.0, "prompt": "fallback neon skyline"}],
        },
    )

    def fake_render_tensorrt_video_variant(**kwargs):
        captured.update(kwargs)
        output = store.project_dir(project.id) / "outputs" / "videos" / "legacy-fallback.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return output

    monkeypatch.setattr(app_module, "render_tensorrt_video_variant", fake_render_tensorrt_video_variant)

    result = app_module._run_internal_video(
        project.id,
        job.id,
        {"model_id": "local_sd15_tensorrt_bundle", "render_mode": "tensorrt", "variant_index": 0},
    )

    assert Path(result["video"]) == Path("outputs/videos/legacy-fallback.mp4")
    assert captured["variant"]["_fallback_plan_source"] == "creative_direction_fallback"
    assert captured["scenes"][0]["prompt"] == "fallback neon skyline"
    jobs.close()


def test_legacy_tensorrt_deforum_job_preserves_canonical_cancellation(tmp_path, monkeypatch) -> None:
    store, project = _make_render_project(tmp_path)
    jobs = JobStore(store.projects_dir)
    job = jobs.create(
        project.id,
        "tensorrt_deforum",
        {"model_id": "local_sd15_tensorrt_bundle"},
    )

    def fake_canceled_render(project_id: str, job_id: str, _payload: dict) -> dict:
        current = jobs.get(project_id, job_id)
        assert current is not None
        current.status = "canceled"
        current.result = {"partial": "outputs/videos/partial.mp4"}
        jobs.save(current)
        raise app_module.JobCanceled("TensorRT render canceled")

    monkeypatch.setattr(app_module, "jobs", jobs)
    monkeypatch.setattr(app_module, "_run_internal_video", fake_canceled_render)

    app_module._execute_job(job)

    completed = jobs.get(project.id, job.id)
    assert completed is not None
    assert completed.status == "canceled"
    assert completed.result == {
        "partial": "outputs/videos/partial.mp4",
    }
    jobs.close()


def test_tensorrt_deforum_route_is_deprecated_in_openapi() -> None:
    operation = app_module.app.openapi()["paths"][
        "/v1/projects/{project_id}/render/tensorrt-deforum"
    ]["post"]

    assert operation["deprecated"] is True


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
    assert len(refined.split()) <= internal_video.CLIP_SAFE_RENDER_PROMPT_MAX_WORDS

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


def test_svd_low_vram_memory_safety_preserves_steps_and_warns() -> None:
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
    assert safe.temporal_steps == 20
    assert any("6 GB CUDA SVD safety" in warning for warning in warnings)
    assert any("Inference steps are preserved" in warning for warning in warnings)


def test_ltx_low_vram_memory_safety_enables_supported_cpu_offload() -> None:
    settings = InternalVideoSettings(
        temporal_mode="video_model",
        video_model_engine="ltx_25",
        video_model_id="ltx_25_distilled_t2v_22b_bf16",
        video_model_max_frames_per_scene=25,
        video_model_decode_chunk_size=8,
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
    assert safe.video_model_decode_chunk_size == 8
    assert safe.video_model_dtype == "fp8"
    assert any("6 GB CUDA LTX-2.5 safety" in warning for warning in warnings)
    assert any("host-memory budget" in warning for warning in warnings)


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


@pytest.mark.parametrize(
    ("engine", "device", "vram_gb"),
    [
        ("svd", "cuda", 6.0),
        ("animatediff", "cuda", 6.0),
        ("svd", "cuda", 8.0),
        ("animatediff", "cuda", 8.0),
        ("svd", "cuda", 12.0),
        ("svd", "cpu", 0.0),
    ],
)
def test_parseq_steps_are_not_reduced_by_low_vram_policy(
    monkeypatch,
    engine: str,
    device: str,
    vram_gb: float,
) -> None:
    monkeypatch.setattr(internal_video, "_cuda_total_vram_gb", lambda _device: vram_gb)

    cap = internal_video._video_model_temporal_step_cap(  # noqa: SLF001 - pure policy helper
        engine=engine,
        device=device,
    )
    effective = internal_video._apply_video_model_temporal_step_cap(  # noqa: SLF001
        15,
        cap,
    )

    assert cap is None
    assert effective == 15


def test_internal_negative_prompt_rejects_spatial_storyboard_layouts() -> None:
    settings = InternalVideoSettings(negative_prompt="blurry, watermark")
    context = internal_video._build_unified_deforum_context(  # noqa: SLF001 - pure prompt helper
        scenes=[],
        timeline=None,
        variant=None,
        settings=settings,
        fps=24,
    )

    negative = internal_video._negative_prompt_for_frame(  # noqa: SLF001 - pure prompt helper
        frame_idx=0,
        settings=settings,
        deforum_context=context,
    )

    assert "collage" in negative
    assert "contact sheet" in negative
    assert "split screen" in negative
    assert "multi-panel composition" in negative
    assert "storyboard sheet" in negative
    assert "duplicate subject" in negative
    assert "multiple people" in negative
    assert "extra person" in negative
    assert "cloned subject" in negative


def test_keyframe_continuity_scope_controls_authored_scene_boundary_reset() -> None:
    sentinel = object()

    assert (
        internal_video._keyframe_continuity_source(  # noqa: SLF001 - pure continuity helper
            sentinel,
            previous_scene_index=3,
            scene_index=3,
        )
        is sentinel
    )
    assert (
        internal_video._keyframe_continuity_source(  # noqa: SLF001 - pure continuity helper
            sentinel,
            previous_scene_index=3,
            scene_index=4,
        )
        is None
    )
    assert (
        internal_video._keyframe_continuity_source(  # noqa: SLF001 - pure continuity helper
            sentinel,
            previous_scene_index=3,
            scene_index=4,
            keyframe_continuity_mode="project",
        )
        is sentinel
    )


def test_keyframe_continuity_mode_changes_render_cache_signature(tmp_path: Path) -> None:
    common = {
        "variant_index": 0,
        "model_dir": tmp_path / "model",
        "variant": {"prompts": {"0": "cinematic guitarist"}},
        "scenes": [{"start_s": 0.0, "end_s": 5.0, "prompt": "cinematic guitarist"}],
        "timeline": None,
    }

    scene_tag = internal_video._build_work_tag(  # noqa: SLF001 - deterministic cache contract
        **common,
        settings=InternalVideoSettings(keyframe_continuity_mode="scene"),
    )
    project_tag = internal_video._build_work_tag(  # noqa: SLF001 - deterministic cache contract
        **common,
        settings=InternalVideoSettings(keyframe_continuity_mode="project"),
    )

    assert scene_tag != project_tag


def test_cinematic_both_anchor_mode_blends_opening_and_ending_frames() -> None:
    frames = [Image.new("RGB", (8, 8), (0, 0, 0)) for _ in range(8)]
    start = Image.new("RGB", (8, 8), (255, 0, 0))
    end = Image.new("RGB", (8, 8), (0, 0, 255))

    anchored = internal_video._apply_video_anchor_frames(  # noqa: SLF001 - continuity contract
        frames,
        anchor_mode="both",
        start_img=start,
        end_img=end,
        anchor_strength=0.2,
    )

    assert internal_video._normalize_video_anchor_mode("both") == "both"  # noqa: SLF001
    assert anchored[0].getpixel((0, 0))[0] > 0
    assert anchored[0].getpixel((0, 0))[2] == 0
    assert anchored[-1].getpixel((0, 0))[2] > 0
    assert anchored[-1].getpixel((0, 0))[0] == 0
    assert anchored[len(anchored) // 2].getpixel((0, 0)) == (0, 0, 0)


def test_storyboard_windows_distinguish_technical_continuity_from_authored_dissolve() -> None:
    windows = internal_video._storyboard_scene_windows(  # noqa: SLF001 - motion-plan contract
        scenes=[
            {"start_s": 0.0, "end_s": 5.0, "prompt": "arrival"},
            {
                "start_s": 5.0,
                "end_s": 10.0,
                "prompt": "departure",
                "transition_cue": "match dissolve",
            },
        ],
        duration_s=10.0,
        settings=InternalVideoSettings(
            motion_strategy="storyboard_full_motion",
            storyboard_shot_max_s=2.5,
        ),
    )

    assert [window["_storyboard_transition"] for window in windows] == [
        "opening",
        "technical_continue",
        "dissolve",
        "technical_continue",
    ]


def test_authored_scene_dissolve_blends_without_changing_frame_size() -> None:
    previous = Image.new("RGB", (8, 8), (255, 0, 0))
    current = Image.new("RGB", (8, 8), (0, 0, 255))

    dissolved = internal_video._blend_storyboard_scene_boundary(  # noqa: SLF001
        previous,
        current,
        transition="dissolve",
    )
    cut = internal_video._blend_storyboard_scene_boundary(  # noqa: SLF001
        previous,
        current,
        transition="cut",
    )

    assert dissolved.size == current.size
    assert dissolved.getpixel((0, 0)) == (127, 0, 127)
    assert cut.getpixel((0, 0)) == (0, 0, 255)


def test_video_motion_score_reads_reactive_camel_case_sections_and_time_events() -> None:
    score = internal_video.video_model_scene_motion_score(
        scene={"energy": 0.2},
        timeline={
            "reactive_lab": {
                "sections": [
                    {"startTime": 0.0, "endTime": 4.0, "avgEnergy": 0.8},
                ],
                "beat_markers": [
                    {"time": 0.5},
                    {"time": 1.5},
                    {"time": 2.5},
                ],
            }
        },
        start_s=0.0,
        end_s=4.0,
        duration_s=4.0,
        settings=InternalVideoSettings(video_model_motion_score_mode="auto"),
    )

    assert score["source"] == "scene+timeline+events"
    assert score["energy"] > 0.59
    assert score["event_density"] > 0
    assert score["motion_score"] >= 5


def test_release_cached_internal_pipelines_moves_cuda_previews_to_cpu(monkeypatch) -> None:
    class FakePipeline:
        def __init__(self) -> None:
            self.devices: list[str] = []

        def to(self, device: str):
            self.devices.append(device)
            return self

    shared = FakePipeline()
    inpaint = FakePipeline()
    pipes = SimpleNamespace(
        txt2img=shared,
        img2img=shared,
        inpaint=inpaint,
        device="cuda",
    )
    cleanup_devices: list[str] = []
    monkeypatch.setattr(internal_video, "_cleanup_torch_cuda", cleanup_devices.append)

    internal_video._PipelineCache.clear()  # noqa: SLF001 - cache-release contract
    internal_video._PipelineCache.set(("preview", "cuda", "video"), pipes)  # noqa: SLF001
    try:
        released = internal_video.release_cached_internal_pipelines()
    finally:
        internal_video._PipelineCache.clear()  # noqa: SLF001

    assert released == 1
    assert shared.devices == ["cpu"]
    assert inpaint.devices == ["cpu"]
    assert cleanup_devices == ["cuda"]
    assert internal_video._PipelineCache.get(("preview", "cuda", "video")) is None  # noqa: SLF001


def test_group_ltx_scene_work_items_assigns_whole_scenes_per_device() -> None:
    items = [
        internal_video._VideoModelSceneWorkItem(
            global_scene_index=index,
            source_scene_index=source_scene_index,
            shot_index=shot_index,
            shot_count=2 if source_scene_index == 0 else 1,
            start_s=float(index),
            end_s=float(index + 1),
            start_f=index * 2,
            end_f=(index * 2) + 2,
            scene_frame_count=2,
            adapter_frames=9,
            authored_scene_boundary=source_scene_index > 0 and shot_index == 0,
            transition_kind="technical_continue" if shot_index else "opening",
            continuity_scope="scene",
            continuity_anchor_source="generated_keyframe",
            schedule_frame=index * 2,
            prompt=f"prompt-{index}",
            negative_prompt="neg",
            prompt_for_model=f"prompt-{index}",
            score_info={"motion_score": 4},
            motion_bucket_id=127,
            seed=100 + index,
            cfg_for_scene=7.0,
            steps_for_scene=8,
            scheduled_steps=8,
            noise_aug_strength=0.02,
            shot_anchor_strength=0.2,
            adapter_w=512,
            adapter_h=512,
            adapter_note=None,
            anchor_mode="start",
            anchorless=False,
            start_anchor_img=None,
            end_anchor_img=None,
            init_img=None,
        )
        for index, (source_scene_index, shot_index) in enumerate(((0, 0), (0, 1), (1, 0), (2, 0)))
    ]

    groups = internal_video._group_ltx_scene_work_items(items, device_ids=(0, 1))

    assert [(group.source_scene_index, group.device_id) for group in groups] == [(0, 0), (1, 1), (2, 1)]
    assert [item.global_scene_index for item in groups[0].items] == [0, 1]
    assert [item.global_scene_index for item in groups[1].items] == [2]
    assert [item.global_scene_index for item in groups[2].items] == [3]


def test_generate_video_model_scene_result_uses_previous_frame_only_for_technical_continuity(monkeypatch) -> None:
    base_anchor = Image.new("RGB", (32, 32), (10, 10, 10))
    previous_frame = Image.new("RGB", (32, 32), (200, 10, 10))
    captured_init_images: list[Image.Image | None] = []

    def fake_generate_video_model_frames(**kwargs):
        init_image = kwargs.get("init_image")
        captured_init_images.append(init_image.copy() if init_image is not None else None)
        return [Image.new("RGB", (32, 32), (0, 64, 128)) for _ in range(9)]

    monkeypatch.setattr(internal_video, "generate_video_model_frames", fake_generate_video_model_frames)
    monkeypatch.setattr(
        internal_video,
        "analyze_motion_images",
        lambda images, fps: {
            "status": "pass",
            "perceptually_unique_frames": len(images),
            "frame_count": len(images),
            "meaningful_transition_count": max(1, len(images) - 1),
            "frozen_pair_ratio": 0.0,
        },
    )

    common = dict(
        source_scene_index=0,
        shot_index=0,
        shot_count=1,
        start_s=0.0,
        end_s=4.0,
        start_f=0,
        end_f=8,
        scene_frame_count=8,
        adapter_frames=9,
        continuity_scope="scene",
        continuity_anchor_source="generated_keyframe",
        schedule_frame=0,
        prompt="prompt",
        negative_prompt="neg",
        prompt_for_model="prompt",
        score_info={"motion_score": 4},
        motion_bucket_id=127,
        seed=123,
        cfg_for_scene=7.0,
        steps_for_scene=8,
        scheduled_steps=8,
        noise_aug_strength=0.02,
        shot_anchor_strength=0.2,
        adapter_w=32,
        adapter_h=32,
        adapter_note=None,
        anchor_mode="start",
        anchorless=False,
        start_anchor_img=base_anchor,
        end_anchor_img=base_anchor,
        init_img=base_anchor,
    )

    technical = internal_video._VideoModelSceneWorkItem(
        global_scene_index=0,
        authored_scene_boundary=False,
        transition_kind="technical_continue",
        **common,
    )
    authored = internal_video._VideoModelSceneWorkItem(
        global_scene_index=1,
        authored_scene_boundary=True,
        transition_kind="dissolve",
        **common,
    )
    settings = InternalVideoSettings(video_model_dtype="auto")

    first = internal_video._generate_video_model_scene_result(
        work_item=technical,
        engine="ltx_25",
        video_model_path=Path("video-model"),
        model_dir=Path("base-model"),
        device="cuda:0",
        settings=settings,
        workspace=Path("workspace"),
        cancel_check_fn=None,
        initial_previous_frame=previous_frame,
    )
    second = internal_video._generate_video_model_scene_result(
        work_item=authored,
        engine="ltx_25",
        video_model_path=Path("video-model"),
        model_dir=Path("base-model"),
        device="cuda:0",
        settings=settings,
        workspace=Path("workspace"),
        cancel_check_fn=None,
        initial_previous_frame=previous_frame,
    )

    assert captured_init_images[0] is not None
    assert captured_init_images[0].getpixel((0, 0)) == previous_frame.getpixel((0, 0))
    assert captured_init_images[1] is not None
    assert captured_init_images[1].getpixel((0, 0)) == base_anchor.getpixel((0, 0))
    assert first.native_motion_report["continuity_anchor_source"] == "previous_native_motion_frame"
    assert second.native_motion_report["continuity_anchor_source"] == "generated_keyframe"


def test_run_ltx_scene_group_preserves_in_group_anchor_chain(monkeypatch, tmp_path: Path) -> None:
    seeds: list[int] = []
    init_pixels: list[tuple[int, int, int] | None] = []

    def fake_generate_video_model_frames(**kwargs):
        seeds.append(kwargs["seed"])
        init_image = kwargs.get("init_image")
        init_pixels.append(None if init_image is None else init_image.getpixel((0, 0)))
        color = (kwargs["seed"] % 255, 40, 90)
        return [Image.new("RGB", (16, 16), color) for _ in range(kwargs["num_frames"])]

    monkeypatch.setattr(internal_video, "generate_video_model_frames", fake_generate_video_model_frames)
    monkeypatch.setattr(
        internal_video,
        "analyze_motion_images",
        lambda images, fps: {
            "status": "pass",
            "perceptually_unique_frames": len(images),
            "frame_count": len(images),
            "meaningful_transition_count": max(1, len(images) - 1),
            "frozen_pair_ratio": 0.0,
        },
    )

    anchor = Image.new("RGB", (16, 16), (5, 5, 5))
    item0 = internal_video._VideoModelSceneWorkItem(
        global_scene_index=0,
        source_scene_index=0,
        shot_index=0,
        shot_count=2,
        start_s=0.0,
        end_s=4.0,
        start_f=0,
        end_f=8,
        scene_frame_count=8,
        adapter_frames=9,
        authored_scene_boundary=False,
        transition_kind="opening",
        continuity_scope="scene",
        continuity_anchor_source="generated_keyframe",
        schedule_frame=0,
        prompt="prompt",
        negative_prompt="neg",
        prompt_for_model="prompt",
        score_info={"motion_score": 4},
        motion_bucket_id=127,
        seed=11,
        cfg_for_scene=7.0,
        steps_for_scene=8,
        scheduled_steps=8,
        noise_aug_strength=0.02,
        shot_anchor_strength=0.2,
        adapter_w=16,
        adapter_h=16,
        adapter_note=None,
        anchor_mode="start",
        anchorless=False,
        start_anchor_img=anchor,
        end_anchor_img=anchor,
        init_img=anchor,
    )
    item1 = internal_video._VideoModelSceneWorkItem(
        global_scene_index=1,
        source_scene_index=0,
        shot_index=1,
        shot_count=2,
        start_s=4.0,
        end_s=8.0,
        start_f=8,
        end_f=16,
        scene_frame_count=8,
        adapter_frames=9,
        authored_scene_boundary=False,
        transition_kind="technical_continue",
        continuity_scope="scene",
        continuity_anchor_source="generated_keyframe",
        schedule_frame=8,
        prompt="prompt",
        negative_prompt="neg",
        prompt_for_model="prompt",
        score_info={"motion_score": 4},
        motion_bucket_id=127,
        seed=22,
        cfg_for_scene=7.0,
        steps_for_scene=8,
        scheduled_steps=8,
        noise_aug_strength=0.02,
        shot_anchor_strength=0.2,
        adapter_w=16,
        adapter_h=16,
        adapter_note=None,
        anchor_mode="start",
        anchorless=False,
        start_anchor_img=anchor,
        end_anchor_img=anchor,
        init_img=anchor,
    )
    group = internal_video._LtxSceneGroup(source_scene_index=0, device_id=1, items=(item0, item1))

    source_scene_index, results = internal_video._run_ltx_scene_group(
        group,
        engine="ltx_25",
        video_model_path=tmp_path / "video_model",
        model_dir=tmp_path / "base_model",
        settings=InternalVideoSettings(video_model_dtype="auto"),
        group_workspace=tmp_path / "workspace",
        cancel_check_fn=None,
    )

    assert source_scene_index == 0
    assert len(results) == 2
    assert init_pixels[0] == anchor.getpixel((0, 0))
    assert init_pixels[1] == results[0].last_frame.getpixel((0, 0))
    assert results[1].native_motion_report["continuity_anchor_source"] == "previous_native_motion_frame"


def test_run_ltx_scene_group_propagates_cancellation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        internal_video,
        "generate_video_model_frames",
        lambda **kwargs: [Image.new("RGB", (16, 16), (1, 2, 3)) for _ in range(kwargs["num_frames"])],
    )
    monkeypatch.setattr(
        internal_video,
        "analyze_motion_images",
        lambda images, fps: {
            "status": "pass",
            "perceptually_unique_frames": len(images),
            "frame_count": len(images),
            "meaningful_transition_count": max(1, len(images) - 1),
            "frozen_pair_ratio": 0.0,
        },
    )
    item = internal_video._VideoModelSceneWorkItem(
        global_scene_index=0,
        source_scene_index=0,
        shot_index=0,
        shot_count=1,
        start_s=0.0,
        end_s=4.0,
        start_f=0,
        end_f=8,
        scene_frame_count=8,
        adapter_frames=9,
        authored_scene_boundary=False,
        transition_kind="opening",
        continuity_scope="scene",
        continuity_anchor_source="generated_keyframe",
        schedule_frame=0,
        prompt="prompt",
        negative_prompt="neg",
        prompt_for_model="prompt",
        score_info={"motion_score": 4},
        motion_bucket_id=127,
        seed=11,
        cfg_for_scene=7.0,
        steps_for_scene=8,
        scheduled_steps=8,
        noise_aug_strength=0.02,
        shot_anchor_strength=0.2,
        adapter_w=16,
        adapter_h=16,
        adapter_note=None,
        anchor_mode="start",
        anchorless=False,
        start_anchor_img=Image.new("RGB", (16, 16), (0, 0, 0)),
        end_anchor_img=Image.new("RGB", (16, 16), (0, 0, 0)),
        init_img=Image.new("RGB", (16, 16), (0, 0, 0)),
    )
    group = internal_video._LtxSceneGroup(source_scene_index=0, device_id=0, items=(item,))

    with pytest.raises(RuntimeError, match="cancelled"):
        internal_video._run_ltx_scene_group(
            group,
            engine="ltx_25",
            video_model_path=tmp_path / "video_model",
            model_dir=tmp_path / "base_model",
            settings=InternalVideoSettings(video_model_dtype="auto"),
            group_workspace=tmp_path / "workspace",
            cancel_check_fn=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
        )


def test_run_ltx_device_lane_serializes_groups_and_stops_after_failure(monkeypatch, tmp_path: Path) -> None:
    groups = (
        internal_video._LtxSceneGroup(source_scene_index=0, device_id=2, items=()),
        internal_video._LtxSceneGroup(source_scene_index=1, device_id=2, items=()),
        internal_video._LtxSceneGroup(source_scene_index=2, device_id=2, items=()),
    )
    started: list[int] = []

    def fake_run_group(group, **kwargs):
        started.append(group.source_scene_index)
        if group.source_scene_index == 1:
            raise RuntimeError("lane failure")
        return group.source_scene_index, ()

    monkeypatch.setattr(internal_video, "_run_ltx_scene_group", fake_run_group)

    with pytest.raises(RuntimeError, match="lane failure"):
        internal_video._run_ltx_device_lane(
            groups,
            engine="ltx_25",
            video_model_path=tmp_path / "video_model",
            model_dir=tmp_path / "base_model",
            settings=InternalVideoSettings(video_model_dtype="auto"),
            lane_workspace=tmp_path / "lane",
            cancel_check_fn=None,
        )

    assert started == [0, 1]
